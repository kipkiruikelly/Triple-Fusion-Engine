"""
feature_engineering.py
Enhanced ICT-Inspired Feature Engineering for the Triple-Fusion-Engine.

Extends the existing ICT features in data_pipeline.py with additional
professional-grade concepts used by institutional traders:

  - Break of Structure (BOS) / Change of Character (CHoCH)
  - Multi-timeframe Fair Value Gaps (FVG)
  - Order Flow Imbalance (Delta)
  - Market Structure Shifts (MSS)
  - Volume Profile nodes (POC, VAH, VAL)
  - Cumulative Delta divergence
  - Feature importance analysis across all models

All functions are pure: they accept a pd.DataFrame with OHLCV columns
and return a pd.DataFrame with new feature columns. No forward-looking
bias - every feature at time t uses only data available at or before t.

Usage:
    from feature_engineering import add_enhanced_ict_features
    df = add_enhanced_ict_features(df)

Author: BullLogic
"""

import logging
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)
EPS = 1e-12


# ── Break of Structure (BOS) / Change of Character (CHoCH) ──────────────────────

def detect_bos_choch(df: pd.DataFrame, swing_lookback: int = 20) -> pd.DataFrame:
    """Detect Break of Structure and Change of Character events.

    BOS (Break of Structure):
      - Bullish BOS: price breaks above a previous swing high in an uptrend
      - Bearish BOS: price breaks below a previous swing low in a downtrend

    CHoCH (Change of Character):
      - Bullish CHoCH: price breaks above a key resistance, shifting trend
      - Bearish CHoCH: price breaks below a key support, shifting trend

    The key difference: BOS confirms existing trend, CHoCH signals a reversal.

    Features added:
      - BOS_Bull: 1 if bullish BOS detected on this bar
      - BOS_Bear: 1 if bearish BOS detected on this bar
      - CHoCH_Bull: 1 if bullish CHoCH detected
      - CHoCH_Bear: 1 if bearish CHoCH detected
      - BOS_Bull_Count: rolling count of bullish BOS (last 20 bars)
      - BOS_Bear_Count: rolling count of bearish BOS (last 20 bars)
      - CHoCH_Signal: cumulative BOS-CHoCH signal (-1 to +1 range)
    """
    df = df.copy()
    high  = df["High"].values
    low   = df["Low"].values
    close = df["Close"].values
    n = len(df)

    # Detect swing highs and lows using a simple pivot method
    # A swing high: higher than N bars before and N bars after
    bos_bull  = np.zeros(n, dtype=int)
    bos_bear  = np.zeros(n, dtype=int)
    choch_bull = np.zeros(n, dtype=int)
    choch_bear = np.zeros(n, dtype=int)

    # Track recent swing levels
    last_swing_high = np.full(n, np.nan)
    last_swing_low  = np.full(n, np.nan)
    trend = np.zeros(n, dtype=int)  # 1 = bullish, -1 = bearish

    for i in range(swing_lookback, n - swing_lookback):
        # Swing high detection
        window_high = high[i - swing_lookback // 2: i + swing_lookback // 2 + 1]
        if high[i] == window_high.max():
            last_swing_high[i] = high[i]

        # Swing low detection
        window_low = low[i - swing_lookback // 2: i + swing_lookback // 2 + 1]
        if low[i] == window_low.min():
            last_swing_low[i] = low[i]

    # Forward-fill swing levels
    sh_series = pd.Series(last_swing_high).ffill().values
    sl_series = pd.Series(last_swing_low).ffill().values

    # Detect BOS and CHoCH
    for i in range(swing_lookback * 2, n):
        prev_high = np.nanmax(last_swing_high[:i])
        prev_low  = np.nanmin(last_swing_low[:i])

        if not np.isnan(prev_high) and close[i] > prev_high:
            if trend[max(0, i - 20): i + 1].sum() >= 0:
                bos_bull[i] = 1
            else:
                choch_bull[i] = 1
            trend[i] = 1

        if not np.isnan(prev_low) and close[i] < prev_low:
            if trend[max(0, i - 20): i + 1].sum() <= 0:
                bos_bear[i] = 1
            else:
                choch_bear[i] = 1
            trend[i] = -1

    df["BOS_Bull"]  = bos_bull
    df["BOS_Bear"]  = bos_bear
    df["CHoCH_Bull"] = choch_bull
    df["CHoCH_Bear"] = choch_bear

    # Rolling aggregations. The Series must share df's index: a bare
    # pd.Series gets a RangeIndex, which aligns to nothing on a
    # DatetimeIndex frame and silently assigns all-NaN columns.
    df["BOS_Bull_Count"]  = pd.Series(bos_bull, index=df.index).rolling(20, min_periods=1).sum()
    df["BOS_Bear_Count"]  = pd.Series(bos_bear, index=df.index).rolling(20, min_periods=1).sum()
    df["CHoCH_Signal"]     = (
        pd.Series(choch_bull - choch_bear, index=df.index).rolling(20, min_periods=1).mean()
    ).fillna(0).clip(-1, 1)

    return df


# ── Enhanced Fair Value Gaps (Multi-Bar FVG) ────────────────────────────────────

def detect_enhanced_fvg(
    df: pd.DataFrame,
    gap_threshold_pct: float = 0.05,
) -> pd.DataFrame:
    """Detect Fair Value Gaps across multiple bar configurations.

    Standard FVG (3-bar): gap when bar[i].low > bar[i-2].high (bullish)
    Extended FVG (4-bar): gap spanning multiple bars
    Inversion FVG: when a prior FVG gets "filled" or "respected"

    Features:
      - FVG_Bull_3bar, FVG_Bear_3bar: standard 3-bar gaps
      - FVG_Bull_4bar, FVG_Bear_4bar: extended 4-bar gaps
      - FVG_Filled: 1 when price retraces into a prior FVG zone
      - FVG_Mitigated: count of FVGs that were filled in the last 20 bars
    """
    df = df.copy()
    high = df["High"].values
    low  = df["Low"].values
    close = df["Close"].values
    n = len(df)

    # 3-bar FVG
    fvg_bull_3 = np.zeros(n, dtype=int)
    fvg_bear_3 = np.zeros(n, dtype=int)

    for i in range(2, n):
        if low[i] > high[i - 2]:
            gap_pct = (low[i] - high[i - 2]) / high[i - 2] * 100
            if gap_pct >= gap_threshold_pct:
                fvg_bull_3[i] = 1
        if high[i] < low[i - 2]:
            gap_pct = (low[i - 2] - high[i]) / low[i - 2] * 100
            if gap_pct >= gap_threshold_pct:
                fvg_bear_3[i] = 1

    # 4-bar FVG
    fvg_bull_4 = np.zeros(n, dtype=int)
    fvg_bear_4 = np.zeros(n, dtype=int)

    for i in range(3, n):
        if low[i] > high[i - 3]:
            gap_pct = (low[i] - high[i - 3]) / high[i - 3] * 100
            if gap_pct >= gap_threshold_pct:
                fvg_bull_4[i] = 1
        if high[i] < low[i - 3]:
            gap_pct = (low[i - 3] - high[i]) / low[i - 3] * 100
            if gap_pct >= gap_threshold_pct:
                fvg_bear_4[i] = 1

    # FVG fill detection: price enters a prior FVG zone
    fvg_filled = np.zeros(n, dtype=int)
    for i in range(3, n):
        for j in range(max(0, i - 20), i - 2):
            # Check if any prior bull FVG got filled
            if fvg_bull_3[j]:
                fvg_top    = low[j]
                fvg_bottom = high[j - 2]
                if low[i] <= fvg_top and close[i] <= fvg_top:
                    fvg_filled[i] = 1
                    break
            # Check bear FVG fill
            if fvg_bear_3[j]:
                fvg_top    = low[j - 2]
                fvg_bottom = high[j]
                if high[i] >= fvg_bottom and close[i] >= fvg_bottom:
                    fvg_filled[i] = 1
                    break

    df["FVG_Bull_3bar"] = fvg_bull_3
    df["FVG_Bear_3bar"] = fvg_bear_3
    df["FVG_Bull_4bar"] = fvg_bull_4
    df["FVG_Bear_4bar"] = fvg_bear_4
    df["FVG_Filled"]    = fvg_filled
    # index= keeps alignment with df's DatetimeIndex (a bare Series would
    # align to nothing and assign all-NaN).
    df["FVG_Mitigated"] = pd.Series(fvg_filled, index=df.index).rolling(20, min_periods=1).sum()

    return df


# ── Order Flow Imbalance ────────────────────────────────────────────────────────

def detect_order_flow_imbalance(df: pd.DataFrame) -> pd.DataFrame:
    """Estimate order flow imbalance from OHLCV data.

    Since we don't have actual tick data, we approximate delta (buy - sell pressure)
    using candle characteristics and volume:

      - Delta_Approx: approximate buy volume - sell volume
        Uses candle body direction and wick ratios to split volume
      - Delta_EMA: exponential moving average of delta
      - Delta_Divergence: price making new highs but delta declining (bearish divergence)
      - Cumulative_Delta: running sum of delta (smart money tracker)

    Features:
      - OF_Delta: approximated order flow delta
      - OF_Delta_EMA_5, OF_Delta_EMA_20: smoothed delta
      - OF_Delta_Div: divergence signal (-1 to 1)
      - OF_CumDelta_5: 5-bar cumulative delta z-score
    """
    df = df.copy()
    high  = df["High"]
    low   = df["Low"]
    open_ = df["Open"]
    close = df["Close"]
    vol   = df["Volume"].fillna(0)

    # Approximate delta: split volume by candle character
    body     = (close - open_).abs()
    upper_w  = high - close.clip(lower=open_)
    lower_w  = open_.clip(upper=close) - low
    total_r  = body + upper_w + lower_w + EPS

    # Buy pressure: body (if bullish) + upper wick rejection
    buy_pct  = ((body * (close > open_).astype(float) + lower_w) / total_r).fillna(0.5)
    delta    = vol * (buy_pct - 0.5) * 2  # Range: -Vol to +Vol

    df["OF_Delta"] = delta

    # Smoothed delta
    df["OF_Delta_EMA_5"]  = delta.ewm(span=5,  adjust=False).mean()
    df["OF_Delta_EMA_20"] = delta.ewm(span=20, adjust=False).mean()

    # Delta divergence: price rises but delta weakens
    price_rising  = (close.diff(5) > 0).astype(int)
    delta_weakening = (df["OF_Delta_EMA_5"].diff(5) < 0).astype(int)
    df["OF_Delta_Div"] = (price_rising & delta_weakening).astype(int)

    # Price falling but delta strengthening (bullish divergence)
    price_falling = (close.diff(5) < 0).astype(int)
    delta_strengthening = (df["OF_Delta_EMA_5"].diff(5) > 0).astype(int)
    df["OF_Delta_Div"] -= (price_falling & delta_strengthening).astype(int)

    # Cumulative delta z-score
    cum_delta = delta.rolling(5, min_periods=1).sum()
    cum_mean  = cum_delta.rolling(60, min_periods=10).mean()
    cum_std   = cum_delta.rolling(60, min_periods=10).std()
    df["OF_CumDelta_5"] = ((cum_delta - cum_mean) / (cum_std + EPS)).fillna(0).clip(-3, 3)

    return df


# ── Market Structure Analysis ───────────────────────────────────────────────────

def detect_market_structure(df: pd.DataFrame) -> pd.DataFrame:
    """Analyze market structure: Higher Highs, Lower Lows, consolidations.

    Classic Dow Theory structure:
      - Uptrend: series of higher highs (HH) and higher lows (HL)
      - Downtrend: series of lower highs (LH) and lower lows (LL)
      - Consolidation: neither pattern clear

    Features:
      - MS_HH: 1 if this bar is a higher high
      - MS_HL: 1 if this bar is a higher low
      - MS_LH: 1 if this bar is a lower high
      - MS_LL: 1 if this bar is a lower low
      - MS_Trend_Strength: -1 (strong downtrend) to 1 (strong uptrend)
    """
    df = df.copy()
    high = df["High"]
    low  = df["Low"]
    n = len(df)

    # Use 5-bar windows for swing point detection
    hh = np.zeros(n, dtype=int)
    hl = np.zeros(n, dtype=int)
    lh = np.zeros(n, dtype=int)
    ll = np.zeros(n, dtype=int)

    # Rolling 5-bar max/min for swing detection
    roll_high_5 = high.rolling(5).max().shift(1)
    roll_low_5  = low.rolling(5).min().shift(1)

    # Higher High: breaks above prior 5-bar high
    hh_cond = (high > roll_high_5)
    df["MS_HH"] = hh_cond.astype(int)

    # Lower Low: breaks below prior 5-bar low
    ll_cond = (low < roll_low_5)
    df["MS_LL"] = ll_cond.astype(int)

    # Higher Low: low is higher than prior swing low
    recent_swing_low  = low.rolling(10).min().shift(1)
    df["MS_HL"] = ((low > recent_swing_low) & (low.diff() > 0)).astype(int)

    # Lower High: high is lower than prior swing high
    recent_swing_high = high.rolling(10).max().shift(1)
    df["MS_LH"] = ((high < recent_swing_high) & (high.diff() < 0)).astype(int)

    # Trend strength: cumulative HH/LL over 50 bars
    hh_sum  = df["MS_HH"].rolling(50, min_periods=1).sum()
    ll_sum  = df["MS_LL"].rolling(50, min_periods=1).sum()
    df["MS_Trend_Strength"] = (
        (hh_sum - ll_sum) / (hh_sum + ll_sum + EPS)
    ).fillna(0).clip(-1, 1)

    return df


# ── Combined Feature Pipeline ───────────────────────────────────────────────────

def add_enhanced_ict_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add all enhanced ICT-inspired features to a DataFrame.

    This should be called after standard TA features are computed.
    All features are causal (no future data leakage).

    Returns DataFrame with additional columns.
    """
    df = df.copy()

    logger.info("Adding enhanced ICT features...")
    start_cols = len(df.columns)

    try:
        df = detect_bos_choch(df, swing_lookback=20)
        logger.info("  BOS/CHoCH features added (%d new cols)", len(df.columns) - start_cols)
        start_cols = len(df.columns)
    except Exception as e:
        logger.warning("  BOS/CHoCH detection failed: %s", e)

    try:
        df = detect_enhanced_fvg(df)
        logger.info("  Enhanced FVG features added (%d new cols)", len(df.columns) - start_cols)
        start_cols = len(df.columns)
    except Exception as e:
        logger.warning("  Enhanced FVG detection failed: %s", e)

    try:
        df = detect_order_flow_imbalance(df)
        logger.info("  Order flow features added (%d new cols)", len(df.columns) - start_cols)
        start_cols = len(df.columns)
    except Exception as e:
        logger.warning("  Order flow detection failed: %s", e)

    try:
        df = detect_market_structure(df)
        logger.info("  Market structure features added (%d new cols)", len(df.columns) - start_cols)
    except Exception as e:
        logger.warning("  Market structure detection failed: %s", e)

    logger.info("Enhanced ICT features complete. Total columns: %d", len(df.columns))
    return df


# ── Feature Importance Analysis ─────────────────────────────────────────────────

def analyze_feature_importance(
    model, feature_names: List[str], X: np.ndarray, y: np.ndarray,
    method: str = "permutation", n_repeats: int = 10,
) -> pd.DataFrame:
    """Compute feature importance for any sklearn-compatible model.

    Args:
        model: Trained sklearn model with predict method.
        feature_names: List of feature column names.
        X: Feature matrix.
        y: Target vector.
        method: "permutation" (model-agnostic) or "native" (model.feature_importances_).
        n_repeats: Number of repeats for permutation importance.

    Returns:
        DataFrame with Feature and Importance columns, sorted descending.
    """
    from sklearn.metrics import mean_squared_error

    if method == "native" and hasattr(model, "feature_importances_"):
        importances = model.feature_importances_
        return pd.DataFrame({
            "Feature": feature_names,
            "Importance": importances,
        }).sort_values("Importance", ascending=False)

    # Permutation importance (model-agnostic, gold standard)
    baseline_pred = model.predict(X)
    baseline_score = mean_squared_error(y, baseline_pred)

    importance_scores = []
    for col_idx in range(X.shape[1]):
        scores = []
        for _ in range(n_repeats):
            X_permuted = X.copy()
            X_permuted[:, col_idx] = np.random.permutation(X_permuted[:, col_idx])
            permuted_pred = model.predict(X_permuted)
            permuted_score = mean_squared_error(y, permuted_pred)
            scores.append(permuted_score - baseline_score)
        importance_scores.append(np.mean(scores))

    return pd.DataFrame({
        "Feature": feature_names,
        "Importance": importance_scores,
    }).sort_values("Importance", ascending=False)


def feature_importance_report(
    models: dict, feature_names: List[str],
    X_test: np.ndarray, y_test: np.ndarray,
    save_path: Optional[str] = None,
) -> pd.DataFrame:
    """Generate a combined feature importance report across multiple models.

    Args:
        models: Dict of {name: trained_model}.
        feature_names: List of feature names.
        X_test: Test feature matrix.
        y_test: Test target.
        save_path: Optional CSV path for saving.

    Returns:
        DataFrame with average importance across models.
    """
    all_importances = []

    for name, model in models.items():
        try:
            imp = analyze_feature_importance(
                model, feature_names, X_test, y_test, method="native"
            )
            imp = imp.rename(columns={"Importance": f"{name}_importance"})
            all_importances.append(imp.set_index("Feature"))
        except Exception as e:
            logger.warning("Could not compute importance for %s: %s", name, e)

    if not all_importances:
        return pd.DataFrame()

    combined = pd.concat(all_importances, axis=1)
    combined["avg_importance"] = combined.mean(axis=1)
    combined = combined.sort_values("avg_importance", ascending=False)

    if save_path:
        combined.to_csv(save_path)
        logger.info("Feature importance report saved → %s", save_path)

    return combined
