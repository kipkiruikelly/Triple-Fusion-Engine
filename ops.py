"""ops.py, background platform operations.

  • Accuracy engine: resolves every past prediction against what the
    market actually did, platform-wide (the old flow only checked when a
    user manually asked, so the accuracy tables stayed empty).
  • Drift monitor: watches rolling directional accuracy per ticker and
    alerts staff when a model decays.
  • Daily digest: one morning summary notification/email for staff.
  • Churn helpers: classify users by recency so admins can act early.

All driven by a single ops thread started from app.py; each job is
idempotent and safe to re-run.
"""

import json
import logging
import threading
import time
from datetime import date, datetime, timedelta

log = logging.getLogger(__name__)

# Prediction horizon per interval, and the bar granularity used to grade it.
_HORIZON = {"1d": timedelta(days=1), "4h": timedelta(hours=4),
            "1h": timedelta(hours=1), "30m": timedelta(minutes=30),
            "15m": timedelta(minutes=15), "5m": timedelta(minutes=5),
            "1m": timedelta(minutes=1)}
# yfinance lookback limits per bar size, beyond these a prediction is
# recorded as unresolvable rather than retried forever.
_MAX_AGE = {"1d": timedelta(days=365), "4h": timedelta(days=55),
            "1h": timedelta(days=55), "30m": timedelta(days=55),
            "15m": timedelta(days=55), "5m": timedelta(days=55),
            "1m": timedelta(days=6)}
_BAR_FOR = {"1d": ("1y", "1d"), "4h": ("60d", "1h"), "1h": ("60d", "1h"),
            "30m": ("60d", "30m"), "15m": ("60d", "15m"),
            "5m": ("60d", "5m"), "1m": ("7d", "1m")}

MIN_SAMPLES = 10          # below this, stats honestly say "insufficient data"
DRIFT_FLOOR = 50.0        # 30d directional accuracy below this → alert
DRIFT_MIN_N = 10


# ── Accuracy engine ───────────────────────────────────────────────────────────

def resolve_pending(db, limit=300):
    """Grade matured, ungraded predictions. Returns (resolved, unresolvable)."""
    from models import PredictionHistory, PredictionAccuracy
    from market_data import get_history, data_status

    now = datetime.utcnow()
    pending = (PredictionHistory.query
               .outerjoin(PredictionAccuracy,
                          PredictionHistory.id == PredictionAccuracy.prediction_id)
               .filter(PredictionAccuracy.id.is_(None))
               .order_by(PredictionHistory.id.desc())
               .limit(limit * 2).all())

    resolved = unresolvable = 0
    series_cache = {}
    for pred in pending:
        if resolved >= limit:
            break
        ivl = pred.interval or "1d"
        horizon = _HORIZON.get(ivl, _HORIZON["1d"])
        due_at = pred.predicted_at + horizon
        if due_at > now:
            continue                          # not matured yet
        if now - pred.predicted_at > _MAX_AGE.get(ivl, _MAX_AGE["1d"]):
            # Too old to grade at this granularity, record honestly as
            # unresolvable so it is never retried.
            db.session.add(PredictionAccuracy(prediction_id=pred.id,
                                              checked_at=now))
            unresolvable += 1
            continue
        if data_status()["rate_limited"]:
            break                             # try again next cycle

        period, bar = _BAR_FOR.get(ivl, ("1y", "1d"))
        key = (pred.ticker, period, bar)
        try:
            if key not in series_cache:
                series_cache[key] = get_history(pred.ticker, period=period,
                                                interval=bar)[0]
            df = series_cache[key]
            idx = df.index.tz_localize(None) if getattr(df.index, "tz", None) is not None \
                  else df.index
            after = df[idx >= due_at]
            if after.empty:
                continue                      # bar not printed yet
            actual = float(after["Close"].iloc[0])
            if actual <= 0:
                continue
            d = (pred.direction or "").lower()
            dir_ok = (d == "up" and actual > pred.current_price) or \
                     (d == "down" and actual <= pred.current_price)
            pct_err = abs(pred.lr_pred - actual) / actual * 100
            db.session.add(PredictionAccuracy(
                prediction_id=pred.id, actual_price=round(actual, 4),
                direction_ok=bool(dir_ok), pct_error=round(pct_err, 2),
                checked_at=now))
            resolved += 1
        except Exception as e:
            log.warning("accuracy resolve failed for %s: %s", pred.ticker, e)
            continue
    db.session.commit()
    return resolved, unresolvable


def platform_stats(db, days=90):
    """Aggregate graded predictions per (ticker, interval) + overall."""
    from models import PredictionHistory, PredictionAccuracy
    since = datetime.utcnow() - timedelta(days=days)
    rows = (db.session.query(
                PredictionHistory.ticker, PredictionHistory.interval,
                db.func.count(PredictionAccuracy.id),
                db.func.sum(db.case((PredictionAccuracy.direction_ok.is_(True), 1),
                                    else_=0)),
                db.func.avg(PredictionAccuracy.pct_error))
            .join(PredictionAccuracy,
                  PredictionAccuracy.prediction_id == PredictionHistory.id)
            .filter(PredictionAccuracy.direction_ok.isnot(None),
                    PredictionHistory.predicted_at >= since)
            .group_by(PredictionHistory.ticker, PredictionHistory.interval)
            .all())
    per, tot_n, tot_ok = [], 0, 0
    for ticker, ivl, n, ok, err in rows:
        tot_n += n
        tot_ok += int(ok or 0)
        per.append({"ticker": ticker, "interval": ivl or "1d", "n": n,
                    "direction_accuracy": round((ok or 0) / n * 100, 1)
                                          if n >= MIN_SAMPLES else None,
                    "avg_pct_error": round(float(err), 2)
                                     if err is not None and n >= MIN_SAMPLES else None,
                    "sufficient": n >= MIN_SAMPLES})
    per.sort(key=lambda r: -r["n"])
    return {"days": days, "total_graded": tot_n,
            "overall_direction_accuracy": round(tot_ok / tot_n * 100, 1)
                                          if tot_n >= MIN_SAMPLES else None,
            "min_samples": MIN_SAMPLES, "per_model": per}


def ticker_stats(db, ticker, interval, days=90):
    """Track record for one model, used for the badge on results."""
    from models import PredictionHistory, PredictionAccuracy
    since = datetime.utcnow() - timedelta(days=days)
    n, ok = (db.session.query(
                 db.func.count(PredictionAccuracy.id),
                 db.func.sum(db.case((PredictionAccuracy.direction_ok.is_(True), 1),
                                     else_=0)))
             .join(PredictionHistory,
                   PredictionAccuracy.prediction_id == PredictionHistory.id)
             .filter(PredictionHistory.ticker == ticker,
                     PredictionHistory.interval == interval,
                     PredictionAccuracy.direction_ok.isnot(None),
                     PredictionHistory.predicted_at >= since)
             .first())
    n = n or 0
    return {"ticker": ticker, "interval": interval, "n": n, "days": days,
            "direction_accuracy": round((ok or 0) / n * 100, 1)
                                  if n >= MIN_SAMPLES else None,
            "sufficient": n >= MIN_SAMPLES}


# ── Drift monitor ─────────────────────────────────────────────────────────────

def check_drift(db):
    """Alert staff when a model's rolling 30d accuracy sinks below the
    floor. Deduped to one alert per model per 3 days via AppSetting."""
    from models import AppSetting, Notification, User, ErrorLog
    stats = platform_stats(db, days=30)
    state_row = db.session.get(AppSetting, "drift_state")
    state = json.loads(state_row.value) if state_row and state_row.value else {}
    today = str(date.today())
    alerts = []

    for m in stats["per_model"]:
        if m["n"] < DRIFT_MIN_N or m["direction_accuracy"] is None:
            continue
        if m["direction_accuracy"] >= DRIFT_FLOOR:
            continue
        key = f"{m['ticker']}:{m['interval']}"
        last = state.get(key)
        if last and (date.today() - date.fromisoformat(last)).days < 3:
            continue
        state[key] = today
        msg = (f"{m['ticker']} {m['interval']} model at "
               f"{m['direction_accuracy']}% directional accuracy "
               f"({m['n']} graded, 30d), below {DRIFT_FLOOR}% floor")
        alerts.append(msg)
        db.session.add(ErrorLog(severity="warning", endpoint="ops.drift",
                                message=msg[:500]))
        for staff in User.query.filter(User.role.in_(["support", "admin"])).all():
            db.session.add(Notification(user_id=staff.id, type="drift",
                                        title="Model drift detected",
                                        body=msg[:300], link="/admin/content"))
    if alerts:
        if state_row:
            state_row.value = json.dumps(state)
        else:
            db.session.add(AppSetting(key="drift_state", value=json.dumps(state)))
    db.session.commit()
    return alerts


def active_drift_alerts(db):
    """Models currently under the floor, shown in admin overview."""
    stats = platform_stats(db, days=30)
    return [f"Drift: {m['ticker']} {m['interval']} at {m['direction_accuracy']}% (30d)"
            for m in stats["per_model"]
            if m["n"] >= DRIFT_MIN_N and m["direction_accuracy"] is not None
            and m["direction_accuracy"] < DRIFT_FLOOR]


# ── Churn ─────────────────────────────────────────────────────────────────────

def churn_bucket(user):
    """active (<7d) | at_risk (7-30d) | churned (>30d) | new (never seen)."""
    if not user.last_seen:
        return "new"
    days = (datetime.utcnow() - user.last_seen).days
    if days < 7:
        return "active"
    if days <= 30:
        return "at_risk"
    return "churned"


def churn_counts(db):
    from models import User
    now = datetime.utcnow()
    return {
        "active":  User.query.filter(User.last_seen >= now - timedelta(days=7)).count(),
        "at_risk": User.query.filter(User.last_seen <  now - timedelta(days=7),
                                     User.last_seen >= now - timedelta(days=30)).count(),
        "churned": User.query.filter(User.last_seen <  now - timedelta(days=30)).count(),
        "new":     User.query.filter(User.last_seen.is_(None)).count(),
    }


# ── M-Pesa reconciliation (backup for lost callbacks) ─────────────────────────

def reconcile_mpesa_payments(db):
    """Poll Daraja's query API for pending STK pushes whose callback never
    arrived. Settles verified payments, fails terminal ones, and expires
    anything still pending after an hour. Never marks paid without a
    confirmed ResultCode of 0 from Safaricom."""
    from models import Payment
    try:
        from mpesa import query_status, MPESA_OK
        from routes.payments import (_settle_mpesa_payment, _fail_mpesa_payment,
                                     MPESA_RESULT_CODES)
    except Exception:
        return 0
    if not MPESA_OK:
        return 0

    now = datetime.utcnow()
    stale = (Payment.query
             .filter(Payment.provider == "mpesa", Payment.status == "pending",
                     Payment.created_at < now - timedelta(minutes=2))
             .limit(20).all())
    handled = 0
    for p in stale:
        if now - p.created_at > timedelta(hours=1):
            p.status = "failed"
            p.completed_at = now
            db.session.commit()
            handled += 1
            continue
        try:
            resp = query_status(p.reference)
        except Exception as e:
            log.warning("mpesa query failed for %s: %s", p.reference, e)
            continue
        code = str(resp.get("ResultCode", ""))
        if code == "0":
            _settle_mpesa_payment(p)
            log.info("mpesa reconcile: settled %s", p.reference)
            handled += 1
        elif code in MPESA_RESULT_CODES:
            _fail_mpesa_payment(p, code)
            handled += 1
    return handled


# ── Daily digest ──────────────────────────────────────────────────────────────

def send_daily_digest(app, db):
    """Once per calendar day: yesterday's numbers to every staff account."""
    from models import (AppSetting, User, Notification, Payment,
                        PredictionHistory, ErrorLog)
    marker = db.session.get(AppSetting, "digest_last_date")
    today = str(date.today())
    if marker and marker.value == today:
        return False
    enabled = db.session.get(AppSetting, "admin_digest_enabled")
    if enabled and enabled.value == "0":
        return False

    y0 = datetime.combine(date.today() - timedelta(days=1), datetime.min.time())
    y1 = datetime.combine(date.today(), datetime.min.time())
    signups = User.query.filter(User.created_at >= y0, User.created_at < y1).count()
    actives = User.query.filter(User.last_seen >= y0).count()
    preds   = PredictionHistory.query.filter(
        PredictionHistory.predicted_at >= y0,
        PredictionHistory.predicted_at < y1).count()
    revenue = (db.session.query(db.func.coalesce(db.func.sum(Payment.amount), 0))
               .filter(Payment.status == "paid", Payment.currency == "KES",
                       Payment.completed_at >= y0, Payment.completed_at < y1)
               .scalar())
    errors  = ErrorLog.query.filter(ErrorLog.created_at >= y0,
                                    ErrorLog.created_at < y1).count()
    churn   = churn_counts(db)
    acc     = platform_stats(db, days=30)

    body = (f"Yesterday: {signups} signups, {actives} active users, "
            f"{preds} predictions, KES {float(revenue or 0):,.0f} revenue, "
            f"{errors} errors. At-risk users: {churn['at_risk']}. "
            f"30d model accuracy: "
            f"{acc['overall_direction_accuracy'] if acc['overall_direction_accuracy'] is not None else 'insufficient data'}"
            f"{'%' if acc['overall_direction_accuracy'] is not None else ''}.")

    staff = User.query.filter(User.role.in_(["viewer", "support", "admin"])).all()
    for s in staff:
        db.session.add(Notification(user_id=s.id, type="digest",
                                    title=f"Daily digest, {today}",
                                    body=body[:300], link="/admin"))
    if marker:
        marker.value = today
    else:
        db.session.add(AppSetting(key="digest_last_date", value=today))
    db.session.commit()

    try:
        from extensions import mail
        if mail and app.config.get("MAIL_USERNAME"):
            from flask_mail import Message as M
            emails = [s.email for s in staff if s.role == "admin"]
            if emails:
                mail.send(M(subject=f"[BullLogic] Daily digest {today}",
                            recipients=emails, body=body))
    except Exception:
        pass
    log.info("daily digest sent: %s", body)
    return True


# ── Ops thread ────────────────────────────────────────────────────────────────

def start_ops_thread(app, db):
    """One thread, ticks every 15 min: digest daily, accuracy+drift ~6-hourly."""
    state = {"last_accuracy": 0.0}

    def _loop():
        time.sleep(90)   # let the app settle before first cycle
        while True:
            with app.app_context():
                try:
                    send_daily_digest(app, db)
                except Exception:
                    db.session.rollback()
                    log.exception("digest failed")
                try:
                    reconcile_mpesa_payments(db)
                except Exception:
                    db.session.rollback()
                    log.exception("mpesa reconcile failed")
                if time.time() - state["last_accuracy"] > 6 * 3600:
                    try:
                        r, u = resolve_pending(db)
                        if r or u:
                            log.info("accuracy engine: %s graded, %s unresolvable", r, u)
                        check_drift(db)
                        state["last_accuracy"] = time.time()
                    except Exception:
                        db.session.rollback()
                        log.exception("accuracy cycle failed")
            time.sleep(900)

    threading.Thread(target=_loop, daemon=True, name="ops").start()
