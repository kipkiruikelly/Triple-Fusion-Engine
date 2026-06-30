"""routes/payments.py — Stripe, M-Pesa, pricing, gift codes."""

import os
import secrets
from datetime import date, datetime, timedelta

from flask import render_template, request, jsonify, redirect, url_for
from flask_login import login_required, current_user

from extensions import db
from models import User, GiftCode
from utils import _add_notification

try:
    import stripe as _stripe
    _stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
    _STRIPE_OK = bool(_stripe.api_key)
except ImportError:
    _stripe    = None
    _STRIPE_OK = False

STRIPE_PUB_KEY        = os.environ.get("STRIPE_PUBLISHABLE_KEY", "")
STRIPE_PRICE_MONTHLY  = os.environ.get("STRIPE_PRICE_ID_MONTHLY", "")
STRIPE_PRICE_ANNUAL   = os.environ.get("STRIPE_PRICE_ID_ANNUAL", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

try:
    from mpesa import stk_push, query_status, MPESA_OK, PRO_MONTHLY_KES, PRO_ANNUAL_KES
except Exception:
    MPESA_OK        = False
    PRO_MONTHLY_KES = 3500
    PRO_ANNUAL_KES  = 23000
    def stk_push(*a, **kw):    raise RuntimeError("M-Pesa not configured")
    def query_status(*a, **kw): raise RuntimeError("M-Pesa not configured")

_mpesa_pending = {}


def register_payment_routes(app):

    @app.route("/pricing")
    def pricing():
        return render_template("pricing.html",
                               stripe_pub_key=STRIPE_PUB_KEY,
                               stripe_enabled=_STRIPE_OK,
                               mpesa_enabled=MPESA_OK,
                               pro_monthly_kes=PRO_MONTHLY_KES,
                               pro_annual_kes=PRO_ANNUAL_KES)

    # ── Stripe ─────────────────────────────────────────────────────────────────

    @app.route("/stripe/checkout", methods=["POST"])
    @login_required
    def stripe_checkout():
        if not _STRIPE_OK:
            current_user.plan = 'pro'
            db.session.commit()
            return redirect(url_for('home'))
        price_id = request.form.get("price_id", STRIPE_PRICE_MONTHLY)
        if price_id not in (STRIPE_PRICE_MONTHLY, STRIPE_PRICE_ANNUAL):
            return redirect(url_for('pricing'))
        base_url = request.host_url.rstrip("/")
        session  = _stripe.checkout.Session.create(
            customer_email=current_user.email,
            payment_method_types=["card"],
            line_items=[{"price": price_id, "quantity": 1}],
            mode="subscription",
            success_url=base_url + url_for("stripe_success") + "?session_id={CHECKOUT_SESSION_ID}",
            cancel_url=base_url + url_for("stripe_cancel"),
            metadata={"user_id": str(current_user.id)},
        )
        return redirect(session.url, code=303)

    @app.route("/stripe/success")
    @login_required
    def stripe_success():
        session_id = request.args.get("session_id")
        if session_id and _STRIPE_OK:
            try:
                session = _stripe.checkout.Session.retrieve(session_id)
                current_user.stripe_customer_id     = session.customer
                current_user.stripe_subscription_id = session.subscription
                current_user.plan = 'pro'
                db.session.commit()
            except Exception:
                pass
        return render_template("stripe_success.html")

    @app.route("/stripe/cancel")
    def stripe_cancel():
        return redirect(url_for('pricing'))

    @app.route("/stripe/portal", methods=["POST"])
    @login_required
    def stripe_portal():
        if not _STRIPE_OK or not current_user.stripe_customer_id:
            return redirect(url_for('profile'))
        session = _stripe.billing_portal.Session.create(
            customer=current_user.stripe_customer_id,
            return_url=request.host_url.rstrip("/") + url_for("profile"),
        )
        return redirect(session.url, code=303)

    @app.route("/stripe/webhook", methods=["POST"])
    def stripe_webhook():
        if not _STRIPE_OK:
            return jsonify({"ok": True})
        payload = request.get_data()
        sig     = request.headers.get("Stripe-Signature", "")
        try:
            event = _stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
        except Exception:
            return jsonify({"error": "invalid signature"}), 400

        if event["type"] in ("customer.subscription.deleted", "customer.subscription.paused"):
            sub  = event["data"]["object"]
            user = User.query.filter_by(stripe_subscription_id=sub["id"]).first()
            if user:
                user.plan = 'free'; db.session.commit()
        elif event["type"] == "customer.subscription.updated":
            sub  = event["data"]["object"]
            user = User.query.filter_by(stripe_subscription_id=sub["id"]).first()
            if user:
                user.plan = 'pro' if sub["status"] == "active" else 'free'
                db.session.commit()
        elif event["type"] == "invoice.payment_failed":
            sub_id = event["data"]["object"].get("subscription")
            if sub_id:
                user = User.query.filter_by(stripe_subscription_id=sub_id).first()
                if user:
                    user.plan = 'free'; db.session.commit()
        return jsonify({"ok": True})

    # ── M-Pesa ─────────────────────────────────────────────────────────────────

    @app.route("/mpesa/pay", methods=["POST"])
    @login_required
    def mpesa_pay():
        if not MPESA_OK:
            return jsonify({"ok": False, "error": "M-Pesa payments are not configured yet."}), 503
        data  = request.get_json() or {}
        phone = data.get("phone", "").strip().replace(" ", "").replace("-", "")
        plan  = data.get("plan", "monthly")
        if phone.startswith("0"):
            phone = "254" + phone[1:]
        if not phone.startswith("254") or len(phone) != 12 or not phone.isdigit():
            return jsonify({"ok": False, "error": "Enter a valid Safaricom number (07XXXXXXXX)."}), 400
        amount = PRO_ANNUAL_KES if plan == "annual" else PRO_MONTHLY_KES
        days   = 365 if plan == "annual" else 30
        desc   = f"BullLogic Pro {'1 year' if plan == 'annual' else '30 days'}"
        try:
            resp = stk_push(phone, amount, "BullLogicPro", desc)
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500
        if resp.get("ResponseCode") != "0":
            return jsonify({"ok": False, "error": resp.get("ResponseDescription", "STK push failed")}), 400
        checkout_id = resp["CheckoutRequestID"]
        _mpesa_pending[checkout_id] = {"user_id": current_user.id, "days": days}
        return jsonify({"ok": True, "checkout_request_id": checkout_id,
                        "message": f"Check your phone ({phone}) and enter your M-Pesa PIN."})

    @app.route("/mpesa/status", methods=["POST"])
    @login_required
    def mpesa_status():
        checkout_id = (request.get_json() or {}).get("checkout_request_id", "")
        if not checkout_id:
            return jsonify({"ok": False, "paid": False, "error": "Missing checkout_request_id"}), 400
        try:
            resp = query_status(checkout_id)
        except Exception as e:
            return jsonify({"ok": False, "paid": False, "error": str(e)}), 500
        result_code = str(resp.get("ResultCode", "-1"))
        if result_code == "0":
            pending = _mpesa_pending.pop(checkout_id, {})
            uid     = pending.get("user_id", current_user.id)
            days    = pending.get("days", 30)
            user    = db.session.get(User, uid)
            if user:
                user.plan = 'pro'
                user.pro_expires_at = date.today() + timedelta(days=days)
                db.session.commit()
            return jsonify({"ok": True, "paid": True,
                            "message": f"Payment confirmed! Pro access granted for {days} days."})
        elif result_code == "1032":
            _mpesa_pending.pop(checkout_id, None)
            return jsonify({"ok": True, "paid": False, "cancelled": True,
                            "message": "You cancelled the payment on your phone."})
        return jsonify({"ok": True, "paid": False, "result_code": result_code,
                        "message": resp.get("ResultDesc", "Waiting for payment…")})

    @app.route("/mpesa/callback", methods=["POST"])
    def mpesa_callback():
        data = request.get_json(silent=True) or {}
        try:
            body   = data["Body"]["stkCallback"]
            code   = body.get("ResultCode", -1)
            chk_id = body.get("CheckoutRequestID", "")
            if code == 0 and chk_id in _mpesa_pending:
                pending = _mpesa_pending.pop(chk_id)
                user    = db.session.get(User, pending["user_id"])
                if user:
                    user.plan = 'pro'
                    user.pro_expires_at = date.today() + timedelta(days=pending["days"])
                    db.session.commit()
        except Exception:
            pass
        return jsonify({"ResultCode": 0, "ResultDesc": "Accepted"})

    # ── Gift codes ─────────────────────────────────────────────────────────────

    @app.route("/api/gift-codes/generate", methods=["POST"])
    def api_gift_codes_generate():
        admin_cookie = request.cookies.get("admin_token", "")
        admin_pw     = os.environ.get("ADMIN_PASSWORD", "bulllogic-admin-2025")
        if not admin_cookie or not secrets.compare_digest(admin_cookie, admin_pw):
            return jsonify({"ok": False, "error": "Unauthorized"}), 403
        data  = request.get_json() or {}
        days  = int(data.get("days", 30))
        count = min(int(data.get("count", 1)), 20)
        note  = (data.get("note") or "")[:100]
        codes = []
        for _ in range(count):
            code = secrets.token_hex(6).upper()
            db.session.add(GiftCode(code=code, days=days, note=note))
            codes.append(code)
        db.session.commit()
        return jsonify({"ok": True, "codes": codes, "days": days})

    @app.route("/api/gift-codes/redeem", methods=["POST"])
    @login_required
    def api_gift_codes_redeem():
        code = (request.get_json() or {}).get("code", "").upper().strip()
        gc   = GiftCode.query.filter_by(code=code, used=False).first()
        if not gc:
            return jsonify({"ok": False, "error": "Invalid or already used code"}), 400
        gc.used    = True
        gc.used_by = current_user.id
        gc.used_at = datetime.utcnow()
        user = db.session.get(User, current_user.id)
        if user.plan != "pro":
            user.plan = "pro"
            user.pro_expires_at = date.today() + timedelta(days=gc.days)
        else:
            if user.pro_expires_at:
                user.pro_expires_at = user.pro_expires_at + timedelta(days=gc.days)
            else:
                user.pro_expires_at = date.today() + timedelta(days=gc.days)
        db.session.commit()
        _add_notification(current_user.id, "gift", "Pro activated!",
                          f"Your gift code added {gc.days} days of Pro access.", "/profile")
        return jsonify({"ok": True, "days_added": gc.days, "pro_until": str(user.pro_expires_at)})
