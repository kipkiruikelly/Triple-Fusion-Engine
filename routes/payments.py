"""routes/payments.py, Stripe, M-Pesa, pricing, gift codes."""

import os
import secrets
from datetime import date, datetime, timedelta

from flask import render_template, request, jsonify, redirect, url_for
from flask_login import login_required, current_user

from extensions import db
from models import User, GiftCode, Payment
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
STRIPE_PRICE_PLUS_MONTHLY = os.environ.get("STRIPE_PRICE_ID_PLUS_MONTHLY", "")
STRIPE_PRICE_PLUS_ANNUAL  = os.environ.get("STRIPE_PRICE_ID_PLUS_ANNUAL", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

# Maps a Stripe Price ID to the plan tier it should grant. Unknown/blank
# price ids (e.g. Plus not configured yet) fall through to 'pro' only via
# explicit membership checks below, never by default.
_STRIPE_TIER_PRICES = {
    STRIPE_PRICE_PLUS_MONTHLY: 'plus',
    STRIPE_PRICE_PLUS_ANNUAL:  'plus',
    STRIPE_PRICE_MONTHLY:      'pro',
    STRIPE_PRICE_ANNUAL:       'pro',
}


def _tier_for_price_id(price_id):
    return _STRIPE_TIER_PRICES.get(price_id)


try:
    from mpesa import (stk_push, query_status, MPESA_OK,
                        PRO_MONTHLY_KES, PRO_ANNUAL_KES,
                        PLUS_MONTHLY_KES, PLUS_ANNUAL_KES)
except Exception:
    MPESA_OK         = False
    PRO_MONTHLY_KES  = 3500
    PRO_ANNUAL_KES   = 23000
    PLUS_MONTHLY_KES = 1450
    PLUS_ANNUAL_KES  = 13000
    def stk_push(*a, **kw):    raise RuntimeError("M-Pesa not configured")
    def query_status(*a, **kw): raise RuntimeError("M-Pesa not configured")


def _grant_plan(user, tier, days):
    """Grant or extend Plus/Pro access by `days`. `tier` is 'plus' or 'pro' -
    anything else is treated as 'pro' so a bad/missing value never silently
    grants nothing."""
    tier = tier if tier in ('plus', 'pro') else 'pro'
    # A tier change (Plus -> Pro or vice versa) resets the expiry window to
    # `days` from today rather than stacking onto the old tier's remaining
    # time; staying on the same tier extends it as before.
    if user.plan == tier and user.pro_expires_at and user.pro_expires_at >= date.today():
        user.pro_expires_at = user.pro_expires_at + timedelta(days=days)
    else:
        user.pro_expires_at = date.today() + timedelta(days=days)
    user.plan = tier


def _grant_pro(user, days):
    """Back-compat wrapper: gift codes only ever grant Pro."""
    _grant_plan(user, 'pro', days)


# Daraja STK Push result codes and what to tell the user.
MPESA_RESULT_CODES = {
    "1":    ("failed",    "Insufficient M-Pesa balance. Top up and try again."),
    "1001": ("failed",    "Another M-Pesa session is active on this number. Wait a minute and retry."),
    "1019": ("failed",    "The payment request expired. Start a new payment."),
    "1025": ("failed",    "M-Pesa could not send the prompt. Try again."),
    "1032": ("cancelled", "You cancelled the payment on your phone."),
    "1037": ("failed",    "No response from your phone. Make sure it is on and unlocked, then retry."),
    "2001": ("failed",    "Wrong M-Pesa PIN entered. Try again."),
    "9999": ("failed",    "M-Pesa error. Try again in a moment."),
}


def _settle_mpesa_payment(payment, receipt=None):
    """Mark a pending M-Pesa payment paid and grant Pro. Idempotent.
    Only ever called after a verified callback or query confirmation."""
    if payment.status == 'paid':
        return
    payment.status       = 'paid'
    payment.receipt      = receipt
    payment.completed_at = datetime.utcnow()
    user = db.session.get(User, payment.user_id)
    if user:
        _grant_plan(user, payment.tier or 'pro', payment.days or 30)
    db.session.commit()
    if user:
        try:
            import emails
            from flask import current_app
            emails.send_receipt(current_app._get_current_object(), user, payment)
        except Exception:
            pass


def _fail_mpesa_payment(payment, result_code):
    """Record a terminal non-success outcome. Returns the user message."""
    status, message = MPESA_RESULT_CODES.get(
        str(result_code), ("failed", "Payment did not complete. Try again."))
    if payment and payment.status == 'pending':
        payment.status       = status
        payment.completed_at = datetime.utcnow()
        db.session.commit()
    return message


def register_payment_routes(app):

    @app.route("/api/pricing")
    def api_pricing():
        return jsonify({
            "ok": True,
            "stripe_pub_key": STRIPE_PUB_KEY,
            "stripe_enabled": _STRIPE_OK,
            "mpesa_enabled": MPESA_OK,
            "pro_monthly_kes": PRO_MONTHLY_KES,
            "pro_annual_kes": PRO_ANNUAL_KES,
            "plus_monthly_kes": PLUS_MONTHLY_KES,
            "plus_annual_kes": PLUS_ANNUAL_KES,
            "stripe_price_monthly": STRIPE_PRICE_MONTHLY,
            "stripe_price_annual": STRIPE_PRICE_ANNUAL,
            "stripe_price_plus_monthly": STRIPE_PRICE_PLUS_MONTHLY,
            "stripe_price_plus_annual": STRIPE_PRICE_PLUS_ANNUAL
        })

    # ── Stripe ─────────────────────────────────────────────────────────────────

    @app.route("/stripe/checkout", methods=["POST"])
    @login_required
    def stripe_checkout():
        if not getattr(current_user, "email_verified", True):
            return redirect(url_for("verify_notice"))
        form_tier = request.form.get("tier", "pro")
        form_tier = form_tier if form_tier in ('plus', 'pro') else 'pro'
        if not _STRIPE_OK:
            current_user.plan = form_tier
            db.session.commit()
            return redirect(url_for('home'))
        price_id = request.form.get("price_id", STRIPE_PRICE_MONTHLY)
        tier     = _tier_for_price_id(price_id)
        if not price_id or tier is None:
            return redirect(url_for('home'))
        base_url = request.host_url.rstrip("/")
        session  = _stripe.checkout.Session.create(
            customer_email=current_user.email,
            payment_method_types=["card"],
            line_items=[{"price": price_id, "quantity": 1}],
            mode="subscription",
            success_url=base_url + url_for("stripe_success") + "?session_id={CHECKOUT_SESSION_ID}",
            cancel_url=base_url + url_for("stripe_cancel"),
            metadata={"user_id": str(current_user.id), "tier": tier},
            subscription_data={"metadata": {"user_id": str(current_user.id), "tier": tier}},
        )
        return redirect(session.url, code=303)

    @app.route("/stripe/success")
    @login_required
    def stripe_success():
        session_id = request.args.get("session_id")
        if session_id and _STRIPE_OK:
            try:
                session = _stripe.checkout.Session.retrieve(session_id)
                tier = (session.metadata or {}).get("tier", "pro")
                tier = tier if tier in ('plus', 'pro') else 'pro'
                current_user.stripe_customer_id     = session.customer
                current_user.stripe_subscription_id = session.subscription
                current_user.plan = tier
                if not Payment.query.filter_by(reference=session_id).first():
                    db.session.add(Payment(
                        user_id=current_user.id, provider='stripe', tier=tier,
                        amount=(session.amount_total or 0) / 100.0,
                        currency=(session.currency or 'usd').upper(),
                        reference=session_id, status='paid',
                        completed_at=datetime.utcnow()))
                db.session.commit()
            except Exception:
                pass
        return redirect(url_for('home'))

    @app.route("/stripe/cancel")
    def stripe_cancel():
        return redirect(url_for('home'))

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
                tier = (sub.get("metadata") or {}).get("tier", "pro")
                tier = tier if tier in ('plus', 'pro') else 'pro'
                user.plan = tier if sub["status"] == "active" else 'free'
                db.session.commit()
        elif event["type"] == "invoice.payment_failed":
            sub_id = event["data"]["object"].get("subscription")
            if sub_id:
                user = User.query.filter_by(stripe_subscription_id=sub_id).first()
                if user:
                    user.plan = 'free'; db.session.commit()
        return jsonify({"ok": True})

    # ── M-Pesa ─────────────────────────────────────────────────────────────────

    @app.route("/api/payment/apply_discount", methods=["POST"])
    @login_required
    def apply_discount():
        data = request.get_json() or {}
        code = data.get("code", "").strip().upper()
        plan = data.get("plan", "monthly")
        tier = data.get("tier", "pro")
        tier = tier if tier in ('plus', 'pro') else 'pro'
        if not code:
            return jsonify({"ok": False, "error": "Code required"}), 400

        gift = GiftCode.query.filter_by(code=code, used=False).first()
        if not gift:
            return jsonify({"ok": False, "error": "Invalid or expired promo code."}), 400

        if tier == 'plus':
            original_price = PLUS_ANNUAL_KES if plan == "annual" else PLUS_MONTHLY_KES
        else:
            original_price = PRO_ANNUAL_KES if plan == "annual" else PRO_MONTHLY_KES
        days = gift.days or (365 if plan == "annual" else 30)
        
        # Currently, all GiftCodes are 100% off (gift passes)
        return jsonify({
            "ok": True,
            "message": "Promo code applied! 100% discount.",
            "original_price": original_price,
            "new_price": 0,
            "days": days
        })

    @app.route("/mpesa/pay", methods=["POST"])
    @login_required
    def mpesa_pay():
        if not getattr(current_user, "email_verified", True):
            return jsonify({"ok": False,
                            "error": "Verify your email address before paying. Check your inbox."}), 403
        if not MPESA_OK:
            return jsonify({"ok": False, "error": "M-Pesa payments are not configured yet."}), 503
        data  = request.get_json() or {}
        phone = data.get("phone", "").strip().replace(" ", "").replace("-", "")
        plan  = data.get("plan", "monthly")
        tier  = data.get("tier", "pro")
        tier  = tier if tier in ('plus', 'pro') else 'pro'
        if phone.startswith("0"):
            phone = "254" + phone[1:]
        if not phone.startswith("254") or len(phone) != 12 or not phone.isdigit():
            return jsonify({"ok": False, "error": "Enter a valid Safaricom number (07XXXXXXXX)."}), 400

        if tier == 'plus':
            amount = PLUS_ANNUAL_KES if plan == "annual" else PLUS_MONTHLY_KES
        else:
            amount = PRO_ANNUAL_KES if plan == "annual" else PRO_MONTHLY_KES
        days   = 365 if plan == "annual" else 30

        discount_code = data.get("discount_code", "").strip().upper()
        if discount_code:
            gift = GiftCode.query.filter_by(code=discount_code, used=False).first()
            if not gift:
                return jsonify({"ok": False, "error": "Invalid or expired promo code."}), 400

            # GiftCode gives 100% off for `gift.days`, for whichever tier was
            # being purchased.
            gift.used = True
            gift.used_by = current_user.id
            gift.used_at = datetime.utcnow()

            _grant_plan(current_user, tier, gift.days)

            db.session.add(Payment(user_id=current_user.id, provider='promo', plan=plan, tier=tier,
                                   amount=0, currency='KES', days=gift.days,
                                   reference=f"PROMO-{discount_code}", status='paid'))
            db.session.commit()
            return jsonify({"ok": True, "paid": True,
                            "message": f"Promo code applied! {tier.capitalize()} access granted for {gift.days} days."})

        desc   = f"BullLogic {tier.capitalize()} {'1 year' if plan == 'annual' else '30 days'}"
        try:
            resp = stk_push(phone, amount, f"BullLogic{tier.capitalize()}", desc)
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500
        if resp.get("ResponseCode") != "0":
            return jsonify({"ok": False, "error": resp.get("ResponseDescription", "STK push failed")}), 400
        checkout_id = resp["CheckoutRequestID"]
        db.session.add(Payment(user_id=current_user.id, provider='mpesa', plan=plan, tier=tier,
                               amount=float(amount), currency='KES', days=days,
                               phone=phone, reference=checkout_id, status='pending'))
        db.session.commit()
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
        payment     = Payment.query.filter_by(reference=checkout_id, provider='mpesa').first()
        result_code = str(resp.get("ResultCode", "-1"))
        if result_code == "0":
            if not payment:
                return jsonify({"ok": False, "paid": False,
                                "error": "Payment record not found. Contact support with your M-Pesa receipt."}), 404
            _settle_mpesa_payment(payment)
            tier_label = (payment.tier or 'pro').capitalize()
            return jsonify({"ok": True, "paid": True,
                            "message": f"Payment confirmed! {tier_label} access granted for {payment.days or 30} days."})
        elif result_code in MPESA_RESULT_CODES:
            message = _fail_mpesa_payment(payment, result_code)
            return jsonify({"ok": True, "paid": False,
                            "cancelled": result_code == "1032",
                            "result_code": result_code, "message": message})
        # Request still processing on Safaricom's side.
        return jsonify({"ok": True, "paid": False, "result_code": result_code,
                        "message": resp.get("ResultDesc", "Waiting for payment confirmation...")})

    @app.route("/mpesa/callback", methods=["POST"])
    def mpesa_callback():
        data = request.get_json(silent=True) or {}
        try:
            body    = data["Body"]["stkCallback"]
            code    = body.get("ResultCode", -1)
            chk_id  = body.get("CheckoutRequestID", "")
            payment = Payment.query.filter_by(reference=chk_id, provider='mpesa').first()
            if payment:
                if code == 0:
                    receipt = None
                    for item in (body.get("CallbackMetadata") or {}).get("Item", []):
                        if item.get("Name") == "MpesaReceiptNumber":
                            receipt = str(item.get("Value", ""))[:40]
                    _settle_mpesa_payment(payment, receipt)
                elif payment.status == 'pending':
                    payment.status       = 'cancelled' if code == 1032 else 'failed'
                    payment.completed_at = datetime.utcnow()
                    db.session.commit()
        except Exception:
            pass
        return jsonify({"ResultCode": 0, "ResultDesc": "Accepted"})

    # ── Gift codes ─────────────────────────────────────────────────────────────

    @app.route("/api/gift-codes/generate", methods=["POST"])
    def api_gift_codes_generate():
        from models import ROLE_LEVELS
        if (not current_user.is_authenticated
                or current_user.role_level < ROLE_LEVELS["support"]):
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
        _grant_pro(user, gc.days)
        db.session.add(Payment(user_id=current_user.id, provider='gift',
                               days=gc.days, reference=f"gift:{gc.code}",
                               status='paid', completed_at=datetime.utcnow()))
        db.session.commit()
        _add_notification(current_user.id, "gift", "Pro activated!",
                          f"Your gift code added {gc.days} days of Pro access.", "/profile")
        return jsonify({"ok": True, "days_added": gc.days, "pro_until": str(user.pro_expires_at)})
