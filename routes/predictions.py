"""routes/predictions.py — core predictions, watchlist, history, profile, AI analyst."""

import csv
import io
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

from flask import render_template, request, jsonify, redirect, url_for, Response
from flask_login import login_required, current_user

from extensions import db
from models import (
    User, PredictionHistory, WatchlistItem, PredictionAccuracy, FREE_DAILY_LIMIT,
)
from utils import consume_quota, _try_azure_download, VALID_INTERVALS, PRO_TICKERS

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")


def register_prediction_routes(app, metrics):
    """metrics: shared dict {"predictions": 0, "total_latency": 0.0}"""

    from predictor import run_prediction, ml_signal

    @app.route("/", methods=["GET"])
    def home():
        if current_user.is_authenticated:
            return render_template("index.html")
        return render_template("landing.html")

    @app.route("/predict", methods=["POST"])
    @login_required
    def predict():
        ticker   = request.form.get("ticker", "").upper().strip()
        interval = request.form.get("interval", "1d").strip()
        if interval not in VALID_INTERVALS:
            interval = "1d"
        if not ticker:
            return render_template("index.html", error="Please enter a stock ticker symbol.",
                                   interval=interval)
        if len(ticker) > 10 or not ticker.replace(".", "").replace("-", "").isalpha():
            return render_template("index.html",
                                   error=f'"{ticker}" is not a valid ticker.',
                                   interval=interval)
        if not consume_quota(current_user):
            return render_template("index.html",
                                   error=f"You've used all {FREE_DAILY_LIMIT} free predictions for today. "
                                         "Upgrade to Pro for unlimited access.",
                                   show_upgrade=True, interval=interval)
        try:
            _try_azure_download(ticker, interval)
            result = run_prediction(ticker, interval)
            try:
                ph = PredictionHistory(
                    user_id=current_user.id, ticker=ticker, interval=interval,
                    current_price=result["current_price"],
                    lr_pred=result["lr_pred"], rf_pred=result["rf_pred"],
                    direction=result["direction"], confidence=result["confidence"],
                )
                db.session.add(ph)
                db.session.commit()
            except Exception:
                db.session.rollback()
            return render_template("result.html", **result)
        except ValueError as e:
            return render_template("index.html", error=str(e), interval=interval)
        except FileNotFoundError:
            return render_template("index.html",
                                   error=f'No trained model for "{ticker}". '
                                         'Supported: AAPL, MSFT, TSLA, NVDA, GOOGL, AMZN, META, QQQ, DIA, NDX.',
                                   interval=interval)
        except Exception:
            return render_template("index.html",
                                   error=f'Could not fetch data for "{ticker}". '
                                         'Please check the symbol and try again.',
                                   interval=interval)

    @app.route("/market")
    @login_required
    def market():
        return render_template("market.html")

    @app.route("/watchlist")
    @login_required
    def watchlist():
        items = WatchlistItem.query.filter_by(user_id=current_user.id).order_by(
            WatchlistItem.added_at).all()
        return render_template("watchlist.html", watchlist=[i.ticker for i in items])

    @app.route("/api/watchlist/add", methods=["POST"])
    @login_required
    def watchlist_add():
        ticker = (request.get_json() or {}).get("ticker", "").upper().strip()
        if not ticker or len(ticker) > 10:
            return jsonify({"ok": False, "error": "Invalid ticker"}), 400
        try:
            db.session.add(WatchlistItem(user_id=current_user.id, ticker=ticker))
            db.session.commit()
            return jsonify({"ok": True})
        except Exception:
            db.session.rollback()
            return jsonify({"ok": False, "error": "Already in watchlist"}), 409

    @app.route("/api/watchlist/remove", methods=["POST"])
    @login_required
    def watchlist_remove():
        ticker = (request.get_json() or {}).get("ticker", "").upper().strip()
        WatchlistItem.query.filter_by(user_id=current_user.id, ticker=ticker).delete()
        db.session.commit()
        return jsonify({"ok": True})

    @app.route("/api/watchlist/signals")
    @login_required
    def watchlist_signals():
        items   = WatchlistItem.query.filter_by(user_id=current_user.id).all()
        tickers = [i.ticker for i in items]
        if not tickers:
            return jsonify({})
        def _get(ticker):
            sig   = ml_signal(ticker, "1d")
            price = sig.get("current_price", 0)
            lr    = sig.get("lr_pred", price)
            chg   = round((lr - price) / price * 100, 2) if price else 0
            return ticker, {"price": price, "chg": chg,
                            "dir": sig.get("action", "HOLD"), "conf": sig.get("confidence", 0)}
        with ThreadPoolExecutor(max_workers=min(len(tickers), 6)) as ex:
            results = dict(ex.map(lambda t: _get(t), tickers))
        return jsonify(results)

    @app.route("/history")
    @login_required
    def history():
        records = (PredictionHistory.query
                   .filter_by(user_id=current_user.id)
                   .order_by(PredictionHistory.predicted_at.desc())
                   .limit(100).all())
        return render_template("history.html", records=records)

    @app.route("/history/export")
    @login_required
    def history_export():
        records = (PredictionHistory.query.filter_by(user_id=current_user.id)
                   .order_by(PredictionHistory.predicted_at.desc()).all())
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Date", "Ticker", "Interval", "Current Price",
                         "LR Pred", "RF Pred", "Direction", "Confidence"])
        for r in records:
            writer.writerow([
                r.predicted_at.strftime("%Y-%m-%d %H:%M") if r.predicted_at else "",
                r.ticker, r.interval, round(r.current_price, 4), round(r.lr_pred, 4),
                round(r.rf_pred, 4), r.direction, round(r.confidence, 1),
            ])
        output.seek(0)
        return Response(output.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": "attachment; filename=bulllogic_history.csv"})

    @app.route("/profile")
    @login_required
    def profile():
        total = PredictionHistory.query.filter_by(user_id=current_user.id).count()
        return render_template("profile.html", total_predictions=total)

    # ── API predict ────────────────────────────────────────────────────────────

    @app.route("/api/predict/", methods=["GET"])
    def api_predict_empty():
        return jsonify({"status": "error",
                        "message": "Please provide a ticker, e.g. /api/predict/AAPL"}), 400

    @app.route("/api/predict/<ticker>", methods=["GET"])
    def api_predict(ticker):
        if not current_user.is_authenticated:
            return jsonify({"status": "error", "message": "Authentication required."}), 401
        if not consume_quota(current_user):
            return jsonify({"status": "error",
                            "message": f"Daily limit of {FREE_DAILY_LIMIT} predictions reached."}), 429
        interval = request.args.get("interval", "1d")
        if interval not in VALID_INTERVALS:
            interval = "1d"
        t0 = time.time()
        try:
            _try_azure_download(ticker.upper(), interval)
            result = run_prediction(ticker.upper(), interval)
            for key in ["chart_dates", "chart_prices", "chart_sma7", "chart_sma21"]:
                result.pop(key, None)
            metrics["predictions"]   += 1
            metrics["total_latency"] += time.time() - t0
            return jsonify({"status": "success", "data": result})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 400

    @app.route("/api/mtf/<ticker>", methods=["GET"])
    @login_required
    def api_mtf(ticker):
        if not current_user.is_pro:
            return jsonify({"ok": False, "error": "Pro required"}), 403
        ticker = ticker.upper()
        try:
            import yfinance as yf
            _try_azure_download(ticker, "1d")
            _try_azure_download(ticker, "1h")
            with ThreadPoolExecutor(max_workers=2) as ex:
                f1d = ex.submit(run_prediction, ticker, "1d")
                f1h = ex.submit(run_prediction, ticker, "1h")
                r1d, r1h = f1d.result(), f1h.result()
            hist = yf.download(ticker, period="5d", interval="1d",
                               auto_adjust=True, progress=False)
            if hasattr(hist.columns, "get_level_values"):
                hist.columns = hist.columns.get_level_values(0)
            prev_close = round(float(hist["Close"].iloc[-2]), 2) if len(hist) >= 2 else 0.0
            return jsonify({
                "ok": True, "ticker": ticker, "prev_close": prev_close,
                "1d": {"pred": r1d["primary_pred"], "direction": r1d["direction"],
                       "change_pct": r1d["change_pct"], "price_change": r1d["price_change"],
                       "confidence": r1d["confidence"]},
                "1h": {"pred": r1h["primary_pred"], "direction": r1h["direction"],
                       "change_pct": r1h["change_pct"], "price_change": r1h["price_change"],
                       "confidence": r1h["confidence"]},
            })
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 400

    @app.route("/api/pro-signals")
    @login_required
    def api_pro_signals():
        interval = request.args.get("interval", "1d")
        if interval not in VALID_INTERVALS:
            interval = "1d"
        def _scan(ticker):
            try:
                sig = ml_signal(ticker, interval)
                return ticker, {"ticker": ticker, "action": sig.get("action", "HOLD"),
                                "price": sig.get("current_price", 0),
                                "confidence": sig.get("confidence", 0),
                                "rsi": sig.get("rsi", 50)}
            except Exception:
                return ticker, {"ticker": ticker, "action": "HOLD", "price": 0,
                                "confidence": 0, "rsi": 50}
        with ThreadPoolExecutor(max_workers=5) as ex:
            results = dict(ex.map(lambda t: _scan(t), PRO_TICKERS))
        return jsonify({"ok": True, "interval": interval, "signals": results})

    # ── Accuracy ───────────────────────────────────────────────────────────────

    @app.route("/api/accuracy/check", methods=["POST"])
    @login_required
    def api_accuracy_check():
        import yfinance as yf
        import pandas as pd
        yesterday = date.today() - timedelta(days=1)
        unchecked = (PredictionHistory.query
                     .outerjoin(PredictionAccuracy,
                                PredictionHistory.id == PredictionAccuracy.prediction_id)
                     .filter(PredictionHistory.user_id == current_user.id,
                             PredictionHistory.interval == "1d",
                             db.func.date(PredictionHistory.predicted_at) <= yesterday,
                             PredictionAccuracy.id == None)
                     .limit(20).all())
        checked = 0
        for pred in unchecked:
            try:
                hist = yf.download(pred.ticker, period="5d", interval="1d",
                                   auto_adjust=True, progress=False)
                if isinstance(hist.columns, pd.MultiIndex):
                    hist.columns = hist.columns.get_level_values(0)
                if len(hist) < 1:
                    continue
                actual = float(hist["Close"].iloc[-1])
                dir_ok = (pred.direction.lower() == "up" and actual > pred.current_price) or \
                         (pred.direction.lower() == "down" and actual <= pred.current_price)
                pct_err = abs(pred.lr_pred - actual) / actual * 100
                db.session.add(PredictionAccuracy(
                    prediction_id=pred.id, actual_price=round(actual, 4),
                    direction_ok=dir_ok, pct_error=round(pct_err, 2),
                    checked_at=datetime.utcnow(),
                ))
                checked += 1
            except Exception:
                pass
        db.session.commit()
        return jsonify({"ok": True, "checked": checked})

    @app.route("/api/accuracy")
    @login_required
    def api_accuracy():
        rows = (db.session.query(PredictionAccuracy, PredictionHistory)
                .join(PredictionHistory, PredictionAccuracy.prediction_id == PredictionHistory.id)
                .filter(PredictionHistory.user_id == current_user.id)
                .order_by(PredictionHistory.predicted_at.desc())
                .limit(200).all())
        if not rows:
            return jsonify({"ok": True, "count": 0, "direction_accuracy": None,
                            "avg_pct_error": None, "recent": []})
        total   = len(rows)
        dir_ok  = sum(1 for a, _ in rows if a.direction_ok)
        avg_err = sum(a.pct_error for a, _ in rows if a.pct_error is not None) / total
        recent  = [{"ticker": ph.ticker,
                    "date": ph.predicted_at.strftime("%Y-%m-%d") if ph.predicted_at else "",
                    "predicted": round(ph.lr_pred, 2),
                    "actual": round(acc.actual_price, 2) if acc.actual_price else None,
                    "dir_ok": acc.direction_ok,
                    "pct_err": round(acc.pct_error, 2) if acc.pct_error else None,
                    } for acc, ph in rows[:20]]
        return jsonify({"ok": True, "count": total,
                        "direction_accuracy": round(dir_ok / total * 100, 1),
                        "avg_pct_error": round(avg_err, 2), "recent": recent})

    # ── News & AI analyst ──────────────────────────────────────────────────────

    @app.route("/api/news/<ticker>")
    @login_required
    def api_news(ticker):
        import yfinance as yf
        try:
            raw = yf.Ticker(ticker.upper()).news or []
            items = []
            for n in raw[:8]:
                ct    = n.get("content", {})
                title = ct.get("title") or n.get("title", "")
                pub   = ct.get("pubDate") or n.get("providerPublishTime", "")
                link  = ct.get("canonicalUrl", {}).get("url") or n.get("link", "")
                pub_fmt = ""
                if isinstance(pub, int):
                    pub_fmt = datetime.utcfromtimestamp(pub).strftime("%b %d, %Y")
                elif isinstance(pub, str) and pub:
                    try:
                        pub_fmt = datetime.fromisoformat(pub[:19]).strftime("%b %d, %Y")
                    except Exception:
                        pub_fmt = pub[:10]
                items.append({"title": title, "link": link, "published": pub_fmt})
            return jsonify({"ok": True, "ticker": ticker.upper(), "news": items})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 400

    @app.route("/api/ai/analyze/<ticker>", methods=["POST"])
    @login_required
    def ai_analyze(ticker):
        if not ANTHROPIC_API_KEY:
            return jsonify({"ok": False,
                            "error": "AI analyst not configured (ANTHROPIC_API_KEY missing)."}), 503
        try:
            import anthropic as _anthropic
            data        = request.get_json() or {}
            interval    = data.get("interval", "1d")
            cur_price   = data.get("current_price", 0)
            lr_pred     = data.get("lr_pred", 0)
            direction   = data.get("direction", "—")
            confidence  = data.get("confidence", 0)
            rsi         = data.get("rsi", 50)
            macd_signal = data.get("macd_signal", "—")
            ict_bias    = data.get("ict_bias", "—")
            pd_zone     = data.get("pd_zone", "—")
            prompt = (
                f"You are a professional quantitative trader and market analyst. "
                f"Provide a concise, actionable market commentary (3-4 short paragraphs) for "
                f"{ticker.upper()} based on the following ML prediction data:\n\n"
                f"- Timeframe: {interval}\n- Current Price: ${cur_price}\n"
                f"- ML Predicted Next Price: ${lr_pred}\n"
                f"- Direction: {direction} (Confidence: {confidence}%)\n"
                f"- RSI(14): {rsi}\n- MACD: {macd_signal}\n"
                f"- ICT Bias: {ict_bias}\n- PD Zone: {pd_zone}\n\n"
                f"Cover: (1) short-term momentum, (2) key levels, (3) risk factors, "
                f"(4) suggested approach. Be direct. No disclaimers."
            )
            client   = _anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            response = client.messages.create(
                model="claude-haiku-4-5-20251001", max_tokens=600,
                messages=[{"role": "user", "content": prompt}],
            )
            return jsonify({"ok": True, "analysis": response.content[0].text})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500
