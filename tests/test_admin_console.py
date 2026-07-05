"""Admin console guarantees: access control, append-only audit log,
and (as later stages land) the power tools and capability groups.

Stage 1 scope:
  - every /admin route refuses anonymous and non-staff users
  - admin_audit_log rows cannot be updated or deleted through the ORM,
    neither per instance nor in bulk
  - admin actions write audit rows
"""

import os
from datetime import datetime

import pytest

from conftest import login, admin_login


# ── Access control: every admin route is closed to non-staff ─────────────────

PUBLIC_ADMIN_ENDPOINTS = {"admin_login", "admin_logout"}


def _admin_rules(app):
    """All /admin URL rules that must be protected, with a GET-able path."""
    rules = []
    for rule in app.url_map.iter_rules():
        if not rule.rule.startswith("/admin"):
            continue
        if rule.endpoint in PUBLIC_ADMIN_ENDPOINTS:
            continue
        path = rule.rule
        for arg in rule.arguments:
            path = path.replace(f"<int:{arg}>", "1").replace(f"<{arg}>", "x")
        methods = rule.methods - {"HEAD", "OPTIONS"}
        rules.append((path, "GET" if "GET" in methods else sorted(methods)[0]))
    assert rules, "no admin routes found: registration is broken"
    return rules


class TestAdminAccessControl:

    def test_anonymous_blocked_on_every_admin_route(self, app, client):
        for path, method in _admin_rules(app):
            resp = client.open(path, method=method)
            assert resp.status_code in (302, 401, 403), (path, resp.status_code)
            if resp.status_code == 302:
                assert "/admin/login" in resp.headers.get("Location", ""), path

    def test_plain_user_blocked_on_every_admin_route(self, app, client, make_user):
        make_user("plainjoe")
        login(client, "plainjoe")
        for path, method in _admin_rules(app):
            resp = client.open(path, method=method)
            assert resp.status_code in (302, 401, 403), (path, resp.status_code)
            if resp.status_code == 302:
                assert "/admin/login" in resp.headers.get("Location", ""), path


# ── Append-only audit log ─────────────────────────────────────────────────────

class TestAuditAppendOnly:

    def _make_row(self, app, db, admin_id):
        from models import AdminAuditLog
        with app.app_context():
            row = AdminAuditLog(admin_id=admin_id, action="test.probe")
            db.session.add(row)
            db.session.commit()
            return row.id

    def test_update_refused(self, app, db, make_user):
        from models import AdminAuditLog, AuditLogImmutableError
        uid = make_user("audadm1", role="admin")
        rid = self._make_row(app, db, uid)
        with app.app_context():
            row = db.session.get(AdminAuditLog, rid)
            row.action = "test.tampered"
            with pytest.raises(AuditLogImmutableError):
                db.session.commit()
            db.session.rollback()
            assert db.session.get(AdminAuditLog, rid).action == "test.probe"

    def test_instance_delete_refused(self, app, db, make_user):
        from models import AdminAuditLog, AuditLogImmutableError
        uid = make_user("audadm2", role="admin")
        rid = self._make_row(app, db, uid)
        with app.app_context():
            db.session.delete(db.session.get(AdminAuditLog, rid))
            with pytest.raises(AuditLogImmutableError):
                db.session.commit()
            db.session.rollback()
            assert db.session.get(AdminAuditLog, rid) is not None

    def test_bulk_delete_refused(self, app, db, make_user):
        from models import AdminAuditLog, AuditLogImmutableError
        uid = make_user("audadm3", role="admin")
        self._make_row(app, db, uid)
        with app.app_context():
            with pytest.raises(AuditLogImmutableError):
                AdminAuditLog.query.filter_by(action="test.probe").delete()
            db.session.rollback()

    def test_bulk_update_refused(self, app, db, make_user):
        from models import AdminAuditLog, AuditLogImmutableError
        uid = make_user("audadm4", role="admin")
        self._make_row(app, db, uid)
        with app.app_context():
            with pytest.raises(AuditLogImmutableError):
                AdminAuditLog.query.filter_by(action="test.probe").update(
                    {"action": "test.tampered"})
            db.session.rollback()


# ── Audit rows written on admin actions ───────────────────────────────────────

class TestAuditWrites:

    def test_admin_login_and_user_action_are_audited(self, app, db, client, make_user):
        from models import AdminAuditLog
        make_user("auditboss", role="admin")
        target = make_user("audittarget")
        admin_login(client, "auditboss")
        with app.app_context():
            assert AdminAuditLog.query.filter_by(action="login").count() >= 1

        csrf = _csrf(client)
        r = client.post(f"/admin/api/users/{target}/action",
                        json={"action": "ban", "reason": "spam"},
                        headers={"X-CSRF-Token": csrf})
        assert r.status_code == 200 and r.get_json()["ok"] is True
        with app.app_context():
            row = (AdminAuditLog.query.filter_by(action="user.ban")
                   .order_by(AdminAuditLog.id.desc()).first())
            assert row is not None
            assert str(row.target_id) == str(target)
            assert "spam" in (row.detail or "")


def _csrf(client):
    with client.session_transaction() as s:
        return s.get("csrf_token", "")


# ── Ban with reason ────────────────────────────────────────────────────────────

class TestBanReason:

    def test_ban_without_reason_refused(self, app, db, client, make_user):
        make_user("banadmin1", role="admin")
        target = make_user("bantarget1")
        admin_login(client, "banadmin1")
        csrf = _csrf(client)
        r = client.post(f"/admin/api/users/{target}/action",
                        json={"action": "ban"}, headers={"X-CSRF-Token": csrf})
        assert r.status_code == 400
        with app.app_context():
            from models import User
            assert db.session.get(User, target).status != "banned"

    def test_ban_with_reason_persists_and_unban_clears_it(self, app, db, client, make_user):
        make_user("banadmin2", role="admin")
        target = make_user("bantarget2")
        admin_login(client, "banadmin2")
        csrf = _csrf(client)
        r = client.post(f"/admin/api/users/{target}/action",
                        json={"action": "ban", "reason": "abusive behavior"},
                        headers={"X-CSRF-Token": csrf})
        assert r.status_code == 200
        with app.app_context():
            from models import User
            u = db.session.get(User, target)
            assert u.status == "banned"
            assert u.ban_reason == "abusive behavior"

        r = client.post(f"/admin/api/users/{target}/action",
                        json={"action": "unban"}, headers={"X-CSRF-Token": csrf})
        assert r.status_code == 200
        with app.app_context():
            from models import User
            u = db.session.get(User, target)
            assert u.status == "active"
            assert u.ban_reason is None


# ── Resend verification ────────────────────────────────────────────────────────

class TestResendVerification:

    def test_resend_verification_for_unverified_user(self, app, db, client, make_user):
        make_user("verifyadmin", role="admin")
        target = make_user("unverifiedguy")
        with app.app_context():
            from models import User
            u = db.session.get(User, target)
            u.email_verified = False
            db.session.commit()
        admin_login(client, "verifyadmin")
        csrf = _csrf(client)
        r = client.post(f"/admin/api/users/{target}/resend-verification",
                        headers={"X-CSRF-Token": csrf})
        assert r.status_code in (200, 502)   # 502 if no mailer configured in this env

    def test_resend_verification_refused_when_already_verified(self, app, db, client, make_user):
        make_user("verifyadmin2", role="admin")
        target = make_user("verifiedguy")
        with app.app_context():
            from models import User
            u = db.session.get(User, target)
            u.email_verified = True
            db.session.commit()
        admin_login(client, "verifyadmin2")
        csrf = _csrf(client)
        r = client.post(f"/admin/api/users/{target}/resend-verification",
                        headers={"X-CSRF-Token": csrf})
        assert r.status_code == 400


# ── Login history / sessions ───────────────────────────────────────────────────

class TestSessions:

    def test_regular_login_is_recorded_and_visible_to_admin(self, app, db, client, make_user):
        make_user("sessadmin", role="admin")
        target = make_user("sessuser")
        login(client, "sessuser")
        client.get("/logout")
        admin_login(client, "sessadmin")
        r = client.get(f"/admin/api/users/{target}/sessions")
        data = r.get_json()
        assert r.status_code == 200 and data["ok"] is True
        assert any(entry["action"] == "login" for entry in data["logins"])
        assert "note" in data


# ── Force logout ────────────────────────────────────────────────────────────────

class TestForceLogout:

    def test_force_logout_rotates_session_token(self, app, db, client, make_user):
        make_user("logoutadmin", role="admin")
        target = make_user("logouttarget")
        with app.app_context():
            from models import User
            before = db.session.get(User, target).session_token
        admin_login(client, "logoutadmin")
        csrf = _csrf(client)
        r = client.post(f"/admin/api/users/{target}/force-logout",
                        headers={"X-CSRF-Token": csrf})
        assert r.status_code == 200
        with app.app_context():
            from models import User
            after = db.session.get(User, target).session_token
        assert after != before and after


# ── Reset paper account ──────────────────────────────────────────────────────────

class TestResetPaper:

    def test_reset_paper_returns_cleared_count(self, client, make_user):
        make_user("paperadmin1", role="admin")
        target = make_user("paperresetuser")
        admin_login(client, "paperadmin1")
        csrf = _csrf(client)
        r = client.post(f"/admin/api/users/{target}/reset-paper",
                        headers={"X-CSRF-Token": csrf})
        assert r.status_code == 200
        assert isinstance(r.get_json()["cleared"], int)


# ── SQL console ──────────────────────────────────────────────────────────────────

class TestSqlConsole:

    def test_support_role_blocked_from_sql_console(self, client, make_user):
        make_user("sqlsupport", role="support")
        admin_login(client, "sqlsupport")
        csrf = _csrf(client)
        r = client.post("/admin/api/sql/run", json={"sql": "SELECT 1"},
                        headers={"X-CSRF-Token": csrf})
        assert r.status_code == 403

    def test_select_runs_freely(self, client, make_user):
        make_user("sqladmin1", role="admin")
        admin_login(client, "sqladmin1")
        csrf = _csrf(client)
        r = client.post("/admin/api/sql/run", json={"sql": "SELECT 1"},
                        headers={"X-CSRF-Token": csrf})
        data = r.get_json()
        assert r.status_code == 200 and data["mode"] == "read"

    def test_write_requires_confirm_then_executes(self, app, db, client, make_user):
        make_user("sqladmin2", role="admin")
        target = make_user("sqlwritetarget", email="sqlwritetarget@test.local")
        admin_login(client, "sqladmin2")
        csrf = _csrf(client)
        sql = f"UPDATE user SET plan = 'pro' WHERE id = {target}"
        preview = client.post("/admin/api/sql/run", json={"sql": sql},
                              headers={"X-CSRF-Token": csrf})
        assert preview.status_code == 200
        assert preview.get_json()["mode"] == "preview"
        confirmed = client.post("/admin/api/sql/run", json={"sql": sql, "confirm": True},
                                headers={"X-CSRF-Token": csrf})
        assert confirmed.status_code == 200
        assert confirmed.get_json()["mode"] == "write"
        with app.app_context():
            from models import User
            assert db.session.get(User, target).plan == "pro"

    def test_admin_audit_log_only_accepts_select_in_console(self, client, make_user):
        make_user("sqladmin3", role="admin")
        admin_login(client, "sqladmin3")
        csrf = _csrf(client)
        r = client.post("/admin/api/sql/run",
                        json={"sql": "DELETE FROM admin_audit_log", "confirm": True},
                        headers={"X-CSRF-Token": csrf})
        assert r.status_code == 403


# ── Table browser / row editor ──────────────────────────────────────────────────

class TestTableBrowser:

    def test_tables_listed_and_audit_log_marked_append_only(self, client, make_user):
        make_user("dbadmin1", role="admin")
        admin_login(client, "dbadmin1")
        r = client.get("/admin/api/db/tables")
        data = r.get_json()
        assert r.status_code == 200
        names = {t["table"]: t for t in data["tables"]}
        assert "user" in names
        assert names["admin_audit_log"]["append_only"] is True

    def test_row_update_and_delete(self, app, db, client, make_user):
        make_user("dbadmin2", role="admin")
        target = make_user("dbrowtarget")
        admin_login(client, "dbadmin2")
        csrf = _csrf(client)
        r = client.post(f"/admin/api/db/table/user/row",
                        json={"mode": "update", "pk": {"id": target},
                              "values": {"plan": "pro"}},
                        headers={"X-CSRF-Token": csrf})
        assert r.status_code == 200
        with app.app_context():
            from models import User
            assert db.session.get(User, target).plan == "pro"

    def test_append_only_table_refuses_row_write(self, client, make_user):
        make_user("dbadmin3", role="admin")
        admin_login(client, "dbadmin3")
        csrf = _csrf(client)
        r = client.post("/admin/api/db/table/admin_audit_log/row",
                        json={"mode": "insert", "values": {"action": "x"}},
                        headers={"X-CSRF-Token": csrf})
        assert r.status_code == 403


# ── User field override ─────────────────────────────────────────────────────────

class TestUserOverride:

    def test_override_email_and_plan(self, app, db, client, make_user):
        make_user("ovadmin", role="admin")
        target = make_user("overridetarget")
        admin_login(client, "ovadmin")
        csrf = _csrf(client)
        r = client.post(f"/admin/api/users/{target}/override",
                        json={"fields": {"plan": "pro", "email_verified": "true"}},
                        headers={"X-CSRF-Token": csrf})
        assert r.status_code == 200
        with app.app_context():
            from models import User
            u = db.session.get(User, target)
            assert u.plan == "pro" and u.email_verified is True


# ── Job runner ───────────────────────────────────────────────────────────────────

class TestJobRunner:

    def test_job_registry_lists_real_jobs(self, client, make_user):
        make_user("jobadmin1", role="admin")
        admin_login(client, "jobadmin1")
        r = client.get("/admin/api/jobs")
        keys = {j["key"] for j in r.get_json()["jobs"]}
        assert {"grade", "drift", "reconcile", "digest", "pyth_sync"} <= keys

    def test_run_job_is_audited(self, app, db, client, make_user):
        import time
        make_user("jobadmin2", role="admin")
        admin_login(client, "jobadmin2")
        csrf = _csrf(client)
        r = client.post("/admin/api/jobs/grade/run", headers={"X-CSRF-Token": csrf})
        assert r.status_code == 200
        for _ in range(50):
            st = client.get("/admin/api/jobs/status").get_json()["status"]["grade"]
            if not st["running"]:
                break
            time.sleep(0.1)
        with app.app_context():
            from models import AdminAuditLog
            assert AdminAuditLog.query.filter_by(action="job.run").count() >= 1


# ── Impersonation ────────────────────────────────────────────────────────────────

class TestImpersonation:

    def test_admin_can_impersonate_plain_user_read_only(self, client, make_user):
        make_user("impadmin", role="admin")
        target = make_user("imptarget")
        admin_login(client, "impadmin")
        csrf = _csrf(client)
        r = client.post(f"/admin/api/users/{target}/impersonate",
                        headers={"X-CSRF-Token": csrf})
        assert r.status_code == 200
        with client.session_transaction() as s:
            assert s.get("impersonator_id") is not None
            assert s.get("impersonate_readonly") is True

    def test_refuses_to_impersonate_another_admin(self, client, make_user):
        make_user("impadmin2", role="admin")
        other_admin = make_user("otheradmin", role="admin")
        admin_login(client, "impadmin2")
        csrf = _csrf(client)
        r = client.post(f"/admin/api/users/{other_admin}/impersonate",
                        headers={"X-CSRF-Token": csrf})
        assert r.status_code == 403


# ── Predictions: regrade (logged reason) and flag ───────────────────────────────

class TestPredictionRegradeAndFlag:

    def _make_prediction(self, app, db, user_id, graded=True):
        from models import PredictionHistory, PredictionAccuracy
        with app.app_context():
            ph = PredictionHistory(user_id=user_id, ticker="AAPL", interval="1d",
                                   current_price=100.0, lr_pred=101.0, rf_pred=102.0,
                                   direction="UP", confidence=70.0)
            db.session.add(ph)
            db.session.commit()
            pid = ph.id
            if graded:
                db.session.add(PredictionAccuracy(prediction_id=pid, direction_ok=True))
                db.session.commit()
            return pid

    def test_regrade_requires_reason(self, app, db, client, make_user):
        make_user("regradeadmin1", role="admin")
        target = make_user("regradeuser1")
        pid = self._make_prediction(app, db, target)
        admin_login(client, "regradeadmin1")
        csrf = _csrf(client)
        r = client.post(f"/admin/api/predictions/{pid}/regrade",
                        json={"direction_ok": False},
                        headers={"X-CSRF-Token": csrf})
        assert r.status_code == 400

    def test_regrade_with_reason_is_audited(self, app, db, client, make_user):
        from models import AdminAuditLog
        make_user("regradeadmin2", role="admin")
        target = make_user("regradeuser2")
        pid = self._make_prediction(app, db, target)
        admin_login(client, "regradeadmin2")
        csrf = _csrf(client)
        r = client.post(f"/admin/api/predictions/{pid}/regrade",
                        json={"direction_ok": False, "reason": "manual review found a data error"},
                        headers={"X-CSRF-Token": csrf})
        assert r.status_code == 200
        with app.app_context():
            row = (AdminAuditLog.query.filter_by(action="prediction.regrade")
                   .order_by(AdminAuditLog.id.desc()).first())
            assert row is not None
            assert "manual review found a data error" in row.detail

    def test_flag_prediction(self, app, db, client, make_user):
        make_user("flagsupport", role="support")
        target = make_user("flaguser")
        pid = self._make_prediction(app, db, target, graded=False)
        admin_login(client, "flagsupport")
        csrf = _csrf(client)
        r = client.post(f"/admin/api/predictions/{pid}/flag",
                        json={"note": "looks off"}, headers={"X-CSRF-Token": csrf})
        assert r.status_code == 200


# ── Paper trading: view all + force close ───────────────────────────────────────

class TestPaperTradingAdmin:

    def _make_trade(self, app, db, status="open"):
        from models import PaperTrade
        with app.app_context():
            t = PaperTrade(strategy="ml_ensemble", ticker="AAPL", asset_class="equity",
                           side="LONG", qty=1.0, entry_time=datetime.utcnow(),
                           entry_price=100.0, entry_mkt=100.0, stop_price=95.0,
                           target_price=110.0, max_hold_hours=24, status=status)
            db.session.add(t)
            db.session.commit()
            return t.id

    def test_view_all_includes_closed_by_default(self, app, db, client, make_user):
        make_user("paperviewadmin", role="admin")
        self._make_trade(app, db, status="closed")
        admin_login(client, "paperviewadmin")
        r = client.get("/admin/api/paper/positions")
        data = r.get_json()
        assert r.status_code == 200 and data["status_filter"] == "all"

    def test_force_close_requires_reason(self, app, db, client, make_user):
        make_user("paperforceadmin", role="admin")
        tid = self._make_trade(app, db, status="open")
        admin_login(client, "paperforceadmin")
        csrf = _csrf(client)
        r = client.post(f"/admin/api/paper/{tid}/force-close", json={},
                        headers={"X-CSRF-Token": csrf})
        assert r.status_code == 400

    def test_force_close_with_reason_is_audited(self, app, db, client, make_user):
        from models import AdminAuditLog, PaperTrade
        make_user("paperforceadmin2", role="admin")
        tid = self._make_trade(app, db, status="open")
        admin_login(client, "paperforceadmin2")
        csrf = _csrf(client)
        r = client.post(f"/admin/api/paper/{tid}/force-close",
                        json={"reason": "duplicate signal"},
                        headers={"X-CSRF-Token": csrf})
        assert r.status_code == 200
        with app.app_context():
            assert db.session.get(PaperTrade, tid).status == "closed"
            assert AdminAuditLog.query.filter_by(action="paper.force_close").count() >= 1


# ── Payments: refund notes + reconcile ──────────────────────────────────────────

class TestPaymentsRefundAndReconcile:

    def _make_payment(self, app, db, user_id, status="paid"):
        from models import Payment
        with app.app_context():
            p = Payment(user_id=user_id, provider="mpesa", plan="monthly",
                       amount=500.0, currency="KES", days=30, status=status)
            db.session.add(p)
            db.session.commit()
            return p.id

    def test_refund_persists_note(self, app, db, client, make_user):
        make_user("refundadmin", role="support")
        target = make_user("refunduser")
        pid = self._make_payment(app, db, target)
        admin_login(client, "refundadmin")
        csrf = _csrf(client)
        r = client.post(f"/admin/api/payments/{pid}/refund",
                        json={"note": "customer requested cancellation"},
                        headers={"X-CSRF-Token": csrf})
        assert r.status_code == 200
        with app.app_context():
            from models import Payment
            p = db.session.get(Payment, pid)
            assert p.status == "refunded"
            assert p.notes == "customer requested cancellation"

    def test_reconcile_moves_payment_to_target_user(self, app, db, client, make_user):
        make_user("reconcileadmin", role="admin")
        wrong_user = make_user("wronguser")
        right_user = make_user("rightuser")
        pid = self._make_payment(app, db, wrong_user)
        admin_login(client, "reconcileadmin")
        csrf = _csrf(client)
        r = client.post(f"/admin/api/payments/{pid}/reconcile",
                        json={"user_id": right_user, "note": "wrong account linked"},
                        headers={"X-CSRF-Token": csrf})
        assert r.status_code == 200
        with app.app_context():
            from models import Payment
            assert db.session.get(Payment, pid).user_id == right_user


# ── Promo codes ──────────────────────────────────────────────────────────────────

class TestPromoCodes:

    def test_create_and_list_codes(self, client, make_user):
        make_user("promoadmin", role="admin")
        admin_login(client, "promoadmin")
        csrf = _csrf(client)
        r = client.post("/admin/api/promos", json={"days": 14, "count": 2, "note": "launch promo"},
                        headers={"X-CSRF-Token": csrf})
        data = r.get_json()
        assert r.status_code == 200 and len(data["codes"]) == 2
        listing = client.get("/admin/api/promos").get_json()
        codes = {c["code"] for c in listing["codes"]}
        assert set(data["codes"]) <= codes


# ── Analytics ────────────────────────────────────────────────────────────────────

class TestAnalytics:

    def test_analytics_endpoint_returns_expected_shape(self, client, make_user):
        make_user("analyticsviewer", role="viewer")
        admin_login(client, "analyticsviewer")
        r = client.get("/admin/api/analytics")
        data = r.get_json()
        assert r.status_code == 200
        for key in ("dau", "mau", "top_tickers", "funnel", "retention"):
            assert key in data


# ── Feature flags ────────────────────────────────────────────────────────────────

class TestFeatureFlags:

    def test_toggle_flag_persists(self, client, make_user):
        make_user("flagadmin", role="admin")
        admin_login(client, "flagadmin")
        csrf = _csrf(client)
        r = client.post("/admin/api/flags", json={"key": "feature_sentiment", "value": "off"},
                        headers={"X-CSRF-Token": csrf})
        assert r.status_code == 200
        got = client.get("/admin/api/flags").get_json()
        row = next(f for f in got["flags"] if f["key"] == "feature_sentiment")
        assert row["value"] == "off"

    def test_live_trading_is_reported_read_only(self, client, make_user):
        make_user("flagviewer", role="admin")
        admin_login(client, "flagviewer")
        got = client.get("/admin/api/flags").get_json()
        assert got["live_trading"]["read_only"] is True


# ── Maintenance mode ─────────────────────────────────────────────────────────────

class TestMaintenanceMode:

    def test_maintenance_blocks_plain_users_but_not_admins(self, app, db, client, make_user):
        import app as app_module
        make_user("maintadmin", role="admin")
        plain = make_user("maintplain")
        with app.app_context():
            from models import AppSetting
            row = db.session.get(AppSetting, "maintenance_mode")
            if row:
                row.value = "1"
            else:
                db.session.add(AppSetting(key="maintenance_mode", value="1"))
            db.session.commit()
        app_module._settings_cache["checked_at"] = 0.0   # force a re-read past the 15s cache
        try:
            login(client, "maintplain")
            r = client.get("/")
            assert r.status_code == 503

            client.get("/logout")
            admin_login(client, "maintadmin")
            r = client.get("/admin")
            assert r.status_code == 200
        finally:
            with app.app_context():
                from models import AppSetting
                row = db.session.get(AppSetting, "maintenance_mode")
                if row:
                    row.value = "0"
                    db.session.commit()
            app_module._settings_cache["checked_at"] = 0.0


# ── System health ────────────────────────────────────────────────────────────────

class TestSystemHealth:

    def test_system_endpoint_lists_real_job_registry(self, client, make_user):
        make_user("sysadmin", role="viewer")
        admin_login(client, "sysadmin")
        r = client.get("/admin/api/system")
        data = r.get_json()
        assert r.status_code == 200
        names = {j["name"] for j in data["jobs"]}
        assert "Grade predictions" in names


# ── Security / audit filterable timeline ────────────────────────────────────────

class TestSecurityAndAuditTimeline:

    def test_security_endpoint_shape(self, client, make_user):
        make_user("secadmin", role="admin")
        admin_login(client, "secadmin")
        r = client.get("/admin/api/security")
        data = r.get_json()
        assert r.status_code == 200
        assert "failed_logins" in data and "lockouts" in data

    def test_audit_log_filterable_by_action_and_date(self, client, make_user):
        make_user("audittimeline", role="admin")
        admin_login(client, "audittimeline")
        r = client.get("/admin/api/audit?action=login&from=2020-01-01")
        data = r.get_json()
        assert r.status_code == 200
        assert all(e["action"] == "login" for e in data["entries"])


# ── Admin-only 2FA ───────────────────────────────────────────────────────────────

class TestAdminOnly2FA:

    def test_admin_with_2fa_enabled_cannot_login_without_code(self, app, db, client, make_user):
        import pyotp
        from models import TwoFactorAuth
        uid = make_user("tfaadmin1", role="admin")
        secret = pyotp.random_base32()
        with app.app_context():
            db.session.add(TwoFactorAuth(user_id=uid, secret=secret, enabled=True))
            db.session.commit()
        r = client.post("/admin/login", data={"identifier": "tfaadmin1", "password": "password123"})
        assert r.status_code == 200
        assert b"code" in r.data.lower()
        with client.session_transaction() as s:
            assert s.get("_user_id") is None

    def test_admin_with_2fa_enabled_completes_login_with_valid_code(self, app, db, client, make_user):
        import pyotp
        from models import TwoFactorAuth
        uid = make_user("tfaadmin2", role="admin")
        secret = pyotp.random_base32()
        with app.app_context():
            db.session.add(TwoFactorAuth(user_id=uid, secret=secret, enabled=True))
            db.session.commit()
        client.post("/admin/login", data={"identifier": "tfaadmin2", "password": "password123"})
        code = pyotp.TOTP(secret).now()
        r = client.post("/admin/login", data={"code": code}, follow_redirects=False)
        assert r.status_code == 302
        assert "/admin" in r.headers.get("Location", "")

    def test_admin_without_2fa_enrolled_logs_in_directly(self, client, make_user):
        make_user("tfaadmin3", role="admin")
        r = client.post("/admin/login", data={"identifier": "tfaadmin3", "password": "password123"},
                        follow_redirects=False)
        assert r.status_code == 302
        assert "/admin" in r.headers.get("Location", "")


# ── promote_admin.py CLI script ─────────────────────────────────────────────────

class TestPromoteAdminScript:
    """Correctness is tested in-process against the shared app/db fixture
    (fast, deterministic). A separate subprocess smoke test below confirms
    the actual CLI entry point is wired up the same way."""

    def test_promote_and_demote_existing_user(self, app, db, make_user):
        import scripts.promote_admin as promote_admin
        uid = make_user("scriptcliuser")

        with app.app_context():
            from models import User, AdminAuditLog
            result = promote_admin.apply_role_change("scriptcliuser@test.local")
            assert result["ok"] is True and result["exit_code"] == 0
            assert db.session.get(User, uid).role == "admin"
            assert AdminAuditLog.query.filter_by(action="user.promote",
                                                 target_id=str(uid)).count() >= 1

            result = promote_admin.apply_role_change("scriptcliuser@test.local", demote=True)
            assert result["ok"] is True and result["exit_code"] == 0
            assert db.session.get(User, uid).role == "user"
            assert AdminAuditLog.query.filter_by(action="user.demote",
                                                 target_id=str(uid)).count() >= 1

    def test_promote_missing_user_reports_failure(self, app):
        import scripts.promote_admin as promote_admin
        with app.app_context():
            result = promote_admin.apply_role_change("nobody-at-all@test.local")
            assert result["ok"] is False and result["exit_code"] == 1

    def test_promote_already_admin_is_a_no_op(self, app, db, make_user):
        import scripts.promote_admin as promote_admin
        uid = make_user("scriptalreadyadmin", role="admin")
        with app.app_context():
            from models import AdminAuditLog
            before = AdminAuditLog.query.filter_by(action="user.promote",
                                                    target_id=str(uid)).count()
            result = promote_admin.apply_role_change("scriptalreadyadmin@test.local")
            assert result["ok"] is True
            assert AdminAuditLog.query.filter_by(
                action="user.promote", target_id=str(uid)).count() == before

    def test_cli_subprocess_smoke(self):
        """One real end-to-end run of the CLI, to prove `python
        scripts/promote_admin.py <email>` is wired correctly. Uses its own
        throwaway sqlite file rather than the shared test database, since
        spawning a subprocess against a file another process is actively
        writing to is inherently timing-sensitive on Windows."""
        import subprocess
        import sys as _sys
        import tempfile
        from conftest import BASE_DIR

        tmp_dir = tempfile.mkdtemp(prefix="bulllogic-promote-cli-")
        db_path = os.path.join(tmp_dir, "cli_test.db")
        env = dict(os.environ)
        env["DATABASE_URL"] = "sqlite:///" + db_path

        setup = subprocess.run(
            [_sys.executable, "-c",
             "from flask import Flask\n"
             "from extensions import db\n"
             "from models import User\n"
             "import os\n"
             "app = Flask(__name__)\n"
             "app.config['SQLALCHEMY_DATABASE_URI'] = os.environ['DATABASE_URL']\n"
             "db.init_app(app)\n"
             "with app.app_context():\n"
             "    db.create_all()\n"
             "    u = User(username='clismoke', email='clismoke@test.local', role='user')\n"
             "    u.set_password('x')\n"
             "    db.session.add(u)\n"
             "    db.session.commit()\n"],
            cwd=BASE_DIR, env=env, capture_output=True, text=True, timeout=60)
        assert setup.returncode == 0, setup.stderr

        script = os.path.join(BASE_DIR, "scripts", "promote_admin.py")
        r = subprocess.run([_sys.executable, script, "clismoke@test.local"],
                           cwd=BASE_DIR, env=env, capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr
        assert "now role 'admin'" in r.stdout
