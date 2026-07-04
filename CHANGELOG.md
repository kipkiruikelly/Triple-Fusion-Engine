# Changelog

## 2026-07-05, Verification audit: MT5 safety gate, truth map, stabilization

No new features. This session proved what is real, gated what is
dangerous, and stabilized the core. Deliverables: FEATURE_TRUTH_MAP.md,
ENSEMBLE_REPORT.md, corrected README.

### Safety (Part 1)
- Live trading now requires an explicit ENABLE_LIVE_TRADING=true env
  flag (default OFF). MetaApi connect, direct MT5 connect, place_order
  and close_all all refuse real execution without it; refusals are
  logged as BLOCKED. Paper trading unaffected. No broker credentials
  were found wired or committed. New tests/test_mt5_safety.py (8 tests)
  asserts paper is the only active execution path.

### Truth map (Part 2)
- FEATURE_TRUTH_MAP.md classifies all 13 Phase modules and every
  /api endpoint as WORKING / PARTIAL / SCAFFOLD with execution
  evidence. Key findings: no stacking/XGB/LGB artifacts were ever
  deployed (live predictions are LR+RF voting, plus LSTM on AAPL
  daily); the Reddit sentiment component is simulated; gamification
  and several dashboard APIs return demonstration data; walk-forward's
  per-fold backtest ignores its mode argument.

### Stabilization (Part 3)
- Real bugs fixed, all exposed by making the shipped tests run:
  - risk_manager: Kelly fraction/percent unit bug (profitable histories
    collapsed to the 0.25% floor), trailing stop tightening the initial
    stop at entry, drawdown halt masked by the daily-loss message.
  - data_quality: weekends counted as data gaps on daily bars; empty
    DataFrame results not logged into the summary report.
  - config: env presets not idempotent (production RISK_PCT leaked into
    later presets); tests assumed a development .env host.
  - tests/mock_data.py: numpy int rejected by timedelta (broke 24 tests).
  - stacking_ensemble: OOF/close-price shape mismatch and a swapped
    scaler/meta-learner unpacking; the trainer had never completed a
    real run before.
  - walk_forward report printer crashed on Windows consoles.
- Fail-safing: every API endpoint serving demonstration data now
  returns simulated: true with a note (new tests/test_honesty_flags.py);
  sentiment payloads carry simulated flags and a warning when no live
  source is configured; walk_forward logs a warning that model modes
  are not evaluated; the shadowed mock /api/notifications endpoint was
  removed (the real one in routes/notifications.py serves it).

### Ensemble result (Part 4)
- Stacking ensemble trained and evaluated for AAPL and QQQ on
  chronological holdouts: it does NOT beat the best single base model
  (XGBoost on direction, LR on price error) on either ticker. Details
  and the deployment blocker (feature-pipeline mismatch) in
  ENSEMBLE_REPORT.md. Production models were restored after evaluation;
  QQQ daily models retrained through the live 82-feature pipeline.

### Hygiene (Part 5)
- Secrets scan of the full git history and tree: clean. .env was never
  committed; no key material found. Nothing requires rotation.
- Project name unified to BullLogic across README/API/DEPLOYMENT/test
  docs (Triple Fusion remains the engine's name).
- README rewritten: headline lists only verified-working features;
  experimental/scaffold work moved to a clearly labeled section.
- Removed all em and en dashes from tracked text/code (68 across 24
  files; 0 remain).

## 2026-07-04, Account-backed dark/light theme across every page

### Persistence
- New theme_preference column on users (light/dark/system, default
  system) with an ad-hoc migration; POST /api/theme saves the choice to
  the account for logged-in users and always sets a bl-theme cookie.
- The account preference wins on every device: server renders the right
  data-theme and the boot script mirrors the account value into
  localStorage, overwriting any stale device choice. Logged-out
  visitors fall back to localStorage/cookie, then the OS setting via
  prefers-color-scheme (which also covers JS-disabled browsers).

### One theme system, every page
- New shared partial _theme.html included in the head of all templates:
  the full light and dark palette as CSS custom properties defined
  once, a tiny blocking boot script that sets data-theme before first
  paint (no flash of the wrong theme), toggle/save helpers, and a
  themechange event.
- All 40+ main templates, the admin console, auth pages, docs pages,
  paper trading pages, offline/maintenance, and new 404/500 error pages
  now share it. Duplicated per-page :root palettes and the three old
  incompatible toggle implementations (bl-theme class flip, adm-theme
  dataset flip, per-page copies) were removed; hardcoded palette colors
  in styles were replaced with variables.
- Charts re-render with theme-appropriate colors when the theme
  changes: lightweight-charts (prediction result, backtest,
  performance), Chart.js (portfolio, admin dashboard and analytics),
  and the paper trading SVG equity curve.

### UI
- Consistent theme toggle in the header of every page (floating button
  on pages without a topbar), showing the current mode.
- New Appearance section in Profile with Light / Dark / System, saved
  to the account instantly.
- Emails intentionally keep their own styling.

### Fixes found during the walkthrough
- Broken logo markup on performance, pricing and model-metrics pages
  rendered "Logic" instead of "BullLogic".
- Full-width button styles on the auth pages no longer stretch the
  theme toggle.

## 2026-07-03, Paper trading engine and WorldQuant-style alpha framework

All simulated, virtual money only. No real order execution anywhere; a
test asserts no broker/order code is reachable from the paper system.

### Paper trading engine (paper_engine.py, routes/paper.py)
- Virtual portfolio (default 1,000,000 KES, labeled VIRTUAL/simulated
  everywhere) consuming two signal streams head to head: ml_ensemble
  (the platform's LR + RF vote) and alpha_rules (quant composite).
- Entries record the real market price, source (yfinance/pyth) and
  timestamp; fills pay configurable spread/slippage (5 bps) and
  commission (10 bps) per side so results are not fantasy fills.
- Exits on stop, target, signal reversal, or max holding period.
- Risk management: volatility-based sizing (1% of equity risked per
  trade over an ATR stop), max concurrent positions, per-asset-class
  exposure cap, and a daily loss circuit breaker that pauses entries.
- Append-only honesty: trades are never edited; every open/close/reject/
  breaker/toggle/config action appends to an audit trail. Nothing is
  seeded; day one starts at zero trades.
- Public results page /paper (equity curve, Sharpe, Sortino, max
  drawdown, win rate, profit factor, avg win/loss, exposure, turnover,
  per-model and per-asset-class breakdowns) with "insufficient data"
  below 10 closed trades. Public /paper/rules page renders every live
  config value so nothing is a black box.
- Admin console page (start/pause, per-strategy toggles, bounded config
  editor, open positions, audit events) plus a dashboard health badge.
- Engine cycles run in the existing ops thread every ~15 minutes,
  respecting market hours per asset class (crypto 24/7, US equities
  regular session, forex/commodities Sun 22:00 to Fri 21:00 UTC).
- Daily staff digest now includes a simulated P&L summary line.

### Alpha framework (alphas.py)
- 11 alphas as clean, testable functions with hypothesis docstrings:
  momentum (5/10/20d, MACD), mean reversion (20d z-score, RSI extremes,
  Bollinger position), volatility (realized vol ratio, vol-adjusted
  momentum), volume (signed volume z-score, OBV trend).
- Cross-sectional ranking across the tracked universe (favor top-ranked
  longs / bottom-ranked shorts rather than absolute values).
- Pyth oracle confidence filter downweights signals when the confidence
  interval is unusually wide.
- Composite scoring with IC-derived weights (negative-IC alphas floored
  to zero, never sign-flipped).
- Validation discipline: walk-forward out-of-sample IC per alpha,
  purged train/test splits for ML retraining (XGB CV folds now purge
  label overlap), and an explicit no-lookahead test that recomputes
  every alpha on truncated history.
- Alpha features (Alpha_*) added to the training feature list and the
  inference feature builder; existing models are unaffected (they select
  their saved feature columns) and the next retrain picks them up.

### Tests (51 new, 93 total)
- Position sizing math, friction application, stop/target/reversal/
  timeout execution, Sharpe/drawdown/profit-factor against hand-computed
  fixtures, daily loss breaker, append-only audit, honest empty states,
  no-lookahead assertion for every alpha, purged split leakage checks,
  and a broker-code scan asserting the paper system contains no real
  order path.

### Fixed along the way
- SSE price stream endpoint set a hop-by-hop Connection header that
  waitress rejects per PEP 3333; every stream connect was crashing (28
  occurrences in the service log). Header removed.

## 2026-07-02, Oracle data layer, resources hub, ethical engagement

### Phase 1: Pyth Network oracle integration
- New pyth_client.py talks to Pyth's Hermes REST API: fixed-point price
  parsing (price times 10^expo), confidence intervals, publish times,
  and an optional PYTH_API_KEY Bearer slot (mandatory from 31 July
  2026). Stale equity feeds outside US trading hours are reported as
  "market closed", not as errors.
- Feed mapping is synced programmatically into a new pyth_feed table
  (41 of 54 tickers mapped automatically) with an admin manager to
  enable, disable, or resync feeds.
- Verified Price: every sidebar price is cross-checked against the
  oracle. Sources agreeing within 0.5 percent get a Verified badge with
  an explanatory tooltip; disagreeing sources show both values and a
  warning, never a silent pick. Divergence incidents are logged and
  throttled.
- Automatic failover: when yfinance is down the oracle serves prices
  with a clear source label; the stale-data banner now appears only
  when every source fails.
- Confidence-aware predictions: each prediction records its data
  source, Pyth confidence percent, and source divergence. The admin
  system page correlates confidence bands with graded accuracy.
- Found and fixed along the way: the quote path was sending friendly
  symbols (BTC, EURUSD, GOLD) to Yahoo unmapped, so BTC quoted a small
  equity trust at 26 dollars instead of Bitcoin. The oracle divergence
  check caught it on first run.

### Phase 2: Dashboard organization and resources hub
- Sidebar navigation regrouped into Markets, My Predictions, Trust
  (Track Record, Methodology, Resources, Data Sources), and Account.
- New public /resources hub: curated links in four categories (Learn
  Trading, Market Data and News, Regulators and Safety, Our Platform)
  rendered as icon cards with external-link markers, rel=noopener, and
  a third-party disclaimer. Fully admin-manageable (category, title,
  URL, description, icon, sort, active) with 12 links seeded, including
  CMA Kenya and CBK safety resources.
- New public /methodology page explaining models, data, grading, and
  limits in plain English, linked from every prediction result.

### Phase 3: Ethical engagement
- Risk Basics interstitial: three short cards (probabilities not
  promises, diversification, only trade what you can afford to lose)
  shown exactly once before a user's first prediction.
- Gentle usage check-in after 15 predictions in one session, opt-out
  in Profile, never blocking.
- Persistent "informational, not financial advice" notice under the
  predict button; "Why am I seeing this?" tooltip on model signals.
- Easy exit: one-click JSON export of all personal data and true
  self-service account deletion with a single confirmation (replacing
  the old "contact support" dead end). Payment rows are retained for
  the legal audit trail only.
- Refund terms one click from the payment button; new public
  /data-sources page listing every provider and what it supplies.
- Tests grew to 42, covering fixed-point parsing, divergence
  detection, failover ordering, resources CRUD permissions, and the
  interstitial showing exactly once.

## 2026-07-02, Production auth, email, and payments

Everything in this wave works end to end with real services. Nothing is
mocked or stubbed.

### Authentication
- Google Sign-In (OAuth 2.0 authorization-code flow via Authlib) on the
  redesigned login and registration pages. First Google sign-in creates
  the account; later sign-ins reuse it. A Google email matching an
  existing password account links to it instead of duplicating. The
  button hides itself until GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET
  are set.
- Email verification on signup: signed 24 hour links (itsdangerous),
  "check your inbox" screen with a rate limited resend, and a hard gate:
  unverified accounts cannot run predictions or pay. Google users are
  treated as verified. Existing accounts were grandfathered in as
  verified. Addresses are validated with email-validator and normalized
  before saving.
- Password reset now sends a real branded email with a single-use link
  valid for 1 hour, never reveals whether an address exists, enforces
  the 8 character minimum, and invalidates every other active session by
  rotating a per-user session token checked on each request.
- Registration requires agreeing to the Terms of Service and Privacy
  Policy.

### Email
- New emails.py module: branded HTML templates with plain-text
  fallbacks for verification, password reset, and payment receipts.
  Sending is asynchronous so requests never block on SMTP. Works with
  Gmail app passwords or a transactional provider (Brevo recommended)
  purely via MAIL_* environment variables.

### Payments
- M-Pesa flow audited end to end. Every Daraja STK result code is now
  handled with a specific user message: cancelled prompt, timeout,
  insufficient balance, wrong PIN, expired request, busy session.
- Backup reconciliation job: if Safaricom's callback never arrives, the
  ops thread polls the query API for pending payments after 2 minutes
  and settles or fails them; anything still pending after an hour is
  expired. Nothing is ever marked paid without a verified ResultCode 0
  from Safaricom.
- Confirmed payments activate the plan instantly, store the M-Pesa
  receipt number, email the user a branded receipt, and appear in the
  admin transactions table. Sandbox to production is a pure .env change
  (MPESA_ENV plus credentials).

### Legal and support pages
- /faq (14 real questions), /privacy-policy (Kenya Data Protection Act
  2019 rights, third parties, retention), and /terms (not-financial-
  advice disclaimer, acceptable use, payments and refunds, liability,
  termination). Linked from footers on the main pages, required at
  registration, and shown next to the payment button. Each policy page
  carries a template notice recommending legal review before launch.

### Housekeeping
- Removed every em dash (561) and en dash (47) across 74 project files,
  replaced with commas, periods, or hyphens as reads best. Zero remain.
- .env.example added covering every configurable value.
- Test suite grew to 29 tests, adding Google OAuth callback handling,
  verification token expiry, reset single-use and session invalidation,
  and M-Pesa settlement verification.

## 2026-07-02, Product upgrade wave: trust, resilience, operations

Built after a full codebase audit, prioritizing what earns user trust and
what keeps the business observable. All features are live end-to-end
(backend + frontend + migrations) and covered by tests.

### For end users

- **Accuracy Engine + public Track Record** (`/track-record`).
  Every prediction is now automatically graded against what the market
  actually did once its horizon passes, platform-wide, in the background,
  including the wrong ones. Previously grading only ran when a user
  manually requested it, so the accuracy tables were empty and the
  question "how right has this model been?" was unanswerable.
  - Public track-record page with per-ticker/timeframe directional
    accuracy and average price error, 30/90-day windows.
  - Honest by design: models with fewer than 10 graded calls display
    "insufficient data", no metric is ever fabricated.
  - Each prediction result now carries its model's track-record badge.
- **Failed predictions no longer cost quota.** The free-tier slot is
  refunded whenever a prediction errors out (data outage, bad symbol).
- **Degraded-mode honesty.** When the market-data source is throttled,
  the app shows a banner and serves last-known prices with their real
  timestamps instead of blank tiles (`market_data.py` stale-while-error
  cache + circuit breaker shared by all endpoints).
- **Low-data & offline support.** With OS data-saver enabled, the app
  swaps the always-on price stream for a light 60-second snapshot poll.
  The service worker now serves an offline page when the connection dies.
- **Feedback widget.** One-tap star rating + comment on the main app,
  rate-limited, with Swahili-flavored thanks.
- **44 new tradeable symbols.** Models trained for crypto (BTC, ETH, …),
  forex (EURUSD, …), commodities (GOLD, OIL, …), indices (SPX, FTSE,
  NIKKEI, …) and more US stocks/ETFs, 54 tickers total now supported.

### For admins

- **Model drift monitor.** Rolling 30-day directional accuracy per model;
  when one sinks below the 50% floor (min 10 graded calls), staff get an
  in-app alert, the dashboard shows a banner, and a warning is logged.
  Deduped to one alert per model per 3 days.
- **Daily digest.** Every morning: yesterday's signups, actives,
  predictions, KES revenue, errors, at-risk users, and 30-day model
  accuracy, as an in-app notification to all staff (+ email to admins
  when mail is configured). Disable with AppSetting
  `admin_digest_enabled=0`.
- **Churn-risk flags.** Users are bucketed by recency (engaged / at risk
  7-30d / churned >30d / never active). Filter in the users table, badge
  per row, and a "N at churn risk →" link on the dashboard KPI.
- **Feedback inbox** on the analytics page with average rating, word-list
  sentiment scoring, and resolve/reopen workflow.
- **Data-source health** surfaces in the admin alert bell when the quote
  provider is rate-limited.

### Engineering

- **`market_data.py`**, single choke-point for all Yahoo access: TTL
  caches, stale-while-error fallback, and a global rate-limit circuit
  breaker (a repeat of today's `YFRateLimitError` outage now degrades
  gracefully instead of blanking the app).
- **`ops.py`**, one background thread runs the accuracy engine, drift
  checks, and the daily digest; each job is idempotent.
- **Security**: rate limiting on `/login` (10/15 min) and `/register`
  (5/hour) per IP; session/remember cookies are HttpOnly + SameSite=Lax
  (`SECURE_COOKIES=true` opts into the Secure flag behind HTTPS);
  password floor raised to 8 characters.
- **Database**: 11 indexes added for the hot query paths
  (prediction history, notifications, activity, payments, alerts…);
  `DATABASE_URL` env var supported (tests run on a throwaway DB).
- **Tests**: pytest suite (17 tests) covering registration rules, banned
  logins, rate limits, quota consume/refund, M-Pesa settlement
  idempotency, accuracy grading, insufficient-data honesty, drift
  alerting + dedupe, admin RBAC, and CSRF enforcement.
  Run: `.venv\Scripts\python.exe -m pytest tests\`.
- **yfinance upgraded 0.2.54 → ≥1.5.1**, the pinned version was being
  rejected by Yahoo (persistent `YFRateLimitError`), which had broken all
  quotes and training.

### Config notes

- `WEB_THREADS` (default 24), waitress worker threads.
- `SECURE_COOKIES=true`, enable Secure cookie flag (HTTPS-only setups).
- `ADMIN_SESSION_MINUTES` (default 30), admin console session timeout.
- `DISABLE_OPS_THREAD=true`, skip background ops (used by tests).
- Email digest/broadcasts need the existing `MAIL_*` variables.

### Future ideas (considered, not built)

- Real Daraja B2C reversal API for one-click refunds (needs production
  M-Pesa credentials; refunds currently mark + revoke Pro days).
- Per-user notification digests (weekly "your accuracy" email).
- WebSocket price streaming (SSE is sufficient at current scale).
- Multi-model A/B serving with per-model track records feeding an
  auto-router that prefers the currently-more-accurate model.
- Prediction explanations (top feature contributions per call).
- Progressive Web App install prompt + push notifications for alerts.
- SMS alerts via Africa's Talking for users without data bundles.
