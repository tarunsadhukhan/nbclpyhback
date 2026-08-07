"""Stoppage Hours entry endpoints (jute production module).

A daily machine-downtime event log under the prefix ``/api/stoppageProd``. Each
row records a reason-tagged stoppage interval for a machine on a (date, spell).
Department is a cascading UI filter only and is NOT stored — it (and branch) are
derived from the machine via machine_mst.dept_id -> dept_mst.branch_id. reason_code
is a fixed app enum (STOPPAGE_REASONS) — there is no reason master table.

Persona: Portal (get_tenant_db + get_current_user_with_refresh, {"data": ...}
responses, soft delete via active = 0, NO approval workflow). Conventions mirror
winding_entry.py: _require_co_id / _optional_branch_id / _f / _serialize_dates
helpers, and the try/except (GET: HTTPException raise / ValueError 400 / Exception
500; POST/PUT/DELETE: db.rollback() then raise / 500) pattern.

Five endpoints (the net_running_hours read model in SPEC §8.2 is DEFERRED and not
built here): entry_create_setup, entry_create, entries_by_date, entry_edit,
entry_delete. Validation: reason_code in STOPPAGE_REASONS, and
0 < stoppage_hours <= the selected spell's working_hours.
"""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.authorization.utils import get_current_user_with_refresh
from src.config.db import get_tenant_db
from src.juteProduction.constants import STOPPAGE_REASONS, STOPPAGE_REASON_LABELS
from src.juteProduction.stoppage_query import (
    derive_branch_for_machine_query,
    get_spell_working_hours_query,
    get_stoppage_active_by_id_query,
    get_stoppage_by_date_query,
    get_stoppage_machines_query,
    get_stoppage_spells_query,
    insert_stoppage_row_query,
    soft_delete_stoppage_row_query,
    update_stoppage_row_query,
)


router = APIRouter()

NOT_FOUND_MSG = "Stoppage entry not found"
BAD_REASON_MSG = "reason_code must be one of: " + ", ".join(STOPPAGE_REASONS)
UNKNOWN_SPELL_MSG = "Unknown spell_id"
HOURS_GATE_MSG = "stoppage_hours must be greater than 0 and at most the spell working hours"


# =============================================================================
# Pydantic models
# =============================================================================


class StoppageEntryCreate(BaseModel):
    co_id: int
    branch_id: Optional[int] = None  # derived on insert if None (SPEC §10)
    tran_date: date
    spell_id: int
    machine_id: int
    stoppage_hours: float  # > 0 and <= spell_mst.working_hours
    reason_code: str  # must be in STOPPAGE_REASONS (SPEC §9)
    remarks: Optional[str] = None


class StoppageEntryUpdate(BaseModel):
    """Editable fields only (SPEC §8.2): machine_id / tran_date are immutable."""

    stoppage_hours: Optional[float] = None
    reason_code: Optional[str] = None
    remarks: Optional[str] = None
    spell_id: Optional[int] = None


# =============================================================================
# Helpers (mirror winding_entry.py)
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


def _serialize_dates(row: dict, keys=("tran_date",)) -> dict:
    for k in keys:
        if row.get(k) is not None:
            row[k] = str(row[k])
    return row


def _validate_reason(reason_code: str) -> str:
    code = (reason_code or "").strip()
    if code not in STOPPAGE_REASONS:
        raise HTTPException(status_code=400, detail=BAD_REASON_MSG)
    return code


def _spell_working_hours(db: Session, spell_id: int) -> float:
    """Resolve a spell_id's planned working_hours (400 if the spell is unknown)."""
    row = db.execute(
        get_spell_working_hours_query(), {"spell_id": int(spell_id)}
    ).fetchone()
    if not row or row.working_hours is None:
        raise HTTPException(status_code=400, detail=UNKNOWN_SPELL_MSG)
    return _f(row.working_hours)


def _validate_hours(db: Session, spell_id: int, stoppage_hours: float) -> float:
    """Gate 0 < stoppage_hours <= spell working_hours (400 otherwise)."""
    hours = float(stoppage_hours)
    working_hours = _spell_working_hours(db, spell_id)
    if hours <= 0 or hours > working_hours:
        raise HTTPException(status_code=400, detail=HOURS_GATE_MSG)
    return hours


def _derive_branch_id(db: Session, machine_id: int) -> Optional[int]:
    row = db.execute(
        derive_branch_for_machine_query(), {"machine_id": int(machine_id)}
    ).fetchone()
    return row.branch_id if row else None


# =============================================================================
# Endpoints — setup + reads
# =============================================================================


@router.get("/entry_create_setup")
def entry_create_setup(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Dropdown payload: all active machines (+dept/branch for the cascade),
    spells (with working_hours), and the fixed reason enum."""
    co_id = _require_co_id(request)
    branch_id = _optional_branch_id(request)
    try:
        machines = []
        for r in db.execute(
            get_stoppage_machines_query(), {"branch_id": branch_id}
        ).fetchall():
            m = dict(r._mapping)
            machines.append(
                {
                    "machine_id": m["machine_id"],
                    "machine_name": m["machine_name"],
                    "mech_code": m["mech_code"],
                    "machine_type_id": m["machine_type_id"],
                    "machine_type_name": m["machine_type_name"],
                    "dept_id": m["dept_id"],
                    "dept_name": m["dept_name"],
                    "branch_id": m["branch_id"],
                }
            )

        spells = []
        seen = set()
        for r in db.execute(
            get_stoppage_spells_query(), {"branch_id": branch_id}
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
                    "spell_name": m["spell_name"],
                    "working_hours": _f(m.get("working_hours")),
                }
            )

        reasons = [
            {"code": code, "label": STOPPAGE_REASON_LABELS.get(code, code)}
            for code in STOPPAGE_REASONS
        ]

        return {"data": {"machines": machines, "spells": spells, "reasons": reasons}}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/entries_by_date")
def entries_by_date(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Day grid: one row per active stoppage event for the date/branch, with
    dept_name / machine_name / spell_code resolved for display."""
    co_id = _require_co_id(request)
    branch_id = _optional_branch_id(request)
    d = request.query_params.get("tran_date")
    if not d:
        raise HTTPException(status_code=400, detail="tran_date is required")
    try:
        d_val = date.fromisoformat(d)
        rows = db.execute(
            get_stoppage_by_date_query(),
            {"co_id": co_id, "tran_date": d_val, "branch_id": branch_id},
        ).fetchall()
        data = []
        for r in rows:
            row = dict(r._mapping)
            if row.get("stoppage_hours") is not None:
                row["stoppage_hours"] = float(row["stoppage_hours"])
            _serialize_dates(row)
            data.append(row)
        return {"data": data}
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tran_date format")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Endpoints — CRUD
# =============================================================================


@router.post("/entry_create")
def entry_create(
    body: StoppageEntryCreate,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Insert one stoppage event. Validates reason_code and the single-event hours
    bound; derives branch_id from machine->dept->branch when omitted (server
    always prefers the derivation)."""
    try:
        reason_code = _validate_reason(body.reason_code)
        stoppage_hours = _validate_hours(db, body.spell_id, body.stoppage_hours)

        branch_id = body.branch_id
        if branch_id is None:
            branch_id = _derive_branch_id(db, int(body.machine_id))

        user_id = token_data.get("user_id")
        result = db.execute(
            insert_stoppage_row_query(),
            {
                "co_id": int(body.co_id),
                "branch_id": branch_id,
                "tran_date": body.tran_date,
                "spell_id": int(body.spell_id),
                "machine_id": int(body.machine_id),
                "stoppage_hours": stoppage_hours,
                "reason_code": reason_code,
                "remarks": body.remarks,
                "updated_by": user_id,
            },
        )
        db.commit()
        return {"data": {"stoppage_hours_id": result.lastrowid}}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/entry_edit/{stoppage_hours_id}")
def entry_edit(
    stoppage_hours_id: int,
    body: StoppageEntryUpdate,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Edit only stoppage_hours / reason_code / remarks / spell_id (machine_id and
    tran_date are immutable — delete + re-add to keep branch derivation clean).
    Re-validates reason_code and the hours bound against the resolved spell."""
    try:
        existing = db.execute(
            get_stoppage_active_by_id_query(), {"id": stoppage_hours_id}
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail=NOT_FOUND_MSG)

        new_spell_id = (
            int(body.spell_id) if body.spell_id is not None else int(existing.spell_id)
        )
        new_reason = (
            _validate_reason(body.reason_code)
            if body.reason_code is not None
            else existing.reason_code
        )
        new_hours_raw = (
            body.stoppage_hours
            if body.stoppage_hours is not None
            else _f(existing.stoppage_hours)
        )
        new_hours = _validate_hours(db, new_spell_id, new_hours_raw)
        new_remarks = (
            body.remarks if body.remarks is not None else existing.remarks
        )

        user_id = token_data.get("user_id")
        db.execute(
            update_stoppage_row_query(),
            {
                "id": stoppage_hours_id,
                "stoppage_hours": new_hours,
                "reason_code": new_reason,
                "remarks": new_remarks,
                "spell_id": new_spell_id,
                "updated_by": user_id,
            },
        )
        db.commit()
        return {"data": {"stoppage_hours_id": stoppage_hours_id}}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/entry_delete/{stoppage_hours_id}")
def entry_delete(
    stoppage_hours_id: int,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Soft delete (active = 0)."""
    try:
        existing = db.execute(
            get_stoppage_active_by_id_query(), {"id": stoppage_hours_id}
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail=NOT_FOUND_MSG)

        user_id = token_data.get("user_id")
        db.execute(
            soft_delete_stoppage_row_query(),
            {"id": stoppage_hours_id, "updated_by": user_id},
        )
        db.commit()
        return {"data": {"stoppage_hours_id": stoppage_hours_id}}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
