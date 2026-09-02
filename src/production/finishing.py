"""
Finishing (sewing) production entries (finishing_production) —
production/finishingproduction.

One row per worker + date + shift + quality, straight from the mill's
"SEWING" sheets (ECODE, ENAME, MC NAME, Q-CODE, TYPE, WK HRS, PROD, RATE,
AMT, SHIFT). The sheet's HIRAKOL / HEMMING sections are just machine groups
(HK% / HM% machines) — machines and Q-codes both live under dept_mst
'SEWING'.

The rate is NOT keyed in: it is resolved from the wages quality master
(tbl_nbcl_wages_quality_mst) for the selected quality and snapshotted on the
row; amount = rate * prod_qty is a stored generated column.

Rows are scoped by branch_id (company filter via branch_mst.co_id); the
employee dropdown reuses the HRMS employee query.
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session
from sqlalchemy.sql import text

from src.authorization.utils import get_current_user_with_refresh
from src.common.utils import parse_json_body
from src.config.db import get_tenant_db
from src.hrms.outsiderRate import get_rate_shifts_query
from src.hrms.workerRate import get_rate_employees_query
from src.models.hrms import FinishingProduction

router = APIRouter()

_FINISHING_DEPT = "SEWING"


# ─── SQL Queries ──────────────────────────────────────────────────────────


def get_finishing_prod_list_query():
    return text("""
        SELECT
            f.finishing_prod_id, f.branch_id, f.prod_date, f.shift,
            f.eb_id, o.emp_code,
            CONCAT(IFNULL(p.first_name, ''), ' ', IFNULL(p.middle_name, ''), ' ',
                   IFNULL(p.last_name, '')) AS emp_name,
            f.machine_id, mc.machine_name,
            f.quality_id, q.quality_code, q.quality_desc,
            f.wk_hrs, f.prod_qty, f.rate, f.amount, f.remarks, f.active
        FROM finishing_production f
        INNER JOIN branch_mst bm ON bm.branch_id = f.branch_id
        LEFT JOIN hrms_ed_personal_details p ON p.eb_id = f.eb_id
        LEFT JOIN hrms_ed_official_details o ON o.eb_id = f.eb_id AND o.active = 1
        LEFT JOIN machine_mst mc ON mc.machine_id = f.machine_id
        LEFT JOIN tbl_nbcl_wages_quality_mst q ON q.quality_id = f.quality_id
        WHERE f.active = 1
          AND bm.co_id = :co_id
          AND (:branch_id IS NULL OR f.branch_id = :branch_id)
          AND (:from_date IS NULL OR f.prod_date >= :from_date)
          AND (:to_date IS NULL OR f.prod_date <= :to_date)
          AND (:search IS NULL
               OR o.emp_code LIKE :search
               OR CONCAT(IFNULL(p.first_name, ''), ' ', IFNULL(p.last_name, '')) LIKE :search
               OR mc.machine_name LIKE :search
               OR q.quality_code LIKE :search
               OR q.quality_desc LIKE :search)
        ORDER BY f.prod_date DESC, o.emp_code, f.shift, f.finishing_prod_id
    """)


def get_finishing_prod_by_id_query():
    return text("""
        SELECT finishing_prod_id, branch_id, prod_date, shift, eb_id,
               machine_id, quality_id, wk_hrs, prod_qty, rate, amount,
               remarks, active
        FROM finishing_production
        WHERE finishing_prod_id = :record_id
    """)


def get_finishing_machines_query():
    return text("""
        SELECT mc.machine_id, mc.machine_name
        FROM machine_mst mc
        INNER JOIN dept_mst d ON d.dept_id = mc.dept_id
        WHERE mc.active = 1 AND d.dept_desc = :dept_desc
        ORDER BY mc.machine_name
    """)


def get_quality_options_query():
    return text("""
        SELECT q.quality_id, q.quality_code, q.quality_desc, q.quality_rate
        FROM tbl_nbcl_wages_quality_mst q
        INNER JOIN dept_mst d ON d.dept_id = q.dept_id
        WHERE q.active = 1 AND d.dept_desc = :dept_desc
        ORDER BY q.quality_code
    """)


def get_quality_rate_query():
    return text("""
        SELECT quality_rate FROM tbl_nbcl_wages_quality_mst
        WHERE quality_id = :quality_id AND active = 1
    """)


def _duplicate_query():
    """Same worker + date + shift + quality already entered (ignoring one id)."""
    return text("""
        SELECT COUNT(*) AS cnt FROM finishing_production
        WHERE active = 1
          AND eb_id = :eb_id
          AND prod_date = :prod_date
          AND shift = :shift
          AND quality_id = :quality_id
          AND (:record_id IS NULL OR finishing_prod_id <> :record_id)
    """)


# ─── Helpers ──────────────────────────────────────────────────────────────


def _branch_param(request: Request) -> int | None:
    raw = request.query_params.get("branch_id")
    return int(raw) if raw not in (None, "", "null") else None


def _int(body: dict, name: str) -> int:
    v = body.get(name)
    if v in (None, "", "null"):
        raise HTTPException(status_code=400, detail=f"{name} is required")
    try:
        return int(v)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"{name} must be an integer")


def _num_or_none(body: dict, name: str) -> float | None:
    v = body.get(name)
    if v in (None, ""):
        return None
    try:
        val = float(v)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"{name} must be a number")
    if val < 0:
        raise HTTPException(status_code=400, detail=f"{name} must be zero or more")
    return val


def _parse_body(body: dict) -> dict:
    """Validate + normalise a create/edit payload into FinishingProduction columns
    (everything except rate, which is resolved from the wages quality master)."""
    raw_date = str(body.get("prod_date") or "").strip()
    if not raw_date:
        raise HTTPException(status_code=400, detail="prod_date is required")
    try:
        prod_date = date.fromisoformat(raw_date[:10])
    except ValueError:
        raise HTTPException(status_code=400, detail="prod_date must be YYYY-MM-DD")

    prod_qty = _num_or_none(body, "prod_qty")
    if not prod_qty:
        raise HTTPException(status_code=400, detail="prod_qty must be greater than 0")

    return {
        "branch_id": _int(body, "branch_id"),
        "prod_date": prod_date,
        "shift": (str(body.get("shift") or "").strip().upper() or "A")[:5],
        "eb_id": _int(body, "eb_id"),
        "machine_id": _int(body, "machine_id"),
        "quality_id": _int(body, "quality_id"),
        "wk_hrs": _num_or_none(body, "wk_hrs"),
        "prod_qty": prod_qty,
        "remarks": (str(body.get("remarks") or "").strip()[:255] or None),
    }


def _resolve_rate(db: Session, quality_id: int) -> float:
    """Sewing rate as per the wages quality master — never trusted from the client."""
    row = db.execute(get_quality_rate_query(), {"quality_id": quality_id}).fetchone()
    if not row or row.quality_rate is None:
        raise HTTPException(status_code=400, detail="Selected sewing quality not found")
    return float(row.quality_rate)


def _assert_not_duplicate(db: Session, values: dict, record_id: int | None) -> None:
    dup = db.execute(_duplicate_query(), {
        "eb_id": values["eb_id"],
        "prod_date": values["prod_date"],
        "shift": values["shift"],
        "quality_id": values["quality_id"],
        "record_id": record_id,
    }).fetchone()
    if dup and dup.cnt > 0:
        raise HTTPException(
            status_code=400,
            detail="This worker already has an entry for this date, shift and quality — edit it instead",
        )


# ─── Endpoints ────────────────────────────────────────────────────────────


@router.get("/finishing_prod_setup")
def finishing_prod_setup(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Dropdown options: employees (company/branch scoped), shifts, the sewing
    machines (hirakol HK% / hemming HM%) and the sewing quality codes with
    their per-unit rate."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        employees = db.execute(get_rate_employees_query(), {
            "co_id": int(co_id), "branch_id": _branch_param(request),
        }).fetchall()
        shifts = db.execute(get_rate_shifts_query()).fetchall()
        machines = db.execute(get_finishing_machines_query(), {
            "dept_desc": _FINISHING_DEPT,
        }).fetchall()
        qualities = db.execute(get_quality_options_query(), {
            "dept_desc": _FINISHING_DEPT,
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
                "shifts": [
                    {"value": r.spell_name, "label": r.spell_name} for r in shifts
                ],
                "machines": [
                    {"value": str(r.machine_id), "label": r.machine_name}
                    for r in machines
                ],
                "qualities": [
                    {
                        "value": str(m["quality_id"]),
                        "label": f"{m['quality_code']} - {m['quality_desc'] or ''}".rstrip(" -"),
                        "quality_rate": float(m["quality_rate"]) if m["quality_rate"] is not None else None,
                    }
                    for m in (dict(r._mapping) for r in qualities)
                ],
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_finishing_prod_table")
def get_finishing_prod_table(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Paginated list of finishing production entries for the selected company/branch."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        search = request.query_params.get("search")
        page = int(request.query_params.get("page", 1))
        limit = int(request.query_params.get("limit", 10))

        rows = db.execute(get_finishing_prod_list_query(), {
            "co_id": int(co_id),
            "branch_id": _branch_param(request),
            "from_date": request.query_params.get("from_date") or None,
            "to_date": request.query_params.get("to_date") or None,
            "search": f"%{search}%" if search else None,
        }).fetchall()
        all_data = [dict(r._mapping) for r in rows]

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


@router.get("/get_finishing_prod_by_id/{record_id}")
def get_finishing_prod_by_id(
    record_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        row = db.execute(get_finishing_prod_by_id_query(), {"record_id": record_id}).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Finishing production entry not found")
        return {"data": dict(row._mapping)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/finishing_prod_create")
def finishing_prod_create(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        values = _parse_body(parse_json_body(request))
        _assert_not_duplicate(db, values, None)
        rate = _resolve_rate(db, values["quality_id"])

        record = FinishingProduction(**values, rate=rate, active=1)
        db.add(record)
        db.commit()
        db.refresh(record)
        return {
            "message": "Finishing production entry created successfully",
            "finishing_prod_id": record.finishing_prod_id,
            "rate": record.rate,
            "amount": record.amount,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/finishing_prod_edit/{record_id}")
def finishing_prod_edit(
    record_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        values = _parse_body(parse_json_body(request))
        existing = db.query(FinishingProduction).filter(
            FinishingProduction.finishing_prod_id == record_id,
        ).first()
        if not existing:
            raise HTTPException(status_code=404, detail="Finishing production entry not found")
        _assert_not_duplicate(db, values, record_id)
        rate = _resolve_rate(db, values["quality_id"])

        for k, v in values.items():
            setattr(existing, k, v)
        existing.rate = rate
        db.commit()
        return {
            "message": "Finishing production entry updated successfully",
            "finishing_prod_id": record_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/finishing_prod_delete/{record_id}")
def finishing_prod_delete(
    record_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Soft-delete (active = 0), matching the list filter."""
    try:
        existing = db.query(FinishingProduction).filter(
            FinishingProduction.finishing_prod_id == record_id,
        ).first()
        if not existing:
            raise HTTPException(status_code=404, detail="Finishing production entry not found")
        existing.active = 0
        db.commit()
        return {"message": "Finishing production entry deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
