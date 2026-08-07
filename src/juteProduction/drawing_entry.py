"""Drawing Production Entry endpoints (daily spellwise meter entry)."""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.authorization.utils import get_current_user_with_refresh
from src.config.db import get_tenant_db
from src.juteProduction.constants import DRAWING_MACHINE_TYPE_NAME
from src.juteProduction.drawing_query import (
    get_drawing_machines_query,
    get_duplicate_entry_query,
    get_entries_by_date_query,
    get_prev_close_meter_query,
    get_spells_query,
)
from src.juteProduction.services.drawing_rules import compute_diff_meter, compute_eff


router = APIRouter()

DUPLICATE_MSG = "Machine already entered for this date and spell"
NO_ATTR_MSG = "No drawing attributes configured for this machine"
NEGATIVE_DIFF_MSG = "Computed diff meter is negative — check open and close meter values"


# =============================================================================
# Pydantic models
# =============================================================================


class DrawingEntryCreate(BaseModel):
    co_id: int
    branch_id: Optional[int] = None
    tran_date: date
    spell: str
    machine_id: int
    open_meter: float = Field(ge=0)
    close_meter: float = Field(ge=0)
    wrk_hours: float = Field(gt=0)
    remarks: Optional[str] = None


class DrawingEntryUpdate(BaseModel):
    tran_date: Optional[date] = None
    spell: Optional[str] = None
    machine_id: Optional[int] = None
    open_meter: Optional[float] = Field(default=None, ge=0)
    close_meter: Optional[float] = Field(default=None, ge=0)
    wrk_hours: Optional[float] = Field(default=None, gt=0)
    remarks: Optional[str] = None


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


def _dedupe_spells(rows) -> list:
    """Keep the first row per spell_code (sls has a duplicate A1 on another branch)."""
    seen = set()
    out = []
    for r in rows:
        m = dict(r._mapping)
        code = m["spell_code"]
        if code in seen:
            continue
        seen.add(code)
        if m.get("working_hours") is not None:
            m["working_hours"] = float(m["working_hours"])
        if m.get("starting_time") is not None:
            m["starting_time"] = str(m["starting_time"])
        out.append(m)
    return out


def _fetch_machine_attr(db: Session, co_id: int, machine_id: int):
    """Active drawing attr row for the machine; None if not configured."""
    return db.execute(
        text(
            """
            SELECT drawing_machine_attr_id, const_meter, meter_wrap_limit
            FROM jute_prod_drawing_machine_attr
            WHERE co_id = :co_id AND machine_id = :machine_id AND active = 1
            """
        ),
        {"co_id": co_id, "machine_id": machine_id},
    ).fetchone()


def _is_duplicate(
    db: Session,
    co_id: int,
    tran_date_val: date,
    spell: str,
    machine_id: int,
    exclude_id: Optional[int] = None,
) -> bool:
    params = {
        "co_id": co_id,
        "tran_date": tran_date_val,
        "spell": spell,
        "machine_id": machine_id,
    }
    if exclude_id is not None:
        params["exclude_id"] = exclude_id
    cnt = db.execute(get_duplicate_entry_query(exclude=exclude_id is not None), params).scalar()
    return bool(cnt and int(cnt) > 0)


def _valid_spell_codes(db: Session, branch_id: Optional[int]) -> set:
    rows = db.execute(get_spells_query(), {"branch_id": branch_id}).fetchall()
    return {dict(r._mapping)["spell_code"] for r in rows}


def _derive_branch_id(db: Session, machine_id: int) -> Optional[int]:
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


# =============================================================================
# Endpoints — setup + state preview
# =============================================================================


@router.get("/entry_create_setup")
def entry_create_setup(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    co_id = _require_co_id(request)
    branch_id = _optional_branch_id(request)
    try:
        machines = []
        for r in db.execute(
            get_drawing_machines_query(),
            {"co_id": co_id, "drawing_type": DRAWING_MACHINE_TYPE_NAME, "branch_id": branch_id},
        ).fetchall():
            m = dict(r._mapping)
            if m.get("const_meter") is not None:
                m["const_meter"] = float(m["const_meter"])
            if m.get("meter_wrap_limit") is not None:
                m["meter_wrap_limit"] = int(m["meter_wrap_limit"])
            machines.append(m)
        spells = _dedupe_spells(
            db.execute(get_spells_query(), {"branch_id": branch_id}).fetchall()
        )
        return {"data": {"machines": machines, "spells": spells}}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/machine_prev_state")
def machine_prev_state(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    co_id = _require_co_id(request)
    try:
        machine_id_s = request.query_params.get("machine_id")
        tran_date_s = request.query_params.get("tran_date")
        spell = request.query_params.get("spell")
        if not machine_id_s or not tran_date_s or not spell:
            raise HTTPException(
                status_code=400, detail="machine_id, tran_date and spell are required"
            )
        machine_id = int(machine_id_s)
        tran_date_val = date.fromisoformat(tran_date_s)
        exclude_raw = request.query_params.get("exclude_entry_id")
        exclude_id = int(exclude_raw) if exclude_raw else None

        already = _is_duplicate(db, co_id, tran_date_val, spell, machine_id, exclude_id)

        attr = _fetch_machine_attr(db, co_id, machine_id)
        const_meter = float(attr.const_meter) if attr else 0.0
        wrap_limit = int(attr.meter_wrap_limit) if attr else 10000

        prev = db.execute(
            get_prev_close_meter_query(),
            {"co_id": co_id, "machine_id": machine_id, "spell": spell},
        ).fetchone()
        open_meter = float(prev.close_meter) if prev else 0.0

        return {
            "data": {
                "already_entered": already,
                "const_meter": const_meter,
                "open_meter": open_meter,
                "meter_wrap_limit": wrap_limit,
                "attr_configured": attr is not None,
            }
        }
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid machine_id, tran_date or exclude_entry_id")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Endpoints — CRUD
# =============================================================================


@router.post("/entry_create")
def entry_create(
    body: DrawingEntryCreate,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        if body.spell not in _valid_spell_codes(db, None):
            raise HTTPException(status_code=400, detail=f"Unknown spell '{body.spell}'")

        if _is_duplicate(db, body.co_id, body.tran_date, body.spell, body.machine_id):
            raise HTTPException(status_code=400, detail=DUPLICATE_MSG)

        attr = _fetch_machine_attr(db, body.co_id, body.machine_id)
        if not attr:
            raise HTTPException(status_code=400, detail=NO_ATTR_MSG)
        const_meter = float(attr.const_meter)
        wrap_limit = int(attr.meter_wrap_limit)

        diff_meter = compute_diff_meter(body.open_meter, body.close_meter, wrap_limit)
        if diff_meter < 0:
            raise HTTPException(status_code=400, detail=NEGATIVE_DIFF_MSG)
        actual_eff = compute_eff(diff_meter, const_meter, body.wrk_hours)

        branch_id = body.branch_id
        if branch_id is None:
            branch_id = _derive_branch_id(db, body.machine_id)

        user_id = token_data.get("user_id")
        result = db.execute(
            text(
                """
                INSERT INTO jute_prod_drawing_entry
                    (co_id, branch_id, tran_date, spell, machine_id,
                     open_meter, close_meter, diff_meter, const_meter,
                     wrk_hours, actual_eff, remarks, active, updated_by)
                VALUES
                    (:co_id, :branch_id, :tran_date, :spell, :machine_id,
                     :open_meter, :close_meter, :diff_meter, :const_meter,
                     :wrk_hours, :actual_eff, :remarks, 1, :updated_by)
                """
            ),
            {
                "co_id": body.co_id,
                "branch_id": branch_id,
                "tran_date": body.tran_date,
                "spell": body.spell,
                "machine_id": int(body.machine_id),
                "open_meter": float(body.open_meter),
                "close_meter": float(body.close_meter),
                "diff_meter": diff_meter,
                "const_meter": const_meter,
                "wrk_hours": float(body.wrk_hours),
                "actual_eff": actual_eff,
                "remarks": body.remarks,
                "updated_by": user_id,
            },
        )
        db.commit()
        return {"data": {"drawing_entry_id": result.lastrowid}}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/entries_by_date")
def entries_by_date(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    co_id = _require_co_id(request)
    branch_id = _optional_branch_id(request)
    d = request.query_params.get("tran_date")
    if not d:
        raise HTTPException(status_code=400, detail="tran_date is required")
    spell = request.query_params.get("spell") or None
    try:
        d_val = date.fromisoformat(d)
        rows = db.execute(
            get_entries_by_date_query(),
            {"co_id": co_id, "tran_date": d_val, "spell": spell, "branch_id": branch_id},
        ).fetchall()
        data = []
        for r in rows:
            row = dict(r._mapping)
            for k in ("const_meter", "open_meter", "close_meter", "diff_meter", "actual_eff", "wrk_hours"):
                if row.get(k) is not None:
                    row[k] = float(row[k])
            if row.get("tran_date") is not None:
                row["tran_date"] = str(row["tran_date"])
            data.append(row)
        return {"data": data}
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tran_date format")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/entry_edit/{entry_id}")
def entry_edit(
    entry_id: int,
    body: DrawingEntryUpdate,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    co_id = _require_co_id(request)
    try:
        existing = db.execute(
            text(
                """
                SELECT drawing_entry_id, co_id, tran_date, spell, machine_id,
                       open_meter, close_meter, const_meter, wrk_hours, remarks
                FROM jute_prod_drawing_entry
                WHERE drawing_entry_id = :id AND co_id = :co_id AND active = 1
                """
            ),
            {"id": entry_id, "co_id": co_id},
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Drawing entry not found")

        new_date = body.tran_date or existing.tran_date
        new_spell = body.spell or existing.spell
        new_machine = int(body.machine_id) if body.machine_id is not None else int(existing.machine_id)
        new_open = float(body.open_meter) if body.open_meter is not None else float(existing.open_meter)
        new_close = float(body.close_meter) if body.close_meter is not None else float(existing.close_meter)
        new_hours = float(body.wrk_hours) if body.wrk_hours is not None else float(existing.wrk_hours)
        new_remarks = body.remarks if body.remarks is not None else existing.remarks

        if body.spell is not None and body.spell not in _valid_spell_codes(db, None):
            raise HTTPException(status_code=400, detail=f"Unknown spell '{body.spell}'")

        key_changed = (
            body.tran_date is not None or body.spell is not None or body.machine_id is not None
        )
        if key_changed and _is_duplicate(
            db, co_id, new_date, new_spell, new_machine, exclude_id=entry_id
        ):
            raise HTTPException(status_code=400, detail=DUPLICATE_MSG)

        # const_meter / meter_wrap_limit are machine snapshots: re-snapshot on machine change.
        const_meter = float(existing.const_meter)
        attr = _fetch_machine_attr(db, co_id, new_machine)
        if new_machine != int(existing.machine_id):
            if not attr:
                raise HTTPException(status_code=400, detail=NO_ATTR_MSG)
            const_meter = float(attr.const_meter)
        wrap_limit = int(attr.meter_wrap_limit) if attr else 10000

        diff_meter = compute_diff_meter(new_open, new_close, wrap_limit)
        if diff_meter < 0:
            raise HTTPException(status_code=400, detail=NEGATIVE_DIFF_MSG)
        actual_eff = compute_eff(diff_meter, const_meter, new_hours)

        user_id = token_data.get("user_id")
        db.execute(
            text(
                """
                UPDATE jute_prod_drawing_entry
                SET tran_date = :tran_date,
                    spell = :spell,
                    machine_id = :machine_id,
                    open_meter = :open_meter,
                    close_meter = :close_meter,
                    diff_meter = :diff_meter,
                    const_meter = :const_meter,
                    wrk_hours = :wrk_hours,
                    actual_eff = :actual_eff,
                    remarks = :remarks,
                    updated_by = :updated_by
                WHERE drawing_entry_id = :id
                """
            ),
            {
                "id": entry_id,
                "tran_date": new_date,
                "spell": new_spell,
                "machine_id": new_machine,
                "open_meter": new_open,
                "close_meter": new_close,
                "diff_meter": diff_meter,
                "const_meter": const_meter,
                "wrk_hours": new_hours,
                "actual_eff": actual_eff,
                "remarks": new_remarks,
                "updated_by": user_id,
            },
        )
        db.commit()
        return {"data": {"message": "Updated"}}
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
    co_id = _require_co_id(request)
    try:
        existing = db.execute(
            text(
                """
                SELECT drawing_entry_id
                FROM jute_prod_drawing_entry
                WHERE drawing_entry_id = :id AND co_id = :co_id AND active = 1
                """
            ),
            {"id": entry_id, "co_id": co_id},
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Drawing entry not found")

        db.execute(
            text("UPDATE jute_prod_drawing_entry SET active = 0 WHERE drawing_entry_id = :id"),
            {"id": entry_id},
        )
        db.commit()
        return {"data": {"message": "Deleted"}}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
