"""Auth: registration rules, banned logins, rate limiting."""

from conftest import login


def test_register_rejects_short_password(client):
    r = client.post("/register", data={"username": "shortpw", "email": "s@t.local",
                                       "password": "short", "confirm": "short"})
    assert b"at least 8 characters" in r.data


def test_register_and_login_flow(client, app, db):
    r = client.post("/register", data={"username": "newuser1",
                                       "email": "newuser1@t.local",
                                       "password": "password123",
                                       "confirm": "password123"})
    assert r.status_code == 302
    with app.app_context():
        from models import User
        u = User.query.filter_by(username="newuser1").first()
        assert u is not None and u.status == "active"
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
