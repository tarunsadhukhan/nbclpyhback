"""Spreader Production Entry endpoints."""

from datetime import date, datetime, time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.authorization.utils import get_current_user_with_refresh
from src.config.db import get_tenant_db
from src.juteProduction.constants import SPREADER_MACHINE_TYPE_NAME
from src.juteProduction.query import (
    get_active_bins_query,
    get_entries_by_date_query,
    get_item_maturity_map_query,
    get_jute_items_query,
    get_spreader_machines_query,
)
from src.juteProduction.services.spreader_rules import (
    assign_or_reuse_entry_id_grp,
    evaluate_4hr_window,
    get_bin_state,
)


router = APIRouter()


# =============================================================================
# Pydantic models
# =============================================================================


class SpreaderEntryCreate(BaseModel):
    co_id: int
    branch_id: Optional[int] = None
    entry_date: date
    entry_time: int = Field(ge=0, le=23)
    spell: str
    machine_id: int
    item_id: int
    bin_id: int
    trolley_no: Optional[int] = None
    no_of_rolls: int = Field(gt=0)
    wt_per_roll: float = Field(gt=0)
    remarks: Optional[str] = None


class SpreaderEntryUpdate(BaseModel):
    entry_date: Optional[date] = None
    entry_time: Optional[int] = Field(default=None, ge=0, le=23)
    spell: Optional[str] = None
    machine_id: Optional[int] = None
    bin_id: Optional[int] = None
    trolley_no: Optional[int] = None
    no_of_rolls: Optional[int] = Field(default=None, gt=0)
    wt_per_roll: Optional[float] = Field(default=None, gt=0)
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


def _combine(d: date, h: int) -> datetime:
    return datetime.combine(d, time(hour=int(h)))


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
        machines = [
            dict(r._mapping)
            for r in db.execute(
                get_spreader_machines_query(),
                {"co_id": co_id, "spreader_type": SPREADER_MACHINE_TYPE_NAME, "branch_id": branch_id},
            ).fetchall()
        ]
        bins = [
            dict(r._mapping)
            for r in db.execute(
                get_active_bins_query(), {"co_id": co_id, "branch_id": branch_id}
            ).fetchall()
        ]
        items = [dict(r._mapping) for r in db.execute(get_jute_items_query(), {"co_id": co_id}).fetchall()]
        maturity = {
            int(r._mapping["item_id"]): int(r._mapping["maturity_hours"])
            for r in db.execute(get_item_maturity_map_query(), {"co_id": co_id}).fetchall()
        }
        return {
            "data": {
                "machines": machines,
                "bins": bins,
                "items": items,
                "maturity_map": maturity,
                "spells": [
                    {"code": "A1", "label": "A1 (06-10)"},
                    {"code": "B1", "label": "B1 (11-13)"},
                    {"code": "A2", "label": "A2 (14-16)"},
                    {"code": "B2", "label": "B2 (17-21)"},
                    {"code": "C", "label": "C (22-05)"},
                ],
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/entry_bin_state")
def entry_bin_state(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    co_id = _require_co_id(request)
    try:
        bin_id = int(request.query_params.get("bin_id", ""))
        entry_date_s = request.query_params.get("entry_date")
        entry_time_s = request.query_params.get("entry_time")
        if not entry_date_s or entry_time_s is None:
            raise HTTPException(status_code=400, detail="entry_date and entry_time are required")
        entry_d = date.fromisoformat(entry_date_s)
        entry_h = int(entry_time_s)
        candidate_dt = _combine(entry_d, entry_h)
        state = get_bin_state(db, co_id, bin_id, candidate_dt)
        return {"data": state}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Endpoints — CRUD
# =============================================================================


@router.post("/entry_create")
def entry_create(
    body: SpreaderEntryCreate,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        candidate_dt = _combine(body.entry_date, body.entry_time)
        grp, _reused = assign_or_reuse_entry_id_grp(
            db, body.co_id, body.bin_id, body.item_id, candidate_dt
        )
        user_id = token_data.get("user_id")
        branch_id = body.branch_id
        if branch_id is None:
            # Derive branch from the machine's department so new rows are never NULL.
            derived = db.execute(
                text(
                    """
                    SELECT d.branch_id
                    FROM machine_mst m
                    INNER JOIN dept_mst d ON d.dept_id = m.dept_id
                    WHERE m.machine_id = :machine_id
                    """
                ),
                {"machine_id": int(body.machine_id)},
            ).fetchone()
            branch_id = derived.branch_id if derived else None
        ins = text(
            """
            INSERT INTO spreader_prod_entry
                (co_id, branch_id, entry_date, entry_time, entry_dt, spell,
                 machine_id, item_id, bin_id, trolley_no, no_of_rolls, wt_per_roll,
                 entry_id_grp, status_id, remarks, active, updated_by)
            VALUES
                (:co_id, :branch_id, :entry_date, :entry_time, :entry_dt, :spell,
                 :machine_id, :item_id, :bin_id, :trolley_no, :no_of_rolls, :wt_per_roll,
                 :entry_id_grp, :status_id, :remarks, 1, :updated_by)
            """
        )
        result = db.execute(
            ins,
            {
                "co_id": body.co_id,
                "branch_id": branch_id,
                "entry_date": body.entry_date,
                "entry_time": int(body.entry_time),
                "entry_dt": candidate_dt,
                "spell": body.spell,
                "machine_id": int(body.machine_id),
                "item_id": int(body.item_id),
                "bin_id": int(body.bin_id),
                "trolley_no": int(body.trolley_no) if body.trolley_no is not None else None,
                "no_of_rolls": int(body.no_of_rolls),
                "wt_per_roll": float(body.wt_per_roll),
                "entry_id_grp": int(grp),
                "status_id": 1,
                "remarks": body.remarks,
                "updated_by": user_id,
            },
        )
        db.commit()
        return {"data": {"spreader_prod_entry_id": result.lastrowid, "entry_id_grp": grp}}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
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
    d = request.query_params.get("entry_date")
    if not d:
        raise HTTPException(status_code=400, detail="entry_date is required")
    try:
        d_val = date.fromisoformat(d)
        rows = db.execute(
            get_entries_by_date_query(), {"co_id": co_id, "d": d_val, "branch_id": branch_id}
        ).fetchall()
        data = [dict(r._mapping) for r in rows]
        for row in data:
            if row.get("produced_kg") is not None:
                row["produced_kg"] = float(row["produced_kg"])
            if row.get("wt_per_roll") is not None:
                row["wt_per_roll"] = float(row["wt_per_roll"])
        return {"data": data}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/entry_edit/{entry_id}")
def entry_edit(
    entry_id: int,
    body: SpreaderEntryUpdate,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    co_id = _require_co_id(request)
    try:
        existing = db.execute(
            text(
                """
                SELECT spreader_prod_entry_id, co_id, entry_date, entry_time, bin_id,
                       item_id, entry_id_grp
                FROM spreader_prod_entry
                WHERE spreader_prod_entry_id = :id AND co_id = :co_id AND active = 1
                """
            ),
            {"id": entry_id, "co_id": co_id},
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Spreader entry not found")

        # Determine the new datetime and re-check 4-hr window if date/time changed.
        new_date = body.entry_date or existing.entry_date
        new_time = body.entry_time if body.entry_time is not None else existing.entry_time
        new_dt = _combine(new_date, int(new_time))
        if body.entry_date is not None or body.entry_time is not None:
            win = evaluate_4hr_window(db, int(existing.entry_id_grp), new_dt)
            # If the entry being edited is the only / earliest row, win may simply move base; that's OK.
            if win is not None and not win.allowed:
                raise HTTPException(status_code=400, detail=win.reason)

        fields = []
        params: dict = {"id": entry_id}
        if body.entry_date is not None:
            fields += ["entry_date = :entry_date", "entry_dt = :entry_dt"]
            params["entry_date"] = new_date
            params["entry_dt"] = new_dt
        if body.entry_time is not None:
            fields += ["entry_time = :entry_time"]
            params["entry_time"] = int(new_time)
            if "entry_dt = :entry_dt" not in fields:
                fields += ["entry_dt = :entry_dt"]
                params["entry_dt"] = new_dt
        if body.spell is not None:
            fields.append("spell = :spell")
            params["spell"] = body.spell
        if body.machine_id is not None:
            fields.append("machine_id = :machine_id")
            params["machine_id"] = int(body.machine_id)
        if body.bin_id is not None and int(body.bin_id) != int(existing.bin_id):
            # Changing bin would invalidate the original group assignment — not supported in edit.
            raise HTTPException(
                status_code=400, detail="Bin cannot be changed on an existing entry; delete and re-create instead."
            )
        if body.trolley_no is not None:
            fields.append("trolley_no = :trolley_no")
            params["trolley_no"] = int(body.trolley_no)
        if body.no_of_rolls is not None:
            fields.append("no_of_rolls = :no_of_rolls")
            params["no_of_rolls"] = int(body.no_of_rolls)
        if body.wt_per_roll is not None:
            fields.append("wt_per_roll = :wt_per_roll")
            params["wt_per_roll"] = float(body.wt_per_roll)
        if body.remarks is not None:
            fields.append("remarks = :remarks")
            params["remarks"] = body.remarks

        if not fields:
            return {"data": {"message": "No fields to update"}}

        user_id = token_data.get("user_id")
        fields.append("updated_by = :updated_by")
        params["updated_by"] = user_id

        sql = text(
            f"UPDATE spreader_prod_entry SET {', '.join(fields)} WHERE spreader_prod_entry_id = :id"
        )
        db.execute(sql, params)
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
                SELECT spreader_prod_entry_id, entry_id_grp
                FROM spreader_prod_entry
                WHERE spreader_prod_entry_id = :id AND co_id = :co_id AND active = 1
                """
            ),
            {"id": entry_id, "co_id": co_id},
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Spreader entry not found")

        # Block deletion if the group already has any active issues — MIS rule.
        issue_count = db.execute(
            text(
                """
                SELECT COUNT(*) FROM spreader_roll_issue
                WHERE entry_id_grp = :grp AND co_id = :co_id AND active = 1
                """
            ),
            {"grp": int(existing.entry_id_grp), "co_id": co_id},
        ).scalar()
        if issue_count and int(issue_count) > 0:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Issues already exist for group {existing.entry_id_grp}. "
                    "Delete the related issues first."
                ),
            )

        db.execute(
            text("UPDATE spreader_prod_entry SET active = 0 WHERE spreader_prod_entry_id = :id"),
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
