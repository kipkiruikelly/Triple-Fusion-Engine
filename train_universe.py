"""
train_universe.py
Train LR (Ridge) + RF prediction models for every ticker x timeframe
combination, reusing train_all_tickers.py's fetch/feature/train pipeline
(same features, same model types - this script only orchestrates).

Priority order (train most useful first so the app works progressively):
  1. All tickers at 1D (daily)  - most stable, most data
  2. All tickers at 1h
  3. All tickers at 4h
  4. All tickers at 1w (weekly)
  5. All tickers at 30m
  6. All tickers at 15m
  7. All tickers at 5m
  8. 1m is opt-in only (--tf 1m) - very short yfinance history (7d)

Usage:
    python train_universe.py                       # all tickers, all TFs (except 1m)
    python train_universe.py --tf 1d 1h             # specific timeframes only
    python train_universe.py --tickers AAPL BTC     # specific tickers only
    python train_universe.py --skip-existing        # skip already-trained combos
    python train_universe.py --workers 4            # parallel training (max 6)

Writes Saved Models/training_manifest.json after each run: every
ticker+timeframe combo attempted, its status (success/skipped/failed), and
metrics for successful ones.
"""

import argparse
import json
import os
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

warnings.filterwarnings("ignore")

import train_all_tickers as T

MANIFEST_PATH = os.path.join(T.MODELS_DIR, "training_manifest.json")

PRIORITY_ORDER = ["1d", "1h", "4h", "1w", "30m", "15m", "5m", "1m"]
DEFAULT_TFS    = [tf for tf in PRIORITY_ORDER if tf != "1m"]   # 1m is opt-in


def _load_manifest() -> dict:
    if os.path.exists(MANIFEST_PATH):
        try:
            with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_manifest(manifest: dict):
    os.makedirs(T.MODELS_DIR, exist_ok=True)
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)


def _combo_key(ticker: str, interval: str) -> str:
    return f"{ticker.upper()}_{interval}"


def _already_trained(ticker: str, interval: str) -> bool:
    suffix = T.model_suffix(interval)
    return os.path.exists(os.path.join(T.MODELS_DIR, f"lr_model_{ticker.upper()}{suffix}.pkl"))


def _train_one(ticker: str, interval: str, fast: bool) -> dict:
    rf_trees, rf_depth = (50, 6) if fast else (100, 8)
    try:
        r = T.train_ticker(ticker, interval, rf_trees=rf_trees, rf_depth=rf_depth)
    except Exception as e:
        return {"ticker": ticker, "interval": interval, "status": "failed",
                "error": str(e)[:300], "trained_at": None}

    r["interval"]   = interval
    r["trained_at"] = datetime.now(timezone.utc).isoformat()
    if r["status"] == "ok":
        r["status"]    = "success"
        r["low_data"]  = r.get("rows", 0) < 100
        if r["low_data"]:
            r["note"] = "Low data model - treat signal as indicative only."
    return r


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tickers", nargs="+", default=T.DEFAULT_TICKERS,
                        help="Tickers to train (default: full DEFAULT_TICKERS universe)")
    parser.add_argument("--tf", nargs="+", default=DEFAULT_TFS,
                        choices=T.SUPPORTED_INTERVALS,
                        help="Timeframes to train, in the order given "
                             "(default: 1d 1h 4h 1w 30m 15m 5m - 1m is opt-in)")
    parser.add_argument("--skip-existing", action="store_true",
                        help="Skip ticker+timeframe combos that already have a model")
    parser.add_argument("--workers", type=int, default=2,
                        help="Parallel training workers (default 2, max 6 - yfinance rate limits)")
    parser.add_argument("--fast", action="store_true",
                        help="RF-50/depth-6, faster, slightly lower accuracy")
    args = parser.parse_args()

    tickers = [t.upper() for t in args.tickers]
    workers = max(1, min(args.workers, 6))
    tfs     = [tf for tf in PRIORITY_ORDER if tf in args.tf] or args.tf

    combos = [(t, tf) for tf in tfs for t in tickers]
    if args.skip_existing:
        before = len(combos)
        combos = [(t, tf) for t, tf in combos if not _already_trained(t, tf)]
        print(f"Skipping {before - len(combos)} already-trained combo(s).\n")

    print(f"Training {len(combos)} ticker x timeframe combo(s) "
          f"({len(tickers)} tickers x {len(tfs)} timeframes) with {workers} worker(s).")
    print(f"Timeframes (priority order): {', '.join(tfs)}\n")

    manifest = _load_manifest()
    results  = []
    wall0    = time.time()

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {}
        for i, (t, tf) in enumerate(combos):
            if i > 0 and i % workers == 0:
                time.sleep(0.5)          # stay polite to yfinance between batches
            futures[ex.submit(_train_one, t, tf, args.fast)] = (t, tf)

        for fut in as_completed(futures):
            t, tf = futures[fut]
            r = fut.result()
            results.append(r)
            manifest[_combo_key(t, tf)] = r
            _save_manifest(manifest)     # persist incrementally - safe to Ctrl-C

            if r["status"] == "success":
                low = "  [LOW DATA]" if r.get("low_data") else ""
                print(f"  [{t:8s} {tf:>3s}] {r['rows']:,} bars  "
                      f"LR MAE=${r['lr_mae']:.2f}  RF MAE=${r['rf_mae']:.2f}{low}  "
                      f"({r['elapsed']}s)")
            elif r["status"] == "skipped":
                print(f"  [{t:8s} {tf:>3s}] skipped (insufficient data: {r.get('bars', 0)} bars)")
            else:
                print(f"  [{t:8s} {tf:>3s}] FAILED: {r.get('error', 'unknown error')}")

    wall = time.time() - wall0
    ok      = [r for r in results if r["status"] == "success"]
    skipped = [r for r in results if r["status"] == "skipped"]
    failed  = [r for r in results if r["status"] == "failed"]

    print(f"\n=== Finished {len(combos)} combo(s) in {wall:.1f}s "
          f"({len(ok)} trained, {len(skipped)} skipped, {len(failed)} failed) ===")

    if failed:
        print("\nFailed combos:")
        for r in failed:
            print(f"  {r['ticker']} {r['interval']}: {r['error']}")

    print(f"\nManifest written to {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
