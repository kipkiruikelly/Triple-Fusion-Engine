"""
train_all_tickers.py
Train LR + RF models for all supported tickers.

Usage:
    python train_all_tickers.py
    python train_all_tickers.py --tickers AAPL TSLA MSFT
    python train_all_tickers.py --upload   # upload to Azure after training
"""

import os
import sys
import argparse
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
import joblib
import ta
from sklearn.linear_model import LinearRegression
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import MinMaxScaler
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(BASE_DIR, "Saved Models")

DEFAULT_TICKERS = ["AAPL", "TSLA", "MSFT", "GOOGL", "NVDA", "META", "AMZN"]


def fetch_data(ticker: str) -> pd.DataFrame:
    yf_ticker = ticker.replace(".", "-")
    df = yf.download(yf_ticker, period="5y", auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["SMA_7"]  = ta.trend.sma_indicator(df["Close"], window=7)
    df["SMA_21"] = ta.trend.sma_indicator(df["Close"], window=21)
    df["EMA_12"] = ta.trend.ema_indicator(df["Close"], window=12)
    df["EMA_26"] = ta.trend.ema_indicator(df["Close"], window=26)
    df["RSI_14"] = ta.momentum.rsi(df["Close"], window=14)

    macd = ta.trend.MACD(df["Close"])
    df["MACD"]        = macd.macd()
    df["MACD_Signal"] = macd.macd_signal()
    df["MACD_Hist"]   = macd.macd_diff()

    bb = ta.volatility.BollingerBands(df["Close"], window=20, window_dev=2)
    df["BB_Upper"] = bb.bollinger_hband()
    df["BB_Lower"] = bb.bollinger_lband()
    df["BB_Width"] = (bb.bollinger_hband() - bb.bollinger_lband()) / bb.bollinger_mavg()

    df["Volume_SMA_10"] = ta.trend.sma_indicator(df["Volume"], window=10)
    df["Daily_Return"]  = df["Close"].pct_change() * 100

    for lag in range(1, 6):
        df[f"Close_lag_{lag}"]  = df["Close"].shift(lag)
    for lag in range(1, 4):
        df[f"Return_lag_{lag}"] = df["Daily_Return"].shift(lag)

    df["Next_Return"] = df["Daily_Return"].shift(-1)
    df.dropna(inplace=True)
    return df


def train_ticker(ticker: str) -> dict:
    print(f"\n[{ticker}] Fetching data...")
    df = fetch_data(ticker)
    if df.empty or len(df) < 200:
        print(f"[{ticker}] Insufficient data — skipping.")
        return {"ticker": ticker, "status": "skipped"}

    df = engineer_features(df)
    print(f"[{ticker}] {len(df)} rows after feature engineering.")

    feature_cols = [c for c in df.columns if c not in
                    ["Open", "BB_Mid", "Next_Return", "Next_Close", "Volume"]]

    X = df[feature_cols].values
    y = df["Next_Return"].values

    split1 = int(len(X) * 0.8)
    split2 = int(len(X) * 0.9)
    X_train, X_val, X_test = X[:split1], X[split1:split2], X[split2:]
    y_train, y_val, y_test = y[:split1], y[split1:split2], y[split2:]

    scaler = MinMaxScaler()
    X_train = scaler.fit_transform(X_train)
    X_val   = scaler.transform(X_val)
    X_test  = scaler.transform(X_test)

    lr = LinearRegression()
    lr.fit(X_train, y_train)
    lr_pred = lr.predict(X_test)
    lr_mae  = mean_absolute_error(y_test, lr_pred)
    lr_r2   = r2_score(y_test, lr_pred)

    rf = RandomForestRegressor(n_estimators=300, max_depth=12,
                               n_jobs=-1, random_state=42)
    rf.fit(X_train, y_train)
    rf_pred = rf.predict(X_test)
    rf_mae  = mean_absolute_error(y_test, rf_pred)
    rf_r2   = r2_score(y_test, rf_pred)

    os.makedirs(MODELS_DIR, exist_ok=True)
    joblib.dump(lr,           os.path.join(MODELS_DIR, f"lr_model_{ticker}.pkl"))
    joblib.dump(rf,           os.path.join(MODELS_DIR, f"rf_model_{ticker}.pkl"))
    joblib.dump(scaler,       os.path.join(MODELS_DIR, f"scaler_sklearn_{ticker}.pkl"))
    joblib.dump(feature_cols, os.path.join(MODELS_DIR, f"feature_cols_sklearn_{ticker}.pkl"))

    print(f"[{ticker}] LR  — MAE: {lr_mae:.4f}  R2: {lr_r2:.4f}")
    print(f"[{ticker}] RF  — MAE: {rf_mae:.4f}  R2: {rf_r2:.4f}")
    print(f"[{ticker}] Models saved to Saved Models/")

    return {
        "ticker": ticker,
        "status": "ok",
        "lr_mae": round(lr_mae, 4),
        "lr_r2":  round(lr_r2, 4),
        "rf_mae": round(rf_mae, 4),
        "rf_r2":  round(rf_r2, 4),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tickers", nargs="+", default=DEFAULT_TICKERS)
    parser.add_argument("--upload",  action="store_true",
                        help="Upload models to Azure after training")
    args = parser.parse_args()

    results = []
    for ticker in [t.upper() for t in args.tickers]:
        results.append(train_ticker(ticker))

    print("\n=== Training Summary ===")
    for r in results:
        if r["status"] == "ok":
            print(f"  {r['ticker']:6s} LR MAE={r['lr_mae']}  RF MAE={r['rf_mae']}")
        else:
            print(f"  {r['ticker']:6s} {r['status']}")

    if args.upload:
        from azure_storage import upload_models_to_azure
        print("\nUploading to Azure...")
        for r in results:
            if r["status"] == "ok":
                upload_models_to_azure(r["ticker"])


if __name__ == "__main__":
    main()
