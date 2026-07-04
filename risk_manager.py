"""
risk_manager.py
Advanced Risk Management for the Triple-Fusion-Engine.

Replaces fixed ATR-based SL/TP with dynamic, adaptive risk controls:

  - Dynamic Trailing Stops: ATR-based, volatility-adjusted, parabolic SAR
  - Kelly Criterion Position Sizing: optimal fraction based on historical
    win rate and win/loss ratio
  - Volatility-Adjusted Position Sizing: scale position inversely with
    recent realized volatility
  - Portfolio Correlation Monitoring: detect when multiple open positions
    are highly correlated and reduce exposure
  - Drawdown-Based Position Reduction: automatically reduce position size
    as drawdown deepens (protect capital, avoid ruin)
  - Enhanced Daily Loss Limit: multi-tier circuit breaker with cooling-off
    periods

Usage:
    from risk_manager import RiskManager
    rm = RiskManager()
    lots, sl, tp = rm.compute_position(signal, account, price, atr)
    should_trade = rm.check_guardrails(account, open_positions)

Author: BullLogic
"""

import logging
import math
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class TradeRecord:
    """Historical trade for Kelly and performance tracking."""
    entry_date: str
    exit_date: str
    action: str
    pnl: float
    r_multiple: float = 0.0  # P&L / initial risk


@dataclass
class RiskState:
    """Current risk state for dynamic position sizing."""
    account_equity: float
    account_balance: float
    daily_pnl: float
    daily_start_equity: float
    peak_equity: float
    current_drawdown_pct: float
    max_drawdown_pct: float
    open_positions: int
    volatility_regime: str = "normal"  # low / normal / high / extreme


class RiskManager:
    """Adaptive risk management with Kelly sizing and dynamic stops."""

    def __init__(
        self,
        max_positions: int = 3,
        daily_loss_limit: float = 0.05,
        base_risk_pct: float = 1.0,
        max_risk_pct: float = 2.0,
        min_risk_pct: float = 0.25,
        volatility_lookback: int = 20,
        correlation_threshold: float = 0.7,
        drawdown_tiers: Optional[List[Tuple[float, float]]] = None,
    ):
        self.max_positions = max_positions
        self.daily_loss_limit = daily_loss_limit
        self.base_risk_pct = base_risk_pct
        self.max_risk_pct = max_risk_pct
        self.min_risk_pct = min_risk_pct
        self.volatility_lookback = volatility_lookback
        self.correlation_threshold = correlation_threshold

        # Drawdown tiers: (drawdown_pct, risk_multiplier)
        # e.g., at 10% DD, reduce risk to 50% of base
        self.drawdown_tiers = drawdown_tiers or [
            (0.05, 0.75),   # 5% DD → 75% risk
            (0.10, 0.50),   # 10% DD → 50% risk
            (0.15, 0.25),   # 15% DD → 25% risk
            (0.20, 0.00),   # 20% DD → halt trading
        ]

        self.trade_history: List[TradeRecord] = []
        self._daily_loss_hit = False
        self._loss_hit_date: Optional[date] = None
        self._cooling_off_days = 1

    # ── Kelly Criterion Position Sizing ─────────────────────────────────────

    def kelly_fraction(
        self,
        win_rate: Optional[float] = None,
        avg_win: Optional[float] = None,
        avg_loss: Optional[float] = None,
        min_trades: int = 20,
    ) -> float:
        """Compute the optimal Kelly fraction for position sizing.

        Kelly formula: f* = (p * b - q) / b
          where p = win probability, q = 1 - p, b = win/loss ratio

        Uses half-Kelly (f*/2) for conservatism and caps at max_risk_pct.

        Args:
            win_rate: Historical win rate (0-1). If None, computed from history.
            avg_win: Average winning trade P&L. If None, from history.
            avg_loss: Average losing trade P&L (positive number). If None, from history.
            min_trades: Minimum trades required before using Kelly.

        Returns:
            Kelly fraction as decimal (e.g. 0.02 = 2% risk per trade).
        """
        if len(self.trade_history) < min_trades:
            logger.debug("Kelly: insufficient history (%d < %d trades), using base risk %.2f%%",
                         len(self.trade_history), min_trades, self.base_risk_pct * 100)
            return self.base_risk_pct

        if win_rate is None:
            wins = [t for t in self.trade_history if t.pnl > 0]
            losses = [t for t in self.trade_history if t.pnl < 0]
            win_rate = len(wins) / len(self.trade_history) if self.trade_history else 0.5

        if avg_win is None:
            wins = [t.pnl for t in self.trade_history if t.pnl > 0]
            avg_win = float(np.mean(wins)) if wins else 1.0

        if avg_loss is None:
            losses = [abs(t.pnl) for t in self.trade_history if t.pnl < 0]
            avg_loss = float(np.mean(losses)) if losses else 1.0

        if avg_loss <= 0 or avg_win <= 0:
            return self.base_risk_pct

        b = avg_win / avg_loss  # win/loss ratio
        p = max(0.1, min(0.9, win_rate))  # clamp to sensible range
        q = 1 - p

        # Kelly fraction
        kelly = (p * b - q) / b
        kelly = max(0.0, kelly)

        # Half-Kelly for conservatism
        half_kelly = kelly / 2

        # Clamp to configurable bounds
        risk_pct = max(self.min_risk_pct, min(self.max_risk_pct, half_kelly))

        logger.info(
            "Kelly: win_rate=%.1f%% b=%.2f kelly=%.4f half_kelly=%.4f → risk=%.2f%%",
            p * 100, b, kelly, half_kelly, risk_pct * 100,
        )
        return risk_pct

    # ── Volatility-Adjusted Position Sizing ─────────────────────────────────

    def volatility_adjustment(
        self,
        current_volatility_pct: float,
        baseline_volatility_pct: float = 1.0,
    ) -> float:
        """Adjust position size inversely to volatility.

        When volatility is high, reduce position size. When volatility is
        low, can increase (up to the base risk). Normalizes to 1.0 at
        baseline volatility.

        Args:
            current_volatility_pct: Current realized volatility (% daily).
            baseline_volatility_pct: Baseline/"normal" volatility level.

        Returns:
            Multiplier for position size (e.g. 0.5 = half size).
        """
        if current_volatility_pct <= 0:
            return 0.5  # safety: unknown vol → reduce

        ratio = baseline_volatility_pct / current_volatility_pct
        # Clamp: never more than 1.5x, never less than 0.25x
        multiplier = max(0.25, min(1.5, ratio))

        if multiplier < 0.5:
            logger.info("High volatility: %.2f%% (baseline %.2f%%) → size ×%.2f",
                        current_volatility_pct, baseline_volatility_pct, multiplier)
        return multiplier

    # ── Dynamic Trailing Stop ───────────────────────────────────────────────

    def trailing_stop(
        self,
        entry_price: float,
        current_price: float,
        action: str,
        atr: float,
        high_since_entry: Optional[float] = None,
        low_since_entry: Optional[float] = None,
        initial_sl_mult: float = 1.5,
        trail_mult: float = 1.0,
    ) -> Tuple[float, str]:
        """Compute a dynamic trailing stop level.

        Starts at initial_sl_mult * ATR from entry, then trails behind
        the most favorable price by trail_mult * ATR.

        Args:
            entry_price: Order entry price.
            current_price: Current market price.
            action: "BUY" or "SELL".
            atr: Current ATR value.
            high_since_entry: Best (highest) price since entry (for BUY).
            low_since_entry: Best (lowest) price since entry (for SELL).
            initial_sl_mult: ATR multiplier for initial stop.
            trail_mult: ATR multiplier for trailing distance.

        Returns:
            (stop_price, stop_type) where stop_type is "initial" or "trailing".
        """
        if action == "BUY":
            # Initial stop: below entry
            initial_sl = entry_price - initial_sl_mult * atr
            # Trailing stop: below best price
            best = high_since_entry if high_since_entry else max(entry_price, current_price)
            trail_sl = best - trail_mult * atr
            # Trailing stop only moves up
            stop = max(initial_sl, trail_sl)
            stop_type = "trailing" if stop > initial_sl else "initial"
        else:
            # SELL
            initial_sl = entry_price + initial_sl_mult * atr
            best = low_since_entry if low_since_entry else min(entry_price, current_price)
            trail_sl = best + trail_mult * atr
            stop = min(initial_sl, trail_sl)
            stop_type = "trailing" if stop < initial_sl else "initial"

        return round(stop, 5), stop_type

    def take_profit_target(
        self,
        entry_price: float,
        action: str,
        atr: float,
        tp_mult: float = 2.5,
        use_rr: bool = True,
        rr_ratio: float = 1.5,
    ) -> float:
        """Compute take-profit level.

        Args:
            entry_price: Entry price.
            action: "BUY" or "SELL".
            atr: ATR value.
            tp_mult: ATR multiplier for TP distance.
            use_rr: If True, use risk-reward ratio instead of fixed TP.
            rr_ratio: Risk-reward ratio (reward / risk).

        Returns:
            TP price.
        """
        if use_rr:
            # R:R based: TP = entry ± (rr_ratio * initial_sl_distance)
            sl_distance = 1.5 * atr  # initial SL distance
            tp_distance = rr_ratio * sl_distance
        else:
            tp_distance = tp_mult * atr

        if action == "BUY":
            return round(entry_price + tp_distance, 5)
        else:
            return round(entry_price - tp_distance, 5)

    # ── Portfolio Correlation ───────────────────────────────────────────────

    def check_correlation(
        self,
        returns_matrix: Dict[str, List[float]],
        threshold: Optional[float] = None,
    ) -> Dict[str, float]:
        """Check pairwise correlation between open position returns.

        Args:
            returns_matrix: Dict of {symbol: [returns_list]}.
            threshold: Correlation threshold for warning (default from init).

        Returns:
            Dict of {(sym1, sym2): correlation_coef} for pairs above threshold.
        """
        if threshold is None:
            threshold = self.correlation_threshold

        if len(returns_matrix) < 2:
            return {}

        symbols = list(returns_matrix.keys())
        high_corr = {}

        for i in range(len(symbols)):
            for j in range(i + 1, len(symbols)):
                s1, s2 = symbols[i], symbols[j]
                r1 = np.array(returns_matrix[s1][-self.volatility_lookback:])
                r2 = np.array(returns_matrix[s2][-self.volatility_lookback:])

                min_len = min(len(r1), len(r2))
                if min_len < 5:
                    continue

                corr = float(np.corrcoef(r1[:min_len], r2[:min_len])[0, 1])
                if abs(corr) >= threshold:
                    high_corr[(s1, s2)] = round(corr, 3)
                    logger.warning(
                        "High correlation: %s—%s = %.3f (threshold %.2f)",
                        s1, s2, corr, threshold,
                    )

        return high_corr

    def correlation_risk_multiplier(
        self, n_correlated_pairs: int, max_correlated: int = 2
    ) -> float:
        """Reduce position size when too many correlated positions exist.

        Each correlated pair beyond max_correlated reduces risk by 25%.
        """
        if n_correlated_pairs <= max_correlated:
            return 1.0
        excess = n_correlated_pairs - max_correlated
        return max(0.1, 1.0 - excess * 0.25)

    # ── Drawdown-Based Position Reduction ───────────────────────────────────

    def drawdown_multiplier(self, current_drawdown_pct: float) -> float:
        """Return a risk multiplier based on current drawdown level.

        Uses the configured drawdown_tiers to progressively reduce risk.

        Args:
            current_drawdown_pct: Current drawdown as percentage (e.g. 8.5 for 8.5%).

        Returns:
            Risk multiplier (0.0 to 1.0).
        """
        multiplier = 1.0
        for dd_level, risk_mult in sorted(self.drawdown_tiers):
            if current_drawdown_pct >= dd_level * 100:
                multiplier = risk_mult

        if multiplier < 1.0:
            logger.info("Drawdown %.1f%% → risk multiplier %.2f",
                        current_drawdown_pct, multiplier)
        return multiplier

    # ── Guardrails ──────────────────────────────────────────────────────────

    def check_guardrails(
        self,
        account: dict,
        positions: list,
        symbol: str = "",
        daily_start_equity: Optional[float] = None,
    ) -> Tuple[bool, str]:
        """Check all trading guardrails before allowing a new position.

        Returns (allowed, reason).
        """
        equity = account.get("equity", 0)

        # 1. Max positions
        if len(positions) >= self.max_positions:
            return False, f"Max positions ({self.max_positions}) reached"

        # 2. Daily loss limit
        if daily_start_equity and daily_start_equity > 0:
            daily_loss = (daily_start_equity - equity) / daily_start_equity
            if daily_loss >= self.daily_loss_limit:
                if not self._daily_loss_hit:
                    self._daily_loss_hit = True
                    self._loss_hit_date = date.today()
                    logger.warning(
                        "Daily loss limit hit: %.1f%% (limit %.1f%%). Cooling off.",
                        daily_loss * 100, self.daily_loss_limit * 100,
                    )
                return False, f"Daily loss limit: {daily_loss*100:.1f}%"

            # Cooling-off: if limit was hit, check if we're past cooling period
            if self._daily_loss_hit and self._loss_hit_date:
                days_since = (date.today() - self._loss_hit_date).days
                if days_since < self._cooling_off_days:
                    return False, f"Cooling off ({self._cooling_off_days - days_since}d remaining)"

        # 3. Drawdown tier check
        if daily_start_equity and daily_start_equity > 0:
            peak = max(daily_start_equity, account.get("peak_equity", equity))
            dd = (peak - equity) / peak * 100
            dd_mult = self.drawdown_multiplier(dd)
            if dd_mult <= 0:
                return False, f"Drawdown halt: {dd:.1f}%"

        # 4. Minimum account equity
        min_equity = account.get("balance", 100) * 0.5
        if equity < min_equity:
            return False, f"Equity below 50% of balance"

        return True, "OK"

    # ── Combined Position Sizing ────────────────────────────────────────────

    def compute_position(
        self,
        signal_action: str,
        account: dict,
        price: float,
        atr: float,
        volatility_pct: float = 1.0,
        current_drawdown_pct: float = 0.0,
        n_correlated: int = 0,
    ) -> dict:
        """Compute optimal position size and SL/TP levels.

        Combines Kelly criterion, volatility adjustment, drawdown scaling,
        and correlation reduction into a single position sizing decision.

        Returns dict with:
            - lots: position size in lots
            - risk_pct: effective risk percentage
            - sl: stop-loss price
            - tp: take-profit price
            - sl_type: "initial" or "trailing"
            - kelly_fraction: raw Kelly fraction
            - vol_multiplier: volatility adjustment
            - dd_multiplier: drawdown adjustment
            - corr_multiplier: correlation adjustment
        """
        balance = account.get("balance", 10000)

        # 1. Kelly base fraction
        kelly = self.kelly_fraction()

        # 2. Volatility adjustment
        vol_mult = self.volatility_adjustment(volatility_pct)

        # 3. Drawdown adjustment
        dd_mult = self.drawdown_multiplier(current_drawdown_pct)

        # 4. Correlation adjustment
        corr_mult = self.correlation_risk_multiplier(n_correlated)

        # Combined effective risk
        effective_risk = kelly * vol_mult * dd_mult * corr_mult
        effective_risk = max(self.min_risk_pct, min(self.max_risk_pct, effective_risk))

        # Compute lot size
        risk_amount = balance * effective_risk
        sl_distance = 1.5 * atr  # initial SL in price terms
        if sl_distance <= 0 or price <= 0:
            lots = 0.01
        else:
            sl_pct = sl_distance / price
            lots = risk_amount / (sl_pct * price * 1000) if sl_pct > 0 else 0.01
            lots = round(max(0.01, min(lots, 10.0)), 2)

        # SL and TP
        if signal_action == "BUY":
            sl = round(price - sl_distance, 5)
            tp = round(price + 2.5 * atr, 5)
        else:
            sl = round(price + sl_distance, 5)
            tp = round(price - 2.5 * atr, 5)

        result = {
            "lots": lots,
            "risk_pct": round(effective_risk * 100, 3),
            "sl": sl,
            "tp": tp,
            "sl_type": "initial",
            "kelly_fraction": round(kelly, 4),
            "vol_multiplier": round(vol_mult, 3),
            "dd_multiplier": round(dd_mult, 2),
            "corr_multiplier": round(corr_mult, 2),
        }

        logger.info(
            "Position sizing: action=%s lots=%.2f risk=%.3f%% "
            "(kelly=%.4f vol=×%.2f dd=×%.2f corr=×%.2f) SL=%.5f TP=%.5f",
            signal_action, lots, effective_risk * 100,
            kelly, vol_mult, dd_mult, corr_mult, sl, tp,
        )
        return result

    # ── Trade History Management ────────────────────────────────────────────

    def record_trade(self, trade: dict) -> None:
        """Record a completed trade for Kelly and performance tracking."""
        pnl = trade.get("pnl$", trade.get("pnl", 0.0))
        record = TradeRecord(
            entry_date=str(trade.get("entry_date", date.today())),
            exit_date=str(trade.get("exit_date", date.today())),
            action=trade.get("action", "UNKNOWN"),
            pnl=float(pnl),
            r_multiple=float(trade.get("r_multiple", 0.0)),
        )
        self.trade_history.append(record)

        # Keep only last 500 trades
        if len(self.trade_history) > 500:
            self.trade_history = self.trade_history[-500:]

    def win_rate(self) -> float:
        """Current historical win rate."""
        if not self.trade_history:
            return 0.5
        wins = sum(1 for t in self.trade_history if t.pnl > 0)
        return wins / len(self.trade_history)

    def profit_factor(self) -> float:
        """Current historical profit factor."""
        wins = sum(t.pnl for t in self.trade_history if t.pnl > 0)
        losses = abs(sum(t.pnl for t in self.trade_history if t.pnl < 0))
        return wins / losses if losses > 0 else float("inf")

    def sharpe_estimate(self) -> float:
        """Estimate Sharpe ratio from trade history."""
        if len(self.trade_history) < 5:
            return 0.0
        pnls = np.array([t.pnl for t in self.trade_history])
        mean_ret = float(np.mean(pnls))
        std_ret = float(np.std(pnls))
        return mean_ret / std_ret if std_ret > 0 else 0.0

    def reset_daily(self) -> None:
        """Reset daily tracking at the start of a new day."""
        if self._loss_hit_date and self._loss_hit_date < date.today():
            self._daily_loss_hit = False
            self._loss_hit_date = None
