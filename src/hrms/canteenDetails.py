"""
Canteen Details (canteen_details).

One row per employee, per date: how many meals taken and at what rate.
Rows carry their own branch_id, so the portal company/branch sidebar selection
drives the list (branch_mst gives the co_id) and the employee dropdown.

Lifecycle is the project-standard two-state cut of it: rows are created at 21
(Draft) and only a draft can be edited, approved or deleted. Approving moves
the row to 3 (Approved), which locks it — same rule as every other module.
Deleting moves it to 6 (Cancelled) so the list filter hides it.

The meal rate is not a user input: it is fixed by the canteen, so the client
never supplies it and edits never change it.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session
from sqlalchemy.sql import text

from src.authorization.utils import get_current_user_with_refresh
from src.common.utils import parse_json_body
from src.config.db import get_tenant_db
from src.models.hrms import CanteenDetails

router = APIRouter()

STATUS_DRAFT = 21
STATUS_APPROVED = 3
STATUS_CANCELLED = 6

# Fixed canteen rate per meal — matches the canteen_details column default.
DEFAULT_RATE_OF_MEALS = 40


# ─── SQL Queries ────────────────────────────────────────────────────


def get_canteen_list_query():
    """List rows joined to the employee, scoped by company/branch."""
    return text("""
        SELECT
            c.tran_id,
            c.tran_date,
            c.branch_id,
            bm.branch_name,
            c.eb_id,
            o.emp_code,
            CONCAT(IFNULL(p.first_name, ''), ' ', IFNULL(p.middle_name, ''), ' ',
                   IFNULL(p.last_name, '')) AS emp_name,
            c.no_of_meals,
            c.rate_of_meals,
            (IFNULL(c.no_of_meals, 0) * IFNULL(c.rate_of_meals, 0)) AS amount,
            c.status_id
        FROM canteen_details c
        INNER JOIN branch_mst bm ON bm.branch_id = c.branch_id
        LEFT JOIN hrms_ed_personal_details p ON p.eb_id = c.eb_id
        LEFT JOIN hrms_ed_official_details o ON o.eb_id = c.eb_id AND o.active = 1
        WHERE c.status_id <> :cancelled
          AND bm.co_id = :co_id
          AND (:branch_id IS NULL OR c.branch_id = :branch_id)
          AND (:date_from IS NULL OR c.tran_date >= :date_from)
          AND (:date_to IS NULL OR c.tran_date <= :date_to)
          AND (:search IS NULL
               OR o.emp_code LIKE :search
               OR CONCAT(IFNULL(p.first_name, ''), ' ', IFNULL(p.last_name, '')) LIKE :search)
        ORDER BY c.tran_date DESC, c.tran_id DESC
    """)


def get_canteen_by_id_query():
    return text("""
        SELECT tran_id, tran_date, branch_id, eb_id, no_of_meals, rate_of_meals, status_id
        FROM canteen_details
        WHERE tran_id = :record_id
    """)


def get_canteen_employees_query():
    """Active employees for the dropdown, scoped by company/branch."""
    return text("""
        SELECT
            p.eb_id,
            o.emp_code,
            CONCAT(IFNULL(p.first_name, ''), ' ', IFNULL(p.middle_name, ''), ' ',
                   IFNULL(p.last_name, '')) AS full_name
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


def _duplicate_query():
    """Same employee already has a canteen row for that date (ignoring one id)."""
    return text("""
        SELECT COUNT(*) AS cnt FROM canteen_details
        WHERE status_id <> :cancelled
          AND eb_id = :eb_id
          AND tran_date = :tran_date
          AND (:record_id IS NULL OR tran_id <> :record_id)
    """)


# ─── Helpers ────────────────────────────────────────────────────────


def _branch_param(request: Request) -> int | None:
    raw = request.query_params.get("branch_id")
    return int(raw) if raw not in (None, "", "null") else None


def _require_fields(body: dict) -> tuple[int, str, int, int]:
    """Validates everything a canteen row cannot be saved without.

    `rate_of_meals` is deliberately absent — it is fixed, so anything the
    client sends for it is ignored.
    """
    branch_id = body.get("branch_id")
    if not branch_id:
        raise HTTPException(status_code=400, detail="Branch is required")

    eb_id = body.get("eb_id")
    if not eb_id:
        raise HTTPException(status_code=400, detail="Employee is required")

    tran_date = body.get("tran_date")
    if not tran_date:
        raise HTTPException(status_code=400, detail="Date is required")

    meals = body.get("no_of_meals")
    if meals in (None, ""):
        raise HTTPException(status_code=400, detail="No. of meals is required")
    try:
        meals = int(meals)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="No. of meals must be a number")
    if meals <= 0:
        raise HTTPException(status_code=400, detail="No. of meals must be greater than 0")

    return int(branch_id), int(eb_id), str(tran_date), meals


def _require_draft(record: CanteenDetails, action: str) -> None:
    """Only a draft row may be changed — approved rows are locked project-wide."""
    if record.status_id != STATUS_DRAFT:
        raise HTTPException(
            status_code=400,
            detail=f"Only draft canteen entries can be {action}",
        )


def _parse_date(value: str):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Date must be in YYYY-MM-DD format")


# ─── Endpoints ──────────────────────────────────────────────────────


@router.get("/canteen_setup")
def canteen_setup(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Dropdown options: employees of the selected company/branch."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        employees = db.execute(get_canteen_employees_query(), {
            "co_id": int(co_id), "branch_id": _branch_param(request),
        }).fetchall()

        return {
            "data": {
                "employees": [
                    {
                        "value": str(m["eb_id"]),
                        "label": f"{m['emp_code'] or m['eb_id']} - {(m['full_name'] or '').strip()}",
                    }
                    for m in (dict(r._mapping) for r in employees)
                ],
                "default_rate": DEFAULT_RATE_OF_MEALS,
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_canteen_table")
def get_canteen_table(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Paginated list of canteen entries."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        search = request.query_params.get("search")
        page = int(request.query_params.get("page", 1))
        limit = int(request.query_params.get("limit", 10))

        rows = db.execute(get_canteen_list_query(), {
            "cancelled": STATUS_CANCELLED,
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
            m["tran_date"] = m["tran_date"].isoformat() if m.get("tran_date") else None
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


@router.get("/get_canteen_by_id/{record_id}")
def get_canteen_by_id(
    record_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Single canteen row, for the edit dialog."""
    try:
        row = db.execute(get_canteen_by_id_query(), {"record_id": record_id}).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Canteen entry not found")

        m = dict(row._mapping)
        m["tran_date"] = m["tran_date"].isoformat() if m.get("tran_date") else None
        return {"data": m}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/canteen_create")
def canteen_create(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Create a canteen entry."""
    try:
        body = parse_json_body(request)
        branch_id, eb_id, tran_date, meals = _require_fields(body)

        dup = db.execute(_duplicate_query(), {
            "cancelled": STATUS_CANCELLED, "eb_id": eb_id,
            "tran_date": tran_date, "record_id": None,
        }).fetchone()
        if dup and dup.cnt > 0:
            raise HTTPException(
                status_code=400,
                detail="A canteen entry already exists for this employee and date",
            )

        record = CanteenDetails(
            branch_id=branch_id,
            tran_date=_parse_date(tran_date),
            no_of_meals=meals,
            rate_of_meals=DEFAULT_RATE_OF_MEALS,
            eb_id=eb_id,
            status_id=STATUS_DRAFT,
            updated_by=str(token_data.get("user_id")) if token_data else None,
        )
        db.add(record)
        db.commit()
        db.refresh(record)

        return {
            "message": "Canteen entry created successfully",
            "tran_id": record.tran_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/canteen_edit/{record_id}")
def canteen_edit(
    record_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Update a canteen entry."""
    try:
        body = parse_json_body(request)
        branch_id, eb_id, tran_date, meals = _require_fields(body)

        existing = db.query(CanteenDetails).filter(
            CanteenDetails.tran_id == record_id,
        ).first()
        if not existing:
            raise HTTPException(status_code=404, detail="Canteen entry not found")
        _require_draft(existing, "edited")

        dup = db.execute(_duplicate_query(), {
            "cancelled": STATUS_CANCELLED, "eb_id": eb_id,
            "tran_date": tran_date, "record_id": record_id,
        }).fetchone()
        if dup and dup.cnt > 0:
            raise HTTPException(
                status_code=400,
                detail="A canteen entry already exists for this employee and date",
            )

        existing.branch_id = branch_id
        existing.eb_id = eb_id
        existing.tran_date = _parse_date(tran_date)
        existing.no_of_meals = meals
        # rate_of_meals is intentionally left untouched — it is not user input.
        existing.updated_by = str(token_data.get("user_id")) if token_data else None
        db.commit()

        return {"message": "Canteen entry updated successfully", "tran_id": record_id}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/canteen_approve/{record_id}")
def canteen_approve(
    record_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Approve a draft entry (21 -> 3). Approved rows can no longer be changed."""
    try:
        existing = db.query(CanteenDetails).filter(
            CanteenDetails.tran_id == record_id,
        ).first()
        if not existing:
            raise HTTPException(status_code=404, detail="Canteen entry not found")
        _require_draft(existing, "approved")

        existing.status_id = STATUS_APPROVED
        existing.updated_by = str(token_data.get("user_id")) if token_data else None
        db.commit()
        return {"message": "Canteen entry approved successfully", "tran_id": record_id}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/canteen_delete/{record_id}")
def canteen_delete(
    record_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Soft-delete a draft entry (status_id = 6), matching the list filter."""
    try:
        existing = db.query(CanteenDetails).filter(
            CanteenDetails.tran_id == record_id,
        ).first()
        if not existing:
            raise HTTPException(status_code=404, detail="Canteen entry not found")
        _require_draft(existing, "deleted")

        existing.status_id = STATUS_CANCELLED
        existing.updated_by = str(token_data.get("user_id")) if token_data else None
        db.commit()
        return {"message": "Canteen entry deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
