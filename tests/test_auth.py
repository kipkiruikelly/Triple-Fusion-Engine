"""Auth: registration rules, banned logins, rate limiting."""

from conftest import login


def test_register_rejects_short_password(client):
    r = client.post("/register", data={"username": "shortpw", "email": "s@gmail.com",
                                       "password": "short", "confirm": "short",
                                       "agree_terms": "on"})
    assert b"at least 8 characters" in r.data


def test_register_requires_terms_agreement(client):
    r = client.post("/register", data={"username": "notterms", "email": "n@gmail.com",
                                       "password": "password123",
                                       "confirm": "password123"})
    assert b"agree to the Terms" in r.data


def test_register_rejects_malformed_email(client):
    r = client.post("/register", data={"username": "bademail", "email": "not-an-email",
                                       "password": "password123",
                                       "confirm": "password123",
                                       "agree_terms": "on"})
    assert b"valid email" in r.data


def test_register_and_login_flow(client, app, db):
    r = client.post("/register", data={"username": "newuser1",
                                       "email": "NewUser1@Gmail.com ",
                                       "password": "password123",
                                       "confirm": "password123",
                                       "agree_terms": "on"})
    assert r.status_code == 302 and "/verify-notice" in r.headers["Location"]
    with app.app_context():
        from models import User
        u = User.query.filter_by(username="newuser1").first()
        assert u is not None and u.status == "active"
        assert u.email == "newuser1@gmail.com"     # normalized
        assert u.email_verified is False           # gated until verified
        db.session.delete(u)
        db.session.commit()


def test_banned_user_cannot_login(client, make_user):
    make_user("banneduser", status="banned")
    r = login(client, "banneduser")
    assert b"suspended" in r.data


def test_login_rate_limit(client):
    for _ in range(10):
        client.post("/login", data={"identifier": "ghost", "password": "wrong"})
    r = client.post("/login", data={"identifier": "ghost", "password": "wrong"})
    assert r.status_code == 429


def test_register_rate_limit(client):
    for _ in range(5):
        client.post("/register", data={"username": "", "email": "", "password": ""})
    r = client.post("/register", data={"username": "", "email": "", "password": ""})
    assert r.status_code == 429
