"""Alpha library tests: the no-lookahead assertion for every registered
alpha, information coefficient math, cross-sectional ranking, the Pyth
confidence filter, walk-forward evaluation, and purged splits."""

import numpy as np
import pandas as pd
import pytest

import alphas
from alphas import (ALPHA_REGISTRY, compute_alphas, composite_score,
                    cross_sectional_rank, pyth_confidence_multiplier,
                    information_coefficient, forward_returns,
                    walk_forward_ic, ic_weights, purged_train_test_splits,
                    add_alpha_features)


def synthetic_ohlcv(n=400, seed=7):
    """Deterministic random-walk OHLCV frame."""
    rng = np.random.default_rng(seed)
    ret = rng.normal(0.0004, 0.015, n)
    close = 100 * np.exp(np.cumsum(ret))
    high = close * (1 + np.abs(rng.normal(0, 0.006, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.006, n)))
    open_ = np.roll(close, 1) * (1 + rng.normal(0, 0.003, n))
    open_[0] = close[0]
    vol = rng.integers(1_000_000, 5_000_000, n).astype(float)
    idx = pd.bdate_range("2024-01-02", periods=n)
    return pd.DataFrame({"Open": open_, "High": high, "Low": low,
                         "Close": close, "Volume": vol}, index=idx)


# ── The no-lookahead assertion (non-negotiable) ───────────────────────────────

@pytest.mark.parametrize("name", sorted(ALPHA_REGISTRY))
def test_alpha_uses_no_future_data(name):
    """The score at time t computed on full history must equal the score
    at time t computed on history truncated at t. If an alpha peeked
    forward, truncating the future would change its value."""
    df = synthetic_ohlcv()
    fn = ALPHA_REGISTRY[name]
    full = fn(df)
    for cut in (250, 300, 399):
        trunc = fn(df.iloc[:cut + 1])
        a, b = full.iloc[cut], trunc.iloc[-1]
        if np.isnan(a) and np.isnan(b):
            continue
        assert a == pytest.approx(b, rel=1e-9, abs=1e-12), \
            f"{name} at bar {cut}: full-history {a} != truncated {b} (lookahead!)"


def test_forward_returns_is_the_evaluation_target_not_a_feature():
    df = synthetic_ohlcv(n=50)
    fr = forward_returns(df, 1)
    # fr[t] must be the NEXT bar's return
    expect = df["Close"].iloc[11] / df["Close"].iloc[10] - 1
    assert fr.iloc[10] == pytest.approx(expect)
    assert np.isnan(fr.iloc[-1])          # last bar has no future: NaN, honest


# ── Registry and composite ────────────────────────────────────────────────────

def test_compute_alphas_has_all_columns():
    adf = compute_alphas(synthetic_ohlcv())
    assert list(adf.columns) == list(ALPHA_REGISTRY.keys())


def test_composite_equal_weight_average():
    row = {name: 1.0 for name in ALPHA_REGISTRY}
    assert composite_score(row) == pytest.approx(1.0)
    row[list(ALPHA_REGISTRY)[0]] = -1.0
    n = len(ALPHA_REGISTRY)
    assert composite_score(row) == pytest.approx((n - 2) / n)


def test_composite_skips_nan_and_renormalizes():
    row = {name: np.nan for name in ALPHA_REGISTRY}
    row[list(ALPHA_REGISTRY)[0]] = 2.0
    assert composite_score(row) == pytest.approx(2.0)
    assert composite_score({n: np.nan for n in ALPHA_REGISTRY}) == 0.0


def test_cross_sectional_rank():
    r = cross_sectional_rank({"A": 0.1, "B": 0.5, "C": 0.9})
    assert r["A"] == pytest.approx(-1.0)
    assert r["B"] == pytest.approx(0.0)
    assert r["C"] == pytest.approx(1.0)
    # fewer than 3 names: no meaningful cross-section, all zero
    assert cross_sectional_rank({"A": 0.1, "B": 0.5}) == {"A": 0.0, "B": 0.0}
    # NaN scores are excluded but still present in the output
    r2 = cross_sectional_rank({"A": 0.1, "B": np.nan, "C": 0.9, "D": 0.5})
    assert r2["B"] == 0.0


def test_pyth_confidence_filter():
    assert pyth_confidence_multiplier(None) == 1.0          # no oracle: neutral
    assert pyth_confidence_multiplier(0.1, wide_pct=0.3) == 1.0
    assert pyth_confidence_multiplier(0.6, wide_pct=0.3) == pytest.approx(2 / 3)
    assert pyth_confidence_multiplier(1.2, wide_pct=0.3) == 0.0
    assert pyth_confidence_multiplier(9.9, wide_pct=0.3) == 0.0


# ── Information coefficient ───────────────────────────────────────────────────

def test_ic_perfect_and_inverted():
    idx = pd.RangeIndex(50)
    sig = pd.Series(np.arange(50, dtype=float), index=idx)
    ret = pd.Series(np.arange(50, dtype=float) ** 3, index=idx)  # monotonic
    assert information_coefficient(sig, ret) == pytest.approx(1.0)
    assert information_coefficient(sig, -ret) == pytest.approx(-1.0)


def test_ic_insufficient_observations_is_nan():
    idx = pd.RangeIndex(10)
    sig = pd.Series(np.arange(10, dtype=float), index=idx)
    assert np.isnan(information_coefficient(sig, sig))


def test_walk_forward_ic_structure():
    df = synthetic_ohlcv(n=450)
    folds = walk_forward_ic(df, ALPHA_REGISTRY["mom_20"],
                            train_bars=252, test_bars=63)
    assert len(folds) == (450 - 252) // 63
    for f in folds:
        assert set(f) == {"start", "end", "ic", "n"}
        if f["ic"] is not None:
            assert -1.0 <= f["ic"] <= 1.0


def test_ic_weights_floor_negative_alphas():
    ics = {name: -0.05 for name in ALPHA_REGISTRY}
    ics[list(ALPHA_REGISTRY)[0]] = 0.04
    ics[list(ALPHA_REGISTRY)[1]] = 0.02
    w = ic_weights(ics)
    assert w[list(ALPHA_REGISTRY)[0]] == pytest.approx(0.04)
    assert w[list(ALPHA_REGISTRY)[2]] == 0.0    # negative IC removed, not negated
    # every alpha useless: honest fallback to equal weights
    all_bad = {name: -0.1 for name in ALPHA_REGISTRY}
    assert set(ic_weights(all_bad).values()) == {1.0}


# ── Purged splits ─────────────────────────────────────────────────────────────

def test_purged_splits_no_leakage():
    n, purge, embargo = 100, 5, 5
    seen_test = []
    for train, test in purged_train_test_splits(n, n_splits=5,
                                                purge=purge, embargo=embargo):
        t0, t1 = test[0], test[-1]
        # no train index inside the purge window before the test block
        assert not any(t0 - purge <= i < t0 for i in train)
        # no train index inside the embargo window after the test block
        assert not any(t1 < i <= t1 + embargo for i in train)
        # train and test never overlap
        assert set(train).isdisjoint(set(test))
        seen_test.extend(test)
    # test blocks jointly cover every index exactly once
    assert sorted(seen_test) == list(range(n))


# ── ML feature integration ────────────────────────────────────────────────────

def test_add_alpha_features_columns_and_no_nan():
    df = add_alpha_features(synthetic_ohlcv())
    for name in ALPHA_REGISTRY:
        col = f"Alpha_{name}"
        assert col in df.columns
        assert not df[col].isna().any()
    assert "Alpha_composite" in df.columns


def test_add_alpha_features_is_causal_too():
    """The integrated feature path must obey the same causality contract."""
    df = synthetic_ohlcv()
    full = add_alpha_features(df.copy())
    cut = 300
    trunc = add_alpha_features(df.iloc[:cut + 1].copy())
    for name in ALPHA_REGISTRY:
        col = f"Alpha_{name}"
        assert full[col].iloc[cut] == pytest.approx(trunc[col].iloc[-1],
                                                    rel=1e-9, abs=1e-12), col
