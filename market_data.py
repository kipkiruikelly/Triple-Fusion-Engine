"""market_data.py — resilient, cached access to market data.

One choke-point for yfinance so the rest of the app gets:
  • TTL caching (interval-aware) — N callers cost one Yahoo request
  • stale-while-error — if Yahoo fails, serve the last good copy with
    an honest `as_of` timestamp instead of an error
  • a global rate-limit circuit breaker — after a YFRateLimitError all
    fetches back off for BREAKER_COOLDOWN_S instead of digging deeper

Usage:
    from market_data import get_history, get_quote, data_status
    df, meta = get_history("AAPL", period="1y", interval="1d")
    # meta = {"stale": bool, "as_of": iso-str, "source": "cache|live"}
"""

import threading
import time
from datetime import datetime

_lock = threading.Lock()
_hist_cache = {}      # (symbol, period, interval) -> (fetched_at, df)
_quote_cache = {}     # symbol -> (fetched_at, payload_or_None)

# Interval-aware freshness windows (seconds).
_HIST_TTL = {"1m": 120, "5m": 240, "15m": 300, "30m": 600,
             "1h": 900, "4h": 1800, "1d": 1800}
_QUOTE_TTL_OK = 20.0
_QUOTE_TTL_FAIL = 60.0

# Circuit breaker: set when Yahoo rate-limits us; all live fetches skip
# straight to cache until the cooldown passes.
BREAKER_COOLDOWN_S = 600
_breaker_until = 0.0


def _rate_limited_now():
    return time.time() < _breaker_until


def _trip_breaker():
    global _breaker_until
    _breaker_until = time.time() + BREAKER_COOLDOWN_S


def _is_rate_limit_error(exc):
    return "ratelimit" in type(exc).__name__.lower() or "Too Many Requests" in str(exc)


def data_status():
    """Health snapshot for banners/monitoring."""
    return {
        "rate_limited": _rate_limited_now(),
        "breaker_until": datetime.fromtimestamp(_breaker_until).isoformat()
                         if _rate_limited_now() else None,
        "hist_cached": len(_hist_cache),
        "quotes_cached": len(_quote_cache),
    }


def get_history(symbol, period="1y", interval="1d"):
    """Return (DataFrame, meta) — raises ValueError only if there is no
    live data AND nothing cached."""
    import yfinance as yf
    import pandas as pd

    key = (symbol.upper(), period, interval)
    ttl = _HIST_TTL.get(interval, 1800)
    now = time.time()

    with _lock:
        hit = _hist_cache.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1], {"stale": False, "source": "cache",
                        "as_of": datetime.fromtimestamp(hit[0]).isoformat()}

    if not _rate_limited_now():
        try:
            df = yf.download(symbol, period=period, interval=interval,
                             auto_adjust=True, progress=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            if df is not None and not df.empty:
                with _lock:
                    _hist_cache[key] = (now, df)
                return df, {"stale": False, "source": "live",
                            "as_of": datetime.fromtimestamp(now).isoformat()}
        except Exception as e:
            if _is_rate_limit_error(e):
                _trip_breaker()

    if hit:   # stale fallback — old data beats no data, say so honestly
        return hit[1], {"stale": True, "source": "cache",
                        "as_of": datetime.fromtimestamp(hit[0]).isoformat()}
    raise ValueError(f"No market data available for {symbol} "
                     f"({'rate limited' if _rate_limited_now() else 'fetch failed'})")


def get_quote(symbol):
    """Return quote dict or None. Failures cached briefly so a throttled
    host is not hammered."""
    import yfinance as yf
    symbol = symbol.upper()
    now = time.time()

    with _lock:
        hit = _quote_cache.get(symbol)
    if hit and now - hit[0] < (_QUOTE_TTL_OK if hit[1] else _QUOTE_TTL_FAIL):
        return hit[1]

    payload = None
    if not _rate_limited_now():
        try:
            fi = yf.Ticker(symbol).fast_info
            lp = float(fi.last_price or 0)
            pc = float(fi.previous_close or 0)
            if lp:
                payload = {"price": round(lp, 4), "prev": round(pc, 4),
                           "chg": round(lp - pc, 4),
                           "pct": round((lp - pc) / pc * 100 if pc else 0, 2)}
        except Exception as e:
            if _is_rate_limit_error(e):
                _trip_breaker()
            payload = None
    if payload is None and hit and hit[1]:
        return hit[1]   # stale quote beats blank tile
    with _lock:
        _quote_cache[symbol] = (now, payload)
    return payload
