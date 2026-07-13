"""Tests for the authenticated dashboard at / and the Predict page at GET /predict.

/ used to render the Predict workstation (index.html) for logged-in users;
it now renders the home dashboard (home.html), and the Predict page moved
to GET /predict. Anonymous visitors still get the landing page at /.
"""

import pytest

from conftest import login


class TestRootRoute:

    def test_anonymous_gets_landing_page(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert b"Welcome back" not in r.data

    def test_logged_in_gets_dashboard(self, client, make_user):
        make_user("dashuser")
        login(client, "dashuser")
        r = client.get("/")
        assert r.status_code == 200
        assert b"Welcome back, dashuser" in r.data
        # Quick-access cards into the main sections
        assert b'href="/predict"' in r.data
        assert b'href="/watchlist"' in r.data
        assert b'href="/paper"' in r.data
        assert b'href="/track-record"' in r.data

    def test_dashboard_alias_renders_same_page(self, client, make_user):
        make_user("aliasuser")
        login(client, "aliasuser")
        r = client.get("/dashboard")
        assert r.status_code == 200
        assert b"Welcome back, aliasuser" in r.data

    def test_dashboard_alias_requires_login(self, client):
        r = client.get("/dashboard")
        assert r.status_code == 302
        assert "/login" in r.headers["Location"]

    def test_new_account_sees_onboarding_not_fake_data(self, client, make_user):
        make_user("freshuser")
        login(client, "freshuser")
        r = client.get("/")
        assert b"Run your first prediction" in r.data
        # Zero predictions shown honestly, not placeholder stats
        assert b"Recent Predictions" in r.data

    def test_recent_predictions_render(self, app, db, client, make_user):
        uid = make_user("preduser")
        with app.app_context():
            from models import PredictionHistory
            db.session.add(PredictionHistory(
                user_id=uid, ticker="AAPL", interval="1d",
                current_price=190.0, lr_pred=192.5, rf_pred=191.8,
                direction="Up", confidence=71.4))
            db.session.commit()
        login(client, "preduser")
        r = client.get("/")
        assert b"AAPL" in r.data
        assert b"Run your first prediction" not in r.data


class TestTierAndRoleGating:

    def test_free_user_sees_upgrade_prompt(self, client, make_user):
        make_user("freeuser")
        login(client, "freeuser")
        r = client.get("/")
        assert b"See Plans" in r.data
        assert b'href="/pricing"' in r.data

    def test_pro_user_sees_no_upgrade_prompt(self, client, make_user):
        make_user("prouser", plan="pro")
        login(client, "prouser")
        r = client.get("/")
        assert b"See Plans" not in r.data
        assert b"PRO" in r.data

    def test_admin_sees_admin_card_plain_user_does_not(self, client, make_user):
        # "Admin Console" also appears in a JS comment in the shared navbar
        # script, so assert on the dashboard card's own markup instead.
        make_user("plaindash")
        login(client, "plaindash")
        assert b'class="quick-card admin"' not in client.get("/").data
        client.get("/logout")
        make_user("admindash", role="admin")
        login(client, "admindash")
        assert b'class="quick-card admin"' in client.get("/").data


class TestPredictPage:

    def test_get_predict_requires_login(self, client):
        r = client.get("/predict")
        assert r.status_code == 302
        assert "/login" in r.headers["Location"]

    def test_get_predict_renders_workstation(self, client, make_user):
        make_user("predictpage")
        login(client, "predictpage")
        r = client.get("/predict")
        assert r.status_code == 200
        assert b'action="/predict"' in r.data

    def test_get_predict_prefills_last_ticker_cookie(self, client, make_user):
        make_user("cookieuser")
        login(client, "cookieuser")
        client.set_cookie("bl-last-ticker", "NVDA")
        r = client.get("/predict")
        assert r.status_code == 200
        assert b"NVDA" in r.data
