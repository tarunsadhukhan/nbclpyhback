"""
R-08-18 Beam MR% QC API endpoints.

Warp-beam moisture-regain QC. The operator records EXACTLY 5 MR% readings per
(entry_date, quality group, beam machine) reading-set — one set saved at a time
(morrah/interCard entry pattern, NOT a full-page batch). avg_mr = mean of the 5;
std_mr defaults by quality group (HESSIAN 16, SACKING 20), is editable on the form,
and is snapshotted at save. deviation = avg_mr - std_mr_pct. No CV%, no pass/fail band.

Quality dropdown = JUTE CLOTH items (item_type_id=5); machine = Beaming-type machines —
both pickers reused from the jute production Beaming module (no re-implementation).
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
    BEAM_MR_READINGS_PER_SET,
    BEAM_MR_QUALITY_GROUPS,
    BEAM_MR_STD_MR_BY_GROUP,
)
from src.juteSQC.query import (
    get_beam_mr_table_query,
    get_beam_mr_table_count_query,
    get_beam_mr_by_date_query,
    get_beam_mr_by_id_query,
    soft_delete_beam_mr_query,
)
from src.juteProduction.beaming_query import (
    get_beaming_entry_machines_query,
    get_beaming_cloth_items_query,
    get_beaming_spells_query,
)
from src.juteProduction.constants import BEAMING_MACHINE_TYPE_NAME
from src.models.jute import JuteSqcBeamMr

logger = logging.getLogger(__name__)

router = APIRouter()


class BeamMrCreateRequest(BaseModel):
    co_id: int
    branch_id: Optional[int] = None
    entry_date: str
    quality_group: str
    spell_id: Optional[int] = None
    item_id: Optional[int] = None
    mc_id: Optional[int] = None
    readings: List[float]
    std_mr_pct: Optional[float] = None


@router.get("/get_beam_mr_create_setup")
def get_beam_mr_create_setup(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Pickers for the Beam MR% entry form: spells, beaming machines, cloth qualities,
    plus the std-MR defaults and the fixed readings-per-set."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        branch_id = request.query_params.get("branch_id")
        if not branch_id:
            raise HTTPException(status_code=400, detail="branch_id is required")

        # Beaming-type machines (de-dup by machine_id — dev3 has duplicate rows).
        machine_rows = db.execute(
            get_beaming_entry_machines_query(),
            {"beaming_type": BEAMING_MACHINE_TYPE_NAME, "branch_id": int(branch_id)},
        ).fetchall()
        seen_mc = set()
        machines = []
        for r in machine_rows:
            m = dict(r._mapping)
            if m["machine_id"] in seen_mc:
                continue
            seen_mc.add(m["machine_id"])
            machines.append(m)

        # Jute-cloth items (item_type_id=5) for the quality dropdown.
        cloth_rows = db.execute(
            get_beaming_cloth_items_query(),
            {"co_id": int(co_id)},
        ).fetchall()
        cloth_qualities = [dict(r._mapping) for r in cloth_rows]

        # Spells (de-dup by spell_code, keep first).
        spell_rows = db.execute(
            get_beaming_spells_query(),
            {"branch_id": int(branch_id)},
        ).fetchall()
        seen_sp = set()
        spells = []
        for r in spell_rows:
            s = dict(r._mapping)
            if s["spell_code"] in seen_sp:
                continue
            seen_sp.add(s["spell_code"])
            spells.append(s)

        return {
            "data": {
                "spells": spells,
                "machines": machines,
                "cloth_qualities": cloth_qualities,
                "std_mr_by_group": BEAM_MR_STD_MR_BY_GROUP,
                "readings_per_set": BEAM_MR_READINGS_PER_SET,
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching beam MR create setup")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/create_beam_mr")
def create_beam_mr(
    body: BeamMrCreateRequest,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Save ONE reading-set (one or more MR% readings). avg = mean(readings); std snapshotted."""
    try:
        if body.quality_group not in BEAM_MR_QUALITY_GROUPS:
            raise HTTPException(
                status_code=400,
                detail=f"quality_group must be one of {list(BEAM_MR_QUALITY_GROUPS)}",
            )

        if len(body.readings) < 1:
            raise HTTPException(
                status_code=400,
                detail="At least one MR% reading is required",
            )

        if any(r <= 0 for r in body.readings):
            raise HTTPException(status_code=400, detail="All readings must be positive numbers")

        if not body.mc_id:
            raise HTTPException(status_code=400, detail="A beam machine must be selected")

        if not body.item_id:
            raise HTTPException(status_code=400, detail="A cloth quality must be selected")

        avg_mr = round(sum(body.readings) / len(body.readings), 2)
        std_mr_pct = (
            body.std_mr_pct
            if body.std_mr_pct is not None
            else BEAM_MR_STD_MR_BY_GROUP[body.quality_group]
        )

        record = JuteSqcBeamMr(
            co_id=body.co_id,
            branch_id=body.branch_id,
            entry_date=body.entry_date,
            quality_group=body.quality_group,
            spell_id=body.spell_id,
            item_id=body.item_id,
            mc_id=body.mc_id,
            readings=json.dumps(body.readings),
            calc_avg_mr=avg_mr,
            std_mr_pct=std_mr_pct,
            updated_by=token_data.get("user_id"),
        )

        db.add(record)
        db.commit()
        db.refresh(record)

        return {
            "message": "Beam MR% QC log created successfully",
            "beam_mr_id": record.beam_mr_id,
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error creating beam MR QC log")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_beam_mr_by_date")
def get_beam_mr_by_date(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """All reading-sets for a (co_id, branch_id, entry_date) with per-machine avg/deviation
    and per-quality-group summaries (overall_avg_mr = mean of the per-machine avgs)."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        entry_date = request.query_params.get("entry_date")
        if not entry_date:
            raise HTTPException(status_code=400, detail="entry_date is required")

        branch_id = request.query_params.get("branch_id")

        result = db.execute(
            get_beam_mr_by_date_query(),
            {
                "co_id": int(co_id),
                "entry_date": entry_date,
                "branch_id": int(branch_id) if branch_id else None,
            },
        ).fetchall()

        rows = []
        # group_key -> list of per-machine avg_mr (for overall_avg_mr = mean of machine avgs)
        group_avgs: dict[str, list[float]] = {}
        group_std: dict[str, float] = {}

        for r in result:
            row = dict(r._mapping)
            if row.get("readings") and isinstance(row["readings"], str):
                row["readings"] = json.loads(row["readings"])

            avg_mr = float(row["calc_avg_mr"]) if row.get("calc_avg_mr") is not None else None
            std_mr = float(row["std_mr_pct"]) if row.get("std_mr_pct") is not None else None
            row["avg_mr"] = avg_mr
            row["std_mr_pct"] = std_mr
            row["deviation"] = (
                round(avg_mr - std_mr, 2) if avg_mr is not None and std_mr is not None else None
            )

            qg = row["quality_group"]
            if avg_mr is not None:
                group_avgs.setdefault(qg, []).append(avg_mr)
            if std_mr is not None and qg not in group_std:
                group_std[qg] = std_mr

            rows.append(row)

        group_summaries = []
        for qg, avgs in group_avgs.items():
            group_summaries.append(
                {
                    "quality_group": qg,
                    "overall_avg_mr": round(sum(avgs) / len(avgs), 2) if avgs else None,
                    "std_mr_pct": group_std.get(qg),
                    "machine_count": len(avgs),
                }
            )

        return {"data": {"rows": rows, "group_summaries": group_summaries}}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching beam MR by date")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_beam_mr_table")
def get_beam_mr_table(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Paginated history of beam-MR reading-sets for a company."""
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
            get_beam_mr_table_count_query(search=search), params
        ).fetchone()
        total = count_row.total if count_row else 0

        result = db.execute(
            get_beam_mr_table_query(search=search), params
        ).fetchall()
        rows = [dict(r._mapping) for r in result]

        return {"data": rows, "total": total, "page": page, "page_size": limit}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching beam MR table")
        raise HTTPException(status_code=500, detail=str(e))


class BeamMrDeleteRequest(BaseModel):
    beam_mr_id: int
    co_id: int


@router.post("/delete_beam_mr")
def delete_beam_mr(
    body: BeamMrDeleteRequest,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Soft-delete (active=0) one reading-set, scoped by co_id."""
    try:
        existing = db.execute(
            get_beam_mr_by_id_query(),
            {"beam_mr_id": body.beam_mr_id, "co_id": body.co_id},
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Beam MR reading not found")

        db.execute(
            soft_delete_beam_mr_query(),
            {
                "beam_mr_id": body.beam_mr_id,
                "co_id": body.co_id,
                "updated_by": token_data.get("user_id"),
            },
        )
        db.commit()
        return {"message": "Beam MR% QC log deleted successfully"}

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error deleting beam MR QC log")
        raise HTTPException(status_code=500, detail=str(e))
