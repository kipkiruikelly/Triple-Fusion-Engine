"""
routes/api.py
REST API endpoints for the Triple-Fusion-Engine dashboard.

Provides JSON APIs consumed by the frontend JavaScript modules:
  /api/dashboard      - Portfolio summary, P&L, positions count, win rate
  /api/predictions    - Prediction history and signal generation
  /api/watchlist      - User watchlist CRUD
  /api/leaderboard    - Global rankings (weekly/monthly/all-time)
  /api/competitions   - Competition listing, entry, leaderboard
  /api/achievements   - User achievements with progress
  /api/notifications  - Notification center (list, mark read)
  /api/settings       - User preferences (theme, risk, notifications)
  /api/profile        - User profile with subscription details

All endpoints require authentication (Flask-Login). Rate-limited
per the user's subscription tier.

Author: BullLogic
"""

import logging
from datetime import date, datetime, timedelta
from flask import Blueprint, jsonify, request, current_app
from flask_login import login_required, current_user

logger = logging.getLogger(__name__)

api_bp = Blueprint("api", __name__, url_prefix="/api")


# ── Helpers ──────────────────────────────────────────────────────────────────────

def _json_ok(data=None, **kwargs):
    """Standardized success response."""
    resp = {"ok": True}
    if data is not None:
        resp["data"] = data
    resp.update(kwargs)
    return jsonify(resp)


def _json_error(message, status=400):
    """Standardized error response."""
    return jsonify({"ok": False, "error": message}), status


def _json_simulated(data=None, **kwargs):
    """Success response for endpoints backed by demonstration data.

    Every payload that is not driven by real user/market state MUST go
    through this helper so no client can mistake it for live data.
    """
    # NOTE: returns simulated data - replace with live source
    resp = {"ok": True, "simulated": True, "data_source": "simulated",
            "note": "Demonstration data - not live account or market state."}
    if data is not None:
        resp["data"] = data
    resp.update(kwargs)
    return jsonify(resp)


# ── Dashboard ───────────────────────────────────────────────────────────────────

@api_bp.route("/dashboard")
@login_required
def dashboard():
    """Return aggregated dashboard data: portfolio, positions, win rate."""
    try:
        # NOTE: returns simulated data - replace with live source
        # Portfolio snapshot defaults are placeholders; real numbers are
        # filled in below only when a trading engine is connected.
        portfolio = {
            "equity": 10_000.0,  # would come from mt5_trading or paper_engine
            "balance": 10_000.0,
            "daily_pnl": 0.0,
            "change_pct": 0.0,
            "win_rate": 0.0,
            "open_positions": 0,
        }

        # Try to get real data from the trading engine if available
        engine_live = False
        try:
            from app import _trading_engine
            if _trading_engine and _trading_engine.connected:
                acct = _trading_engine.account
                portfolio["equity"] = acct.get("equity", portfolio["equity"])
                portfolio["balance"] = acct.get("balance", portfolio["balance"])
                engine_live = True
        except Exception:
            pass

        # Recent predictions count today
        predictions_today = getattr(current_user, "predictions_today", 0)

        # Placeholder portfolio numbers must be labeled as such.
        respond = _json_ok if engine_live else _json_simulated
        return respond({
            "portfolio": portfolio,
            "predictions_today": predictions_today,
            "plan": getattr(current_user, "plan", "free"),
        })
    except Exception as e:
        logger.exception("Dashboard API error")
        return _json_error(str(e), 500)


# ── Predictions ─────────────────────────────────────────────────────────────────

@api_bp.route("/predictions/recent")
@login_required
def predictions_recent():
    """Return recent predictions for the current user."""
    try:
        limit = request.args.get("limit", 10, type=int)
        from models import PredictionHistory
        predictions = (
            PredictionHistory.query
            .filter_by(user_id=current_user.id)
            .order_by(PredictionHistory.predicted_at.desc())
            .limit(limit)
            .all()
        )
        return _json_ok({
            "predictions": [
                {
                    "ticker": p.ticker,
                    "interval": p.interval,
                    "direction": p.direction,
                    "confidence": p.confidence,
                    "current_price": p.current_price,
                    "predicted_price": p.lr_pred,
                    "created_at": p.predicted_at.isoformat() if p.predicted_at else None,
                }
                for p in predictions
            ]
        })
    except Exception as e:
        logger.exception("Predictions API error")
        return _json_error(str(e), 500)


@api_bp.route("/predictions/signal", methods=["POST"])
@login_required
def predictions_signal():
    """Generate a live prediction signal for a ticker."""
    try:
        data = request.get_json(silent=True) or {}
        ticker = data.get("ticker", "").strip().upper()
        interval = data.get("interval", "1d")

        if not ticker:
            return _json_error("ticker is required")

        from predictor import run_prediction
        result = run_prediction(ticker, interval)

        # Inject sentiment if available
        try:
            from sentiment import get_sentiment_signal
            sentiment = get_sentiment_signal(ticker)
            result["sentiment"] = sentiment
        except Exception:
            result["sentiment"] = None

        # Inject economic calendar alert
        try:
            from economic_calendar import event_volatility_warning
            warning = event_volatility_warning(days_ahead=3)
            result["economic_warning"] = warning
        except Exception:
            result["economic_warning"] = None

        return _json_ok(result)
    except ValueError as e:
        return _json_error(str(e), 400)
    except Exception as e:
        logger.exception("Signal API error")
        return _json_error(str(e), 500)


# ── Watchlist ────────────────────────────────────────────────────────────────────

@api_bp.route("/watchlist")
@login_required
def watchlist_get():
    """Return user's watchlist with current prices.

    Add/remove live in routes/predictions.py (/api/watchlist/add and
    /api/watchlist/remove) - the same WatchlistItem table backs both.
    """
    try:
        from models import WatchlistItem
        items = WatchlistItem.query.filter_by(user_id=current_user.id).all()
        tickers = [w.ticker for w in items]

        # Fetch current prices (would use cached/mocked data)
        prices = {}
        if tickers:
            try:
                import yfinance as yf
                data = yf.download(tickers, period="1d", auto_adjust=True, progress=False)
                for t in tickers:
                    if t in data["Close"].columns:
                        prices[t] = round(float(data["Close"][t].iloc[-1]), 2)
            except Exception:
                pass

        return _json_ok({
            "watchlist": [
                {
                    "ticker": w.ticker,
                    "added_at": w.added_at.isoformat() if w.added_at else None,
                    "price": prices.get(w.ticker, None),
                }
                for w in items
            ]
        })
    except Exception as e:
        logger.exception("Watchlist API error")
        return _json_error(str(e), 500)


# ── AI Robots ───────────────────────────────────────────────────────────────────

@api_bp.route("/bots", methods=["GET"])
@login_required
def get_bots():
    """Return all active bots and current user's subscriptions."""
    try:
        from models import TradingBot, UserBotSubscription
        bots = TradingBot.query.filter_by(is_active=True).all()
        subs = {s.bot_id for s in UserBotSubscription.query.filter_by(user_id=current_user.id).all()}
        
        return _json_ok({
            "bots": [
                {
                    "id": b.id,
                    "name": b.name,
                    "description": b.description,
                    "asset_class": b.asset_class,
                    "is_subscribed": b.id in subs
                }
                for b in bots
            ]
        })
    except Exception as e:
        logger.exception("Bots API error")
        return _json_error(str(e), 500)

@api_bp.route("/bots/subscribe", methods=["POST"])
@login_required
def toggle_bot_subscription():
    """Toggle subscription to a bot."""
    try:
        from models import TradingBot, UserBotSubscription
        from extensions import db
        bot_id = request.form.get("bot_id", type=int)
        if not bot_id:
            return _json_error("Missing bot_id", 400)
            
        bot = TradingBot.query.get(bot_id)
        if not bot:
            return _json_error("Bot not found", 404)
            
        sub = UserBotSubscription.query.filter_by(user_id=current_user.id, bot_id=bot_id).first()
        if sub:
            db.session.delete(sub)
            is_subscribed = False
        else:
            new_sub = UserBotSubscription(user_id=current_user.id, bot_id=bot_id)
            db.session.add(new_sub)
            is_subscribed = True
            
        db.session.commit()
        return _json_ok({"is_subscribed": is_subscribed})
    except Exception as e:
        logger.exception("Bot subscription toggle error")
        db.session.rollback()
        return _json_error(str(e), 500)

# ── Leaderboard ─────────────────────────────────────────────────────────────────

def _trader_leaderboard(limit=10):
    """Rank real (user, strategy) paper-trading portfolios by Sharpe ratio,
    using the exact same compute_metrics() the platform's own public
    strategy reports use - not a second, disconnected formula. Only
    opted-in users with >= paper_engine.MIN_TRADES closed trades for a
    given strategy are eligible, the same "insufficient data" honesty gate
    the engine already enforces everywhere else. See
    PAPER_TRADING_PHASE2_DESIGN.md for why Sharpe (not raw return) is the
    ranking metric."""
    import paper_engine
    from models import User
    from extensions import db

    cfg = paper_engine.load_config(db)
    rows = []
    for u in User.query.filter_by(paper_trading_opted_in=True).all():
        for strategy in paper_engine.STRATEGIES:
            report = paper_engine.strategy_report(db, strategy, cfg, user_id=u.id)
            m = report["metrics"]
            if not m["sufficient"]:
                continue
            rows.append({
                "username": u.username,
                "strategy": strategy,
                "sharpe": m["sharpe"],
                "return_pct": m["total_return_pct"],
                "win_rate": m["win_rate_pct"],
                "trades": m["trades"],
                "equity": report["equity"],
            })
    # Sharpe primary, return_pct as tiebreak; a None Sharpe (zero-variance
    # equity curve, an edge case compute_metrics already handles honestly)
    # sorts last rather than crashing or being mistaken for a zero score.
    rows.sort(key=lambda r: (r["sharpe"] if r["sharpe"] is not None else float("-inf"),
                             r["return_pct"] or 0), reverse=True)
    for i, r in enumerate(rows):
        r["rank"] = i + 1
    return rows[:limit]


@api_bp.route("/leaderboard/users")
@login_required
def leaderboard_users():
    """Real per-user, per-strategy paper-trading rankings by Sharpe ratio.
    All-time only - no weekly/monthly slicing yet (would need per-period
    trade filtering, not built in this phase).

    (/api/leaderboard without a suffix is the model-accuracy leaderboard
    in routes/predictions.py - a different, unrelated ranking.)
    """
    try:
        limit = request.args.get("limit", 10, type=int)
        import paper_engine
        rows = _trader_leaderboard(limit=limit)
        return _json_ok(leaderboard=rows, min_trades=paper_engine.MIN_TRADES,
                        total_ranked=len(rows))
    except Exception as e:
        logger.exception("Leaderboard API error")
        return _json_error(str(e), 500)


# ── Competitions ────────────────────────────────────────────────────────────────

@api_bp.route("/competitions")
@login_required
def competitions_list():
    """Return competition listings."""
    try:
        status = request.args.get("status", "active")  # active, upcoming, completed

        # Mock competitions (in production: query CompetitionModel table)
        mock_comps = [
            {
                "id": "comp_001", "name": "July Trading Showdown",
                "start_date": "2026-07-01", "end_date": "2026-07-31",
                "participants": 48, "status": "active",
                "initial_balance": 10_000.0,
                "leader": {"username": "AlphaTrader", "return_pct": 12.5},
            },
            {
                "id": "comp_002", "name": "Summer Bull Run",
                "start_date": "2026-06-01", "end_date": "2026-08-31",
                "participants": 89, "status": "active",
                "initial_balance": 25_000.0,
                "leader": {"username": "QuantKing", "return_pct": 18.3},
            },
            {
                "id": "comp_003", "name": "August Crypto Cup",
                "start_date": "2026-08-01", "end_date": "2026-08-31",
                "participants": 0, "status": "upcoming",
                "initial_balance": 5_000.0,
                "leader": None,
            },
        ]

        filtered = [c for c in mock_comps if c["status"] == status] if status != "all" else mock_comps

        return _json_simulated({"competitions": filtered})
    except Exception as e:
        logger.exception("Competitions API error")
        return _json_error(str(e), 500)


@api_bp.route("/competitions/<comp_id>/leaderboard")
@login_required
def competition_leaderboard(comp_id):
    """Return leaderboard for a specific competition."""
    try:
        # Mock: would query CompetitionEntry table
        return _json_simulated({
            "competition_id": comp_id,
            "leaderboard": [
                {"rank": 1, "username": "AlphaTrader", "return_pct": 12.5, "equity": 11250.0},
                {"rank": 2, "username": "BullRider", "return_pct": 9.2, "equity": 10920.0},
                {"rank": 3, "username": "QuantKing", "return_pct": 7.8, "equity": 10780.0},
            ]
        })
    except Exception as e:
        logger.exception("Competition leaderboard error")
        return _json_error(str(e), 500)


# ── Achievements ────────────────────────────────────────────────────────────────

@api_bp.route("/achievements/user")
@login_required
def achievements_user():
    """Return user's achievement progress."""
    try:
        from models import UserAchievement
        from gamification import ACHIEVEMENTS
        unlocked = UserAchievement.query.filter_by(user_id=current_user.id).all()
        unlocked_ids = [a.achievement_id for a in unlocked]

        return _json_ok({
            "unlocked": unlocked_ids,
            "total": len(ACHIEVEMENTS),
            "points": len(unlocked_ids) * 10,  # simplified
        }, note="Achievement awarding is not yet automated; unlocked list "
                "reflects only rows explicitly written to user_achievement.")
    except Exception as e:
        logger.exception("Achievements API error")
        return _json_error(str(e), 500)


# ── Notifications ───────────────────────────────────────────────────────────────

# NOTE: GET /api/notifications is served by routes/notifications.py from
# the real Notification table (that route registers first). The mock that
# used to live here was dead, shadowed code and has been removed.


@api_bp.route("/notifications/count")
@login_required
def notifications_count():
    """Unread notification count for the header badge (_base.html)."""
    try:
        from models import Notification
        count = Notification.query.filter_by(user_id=current_user.id, read=False).count()
        return _json_ok(count=count)
    except Exception:
        return _json_ok(count=0)


@api_bp.route("/notifications/mark-read", methods=["POST"])
@login_required
def notifications_mark_read():
    """Mark notification(s) as read."""
    data = request.get_json(silent=True) or {}
    notif_id = data.get("id")
    mark_all = data.get("all", False)
    return _json_ok({"marked_read": True},
                    note="Not persisted - notification storage is not wired up yet.")


# ── Settings ─────────────────────────────────────────────────────────────────────

@api_bp.route("/settings")
@login_required
def settings_get():
    """Return current user settings."""
    try:
        from models import UserPreferences
        prefs = UserPreferences.query.filter_by(user_id=current_user.id).first()

        return _json_ok({
            "theme": prefs.theme if prefs else "dark",
            "digest_enabled": prefs.digest_enabled if prefs else False,
            "default_ticker": prefs.default_ticker if prefs else "AAPL",
            "timezone": prefs.timezone if prefs else "UTC",
            "risk_intro_seen": prefs.risk_intro_seen if prefs else False,
        })
    except Exception as e:
        logger.exception("Settings API error")
        return _json_error(str(e), 500)


@api_bp.route("/settings", methods=["POST"])
@login_required
def settings_update():
    """Update user settings."""
    try:
        data = request.get_json(silent=True) or {}
        from models import UserPreferences
        from extensions import db

        prefs = UserPreferences.query.filter_by(user_id=current_user.id).first()
        if not prefs:
            prefs = UserPreferences(user_id=current_user.id)
            db.session.add(prefs)

        if "theme" in data:
            prefs.theme = data["theme"]
        if "digest_enabled" in data:
            prefs.digest_enabled = data["digest_enabled"]
        if "default_ticker" in data:
            prefs.default_ticker = data["default_ticker"]
        if "timezone" in data:
            prefs.timezone = data["timezone"]

        db.session.commit()
        return _json_ok({"updated": True})
    except Exception as e:
        logger.exception("Settings update error")
        return _json_error(str(e), 500)


# ── Profile ──────────────────────────────────────────────────────────────────────

@api_bp.route("/profile")
@login_required
def profile_get():
    """Return current user profile."""
    return _json_ok({
        "username": current_user.username,
        "email": current_user.email,
        "plan": getattr(current_user, "plan", "free"),
        "created_at": current_user.created_at.isoformat() if current_user.created_at else None,
        "predictions_today": getattr(current_user, "predictions_today", 0),
        "email_verified": getattr(current_user, "email_verified", False),
    })


# ── Market Movers ───────────────────────────────────────────────────────────────

@api_bp.route("/market/movers")
@login_required
def market_movers():
    """Return top market movers."""
    try:
        limit = request.args.get("limit", 5, type=int)
        # Mock data (would fetch from yfinance or cache)
        movers = [
            {"ticker": "NVDA", "name": "NVIDIA Corp", "change_pct": 8.5},
            {"ticker": "TSLA", "name": "Tesla Inc", "change_pct": 5.2},
            {"ticker": "AMD", "name": "Advanced Micro Devices", "change_pct": -3.8},
            {"ticker": "META", "name": "Meta Platforms", "change_pct": 3.1},
            {"ticker": "AAPL", "name": "Apple Inc", "change_pct": -2.4},
        ]
        return _json_simulated({"movers": movers[:limit]})
    except Exception as e:
        return _json_error(str(e), 500)


# ── Activity Feed ───────────────────────────────────────────────────────────────

@api_bp.route("/activity/recent")
@login_required
def activity_recent():
    """Return recent activity for the current user."""
    try:
        limit = request.args.get("limit", 10, type=int)
        activities = [
            {"type": "trade", "message": "BUY AAPL executed @ $185.50", "timestamp": datetime.now().isoformat()},
            {"type": "prediction", "message": "NVDA prediction: BUY (72% confidence)", "timestamp": (datetime.now() - timedelta(minutes=30)).isoformat()},
            {"type": "achievement", "message": "Achievement unlocked: Hot Hand - 5 wins in a row!", "timestamp": (datetime.now() - timedelta(hours=1)).isoformat()},
            {"type": "alert", "message": "FOMC rate decision in 3 days - consider reducing positions", "timestamp": (datetime.now() - timedelta(hours=3)).isoformat()},
            {"type": "system", "message": "Daily loss limit reset for new trading day", "timestamp": (datetime.now() - timedelta(hours=8)).isoformat()},
        ]
        return _json_simulated({"activities": activities[:limit]})
    except Exception as e:
        return _json_error(str(e), 500)


# ── Portfolio ────────────────────────────────────────────────────────────────────

@api_bp.route("/portfolio")
@login_required
def portfolio():
    """Return portfolio summary for dashboard."""
    try:
        return _json_simulated({
            "equity": 10_000.0,
            "balance": 10_000.0,
            "daily_pnl": 125.50,
            "change_pct": 1.26,
            "win_rate": 58.3,
            "open_positions": 2,
        })
    except Exception as e:
        return _json_error(str(e), 500)


@api_bp.route("/portfolio/equity-curve")
@login_required
def equity_curve():
    """Return equity curve data for charting."""
    try:
        import numpy as np
        days = 90
        rng = np.random.default_rng(42)
        equity = 10000 * np.cumprod(1 + rng.normal(0.0005, 0.01, days))
        return _json_simulated({"equity": [round(float(e), 2) for e in equity]})
    except Exception as e:
        return _json_error(str(e), 500)


# ── Trading ──────────────────────────────────────────────────────────────────────

@api_bp.route("/trading/place", methods=["POST"])
@login_required
def trading_place():
    """Place an order from the trade modal (trading.js).

    Delegates to the MT5/paper trading engine; mirrors /api/trade/order
    but takes the modal's payload shape {symbol, action, risk_pct}.
    """
    try:
        data = request.get_json(silent=True) or {}
        symbol = data.get("symbol", "").strip().upper()
        action = data.get("action", "").strip().upper()
        risk_pct = float(data.get("risk_pct", 1.0))

        if not symbol:
            return _json_error("symbol is required")
        if action not in ("BUY", "SELL"):
            return _json_error("action must be BUY or SELL")

        from mt5_trading import trader as mt5_trader
        if not mt5_trader.connected:
            return _json_error(
                "Trading engine not connected - connect a paper account on the MT5 page first.", 400)

        result = mt5_trader.place_order(symbol, action, risk_pct, float(data.get("atr", 0)))
        if result.get("ok"):
            mt5_trader.refresh_account()
        return jsonify(result)
    except Exception as e:
        logger.exception("Trade place error")
        return _json_error(str(e), 500)


@api_bp.route("/trading/positions")
@login_required
def trading_positions():
    """Return open positions."""
    try:
        # Would query the trading engine
        return _json_ok({"positions": []})
    except Exception as e:
        return _json_error(str(e), 500)


@api_bp.route("/trading/orders")
@login_required
def trading_orders():
    """Return order history."""
    try:
        limit = request.args.get("limit", 20, type=int)
        return _json_ok({"orders": []})
    except Exception as e:
        return _json_error(str(e), 500)
