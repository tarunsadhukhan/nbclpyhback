"""
R-08-22 Stitch SQC API endpoints.

Finishing-stage sewing-stitch-density QC. The operator records EXACTLY 5 stitch counts
(stitches/dm) per (entry_date, sewing machine) reading-set — one set saved at a time
(beam_mr/morrah flat pattern, single table, NO detail table). avg = mean of the 5;
std_stitch is a fixed mill standard (9 stitches/dm) prefilled on the form, editable, and
snapshotted at save. flag = 'OK' when avg == std_stitch (exact), else 'LOW' if
avg < std_stitch, else 'HIGH'. No CV%, no MR correction, no quality column (machine-only).

Machine dropdown = SEWING machines resolved by machine_type_mst.machine_type_name =
STITCH_MACHINE_TYPE_NAME ('HEMMING' in dev3). De-duped by machine_id. Duplicate
(date, machine) sets are allowed (insert-only).
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
    STITCH_READINGS,
    STITCH_DEFAULT_STD,
    STITCH_MACHINE_TYPE_NAME,
)
from src.juteSQC.query import (
    get_stitch_machines_query,
    get_stitch_table_query,
    get_stitch_table_count_query,
    get_stitch_by_date_query,
    get_stitch_by_id_query,
    soft_delete_stitch_query,
)
from src.models.jute import JuteSqcStitch

logger = logging.getLogger(__name__)

router = APIRouter()


def _flag(avg: float, std: float) -> Optional[str]:
    """OK when avg == std (within epsilon); LOW when avg < std; else HIGH.

    Exact-equality (not rounded) so any drift off the standard flags — a stitch QC
    must surface a 9.4 avg as HIGH, not absorb it as OK. Matches the FE rule so the
    server and client never disagree on the flag.
    """
    if avg is None or std is None:
        return None
    if abs(avg - std) < 1e-9:
        return "OK"
    return "LOW" if avg < std else "HIGH"


class StitchCreateRequest(BaseModel):
    co_id: int
    branch_id: Optional[int] = None
    entry_date: str
    mc_id: Optional[int] = None
    std_stitch: Optional[float] = None
    readings: List[float]
    inspector_name: Optional[str] = None


@router.get("/stitch_create_setup")
def stitch_create_setup(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Pickers for the Stitch entry form: sewing machines, plus the default std and the
    fixed readings count."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        branch_id = request.query_params.get("branch_id")
        if not branch_id:
            raise HTTPException(status_code=400, detail="branch_id is required")

        # Sewing/stitch machines (de-dup by machine_id — dev3 may have duplicate rows).
        machine_rows = db.execute(
            get_stitch_machines_query(),
            {"stitch_type": STITCH_MACHINE_TYPE_NAME, "branch_id": int(branch_id)},
        ).fetchall()
        seen_mc = set()
        machines = []
        for r in machine_rows:
            m = dict(r._mapping)
            if m["machine_id"] in seen_mc:
                continue
            seen_mc.add(m["machine_id"])
            machines.append(
                {
                    "machine_id": m["machine_id"],
                    "machine_name": m["machine_name"],
                    "mech_code": m["mech_code"],
                }
            )

        return {
            "data": {
                "machines": machines,
                "default_std_stitch": STITCH_DEFAULT_STD,
                "readings_count": STITCH_READINGS,
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching stitch create setup")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/create_stitch")
def create_stitch(
    body: StitchCreateRequest,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Save ONE reading-set (exactly 5 stitch counts). avg = mean(5); std snapshotted."""
    try:
        if len(body.readings) != STITCH_READINGS:
            raise HTTPException(
                status_code=400,
                detail=f"Exactly {STITCH_READINGS} stitch readings are required, got {len(body.readings)}",
            )

        if any(r <= 0 for r in body.readings):
            raise HTTPException(status_code=400, detail="All readings must be positive numbers")

        if not body.mc_id:
            raise HTTPException(status_code=400, detail="A sewing machine must be selected")

        std_stitch = body.std_stitch if body.std_stitch is not None else STITCH_DEFAULT_STD
        if std_stitch <= 0:
            raise HTTPException(status_code=400, detail="std_stitch must be a positive number")

        avg = round(sum(body.readings) / len(body.readings), 2)

        record = JuteSqcStitch(
            co_id=body.co_id,
            branch_id=body.branch_id,
            entry_date=body.entry_date,
            mc_id=body.mc_id,
            std_stitch=std_stitch,
            readings=json.dumps(body.readings),
            calc_avg=avg,
            inspector_name=body.inspector_name,
            updated_by=token_data.get("user_id"),
        )

        db.add(record)
        db.commit()
        db.refresh(record)

        return {
            "message": "Stitch QC log created successfully",
            "stitch_id": record.stitch_id,
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error creating stitch QC log")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_stitch_by_date")
def get_stitch_by_date(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """All reading-sets for a (co_id, branch_id, entry_date) with per-machine avg and the
    OK/LOW/HIGH flag computed from calc_avg vs std_stitch."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        entry_date = request.query_params.get("entry_date")
        if not entry_date:
            raise HTTPException(status_code=400, detail="entry_date is required")

        branch_id = request.query_params.get("branch_id")

        result = db.execute(
            get_stitch_by_date_query(),
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

            avg = float(row["calc_avg"]) if row.get("calc_avg") is not None else None
            std = float(row["std_stitch"]) if row.get("std_stitch") is not None else None
            row["avg"] = avg
            row["std_stitch"] = std
            row["flag"] = _flag(avg, std)
            rows.append(row)

        return {"data": {"rows": rows}}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching stitch by date")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_stitch_table")
def get_stitch_table(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Paginated history of stitch reading-sets for a company."""
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
            get_stitch_table_count_query(search=search), params
        ).fetchone()
        total = count_row.total if count_row else 0

        result = db.execute(
            get_stitch_table_query(search=search), params
        ).fetchall()
        rows = []
        for r in result:
            row = dict(r._mapping)
            # Mirror get_stitch_by_date: the FE history row reads `avg`/`flag`, which
            # are derived (not stored). Map calc_avg -> avg and compute the OK/LOW/HIGH
            # flag so the trend table matches the by-date grid.
            avg = float(row["calc_avg"]) if row.get("calc_avg") is not None else None
            std = float(row["std_stitch"]) if row.get("std_stitch") is not None else None
            row["avg"] = avg
            row["std_stitch"] = std
            row["flag"] = _flag(avg, std)
            rows.append(row)

        return {"data": rows, "total": total, "page": page, "page_size": limit}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching stitch table")
        raise HTTPException(status_code=500, detail=str(e))


class StitchDeleteRequest(BaseModel):
    stitch_id: int
    co_id: int


@router.post("/delete_stitch")
def delete_stitch(
    body: StitchDeleteRequest,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Soft-delete (active=0) one reading-set, scoped by co_id."""
    try:
        existing = db.execute(
            get_stitch_by_id_query(),
            {"stitch_id": body.stitch_id, "co_id": body.co_id},
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Stitch reading not found")

        db.execute(
            soft_delete_stitch_query(),
            {
                "stitch_id": body.stitch_id,
                "co_id": body.co_id,
                "updated_by": token_data.get("user_id"),
            },
        )
        db.commit()
        return {"message": "Stitch QC log deleted successfully"}

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error deleting stitch QC log")
        raise HTTPException(status_code=500, detail=str(e))
