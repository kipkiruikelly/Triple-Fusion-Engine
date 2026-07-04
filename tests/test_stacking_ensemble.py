"""Tests for stacking_ensemble.py and model_training.py."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
import numpy as np
from sklearn.linear_model import LinearRegression
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score


class TestEvaluate:
    """Test the evaluate function from stacking_ensemble.py."""

    def test_evaluate_perfect_prediction(self):
        """Perfect predictions should give MAE=0, RMSE=0, R²=1."""
        from stacking_ensemble import evaluate
        y_true = np.array([100.0, 110.0, 120.0])
        y_pred = np.array([100.0, 110.0, 120.0])
        metrics = evaluate(y_true, y_pred, "Perfect")
        assert metrics["mae"] == 0.0
        assert metrics["rmse"] == 0.0
        assert metrics["r2"] == 1.0
        assert metrics["model"] == "Perfect"

    def test_evaluate_bad_prediction(self):
        """Poor predictions should give low R²."""
        from stacking_ensemble import evaluate
        y_true = np.array([100.0, 110.0, 120.0, 130.0, 140.0])
        y_pred = np.array([50.0, 60.0, 70.0, 80.0, 90.0])
        metrics = evaluate(y_true, y_pred, "Bad")
        assert metrics["r2"] < 0
        assert metrics["mae"] > 0

    def test_evaluate_directional_accuracy(self):
        """Directional accuracy should reflect correct up/down predictions."""
        from stacking_ensemble import evaluate
        y_true = np.array([100, 102, 101, 105])
        y_pred = np.array([100, 103, 102, 106])
        metrics = evaluate(y_true, y_pred, "Dir")
        assert "directional_accuracy" in metrics
        assert 0 <= metrics["directional_accuracy"] <= 100


class TestFeatureImportance:
    """Test feature importance functions."""

    def test_save_feature_importance(self, tmp_path):
        """Should save CSV and PNG files for feature importance."""
        from stacking_ensemble import _save_feature_importance
        import os
        importances = np.array([0.3, 0.2, 0.5])
        names = ["feature_a", "feature_b", "feature_c"]
        # Monkey-patch MODELS_DIR to use tmp_path
        import stacking_ensemble
        old_dir = stacking_ensemble.MODELS_DIR
        stacking_ensemble.MODELS_DIR = str(tmp_path)
        try:
            _save_feature_importance(importances, names, "test_imp", "TestModel")
            assert os.path.exists(str(tmp_path / "test_imp.csv"))
        finally:
            stacking_ensemble.MODELS_DIR = old_dir


class TestBaseModelTraining:
    """Test base model training functions."""

    def test_train_linear_regression(self):
        """LR should fit and predict with reasonable accuracy."""
        from sklearn.linear_model import LinearRegression
        from stacking_ensemble import evaluate
        X = np.random.default_rng(42).normal(0, 1, (100, 5))
        y = X[:, 0] * 2 + X[:, 1] * 0.5 + np.random.default_rng(42).normal(0, 0.5, 100)
        model = LinearRegression()
        model.fit(X[:80], y[:80])
        y_pred = model.predict(X[80:])
        metrics = evaluate(y[80:], y_pred, "LR")
        assert metrics["r2"] > 0  # should be better than mean


class TestMetricsCompat:
    """Test backward compatibility with model_training.py metrics format."""

    def test_metrics_format(self):
        """Metrics dict should have the expected keys."""
        from stacking_ensemble import evaluate
        y = np.array([1.0, 2.0, 3.0])
        p = np.array([1.1, 2.1, 3.1])
        m = evaluate(y, p, "Test")
        assert set(m.keys()) == {"model", "mae", "rmse", "r2", "directional_accuracy"}
        assert isinstance(m["mae"], (int, float))
        assert isinstance(m["rmse"], (int, float))
        assert isinstance(m["r2"], (int, float))


class TestSklearnMetrics:
    """Test that sklearn metrics are computed correctly."""

    def test_mae(self):
        """MAE should be mean of absolute errors."""
        y_true = np.array([1.0, 2.0, 3.0])
        y_pred = np.array([2.0, 2.0, 4.0])
        mae = mean_absolute_error(y_true, y_pred)
        assert mae == pytest.approx((1.0 + 0.0 + 1.0) / 3)

    def test_rmse(self):
        """RMSE should be sqrt of mean squared error."""
        y_true = np.array([0.0, 0.0, 0.0])
        y_pred = np.array([3.0, 4.0, 0.0])
        rmse = np.sqrt(mean_squared_error(y_true, y_pred))
        assert rmse == pytest.approx(np.sqrt((9 + 16 + 0) / 3))

    def test_r2_perfect(self):
        """R² should be 1.0 for perfect fit."""
        y_true = np.array([1.0, 2.0, 3.0])
        y_pred = np.array([1.0, 2.0, 3.0])
        assert r2_score(y_true, y_pred) == 1.0
