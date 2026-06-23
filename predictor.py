"""
predictor.py
Shared ML prediction layer for ML-QTS.

Loads LR + RF models once and exposes two public functions:
  run_prediction(ticker) → full result dict (used by Flask routes)
  ml_signal(ticker)      → {"action": BUY|SELL|HOLD, "lr_pred", "rf_pred",
                             "current_price", "rf_ret", "confidence",
                             "rsi", "macd_hist", "atr"}
                           (used by the trading loop)
"""

import os
import json
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import joblib
import yfinance as yf
import ta

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(BASE_DIR, "Saved Models")

print("Loading ML models...")
lr_model     = joblib.load(os.path.join(MODELS_DIR, "lr_model_QQQ.pkl"))
rf_model     = joblib.load(os.path.join(MODELS_DIR, "rf_model_QQQ.pkl"))
scaler       = joblib.load(os.path.join(MODELS_DIR, "scaler_sklearn_QQQ.pkl"))
feature_cols = joblib.load(os.path.join(MODELS_DIR, "feature_cols_sklearn_QQQ.pkl"))
print("ML models loaded.")


def build_features(df: pd.DataFrame) -> pd.DataFrame:
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

    for lag in range(1, 6):
        df[f"Close_lag_{lag}"]  = df["Close"].shift(lag)
        df[f"Return_lag_{lag}"] = df["Daily_Return"].shift(lag)

    # ATR (not a feature col but needed for position sizing)
    hi = df["High"].values
    lo = df["Low"].values
    cl = df["Close"].values
    tr = np.maximum(hi[1:] - lo[1:],
         np.maximum(np.abs(hi[1:] - cl[:-1]), np.abs(lo[1:] - cl[:-1])))
    df["ATR_14"] = np.nan
    if len(tr) >= 14:
        df.iloc[14:, df.columns.get_loc("ATR_14")] = pd.Series(tr).rolling(14).mean().iloc[13:].values

    df.dropna(inplace=True)
    return df


def _fetch_df(ticker: str) -> pd.DataFrame:
    yf_ticker = ticker.replace(".", "-")
    df = yf.download(yf_ticker, period="6mo", auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


def run_prediction(ticker: str) -> dict:
    """Full prediction result for Flask routes and the result page."""
    df = _fetch_df(ticker)
    if df.empty or len(df) < 70:
        raise ValueError(f"Not enough data for '{ticker}'. Please check the ticker symbol.")

    df = build_features(df)
    if df.empty:
        raise ValueError("Feature engineering failed — insufficient data history.")

    current_price = float(df["Close"].iloc[-1])
    X             = scaler.transform(df[feature_cols].iloc[-1:].values)
    lr_pred       = float(lr_model.predict(X)[0])
    rf_ret        = float(rf_model.predict(X)[0])
    rf_pred       = current_price * (1 + rf_ret / 100)

    price_change = lr_pred - current_price
    direction    = "Up" if price_change > 0 else "Down"
    recent_vol   = float(df["Daily_Return"].tail(20).std())
    change_pct   = abs(price_change / current_price * 100)
    confidence   = min(95, max(51, 50 + (change_pct / max(recent_vol, 0.1)) * 10))

    chart_df     = df.tail(90)
    chart_dates  = [d.strftime("%Y-%m-%d") for d in chart_df.index]
    chart_prices = [round(float(p), 2) for p in chart_df["Close"]]
    chart_sma7   = [round(float(p), 2) for p in chart_df["SMA_7"]]
    chart_sma21  = [round(float(p), 2) for p in chart_df["SMA_21"]]

    rsi       = round(float(df["RSI_14"].iloc[-1]), 1)
    macd_val  = round(float(df["MACD"].iloc[-1]), 3)
    macd_hist = float(df["MACD_Hist"].iloc[-1])

    return {
        "ticker"       : ticker.upper(),
        "current_price": round(current_price, 2),
        "lr_pred"      : round(lr_pred, 2),
        "rf_pred"      : round(rf_pred, 2),
        "lstm_pred"    : "N/A",
        "primary_pred" : round(lr_pred, 2),
        "price_change" : round(price_change, 2),
        "change_pct"   : round(change_pct, 2),
        "direction"    : direction,
        "confidence"   : round(confidence, 1),
        "chart_dates"  : json.dumps(chart_dates),
        "chart_prices" : json.dumps(chart_prices),
        "chart_sma7"   : json.dumps(chart_sma7),
        "chart_sma21"  : json.dumps(chart_sma21),
        "rsi"          : rsi,
        "rsi_signal"   : "Overbought" if rsi >= 70 else ("Oversold" if rsi <= 30 else "Neutral"),
        "macd"         : macd_val,
        "macd_signal"  : "Bullish" if macd_hist > 0 else "Bearish",
        "bb_upper"     : round(float(df["BB_Upper"].iloc[-1]), 2),
        "bb_lower"     : round(float(df["BB_Lower"].iloc[-1]), 2),
        "as_of"        : df.index[-1].strftime("%B %d, %Y"),
    }


def ml_signal(ticker: str) -> dict:
    """
    Distill the ML models into a trading signal for the auto-trade loop.

    Logic:
      LR direction  = "up"  if lr_pred > current_price, else "down"
      RF direction  = "up"  if rf_ret > 0,             else "down"
      ML action     = BUY  if both say "up"
                    = SELL if both say "down"
                    = HOLD if they disagree

    Returns a dict consumed by MT5Trader.generate_signal_ml().
    """
    try:
        df = _fetch_df(ticker)
        if df.empty or len(df) < 70:
            return {"action": "HOLD", "error": "Insufficient data", "confidence": 0}

        df = build_features(df)
        if df.empty:
            return {"action": "HOLD", "error": "Feature build failed", "confidence": 0}

        current_price = float(df["Close"].iloc[-1])
        X             = scaler.transform(df[feature_cols].iloc[-1:].values)
        lr_pred       = float(lr_model.predict(X)[0])
        rf_ret        = float(rf_model.predict(X)[0])
        rf_pred       = current_price * (1 + rf_ret / 100)

        lr_up = lr_pred > current_price
        rf_up = rf_ret  > 0

        if lr_up and rf_up:
            action = "BUY"
        elif not lr_up and not rf_up:
            action = "SELL"
        else:
            action = "HOLD"   # models disagree — stay flat

        # Confidence based on predicted move vs recent volatility
        recent_vol = float(df["Daily_Return"].tail(20).std())
        change_pct = abs(lr_pred - current_price) / current_price * 100
        confidence = min(95, max(51, 50 + (change_pct / max(recent_vol, 0.1)) * 10))

        rsi       = float(df["RSI_14"].iloc[-1])
        macd_hist = float(df["MACD_Hist"].iloc[-1])
        atr       = float(df["ATR_14"].iloc[-1]) if "ATR_14" in df.columns else current_price * 0.01

        return {
            "action"       : action,
            "current_price": round(current_price, 5),
            "lr_pred"      : round(lr_pred, 5),
            "rf_pred"      : round(rf_pred, 5),
            "rf_ret"       : round(rf_ret, 4),
            "confidence"   : round(confidence, 1),
            "rsi"          : round(rsi, 2),
            "macd_hist"    : round(macd_hist, 6),
            "atr"          : round(atr, 6),
        }

    except Exception as e:
        return {"action": "HOLD", "error": str(e), "confidence": 0}
