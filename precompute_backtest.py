#!/usr/bin/env python3
"""
precompute_backtest.py
Runs 2-year backtest for all trained tickers and saves results to
Data/backtest_summary.json — used by the /performance page to show
historical equity curves before live paper trades accumulate.

Run once manually, then re-run after retraining.
"""

import os, sys, json, warnings
warnings.filterwarnings("ignore")

BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
OUT_PATH  = os.path.join(BASE_DIR, "Data", "backtest_summary.json")
TICKERS   = ["QQQ", "SPY", "DIA", "AAPL", "MSFT", "TSLA",
             "NVDA", "GOOGL", "AMZN", "META", "ADBE"]

sys.path.insert(0, BASE_DIR)
from backtester import run_backtest

results = {}
combined_equity = {}  # date → running total across tickers (normalised)

for ticker in TICKERS:
    print(f"  Backtesting {ticker}…", end=" ", flush=True)
    try:
        r  = run_backtest(ticker, "1d", "2y", 10_000, 1.0)
        eq = r.get("equity_curve", [])
        m  = r.get("metrics", {})
        metrics = {
            "n_trades":      m.get("total_trades", 0),
            "win_rate":      round(m.get("win_rate", 0), 1),
            "profit_factor": round(m.get("profit_factor", 0), 2),
            "sharpe":        round(m.get("sharpe", 0), 3),
            "max_dd":        round(m.get("max_drawdown", 0), 2),
            "total_return":  round(m.get("total_return", 0), 2),
            "bh_return":     round(m.get("bh_return", 0), 2),
        }
        results[ticker] = {
            "metrics": metrics,
            "equity":  [{"date": p["date"], "value": round(p["equity"], 2)} for p in eq],
        }
        for point in eq:
            d = point["date"]
            combined_equity[d] = combined_equity.get(d, 0) + point["equity"]
        print(f"trades={metrics['n_trades']}  PF={metrics['profit_factor']}  ret={metrics['total_return']:+.1f}%")
    except Exception as e:
        print(f"SKIP ({e})")
        results[ticker] = {"metrics": {}, "equity": []}

# Build combined equity normalised to $10k start
if combined_equity:
    dates   = sorted(combined_equity.keys())
    n_ticks = sum(1 for t in TICKERS if results[t]["equity"])
    if n_ticks > 0:
        first_total = combined_equity[dates[0]]
        combined = [
            {"date": d, "value": round(combined_equity[d] / first_total * 10_000, 2)}
            for d in dates
        ]
    else:
        combined = []
else:
    combined = []

output = {
    "generated_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
    "tickers":      results,
    "combined":     combined,
}

os.makedirs(os.path.join(BASE_DIR, "Data"), exist_ok=True)
with open(OUT_PATH, "w") as f:
    json.dump(output, f)
print(f"\nSaved → {OUT_PATH}")
