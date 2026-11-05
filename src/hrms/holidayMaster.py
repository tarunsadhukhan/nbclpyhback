"""
Holiday Master (holiday_master) — HRMS Master -> Holiday Masters.

Ports legacy Smart Eye FrmHoliday (PayOHoliday): the holidays of one year for
a branch are edited together as a grid of date + event. Unlike legacy's
delete-and-reinsert, rows are kept by holiday_id — hrms_holiday_transactions
(holiday eligibility / wages) points at them — so a removed row is deleted
only when no transaction uses it.

New rows get holiday_type 1 (occasional) and status 3, like the migrated rows.
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy.sql import text

from src.authorization.utils import get_current_user_with_refresh
from src.common.utils import parse_json_body
from src.config.db import get_tenant_db

router = APIRouter()


def _int_param(request: Request, name: str) -> int:
    raw = request.query_params.get(name)
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"{name} is required and must be an integer")


@router.get("/holiday_years")
def holiday_years(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Years with holidays for the branch, newest first."""
    try:
        rows = db.execute(text("""
            SELECT YEAR(holiday_date) yr, COUNT(*) holidays,
                   MIN(holiday_date) first_date, MAX(holiday_date) last_date
            FROM holiday_master WHERE branch_id = :b AND holiday_date IS NOT NULL
            GROUP BY YEAR(holiday_date) ORDER BY yr DESC
        """), {"b": _int_param(request, "branch_id")}).fetchall()
        return {"data": [
            {"id": r.yr, "year": r.yr, "holidays": r.holidays,
             "first_date": r.first_date.isoformat(), "last_date": r.last_date.isoformat()}
            for r in rows
        ]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/holiday_year")
def holiday_year(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Holidays of one year; in_use = referenced by holiday transactions (can't be removed)."""
    try:
        rows = db.execute(text("""
            SELECT h.holiday_id, h.holiday_date, h.holiday,
                   EXISTS (SELECT 1 FROM hrms_holiday_transactions t WHERE t.holiday_id = h.holiday_id) in_use
            FROM holiday_master h
            WHERE h.branch_id = :b AND YEAR(h.holiday_date) = :y
            ORDER BY h.holiday_date, h.holiday_id
        """), {"b": _int_param(request, "branch_id"), "y": _int_param(request, "year")}).fetchall()
        return {"data": [
            {"holiday_id": r.holiday_id, "holiday_date": r.holiday_date.isoformat(),
             "holiday": r.holiday or "", "in_use": bool(r.in_use)}
            for r in rows
        ]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/holiday_year_save")
def holiday_year_save(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Save one year: body {branch_id, year, rows: [{holiday_id?, holiday_date, holiday}]}.
    Rows of the year missing from the body are deleted (refused when in use)."""
    try:
        body = parse_json_body(request)
        try:
            b, year = int(body.get("branch_id")), int(body.get("year"))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="branch_id and year are required")
        if not 1900 <= year <= 2100:
            raise HTTPException(status_code=400, detail="Enter year in correct format")
        rows = body.get("rows") or []

        clean, seen = [], {}
        for i, r in enumerate(rows, 1):
            try:
                d = date.fromisoformat(str(r.get("holiday_date") or ""))
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Please enter a valid date in line {i}")
            if d.year != year:
                raise HTTPException(status_code=400, detail=f"Line {i}: date is not in {year}")
            name = str(r.get("holiday") or "").strip()
            if not name:
                raise HTTPException(status_code=400, detail=f"Please enter the event in line {i}")
            if len(name) > 255:
                raise HTTPException(status_code=400, detail=f"Line {i}: event is too long (max 255)")
            if d in seen:
                raise HTTPException(status_code=400, detail=f"Line {i}: {d:%d/%m/%Y} is already on line {seen[d]}")
            seen[d] = i
            hid = r.get("holiday_id")
            clean.append((int(hid) if hid not in (None, "") else None, d, name))

        existing = {r.holiday_id: r for r in db.execute(text("""
            SELECT h.holiday_id, EXISTS (SELECT 1 FROM hrms_holiday_transactions t
                                         WHERE t.holiday_id = h.holiday_id) in_use
            FROM holiday_master h WHERE h.branch_id = :b AND YEAR(h.holiday_date) = :y
        """), {"b": b, "y": year})}
        kept = {hid for hid, _, _ in clean if hid is not None}
        unknown = kept - existing.keys()
        if unknown:
            raise HTTPException(status_code=400, detail="Some rows no longer exist — reload and try again")
        removed = existing.keys() - kept
        if any(existing[h].in_use for h in removed):
            raise HTTPException(
                status_code=400,
                detail="A removed holiday is already used in holiday transactions and can't be deleted",
            )

        user = token_data.get("user_id") if token_data else None
        if removed:
            db.execute(text("DELETE FROM holiday_master WHERE holiday_id = :id"), [{"id": h} for h in removed])
        for hid, d, name in clean:
            if hid is None:
                db.execute(text("""
                    INSERT INTO holiday_master (branch_id, holiday, holiday_date, holiday_type, updated_by, status)
                    VALUES (:b, :name, :d, 1, :u, 3)
                """), {"b": b, "name": name, "d": d, "u": user})
            else:
                db.execute(text("""
                    UPDATE holiday_master SET holiday = :name, holiday_date = :d, updated_by = :u,
                           updated_date_time = NOW()
                    WHERE holiday_id = :id
                """), {"id": hid, "name": name, "d": d, "u": user})
        db.commit()
        return {"message": f"{year}: {len(clean)} holiday(s) saved"}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
