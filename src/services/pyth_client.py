"""pyth_client.py, oracle-grade prices from Pyth Network's Hermes API.

Hermes serves Pyth's institutional price feeds over plain REST, no
blockchain infrastructure needed. Docs: https://hermes.pyth.network/docs

Prices arrive in fixed-point form: integer `price` and `conf` scaled by
10^expo (expo is negative). publish_time tells us freshness; equity
feeds legitimately go quiet outside US market hours, which we report as
"market closed" rather than an error.

PYTH_API_KEY (optional today) is sent as a Bearer token. Hermes makes
authentication mandatory on 31 July 2026, so set the key before then.
"""

import logging
import os
import threading
import time
from datetime import datetime

import requests

log = logging.getLogger(__name__)

HERMES_BASE = os.environ.get("PYTH_HERMES_URL", "https://hermes.pyth.network")
PYTH_API_KEY = os.environ.get("PYTH_API_KEY", "")

# How our ticker symbols translate to Pyth's naming scheme.
_CRYPTO = {"BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "AVAX", "DOGE", "LINK",
           "DOT", "LTC", "MATIC", "UNI", "ATOM", "SHIB"}
_METALS = {"GOLD": "Metal.XAU/USD", "SILVER": "Metal.XAG/USD"}
_FX_QUOTES = {"USD", "JPY", "GBP", "CAD", "CHF"}

_lock = threading.Lock()
_price_cache = {}          # feed_id -> (fetched_at, parsed_dict)
_PRICE_TTL = 10.0

# Freshness thresholds by asset class (seconds).
_FRESH_S = {"crypto": 120, "fx": 300, "metal": 300, "equity": 120}


def _headers():
    h = {"Accept": "application/json"}
    if PYTH_API_KEY:
        h["Authorization"] = f"Bearer {PYTH_API_KEY}"
    return h


def expected_pyth_symbol(our_symbol):
    """Best-guess Pyth symbol for one of our tickers, or None."""
    s = our_symbol.upper()
    if s in _CRYPTO:
        return f"Crypto.{s}/USD"
    if s in _METALS:
        return _METALS[s]
    if len(s) == 6 and s[3:] in _FX_QUOTES and s[:3].isalpha():
        return f"FX.{s[:3]}/{s[3:]}"
    if s.isalpha() and len(s) <= 5:          # US equities and ETFs
        return f"Equity.US.{s}/USD"
    return None


def asset_class(pyth_symbol):
    head = (pyth_symbol or "").split(".")[0].lower()
    return {"crypto": "crypto", "fx": "fx", "metal": "metal",
            "equity": "equity"}.get(head, "crypto")


def fetch_feed_directory():
    """Full Hermes feed list as {pyth_symbol: feed_id}, skipping
    deprecated feeds."""
    r = requests.get(f"{HERMES_BASE}/v2/price_feeds",
                     headers=_headers(), timeout=20)
    r.raise_for_status()
    directory = {}
    for item in r.json():
        attrs = item.get("attributes", {})
        sym = attrs.get("symbol", "")
        if not sym or "DEPRECATED" in attrs.get("description", "").upper():
            continue
        directory[sym] = item["id"]
    return directory


def sync_feed_mapping(db, symbols):
    """Map our tickers to Pyth feed ids and persist in PythFeed.
    Returns (mapped, unmapped) counts."""
    from models import PythFeed
    directory = fetch_feed_directory()
    mapped = unmapped = 0
    for sym in symbols:
        want = expected_pyth_symbol(sym)
        feed_id = directory.get(want) if want else None
        row = PythFeed.query.filter_by(symbol=sym.upper()).first()
        if feed_id:
            if row:
                row.feed_id = feed_id
                row.pyth_symbol = want
                row.updated_at = datetime.utcnow()
            else:
                db.session.add(PythFeed(symbol=sym.upper(), feed_id=feed_id,
                                        pyth_symbol=want, active=True))
            mapped += 1
        else:
            unmapped += 1
    db.session.commit()
    return mapped, unmapped


def _parse_entry(entry):
    """Hermes parsed entry -> {price, conf, publish_time} in real units."""
    p = entry.get("price", {})
    expo = int(p.get("expo", 0))
    scale = 10 ** expo
    return {"price": int(p.get("price", 0)) * scale,
            "conf": int(p.get("conf", 0)) * scale,
            "publish_time": int(p.get("publish_time", 0))}


def get_prices(feed_map):
    """feed_map: {our_symbol: (feed_id, pyth_symbol)}.
    Returns {our_symbol: {price, conf, publish_time, age_s, fresh,
    market_closed, source:'pyth'}}. Raises nothing; failures return {}."""
    if not feed_map:
        return {}
    now = time.time()
    result, to_fetch = {}, {}
    with _lock:
        for sym, (fid, psym) in feed_map.items():
            hit = _price_cache.get(fid)
            if hit and now - hit[0] < _PRICE_TTL:
                result[sym] = _decorate(hit[1], psym)
            else:
                to_fetch[sym] = (fid, psym)

    if to_fetch:
        try:
            params = [("ids[]", fid) for fid, _ in to_fetch.values()]
            params.append(("parsed", "true"))
            r = requests.get(f"{HERMES_BASE}/v2/updates/price/latest",
                             params=params, headers=_headers(), timeout=10)
            r.raise_for_status()
            parsed = {e["id"].lower().lstrip("0x"): _parse_entry(e)
                      for e in r.json().get("parsed", [])}
            with _lock:
                for sym, (fid, psym) in to_fetch.items():
                    entry = parsed.get(fid.lower().lstrip("0x"))
                    if entry and entry["price"] > 0:
                        _price_cache[fid] = (now, entry)
                        result[sym] = _decorate(entry, psym)
        except Exception as e:
            log.warning("pyth fetch failed: %s", e)
    return result


def _decorate(entry, pyth_symbol):
    age = max(0, time.time() - entry["publish_time"])
    cls = asset_class(pyth_symbol)
    fresh = age <= _FRESH_S.get(cls, 120)
    return {"price": round(entry["price"], 6), "conf": round(entry["conf"], 6),
            "publish_time": entry["publish_time"], "age_s": round(age, 1),
            "fresh": fresh, "source": "pyth",
            # A quiet equity feed outside trading hours is expected.
            "market_closed": (not fresh and cls == "equity")}
