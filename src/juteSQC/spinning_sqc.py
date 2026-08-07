"""Spinning SQC capture endpoints (jute SQC module).

Two capture surfaces feed the spinning planning grid:
  * jute_sqc_spinning_entry  - single-value actual Speed/TPI per (date, machine,
    quality). Upsert one active row per key (last value wins; resolved downstream
    by last-date).
  * jute_sqc_spinning_count  - multi-observation count readings. Each save is a
    NEW reading (no upsert); Act Count(date, quality) = AVG(observed_count).

Portal persona: get_tenant_db + get_current_user_with_refresh, {"data": ...}
responses, _require_co_id / _optional_branch_id / _f / _i helpers mirrored from
spinning_entry.py, and the try/except pattern (GET: HTTPException re-raise,
ValueError 400, Exception 500; POST/PUT/DELETE: rollback before raise/500).

The machine list (spinning-type) and yarn-quality / spell lookups are reused
directly from src/juteProduction/spinning_query.py.
"""

import statistics
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.authorization.utils import get_current_user_with_refresh
from src.config.db import get_tenant_db
from src.juteProduction.constants import SPINNING_MACHINE_TYPE_NAME
from src.juteProduction.spinning_query import (
    get_spells_query,
    get_spinning_machines_query,
    get_yarn_qualities_query,
)
from src.juteSQC.spinning_sqc_query import (
    get_quality_std_mr_query,
    get_sqc_count_active_row_query,
    get_sqc_count_avg_query,
    get_sqc_count_by_date_query,
    get_sqc_count_obs_mr_avg_query,
    get_sqc_entry_active_row_query,
    get_sqc_entry_by_date_query,
    get_sqc_qr_cv_active_row_query,
    get_sqc_qr_cv_by_date_query,
    get_sqc_qr_cv_dtl_query,
    get_sqc_rhmr_active_row_query,
    get_sqc_rhmr_by_id_query,
    get_sqc_rhmr_search_query,
    insert_sqc_count_query,
    insert_sqc_entry_query,
    insert_sqc_qr_cv_dtl_query,
    insert_sqc_qr_cv_header_query,
    insert_sqc_rhmr_query,
    soft_delete_sqc_count_query,
    soft_delete_sqc_qr_cv_query,
    soft_delete_sqc_rhmr_query,
    update_sqc_entry_query,
    update_sqc_rhmr_query,
)


router = APIRouter()

COUNT_NOT_FOUND_MSG = "SQC count reading not found"
RHMR_NOT_FOUND_MSG = "SQC RHMR reading not found"
QR_CV_NOT_FOUND_MSG = "SQC QR/CV group not found"


# =============================================================================
# Pydantic models
# =============================================================================


class SqcEntryRow(BaseModel):
    mc_id: int
    item_id: int
    actual_speed: Optional[float] = Field(default=None, ge=0)
    actual_tpi: Optional[float] = Field(default=None, ge=0)


class SqcEntrySave(BaseModel):
    co_id: int
    branch_id: Optional[int] = None
    entry_date: date
    entries: List[SqcEntryRow] = Field(default_factory=list)


class SqcCountRow(BaseModel):
    """One R-08-16 reading. The operator enters DP, TP, WT/450 YDS (gms) and MR%;
    observed_count and corrected_count are RECOMPUTED server-side (any values sent
    from the FE are ignored — the FE only shows them as a preview)."""

    spell_id: Optional[int] = None
    mc_id: Optional[int] = None
    item_id: int
    dp: Optional[float] = Field(default=None, ge=0)
    tp: Optional[float] = Field(default=None, ge=0)
    wt_450_gms: Optional[float] = Field(default=None, ge=0)
    mr_pct: Optional[float] = Field(default=None, ge=0)
    # Accepted for backward-compat / FE preview, but the server recomputes them.
    observed_count: Optional[float] = Field(default=None, ge=0)
    corrected_count: Optional[float] = Field(default=None, ge=0)


class SqcCountSave(BaseModel):
    co_id: int
    branch_id: Optional[int] = None
    entry_date: date
    entries: List[SqcCountRow] = Field(default_factory=list)


class SqcRhmrSave(BaseModel):
    """One RHMR reading. Upsert per (co, date, spell): set confirm=True to
    overwrite an existing active row (the first call returns exists=True instead)."""

    co_id: int
    branch_id: Optional[int] = None
    entry_date: date
    spell_id: int
    temperature: Optional[float] = Field(default=None, ge=0)
    humidity: Optional[float] = Field(default=None, ge=0)
    confirm: bool = False


class SqcQrCvSpindle(BaseModel):
    """One spindle's readings within a QR/CV group (up to 5 b/s readings)."""

    spindle_no: int
    readings: List[Optional[float]] = Field(default_factory=list)  # up to 5


class SqcQrCvRow(BaseModel):
    """One QR/CV group = machine + yarn item + 6 spindles (30 readings)."""

    mc_id: Optional[int] = None
    item_id: int
    spindles: List[SqcQrCvSpindle] = Field(default_factory=list)


class SqcQrCvSave(BaseModel):
    co_id: int
    branch_id: Optional[int] = None
    entry_date: date
    entries: List[SqcQrCvRow] = Field(default_factory=list)


# =============================================================================
# Helpers (mirrored from spinning_entry.py)
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


# R-08-16 count calculation (mirrors the FE spinningCalc util).
#   observed  = round( (wt_450_gms / 450) * (14400 / 454), 2 )
#   corrected = round( observed / (100 + mr_pct) * (100 + std_mr_pct), 2 )
_COUNT_FACTOR = 14400.0 / 454.0


def _observed_count(wt_450_gms) -> Optional[float]:
    if wt_450_gms is None:
        return None
    wt = float(wt_450_gms)
    if wt <= 0:
        return None
    return round((wt / 450.0) * _COUNT_FACTOR, 2)


def _corrected_count(observed, mr_pct, std_mr_pct) -> Optional[float]:
    if observed is None or mr_pct is None or std_mr_pct is None:
        return None
    denom = 100.0 + float(mr_pct)
    if denom == 0:
        return None
    return round((float(observed) / denom) * (100.0 + float(std_mr_pct)), 2)


def _require_entry_date(request: Request) -> date:
    raw = request.query_params.get("entry_date")
    if not raw:
        raise HTTPException(status_code=400, detail="entry_date is required")
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid entry_date format")


def _optional_entry_date(request: Request) -> Optional[date]:
    raw = request.query_params.get("entry_date")
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid entry_date format")


def _optional_spell_id(request: Request) -> Optional[int]:
    raw = request.query_params.get("spell_id")
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid spell_id")


def _fetch_machines(db: Session, co_id: int, branch_id: Optional[int]) -> list:
    machines = []
    for r in db.execute(
        get_spinning_machines_query(),
        {"co_id": co_id, "spinning_type": SPINNING_MACHINE_TYPE_NAME, "branch_id": branch_id},
    ).fetchall():
        m = dict(r._mapping)
        machines.append(
            {
                "machine_id": m["machine_id"],
                "machine_name": m["machine_name"],
                "mech_code": m["mech_code"],
                "branch_id": m["branch_id"],
            }
        )
    return machines


def _fetch_qualities(db: Session, co_id: int, branch_id: Optional[int]) -> list:
    yarn_items = []
    for r in db.execute(
        get_yarn_qualities_query(), {"co_id": co_id, "branch_id": branch_id}
    ).fetchall():
        m = dict(r._mapping)
        yarn_items.append(
            {
                "item_id": m["item_id"],
                "item_code": m["item_code"],
                "item_name": m.get("item_name"),
                "std_count": _f(m.get("std_count")) if m.get("std_count") is not None else None,
                "std_mr_pct": None if m.get("std_mr_pct") is None else _f(m.get("std_mr_pct")),
            }
        )
    return yarn_items


def _fetch_spells(db: Session, branch_id: Optional[int]) -> list:
    spells = []
    seen = set()
    for r in db.execute(get_spells_query(), {"branch_id": branch_id}).fetchall():
        m = dict(r._mapping)
        code = m["spell_code"]
        if code in seen:
            continue
        seen.add(code)
        spells.append(
            {
                "spell_code": code,
                "spell_name": m["spell_name"],
                "spell_id": int(m["spell_id"]),
                "working_hours": _f(m.get("working_hours")),
            }
        )
    return spells


def _entry_row_out(r) -> dict:
    m = dict(r._mapping)
    return {
        "spinning_sqc_entry_id": m["spinning_sqc_entry_id"],
        "co_id": m["co_id"],
        "branch_id": m.get("branch_id"),
        "entry_date": str(m["entry_date"]) if m.get("entry_date") is not None else None,
        "mc_id": m.get("mc_id"),
        "mech_code": m.get("mech_code"),
        "machine_name": m.get("machine_name"),
        "item_id": m.get("item_id"),
        "item_code": m.get("item_code"),
        "item_name": m.get("item_name"),
        "actual_speed": _f(m.get("actual_speed")) if m.get("actual_speed") is not None else None,
        "actual_tpi": _f(m.get("actual_tpi")) if m.get("actual_tpi") is not None else None,
    }


def _count_row_out(r) -> dict:
    m = dict(r._mapping)
    return {
        "spinning_sqc_count_id": m["spinning_sqc_count_id"],
        "co_id": m["co_id"],
        "branch_id": m.get("branch_id"),
        "entry_date": str(m["entry_date"]) if m.get("entry_date") is not None else None,
        "spell_id": m.get("spell_id"),
        "spell_code": m.get("spell_code"),
        "mc_id": m.get("mc_id"),
        "mech_code": m.get("mech_code"),
        "machine_name": m.get("machine_name"),
        "item_id": m.get("item_id"),
        "item_code": m.get("item_code"),
        "item_name": m.get("item_name"),
        "std_mr_pct": None if m.get("std_mr_pct") is None else _f(m.get("std_mr_pct")),
        "dp": None if m.get("dp") is None else _f(m.get("dp")),
        "tp": None if m.get("tp") is None else _f(m.get("tp")),
        "wt_450_gms": None if m.get("wt_450_gms") is None else _f(m.get("wt_450_gms")),
        "mr_pct": None if m.get("mr_pct") is None else _f(m.get("mr_pct")),
        "observed_count": _f(m.get("observed_count")),
        "corrected_count": None if m.get("corrected_count") is None else _f(m.get("corrected_count")),
    }


def _rhmr_row_out(r) -> dict:
    m = dict(r._mapping)
    return {
        "spinning_sqc_rhmr_id": m["spinning_sqc_rhmr_id"],
        "co_id": m["co_id"],
        "branch_id": m.get("branch_id"),
        "entry_date": str(m["entry_date"]) if m.get("entry_date") is not None else None,
        "spell_id": m.get("spell_id"),
        "spell_code": m.get("spell_code"),
        "spell_name": m.get("spell_name"),
        "temperature": None if m.get("temperature") is None else _f(m.get("temperature")),
        "humidity": None if m.get("humidity") is None else _f(m.get("humidity")),
    }


# =============================================================================
# jute_sqc_spinning_entry — single-value actual Speed / TPI
# =============================================================================


@router.get("/sqc_entry_setup")
def sqc_entry_setup(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    co_id = _require_co_id(request)
    branch_id = _optional_branch_id(request)
    entry_date = _require_entry_date(request)
    try:
        machines = _fetch_machines(db, co_id, branch_id)
        yarn_items = _fetch_qualities(db, co_id, branch_id)
        rows = db.execute(
            get_sqc_entry_by_date_query(),
            {"co_id": co_id, "entry_date": entry_date, "branch_id": branch_id},
        ).fetchall()
        entries = [_entry_row_out(r) for r in rows]
        return {
            "data": {
                "machines": machines,
                "yarn_items": yarn_items,
                "entries": entries,
            }
        }
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid entry_date format")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sqc_entry_save")
def sqc_entry_save(
    body: SqcEntrySave,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        user_id = token_data.get("user_id")
        saved = 0
        for e in body.entries:
            actual_speed = float(e.actual_speed) if e.actual_speed is not None else None
            actual_tpi = float(e.actual_tpi) if e.actual_tpi is not None else None
            existing = db.execute(
                get_sqc_entry_active_row_query(),
                {
                    "co_id": body.co_id,
                    "entry_date": body.entry_date,
                    "mc_id": int(e.mc_id),
                    "item_id": int(e.item_id),
                },
            ).fetchone()
            if existing:
                db.execute(
                    update_sqc_entry_query(),
                    {
                        "id": existing.spinning_sqc_entry_id,
                        "actual_speed": actual_speed,
                        "actual_tpi": actual_tpi,
                        "updated_by": user_id,
                    },
                )
            else:
                db.execute(
                    insert_sqc_entry_query(),
                    {
                        "co_id": body.co_id,
                        "branch_id": body.branch_id,
                        "entry_date": body.entry_date,
                        "mc_id": int(e.mc_id),
                        "item_id": int(e.item_id),
                        "actual_speed": actual_speed,
                        "actual_tpi": actual_tpi,
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


@router.get("/sqc_entry_by_date")
def sqc_entry_by_date(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    co_id = _require_co_id(request)
    branch_id = _optional_branch_id(request)
    entry_date = _require_entry_date(request)
    try:
        rows = db.execute(
            get_sqc_entry_by_date_query(),
            {"co_id": co_id, "entry_date": entry_date, "branch_id": branch_id},
        ).fetchall()
        return {"data": [_entry_row_out(r) for r in rows]}
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid entry_date format")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# jute_sqc_spinning_count — multi-observation count
# =============================================================================


@router.get("/sqc_count_setup")
def sqc_count_setup(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    co_id = _require_co_id(request)
    branch_id = _optional_branch_id(request)
    entry_date = _require_entry_date(request)
    try:
        machines = _fetch_machines(db, co_id, branch_id)
        yarn_items = _fetch_qualities(db, co_id, branch_id)
        spells = _fetch_spells(db, branch_id)
        rows = db.execute(
            get_sqc_count_by_date_query(),
            {"co_id": co_id, "entry_date": entry_date, "branch_id": branch_id},
        ).fetchall()
        entries = [_count_row_out(r) for r in rows]
        return {
            "data": {
                "machines": machines,
                "yarn_items": yarn_items,
                "spells": spells,
                "entries": entries,
            }
        }
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid entry_date format")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sqc_count_save")
def sqc_count_save(
    body: SqcCountSave,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        user_id = token_data.get("user_id")
        saved = 0
        std_mr_cache: dict = {}  # item_id -> std_mr_pct (one lookup per yarn item)
        for e in body.entries:
            qid = int(e.item_id)
            if qid not in std_mr_cache:
                row = db.execute(get_quality_std_mr_query(), {"item_id": qid}).fetchone()
                std_mr_cache[qid] = None if row is None else row._mapping.get("std_mr_pct")
            std_mr = std_mr_cache[qid]

            # Recompute from raw inputs (never trust the FE values); fall back to a
            # directly-supplied observed_count for backward compatibility.
            observed = _observed_count(e.wt_450_gms)
            if observed is None and e.observed_count is not None:
                observed = round(float(e.observed_count), 2)
            corrected = _corrected_count(observed, e.mr_pct, std_mr)

            db.execute(
                insert_sqc_count_query(),
                {
                    "co_id": body.co_id,
                    "branch_id": body.branch_id,
                    "entry_date": body.entry_date,
                    "spell_id": _i(e.spell_id),
                    "mc_id": _i(e.mc_id),
                    "item_id": qid,
                    "dp": None if e.dp is None else float(e.dp),
                    "tp": None if e.tp is None else float(e.tp),
                    "wt_450_gms": None if e.wt_450_gms is None else float(e.wt_450_gms),
                    "mr_pct": None if e.mr_pct is None else float(e.mr_pct),
                    "observed_count": observed if observed is not None else 0.0,
                    "corrected_count": corrected,
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


@router.get("/sqc_count_by_date")
def sqc_count_by_date(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    co_id = _require_co_id(request)
    branch_id = _optional_branch_id(request)
    entry_date = _require_entry_date(request)
    try:
        rows = db.execute(
            get_sqc_count_by_date_query(),
            {"co_id": co_id, "entry_date": entry_date, "branch_id": branch_id},
        ).fetchall()
        readings = [_count_row_out(r) for r in rows]

        avg_rows = db.execute(
            get_sqc_count_avg_query(),
            {"co_id": co_id, "entry_date": entry_date, "branch_id": branch_id},
        ).fetchall()
        averages = []
        for r in avg_rows:
            m = dict(r._mapping)
            averages.append(
                {
                    "item_id": m["item_id"],
                    "item_code": m.get("item_code"),
                    "item_name": m.get("item_name"),
                    "avg_count": _f(m.get("avg_count")),
                    "avg_corrected": None if m.get("avg_corrected") is None else _f(m.get("avg_corrected")),
                    "obs_count": _i(m.get("obs_count"), 0),
                }
            )
        return {"data": {"readings": readings, "averages": averages}}
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid entry_date format")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/sqc_count_delete/{count_id}")
def sqc_count_delete(
    count_id: int,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        existing = db.execute(
            get_sqc_count_active_row_query(),
            {"id": count_id},
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail=COUNT_NOT_FOUND_MSG)

        db.execute(
            soft_delete_sqc_count_query(),
            {"id": count_id, "updated_by": token_data.get("user_id")},
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
# jute_sqc_spinning_rhmr — RHMR (Temperature / Humidity per date + spell)
# =============================================================================


@router.get("/sqc_rhmr_setup")
def sqc_rhmr_setup(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    _require_co_id(request)
    branch_id = _optional_branch_id(request)
    try:
        spells = _fetch_spells(db, branch_id)
        return {"data": {"spells": spells}}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sqc_rhmr_search")
def sqc_rhmr_search(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    co_id = _require_co_id(request)
    branch_id = _optional_branch_id(request)
    entry_date = _optional_entry_date(request)
    spell_id = _optional_spell_id(request)
    try:
        rows = db.execute(
            get_sqc_rhmr_search_query(),
            {
                "co_id": co_id,
                "entry_date": entry_date,
                "spell_id": spell_id,
                "branch_id": branch_id,
            },
        ).fetchall()
        return {"data": {"rows": [_rhmr_row_out(r) for r in rows]}}
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid query parameter")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sqc_rhmr_save")
def sqc_rhmr_save(
    body: SqcRhmrSave,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Upsert one RHMR row per (co, date, spell).

    If an active row already exists and confirm is False, return
    {"exists": True, "existing": {...}} WITHOUT writing — the caller shows the
    existing values and re-sends with confirm=True to overwrite.
    """
    try:
        user_id = token_data.get("user_id")
        existing = db.execute(
            get_sqc_rhmr_active_row_query(),
            {"co_id": body.co_id, "entry_date": body.entry_date, "spell_id": int(body.spell_id)},
        ).fetchone()

        if existing is not None and not body.confirm:
            m = dict(existing._mapping)
            return {
                "data": {
                    "exists": True,
                    "existing": {
                        "spinning_sqc_rhmr_id": m["spinning_sqc_rhmr_id"],
                        "temperature": None if m.get("temperature") is None else _f(m.get("temperature")),
                        "humidity": None if m.get("humidity") is None else _f(m.get("humidity")),
                    },
                }
            }

        temperature = None if body.temperature is None else float(body.temperature)
        humidity = None if body.humidity is None else float(body.humidity)

        if existing is not None:
            db.execute(
                update_sqc_rhmr_query(),
                {
                    "id": dict(existing._mapping)["spinning_sqc_rhmr_id"],
                    "temperature": temperature,
                    "humidity": humidity,
                    "updated_by": user_id,
                },
            )
            mode = "update"
        else:
            db.execute(
                insert_sqc_rhmr_query(),
                {
                    "co_id": body.co_id,
                    "branch_id": body.branch_id,
                    "entry_date": body.entry_date,
                    "spell_id": int(body.spell_id),
                    "temperature": temperature,
                    "humidity": humidity,
                    "updated_by": user_id,
                },
            )
            mode = "insert"

        db.commit()
        return {"data": {"saved": 1, "mode": mode}}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/sqc_rhmr_delete/{rhmr_id}")
def sqc_rhmr_delete(
    rhmr_id: int,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        existing = db.execute(
            get_sqc_rhmr_by_id_query(),
            {"id": rhmr_id},
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail=RHMR_NOT_FOUND_MSG)

        db.execute(
            soft_delete_sqc_rhmr_query(),
            {"id": rhmr_id, "updated_by": token_data.get("user_id")},
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
# jute_sqc_spinning_qr_cv (+ _dtl) — R-08-15 Yarn QR & CV %
# =============================================================================
#
# A group = one saved test for (date, machine, item_id) carrying 30 readings
# (6 spindles x 5 readings). Save is insert-only (duplicates allowed); a group is
# soft-deleted as a unit. observed_count / mr_pct are NOT stored here — they are
# read from R-08-16's already-saved values in jute_sqc_spinning_count (AVG per
# item_id) at read time (D1, D6). Stats (max/min/std_dev/avg_bs/qr_pct/cv_pct) are
# computed server-side at read from the stored readings (D5, D7).


def _fetch_yarn_obs(db: Session, co_id: int, branch_id: Optional[int], entry_date) -> list:
    """Per-yarn AVG(observed_count) + AVG(mr_pct) + COUNT(*) read from R-08-16's
    already-saved jute_sqc_spinning_count rows (the source for the displayed
    observed count + MR% obtained — D1/D6). Only yarns with R-08-16 rows appear."""
    yarn_obs = []
    for r in db.execute(
        get_sqc_count_obs_mr_avg_query(),
        {"co_id": co_id, "entry_date": entry_date, "branch_id": branch_id, "item_id": None},
    ).fetchall():
        m = dict(r._mapping)
        yarn_obs.append(
            {
                "item_id": m["item_id"],
                "item_code": m.get("item_code"),
                "item_name": m.get("item_name"),
                "observed_count": None if m.get("observed_count") is None else _f(m.get("observed_count")),
                "mr_pct": None if m.get("mr_pct") is None else _f(m.get("mr_pct")),
                "obs_count": _i(m.get("obs_count"), 0),
            }
        )
    return yarn_obs


def _qr_cv_obs_map(db: Session, co_id: int, branch_id: Optional[int], entry_date) -> dict:
    """{item_id -> {"observed_count", "mr_pct"}} from R-08-16's saved values (AVG
    per item_id). Built ONCE per request, NOT per group, NOT stored (D6)."""
    obs_map: dict = {}
    for o in _fetch_yarn_obs(db, co_id, branch_id, entry_date):
        obs_map[o["item_id"]] = {
            "observed_count": o["observed_count"],
            "mr_pct": o["mr_pct"],
        }
    return obs_map


def _qr_cv_stats(readings: list, observed_count) -> dict:
    """Compute QR/CV stats server-side (D3, D5, D7). std_dev is the SAMPLE (n-1)
    standard deviation via statistics.stdev; QR%/CV% are guarded against
    divide-by-zero; all rounded to 2 dp."""
    vals = [r["reading_val"] for r in readings if r["reading_val"] is not None]
    n = len(vals)
    avg_bs = (sum(vals) / n) if n else None
    mx, mn = (max(vals), min(vals)) if vals else (None, None)
    std_dev = statistics.stdev(vals) if n >= 2 else (0.0 if n == 1 else None)
    qr_pct = (avg_bs / observed_count) * 100 if (avg_bs is not None and observed_count) else None
    cv_pct = (std_dev / qr_pct) * 100 if (qr_pct not in (None, 0) and std_dev is not None) else None
    return {
        "max": None if mx is None else round(_f(mx), 2),
        "min": None if mn is None else round(_f(mn), 2),
        "std_dev": None if std_dev is None else round(std_dev, 2),
        "avg_bs": None if avg_bs is None else round(avg_bs, 2),
        "qr_pct": None if qr_pct is None else round(qr_pct, 2),
        "cv_pct": None if cv_pct is None else round(cv_pct, 2),
        "n": n,
    }


def _qr_cv_groups(db: Session, co_id: int, branch_id: Optional[int], entry_date) -> list:
    """Active QR/CV groups for (co, date, branch) with readings, observed_count /
    mr_pct (from saved R-08-16, AVG per item_id) and computed stats."""
    headers = db.execute(
        get_sqc_qr_cv_by_date_query(),
        {"co_id": co_id, "entry_date": entry_date, "branch_id": branch_id},
    ).fetchall()
    if not headers:
        return []

    hdr_ids = [int(dict(h._mapping)["spinning_sqc_qr_cv_id"]) for h in headers]

    # Reading rows for all groups in one round-trip (expanding IN :ids bind).
    dtl_by_hdr: dict = {hid: [] for hid in hdr_ids}
    for d in db.execute(get_sqc_qr_cv_dtl_query(), {"ids": hdr_ids}).fetchall():
        dm = dict(d._mapping)
        dtl_by_hdr.setdefault(int(dm["spinning_sqc_qr_cv_id"]), []).append(
            {
                "spindle_no": _i(dm.get("spindle_no")),
                "reading_no": _i(dm.get("reading_no")),
                "reading_val": None if dm.get("reading_val") is None else _f(dm.get("reading_val")),
            }
        )

    # observed_count / mr_pct from R-08-16's saved values — ONE query, mapped by item_id.
    obs_map = _qr_cv_obs_map(db, co_id, branch_id, entry_date)

    groups = []
    for h in headers:
        m = dict(h._mapping)
        hid = int(m["spinning_sqc_qr_cv_id"])
        item_id = m.get("item_id")
        readings = dtl_by_hdr.get(hid, [])
        obs = obs_map.get(item_id, {})
        observed_count = obs.get("observed_count")
        mr_pct = obs.get("mr_pct")
        groups.append(
            {
                "spinning_sqc_qr_cv_id": hid,
                "co_id": m["co_id"],
                "branch_id": m.get("branch_id"),
                "entry_date": str(m["entry_date"]) if m.get("entry_date") is not None else None,
                "mc_id": m.get("mc_id"),
                "mech_code": m.get("mech_code"),
                "machine_name": m.get("machine_name"),
                "item_id": item_id,
                "item_code": m.get("item_code"),
                "item_name": m.get("item_name"),
                "observed_count": observed_count,
                "mr_pct": mr_pct,
                "readings": readings,
                "stats": _qr_cv_stats(readings, observed_count),
            }
        )
    return groups


@router.get("/sqc_qr_cv_setup")
def sqc_qr_cv_setup(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    co_id = _require_co_id(request)
    branch_id = _optional_branch_id(request)
    entry_date = _require_entry_date(request)
    try:
        machines = _fetch_machines(db, co_id, branch_id)
        yarn_items = _fetch_qualities(db, co_id, branch_id)
        yarn_obs = _fetch_yarn_obs(db, co_id, branch_id, entry_date)
        groups = _qr_cv_groups(db, co_id, branch_id, entry_date)
        return {
            "data": {
                "machines": machines,
                "yarn_items": yarn_items,
                "yarn_obs": yarn_obs,
                "groups": groups,
            }
        }
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid entry_date format")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sqc_qr_cv_save")
def sqc_qr_cv_save(
    body: SqcQrCvSave,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Insert-only, multi-observation save (mirrors sqc_count_save). Each entry
    inserts one header (read lastrowid) then its 30 detail rows. observed_count /
    mr_pct are NOT stored (read from R-08-16's saved values at read — D6)."""
    try:
        user_id = token_data.get("user_id")
        saved_ids = []
        for e in body.entries:
            result = db.execute(
                insert_sqc_qr_cv_header_query(),
                {
                    "co_id": body.co_id,
                    "branch_id": body.branch_id,
                    "entry_date": body.entry_date,
                    "mc_id": _i(e.mc_id),
                    "item_id": int(e.item_id),
                    "updated_by": user_id,
                },
            )
            hdr_id = result.lastrowid
            for sp in e.spindles:
                for idx in range(5):
                    reading_val = sp.readings[idx] if idx < len(sp.readings) else None
                    db.execute(
                        insert_sqc_qr_cv_dtl_query(),
                        {
                            "hdr_id": hdr_id,
                            "spindle_no": int(sp.spindle_no),
                            "reading_no": idx + 1,
                            "reading_val": None if reading_val is None else float(reading_val),
                        },
                    )
            saved_ids.append(hdr_id)
        db.commit()
        return {"data": {"saved": len(saved_ids), "ids": saved_ids}}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sqc_qr_cv_by_date")
def sqc_qr_cv_by_date(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    co_id = _require_co_id(request)
    branch_id = _optional_branch_id(request)
    entry_date = _require_entry_date(request)
    try:
        groups = _qr_cv_groups(db, co_id, branch_id, entry_date)
        return {"data": {"groups": groups}}
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid entry_date format")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/sqc_qr_cv_delete/{qr_cv_id}")
def sqc_qr_cv_delete(
    qr_cv_id: int,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Soft-delete the group header (active=0); detail rows stay (hidden via the
    active-header join). Mirrors sqc_count_delete."""
    try:
        existing = db.execute(
            get_sqc_qr_cv_active_row_query(),
            {"id": qr_cv_id},
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail=QR_CV_NOT_FOUND_MSG)

        db.execute(
            soft_delete_sqc_qr_cv_query(),
            {"id": qr_cv_id, "updated_by": token_data.get("user_id")},
        )
        db.commit()
        return {"data": {"message": "Deleted"}}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
