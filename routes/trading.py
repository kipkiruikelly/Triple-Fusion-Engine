"""routes/trading.py, MT5, quick-trade API, performance, backtest."""

import logging
import os
from datetime import date, datetime

from flask import render_template, request, jsonify, redirect, url_for
from flask_login import login_required, current_user

from extensions import db
from utils import pro_required, PLUS_BACKTEST_DAILY, PLUS_BACKTEST_PERIODS, award_xp

logger = logging.getLogger(__name__)


def register_trading_routes(app):

    from mt5_trading import trader as mt5_trader
    from predictor import run_prediction

    _API_DAILY_LIMIT = 100

    # ── MT5 dashboard ──────────────────────────────────────────────────────────



    @app.route("/api/live/summary")
    @login_required
    def api_live_summary():
        # Placeholder live metrics matching the paper trading structure
        return jsonify({
            "ok": True,
            "simulated": False,
            "currency": "USD",
            "enabled": getattr(mt5_trader, "connected", False),
            "started_at": None,
            "min_trades": 10,
            "assumptions": {
                "note": "Real execution metrics from MT5 terminal."
            },
            "strategies": [
                {
                    "strategy": "ml_ensemble",
                    "starting_balance": 10000,
                    "equity": 10000,
                    "open_positions": 0,
                    "exposure_pct": 0,
                    "metrics": {
                        "trades": 0,
                        "min_trades": 10,
                        "sufficient": False
                    },
                    "by_asset_class": {},
                    "by_model": {},
                    "equity_curve": []
                },
                {
                    "strategy": "alpha_rules",
                    "starting_balance": 10000,
                    "equity": 10000,
                    "open_positions": 0,
                    "exposure_pct": 0,
                    "metrics": {
                        "trades": 0,
                        "min_trades": 10,
                        "sufficient": False
                    },
                    "by_asset_class": {},
                    "by_model": {},
                    "equity_curve": []
                }
            ]
        })

    @app.route("/api/live/trades")
    @login_required
    def api_live_trades():
        return jsonify({"ok": True, "simulated": False, "page": 1, "total": 0, "trades": []})




    @app.route("/mt5/connect", methods=["POST"])
    @pro_required
    def mt5_connect():
        data               = request.get_json() or {}
        account            = int(data.get("account", 0))
        password           = data.get("password", "")
        server             = data.get("server", "")
        host               = data.get("host", "localhost")
        port               = int(data.get("port", 18812))
        metaapi_token      = data.get("metaapi_token", "")
        metaapi_account_id = data.get("metaapi_account_id", "")
        return jsonify(mt5_trader.connect(account, password, server, host, port,
                                          metaapi_token, metaapi_account_id))

    @app.route("/mt5/disconnect", methods=["POST"])
    @pro_required
    def mt5_disconnect():
        mt5_trader.disconnect()
        return jsonify({"ok": True})

    @app.route("/mt5/start", methods=["POST"])
    @pro_required
    def mt5_start():
        data      = request.get_json() or {}
        symbol    = data.get("symbol", "EURUSD")
        timeframe = data.get("timeframe", "M5")
        risk_pct  = float(data.get("risk_pct", 1.0))
        interval  = int(data.get("interval", 60))
        use_ml    = bool(data.get("use_ml", True))
        return jsonify(mt5_trader.start_trading(symbol, timeframe, risk_pct, interval, use_ml))

    @app.route("/mt5/stop", methods=["POST"])
    @pro_required
    def mt5_stop():
        return jsonify(mt5_trader.stop_trading())

    @app.route("/mt5/close_all", methods=["POST"])
    @pro_required
    def mt5_close_all():
        data   = request.get_json() or {}
        symbol = data.get("symbol", "EURUSD")
        n      = mt5_trader.close_all(symbol)
        return jsonify({"ok": True, "closed": n})

    @app.route("/mt5/status")
    @pro_required
    def mt5_status():
        return jsonify(mt5_trader.get_status())

    # ── Quick Trade API ────────────────────────────────────────────────────────

    @app.route("/api/trade/connect", methods=["POST"])
    @login_required
    def trade_connect():
        if not current_user.is_pro:
            return jsonify({"ok": False, "error": "Pro required"}), 403
        data = request.get_json() or {}
        mode = data.get("mode", "paper")
        if mode == "metaapi":
            result = mt5_trader.connect(0, "", "",
                                        metaapi_token=data.get("token", ""),
                                        metaapi_account_id=data.get("account_id", ""))
        elif mode == "paper":
            result = mt5_trader.connect(0, "", "")
        else:
            return jsonify({"ok": False, "error": "Unknown mode"}), 400
        return jsonify(result)

    @app.route("/api/trade/disconnect", methods=["POST"])
    @login_required
    def trade_disconnect():
        if not current_user.is_pro:
            return jsonify({"ok": False, "error": "Pro required"}), 403
        mt5_trader.disconnect()
        return jsonify({"ok": True})

    @app.route("/api/trade/status", methods=["GET"])
    @login_required
    def trade_status():
        if not current_user.is_pro:
            return jsonify({"ok": False, "connected": False}), 403
        if not mt5_trader.connected:
            mt5_trader._auto_connect_live()
        s = mt5_trader.get_status()
        return jsonify({
            "ok":        True,
            "connected": s["connected"],
            "mode":      s.get("mode", "none"),
            "account":   s.get("account", {}),
            "positions": s.get("positions", []),
        })

    @app.route("/api/trade/order", methods=["POST"])
    @login_required
    def trade_order():
        if not current_user.is_pro:
            return jsonify({"ok": False, "error": "Pro required"}), 403
        if not mt5_trader.connected:
            mt5_trader._auto_connect_live()
        if not mt5_trader.connected:
            return jsonify({"ok": False,
                            "error": "Not connected to MT5. Please check configuration."}), 400
        data     = request.get_json() or {}
        ticker   = data.get("ticker", "").upper()
        action   = data.get("action", "").upper()
        risk_pct = float(data.get("risk_pct", 1.0))
        atr      = float(data.get("atr", 0))
        order_type = data.get("order_type", "MARKET").upper()
        target_price = data.get("target_price")
        if target_price is not None:
            try:
                target_price = float(target_price)
            except ValueError:
                target_price = None

        if action not in ("BUY", "SELL"):
            return jsonify({"ok": False, "error": "action must be BUY or SELL"}), 400
        if not ticker:
            return jsonify({"ok": False, "error": "ticker required"}), 400
        try:
            result = mt5_trader.place_order(ticker, action, risk_pct, atr, order_type_str=order_type, target_price=target_price)
            if result.get("ok"):
                mt5_trader.refresh_account()
            return jsonify(result)
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 400

    @app.route("/api/trade/close", methods=["POST"])
    @login_required
    def trade_close():
        if not current_user.is_pro:
            return jsonify({"ok": False, "error": "Pro required"}), 403
        if not mt5_trader.connected:
            return jsonify({"ok": False, "error": "Not connected"}), 400
        data   = request.get_json() or {}
        ticker = data.get("ticker", "").upper()
        n      = mt5_trader.close_all(ticker)
        mt5_trader.refresh_account()
        return jsonify({"ok": True, "closed": n})

    # ── API key authenticated prediction (v1) ──────────────────────────────────

    @app.route("/api/v1/predict/<ticker>", methods=["GET"])
    def api_v1_predict(ticker):
        from extensions import db
        from models import ApiKey, User
        key_str = request.args.get("key") or request.headers.get("X-API-Key", "")
        if not key_str:
            return jsonify({"status": "error",
                            "message": "API key required. Pass ?key=YOUR_KEY"}), 401
        ak = ApiKey.query.filter_by(key=key_str).first()
        if not ak:
            return jsonify({"status": "error", "message": "Invalid API key"}), 401
        owner = db.session.get(User, ak.user_id)
        if not owner:
            return jsonify({"status": "error", "message": "Invalid API key"}), 401
        today = date.today()
        if ak.calls_date != today:
            ak.calls_today = 0
            ak.calls_date  = today
        if not owner.is_pro and ak.calls_today >= _API_DAILY_LIMIT:
            return jsonify({"status": "error",
                            "message": f"Daily API limit of {_API_DAILY_LIMIT} reached. Upgrade to Pro."}), 429
        ak.calls_today += 1
        ak.last_used    = datetime.utcnow()
        db.session.commit()
        interval = request.args.get("interval", "1d")
        if interval not in ("1d", "1h", "15m"):
            interval = "1d"
        try:
            result = run_prediction(ticker.upper(), interval)
            for key in ["chart_dates", "chart_prices", "chart_sma7", "chart_sma21", "lw_chart"]:
                result.pop(key, None)
            return jsonify({"status": "success", "data": result})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 400

    # ── Performance / backtest ─────────────────────────────────────────────────

    @app.route("/api/performance")
    def api_performance():
        import sqlite3
        import json as _json
        import numpy as _np
        import pandas as _pd
        BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        db_path  = os.path.join(BASE_DIR, "Data", "paper_trades.db")
        bt_path  = os.path.join(BASE_DIR, "Data", "backtest_summary.json")
        stats = {
            "started": None, "total_ret": 0, "n_trades": 0, "win_rate": 0,
            "profit_factor": 0, "sharpe": 0, "sortino": 0, "max_dd": 0,
            "equity": 10_000, "trades": [], "equity_dates": "[]", "equity_vals": "[]",
            "backtest_dates": "[]", "backtest_vals": "[]", "backtest_tickers": [],
        }
        if os.path.exists(db_path):
            try:
                conn = sqlite3.connect(db_path)
                conn.row_factory = sqlite3.Row
                closed  = conn.execute(
                    "SELECT * FROM paper_positions WHERE status='closed' ORDER BY exit_date"
                ).fetchall()
                eq_rows = conn.execute(
                    "SELECT date, equity FROM paper_equity ORDER BY date"
                ).fetchall()
                conn.close()
                if eq_rows:
                    eq_s = _pd.Series(
                        [r["equity"] for r in eq_rows],
                        index=_pd.to_datetime([r["date"] for r in eq_rows])
                    )
                    stats["equity"]       = round(float(eq_s.iloc[-1]), 2)
                    stats["total_ret"]    = round((eq_s.iloc[-1] - 10_000) / 10_000 * 100, 2)
                    stats["started"]      = eq_rows[0]["date"]
                    stats["equity_dates"] = [r["date"] for r in eq_rows]
                    stats["equity_vals"]  = [round(r["equity"], 2) for r in eq_rows]
                    dr    = eq_s.pct_change().dropna()
                    if dr.std() > 0:
                        stats["sharpe"]   = round(float(dr.mean() / dr.std() * _np.sqrt(252)), 3)
                    dside = dr[dr < 0]
                    if len(dside) > 1 and dside.std() > 0:
                        stats["sortino"]  = round(float(dr.mean() / dside.std() * _np.sqrt(252)), 3)
                    peak = eq_s.cummax()
                    stats["max_dd"] = round(float(((eq_s - peak) / peak).min() * 100), 2)
                if closed:
                    wins   = [r for r in closed if (r["pnl"] or 0) > 0]
                    losses = [r for r in closed if (r["pnl"] or 0) <= 0]
                    gw     = sum(r["pnl"] for r in wins)
                    gl     = abs(sum(r["pnl"] for r in losses))
                    stats["n_trades"]      = len(closed)
                    stats["win_rate"]      = round(len(wins) / len(closed) * 100, 1)
                    stats["profit_factor"] = round(gw / gl if gl > 0 else 0, 2)
                    stats["trades"]        = [dict(r) for r in closed[-20:]]
            except Exception:
                pass
        if os.path.exists(bt_path):
            try:
                with open(bt_path) as f:
                    bt = _json.load(f)
                combined = bt.get("combined", [])
                if combined:
                    stats["backtest_dates"] = [p["date"] for p in combined]
                    stats["backtest_vals"]  = [p["value"] for p in combined]
                ticker_rows = []
                for t, td in bt.get("tickers", {}).items():
                    m = td.get("metrics", {})
                    if m.get("n_trades", 0) > 0:
                        ticker_rows.append({
                            "ticker":        t,
                            "n_trades":      m["n_trades"],
                            "win_rate":      m["win_rate"],
                            "profit_factor": m["profit_factor"],
                            "sharpe":        m["sharpe"],
                            "total_return":  m["total_return"],
                            "bh_return":     m["bh_return"],
                        })
                stats["backtest_tickers"] = ticker_rows
            except Exception:
                pass
        return jsonify({"ok": True, "stats": stats})

    @app.route("/api/backtest", methods=["POST"])
    @login_required
    def api_backtest():
        if not current_user.is_plus:
            return jsonify({"ok": False, "error": "Backtesting requires a Plus or Pro plan."}), 403
        data     = request.get_json() or {}
        ticker   = data.get("ticker", "AAPL").upper()
        interval = data.get("interval", "1d")
        period   = data.get("period", "2y")
        capital  = float(data.get("initial_capital", 10_000))
        risk_pct = float(data.get("risk_pct", 1.0))
        if interval not in ("1d", "1h"):
            return jsonify({"ok": False, "error": "interval must be 1d or 1h"}), 400
        if period not in ("6mo", "1y", "2y"):
            return jsonify({"ok": False, "error": "period must be 6mo, 1y, or 2y"}), 400
        if not current_user.is_pro:
            # Plus tier: capped history range and one run/day. Pro/Enterprise
            # keep the full range and unlimited runs checked above.
            if period not in PLUS_BACKTEST_PERIODS:
                return jsonify({"ok": False,
                                "error": "The Plus plan supports 6mo or 1y of history. Upgrade to Pro for 2y."}), 403
            today = date.today()
            if current_user.last_backtest_date != today:
                current_user.backtests_today    = 0
                current_user.last_backtest_date = today
            if current_user.backtests_today >= PLUS_BACKTEST_DAILY:
                return jsonify({"ok": False,
                                "error": f"The Plus plan allows {PLUS_BACKTEST_DAILY} backtest run per day. "
                                         "Upgrade to Pro for unlimited runs."}), 429
            current_user.backtests_today += 1
            db.session.commit()
        if not (100 <= capital <= 10_000_000):
            return jsonify({"ok": False, "error": "Capital must be between $100 and $10,000,000"}), 400
        if not (0.1 <= risk_pct <= 10):
            return jsonify({"ok": False, "error": "Risk must be between 0.1% and 10%"}), 400
        try:
            from backtester import run_backtest
            result = run_backtest(ticker, interval, period, capital, risk_pct)
            result["ok"] = True
            try:
                award_xp(current_user, 10)
            except Exception:
                db.session.rollback()
            return jsonify(result)
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        except Exception as e:
            logger.exception("Backtest error for %s", ticker)
            return jsonify({"ok": False, "error": f"Backtest failed: {str(e)}"}), 500
