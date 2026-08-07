"""Weaving Process + status endpoints (spec §6/§8). Prefix /api/weavingProd.

Process is set-based, one transaction: BLOCK on unmapped quality AND on daily rows
whose stored quality is NULL/stale vs the active map, collect WARN lists (no_worker /
no_standard / no_picks / negative_jugar), resolve open_jugar per unit row
(full-history two-probe), soft-delete + INSERT...SELECT freeze from
weaving_day_slice_sql (parity oracle — never the Python resolvers), best-effort eb
stamp, lock header upsert. Every unit query is branch-scoped when the body sends
branch_id (NULL = co-wide). process_status recomputes SQC/stoppage drift for a
locked unit."""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.authorization.utils import get_current_user_with_refresh
from src.config.db import get_tenant_db
from src.juteProduction.weaving_entry import _derive_co_id, _i
# Shared spell-resolution contract (spell_id preferred, branch-scoped code fallback) —
# import, do NOT copy. See spinning_entry._resolve_spell.
from src.juteProduction.spinning_entry import _resolve_spell, _optional_spell_id_param
from src.juteProduction.weaving_lock import get_process_lock, require_edit_if_locked
from src.juteProduction.weaving_query import (
    get_weaving_unit_daily_ids_query,
    get_weaving_unmapped_produced_looms_query,
    get_weaving_process_quality_mismatch_query,
    get_weaving_process_negative_jugar_query,
    get_weaving_process_no_worker_query,
    get_weaving_process_no_standard_query,
    get_weaving_process_no_picks_query,
    soft_delete_weaving_log_for_unit_query,
    insert_weaving_log_from_slice_query,
    update_weaving_log_eb_stamp_query,
    get_weaving_process_lock_row_query,
    insert_weaving_process_lock_query,
    update_weaving_process_lock_query,
    update_weaving_process_lock_reprocess_query,
    get_weaving_drift_query,
    resolve_weaving_open_jugar_for_row_query,
    update_weaving_daily_open_jugar_query,
)

router = APIRouter()

BLOCK_MSG = "Cannot process: these looms have production but no mapped quality."


class ProcessRequest(BaseModel):
    co_id: Optional[int] = None
    branch_id: Optional[int] = None
    tran_date: date
    spell_id: Optional[int] = None  # preferred — validated against the branch's shifts
    spell: Optional[str] = None  # DEPRECATED spell CODE fallback (branch-scoped)


def _rows(res):
    return [dict(r._mapping) for r in res.fetchall()]


@router.post("/process")
def process_weaving(
    body: ProcessRequest,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        spell_id = _resolve_spell(db, body.spell_id, body.spell, body.branch_id)
        co_id = body.co_id if body.co_id is not None else _derive_co_id(db, body.branch_id)
        if co_id is None:
            raise HTTPException(
                status_code=400,
                detail="co_id is required (or a branch_id it can be derived from)",
            )
        user_id = token_data.get("user_id")
        # branch_id scopes every unit query (NULL = co-wide) so branch A's Process
        # never re-freezes branch B's rows on shared-spell tenants.
        binds = {
            "co_id": int(co_id),
            "tran_date": body.tran_date,
            "spell_id": int(spell_id),
            "branch_id": _i(body.branch_id),
        }

        # Re-processing a locked unit requires Edit.
        require_edit_if_locked(db, token_data, co_id, body.branch_id, body.tran_date, spell_id)

        # (2) BLOCK: any produced loom without a mapped quality, plus any daily row
        # whose STORED quality is NULL/stale vs the active map (capture-before-map or
        # pre-re-stamp remap) — freezing either would compute zero/wrong production.
        unmapped = _rows(db.execute(get_weaving_unmapped_produced_looms_query(), binds))
        mismatch = _rows(db.execute(get_weaving_process_quality_mismatch_query(), binds))
        if unmapped or mismatch:
            raise HTTPException(status_code=400, detail={
                "message": BLOCK_MSG,
                "unmapped": unmapped,
                "quality_mismatch": [r["mech_code"] for r in mismatch],
            })

        # (3) WARN collectors.
        warnings = {
            "no_worker": _rows(db.execute(get_weaving_process_no_worker_query(), binds)),
            "no_standard": _rows(db.execute(get_weaving_process_no_standard_query(), binds)),
            "no_picks": _rows(db.execute(get_weaving_process_no_picks_query(), binds)),
        }

        # (4) open_jugar resolve — per-row two-probe over the unit (full history; never a
        # partitioned LAG or a single correlated UPDATE — MySQL 1093).
        for r in db.execute(get_weaving_unit_daily_ids_query(), binds).fetchall():
            rid = int(r.weaving_daily_id)
            resolved = db.execute(
                resolve_weaving_open_jugar_for_row_query(), {"row_id": rid}
            ).fetchone()
            if resolved is not None:
                db.execute(update_weaving_daily_open_jugar_query(),
                           {"row_id": rid, "open_jugar": float(resolved.open_jugar or 0)})

        # (4b) WARN: negative straight-count total_jugar (by design representable —
        # e.g. mid-spell beam change — so surfaced, never clamped or blocked).
        # Collected AFTER the open_jugar re-resolve so it sees the repaired values.
        warnings["negative_jugar"] = _rows(
            db.execute(get_weaving_process_negative_jugar_query(), binds))

        # (5) soft-delete prior log rows (idempotent reprocess).
        db.execute(soft_delete_weaving_log_for_unit_query(), {**binds, "updated_by": user_id})

        # (6) freeze: INSERT ... SELECT from the day-slice (+ SQC fingerprint).
        # branch_id rides in binds — a branch-scoped Process freezes only its rows.
        slice_binds = {**binds, "machine_id": None, "updated_by": user_id}
        result = db.execute(insert_weaving_log_from_slice_query(), slice_binds)
        processed = int(result.rowcount)

        # (7) best-effort eb stamp.
        db.execute(update_weaving_log_eb_stamp_query(), binds)

        # (9) lock header upsert.
        lock = db.execute(get_weaving_process_lock_row_query(), binds).fetchone()
        if lock:
            db.execute(update_weaving_process_lock_query(),
                       {"id": lock.weaving_process_lock_id, "processed_by": user_id})
        else:
            db.execute(insert_weaving_process_lock_query(),
                       {**binds, "processed_by": user_id})

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
        spell_raw = request.query_params.get("spell")
        spell_id_param = _optional_spell_id_param(request)
        if not d or (spell_id_param is None and not spell_raw):
            raise HTTPException(
                status_code=400,
                detail="tran_date and spell_id (or spell) are required",
            )
        branch_raw = request.query_params.get("branch_id")
        branch_id = int(branch_raw) if branch_raw else None
        co_id = int(co_raw)
        d_val = date.fromisoformat(d)
        spell_id = _resolve_spell(db, spell_id_param, spell_raw, branch_id)

        lock = get_process_lock(db, co_id, branch_id, d_val, spell_id)
        if not lock or not lock.is_locked:
            return {"data": {"locked": False, "reprocess_needed": False}}

        drift = db.execute(
            get_weaving_drift_query(),
            {"co_id": co_id, "tran_date": d_val, "spell_id": spell_id},
        ).fetchone()
        needed = drift is not None
        if needed and not lock.reprocess_needed:
            db.execute(update_weaving_process_lock_reprocess_query(),
                       {"id": lock.weaving_process_lock_id})
            db.commit()
        return {"data": {"locked": True, "reprocess_needed": bool(needed or lock.reprocess_needed)}}
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tran_date")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
