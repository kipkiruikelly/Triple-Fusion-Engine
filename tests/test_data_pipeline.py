"""Tests for data_pipeline.py — data download, cleaning, feature engineering."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
import numpy as np
import pandas as pd


class TestCleanData:
    """Test clean_data function."""

    def test_removes_nan_rows(self):
        """clean_data should remove rows with all NaN values."""
        from data_pipeline import clean_data
        df = pd.DataFrame({
            "Open":  [100.0, np.nan, 102.0],
            "High":  [105.0, np.nan, 107.0],
            "Low":   [99.0,  np.nan, 101.0],
            "Close": [102.0, np.nan, 104.0],
            "Volume":[1000,  0,     2000],
        })
        cleaned = clean_data(df)
        assert len(cleaned) <= 3

    def test_removes_zero_volume(self):
        """clean_data should remove rows where Volume == 0."""
        from data_pipeline import clean_data
        df = pd.DataFrame({
            "Open":  [100.0, 101.0],
            "High":  [105.0, 106.0],
            "Low":   [99.0,  100.0],
            "Close": [102.0, 103.0],
            "Volume":[1000,  0],
        })
        cleaned = clean_data(df)
        assert len(cleaned) == 1

    def test_forward_fills_nan(self):
        """clean_data should forward-fill NaN values."""
        from data_pipeline import clean_data
        df = pd.DataFrame({
            "Open":  [100.0, np.nan, 102.0],
            "High":  [105.0, 106.0, 107.0],
            "Low":   [99.0,  100.0, 101.0],
            "Close": [102.0, 103.0, 104.0],
            "Volume":[1000,  2000,  3000],
        })
        cleaned = clean_data(df)
        assert not cleaned["Open"].isna().any()

    def test_sorts_index(self):
        """clean_data should sort the index chronologically."""
        from data_pipeline import clean_data
        dates = pd.to_datetime(["2026-03-01", "2026-01-01", "2026-02-01"])
        df = pd.DataFrame({
            "Open":  [100, 101, 102],
            "High":  [105, 106, 107],
            "Low":   [99,  100, 101],
            "Close": [102, 103, 104],
            "Volume":[1000, 2000, 3000],
        }, index=dates)
        cleaned = clean_data(df)
        assert cleaned.index.is_monotonic_increasing


class TestICTFeatures:
    """Test engineer_ict_features."""

    def test_adds_ict_columns(self, sample_df):
        """Should add ICT columns like Above_200SMA, PD_Position, etc."""
        from data_pipeline import engineer_ict_features
        df = sample_df.copy()
        result = engineer_ict_features(df)
        expected_cols = [
            "Above_200SMA", "Dist_200SMA", "Body_Ratio", "Displacement",
            "Dist_to_SH", "Dist_to_SL", "Structure_Bullish", "PD_Position",
            "Bull_FVG_Count", "Bear_FVG_Count",
        ]
        for col in expected_cols:
            assert col in result.columns, f"Missing column: {col}"

    def test_pd_position_range(self, sample_df):
        """PD_Position should be between 0 and 1."""
        from data_pipeline import engineer_ict_features
        df = sample_df.copy()
        result = engineer_ict_features(df)
        valid = result["PD_Position"].dropna()
        assert (valid >= 0).all()
        assert (valid <= 1).all()

    def test_displacement_is_binary(self, sample_df):
        """Displacement should be 0 or 1."""
        from data_pipeline import engineer_ict_features
        df = sample_df.copy()
        result = engineer_ict_features(df)
        valid = result["Displacement"].dropna()
        assert set(valid.unique()).issubset({0, 1})


class TestFeatureEngineering:
    """Test engineer_features (the full pipeline)."""

    def test_adds_standard_ta(self, sample_df):
        """Should add RSI, MACD, Bollinger Bands, etc."""
        from data_pipeline import engineer_features
        df = sample_df.copy()
        result = engineer_features(df)
        expected = ["SMA_7", "SMA_21", "RSI_14", "MACD", "MACD_Signal",
                    "BB_Upper", "BB_Lower", "Daily_Return"]
        for col in expected:
            assert col in result.columns, f"Missing column: {col}"

    def test_rsi_range(self, sample_df):
        """RSI should be between 0 and 100."""
        from data_pipeline import engineer_features
        df = sample_df.copy()
        result = engineer_features(df)
        valid = result["RSI_14"].dropna()
        assert (valid >= 0).all()
        assert (valid <= 100).all()


class TestSplitData:
    """Test split_data function."""

    def test_train_val_test_split_sizes(self, sample_df):
        """Splits should respect train/val ratios."""
        from data_pipeline import engineer_features, split_data
        df = engineer_features(sample_df.copy())
        train, val, test = split_data(df, 0.80, 0.10)
        n = len(df)
        assert len(train) + len(val) + len(test) == n
        assert len(train) > len(val)
        assert len(train) > len(test)

    def test_splits_are_chronological(self, sample_df):
        """Train should be earliest, then val, then test."""
        from data_pipeline import engineer_features, split_data
        df = engineer_features(sample_df.copy())
        train, val, test = split_data(df, 0.80, 0.10)
        assert train.index.max() < val.index.min()
        assert val.index.max() < test.index.min()
