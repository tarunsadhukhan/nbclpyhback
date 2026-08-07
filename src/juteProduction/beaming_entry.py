"""Beaming Production Entry endpoints (Page C, prefix /api/beamingProd).

Daily per-machine/per-quality production entry, modelled on spinning_entry.py:
get_tenant_db + get_current_user_with_refresh, {"data": ...} responses, soft delete
via active=0, no approval workflow, trigger-based audit (no created_*).

Per the locked grain (SPEC §0, §C.1) the entry header is (tran_date, spell_id, eb_id,
machine_id) and each row is (item_id, bm_quality_id, act_cuts, no_of_beam). On create/edit
the SERVER is authoritative:

  * ends / std_count          -> resolved from the Page A row (jute_prod_bm_quality)
  * laid_length / cuts_per_beam / std_speed / target_speed / std_eff / target_eff
                              -> resolved via beaming_standards.resolve_machine_standards
                                 (LAST-DATE, as-of tran_date) from jute_prod_beaming_target_map
  * working_hours             -> max(0, spell_mst.working_hours − idle_hours), where
                                 idle_hours = Σ jute_prod_stoppage_hours for the
                                 (co_id, machine_id, tran_date, spell_id) (Q8)
  * dia (roller diameter)     -> machine-linked STANDARD resolved server-side (Q7);
                                 NOT an entry input. Stored in the dia_roller column.
  * act_count                 -> defaults to std_count (SQC override deferred §12 Q5)

then compute_beaming_daily(...) produces every derived column and the FULL snapshot is
stored in jute_prod_beaming_daily.

SQC SEAM (rpm_roller / act_speed): the ACTUAL roller speed (rpm_roller) is NOT a
production-entry input. It is populated later by the future Beaming SQC page (a tab,
mirroring how Spinning's SQC overrides act_count via jute_sqc_spinning_count). Until that
page is wired, production entry passes NO rpm into compute_beaming_daily, so act_speed
computes to 0 — exactly like idle_hours read 0 before Stoppage Hours was wired, and like
Spinning's act_count default-then-SQC-override pattern. The rpm_roller and act_speed
COLUMNS / query binds are kept (default NULL/0) so the SQC page can update them on the
daily row; dia stays resolved from the machine standard (Q7) and is stored in dia_roller.

COMPOSITE (SPEC §C.5 / Q3): a quality whose jute_prod_bm_quality.is_composite = 1 carries
its real (ends, count) warp-component pairs in jute_prod_bm_quality_dtl (§A.4). For a
composite quality the server loads the active components, passes them into
compute_beaming_daily for the Σ_n kg_per_cut, and stores ends = SUM(component ends) and
std_count = NULL on the snapshot. A composite quality with no active component is a data
integrity error (HTTP 400). Simple (is_composite=0) qualities use the single master pair.

Upsert app-uniqueness: (co_id, tran_date, spell_id, machine_id, item_id, bm_quality_id,
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
from src.juteProduction.constants import BEAMING_MACHINE_TYPE_NAME
from src.juteProduction.beaming_query import (
    get_beaming_daily_active_row_query,
    get_beaming_eb_list_query,
    get_beaming_entries_by_date_query,
    get_beaming_entry_machines_query,
    get_beaming_entry_qualities_query,
    get_beaming_idle_hours_query,
    get_beaming_plan_driver_query,
    get_beaming_spells_query,
    get_bm_quality_components_query,
    insert_beaming_daily_query,
    soft_delete_beaming_daily_query,
    update_beaming_daily_query,
)
from src.juteProduction.services.beaming_rules import compute_beaming_daily
from src.juteProduction.services.beaming_standards import resolve_machine_standards


router = APIRouter()

QUALITY_NOT_FOUND_MSG = "Beaming quality not found"
QUALITY_ITEM_MISMATCH_MSG = "Selected quality does not belong to the chosen item"
COMPOSITE_NO_COMPONENTS_MSG = (
    "Composite beaming quality has no active components (jute_prod_bm_quality_dtl); "
    "fix the quality master before entering production."
)
ENTRY_NOT_FOUND_MSG = "Beaming entry not found"


# =============================================================================
# Pydantic models
# =============================================================================


class BeamingEntryCreate(BaseModel):
    co_id: int
    branch_id: Optional[int] = None  # derived from machine on insert
    tran_date: date
    spell_id: int
    machine_id: int
    eb_id: Optional[int] = None
    item_id: int
    bm_quality_id: int
    beam_no: Optional[str] = None  # physical beam number holding material (Q10)
    act_cuts: int = Field(gt=0)
    no_of_beam: int = Field(gt=0)
    # rpm_roller is NO LONGER a production input — the ACTUAL roller speed is entered on the
    # future Beaming SQC page (tab, like Spinning SQC), not here. act_speed = 0 until then.
    # dia_roller is NO LONGER an input (Q7) — it is a machine-linked STANDARD resolved
    # server-side and stored in the dia_roller column.


class BeamingEntryUpdate(BaseModel):
    spell_id: Optional[int] = None
    machine_id: Optional[int] = None
    eb_id: Optional[int] = None
    item_id: Optional[int] = None
    bm_quality_id: Optional[int] = None
    beam_no: Optional[str] = None
    act_cuts: Optional[int] = Field(default=None, gt=0)
    no_of_beam: Optional[int] = Field(default=None, gt=0)
    # rpm_roller is NOT a production input — entered later on the Beaming SQC page (tab,
    # like Spinning SQC), so it is not editable here. dia_roller resolved from the standard
    # (Q7) — not an editable input either.


class PlanningGridRow(BaseModel):
    """One per-machine/per-quality row to persist into jute_prod_beaming_daily.

    Identity (spell/machine/item/quality) and the genuine entry inputs (beam_no, act_cuts,
    no_of_beam, eb_id) are the only fields the server reads. rpm_roller is NO LONGER a
    production input — the ACTUAL roller speed is entered on the future Beaming SQC page
    (tab, like Spinning SQC), so any rpm_roller the client sends is IGNORED here (kept only
    for FE-payload backward-compat). dia_roller is likewise NO LONGER a client input (Q7) —
    it is resolved server-side from the machine standard; any dia_roller the client sends is
    IGNORED. The resolved/computed fields below (ends, std_count, act_eff, kg_*, *_prod, ...)
    are ACCEPTED for backward-compatibility with the FE preview payload but are IGNORED on
    save — the server re-resolves standards and recomputes every derived column (SPEC
    §C.2/§C.5). They default to 0 so a sparse payload still validates.
    """

    spell_id: int
    machine_id: int
    item_id: int
    bm_quality_id: int
    eb_id: Optional[int] = None
    beam_no: Optional[str] = None
    act_cuts: int = Field(default=0, ge=0)
    no_of_beam: int = Field(default=0, ge=0)
    rpm_roller: float = Field(default=0.0, ge=0)  # accepted for BC, IGNORED on save (SQC seam)
    dia_roller: float = Field(default=0.0, ge=0)  # accepted for BC, IGNORED on save (Q7)
    ends: float = Field(default=0.0)
    std_count: float = Field(default=0.0)
    act_count: float = Field(default=0.0)
    laid_length: float = Field(default=0.0)
    std_cuts_per_beam: float = Field(default=0.0)
    std_speed: float = Field(default=0.0)
    target_speed: float = Field(default=0.0)
    act_speed: float = Field(default=0.0)
    std_eff: float = Field(default=0.0)
    target_eff: float = Field(default=0.0)
    working_hours: float = Field(default=0.0)
    yards_per_beam: float = Field(default=0.0)
    kg_per_cut: float = Field(default=0.0)
    kg_per_beam: float = Field(default=0.0)
    p100prod: float = Field(default=0.0)
    std_prod: float = Field(default=0.0)
    target_prod: float = Field(default=0.0)
    act_prod_kg: float = Field(default=0.0)
    act_prod_yards: float = Field(default=0.0)
    act_eff: float = Field(default=0.0)


class PlanningGridSave(BaseModel):
    co_id: int
    branch_id: Optional[int] = None
    tran_date: date
    rows: List[PlanningGridRow] = Field(default_factory=list)


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


def _derive_branch_id(db: Session, machine_id: int) -> Optional[int]:
    """Branch from the machine's department (machine_mst.dept_id -> dept_mst.branch_id).

    Clone of spreader_entry.py:186-200 so a new row is never silently NULL when the
    client omits branch_id.
    """
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


def _spell_working_hours(db: Session, spell_id: int) -> float:
    """Gross spell_mst.working_hours for a spell_id (status = 1). 0.0 when unknown.

    This is the GROSS shift duration; net working_hours subtracts idle (stoppage) hours
    via :func:`_idle_hours` (Q8).
    """
    row = db.execute(
        text(
            """
            SELECT working_hours
            FROM spell_mst
            WHERE spell_id = :spell_id AND status = 1
            """
        ),
        {"spell_id": int(spell_id)},
    ).fetchone()
    return _f(row.working_hours) if row else 0.0


def _idle_hours(db: Session, co_id: int, machine_id: int, tran_date, spell_id: int) -> float:
    """Σ active jute_prod_stoppage_hours for (co_id, machine_id, tran_date, spell_id) (Q8).

    0.0 when no stoppage rows exist. Net working_hours = max(0, gross − idle).
    """
    row = db.execute(
        get_beaming_idle_hours_query(),
        {
            "co_id": int(co_id),
            "machine_id": int(machine_id),
            "tran_date": tran_date,
            "spell_id": int(spell_id),
        },
    ).fetchone()
    return _f(row.idle_hours) if row else 0.0


def _net_working_hours(
    db: Session, co_id: int, machine_id: int, tran_date, spell_id: int
) -> float:
    """Net working_hours = max(0, gross spell working_hours − idle_hours) (Q8)."""
    gross = _spell_working_hours(db, spell_id)
    idle = _idle_hours(db, co_id, machine_id, tran_date, spell_id)
    return max(0.0, gross - idle)


def _composite_components(db: Session, bm_quality_id: int) -> List[Dict[str, Any]]:
    """Active warp components ({ends, count}) for a composite quality (Q3 / §A.4).

    Returns the (ends, count) pairs ordered by component_no from jute_prod_bm_quality_dtl
    for the Σ_n kg_per_cut path. Empty list when the quality has no active components
    (the caller treats this as a data-integrity error for a composite quality).
    """
    rows = db.execute(
        get_bm_quality_components_query(),
        {"bm_quality_id": int(bm_quality_id)},
    ).fetchall()
    components: List[Dict[str, Any]] = []
    for r in rows:
        m = dict(r._mapping)
        components.append(
            {
                "ends": _f(m.get("ends")),
                "count": _f(m.get("count")),
            }
        )
    return components


def _fetch_quality(db: Session, co_id: int, bm_quality_id: int):
    """Active jute_prod_bm_quality row (Page A) for std/ends resolution + guards.

    Scoped by co_id so a quality from another company can't be referenced. Returns the
    SQLAlchemy row (item_id, ends, std_count, is_composite) or None.
    """
    return db.execute(
        text(
            """
            SELECT bm_quality_id, item_id, ends, std_count, is_composite
            FROM jute_prod_bm_quality
            WHERE bm_quality_id = :bm_quality_id
              AND co_id = :co_id
              AND active = 1
            """
        ),
        {"bm_quality_id": int(bm_quality_id), "co_id": int(co_id)},
    ).fetchone()


def _resolve_snapshot(
    db: Session,
    co_id: int,
    machine_id: int,
    item_id: int,
    bm_quality_id: int,
    tran_date,
    spell_id: int,
    inputs: dict,
) -> Dict[str, Any]:
    """Resolve standards (Page A + Page B + spell) and compute the §3 derived columns.

    Validates the quality (exists, belongs to the chosen item), then resolves:
      * SIMPLE quality (is_composite=0): the quality-linked ends/std_count.
      * COMPOSITE quality (is_composite=1, Q3): the active warp components from
        jute_prod_bm_quality_dtl — ends = SUM(component ends), std_count = NULL, and the
        (ends, count) pairs flow into compute_beaming_daily for the Σ_n kg_per_cut. A
        composite quality with no active component is a data-integrity error (400).
      * dia (Q7): machine-linked STANDARD (standards['dia']) — NOT an input — folded into
        act_speed and stored in the dia_roller column.
      * rpm (SQC seam): NOT a production input — sourced from the future Beaming SQC page
        (tab, like Spinning SQC). ``inputs`` carries no rpm here, so act_speed = 0 until SQC
        is wired (the rpm_roller/act_speed columns stay on the row for SQC to populate).
      * working_hours (Q8): net = max(0, gross spell working_hours − idle_hours).

    Returns ``{standards: {...}, computed: {...}}`` ready for the snapshot insert/update.
    Raises HTTPException(400/404) on validation failure.
    """
    quality = _fetch_quality(db, co_id, bm_quality_id)
    if not quality:
        raise HTTPException(status_code=404, detail=QUALITY_NOT_FOUND_MSG)
    if int(quality.item_id) != int(item_id):
        raise HTTPException(status_code=400, detail=QUALITY_ITEM_MISMATCH_MSG)

    # Standards now span TWO dimensions: machine-linked (speed/dia) AND quality-linked
    # (laid_length/cuts_per_beam/eff) — so the resolver needs the bm_quality_id (qid ref).
    machine_std = resolve_machine_standards(
        db, co_id, machine_id, bm_quality_id, tran_date
    )
    working_hours = _net_working_hours(db, co_id, machine_id, tran_date, spell_id)

    is_composite = bool(quality.is_composite) and int(quality.is_composite) == 1
    if is_composite:
        # Composite (Q3): real (ends, count) pairs live in jute_prod_bm_quality_dtl.
        components = _composite_components(db, bm_quality_id)
        if not components:
            raise HTTPException(status_code=400, detail=COMPOSITE_NO_COMPONENTS_MSG)
        ends = sum(c["ends"] for c in components)
        std_count = None  # parent std_count is NULL for a composite quality
        act_count = None  # compute reuses per-component counts (Q5)
    else:
        components = None
        ends = _f(quality.ends)
        std_count = _f(quality.std_count)
        # act_count defaults to std_count (SQC override deferred §12 Q5).
        act_count = std_count

    standards = {
        "ends": ends,
        "std_count": std_count,
        "act_count": act_count,
        "laid_length": machine_std["laid_length"],
        "std_cuts_per_beam": machine_std["cuts_per_beam"],
        # std_speed / target_speed are RPMs (machine 'speed' param); compute_beaming_daily
        # converts them to SURFACE speeds (rpm × dia × π/36) and returns those.
        "std_speed": machine_std["std_speed"],
        "target_speed": machine_std["target_speed"],
        # act_rpm (LOCKED CONTRACT): actual RPM from value_role='actual' (Beaming SQC page);
        # 0.0 until SQC is entered, so the computed act_speed (surface) is 0 until then.
        "act_rpm": machine_std.get("act_rpm", 0.0),
        "std_eff": machine_std["std_eff"],
        "target_eff": machine_std["target_eff"],
        "working_hours": working_hours,
        # dia is a machine-linked STANDARD (Q7), not an entry input.
        "dia": machine_std["dia"],
        # Composite Σ_n components (None for a simple quality).
        "components": components,
    }
    computed = compute_beaming_daily(inputs, standards)
    return {"standards": standards, "computed": computed}


def _snapshot_params(
    co_id: int,
    branch_id: Optional[int],
    tran_date,
    spell_id: int,
    machine_id: int,
    item_id: int,
    bm_quality_id: int,
    eb_id: Optional[int],
    beam_no: Optional[str],
    inputs: dict,
    standards: dict,
    computed: dict,
    user_id,
) -> Dict[str, Any]:
    """Flat bind dict for insert_beaming_daily_query / update_beaming_daily_query.

    dia_roller is the resolved machine STANDARD (standards['dia'], Q7) — not an input.
    std_count is NULL for a composite quality (Q3); act_count likewise reuses the
    per-component counts there, so both pass through as None for composite.

    rpm_roller / act_speed (SQC seam): production entry supplies NO rpm (it is entered on
    the future Beaming SQC page, like Spinning SQC), so rpm_roller binds NULL and the
    computed act_speed is 0 until SQC is wired. The binds are kept so the SQC page can
    UPDATE these columns on the daily row.
    """
    std_count = standards.get("std_count")
    act_count = standards.get("act_count")
    dia = standards.get("dia")
    # act_rpm is the server-resolved ACTUAL roller RPM (value_role='actual', Beaming SQC).
    # It is stored in the rpm_roller column (NULL/0 until SQC writes the actual speed).
    act_rpm = standards.get("act_rpm")
    return {
        "co_id": int(co_id),
        "branch_id": _i(branch_id),
        "tran_date": tran_date,
        "spell_id": int(spell_id),
        "machine_id": int(machine_id),
        "item_id": int(item_id),
        "bm_quality_id": int(bm_quality_id),
        "eb_id": _i(eb_id),
        "beam_no": beam_no if beam_no else None,
        "act_cuts": int(inputs["act_cuts"]),
        "no_of_beam": int(inputs["no_of_beam"]),
        # rpm_roller stores the resolved ACTUAL roller RPM (standards['act_rpm']), sourced
        # from the Beaming SQC actual role as-of tran_date; NULL until SQC is entered (the
        # computed act_speed below is then 0). NOT a production-entry input (SQC seam).
        "rpm_roller": None if act_rpm in (None, 0, 0.0) else float(act_rpm),
        # dia_roller stores the server-resolved machine standard (Q7), not a client input.
        "dia_roller": None if dia is None else float(dia),
        "ends": None if standards.get("ends") is None else int(standards["ends"]),
        "std_count": None if std_count is None else float(std_count),
        "act_count": None if act_count is None else float(act_count),
        "laid_length": _f(standards.get("laid_length")),
        "std_cuts_per_beam": _f(standards.get("std_cuts_per_beam")),
        # std_speed / target_speed / act_speed are the COMPUTED SURFACE speeds (yd/min =
        # rpm × dia × π/36), NOT the raw RPMs in standards (LOCKED CONTRACT).
        "std_speed": _f(computed.get("std_speed")),
        "target_speed": _f(computed.get("target_speed")),
        "act_speed": _f(computed.get("act_speed")),
        "std_eff": _f(standards.get("std_eff")),
        "target_eff": _f(standards.get("target_eff")),
        "working_hours": _f(standards.get("working_hours")),
        "yards_per_beam": _f(computed.get("yards_per_beam")),
        "kg_per_cut": _f(computed.get("kg_per_cut")),
        "kg_per_beam": _f(computed.get("kg_per_beam")),
        "p100prod": _f(computed.get("p100prod")),
        "std_prod": _f(computed.get("std_prod")),
        "target_prod": _f(computed.get("target_prod")),
        "act_prod_kg": _f(computed.get("act_prod_kg")),
        "act_prod_yards": _f(computed.get("act_prod_yards")),
        "act_eff": _f(computed.get("act_eff")),
        "updated_by": user_id,
    }


def _serialize_entry_row(row) -> Dict[str, Any]:
    """dict(_mapping) with Decimal -> float and date -> str for JSON safety."""
    m = dict(row._mapping)
    float_cols = (
        "rpm_roller", "dia_roller", "std_count", "act_count", "laid_length",
        "std_cuts_per_beam", "std_speed", "target_speed", "act_speed", "std_eff",
        "target_eff", "working_hours", "yards_per_beam", "kg_per_cut", "kg_per_beam",
        "p100prod", "std_prod", "target_prod", "act_prod_kg", "act_prod_yards", "act_eff",
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
    """Lookups for the entry form: Beaming machines, spells, eb list, items+qualities."""
    co_id = _require_co_id(request)
    branch_id = _optional_branch_id(request)
    try:
        machines = [
            dict(r._mapping)
            for r in db.execute(
                get_beaming_entry_machines_query(),
                {"beaming_type": BEAMING_MACHINE_TYPE_NAME, "branch_id": branch_id},
            ).fetchall()
        ]

        # spell_mst filters status = 1 (SPEC §9); de-dup by spell_code (branch fanout).
        spells = []
        seen = set()
        for r in db.execute(get_beaming_spells_query(), {"branch_id": branch_id}).fetchall():
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
            for r in db.execute(get_beaming_eb_list_query(), {"branch_id": branch_id}).fetchall()
        ]

        qualities = []
        items_seen: Dict[int, Dict[str, Any]] = {}
        for r in db.execute(
            get_beaming_entry_qualities_query(), {"co_id": co_id, "item_id": None}
        ).fetchall():
            m = dict(r._mapping)
            if m.get("std_count") is not None:
                m["std_count"] = float(m["std_count"])
            qualities.append(m)
            iid = m.get("item_id")
            if iid is not None and int(iid) not in items_seen:
                items_seen[int(iid)] = {
                    "item_id": int(iid),
                    "item_code": m.get("item_code"),
                    "item_name": m.get("item_name"),
                }
        items = list(items_seen.values())

        return {
            "data": {
                "machines": machines,
                "spells": spells,
                "eb_list": eb,
                "items": items,
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
    """Raw beaming-daily entries for a tran_date (optional spell_id, machine_id)."""
    co_id = _require_co_id(request)
    branch_id = _optional_branch_id(request)
    d = request.query_params.get("tran_date")
    if not d:
        raise HTTPException(status_code=400, detail="tran_date is required")
    spell_raw = request.query_params.get("spell_id")
    machine_raw = request.query_params.get("machine_id")
    try:
        d_val = date.fromisoformat(d)
        spell_id = int(spell_raw) if spell_raw else None
        machine_id = int(machine_raw) if machine_raw else None
        rows = db.execute(
            get_beaming_entries_by_date_query(),
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
        raise HTTPException(status_code=400, detail="Invalid tran_date, spell_id or machine_id")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/machine_standards")
def machine_standards(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Resolve a machine+quality's standard/target params as-of tran_date (LAST-DATE).

    Lets the entry form prefill act_cuts with the QUALITY's std cuts/beam (and read
    laid_length/eff from the quality + dia/speed from the machine) before save. Standards
    now span two dimensions, so the QUALITY-linked params (laid_length/cuts_per_beam/eff)
    resolve from the bm_quality_id (qid) and the MACHINE-linked params (speed/dia) from
    machine_id (mcid). Both query params are OPTIONAL: machine_id may be 0/None when the
    FE only needs the quality-linked std cuts/beam, and bm_quality_id may be omitted when
    only machine params are needed. Returns 0.0 for any param with no active target-map
    row. ``std_cuts_per_beam`` is an alias of ``cuts_per_beam`` (now qid-resolved) for the
    FE act-cuts default.
    """
    co_id = _require_co_id(request)
    machine_raw = request.query_params.get("machine_id")
    quality_raw = request.query_params.get("bm_quality_id")
    d = request.query_params.get("tran_date")
    if not d:
        raise HTTPException(status_code=400, detail="tran_date is required")
    try:
        # machine_id is optional (0/None when only quality-linked params are needed);
        # guard int parsing so an absent/empty value resolves the machine params to 0.0.
        machine_id = int(machine_raw) if machine_raw else 0
        bm_quality_id = int(quality_raw) if quality_raw else None
        d_val = date.fromisoformat(d)
        std = resolve_machine_standards(db, co_id, machine_id, bm_quality_id, d_val)
        std["std_cuts_per_beam"] = std.get("cuts_per_beam")
        return {"data": std}
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(
            status_code=400, detail="Invalid machine_id, bm_quality_id or tran_date"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Endpoints — CRUD (server resolves standards + computes the snapshot)
# =============================================================================


@router.post("/entry_create")
def entry_create(
    body: BeamingEntryCreate,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Create (or upsert) one per-machine/per-quality entry, server-computed.

    Resolves ends/std_count (Page A), the machine standards (Page B, as-of tran_date) and
    spell working_hours, computes §3, then upserts the full snapshot keyed by
    (co_id, tran_date, spell_id, machine_id, item_id, bm_quality_id, active=1).
    """
    try:
        # dia_roller is resolved server-side (Q7). rpm is NOT a production input — it is
        # entered on the future Beaming SQC page (tab, like Spinning SQC), so no rpm is
        # passed here and act_speed computes to 0 until SQC is wired (SQC seam).
        inputs = {
            "act_cuts": int(body.act_cuts),
            "no_of_beam": int(body.no_of_beam),
        }
        resolved = _resolve_snapshot(
            db,
            body.co_id,
            body.machine_id,
            body.item_id,
            body.bm_quality_id,
            body.tran_date,
            body.spell_id,
            inputs,
        )

        branch_id = body.branch_id
        if branch_id is None:
            branch_id = _derive_branch_id(db, body.machine_id)

        user_id = token_data.get("user_id")
        params = _snapshot_params(
            body.co_id,
            branch_id,
            body.tran_date,
            body.spell_id,
            body.machine_id,
            body.item_id,
            body.bm_quality_id,
            body.eb_id,
            body.beam_no,
            inputs,
            resolved["standards"],
            resolved["computed"],
            user_id,
        )

        existing = db.execute(
            get_beaming_daily_active_row_query(),
            {
                "co_id": int(body.co_id),
                "tran_date": body.tran_date,
                "spell_id": int(body.spell_id),
                "machine_id": int(body.machine_id),
                "item_id": int(body.item_id),
                "bm_quality_id": int(body.bm_quality_id),
            },
        ).fetchone()
        if existing:
            params["id"] = existing.beaming_daily_id
            db.execute(update_beaming_daily_query(), params)
            beaming_daily_id = int(existing.beaming_daily_id)
        else:
            result = db.execute(insert_beaming_daily_query(), params)
            beaming_daily_id = int(result.lastrowid)
        db.commit()
        return {"data": {"beaming_daily_id": beaming_daily_id, "computed": resolved["computed"]}}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/entry_edit/{entry_id}")
def entry_edit(
    entry_id: int,
    body: BeamingEntryUpdate,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Edit one entry's inputs and re-resolve + recompute the full snapshot.

    Any omitted field keeps its existing value; the standards/computed columns are always
    recomputed from the resulting (machine, quality, spell, tran_date) so the stored
    snapshot stays internally consistent: dia is re-resolved from the machine standard
    (Q7), working_hours nets out idle/stoppage hours (Q8), and a composite quality folds
    in its jute_prod_bm_quality_dtl components (Q3). The item-mismatch guard re-runs.
    """
    co_id = _require_co_id(request)
    try:
        existing = db.execute(
            text(
                """
                SELECT beaming_daily_id, co_id, branch_id, tran_date, spell_id,
                       machine_id, item_id, bm_quality_id, eb_id, beam_no,
                       act_cuts, no_of_beam, rpm_roller, dia_roller
                FROM jute_prod_beaming_daily
                WHERE beaming_daily_id = :id AND co_id = :co_id AND active = 1
                """
            ),
            {"id": entry_id, "co_id": co_id},
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail=ENTRY_NOT_FOUND_MSG)

        spell_id = _i(body.spell_id, int(existing.spell_id))
        machine_id = _i(body.machine_id, int(existing.machine_id))
        item_id = _i(body.item_id, int(existing.item_id))
        bm_quality_id = _i(body.bm_quality_id, int(existing.bm_quality_id))
        eb_id = body.eb_id if body.eb_id is not None else _i(existing.eb_id)
        beam_no = body.beam_no if body.beam_no is not None else existing.beam_no
        act_cuts = _i(body.act_cuts, int(existing.act_cuts))
        no_of_beam = _i(body.no_of_beam, int(existing.no_of_beam))

        # dia_roller is no longer an input (Q7); _resolve_snapshot re-resolves it from the
        # machine standard for the (possibly changed) machine/tran_date. rpm is NOT a
        # production input either: the ACTUAL roller RPM is the value_role='actual' speed,
        # re-resolved server-side inside _resolve_snapshot (standards['act_rpm']) as-of
        # tran_date — so a production edit reflects the current SQC value and never reads it
        # from the request body. inputs therefore carries NO rpm (LOCKED CONTRACT).
        inputs = {
            "act_cuts": int(act_cuts),
            "no_of_beam": int(no_of_beam),
        }
        resolved = _resolve_snapshot(
            db,
            co_id,
            machine_id,
            item_id,
            bm_quality_id,
            existing.tran_date,
            spell_id,
            inputs,
        )

        # Re-derive branch from the (possibly changed) machine; keep existing if not found.
        branch_id = _derive_branch_id(db, machine_id)
        if branch_id is None:
            branch_id = _i(existing.branch_id)

        user_id = token_data.get("user_id")
        params = _snapshot_params(
            co_id,
            branch_id,
            existing.tran_date,
            spell_id,
            machine_id,
            item_id,
            bm_quality_id,
            eb_id,
            beam_no,
            inputs,
            resolved["standards"],
            resolved["computed"],
            user_id,
        )
        params["id"] = entry_id
        db.execute(update_beaming_daily_query(), params)
        db.commit()
        return {"data": {"message": "Updated", "computed": resolved["computed"]}}
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
    """Soft-delete (active=0) one beaming-daily entry."""
    co_id = _require_co_id(request)
    try:
        existing = db.execute(
            text(
                """
                SELECT beaming_daily_id
                FROM jute_prod_beaming_daily
                WHERE beaming_daily_id = :id AND co_id = :co_id AND active = 1
                """
            ),
            {"id": entry_id, "co_id": co_id},
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail=ENTRY_NOT_FOUND_MSG)

        user_id = token_data.get("user_id")
        db.execute(
            soft_delete_beaming_daily_query(), {"id": entry_id, "updated_by": user_id}
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
# Planning grid (jute_prod_beaming_daily) — server-computed, per machine+quality
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
    """Server-computed planning grid for a tran_date (optional spell_id).

    Driver rows are the active jute_prod_beaming_daily snapshots; standards re-resolve
    from the time-versioned target map (LAST-DATE, as-of tran_date) and the §3 formulas
    recompute per row so the grid always reflects current masters. dia is re-resolved from
    the machine standard (Q7) and working_hours nets out idle/stoppage hours (Q8).
    Composite qualities (is_composite=1) fold in their jute_prod_bm_quality_dtl components
    for the Σ_n kg_per_cut (Q3; ends = SUM(component ends), std_count NULL) — a composite
    quality with no active component is surfaced with zeroed computed columns rather than
    failing the whole grid. A per-(machine,item,quality,shift) rollup mirrors the Spinning
    grid (SUM numerator / SUM denominator, never the average of effs).
    """
    co_id = _require_co_id(request)
    branch_id = _optional_branch_id(request)
    d = request.query_params.get("tran_date")
    if not d:
        raise HTTPException(status_code=400, detail="tran_date is required")
    spell_raw = request.query_params.get("spell_id")
    try:
        d_val = date.fromisoformat(d)
        spell_id = int(spell_raw) if spell_raw else None

        driver = db.execute(
            get_beaming_plan_driver_query(),
            {
                "co_id": co_id,
                "tran_date": d_val,
                "spell_id": spell_id,
                "beaming_type": BEAMING_MACHINE_TYPE_NAME,
                "branch_id": branch_id,
            },
        ).fetchall()

        rows: List[Dict[str, Any]] = []
        for r in driver:
            m = dict(r._mapping)
            machine_id = int(m["machine_id"])
            row_spell_id = int(m["spell_id"])
            row_bm_quality_id = int(m["bm_quality_id"])
            spell_code = m.get("spell_code")
            is_composite = bool(m.get("is_composite"))

            # dia_roller is resolved server-side (Q7). rpm is NOT a production input — the
            # ACTUAL roller RPM is the value_role='actual' speed resolved server-side (below,
            # via resolve_machine_standards), NOT the persisted column. inputs carries NO rpm
            # (act_speed comes from standards['act_rpm'] inside compute, 0 until SQC entered).
            inputs = {
                "act_cuts": _i(m.get("act_cuts"), 0),
                "no_of_beam": _i(m.get("no_of_beam"), 0),
            }

            # Quality-linked (laid_length/cuts_per_beam/eff) + machine-linked (speed/dia)
            # standards both resolve per row — pass the row's bm_quality_id as the qid ref.
            machine_std = resolve_machine_standards(
                db, co_id, machine_id, row_bm_quality_id, d_val
            )
            # Net working hours: gross spell hours minus idle/stoppage hours (Q8).
            working_hours = _net_working_hours(db, co_id, machine_id, d_val, row_spell_id)

            if is_composite:
                # Composite (Q3): real (ends, count) pairs from jute_prod_bm_quality_dtl.
                components = _composite_components(db, int(m["bm_quality_id"]))
                ends = sum(c["ends"] for c in components) if components else 0.0
                std_count = None
                act_count = None
            else:
                components = None
                ends = _f(m.get("ends"))
                std_count = _f(m.get("std_count"))
                act_count = std_count
            standards = {
                "ends": ends,
                "std_count": std_count,
                "act_count": act_count,
                "laid_length": machine_std["laid_length"],
                "std_cuts_per_beam": machine_std["cuts_per_beam"],
                # std_speed / target_speed are RPMs; compute converts to SURFACE speeds.
                "std_speed": machine_std["std_speed"],
                "target_speed": machine_std["target_speed"],
                # act_rpm: actual RPM (value_role='actual', Beaming SQC); 0 until entered.
                "act_rpm": machine_std.get("act_rpm", 0.0),
                "std_eff": machine_std["std_eff"],
                "target_eff": machine_std["target_eff"],
                "working_hours": working_hours,
                # dia is a machine-linked STANDARD (Q7), not an entry input.
                "dia": machine_std["dia"],
                "components": components,
            }
            # A composite quality with no active component can't compute a Σ_n kg_per_cut;
            # surface zeroed computed columns rather than failing the whole grid (Q3).
            if is_composite and not components:
                computed = {
                    "yards_per_beam": 0.0, "kg_per_cut": 0.0, "kg_per_beam": 0.0,
                    "p100prod": 0.0, "std_prod": 0.0, "target_prod": 0.0,
                    "act_prod_yards": 0.0, "act_prod_kg": 0.0,
                    "std_speed": 0.0, "target_speed": 0.0, "act_speed": 0.0,
                    "act_eff": 0.0,
                }
            else:
                computed = compute_beaming_daily(inputs, standards)

            rows.append(
                {
                    "beaming_daily_id": int(m["beaming_daily_id"]),
                    "spell_id": row_spell_id,
                    "spell_code": spell_code,
                    "shift_bucket": _shift_bucket(spell_code),
                    "machine_id": machine_id,
                    "mech_code": m.get("mech_code"),
                    "machine_name": m.get("machine_name"),
                    "branch_id": m.get("branch_id"),
                    "item_id": int(m["item_id"]),
                    "item_code": m.get("item_code"),
                    "item_name": m.get("item_name"),
                    "bm_quality_id": int(m["bm_quality_id"]),
                    "bm_quality_code": m.get("bm_quality_code"),
                    "bm_quality_name": m.get("bm_quality_name"),
                    "eb_id": _i(m.get("eb_id")),
                    "beam_no": m.get("beam_no"),
                    "act_cuts": inputs["act_cuts"],
                    "no_of_beam": inputs["no_of_beam"],
                    # rpm_roller is the resolved ACTUAL roller RPM (standards['act_rpm'],
                    # value_role='actual', Beaming SQC); NULL until SQC entered (SQC seam).
                    "rpm_roller": None if not standards.get("act_rpm") else float(standards["act_rpm"]),
                    # dia_roller now reflects the resolved machine standard (Q7).
                    "dia_roller": standards["dia"],
                    "is_composite": is_composite,
                    "ends": standards["ends"],
                    "std_count": standards["std_count"],
                    "act_count": standards["act_count"],
                    "laid_length": standards["laid_length"],
                    "std_cuts_per_beam": standards["std_cuts_per_beam"],
                    # SURFACE speeds (yd/min) from compute, NOT the raw RPMs in standards.
                    "std_speed": computed.get("std_speed", 0.0),
                    "target_speed": computed.get("target_speed", 0.0),
                    "act_speed": computed["act_speed"],
                    "std_eff": standards["std_eff"],
                    "target_eff": standards["target_eff"],
                    "working_hours": standards["working_hours"],
                    "yards_per_beam": computed["yards_per_beam"],
                    "kg_per_cut": computed["kg_per_cut"],
                    "kg_per_beam": computed["kg_per_beam"],
                    "p100prod": computed["p100prod"],
                    "std_prod": computed["std_prod"],
                    "target_prod": computed["target_prod"],
                    "act_prod_yards": computed["act_prod_yards"],
                    "act_prod_kg": computed["act_prod_kg"],
                    "act_eff": computed["act_eff"],
                }
            )

        # Shift rollup per (machine, item, quality, shift_bucket): SUM(num)/SUM(denom).
        roll: Dict[tuple, Dict[str, Any]] = {}
        for row in rows:
            key = (
                row["machine_id"],
                row["item_id"],
                row["bm_quality_id"],
                row["shift_bucket"],
            )
            agg = roll.setdefault(
                key,
                {
                    "machine_id": row["machine_id"],
                    "mech_code": row.get("mech_code"),
                    "machine_name": row.get("machine_name"),
                    "item_id": row["item_id"],
                    "item_code": row.get("item_code"),
                    "bm_quality_id": row["bm_quality_id"],
                    "bm_quality_code": row.get("bm_quality_code"),
                    "shift_bucket": row["shift_bucket"],
                    "act_prod_yards": 0.0,
                    "act_prod_kg": 0.0,
                    "_p100": 0.0,
                },
            )
            agg["act_prod_yards"] += row["act_prod_yards"]
            agg["act_prod_kg"] += row["act_prod_kg"]
            agg["_p100"] += row["p100prod"]

        shift_rollup = []
        for agg in roll.values():
            p100 = agg.pop("_p100")
            agg["act_prod_yards"] = round(agg["act_prod_yards"], 3)
            agg["act_prod_kg"] = round(agg["act_prod_kg"], 3)
            agg["act_eff"] = round(agg["act_prod_yards"] / p100 * 100, 2) if p100 else 0.0
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
    """Batch upsert per-machine/per-quality planning rows into jute_prod_beaming_daily.

    SERVER-AUTHORITATIVE (mirrors entry_create, SPEC §C.2/§C.5): for EACH row the server
    re-fetches the quality (co_id-scoped), enforces the item-mismatch guard, resolves the
    machine standards as-of tran_date (incl. dia, Q7) + the NET spell working_hours
    (gross − idle/stoppage hours, Q8), defaults act_count to std_count (or folds in the
    jute_prod_bm_quality_dtl components for a composite quality, Q3), and recomputes the
    full snapshot via compute_beaming_daily. The client may supply ONLY the genuine inputs
    (beam_no, act_cuts, no_of_beam, eb_id); rpm_roller (the ACTUAL roller speed, set later by
    the future Beaming SQC page — tab, like Spinning SQC — SQC seam), dia_roller and every
    resolved/computed field it sends is DISCARDED and replaced by the server values, so a
    client can neither bypass the server compute nor fabricate efficiency/weight numbers.
    With no rpm supplied, act_speed computes to 0 until SQC is wired.

    App-uniqueness is (co_id, tran_date, spell_id, machine_id, item_id, bm_quality_id,
    active=1): an existing active row is updated, otherwise a fresh one is inserted.
    branch_id is derived from the machine when the row omits it (never silently NULL).
    The whole batch is one transaction: a composite quality with no active component (or
    any error) mid-batch 400s and rolls back the entire save (consistent with entry_create).
    """
    try:
        user_id = token_data.get("user_id")
        saved = 0
        for e in body.rows:
            # Keep ONLY the genuine inputs from the client; discard any computed columns,
            # the client-sent dia_roller (resolved server-side, Q7) and rpm_roller (the
            # ACTUAL roller speed is set on the future Beaming SQC page, not production
            # entry — SQC seam). With no rpm passed, act_speed computes to 0 until SQC wires.
            inputs = {
                "act_cuts": int(e.act_cuts),
                "no_of_beam": int(e.no_of_beam),
            }
            # Server resolves standards + computes the snapshot (composite/mismatch guard).
            resolved = _resolve_snapshot(
                db,
                body.co_id,
                e.machine_id,
                e.item_id,
                e.bm_quality_id,
                body.tran_date,
                e.spell_id,
                inputs,
            )

            branch_id = body.branch_id
            if branch_id is None:
                branch_id = _derive_branch_id(db, e.machine_id)

            params = _snapshot_params(
                body.co_id,
                branch_id,
                body.tran_date,
                e.spell_id,
                e.machine_id,
                e.item_id,
                e.bm_quality_id,
                e.eb_id,
                e.beam_no,
                inputs,
                resolved["standards"],
                resolved["computed"],
                user_id,
            )

            existing = db.execute(
                get_beaming_daily_active_row_query(),
                {
                    "co_id": int(body.co_id),
                    "tran_date": body.tran_date,
                    "spell_id": int(e.spell_id),
                    "machine_id": int(e.machine_id),
                    "item_id": int(e.item_id),
                    "bm_quality_id": int(e.bm_quality_id),
                },
            ).fetchone()
            if existing:
                params["id"] = existing.beaming_daily_id
                db.execute(update_beaming_daily_query(), params)
            else:
                db.execute(insert_beaming_daily_query(), params)
            saved += 1
        db.commit()
        return {"data": {"saved": saved}}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
