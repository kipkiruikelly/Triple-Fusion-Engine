"""
mock_data.py
Realistic mock data for unit and integration testing.

Provides pre-built OHLCV DataFrames, trade histories, model predictions,
and account snapshots that resemble real market data without requiring
live API calls or trained models.

Usage:
    from tests.mock_data import sample_ohlcv, sample_trades, sample_account

Author: BullLogic
"""

import numpy as np
import pandas as pd
from datetime import date, datetime, timedelta


# ── OHLCV Data ──────────────────────────────────────────────────────────────────

def sample_ohlcv(n_bars: int = 200, start_price: float = 100.0,
                 volatility: float = 0.015, seed: int = 42) -> pd.DataFrame:
    """Generate realistic OHLCV data using geometric Brownian motion.

    Args:
        n_bars: Number of bars (trading days).
        start_price: Starting close price.
        volatility: Daily volatility (standard deviation of returns).
        seed: Random seed for reproducibility.

    Returns:
        DataFrame with columns Open, High, Low, Close, Volume and DateTimeIndex.
    """
    rng = np.random.default_rng(seed)
    dates = pd.date_range(end=date.today(), periods=n_bars, freq="B")

    # Generate log returns
    returns = rng.normal(0.0002, volatility, n_bars)  # slight positive drift

    # Build close prices
    close = start_price * np.exp(np.cumsum(returns))

    # Build OHLC from close
    open_price = close * (1 + rng.normal(0, 0.003, n_bars))
    high = np.maximum(open_price, close) * (1 + np.abs(rng.normal(0, 0.005, n_bars)))
    low = np.minimum(open_price, close) * (1 - np.abs(rng.normal(0, 0.005, n_bars)))

    # Volume: lognormal distribution
    volume = rng.lognormal(mean=14, sigma=0.8, size=n_bars).astype(int)

    df = pd.DataFrame({
        "Open":   np.round(open_price, 4),
        "High":   np.round(high, 4),
        "Low":    np.round(low, 4),
        "Close":  np.round(close, 4),
        "Volume": volume,
    }, index=dates)

    return df


def sample_ohlcv_multi_ticker(n_bars: int = 100) -> dict:
    """Generate OHLCV data for multiple correlated tickers."""
    tickers = ["AAPL", "MSFT", "GOOGL"]
    result = {}
    base = sample_ohlcv(n_bars, start_price=100, seed=42)
    result["AAPL"] = base.copy()

    # Correlated tickers
    msft = base.copy()
    msft["Close"] = base["Close"] * 3.2 + np.random.default_rng(99).normal(0, 0.5, n_bars)
    msft[["Open", "High", "Low"]] = msft[["Open", "High", "Low"]] * 3.2
    result["MSFT"] = msft

    googl = base.copy()
    googl["Close"] = base["Close"] * 1.4 + np.random.default_rng(123).normal(0, 0.3, n_bars)
    googl[["Open", "High", "Low"]] = googl[["Open", "High", "Low"]] * 1.4
    result["GOOGL"] = googl

    return result


# ── Trade History ───────────────────────────────────────────────────────────────

def sample_trades(n_trades: int = 50, win_rate: float = 0.55,
                  avg_win: float = 50.0, avg_loss: float = -40.0,
                  seed: int = 42) -> list:
    """Generate a realistic trade history.

    Returns list of dicts compatible with risk_manager.TradeRecord.
    """
    rng = np.random.default_rng(seed)
    base_date = date.today() - timedelta(days=n_trades * 2)
    trades = []

    for i in range(n_trades):
        is_win = rng.random() < win_rate
        pnl = rng.normal(avg_win, 15) if is_win else rng.normal(avg_loss, 15)
        entry_date = base_date + timedelta(days=i * 2)
        exit_date = entry_date + timedelta(days=rng.integers(1, 10))

        trades.append({
            "entry_date": str(entry_date),
            "exit_date": str(exit_date),
            "action": "BUY" if rng.random() < 0.6 else "SELL",
            "entry_price": round(rng.uniform(95, 105), 4),
            "exit_price": round(rng.uniform(95, 105), 4),
            "pnl$": round(float(pnl), 2),
            "r_multiple": round(float(pnl) / 100, 2),
            "reason": "TP" if is_win else "SL",
        })
    return trades


def sample_trade_history_bullish(n_trades: int = 50) -> list:
    """Generate a strongly bullish trade history (70% win rate)."""
    return sample_trades(n_trades, win_rate=0.70, avg_win=80.0, avg_loss=-35.0, seed=123)


def sample_trade_history_bearish(n_trades: int = 50) -> list:
    """Generate a bearish trade history (30% win rate)."""
    return sample_trades(n_trades, win_rate=0.30, avg_win=40.0, avg_loss=-60.0, seed=456)


# ── Account Data ────────────────────────────────────────────────────────────────

def sample_account(equity: float = 10_000.0, balance: float = 10_000.0) -> dict:
    """Return a mock account dict matching MT5Trader.account structure."""
    return {
        "login": 12345,
        "name": "Test Account",
        "server": "TestBroker-Demo",
        "currency": "USD",
        "balance": round(balance, 2),
        "equity": round(equity, 2),
        "margin": 0.0,
        "free_margin": round(equity, 2),
        "leverage": 100,
    }


def sample_account_underwater() -> dict:
    """Return an account in drawdown."""
    return sample_account(equity=8_500.0, balance=10_000.0)


# ── Model Predictions ───────────────────────────────────────────────────────────

def sample_predictions(n: int = 100, price_range: tuple = (95, 105),
                       seed: int = 42) -> dict:
    """Generate mock model predictions with realistic error distributions."""
    rng = np.random.default_rng(seed)
    true = np.linspace(price_range[0], price_range[1], n) + rng.normal(0, 1, n)
    lr_pred = true + rng.normal(0, 2, n)       # LR: moderate error
    rf_pred = true + rng.normal(0, 1.5, n)     # RF: better than LR
    xgb_pred = true + rng.normal(0, 1.2, n)    # XGB: slightly better
    lgb_pred = true + rng.normal(0, 1.1, n)    # LGB: best individual
    lstm_pred = true + rng.normal(0, 1.3, n)   # LSTM: decent
    stack_pred = true + rng.normal(0, 0.8, n)  # Stacking: best overall

    return {
        "y_true": np.round(true, 2),
        "lr": np.round(lr_pred, 2),
        "rf": np.round(rf_pred, 2),
        "xgb": np.round(xgb_pred, 2),
        "lgb": np.round(lgb_pred, 2),
        "lstm": np.round(lstm_pred, 2),
        "stacking": np.round(stack_pred, 2),
    }


# ── Signal Data ─────────────────────────────────────────────────────────────────

def sample_signal_buy() -> dict:
    """Return a BUY signal dict."""
    return {
        "action": "BUY",
        "score": 6,
        "reason": "ICT_bias=bull PD=0.32 | ML=BUY | Tech=BUY",
        "rsi": 35.5,
        "macd": 0.0023,
        "atr": 1.25,
        "price": 100.50,
        "confidence": 72.5,
    }


def sample_signal_sell() -> dict:
    """Return a SELL signal dict."""
    return {
        "action": "SELL",
        "score": 5,
        "reason": "ICT_bias=bear PD=0.78 | ML=SELL | Tech=SELL",
        "rsi": 68.2,
        "macd": -0.0015,
        "atr": 1.10,
        "price": 99.80,
        "confidence": 65.0,
    }


def sample_signal_hold() -> dict:
    """Return a HOLD signal dict."""
    return {
        "action": "HOLD",
        "score": 2,
        "reason": "ML=HOLD | Tech=HOLD | fallback",
        "rsi": 52.0,
        "macd": 0.0001,
        "atr": 0.95,
        "price": 100.00,
        "confidence": 45.0,
    }


# ── Economic Events ─────────────────────────────────────────────────────────────

def sample_economic_events() -> list:
    """Return a list of mock economic events."""
    today = date.today()
    return [
        {"date": (today + timedelta(days=3)).isoformat(), "title": "FOMC Rate Decision",
         "type": "FOMC", "currency": "USD", "impact": 9},
        {"date": (today + timedelta(days=7)).isoformat(), "title": "US Non-Farm Payrolls",
         "type": "NFP", "currency": "USD", "impact": 9},
        {"date": (today + timedelta(days=14)).isoformat(), "title": "US CPI YoY",
         "type": "CPI", "currency": "USD", "impact": 8},
        {"date": (today + timedelta(days=1)).isoformat(), "title": "ECB Rate Decision",
         "type": "RATE_DECISION", "currency": "EUR", "impact": 8},
    ]


# ── Competition Data ────────────────────────────────────────────────────────────

def sample_competition_participants(n: int = 10, seed: int = 42) -> list:
    """Generate mock competition participants."""
    rng = np.random.default_rng(seed)
    names = ["Trader" + str(i) for i in range(1, n + 1)]
    participants = []
    for i, name in enumerate(names):
        equity = 10000 * (1 + rng.normal(0.05, 0.15))
        trades = sample_trades(20, win_rate=0.45 + rng.random() * 0.3, seed=seed + i)
        participants.append({
            "user_id": i + 1,
            "username": name,
            "equity": round(equity, 2),
            "trades": trades,
        })
    return participants


# ── Feature Matrix ───────────────────────────────────────────────────────────────

def sample_feature_matrix(n_samples: int = 500, n_features: int = 45,
                          seed: int = 42) -> np.ndarray:
    """Generate a mock feature matrix with realistic correlations."""
    rng = np.random.default_rng(seed)
    X = rng.normal(0, 1, (n_samples, n_features))
    # Add some structure: first 5 features are correlated
    X[:, 1] = X[:, 0] * 0.7 + rng.normal(0, 0.3, n_samples)
    X[:, 2] = X[:, 0] * 0.5 + rng.normal(0, 0.5, n_samples)
    X[:, 3] = X[:, 1] * 0.8 + rng.normal(0, 0.2, n_samples)
    X[:, 4] = -X[:, 0] * 0.3 + rng.normal(0, 0.7, n_samples)
    return X


def sample_feature_names(n_features: int = 45) -> list:
    """Return realistic feature names matching the project's FEATURES list."""
    base = [
        "Close", "High", "Low", "Volume",
        "SMA_7", "SMA_21", "EMA_12", "EMA_26",
        "RSI_14", "MACD", "MACD_Signal", "MACD_Hist",
        "BB_Upper", "BB_Lower", "BB_Width",
        "Volume_SMA_10", "Daily_Return",
        "Close_lag_1", "Close_lag_2", "Close_lag_3",
        "Close_lag_4", "Close_lag_5",
        "Return_lag_1", "Return_lag_2", "Return_lag_3",
        "Above_200SMA", "Dist_200SMA",
        "Body_Ratio", "Displacement",
        "Dist_to_SH", "Dist_to_SL",
        "Structure_Bullish", "PD_Position",
        "Bull_FVG_Count", "Bear_FVG_Count",
        "Bull_OB_Count", "Bear_OB_Count",
        "Dist_PWH", "Dist_PWL",
        "Swept_High", "Swept_Low",
        "Quarter_Sin", "Quarter_Cos",
        "Month_Sin", "Month_Cos",
    ]
    while len(base) < n_features:
        base.append(f"feature_{len(base)}")
    return base[:n_features]
