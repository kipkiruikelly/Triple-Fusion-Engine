"""
data_pipeline.py
ML-based Quantitative Trading System
Phase 2: Multi-ticker parallel fetching, intraday support, centralized config.

Downloads historical OHLCV data for a given ticker, engineers technical
indicator features, splits the dataset chronologically, scales the features,
builds LSTM input sequences, and saves all outputs to the Data directory.

Usage:
    python data_pipeline.py

Author: BullLogic
"""

import os
import warnings
import argparse
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
import ta
import matplotlib.pyplot as plt
import seaborn as sns
import joblib
from concurrent.futures import ThreadPoolExecutor, as_completed
from sklearn.preprocessing import MinMaxScaler


# ── Configuration ───────────────────────────────────────────────────────────────
# Phase 2: Centralized config via config.py with CLI override support

try:
    from config import settings as _cfg
    TICKER      = _cfg.DEFAULT_TICKER
    START_DATE  = _cfg.START_DATE
    END_DATE    = _cfg.END_DATE
    LOOKBACK    = _cfg.LOOKBACK
    TRAIN_RATIO = _cfg.TRAIN_RATIO
    VAL_RATIO   = _cfg.VAL_RATIO
    DEFAULT_TICKERS = _cfg.DEFAULT_TICKERS
    MAX_PARALLEL = _cfg.MAX_PARALLEL_FETCHES
    INTRADAY_INTERVALS = _cfg.INTRADAY_INTERVALS
except ImportError:
    TICKER      = "QQQ"
    START_DATE  = "1999-01-01"
    END_DATE    = "2026-06-01"
    LOOKBACK    = 60
    TRAIN_RATIO = 0.80
    VAL_RATIO   = 0.10
    DEFAULT_TICKERS = ["QQQ", "SPY", "AAPL"]
    MAX_PARALLEL = 5
    INTRADAY_INTERVALS = ["1h"]

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "Data")
os.makedirs(DATA_DIR, exist_ok=True)

FEATURES = [
    "Open", "High", "Low", "Close", "Volume",
    "SMA_7", "SMA_21", "EMA_12", "EMA_26",
    "RSI_14", "MACD", "MACD_Signal", "MACD_Hist",
    "BB_Upper", "BB_Lower", "BB_Mid", "BB_Width",
    "Volume_SMA_10", "Daily_Return",
    # ICT-inspired features
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


def download_data(ticker, start, end):
    print(f"Downloading {ticker} from {start} to {end}...")
    df = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df[["Open", "High", "Low", "Close", "Volume"]]
    df.index = pd.to_datetime(df.index)
    df.index.name = "Date"

    if df.empty:
        raise ValueError(f"No data returned for {ticker}. Check the ticker and date range.")

    print(f"  {len(df):,} trading days, {df.index.min().date()} to {df.index.max().date()}")
    return df


def clean_data(df):
    print("Cleaning data...")
    df = df.copy()
    df = df[~df.index.duplicated(keep="first")]
    df.dropna(how="all", inplace=True)
    df.ffill(inplace=True)
    df = df[df["Volume"] > 0]
    df.sort_index(inplace=True)
    print(f"  {len(df):,} rows after cleaning, {df.isnull().sum().sum()} nulls remaining")
    return df


def engineer_ict_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    ICT (Inner Circle Trader) inspired features derived from OHLCV data.

    Concepts:
      Trend filter     , 200-day SMA direction and distance
      Candle character , body ratio, displacement bars (large range expansion)
      Market structure , distance to 20-bar swing high/low, bullish/bearish bias
      Premium/Discount , price position inside the 60-bar range (0=discount, 1=premium)
      Fair Value Gaps  , 3-bar imbalance (bullish/bearish)
      Order Blocks     , last opposing candle before a displacement move
      Weekly levels    , previous 5-bar high/low as liquidity reference
      Liquidity sweeps , price exceeds swing level then reverses
      Seasonal encoding, quarterly and monthly sin/cos
    """
    close = df["Close"]
    high  = df["High"]
    low   = df["Low"]
    open_ = df["Open"]

    # Trend filter: 200-day SMA
    sma200 = close.rolling(200, min_periods=1).mean()
    df["Above_200SMA"] = (close > sma200).astype(int)
    df["Dist_200SMA"]  = ((close - sma200) / sma200 * 100).fillna(0)

    # Candle character
    rng  = (high - low).replace(0, np.nan)
    body = (close - open_).abs()
    df["Body_Ratio"] = (body / rng).fillna(0).clip(0, 1)
    atr14 = ta.volatility.AverageTrueRange(high, low, close, window=14).average_true_range()
    atr14 = atr14.fillna(close * 0.01)
    df["Displacement"] = ((rng.fillna(0) > atr14 * 1.5) & (df["Body_Ratio"] > 0.6)).astype(int)

    # Market structure
    sh20 = high.rolling(20).max()
    sl20 = low.rolling(20).min()
    df["Dist_to_SH"]       = ((sh20 - close) / (atr14 + 1e-8)).clip(-10, 10)
    df["Dist_to_SL"]       = ((close - sl20)  / (atr14 + 1e-8)).clip(-10, 10)
    df["Structure_Bullish"] = (sh20 > high.rolling(60).max().shift(20)).astype(int)

    # Premium / Discount, position in 60-bar range
    rh = high.rolling(60).max()
    rl = low.rolling(60).min()
    df["PD_Position"] = ((close - rl) / (rh - rl).replace(0, np.nan)).fillna(0.5).clip(0, 1)

    # Fair Value Gaps (3-bar imbalance)
    bull_fvg = (low > high.shift(2)).astype(int)
    bear_fvg = (high < low.shift(2)).astype(int)
    df["Bull_FVG_Count"] = bull_fvg.rolling(10, min_periods=1).sum()
    df["Bear_FVG_Count"] = bear_fvg.rolling(10, min_periods=1).sum()

    # Order Blocks, opposing candle before a displacement move
    bearish = (close < open_)
    bullish = (close > open_)
    bull_ob = (bearish.shift(1).fillna(False)) & (df["Displacement"] == 1) & bullish
    bear_ob = (bullish.shift(1).fillna(False)) & (df["Displacement"] == 1) & bearish
    df["Bull_OB_Count"] = bull_ob.astype(int).rolling(10, min_periods=1).sum()
    df["Bear_OB_Count"] = bear_ob.astype(int).rolling(10, min_periods=1).sum()

    # Weekly levels (prev 5-bar high/low = ~1 trading week)
    pwh = high.rolling(5).max().shift(1)
    pwl = low.rolling(5).min().shift(1)
    df["Dist_PWH"] = ((pwh - close) / (atr14 + 1e-8)).clip(-10, 10)
    df["Dist_PWL"] = ((close - pwl)  / (atr14 + 1e-8)).clip(-10, 10)

    # Liquidity sweeps, price exceeded swing level but closed back inside
    df["Swept_High"] = ((high > sh20.shift(1)) & (close < sh20.shift(1))).astype(int)
    df["Swept_Low"]  = ((low  < sl20.shift(1)) & (close > sl20.shift(1))).astype(int)

    # Seasonal / cyclical encoding
    q = df.index.quarter
    m = df.index.month
    df["Quarter_Sin"] = np.sin(2 * np.pi * q / 4)
    df["Quarter_Cos"] = np.cos(2 * np.pi * q / 4)
    df["Month_Sin"]   = np.sin(2 * np.pi * m / 12)
    df["Month_Cos"]   = np.cos(2 * np.pi * m / 12)

    return df


def engineer_features(df):
    print("Engineering features...")
    df = df.copy()

    df["SMA_7"]  = ta.trend.sma_indicator(df["Close"], window=7)
    df["SMA_21"] = ta.trend.sma_indicator(df["Close"], window=21)
    df["EMA_12"] = ta.trend.ema_indicator(df["Close"], window=12)
    df["EMA_26"] = ta.trend.ema_indicator(df["Close"], window=26)
    df["RSI_14"] = ta.momentum.rsi(df["Close"], window=14)

    macd_obj = ta.trend.MACD(df["Close"], window_fast=12, window_slow=26, window_sign=9)
    df["MACD"]        = macd_obj.macd()
    df["MACD_Signal"] = macd_obj.macd_signal()
    df["MACD_Hist"]   = macd_obj.macd_diff()

    bb_obj = ta.volatility.BollingerBands(df["Close"], window=20, window_dev=2)
    df["BB_Upper"] = bb_obj.bollinger_hband()
    df["BB_Lower"] = bb_obj.bollinger_lband()
    df["BB_Mid"]   = bb_obj.bollinger_mavg()
    df["BB_Width"] = (df["BB_Upper"] - df["BB_Lower"]) / df["BB_Mid"]

    df["Volume_SMA_10"] = ta.trend.sma_indicator(df["Volume"], window=10)
    df["Daily_Return"]  = df["Close"].pct_change() * 100
    df["Direction"]     = (df["Close"].shift(-1) > df["Close"]).astype(int)

    df = engineer_ict_features(df)

    # Phase 1: Enhanced ICT features (BOS/CHoCH, Order Flow, Market Structure)
    try:
        from feature_engineering import add_enhanced_ict_features
        df = add_enhanced_ict_features(df)
    except ImportError:
        pass  # feature_engineering.py is optional

    # Phase 1: Alpha features for ML models
    try:
        from alphas import add_alpha_features
        df = add_alpha_features(df)
    except ImportError:
        pass  # alphas.py is loaded separately

    before = len(df)
    df.dropna(inplace=True)
    print(f"  {len(df):,} rows after feature engineering ({before - len(df)} dropped for warm-up)")
    return df


def split_data(df, train_ratio, val_ratio):
    n         = len(df)
    train_end = int(n * train_ratio)
    val_end   = int(n * (train_ratio + val_ratio))

    df_train = df.iloc[:train_end]
    df_val   = df.iloc[train_end:val_end]
    df_test  = df.iloc[val_end:]

    print(f"  Train : {len(df_train):,} rows ({df_train.index.min().date()} to {df_train.index.max().date()})")
    print(f"  Val   : {len(df_val):,} rows ({df_val.index.min().date()} to {df_val.index.max().date()})")
    print(f"  Test  : {len(df_test):,} rows ({df_test.index.min().date()} to {df_test.index.max().date()})")
    return df_train, df_val, df_test


def scale_features(df_train, df_val, df_test, features, ticker):
    print("Scaling features...")
    scaler = MinMaxScaler(feature_range=(0, 1))

    X_train = scaler.fit_transform(df_train[features])
    X_val   = scaler.transform(df_val[features])
    X_test  = scaler.transform(df_test[features])

    joblib.dump(scaler,   os.path.join(DATA_DIR, f"scaler_{ticker}.pkl"))
    joblib.dump(features, os.path.join(DATA_DIR, f"feature_cols_{ticker}.pkl"))

    print(f"  Train: {X_train.shape}, Val: {X_val.shape}, Test: {X_test.shape}")
    return X_train, X_val, X_test, scaler, features.index("Close")


def build_sequences(data, targets, lookback):
    X, y = [], []
    for i in range(lookback, len(data)):
        X.append(data[i - lookback:i])
        y.append(targets[i])
    return np.array(X), np.array(y)


def save_charts(df, df_train, df_val, df_test, ticker):
    print("Saving charts...")
    sns.set_theme(style="whitegrid")

    fig, axes = plt.subplots(3, 1, figsize=(14, 11), sharex=True)

    axes[0].plot(df.index, df["Close"],  color="#1F4E79", lw=1.5, label="Close")
    axes[0].plot(df.index, df["SMA_7"],  color="#E67E22", lw=1.1, linestyle="--", label="SMA 7")
    axes[0].plot(df.index, df["SMA_21"], color="#27AE60", lw=1.1, linestyle="--", label="SMA 21")
    axes[0].fill_between(df.index, df["BB_Upper"], df["BB_Lower"],
                         alpha=0.08, color="#2E75B6", label="Bollinger Bands")
    axes[0].set_title(f"{ticker}, Price, Moving Averages & Bollinger Bands", fontweight="bold")
    axes[0].set_ylabel("Price (USD)")
    axes[0].legend(loc="upper left", fontsize=9)

    axes[1].plot(df.index, df["RSI_14"], color="#8E44AD", lw=1.2, label="RSI (14)")
    axes[1].axhline(70, color="red",   lw=0.8, linestyle="--", alpha=0.6, label="Overbought (70)")
    axes[1].axhline(30, color="green", lw=0.8, linestyle="--", alpha=0.6, label="Oversold (30)")
    axes[1].set_title(f"{ticker}, RSI (14-period)", fontweight="bold")
    axes[1].set_ylabel("RSI")
    axes[1].set_ylim(0, 100)
    axes[1].legend(fontsize=9)

    colors = df["MACD_Hist"].apply(lambda x: "#27AE60" if x >= 0 else "#E74C3C")
    axes[2].plot(df.index, df["MACD"],        color="#2E75B6", lw=1.2, label="MACD")
    axes[2].plot(df.index, df["MACD_Signal"], color="#E74C3C", lw=1.2, label="Signal")
    axes[2].bar(df.index, df["MACD_Hist"], color=colors, alpha=0.4, width=1)
    axes[2].axhline(0, color="black", lw=0.5)
    axes[2].set_title(f"{ticker}, MACD", fontweight="bold")
    axes[2].set_ylabel("MACD")
    axes[2].set_xlabel("Date")
    axes[2].legend(fontsize=9)

    plt.tight_layout()
    plt.savefig(os.path.join(DATA_DIR, f"{ticker}_indicators.png"), dpi=150, bbox_inches="tight")
    plt.close()

    fig, ax = plt.subplots(figsize=(14, 4))
    ax.plot(df_train.index, df_train["Close"], color="#1F4E79", lw=1.5,
            label=f"Train ({len(df_train):,})")
    ax.plot(df_val.index,   df_val["Close"],   color="#F39C12", lw=1.5,
            label=f"Validation ({len(df_val):,})")
    ax.plot(df_test.index,  df_test["Close"],  color="#E74C3C", lw=1.5,
            label=f"Test ({len(df_test):,})")
    ax.axvline(df_val.index[0],  color="#F39C12", linestyle="--", lw=1, alpha=0.5)
    ax.axvline(df_test.index[0], color="#E74C3C", linestyle="--", lw=1, alpha=0.5)
    ax.set_title(f"{ticker}, Train / Validation / Test Split", fontweight="bold")
    ax.set_ylabel("Close Price (USD)")
    ax.set_xlabel("Date")
    ax.legend()
    plt.tight_layout()
    plt.savefig(os.path.join(DATA_DIR, f"{ticker}_split.png"), dpi=150, bbox_inches="tight")
    plt.close()
    print("  Charts saved to Data/")


def run_pipeline_for_ticker(ticker: str, start: str, end: str) -> None:
    """Run the full data pipeline for a single ticker."""
    print(f"\n{'='*60}")
    print(f"  Pipeline: {ticker}  |  {start} → {end}")
    print(f"{'='*60}")

    df_raw      = download_data(ticker, start, end)
    df_clean    = clean_data(df_raw)
    df_featured = engineer_features(df_clean)

    print("Splitting data...")
    df_train, df_val, df_test = split_data(df_featured, TRAIN_RATIO, VAL_RATIO)

    X_train_sc, X_val_sc, X_test_sc, scaler, close_idx = scale_features(
        df_train, df_val, df_test, FEATURES, ticker
    )

    print("Building LSTM sequences...")
    X_train, y_train = build_sequences(X_train_sc, X_train_sc[:, close_idx], LOOKBACK)
    X_val,   y_val   = build_sequences(X_val_sc,   X_val_sc[:,   close_idx], LOOKBACK)
    X_test,  y_test  = build_sequences(X_test_sc,  X_test_sc[:,  close_idx], LOOKBACK)
    print(f"  X_train: {X_train.shape}, X_val: {X_val.shape}, X_test: {X_test.shape}")

    print("Saving outputs...")
    for name, arr in [
        (f"X_train_{ticker}", X_train), (f"X_val_{ticker}",   X_val),
        (f"X_test_{ticker}",  X_test),  (f"y_train_{ticker}", y_train),
        (f"y_val_{ticker}",   y_val),   (f"y_test_{ticker}",  y_test),
    ]:
        np.save(os.path.join(DATA_DIR, f"{name}.npy"), arr)

    df_featured.to_csv(os.path.join(DATA_DIR, f"{ticker}_featured.csv"))
    save_charts(df_featured, df_train, df_val, df_test, ticker)
    print(f"  ✓ {ticker} pipeline complete\n")


def main():
    parser = argparse.ArgumentParser(description="Data Pipeline — Phase 2 multi-ticker")
    parser.add_argument("--ticker",  default=None, metavar="SYM",
                        help="Single ticker (default: QQQ)")
    parser.add_argument("--tickers", nargs="+", metavar="SYM",
                        help="Multiple tickers, space-separated")
    parser.add_argument("--all",     action="store_true",
                        help=f"All default tickers: {DEFAULT_TICKERS}")
    parser.add_argument("--start",   default=START_DATE, metavar="DATE")
    parser.add_argument("--end",     default=END_DATE,   metavar="DATE")
    parser.add_argument("--parallel", default=MAX_PARALLEL, type=int, metavar="N",
                        help=f"Max parallel fetches (default: {MAX_PARALLEL})")
    parser.add_argument("--intraday", action="store_true",
                        help=f"Also fetch intraday data: {INTRADAY_INTERVALS}")
    args = parser.parse_args()

    print(f"\nML-based Quantitative Trading System, Data Pipeline")

    # Determine ticker list
    if args.tickers:
        tickers = args.tickers
    elif args.all:
        tickers = DEFAULT_TICKERS
    else:
        tickers = [args.ticker or TICKER]

    print(f"Tickers: {tickers} | Period: {args.start} to {args.end}")
    print(f"Parallel workers: {args.parallel}\n")

    # Parallel pipeline execution
    if len(tickers) == 1:
        run_pipeline_for_ticker(tickers[0], args.start, args.end)
    else:
        with ThreadPoolExecutor(max_workers=min(args.parallel, len(tickers))) as executor:
            futures = {
                executor.submit(run_pipeline_for_ticker, t, args.start, args.end): t
                for t in tickers
            }
            for future in as_completed(futures):
                t = futures[future]
                try:
                    future.result()
                except Exception as e:
                    print(f"  ✗ {t} FAILED: {e}")

    print(f"\nPipeline complete. Outputs saved to: {DATA_DIR}")
    print("Next step: python model_training.py --all-tickers\n")


if __name__ == "__main__":
    main()