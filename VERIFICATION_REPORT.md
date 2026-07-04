# BullLogic Verification Report

Date: 2026-07-04 (updated twice same day: afternoon follow-up, then a live
integration session that took SMTP, Google OAuth and M-Pesa Daraja sandbox
from BLOCKED-EXTERNAL to PASS with real end-to-end traffic)
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
| Google OAuth full flow | PASS (live) | real sign-in completed from the public HTTPS tunnel after the ProxyFix/waitress fix; login.google activity recorded, session established |
| Google OAuth account linking | PASS (live) | signing in with an email that already had a password account linked it (google_sub set on the existing row, email stays verified); no duplicate account created. Confirmed for two existing accounts |
| OAuth scheme behind proxy | PASS (fixed) | pre-fix probe through the HTTPS tunnel produced redirect_uri=http://... (captured live); after adding ProxyFix (app.py) AND waitress trusted_proxy (wsgi.py, waitress strips X-Forwarded-* from untrusted peers by default) the same probe returns https://... |
| Password reset anti-enumeration | PASS | identical 200 + identical body for existing vs unknown email |
| Reset email sent | PASS | captured via SMTP sink, link extracted |
| Reset link sets new password | PASS | login with new password works |
| Reset token single-use | PASS | second use does not change password |
| Reset kills other sessions | PASS | parallel session 200 -> 302 login after reset (session_token rotation) |
| Theme saves to DB, survives logout/login | PASS | data-theme="light" server-rendered after fresh login |
| Theme on every page, no white flash | PASS | verified in Chrome earlier today: ~40 pages in both modes, blocking boot script in head, account-beats-localStorage proven live |
| Data export | PASS | /account/export returns JSON (fresh account, 235 bytes; grows with data) |
| Account deletion | PASS (re-proven live) | both audit test accounts deleted through POST /account/delete on the live service: 400 without confirm, deleted with confirm, login rejected after. Payment records correctly retained as financial history |
| SMTP on the LIVE service | PASS (live) | Gmail app password configured in .env (never committed). Raw Flask-Mail send accepted by smtp.gmail.com and received. Full registration on live /register: verification email received, link clicked, email_verified flipped, prediction then ran and recorded. Password reset end to end on a real account: emailed token set a new password, sessions rotated, replayed token rejected. Resend limit live: [200,200,200,429] |

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
| Production engine status | PASS (started live) | started from Admin > Paper Trading during the integration session: paper_trading_enabled=1, started_at recorded, "engine started" toggle event written. Zero trades is honest: enabled on a Saturday, first cycles run during Monday market hours. NOTE: the first two start attempts silently went nowhere because the user-facing /mt5 page has its own differently-scoped "paper trading" button (mt5_trading.py, separate $10k simulator); see flags below |
| Engine cycle executes | PASS | run_cycle on audit instance: {ran: True, opened: 2, closed: 0, rejected: 3} in 57s; open events recorded with real prices |
| Sizing, stops, breaker, slippage | PASS | enforced by tests/test_paper_engine.py (part of the 105 passing); rejected=3 above shows gating working live |
| /paper honesty rules | PASS | page shows honest empty state, Simulated/virtual labels present, min-trade rule wired |
| No real-order code path | PASS | paper_engine.py has zero mt5/order_send references; test_ethics.py asserts unreachability and passes |

### Payments

| Item | Status | Evidence |
|---|---|---|
| STK initiation payload | PASS | password + 14-digit timestamp build correctly |
| Daraja OAuth token | PASS (live) | mpesa._get_token() returned a real sandbox access token with the configured consumer key/secret |
| Callback URL internet-reachable | PASS (live) | POST from the public internet through the ngrok tunnel answered {"ResultCode":0} |
| Live STK push | PASS (live) | sandbox creds configured; real push ws_CO_04072026163410644710000898 delivered to the owner's handset via POST /mpesa/pay as a logged-in user |
| Live settlement | PASS (live) | PIN entered on phone; Daraja callback landed through the tunnel; payment flipped to paid with real receipt UG4D8A21O0; Pro activated for exactly 30 days |
| Receipt email (live) | PASS | receipt delivered to the payer inbox (original arrived delayed; a synchronous re-send confirmed the SMTP path clean) |
| Idempotency (live) | PASS | forged duplicate callback with same CheckoutRequestID and a different receipt number: 200 ack, receipt and expiry unchanged |
| Cancelled prompt (live) | PASS | second push cancelled on the handset: callback mapped 1032 to status=cancelled; admin transactions shows it |
| Status polling fallback (live) | PASS | /mpesa/status queried Daraja directly and mapped 1032 ("You cancelled...") and updated the row |
| Timeout (live) | PASS | fourth push with handset unreachable: result 1037 mapped to "No response from your phone", payment status=failed |
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
6. `app.py`: added ProxyFix (one trusted hop) so X-Forwarded-Proto/Host from
   the local reverse proxy produce correct https URLs.
7. `wsgi.py`: waitress now trusts X-Forwarded-* from 127.0.0.1; by default
   waitress strips these headers from untrusted peers, which starved ProxyFix
   entirely (proven live: redirect_uri stayed http until this second fix).
   Together 6+7 fixed the OAuth redirect scheme and payment callback URLs
   behind Caddy/ngrok.

Found earlier today during the theme walkthrough (already committed in 8db7515):
broken logo markup on 3 pages, stretched theme toggle on auth pages.

## 4. Needs your decision (prioritized)

1. **FLAG, "paper trading" naming collision**: the user-facing /mt5 page has
   Connect Paper Account / Start buttons (mt5_trading.py, its own $10k
   simulator) that are easy to mistake for the admin paper engine; even the
   owner started the wrong one twice during this session. Renaming one of
   them is a product decision, deliberately not touched.
2. **FLAG, tunnel-dependent public URL**: Google's registered redirect URI
   and MPESA_CALLBACK_URL both point at the ngrok domain
   (outclass-umbilical-outfield.ngrok-free.dev). If the tunnel restarts on a
   different domain, the public OAuth flow and M-Pesa callbacks break until
   the Console and .env are updated. Production wants a stable domain (and
   Brevo with domain verification for mail, see checklist).
3. **ROTATE two passwords**: the account 'kip' was password-reset during the
   3c test and that password appeared in the session transcript; change it
   from the profile page. The Gmail app password also transited the chat;
   revoke and re-issue at myaccount.google.com/apppasswords if that bothers
   you (one-line .env update afterwards).
4. **DEGRADED, production grading at 0**: unchanged all day (8 predictions,
   0 graded), consistent with the July 4 holiday weekend. Re-check after
   Monday's US close; if still zero on Tuesday, escalate to FAIL and
   investigate resolve_pending against the live DB.
5. **DEGRADED, retrain trigger unverified**: decide when a safe isolated
   retrain run can happen; the audit deliberately did not fire it.

## 5. BLOCKED-EXTERNAL checklist (exact items you must provide)

- ~~Daraja sandbox~~ DONE: live sandbox STK pushes verified end to end
  today (paid, cancelled, timeout).
- ~~Google OAuth~~ DONE: live sign-in and account linking verified from the
  public HTTPS URL.
- ~~SMTP~~ DONE: Gmail app password live; verification, reset, receipt and
  rate-limit flows all proven with real email. Production upgrade path:
  Brevo with domain verification (swap MAIL_SERVER/USERNAME/PASSWORD).
- Stripe keys if card payments should be demoed (otherwise the UI degrades
  gracefully). Still the only untested payment provider.
- ALPACA keys only if you want to re-verify the training data pipeline.
- Daraja PRODUCTION credentials (Go-Live approval) remain external for real
  money; everything up to that boundary is now proven in sandbox.

## 6. Honest overall assessment

The system is demo-ready, and as of tonight the demo can be entirely real:
registration sends real verification email, password reset works with real
mail, Google sign-in works from the public HTTPS URL including the
account-linking edge case, and M-Pesa sandbox payments run the full arc on a
real handset: STK push, PIN, callback, settlement with a real receipt
number, Pro activation, receipt email, idempotent against replays, with
cancelled and timeout paths mapped to honest user messages. The paper
trading engine is enabled and will honestly accumulate its first trades
during Monday market hours. All 105 tests pass after the proxy fixes. Three
knowable caveats for a panel day: the public URL is an ngrok tunnel, so keep
that window open (or invest in a stable domain); the grading backlog clears
after Monday's US close; and Stripe remains the one unproven payment path,
hidden gracefully without keys. Rotate the two passwords noted above and
this is presentable with live integrations, not mocks.
