"""R-08-19 Fabric Construction QC API endpoints (jute SQC module).

Woven hessian cloth construction audit. One save = ONE quality block = a header (date,
cloth quality, its 6 std values snapshotted) + up to 5 sample rows. Array-entry: the FE
POSTs an array of sample rows; the BE inserts one header + N detail rows.

Each sample row has 6 MEASURED inputs (length_yds, width_cms, ends_per_dm, picks_per_dm,
mr_pct, obs_wt_kg). Per-row computed server-side (authoritative):
    obs_ozs   = (obs_wt_kg * 1000 / KG_TO_OZ) / length_yds        (oz per yard)
    crcted_oz = obs_ozs * (100 + std_mr_pct) / (100 + mr_pct)     (universal MR correction)

by_date summary (server-computed): per block, per-column AVG of its sample rows +
a Std-vs-Actual comparison of the 6 dimensions (deviation = block avg - std). No CV%,
no pass/fail band.

Quality dropdown = JUTE CLOTH items (item_type_id=5) — the beaming cloth picker is reused
directly (get_beaming_cloth_items_query). Portal persona: get_tenant_db +
get_current_user_with_refresh, {"data": ...} responses, the beam_mr _f/_i + try/except style.
"""

from typing import List, Optional
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.juteSQC.constants import (
    FABRIC_CONSTRUCTION_SAMPLE_ROWS,
    FABRIC_CONSTRUCTION_DEFAULT_STD_MR,
    KG_TO_OZ,
)
from src.juteSQC.query import (
    get_fabric_construction_table_query,
    get_fabric_construction_table_count_query,
    get_fabric_construction_by_date_query,
    get_fabric_construction_by_id_query,
    get_fabric_construction_dtl_query,
    soft_delete_fabric_construction_query,
)
from src.juteProduction.beaming_query import get_beaming_cloth_items_query
from src.models.jute import JuteSqcFabricConstruction, JuteSqcFabricConstructionDtl

logger = logging.getLogger(__name__)

router = APIRouter()

# The 6 dimensions compared Std-vs-Actual in by_date (sample-column name, header-std name).
_DIMENSIONS = [
    ("length_yds", "std_length_yds"),
    ("width_cms", "std_width_cms"),
    ("ends_per_dm", "std_ends_dm"),
    ("picks_per_dm", "std_picks_dm"),
    ("mr_pct", "std_mr_pct"),
    ("obs_ozs", "std_oz_per_yd"),
]


def _f(v):
    """Cast a possibly-None / Decimal value to float (None stays None)."""
    return None if v is None else float(v)


def _avg(vals):
    nums = [v for v in vals if v is not None]
    return round(sum(nums) / len(nums), 3) if nums else None


def _compute_row(length_yds, mr_pct, std_mr_pct, obs_wt_kg):
    """obs_ozs = (obs_wt_kg * 1000 / KG_TO_OZ) / length_yds;
    crcted_oz = obs_ozs * (100 + std_mr_pct) / (100 + mr_pct)."""
    obs_ozs = round((obs_wt_kg * 1000.0 / KG_TO_OZ) / length_yds, 3)
    crcted_oz = round(obs_ozs * (100.0 + std_mr_pct) / (100.0 + mr_pct), 3)
    return obs_ozs, crcted_oz


# =============================================================================
# Pydantic models
# =============================================================================


class FabricConstructionRow(BaseModel):
    length_yds: float
    width_cms: float
    ends_per_dm: float
    picks_per_dm: float
    mr_pct: float
    obs_wt_kg: float


class FabricConstructionCreateRequest(BaseModel):
    co_id: int
    branch_id: Optional[int] = None
    entry_date: str
    item_id: int
    quality_text: Optional[str] = None
    std_length_yds: float
    std_width_cms: float
    std_ends_dm: float
    std_picks_dm: float
    std_mr_pct: float
    std_oz_per_yd: float
    rows: List[FabricConstructionRow]


class FabricConstructionDeleteRequest(BaseModel):
    fabric_const_id: int
    co_id: int


# =============================================================================
# Endpoints
# =============================================================================


@router.get("/get_fabric_construction_create_setup")
def get_fabric_construction_create_setup(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Cloth-quality picker (jute cloth items, item_type_id=5) plus the default std-MR
    prefill and the fixed sample-row cap for the Fabric Construction entry form."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        cloth_rows = db.execute(
            get_beaming_cloth_items_query(),
            {"co_id": int(co_id)},
        ).fetchall()
        cloth_qualities = [dict(r._mapping) for r in cloth_rows]

        return {
            "data": {
                "cloth_qualities": cloth_qualities,
                "default_std_mr_pct": FABRIC_CONSTRUCTION_DEFAULT_STD_MR,
                "sample_rows": FABRIC_CONSTRUCTION_SAMPLE_ROWS,
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching fabric construction create setup")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/create_fabric_construction")
def create_fabric_construction(
    body: FabricConstructionCreateRequest,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Save ONE quality block: header (6 std values snapshotted) + 1..5 sample rows.
    obs_ozs / crcted_oz are computed server-side per row."""
    try:
        if not body.rows:
            raise HTTPException(status_code=400, detail="At least one sample row is required")

        if len(body.rows) > FABRIC_CONSTRUCTION_SAMPLE_ROWS:
            raise HTTPException(
                status_code=400,
                detail=f"At most {FABRIC_CONSTRUCTION_SAMPLE_ROWS} sample rows are allowed, got {len(body.rows)}",
            )

        if body.std_mr_pct <= 0:
            raise HTTPException(status_code=400, detail="std_mr_pct must be greater than 0")

        for idx, r in enumerate(body.rows, start=1):
            for field in ("length_yds", "width_cms", "ends_per_dm", "picks_per_dm", "mr_pct", "obs_wt_kg"):
                val = getattr(r, field)
                if val is None or val <= 0:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Row {idx}: {field} must be present and greater than 0",
                    )

        header = JuteSqcFabricConstruction(
            co_id=body.co_id,
            branch_id=body.branch_id,
            entry_date=body.entry_date,
            item_id=body.item_id,
            quality_text=body.quality_text,
            std_length_yds=body.std_length_yds,
            std_width_cms=body.std_width_cms,
            std_ends_dm=body.std_ends_dm,
            std_picks_dm=body.std_picks_dm,
            std_mr_pct=body.std_mr_pct,
            std_oz_per_yd=body.std_oz_per_yd,
            updated_by=token_data.get("user_id"),
        )
        db.add(header)
        db.flush()  # populate fabric_const_id for the detail rows

        for sl, r in enumerate(body.rows, start=1):
            obs_ozs, crcted_oz = _compute_row(
                r.length_yds, r.mr_pct, body.std_mr_pct, r.obs_wt_kg
            )
            db.add(
                JuteSqcFabricConstructionDtl(
                    fabric_const_id=header.fabric_const_id,
                    sl=sl,
                    length_yds=r.length_yds,
                    width_cms=r.width_cms,
                    ends_per_dm=r.ends_per_dm,
                    picks_per_dm=r.picks_per_dm,
                    mr_pct=r.mr_pct,
                    obs_wt_kg=r.obs_wt_kg,
                    obs_ozs=obs_ozs,
                    crcted_oz=crcted_oz,
                )
            )

        db.commit()
        db.refresh(header)

        return {
            "message": "Fabric Construction QC log created successfully",
            "fabric_const_id": header.fabric_const_id,
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error creating fabric construction QC log")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_fabric_construction_by_date")
def get_fabric_construction_by_date(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """All quality blocks for one (co_id, branch_id, entry_date) with each block's sample
    rows, per-column averages, and a Std-vs-Actual comparison of the 6 dimensions."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        entry_date = request.query_params.get("entry_date")
        if not entry_date:
            raise HTTPException(status_code=400, detail="entry_date is required")

        branch_id = request.query_params.get("branch_id")

        headers = db.execute(
            get_fabric_construction_by_date_query(),
            {
                "co_id": int(co_id),
                "entry_date": entry_date,
                "branch_id": int(branch_id) if branch_id else None,
            },
        ).fetchall()

        blocks = []
        for h in headers:
            hm = dict(h._mapping)
            hid = hm["fabric_const_id"]

            dtl_rows = db.execute(
                get_fabric_construction_dtl_query(),
                {"fabric_const_id": hid},
            ).fetchall()
            samples = []
            for d in dtl_rows:
                dm = dict(d._mapping)
                samples.append(
                    {
                        "sl": dm["sl"],
                        "length_yds": _f(dm.get("length_yds")),
                        "width_cms": _f(dm.get("width_cms")),
                        "ends_per_dm": _f(dm.get("ends_per_dm")),
                        "picks_per_dm": _f(dm.get("picks_per_dm")),
                        "mr_pct": _f(dm.get("mr_pct")),
                        "obs_wt_kg": _f(dm.get("obs_wt_kg")),
                        "obs_ozs": _f(dm.get("obs_ozs")),
                        "crcted_oz": _f(dm.get("crcted_oz")),
                    }
                )

            # Per-column averages over the block's sample rows.
            averages = {
                col: _avg([s[col] for s in samples])
                for col in (
                    "length_yds", "width_cms", "ends_per_dm", "picks_per_dm",
                    "mr_pct", "obs_wt_kg", "obs_ozs", "crcted_oz",
                )
            }

            # Std-vs-Actual: actual = block avg of the dimension, deviation = actual - std.
            comparison = []
            for sample_col, std_col in _DIMENSIONS:
                std = _f(hm.get(std_col))
                actual = averages.get(sample_col)
                deviation = (
                    round(actual - std, 3)
                    if actual is not None and std is not None
                    else None
                )
                comparison.append(
                    {
                        "dimension": sample_col,
                        "std": std,
                        "actual": actual,
                        "deviation": deviation,
                    }
                )

            blocks.append(
                {
                    "fabric_const_id": hid,
                    "entry_date": str(hm["entry_date"]) if hm.get("entry_date") is not None else None,
                    "branch_id": hm.get("branch_id"),
                    "item_id": hm.get("item_id"),
                    "item_code": hm.get("item_code"),
                    "item_name": hm.get("item_name"),
                    "quality_text": hm.get("quality_text"),
                    "std_length_yds": _f(hm.get("std_length_yds")),
                    "std_width_cms": _f(hm.get("std_width_cms")),
                    "std_ends_dm": _f(hm.get("std_ends_dm")),
                    "std_picks_dm": _f(hm.get("std_picks_dm")),
                    "std_mr_pct": _f(hm.get("std_mr_pct")),
                    "std_oz_per_yd": _f(hm.get("std_oz_per_yd")),
                    # FE FabricConstructionBlock.rows + grid read this under "rows".
                    "rows": samples,
                    "averages": averages,
                    "comparison": comparison,
                }
            )

        return {"data": {"blocks": blocks}}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching fabric construction by date")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_fabric_construction_table")
def get_fabric_construction_table(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Paginated history of fabric-construction quality blocks for a company."""
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
            get_fabric_construction_table_count_query(search=search), params
        ).fetchone()
        total = count_row.total if count_row else 0

        result = db.execute(
            get_fabric_construction_table_query(search=search), params
        ).fetchall()
        rows = [dict(r._mapping) for r in result]

        return {"data": rows, "total": total, "page": page, "page_size": limit}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching fabric construction table")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/delete_fabric_construction")
def delete_fabric_construction(
    body: FabricConstructionDeleteRequest,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Soft-delete (active=0) one quality block header, scoped by co_id."""
    try:
        existing = db.execute(
            get_fabric_construction_by_id_query(),
            {"fabric_const_id": body.fabric_const_id, "co_id": body.co_id},
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Fabric Construction block not found")

        db.execute(
            soft_delete_fabric_construction_query(),
            {
                "fabric_const_id": body.fabric_const_id,
                "co_id": body.co_id,
                "updated_by": token_data.get("user_id"),
            },
        )
        db.commit()
        return {"message": "Fabric Construction QC log deleted successfully"}

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error deleting fabric construction QC log")
        raise HTTPException(status_code=500, detail=str(e))
