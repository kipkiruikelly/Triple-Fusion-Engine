# Changelog

## 2026-07-02 — Product upgrade wave: trust, resilience, operations

Built after a full codebase audit, prioritizing what earns user trust and
what keeps the business observable. All features are live end-to-end
(backend + frontend + migrations) and covered by tests.

### For end users

- **Accuracy Engine + public Track Record** (`/track-record`).
  Every prediction is now automatically graded against what the market
  actually did once its horizon passes — platform-wide, in the background,
  including the wrong ones. Previously grading only ran when a user
  manually requested it, so the accuracy tables were empty and the
  question "how right has this model been?" was unanswerable.
  - Public track-record page with per-ticker/timeframe directional
    accuracy and average price error, 30/90-day windows.
  - Honest by design: models with fewer than 10 graded calls display
    "insufficient data" — no metric is ever fabricated.
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
  NIKKEI, …) and more US stocks/ETFs — 54 tickers total now supported.

### For admins

- **Model drift monitor.** Rolling 30-day directional accuracy per model;
  when one sinks below the 50% floor (min 10 graded calls), staff get an
  in-app alert, the dashboard shows a banner, and a warning is logged.
  Deduped to one alert per model per 3 days.
- **Daily digest.** Every morning: yesterday's signups, actives,
  predictions, KES revenue, errors, at-risk users, and 30-day model
  accuracy — as an in-app notification to all staff (+ email to admins
  when mail is configured). Disable with AppSetting
  `admin_digest_enabled=0`.
- **Churn-risk flags.** Users are bucketed by recency (engaged / at risk
  7–30d / churned >30d / never active). Filter in the users table, badge
  per row, and a "N at churn risk →" link on the dashboard KPI.
- **Feedback inbox** on the analytics page with average rating, word-list
  sentiment scoring, and resolve/reopen workflow.
- **Data-source health** surfaces in the admin alert bell when the quote
  provider is rate-limited.

### Engineering

- **`market_data.py`** — single choke-point for all Yahoo access: TTL
  caches, stale-while-error fallback, and a global rate-limit circuit
  breaker (a repeat of today's `YFRateLimitError` outage now degrades
  gracefully instead of blanking the app).
- **`ops.py`** — one background thread runs the accuracy engine, drift
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
- **yfinance upgraded 0.2.54 → ≥1.5.1** — the pinned version was being
  rejected by Yahoo (persistent `YFRateLimitError`), which had broken all
  quotes and training.

### Config notes

- `WEB_THREADS` (default 24) — waitress worker threads.
- `SECURE_COOKIES=true` — enable Secure cookie flag (HTTPS-only setups).
- `ADMIN_SESSION_MINUTES` (default 30) — admin console session timeout.
- `DISABLE_OPS_THREAD=true` — skip background ops (used by tests).
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
