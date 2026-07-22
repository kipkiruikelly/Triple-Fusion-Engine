"""
data_quality.py
Data Quality Monitoring for the Triple-Fusion-Engine.

Monitors data pipeline health and alerts on anomalies:
  - Freshness checks: when was the last data update?
  - Completeness: are there gaps or missing bars?
  - Consistency: do OHLC values make sense? (high >= low, etc.)
  - Anomaly detection: sudden price spikes, volume outliers
  - Duplicate detection: identical consecutive bars
  - Staleness alerts for each data source

Usage:
    from data_quality import DataQualityMonitor
    dqm = DataQualityMonitor()
    report = dqm.check_dataframe(df, ticker="AAPL")
    if not report["passed"]:
        print(f"Data quality issues: {report['issues']}")

Author: BullLogic
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class DataQualityMonitor:
    """Monitors data quality across all pipeline stages."""

    def __init__(
        self,
        max_staleness_hours: int = 24,
        max_gap_bars: int = 5,
        volume_spike_threshold: float = 5.0,
        price_spike_threshold: float = 10.0,
    ):
        self.max_staleness_hours = max_staleness_hours
        self.max_gap_bars = max_gap_bars
        self.volume_spike_threshold = volume_spike_threshold
        self.price_spike_threshold = price_spike_threshold
        self.issues_log: List[dict] = []

    # ── DataFrame Validation ─────────────────────────────────────────────────

    def check_dataframe(
        self, df: pd.DataFrame, ticker: str = "unknown"
    ) -> dict:
        """Run all quality checks on a DataFrame.

        Returns:
            dict with passed (bool), score (0-100), issues (list), warnings (list).
        """
        if df is None or df.empty:
            report = {
                "passed": False, "score": 0,
                "issues": ["DataFrame is empty or None"],
                "warnings": [],
                "ticker": ticker,
                "n_rows": 0,
                "checked_at": datetime.now().isoformat(),
            }
            logger.warning("Data quality FAILED for %s: empty/None DataFrame", ticker)
            self.issues_log.append(report)
            return report

        issues = []
        warnings = []
        checks_passed = 0
        checks_total = 6

        # 1. Required columns
        required = ["Open", "High", "Low", "Close"]
        missing_cols = [c for c in required if c not in df.columns]
        if missing_cols:
            issues.append(f"Missing columns: {missing_cols}")
        else:
            checks_passed += 1

        # 2. OHLC consistency
        if not missing_cols:
            bad_ohlc = df[
                (df["High"] < df["Low"]) |
                (df["High"] < df["Open"]) |
                (df["High"] < df["Close"]) |
                (df["Low"] > df["Open"]) |
                (df["Low"] > df["Close"])
            ]
            if len(bad_ohlc) > 0:
                issues.append(f"{len(bad_ohlc)} bars with invalid OHLC (High<Low etc.)")
            else:
                checks_passed += 1

        # 3. Duplicate index
        dupes = df.index.duplicated().sum()
        if dupes > 0:
            issues.append(f"{dupes} duplicate timestamps found")
        else:
            checks_passed += 1

        # 4. Gap detection
        if len(df) > 1:
            gaps = self._detect_gaps(df)
            if gaps > self.max_gap_bars:
                warnings.append(f"{gaps} data gaps detected (>{self.max_gap_bars} bars)")
            else:
                checks_passed += 1
        else:
            checks_passed += 1

        # 5. Volume anomaly
        if "Volume" in df.columns and len(df) > 20:
            vol_spikes = self._detect_volume_spikes(df)
            if vol_spikes > 0:
                warnings.append(f"{vol_spikes} volume spikes detected (> {self.volume_spike_threshold}x avg)")
            checks_passed += 1
        else:
            checks_passed += 1

        # 6. Price anomaly
        if "Close" in df.columns and len(df) > 1:
            price_spikes = self._detect_price_spikes(df)
            if price_spikes > 0:
                warnings.append(f"{price_spikes} price spikes detected (> {self.price_spike_threshold}% move)")
            checks_passed += 1
        else:
            checks_passed += 1

        score = round(checks_passed / checks_total * 100, 1)
        passed = len(issues) == 0

        report = {
            "passed": passed,
            "score": score,
            "issues": issues,
            "warnings": warnings,
            "ticker": ticker,
            "n_rows": len(df),
            "date_range": f"{df.index.min()} → {df.index.max()}" if len(df) > 0 else "N/A",
            "checked_at": datetime.now().isoformat(),
        }

        if not passed:
            logger.warning("Data quality FAILED for %s: %s", ticker, issues)
        elif warnings:
            logger.info("Data quality WARN for %s: %s", ticker, warnings)

        self.issues_log.append(report)
        return report

    def _detect_gaps(self, df: pd.DataFrame) -> int:
        """Count gaps in time series (missing bars)."""
        if not isinstance(df.index, pd.DatetimeIndex):
            return 0
        diffs = df.index.to_series().diff().dropna()
        median_diff = diffs.median()
        if median_diff >= pd.Timedelta(hours=20):
            # Daily bars: weekend/holiday spacing (up to 4 calendar days,
            # e.g. Friday → Tuesday) is expected, not a data gap.
            gaps = diffs[diffs > pd.Timedelta(days=4)]
        else:
            gaps = diffs[diffs > median_diff * 2]
        return len(gaps)

    def _detect_volume_spikes(self, df: pd.DataFrame) -> int:
        """Count volume bars that are N times the rolling average."""
        vol = df["Volume"].values.astype(float)
        if len(vol) < 20:
            return 0
        rolling_avg = pd.Series(vol).rolling(20, min_periods=10).mean().values
        spikes = vol > rolling_avg * self.volume_spike_threshold
        return int(spikes.sum())

    def _detect_price_spikes(self, df: pd.DataFrame) -> int:
        """Count bars where price moved more than threshold % in one period."""
        close = df["Close"].values.astype(float)
        returns = np.abs(np.diff(close) / close[:-1]) * 100
        return int((returns > self.price_spike_threshold).sum())

    # ── Freshness Checks ────────────────────────────────────────────────────

    def check_staleness(
        self, last_update: datetime, source_name: str = "unknown"
    ) -> dict:
        """Check if data is stale based on last update time.

        Args:
            last_update: Datetime of the most recent data point.
            source_name: Human-readable source identifier.

        Returns:
            dict with is_stale, hours_since_update, status.
        """
        now = datetime.now(timezone.utc)
        if last_update.tzinfo is None:
            last_update = last_update.replace(tzinfo=timezone.utc)

        hours = (now - last_update).total_seconds() / 3600
        is_stale = hours > self.max_staleness_hours

        status = "fresh" if hours < 1 else (
            "aging" if hours < self.max_staleness_hours else "stale"
        )

        if is_stale:
            logger.warning("Data staleness: %s last updated %.1f hours ago",
                           source_name, hours)

        return {
            "source": source_name,
            "is_stale": is_stale,
            "hours_since_update": round(hours, 1),
            "status": status,
            "last_update": last_update.isoformat(),
        }

    # ── Model Data Quality ──────────────────────────────────────────────────

    def check_model_features(
        self, X: np.ndarray, feature_names: List[str]
    ) -> dict:
        """Check feature matrix for common ML pipeline issues.

        Returns:
            dict with has_nan, has_inf, zero_variance_cols, constant_cols.
        """
        if X is None or X.size == 0:
            return {"has_nan": False, "has_inf": False, "zero_variance_cols": [],
                    "constant_cols": [], "n_samples": 0}

        issues = {
            "has_nan": bool(np.isnan(X).any()),
            "has_inf": bool(np.isinf(X).any()),
            "zero_variance_cols": [],
            "constant_cols": [],
            "n_samples": X.shape[0],
            "n_features": X.shape[1],
        }

        # Check zero-variance and constant columns
        for i in range(min(X.shape[1], len(feature_names))):
            col = X[:, i]
            if np.isnan(col).all():
                continue
            std = float(np.nanstd(col))
            if std < 1e-8:
                issues["zero_variance_cols"].append(feature_names[i])

        if issues["has_nan"]:
            logger.warning("Feature matrix contains NaN values")
        if issues["has_inf"]:
            logger.warning("Feature matrix contains Inf values")
        if issues["zero_variance_cols"]:
            logger.warning("Zero-variance features: %s", issues["zero_variance_cols"])

        return issues

    # ── Summary Report ──────────────────────────────────────────────────────

    def summary_report(self) -> dict:
        """Return a summary of all quality issues logged."""
        if not self.issues_log:
            return {"status": "clean", "total_checks": 0, "failures": 0}

        failures = [r for r in self.issues_log if not r["passed"]]
        warnings = [r for r in self.issues_log if r.get("warnings")]

        return {
            # Failures decide health; warnings are advisory and reported
            # separately in warnings_count.
            "status": "dirty" if failures else "clean",
            "total_checks": len(self.issues_log),
            "failures": len(failures),
            "warnings_count": len(warnings),
            "avg_score": round(
                np.mean([r["score"] for r in self.issues_log]), 1
            ) if self.issues_log else 100.0,
            "recent_issues": failures[-5:] if failures else [],
        }
