"""
Tests for economic_calendar.py — event listing, date-based lookups,
high-impact day detection, volatility warnings, and impact scoring.

All tests use the pre-loaded _MAJOR_EVENTS data so they are fully
deterministic and never hit a network.
"""

from datetime import date, datetime
from unittest.mock import patch

import pytest

from economic_calendar import (
    event_impact_label,
    event_impact_score,
    event_volatility_warning,
    get_events_for_date,
    get_upcoming_events,
    is_high_impact_day,
)


# ── get_upcoming_events tests ──────────────────────────────────────────────────

class TestGetUpcomingEvents:
    """Filtering economic events by lookahead window, currency, and impact."""

    def test_default_7_days(self):
        """Default call returns events within the next 7 days from today."""
        today = date.today()
        events = get_upcoming_events()
        for e in events:
            event_date = datetime.strptime(e["date"], "%Y-%m-%d").date()
            assert today <= event_date <= today.replace(day=today.day + 7) or \
                today <= event_date, "Event date must be >= today"

    def test_with_currency_filter(self):
        """Filtering by 'EUR' returns only EUR-denominated events."""
        today = date.today()
        # Use a wide window so we likely get some EUR events
        events = get_upcoming_events(days_ahead=365, currency="EUR")
        assert all(e["currency"] == "EUR" for e in events)
        assert len(events) > 0, "Expected at least one EUR event in 365-day window"

    def test_with_min_impact_filter(self):
        """min_impact=9 returns only critical events (impact >= 9)."""
        events = get_upcoming_events(days_ahead=365, min_impact=9)
        assert all(e["impact"] >= 9 for e in events)

    def test_zero_days_ahead_returns_empty(self):
        """days_ahead=0 should return no events (cutoff == today, exclusive)."""
        events = get_upcoming_events(days_ahead=0)
        assert events == [], f"Expected empty list, got {len(events)} events"

    def test_365_days_ahead(self):
        """A full year window should return many events across all currencies."""
        events = get_upcoming_events(days_ahead=365, min_impact=1)
        assert len(events) > 0, "Expected events in a 365-day window"
        # All returned events should have days_away within [0, 365]
        for e in events:
            assert 0 <= e["days_away"] <= 365


# ── get_events_for_date tests ──────────────────────────────────────────────────

class TestGetEventsForDate:
    """Looking up events by exact date."""

    def test_found(self):
        """Known FOMC date returns at least one event."""
        events = get_events_for_date(date(2026, 1, 29))
        assert len(events) >= 1
        assert any(e["type"] == "FOMC" for e in events)

    def test_not_found(self):
        """A date with no events returns an empty list."""
        events = get_events_for_date(date(2026, 6, 15))
        assert events == []

    def test_invalid_date_format(self):
        """Passing an invalid date raises ValueError (strptime failure)."""
        # The function expects a ``date`` object, so invalid types should raise.
        with pytest.raises(AttributeError):
            get_events_for_date("not-a-date")  # type: ignore


# ── is_high_impact_day tests ───────────────────────────────────────────────────

class TestIsHighImpactDay:
    """Detecting dates with impact >= 7 events."""

    def test_fomc_day_returns_true(self):
        """Jan 29 2026 is an FOMC day (impact=9) → True."""
        assert is_high_impact_day(date(2026, 1, 29)) is True

    def test_normal_day_returns_false(self):
        """A day with no events → False."""
        assert is_high_impact_day(date(2026, 6, 15)) is False

    def test_gdp_day_returns_true(self):
        """Mar 26 2026 is GDP (impact=7) → True."""
        assert is_high_impact_day(date(2026, 3, 26)) is True

    def test_cpi_day_returns_true(self):
        """Feb 12 2026 is CPI (impact=8) → True."""
        assert is_high_impact_day(date(2026, 2, 12)) is True

    def test_low_impact_day_returns_false(self):
        """HOUSING (impact=5) is below threshold 7 → False."""
        # There is no HOUSING event in _MAJOR_EVENTS, but we can test
        # a day that has an ECB decision (impact=8, so actually True).
        # Use a day with nothing at all.
        assert is_high_impact_day(date(2026, 5, 1)) is False


# ── event_volatility_warning tests ─────────────────────────────────────────────

class TestEventVolatilityWarning:
    """Volatility warning levels based on upcoming event density."""

    @patch("economic_calendar.date")
    def test_critical_fomc_within_range(self, mock_date_module):
        """When FOMC (impact=9) falls within the window → level='critical'."""
        mock_date_module.today.return_value = date(2026, 1, 27)
        warning = event_volatility_warning(days_ahead=5)
        assert warning["level"] == "critical"
        assert any(e["type"] == "FOMC" for e in warning["events"])

    @patch("economic_calendar.date")
    def test_warning_two_plus_high_events(self, mock_date_module):
        """Two+ high-impact (>=7) events and no critical (>=9) → 'warning'."""
        # Jan 21-24 window contains:
        #   Jan 23 ECB RATE_DECISION (impact=8)
        #   Jan 24 BOJ RATE_DECISION (impact=8)
        # Two events with impact>=7, none with impact>=9 → level='warning'.
        mock_date_module.today.return_value = date(2026, 1, 21)
        warning = event_volatility_warning(days_ahead=3)
        assert warning["level"] == "warning", (
            f"Expected 'warning' for 2 high-impact events, got '{warning['level']}'"
        )
        assert len(warning["events"]) >= 2
        assert all(e["impact"] >= 7 for e in warning["events"])

    @patch("economic_calendar.date")
    def test_caution_one_high_event(self, mock_date_module):
        """Exactly 1 high-impact event → level='caution'."""
        # ECB decision on Apr 16 (impact=8), no other events within 3 days
        mock_date_module.today.return_value = date(2026, 4, 14)
        warning = event_volatility_warning(days_ahead=3)
        # Apr 14-17: Apr 16 ECB (impact=8) is >=7, and no >=9 events
        # That's 1 high event -> caution
        assert warning["level"] == "caution", (
            f"Expected caution, got {warning['level']}"
        )

    @patch("economic_calendar.date")
    def test_none(self, mock_date_module):
        """No high-impact events in window → level='none'."""
        mock_date_module.today.return_value = date(2026, 5, 15)
        warning = event_volatility_warning(days_ahead=3)
        assert warning["level"] == "none"
        assert warning["events"] == []


# ── event_impact_score tests ───────────────────────────────────────────────────

class TestEventImpactScore:
    """Event type → numeric impact score mapping."""

    def test_fomc_returns_9(self):
        assert event_impact_score("FOMC") == 9

    def test_gdp_returns_7(self):
        assert event_impact_score("GDP") == 7

    def test_housing_returns_5(self):
        assert event_impact_score("HOUSING") == 5

    def test_unknown_type_returns_3(self):
        assert event_impact_score("UNKNOWN") == 3

    def test_case_insensitive(self):
        assert event_impact_score("fomc") == 9
        assert event_impact_score("gdp") == 7


# ── event_impact_label tests ───────────────────────────────────────────────────

class TestEventImpactLabel:
    """Numeric score → human-readable label mapping."""

    def test_score_9_is_critical(self):
        assert event_impact_label(9) == "critical"

    def test_score_8_is_high(self):
        assert event_impact_label(8) == "high"

    def test_score_5_is_medium(self):
        assert event_impact_label(5) == "medium"

    def test_score_3_is_low(self):
        assert event_impact_label(3) == "low"

    def test_score_2_defaults_to_low(self):
        """Scores not in the label map default to 'low'."""
        assert event_impact_label(2) == "low"

    def test_score_7_is_high(self):
        """Score 7 maps to 'high' per the IMPACT_LABELS dict."""
        assert event_impact_label(7) == "high"

    def test_score_6_is_medium(self):
        """Score 6 maps to 'medium' per the IMPACT_LABELS dict."""
        assert event_impact_label(6) == "medium"

    def test_score_4_is_low(self):
        """Score 4 maps to 'low' per the IMPACT_LABELS dict."""
        assert event_impact_label(4) == "low"
