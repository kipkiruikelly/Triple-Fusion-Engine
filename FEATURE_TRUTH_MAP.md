# Feature Truth Map

Audit date: 2026-07-05. Every status below was assigned by executing the
module or endpoint on this machine, not by reading the code alone.
Statuses: **WORKING** (real end to end, verified by execution, has a test),
**PARTIAL** (runs but incomplete or unwired; missing piece stated),
**SCAFFOLD** (code exists and returns responses, but no real functionality
behind it), **ABSENT** (referenced but not implemented).

A 200 response was not accepted as proof of anything.

## The 13 modules

| # | Module | Status | Evidence and what is missing |
|---|--------|--------|------------------------------|
| 1 | `stacking_ensemble.py` | **PARTIAL** | Unit tests pass, but the trainer had never been run end to end: on real data it crashed twice (OOF/close-array shape mismatch; swapped unpacking in the test-evaluation step). Both fixed in this audit, after which it trains and evaluates cleanly for AAPL and QQQ. There are still **no deployable stacking/XGB/LGB artifacts**: the trainer consumes 21-column featured CSVs while live models use a 70+ feature builder, so its artifacts are incompatible with the live predictor and were not deployed (production models restored after evaluation). **Live predictions remain LR+RF voting (+LSTM for AAPL).** See ENSEMBLE_REPORT.md. |
| 2 | `lstm_trainer.py` | **PARTIAL** | Module imports; TensorFlow 2.21 installed; exactly one trained artifact exists (`lstm_model_AAPL.keras`), so the LSTM vote participates for AAPL daily only. No dedicated test file for the trainer; training end-to-end was not re-run in this audit. |
| 3 | `feature_engineering.py` (ICT) | **WORKING (library, after fix)** | Real API: `add_enhanced_ict_features`, `detect_bos_choch`, `detect_enhanced_fvg`, `detect_market_structure`, `detect_order_flow_imbalance`; wired into `data_pipeline.py`. This audit found that 4 of its features (`BOS_Bull_Count`, `BOS_Bear_Count`, `CHoCH_Signal`, `FVG_Mitigated`) had NEVER produced values: a pandas index-alignment bug assigned all-NaN columns, and the pipeline's dropna then deleted every row of any dataset it processed. Fixed and covered by the now-passing pipeline tests. Saved models still predate these features; they take effect at next retrain. |
| 4 | `walk_forward.py` | **PARTIAL** | Purged/embargoed splits and fold metrics are real and tested (10/10). BUT executing it end to end (Part 4) proved the per-fold backtest is a fixed SMA20/50 crossover: `mode="ml"`, `"fused"` and `"tech"` produced byte-identical results and no model is trained per fold. Now logs a warning saying exactly that. Report printer also crashed on Windows consoles (box-drawing chars) - fixed. |
| 5 | `config.py` | **WORKING** | Pydantic settings singleton used by app and mt5_trading. Two real bugs found and fixed in this audit: env presets were not idempotent (production `RISK_PCT=0.5` leaked into dev/staging), and tests assumed a dev `.env`. 10/10 tests pass. |
| 6 | `messaging.py` | **WORKING** | Executed: publish/subscribe delivered `{'x': 1}` end to end after Redis connect failed and the in-memory fallback engaged (this host has no Redis). Caveat: nothing in the app publishes or subscribes yet - it is available infrastructure, not an active bus. |
| 7 | `smart_router.py` | **WORKING (library)** | TWAP/VWAP/Iceberg logic passes its 646-line test file. All child orders route through `MT5Trader.place_order`, which is now gated (Part 1). Not wired into any route/UI - nothing calls it in the running app. |
| 8 | `risk_manager.py` | **WORKING** | Wired into the mt5 auto-trade loop (`check_guardrails`). This audit found and fixed three real bugs the tests exposed: (1) Kelly returned a fraction but clamped against percent bounds, so every profitable history collapsed to the 0.25% floor; (2) trailing stop engaged at entry, silently tightening the initial 1.5×ATR stop to 1×ATR; (3) a 21% drawdown reported as a daily-loss trip instead of a drawdown halt. 74/74 tests pass. One contradictory test (15% down-day expected to pass) was corrected to expect a block. |
| 9 | `sentiment.py` | **PARTIAL** | Lexicon scoring is real and tested (probe: +0.87 bullish text, -0.95 bearish text). NewsAPI path is real code but **no NEWSAPI_KEY is configured**, so it returns nothing. The Reddit component is **simulated** - hardcoded per-ticker popularity plus random noise (`_reddit_mention_count`). Fail-safed in this audit: payloads now carry `simulated: true` and a warning whenever no live source is behind the number. |
| 10 | `economic_calendar.py` | **PARTIAL** | Executed: 23 curated real 2026 events (FOMC/NFP/CPI), `get_upcoming_events(30d)=4`, `event_volatility_warning` returns a real recommendation. It is a **static hand-maintained list**, not a live feed - accurate for 2026, stale after. Tests pass. |
| 11 | `data_quality.py` | **WORKING (library)** | 16/16 tests pass after this audit fixed weekend spacing being counted as data gaps (a valid business-day frame scored 83/100) and empty-frame checks not being logged. Caveat: **nothing imports it** outside tests - the data pipeline does not call it yet. |
| 12 | `gamification.py` | **PARTIAL** | The engine (competitions, leaderboards, 12-achievement catalog, checker) works in memory and passes its tests. BUT: state is in-memory only (verified: engine attrs are two dicts), nothing ever writes `UserAchievement` rows (repo-wide grep: zero writers), and the `/api/competitions` + `/api/leaderboard/users` endpoints do NOT use this engine - they return hardcoded mocks (now labeled `simulated`). |
| 13 | `db_utils.py` | **PARTIAL / SCAFFOLD** | `run_migrations()` works (verified against a temp SQLite DB → True). Model **versioning is scaffold**: `create_model_version` builds a dict and logs it but persists nothing (the "version" is the wall-clock HHMM), `get_model_versions` just lists files in `Saved Models/`, and rollback does not exist. |

## New API endpoints (`routes/api.py`)

| Endpoint | Status | Evidence |
|----------|--------|----------|
| `GET /api/dashboard` | PARTIAL | Real user fields; portfolio block is placeholder unless a trading engine is connected - response now says `simulated: true` in that case. |
| `GET /api/predictions/recent` | WORKING | Real `PredictionHistory` query (field names fixed in this audit). |
| `POST /api/predictions/signal` | WORKING | Calls the real `run_prediction`; sentiment/calendar enrichment attached (sentiment carries its simulated flag through). |
| `GET /api/watchlist` | WORKING | Real `WatchlistItem` rows + yfinance prices. |
| `GET /api/leaderboard/users` | SCAFFOLD | Hardcoded five fake traders - now labeled `simulated`. (The real model-accuracy leaderboard is `GET /api/leaderboard` in routes/predictions.py.) |
| `GET /api/competitions`, `GET /api/competitions/<id>/leaderboard` | SCAFFOLD | Hardcoded competitions; not connected to `gamification.CompetitionEngine`. Now labeled `simulated`. |
| `GET /api/achievements/user` | PARTIAL | Real DB query, but no code ever awards achievements, so it always returns empty. Response now says so. |
| `GET /api/notifications` | WORKING | Served by routes/notifications.py from the real Notification table (it registers before the blueprint). The shadowed mock in routes/api.py was dead code and was removed in this audit. |
| `GET /api/notifications/count` | WORKING | Real `Notification` table count. |
| `POST /api/notifications/mark-read` | SCAFFOLD | No-op - response now says "Not persisted". |
| `GET /api/settings`, `POST /api/settings` | WORKING | Real `UserPreferences` read/write. |
| `GET /api/profile` | WORKING | Real `current_user` fields. |
| `GET /api/market/movers` | SCAFFOLD | Hardcoded tickers - labeled `simulated`. |
| `GET /api/activity/recent` | SCAFFOLD | Hardcoded feed - labeled `simulated`. |
| `GET /api/portfolio` | SCAFFOLD | Hardcoded numbers - labeled `simulated`. |
| `GET /api/portfolio/equity-curve` | SCAFFOLD | **Random walk** from a seeded RNG - labeled `simulated`. |
| `POST /api/trading/place` | WORKING (gated) | Routes to `MT5Trader.place_order`; refuses real execution unless `ENABLE_LIVE_TRADING=true` (Part 1). |
| `GET /api/trading/positions`, `/api/trading/orders` | SCAFFOLD | Always return empty lists; not connected to any engine. |

## Cross-cutting findings

- **Live trading**: no real credentials configured anywhere; all real-order
  paths now refuse unless `ENABLE_LIVE_TRADING=true` (default off);
  8 safety tests assert this. Paper trading is the only active path.
- **The runtime prediction stack is LR + RF (+ LSTM for AAPL)** despite the
  Phase 1 ensemble code existing - no stacking/XGB/LGB artifacts were ever
  trained and saved for the deployed tickers.
- **Nothing consumes** `smart_router`, `messaging`, `walk_forward`,
  `stacking_ensemble`, `db_utils`, or `data_quality` in the running app;
  they are libraries/CLIs with tests, not features users touch.
