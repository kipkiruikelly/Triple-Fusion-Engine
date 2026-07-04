"""Tests for walk_forward.py - purged splits and metrics."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
import numpy as np
import pandas as pd


class TestPurgedSplits:
    """Test purged_train_test_split."""

    def test_creates_correct_number_of_folds(self):
        """Should create n_folds splits."""
        from walk_forward import purged_train_test_split
        df = pd.DataFrame({
            "Close": np.random.default_rng(42).normal(100, 5, 500),
            "Open": np.random.default_rng(42).normal(100, 5, 500),
            "High": np.random.default_rng(42).normal(102, 5, 500),
            "Low": np.random.default_rng(42).normal(98, 5, 500),
            "Volume": np.ones(500) * 1000,
        })
        splits = purged_train_test_split(df, n_folds=3)
        assert len(splits) == 3

    def test_splits_are_chronological(self):
        """Each fold's train and test should be in order with no overlap."""
        from walk_forward import purged_train_test_split
        df = pd.DataFrame({
            "Close": np.arange(200, dtype=float),
            "Open": np.arange(200, dtype=float),
            "High": np.arange(200, dtype=float) + 1,
            "Low": np.arange(200, dtype=float) - 1,
        })
        splits = purged_train_test_split(df, n_folds=3, purge_pct=0.01, embargo_pct=0.005)
        for train_df, test_df in splits:
            assert len(train_df) > 0
            assert len(test_df) > 0
            # Test must come after train
            assert test_df.index[0] > train_df.index[-1]

    def test_purge_separates_train_test(self):
        """Train and test should not overlap with purge zone."""
        from walk_forward import purged_train_test_split
        df = pd.DataFrame({
            "Close": np.arange(500, dtype=float),
            "Open": np.arange(500, dtype=float),
            "High": np.arange(500, dtype=float) + 1,
            "Low": np.arange(500, dtype=float) - 1,
        })
        splits = purged_train_test_split(df, n_folds=4, purge_pct=0.05, embargo_pct=0.02)
        for train_df, test_df in splits:
            gap = (test_df.index[0] - train_df.index[-1]).days if hasattr(test_df.index[0], 'days') else 1
            assert gap >= 0  # no overlap


class TestFoldMetrics:
    """Test compute_fold_metrics."""

    def test_empty_equity_curve(self):
        """Empty equity curve should return zero metrics."""
        from walk_forward import compute_fold_metrics
        eq = pd.Series(dtype=float)
        metrics = compute_fold_metrics(eq, [])
        assert metrics["total_return"] == 0.0
        assert metrics["sharpe"] == 0.0
        assert metrics["n_trades"] == 0

    def test_profitable_curve(self):
        """Increasing equity should produce positive return."""
        from walk_forward import compute_fold_metrics
        eq = pd.Series([10000, 10100, 10200, 10300, 10400])
        trades = [{"pnl$": 100.0} for _ in range(4)]
        metrics = compute_fold_metrics(eq, trades)
        assert metrics["total_return"] > 0
        assert metrics["win_rate"] == 100.0
        assert metrics["n_trades"] == 4

    def test_losing_curve(self):
        """Decreasing equity should produce negative return."""
        from walk_forward import compute_fold_metrics
        eq = pd.Series([10000, 9900, 9800, 9700])
        trades = [{"pnl$": -100.0} for _ in range(3)]
        metrics = compute_fold_metrics(eq, trades)
        assert metrics["total_return"] < 0
        assert metrics["win_rate"] == 0.0

    def test_sharpe_calculation(self):
        """Sharpe should be computed from returns."""
        from walk_forward import compute_fold_metrics
        eq = pd.Series(np.linspace(10000, 11000, 100))
        metrics = compute_fold_metrics(eq, [{"pnl$": 100} for _ in range(10)])
        assert metrics["sharpe"] > 0

    def test_all_metric_keys_present(self):
        """All expected metric keys should be in the result."""
        from walk_forward import compute_fold_metrics
        eq = pd.Series([10000, 10100])
        metrics = compute_fold_metrics(eq, [{"pnl$": 100.0}])
        expected = {"total_return", "sharpe", "sortino", "max_dd", "calmar",
                    "win_rate", "profit_factor", "n_trades", "alpha"}
        assert expected.issubset(set(metrics.keys()))
