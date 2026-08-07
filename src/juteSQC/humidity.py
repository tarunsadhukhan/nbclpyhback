"""
Humidity Recording SQC API endpoints.

Plant-wide department temperature / relative-humidity log. ONE save = ONE
(report_date, department, round) reading-set: a flat header (report_date, dept_id,
round_no [1=Morning, 2=Noon, 3=Evening], prepared_by) plus 1..3 SPOT readings stored
as a JSON-string array of objects {spot_label, reading_time, temp_c, rh_pct}
(bag_weight flat single-table pattern — NO detail table).

COMPUTED (server-authoritative, stored at save): avg_temp = mean(temp_c over spots);
avg_rh = mean(rh_pct over spots). Rounded 2dp. No StDev/CV, no band/status (the sheet
shows averages only). Coexists with the spinning RHMR report (JuteSqcSpinningRhmr) — does
NOT touch or supersede it. Department dropdown = dept_mst by branch (reuses the morrah
departments query).
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
from src.juteSQC.constants import HUMIDITY_SPOTS_PER_ROUND, HUMIDITY_ROUNDS
from src.juteSQC.query import (
    get_morrah_wt_departments_query,
    get_humidity_table_query,
    get_humidity_table_count_query,
    get_humidity_by_date_query,
    get_humidity_by_id_query,
    soft_delete_humidity_query,
)
from src.models.jute import JuteSqcHumidity

logger = logging.getLogger(__name__)

router = APIRouter()

# round_no -> label, derived from the shared constant (single source of truth).
ROUND_LABELS = {r["round_no"]: r["label"] for r in HUMIDITY_ROUNDS}
VALID_ROUNDS = set(ROUND_LABELS)


class HumiditySpot(BaseModel):
    spot_label: Optional[str] = None
    reading_time: Optional[str] = None
    temp_c: float
    rh_pct: float


class HumidityCreateRequest(BaseModel):
    co_id: int
    branch_id: Optional[int] = None
    report_date: str
    dept_id: Optional[int] = None
    round_no: int
    prepared_by: Optional[str] = None
    spots: List[HumiditySpot]


class HumidityDeleteRequest(BaseModel):
    humidity_id: int
    co_id: int


def compute_humidity_avgs(spots: List[dict]) -> dict:
    """avg_temp = mean(temp_c), avg_rh = mean(rh_pct), over the 1..3 spots. 2dp."""
    return {
        "calc_avg_temp": round(statistics.mean([s["temp_c"] for s in spots]), 2),
        "calc_avg_rh": round(statistics.mean([s["rh_pct"] for s in spots]), 2),
    }


@router.get("/humidity_create_setup")
def humidity_create_setup(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Department picker (dept_mst by branch) plus the fixed round list and spots-per-round
    for the entry form."""
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

        return {
            "data": {
                "departments": departments,
                "rounds": HUMIDITY_ROUNDS,
                "spots_per_round": HUMIDITY_SPOTS_PER_ROUND,
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching humidity create setup")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/create_humidity")
def create_humidity(
    body: HumidityCreateRequest,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Save ONE (report_date, dept, round) reading-set (1..3 spots). avg_temp + avg_rh
    computed server-side from the spots and stored."""
    try:
        if body.round_no not in VALID_ROUNDS:
            raise HTTPException(
                status_code=400,
                detail=f"round_no must be one of {sorted(VALID_ROUNDS)} (1=Morning, 2=Noon, 3=Evening)",
            )

        n = len(body.spots)
        if n < 1:
            raise HTTPException(status_code=400, detail="At least 1 spot reading is required")
        if n > HUMIDITY_SPOTS_PER_ROUND:
            raise HTTPException(
                status_code=400,
                detail=f"At most {HUMIDITY_SPOTS_PER_ROUND} spot readings are allowed, got {n}",
            )

        if any(s.temp_c <= 0 for s in body.spots):
            raise HTTPException(status_code=400, detail="All temp_c values must be positive numbers")
        if any(not (0 < s.rh_pct <= 100) for s in body.spots):
            raise HTTPException(status_code=400, detail="All rh_pct values must be in (0, 100]")

        spots = [
            {
                "spot_label": s.spot_label,
                "reading_time": s.reading_time,
                "temp_c": s.temp_c,
                "rh_pct": s.rh_pct,
            }
            for s in body.spots
        ]
        avgs = compute_humidity_avgs(spots)

        record = JuteSqcHumidity(
            co_id=body.co_id,
            branch_id=body.branch_id,
            report_date=body.report_date,
            dept_id=body.dept_id,
            round_no=body.round_no,
            spots=json.dumps(spots),
            calc_avg_temp=avgs["calc_avg_temp"],
            calc_avg_rh=avgs["calc_avg_rh"],
            prepared_by=body.prepared_by,
            updated_by=token_data.get("user_id"),
        )

        db.add(record)
        db.commit()
        db.refresh(record)

        return {
            "message": "Humidity reading saved successfully",
            "humidity_id": record.humidity_id,
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error creating humidity reading")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_humidity_by_date")
def get_humidity_by_date(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """All humidity reading-sets for a (co_id, branch_id, report_date), grouped by dept
    then round. spots parsed to a list; avgs project from the stored calc_* columns."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        report_date = request.query_params.get("report_date")
        if not report_date:
            raise HTTPException(status_code=400, detail="report_date is required")

        branch_id = request.query_params.get("branch_id")

        result = db.execute(
            get_humidity_by_date_query(),
            {
                "co_id": int(co_id),
                "report_date": report_date,
                "branch_id": int(branch_id) if branch_id else None,
            },
        ).fetchall()

        # Group rows by dept (preserving first-seen order) then round.
        depts: dict = {}
        for r in result:
            row = dict(r._mapping)
            dept_id = row.get("dept_id")
            if dept_id not in depts:
                depts[dept_id] = {
                    "dept_id": dept_id,
                    "dept_desc": row.get("dept_desc"),
                    "rounds": [],
                }

            spots = []
            if row.get("spots") and isinstance(row["spots"], str):
                spots = json.loads(row["spots"])

            depts[dept_id]["rounds"].append(
                {
                    "humidity_id": row["humidity_id"],
                    "round_no": row["round_no"],
                    "round_label": ROUND_LABELS.get(row["round_no"]),
                    "spots": spots,
                    "avg_temp": float(row["avg_temp"]) if row.get("avg_temp") is not None else None,
                    "avg_rh": float(row["avg_rh"]) if row.get("avg_rh") is not None else None,
                    "prepared_by": row.get("prepared_by"),
                }
            )

        return {"data": {"departments": list(depts.values())}}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching humidity by date")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_humidity_table")
def get_humidity_table(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Paginated history of humidity reading-sets for a company."""
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
            get_humidity_table_count_query(search=search), params
        ).fetchone()
        total = count_row.total if count_row else 0

        result = db.execute(
            get_humidity_table_query(search=search), params
        ).fetchall()
        rows = [dict(r._mapping) for r in result]

        return {"data": rows, "total": total, "page": page, "page_size": limit}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching humidity table")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/delete_humidity")
def delete_humidity(
    body: HumidityDeleteRequest,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Soft-delete (active=0) one humidity reading-set, scoped by co_id."""
    try:
        existing = db.execute(
            get_humidity_by_id_query(),
            {"humidity_id": body.humidity_id, "co_id": body.co_id},
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Humidity reading not found")

        db.execute(
            soft_delete_humidity_query(),
            {
                "humidity_id": body.humidity_id,
                "co_id": body.co_id,
                "updated_by": token_data.get("user_id"),
            },
        )
        db.commit()
        return {"message": "Humidity reading deleted successfully"}

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error deleting humidity reading")
        raise HTTPException(status_code=500, detail=str(e))
