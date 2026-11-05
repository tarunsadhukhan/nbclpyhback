"""
Holiday Process / Entry (hrms_holiday_transactions) — legacy Smart Eye
FrmHolidayProcess + SP_HolidayProcessing.

As in legacy, a wages (P) period is picked and its holidays listed; Process
makes the holiday's eligible employees. An employee is eligible when their
duty hours (working + night, pay_attendance att_type R) on the attendance
date reach MIN_DUTY_HOURS; outsiders / contractors / staff are excluded
(legacy Grade = MILL-WORKMEN). Each gets HOLIDAY_HOURS.

The attendance date (legacy PDate/NDate) defaults to the last day before the
holiday with a real turnout (>= half the busiest day's heads) — skeleton-crew
days such as 14/08/2026 (13 heads) are skipped, as legacy operators did. It can
be overridden. Verified against legacy PayWHoliday for 15/08/2026 branch 87:
453 = 453, same employees.

Processed rows are manual = 0 and are replaced on every run; rows keyed by hand
(manual = 1) are kept and those employees skipped.

ponytail: skipped SP rules — rest-day fallback (legacy RestDay is blank for
~all workers) and the PayWHolidayEligShift shift-hours rule (no table here).
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy.sql import text

from src.authorization.utils import get_current_user_with_refresh
from src.common.utils import parse_json_body
from src.config.db import get_tenant_db
from src.hrms.canteenDetails import get_canteen_employees_query

router = APIRouter()

STATUS_ACTIVE = 3  # holiday_master.status
HOLIDAY_HOURS = 8
MAX_HOLIDAY_HOURS = 24
MIN_DUTY_HOURS = 8
LOOKBACK_DAYS = 10

HOLIDAY_SQL = text("""
    SELECT holiday_id, holiday_date, holiday FROM holiday_master
    WHERE holiday_id = :holiday_id AND branch_id = :branch_id AND IFNULL(status, 3) = :status
""")


def _int(body: dict, name: str) -> int:
    try:
        return int(body.get(name))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"{name} is required and must be an integer")


def _q(request: Request, name: str) -> int:
    return _int(dict(request.query_params), name)


def _holiday(db: Session, branch_id: int, holiday_id: int):
    h = db.execute(HOLIDAY_SQL, {"holiday_id": holiday_id, "branch_id": branch_id, "status": STATUS_ACTIVE}).fetchone()
    if not h:
        raise HTTPException(status_code=404, detail="Holiday not found for this branch")
    return h


def pick_attendance_date(duty_heads: dict) -> date | None:
    """Latest day with >= half the busiest day's heads (see module doc)."""
    if not duty_heads:
        return None
    busiest = max(duty_heads.values())
    return max(d for d, heads in duty_heads.items() if heads * 2 >= busiest)


def _duty_heads(db: Session, branch_id: int, holiday_date: date) -> dict:
    rows = db.execute(text("""
        SELECT attendance_date, COUNT(DISTINCT eb_id) AS heads
        FROM pay_attendance
        WHERE branch_id = :branch_id AND att_type = 'R'
          AND attendance_date BETWEEN DATE_SUB(:holiday_date, INTERVAL :lookback DAY)
                                  AND DATE_SUB(:holiday_date, INTERVAL 1 DAY)
        GROUP BY attendance_date
    """), {"branch_id": branch_id, "holiday_date": holiday_date, "lookback": LOOKBACK_DAYS}).fetchall()
    return {r.attendance_date: r.heads for r in rows}


# ─── Endpoints ────────────────────────────────────────────────────────────


@router.get("/holiday_process_setup")
def holiday_process_setup(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Wages (P) pay periods of the branch, newest first, plus employee options."""
    try:
        scope = {"co_id": _q(request, "co_id"), "branch_id": _q(request, "branch_id")}
        periods = db.execute(text("""
            SELECT ID id, code, FROM_DATE from_date, TO_DATE to_date FROM pay_period
            WHERE COMPANY_ID = :co_id AND (branch_id IS NULL OR branch_id = :branch_id)
              AND code LIKE 'P%' AND FROM_DATE IS NOT NULL AND TO_DATE IS NOT NULL
            ORDER BY TO_DATE DESC, ID DESC
        """), scope).fetchall()
        employees = db.execute(get_canteen_employees_query(), scope).fetchall()
        return {"data": {
            "periods": [
                {"value": str(p.id), "label": f"{p.code}: {p.from_date:%d-%m-%Y} to {p.to_date:%d-%m-%Y}",
                 "to_date": p.to_date.isoformat()}
                for p in periods
            ],
            "employees": [
                {"value": str(r.eb_id), "label": f"{r.emp_code or r.eb_id} - {(r.full_name or '').strip()}"}
                for r in employees
            ],
        }}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/holiday_process_holidays")
def holiday_process_holidays(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Holidays inside the period with prev / next day, the suggested attendance
    date and how many employees are processed / manual."""
    try:
        b = _q(request, "branch_id")
        period = db.execute(text("SELECT FROM_DATE, TO_DATE FROM pay_period WHERE ID = :id"),
                            {"id": _q(request, "period_id")}).fetchone()
        if not period:
            raise HTTPException(status_code=404, detail="Pay period not found")
        rows = db.execute(text("""
            SELECT h.holiday_id, h.holiday_date, h.holiday,
                   SUM(t.manual = 0) processed, SUM(IFNULL(t.manual, 1) = 1) manual
            FROM holiday_master h
            LEFT JOIN hrms_holiday_transactions t ON t.holiday_id = h.holiday_id AND t.branch_id = h.branch_id
            WHERE h.branch_id = :b AND IFNULL(h.status, 3) = :status
              AND h.holiday_date BETWEEN :f AND :t
            GROUP BY h.holiday_id ORDER BY h.holiday_date
        """), {"b": b, "status": STATUS_ACTIVE, "f": period.FROM_DATE, "t": period.TO_DATE}).fetchall()
        data = []
        for r in rows:
            att = pick_attendance_date(_duty_heads(db, b, r.holiday_date))
            data.append({
                "id": r.holiday_id, "holiday_id": r.holiday_id, "holiday_date": r.holiday_date.isoformat(),
                "holiday": r.holiday, "processed": int(r.processed or 0), "manual": int(r.manual or 0),
                "attendance_date": att.isoformat() if att else None,
            })
        return {"data": data}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/holiday_process")
def holiday_process(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Process one holiday: body {branch_id, holiday_id, attendance_date?}."""
    try:
        body = parse_json_body(request)
        branch_id, holiday_id = _int(body, "branch_id"), _int(body, "holiday_id")
        h = _holiday(db, branch_id, holiday_id)
        if body.get("attendance_date"):
            try:
                attendance_date = date.fromisoformat(str(body["attendance_date"]))
            except ValueError:
                raise HTTPException(status_code=400, detail="attendance_date must be YYYY-MM-DD")
            if attendance_date == h.holiday_date:
                raise HTTPException(status_code=400, detail="Attendance date can't be the holiday itself")
        else:
            attendance_date = pick_attendance_date(_duty_heads(db, branch_id, h.holiday_date))
            if attendance_date is None:
                raise HTTPException(
                    status_code=400,
                    detail=f"No processed attendance in the {LOOKBACK_DAYS} days before the holiday "
                           "— run Daily Wages Process first",
                )

        params = {
            "branch_id": branch_id, "holiday_id": holiday_id, "holiday_date": h.holiday_date,
            "attendance_date": attendance_date, "min_hours": MIN_DUTY_HOURS, "holiday_hours": HOLIDAY_HOURS,
            "updated_by": token_data.get("user_id") if token_data else None,
        }
        db.execute(text("""
            DELETE FROM hrms_holiday_transactions
            WHERE branch_id = :branch_id AND holiday_id = :holiday_id AND manual = 0
        """), params)
        result = db.execute(text("""
            INSERT INTO hrms_holiday_transactions
                (holiday_id, eb_id, holiday_hours, eligibility_date, branch_id, updated_by, manual)
            SELECT :holiday_id, pa.eb_id, :holiday_hours, :holiday_date, :branch_id, :updated_by, 0
            FROM pay_attendance pa
            LEFT JOIN hrms_ed_official_details o ON o.eb_id = pa.eb_id AND o.active = 1
            LEFT JOIN category_mst cm ON cm.cata_id = o.catagory_id
            WHERE pa.branch_id = :branch_id AND pa.att_type = 'R' AND pa.attendance_date = :attendance_date
              AND COALESCE(cm.cata_desc, '') NOT IN ('OUTSIDER', 'CONTRACTOR', 'STAFF')
              AND pa.eb_id NOT IN (
                  SELECT eb_id FROM hrms_holiday_transactions
                  WHERE branch_id = :branch_id AND holiday_id = :holiday_id AND COALESCE(manual, 1) = 1)
            GROUP BY pa.eb_id
            HAVING SUM(COALESCE(pa.working_hrs, 0) + COALESCE(pa.ns_hrs, 0)) >= :min_hours
        """), params)
        db.commit()
        return {"data": {"attendance_date": attendance_date.isoformat(), "eligible": result.rowcount}}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/holiday_tran_by_holiday")
def holiday_tran_by_holiday(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Employees of one holiday (processed + manual)."""
    try:
        rows = db.execute(text("""
            SELECT t.holiday_tran_id, t.eb_id, t.holiday_hours, COALESCE(t.manual, 1) AS manual,
                   CONCAT(COALESCE(o.emp_code, t.eb_id), ' - ',
                          CONCAT_WS(' ', NULLIF(TRIM(p.first_name), ''), NULLIF(TRIM(p.middle_name), ''),
                                    NULLIF(TRIM(p.last_name), ''))) AS emp_label
            FROM hrms_holiday_transactions t
            LEFT JOIN hrms_ed_personal_details p ON p.eb_id = t.eb_id
            LEFT JOIN hrms_ed_official_details o ON o.eb_id = t.eb_id AND o.active = 1
            WHERE t.branch_id = :branch_id AND t.holiday_id = :holiday_id
            ORDER BY COALESCE(t.manual, 1) DESC, o.emp_code IS NULL, o.emp_code, t.eb_id
        """), {"branch_id": _q(request, "branch_id"), "holiday_id": _q(request, "holiday_id")}).fetchall()
        return {"data": [
            {**dict(r._mapping), "id": r.holiday_tran_id, "holiday_hours": float(r.holiday_hours or 0)}
            for r in rows
        ]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/holiday_tran_save")
def holiday_tran_save(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Add / edit one manual row: body {branch_id, holiday_id, eb_id, holiday_hours, holiday_tran_id?}.
    A processed row of the same employee becomes this manual row."""
    try:
        body = parse_json_body(request)
        branch_id, holiday_id, eb_id = _int(body, "branch_id"), _int(body, "holiday_id"), _int(body, "eb_id")
        try:
            hours = round(float(body.get("holiday_hours")), 2)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="holiday_hours must be a number")
        if not 0 < hours <= MAX_HOLIDAY_HOURS:
            raise HTTPException(status_code=400, detail=f"Holiday hours must be above 0 and at most {MAX_HOLIDAY_HOURS}")
        tran_id = body.get("holiday_tran_id")
        tran_id = int(tran_id) if tran_id not in (None, "") else None
        h = _holiday(db, branch_id, holiday_id)

        p = {"branch_id": branch_id, "holiday_id": holiday_id, "eb_id": eb_id, "holiday_hours": hours,
             "eligibility_date": h.holiday_date, "holiday_tran_id": tran_id,
             "updated_by": token_data.get("user_id") if token_data else None}
        dup = db.execute(text("""
            SELECT holiday_tran_id, COALESCE(manual, 1) manual FROM hrms_holiday_transactions
            WHERE branch_id = :branch_id AND holiday_id = :holiday_id AND eb_id = :eb_id
              AND (:holiday_tran_id IS NULL OR holiday_tran_id <> :holiday_tran_id)
            LIMIT 1
        """), p).fetchone()
        if dup and dup.manual == 1:
            raise HTTPException(status_code=400, detail="This employee already has hours for this holiday")
        if dup:  # processed row -> taken over by the manual entry
            db.execute(text("DELETE FROM hrms_holiday_transactions WHERE holiday_tran_id = :id"),
                       {"id": dup.holiday_tran_id})

        if tran_id is None:
            db.execute(text("""
                INSERT INTO hrms_holiday_transactions
                    (holiday_id, eb_id, holiday_hours, eligibility_date, branch_id, updated_by, manual)
                VALUES (:holiday_id, :eb_id, :holiday_hours, :eligibility_date, :branch_id, :updated_by, 1)
            """), p)
        else:
            n = db.execute(text("""
                UPDATE hrms_holiday_transactions
                SET eb_id = :eb_id, holiday_hours = :holiday_hours, eligibility_date = :eligibility_date,
                    updated_by = :updated_by, updated_date_time = CURRENT_TIMESTAMP, manual = 1
                WHERE holiday_tran_id = :holiday_tran_id AND branch_id = :branch_id AND holiday_id = :holiday_id
            """), p).rowcount
            if not n:
                raise HTTPException(status_code=404, detail="Holiday entry not found")
        db.commit()
        return {"message": "Holiday entry saved"}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/holiday_tran_delete/{holiday_tran_id}")
def holiday_tran_delete(
    holiday_tran_id: int,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Hard delete one row (a processed row comes back on the next Process)."""
    try:
        n = db.execute(text("DELETE FROM hrms_holiday_transactions WHERE holiday_tran_id = :id"),
                       {"id": holiday_tran_id}).rowcount
        if not n:
            raise HTTPException(status_code=404, detail="Holiday entry not found")
        db.commit()
        return {"message": "Holiday entry deleted"}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
