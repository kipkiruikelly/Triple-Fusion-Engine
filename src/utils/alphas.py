"""alphas.py, WorldQuant-style alpha library and validation utilities.

Each alpha is a pure function: pd.DataFrame (OHLCV) -> pd.Series of scores,
one score per bar, where positive = bullish and negative = bearish, roughly
standardized so magnitudes are comparable across alphas.

Causality contract (non-negotiable): the score at time t may use only data
available at or before t. No alpha may call shift() with a negative
argument or otherwise peek forward. tests/test_alphas.py asserts this for
every registered alpha by recomputing on truncated history.

Validation utilities at the bottom implement:
  - information_coefficient: Spearman corr of signal vs next-period return
  - walk_forward_ic: out-of-sample IC per fold, no training on test data
  - ic_weights: turn walk-forward ICs into composite weights
  - purged_train_test_splits: purged + embargoed splits for ML retraining
"""

import numpy as np
import pandas as pd

EPS = 1e-12


def _z(series: pd.Series, window: int) -> pd.Series:
    """Rolling z-score using only trailing data."""
    mean = series.rolling(window, min_periods=max(3, window // 2)).mean()
    std = series.rolling(window, min_periods=max(3, window // 2)).std()
    return (series - mean) / (std + EPS)


def _clip(series: pd.Series, lo: float = -3.0, hi: float = 3.0) -> pd.Series:
    return series.clip(lo, hi)


# ── Momentum ──────────────────────────────────────────────────────────────────

def alpha_mom_5(df: pd.DataFrame) -> pd.Series:
    """Hypothesis: short-term (1 week) winners keep drifting in the same
    direction for the next day. Score = 5-day return, z-scored over 60d."""
    ret = df["Close"].pct_change(5)
    return _clip(_z(ret, 60))


def alpha_mom_10(df: pd.DataFrame) -> pd.Series:
    """Hypothesis: 2-week momentum persists. Score = 10-day return,
    z-scored over 60d."""
    ret = df["Close"].pct_change(10)
    return _clip(_z(ret, 60))


def alpha_mom_20(df: pd.DataFrame) -> pd.Series:
    """Hypothesis: 1-month momentum persists (classic time-series momentum).
    Score = 20-day return, z-scored over 120d."""
    ret = df["Close"].pct_change(20)
    return _clip(_z(ret, 120))


def alpha_macd(df: pd.DataFrame) -> pd.Series:
    """Hypothesis: when the MACD histogram is rising and positive, trend
    continuation is more likely. Score = MACD histogram normalized by
    price so it is comparable across tickers."""
    close = df["Close"]
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    hist = (macd - signal) / (close + EPS) * 100
    return _clip(_z(hist, 60))


# ── Mean reversion ────────────────────────────────────────────────────────────

def alpha_zscore_20(df: pd.DataFrame) -> pd.Series:
    """Hypothesis: price stretched far from its 20-day mean snaps back.
    Score = negative z-score of price vs 20-day mean (below mean = buy)."""
    return _clip(-_z(df["Close"], 20))


def alpha_rsi_extreme(df: pd.DataFrame) -> pd.Series:
    """Hypothesis: RSI(14) below 30 marks capitulation (buy) and above 70
    marks euphoria (sell); in between carries little information.
    Score = scaled distance from RSI 50, zeroed in the 40..60 dead zone."""
    close = df["Close"]
    delta = close.diff()
    up = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    dn = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rsi = 100 - 100 / (1 + up / (dn + EPS))
    score = (50 - rsi) / 20.0                      # rsi 30 -> +1, rsi 70 -> -1
    score = score.where(score.abs() >= 0.5, 0.0)   # dead zone 40..60
    return _clip(score)


def alpha_bb_position(df: pd.DataFrame) -> pd.Series:
    """Hypothesis: closes hugging the lower Bollinger band revert up, and
    closes hugging the upper band revert down. Score = -(position within
    the bands mapped to -1..+1)."""
    close = df["Close"]
    mid = close.rolling(20, min_periods=10).mean()
    sd = close.rolling(20, min_periods=10).std()
    pos = (close - mid) / (2 * sd + EPS)           # -1 at lower band, +1 at upper
    return _clip(-pos, -1.5, 1.5)


# ── Volatility ────────────────────────────────────────────────────────────────

def alpha_vol_ratio(df: pd.DataFrame) -> pd.Series:
    """Hypothesis: when short-term realized volatility runs hot vs its
    long-term level, forward returns are poorer (risk-off); calm regimes
    favor longs. Score = -(vol_10 / vol_60 - 1), clipped."""
    ret = df["Close"].pct_change()
    vol_s = ret.rolling(10, min_periods=5).std()
    vol_l = ret.rolling(60, min_periods=30).std()
    return _clip(-(vol_s / (vol_l + EPS) - 1.0), -2.0, 2.0)


def alpha_vol_adj_mom(df: pd.DataFrame) -> pd.Series:
    """Hypothesis: momentum earned per unit of risk is more persistent than
    raw momentum. Score = 20-day return divided by 20-day realized vol
    (a rolling Sharpe-like ratio), z-scored."""
    ret = df["Close"].pct_change()
    mom = df["Close"].pct_change(20)
    vol = ret.rolling(20, min_periods=10).std() * np.sqrt(20)
    return _clip(_z(mom / (vol + EPS), 120))


# ── Volume / liquidity ────────────────────────────────────────────────────────

def alpha_volume_z(df: pd.DataFrame) -> pd.Series:
    """Hypothesis: unusually high volume confirms the day's move; volume
    spikes on up days are bullish and on down days bearish.
    Score = volume z-score signed by the day's return direction."""
    if "Volume" not in df.columns or df["Volume"].fillna(0).sum() == 0:
        return pd.Series(0.0, index=df.index)
    vz = _z(df["Volume"].astype(float), 20).clip(-3, 3)
    sign = np.sign(df["Close"].pct_change().fillna(0))
    return _clip(vz.clip(lower=0) * sign)


def alpha_obv_trend(df: pd.DataFrame) -> pd.Series:
    """Hypothesis: on-balance volume trending above its own 20-day mean
    means accumulation (bullish); below means distribution.
    Score = z-score of (OBV - OBV 20-day mean)."""
    if "Volume" not in df.columns or df["Volume"].fillna(0).sum() == 0:
        return pd.Series(0.0, index=df.index)
    sign = np.sign(df["Close"].diff().fillna(0))
    obv = (sign * df["Volume"].fillna(0)).cumsum()
    return _clip(_z(obv - obv.rolling(20, min_periods=10).mean(), 60))


# ── Registry ──────────────────────────────────────────────────────────────────

ALPHA_REGISTRY = {
    "mom_5":       alpha_mom_5,
    "mom_10":      alpha_mom_10,
    "mom_20":      alpha_mom_20,
    "macd":        alpha_macd,
    "zscore_20":   alpha_zscore_20,
    "rsi_extreme": alpha_rsi_extreme,
    "bb_position": alpha_bb_position,
    "vol_ratio":   alpha_vol_ratio,
    "vol_adj_mom": alpha_vol_adj_mom,
    "volume_z":    alpha_volume_z,
    "obv_trend":   alpha_obv_trend,
}


def compute_alphas(df: pd.DataFrame) -> pd.DataFrame:
    """All registered alphas for one ticker. Returns a DataFrame with one
    column per alpha, aligned to df.index. NaN rows (warmup) are kept so
    the caller can see exactly what is unavailable."""
    out = pd.DataFrame(index=df.index)
    for name, fn in ALPHA_REGISTRY.items():
        out[name] = fn(df)
    return out


def composite_score(alpha_row, weights=None) -> float:
    """Weighted average of one bar's alpha values (dict or Series).
    Missing/NaN alphas are excluded and the weights renormalized, so a
    single broken input cannot silently drag the composite to zero."""
    if weights is None:
        weights = {k: 1.0 for k in ALPHA_REGISTRY}
    num = den = 0.0
    for name, w in weights.items():
        v = alpha_row.get(name)
        if v is None or (isinstance(v, float) and np.isnan(v)) or w <= 0:
            continue
        num += w * float(v)
        den += w
    return num / den if den > 0 else 0.0


def cross_sectional_rank(scores: dict) -> dict:
    """The core WorldQuant idea: what matters is not a ticker's absolute
    score but its rank against peers. Maps {ticker: score} to
    {ticker: rank} scaled to -1..+1 (top rank = +1). Requires at least 3
    names to be meaningful; fewer than that returns zeros."""
    valid = {t: s for t, s in scores.items() if s is not None and not np.isnan(s)}
    n = len(valid)
    if n < 3:
        return {t: 0.0 for t in scores}
    order = sorted(valid, key=lambda t: valid[t])
    out = {t: 0.0 for t in scores}
    for i, t in enumerate(order):
        out[t] = 2.0 * i / (n - 1) - 1.0
    return out


def pyth_confidence_multiplier(conf_pct, wide_pct: float = 0.30) -> float:
    """Downweight signals when the Pyth oracle confidence interval is
    unusually wide (uncertain market). conf_pct is the confidence interval
    as a percent of price. Returns a multiplier in 0..1:
      <= wide_pct        -> 1.0 (normal market)
      2x wide_pct        -> 0.5
      >= 4x wide_pct     -> 0.0 (stand aside)
    Unknown confidence (None) returns 1.0 so equities without Pyth
    coverage are not penalized."""
    if conf_pct is None:
        return 1.0
    c = float(conf_pct)
    if c <= wide_pct:
        return 1.0
    if c >= 4 * wide_pct:
        return 0.0
    return max(0.0, 1.0 - (c - wide_pct) / (3 * wide_pct))


# ── ML feature integration ────────────────────────────────────────────────────

def add_alpha_features(df: pd.DataFrame) -> pd.DataFrame:
    """Append alpha columns (prefixed Alpha_) plus the equal-weight
    composite as ML features. Purely causal, safe to call in both training
    and inference pipelines. Failure of any single alpha never breaks the
    caller; that column is simply skipped."""
    for name, fn in ALPHA_REGISTRY.items():
        try:
            df[f"Alpha_{name}"] = fn(df).fillna(0.0)
        except Exception:
            continue
    alpha_cols = [c for c in df.columns if c.startswith("Alpha_")]
    if alpha_cols:
        df["Alpha_composite"] = df[alpha_cols].mean(axis=1)
    return df


# ── Validation: IC, walk-forward, purged splits ───────────────────────────────

def forward_returns(df: pd.DataFrame, horizon: int = 1) -> pd.Series:
    """Return over the NEXT `horizon` bars, aligned to signal time t.
    This intentionally looks forward: it is the evaluation target, never a
    feature. fr[t] = close[t+horizon] / close[t] - 1."""
    return df["Close"].shift(-horizon) / df["Close"] - 1.0


def information_coefficient(signal: pd.Series, fwd_ret: pd.Series) -> float:
    """Spearman rank correlation between the signal at t and the realized
    next-period return. The honest, standard measure of alpha strength.
    Returns np.nan when there are fewer than 20 overlapping observations."""
    joined = pd.concat([signal, fwd_ret], axis=1, keys=["s", "r"]).dropna()
    if len(joined) < 20:
        return float("nan")
    return float(joined["s"].rank().corr(joined["r"].rank()))


def walk_forward_ic(df: pd.DataFrame, alpha_fn, train_bars: int = 252,
                    test_bars: int = 63, horizon: int = 1) -> list:
    """Out-of-sample IC per walk-forward fold.

    The alpha is computed on data up to the end of each test window using
    only trailing history (alphas are causal by contract), and the IC is
    measured strictly on the test window. Nothing is fit on test data.
    Returns a list of {start, end, ic, n} dicts."""
    folds = []
    n = len(df)
    start = train_bars
    while start + test_bars <= n:
        window = df.iloc[:start + test_bars]
        sig = alpha_fn(window)
        fr = forward_returns(window, horizon)
        test_sig = sig.iloc[start:start + test_bars]
        test_ret = fr.iloc[start:start + test_bars]
        ic = information_coefficient(test_sig, test_ret)
        folds.append({
            "start": str(window.index[start].date()) if hasattr(window.index[start], "date") else start,
            "end": str(window.index[-1].date()) if hasattr(window.index[-1], "date") else start + test_bars,
            "ic": None if np.isnan(ic) else round(ic, 4),
            "n": int(test_sig.notna().sum()),
        })
        start += test_bars
    return folds


def ic_weights(mean_ics: dict, floor: float = 0.0) -> dict:
    """Turn per-alpha mean walk-forward ICs into composite weights.
    Negative or unknown ICs get weight `floor` (default 0: a demonstrably
    unhelpful alpha is removed, not negated, to avoid overfitting sign
    flips). If everything is floored, fall back to equal weights."""
    w = {}
    for name in ALPHA_REGISTRY:
        ic = mean_ics.get(name)
        if ic is None or (isinstance(ic, float) and np.isnan(ic)) or ic <= 0:
            w[name] = floor
        else:
            w[name] = float(ic)
    if sum(w.values()) <= 0:
        return {k: 1.0 for k in ALPHA_REGISTRY}
    return w


def purged_train_test_splits(n: int, n_splits: int = 5, purge: int = 5,
                             embargo: int = 5):
    """K-fold splits for financial ML where overlapping label windows leak.

    Each fold's test block is contiguous. Training indices within `purge`
    bars before the test block are dropped (their forward-looking labels
    overlap the test period), and `embargo` bars after the test block are
    also dropped (test outcomes leak into subsequent features).
    Yields (train_idx, test_idx) as numpy arrays."""
    fold = n // n_splits
    for k in range(n_splits):
        t0 = k * fold
        t1 = n if k == n_splits - 1 else (k + 1) * fold
        test = np.arange(t0, t1)
        before = np.arange(0, max(0, t0 - purge))
        after = np.arange(min(n, t1 + embargo), n)
        train = np.concatenate([before, after])
        yield train, test
