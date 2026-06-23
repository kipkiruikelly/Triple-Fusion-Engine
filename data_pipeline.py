"""
data_pipeline.py
ML-based Quantitative Trading System

Downloads historical OHLCV data for a given ticker, engineers technical
indicator features, splits the dataset chronologically, scales the features,
builds LSTM input sequences, and saves all outputs to the Data directory.

Usage:
    python data_pipeline.py

Author: Kelvin Kipkirui | DAC-01-0010/2025 | Zetech University
"""

import os
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
import ta
import matplotlib.pyplot as plt
import seaborn as sns
import joblib
from sklearn.preprocessing import MinMaxScaler


# Configuration
TICKER      = "AAPL"
START_DATE  = "2019-01-01"
END_DATE    = "2026-06-01"
LOOKBACK    = 60
TRAIN_RATIO = 0.80
VAL_RATIO   = 0.10

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "Data")
os.makedirs(DATA_DIR, exist_ok=True)

FEATURES = [
    "Open", "High", "Low", "Close", "Volume",
    "SMA_7", "SMA_21", "EMA_12", "EMA_26",
    "RSI_14", "MACD", "MACD_Signal", "MACD_Hist",
    "BB_Upper", "BB_Lower", "BB_Mid", "BB_Width",
    "Volume_SMA_10", "Daily_Return",
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

    print(f"  {len(df):,} trading days — {df.index.min().date()} to {df.index.max().date()}")
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
    axes[0].set_title(f"{ticker} — Price, Moving Averages & Bollinger Bands", fontweight="bold")
    axes[0].set_ylabel("Price (USD)")
    axes[0].legend(loc="upper left", fontsize=9)

    axes[1].plot(df.index, df["RSI_14"], color="#8E44AD", lw=1.2, label="RSI (14)")
    axes[1].axhline(70, color="red",   lw=0.8, linestyle="--", alpha=0.6, label="Overbought (70)")
    axes[1].axhline(30, color="green", lw=0.8, linestyle="--", alpha=0.6, label="Oversold (30)")
    axes[1].set_title(f"{ticker} — RSI (14-period)", fontweight="bold")
    axes[1].set_ylabel("RSI")
    axes[1].set_ylim(0, 100)
    axes[1].legend(fontsize=9)

    colors = df["MACD_Hist"].apply(lambda x: "#27AE60" if x >= 0 else "#E74C3C")
    axes[2].plot(df.index, df["MACD"],        color="#2E75B6", lw=1.2, label="MACD")
    axes[2].plot(df.index, df["MACD_Signal"], color="#E74C3C", lw=1.2, label="Signal")
    axes[2].bar(df.index, df["MACD_Hist"], color=colors, alpha=0.4, width=1)
    axes[2].axhline(0, color="black", lw=0.5)
    axes[2].set_title(f"{ticker} — MACD", fontweight="bold")
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
    ax.set_title(f"{ticker} — Train / Validation / Test Split", fontweight="bold")
    ax.set_ylabel("Close Price (USD)")
    ax.set_xlabel("Date")
    ax.legend()
    plt.tight_layout()
    plt.savefig(os.path.join(DATA_DIR, f"{ticker}_split.png"), dpi=150, bbox_inches="tight")
    plt.close()
    print("  Charts saved to Data/")


def main():
    print(f"\nML-based Quantitative Trading System — Data Pipeline")
    print(f"Ticker: {TICKER} | Period: {START_DATE} to {END_DATE}\n")

    df_raw      = download_data(TICKER, START_DATE, END_DATE)
    df_clean    = clean_data(df_raw)
    df_featured = engineer_features(df_clean)

    print("Splitting data...")
    df_train, df_val, df_test = split_data(df_featured, TRAIN_RATIO, VAL_RATIO)

    X_train_sc, X_val_sc, X_test_sc, scaler, close_idx = scale_features(
        df_train, df_val, df_test, FEATURES, TICKER
    )

    print("Building LSTM sequences...")
    X_train, y_train = build_sequences(X_train_sc, X_train_sc[:, close_idx], LOOKBACK)
    X_val,   y_val   = build_sequences(X_val_sc,   X_val_sc[:,   close_idx], LOOKBACK)
    X_test,  y_test  = build_sequences(X_test_sc,  X_test_sc[:,  close_idx], LOOKBACK)
    print(f"  X_train: {X_train.shape}, X_val: {X_val.shape}, X_test: {X_test.shape}")

    print("Saving outputs...")
    for name, arr in [
        (f"X_train_{TICKER}", X_train), (f"X_val_{TICKER}",   X_val),
        (f"X_test_{TICKER}",  X_test),  (f"y_train_{TICKER}", y_train),
        (f"y_val_{TICKER}",   y_val),   (f"y_test_{TICKER}",  y_test),
    ]:
        np.save(os.path.join(DATA_DIR, f"{name}.npy"), arr)

    df_featured.to_csv(os.path.join(DATA_DIR, f"{TICKER}_featured.csv"))
    save_charts(df_featured, df_train, df_val, df_test, TICKER)

    print(f"\nPipeline complete. All outputs saved to: {DATA_DIR}")
    print("Next step: python model_training.py\n")


if __name__ == "__main__":
    main()
