"""
R-08-20 Cutting Length QC API endpoints.

Daily cut-piece length consistency. ONE save = ONE date's reading-set: a flat header
(entry_date, optional cloth quality, std_length) plus EXACTLY 20 cut-length readings
(inches) stored as a JSON-string array (morrah pattern, single flat table — NO detail
table). avg = mean(20); stdev = SAMPLE stdev (n-1, statistics.stdev); cv_pct =
stdev/avg*100; deviation = avg - std_length. No MR correction, no pass/fail band. All
stats are computed server-side at save (authoritative) and stored.

Optional cloth-quality link = JUTE CLOTH items (item_type_id=5), reusing the beaming
cloth picker. std_length is entered on the form (prefilled 78, editable, snapshotted).
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
from src.juteSQC.constants import (
    CUTTING_LENGTH_READINGS,
    CUTTING_LENGTH_DEFAULT_STD,
)
from src.juteSQC.query import (
    get_cutting_length_table_query,
    get_cutting_length_table_count_query,
    get_cutting_length_by_date_query,
    get_cutting_length_by_id_query,
    soft_delete_cutting_length_query,
)
from src.juteProduction.beaming_query import get_beaming_cloth_items_query
from src.models.jute import JuteSqcCuttingLength

logger = logging.getLogger(__name__)

router = APIRouter()


class CuttingLengthCreateRequest(BaseModel):
    co_id: int
    branch_id: Optional[int] = None
    entry_date: str
    item_id: Optional[int] = None
    std_length: float
    readings: List[float]


class CuttingLengthDeleteRequest(BaseModel):
    cutting_length_id: int
    co_id: int


def compute_cutting_length_stats(readings: List[float], std_length: float) -> dict:
    """avg = mean(readings); stdev = SAMPLE stdev (n-1); cv_pct = stdev/avg*100;
    deviation = avg - std_length. stdev needs >= 2 readings (always 20 here)."""
    avg = sum(readings) / len(readings)
    stdev = statistics.stdev(readings) if len(readings) > 1 else 0.0
    cv_pct = round(stdev / avg * 100, 4) if avg > 0 else 0.0
    return {
        "calc_avg": round(avg, 3),
        "calc_stdev": round(stdev, 4),
        "calc_cv_pct": cv_pct,
        "calc_deviation": round(avg - std_length, 3),
    }


@router.get("/cutting_length_create_setup")
def cutting_length_create_setup(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Cloth-quality picker (JUTE CLOTH, item_type_id=5) plus the prefilled std length
    and the fixed readings count for the entry form."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        # branch_id is accepted for parity with siblings; the cloth picker is co-scoped only.
        cloth_rows = db.execute(
            get_beaming_cloth_items_query(),
            {"co_id": int(co_id)},
        ).fetchall()
        cloth_qualities = [
            {
                "item_id": r._mapping["item_id"],
                "item_code": r._mapping["item_code"],
                "item_name": r._mapping["item_name"],
            }
            for r in cloth_rows
        ]

        return {
            "data": {
                "cloth_qualities": cloth_qualities,
                "default_std_length": CUTTING_LENGTH_DEFAULT_STD,
                "readings_count": CUTTING_LENGTH_READINGS,
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching cutting length create setup")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/create_cutting_length")
def create_cutting_length(
    body: CuttingLengthCreateRequest,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Save ONE reading-set (exactly 20 cut-length readings). std_length snapshotted;
    avg / sample stdev / cv_pct / deviation computed server-side and stored."""
    try:
        if len(body.readings) != CUTTING_LENGTH_READINGS:
            raise HTTPException(
                status_code=400,
                detail=f"Exactly {CUTTING_LENGTH_READINGS} readings are required, got {len(body.readings)}",
            )

        if any(r <= 0 for r in body.readings):
            raise HTTPException(status_code=400, detail="All readings must be positive numbers")

        if body.std_length <= 0:
            raise HTTPException(status_code=400, detail="std_length must be positive")

        stats = compute_cutting_length_stats(body.readings, body.std_length)

        record = JuteSqcCuttingLength(
            co_id=body.co_id,
            branch_id=body.branch_id,
            entry_date=body.entry_date,
            item_id=body.item_id,
            std_length=body.std_length,
            readings=json.dumps(body.readings),
            calc_avg=stats["calc_avg"],
            calc_stdev=stats["calc_stdev"],
            calc_cv_pct=stats["calc_cv_pct"],
            calc_deviation=stats["calc_deviation"],
            updated_by=token_data.get("user_id"),
        )

        db.add(record)
        db.commit()
        db.refresh(record)

        return {
            "message": "Cutting length QC log created successfully",
            "cutting_length_id": record.cutting_length_id,
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error creating cutting length QC log")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_cutting_length_by_date")
def get_cutting_length_by_date(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """All reading-sets for a (co_id, branch_id, entry_date) with readings parsed to a list
    and the stored stats (avg / stdev / cv_pct / deviation) projected straight through."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        entry_date = request.query_params.get("entry_date")
        if not entry_date:
            raise HTTPException(status_code=400, detail="entry_date is required")

        branch_id = request.query_params.get("branch_id")

        result = db.execute(
            get_cutting_length_by_date_query(),
            {
                "co_id": int(co_id),
                "entry_date": entry_date,
                "branch_id": int(branch_id) if branch_id else None,
            },
        ).fetchall()

        rows = []
        for r in result:
            row = dict(r._mapping)
            if row.get("readings") and isinstance(row["readings"], str):
                row["readings"] = json.loads(row["readings"])
            for k in ("std_length", "avg", "stdev", "cv_pct", "deviation"):
                if row.get(k) is not None:
                    row[k] = float(row[k])
            rows.append(row)

        return {"data": {"rows": rows}}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching cutting length by date")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_cutting_length_table")
def get_cutting_length_table(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Paginated history of cutting-length reading-sets for a company (doubles as trend)."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        page = max(1, int(request.query_params.get("page", "1")))
        limit = max(1, min(100, int(request.query_params.get("limit", "10"))))
        offset = (page - 1) * limit
        search = request.query_params.get("search")
        branch_id = request.query_params.get("branch_id")

        params = {
            "co_id": int(co_id),
            "branch_id": int(branch_id) if branch_id else None,
            "limit": limit,
            "offset": offset,
        }
        if search:
            params["search"] = f"%{search}%"

        count_row = db.execute(
            get_cutting_length_table_count_query(search=search), params
        ).fetchone()
        total = count_row.total if count_row else 0

        result = db.execute(
            get_cutting_length_table_query(search=search), params
        ).fetchall()
        rows = [dict(r._mapping) for r in result]

        return {"data": rows, "total": total, "page": page, "page_size": limit}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching cutting length table")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/delete_cutting_length")
def delete_cutting_length(
    body: CuttingLengthDeleteRequest,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Soft-delete (active=0) one reading-set, scoped by co_id."""
    try:
        existing = db.execute(
            get_cutting_length_by_id_query(),
            {"cutting_length_id": body.cutting_length_id, "co_id": body.co_id},
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Cutting length reading not found")

        db.execute(
            soft_delete_cutting_length_query(),
            {
                "cutting_length_id": body.cutting_length_id,
                "co_id": body.co_id,
                "updated_by": token_data.get("user_id"),
            },
        )
        db.commit()
        return {"message": "Cutting length QC log deleted successfully"}

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error deleting cutting length QC log")
        raise HTTPException(status_code=500, detail=str(e))
