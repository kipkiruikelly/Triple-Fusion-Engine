"""
predictor.py
Shared ML inference layer for BullLogic.

Public functions:
  run_prediction(ticker, interval="1d") → full result dict (Flask routes)
  ml_signal(ticker, interval="1d")      → compact trading signal dict

Supported intervals:
  "1d" , daily models (45 features, TA + ICT daily)
  "1h" , hourly models (55 features, + kill zones + session)
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

# ── Ticker → sector ETF mapping ───────────────────────────────────────────────

_TICKER_SECTOR_MAP = {
    "AAPL": "XLK", "MSFT": "XLK", "GOOGL": "XLK", "META": "XLK",
    "NVDA": "XLK", "AMD": "XLK", "NFLX": "XLK", "CRM": "XLK", "ADBE": "XLK",
    "AMZN": "XLY", "TSLA": "XLY", "HD": "XLY", "DIS": "XLY", "NKE": "XLY",
    "JPM": "XLF", "GS": "XLF", "BAC": "XLF", "V": "XLF", "MA": "XLF",
    "JNJ": "XLV", "PFE": "XLV", "UNH": "XLV", "ABBV": "XLV", "MRK": "XLV",
    "XOM": "XLE", "CVX": "XLE", "COP": "XLE",
    "WMT": "XLP", "COST": "XLP", "PG": "XLP", "KO": "XLP",
    "BA": "XLI", "GE": "XLI", "CAT": "XLI",
    "QQQ": "SPY", "IWM": "SPY", "DIA": "SPY",
}

_EQUITY_TICKERS = {
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "AMD",
    "NFLX", "JPM", "GS", "BAC", "V", "MA", "JNJ", "PFE", "UNH",
    "XOM", "CVX", "WMT", "HD", "COST", "BA", "DIS", "CRM", "ADBE",
    "ABBV", "MRK", "PG", "KO", "NKE", "CAT", "GE", "COP",
}

_VIX_COLS      = ["VIX_Level", "VIX_Change", "VIX_Percentile_252", "VIX_Regime", "VIX_MA_Ratio"]
_SECTOR_COLS   = ["Sector_RS_20", "Sector_RS_60", "Sector_vs_SPY_20", "Sector_Momentum"]
_EARNINGS_COLS = ["Days_To_Earnings", "Days_Since_Earnings", "Pre_Earnings_Window", "Post_Earnings_Window"]
_AUX_COLS      = _VIX_COLS + _SECTOR_COLS + _EARNINGS_COLS

# Per-(ticker, interval) model cache so we only load from disk once
_model_cache: dict = {}


def _model_suffix(interval: str) -> str:
    return "" if interval == "1d" else f"_{interval}"


def _infer_model(model, X: np.ndarray, current_price: float):
    """Return (price_target, return_pct, prob_up) compatible with any model type.

    Professional models (classifiers, have ``classes_``) produce a synthetic
    price target from their directional probability so downstream display code
    keeps working without changes.  Legacy regressors return raw predictions.
    """
    if hasattr(model, "classes_"):                        # classifier
        prob_up = float(model.predict_proba(X)[0][1])
        ret_pct = (prob_up - 0.5) * 4                    # maps [0,1] → [-2%, +2%]
        return current_price * (1 + ret_pct / 100), ret_pct, prob_up
    pred = float(model.predict(X)[0])                    # regressor
    if pred > 10:                                         # LR → next close price
        ret_pct = (pred - current_price) / current_price * 100
        return pred, ret_pct, pred > current_price
    return current_price * (1 + pred / 100), pred, pred > 0  # RF → next return %


def _load_models(ticker: str, interval: str = "1d"):
    """Return (lr, rf, scaler, feature_cols, xgb), cached after first load. xgb may be None."""
    key = (ticker.upper(), interval)
    if key in _model_cache:
        return _model_cache[key]

    suffix = _model_suffix(interval)
    t = ticker.upper()
    lr    = joblib.load(os.path.join(MODELS_DIR, f"lr_model_{t}{suffix}.pkl"))
    rf    = joblib.load(os.path.join(MODELS_DIR, f"rf_model_{t}{suffix}.pkl"))
    sc    = joblib.load(os.path.join(MODELS_DIR, f"scaler_sklearn_{t}{suffix}.pkl"))
    feat  = joblib.load(os.path.join(MODELS_DIR, f"feature_cols_sklearn_{t}{suffix}.pkl"))
    xgb_path = os.path.join(MODELS_DIR, f"xgb_model_{t}{suffix}.pkl")
    xgb   = joblib.load(xgb_path) if os.path.exists(xgb_path) else None
    _model_cache[key] = (lr, rf, sc, feat, xgb)
    return lr, rf, sc, feat, xgb


_FETCH_PERIOD = {
    "1d":  "18mo",
    "1h":  "730d",
    "4h":  "730d",   # fetch as 1h then resample
    "30m": "60d",
    "15m": "60d",
    "5m":  "60d",
    "1m":  "7d",
}

_HTF_YF_PARAMS = {
    "5m":  ("5m",  "60d"),
    "15m": ("15m", "60d"),
    "1h":  ("1h",  "730d"),
    "4h":  ("1h",  "730d"),  # resample to 4h after fetch
    "1d":  ("1d",  "18mo"),
}

_MTF_SOURCES = {
    "1m":  ["5m", "15m", "1h"],
    "5m":  ["15m", "1h", "4h"],
    "15m": ["1h", "4h", "1d"],
    "30m": ["1h", "4h", "1d"],
    "1h":  ["4h", "1d"],
    "4h":  ["1d"],
    "1d":  [],
}

_MTF_COLS = {
    "Structure_Bullish": "Struct",
    "PD_Position":       "PD",
    "RSI_14":            "RSI",
    "Above_200SMA":      "A200",
    "MACD_Diff":         "MACD",
    "Bull_FVG_Count":    "BullFVG",
    "Bear_FVG_Count":    "BearFVG",
    "Displacement":      "Disp",
    "BB_Pos":            "BBPos",
    "ADX":               "ADX",
}


def _resample_4h(df: pd.DataFrame) -> pd.DataFrame:
    df = df.resample("4h", label="left", closed="left").agg(
        {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
    ).dropna(subset=["Open", "Close"])
    return df[df["Volume"] > 0]


def _fetch_df(ticker: str, interval: str = "1d") -> pd.DataFrame:
    yf_ticker = YF_SYMBOL_MAP.get(ticker.upper(), ticker.replace(".", "-"))
    if interval == "4h":
        df = yf.download(yf_ticker, period="730d", interval="1h",
                         auto_adjust=True, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return _resample_4h(df) if not df.empty else df
    period = _FETCH_PERIOD.get(interval, "1y")
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

    # ICT, base features (work on all timeframes)
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

    # ICT 2022, IPDA lookback levels (20 / 40 / 60 bars)
    for n in [20, 40, 60]:
        df[f"IPDA_{n}_High_Dist"] = ((high.rolling(n).max().shift(1) - close) / (atr14 + 1e-8)).clip(-20, 20)
        df[f"IPDA_{n}_Low_Dist"]  = ((close - low.rolling(n).min().shift(1))  / (atr14 + 1e-8)).clip(-20, 20)

    # ICT 2022, Equal Highs / Equal Lows (liquidity pools)
    tol   = close * 0.001
    r10h  = high.rolling(10).max().shift(1)
    r10l  = low.rolling(10).min().shift(1)
    df["Equal_Highs"] = ((high - r10h).abs() < tol).astype(int).rolling(10, min_periods=1).sum()
    df["Equal_Lows"]  = ((low  - r10l).abs() < tol).astype(int).rolling(10, min_periods=1).sum()

    # ICT 2022, OTE zone (Optimal Trade Entry: 0.62-0.79 Fibonacci of 20-bar swing)
    rng20 = (sh20 - sl20).replace(0, np.nan)
    df["In_OTE_Buy"]  = ((close >= sh20 - rng20 * 0.79) & (close <= sh20 - rng20 * 0.62)).astype(int)
    df["In_OTE_Sell"] = ((close >= sl20 + rng20 * 0.62) & (close <= sl20 + rng20 * 0.79)).astype(int)

    # ICT 2022, Consequent Encroachment (CE) of most recent FVG midpoint
    bull_ce_level = ((high.shift(2) + low) / 2).where(bull_fvg.astype(bool)).ffill()
    bear_ce_level = ((low.shift(2)  + high) / 2).where(bear_fvg.astype(bool)).ffill()
    df["CE_Bull_FVG_Dist"] = ((close - bull_ce_level) / (atr14 + 1e-8)).clip(-10, 10).fillna(0)
    df["CE_Bear_FVG_Dist"] = ((bear_ce_level - close) / (atr14 + 1e-8)).clip(-10, 10).fillna(0)

    return df


def _add_intraday_ict(df: pd.DataFrame) -> pd.DataFrame:
    """Kill-zone and session features, only meaningful on sub-daily bars."""
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

    # ICT 2022, Silver Bullet windows (ET)
    df["In_SilverBullet_AM"] = ((hour >= 10) & (hour < 11)).astype(int)
    df["In_SilverBullet_PM"] = ((hour >= 14) & (hour < 15)).astype(int)

    # ICT 2022, Asia session range (8 PM - 2 AM ET)
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

    # ICT 2022, New Week Opening Gap (Monday open vs previous Friday close)
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


def _fetch_aux(ticker: str, interval: str = "1d") -> dict:
    period = _FETCH_PERIOD.get(interval, "18mo")
    # Use 18 months for daily so VIX 252-day rolling has enough history
    if interval == "1d":
        period = "18mo"

    def _dl(sym):
        try:
            d = yf.download(sym, period=period, interval=interval,
                            auto_adjust=True, progress=False)
            if isinstance(d.columns, pd.MultiIndex):
                d.columns = d.columns.get_level_values(0)
            return d if not d.empty else None
        except Exception:
            return None

    vix    = _dl("^VIX")
    spy    = _dl("SPY") if ticker != "SPY" else None
    sec_id = _TICKER_SECTOR_MAP.get(ticker.upper())
    sector = _dl(sec_id) if sec_id and sec_id not in (ticker, "SPY") else None

    earnings = pd.DatetimeIndex([])
    if ticker.upper() in _EQUITY_TICKERS:
        try:
            raw = yf.Ticker(ticker).earnings_dates
            if raw is not None and not raw.empty:
                idx = raw.index.tz_localize(None) if raw.index.tz else raw.index
                earnings = idx.normalize()
        except Exception:
            pass

    return {"vix": vix, "spy": spy, "sector": sector, "earnings": earnings}


def _apply_vix(df: pd.DataFrame, vix_df) -> pd.DataFrame:
    if vix_df is None or vix_df.empty:
        return df.assign(**{c: 0.0 for c in _VIX_COLS})
    idx = df.index.normalize() if df.index.tz is None else df.index.tz_convert(None).normalize()
    vc  = vix_df["Close"].copy()
    vc.index = vc.index.normalize() if vc.index.tz is None else vc.index.tz_localize(None).normalize()
    vc = vc[~vc.index.duplicated(keep="last")]
    unique_idx = pd.DatetimeIndex(sorted(set(idx)))
    vc_filled  = vc.reindex(unique_idx, method="ffill")
    vix_map    = vc_filled.to_dict()
    vix = pd.Series([vix_map.get(d, 20.0) for d in idx], index=df.index).fillna(20.0)
    df["VIX_Level"]          = vix
    df["VIX_Change"]         = vix.pct_change().fillna(0) * 100
    df["VIX_Percentile_252"] = vix.rolling(252, min_periods=60).rank(pct=True).fillna(0.5)
    df["VIX_Regime"]         = pd.cut(df["VIX_Level"], bins=[0, 15, 25, 200],
                                       labels=[0, 1, 2]).astype(float).fillna(1.0)
    vma = vix.rolling(20, min_periods=5).mean()
    df["VIX_MA_Ratio"]       = (vix / vma.replace(0, np.nan)).fillna(1.0).clip(0.5, 2.0)
    return df


def _apply_sector(df: pd.DataFrame, sector_df, spy_df) -> pd.DataFrame:
    def _align(src):
        if src is None or src.empty:
            return None
        s = src["Close"].copy()
        s.index = s.index.normalize() if s.index.tz is None else s.index.tz_localize(None).normalize()
        s = s[~s.index.duplicated(keep="last")]
        ix = df.index.normalize() if df.index.tz is None else df.index.tz_convert(None).normalize()
        unique_ix = pd.DatetimeIndex(sorted(set(ix)))
        s_filled  = s.reindex(unique_ix, method="ffill")
        s_map     = s_filled.to_dict()
        return pd.Series([s_map.get(d, np.nan) for d in ix], index=df.index)

    sec = _align(sector_df)
    spy = _align(spy_df)
    ref = sec if sec is not None else spy
    if ref is None:
        return df.assign(**{c: 0.0 for c in _SECTOR_COLS})

    tick = df["Close"]
    df["Sector_RS_20"]     = (tick.pct_change(20) - ref.pct_change(20)).fillna(0).clip(-0.5, 0.5)
    df["Sector_RS_60"]     = (tick.pct_change(60) - ref.pct_change(60)).fillna(0).clip(-0.5, 0.5)
    if sec is not None and spy is not None:
        df["Sector_vs_SPY_20"] = (sec.pct_change(20) - spy.pct_change(20)).fillna(0).clip(-0.3, 0.3)
    else:
        df["Sector_vs_SPY_20"] = 0.0
    df["Sector_Momentum"]  = ta.momentum.rsi(ref.ffill(), window=14).fillna(50)
    return df


def _apply_earnings(df: pd.DataFrame, earnings: pd.DatetimeIndex) -> pd.DataFrame:
    if earnings is None or len(earnings) == 0:
        return df.assign(**{c: 0.0 for c in _EARNINGS_COLS})
    dates_arr = np.array(sorted(set(pd.DatetimeIndex(earnings).normalize())), dtype="datetime64[D]")
    ix_vals   = pd.DatetimeIndex(
        df.index.normalize() if df.index.tz is None else df.index.tz_convert(None).normalize()
    ).values.astype("datetime64[D]")
    dt, ds = [], []
    for d_np in ix_vals:
        future = dates_arr[dates_arr > d_np]
        past   = dates_arr[dates_arr <= d_np]
        dt.append(int((future[0] - d_np).astype(int)) if len(future) else 90)
        ds.append(int((d_np - past[-1]).astype(int)) if len(past) else 90)
    dt_s = pd.Series(dt, index=df.index, dtype=float).clip(0, 90)
    ds_s = pd.Series(ds, index=df.index, dtype=float).clip(0, 90)
    df["Days_To_Earnings"]     = dt_s
    df["Days_Since_Earnings"]  = ds_s
    df["Pre_Earnings_Window"]  = (dt_s <= 5).astype(float)
    df["Post_Earnings_Window"] = (ds_s <= 2).astype(float)
    return df


def build_features(df: pd.DataFrame, interval: str = "1d",
                   ticker: str = "", aux: dict = None) -> pd.DataFrame:
    df = _add_base_ta(df)
    if interval != "1d":
        df = _add_intraday_ict(df)
    if aux:
        df = _apply_vix(df, aux.get("vix"))
        df = _apply_sector(df, aux.get("sector"), aux.get("spy"))
        df = _apply_earnings(df, aux.get("earnings", pd.DatetimeIndex([])))
    else:
        for c in _AUX_COLS:
            df[c] = 0.0
    # Quant alpha features (Alpha_*). Causal by contract; existing models
    # ignore them (they select by saved feature_cols) and the next retrain
    # picks them up automatically.
    try:
        from alphas import add_alpha_features
        df = add_alpha_features(df)
    except Exception:
        pass
    df.dropna(inplace=True)
    return df


# ── Professional (ICT 2022) feature engineering ────────────────────────────────

def _is_professional_model(feature_cols: list) -> bool:
    """True if model was trained by train_professional.py (has new ICT feature names)."""
    return bool(set(feature_cols) & {"Returns", "CHoCH_Bear", "BB_Pos", "ADX", "MACD_Diff"})


def _compute_pro_features(df: pd.DataFrame, is_intraday: bool = True) -> pd.DataFrame:
    """Mirror of compute_ict_features() from train_professional.py for live inference."""
    df = df.copy()
    c, h, l, o, v = df["Close"], df["High"], df["Low"], df["Open"], df["Volume"]

    df["Returns"]  = c.pct_change()
    df["Log_Ret"]  = np.log((c / c.shift(1)).replace(0, np.nan))
    df["HL_Range"] = (h - l) / (c + 1e-8)
    df["CO_Move"]  = (c - o) / (o + 1e-8)

    atr14 = ta.volatility.AverageTrueRange(h, l, c, window=14).average_true_range().fillna(c * 0.01)
    df["ATR_14"] = atr14
    df["ATR_r"]  = atr14 / (c + 1e-8)

    for p in [5, 10, 20, 50]:
        sma = ta.trend.sma_indicator(c, window=p)
        df[f"SMA_{p}"]   = sma
        df[f"SMA_{p}_r"] = c / (sma + 1e-8) - 1
    sma200 = c.rolling(200, min_periods=1).mean()
    df["SMA_200_r"]    = c / (sma200 + 1e-8) - 1
    df["Above_200SMA"] = (c > sma200).astype(int)
    df["EMA_9"]  = ta.trend.ema_indicator(c, window=9)
    df["EMA_21"] = ta.trend.ema_indicator(c, window=21)
    df["EMA_50"] = ta.trend.ema_indicator(c, window=50)

    df["RSI_7"]      = ta.momentum.rsi(c, window=7)
    df["RSI_14"]     = ta.momentum.rsi(c, window=14)
    df["RSI_21"]     = ta.momentum.rsi(c, window=21)
    df["Stoch_K"]    = ta.momentum.stoch(h, l, c, window=14, smooth_window=3)
    df["Stoch_D"]    = ta.momentum.stoch_signal(h, l, c, window=14, smooth_window=3)
    df["ROC_5"]      = ta.momentum.roc(c, window=5)
    df["ROC_10"]     = ta.momentum.roc(c, window=10)
    df["Williams_R"] = ta.momentum.williams_r(h, l, c, lbp=14)

    macd_ind        = ta.trend.MACD(c, window_fast=12, window_slow=26, window_sign=9)
    df["MACD"]      = macd_ind.macd()
    df["MACD_Sig"]  = macd_ind.macd_signal()
    df["MACD_Diff"] = macd_ind.macd_diff()
    df["ADX"]       = ta.trend.adx(h, l, c, window=14)
    df["ADX_Pos"]   = ta.trend.adx_pos(h, l, c, window=14)
    df["ADX_Neg"]   = ta.trend.adx_neg(h, l, c, window=14)
    df["CCI"]       = ta.trend.cci(h, l, c, window=20)

    bb = ta.volatility.BollingerBands(c, window=20, window_dev=2)
    df["BB_Upper"] = bb.bollinger_hband()
    df["BB_Lower"] = bb.bollinger_lband()
    df["BB_Mid"]   = bb.bollinger_mavg()
    df["BB_Width"] = (df["BB_Upper"] - df["BB_Lower"]) / (df["BB_Mid"] + 1e-8)
    df["BB_Pos"]   = (c - df["BB_Lower"]) / (df["BB_Upper"] - df["BB_Lower"] + 1e-8)
    try:
        kc = ta.volatility.KeltnerChannel(h, l, c, window=20)
        df["KC_Squeeze"] = ((df["BB_Upper"] < kc.keltner_channel_hband()) &
                            (df["BB_Lower"] > kc.keltner_channel_lband())).astype(int)
    except Exception:
        df["KC_Squeeze"] = 0

    vma20          = v.rolling(20, min_periods=1).mean()
    df["Volume_r"] = v / (vma20 + 1)
    df["OBV"]      = ta.volume.on_balance_volume(c, v)
    df["OBV_r"]    = df["OBV"] / (df["OBV"].rolling(20, min_periods=1).mean() + 1e-8) - 1
    try:
        df["CMF"] = ta.volume.chaikin_money_flow(h, l, c, v, window=20)
    except Exception:
        df["CMF"] = 0.0
    df["VWAP_r"] = c / (ta.volume.volume_weighted_average_price(h, l, c, v, window=14) + 1e-8) - 1

    sh20 = h.rolling(20).max();  sl20 = l.rolling(20).min()
    sh60 = h.rolling(60).max();  sl60 = l.rolling(60).min()
    df["Dist_to_SH20"] = ((sh20 - c) / (atr14 + 1e-8)).clip(-10, 10)
    df["Dist_to_SL20"] = ((c - sl20) / (atr14 + 1e-8)).clip(-10, 10)
    df["Dist_to_SH60"] = ((sh60 - c) / (atr14 + 1e-8)).clip(-10, 10)
    df["Dist_to_SL60"] = ((c - sl60) / (atr14 + 1e-8)).clip(-10, 10)
    df["HH"] = ((h > h.shift(1)) & (h.shift(1) > h.shift(2))).astype(int)
    df["LL"] = ((l < l.shift(1)) & (l.shift(1) < l.shift(2))).astype(int)
    df["HL"] = ((l > l.shift(2)) & (h < sh20.shift(1))).astype(int)
    df["LH"] = ((h < h.shift(2)) & (l > sl20.shift(1))).astype(int)
    df["Structure_Bullish"] = (sh20 > sh60.shift(20)).astype(int)

    hl_mask   = (l > l.shift(2)) & (h < sh20.shift(1))
    lh_mask   = (h < h.shift(2)) & (l > sl20.shift(1))
    recent_hl = l.where(hl_mask).rolling(10, min_periods=1).max().ffill()
    recent_lh = h.where(lh_mask).rolling(10, min_periods=1).min().ffill()
    df["CHoCH_Bear"] = ((c < recent_hl) &  df["Structure_Bullish"].astype(bool)).astype(int)
    df["CHoCH_Bull"] = ((c > recent_lh) & ~df["Structure_Bullish"].astype(bool)).astype(int)

    rng60 = (sh60 - sl60).replace(0, np.nan)
    df["PD_Position"] = ((c - sl60) / rng60).fillna(0.5).clip(0, 1)
    df["In_Premium"]  = (df["PD_Position"] >= 0.55).astype(int)
    df["In_Discount"] = (df["PD_Position"] <= 0.45).astype(int)

    rng20 = (sh20 - sl20).replace(0, np.nan)
    df["In_OTE_Buy"]  = ((c >= sh20 - rng20 * 0.79) & (c <= sh20 - rng20 * 0.62)).astype(int)
    df["In_OTE_Sell"] = ((c >= sl20 + rng20 * 0.62) & (c <= sl20 + rng20 * 0.79)).astype(int)

    bull_fvg = (l > h.shift(2)).astype(int)
    bear_fvg = (h < l.shift(2)).astype(int)
    df["Bull_FVG_Count"] = bull_fvg.rolling(10, min_periods=1).sum()
    df["Bear_FVG_Count"] = bear_fvg.rolling(10, min_periods=1).sum()
    df["FVG_Net"]        = df["Bull_FVG_Count"] - df["Bear_FVG_Count"]
    bull_ce = ((h.shift(2) + l) / 2).where(bull_fvg.astype(bool)).ffill()
    bear_ce = ((l.shift(2) + h) / 2).where(bear_fvg.astype(bool)).ffill()
    df["CE_Bull_Dist"] = ((c - bull_ce) / (atr14 + 1e-8)).clip(-10, 10).fillna(0)
    df["CE_Bear_Dist"] = ((bear_ce - c) / (atr14 + 1e-8)).clip(-10, 10).fillna(0)

    body = (c - o).abs();  rng = (h - l).replace(0, np.nan)
    df["Body_Ratio"]   = (body / rng).fillna(0).clip(0, 1)
    df["Displacement"] = ((rng.fillna(0) > atr14 * 1.5) & (df["Body_Ratio"] > 0.6)).astype(int)
    bear_c = (c < o);  bull_c = (c > o)
    bull_ob = (bear_c.shift(1).fillna(False)) & (df["Displacement"] == 1) & bull_c
    bear_ob = (bull_c.shift(1).fillna(False)) & (df["Displacement"] == 1) & bear_c
    df["Bull_OB_Count"] = bull_ob.astype(int).rolling(10, min_periods=1).sum()
    df["Bear_OB_Count"] = bear_ob.astype(int).rolling(10, min_periods=1).sum()
    last_boh = h.where(bull_ob).ffill();  last_bol = l.where(bull_ob).ffill()
    last_beh = h.where(bear_ob).ffill();  last_bel = l.where(bear_ob).ffill()
    df["Bull_OB_H_Dist"] = ((last_boh - c) / (atr14 + 1e-8)).clip(-10, 10).fillna(0)
    df["Bull_OB_L_Dist"] = ((c - last_bol) / (atr14 + 1e-8)).clip(-10, 10).fillna(0)
    df["Bear_OB_H_Dist"] = ((last_beh - c) / (atr14 + 1e-8)).clip(-10, 10).fillna(0)
    df["Bear_OB_L_Dist"] = ((c - last_bel) / (atr14 + 1e-8)).clip(-10, 10).fillna(0)

    tol  = c * 0.001
    r10h = h.rolling(10).max().shift(1);  r10l = l.rolling(10).min().shift(1)
    df["Equal_Highs"] = ((h - r10h).abs() < tol).astype(int).rolling(5, min_periods=1).sum()
    df["Equal_Lows"]  = ((l - r10l).abs() < tol).astype(int).rolling(5, min_periods=1).sum()
    df["Swept_High"]  = ((h > sh20.shift(1)) & (c < sh20.shift(1))).astype(int)
    df["Swept_Low"]   = ((l < sl20.shift(1)) & (c > sl20.shift(1))).astype(int)
    pwh = h.rolling(5).max().shift(1);  pwl = l.rolling(5).min().shift(1)
    df["Dist_PWH"] = ((pwh - c) / (atr14 + 1e-8)).clip(-10, 10)
    df["Dist_PWL"] = ((c - pwl)  / (atr14 + 1e-8)).clip(-10, 10)

    for n in [20, 40, 60]:
        df[f"IPDA_{n}_H"] = ((h.rolling(n).max().shift(1) - c) / (atr14 + 1e-8)).clip(-20, 20)
        df[f"IPDA_{n}_L"] = ((c - l.rolling(n).min().shift(1)) / (atr14 + 1e-8)).clip(-20, 20)

    df["P3_Accum"]   = (df["Returns"].abs() < df["ATR_r"] * 0.5).astype(int)
    df["P3_Manip"]   = ((h > h.shift(1)) & (c < o)).astype(int)
    df["P3_Distrib"] = df["Displacement"].rolling(3, min_periods=1).sum()

    df["DayOfWeek"] = np.array(df.index.dayofweek, dtype=np.int32)
    _m = np.array(df.index.month, dtype=np.int32)
    _q = np.array(df.index.quarter, dtype=np.int32)
    df["Month_Sin"]   = np.sin(2 * np.pi * _m / 12)
    df["Month_Cos"]   = np.cos(2 * np.pi * _m / 12)
    df["Quarter_Sin"] = np.sin(2 * np.pi * _q / 4)
    df["Quarter_Cos"] = np.cos(2 * np.pi * _q / 4)

    for lag in range(1, 6):
        df[f"Ret_lag_{lag}"] = df["Returns"].shift(lag)
    for lag in range(1, 4):
        df[f"Vol_lag_{lag}"] = df["Volume_r"].shift(lag)

    if is_intraday:
        idx  = df.index
        et   = idx.tz_convert("America/New_York") if idx.tz else idx.tz_localize("UTC").tz_convert("America/New_York")
        hour   = np.array(et.hour,      dtype=np.int32)
        minute = np.array(et.minute,    dtype=np.int32)
        dow    = np.array(et.dayofweek, dtype=np.int32)

        df["KZ_London"]       = ((hour >= 2)  & (hour < 5)).astype(int)
        df["KZ_NY_Open"]      = ((hour >= 9)  & (hour < 11)).astype(int)
        df["KZ_London_Close"] = ((hour >= 10) & (hour < 12)).astype(int)
        df["KZ_NY_PM"]        = ((hour >= 13) & (hour < 16)).astype(int)
        df["KZ_SB_AM"]        = ((hour == 10) | ((hour == 9) & (minute >= 50))).astype(int)
        df["KZ_SB_PM"]        = ((hour >= 14) & (hour < 15)).astype(int)

        mins_in           = np.clip((hour - 9) * 60 + minute - 30, 0, 390)
        df["Session_Pct"] = mins_in / 390
        df["Hour_Sin"]    = np.sin(2 * np.pi * hour / 24)
        df["Hour_Cos"]    = np.cos(2 * np.pi * hour / 24)
        df["Day_Sin"]     = np.sin(2 * np.pi * dow / 5)
        df["Day_Cos"]     = np.cos(2 * np.pi * dow / 5)

        date_str      = pd.Series(et.date, index=df.index)
        midnight_open = df.groupby(date_str)["Open"].transform("first")
        df["vs_MidOpen"] = (c - midnight_open) / (midnight_open + 1e-8) * 100
        sess_hi = df.groupby(date_str)["High"].transform("cummax")
        sess_lo = df.groupby(date_str)["Low"].transform("cummin")
        df["Sess_H_Dist"] = ((sess_hi - c) / (atr14 + 1e-8)).clip(-10, 10)
        df["Sess_L_Dist"] = ((c - sess_lo) / (atr14 + 1e-8)).clip(-10, 10)

        is_asia_s = pd.Series((hour >= 20) | (hour < 2), index=df.index)
        asia_h    = h.where(is_asia_s).rolling(14, min_periods=1).max().ffill()
        asia_l    = l.where(is_asia_s).rolling(14, min_periods=1).min().ffill()
        df["Asia_H_Dist"] = ((asia_h - c) / (atr14 + 1e-8)).clip(-10, 10).fillna(0)
        df["Asia_L_Dist"] = ((c - asia_l) / (atr14 + 1e-8)).clip(-10, 10).fillna(0)
        df["Asia_Range"]  = ((asia_h - asia_l) / (atr14 + 1e-8)).clip(0, 20).fillna(0)
        df["Above_AsiaH"] = (c > asia_h).astype(int)
        df["Below_AsiaL"] = (c < asia_l).astype(int)

        is_mon_s   = pd.Series(dow == 0, index=df.index)
        prev_close = c.shift(1)
        nwog_open  = df["Open"].where(is_mon_s).ffill()
        nwog_prev  = prev_close.where(is_mon_s).ffill()
        lo = nwog_prev.clip(lower=0)
        df["In_NWOG"]   = (nwog_open.notna() & nwog_prev.notna() &
                           c.between(lo, nwog_open, inclusive="both")).astype(int)
        week_gap        = (df["Open"] - prev_close).where(is_mon_s).ffill().fillna(0)
        df["NWOG_Norm"] = (week_gap / (atr14 + 1e-8)).clip(-5, 5)

    # Compatibility aliases so display/chart code in run_prediction() works unchanged
    df["SMA_7"]        = ta.trend.sma_indicator(c, window=7)
    df["SMA_21"]       = ta.trend.sma_indicator(c, window=21)
    df["MACD_Hist"]    = df["MACD_Diff"]
    df["Daily_Return"] = df["Returns"] * 100
    return df


def _fetch_htf_for_mtf(ticker: str, htf: str) -> "pd.DataFrame | None":
    """Fetch higher-timeframe data for MTF context injection during inference."""
    yf_ticker = YF_SYMBOL_MAP.get(ticker.upper(), ticker.replace(".", "-"))
    iv, period = _HTF_YF_PARAMS.get(htf, ("1d", "18mo"))
    try:
        df = yf.download(yf_ticker, period=period, interval=iv,
                         auto_adjust=True, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        if df.empty:
            return None
        if htf == "4h":
            df = _resample_4h(df)
        return df if not df.empty else None
    except Exception:
        return None


def _build_pro_features(df: pd.DataFrame, ticker: str, interval: str) -> pd.DataFrame:
    """Build professional feature set (153 features + MTF context) for inference."""
    is_intraday = (interval != "1d")
    df = _compute_pro_features(df, is_intraday)

    for htf in _MTF_SOURCES.get(interval, []):
        htf_raw = _fetch_htf_for_mtf(ticker, htf)
        if htf_raw is None:
            continue
        try:
            htf_feat = _compute_pro_features(htf_raw, is_intraday=(htf != "1d"))
        except Exception:
            continue
        for src_col, suffix in _MTF_COLS.items():
            col_name = f"HTF_{htf}_{suffix}"
            if src_col not in htf_feat.columns:
                df[col_name] = 0.0
                continue
            s = htf_feat[src_col].copy()
            # Normalise timezones before reindex-merge
            try:
                if s.index.tz is not None:
                    s.index = s.index.tz_convert("UTC")
                if df.index.tz is not None:
                    ref_idx = df.index.tz_convert("UTC")
                else:
                    ref_idx = df.index
                    s.index = s.index.tz_localize(None) if s.index.tz else s.index
            except Exception:
                ref_idx = df.index
            union_ix = s.index.union(ref_idx)
            combined = s.reindex(union_ix).sort_index().ffill()
            df[col_name] = combined.reindex(ref_idx).values

    # Zero-fill any HTF columns that couldn't be fetched
    for htf in _MTF_SOURCES.get(interval, []):
        for src_col, suffix in _MTF_COLS.items():
            col_name = f"HTF_{htf}_{suffix}"
            if col_name not in df.columns:
                df[col_name] = 0.0

    df.dropna(inplace=True)
    return df


# ── Public API ─────────────────────────────────────────────────────────────────

def run_prediction(ticker: str, interval: str = "1d") -> dict:
    """Full prediction result dict for Flask routes and the result page."""
    ticker   = ticker.upper()
    min_bars = {"1d": 70, "1h": 100, "4h": 30, "30m": 50,
                "15m": 80, "5m": 80, "1m": 50}.get(interval, 70)

    df = _fetch_df(ticker, interval)
    if df.empty or len(df) < min_bars:
        raise ValueError(
            f"Not enough data for '{ticker}' on {interval} interval. "
            "Check the ticker symbol."
        )

    # Load models first so we know which feature set to build
    lr_model, rf_model, scaler, feature_cols, xgb_model = _load_models(ticker, interval)

    if _is_professional_model(feature_cols):
        df = _build_pro_features(df, ticker, interval)
    else:
        aux = _fetch_aux(ticker, interval)
        df  = build_features(df, interval, ticker, aux)

    if df.empty:
        raise ValueError("Feature engineering failed, insufficient data history.")

    current_price = float(df["Close"].iloc[-1])
    X             = scaler.transform(df[feature_cols].iloc[-1:].values)
    lr_pred, _, lr_up    = _infer_model(lr_model, X, current_price)
    rf_pred, rf_ret, rf_up = _infer_model(rf_model, X, current_price)

    price_change = lr_pred - current_price

    if xgb_model is not None:
        xgb_prob   = float(xgb_model.predict_proba(X)[0][1])
        xgb_up     = xgb_prob > 0.5
        votes_up   = sum([bool(lr_up), bool(rf_up), xgb_up])
        direction  = "Up" if xgb_prob > 0.5 else "Down"
        confidence = round(min(95, max(51, max(xgb_prob, 1 - xgb_prob) * 100)), 1)
        signal_strength = ("Strong" if votes_up == 3 and confidence >= 62
                           else ("Strong" if votes_up == 0 and confidence >= 62
                           else ("Moderate" if votes_up >= 2 or votes_up == 0
                           else "Weak")))
    else:
        xgb_prob   = 0.5
        xgb_up     = lr_up
        votes_up   = sum([bool(lr_up), bool(rf_up)])
        direction  = "Up" if lr_up else "Down"
        daily_ret  = df.get("Daily_Return", df.get("Returns", pd.Series(dtype=float)))
        recent_vol = float(daily_ret.tail(20).std()) if not daily_ret.empty else 1.0
        change_pct = abs(price_change / current_price * 100)
        confidence = min(95, max(51, 50 + (change_pct / max(recent_vol, 0.1)) * 10))
        signal_strength = "Moderate" if votes_up == 2 or votes_up == 0 else "Weak"

    change_pct = abs(price_change / current_price * 100)

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

    # ICT values from last bar
    last        = df.iloc[-1]
    pd_pos      = round(float(last["PD_Position"]), 3)
    above_200   = int(last["Above_200SMA"])
    struct_bull = int(last["Structure_Bullish"])
    bull_fvg    = int(last["Bull_FVG_Count"])
    bear_fvg    = int(last["Bear_FVG_Count"])
    bull_ob     = int(last["Bull_OB_Count"])
    bear_ob     = int(last["Bear_OB_Count"])
    swept_high  = int(last["Swept_High"])
    swept_low   = int(last["Swept_Low"])
    in_ote_buy  = int(last["In_OTE_Buy"])
    in_ote_sell = int(last["In_OTE_Sell"])
    eq_highs    = int(last["Equal_Highs"])
    eq_lows     = int(last["Equal_Lows"])
    displaced   = int(last["Displacement"])

    # Derive readable ICT bias
    if above_200 and struct_bull:
        ict_bias = "Bullish"
    elif not above_200 and not struct_bull:
        ict_bias = "Bearish"
    else:
        ict_bias = "Neutral"

    # PD zone label
    if pd_pos <= 0.45:
        pd_zone = "Discount"
    elif pd_pos >= 0.55:
        pd_zone = "Premium"
    else:
        pd_zone = "Equilibrium"

    # ── Lightweight Charts payload ─────────────────────────────────────────────
    def _lw_time(ts):
        if interval == "1d":
            return ts.strftime("%Y-%m-%d")
        if ts.tzinfo is not None:
            return int(ts.timestamp())
        return int(pd.Timestamp(ts, tz="UTC").timestamp())

    chart_plot = df.tail(120)

    candles = [
        {
            "time":  _lw_time(idx),
            "open":  round(float(r["Open"]),  4),
            "high":  round(float(r["High"]),  4),
            "low":   round(float(r["Low"]),   4),
            "close": round(float(r["Close"]), 4),
        }
        for idx, r in chart_plot.iterrows()
    ]

    sma200_raw  = df["Close"].rolling(200, min_periods=1).mean().tail(120)
    sma200_line = [
        {"time": _lw_time(idx), "value": round(float(v), 4)}
        for idx, v in sma200_raw.items()
        if pd.notna(v)
    ]

    # OTE zones (0.62-0.79 Fibonacci of last 20-bar swing)
    atr_val = float(last["ATR_14"])
    sh20    = float(df["High"].rolling(20).max().iloc[-1])
    sl20_v  = float(df["Low"].rolling(20).min().iloc[-1])
    rng20v  = max(sh20 - sl20_v, atr_val)
    ote_buy_zone  = {"low": round(sh20  - rng20v * 0.79, 4), "high": round(sh20  - rng20v * 0.62, 4)}
    ote_sell_zone = {"low": round(sl20_v + rng20v * 0.62, 4), "high": round(sl20_v + rng20v * 0.79, 4)}

    # FVG zones (last 5 in the 120-bar window)
    h_arr = chart_plot["High"].values
    l_arr = chart_plot["Low"].values
    fvg_list = []
    for i in range(2, len(h_arr)):
        if l_arr[i] > h_arr[i - 2]:            # Bullish FVG: gap above candle i-2
            fvg_list.append({"low": round(float(h_arr[i - 2]), 4), "high": round(float(l_arr[i]), 4), "type": "bull"})
        elif h_arr[i] < l_arr[i - 2]:           # Bearish FVG: gap below candle i-2
            fvg_list.append({"low": round(float(h_arr[i]), 4), "high": round(float(l_arr[i - 2]), 4), "type": "bear"})
    fvg_list = fvg_list[-5:]

    # OB zones (last 5 in the 120-bar window)
    o_arr = chart_plot["Open"].values
    c_arr = chart_plot["Close"].values
    d_arr = chart_plot["Displacement"].values
    ob_list = []
    for i in range(1, len(h_arr)):
        if d_arr[i] and c_arr[i-1] < o_arr[i-1] and c_arr[i] > o_arr[i]:    # Bull OB
            ob_list.append({"low": round(float(l_arr[i-1]), 4), "high": round(float(h_arr[i-1]), 4), "type": "bull"})
        elif d_arr[i] and c_arr[i-1] > o_arr[i-1] and c_arr[i] < o_arr[i]:  # Bear OB
            ob_list.append({"low": round(float(l_arr[i-1]), 4), "high": round(float(h_arr[i-1]), 4), "type": "bear"})
    ob_list = ob_list[-5:]

    # ATR-based SL / TP
    sl_price = round(current_price - 1.5 * atr_val, 4) if direction == "Up" else round(current_price + 1.5 * atr_val, 4)
    tp_price = round(current_price + 3.0 * atr_val, 4) if direction == "Up" else round(current_price - 3.0 * atr_val, 4)

    lw_chart_data = {
        "candles":    candles,
        "sma200":     sma200_line,
        "ote_buy":    ote_buy_zone,
        "ote_sell":   ote_sell_zone,
        "fvg":        fvg_list,
        "ob":         ob_list,
        "pred":       round(lr_pred, 4),
        "sl":         sl_price,
        "tp":         tp_price,
        "direction":  direction,
        "in_ote_buy": in_ote_buy,
        "in_ote_sell": in_ote_sell,
    }

    # Human-readable timestamp for the last bar
    last_idx = df.index[-1]
    _horizon_label = {
        "1d":  "Next Day",
        "1h":  "Next Hour",
        "4h":  "Next 4 Hours",
        "30m": "Next 30 Minutes",
        "15m": "Next 15 Minutes",
        "5m":  "Next 5 Minutes",
        "1m":  "Next 5 Minutes",
    }
    if interval == "1d":
        as_of   = last_idx.strftime("%B %d, %Y")
        horizon = "Next Day"
    else:
        try:
            et = last_idx.tz_convert("America/New_York") if last_idx.tzinfo else last_idx
            as_of = et.strftime("%b %d, %Y %I:%M %p ET")
        except Exception:
            as_of = str(last_idx)
        horizon = _horizon_label.get(interval, "Next Bar")

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
        # ICT
        "ict_bias"     : ict_bias,
        "pd_position"  : pd_pos,
        "pd_zone"      : pd_zone,
        "bull_fvg"     : bull_fvg,
        "bear_fvg"     : bear_fvg,
        "bull_ob"      : bull_ob,
        "bear_ob"      : bear_ob,
        "swept_high"   : swept_high,
        "swept_low"    : swept_low,
        "in_ote_buy"   : in_ote_buy,
        "in_ote_sell"  : in_ote_sell,
        "eq_highs"     : eq_highs,
        "eq_lows"      : eq_lows,
        "displaced"    : displaced,
        # Lightweight Charts
        "lw_chart"     : json.dumps(lw_chart_data),
        # Model consensus fields (used by result.html confidence panel)
        "xgb_prob"      : round(xgb_prob, 4),
        "signal_strength": signal_strength,
        "lr_up"          : bool(lr_up),
        "rf_up"          : bool(rf_up),
        "xgb_up"         : bool(xgb_up),
        "votes_up"       : votes_up,
        "has_xgb"        : (xgb_model is not None),
    }


def ml_signal(ticker: str, interval: str = "1d") -> dict:
    """
    Trading signal for the MT5 auto-trade loop.

    BUY , LR and RF both predict up
    SELL, both predict down
    HOLD, models disagree
    """
    try:
        ticker   = ticker.upper()
        min_bars = {"1d": 70, "1h": 100, "4h": 30, "30m": 50,
                    "15m": 80, "5m": 80, "1m": 50}.get(interval, 70)
        df = _fetch_df(ticker, interval)
        if df.empty or len(df) < min_bars:
            return {"action": "HOLD", "error": "Insufficient data", "confidence": 0}

        lr_model, rf_model, scaler, feature_cols, xgb_model = _load_models(ticker, interval)

        if _is_professional_model(feature_cols):
            df = _build_pro_features(df, ticker, interval)
        else:
            aux = _fetch_aux(ticker, interval)
            df  = build_features(df, interval, ticker, aux)

        if df.empty:
            return {"action": "HOLD", "error": "Feature build failed", "confidence": 0}

        current_price = float(df["Close"].iloc[-1])
        X             = scaler.transform(df[feature_cols].iloc[-1:].values)
        lr_pred, _, lr_up    = _infer_model(lr_model, X, current_price)
        rf_pred, rf_ret, rf_up = _infer_model(rf_model, X, current_price)

        if xgb_model is not None:
            xgb_prob = float(xgb_model.predict_proba(X)[0][1])
            xgb_up   = xgb_prob > 0.5
            votes_up = sum([lr_up, rf_up, xgb_up])
            votes_dn = 3 - votes_up
            if votes_up >= 2:   action = "BUY"
            elif votes_dn >= 2: action = "SELL"
            else:               action = "HOLD"
            confidence = round(min(95, max(51, max(xgb_prob, 1 - xgb_prob) * 100)), 1)
        else:
            xgb_prob = 0.5
            if lr_up and rf_up:           action = "BUY"
            elif not lr_up and not rf_up: action = "SELL"
            else:                          action = "HOLD"
            daily_ret  = df.get("Daily_Return", df.get("Returns", pd.Series(dtype=float)))
            recent_vol = float(daily_ret.tail(20).std()) if not daily_ret.empty else 1.0
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
