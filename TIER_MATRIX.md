# BullLogic — Free / Plus / Pro Tier Matrix

This is the source of truth for what Free, Plus, and Pro accounts get. Two
columns matter for every row: **Enforced today** (what the running code
actually does, verified against the routes below) and **Planned** (what
we intend to build toward). Do not treat "Planned" as already true —
several rows below started life as assumptions that turned out not to
match the code, which is why this file insists on the distinction.

`User.plan` is `free|plus|pro|enterprise`. `User.is_plus` is true for
`plus`, `pro`, and `enterprise` (i.e. "at least Plus"); `User.is_pro` is
true only for `pro` and `enterprise`, unchanged from before Plus existed -
features gated on `is_pro` stay Pro/Enterprise-exclusive even for Plus
subscribers.

## Currently enforced (verified against the code)

| Feature | Free | Plus | Pro | Enforced in |
|---|---|---|---|---|
| Daily predictions | 5/day (`FREE_DAILY_LIMIT`) | Unlimited | Unlimited | `utils.consume_quota`, `models.User.predictions_remaining` (`is_plus`) |
| Multi-timeframe confluence (`/api/mtf/<ticker>`) | Blocked | Yes | Yes | `routes/predictions.py` (`is_plus` check) |
| Backtester (`/api/backtest`) | **Blocked entirely** | 1 run/day, `6mo`/`1y` history only (`PLUS_BACKTEST_DAILY`, `PLUS_BACKTEST_PERIODS` in `utils.py`) | Unlimited runs, `1d`/`1h` interval and `6mo`/`1y`/`2y` history | `routes/trading.py` |
| MT5 connect/start/stop/status, REST API keys, Quick-Trade API | Blocked | **Blocked** (Plus does not include MT5/API access) | Yes | `routes/trading.py` (`@pro_required` / inline `is_pro`), `routes/auth.py` |
| Paper trading, platform demo (`/paper`) | Full read/write access | Full access | Full access | `routes/paper.py` (no gate at all - paper mode is simulated money, open to everyone) |
| Paper trading, own portfolio (opt-in, `/api/paper/opt-in`) | Open, login only | Open, login only | Open, login only | `routes/paper.py` - no plan gate, deliberately (see `PAPER_TRADING_PHASE2_DESIGN.md`) |
| Trader leaderboard (`/traders`, `/api/leaderboard/users`) | Open, login only | Open, login only | Open, login only | `routes/paper.py`, `routes/api.py` - real per-user Sharpe ranking, no plan gate |
| Admin console | N/A - separate `role` field, unrelated to `plan` | N/A | N/A | `routes/admin.py` |

Billing: `routes/payments.py` grants/extends a tier via `_grant_plan(user,
tier, days)`, called from Stripe checkout/webhook and M-Pesa
settlement/promo-code redemption. Stripe distinguishes Plus vs Pro by
which of the four `STRIPE_PRICE_ID_*` env vars was used (mapped in
`_STRIPE_TIER_PRICES`) and threads the tier through via checkout/session
metadata (`subscription_data.metadata.tier`) since Stripe subscription
webhook events don't otherwise carry it. M-Pesa distinguishes tiers by a
`tier` field in the `/mpesa/pay` request body, persisted on `Payment.tier`
so the async callback/status-poll settlement path knows which plan to
grant. Gift codes (`GiftCode`/`_grant_pro`) still only ever grant Pro.

## Currently NOT restricted by plan at all (open to every logged-in user, any tier)

Verified by absence of any `is_pro`/`pro_required` check in the route:

| Feature | Where |
|---|---|
| Timeframe choice on charts/predictions (1m through 1W) | `/predict`, `/api/chart/<ticker>`, `/api/candles/<ticker>` |
| Asset class (stocks, ETFs, crypto, forex, commodities, indices) | same routes above |
| Watchlist size | `routes/predictions.py` (`WatchlistItem` model - note a second, unused `Watchlist` model also exists in `models.py`, dead code, do not query it) |
| Price alerts count | `routes/notifications.py` (`PriceAlert`) |
| Trade journal entries | `routes/portfolio.py` (`TradeJournal`) |
| Scanner (volume, short-squeeze, sector heatmap) | `routes/analytics.py` |
| Screener, Calendar, Fear & Greed, Correlation, Monte Carlo, Sentiment, Feature Importance, Short Interest, Options, Dividends, Insiders | `routes/analytics.py` |
| AI analyst commentary (`/api/ai/analyze/<ticker>`) | `routes/predictions.py` - gated only on whether an API key is configured server-side, not on user plan |
| API key creation (`/api/keys/create`) | `routes/auth.py` |
| Prediction history export (`/history/export`) | `routes/predictions.py` |
| Chart indicator overlays (SMA20/50, EMA12/26, Bollinger Bands, Volume) | `Web Pages/result.html` - BB and Volume are already free for everyone today; there is no MACD overlay toggle at all currently (MACD only shows as a stat) |

**`/account/export`** (full personal-data export, `routes/predictions.py`) is
explicitly excluded from any future Pro gate regardless of what else changes
here - it exists for account portability, and paywalling a user's access to
their own data is a legal/ethics problem independent of subscription tier.

## Planned (not yet built - needs an explicit decision before shipping)

Every row above marked "not restricted at all" currently has **no limit**
for existing free accounts. Turning any of these into a hard cap is a
retroactive restriction on accounts that signed up under the current,
unlimited behavior - which is the exact "bait-and-switch" pattern most
consumer-protection and platform-fairness rules (and simple fairness to
existing users) warn against. Before any of the below ships, a decision
is needed on scope:

- Apply the new cap to everyone immediately (simplest, higher risk for
  existing users who already exceed the new cap), **or**
- Grandfather existing usage (existing users keep what they have, can't
  grow past the new cap; new signups get the cap from day one), **or**
- Leave a given row unrestricted indefinitely and only enforce it for
  genuinely new features going forward.

Candidate caps, not yet implemented:

| Feature | Proposed Free cap | Proposed Pro |
|---|---|---|
| Timeframe access | 1D, 1W only | All (1m-1W) |
| Asset classes | Equities, ETFs | + crypto, forex, commodities |
| AI analyst calls | 1/day | Unlimited |
| Watchlist size | 10 tickers | Unlimited |
| Price alerts | 3 active | Unlimited |
| Journal entries visible | Last 10 | Full history |
| Scanner | Current filters | + saved presets |
| API key creation | Not allowed | Allowed, rate limited |
| `/history/export` | Not allowed | Allowed |
| Chart indicators | SMA, EMA | + Bollinger Bands, Volume (already free today - would need to become a genuine new restriction to change) |

The backtester row that used to live here shipped: Free stays blocked
(unchanged, not loosened), Plus gets 1 run/day up to 1yr history, Pro keeps
unlimited runs up to 2yr - see the enforced table above.

## Pricing

See `/pricing` (`routes/payments.py`) for the authoritative KES amounts;
do not duplicate specific prices here where they can drift out of sync.
