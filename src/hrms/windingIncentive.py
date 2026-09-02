"""
Winding Incentive master (winding_incentive_mst).

One row per winding quality, straight from the mill's "WINDING INCENTIVE"
sheet: warp qualities carry a flat incentive amount per eligibility hours
(Rs. 59 or 40 per 96 hrs); weft qualities carry one row per production slab
(bundles per 8 hrs) with the grist range the slab applies to. The per-hour
rate is a stored generated column in MySQL (incentive_amt / eligibility_hrs)
— winding production entries snapshot it as their rate.

Tenant-wide master (no co_id/branch_id), like the wages quality master.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session
from sqlalchemy.sql import text

from src.authorization.utils import get_current_user_with_refresh
from src.common.utils import parse_json_body
from src.config.db import get_tenant_db
from src.models.hrms import WindingIncentiveMst

router = APIRouter()

DEFAULT_ELIGIBILITY_HRS = 96


# ─── SQL Queries ──────────────────────────────────────────────────────────


def get_winding_incentive_list_query():
    return text("""
        SELECT winding_incentive_id, quality_code, quality_name, inc_code,
               grist_from, grist_to, prod_from, prod_to,
               incentive_amt, eligibility_hrs, unit, rate_per_hr, remarks, active
        FROM winding_incentive_mst
        WHERE active = 1
          AND (:search IS NULL
               OR quality_code LIKE :search
               OR quality_name LIKE :search
               OR inc_code LIKE :search)
        ORDER BY quality_code, prod_from, winding_incentive_id
    """)


def get_winding_incentive_by_id_query():
    return text("""
        SELECT winding_incentive_id, quality_code, quality_name, inc_code,
               grist_from, grist_to, prod_from, prod_to,
               incentive_amt, eligibility_hrs, unit, rate_per_hr, remarks, active
        FROM winding_incentive_mst
        WHERE winding_incentive_id = :record_id
    """)


def _duplicate_query():
    """Same quality + slab already has an active row (ignoring one id)."""
    return text("""
        SELECT COUNT(*) AS cnt FROM winding_incentive_mst
        WHERE active = 1
          AND quality_code = :quality_code
          AND (prod_from <=> :prod_from)
          AND (:record_id IS NULL OR winding_incentive_id <> :record_id)
    """)


# ─── Helpers ──────────────────────────────────────────────────────────────


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
    """Validate + normalise a create/edit payload into WindingIncentiveMst columns."""
    quality_code = str(body.get("quality_code") or "").strip()
    if not quality_code:
        raise HTTPException(status_code=400, detail="Quality code is required")
    if len(quality_code) > 10:
        raise HTTPException(status_code=400, detail="Quality code cannot exceed 10 characters")

    quality_name = str(body.get("quality_name") or "").strip()
    if not quality_name:
        raise HTTPException(status_code=400, detail="Quality name is required")
    if len(quality_name) > 100:
        raise HTTPException(status_code=400, detail="Quality name cannot exceed 100 characters")

    incentive_amt = _num_or_none(body, "incentive_amt")
    if incentive_amt is None:
        raise HTTPException(status_code=400, detail="incentive_amt is required")

    eligibility_hrs = _num_or_none(body, "eligibility_hrs")
    if eligibility_hrs is None:
        eligibility_hrs = float(DEFAULT_ELIGIBILITY_HRS)
    if eligibility_hrs == 0:
        raise HTTPException(status_code=400, detail="eligibility_hrs must be greater than 0")

    values = {
        "quality_code": quality_code,
        "quality_name": quality_name,
        "inc_code": (str(body.get("inc_code") or "").strip() or None),
        "grist_from": _num_or_none(body, "grist_from"),
        "grist_to": _num_or_none(body, "grist_to"),
        "prod_from": _num_or_none(body, "prod_from"),
        "prod_to": _num_or_none(body, "prod_to"),
        "incentive_amt": incentive_amt,
        "eligibility_hrs": eligibility_hrs,
        "unit": (str(body.get("unit") or "").strip().upper() or "KG")[:10],
        "remarks": (str(body.get("remarks") or "").strip()[:255] or None),
    }
    for lo, hi in (("grist_from", "grist_to"), ("prod_from", "prod_to")):
        if values[lo] is not None and values[hi] is not None and values[lo] > values[hi]:
            raise HTTPException(status_code=400, detail=f"{lo} cannot be greater than {hi}")
    return values


def _assert_not_duplicate(db: Session, values: dict, record_id: int | None) -> None:
    dup = db.execute(_duplicate_query(), {
        "quality_code": values["quality_code"],
        "prod_from": values["prod_from"],
        "record_id": record_id,
    }).fetchone()
    if dup and dup.cnt > 0:
        raise HTTPException(
            status_code=400,
            detail="An incentive row already exists for this quality/slab — edit it instead",
        )


# ─── Endpoints ────────────────────────────────────────────────────────────


@router.get("/get_winding_incentive_table")
def get_winding_incentive_table(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Paginated list of winding incentive scheme rows."""
    try:
        search = request.query_params.get("search")
        page = int(request.query_params.get("page", 1))
        limit = int(request.query_params.get("limit", 10))

        rows = db.execute(get_winding_incentive_list_query(), {
            "search": f"%{search}%" if search else None,
        }).fetchall()
        all_data = [dict(r._mapping) for r in rows]

        # ponytail: in-memory pagination like the sibling masters; SQL LIMIT if it grows
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


@router.get("/get_winding_incentive_by_id/{record_id}")
def get_winding_incentive_by_id(
    record_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        row = db.execute(get_winding_incentive_by_id_query(), {"record_id": record_id}).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Winding incentive row not found")
        return {"data": dict(row._mapping)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/winding_incentive_create")
def winding_incentive_create(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        values = _parse_body(parse_json_body(request))
        _assert_not_duplicate(db, values, None)

        record = WindingIncentiveMst(**values, active=1)
        db.add(record)
        db.commit()
        db.refresh(record)
        return {
            "message": "Winding incentive row created successfully",
            "winding_incentive_id": record.winding_incentive_id,
            "rate_per_hr": record.rate_per_hr,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/winding_incentive_edit/{record_id}")
def winding_incentive_edit(
    record_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        values = _parse_body(parse_json_body(request))
        existing = db.query(WindingIncentiveMst).filter(
            WindingIncentiveMst.winding_incentive_id == record_id,
        ).first()
        if not existing:
            raise HTTPException(status_code=404, detail="Winding incentive row not found")
        _assert_not_duplicate(db, values, record_id)

        for k, v in values.items():
            setattr(existing, k, v)
        db.commit()
        return {
            "message": "Winding incentive row updated successfully",
            "winding_incentive_id": record_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/winding_incentive_delete/{record_id}")
def winding_incentive_delete(
    record_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Soft-delete (active = 0), matching the list filter."""
    try:
        existing = db.query(WindingIncentiveMst).filter(
            WindingIncentiveMst.winding_incentive_id == record_id,
        ).first()
        if not existing:
            raise HTTPException(status_code=404, detail="Winding incentive row not found")
        existing.active = 0
        db.commit()
        return {"message": "Winding incentive row deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
