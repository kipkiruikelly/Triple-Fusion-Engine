"""
predictor.py
Shared ML inference layer for BullLogic.

Public functions:
  run_prediction(ticker, interval="1d") → full result dict (Flask routes)
  ml_signal(ticker, interval="1d")      → compact trading signal dict

Supported intervals:
  "1d"  — daily models (45 features, TA + ICT daily)
  "1h"  — hourly models (55 features, + kill zones + session)
"""

import os
import json
import pytz
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import joblib
import yfinance as yf
import ta

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(BASE_DIR, "Saved Models")

YF_SYMBOL_MAP = {"NDX": "^NDX"}

# Per-(ticker, interval) model cache so we only load from disk once
_model_cache: dict = {}


def _model_suffix(interval: str) -> str:
    return "" if interval == "1d" else f"_{interval}"


def _load_models(ticker: str, interval: str = "1d"):
    """Return (lr, rf, scaler, feature_cols) — cached after first load."""
    key = (ticker.upper(), interval)
    if key in _model_cache:
        return _model_cache[key]

    suffix = _model_suffix(interval)
    t = ticker.upper()
    lr    = joblib.load(os.path.join(MODELS_DIR, f"lr_model_{t}{suffix}.pkl"))
    rf    = joblib.load(os.path.join(MODELS_DIR, f"rf_model_{t}{suffix}.pkl"))
    sc    = joblib.load(os.path.join(MODELS_DIR, f"scaler_sklearn_{t}{suffix}.pkl"))
    feat  = joblib.load(os.path.join(MODELS_DIR, f"feature_cols_sklearn_{t}{suffix}.pkl"))
    _model_cache[key] = (lr, rf, sc, feat)
    return lr, rf, sc, feat


def _fetch_df(ticker: str, interval: str = "1d") -> pd.DataFrame:
    yf_ticker = YF_SYMBOL_MAP.get(ticker.upper(), ticker.replace(".", "-"))
    period    = "730d" if interval == "1h" else "6mo"
    df = yf.download(yf_ticker, period=period, interval=interval,
                     auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


# ── Feature engineering ────────────────────────────────────────────────────────

def _add_base_ta(df: pd.DataFrame) -> pd.DataFrame:
    close = df["Close"]
    high  = df["High"]
    low   = df["Low"]
    open_ = df["Open"]

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
    for lag in range(1, 4):
        df[f"Return_lag_{lag}"] = df["Daily_Return"].shift(lag)

    # ATR for position sizing (not a model feature, kept for ml_signal)
    atr14 = ta.volatility.AverageTrueRange(high, low, close, window=14).average_true_range()
    atr14 = atr14.fillna(close * 0.01)
    df["ATR_14"] = atr14

    # ICT — base features (work on all timeframes)
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
    """Kill-zone and session features — only meaningful on sub-daily bars."""
    idx = df.index
    if idx.tz is not None:
        et_idx = idx.tz_convert("America/New_York")
    else:
        et_idx = idx.tz_localize("UTC").tz_convert("America/New_York")

    hour = et_idx.hour

    df["In_London_KZ"]  = ((hour >= 3)  & (hour < 5)).astype(int)
    df["In_NY_Open_KZ"] = ((hour >= 9)  & (hour < 11)).astype(int)
    df["In_NY_PM_KZ"]   = ((hour >= 13) & (hour < 15)).astype(int)

    date_str     = pd.Series(et_idx.date, index=df.index)
    midnight_open = df.groupby(date_str)["Open"].transform("first")
    df["Price_vs_MidnightOpen"] = (
        (df["Close"] - midnight_open) / (midnight_open + 1e-8) * 100
    )

    session_high = df.groupby(date_str)["High"].transform("cummax")
    session_low  = df.groupby(date_str)["Low"].transform("cummin")
    atr_h = ta.volatility.AverageTrueRange(
        df["High"], df["Low"], df["Close"], window=14
    ).average_true_range().fillna(df["Close"] * 0.01)
    df["Session_High_Dist"] = ((session_high - df["Close"]) / (atr_h + 1e-8)).clip(-10, 10)
    df["Session_Low_Dist"]  = ((df["Close"] - session_low)  / (atr_h + 1e-8)).clip(-10, 10)

    df["Hour_Sin"] = np.sin(2 * np.pi * hour / 24)
    df["Hour_Cos"] = np.cos(2 * np.pi * hour / 24)
    dow = et_idx.dayofweek
    df["Day_Sin"] = np.sin(2 * np.pi * dow / 5)
    df["Day_Cos"] = np.cos(2 * np.pi * dow / 5)

    # ICT 2022 — Silver Bullet windows (ET)
    df["In_SilverBullet_AM"] = ((hour >= 10) & (hour < 11)).astype(int)
    df["In_SilverBullet_PM"] = ((hour >= 14) & (hour < 15)).astype(int)

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


def build_features(df: pd.DataFrame, interval: str = "1d") -> pd.DataFrame:
    df = _add_base_ta(df)
    if interval != "1d":
        df = _add_intraday_ict(df)
    df.dropna(inplace=True)
    return df


# ── Public API ─────────────────────────────────────────────────────────────────

def run_prediction(ticker: str, interval: str = "1d") -> dict:
    """Full prediction result dict for Flask routes and the result page."""
    ticker = ticker.upper()
    min_bars = 70 if interval == "1d" else 200

    df = _fetch_df(ticker, interval)
    if df.empty or len(df) < min_bars:
        raise ValueError(
            f"Not enough data for '{ticker}' on {interval} interval. "
            "Check the ticker symbol."
        )

    df = build_features(df, interval)
    if df.empty:
        raise ValueError("Feature engineering failed — insufficient data history.")

    lr_model, rf_model, scaler, feature_cols = _load_models(ticker, interval)

    current_price = float(df["Close"].iloc[-1])
    X             = scaler.transform(df[feature_cols].iloc[-1:].values)
    lr_pred       = float(lr_model.predict(X)[0])   # next close price
    rf_ret        = float(rf_model.predict(X)[0])   # next % return
    rf_pred       = current_price * (1 + rf_ret / 100)

    price_change = lr_pred - current_price
    direction    = "Up" if price_change > 0 else "Down"
    recent_vol   = float(df["Daily_Return"].tail(20).std())
    change_pct   = abs(price_change / current_price * 100)
    confidence   = min(95, max(51, 50 + (change_pct / max(recent_vol, 0.1)) * 10))

    # Chart data (last 90 bars)
    chart_df     = df.tail(90)
    chart_dates  = [
        d.strftime("%Y-%m-%d %H:%M") if interval != "1d" else d.strftime("%Y-%m-%d")
        for d in chart_df.index
    ]
    chart_prices = [round(float(p), 2) for p in chart_df["Close"]]
    chart_sma7   = [round(float(p), 2) for p in chart_df["SMA_7"]]
    chart_sma21  = [round(float(p), 2) for p in chart_df["SMA_21"]]

    rsi       = round(float(df["RSI_14"].iloc[-1]), 1)
    macd_val  = round(float(df["MACD"].iloc[-1]), 3)
    macd_hist = float(df["MACD_Hist"].iloc[-1])

    # Human-readable timestamp for the last bar
    last_idx = df.index[-1]
    if interval == "1d":
        as_of   = last_idx.strftime("%B %d, %Y")
        horizon = "Next Day"
    else:
        try:
            et = last_idx.tz_convert("America/New_York") if last_idx.tzinfo else last_idx
            as_of = et.strftime("%b %d, %Y %I:%M %p ET")
        except Exception:
            as_of = str(last_idx)
        horizon = "Next Hour" if interval == "1h" else "Next Bar"

    return {
        "ticker"       : ticker,
        "interval"     : interval,
        "horizon"      : horizon,
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
        "as_of"        : as_of,
    }


def ml_signal(ticker: str, interval: str = "1d") -> dict:
    """
    Trading signal for the MT5 auto-trade loop.

    BUY  — LR and RF both predict up
    SELL — both predict down
    HOLD — models disagree
    """
    try:
        ticker = ticker.upper()
        df = _fetch_df(ticker, interval)
        if df.empty or len(df) < 70:
            return {"action": "HOLD", "error": "Insufficient data", "confidence": 0}

        df = build_features(df, interval)
        if df.empty:
            return {"action": "HOLD", "error": "Feature build failed", "confidence": 0}

        lr_model, rf_model, scaler, feature_cols = _load_models(ticker, interval)

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
            action = "HOLD"

        recent_vol = float(df["Daily_Return"].tail(20).std())
        change_pct = abs(lr_pred - current_price) / current_price * 100
        confidence = min(95, max(51, 50 + (change_pct / max(recent_vol, 0.1)) * 10))

        rsi       = float(df["RSI_14"].iloc[-1])
        macd_hist = float(df["MACD_Hist"].iloc[-1])
        atr       = float(df["ATR_14"].iloc[-1]) if "ATR_14" in df.columns else current_price * 0.01

        return {
            "action"       : action,
            "interval"     : interval,
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
