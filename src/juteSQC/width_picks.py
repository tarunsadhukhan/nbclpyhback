"""R-08-21 Width and Picks QC API endpoints (jute SQC module).

On-loom dimensional QC of woven cloth. ONE save = ONE (entry_date, cloth-quality) group =
a header (entry_date, cloth quality, std_width_cm, std_picks snapshotted, optional
inspector_name) + N loom reading rows (loom machine, width_cm required, picks_dm optional).
Header+detail tables (NOT JSON arrays). picks_dm is OPTIONAL per row (only a sampled subset
of looms is pick-checked); width_cm is required per row.

std_width_cm + std_picks are entered/editable on the form per quality and SNAPSHOTTED on
the header at save — no change to any item master.

by_date summary (server-computed) per group:
  WIDTH: avg_width = mean(width_cm over rows); tol_low = std_width_cm*(1-WIDTH_TOL_PCT);
         tol_high = std_width_cm*(1+WIDTH_TOL_PCT); remark = '$' when avg_width < tol_low
         OR avg_width > tol_high (two-sided +/-0.5%), else ''.
  PICKS: over the NON-NULL picks_dm only -> avg_picks = mean; stdev = SAMPLE stdev
         (statistics.stdev, needs >=2 values else null); max_picks; min_picks; pick_count.
         No CV%, no MR correction.

Quality dropdown = JUTE CLOTH items (item_type_id=5) — the beaming cloth picker is reused
directly (get_beaming_cloth_items_query). Loom dropdown = WEAVING (Loom) machines — reused
via get_weaving_entry_machines_query exactly as weaving_sqc.py calls it (de-duped by
machine_id; dev3 has duplicate loom rows). Portal persona: get_tenant_db +
get_current_user_with_refresh, {"data": ...} responses.
"""

from statistics import mean, stdev
from typing import List, Optional
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.juteSQC.constants import WIDTH_TOL_PCT
from src.juteSQC.query import (
    get_width_picks_table_query,
    get_width_picks_table_count_query,
    get_width_picks_by_date_query,
    get_width_picks_by_id_query,
    get_width_picks_dtl_query,
    soft_delete_width_picks_query,
)
from src.juteProduction.constants import WEAVING_MACHINE_TYPE_NAME
from src.juteProduction.beaming_query import get_beaming_cloth_items_query
from src.juteProduction.weaving_query import get_weaving_entry_machines_query
from src.models.jute import JuteSqcWidthPicks, JuteSqcWidthPicksDtl

logger = logging.getLogger(__name__)

router = APIRouter()


def _f(v):
    """Cast a possibly-None / Decimal value to float (None stays None)."""
    return None if v is None else float(v)


def _width_summary(widths, std_width_cm):
    """avg_width = mean(width_cm); tol = std_width_cm +/- WIDTH_TOL_PCT (two-sided);
    remark = '$' when avg_width outside [tol_low, tol_high], else ''."""
    nums = [w for w in widths if w is not None]
    avg_width = round(mean(nums), 2) if nums else None
    tol_low = round(std_width_cm * (1 - WIDTH_TOL_PCT), 2) if std_width_cm is not None else None
    tol_high = round(std_width_cm * (1 + WIDTH_TOL_PCT), 2) if std_width_cm is not None else None
    remark = ""
    if avg_width is not None and tol_low is not None and tol_high is not None:
        if avg_width < tol_low or avg_width > tol_high:
            remark = "$"
    return {
        "avg_width": avg_width,
        "tol_low": tol_low,
        "tol_high": tol_high,
        "remark": remark,
    }


def _picks_summary(picks):
    """Over the NON-NULL picks_dm only: avg_picks = mean; stdev = SAMPLE stdev (n-1,
    needs >=2 values else null); max_picks; min_picks; pick_count."""
    nums = [p for p in picks if p is not None]
    n = len(nums)
    return {
        "avg_picks": round(mean(nums), 2) if nums else None,
        "stdev": round(stdev(nums), 4) if n >= 2 else None,
        "max_picks": round(max(nums), 2) if nums else None,
        "min_picks": round(min(nums), 2) if nums else None,
        "pick_count": n,
    }


# =============================================================================
# Pydantic models
# =============================================================================


class WidthPicksRow(BaseModel):
    loom_id: int
    width_cm: float
    picks_dm: Optional[float] = None


class WidthPicksCreateRequest(BaseModel):
    co_id: int
    branch_id: Optional[int] = None
    entry_date: str
    item_id: int
    std_width_cm: float
    std_picks: float
    inspector_name: Optional[str] = None
    rows: List[WidthPicksRow]


class WidthPicksDeleteRequest(BaseModel):
    width_picks_id: int
    co_id: int


# =============================================================================
# Endpoints
# =============================================================================


@router.get("/width_picks_create_setup")
def width_picks_create_setup(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Cloth-quality picker (jute cloth items, item_type_id=5) + the WEAVING loom picker
    (de-duped by machine_id) for the Width and Picks entry form."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        branch_id = request.query_params.get("branch_id")

        cloth_rows = db.execute(
            get_beaming_cloth_items_query(),
            {"co_id": int(co_id)},
        ).fetchall()
        cloth_qualities = [
            {
                "item_id": m["item_id"],
                "item_code": m.get("item_code"),
                "item_name": m.get("item_name"),
            }
            for m in (dict(r._mapping) for r in cloth_rows)
        ]

        loom_rows = db.execute(
            get_weaving_entry_machines_query(),
            {"loom_type": WEAVING_MACHINE_TYPE_NAME, "branch_id": int(branch_id) if branch_id else None},
        ).fetchall()
        looms = []
        seen = set()
        for r in loom_rows:
            m = dict(r._mapping)
            mid = m["machine_id"]
            if mid in seen:  # dev3 has duplicate loom rows — de-dup by machine_id
                continue
            seen.add(mid)
            looms.append(
                {
                    "machine_id": mid,
                    "machine_name": m.get("machine_name"),
                    "mech_code": m.get("mech_code"),
                }
            )

        return {"data": {"cloth_qualities": cloth_qualities, "looms": looms}}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching width/picks create setup")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/create_width_picks")
def create_width_picks(
    body: WidthPicksCreateRequest,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Save ONE (date, cloth-quality) group: header (std snapshot) + N loom reading rows."""
    try:
        if not body.rows:
            raise HTTPException(status_code=400, detail="At least one loom reading row is required")

        if body.std_width_cm <= 0:
            raise HTTPException(status_code=400, detail="std_width_cm must be greater than 0")

        if body.std_picks <= 0:
            raise HTTPException(status_code=400, detail="std_picks must be greater than 0")

        for idx, r in enumerate(body.rows, start=1):
            if r.width_cm is None or r.width_cm <= 0:
                raise HTTPException(
                    status_code=400,
                    detail=f"Row {idx}: width_cm must be present and greater than 0",
                )
            if r.picks_dm is not None and r.picks_dm <= 0:
                raise HTTPException(
                    status_code=400,
                    detail=f"Row {idx}: picks_dm must be greater than 0 when present",
                )

        header = JuteSqcWidthPicks(
            co_id=body.co_id,
            branch_id=body.branch_id,
            entry_date=body.entry_date,
            item_id=body.item_id,
            std_width_cm=body.std_width_cm,
            std_picks=body.std_picks,
            inspector_name=body.inspector_name,
            updated_by=token_data.get("user_id"),
        )
        db.add(header)
        db.flush()  # populate width_picks_id for the detail rows

        for r in body.rows:
            db.add(
                JuteSqcWidthPicksDtl(
                    width_picks_id=header.width_picks_id,
                    loom_id=r.loom_id,
                    width_cm=r.width_cm,
                    picks_dm=r.picks_dm,
                )
            )

        db.commit()
        db.refresh(header)

        return {
            "message": "Width and Picks QC log created successfully",
            "width_picks_id": header.width_picks_id,
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error creating width/picks QC log")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_width_picks_by_date")
def get_width_picks_by_date(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """All (cloth-quality) groups for one (co_id, branch_id, entry_date) with each group's
    loom rows + server-computed Width and Picks summaries."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        entry_date = request.query_params.get("entry_date")
        if not entry_date:
            raise HTTPException(status_code=400, detail="entry_date is required")

        branch_id = request.query_params.get("branch_id")

        headers = db.execute(
            get_width_picks_by_date_query(),
            {
                "co_id": int(co_id),
                "entry_date": entry_date,
                "branch_id": int(branch_id) if branch_id else None,
            },
        ).fetchall()

        blocks = []
        for h in headers:
            hm = dict(h._mapping)
            hid = hm["width_picks_id"]
            std_width_cm = _f(hm.get("std_width_cm"))

            dtl_rows = db.execute(
                get_width_picks_dtl_query(),
                {"width_picks_id": hid},
            ).fetchall()
            rows = []
            for d in dtl_rows:
                dm = dict(d._mapping)
                rows.append(
                    {
                        "loom_id": dm.get("loom_id"),
                        "loom_name": dm.get("loom_name"),
                        "mech_code": dm.get("mech_code"),
                        "width_cm": _f(dm.get("width_cm")),
                        "picks_dm": _f(dm.get("picks_dm")),
                    }
                )

            width_summary = _width_summary([r["width_cm"] for r in rows], std_width_cm)
            picks_summary = _picks_summary([r["picks_dm"] for r in rows])

            blocks.append(
                {
                    "width_picks_id": hid,
                    "entry_date": str(hm["entry_date"]) if hm.get("entry_date") is not None else None,
                    "branch_id": hm.get("branch_id"),
                    "item_id": hm.get("item_id"),
                    "item_code": hm.get("item_code"),
                    "item_name": hm.get("item_name"),
                    "std_width_cm": std_width_cm,
                    "std_picks": _f(hm.get("std_picks")),
                    "inspector_name": hm.get("inspector_name"),
                    "rows": rows,
                    "width_summary": width_summary,
                    "picks_summary": picks_summary,
                }
            )

        return {"data": {"blocks": blocks}}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching width/picks by date")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_width_picks_table")
def get_width_picks_table(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Paginated history of width-and-picks groups for a company."""
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
            get_width_picks_table_count_query(search=search), params
        ).fetchone()
        total = count_row.total if count_row else 0

        result = db.execute(
            get_width_picks_table_query(search=search), params
        ).fetchall()
        rows = [dict(r._mapping) for r in result]

        return {"data": rows, "total": total, "page": page, "page_size": limit}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching width/picks table")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/delete_width_picks")
def delete_width_picks(
    body: WidthPicksDeleteRequest,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Soft-delete (active=0) one width-and-picks group header, scoped by co_id."""
    try:
        existing = db.execute(
            get_width_picks_by_id_query(),
            {"width_picks_id": body.width_picks_id, "co_id": body.co_id},
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Width and Picks group not found")

        db.execute(
            soft_delete_width_picks_query(),
            {
                "width_picks_id": body.width_picks_id,
                "co_id": body.co_id,
                "updated_by": token_data.get("user_id"),
            },
        )
        db.commit()
        return {"message": "Width and Picks QC log deleted successfully"}

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error deleting width/picks QC log")
        raise HTTPException(status_code=500, detail=str(e))
