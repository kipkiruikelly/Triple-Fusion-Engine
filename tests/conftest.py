"""Shared pytest fixtures — the app runs against a throwaway SQLite file,
never the production instance/users.db."""

import os
import sys
import tempfile

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

# Must be set before `app` is imported.
_tmpdb = os.path.join(tempfile.mkdtemp(prefix="bulllogic-test-"), "test.db")
os.environ["DATABASE_URL"] = "sqlite:///" + _tmpdb
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ["DISABLE_OPS_THREAD"] = "true"

import pytest                      # noqa: E402
from app import app as _app       # noqa: E402
from extensions import db as _db  # noqa: E402


@pytest.fixture()
def app():
    return _app


@pytest.fixture()
def db(app):
    return _db


@pytest.fixture()
def client(app):
    import utils
    from routes import admin as admin_mod
    utils._rl_buckets.clear()
    admin_mod._login_attempts.clear()
    return app.test_client()


@pytest.fixture()
def make_user(app, db):
    from models import User
    created = []

    def _make(username, password="password123", role="user", plan="free",
              status="active", email=None):
        with app.app_context():
            u = User(username=username, email=email or f"{username}@test.local",
                     role=role, plan=plan, status=status)
            u.set_password(password)
            db.session.add(u)
            db.session.commit()
            created.append(u.id)
            return u.id

    yield _make

    with app.app_context():
        from models import (User, PredictionHistory, PredictionAccuracy,
                            Payment, Notification, AdminAuditLog)
        for uid in created:
            for ph in PredictionHistory.query.filter_by(user_id=uid).all():
                PredictionAccuracy.query.filter_by(prediction_id=ph.id).delete()
            PredictionHistory.query.filter_by(user_id=uid).delete()
            Payment.query.filter_by(user_id=uid).delete()
            Notification.query.filter_by(user_id=uid).delete()
            AdminAuditLog.query.filter_by(admin_id=uid).delete()
            u = db.session.get(User, uid)
            if u:
                db.session.delete(u)
        db.session.commit()


def login(client, identifier, password="password123"):
    return client.post("/login", data={"identifier": identifier,
                                       "password": password})


def admin_login(client, identifier, password="password123"):
    client.post("/admin/login", data={"identifier": identifier,
                                      "password": password})
    import re
    m = re.search(r'name="csrf" content="([^"]+)"',
                  client.get("/admin/audit").data.decode())
    return {"X-CSRF-Token": m.group(1)} if m else {}
