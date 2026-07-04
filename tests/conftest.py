"""Shared pytest fixtures for the Triple-Fusion-Engine.

The app runs against a throwaway SQLite file, never the production
instance/users.db. Phase 1-4 fixtures for ML, risk, smart routing, etc.
"""

import os
import sys
import tempfile
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

_tmpdb = os.path.join(tempfile.mkdtemp(prefix="bulllogic-test-"), "test.db")
os.environ["DATABASE_URL"] = "sqlite:///" + _tmpdb
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ["DISABLE_OPS_THREAD"] = "true"

import pytest
import numpy as np
import pandas as pd

from app import app as _app
from extensions import db as _db


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


# ── Phase 1-4 Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def sample_df():
    """Return a realistic OHLCV DataFrame via mock_data."""
    from tests.mock_data import sample_ohlcv
    return sample_ohlcv(n_bars=200, seed=42)


@pytest.fixture
def sample_trades_fixture():
    """Return 50 realistic trades."""
    from tests.mock_data import sample_trades
    return sample_trades(n_trades=50, seed=42)


@pytest.fixture
def sample_account_fixture():
    """Return a mock account with $10k equity."""
    from tests.mock_data import sample_account
    return sample_account()


@pytest.fixture
def sample_feature_data():
    """Return (X, y, feature_names) tuple."""
    from tests.mock_data import sample_feature_matrix, sample_feature_names
    X = sample_feature_matrix(500, 45, seed=42)
    y = X[:, 0] * 2 + X[:, 1] * 0.5 + np.random.default_rng(42).normal(0, 1, 500)
    names = sample_feature_names(45)
    return X, y, names


@pytest.fixture
def mock_trader():
    """Return a MagicMock that quacks like MT5Trader."""
    t = MagicMock()
    t.place_order.return_value = {"ok": True, "trade": {
        "time": "12:00:00", "action": "BUY", "symbol": "EURUSD",
        "lot": 0.1, "price": 1.0850, "sl": 1.0800, "tp": 1.0950,
        "ticket": 1001,
    }}
    t.account = {"balance": 10000, "equity": 10000}
    t.is_paper = True
    return t


@pytest.fixture
def risk_manager_instance():
    """Return a fresh RiskManager with default settings."""
    from risk_manager import RiskManager
    return RiskManager()


@pytest.fixture
def competition_engine():
    """Return a fresh CompetitionEngine."""
    from gamification import CompetitionEngine
    return CompetitionEngine()


@pytest.fixture
def data_quality_monitor():
    """Return a fresh DataQualityMonitor."""
    from data_quality import DataQualityMonitor
    return DataQualityMonitor()


@pytest.fixture
def smart_router(mock_trader):
    """Return a SmartOrderRouter with a mock trader."""
    from smart_router import SmartOrderRouter
    return SmartOrderRouter(mock_trader)
