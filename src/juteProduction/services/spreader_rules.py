"""Business rules for spreader production entries.

Encapsulates the tricky group-assignment, item-lock, no-backdate, and
4-hour-window logic so both the entry router and the bin-state preview
endpoint share a single implementation.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.juteProduction.constants import GROUP_WINDOW_HOURS


@dataclass
class WindowResult:
    allowed: bool
    base_dt: Optional[datetime]
    allowed_end_dt: Optional[datetime]
    candidate_dt: datetime
    reason: str = ""


def _active_group_for_bin(db: Session, co_id: int, bin_id: int):
    """Return (entry_id_grp, locked_item_id) for the latest in-stock group in the bin,
    or (None, None) if the bin has no open group."""
    sql = text(
        """
        SELECT z.entry_id_grp, z.item_id
        FROM (
            SELECT p.entry_id_grp,
                   CAST(SUBSTRING_INDEX(
                       MIN(CONCAT(p.entry_dt, '|', LPAD(p.item_id, 9, '0'))), '|', -1
                   ) AS UNSIGNED) AS item_id
            FROM spreader_prod_entry p
            WHERE p.co_id = :co_id AND p.bin_id = :bin_id AND p.active = 1
            GROUP BY p.entry_id_grp
        ) z
        JOIN (
            SELECT p.entry_id_grp,
                   SUM(p.no_of_rolls) AS produced,
                   COALESCE((
                       SELECT SUM(i.no_of_rolls)
                       FROM spreader_roll_issue i
                       WHERE i.entry_id_grp = p.entry_id_grp AND i.active = 1
                   ), 0) AS issued
            FROM spreader_prod_entry p
            WHERE p.co_id = :co_id AND p.bin_id = :bin_id AND p.active = 1
            GROUP BY p.entry_id_grp
        ) s ON s.entry_id_grp = z.entry_id_grp
        WHERE (s.produced - s.issued) > 0
        ORDER BY z.entry_id_grp DESC
        LIMIT 1
        """
    )
    row = db.execute(sql, {"co_id": co_id, "bin_id": bin_id}).fetchone()
    if not row:
        return None, None
    return int(row[0]), int(row[1])


def _next_entry_id_grp(db: Session, co_id: int) -> int:
    sql = text("SELECT COALESCE(MAX(entry_id_grp), 0) FROM spreader_prod_entry WHERE co_id = :co_id")
    cur = db.execute(sql, {"co_id": co_id}).scalar() or 0
    return int(cur) + 1


def evaluate_4hr_window(db: Session, entry_id_grp: int, candidate_dt: datetime) -> Optional[WindowResult]:
    """Return whether `candidate_dt` falls inside the 4-hr window of `entry_id_grp`.

    Returns None if the group has no entries.
    """
    earliest_sql = text(
        """
        SELECT MIN(entry_dt) AS first_dt
        FROM spreader_prod_entry
        WHERE entry_id_grp = :grp AND active = 1
        """
    )
    row = db.execute(earliest_sql, {"grp": entry_id_grp}).fetchone()
    if not row or row[0] is None:
        return None

    base_dt = row[0] if isinstance(row[0], datetime) else datetime.fromisoformat(str(row[0]))
    candidate_dt = candidate_dt.replace(second=0, microsecond=0)
    # Same-day earliest hour determines the daily window; cross-midnight handled implicitly via entry_dt.
    same_day_sql = text(
        """
        SELECT MIN(entry_dt) AS first_dt
        FROM spreader_prod_entry
        WHERE entry_id_grp = :grp AND active = 1
          AND entry_date = :d
        """
    )
    same_row = db.execute(same_day_sql, {"grp": entry_id_grp, "d": candidate_dt.date()}).fetchone()
    if same_row and same_row[0]:
        sd = same_row[0] if isinstance(same_row[0], datetime) else datetime.fromisoformat(str(same_row[0]))
        base_dt = sd
    else:
        # Check previous day for cross-midnight continuation
        prev_sql = text(
            """
            SELECT MIN(entry_dt) AS first_dt
            FROM spreader_prod_entry
            WHERE entry_id_grp = :grp AND active = 1
              AND entry_date = :pd
            """
        )
        prev = db.execute(
            prev_sql, {"grp": entry_id_grp, "pd": candidate_dt.date() - timedelta(days=1)}
        ).fetchone()
        if prev and prev[0]:
            pd_dt = prev[0] if isinstance(prev[0], datetime) else datetime.fromisoformat(str(prev[0]))
            if (pd_dt + timedelta(hours=GROUP_WINDOW_HOURS)).date() == candidate_dt.date():
                base_dt = pd_dt
            else:
                base_dt = candidate_dt
        else:
            base_dt = candidate_dt

    allowed_end_dt = base_dt + timedelta(hours=GROUP_WINDOW_HOURS)
    # Backdated guard
    if candidate_dt < base_dt:
        return WindowResult(
            allowed=False,
            base_dt=base_dt,
            allowed_end_dt=allowed_end_dt,
            candidate_dt=candidate_dt,
            reason=(
                f"Backdated entry not allowed. Group window started "
                f"{base_dt:%Y-%m-%d %H:00}; candidate {candidate_dt:%Y-%m-%d %H:00} precedes it."
            ),
        )
    allowed = candidate_dt <= allowed_end_dt
    reason = (
        ""
        if allowed
        else (
            f"Group window closed. Base {base_dt:%Y-%m-%d %H:00} → allowed until "
            f"{allowed_end_dt:%Y-%m-%d %H:00}; candidate {candidate_dt:%Y-%m-%d %H:00} is outside the 4-hour window."
        )
    )
    return WindowResult(allowed=allowed, base_dt=base_dt, allowed_end_dt=allowed_end_dt, candidate_dt=candidate_dt, reason=reason)


def get_bin_state(db: Session, co_id: int, bin_id: int, candidate_dt: datetime) -> dict:
    """Snapshot the bin's open-group state and 4-hr window evaluation for the candidate datetime.

    Returns dict with: active_grp, locked_item_id, window: { allowed, base_dt, allowed_end_dt, reason }.
    """
    grp, locked = _active_group_for_bin(db, co_id, bin_id)
    window_info = None
    if grp is not None:
        win = evaluate_4hr_window(db, grp, candidate_dt)
        if win is not None:
            window_info = {
                "allowed": win.allowed,
                "base_dt": win.base_dt.isoformat() if win.base_dt else None,
                "allowed_end_dt": win.allowed_end_dt.isoformat() if win.allowed_end_dt else None,
                "candidate_dt": win.candidate_dt.isoformat(),
                "reason": win.reason,
            }
    return {
        "active_grp": grp,
        "locked_item_id": locked,
        "window": window_info,
    }


def assign_or_reuse_entry_id_grp(
    db: Session,
    co_id: int,
    bin_id: int,
    item_id: int,
    candidate_dt: datetime,
) -> Tuple[int, bool]:
    """Decide whether the new entry joins the bin's open group or starts a fresh one.

    Raises ValueError when the entry would violate item-lock, no-backdate or the 4-hr window.
    Returns (entry_id_grp, reused).
    """
    grp, locked_item = _active_group_for_bin(db, co_id, bin_id)
    if grp is None:
        return _next_entry_id_grp(db, co_id), False

    if int(item_id) != int(locked_item):
        raise ValueError(
            "This bin already has an open group with a different item. "
            "Finish issuing those rolls before producing a new item into the same bin."
        )

    win = evaluate_4hr_window(db, grp, candidate_dt)
    if win is None:
        # Should not happen — group existed but no entries — fall back to fresh group.
        return _next_entry_id_grp(db, co_id), False
    if not win.allowed:
        raise ValueError(win.reason)
    return grp, True
