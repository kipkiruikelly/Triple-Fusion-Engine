#!/usr/bin/env python3
"""
tools/train_batch.py — wait out any Yahoo rate limit, then train a ticker
batch with train_all_tickers.py and register the results in TickerConfig.

Usage:
    python tools/train_batch.py            # trains the STANDARD_BATCH below
    python tools/train_batch.py AAPL BTC   # trains an explicit list
"""

import os
import subprocess
import sys
import time
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

STANDARD_BATCH = [
    # US stocks
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "AMD",
    "NFLX", "JPM", "V", "JNJ", "XOM", "WMT",
    # ETFs
    "SPY", "QQQ", "IWM", "DIA", "GLD", "SLV", "TLT", "XLF", "XLE",
    # Crypto
    "BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "AVAX", "DOGE", "LINK",
    # Forex
    "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "NZDUSD", "EURGBP",
    # Commodities
    "GOLD", "OIL", "SILVER", "NATGAS", "COPPER", "WHEAT", "BRENT",
    # Indices
    "SPX", "NDX", "DJI", "RUT", "VIX", "FTSE", "DAX", "NIKKEI",
]

PROBE_EVERY_S = 300          # 5 min between rate-limit probes
PROBE_MAX_H   = 6            # give up waiting after this many hours


def _log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def wait_for_yahoo():
    import yfinance as yf
    deadline = time.time() + PROBE_MAX_H * 3600
    while time.time() < deadline:
        try:
            price = yf.Ticker("AAPL").fast_info.last_price
            if price:
                _log(f"Yahoo reachable (AAPL={price:.2f}) — starting training")
                return True
        except Exception as e:
            _log(f"Yahoo still unavailable ({type(e).__name__}) — retry in {PROBE_EVERY_S//60} min")
        time.sleep(PROBE_EVERY_S)
    return False


def register_tickers(tickers):
    """Add trained tickers to TickerConfig so the admin console lists them."""
    if not os.environ.get("SECRET_KEY"):
        kp = os.path.join(BASE_DIR, "instance", "secret_key.txt")
        if os.path.exists(kp):
            os.environ["SECRET_KEY"] = open(kp).read().strip()
    from app import app
    from extensions import db
    from models import TickerConfig
    added = 0
    with app.app_context():
        for sym in tickers:
            has_model = os.path.exists(os.path.join(BASE_DIR, "Saved Models",
                                                    f"rf_model_{sym}.pkl"))
            if has_model and not TickerConfig.query.filter_by(symbol=sym).first():
                db.session.add(TickerConfig(symbol=sym, enabled=True))
                added += 1
        db.session.commit()
    _log(f"Registered {added} new tickers in TickerConfig")


def main():
    tickers = [t.upper() for t in sys.argv[1:]] or STANDARD_BATCH
    _log(f"Batch: {len(tickers)} tickers")
    if not wait_for_yahoo():
        _log("Gave up waiting for Yahoo — rerun later")
        sys.exit(2)
    cmd = [sys.executable, os.path.join(BASE_DIR, "train_all_tickers.py"),
           "--tickers", *tickers, "--fast", "--workers", "2"]
    rc = subprocess.call(cmd, cwd=BASE_DIR)
    _log(f"train_all_tickers.py finished rc={rc}")
    register_tickers(tickers)
    sys.exit(rc)


if __name__ == "__main__":
    main()
