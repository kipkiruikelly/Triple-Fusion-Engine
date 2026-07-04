"""Tests for data_quality.py — DataFrame validation and monitoring."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
import numpy as np
import pandas as pd


class TestDataFrameValidation:
    """Test check_dataframe with various data quality scenarios."""

    def test_none_dataframe(self, data_quality_monitor):
        """None or empty DataFrame should fail with score 0."""
        result = data_quality_monitor.check_dataframe(None)
        assert result["passed"] is False
        assert result["score"] == 0

    def test_empty_dataframe(self, data_quality_monitor):
        """Empty DataFrame should fail."""
        result = data_quality_monitor.check_dataframe(pd.DataFrame())
        assert result["passed"] is False

    def test_valid_dataframe(self, data_quality_monitor, sample_df):
        """Valid OHLCV DataFrame should pass all checks."""
        result = data_quality_monitor.check_dataframe(sample_df, ticker="AAPL")
        assert result["passed"] is True
        assert result["score"] == 100.0
        assert result["ticker"] == "AAPL"
        assert len(result["issues"]) == 0

    def test_missing_columns(self, data_quality_monitor):
        """DataFrame without required columns should report issues."""
        df = pd.DataFrame({"A": [1, 2, 3], "B": [4, 5, 6]})
        result = data_quality_monitor.check_dataframe(df)
        assert result["passed"] is False
        assert any("Missing columns" in i for i in result["issues"])

    def test_invalid_ohlc(self, data_quality_monitor):
        """High < Low should be detected."""
        df = pd.DataFrame({
            "Open":  [100.0, 101.0],
            "High":  [99.0, 102.0],   # High < Low on first row
            "Low":   [101.0, 100.0],
            "Close": [100.5, 101.5],
        })
        result = data_quality_monitor.check_dataframe(df)
        assert any("invalid OHLC" in i for i in result["issues"])

    def test_duplicate_index(self, data_quality_monitor):
        """Duplicate timestamps should be detected."""
        dates = pd.date_range("2026-01-01", periods=3)
        dates = dates.append(pd.DatetimeIndex([dates[0]]))  # duplicate
        df = pd.DataFrame({
            "Open": [100, 101, 102, 103],
            "High": [105, 106, 107, 108],
            "Low": [99, 100, 101, 102],
            "Close": [102, 103, 104, 105],
        }, index=dates)
        result = data_quality_monitor.check_dataframe(df)
        assert any("duplicate" in i.lower() for i in result["issues"])

    def test_volume_spikes(self, data_quality_monitor, sample_df):
        """Volume spikes should generate warnings but not fail."""
        df = sample_df.copy()
        df.loc[df.index[-1], "Volume"] = df["Volume"].mean() * 20  # massive spike
        result = data_quality_monitor.check_dataframe(df)
        assert any("volume" in w.lower() for w in result.get("warnings", []))


class TestStalenessChecks:
    """Test check_staleness method."""

    def test_fresh_data(self, data_quality_monitor):
        """Data updated 1 minute ago should be fresh."""
        recent = datetime.now(timezone.utc) - timedelta(minutes=1)
        result = data_quality_monitor.check_staleness(recent, "yfinance")
        assert result["is_stale"] is False
        assert result["status"] == "fresh"

    def test_stale_data(self, data_quality_monitor):
        """Data updated 48 hours ago should be stale."""
        old = datetime.now(timezone.utc) - timedelta(hours=48)
        result = data_quality_monitor.check_staleness(old, "yfinance")
        assert result["is_stale"] is True
        assert result["status"] == "stale"

    def test_aging_data(self, data_quality_monitor):
        """Data updated 5 hours ago should be 'aging'."""
        mid = datetime.now(timezone.utc) - timedelta(hours=5)
        result = data_quality_monitor.check_staleness(mid, "pyth")
        assert result["status"] == "aging"
        assert result["is_stale"] is False


class TestModelFeatureChecks:
    """Test check_model_features."""

    def test_clean_features(self, data_quality_monitor):
        """Clean feature matrix should pass."""
        X = np.random.default_rng(42).normal(0, 1, (100, 10))
        names = [f"f{i}" for i in range(10)]
        result = data_quality_monitor.check_model_features(X, names)
        assert result["has_nan"] is False
        assert result["has_inf"] is False
        assert result["n_samples"] == 100

    def test_nan_features(self, data_quality_monitor):
        """NaN values should be detected."""
        X = np.array([[1.0, np.nan], [3.0, 4.0]])
        result = data_quality_monitor.check_model_features(X, ["a", "b"])
        assert result["has_nan"] is True

    def test_inf_features(self, data_quality_monitor):
        """Inf values should be detected."""
        X = np.array([[1.0, np.inf], [3.0, 4.0]])
        result = data_quality_monitor.check_model_features(X, ["a", "b"])
        assert result["has_inf"] is True

    def test_zero_variance(self, data_quality_monitor):
        """Constant columns should be flagged."""
        X = np.column_stack([
            np.random.default_rng(42).normal(0, 1, 100),
            np.ones(100) * 5.0,  # constant column
        ])
        result = data_quality_monitor.check_model_features(X, ["varying", "constant"])
        assert len(result["zero_variance_cols"]) > 0
        assert "constant" in result["zero_variance_cols"]


class TestSummaryReport:
    """Test summary_report aggregation."""

    def test_clean_summary(self, data_quality_monitor, sample_df):
        """No issues should produce clean summary."""
        data_quality_monitor.check_dataframe(sample_df)
        report = data_quality_monitor.summary_report()
        assert report["status"] == "clean"
        assert report["failures"] == 0

    def test_dirty_summary(self, data_quality_monitor):
        """Issues should produce dirty summary."""
        data_quality_monitor.check_dataframe(None)
        report = data_quality_monitor.summary_report()
        assert report["status"] == "dirty"
        assert report["failures"] > 0
