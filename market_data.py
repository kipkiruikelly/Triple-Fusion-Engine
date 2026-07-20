"""market_data.py, resilient, cached access to market data.

One choke-point for yfinance so the rest of the app gets:
  • TTL caching (interval-aware), N callers cost one Yahoo request
  • stale-while-error, if Yahoo fails, serve the last good copy with
    an honest `as_of` timestamp instead of an error
  • a global rate-limit circuit breaker, after a YFRateLimitError all
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


# ── Multi-source verification (yfinance vs Pyth oracle) ──────────────────────

VERIFY_TOLERANCE_PCT = 0.5     # sources agreeing within this are "verified"

_source_stats = {
    "yfinance": {"success": 0, "fail": 0, "last_success": None,
                "last_error": None, "last_error_at": None},
    "pyth":     {"success": 0, "fail": 0, "last_success": None,
                "last_error": None, "last_error_at": None},
    "finnhub":  {"success": 0, "fail": 0, "last_success": None,
                "last_error": None, "last_error_at": None},
    "failovers": 0, "divergences": 0,
}
_divergence_last_logged = {}   # symbol -> ts, throttle ErrorLog spam


def source_stats():
    return dict(_source_stats)


def _mark(source, ok, err=None):
    s = _source_stats[source]
    if ok:
        s["success"] += 1
        s["last_success"] = datetime.utcnow().isoformat()
    else:
        s["fail"] += 1
        s["last_error"] = (err or "no data returned")[:200]
        s["last_error_at"] = datetime.utcnow().isoformat()


def _pyth_feed_map(symbols):
    """Active PythFeed rows for the given symbols; {} outside app context."""
    try:
        from models import PythFeed
        rows = PythFeed.query.filter(PythFeed.symbol.in_([s.upper() for s in symbols]),
                                     PythFeed.active.is_(True)).all()
        return {r.symbol: (r.feed_id, r.pyth_symbol) for r in rows}
    except Exception:
        return {}


def _log_divergence(symbol, yf_price, pyth_price, pct):
    now = time.time()
    if now - _divergence_last_logged.get(symbol, 0) < 3600:
        return
    _divergence_last_logged[symbol] = now
    _source_stats["divergences"] += 1
    try:
        from extensions import db
        from models import ErrorLog
        db.session.add(ErrorLog(
            severity="warning", endpoint="data.divergence",
            message=f"{symbol}: yfinance {yf_price} vs pyth {round(pyth_price, 4)} "
                    f"({pct:.2f}% apart, tolerance {VERIFY_TOLERANCE_PCT}%)"))
        db.session.commit()
    except Exception:
        pass


def get_quotes_verified(symbols):
    """Cross-checked quotes for a list of symbols.

    Returns {symbol: {price, pct, source, verified, divergence_pct,
    conf, conf_pct, publish_time, market_closed} or None}. Primary source
    is yfinance; Pyth verifies it and takes over when yfinance is down.
    Finnhub (only if FINNHUB_API_KEY is configured) fills the same two
    roles for symbols with no configured Pyth feed: cross-verifier when
    yfinance is up, failover when it isn't. Pyth stays the primary
    verifier wherever a feed exists - Finnhub only covers the gap.
    """
    import pyth_client
    import finnhub_service

    feed_map = _pyth_feed_map(symbols)
    pyth = {}
    if feed_map:
        pyth = pyth_client.get_prices(feed_map)
        _mark("pyth", bool(pyth))

    out = {}
    for sym in [s.upper() for s in symbols]:
        yq = get_quote(sym)
        _mark("yfinance", yq is not None)
        pq = pyth.get(sym)
        pq_usable = pq and pq["fresh"]

        if yq and pq_usable:
            div = abs(yq["price"] - pq["price"]) / pq["price"] * 100
            verified = div <= VERIFY_TOLERANCE_PCT
            if not verified:
                _log_divergence(sym, yq["price"], pq["price"], div)
            out[sym] = {**yq, "source": "yfinance+pyth",
                        "verified": verified,
                        "divergence_pct": round(div, 3),
                        "pyth_price": round(pq["price"], 4),
                        "conf": pq["conf"],
                        "conf_pct": round(pq["conf"] / pq["price"] * 100, 3)
                                    if pq["price"] else None,
                        "publish_time": pq["publish_time"],
                        "market_closed": False}
        elif yq and not pq_usable and finnhub_service.FINNHUB_KEY:
            fq = finnhub_service.get_quote(sym)
            _mark("finnhub", fq is not None)
            if fq and fq["price"]:
                div = abs(yq["price"] - fq["price"]) / fq["price"] * 100
                verified = div <= VERIFY_TOLERANCE_PCT
                if not verified:
                    _log_divergence(sym, yq["price"], fq["price"], div)
                out[sym] = {**yq, "source": "yfinance+finnhub",
                            "verified": verified,
                            "divergence_pct": round(div, 3),
                            "finnhub_price": round(fq["price"], 4),
                            "conf": None, "conf_pct": None,
                            "publish_time": None,
                            "market_closed": bool(pq and pq.get("market_closed"))}
            else:
                out[sym] = {**yq, "source": "yfinance", "verified": False,
                            "divergence_pct": None, "conf": None, "conf_pct": None,
                            "publish_time": None,
                            "market_closed": bool(pq and pq.get("market_closed"))}
        elif yq:
            out[sym] = {**yq, "source": "yfinance", "verified": False,
                        "divergence_pct": None, "conf": None, "conf_pct": None,
                        "publish_time": None,
                        "market_closed": bool(pq and pq.get("market_closed"))}
        elif pq_usable:
            # yfinance down: the oracle keeps prices flowing.
            _source_stats["failovers"] += 1
            out[sym] = {"price": round(pq["price"], 4), "prev": None,
                        "chg": None, "pct": None, "source": "pyth",
                        "verified": False, "divergence_pct": None,
                        "conf": pq["conf"],
                        "conf_pct": round(pq["conf"] / pq["price"] * 100, 3)
                                    if pq["price"] else None,
                        "publish_time": pq["publish_time"],
                        "market_closed": False}
        elif finnhub_service.FINNHUB_KEY and (
                fq := finnhub_service.get_quote(sym)):
            # yfinance and Pyth both down/unconfigured: Finnhub keeps a
            # live price flowing, same failover shape as the Pyth branch.
            _mark("finnhub", True)
            _source_stats["failovers"] += 1
            out[sym] = {**fq, "source": "finnhub", "verified": False,
                        "divergence_pct": None, "conf": None, "conf_pct": None,
                        "publish_time": None, "market_closed": False}
        else:
            out[sym] = None
    return out


def data_status():
    """Health snapshot for banners/monitoring."""
    return {
        "rate_limited": _rate_limited_now(),
        "breaker_until": datetime.fromtimestamp(_breaker_until).isoformat()
                         if _rate_limited_now() else None,
        "hist_cached": len(_hist_cache),
        "quotes_cached": len(_quote_cache),
    }


def _yf_symbol(symbol):
    """Friendly symbols (BTC, EURUSD, GOLD) to real Yahoo tickers
    (BTC-USD, EURUSD=X, GC=F). Without this, yfinance quietly returns a
    tiny equity trust that happens to trade under the ticker BTC."""
    symbol_upper = symbol.upper()
    overrides = {
        "SPXUSD": "^GSPC",
        "SPX500": "^GSPC",
    }
    if symbol_upper in overrides:
        return overrides[symbol_upper]

    try:
        from predictor import YF_SYMBOL_MAP
        return YF_SYMBOL_MAP.get(symbol_upper, symbol_upper)
    except Exception:
        return symbol_upper


def get_history(symbol, period="1y", interval="1d"):
    """Return (DataFrame, meta), raises ValueError only if there is no
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
            df = yf.download(_yf_symbol(symbol), period=period, interval=interval,
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

    if hit:   # stale fallback, old data beats no data, say so honestly
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
            fi = yf.Ticker(_yf_symbol(symbol)).fast_info
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
