"""
train_1min.py, 1-minute model training via Alpaca historical data

Pulls 2+ years of 1-min bars from Alpaca for each ticker, engineers
features, trains LR + RF classifiers, and saves models to Saved Models/
using the same naming convention as train_all_tickers.py.

Usage:
    python train_1min.py                     # all tickers
    python train_1min.py --tickers QQQ AAPL  # specific tickers
"""

import os, sys, warnings, argparse
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import joblib
from datetime import datetime, timedelta

from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import accuracy_score, classification_report

import ta

# ── Alpaca client ────────────────────────────────────────────────────────────
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

ALPACA_KEY    = os.environ.get("ALPACA_API_KEY", "")
ALPACA_SECRET = os.environ.get("ALPACA_SECRET_KEY", "")

if not ALPACA_KEY or not ALPACA_SECRET:
    sys.exit("ERROR: Set ALPACA_API_KEY and ALPACA_SECRET_KEY env vars (see .env)")

client = StockHistoricalDataClient(api_key=ALPACA_KEY, secret_key=ALPACA_SECRET)

# ── Config ───────────────────────────────────────────────────────────────────
TICKERS   = ["QQQ", "AAPL", "NVDA", "TSLA", "MSFT", "GOOGL", "META", "AMZN", "NDX", "DIA"]
START     = datetime(2024, 1, 2)
END       = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
MODEL_DIR = "Saved Models"
INTERVAL  = "1m"

# NDX isn't a tradeable stock on Alpaca, use QQQ as proxy
ALPACA_SYMBOL_MAP = {"NDX": "QQQ"}

os.makedirs(MODEL_DIR, exist_ok=True)


def fetch_1min(ticker: str) -> pd.DataFrame:
    symbol = ALPACA_SYMBOL_MAP.get(ticker, ticker)
    print(f"  Fetching {symbol} 1-min bars {START.date()} → {END.date()} ...")

    # Pull in monthly chunks to avoid timeout/limit issues
    chunks = []
    cursor = START
    while cursor < END:
        chunk_end = min(cursor + timedelta(days=30), END)
        try:
            req = StockBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=TimeFrame.Minute,
                start=cursor,
                end=chunk_end,
            )
            bars = client.get_stock_bars(req)
            df   = bars.df
            if not df.empty:
                # Drop symbol level from MultiIndex if present
                if isinstance(df.index, pd.MultiIndex):
                    df = df.droplevel(0)
                chunks.append(df)
                print(f"    {cursor.date()} → {chunk_end.date()}: {len(df):,} bars")
        except Exception as e:
            print(f"    {cursor.date()} → {chunk_end.date()}: ERROR {e}")
        cursor = chunk_end

    if not chunks:
        raise ValueError(f"No data returned for {symbol}")

    df = pd.concat(chunks).sort_index()
    df = df[~df.index.duplicated(keep="last")]

    # Rename Alpaca columns → standard OHLCV
    df = df.rename(columns={"open": "Open", "high": "High", "low": "Low",
                             "close": "Close", "volume": "Volume"})
    df.index.name = "Date"

    # Keep only market hours (09:30-16:00 ET)
    df.index = pd.to_datetime(df.index, utc=True).tz_convert("America/New_York")
    df = df.between_time("09:30", "16:00")

    print(f"  Total: {len(df):,} bars after filtering")
    return df[["Open", "High", "Low", "Close", "Volume"]]


def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    c = df["Close"]
    h = df["High"]
    l = df["Low"]
    v = df["Volume"]

    # ── Price-derived ────────────────────────────────────────────────────────
    df["Returns"]       = c.pct_change()
    df["Log_Returns"]   = np.log(c / c.shift(1))
    df["HL_Range"]      = (h - l) / c
    df["CO_Move"]       = (c - df["Open"]) / df["Open"]

    # ── Moving averages ──────────────────────────────────────────────────────
    for p in [5, 10, 20, 50, 200]:
        df[f"SMA_{p}"]    = c.rolling(p, min_periods=1).mean()
        df[f"SMA_{p}_r"]  = c / df[f"SMA_{p}"] - 1   # ratio to SMA

    df["EMA_9"]  = ta.trend.ema_indicator(c, window=9)
    df["EMA_21"] = ta.trend.ema_indicator(c, window=21)
    df["EMA_50"] = ta.trend.ema_indicator(c, window=50)

    # ── Momentum ─────────────────────────────────────────────────────────────
    df["RSI_14"]    = ta.momentum.rsi(c, window=14)
    df["RSI_7"]     = ta.momentum.rsi(c, window=7)
    df["Stoch_K"]   = ta.momentum.stoch(h, l, c, window=14, smooth_window=3)
    df["Stoch_D"]   = ta.momentum.stoch_signal(h, l, c, window=14, smooth_window=3)
    df["ROC_5"]     = ta.momentum.roc(c, window=5)
    df["ROC_10"]    = ta.momentum.roc(c, window=10)
    df["ROC_20"]    = ta.momentum.roc(c, window=20)
    df["Williams_R"]= ta.momentum.williams_r(h, l, c, lbp=14)

    # ── Trend ────────────────────────────────────────────────────────────────
    macd_ind        = ta.trend.MACD(c)
    df["MACD"]      = macd_ind.macd()
    df["MACD_Sig"]  = macd_ind.macd_signal()
    df["MACD_Diff"] = macd_ind.macd_diff()
    df["ADX"]       = ta.trend.adx(h, l, c, window=14)
    df["CCI"]       = ta.trend.cci(h, l, c, window=20)

    # ── Volatility ───────────────────────────────────────────────────────────
    bb              = ta.volatility.BollingerBands(c, window=20)
    df["BB_Upper"]  = bb.bollinger_hband()
    df["BB_Lower"]  = bb.bollinger_lband()
    df["BB_Width"]  = (df["BB_Upper"] - df["BB_Lower"]) / c
    df["BB_Pos"]    = (c - df["BB_Lower"]) / (df["BB_Upper"] - df["BB_Lower"] + 1e-9)
    df["ATR_14"]    = ta.volatility.average_true_range(h, l, c, window=14)
    df["ATR_r"]     = df["ATR_14"] / c

    # ── Volume ───────────────────────────────────────────────────────────────
    df["Volume_SMA20"] = v.rolling(20, min_periods=1).mean()
    df["Volume_Ratio"] = v / (df["Volume_SMA20"] + 1)
    df["OBV"]          = ta.volume.on_balance_volume(c, v)
    df["VWAP_ratio"]   = c / (ta.volume.volume_weighted_average_price(h, l, c, v, window=14) + 1e-9)

    # ── ICT-style intraday features ──────────────────────────────────────────
    # Session VWAP (rolling intraday, approximate with 390-bar window)
    df["Session_VWAP"]    = ta.volume.volume_weighted_average_price(h, l, c, v, window=390)
    df["VWAP_dist"]       = (c - df["Session_VWAP"]) / df["Session_VWAP"]

    # Kill zones (NY time)
    hour = df.index.hour
    df["KZ_London"]       = ((hour >= 2) & (hour < 5)).astype(int)
    df["KZ_NY_Open"]      = ((hour >= 9) & (hour < 11)).astype(int)
    df["KZ_NY_PM"]        = ((hour >= 13) & (hour < 16)).astype(int)
    df["KZ_London_Close"] = ((hour >= 10) & (hour < 12)).astype(int)

    # Time-of-day features
    df["Minutes_Into_Session"] = (hour - 9) * 60 + df.index.minute - 30
    df["Minutes_Into_Session"] = df["Minutes_Into_Session"].clip(0, 390)
    df["Session_Pct"]          = df["Minutes_Into_Session"] / 390

    # Day of week
    df["DayOfWeek"] = df.index.dayofweek

    # Fair Value Gap (simplified: gap between current candle and 2 bars ago)
    df["FVG_Bull"] = ((l > h.shift(2)) & (c > df["Open"])).astype(int)
    df["FVG_Bear"] = ((h < l.shift(2)) & (c < df["Open"])).astype(int)

    # Displacement (3× ATR move)
    df["Displacement"] = (df["Returns"].abs() > 3 * df["ATR_r"]).astype(int)

    # Liquidity sweep (wick past prior high/low then reversal)
    df["Sweep_High"] = ((h > h.shift(1)) & (c < h.shift(1))).astype(int)
    df["Sweep_Low"]  = ((l < l.shift(1)) & (c > l.shift(1))).astype(int)

    return df


def make_target(df: pd.DataFrame, lookahead: int = 5) -> pd.Series:
    """Binary: 1 if price is higher in `lookahead` bars, else 0."""
    future = df["Close"].shift(-lookahead)
    return (future > df["Close"]).astype(int)


def train_ticker(ticker: str):
    print(f"\n{'='*55}")
    print(f"  Training {ticker}, 1-minute")
    print(f"{'='*55}")

    # 1. Fetch data
    df_raw = fetch_1min(ticker)

    # 2. Engineer features
    df = engineer_features(df_raw)
    df["Target"] = make_target(df, lookahead=5)

    # 3. Drop NaNs
    df = df.dropna()
    df = df[df["Target"].notna()]

    if len(df) < 1000:
        print(f"  SKIP, only {len(df)} usable rows after feature engineering")
        return

    print(f"  Usable rows: {len(df):,}")

    feature_cols = [c for c in df.columns if c not in
                    ["Open", "High", "Low", "Close", "Volume", "Target"]]

    X = df[feature_cols].values
    y = df["Target"].values

    # 4. Train/test split (last 20% as test, time-ordered)
    split = int(len(X) * 0.80)
    X_train, X_test = X[:split], X[split:]
    y_train, y_test = y[:split], y[split:]

    # 5. Scale
    scaler = StandardScaler()
    X_train_s = scaler.fit_transform(X_train)
    X_test_s  = scaler.transform(X_test)

    # 6. Train LR
    print("  Training Logistic Regression ...")
    lr = LogisticRegression(max_iter=1000, C=0.1, class_weight="balanced")
    lr.fit(X_train_s, y_train)
    lr_acc = accuracy_score(y_test, lr.predict(X_test_s))
    print(f"    LR accuracy: {lr_acc:.4f}")

    # 7. Train RF
    print("  Training Random Forest ...")
    rf = RandomForestClassifier(n_estimators=200, max_depth=8, min_samples_leaf=50,
                                 class_weight="balanced", random_state=42, n_jobs=-1)
    rf.fit(X_train_s, y_train)
    rf_acc = accuracy_score(y_test, rf.predict(X_test_s))
    print(f"    RF accuracy: {rf_acc:.4f}")

    # 8. Save models
    suffix = f"_{ticker}_1m"
    joblib.dump(lr,           f"{MODEL_DIR}/lr_model{suffix}.pkl")
    joblib.dump(rf,           f"{MODEL_DIR}/rf_model{suffix}.pkl")
    joblib.dump(scaler,       f"{MODEL_DIR}/scaler_sklearn{suffix}.pkl")
    joblib.dump(feature_cols, f"{MODEL_DIR}/feature_cols_sklearn{suffix}.pkl")

    print(f"  Saved: lr_model{suffix}.pkl  rf_model{suffix}.pkl")
    print(f"         scaler_sklearn{suffix}.pkl  feature_cols_sklearn{suffix}.pkl")
    print(f"  Done, LR={lr_acc:.3f}  RF={rf_acc:.3f}")

    return {"ticker": ticker, "rows": len(df), "lr_acc": lr_acc, "rf_acc": rf_acc}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tickers", nargs="+", default=TICKERS)
    args = parser.parse_args()

    results = []
    for t in args.tickers:
        try:
            r = train_ticker(t)
            if r:
                results.append(r)
        except Exception as e:
            print(f"  ERROR training {t}: {e}")

    if results:
        print(f"\n{'='*55}")
        print("  SUMMARY")
        print(f"{'='*55}")
        print(f"  {'Ticker':<8} {'Rows':>8} {'LR Acc':>8} {'RF Acc':>8}")
        print(f"  {'-'*36}")
        for r in results:
            print(f"  {r['ticker']:<8} {r['rows']:>8,} {r['lr_acc']:>8.3f} {r['rf_acc']:>8.3f}")


if __name__ == "__main__":
    main()
