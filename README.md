# BullLogic

BullLogic — AI-powered trading intelligence platform for retail traders.
Freemium subscriptions, M-Pesa payments, MT5 algorithmic trading, and
multi-model ML predictions across 76 tickers.

Stock market prediction and paper-trading platform, powered by the
Triple Fusion prediction engine (ICT structure + machine learning +
technical analysis). Built as a Flask web application with user
accounts, subscriptions, and a verified M-Pesa/Stripe payment stack.

Every claim in this README is limited to what has been verified by
execution. The full per-feature audit lives in
[FEATURE_TRUTH_MAP.md](FEATURE_TRUTH_MAP.md); the ensemble evaluation
(including its negative result) lives in
[ENSEMBLE_REPORT.md](ENSEMBLE_REPORT.md).

---

## Working today (verified end to end)

- **ML price predictions** for 60+ ticker/interval combinations across
  equities, crypto, forex and commodities: Linear Regression + Random
  Forest voting (plus an LSTM vote on AAPL daily), with ATR-derived
  stop-loss/take-profit levels and confidence from vote agreement.
- **Honest accuracy tracking**: every prediction is stored, later graded
  against the realized price, and published on the public
  `/track-record` page. Nothing is cherry-picked.
- **Paper trading engine**: virtual portfolio trading two signal streams
  head to head with realistic spread/slippage/commission, risk limits,
  a daily loss circuit breaker, and an append-only audit trail. It has
  produced real (simulated-money) trades on this install. Any user can
  also opt into their own isolated version of the same engine (own
  balance, own positions, own risk gates) and appear on a real, Sharpe-
  ranked trader leaderboard at `/traders` - see
  PAPER_TRADING_PHASE2_DESIGN.md.
- **XP, levels, and daily streaks**: predictions, backtests, and paper
  trade outcomes award XP (`utils.award_xp`); level is derived from XP,
  never stored. A daily activity streak advances on any authenticated
  request, once per calendar day, with a bonus every 7th consecutive day.
- **User accounts and billing**: registration with email verification,
  Google OAuth sign-in, password reset, Free/Plus/Pro tiers, Stripe
  checkout, and M-Pesa Daraja STK Push (verified live in the sandbox end
  to end: push, PIN entry, callback, receipt, Pro activation). See
  TIER_MATRIX.md for exactly what each tier is gated to in code.
- **Risk management library** (`risk_manager.py`): Kelly-criterion
  sizing, ATR trailing stops, tiered drawdown reduction with a 20% halt,
  daily-loss breaker with cooling-off, correlation checks. 74/74 tests.
- **Verified market data**: yfinance quotes cross-checked against the
  Pyth oracle with divergence warnings and automatic failover.
- **Technical analysis + TradingView charts**, watchlists with live
  signals, screener, scanner, research pages, admin console.

## Safety: live trading is off by default

Real order execution (MetaApi or a direct MT5 bridge) is **refused
everywhere** unless an operator explicitly sets `ENABLE_LIVE_TRADING=true`
in the environment. The default is off, no broker credentials ship with
the project, and `tests/test_mt5_safety.py` asserts that paper trading
is the only active execution path. Paper trading needs no flag.

## Experimental / in progress (not yet real features)

These exist as tested libraries or scaffolds but are NOT wired into the
product, and their API endpoints label their responses
`"simulated": true` where demonstration data is returned:

- **Stacking ensemble (XGBoost + LightGBM + Ridge meta-learner)**: the
  trainer runs and is evaluated in ENSEMBLE_REPORT.md, but on held-out
  data it did not beat the best single model and its artifacts are not
  compatible with the live feature pipeline, so it is not deployed.
- **Walk-forward framework**: purged/embargoed splits and fold metrics
  are real; per-fold model evaluation is not implemented yet (the fold
  backtest currently runs a fixed SMA crossover and says so loudly).
- **Sentiment analysis**: the financial lexicon scorer is real; NewsAPI
  integration requires a `NEWSAPI_KEY`; the Reddit component is a
  placeholder model and is flagged as simulated in every payload.
- **Economic calendar**: a curated static list of real 2026 events
  (FOMC/NFP/CPI) with volatility warnings; not a live feed.
- **Gamification**: competition/achievement engine works in memory with
  tests, but competitions and trader leaderboards in the API are
  demonstration data and no achievements are awarded automatically yet.
- **Smart order router (TWAP/VWAP/Iceberg)**, **message bus
  (Redis/in-memory)**, **data quality monitor**: tested libraries,
  nothing in the running app calls them yet.
- **Model versioning** (`db_utils.py`): migration runner works; version
  records are not persisted yet and rollback does not exist.
- **Docker/microservices** (`docker-compose.yml`, `predictor_api.py`):
  compose files and a standalone prediction API exist but have not been
  verified end to end in this audit.

---

## Architecture

```
data_pipeline.py       ->  featured datasets (TA + ICT features)
model_training.py      ->  Saved Models/ (LR + RF per ticker/interval)
predictor.py           ->  shared inference: multi-model vote, SL/TP, confidence
app.py + routes/       ->  Flask web app (auth, predictions, payments, admin)
paper_engine.py        ->  virtual portfolio, audited simulated trading
mt5_trading.py         ->  trading engine (paper by default; live is env-gated)
ops.py                 ->  background jobs: accuracy grading, digests, paper cycles
```

## Setup

Requirements: Python 3.10-3.12 (this project's venv uses 3.11).

```bash
python -m venv .venv
.venv\Scripts\activate       # Windows
source .venv/bin/activate    # Mac/Linux
pip install -r requirements.txt

cp .env.example .env         # fill in secrets

python app.py                # http://127.0.0.1:5000
```

Training pipeline (regenerates models):

```bash
python data_pipeline.py                        # build featured datasets
python train_all_tickers.py --tickers QQQ      # train through the live feature builder
```

Tests:

```bash
python -m pytest tests/ -q
```

## Hosted server access

The app runs as a persistent service on a private server, reachable via
Tailscale VPN:

| Access | URL |
|---|---|
| HTTPS (recommended) | https://kali.tail3ceaef.ts.net |
| Direct IP | http://100.116.236.84:5000 |

Requires Tailscale connected to the `kipkiruikelly.github` tailnet.

## Trading options

- **Paper trading (default, recommended)**: connect instantly in the MT5
  page's Paper tab; $10,000 virtual balance against live prices.
- **Live trading (opt-in only)**: requires an operator to set
  `ENABLE_LIVE_TRADING=true`, plus MetaApi credentials or a Linux MT5
  bridge. Without the flag every live order path refuses.

## Configuration

Settings are centralized in `config.py` (Pydantic) with
development/staging/production presets; secrets and overrides live in
`.env` (gitignored, template in `.env.example`).

## Disclaimer

Predictions and trades generated by this system are for **educational
purposes only**. They do not constitute financial advice. Past
performance does not guarantee future results. Never risk capital you
cannot afford to lose.
