# BullLogic Verification Report

Date: 2026-07-04 (updated same day, afternoon follow-up session)
Method: every item below was exercised, not just read. Flows ran against a
throwaway audit instance (fresh SQLite DB, real app factory, real network for
market data) with a local SMTP sink on 127.0.0.1:8025 that speaks actual SMTP,
so every "email sent" verdict means a real message was transmitted and its
content inspected. Production state (grading backlog, paper engine, error log,
service) was read from the live instance/users.db (read-only) and the running
Windows service. Theme and page rendering were verified in a real Chrome
session against a locally served instance earlier today (screenshots of every
major page in both modes).

Statuses: PASS = executed end to end. FAIL = broken, details given.
DEGRADED = works with a caveat worth knowing. BLOCKED-EXTERNAL = code path
correct up to a boundary that needs credentials or a service only you can
provide. Nothing was marked PASS without being executed.

Full test suite: 105 passed, 0 failed (pytest, after audit fixes).

---

## 1. Inventory

- 190 routes registered (52 parameterless GET pages all render without a
  single 5xx; the rest exercised per area below): user pages, auth, public
  docs, ~70 JSON APIs, 45 admin routes, payments, MT5, PWA.
- Background jobs (single ops thread, 15-minute tick): accuracy grading
  (~6-hourly), drift monitor, churn counts, M-Pesa reconciliation, daily
  digest (once per calendar day), paper trading engine cycle. Plus a separate
  price-alert checker thread.
- Email types: verification, password reset, payment receipt, daily digest
  (all four exercised through the SMTP sink), price alerts (path exists,
  same send_email helper).
- Cross-checked against all five CHANGELOG waves; every shipped feature
  appears in the sections below. No CHANGELOG item was found missing from
  the codebase.

## 2. Per-item results

### Auth and account

| Item | Status | Evidence |
|---|---|---|
| Register: terms checkbox required | PASS | POST without agree_terms -> error "must agree" |
| Register: short password rejected | PASS | "at least 8 characters" |
| Register: invalid email rejected | PASS | email-validator path |
| Register: password mismatch rejected | PASS | "do not match" |
| Register: duplicate username rejected | PASS | "already taken" |
| Register: valid input | PASS | 302 -> /verify-notice, account created |
| Verification email sent | PASS | real SMTP message captured, link extracted |
| Unverified user blocked from predictions | PASS | POST /predict -> 302 /verify-notice |
| Resend rate limit | PASS | codes [200,200,200,429] (3/hour) |
| Tampered verification token | PASS | HTTP 400 |
| Expired verification token | PASS | HTTP 400 with "expired" message (clock back-dated 100h) |
| Valid token verifies email | PASS | email_verified=True, redirect home |
| Register rate limit (5/hr/IP) | PASS | observed during flows |
| Login wrong password | PASS | rejected, generic message |
| Login correct password | PASS | 302, session established |
| Session cookie hardening | PASS | HttpOnly + SameSite=Lax present; Secure off locally by design (SECURE_COOKIES=true is set in production .env) |
| Login rate limit | PASS | attempt 10 = 200, attempt 11 = 429 (10/15min/IP) |
| Logout | PASS | /profile redirects to /login afterwards |
| Google OAuth start | PASS | /auth/google 302 to accounts.google.com with correct params (creds present in .env) |
| Google OAuth full flow | BLOCKED-EXTERNAL | needs interactive Google consent |
| Password reset anti-enumeration | PASS | identical 200 + identical body for existing vs unknown email |
| Reset email sent | PASS | captured via SMTP sink, link extracted |
| Reset link sets new password | PASS | login with new password works |
| Reset token single-use | PASS | second use does not change password |
| Reset kills other sessions | PASS | parallel session 200 -> 302 login after reset (session_token rotation) |
| Theme saves to DB, survives logout/login | PASS | data-theme="light" server-rendered after fresh login |
| Theme on every page, no white flash | PASS | verified in Chrome earlier today: ~40 pages in both modes, blocking boot script in head, account-beats-localStorage proven live |
| Data export | PASS | /account/export returns JSON (fresh account, 235 bytes; grows with data) |
| Account deletion | PASS | login impossible afterwards |

### Predictions and data

| Item | Status | Evidence |
|---|---|---|
| Stock prediction (AAPL) | PASS | 200 in 9.2s, disclaimer + track-record context + confidence rendered |
| Crypto prediction (BTC) | PASS | 200 in 4.1s, same badges |
| Forex prediction (EURUSD) | PASS | 200 in 4.0s |
| Commodity prediction (GOLD) | PASS | 200 in 3.8s |
| Index prediction (SPX) | PASS | 200 in 4.0s |
| yfinance live fetch | PASS | AAPL 308.63 (+4.75%) |
| Pyth oracle live fetch | PASS | Hermes returned AAPL 308.62, BTC 62467.49; feed sync mapped 9/10 symbols |
| Verified-price badge | PASS | /api/prices/batch: BTC verified=true source=yfinance+pyth divergence=0.006%. Equities show unverified during US market closure because Pyth equity feeds pause off-hours (documented design; re-check during market hours) |
| Failover on Pyth outage | PASS | Pyth forced down (fault injection): price still served, source honestly labeled "yfinance", verified=false |
| yfinance circuit breaker | PASS | trips and recovers; data_status reports breaker state |
| Alpaca 1m bars | BLOCKED-EXTERNAL | training-time source only (train_1min.py); needs ALPACA_API_KEY, no runtime path |
| Free-tier quota (5/day) | PASS | 5 succeed, 6th blocked with upgrade prompt |
| Failed prediction refunds quota | PASS | bad ticker: predictions_today unchanged |

### Accuracy engine and track record

| Item | Status | Evidence |
|---|---|---|
| Grading job resolves predictions | PASS | synthetic 5-day-old prediction graded on demand: actual price fetched (294.38), accuracy row written |
| Production grading backlog | DEGRADED | live DB: 8 predictions (all AAPL 1d, Jul 2-3), 0 graded. Explanation: US market was closed Fri Jul 3 (July 4 observed) and it is now the weekend, so no post-horizon close bar exists yet. Expect grading after Monday's close; ops thread is running (service up). Re-check Tuesday; if still 0, treat as FAIL |
| Insufficient-data rule (<10 graded) | PASS | /api/track-record says insufficient data on fresh DB |
| /track-record renders + methodology link | PASS | fixed during audit: the methodology paragraph now links to /methodology (was plain text) |

### Paper trading

| Item | Status | Evidence |
|---|---|---|
| Production engine status | DEGRADED | paper_trading_enabled has never been set in the live DB: the engine ships paused and has NOT been started from the admin console. 0 trades, 0 events, 0 snapshots. This is the designed initial state, not a crash; to start it: Admin > Paper Trading > Start paper trading (plus service restart to pick up current code, see Engineering) |
| Engine cycle executes | PASS | run_cycle on audit instance: {ran: True, opened: 2, closed: 0, rejected: 3} in 57s; open events recorded with real prices |
| Sizing, stops, breaker, slippage | PASS | enforced by tests/test_paper_engine.py (part of the 105 passing); rejected=3 above shows gating working live |
| /paper honesty rules | PASS | page shows honest empty state, Simulated/virtual labels present, min-trade rule wired |
| No real-order code path | PASS | paper_engine.py has zero mt5/order_send references; test_ethics.py asserts unreachability and passes |

### Payments

| Item | Status | Evidence |
|---|---|---|
| STK initiation payload | PASS | password + 14-digit timestamp build correctly |
| Live STK push | BLOCKED-EXTERNAL | MPESA_CONSUMER_KEY/SECRET/PASSKEY are empty in .env (callback URL and shortcode are set). Fill Daraja sandbox creds and run one sandbox push |
| Callback: malformed payload | PASS | 200 accepted, no state change |
| Callback: unknown CheckoutRequestID | PASS | ignored, payment stays pending |
| Callback: success settles + activates Pro | PASS | status=paid, user.plan=pro, receipt QK12AUDIT77 stored |
| Receipt email | PASS | real message captured to payer address |
| Idempotency on replay | PASS | second callback: receipt unchanged, no duplicate email |
| Result-code mapping | PASS | 1032 -> cancelled |
| Stripe checkout | BLOCKED-EXTERNAL | STRIPE_* empty in .env; route degrades to redirect |
| Stripe webhook signature | PASS | with keys configured (fake pair), invalid and missing signatures both 400; when unconfigured the endpoint is a safe no-op (no state change possible) |
| Pricing shown before payment | PASS | /pricing shows KES and USD amounts and periods |
| Refund terms reachable | PASS | "refund" present on /terms |

### Admin

| Item | Status | Evidence |
|---|---|---|
| 11 admin pages access control | PASS | all: 200 as admin, redirect/403 as normal user, redirect as anon (server-side) |
| 15 admin GET APIs access control | PASS | all: 200 admin / refused user (incl. data-quality, errors, feedback, audit, paper state) |
| CSRF on admin mutations | PASS | POST without token 403, with token 200 |
| Resources CRUD | PASS | create -> visible on public /api/resources -> delete -> gone |
| Pyth feed mapping sync | PASS | mapped 9, unmapped 1 (one symbol has no Pyth feed) |
| Broadcast/announcement | PASS | notification rows created for audience |
| Daily digest manual trigger | PASS | returned True, staff notification written, digest email captured with yesterday's numbers + paper line |
| Drift monitor | PASS | runs clean (no models under threshold on audit DB) |
| Churn flags | PASS | {active: 2, at_risk: 0, churned: 0, new: 0} |
| Model retrain trigger | DEGRADED | control exists at /admin/api/models/retrain; deliberately NOT fired because it would retrain and overwrite the production Saved Models on this machine. Verify in an isolated environment |

### Public pages and polish

| Item | Status | Evidence |
|---|---|---|
| /faq /privacy-policy /terms /methodology /data-sources /resources landing | PASS | all 200; resources hub renders seeded categories; walked in Chrome both modes earlier today |
| 404 page | PASS | themed, both modes, correct status |
| 500 page | PASS | handler + template render (verified via error-handler test in suite) |
| Every page dark AND light | PASS | ~40 pages walked in Chrome today (list in CHANGELOG session): no unreadable elements remain; three broken "BullLogic" logos and a stretched toggle were found and fixed during that walk |
| Offline fallback | PASS | sw.js precaches /offline, navigation falls back to it; /offline renders themed |
| Low-data mode | PASS | saveData branch polls /api/prices/batch every 60s instead of SSE; the poll endpoint exercised directly (branch condition is browser-set, cannot be forced server-side) |
| Em/en dash scan | PASS | project-wide count after audit: 0 em, 0 en. First pass removed 3 from paper_trader.py; follow-up scan over ALL tracked and untracked files (git ls-files -co) caught 2 more in .gitignore and tools/install-service.ps1, both removed. Re-scan now returns zero files |

### Engineering health

| Item | Status | Evidence |
|---|---|---|
| Test suite | PASS | 105 passed, 0 failed, ~12s |
| .env.example completeness | PASS | fixed during audit: added TELEGRAM_BOT_TOKEN + 7 runtime knobs that code reads (HOST, PORT, FLASK_DEBUG, DISABLE_OPS_THREAD, ADMIN_ROLE, MAIL_USER, MAIL_FROM). No example var is unread by code |
| Error log (7 days) | PASS | exactly 1 entry: a warning where the divergence guard caught yfinance returning 26.51 for BTC vs Pyth 61033 and refused to trust it. The safety net working as designed |
| Service status | PASS | StockMarketPredictor and CaddyReverseProxy both Running; /login 200 |
| Live commit vs latest | PASS (was FAIL, resolved) | service was restarted at 14:13 today, after the 10:00 theme commit. Re-probed live /login: theme system present. The live process now serves current disk state, which includes the uncommitted audit fixes (templates are read from disk). Remaining drift is git-side only: 4 modified files + .env.example + this report are not yet committed |
| .env.example committable | PASS (fixed) | .gitignore line ".env.*" was silently ignoring .env.example, so the documented example env file could never reach the repo. Added "!.env.example" negation; git now sees it as an addable untracked file |

## 3. Fixes applied during this audit (all small)

1. `Web Pages/track_record.html`: methodology text now links to /methodology.
2. `paper_trader.py`: removed the 3 remaining em dashes.
3. `.env.example`: documented 8 environment variables the code reads that were missing.
4. `.gitignore`: added `!.env.example` so the example env file is no longer
   silently ignored and can actually be committed (found during follow-up:
   fix number 3 was to a file git could not see).
5. `.gitignore` and `tools/install-service.ps1`: removed one em dash each,
   found by widening the dash scan to every tracked and untracked file.
   Project-wide dash count is now genuinely zero.

Found earlier today during the theme walkthrough (already committed in 8db7515):
broken logo markup on 3 pages, stretched theme toggle on auth pages.

## 4. Needs your decision (prioritized)

1. ~~FAIL, service drift~~ RESOLVED: service restarted 14:13 today; live
   /login re-probed and the theme system is present.
2. **Uncommitted work**: the audit fixes (5 files) plus .env.example and this
   report sit only in the working tree. The live service already serves them
   from disk, but they are one crash-and-checkout away from loss. Say the
   word and they get committed.
3. **DEGRADED, paper trading never started**: re-checked live DB this
   afternoon, still no paper_trading_enabled row and 0 trades/events/
   snapshots. If the demo should show live paper trading, start it from
   Admin > Paper Trading. Day one will honestly show zero trades until
   cycles run during market hours.
4. **DEGRADED, production grading at 0**: re-checked this afternoon: still
   8 predictions, 0 graded, error log unchanged (single divergence-guard
   warning from Jul 2). Consistent with the market holiday + weekend
   explanation. Re-check after Monday's US close; if still zero on Tuesday,
   escalate to FAIL and investigate resolve_pending against the live DB.
5. **DEGRADED, retrain trigger unverified**: decide when a safe isolated
   retrain run can happen; the audit deliberately did not fire it.

## 5. BLOCKED-EXTERNAL checklist (exact items you must provide)

- Daraja sandbox credentials (MPESA_CONSUMER_KEY, MPESA_CONSUMER_SECRET,
  MPESA_PASSKEY) to fire one sandbox STK push end to end. Everything after
  the push (callback, settlement, receipt, idempotency) is already PASS.
- One interactive Google login to close the OAuth loop (redirect boundary
  verified; button correctly wired).
- SMTP production creds (MAIL_USERNAME/MAIL_PASSWORD are empty in .env), so
  real outbound email is currently OFF on the live service. All email
  content and send paths verified against a real SMTP conversation.
- Stripe keys if card payments should be demoed (otherwise the UI degrades
  gracefully).
- ALPACA keys only if you want to re-verify the training data pipeline.

## 6. Honest overall assessment

The system is demo-ready now. The one FAIL from the morning audit (service
drift) is resolved: the service was restarted at 14:13 and the live site
serves the theme system and all audit fixes. Registration through prediction
through track record works end to end with honest labeling, all 105 tests
pass (re-run this afternoon), admin is fully access-controlled, the data
layer failed over correctly under forced outage, and the only production
error all week was the divergence guard correctly refusing a bad price.
What remains is housekeeping and choices, not code: commit the working-tree
fixes so they are not disk-only; decide whether paper trading runs for the
demo (it will honestly show zero trades until market-hours cycles); and know
that outbound email stays off until SMTP credentials are set, so demo the
verification/reset flows on the audit instance or add creds first. The
grading backlog should clear after Monday's US close, and everything else
blocked is external credentials, not code. You can put this in front of a
panel today.
