# Strategy Assumptions, Paper Trading Engine

Everything in this document describes a simulation. All money, balances,
positions and P&L are VIRTUAL. The engine never places, suggests placing,
or connects to real-money orders, and a test (tests/test_paper_engine.py)
asserts that no broker/order code is reachable from the paper system.

Simulated performance does not guarantee real results.

## The virtual account

- Starting balance: 1,000,000 KES, virtual. Configurable.
- Prices from yfinance are used as-is and treated as KES-denominated
  simulation units. No FX conversion is applied; the account currency is a
  label for familiarity, not an exchange-rate model.
- Two strategies run against separate virtual books so ML and quant rules
  can be compared head to head:
  - ml_ensemble: the platform's LR + RF model vote (same models the app
    shows users), entered only at or above a minimum confidence.
  - alpha_rules: the alphas.py composite score with cross-sectional
    ranking across the tracked universe and a Pyth oracle confidence
    filter.

## Fills and friction

Fantasy fills make every backtest look good, so the engine charges
friction on both sides of every trade:

- Spread/slippage: each fill moves spread_bps (default 5 bps) against the
  trade. Entries buy above / sell below the observed market price; exits
  do the reverse.
- Commission: commission_bps (default 10 bps) of notional per side.
- The observed market price, its source (yfinance, yfinance+pyth, or
  pyth), and the timestamp are recorded on every trade for audit.

Known simplifications, stated honestly:

- Fills assume the full size executes at the quoted price plus the fixed
  friction estimate. Real books have depth; large orders would move the
  market more.
- Stops and targets are checked once per engine cycle (about every 15
  minutes) against the latest quote, not tick by tick. A price that
  spikes through a stop and recovers between cycles will not trigger it,
  and gaps fill at the observed quote, which can be worse or better than
  the stop level. Overnight and weekend gaps are inherent to this.
- US exchange holidays are not modeled; the market-hours gate is a fixed
  weekly schedule (equities/ETFs weekdays 13:30 to 20:00 UTC, forex and
  commodities Sunday 22:00 UTC to Friday 21:00 UTC, crypto 24/7). Outside
  those windows the engine neither opens nor closes positions in that
  class.

## Risk rules (all visible on /paper/rules)

- Position sizing: qty = (equity x risk_pct) / (ATR14 x stop_atr_mult).
  Hitting the stop loses risk_pct (default 1%) of the virtual equity.
- Stop distance: ATR14 x 1.5. Target distance: ATR14 x 2.5.
- Exits: stop hit, target hit, opposite signal (reversal), or max holding
  period (default 240 hours). Priority order: stop, target, reversal,
  timeout.
- Max concurrent positions per strategy (default 5).
- Max exposure per asset class (default 40% of equity, entry notional).
  Entries that would exceed the cap are scaled down to the remaining
  budget, or rejected when the remainder is negligible.
- Daily loss circuit breaker: when mark-to-market equity falls more than
  daily_loss_breaker_pct (default 5%) below the day's first snapshot, new
  entries pause for the rest of the UTC day. Exits keep running.

## Honesty rules (same as the prediction accuracy engine)

- Trades are append-only. A trade is inserted at open; exit fields are
  written exactly once at close; nothing is ever edited or deleted, and
  every action appends an audit event.
- Nothing is seeded or backfilled. Day one starts with zero trades.
- Below 10 closed trades a strategy reports "insufficient data" instead
  of unstable ratios. Profit factor with zero losses reports as
  undefined, not infinity. Zero-variance equity reports no Sharpe.
- Every P&L figure in the UI is labeled simulated, and public pages carry
  the disclaimer that simulated performance does not guarantee real
  results.

## Alpha framework validation

- Every alpha states its hypothesis in its docstring and obeys a strict
  causality contract: the score at time t uses only data at or before t.
  tests/test_alphas.py recomputes every registered alpha on truncated
  history and asserts identical values (the no-lookahead test).
- Alpha strength is measured by the information coefficient (Spearman
  correlation of the signal with the next-period return) evaluated
  walk-forward on out-of-sample windows only.
- Composite weights derived from ICs floor negative-IC alphas to zero
  (removed, not sign-flipped) to avoid overfitting.
- ML retraining uses a chronological train/test split with a gap, and the
  XGBoost cross-validation purges the last bars of each training fold so
  forward-looking labels cannot leak into validation.

## Metrics definitions

- Total return: last equity vs starting balance.
- Sharpe: mean daily equity return / std (ddof=1), annualized by sqrt(252).
- Sortino: same but using downside deviation only.
- Max drawdown: largest peak-to-trough decline of the equity curve.
- Win rate: closed trades with positive net P&L / all closed trades.
- Profit factor: gross wins / gross losses.
- Exposure: open entry notional / current equity.
- Turnover: cumulative entry notional of closed trades.

## Operations

- The engine runs inside the existing ops background thread, one cycle
  about every 15 minutes: exits first, then entries, then an equity
  snapshot per strategy.
- Start/pause: Admin console > Paper Trading (role admin), or set the
  AppSetting paper_trading_enabled to "1"/"0". The engine ships paused.
- The daily staff digest includes a simulated P&L summary line once the
  engine has started.
