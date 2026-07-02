# Changelog

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
