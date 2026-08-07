"""Finishing SQC capture endpoints (jute SQC module) — ACTUALS ONLY.

The Finishing SQC page captures ACTUAL operating parameters (speed, bowl_temp,
moisture_add_pct, …) per (process, machine|quality) into the SAME spec-sheet table the
standards/targets live in — jute_prod_finishing_target_map with value_role='actual'. No
new SQC table is needed (SPEC §4.4). Quality lab tests (GSM/width/strength/moisture/…)
are DEFERRED and intentionally NOT built here.

These endpoints PROXY to the finishing_target_map grid/bulk_save core functions with
value_role forced to 'actual' — they reuse resolve_finishing_grid /
bulk_save_finishing_cells / fetch_finishing_refs verbatim, so NO SQL is duplicated.

Portal persona: get_tenant_db + get_current_user_with_refresh, {"data": ...} responses,
the standard try/except pattern (GET: HTTPException re-raise, ValueError 400, Exception
500; POST: rollback before raise/500). Registered under /api/juteSQC (shared with the
existing Spinning/Beaming SQC).
"""

from datetime import date
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.authorization.utils import get_current_user_with_refresh
from src.config.db import get_tenant_db
from src.juteProduction.constants import (
    FINISHING_ID_TYPE_MC,
    FINISHING_ID_TYPE_QLTY,
    FINISHING_PARAMS,
    FINISHING_PROCESSES,
)
from src.juteProduction.finishing_target_map import (
    CellItem,
    bulk_save_finishing_cells,
    fetch_finishing_refs,
    resolve_finishing_grid,
)


router = APIRouter()

# Finishing SQC only ever writes ACTUALS — value_role is forced everywhere.
ACTUAL = "actual"
PROCESSES = list(FINISHING_PROCESSES)
ID_TYPES = [FINISHING_ID_TYPE_MC, FINISHING_ID_TYPE_QLTY]


# =============================================================================
# Pydantic models
# =============================================================================


class FinishingSqcActualSave(BaseModel):
    """Body for the actuals save — same shape as the spec-sheet bulk_save MINUS value_role
    (forced to 'actual' server-side)."""

    co_id: int
    branch_id: Optional[int] = None
    process: str
    effective_date: date
    id_type: str
    cells: List[CellItem] = Field(default_factory=list)


# =============================================================================
# Helpers
# =============================================================================


def _require_co_id(request: Request) -> int:
    raw = request.query_params.get("co_id")
    if not raw:
        raise HTTPException(status_code=400, detail="co_id is required")
    try:
        return int(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid co_id")


def _optional_branch_id(request: Request) -> Optional[int]:
    raw = request.query_params.get("branch_id")
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid branch_id")


def _require_enum(request: Request, key: str, allowed: list) -> str:
    raw = request.query_params.get(key)
    if not raw:
        raise HTTPException(status_code=400, detail=f"{key} is required")
    if raw not in allowed:
        raise HTTPException(status_code=400, detail=f"Invalid {key} '{raw}'")
    return raw


def _require_date(request: Request, key: str) -> date:
    raw = request.query_params.get(key)
    if not raw:
        raise HTTPException(status_code=400, detail=f"{key} is required")
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid {key} (expected YYYY-MM-DD)")


def _actual_params_matrix() -> Dict[str, Dict[str, List[str]]]:
    """The 'actual'-role slice of FINISHING_PARAMS per process/id_type (for FE rendering)."""
    out: Dict[str, Dict[str, List[str]]] = {}
    for proc, by_type in FINISHING_PARAMS.items():
        out[proc] = {
            id_type: list(by_role.get(ACTUAL, ()))
            for id_type, by_role in by_type.items()
        }
    return out


# =============================================================================
# Endpoints
# =============================================================================


@router.get("/finishing_sqc_setup")
def finishing_sqc_setup(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Setup payload: processes, id_types, the 'actual'-role param matrix, and (for a
    given process) the per-process machine + quality ref lists. process OPTIONAL."""
    co_id = _require_co_id(request)
    branch_id = _optional_branch_id(request)
    process = request.query_params.get("process")
    if process and process not in PROCESSES:
        raise HTTPException(status_code=400, detail=f"Invalid process '{process}'")
    try:
        machines: List[Dict[str, Any]] = []
        qualities: List[Dict[str, Any]] = []
        if process:
            machines = [
                {
                    "machine_id": ref["ref_id"],
                    "mech_code": ref["ref_code"],
                    "machine_name": ref["ref_name"],
                }
                for ref in fetch_finishing_refs(
                    db, co_id, process, FINISHING_ID_TYPE_MC, branch_id
                )
            ]
            qualities = [
                {
                    "finishing_quality_id": ref["ref_id"],
                    "fin_quality_code": ref["ref_code"],
                    "fin_quality_name": ref["ref_name"],
                }
                for ref in fetch_finishing_refs(
                    db, co_id, process, FINISHING_ID_TYPE_QLTY, branch_id
                )
            ]
        return {
            "data": {
                "processes": PROCESSES,
                "id_types": ID_TYPES,
                "value_role": ACTUAL,
                "params": _actual_params_matrix(),
                "machines": machines,
                "qualities": qualities,
            }
        }
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid query parameter")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/finishing_sqc_actual_grid")
def finishing_sqc_actual_grid(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Actuals grid — proxy to the finishing spec-sheet grid with value_role='actual'.

    One row per ref (machine | quality), one cell per applicable 'actual' param for the
    (process, id_type) combination, resolved LAST-DATE / branch-agnostic — identical
    shape to /api/finishingTargetMap/target_map_grid.
    """
    co_id = _require_co_id(request)
    branch_id = _optional_branch_id(request)
    process = _require_enum(request, "process", PROCESSES)
    id_type = _require_enum(request, "id_type", ID_TYPES)
    effective_date = _require_date(request, "effective_date")
    try:
        data = resolve_finishing_grid(
            db, co_id, process, id_type, ACTUAL, effective_date, branch_id
        )
        return {"data": data}
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid query parameter")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/finishing_sqc_actual_save")
def finishing_sqc_actual_save(
    body: FinishingSqcActualSave,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Save actuals — proxy to the finishing spec-sheet bulk_save with value_role='actual'.

    Per-cell exact-key insert/update/clear in ONE transaction; returns
    {inserted, updated, cleared} — identical to
    /api/finishingTargetMap/target_map_bulk_save.
    """
    try:
        if body.process not in PROCESSES:
            raise HTTPException(status_code=400, detail=f"Invalid process '{body.process}'")
        if body.id_type not in ID_TYPES:
            raise HTTPException(status_code=400, detail=f"Invalid id_type '{body.id_type}'")

        result = bulk_save_finishing_cells(
            db,
            int(body.co_id),
            body.process,
            body.id_type,
            ACTUAL,
            body.effective_date,
            body.branch_id,
            body.cells,
            token_data.get("user_id"),
        )
        db.commit()
        return {"data": result}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
