"""
train_all_tickers.py
Train LR + RF models for all supported tickers in parallel.

- LR  predicts Next_Close (price)
- RF  predicts Next_Return (% return over the next bar)
- Supports daily (1d) and intraday (1h, 15m) intervals

Intervals and yfinance history limits:
  1d  — unlimited history   (use period="max" for NDX/QQQ)
  1h  — 730 days            (ICT kill zones + FVG/OB work properly)
  15m — 60 days             (very short; mainly for backtesting)

Usage:
    python train_all_tickers.py
    python train_all_tickers.py --interval 1h
    python train_all_tickers.py --interval 1h --tickers QQQ AAPL
    python train_all_tickers.py --upload
    python train_all_tickers.py --fast
    python train_all_tickers.py --workers 4
"""

import os
import time
import argparse
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import pytz
import yfinance as yf
import joblib
import ta
from concurrent.futures import ThreadPoolExecutor, as_completed
from sklearn.linear_model import LinearRegression
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import MinMaxScaler
from sklearn.metrics import mean_absolute_error, r2_score

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(BASE_DIR, "Saved Models")

DEFAULT_TICKERS = [
    # ── US Stocks ──────────────────────────────────────────────────────────────
    # Tech
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "AMD", "NFLX",
    # Finance
    "JPM", "GS", "BAC", "V", "MA",
    # Healthcare
    "JNJ", "PFE", "UNH",
    # Energy
    "XOM", "CVX",
    # Consumer / Industrials
    "WMT", "HD", "COST", "BA", "DIS",

    # ── ETFs ───────────────────────────────────────────────────────────────────
    "QQQ", "SPY", "IWM", "DIA", "GLD", "SLV", "TLT", "XLF", "XLE",

    # ── Crypto ─────────────────────────────────────────────────────────────────
    "BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "AVAX", "DOGE",
    "DOT", "LINK", "LTC", "MATIC", "UNI", "ATOM",

    # ── Forex ──────────────────────────────────────────────────────────────────
    "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD",
    "EURGBP", "EURJPY", "GBPJPY", "XAUUSD", "XAGUSD",

    # ── Commodities ────────────────────────────────────────────────────────────
    "GOLD", "SILVER", "OIL", "BRENT", "NATGAS", "COPPER",
    "WHEAT", "CORN", "SOYBEAN", "COFFEE",

    # ── Indices ────────────────────────────────────────────────────────────────
    "NDX", "SPX", "DJI", "RUT", "FTSE", "DAX", "NIKKEI", "HSI",
]

YF_SYMBOL_MAP = {
    # ── Indices ───────────────────────────────────────────────────────────────
    "NDX":      "^NDX",
    "SPX":      "^GSPC",
    "DJI":      "^DJI",
    "VIX":      "^VIX",
    "RUT":      "^RUT",
    "FTSE":     "^FTSE",
    "DAX":      "^GDAXI",
    "NIKKEI":   "^N225",
    "HSI":      "^HSI",

    # ── Crypto ────────────────────────────────────────────────────────────────
    "BTC":      "BTC-USD",
    "ETH":      "ETH-USD",
    "BNB":      "BNB-USD",
    "SOL":      "SOL-USD",
    "XRP":      "XRP-USD",
    "ADA":      "ADA-USD",
    "AVAX":     "AVAX-USD",
    "DOGE":     "DOGE-USD",
    "DOT":      "DOT-USD",
    "LINK":     "LINK-USD",
    "LTC":      "LTC-USD",
    "MATIC":    "POL-USD",
    "SHIB":     "SHIB-USD",
    "UNI":      "UNI-USD",
    "ATOM":     "ATOM-USD",

    # ── Forex (spot) ──────────────────────────────────────────────────────────
    "EURUSD":   "EURUSD=X",
    "GBPUSD":   "GBPUSD=X",
    "USDJPY":   "USDJPY=X",
    "AUDUSD":   "AUDUSD=X",
    "USDCAD":   "USDCAD=X",
    "USDCHF":   "USDCHF=X",
    "NZDUSD":   "NZDUSD=X",
    "EURGBP":   "EURGBP=X",
    "EURJPY":   "EURJPY=X",
    "GBPJPY":   "GBPJPY=X",
    "USDMXN":   "MXN=X",
    "USDZAR":   "ZAR=X",
    "XAUUSD":   "XAUUSD=X",
    "XAGUSD":   "XAGUSD=X",

    # ── Commodities (futures) ─────────────────────────────────────────────────
    "GOLD":     "GC=F",
    "SILVER":   "SI=F",
    "OIL":      "CL=F",
    "BRENT":    "BZ=F",
    "NATGAS":   "NG=F",
    "COPPER":   "HG=F",
    "PLATINUM": "PL=F",
    "PALLADIUM":"PA=F",
    "WHEAT":    "ZW=F",
    "CORN":     "ZC=F",
    "SOYBEAN":  "ZS=F",
    "COTTON":   "CT=F",
    "SUGAR":    "SB=F",
    "COCOA":    "CC=F",
    "COFFEE":   "KC=F",
}

MAX_HISTORY_TICKERS = {"NDX", "QQQ", "SPX", "DJI", "RUT", "FTSE", "DAX", "NIKKEI", "HSI",
                        "SPY", "IWM", "DIA", "GLD", "SLV", "TLT", "XLF", "XLE"}

# ── Feature lists ──────────────────────────────────────────────────────────────

DAILY_FEATURE_COLS = [
    "Close", "High", "Low", "Volume",
    "SMA_7", "SMA_21", "EMA_12", "EMA_26",
    "RSI_14", "MACD", "MACD_Signal", "MACD_Hist",
    "BB_Upper", "BB_Lower", "BB_Width",
    "Volume_SMA_10", "Daily_Return",
    "Close_lag_1", "Close_lag_2", "Close_lag_3", "Close_lag_4", "Close_lag_5",
    "Return_lag_1", "Return_lag_2", "Return_lag_3",
    # ICT — daily-timeframe signals
    "Above_200SMA", "Dist_200SMA",
    "Body_Ratio", "Displacement",
    "Dist_to_SH", "Dist_to_SL", "Structure_Bullish",
    "PD_Position",
    "Bull_FVG_Count", "Bear_FVG_Count",
    "Bull_OB_Count", "Bear_OB_Count",
    "Dist_PWH", "Dist_PWL",
    "Swept_High", "Swept_Low",
    "Quarter_Sin", "Quarter_Cos", "Month_Sin", "Month_Cos",
    # ICT 2022 — IPDA, Equal H/L, OTE, CE
    "IPDA_20_High_Dist", "IPDA_20_Low_Dist",
    "IPDA_40_High_Dist", "IPDA_40_Low_Dist",
    "IPDA_60_High_Dist", "IPDA_60_Low_Dist",
    "Equal_Highs", "Equal_Lows",
    "In_OTE_Buy", "In_OTE_Sell",
    "CE_Bull_FVG_Dist", "CE_Bear_FVG_Dist",
]

# Intraday adds kill-zone, session, and 2022 Silver Bullet / Asia range features
INTRADAY_EXTRA_COLS = [
    "In_London_KZ", "In_NY_Open_KZ", "In_NY_PM_KZ",
    "Session_High_Dist", "Session_Low_Dist",
    "Price_vs_MidnightOpen",
    "Hour_Sin", "Hour_Cos",
    "Day_Sin", "Day_Cos",
    # ICT 2022 intraday
    "In_SilverBullet_AM", "In_SilverBullet_PM",
    "Asia_High_Dist", "Asia_Low_Dist", "Asia_Range_Norm",
    "Price_vs_AsiaHigh", "Price_vs_AsiaLow",
    "In_NWOG", "NWOG_Gap_Norm",
]


# ── Data fetching ──────────────────────────────────────────────────────────────

def fetch_data(ticker: str, interval: str = "1d") -> pd.DataFrame:
    yf_ticker = YF_SYMBOL_MAP.get(ticker, ticker.replace(".", "-"))

    if interval == "1d":
        period = "max" if ticker in MAX_HISTORY_TICKERS else "5y"
    elif interval == "1h":
        period = "730d"
    elif interval == "15m":
        period = "60d"
    else:
        raise ValueError(f"Unsupported interval: {interval}")

    df = yf.download(yf_ticker, period=period, interval=interval,
                     auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


# ── Feature engineering ────────────────────────────────────────────────────────

def _add_base_ta(df: pd.DataFrame) -> pd.DataFrame:
    """Standard TA + ICT features shared by all timeframes."""
    close = df["Close"]
    high  = df["High"]
    low   = df["Low"]
    open_ = df["Open"]

    # Standard indicators
    df["SMA_7"]  = ta.trend.sma_indicator(close, window=7)
    df["SMA_21"] = ta.trend.sma_indicator(close, window=21)
    df["EMA_12"] = ta.trend.ema_indicator(close, window=12)
    df["EMA_26"] = ta.trend.ema_indicator(close, window=26)
    df["RSI_14"] = ta.momentum.rsi(close, window=14)

    macd = ta.trend.MACD(close)
    df["MACD"]        = macd.macd()
    df["MACD_Signal"] = macd.macd_signal()
    df["MACD_Hist"]   = macd.macd_diff()

    bb = ta.volatility.BollingerBands(close, window=20, window_dev=2)
    df["BB_Upper"] = bb.bollinger_hband()
    df["BB_Lower"] = bb.bollinger_lband()
    df["BB_Width"] = (bb.bollinger_hband() - bb.bollinger_lband()) / bb.bollinger_mavg()

    df["Volume_SMA_10"] = ta.trend.sma_indicator(df["Volume"], window=10)
    df["Daily_Return"]  = close.pct_change() * 100

    for lag in range(1, 6):
        df[f"Close_lag_{lag}"]  = close.shift(lag)
    for lag in range(1, 4):
        df[f"Return_lag_{lag}"] = df["Daily_Return"].shift(lag)

    # ICT: ATR for normalising distance features
    atr14 = ta.volatility.AverageTrueRange(high, low, close, window=14).average_true_range()
    atr14 = atr14.fillna(close * 0.01)

    sma200 = close.rolling(200, min_periods=1).mean()
    df["Above_200SMA"] = (close > sma200).astype(int)
    df["Dist_200SMA"]  = ((close - sma200) / sma200 * 100).fillna(0)

    rng  = (high - low).replace(0, np.nan)
    body = (close - open_).abs()
    df["Body_Ratio"]   = (body / rng).fillna(0).clip(0, 1)
    df["Displacement"] = ((rng.fillna(0) > atr14 * 1.5) & (df["Body_Ratio"] > 0.6)).astype(int)

    # Market structure
    sh20 = high.rolling(20).max()
    sl20 = low.rolling(20).min()
    df["Dist_to_SH"]       = ((sh20 - close) / (atr14 + 1e-8)).clip(-10, 10)
    df["Dist_to_SL"]       = ((close - sl20)  / (atr14 + 1e-8)).clip(-10, 10)
    df["Structure_Bullish"] = (sh20 > high.rolling(60).max().shift(20)).astype(int)

    # Premium / Discount (60-bar range)
    rh = high.rolling(60).max()
    rl = low.rolling(60).min()
    df["PD_Position"] = ((close - rl) / (rh - rl).replace(0, np.nan)).fillna(0.5).clip(0, 1)

    # Fair Value Gaps
    bull_fvg = (low > high.shift(2)).astype(int)
    bear_fvg = (high < low.shift(2)).astype(int)
    df["Bull_FVG_Count"] = bull_fvg.rolling(10, min_periods=1).sum()
    df["Bear_FVG_Count"] = bear_fvg.rolling(10, min_periods=1).sum()

    # Order Blocks
    bearish = (close < open_)
    bullish = (close > open_)
    bull_ob = (bearish.shift(1).fillna(False)) & (df["Displacement"] == 1) & bullish
    bear_ob = (bullish.shift(1).fillna(False)) & (df["Displacement"] == 1) & bearish
    df["Bull_OB_Count"] = bull_ob.astype(int).rolling(10, min_periods=1).sum()
    df["Bear_OB_Count"] = bear_ob.astype(int).rolling(10, min_periods=1).sum()

    # Previous 5-bar high/low liquidity
    pwh = high.rolling(5).max().shift(1)
    pwl = low.rolling(5).min().shift(1)
    df["Dist_PWH"] = ((pwh - close) / (atr14 + 1e-8)).clip(-10, 10)
    df["Dist_PWL"] = ((close - pwl)  / (atr14 + 1e-8)).clip(-10, 10)

    # Liquidity sweeps
    df["Swept_High"] = ((high > sh20.shift(1)) & (close < sh20.shift(1))).astype(int)
    df["Swept_Low"]  = ((low  < sl20.shift(1)) & (close > sl20.shift(1))).astype(int)

    # Calendar seasonality (daily)
    q = df.index.quarter
    m = df.index.month
    df["Quarter_Sin"] = np.sin(2 * np.pi * q / 4)
    df["Quarter_Cos"] = np.cos(2 * np.pi * q / 4)
    df["Month_Sin"]   = np.sin(2 * np.pi * m / 12)
    df["Month_Cos"]   = np.cos(2 * np.pi * m / 12)

    # ICT 2022 — IPDA lookback levels (20 / 40 / 60 bars)
    for n in [20, 40, 60]:
        df[f"IPDA_{n}_High_Dist"] = ((high.rolling(n).max().shift(1) - close) / (atr14 + 1e-8)).clip(-20, 20)
        df[f"IPDA_{n}_Low_Dist"]  = ((close - low.rolling(n).min().shift(1))  / (atr14 + 1e-8)).clip(-20, 20)

    # ICT 2022 — Equal Highs / Equal Lows (liquidity pools)
    tol   = close * 0.001
    r10h  = high.rolling(10).max().shift(1)
    r10l  = low.rolling(10).min().shift(1)
    df["Equal_Highs"] = ((high - r10h).abs() < tol).astype(int).rolling(10, min_periods=1).sum()
    df["Equal_Lows"]  = ((low  - r10l).abs() < tol).astype(int).rolling(10, min_periods=1).sum()

    # ICT 2022 — OTE zone (Optimal Trade Entry: 0.62–0.79 Fibonacci of 20-bar swing)
    rng20 = (sh20 - sl20).replace(0, np.nan)
    df["In_OTE_Buy"]  = ((close >= sh20 - rng20 * 0.79) & (close <= sh20 - rng20 * 0.62)).astype(int)
    df["In_OTE_Sell"] = ((close >= sl20 + rng20 * 0.62) & (close <= sl20 + rng20 * 0.79)).astype(int)

    # ICT 2022 — Consequent Encroachment (CE) of most recent FVG midpoint
    bull_ce_level = ((high.shift(2) + low) / 2).where(bull_fvg.astype(bool)).ffill()
    bear_ce_level = ((low.shift(2)  + high) / 2).where(bear_fvg.astype(bool)).ffill()
    df["CE_Bull_FVG_Dist"] = ((close - bull_ce_level) / (atr14 + 1e-8)).clip(-10, 10).fillna(0)
    df["CE_Bear_FVG_Dist"] = ((bear_ce_level - close) / (atr14 + 1e-8)).clip(-10, 10).fillna(0)

    return df


def _add_intraday_ict(df: pd.DataFrame) -> pd.DataFrame:
    """
    Intraday-only ICT features.

    Kill zones are based on New York (ET) session times — converted from
    whatever tz yfinance returns (usually UTC for intraday).
    """
    idx = df.index

    # Convert to Eastern Time if tz-aware
    if idx.tz is not None:
        et_idx = idx.tz_convert("America/New_York")
    else:
        # yfinance sometimes returns tz-naive UTC for older data
        et_idx = idx.tz_localize("UTC").tz_convert("America/New_York")

    hour = et_idx.hour

    # ICT Kill Zones (ET hours)
    df["In_London_KZ"]  = ((hour >= 3)  & (hour < 5)).astype(int)   # 03:00-05:00 ET
    df["In_NY_Open_KZ"] = ((hour >= 9)  & (hour < 11)).astype(int)  # 09:30-11:00 ET
    df["In_NY_PM_KZ"]   = ((hour >= 13) & (hour < 15)).astype(int)  # 13:00-15:00 ET (London close)

    # Midnight open — first price of each calendar day (ET)
    date_str = pd.Series(et_idx.date, index=df.index)
    midnight_open = (
        df.groupby(date_str)["Open"]
          .transform("first")
    )
    df["Price_vs_MidnightOpen"] = ((df["Close"] - midnight_open) / (midnight_open + 1e-8) * 100)

    # Intraday session high / low (how far from today's range extremes?)
    session_high = df.groupby(date_str)["High"].transform("cummax")
    session_low  = df.groupby(date_str)["Low"].transform("cummin")
    atr_h = ta.volatility.AverageTrueRange(df["High"], df["Low"], df["Close"], window=14) \
              .average_true_range().fillna(df["Close"] * 0.01)
    df["Session_High_Dist"] = ((session_high - df["Close"]) / (atr_h + 1e-8)).clip(-10, 10)
    df["Session_Low_Dist"]  = ((df["Close"] - session_low)  / (atr_h + 1e-8)).clip(-10, 10)

    # Hour / day-of-week cyclical encoding
    df["Hour_Sin"] = np.sin(2 * np.pi * hour / 24)
    df["Hour_Cos"] = np.cos(2 * np.pi * hour / 24)
    dow = et_idx.dayofweek
    df["Day_Sin"] = np.sin(2 * np.pi * dow / 5)
    df["Day_Cos"] = np.cos(2 * np.pi * dow / 5)

    # ICT 2022 — Silver Bullet windows (ET)
    df["In_SilverBullet_AM"] = ((hour >= 10) & (hour < 11)).astype(int)  # 10–11 AM
    df["In_SilverBullet_PM"] = ((hour >= 14) & (hour < 15)).astype(int)  # 2–3 PM

    # ICT 2022 — Asia session range (8 PM – 2 AM ET)
    is_asia = (hour >= 20) | (hour < 2)
    atr_h2 = ta.volatility.AverageTrueRange(df["High"], df["Low"], df["Close"], window=14) \
               .average_true_range().fillna(df["Close"] * 0.01)
    asia_high_ref = df["High"].where(is_asia).rolling(14, min_periods=1).max().ffill()
    asia_low_ref  = df["Low"].where(is_asia).rolling(14, min_periods=1).min().ffill()
    df["Asia_High_Dist"]    = ((asia_high_ref - df["Close"]) / (atr_h2 + 1e-8)).clip(-10, 10).fillna(0)
    df["Asia_Low_Dist"]     = ((df["Close"] - asia_low_ref)  / (atr_h2 + 1e-8)).clip(-10, 10).fillna(0)
    df["Asia_Range_Norm"]   = ((asia_high_ref - asia_low_ref) / (atr_h2 + 1e-8)).clip(0, 20).fillna(0)
    df["Price_vs_AsiaHigh"] = (df["Close"] > asia_high_ref).astype(int)
    df["Price_vs_AsiaLow"]  = (df["Close"] < asia_low_ref).astype(int)

    # ICT 2022 — New Week Opening Gap (Monday open vs previous Friday close)
    is_monday  = (et_idx.dayofweek == 0)
    prev_close = df["Close"].shift(1)
    nwog_open  = df["Open"].where(is_monday).ffill()
    nwog_close = prev_close.where(is_monday).ffill()
    nwog_lo    = nwog_close.clip(lower=0)
    nwog_hi    = nwog_open
    df["In_NWOG"] = (
        nwog_hi.notna() & nwog_lo.notna() &
        (df["Close"] >= nwog_lo) & (df["Close"] <= nwog_hi)
    ).astype(int)
    week_gap = (df["Open"] - prev_close).where(is_monday).ffill().fillna(0)
    df["NWOG_Gap_Norm"] = (week_gap / (atr_h2 + 1e-8)).clip(-5, 5)

    return df


def engineer_features(df: pd.DataFrame, interval: str = "1d") -> pd.DataFrame:
    df = _add_base_ta(df)
    if interval != "1d":
        df = _add_intraday_ict(df)

    df["Next_Close"]  = df["Close"].shift(-1)
    df["Next_Return"] = (df["Next_Close"] / df["Close"] - 1) * 100
    df.dropna(inplace=True)
    return df


# ── Training ───────────────────────────────────────────────────────────────────

def _feature_list(interval: str) -> list:
    if interval == "1d":
        return DAILY_FEATURE_COLS
    return DAILY_FEATURE_COLS + INTRADAY_EXTRA_COLS


def model_suffix(interval: str) -> str:
    return "" if interval == "1d" else f"_{interval}"


def train_ticker(ticker: str, interval: str = "1d",
                 rf_trees: int = 100, rf_depth: int = 8) -> dict:
    t0 = time.time()
    df = fetch_data(ticker, interval)
    min_rows = 300 if interval == "1d" else 500
    if df.empty or len(df) < min_rows:
        return {"ticker": ticker, "status": "skipped", "elapsed": 0}

    df   = engineer_features(df, interval)
    feat = [c for c in _feature_list(interval) if c in df.columns]

    X      = df[feat].values
    y_px   = df["Next_Close"].values
    y_ret  = df["Next_Return"].values

    split1 = int(len(X) * 0.8)
    split2 = int(len(X) * 0.9)

    X_train, X_test = X[:split1], X[split2:]
    y_px_train      = y_px[:split1]
    y_ret_train     = y_ret[:split1]
    y_px_test       = y_px[split2:]
    close_test      = df["Close"].values[split2:]

    scaler  = MinMaxScaler()
    X_train = scaler.fit_transform(X_train)
    X_test  = scaler.transform(X_test)

    lr = LinearRegression()
    lr.fit(X_train, y_px_train)
    lr_pred = lr.predict(X_test)
    lr_mae  = mean_absolute_error(y_px_test, lr_pred)
    lr_r2   = r2_score(y_px_test, lr_pred)

    rf = RandomForestRegressor(n_estimators=rf_trees, max_depth=rf_depth,
                               n_jobs=2, random_state=42)
    rf.fit(X_train, y_ret_train)
    rf_price_pred = close_test * (1 + rf.predict(X_test) / 100)
    rf_mae = mean_absolute_error(y_px_test, rf_price_pred)
    rf_r2  = r2_score(y_px_test, rf_price_pred)

    suffix = model_suffix(interval)
    os.makedirs(MODELS_DIR, exist_ok=True)
    joblib.dump(lr,     os.path.join(MODELS_DIR, f"lr_model_{ticker}{suffix}.pkl"))
    joblib.dump(rf,     os.path.join(MODELS_DIR, f"rf_model_{ticker}{suffix}.pkl"))
    joblib.dump(scaler, os.path.join(MODELS_DIR, f"scaler_sklearn_{ticker}{suffix}.pkl"))
    joblib.dump(feat,   os.path.join(MODELS_DIR, f"feature_cols_sklearn_{ticker}{suffix}.pkl"))

    return {
        "ticker":  ticker,
        "status":  "ok",
        "rows":    len(df),
        "feat":    len(feat),
        "lr_mae":  round(lr_mae, 4),
        "lr_r2":   round(lr_r2, 4),
        "rf_mae":  round(rf_mae, 4),
        "rf_r2":   round(rf_r2, 4),
        "elapsed": round(time.time() - t0, 1),
    }


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tickers",  nargs="+", default=DEFAULT_TICKERS)
    parser.add_argument("--interval", default="1d",
                        choices=["1d", "1h", "15m"],
                        help="Bar interval: 1d (default), 1h (730d history), 15m (60d history)")
    parser.add_argument("--upload",   action="store_true",
                        help="Upload models to Azure after training")
    parser.add_argument("--fast",     action="store_true",
                        help="RF-50/depth-6 — faster, slightly lower accuracy")
    parser.add_argument("--workers",      type=int, default=None,
                        help="Max parallel workers (default: one per ticker)")
    parser.add_argument("--skip-existing", action="store_true",
                        help="Skip tickers whose model files already exist")
    args = parser.parse_args()

    tickers  = [t.upper() for t in args.tickers]
    rf_trees = 50  if args.fast else 100
    rf_depth = 6   if args.fast else 8
    suffix   = model_suffix(args.interval)

    if args.skip_existing:
        before = len(tickers)
        tickers = [
            t for t in tickers
            if not os.path.exists(os.path.join(MODELS_DIR, f"lr_model_{t}{suffix}.pkl"))
        ]
        print(f"  Skipping {before - len(tickers)} already-trained tickers.\n")

    max_w    = args.workers or min(len(tickers), 8)
    feat_list = _feature_list(args.interval)
    mode_tag  = "fast (RF-50/d6)" if args.fast else "standard (RF-100/d8)"

    history_note = {"1d": "5y/max", "1h": "730d", "15m": "60d"}[args.interval]
    print(f"Interval  : {args.interval}  ({history_note} history)")
    print(f"Mode      : {mode_tag}")
    print(f"Features  : {len(feat_list)}  (TA + ICT"
          + (" + kill zones + session" if args.interval != "1d" else "") + ")")
    print(f"Model tag : *{suffix}.pkl  ('' = daily)")
    print(f"Tickers   : {', '.join(tickers)}\n")

    wall_start = time.time()
    results    = []

    with ThreadPoolExecutor(max_workers=max_w) as ex:
        futures = {
            ex.submit(train_ticker, t, args.interval, rf_trees, rf_depth): t
            for t in tickers
        }
        for fut in as_completed(futures):
            r = fut.result()
            results.append(r)
            t = r["ticker"]
            if r["status"] == "ok":
                print(f"  [{t:6s}] {r['rows']:,} bars  {r['feat']} feats  "
                      f"LR MAE=${r['lr_mae']:.2f}  RF MAE=${r['rf_mae']:.2f}  "
                      f"({r['elapsed']}s)")
            else:
                print(f"  [{t:6s}] {r['status']}")

    wall = time.time() - wall_start
    ok   = [r for r in results if r["status"] == "ok"]
    print(f"\n=== Finished {len(tickers)} tickers in {wall:.1f}s ===")

    if ok:
        print(f"\n{'Ticker':<8} {'LR MAE':>10} {'RF MAE':>10} {'LR R2':>8} {'Bars':>8}")
        print("-" * 50)
        for r in sorted(ok, key=lambda x: x["ticker"]):
            print(f"{r['ticker']:<8} ${r['lr_mae']:>9.2f} ${r['rf_mae']:>9.2f} "
                  f"{r['lr_r2']:>8.4f} {r['rows']:>8,}")

    if args.upload:
        from azure_storage import upload_models_to_azure
        print("\nUploading to Azure...")
        for r in ok:
            upload_models_to_azure(r["ticker"])
            print(f"  {r['ticker']} uploaded.")


if __name__ == "__main__":
    main()
