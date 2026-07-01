#!/usr/bin/env python3
"""
tools/create_admin.py — create or promote the first admin account.

Credentials come from environment variables (never hardcoded):
    ADMIN_EMAIL       required — email for the admin account
    ADMIN_USERNAME    optional — defaults to the part before @ in ADMIN_EMAIL
    ADMIN_PASSWORD    required if the user does not exist yet
    ADMIN_ROLE        optional — viewer|support|admin (default: admin)

If a user with ADMIN_EMAIL already exists, it is promoted to the role
(password unchanged, ADMIN_PASSWORD not required). Otherwise a new
account is created.

Usage (PowerShell):
    $env:ADMIN_EMAIL="you@example.com"; $env:ADMIN_PASSWORD="…"
    .venv\Scripts\python.exe tools\create_admin.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# SECRET_KEY is required to import the app; fall back to the instance file.
if not os.environ.get("SECRET_KEY"):
    _kp = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "instance", "secret_key.txt")
    if os.path.exists(_kp):
        with open(_kp) as f:
            os.environ["SECRET_KEY"] = f.read().strip()

from app import app                      # noqa: E402
from extensions import db                # noqa: E402
from models import User, ROLE_LEVELS     # noqa: E402


def main():
    email    = os.environ.get("ADMIN_EMAIL", "").strip().lower()
    username = os.environ.get("ADMIN_USERNAME", "").strip() or (email.split("@")[0] if email else "")
    password = os.environ.get("ADMIN_PASSWORD", "")
    role     = os.environ.get("ADMIN_ROLE", "admin").strip()

    if not email:
        sys.exit("ADMIN_EMAIL environment variable is required")
    if role not in ROLE_LEVELS or role == "user":
        sys.exit(f"ADMIN_ROLE must be one of: viewer, support, admin (got {role!r})")

    with app.app_context():
        user = User.query.filter_by(email=email).first()
        if user:
            user.role = role
            user.status = "active"
            db.session.commit()
            print(f"Promoted existing user '{user.username}' <{email}> to role '{role}'.")
        else:
            if len(password) < 10:
                sys.exit("ADMIN_PASSWORD is required (min 10 chars) to create a new admin")
            if User.query.filter_by(username=username).first():
                sys.exit(f"Username '{username}' is taken — set ADMIN_USERNAME explicitly")
            user = User(username=username, email=email, role=role, status="active")
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            print(f"Created admin '{username}' <{email}> with role '{role}'.")
        print(f"Log in at /admin/login — sessions expire after "
              f"{os.environ.get('ADMIN_SESSION_MINUTES', '30')} min of inactivity.")


if __name__ == "__main__":
    main()
