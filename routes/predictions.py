"""routes/predictions.py, core predictions, watchlist, history, profile, AI analyst."""

import csv
import io
import json
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
from utils import (consume_quota, refund_quota, _try_azure_download,
                   VALID_INTERVALS, PRO_TICKERS, award_xp)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")


def register_prediction_routes(app, metrics):
    """metrics: shared dict {"predictions": 0, "total_latency": 0.0}"""

    @app.route("/", methods=["GET"])
    def home():
        """Logged-in: the dashboard. Logged-out: the marketing landing page.
        The Predict workstation lives at GET /predict."""
        if not current_user.is_authenticated:
            return render_template("landing.html")
        from models import PaperTrade, PaperEquitySnapshot
        recent_predictions = (PredictionHistory.query
                              .filter_by(user_id=current_user.id)
                              .order_by(PredictionHistory.predicted_at.desc())
                              .limit(5).all())
        total_predictions = PredictionHistory.query.filter_by(
            user_id=current_user.id).count()
        predictions_today = (current_user.predictions_today or 0
                             if current_user.last_prediction_date == date.today()
                             else 0)
        watchlist_items = (WatchlistItem.query
                           .filter_by(user_id=current_user.id)
                           .order_by(WatchlistItem.added_at).all())
        paper_open = PaperTrade.query.filter_by(
            user_id=current_user.id, status="open").count()
        paper_closed = PaperTrade.query.filter_by(
            user_id=current_user.id, status="closed").count()
        paper_pnl = None
        if paper_closed:
            paper_pnl = round(db.session.query(
                db.func.coalesce(db.func.sum(PaperTrade.pnl), 0.0))
                .filter(PaperTrade.user_id == current_user.id,
                        PaperTrade.status == "closed").scalar() or 0.0, 2)
        paper_balance = None
        latest = (db.session.query(
                      PaperEquitySnapshot.strategy,
                      db.func.max(PaperEquitySnapshot.taken_at))
                  .filter(PaperEquitySnapshot.user_id == current_user.id)
                  .group_by(PaperEquitySnapshot.strategy).all())
        if latest:
            total_equity = 0.0
            for strategy, taken_at in latest:
                snap = (PaperEquitySnapshot.query
                        .filter_by(user_id=current_user.id, strategy=strategy,
                                   taken_at=taken_at).first())
                if snap:
                    total_equity += snap.equity
            paper_balance = round(total_equity, 2)
        from paper_engine import SIM_CURRENCY
        return render_template(
            "home.html",
            recent_predictions=recent_predictions,
            total_predictions=total_predictions,
            predictions_today=predictions_today,
            watchlist_tickers=[i.ticker for i in watchlist_items],
            paper_open=paper_open,
            paper_closed=paper_closed,
            paper_pnl=paper_pnl,
            paper_balance=paper_balance,
            paper_currency=SIM_CURRENCY,
        )

    @app.route("/dashboard", methods=["GET"])
    @login_required
    def dashboard():
        """Stable alias for the authenticated homepage at /."""
        return home()

    @app.route("/predict", methods=["GET", "POST"])
    @login_required
    def predict():
        if request.method == "GET":
            last_ticker = request.cookies.get("bl-last-ticker", "")
            last_interval = request.cookies.get("bl-last-interval", "1d")
            return render_template("index.html", ticker=last_ticker,
                                   interval=last_interval)
        ticker   = request.form.get("ticker", "").upper().strip()
        interval = request.form.get("interval", "1d").strip()
        if interval not in VALID_INTERVALS:
            return render_template("index.html", error="Invalid interval selected."), 400
        if not ticker:
            return render_template("index.html", error="Please enter a valid symbol."), 400
        allowed, err_msg = consume_quota(current_user)
        if not allowed:
            return render_template("index.html", error=err_msg), 429
        try:
            start_t = time.time()
            res = run_prediction(ticker, interval=interval)
            latency = time.time() - start_t
            metrics["predictions"] += 1
            metrics["total_latency"] += latency
            ph = PredictionHistory(
                user_id=current_user.id, ticker=ticker, interval=interval,
                predicted_price=res.get("predicted_price", 0.0),
                direction=res.get("direction", "NEUTRAL"),
                confidence=res.get("confidence", 0.0),
                current_price=res.get("current_price", 0.0)
            )
            db.session.add(ph)
            db.session.commit()
            award_xp(current_user, 5)
            from flask import make_response
            resp = make_response(render_template("index.html", result=res, ticker=ticker, interval=interval))
            resp.set_cookie("bl-last-ticker", ticker, max_age=30*86400)
            resp.set_cookie("bl-last-interval", interval, max_age=30*86400)
            return resp
        except Exception as e:
            refund_quota(current_user)
            return render_template("index.html", error=f"Prediction error: {e}"), 500

    @app.route("/research/<ticker>")
    @login_required
    def research_page(ticker):
        return render_template("research.html", ticker=ticker.upper())

    @app.route("/pipeline")
    @login_required
    def pipeline():
        return render_template("pipeline.html")

    @app.route("/ethics/risk-basics", methods=["GET", "POST"])
    @login_required
    def risk_basics():
        from models import UserPreferences
        pref = UserPreferences.query.filter_by(user_id=current_user.id).first()
        if request.method == "POST":
            if not pref:
                pref = UserPreferences(user_id=current_user.id)
                db.session.add(pref)
            pref.risk_intro_seen = True
            db.session.commit()
            return redirect(url_for("predict"))
        if pref and pref.risk_intro_seen:
            return redirect(url_for("predict"))
        return render_template("risk_basics.html")

    @app.route("/api/watchlist")

    @login_required
    def api_watchlist():
        items = WatchlistItem.query.filter_by(user_id=current_user.id).order_by(WatchlistItem.added_at).all()
        return jsonify({"ok": True, "watchlist": [i.ticker for i in items]})

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

    @app.route("/api/history")
    @login_required
    def api_history():
        records = (PredictionHistory.query
                   .filter_by(user_id=current_user.id)
                   .order_by(PredictionHistory.predicted_at.desc())
                   .limit(100).all())
        out = []
        for r in records:
            out.append({
                "id": r.id,
                "ticker": r.ticker,
                "interval": r.interval,
                "predicted_at": r.predicted_at.isoformat() if r.predicted_at else None,
                "current_price": r.current_price,
                "lr_pred": r.lr_pred,
                "rf_pred": r.rf_pred,
                "direction": r.direction,
                "confidence": r.confidence,
                "status": getattr(r, "status", "pending")
            })
        return jsonify({"ok": True, "history": out})

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

    @app.route("/api/profile")
    @login_required
    def api_profile():
        total = PredictionHistory.query.filter_by(user_id=current_user.id).count()
        return jsonify({"ok": True, "total_predictions": total})

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
        if not current_user.is_plus:
            return jsonify({"ok": False, "error": "Plus plan required"}), 403
        ticker = ticker.upper()
        try:
            from market_data import get_history
            _try_azure_download(ticker, "1d")
            _try_azure_download(ticker, "1h")
            with ThreadPoolExecutor(max_workers=2) as ex:
                f1d = ex.submit(run_prediction, ticker, "1d")
                f1h = ex.submit(run_prediction, ticker, "1h")
                r1d, r1h = f1d.result(), f1h.result()
            hist, _ = get_history(ticker, period="5d", interval="1d")
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

    def _resample_weekly(daily_candles):
        """Group daily candles (time='YYYY-MM-DD') into ISO-week OHLCV bars."""
        weeks = {}
        order = []
        for c in daily_candles:
            d = datetime.strptime(c["time"], "%Y-%m-%d")
            wk = d - timedelta(days=d.weekday())      # Monday of that week
            key = wk.strftime("%Y-%m-%d")
            if key not in weeks:
                weeks[key] = {"time": key, "open": c["open"], "high": c["high"],
                              "low": c["low"], "close": c["close"], "volume": c.get("volume", 0)}
                order.append(key)
            else:
                bar = weeks[key]
                bar["high"]   = max(bar["high"], c["high"])
                bar["low"]    = min(bar["low"],  c["low"])
                bar["close"]  = c["close"]
                bar["volume"] = bar.get("volume", 0) + c.get("volume", 0)
        return [weeks[k] for k in order]

    @app.route("/api/chart/<ticker>", methods=["GET"])
    @login_required
    def api_chart(ticker):
        ticker = ticker.upper().strip()
        tf = (request.args.get("interval") or "1D").strip()
        pred_interval = "1d" if tf in ("1D", "1W") else tf
        if pred_interval not in VALID_INTERVALS:
            return jsonify({"ok": False, "error": f'Unsupported timeframe "{tf}".'}), 400

        empty_zones = {"pred": None, "tp": None, "sl": None,
                       "ote_buy": None, "ote_sell": None, "fvg": [], "ob": [],
                       "in_ote_buy": False, "in_ote_sell": False}

        try:
            result = run_prediction(ticker, pred_interval)
            lw = json.loads(result["lw_chart"])
            candles = lw["candles"]
            zones = {"pred": lw["pred"], "tp": lw["tp"], "sl": lw["sl"],
                     "ote_buy": lw["ote_buy"], "ote_sell": lw["ote_sell"],
                     "fvg": lw["fvg"], "ob": lw["ob"],
                     "in_ote_buy": lw["in_ote_buy"], "in_ote_sell": lw["in_ote_sell"]}
            sma200 = lw["sma200"]
            direction_label = {"Up": "BUY", "Down": "SELL"}.get(result["direction"], "HOLD")
            prediction = {
                "direction":     direction_label,
                "confidence":    result["confidence"],
                "target_price":  result["lr_pred"],
                "current_price": result["current_price"],
                "change_pct":    result["change_pct"],
                "model_used":    "LR + RF",
            }
        except FileNotFoundError:
            # No trained model for this ticker/timeframe combo, still show
            # the price chart (candles only), just without a prediction.
            from predictor import _fetch_df, lw_time
            try:
                df = _fetch_df(ticker, pred_interval)
            except Exception as e:
                return jsonify({"ok": False, "error": str(e)}), 404
            if df is None or df.empty:
                return jsonify({"ok": False, "error": f'No market data for "{ticker}".'}), 404
            chart_plot = df.tail(300)
            candles = [
                {"time": lw_time(idx, pred_interval),
                 "open": round(float(r["Open"]), 4), "high": round(float(r["High"]), 4),
                 "low": round(float(r["Low"]), 4), "close": round(float(r["Close"]), 4),
                 "volume": round(float(r["Volume"]), 2) if "Volume" in r and r["Volume"] == r["Volume"] else 0}
                for idx, r in chart_plot.iterrows()
            ]
            sma200 = []
            zones = dict(empty_zones)
            prediction = None
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 404
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500

        if tf == "1W":
            candles = _resample_weekly(candles)
            sma200 = []
            zones = dict(empty_zones)

        return jsonify({
            "ok": True,
            "ticker": ticker,
            "interval": tf,
            "ohlcv": candles,
            "sma200": sma200,
            "zones": zones,
            "prediction": prediction,
        })

    @app.route("/api/available-models")
    @login_required
    def api_available_models():
        from predictor import available_models
        models = available_models()
        return jsonify({"ok": True, "tickers": models, "total_tickers": len(models)})

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
                from market_data import get_history
                hist, _ = get_history(pred.ticker, period="5d", interval="1d")
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

    # ── Risk basics interstitial (shown once before first prediction) ──────────

    @app.route("/api/risk-basics", methods=["POST"])
    @login_required
    def api_risk_basics():
        from models import UserPreferences
        pref = UserPreferences.query.filter_by(user_id=current_user.id).first()
        if not pref:
            pref = UserPreferences(user_id=current_user.id)
            db.session.add(pref)
        pref.risk_intro_seen = True
        db.session.commit()
        return jsonify({"ok": True})

    # ── Account data export and deletion (easy exit, no dark patterns) ─────────

    @app.route("/account/export")
    @login_required
    def account_export():
        from models import (PredictionHistory, WatchlistItem, PriceAlert,
                            PortfolioPosition, TradeJournal, Payment)
        u = current_user
        data = {
            "account": {"username": u.username, "email": u.email, "plan": u.plan,
                        "created_at": str(u.created_at or ""),
                        "auth_provider": u.auth_provider},
            "predictions": [{"ticker": p.ticker, "interval": p.interval,
                             "current_price": p.current_price, "lr_pred": p.lr_pred,
                             "rf_pred": p.rf_pred, "direction": p.direction,
                             "confidence": p.confidence, "at": str(p.predicted_at)}
                            for p in PredictionHistory.query.filter_by(user_id=u.id)],
            "watchlist": [w.ticker for w in WatchlistItem.query.filter_by(user_id=u.id)],
            "alerts": [{"ticker": a.ticker, "price": a.price, "direction": a.direction}
                       for a in PriceAlert.query.filter_by(user_id=u.id)],
            "positions": [{"ticker": p.ticker, "side": p.side, "entry": p.entry_price,
                           "qty": p.quantity, "status": p.status}
                          for p in PortfolioPosition.query.filter_by(user_id=u.id)],
            "journal": [{"title": j.title, "body": j.body, "at": str(j.created_at)}
                        for j in TradeJournal.query.filter_by(user_id=u.id)],
            "payments": [{"provider": p.provider, "amount": p.amount,
                          "currency": p.currency, "status": p.status,
                          "receipt": p.receipt, "at": str(p.created_at)}
                         for p in Payment.query.filter_by(user_id=u.id)],
        }
        resp = jsonify(data)
        resp.headers["Content-Disposition"] = "attachment; filename=bulllogic-data.json"
        return resp

    @app.route("/account/delete", methods=["POST"])
    @login_required
    def account_delete():
        from flask_login import logout_user
        from models import (User, PredictionAccuracy,
                            WatchlistItem, PriceAlert, PortfolioPosition,
                            ApiKey, PasswordResetToken, TelegramConfig,
                            Notification, TradeJournal, DiscordConfig,
                            UserWebhook, ActivityLog, TwoFactorAuth,
                            UserPreferences, Feedback)
        if (request.get_json() or {}).get("confirm") is not True:
            return jsonify({"ok": False, "error": "Confirmation required"}), 400
        uid = current_user.id
        if getattr(current_user, "role_level", 0) >= 3:
            return jsonify({"ok": False,
                            "error": "Admin accounts must transfer admin rights before deletion."}), 400
        for ph in PredictionHistory.query.filter_by(user_id=uid).all():
            PredictionAccuracy.query.filter_by(prediction_id=ph.id).delete()
        for model in (PredictionHistory, WatchlistItem, PriceAlert,
                      PortfolioPosition, ApiKey, PasswordResetToken,
                      TelegramConfig, Notification, TradeJournal, DiscordConfig,
                      UserWebhook, ActivityLog, TwoFactorAuth, UserPreferences,
                      Feedback):
            model.query.filter_by(user_id=uid).delete()
        # Payment rows are retained for the legal audit trail.
        user = db.session.get(User, uid)
        logout_user()
        db.session.delete(user)
        db.session.commit()
        return jsonify({"ok": True, "message": "Your account and data were deleted. Kwaheri."})

    # ── Track record (public, the trust page) ─────────────────────────────────

    @app.route("/api/track-record")
    def api_track_record():
        from ops import platform_stats
        days = int(request.args.get("days", 90))
        days = 30 if days <= 30 else 90
        return jsonify({"ok": True, **platform_stats(db, days=days)})

    # ── Data health (degraded-mode banner) ─────────────────────────────────────

    @app.route("/api/health/data")
    def api_health_data():
        from market_data import data_status
        return jsonify({"ok": True, **data_status()})

    # ── Feedback widget ────────────────────────────────────────────────────────

    @app.route("/api/feedback", methods=["POST"])
    @login_required
    def api_feedback():
        from utils import rate_limited, _POSITIVE_WORDS, _NEGATIVE_WORDS
        from models import Feedback
        if rate_limited(f"feedback:{current_user.id}", 5, 86400):
            return jsonify({"ok": False, "error": "Feedback limit reached for today"}), 429
        data    = request.get_json() or {}
        try:
            rating = int(data.get("rating", 0))
        except (TypeError, ValueError):
            rating = 0
        if rating < 1 or rating > 5:
            return jsonify({"ok": False, "error": "Rating must be 1-5"}), 400
        comment = (data.get("comment") or "").strip()[:500] or None
        sentiment = None
        if comment:
            words = {w.strip(".,!?").lower() for w in comment.split()}
            pos = len(words & _POSITIVE_WORDS)
            neg = len(words & _NEGATIVE_WORDS)
            sentiment = round((pos - neg) / max(pos + neg, 1), 2)
        db.session.add(Feedback(user_id=current_user.id,
                                page=(data.get("page") or "")[:50] or None,
                                rating=rating, comment=comment,
                                sentiment=sentiment))
        db.session.commit()
        return jsonify({"ok": True, "message": "Asante! Feedback received."})

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

    # ── Signal leaderboard ─────────────────────────────────────────────────────

    @app.route("/api/leaderboard")
    @login_required
    def api_leaderboard():
        from models import PredictionAccuracy, PredictionHistory
        tickers   = ["AAPL", "MSFT", "NVDA", "TSLA", "GOOGL", "AMZN", "META", "QQQ", "NDX", "DIA"]
        intervals = ["1d", "1h", "4h"]
        rows = []

        def _sig(args):
            ticker, ivl = args
            try:
                sig    = ml_signal(ticker, ivl)
                acc_rows = (db.session.query(PredictionAccuracy)
                            .join(PredictionHistory,
                                  PredictionAccuracy.prediction_id == PredictionHistory.id)
                            .filter(PredictionHistory.ticker == ticker,
                                    PredictionHistory.interval == ivl)
                            .limit(50).all())
                n      = len(acc_rows)
                dir_ok = sum(1 for a in acc_rows if a.direction_ok) if n else 0
                return {
                    "ticker":     ticker,
                    "interval":   ivl,
                    "action":     sig.get("action", "HOLD"),
                    "confidence": sig.get("confidence", 0),
                    "price":      sig.get("current_price", 0),
                    "rsi":        sig.get("rsi", 50),
                    "accuracy":   round(dir_ok / n * 100, 1) if n >= 3 else None,
                    "n_checked":  n,
                }
            except Exception:
                return None

        with ThreadPoolExecutor(max_workers=8) as ex:
            results = list(ex.map(_sig, [(t, iv) for t in tickers for iv in intervals]))
        rows = sorted([r for r in results if r],
                      key=lambda x: (x["accuracy"] or 0, x["confidence"]), reverse=True)
        return jsonify({"ok": True, "rows": rows})

    # ── Deep research page ─────────────────────────────────────────────────────

    @app.route("/api/research/<ticker>")
    @login_required
    def api_research(ticker):
        ticker = ticker.upper()
        import yfinance as yf

        def _price():
            try:
                fi = yf.Ticker(ticker).fast_info
                return {"price": round(float(fi.last_price or 0), 2),
                        "prev":  round(float(fi.previous_close or 0), 2)}
            except Exception:
                return {}

        def _info():
            try:
                i = yf.Ticker(ticker).info
                return {
                    "name":           i.get("longName", ticker),
                    "sector":         i.get("sector", "-"),
                    "industry":       i.get("industry", "-"),
                    "market_cap":     i.get("marketCap"),
                    "pe":             round(float(i.get("trailingPE") or 0), 2),
                    "eps":            round(float(i.get("trailingEps") or 0), 2),
                    "52w_high":       round(float(i.get("fiftyTwoWeekHigh") or 0), 2),
                    "52w_low":        round(float(i.get("fiftyTwoWeekLow") or 0), 2),
                    "avg_volume":     i.get("averageVolume"),
                    "beta":           round(float(i.get("beta") or 0), 2),
                    "div_yield":      round(float((i.get("dividendYield") or 0) * 100), 2),
                    "target_mean":    round(float(i.get("targetMeanPrice") or 0), 2),
                    "recommendation": i.get("recommendationKey", "-"),
                    "analyst_count":  i.get("numberOfAnalystOpinions", 0),
                    "short_float":    round(float((i.get("shortPercentOfFloat") or 0) * 100), 2),
                    "description":    (i.get("longBusinessSummary") or "")[:400],
                }
            except Exception:
                return {}

        def _news():
            try:
                raw = yf.Ticker(ticker).news or []
                items = []
                for n in raw[:5]:
                    ct    = n.get("content", {})
                    title = ct.get("title") or n.get("title", "")
                    link  = ct.get("canonicalUrl", {}).get("url") or n.get("link", "")
                    items.append({"title": title, "link": link})
                return items
            except Exception:
                return []

        def _prediction():
            try:
                _try_azure_download(ticker, "1d")
                res = run_prediction(ticker, "1d")
                return {
                    "direction":  res.get("direction"),
                    "confidence": res.get("confidence"),
                    "lr_pred":    res.get("lr_pred"),
                    "action":     res.get("action"),
                    "rsi":        res.get("rsi"),
                    "macd":       res.get("macd_signal"),
                    "ict_bias":   res.get("ict_bias"),
                    "current_price": res.get("current_price"),
                }
            except Exception:
                return {}

        with ThreadPoolExecutor(max_workers=4) as ex:
            fp = ex.submit(_price)
            fi = ex.submit(_info)
            fn = ex.submit(_news)
            fd = ex.submit(_prediction)
            price_d = fp.result()
            info_d  = fi.result()
            news_d  = fn.result()
            pred_d  = fd.result()

        return jsonify({"ok": True, "ticker": ticker,
                        "price": price_d, "info": info_d,
                        "news": news_d,  "prediction": pred_d})

    # ── Pipeline page ──────────────────────────────────────────────────────────

    @app.route("/api/pipeline/retrain", methods=["POST"])
    @login_required
    def api_pipeline_retrain():
        import subprocess
        import threading
        BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        
        def run_job():
            try:
                subprocess.run([sys.executable, "train_all_tickers.py", "--fast"], cwd=BASE_DIR, check=True)
            except Exception as e:
                print("Retrain job failed:", e)
        
        threading.Thread(target=run_job, daemon=True).start()
        return jsonify({"ok": True, "msg": "Retraining started in the background"})

    @app.route("/api/pipeline/stats")
    @login_required
    def api_pipeline_stats():
        """Return system-wide metrics for the strategy pipeline page."""
        import glob
        from models import PredictionAccuracy, PredictionHistory, PortfolioPosition
        BASE_DIR   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        models_dir = os.path.join(BASE_DIR, "Saved Models")
        data_dir   = os.path.join(BASE_DIR, "Data")

        n_models = len(glob.glob(os.path.join(models_dir, "lr_model_*.pkl")))

        metrics_path = os.path.join(data_dir, "model_metrics.json")
        avg_auc = None
        if os.path.exists(metrics_path):
            import json
            with open(metrics_path) as f:
                m = json.load(f)
            results = m.get("results", [])
            aucs = [r["xgb_auc"] for r in results if r.get("xgb_auc") and r["xgb_auc"] > 0]
            avg_auc = round(sum(aucs) / len(aucs), 3) if aucs else None

        bt_path = os.path.join(data_dir, "backtest_summary.json")
        bt_return, bt_sharpe = None, None
        if os.path.exists(bt_path):
            import json
            with open(bt_path) as f:
                bt = json.load(f)
            metrics = bt.get("metrics", {})
            bt_return = metrics.get("total_return")
            bt_sharpe = metrics.get("sharpe")

        total_acc = PredictionAccuracy.query.count()
        dir_ok    = PredictionAccuracy.query.filter_by(direction_ok=True).count()
        direction_acc = round(dir_ok / total_acc * 100, 1) if total_acc >= 5 else None

        open_positions  = PortfolioPosition.query.filter_by(
            user_id=current_user.id, status="open").count()
        total_positions = PortfolioPosition.query.filter_by(user_id=current_user.id).count()

        total_preds = PredictionHistory.query.filter_by(user_id=current_user.id).count()

        return jsonify({
            "ok": True,
            "research":    {"n_models": n_models, "avg_auc": avg_auc, "tickers": 10, "timeframes": 7},
            "backtest":    {"total_return": bt_return, "sharpe": bt_sharpe},
            "paper":       {"open": open_positions, "total": total_positions,
                            "direction_acc": direction_acc, "checked": total_acc},
            "live":        {"total_predictions": total_preds},
        })

    @app.route("/api/ai/analyze/<ticker>", methods=["POST"])
    @login_required
    def ai_analyze(ticker):
        if not DEEPSEEK_API_KEY and not ANTHROPIC_API_KEY:
            return jsonify({"ok": False,
                            "error": "AI analyst not configured (no provider API key set)."}), 503
        data        = request.get_json() or {}
        interval    = data.get("interval", "1d")
        cur_price   = data.get("current_price", 0)
        lr_pred     = data.get("lr_pred", 0)
        direction   = data.get("direction", "-")
        confidence  = data.get("confidence", 0)
        rsi         = data.get("rsi", 50)
        macd_signal = data.get("macd_signal", "-")
        ict_bias    = data.get("ict_bias", "-")
        pd_zone     = data.get("pd_zone", "-")
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

        deepseek_err = None
        if DEEPSEEK_API_KEY:
            try:
                import openai as _openai
                client = _openai.OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")
                response = client.chat.completions.create(
                    model="deepseek-chat", max_tokens=600,
                    messages=[{"role": "user", "content": prompt}],
                )
                return jsonify({"ok": True, "analysis": response.choices[0].message.content,
                                "provider": "deepseek"})
            except Exception as e:
                deepseek_err = str(e)
                if not ANTHROPIC_API_KEY:
                    return jsonify({"ok": False, "error": deepseek_err}), 500

        try:
            import anthropic as _anthropic
            client   = _anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            response = client.messages.create(
                model="claude-haiku-4-5-20251001", max_tokens=600,
                messages=[{"role": "user", "content": prompt}],
            )
            return jsonify({"ok": True, "analysis": response.content[0].text,
                            "provider": "anthropic"})
        except Exception as e:
            err = str(e)
            if deepseek_err:
                err = f"deepseek: {deepseek_err}; anthropic: {err}"
            return jsonify({"ok": False, "error": err}), 500
