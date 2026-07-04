"""
economic_calendar.py
Economic Calendar Integration for the Triple-Fusion-Engine.

Provides upcoming economic events that may impact market volatility:
  - FOMC meetings, NFP, CPI, GDP, PMI, interest rate decisions
  - Event importance classification (low/medium/high)
  - Forecast vs actual tracking
  - Volatility impact scoring per event type
  - Pre-built list of major events for 2024-2026

Usage:
    from economic_calendar import get_upcoming_events, event_impact_score
    events = get_upcoming_events(days_ahead=7)
    for e in events:
        print(f"{e['date']} {e['title']} - Impact: {e['impact']}")

Author: BullLogic
"""

import logging
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Event Type → Volatility Impact Score ────────────────────────────────────────

EVENT_IMPACT = {
    "FOMC":                 9,   # Federal Reserve rate decision
    "NFP":                  9,   # Non-Farm Payrolls
    "CPI":                  8,   # Consumer Price Index
    "GDP":                  7,   # Gross Domestic Product
    "PMI":                  6,   # Purchasing Managers Index
    "RATE_DECISION":        9,   # Central bank rate decision
    "RETAIL_SALES":         6,   # Retail sales data
    "UNEMPLOYMENT":         7,   # Unemployment claims
    "PPI":                  6,   # Producer Price Index
    "HOUSING":              5,   # Housing starts / sales
    "CONFIDENCE":           5,   # Consumer confidence
    "MANUFACTURING":        5,   # Industrial production
    "TRADE_BALANCE":        4,   # Trade balance
    "EARNINGS":             7,   # Major corporate earnings
    "GOVERNMENT":           8,   # Government policy / fiscal
    "GEOPOLITICAL":         8,   # Geopolitical events
    "SPEECH":               4,   # Central bank speech
}

IMPACT_LABELS = {9: "critical", 8: "high", 7: "high", 6: "medium",
                 5: "medium", 4: "low", 3: "low"}


def event_impact_score(event_type: str) -> int:
    """Return the volatility impact score (1-10) for an event type."""
    return EVENT_IMPACT.get(event_type.upper(), 3)


def event_impact_label(score: int) -> str:
    """Convert impact score to human-readable label."""
    return IMPACT_LABELS.get(score, "low")


# ── Major Economic Events Database ──────────────────────────────────────────────

# Pre-loaded events for 2024-2026. In production, this would be fetched from
# an API like ForexFactory, TradingEconomics, or Bloomberg.
_MAJOR_EVENTS = [
    # ── 2026 ──
    {"date": "2026-01-29", "title": "FOMC Rate Decision", "type": "FOMC",
     "currency": "USD", "impact": 9},
    {"date": "2026-02-07", "title": "US Non-Farm Payrolls (Jan)", "type": "NFP",
     "currency": "USD", "impact": 9},
    {"date": "2026-02-12", "title": "US CPI YoY (Jan)", "type": "CPI",
     "currency": "USD", "impact": 8},
    {"date": "2026-03-19", "title": "FOMC Rate Decision", "type": "FOMC",
     "currency": "USD", "impact": 9},
    {"date": "2026-03-26", "title": "US GDP Q4 Final", "type": "GDP",
     "currency": "USD", "impact": 7},
    {"date": "2026-04-10", "title": "US CPI YoY (Mar)", "type": "CPI",
     "currency": "USD", "impact": 8},
    {"date": "2026-05-07", "title": "FOMC Rate Decision", "type": "FOMC",
     "currency": "USD", "impact": 9},
    {"date": "2026-06-11", "title": "US CPI YoY (May)", "type": "CPI",
     "currency": "USD", "impact": 8},
    {"date": "2026-06-18", "title": "FOMC Rate Decision", "type": "FOMC",
     "currency": "USD", "impact": 9},
    {"date": "2026-07-30", "title": "FOMC Rate Decision", "type": "FOMC",
     "currency": "USD", "impact": 9},
    {"date": "2026-07-30", "title": "US GDP Q2 Advance", "type": "GDP",
     "currency": "USD", "impact": 7},
    {"date": "2026-08-07", "title": "US Non-Farm Payrolls (Jul)", "type": "NFP",
     "currency": "USD", "impact": 9},
    {"date": "2026-08-12", "title": "US CPI YoY (Jul)", "type": "CPI",
     "currency": "USD", "impact": 8},

    # ── ECB ──
    {"date": "2026-01-23", "title": "ECB Rate Decision", "type": "RATE_DECISION",
     "currency": "EUR", "impact": 8},
    {"date": "2026-03-12", "title": "ECB Rate Decision", "type": "RATE_DECISION",
     "currency": "EUR", "impact": 8},
    {"date": "2026-04-16", "title": "ECB Rate Decision", "type": "RATE_DECISION",
     "currency": "EUR", "impact": 8},
    {"date": "2026-06-04", "title": "ECB Rate Decision", "type": "RATE_DECISION",
     "currency": "EUR", "impact": 8},
    {"date": "2026-07-23", "title": "ECB Rate Decision", "type": "RATE_DECISION",
     "currency": "EUR", "impact": 8},

    # ── BOE ──
    {"date": "2026-02-05", "title": "BOE Rate Decision", "type": "RATE_DECISION",
     "currency": "GBP", "impact": 8},
    {"date": "2026-05-07", "title": "BOE Rate Decision", "type": "RATE_DECISION",
     "currency": "GBP", "impact": 8},

    # ── BOJ ──
    {"date": "2026-01-24", "title": "BOJ Rate Decision", "type": "RATE_DECISION",
     "currency": "JPY", "impact": 8},
    {"date": "2026-04-28", "title": "BOJ Rate Decision", "type": "RATE_DECISION",
     "currency": "JPY", "impact": 8},
    {"date": "2026-07-29", "title": "BOJ Rate Decision", "type": "RATE_DECISION",
     "currency": "JPY", "impact": 8},
]


def get_upcoming_events(
    days_ahead: int = 7,
    min_impact: int = 4,
    currency: Optional[str] = None,
) -> List[dict]:
    """Return upcoming economic events within the next N days.

    Args:
        days_ahead: Number of days to look ahead.
        min_impact: Minimum impact score (1-10) to include.
        currency: Optional filter for specific currency (e.g. "USD").

    Returns:
        List of event dicts sorted by date.
    """
    today = date.today()
    cutoff = today + timedelta(days=days_ahead)

    events = []
    for e in _MAJOR_EVENTS:
        try:
            event_date = datetime.strptime(e["date"], "%Y-%m-%d").date()
        except ValueError:
            continue

        if today <= event_date <= cutoff:
            if e["impact"] >= min_impact:
                if currency is None or e["currency"] == currency:
                    events.append({
                        **e,
                        "days_away": (event_date - today).days,
                        "impact_label": event_impact_label(e["impact"]),
                    })

    events.sort(key=lambda x: x["date"])
    return events


def get_events_for_date(target_date: date) -> List[dict]:
    """Return all major events for a specific date."""
    date_str = target_date.strftime("%Y-%m-%d")
    return [e for e in _MAJOR_EVENTS if e["date"] == date_str]


def is_high_impact_day(target_date: Optional[date] = None) -> bool:
    """Check if today (or given date) has any high-impact events."""
    if target_date is None:
        target_date = date.today()
    events = get_events_for_date(target_date)
    return any(e["impact"] >= 7 for e in events)


def event_volatility_warning(days_ahead: int = 3) -> dict:
    """Return a volatility warning for the next few days.

    Used by the trading engine to adjust position sizing or pause trading
    ahead of major events.

    Returns:
        dict with warning_level ("none"/"caution"/"warning"/"critical")
        and list of upcoming high-impact events.
    """
    high_events = get_upcoming_events(days_ahead=days_ahead, min_impact=7)
    critical_events = [e for e in high_events if e["impact"] >= 9]

    if critical_events:
        level = "critical"
    elif len(high_events) >= 2:
        level = "warning"
    elif high_events:
        level = "caution"
    else:
        level = "none"

    return {
        "level": level,
        "events": high_events,
        "recommendation": (
            "Consider reducing position sizes or pausing trading"
            if level in ("warning", "critical") else
            "Normal trading conditions" if level == "none" else
            "Trade with caution, use tighter stops"
        ),
    }
