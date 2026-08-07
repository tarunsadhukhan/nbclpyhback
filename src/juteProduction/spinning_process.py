"""Spinning Process + status endpoints. Prefix /api/spinningProd.

Process is set-based, one transaction: run the fill-sync automatically (spec
5.4 — settlement-time catch-up, attendance is habitually late), BLOCK on doff
rows still item_id NULL (B1), collect WARN lists (no_standard / no_count /
W3 doffs-no-operator / W11 attendance-inactive), soft-delete + INSERT...SELECT
freeze from spinning_day_slice_sql (the same SQL the live grid serves), lock
header upsert. process_status recomputes count/doff/winding drift for a locked
unit and surfaces processed_date_time (spec 5.6.3). Mirror of
weaving_process.py."""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.authorization.utils import get_current_user_with_refresh
from src.config.db import get_tenant_db
from src.juteProduction.constants import SPINNING_MACHINE_TYPE_NAME
from src.juteProduction.spinning_entry import (
    _optional_spell_id_param,
    _resolve_spell,
    _run_doff_sync,
)
from src.juteProduction.spinning_lock import get_process_lock, require_edit_if_locked
from src.juteProduction.spinning_query import (
    get_spinning_attendance_inactive_query,
    get_spinning_drift_query,
    get_spinning_process_lock_row_query,
    get_spinning_process_no_count_query,
    get_spinning_process_no_standard_query,
    get_spinning_unmapped_produced_machines_query,
    insert_spinning_log_from_slice_query,
    insert_spinning_process_lock_query,
    soft_delete_spinning_log_for_unit_query,
    update_spinning_process_lock_query,
    update_spinning_process_lock_reprocess_query,
)

router = APIRouter()

BLOCK_MSG = "Cannot process: these machines have doff production but no mapped quality."


class ProcessRequest(BaseModel):
    co_id: int
    branch_id: Optional[int] = None
    tran_date: date
    spell: Optional[str] = None  # deprecated — send spell_id
    spell_id: Optional[int] = None  # preferred; exactly one of spell/spell_id


def _rows(res):
    return [dict(r._mapping) for r in res.fetchall()]


@router.post("/process")
def process_spinning(
    body: ProcessRequest,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        spell_id = _resolve_spell(db, body.spell_id, body.spell, body.branch_id)
        user_id = token_data.get("user_id")
        binds = {"co_id": int(body.co_id), "tran_date": body.tran_date,
                 "spell_id": int(spell_id)}

        # Re-processing a locked unit requires Edit.
        require_edit_if_locked(db, token_data, body.co_id, body.branch_id,
                               body.tran_date, spell_id)

        # Fill-sync automatically before freezing (spec 5.4) — repairs NULL
        # item stamps from the mapper as-of and fills eb_id from attendance.
        # Same transaction as the freeze; commits together.
        sync_result = _run_doff_sync(
            db,
            co_id=body.co_id,
            branch_id=body.branch_id,
            tran_date=body.tran_date,
            spell_id=spell_id,
            mode="fill",
            targets=["quality", "operator"],
        )

        # BLOCK B1: doff rows still item_id IS NULL after fill-sync (unmapped
        # at post time, unrepaired) — co-scoped via the machine spine.
        unmapped = _rows(db.execute(
            get_spinning_unmapped_produced_machines_query(), binds))
        if unmapped:
            raise HTTPException(status_code=400,
                                detail={"message": BLOCK_MSG, "unmapped": unmapped})

        # WARN collectors (set-based). W11: sync-stamped eb whose backing
        # attendance was later rejected/deactivated. Joins on spell_id (already
        # in binds) — spell_code repeats per shift generation, so the old name
        # join spanned generations and under-reported.
        attendance_inactive = _rows(db.execute(
            get_spinning_attendance_inactive_query(), binds))
        warnings = {
            "no_standard": _rows(db.execute(get_spinning_process_no_standard_query(), binds)),
            "no_count": _rows(db.execute(get_spinning_process_no_count_query(), binds)),
            "sync": {
                "quality_stamped": sync_result["quality_stamped"],
                "operator_stamped": sync_result["operator_stamped"],
            },
            "doffs_no_operator": sync_result["exceptions"]["doffs_no_operator"],  # W3
            "attendance_inactive": attendance_inactive,  # W11
        }

        # Soft-delete prior frozen rows (idempotent reprocess).
        db.execute(soft_delete_spinning_log_for_unit_query(),
                   {**binds, "updated_by": user_id})

        # Freeze: INSERT ... SELECT from the day-slice — one statement, cost
        # independent of frame count. Branch-UNfiltered so the frozen unit is
        # complete; branch scoping applies on read.
        slice_binds = {**binds, "branch_id": None, "updated_by": user_id,
                       "spinning_type": SPINNING_MACHINE_TYPE_NAME}
        result = db.execute(insert_spinning_log_from_slice_query(), slice_binds)
        processed = int(result.rowcount)

        # Lock header upsert (branch-scoped probe — must not match another branch).
        lock = db.execute(
            get_spinning_process_lock_row_query(),
            {**binds, "branch_id": None if body.branch_id is None else int(body.branch_id)},
        ).fetchone()
        if lock:
            db.execute(update_spinning_process_lock_query(),
                       {"id": lock.spinning_process_lock_id, "processed_by": user_id})
        else:
            db.execute(insert_spinning_process_lock_query(),
                       {**binds,
                        "branch_id": None if body.branch_id is None else int(body.branch_id),
                        "processed_by": user_id})

        db.commit()
        return {"data": {"processed": processed, "warnings": warnings}}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/process_status")
def process_status(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_raw = request.query_params.get("co_id")
        if not co_raw:
            raise HTTPException(status_code=400, detail="co_id is required")
        d = request.query_params.get("tran_date")
        spell_raw = request.query_params.get("spell") or None
        spell_id_param = _optional_spell_id_param(request)
        if not d or not (spell_raw or spell_id_param):
            raise HTTPException(
                status_code=400, detail="tran_date and spell_id (or spell) are required"
            )
        branch_raw = request.query_params.get("branch_id")
        branch_id = int(branch_raw) if branch_raw else None
        co_id = int(co_raw)
        d_val = date.fromisoformat(d)
        spell_id = _resolve_spell(db, spell_id_param, spell_raw, branch_id)

        lock = get_process_lock(db, co_id, branch_id, d_val, spell_id)
        if not lock or not lock.is_locked:
            return {"data": {"locked": False, "reprocess_needed": False,
                             "processed_date_time": None}}

        drift = db.execute(
            get_spinning_drift_query(),
            {"co_id": co_id, "tran_date": d_val, "spell_id": spell_id},
        ).fetchone()
        needed = drift is not None
        if needed and not lock.reprocess_needed:
            db.execute(update_spinning_process_lock_reprocess_query(),
                       {"id": lock.spinning_process_lock_id})
            db.commit()
        pdt = getattr(lock, "processed_date_time", None)
        return {"data": {"locked": True,
                         "reprocess_needed": bool(needed or lock.reprocess_needed),
                         "processed_date_time": str(pdt) if pdt is not None else None}}
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tran_date")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
