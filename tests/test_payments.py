"""M-Pesa settlement: callback settles the persisted payment, idempotently."""

from datetime import date


def _callback(chk_id, code=0, receipt="TESTRCPT01"):
    body = {"ResultCode": code, "CheckoutRequestID": chk_id}
    if code == 0:
        body["CallbackMetadata"] = {"Item": [
            {"Name": "Amount", "Value": 3500},
            {"Name": "MpesaReceiptNumber", "Value": receipt},
        ]}
    return {"Body": {"stkCallback": body}}


def test_mpesa_callback_settles_and_is_idempotent(client, app, db, make_user):
    from models import User, Payment
    uid = make_user("mpesauser")
    with app.app_context():
        db.session.add(Payment(user_id=uid, provider="mpesa", plan="monthly",
                               amount=3500.0, currency="KES", days=30,
                               reference="ws_CO_PYTEST1", status="pending"))
        db.session.commit()

    r = client.post("/mpesa/callback", json=_callback("ws_CO_PYTEST1"))
    assert r.status_code == 200

    with app.app_context():
        p = Payment.query.filter_by(reference="ws_CO_PYTEST1").first()
        u = db.session.get(User, uid)
        assert p.status == "paid" and p.receipt == "TESTRCPT01"
        assert u.plan == "pro"
        expiry = u.pro_expires_at

    # replaying the callback must not double-credit
    client.post("/mpesa/callback", json=_callback("ws_CO_PYTEST1"))
    with app.app_context():
        assert db.session.get(User, uid).pro_expires_at == expiry


def test_mpesa_callback_failure_marks_failed(client, app, db, make_user):
    from models import Payment
    uid = make_user("mpesafail")
    with app.app_context():
        db.session.add(Payment(user_id=uid, provider="mpesa", days=30,
                               reference="ws_CO_PYTEST2", status="pending"))
        db.session.commit()
    client.post("/mpesa/callback", json=_callback("ws_CO_PYTEST2", code=1))
    with app.app_context():
        assert Payment.query.filter_by(
            reference="ws_CO_PYTEST2").first().status == "failed"
