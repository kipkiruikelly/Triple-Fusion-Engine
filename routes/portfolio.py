"""routes/portfolio.py, portfolio tracker, trade journal, risk calculator."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from flask import render_template, request, jsonify
from flask_login import login_required, current_user

from extensions import db
from models import PortfolioPosition, TradeJournal
from utils import _add_notification


def register_portfolio_routes(app):

    # ── Portfolio tracker ──────────────────────────────────────────────────────

    @app.route("/portfolio")
    @login_required
    def portfolio():
        return render_template("portfolio.html")

    @app.route("/api/portfolio/positions", methods=["GET"])
    @login_required
    def portfolio_positions():
        import yfinance as yf
        positions = PortfolioPosition.query.filter_by(user_id=current_user.id).order_by(
            PortfolioPosition.opened_at.desc()).all()
        open_tickers = list({p.ticker for p in positions if p.status == "open"})
        live_prices  = {}
        if open_tickers:
            def _px(t):
                try:
                    return t, float(yf.Ticker(t).fast_info.last_price or 0)
                except Exception:
                    return t, 0.0
            with ThreadPoolExecutor(max_workers=min(len(open_tickers), 6)) as ex:
                live_prices = dict(ex.map(_px, open_tickers))
        rows = []
        for p in positions:
            ep, qty = p.entry_price, p.quantity
            if p.status == "open":
                lp = live_prices.get(p.ticker, ep)
            else:
                lp = p.exit_price or ep
            pnl     = (lp - ep) * qty if p.side == "long" else (ep - lp) * qty
            pnl_pct = (pnl / (ep * qty) * 100) if ep * qty else 0
            rows.append({
                "id": p.id, "ticker": p.ticker, "side": p.side,
                "entry_price": ep, "quantity": qty,
                "live_price":  round(lp, 4),
                "exit_price":  p.exit_price,
                "pnl":         round(pnl, 2),
                "pnl_pct":     round(pnl_pct, 2),
                "status":      p.status,
                "opened_at":   p.opened_at.strftime("%Y-%m-%d") if p.opened_at else "",
                "closed_at":   p.closed_at.strftime("%Y-%m-%d") if p.closed_at else None,
                "note":        p.note or "",
            })
        return jsonify({"ok": True, "positions": rows})

    @app.route("/api/portfolio/open", methods=["POST"])
    @login_required
    def portfolio_open():
        data        = request.get_json() or {}
        ticker      = data.get("ticker", "").upper().strip()
        side        = data.get("side", "long").lower()
        entry_price = data.get("entry_price")
        quantity    = data.get("quantity")
        note        = data.get("note", "")[:200]
        if not ticker or entry_price is None or quantity is None:
            return jsonify({"ok": False, "error": "ticker, entry_price, quantity required"}), 400
        if side not in ("long", "short"):
            return jsonify({"ok": False, "error": "side must be long or short"}), 400
        try:
            entry_price = float(entry_price)
            quantity    = float(quantity)
        except (TypeError, ValueError):
            return jsonify({"ok": False,
                            "error": "entry_price and quantity must be numbers"}), 400
        pos = PortfolioPosition(user_id=current_user.id, ticker=ticker, side=side,
                                entry_price=entry_price, quantity=quantity, note=note)
        db.session.add(pos)
        db.session.commit()
        return jsonify({"ok": True, "id": pos.id})

    @app.route("/api/portfolio/close", methods=["POST"])
    @login_required
    def portfolio_close():
        data       = request.get_json() or {}
        pos_id     = data.get("position_id")
        exit_price = data.get("exit_price")
        pos = PortfolioPosition.query.filter_by(id=pos_id, user_id=current_user.id,
                                                status="open").first()
        if not pos:
            return jsonify({"ok": False, "error": "Position not found"}), 404
        if exit_price is None:
            return jsonify({"ok": False, "error": "exit_price required"}), 400
        pos.exit_price = float(exit_price)
        pos.status     = "closed"
        pos.closed_at  = datetime.utcnow()
        db.session.commit()
        return jsonify({"ok": True})

    @app.route("/api/portfolio/delete", methods=["POST"])
    @login_required
    def portfolio_delete():
        pos_id = (request.get_json() or {}).get("position_id")
        pos = PortfolioPosition.query.filter_by(id=pos_id, user_id=current_user.id).first()
        if not pos:
            return jsonify({"ok": False, "error": "Position not found"}), 404
        db.session.delete(pos)
        db.session.commit()
        return jsonify({"ok": True})

    # ── Trade journal ──────────────────────────────────────────────────────────

    @app.route("/journal")
    @login_required
    def journal_page():
        return render_template("journal.html", user=current_user)

    @app.route("/api/journal")
    @login_required
    def api_journal_list():
        q = TradeJournal.query.filter_by(user_id=current_user.id)\
                              .order_by(TradeJournal.created_at.desc())
        tag    = request.args.get("tag")
        ticker = request.args.get("ticker")
        if tag:
            q = q.filter(TradeJournal.tags.ilike(f"%{tag}%"))
        if ticker:
            q = q.filter(TradeJournal.ticker == ticker.upper())
        entries = q.limit(100).all()
        return jsonify({"ok": True, "entries": [{
            "id": e.id, "ticker": e.ticker, "title": e.title, "body": e.body[:300],
            "mood": e.mood, "tags": e.tags, "trade_type": e.trade_type,
            "created_at": e.created_at.strftime("%Y-%m-%d %H:%M"),
        } for e in entries]})

    @app.route("/api/journal/add", methods=["POST"])
    @login_required
    def api_journal_add():
        data  = request.get_json() or {}
        title = (data.get("title") or "").strip()[:100]
        body  = (data.get("body") or "").strip()
        if not title or not body:
            return jsonify({"ok": False, "error": "Title and body required"}), 400
        entry = TradeJournal(
            user_id    = current_user.id,
            ticker     = (data.get("ticker") or "").upper()[:12] or None,
            title      = title,
            body       = body[:5000],
            mood       = data.get("mood"),
            tags       = (data.get("tags") or "")[:200],
            trade_type = data.get("trade_type"),
        )
        db.session.add(entry)
        db.session.commit()
        _add_notification(current_user.id, "system", "Journal entry saved", title)
        return jsonify({"ok": True, "id": entry.id})

    @app.route("/api/journal/delete", methods=["POST", "DELETE"])
    @login_required
    def api_journal_delete():
        eid = (request.get_json() or {}).get("id")
        e   = TradeJournal.query.filter_by(id=eid, user_id=current_user.id).first()
        if not e:
            return jsonify({"ok": False, "error": "Not found"}), 404
        db.session.delete(e)
        db.session.commit()
        return jsonify({"ok": True})

    # ── Portfolio equity curve ─────────────────────────────────────────────────

    @app.route("/api/portfolio/equity")
    @login_required
    def portfolio_equity():
        """Return time-series portfolio equity for the equity curve chart."""
        positions = PortfolioPosition.query.filter_by(user_id=current_user.id)\
                                           .order_by(PortfolioPosition.opened_at).all()
        if not positions:
            return jsonify({"ok": True, "labels": [], "values": [], "total_return": 0})

        # Build a timeline of events (open/close) to compute running P&L
        from collections import defaultdict
        events = []
        for p in positions:
            if p.opened_at:
                cost = p.entry_price * p.quantity
                events.append((p.opened_at.date(), "open",  cost))
            if p.status == "closed" and p.closed_at and p.exit_price:
                pnl = ((p.exit_price - p.entry_price) * p.quantity
                       if p.side == "long"
                       else (p.entry_price - p.exit_price) * p.quantity)
                events.append((p.closed_at.date(), "close", pnl))

        if not events:
            return jsonify({"ok": True, "labels": [], "values": [], "total_return": 0})

        events.sort(key=lambda x: x[0])
        start   = events[0][0]
        end     = datetime.utcnow().date()
        equity  = 10_000.0   # starting paper capital

        # Daily equity series
        from datetime import timedelta
        labels, values = [], []
        running = equity
        daily_pnl: dict = defaultdict(float)
        for dt, etype, amount in events:
            if etype == "close":
                daily_pnl[dt] += amount

        current = start
        while current <= end:
            running += daily_pnl.get(current, 0)
            labels.append(current.strftime("%b %d"))
            values.append(round(running, 2))
            current += timedelta(days=1)

        total_return = round((running - equity) / equity * 100, 2)
        return jsonify({"ok": True, "labels": labels, "values": values,
                        "total_return": total_return})

    # ── Risk / position size calculator ───────────────────────────────────────

    @app.route("/risk")
    @login_required
    def risk_calculator():
        return render_template("risk.html")

    @app.route("/api/risk/calculate", methods=["POST"])
    @login_required
    def api_risk_calculate():
        data      = request.get_json() or {}
        account   = float(data.get("account",   10000))
        risk_pct  = float(data.get("risk_pct",  1.0))
        entry     = float(data.get("entry",     100))
        stop_loss = float(data.get("stop_loss", 95))
        target    = float(data.get("target",    110))
        if entry <= 0 or stop_loss <= 0:
            return jsonify({"ok": False, "error": "Invalid prices"}), 400
        risk_amount = account * risk_pct / 100
        risk_per_sh = abs(entry - stop_loss)
        if risk_per_sh == 0:
            return jsonify({"ok": False, "error": "Entry and stop loss cannot be equal"}), 400
        shares        = risk_amount / risk_per_sh
        position_val  = shares * entry
        rr_ratio      = abs(target - entry) / risk_per_sh if risk_per_sh else 0
        potential_pnl = (target - entry) * shares
        win_rate_est  = 0.55
        kelly_fraction = win_rate_est - (1 - win_rate_est) / rr_ratio if rr_ratio > 0 else 0
        kelly_shares   = max(0, account * kelly_fraction / entry)
        return jsonify({
            "ok":            True,
            "shares":        round(shares, 4),
            "position_val":  round(position_val, 2),
            "risk_amount":   round(risk_amount, 2),
            "risk_per_sh":   round(risk_per_sh, 4),
            "rr_ratio":      round(rr_ratio, 2),
            "potential_pnl": round(potential_pnl, 2),
            "kelly_shares":  round(kelly_shares, 4),
            "kelly_pct":     round(kelly_fraction * 100, 2),
        })
