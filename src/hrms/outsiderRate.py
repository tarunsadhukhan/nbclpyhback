"""
Cash / Daily Rate Entry master (outsider_rate_approve).

One approved cash rate per employee, date and shift. The table carries no
co_id/branch_id of its own, so every read is scoped through the employee's
branch (hrms_ed_personal_details.branch_id -> branch_mst.co_id) — the portal
company/branch sidebar selection drives the list and the dropdowns.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session
from sqlalchemy.sql import text

from src.authorization.utils import get_current_user_with_refresh
from src.common.utils import parse_json_body
from src.config.db import get_tenant_db
from src.models.hrms import OutsiderRateApprove

router = APIRouter()


# ─── SQL Queries ────────────────────────────────────────────────────


def get_daily_rate_list_query():
    """List rows joined to employee + designation, scoped by company/branch."""
    return text("""
        SELECT
            r.outsider_rate_app_id,
            r.eb_id,
            o.emp_code,
            CONCAT(IFNULL(p.first_name, ''), ' ', IFNULL(p.middle_name, ''), ' ',
                   IFNULL(p.last_name, '')) AS emp_name,
            r.rate_approve,
            r.app_date,
            r.app_shift,
            r.desig_id,
            d.desig AS designation,
            r.is_active
        FROM outsider_rate_approve r
        INNER JOIN hrms_ed_personal_details p ON p.eb_id = r.eb_id
        INNER JOIN branch_mst bm ON bm.branch_id = p.branch_id
        LEFT JOIN hrms_ed_official_details o ON o.eb_id = r.eb_id AND o.active = 1
        LEFT JOIN designation_mst d ON d.designation_id = r.desig_id
        WHERE r.is_active = 1
          AND bm.co_id = :co_id
          AND (:branch_id IS NULL OR p.branch_id = :branch_id)
          AND (:date_from IS NULL OR r.app_date >= :date_from)
          AND (:date_to IS NULL OR r.app_date <= :date_to)
          AND (:search IS NULL
               OR o.emp_code LIKE :search
               OR CONCAT(IFNULL(p.first_name, ''), ' ', IFNULL(p.last_name, '')) LIKE :search
               OR d.desig LIKE :search)
        ORDER BY r.app_date DESC, r.outsider_rate_app_id DESC
    """)


def get_daily_rate_by_id_query():
    return text("""
        SELECT
            r.outsider_rate_app_id,
            r.eb_id,
            r.rate_approve,
            r.app_date,
            r.app_shift,
            r.desig_id,
            r.is_active
        FROM outsider_rate_approve r
        WHERE r.outsider_rate_app_id = :record_id
    """)


def get_rate_employees_query():
    """Active employees for the dropdown, scoped by company/branch."""
    return text("""
        SELECT
            p.eb_id,
            o.emp_code,
            CONCAT(IFNULL(p.first_name, ''), ' ', IFNULL(p.middle_name, ''), ' ',
                   IFNULL(p.last_name, '')) AS full_name,
            o.designation_id
        FROM hrms_ed_personal_details p
        INNER JOIN branch_mst bm ON bm.branch_id = p.branch_id
        LEFT JOIN hrms_ed_official_details o ON o.eb_id = p.eb_id AND o.active = 1
        WHERE COALESCE(p.active, 1) = 1
          AND bm.co_id = :co_id
          AND (:branch_id IS NULL OR p.branch_id = :branch_id)
        -- Employees with no official record (and so no emp_code) are kept but
        -- sorted last, so the dropdown opens on real EB numbers.
        ORDER BY o.emp_code IS NULL, o.emp_code, p.eb_id
    """)


def get_rate_designations_query():
    """Designations available to the branch (falls back to company-wide)."""
    return text("""
        SELECT DISTINCT d.designation_id, d.desig
        FROM designation_mst d
        WHERE COALESCE(d.active, 1) = 1
          AND (:branch_id IS NULL OR d.branch_id = :branch_id)
        ORDER BY d.desig
    """)


def get_rate_shifts_query():
    """Distinct spell codes configured for the tenant (A1/A2/B1/B2/C ...)."""
    return text("""
        SELECT DISTINCT s.spell_name
        FROM spell_mst s
        WHERE s.status = 1 AND s.spell_name IS NOT NULL AND s.spell_name <> ''
        ORDER BY s.spell_name
    """)


def _duplicate_query():
    """Same employee + date + shift already approved (ignoring one id)."""
    return text("""
        SELECT COUNT(*) AS cnt FROM outsider_rate_approve
        WHERE is_active = 1
          AND eb_id = :eb_id
          AND app_date = :app_date
          AND COALESCE(app_shift, '') = COALESCE(:app_shift, '')
          AND (:record_id IS NULL OR outsider_rate_app_id <> :record_id)
    """)


# ─── Helpers ────────────────────────────────────────────────────────


def _branch_param(request: Request) -> int | None:
    raw = request.query_params.get("branch_id")
    return int(raw) if raw not in (None, "", "null") else None


def _require_fields(body: dict) -> tuple[int, str, int]:
    """Validates the three fields a rate row cannot be saved without."""
    eb_id = body.get("eb_id")
    if not eb_id:
        raise HTTPException(status_code=400, detail="Employee is required")

    app_date = body.get("app_date")
    if not app_date:
        raise HTTPException(status_code=400, detail="Date is required")

    rate = body.get("rate_approve")
    if rate in (None, ""):
        raise HTTPException(status_code=400, detail="Approved rate is required")
    try:
        rate_val = int(rate)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Approved rate must be a number")
    if rate_val < 0:
        raise HTTPException(status_code=400, detail="Approved rate cannot be negative")

    return int(eb_id), str(app_date), rate_val


# ─── Endpoints ──────────────────────────────────────────────────────


@router.get("/daily_rate_setup")
def daily_rate_setup(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Dropdown options: employees, designations and shifts for the branch."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        branch_id = _branch_param(request)

        employees = db.execute(get_rate_employees_query(), {
            "co_id": int(co_id), "branch_id": branch_id,
        }).fetchall()
        designations = db.execute(get_rate_designations_query(), {
            "branch_id": branch_id,
        }).fetchall()
        shifts = db.execute(get_rate_shifts_query()).fetchall()

        return {
            "data": {
                "employees": [
                    {
                        "value": str(m["eb_id"]),
                        "label": f"{m['emp_code'] or m['eb_id']} - {(m['full_name'] or '').strip()}",
                        "designation_id": m["designation_id"],
                    }
                    for m in (dict(r._mapping) for r in employees)
                ],
                "designations": [
                    {
                        "value": str(dict(r._mapping)["designation_id"]),
                        "label": dict(r._mapping)["desig"],
                    }
                    for r in designations
                ],
                "shifts": [
                    {
                        "value": dict(r._mapping)["spell_name"],
                        "label": dict(r._mapping)["spell_name"],
                    }
                    for r in shifts
                ],
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_daily_rate_table")
def get_daily_rate_table(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Paginated list of approved daily/cash rates."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        search = request.query_params.get("search")
        page = int(request.query_params.get("page", 1))
        limit = int(request.query_params.get("limit", 10))

        rows = db.execute(get_daily_rate_list_query(), {
            "co_id": int(co_id),
            "branch_id": _branch_param(request),
            "date_from": request.query_params.get("date_from") or None,
            "date_to": request.query_params.get("date_to") or None,
            "search": f"%{search}%" if search else None,
        }).fetchall()

        all_data = []
        for row in rows:
            m = dict(row._mapping)
            m["emp_name"] = (m.get("emp_name") or "").strip()
            m["app_date"] = m["app_date"].isoformat() if m.get("app_date") else None
            all_data.append(m)

        total = len(all_data)
        start = (page - 1) * limit
        return {
            "data": all_data[start:start + limit],
            "total": total,
            "page": page,
            "limit": limit,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_daily_rate_by_id/{record_id}")
def get_daily_rate_by_id(
    record_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Single rate row, for the edit dialog."""
    try:
        row = db.execute(get_daily_rate_by_id_query(), {"record_id": record_id}).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Rate entry not found")

        m = dict(row._mapping)
        m["app_date"] = m["app_date"].isoformat() if m.get("app_date") else None
        return {"data": m}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/daily_rate_create")
def daily_rate_create(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Create a rate entry."""
    try:
        body = parse_json_body(request)
        eb_id, app_date, rate_val = _require_fields(body)
        app_shift = body.get("app_shift") or None

        dup = db.execute(_duplicate_query(), {
            "eb_id": eb_id, "app_date": app_date,
            "app_shift": app_shift, "record_id": None,
        }).fetchone()
        if dup and dup.cnt > 0:
            raise HTTPException(
                status_code=400,
                detail="A rate is already approved for this employee, date and shift",
            )

        record = OutsiderRateApprove(
            eb_id=eb_id,
            rate_approve=rate_val,
            app_date=datetime.strptime(app_date, "%Y-%m-%d").date(),
            app_shift=app_shift,
            desig_id=int(body["desig_id"]) if body.get("desig_id") else None,
            is_active=1,
        )
        db.add(record)
        db.commit()
        db.refresh(record)

        return {
            "message": "Rate entry created successfully",
            "outsider_rate_app_id": record.outsider_rate_app_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/daily_rate_edit/{record_id}")
def daily_rate_edit(
    record_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Update a rate entry."""
    try:
        body = parse_json_body(request)
        eb_id, app_date, rate_val = _require_fields(body)
        app_shift = body.get("app_shift") or None

        existing = db.query(OutsiderRateApprove).filter(
            OutsiderRateApprove.outsider_rate_app_id == record_id,
        ).first()
        if not existing:
            raise HTTPException(status_code=404, detail="Rate entry not found")

        dup = db.execute(_duplicate_query(), {
            "eb_id": eb_id, "app_date": app_date,
            "app_shift": app_shift, "record_id": record_id,
        }).fetchone()
        if dup and dup.cnt > 0:
            raise HTTPException(
                status_code=400,
                detail="A rate is already approved for this employee, date and shift",
            )

        existing.eb_id = eb_id
        existing.rate_approve = rate_val
        existing.app_date = datetime.strptime(app_date, "%Y-%m-%d").date()
        existing.app_shift = app_shift
        existing.desig_id = int(body["desig_id"]) if body.get("desig_id") else None
        db.commit()

        return {
            "message": "Rate entry updated successfully",
            "outsider_rate_app_id": record_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/daily_rate_delete/{record_id}")
def daily_rate_delete(
    record_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Soft-delete a rate entry (is_active = 0), matching the list filter."""
    try:
        existing = db.query(OutsiderRateApprove).filter(
            OutsiderRateApprove.outsider_rate_app_id == record_id,
        ).first()
        if not existing:
            raise HTTPException(status_code=404, detail="Rate entry not found")

        existing.is_active = 0
        db.commit()
        return {"message": "Rate entry deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
