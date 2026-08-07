"""Finishing Spec Sheet (standards / targets / actuals) CRUD — jute_prod_finishing_target_map.

Endpoint-for-endpoint clone of beaming_target_map.py against the dedicated finishing
spec-sheet table, extended with ONE new dimension — ``process``. Time-versioned
standards/targets/actuals resolved by LAST-DATE (MAX(effective_date) <= on_date),
branch-agnostic. Finishing is THREE-DIMENSIONAL: process
('damping'|'calendering'|'lapping'|'cutting'|'hemming'|'balepress'), id_type ('mcid'
ref_id=machine_id | 'qid' ref_id=finishing_quality_id), and value_role
('standard'|'target'|'actual'). The applicable-param matrix is FINISHING_PARAMS
(constants.py, SPEC §5.1) — grid_params_for(process, id_type, value_role) is the single
source of truth for both target_map_grid (which cells to resolve) and target_map_bulk_save
(which params a cell may carry).

Portal persona: get_tenant_db + get_current_user_with_refresh, {"data": ...} responses,
_require_co_id / _optional_branch_id helpers, GET try/except (HTTPException: raise) /
(ValueError: 400) / (Exception: 500), and POST/PUT/DELETE rollback-then-raise. Setup
lists per-process machines (machine_type per FINISHING_MACHINE_TYPE_NAMES) and active
finishing qualities (filtered by quality_type per process) so the FE can pick a machine
(mcid) or quality (qid) ref. bulk_save semantics are IDENTICAL to beaming: per-cell
exact-key insert/update/clear in ONE transaction.

The grid-resolve (``resolve_finishing_grid``) and bulk-save (``bulk_save_finishing_cells``)
core functions are exported and REUSED VERBATIM by the Finishing SQC router
(src/juteSQC/finishing_sqc.py) with value_role forced to 'actual' — no SQL is duplicated.
"""

import math
from datetime import date
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.authorization.utils import get_current_user_with_refresh
from src.config.db import get_tenant_db
from src.juteProduction.constants import (
    FINISHING_BAG_PROCESSES,
    FINISHING_CLOTH_PROCESSES,
    FINISHING_ID_TYPE_MC,
    FINISHING_ID_TYPE_QLTY,
    FINISHING_MACHINE_TYPE_NAMES,
    FINISHING_PARAMS,
    FINISHING_PROCESSES,
    FINISHING_QUALITY_TYPE_BAG,
    FINISHING_QUALITY_TYPE_CLOTH,
    FINISHING_VALUE_ROLES,
)
from src.juteProduction.finishing_query import (
    clear_finishing_grid_value_query,
    find_exact_finishing_grid_row_query,
    get_finishing_machines_query,
    get_finishing_qualities_query,
    get_finishing_target_map_list_query,
    get_finishing_target_map_row_query,
    insert_finishing_target_map_query,
    resolve_finishing_grid_cell_query,
    update_finishing_grid_value_query,
)


router = APIRouter()

ID_TYPES = [FINISHING_ID_TYPE_MC, FINISHING_ID_TYPE_QLTY]  # ['mcid', 'qid']
VALUE_ROLES = list(FINISHING_VALUE_ROLES)  # ['standard', 'target', 'actual']
PROCESSES = list(FINISHING_PROCESSES)

# Union of every valid param across all processes / id_types / value_roles (for the
# global param enum check). grid_params_for() narrows to the exact applicable set.
PARAMS = list(
    dict.fromkeys(
        param
        for proc in FINISHING_PARAMS.values()
        for by_role in proc.values()
        for params in by_role.values()
        for param in params
    )
)

TARGET_MAP_NOT_FOUND_MSG = "Finishing spec-sheet row not found"


def grid_params_for(process: str, id_type: str, value_role: str) -> List[str]:
    """Ordered applicable params for a (process, id_type, value_role) combination.

    Single source of truth for both target_map_grid (which columns to resolve) and
    target_map_bulk_save (which params a cell may carry), read directly from the
    FINISHING_PARAMS matrix (SPEC §5.1). Returns [] for an unknown combination; callers
    validate process / id_type / value_role enums separately.
    """
    return list(FINISHING_PARAMS.get(process, {}).get(id_type, {}).get(value_role, ()))


def quality_type_for_process(process: str) -> Optional[int]:
    """quality_type to filter qid (finishing_quality) refs by, per process.

    Cloth processes -> type 1 (cloth qualities); bag processes -> type 2 (bag qualities).
    Returns None when the process is unknown (no filter).
    """
    if process in FINISHING_CLOTH_PROCESSES:
        return FINISHING_QUALITY_TYPE_CLOTH
    if process in FINISHING_BAG_PROCESSES:
        return FINISHING_QUALITY_TYPE_BAG
    return None


# =============================================================================
# Pydantic models
# =============================================================================


class TargetMapCreate(BaseModel):
    co_id: int
    branch_id: Optional[int] = None
    process: str
    effective_date: date
    ref_id: int
    id_type: str
    value_role: str
    param: str
    value: float = Field(ge=0)


class TargetMapUpdate(BaseModel):
    effective_date: Optional[date] = None
    value: Optional[float] = Field(default=None, ge=0)
    active: Optional[int] = None


class CellItem(BaseModel):
    ref_id: int
    param: str
    # None / empty -> clear the cell (soft-delete the exact-key active row, if any).
    # A present value is validated >= 0 in the handler (not via Field) so a negative
    # value yields a 400 with our message rather than a 422 Pydantic error.
    value: Optional[float] = None


class BulkSaveRequest(BaseModel):
    co_id: int
    branch_id: Optional[int] = None
    process: str
    effective_date: date
    id_type: str
    value_role: str
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


def _f(v, default: float = 0.0) -> float:
    """Cast a possibly-None / Decimal value to float."""
    return default if v is None else float(v)


def _i(v, default: Optional[int] = None) -> Optional[int]:
    return default if v is None else int(v)


def _validate_enums(process: str, id_type: str, value_role: str, param: str) -> None:
    if process not in PROCESSES:
        raise HTTPException(status_code=400, detail=f"Invalid process '{process}'")
    if id_type not in ID_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid id_type '{id_type}'")
    if value_role not in VALUE_ROLES:
        raise HTTPException(status_code=400, detail=f"Invalid value_role '{value_role}'")
    if param not in PARAMS:
        raise HTTPException(status_code=400, detail=f"Invalid param '{param}'")


def _optional_enum(request: Request, key: str, allowed: list) -> Optional[str]:
    raw = request.query_params.get(key)
    if not raw:
        return None
    if raw not in allowed:
        raise HTTPException(status_code=400, detail=f"Invalid {key} '{raw}'")
    return raw


def _optional_ref_id(request: Request) -> Optional[int]:
    raw = request.query_params.get("ref_id")
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ref_id")


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
        raise HTTPException(
            status_code=400, detail=f"Invalid {key} (expected YYYY-MM-DD)"
        )


def fetch_finishing_refs(
    db: Session, co_id: int, process: str, id_type: str, branch_id: Optional[int]
) -> List[Dict[str, Any]]:
    """The grid ref list for a (process, id_type): machines (mcid) or qualities (qid).

    machines -> {ref_id=machine_id, ref_code=mech_code, ref_name=machine_name} filtered
    by the process's machine type. qualities -> {ref_id=finishing_quality_id,
    ref_code=fin_quality_code, ref_name=fin_quality_name} filtered by the process's
    quality_type. branch_id scopes ONLY which refs are listed; value resolution itself
    never filters by branch. Shared by target_map_grid, target_map_setup and the SQC
    proxy.
    """
    refs: List[Dict[str, Any]] = []
    if id_type == FINISHING_ID_TYPE_MC:
        machine_type = FINISHING_MACHINE_TYPE_NAMES.get(process)
        for r in db.execute(
            get_finishing_machines_query(),
            {"machine_type": machine_type, "branch_id": branch_id},
        ).fetchall():
            m = dict(r._mapping)
            refs.append(
                {
                    "ref_id": m["machine_id"],
                    "ref_code": m["mech_code"],
                    "ref_name": m["machine_name"],
                }
            )
    else:  # qid
        for r in db.execute(
            get_finishing_qualities_query(),
            {
                "co_id": co_id,
                "quality_type": quality_type_for_process(process),
                "branch_id": branch_id,
            },
        ).fetchall():
            q = dict(r._mapping)
            refs.append(
                {
                    "ref_id": q["finishing_quality_id"],
                    "ref_code": q["fin_quality_code"],
                    "ref_name": q["fin_quality_name"],
                }
            )
    return refs


def resolve_finishing_grid(
    db: Session,
    co_id: int,
    process: str,
    id_type: str,
    value_role: str,
    effective_date: date,
    branch_id: Optional[int],
) -> Dict[str, Any]:
    """Core grid resolver — ``{"params": [...], "rows": [...]}`` for a process/type/role.

    One row per ref (machine | quality), one cell per applicable param resolved the SAME
    WAY production reads it (LAST-DATE, branch-agnostic). A param key is omitted from a
    cell when no active row resolves. is_exact = (source_date == effective_date). Shared
    verbatim by target_map_grid and the Finishing SQC actual grid (value_role='actual').
    """
    params = grid_params_for(process, id_type, value_role)
    refs = fetch_finishing_refs(db, co_id, process, id_type, branch_id)

    resolve_q = resolve_finishing_grid_cell_query()
    rows: List[Dict[str, Any]] = []
    for ref in refs:
        cells: Dict[str, Any] = {}
        for param in params:
            resolved = db.execute(
                resolve_q,
                {
                    "co_id": co_id,
                    "process": process,
                    "ref_id": int(ref["ref_id"]),
                    "id_type": id_type,
                    "value_role": value_role,
                    "param": param,
                    "on_date": effective_date,
                },
            ).fetchone()
            if not resolved or resolved.value is None:
                continue
            src = resolved.effective_date
            src_str = str(src) if src is not None else None
            cells[param] = {
                "value": _f(resolved.value),
                "source_date": src_str,
                "is_exact": src_str == str(effective_date),
            }
        rows.append(
            {
                "ref_id": ref["ref_id"],
                "ref_code": ref["ref_code"],
                "ref_name": ref["ref_name"],
                "cells": cells,
            }
        )
    return {"params": params, "rows": rows}


def bulk_save_finishing_cells(
    db: Session,
    co_id: int,
    process: str,
    id_type: str,
    value_role: str,
    effective_date: date,
    branch_id: Optional[int],
    cells: List[CellItem],
    user_id,
) -> Dict[str, int]:
    """Core bulk upsert/clear — exact-key per cell in ONE transaction (commit once).

    For each cell, finds the ACTIVE row at the exact key (co_id, process, ref_id,
    id_type, value_role, param, effective_date), BRANCH-AGNOSTIC:
      * value null/empty -> if found set active=0 (clear); else no-op
      * value present     -> if found UPDATE value; else INSERT a new active row
    Every cell's param must be valid for (process, id_type, value_role) -> 400 otherwise;
    a negative/non-finite value -> 400. Returns {inserted, updated, cleared}. Does NOT
    commit/rollback — the caller owns the transaction. Shared verbatim by
    target_map_bulk_save and the Finishing SQC actual save (value_role='actual').
    """
    allowed_params = grid_params_for(process, id_type, value_role)

    find_q = find_exact_finishing_grid_row_query()
    update_q = update_finishing_grid_value_query()
    clear_q = clear_finishing_grid_value_query()
    insert_q = insert_finishing_target_map_query()

    inserted = 0
    updated = 0
    cleared = 0

    for cell in cells:
        if cell.param not in allowed_params:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Invalid param '{cell.param}' for "
                    f"{process}/{id_type}/{value_role}"
                ),
            )
        if cell.value is not None:
            if not math.isfinite(float(cell.value)):
                raise HTTPException(
                    status_code=400,
                    detail=f"Value must be a finite number for param '{cell.param}'",
                )
            if float(cell.value) < 0:
                raise HTTPException(
                    status_code=400,
                    detail=f"Negative value not allowed for param '{cell.param}'",
                )

        key = {
            "co_id": co_id,
            "process": process,
            "ref_id": int(cell.ref_id),
            "id_type": id_type,
            "value_role": value_role,
            "param": cell.param,
            "effective_date": effective_date,
        }
        existing = db.execute(find_q, key).fetchone()

        if cell.value is None:
            if existing:
                db.execute(
                    clear_q,
                    {"id": existing.finishing_target_map_id, "updated_by": user_id},
                )
                cleared += 1
            continue

        value = float(cell.value)
        if existing:
            db.execute(
                update_q,
                {
                    "id": existing.finishing_target_map_id,
                    "value": value,
                    "updated_by": user_id,
                },
            )
            updated += 1
        else:
            db.execute(
                insert_q,
                {
                    "co_id": co_id,
                    "branch_id": branch_id,
                    "process": process,
                    "effective_date": effective_date,
                    "ref_id": int(cell.ref_id),
                    "id_type": id_type,
                    "value_role": value_role,
                    "param": cell.param,
                    "value": value,
                    "updated_by": user_id,
                },
            )
            inserted += 1

    return {"inserted": inserted, "updated": updated, "cleared": cleared}


# =============================================================================
# Setup
# =============================================================================


@router.get("/target_map_setup")
def target_map_setup(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Setup payload: processes, id_types, value_roles, the full FINISHING_PARAMS matrix,
    and (for a given process) the per-process machine list + quality list. process is
    OPTIONAL — when omitted, machines/qualities are returned empty and the FE fetches
    them after the user picks a process."""
    co_id = _require_co_id(request)
    branch_id = _optional_branch_id(request)
    process = _optional_enum(request, "process", PROCESSES)
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
                "value_roles": VALUE_ROLES,
                "params": FINISHING_PARAMS,
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


# =============================================================================
# List
# =============================================================================


@router.get("/target_map_list")
def target_map_list(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    co_id = _require_co_id(request)
    branch_id = _optional_branch_id(request)
    process = _optional_enum(request, "process", PROCESSES)
    id_type = _optional_enum(request, "id_type", ID_TYPES)
    ref_id = _optional_ref_id(request)
    value_role = _optional_enum(request, "value_role", VALUE_ROLES)
    param = _optional_enum(request, "param", PARAMS)
    try:
        rows = db.execute(
            get_finishing_target_map_list_query(),
            {
                "co_id": co_id,
                "branch_id": branch_id,
                "process": process,
                "id_type": id_type,
                "ref_id": ref_id,
                "value_role": value_role,
                "param": param,
            },
        ).fetchall()
        data = []
        for r in rows:
            m = dict(r._mapping)
            data.append(
                {
                    "finishing_target_map_id": m["finishing_target_map_id"],
                    "co_id": m["co_id"],
                    "branch_id": m.get("branch_id"),
                    "process": m["process"],
                    "effective_date": str(m["effective_date"])
                    if m.get("effective_date") is not None
                    else None,
                    "ref_id": m["ref_id"],
                    "id_type": m["id_type"],
                    "value_role": m["value_role"],
                    "param": m["param"],
                    "value": _f(m.get("value")),
                    "active": _i(m.get("active")),
                    "ref_code": m.get("ref_code"),
                    "ref_name": m.get("ref_name"),
                }
            )
        return {"data": data}
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid query parameter")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Create
# =============================================================================


@router.post("/target_map_create")
def target_map_create(
    body: TargetMapCreate,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        _validate_enums(body.process, body.id_type, body.value_role, body.param)
        # Cross-dimension guard: the param must be valid for THIS
        # (process, id_type, value_role) — _validate_enums only checks the global union.
        if body.param not in grid_params_for(body.process, body.id_type, body.value_role):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Invalid param '{body.param}' for "
                    f"{body.process}/{body.id_type}/{body.value_role}"
                ),
            )
        user_id = token_data.get("user_id")
        result = db.execute(
            insert_finishing_target_map_query(),
            {
                "co_id": int(body.co_id),
                "branch_id": body.branch_id,
                "process": body.process,
                "effective_date": body.effective_date,
                "ref_id": int(body.ref_id),
                "id_type": body.id_type,
                "value_role": body.value_role,
                "param": body.param,
                "value": float(body.value),
                "updated_by": user_id,
            },
        )
        db.commit()
        return {"data": {"finishing_target_map_id": result.lastrowid}}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Edit
# =============================================================================


@router.put("/target_map_edit/{target_map_id}")
def target_map_edit(
    target_map_id: int,
    body: TargetMapUpdate,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    co_id = _require_co_id(request)
    try:
        existing = db.execute(
            get_finishing_target_map_row_query(), {"id": target_map_id}
        ).fetchone()
        if not existing or existing._mapping["co_id"] != co_id:
            raise HTTPException(status_code=404, detail=TARGET_MAP_NOT_FOUND_MSG)

        user_id = token_data.get("user_id")
        sets = ["updated_by = :updated_by"]
        params = {"id": target_map_id, "updated_by": user_id}
        if body.effective_date is not None:
            sets.append("effective_date = :effective_date")
            params["effective_date"] = body.effective_date
        if body.value is not None:
            sets.append("value = :value")
            params["value"] = float(body.value)
        if body.active is not None:
            sets.append("active = :active")
            params["active"] = int(body.active)

        db.execute(
            text(
                f"UPDATE jute_prod_finishing_target_map SET {', '.join(sets)} "
                "WHERE finishing_target_map_id = :id"
            ),
            params,
        )
        db.commit()
        return {"data": {"finishing_target_map_id": target_map_id}}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Delete (soft)
# =============================================================================


@router.delete("/target_map_delete/{target_map_id}")
def target_map_delete(
    target_map_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    co_id = _require_co_id(request)
    try:
        existing = db.execute(
            get_finishing_target_map_row_query(), {"id": target_map_id}
        ).fetchone()
        if not existing or existing._mapping["co_id"] != co_id:
            raise HTTPException(status_code=404, detail=TARGET_MAP_NOT_FOUND_MSG)

        user_id = token_data.get("user_id")
        db.execute(
            text(
                "UPDATE jute_prod_finishing_target_map SET active = 0, updated_by = :updated_by "
                "WHERE finishing_target_map_id = :id"
            ),
            {"id": target_map_id, "updated_by": user_id},
        )
        db.commit()
        return {"data": {"message": "Deleted"}}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Inline grid: read (target_map_grid)
# =============================================================================


@router.get("/target_map_grid")
def target_map_grid(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """One row per ref (machine | quality), one cell per applicable param for the
    (process, id_type, value_role) combination, resolved LAST-DATE / branch-agnostic."""
    co_id = _require_co_id(request)
    branch_id = _optional_branch_id(request)
    process = _require_enum(request, "process", PROCESSES)
    id_type = _require_enum(request, "id_type", ID_TYPES)
    value_role = _require_enum(request, "value_role", VALUE_ROLES)
    effective_date = _require_date(request, "effective_date")
    try:
        data = resolve_finishing_grid(
            db, co_id, process, id_type, value_role, effective_date, branch_id
        )
        return {"data": data}
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid query parameter")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Inline grid: bulk save (target_map_bulk_save)
# =============================================================================


@router.post("/target_map_bulk_save")
def target_map_bulk_save(
    body: BulkSaveRequest,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Upsert/clear grid cells at the EXACT key (incl. process) in ONE transaction."""
    try:
        if body.process not in PROCESSES:
            raise HTTPException(status_code=400, detail=f"Invalid process '{body.process}'")
        if body.id_type not in ID_TYPES:
            raise HTTPException(status_code=400, detail=f"Invalid id_type '{body.id_type}'")
        if body.value_role not in VALUE_ROLES:
            raise HTTPException(
                status_code=400, detail=f"Invalid value_role '{body.value_role}'"
            )

        result = bulk_save_finishing_cells(
            db,
            int(body.co_id),
            body.process,
            body.id_type,
            body.value_role,
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
