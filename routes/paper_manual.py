"""routes/paper_manual.py, persistent manual paper trading."""

from datetime import datetime
from flask import Blueprint, request, jsonify, render_template
from flask_login import login_required, current_user

from extensions import db
from models import UserPaperAccount, UserPaperOrder, UserPaperPosition

def register_manual_paper_routes(app):
    


    @app.route("/api/manual-paper/account", methods=["GET"])
    @login_required
    def get_manual_paper_account():
        acc = UserPaperAccount.query.filter_by(user_id=current_user.id).first()
        if not acc:
            return jsonify({"ok": True, "account": None})
            
        orders = UserPaperOrder.query.filter_by(account_id=acc.id).order_by(UserPaperOrder.created_at.desc()).all()
        positions = UserPaperPosition.query.filter_by(account_id=acc.id).order_by(UserPaperPosition.opened_at.desc()).all()
        
        return jsonify({
            "ok": True, 
            "account": {
                "id": acc.id,
                "starting_balance": acc.starting_balance,
                "balance": acc.balance,
                "equity": acc.equity
            },
            "orders": [{
                "id": o.id, "ticker": o.ticker, "order_type": o.order_type, "side": o.side,
                "quantity": o.quantity, "target_price": o.target_price, "sl": o.sl, "tp": o.tp,
                "status": o.status, "created_at": o.created_at.strftime("%Y-%m-%d %H:%M:%S")
            } for o in orders],
            "positions": [{
                "id": p.id, "ticker": p.ticker, "side": p.side, "quantity": p.quantity,
                "entry_price": p.entry_price, "current_price": p.current_price, "sl": p.sl, "tp": p.tp,
                "realized_pnl": p.realized_pnl, "status": p.status, "opened_at": p.opened_at.strftime("%Y-%m-%d %H:%M:%S")
            } for p in positions]
        })

    @app.route("/api/manual-paper/account/init", methods=["POST"])
    @login_required
    def init_manual_paper_account():
        data = request.get_json() or {}
        starting_balance = float(data.get("starting_balance", 10000.0))
        
        acc = UserPaperAccount.query.filter_by(user_id=current_user.id).first()
        if acc:
            return jsonify({"ok": False, "error": "Account already exists"})
            
        acc = UserPaperAccount(user_id=current_user.id, starting_balance=starting_balance, balance=starting_balance, equity=starting_balance)
        db.session.add(acc)
        db.session.commit()
        return jsonify({"ok": True})

    @app.route("/api/manual-paper/order", methods=["POST"])
    @login_required
    def place_manual_paper_order():
        acc = UserPaperAccount.query.filter_by(user_id=current_user.id).first()
        if not acc:
            return jsonify({"ok": False, "error": "No paper account initialized"})
            
        data = request.get_json() or {}
        ticker = data.get("ticker", "").upper()
        order_type = data.get("order_type", "market").lower()
        side = data.get("side", "buy").lower()
        quantity = float(data.get("quantity", 0))
        target_price = data.get("target_price")
        sl = data.get("sl")
        tp = data.get("tp")
        
        if not ticker or quantity <= 0:
            return jsonify({"ok": False, "error": "Invalid ticker or quantity"})
            
        if order_type in ("limit", "stop") and not target_price:
            return jsonify({"ok": False, "error": "Target price required for limit/stop orders"})

        if target_price: target_price = float(target_price)
        if sl: sl = float(sl)
        if tp: tp = float(tp)

        order = UserPaperOrder(
            account_id=acc.id, ticker=ticker, order_type=order_type, side=side, 
            quantity=quantity, target_price=target_price, sl=sl, tp=tp
        )
        db.session.add(order)
        db.session.commit()
        return jsonify({"ok": True})

    @app.route("/api/manual-paper/cancel", methods=["POST"])
    @login_required
    def cancel_manual_paper_order():
        data = request.get_json() or {}
        order_id = data.get("order_id")
        
        order = UserPaperOrder.query.filter_by(id=order_id, status="pending").first()
        if not order:
            return jsonify({"ok": False, "error": "Order not found or not pending"})
            
        acc = UserPaperAccount.query.get(order.account_id)
        if acc.user_id != current_user.id:
            return jsonify({"ok": False, "error": "Unauthorized"})
            
        order.status = "canceled"
        db.session.commit()
        return jsonify({"ok": True})
        
    @app.route("/api/manual-paper/close", methods=["POST"])
    @login_required
    def close_manual_paper_position():
        data = request.get_json() or {}
        pos_id = data.get("position_id")
        
        pos = UserPaperPosition.query.filter_by(id=pos_id, status="open").first()
        if not pos:
            return jsonify({"ok": False, "error": "Position not found or already closed"})
            
        acc = UserPaperAccount.query.get(pos.account_id)
        if acc.user_id != current_user.id:
            return jsonify({"ok": False, "error": "Unauthorized"})
            
        # We queue a market order in the opposite direction to close it out.
        close_side = "sell" if pos.side == "buy" else "buy"
        order = UserPaperOrder(
            account_id=acc.id, ticker=pos.ticker, order_type="market", side=close_side, 
            quantity=pos.quantity
        )
        db.session.add(order)
        db.session.commit()
        return jsonify({"ok": True, "message": "Market close order submitted"})
