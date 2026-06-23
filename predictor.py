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

    macd_obj = ta.trend.MACD(close, window_fast=12, window_slow=26, window_sign=9)
    df["MACD"]        = macd_obj.macd()
    df["MACD_Signal"] = macd_obj.macd_signal()
    df["MACD_Hist"]   = macd_obj.macd_diff()

    bb_obj = ta.volatility.BollingerBands(close, window=20, window_dev=2)
    df["BB_Upper"] = bb_obj.bollinger_hband()
    df["BB_Lower"] = bb_obj.bollinger_lband()
    df["BB_Mid"]   = bb_obj.bollinger_mavg()
    df["BB_Width"] = (df["BB_Upper"] - df["BB_Lower"]) / df["BB_Mid"]

    df["Volume_SMA_10"] = ta.trend.sma_indicator(df["Volume"], window=10)
    df["Daily_Return"]  = close.pct_change() * 100

    for lag in range(1, 6):
        df[f"Close_lag_{lag}"]  = close.shift(lag)
        df[f"Return_lag_{lag}"] = df["Daily_Return"].shift(lag)

    # ATR for position sizing (not a model feature)
    hi = high.values
    lo = low.values
    cl = close.values
    tr = np.maximum(hi[1:] - lo[1:],
         np.maximum(np.abs(hi[1:] - cl[:-1]), np.abs(lo[1:] - cl[:-1])))
    df["ATR_14"] = np.nan
    if len(tr) >= 14:
        df.iloc[14:, df.columns.get_loc("ATR_14")] = pd.Series(tr).rolling(14).mean().iloc[13:].values

    # ICT features
    atr14 = ta.volatility.AverageTrueRange(high, low, close, window=14).average_true_range()
    atr14 = atr14.fillna(close * 0.01)

    sma200 = close.rolling(200, min_periods=1).mean()
    df["Above_200SMA"] = (close > sma200).astype(int)
    df["Dist_200SMA"]  = ((close - sma200) / sma200 * 100).fillna(0)

    rng  = (high - low).replace(0, np.nan)
    body = (close - open_).abs()
    df["Body_Ratio"]   = (body / rng).fillna(0).clip(0, 1)
    df["Displacement"] = ((rng.fillna(0) > atr14 * 1.5) & (df["Body_Ratio"] > 0.6)).astype(int)

    sh20 = high.rolling(20).max()
    sl20 = low.rolling(20).min()
    df["Dist_to_SH"]       = ((sh20 - close) / (atr14 + 1e-8)).clip(-10, 10)
    df["Dist_to_SL"]       = ((close - sl20)  / (atr14 + 1e-8)).clip(-10, 10)
    df["Structure_Bullish"] = (sh20 > high.rolling(60).max().shift(20)).astype(int)

    rh = high.rolling(60).max()
    rl = low.rolling(60).min()
    df["PD_Position"] = ((close - rl) / (rh - rl).replace(0, np.nan)).fillna(0.5).clip(0, 1)

    bull_fvg = (low > high.shift(2)).astype(int)
    bear_fvg = (high < low.shift(2)).astype(int)
    df["Bull_FVG_Count"] = bull_fvg.rolling(10, min_periods=1).sum()
    df["Bear_FVG_Count"] = bear_fvg.rolling(10, min_periods=1).sum()

    bearish = (close < open_)
    bullish = (close > open_)
    bull_ob = (bearish.shift(1).fillna(False)) & (df["Displacement"] == 1) & bullish
    bear_ob = (bullish.shift(1).fillna(False)) & (df["Displacement"] == 1) & bearish
    df["Bull_OB_Count"] = bull_ob.astype(int).rolling(10, min_periods=1).sum()
    df["Bear_OB_Count"] = bear_ob.astype(int).rolling(10, min_periods=1).sum()

    pwh = high.rolling(5).max().shift(1)
    pwl = low.rolling(5).min().shift(1)
    df["Dist_PWH"] = ((pwh - close) / (atr14 + 1e-8)).clip(-10, 10)
    df["Dist_PWL"] = ((close - pwl)  / (atr14 + 1e-8)).clip(-10, 10)

    df["Swept_High"] = ((high > sh20.shift(1)) & (close < sh20.shift(1))).astype(int)
    df["Swept_Low"]  = ((low  < sl20.shift(1)) & (close > sl20.shift(1))).astype(int)

    q = df.index.quarter
    m = df.index.month
    df["Quarter_Sin"] = np.sin(2 * np.pi * q / 4)
    df["Quarter_Cos"] = np.cos(2 * np.pi * q / 4)
    df["Month_Sin"]   = np.sin(2 * np.pi * m / 12)
    df["Month_Cos"]   = np.cos(2 * np.pi * m / 12)

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
