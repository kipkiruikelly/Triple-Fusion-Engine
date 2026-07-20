"""routes/admin_power.py

Admin power tools and the extended capability groups, built on the same
guard, audit sink and CSRF check as routes/admin.py (passed in via
app.extensions["bulllogic"]["admin"]).

Three fixed guards are enforced here by design:
  1. admin_audit_log is append-only. The SQL console refuses any
     statement touching it that is not a plain SELECT, and the ORM layer
     (models.py) blocks updates/deletes independently.
  2. ENABLE_LIVE_TRADING is shown read-only; it stays env-controlled.
  3. Editing a graded prediction requires a reason and is audited; it is
     never a silent overwrite.

Everything admin-only (min_role "admin") unless noted.
"""

import os
import re
import secrets
from datetime import date, datetime, timedelta

from flask import render_template, request, jsonify, session, redirect, url_for
from flask_login import login_user, current_user
from sqlalchemy import inspect as sa_inspect, text

from extensions import db
from models import (User, PredictionHistory, PredictionAccuracy, Payment,
                    GiftCode, AppSetting, AdminAuditLog, ActivityLog, ROLE_LEVELS)

# Tables the SQL console and table browser will not expose for writes even
# to an admin. admin_audit_log is append-only; alembic bookkeeping is off
# limits.
_AUDIT_TABLE = "admin_audit_log"

# Feature flags surfaced in the panel: (key, label, default).
FEATURE_FLAGS = [
    ("feature_sentiment",   "Sentiment analysis",  "on"),
    ("feature_gamification", "Gamification",       "on"),
    ("feature_ict",         "ICT features",        "on"),
]


def register_admin_power_routes(app):
    admin = app.extensions["bulllogic"]["admin"]
    admin_required = admin["admin_required"]
    _audit = admin["audit"]
    _get_setting = admin["get_setting"]
    _set_setting = admin["set_setting"]
    _page = admin["page"]

    # ══ Pages (server-rendered, admin only) ════════════════════════════════════
    

    # ══ SQL Console ════════════════════════════════════════════════════════════

    def _first_keyword(sql):
        s = sql.strip()
        # strip leading line/block comments
        s = re.sub(r"^\s*(--[^\n]*\n|/\*.*?\*/)\s*", "", s, flags=re.S)
        m = re.match(r"[a-zA-Z]+", s.strip())
        return (m.group(0).lower() if m else "")

    def _statement_count(sql):
        # Rough: count non-empty statements separated by ';'. Enough to
        # refuse stacked queries in the console.
        parts = [p for p in re.split(r";\s*", sql.strip()) if p.strip()]
        return len(parts)

    def _touches_audit(sql):
        return re.search(r"\badmin_audit_log\b", sql, re.I) is not None

    @app.route("/admin/api/sql/run", methods=["POST"])
    @admin_required("admin")
    def admin_api_sql_run():
        data = request.get_json() or {}
        sql = (data.get("sql") or "").strip()
        confirm = bool(data.get("confirm"))
        if not sql:
            return jsonify({"ok": False, "error": "Empty statement"}), 400
        if _statement_count(sql) != 1:
            return jsonify({"ok": False,
                            "error": "Run one statement at a time (no ';' stacking)."}), 400

        kw = _first_keyword(sql)
        read_only = kw in ("select", "explain", "pragma", "with")
        write = kw in ("insert", "update", "delete")

        # Guard 1: audit log is append-only. Only a SELECT may touch it.
        if _touches_audit(sql) and not read_only:
            return jsonify({"ok": False,
                            "error": "admin_audit_log is append-only; only SELECT is allowed on it."}), 403

        if not read_only and not write:
            return jsonify({"ok": False,
                            "error": f"Statement type '{kw or '?'}' is not permitted here "
                                     "(DDL and admin commands are blocked)."}), 403

        # ── READ ──
        if read_only:
            try:
                result = db.session.execute(text(sql))
                cols = list(result.keys())
                rows = [list(r) for r in result.fetchmany(500)]
            except Exception as e:
                db.session.rollback()
                return jsonify({"ok": False, "error": str(e)[:400]}), 400
            _audit("sql.select", "sql", None, sql[:400])
            return jsonify({"ok": True, "mode": "read", "columns": cols,
                            "rows": [[_jsonable(v) for v in row] for row in rows],
                            "truncated": len(rows) >= 500})

        # ── WRITE ── two-phase: preview affected count, then confirm ──
        # Wrap in a transaction we can roll back for the preview.
        try:
            if not confirm:
                affected = _preview_write_count(sql)
                return jsonify({"ok": True, "mode": "preview",
                                "affected": affected,
                                "message": f"This statement affects {affected} row(s). "
                                           "Confirm to execute."})
            result = db.session.execute(text(sql))
            affected = result.rowcount
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return jsonify({"ok": False, "error": str(e)[:400]}), 400
        _audit(f"sql.{kw}", "sql", None, f"[{affected} rows] {sql[:360]}")
        return jsonify({"ok": True, "mode": "write", "affected": affected,
                        "message": f"Executed. {affected} row(s) affected."})

    def _preview_write_count(sql):
        """Count rows a write would affect without committing.

        Converts UPDATE/DELETE to a SELECT COUNT(*) over the same table and
        WHERE clause. Falls back to executing inside a rolled-back
        transaction when the shape is not recognized.
        """
        kw = _first_keyword(sql)
        m = None
        if kw == "delete":
            m = re.match(r"\s*delete\s+from\s+([^\s;]+)(.*)$", sql, re.I | re.S)
        elif kw == "update":
            m = re.match(r"\s*update\s+([^\s;]+)\s+set\b.*?(\swhere\b.*)?$", sql, re.I | re.S)
        if m:
            table = m.group(1)
            where = ""
            if kw == "delete":
                where = m.group(2) or ""
            else:
                where = m.group(2) or ""
            where = where.strip().rstrip(";")
            try:
                cnt = db.session.execute(
                    text(f"SELECT COUNT(*) FROM {table} {where}")).scalar()
                return int(cnt or 0)
            except Exception:
                db.session.rollback()
        # Fallback: run then roll back, report rowcount.
        try:
            res = db.session.execute(text(sql))
            n = res.rowcount
            db.session.rollback()
            return int(n if n is not None and n >= 0 else 0)
        except Exception:
            db.session.rollback()
            return 0

    # ══ Table Browser + Row Editor ═════════════════════════════════════════════

    def _tables():
        insp = sa_inspect(db.engine)
        return sorted(t for t in insp.get_table_names() if not t.startswith("sqlite_"))

    def _table_meta(table):
        insp = sa_inspect(db.engine)
        cols = insp.get_columns(table)
        pk = insp.get_pk_constraint(table).get("constrained_columns") or []
        fks = {}
        for fk in insp.get_foreign_keys(table):
            for local in fk.get("constrained_columns", []):
                fks[local] = {"table": fk.get("referred_table"),
                              "column": (fk.get("referred_columns") or ["id"])[0]}
        return cols, pk, fks

    @app.route("/admin/api/db/tables")
    @admin_required("admin")
    def admin_api_db_tables():
        out = []
        for t in _tables():
            try:
                n = db.session.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
            except Exception:
                n = None
            out.append({"table": t, "rows": n,
                        "append_only": t == _AUDIT_TABLE})
        return jsonify({"ok": True, "tables": out})

    @app.route("/admin/api/db/table/<table>")
    @admin_required("admin")
    def admin_api_db_table(table):
        if table not in _tables():
            return jsonify({"ok": False, "error": "Unknown table"}), 404
        cols, pk, fks = _table_meta(table)
        page = max(int(request.args.get("page", 1)), 1)
        per = min(int(request.args.get("per", 25)), 100)
        total = db.session.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar() or 0
        order = f"ORDER BY {pk[0]} DESC" if pk else ""
        result = db.session.execute(
            text(f"SELECT * FROM {table} {order} LIMIT :lim OFFSET :off"),
            {"lim": per, "off": (page - 1) * per})
        keys = list(result.keys())
        rows = [{k: _jsonable(v) for k, v in zip(keys, r)} for r in result.fetchall()]
        return jsonify({"ok": True, "table": table, "columns": [c["name"] for c in cols],
                        "col_types": {c["name"]: str(c["type"]) for c in cols},
                        "pk": pk, "fks": fks, "append_only": table == _AUDIT_TABLE,
                        "rows": rows, "total": total, "page": page, "per": per})

    @app.route("/admin/api/db/table/<table>/row", methods=["POST"])
    @admin_required("admin")
    def admin_api_db_row_upsert(table):
        if table not in _tables():
            return jsonify({"ok": False, "error": "Unknown table"}), 404
        if table == _AUDIT_TABLE:
            # Guard 1: never editable, inserts only through _audit().
            return jsonify({"ok": False,
                            "error": "admin_audit_log is append-only and not editable here."}), 403
        data = request.get_json() or {}
        mode = data.get("mode", "update")     # 'insert' | 'update'
        values = data.get("values", {}) or {}
        cols, pk, _ = _table_meta(table)
        colnames = {c["name"] for c in cols}
        values = {k: v for k, v in values.items() if k in colnames}
        try:
            if mode == "insert":
                keys = [k for k in values if not (pk and k in pk and values[k] in (None, ""))]
                collist = ", ".join(keys)
                params = ", ".join(f":{k}" for k in keys)
                db.session.execute(text(f"INSERT INTO {table} ({collist}) VALUES ({params})"),
                                   {k: values[k] for k in keys})
                db.session.commit()
                _audit("db.insert", table, None, f"{table}: {list(values.keys())}")
                return jsonify({"ok": True, "message": "Row inserted."})
            # update
            if not pk:
                return jsonify({"ok": False, "error": "Table has no primary key; cannot update safely."}), 400
            pk_vals = data.get("pk") or {}
            setclause = ", ".join(f"{k} = :{k}" for k in values if k not in pk)
            if not setclause:
                return jsonify({"ok": False, "error": "No editable fields changed."}), 400
            whereclause = " AND ".join(f"{k} = :pk_{k}" for k in pk)
            params = {k: values[k] for k in values if k not in pk}
            params.update({f"pk_{k}": pk_vals.get(k) for k in pk})
            res = db.session.execute(
                text(f"UPDATE {table} SET {setclause} WHERE {whereclause}"), params)
            db.session.commit()
            _audit("db.update", table, str(list(pk_vals.values())),
                   f"{table}: set {list(params.keys())}")
            return jsonify({"ok": True, "affected": res.rowcount, "message": "Row updated."})
        except Exception as e:
            db.session.rollback()
            return jsonify({"ok": False, "error": str(e)[:400]}), 400

    @app.route("/admin/api/db/table/<table>/row/delete", methods=["POST"])
    @admin_required("admin")
    def admin_api_db_row_delete(table):
        if table not in _tables():
            return jsonify({"ok": False, "error": "Unknown table"}), 404
        if table == _AUDIT_TABLE:
            return jsonify({"ok": False,
                            "error": "admin_audit_log is append-only; rows cannot be deleted."}), 403
        cols, pk, _ = _table_meta(table)
        if not pk:
            return jsonify({"ok": False, "error": "Table has no primary key; refusing delete."}), 400
        pk_vals = (request.get_json() or {}).get("pk") or {}
        whereclause = " AND ".join(f"{k} = :{k}" for k in pk)
        try:
            res = db.session.execute(text(f"DELETE FROM {table} WHERE {whereclause}"),
                                     {k: pk_vals.get(k) for k in pk})
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return jsonify({"ok": False, "error": str(e)[:400]}), 400
        _audit("db.delete", table, str(list(pk_vals.values())), f"{table} row deleted")
        return jsonify({"ok": True, "affected": res.rowcount, "message": "Row deleted."})

    # ══ User field override ════════════════════════════════════════════════════

    _USER_EDITABLE = {
        "email": str, "username": str, "role": str, "status": str,
        "plan": str, "email_verified": bool, "alerts_enabled": bool,
        "pro_expires_at": "date", "predictions_today": int,
    }

    @app.route("/admin/api/users/<int:user_id>/override", methods=["POST"])
    @admin_required("admin")
    def admin_api_user_override(user_id):
        u = db.session.get(User, user_id)
        if not u:
            return jsonify({"ok": False, "error": "User not found"}), 404
        data = request.get_json() or {}
        fields = data.get("fields", {}) or {}
        changed = []
        for key, val in fields.items():
            if key not in _USER_EDITABLE:
                continue
            typ = _USER_EDITABLE[key]
            old = getattr(u, key, None)
            try:
                if typ is bool:
                    val = str(val).lower() in ("1", "true", "yes", "on")
                elif typ is int:
                    val = int(val)
                elif typ == "date":
                    val = datetime.fromisoformat(val).date() if val else None
                else:
                    val = str(val)
            except (ValueError, TypeError):
                return jsonify({"ok": False, "error": f"Bad value for {key}"}), 400
            if key == "role" and val not in ROLE_LEVELS:
                return jsonify({"ok": False, "error": "Invalid role"}), 400
            setattr(u, key, val)
            changed.append(f"{key}: {old} -> {val}")
        if not changed:
            return jsonify({"ok": False, "error": "No editable fields provided"}), 400
        db.session.commit()
        _audit("user.override", "user", u.id, "; ".join(changed)[:400])
        return jsonify({"ok": True, "changed": changed})

    @app.route("/admin/api/users/<int:user_id>/pro", methods=["POST"])
    @admin_required("admin")
    def admin_api_user_pro(user_id):
        u = db.session.get(User, user_id)
        if not u:
            return jsonify({"ok": False, "error": "User not found"}), 404
        data = request.get_json() or {}
        grant = bool(data.get("grant"))
        days = int(data.get("days", 30))
        if grant:
            base = date.today()
            if u.pro_expires_at and u.pro_expires_at > base:
                base = u.pro_expires_at
            u.pro_expires_at = base + timedelta(days=days)
            u.plan = "pro"
            _audit("user.pro_grant", "user", u.id, f"+{days}d -> {u.pro_expires_at}")
        else:
            u.pro_expires_at = None
            u.plan = "free"
            _audit("user.pro_revoke", "user", u.id, "Pro revoked")
        db.session.commit()
        return jsonify({"ok": True, "plan": u.plan,
                        "pro_expires_at": u.pro_expires_at.isoformat() if u.pro_expires_at else None})

    @app.route("/admin/api/users/<int:user_id>/reset-paper", methods=["POST"])
    @admin_required("admin")
    def admin_api_user_reset_paper(user_id):
        u = db.session.get(User, user_id)
        if not u:
            return jsonify({"ok": False, "error": "User not found"}), 404
        # Paper trades are shared-engine, virtual-money records; a user
        # reset clears this user's paper rows. Guard-safe: no live money.
        n = 0
        try:
            from models import PaperTrade, PaperTradeEvent, PaperEquitySnapshot
            for model in (PaperTradeEvent, PaperEquitySnapshot, PaperTrade):
                if hasattr(model, "user_id"):
                    n += model.query.filter_by(user_id=u.id).delete()
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return jsonify({"ok": False, "error": str(e)[:200]}), 400
        _audit("user.reset_paper", "user", u.id, f"cleared {n} paper rows")
        return jsonify({"ok": True, "cleared": n})

    @app.route("/admin/api/users/<int:user_id>/force-logout", methods=["POST"])
    @admin_required("admin")
    def admin_api_user_force_logout(user_id):
        u = db.session.get(User, user_id)
        if not u:
            return jsonify({"ok": False, "error": "User not found"}), 404
        # Rotating the session token invalidates every existing session
        # (the user loader checks it, see models.User.get_id).
        u.session_token = secrets.token_hex(16)
        db.session.commit()
        _audit("user.force_logout", "user", u.id, "sessions revoked")
        return jsonify({"ok": True})

    @app.route("/admin/api/users/<int:user_id>/sessions")
    @admin_required("support")
    def admin_api_user_sessions(user_id):
        u = db.session.get(User, user_id)
        if not u:
            return jsonify({"ok": False, "error": "User not found"}), 404
        logins = (ActivityLog.query.filter_by(user_id=u.id)
                  .filter(ActivityLog.action.in_(["login", "login.google"]))
                  .order_by(ActivityLog.id.desc()).limit(20).all())
        return jsonify({"ok": True,
                        "note": "This app keeps one rotating session token per "
                                "user, not per-device session records, so this "
                                "is login history (time, IP, device), not a "
                                "list of currently active sessions. Force "
                                "logout invalidates every active session at "
                                "once by rotating that token.",
                        "logins": [{"action": a.action, "ip": a.ip, "ua": a.ua,
                                   "at": a.created_at.isoformat()} for a in logins]})

    # ══ Impersonation (read-only) ══════════════════════════════════════════════

    @app.route("/admin/api/users/<int:user_id>/impersonate", methods=["POST"])
    @admin_required("admin")
    def admin_api_impersonate(user_id):
        u = db.session.get(User, user_id)
        if not u:
            return jsonify({"ok": False, "error": "User not found"}), 404
        if u.role_level >= ROLE_LEVELS["admin"]:
            return jsonify({"ok": False, "error": "Refusing to impersonate another admin"}), 403
        session["impersonator_id"] = current_user.id
        session["impersonate_readonly"] = True
        _audit("user.impersonate_start", "user", u.id, f"as {u.username}")
        login_user(u)
        return jsonify({"ok": True, "redirect": "/"})

    @app.route("/admin/impersonate/stop")
    def admin_impersonate_stop():
        # Not every visitor of this route is impersonating (the impersonated
        # identity itself is usually a plain "user" role, so this cannot be
        # gated by admin_required without breaking the real flow). Anyone who
        # is not actually mid-impersonation is treated like any other
        # unauthorized /admin route hit.
        imp = session.get("impersonator_id")
        if not imp:
            return redirect(url_for("admin_login"))
        session.pop("impersonator_id", None)
        session.pop("impersonate_readonly", None)
        admin_user = db.session.get(User, imp)
        if admin_user:
            login_user(admin_user)
            _audit("user.impersonate_stop", "user", None, "returned to admin")
            return redirect(url_for("admin_dashboard"))
        return redirect(url_for("home"))

    # ══ Job Runner ═════════════════════════════════════════════════════════════

    from routes.admin_jobs import JOB_REGISTRY, run_job, job_status

    @app.route("/admin/api/jobs")
    @admin_required("admin")
    def admin_api_jobs():
        return jsonify({"ok": True, "jobs": [
            {"key": k, "label": v["label"], "desc": v["desc"]}
            for k, v in JOB_REGISTRY.items()]})

    @app.route("/admin/api/jobs/<job>/run", methods=["POST"])
    @admin_required("admin")
    def admin_api_job_run(job):
        if job not in JOB_REGISTRY:
            return jsonify({"ok": False, "error": "Unknown job"}), 404
        started = run_job(app, job)
        if not started:
            return jsonify({"ok": False, "error": "Job already running"}), 409
        _audit("job.run", "job", job, JOB_REGISTRY[job]["label"])
        return jsonify({"ok": True, "message": f"Started {JOB_REGISTRY[job]['label']}"})

    @app.route("/admin/api/jobs/status")
    @admin_required("admin")
    def admin_api_jobs_status():
        return jsonify({"ok": True, "status": job_status()})

    # ══ Feature Flags ══════════════════════════════════════════════════════════

    @app.route("/admin/api/flags")
    @admin_required("admin")
    def admin_api_flags():
        flags = [{"key": k, "label": lbl, "value": _get_setting(k, dflt)}
                 for (k, lbl, dflt) in FEATURE_FLAGS]
        # Active model per asset: stored as model_<TICKER> keys.
        model_rows = (db.session.query(AppSetting)
                      .filter(AppSetting.key.like("model_%")).all())
        models = [{"key": r.key, "ticker": r.key[len("model_"):], "value": r.value}
                  for r in model_rows]
        return jsonify({"ok": True, "flags": flags, "models": models,
                        "live_trading": _live_trading_state()})

    @app.route("/admin/api/flags", methods=["POST"])
    @admin_required("admin")
    def admin_api_flags_save():
        data = request.get_json() or {}
        key = data.get("key", "")
        value = data.get("value", "")
        valid = {k for (k, _, _) in FEATURE_FLAGS}
        if key not in valid and not key.startswith("model_"):
            return jsonify({"ok": False, "error": "Unknown flag"}), 400
        _set_setting(key, value)
        db.session.commit()
        try:
            from app import invalidate_settings_cache
            invalidate_settings_cache()
        except Exception:
            pass
        _audit("flag.set", "flag", key, f"{key} = {value}")
        return jsonify({"ok": True})

    # ══ Promo Codes ════════════════════════════════════════════════════════════

    @app.route("/admin/api/promos")
    @admin_required("admin")
    def admin_api_promos():
        rows = GiftCode.query.order_by(GiftCode.created_at.desc()).limit(500).all()
        users = {u.id: u.username for u in User.query.filter(
            User.id.in_({r.used_by for r in rows if r.used_by})).all()}
        return jsonify({"ok": True, "codes": [
            {"code": r.code, "days": r.days, "used": r.used,
             "used_by": users.get(r.used_by), "note": r.note,
             "created_at": r.created_at.isoformat() if r.created_at else None,
             "used_at": r.used_at.isoformat() if r.used_at else None}
            for r in rows]})

    @app.route("/admin/api/promos", methods=["POST"])
    @admin_required("admin")
    def admin_api_promo_create():
        data = request.get_json() or {}
        days = int(data.get("days", 30))
        count = min(int(data.get("count", 1)), 100)
        note = (data.get("note") or "")[:100]
        created = []
        for _ in range(count):
            code = "BULL-" + secrets.token_hex(4).upper()
            db.session.add(GiftCode(code=code, days=days, note=note))
            created.append(code)
        db.session.commit()
        _audit("promo.create", "promo", None, f"{count} codes x {days}d")
        return jsonify({"ok": True, "codes": created})

    # ══ Predictions: annotate / regrade (Guard 3) ══════════════════════════════

    @app.route("/admin/api/predictions/<int:pid>/regrade", methods=["POST"])
    @admin_required("admin")
    def admin_api_prediction_regrade(pid):
        ph = db.session.get(PredictionHistory, pid)
        if not ph:
            return jsonify({"ok": False, "error": "Prediction not found"}), 404
        data = request.get_json() or {}
        reason = (data.get("reason") or "").strip()
        # Guard 3: never a silent overwrite.
        if not reason:
            return jsonify({"ok": False,
                            "error": "A reason is required to edit a graded prediction."}), 400
        acc = PredictionAccuracy.query.filter_by(prediction_id=pid).first()
        if not acc:
            return jsonify({"ok": False, "error": "This prediction has not been graded yet."}), 400
        changed = []
        if "direction_ok" in data:
            old = acc.direction_ok
            acc.direction_ok = bool(data["direction_ok"])
            changed.append(f"direction_ok: {old} -> {acc.direction_ok}")
        if not changed:
            return jsonify({"ok": False, "error": "No graded field changed"}), 400
        db.session.commit()
        _audit("prediction.regrade", "prediction", pid,
               f"{'; '.join(changed)} | reason: {reason}"[:400])
        return jsonify({"ok": True, "changed": changed})

    @app.route("/admin/api/predictions/<int:pid>/flag", methods=["POST"])
    @admin_required("support")
    def admin_api_prediction_flag(pid):
        ph = db.session.get(PredictionHistory, pid)
        if not ph:
            return jsonify({"ok": False, "error": "Prediction not found"}), 404
        note = (request.get_json() or {}).get("note", "")[:200]
        _audit("prediction.flag", "prediction", pid, note or "flagged")
        return jsonify({"ok": True})

    # ══ Paper trading: force-close (logged reason) ═════════════════════════════

    @app.route("/admin/api/paper/positions")
    @admin_required("support")
    def admin_api_paper_positions():
        try:
            from models import PaperTrade
            status = request.args.get("status", "all")
            q = PaperTrade.query
            if status in ("open", "closed") and hasattr(PaperTrade, "status"):
                q = q.filter_by(status=status)
            rows = q.order_by(PaperTrade.id.desc()).limit(300).all()
            return jsonify({"ok": True, "positions": [_paper_row(r) for r in rows],
                           "status_filter": status})
        except Exception as e:
            return jsonify({"ok": True, "positions": [], "note": str(e)[:120]})

    @app.route("/admin/api/paper/<int:tid>/force-close", methods=["POST"])
    @admin_required("admin")
    def admin_api_paper_force_close(tid):
        reason = (request.get_json() or {}).get("reason", "").strip()
        if not reason:
            return jsonify({"ok": False, "error": "A reason is required to force-close."}), 400
        try:
            from models import PaperTrade
            t = db.session.get(PaperTrade, tid)
            if not t:
                return jsonify({"ok": False, "error": "Trade not found"}), 404
            if hasattr(t, "status"):
                t.status = "closed"
            if hasattr(t, "close_reason"):
                t.close_reason = f"admin force-close: {reason}"[:120]
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return jsonify({"ok": False, "error": str(e)[:200]}), 400
        _audit("paper.force_close", "paper_trade", tid, f"reason: {reason}")
        return jsonify({"ok": True})

    # ══ Payments: reconcile ════════════════════════════════════════════════════

    @app.route("/admin/api/payments/<int:pid>/reconcile", methods=["POST"])
    @admin_required("admin")
    def admin_api_payment_reconcile(pid):
        p = db.session.get(Payment, pid)
        if not p:
            return jsonify({"ok": False, "error": "Payment not found"}), 404
        data = request.get_json() or {}
        target_uid = data.get("user_id")
        note = (data.get("note") or "")[:200]
        u = db.session.get(User, int(target_uid)) if target_uid else None
        if not u:
            return jsonify({"ok": False, "error": "Target user not found"}), 400
        old = p.user_id
        p.user_id = u.id
        db.session.commit()
        _audit("payment.reconcile", "payment", pid,
               f"user {old} -> {u.id} ({u.username}); {note}")
        return jsonify({"ok": True})

    # ══ Security page data ═════════════════════════════════════════════════════

    @app.route("/admin/api/security")
    @admin_required("admin")
    def admin_api_security():
        # Failed logins from the audit log, plus in-memory IP lockouts.
        fails = (AdminAuditLog.query
                 .filter(AdminAuditLog.action.in_(["login.failed", "login.google.denied"]))
                 .order_by(AdminAuditLog.id.desc()).limit(100).all())
        from routes.admin import _login_attempts, _LOGIN_MAX_FAILS, _LOGIN_WINDOW_S
        import time as _t
        now = _t.time()
        lockouts = []
        for ip, ts in _login_attempts.items():
            recent = [t for t in ts if now - t < _LOGIN_WINDOW_S]
            if recent:
                lockouts.append({"ip": ip, "fails": len(recent),
                                 "locked": len(recent) >= _LOGIN_MAX_FAILS,
                                 "last": datetime.fromtimestamp(max(recent)).isoformat()})
        return jsonify({"ok": True,
                        "failed_logins": [
                            {"admin_id": r.admin_id, "action": r.action,
                             "ip": r.ip, "detail": r.detail,
                             "at": r.created_at.isoformat()} for r in fails],
                        "lockouts": sorted(lockouts, key=lambda x: -x["fails"]),
                        "live_trading": _live_trading_state()})

    # ── helpers local to registration ──
    def _paper_row(r):
        out = {"id": r.id}
        for attr in ("user_id", "ticker", "symbol", "side", "action", "status",
                     "entry_price", "qty", "quantity", "opened_at", "source"):
            if hasattr(r, attr):
                out[attr] = _jsonable(getattr(r, attr))
        return out


def _live_trading_state():
    """Guard 2: report the env-controlled flag; never writable in-panel."""
    raw = os.environ.get("ENABLE_LIVE_TRADING", "")
    return {"enabled": raw.strip().lower() in ("1", "true", "yes", "on"),
            "raw": raw or "(unset)", "read_only": True,
            "note": "Controlled by the ENABLE_LIVE_TRADING environment "
                    "variable only. It cannot be changed from this panel."}


def _jsonable(v):
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, bytes):
        return v.decode("utf-8", "replace")
    return v
