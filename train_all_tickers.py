"""
train_all_tickers.py
Train LR + RF models for all supported tickers in parallel.

- LR  predicts Next_Close (price)
- RF  predicts Next_Return (% return over the next bar)
- Supports daily (1d) and intraday (1h, 15m) intervals

Intervals and yfinance history limits:
  1d , unlimited history   (use period="max" for NDX/QQQ)
  1h , 730 days            (ICT kill zones + FVG/OB work properly)
  15m, 60 days             (very short; mainly for backtesting)

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
from sklearn.linear_model import Ridge
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import MinMaxScaler
from sklearn.metrics import mean_absolute_error, r2_score, accuracy_score, roc_auc_score
from sklearn.model_selection import TimeSeriesSplit

try:
    from xgboost import XGBClassifier
    _XGB_AVAILABLE = True
except ImportError:
    _XGB_AVAILABLE = False

import ict_features

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(BASE_DIR, "Saved Models")

# Interval -> (yfinance interval to download, yfinance period, minimum bars
# needed to train, whether it's resampled from a shorter interval after
# download). Intraday periods (1m/5m/15m/30m/1h/4h) are yfinance's hard
# server-side history limits - they cannot be extended by requesting a
# longer period. Only 1d/1w have deep history available, hence 20y there.
INTERVAL_CONFIG = {
    "1m":  {"yf_interval": "1m",  "yf_period": "7d",   "min_rows": 200, "resample_to": None},
    "5m":  {"yf_interval": "5m",  "yf_period": "60d",  "min_rows": 200, "resample_to": None},
    "15m": {"yf_interval": "15m", "yf_period": "60d",  "min_rows": 150, "resample_to": None},
    "30m": {"yf_interval": "30m", "yf_period": "60d",  "min_rows": 100, "resample_to": None},
    "1h":  {"yf_interval": "1h",  "yf_period": "730d", "min_rows": 100, "resample_to": None},
    "4h":  {"yf_interval": "1h",  "yf_period": "730d", "min_rows": 80,  "resample_to": "4h"},
    "1d":  {"yf_interval": "1d",  "yf_period": "20y",  "min_rows": 300, "resample_to": None},
    "1w":  {"yf_interval": "1wk", "yf_period": "20y",  "min_rows": 60,  "resample_to": None},
}
SUPPORTED_INTERVALS = list(INTERVAL_CONFIG)

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

# ── Ticker → sector ETF mapping ───────────────────────────────────────────────

TICKER_SECTOR_MAP = {
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

EQUITY_TICKERS = {
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "AMD",
    "NFLX", "JPM", "GS", "BAC", "V", "MA", "JNJ", "PFE", "UNH",
    "XOM", "CVX", "WMT", "HD", "COST", "BA", "DIS", "CRM", "ADBE",
    "ABBV", "MRK", "PG", "KO", "NKE", "CAT", "GE", "COP",
}

# ── Macro / sector / earnings feature columns (defined before DAILY_FEATURE_COLS) ─

VIX_FEATURE_COLS = [
    "VIX_Level", "VIX_Change", "VIX_Percentile_252",
    "VIX_Regime", "VIX_MA_Ratio",
]

SECTOR_FEATURE_COLS = [
    "Sector_RS_20", "Sector_RS_60", "Sector_vs_SPY_20", "Sector_Momentum",
]

EARNINGS_FEATURE_COLS = [
    "Days_To_Earnings", "Days_Since_Earnings",
    "Pre_Earnings_Window", "Post_Earnings_Window",
]

# Quant alpha features from alphas.py (momentum, mean reversion, volatility,
# volume) plus the equal-weight composite. Causal by contract, tested in
# tests/test_alphas.py.
try:
    from alphas import ALPHA_REGISTRY as _ALPHA_REGISTRY
    ALPHA_FEATURE_COLS = [f"Alpha_{name}" for name in _ALPHA_REGISTRY] + ["Alpha_composite"]
except ImportError:
    ALPHA_FEATURE_COLS = []

# ── Feature lists ──────────────────────────────────────────────────────────────

DAILY_FEATURE_COLS = [
    "Close", "High", "Low", "Volume",
    "SMA_7", "SMA_21", "EMA_12", "EMA_26",
    "RSI_14", "MACD", "MACD_Signal", "MACD_Hist",
    "BB_Upper", "BB_Lower", "BB_Width",
    "Volume_SMA_10", "Daily_Return",
    "Close_lag_1", "Close_lag_2", "Close_lag_3", "Close_lag_4", "Close_lag_5",
    "Return_lag_1", "Return_lag_2", "Return_lag_3",
    # ICT (base + advanced concepts) - see ict_features.py
    *ict_features.BASE_ICT_COLS,
    # SMT divergence (needs a correlated reference instrument)
    *ict_features.SMT_COLS,
    # Macro
    *VIX_FEATURE_COLS,
    # Sector rotation
    *SECTOR_FEATURE_COLS,
    # Earnings proximity
    *EARNINGS_FEATURE_COLS,
    # Quant alphas
    *ALPHA_FEATURE_COLS,
]

# Intraday adds kill-zone, session, and 2022 Silver Bullet / Asia range features
INTRADAY_EXTRA_COLS = list(ict_features.INTRADAY_ICT_COLS)


# ── Data fetching ──────────────────────────────────────────────────────────────

def fetch_data(ticker: str, interval: str = "1d") -> pd.DataFrame:
    if interval not in INTERVAL_CONFIG:
        raise ValueError(f"Unsupported interval: {interval}")

    yf_ticker = YF_SYMBOL_MAP.get(ticker, ticker.replace(".", "-"))
    cfg = INTERVAL_CONFIG[interval]
    period = cfg["yf_period"]

    df = yf.download(yf_ticker, period=period, interval=cfg["yf_interval"],
                     auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    if cfg["resample_to"] == "4h" and df is not None and not df.empty:
        df = df.resample("4h", label="left", closed="left").agg({
            "Open": "first", "High": "max", "Low": "min",
            "Close": "last", "Volume": "sum",
        }).dropna(subset=["Open", "Close"])
        df = df[df["Volume"] > 0]

    return df


def fetch_aux_data(ticker: str, interval: str = "1d") -> dict:
    """Fetch VIX, sector ETF, SPY, and earnings dates for a ticker.

    Aux series are aligned to the main df by calendar day (see
    _add_vix_features/_add_sector_features), so it's fine to fetch them at
    the underlying yfinance interval even for resampled intervals like 4h.
    """
    cfg = INTERVAL_CONFIG.get(interval, INTERVAL_CONFIG["1d"])
    period = cfg["yf_period"]
    yf_interval = cfg["yf_interval"]

    def _dl(sym):
        try:
            df = yf.download(sym, period=period, interval=yf_interval,
                             auto_adjust=True, progress=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            return df if not df.empty else None
        except Exception:
            return None

    vix    = _dl("^VIX")
    spy    = _dl("SPY") if ticker != "SPY" else None
    sec_id = TICKER_SECTOR_MAP.get(ticker.upper())
    sector = _dl(sec_id) if sec_id and sec_id not in (ticker, "SPY") else None

    earnings = pd.DatetimeIndex([])
    if ticker.upper() in EQUITY_TICKERS:
        try:
            raw = yf.Ticker(ticker).earnings_dates
            if raw is not None and not raw.empty:
                idx = raw.index.tz_localize(None) if raw.index.tz else raw.index
                earnings = idx.normalize()
        except Exception:
            pass

    return {"vix": vix, "spy": spy, "sector": sector, "earnings": earnings}


# ── Feature engineering ────────────────────────────────────────────────────────

def _add_base_ta(df: pd.DataFrame) -> pd.DataFrame:
    """Standard TA + ICT features shared by all timeframes."""
    return ict_features.add_base_ta(df)


def _add_intraday_ict(df: pd.DataFrame) -> pd.DataFrame:
    """Kill-zone, session, and ICT 2022 intraday-only features."""
    return ict_features.add_intraday_ict(df)


def _add_vix_features(df: pd.DataFrame, vix_df) -> pd.DataFrame:
    _zero = {c: 0.0 for c in VIX_FEATURE_COLS}
    if vix_df is None or vix_df.empty:
        return df.assign(**_zero)

    # Align VIX to ticker's trading days. Source may itself be intraday
    # (multiple bars per day), so collapse to one value per day before
    # reindexing - .reindex() requires a unique source index.
    idx = df.index.normalize() if df.index.tz is None else df.index.tz_convert(None).normalize()
    vix_close = vix_df["Close"].copy()
    vix_close.index = vix_close.index.normalize() if vix_close.index.tz is None else vix_close.index.tz_localize(None).normalize()
    vix_close = vix_close[~vix_close.index.duplicated(keep="last")]
    vix = vix_close.reindex(idx, method="ffill").values

    vix_s = pd.Series(vix, index=df.index)
    df["VIX_Level"]          = vix_s.fillna(20.0)
    df["VIX_Change"]         = vix_s.pct_change().fillna(0) * 100
    df["VIX_Percentile_252"] = vix_s.rolling(252, min_periods=60).rank(pct=True).fillna(0.5)
    df["VIX_Regime"]         = pd.cut(df["VIX_Level"], bins=[0, 15, 25, 200],
                                       labels=[0, 1, 2]).astype(float).fillna(1.0)
    vma20 = vix_s.rolling(20, min_periods=5).mean()
    df["VIX_MA_Ratio"]       = (vix_s / vma20.replace(0, np.nan)).fillna(1.0).clip(0.5, 2.0)
    return df


def _add_sector_features(df: pd.DataFrame, sector_df, spy_df) -> pd.DataFrame:
    _zero = {c: 0.0 for c in SECTOR_FEATURE_COLS}

    def _align(src_df):
        if src_df is None or src_df.empty:
            return None
        s = src_df["Close"].copy()
        s.index = s.index.normalize() if s.index.tz is None else s.index.tz_localize(None).normalize()
        s = s[~s.index.duplicated(keep="last")]
        idx = df.index.normalize() if df.index.tz is None else df.index.tz_convert(None).normalize()
        out = s.reindex(idx, method="ffill")
        out.index = df.index      # restore df's original (possibly tz-aware) index for arithmetic
        return out

    sec = _align(sector_df)
    spy = _align(spy_df)

    if sec is None and spy is None:
        return df.assign(**_zero)

    tick = df["Close"]
    ref  = sec if sec is not None else spy   # fallback to SPY when no sector ETF

    # Ticker relative strength vs sector (or SPY)
    tr20 = tick.pct_change(20).fillna(0)
    rr20 = ref.pct_change(20).fillna(0)
    df["Sector_RS_20"] = (tr20 - rr20).clip(-0.5, 0.5)

    tr60 = tick.pct_change(60).fillna(0)
    rr60 = ref.pct_change(60).fillna(0)
    df["Sector_RS_60"] = (tr60 - rr60).clip(-0.5, 0.5)

    # Sector vs broad market
    if sec is not None and spy is not None:
        sr20 = sec.pct_change(20).fillna(0)
        mr20 = spy.pct_change(20).fillna(0)
        df["Sector_vs_SPY_20"] = (sr20 - mr20).clip(-0.3, 0.3)
        # Sector RSI (14-day momentum)
        df["Sector_Momentum"]  = ta.momentum.rsi(ref.fillna(method="ffill"), window=14).fillna(50)
    else:
        df["Sector_vs_SPY_20"] = 0.0
        df["Sector_Momentum"]  = ta.momentum.rsi(ref.fillna(method="ffill"), window=14).fillna(50)

    return df


def _add_earnings_features(df: pd.DataFrame, earnings: pd.DatetimeIndex) -> pd.DataFrame:
    _zero = {c: 0.0 for c in EARNINGS_FEATURE_COLS}
    if earnings is None or len(earnings) == 0:
        return df.assign(**_zero)

    dates_arr = np.array(sorted(set(pd.DatetimeIndex(earnings).normalize())), dtype="datetime64[D]")
    idx_norm  = pd.DatetimeIndex(
        df.index.normalize() if df.index.tz is None else df.index.tz_convert(None).normalize()
    ).values.astype("datetime64[D]")

    days_to, days_since = [], []
    for d_np in idx_norm:
        future = dates_arr[dates_arr > d_np]
        past   = dates_arr[dates_arr <= d_np]
        days_to.append(int((future[0] - d_np).astype(int)) if len(future) else 90)
        days_since.append(int((d_np - past[-1]).astype(int)) if len(past) else 90)

    dt_s = pd.Series(days_to,   index=df.index, dtype=float).clip(0, 90)
    ds_s = pd.Series(days_since, index=df.index, dtype=float).clip(0, 90)
    df["Days_To_Earnings"]     = dt_s
    df["Days_Since_Earnings"]  = ds_s
    df["Pre_Earnings_Window"]  = (dt_s <= 5).astype(float)
    df["Post_Earnings_Window"] = (ds_s <= 2).astype(float)
    return df


def engineer_features(df: pd.DataFrame, interval: str = "1d",
                      ticker: str = "", aux: dict = None) -> pd.DataFrame:
    df = _add_base_ta(df)
    if interval != "1d":
        df = _add_intraday_ict(df)
    if aux:
        df = _add_vix_features(df, aux.get("vix"))
        df = _add_sector_features(df, aux.get("sector"), aux.get("spy"))
        df = _add_earnings_features(df, aux.get("earnings", pd.DatetimeIndex([])))
        df = ict_features.add_smt_divergence(df, aux.get("spy") if aux.get("spy") is not None else aux.get("sector"))
    else:
        # Zero-fill new columns so feature list is always consistent
        for c in VIX_FEATURE_COLS + SECTOR_FEATURE_COLS + EARNINGS_FEATURE_COLS + ict_features.SMT_COLS:
            df[c] = 0.0

    if ALPHA_FEATURE_COLS:
        from alphas import add_alpha_features
        df = add_alpha_features(df)

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
    min_rows = INTERVAL_CONFIG.get(interval, {}).get("min_rows", 300)
    if df is None or df.empty or len(df) < min_rows:
        got = 0 if df is None else len(df)
        print(f"  SKIP {ticker} {interval}: only {got} bars (need {min_rows})")
        return {"ticker": ticker, "status": "skipped", "elapsed": 0, "bars": got}

    aux  = fetch_aux_data(ticker, interval)
    df   = engineer_features(df, interval, ticker, aux)
    feat = [c for c in _feature_list(interval) if c in df.columns]

    suffix = model_suffix(interval)

    split1 = int(len(df) * 0.8)
    split2 = int(len(df) * 0.9)

    # Drop columns that are constant over the training window (e.g. earnings-
    # proximity or Asia-session features on a short/limited history window).
    # MinMaxScaler divides by (max-min); a zero-variance column divides by
    # zero and blows LR's coefficients up to nonsense (seen on 5m/30m/1w with
    # short intraday histories or degenerate calendar features on weekly bars).
    train_std = df[feat].iloc[:split1].std()
    feat = [c for c in feat if train_std[c] > 1e-9]

    X      = df[feat].values
    y_px   = df["Next_Close"].values
    y_ret  = df["Next_Return"].values

    X_train, X_test = X[:split1], X[split2:]
    y_px_train      = y_px[:split1]
    y_ret_train     = y_ret[:split1]
    y_px_test       = y_px[split2:]
    close_test      = df["Close"].values[split2:]

    scaler  = MinMaxScaler()
    X_train = scaler.fit_transform(X_train)
    X_test  = scaler.transform(X_test)

    # Ridge (L2-regularized) rather than plain OLS: several features are
    # highly collinear (Close, High, Low, SMA/EMA, Close_lag_*), which makes
    # unregularized LinearRegression's normal equations near-singular -
    # coefficients can blow up to absurd magnitudes (seen on BTC 5m: MAE in
    # the tens of trillions). Ridge keeps this numerically stable.
    lr = Ridge(alpha=1.0)
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

    # ── XGBoost direction classifier ───────────────────────────────────────────
    xgb_cv_acc = xgb_test_acc = xgb_auc = None
    if _XGB_AVAILABLE:
        X_raw = df[feat].values          # unscaled, rescaled per CV fold
        y_dir = (df["Next_Return"].values > 0).astype(int)

        # 5-fold walk-forward CV on training portion (no data leakage).
        # Purge: drop the last bars of each training fold whose forward
        # looking labels overlap the validation window.
        _PURGE = 5
        X_cv  = X_raw[:split1]
        y_cv  = y_dir[:split1]
        tscv  = TimeSeriesSplit(n_splits=5)
        fold_accs = []
        for tr_idx, val_idx in tscv.split(X_cv):
            if len(tr_idx) > _PURGE:
                tr_idx = tr_idx[:-_PURGE]
            sc_tmp = MinMaxScaler().fit(X_cv[tr_idx])
            Xtr = sc_tmp.transform(X_cv[tr_idx])
            Xvl = sc_tmp.transform(X_cv[val_idx])
            m = XGBClassifier(n_estimators=100, max_depth=4, learning_rate=0.05,
                              subsample=0.8, colsample_bytree=0.8,
                              random_state=42, eval_metric="logloss", verbosity=0)
            m.fit(Xtr, y_cv[tr_idx])
            fold_accs.append(accuracy_score(y_cv[val_idx], m.predict(Xvl)))
        xgb_cv_acc = float(np.mean(fold_accs))

        # Final model trained on full training split
        xgb = XGBClassifier(n_estimators=200, max_depth=4, learning_rate=0.05,
                             subsample=0.8, colsample_bytree=0.8,
                             random_state=42, eval_metric="logloss", verbosity=0)
        xgb.fit(X_train, y_dir[:split1])      # X_train already scaled by scaler
        y_dir_test = y_dir[split2:]
        xgb_preds  = xgb.predict(X_test)
        xgb_proba  = xgb.predict_proba(X_test)[:, 1]
        xgb_test_acc = float(accuracy_score(y_dir_test, xgb_preds))
        try:
            xgb_auc = float(roc_auc_score(y_dir_test, xgb_proba))
        except Exception:
            xgb_auc = 0.5

        joblib.dump(xgb, os.path.join(MODELS_DIR, f"xgb_model_{ticker}{suffix}.pkl"))

    os.makedirs(MODELS_DIR, exist_ok=True)
    joblib.dump(lr,     os.path.join(MODELS_DIR, f"lr_model_{ticker}{suffix}.pkl"))
    joblib.dump(rf,     os.path.join(MODELS_DIR, f"rf_model_{ticker}{suffix}.pkl"))
    joblib.dump(scaler, os.path.join(MODELS_DIR, f"scaler_sklearn_{ticker}{suffix}.pkl"))
    joblib.dump(feat,   os.path.join(MODELS_DIR, f"feature_cols_sklearn_{ticker}{suffix}.pkl"))

    return {
        "ticker":       ticker,
        "status":       "ok",
        "rows":         len(df),
        "feat":         len(feat),
        "lr_mae":       round(lr_mae, 4),
        "lr_r2":        round(lr_r2, 4),
        "rf_mae":       round(rf_mae, 4),
        "rf_r2":        round(rf_r2, 4),
        "xgb_cv_acc":   round(xgb_cv_acc,   4) if xgb_cv_acc   is not None else None,
        "xgb_test_acc": round(xgb_test_acc,  4) if xgb_test_acc is not None else None,
        "xgb_auc":      round(xgb_auc,       4) if xgb_auc      is not None else None,
        "elapsed":      round(time.time() - t0, 1),
    }


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tickers",  nargs="+", default=DEFAULT_TICKERS)
    parser.add_argument("--interval", default="1d",
                        choices=SUPPORTED_INTERVALS,
                        help="Bar interval: " + ", ".join(SUPPORTED_INTERVALS) + " (default: 1d)")
    parser.add_argument("--upload",   action="store_true",
                        help="Upload models to Azure after training")
    parser.add_argument("--fast",     action="store_true",
                        help="RF-50/depth-6, faster, slightly lower accuracy")
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

    history_note = INTERVAL_CONFIG[args.interval]["yf_period"]
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
                xgb_str = ""
                if r.get("xgb_cv_acc") is not None:
                    xgb_str = (f"  XGB cv={r['xgb_cv_acc']:.3f}"
                               f" test={r['xgb_test_acc']:.3f}"
                               f" auc={r['xgb_auc']:.3f}")
                print(f"  [{t:6s}] {r['rows']:,} bars  {r['feat']} feats  "
                      f"LR MAE=${r['lr_mae']:.2f}  RF MAE=${r['rf_mae']:.2f}"
                      f"{xgb_str}  ({r['elapsed']}s)")
            else:
                print(f"  [{t:6s}] {r['status']}")

    wall = time.time() - wall_start
    ok   = [r for r in results if r["status"] == "ok"]
    print(f"\n=== Finished {len(tickers)} tickers in {wall:.1f}s ===")

    if ok:
        has_xgb = any(r.get("xgb_cv_acc") is not None for r in ok)
        hdr = f"{'Ticker':<8} {'LR MAE':>10} {'RF MAE':>10} {'LR R2':>8} {'Bars':>8}"
        if has_xgb:
            hdr += f"  {'XGB CV':>8} {'XGB Test':>9} {'AUC':>7}"
        print(f"\n{hdr}")
        print("-" * (50 + (28 if has_xgb else 0)))
        for r in sorted(ok, key=lambda x: x["ticker"]):
            line = (f"{r['ticker']:<8} ${r['lr_mae']:>9.2f} ${r['rf_mae']:>9.2f} "
                    f"{r['lr_r2']:>8.4f} {r['rows']:>8,}")
            if has_xgb and r.get("xgb_cv_acc") is not None:
                line += (f"  {r['xgb_cv_acc']:>8.3f} {r['xgb_test_acc']:>9.3f}"
                         f" {r['xgb_auc']:>7.3f}")
            print(line)

    if args.upload:
        from azure_storage import upload_models_to_azure
        print("\nUploading to Azure...")
        for r in ok:
            upload_models_to_azure(r["ticker"])
            print(f"  {r['ticker']} uploaded.")


if __name__ == "__main__":
    main()
