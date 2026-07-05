"""scripts/promote_admin.py

Promote an existing user to the admin role, or demote them back, directly
against the database. This is how the very first admin account gets
created: there is no other bootstrap path, and this script never creates a
user, it only ever changes the role of one that already exists.

Loads the database connection the same way app.py does (.env then the
DATABASE_URL environment variable, same sqlite fallback path), so it works
unchanged whether run on a local checkout or inside the Docker container.

Usage:
    python scripts/promote_admin.py someone@example.com
    python scripts/promote_admin.py someone@example.com --demote
"""

import argparse
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from dotenv import load_dotenv
load_dotenv(os.path.join(BASE_DIR, ".env"), override=False)

from flask import Flask
from sqlalchemy import func

from extensions import db
from models import User, AdminAuditLog


def _build_app():
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
        "DATABASE_URL",
        "sqlite:///" + os.path.join(BASE_DIR, "instance", "users.db"))
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    db.init_app(app)
    return app


def _find_user(email):
    return User.query.filter(func.lower(User.email) == email.strip().lower()).first()


def apply_role_change(email, demote=False):
    """Core logic, run inside an active app context. Returns a result dict:
    {ok, message, exit_code}. Never creates a user."""
    user = _find_user(email)
    if not user:
        return {"ok": False, "exit_code": 1,
                "message": f"No user found with email {email}. Nothing was changed."}

    target_role = "user" if demote else "admin"
    if user.role == target_role:
        return {"ok": True, "exit_code": 0,
                "message": f"{user.username} <{user.email}> already has role "
                          f"'{target_role}'. Nothing to do."}

    old_role = user.role
    user.role = target_role
    db.session.add(AdminAuditLog(
        admin_id=user.id, action="user.demote" if demote else "user.promote",
        target_type="user", target_id=str(user.id),
        detail=f"{user.username} <{user.email}>: {old_role} -> {target_role} "
               f"(via scripts/promote_admin.py, no other admin was signed in)"))
    db.session.commit()
    return {"ok": True, "exit_code": 0,
            "message": f"{user.username} <{user.email}> is now role "
                      f"'{target_role}' (was '{old_role}')."}


def main():
    parser = argparse.ArgumentParser(
        description="Promote a user to admin, or demote them back to a "
                    "plain user account.")
    parser.add_argument("email", help="Email of an existing user")
    parser.add_argument("--demote", action="store_true",
                        help="Revert the user to the plain 'user' role "
                             "instead of granting admin")
    args = parser.parse_args()

    app = _build_app()
    with app.app_context():
        result = apply_role_change(args.email, demote=args.demote)
        print(result["message"])
        if result["exit_code"]:
            sys.exit(result["exit_code"])


if __name__ == "__main__":
    main()
