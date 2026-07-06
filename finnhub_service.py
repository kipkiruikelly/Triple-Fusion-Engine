"""finnhub_service.py, quotes via Finnhub.io.

Used by market_data.py as a second live-price source alongside yfinance
and Pyth: a fallback when yfinance is rate-limited/down, and a
cross-verifier for symbols that have no configured Pyth feed. Not used
for historical/training data (get_history in market_data.py is
untouched) and not wired into the prediction chart.

Free-tier coverage: US stocks/ETFs via /quote, crypto via Binance
candles, forex via OANDA candles. Commodities and indices aren't
reliably available on the free tier, so those tickers are passed
through as "stock" and will just come back empty, no behaviour change
for them beyond an unused request.

No key configured -> FINNHUB_KEY is "" and get_quote() always returns
None immediately, so callers can gate on FINNHUB_KEY directly.
"""

import os
import threading
import time

import requests

FINNHUB_KEY = os.environ.get("FINNHUB_API_KEY", "")
FINNHUB_BASE = "https://finnhub.io/api/v1"

_lock = threading.Lock()
_quote_cache = {}   # symbol -> (fetched_at, payload_or_None)
_QUOTE_TTL_OK = 20.0
_QUOTE_TTL_FAIL = 60.0

# Friendly app-wide ticker names (matches predictor.YF_SYMBOL_MAP) mapped
# to the Finnhub symbol format each asset class needs.
_CRYPTO_MAP = {
    "BTC": "BINANCE:BTCUSDT", "ETH": "BINANCE:ETHUSDT",
    "SOL": "BINANCE:SOLUSDT", "BNB": "BINANCE:BNBUSDT",
    "XRP": "BINANCE:XRPUSDT", "ADA": "BINANCE:ADAUSDT",
    "AVAX": "BINANCE:AVAXUSDT", "DOGE": "BINANCE:DOGEUSDT",
    "LINK": "BINANCE:LINKUSDT", "DOT": "BINANCE:DOTUSDT",
    "LTC": "BINANCE:LTCUSDT", "UNI": "BINANCE:UNIUSDT",
    "ATOM": "BINANCE:ATOMUSDT",
}
_FOREX_MAP = {
    "EURUSD": "OANDA:EUR_USD", "GBPUSD": "OANDA:GBP_USD",
    "USDJPY": "OANDA:USD_JPY", "AUDUSD": "OANDA:AUD_USD",
    "USDCAD": "OANDA:USD_CAD", "USDCHF": "OANDA:USD_CHF",
    "NZDUSD": "OANDA:NZD_USD", "EURGBP": "OANDA:EUR_GBP",
    "EURJPY": "OANDA:EUR_JPY", "GBPJPY": "OANDA:GBP_JPY",
}


def _asset(ticker):
    if ticker in _CRYPTO_MAP:
        return _CRYPTO_MAP[ticker], "crypto"
    if ticker in _FOREX_MAP:
        return _FOREX_MAP[ticker], "forex"
    return ticker, "stock"


def _get(endpoint, params):
    if not FINNHUB_KEY:
        return {}
    params = {**params, "token": FINNHUB_KEY}
    try:
        r = requests.get(f"{FINNHUB_BASE}{endpoint}", params=params, timeout=5)
        r.raise_for_status()
        return r.json()
    except Exception:
        return {}


def _payload(price, prev):
    price = float(price)
    prev = float(prev) if prev else price
    return {"price": round(price, 4), "prev": round(prev, 4),
            "chg": round(price - prev, 4),
            "pct": round((price - prev) / prev * 100 if prev else 0, 2)}


def get_quote(ticker):
    """Return {"price","prev","chg","pct"} or None. Same payload shape
    as market_data.get_quote() so callers can treat it as a peer source.
    Cached with the same TTL pattern as market_data to keep this well
    inside Finnhub's free-tier 60 calls/minute limit under normal use."""
    if not FINNHUB_KEY:
        return None
    ticker = ticker.upper()
    now = time.time()

    with _lock:
        hit = _quote_cache.get(ticker)
    if hit and now - hit[0] < (_QUOTE_TTL_OK if hit[1] else _QUOTE_TTL_FAIL):
        return hit[1]

    sym, kind = _asset(ticker)
    payload = None
    if kind == "stock":
        d = _get("/quote", {"symbol": sym})
        if d.get("c"):
            payload = _payload(d["c"], d.get("pc"))
    else:
        now_s = int(now)
        d = _get(f"/{kind}/candle", {"symbol": sym, "resolution": "1",
                                      "from": now_s - 300, "to": now_s})
        if d.get("s") == "ok" and d.get("c"):
            payload = _payload(d["c"][-1], d["o"][0])

    with _lock:
        _quote_cache[ticker] = (now, payload)
    return payload
