"""routes/admin.py, admin dashboard: auth, RBAC, pages, and JSON APIs.

Roles (User.role): viewer (read-only) < support (user/payment/broadcast
actions) < admin (settings, roles, tickers, models, deletes).

Every mutating endpoint requires a CSRF token (X-CSRF-Token header or
csrf_token form field) tied to the session. Admin sessions expire after
ADMIN_SESSION_MINUTES (default 30) of inactivity, sliding.
"""

import csv
import io
import os
import secrets
import subprocess
import sys
import threading
import time
from datetime import date, datetime, timedelta
from functools import wraps

from flask import (render_template, request, jsonify, redirect, url_for,
                   session, Response)
from flask_login import login_user, logout_user, current_user

from extensions import db
from models import (User, PredictionHistory, PriceAlert, PortfolioPosition,
                    ApiKey, Payment, GiftCode, Notification, ActivityLog,
                    AdminAuditLog, AppSetting, TickerConfig, Broadcast,
                    ErrorLog, PasswordResetToken, TwoFactorAuth, ROLE_LEVELS)

try:
    import pyotp as _pyotp
    _PYOTP_OK = True
except ImportError:
    _pyotp    = None
    _PYOTP_OK = False

BASE_DIR   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS_DIR = os.path.join(BASE_DIR, "Saved Models")

ADMIN_SESSION_MINUTES = int(os.environ.get("ADMIN_SESSION_MINUTES", "30"))

# Admin roles (support and above) must pass a TOTP check at /admin/login if
# they have 2FA enabled on their account (enrolled via the regular
# /api/2fa/setup + /api/2fa/enable endpoints, this console does not have its
# own separate enrollment). The credential check and the code check happen
# as two round trips of the same form; PENDING_2FA_MAX_S bounds how long a
# verified-password-but-no-code-yet session may sit before it must restart.
PENDING_2FA_MAX_S = 5 * 60

# ── Login rate limiting (per-IP, in-memory) ───────────────────────────────────

_login_attempts = {}          # ip -> [timestamps of failures]
_LOGIN_MAX_FAILS = 5
_LOGIN_WINDOW_S  = 15 * 60


def _rate_limited(ip):
    now = time.time()
    fails = [t for t in _login_attempts.get(ip, []) if now - t < _LOGIN_WINDOW_S]
    _login_attempts[ip] = fails
    return len(fails) >= _LOGIN_MAX_FAILS


def _record_fail(ip):
    _login_attempts.setdefault(ip, []).append(time.time())


# ── Helpers ───────────────────────────────────────────────────────────────────

def _audit(action, target_type=None, target_id=None, detail=None):
    try:
        db.session.add(AdminAuditLog(
            admin_id=current_user.id, action=action, target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            detail=(detail or "")[:400] or None, ip=request.remote_addr))
        db.session.commit()
    except Exception:
        db.session.rollback()


def _get_setting(key, default=None):
    row = db.session.get(AppSetting, key)
    return row.value if row and row.value is not None else default


def _set_setting(key, value):
    row = db.session.get(AppSetting, key)
    if row:
        row.value = str(value)
        row.updated_by = current_user.id
    else:
        db.session.add(AppSetting(key=key, value=str(value), updated_by=current_user.id))


def _csrf_ok():
    token = (request.headers.get("X-CSRF-Token")
             or request.form.get("csrf_token", ""))
    want = session.get("csrf_token", "")
    return bool(want) and secrets.compare_digest(token, want)


def admin_required(min_role="viewer"):
    """Server-side guard: role check + sliding session timeout + CSRF on writes."""
    def outer(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            wants_json = request.path.startswith("/admin/api")

            def deny(msg, code):
                if wants_json:
                    return jsonify({"ok": False, "error": msg}), code
                return redirect(url_for("admin_login", next=request.path))

            if not current_user.is_authenticated:
                return deny("Login required", 401)
            if current_user.role_level < ROLE_LEVELS[min_role]:
                return deny("Insufficient role", 403)
            if current_user.status != "active":
                return deny("Account disabled", 403)

            auth_at = session.get("admin_auth_at", 0)
            if time.time() - auth_at > ADMIN_SESSION_MINUTES * 60:
                session.pop("admin_auth_at", None)
                return deny("Admin session expired, log in again", 401)
            session["admin_auth_at"] = time.time()   # sliding refresh

            if request.method in ("POST", "PUT", "PATCH", "DELETE") and not _csrf_ok():
                return jsonify({"ok": False, "error": "CSRF token missing or invalid"}), 403
            return f(*args, **kwargs)
        return decorated
    return outer


def _csv_response(rows, header, filename):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    w.writerows(rows)
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={filename}"})


def _day_series(query_dt_col, days, filt=None):
    """Return [{date, count}] for the last `days` days grouped by day."""
    since = date.today() - timedelta(days=days - 1)
    q = db.session.query(db.func.date(query_dt_col).label("d"),
                         db.func.count().label("c"))
    if filt is not None:
        q = q.filter(*filt)
    q = (q.filter(query_dt_col >= datetime.combine(since, datetime.min.time()))
          .group_by("d").all())
    counts = {str(r.d): r.c for r in q}
    return [{"date": str(since + timedelta(days=i)),
             "count": counts.get(str(since + timedelta(days=i)), 0)}
            for i in range(days)]


# ── Retrain job state (one at a time, in-memory) ──────────────────────────────

_retrain = {"running": False, "ticker": None, "started_at": None,
            "finished_at": None, "returncode": None, "tail": ""}


def _run_retrain(tickers):
    cmd = [sys.executable, os.path.join(BASE_DIR, "train_all_tickers.py"),
           "--tickers", *tickers, "--fast"]
    try:
        proc = subprocess.Popen(cmd, cwd=BASE_DIR, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True)
        lines = []
        for line in proc.stdout:
            lines.append(line.rstrip())
            _retrain["tail"] = "\n".join(lines[-25:])
        proc.wait()
        _retrain["returncode"] = proc.returncode
    except Exception as e:
        _retrain["returncode"] = -1
        _retrain["tail"] += f"\n[launcher error] {e}"
    finally:
        _retrain["running"] = False
        _retrain["finished_at"] = datetime.utcnow().isoformat()


# ── Route registration ────────────────────────────────────────────────────────

def register_admin_routes(app, endpoint_stats=None, app_start=None):
    endpoint_stats = endpoint_stats if endpoint_stats is not None else {}
    app_start = app_start or time.time()

    # ══ Auth ══════════════════════════════════════════════════════════════════

    @app.route("/api/admin/login", methods=["POST"])
    def admin_login():
        ip = request.remote_addr or "?"
        if _rate_limited(ip):
            return jsonify({"ok": False, "error": "Too many failed attempts. Try again in 15 minutes."}), 429
            
        data = request.get_json() or {}
        pending_uid = session.get("admin_2fa_pending_uid")
        pending_at  = session.get("admin_2fa_pending_at", 0)
        
        if pending_uid and time.time() - pending_at <= PENDING_2FA_MAX_S:
            user = db.session.get(User, pending_uid)
            rec  = TwoFactorAuth.query.filter_by(user_id=pending_uid, enabled=True).first()
            code = data.get("code", "").strip()
            if (user and rec and _PYOTP_OK and code
                    and _pyotp.TOTP(rec.secret).verify(code, valid_window=1)):
                session.pop("admin_2fa_pending_uid", None)
                session.pop("admin_2fa_pending_at", None)
                login_user(user)
                session["admin_auth_at"] = time.time()
                session["csrf_token"] = secrets.token_hex(16)
                db.session.add(AdminAuditLog(admin_id=user.id, action="login",
                                             ip=ip, detail=(request.user_agent.string or "")[:200]))
                db.session.commit()
                return jsonify({"ok": True})
            _record_fail(ip)
            if user:
                db.session.add(AdminAuditLog(admin_id=user.id, action="login.failed",
                                             ip=ip, detail="2FA code invalid or missing"))
                db.session.commit()
            return jsonify({"ok": False, "error": "Invalid or missing 2FA code.", "need_2fa": True}), 401
        else:
            session.pop("admin_2fa_pending_uid", None)
            session.pop("admin_2fa_pending_at", None)
            identifier = data.get("identifier", "").strip()
            password   = data.get("password", "")
            user = User.query.filter(
                (User.username == identifier) | (User.email == identifier)).first()
            if (user and user.check_password(password)
                    and user.role_level >= ROLE_LEVELS["viewer"]
                    and user.status == "active"):
                rec = TwoFactorAuth.query.filter_by(
                    user_id=user.id, enabled=True).first()
                if user.role_level >= ROLE_LEVELS["admin"] and _PYOTP_OK and rec:
                    session["admin_2fa_pending_uid"] = user.id
                    session["admin_2fa_pending_at"] = time.time()
                    return jsonify({"ok": False, "need_2fa": True})
                else:
                    login_user(user)
                    session["admin_auth_at"] = time.time()
                    session["csrf_token"] = secrets.token_hex(16)
                    db.session.add(AdminAuditLog(admin_id=user.id, action="login",
                                                 ip=ip, detail=(request.user_agent.string or "")[:200]))
                    db.session.commit()
                    return jsonify({"ok": True})
            else:
                _record_fail(ip)
                if user and user.role_level >= 1:
                    db.session.add(AdminAuditLog(admin_id=user.id,
                                                 action="login.failed", ip=ip))
                    db.session.commit()
                return jsonify({"ok": False, "error": "Invalid credentials or no admin access."}), 401

    @app.route("/api/admin/logout", methods=["POST"])
    def admin_logout():
        if current_user.is_authenticated and current_user.role_level >= 1:
            _audit("logout")
        session.pop("admin_auth_at", None)
        session.pop("csrf_token", None)
        logout_user()
        return jsonify({"ok": True})

    # ══ Pages ═════════════════════════════════════════════════════════════════

    @app.route("/admin/login", methods=["GET", "POST"])
    def admin_login_page():
        if request.method == "GET":
            if current_user.is_authenticated and getattr(current_user, "role_level", 0) >= ROLE_LEVELS["viewer"]:
                return redirect(url_for("admin_dashboard"))
            return render_template("admin/login.html")

        ip = request.remote_addr or "?"
        if _rate_limited(ip):
            return render_template("admin/login.html", error="Too many failed attempts. Try again in 15 minutes."), 429

        pending_uid = session.get("admin_2fa_pending_uid")
        pending_at  = session.get("admin_2fa_pending_at", 0)

        if pending_uid and time.time() - pending_at <= PENDING_2FA_MAX_S:
            user = db.session.get(User, pending_uid)
            rec  = TwoFactorAuth.query.filter_by(user_id=pending_uid, enabled=True).first()
            code = request.form.get("code", "").strip()
            if (user and rec and _PYOTP_OK and code
                    and _pyotp.TOTP(rec.secret).verify(code, valid_window=1)):
                session.pop("admin_2fa_pending_uid", None)
                session.pop("admin_2fa_pending_at", None)
                login_user(user, remember=True)
                session["admin_auth_at"] = time.time()
                session["csrf_token"] = secrets.token_hex(16)
                db.session.add(AdminAuditLog(admin_id=user.id, action="login",
                                             ip=ip, detail=(request.user_agent.string or "")[:200]))
                db.session.commit()
                return redirect(url_for("admin_dashboard"))
            _record_fail(ip)
            if user:
                db.session.add(AdminAuditLog(admin_id=user.id, action="login.failed",
                                             ip=ip, detail="2FA code invalid or missing"))
                db.session.commit()
            return render_template("admin/login.html", error="Invalid or missing 2FA code.", need_2fa=True), 401
        else:
            session.pop("admin_2fa_pending_uid", None)
            session.pop("admin_2fa_pending_at", None)
            identifier = request.form.get("identifier", "").strip()
            password   = request.form.get("password", "")
            user = User.query.filter(
                (User.username == identifier) | (User.email == identifier)).first()
            if (user and user.check_password(password)
                    and user.role_level >= ROLE_LEVELS["viewer"]
                    and user.status == "active"):
                rec = TwoFactorAuth.query.filter_by(
                    user_id=user.id, enabled=True).first()
                if user.role_level >= ROLE_LEVELS["admin"] and _PYOTP_OK and rec:
                    session["admin_2fa_pending_uid"] = user.id
                    session["admin_2fa_pending_at"] = time.time()
                    return render_template("admin/login.html", need_2fa=True)
                else:
                    login_user(user, remember=True)
                    session["admin_auth_at"] = time.time()
                    session["csrf_token"] = secrets.token_hex(16)
                    db.session.add(AdminAuditLog(admin_id=user.id, action="login",
                                                 ip=ip, detail=(request.user_agent.string or "")[:200]))
                    db.session.commit()
                    return redirect(url_for("admin_dashboard"))
            else:
                _record_fail(ip)
                if user and user.role_level >= 1:
                    db.session.add(AdminAuditLog(admin_id=user.id, action="login.failed", ip=ip))
                    db.session.commit()
                return render_template("admin/login.html", error="Invalid credentials or no admin access."), 401

    @app.route("/admin")
    @app.route("/admin/dashboard")
    @admin_required("viewer")
    def admin_dashboard():
        return render_template("admin/dashboard.html")




    # ══ API: overview ═════════════════════════════════════════════════════════

    @app.route("/admin/api/overview")
    @admin_required("viewer")
    def admin_api_overview():
        days = min(int(request.args.get("days", 30)), 90)
        today_start = datetime.combine(date.today(), datetime.min.time())
        week_ago    = datetime.utcnow() - timedelta(days=7)

        total_users  = User.query.count()
        active_today = User.query.filter(User.last_seen >= today_start).count()
        total_preds  = PredictionHistory.query.count()
        revenue_kes  = (db.session.query(db.func.coalesce(db.func.sum(Payment.amount), 0))
                        .filter(Payment.status == "paid", Payment.currency == "KES").scalar())
        errors_24h   = ErrorLog.query.filter(
            ErrorLog.created_at >= datetime.utcnow() - timedelta(hours=24)).count()
        reqs = sum(s["count"] for s in endpoint_stats.values()) or 1
        errs = sum(s["errors"] for s in endpoint_stats.values())

        signups  = _day_series(User.created_at, days)
        preds    = _day_series(PredictionHistory.predicted_at, days)
        rev_rows = (db.session.query(
                        db.func.date(Payment.completed_at).label("d"),
                        db.func.sum(Payment.amount).label("s"))
                    .filter(Payment.status == "paid", Payment.currency == "KES",
                            Payment.completed_at >= datetime.utcnow() - timedelta(days=days))
                    .group_by("d").all())
        rev_map = {str(r.d): float(r.s or 0) for r in rev_rows}
        revenue_series = [{"date": p["date"], "amount": rev_map.get(p["date"], 0)}
                          for p in preds]

        feed = []
        for u in User.query.order_by(User.id.desc()).limit(5):
            feed.append({"type": "signup", "text": f"{u.username} signed up",
                         "at": (u.created_at or datetime.utcnow()).isoformat()})
        for p in (Payment.query.filter(Payment.status == "paid")
                  .order_by(Payment.id.desc()).limit(5)):
            u = db.session.get(User, p.user_id)
            feed.append({"type": "payment",
                         "text": f"{u.username if u else '?'} paid "
                                 f"{p.amount or 0:g} {p.currency or ''} ({p.provider})",
                         "at": (p.completed_at or p.created_at).isoformat()})
        for e in ErrorLog.query.order_by(ErrorLog.id.desc()).limit(5):
            feed.append({"type": "error", "text": f"{e.endpoint}: {e.message[:80]}",
                         "at": e.created_at.isoformat()})
        feed.sort(key=lambda x: x["at"], reverse=True)

        model_files = [f for f in os.listdir(MODELS_DIR)
                       if f.endswith((".pkl", ".keras"))] if os.path.isdir(MODELS_DIR) else []
        try:
            from azure_storage import azure_enabled
            azure_ok = azure_enabled()
        except Exception:
            azure_ok = False

        failed_24h = Payment.query.filter(
            Payment.status.in_(["failed", "cancelled"]),
            Payment.created_at >= datetime.utcnow() - timedelta(hours=24)).count()
        alerts = []
        if failed_24h >= 3:
            alerts.append(f"{failed_24h} failed/cancelled payments in the last 24h")
        if errors_24h >= 10:
            alerts.append(f"{errors_24h} application errors in the last 24h")
        if _retrain["running"]:
            alerts.append(f"Model retrain running for {_retrain['ticker']}")
        try:
            from ops import active_drift_alerts, churn_counts
            alerts.extend(active_drift_alerts(db))
            churn = churn_counts(db)
        except Exception:
            churn = {}
        try:
            from market_data import data_status
            if data_status()["rate_limited"]:
                alerts.append("Market data source is rate-limited, serving cached data")
        except Exception:
            pass

        return jsonify({"ok": True, "kpis": {
                            "total_users": total_users, "active_today": active_today,
                            "total_predictions": total_preds,
                            "revenue_kes": float(revenue_kes or 0),
                            "error_rate_pct": round(errs / reqs * 100, 2),
                            "pro_users": User.query.filter_by(plan="pro").count(),
                            "churn_at_risk": churn.get("at_risk", 0),
                        },
                        "signups": signups, "predictions": preds,
                        "revenue": revenue_series, "feed": feed[:12],
                        "health": {
                            "api": True,
                            "models": len(model_files) > 0,
                            "model_count": len(model_files),
                            "azure": azure_ok,
                            "uptime_s": round(time.time() - app_start, 1),
                            "maintenance": _get_setting("maintenance_mode") == "1",
                            "paper_trading": _get_setting("paper_trading_enabled") == "1",
                        },
                        "alerts": alerts})

    # ══ API: users ════════════════════════════════════════════════════════════

    _USER_SORTS = {"username": User.username, "email": User.email,
                   "created_at": User.created_at, "last_seen": User.last_seen,
                   "plan": User.plan, "status": User.status, "id": User.id}

    def _users_query():
        q = User.query
        term = request.args.get("q", "").strip()
        if term:
            q = q.filter((User.username.ilike(f"%{term}%")) |
                         (User.email.ilike(f"%{term}%")))
        plan = request.args.get("plan", "")
        if plan in ("free", "pro"):
            q = q.filter(User.plan == plan)
        status = request.args.get("status", "")
        if status in ("active", "deactivated", "banned"):
            q = q.filter(User.status == status)
        churn = request.args.get("churn", "")
        if churn in ("active", "at_risk", "churned", "new"):
            now = datetime.utcnow()
            if churn == "active":
                q = q.filter(User.last_seen >= now - timedelta(days=7))
            elif churn == "at_risk":
                q = q.filter(User.last_seen < now - timedelta(days=7),
                             User.last_seen >= now - timedelta(days=30))
            elif churn == "churned":
                q = q.filter(User.last_seen < now - timedelta(days=30))
            else:
                q = q.filter(User.last_seen.is_(None))
        col = _USER_SORTS.get(request.args.get("sort", "id"), User.id)
        q = q.order_by(col.desc() if request.args.get("dir", "desc") == "desc"
                       else col.asc())
        return q

    def _user_row(u):
        from ops import churn_bucket
        return {"id": u.id, "username": u.username, "email": u.email,
                "plan": u.plan, "role": u.role or "user",
                "status": u.status or "active",
                "ban_reason": u.ban_reason,
                "churn": churn_bucket(u),
                "created_at": u.created_at.isoformat() if u.created_at else None,
                "last_seen": u.last_seen.isoformat() if u.last_seen else None,
                "predictions": PredictionHistory.query.filter_by(user_id=u.id).count()}

    @app.route("/admin/api/users")
    @admin_required("viewer")
    def admin_api_users():
        page = max(int(request.args.get("page", 1)), 1)
        per  = min(int(request.args.get("per", 20)), 100)
        q    = _users_query()
        total = q.count()
        users = q.offset((page - 1) * per).limit(per).all()
        return jsonify({"ok": True, "total": total, "page": page, "per": per,
                        "users": [_user_row(u) for u in users]})

    @app.route("/admin/api/users/export.csv")
    @admin_required("support")
    def admin_api_users_export():
        _audit("users.export")
        rows = [(u.id, u.username, u.email, u.plan, u.role, u.status,
                 u.created_at or "", u.last_seen or "")
                for u in _users_query().all()]
        return _csv_response(rows, ["id", "username", "email", "plan", "role",
                                    "status", "created_at", "last_seen"], "users.csv")

    @app.route("/admin/api/users/<int:user_id>")
    @admin_required("viewer")
    def admin_api_user_detail(user_id):
        u = db.session.get(User, user_id)
        if not u:
            return jsonify({"ok": False, "error": "User not found"}), 404
        payments = [{"id": p.id, "provider": p.provider, "amount": p.amount,
                     "currency": p.currency, "status": p.status,
                     "reference": p.reference,
                     "created_at": p.created_at.isoformat()}
                    for p in Payment.query.filter_by(user_id=u.id)
                        .order_by(Payment.id.desc()).limit(50)]
        activity = [{"action": a.action, "detail": a.detail, "ip": a.ip,
                     "at": a.created_at.isoformat()}
                    for a in ActivityLog.query.filter_by(user_id=u.id)
                        .order_by(ActivityLog.id.desc()).limit(50)]
        preds = [{"ticker": p.ticker, "interval": p.interval,
                  "direction": p.direction, "confidence": p.confidence,
                  "at": p.predicted_at.isoformat()}
                 for p in PredictionHistory.query.filter_by(user_id=u.id)
                     .order_by(PredictionHistory.id.desc()).limit(50)]
        return jsonify({"ok": True, "user": _user_row(u),
                        "pro_expires_at": str(u.pro_expires_at or ""),
                        "payments": payments, "activity": activity,
                        "predictions": preds})

    def _apply_user_action(u, action, reason=None):
        """Returns (ok, message_or_extra). Caller commits + audits."""
        if action == "activate":
            u.status = "active"
            u.ban_reason = None
        elif action == "deactivate":
            u.status = "deactivated"
        elif action == "ban":
            if not reason:
                return False, "A reason is required to ban a user"
            u.status = "banned"
            u.ban_reason = reason
        elif action == "unban":
            u.status = "active"
            u.ban_reason = None
        elif action == "reset_password":
            token = secrets.token_urlsafe(32)
            db.session.add(PasswordResetToken(
                user_id=u.id, token=token,
                expires_at=datetime.utcnow() + timedelta(hours=1)))
            return True, {"reset_link": url_for("reset_password", token=token,
                                                _external=True)}
        else:
            return False, "Unknown action"
        return True, {}

    @app.route("/admin/api/users/<int:user_id>/action", methods=["POST"])
    @admin_required("support")
    def admin_api_user_action(user_id):
        u = db.session.get(User, user_id)
        if not u:
            return jsonify({"ok": False, "error": "User not found"}), 404
        data   = request.get_json() or {}
        action = data.get("action", "")

        if action in ("set_role", "delete"):
            if current_user.role_level < ROLE_LEVELS["admin"]:
                return jsonify({"ok": False, "error": "Admin role required"}), 403
            if u.id == current_user.id:
                return jsonify({"ok": False, "error": "You cannot modify your own account here"}), 400
            if action == "set_role":
                role = data.get("role", "user")
                if role not in ROLE_LEVELS:
                    return jsonify({"ok": False, "error": "Invalid role"}), 400
                old = u.role
                u.role = role
                db.session.commit()
                _audit("user.set_role", "user", u.id, f"{old} → {role}")
                return jsonify({"ok": True})
            # delete
            for model in (PredictionHistory, PriceAlert, PortfolioPosition,
                          ApiKey, Notification, ActivityLog, PasswordResetToken):
                model.query.filter_by(user_id=u.id).delete()
            name = u.username
            db.session.delete(u)
            db.session.commit()
            _audit("user.delete", "user", user_id, f"deleted {name}")
            return jsonify({"ok": True})

        if u.role_level >= ROLE_LEVELS["admin"] and u.id != current_user.id:
            return jsonify({"ok": False, "error": "Cannot act on another admin"}), 403
        reason = (data.get("reason") or "").strip()[:200]
        ok, extra = _apply_user_action(u, action, reason=reason)
        if not ok:
            return jsonify({"ok": False, "error": extra}), 400
        db.session.commit()
        detail = f"{u.username}: {reason}" if action == "ban" else u.username
        _audit(f"user.{action}", "user", u.id, detail)
        return jsonify({"ok": True, **(extra if isinstance(extra, dict) else {})})

    @app.route("/admin/api/users/bulk", methods=["POST"])
    @admin_required("support")
    def admin_api_users_bulk():
        data   = request.get_json() or {}
        ids    = [int(i) for i in data.get("ids", [])][:200]
        action = data.get("action", "")
        if action not in ("activate", "deactivate"):
            return jsonify({"ok": False, "error": "Invalid bulk action"}), 400
        done = 0
        for uid in ids:
            u = db.session.get(User, uid)
            if u and u.role_level < ROLE_LEVELS["admin"]:
                u.status = "active" if action == "activate" else "deactivated"
                done += 1
        db.session.commit()
        _audit(f"users.bulk_{action}", "user", None, f"{done} users: {ids}")
        return jsonify({"ok": True, "affected": done})

    @app.route("/admin/api/users/<int:user_id>/resend-verification", methods=["POST"])
    @admin_required("support")
    def admin_api_user_resend_verification(user_id):
        u = db.session.get(User, user_id)
        if not u:
            return jsonify({"ok": False, "error": "User not found"}), 404
        if u.email_verified:
            return jsonify({"ok": False, "error": "User is already verified"}), 400
        send_fn = app.extensions.get("bulllogic", {}).get("send_verification_email")
        if not send_fn:
            return jsonify({"ok": False, "error": "Verification is not configured"}), 500
        sent = send_fn(u)
        _audit("user.resend_verification", "user", u.id,
               u.username + (" (sent)" if sent else " (send failed, no mailer configured)"))
        if not sent:
            return jsonify({"ok": False,
                            "error": "Email is not configured on the server."}), 502
        return jsonify({"ok": True})

    # ══ API: tickers / predictions / models ═══════════════════════════════════

    @app.route("/admin/api/tickers")
    @admin_required("viewer")
    def admin_api_tickers():
        rows = TickerConfig.query.order_by(TickerConfig.symbol).all()
        counts = dict(db.session.query(PredictionHistory.ticker,
                                       db.func.count(PredictionHistory.id))
                      .group_by(PredictionHistory.ticker).all())
        return jsonify({"ok": True, "tickers": [
            {"id": t.id, "symbol": t.symbol, "name": t.name,
             "enabled": bool(t.enabled), "added_at": t.added_at.isoformat(),
             "predictions": counts.get(t.symbol, 0),
             "has_model": os.path.exists(os.path.join(MODELS_DIR, f"rf_model_{t.symbol}.pkl"))}
            for t in rows]})

    @app.route("/admin/api/tickers", methods=["POST"])
    @admin_required("admin")
    def admin_api_ticker_add():
        data   = request.get_json() or {}
        symbol = (data.get("symbol") or "").upper().strip()[:12]
        if not symbol or not symbol.replace("^", "").replace("-", "").isalnum():
            return jsonify({"ok": False, "error": "Invalid symbol"}), 400
        if TickerConfig.query.filter_by(symbol=symbol).first():
            return jsonify({"ok": False, "error": "Ticker already exists"}), 400
        db.session.add(TickerConfig(symbol=symbol,
                                    name=(data.get("name") or "")[:60] or None,
                                    enabled=bool(data.get("enabled", True))))
        db.session.commit()
        _audit("ticker.add", "ticker", symbol)
        return jsonify({"ok": True})

    @app.route("/admin/api/tickers/<int:tid>", methods=["POST", "DELETE"])
    @admin_required("admin")
    def admin_api_ticker_edit(tid):
        t = db.session.get(TickerConfig, tid)
        if not t:
            return jsonify({"ok": False, "error": "Not found"}), 404
        if request.method == "DELETE":
            _audit("ticker.delete", "ticker", t.symbol)
            db.session.delete(t)
            db.session.commit()
            return jsonify({"ok": True})
        data = request.get_json() or {}
        if "enabled" in data:
            t.enabled = bool(data["enabled"])
        if "name" in data:
            t.name = (data["name"] or "")[:60] or None
        db.session.commit()
        _audit("ticker.update", "ticker", t.symbol,
               f"enabled={t.enabled} name={t.name}")
        return jsonify({"ok": True})

    @app.route("/admin/api/predictions")
    @admin_required("viewer")
    def admin_api_predictions():
        page = max(int(request.args.get("page", 1)), 1)
        per  = min(int(request.args.get("per", 25)), 100)
        q = PredictionHistory.query
        if request.args.get("ticker"):
            q = q.filter(PredictionHistory.ticker == request.args["ticker"].upper())
        if request.args.get("interval"):
            q = q.filter(PredictionHistory.interval == request.args["interval"])
        for arg, op in (("from", ">="), ("to", "<=")):
            val = request.args.get(arg)
            if val:
                try:
                    dt = datetime.fromisoformat(val)
                    q = (q.filter(PredictionHistory.predicted_at >= dt) if op == ">="
                         else q.filter(PredictionHistory.predicted_at <= dt + timedelta(days=1)))
                except ValueError:
                    pass
        total = q.count()
        rows = (q.order_by(PredictionHistory.id.desc())
                 .offset((page - 1) * per).limit(per).all())
        users = {u.id: u.username for u in
                 User.query.filter(User.id.in_({r.user_id for r in rows})).all()} if rows else {}
        return jsonify({"ok": True, "total": total, "page": page, "per": per,
                        "predictions": [
                            {"id": r.id, "user": users.get(r.user_id, "?"),
                             "ticker": r.ticker, "interval": r.interval,
                             "price": r.current_price, "lr": r.lr_pred,
                             "rf": r.rf_pred, "direction": r.direction,
                             "confidence": r.confidence,
                             "at": r.predicted_at.isoformat()} for r in rows]})

    @app.route("/admin/api/models")
    @admin_required("viewer")
    def admin_api_models():
        import json as _json
        metrics = {}
        mpath = os.path.join(BASE_DIR, "Data", "model_metrics.json")
        if os.path.exists(mpath):
            try:
                with open(mpath) as f:
                    metrics = _json.load(f)
            except Exception:
                pass
        models = []
        if os.path.isdir(MODELS_DIR):
            for t in TickerConfig.query.order_by(TickerConfig.symbol).all():
                for kind, fname in (("Random Forest", f"rf_model_{t.symbol}.pkl"),
                                    ("Linear Regression", f"lr_model_{t.symbol}.pkl"),
                                    ("LSTM", f"lstm_model_{t.symbol}.keras")):
                    fpath = os.path.join(MODELS_DIR, fname)
                    if os.path.exists(fpath):
                        models.append({
                            "ticker": t.symbol, "kind": kind,
                            "enabled": bool(t.enabled),
                            "size_kb": round(os.path.getsize(fpath) / 1024, 1),
                            "trained_at": datetime.fromtimestamp(
                                os.path.getmtime(fpath)).isoformat()})
        return jsonify({"ok": True, "models": models,
                        "metrics_trained_at": metrics.get("trained_at"),
                        "metrics": metrics.get("results", {}),
                        "retrain": _retrain})

    @app.route("/admin/api/models/retrain", methods=["POST"])
    @admin_required("admin")
    def admin_api_models_retrain():
        if _retrain["running"]:
            return jsonify({"ok": False, "error": "A retrain is already running"}), 409
        data    = request.get_json() or {}
        tickers = [str(t).upper() for t in data.get("tickers", [])][:12]
        valid   = {t.symbol for t in TickerConfig.query.all()}
        tickers = [t for t in tickers if t in valid]
        if not tickers:
            return jsonify({"ok": False, "error": "No valid tickers given"}), 400
        _retrain.update(running=True, ticker=",".join(tickers),
                        started_at=datetime.utcnow().isoformat(),
                        finished_at=None, returncode=None, tail="starting…")
        threading.Thread(target=_run_retrain, args=(tickers,), daemon=True).start()
        _audit("models.retrain", "model", ",".join(tickers))
        return jsonify({"ok": True})

    @app.route("/admin/api/models/retrain/status")
    @admin_required("viewer")
    def admin_api_retrain_status():
        return jsonify({"ok": True, "retrain": _retrain})

    # ══ API: payments ═════════════════════════════════════════════════════════

    def _payments_query():
        q = Payment.query
        if request.args.get("status"):
            q = q.filter(Payment.status == request.args["status"])
        if request.args.get("provider"):
            q = q.filter(Payment.provider == request.args["provider"])
        if request.args.get("flagged") == "1":
            q = q.filter(Payment.flagged.is_(True))
        term = request.args.get("q", "").strip()
        if term:
            q = q.filter(Payment.reference.ilike(f"%{term}%"))
        for arg in ("from", "to"):
            val = request.args.get(arg)
            if val:
                try:
                    dt = datetime.fromisoformat(val)
                    q = (q.filter(Payment.created_at >= dt) if arg == "from"
                         else q.filter(Payment.created_at <= dt + timedelta(days=1)))
                except ValueError:
                    pass
        return q.order_by(Payment.id.desc())

    def _payment_row(p, users):
        return {"id": p.id, "user": users.get(p.user_id, "?"),
                "user_id": p.user_id, "provider": p.provider, "plan": p.plan,
                "amount": p.amount, "currency": p.currency, "days": p.days,
                "phone": p.phone, "reference": p.reference,
                "receipt": p.receipt, "status": p.status,
                "flagged": bool(p.flagged),
                "created_at": p.created_at.isoformat(),
                "completed_at": p.completed_at.isoformat() if p.completed_at else None}

    @app.route("/admin/api/payments")
    @admin_required("viewer")
    def admin_api_payments():
        page  = max(int(request.args.get("page", 1)), 1)
        per   = min(int(request.args.get("per", 25)), 100)
        q     = _payments_query()
        total = q.count()
        rows  = q.offset((page - 1) * per).limit(per).all()
        users = {u.id: u.username for u in
                 User.query.filter(User.id.in_({r.user_id for r in rows})).all()} if rows else {}
        return jsonify({"ok": True, "total": total, "page": page, "per": per,
                        "payments": [_payment_row(p, users) for p in rows]})

    @app.route("/admin/api/payments/summary")
    @admin_required("viewer")
    def admin_api_payments_summary():
        def _sum(since=None):
            q = (db.session.query(Payment.currency,
                                  db.func.sum(Payment.amount))
                 .filter(Payment.status == "paid"))
            if since:
                q = q.filter(Payment.completed_at >= since)
            return {c or "?": float(s or 0) for c, s in q.group_by(Payment.currency)}
        now = datetime.utcnow()
        return jsonify({"ok": True,
                        "today":     _sum(datetime.combine(date.today(), datetime.min.time())),
                        "this_week": _sum(now - timedelta(days=7)),
                        "this_month": _sum(now - timedelta(days=30)),
                        "all_time":  _sum(),
                        "counts": {s: c for s, c in
                                   db.session.query(Payment.status, db.func.count())
                                   .group_by(Payment.status)}})

    @app.route("/admin/api/payments/<int:pid>/refund", methods=["POST"])
    @admin_required("support")
    def admin_api_payment_refund(pid):
        p = db.session.get(Payment, pid)
        if not p:
            return jsonify({"ok": False, "error": "Not found"}), 404
        if p.status != "paid":
            return jsonify({"ok": False, "error": "Only paid transactions can be refunded"}), 400
        note = ((request.get_json() or {}).get("note") or "").strip()[:300]
        p.status = "refunded"
        p.notes = note or None
        # Revoke the granted days from the user's Pro expiry.
        u = db.session.get(User, p.user_id)
        if u and u.pro_expires_at and p.days:
            u.pro_expires_at = u.pro_expires_at - timedelta(days=p.days)
            if u.pro_expires_at <= date.today():
                u.plan = "free"
                u.pro_expires_at = None
        db.session.commit()
        detail = f"{p.amount} {p.currency} ref={p.reference} (money movement is manual)"
        if note:
            detail += f"; note: {note}"
        _audit("payment.refund", "payment", p.id, detail)
        return jsonify({"ok": True, "note": "Marked refunded and Pro days revoked. "
                        "Actual M-Pesa reversal must be done in the Daraja portal."})

    @app.route("/admin/api/payments/<int:pid>/flag", methods=["POST"])
    @admin_required("support")
    def admin_api_payment_flag(pid):
        p = db.session.get(Payment, pid)
        if not p:
            return jsonify({"ok": False, "error": "Not found"}), 404
        p.flagged = not bool(p.flagged)
        db.session.commit()
        _audit("payment.flag" if p.flagged else "payment.unflag", "payment", p.id)
        return jsonify({"ok": True, "flagged": p.flagged})

    @app.route("/admin/api/payments/export.csv")
    @admin_required("support")
    def admin_api_payments_export():
        _audit("payments.export")
        users = {u.id: u.username for u in User.query.all()}
        rows = [(p.id, users.get(p.user_id, "?"), p.provider, p.plan, p.amount,
                 p.currency, p.status, "yes" if p.flagged else "",
                 p.reference, p.receipt, p.created_at, p.completed_at or "")
                for p in _payments_query().all()]
        return _csv_response(rows, ["id", "user", "provider", "plan", "amount",
                                    "currency", "status", "flagged", "reference",
                                    "receipt", "created_at", "completed_at"],
                             "transactions.csv")

    # ══ API: analytics ════════════════════════════════════════════════════════

    @app.route("/admin/api/analytics")
    @admin_required("viewer")
    def admin_api_analytics():
        days = min(int(request.args.get("days", 30)), 90)
        dau = _day_series(User.last_seen, days)
        mau = User.query.filter(
            User.last_seen >= datetime.utcnow() - timedelta(days=30)).count()

        top = (db.session.query(PredictionHistory.ticker,
                                db.func.count(PredictionHistory.id))
               .group_by(PredictionHistory.ticker)
               .order_by(db.func.count(PredictionHistory.id).desc())
               .limit(10).all())
        by_interval = (db.session.query(PredictionHistory.interval,
                                        db.func.count(PredictionHistory.id))
                       .group_by(PredictionHistory.interval).all())

        total_users = User.query.count()
        predicted   = (db.session.query(db.func.count(
                           db.func.distinct(PredictionHistory.user_id))).scalar()) or 0
        paid        = (db.session.query(db.func.count(db.func.distinct(Payment.user_id)))
                       .filter(Payment.status == "paid").scalar()) or 0

        # Weekly retention: of users created in week N, how many were seen in
        # the last 7 days.
        cohorts = []
        for w in range(6):
            start = datetime.utcnow() - timedelta(weeks=w + 1)
            end   = datetime.utcnow() - timedelta(weeks=w)
            cohort = User.query.filter(User.created_at >= start,
                                       User.created_at < end)
            size = cohort.count()
            retained = cohort.filter(
                User.last_seen >= datetime.utcnow() - timedelta(days=7)).count()
            cohorts.append({"week": f"{w+1}w ago", "size": size,
                            "retained": retained,
                            "pct": round(retained / size * 100, 1) if size else None})

        return jsonify({"ok": True, "dau": dau, "mau": mau,
                        "top_tickers": [{"ticker": t, "count": c} for t, c in top],
                        "by_interval": [{"interval": i or "1d", "count": c}
                                        for i, c in by_interval],
                        "funnel": {"signups": total_users, "predicted": predicted,
                                   "paid": paid},
                        "retention": cohorts})

    @app.route("/admin/api/analytics/report.csv")
    @admin_required("viewer")
    def admin_api_analytics_report():
        days = min(int(request.args.get("days", 30)), 90)
        signups = _day_series(User.created_at, days)
        preds   = _day_series(PredictionHistory.predicted_at, days)
        dau     = _day_series(User.last_seen, days)
        rows = [(s["date"], s["count"], p["count"], d["count"])
                for s, p, d in zip(signups, preds, dau)]
        _audit("analytics.export")
        return _csv_response(rows, ["date", "signups", "predictions", "dau"],
                             f"report_{days}d.csv")

    # ══ API: system ═══════════════════════════════════════════════════════════

    @app.route("/admin/api/errors")
    @admin_required("viewer")
    def admin_api_errors():
        page = max(int(request.args.get("page", 1)), 1)
        per  = min(int(request.args.get("per", 25)), 100)
        q = ErrorLog.query
        if request.args.get("severity"):
            q = q.filter(ErrorLog.severity == request.args["severity"])
        if request.args.get("endpoint"):
            q = q.filter(ErrorLog.endpoint.ilike(f"%{request.args['endpoint']}%"))
        for arg in ("from", "to"):
            val = request.args.get(arg)
            if val:
                try:
                    dt = datetime.fromisoformat(val)
                    q = (q.filter(ErrorLog.created_at >= dt) if arg == "from"
                         else q.filter(ErrorLog.created_at <= dt + timedelta(days=1)))
                except ValueError:
                    pass
        total = q.count()
        rows  = q.order_by(ErrorLog.id.desc()).offset((page - 1) * per).limit(per).all()
        return jsonify({"ok": True, "total": total, "page": page, "per": per,
                        "errors": [{"id": e.id, "severity": e.severity,
                                    "endpoint": e.endpoint, "method": e.method,
                                    "message": e.message, "trace": e.trace,
                                    "ip": e.ip, "at": e.created_at.isoformat()}
                                   for e in rows]})

    @app.route("/admin/api/system")
    @admin_required("viewer")
    def admin_api_system():
        stats = sorted(
            ({"endpoint": k, "count": v["count"],
              "avg_ms": round(v["total_ms"] / v["count"], 1) if v["count"] else 0,
              "errors": v["errors"]} for k, v in endpoint_stats.items()),
            key=lambda r: r["count"], reverse=True)[:40]

        db_path = os.path.join(BASE_DIR, "instance", "users.db")
        db_mb = round(os.path.getsize(db_path) / 1e6, 2) if os.path.exists(db_path) else 0

        azure = {"enabled": False, "blobs": None}
        try:
            from azure_storage import azure_enabled, list_models_in_azure
            azure["enabled"] = azure_enabled()
            if azure["enabled"]:
                blobs = list_models_in_azure()
                azure["blobs"] = len(blobs)
        except Exception as e:
            azure["error"] = str(e)[:100]

        jobs = [{"name": "Price-alert checker", "status": "running",
                 "detail": "polls every 120s (in-process thread)"},
                {"name": "Model retrain",
                 "status": "running" if _retrain["running"] else "idle",
                 "detail": (_retrain["ticker"] or "") if _retrain["running"]
                           else (f"last: {_retrain['finished_at'] or 'never'}"
                                 f" rc={_retrain['returncode']}"
                                 if _retrain["finished_at"] else "never run")}]

        # Manually run-able jobs (grading, data fetch, retraining, etc). This
        # is a read-only status view; use the Job Runner page to run one now.
        try:
            from routes.admin_jobs import JOB_REGISTRY, job_status
            status = job_status()
            for key, meta in JOB_REGISTRY.items():
                st = status.get(key, {})
                if st.get("running"):
                    detail = "running now"
                elif st.get("last_run"):
                    detail = f"last: {st['last_run']} ok={st.get('last_ok')}"
                else:
                    detail = "never run, use Job Runner"
                jobs.append({"name": meta["label"],
                            "status": "running" if st.get("running") else "idle",
                            "detail": detail})
        except Exception:
            pass

        return jsonify({"ok": True, "endpoints": stats,
                        "uptime_s": round(time.time() - app_start, 1),
                        "db_mb": db_mb, "azure": azure, "jobs": jobs,
                        "error_count_24h": ErrorLog.query.filter(
                            ErrorLog.created_at >= datetime.utcnow() - timedelta(hours=24)).count()})

    # ══ API: broadcasts ═══════════════════════════════════════════════════════

    def _segment_users(segment):
        q = User.query.filter(User.status == "active")
        if segment == "free":
            q = q.filter(User.plan != "pro")
        elif segment == "pro":
            q = q.filter(User.plan == "pro")
        return q.all()

    @app.route("/admin/api/broadcasts")
    @admin_required("viewer")
    def admin_api_broadcasts():
        admins = {u.id: u.username for u in
                  User.query.filter(User.role != "user").all()}
        return jsonify({"ok": True, "broadcasts": [
            {"id": b.id, "title": b.title, "body": b.body,
             "segment": b.segment, "channel": b.channel,
             "sent_count": b.sent_count, "by": admins.get(b.admin_id, "?"),
             "at": b.created_at.isoformat()}
            for b in Broadcast.query.order_by(Broadcast.id.desc()).limit(50)]})

    @app.route("/admin/api/broadcasts", methods=["POST"])
    @admin_required("support")
    def admin_api_broadcast_send():
        data    = request.get_json() or {}
        title   = (data.get("title") or "").strip()[:100]
        body    = (data.get("body") or "").strip()[:1000]
        segment = data.get("segment", "all")
        channel = data.get("channel", "in-app")
        if not title or not body:
            return jsonify({"ok": False, "error": "Title and body are required"}), 400
        if segment not in ("all", "free", "pro") or channel not in ("in-app", "email", "both"):
            return jsonify({"ok": False, "error": "Invalid segment or channel"}), 400

        targets = _segment_users(segment)
        sent = 0
        if channel in ("in-app", "both"):
            for u in targets:
                db.session.add(Notification(user_id=u.id, type="announcement",
                                            title=title, body=body[:300]))
                sent += 1
        emails_queued = 0
        if channel in ("email", "both"):
            from extensions import mail
            if mail and app.config.get("MAIL_USERNAME"):
                recipients = [u.email for u in targets]
                emails_queued = len(recipients)

                def _send_bulk(recips):
                    from flask_mail import Message as M
                    with app.app_context():
                        for r in recips:
                            try:
                                mail.send(M(subject=f"[BullLogic] {title}",
                                            recipients=[r], body=body))
                            except Exception:
                                pass
                threading.Thread(target=_send_bulk, args=(recipients,),
                                 daemon=True).start()
            else:
                return jsonify({"ok": False,
                                "error": "Email is not configured (MAIL_USERNAME)"}), 400

        bc = Broadcast(admin_id=current_user.id, title=title, body=body,
                       segment=segment, channel=channel,
                       sent_count=max(sent, emails_queued))
        db.session.add(bc)
        db.session.commit()
        _audit("broadcast.send", "broadcast", bc.id,
               f"{channel}/{segment}: {title} → {bc.sent_count} users")
        return jsonify({"ok": True, "sent": bc.sent_count})

    # ══ API: settings ═════════════════════════════════════════════════════════

    _EDITABLE_SETTINGS = {"app_name", "maintenance_mode", "registration_open",
                          "feature_signals", "feature_mpesa",
                          "pro_monthly_kes", "pro_annual_kes"}

    _MASKED_ENV_KEYS = ["ALPACA_API_KEY", "ALPACA_SECRET_KEY",
                        "AZURE_STORAGE_CONNECTION_STRING",
                        "MPESA_CONSUMER_KEY", "MPESA_CONSUMER_SECRET",
                        "MPESA_PASSKEY", "STRIPE_SECRET_KEY",
                        "STRIPE_WEBHOOK_SECRET", "MAIL_USERNAME",
                        "ANTHROPIC_API_KEY", "FINNHUB_API_KEY", "PYTH_API_KEY"]

    @app.route("/admin/api/settings")
    @admin_required("admin")
    def admin_api_settings():
        settings = {s.key: s.value for s in AppSetting.query.all()}
        admins = [{"id": u.id, "username": u.username, "email": u.email,
                   "role": u.role, "status": u.status}
                  for u in User.query.filter(User.role.in_(
                      ["viewer", "support", "admin"])).all()]

        def _mask(v):
            if not v:
                return None
            return v[:4] + "…" + v[-4:] if len(v) > 12 else "•" * len(v)
        env_keys = [{"key": k, "configured": bool(os.environ.get(k)),
                     "masked": _mask(os.environ.get(k, ""))}
                    for k in _MASKED_ENV_KEYS]
        return jsonify({"ok": True, "settings": settings, "admins": admins,
                        "env_keys": env_keys,
                        "session_minutes": ADMIN_SESSION_MINUTES})

    @app.route("/admin/api/settings", methods=["POST"])
    @admin_required("admin")
    def admin_api_settings_save():
        data = request.get_json() or {}
        changed = []
        for k, v in data.items():
            if k in _EDITABLE_SETTINGS:
                _set_setting(k, str(v)[:500])
                changed.append(f"{k}={str(v)[:50]}")
        db.session.commit()
        try:
            from app import invalidate_settings_cache
            invalidate_settings_cache()
        except Exception:
            pass
        _audit("settings.update", "setting", None, "; ".join(changed))
        return jsonify({"ok": True, "changed": len(changed)})

    # ══ API: MT5 algorithm control panel ═════════════════════════════════════
    # Never returns the MT5 password or MetaApi token - trader.account only
    # ever holds login/name/server/currency/balance/equity/margin/leverage,
    # the credentials themselves are passed through connect() and not stored.

    _MT5_RANGES = {
        "ict_score_threshold":   (1, 8),     "total_score_threshold": (1, 15),
        "pd_zone_buy_strong":    (0.20, 0.50), "pd_zone_buy_weak":    (0.30, 0.60),
        "pd_zone_sell_strong":   (0.50, 0.80), "pd_zone_sell_weak":   (0.40, 0.70),
        "ob_pts": (1, 5), "fvg_pts": (1, 3), "sweep_pts": (1, 5), "displacement_pts": (1, 3),
        "ml_agreement_pts": (1, 5), "ml_conflict_pts": (-5, 0),
        "rsi_period": (5, 30), "rsi_oversold": (10, 40), "rsi_overbought": (60, 90),
        "rsi_soft_os": (20, 45), "rsi_soft_ob": (55, 80),
        "macd_fast": (5, 20), "macd_slow": (15, 40), "macd_signal_period": (5, 15),
        "macd_cross_pts": (1, 5), "macd_trend_pts": (1, 3), "ema_period": (10, 50),
        "risk_pct": (0.1, 10), "sl_multiplier": (0.5, 5.0), "tp_multiplier": (1.0, 10.0),
        "atr_period": (5, 30), "max_positions": (1, 10),
        "daily_loss_limit": (0.01, 0.20), "max_lot": (0.01, 100), "min_lot": (0.01, 1.0),
        "paper_balance": (100, 1_000_000), "interval_sec": (10, 3600),
    }
    _MT5_TIMEFRAMES = {"M1", "M5", "M15", "M30", "H1", "H4", "D1"}

    def _validate_mt5_config(data):
        errors = []
        for key, (lo, hi) in _MT5_RANGES.items():
            if key not in data:
                continue
            try:
                v = float(data[key])
            except (TypeError, ValueError):
                errors.append(f"{key} must be a number")
                continue
            if not (lo <= v <= hi):
                errors.append(f"{key} must be between {lo} and {hi}")
        if "min_lot" in data and "max_lot" in data:
            try:
                if float(data["min_lot"]) >= float(data["max_lot"]):
                    errors.append("min_lot must be less than max_lot")
            except (TypeError, ValueError):
                pass
        if "timeframe" in data and data["timeframe"] not in _MT5_TIMEFRAMES:
            errors.append(f"timeframe must be one of {', '.join(sorted(_MT5_TIMEFRAMES))}")
        if "symbol" in data and not str(data["symbol"]).strip():
            errors.append("symbol cannot be empty")
        return errors

    @app.route("/admin/api/mt5/config")
    @admin_required("admin")
    def admin_api_mt5_config():
        import mt5_config
        return jsonify({"ok": True, "config": mt5_config.load()})

    @app.route("/admin/api/mt5/config", methods=["POST"])
    @admin_required("admin")
    def admin_api_mt5_config_save():
        import mt5_config
        data = request.get_json() or {}
        if not data:
            return jsonify({"ok": False, "error": "No data"}), 400
        errors = _validate_mt5_config(data)
        if errors:
            return jsonify({"ok": False, "errors": errors}), 400
        if "symbol" in data:
            data["symbol"] = str(data["symbol"]).strip().upper()
        merged = mt5_config.save(data)
        _audit("mt5.config.update", "mt5_config", None,
              "; ".join(f"{k}={data[k]}" for k in data))
        return jsonify({"ok": True, "config": merged})

    @app.route("/admin/api/mt5/config/reset", methods=["POST"])
    @admin_required("admin")
    def admin_api_mt5_config_reset():
        import mt5_config
        defaults = mt5_config.reset()
        _audit("mt5.config.reset", "mt5_config")
        return jsonify({"ok": True, "config": defaults})

    @app.route("/admin/api/mt5/status")
    @admin_required("admin")
    def admin_api_mt5_status():
        import mt5_config
        from mt5_trading import trader as mt5_trader, live_trading_enabled
        status = mt5_trader.get_status()
        log_entries = status.get("log", [])
        trades = [e for e in log_entries if e["level"] in ("TRADE", "PAPER TRADE")]
        closed = [e for e in log_entries if "CLOSE" in e["level"]]
        return jsonify({
            "ok": True,
            "status": status,
            "config": mt5_config.load(),
            "live_trading_enabled": live_trading_enabled(),
            "metrics": {
                "total_signals": len([e for e in log_entries if e["level"] == "SIGNAL"]),
                "total_trades":  len(trades),
                "total_closed":  len(closed),
                "errors":        len([e for e in log_entries if e["level"] == "ERROR"]),
            },
        })

    @app.route("/admin/api/mt5/live-trading", methods=["POST"])
    @admin_required("admin")
    def admin_api_mt5_live_trading():
        from mt5_trading import set_live_trading_enabled, live_trading_enabled
        data = request.get_json() or {}
        if "enabled" not in data:
            return jsonify({"ok": False, "error": "Missing 'enabled'"}), 400
        enabled = bool(data["enabled"])
        set_live_trading_enabled(enabled)
        _audit("mt5.live_trading." + ("enable" if enabled else "disable"),
              "mt5_trader", None,
              f"Live trading {'ENABLED' if enabled else 'disabled'} by {current_user.username}")
        return jsonify({"ok": True, "live_trading_enabled": live_trading_enabled()})

    @app.route("/admin/api/mt5/start", methods=["POST"])
    @admin_required("admin")
    def admin_api_mt5_start():
        import mt5_config
        from mt5_trading import trader as mt5_trader
        cfg = mt5_config.load()
        result = mt5_trader.start_trading(
            symbol=cfg["symbol"], timeframe=cfg["timeframe"],
            risk_pct=cfg["risk_pct"], interval=cfg["interval_sec"],
            use_ml=cfg["use_ml"],
        )
        if result.get("ok"):
            _audit("mt5.start", "mt5_trader", None, f"{cfg['symbol']} {cfg['timeframe']}")
        return jsonify(result)

    @app.route("/admin/api/mt5/stop", methods=["POST"])
    @admin_required("admin")
    def admin_api_mt5_stop():
        from mt5_trading import trader as mt5_trader
        result = mt5_trader.stop_trading()
        if result.get("ok"):
            _audit("mt5.stop", "mt5_trader")
        return jsonify(result)

    @app.route("/admin/api/mt5/signal")
    @admin_required("admin")
    def admin_api_mt5_signal():
        import mt5_config
        from mt5_trading import trader as mt5_trader
        cfg = mt5_config.load()
        signal = (mt5_trader.generate_signal_ml(cfg["symbol"]) if cfg["use_ml"]
                  else mt5_trader.generate_signal(cfg["symbol"]))
        return jsonify({"ok": True, "signal": signal})

    @app.route("/admin/api/mt5/log")
    @admin_required("admin")
    def admin_api_mt5_log():
        from mt5_trading import trader as mt5_trader
        return jsonify({"ok": True, "log": list(mt5_trader.trade_log)})

    @app.route("/admin/api/mt5/paper/reset", methods=["POST"])
    @admin_required("admin")
    def admin_api_mt5_paper_reset():
        import mt5_config
        from mt5_trading import trader as mt5_trader, PaperAccount
        if not mt5_trader.is_paper:
            return jsonify({"ok": False, "error": "Not in paper mode"}), 400
        cfg = mt5_config.load()
        mt5_trader._paper = PaperAccount(balance=cfg["paper_balance"])
        mt5_trader.account = mt5_trader._paper.info()
        mt5_trader.equity_open = mt5_trader._paper.balance
        _audit("mt5.paper.reset", "mt5_trader", None, f"balance={cfg['paper_balance']}")
        return jsonify({"ok": True, "account": mt5_trader.account})

    # ══ API: data quality (sources, Pyth feeds, divergences) ═════════════════

    @app.route("/admin/api/data-quality")
    @admin_required("viewer")
    def admin_api_data_quality():
        from market_data import source_stats, data_status
        from models import PythFeed
        incidents = (ErrorLog.query.filter_by(endpoint="data.divergence")
                     .order_by(ErrorLog.id.desc()).limit(20).all())
        feeds = PythFeed.query.order_by(PythFeed.symbol).all()

        # Does wide Pyth confidence correlate with worse predictions?
        buckets = []
        for label, lo, hi in [("tight (<0.05%)", 0, 0.05),
                              ("normal (0.05-0.2%)", 0.05, 0.2),
                              ("wide (>0.2%)", 0.2, 1e9)]:
            from models import PredictionAccuracy
            n, ok = (db.session.query(
                         db.func.count(PredictionAccuracy.id),
                         db.func.sum(db.case((PredictionAccuracy.direction_ok.is_(True), 1),
                                             else_=0)))
                     .join(PredictionHistory,
                           PredictionAccuracy.prediction_id == PredictionHistory.id)
                     .filter(PredictionHistory.src_conf_pct.isnot(None),
                             PredictionHistory.src_conf_pct >= lo,
                             PredictionHistory.src_conf_pct < hi,
                             PredictionAccuracy.direction_ok.isnot(None))
                     .first())
            n = n or 0
            buckets.append({"bucket": label, "n": n,
                            "accuracy": round((ok or 0) / n * 100, 1) if n >= 5 else None})

        return jsonify({"ok": True, "sources": source_stats(),
                        "breaker": data_status(),
                        "incidents": [{"message": i.message,
                                       "at": i.created_at.isoformat()}
                                      for i in incidents],
                        "feeds": [{"id": f.id, "symbol": f.symbol,
                                   "feed_id": f.feed_id,
                                   "pyth_symbol": f.pyth_symbol,
                                   "active": f.active} for f in feeds],
                        "conf_accuracy": buckets})

    @app.route("/admin/api/pyth-feeds/sync", methods=["POST"])
    @admin_required("admin")
    def admin_api_pyth_sync():
        from models import TickerConfig
        import pyth_client
        symbols = [t.symbol for t in TickerConfig.query.filter_by(enabled=True)]
        try:
            mapped, unmapped = pyth_client.sync_feed_mapping(db, symbols)
        except Exception as e:
            return jsonify({"ok": False, "error": f"Sync failed: {e}"}), 502
        _audit("pyth.sync", "pyth_feed", None, f"{mapped} mapped, {unmapped} unmapped")
        return jsonify({"ok": True, "mapped": mapped, "unmapped": unmapped})

    @app.route("/admin/api/pyth-feeds/<int:fid>", methods=["POST", "DELETE"])
    @admin_required("admin")
    def admin_api_pyth_feed_edit(fid):
        from models import PythFeed
        f = db.session.get(PythFeed, fid)
        if not f:
            return jsonify({"ok": False, "error": "Not found"}), 404
        if request.method == "DELETE":
            _audit("pyth.unlink", "pyth_feed", f.symbol)
            db.session.delete(f)
            db.session.commit()
            return jsonify({"ok": True})
        data = request.get_json() or {}
        if "active" in data:
            f.active = bool(data["active"])
        if data.get("feed_id"):
            f.feed_id = str(data["feed_id"])[:70]
        db.session.commit()
        _audit("pyth.update", "pyth_feed", f.symbol, f"active={f.active}")
        return jsonify({"ok": True})

    # ══ API: resource links CRUD ══════════════════════════════════════════════

    @app.route("/admin/api/resources")
    @admin_required("viewer")
    def admin_api_resources():
        from models import ResourceLink
        rows = ResourceLink.query.order_by(ResourceLink.category,
                                           ResourceLink.sort).all()
        return jsonify({"ok": True, "resources": [
            {"id": r.id, "category": r.category, "title": r.title,
             "url": r.url, "description": r.description, "icon": r.icon,
             "sort": r.sort, "active": r.active} for r in rows]})

    @app.route("/admin/api/resources", methods=["POST"])
    @admin_required("admin")
    def admin_api_resource_add():
        from models import ResourceLink
        d = request.get_json() or {}
        if not d.get("title") or not d.get("url") or not d.get("category"):
            return jsonify({"ok": False, "error": "category, title and url are required"}), 400
        if not str(d["url"]).startswith(("http://", "https://", "/")):
            return jsonify({"ok": False, "error": "URL must be http(s) or a local path"}), 400
        r = ResourceLink(category=str(d["category"])[:40], title=str(d["title"])[:80],
                         url=str(d["url"])[:300],
                         description=(d.get("description") or "")[:200] or None,
                         icon=(d.get("icon") or "")[:10] or None,
                         sort=int(d.get("sort", 0)), active=bool(d.get("active", True)))
        db.session.add(r)
        db.session.commit()
        _audit("resource.add", "resource", r.id, r.title)
        return jsonify({"ok": True, "id": r.id})

    @app.route("/admin/api/resources/<int:rid>", methods=["POST", "DELETE"])
    @admin_required("admin")
    def admin_api_resource_edit(rid):
        from models import ResourceLink
        r = db.session.get(ResourceLink, rid)
        if not r:
            return jsonify({"ok": False, "error": "Not found"}), 404
        if request.method == "DELETE":
            _audit("resource.delete", "resource", rid, r.title)
            db.session.delete(r)
            db.session.commit()
            return jsonify({"ok": True})
        d = request.get_json() or {}
        for field, limit in (("category", 40), ("title", 80), ("url", 300),
                             ("description", 200), ("icon", 10)):
            if field in d:
                setattr(r, field, (str(d[field])[:limit] or None)
                        if field in ("description", "icon") else str(d[field])[:limit])
        if "sort" in d:
            r.sort = int(d["sort"])
        if "active" in d:
            r.active = bool(d["active"])
        db.session.commit()
        _audit("resource.update", "resource", rid, r.title)
        return jsonify({"ok": True})

    # ══ API: user feedback ════════════════════════════════════════════════════

    @app.route("/admin/api/feedback")
    @admin_required("viewer")
    def admin_api_feedback():
        from models import Feedback
        page = max(int(request.args.get("page", 1)), 1)
        per  = min(int(request.args.get("per", 20)), 100)
        q = Feedback.query
        if request.args.get("unresolved") == "1":
            q = q.filter(Feedback.resolved.is_(False))
        total = q.count()
        rows = q.order_by(Feedback.id.desc()).offset((page - 1) * per).limit(per).all()
        users = {u.id: u.username for u in
                 User.query.filter(User.id.in_({r.user_id for r in rows})).all()} if rows else {}
        avg = db.session.query(db.func.avg(Feedback.rating)).scalar()
        sent = db.session.query(db.func.avg(Feedback.sentiment)).filter(
            Feedback.sentiment.isnot(None)).scalar()
        return jsonify({"ok": True, "total": total, "page": page, "per": per,
                        "avg_rating": round(float(avg), 2) if avg is not None else None,
                        "avg_sentiment": round(float(sent), 2) if sent is not None else None,
                        "items": [{"id": f.id, "user": users.get(f.user_id, "?"),
                                   "user_id": f.user_id, "page": f.page,
                                   "rating": f.rating, "comment": f.comment,
                                   "sentiment": f.sentiment, "resolved": f.resolved,
                                   "at": f.created_at.isoformat()} for f in rows]})

    @app.route("/admin/api/feedback/<int:fid>/resolve", methods=["POST"])
    @admin_required("support")
    def admin_api_feedback_resolve(fid):
        from models import Feedback
        f = db.session.get(Feedback, fid)
        if not f:
            return jsonify({"ok": False, "error": "Not found"}), 404
        f.resolved = not bool(f.resolved)
        db.session.commit()
        _audit("feedback.resolve" if f.resolved else "feedback.reopen",
               "feedback", f.id)
        return jsonify({"ok": True, "resolved": f.resolved})

    # ══ API: audit log ════════════════════════════════════════════════════════

    @app.route("/admin/api/audit")
    @admin_required("viewer")
    def admin_api_audit():
        page = max(int(request.args.get("page", 1)), 1)
        per  = min(int(request.args.get("per", 30)), 100)
        q = AdminAuditLog.query
        term = request.args.get("q", "").strip()
        if term:
            q = q.filter((AdminAuditLog.action.ilike(f"%{term}%")) |
                         (AdminAuditLog.detail.ilike(f"%{term}%")) |
                         (AdminAuditLog.target_id.ilike(f"%{term}%")))
        if request.args.get("action"):
            q = q.filter(AdminAuditLog.action == request.args["action"])
        if request.args.get("admin_id"):
            q = q.filter(AdminAuditLog.admin_id == int(request.args["admin_id"]))
        for arg in ("from", "to"):
            val = request.args.get(arg)
            if val:
                try:
                    dt = datetime.fromisoformat(val)
                    q = (q.filter(AdminAuditLog.created_at >= dt) if arg == "from"
                         else q.filter(AdminAuditLog.created_at <= dt + timedelta(days=1)))
                except ValueError:
                    pass
        total = q.count()
        rows = q.order_by(AdminAuditLog.id.desc()).offset((page - 1) * per).limit(per).all()
        admins = {u.id: u.username for u in
                  User.query.filter(User.id.in_({r.admin_id for r in rows})).all()} if rows else {}
        actions = [a[0] for a in db.session.query(AdminAuditLog.action).distinct().all()]
        return jsonify({"ok": True, "total": total, "page": page, "per": per,
                        "actions": sorted(actions),
                        "entries": [{"id": r.id, "admin": admins.get(r.admin_id, "?"),
                                     "admin_id": r.admin_id, "action": r.action,
                                     "target_type": r.target_type,
                                     "target_id": r.target_id, "detail": r.detail,
                                     "ip": r.ip, "at": r.created_at.isoformat()}
                                    for r in rows]})

    # ── Power tools + extended capabilities (routes/admin_power.py) ────────────
    # Shared here so that module reuses the exact same guard, audit sink and
    # CSRF check rather than reimplementing them.
    def _page(template, **kwargs):
        return render_template(template, **kwargs)

    app.extensions.setdefault("bulllogic", {})
    app.extensions["bulllogic"]["admin"] = {
        "admin_required": admin_required,
        "audit": _audit,
        "get_setting": _get_setting,
        "set_setting": _set_setting,
        "page": _page,
        "ROLE_LEVELS": ROLE_LEVELS,
    }
    from routes.admin_power import register_admin_power_routes
    register_admin_power_routes(app)