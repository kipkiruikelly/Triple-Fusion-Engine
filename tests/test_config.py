"""Tests for config.py — centralized Pydantic settings."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest


class TestSettings:
    """Test the config.Settings singleton and environment-specific overrides."""

    def test_settings_singleton_exists(self):
        """settings singleton should be importable with defaults."""
        from config import settings
        assert settings.ENV == "development"
        assert settings.DEFAULT_TICKER == "QQQ"
        assert settings.TRAIN_RATIO == 0.80
        assert settings.MAX_POSITIONS == 3
        assert settings.RISK_PCT == 1.0

    def test_settings_paths_are_paths(self):
        """DATA_DIR, MODELS_DIR, LOGS_DIR should be Path objects."""
        from config import settings
        assert isinstance(settings.DATA_DIR, Path)
        assert isinstance(settings.MODELS_DIR, Path)
        assert settings.DATA_DIR.name == "Data"
        assert settings.MODELS_DIR.name == "Saved Models"

    def test_settings_database_url_default(self):
        """DATABASE_URL should default to SQLite when empty."""
        from config import settings
        assert "sqlite" in str(settings.DATABASE_URL) or settings.DATABASE_URL == ""

    def test_apply_env_overrides_development(self):
        """Development env should enable debug and reduce training params."""
        from config import settings, apply_env_overrides
        settings.ENV = "development"
        apply_env_overrides()
        assert settings.DEBUG is True
        assert settings.SECURE_COOKIES is False
        assert settings.RF_N_ESTIMATORS == 100
        assert settings.LSTM_EPOCHS == 20

    def test_apply_env_overrides_production_requires_secret(self):
        """Production env without SECRET_KEY should raise RuntimeError."""
        from config import settings, apply_env_overrides
        settings.ENV = "production"
        old_secret = settings.SECRET_KEY
        settings.SECRET_KEY = "smp-dev-key-2025"  # dev key should fail in production
        with pytest.raises(RuntimeError, match="SECRET_KEY"):
            apply_env_overrides()
        settings.SECRET_KEY = old_secret
        settings.ENV = "development"

    def test_as_dict_excludes_secrets(self):
        """as_dict() should not expose secret keys."""
        from config import as_dict, settings
        d = as_dict()
        assert "SECRET_KEY" not in d
        assert "MAIL_PASSWORD" not in d
        assert "STRIPE_SECRET_KEY" not in d
        assert "DEFAULT_TICKER" in d

    @pytest.mark.parametrize("env,expected_debug,expected_risk", [
        ("development", True, 1.0),
        ("staging", False, 1.0),
        ("production", False, 0.5),
    ])
    def test_env_presets(self, env, expected_debug, expected_risk):
        """Each environment should have correct preset values."""
        from config import settings, apply_env_overrides
        settings.ENV = env
        if env == "production":
            settings.SECRET_KEY = "prod-secret-key-very-long-random"
        apply_env_overrides()
        assert settings.DEBUG == expected_debug
        assert settings.RISK_PCT == expected_risk
        settings.ENV = "development"
        apply_env_overrides()

    def test_risk_management_settings(self):
        """Phase 3 risk settings should have sensible defaults."""
        from config import settings
        assert settings.KELLY_ENABLED is True
        assert settings.KELLY_MIN_TRADES == 20
        assert 0 < settings.KELLY_MIN_RISK_PCT < settings.KELLY_MAX_RISK_PCT
        assert settings.TRAILING_STOP_ENABLED is True
        assert settings.CORRELATION_THRESHOLD == 0.7
        assert settings.COOLING_OFF_DAYS == 1
