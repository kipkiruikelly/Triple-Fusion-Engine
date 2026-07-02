"""routes/auth.py, authentication, account, 2FA, API keys, webhooks."""

import json as _json
import os
import secrets
from datetime import date, datetime, timedelta

from flask import render_template, request, jsonify, redirect, url_for, make_response
from flask_login import login_user, logout_user, login_required, current_user

from extensions import db
from models import (
    User, PasswordResetToken, ApiKey, UserWebhook, ActivityLog,
    TwoFactorAuth, UserPreferences, Notification,
)
from utils import _log_activity, _add_notification, _fire_webhooks

try:
    import pyotp as _pyotp
    _PYOTP_OK = True
except ImportError:
    _pyotp     = None
    _PYOTP_OK  = False

_API_DAILY_LIMIT = 100

GOOGLE_CLIENT_ID     = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
GOOGLE_OK            = bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)

VERIFY_TOKEN_MAX_AGE_S = 24 * 3600      # verification links live 24h


def _clean_email(raw):
    """Validate, normalize and return an email address, or (None, error)."""
    from email_validator import validate_email, EmailNotValidError
    try:
        result = validate_email((raw or "").strip(), check_deliverability=False)
        return result.normalized.lower(), None
    except EmailNotValidError as e:
        return None, str(e)


def _unique_username(base):
    from models import User
    base = "".join(c for c in (base or "trader") if c.isalnum() or c in "._-")[:30] or "trader"
    name = base
    n = 1
    while User.query.filter_by(username=name).first():
        n += 1
        name = f"{base}{n}"
    return name


def register_auth_routes(app):

    from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

    def _verify_serializer():
        return URLSafeTimedSerializer(app.secret_key, salt="email-verify")

    def _make_verify_token(user):
        return _verify_serializer().dumps({"uid": user.id, "email": user.email})

    def _load_verify_token(token, max_age=VERIFY_TOKEN_MAX_AGE_S):
        """Returns (payload, error) where error is 'expired' or 'invalid'."""
        try:
            return _verify_serializer().loads(token, max_age=max_age), None
        except SignatureExpired:
            return None, "expired"
        except BadSignature:
            return None, "invalid"

    def _send_verification_email(user):
        import emails
        url = request.host_url.rstrip("/") + url_for(
            "verify_email", token=_make_verify_token(user))
        return emails.send_verification(app, user, url)

    app.jinja_env.globals["google_enabled"] = GOOGLE_OK

    # expose token helpers for tests
    app.extensions.setdefault("bulllogic", {})["load_verify_token"] = _load_verify_token
    app.extensions["bulllogic"]["make_verify_token"] = _make_verify_token

    # ── Google OAuth 2.0 (authorization-code flow via Authlib) ────────────────

    if GOOGLE_OK:
        from authlib.integrations.flask_client import OAuth
        _oauth = OAuth(app)
        _oauth.register(
            "google",
            client_id=GOOGLE_CLIENT_ID,
            client_secret=GOOGLE_CLIENT_SECRET,
            server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
            client_kwargs={"scope": "openid email profile"},
        )
        app.extensions["bulllogic"]["oauth"] = _oauth

    @app.route("/auth/google")
    def google_login():
        if not GOOGLE_OK:
            return redirect(url_for("login"))
        oauth = app.extensions["bulllogic"]["oauth"]
        redirect_uri = request.host_url.rstrip("/") + url_for("google_callback")
        return oauth.google.authorize_redirect(redirect_uri)

    @app.route("/auth/google/callback")
    def google_callback():
        if not GOOGLE_OK:
            return redirect(url_for("login"))
        oauth = app.extensions["bulllogic"]["oauth"]
        try:
            token = oauth.google.authorize_access_token()
            info  = token.get("userinfo") or {}
        except Exception:
            return render_template("login.html",
                                   error="Google sign-in failed. Try again or use your password."), 400
        return _finish_google_login(info)

    def _finish_google_login(info):
        """Shared by the real callback and tests. `info` is the verified
        OpenID payload (sub, email, name, email_verified)."""
        sub   = str(info.get("sub") or "")
        email = (info.get("email") or "").strip().lower()
        if not sub or not email:
            return render_template("login.html",
                                   error="Google did not return a usable account."), 400

        user = User.query.filter_by(google_sub=sub).first()
        if not user:
            # Same email registered with a password: link the accounts
            # rather than creating a duplicate.
            user = User.query.filter_by(email=email).first()
            if user:
                user.google_sub = sub
                user.email_verified = True
            else:
                user = User(username=_unique_username(
                                (info.get("name") or email.split("@")[0]).replace(" ", "").lower()),
                            email=email, auth_provider="google",
                            google_sub=sub, email_verified=True)
                user.set_password(secrets.token_urlsafe(24))  # unusable, OAuth-only
                db.session.add(user)
            db.session.commit()

        if (user.status or "active") != "active":
            return render_template("login.html",
                                   error="This account has been suspended."), 403
        login_user(user, remember=True)
        _log_activity(user.id, "login.google")
        return redirect(url_for("home"))

    app.extensions["bulllogic"]["finish_google_login"] = _finish_google_login

    # ── Login / Register / Logout ──────────────────────────────────────────────

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for('home'))
        error = None
        if request.method == "POST":
            from utils import rate_limited
            if rate_limited(f"login:{request.remote_addr}", 10, 900):
                return render_template("login.html",
                                       error="Too many attempts. Try again in 15 minutes."), 429
            identifier = request.form.get("identifier", "").strip()
            password   = request.form.get("password", "")
            user = User.query.filter(
                (User.username == identifier) | (User.email == identifier)
            ).first()
            if user and user.check_password(password):
                if (user.status or "active") != "active":
                    error = ("This account has been suspended."
                             if user.status == "banned"
                             else "This account is deactivated. Contact support.")
                    return render_template("login.html", error=error)
                login_user(user, remember=True)
                next_page = request.args.get('next')
                return redirect(next_page or url_for('home'))
            error = "Invalid username / email or password."
        return render_template("login.html", error=error)

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if current_user.is_authenticated:
            return redirect(url_for('home'))
        error = None
        try:
            from models import AppSetting
            closed = (row := db.session.get(AppSetting, "registration_open")) and row.value == "0"
        except Exception:
            closed = False
        if closed:
            return render_template("register.html",
                                   error="Registration is temporarily closed."), 403
        if request.method == "POST":
            from utils import rate_limited
            if rate_limited(f"register:{request.remote_addr}", 5, 3600):
                return render_template("register.html",
                                       error="Too many signups from this network. Try later."), 429
            username = request.form.get("username", "").strip()
            raw_email = request.form.get("email", "")
            password = request.form.get("password", "")
            confirm  = request.form.get("confirm", "")
            agreed   = request.form.get("agree_terms")
            email, email_err = _clean_email(raw_email)
            if not username or not raw_email or not password:
                error = "All fields are required."
            elif not agreed:
                error = "You must agree to the Terms of Service and Privacy Policy."
            elif len(username) < 3:
                error = "Username must be at least 3 characters."
            elif email_err:
                error = "Enter a valid email address."
            elif len(password) < 8:
                error = "Password must be at least 8 characters."
            elif password != confirm:
                error = "Passwords do not match."
            elif User.query.filter_by(username=username).first():
                error = "That username is already taken."
            elif User.query.filter_by(email=email).first():
                error = "An account with that email already exists."
            else:
                user = User(username=username, email=email, email_verified=False)
                user.set_password(password)
                db.session.add(user)
                db.session.commit()
                login_user(user, remember=True)
                _send_verification_email(user)
                return redirect(url_for("verify_notice"))
        return render_template("register.html", error=error)

    # ── Email verification ─────────────────────────────────────────────────────

    @app.route("/verify-notice")
    @login_required
    def verify_notice():
        if current_user.email_verified:
            return redirect(url_for("home"))
        return render_template("verify_notice.html", email=current_user.email)

    @app.route("/verify-email/<token>")
    def verify_email(token):
        payload, err = _load_verify_token(token)
        if err:
            return render_template("verify_notice.html",
                                   email=current_user.email if current_user.is_authenticated else "",
                                   token_error=("This link has expired. Request a new one below."
                                                if err == "expired" else
                                                "This verification link is not valid.")), 400
        user = db.session.get(User, payload.get("uid", 0))
        if not user or user.email != payload.get("email"):
            return render_template("verify_notice.html", email="",
                                   token_error="This verification link is not valid."), 400
        if not user.email_verified:
            user.email_verified = True
            db.session.commit()
            _log_activity(user.id, "email.verified")
        if not current_user.is_authenticated:
            login_user(user, remember=True)
        return redirect(url_for("home"))

    @app.route("/verify/resend", methods=["POST"])
    @login_required
    def verify_resend():
        from utils import rate_limited
        if current_user.email_verified:
            return redirect(url_for("home"))
        if rate_limited(f"resend:{current_user.id}", 3, 3600):
            return render_template("verify_notice.html", email=current_user.email,
                                   token_error="Resend limit reached. Try again in an hour."), 429
        sent = _send_verification_email(current_user)
        return render_template("verify_notice.html", email=current_user.email,
                               resent=sent,
                               token_error=None if sent else
                               "Email is not configured on the server. Contact support.")

    @app.route("/logout")
    @login_required
    def logout():
        logout_user()
        return redirect(url_for('login'))

    # ── Password reset ─────────────────────────────────────────────────────────

    @app.route("/forgot-password", methods=["GET", "POST"])
    def forgot_password():
        if current_user.is_authenticated:
            return redirect(url_for("home"))
        sent = False
        if request.method == "POST":
            from utils import rate_limited
            if rate_limited(f"forgot:{request.remote_addr}", 5, 3600):
                return render_template("forgot_password.html", sent=False,
                                       error="Too many requests. Try again later."), 429
            email, _ = _clean_email(request.form.get("email", ""))
            user = User.query.filter_by(email=email).first() if email else None
            if user:
                token   = secrets.token_urlsafe(32)
                expires = datetime.utcnow() + timedelta(hours=1)
                db.session.add(PasswordResetToken(user_id=user.id, token=token,
                                                  expires_at=expires))
                db.session.commit()
                import emails
                reset_url = request.host_url.rstrip("/") + url_for(
                    "reset_password", token=token)
                emails.send_password_reset(app, user, reset_url)
            # Same response whether or not the address exists.
            sent = True
        return render_template("forgot_password.html", sent=sent, error=None)

    @app.route("/reset-password/<token>", methods=["GET", "POST"])
    def reset_password(token):
        rt = PasswordResetToken.query.filter_by(token=token, used=False).first()
        if not rt or rt.expires_at < datetime.utcnow():
            return render_template("reset_password.html", invalid=True)
        error = None
        if request.method == "POST":
            pw      = request.form.get("password", "")
            confirm = request.form.get("confirm", "")
            if len(pw) < 8:
                error = "Password must be at least 8 characters."
            elif pw != confirm:
                error = "Passwords do not match."
            else:
                user = db.session.get(User, rt.user_id)
                if user:
                    user.set_password(pw)
                    # Rotate the session token: every existing session for
                    # this user is invalidated immediately.
                    user.session_token = secrets.token_hex(16)
                    PasswordResetToken.query.filter_by(user_id=user.id,
                                                       used=False).update({"used": True})
                rt.used = True
                db.session.commit()
                return redirect(url_for("login"))
        return render_template("reset_password.html", token=token, error=error, invalid=False)

    # ── Profile ────────────────────────────────────────────────────────────────

    @app.route("/profile/change-password", methods=["POST"])
    @login_required
    def change_password():
        from models import PredictionHistory
        current_pw = request.form.get("current_password", "")
        new_pw     = request.form.get("new_password", "")
        confirm_pw = request.form.get("confirm_password", "")
        total      = PredictionHistory.query.filter_by(user_id=current_user.id).count()
        if not current_user.check_password(current_pw):
            return render_template("profile.html", total_predictions=total,
                                   pw_error="Current password is incorrect.")
        if len(new_pw) < 8:
            return render_template("profile.html", total_predictions=total,
                                   pw_error="New password must be at least 8 characters.")
        if new_pw != confirm_pw:
            return render_template("profile.html", total_predictions=total,
                                   pw_error="Passwords do not match.")
        current_user.set_password(new_pw)
        db.session.commit()
        return render_template("profile.html", total_predictions=total,
                               pw_success="Password updated successfully.")

    @app.route("/profile/alerts", methods=["POST"])
    @login_required
    def toggle_alerts():
        current_user.alerts_enabled = not current_user.alerts_enabled
        db.session.commit()
        return jsonify({"ok": True, "alerts_enabled": current_user.alerts_enabled})

    # ── User preferences ───────────────────────────────────────────────────────

    @app.route("/api/preferences", methods=["GET"])
    @login_required
    def api_preferences_get():
        prefs = UserPreferences.query.filter_by(user_id=current_user.id).first()
        return jsonify({
            "ok": True,
            "digest_enabled": prefs.digest_enabled if prefs else False,
            "theme":          prefs.theme          if prefs else "dark",
            "default_ticker": prefs.default_ticker if prefs else "AAPL",
            "timezone":       prefs.timezone        if prefs else "UTC",
        })

    @app.route("/api/preferences", methods=["POST"])
    @login_required
    def api_preferences_set():
        data  = request.get_json() or {}
        prefs = UserPreferences.query.filter_by(user_id=current_user.id).first()
        if not prefs:
            prefs = UserPreferences(user_id=current_user.id)
            db.session.add(prefs)
        if "digest_enabled" in data:
            prefs.digest_enabled = bool(data["digest_enabled"])
        if "theme" in data and data["theme"] in ("dark", "light"):
            prefs.theme = data["theme"]
        if "default_ticker" in data:
            prefs.default_ticker = (data["default_ticker"] or "AAPL").upper()[:12]
        if "timezone" in data:
            prefs.timezone = (data["timezone"] or "UTC")[:50]
        db.session.commit()
        return jsonify({"ok": True})

    # ── 2FA ────────────────────────────────────────────────────────────────────

    @app.route("/api/2fa/setup")
    @login_required
    def api_2fa_setup():
        if not _PYOTP_OK:
            return jsonify({"ok": False, "error": "2FA library not installed"}), 503
        rec = TwoFactorAuth.query.filter_by(user_id=current_user.id).first()
        if rec and rec.enabled:
            return jsonify({"ok": False, "error": "2FA already enabled"}), 400
        secret = _pyotp.random_base32()
        if rec:
            rec.secret = secret
        else:
            rec = TwoFactorAuth(user_id=current_user.id, secret=secret)
            db.session.add(rec)
        db.session.commit()
        uri = _pyotp.totp.TOTP(secret).provisioning_uri(
            name=current_user.email, issuer_name="BullLogic"
        )
        return jsonify({"ok": True, "secret": secret, "uri": uri})

    @app.route("/api/2fa/enable", methods=["POST"])
    @login_required
    def api_2fa_enable():
        if not _PYOTP_OK:
            return jsonify({"ok": False, "error": "2FA library not installed"}), 503
        code = (request.get_json() or {}).get("code", "")
        rec  = TwoFactorAuth.query.filter_by(user_id=current_user.id).first()
        if not rec:
            return jsonify({"ok": False, "error": "Run /api/2fa/setup first"}), 400
        if not _pyotp.TOTP(rec.secret).verify(code, valid_window=1):
            return jsonify({"ok": False, "error": "Invalid code"}), 400
        backup       = [secrets.token_hex(4).upper() for _ in range(8)]
        rec.enabled      = True
        rec.backup_codes = _json.dumps(backup)
        db.session.commit()
        _add_notification(current_user.id, "system", "2FA Enabled",
                          "Two-factor authentication is now active on your account.")
        _log_activity(current_user.id, "2fa_enable")
        return jsonify({"ok": True, "backup_codes": backup})

    @app.route("/api/2fa/disable", methods=["POST"])
    @login_required
    def api_2fa_disable():
        if not _PYOTP_OK:
            return jsonify({"ok": False, "error": "2FA library not installed"}), 503
        data = request.get_json() or {}
        rec  = TwoFactorAuth.query.filter_by(user_id=current_user.id, enabled=True).first()
        if not rec:
            return jsonify({"ok": False, "error": "2FA is not enabled"}), 400
        user = db.session.get(User, current_user.id)
        if not user.check_password(data.get("password", "")):
            return jsonify({"ok": False, "error": "Incorrect password"}), 400
        if not _pyotp.TOTP(rec.secret).verify(data.get("code", ""), valid_window=1):
            return jsonify({"ok": False, "error": "Invalid 2FA code"}), 400
        rec.enabled = False
        db.session.commit()
        _log_activity(current_user.id, "2fa_disable")
        return jsonify({"ok": True})

    @app.route("/api/2fa/status")
    @login_required
    def api_2fa_status():
        rec = TwoFactorAuth.query.filter_by(user_id=current_user.id).first()
        return jsonify({"ok": True, "enabled": rec.enabled if rec else False,
                        "available": _PYOTP_OK})

    # ── API Keys ───────────────────────────────────────────────────────────────

    @app.route("/api/keys", methods=["GET"])
    @login_required
    def api_keys_list():
        keys = ApiKey.query.filter_by(user_id=current_user.id).order_by(
            ApiKey.created_at.desc()).all()
        return jsonify([{
            "id": k.id, "name": k.name,
            "key_preview": k.key[:8] + "..." + k.key[-4:],
            "created_at": k.created_at.strftime("%Y-%m-%d") if k.created_at else "",
            "last_used":  k.last_used.strftime("%Y-%m-%d %H:%M") if k.last_used else None,
            "calls_today": k.calls_today,
        } for k in keys])

    @app.route("/api/keys/create", methods=["POST"])
    @login_required
    def api_keys_create():
        if ApiKey.query.filter_by(user_id=current_user.id).count() >= 5:
            return jsonify({"ok": False, "error": "Maximum 5 API keys per account"}), 400
        name = (request.get_json() or {}).get("name", "Default")[:50]
        key  = secrets.token_hex(32)
        ak   = ApiKey(user_id=current_user.id, key=key, name=name)
        db.session.add(ak)
        db.session.commit()
        return jsonify({"ok": True, "key": key, "id": ak.id, "name": name})

    @app.route("/api/keys/delete", methods=["POST"])
    @login_required
    def api_keys_delete():
        key_id = (request.get_json() or {}).get("key_id")
        ak = ApiKey.query.filter_by(id=key_id, user_id=current_user.id).first()
        if not ak:
            return jsonify({"ok": False, "error": "Key not found"}), 404
        db.session.delete(ak)
        db.session.commit()
        return jsonify({"ok": True})

    # ── User webhooks ──────────────────────────────────────────────────────────

    @app.route("/api/webhooks")
    @login_required
    def api_webhooks_list():
        hooks = UserWebhook.query.filter_by(user_id=current_user.id).all()
        return jsonify({"ok": True, "webhooks": [{
            "id": h.id, "name": h.name, "url": h.url[:60] + "...",
            "events": h.events, "active": h.active, "fire_count": h.fire_count,
            "last_fired": h.last_fired.strftime("%Y-%m-%d %H:%M") if h.last_fired else None,
        } for h in hooks]})

    @app.route("/api/webhooks/add", methods=["POST"])
    @login_required
    def api_webhooks_add():
        data = request.get_json() or {}
        url  = (data.get("url") or "").strip()
        if not url.startswith("http"):
            return jsonify({"ok": False, "error": "URL must start with http"}), 400
        if UserWebhook.query.filter_by(user_id=current_user.id).count() >= 5:
            return jsonify({"ok": False, "error": "Max 5 webhooks per account"}), 400
        hook = UserWebhook(
            user_id=current_user.id, url=url[:500],
            name=(data.get("name") or "My Webhook")[:50],
            events=(data.get("events") or "alert,signal")[:100],
            secret=secrets.token_hex(16),
        )
        db.session.add(hook)
        db.session.commit()
        return jsonify({"ok": True, "id": hook.id, "secret": hook.secret})

    @app.route("/api/webhooks/delete", methods=["POST"])
    @login_required
    def api_webhooks_delete():
        hook_id = (request.get_json() or {}).get("webhook_id")
        hook = UserWebhook.query.filter_by(id=hook_id, user_id=current_user.id).first()
        if not hook:
            return jsonify({"ok": False, "error": "Not found"}), 404
        db.session.delete(hook)
        db.session.commit()
        return jsonify({"ok": True})

    @app.route("/api/webhooks/test", methods=["POST"])
    @login_required
    def api_webhooks_test():
        hook_id = (request.get_json() or {}).get("webhook_id")
        hook = UserWebhook.query.filter_by(id=hook_id, user_id=current_user.id).first()
        if not hook:
            return jsonify({"ok": False, "error": "Not found"}), 404
        _fire_webhooks(current_user.id, "alert", {
            "message": "BullLogic webhook test",
            "ticker": "AAPL", "price": 195.0, "timestamp": datetime.utcnow().isoformat(),
        })
        return jsonify({"ok": True})

    # ── Activity log ───────────────────────────────────────────────────────────

    @app.route("/api/activity-log")
    @login_required
    def api_activity_log():
        entries = ActivityLog.query.filter_by(user_id=current_user.id)\
                                   .order_by(ActivityLog.created_at.desc()).limit(50).all()
        return jsonify({"ok": True, "entries": [{
            "action":     e.action,
            "detail":     e.detail,
            "ip":         e.ip,
            "ua":         (e.ua or "")[:60],
            "created_at": e.created_at.strftime("%Y-%m-%d %H:%M"),
        } for e in entries]})
