"""Weaving standards / targets master CRUD (jute_prod_weaving_target_map).

Endpoint-for-endpoint clone of beaming_target_map.py against the dedicated weaving
table. Time-versioned standards & targets resolved by LAST-DATE (MAX(effective_date) <=
on_date). Weaving is TWO-DIMENSIONAL (mirroring beaming): id_type is 'mcid'
(ref_id = machine_id, a LOOM) or 'qid'
(ref_id = jute_prod_weaving_quality.weaving_quality_id). value_role is
'standard' | 'target' | 'actual'. Resolution map (LOCKED CONTRACT, via grid_params_for):
  mcid standard -> ('speed',)
  mcid target   -> ('speed',)
  mcid actual   -> ('speed',)   (Weaving SQC "Actual Speed" tab)
  qid  standard -> ('picks','eff')
  qid  target   -> ('eff',)
  qid  actual   -> ()           (NONE: actual picks owned by vw_weaving_pick_act;
                                 actual speed is the mcid dimension)

Portal persona: get_tenant_db + get_current_user_with_refresh, {"data": ...} responses,
_require_co_id / _optional_branch_id helpers, GET try/except (HTTPException: raise) /
(ValueError: 400) / (Exception: 500), and POST/PUT/DELETE rollback-then-raise. Setup
lists BOTH Loom-type machines (machine_type_name='Loom') and active weaving qualities
(jute_prod_weaving_quality) so the FE can pick a machine (mcid) or quality (qid) ref.
bulk_save semantics are IDENTICAL to beaming: per-cell exact-key insert/update/clear in
ONE transaction.
"""

import math
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.authorization.utils import get_current_user_with_refresh
from src.config.db import get_tenant_db
from src.juteProduction.constants import (
    WEAVING_ID_TYPE_MC,
    WEAVING_ID_TYPE_QLTY,
    WEAVING_MACHINE_TYPE_NAME,
    WEAVING_MC_PARAMS_ACTUAL,
    WEAVING_MC_PARAMS_STD,
    WEAVING_MC_PARAMS_TARGET,
    WEAVING_QID_PARAMS_STD,
    WEAVING_QID_PARAMS_TARGET,
    WEAVING_VALUE_ROLES,
)
from src.juteProduction.weaving_query import (
    clear_weaving_grid_value_query,
    find_exact_weaving_grid_row_query,
    get_weaving_entry_machines_query,
    get_weaving_target_map_list_query,
    get_weaving_target_map_row_query,
    get_weaving_target_qualities_query,
    insert_weaving_target_map_query,
    resolve_weaving_grid_cells_batch_query,
    update_weaving_grid_value_query,
)


router = APIRouter()

# Weaving is two-dimensional: id_type is 'mcid' (ref_id=machine_id, a LOOM) or 'qid'
# (ref_id=weaving_quality_id); value_role is standard | target | actual.
ID_TYPES = [WEAVING_ID_TYPE_MC, WEAVING_ID_TYPE_QLTY]
# 'actual' = loom speed (mcid) captured on the Weaving SQC page; reuses these same
# endpoints (value_role='actual', param 'speed' as-of effective_date). Actual picks are
# owned by vw_weaving_pick_act (no qid actual param). No new router/table.
VALUE_ROLES = list(WEAVING_VALUE_ROLES)
# Union of every valid param across both id_types / all value_roles (for _validate_enums).
# Machine (mcid): speed (std / target / actual). Quality (qid): picks, eff (std), eff (target).
PARAMS = list(
    dict.fromkeys(
        list(WEAVING_MC_PARAMS_STD)
        + list(WEAVING_MC_PARAMS_TARGET)
        + list(WEAVING_MC_PARAMS_ACTUAL)
        + list(WEAVING_QID_PARAMS_STD)
        + list(WEAVING_QID_PARAMS_TARGET)
    )
)

TARGET_MAP_NOT_FOUND_MSG = "Standards/targets row not found"


def grid_params_for(id_type: str, value_role: str) -> List[str]:
    """Ordered valid params for an inline-grid (id_type, value_role) combination.

    Single source of truth for target_map_grid (which columns to resolve),
    target_map_bulk_save (which params a cell may carry) AND the create cross-dimension
    guard. LOCKED CONTRACT (two-dimensional, mirrors beaming):
      * mcid + standard -> speed
      * mcid + target   -> speed
      * mcid + actual   -> speed   (loom speed, Weaving SQC "Actual Speed" tab)
      * qid  + standard -> picks, eff
      * qid  + target   -> eff
      * qid  + actual   -> []      (NONE: actual picks owned by vw_weaving_pick_act;
                                    actual speed is the mcid dimension)
    Returns [] for an unknown combination; callers validate id_type / value_role enums
    separately.
    """
    if id_type == WEAVING_ID_TYPE_MC:
        if value_role == "standard":
            return list(WEAVING_MC_PARAMS_STD)
        if value_role == "target":
            return list(WEAVING_MC_PARAMS_TARGET)
        if value_role == "actual":
            return list(WEAVING_MC_PARAMS_ACTUAL)
    if id_type == WEAVING_ID_TYPE_QLTY:
        if value_role == "standard":
            return list(WEAVING_QID_PARAMS_STD)
        if value_role == "target":
            return list(WEAVING_QID_PARAMS_TARGET)
    return []


# =============================================================================
# Pydantic models
# =============================================================================


class TargetMapCreate(BaseModel):
    co_id: int
    branch_id: Optional[int] = None
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
    effective_date: date
    id_type: str
    value_role: str
    cells: List[CellItem] = Field(default_factory=list)


# =============================================================================
# Helpers
# =============================================================================
#
# _require_co_id / _optional_branch_id / _f / _i are mirrored EXACTLY from
# beaming_target_map.py (kept inline rather than imported so this master CRUD does not
# couple to the beaming module).


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


def _validate_enums(id_type: str, value_role: str, param: str) -> None:
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


# =============================================================================
# Setup
# =============================================================================


@router.get("/target_map_setup")
def target_map_setup(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    co_id = _require_co_id(request)
    branch_id = _optional_branch_id(request)
    try:
        # Machine (mcid) refs: Loom-type machines (resolve by NAME 'Loom'). The FE picks
        # one as the mcid ref for the loom 'speed' standard / target / actual.
        machines = []
        for r in db.execute(
            get_weaving_entry_machines_query(),
            {"co_id": co_id, "loom_type": WEAVING_MACHINE_TYPE_NAME, "branch_id": branch_id},
        ).fetchall():
            m = dict(r._mapping)
            machines.append(
                {
                    "machine_id": m["machine_id"],
                    "machine_name": m["machine_name"],
                    "mech_code": m["mech_code"],
                    "branch_id": m.get("branch_id"),
                }
            )

        # Quality (qid) refs: active Weaving qualities (company-scoped). The FE picks one
        # as the qid ref for picks / eff standards & target eff.
        qualities = []
        for r in db.execute(
            get_weaving_target_qualities_query(),
            {"co_id": co_id, "branch_id": branch_id},
        ).fetchall():
            q = dict(r._mapping)
            qualities.append(
                {
                    "weaving_quality_id": q["weaving_quality_id"],
                    "weaving_quality_code": q["weaving_quality_code"],
                    "weaving_quality_name": q["weaving_quality_name"],
                    "branch_id": q.get("branch_id"),
                }
            )

        return {
            "data": {
                "machines": machines,
                "qualities": qualities,
                "id_types": ID_TYPES,
                "value_roles": VALUE_ROLES,
                "params": PARAMS,
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
    id_type = _optional_enum(request, "id_type", ID_TYPES)
    ref_id = _optional_ref_id(request)
    value_role = _optional_enum(request, "value_role", VALUE_ROLES)
    param = _optional_enum(request, "param", PARAMS)
    try:
        rows = db.execute(
            get_weaving_target_map_list_query(),
            {
                "co_id": co_id,
                "branch_id": branch_id,
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
                    "weaving_target_map_id": m["weaving_target_map_id"],
                    "co_id": m["co_id"],
                    "branch_id": m.get("branch_id"),
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
        _validate_enums(body.id_type, body.value_role, body.param)
        # Cross-dimension guard: the param must be valid for THIS (id_type, value_role)
        # -- _validate_enums only checks the global union, so without this an actual-only
        # param combination could be written under a value_role that never resolves it.
        if body.param not in grid_params_for(body.id_type, body.value_role):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid param '{body.param}' for {body.id_type}/{body.value_role}",
            )
        user_id = token_data.get("user_id")
        result = db.execute(
            insert_weaving_target_map_query(),
            {
                "co_id": int(body.co_id),
                "branch_id": body.branch_id,
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
        return {"data": {"weaving_target_map_id": result.lastrowid}}
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
            get_weaving_target_map_row_query(), {"id": target_map_id}
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
                f"UPDATE jute_prod_weaving_target_map SET {', '.join(sets)} "
                "WHERE weaving_target_map_id = :id"
            ),
            params,
        )
        db.commit()
        return {"data": {"weaving_target_map_id": target_map_id}}
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
            get_weaving_target_map_row_query(), {"id": target_map_id}
        ).fetchone()
        if not existing or existing._mapping["co_id"] != co_id:
            raise HTTPException(status_code=404, detail=TARGET_MAP_NOT_FOUND_MSG)

        user_id = token_data.get("user_id")
        db.execute(
            text(
                "UPDATE jute_prod_weaving_target_map SET active = 0, updated_by = :updated_by "
                "WHERE weaving_target_map_id = :id"
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
    """One row per ref (loom | quality), one cell per valid param.

    Each cell is resolved the SAME WAY production reads it -- the active row with
    MAX(effective_date) <= effective_date for (co_id, ref_id, id_type, value_role,
    param), with NO branch filter (mirrors weaving_standards resolution). A param key
    is omitted from a cell when no active row resolves. is_exact = (source_date ==
    effective_date) so the UI can mark inherited vs set-here cells. Two-dimensional:
    id_type='mcid' lists looms, id_type='qid' lists qualities. The SQC "Actual Speed"
    tab reuses this endpoint with id_type='mcid' & value_role='actual'.
    """
    co_id = _require_co_id(request)
    branch_id = _optional_branch_id(request)
    id_type = _require_enum(request, "id_type", ID_TYPES)
    value_role = _require_enum(request, "value_role", VALUE_ROLES)
    effective_date = _require_date(request, "effective_date")
    try:
        params = grid_params_for(id_type, value_role)

        # Source list (same source as target_map_setup): Loom-type machines for
        # id_type='mcid', active Weaving qualities for id_type='qid'. The grid ref label
        # uses mech_code/machine_name (mcid) or weaving_quality_code/weaving_quality_name
        # (qid). branch_id scopes ONLY which refs are listed -- value resolution itself
        # never filters by branch (resolve parity).
        refs = []
        if id_type == WEAVING_ID_TYPE_MC:
            for r in db.execute(
                get_weaving_entry_machines_query(),
                {
                    "co_id": co_id,
                    "loom_type": WEAVING_MACHINE_TYPE_NAME,
                    "branch_id": branch_id,
                },
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
                get_weaving_target_qualities_query(),
                {"co_id": co_id, "branch_id": branch_id},
            ).fetchall():
                q = dict(r._mapping)
                refs.append(
                    {
                        "ref_id": q["weaving_quality_id"],
                        "ref_code": q["weaving_quality_code"],
                        "ref_name": q["weaving_quality_name"],
                    }
                )

        # ONE batch resolve for the whole grid (rn=1 per ref_id+param — same
        # last-date + newest-id tiebreak the per-cell probe used), then dict-keyed
        # lookups. Kills the refs x params N+1.
        cell_map = {}
        for r in db.execute(
            resolve_weaving_grid_cells_batch_query(),
            {
                "co_id": co_id,
                "id_type": id_type,
                "value_role": value_role,
                "on_date": effective_date,
            },
        ).fetchall():
            cell_map[(int(r.ref_id), r.param)] = r

        rows = []
        for ref in refs:
            cells = {}
            for param in params:
                resolved = cell_map.get((int(ref["ref_id"]), param))
                # Omit the param key when no active row resolves (or value is NULL).
                if resolved is None or resolved.value is None:
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

        return {"data": {"params": params, "rows": rows}}
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
    """Upsert/clear grid cells at the EXACT key in ONE transaction (commit once).

    For each cell, finds the ACTIVE row at the exact key (co_id, ref_id, id_type,
    value_role, param, effective_date), BRANCH-AGNOSTIC so save targets the same row
    the grid prefilled (grid/production resolution ignore branch_id):
      * value null/empty -> if found set active=0 (clear); else no-op
      * value present     -> if found UPDATE value; else INSERT a new active row
    Every cell's param must be valid for (id_type, value_role) -> 400 otherwise;
    a negative value -> 400. Any error rolls the whole batch back. The Weaving SQC page
    reuses this endpoint with value_role='actual' (no extra code).
    """
    try:
        if body.id_type not in ID_TYPES:
            raise HTTPException(
                status_code=400, detail=f"Invalid id_type '{body.id_type}'"
            )
        if body.value_role not in VALUE_ROLES:
            raise HTTPException(
                status_code=400, detail=f"Invalid value_role '{body.value_role}'"
            )

        allowed_params = grid_params_for(body.id_type, body.value_role)
        user_id = token_data.get("user_id")
        co_id = int(body.co_id)
        branch_id = body.branch_id
        effective_date = body.effective_date

        find_q = find_exact_weaving_grid_row_query()
        update_q = update_weaving_grid_value_query()
        clear_q = clear_weaving_grid_value_query()
        insert_q = insert_weaving_target_map_query()

        inserted = 0
        updated = 0
        cleared = 0

        for cell in body.cells:
            if cell.param not in allowed_params:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Invalid param '{cell.param}' for "
                        f"{body.id_type}/{body.value_role}"
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
                "ref_id": int(cell.ref_id),
                "id_type": body.id_type,
                "value_role": body.value_role,
                "param": cell.param,
                "effective_date": effective_date,
                "branch_id": branch_id,
            }
            existing = db.execute(find_q, key).fetchone()

            if cell.value is None:
                # Clear: soft-delete the exact-key active row if present; else no-op.
                if existing:
                    db.execute(
                        clear_q,
                        {"id": existing.weaving_target_map_id, "updated_by": user_id},
                    )
                    cleared += 1
                continue

            value = float(cell.value)
            if existing:
                db.execute(
                    update_q,
                    {
                        "id": existing.weaving_target_map_id,
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
                        "effective_date": effective_date,
                        "ref_id": int(cell.ref_id),
                        "id_type": body.id_type,
                        "value_role": body.value_role,
                        "param": cell.param,
                        "value": value,
                        "updated_by": user_id,
                    },
                )
                inserted += 1

        db.commit()
        return {
            "data": {"inserted": inserted, "updated": updated, "cleared": cleared}
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
