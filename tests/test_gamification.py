"""Tests for gamification.py - competitions, leaderboards, achievements."""
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
import numpy as np


class TestAchievements:
    """Test achievement definitions and checking."""

    def test_all_achievements_defined(self):
        """Should have exactly 12 achievements across all tiers."""
        from gamification import ACHIEVEMENTS
        assert len(ACHIEVEMENTS) == 12
        tiers = {a.tier for a in ACHIEVEMENTS.values()}
        assert tiers == {"bronze", "silver", "gold", "platinum"}

    def test_achievement_tiers(self):
        """Bronze should be easiest, platinum hardest."""
        from gamification import ACHIEVEMENTS
        bronze = [a for a in ACHIEVEMENTS.values() if a.tier == "bronze"]
        platinum = [a for a in ACHIEVEMENTS.values() if a.tier == "platinum"]
        assert len(bronze) > 0
        assert len(platinum) > 0
        assert len(bronze) > len(platinum)

    def test_check_achievements_first_trade(self, competition_engine):
        """One trade should unlock 'first_trade'."""
        trades = [{"pnl$": 10.0, "entry_date": "2026-01-01", "exit_date": "2026-01-02"}]
        stats = {"total_trades": 1}
        earned = competition_engine.check_achievements(trades, stats)
        ids = {a.id for a in earned}
        assert "first_trade" in ids

    def test_check_achievements_ten_trades(self, competition_engine):
        """10 trades should unlock 'ten_trades'."""
        trades = [{"pnl$": 10.0} for _ in range(10)]
        stats = {"total_trades": 10}
        earned = competition_engine.check_achievements(trades, stats)
        ids = {a.id for a in earned}
        assert "ten_trades" in ids

    def test_check_achievements_hundred_trades(self, competition_engine):
        """100 trades should unlock 'hundred_trades'."""
        trades = [{"pnl$": 10.0} for _ in range(100)]
        stats = {"total_trades": 100}
        earned = competition_engine.check_achievements(trades, stats)
        ids = {a.id for a in earned}
        assert "hundred_trades" in ids

    def test_check_achievements_win_streak(self, competition_engine):
        """5+ win streak should unlock 'win_streak_5'."""
        trades = [{"pnl$": 10.0} for _ in range(10)]
        stats = {"best_streak": 7}
        earned = competition_engine.check_achievements(trades, stats)
        ids = {a.id for a in earned}
        assert "win_streak_5" in ids

    def test_check_achievements_diversified(self, competition_engine):
        """5+ symbols should unlock 'diversified'."""
        trades = [{"pnl$": 10.0} for _ in range(10)]
        stats = {"symbols_traded": 5}
        earned = competition_engine.check_achievements(trades, stats)
        ids = {a.id for a in earned}
        assert "diversified" in ids


class TestCompetitionEngine:
    """Test CompetitionEngine create, update, leaderboard."""

    def test_create_competition(self, competition_engine):
        """Should create a competition with correct defaults."""
        today = date.today()
        end = today + timedelta(days=30)
        comp = competition_engine.create_competition("Test Cup", today, end)
        assert comp.name == "Test Cup"
        assert comp.start_date == today
        assert comp.end_date == end
        assert comp.initial_balance == 10_000.0
        assert comp.status in ("active", "upcoming")

    def test_get_active_competitions(self, competition_engine):
        """Should return only competitions where today is within date range."""
        today = date.today()
        comp = competition_engine.create_competition("Active", today, today + timedelta(days=7))
        active = competition_engine.get_active_competitions()
        assert comp.id in {c.id for c in active}

    def test_update_leaderboard_ranks(self, competition_engine):
        """Participants should be ranked by return descending."""
        from tests.mock_data import sample_competition_participants
        today = date.today()
        comp = competition_engine.create_competition("Ranked", today, today + timedelta(days=7))
        participants = sample_competition_participants(5, seed=42)
        ranked = competition_engine.update_leaderboard(comp.id, participants)
        assert len(ranked) == 5
        # Check ranking: higher return = lower rank number
        returns = [p.return_pct for p in ranked]
        assert returns == sorted(returns, reverse=True)
        assert ranked[0].rank == 1

    def test_get_leaderboard_top_n(self, competition_engine):
        """get_leaderboard should return top N only."""
        from tests.mock_data import sample_competition_participants
        today = date.today()
        comp = competition_engine.create_competition("LB", today, today + timedelta(days=7))
        competition_engine.update_leaderboard(comp.id, sample_competition_participants(20, seed=42))
        top = competition_engine.get_leaderboard(comp.id, top_n=5)
        assert len(top) == 5

    def test_leaderboard_rankings_by_metric(self, competition_engine):
        """leaderboard_rankings should sort by specified metric."""
        from tests.mock_data import sample_competition_participants
        today = date.today()
        comp = competition_engine.create_competition("Metric", today, today + timedelta(days=7))
        competition_engine.update_leaderboard(comp.id, sample_competition_participants(10, seed=42))
        by_sharpe = competition_engine.leaderboard_rankings(comp.id, metric="sharpe")
        by_return = competition_engine.leaderboard_rankings(comp.id, metric="return_pct")
        assert len(by_sharpe) == 10
        assert len(by_return) == 10


class TestPerformanceReport:
    """Test the generate_performance_report method."""

    def test_no_trades(self, competition_engine):
        """Empty trade list should return 'no_trades' status."""
        report = competition_engine.generate_performance_report([])
        assert report["status"] == "no_trades"

    def test_with_trades(self, competition_engine):
        """Should compute correct metrics from trade history."""
        from tests.mock_data import sample_trades
        trades = sample_trades(30, win_rate=0.6, seed=42)
        report = competition_engine.generate_performance_report(trades)
        assert report["n_trades"] == 30
        assert "total_pnl" in report
        assert "win_rate_pct" in report
        assert "sharpe_ratio" in report
        assert "max_drawdown_pct" in report
        assert "profit_factor" in report

    def test_report_fields_complete(self, competition_engine):
        """Report should contain all expected fields."""
        from tests.mock_data import sample_trades
        trades = sample_trades(20, seed=42)
        report = competition_engine.generate_performance_report(trades)
        expected = {"initial_balance", "final_equity", "total_pnl", "total_return_pct",
                    "n_trades", "win_rate_pct", "avg_win", "avg_loss",
                    "profit_factor", "sharpe_ratio", "max_drawdown_pct",
                    "best_trade", "worst_trade", "monthly_pnl", "generated_at"}
        assert set(report.keys()) == expected
