"""routes/analytics.py, screener, scanner, calendar, fear-greed, Monte Carlo,
correlation, sentiment, feature-importance, options, dividends, insiders,
analyst targets, batch prices, SSE stream."""

import json as _json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

from flask import render_template, request, jsonify, Response, stream_with_context
from flask_login import login_required, current_user

from utils import (SCREENER_TICKERS, CALENDAR_TICKERS, _POSITIVE_WORDS, _NEGATIVE_WORDS,
                   _SECTOR_ETFS, VALID_INTERVALS)

# Quotes go through market_data, one shared cache and rate-limit circuit
# breaker for the whole app.
from market_data import get_quote as _cached_quote


def register_analytics_routes(app):

    # ── Screener ───────────────────────────────────────────────────────────────

    @app.route("/screener")
    @login_required
    def screener():
        return render_template("screener.html")

    @app.route("/api/screener")
    @login_required
    def api_screener():
        from predictor import ml_signal
        interval = request.args.get("interval", "1d")
        if interval not in ("1d", "1h"):
            interval = "1d"
        tickers = request.args.getlist("tickers") or SCREENER_TICKERS

        def _scan(ticker):
            try:
                sig = ml_signal(ticker, interval)
                return ticker, {
                    "ticker":     ticker,
                    "action":     sig.get("action", "HOLD"),
                    "price":      sig.get("current_price", 0),
                    "lr_pred":    sig.get("lr_pred", 0),
                    "confidence": sig.get("confidence", 0),
                    "rsi":        sig.get("rsi", 50),
                    "macd_hist":  sig.get("macd_hist", 0),
                    "atr":        sig.get("atr", 0),
                }
            except Exception:
                return ticker, {"ticker": ticker, "action": "HOLD", "price": 0,
                                "lr_pred": 0, "confidence": 0, "rsi": 50,
                                "macd_hist": 0, "atr": 0}

        with ThreadPoolExecutor(max_workers=min(len(tickers), 8)) as ex:
            results = dict(ex.map(lambda t: _scan(t), tickers))
        rows = sorted(results.values(), key=lambda x: x["confidence"], reverse=True)
        return jsonify({"ok": True, "interval": interval, "rows": rows})

    # ── Scanner ────────────────────────────────────────────────────────────────

    @app.route("/scanner")
    @login_required
    def scanner_page():
        return render_template("scanner.html", user=current_user)

    @app.route("/api/scanner/volume")
    @login_required
    def api_scanner_volume():
        from market_data import get_history
        results = []

        def _chk(t):
            try:
                hist, _ = get_history(t, period="30d", interval="1d")
                if len(hist) < 10:
                    return
                avg_vol = float(hist["Volume"].iloc[:-1].mean())
                today   = float(hist["Volume"].iloc[-1])
                ratio   = today / avg_vol if avg_vol > 0 else 1.0
                price   = float(hist["Close"].iloc[-1])
                chg     = float((hist["Close"].iloc[-1] / hist["Close"].iloc[-2] - 1) * 100)
                results.append({"ticker": t, "price": round(price, 2),
                                "volume": int(today), "avg_volume": int(avg_vol),
                                "volume_ratio": round(ratio, 2), "pct_change": round(chg, 2)})
            except Exception:
                pass

        with ThreadPoolExecutor(max_workers=8) as ex:
            list(ex.map(_chk, SCREENER_TICKERS))
        results.sort(key=lambda x: x["volume_ratio"], reverse=True)
        return jsonify({"ok": True, "rows": results})

    @app.route("/api/scanner/short-squeeze")
    @login_required
    def api_scanner_short_squeeze():
        import yfinance as yf
        import pandas as pd
        import ta as _ta
        results = []

        def _chk(t):
            try:
                info  = yf.Ticker(t).info
                sf    = (info.get("shortPercentOfFloat") or 0) * 100
                sr    = info.get("shortRatio") or 0
                price = info.get("currentPrice") or info.get("regularMarketPrice") or 0
                from market_data import get_history
                hist, _ = get_history(t, period="30d", interval="1d")
                rsi_val = None
                if len(hist) >= 14:
                    rsi_val = round(float(_ta.momentum.rsi(hist["Close"], window=14).iloc[-1]), 1)
                mom = 0.0
                if len(hist) >= 5:
                    mom = round(float((hist["Close"].iloc[-1] / hist["Close"].iloc[-5] - 1) * 100), 2)
                results.append({
                    "ticker": t, "price": round(float(price), 2),
                    "short_float_pct": round(float(sf), 1),
                    "days_to_cover":   round(float(sr), 1),
                    "rsi": rsi_val, "momentum_5d": mom,
                    "squeeze_score": round(float(sf) * 0.5 + max(0, mom) * 0.5, 1),
                })
            except Exception:
                pass

        with ThreadPoolExecutor(max_workers=6) as ex:
            list(ex.map(_chk, SCREENER_TICKERS))
        results.sort(key=lambda x: x["squeeze_score"], reverse=True)
        return jsonify({"ok": True, "rows": results})

    @app.route("/api/scanner/sector-heatmap")
    @login_required
    def api_scanner_sector_heatmap():
        import yfinance as yf
        import pandas as pd
        results = []

        def _chk(item):
            sector, etf = item
            try:
                from market_data import get_history
                hist, _ = get_history(etf, period="5d", interval="1d")
                if len(hist) < 2:
                    return
                d1 = round(float((hist["Close"].iloc[-1] / hist["Close"].iloc[-2] - 1) * 100), 2)
                d5 = round(float((hist["Close"].iloc[-1] / hist["Close"].iloc[0]  - 1) * 100), 2)
                results.append({"sector": sector, "etf": etf,
                                "price": round(float(hist["Close"].iloc[-1]), 2),
                                "d1": d1, "d5": d5,
                                "volume": int(hist["Volume"].iloc[-1])})
            except Exception:
                pass

        with ThreadPoolExecutor(max_workers=8) as ex:
            list(ex.map(_chk, _SECTOR_ETFS.items()))
        results.sort(key=lambda x: x["d1"], reverse=True)
        return jsonify({"ok": True, "sectors": results})

    # ── Calendar ───────────────────────────────────────────────────────────────

    @app.route("/calendar")
    @login_required
    def calendar_page():
        return render_template("calendar.html")

    @app.route("/api/calendar/earnings")
    @login_required
    def api_calendar_earnings():
        import yfinance as yf
        results = []
        today   = date.today()

        def _fetch(ticker):
            try:
                t   = yf.Ticker(ticker)
                raw = t.earnings_dates
                if raw is None or raw.empty:
                    return
                idx = raw.index.tz_localize(None) if raw.index.tz else raw.index
                for dt in idx:
                    d = dt.date()
                    if d >= today and (d - today).days <= 90:
                        results.append({"ticker": ticker,
                                        "date": d.strftime("%Y-%m-%d"),
                                        "days": (d - today).days})
            except Exception:
                pass

        with ThreadPoolExecutor(max_workers=8) as ex:
            list(ex.map(_fetch, CALENDAR_TICKERS))
        results.sort(key=lambda x: x["date"])
        return jsonify({"ok": True, "events": results})

    @app.route("/api/calendar/macro")
    @login_required
    def api_calendar_macro():
        today  = date.today()
        events = []
        for offset in range(0, 90):
            d = today + timedelta(days=offset)
            if d.weekday() == 2 and offset % 42 < 7:
                events.append({"name": "FOMC Meeting (approx)", "date": d.strftime("%Y-%m-%d"),
                               "impact": "high", "category": "fed"})
            if d.weekday() == 1 and 8 <= d.day <= 14:
                events.append({"name": "CPI Report (approx)", "date": d.strftime("%Y-%m-%d"),
                               "impact": "high", "category": "inflation"})
            if d.weekday() == 4 and d.day <= 7:
                events.append({"name": "Non-Farm Payrolls (approx)", "date": d.strftime("%Y-%m-%d"),
                               "impact": "high", "category": "employment"})
        return jsonify({"ok": True, "events": events[:20]})

    # ── Fear & Greed ───────────────────────────────────────────────────────────

    @app.route("/api/fear-greed")
    @login_required
    def api_fear_greed():
        try:
            from market_data import get_history
            import pandas as pd
            import ta as _ta
            spy, _ = get_history("SPY", period="1y", interval="1d")
            spy_c = spy["Close"].dropna()
            mom_score = 50.0
            if len(spy_c) >= 125:
                ma125     = spy_c.rolling(125).mean().iloc[-1]
                ratio     = float(spy_c.iloc[-1]) / float(ma125)
                mom_score = max(0.0, min(100.0, (ratio - 0.9) / 0.2 * 100))
            vix, _ = get_history("^VIX", period="30d", interval="1d")
            vix_level = float(vix["Close"].iloc[-1]) if not vix.empty else 20.0
            vol_score = max(0.0, min(100.0, (40 - vix_level) / 30 * 100))
            rsi_val   = float(_ta.momentum.rsi(spy_c, window=14).iloc[-1]) if len(spy_c) >= 14 else 50.0
            h52       = float(spy_c.rolling(252, min_periods=100).max().iloc[-1])
            l52       = float(spy_c.rolling(252, min_periods=100).min().iloc[-1])
            hl_score  = (float(spy_c.iloc[-1]) - l52) / (h52 - l52) * 100 if h52 != l52 else 50.0
            composite = max(0, min(100, int(round(
                mom_score * 0.30 + vol_score * 0.30 + rsi_val * 0.20 + hl_score * 0.20
            ))))
            if composite >= 75:   label, color = "Extreme Greed", "#00C853"
            elif composite >= 55: label, color = "Greed",          "#69F0AE"
            elif composite >= 45: label, color = "Neutral",        "#FFD54F"
            elif composite >= 25: label, color = "Fear",           "#FF8A65"
            else:                 label, color = "Extreme Fear",   "#FF5252"
            return jsonify({"ok": True, "score": composite, "label": label, "color": color,
                            "vix": round(vix_level, 1), "rsi": round(rsi_val, 1),
                            "components": {"momentum": round(mom_score), "volatility": round(vol_score),
                                           "rsi": round(rsi_val), "breadth": round(hl_score)}})
        except Exception as e:
            return jsonify({"ok": True, "score": 50, "label": "Neutral", "color": "#FFD54F",
                            "vix": 0, "rsi": 50, "components": {}, "error": str(e)})

    # ── Correlation matrix ─────────────────────────────────────────────────────

    @app.route("/api/correlation")
    @login_required
    def api_correlation():
        try:
            import yfinance as yf
            import pandas as pd
            from models import WatchlistItem
            tickers = request.args.getlist("t")
            if not tickers:
                items   = WatchlistItem.query.filter_by(user_id=current_user.id).all()
                tickers = [i.ticker for i in items]
            if len(tickers) < 2:
                return jsonify({"ok": False,
                                "error": "Add at least 2 tickers to your watchlist"})
            tickers = [t.upper() for t in tickers[:12]]
            raw     = yf.download(tickers, period="3mo", interval="1d",
                                  auto_adjust=True, progress=False)
            close   = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw
            if isinstance(close, pd.Series):
                close = close.to_frame(name=tickers[0])
            close = close.dropna(axis=1, how="all")
            rets  = close.pct_change().dropna()
            corr  = rets.corr().round(3)
            return jsonify({"ok": True, "tickers": list(corr.columns),
                            "matrix": corr.values.tolist()})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 400

    # ── Monte Carlo ────────────────────────────────────────────────────────────

    @app.route("/api/monte-carlo", methods=["POST"])
    @login_required
    def api_monte_carlo():
        try:
            import yfinance as yf
            import pandas as pd
            import numpy as np
            data    = request.get_json() or {}
            tickers = data.get("tickers", ["AAPL"])[:10]
            weights = data.get("weights")
            capital = float(data.get("capital", 10000))
            days    = int(data.get("days", 252))
            sims    = min(int(data.get("simulations", 500)), 1000)
            raw     = yf.download(tickers, period="2y", interval="1d",
                                  auto_adjust=True, progress=False)
            prices  = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw
            if isinstance(prices, pd.Series):
                prices = prices.to_frame(name=tickers[0])
            rets    = prices.pct_change().dropna()
            w       = np.array(weights if weights and len(weights) == len(tickers)
                               else [1 / len(tickers)] * len(tickers))
            w       = w / w.sum()
            port_r  = rets.dot(w)
            mu, sigma = float(port_r.mean()), float(port_r.std())
            paths   = np.zeros((sims, days))
            for i in range(sims):
                r        = np.random.normal(mu, sigma, days)
                paths[i] = capital * np.cumprod(1 + r)
            final = paths[:, -1]
            p5, p25, p50, p75, p95 = np.percentile(final, [5, 25, 50, 75, 95])
            step  = max(1, days // 60)
            return jsonify({
                "ok": True, "simulations": sims, "days": days, "capital": capital,
                "final": {"p5": round(p5, 2), "p25": round(p25, 2), "p50": round(p50, 2),
                          "p75": round(p75, 2), "p95": round(p95, 2)},
                "chart": {
                    "p5":  [round(v, 2) for v in np.percentile(paths, 5,  axis=0)[::step]],
                    "p50": [round(v, 2) for v in np.percentile(paths, 50, axis=0)[::step]],
                    "p95": [round(v, 2) for v in np.percentile(paths, 95, axis=0)[::step]],
                },
                "prob_profit": round(float((final > capital).mean() * 100), 1),
            })
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 400

    # ── Sentiment ──────────────────────────────────────────────────────────────

    @app.route("/api/sentiment/<ticker>")
    @login_required
    def api_sentiment(ticker):
        try:
            import yfinance as yf
            news = yf.Ticker(ticker.upper()).news or []
            scores, headlines = [], []
            for item in news[:15]:
                content = item.get("content") or {}
                title   = (content.get("title") or item.get("title") or "").lower()
                pos     = sum(1 for w in _POSITIVE_WORDS if w in title)
                neg     = sum(1 for w in _NEGATIVE_WORDS if w in title)
                s       = (pos - neg) / (pos + neg) if (pos + neg) else 0
                scores.append(s)
                url = (content.get("canonicalUrl") or {}).get("url") or item.get("link", "")
                headlines.append({"title": title[:120], "score": round(s, 2), "url": url})
            avg = round(sum(scores) / len(scores), 3) if scores else 0
            if avg > 0.25:    label, color = "Bullish",          "#69F0AE"
            elif avg > 0.0:   label, color = "Slightly Bullish", "#B9F6CA"
            elif avg > -0.25: label, color = "Slightly Bearish", "#FFAB91"
            else:             label, color = "Bearish",          "#FF5252"
            return jsonify({"ok": True, "ticker": ticker.upper(),
                            "score": avg, "label": label, "color": color,
                            "article_count": len(news), "analyzed": len(scores),
                            "headlines": headlines[:8]})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 400

    # ── Feature importance ─────────────────────────────────────────────────────

    @app.route("/api/feature-importance/<ticker>")
    @login_required
    def api_feature_importance(ticker):
        try:
            import joblib
            BASE_DIR   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            models_dir = os.path.join(BASE_DIR, "Saved Models")
            ticker     = ticker.upper()
            interval   = request.args.get("interval", "1d")
            if interval not in VALID_INTERVALS:
                interval = "1d"
            suffix     = "" if interval == "1d" else f"_{interval}"
            rf_path    = os.path.join(models_dir, f"rf_model_{ticker}{suffix}.pkl")
            feat_path  = os.path.join(models_dir, f"feature_cols_sklearn_{ticker}{suffix}.pkl")
            if not os.path.exists(rf_path):
                return jsonify({"ok": False,
                                "error": f"No {interval} model found for {ticker}."})
            rf   = joblib.load(rf_path)
            feat = joblib.load(feat_path)
            pairs = sorted(zip(feat, rf.feature_importances_.tolist()),
                           key=lambda x: x[1], reverse=True)[:15]
            return jsonify({"ok": True, "ticker": ticker, "interval": interval,
                            "features": [{"name": n, "importance": round(v, 4)} for n, v in pairs]})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 400

    # ── Short interest + institutional holders ─────────────────────────────────

    @app.route("/api/short-interest/<ticker>")
    @login_required
    def api_short_interest(ticker):
        try:
            import yfinance as yf
            t    = yf.Ticker(ticker.upper())
            info = t.info
            holders = []
            try:
                ih = t.institutional_holders
                if ih is not None and not ih.empty:
                    for _, row in ih.head(6).iterrows():
                        holders.append({
                            "holder": str(row.get("Holder", "")),
                            "shares": int(row.get("Shares", 0)),
                            "pct":    round(float(row.get("% Out", 0)) * 100, 2),
                        })
            except Exception:
                pass
            return jsonify({
                "ok": True, "ticker": ticker.upper(),
                "short_pct":            round(float((info.get("shortPercentOfFloat") or 0) * 100), 2),
                "short_ratio":          round(float(info.get("shortRatio") or 0), 2),
                "float_shares":         int(info.get("floatShares") or 0),
                "institutional_pct":    round(float((info.get("heldPercentInstitutions") or 0) * 100), 1),
                "insider_pct":          round(float((info.get("heldPercentInsiders") or 0) * 100), 1),
                "top_holders":          holders,
            })
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 400

    # ── Options chain ──────────────────────────────────────────────────────────

    @app.route("/api/options/<ticker>")
    @login_required
    def api_options(ticker):
        try:
            import yfinance as yf
            t    = yf.Ticker(ticker.upper())
            exps = t.options
            if not exps:
                return jsonify({"ok": False, "error": "No options data available"})
            exp   = request.args.get("exp") or exps[0]
            chain = t.option_chain(exp)
            price = float(t.fast_info.last_price or 0)

            def _fmt(df, otype):
                rows = []
                for _, r in df.iterrows():
                    try:
                        vol = r.get("volume", 0)
                        oi  = r.get("openInterest", 0)
                        rows.append({
                            "strike": float(r.get("strike", 0) or 0),
                            "iv":     round(float(r.get("impliedVolatility", 0) or 0) * 100, 1),
                            "volume": int(vol) if vol == vol else 0,
                            "oi":     int(oi)  if oi  == oi  else 0,
                            "bid":    float(r.get("bid", 0) or 0),
                            "ask":    float(r.get("ask", 0) or 0),
                            "itm":    bool(r.get("inTheMoney", False)),
                            "type":   otype,
                        })
                    except Exception:
                        pass
                return rows

            calls = _fmt(chain.calls, "call")
            puts  = _fmt(chain.puts,  "put")
            near  = sorted(calls + puts, key=lambda x: abs(x["strike"] - price))[:20]
            return jsonify({
                "ok": True, "ticker": ticker.upper(), "expiry": exp,
                "expirations": list(exps[:6]), "price": round(price, 2),
                "calls": calls[:15], "puts": puts[:15], "near_atm": near,
            })
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 400

    # ── Dividends ──────────────────────────────────────────────────────────────

    @app.route("/api/dividends/<ticker>")
    @login_required
    def api_dividends(ticker):
        try:
            import yfinance as yf
            t    = yf.Ticker(ticker.upper())
            info = t.info
            divs = t.dividends
            history = []
            if divs is not None and not divs.empty:
                for dt, val in divs.tail(12).items():
                    history.append({"date": str(dt.date()), "amount": round(float(val), 4)})
            return jsonify({
                "ok": True, "ticker": ticker.upper(),
                "dividend_yield":   round(float((info.get("dividendYield") or 0) * 100), 2),
                "forward_annual":   round(float(info.get("dividendRate") or 0), 4),
                "payout_ratio":     round(float((info.get("payoutRatio") or 0) * 100), 1),
                "ex_dividend_date": str(info.get("exDividendDate") or ""),
                "history":          list(reversed(history)),
            })
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 400

    # ── Insider transactions ───────────────────────────────────────────────────

    @app.route("/api/insiders/<ticker>")
    @login_required
    def api_insiders(ticker):
        try:
            import yfinance as yf
            t    = yf.Ticker(ticker.upper())
            rows = []
            try:
                ins = t.insider_transactions
                if ins is not None and not ins.empty:
                    for _, r in ins.head(10).iterrows():
                        rows.append({
                            "insider":  str(r.get("Insider", "")),
                            "relation": str(r.get("Relation", "")),
                            "date":     str(r.get("Start Date", "")),
                            "shares":   int(r.get("Shares", 0) or 0),
                            "value":    int(r.get("Value", 0) or 0),
                            "type":     str(r.get("Transaction", "")),
                        })
            except Exception:
                pass
            return jsonify({"ok": True, "ticker": ticker.upper(), "transactions": rows})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 400

    # ── Analyst targets ────────────────────────────────────────────────────────

    @app.route("/api/analyst-targets/<ticker>")
    @login_required
    def api_analyst_targets(ticker):
        try:
            import yfinance as yf
            info = yf.Ticker(ticker.upper()).info
            return jsonify({
                "ok": True, "ticker": ticker.upper(),
                "current_price":  round(float(info.get("currentPrice") or 0), 2),
                "target_mean":    round(float(info.get("targetMeanPrice") or 0), 2),
                "target_high":    round(float(info.get("targetHighPrice") or 0), 2),
                "target_low":     round(float(info.get("targetLowPrice") or 0), 2),
                "target_median":  round(float(info.get("targetMedianPrice") or 0), 2),
                "recommendation": str(info.get("recommendationKey") or "n/a"),
                "analyst_count":  int(info.get("numberOfAnalystOpinions") or 0),
            })
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 400

    # ── Batch price snapshot ───────────────────────────────────────────────────

    @app.route("/api/prices/batch")
    @login_required
    def api_prices_batch():
        from market_data import get_quotes_verified
        tickers = [t.upper() for t in request.args.getlist("t")[:60]]
        result = {}
        for t, q in get_quotes_verified(tickers).items():
            result[t] = ({"price": q["price"], "change_pct": q["pct"],
                          "source": q["source"], "verified": q["verified"],
                          "divergence_pct": q["divergence_pct"],
                          "conf": q["conf"], "conf_pct": q["conf_pct"],
                          "market_closed": q["market_closed"]}
                         if q else None)
        return jsonify(result)

    # ── SSE real-time price stream ─────────────────────────────────────────────

    @app.route("/api/stream/prices")
    @login_required
    def stream_prices():
        tickers = [t.upper() for t in (request.args.getlist("t") or
                                       ["AAPL", "MSFT", "TSLA", "NVDA", "SPY"])[:15]]

        def generate():
            while True:
                batch = {}
                for t in tickers:
                    q = _cached_quote(t)
                    if q:
                        batch[t] = q
                yield f"data: {_json.dumps(batch)}\n\n"
                time.sleep(15)

        return Response(
            stream_with_context(generate()),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache",
                     "X-Accel-Buffering": "no"},
        )
