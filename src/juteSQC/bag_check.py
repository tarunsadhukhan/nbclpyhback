"""R-08-24 Bag Checking QC API endpoints (jute SQC module).

Finished-bag acceptance inspection. ONE save = ONE (entry_date, bag type) block = a header
(date, bag type, free-text vendor_name / id_code, and the 7 per-quality STANDARDS snapshotted
at save: std_bag_weight, std_length, std_width, std_ends, std_picks, std_stitch, std_mr_pct —
std_mr_pct prefills 20, all editable) + N per-bag detail rows (variable, >=1, up to 20+).

Each bag has 7 MEASURED inputs (length_cm, width_cm, ends_dm, picks_dm, mr_pct, bag_wt_gm,
stitch_dm), all required and > 0, plus optional free-text defects. Per-bag computed server-side:
    corr_wt_gm = bag_wt_gm * (100 + std_mr_pct) / (100 + mr_pct)   (universal MR correction)

by_date summary (server-computed, authoritative) per block: for EACH numeric column
(length, width, ends, picks, mr, bag_wt, stitch, corr_wt) avg / SAMPLE stdev (n-1,
statistics.stdev, null if <2) / cv_pct (stdev/avg*100) / min / max; plus
    obs_hy_lt_pct  = (avg_bag_wt  - std_bag_weight) / std_bag_weight * 100
    corr_hy_lt_pct = (avg_corr_wt - std_bag_weight) / std_bag_weight * 100   (avg_corr_wt is the
ROW-WISE mean of the per-bag corr). DISPLAY-ONLY — no pass/fail flags, no CV% band.

Bag type dropdown = JUTE CLOTH items (item_type_id=5), reusing the beaming cloth picker
(get_beaming_cloth_items_query). NO vendor master (vendor_name free text). Portal persona:
get_tenant_db + get_current_user_with_refresh, {"data": ...} responses.
"""

from typing import List, Optional
import logging
import statistics

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.juteSQC.constants import BAG_CHECK_DEFAULT_STD_MR
from src.juteSQC.query import (
    get_bag_check_table_query,
    get_bag_check_table_count_query,
    get_bag_check_by_date_query,
    get_bag_check_by_id_query,
    get_bag_check_dtl_query,
    soft_delete_bag_check_query,
)
from src.juteProduction.beaming_query import get_beaming_cloth_items_query
from src.models.jute import JuteSqcBagCheck, JuteSqcBagCheckDtl

logger = logging.getLogger(__name__)

router = APIRouter()

# 7 per-bag MEASURED inputs — all required and > 0 at save.
_MEASURES = ("length_cm", "width_cm", "ends_dm", "picks_dm", "mr_pct", "bag_wt_gm", "stitch_dm")

# 8 numeric columns aggregated in by_date (avg/stdev/cv/min/max). corr_wt is computed per bag.
_AGG_COLS = (
    "length_cm", "width_cm", "ends_dm", "picks_dm",
    "mr_pct", "bag_wt_gm", "stitch_dm", "corr_wt_gm",
)


def _f(v):
    """Cast a possibly-None / Decimal value to float (None stays None)."""
    return None if v is None else float(v)


def bag_corr(bag_wt_gm: float, mr_pct: float, std_mr_pct: float) -> float:
    """MR-corrected bag weight: bag_wt_gm * (100 + std_mr_pct) / (100 + mr_pct).
    (100 + mr_pct) is never 0 here (mr_pct > 0 enforced at save)."""
    return bag_wt_gm * (100.0 + std_mr_pct) / (100.0 + mr_pct)


def _col_stats(vals):
    """avg / SAMPLE stdev (n-1, null if <2) / cv_pct (stdev/avg*100) / min / max over the
    non-None values of one column. cv guards on avg > 0; returns Nones for an empty column."""
    nums = [v for v in vals if v is not None]
    if not nums:
        return {"avg": None, "stdev": None, "cv_pct": None, "min": None, "max": None}
    avg = statistics.mean(nums)
    stdev = statistics.stdev(nums) if len(nums) > 1 else None
    cv_pct = round(stdev / avg * 100, 2) if stdev is not None and avg > 0 else None
    return {
        "avg": round(avg, 3),
        "stdev": round(stdev, 3) if stdev is not None else None,
        "cv_pct": cv_pct,
        "min": round(min(nums), 2),
        "max": round(max(nums), 2),
    }


# =============================================================================
# Pydantic models
# =============================================================================


class BagCheckRow(BaseModel):
    length_cm: float
    width_cm: float
    ends_dm: float
    picks_dm: float
    mr_pct: float
    bag_wt_gm: float
    stitch_dm: float
    defects: Optional[str] = None


class BagCheckCreateRequest(BaseModel):
    co_id: int
    branch_id: Optional[int] = None
    entry_date: str
    item_id: Optional[int] = None
    bag_type_label: Optional[str] = None
    vendor_name: Optional[str] = None
    id_code: Optional[str] = None
    std_bag_weight: float
    std_length: float
    std_width: float
    std_ends: float
    std_picks: float
    std_stitch: float
    std_mr_pct: float
    bags: List[BagCheckRow]


class BagCheckDeleteRequest(BaseModel):
    bag_check_id: int
    co_id: int


# =============================================================================
# Endpoints
# =============================================================================


@router.get("/bag_check_create_setup")
def bag_check_create_setup(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Bag-type picker (JUTE CLOTH, item_type_id=5) plus the prefilled std MR for the form."""
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
                "default_std_mr_pct": BAG_CHECK_DEFAULT_STD_MR,
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching bag check create setup")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/create_bag_check")
def create_bag_check(
    body: BagCheckCreateRequest,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Save ONE (date, bag type) block: header (7 std values snapshotted) + 1..N per-bag rows.
    corr_wt_gm is computed server-side per bag; block aggregates are computed on read."""
    try:
        if not body.bags:
            raise HTTPException(status_code=400, detail="At least 1 bag is required")

        for idx, b in enumerate(body.bags, start=1):
            for field in _MEASURES:
                val = getattr(b, field)
                if val is None or val <= 0:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Bag {idx}: {field} must be present and greater than 0",
                    )

        for std_field in (
            "std_bag_weight", "std_length", "std_width", "std_ends",
            "std_picks", "std_stitch", "std_mr_pct",
        ):
            if getattr(body, std_field) <= 0:
                raise HTTPException(status_code=400, detail=f"{std_field} must be greater than 0")

        header = JuteSqcBagCheck(
            co_id=body.co_id,
            branch_id=body.branch_id,
            entry_date=body.entry_date,
            item_id=body.item_id,
            bag_type_label=body.bag_type_label,
            vendor_name=body.vendor_name,
            id_code=body.id_code,
            std_bag_weight=body.std_bag_weight,
            std_length=body.std_length,
            std_width=body.std_width,
            std_ends=body.std_ends,
            std_picks=body.std_picks,
            std_stitch=body.std_stitch,
            std_mr_pct=body.std_mr_pct,
            updated_by=token_data.get("user_id"),
        )
        db.add(header)
        db.flush()  # populate bag_check_id for the detail rows

        for sl, b in enumerate(body.bags, start=1):
            corr_wt = round(bag_corr(b.bag_wt_gm, b.mr_pct, body.std_mr_pct), 2)
            db.add(
                JuteSqcBagCheckDtl(
                    bag_check_id=header.bag_check_id,
                    sl_no=sl,
                    length_cm=b.length_cm,
                    width_cm=b.width_cm,
                    ends_dm=b.ends_dm,
                    picks_dm=b.picks_dm,
                    mr_pct=b.mr_pct,
                    bag_wt_gm=b.bag_wt_gm,
                    stitch_dm=b.stitch_dm,
                    defects=b.defects,
                    corr_wt_gm=corr_wt,
                )
            )

        db.commit()
        db.refresh(header)

        return {
            "message": "Bag Checking QC log created successfully",
            "bag_check_id": header.bag_check_id,
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error creating bag check QC log")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_bag_check_by_date")
def get_bag_check_by_date(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """All bag-check blocks for one (co_id, branch_id, entry_date) with each block's per-bag
    rows, per-column aggregates (avg/stdev/cv%/min/max), and obs/corr heavy-light percents."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        entry_date = request.query_params.get("entry_date")
        if not entry_date:
            raise HTTPException(status_code=400, detail="entry_date is required")

        branch_id = request.query_params.get("branch_id")

        headers = db.execute(
            get_bag_check_by_date_query(),
            {
                "co_id": int(co_id),
                "entry_date": entry_date,
                "branch_id": int(branch_id) if branch_id else None,
            },
        ).fetchall()

        blocks = []
        for h in headers:
            hm = dict(h._mapping)
            hid = hm["bag_check_id"]

            dtl_rows = db.execute(
                get_bag_check_dtl_query(),
                {"bag_check_id": hid},
            ).fetchall()
            bags = []
            for d in dtl_rows:
                dm = dict(d._mapping)
                bags.append(
                    {
                        "sl_no": dm.get("sl_no"),
                        "length_cm": _f(dm.get("length_cm")),
                        "width_cm": _f(dm.get("width_cm")),
                        "ends_dm": _f(dm.get("ends_dm")),
                        "picks_dm": _f(dm.get("picks_dm")),
                        "mr_pct": _f(dm.get("mr_pct")),
                        "bag_wt_gm": _f(dm.get("bag_wt_gm")),
                        "stitch_dm": _f(dm.get("stitch_dm")),
                        "corr_wt_gm": _f(dm.get("corr_wt_gm")),
                        "defects": dm.get("defects"),
                    }
                )

            # Per-column aggregates over the block's bags (server-authoritative).
            aggregates = {col: _col_stats([b[col] for b in bags]) for col in _AGG_COLS}

            std_bag_weight = _f(hm.get("std_bag_weight"))
            # HY/LT works off the DISPLAYED (2dp) avg weights the operator reads on the report,
            # so the percent matches the rounded figures shown (avoids a 3dp-internal drift).
            avg_bag_wt = (
                round(aggregates["bag_wt_gm"]["avg"], 2)
                if aggregates["bag_wt_gm"]["avg"] is not None else None
            )
            avg_corr_wt = (
                round(aggregates["corr_wt_gm"]["avg"], 2)
                if aggregates["corr_wt_gm"]["avg"] is not None else None
            )
            obs_hy_lt_pct = (
                round((avg_bag_wt - std_bag_weight) / std_bag_weight * 100, 2)
                if avg_bag_wt is not None and std_bag_weight not in (None, 0)
                else None
            )
            corr_hy_lt_pct = (
                round((avg_corr_wt - std_bag_weight) / std_bag_weight * 100, 2)
                if avg_corr_wt is not None and std_bag_weight not in (None, 0)
                else None
            )

            blocks.append(
                {
                    "bag_check_id": hid,
                    "entry_date": str(hm["entry_date"]) if hm.get("entry_date") is not None else None,
                    "branch_id": hm.get("branch_id"),
                    "item_id": hm.get("item_id"),
                    "item_code": hm.get("item_code"),
                    "item_name": hm.get("item_name"),
                    "bag_type_label": hm.get("bag_type_label"),
                    "vendor_name": hm.get("vendor_name"),
                    "id_code": hm.get("id_code"),
                    "std_bag_weight": std_bag_weight,
                    "std_length": _f(hm.get("std_length")),
                    "std_width": _f(hm.get("std_width")),
                    "std_ends": _f(hm.get("std_ends")),
                    "std_picks": _f(hm.get("std_picks")),
                    "std_stitch": _f(hm.get("std_stitch")),
                    "std_mr_pct": _f(hm.get("std_mr_pct")),
                    "bags": bags,
                    "aggregates": aggregates,
                    "obs_hy_lt_pct": obs_hy_lt_pct,
                    "corr_hy_lt_pct": corr_hy_lt_pct,
                }
            )

        return {"data": {"blocks": blocks}}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching bag check by date")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_bag_check_table")
def get_bag_check_table(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Paginated history of bag-check blocks for a company."""
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
            get_bag_check_table_count_query(search=search), params
        ).fetchone()
        total = count_row.total if count_row else 0

        result = db.execute(
            get_bag_check_table_query(search=search), params
        ).fetchall()
        rows = [dict(r._mapping) for r in result]

        return {"data": rows, "total": total, "page": page, "page_size": limit}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching bag check table")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/delete_bag_check")
def delete_bag_check(
    body: BagCheckDeleteRequest,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Soft-delete (active=0) one bag-check block header, scoped by co_id."""
    try:
        existing = db.execute(
            get_bag_check_by_id_query(),
            {"bag_check_id": body.bag_check_id, "co_id": body.co_id},
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Bag Checking block not found")

        db.execute(
            soft_delete_bag_check_query(),
            {
                "bag_check_id": body.bag_check_id,
                "co_id": body.co_id,
                "updated_by": token_data.get("user_id"),
            },
        )
        db.commit()
        return {"message": "Bag Checking QC log deleted successfully"}

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error deleting bag check QC log")
        raise HTTPException(status_code=500, detail=str(e))
