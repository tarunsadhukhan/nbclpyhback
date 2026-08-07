"""essl_resolver — pure-Python replica of the eSSL eTrack TrackLite
"Daily Attendance Detailed Report" daily-row computation.

Given one employee's raw biometric punches over a window, group them into work
sessions and produce one ``DailyResult`` per attendance-day, matching what the
eSSL Detailed Report emits (shift, in/out, work/OT/break, late/early, status).

Design notes (validated against the eSSL Excel golden set, Apr-Jun 2026):

* **In/Out is positional, not direction-based.** Within a session,
  ``actual_in`` is the FIRST punch and ``actual_out`` is the LAST punch,
  regardless of the device's in/out label (verified 22186/22186). The device
  ``device_direction``/``device_id`` are NOT used to decide in/out — they are
  only used cosmetically when rendering the punch_records string.

* **Shift** is chosen from the first-in hour band, with a cross-midnight
  override: an afternoon/evening start whose session reaches the next morning is
  Shift C (night).  04-07->A, 08-10->GS, 11-16->B, >=17 or crosses-midnight->C.

* **Work/OT** is span-minus-breaks, capped at 8h regular:
  ``work = min(8h, worked)``, ``ot = max(0, worked - 8h)``.

This module performs NO database access and never mutates state — it is a pure
function of its inputs, so it can be unit-tested directly against the golden set.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta


# ── Tunables (pinned empirically against the golden set) ──────────────────────

# A new work session begins whenever the gap from the previous punch exceeds
# this. It sits in the empirical window between the largest intra-shift gap
# (a night shift's evening IN -> next-morning OUT, ~8-10h; a day shift's only
# two punches up to ~10h apart) and the smallest inter-shift gap (a night OUT ->
# the next evening IN, ~11.9h; a morning OUT -> evening IN, ~15h). The split is
# PURELY time-based: the device's in/out label and physical reader are
# unreliable (a shift can start on the OUT reader), so they are NOT used to
# delimit sessions.
NEW_SHIFT_GAP_HOURS = 11.0

# A session is one shift-day. A continuous multi-shift worker (e.g. afternoon-IN
# -> night work -> next-morning-OUT, day after day) punches every ~8h, so no gap
# ever exceeds NEW_SHIFT_GAP_HOURS and a pure gap split would merge every day into
# one session — losing all but the first day. Cap a session's span instead: the
# eSSL golden set has legitimate sessions up to ~16h (p99.9) and essentially none
# beyond 18h, so a run that reaches MAX_SESSION_HOURS from its first punch has
# rolled into the next shift and must start a fresh session.
# ponytail: empirical cap (vendor ceiling + margin); widen only if a real single
# shift legitimately exceeds it.
MAX_SESSION_HOURS = 18.0

# Consecutive punches within this gap are the SAME event (a double-tap or a
# device re-read) and collapse to one punch. Measured from the previous KEPT
# punch, mirroring an eSSL device's minimum-repunch lockout.
MIN_REPUNCH_MINUTES = 2

REGULAR_WORK_MINUTES = 8 * 60  # eSSL regular-hours cap (8h)

# Scheduled in/out per shift (HH:MM). Shift C's out is on the next calendar day.
SHIFT_SCHED: dict[str, tuple[str, str]] = {
    "A":  ("06:00", "14:00"),
    "GS": ("10:00", "18:00"),
    "B":  ("14:00", "22:00"),
    "C":  ("22:00", "06:00"),
}


@dataclass(frozen=True)
class Punch:
    """One raw biometric punch."""
    log_date: datetime
    raw_dir: str = ""          # device's in/out text (cosmetic only)
    device_id: int | None = None


@dataclass
class DailyResult:
    """One eSSL-style daily attendance row."""
    tran_date: date
    shift: str
    sched_in: str
    sched_out: str
    actual_in: datetime
    actual_out: datetime | None
    work_minutes: int
    ot_minutes: int
    break_minutes: int
    total_minutes: int
    late_minutes: int
    early_going_minutes: int
    status: str
    punch_records: str
    punch_count: int = 0
    crosses_midnight: bool = False


# ── Helpers ───────────────────────────────────────────────────────────────────

def _hhmm_to_minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _shift_for(first_in: datetime, crosses_midnight: bool) -> str | None:
    """Map a session's first-in to an eSSL shift label.

    The 13:00-17:59 band is ambiguous between an evening day-shift (B) and a
    night shift (C); it resolves to C only when the session actually crosses
    midnight. Bands: 04-07->A, 08-10->GS, 11-12->B, 13-17->B/C, 18+->C, 00-03->C.
    """
    h = first_in.hour
    if 4 <= h < 8:
        return "A"
    if 8 <= h < 11:
        return "GS"
    if 11 <= h < 13:
        return "B"
    if 13 <= h < 18:
        return "C" if crosses_midnight else "B"
    if h >= 18:
        return "C"
    # 00:00-03:59 — a bare early-morning start with no prior evening (night tail).
    return "C"


def _collapse_near_duplicates(ordered: list[Punch]) -> list[Punch]:
    """Drop punches within ``MIN_REPUNCH_MINUTES`` of the previous KEPT punch.

    Input must be chronologically sorted. A burst (double-tap / device re-read)
    collapses to its earliest punch, so it never fabricates a short break or a
    1-minute in/out pair. The lockout resets from each kept punch, matching an
    eSSL device's minimum-repunch interval.
    """
    kept: list[Punch] = []
    for p in ordered:
        if kept and (p.log_date - kept[-1].log_date) <= timedelta(minutes=MIN_REPUNCH_MINUTES):
            continue
        kept.append(p)
    return kept


def segment_sessions(punches: list[Punch]) -> list[list[Punch]]:
    """Split an employee's chronologically-sorted punches into work sessions.

    Near-duplicate punches (within ``MIN_REPUNCH_MINUTES``) are first collapsed to
    a single event. A new session then starts whenever the gap from the previous
    punch exceeds ``NEW_SHIFT_GAP_HOURS``. The split is purely time-based: a night
    shift's evening IN keeps its next-morning OUT (gap < threshold) while a
    genuinely new shift (gap > threshold) starts fresh — and a long day shift whose
    only two punches sit ~10h apart is not split. The device's in/out label and
    physical reader are deliberately ignored here (a shift can be punched on the
    wrong reader); in/out within a session is positional (first punch / last punch).
    """
    ordered = _collapse_near_duplicates(sorted(punches, key=lambda p: p.log_date))
    sessions: list[list[Punch]] = []
    current: list[Punch] = []
    for p in ordered:
        if current and (
            (p.log_date - current[-1].log_date) > timedelta(hours=NEW_SHIFT_GAP_HOURS)
            or (p.log_date - current[0].log_date) > timedelta(hours=MAX_SESSION_HOURS)
        ):
            sessions.append(current)
            current = []
        current.append(p)
    if current:
        sessions.append(current)
    return sessions


def _abs_minute(dt: datetime, base: date) -> int:
    """Absolute minute-of-day for ``dt`` relative to ``base``, SECONDS DROPPED.

    eSSL reports all durations at minute granularity using the punches' HH:MM
    (seconds are discarded before differencing — verified 99.4% on 2-punch days).
    A punch on a later calendar date than ``base`` rolls past midnight (+1440/day).
    """
    day_offset = (dt.date() - base).days
    return day_offset * 1440 + dt.hour * 60 + dt.minute


def _compute_break_minutes(minutes: list[int]) -> int:
    """Break time = sum of the gaps of intermediate (out,in) pairs, in minutes.

    The punches strictly between the first and last come in (OUT,IN) pairs — the
    employee leaves then returns — so each pair's gap is a break. A trailing
    unpaired intermediate punch is ignored.
    """
    if len(minutes) <= 2:
        return 0
    mid = minutes[1:-1]
    brk = 0
    j = 0
    while j + 1 < len(mid):
        brk += mid[j + 1] - mid[j]
        j += 2
    return brk


def _fmt_punch_records(session: list[Punch], *, no_out: bool, sched_out: str) -> str:
    """Render the cosmetic eSSL-style punch_records string with alternating
    in/out labels (1st=in, 2nd=out, ...). This affects display only."""
    parts: list[str] = []
    for i, p in enumerate(session):
        direction = "in" if i % 2 == 0 else "out"
        parts.append(f"{p.log_date.strftime('%H:%M')}:{direction}")
    if no_out:
        parts.append(f"{sched_out}:out(SE)")
    return ",".join(parts)


def resolve_session(session: list[Punch], *, is_off_day: bool = False,
                    is_holiday: bool = False, is_weekly_off: bool = False,
                    ot_eligible: bool = True) -> DailyResult | None:
    """Compute one ``DailyResult`` from a single work session.

    ``ot_eligible`` reflects the employee's eSSL OT-eligibility (workers get the
    8h-cap + OT split; non-OT staff record the whole span as regular work). It is
    NOT derivable from punches — the caller supplies it (default True). eSSL also
    applies a per-day OT *sanction* policy that can suppress small OT; that
    config is not available here, so OT may over-count vs the eSSL report on
    unsanctioned days. See docs spec for details.
    """
    if not session:
        return None
    session = sorted(session, key=lambda p: p.log_date)
    first = session[0].log_date
    last = session[-1].log_date
    tran_date = first.date()
    crosses_midnight = last.date() > first.date()

    shift = _shift_for(first, crosses_midnight)
    if shift is None:
        return None
    sched_in, sched_out = SHIFT_SCHED[shift]

    # All durations are computed in truncated minutes relative to tran_date.
    in_min = _abs_minute(first, tran_date)
    sched_in_min = _hhmm_to_minutes(sched_in)
    sched_out_min = _hhmm_to_minutes(sched_out) + (1440 if shift == "C" else 0)

    no_out = len(session) < 2
    if no_out:
        # Synthesize the OUT at scheduled end; no OT credit, no early-going.
        actual_out = None
        out_min = sched_out_min
        break_min = 0
        worked_min = max(0, out_min - in_min)
        work_min = worked_min
        ot_min = 0
        early_min = 0
    else:
        actual_out = last
        out_min = _abs_minute(last, tran_date)
        punch_mins = [_abs_minute(p.log_date, tran_date) for p in session]
        break_min = _compute_break_minutes(punch_mins)
        span_min = max(0, out_min - in_min)
        worked_min = max(0, span_min - break_min)
        if (is_off_day or is_holiday or is_weekly_off) and ot_eligible:
            # On a non-working day every worked minute is overtime (eSSL: an
            # OT-eligible employee present on a weekly-off / holiday gets
            # work=0, ot=full). Non-OT (staff) keep it as regular work.
            work_min = 0
            ot_min = worked_min
        elif ot_eligible:
            work_min = min(REGULAR_WORK_MINUTES, worked_min)
            ot_min = max(0, worked_min - REGULAR_WORK_MINUTES)
        else:
            # Non-OT (staff): the whole worked span is regular, never OT.
            work_min = worked_min
            ot_min = 0
        early_min = max(0, sched_out_min - out_min)

    late_min = max(0, in_min - sched_in_min)

    # status text
    if no_out:
        status = "Present  (No OutPunch)"
    elif is_holiday:
        status = "Holiday Present"
    elif is_weekly_off:
        status = "WeeklyOff Present"
    elif is_off_day:
        status = "Off Day Present"
    else:
        status = "Present "

    return DailyResult(
        tran_date=tran_date,
        shift=shift,
        sched_in=sched_in,
        sched_out=sched_out,
        actual_in=first,
        actual_out=actual_out,
        work_minutes=work_min,
        ot_minutes=ot_min,
        break_minutes=break_min,
        total_minutes=work_min + ot_min,
        late_minutes=late_min,
        early_going_minutes=early_min,
        status=status,
        punch_records=_fmt_punch_records(session, no_out=no_out, sched_out=sched_out),
        punch_count=len(session),
        crosses_midnight=crosses_midnight,
    )


def resolve_employee_days(punches: list[Punch]) -> list[DailyResult]:
    """Resolve all of one employee's punches into per-attendance-day results.

    Off-day/holiday/weekly-off status is applied by the caller (it needs the
    tenant calendar); this returns plain Present/No-OutPunch rows.
    """
    results: list[DailyResult] = []
    for session in segment_sessions(punches):
        r = resolve_session(session)
        if r is not None:
            results.append(r)
    return results
