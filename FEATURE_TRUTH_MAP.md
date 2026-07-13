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
| 12 | `gamification.py` | **PARTIAL, unchanged** | The engine (competitions, 12-achievement catalog, checker) still works in memory and passes its tests, still unwired. State is in-memory only (engine attrs are two dicts), nothing ever writes `UserAchievement` rows, and `/api/competitions`/`/api/competitions/<id>/leaderboard`/`/api/achievements/user` still return hardcoded mocks (labeled `simulated`) - deliberately out of scope for the per-user paper trading work below, not forgotten (see `PAPER_TRADING_PHASE2_DESIGN.md`). **`/api/leaderboard/users` is no longer part of this module's gap** - it moved to real, DB-backed per-user data (see new section below) rather than being wired to this engine, because `CompetitionEngine` computes Sharpe from raw trade-PnL arrays, a different formula than `paper_engine.compute_metrics()`'s equity-curve-return Sharpe already used platform-wide - wiring it in would have meant two disagreeing "Sharpe" numbers in the same app. |
| 13 | `db_utils.py` | **PARTIAL / SCAFFOLD** | `run_migrations()` works (verified against a temp SQLite DB → True). Model **versioning is scaffold**: `create_model_version` builds a dict and logs it but persists nothing (the "version" is the wall-clock HHMM), `get_model_versions` just lists files in `Saved Models/`, and rollback does not exist. |

## New API endpoints (`routes/api.py`)

| Endpoint | Status | Evidence |
|----------|--------|----------|
| `GET /api/dashboard` | PARTIAL | Real user fields; portfolio block is placeholder unless a trading engine is connected - response now says `simulated: true` in that case. |
| `GET /api/predictions/recent` | WORKING | Real `PredictionHistory` query (field names fixed in this audit). |
| `POST /api/predictions/signal` | WORKING | Calls the real `run_prediction`; sentiment/calendar enrichment attached (sentiment carries its simulated flag through). |
| `GET /api/watchlist` | WORKING | Real `WatchlistItem` rows + yfinance prices. |
| `GET /api/leaderboard/users` | **WORKING** (was SCAFFOLD) | Fixed 2026-07-11: real per-`(user, strategy)` ranking by Sharpe ratio from actual `PaperTrade`/`PaperEquitySnapshot` rows, gated to users with >= `paper_engine.MIN_TRADES` closed trades. No `simulated` flag - it's real data. All-time only, no weekly/monthly slicing yet. See "Per-user paper trading" section below. (The unrelated model-accuracy leaderboard is still `GET /api/leaderboard` in routes/predictions.py.) |
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

## Admin console (audit date 2026-07-05, built and tested this session)

Access control (`routes/admin.py`): every `/admin*` route runs through
`admin_required(min_role)`, which checks authentication, role level, account
status, a sliding session timeout, and CSRF on every write. `User.role` is
`user|viewer|support|admin` with a safe `ALTER TABLE` migration in
`app.py:_run_migrations` so existing databases pick it up without a manual
step. **WORKING**, tested (`TestAdminAccessControl` walks every registered
`/admin*` route for both anonymous and plain-user callers).

Three fixed guards, by design, not bugs:
1. `admin_audit_log` is append-only: SQLAlchemy `before_update`/`before_delete`
   events and a `do_orm_execute` hook block per-instance and bulk ORM writes
   (`models.py`), and the SQL console independently refuses any non-SELECT
   statement that touches the table. **WORKING**, tested
   (`TestAuditAppendOnly`, `TestSqlConsole::test_admin_audit_log_only_accepts_select_in_console`).
2. `ENABLE_LIVE_TRADING` is surfaced read-only in the Feature Flags panel
   (`routes/admin_power.py:_live_trading_state`); it is never writable from
   the console, only from the environment. **WORKING**, tested
   (`TestFeatureFlags::test_live_trading_is_reported_read_only`).
3. Editing a graded prediction (`POST /admin/api/predictions/<id>/regrade`)
   requires a non-empty `reason` and is audited with that reason attached; it
   never silently overwrites a grade. **WORKING**, tested
   (`TestPredictionRegradeAndFlag`).

| Capability group | Status | Evidence and what is missing |
|---|---|---|
| SQL console | **WORKING** | SELECT runs freely; INSERT/UPDATE/DELETE preview an affected-row count and require `confirm: true` to execute; every statement is audited. Tested: role gate, SELECT, preview-then-write, audit-log guard. |
| Table browser + row editor | **WORKING** | Lists every table with row counts, paginates, edits/inserts/deletes by primary key; `admin_audit_log` is marked append-only and refuses row writes. Tested. |
| User field override | **WORKING** | Any editable `User` attribute (email, role, plan, verification, paper balance is not a real column, see Paper trading below) can be set with type coercion and old->new values audited. Tested. |
| Job runner | **WORKING** | Runs the same functions the ops thread schedules (`grade`, `drift`, `reconcile`, `digest`, `pyth_sync`) in a background thread, one at a time per job, with live status. Tested (registry contents, run + audit). |
| User management: search/activate/deactivate | **WORKING** | Pre-existing, unchanged this session. |
| User management: ban with reason | **WORKING** | `User.ban_reason` column added; banning without a reason is refused (400); the reason is stored on the user and included in the audit detail; unbanning clears it. Tested. |
| User management: grant/revoke Pro | **WORKING** | Pre-existing (`/admin/api/users/<id>/pro`), unchanged this session. |
| User management: resend verification | **WORKING** | New admin route reuses the exact same `_send_verification_email` helper the self-service `/verify/resend` route uses (exposed via `app.extensions`), so behavior (including "no mailer configured" handling) is identical, not reimplemented. Refuses if already verified. Tested. |
| User management: reset paper account | **WORKING** (was PARTIAL, fixed 2026-07-11) | `PaperTrade`/`PaperTradeEvent`/`PaperEquitySnapshot` gained a nullable `user_id` for the per-user paper trading work (see below); this route's `hasattr(model, "user_id")` check meant it needed **zero code changes** to start doing real work - it now genuinely clears one user's own paper rows, tested (`test_reset_paper_account_now_clears_only_that_user`). |
| User management: force logout | **WORKING** | Rotates `User.session_token`, which `get_id()` mixes into the Flask-Login session id, invalidating every existing session at once. Tested. |
| User management: view sessions | **PARTIAL, by design** | This app has one rotating session token per user, not a per-device session table, so there is no such thing as "list of currently active sessions" to show. The console instead shows **login history** (time, IP, device) from `ActivityLog`, and the API response says so explicitly. Regular `/login` now also writes an `ActivityLog("login")` row (it previously only did on Google login), so this history is populated for password logins too. Tested. |
| Impersonation | **WORKING** | Read-only flag set in session, refuses to impersonate another admin, start/stop both audited. Tested. |
| Predictions: view all / trigger grading / annotate | **WORKING** | `GET /admin/api/predictions` (existing) lists and filters by ticker/interval/date; the Job Runner's `grade` job runs the real grading function; `/flag` annotates. **Caveat carried over from the module-level audit above**: only `lr_pred`/`rf_pred` exist in the schema, there is no xgb/lstm to break accuracy out by, so "per model" analytics (below) means LR vs RF only. |
| Predictions: edit a graded result | **WORKING** | Guard 3 above. |
| Paper trading: view all / force close | **WORKING** | `GET /admin/api/paper/positions?status=all|open|closed` (previously hardcoded to `open` only, fixed this session); force-close requires a reason and is audited. Tested. |
| Payments: view + refund with notes + reconcile | **WORKING** | `Payment.notes` column added; refund persists an admin note (previously the note only existed transiently in the audit-log string, never stored on the row); reconcile moves a payment to the correct user. Tested. |
| Promo codes | **WORKING** | Generates N codes for D days with a note, usage (`used`, `used_by`, `used_at`) tracked on `GiftCode`. Tested. |
| Analytics | **WORKING, narrower than the literal spec** | Signups/DAU/MAU, Pro conversion funnel, weekly retention, revenue by period (separate `/admin/api/payments/summary` route) all real and queried from the database. "Prediction performance per asset and model": per-asset exists (`top_tickers`, `/admin/api/data-quality` confidence-band accuracy); per-model is LR vs RF only, because (as documented in the module table above) no xgb/lstm model has ever been trained for a deployed ticker. Tested (shape smoke test). |
| Feature flags | **WORKING** | DB-stored toggles (sentiment/gamification/ICT) and a per-ticker active-model override, both take effect immediately. `ENABLE_LIVE_TRADING` is shown but refuses writes (Guard 2). Tested. |
| Maintenance mode | **WORKING** (pre-existing, not new this session) | `app.py` `before_request` gates every route except `/admin`, `/login`, `/static`, etc. behind the `maintenance_mode` `AppSetting`; any authenticated staff role is exempt. No test existed before this session; added one. |
| System health | **WORKING** | Row counts and last-fetch/last-error per data source (`market_data.py` `_source_stats` gained `last_error`/`last_error_at` this session, previously only tracked success), the real 5-job registry now shown alongside the 2 pre-existing pseudo-jobs (was previously hardcoded and did not reflect the real jobs at all), log viewer with severity/endpoint/date filters. Tested (job registry visible). |
| Security: failed logins / IP lockouts | **WORKING** | Reads the in-memory rate limiter state and recent `login.failed` audit rows. Tested (shape smoke test). |
| Security: admin-only 2FA | **WORKING** | Enrollment is the existing self-service TOTP flow (`/api/2fa/setup`, `/api/2fa/enable`, on the regular `/profile` page) - there is no separate admin enrollment system. Once an `admin`-role account has 2FA enabled, both the password `/admin/login` form and the Google `/auth/google?admin=1` path stop short of completing the session and require a valid TOTP code as a second round trip; accounts without 2FA enrolled are unaffected. Tested: blocked without code, succeeds with a valid code, unaffected accounts log in directly. |
| Security: audit log as a filterable timeline | **WORKING** (pre-existing, not new this session) | `GET /admin/api/audit` filters by free text, exact action, admin id, and date range; the existing `audit.html` renders it as a timeline. Tested (filter smoke test added this session). |

## Per-user paper trading + trader leaderboard (added 2026-07-11)

Full design rationale in `PAPER_TRADING_PHASE2_DESIGN.md`. Summary of what
changed and what's still out of scope:

- **`paper_engine.py` is now multi-tenant.** `PaperTrade`,
  `PaperTradeEvent`, `PaperEquitySnapshot` gained a nullable `user_id`
  (`NULL` = the original platform-wide demo stream on `/paper`, unaffected
  and unchanged - all 27 pre-existing tests pass without modification).
  Every portfolio-state function (`open_positions`, `realized_equity`,
  `mark_to_market`, `class_exposure`, `breaker_tripped`, `try_open`,
  `strategy_report`, `snapshot_equity`) takes an optional `user_id=None`.
  Signal generation (`ml_signals`/`alpha_signals`) is still computed once
  per ops cycle and shared; only portfolio bookkeeping is per-owner
  (`_run_owner_cycle`, called once for the demo and once per opted-in
  user). **WORKING**, tested (`test_portfolio_isolation_between_users_and_demo`
  and 5 other new tests in `tests/test_paper_engine.py`).
- **Opt-in, not automatic**: `User.paper_trading_opted_in`
  (`/api/paper/opt-in`, `/api/paper/opt-out`). Opting out pauses new
  entries only - open positions still get exit-checked normally so nothing
  gets stranded. No plan-tier gate (open to Free through Enterprise).
- **XP integration** (ties into the Phase 1 streak/XP system, not a second
  scoring system): `utils.award_xp()` called directly from `try_open`
  (+3 on open) and `close_trade` (+15 profitable close, +3 losing close).
  Position size is never user-chosen (sized off a shared `risk_pct` config
  and each user's own equity), so this can't be gamed by oversized bets.
  **WORKING**, tested (`test_xp_awarded_on_open_and_close`,
  `test_demo_stream_trades_never_award_xp`).
- **`GET /api/leaderboard/users`** now returns real `(user, strategy)`
  rankings by Sharpe ratio (`routes/api.py:_trader_leaderboard`), reusing
  `paper_engine.compute_metrics()` - the same function, not a second
  formula. Rows need >= `MIN_TRADES` (10) closed trades to appear, the
  same honesty gate the engine already used everywhere else. **WORKING**,
  tested (`test_leaderboard_ranks_by_sharpe_not_raw_return` - confirms a
  low-volatility performer outranks a choppier one with a *higher* raw
  return, proving the ranking can't be won by reckless variance).
- **New page**: `/traders` (`Web Pages/traders.html`) - opt-in control,
  the user's own per-strategy portfolio summary, and the top-10 board.
  Requires login (matches the pre-existing gate on
  `/api/leaderboard/users`), no plan-tier gate. Linked from the navbar's
  Learn menu alongside (not replacing) the existing model-accuracy
  `/leaderboard`, relabeled "Model Leaderboard" there to disambiguate.
- **`/api/paper/trades`** (the public demo trade-log endpoint) was
  explicitly scoped to `user_id IS NULL` so it keeps meaning exactly what
  it meant before - the platform demo's log, not a feed mixing in
  individual users' own trades.
- **Deliberately not done this phase**: `gamification.py`'s
  `CompetitionEngine` (time-boxed contests) and `ACHIEVEMENTS` remain
  unwired - see module #12 above. `mt5_trading.py`'s MT5 Paper tab (a
  separate, singleton-based simulator with its own known concurrency bug)
  is untouched. No weekly/monthly leaderboard slicing - all-time only.

## Trained model coverage (updated 2026-07-06)

Prior state: LR+RF (+XGB where available) models existed for only 9 tickers
(AAPL, MSFT, GOOGL, AMZN, META, NVDA, TSLA, NDX, QQQ) at 1d and 1h. Every
other ticker or timeframe hit `/predict` and got either a crash or (after
this session's chart fix) an honest "no prediction model for this
timeframe" badge. The homepage's "210 Pro Models" stat was static marketing
text, not a real count.

`train_all_tickers.py` now supports all 7 timeframes the chart UI exposes
(1m/5m/15m/30m/1h/4h/1d, plus 1w), reusing the same 87-153 feature ICT/TA
pipeline for every asset class (equities, ETFs, crypto, forex, commodities,
indices) - no separate pipeline per asset class, per the existing design.
Two real bugs were found and fixed while extending it (not pre-existing on
1d/1h, which never exercised these code paths until 4h/5m/30m/1w training
was attempted):
- `_add_vix_features`/`_add_sector_features` crashed with "cannot reindex
  on an axis with duplicate labels" for any non-daily interval, because
  VIX/sector aux data fetched at intraday granularity produced duplicate
  normalized-day index entries. Fixed by deduping to one value per day
  before reindexing.
- Plain `LinearRegression` could blow up to nonsense coefficients (seen:
  BTC 5m predicting a next-close MAE in the tens of trillions of dollars)
  due to multicollinearity between Close/High/Low/SMA/EMA/lag features.
  Switched to `Ridge(alpha=1.0)` - still linear regression, regularized.
- Also: zero-variance columns (e.g. Asia-session features that are
  constant when a short intraday window never crosses that session, or
  earnings-window features with no earnings event in range) are now
  dropped per ticker+interval before scaling, since a constant column
  divides by zero in MinMaxScaler and had the same blow-up effect.

`train_universe.py` (new) orchestrates training across the ticker x
timeframe grid: priority order (1d, 1h, 4h, 1w, 30m, 15m, 5m, 1m opt-in),
`--skip-existing` to resume interrupted runs, and an incremental
`Saved Models/training_manifest.json` (gitignored along with the model
binaries) recording status and metrics per combo.

1d and 1w now train on **20 years** of history for every ticker (previously
5y, or "max" for a hardcoded subset of index/ETF tickers - that special
case was removed in favor of one uniform window). This does **not** apply
to intraday timeframes: yfinance enforces hard server-side history limits
that no period parameter can override (1m: 7d, 5m/15m/30m: 60d, 1h/4h:
730d) - those stay at their existing maximum windows.

Coverage after training (unique tickers with a model, out of 76 total that
have at least one timeframe), from the actual files in `Saved Models/`:

| Timeframe | Tickers covered |
|-----------|------------------|
| 1d  | 76 |
| 1h  | 73 |
| 4h  | 58 |
| 1w  | 75 |
| 30m | 73 |
| 15m | 73 |
| 5m  | 73 |
| 1m  | 73 |

Gaps are asset-data limits, not code bugs: a handful of tickers (e.g.
`MATIC`, `UNI`, `XAUUSD`, `XAGUSD`) return zero rows from yfinance at some
intraday intervals (renamed/delisted symbols or no intraday feed) and are
skipped with a logged reason rather than crashing; 4h is lowest because it
resamples from 1h, so any ticker without enough 1h history is skipped
there too.

**Not wired into live serving**: 1w models are trained and on disk, but
`/api/chart/<ticker>` still serves the "1W" tab as a resample of the 1d
model's candles/prediction (a deliberate choice made in the chart-feature
session, not an oversight) - actually consuming the dedicated weekly model
would need a route change not yet made.

**Deliberately not implemented**: the ticket that requested this training
pass also asked for a `predictor.py` fallback that reuses AAPL's model for
any ticker without its own (Step 6 of that ticket). Not implemented -
AAPL's regressor predicts an absolute price on AAPL's ~$300 scale, which is
nonsensical for BTC (~$80k) or GOLD (~$3k) predictions. The existing "no
prediction model for this timeframe" badge (shipped in the chart-feature
session) is the honest alternative already in place.

## ICT concept expansion + shared feature module (updated 2026-07-06)

**Architecture fix**: `predictor.py` (live inference) and `train_all_tickers.py`
(training) each had their own near-identical copy of the base TA/ICT feature
functions - a drift risk, since a model's saved `feature_cols` only match
reality if both sides compute every column exactly the same way. Extracted
both into `ict_features.py`; both callers now import from one implementation.

**16 additional ICT concepts** added on top of the existing set (OB, FVG,
OTE, IPDA, Equal H/L, CE, PD, Displacement, structure, sweeps, kill zones,
Silver Bullet, Asia range, NWOG, midnight open):

| Concept | Faithfulness |
|---|---|
| Equilibrium (EQ), Turtle Soup, ADR consumption, Std-Dev projections, True Week/Month Open, Breaker Block, Inversion FVG | Fairly unambiguous quantitative definitions |
| Mitigation Block, Rejection Block, Propulsion Block, Unicorn Model, Power of Three (AMD), Judas Swing | Real concepts, but ICT's actual criteria involve discretionary judgment a rule-based encoding has to approximate |
| SMT Divergence | Uses whatever correlated reference (SPY/sector ETF) is already fetched for VIX/sector features - **not a genuine correlated pair** for crypto/forex/commodities, only meaningful for equities |
| Market Maker Buy/Sell Models (MMBM/MMSM) | Heuristic 3-step approximation (liquidity sweep -> structure shift -> displacement) of what ICT teaches as a much richer multi-step sequence |

**Two real bugs found and fixed while implementing** (neither was a
pre-existing issue - both were introduced by adding 30+ new columns and
caught before shipping):
- `Dist_to_EQ` was defined as a pure linear transform of the already-existing
  `PD_Position` (correlation 1.0) - redundant but not itself harmful (Ridge
  tolerates perfect collinearity).
- After the full retrain, ~12 combos showed catastrophically negative R2
  (e.g. `UNI_1d`: -11,351). Diagnosed as **not** a coefficient blowup (Ridge
  coefficients stayed small and stable) but tiny test-split sizes (as few as
  33-72 rows) combined with 100+ features - R2's denominator is the test
  set's own variance, so it's inherently unstable on a small sample even
  when absolute error (MAE) is fine. Tried scaling Ridge's alpha up for
  low-sample combos; it helped some tickers and hurt others, confirming
  this is evaluation-metric noise, not a fixable modeling defect. Instead,
  `train_universe.py`'s `low_data` flag now also triggers on test-split
  size and observed R2 (not just total row count), so the manifest is
  honest about it: 23 combos are flagged, up from whatever the old
  rows-only threshold caught.

**Full retrain result**: all 8 timeframes across the ~76-ticker universe,
0 failures, verified live (AAPL prediction + Model Drivers panel both
reflect the new feature set without a code regression).

### Promotion script

`scripts/promote_admin.py <email> [--demote]` looks up a user by email
(case-insensitive), never creates one, sets `role` to `admin` (or back to
`user` with `--demote`), commits, and logs to `admin_audit_log` (the actor
recorded is the target account itself, since this is meant to bootstrap the
very first admin before any admin session exists to attribute the action
to). Loads the database URL exactly the way `app.py` does (`.env` then
`DATABASE_URL`, same sqlite fallback path), so the same command works
unchanged on a local checkout or inside the Docker container. **WORKING**,
smoke-tested manually against a throwaway sqlite database (promote, re-run
is a no-op, demote, missing-user exits 1) and covered by
`TestPromoteAdminScript`.
