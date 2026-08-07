"""
Morrah Weight QC API endpoints.
Allows QC inspectors to record 10 weight samples per jute Morrah batch,
computes statistical analysis and quality categorization.
"""

from fastapi import Depends, Request, HTTPException, APIRouter
from pydantic import BaseModel
from typing import List, Optional
import logging
import json
import statistics
from sqlalchemy.orm import Session

from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.juteSQC.query import (
    get_morrah_wt_table_query,
    get_morrah_wt_table_count_query,
    get_morrah_wt_by_id_query,
    get_morrah_wt_departments_query,
    get_morrah_wt_jute_qualities_query,
)
from src.models.jute import JuteSqcMorrahWt

logger = logging.getLogger(__name__)

router = APIRouter()

# Constants
STANDARD_MIN_WEIGHT = 1200
STANDARD_MAX_WEIGHT = 1400
SAMPLE_SIZE = 10


class MorrahWeightCreateRequest(BaseModel):
    co_id: int
    branch_id: int
    entry_date: str
    inspector_name: Optional[str] = None
    dept_id: Optional[int] = None
    item_id: Optional[int] = None
    trolley_no: Optional[str] = None
    avg_mr_pct: Optional[float] = None
    weights: List[int]


def compute_morrah_stats(weights: list[int]) -> dict:
    """Compute statistical analysis and quality categorization for morrah weight readings."""
    avg_weight = sum(weights) / len(weights)
    max_weight = max(weights)
    min_weight = min(weights)
    weight_range = max_weight - min_weight
    std_dev = statistics.stdev(weights) if len(weights) > 1 else 0.0
    cv_pct = (std_dev / avg_weight) * 100 if avg_weight > 0 else 0.0

    count_lt = sum(1 for w in weights if w < STANDARD_MIN_WEIGHT)
    count_ok = sum(1 for w in weights if STANDARD_MIN_WEIGHT <= w <= STANDARD_MAX_WEIGHT)
    count_hy = sum(1 for w in weights if w > STANDARD_MAX_WEIGHT)

    return {
        "calc_avg_weight": round(avg_weight, 2),
        "calc_max_weight": max_weight,
        "calc_min_weight": min_weight,
        "calc_range": weight_range,
        "calc_cv_pct": round(cv_pct, 2),
        "count_lt": count_lt,
        "count_ok": count_ok,
        "count_hy": count_hy,
    }


@router.get("/get_morrah_wt_create_setup")
def get_morrah_wt_create_setup(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        branch_id = request.query_params.get("branch_id")
        if not branch_id:
            raise HTTPException(status_code=400, detail="branch_id is required")

        dept_result = db.execute(
            get_morrah_wt_departments_query(),
            {"branch_id": int(branch_id)},
        ).fetchall()
        departments = [dict(r._mapping) for r in dept_result]

        quality_result = db.execute(
            get_morrah_wt_jute_qualities_query(),
            {"co_id": int(co_id)},
        ).fetchall()
        jute_qualities = [dict(r._mapping) for r in quality_result]

        return {
            "data": {
                "departments": departments,
                "jute_qualities": jute_qualities,
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching morrah weight create setup")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/create_morrah_wt")
def create_morrah_wt(
    request: Request,
    body: MorrahWeightCreateRequest,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        if len(body.weights) != SAMPLE_SIZE:
            raise HTTPException(
                status_code=400,
                detail=f"Exactly {SAMPLE_SIZE} weight readings are required, got {len(body.weights)}",
            )

        if any(w <= 0 for w in body.weights):
            raise HTTPException(status_code=400, detail="All weights must be positive integers")

        stats = compute_morrah_stats(body.weights)

        record = JuteSqcMorrahWt(
            co_id=body.co_id,
            branch_id=body.branch_id,
            entry_date=body.entry_date,
            inspector_name=body.inspector_name,
            dept_id=body.dept_id,
            item_id=body.item_id,
            trolley_no=body.trolley_no,
            avg_mr_pct=body.avg_mr_pct,
            weights=json.dumps(body.weights),
            calc_avg_weight=stats["calc_avg_weight"],
            calc_max_weight=stats["calc_max_weight"],
            calc_min_weight=stats["calc_min_weight"],
            calc_range=stats["calc_range"],
            calc_cv_pct=stats["calc_cv_pct"],
            count_lt=stats["count_lt"],
            count_ok=stats["count_ok"],
            count_hy=stats["count_hy"],
            updated_by=token_data.get("user_id"),
        )

        db.add(record)
        db.commit()
        db.refresh(record)

        return {
            "message": "Morrah weight QC log created successfully",
            "morrah_wt_id": record.morrah_wt_id,
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error creating morrah weight QC log")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_morrah_wt_table")
def get_morrah_wt_table(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        page = max(1, int(request.query_params.get("page", "1")))
        limit = max(1, min(100, int(request.query_params.get("limit", "10"))))
        offset = (page - 1) * limit
        search = request.query_params.get("search")

        params = {
            "co_id": int(co_id),
            "limit": limit,
            "offset": offset,
        }
        if search:
            params["search"] = f"%{search}%"

        count_query = get_morrah_wt_table_count_query(search=search)
        total_row = db.execute(count_query, params).fetchone()
        total = total_row.total if total_row else 0

        data_query = get_morrah_wt_table_query(search=search)
        result = db.execute(data_query, params).fetchall()
        rows = [dict(r._mapping) for r in result]

        return {"data": rows, "total": total, "page": page, "page_size": limit}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching morrah weight table")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_morrah_wt_by_id")
def get_morrah_wt_by_id(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        morrah_wt_id = request.query_params.get("id")
        if not morrah_wt_id:
            raise HTTPException(status_code=400, detail="id is required")

        query = get_morrah_wt_by_id_query()
        result = db.execute(query, {"morrah_wt_id": int(morrah_wt_id)}).fetchone()

        if not result:
            raise HTTPException(status_code=404, detail="Record not found")

        row = dict(result._mapping)
        if row.get("weights") and isinstance(row["weights"], str):
            row["weights"] = json.loads(row["weights"])

        return {"data": row}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching morrah weight by id")
        raise HTTPException(status_code=500, detail=str(e))
