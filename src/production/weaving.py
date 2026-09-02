"""
Weaving production entries (weaving_production) — production/weavingproduction.

One row per worker + date + shift + quality, straight from the mill's
"WEAVING PROD" sheets (C.NO., NAME, MC-1, MC-2, LINE NO., Q-CODE, QUALITY,
TYPE, WK HRS, PROD, RATE, VALUE/AMOUNT, PAYBLE AMT, SHIFT). A weaver runs a
pair of looms: machine_id = MC-1, machine_id2 = MC-2. The weaving looms and
Q-codes both live under dept_mst 'HESSIAN WEAVING' / 'SACKING WEAVING', and
that dept is the sheet's TYPE column (HESS / SACK).

The rate is NOT keyed in: it is resolved from the wages quality master
(tbl_nbcl_wages_quality_mst) for the selected quality and snapshotted on the
row; amount = rate * prod_qty and payable_amt = amount * 0.8 are stored
generated columns.

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
from src.models.hrms import WeavingProduction

router = APIRouter()


def _dept_type(dept_desc: str | None) -> str:
    """Sheet TYPE column from the quality/loom dept: HESS or SACK."""
    return "HESS" if (dept_desc or "").upper().startswith("HESSIAN") else "SACK"


# ─── SQL Queries ──────────────────────────────────────────────────────────


def get_weaving_prod_list_query():
    return text("""
        SELECT
            w.weaving_prod_id, w.branch_id, w.prod_date, w.shift,
            w.eb_id, o.emp_code,
            CONCAT(IFNULL(p.first_name, ''), ' ', IFNULL(p.middle_name, ''), ' ',
                   IFNULL(p.last_name, '')) AS emp_name,
            w.machine_id, mc1.machine_name AS machine1_name,
            w.machine_id2, mc2.machine_name AS machine2_name,
            w.line_no,
            w.quality_id, q.quality_code, q.quality_desc, d.dept_desc,
            w.wk_hrs, w.prod_qty, w.rate, w.amount, w.payable_amt,
            w.remarks, w.active
        FROM weaving_production w
        INNER JOIN branch_mst bm ON bm.branch_id = w.branch_id
        LEFT JOIN hrms_ed_personal_details p ON p.eb_id = w.eb_id
        LEFT JOIN hrms_ed_official_details o ON o.eb_id = w.eb_id AND o.active = 1
        LEFT JOIN machine_mst mc1 ON mc1.machine_id = w.machine_id
        LEFT JOIN machine_mst mc2 ON mc2.machine_id = w.machine_id2
        LEFT JOIN tbl_nbcl_wages_quality_mst q ON q.quality_id = w.quality_id
        LEFT JOIN dept_mst d ON d.dept_id = q.dept_id
        WHERE w.active = 1
          AND bm.co_id = :co_id
          AND (:branch_id IS NULL OR w.branch_id = :branch_id)
          AND (:from_date IS NULL OR w.prod_date >= :from_date)
          AND (:to_date IS NULL OR w.prod_date <= :to_date)
          AND (:search IS NULL
               OR o.emp_code LIKE :search
               OR CONCAT(IFNULL(p.first_name, ''), ' ', IFNULL(p.last_name, '')) LIKE :search
               OR mc1.machine_name LIKE :search
               OR mc2.machine_name LIKE :search
               OR q.quality_code LIKE :search
               OR q.quality_desc LIKE :search)
        ORDER BY w.prod_date DESC, o.emp_code, w.shift, w.weaving_prod_id
    """)


def get_weaving_prod_by_id_query():
    return text("""
        SELECT weaving_prod_id, branch_id, prod_date, shift, eb_id,
               machine_id, machine_id2, line_no, quality_id,
               wk_hrs, prod_qty, rate, amount, payable_amt, remarks, active
        FROM weaving_production
        WHERE weaving_prod_id = :record_id
    """)


def get_weaving_machines_query():
    return text("""
        SELECT mc.machine_id, mc.machine_name, d.dept_desc
        FROM machine_mst mc
        INNER JOIN dept_mst d ON d.dept_id = mc.dept_id
        WHERE mc.active = 1
          AND d.dept_desc IN ('HESSIAN WEAVING', 'SACKING WEAVING')
        ORDER BY mc.machine_name
    """)


def get_quality_options_query():
    return text("""
        SELECT q.quality_id, q.quality_code, q.quality_desc, q.quality_rate,
               d.dept_desc
        FROM tbl_nbcl_wages_quality_mst q
        INNER JOIN dept_mst d ON d.dept_id = q.dept_id
        WHERE q.active = 1
          AND d.dept_desc IN ('HESSIAN WEAVING', 'SACKING WEAVING')
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
        SELECT COUNT(*) AS cnt FROM weaving_production
        WHERE active = 1
          AND eb_id = :eb_id
          AND prod_date = :prod_date
          AND shift = :shift
          AND quality_id = :quality_id
          AND (:record_id IS NULL OR weaving_prod_id <> :record_id)
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


def _int_or_none(body: dict, name: str) -> int | None:
    v = body.get(name)
    if v in (None, "", "null"):
        return None
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
    """Validate + normalise a create/edit payload into WeavingProduction columns
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
        "machine_id2": _int_or_none(body, "machine_id2"),
        "line_no": (str(body.get("line_no") or "").strip()[:10] or None),
        "quality_id": _int(body, "quality_id"),
        "wk_hrs": _num_or_none(body, "wk_hrs"),
        "prod_qty": prod_qty,
        "remarks": (str(body.get("remarks") or "").strip()[:255] or None),
    }


def _resolve_rate(db: Session, quality_id: int) -> float:
    """Weaving rate as per the wages quality master — never trusted from the client."""
    row = db.execute(get_quality_rate_query(), {"quality_id": quality_id}).fetchone()
    if not row or row.quality_rate is None:
        raise HTTPException(status_code=400, detail="Selected weaving quality not found")
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


@router.get("/weaving_prod_setup")
def weaving_prod_setup(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Dropdown options: employees (company/branch scoped), shifts, the weaving
    looms and the weaving quality codes with their per-unit rate — looms and
    qualities both carry a HESS/SACK type derived from their dept."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        employees = db.execute(get_rate_employees_query(), {
            "co_id": int(co_id), "branch_id": _branch_param(request),
        }).fetchall()
        shifts = db.execute(get_rate_shifts_query()).fetchall()
        machines = db.execute(get_weaving_machines_query()).fetchall()
        qualities = db.execute(get_quality_options_query()).fetchall()

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
                    {
                        "value": str(r.machine_id),
                        "label": r.machine_name,
                        "machine_type": _dept_type(r.dept_desc),
                    }
                    for r in machines
                ],
                "qualities": [
                    {
                        "value": str(m["quality_id"]),
                        "label": f"{m['quality_code']} - {m['quality_desc'] or ''}".rstrip(" -"),
                        "quality_rate": float(m["quality_rate"]) if m["quality_rate"] is not None else None,
                        "quality_type": _dept_type(m["dept_desc"]),
                    }
                    for m in (dict(r._mapping) for r in qualities)
                ],
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_weaving_prod_table")
def get_weaving_prod_table(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Paginated list of weaving production entries for the selected company/branch."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        search = request.query_params.get("search")
        page = int(request.query_params.get("page", 1))
        limit = int(request.query_params.get("limit", 10))

        rows = db.execute(get_weaving_prod_list_query(), {
            "co_id": int(co_id),
            "branch_id": _branch_param(request),
            "from_date": request.query_params.get("from_date") or None,
            "to_date": request.query_params.get("to_date") or None,
            "search": f"%{search}%" if search else None,
        }).fetchall()
        all_data = []
        for r in rows:
            m = dict(r._mapping)
            m["quality_type"] = _dept_type(m.pop("dept_desc"))
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


@router.get("/get_weaving_prod_by_id/{record_id}")
def get_weaving_prod_by_id(
    record_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        row = db.execute(get_weaving_prod_by_id_query(), {"record_id": record_id}).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Weaving production entry not found")
        return {"data": dict(row._mapping)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/weaving_prod_create")
def weaving_prod_create(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        values = _parse_body(parse_json_body(request))
        _assert_not_duplicate(db, values, None)
        rate = _resolve_rate(db, values["quality_id"])

        record = WeavingProduction(**values, rate=rate, active=1)
        db.add(record)
        db.commit()
        db.refresh(record)
        return {
            "message": "Weaving production entry created successfully",
            "weaving_prod_id": record.weaving_prod_id,
            "rate": record.rate,
            "amount": record.amount,
            "payable_amt": record.payable_amt,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/weaving_prod_edit/{record_id}")
def weaving_prod_edit(
    record_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        values = _parse_body(parse_json_body(request))
        existing = db.query(WeavingProduction).filter(
            WeavingProduction.weaving_prod_id == record_id,
        ).first()
        if not existing:
            raise HTTPException(status_code=404, detail="Weaving production entry not found")
        _assert_not_duplicate(db, values, record_id)
        rate = _resolve_rate(db, values["quality_id"])

        for k, v in values.items():
            setattr(existing, k, v)
        existing.rate = rate
        db.commit()
        return {
            "message": "Weaving production entry updated successfully",
            "weaving_prod_id": record_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/weaving_prod_delete/{record_id}")
def weaving_prod_delete(
    record_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Soft-delete (active = 0), matching the list filter."""
    try:
        existing = db.query(WeavingProduction).filter(
            WeavingProduction.weaving_prod_id == record_id,
        ).first()
        if not existing:
            raise HTTPException(status_code=404, detail="Weaving production entry not found")
        existing.active = 0
        db.commit()
        return {"message": "Weaving production entry deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
