"""
gamification.py
Gamification Engine for the Triple-Fusion-Engine.

Adds engagement features to encourage learning and strategy development:
  - Paper Trading Competitions: timed contests with leaderboards
  - Performance Badges/Achievements
  - Leaderboard calculations (return, Sharpe, win rate rankings)
  - Shareable strategy performance reports
  - Weekly/monthly/all-time leaderboards

Usage:
    from gamification import CompetitionEngine
    engine = CompetitionEngine()
    engine.create_competition("July Showdown", start, end, initial_balance=10000)
    leaderboard = engine.get_leaderboard(competition_id)

Author: BullLogic
"""

import logging
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class Competition:
    """A paper trading competition."""
    id: str
    name: str
    start_date: date
    end_date: date
    initial_balance: float = 10_000.0
    status: str = "upcoming"  # upcoming / active / completed
    participants: int = 0


@dataclass
class Participant:
    """A competition participant's snapshot."""
    user_id: int
    username: str
    equity: float
    return_pct: float
    sharpe: float
    win_rate: float
    n_trades: int
    rank: int = 0


@dataclass
class Achievement:
    """A user achievement/badge."""
    id: str
    name: str
    description: str
    icon: str  # emoji
    tier: str  # bronze / silver / gold / platinum


# ── Achievement Definitions ─────────────────────────────────────────────────────

ACHIEVEMENTS = {
    "first_trade": Achievement(
        "first_trade", "First Trade", "Place your first paper trade", "🎯", "bronze"
    ),
    "ten_trades": Achievement(
        "ten_trades", "Getting Serious", "Complete 10 paper trades", "📊", "bronze"
    ),
    "hundred_trades": Achievement(
        "hundred_trades", "Centurion", "Complete 100 paper trades", "💯", "silver"
    ),
    "profitable_week": Achievement(
        "profitable_week", "Green Week", "Close a week with positive P&L", "📈", "bronze"
    ),
    "profitable_month": Achievement(
        "profitable_month", "Monthly Profit", "Close a month with >5% return", "💰", "silver"
    ),
    "sharpe_master": Achievement(
        "sharpe_master", "Risk-Adjusted Returns", "Achieve Sharpe > 1.5 over 50+ trades", "🎓", "gold"
    ),
    "win_streak_5": Achievement(
        "win_streak_5", "Hot Hand", "Win 5 trades in a row", "🔥", "silver"
    ),
    "win_streak_10": Achievement(
        "win_streak_10", "Unstoppable", "Win 10 trades in a row", "🚀", "gold"
    ),
    "comeback": Achievement(
        "comeback", "Comeback Kid", "Recover from -20% drawdown to breakeven", "🔄", "silver"
    ),
    "diamond_hands": Achievement(
        "diamond_hands", "Diamond Hands", "Hold a position for 30+ days in profit", "💎", "gold"
    ),
    "diversified": Achievement(
        "diversified", "Diversified", "Trade 5+ different symbols", "🌐", "bronze"
    ),
    "perfect_month": Achievement(
        "perfect_month", "Perfect Month", "Every week of the month is profitable", "👑", "platinum"
    ),
}


class CompetitionEngine:
    """Manages paper trading competitions and leaderboards."""

    def __init__(self):
        self.competitions: Dict[str, Competition] = {}
        self.leaderboards: Dict[str, List[Participant]] = {}

    def create_competition(
        self,
        name: str,
        start_date: date,
        end_date: date,
        initial_balance: float = 10_000.0,
    ) -> Competition:
        """Create a new competition."""
        comp_id = f"comp_{int(datetime.now().timestamp())}"
        comp = Competition(
            id=comp_id,
            name=name,
            start_date=start_date,
            end_date=end_date,
            initial_balance=initial_balance,
            status="upcoming" if start_date > date.today() else (
                "active" if end_date >= date.today() else "completed"
            ),
        )
        self.competitions[comp_id] = comp
        logger.info("Created competition '%s' (%s to %s)", name, start_date, end_date)
        return comp

    def get_active_competitions(self) -> List[Competition]:
        """Return currently active competitions."""
        today = date.today()
        return [c for c in self.competitions.values()
                if c.start_date <= today <= c.end_date]

    def update_leaderboard(
        self,
        competition_id: str,
        participants_data: List[dict],
    ) -> List[Participant]:
        """Update and rank participants for a competition.

        Args:
            competition_id: Competition ID.
            participants_data: List of dicts with user_id, username, equity,
                               trades list.

        Returns:
            Ranked list of Participants.
        """
        comp = self.competitions.get(competition_id)
        if not comp:
            return []

        participants = []
        for pdata in participants_data:
            equity = pdata.get("equity", comp.initial_balance)
            return_pct = (equity - comp.initial_balance) / comp.initial_balance * 100

            trades = pdata.get("trades", [])
            n_trades = len(trades)

            # Calculate Sharpe from trade PnLs
            pnls = np.array([t.get("pnl$", 0) for t in trades]) if trades else np.array([])
            if len(pnls) > 1 and np.std(pnls) > 0:
                sharpe = float(np.mean(pnls) / np.std(pnls) * np.sqrt(252))
            else:
                sharpe = 0.0

            # Win rate
            if n_trades > 0:
                wins = sum(1 for t in trades if t.get("pnl$", 0) > 0)
                win_rate = wins / n_trades * 100
            else:
                win_rate = 0.0

            participants.append(Participant(
                user_id=pdata["user_id"],
                username=pdata.get("username", f"user_{pdata['user_id']}"),
                equity=round(equity, 2),
                return_pct=round(return_pct, 2),
                sharpe=round(sharpe, 3),
                win_rate=round(win_rate, 1),
                n_trades=n_trades,
            ))

        # Rank by return (primary), then Sharpe (tiebreaker)
        participants.sort(key=lambda p: (p.return_pct, p.sharpe), reverse=True)
        for i, p in enumerate(participants):
            p.rank = i + 1

        self.leaderboards[competition_id] = participants
        comp.participants = len(participants)
        return participants

    def get_leaderboard(
        self, competition_id: str, top_n: int = 20
    ) -> List[Participant]:
        """Return the top N participants for a competition."""
        lb = self.leaderboards.get(competition_id, [])
        return lb[:top_n]

    # ── Achievement Logic ───────────────────────────────────────────────────

    def check_achievements(
        self, user_trades: List[dict], user_stats: dict
    ) -> List[Achievement]:
        """Check which achievements a user has earned.

        Args:
            user_trades: List of completed trade dicts.
            user_stats: Dict with keys like total_trades, current_streak,
                        best_streak, max_drawdown_pct, symbols_traded.

        Returns:
            List of newly earned Achievements.
        """
        earned = []
        n = len(user_trades)
        pnls = [t.get("pnl$", 0) for t in user_trades]

        if n >= 1:
            earned.append(ACHIEVEMENTS["first_trade"])
        if n >= 10:
            earned.append(ACHIEVEMENTS["ten_trades"])
        if n >= 100:
            earned.append(ACHIEVEMENTS["hundred_trades"])

        # Win streaks
        current_streak = user_stats.get("current_streak", 0)
        best_streak = user_stats.get("best_streak", 0)
        if best_streak >= 5:
            earned.append(ACHIEVEMENTS["win_streak_5"])
        if best_streak >= 10:
            earned.append(ACHIEVEMENTS["win_streak_10"])

        # Profitable periods
        if user_stats.get("profitable_week", False):
            earned.append(ACHIEVEMENTS["profitable_week"])
        if user_stats.get("monthly_return_pct", 0) > 5:
            earned.append(ACHIEVEMENTS["profitable_month"])

        # Sharpe
        if len(pnls) >= 50:
            mean_ret = np.mean(pnls)
            std_ret = np.std(pnls)
            sharpe = mean_ret / std_ret * np.sqrt(252) if std_ret > 0 else 0
            if sharpe > 1.5:
                earned.append(ACHIEVEMENTS["sharpe_master"])

        # Comeback
        if user_stats.get("max_drawdown_pct", 0) >= 20 and user_stats.get("return_pct", -99) >= 0:
            earned.append(ACHIEVEMENTS["comeback"])

        # Diversification
        symbols_traded = user_stats.get("symbols_traded", 0)
        if symbols_traded >= 5:
            earned.append(ACHIEVEMENTS["diversified"])

        # Diamond hands
        if user_stats.get("longest_hold_days", 0) >= 30:
            earned.append(ACHIEVEMENTS["diamond_hands"])

        return earned

    # ── Performance Report ──────────────────────────────────────────────────

    def generate_performance_report(
        self, trades: List[dict], initial_balance: float = 10_000.0
    ) -> dict:
        """Generate a shareable performance report from trade history.

        Returns a dict suitable for rendering as HTML/PDF.
        """
        n = len(trades)
        if n == 0:
            return {"status": "no_trades", "message": "No trades to report"}

        pnls = np.array([t.get("pnl$", 0) for t in trades])
        wins = pnls[pnls > 0]
        losses = pnls[pnls < 0]

        total_pnl = float(np.sum(pnls))
        final_equity = initial_balance + total_pnl
        total_return = (final_equity - initial_balance) / initial_balance * 100

        win_rate = len(wins) / n * 100 if n else 0
        avg_win = float(np.mean(wins)) if len(wins) > 0 else 0
        avg_loss = float(np.mean(np.abs(losses))) if len(losses) > 0 else 0
        profit_factor = float(np.sum(wins) / abs(np.sum(losses))) if len(losses) > 0 and np.sum(losses) != 0 else float("inf")

        # Sharpe
        if len(pnls) > 1:
            sharpe = float(np.mean(pnls) / np.std(pnls) * np.sqrt(252)) if np.std(pnls) > 0 else 0
        else:
            sharpe = 0.0

        # Drawdown
        equity_curve = np.cumsum(np.insert(pnls, 0, 0)) + initial_balance
        peak = np.maximum.accumulate(equity_curve)
        dd = (peak - equity_curve) / peak * 100
        max_dd = float(np.max(dd))

        # Best/worst trade
        best_trade = float(np.max(pnls)) if len(pnls) > 0 else 0
        worst_trade = float(np.min(pnls)) if len(pnls) > 0 else 0

        # Monthly breakdown
        monthly_pnl: Dict[str, float] = {}
        for t in trades:
            month_key = str(t.get("exit_date", ""))[:7]
            if month_key:
                monthly_pnl[month_key] = monthly_pnl.get(month_key, 0) + t.get("pnl$", 0)

        return {
            "initial_balance": initial_balance,
            "final_equity": round(final_equity, 2),
            "total_pnl": round(total_pnl, 2),
            "total_return_pct": round(total_return, 2),
            "n_trades": n,
            "win_rate_pct": round(win_rate, 1),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "profit_factor": round(profit_factor, 2) if profit_factor != float("inf") else 999.99,
            "sharpe_ratio": round(sharpe, 3),
            "max_drawdown_pct": round(max_dd, 2),
            "best_trade": round(best_trade, 2),
            "worst_trade": round(worst_trade, 2),
            "monthly_pnl": {k: round(v, 2) for k, v in monthly_pnl.items()},
            "generated_at": datetime.now().isoformat(),
        }

    def leaderboard_rankings(
        self, competition_id: str, metric: str = "return_pct"
    ) -> List[dict]:
        """Return leaderboard sorted by a specific metric."""
        lb = self.leaderboards.get(competition_id, [])
        if metric == "sharpe":
            sorted_lb = sorted(lb, key=lambda p: p.sharpe, reverse=True)
        elif metric == "win_rate":
            sorted_lb = sorted(lb, key=lambda p: p.win_rate, reverse=True)
        else:
            sorted_lb = sorted(lb, key=lambda p: p.return_pct, reverse=True)

        return [
            {
                "rank": i + 1,
                "username": p.username,
                "equity": p.equity,
                "return_pct": p.return_pct,
                "sharpe": p.sharpe,
                "win_rate": p.win_rate,
                "n_trades": p.n_trades,
            }
            for i, p in enumerate(sorted_lb)
        ]
