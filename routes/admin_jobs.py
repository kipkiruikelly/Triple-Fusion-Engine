"""routes/admin_jobs.py

Manual background-job runner for the admin console. Each job runs in a
daemon thread; one run at a time per job key. Live status and captured
output are exposed to the Job Runner page.

Jobs here reuse the real functions used by the scheduled ops thread, so
"run now" does exactly what the schedule does, just on demand.
"""

import io
import logging
import threading
import traceback
from contextlib import redirect_stdout
from datetime import datetime

logger = logging.getLogger(__name__)

# key -> {label, desc, fn(app)->str|None}
JOB_REGISTRY = {}

# key -> live state
_state = {}
_lock = threading.Lock()


def _register(key, label, desc, fn):
    JOB_REGISTRY[key] = {"label": label, "desc": desc, "fn": fn}
    _state[key] = {"running": False, "last_run": None, "last_ok": None,
                   "last_ms": None, "output": ""}


# ── Job implementations (thin wrappers over the real ops functions) ───────────

def _job_grade(app):
    from extensions import db
    from ops import resolve_pending
    n = resolve_pending(db)
    return f"Graded {n} pending prediction(s)."


def _job_drift(app):
    from extensions import db
    from ops import check_drift
    alerts = check_drift(db)
    return f"Drift check complete. {len(alerts or [])} alert(s)."


def _job_reconcile(app):
    from extensions import db
    from ops import reconcile_mpesa_payments
    n = reconcile_mpesa_payments(db)
    return f"Reconciled {n} M-Pesa payment(s)."


def _job_digest(app):
    from extensions import db
    from ops import send_daily_digest
    send_daily_digest(app, db)
    return "Daily digest sent."


def _job_pyth_sync(app):
    from extensions import db
    from pyth_client import sync_feed_mapping
    from utils import PRO_TICKERS
    n = sync_feed_mapping(db, PRO_TICKERS)
    return f"Synced Pyth feed mapping ({n} feeds)."


_register("grade", "Grade predictions",
          "Resolve pending predictions against realized prices.", _job_grade)
_register("drift", "Drift monitor",
          "Recompute model drift alerts.", _job_drift)
_register("reconcile", "Reconcile M-Pesa",
          "Match pending M-Pesa transactions to payments.", _job_reconcile)
_register("digest", "Send staff digest",
          "Send the daily operations digest email now.", _job_digest)
_register("pyth_sync", "Sync Pyth feeds",
          "Refresh the oracle feed mapping table.", _job_pyth_sync)


# ── Runner ────────────────────────────────────────────────────────────────────

def run_job(app, key):
    """Start a job in the background. Returns False if already running."""
    with _lock:
        st = _state.get(key)
        if st is None:
            return False
        if st["running"]:
            return False
        st["running"] = True
        st["output"] = ""

    def _worker():
        started = datetime.utcnow()
        buf = io.StringIO()
        ok = False
        msg = ""
        try:
            with app.app_context(), redirect_stdout(buf):
                msg = JOB_REGISTRY[key]["fn"](app) or "Done."
            ok = True
        except Exception as e:
            msg = f"FAILED: {e}\n{traceback.format_exc()}"
            logger.exception("Admin job %s failed", key)
        finally:
            captured = buf.getvalue()
            with _lock:
                st = _state[key]
                st["running"] = False
                st["last_run"] = started.isoformat()
                st["last_ok"] = ok
                st["last_ms"] = int((datetime.utcnow() - started).total_seconds() * 1000)
                st["output"] = (captured + ("\n" if captured else "") + msg)[-4000:]

    threading.Thread(target=_worker, name=f"admin-job-{key}", daemon=True).start()
    return True


def job_status():
    with _lock:
        return {k: dict(v) for k, v in _state.items()}
