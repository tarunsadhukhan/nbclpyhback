"""Weaving Production Entry endpoints (Page C, prefix /api/weavingProd).

Daily per-loom/per-quality production entry. STORAGE MODEL = FREEZE NOTHING + day-slice
(2026-06-24, revised Phase 1b 2026-07-07): jute_prod_weaving_daily stores INPUTS
(cuts, close_jugar, less_production + identity) PLUS the stored ``open_jugar``
carry-forward; every other derived/standard/computed column is recomputed on read by
the day-slice SQL (oracle: ``vw_weaving_daily``). open_jugar is resolved at WRITE time:
every mutation of a daily row (entry_create / entry_edit / planning_grid_save /
adjustment_save insert path / entry_delete) re-resolves the row's own open_jugar from
its chain predecessor and repairs the SINGLE chain successor in the same transaction
(_sync_jugar_chain_after_write) — bounded at 2-3 indexed statements per write, no
cascade beyond the immediate successor (rows further down depend on the successor's
own close_jugar, which never changes here). ``entry_create``/``entry_edit`` persist
inputs after validating the quality is mapped and
0 <= close_jugar <= no_of_jugar_per_cut; ``entries_by_date``/``planning_grid`` compute
via the day-slice.

Portal persona (get_tenant_db + get_current_user_with_refresh, {"data": ...} responses,
soft delete via active=0, no approval workflow, trigger-based audit — no created_*), with
the Loom->Quality map endpoints (quality_map_get/save/mapped) and the Beam-change map
endpoints (beam_map_get/save).

QUALITY IS MAPPED, NOT SELECTED INLINE: the entry/plan grain is
(tran_date, spell_id, machine_id) and the weaving_quality_id is INHERITED from the active
jute_prod_weaving_quality_map (one active row per loom/spell/date), never sent in the entry
body. The stored daily.weaving_quality_id is authoritative on read (NO map coalesce in the
day-slice); quality_map_save re-stamps the cell's daily rows when the mapping changes.
On create/edit the server
resolves: weaving_quality_id (from the §6.6 map), beam_no (latest §6.7 beam map), eb_id
(left NULL — attendance view, Q7), branch_id/co_id (machine -> dept -> branch -> company).

Upsert app-uniqueness: (co_id, tran_date, spell_id, machine_id, weaving_quality_id,
active=1) — an existing active row is updated, otherwise a fresh one is inserted.
"""

from datetime import date
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.authorization.utils import get_current_user_with_refresh
from src.config.db import get_tenant_db
from src.juteProduction.constants import WEAVING_MACHINE_TYPE_NAME
from src.juteProduction.weaving_query import (
    get_weaving_adjustment_grid_query,
    get_weaving_beam_map_active_row_query,
    get_weaving_beam_map_query,
    get_weaving_chain_successor_query,
    get_weaving_daily_active_row_query,
    get_weaving_eb_list_query,
    get_weaving_entries_by_date_query,
    get_weaving_entry_inputs_query,
    get_weaving_entry_machines_query,
    get_weaving_latest_beam_no_query,
    get_weaving_plan_driver_query,
    get_weaving_quality_list_query,
    get_weaving_quality_map_active_row_query,
    get_weaving_quality_map_last_updated_query,
    get_weaving_quality_map_mapped_query,
    get_weaving_quality_map_query,
    get_weaving_quality_map_saved_query,
    get_weaving_daily_rows_to_restamp_query,
    get_weaving_spells_query,
    insert_weaving_beam_map_row_query,
    insert_weaving_daily_query,
    insert_weaving_quality_map_row_query,
    resolve_weaving_open_jugar_for_row_query,
    soft_delete_weaving_daily_query,
    update_weaving_beam_map_row_query,
    update_weaving_daily_less_production_query,
    update_weaving_daily_open_jugar_query,
    update_weaving_daily_quality_stamp_query,
    update_weaving_daily_query,
    update_weaving_quality_map_row_query,
    upsert_weaving_current_quality_query,
    get_weaving_daily_active_row_by_machine_query,
    get_weaving_log_rows_query,
)
from src.juteProduction.services.weaving_standards import (
    net_working_hours,
    resolve_quality_standards,
)
# Shared spell-resolution contract (spell_id preferred, branch-scoped code fallback) —
# import, do NOT copy. See spinning_entry._resolve_spell.
from src.juteProduction.spinning_entry import _resolve_spell, _optional_spell_id_param
from src.juteProduction.weaving_lock import (
    require_edit_if_locked,
    is_unit_locked,
    flag_reprocess_if_locked,
)


router = APIRouter()

QUALITY_NOT_FOUND_MSG = "Weaving quality not found"
NO_MAPPED_QUALITY_MSG = (
    "No quality mapped for this loom/spell/date in jute_prod_weaving_quality_map; "
    "assign a quality on the Loom->Quality map before entering production."
)
ENTRY_NOT_FOUND_MSG = "Weaving entry not found"
SPELL_REQUIRED_MSG = "tran_date and spell_id (or spell) are required"


def _close_jugar_range_msg(jc: float) -> str:
    return f"close_jugar must be between 0 and no_of_jugar_per_cut ({jc})"


# =============================================================================
# Pydantic models — INPUTS ONLY (no computed columns; the view derives everything)
# =============================================================================


class WeavingEntryCreate(BaseModel):
    """One loom production entry — INPUTS ONLY. Quality is INHERITED from the map.

    weaving_quality_id is intentionally NOT here: it is resolved server-side from the
    active jute_prod_weaving_quality_map for (tran_date, spell_id, machine_id). beam_no /
    eb_id are likewise resolved server-side. ``close_jugar`` is the operator's closing-
    jugar reading (validated 0 <= cj <= no_of_jugar_per_cut). Nothing computed is sent.
    """

    co_id: Optional[int] = None  # derived from the machine's branch when omitted
    branch_id: Optional[int] = None  # derived from machine on insert
    tran_date: date
    spell_id: Optional[int] = None  # preferred — validated against the branch's shifts
    spell: Optional[str] = None  # DEPRECATED spell CODE fallback (branch-scoped)
    machine_id: int
    cuts: int = Field(ge=0)  # whole cuts only — INT column (no silent truncation)
    close_jugar: float = Field(ge=0)
    # None => preserve the row's existing less_production (the adjustment value). The entry
    # tab never sends this, so defaulting to 0.0 would ZERO any adjustment on every re-save.
    less_production: Optional[float] = Field(default=None, ge=0)


class WeavingEntryUpdate(BaseModel):
    """Edit one entry's inputs — any omitted field keeps its existing value."""

    spell_id: Optional[int] = None  # preferred — validated against the row's branch
    spell: Optional[str] = None  # DEPRECATED spell CODE fallback (branch-scoped)
    machine_id: Optional[int] = None
    cuts: Optional[int] = Field(default=None, ge=0)  # whole cuts only — INT column
    close_jugar: Optional[float] = Field(default=None, ge=0)
    less_production: Optional[float] = Field(default=None, ge=0)


class PlanningGridRow(BaseModel):
    """One per-loom/per-quality planning row to persist into jute_prod_weaving_daily.

    INPUTS ONLY: identity (spell/machine) + the genuine entry inputs (cuts, close_jugar,
    less_production). weaving_quality_id is accepted for backward-compat but the server
    re-derives it from the quality map (driver source). No computed/standard fields are
    accepted — the view derives everything on read.
    """

    spell_id: Optional[int] = None  # preferred — validated against the row's branch
    spell: Optional[str] = None  # DEPRECATED spell CODE fallback (branch-scoped)
    machine_id: int
    weaving_quality_id: Optional[int] = None
    cuts: int = Field(default=0, ge=0)  # whole cuts only — INT column (no silent truncation)
    close_jugar: float = Field(default=0.0, ge=0)
    less_production: float = Field(default=0.0, ge=0)
    eb_id: Optional[int] = None
    beam_no: Optional[str] = None


class PlanningGridSave(BaseModel):
    co_id: Optional[int] = None  # derived from branch when omitted
    branch_id: Optional[int] = None
    tran_date: date
    rows: List[PlanningGridRow] = Field(default_factory=list)


class QualityMapEntry(BaseModel):
    machine_id: int
    weaving_quality_id: Optional[int] = None


class QualityMapSave(BaseModel):
    co_id: Optional[int] = None  # derived from branch when omitted
    branch_id: Optional[int] = None
    tran_date: date
    spell_id: Optional[int] = None  # preferred — validated against the branch's shifts
    spell: Optional[str] = None  # DEPRECATED spell CODE fallback (branch-scoped)
    entries: List[QualityMapEntry] = Field(default_factory=list)


class QualityMapMapped(BaseModel):
    co_id: Optional[int] = None  # derived from branch when omitted
    branch_id: Optional[int] = None
    tran_date: date
    spell_id: Optional[int] = None  # preferred; neither -> widen to the whole date
    spell: Optional[str] = None  # DEPRECATED spell CODE fallback (branch-scoped)
    machine_id: Optional[int] = None


class BeamMapEntry(BaseModel):
    machine_id: int
    beam_no: Optional[str] = None


class BeamMapSave(BaseModel):
    co_id: Optional[int] = None  # derived from branch when omitted
    branch_id: Optional[int] = None
    tran_date: date
    spell_id: Optional[int] = None  # preferred — validated against the branch's shifts
    spell: Optional[str] = None  # DEPRECATED spell CODE fallback (branch-scoped)
    entries: List[BeamMapEntry] = Field(default_factory=list)


class AdjustmentEntry(BaseModel):
    machine_id: int
    less_production: float = Field(ge=0)


class AdjustmentSave(BaseModel):
    co_id: Optional[int] = None  # derived from branch when omitted
    branch_id: Optional[int] = None
    tran_date: date
    spell_id: Optional[int] = None  # preferred — validated against the branch's shifts
    spell: Optional[str] = None  # DEPRECATED spell CODE fallback (branch-scoped)
    entries: List[AdjustmentEntry] = Field(default_factory=list)


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


def _resolve_optional_spell(
    db: Session,
    spell_id: Optional[int],
    spell_code: Optional[str],
    branch_id: Optional[int],
) -> Optional[int]:
    """Optional-spell reads: neither spell_id nor spell -> None (widen to the whole
    date). Either given -> the shared spinning_entry._resolve_spell contract:
    spell_id preferred (validated to exist, status=1, and belong to the branch's
    shift), spell CODE as deprecated branch-scoped fallback (NO global fallback —
    spell codes repeat per branch, dev3 branch-12 'C' = 8 vs branch-2 'C' = 5)."""
    if spell_id is None and not spell_code:
        return None
    return _resolve_spell(db, spell_id, spell_code, branch_id)


def _f(v, default: float = 0.0) -> float:
    """Cast a possibly-None / Decimal value to float."""
    return default if v is None else float(v)


def _i(v, default: Optional[int] = None) -> Optional[int]:
    return default if v is None else int(v)


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


def _derive_co_id(db: Session, branch_id: Optional[int]) -> Optional[int]:
    """Company for a branch (branch_mst.co_id). branch_id pins the company."""
    if branch_id is None:
        return None
    row = db.execute(
        text("SELECT co_id FROM branch_mst WHERE branch_id = :branch_id"),
        {"branch_id": int(branch_id)},
    ).fetchone()
    return _i(row.co_id) if row else None


def _mapped_quality_id(
    db: Session, co_id: int, tran_date, spell_id: int, machine_id: int
) -> Optional[int]:
    """The weaving_quality_id mapped to this loom/spell/date (active map row).

    Production quality is inherited from jute_prod_weaving_quality_map, NOT entered
    inline. Returns None when no active mapping exists.
    """
    row = db.execute(
        text(
            """
            SELECT weaving_quality_id
            FROM jute_prod_weaving_quality_map
            WHERE co_id = :co_id
              AND tran_date = :tran_date
              AND spell_id = :spell_id
              AND machine_id = :machine_id
              AND active = 1
              AND weaving_quality_id IS NOT NULL
            ORDER BY weaving_quality_map_id DESC
            LIMIT 1
            """
        ),
        {
            "co_id": int(co_id),
            "tran_date": tran_date,
            "spell_id": int(spell_id),
            "machine_id": int(machine_id),
        },
    ).fetchone()
    return _i(row.weaving_quality_id) if row else None


def _fetch_quality(db: Session, co_id: int, weaving_quality_id: int):
    """Active jute_prod_weaving_quality row (Page A) — for the close_jugar range check.

    Scoped by co_id so a quality from another company can't be referenced. Returns the
    SQLAlchemy row (construction attrs incl. no_of_jugar_per_cut) or None.
    """
    return db.execute(
        text(
            """
            SELECT weaving_quality_id, item_id, ends, finished_length, ozs_yds,
                   std_ozs_yds, no_of_jugar_per_cut, is_composite
            FROM jute_prod_weaving_quality
            WHERE weaving_quality_id = :weaving_quality_id
              AND co_id = :co_id
              AND active = 1
            """
        ),
        {"weaving_quality_id": int(weaving_quality_id), "co_id": int(co_id)},
    ).fetchone()


def _validate_close_jugar(close_jugar: float, quality) -> None:
    """Enforce 0 <= close_jugar <= no_of_jugar_per_cut (REJECT cj > jc at write time).

    ``quality`` is the _fetch_quality row. 404 when missing; 400 when cj out of range.
    """
    if not quality:
        raise HTTPException(status_code=404, detail=QUALITY_NOT_FOUND_MSG)
    jc = _f(quality.no_of_jugar_per_cut)
    cj = _f(close_jugar)
    if cj < 0 or (jc > 0 and cj > jc):
        raise HTTPException(status_code=400, detail=_close_jugar_range_msg(jc))


def _input_params(
    co_id: int,
    branch_id: Optional[int],
    tran_date,
    spell_id: int,
    machine_id: int,
    weaving_quality_id: int,
    eb_id: Optional[int],
    beam_no: Optional[str],
    cuts: int,
    close_jugar: float,
    less_production: float,
    user_id,
) -> Dict[str, Any]:
    """Flat bind dict for insert_weaving_daily_query / update_weaving_daily_query.

    INPUTS ONLY (FREEZE NOTHING + VIEW): identity + cuts/close_jugar/less_production. No
    open_jugar/jugar/standards/computed columns — the view derives them on read.
    """
    return {
        "co_id": int(co_id),
        "branch_id": _i(branch_id),
        "tran_date": tran_date,
        "spell_id": int(spell_id),
        "machine_id": int(machine_id),
        "weaving_quality_id": _i(weaving_quality_id),
        "eb_id": _i(eb_id),
        "beam_no": beam_no if beam_no else None,
        "cuts": _i(cuts, 0),  # INT column — cast via _i(), never _f() (no truncation)
        "close_jugar": _f(close_jugar),
        "less_production": _f(less_production),
        "updated_by": user_id,
    }


def _resync_open_jugar_row(db: Session, row_id: int) -> None:
    """Recompute + store ONE row's open_jugar from its chain predecessor.

    Phase 1b: open_jugar is a STORED column, resolved at write time. This runs the
    shared two-probe predecessor expression (same semantics as the oracle view's
    LAG carry-forward) against the row's stored identity and persists the result.
    One indexed SELECT + one UPDATE; no-op when the row id vanished.
    """
    resolved = db.execute(
        resolve_weaving_open_jugar_for_row_query(), {"row_id": int(row_id)}
    ).fetchone()
    if resolved is None:
        return
    db.execute(
        update_weaving_daily_open_jugar_query(),
        {"row_id": int(row_id), "open_jugar": _f(resolved.open_jugar)},
    )


def _resync_chain_successor(
    db: Session,
    co_id: int,
    machine_id: int,
    weaving_quality_id: int,
    tran_date,
    spell_id: int,
    row_id: int,
) -> Optional[int]:
    """Repair the SINGLE chain successor of one (co, machine, quality) position.

    The immediate successor's open_jugar equals this position's close_jugar (LAG
    semantics), so after any insert/edit/soft-delete at the position, exactly one
    row downstream needs recomputing — rows past the successor depend on the
    successor's own close_jugar and are untouched. Identity is passed explicitly
    so an identity-changing edit can also repair its OLD position's successor.
    Returns the successor row id (or None) so callers can flag its unit for
    reprocess without re-running the lookup.
    """
    successor_id = db.execute(
        get_weaving_chain_successor_query(),
        {
            "co_id": int(co_id),
            "machine_id": int(machine_id),
            "weaving_quality_id": int(weaving_quality_id),
            "tran_date": tran_date,
            "spell_id": int(spell_id),
            "row_id": int(row_id),
        },
    ).scalar()
    if successor_id is not None:
        _resync_open_jugar_row(db, int(successor_id))
        return int(successor_id)
    return None


def _sync_jugar_chain_after_write(
    db: Session,
    row_id: int,
    co_id: int,
    machine_id: int,
    weaving_quality_id: int,
    tran_date,
    spell_id: int,
) -> Optional[int]:
    """Post-write chain sync: the row's own open_jugar + its single successor.

    Returns the successor row id (or None) for the caller's reprocess flagging."""
    _resync_open_jugar_row(db, row_id)
    return _resync_chain_successor(
        db, co_id, machine_id, weaving_quality_id, tran_date, spell_id, row_id
    )


def _flag_reprocess_units(
    db: Session, co_id, tran_date, spell_id, successor_id: Optional[int] = None,
    seen: Optional[set] = None,
) -> None:
    """Spec §7: an Edit-user mutation of a locked unit invalidates its frozen snapshot
    (and its immediate chain successor's, whose stored open_jugar just shifted). Flag
    reprocess_needed on BOTH units when they are locked. No-op on unlocked units.
    successor_id is the id already returned by the chain resync — no extra lookup.
    ``seen`` (batch callers): units already flagged this request are skipped — the
    flag UPDATE is idempotent, so once per unit is identical to once per row."""

    def _flag(c, d, s):
        key = (c, str(d), _i(s))
        if seen is not None and key in seen:
            return
        flag_reprocess_if_locked(db, c, d, s)
        if seen is not None:
            seen.add(key)

    _flag(co_id, tran_date, spell_id)
    if successor_id is None:
        return
    su = db.execute(
        text(
            "SELECT co_id, tran_date, spell_id FROM jute_prod_weaving_daily "
            "WHERE weaving_daily_id = :id"
        ),
        {"id": int(successor_id)},
    ).fetchone()
    if su and (str(su.tran_date), int(su.spell_id)) != (str(tran_date), int(spell_id)):
        _flag(su.co_id, su.tran_date, su.spell_id)


def _lock_co_for_batch(db: Session, co_id, branch_id, entries):
    """co_id for a batch endpoint's lock gate: body co_id, else branch, else the
    first well-formed entry's machine. Fail closed — a body omitting BOTH co_id
    and branch_id must not skip the locked-unit gate (the per-row loop still
    derives a co_id from each machine and would otherwise mutate the locked unit)."""
    lock_co = co_id if co_id is not None else _derive_co_id(db, branch_id)
    if lock_co is None:
        for e in entries:
            try:
                machine_id = int(e.machine_id)
            except (TypeError, ValueError):
                continue
            lock_co = _derive_co_id(db, _derive_branch_id(db, machine_id))
            break
    return lock_co


def _serialize_entry_row(row) -> Dict[str, Any]:
    """dict(_mapping) with Decimal -> float and date -> str for JSON safety.

    Columns come from vw_weaving_daily (inputs + every derived column).
    """
    m = dict(row._mapping)
    float_cols = (
        "cuts", "close_jugar", "less_production", "open_jugar", "jugar",
        "jpc", "fl",  # entry_inputs_by_date aliases (FE preview field names)
        "finished_length", "ozs_yds", "std_ozs_yds", "no_of_jugar_per_cut",
        "std_speed", "act_speed", "std_picks", "act_picks", "std_eff", "target_eff",
        "eff_speed", "eff_picks", "working_hours",
        "production_yds", "production_kg", "production_mt",
        "std_prod_yds", "target_prod_yds", "efficiency", "std_prod_kg", "target_kg",
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


@router.get("/entry_create_setup")
def entry_create_setup(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Lookups for the weaving tabs: Loom machines, spells, eb list, qualities.

    The production grid does NOT pick quality inline — it is inherited from the
    Loom->Quality map. The Loom->Quality MAP tab is where the operator assigns a quality
    to each loom, so the active weaving qualities (jute_prod_weaving_quality, Page A) are
    returned here to populate that dropdown. Keys mirror the FE WeavingQualityOption.
    """
    co_id = _require_co_id(request)
    branch_id = _optional_branch_id(request)
    try:
        machines = [
            dict(r._mapping)
            for r in db.execute(
                get_weaving_entry_machines_query(),
                {"loom_type": WEAVING_MACHINE_TYPE_NAME, "branch_id": branch_id},
            ).fetchall()
        ]

        # spell_mst filters status = 1; de-dup by spell_code (branch fanout).
        spells = []
        seen = set()
        for r in db.execute(get_weaving_spells_query(), {"branch_id": branch_id}).fetchall():
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

        eb = [
            dict(r._mapping)
            for r in db.execute(get_weaving_eb_list_query(), {"branch_id": branch_id}).fetchall()
        ]

        # Active weaving qualities for the Loom->Quality map dropdown (Page A master).
        qualities = []
        for r in db.execute(
            get_weaving_quality_list_query(),
            {"co_id": co_id, "item_id": None, "branch_id": branch_id, "search": None},
        ).fetchall():
            m = dict(r._mapping)
            qualities.append(
                {
                    "weaving_quality_id": int(m["weaving_quality_id"]),
                    "item_id": _i(m.get("item_id")),
                    "weaving_quality_code": m.get("weaving_quality_code"),
                    "weaving_quality_name": m.get("weaving_quality_name"),
                }
            )

        return {
            "data": {
                "machines": machines,
                "spells": spells,
                "eb_list": eb,
                "qualities": qualities,
            }
        }
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
    """Weaving-daily entries for a tran_date — FULL computed row set (day-slice).

    Every derived column (open_jugar, jugar, production_*, std_*, efficiency, ...)
    is computed on read by the day-slice query (vw_weaving_daily is reference/oracle
    only). For the entry grid, prefer /entry_inputs_by_date — same rows, no
    standards/pick/stoppage probes.
    """
    co_id = _require_co_id(request)
    branch_id = _optional_branch_id(request)
    d = request.query_params.get("tran_date")
    if not d:
        raise HTTPException(status_code=400, detail="tran_date is required")
    spell_raw = request.query_params.get("spell")
    spell_id_param = _optional_spell_id_param(request)
    machine_raw = request.query_params.get("machine_id")
    try:
        d_val = date.fromisoformat(d)
        spell_id = _resolve_optional_spell(db, spell_id_param, spell_raw, branch_id)
        machine_id = int(machine_raw) if machine_raw else None
        # Locked units serve the frozen log; unlocked units recompute live (day-slice).
        if spell_id is not None and is_unit_locked(db, co_id, branch_id, d_val, spell_id):
            rows = db.execute(
                get_weaving_log_rows_query(),
                {
                    "co_id": co_id,
                    "tran_date": d_val,
                    "spell_id": spell_id,
                    "machine_id": machine_id,
                    "branch_id": branch_id,
                },
            ).fetchall()
        else:
            rows = db.execute(
                get_weaving_entries_by_date_query(),
                {
                    "co_id": co_id,
                    "tran_date": d_val,
                    "spell_id": spell_id,
                    "machine_id": machine_id,
                    "branch_id": branch_id,
                },
            ).fetchall()
        return {"data": [_serialize_entry_row(r) for r in rows]}
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tran_date or machine_id")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/entry_inputs_by_date")
def entry_inputs_by_date(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Entry-tab day rows straight from jute_prod_weaving_daily (LIGHT read).

    Returns the stored inputs (cuts, close_jugar, less_production) + open_jugar
    (jugar-chain probe) + the mapped quality's jpc/fl/ozs_yds — everything the
    Production Entry grid needs to prefill and preview total_jugar, with none of
    the standards / pick-SQC / stoppage probes the full /entries_by_date pays.
    Same params and response envelope as /entries_by_date.
    """
    co_id = _require_co_id(request)
    branch_id = _optional_branch_id(request)
    d = request.query_params.get("tran_date")
    if not d:
        raise HTTPException(status_code=400, detail="tran_date is required")
    spell_raw = request.query_params.get("spell")
    spell_id_param = _optional_spell_id_param(request)
    machine_raw = request.query_params.get("machine_id")
    try:
        d_val = date.fromisoformat(d)
        spell_id = _resolve_optional_spell(db, spell_id_param, spell_raw, branch_id)
        machine_id = int(machine_raw) if machine_raw else None
        rows = db.execute(
            get_weaving_entry_inputs_query(),
            {
                "co_id": co_id,
                "tran_date": d_val,
                "spell_id": spell_id,
                "machine_id": machine_id,
                "branch_id": branch_id,
            },
        ).fetchall()
        return {"data": [_serialize_entry_row(r) for r in rows]}
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tran_date or machine_id")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/machine_standards")
def machine_standards(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Resolve std/target/actual params + working_hours as-of date for a (loom, quality).

    Weaving is TWO-DIMENSIONAL: speed (std/actual) resolves from the MCID target map for
    the LOOM (machine_id); picks/eff resolve from the QID target map for the MAPPED quality.
    When weaving_quality_id is omitted the server reads it from the active Loom->Quality map
    for (tran_date, spell_id, machine_id).
    working_hours nets out stoppage hours (Q8) when machine_id + spell_id are supplied.
    Lets the entry form PREFILL the standards before save (kept as a convenience even
    though the view now computes everything on read). Returns 0.0 for any param with no
    active target-map row.
    """
    co_id = _require_co_id(request)
    branch_id = _optional_branch_id(request)
    machine_raw = request.query_params.get("machine_id")
    quality_raw = request.query_params.get("weaving_quality_id")
    spell_raw = request.query_params.get("spell")
    d = request.query_params.get("tran_date")
    if not d:
        raise HTTPException(status_code=400, detail="tran_date is required")
    try:
        machine_id = int(machine_raw) if machine_raw else 0
        spell_id = _resolve_optional_spell(
            db, _optional_spell_id_param(request), spell_raw, branch_id
        )
        weaving_quality_id = int(quality_raw) if quality_raw else None
        d_val = date.fromisoformat(d)

        # Quality is mapped, not selected inline — resolve from the map when not given.
        if weaving_quality_id is None and machine_id and spell_id:
            weaving_quality_id = _mapped_quality_id(db, co_id, d_val, spell_id, machine_id)

        std = resolve_quality_standards(db, co_id, machine_id, weaving_quality_id, d_val)
        if machine_id and spell_id:
            std["working_hours"] = net_working_hours(
                db, co_id, machine_id, d_val, spell_id
            )
        else:
            std["working_hours"] = 0.0
        std["weaving_quality_id"] = weaving_quality_id
        return {"data": std}
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Invalid machine_id, weaving_quality_id, spell_id or tran_date",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Endpoints — CRUD (persist INPUTS ONLY; the view computes on read)
# =============================================================================


@router.post("/entry_create")
def entry_create(
    body: WeavingEntryCreate,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Create (or upsert) one per-loom/per-quality entry — INPUTS ONLY.

    Quality is INHERITED from the active jute_prod_weaving_quality_map (NOT in the body).
    The server validates the quality is mapped and 0 <= close_jugar <= no_of_jugar_per_cut,
    resolves beam_no (latest beam map; eb_id left NULL, Q7), and persists the inputs keyed
    by (co_id, tran_date, spell_id, machine_id, weaving_quality_id, active=1). It does NOT
    compute or store any derived column — vw_weaving_daily does that on read.
    """
    try:
        # spell_id preferred (spell CODE deprecated fallback); co_id is optional.
        # Branch FIRST — spell resolution is branch-scoped (spell fanout via shift_mst).
        branch_id = body.branch_id
        if branch_id is None:
            branch_id = _derive_branch_id(db, body.machine_id)
        spell_id = _resolve_spell(db, body.spell_id, body.spell, branch_id)
        co_id = body.co_id if body.co_id is not None else _derive_co_id(db, branch_id)

        weaving_quality_id = _mapped_quality_id(
            db, co_id, body.tran_date, spell_id, body.machine_id
        )  # may be None: capture is allowed before the Loom->Quality map is done

        # Block mutation of a processed+locked (date,spell) unless the user has Edit.
        require_edit_if_locked(db, token_data, co_id, branch_id, body.tran_date, spell_id)

        # Validate close_jugar only when a quality (hence no_of_jugar_per_cut) is known.
        if weaving_quality_id is not None:
            quality = _fetch_quality(db, co_id, weaving_quality_id)
            _validate_close_jugar(body.close_jugar, quality)

        beam_no = db.execute(
            get_weaving_latest_beam_no_query(),
            {
                "co_id": _i(co_id),
                "tran_date": body.tran_date,
                "spell_id": spell_id,
                "machine_id": int(body.machine_id),
            },
        ).scalar()

        existing = db.execute(
            get_weaving_daily_active_row_by_machine_query(),
            {
                "co_id": _i(co_id),
                "tran_date": body.tran_date,
                "spell_id": spell_id,
                "machine_id": int(body.machine_id),
            },
        ).fetchone()

        # less_production (the "reduce jugar" adjustment) is NOT sent by the entry tab.
        # When omitted, PRESERVE the existing row's value (else 0.0) so a cuts re-save
        # never clobbers an adjustment made on the Production Adjustment tab.
        less_production = body.less_production
        if less_production is None:
            if existing:
                cur = db.execute(
                    text(
                        "SELECT less_production FROM jute_prod_weaving_daily "
                        "WHERE weaving_daily_id = :id"
                    ),
                    {"id": existing.weaving_daily_id},
                ).scalar()
                less_production = _f(cur)
            else:
                less_production = 0.0

        user_id = token_data.get("user_id")
        params = _input_params(
            co_id,
            branch_id,
            body.tran_date,
            spell_id,
            body.machine_id,
            weaving_quality_id,
            None,  # eb_id resolved via attendance later (Q7)
            beam_no,
            body.cuts,
            body.close_jugar,
            less_production,
            user_id,
        )

        if existing:
            params["id"] = existing.weaving_daily_id
            db.execute(update_weaving_daily_query(), params)
            weaving_daily_id = int(existing.weaving_daily_id)
        else:
            result = db.execute(insert_weaving_daily_query(), params)
            weaving_daily_id = int(result.lastrowid)
        # Phase 1b: persist this row's open_jugar + repair its single chain
        # successor, in the SAME transaction as the input write. Only with a
        # quality (the chain partitions by it); NULL-quality capture defers to Process.
        succ_id = None
        if weaving_quality_id is not None:
            succ_id = _sync_jugar_chain_after_write(
                db, weaving_daily_id, co_id, body.machine_id, weaving_quality_id,
                body.tran_date, spell_id,
            )
        # Spec §7: mutating a locked unit invalidates its frozen snapshot — and the
        # successor's unit too (its stored open_jugar was just rewritten).
        _flag_reprocess_units(db, co_id, body.tran_date, spell_id, succ_id)
        db.commit()
        return {
            "data": {
                "weaving_daily_id": weaving_daily_id,
                "weaving_quality_id": weaving_quality_id,
            }
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/entry_edit/{entry_id}")
def entry_edit(
    entry_id: int,
    body: WeavingEntryUpdate,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Edit one entry's inputs — INPUTS ONLY, no recompute, no cascade.

    Any omitted field keeps its existing value. Quality stays inherited from the
    (possibly changed) loom/spell/date map, falling back to the row's existing quality.
    The server validates 0 <= close_jugar <= no_of_jugar_per_cut and persists the inputs.
    There is NO recompute and NO jugar cascade — the view's LAG-over-existing-rows
    re-derives open/jugar/production for this row AND every downstream/next-day row on the
    next read.
    """
    co_id = _require_co_id(request)
    try:
        existing = db.execute(
            text(
                """
                SELECT weaving_daily_id, co_id, branch_id, tran_date, spell_id,
                       machine_id, weaving_quality_id, eb_id, beam_no, cuts,
                       close_jugar, less_production
                FROM jute_prod_weaving_daily
                WHERE weaving_daily_id = :id AND co_id = :co_id AND active = 1
                """
            ),
            {"id": entry_id, "co_id": co_id},
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail=ENTRY_NOT_FOUND_MSG)

        # Neither spell_id nor spell -> keep the row's spell. Either given -> the
        # shared contract validates it against the row's branch (no global fallback).
        if body.spell_id is not None or body.spell:
            spell_id = _resolve_spell(
                db, body.spell_id, body.spell, _i(existing.branch_id)
            )
        else:
            spell_id = int(existing.spell_id)
        machine_id = _i(body.machine_id, int(existing.machine_id))
        cuts = _i(body.cuts if body.cuts is not None else existing.cuts, 0)
        close_jugar = _f(
            body.close_jugar if body.close_jugar is not None else existing.close_jugar
        )
        less_production = _f(
            body.less_production
            if body.less_production is not None
            else existing.less_production
        )

        # Block mutation of a processed+locked (date,spell) unless the user has Edit.
        require_edit_if_locked(db, token_data, co_id, _i(existing.branch_id),
                               existing.tran_date, spell_id)
        # A spell/machine change moves the row OUT of its current unit/chain — the
        # OLD unit's frozen snapshot is mutated too, so gate on it as well.
        if (int(spell_id) != int(existing.spell_id)
                or int(machine_id) != int(existing.machine_id)):
            require_edit_if_locked(db, token_data, co_id, _i(existing.branch_id),
                                   existing.tran_date, existing.spell_id)

        # Quality is inherited from the (possibly changed) loom/spell/date map; fall back
        # to the row's existing quality when no active mapping exists (may stay None).
        weaving_quality_id = _mapped_quality_id(
            db, co_id, existing.tran_date, spell_id, machine_id
        )
        if weaving_quality_id is None:
            weaving_quality_id = _i(existing.weaving_quality_id)

        # Validate close_jugar only when a quality (hence no_of_jugar_per_cut) is known.
        if weaving_quality_id is not None:
            quality = _fetch_quality(db, co_id, weaving_quality_id)
            _validate_close_jugar(close_jugar, quality)

        branch_id = _derive_branch_id(db, machine_id)
        if branch_id is None:
            branch_id = _i(existing.branch_id)

        beam_no = db.execute(
            get_weaving_latest_beam_no_query(),
            {
                "co_id": int(co_id),
                "tran_date": existing.tran_date,
                "spell_id": int(spell_id),
                "machine_id": int(machine_id),
            },
        ).scalar()
        if not beam_no:
            beam_no = existing.beam_no

        user_id = token_data.get("user_id")
        params = _input_params(
            co_id,
            branch_id,
            existing.tran_date,
            spell_id,
            machine_id,
            weaving_quality_id,
            _i(existing.eb_id),
            beam_no,
            cuts,
            close_jugar,
            less_production,
            user_id,
        )
        params["id"] = entry_id
        db.execute(update_weaving_daily_query(), params)
        # Phase 1b: re-resolve this row's open_jugar + repair its chain successor
        # (only meaningful with a quality — the chain partitions by it).
        succ_id = None
        old_succ_id = None
        if weaving_quality_id is not None:
            succ_id = _sync_jugar_chain_after_write(
                db, entry_id, co_id, machine_id, weaving_quality_id,
                existing.tran_date, spell_id,
            )
            # An identity change moves the row between jugar chains — the OLD
            # position's successor lost its predecessor, repair it too.
            old_key = (_i(existing.machine_id), _i(existing.weaving_quality_id),
                       _i(existing.spell_id))
            if (existing.weaving_quality_id is not None
                    and old_key != (int(machine_id), int(weaving_quality_id), int(spell_id))):
                old_succ_id = _resync_chain_successor(
                    db, co_id, existing.machine_id, existing.weaving_quality_id,
                    existing.tran_date, existing.spell_id, entry_id,
                )
        # Spec §7: flag the edited unit + chain successor's unit for reprocess if locked.
        _flag_reprocess_units(db, co_id, existing.tran_date, spell_id, succ_id)
        # A unit move also invalidates the OLD unit (and its repaired old-chain successor).
        if old_succ_id is not None or int(spell_id) != int(existing.spell_id):
            _flag_reprocess_units(
                db, co_id, existing.tran_date, existing.spell_id, old_succ_id
            )
        db.commit()
        return {
            "data": {
                "message": "Updated",
                "weaving_daily_id": entry_id,
                "weaving_quality_id": weaving_quality_id,
            }
        }
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
    """Soft-delete (active=NULL — see soft_delete_weaving_daily_query) one weaving-daily entry."""
    co_id = _require_co_id(request)
    try:
        existing = db.execute(
            text(
                """
                SELECT weaving_daily_id, machine_id, weaving_quality_id,
                       tran_date, spell_id
                FROM jute_prod_weaving_daily
                WHERE weaving_daily_id = :id AND co_id = :co_id AND active = 1
                """
            ),
            {"id": entry_id, "co_id": co_id},
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail=ENTRY_NOT_FOUND_MSG)

        # Block delete of a processed+locked (date,spell) unless the user has Edit.
        require_edit_if_locked(db, token_data, co_id, None,
                               existing.tran_date, existing.spell_id)

        user_id = token_data.get("user_id")
        db.execute(
            soft_delete_weaving_daily_query(), {"id": entry_id, "updated_by": user_id}
        )
        # Phase 1b: the deleted row's successor now carries forward from the
        # deleted row's own predecessor — repair it in the same transaction.
        # NULL-quality rows are in no jugar chain (same guard as create/edit).
        succ_id = None
        if existing.weaving_quality_id is not None:
            succ_id = _resync_chain_successor(
                db, co_id, existing.machine_id, existing.weaving_quality_id,
                existing.tran_date, existing.spell_id, entry_id,
            )
        # Spec §7: deleting from a locked unit invalidates its frozen snapshot —
        # and the successor's unit too (its stored open_jugar was just rewritten).
        _flag_reprocess_units(
            db, co_id, existing.tran_date, existing.spell_id, succ_id
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
# Planning grid (jute_prod_weaving_daily) — view-backed, per loom+quality
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
    """View-backed planning grid for a tran_date (optional spell_id).

    Driver rows are the active jute_prod_weaving_quality_map rows (one loom mapped to one
    quality per (tran_date, spell_id)) LEFT JOIN vw_weaving_daily — so mapped looms with no
    entry yet still appear (NULL view columns -> coalesced to 0) and every saved row carries
    the view-computed open_jugar/jugar/production/std/efficiency. Nothing is recomputed in
    Python; the grid always reflects current masters + as-of standards. A per-(loom,quality,
    shift) rollup sums numerator/denominator (never the average of effs).
    """
    co_id = _require_co_id(request)
    branch_id = _optional_branch_id(request)
    d = request.query_params.get("tran_date")
    if not d:
        raise HTTPException(status_code=400, detail="tran_date is required")
    spell_raw = request.query_params.get("spell")
    spell_id_param = _optional_spell_id_param(request)
    try:
        d_val = date.fromisoformat(d)
        spell_id = _resolve_optional_spell(db, spell_id_param, spell_raw, branch_id)

        driver = db.execute(
            get_weaving_plan_driver_query(),
            {
                "co_id": co_id,
                "tran_date": d_val,
                "spell_id": spell_id,
                "loom_type": WEAVING_MACHINE_TYPE_NAME,
                "machine_id": None,  # grid spans all mapped looms
                "branch_id": branch_id,
            },
        ).fetchall()

        rows: List[Dict[str, Any]] = []
        for r in driver:
            m = dict(r._mapping)
            machine_id = int(m["machine_id"])
            row_spell_id = int(m["spell_id"])
            weaving_quality_id = int(m["weaving_quality_id"])
            spell_code = m.get("spell_code")

            rows.append(
                {
                    "weaving_daily_id": _i(m.get("weaving_daily_id")),
                    "weaving_quality_map_id": int(m["weaving_quality_map_id"]),
                    "spell_id": row_spell_id,
                    "spell_code": spell_code,
                    "shift_bucket": _shift_bucket(spell_code),
                    "machine_id": machine_id,
                    "mech_code": m.get("mech_code"),
                    "machine_name": m.get("machine_name"),
                    "line_no": m.get("line_no"),
                    "branch_id": m.get("branch_id"),
                    "item_id": _i(m.get("item_id")),
                    "item_code": m.get("item_code"),
                    "item_name": m.get("item_name"),
                    "weaving_quality_id": weaving_quality_id,
                    "weaving_quality_code": m.get("weaving_quality_code"),
                    "weaving_quality_name": m.get("weaving_quality_name"),
                    "is_composite": bool(m.get("is_composite")),
                    "cuts": _f(m.get("cuts")),
                    "close_jugar": _f(m.get("close_jugar")),
                    "less_production": _f(m.get("less_production")),
                    "open_jugar": _f(m.get("open_jugar")),
                    "jugar": _f(m.get("jugar")),
                    "finished_length": _f(m.get("finished_length")),
                    "ozs_yds": _f(m.get("ozs_yds")),
                    "std_ozs_yds": _f(m.get("std_ozs_yds")),
                    "no_of_jugar_per_cut": _f(m.get("no_of_jugar_per_cut")),
                    "std_speed": _f(m.get("std_speed")),
                    "act_speed": _f(m.get("act_speed")),
                    "std_picks": _f(m.get("std_picks")),
                    "act_picks": _f(m.get("act_picks")),
                    "std_eff": _f(m.get("std_eff")),
                    "target_eff": _f(m.get("target_eff")),
                    "eff_speed": _f(m.get("eff_speed")),
                    "eff_picks": _f(m.get("eff_picks")),
                    "working_hours": _f(m.get("working_hours")),
                    "production_yds": _f(m.get("production_yds")),
                    "production_kg": _f(m.get("production_kg")),
                    "production_mt": _f(m.get("production_mt")),
                    "std_prod_yds": _f(m.get("std_prod_yds")),  # "100prod" — 100% eff theoretical (drives actual eff)
                    "target_prod_yds": _f(m.get("target_prod_yds")),
                    # "std prod" = 100prod * std_eff% (efficiency-weighted standard production).
                    "std_prod_eff": round(_f(m.get("std_prod_yds")) * _f(m.get("std_eff")) / 100.0, 3),
                    "efficiency": _f(m.get("efficiency")),  # ACTUAL eff = production_yds*100/100prod
                    "std_prod_kg": _f(m.get("std_prod_kg")),
                    "target_kg": _f(m.get("target_kg")),
                }
            )

        # Shift rollup per (machine, quality, shift_bucket): SUM(num)/SUM(denom).
        roll: Dict[tuple, Dict[str, Any]] = {}
        for row in rows:
            key = (
                row["machine_id"],
                row["weaving_quality_id"],
                row["shift_bucket"],
            )
            agg = roll.setdefault(
                key,
                {
                    "machine_id": row["machine_id"],
                    "mech_code": row.get("mech_code"),
                    "machine_name": row.get("machine_name"),
                    "weaving_quality_id": row["weaving_quality_id"],
                    "weaving_quality_code": row.get("weaving_quality_code"),
                    "shift_bucket": row["shift_bucket"],
                    "production_yds": 0.0,
                    "production_kg": 0.0,
                    "_std_prod_yds": 0.0,
                },
            )
            agg["production_yds"] += row["production_yds"]
            agg["production_kg"] += row["production_kg"]
            agg["_std_prod_yds"] += row["std_prod_yds"]

        shift_rollup = []
        for agg in roll.values():
            std_prod_yds = agg.pop("_std_prod_yds")
            agg["production_yds"] = round(agg["production_yds"], 3)
            agg["production_kg"] = round(agg["production_kg"], 3)
            # SUM(production_yds) / SUM(std_prod_yds) * 100 — never the avg of row effs.
            agg["efficiency"] = (
                round(agg["production_yds"] / std_prod_yds * 100, 2)
                if std_prod_yds > 0
                else 0.0
            )
            shift_rollup.append(agg)

        return {"data": {"rows": rows, "shift_rollup": shift_rollup}}
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tran_date or spell_id")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/planning_grid_save")
def planning_grid_save(
    body: PlanningGridSave,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Batch upsert per-loom/per-quality planning rows into jute_prod_weaving_daily — INPUTS ONLY.

    For EACH row the server re-derives the quality from the active Loom->Quality map (the
    client weaving_quality_id is ignored), validates 0 <= close_jugar <= no_of_jugar_per_cut,
    resolves beam_no (eb_id left NULL), and persists ONLY the genuine inputs (cuts,
    close_jugar, less_production). NO computed/standard columns are stored — vw_weaving_daily
    derives them on read.

    App-uniqueness is (co_id, tran_date, spell_id, machine_id, weaving_quality_id, active=1):
    an existing active row is updated, otherwise a fresh one is inserted. branch_id is derived
    from the machine when the row omits it. The whole batch is one transaction.
    """
    try:
        user_id = token_data.get("user_id")
        saved = 0
        # Request-local memo caches: rows in a batch overwhelmingly share the same
        # (co, branch, spell) and qualities, so loop-invariant lookups (branch/co
        # derivation, quality map, quality row, lock gate, reprocess flag) run once
        # per distinct key instead of once per row (~10 SQL/row on a 400-loom grid).
        # Nothing in this txn mutates those source tables, so memoizing is identical.
        branch_memo: Dict[int, Optional[int]] = {}       # machine_id -> branch_id
        co_memo: Dict[Optional[int], Optional[int]] = {}  # branch_id -> co_id
        spell_memo: Dict[tuple, int] = {}                # (id, code, branch) -> spell_id
        qmap_memo: Dict[tuple, Optional[int]] = {}       # (co, spell, machine) -> quality_id
        quality_memo: Dict[tuple, Any] = {}              # (co, quality_id) -> quality row
        lock_checked: set = set()                        # (co, branch, spell) gates passed
        flagged_units: set = set()                       # units already reprocess-flagged
        for e in body.rows:
            branch_id = body.branch_id
            if branch_id is None:
                if e.machine_id not in branch_memo:
                    branch_memo[e.machine_id] = _derive_branch_id(db, e.machine_id)
                branch_id = branch_memo[e.machine_id]
            if body.co_id is not None:
                co_id = body.co_id
            else:
                if branch_id not in co_memo:
                    co_memo[branch_id] = _derive_co_id(db, branch_id)
                co_id = co_memo[branch_id]

            # Per-row spell resolution (spell_id preferred, code deprecated fallback),
            # branch-scoped — memoized, rows overwhelmingly share one spell.
            skey = (e.spell_id, e.spell, branch_id)
            if skey not in spell_memo:
                spell_memo[skey] = _resolve_spell(db, e.spell_id, e.spell, branch_id)
            spell_id = spell_memo[skey]

            qmap_key = (co_id, spell_id, e.machine_id)
            if qmap_key not in qmap_memo:
                qmap_memo[qmap_key] = _mapped_quality_id(
                    db, co_id, body.tran_date, spell_id, e.machine_id
                )
            weaving_quality_id = qmap_memo[qmap_key]  # may be None: capture allowed pre-mapping

            # Block mutation of a processed+locked (date,spell) unless the user has Edit.
            lock_key = (co_id, branch_id, spell_id)
            if lock_key not in lock_checked:
                require_edit_if_locked(
                    db, token_data, co_id, branch_id, body.tran_date, spell_id
                )
                lock_checked.add(lock_key)

            # Validate close_jugar only when a quality (hence no_of_jugar_per_cut) is known.
            if weaving_quality_id is not None:
                q_key = (co_id, weaving_quality_id)
                if q_key not in quality_memo:
                    quality_memo[q_key] = _fetch_quality(db, co_id, weaving_quality_id)
                _validate_close_jugar(e.close_jugar, quality_memo[q_key])

            beam_no = db.execute(
                get_weaving_latest_beam_no_query(),
                {
                    "co_id": _i(co_id),
                    "tran_date": body.tran_date,
                    "spell_id": int(spell_id),
                    "machine_id": int(e.machine_id),
                },
            ).scalar()

            params = _input_params(
                co_id,
                branch_id,
                body.tran_date,
                spell_id,
                e.machine_id,
                weaving_quality_id,
                None,  # eb_id resolved via attendance later (Q7)
                beam_no,
                e.cuts,
                e.close_jugar,
                e.less_production,
                user_id,
            )

            existing = db.execute(
                get_weaving_daily_active_row_by_machine_query(),
                {
                    "co_id": _i(co_id),
                    "tran_date": body.tran_date,
                    "spell_id": int(spell_id),
                    "machine_id": int(e.machine_id),
                },
            ).fetchone()
            if existing:
                params["id"] = existing.weaving_daily_id
                db.execute(update_weaving_daily_query(), params)
                row_id = int(existing.weaving_daily_id)
            else:
                result = db.execute(insert_weaving_daily_query(), params)
                row_id = int(result.lastrowid)
            # Phase 1b: per-row open_jugar + single-successor repair, same txn
            # (only with a quality — the chain partitions by it).
            succ_id = None
            if weaving_quality_id is not None:
                succ_id = _sync_jugar_chain_after_write(
                    db, row_id, co_id, e.machine_id, weaving_quality_id,
                    body.tran_date, spell_id,
                )
            # Spec §7: saving into a locked unit invalidates its frozen snapshot —
            # and the successor's unit too (its stored open_jugar was just rewritten).
            _flag_reprocess_units(
                db, co_id, body.tran_date, spell_id, succ_id, seen=flagged_units
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


# =============================================================================
# Loom -> Quality map (jute_prod_weaving_quality_map) — clone of spinning frame_map_*
# One ACTIVE row per (tran_date, spell_id, machine_id). Production inherits quality here.
# =============================================================================


@router.get("/quality_map_get")
def quality_map_get(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Loom->Quality grid for a (tran_date, spell_id), with carry-forward prefill.

    Every Loom-type machine with today's SAVED mapping plus the loom's most-recent saved
    mapping across any spell/date (prev_quality_*) so the client can prefill the dropdown
    and flag it 'Unsaved' until Save Map. Looms resolved by NAME 'Loom'.
    """
    co_id = _require_co_id(request)
    branch_id = _optional_branch_id(request)
    d = request.query_params.get("tran_date")
    spell_raw = request.query_params.get("spell")
    spell_id_param = _optional_spell_id_param(request)
    if not d or (spell_id_param is None and not spell_raw):
        raise HTTPException(status_code=400, detail=SPELL_REQUIRED_MSG)
    try:
        d_val = date.fromisoformat(d)
        spell_id = _resolve_spell(db, spell_id_param, spell_raw, branch_id)

        rows = db.execute(
            get_weaving_quality_map_query(),
            {
                "co_id": co_id,
                "tran_date": d_val,
                "spell_id": spell_id,
                "loom_type": WEAVING_MACHINE_TYPE_NAME,
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
                    "mech_posting_code": m.get("mech_posting_code"),
                    "machine_name": m["machine_name"],
                    "line_no": m.get("line_no"),
                    "branch_id": m.get("branch_id"),
                    "weaving_quality_map_id": m.get("weaving_quality_map_id"),
                    "weaving_quality_id": m.get("weaving_quality_id"),
                    "weaving_quality_code": m.get("weaving_quality_code"),
                    "weaving_quality_name": m.get("weaving_quality_name"),
                    "prev_quality_id": m.get("prev_quality_id"),
                    "prev_quality_code": m.get("prev_quality_code"),
                    "prev_quality_name": m.get("prev_quality_name"),
                    "prev_date": str(prev_date) if prev_date is not None else None,
                }
            )

        last_updated = db.execute(
            get_weaving_quality_map_last_updated_query(),
            {"co_id": co_id, "branch_id": branch_id},
        ).scalar()

        return {
            "data": data,
            "last_updated": str(last_updated) if last_updated is not None else None,
        }
    except HTTPException:
        db.rollback()
        raise
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tran_date")
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/quality_map_saved")
def quality_map_saved(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Cheap Loom->Quality grid for a (tran_date, spell) — saved mapping only, NO carry-forward.

    Same loom set + response shape as /quality_map_get (LoomQualityMapRow), but the four
    per-loom prev_quality_* correlated subqueries are dropped (prev_* returned as NULL).
    On large tenants that is ~88ms vs ~20s. The Production Entry grid only needs the loom
    list + saved mapping; the mapping EDITOR keeps /quality_map_get for carry-forward prefill.
    """
    co_id = _require_co_id(request)
    branch_id = _optional_branch_id(request)
    d = request.query_params.get("tran_date")
    spell_raw = request.query_params.get("spell")
    spell_id_param = _optional_spell_id_param(request)
    if not d or (spell_id_param is None and not spell_raw):
        raise HTTPException(status_code=400, detail=SPELL_REQUIRED_MSG)
    try:
        d_val = date.fromisoformat(d)
        spell_id = _resolve_spell(db, spell_id_param, spell_raw, branch_id)

        rows = db.execute(
            get_weaving_quality_map_saved_query(),
            {
                "co_id": co_id,
                "tran_date": d_val,
                "spell_id": spell_id,
                "loom_type": WEAVING_MACHINE_TYPE_NAME,
                "branch_id": branch_id,
            },
        ).fetchall()
        data = []
        for r in rows:
            m = dict(r._mapping)
            data.append(
                {
                    "machine_id": m["machine_id"],
                    "mech_code": m["mech_code"],
                    "mech_posting_code": m.get("mech_posting_code"),
                    "machine_name": m["machine_name"],
                    "line_no": m.get("line_no"),
                    "branch_id": m.get("branch_id"),
                    "weaving_quality_map_id": m.get("weaving_quality_map_id"),
                    "weaving_quality_id": m.get("weaving_quality_id"),
                    "weaving_quality_code": m.get("weaving_quality_code"),
                    "weaving_quality_name": m.get("weaving_quality_name"),
                    "no_of_jugar_per_cut": m.get("no_of_jugar_per_cut"),
                    # No carry-forward on this cheap read — the editor's endpoint fills these.
                    "prev_quality_id": None,
                    "prev_quality_code": None,
                    "prev_quality_name": None,
                    "prev_date": None,
                }
            )

        last_updated = db.execute(
            get_weaving_quality_map_last_updated_query(),
            {"co_id": co_id, "branch_id": branch_id},
        ).scalar()

        return {
            "data": data,
            "last_updated": str(last_updated) if last_updated is not None else None,
        }
    except HTTPException:
        db.rollback()
        raise
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tran_date")
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/quality_map_save")
def quality_map_save(
    body: QualityMapSave,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Batch upsert the Loom->Quality map for a (tran_date, spell).

    One ACTIVE row per (co_id, tran_date, spell_id, machine_id) — an existing active row is
    UPDATED in place, otherwise a fresh row is inserted. Tolerates a loom set that changed
    since the grid loaded (skips malformed ids). The client sends the spell CODE ('A1').
    branch_id + co_id are derived from the machine/branch when the body omits them.

    A created/changed mapping also RE-STAMPS the cell's active daily rows (NULL or stale
    weaving_quality_id -> new quality) and re-syncs both jugar chains, so production
    captured before the mapping no longer freezes as zero.
    """
    try:
        user_id = token_data.get("user_id")
        spell_id = _resolve_spell(db, body.spell_id, body.spell, body.branch_id)
        # Block remapping a processed+locked (date,spell) unless the user has Edit.
        # Fail closed: derive co_id from the first entry's machine when the body
        # omits both co_id and branch_id (mirrors adjustment_save). ONE gate + ONE
        # reprocess flag per request — the whole batch shares (co, date, spell).
        _lock_co = _lock_co_for_batch(db, body.co_id, body.branch_id, body.entries)
        if _lock_co is not None:
            require_edit_if_locked(db, token_data, _lock_co, body.branch_id,
                                   body.tran_date, spell_id)
        saved = 0
        skipped = 0
        current_syncs = []  # Layer 3: pointer upserts, run after the loop (non-null quality only)
        for e in body.entries:
            try:
                machine_id = int(e.machine_id)
            except (TypeError, ValueError):
                skipped += 1
                continue
            if machine_id <= 0:
                skipped += 1
                continue

            branch_id = body.branch_id
            if branch_id is None:
                branch_id = _derive_branch_id(db, machine_id)
            co_id = body.co_id if body.co_id is not None else _derive_co_id(db, branch_id)

            existing = db.execute(
                get_weaving_quality_map_active_row_query(),
                {
                    "co_id": _i(co_id),
                    "tran_date": body.tran_date,
                    "spell_id": spell_id,
                    "machine_id": machine_id,
                },
            ).fetchone()
            if existing:
                db.execute(
                    update_weaving_quality_map_row_query(),
                    {
                        "id": existing.weaving_quality_map_id,
                        "weaving_quality_id": _i(e.weaving_quality_id),
                        "updated_by": user_id,
                    },
                )
            else:
                db.execute(
                    insert_weaving_quality_map_row_query(),
                    {
                        "co_id": _i(co_id),
                        "branch_id": _i(branch_id),
                        "tran_date": body.tran_date,
                        "spell_id": spell_id,
                        "machine_id": machine_id,
                        "weaving_quality_id": _i(e.weaving_quality_id),
                        "updated_by": user_id,
                    },
                )
            new_q = _i(e.weaving_quality_id)
            if new_q is not None:
                current_syncs.append(
                    {
                        "co_id": _i(co_id),
                        "branch_id": _i(branch_id),
                        "machine_id": machine_id,
                        "weaving_quality_id": new_q,
                        "tran_date": body.tran_date,
                        "spell_id": spell_id,
                    }
                )
                # Re-stamp saved daily rows for this cell: capture BEFORE the map left
                # weaving_quality_id NULL (day-slice computes zero production), a remap
                # left it stale. Update the stored quality + run the jugar-chain sync
                # for the row's NEW chain, and repair the OLD chain's successor when
                # the row moves between chains (same pattern as entry_edit).
                stale_rows = db.execute(
                    get_weaving_daily_rows_to_restamp_query(),
                    {
                        "co_id": _i(co_id),
                        "tran_date": body.tran_date,
                        "spell_id": spell_id,
                        "machine_id": machine_id,
                        "weaving_quality_id": new_q,
                    },
                ).fetchall()
                for stale in stale_rows:
                    rid = int(stale.weaving_daily_id)
                    old_q = _i(stale.weaving_quality_id)
                    db.execute(
                        update_weaving_daily_quality_stamp_query(),
                        {"id": rid, "weaving_quality_id": new_q, "updated_by": user_id},
                    )
                    succ_id = _sync_jugar_chain_after_write(
                        db, rid, int(co_id), machine_id, new_q,
                        body.tran_date, spell_id,
                    )
                    _flag_reprocess_units(db, co_id, body.tran_date, spell_id, succ_id)
                    if old_q is not None:
                        old_succ_id = _resync_chain_successor(
                            db, int(co_id), machine_id, old_q,
                            body.tran_date, spell_id, rid,
                        )
                        _flag_reprocess_units(
                            db, co_id, body.tran_date, spell_id, old_succ_id
                        )
            saved += 1
        # Layer 3: flush the current-quality pointer upserts after the map rows (same txn).
        for sync in current_syncs:
            db.execute(upsert_weaving_current_quality_query(), sync)
        # Spec §7: remapping a locked unit invalidates its frozen snapshot.
        if _lock_co is not None and saved:
            flag_reprocess_if_locked(db, _lock_co, body.tran_date, spell_id)
        db.commit()
        return {"data": {"saved": saved, "skipped": skipped}}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/quality_map_mapped")
def quality_map_mapped(
    body: QualityMapMapped,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """The saved Loom->Quality mappings for a (tran_date, spell_id) — the mapped view.

    Only looms that actually have an active mapping for this cell, with the machine +
    quality + item labels. Looms resolved by NAME 'Loom'.
    """
    try:
        co_id = body.co_id if body.co_id is not None else _derive_co_id(db, body.branch_id)
        if co_id is None:
            raise HTTPException(status_code=400, detail="co_id or branch_id is required")
        spell_id = _resolve_optional_spell(
            db, body.spell_id, body.spell, _i(body.branch_id)
        )
        rows = db.execute(
            get_weaving_quality_map_mapped_query(),
            {
                "co_id": int(co_id),
                "tran_date": body.tran_date,
                "spell_id": spell_id,
                "machine_id": _i(body.machine_id),
                "loom_type": WEAVING_MACHINE_TYPE_NAME,
                "branch_id": _i(body.branch_id),
            },
        ).fetchall()
        data = []
        for r in rows:
            m = dict(r._mapping)
            if m.get("updated_date_time") is not None:
                m["updated_date_time"] = str(m["updated_date_time"])
            data.append(m)
        return {"data": data}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Beam -> Loom map (jute_prod_weaving_beam_map) — beam-change tab
# Upsert beam_no per (co_id, tran_date, spell_id, machine_id).
# =============================================================================


@router.get("/beam_map_get")
def beam_map_get(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Beam-change grid for a (tran_date, spell_id): every loom + its latest beam_no.

    Returns each Loom-type machine with its most-recent active beam_no for the cell so the
    client can show/edit the mounted beam. Looms resolved by NAME 'Loom'.
    """
    co_id = _require_co_id(request)
    branch_id = _optional_branch_id(request)
    d = request.query_params.get("tran_date")
    spell_raw = request.query_params.get("spell")
    spell_id_param = _optional_spell_id_param(request)
    if not d or (spell_id_param is None and not spell_raw):
        raise HTTPException(status_code=400, detail=SPELL_REQUIRED_MSG)
    try:
        d_val = date.fromisoformat(d)
        spell_id = _resolve_spell(db, spell_id_param, spell_raw, branch_id)
        rows = db.execute(
            get_weaving_beam_map_query(),
            {
                "co_id": co_id,
                "tran_date": d_val,
                "spell_id": spell_id,
                "loom_type": WEAVING_MACHINE_TYPE_NAME,
                "branch_id": branch_id,
            },
        ).fetchall()
        return {"data": [dict(r._mapping) for r in rows]}
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tran_date")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/beam_map_save")
def beam_map_save(
    body: BeamMapSave,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Batch upsert beam_no per (co_id, tran_date, spell_id, machine_id).

    One ACTIVE row per loom/spell/date — an existing active row is UPDATED in place,
    otherwise a fresh one is inserted. Tolerates a loom set that changed since the grid
    loaded (skips malformed ids). The client sends the spell CODE ('A1'). branch_id +
    co_id are derived from the machine/branch when omitted.
    """
    try:
        user_id = token_data.get("user_id")
        spell_id = _resolve_spell(db, body.spell_id, body.spell, body.branch_id)
        # Block beam changes on a processed+locked (date,spell) unless the user has
        # Edit. ONE gate + ONE reprocess flag per request — the batch shares the unit.
        _lock_co = _lock_co_for_batch(db, body.co_id, body.branch_id, body.entries)
        if _lock_co is not None:
            require_edit_if_locked(db, token_data, _lock_co, body.branch_id,
                                   body.tran_date, spell_id)
        saved = 0
        skipped = 0
        for e in body.entries:
            try:
                machine_id = int(e.machine_id)
            except (TypeError, ValueError):
                skipped += 1
                continue
            if machine_id <= 0:
                skipped += 1
                continue

            branch_id = body.branch_id
            if branch_id is None:
                branch_id = _derive_branch_id(db, machine_id)
            co_id = body.co_id if body.co_id is not None else _derive_co_id(db, branch_id)

            beam_no = e.beam_no if e.beam_no else None
            existing = db.execute(
                get_weaving_beam_map_active_row_query(),
                {
                    "co_id": _i(co_id),
                    "tran_date": body.tran_date,
                    "spell_id": spell_id,
                    "machine_id": machine_id,
                },
            ).fetchone()
            if existing:
                beam_changed = (existing.beam_no or None) != beam_no
                db.execute(
                    update_weaving_beam_map_row_query(),
                    {
                        "id": existing.weaving_beam_map_id,
                        "beam_no": beam_no,
                        "updated_by": user_id,
                    },
                )
            else:
                beam_changed = beam_no is not None
                db.execute(
                    insert_weaving_beam_map_row_query(),
                    {
                        "co_id": _i(co_id),
                        "branch_id": _i(branch_id),
                        "tran_date": body.tran_date,
                        "spell_id": spell_id,
                        "machine_id": machine_id,
                        "beam_no": beam_no,
                        "updated_by": user_id,
                    },
                )
            # A fresh beam resets the loom's jugar counter: the cell's daily row (if
            # any) must OPEN at 0, not at the previous beam's close — otherwise
            # closing < opening reads as lost production. Zero the stored open_jugar
            # and repair the chain successor. Re-saving an unchanged grid is NOT a
            # beam change and leaves the chain alone.
            # ponytail: a later entry re-save re-resolves open_jugar from the chain
            # predecessor (clobbers this zero); beam-aware resolution is the upgrade.
            if beam_changed:
                daily = db.execute(
                    get_weaving_daily_active_row_by_machine_query(),
                    {
                        "co_id": _i(co_id),
                        "tran_date": body.tran_date,
                        "spell_id": spell_id,
                        "machine_id": machine_id,
                    },
                ).fetchone()
                if daily:
                    db.execute(
                        update_weaving_daily_open_jugar_query(),
                        {"row_id": int(daily.weaving_daily_id), "open_jugar": 0.0},
                    )
                    if daily.weaving_quality_id is not None:
                        _resync_chain_successor(
                            db, co_id, machine_id, int(daily.weaving_quality_id),
                            body.tran_date, spell_id, int(daily.weaving_daily_id),
                        )
            saved += 1
        # Spec §7: a beam change on a locked unit invalidates its frozen snapshot.
        if _lock_co is not None and saved:
            flag_reprocess_if_locked(db, _lock_co, body.tran_date, spell_id)
        db.commit()
        return {"data": {"saved": saved, "skipped": skipped}}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Production Adjustment (jute_prod_weaving_daily.less_production = "reduce jugar")
# Sets ONLY less_production per loom for a (tran_date, spell); the view subtracts
# less_production/jc from production. Grain matches the daily row (incl. mapped quality).
# =============================================================================


@router.get("/adjustment_get")
def adjustment_get(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Looms + mapped quality + current less_production for a (tran_date, spell).

    Mirrors beam_map_get: require co_id, optional branch_id, require tran_date + spell.
    Each row is the loom with its mapped quality and the adjustment value currently stored
    on the active daily row (0 when none yet). Looms resolved by NAME 'Loom'.
    """
    co_id = _require_co_id(request)
    branch_id = _optional_branch_id(request)
    d = request.query_params.get("tran_date")
    spell_raw = request.query_params.get("spell")
    spell_id_param = _optional_spell_id_param(request)
    if not d or (spell_id_param is None and not spell_raw):
        raise HTTPException(status_code=400, detail=SPELL_REQUIRED_MSG)
    try:
        d_val = date.fromisoformat(d)
        spell_id = _resolve_spell(db, spell_id_param, spell_raw, branch_id)
        rows = db.execute(
            get_weaving_adjustment_grid_query(),
            {
                "co_id": co_id,
                "tran_date": d_val,
                "spell_id": spell_id,
                "loom_type": WEAVING_MACHINE_TYPE_NAME,
                "branch_id": branch_id,
            },
        ).fetchall()
        data = []
        for r in rows:
            m = dict(r._mapping)
            # less_production -> float; mech_posting_code / weaving_daily_id stay int|None.
            m["less_production"] = _f(m.get("less_production"))
            data.append(m)
        return {"data": data}
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tran_date")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/adjustment_save")
def adjustment_save(
    body: AdjustmentSave,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Set ONLY less_production per loom for a (tran_date, spell). One transaction.

    For each entry: derive branch_id/co_id when omitted, resolve the mapped quality (the
    daily-row grain includes it) — no mapping => skipped. Update less_production on the
    active daily row when one exists; no daily row => skipped (an adjustment reduces
    production — with no production row there is nothing to reduce, and a manufactured
    cuts=0 row would go strictly negative AND zero its chain successor's open_jugar).
    Skipped looms are returned in skipped_machines. Mirrors beam_map_save's
    malformed-id tolerance.
    """
    try:
        user_id = token_data.get("user_id")
        spell_id = _resolve_spell(db, body.spell_id, body.spell, body.branch_id)
        # Block mutation of a processed+locked (date,spell) unless the user has Edit.
        _lock_co = _lock_co_for_batch(db, body.co_id, body.branch_id, body.entries)
        if _lock_co is not None:
            require_edit_if_locked(db, token_data, _lock_co, body.branch_id,
                                   body.tran_date, spell_id)
        saved = 0
        skipped = 0
        skipped_machines: list = []
        for e in body.entries:
            try:
                machine_id = int(e.machine_id)
            except (TypeError, ValueError):
                skipped += 1
                continue
            if machine_id <= 0:
                skipped += 1
                continue

            branch_id = body.branch_id
            if branch_id is None:
                branch_id = _derive_branch_id(db, machine_id)
            co_id = body.co_id if body.co_id is not None else _derive_co_id(db, branch_id)

            weaving_quality_id = _mapped_quality_id(
                db, co_id, body.tran_date, spell_id, machine_id
            )
            if weaving_quality_id is None:
                # An adjustment row needs the mapped quality (daily-row uniqueness includes it).
                skipped += 1
                skipped_machines.append(machine_id)
                continue

            existing = db.execute(
                get_weaving_daily_active_row_by_machine_query(),
                {
                    "co_id": _i(co_id),
                    "tran_date": body.tran_date,
                    "spell_id": spell_id,
                    "machine_id": machine_id,
                },
            ).fetchone()
            if existing:
                # Touches ONLY less_production, which never affects the jugar
                # chain — no sync needed.
                db.execute(
                    update_weaving_daily_less_production_query(),
                    {
                        "id": existing.weaving_daily_id,
                        "less_production": _f(e.less_production),
                        "updated_by": user_id,
                    },
                )
                saved += 1
            else:
                # No daily row => nothing to reduce. A manufactured cuts=0 row
                # would compute strictly negative total_jugar and zero its chain
                # successor's open_jugar (inflating the next day) — skip instead.
                skipped += 1
                skipped_machines.append(machine_id)
        # Spec §7: adjusting a locked unit invalidates its frozen snapshot.
        # less_production never touches the jugar chain — no successor to flag.
        if _lock_co is not None:
            _flag_reprocess_units(db, _lock_co, body.tran_date, spell_id, None)
        db.commit()
        return {
            "data": {
                "saved": saved,
                "skipped": skipped,
                "skipped_machines": skipped_machines,
            }
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
