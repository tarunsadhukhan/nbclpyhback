"""Finishing Production Entry endpoints (prefix /api/finishingProd).

Per-process daily production entry, modelled on beaming_entry.py: get_tenant_db +
get_current_user_with_refresh, {"data": ...} responses, soft delete via active=0, no
approval workflow, trigger-based audit (no created_*).

Figure-only model: the user enters ONLY tran_date, spell, machine, quality and the
production figure (prod_qty + its per-process default prod_uom). The server stores that
snapshot and nothing else — no input/wastage, no spec-sheet speed/eff resolution, no
F1–F3 derived columns, no captured EAV params (SQC dropped for now). Those typed columns
(input_qty, input_uom, wastage_kg, std/target/act speed & eff, working_hours, p100prod,
std/target prod, act_eff, prod_wt_kg) are left NULL.

Grain / upsert uniqueness: (co_id, tran_date, spell_id, process, machine_id,
finishing_quality_id, active=1) — an existing active row is updated, otherwise inserted.
Machine LINKING is unused (machine types exist for the future only); branch is derived
from the machine on insert.
"""

from datetime import date
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.authorization.utils import get_current_user_with_refresh
from src.config.db import get_tenant_db
from src.juteProduction.constants import (
    FINISHING_MACHINE_TYPE_NAMES,
    FINISHING_PROCESSES,
)
from src.juteProduction.finishing_query import (
    get_finishing_daily_active_row_by_emp_query,
    get_finishing_daily_active_row_query,
    get_finishing_employee_query,
    get_finishing_entries_by_date_query,
    get_finishing_machines_query,
    get_finishing_qualities_query,
    get_finishing_quality_for_entry_query,
    get_finishing_spells_query,
    insert_finishing_daily_query,
    soft_delete_finishing_daily_query,
    update_finishing_daily_query,
)
from src.juteProduction.finishing_target_map import quality_type_for_process


router = APIRouter()

PROCESSES = list(FINISHING_PROCESSES)
# Labour-based processes have NO machine — production is keyed by the worker (eb_id).
LABOUR_PROCESSES = ("sacksewing",)
QUALITY_NOT_FOUND_MSG = "Finishing quality not found"
QUALITY_TYPE_MISMATCH_MSG = "Selected quality does not match the process (cloth vs bag)"
ENTRY_NOT_FOUND_MSG = "Finishing entry not found"
EMP_NOT_FOUND_MSG = "Emp code not found"
EMP_REQUIRED_MSG = "Employee (emp code) is required for this process"
BRANCH_REQUIRED_MSG = "branch_id is required for this process"


# =============================================================================
# Pydantic models
# =============================================================================


class FinishingEntryCreate(BaseModel):
    co_id: int
    branch_id: Optional[int] = None  # derived from machine on insert; required for labour
    tran_date: date
    spell_id: int
    process: str
    machine_id: Optional[int] = None  # None for labour processes (sacksewing)
    eb_id: Optional[int] = None  # worker, for labour processes (sacksewing)
    finishing_quality_id: int
    prod_qty: float = Field(ge=0)
    prod_uom: str


class FinishingEntryUpdate(BaseModel):
    spell_id: Optional[int] = None
    machine_id: Optional[int] = None
    eb_id: Optional[int] = None
    finishing_quality_id: Optional[int] = None
    prod_qty: Optional[float] = Field(default=None, ge=0)
    prod_uom: Optional[str] = None


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


def _require_process(request: Request) -> str:
    raw = request.query_params.get("process")
    if not raw:
        raise HTTPException(status_code=400, detail="process is required")
    if raw not in PROCESSES:
        raise HTTPException(status_code=400, detail=f"Invalid process '{raw}'")
    return raw


def _optional_process(request: Request) -> Optional[str]:
    raw = request.query_params.get("process")
    if not raw:
        return None
    if raw not in PROCESSES:
        raise HTTPException(status_code=400, detail=f"Invalid process '{raw}'")
    return raw


def _derive_branch_id(db: Session, machine_id: int) -> Optional[int]:
    """Branch from the machine's department (machine_mst.dept_id -> dept_mst.branch_id)."""
    derived = db.execute(
        text(
            """
            SELECT d.branch_id
            FROM machine_mst m
            INNER JOIN dept_mst d ON d.dept_id = m.dept_id
            WHERE m.machine_id = :machine_id
            """
        ),
        {"machine_id": int(machine_id)},
    ).fetchone()
    return derived.branch_id if derived else None


def _validate_quality(db: Session, co_id: int, process: str, finishing_quality_id: int):
    """Fetch + validate the quality against the process (cloth vs bag). Returns the row.

    Raises 404 if the quality is missing/foreign, 400 if its quality_type does not match
    the process (cloth processes need a cloth quality; bag processes need a bag quality).
    balepress accepts both (quality_type_for_process -> None, no filter).
    """
    quality = db.execute(
        get_finishing_quality_for_entry_query(),
        {"finishing_quality_id": int(finishing_quality_id), "co_id": int(co_id)},
    ).fetchone()
    if not quality:
        raise HTTPException(status_code=404, detail=QUALITY_NOT_FOUND_MSG)
    expected_type = quality_type_for_process(process)
    if expected_type is not None and int(quality.quality_type) != int(expected_type):
        raise HTTPException(status_code=400, detail=QUALITY_TYPE_MISMATCH_MSG)
    return quality


def _resolve_employee(
    db: Session,
    branch_id: int,
    emp_code: Optional[str] = None,
    eb_id: Optional[int] = None,
):
    """Resolve a worker by emp_code OR eb_id, scoped to branch_id. Returns the row or None.

    The branch is enforced server-side (a code from another branch resolves to nothing), so
    the entered code must belong to the same branch the entry is for.
    """
    return db.execute(
        get_finishing_employee_query(),
        {
            "branch_id": int(branch_id),
            "emp_code": emp_code.strip() if emp_code else None,
            "eb_id": int(eb_id) if eb_id is not None else None,
        },
    ).fetchone()


def _snapshot(
    co_id: int,
    branch_id: Optional[int],
    tran_date,
    spell_id: int,
    process: str,
    machine_id: Optional[int],
    finishing_quality_id: int,
    prod_qty: float,
    prod_uom: str,
    eb_id: Optional[int],
    user_id,
) -> Dict[str, Any]:
    """Flat bind dict for insert_finishing_daily_query / update_finishing_daily_query.

    Figure-only: prod_qty + prod_uom are stored; every other typed column is NULL.
    machine_id is None for labour processes (sacksewing), where eb_id keys the row instead.
    """
    return {
        "co_id": int(co_id),
        "branch_id": _i(branch_id),
        "tran_date": tran_date,
        "spell_id": int(spell_id),
        "process": process,
        "machine_id": _i(machine_id),
        "finishing_quality_id": int(finishing_quality_id),
        "eb_id": _i(eb_id),
        "input_qty": None,
        "input_uom": None,
        "prod_qty": float(prod_qty),
        "prod_uom": prod_uom,
        "prod_wt_kg": None,
        "wastage_kg": None,
        "std_speed": None,
        "target_speed": None,
        "act_speed": None,
        "std_eff": None,
        "target_eff": None,
        "working_hours": None,
        "p100prod": None,
        "std_prod": None,
        "target_prod": None,
        "act_eff": None,
        "updated_by": user_id,
    }


def _serialize_entry_row(row) -> Dict[str, Any]:
    """dict(_mapping) with Decimal -> float and date -> str for JSON safety."""
    m = dict(row._mapping)
    float_cols = (
        "input_qty", "prod_qty", "prod_wt_kg", "wastage_kg", "std_speed", "target_speed",
        "act_speed", "std_eff", "target_eff", "working_hours", "p100prod", "std_prod",
        "target_prod", "act_eff",
    )
    for k in float_cols:
        if m.get(k) is not None:
            m[k] = float(m[k])
    if m.get("tran_date") is not None:
        m["tran_date"] = str(m["tran_date"])
    return m


# =============================================================================
# Endpoints — setup
# =============================================================================


@router.get("/entry_setup")
def entry_setup(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Lookups for the entry form (for a process): machines, qualities, spells, and the
    day's existing rows (if tran_date given)."""
    co_id = _require_co_id(request)
    branch_id = _optional_branch_id(request)
    process = _require_process(request)
    try:
        machine_type = FINISHING_MACHINE_TYPE_NAMES.get(process)
        machines = [
            dict(r._mapping)
            for r in db.execute(
                get_finishing_machines_query(),
                {"machine_type": machine_type, "branch_id": branch_id},
            ).fetchall()
        ]
        qualities = [
            dict(r._mapping)
            for r in db.execute(
                get_finishing_qualities_query(),
                {
                    "co_id": co_id,
                    "quality_type": quality_type_for_process(process),
                    "branch_id": branch_id,
                },
            ).fetchall()
        ]

        spells = []
        seen = set()
        for r in db.execute(
            get_finishing_spells_query(), {"branch_id": branch_id}
        ).fetchall():
            m = dict(r._mapping)
            code = m["spell_code"]
            if code in seen:
                continue
            seen.add(code)
            spells.append(
                {
                    "spell_id": int(m["spell_id"]),
                    "spell_code": code,
                    "spell_name": m.get("spell_name"),
                    "working_hours": _f(m.get("working_hours")),
                }
            )

        entries: List[Dict[str, Any]] = []
        d = request.query_params.get("tran_date")
        if d:
            d_val = date.fromisoformat(d)
            entries = _entries_for_date(db, co_id, process, d_val, None, None, branch_id)

        return {
            "data": {
                "process": process,
                "machines": machines,
                "qualities": qualities,
                "spells": spells,
                "entries": entries,
            }
        }
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid query parameter")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _entries_for_date(
    db: Session,
    co_id: int,
    process: Optional[str],
    tran_date,
    spell_id: Optional[int],
    machine_id: Optional[int],
    branch_id: Optional[int],
) -> List[Dict[str, Any]]:
    """Day-grid rows for (co, date[, process, spell, machine])."""
    rows = db.execute(
        get_finishing_entries_by_date_query(),
        {
            "co_id": co_id,
            "tran_date": tran_date,
            "process": process,
            "spell_id": spell_id,
            "machine_id": machine_id,
            "branch_id": branch_id,
        },
    ).fetchall()
    return [_serialize_entry_row(r) for r in rows]


@router.get("/entry_by_date")
def entry_by_date(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Day-grid finishing-daily entries for a tran_date (optional process, spell_id, machine_id)."""
    co_id = _require_co_id(request)
    branch_id = _optional_branch_id(request)
    process = _optional_process(request)
    d = request.query_params.get("tran_date")
    if not d:
        raise HTTPException(status_code=400, detail="tran_date is required")
    spell_raw = request.query_params.get("spell_id")
    machine_raw = request.query_params.get("machine_id")
    try:
        d_val = date.fromisoformat(d)
        spell_id = int(spell_raw) if spell_raw else None
        machine_id = int(machine_raw) if machine_raw else None
        entries = _entries_for_date(db, co_id, process, d_val, spell_id, machine_id, branch_id)
        return {"data": entries}
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tran_date, spell_id or machine_id")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/employee_lookup")
def employee_lookup(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Resolve an employee by emp_code for the labour entry (sacksewing).

    Branch-scoped (the code must belong to the selected branch). Returns the eb_id, emp_code
    and a display name (emp_code + first/middle/last). 404 'Emp code not found' if no active
    employee with that code exists in the branch.
    """
    _require_co_id(request)
    branch_id = _optional_branch_id(request)
    if branch_id is None:
        raise HTTPException(status_code=400, detail=BRANCH_REQUIRED_MSG)
    emp_code = request.query_params.get("emp_code")
    if not emp_code or not emp_code.strip():
        raise HTTPException(status_code=400, detail="emp_code is required")
    try:
        row = _resolve_employee(db, branch_id, emp_code=emp_code)
        if not row:
            raise HTTPException(status_code=404, detail=EMP_NOT_FOUND_MSG)
        return {
            "data": {
                "eb_id": int(row.eb_id),
                "emp_code": row.emp_code,
                "employee_name": row.employee_name,
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Endpoints — save / delete (figure-only snapshot)
# =============================================================================


@router.post("/entry_save")
def entry_save(
    body: FinishingEntryCreate,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Insert (or upsert) one finishing daily row — production figure only.

    Validates the quality against the process (balepress accepts both), then upserts the
    snapshot. Machine processes are keyed by (co_id, tran_date, spell_id, process,
    machine_id, finishing_quality_id, active=1). LABOUR processes (sacksewing) have no
    machine: branch_id + eb_id are required, the worker must belong to that branch, and the
    row is keyed by (co_id, tran_date, spell_id, process, machine_id IS NULL, eb_id,
    finishing_quality_id). Only prod_qty + prod_uom are stored; all other typed columns NULL.
    """
    try:
        if body.process not in PROCESSES:
            raise HTTPException(status_code=400, detail=f"Invalid process '{body.process}'")

        _validate_quality(db, body.co_id, body.process, body.finishing_quality_id)

        is_labour = body.process in LABOUR_PROCESSES
        user_id = token_data.get("user_id")

        if is_labour:
            # Labour (no-machine) path: keyed by the worker. branch_id + eb_id are required;
            # the employee must belong to that branch. machine_id stays NULL.
            if body.branch_id is None:
                raise HTTPException(status_code=400, detail=BRANCH_REQUIRED_MSG)
            if body.eb_id is None:
                raise HTTPException(status_code=400, detail=EMP_REQUIRED_MSG)
            if not _resolve_employee(db, body.branch_id, eb_id=body.eb_id):
                raise HTTPException(status_code=404, detail=EMP_NOT_FOUND_MSG)
            branch_id = int(body.branch_id)
            machine_id = None
            eb_id = int(body.eb_id)
            existing = db.execute(
                get_finishing_daily_active_row_by_emp_query(),
                {
                    "co_id": int(body.co_id),
                    "tran_date": body.tran_date,
                    "spell_id": int(body.spell_id),
                    "process": body.process,
                    "eb_id": eb_id,
                    "finishing_quality_id": int(body.finishing_quality_id),
                },
            ).fetchone()
        else:
            if body.machine_id is None:
                raise HTTPException(status_code=400, detail="machine_id is required")
            branch_id = body.branch_id
            if branch_id is None:
                branch_id = _derive_branch_id(db, body.machine_id)
            machine_id = int(body.machine_id)
            eb_id = None
            existing = db.execute(
                get_finishing_daily_active_row_query(),
                {
                    "co_id": int(body.co_id),
                    "tran_date": body.tran_date,
                    "spell_id": int(body.spell_id),
                    "process": body.process,
                    "machine_id": machine_id,
                    "finishing_quality_id": int(body.finishing_quality_id),
                },
            ).fetchone()

        params = _snapshot(
            body.co_id,
            branch_id,
            body.tran_date,
            body.spell_id,
            body.process,
            machine_id,
            body.finishing_quality_id,
            body.prod_qty,
            body.prod_uom,
            eb_id,
            user_id,
        )

        if existing:
            params["id"] = existing.finishing_daily_id
            db.execute(update_finishing_daily_query(), params)
            finishing_daily_id = int(existing.finishing_daily_id)
        else:
            result = db.execute(insert_finishing_daily_query(), params)
            finishing_daily_id = int(result.lastrowid)

        db.commit()
        return {"data": {"finishing_daily_id": finishing_daily_id}}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/entry_delete/{entry_id}")
def entry_delete(
    entry_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Soft-delete (active=0) one finishing-daily entry (co_id-scoped)."""
    co_id = _require_co_id(request)
    try:
        existing = db.execute(
            text(
                """
                SELECT finishing_daily_id
                FROM jute_prod_finishing_daily
                WHERE finishing_daily_id = :id AND co_id = :co_id AND active = 1
                """
            ),
            {"id": entry_id, "co_id": co_id},
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail=ENTRY_NOT_FOUND_MSG)

        user_id = token_data.get("user_id")
        db.execute(
            soft_delete_finishing_daily_query(), {"id": entry_id, "updated_by": user_id}
        )
        db.commit()
        return {"data": {"message": "Deleted"}}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
