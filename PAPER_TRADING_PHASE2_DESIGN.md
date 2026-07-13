# Per-user paper trading + real leaderboard (Phase 2 design note)

Scope: `paper_engine.py` only, per the files named for this phase.
`mt5_trading.py`'s MT5 Paper tab (a separate, singleton-based simulator with
its own known concurrency bug) is untouched and remains a separate,
not-yet-scheduled effort.

## Decision 1: structural shape of per-user portfolios

**Extend the existing two-strategy engine to be multi-tenant, rather than
building a second, separate portfolio system.** Concretely:

- `PaperTrade`, `PaperTradeEvent`, `PaperEquitySnapshot` gain a nullable
  `user_id`. **`NULL` means the existing platform-wide demo stream** (the
  public `/paper` page, its track record, and every existing test are
  unaffected - this is the same reserved-sentinel approach already used for
  `Payment.tier` defaulting to "pro" on legacy rows).
- A non-null `user_id` is a real user's own isolated portfolio: their own
  starting balance (KES 1,000,000, unchanged - not the $10,000 figure
  `mt5_trading.py`'s unrelated simulator uses), their own open positions,
  their own exposure/breaker/risk gates, their own append-only event log.
- **Signal generation stays shared, portfolio bookkeeping becomes
  per-user.** `ml_signals()`/`alpha_signals()` are computed once per ops
  cycle from the admin-configured ticker list - recomputing per user would
  be wasteful and signals don't depend on who's holding the position.
  `try_open`/`close_trade`/`open_positions`/`class_exposure`/
  `breaker_tripped`/`realized_equity`/`mark_to_market` all gain an optional
  `user_id=None` parameter and filter by it, so every existing call site
  (and every existing test) keeps working unchanged by default.
- Each opted-in user runs **both** `ml_ensemble` and `alpha_rules` under
  their own account, mirroring the platform demo's own "two strategies
  head to head" framing - lets a user see which approach works better for
  *them*, which fits the "encourage learning" goal directly.
- Participation is **opt-in**, not automatic for every registered account
  (`User.paper_trading_opted_in`). Every ops tick already iterates all open
  positions across the platform; doing that for every registered user
  regardless of engagement would scale cycle cost with total signups
  rather than active users. Opting out pauses new entries for that user but
  existing open positions still get exit-checked normally (same philosophy
  the daily-loss breaker already uses: "new entries pause, exits keep
  running") - so opting out never strands an open position.

## Decision 2: leaderboard ranking metric

**Sharpe ratio, computed by the exact same `paper_engine.compute_metrics()`
already used for the platform's own public strategy reports** - not a new
formula, not `gamification.py`'s `CompetitionEngine` (see Decision 3).

- Ranked rows are `(user, strategy)` pairs, so a user's ML and alpha-rules
  performance are both visible rather than blended or hidden.
- A row is only eligible once it has `>= MIN_TRADES` (10) closed trades -
  the same "insufficient data" honesty gate the engine already enforces
  everywhere else, so one lucky trade can't top the board.
- Total return % and win rate are shown alongside as context but Sharpe is
  the sort key, because it's return *relative to volatility*.
- This is safe against reckless sizing by construction, not just by
  ranking choice: position size is never user-chosen. `try_open` sizes
  every trade off `cfg["risk_pct"]` (a shared, admin-set % of the user's
  own equity) and ATR-derived stop distance - there is no field anywhere a
  user can inflate to bet bigger. A user can only change *which signals
  they act on* (by which strategies they opt into), never *how much*.

## Decision 3: tying into Phase 1's XP/streak system

No new/parallel scoring system. `utils.award_xp()` (Phase 1) is called
directly from `paper_engine.py`:

- **+3 XP** when a user's own trade opens.
- **+15 XP** when a user's own trade closes profitably.
- **+3 XP** when it closes at a loss (still rewards completing the
  learning loop - seeing a loss through to a graded exit - just far less
  than a win, so it can't be farmed by opening and immediately eating small
  losses for XP).
- Deliberately **not** adding bonus XP for leaderboard rank/movement - the
  leaderboard is a *view* over the same trade-outcome-driven XP, not an
  independent reward.
- `User.current_streak`/daily activity streak is untouched by this phase;
  paper trading happens through the same authenticated request lifecycle
  that already advances it (Phase 1's `before_request` hook), so no new
  wiring is needed there.

## Tier gating

**Open to every authenticated user, no plan gate** - matches
`TIER_MATRIX.md`'s existing "Paper trading: open to everyone" reality (Free
included), and matches the platform's stated goal of encouraging learning
rather than paywalling the safe/educational feature. Viewing the
leaderboard requires login (`/api/leaderboard/users` already required it
before this change) but not a specific plan.

## `gamification.py` / `CompetitionEngine`: left alone, on purpose

`CompetitionEngine` is designed around **time-boxed contests** fed
pre-assembled participant snapshots from outside, held **in memory only**
(lost on every restart), and computes Sharpe from raw trade-PnL arrays with
a different formula than `paper_engine.compute_metrics()` (equity-curve
returns). Wiring it in for an always-on, persistent leaderboard would mean
two different "Sharpe" numbers existing in the app for the same concept -
exactly the "second, disconnected scoring system" this phase was told to
avoid. `ACHIEVEMENTS`, `UserAchievement`, `CompetitionModel`,
`CompetitionEntry`, and the mocked `/api/competitions*` and
`/api/achievements/user` endpoints are **not** part of this phase and stay
exactly as documented in `FEATURE_TRUTH_MAP.md` - still real gaps, just not
this one's to close. Only `/api/leaderboard/users` (the trader leaderboard
specifically named in the truth map) is fixed here.
