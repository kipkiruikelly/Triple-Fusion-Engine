"""paper_engine.py, the platform paper trading engine. VIRTUAL MONEY ONLY.

This module simulates trades against real market prices so the platform
can build an honest, live track record for its signals. It never places,
suggests placing, or connects to real-money orders: there are no broker
imports here and tests/test_paper_engine.py asserts that stays true.

Two strategies run side by side so ML and quant rules can be compared:
  ml_ensemble  - consumes predictor.ml_signal (LR + RF ensemble vote)
  alpha_rules  - consumes the alphas.py composite with cross-sectional
                 ranking and the Pyth confidence filter

Every portfolio-state function takes an optional user_id (default None).
None is the original platform-wide demo stream (public /paper page,
unaffected); a real id is that user's own isolated portfolio, opted into
via User.paper_trading_opted_in. Signal generation is computed once per
cycle and shared; only position/equity bookkeeping is per-owner. See
PAPER_TRADING_PHASE2_DESIGN.md for the full design rationale.

Honesty rules, same as the accuracy engine:
  - trades are append-only; exits are written exactly once, never edited
  - every fill applies configurable spread/slippage and commission
  - metrics show "insufficient data" below MIN_TRADES closed trades
  - the engine starts with zero trades; nothing is seeded or backfilled
"""

import json
import logging
from datetime import datetime, timedelta

log = logging.getLogger(__name__)

SIM_CURRENCY = "KES"
STRATEGIES = ("ml_ensemble", "alpha_rules")
MIN_TRADES = 10            # below this, metrics honestly say insufficient data

# Every value here is visible on the public Strategy Rules page.
DEFAULT_CONFIG = {
    "starting_balance": 1_000_000.0,   # VIRTUAL KES
    "risk_pct": 1.0,                   # % of virtual equity risked per trade
    "max_positions": 5,                # per strategy
    "max_class_exposure_pct": 40.0,    # max % of equity notional in one asset class
    "daily_loss_breaker_pct": 5.0,     # pause new entries after this daily drawdown
    "spread_bps": 5.0,                 # simulated half-spread+slippage per side, bps
    "commission_bps": 10.0,            # simulated commission per side, bps of notional
    "stop_atr_mult": 1.5,
    "target_atr_mult": 2.5,
    "max_hold_hours": 240,             # 10 days
    "min_confidence": 55.0,            # ML strategy entry floor
    "alpha_entry_threshold": 0.5,      # composite+rank blend needed to enter
    "alpha_rank_weight": 0.5,          # blend: score*(1-w) + rank*w
    "pyth_wide_conf_pct": 0.30,        # confidence filter kicks in above this
    "tickers": ["QQQ", "SPY", "DIA", "AAPL", "MSFT", "TSLA", "NVDA",
                 "GOOGL", "AMZN", "META", "BTC", "ETH"],
}

_CRYPTO = {"BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "AVAX", "DOGE", "DOT",
           "LINK", "LTC", "MATIC", "SHIB", "UNI", "ATOM"}
_FOREX = {"EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF",
          "NZDUSD", "EURGBP", "EURJPY", "GBPJPY", "USDMXN", "USDZAR",
          "XAUUSD", "XAGUSD"}
_COMMODITY = {"GOLD", "SILVER", "OIL", "BRENT", "NATGAS", "COPPER",
              "PLATINUM", "PALLADIUM", "WHEAT", "CORN", "SOYBEAN",
              "COTTON", "SUGAR", "COCOA", "COFFEE"}
_INDEX = {"NDX", "SPX", "DJI", "VIX", "RUT", "FTSE", "DAX", "NIKKEI", "HSI"}
_ETF = {"QQQ", "SPY", "DIA", "IWM", "GLD", "XLK", "XLV", "XLF", "XLY",
        "XLI", "XLE", "XLP", "XLRE", "XLB", "XLU", "XLC"}


def asset_class(ticker: str) -> str:
    t = ticker.upper()
    if t in _CRYPTO:
        return "crypto"
    if t in _FOREX:
        return "forex"
    if t in _COMMODITY:
        return "commodity"
    if t in _INDEX:
        return "index"
    if t in _ETF:
        return "etf"
    return "equity"


def market_open(asset_cls: str, now: datetime = None) -> bool:
    """Coarse UTC market-hours gate per asset class. Crypto trades 24/7;
    US equities/ETFs Mon-Fri 13:30-20:00 UTC (regular session, holidays
    not modeled, documented in STRATEGY_ASSUMPTIONS.md); forex and
    commodities Sun 22:00 through Fri 21:00 UTC."""
    now = now or datetime.utcnow()
    wd = now.weekday()          # Mon=0 .. Sun=6
    if asset_cls == "crypto":
        return True
    if asset_cls in ("forex", "commodity"):
        if wd == 5:
            return False
        if wd == 6:
            return now.hour >= 22
        if wd == 4:
            return now.hour < 21
        return True
    # equity / etf / index: US regular session
    if wd >= 5:
        return False
    minutes = now.hour * 60 + now.minute
    return 13 * 60 + 30 <= minutes < 20 * 60


# ── Config (stored in AppSetting, editable from admin) ────────────────────────

def load_config(db) -> dict:
    from models import AppSetting
    cfg = dict(DEFAULT_CONFIG)
    try:
        row = db.session.get(AppSetting, "paper_config")
        if row and row.value:
            saved = json.loads(row.value)
            for k in DEFAULT_CONFIG:
                if k in saved:
                    cfg[k] = saved[k]
    except Exception:
        log.exception("paper config load failed, using defaults")
    return cfg


def save_config(db, updates: dict, actor_id=None) -> dict:
    """Persist bounded config updates. Unknown keys are ignored; numeric
    values are clamped to sane ranges so a typo cannot break the sim."""
    from models import AppSetting, PaperTradeEvent
    bounds = {
        "starting_balance": (10_000.0, 1e9),
        "risk_pct": (0.1, 5.0),
        "max_positions": (1, 20),
        "max_class_exposure_pct": (5.0, 100.0),
        "daily_loss_breaker_pct": (1.0, 20.0),
        "spread_bps": (0.0, 100.0),
        "commission_bps": (0.0, 100.0),
        "stop_atr_mult": (0.5, 5.0),
        "target_atr_mult": (0.5, 10.0),
        "max_hold_hours": (1, 24 * 60),
        "min_confidence": (50.0, 95.0),
        "alpha_entry_threshold": (0.1, 2.0),
        "alpha_rank_weight": (0.0, 1.0),
        "pyth_wide_conf_pct": (0.05, 5.0),
    }
    cfg = load_config(db)
    changed = {}
    for k, v in updates.items():
        if k == "tickers" and isinstance(v, list):
            clean = [str(t).upper()[:12] for t in v if str(t).strip()][:30]
            if clean:
                cfg[k] = clean
                changed[k] = clean
        elif k in bounds:
            try:
                lo, hi = bounds[k]
                nv = min(hi, max(lo, float(v)))
                if isinstance(DEFAULT_CONFIG[k], int):
                    nv = int(nv)
                cfg[k] = nv
                changed[k] = nv
            except (TypeError, ValueError):
                continue
    row = db.session.get(AppSetting, "paper_config")
    if row:
        row.value = json.dumps(cfg)
        row.updated_by = actor_id
    else:
        db.session.add(AppSetting(key="paper_config", value=json.dumps(cfg),
                                  updated_by=actor_id))
    if changed:
        db.session.add(PaperTradeEvent(event="config",
                                       detail=json.dumps(changed)[:400]))
    db.session.commit()
    return cfg


def _get_flag(db, key, default="0"):
    from models import AppSetting
    row = db.session.get(AppSetting, key)
    return (row.value if row and row.value is not None else default)


def engine_enabled(db) -> bool:
    return _get_flag(db, "paper_trading_enabled") == "1"


def strategy_enabled(db, strategy: str) -> bool:
    return _get_flag(db, f"paper_strategy_{strategy}", "1") == "1"


def set_engine_enabled(db, enabled: bool, actor_id=None):
    from models import AppSetting, PaperTradeEvent
    row = db.session.get(AppSetting, "paper_trading_enabled")
    val = "1" if enabled else "0"
    if row:
        row.value = val
        row.updated_by = actor_id
    else:
        db.session.add(AppSetting(key="paper_trading_enabled", value=val,
                                  updated_by=actor_id))
    if enabled and not _get_flag(db, "paper_trading_started_at", ""):
        db.session.add(AppSetting(key="paper_trading_started_at",
                                  value=datetime.utcnow().isoformat()))
    db.session.add(PaperTradeEvent(
        event="toggle", detail=f"engine {'started' if enabled else 'paused'}"))
    db.session.commit()


# ── Friction and sizing (pure functions, unit tested) ─────────────────────────

def apply_entry_friction(mkt_price: float, side: str, cfg: dict) -> float:
    """Simulated fill for an entry: you cross the spread and eat slippage,
    so LONG fills above the quoted price and SHORT fills below it."""
    slip = cfg["spread_bps"] / 10_000.0
    return mkt_price * (1 + slip) if side == "LONG" else mkt_price * (1 - slip)


def apply_exit_friction(mkt_price: float, side: str, cfg: dict) -> float:
    """Simulated fill for an exit: the same friction works against you on
    the way out. Closing a LONG sells below market; closing a SHORT buys
    above market."""
    slip = cfg["spread_bps"] / 10_000.0
    return mkt_price * (1 - slip) if side == "LONG" else mkt_price * (1 + slip)


def commission(notional: float, cfg: dict) -> float:
    return abs(notional) * cfg["commission_bps"] / 10_000.0


def position_size(equity: float, risk_pct: float, stop_distance: float) -> float:
    """Volatility-based sizing: qty such that hitting the stop loses
    exactly risk_pct of equity (before friction). Returns 0 for degenerate
    inputs rather than raising."""
    if equity <= 0 or stop_distance <= 0 or risk_pct <= 0:
        return 0.0
    return (equity * risk_pct / 100.0) / stop_distance


def trade_pnl(side: str, qty: float, entry_fill: float, exit_fill: float,
              total_commission: float) -> float:
    gross = qty * ((exit_fill - entry_fill) if side == "LONG"
                   else (entry_fill - exit_fill))
    return gross - total_commission


# ── Portfolio state ───────────────────────────────────────────────────────────

def realized_equity(db, strategy: str, cfg: dict, user_id=None) -> float:
    """Starting balance plus the sum of all closed-trade P&L. VIRTUAL.
    user_id=None is the platform demo stream; pass a real id for a user's
    own isolated portfolio."""
    from models import PaperTrade
    from extensions import db as _db
    total = (_db.session.query(_db.func.coalesce(_db.func.sum(PaperTrade.pnl), 0.0))
             .filter(PaperTrade.strategy == strategy,
                     PaperTrade.status == "closed",
                     PaperTrade.user_id == user_id).scalar())
    return cfg["starting_balance"] + float(total or 0.0)


def open_positions(db, strategy: str = None, user_id=None):
    from models import PaperTrade
    q = PaperTrade.query.filter(PaperTrade.status == "open",
                                PaperTrade.user_id == user_id)
    if strategy:
        q = q.filter(PaperTrade.strategy == strategy)
    return q.order_by(PaperTrade.entry_time).all()


def mark_to_market(db, strategy: str, cfg: dict, quotes: dict, user_id=None) -> float:
    """Realized equity plus unrealized P&L of open positions at current
    quotes. Positions with no live quote are marked at entry (flat)."""
    eq = realized_equity(db, strategy, cfg, user_id=user_id)
    for p in open_positions(db, strategy, user_id=user_id):
        q = quotes.get(p.ticker)
        if not q or not q.get("price"):
            continue
        px = float(q["price"])
        eq += p.qty * ((px - p.entry_price) if p.side == "LONG"
                       else (p.entry_price - px))
    return eq


def class_exposure(db, strategy: str, asset_cls: str, user_id=None) -> float:
    """Total open notional (entry basis) in one asset class."""
    return sum(p.qty * p.entry_price
               for p in open_positions(db, strategy, user_id=user_id)
               if p.asset_class == asset_cls)


def breaker_tripped(db, strategy: str, cfg: dict, quotes: dict, user_id=None) -> bool:
    """Daily loss circuit breaker: True when today's mark-to-market equity
    has fallen more than daily_loss_breaker_pct below today's first
    snapshot. New entries pause; exits keep running."""
    from models import PaperEquitySnapshot
    day_start = datetime.utcnow().replace(hour=0, minute=0, second=0,
                                          microsecond=0)
    first = (PaperEquitySnapshot.query
             .filter(PaperEquitySnapshot.strategy == strategy,
                     PaperEquitySnapshot.user_id == user_id,
                     PaperEquitySnapshot.taken_at >= day_start)
             .order_by(PaperEquitySnapshot.taken_at).first())
    if not first or first.equity <= 0:
        return False
    now_eq = mark_to_market(db, strategy, cfg, quotes, user_id=user_id)
    dd_pct = (first.equity - now_eq) / first.equity * 100.0
    return dd_pct >= cfg["daily_loss_breaker_pct"]


# ── Open / close ──────────────────────────────────────────────────────────────

def _award_paper_xp(user_id, amount):
    """Best-effort XP award for a paper-trading outcome; never lets an XP
    hiccup break the trade that earned it. No-op for the platform demo
    stream (user_id=None - there's no account to credit)."""
    if user_id is None:
        return
    from extensions import db as _db
    try:
        from models import User
        from utils import award_xp
        u = _db.session.get(User, user_id)
        if u:
            award_xp(u, amount)
    except Exception:
        _db.session.rollback()


def try_open(db, strategy: str, ticker: str, side: str, quote: dict,
             atr: float, cfg: dict, model: str = None, confidence=None,
             rationale: str = None, quotes_all: dict = None, now=None,
             user_id=None):
    """Open a VIRTUAL position if every risk gate passes. Returns the
    PaperTrade or a string describing why the entry was rejected.
    user_id=None is the platform demo stream; a real id opens that user's
    own isolated position, sized off their own equity."""
    from models import PaperTrade, PaperTradeEvent
    now = now or datetime.utcnow()
    quotes_all = quotes_all or {ticker: quote}

    if side not in ("LONG", "SHORT"):
        return "invalid side"
    if not quote or not quote.get("price"):
        return "no live quote"
    if atr is None or atr <= 0:
        return "no ATR"

    cls = asset_class(ticker)
    if not market_open(cls, now):
        return "market closed"

    opens = open_positions(db, strategy, user_id=user_id)
    if any(p.ticker == ticker for p in opens):
        return "already open"
    if len(opens) >= cfg["max_positions"]:
        return "max positions"
    if breaker_tripped(db, strategy, cfg, quotes_all, user_id=user_id):
        db.session.add(PaperTradeEvent(
            user_id=user_id, event="breaker",
            detail=f"{strategy}: daily loss breaker active, {ticker} entry skipped"))
        db.session.commit()
        return "daily loss breaker"

    mkt = float(quote["price"])
    equity = realized_equity(db, strategy, cfg, user_id=user_id)
    stop_dist = atr * cfg["stop_atr_mult"]
    qty = position_size(equity, cfg["risk_pct"], stop_dist)
    if qty <= 0:
        return "zero size"

    notional = qty * mkt
    max_class = equity * cfg["max_class_exposure_pct"] / 100.0
    if class_exposure(db, strategy, cls, user_id=user_id) + notional > max_class:
        # scale down to the remaining class budget instead of rejecting
        room = max_class - class_exposure(db, strategy, cls, user_id=user_id)
        if room < equity * 0.001:
            return "class exposure cap"
        qty = room / mkt
        notional = qty * mkt

    fill = apply_entry_friction(mkt, side, cfg)
    comm = commission(qty * fill, cfg)
    stop = fill - stop_dist if side == "LONG" else fill + stop_dist
    target = (fill + atr * cfg["target_atr_mult"] if side == "LONG"
              else fill - atr * cfg["target_atr_mult"])

    trade = PaperTrade(
        user_id=user_id, strategy=strategy, model=model, ticker=ticker.upper(),
        asset_class=cls, side=side, qty=round(qty, 6),
        entry_time=now, entry_price=round(fill, 6), entry_mkt=round(mkt, 6),
        price_source=quote.get("source"), stop_price=round(stop, 6),
        target_price=round(target, 6),
        max_hold_hours=int(cfg["max_hold_hours"]),
        confidence=confidence, rationale=(rationale or "")[:300],
        commission=round(comm, 6), status="open")
    db.session.add(trade)
    db.session.flush()
    db.session.add(PaperTradeEvent(
        user_id=user_id, trade_id=trade.id, event="open",
        detail=f"{strategy} {side} {ticker} qty={qty:.4f} mkt={mkt:.4f} "
               f"fill={fill:.4f} stop={stop:.4f} target={target:.4f} "
               f"src={quote.get('source')}"))
    db.session.commit()
    _award_paper_xp(user_id, 3)
    return trade


def close_trade(db, trade, mkt_price: float, reason: str, cfg: dict, now=None):
    """Write the exit exactly once. A closed trade is never re-closed."""
    from models import PaperTradeEvent
    if trade.status != "open":
        return None
    now = now or datetime.utcnow()
    fill = apply_exit_friction(float(mkt_price), trade.side, cfg)
    exit_comm = commission(trade.qty * fill, cfg)
    pnl = trade_pnl(trade.side, trade.qty, trade.entry_price, fill,
                    trade.commission + exit_comm)
    trade.status = "closed"
    trade.exit_time = now
    trade.exit_price = round(fill, 6)
    trade.exit_mkt = round(float(mkt_price), 6)
    trade.exit_reason = reason
    trade.commission = round(trade.commission + exit_comm, 6)
    trade.pnl = round(pnl, 4)
    db.session.add(PaperTradeEvent(
        user_id=trade.user_id, trade_id=trade.id, event="close",
        detail=f"{reason} mkt={float(mkt_price):.4f} fill={fill:.4f} "
               f"pnl={pnl:+.2f} VIRTUAL"))
    db.session.commit()
    _award_paper_xp(trade.user_id, 15 if pnl > 0 else 3)
    return trade


def check_exit(trade, quote: dict, signal_action: str = None, now=None):
    """Decide whether an open trade should close. Returns (reason, price)
    or (None, None). Priority: stop, target, reversal, timeout."""
    now = now or datetime.utcnow()
    if not quote or not quote.get("price"):
        return None, None
    px = float(quote["price"])
    if trade.side == "LONG":
        if px <= trade.stop_price:
            return "stop", px
        if px >= trade.target_price:
            return "target", px
        if signal_action == "SELL":
            return "reversal", px
    else:
        if px >= trade.stop_price:
            return "stop", px
        if px <= trade.target_price:
            return "target", px
        if signal_action == "BUY":
            return "reversal", px
    held = now - trade.entry_time
    if held >= timedelta(hours=trade.max_hold_hours):
        return "timeout", px
    return None, None


# ── Metrics (honestly computed, unit tested against fixtures) ─────────────────

def compute_metrics(closed_pnls: list, equity_series: list,
                    min_trades: int = MIN_TRADES) -> dict:
    """Performance metrics from closed-trade P&Ls and an equity time
    series. Below min_trades closed trades, returns
    {"sufficient": False, ...} and no ratio metrics, honestly."""
    import numpy as np
    n = len(closed_pnls)
    out = {"trades": n, "min_trades": min_trades, "sufficient": n >= min_trades}
    if not out["sufficient"]:
        return out

    wins = [p for p in closed_pnls if p > 0]
    losses = [p for p in closed_pnls if p <= 0]
    gross_w = sum(wins)
    gross_l = abs(sum(losses))
    out["win_rate_pct"] = round(len(wins) / n * 100, 1)
    out["profit_factor"] = round(gross_w / gross_l, 3) if gross_l > 0 else None
    out["avg_win"] = round(gross_w / len(wins), 2) if wins else 0.0
    out["avg_loss"] = round(-gross_l / len(losses), 2) if losses else 0.0
    out["net_pnl"] = round(sum(closed_pnls), 2)

    eq = np.asarray([e for e in equity_series if e and e > 0], dtype=float)
    if len(eq) >= 3:
        rets = np.diff(eq) / eq[:-1]
        sd = rets.std(ddof=1)
        out["total_return_pct"] = round((eq[-1] / eq[0] - 1) * 100, 2)
        out["sharpe"] = round(float(rets.mean() / sd * np.sqrt(252)), 3) if sd > 0 else None
        downside = rets[rets < 0]
        dsd = downside.std(ddof=1) if len(downside) > 1 else 0.0
        out["sortino"] = round(float(rets.mean() / dsd * np.sqrt(252)), 3) if dsd > 0 else None
        peak = np.maximum.accumulate(eq)
        out["max_drawdown_pct"] = round(float(((eq - peak) / peak).min() * 100), 2)
    else:
        out["total_return_pct"] = out["sharpe"] = out["sortino"] = None
        out["max_drawdown_pct"] = None
    return out


def strategy_report(db, strategy: str, cfg: dict, user_id=None) -> dict:
    """Everything the results page needs for one strategy. user_id=None is
    the platform demo stream; a real id is that user's own portfolio."""
    from models import PaperTrade, PaperEquitySnapshot
    closed = (PaperTrade.query
              .filter(PaperTrade.strategy == strategy,
                      PaperTrade.status == "closed",
                      PaperTrade.user_id == user_id)
              .order_by(PaperTrade.exit_time).all())
    snaps = (PaperEquitySnapshot.query
             .filter(PaperEquitySnapshot.strategy == strategy,
                     PaperEquitySnapshot.user_id == user_id)
             .order_by(PaperEquitySnapshot.taken_at).all())
    # one equity point per day (last snapshot of the day) for ratio math
    daily = {}
    for s in snaps:
        daily[s.taken_at.date().isoformat()] = s.equity
    eq_series = [cfg["starting_balance"]] + list(daily.values())

    pnls = [t.pnl for t in closed if t.pnl is not None]
    metrics = compute_metrics(pnls, eq_series)

    exposure_notional = sum(p.qty * p.entry_price
                            for p in open_positions(db, strategy, user_id=user_id))
    eq_now = realized_equity(db, strategy, cfg, user_id=user_id)
    turnover = sum(abs(t.qty * t.entry_price) for t in closed)

    by_class, by_model = {}, {}
    for t in closed:
        for key, bucket in ((t.asset_class, by_class), (t.model or "?", by_model)):
            b = bucket.setdefault(key, {"trades": 0, "net_pnl": 0.0, "wins": 0})
            b["trades"] += 1
            b["net_pnl"] = round(b["net_pnl"] + (t.pnl or 0.0), 2)
            if (t.pnl or 0) > 0:
                b["wins"] += 1
    for bucket in (by_class, by_model):
        for b in bucket.values():
            b["win_rate_pct"] = (round(b["wins"] / b["trades"] * 100, 1)
                                 if b["trades"] >= MIN_TRADES else None)

    return {
        "strategy": strategy,
        "enabled": strategy_enabled(db, strategy),
        "equity": round(eq_now, 2),
        "starting_balance": cfg["starting_balance"],
        "currency": SIM_CURRENCY,
        "open_positions": len(open_positions(db, strategy, user_id=user_id)),
        "exposure_pct": round(exposure_notional / eq_now * 100, 2) if eq_now > 0 else 0.0,
        "turnover": round(turnover, 2),
        "metrics": metrics,
        "by_asset_class": by_class,
        "by_model": by_model,
        "equity_curve": [{"date": d, "equity": round(v, 2)}
                         for d, v in sorted(daily.items())],
    }


def snapshot_equity(db, strategy: str, cfg: dict, quotes: dict, user_id=None):
    from models import PaperEquitySnapshot
    db.session.add(PaperEquitySnapshot(
        user_id=user_id, strategy=strategy,
        equity=round(mark_to_market(db, strategy, cfg, quotes, user_id=user_id), 4),
        open_count=len(open_positions(db, strategy, user_id=user_id))))
    db.session.commit()


def digest_summary(db) -> str:
    """One line for the staff daily digest. Empty string when the engine
    has never run."""
    from models import PaperTrade
    cfg_started = _get_flag(db, "paper_trading_started_at", "")
    if not cfg_started:
        return ""
    cfg = load_config(db)
    parts = []
    for s in STRATEGIES:
        eq = realized_equity(db, s, cfg)
        n_open = len(open_positions(db, s))
        n_closed = (PaperTrade.query
                    .filter(PaperTrade.strategy == s,
                            PaperTrade.status == "closed").count())
        ret = (eq / cfg["starting_balance"] - 1) * 100
        parts.append(f"{s}: {ret:+.2f}% ({n_closed} closed, {n_open} open)")
    return "Simulated paper trading: " + "; ".join(parts) + "."


# ── Signal generation ─────────────────────────────────────────────────────────

def _atr_from_history(df) -> float:
    """ATR(14) from an OHLC frame, for stop distance."""
    import numpy as np
    high, low, close = df["High"], df["Low"], df["Close"]
    prev = close.shift(1)
    tr = np.maximum(high - low, np.maximum((high - prev).abs(),
                                           (low - prev).abs()))
    atr = tr.rolling(14, min_periods=5).mean()
    v = float(atr.iloc[-1]) if len(atr) else 0.0
    return v if v > 0 else float(close.iloc[-1]) * 0.01


def alpha_signals(db, cfg: dict, quotes: dict) -> dict:
    """Rules-based signals from the alpha library, cross-sectionally
    ranked, filtered by Pyth oracle confidence. Returns
    {ticker: {action, score, atr, rationale}}."""
    from market_data import get_history
    from alphas import (compute_alphas, composite_score,
                        cross_sectional_rank, pyth_confidence_multiplier)

    scores, atrs, details = {}, {}, {}
    for t in cfg["tickers"]:
        try:
            df, _meta = get_history(t, period="1y", interval="1d")
            if df is None or len(df) < 80:
                continue
            adf = compute_alphas(df)
            score = composite_score(adf.iloc[-1])
            scores[t] = score
            atrs[t] = _atr_from_history(df)
            details[t] = score
        except Exception as e:
            log.warning("alpha signal failed for %s: %s", t, e)

    ranks = cross_sectional_rank(scores)
    out = {}
    w = cfg["alpha_rank_weight"]
    for t, score in scores.items():
        blended = score * (1 - w) + ranks.get(t, 0.0) * w
        q = quotes.get(t) or {}
        mult = pyth_confidence_multiplier(q.get("conf_pct"),
                                          cfg["pyth_wide_conf_pct"])
        final = blended * mult
        if final >= cfg["alpha_entry_threshold"]:
            action = "BUY"
        elif final <= -cfg["alpha_entry_threshold"]:
            action = "SELL"
        else:
            action = "HOLD"
        out[t] = {"action": action, "score": round(final, 4),
                  "atr": atrs.get(t, 0.0),
                  "rationale": (f"alpha composite {score:+.2f}, xs-rank "
                                f"{ranks.get(t, 0):+.2f}, pyth conf x{mult:.2f} "
                                f"=> {final:+.2f}")}
    return out


def ml_signals(cfg: dict) -> dict:
    """ML ensemble signals via predictor.ml_signal. Only tickers with
    trained daily models produce non-HOLD actions; the rest are skipped
    by the predictor itself (honest HOLD with an error field)."""
    from predictor import ml_signal
    out = {}
    for t in cfg["tickers"]:
        try:
            s = ml_signal(t, "1d")
            out[t] = s
        except Exception as e:
            log.warning("ml signal failed for %s: %s", t, e)
    return out


# ── Cycle runner (called from the ops thread) ─────────────────────────────────

def _run_owner_cycle(db, cfg, quotes, sig_ml, sig_alpha, user_id=None):
    """One exits+entries+snapshots pass for a single owner (None = the
    platform demo stream; a real id = that user's own portfolio). Signals
    are precomputed once per cycle and shared across every owner - they
    depend only on the ticker, not on who might trade it."""
    result = {"opened": 0, "closed": 0, "rejected": 0}

    owned = open_positions(db, user_id=user_id)

    # 1) exits
    for p in owned:
        sig = (sig_ml if p.strategy == "ml_ensemble" else sig_alpha).get(p.ticker) or {}
        # only act on exits while that market trades (stops use live quotes)
        if not market_open(p.asset_class):
            continue
        reason, px = check_exit(p, quotes.get(p.ticker), sig.get("action"))
        if reason:
            close_trade(db, p, px, reason, cfg)
            result["closed"] += 1

    # 2) entries
    for strategy, sigs in (("ml_ensemble", sig_ml), ("alpha_rules", sig_alpha)):
        if not strategy_enabled(db, strategy):
            continue
        for t, s in sigs.items():
            action = s.get("action")
            if action not in ("BUY", "SELL"):
                continue
            if strategy == "ml_ensemble":
                conf = s.get("confidence") or 0
                if conf < cfg["min_confidence"]:
                    continue
                model = "lr+rf" + ("+xgb" if s.get("has_xgb") else "")
                rationale = (f"ML ensemble {action} conf={conf}% "
                             f"lr={s.get('lr_pred')} rf_ret={s.get('rf_ret')}")
                atr = s.get("atr") or 0
            else:
                conf = min(99.0, abs(s.get("score", 0)) * 100)
                model = "alpha_composite"
                rationale = s.get("rationale")
                atr = s.get("atr") or 0
            side = "LONG" if action == "BUY" else "SHORT"
            r = try_open(db, strategy, t, side, quotes.get(t), atr, cfg,
                         model=model, confidence=conf, rationale=rationale,
                         quotes_all=quotes, user_id=user_id)
            if isinstance(r, str):
                result["rejected"] += 1
            else:
                result["opened"] += 1

    # 3) snapshots
    for s in STRATEGIES:
        snapshot_equity(db, s, cfg, quotes, user_id=user_id)

    return result


def run_cycle(app, db):
    """One full engine cycle for the platform demo stream, then again for
    every opted-in user's own portfolio, all sharing one signal computation.
    Safe to call every ops tick. The demo stream does nothing while paused
    (engine_enabled); opted-in users still get their own cycle even then -
    it's their own portfolio, not the demo (see
    PAPER_TRADING_PHASE2_DESIGN.md)."""
    from market_data import get_quotes_verified
    from models import User

    cfg = load_config(db)
    demo_enabled = engine_enabled(db)
    opted_in = User.query.filter_by(paper_trading_opted_in=True).all()

    if not demo_enabled and not opted_in:
        return {"ran": False, "reason": "paused"}

    open_all = list(open_positions(db))
    for u in opted_in:
        open_all += open_positions(db, user_id=u.id)
    need_quotes = sorted({p.ticker for p in open_all} | set(cfg["tickers"]))
    quotes = get_quotes_verified(need_quotes)

    # signals (used for both reversal exits and entries), computed once and
    # shared across the demo stream and every opted-in user this cycle.
    sig_ml = {}
    sig_alpha = {}
    if strategy_enabled(db, "ml_ensemble"):
        sig_ml = ml_signals(cfg)
    if strategy_enabled(db, "alpha_rules"):
        sig_alpha = alpha_signals(db, cfg, quotes)

    result = {"ran": False, "opened": 0, "closed": 0, "rejected": 0, "users": 0}

    if demo_enabled:
        demo = _run_owner_cycle(db, cfg, quotes, sig_ml, sig_alpha, user_id=None)
        result["ran"] = True
        result["opened"]   += demo["opened"]
        result["closed"]   += demo["closed"]
        result["rejected"] += demo["rejected"]

    for u in opted_in:
        try:
            _run_owner_cycle(db, cfg, quotes, sig_ml, sig_alpha, user_id=u.id)
            result["users"] += 1
            result["ran"] = True
        except Exception:
            db.session.rollback()
            log.exception("paper cycle failed for user %s", u.id)

    log.info("paper cycle: demo=%s users=%s opened=%s closed=%s rejected=%s",
             demo_enabled, result["users"], result["opened"],
             result["closed"], result["rejected"])
    return result
