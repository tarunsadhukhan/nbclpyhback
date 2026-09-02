"""
Attendance Incentive master (atten_incentive_mst).

One rule per branch + employee category (category_mst), straight from the
mill's "ATTEN_INCENTIVE" sheet: an amount paid per a block of hours (Rs. 1 or
Rs. 20 per 8 hrs depending on category), payable once the worker reaches the
eligibility hours (96) in the fortnight. `working_includes` names the hour
buckets that count toward eligibility; `calc_on` names the buckets the
incentive is actually paid on. The per-hour rate is a stored generated column
in MySQL (amount / per_hrs), so payroll can read it directly.

Scoped by branch_id (category_mst is branch-scoped); the company filter goes
through branch_mst.co_id.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session
from sqlalchemy.sql import text

from src.authorization.utils import get_current_user_with_refresh
from src.common.utils import parse_json_body
from src.config.db import get_tenant_db
from src.models.hrms import AttenIncentiveMst

router = APIRouter()

DEFAULT_ELIGIBILITY_HRS = 96
DEFAULT_WORKING_INCLUDES = "WK HRS+NS HRS+HOLIDAY HRS+LEAVE HRS"
DEFAULT_CALC_ON = "WK HRS+NS HRS"


# ─── SQL Queries ──────────────────────────────────────────────────────────


def get_atten_incentive_list_query():
    return text("""
        SELECT
            m.atten_incentive_id, m.branch_id, m.cata_id, cm.cata_code, cm.cata_desc,
            m.amount, m.per_hrs, m.eligibility_hrs, m.working_includes, m.calc_on,
            m.rate_per_hr, m.remarks, m.active
        FROM atten_incentive_mst m
        INNER JOIN branch_mst bm ON bm.branch_id = m.branch_id
        LEFT JOIN category_mst cm ON cm.cata_id = m.cata_id
        WHERE m.active = 1
          AND bm.co_id = :co_id
          AND (:branch_id IS NULL OR m.branch_id = :branch_id)
          AND (:search IS NULL
               OR cm.cata_code LIKE :search
               OR cm.cata_desc LIKE :search)
        ORDER BY cm.cata_code, m.atten_incentive_id
    """)


def get_atten_incentive_by_id_query():
    return text("""
        SELECT atten_incentive_id, branch_id, cata_id, amount, per_hrs,
               eligibility_hrs, working_includes, calc_on, rate_per_hr, remarks, active
        FROM atten_incentive_mst
        WHERE atten_incentive_id = :record_id
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


def _duplicate_query():
    """Same branch/category already has an active rule (ignoring one id)."""
    return text("""
        SELECT COUNT(*) AS cnt FROM atten_incentive_mst
        WHERE active = 1
          AND branch_id = :branch_id
          AND cata_id = :cata_id
          AND (:record_id IS NULL OR atten_incentive_id <> :record_id)
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


def _text(body: dict, name: str, default: str, limit: int = 100) -> str:
    v = str(body.get(name) or "").strip()
    return (v or default)[:limit]


def _parse_body(body: dict) -> dict:
    """Validate + normalise a create/edit payload into AttenIncentiveMst columns."""
    branch_id = _int_or_none(body, "branch_id")
    cata_id = _int_or_none(body, "cata_id")
    if branch_id is None:
        raise HTTPException(status_code=400, detail="branch_id is required (select a branch)")
    if cata_id is None:
        raise HTTPException(status_code=400, detail="Employee category is required")
    remarks = str(body.get("remarks") or "").strip() or None
    return {
        "branch_id": branch_id,
        "cata_id": cata_id,
        "amount": _num(body, "amount"),
        "per_hrs": _num(body, "per_hrs", positive=True),
        "eligibility_hrs": (
            _num(body, "eligibility_hrs")
            if body.get("eligibility_hrs") not in (None, "")
            else float(DEFAULT_ELIGIBILITY_HRS)
        ),
        "working_includes": _text(body, "working_includes", DEFAULT_WORKING_INCLUDES),
        "calc_on": _text(body, "calc_on", DEFAULT_CALC_ON),
        "remarks": remarks[:255] if remarks else None,
    }


def _assert_not_duplicate(db: Session, values: dict, record_id: int | None) -> None:
    dup = db.execute(_duplicate_query(), {
        "branch_id": values["branch_id"],
        "cata_id": values["cata_id"],
        "record_id": record_id,
    }).fetchone()
    if dup and dup.cnt > 0:
        raise HTTPException(
            status_code=400,
            detail="A rule already exists for this employee category — edit it instead",
        )


# ─── Endpoints ────────────────────────────────────────────────────────────


@router.get("/atten_incentive_setup")
def atten_incentive_setup(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Dropdown options: employee categories for the selected company/branch."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        cats = db.execute(get_categories_query(), {
            "co_id": int(co_id), "branch_id": _branch_param(request),
        }).fetchall()
        return {
            "data": {
                "categories": [
                    {"value": str(r.cata_id), "label": r.cata_desc or r.cata_code or str(r.cata_id)}
                    for r in cats
                ],
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_atten_incentive_table")
def get_atten_incentive_table(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Paginated list of attendance incentive rules for the selected company/branch."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        search = request.query_params.get("search")
        page = int(request.query_params.get("page", 1))
        limit = int(request.query_params.get("limit", 10))

        rows = db.execute(get_atten_incentive_list_query(), {
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


@router.get("/get_atten_incentive_by_id/{record_id}")
def get_atten_incentive_by_id(
    record_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        row = db.execute(get_atten_incentive_by_id_query(), {"record_id": record_id}).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Attendance incentive rule not found")
        return {"data": dict(row._mapping)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/atten_incentive_create")
def atten_incentive_create(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        values = _parse_body(parse_json_body(request))
        _assert_not_duplicate(db, values, None)

        record = AttenIncentiveMst(**values, active=1)
        db.add(record)
        db.commit()
        db.refresh(record)
        return {
            "message": "Attendance incentive rule created successfully",
            "atten_incentive_id": record.atten_incentive_id,
            "rate_per_hr": record.rate_per_hr,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/atten_incentive_edit/{record_id}")
def atten_incentive_edit(
    record_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        values = _parse_body(parse_json_body(request))
        existing = db.query(AttenIncentiveMst).filter(
            AttenIncentiveMst.atten_incentive_id == record_id,
        ).first()
        if not existing:
            raise HTTPException(status_code=404, detail="Attendance incentive rule not found")
        _assert_not_duplicate(db, values, record_id)

        for k, v in values.items():
            setattr(existing, k, v)
        db.commit()
        return {
            "message": "Attendance incentive rule updated successfully",
            "atten_incentive_id": record_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/atten_incentive_delete/{record_id}")
def atten_incentive_delete(
    record_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Soft-delete (active = 0), matching the list filter."""
    try:
        existing = db.query(AttenIncentiveMst).filter(
            AttenIncentiveMst.atten_incentive_id == record_id,
        ).first()
        if not existing:
            raise HTTPException(status_code=404, detail="Attendance incentive rule not found")
        existing.active = 0
        db.commit()
        return {"message": "Attendance incentive rule deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
