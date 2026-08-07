"""Weaving Pick-SQC capture endpoints (jute SQC module).

One capture surface feeds the weaving planning grid:
  * jute_sqc_weaving_pick - multi-observation pick readings. Each save is a NEW
    reading (insert-only, no upsert); Act Picks(date, quality) = AVG(picks),
    surfaced via vw_weaving_pick_act and resolved downstream by last-date.

Portal persona: get_tenant_db + get_current_user_with_refresh, {"data": ...}
responses, _require_co_id / _optional_branch_id / _require_entry_date / _f / _i
helpers mirrored from spinning_sqc.py, and the try/except pattern (GET:
HTTPException re-raise, ValueError 400, Exception 500; POST/DELETE: rollback
before raise/500).

The loom list (loom-type machines) and weaving-quality lookups are reused
directly from src/juteProduction/weaving_query.py.
"""

from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.authorization.utils import get_current_user_with_refresh
from src.config.db import get_tenant_db
from src.juteProduction.constants import WEAVING_MACHINE_TYPE_NAME
from src.juteProduction.weaving_query import (
    get_weaving_entry_machines_query,
    get_weaving_entry_qualities_query,
)
# Shared spell-resolution contract (spell_id preferred, branch-scoped code fallback,
# NO global fallback) — import, do NOT copy. See spinning_entry._resolve_spell.
from src.juteProduction.spinning_entry import _resolve_spell
from src.juteSQC.weaving_sqc_query import (
    get_weaving_pick_active_row_query,
    get_weaving_pick_readings_by_date_query,
    get_weaving_pick_summary_query,
    insert_weaving_pick_query,
    soft_delete_weaving_pick_query,
)


router = APIRouter()

PICK_NOT_FOUND_MSG = "SQC pick reading not found"


# =============================================================================
# Pydantic models
# =============================================================================


class WeavingPickRow(BaseModel):
    weaving_quality_id: int
    machine_id: int
    width: Optional[float] = Field(default=None, ge=0)
    picks: float = Field(ge=0)


class WeavingPickSave(BaseModel):
    co_id: int
    branch_id: Optional[int] = None
    entry_date: date
    # Optional spell: spell_id (preferred, branch-validated) or DEPRECATED spell CODE
    # (branch-scoped fallback); stamped on every reading of the batch (Phase 1c
    # join-key hygiene). Neither => NULL.
    spell_id: Optional[int] = None
    spell: Optional[str] = None
    entries: List[WeavingPickRow] = Field(default_factory=list)


# =============================================================================
# Helpers (mirrored from spinning_sqc.py)
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


def _require_entry_date(request: Request) -> date:
    raw = request.query_params.get("entry_date")
    if not raw:
        raise HTTPException(status_code=400, detail="entry_date is required")
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid entry_date format")


def _f(v, default: float = 0.0) -> float:
    """Cast a possibly-None / Decimal value to float."""
    return default if v is None else float(v)


def _i(v, default: Optional[int] = None) -> Optional[int]:
    return default if v is None else int(v)


def _fetch_looms(db: Session, branch_id: Optional[int]) -> list:
    looms = []
    for r in db.execute(
        get_weaving_entry_machines_query(),
        {"loom_type": WEAVING_MACHINE_TYPE_NAME, "branch_id": branch_id},
    ).fetchall():
        m = dict(r._mapping)
        looms.append(
            {
                "machine_id": m["machine_id"],
                "machine_name": m["machine_name"],
                "mech_code": m["mech_code"],
                "line_no": m.get("line_no"),
                "branch_id": m.get("branch_id"),
            }
        )
    return looms


def _fetch_qualities(db: Session, co_id: int) -> list:
    qualities = []
    for r in db.execute(
        get_weaving_entry_qualities_query(), {"co_id": co_id, "item_id": None}
    ).fetchall():
        m = dict(r._mapping)
        qualities.append(
            {
                "weaving_quality_id": m["weaving_quality_id"],
                "item_id": m.get("item_id"),
                "item_code": m.get("item_code"),
                "item_name": m.get("item_name"),
                "weaving_quality_code": m.get("weaving_quality_code"),
                "weaving_quality_name": m.get("weaving_quality_name"),
            }
        )
    return qualities


def _reading_row_out(r) -> dict:
    m = dict(r._mapping)
    return {
        "weaving_sqc_pick_id": m["weaving_sqc_pick_id"],
        "co_id": m["co_id"],
        "branch_id": m.get("branch_id"),
        "entry_date": str(m["entry_date"]) if m.get("entry_date") is not None else None,
        "weaving_quality_id": m.get("weaving_quality_id"),
        "weaving_quality_code": m.get("weaving_quality_code"),
        "weaving_quality_name": m.get("weaving_quality_name"),
        "item_code": m.get("item_code"),
        "item_name": m.get("item_name"),
        "machine_id": m.get("machine_id"),
        "mech_code": m.get("mech_code"),
        "machine_name": m.get("machine_name"),
        "line_no": m.get("line_no"),
        "width": None if m.get("width") is None else _f(m.get("width")),
        "picks": _f(m.get("picks")),
    }


def _summary_row_out(r) -> dict:
    m = dict(r._mapping)
    return {
        "weaving_quality_id": m.get("weaving_quality_id"),
        "weaving_quality_code": m.get("weaving_quality_code"),
        "weaving_quality_name": m.get("weaving_quality_name"),
        "avg_picks": _f(m.get("avg_picks")),
        "std_picks": _f(m.get("std_picks")),
        "min_picks": _f(m.get("min_picks")),
        "max_picks": _f(m.get("max_picks")),
        "avg_width": None if m.get("avg_width") is None else _f(m.get("avg_width")),
        "min_width": None if m.get("min_width") is None else _f(m.get("min_width")),
        "max_width": None if m.get("max_width") is None else _f(m.get("max_width")),
        "n_obs": _i(m.get("n_obs"), 0),
    }


# =============================================================================
# jute_sqc_weaving_pick — multi-observation pick readings
# =============================================================================


@router.get("/weaving_sqc_pick_setup")
def weaving_sqc_pick_setup(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    co_id = _require_co_id(request)
    branch_id = _optional_branch_id(request)
    entry_date = _require_entry_date(request)
    try:
        qualities = _fetch_qualities(db, co_id)
        looms = _fetch_looms(db, branch_id)
        reading_rows = db.execute(
            get_weaving_pick_readings_by_date_query(),
            {"co_id": co_id, "entry_date": entry_date, "branch_id": branch_id},
        ).fetchall()
        readings = [_reading_row_out(r) for r in reading_rows]
        summary_rows = db.execute(
            get_weaving_pick_summary_query(),
            {"co_id": co_id, "entry_date": entry_date},
        ).fetchall()
        summary = [_summary_row_out(r) for r in summary_rows]
        return {
            "data": {
                "qualities": qualities,
                "looms": looms,
                "readings": readings,
                "summary": summary,
            }
        }
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid entry_date format")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/weaving_sqc_pick_save")
def weaving_sqc_pick_save(
    body: WeavingPickSave,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Insert-only, multi-observation save (no upsert). Each entry is a NEW
    pick reading; Act Picks resolves downstream as AVG(picks) per quality/date.
    An optional body.spell (code) is resolved branch-aware once and stamped on
    every reading (spell_id NULL when omitted)."""
    try:
        user_id = token_data.get("user_id")
        spell_id = None
        if body.spell_id is not None or body.spell:
            spell_id = _resolve_spell(db, body.spell_id, body.spell, _i(body.branch_id))
        saved = 0
        for e in body.entries:
            db.execute(
                insert_weaving_pick_query(),
                {
                    "co_id": body.co_id,
                    "branch_id": body.branch_id,
                    "entry_date": body.entry_date,
                    "weaving_quality_id": int(e.weaving_quality_id),
                    "machine_id": int(e.machine_id),
                    "spell_id": spell_id,
                    "width": None if e.width is None else float(e.width),
                    "picks": float(e.picks),
                    "updated_by": user_id,
                },
            )
            saved += 1
        db.commit()
        return {"data": {"saved": saved}}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/weaving_sqc_pick_by_date")
def weaving_sqc_pick_by_date(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    co_id = _require_co_id(request)
    branch_id = _optional_branch_id(request)
    entry_date = _require_entry_date(request)
    try:
        reading_rows = db.execute(
            get_weaving_pick_readings_by_date_query(),
            {"co_id": co_id, "entry_date": entry_date, "branch_id": branch_id},
        ).fetchall()
        readings = [_reading_row_out(r) for r in reading_rows]
        summary_rows = db.execute(
            get_weaving_pick_summary_query(),
            {"co_id": co_id, "entry_date": entry_date},
        ).fetchall()
        summary = [_summary_row_out(r) for r in summary_rows]
        return {"data": {"readings": readings, "summary": summary}}
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid entry_date format")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/weaving_sqc_pick_delete/{pick_id}")
def weaving_sqc_pick_delete(
    pick_id: int,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        existing = db.execute(
            get_weaving_pick_active_row_query(),
            {"id": pick_id},
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail=PICK_NOT_FOUND_MSG)

        db.execute(
            soft_delete_weaving_pick_query(),
            {"id": pick_id, "updated_by": token_data.get("user_id")},
        )
        db.commit()
        return {"data": {"message": "Deleted"}}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
