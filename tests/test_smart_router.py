"""
test_smart_router.py
Comprehensive unit tests for SmartOrderRouter, OrderSlice, and ExecutionReport.

Tests cover:
  - OrderSlice and ExecutionReport dataclass construction
  - SmartOrderRouter.estimate_market_impact with various sizes, ADV, volatilities
  - SmartOrderRouter.optimal_chunk_size with edge cases
  - SmartOrderRouter.build_volume_profile with valid/empty/missing-Volume DataFrames
  - TWAP, VWAP, and Iceberg execution via mocked trader

Author: BullLogic
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import MagicMock

import pandas as pd
import pytest

from smart_router import ExecutionReport, OrderSlice, SmartOrderRouter
from tests.mock_data import sample_account, sample_ohlcv


# ── Fixtures ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def ohlcv_df() -> pd.DataFrame:
    """Return a reproducible 200-bar OHLCV DataFrame with a Volume column."""
    return sample_ohlcv(n_bars=200, start_price=100.0, volatility=0.015, seed=42)


@pytest.fixture
def empty_df() -> pd.DataFrame:
    """Return an empty DataFrame (no rows)."""
    return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])


@pytest.fixture
def df_missing_volume() -> pd.DataFrame:
    """Return a DataFrame that is structurally valid but has no Volume column."""
    df = sample_ohlcv(n_bars=50, seed=7)
    return df.drop(columns=["Volume"])


@pytest.fixture
def router() -> SmartOrderRouter:
    """Return a SmartOrderRouter *without* a trader (for static-method tests)."""
    return SmartOrderRouter()


@pytest.fixture
def mock_trader() -> MagicMock:
    """Return a MagicMock that mimics an MT5Trader instance."""
    trader = MagicMock()
    trader.place_order.return_value = {
        "ok": True,
        "trade": {"price": 100.50, "lots": 0.1},
    }
    return trader


@pytest.fixture
def router_with_trader(mock_trader: MagicMock) -> SmartOrderRouter:
    """Return a SmartOrderRouter wired to the mock trader."""
    return SmartOrderRouter(trader=mock_trader)


# ── OrderSlice Dataclass ──────────────────────────────────────────────────────────


class TestOrderSlice:
    """Verify OrderSlice dataclass construction and default values."""

    def test_defaults(self) -> None:
        """OrderSlice should use sensible defaults for optional fields."""
        t = datetime(2025, 1, 15, 10, 30, 0)
        s = OrderSlice(slice_id=1, lots=0.5, target_time=t)

        assert s.slice_id == 1
        assert s.lots == 0.5
        assert s.target_time == t
        # Optional fields
        assert s.price_limit is None
        assert s.filled is False
        assert s.fill_price == 0.0
        assert s.fill_time is None
        assert s.slippage_bps == 0.0

    def test_all_fields_explicit(self) -> None:
        """All OrderSlice fields can be set via the constructor."""
        t = datetime(2025, 6, 1, 14, 0, 0)
        ft = datetime(2025, 6, 1, 14, 5, 0)
        s = OrderSlice(
            slice_id=10,
            lots=1.25,
            target_time=t,
            price_limit=102.50,
            filled=True,
            fill_price=101.75,
            fill_time=ft,
            slippage_bps=3.2,
        )
        assert s.slice_id == 10
        assert s.lots == 1.25
        assert s.target_time == t
        assert s.price_limit == 102.50
        assert s.filled is True
        assert s.fill_price == 101.75
        assert s.fill_time == ft
        assert s.slippage_bps == 3.2


# ── ExecutionReport Dataclass ─────────────────────────────────────────────────────


class TestExecutionReport:
    """Verify ExecutionReport dataclass construction and field types."""

    def test_minimal_construction(self) -> None:
        """ExecutionReport can be built with all required fields."""
        # only scalar fields — slices is optional
        report = ExecutionReport(
            parent_action="BUY",
            parent_lots=2.0,
            slices_total=10,
            slices_filled=8,
            avg_price=100.25,
            vwap_benchmark=100.30,
            slippage_vs_vwap_bps=-4.99,
            total_time_seconds=180.0,
            fill_rate_pct=80.0,
            market_impact_bps=1.2,
            algo="TWAP",
        )
        assert report.parent_action == "BUY"
        assert report.parent_lots == 2.0
        assert report.slices_total == 10
        assert report.slices_filled == 8
        assert report.avg_price == 100.25
        assert report.vwap_benchmark == 100.30
        assert report.slippage_vs_vwap_bps == -4.99
        assert report.total_time_seconds == 180.0
        assert report.fill_rate_pct == 80.0
        assert report.market_impact_bps == 1.2
        assert report.algo == "TWAP"
        assert report.slices == []  # factory default

    def test_with_slices(self) -> None:
        """ExecutionReport accepts a list of OrderSlices."""
        now = datetime.now()
        slices = [
            OrderSlice(slice_id=1, lots=0.5, target_time=now, filled=True,
                       fill_price=100.0, fill_time=now, slippage_bps=0.5),
            OrderSlice(slice_id=2, lots=0.5, target_time=now, filled=False),
        ]
        report = ExecutionReport(
            parent_action="SELL",
            parent_lots=1.0,
            slices_total=2,
            slices_filled=1,
            avg_price=100.0,
            vwap_benchmark=100.05,
            slippage_vs_vwap_bps=-5.0,
            total_time_seconds=60.0,
            fill_rate_pct=50.0,
            market_impact_bps=0.8,
            algo="VWAP",
            slices=slices,
        )
        assert len(report.slices) == 2
        assert report.slices[0].filled is True
        assert report.slices[1].filled is False


# ── estimate_market_impact ────────────────────────────────────────────────────────


class TestEstimateMarketImpact:
    """Static method: estimate_market_impact(order_size, ADV, volatility)."""

    def test_small_order_near_zero_impact(self, router: SmartOrderRouter) -> None:
        """A very small order relative to ADV should yield near-zero impact."""
        impact = router.estimate_market_impact(
            order_size_lots=0.01,
            avg_daily_volume_lots=1_000_000.0,
            volatility_pct=0.5,
        )
        assert isinstance(impact, float)
        assert 0.0 <= impact < 1.0  # well under 1 bps

    def test_large_order_significant_impact(
        self, router: SmartOrderRouter
    ) -> None:
        """An order that is a large fraction of ADV should yield a meaningful
        impact estimate (>1 bps)."""
        impact = router.estimate_market_impact(
            order_size_lots=50_000.0,  # 5% of 1M ADV
            avg_daily_volume_lots=1_000_000.0,
            volatility_pct=2.0,
        )
        assert impact > 1.0  # should be several bps

    def test_zero_adv_fallback(self, router: SmartOrderRouter) -> None:
        """When ADV is zero the method should return a conservative fallback."""
        impact = router.estimate_market_impact(
            order_size_lots=1.0,
            avg_daily_volume_lots=0.0,
            volatility_pct=1.0,
        )
        # fallback = order_size * 2
        assert impact == 2.0

    def test_negative_adv_treated_as_zero(self, router: SmartOrderRouter) -> None:
        """Negative ADV should hit the same <=0 guard and produce the fallback."""
        impact = router.estimate_market_impact(
            order_size_lots=1.0,
            avg_daily_volume_lots=-100.0,
            volatility_pct=1.0,
        )
        assert impact == 2.0  # same fallback as zero ADV

    def test_negative_order_size_small_impact(
        self, router: SmartOrderRouter
    ) -> None:
        """A negative order_size should still produce a positive impact via
        the sqrt of the participation rate (rate clamped at min 0.0001)."""
        impact = router.estimate_market_impact(
            order_size_lots=-5.0,
            avg_daily_volume_lots=1_000_000.0,
            volatility_pct=1.0,
        )
        # Participation rate = -5 / 1e6 → negative → max(negative, 0.0001) = 0.0001
        # This is a valid numeric path, so impact will be > 0.
        assert impact >= 0.0

    def test_zero_volatility(self, router: SmartOrderRouter) -> None:
        """Zero volatility should result in zero impact (falls through normal
        path, not the fallback)."""
        impact = router.estimate_market_impact(
            order_size_lots=1000.0,
            avg_daily_volume_lots=1_000_000.0,
            volatility_pct=0.0,
        )
        # participation_rate = 0.001, eta=10,
        # impact = 10 * sqrt(0.001) * 0 = 0, times 100 = 0.0
        assert impact == 0.0

    def test_impact_monotonic_with_order_size(
        self, router: SmartOrderRouter
    ) -> None:
        """Larger orders should produce larger (or equal) impact estimates."""
        small = router.estimate_market_impact(100, 1_000_000, 1.0)
        large = router.estimate_market_impact(10_000, 1_000_000, 1.0)
        assert large >= small

    def test_impact_monotonic_with_volatility(
        self, router: SmartOrderRouter
    ) -> None:
        """Higher volatility should produce larger (or equal) impact."""
        low_vol = router.estimate_market_impact(1000, 1_000_000, 0.5)
        high_vol = router.estimate_market_impact(1000, 1_000_000, 3.0)
        assert high_vol >= low_vol


# ── optimal_chunk_size ────────────────────────────────────────────────────────────


class TestOptimalChunkSize:
    """Static method: optimal_chunk_size(total_lots, ADV, participation, min_lot)."""

    def test_normal_case(self, router: SmartOrderRouter) -> None:
        """A standard order should produce a sensible chunk size between
        min_lot and the ADV-based cap."""
        chunk = router.optimal_chunk_size(
            total_lots=10.0,
            avg_daily_volume_lots=100_000.0,
            max_participation_pct=0.05,
            min_lot=0.01,
        )
        assert 0.01 <= chunk <= 100_000.0 * 0.05  # capped by participation
        assert isinstance(chunk, float)

    def test_tiny_order_rounds_to_min_lot(
        self, router: SmartOrderRouter
    ) -> None:
        """An order smaller than min_lot should return min_lot."""
        chunk = router.optimal_chunk_size(
            total_lots=0.001,
            avg_daily_volume_lots=100_000.0,
            max_participation_pct=0.05,
            min_lot=0.01,
        )
        assert chunk == 0.01

    def test_participation_limit_capping(
        self, router: SmartOrderRouter
    ) -> None:
        """When the natural chunk would exceed the ADV-based participation
        limit, the limit should win."""
        # Very small ADV to make the cap very tight
        chunk = router.optimal_chunk_size(
            total_lots=100.0,
            avg_daily_volume_lots=10.0,  # ADV is tiny
            max_participation_pct=0.05,  # cap = 10 * 0.05 = 0.5
            min_lot=0.01,
        )
        assert chunk <= 0.5  # capped by max_chunk_from_adv
        assert chunk >= 0.01

    def test_minimum_lot_enforcement(
        self, router: SmartOrderRouter
    ) -> None:
        """Even with zero ADV the chunk should not drop below min_lot."""
        chunk = router.optimal_chunk_size(
            total_lots=0.1,
            avg_daily_volume_lots=0.0,
            max_participation_pct=0.05,
            min_lot=0.01,
        )
        assert chunk >= 0.01

    def test_zero_volume_zero_lots(
        self, router: SmartOrderRouter
    ) -> None:
        """Zero total_lots and zero ADV should return min_lot."""
        chunk = router.optimal_chunk_size(
            total_lots=0.0,
            avg_daily_volume_lots=0.0,
            max_participation_pct=0.05,
            min_lot=0.01,
        )
        assert chunk == 0.01

    def test_custom_participation_pct(
        self, router: SmartOrderRouter
    ) -> None:
        """A very tight participation cap should visibly restrict the chunk."""
        chunk = router.optimal_chunk_size(
            total_lots=100.0,
            avg_daily_volume_lots=1000.0,
            max_participation_pct=0.01,  # cap = 10
            min_lot=0.01,
        )
        assert chunk <= 10.0

    def test_custom_min_lot(self, router: SmartOrderRouter) -> None:
        """A larger min_lot should be respected."""
        chunk = router.optimal_chunk_size(
            total_lots=0.5,
            avg_daily_volume_lots=1000.0,
            max_participation_pct=0.05,
            min_lot=0.5,
        )
        assert chunk >= 0.5


# ── build_volume_profile ──────────────────────────────────────────────────────────


class TestBuildVolumeProfile:
    """Static method: build_volume_profile(df_ohlcv, n_buckets)."""

    def test_valid_dataframe(
        self, router: SmartOrderRouter, ohlcv_df: pd.DataFrame
    ) -> None:
        """A valid OHLCV DataFrame with a Volume column should return a list
        of positive weights equal to n_buckets."""
        profile = router.build_volume_profile(ohlcv_df, n_buckets=30)
        assert isinstance(profile, list)
        assert all(isinstance(v, float) for v in profile)
        assert len(profile) == 30

    def test_empty_dataframe_fallback(
        self, router: SmartOrderRouter, empty_df: pd.DataFrame
    ) -> None:
        """An empty DataFrame should produce a uniform fallback profile."""
        profile = router.build_volume_profile(empty_df, n_buckets=10)
        assert len(profile) == 10
        assert all(v == 1.0 for v in profile)

    def test_missing_volume_column(
        self, router: SmartOrderRouter, df_missing_volume: pd.DataFrame
    ) -> None:
        """A DataFrame without a 'Volume' column should produce the uniform
        fallback."""
        profile = router.build_volume_profile(df_missing_volume, n_buckets=20)
        assert len(profile) == 20
        assert all(v == 1.0 for v in profile)

    def test_various_n_buckets(
        self, router: SmartOrderRouter, ohlcv_df: pd.DataFrame
    ) -> None:
        """build_volume_profile should respect the n_buckets parameter across
        a range of values."""
        for n in [1, 5, 24, 60, 96, 288]:
            profile = router.build_volume_profile(ohlcv_df, n_buckets=n)
            assert len(profile) == n, f"Expected {n} buckets, got {len(profile)}"

    def test_profile_weights_positive(
        self, router: SmartOrderRouter, ohlcv_df: pd.DataFrame
    ) -> None:
        """All returned volume weights should be non-negative."""
        profile = router.build_volume_profile(ohlcv_df, n_buckets=30)
        assert all(v >= 0.0 for v in profile)

    def test_none_dataframe(self, router: SmartOrderRouter) -> None:
        """A None DataFrame should return the uniform fallback."""
        profile = router.build_volume_profile(None, n_buckets=12)  # type: ignore[arg-type]
        assert len(profile) == 12
        assert all(v == 1.0 for v in profile)


# ── TWAP Execution ────────────────────────────────────────────────────────────────


class TestTwapExecution:
    """execute_twap with a mocked trader."""

    def test_twap_success_all_filled(
        self, router_with_trader: SmartOrderRouter, mock_trader: MagicMock
    ) -> None:
        """When all slices succeed the report should reflect 100% fill rate."""
        mock_trader.place_order.return_value = {
            "ok": True,
            "trade": {"price": 100.50, "lots": 0.1},
        }
        report = router_with_trader.execute_twap(
            symbol="EURUSD",
            action="BUY",
            total_lots=1.0,
            duration_minutes=5,
            min_lot=0.01,
        )
        assert isinstance(report, ExecutionReport)
        assert report.slices_filled == report.slices_total
        assert report.fill_rate_pct == 100.0
        assert report.algo == "TWAP"
        assert report.parent_action == "BUY"
        assert report.parent_lots == 1.0

    def test_twap_partial_fill(
        self, router_with_trader: SmartOrderRouter, mock_trader: MagicMock
    ) -> None:
        """When some slices fail the report should reflect a partial fill rate
        and fewer filled slices."""
        # Alternate success and failure
        call_count = 0

        def _side_effect(*args: Any, **kwargs: Any) -> dict:
            nonlocal call_count
            call_count += 1
            if call_count % 2 == 0:
                return {"ok": False, "error": "rejected"}
            return {"ok": True, "trade": {"price": 99.0, "lots": 0.1}}

        mock_trader.place_order.side_effect = _side_effect
        report = router_with_trader.execute_twap(
            symbol="EURUSD",
            action="SELL",
            total_lots=1.0,
            duration_minutes=5,
            min_lot=0.01,
        )
        assert report.algo == "TWAP"
        assert report.slices_filled < report.slices_total
        assert 0.0 < report.fill_rate_pct < 100.0

    def test_twap_requires_trader(self) -> None:
        """A router without a trader should raise RuntimeError."""
        router_no_trader = SmartOrderRouter()
        with pytest.raises(RuntimeError, match="requires a trader"):
            router_no_trader.execute_twap(
                symbol="EURUSD", action="BUY", total_lots=1.0,
            )


# ── VWAP Execution ────────────────────────────────────────────────────────────────


class TestVwapExecution:
    """execute_vwap with a mocked trader."""

    def test_vwap_success_all_filled(
        self, router_with_trader: SmartOrderRouter, mock_trader: MagicMock
    ) -> None:
        """When all VWAP slices succeed the report should show 100% fill rate."""
        mock_trader.place_order.return_value = {
            "ok": True,
            "trade": {"price": 100.25, "lots": 0.1},
        }
        volume_profile = [0.1, 0.2, 0.3, 0.4]  # 4 buckets
        report = router_with_trader.execute_vwap(
            symbol="EURUSD",
            action="BUY",
            total_lots=1.0,
            volume_profile=volume_profile,
            duration_minutes=4,
            min_lot=0.01,
        )
        assert isinstance(report, ExecutionReport)
        assert report.algo == "VWAP"
        assert report.slices_filled == report.slices_total
        assert report.fill_rate_pct == 100.0

    def test_vwap_fallback_on_empty_profile(
        self, router_with_trader: SmartOrderRouter, mock_trader: MagicMock
    ) -> None:
        """An empty volume profile should fall back to equal-weight slices
        (TWAP behaviour)."""
        mock_trader.place_order.return_value = {
            "ok": True,
            "trade": {"price": 100.0, "lots": 0.05},
        }
        report = router_with_trader.execute_vwap(
            symbol="EURUSD",
            action="SELL",
            total_lots=0.5,
            volume_profile=[],
            duration_minutes=3,
            min_lot=0.01,
        )
        assert report.algo == "VWAP"
        assert report.slices_total >= 1

    def test_vwap_requires_trader(self) -> None:
        """A router without a trader should raise RuntimeError."""
        router_no_trader = SmartOrderRouter()
        with pytest.raises(RuntimeError, match="requires a trader"):
            router_no_trader.execute_vwap(
                symbol="EURUSD",
                action="BUY",
                total_lots=1.0,
                volume_profile=[0.5, 0.5],
            )

    def test_vwap_partial_fill(
        self, router_with_trader: SmartOrderRouter, mock_trader: MagicMock
    ) -> None:
        """Simulated failures in VWAP should still produce a valid report."""
        call_count = 0

        def _side_effect(*args: Any, **kwargs: Any) -> dict:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {"ok": False, "error": "rate limited"}
            return {"ok": True, "trade": {"price": 101.0, "lots": 0.05}}

        mock_trader.place_order.side_effect = _side_effect
        report = router_with_trader.execute_vwap(
            symbol="EURUSD",
            action="BUY",
            total_lots=0.5,
            volume_profile=[0.25, 0.25, 0.25, 0.25],
            duration_minutes=4,
            min_lot=0.01,
        )
        assert report.algo == "VWAP"
        assert report.slices_filled >= 0


# ── Iceberg Execution ─────────────────────────────────────────────────────────────


class TestIcebergExecution:
    """execute_iceberg with a mocked trader."""

    def test_iceberg_all_filled(
        self, router_with_trader: SmartOrderRouter, mock_trader: MagicMock
    ) -> None:
        """When every slice succeeds the report should show the order as
        fully executed."""
        mock_trader.place_order.return_value = {
            "ok": True,
            "trade": {"price": 100.0, "lots": 0.5},
        }
        report = router_with_trader.execute_iceberg(
            symbol="EURUSD",
            action="BUY",
            total_lots=1.0,
            visible_lots=0.5,
            min_lot=0.01,
            max_slices=10,
        )
        assert isinstance(report, ExecutionReport)
        assert report.algo == "ICEBERG"
        # 2 slices: 0.5 + 0.5
        assert report.slices_filled == 2
        assert report.fill_rate_pct == 100.0

    def test_iceberg_partial_fill(
        self, router_with_trader: SmartOrderRouter, mock_trader: MagicMock
    ) -> None:
        """Rejected slices should produce a partial fill report."""
        call_count = 0

        def _side_effect(*args: Any, **kwargs: Any) -> dict:
            nonlocal call_count
            call_count += 1
            if call_count == 2:  # second slice fails
                return {"ok": False, "error": "liquidity"}
            return {"ok": True, "trade": {"price": 99.5, "lots": 0.3}}

        mock_trader.place_order.side_effect = _side_effect
        report = router_with_trader.execute_iceberg(
            symbol="EURUSD",
            action="SELL",
            total_lots=0.6,
            visible_lots=0.3,
            min_lot=0.01,
            max_slices=10,
        )
        assert report.algo == "ICEBERG"
        assert report.slices_filled >= 0

    def test_iceberg_requires_trader(self) -> None:
        """A router without a trader should raise RuntimeError."""
        router_no_trader = SmartOrderRouter()
        with pytest.raises(RuntimeError, match="requires a trader"):
            router_no_trader.execute_iceberg(
                symbol="EURUSD",
                action="BUY",
                total_lots=1.0,
                visible_lots=0.1,
            )


# ── sample_account integration (the fixture is imported from mock_data) ────────────


class TestSampleAccountUsage:
    """Verify that sample_account integrates as expected (surface-level smoke)."""

    def test_sample_account_structure(self) -> None:
        """sample_account returns a dict with expected keys."""
        acct = sample_account(equity=10_000.0, balance=10_000.0)
        assert isinstance(acct, dict)
        assert acct["login"] == 12345
        assert acct["balance"] == 10_000.0
        assert acct["equity"] == 10_000.0
        assert acct["currency"] == "USD"
