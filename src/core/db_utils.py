"""
db_utils.py
Database Utilities for the Triple-Fusion-Engine.

Provides helpers for database migration, data versioning, and the
hybrid CSV/TimescaleDB/PostgreSQL approach described in Phase 4:
  - Schema migration scripts (in migrations/ directory)
  - Data versioning for model reproducibility
  - CSV → PostgreSQL import utilities
  - Model version tracking

Usage:
    from db_utils import run_migrations, create_model_version
    run_migrations()
    create_model_version("AAPL", "rf", "2026-07-04-v1", metrics)

Author: BullLogic
"""

import hashlib
import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MIGRATIONS_DIR = os.path.join(BASE_DIR, "migrations")


# ── Schema Migrations ───────────────────────────────────────────────────────────

MIGRATION_001 = """
-- Migration 001: Phase 4 gamification models
-- Run: sqlite3 instance/users.db < migrations/001_gamification.sql
-- Or: psql -d tfe < migrations/001_gamification.sql

CREATE TABLE IF NOT EXISTS watchlist (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id  INTEGER NOT NULL REFERENCES user(id),
    ticker   VARCHAR(12) NOT NULL,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    notes    VARCHAR(200),
    UNIQUE(user_id, ticker)
);

CREATE TABLE IF NOT EXISTS user_portfolio (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL REFERENCES user(id),
    equity         REAL NOT NULL,
    balance        REAL NOT NULL,
    open_positions INTEGER DEFAULT 0,
    snapshot_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_portfolio_user ON user_portfolio(user_id, snapshot_at);

CREATE TABLE IF NOT EXISTS user_achievement (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL REFERENCES user(id),
    achievement_id VARCHAR(32) NOT NULL,
    earned_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, achievement_id)
);

CREATE TABLE IF NOT EXISTS competition_model (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            VARCHAR(100) NOT NULL,
    start_date      DATE NOT NULL,
    end_date        DATE NOT NULL,
    initial_balance REAL DEFAULT 10000.0,
    status          VARCHAR(12) DEFAULT 'upcoming',
    created_by      INTEGER REFERENCES user(id),
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS competition_entry (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    competition_id INTEGER NOT NULL REFERENCES competition_model(id),
    user_id        INTEGER NOT NULL REFERENCES user(id),
    start_equity   REAL NOT NULL,
    current_equity REAL NOT NULL,
    joined_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(competition_id, user_id)
);

CREATE TABLE IF NOT EXISTS model_version (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker        VARCHAR(12) NOT NULL,
    model_type    VARCHAR(20) NOT NULL,
    version       VARCHAR(16) NOT NULL,
    file_path     VARCHAR(256) NOT NULL,
    metrics_json  TEXT,
    feature_hash  VARCHAR(64),
    data_hash     VARCHAR(64),
    trained_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_active     BOOLEAN DEFAULT 1,
    UNIQUE(ticker, model_type, version)
);
CREATE INDEX IF NOT EXISTS idx_model_version_ticker ON model_version(ticker, model_type);
"""


def run_migrations(db_url: Optional[str] = None) -> bool:
    """Run all pending database migrations.

    Args:
        db_url: SQLAlchemy database URL. Defaults to SQLite instance/users.db.

    Returns:
        True if migrations ran successfully.
    """
    try:
        from extensions import db
        from flask import Flask

        # Create a minimal Flask app for DB operations
        app = Flask(__name__)
        if db_url:
            app.config["SQLALCHEMY_DATABASE_URI"] = db_url
        else:
            app.config["SQLALCHEMY_DATABASE_URI"] = (
                f"sqlite:///{os.path.join(BASE_DIR, 'instance', 'users.db')}"
            )
        app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        db.init_app(app)

        with app.app_context():
            db.create_all()
            logger.info("Database migrations completed successfully")
        return True
    except Exception as e:
        logger.error("Migration failed: %s", e)
        return False


def save_migration_file() -> str:
    """Save the migration SQL to the migrations/ directory."""
    os.makedirs(MIGRATIONS_DIR, exist_ok=True)
    path = os.path.join(MIGRATIONS_DIR, "001_gamification.sql")
    with open(path, "w") as f:
        f.write(MIGRATION_001.strip())
    logger.info("Migration saved → %s", path)
    return path


# ── Data Versioning ─────────────────────────────────────────────────────────────

def compute_data_hash(df_or_path: Any) -> str:
    """Compute a deterministic hash of training data for reproducibility.

    Args:
        df_or_path: Either a pandas DataFrame or a path to a CSV file.

    Returns:
        SHA-256 hex digest.
    """
    import pandas as pd

    if isinstance(df_or_path, str):
        df = pd.read_csv(df_or_path)
    else:
        df = df_or_path

    # Hash only the numeric columns, sorted by index
    numeric = df.select_dtypes(include="number")
    data_str = numeric.to_csv(index=True).encode("utf-8")
    return hashlib.sha256(data_str).hexdigest()[:16]


def compute_feature_hash(feature_list: List[str]) -> str:
    """Compute a deterministic hash of the feature list."""
    data_str = json.dumps(sorted(feature_list), sort_keys=True).encode("utf-8")
    return hashlib.sha256(data_str).hexdigest()[:16]


def create_model_version(
    ticker: str,
    model_type: str,
    metrics: dict,
    file_path: str,
    feature_list: Optional[List[str]] = None,
    data_hash: Optional[str] = None,
) -> dict:
    """Record a model version for reproducibility tracking.

    Returns a dict suitable for insertion into model_version table.
    """
    version = datetime.now().strftime("%Y-%m-%d-v%H%M")

    record = {
        "ticker": ticker,
        "model_type": model_type,
        "version": version,
        "file_path": file_path,
        "metrics_json": json.dumps(metrics),
        "feature_hash": compute_feature_hash(feature_list) if feature_list else None,
        "data_hash": data_hash,
        "trained_at": datetime.utcnow(),
        "is_active": True,
    }

    logger.info("Model version created: %s %s %s", ticker, model_type, version)
    return record


def get_model_versions(ticker: str, model_type: str) -> List[dict]:
    """Retrieve all versions for a given ticker/model combination.

    In production, queries the database. In development, scans Saved Models/.
    """
    versions = []
    models_dir = os.path.join(BASE_DIR, "Saved Models")

    prefix_map = {
        "lr": "lr_model_", "rf": "rf_model_", "xgb": "xgb_model_",
        "lgb": "lgb_model_", "lstm": "lstm_model_", "stacking": "stacking_meta_",
    }

    prefix = prefix_map.get(model_type, f"{model_type}_")
    pattern = f"{prefix}{ticker}"

    if os.path.isdir(models_dir):
        for fname in sorted(os.listdir(models_dir)):
            if fname.startswith(pattern):
                full_path = os.path.join(models_dir, fname)
                mtime = datetime.fromtimestamp(os.path.getmtime(full_path))
                versions.append({
                    "file": fname,
                    "path": full_path,
                    "trained_at": mtime.isoformat(),
                    "size_mb": round(os.path.getsize(full_path) / (1024 * 1024), 2),
                })

    return versions
