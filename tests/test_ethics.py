"""Risk interstitial (exactly once), resources CRUD permissions,
account export and deletion."""

from conftest import admin_login


def _login(client, name):
    client.post("/login", data={"identifier": name, "password": "password123"})


def _verify(app, db, name):
    from models import User
    with app.app_context():
        u = User.query.filter_by(username=name).first()
        u.email_verified = True
        db.session.commit()
        return u.id


def test_risk_interstitial_shown_exactly_once(client, app, db, make_user):
    make_user("riskuser")
    _verify(app, db, "riskuser")
    _login(client, "riskuser")

    # First prediction attempt: redirected to the interstitial.
    r = client.post("/predict", data={"ticker": "AAPL", "interval": "1d"})
    assert r.status_code == 302 and "/risk-basics" in r.headers["Location"]

    # The page renders, acknowledging sets the flag.
    assert b"before your first prediction" in client.get("/risk-basics").data
    r = client.post("/risk-basics")
    assert r.status_code == 302

    # Second attempt is not intercepted (may fail later for other reasons,
    # but never bounces back to the interstitial).
    r = client.post("/predict", data={"ticker": "ZZNOMODEL", "interval": "1d"})
    assert "/risk-basics" not in r.headers.get("Location", "")

    # Revisiting the interstitial after acknowledgement redirects away.
    r = client.get("/risk-basics")
    assert r.status_code == 302


def test_resources_public_no_login_needed(client):
    r = client.get("/api/resources")
    assert r.status_code == 200 and r.get_json()["ok"] is True


def test_resources_crud_requires_admin_role(client, make_user):
    make_user("resviewer", role="viewer")
    headers = admin_login(client, "resviewer")
    assert client.get("/admin/api/resources").status_code == 200   # read ok
    r = client.post("/admin/api/resources",
                    json={"category": "Learn Trading", "title": "X", "url": "https://x.com"},
                    headers=headers)
    assert r.status_code == 403                                    # write denied


def test_resources_crud_as_admin(client, app, db, make_user):
    from models import ResourceLink
    make_user("resadmin", role="admin")
    headers = admin_login(client, "resadmin")
    r = client.post("/admin/api/resources",
                    json={"category": "Learn Trading", "title": "PyTest Link",
                          "url": "https://example-edu.com", "icon": "🧪"},
                    headers=headers)
    assert r.get_json()["ok"] is True
    rid = r.get_json()["id"]
    r = client.post(f"/admin/api/resources/{rid}", json={"active": False}, headers=headers)
    assert r.get_json()["ok"] is True
    r = client.delete(f"/admin/api/resources/{rid}", headers=headers)
    assert r.get_json()["ok"] is True
    with app.app_context():
        assert db.session.get(ResourceLink, rid) is None


def test_resources_rejects_bad_url(client, make_user):
    make_user("resadmin2", role="admin")
    headers = admin_login(client, "resadmin2")
    r = client.post("/admin/api/resources",
                    json={"category": "X", "title": "Bad", "url": "javascript:alert(1)"},
                    headers=headers)
    assert r.status_code == 400


def test_account_export_and_delete(client, app, db, make_user):
    from models import User
    make_user("leaver")
    uid = _verify(app, db, "leaver")
    _login(client, "leaver")

    r = client.get("/account/export")
    assert r.status_code == 200
    assert r.get_json()["account"]["username"] == "leaver"
    assert "attachment" in r.headers.get("Content-Disposition", "")

    # Deletion needs explicit confirmation, then works with exactly one step.
    r = client.post("/account/delete", json={})
    assert r.status_code == 400
    r = client.post("/account/delete", json={"confirm": True})
    assert r.get_json()["ok"] is True
    with app.app_context():
        assert db.session.get(User, uid) is None
