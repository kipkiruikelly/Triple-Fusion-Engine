"""routes/paper.py, paper trading pages and APIs. VIRTUAL MONEY ONLY.

Public:
  GET  /paper                    results page (equity curve, metrics)
  GET  /paper/rules              strategy rules and friction assumptions
  GET  /api/paper/summary        metrics + equity curves, both strategies
  GET  /api/paper/trades         closed trade log (public transparency)
  GET  /traders                  trader leaderboard page (real per-user data)

Per-user (login required, open to every plan tier - see
PAPER_TRADING_PHASE2_DESIGN.md):
  POST /api/paper/opt-in         start my own paper portfolio
  POST /api/paper/opt-out        stop opening new positions for me (open
                                  positions still get exit-checked normally)
  GET  /api/paper/my-portfolio   my own per-strategy reports

Admin (role admin, CSRF enforced by admin_required):
  GET  /admin/api/paper/state    config + open positions + recent events
  POST /admin/api/paper/toggle   start/pause the engine or one strategy
  POST /admin/api/paper/config   bounded config updates

This module never imports any broker/order library. A test asserts that.
"""

from flask import render_template, request, jsonify
from flask_login import login_required, current_user

from extensions import db
import paper_engine


def register_paper_routes(app):

    # ── Public pages ──────────────────────────────────────────────────────────

    @app.route("/paper")
    def paper_page():
        return render_template("paper_trading.html")

    @app.route("/paper/rules")
    def paper_rules_page():
        return render_template("paper_rules.html")

    @app.route("/traders")
    @login_required
    def traders_leaderboard_page():
        # Matches the pre-existing login gate on /api/leaderboard/users,
        # which this page calls - not gated by plan tier, see design note.
        return render_template("traders.html")

    # ── Public APIs ───────────────────────────────────────────────────────────

    @app.route("/api/paper/summary")
    def api_paper_summary():
        cfg = paper_engine.load_config(db)
        started = paper_engine._get_flag(db, "paper_trading_started_at", "")
        return jsonify({
            "ok": True,
            "simulated": True,
            "currency": paper_engine.SIM_CURRENCY,
            "enabled": paper_engine.engine_enabled(db),
            "started_at": started or None,
            "min_trades": paper_engine.MIN_TRADES,
            "assumptions": {
                "spread_bps": cfg["spread_bps"],
                "commission_bps": cfg["commission_bps"],
                "note": ("Fills are simulated: entries and exits cross a "
                         "configurable spread/slippage estimate and pay a "
                         "commission per side. Simulated performance does "
                         "not guarantee real results."),
            },
            "strategies": [paper_engine.strategy_report(db, s, cfg)
                           for s in paper_engine.STRATEGIES],
        })

    @app.route("/api/paper/rules-config")
    def api_paper_rules_config():
        """Public: every engine rule, so nothing is a black box."""
        return jsonify({"ok": True, "simulated": True,
                        "config": paper_engine.load_config(db)})

    @app.route("/api/paper/trades")
    def api_paper_trades():
        from models import PaperTrade
        # Scoped to the platform demo stream only (user_id IS NULL) - this
        # is the public transparency log for the admin-run demo, not a feed
        # of individual users' own trades. See /api/paper/my-portfolio for
        # a user's own history.
        q = PaperTrade.query.filter(PaperTrade.status == "closed",
                                    PaperTrade.user_id.is_(None))
        strategy = request.args.get("strategy", "")
        ticker = request.args.get("ticker", "").upper()
        if strategy in paper_engine.STRATEGIES:
            q = q.filter(PaperTrade.strategy == strategy)
        if ticker:
            q = q.filter(PaperTrade.ticker == ticker)
        page = max(1, int(request.args.get("page", 1) or 1))
        per = 50
        rows = (q.order_by(PaperTrade.exit_time.desc())
                .offset((page - 1) * per).limit(per).all())
        return jsonify({"ok": True, "simulated": True, "page": page,
                        "total": q.count(),
                        "trades": [_trade_json(t) for t in rows]})

    # ── Per-user paper trading ───────────────────────────────────────────────
    # Open to every plan tier - see PAPER_TRADING_PHASE2_DESIGN.md.

    @app.route("/api/paper/opt-in", methods=["POST"])
    @login_required
    def api_paper_opt_in():
        current_user.paper_trading_opted_in = True
        db.session.commit()
        return jsonify({"ok": True, "opted_in": True})

    @app.route("/api/paper/opt-out", methods=["POST"])
    @login_required
    def api_paper_opt_out():
        # Pauses new entries only; any position already open for this user
        # keeps being exit-checked by the ops cycle until it closes
        # naturally, so opting out never strands a position.
        current_user.paper_trading_opted_in = False
        db.session.commit()
        return jsonify({"ok": True, "opted_in": False})

    @app.route("/api/paper/my-portfolio")
    @login_required
    def api_paper_my_portfolio():
        cfg = paper_engine.load_config(db)
        return jsonify({
            "ok": True,
            "simulated": True,
            "currency": paper_engine.SIM_CURRENCY,
            "opted_in": bool(current_user.paper_trading_opted_in),
            "min_trades": paper_engine.MIN_TRADES,
            "strategies": [paper_engine.strategy_report(db, s, cfg, user_id=current_user.id)
                           for s in paper_engine.STRATEGIES],
        })

    # ── Admin APIs ────────────────────────────────────────────────────────────

    from routes.admin import admin_required, _audit

    @app.route("/admin/paper")
    @admin_required("viewer")
    def admin_paper_page():
        return render_template("admin/paper.html")

    @app.route("/admin/api/paper/state")
    @admin_required("viewer")
    def admin_paper_state():
        from models import PaperTradeEvent
        cfg = paper_engine.load_config(db)
        events = (PaperTradeEvent.query
                  .order_by(PaperTradeEvent.created_at.desc())
                  .limit(30).all())
        return jsonify({
            "ok": True,
            "enabled": paper_engine.engine_enabled(db),
            "strategies": {s: paper_engine.strategy_enabled(db, s)
                           for s in paper_engine.STRATEGIES},
            "config": cfg,
            "open_positions": [_trade_json(p)
                               for p in paper_engine.open_positions(db)],
            "events": [{"at": e.created_at.isoformat(), "event": e.event,
                        "trade_id": e.trade_id, "detail": e.detail}
                       for e in events],
        })

    @app.route("/admin/api/paper/toggle", methods=["POST"])
    @admin_required("admin")
    def admin_paper_toggle():
        from flask_login import current_user
        data = request.get_json() or {}
        strategy = data.get("strategy")
        enabled = bool(data.get("enabled"))
        if strategy:
            if strategy not in paper_engine.STRATEGIES:
                return jsonify({"ok": False, "error": "unknown strategy"}), 400
            from models import AppSetting
            key = f"paper_strategy_{strategy}"
            row = db.session.get(AppSetting, key)
            if row:
                row.value = "1" if enabled else "0"
            else:
                db.session.add(AppSetting(key=key,
                                          value="1" if enabled else "0"))
            db.session.commit()
            _audit("paper.strategy_toggle", "setting", key,
                   f"{strategy} -> {'on' if enabled else 'off'}")
        else:
            paper_engine.set_engine_enabled(db, enabled, current_user.id)
            _audit("paper.toggle", "setting", "paper_trading_enabled",
                   "started" if enabled else "paused")
        return jsonify({"ok": True, "enabled": enabled})

    @app.route("/admin/api/paper/config", methods=["POST"])
    @admin_required("admin")
    def admin_paper_config():
        from flask_login import current_user
        data = request.get_json() or {}
        cfg = paper_engine.save_config(db, data, current_user.id)
        _audit("paper.config", "setting", "paper_config",
               str(sorted(data.keys()))[:200])
        return jsonify({"ok": True, "config": cfg})


def _trade_json(t):
    return {
        "id": t.id, "strategy": t.strategy, "model": t.model,
        "ticker": t.ticker, "asset_class": t.asset_class, "side": t.side,
        "qty": t.qty, "entry_time": t.entry_time.isoformat(),
        "entry_price": t.entry_price, "entry_mkt": t.entry_mkt,
        "price_source": t.price_source, "stop": t.stop_price,
        "target": t.target_price, "confidence": t.confidence,
        "rationale": t.rationale, "commission": t.commission,
        "status": t.status,
        "exit_time": t.exit_time.isoformat() if t.exit_time else None,
        "exit_price": t.exit_price, "exit_reason": t.exit_reason,
        "pnl": t.pnl, "simulated": True,
    }
