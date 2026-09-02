"""
Misc Earn / Extra Allowance master (misc_earn_mst).

One rule per branch + department (+ optional designation/occupation) + earn
type, straight from the mill's "EXTRA ALLOWANCES" sheet: an amount that is
paid per a block of hours, optionally scaled by a percentage (beam changes are
paid at 60% of total value / divisible hours). The per-hour rate is a stored
generated column in MySQL (amount / per_hrs * rate_pct / 100), so payroll can
read it directly and every row is guaranteed consistent with the formula.

Scoped by branch_id (dept_mst and designation_mst are branch-scoped); the
company filter goes through branch_mst.co_id.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session
from sqlalchemy.sql import text

from src.authorization.utils import get_current_user_with_refresh
from src.common.utils import parse_json_body
from src.config.db import get_tenant_db
from src.models.hrms import MiscEarnMst

router = APIRouter()

# ponytail: fixed list from the sheet; extend the tuple when a new allowance type appears.
EARN_TYPES = ("MISC EARN", "BEAM CHANGES", "OIL CHARGE")


# ─── SQL Queries ──────────────────────────────────────────────────────────


def get_misc_earn_list_query():
    return text("""
        SELECT
            m.misc_earn_id, m.branch_id, m.dept_id, d.dept_code, d.dept_desc,
            m.designation_id, g.desig, m.cata_id, cm.cata_code, cm.cata_desc,
            m.earn_type, m.amount, m.per_hrs,
            m.rate_pct, m.rate_per_hr, m.remarks, m.active
        FROM misc_earn_mst m
        INNER JOIN branch_mst bm ON bm.branch_id = m.branch_id
        LEFT JOIN dept_mst d ON d.dept_id = m.dept_id
        LEFT JOIN designation_mst g ON g.designation_id = m.designation_id
        LEFT JOIN category_mst cm ON cm.cata_id = m.cata_id
        WHERE m.active = 1
          AND bm.co_id = :co_id
          AND (:branch_id IS NULL OR m.branch_id = :branch_id)
          AND (:search IS NULL
               OR d.dept_desc LIKE :search
               OR d.dept_code LIKE :search
               OR g.desig LIKE :search
               OR cm.cata_desc LIKE :search
               OR m.earn_type LIKE :search)
        ORDER BY d.dept_code, g.desig, m.misc_earn_id
    """)


def get_misc_earn_by_id_query():
    return text("""
        SELECT misc_earn_id, branch_id, dept_id, designation_id, cata_id, earn_type,
               amount, per_hrs, rate_pct, rate_per_hr, remarks, active
        FROM misc_earn_mst
        WHERE misc_earn_id = :record_id
    """)


def get_depts_query():
    return text("""
        SELECT d.dept_id, d.dept_code, d.dept_desc
        FROM dept_mst d
        INNER JOIN branch_mst bm ON bm.branch_id = d.branch_id
        WHERE bm.co_id = :co_id
          AND (:branch_id IS NULL OR d.branch_id = :branch_id)
        ORDER BY d.dept_code, d.dept_desc
    """)


def get_designations_query():
    return text("""
        SELECT g.designation_id, g.dept_id, g.desig
        FROM designation_mst g
        INNER JOIN branch_mst bm ON bm.branch_id = g.branch_id
        WHERE g.active = 1
          AND bm.co_id = :co_id
          AND (:branch_id IS NULL OR g.branch_id = :branch_id)
        ORDER BY g.desig
    """)


def _duplicate_query():
    """Same branch/dept/designation/category/earn type already has an active rule (ignoring one id)."""
    return text("""
        SELECT COUNT(*) AS cnt FROM misc_earn_mst
        WHERE active = 1
          AND branch_id = :branch_id
          AND dept_id = :dept_id
          AND earn_type = :earn_type
          AND ((:designation_id IS NULL AND designation_id IS NULL)
               OR designation_id = :designation_id)
          AND ((:cata_id IS NULL AND cata_id IS NULL)
               OR cata_id = :cata_id)
          AND (:record_id IS NULL OR misc_earn_id <> :record_id)
    """)


def get_categories_query():
    return text("""
        SELECT cm.cata_id, cm.cata_code, cm.cata_desc
        FROM category_mst cm
        INNER JOIN branch_mst bm ON bm.branch_id = cm.branch_id
        WHERE bm.co_id = :co_id
          AND (:branch_id IS NULL OR cm.branch_id = :branch_id)
        ORDER BY cm.cata_code
    """)


# ─── Helpers ──────────────────────────────────────────────────────────────


def _branch_param(request: Request) -> int | None:
    raw = request.query_params.get("branch_id")
    return int(raw) if raw not in (None, "", "null") else None


def _num(body: dict, name: str, *, positive: bool = False) -> float:
    """Required numeric field; `positive` rejects 0 (per_hrs is a divisor)."""
    v = body.get(name)
    if v in (None, ""):
        raise HTTPException(status_code=400, detail=f"{name} is required")
    try:
        val = float(v)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"{name} must be a number")
    if val < 0 or (positive and val == 0):
        raise HTTPException(
            status_code=400,
            detail=f"{name} must be {'greater than 0' if positive else 'zero or more'}",
        )
    return val


def _int_or_none(body: dict, name: str) -> int | None:
    v = body.get(name)
    return int(v) if v not in (None, "", "null") else None


def _parse_body(body: dict) -> dict:
    """Validate + normalise a create/edit payload into MiscEarnMst columns."""
    branch_id = _int_or_none(body, "branch_id")
    dept_id = _int_or_none(body, "dept_id")
    if branch_id is None:
        raise HTTPException(status_code=400, detail="branch_id is required (select a branch)")
    if dept_id is None:
        raise HTTPException(status_code=400, detail="Department is required")
    earn_type = str(body.get("earn_type") or "").strip().upper()
    if earn_type not in EARN_TYPES:
        raise HTTPException(
            status_code=400, detail=f"earn_type must be one of {', '.join(EARN_TYPES)}",
        )
    remarks = str(body.get("remarks") or "").strip() or None
    return {
        "branch_id": branch_id,
        "dept_id": dept_id,
        "designation_id": _int_or_none(body, "designation_id"),
        "cata_id": _int_or_none(body, "cata_id"),
        "earn_type": earn_type,
        "amount": _num(body, "amount"),
        "per_hrs": _num(body, "per_hrs", positive=True),
        "rate_pct": _num(body, "rate_pct") if body.get("rate_pct") not in (None, "") else 100.0,
        "remarks": remarks[:255] if remarks else None,
    }


def _assert_not_duplicate(db: Session, values: dict, record_id: int | None) -> None:
    dup = db.execute(_duplicate_query(), {
        "branch_id": values["branch_id"],
        "dept_id": values["dept_id"],
        "designation_id": values["designation_id"],
        "cata_id": values["cata_id"],
        "earn_type": values["earn_type"],
        "record_id": record_id,
    }).fetchone()
    if dup and dup.cnt > 0:
        raise HTTPException(
            status_code=400,
            detail="A rule already exists for this department / occupation / category / earn type — edit it instead",
        )


# ─── Endpoints ────────────────────────────────────────────────────────────


@router.get("/misc_earn_setup")
def misc_earn_setup(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Dropdown options: departments, designations (with dept_id for cascading), earn types."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        params = {"co_id": int(co_id), "branch_id": _branch_param(request)}

        depts = db.execute(get_depts_query(), params).fetchall()
        desigs = db.execute(get_designations_query(), params).fetchall()
        cats = db.execute(get_categories_query(), params).fetchall()
        return {
            "data": {
                "depts": [
                    {"value": str(r.dept_id), "label": f"{r.dept_desc or ''} ({r.dept_code or ''})".strip()}
                    for r in depts
                ],
                "designations": [
                    {"value": str(r.designation_id), "label": r.desig or str(r.designation_id),
                     "dept_id": r.dept_id}
                    for r in desigs
                ],
                "categories": [
                    {"value": str(r.cata_id), "label": r.cata_desc or r.cata_code or str(r.cata_id)}
                    for r in cats
                ],
                "earn_types": [{"value": t, "label": t} for t in EARN_TYPES],
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_misc_earn_table")
def get_misc_earn_table(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Paginated list of misc earn rules for the selected company/branch."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        search = request.query_params.get("search")
        page = int(request.query_params.get("page", 1))
        limit = int(request.query_params.get("limit", 10))

        rows = db.execute(get_misc_earn_list_query(), {
            "co_id": int(co_id),
            "branch_id": _branch_param(request),
            "search": f"%{search}%" if search else None,
        }).fetchall()
        all_data = [dict(r._mapping) for r in rows]

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


@router.get("/get_misc_earn_by_id/{record_id}")
def get_misc_earn_by_id(
    record_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        row = db.execute(get_misc_earn_by_id_query(), {"record_id": record_id}).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Misc earn rule not found")
        return {"data": dict(row._mapping)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/misc_earn_create")
def misc_earn_create(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        values = _parse_body(parse_json_body(request))
        _assert_not_duplicate(db, values, None)

        record = MiscEarnMst(**values, active=1)
        db.add(record)
        db.commit()
        db.refresh(record)
        return {
            "message": "Misc earn rule created successfully",
            "misc_earn_id": record.misc_earn_id,
            "rate_per_hr": record.rate_per_hr,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/misc_earn_edit/{record_id}")
def misc_earn_edit(
    record_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        values = _parse_body(parse_json_body(request))
        existing = db.query(MiscEarnMst).filter(MiscEarnMst.misc_earn_id == record_id).first()
        if not existing:
            raise HTTPException(status_code=404, detail="Misc earn rule not found")
        _assert_not_duplicate(db, values, record_id)

        for k, v in values.items():
            setattr(existing, k, v)
        db.commit()
        return {"message": "Misc earn rule updated successfully", "misc_earn_id": record_id}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/misc_earn_delete/{record_id}")
def misc_earn_delete(
    record_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Soft-delete (active = 0), matching the list filter."""
    try:
        existing = db.query(MiscEarnMst).filter(MiscEarnMst.misc_earn_id == record_id).first()
        if not existing:
            raise HTTPException(status_code=404, detail="Misc earn rule not found")
        existing.active = 0
        db.commit()
        return {"message": "Misc earn rule deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
