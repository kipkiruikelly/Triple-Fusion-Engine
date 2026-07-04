"""
config.py
Centralized Configuration for the Triple-Fusion-Engine.

Uses Pydantic Settings for validation, type coercion, and environment-
specific presets. All previously hardcoded constants from across the
codebase are now managed here.

Environment precedence (highest to lowest):
  1. Environment variables (os.environ)
  2. .env file (loaded by python-dotenv in app.py)
  3. Default values defined below

Usage:
    from config import settings
    ticker = settings.DEFAULT_TICKER

Environment presets:
    ENV=development   → debug mode, SQLite, short data periods
    ENV=staging       → PostgreSQL, longer periods, moderate risk
    ENV=production    → PostgreSQL, full history, conservative risk

Author: BullLogic
"""

import os
from pathlib import Path
from typing import List, Optional, Literal
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    """Centralized settings for all Triple-Fusion-Engine components."""

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Environment ──────────────────────────────────────────────────────────
    ENV: Literal["development", "staging", "production"] = "development"
    DEBUG: bool = False

    # ── Paths ────────────────────────────────────────────────────────────────
    DATA_DIR: Path = BASE_DIR / "Data"
    MODELS_DIR: Path = BASE_DIR / "Saved Models"
    LOGS_DIR: Path = BASE_DIR / "logs"
    INSTANCE_DIR: Path = BASE_DIR / "instance"

    # ── Flask / Web ──────────────────────────────────────────────────────────
    SECRET_KEY: str = "smp-dev-key-change-in-production"
    HOST: str = "127.0.0.1"
    PORT: int = 5000
    WEB_THREADS: int = 24
    SECURE_COOKIES: bool = False
    ADMIN_SESSION_MINUTES: int = 30
    ADMIN_ROLE: str = "admin"

    # ── Database ─────────────────────────────────────────────────────────────
    DATABASE_URL: str = ""

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def set_default_db(cls, v: str) -> str:
        if not v or v == "":
            return f"sqlite:///{BASE_DIR / 'instance' / 'users.db'}"
        return v

    # ── Data Pipeline ────────────────────────────────────────────────────────
    DEFAULT_TICKER: str = "QQQ"
    DEFAULT_TICKERS: List[str] = ["QQQ", "SPY", "AAPL", "MSFT", "NVDA"]
    START_DATE: str = "1999-01-01"
    END_DATE: str = "2026-06-01"
    LOOKBACK: int = 60
    TRAIN_RATIO: float = 0.80
    VAL_RATIO: float = 0.10
    INTRADAY_INTERVALS: List[str] = ["1m", "5m", "15m", "30m", "1h", "4h"]
    MAX_PARALLEL_FETCHES: int = 5

    # ── Model Training ───────────────────────────────────────────────────────
    RF_N_ESTIMATORS: int = 300
    RF_MAX_DEPTH: int = 12
    XGB_N_ESTIMATORS: int = 300
    XGB_MAX_DEPTH: int = 6
    XGB_LEARNING_RATE: float = 0.05
    LGB_N_ESTIMATORS: int = 300
    LGB_MAX_DEPTH: int = 8
    LGB_LEARNING_RATE: float = 0.05
    LSTM_EPOCHS: int = 80
    LSTM_BATCH_SIZE: int = 32
    LSTM_PATIENCE: int = 15
    LSTM_LEARNING_RATE: float = 0.001
    LSTM_UNITS: str = "128,64"
    CV_FOLDS: int = 5

    # ── Trading Engine ───────────────────────────────────────────────────────
    MAX_POSITIONS: int = 3
    DAILY_LOSS_LIMIT: float = 0.05
    PAPER_BALANCE: float = 10_000.0
    RISK_PCT: float = 1.0
    SL_ATR_MULT: float = 1.5
    TP_ATR_MULT: float = 2.5
    MAX_HOLD_BARS: int = 10
    COMMISSION: float = 0.001
    MAX_LOG_ENTRIES: int = 200
    WARMUP_BARS: int = 100
    TRADING_MODE: Literal["paper", "metaapi", "mt5linux"] = "paper"

    # ── Phase 3: Risk Management ────────────────────────────────────────────
    KELLY_ENABLED: bool = True
    KELLY_MIN_TRADES: int = 20
    KELLY_MAX_RISK_PCT: float = 2.0
    KELLY_MIN_RISK_PCT: float = 0.25
    TRAILING_STOP_ENABLED: bool = True
    TRAIL_STOP_MULT: float = 1.0
    CORRELATION_THRESHOLD: float = 0.7
    DRAWDOWN_TIERS: str = "0.05:0.75,0.10:0.50,0.15:0.25,0.20:0.00"
    COOLING_OFF_DAYS: int = 1

    # ── MetaApi ──────────────────────────────────────────────────────────────
    METAAPI_TOKEN: str = ""
    METAAPI_ACCOUNT_ID: str = ""
    METAAPI_TIMEOUT: int = 60

    # ── MT5 Bridge ───────────────────────────────────────────────────────────
    MT5_HOST: str = "127.0.0.1"
    MT5_PORT: int = 18812

    # ── Messaging / Redis ────────────────────────────────────────────────────
    REDIS_URL: str = ""
    USE_REDIS: bool = False

    # ── Email ────────────────────────────────────────────────────────────────
    MAIL_SERVER: str = "smtp.gmail.com"
    MAIL_PORT: int = 587
    MAIL_USE_TLS: bool = True
    MAIL_USERNAME: str = ""
    MAIL_PASSWORD: str = ""
    MAIL_DEFAULT_SENDER: str = "BullLogic <noreply@yourdomain.com>"

    # ── M-Pesa ───────────────────────────────────────────────────────────────
    MPESA_ENV: str = "sandbox"
    MPESA_CONSUMER_KEY: str = ""
    MPESA_CONSUMER_SECRET: str = ""
    MPESA_SHORTCODE: str = "174379"
    MPESA_PASSKEY: str = ""
    MPESA_CALLBACK_URL: str = ""
    PRO_MONTHLY_KES: int = 3500
    PRO_ANNUAL_KES: int = 23000

    # ── Stripe ───────────────────────────────────────────────────────────────
    STRIPE_SECRET_KEY: str = ""
    STRIPE_PUBLISHABLE_KEY: str = ""
    STRIPE_PRICE_ID_MONTHLY: str = ""
    STRIPE_PRICE_ID_ANNUAL: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""

    # ── Google OAuth ─────────────────────────────────────────────────────────
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""

    # ── External APIs ────────────────────────────────────────────────────────
    ANTHROPIC_API_KEY: str = ""
    TELEGRAM_BOT_TOKEN: str = ""
    PYTH_API_KEY: str = ""
    AZURE_STORAGE_CONNECTION_STRING: str = ""

    # ── Admin ────────────────────────────────────────────────────────────────
    ADMIN_EMAIL: str = ""
    ADMIN_USERNAME: str = ""
    ADMIN_PASSWORD: str = ""
    ADMIN_EMAIL: str = ""


# ── Singleton ────────────────────────────────────────────────────────────────────

settings = Settings()


# ── Environment-specific overrides ───────────────────────────────────────────────

def apply_env_overrides() -> None:
    """Apply environment-specific configuration overrides.

    Called once at app startup after .env is loaded. Modifies the global
    settings singleton in-place so all modules see the tuned values.
    """
    env = settings.ENV

    if env == "development":
        settings.DEBUG = True
        settings.SECURE_COOKIES = False
        settings.START_DATE = "2024-01-01"
        settings.END_DATE = "2026-06-01"
        settings.RF_N_ESTIMATORS = 100
        settings.LSTM_EPOCHS = 20
        settings.MAX_PARALLEL_FETCHES = 3
        settings.SECRET_KEY = os.environ.get("SECRET_KEY", "smp-dev-key-2025")

    elif env == "staging":
        settings.DEBUG = False
        settings.SECURE_COOKIES = True
        settings.START_DATE = "2022-01-01"
        settings.END_DATE = "2026-06-01"
        settings.LSTM_EPOCHS = 50

    elif env == "production":
        settings.DEBUG = False
        settings.SECURE_COOKIES = True
        settings.START_DATE = "1999-01-01"
        settings.END_DATE = "2026-06-01"
        settings.RISK_PCT = 0.5  # More conservative
        settings.MAX_POSITIONS = 2
        if not settings.SECRET_KEY or settings.SECRET_KEY.startswith("smp-dev"):
            raise RuntimeError("SECRET_KEY must be set to a secure value in production")


def as_dict() -> dict:
    """Return all non-secret settings as a dict (for /health endpoint)."""
    skip = {"SECRET_KEY", "MAIL_PASSWORD", "MPESA_PASSKEY", "MPESA_CONSUMER_SECRET",
            "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET", "GOOGLE_CLIENT_SECRET",
            "ANTHROPIC_API_KEY", "TELEGRAM_BOT_TOKEN", "AZURE_STORAGE_CONNECTION_STRING",
            "METAAPI_TOKEN", "PYTH_API_KEY", "ADMIN_PASSWORD", "REDIS_URL"}
    return {k: str(v) for k, v in settings.model_dump().items() if k not in skip}