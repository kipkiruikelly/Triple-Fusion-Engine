"""
train_professional.py
Multi-timeframe ICT-enhanced ensemble training pipeline for BullLogic.

Pulls 1-minute OHLCV from Alpaca -> resamples to 7 timeframes -> engineers
comprehensive TA + ICT features with multi-timeframe (MTF) context -> trains
LR + RF + XGBoost direction classifiers for every ticker × timeframe.

Usage:
    python train_professional.py                          # all tickers, all TFs
    python train_professional.py --tickers QQQ AAPL       # specific tickers
    python train_professional.py --timeframes 1h 4h 1d    # specific TFs
    python train_professional.py --skip-existing          # skip trained combos
"""

import os
import sys
import logging
import argparse
import warnings
import time
from datetime import datetime, timedelta

warnings.filterwarnings("ignore")

# Load .env before reading any credentials
try:
    from dotenv import load_dotenv
    _env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    load_dotenv(_env_path)
except ImportError:
    pass

import numpy as np
import pandas as pd
import joblib
import ta

from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import accuracy_score, roc_auc_score

try:
    from xgboost import XGBClassifier
    XGB_OK = True
except ImportError:
    XGB_OK = False

import json

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

# ── Credentials ───────────────────────────────────────────────────────────────

ALPACA_KEY    = os.environ.get("ALPACA_API_KEY", "")
ALPACA_SECRET = os.environ.get("ALPACA_SECRET_KEY", "")
if not ALPACA_KEY or not ALPACA_SECRET:
    sys.exit("ERROR: Set ALPACA_API_KEY and ALPACA_SECRET_KEY (see .env)")

_client = StockHistoricalDataClient(api_key=ALPACA_KEY, secret_key=ALPACA_SECRET)

# ── Config ────────────────────────────────────────────────────────────────────

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(BASE_DIR, "Saved Models")
os.makedirs(MODELS_DIR, exist_ok=True)

FETCH_START = datetime(2024, 1, 2)
FETCH_END   = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

# For longer TFs, fetch directly from Alpaca with an extended start date.
# Alpaca daily/hourly bars go back further than the 1m free-tier limit.
DIRECT_TF_FETCH = {
    # (alpaca TimeFrame, start_date, chunk_days)
    "1h": (TimeFrame(1, TimeFrameUnit.Hour), datetime(2022, 1, 3), 365),
    "1d": (TimeFrame(1, TimeFrameUnit.Day),  datetime(2019, 1, 2), 730),
}

ALL_TICKERS = ["QQQ", "AAPL", "NVDA", "TSLA", "MSFT", "GOOGL", "META", "AMZN", "NDX", "DIA"]

ALPACA_SYMBOL_MAP = {"NDX": "QQQ"}

# (pandas resample rule, lookahead bars for target, minimum usable rows)
TF_CONFIG = {
    "1m":  ("1min",  5,  1000),
    "5m":  ("5min",  3,   500),
    "15m": ("15min", 2,   300),
    "30m": ("30min", 2,   200),
    "1h":  ("1h",    2,   150),
    "4h":  ("4h",    2,   100),
    "1d":  ("1D",    1,    80),
}

# Higher TFs whose state is injected as context into each lower TF
MTF_SOURCES = {
    "1m":  ["5m", "15m", "1h"],
    "5m":  ["15m", "1h", "4h"],
    "15m": ["1h", "4h", "1d"],
    "30m": ["1h", "4h", "1d"],
    "1h":  ["4h", "1d"],
    "4h":  ["1d"],
    "1d":  [],
}

# HTF columns pulled into lower TF as context (source_col -> short suffix)
MTF_COLS = {
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

# ── Logging ───────────────────────────────────────────────────────────────────

LOG_FILE = os.path.join(BASE_DIR, "train_professional.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_FILE, mode="w"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

# ── Data Acquisition ──────────────────────────────────────────────────────────

def fetch_1min(ticker: str) -> pd.DataFrame:
    """Pull 1-min OHLCV from Alpaca for `ticker` in 30-day chunks."""
    symbol = ALPACA_SYMBOL_MAP.get(ticker, ticker)
    log.info(f"  Fetching {symbol} 1m  {FETCH_START.date()} -> {FETCH_END.date()}")

    chunks, cursor = [], FETCH_START
    while cursor < FETCH_END:
        end = min(cursor + timedelta(days=30), FETCH_END)
        try:
            req  = StockBarsRequest(symbol_or_symbols=symbol,
                                    timeframe=TimeFrame.Minute,
                                    start=cursor, end=end)
            df   = _client.get_stock_bars(req).df
            if not df.empty:
                if isinstance(df.index, pd.MultiIndex):
                    df = df.droplevel(0)
                chunks.append(df)
        except Exception as exc:
            log.warning(f"    {cursor.date()} -> {end.date()}: {exc}")
        cursor = end

    if not chunks:
        raise ValueError(f"No Alpaca data for {symbol}")

    df = pd.concat(chunks).sort_index()
    df = df[~df.index.duplicated(keep="last")]
    df = df.rename(columns={"open": "Open", "high": "High", "low": "Low",
                             "close": "Close", "volume": "Volume"})
    df.index.name = "Date"
    df.index = pd.to_datetime(df.index, utc=True).tz_convert("America/New_York")
    df = df.between_time("09:30", "16:00")[["Open", "High", "Low", "Close", "Volume"]]
    log.info(f"  {len(df):,} 1m bars after market-hours filter")
    return df


def fetch_tf_direct(ticker: str, alpaca_tf, start: datetime, chunk_days: int = 365) -> pd.DataFrame:
    """Fetch OHLCV at a coarser timeframe directly from Alpaca (longer history than 1m)."""
    symbol = ALPACA_SYMBOL_MAP.get(ticker, ticker)
    log.info(f"  Fetching {symbol} direct {alpaca_tf} {start.date()} -> {FETCH_END.date()}")

    chunks, cursor = [], start
    while cursor < FETCH_END:
        end = min(cursor + timedelta(days=chunk_days), FETCH_END)
        try:
            req = StockBarsRequest(symbol_or_symbols=symbol, timeframe=alpaca_tf,
                                   start=cursor, end=end)
            df = _client.get_stock_bars(req).df
            if not df.empty:
                if isinstance(df.index, pd.MultiIndex):
                    df = df.droplevel(0)
                chunks.append(df)
        except Exception as exc:
            log.warning(f"    {cursor.date()} -> {end.date()}: {exc}")
        cursor = end

    if not chunks:
        raise ValueError(f"No direct Alpaca data for {symbol} at {alpaca_tf}")

    df = pd.concat(chunks).sort_index()
    df = df[~df.index.duplicated(keep="last")]
    df = df.rename(columns={"open": "Open", "high": "High", "low": "Low",
                             "close": "Close", "volume": "Volume"})
    df.index.name = "Date"
    df.index = pd.to_datetime(df.index, utc=True).tz_convert("America/New_York")
    df = df[df["Volume"] > 0]
    log.info(f"  Direct {alpaca_tf}: {len(df):,} bars")
    return df[["Open", "High", "Low", "Close", "Volume"]]


def resample_ohlcv(df_1m: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Resample 1m OHLCV to a coarser timeframe."""
    df = df_1m.resample(rule, label="left", closed="left").agg(
        {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
    ).dropna(subset=["Open", "Close"])
    return df[df["Volume"] > 0]


# ── Feature Engineering ───────────────────────────────────────────────────────

def compute_ict_features(df: pd.DataFrame, is_intraday: bool = True) -> pd.DataFrame:
    """Compute full TA + ICT feature set for one OHLCV timeframe."""
    df = df.copy()
    c, h, l, o, v = df["Close"], df["High"], df["Low"], df["Open"], df["Volume"]

    # ── Price action ─────────────────────────────────────────────────────────
    df["Returns"]   = c.pct_change()
    df["Log_Ret"]   = np.log(c / c.shift(1))
    df["HL_Range"]  = (h - l) / (c + 1e-8)
    df["CO_Move"]   = (c - o) / (o + 1e-8)

    # ── ATR (used throughout for normalisation) ───────────────────────────────
    atr14 = ta.volatility.AverageTrueRange(h, l, c, window=14).average_true_range()
    atr14 = atr14.fillna(c * 0.01)
    df["ATR_14"] = atr14
    df["ATR_r"]  = atr14 / (c + 1e-8)

    # ── Moving averages ───────────────────────────────────────────────────────
    for p in [5, 10, 20, 50]:
        sma = ta.trend.sma_indicator(c, window=p)
        df[f"SMA_{p}"]   = sma
        df[f"SMA_{p}_r"] = c / (sma + 1e-8) - 1
    sma200 = c.rolling(200, min_periods=1).mean()
    df["SMA_200_r"]    = c / (sma200 + 1e-8) - 1
    df["Above_200SMA"] = (c > sma200).astype(int)
    df["EMA_9"]        = ta.trend.ema_indicator(c, window=9)
    df["EMA_21"]       = ta.trend.ema_indicator(c, window=21)
    df["EMA_50"]       = ta.trend.ema_indicator(c, window=50)

    # ── Momentum ──────────────────────────────────────────────────────────────
    df["RSI_7"]      = ta.momentum.rsi(c, window=7)
    df["RSI_14"]     = ta.momentum.rsi(c, window=14)
    df["RSI_21"]     = ta.momentum.rsi(c, window=21)
    df["Stoch_K"]    = ta.momentum.stoch(h, l, c, window=14, smooth_window=3)
    df["Stoch_D"]    = ta.momentum.stoch_signal(h, l, c, window=14, smooth_window=3)
    df["ROC_5"]      = ta.momentum.roc(c, window=5)
    df["ROC_10"]     = ta.momentum.roc(c, window=10)
    df["Williams_R"] = ta.momentum.williams_r(h, l, c, lbp=14)

    # ── Trend ─────────────────────────────────────────────────────────────────
    macd_ind       = ta.trend.MACD(c, window_fast=12, window_slow=26, window_sign=9)
    df["MACD"]     = macd_ind.macd()
    df["MACD_Sig"] = macd_ind.macd_signal()
    df["MACD_Diff"]= macd_ind.macd_diff()
    df["ADX"]      = ta.trend.adx(h, l, c, window=14)
    df["ADX_Pos"]  = ta.trend.adx_pos(h, l, c, window=14)
    df["ADX_Neg"]  = ta.trend.adx_neg(h, l, c, window=14)
    df["CCI"]      = ta.trend.cci(h, l, c, window=20)

    # ── Volatility ────────────────────────────────────────────────────────────
    bb             = ta.volatility.BollingerBands(c, window=20, window_dev=2)
    df["BB_Upper"] = bb.bollinger_hband()
    df["BB_Lower"] = bb.bollinger_lband()
    df["BB_Mid"]   = bb.bollinger_mavg()
    df["BB_Width"] = (df["BB_Upper"] - df["BB_Lower"]) / (df["BB_Mid"] + 1e-8)
    df["BB_Pos"]   = (c - df["BB_Lower"]) / (df["BB_Upper"] - df["BB_Lower"] + 1e-8)
    try:
        kc = ta.volatility.KeltnerChannel(h, l, c, window=20)
        df["KC_Squeeze"] = (
            (df["BB_Upper"] < kc.keltner_channel_hband()) &
            (df["BB_Lower"] > kc.keltner_channel_lband())
        ).astype(int)
    except Exception:
        df["KC_Squeeze"] = 0

    # ── Volume ────────────────────────────────────────────────────────────────
    vma20           = v.rolling(20, min_periods=1).mean()
    df["Volume_r"]  = v / (vma20 + 1)
    df["OBV"]       = ta.volume.on_balance_volume(c, v)
    df["OBV_r"]     = df["OBV"] / (df["OBV"].rolling(20, min_periods=1).mean() + 1e-8) - 1
    try:
        df["CMF"] = ta.volume.chaikin_money_flow(h, l, c, v, window=20)
    except Exception:
        df["CMF"] = 0.0
    vwap14          = ta.volume.volume_weighted_average_price(h, l, c, v, window=14)
    df["VWAP_r"]    = c / (vwap14 + 1e-8) - 1

    # ── ICT: Market Structure ─────────────────────────────────────────────────
    sh20 = h.rolling(20).max()
    sl20 = l.rolling(20).min()
    sh60 = h.rolling(60).max()
    sl60 = l.rolling(60).min()

    df["Dist_to_SH20"] = ((sh20 - c) / (atr14 + 1e-8)).clip(-10, 10)
    df["Dist_to_SL20"] = ((c - sl20) / (atr14 + 1e-8)).clip(-10, 10)
    df["Dist_to_SH60"] = ((sh60 - c) / (atr14 + 1e-8)).clip(-10, 10)
    df["Dist_to_SL60"] = ((c - sl60) / (atr14 + 1e-8)).clip(-10, 10)

    # HH / HL / LH / LL candle-structure tags
    df["HH"] = ((h > h.shift(1)) & (h.shift(1) > h.shift(2))).astype(int)
    df["LL"] = ((l < l.shift(1)) & (l.shift(1) < l.shift(2))).astype(int)
    df["HL"] = ((l > l.shift(2)) & (h < sh20.shift(1))).astype(int)
    df["LH"] = ((h < h.shift(2)) & (l > sl20.shift(1))).astype(int)

    df["Structure_Bullish"] = (sh20 > sh60.shift(20)).astype(int)

    # CHoCH, trend-reversal canaries
    hl_mask = (l > l.shift(2)) & (h < sh20.shift(1))
    lh_mask = (h < h.shift(2)) & (l > sl20.shift(1))
    recent_hl = l.where(hl_mask).rolling(10, min_periods=1).max().ffill()
    recent_lh = h.where(lh_mask).rolling(10, min_periods=1).min().ffill()
    df["CHoCH_Bear"] = ((c < recent_hl) &  df["Structure_Bullish"].astype(bool)).astype(int)
    df["CHoCH_Bull"] = ((c > recent_lh) & ~df["Structure_Bullish"].astype(bool)).astype(int)

    # ── ICT: Premium / Discount zones ────────────────────────────────────────
    rng60 = (sh60 - sl60).replace(0, np.nan)
    df["PD_Position"] = ((c - sl60) / rng60).fillna(0.5).clip(0, 1)
    df["In_Premium"]  = (df["PD_Position"] >= 0.55).astype(int)
    df["In_Discount"] = (df["PD_Position"] <= 0.45).astype(int)

    # ── ICT: Optimal Trade Entry (OTE: 0.62-0.79 Fibonacci retracement) ──────
    rng20 = (sh20 - sl20).replace(0, np.nan)
    df["In_OTE_Buy"]  = ((c >= sh20 - rng20 * 0.79) & (c <= sh20 - rng20 * 0.62)).astype(int)
    df["In_OTE_Sell"] = ((c >= sl20 + rng20 * 0.62) & (c <= sl20 + rng20 * 0.79)).astype(int)

    # ── ICT: Fair Value Gaps ──────────────────────────────────────────────────
    bull_fvg = (l > h.shift(2)).astype(int)
    bear_fvg = (h < l.shift(2)).astype(int)
    df["Bull_FVG_Count"] = bull_fvg.rolling(10, min_periods=1).sum()
    df["Bear_FVG_Count"] = bear_fvg.rolling(10, min_periods=1).sum()
    df["FVG_Net"]        = df["Bull_FVG_Count"] - df["Bear_FVG_Count"]

    # Consequent Encroachment (CE), midpoint of most recent FVG
    bull_ce = ((h.shift(2) + l) / 2).where(bull_fvg.astype(bool)).ffill()
    bear_ce = ((l.shift(2) + h) / 2).where(bear_fvg.astype(bool)).ffill()
    df["CE_Bull_Dist"] = ((c - bull_ce) / (atr14 + 1e-8)).clip(-10, 10).fillna(0)
    df["CE_Bear_Dist"] = ((bear_ce - c) / (atr14 + 1e-8)).clip(-10, 10).fillna(0)

    # ── ICT: Order Blocks ─────────────────────────────────────────────────────
    body = (c - o).abs()
    rng  = (h - l).replace(0, np.nan)
    df["Body_Ratio"]   = (body / rng).fillna(0).clip(0, 1)
    df["Displacement"] = ((rng.fillna(0) > atr14 * 1.5) & (df["Body_Ratio"] > 0.6)).astype(int)

    bear_c = (c < o)
    bull_c = (c > o)
    bull_ob = (bear_c.shift(1).fillna(False)) & (df["Displacement"] == 1) & bull_c
    bear_ob = (bull_c.shift(1).fillna(False)) & (df["Displacement"] == 1) & bear_c
    df["Bull_OB_Count"] = bull_ob.astype(int).rolling(10, min_periods=1).sum()
    df["Bear_OB_Count"] = bear_ob.astype(int).rolling(10, min_periods=1).sum()

    # Distance to last OB price level
    last_boh = h.where(bull_ob).ffill()
    last_bol = l.where(bull_ob).ffill()
    last_beh = h.where(bear_ob).ffill()
    last_bel = l.where(bear_ob).ffill()
    df["Bull_OB_H_Dist"] = ((last_boh - c) / (atr14 + 1e-8)).clip(-10, 10).fillna(0)
    df["Bull_OB_L_Dist"] = ((c - last_bol) / (atr14 + 1e-8)).clip(-10, 10).fillna(0)
    df["Bear_OB_H_Dist"] = ((last_beh - c) / (atr14 + 1e-8)).clip(-10, 10).fillna(0)
    df["Bear_OB_L_Dist"] = ((c - last_bel) / (atr14 + 1e-8)).clip(-10, 10).fillna(0)

    # ── ICT: Liquidity Pools & Sweeps ────────────────────────────────────────
    tol  = c * 0.001
    r10h = h.rolling(10).max().shift(1)
    r10l = l.rolling(10).min().shift(1)
    df["Equal_Highs"] = ((h - r10h).abs() < tol).astype(int).rolling(5, min_periods=1).sum()
    df["Equal_Lows"]  = ((l - r10l).abs() < tol).astype(int).rolling(5, min_periods=1).sum()
    df["Swept_High"]  = ((h > sh20.shift(1)) & (c < sh20.shift(1))).astype(int)
    df["Swept_Low"]   = ((l < sl20.shift(1)) & (c > sl20.shift(1))).astype(int)
    pwh = h.rolling(5).max().shift(1)
    pwl = l.rolling(5).min().shift(1)
    df["Dist_PWH"] = ((pwh - c) / (atr14 + 1e-8)).clip(-10, 10)
    df["Dist_PWL"] = ((c - pwl) / (atr14 + 1e-8)).clip(-10, 10)

    # ── ICT: IPDA Lookback Levels (20 / 40 / 60 bars) ────────────────────────
    for n in [20, 40, 60]:
        df[f"IPDA_{n}_H"] = ((h.rolling(n).max().shift(1) - c) / (atr14 + 1e-8)).clip(-20, 20)
        df[f"IPDA_{n}_L"] = ((c - l.rolling(n).min().shift(1)) / (atr14 + 1e-8)).clip(-20, 20)

    # ── ICT: Power of 3 (accumulation / manipulation / distribution) ──────────
    df["P3_Accum"]  = (df["Returns"].abs() < df["ATR_r"] * 0.5).astype(int)
    df["P3_Manip"]  = ((h > h.shift(1)) & (c < o)).astype(int)
    df["P3_Distrib"]= df["Displacement"].rolling(3, min_periods=1).sum()

    # ── Calendar / cyclical ───────────────────────────────────────────────────
    df["DayOfWeek"]   = np.array(df.index.dayofweek, dtype=np.int32)
    m = np.array(df.index.month,   dtype=np.int32)
    q = np.array(df.index.quarter, dtype=np.int32)
    df["Month_Sin"]   = np.sin(2 * np.pi * m / 12)
    df["Month_Cos"]   = np.cos(2 * np.pi * m / 12)
    df["Quarter_Sin"] = np.sin(2 * np.pi * q / 4)
    df["Quarter_Cos"] = np.cos(2 * np.pi * q / 4)

    # ── Lags ─────────────────────────────────────────────────────────────────
    for lag in range(1, 6):
        df[f"Ret_lag_{lag}"] = df["Returns"].shift(lag)
    for lag in range(1, 4):
        df[f"Vol_lag_{lag}"] = df["Volume_r"].shift(lag)

    # ── Intraday-only: Kill Zones, Session, Asia, NWOG ───────────────────────
    if is_intraday:
        idx = df.index
        et  = idx.tz_convert("America/New_York") if idx.tz else idx.tz_localize("UTC").tz_convert("America/New_York")
        hour   = np.array(et.hour,      dtype=np.int32)
        minute = np.array(et.minute,    dtype=np.int32)
        dow    = np.array(et.dayofweek, dtype=np.int32)

        df["KZ_London"]       = ((hour >= 2)  & (hour < 5)).astype(int)
        df["KZ_NY_Open"]      = ((hour >= 9)  & (hour < 11)).astype(int)
        df["KZ_London_Close"] = ((hour >= 10) & (hour < 12)).astype(int)
        df["KZ_NY_PM"]        = ((hour >= 13) & (hour < 16)).astype(int)
        df["KZ_SB_AM"]        = ((hour == 10) | ((hour == 9) & (minute >= 50))).astype(int)
        df["KZ_SB_PM"]        = ((hour >= 14) & (hour < 15)).astype(int)

        mins_in          = np.clip((hour - 9) * 60 + minute - 30, 0, 390)
        df["Session_Pct"]= mins_in / 390
        df["Hour_Sin"]   = np.sin(2 * np.pi * hour / 24)
        df["Hour_Cos"]   = np.cos(2 * np.pi * hour / 24)
        df["Day_Sin"]    = np.sin(2 * np.pi * dow / 5)
        df["Day_Cos"]    = np.cos(2 * np.pi * dow / 5)

        date_str = pd.Series(et.date, index=df.index)
        midnight_open = df.groupby(date_str)["Open"].transform("first")
        df["vs_MidOpen"] = (c - midnight_open) / (midnight_open + 1e-8) * 100

        sess_hi = df.groupby(date_str)["High"].transform("cummax")
        sess_lo = df.groupby(date_str)["Low"].transform("cummin")
        df["Sess_H_Dist"] = ((sess_hi - c) / (atr14 + 1e-8)).clip(-10, 10)
        df["Sess_L_Dist"] = ((c - sess_lo) / (atr14 + 1e-8)).clip(-10, 10)

        # Asia session range (8 PM - 2 AM ET) , use Series for .where() alignment
        is_asia_s = pd.Series((hour >= 20) | (hour < 2), index=df.index)
        asia_h    = h.where(is_asia_s).rolling(14, min_periods=1).max().ffill()
        asia_l    = l.where(is_asia_s).rolling(14, min_periods=1).min().ffill()
        df["Asia_H_Dist"] = ((asia_h - c) / (atr14 + 1e-8)).clip(-10, 10).fillna(0)
        df["Asia_L_Dist"] = ((c - asia_l) / (atr14 + 1e-8)).clip(-10, 10).fillna(0)
        df["Asia_Range"]  = ((asia_h - asia_l) / (atr14 + 1e-8)).clip(0, 20).fillna(0)
        df["Above_AsiaH"] = (c > asia_h).astype(int)
        df["Below_AsiaL"] = (c < asia_l).astype(int)

        # NWOG, New Week Opening Gap (Monday open vs prior Friday close)
        is_mon_s   = pd.Series(dow == 0, index=df.index)
        prev_close = c.shift(1)
        nwog_open  = df["Open"].where(is_mon_s).ffill()
        nwog_prev  = prev_close.where(is_mon_s).ffill()
        lo = nwog_prev.clip(lower=0)
        df["In_NWOG"]   = (nwog_open.notna() & nwog_prev.notna() &
                           c.between(lo, nwog_open, inclusive="both")).astype(int)
        week_gap         = (df["Open"] - prev_close).where(is_mon_s).ffill().fillna(0)
        df["NWOG_Norm"]  = (week_gap / (atr14 + 1e-8)).clip(-5, 5)

    return df


# ── MTF Context ───────────────────────────────────────────────────────────────

def add_mtf_context(df_low: pd.DataFrame, tf_low: str,
                    tf_feat: dict) -> pd.DataFrame:
    """Forward-fill higher-timeframe state variables into the lower-TF dataframe."""
    df = df_low.copy()
    for htf in MTF_SOURCES.get(tf_low, []):
        htf_df = tf_feat.get(htf, pd.DataFrame())
        if htf_df.empty:
            continue
        for src_col, suffix in MTF_COLS.items():
            col_name = f"HTF_{htf}_{suffix}"
            if src_col not in htf_df.columns:
                df[col_name] = 0.0
                continue
            s        = htf_df[src_col]
            union_ix = s.index.union(df.index)
            combined = s.reindex(union_ix).sort_index().ffill()
            df[col_name] = combined.reindex(df.index).values
    return df


# ── Training ──────────────────────────────────────────────────────────────────

def _make_target(df: pd.DataFrame, lookahead: int) -> pd.Series:
    return (df["Close"].shift(-lookahead) > df["Close"]).astype(int)


def _model_suffix(tf: str) -> str:
    """Match predictor.py convention: 1d -> '', others -> '_{tf}'."""
    return "" if tf == "1d" else f"_{tf}"


def train_one(ticker: str, tf: str, df: pd.DataFrame) -> dict | None:
    """Train LR + RF + XGBoost for one ticker/timeframe. Saves models and returns metrics."""
    _, lookahead, min_rows = TF_CONFIG[tf]

    df = df.copy()
    df["Target"] = _make_target(df, lookahead)
    df.dropna(inplace=True)

    if len(df) < min_rows:
        log.warning(f"    [{ticker}/{tf}] SKIP, {len(df)} rows < {min_rows}")
        return None

    feat_cols = [c for c in df.columns
                 if c not in {"Open", "High", "Low", "Close", "Volume", "Target"}]

    X = np.nan_to_num(df[feat_cols].values.astype(np.float32),
                      nan=0.0, posinf=10.0, neginf=-10.0)
    y = df["Target"].values.astype(int)

    split    = int(len(X) * 0.80)
    X_tr, X_te = X[:split], X[split:]
    y_tr, y_te = y[:split], y[split:]

    scaler   = StandardScaler()
    X_tr_s   = scaler.fit_transform(X_tr)
    X_te_s   = scaler.transform(X_te)

    # ── Logistic Regression ──────────────────────────────────────────────────
    lr = LogisticRegression(max_iter=2000, C=0.05, class_weight="balanced",
                            solver="saga", n_jobs=-1)
    lr.fit(X_tr_s, y_tr)
    lr_acc = accuracy_score(y_te, lr.predict(X_te_s))
    try:
        lr_auc = roc_auc_score(y_te, lr.predict_proba(X_te_s)[:, 1])
    except Exception:
        lr_auc = 0.5

    # ── Random Forest ────────────────────────────────────────────────────────
    n_trees = 100 if len(X_tr) > 50_000 else 200
    rf = RandomForestClassifier(n_estimators=n_trees, max_depth=10,
                                min_samples_leaf=30, class_weight="balanced",
                                random_state=42, n_jobs=-1)
    rf.fit(X_tr_s, y_tr)
    rf_acc = accuracy_score(y_te, rf.predict(X_te_s))
    try:
        rf_auc = roc_auc_score(y_te, rf.predict_proba(X_te_s)[:, 1])
    except Exception:
        rf_auc = 0.5

    # ── XGBoost (5-fold walk-forward CV + final model) ───────────────────────
    xgb_cv_acc = xgb_test_acc = xgb_auc = None
    xgb = None
    if XGB_OK:
        cv_trees = 100 if len(X_tr) > 50_000 else 200
        tscv     = TimeSeriesSplit(n_splits=5)
        fold_accs = []
        for tr_i, val_i in tscv.split(X_tr_s):
            m = XGBClassifier(n_estimators=cv_trees, max_depth=5, learning_rate=0.05,
                              subsample=0.8, colsample_bytree=0.7, min_child_weight=10,
                              gamma=0.1, reg_alpha=0.1, reg_lambda=1.0,
                              eval_metric="logloss", verbosity=0, random_state=42, n_jobs=-1)
            m.fit(X_tr_s[tr_i], y_tr[tr_i])
            fold_accs.append(accuracy_score(y_tr[val_i], m.predict(X_tr_s[val_i])))
        xgb_cv_acc = float(np.mean(fold_accs))

        final_trees = 300 if len(X_tr) <= 50_000 else 200
        xgb = XGBClassifier(n_estimators=final_trees, max_depth=5, learning_rate=0.05,
                             subsample=0.8, colsample_bytree=0.7, min_child_weight=10,
                             gamma=0.1, reg_alpha=0.1, reg_lambda=1.0,
                             eval_metric="logloss", verbosity=0, random_state=42, n_jobs=-1)
        xgb.fit(X_tr_s, y_tr)
        xgb_test_acc = accuracy_score(y_te, xgb.predict(X_te_s))
        try:
            xgb_auc = roc_auc_score(y_te, xgb.predict_proba(X_te_s)[:, 1])
        except Exception:
            xgb_auc = 0.5

    # ── Save ─────────────────────────────────────────────────────────────────
    suf = _model_suffix(tf)
    T   = ticker.upper()
    joblib.dump(lr,        os.path.join(MODELS_DIR, f"lr_model_{T}{suf}.pkl"))
    joblib.dump(rf,        os.path.join(MODELS_DIR, f"rf_model_{T}{suf}.pkl"))
    joblib.dump(scaler,    os.path.join(MODELS_DIR, f"scaler_sklearn_{T}{suf}.pkl"))
    joblib.dump(feat_cols, os.path.join(MODELS_DIR, f"feature_cols_sklearn_{T}{suf}.pkl"))
    if xgb is not None:
        joblib.dump(xgb,   os.path.join(MODELS_DIR, f"xgb_model_{T}{suf}.pkl"))

    xgb_str = ""
    if xgb_cv_acc is not None:
        xgb_str = f"  XGB cv={xgb_cv_acc:.3f} test={xgb_test_acc:.3f}/{xgb_auc:.3f}"
    log.info(f"    [{T}/{tf}] {len(df):,} rows  {len(feat_cols)} feats  "
             f"LR {lr_acc:.3f}/{lr_auc:.3f}  RF {rf_acc:.3f}/{rf_auc:.3f}{xgb_str}")

    return {
        "ticker": T, "tf": tf, "rows": len(df), "feats": len(feat_cols),
        "lr_acc": lr_acc,   "lr_auc": lr_auc,
        "rf_acc": rf_acc,   "rf_auc": rf_auc,
        "xgb_cv_acc": xgb_cv_acc, "xgb_test_acc": xgb_test_acc, "xgb_auc": xgb_auc,
    }


# ── Entry Point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="BullLogic professional multi-TF ICT training pipeline"
    )
    parser.add_argument("--tickers",       nargs="+", default=ALL_TICKERS)
    parser.add_argument("--timeframes",    nargs="+", default=list(TF_CONFIG.keys()))
    parser.add_argument("--skip-existing", action="store_true",
                        help="Skip ticker/TF combos whose models already exist")
    args = parser.parse_args()

    tickers    = [t.upper() for t in args.tickers]
    timeframes = [tf for tf in args.timeframes if tf in TF_CONFIG]

    log.info("=" * 70)
    log.info("  BullLogic Professional Multi-TF ICT Training Pipeline")
    log.info("=" * 70)
    log.info(f"  Tickers    : {', '.join(tickers)}")
    log.info(f"  Timeframes : {', '.join(timeframes)}")
    log.info(f"  XGBoost    : {'available' if XGB_OK else 'NOT installed'}")
    log.info(f"  Date range : {FETCH_START.date()} -> {FETCH_END.date()}")
    log.info(f"  Models dir : {MODELS_DIR}")
    log.info("=" * 70)

    all_results = []
    wall_start  = time.time()

    for ticker in tickers:
        t0 = time.time()
        log.info(f"\n{'─' * 60}")
        log.info(f"  TICKER: {ticker}")
        log.info(f"{'─' * 60}")

        # 1. Fetch 1m base data
        try:
            df_1m = fetch_1min(ticker)
        except Exception as exc:
            log.error(f"  {ticker}: fetch failed, {exc}")
            continue

        # 2. Resample 1m -> short timeframes
        tf_dfs: dict[str, pd.DataFrame] = {"1m": df_1m.copy()}
        for tf, (rule, _, _) in TF_CONFIG.items():
            if tf in ("1m", "1h", "4h", "1d"):
                continue
            try:
                tf_dfs[tf] = resample_ohlcv(df_1m, rule)
                log.info(f"  Resampled {tf:>4s}: {len(tf_dfs[tf]):,} bars")
            except Exception as exc:
                log.warning(f"  Resample {tf} failed: {exc}")

        # 2b. Fetch 1h and 1d directly from Alpaca for more historical data.
        #     4h is then resampled from the extended 1h feed.
        for tf, (alpaca_tf, start, chunk_days) in DIRECT_TF_FETCH.items():
            try:
                tf_dfs[tf] = fetch_tf_direct(ticker, alpaca_tf, start, chunk_days)
            except Exception as exc:
                log.warning(f"  Direct {tf} fetch failed, falling back to resample: {exc}")
                if tf not in tf_dfs:
                    rule = TF_CONFIG[tf][0]
                    try:
                        tf_dfs[tf] = resample_ohlcv(df_1m, rule)
                    except Exception:
                        pass

        # Build 4h from the (possibly extended) 1h data
        if "1h" in tf_dfs and not tf_dfs["1h"].empty:
            try:
                tf_dfs["4h"] = resample_ohlcv(tf_dfs["1h"], "4h")
                log.info(f"  Resampled {'4h':>4s}: {len(tf_dfs['4h']):,} bars (from 1h)")
            except Exception as exc:
                log.warning(f"  4h resample from 1h failed: {exc}")
        elif "4h" not in tf_dfs:
            try:
                tf_dfs["4h"] = resample_ohlcv(df_1m, "4h")
            except Exception:
                pass

        # 3. Compute ICT features for every TF (including those not being trained,
        #    as they may be needed as MTF context sources)
        tf_feat: dict[str, pd.DataFrame] = {}
        for tf in TF_CONFIG:
            if tf not in tf_dfs:
                continue
            try:
                tf_feat[tf] = compute_ict_features(tf_dfs[tf], is_intraday=(tf != "1d"))
            except Exception as exc:
                log.warning(f"  Features {tf} failed: {exc}")
                tf_feat[tf] = pd.DataFrame()

        # 4. Train each requested timeframe
        for tf in timeframes:
            if tf not in tf_feat or tf_feat[tf].empty:
                log.warning(f"  [{ticker}/{tf}] skip, no feature data")
                continue

            if args.skip_existing:
                suf  = _model_suffix(tf)
                path = os.path.join(MODELS_DIR, f"lr_model_{ticker}{suf}.pkl")
                if os.path.exists(path):
                    log.info(f"  [{ticker}/{tf}] skip, model already exists")
                    continue

            try:
                df_tf = add_mtf_context(tf_feat[tf], tf, tf_feat)
                result = train_one(ticker, tf, df_tf)
                if result:
                    all_results.append(result)
            except Exception as exc:
                log.error(f"  [{ticker}/{tf}] ERROR: {exc}", exc_info=True)

        log.info(f"  {ticker} completed in {time.time() - t0:.0f}s")

    # ── Summary ───────────────────────────────────────────────────────────────
    wall = time.time() - wall_start
    log.info(f"\n{'=' * 80}")
    log.info(f"  COMPLETE, {len(all_results)} models trained in {wall:.0f}s  ({wall/60:.1f} min)")
    log.info(f"{'=' * 80}")

    if all_results:
        hdr = (f"  {'Ticker':<8} {'TF':<5} {'Rows':>8} {'Feats':>6}"
               f"  {'LR Acc':>7} {'LR AUC':>7}"
               f"  {'RF Acc':>7} {'RF AUC':>7}"
               f"  {'XGB CV':>7} {'XGB Tst':>8} {'XGB AUC':>8}")
        log.info(hdr)
        log.info("  " + "─" * (len(hdr) - 2))
        for r in sorted(all_results, key=lambda x: (x["ticker"], list(TF_CONFIG).index(x["tf"]))):
            xgb_s = ""
            if r["xgb_cv_acc"] is not None:
                xgb_s = (f"  {r['xgb_cv_acc']:>7.3f} {r['xgb_test_acc']:>8.3f}"
                         f" {r['xgb_auc']:>8.3f}")
            log.info(
                f"  {r['ticker']:<8} {r['tf']:<5} {r['rows']:>8,} {r['feats']:>6}"
                f"  {r['lr_acc']:>7.3f} {r['lr_auc']:>7.3f}"
                f"  {r['rf_acc']:>7.3f} {r['rf_auc']:>7.3f}{xgb_s}"
            )

    log.info(f"\n  Log : {LOG_FILE}")
    log.info(f"  Models dir : {MODELS_DIR}")

    # Persist metrics for the AUC dashboard
    metrics_path = os.path.join(BASE_DIR, "Data", "model_metrics.json")
    try:
        with open(metrics_path, "w") as _mf:
            json.dump({"trained_at": datetime.now().isoformat(), "results": all_results},
                      _mf, indent=2, default=str)
        log.info(f"  Metrics saved -> {metrics_path}")
    except Exception as _e:
        log.warning(f"  Could not save metrics JSON: {_e}")

    # Auto-upload to Azure if configured
    conn_str = os.environ.get("AZURE_STORAGE_CONNECTION_STRING", "")
    if conn_str:
        try:
            from azure_storage import upload_models_to_azure
            trained = list({r["ticker"] for r in all_results})
            log.info(f"  Uploading {len(trained)} tickers to Azure…")
            for t in trained:
                upload_models_to_azure(t)
            log.info("  Azure upload complete.")
        except Exception as _ae:
            log.warning(f"  Azure upload failed: {_ae}")


if __name__ == "__main__":
    main()
