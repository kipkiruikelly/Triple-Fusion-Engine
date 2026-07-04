"""Theme preference: account persistence, cookie fallback, server rendering."""

from tests.conftest import login


def _get_user(app, db, uid):
    from models import User
    with app.app_context():
        return db.session.get(User, uid)


# ── /api/theme endpoint ───────────────────────────────────────────────────────

def test_theme_saves_to_account(client, app, db, make_user):
    uid = make_user("themeuser1")
    login(client, "themeuser1")
    r = client.post("/api/theme", json={"theme": "light"})
    assert r.status_code == 200
    assert r.get_json()["ok"] is True
    assert _get_user(app, db, uid).theme_preference == "light"

    r = client.post("/api/theme", json={"theme": "system"})
    assert r.status_code == 200
    assert _get_user(app, db, uid).theme_preference == "system"


def test_theme_endpoint_sets_cookie(client, make_user):
    make_user("themeuser2")
    login(client, "themeuser2")
    r = client.post("/api/theme", json={"theme": "dark"})
    cookie = r.headers.get("Set-Cookie", "")
    assert "bl-theme=dark" in cookie


def test_theme_rejects_invalid_value(client, app, db, make_user):
    uid = make_user("themeuser3")
    login(client, "themeuser3")
    r = client.post("/api/theme", json={"theme": "neon"})
    assert r.status_code == 400
    assert _get_user(app, db, uid).theme_preference in (None, "system")


def test_theme_works_logged_out_via_cookie(client):
    r = client.post("/api/theme", json={"theme": "light"})
    assert r.status_code == 200
    assert "bl-theme=light" in r.headers.get("Set-Cookie", "")


def test_preferences_endpoint_returns_account_theme(client, make_user):
    make_user("themeuser4")
    login(client, "themeuser4")
    client.post("/api/theme", json={"theme": "light"})
    d = client.get("/api/preferences").get_json()
    assert d["theme"] == "light"


# ── Server-side rendering: account preference wins ────────────────────────────

def test_logged_in_page_renders_account_theme(client, make_user):
    make_user("themeuser5")
    login(client, "themeuser5")
    client.post("/api/theme", json={"theme": "light"})
    html = client.get("/profile").data.decode()
    assert 'data-theme="light"' in html
    # boot script mirrors the account value into localStorage so it
    # overwrites any stale device choice
    assert 'localStorage.setItem("bl-theme", acct)' in html
    assert 'var acct = "light"' in html


def test_account_theme_beats_cookie(client, make_user):
    """The cookie says dark, the account says light: account wins."""
    make_user("themeuser6")
    login(client, "themeuser6")
    client.post("/api/theme", json={"theme": "light"})
    client.set_cookie("bl-theme", "dark")
    html = client.get("/profile").data.decode()
    assert 'data-theme="light"' in html


def test_system_preference_renders_no_attribute(client, make_user):
    make_user("themeuser7")
    login(client, "themeuser7")
    client.post("/api/theme", json={"theme": "system"})
    html = client.get("/profile").data.decode()
    assert 'data-theme="light"' not in html.split("<head>")[0]
    assert 'data-theme="dark"' not in html.split("<head>")[0]
    # the CSS system fallback must be present for no-JS visitors
    assert "prefers-color-scheme: light" in html


# ── Logged-out fallback chain ─────────────────────────────────────────────────

def test_anonymous_cookie_drives_render(client):
    client.set_cookie("bl-theme", "light")
    html = client.get("/login").data.decode()
    assert 'data-theme="light"' in html


def test_anonymous_no_choice_uses_system(client):
    html = client.get("/login").data.decode()
    head = html.split("</head>")[0]
    assert 'data-theme="light"' not in head.split("<style>")[0]
    assert "prefers-color-scheme: light" in html
    # boot script present so first paint is correct
    assert "localStorage.getItem" in html


# ── Coverage: every page carries the theme system ─────────────────────────────

def test_public_pages_include_theme_system(client):
    for path in ["/login", "/register", "/faq", "/privacy-policy", "/terms",
                 "/methodology", "/resources", "/track-record", "/offline"]:
        r = client.get(path)
        assert r.status_code == 200, path
        html = r.data.decode()
        assert "blTheme" in html, f"{path} missing theme system"
        assert "themeToggle" in html, f"{path} missing theme toggle"


def test_404_page_is_themed(client):
    r = client.get("/definitely-not-a-real-page")
    assert r.status_code == 404
    html = r.data.decode()
    assert "blTheme" in html
    assert "Page not found" in html
