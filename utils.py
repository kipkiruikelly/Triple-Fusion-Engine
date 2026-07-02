"""utils.py — shared constants, decorators, and stateless helpers."""

import json as _json
import os
from datetime import date, datetime
from functools import wraps

from flask import request
from flask_login import current_user, login_required

from extensions import db
from models import (
    User, Notification, UserWebhook, ActivityLog,
    FREE_DAILY_LIMIT,
)

# ── Constants ─────────────────────────────────────────────────────────────────

VALID_INTERVALS = {"1d", "1h", "4h", "30m", "15m", "5m", "1m"}

SCREENER_TICKERS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA",
    "QQQ", "NDX", "NFLX", "AMD", "V", "JPM", "ADBE", "CRM",
]

PRO_TICKERS = ["QQQ", "AAPL", "NVDA", "TSLA", "MSFT", "GOOGL", "META", "AMZN", "NDX", "DIA"]

CALENDAR_TICKERS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA",
    "NFLX", "AMD", "V", "JPM", "ADBE", "CRM",
]

_API_DAILY_LIMIT = 100

_POSITIVE_WORDS = {
    "rally","surge","soar","rise","gain","beat","record","profit","strong","growth",
    "upgrade","outperform","positive","boost","buy","breakout","milestone","expand",
    "exceed","robust","recover","rebound","launch","partner","deal","approve",
}
_NEGATIVE_WORDS = {
    "crash","fall","plunge","drop","loss","miss","decline","weak","cut","sell",
    "underperform","warning","concern","risk","debt","layoff","downgrade","recall",
    "investigation","lawsuit","fraud","default","bankruptcy","halt","suspend","probe",
}

_SECTOR_ETFS = {
    "Technology":       "XLK",
    "Healthcare":       "XLV",
    "Financials":       "XLF",
    "Consumer Disc":    "XLY",
    "Industrials":      "XLI",
    "Energy":           "XLE",
    "Consumer Staples": "XLP",
    "Real Estate":      "XLRE",
    "Materials":        "XLB",
    "Utilities":        "XLU",
    "Communication":    "XLC",
}


# ── Rate limiting (in-memory, per key) ────────────────────────────────────────

_rl_buckets = {}


def rate_limited(key, max_hits, window_s):
    """Sliding-window limiter. Records the hit and returns True if the
    caller has now exceeded max_hits within window_s."""
    import time as _time
    now = _time.time()
    hits = [t for t in _rl_buckets.get(key, []) if now - t < window_s]
    hits.append(now)
    _rl_buckets[key] = hits
    return len(hits) > max_hits


# ── Auth helpers ──────────────────────────────────────────────────────────────

def consume_quota(user):
    """Deducts one prediction from the user's daily quota. Returns False if exceeded."""
    today = date.today()
    if user.last_prediction_date != today:
        user.predictions_today    = 0
        user.last_prediction_date = today
    if not user.is_pro and user.predictions_today >= FREE_DAILY_LIMIT:
        return False
    user.predictions_today += 1
    db.session.commit()
    return True


def refund_quota(user):
    """Give back one prediction — used when a prediction fails after the
    quota was already consumed, so errors never cost free users a slot."""
    try:
        if not user.is_pro and (user.predictions_today or 0) > 0:
            user.predictions_today -= 1
            db.session.commit()
    except Exception:
        db.session.rollback()


def pro_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            from flask import jsonify
            return jsonify({"ok": False, "error": "Login required"}), 401
        if not current_user.is_pro:
            from flask import jsonify
            return jsonify({"ok": False, "error": "Pro subscription required"}), 403
        return f(*args, **kwargs)
    return decorated


# ── Notification helpers ──────────────────────────────────────────────────────

def _add_notification(user_id, ntype, title, body=None, link=None):
    try:
        n = Notification(user_id=user_id, type=ntype, title=title, body=body, link=link)
        db.session.add(n)
        db.session.commit()
    except Exception:
        pass


def _fire_webhooks(user_id, event, payload):
    import hmac as _hmac
    try:
        hooks = UserWebhook.query.filter_by(user_id=user_id, active=True).all()
        for hook in hooks:
            evts = (hook.events or "alert,signal").split(",")
            if event not in evts:
                continue
            try:
                import requests as _req
                body_str = _json.dumps({"event": event, "data": payload})
                headers  = {"Content-Type": "application/json", "X-BullLogic-Event": event}
                if hook.secret:
                    sig = _hmac.new(hook.secret.encode(), body_str.encode(), "sha256").hexdigest()
                    headers["X-BullLogic-Signature"] = f"sha256={sig}"
                _req.post(hook.url, data=body_str, headers=headers, timeout=5)
                hook.last_fired = datetime.utcnow()
                hook.fire_count = (hook.fire_count or 0) + 1
                db.session.commit()
            except Exception:
                pass
    except Exception:
        pass


def _send_discord(webhook_url, title, body, color=0x00AA55):
    try:
        import requests as _req
        _req.post(webhook_url, json={
            "embeds": [{"title": title, "description": body,
                        "color": color, "footer": {"text": "BullLogic"}}]
        }, timeout=5)
    except Exception:
        pass


def _log_activity(user_id, action, detail=None):
    try:
        ip = request.remote_addr if request else None
        ua = (request.headers.get("User-Agent") or "")[:200] if request else None
        entry = ActivityLog(user_id=user_id, action=action, detail=detail, ip=ip, ua=ua)
        db.session.add(entry)
        db.session.commit()
    except Exception:
        pass


def _send_telegram(chat_id: str, text: str):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token or not chat_id:
        return
    import requests as _req
    try:
        _req.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=8,
        )
    except Exception:
        pass


def _try_azure_download(ticker: str, interval: str = "1d"):
    from azure_storage import download_models_from_azure, azure_enabled
    BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
    models_dir = os.path.join(BASE_DIR, "Saved Models")
    suffix = "" if interval == "1d" else f"_{interval}"
    needed = f"lr_model_{ticker}{suffix}.pkl"
    if not os.path.exists(os.path.join(models_dir, needed)):
        if azure_enabled():
            download_models_from_azure(ticker)
