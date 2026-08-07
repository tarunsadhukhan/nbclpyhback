"""
R-08-02 Emulsion SQC API endpoints.

Daily batching jute-oil emulsion recipe log (NOT a sampled QC report). ONE save = ONE date's
recipe: a single flat row (no readings array, no StDev/CV). Header carries the recipe
(oil_used_ltr, tank_capacity_ltr, oil_pct_in_emulsion) + the target band
(std_oil_pct_low/high, prefilled 16/17, editable, snapshotted at save) + a long list of
nullable additive columns + free-text others/prepared_by.

COMPUTED server-side on read (NOT stored):
  theoretical_oil_pct = oil_used_ltr / tank_capacity_ltr * 100  (REFERENCE only, div-guard
    tank > 0). Shown beside the measured oil_pct_in_emulsion.
  oil_pct_status = 'OK' when std_oil_pct_low <= oil_pct_in_emulsion <= std_oil_pct_high,
    'LOW' when below the band, 'HIGH' when above. DISPLAY-ONLY (no hard pass/fail gate).

Machine dropdown = SPREADER machines resolved by machine_type_mst.machine_type_name =
SPREADER_MACHINE_TYPE_NAME (from src.juteProduction.constants), de-duped by machine_id.
mc_id is OPTIONAL.
"""

from fastapi import Depends, Request, HTTPException, APIRouter
from pydantic import BaseModel
from typing import Optional
import logging

from sqlalchemy.orm import Session

from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.juteProduction.constants import SPREADER_MACHINE_TYPE_NAME
from src.juteSQC.constants import (
    EMULSION_DEFAULT_OIL_PCT_LOW,
    EMULSION_DEFAULT_OIL_PCT_HIGH,
    EMULSION_DEFAULT_TANK_CAPACITY,
)
from src.juteSQC.query import (
    get_emulsion_machines_query,
    get_emulsion_table_query,
    get_emulsion_table_count_query,
    get_emulsion_by_date_query,
    get_emulsion_by_id_query,
    soft_delete_emulsion_query,
)
from src.models.jute import JuteSqcEmulsion

logger = logging.getLogger(__name__)

router = APIRouter()

# Additive / free-text columns copied verbatim from the request body to the row. Kept as a
# tuple so create stays a one-liner loop instead of 20 hand-written assignments.
_ADDITIVE_FIELDS = (
    "adco_used_ml",
    "eco_fin_used_ltr",
    "p40_gms",
    "efjl_kg",
    "glycerine_gms",
    "castrol_oil",
    "diesel_ltr",
    "citric_acid_ltr",
    "enzyme_gms",
    "treated_water_ltr",
    "rbo_ltr",
    "jbo_ltr",
    "molasses_kg",
    "urea_kg",
    "biochemical_kg",
    "jsp66",
    "feel_free_good_ve_kg",
    "spreader_rolls_made",
    "others",
    "prepared_by",
)

# Numeric columns cast Decimal -> float on read (JSON-friendly, FE math).
_FLOAT_FIELDS = (
    "oil_used_ltr",
    "tank_capacity_ltr",
    "oil_pct_in_emulsion",
    "std_oil_pct_low",
    "std_oil_pct_high",
    "adco_used_ml",
    "eco_fin_used_ltr",
    "p40_gms",
    "efjl_kg",
    "glycerine_gms",
    "castrol_oil",
    "diesel_ltr",
    "citric_acid_ltr",
    "enzyme_gms",
    "treated_water_ltr",
    "rbo_ltr",
    "jbo_ltr",
    "molasses_kg",
    "urea_kg",
    "biochemical_kg",
    "jsp66",
    "feel_free_good_ve_kg",
)


def theoretical_oil_pct(oil_used: Optional[float], tank: Optional[float]) -> Optional[float]:
    """Reference oil% = oil_used_ltr / tank_capacity_ltr * 100. Div-guard tank > 0 (None
    when tank is missing/zero). 170/1000 -> 17.0."""
    if oil_used is None or tank is None or tank <= 0:
        return None
    return round(oil_used / tank * 100.0, 2)


def oil_pct_status(
    oil_pct: Optional[float], low: Optional[float], high: Optional[float]
) -> Optional[str]:
    """OK when low <= oil_pct <= high; LOW below the band; HIGH above. DISPLAY-ONLY.
    16.5 in 16-17 -> OK; 15 -> LOW; 18 -> HIGH."""
    if oil_pct is None or low is None or high is None:
        return None
    if oil_pct < low:
        return "LOW"
    if oil_pct > high:
        return "HIGH"
    return "OK"


class EmulsionCreateRequest(BaseModel):
    co_id: int
    branch_id: Optional[int] = None
    entry_date: str
    mc_id: Optional[int] = None
    oil_used_ltr: float
    tank_capacity_ltr: float
    oil_pct_in_emulsion: float
    std_oil_pct_low: float
    std_oil_pct_high: float
    adco_used_ml: Optional[float] = None
    eco_fin_used_ltr: Optional[float] = None
    p40_gms: Optional[float] = None
    efjl_kg: Optional[float] = None
    glycerine_gms: Optional[float] = None
    castrol_oil: Optional[float] = None
    diesel_ltr: Optional[float] = None
    citric_acid_ltr: Optional[float] = None
    enzyme_gms: Optional[float] = None
    treated_water_ltr: Optional[float] = None
    rbo_ltr: Optional[float] = None
    jbo_ltr: Optional[float] = None
    molasses_kg: Optional[float] = None
    urea_kg: Optional[float] = None
    biochemical_kg: Optional[float] = None
    jsp66: Optional[float] = None
    feel_free_good_ve_kg: Optional[float] = None
    spreader_rolls_made: Optional[int] = None
    others: Optional[str] = None
    prepared_by: Optional[str] = None


class EmulsionDeleteRequest(BaseModel):
    emulsion_id: int
    co_id: int


def _enrich(row: dict) -> dict:
    """Cast numeric columns to float and attach the two computed fields. Used by by_date."""
    for k in _FLOAT_FIELDS:
        if row.get(k) is not None:
            row[k] = float(row[k])

    row["theoretical_oil_pct"] = theoretical_oil_pct(
        row.get("oil_used_ltr"), row.get("tank_capacity_ltr")
    )
    row["oil_pct_status"] = oil_pct_status(
        row.get("oil_pct_in_emulsion"),
        row.get("std_oil_pct_low"),
        row.get("std_oil_pct_high"),
    )
    return row


@router.get("/emulsion_create_setup")
def emulsion_create_setup(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Pickers for the Emulsion entry form: SPREADER machines (de-duped by machine_id) plus
    the prefilled band defaults (16/17) and tank capacity (1000)."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        branch_id = request.query_params.get("branch_id")

        machine_rows = db.execute(
            get_emulsion_machines_query(),
            {
                "spreader_type": SPREADER_MACHINE_TYPE_NAME,
                "branch_id": int(branch_id) if branch_id else None,
            },
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
                "default_oil_pct_low": EMULSION_DEFAULT_OIL_PCT_LOW,
                "default_oil_pct_high": EMULSION_DEFAULT_OIL_PCT_HIGH,
                "default_tank_capacity": EMULSION_DEFAULT_TANK_CAPACITY,
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching emulsion create setup")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/create_emulsion")
def create_emulsion(
    body: EmulsionCreateRequest,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Save ONE date's emulsion recipe row. Band edges snapshotted; the two computed fields
    are derived on read, NOT stored."""
    try:
        if body.oil_used_ltr <= 0:
            raise HTTPException(status_code=400, detail="oil_used_ltr must be positive")
        if body.tank_capacity_ltr <= 0:
            raise HTTPException(status_code=400, detail="tank_capacity_ltr must be positive")
        if body.oil_pct_in_emulsion <= 0:
            raise HTTPException(status_code=400, detail="oil_pct_in_emulsion must be positive")
        if body.std_oil_pct_low <= 0:
            raise HTTPException(status_code=400, detail="std_oil_pct_low must be positive")
        if body.std_oil_pct_high < body.std_oil_pct_low:
            raise HTTPException(
                status_code=400,
                detail="std_oil_pct_high must be >= std_oil_pct_low",
            )

        record = JuteSqcEmulsion(
            co_id=body.co_id,
            branch_id=body.branch_id,
            entry_date=body.entry_date,
            mc_id=body.mc_id,
            oil_used_ltr=body.oil_used_ltr,
            tank_capacity_ltr=body.tank_capacity_ltr,
            oil_pct_in_emulsion=body.oil_pct_in_emulsion,
            std_oil_pct_low=body.std_oil_pct_low,
            std_oil_pct_high=body.std_oil_pct_high,
            updated_by=token_data.get("user_id"),
            **{f: getattr(body, f) for f in _ADDITIVE_FIELDS},
        )

        db.add(record)
        db.commit()
        db.refresh(record)

        return {
            "message": "Emulsion recipe log created successfully",
            "emulsion_id": record.emulsion_id,
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error creating emulsion recipe log")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_emulsion_by_date")
def get_emulsion_by_date(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """All emulsion rows for a (co_id, branch_id, entry_date), each with theoretical_oil_pct
    and oil_pct_status computed on read."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        entry_date = request.query_params.get("entry_date")
        if not entry_date:
            raise HTTPException(status_code=400, detail="entry_date is required")

        branch_id = request.query_params.get("branch_id")

        result = db.execute(
            get_emulsion_by_date_query(),
            {
                "co_id": int(co_id),
                "entry_date": entry_date,
                "branch_id": int(branch_id) if branch_id else None,
            },
        ).fetchall()

        rows = [_enrich(dict(r._mapping)) for r in result]
        return {"data": {"rows": rows}}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching emulsion by date")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_emulsion_table")
def get_emulsion_table(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Paginated history of emulsion rows for a company (each row carries the OK/LOW/HIGH
    status derived from the snapshotted band)."""
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
            get_emulsion_table_count_query(search=search), params
        ).fetchone()
        total = count_row.total if count_row else 0

        result = db.execute(
            get_emulsion_table_query(search=search), params
        ).fetchall()

        rows = []
        for r in result:
            row = dict(r._mapping)
            for k in (
                "oil_used_ltr",
                "tank_capacity_ltr",
                "oil_pct_in_emulsion",
                "std_oil_pct_low",
                "std_oil_pct_high",
            ):
                if row.get(k) is not None:
                    row[k] = float(row[k])
            row["oil_pct_status"] = oil_pct_status(
                row.get("oil_pct_in_emulsion"),
                row.get("std_oil_pct_low"),
                row.get("std_oil_pct_high"),
            )
            rows.append(row)

        return {"data": rows, "total": total, "page": page, "page_size": limit}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching emulsion table")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/delete_emulsion")
def delete_emulsion(
    body: EmulsionDeleteRequest,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Soft-delete (active=0) one emulsion row, scoped by co_id."""
    try:
        existing = db.execute(
            get_emulsion_by_id_query(),
            {"emulsion_id": body.emulsion_id, "co_id": body.co_id},
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Emulsion record not found")

        db.execute(
            soft_delete_emulsion_query(),
            {
                "emulsion_id": body.emulsion_id,
                "co_id": body.co_id,
                "updated_by": token_data.get("user_id"),
            },
        )
        db.commit()
        return {"message": "Emulsion recipe log deleted successfully"}

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error deleting emulsion recipe log")
        raise HTTPException(status_code=500, detail=str(e))
