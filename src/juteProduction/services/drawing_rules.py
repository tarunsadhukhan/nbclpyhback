"""Business rules for drawing production entries — single source of truth.

The frontend mirrors these computations for live preview only; the server
values are authoritative and recomputed on every create/edit.
"""

from src.juteProduction.constants import EFF_BASE_HOURS


def compute_diff_meter(open_meter: float, close_meter: float, wrap_limit: int) -> float:
    """Meters run during the spell, handling odometer wrap.

    close - open; when the counter wrapped (open > close):
    (close + wrap_limit) - open. Legacy used a fixed 10000 wrap.
    """
    open_meter = float(open_meter)
    close_meter = float(close_meter)
    if open_meter > close_meter:
        return (close_meter + float(wrap_limit)) - open_meter
    return close_meter - open_meter


def compute_eff(diff_meter: float, const_meter: float, wrk_hours: float) -> float:
    """Efficiency %: diff / (const_meter / EFF_BASE_HOURS * wrk_hours) * 100.

    const_meter is the machine's meters per 8-hour shift at 100% efficiency.
    Returns 0.0 when diff, const_meter or wrk_hours is not positive.
    """
    diff_meter = float(diff_meter)
    const_meter = float(const_meter)
    wrk_hours = float(wrk_hours)
    if diff_meter <= 0 or const_meter <= 0 or wrk_hours <= 0:
        return 0.0
    return round(diff_meter / (const_meter / EFF_BASE_HOURS * wrk_hours) * 100, 2)
