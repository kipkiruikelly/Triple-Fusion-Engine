"""Google OAuth, email verification, and password-reset flows."""

from datetime import datetime, timedelta


# ── Google OAuth ──────────────────────────────────────────────────────────────

def _finish(app, info):
    fin = app.extensions["bulllogic"]["finish_google_login"]
    with app.test_request_context("/auth/google/callback"):
        return fin(info)


def test_google_creates_account_verified(app, db):
    from models import User, ActivityLog
    _finish(app, {"sub": "sub-new-1", "email": "gnew1@gmail.com", "name": "G New"})
    with app.app_context():
        u = User.query.filter_by(google_sub="sub-new-1").first()
        assert u is not None
        assert u.auth_provider == "google"
        assert u.email_verified is True         # Google emails skip verification
        ActivityLog.query.filter_by(user_id=u.id).delete()
        db.session.delete(u)
        db.session.commit()


def test_google_links_existing_email_account(app, db, make_user):
    from models import User
    uid = make_user("linkme", email="linkme@gmail.com")
    _finish(app, {"sub": "sub-link-1", "email": "linkme@gmail.com", "name": "Link Me"})
    with app.app_context():
        assert User.query.filter_by(email="linkme@gmail.com").count() == 1  # no duplicate
        u = db.session.get(User, uid)
        assert u.google_sub == "sub-link-1"
        assert u.email_verified is True


def test_google_rejects_incomplete_payload(app):
    resp = _finish(app, {"email": "", "sub": ""})
    body, status = resp if isinstance(resp, tuple) else (resp, 200)
    assert status == 400


# ── Email verification ────────────────────────────────────────────────────────

def test_verification_token_roundtrip_and_expiry(app, db, make_user):
    from models import User
    uid = make_user("verifytok")
    with app.app_context():
        u = db.session.get(User, uid)
        make = app.extensions["bulllogic"]["make_verify_token"]
        load = app.extensions["bulllogic"]["load_verify_token"]
        token = make(u)
        payload, err = load(token)
        assert err is None and payload["uid"] == uid
        payload, err = load(token, max_age=-1)      # simulate 24h having passed
        assert err == "expired" and payload is None
        payload, err = load("tampered." + token)
        assert err == "invalid"


def test_verify_endpoint_flips_flag_and_unblocks(client, app, db, make_user):
    from models import User
    uid = make_user("verifyflow")
    with app.app_context():
        u = db.session.get(User, uid)
        u.email_verified = False
        db.session.commit()
        token = app.extensions["bulllogic"]["make_verify_token"](u)
    r = client.get(f"/verify-email/{token}")
    assert r.status_code == 302
    with app.app_context():
        assert db.session.get(User, uid).email_verified is True


def test_bad_verification_token_rejected(client):
    r = client.get("/verify-email/not-a-real-token")
    assert r.status_code == 400


# ── Password reset ────────────────────────────────────────────────────────────

def _issue_reset(app, db, uid):
    import secrets
    from models import PasswordResetToken
    token = secrets.token_urlsafe(32)
    with app.app_context():
        db.session.add(PasswordResetToken(
            user_id=uid, token=token,
            expires_at=datetime.utcnow() + timedelta(hours=1)))
        db.session.commit()
    return token


def test_reset_is_single_use(client, app, db, make_user):
    uid = make_user("resetonce")
    token = _issue_reset(app, db, uid)
    r = client.post(f"/reset-password/{token}",
                    data={"password": "brandnewpass1", "confirm": "brandnewpass1"})
    assert r.status_code == 302
    # Second use of the same link must be rejected.
    r = client.post(f"/reset-password/{token}",
                    data={"password": "anotherpass22", "confirm": "anotherpass22"})
    assert b"invalid" in r.data.lower() or b"expired" in r.data.lower()


def test_reset_invalidates_other_sessions(client, app, db, make_user):
    make_user("resetkill")
    from models import User
    client.post("/login", data={"identifier": "resetkill",
                                "password": "password123"})
    assert client.get("/verify-notice").status_code in (200, 302)
    with app.app_context():
        uid = User.query.filter_by(username="resetkill").first().id
    token = _issue_reset(app, db, uid)
    other = app.test_client()
    other.post(f"/reset-password/{token}",
               data={"password": "afterreset99", "confirm": "afterreset99"})
    # Original session's cookie now carries a stale session_token.
    r = client.get("/profile")
    assert r.status_code == 302 and "/login" in r.headers["Location"]


def test_reset_enforces_password_rules(client, app, db, make_user):
    uid = make_user("resetweak")
    token = _issue_reset(app, db, uid)
    r = client.post(f"/reset-password/{token}",
                    data={"password": "short", "confirm": "short"})
    assert b"at least 8 characters" in r.data


def test_forgot_password_does_not_reveal_accounts(client):
    r = client.post("/forgot-password", data={"email": "ghost-nobody@gmail.com"})
    # Same generic response whether or not the account exists.
    assert r.status_code == 200
    assert b"registered" in r.data or b"sent" in r.data.lower()


# ── Google OAuth for the admin console ────────────────────────────────────────

def _finish_admin(app, info):
    """Simulate /auth/google?admin=1 followed by the Google callback:
    the admin-intent flag is in the session when the callback runs."""
    fin = app.extensions["bulllogic"]["finish_google_login"]
    with app.test_request_context("/auth/google/callback"):
        from flask import session
        session["google_admin_intent"] = True
        resp = fin(info)
        admin_at = session.get("admin_auth_at")
    return resp, admin_at


def test_google_admin_login_staff_gets_admin_session(app, db, make_user):
    make_user("gadminstaff", role="admin", email="gadminstaff@gmail.com")
    resp, admin_at = _finish_admin(app,
                                   {"sub": "sub-adm-1", "email": "gadminstaff@gmail.com",
                                    "name": "G Admin"})
    # Redirects into the console and the admin session marker is set
    assert resp.status_code == 302
    assert "/admin" in resp.headers["Location"]
    assert admin_at is not None


def test_google_admin_login_non_staff_denied(app, db, make_user):
    make_user("gplainuser", role="user", email="gplainuser@gmail.com")
    resp, admin_at = _finish_admin(app,
                                   {"sub": "sub-adm-2", "email": "gplainuser@gmail.com",
                                    "name": "G Plain"})
    body, status = (resp if isinstance(resp, tuple) else (resp, 200))
    assert status == 403
    assert admin_at is None


def test_google_normal_login_never_grants_admin_session(app, db, make_user):
    """Without the admin intent flag, even a staff account's Google login
    must not create an admin console session."""
    make_user("gadminplain", role="admin", email="gadminplain@gmail.com")
    fin = app.extensions["bulllogic"]["finish_google_login"]
    with app.test_request_context("/auth/google/callback"):
        from flask import session
        resp = fin({"sub": "sub-adm-3", "email": "gadminplain@gmail.com",
                    "name": "G AdminPlain"})
        assert session.get("admin_auth_at") is None
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/"
