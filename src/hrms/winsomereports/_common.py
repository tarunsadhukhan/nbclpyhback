"""Shared helpers for the Winsome report modules."""
from datetime import date

from sqlalchemy.orm import Session
from sqlalchemy.sql import text

from src.hrms.nbjclAttendanceReports import _col, _dmy, _layout, _num  # noqa: F401 — re-exported
from src.hrms.winsomeWagesProcess import UNIT_CODE, _scope  # noqa: F401 — re-exported


def rows(db: Session, sql: str, args: dict | None = None) -> list[dict]:
    """Query rows as dicts with Decimal -> float and strings trimmed."""
    out = []
    for r in db.execute(text(sql), args or {}):
        m = dict(r._mapping)
        for k, v in m.items():
            if isinstance(v, str):
                m[k] = v.strip()
            elif v is not None and not isinstance(v, (int, float, date)):
                m[k] = float(v)
        out.append(m)
    return out


def scope_args(b: int, **more) -> dict:
    """{"c": CompCode, "l": Location, "u": UnitCode} of the Winsome branch plus `more`."""
    comp, loc = _scope(b)
    return {"c": comp, "l": loc, "u": UNIT_CODE, **more}


def spec(title: str, build, dates: str = "range", span: str = "fortnight", extra=None, **more) -> dict:
    return {"title": title, "build": build, "dates": dates, "span": span, "extra": extra, **more}
