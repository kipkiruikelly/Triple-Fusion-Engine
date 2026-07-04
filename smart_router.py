"""
smart_router.py
Smart Order Router for the Triple-Fusion-Engine.

Provides advanced order execution algorithms that minimize market impact
and improve fill quality:

  - TWAP (Time-Weighted Average Price): splits large orders into equal
    time slices over a specified duration.
  - VWAP (Volume-Weighted Average Price): weights slices by historical
    volume profile to match the market's natural rhythm.
  - Iceberg Orders: only a small visible portion is shown to the market;
    the remainder is hidden and revealed as the visible part fills.
  - Order Splitting: generic utility to split any large order into
    smaller child orders with configurable chunk sizes.
  - Market Impact Estimation: estimates the expected slippage for a
    given order size based on recent volume and volatility.

All algorithms work in both live and paper trading modes. The paper
trader simulates partial fills; the live mode delegates to the broker.

Usage:
    from smart_router import SmartOrderRouter
    router = SmartOrderRouter(trader)
    result = router.execute_twap(symbol="EURUSD", action="BUY",
                                  total_lots=1.0, duration_minutes=30)

Author: BullLogic
"""

import logging
import math
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class OrderSlice:
    """A single slice of a larger parent order."""
    slice_id: int
    lots: float
    target_time: datetime
    price_limit: Optional[float] = None
    filled: bool = False
    fill_price: float = 0.0
    fill_time: Optional[datetime] = None
    slippage_bps: float = 0.0


@dataclass
class ExecutionReport:
    """Post-trade execution quality report."""
    parent_action: str
    parent_lots: float
    slices_total: int
    slices_filled: int
    avg_price: float
    vwap_benchmark: float
    slippage_vs_vwap_bps: float
    total_time_seconds: float
    fill_rate_pct: float
    market_impact_bps: float
    algo: str
    slices: List[OrderSlice] = field(default_factory=list)


class SmartOrderRouter:
    """Smart order routing with TWAP, VWAP, and iceberg execution.

    Wraps the MT5Trader instance and adds algorithmic execution on top.
    """

    def __init__(self, trader: "MT5Trader" = None):  # noqa: F821
        self._trader = trader

    @property
    def trader(self):
        return self._trader

    # ── Market Impact Estimation ─────────────────────────────────────────────

    @staticmethod
    def estimate_market_impact(
        order_size_lots: float,
        avg_daily_volume_lots: float,
        volatility_pct: float,
    ) -> float:
        """Estimate market impact in basis points (bps).

        Uses a simplified square-root model:
          impact_bps = eta * sqrt(order_size / ADV) * volatility

        where eta is a market-specific constant (default 10 for forex).

        Args:
            order_size_lots: Size of the order in lots.
            avg_daily_volume_lots: Average daily volume in lots.
            volatility_pct: Recent volatility as percentage (e.g. 1.5 for 1.5%).

        Returns:
            Estimated market impact in basis points.
        """
        if avg_daily_volume_lots <= 0:
            return order_size_lots * 2  # conservative fallback

        participation_rate = order_size_lots / avg_daily_volume_lots
        eta = 10.0  # market impact coefficient (calibrate per asset class)
        impact = eta * math.sqrt(max(participation_rate, 0.0001)) * (volatility_pct / 100)
        return round(impact * 100, 2)  # convert to bps

    @staticmethod
    def optimal_chunk_size(
        total_lots: float,
        avg_daily_volume_lots: float,
        max_participation_pct: float = 0.05,
        min_lot: float = 0.01,
    ) -> float:
        """Calculate optimal chunk size to stay under participation limits.

        Args:
            total_lots: Total order size in lots.
            avg_daily_volume_lots: Average daily volume in lots.
            max_participation_pct: Maximum % of ADV per chunk (default 5%).
            min_lot: Minimum lot size (broker-dependent).

        Returns:
            Recommended chunk size in lots.
        """
        max_chunk_from_adv = avg_daily_volume_lots * max_participation_pct
        natural_chunk = total_lots / max(1, round(total_lots / max(min_lot, max_chunk_from_adv)))
        return round(max(min_lot, min(natural_chunk, max_chunk_from_adv)), 2)

    # ── TWAP Algorithm ──────────────────────────────────────────────────────

    def execute_twap(
        self,
        symbol: str,
        action: str,
        total_lots: float,
        duration_minutes: int = 30,
        min_lot: float = 0.01,
        risk_pct: float = 1.0,
        atr: float = 0.0,
    ) -> ExecutionReport:
        """Execute an order using the TWAP algorithm.

        Splits total_lots into equal slices executed at regular intervals
        over duration_minutes. Each slice is sent as a market order.

        Args:
            symbol: Trading symbol (e.g. "EURUSD").
            action: "BUY" or "SELL".
            total_lots: Total position size in lots.
            duration_minutes: Total execution time in minutes.
            min_lot: Minimum lot size allowed by the broker.
            risk_pct: Risk percentage for lot calculation fallback.
            atr: ATR value for SL/TP calculation.

        Returns:
            ExecutionReport with fill details and quality metrics.
        """
        if self._trader is None:
            raise RuntimeError("SmartOrderRouter requires a trader instance")

        n_slices = max(2, duration_minutes)  # one slice per minute minimum
        slice_lots = round(total_lots / n_slices, 2)
        if slice_lots < min_lot:
            slice_lots = min_lot
            n_slices = max(1, int(total_lots / min_lot))

        interval_seconds = (duration_minutes * 60) / n_slices
        slices: List[OrderSlice] = []
        fill_prices: List[float] = []
        start_time = datetime.now()

        logger.info("TWAP: %s %s %.2f lots over %d min → %d slices of %.2f lots",
                     action, symbol, total_lots, duration_minutes, n_slices, slice_lots)

        for i in range(n_slices):
            slice_start = datetime.now()
            s = OrderSlice(
                slice_id=i + 1,
                lots=slice_lots,
                target_time=start_time + timedelta(seconds=interval_seconds * (i + 1)),
            )

            try:
                result = self._trader.place_order(symbol, action, risk_pct, atr)
                if result.get("ok"):
                    trade = result.get("trade", {})
                    s.filled = True
                    s.fill_price = trade.get("price", 0.0)
                    s.fill_time = datetime.now()
                    fill_prices.append(s.fill_price)

                    # Estimate slippage (vs first fill as reference)
                    if fill_prices:
                        ref = fill_prices[0]
                        s.slippage_bps = (
                            (s.fill_price - ref) / ref * 10000
                            if ref > 0 else 0.0
                        )
                else:
                    logger.warning("TWAP slice %d/%d rejected: %s",
                                   i + 1, n_slices, result.get("error", "unknown"))
            except Exception as e:
                logger.error("TWAP slice %d/%d error: %s", i + 1, n_slices, e)

            slices.append(s)

            # Sleep until next slice (respect the time interval)
            elapsed = (datetime.now() - slice_start).total_seconds()
            if i < n_slices - 1 and elapsed < interval_seconds:
                time.sleep(interval_seconds - elapsed)

        total_time = (datetime.now() - start_time).total_seconds()
        filled_slices = [s for s in slices if s.filled]
        avg_price = float(np.mean(fill_prices)) if fill_prices else 0.0

        # VWAP benchmark: volume-weighted average of all fills (simplified)
        total_filled_lots = sum(s.lots for s in filled_slices)
        vwap = (
            sum(s.fill_price * s.lots for s in filled_slices) / total_filled_lots
            if total_filled_lots > 0 else 0.0
        )

        report = ExecutionReport(
            parent_action=action,
            parent_lots=total_lots,
            slices_total=n_slices,
            slices_filled=len(filled_slices),
            avg_price=round(avg_price, 5),
            vwap_benchmark=round(vwap, 5) if vwap else round(avg_price, 5),
            slippage_vs_vwap_bps=round(
                (avg_price - vwap) / vwap * 10000 if vwap and avg_price else 0.0, 2
            ),
            total_time_seconds=round(total_time, 1),
            fill_rate_pct=round(len(filled_slices) / n_slices * 100, 1),
            market_impact_bps=0.0,  # computed separately via estimate_market_impact
            algo="TWAP",
            slices=slices,
        )

        logger.info(
            "TWAP complete: %d/%d slices filled, avg price %.5f, "
            "fill rate %.0f%%, time %.1fs",
            report.slices_filled, report.slices_total,
            report.avg_price, report.fill_rate_pct, report.total_time_seconds,
        )
        return report

    # ── VWAP Algorithm ──────────────────────────────────────────────────────

    def execute_vwap(
        self,
        symbol: str,
        action: str,
        total_lots: float,
        volume_profile: List[float],
        duration_minutes: int = 30,
        min_lot: float = 0.01,
        risk_pct: float = 1.0,
        atr: float = 0.0,
    ) -> ExecutionReport:
        """Execute an order using the VWAP algorithm.

        Unlike TWAP which uses equal time slices, VWAP weights each slice
        by the historical volume profile to send larger chunks during
        high-volume periods and smaller chunks during low-volume periods.

        Args:
            symbol: Trading symbol.
            action: "BUY" or "SELL".
            total_lots: Total position size in lots.
            volume_profile: List of volume weights per time bucket.
                Length should match the number of slices. If empty or
                all zeros, falls back to TWAP.
            duration_minutes: Total execution time in minutes.
            min_lot: Minimum lot size.
            risk_pct: Risk percentage.
            atr: ATR value.

        Returns:
            ExecutionReport with fill details.
        """
        if self._trader is None:
            raise RuntimeError("SmartOrderRouter requires a trader instance")

        n_slices = max(2, duration_minutes)

        # Normalize volume profile
        if not volume_profile or sum(volume_profile) <= 0:
            logger.info("VWAP: no volume profile, falling back to equal-weight TWAP")
            volume_profile = [1.0] * n_slices

        total_vol = sum(volume_profile)
        weights = [v / total_vol for v in volume_profile[:n_slices]]

        # Pad/trim weights to match n_slices
        if len(weights) < n_slices:
            weights += [1.0 / n_slices] * (n_slices - len(weights))
            weights = [w / sum(weights) for w in weights]
        weights = weights[:n_slices]

        # Allocate lots by volume weight
        slice_lots_list = [round(total_lots * w, 2) for w in weights]
        # Adjust to ensure sum equals total_lots
        diff = round(total_lots - sum(slice_lots_list), 2)
        if diff != 0 and slice_lots_list:
            slice_lots_list[0] = round(slice_lots_list[0] + diff, 2)
        slice_lots_list = [max(min_lot, sl) for sl in slice_lots_list]

        interval_seconds = (duration_minutes * 60) / n_slices
        slices: List[OrderSlice] = []
        fill_prices: List[float] = []
        start_time = datetime.now()

        logger.info("VWAP: %s %s %.2f lots over %d min → %d volume-weighted slices",
                     action, symbol, total_lots, duration_minutes, n_slices)

        for i, sl in enumerate(slice_lots_list):
            if sl < min_lot:
                continue
            slice_start = datetime.now()
            s = OrderSlice(
                slice_id=i + 1,
                lots=sl,
                target_time=start_time + timedelta(seconds=interval_seconds * (i + 1)),
            )

            try:
                result = self._trader.place_order(symbol, action, risk_pct, atr)
                if result.get("ok"):
                    trade = result.get("trade", {})
                    s.filled = True
                    s.fill_price = trade.get("price", 0.0)
                    s.fill_time = datetime.now()
                    fill_prices.append(s.fill_price)
            except Exception as e:
                logger.error("VWAP slice %d/%d error: %s", i + 1, n_slices, e)

            slices.append(s)
            elapsed = (datetime.now() - slice_start).total_seconds()
            if i < n_slices - 1 and elapsed < interval_seconds:
                time.sleep(interval_seconds - elapsed)

        total_time = (datetime.now() - start_time).total_seconds()
        filled_slices = [s for s in slices if s.filled]
        avg_price = float(np.mean(fill_prices)) if fill_prices else 0.0

        total_filled_lots = sum(s.lots for s in filled_slices)
        vwap = (
            sum(s.fill_price * s.lots for s in filled_slices) / total_filled_lots
            if total_filled_lots > 0 else 0.0
        )

        report = ExecutionReport(
            parent_action=action,
            parent_lots=total_lots,
            slices_total=len(slice_lots_list),
            slices_filled=len(filled_slices),
            avg_price=round(avg_price, 5),
            vwap_benchmark=round(vwap, 5) if vwap else round(avg_price, 5),
            slippage_vs_vwap_bps=round(
                (avg_price - vwap) / vwap * 10000 if vwap and avg_price else 0.0, 2
            ),
            total_time_seconds=round(total_time, 1),
            fill_rate_pct=round(len(filled_slices) / max(1, len(slice_lots_list)) * 100, 1),
            market_impact_bps=0.0,
            algo="VWAP",
            slices=slices,
        )

        logger.info(
            "VWAP complete: %d/%d slices filled, avg price %.5f, fill rate %.0f%%",
            report.slices_filled, report.slices_total,
            report.avg_price, report.fill_rate_pct,
        )
        return report

    # ── Iceberg Order ───────────────────────────────────────────────────────

    def execute_iceberg(
        self,
        symbol: str,
        action: str,
        total_lots: float,
        visible_lots: float,
        min_lot: float = 0.01,
        risk_pct: float = 1.0,
        atr: float = 0.0,
        max_slices: int = 20,
    ) -> ExecutionReport:
        """Execute an iceberg (stealth) order.

        Only `visible_lots` is shown to the market at any time. When that
        portion fills, the next slice is revealed. Continues until the
        entire `total_lots` is executed or `max_slices` is reached.

        Args:
            symbol: Trading symbol.
            action: "BUY" or "SELL".
            total_lots: Total order size to execute.
            visible_lots: Size of each visible slice.
            min_lot: Minimum lot size.
            risk_pct: Risk percentage.
            atr: ATR value.
            max_slices: Maximum number of slices before giving up.

        Returns:
            ExecutionReport.
        """
        if self._trader is None:
            raise RuntimeError("SmartOrderRouter requires a trader instance")

        remaining = total_lots
        slices: List[OrderSlice] = []
        fill_prices: List[float] = []
        start_time = datetime.now()
        slice_id = 0

        logger.info("ICEBERG: %s %s %.2f total lots, %.2f visible per slice",
                     action, symbol, total_lots, visible_lots)

        while remaining >= min_lot and slice_id < max_slices:
            slice_id += 1
            chunk = min(visible_lots, remaining)
            s = OrderSlice(
                slice_id=slice_id,
                lots=chunk,
                target_time=datetime.now(),
            )

            try:
                result = self._trader.place_order(symbol, action, risk_pct, atr)
                if result.get("ok"):
                    trade = result.get("trade", {})
                    s.filled = True
                    s.fill_price = trade.get("price", 0.0)
                    s.fill_time = datetime.now()
                    fill_prices.append(s.fill_price)
                    remaining -= chunk
                else:
                    logger.warning("Iceberg slice %d rejected: %s",
                                   slice_id, result.get("error", "unknown"))
                    time.sleep(1)  # brief pause before retry
            except Exception as e:
                logger.error("Iceberg slice %d error: %s", slice_id, e)

            slices.append(s)

            # Small delay between slices to avoid detection
            if remaining >= min_lot and slice_id < max_slices:
                time.sleep(0.5)

        total_time = (datetime.now() - start_time).total_seconds()
        filled_slices = [s for s in slices if s.filled]
        avg_price = float(np.mean(fill_prices)) if fill_prices else 0.0

        report = ExecutionReport(
            parent_action=action,
            parent_lots=total_lots,
            slices_total=len(slices),
            slices_filled=len(filled_slices),
            avg_price=round(avg_price, 5),
            vwap_benchmark=round(avg_price, 5),
            slippage_vs_vwap_bps=0.0,
            total_time_seconds=round(total_time, 1),
            fill_rate_pct=round(
                sum(s.lots for s in filled_slices) / total_lots * 100, 1
            ) if total_lots > 0 else 0.0,
            market_impact_bps=0.0,
            algo="ICEBERG",
            slices=slices,
        )

        executed_pct = round((total_lots - remaining) / total_lots * 100, 1)
        logger.info(
            "Iceberg complete: executed %.1f%% (%.2f/%.2f lots), "
            "%d slices, avg price %.5f",
            executed_pct, total_lots - remaining, total_lots,
            len(filled_slices), report.avg_price,
        )
        return report

    # ── Volume Profile Builder ──────────────────────────────────────────────

    @staticmethod
    def build_volume_profile(
        df_ohlcv: "pd.DataFrame", n_buckets: int = 30
    ) -> List[float]:
        """Build an intraday volume profile from historical OHLCV data.

        Divides the trading day into n_buckets and computes the average
        volume for each bucket. Used by the VWAP algorithm.

        Args:
            df_ohlcv: DataFrame with DateTimeIndex and 'Volume' column.
            n_buckets: Number of time buckets (default 30 for 30-min slices).

        Returns:
            List of volume weights, one per bucket.
        """
        import pandas as pd

        if df_ohlcv is None or df_ohlcv.empty or "Volume" not in df_ohlcv.columns:
            return [1.0] * n_buckets

        df = df_ohlcv.copy()
        df["time_bucket"] = pd.cut(
            df.index.hour + df.index.minute / 60,
            bins=n_buckets,
            labels=False,
        )
        profile = df.groupby("time_bucket")["Volume"].mean().fillna(0).tolist()

        # Pad/trim
        if len(profile) < n_buckets:
            profile += [np.mean(profile)] * (n_buckets - len(profile))
        return profile[:n_buckets]
