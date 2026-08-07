"""Spinning / Doff Production Entry + Planning-grid endpoints.

Stage 1 — doff entry (daily_doff_tbl), reusing the mobile-app doff table by raw SQL.
          Item identity is stamped at post time (spec 5.2): manual > helper
          (spg_quality_helper, today) > mapper as-of (spg_quality_mapper, backdated);
          /doff_sync (spec 5.4) repairs NULL stamps and fills eb_id from attendance.
Stage 2 — frame map (daily_doff_frames_winding, spg_wdg='S'): legacy mapping surface;
          frame_map_mapped now delegates to the doff_sync internals.
Planning grid — per-frame-per-spell snapshot (jute_prod_spinning_daily). Driver rows
          come from the S frame-map; standards/targets/actuals for speed/tpi/eff resolve
          from the time-versioned jute_prod_spng_target_map (last-date, value_role
          standard|target|actual), act_count from jute_sqc_spinning_count, doff
          from daily_doff_tbl, and winding from jute_prod_winding_prod (allocated by doff
          share). Shift rollups are derived (SUM numerator / SUM denominator), never the
          average of per-spell effs.

Mirrors drawing_entry.py for conventions: get_tenant_db + get_current_user_with_refresh,
{"data": ...} responses, _require_co_id / _optional_branch_id helpers, and the
try/except (HTTPException: rollback; raise) / (Exception: rollback; 500) pattern.
Spell codes are resolved to spell_id at the boundary because the doff tables store
spell_id (INT), not the spell_code string.
"""

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.authorization.utils import get_current_user_with_refresh
from src.config.db import get_tenant_db
from src.juteProduction.constants import (
    ID_TYPE_MC,
    PARAM_BOBBIN_WT,
    SPINNING_MACHINE_TYPE_NAME,
    VALUE_ROLE_STANDARD,
)
from src.juteProduction.services.spinning_rules import (
    compute_net,
    compute_tare,
    validate_net,
)
from src.juteProduction.services.spinning_standards import (
    resolve_param,
)
from src.juteProduction.spinning_lock import (
    EDIT_LEVEL,
    SPINNING_MENU_PATH,
    flag_reprocess_if_locked,
    get_process_lock,
    require_edit_if_locked,
    user_menu_access_level,
)
from src.juteProduction.spinning_query import (
    SPINNER_DESIG_PREFIX,
    deactivate_doff_entries_query,
    get_active_workers_query,
    get_doff_entries_by_date_query,
    get_doff_running_total_query,
    get_exact_duplicate_doff_ids_query,
    get_frame_map_active_row_query,
    get_frame_map_last_updated_query,
    get_frame_map_query,
    get_helper_item_query,
    get_machine_bobbin_batch_query,
    get_machine_codes_query,
    get_mapper_asof_item_query,
    get_operator_candidates_query,
    get_spells_query,
    get_spinning_log_rows_query,
    get_spinning_machines_query,
    get_spinning_planning_slice_query,
    get_sync_item_override_preview_query,
    get_sync_scope_summary_query,
    get_trollies_query,
    get_yarn_qualities_query,
    insert_frame_map_row_query,
    resolve_spell_id_query,
    stamp_operator_query,
    sync_quality_stamp_query,
    update_frame_map_row_query,
)


router = APIRouter()

DOFF_NET_RANGE_MSG = "Computed net weight is out of the valid range (5..60 kg)"
UNKNOWN_SPELL_MSG = "Unknown spell"
NO_MACHINE_ATTR_MSG = "No spinning attributes configured for this machine"
DOFF_NOT_FOUND_MSG = "Doff entry not found"
TROLLY_SCOPE_MSG = "Trolly does not belong to this machine's branch / the spinning stage"
SYNC_FORCE_EDIT_MSG = (
    "mode=force sync requires Edit permission for the Spinning Production menu"
)


# =============================================================================
# Pydantic models
# =============================================================================


class DoffEntryCreate(BaseModel):
    co_id: int
    branch_id: Optional[int] = None
    tran_date: date
    spell: Optional[str] = None  # deprecated — send spell_id
    spell_id: Optional[int] = None  # preferred; exactly one of spell/spell_id
    machine_id: int
    trolly_id: int
    item_id: Optional[int] = None
    gross_weight: float = Field(ge=0)


class DoffEntryUpdate(BaseModel):
    gross_weight: Optional[float] = Field(default=None, ge=0)
    trolly_id: Optional[int] = None
    item_id: Optional[int] = None
    eb_id: Optional[int] = None


class DoffDedupRun(BaseModel):
    co_id: int
    tran_date: date
    spell: Optional[str] = None  # deprecated — send spell_id
    spell_id: Optional[int] = None
    confirm: bool = False  # False = list candidates only, deactivate NOTHING (D8)


class DoffSync(BaseModel):
    """POST /doff_sync body (spec 5.4)."""

    co_id: int
    branch_id: Optional[int] = None
    tran_date: date
    spell: Optional[str] = None  # deprecated — send spell_id
    spell_id: Optional[int] = None
    mode: str = "fill"  # fill | force (force requires Edit level)
    targets: List[str] = Field(default_factory=lambda: ["quality", "operator"])
    ignore_designation: bool = False  # escape hatch for the spinner-designation gate


class FrameMapEntry(BaseModel):
    machine_id: int
    item_id: Optional[int] = None


class FrameMapSave(BaseModel):
    co_id: int
    branch_id: Optional[int] = None
    tran_date: date
    spell: Optional[str] = None  # deprecated — send spell_id
    spell_id: Optional[int] = None
    entries: List[FrameMapEntry] = Field(default_factory=list)


class FrameMapMapped(BaseModel):
    co_id: int
    branch_id: Optional[int] = None
    tran_date: date
    spell: Optional[str] = None  # deprecated — send spell_id
    spell_id: Optional[int] = None


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


def _resolve_spell_id(db: Session, spell_code: str) -> int:
    """spell_code -> canonical spell_id (MIN dedupes branch fanout). 400 if unknown."""
    row = db.execute(resolve_spell_id_query(), {"spell_code": spell_code}).fetchone()
    if not row or row.spell_id is None:
        raise HTTPException(status_code=400, detail=f"{UNKNOWN_SPELL_MSG} '{spell_code}'")
    return int(row.spell_id)


def _resolve_spell(
    db: Session,
    spell_id: Optional[int],
    spell_code: Optional[str],
    branch_id: Optional[int],
) -> int:
    """spell_id-first spell resolution (branch-aware). Exactly ONE of spell_id /
    spell_code must be provided.

    spell_id (preferred): must exist with status=1; when branch_id is given the
    spell's shift must belong to that branch. spell_code (deprecated fallback):
    branch-scoped via shift_mst — spell codes repeat per branch (sls 'A1' =
    91/97/102 on branches 4/29/87), so the legacy unscoped MIN() path
    (_resolve_spell_id) must not be used inside spinning handlers.
    """
    if (spell_id is None) == (not spell_code):
        raise HTTPException(
            status_code=400, detail="Provide exactly one of spell_id or spell"
        )
    if spell_id is not None:
        row = db.execute(
            text(
                """
                SELECT sp.spell_id, sh.branch_id
                FROM spell_mst sp
                LEFT JOIN shift_mst sh ON sh.shift_id = sp.shift_id
                WHERE sp.spell_id = :spell_id AND sp.status = 1
                """
            ),
            {"spell_id": int(spell_id)},
        ).fetchone()
        if not row:
            raise HTTPException(
                status_code=400, detail=f"{UNKNOWN_SPELL_MSG} id {spell_id}"
            )
        if (
            branch_id is not None
            and row.branch_id is not None
            and int(row.branch_id) != int(branch_id)
        ):
            raise HTTPException(
                status_code=400, detail="Spell does not belong to this branch"
            )
        return int(spell_id)
    row = db.execute(
        text(
            """
            SELECT sp.spell_id
            FROM spell_mst sp
            INNER JOIN shift_mst sh ON sh.shift_id = sp.shift_id
            WHERE sp.spell_code = :spell_code
              AND sp.status = 1
              AND (:branch_id IS NULL OR sh.branch_id = :branch_id)
            ORDER BY sp.spell_id
            LIMIT 1
            """
        ),
        {
            "spell_code": spell_code,
            "branch_id": None if branch_id is None else int(branch_id),
        },
    ).fetchone()
    if not row or row.spell_id is None:
        raise HTTPException(status_code=400, detail=f"{UNKNOWN_SPELL_MSG} '{spell_code}'")
    return int(row.spell_id)


def _optional_spell_id_param(request: Request) -> Optional[int]:
    raw = request.query_params.get("spell_id")
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid spell_id")


def _spell_name(db: Session, spell_id: int) -> Optional[str]:
    """spell_id -> spell_name (for operator-stamp join on daily_attendance.spell)."""
    row = db.execute(
        text("SELECT spell_name FROM spell_mst WHERE spell_id = :spell_id"),
        {"spell_id": spell_id},
    ).fetchone()
    return row.spell_name if row else None


def _resolve_bobbin(db: Session, co_id: int, machine_id: int, on_date) -> float:
    """Standard bobbin weight (kg) for the machine effective on ``on_date``.

    Resolved from the time-versioned jute_prod_spng_target_map (id_type=mcid,
    value_role=standard, param=bobbin_wt). Missing / non-positive standard is a
    hard 400 (spec B5 / 7.2) — bobbin 0.0 silently understates tare, so every
    weight-touching caller (create, edit, prev_state) must refuse instead.
    """
    bobbin = resolve_param(
        db, co_id, machine_id, ID_TYPE_MC, VALUE_ROLE_STANDARD, PARAM_BOBBIN_WT, on_date
    )
    if bobbin is None or float(bobbin) <= 0:
        raise HTTPException(status_code=400, detail=NO_MACHINE_ATTR_MSG)
    return float(bobbin)


def _fetch_trolly(db: Session, trolly_id: int, machine_branch_id: Optional[int] = None):
    """Trolly row (trolly_weight + busket_weight) for tare computation.

    400 on unknown id. When the doff's machine branch is supplied, also enforce
    the setup-page scope (spec 7.6): trolly must be spinning-tagged and belong
    to the machine's branch."""
    row = db.execute(
        text(
            """
            SELECT t.trolly_id, t.trolly_weight, t.busket_weight, t.branch_id,
                   mt.machine_type_name
            FROM trolly_mst t
            LEFT JOIN machine_type_mst mt
                   ON mt.machine_type_id = t.machine_type_id AND mt.active = 1
            WHERE t.trolly_id = :trolly_id
            """
        ),
        {"trolly_id": int(trolly_id)},
    ).fetchone()
    if not row:
        raise HTTPException(status_code=400, detail="Unknown trolly")
    if machine_branch_id is not None:
        # Case-insensitive + None-safe: sls stores 'SPINNING' vs the constant's
        # 'Spinning' — a raw != rejected every valid sls trolly.
        wrong_type = (
            (row.machine_type_name or "").strip().lower()
            != SPINNING_MACHINE_TYPE_NAME.strip().lower()
        )
        wrong_branch = (
            row.branch_id is not None and int(row.branch_id) != int(machine_branch_id)
        )
        if wrong_type or wrong_branch:
            raise HTTPException(status_code=400, detail=TROLLY_SCOPE_MSG)
    return row


def _machine_branch_co(db: Session, machine_id: int):
    """The machine's branch + co via the dept -> branch spine (or None).

    The co side is the 7.4 fix: edit/delete derive the effective co from the
    entry's machine instead of trusting the caller-supplied co_id."""
    return db.execute(
        text(
            """
            SELECT d.branch_id, bm.co_id
            FROM machine_mst m
            INNER JOIN dept_mst d ON d.dept_id = m.dept_id
            INNER JOIN branch_mst bm ON bm.branch_id = d.branch_id
            WHERE m.machine_id = :machine_id
            """
        ),
        {"machine_id": int(machine_id)},
    ).fetchone()


def _compute_doff_tare(
    db: Session,
    co_id: int,
    machine_id: int,
    trolly_id: int,
    on_date,
    machine_branch_id: Optional[int] = None,
) -> float:
    """Tare = trolly_weight + busket_weight + machine bobbin_weight.

    Bobbin weight is resolved from jute_prod_spng_target_map effective on ``on_date``
    (400 when missing — B5); trolly is scope-checked when the machine branch is given.
    """
    trolly = _fetch_trolly(db, trolly_id, machine_branch_id)
    bobbin = _resolve_bobbin(db, co_id, machine_id, on_date)
    return compute_tare(_f(trolly.trolly_weight), _f(trolly.busket_weight), bobbin)


def _spell_start(db: Session, spell_id: int):
    """spell_mst.starting_time for a spell_id (spell-order comparator) or None."""
    row = db.execute(
        text("SELECT starting_time FROM spell_mst WHERE spell_id = :spell_id"),
        {"spell_id": int(spell_id)},
    ).fetchone()
    return row.starting_time if row else None


def _as_timedelta(t) -> Optional[timedelta]:
    """TIME column -> timedelta (PyMySQL yields timedelta; tolerate time)."""
    if t is None or isinstance(t, timedelta):
        return t
    return timedelta(hours=t.hour, minutes=t.minute, seconds=t.second)


def _overnight_date_warning(db: Session, spell_id: int, tran_date) -> bool:
    """D5 soft warn: an overnight spell's post-midnight tail entered with
    TODAY's calendar date — convention is shift-START date (T12), so the doff
    probably belongs on yesterday. Warn only, never reject."""
    row = db.execute(
        text("SELECT is_overnight, end_time FROM spell_mst WHERE spell_id = :spell_id"),
        {"spell_id": int(spell_id)},
    ).fetchone()
    if not row or not row.is_overnight or row.end_time is None:
        return False
    now = datetime.now()
    if tran_date != now.date():
        return False
    now_t = timedelta(hours=now.hour, minutes=now.minute, seconds=now.second)
    end_t = _as_timedelta(row.end_time)
    return end_t is not None and now_t < end_t


def _resolve_doff_item(db: Session, machine_id: int, tran_date, spell_id: int):
    """Resolve a doff row's item identity per spec 5.2.

    Fast path (helper) only when the doff is dated today AND the helper rule's
    effective (effective_from_date, spell-order) <= the doff's (tran_date,
    spell starting_time) — a rule effective from a LATER spell today must not
    stamp an earlier spell's doff (D4); such doffs fall through to the mapper
    as-of query. Backdated always resolves as-of from the mapper (NEVER the
    helper — it holds today's state, wrong for yesterday, T1). Missing helper
    row = unmapped machine (helper is derived from the mapper, so no mapper
    fallback exists either). Returns (item_id, item_source, item_name) with
    (None, None, None) when unmapped.
    """
    doff_start = None
    doff_start_known = False
    if tran_date == date.today():
        row = db.execute(get_helper_item_query(), {"mc_id": int(machine_id)}).fetchone()
        if row is None:
            return None, None, None
        eff_date = row.effective_from_date
        applies = eff_date is None or eff_date < tran_date
        if not applies and eff_date == tran_date:
            # Same-day rule: compare spell order. NULL helper spell = day-start
            # (always applies); NULL doff starting_time sorts as end of day
            # (every same-date rule applies) — mirrors _MAPPER_ASOF_WHERE.
            doff_start = _spell_start(db, spell_id)
            doff_start_known = True
            h_start = row.effective_start_time
            applies = h_start is None or doff_start is None or h_start <= doff_start
        if applies:
            if row.item_id is not None:
                return int(row.item_id), "helper", row.item_name
            return None, None, None
    if not doff_start_known:
        doff_start = _spell_start(db, spell_id)
    row = db.execute(
        get_mapper_asof_item_query(),
        {
            "mc_id": int(machine_id),
            "tran_date": tran_date,
            "spell_start": doff_start,
        },
    ).fetchone()
    if row and row.item_id is not None:
        return int(row.item_id), "mapper", row.item_name
    return None, None, None


# =============================================================================
# Stage 1 — Doff entry
# =============================================================================


@router.get("/doff_entry_create_setup")
def doff_entry_create_setup(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    co_id = _require_co_id(request)
    # branch_id is REQUIRED here: a missing param would silently return every
    # branch's machines/trollies/spells (all setup consumers are branch-scoped).
    branch_id = _optional_branch_id(request)
    if branch_id is None:
        raise HTTPException(status_code=400, detail="branch_id is required")
    try:
        # Bobbin weight is time-versioned in jute_prod_spng_target_map; the setup
        # value is an as-of-today display hint — doff create/edit re-resolve it for
        # the actual tran_date.
        today = date.today()
        bobbin_by_mc = {
            int(r.machine_id): _f(r.bobbin_weight)
            for r in db.execute(
                get_machine_bobbin_batch_query(), {"co_id": co_id, "on_date": today}
            ).fetchall()
        }
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
                    "bobbin_weight": bobbin_by_mc.get(int(m["machine_id"]), 0.0),
                }
            )

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

        trollies = []
        for r in db.execute(
            get_trollies_query(),
            {"branch_id": branch_id, "machine_type_name": SPINNING_MACHINE_TYPE_NAME},
        ).fetchall():
            m = dict(r._mapping)
            trollies.append(
                {
                    "trolly_id": m["trolly_id"],
                    "trolly_name": m["trolly_name"],
                    "trolly_weight": _f(m.get("trolly_weight")),
                    "bucket_weight": _f(m.get("bucket_weight")),
                }
            )

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

        return {
            "data": {
                "machines": machines,
                "spells": spells,
                "trollies": trollies,
                "yarn_items": yarn_items,
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/doff_machine_prev_state")
def doff_machine_prev_state(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    co_id = _require_co_id(request)
    try:
        machine_id_s = request.query_params.get("machine_id")
        tran_date_s = request.query_params.get("tran_date")
        spell = request.query_params.get("spell") or None
        spell_id_param = _optional_spell_id_param(request)
        if not machine_id_s or not tran_date_s or not (spell or spell_id_param):
            raise HTTPException(
                status_code=400,
                detail="machine_id, tran_date and spell_id (or spell) are required",
            )
        machine_id = int(machine_id_s)
        tran_date_val = date.fromisoformat(tran_date_s)
        # Spell resolution is branch-scoped: explicit branch_id param, else the
        # machine's own branch (spell codes repeat per branch on sls).
        mrow = _machine_branch_co(db, machine_id)
        machine_branch = mrow.branch_id if mrow else None
        branch_id = _optional_branch_id(request)
        spell_id = _resolve_spell(
            db, spell_id_param, spell,
            branch_id if branch_id is not None else machine_branch,
        )

        row = db.execute(
            get_doff_running_total_query(),
            {
                "co_id": co_id,
                "tran_date": tran_date_val,
                "spell_id": spell_id,
                "machine_id": machine_id,
            },
        ).fetchone()
        running_total_net = _f(row.total_net) if row else 0.0
        next_doff_no = (int(row.doff_count) if row and row.doff_count is not None else 0) + 1

        trolly_raw = request.query_params.get("trolly_id")
        tare = 0.0
        if trolly_raw:
            tare = _compute_doff_tare(
                db, co_id, machine_id, int(trolly_raw), tran_date_val,
                machine_branch,
            )

        # Mapped yarn prefill (spec 5.3 FE note): helper for today, mapper as-of
        # for a backdated date.
        mapped_item_id, _, mapped_item_name = _resolve_doff_item(
            db, machine_id, tran_date_val, spell_id
        )

        return {
            "data": {
                "running_total_net": running_total_net,
                "next_doff_no": next_doff_no,
                "tare": tare,
                "mapped_item_id": mapped_item_id,
                "mapped_item_name": mapped_item_name,
            }
        }
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid machine_id, tran_date or trolly_id")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/doff_entry_create")
def doff_entry_create(
    body: DoffEntryCreate,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        mrow = _machine_branch_co(db, body.machine_id)
        machine_branch = mrow.branch_id if mrow else None

        # Branch-scoped spell resolution: body branch_id, else the machine's
        # branch (spell codes repeat per branch on sls).
        spell_id = _resolve_spell(
            db, body.spell_id, body.spell,
            body.branch_id if body.branch_id is not None else machine_branch,
        )

        trolly = _fetch_trolly(db, body.trolly_id, machine_branch)
        bobbin = _resolve_bobbin(db, body.co_id, body.machine_id, body.tran_date)

        tare = compute_tare(_f(trolly.trolly_weight), _f(trolly.busket_weight), bobbin)
        net = compute_net(body.gross_weight, tare)
        if not validate_net(net):
            raise HTTPException(status_code=400, detail=DOFF_NET_RANGE_MSG)

        branch_id = body.branch_id
        if branch_id is None:
            branch_id = machine_branch

        require_edit_if_locked(db, token_data, body.co_id, branch_id, body.tran_date, spell_id)

        # Item identity stamped at post time (spec 5.2): explicit item wins
        # ('manual'); else helper (today) / mapper as-of (backdated).
        if body.item_id is not None:
            item_id, item_source = int(body.item_id), "manual"
        else:
            item_id, item_source, _ = _resolve_doff_item(
                db, body.machine_id, body.tran_date, spell_id
            )

        user_id = token_data.get("user_id")
        result = db.execute(
            text(
                """
                INSERT INTO daily_doff_tbl
                    (doff_date, spell, mc_id, quality_id, item_id, item_source,
                     trolly_id, gross_weight, tare_weight, net_weight, weight_type,
                     active, branch_id, updated_by, updated_date_time)
                VALUES
                    (:doff_date, :spell_id, :mc_id, NULL, :item_id, :item_source,
                     :trolly_id, :gross_weight, :tare_weight, :net_weight, 'SPG1',
                     1, :branch_id, :updated_by, NOW())
                """
            ),
            {
                "doff_date": body.tran_date,
                "spell_id": spell_id,
                "mc_id": int(body.machine_id),
                "item_id": item_id,
                "item_source": item_source,
                "trolly_id": int(body.trolly_id),
                "gross_weight": float(body.gross_weight),
                "tare_weight": tare,
                "net_weight": net,
                "branch_id": branch_id,
                "updated_by": user_id,
            },
        )
        flag_reprocess_if_locked(db, body.co_id, body.tran_date, spell_id)
        overnight_warn = _overnight_date_warning(db, spell_id, body.tran_date)
        db.commit()
        data = {
            "daily_doff_tbl_id": result.lastrowid,
            "net_weight": net,
            "tare_weight": tare,
            "item_id": item_id,
            "item_source": item_source,
        }
        if item_id is None:
            data["unmapped_machine"] = True  # T4 warn — Process B1 stays the hard gate
        if overnight_warn:
            # D5/T12: overnight-shift tail dated today — convention is
            # shift-START date; saved as entered, warn only.
            data["overnight_date_warning"] = True
        return {"data": data}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/doff_entries_by_date")
def doff_entries_by_date(
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
    machine_raw = request.query_params.get("machine_id")
    try:
        d_val = date.fromisoformat(d)
        spell_id_param = _optional_spell_id_param(request)
        spell_id = (
            _resolve_spell(db, spell_id_param, spell, branch_id)
            if (spell_id_param is not None or spell)
            else None
        )
        machine_id = int(machine_raw) if machine_raw else None
        rows = db.execute(
            get_doff_entries_by_date_query(),
            {
                "co_id": co_id,
                "tran_date": d_val,
                "spell_id": spell_id,
                "branch_id": branch_id,
                "machine_id": machine_id,
            },
        ).fetchall()
        data = []
        for r in rows:
            row = dict(r._mapping)
            for k in ("gross_weight", "tare_weight", "net_weight"):
                if row.get(k) is not None:
                    row[k] = float(row[k])
            if row.get("doff_date") is not None:
                row["doff_date"] = str(row["doff_date"])
            data.append(row)
        # Unsynced badges (spec 5.6.4): the DOFF table itself is not fully stamped.
        unsynced = {
            "no_item": sum(1 for row in data if row.get("item_id") is None),
            "no_eb": sum(1 for row in data if row.get("eb_id") is None),
        }
        return {"data": data, "unsynced": unsynced}
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tran_date or machine_id")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/doff_entry_edit/{entry_id}")
def doff_entry_edit(
    entry_id: int,
    body: DoffEntryUpdate,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    co_id = _require_co_id(request)
    branch_id = _optional_branch_id(request)
    try:
        payload = body.model_dump(exclude_unset=True)
        existing = db.execute(
            text(
                """
                SELECT daily_doff_tbl_id, mc_id, trolly_id,
                       gross_weight, tare_weight, net_weight,
                       item_id, doff_date, spell, branch_id
                FROM daily_doff_tbl
                WHERE daily_doff_tbl_id = :id
                  AND (active = 1 OR active IS NULL)
                  AND (:branch_id IS NULL OR branch_id = :branch_id)
                """
            ),
            {"id": entry_id, "branch_id": branch_id},
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail=DOFF_NOT_FOUND_MSG)

        # 7.4: never trust the caller-supplied co_id — derive the effective co
        # (and branch, for the trolly scope check) from the entry's machine.
        mrow = _machine_branch_co(db, int(existing.mc_id))
        if not mrow or mrow.co_id is None or int(mrow.co_id) != co_id:
            raise HTTPException(status_code=404, detail=DOFF_NOT_FOUND_MSG)
        eff_co = int(mrow.co_id)

        # Legacy rows can carry a NULL spell; such a row can't belong to any
        # processed unit, so skip the lock gate (int(None) would 500).
        if existing.spell is not None:
            require_edit_if_locked(db, token_data, eff_co, existing.branch_id,
                                   existing.doff_date, int(existing.spell))

        user_id = token_data.get("user_id")
        sets = ["updated_by = :updated_by", "updated_date_time = NOW()"]
        params: Dict[str, Any] = {"id": entry_id, "updated_by": user_id}

        # 7.3: recompute tare/net ONLY when the payload touches the weights
        # (gross_weight or trolly_id). Item/eb-only edits keep the stored,
        # frozen-at-entry weights and skip validate_net.
        weights_touched = "gross_weight" in payload or "trolly_id" in payload
        if weights_touched:
            new_trolly = (
                int(body.trolly_id) if body.trolly_id is not None else int(existing.trolly_id)
            )
            new_gross = (
                float(body.gross_weight)
                if body.gross_weight is not None
                else _f(existing.gross_weight)
            )
            tare = _compute_doff_tare(
                db, eff_co, int(existing.mc_id), new_trolly, existing.doff_date,
                mrow.branch_id,
            )
            net = compute_net(new_gross, tare)
            if not validate_net(net):
                raise HTTPException(status_code=400, detail=DOFF_NET_RANGE_MSG)
            sets += [
                "trolly_id = :trolly_id",
                "gross_weight = :gross_weight",
                "tare_weight = :tare_weight",
                "net_weight = :net_weight",
            ]
            params.update(
                {"trolly_id": new_trolly, "gross_weight": new_gross,
                 "tare_weight": tare, "net_weight": net}
            )
        else:
            tare = _f(existing.tare_weight)
            net = _f(existing.net_weight)

        # Explicit identity edits stamp *_source='manual' — protected from every
        # sync/retro except retro_mode='all' (spec 5.2.5).
        if body.item_id is not None:
            sets += ["item_id = :item_id", "item_source = 'manual'"]
            params["item_id"] = int(body.item_id)
        if body.eb_id is not None:
            sets += ["eb_id = :eb_id", "eb_source = 'manual'"]
            params["eb_id"] = int(body.eb_id)

        db.execute(
            text(
                "UPDATE daily_doff_tbl SET " + ", ".join(sets)
                + " WHERE daily_doff_tbl_id = :id"
            ),
            params,
        )
        if existing.spell is not None:
            flag_reprocess_if_locked(db, eff_co, existing.doff_date, int(existing.spell))
        db.commit()
        return {"data": {"daily_doff_tbl_id": entry_id, "net_weight": net, "tare_weight": tare}}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/doff_entry_delete/{entry_id}")
def doff_entry_delete(
    entry_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    co_id = _require_co_id(request)
    branch_id = _optional_branch_id(request)
    try:
        existing = db.execute(
            text(
                """
                SELECT daily_doff_tbl_id, mc_id, doff_date, spell, branch_id
                FROM daily_doff_tbl
                WHERE daily_doff_tbl_id = :id
                  AND (active = 1 OR active IS NULL)
                  AND (:branch_id IS NULL OR branch_id = :branch_id)
                """
            ),
            {"id": entry_id, "branch_id": branch_id},
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail=DOFF_NOT_FOUND_MSG)

        # 7.4: derive the effective co from the entry's machine — a bogus co_id
        # must not bypass the lock gate.
        mrow = _machine_branch_co(db, int(existing.mc_id))
        if not mrow or mrow.co_id is None or int(mrow.co_id) != co_id:
            raise HTTPException(status_code=404, detail=DOFF_NOT_FOUND_MSG)
        eff_co = int(mrow.co_id)

        # Legacy NULL-spell rows can't belong to a processed unit -> skip the
        # lock gate/flag (int(None) would 500).
        if existing.spell is not None:
            require_edit_if_locked(db, token_data, eff_co, existing.branch_id,
                                   existing.doff_date, int(existing.spell))

        db.execute(
            text(
                "UPDATE daily_doff_tbl SET active = 0, updated_date_time = NOW() "
                "WHERE daily_doff_tbl_id = :id"
            ),
            {"id": entry_id},
        )
        if existing.spell is not None:
            flag_reprocess_if_locked(db, eff_co, existing.doff_date, int(existing.spell))
        db.commit()
        return {"data": {"message": "Deleted"}}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/doff_dedup_run")
def doff_dedup_run(
    body: DoffDedupRun,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        # DoffDedupRun carries no branch — spell_id is the branch-safe input;
        # the code fallback resolves unscoped (legacy behavior).
        spell_id = _resolve_spell(db, body.spell_id, body.spell, None)
        # W10 hardening: only EXACT duplicates (same mc/trolly/gross/tare) are
        # candidates, keeping the lowest id per group; legitimate multi-doff
        # rows are never touched. Co-scoped via the machine spine (D3c).
        dup_rows = db.execute(
            get_exact_duplicate_doff_ids_query(),
            {"tran_date": body.tran_date, "spell_id": spell_id,
             "co_id": int(body.co_id)},
        ).fetchall()
        candidates = [
            {
                "daily_doff_tbl_id": int(r.daily_doff_tbl_id),
                "mc_id": _i(r.mc_id),
                "keep_id": _i(r.keep_id),
                "gross_weight": _f(r.gross_weight),
                "tare_weight": _f(r.tare_weight),
                "net_weight": _f(r.net_weight),
            }
            for r in dup_rows
        ]
        # D8: confirm:false = preview — list the candidates, deactivate NOTHING.
        if not body.confirm:
            return {"data": {"preview": True, "candidates": candidates,
                             "deactivated": 0, "deactivated_ids": []}}
        require_edit_if_locked(db, token_data, body.co_id, None, body.tran_date, spell_id)
        ids = [c["daily_doff_tbl_id"] for c in candidates]
        if ids:
            db.execute(deactivate_doff_entries_query(), {"ids": ids})
            flag_reprocess_if_locked(db, body.co_id, body.tran_date, spell_id)
        db.commit()
        return {"data": {"preview": False, "deactivated": len(ids),
                         "deactivated_ids": ids}}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Stage 2 — Frame map (daily_doff_frames_winding, spg_wdg = 'S')
# =============================================================================


@router.get("/frame_map_get")
def frame_map_get(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    co_id = _require_co_id(request)
    branch_id = _optional_branch_id(request)
    d = request.query_params.get("tran_date")
    spell = request.query_params.get("spell") or None
    spell_id_param = _optional_spell_id_param(request)
    if not d or not (spell or spell_id_param):
        raise HTTPException(
            status_code=400, detail="tran_date and spell_id (or spell) are required"
        )
    try:
        d_val = date.fromisoformat(d)
        spell_id = _resolve_spell(db, spell_id_param, spell, branch_id)

        # Draft carry-forward (no auto-persist): the grid query surfaces each frame's
        # most recent saved S-mapping (any spell/date, excluding the current cell) as
        # prev_item_id/prev_item_name/prev_date so the client can prefill the dropdowns
        # and flag them unsaved — nothing is written until Save Map. This lets a
        # never-mapped spell (e.g. a new B1) bootstrap from the latest A1 setup.
        rows = db.execute(
            get_frame_map_query(),
            {
                "tran_date": d_val,
                "spell_id": spell_id,
                "spinning_type": SPINNING_MACHINE_TYPE_NAME,
                "branch_id": branch_id,
            },
        ).fetchall()
        data = []
        for r in rows:
            m = dict(r._mapping)
            prev_date = m.get("prev_date")
            data.append(
                {
                    "machine_id": m["machine_id"],
                    "mech_code": m["mech_code"],
                    "machine_name": m["machine_name"],
                    "item_id": m.get("item_id"),
                    "item_code": m.get("item_code"),
                    "item_name": m.get("item_name"),
                    "prev_item_id": m.get("prev_item_id"),
                    "prev_item_name": m.get("prev_item_name"),
                    "prev_date": str(prev_date) if prev_date is not None else None,
                }
            )

        # Branch's most-recent save timestamp (display-only).
        last_updated = db.execute(
            get_frame_map_last_updated_query(),
            {"branch_id": branch_id},
        ).scalar()

        return {
            "data": data,
            "last_updated": str(last_updated) if last_updated is not None else None,
        }
    except HTTPException:
        db.rollback()
        raise
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tran_date format")
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/frame_map_save")
def frame_map_save(
    body: FrameMapSave,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        spell_id = _resolve_spell(db, body.spell_id, body.spell, body.branch_id)
        require_edit_if_locked(db, token_data, body.co_id, body.branch_id, body.tran_date, spell_id)
        # The `spell` column stores the spell NAME — derived from the resolved
        # spell_id, never trusted from the client payload.
        spell_name = _spell_name(db, spell_id)
        user_id = token_data.get("user_id")
        saved = 0
        skipped = 0
        for e in body.entries:
            # Tolerate a machine set that changed since the grid loaded (a frame
            # added or removed): skip malformed ids instead of failing the save.
            try:
                machine_id = int(e.machine_id)
            except (TypeError, ValueError):
                skipped += 1
                continue
            if machine_id <= 0:
                skipped += 1
                continue

            existing = db.execute(
                get_frame_map_active_row_query(),
                {"tran_date": body.tran_date, "spell_id": spell_id, "machine_id": machine_id},
            ).fetchone()
            if existing:
                # Re-save of an already-saved frame: in-place UPDATE of the same
                # active row (no duplicate, no history) — refresh who/when stamps.
                db.execute(
                    update_frame_map_row_query(),
                    {
                        "id": existing.daily_doff_frm_wdg_id,
                        "item_id": e.item_id,
                        "updated_by": user_id,
                    },
                )
            else:
                db.execute(
                    insert_frame_map_row_query(),
                    {
                        "tran_date": body.tran_date,
                        "spell": spell_name,
                        "spell_id": spell_id,
                        "machine_id": machine_id,
                        "item_id": e.item_id,
                        "branch_id": body.branch_id,
                        "updated_by": user_id,
                    },
                )
            saved += 1
        flag_reprocess_if_locked(db, body.co_id, body.tran_date, spell_id)
        db.commit()
        return {"data": {"saved": saved, "skipped": skipped}}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Sync (spec 5.4) — quality from the mapper as-of, operator from attendance
# =============================================================================


def _run_doff_sync(
    db: Session,
    *,
    co_id: int,
    branch_id: Optional[int],
    tran_date,
    spell_id: int,
    mode: str = "fill",
    targets: Optional[List[str]] = None,
    ignore_designation: bool = False,
) -> Dict[str, Any]:
    """Core of POST /doff_sync (and the frame_map_mapped delegate).

    Stamps quality (mapper as-of) and operator (attendance cascade) onto the
    unit's doff rows, then collects the spec-5.4 exception report. Caller owns
    the lock gate, force-mode permission check, reprocess flag and commit.
    """
    targets = targets or ["quality", "operator"]
    force = 1 if mode == "force" else 0
    # co_id feeds the machine->dept->branch co spine inside _SYNC_SCOPE_WHERE
    # (D3b) — stamps/preview/summary never touch another company's rows.
    scope = {"tran_date": tran_date, "spell_id": int(spell_id),
             "branch_id": None if branch_id is None else int(branch_id),
             "co_id": int(co_id)}

    quality_stamped = 0
    item_overridden: List[Dict[str, Any]] = []
    if "quality" in targets:
        qp = dict(scope, spell_start=_spell_start(db, spell_id), force=force)
        if force:
            # Preview BEFORE the update — rows whose stamped item changes.
            for r in db.execute(get_sync_item_override_preview_query(), qp).fetchall():
                item_overridden.append(
                    {
                        "daily_doff_tbl_id": int(r.daily_doff_tbl_id),
                        "machine_id": int(r.mc_id),
                        "old_item_id": _i(r.old_item_id),
                        "new_item_id": _i(r.new_item_id),
                    }
                )
        q_res = db.execute(sync_quality_stamp_query(), qp)
        quality_stamped = int(q_res.rowcount or 0)

    operator_stamped = 0
    ambiguous: List[Dict[str, Any]] = []
    by_mc: Dict[int, List[tuple]] = {}  # kept for the W7 collector below
    if "operator" in targets:
        cand_rows = db.execute(
            get_operator_candidates_query(),
            {"tran_date": tran_date, "spell_id": int(spell_id),
             "branch_id": scope["branch_id"],
             "ignore_designation": 1 if ignore_designation else 0,
             "desig_prefix": SPINNER_DESIG_PREFIX},
        ).fetchall()
        # Cascade (spec 5.4): the spinner-designation gate runs in SQL now; what
        # is left here is the lowest daily_atten_id tie-break (first-marked,
        # deterministic). On sls the gate alone resolves every doffed frame to
        # exactly one eb, so the tie-break is a safety net, not the mechanism —
        # and any tie it does resolve is ALSO reported as operator_ambiguous
        # below, because marking order is arbitrary between two real spinners.
        for r in cand_rows:
            by_mc.setdefault(int(r.mc_id), []).append(
                (int(r.daily_atten_id), int(r.eb_id))
            )
        for mc_id, cands in by_mc.items():
            _, chosen_eb = min(cands)
            eb_ids = sorted({eb for _, eb in cands})
            if len(eb_ids) > 1:
                # W4: ALWAYS reported when >1 candidate, regardless of how
                # the cascade resolved — visible, never a silent guess.
                ambiguous.append(
                    {"machine_id": mc_id, "eb_ids": eb_ids,
                     "stamped_eb_id": chosen_eb}
                )
            o_res = db.execute(
                stamp_operator_query(),
                dict(scope, mc_id=mc_id, eb_id=chosen_eb, force=force),
            )
            operator_stamped += int(o_res.rowcount or 0)

    # Exception report over the unit's post-sync state.
    scope_rows = db.execute(get_sync_scope_summary_query(), scope).fetchall()
    scope_mcs = {int(r.mc_id) for r in scope_rows}
    machines_unmapped = sorted(
        int(r.mc_id) for r in scope_rows if int(r.null_item_rows or 0) > 0
    )
    doffs_no_operator = sum(int(r.null_eb_rows or 0) for r in scope_rows)
    # Ambiguity only matters for machines that actually have doffs in the unit.
    operator_ambiguous = [a for a in ambiguous if a["machine_id"] in scope_mcs]

    # W7 (D6): machines with an active on-machine attendance candidate but ZERO
    # active doff rows in the unit — someone was marked on the frame, nothing
    # was weighed. Only computable when the operator target ran (by_mc empty
    # otherwise).
    attendance_no_doffs: List[Dict[str, Any]] = []
    missing_mcs = sorted(set(by_mc) - scope_mcs)
    if missing_mcs:
        mech = {
            int(r.machine_id): r.mech_code
            for r in db.execute(
                get_machine_codes_query(), {"ids": missing_mcs}
            ).fetchall()
        }
        for mc_id in missing_mcs:
            attendance_no_doffs.append(
                {
                    "machine_id": mc_id,
                    "mech_code": mech.get(mc_id),
                    "eb_ids": sorted({eb for _, eb in by_mc[mc_id]}),
                }
            )

    bobbin_by_mc = {
        int(r.machine_id): _f(r.bobbin_weight)
        for r in db.execute(
            get_machine_bobbin_batch_query(),
            {"co_id": int(co_id), "on_date": tran_date},
        ).fetchall()
    }
    bobbin_missing = sorted(
        mc for mc in scope_mcs if bobbin_by_mc.get(mc, 0.0) <= 0
    )

    return {
        "quality_stamped": quality_stamped,
        "operator_stamped": operator_stamped,
        "exceptions": {
            "machines_unmapped": machines_unmapped,
            "doffs_no_operator": doffs_no_operator,
            "operator_ambiguous": operator_ambiguous,
            "item_overridden": item_overridden,
            "bobbin_missing": bobbin_missing,
            "attendance_no_doffs": attendance_no_doffs,
        },
    }


@router.post("/doff_sync")
def doff_sync(
    body: DoffSync,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        if body.mode not in ("fill", "force"):
            raise HTTPException(status_code=400, detail="mode must be 'fill' or 'force'")
        targets = [t for t in body.targets if t in ("quality", "operator")]
        if not targets:
            raise HTTPException(
                status_code=400, detail="targets must include 'quality' and/or 'operator'"
            )
        spell_id = _resolve_spell(db, body.spell_id, body.spell, body.branch_id)
        require_edit_if_locked(
            db, token_data, body.co_id, body.branch_id, body.tran_date, spell_id
        )
        if body.mode == "force":
            # B6: force overwrites synced stamps — Edit level required.
            level = user_menu_access_level(
                db, token_data.get("user_id"), body.co_id, body.branch_id,
                SPINNING_MENU_PATH,
            )
            if level < EDIT_LEVEL:
                raise HTTPException(status_code=403, detail=SYNC_FORCE_EDIT_MSG)

        result = _run_doff_sync(
            db,
            co_id=body.co_id,
            branch_id=body.branch_id,
            tran_date=body.tran_date,
            spell_id=spell_id,
            mode=body.mode,
            targets=targets,
            ignore_designation=body.ignore_designation,
        )
        flag_reprocess_if_locked(db, body.co_id, body.tran_date, spell_id)
        db.commit()
        return {"data": result}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/frame_map_mapped")
def frame_map_mapped(
    body: FrameMapMapped,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Legacy 'Mapped' button — thin delegate over the doff_sync internals
    (fill mode, both targets) kept for one release. Response keeps the
    quality_stamped / operator_stamped keys for FE compatibility."""
    try:
        spell_id = _resolve_spell(db, body.spell_id, body.spell, body.branch_id)
        require_edit_if_locked(db, token_data, body.co_id, body.branch_id, body.tran_date, spell_id)
        result = _run_doff_sync(
            db,
            co_id=body.co_id,
            branch_id=body.branch_id,
            tran_date=body.tran_date,
            spell_id=spell_id,
            mode="fill",
            targets=["quality", "operator"],
        )
        flag_reprocess_if_locked(db, body.co_id, body.tran_date, spell_id)
        db.commit()
        return {
            "data": {
                "quality_stamped": result["quality_stamped"],
                "operator_stamped": result["operator_stamped"],
                "exceptions": result["exceptions"],
            }
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/doff_editor_setup")
def doff_editor_setup(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Setup for the Doff Data Editor page (spec 5.8): yarn dropdown (same shape
    as doff_entry_create_setup) + active branch workers for the operator picker."""
    co_id = _require_co_id(request)
    branch_id = _optional_branch_id(request)
    try:
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

        # worker_name arrives pre-concatenated ('E1234 - Ramesh Das') — the
        # picker renders it as-is, no client-side reassembly.
        workers = [
            {
                "eb_id": int(r.eb_id),
                "worker_name": r.worker_name,
            }
            for r in db.execute(
                get_active_workers_query(), {"branch_id": branch_id}
            ).fetchall()
        ]

        return {"data": {"yarn_items": yarn_items, "workers": workers}}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Planning grid (jute_prod_spinning_daily) — per-frame-per-spell snapshot
# =============================================================================


def _shift_bucket(spell_code: Optional[str]) -> str:
    """Shift bucket = leading char of spell_code (A1/A2->A, B1/B2->B, C->C)."""
    return (spell_code or "")[:1].upper()


@router.get("/planning_grid")
def planning_grid(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Per-frame-per-spell planning grid for a tran_date (optional spell).

    Source-agnostic read: a Processed+locked (co, branch, date, spell) unit serves
    its frozen jute_prod_spinning_daily rows; otherwise ONE execution of the
    day-slice computes the grid live (no per-row resolvers, no view reads).
    Spell-less calls always serve the live slice — the lock switch needs the spell."""
    co_id = _require_co_id(request)
    branch_id = _optional_branch_id(request)
    d = request.query_params.get("tran_date")
    if not d:
        raise HTTPException(status_code=400, detail="tran_date is required")
    spell = request.query_params.get("spell") or None
    try:
        d_val = date.fromisoformat(d)
        spell_id_param = _optional_spell_id_param(request)
        spell_id = (
            _resolve_spell(db, spell_id_param, spell, branch_id)
            if (spell_id_param is not None or spell)
            else None
        )

        locked = False
        reprocess_needed = False
        if spell_id is not None:
            lock = get_process_lock(db, co_id, branch_id, d_val, spell_id)
            locked = bool(lock and lock.is_locked)
            reprocess_needed = bool(lock and lock.reprocess_needed)

        if locked:
            raw = db.execute(
                get_spinning_log_rows_query(),
                {"co_id": co_id, "tran_date": d_val, "spell_id": spell_id,
                 "branch_id": branch_id},
            ).fetchall()
        else:
            raw = db.execute(
                get_spinning_planning_slice_query(),
                {"co_id": co_id, "tran_date": d_val, "spell_id": spell_id,
                 "branch_id": branch_id,
                 "spinning_type": SPINNING_MACHINE_TYPE_NAME},
            ).fetchall()

        rows: List[Dict[str, Any]] = []
        for r in raw:
            m = dict(r._mapping)
            rows.append(
                {
                    "spell_id": _i(m.get("spell_id")),
                    "spell_code": m.get("spell_code"),
                    "shift_bucket": m.get("shift_bucket") or _shift_bucket(m.get("spell_code")),
                    "machine_id": _i(m.get("machine_id")),
                    "mech_code": m.get("mech_code"),
                    "machine_name": m.get("machine_name"),
                    "branch_id": m.get("branch_id"),
                    "item_id": _i(m.get("item_id")),
                    "item_code": m.get("item_code"),
                    "item_name": m.get("item_name"),
                    "spindles": int(m.get("spindles") or 0),
                    "minutes": int(m.get("minutes") or 0),
                    "act_count": _f(m.get("act_count")),
                    "std_count": _f(m.get("std_count")),
                    "std_speed": _f(m.get("std_speed")),
                    "actual_speed": _f(m.get("actual_speed")),
                    "target_speed": _f(m.get("target_speed")),
                    "std_tpi": _f(m.get("std_tpi")),
                    "actual_tpi": _f(m.get("actual_tpi")),
                    "target_tpi": _f(m.get("target_tpi")),
                    "std_eff": _f(m.get("std_eff")),
                    "target_eff": _f(m.get("target_eff")),
                    "p100prod": _f(m.get("p100prod")),
                    "std_prod": _f(m.get("std_prod")),
                    "target_prod": _f(m.get("target_prod")),
                    "act_prod_doff": _f(m.get("act_prod_doff")),
                    "winding_total": _f(m.get("winding_total")),
                    "act_prod_wind": _f(m.get("act_prod_wind")),
                    "eff_doff": _f(m.get("eff_doff")),
                    "eff_winding": _f(m.get("eff_winding")),
                }
            )

        # Shift rollup per (machine, yarn item, shift_bucket): SUM(num)/SUM(denom) —
        # unchanged from the pre-slice implementation.
        roll: Dict[tuple, Dict[str, Any]] = {}
        for row in rows:
            key = (row["machine_id"], row["item_id"], row["shift_bucket"])
            agg = roll.setdefault(
                key,
                {
                    "machine_id": row["machine_id"],
                    "mech_code": row.get("mech_code"),
                    "machine_name": row.get("machine_name"),
                    "item_id": row["item_id"],
                    "item_code": row.get("item_code"),
                    "shift_bucket": row["shift_bucket"],
                    "prod_doff": 0.0,
                    "prod_wind": 0.0,
                    "_p100": 0.0,
                },
            )
            agg["prod_doff"] += row["act_prod_doff"]
            agg["prod_wind"] += row["act_prod_wind"]
            agg["_p100"] += row["p100prod"]

        shift_rollup = []
        for agg in roll.values():
            p100 = agg.pop("_p100")
            agg["prod_doff"] = round(agg["prod_doff"], 3)
            agg["prod_wind"] = round(agg["prod_wind"], 3)
            agg["doff_eff"] = round(agg["prod_doff"] / p100 * 100, 2) if p100 else 0.0
            agg["wind_eff"] = round(agg["prod_wind"] / p100 * 100, 2) if p100 else 0.0
            shift_rollup.append(agg)

        return {"data": {"rows": rows, "shift_rollup": shift_rollup,
                         "locked": locked, "reprocess_needed": reprocess_needed}}
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tran_date format")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
