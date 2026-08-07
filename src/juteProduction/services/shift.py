"""Shift / spell helpers for spreader entries and reports.

Bucket cutoffs (must mirror frontend src/app/dashboardportal/juteProduction/spreader/utils/shift.ts):
  A1: 06-10
  B1: 11-13
  A2: 14-16
  B2: 17-21
  C : 22-05 (overflows to next calendar day's 00-05)
"""

from datetime import date, timedelta
from typing import Optional


def spell_from_hour(hour: int) -> str:
    """Return the spell code for the given hour-of-day (0..23)."""
    h = int(hour)
    if 6 <= h <= 10:
        return "A1"
    if 11 <= h <= 13:
        return "B1"
    if 14 <= h <= 16:
        return "A2"
    if 17 <= h <= 21:
        return "B2"
    return "C"


def shift_for_report(entry_date: date, hour: int, report_date: date) -> Optional[str]:
    """Map a production entry to a shift bucket on a given report_date.

    Hours 00..05 of (report_date + 1) belong to the C shift of report_date,
    matching the mill's overnight overflow rule.
    """
    h = int(hour)
    if entry_date == report_date:
        if h < 6:
            return None  # belongs to previous day's C
        return spell_from_hour(h)
    if entry_date == report_date + timedelta(days=1) and h < 6:
        return "C"
    return None
