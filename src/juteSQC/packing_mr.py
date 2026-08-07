"""
R-08-25 Packing MR% QC API endpoints.

Finished-goods moisture at packing. ONE save = ONE (entry_date, quality column) reading-set:
a flat header (entry_date, quality_group HESSIAN|SACKING, optional cloth-quality item,
optional construction_code free text) plus EXACTLY 10 MR% readings stored as a JSON-string
array (beam_mr/morrah flat pattern, single table — NO detail table).

avg_mr = mean(10), computed server-side at save (authoritative). No std, no CV%, no MR
correction, no pass/fail — the sheet shows averages only.

by_date roll-up (server-computed): for each quality_group, group_avg_mr = WEIGHTED mean of
ALL readings across that group's columns (= sum(all readings) / count(all readings)). This
equals the mean-of-column-averages when every column carries 10 readings, and stays correct
if counts ever differ. column_count + reading_count are reported per group.

Cloth-quality link = JUTE CLOTH items (item_type_id=5), reusing the beaming cloth picker
(nullable). construction_code is free text.
"""

from fastapi import Depends, Request, HTTPException, APIRouter
from pydantic import BaseModel
from typing import List, Optional
import logging
import json

from sqlalchemy.orm import Session

from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.juteSQC.constants import (
    PACKING_MR_READINGS,
    PACKING_MR_QUALITY_GROUPS,
)
from src.juteSQC.query import (
    get_packing_mr_table_query,
    get_packing_mr_table_count_query,
    get_packing_mr_by_date_query,
    get_packing_mr_by_id_query,
    soft_delete_packing_mr_query,
)
from src.juteProduction.beaming_query import get_beaming_cloth_items_query
from src.models.jute import JuteSqcPackingMr

logger = logging.getLogger(__name__)

router = APIRouter()


class PackingMrCreateRequest(BaseModel):
    co_id: int
    branch_id: Optional[int] = None
    entry_date: str
    quality_group: str
    item_id: Optional[int] = None
    quality_label: Optional[str] = None
    construction_code: Optional[str] = None
    readings: List[float]


class PackingMrDeleteRequest(BaseModel):
    packing_mr_id: int
    co_id: int


@router.get("/packing_mr_create_setup")
def packing_mr_create_setup(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Cloth-quality picker (JUTE CLOTH, item_type_id=5), the two quality groups, and the
    fixed readings count for the Packing MR% entry form."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        # branch_id is accepted for parity with siblings; the cloth picker is co-scoped only.
        cloth_rows = db.execute(
            get_beaming_cloth_items_query(),
            {"co_id": int(co_id)},
        ).fetchall()
        qualities = [
            {
                "item_id": r._mapping["item_id"],
                "item_code": r._mapping["item_code"],
                "item_name": r._mapping["item_name"],
            }
            for r in cloth_rows
        ]

        return {
            "data": {
                "qualities": qualities,
                "quality_groups": list(PACKING_MR_QUALITY_GROUPS),
                "readings_count": PACKING_MR_READINGS,
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching packing MR create setup")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/create_packing_mr")
def create_packing_mr(
    body: PackingMrCreateRequest,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Save ONE reading-set (one or more MR% readings). avg = mean(readings), stored at save."""
    try:
        if body.quality_group not in PACKING_MR_QUALITY_GROUPS:
            raise HTTPException(
                status_code=400,
                detail=f"quality_group must be one of {list(PACKING_MR_QUALITY_GROUPS)}",
            )

        if len(body.readings) < 1:
            raise HTTPException(
                status_code=400,
                detail="At least one MR% reading is required",
            )

        if any(r <= 0 for r in body.readings):
            raise HTTPException(status_code=400, detail="All readings must be positive numbers")

        avg_mr = round(sum(body.readings) / len(body.readings), 3)

        record = JuteSqcPackingMr(
            co_id=body.co_id,
            branch_id=body.branch_id,
            entry_date=body.entry_date,
            item_id=body.item_id,
            quality_group=body.quality_group,
            quality_label=body.quality_label,
            construction_code=body.construction_code,
            readings=json.dumps(body.readings),
            calc_avg_mr=avg_mr,
            updated_by=token_data.get("user_id"),
        )

        db.add(record)
        db.commit()
        db.refresh(record)

        return {
            "message": "Packing MR% QC log created successfully",
            "packing_mr_id": record.packing_mr_id,
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error creating packing MR QC log")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_packing_mr_by_date")
def get_packing_mr_by_date(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """All reading-sets for a (co_id, branch_id, entry_date) with per-column avg and per-
    quality-group summaries. group_avg_mr = WEIGHTED mean of ALL readings in the group
    (sum of all readings / total reading count) — equals mean-of-column-avgs when every
    column carries 10 readings, and stays correct if counts ever differ."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        entry_date = request.query_params.get("entry_date")
        if not entry_date:
            raise HTTPException(status_code=400, detail="entry_date is required")

        branch_id = request.query_params.get("branch_id")

        result = db.execute(
            get_packing_mr_by_date_query(),
            {
                "co_id": int(co_id),
                "entry_date": entry_date,
                "branch_id": int(branch_id) if branch_id else None,
            },
        ).fetchall()

        columns = []
        # quality_group -> [running reading sum, running reading count, column count]
        group_totals: dict[str, list[float]] = {}

        for r in result:
            row = dict(r._mapping)
            readings = []
            if row.get("readings") and isinstance(row["readings"], str):
                readings = json.loads(row["readings"])

            avg_mr = round(sum(readings) / len(readings), 3) if readings else None

            columns.append(
                {
                    "packing_mr_id": row["packing_mr_id"],
                    "quality_group": row["quality_group"],
                    "item_id": row.get("item_id"),
                    "item_name": row.get("item_name"),
                    "quality_label": row.get("quality_label"),
                    "construction_code": row.get("construction_code"),
                    "readings": readings,
                    "avg_mr": avg_mr,
                }
            )

            qg = row["quality_group"]
            acc = group_totals.setdefault(qg, [0.0, 0, 0])
            acc[0] += sum(readings)
            acc[1] += len(readings)
            acc[2] += 1

        group_summaries = []
        for qg, (total, count, col_count) in group_totals.items():
            group_summaries.append(
                {
                    "quality_group": qg,
                    "group_avg_mr": round(total / count, 3) if count else None,
                    "column_count": col_count,
                    "reading_count": count,
                }
            )

        return {"data": {"columns": columns, "group_summaries": group_summaries}}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching packing MR by date")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_packing_mr_table")
def get_packing_mr_table(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Paginated history of packing-MR reading-sets for a company."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        page = max(1, int(request.query_params.get("page", "1")))
        limit = max(1, min(100, int(request.query_params.get("limit", "10"))))
        offset = (page - 1) * limit
        search = request.query_params.get("search")

        params = {"co_id": int(co_id), "limit": limit, "offset": offset}
        if search:
            params["search"] = f"%{search}%"

        count_row = db.execute(
            get_packing_mr_table_count_query(search=search), params
        ).fetchone()
        total = count_row.total if count_row else 0

        result = db.execute(
            get_packing_mr_table_query(search=search), params
        ).fetchall()
        rows = [dict(r._mapping) for r in result]

        return {"data": rows, "total": total, "page": page, "page_size": limit}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching packing MR table")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/delete_packing_mr")
def delete_packing_mr(
    body: PackingMrDeleteRequest,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Soft-delete (active=0) one reading-set, scoped by co_id."""
    try:
        existing = db.execute(
            get_packing_mr_by_id_query(),
            {"packing_mr_id": body.packing_mr_id, "co_id": body.co_id},
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Packing MR reading not found")

        db.execute(
            soft_delete_packing_mr_query(),
            {
                "packing_mr_id": body.packing_mr_id,
                "co_id": body.co_id,
                "updated_by": token_data.get("user_id"),
            },
        )
        db.commit()
        return {"message": "Packing MR% QC log deleted successfully"}

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error deleting packing MR QC log")
        raise HTTPException(status_code=500, detail=str(e))
