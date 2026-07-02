"""Admin console: RBAC enforcement and CSRF protection."""

from conftest import admin_login


def test_admin_routes_require_login(client):
    assert client.get("/admin").status_code == 302
    assert client.get("/admin/api/users").status_code == 401


def test_regular_user_cannot_access_admin(client, make_user):
    make_user("plainuser")
    client.post("/login", data={"identifier": "plainuser",
                                "password": "password123"})
    r = client.get("/admin/api/users")
    assert r.status_code == 403       # authenticated but role 'user' → forbidden


def test_viewer_reads_but_cannot_write(client, make_user):
    make_user("viewer1", role="viewer")
    headers = admin_login(client, "viewer1")
    assert client.get("/admin/api/users").status_code == 200
    r = client.post("/admin/api/tickers", json={"symbol": "PYT"}, headers=headers)
    assert r.status_code == 403       # viewer below admin role
    assert client.get("/admin/api/settings").status_code == 403


def test_csrf_required_on_admin_writes(client, make_user):
    make_user("admin1", role="admin")
    admin_login(client, "admin1")     # authenticated, but send no CSRF header
    r = client.post("/admin/api/tickers", json={"symbol": "PYT"})
    assert r.status_code == 403
    assert "CSRF" in r.get_json()["error"]


def test_admin_login_audited(client, app, db, make_user):
    from models import AdminAuditLog
    uid = make_user("admin2", role="admin")
    admin_login(client, "admin2")
    with app.app_context():
        assert AdminAuditLog.query.filter_by(admin_id=uid,
                                             action="login").count() == 1
