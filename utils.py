"""utils.py, shared constants, decorators, and stateless helpers."""

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

# ── Tier gating (see TIER_MATRIX.md) ─────────────────────────────────────────
# PRO_TICKERS above is an unrelated concept (the 10 tickers with the full
# LR+RF+XGB "Pro Models" ensemble, available to every user) - don't confuse
# it with subscription-tier asset gating below.

FREE_TIMEFRAMES = {"1D", "1W"}

# Built from predictor.YF_SYMBOL_MAP's own crypto/forex/commodity groupings
# rather than finnhub_service.symbol_for_finnhub(), which classifies anything
# it can't map as "stock" (including commodities) - fine for routing a quote
# request, wrong for deciding what's Pro-only here.
CRYPTO_TICKERS = {
    "BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "AVAX", "DOGE",
    "DOT", "LINK", "LTC", "MATIC", "SHIB", "UNI", "ATOM",
}
FOREX_TICKERS = {
    "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD",
    "EURGBP", "EURJPY", "GBPJPY", "USDMXN", "USDZAR", "XAUUSD", "XAGUSD",
}
COMMODITY_TICKERS = {
    "GOLD", "SILVER", "OIL", "BRENT", "NATGAS", "COPPER", "PLATINUM",
    "PALLADIUM", "WHEAT", "CORN", "SOYBEAN", "COTTON", "SUGAR", "COCOA", "COFFEE",
}
# Equities, ETFs, and indices stay free - only these three classes are
# Pro-only per TIER_MATRIX.md ("Free: Equities, ETFs / Pro: + crypto, forex,
# commodities"). Indices aren't named in the Pro-exclusive list, so they
# stay in the free bucket alongside equities/ETFs.
PRO_ONLY_ASSETS = CRYPTO_TICKERS | FOREX_TICKERS | COMMODITY_TICKERS

FREE_WATCHLIST_LIMIT   = 10
FREE_ALERTS_LIMIT      = 3
FREE_AI_ANALYSIS_DAILY = 1
FREE_JOURNAL_VISIBLE   = 10
FREE_BACKTEST_DAILY    = 1
# /api/backtest already hard-validates period against {6mo, 1y, 2y} for
# everyone - "5yr Pro history" isn't achievable without new work, so Pro
# keeps the existing max (2y) and only the daily-run cap changes for Free.
FREE_BACKTEST_PERIODS  = {"6mo", "1y"}


def check_timeframe_access(interval, user):
    """403 payload matches the upgrade_required shape blHandleUpgrade() in
    _navbar.html expects. Returns (allowed, error_payload_or_None)."""
    if user.is_pro:
        return True, None
    if (interval or "").upper() not in FREE_TIMEFRAMES:
        return False, {
            "ok": False, "error": "upgrade_required", "feature": "timeframe",
            "message": f"{interval} charts are a Pro feature. Free accounts get Daily and Weekly views.",
            "cta": "/pricing",
        }
    return True, None


def check_asset_access(ticker, user):
    if user.is_pro:
        return True, None
    if (ticker or "").upper() in PRO_ONLY_ASSETS:
        return False, {
            "ok": False, "error": "upgrade_required", "feature": "asset_class",
            "message": f"{ticker.upper()} is a Pro-only asset. Crypto, forex, and commodities require a Pro plan.",
            "cta": "/pricing",
        }
    return True, None


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
    """Give back one prediction, used when a prediction fails after the
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


def _send_whatsapp(to_number: str, text: str):
    sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
    from_number = os.environ.get("TWILIO_WHATSAPP_FROM", "")
    
    # Support both Twilio Auth Token and API Key authentication
    token = os.environ.get("TWILIO_AUTH_TOKEN", "")
    api_key_sid = os.environ.get("TWILIO_API_KEY_SID", "")
    api_key_secret = os.environ.get("TWILIO_API_KEY_SECRET", "")
    
    auth_user = api_key_sid if api_key_sid else sid
    auth_pass = api_key_secret if api_key_secret else token
    
    if not sid or not auth_user or not auth_pass or not from_number or not to_number:
        return
        
    # Standardize format
    if not to_number.startswith("whatsapp:"):
        to_number = f"whatsapp:{to_number}"
    if not from_number.startswith("whatsapp:"):
        from_number = f"whatsapp:{from_number}"
        
    import requests as _req
    from requests.auth import HTTPBasicAuth as _BasicAuth
    
    url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
    payload = {
        "From": from_number,
        "To": to_number,
        "Body": text
    }
    try:
        _req.post(url, data=payload, auth=_BasicAuth(auth_user, auth_pass), timeout=8)
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
