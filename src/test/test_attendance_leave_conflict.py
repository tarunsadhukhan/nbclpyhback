"""Self-check for _check_leave_conflict (attendance vs vw_leave_dates rule).

Rule: a leave date blocks the save; payable='Y' softens it to allow only
Cash ('C') / OT ('O') — never Regular ('R'). Run: python -m src.test.test_attendance_leave_conflict
"""
from fastapi import HTTPException

from src.hrms.attendance import _check_leave_conflict


class _Row:
    def __init__(self, payable):
        self.payable = payable


class _Result:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _DB:
    """Stub Session: db.execute(...).fetchone() returns the configured row."""
    def __init__(self, row):
        self._row = row

    def execute(self, *args, **kwargs):
        return _Result(self._row)


def _blocks(row, att_type):
    try:
        _check_leave_conflict(_DB(row), 1, "2026-07-04", att_type)
        return False
    except HTTPException:
        return True


def test_leave_conflict_rule():
    # No leave on the date -> every type is allowed.
    for t in ("R", "C", "O"):
        assert _blocks(None, t) is False

    # Unpaid (or missing payable) leave -> nothing may be saved.
    for t in ("R", "C", "O"):
        assert _blocks(_Row("N"), t) is True
        assert _blocks(_Row(None), t) is True

    # Paid leave -> Regular blocked, Cash / OT allowed.
    assert _blocks(_Row("Y"), "R") is True
    assert _blocks(_Row("y"), "R") is True  # case-insensitive
    assert _blocks(_Row("Y"), "C") is False
    assert _blocks(_Row("Y"), "O") is False

    # Missing eb_id or date -> no check runs.
    assert _check_leave_conflict(_DB(_Row("N")), 0, "2026-07-04", "R") is None
    assert _check_leave_conflict(_DB(_Row("N")), 1, None, "R") is None


if __name__ == "__main__":
    test_leave_conflict_rule()
    print("all leave-conflict checks passed")
