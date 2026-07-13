# Investor Readiness Audit

Audit and fixes performed 2026-07-13 ahead of angel investor outreach.
Companion documents: FEATURE_TRUTH_MAP.md (per-feature verification),
README_TESTS.md (test status), TIER_MATRIX.md (tier gating).

## Fixed Automatically

| File | Change |
|---|---|
| README.md | Opens with the investor-facing platform description; "76 tickers" verified against the 574 trained models in Saved Models (76 unique tickers). |
| .gitignore / git index | .DS_Store removed from git tracking (it was committed); already ignored going forward. |
| app.py | /health now returns a version field alongside status and uptime, as PaaS health checks expect. |
| app.py | Security headers on every response: X-Content-Type-Options, X-Frame-Options, X-XSS-Protection, Referrer-Policy. |
| app.py | Startup log line states plainly whether live trading is enabled or disabled. |
| routes/trading.py, Web Pages/mt5.html | The /mt5 dashboard shows a persistent banner: red "LIVE TRADING ENABLED" or yellow "paper mode only", driven by the same ENABLE_LIVE_TRADING flag that gates execution. |
| tests/test_mt5_safety.py | Two new tests lock the banner to the flag state (10/10 passing). The execution gate itself was already enforced at every connect and order path. |
| routes/predictions.py | Authenticated users land on a real dashboard at / (aliased at /dashboard) instead of the Predict page; the Predict workstation moved to GET /predict with all POST flows unchanged. |
| Web Pages/home.html | Dashboard shows plan tier, quota, predictions today/all-time, watchlist, paper balance from real equity snapshots, recent predictions, quick links (Predict, MT5, Paper, Leaderboard, Track Record), role-gated admin card, and an onboarding empty state for new accounts. No fabricated numbers anywhere. |
| Web Pages/_navbar.html and 5 other pages | Home tab added; every "run a prediction" link now points at /predict. |
| routes/api.py | All demonstration payloads (via _json_simulated) now carry data_source="simulated" in addition to the existing simulated=true and human-readable note. |
| sentiment.py | The placeholder reddit sentiment component carries data_source="simulated". |
| Web Pages: index, result, history, macro, profile, watchlist, market, landing | Every static ticker strip, index card, and demo modal now shows a visible DEMO DATA badge; the Market Overview modal no longer claims Yahoo Finance sourcing for hardcoded numbers. |
| tests/test_honesty_flags.py | The data_source="simulated" contract is now test-enforced for all demo endpoints. |
| CONTRIBUTING.md | New: dev setup, test instructions, code style rules, issue guidelines, honesty and safety invariants. |
| README_TESTS.md | Current status section: 435 tests, 435 passing, last run 2026-07-13. |

Test suite after all changes: 435 passed, 0 failed.

## Requires Developer Action

```
[ ] ACTION: Set the GitHub repository About description
    WHY: It is the first thing an investor sees when browsing the repo.
    HOW: Repo page > gear icon next to About, or install GitHub CLI and run:
         gh repo edit kipkiruikelly/Triple-Fusion-Engine --description
         "BullLogic - AI-powered trading intelligence platform for retail
         traders. Freemium subscriptions, M-Pesa payments, MT5 algorithmic
         trading, and multi-model ML predictions across 76 tickers."

[ ] ACTION: Register a real domain (e.g. bulllogic.co.ke) and serve over HTTPS
    WHY: A tunnel or bare-IP demo signals a hobby project; a domain with TLS
         signals a product. OAuth and M-Pesa callbacks also need a stable URL.
    HOW: Register via a KE registrar (e.g. Truehost, HostPinnacle, Safaricom
         domains), point DNS at the host, terminate TLS with Caddy (already
         the assumed proxy in app.py), then set SECURE_COOKIES=true and
         update GOOGLE redirect URIs and MPESA_CALLBACK_URL.

[ ] ACTION: Replace the demo data endpoints with live sources
    WHY: Everything is now honestly labeled DEMO DATA, but investors doing
         product due diligence will still see badges where live data should be.
    HOW: The verified quote layer already exists (market_data.get_quotes_verified).
         Wire it into: the static ticker strips (index, result, history, macro,
         profile, watchlist), market.html index cards, /api/market/movers,
         /api/portfolio and /api/portfolio/equity-curve (real per-user paper
         equity exists in PaperEquitySnapshot), /api/activity/recent, and
         /api/competitions. Remove each badge only when its widget goes live.

[ ] ACTION: Recruit real beta users and (ideally) first paying subscribers
    WHY: Traction is the single strongest signal for angels; the M-Pesa stack
         is verified in sandbox but zero production payments is a gap.
    HOW: Move MPESA_ENV to production with a registered paybill/till, onboard
         a small beta cohort (the free tier plus /traders leaderboard is the
         hook), and track signups/conversions in the admin console.

[ ] ACTION: Register the business entity and sort the regulatory posture
    WHY: Angels invest in companies, not repos. A trading-signals product in
         Kenya also needs a defensible position with respect to CMA rules.
    HOW: Register (BRS eCitizen), then get written advice on whether the
         product as marketed requires CMA licensing or only the current
         disclaimers (/disclosures page already exists and helps here).

[ ] ACTION: Provision production credentials in .env
    WHY: Several features silently degrade or stay off without them.
    HOW: Fill in on the production host (never commit .env):
         - SECRET_KEY: long random value (required outside debug)
         - DATABASE_URL: managed Postgres for production (SQLite is dev-only)
         - MPESA_*: production consumer key/secret, shortcode, passkey,
           callback URL
         - STRIPE_*: live keys and price IDs if card payments are wanted
         - GOOGLE_CLIENT_ID/SECRET: production OAuth origin + redirect URI
         - MAIL_*: production SMTP (email verification and alerts need it)
         - ANTHROPIC_API_KEY (and/or DEEPSEEK_API_KEY): AI analyst feature
         - NEWSAPI key: without it, sentiment rests on the simulated reddit
           component and is flagged accordingly
         - METAAPI_TOKEN/ACCOUNT_ID: only if offering hosted MT5; leave
           ENABLE_LIVE_TRADING=false until a real compliance review

[ ] ACTION: Clean up working-tree stragglers before showing the repo
    WHY: Stray files look unmaintained in a due-diligence clone.
    HOW: Delete or ignore out.txt and test_app2.py at the repo root; commit
         or stash the remaining uncommitted work-in-progress files
         (models.py, mpesa.py, paper_engine.py, utils.py, routes/paper.py,
         routes/payments.py, several Web Pages, FEATURE_TRUTH_MAP.md,
         TIER_MATRIX.md, .env.example, Static Files/index.css,
         Web Pages/traders.html, PAPER_TRADING_PHASE2_DESIGN.md).
```
