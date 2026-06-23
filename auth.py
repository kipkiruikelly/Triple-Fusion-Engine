"""
auth.py
SQLite-based authentication module for ML-QTS.

Functions: init_db(), create_user(), verify_user()
DB path: Data/users.db
"""

import os
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(BASE_DIR, "Data", "users.db")


def _connect():
    return sqlite3.connect(DB_PATH)


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                username      TEXT    UNIQUE NOT NULL,
                password_hash TEXT    NOT NULL,
                created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()


def create_user(username: str, password: str) -> bool:
    """Create a new user. Returns True on success, False if username taken."""
    try:
        with _connect() as conn:
            conn.execute(
                "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                (username.strip(), generate_password_hash(password))
            )
            conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def verify_user(username: str, password: str) -> bool:
    """Return True if username/password are valid."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE username = ?",
            (username.strip(),)
        ).fetchone()
    if not row:
        return False
    return check_password_hash(row[0], password)
