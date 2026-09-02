"""
Electric Data (electric_details) — others/electricdata.

One row per employee + date: the electric amount charged to the worker.
Same shape as Canteen Details, minus meals/rate — the amount is keyed
directly. Rows carry their own branch_id, so the portal company/branch
sidebar selection drives the list (branch_mst gives the co_id) and the
employee dropdown (reused from canteen).

ponytail: plain active=1 soft-delete lifecycle; add the canteen-style
draft/approve statuses if payroll starts consuming these rows.
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session
from sqlalchemy.sql import text

from src.authorization.utils import get_current_user_with_refresh
from src.common.utils import parse_json_body
from src.config.db import get_tenant_db
from src.hrms.canteenDetails import get_canteen_employees_query
from src.models.hrms import ElectricDetails

router = APIRouter()


# ─── SQL Queries ──────────────────────────────────────────────────────────


def get_electric_list_query():
    """List rows joined to the employee, scoped by company/branch."""
    return text("""
        SELECT
            e.tran_id, e.tran_date, e.branch_id,
            e.eb_id, o.emp_code,
            CONCAT(IFNULL(p.first_name, ''), ' ', IFNULL(p.middle_name, ''), ' ',
                   IFNULL(p.last_name, '')) AS emp_name,
            e.amount, e.remarks, e.active
        FROM electric_details e
        INNER JOIN branch_mst bm ON bm.branch_id = e.branch_id
        LEFT JOIN hrms_ed_personal_details p ON p.eb_id = e.eb_id
        LEFT JOIN hrms_ed_official_details o ON o.eb_id = e.eb_id AND o.active = 1
        WHERE e.active = 1
          AND bm.co_id = :co_id
          AND (:branch_id IS NULL OR e.branch_id = :branch_id)
          AND (:from_date IS NULL OR e.tran_date >= :from_date)
          AND (:to_date IS NULL OR e.tran_date <= :to_date)
          AND (:search IS NULL
               OR o.emp_code LIKE :search
               OR CONCAT(IFNULL(p.first_name, ''), ' ', IFNULL(p.last_name, '')) LIKE :search)
        ORDER BY e.tran_date DESC, o.emp_code, e.tran_id
    """)


def get_electric_by_id_query():
    return text("""
        SELECT tran_id, tran_date, branch_id, eb_id, amount, remarks, active
        FROM electric_details
        WHERE tran_id = :record_id
    """)


def _duplicate_query():
    """Same employee already has an electric row for that date (ignoring one id)."""
    return text("""
        SELECT COUNT(*) AS cnt FROM electric_details
        WHERE active = 1
          AND eb_id = :eb_id
          AND tran_date = :tran_date
          AND (:record_id IS NULL OR tran_id <> :record_id)
    """)


# ─── Helpers ──────────────────────────────────────────────────────────────


def _branch_param(request: Request) -> int | None:
    raw = request.query_params.get("branch_id")
    return int(raw) if raw not in (None, "", "null") else None


def _parse_body(body: dict) -> dict:
    """Validate + normalise a create/edit payload into ElectricDetails columns."""
    raw_date = str(body.get("tran_date") or "").strip()
    if not raw_date:
        raise HTTPException(status_code=400, detail="tran_date is required")
    try:
        tran_date = date.fromisoformat(raw_date[:10])
    except ValueError:
        raise HTTPException(status_code=400, detail="tran_date must be YYYY-MM-DD")

    def _int(name):
        v = body.get(name)
        if v in (None, "", "null"):
            raise HTTPException(status_code=400, detail=f"{name} is required")
        try:
            return int(v)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail=f"{name} must be an integer")

    raw_amount = body.get("amount")
    if raw_amount in (None, ""):
        raise HTTPException(status_code=400, detail="amount is required")
    try:
        amount = float(raw_amount)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="amount must be a number")
    if amount <= 0:
        raise HTTPException(status_code=400, detail="amount must be greater than 0")

    return {
        "branch_id": _int("branch_id"),
        "tran_date": tran_date,
        "eb_id": _int("eb_id"),
        "amount": amount,
        "remarks": (str(body.get("remarks") or "").strip()[:255] or None),
    }


def _assert_not_duplicate(db: Session, values: dict, record_id: int | None) -> None:
    dup = db.execute(_duplicate_query(), {
        "eb_id": values["eb_id"],
        "tran_date": values["tran_date"],
        "record_id": record_id,
    }).fetchone()
    if dup and dup.cnt > 0:
        raise HTTPException(
            status_code=400,
            detail="This worker already has an electric entry for this date — edit it instead",
        )


# ─── Endpoints ────────────────────────────────────────────────────────────


@router.get("/electric_setup")
def electric_setup(
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
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_electric_table")
def get_electric_table(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Paginated list of electric entries for the selected company/branch."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        search = request.query_params.get("search")
        page = int(request.query_params.get("page", 1))
        limit = int(request.query_params.get("limit", 10))

        rows = db.execute(get_electric_list_query(), {
            "co_id": int(co_id),
            "branch_id": _branch_param(request),
            "from_date": request.query_params.get("from_date") or None,
            "to_date": request.query_params.get("to_date") or None,
            "search": f"%{search}%" if search else None,
        }).fetchall()
        all_data = []
        for row in rows:
            m = dict(row._mapping)
            m["emp_name"] = (m.get("emp_name") or "").strip()
            all_data.append(m)

        # ponytail: in-memory pagination like the sibling pages; SQL LIMIT if it grows
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


@router.get("/get_electric_by_id/{record_id}")
def get_electric_by_id(
    record_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        row = db.execute(get_electric_by_id_query(), {"record_id": record_id}).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Electric entry not found")
        return {"data": dict(row._mapping)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/electric_create")
def electric_create(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        values = _parse_body(parse_json_body(request))
        _assert_not_duplicate(db, values, None)

        record = ElectricDetails(**values, active=1)
        db.add(record)
        db.commit()
        db.refresh(record)
        return {
            "message": "Electric entry created successfully",
            "tran_id": record.tran_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/electric_edit/{record_id}")
def electric_edit(
    record_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        values = _parse_body(parse_json_body(request))
        existing = db.query(ElectricDetails).filter(
            ElectricDetails.tran_id == record_id,
        ).first()
        if not existing:
            raise HTTPException(status_code=404, detail="Electric entry not found")
        _assert_not_duplicate(db, values, record_id)

        for k, v in values.items():
            setattr(existing, k, v)
        db.commit()
        return {"message": "Electric entry updated successfully", "tran_id": record_id}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/electric_delete/{record_id}")
def electric_delete(
    record_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Soft-delete (active = 0), matching the list filter."""
    try:
        existing = db.query(ElectricDetails).filter(
            ElectricDetails.tran_id == record_id,
        ).first()
        if not existing:
            raise HTTPException(status_code=404, detail="Electric entry not found")
        existing.active = 0
        db.commit()
        return {"message": "Electric entry deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
