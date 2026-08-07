"""Spinning quality mapper endpoints (spec 5.3). Prefix /api/spinningProd.

GET /quality_map_grid — one row per active spinning machine with its current
helper mapping + mapper history count, plus the yarn-item master list.

POST /quality_map_save — ONE transaction: validate (future date 400, yarn item
active, machine active + spinning type), mapper INSERT, helper RE-DERIVATION
from the latest active mapper row (uq_sqh_mc — backdated saves never regress
it), retro UPDATE per retro_mode (fill | synced | all — 'all' needs Edit)
scoped below each machine's next change-point, explicit
flag_reprocess_if_locked on every locked (co, date, spell) unit the retro
range crosses — co derived from the machine's dept->branch spine, not the
body (drift detection is blind to pure item reassignment, T6), and a
confirm:false preview path that writes NOTHING.

Conventions mirror spinning_process.py: get_tenant_db +
get_current_user_with_refresh, {"data": ...} responses, rollback-on-exception.
"""

from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.authorization.utils import get_current_user_with_refresh
from src.config.db import get_tenant_db
from src.juteProduction.constants import SPINNING_MACHINE_TYPE_NAME
from src.juteProduction.spinning_entry import (
    _optional_branch_id,
    _require_co_id,
    _resolve_spell,
)
from src.juteProduction.spinning_lock import (
    EDIT_LEVEL,
    SPINNING_MENU_PATH,
    flag_reprocess_if_locked,
    user_menu_access_level,
)
from src.juteProduction.spinning_quality_map_query import (
    RETRO_MODES,
    count_retro_doff_rows_query,
    get_locked_units_in_retro_range_query,
    get_next_change_point_query,
    get_quality_map_grid_query,
    get_quality_map_yarns_query,
    get_spell_starting_time_query,
    insert_quality_mapper_query,
    rederive_quality_helper_query,
    retro_update_doff_rows_query,
    update_mapper_retro_rows_query,
    validate_spinning_machine_query,
    validate_yarn_item_query,
)

router = APIRouter()

FUTURE_DATE_MSG = (
    "effective_from_date cannot be in the future — shop-floor changes are "
    "'now' or backdated"
)
EDIT_REQUIRED_ALL_MSG = (
    "retro_mode 'all' requires Edit permission for the Spinning Production menu"
)
EDIT_REQUIRED_LOCKED_MSG = (
    "The retro range crosses processed/locked day-spell units — Edit "
    "permission for the Spinning Production menu is required"
)


class QualityMapEntry(BaseModel):
    mc_id: int
    item_id: int


class QualityMapSave(BaseModel):
    co_id: int
    branch_id: Optional[int] = None
    entries: List[QualityMapEntry] = Field(min_length=1)
    effective_from_date: date
    effective_from_spell: Optional[str] = None  # spell_code (deprecated); None = start of day
    effective_from_spell_id: Optional[int] = None  # preferred; exactly one when a spell is given
    retro_mode: str = "fill"  # fill | synced | all
    confirm: bool = False  # False = preview counts only, write nothing


@router.get("/quality_map_grid")
def quality_map_grid(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = _require_co_id(request)
        branch_id = _optional_branch_id(request)

        machines = [
            dict(r._mapping)
            for r in db.execute(
                get_quality_map_grid_query(),
                {"spinning_type": SPINNING_MACHINE_TYPE_NAME, "branch_id": branch_id},
            ).fetchall()
        ]
        yarn_items = [
            dict(r._mapping)
            for r in db.execute(
                get_quality_map_yarns_query(), {"co_id": int(co_id)}
            ).fetchall()
        ]
        return {"data": {"machines": machines, "yarn_items": yarn_items}}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/quality_map_save")
def quality_map_save(
    body: QualityMapSave,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        if body.retro_mode not in RETRO_MODES:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid retro_mode '{body.retro_mode}' (fill | synced | all)",
            )
        # Step 1 (T2): future effective date would poison the helper.
        if body.effective_from_date > date.today():
            raise HTTPException(status_code=400, detail=FUTURE_DATE_MSG)

        co_id = int(body.co_id)
        user_id = token_data.get("user_id")

        # Effective spell (optional) -> spell_id + starting_time comparator.
        eff_spell_id = None
        eff_start_time = None
        if body.effective_from_spell_id is not None or body.effective_from_spell:
            eff_spell_id = _resolve_spell(
                db,
                body.effective_from_spell_id,
                body.effective_from_spell,
                body.branch_id,
            )
            spell_row = db.execute(
                get_spell_starting_time_query(), {"spell_id": eff_spell_id}
            ).fetchone()
            eff_start_time = spell_row.starting_time if spell_row else None

        # 'all' rewrites manual rows too -> Edit level, preview included.
        if body.retro_mode == "all":
            if (
                user_menu_access_level(
                    db, user_id, co_id, body.branch_id, SPINNING_MENU_PATH
                )
                < EDIT_LEVEL
            ):
                raise HTTPException(status_code=403, detail=EDIT_REQUIRED_ALL_MSG)

        scope = {
            "eff_date": body.effective_from_date,
            "eff_start_time": eff_start_time,
        }

        # Step 1 continued: validate every entry BEFORE any write; compute each
        # machine's retro cap (next change-point, D2) from PRE-EXISTING mapper
        # rows; collect the locked (co, date, spell) units the capped retro
        # range crosses (deduped). co comes from the machine's OWN
        # dept->branch spine (D3a), never the caller-supplied body co_id.
        validated = []  # (mc_id, item_id, machine_branch_id, machine_co, entry_scope)
        locked_units: dict = {}
        for entry in body.entries:
            mc = db.execute(
                validate_spinning_machine_query(),
                {
                    "machine_id": int(entry.mc_id),
                    "spinning_type": SPINNING_MACHINE_TYPE_NAME,
                },
            ).fetchone()
            if not mc:
                raise HTTPException(
                    status_code=400,
                    detail=f"Machine {entry.mc_id} is not an active spinning machine",
                )
            item = db.execute(
                validate_yarn_item_query(),
                {"item_id": int(entry.item_id), "co_id": co_id},
            ).fetchone()
            if not item:
                raise HTTPException(
                    status_code=400,
                    detail=f"Item {entry.item_id} is not an active yarn item",
                )
            mc_co = int(mc.co_id)
            nxt = db.execute(
                get_next_change_point_query(),
                {"mc_id": int(entry.mc_id), **scope},
            ).fetchone()
            entry_scope = {
                **scope,
                "next_date": nxt.next_date if nxt else None,
                "next_start_time": nxt.next_start_time if nxt else None,
            }
            validated.append(
                (int(entry.mc_id), int(entry.item_id), mc.branch_id, mc_co, entry_scope)
            )

            for r in db.execute(
                get_locked_units_in_retro_range_query(),
                {"mc_id": int(entry.mc_id), "co_id": mc_co, **entry_scope},
            ).fetchall():
                key = (mc_co, str(r.tran_date), int(r.spell_id))
                locked_units[key] = {
                    "co_id": mc_co,
                    "tran_date": str(r.tran_date),
                    "spell_id": int(r.spell_id),
                }
        reprocessed = sorted(
            locked_units.values(), key=lambda u: (u["tran_date"], u["spell_id"])
        )
        # Response shape stays {tran_date, spell_id}; co_id is internal (flag key).
        reprocessed_public = [
            {"tran_date": u["tran_date"], "spell_id": u["spell_id"]}
            for u in reprocessed
        ]

        # Preview path (confirm:false): counts only, write NOTHING. Same
        # per-machine cap as the real retro UPDATE (D2).
        if not body.confirm:
            total = 0
            for mc_id, _item_id, _b, _co, entry_scope in validated:
                total += int(
                    db.execute(
                        count_retro_doff_rows_query(body.retro_mode),
                        {"mc_id": mc_id, **entry_scope},
                    ).scalar()
                    or 0
                )
            return {
                "data": {
                    "mapper_ids": [],
                    "retro_rows": total,
                    "reprocessed_units": reprocessed_public,
                    "preview": True,
                }
            }

        # Crossing a locked unit requires Edit (already proven for 'all').
        if reprocessed and body.retro_mode != "all":
            if (
                user_menu_access_level(
                    db, user_id, co_id, body.branch_id, SPINNING_MENU_PATH
                )
                < EDIT_LEVEL
            ):
                raise HTTPException(status_code=403, detail=EDIT_REQUIRED_LOCKED_MSG)

        # Steps 2-4 per entry: mapper INSERT, helper re-derivation, capped retro
        # UPDATE. branch_id denormalized from the machine's dept (spec 5.1), not
        # the body.
        mapper_ids = []
        total_retro = 0
        for mc_id, item_id, mc_branch, _mc_co, entry_scope in validated:
            binds = {
                "branch_id": None if mc_branch is None else int(mc_branch),
                "mc_id": mc_id,
                "item_id": item_id,
                "eff_date": body.effective_from_date,
                "eff_spell_id": eff_spell_id,
                "updated_by": user_id,
            }
            ins = db.execute(
                insert_quality_mapper_query(),
                {**binds, "retro_mode": body.retro_mode},
            )
            mapper_id = int(ins.lastrowid)
            mapper_ids.append(mapper_id)

            # D1: NOT an upsert of the saved rule — the helper is re-derived
            # from the machine's LATEST active mapper row, so a backdated save
            # can never regress it (helper always = latest applicable rule, T3).
            db.execute(
                rederive_quality_helper_query(),
                {"mc_id": mc_id, "updated_by": user_id},
            )

            res = db.execute(
                retro_update_doff_rows_query(body.retro_mode),
                {"mc_id": mc_id, "item_id": item_id, **entry_scope},
            )
            rows = int(res.rowcount or 0)
            total_retro += rows
            db.execute(
                update_mapper_retro_rows_query(),
                {"mapper_id": mapper_id, "retro_rows": rows},
            )

        # Step 5: explicit reprocess flag — drift detection can't see pure item
        # reassignment (same doff SUM, different item). Keyed on each unit's
        # machine-spine co (D3a).
        for unit in reprocessed:
            flag_reprocess_if_locked(
                db, unit["co_id"], unit["tran_date"], unit["spell_id"]
            )

        db.commit()
        return {
            "data": {
                "mapper_ids": mapper_ids,
                "retro_rows": total_retro,
                "reprocessed_units": reprocessed_public,
                "preview": False,
            }
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
