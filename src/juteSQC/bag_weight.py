"""
R-08-23 Bag Weight QC API endpoints.

Finished-bag weight control. ONE save = ONE (entry_date, bag type) block: a flat header
(entry_date, bag type, std_bag_weight, std_mr_pct) plus N reading rows (up to 24, variable
>=1), each row = {mr (MR%), obs (observed bag weight gm)}. Readings stored as a JSON-string
array of objects (morrah flat pattern, single table — NO detail table).

PER-ROW (computed at save, re-derived on read): corr = obs * (100 + std_mr_pct) / (100 + mr).
BLOCK stats (server-authoritative, stored at save):
  avg_mr = mean(mr); avg_obs = mean(obs); avg_corr = mean(per-row corr) [ROW-WISE mean];
  obs_stdev = SAMPLE stdev(obs) (n-1, statistics.stdev, null if <2 rows);
  obs_cv_pct = obs_stdev / avg_obs * 100;
  obs_hy_lt_pct = (avg_obs - std_bag_weight) / std_bag_weight * 100;
  corr_hy_lt_pct = (avg_corr - std_bag_weight) / std_bag_weight * 100.
HY/LT sign: positive = Heavy, negative = Light. DISPLAY-ONLY (no hard pass/fail band).

std_bag_weight + std_mr_pct are entered on the form (std_mr_pct prefills 20 for jute bags,
editable) and SNAPSHOTTED on the header at save. Bag type dropdown = JUTE CLOTH items
(item_type_id=5), reusing the beaming cloth picker (no re-implementation).
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
    BAG_WEIGHT_DEFAULT_STD_MR,
)
from src.juteSQC.query import (
    get_bag_weight_table_query,
    get_bag_weight_table_count_query,
    get_bag_weight_by_date_query,
    get_bag_weight_by_id_query,
    soft_delete_bag_weight_query,
)
from src.juteProduction.beaming_query import get_beaming_cloth_items_query
from src.models.jute import JuteSqcBagWeight

logger = logging.getLogger(__name__)

router = APIRouter()


class BagWeightReading(BaseModel):
    mr: float
    obs: float


class BagWeightCreateRequest(BaseModel):
    co_id: int
    branch_id: Optional[int] = None
    entry_date: str
    item_id: Optional[int] = None
    bag_type_label: Optional[str] = None
    std_bag_weight: float
    std_mr_pct: float
    readings: List[BagWeightReading]


class BagWeightDeleteRequest(BaseModel):
    bag_weight_id: int
    co_id: int


def row_corr(obs: float, mr: float, std_mr_pct: float) -> float:
    """MR-corrected observed bag weight: obs * (100 + std_mr_pct) / (100 + mr).
    mr is the per-row MR%; (100 + mr) is never 0 here (mr > 0 enforced at save)."""
    return obs * (100.0 + std_mr_pct) / (100.0 + mr)


def compute_bag_weight_stats(readings: List[dict], std_bag_weight: float, std_mr_pct: float) -> dict:
    """Block stats over the rows (authoritative). avg_corr is the ROW-WISE mean of the
    per-row corrected weights. obs_stdev = SAMPLE stdev (n-1), None when <2 rows; cv guards
    on avg_obs > 0. HY/LT percents are display-only (positive = Heavy, negative = Light)."""
    mrs = [r["mr"] for r in readings]
    obss = [r["obs"] for r in readings]
    corrs = [row_corr(r["obs"], r["mr"], std_mr_pct) for r in readings]

    avg_mr = statistics.mean(mrs)
    avg_obs = statistics.mean(obss)
    avg_corr = statistics.mean(corrs)

    obs_stdev = statistics.stdev(obss) if len(obss) > 1 else None
    obs_cv_pct = (
        round(obs_stdev / avg_obs * 100, 2)
        if obs_stdev is not None and avg_obs > 0
        else None
    )

    obs_hy_lt_pct = (
        round((avg_obs - std_bag_weight) / std_bag_weight * 100, 2)
        if std_bag_weight > 0
        else None
    )
    corr_hy_lt_pct = (
        round((avg_corr - std_bag_weight) / std_bag_weight * 100, 2)
        if std_bag_weight > 0
        else None
    )

    return {
        "calc_avg_mr": round(avg_mr, 3),
        "calc_avg_obs_wt": round(avg_obs, 2),
        "calc_avg_corr_wt": round(avg_corr, 2),
        "calc_obs_stdev": round(obs_stdev, 3) if obs_stdev is not None else None,
        "calc_obs_cv_pct": obs_cv_pct,
        "calc_obs_hy_lt_pct": obs_hy_lt_pct,
        "calc_corr_hy_lt_pct": corr_hy_lt_pct,
    }


@router.get("/bag_weight_create_setup")
def bag_weight_create_setup(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Bag-type picker (JUTE CLOTH, item_type_id=5) plus the prefilled std MR for the
    entry form."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        # branch_id is accepted for parity with siblings; the bag-type picker is co-scoped only.
        bag_rows = db.execute(
            get_beaming_cloth_items_query(),
            {"co_id": int(co_id)},
        ).fetchall()
        bag_types = [
            {
                "item_id": r._mapping["item_id"],
                "item_code": r._mapping["item_code"],
                "item_name": r._mapping["item_name"],
            }
            for r in bag_rows
        ]

        return {
            "data": {
                "bag_types": bag_types,
                "default_std_mr_pct": BAG_WEIGHT_DEFAULT_STD_MR,
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching bag weight create setup")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/create_bag_weight")
def create_bag_weight(
    body: BagWeightCreateRequest,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Save ONE (date, bag type) block (>=1 reading rows, no upper cap). std_bag_weight + std_mr_pct
    snapshotted; per-row corr + all block stats computed server-side and stored."""
    try:
        n = len(body.readings)
        if n < 1:
            raise HTTPException(status_code=400, detail="At least 1 reading row is required")

        if any(r.mr <= 0 for r in body.readings):
            raise HTTPException(status_code=400, detail="All mr values must be positive numbers")
        if any(r.obs <= 0 for r in body.readings):
            raise HTTPException(status_code=400, detail="All obs values must be positive numbers")

        if body.std_bag_weight <= 0:
            raise HTTPException(status_code=400, detail="std_bag_weight must be positive")
        if body.std_mr_pct <= 0:
            raise HTTPException(status_code=400, detail="std_mr_pct must be positive")

        readings = [{"mr": r.mr, "obs": r.obs} for r in body.readings]
        stats = compute_bag_weight_stats(readings, body.std_bag_weight, body.std_mr_pct)

        record = JuteSqcBagWeight(
            co_id=body.co_id,
            branch_id=body.branch_id,
            entry_date=body.entry_date,
            item_id=body.item_id,
            bag_type_label=body.bag_type_label,
            std_bag_weight=body.std_bag_weight,
            std_mr_pct=body.std_mr_pct,
            readings=json.dumps(readings),
            calc_avg_mr=stats["calc_avg_mr"],
            calc_avg_obs_wt=stats["calc_avg_obs_wt"],
            calc_avg_corr_wt=stats["calc_avg_corr_wt"],
            calc_obs_stdev=stats["calc_obs_stdev"],
            calc_obs_cv_pct=stats["calc_obs_cv_pct"],
            calc_obs_hy_lt_pct=stats["calc_obs_hy_lt_pct"],
            calc_corr_hy_lt_pct=stats["calc_corr_hy_lt_pct"],
            updated_by=token_data.get("user_id"),
        )

        db.add(record)
        db.commit()
        db.refresh(record)

        return {
            "message": "Bag weight QC log created successfully",
            "bag_weight_id": record.bag_weight_id,
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error creating bag weight QC log")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_bag_weight_by_date")
def get_bag_weight_by_date(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """All bag-weight blocks for a (co_id, branch_id, entry_date). readings parsed to a list
    with per-row corr re-derived from the snapshotted std_mr_pct; block stats projected from
    the stored calc_* columns."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        entry_date = request.query_params.get("entry_date")
        if not entry_date:
            raise HTTPException(status_code=400, detail="entry_date is required")

        branch_id = request.query_params.get("branch_id")

        result = db.execute(
            get_bag_weight_by_date_query(),
            {
                "co_id": int(co_id),
                "entry_date": entry_date,
                "branch_id": int(branch_id) if branch_id else None,
            },
        ).fetchall()

        blocks = []
        for r in result:
            row = dict(r._mapping)
            std_mr_pct = float(row["std_mr_pct"]) if row.get("std_mr_pct") is not None else None

            raw_readings = []
            if row.get("readings") and isinstance(row["readings"], str):
                raw_readings = json.loads(row["readings"])
            readings = []
            for rd in raw_readings:
                mr = rd.get("mr")
                obs = rd.get("obs")
                corr = (
                    round(row_corr(obs, mr, std_mr_pct), 2)
                    if mr is not None and obs is not None and std_mr_pct is not None
                    else None
                )
                readings.append({"mr": mr, "obs": obs, "corr": corr})

            for k in (
                "std_bag_weight",
                "std_mr_pct",
                "avg_mr",
                "avg_obs",
                "avg_corr",
                "obs_stdev",
                "obs_cv_pct",
                "obs_hy_lt_pct",
                "corr_hy_lt_pct",
            ):
                if row.get(k) is not None:
                    row[k] = float(row[k])

            row["readings"] = readings
            blocks.append(row)

        return {"data": {"blocks": blocks}}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching bag weight by date")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_bag_weight_table")
def get_bag_weight_table(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Paginated history of bag-weight blocks for a company (doubles as trend)."""
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
            get_bag_weight_table_count_query(search=search), params
        ).fetchone()
        total = count_row.total if count_row else 0

        result = db.execute(
            get_bag_weight_table_query(search=search), params
        ).fetchall()
        rows = [dict(r._mapping) for r in result]

        return {"data": rows, "total": total, "page": page, "page_size": limit}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching bag weight table")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/delete_bag_weight")
def delete_bag_weight(
    body: BagWeightDeleteRequest,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Soft-delete (active=0) one bag-weight block, scoped by co_id."""
    try:
        existing = db.execute(
            get_bag_weight_by_id_query(),
            {"bag_weight_id": body.bag_weight_id, "co_id": body.co_id},
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Bag weight reading not found")

        db.execute(
            soft_delete_bag_weight_query(),
            {
                "bag_weight_id": body.bag_weight_id,
                "co_id": body.co_id,
                "updated_by": token_data.get("user_id"),
            },
        )
        db.commit()
        return {"message": "Bag weight QC log deleted successfully"}

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error deleting bag weight QC log")
        raise HTTPException(status_code=500, detail=str(e))
