"""Winding production entry endpoints (jute production module).

Entry is **person-keyed** (``docs/winding-person-keyed-entry-spec.md``): winding
production is *person* production, not *machine* production. Three entry screens
share a Date + Spell + Winder (EB no) header (prefix ``/api/windingProd``):

* **Doff**    — one weighing (ONE trolly + ONE spool) may be SHARED by several
  winders: it writes one jute_prod_winding_doff row per winder. The tare is
  deducted exactly once — ``net_total = gross - trolly_wt - spool_wt`` — and that
  net is split equally across the selected winders (the last row absorbs the
  rounding remainder so the shares sum back to net_total); trolly_wt / spool_wt
  are stored in full on every row (they describe the shared trolly). Save gate:
  net_total > 0 and EACH ROW's share within [WINDING_NET_MIN, WINDING_NET_MAX].
  Still no machine and no no_of_machines. The rows of one weighing share a
  ``weighing_id`` (the first row's id), and edit + delete act on that GROUP —
  re-splitting or removing a single share would leave the survivors summing to a
  weighing that never happened, and the spinning planning grid (which sums
  production_qty per item + shift) would silently lose the difference.
* **Jugar**   — spindle leftover weight per person/spell. Opening and closing are
  ONE entry with two fields (no O/C selector): /jugar_state prefills both from
  what is stored, else from the previous spell's closing in spell-sequence order
  (earlier spell same day, else the last spell of an earlier date), and
  /jugar_save UPSERTS whichever sides the form posts — so an untouched carried
  opening still gets persisted, which is what makes it count in reconciliation.
  Bands differ per side: opening 0 <= w <= JUGAR_MAX (0 is legal — a spell can
  start with an empty spindle), closing 0 < w <= JUGAR_MAX. Lookups are BRANCH +
  person scoped.
* **Quality** — the person -> yarn-quality map (+ the winding machine and spindle
  count), auto-seeded by carrying the PERSONS of the previous spell forward with
  their machine; winders are added (/quality_add) and removed (/quality_delete) by
  hand. 1 <= spindle <= 30. This map is the ONLY place a machine is recorded —
  doff and jugar stay machine-free (decisions D3/D4).

The winder list comes from HRMS masters (``/workers``), never from attendance, so
entry never depends on an attendance sync, and it is deliberately NOT
designation-filtered (the mill's winding designations share no common prefix).

Mirrors spinning_entry.py for conventions: get_tenant_db + get_current_user_with_refresh,
{"data": ...} responses, _require_co_id / _optional_branch_id / _f / _i helpers, and
the try/except (GET: HTTPException raise / ValueError 400 / Exception 500;
POST/PUT/DELETE: db.rollback() then raise / 500) pattern. Spells resolve at the
boundary via spinning_entry._resolve_spell: spell_id (INT, preferred) validated
against its shift's branch, or the deprecated spell code fallback branch-scoped via
shift_mst — spell codes repeat per branch. The winding tables store spell_id, not
the spell_code string. Reconciled production is computed at READ time in
winding_reports.py — never persisted here. The production typo
trolly_mst.busket_weight is kept; responses alias it bucket_weight.
"""

from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from src.authorization.utils import get_current_user_with_refresh
from src.config.db import get_tenant_db
from src.juteProduction.constants import (
    JUGAR_MAX,
    JUGAR_MIN,
    SPINDLE_MAX,
    SPINDLE_MIN,
    WINDING_MACHINE_TYPE_NAME,
)
from src.juteProduction.services.winding_rules import (
    compute_winding_net,
    compute_winding_row_gross_wt,
    validate_winding_net,
)
from src.juteProduction.spinning_entry import (
    _optional_spell_id_param,
    _resolve_spell,
)
from src.juteProduction.spinning_query import (
    get_spells_query,
    get_yarn_qualities_query,
)
from src.juteProduction.winding_query import (
    auto_seed_quality_query,
    derive_branch_for_worker_query,
    get_doff_active_by_id_query,
    get_doff_by_date_query,
    get_doff_group_rows_query,
    get_doff_prev_state_query,
    get_jugar_active_by_id_query,
    get_jugar_by_date_query,
    get_jugar_prev_seq_query,
    get_jugar_saved_pair_query,
    get_quality_active_by_id_query,
    get_quality_by_date_query,
    get_quality_duplicate_query,
    get_quality_exists_query,
    get_quality_prev_seed_date_spell_query,
    get_winding_machines_query,
    get_winding_trollies_query,
    get_winding_trolly_query,
    get_winding_workers_query,
    insert_doff_row_query,
    insert_jugar_row_query,
    insert_quality_row_query,
    soft_delete_doff_group_query,
    soft_delete_quality_row_query,
    stamp_doff_weighing_id_query,
    update_doff_row_query,
    update_jugar_row_query,
    update_quality_row_query,
)


router = APIRouter()

DOFF_NOT_FOUND_MSG = "Winding doff entry not found"
JUGAR_NOT_FOUND_MSG = "Winding jugar entry not found"
QUALITY_NOT_FOUND_MSG = "Winding quality entry not found"
NET_GATE_MSG = "Computed net weight must be greater than 0"
NET_RANGE_MSG = "Net weight is out of the valid range (1..500 kg)"
DUP_QUALITY_MSG = "A quality entry already exists for this date/spell/winder"
UNKNOWN_WORKER_MSG = "Unknown eb_id - no active employee record"
WORKER_NO_BRANCH_MSG = (
    "This winder's HRMS record has no branch - winding rows are branch-scoped, "
    "set the employee's branch first"
)
OPEN_CLOSE_MSG = "open_close must be 'O' or 'C'"
SPINDLE_RANGE_MSG = f"no_of_spindle must be between {SPINDLE_MIN} and {SPINDLE_MAX}"
SPINDLE_ADD_RANGE_MSG = f"no_of_spindle must be between 0 and {SPINDLE_MAX}"
JUGAR_RANGE_MSG = f"weight must be greater than {JUGAR_MIN} and at most {JUGAR_MAX}"
# Opening may be exactly 0 — a winder can start a spell with nothing left on the
# spindle, and forcing a positive number there would fake carryover that is not there.
JUGAR_OPENING_RANGE_MSG = (
    f"opening weight must be at least {JUGAR_MIN} and at most {JUGAR_MAX}"
)

WORKER_LIMIT_DEFAULT = 200


# =============================================================================
# Pydantic models
# =============================================================================


class DoffCreate(BaseModel):
    co_id: int
    branch_id: Optional[int] = None
    tran_date: date
    spell: Optional[str] = None  # deprecated — send spell_id
    spell_id: Optional[int] = None  # preferred; exactly one of spell/spell_id
    eb_id: Optional[int] = None  # single winder (legacy shape)
    eb_ids: Optional[List[int]] = None  # winders sharing this weighing
    trolly_id: int
    spool_id: int
    quality_id: int
    gross_weight: float = Field(gt=0)

    @model_validator(mode="after")
    def _winder_required(self):
        """A winder is still mandatory — neither key given -> 422 (pydantic)."""
        if not self.eb_ids and self.eb_id is None:
            raise ValueError("eb_id or eb_ids is required")
        return self


class DoffUpdate(BaseModel):
    quality_id: Optional[int] = None
    trolly_id: Optional[int] = None
    spool_id: Optional[int] = None
    gross_weight: Optional[float] = Field(default=None, gt=0)


class JugarSave(BaseModel):
    """One winder's spindle leftover for a spell — BOTH ends in one payload.

    The form shows Opening and Closing as two fields (prefilled from
    /jugar_state), so a save upserts each side it was given. Omitting a side
    leaves that stored row untouched; at least one must be present.
    """

    co_id: int
    branch_id: Optional[int] = None
    tran_date: date
    spell: Optional[str] = None  # deprecated — send spell_id
    spell_id: Optional[int] = None  # preferred; exactly one of spell/spell_id
    eb_id: int
    opening: Optional[float] = None
    closing: Optional[float] = None

    @model_validator(mode="after")
    def _one_side_required(self):
        if self.opening is None and self.closing is None:
            raise ValueError("opening or closing is required")
        return self


class JugarUpdate(BaseModel):
    # ge=0, not gt=0: an OPENING of 0 is legal. The router gates per side once it
    # knows which one this row is (see _validate_jugar_weight).
    weight: float = Field(ge=0)


class QualityAdd(BaseModel):
    co_id: int
    branch_id: Optional[int] = None
    tran_date: date
    spell: Optional[str] = None  # deprecated — send spell_id
    spell_id: Optional[int] = None  # preferred; exactly one of spell/spell_id
    eb_id: int
    item_id: Optional[int] = None
    machine_id: Optional[int] = None  # the winding machine (optional, may be unknown)
    no_of_spindle: int = Field(default=0, ge=0)


class QualitySave(BaseModel):
    co_id: int
    branch_id: Optional[int] = None
    item_id: Optional[int] = None
    machine_id: Optional[int] = None  # the winding machine (optional, may be unknown)
    no_of_spindle: int = Field(ge=0)


# =============================================================================
# Helpers (mirror spinning_entry.py)
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


def _fetch_trolly(db: Session, trolly_id: int):
    """One trolly/spool row (trolly_weight + busket_weight) for the tare."""
    return db.execute(get_winding_trolly_query(), {"trolly_id": int(trolly_id)}).fetchone()


def _fetch_workers(db: Session, branch_id: Optional[int], search=None, limit=None):
    """The winder picker rows (HRMS masters; label concatenated server-side)."""
    rows = db.execute(
        get_winding_workers_query(),
        {
            "branch_id": branch_id,
            "search": f"%{search}%" if search else None,
            "limit": int(limit) if limit else WORKER_LIMIT_DEFAULT,
        },
    ).fetchall()
    workers = []
    for r in rows:
        m = dict(r._mapping)
        workers.append(
            {
                "eb_id": m["eb_id"],
                "emp_code": m.get("emp_code"),
                "worker_name": m.get("worker_name"),
                "designation": m.get("designation"),
                "label": m.get("label"),
            }
        )
    return workers


def _worker_branch(db: Session, eb_id: int) -> int:
    """The winder's branch from HRMS (spec §4.4). 400 when the eb_id is unknown —
    every write validates the person before creating a row keyed on them.

    Also 400 when the HRMS record carries no branch: branch_id is the SCOPE KEY
    for every winding read (jugar state, grids, reconciliation, the spinning
    day-slice), so a branchless row would be invisible to all of them. Rejecting
    at the write boundary is what lets those queries use a plain
    ``branch_id = :branch_id`` instead of NULL-tolerant filters."""
    row = db.execute(derive_branch_for_worker_query(), {"eb_id": int(eb_id)}).fetchone()
    if not row:
        raise HTTPException(status_code=400, detail=UNKNOWN_WORKER_MSG)
    if row.branch_id is None:
        raise HTTPException(status_code=400, detail=WORKER_NO_BRANCH_MSG)
    return int(row.branch_id)


def _require_branch_id(request: Request) -> int:
    """branch_id is mandatory on winding reads — it is the scope key (co_id is
    implied by it: one branch belongs to exactly one company)."""
    branch_id = _optional_branch_id(request)
    if branch_id is None:
        raise HTTPException(status_code=400, detail="branch_id is required")
    return branch_id


def _required_eb_id(request: Request) -> int:
    raw = request.query_params.get("eb_id")
    if not raw:
        raise HTTPException(status_code=400, detail="eb_id is required")
    try:
        return int(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid eb_id")


def _validate_jugar_weight(open_close: str, weight) -> float:
    """Gate one jugar weight against its side's band.

    Opening: ``JUGAR_MIN <= w <= JUGAR_MAX`` — 0 is legal, a winder can start a
    spell with an empty spindle and forcing a positive number there would invent
    carryover that does not exist (and inflate that spell's reconciled kg, which
    subtracts the opening).
    Closing: ``JUGAR_MIN < w <= JUGAR_MAX`` — a recorded closing leftover of 0 is
    "nothing left", which is expressed by not entering one.
    """
    w = float(weight)
    low_ok = w >= JUGAR_MIN if open_close == "O" else w > JUGAR_MIN
    if not (low_ok and w <= JUGAR_MAX):
        raise HTTPException(
            status_code=400,
            detail=JUGAR_OPENING_RANGE_MSG if open_close == "O" else JUGAR_RANGE_MSG,
        )
    return w


def _validate_open_close(open_close: str) -> str:
    oc = (open_close or "").strip().upper()
    if oc not in ("O", "C"):
        raise HTTPException(status_code=400, detail=OPEN_CLOSE_MSG)
    return oc


def _serialize_dates(row: dict, keys=("tran_date",)) -> dict:
    for k in keys:
        if row.get(k) is not None:
            row[k] = str(row[k])
    return row


def _spells(db: Session, branch_id: Optional[int]):
    """Distinct spells for the header picker (first spell_id wins per code)."""
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
    return spells


def _yarn_items(db: Session, co_id: int, branch_id: Optional[int]):
    """The yarn-quality picker (quality identity is the ITEM)."""
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
    return yarn_items


def _equal_split(total: float, n: int) -> List[float]:
    """Split one weighing evenly into n shares that add back up to the total.

    Every share is the rounded quotient except the last, which absorbs the
    rounding remainder — so sum(shares) == total to 3 dp and the day's winding
    production is unchanged by how many winders shared the trolly.
    """
    share = round(total / n, 3)
    return [share] * (n - 1) + [round(total - share * (n - 1), 3)]


def _trollies(db: Session, trolly_type: str, branch_id: Optional[int]):
    """Trolly ('T') or spool ('S') master rows, Winding-tagged."""
    out = []
    for r in db.execute(
        get_winding_trollies_query(),
        {
            "trolly_type": trolly_type,
            "branch_id": branch_id,
            "machine_type_name": WINDING_MACHINE_TYPE_NAME,
        },
    ).fetchall():
        m = dict(r._mapping)
        out.append(
            {
                "trolly_id": m["trolly_id"],
                "trolly_name": m["trolly_name"],
                "trolly_weight": _f(m.get("trolly_weight")),
                "bucket_weight": _f(m.get("bucket_weight")),
            }
        )
    return out


def _machines(db: Session, branch_id: Optional[int]):
    """Winding-type machines for the quality map's machine picker."""
    return [
        dict(r._mapping)
        for r in db.execute(
            get_winding_machines_query(),
            {
                "machine_type_name": WINDING_MACHINE_TYPE_NAME,
                "branch_id": branch_id,
            },
        ).fetchall()
    ]


# =============================================================================
# Worker picker
# =============================================================================


@router.get("/workers")
def workers(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """The winder picker (spec §3.1). HRMS masters, branch-scoped, NOT
    designation-filtered and NOT attendance-driven."""
    _require_co_id(request)
    branch_id = _optional_branch_id(request)
    try:
        limit_raw = request.query_params.get("limit")
        limit = int(limit_raw) if limit_raw else WORKER_LIMIT_DEFAULT
        search = request.query_params.get("search")
        return {"data": _fetch_workers(db, branch_id, search, limit)}
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid limit")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Doff endpoints
# =============================================================================


@router.get("/doff_setup")
def doff_setup(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    co_id = _require_co_id(request)
    branch_id = _optional_branch_id(request)
    try:
        return {
            "data": {
                "workers": _fetch_workers(db, branch_id),
                "yarn_items": _yarn_items(db, co_id, branch_id),
                "trollies": _trollies(db, "T", branch_id),
                "spools": _trollies(db, "S", branch_id),
                "spells": _spells(db, branch_id),
            }
        }
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/doff_prev_state")
def doff_prev_state(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Prefill the doff form from this winder's last active doff
    (trolly / spool / quality + their weights).

    Branch-scoped; derived from the winder when the caller omits it.
    """
    try:
        eb_id = _required_eb_id(request)
        branch_id = _optional_branch_id(request)
        if branch_id is None:
            branch_id = _worker_branch(db, eb_id)
        row = db.execute(
            get_doff_prev_state_query(),
            {"eb_id": eb_id, "branch_id": branch_id},
        ).fetchone()
        if not row:
            return {"data": None}

        m = dict(row._mapping)
        data = {
            "winding_doff_id": m["winding_doff_id"],
            "eb_id": m.get("eb_id"),
            "spell_id": _i(m.get("spell_id")),
            "item_id": m.get("item_id"),
            "trolly_id": m.get("trolly_id"),
            "trolly_wt": _f(m.get("trolly_wt")),
            "spool_id": m.get("spool_id"),
            "spool_wt": _f(m.get("spool_wt")),
            "gross_input_wt": _f(m.get("gross_input_wt")),
            "production_qty": _f(m.get("production_qty")),
        }
        if m.get("tran_date") is not None:
            data["tran_date"] = str(m["tran_date"])
        return {"data": data}
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid eb_id")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/doff_create")
def doff_create(
    body: DoffCreate,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Create one doff weighing — ONE row per winder sharing it.

    One weighing is one trolly + one spool, so the tare comes off exactly once:
    net_total = gross - trolly - spool, split equally over the N selected winders
    (eb_ids, or the single eb_id). The last row carries the rounding remainder so
    the shares add back up to net_total; trolly_wt / spool_wt are NOT divided.
    Gate: net_total > 0 and each row's share within [WINDING_NET_MIN,
    WINDING_NET_MAX]; otherwise 400. All N rows go in one transaction — a partial
    split can never persist. machine_id and no_of_machines stay NULL (D3/D4).
    """
    try:
        # de-duplicated, selection order preserved
        eb_ids = list(dict.fromkeys(int(e) for e in (body.eb_ids or [body.eb_id])))
        # every winder must exist (400s an unknown eb_id); branch from the first
        worker_branches = [_worker_branch(db, eb_id) for eb_id in eb_ids]
        branch_id = body.branch_id if body.branch_id is not None else worker_branches[0]
        spell_id = _resolve_spell(db, body.spell_id, body.spell, branch_id)

        trolly = _fetch_trolly(db, body.trolly_id)
        if not trolly:
            raise HTTPException(status_code=400, detail="Unknown trolly")
        spool = _fetch_trolly(db, body.spool_id)
        if not spool:
            raise HTTPException(status_code=400, detail="Unknown spool")

        trolly_wt = _f(trolly.trolly_weight)
        spool_wt = _f(spool.trolly_weight)
        gross = float(body.gross_weight)

        n = len(eb_ids)
        net_total = compute_winding_net(gross, trolly_wt, spool_wt)
        if net_total <= 0:
            raise HTTPException(status_code=400, detail=NET_GATE_MSG)
        nets = _equal_split(net_total, n)
        # Gate EVERY share, remainder row included — not just the quotient.
        if not all(validate_winding_net(s) for s in nets):
            raise HTTPException(status_code=400, detail=NET_RANGE_MSG)
        gross_shares = _equal_split(gross, n)

        ids, row_grosses = [], []
        for eb_id, row_net, row_gross_input in zip(eb_ids, nets, gross_shares):
            row_gross = compute_winding_row_gross_wt(row_net, trolly_wt, spool_wt)
            result = db.execute(
                insert_doff_row_query(),
                {
                    "co_id": int(body.co_id),
                    "branch_id": branch_id,
                    "tran_date": body.tran_date,
                    "spell_id": spell_id,
                    "eb_id": eb_id,
                    "item_id": int(body.quality_id),
                    "trolly_id": int(body.trolly_id),
                    "trolly_wt": trolly_wt,
                    "spool_id": int(body.spool_id),
                    "spool_wt": spool_wt,
                    "gross_input_wt": row_gross_input,
                    "production_qty": row_net,
                    "row_gross_wt": row_gross,
                    "updated_by": token_data.get("user_id"),
                },
            )
            ids.append(result.lastrowid)
            row_grosses.append(row_gross)

        # Tie the shares together under the first row's id so edit and delete
        # act on the whole weighing — see stamp_doff_weighing_id_query.
        db.execute(
            stamp_doff_weighing_id_query(), {"ids": ids, "weighing_id": ids[0]}
        )
        db.commit()
        return {
            "data": {
                "winding_doff_ids": ids,
                "winding_doff_id": ids[0],
                "weighing_id": ids[0],
                "net_total": net_total,
                "net_per_row": nets[0],
                "net": nets[0],
                "row_gross_wt": row_grosses[0],
            }
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/doff_by_date")
def doff_by_date(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    # branch_id is the scope key here (co_id is implied by it and no longer filters).
    branch_id = _require_branch_id(request)
    d = request.query_params.get("tran_date")
    if not d:
        raise HTTPException(status_code=400, detail="tran_date is required")
    spell = request.query_params.get("spell") or None
    eb_raw = request.query_params.get("eb_id")
    try:
        d_val = date.fromisoformat(d)
        spell_id_param = _optional_spell_id_param(request)
        spell_id = (
            _resolve_spell(db, spell_id_param, spell, branch_id)
            if (spell_id_param is not None or spell)
            else None
        )
        rows = db.execute(
            get_doff_by_date_query(),
            {
                "tran_date": d_val,
                "spell_id": spell_id,
                "branch_id": branch_id,
                "eb_id": int(eb_raw) if eb_raw else None,
            },
        ).fetchall()
        data = []
        for r in rows:
            row = dict(r._mapping)
            for k in (
                "trolly_wt",
                "spool_wt",
                "gross_input_wt",
                "production_qty",
                "row_gross_wt",
            ):
                if row.get(k) is not None:
                    row[k] = float(row[k])
            _serialize_dates(row)
            data.append(row)
        return {"data": data}
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tran_date or eb_id")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/doff_edit/{entry_id}")
def doff_edit(
    entry_id: int,
    body: DoffUpdate,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Edit the WEIGHING this row belongs to — every winder's share is re-split.

    One weighing is one trolly + one spool + one quality, so an edit applies to
    all its rows: the new gross is the whole weighing's gross (as on create), and
    the recomputed net_total is split again over the winders currently on it.
    Editing a single share instead would leave the shares summing to a weighing
    that never happened. A row written before the split existed is its own group,
    so this is the old single-row recompute for legacy rows.
    """
    _require_co_id(request)
    branch_id = _optional_branch_id(request)
    try:
        existing = db.execute(
            get_doff_active_by_id_query(), {"id": entry_id, "branch_id": branch_id}
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail=DOFF_NOT_FOUND_MSG)

        group_rows = db.execute(
            get_doff_group_rows_query(), {"group_id": existing.weighing_id}
        ).fetchall()

        new_trolly = int(body.trolly_id) if body.trolly_id is not None else int(existing.trolly_id)
        new_spool = int(body.spool_id) if body.spool_id is not None else int(existing.spool_id)
        new_quality = (
            int(body.quality_id) if body.quality_id is not None else existing.item_id
        )
        # No gross sent -> keep the WEIGHING's gross, i.e. the sum of the shares.
        # Reusing this row's own gross_input_wt would shrink a shared weighing to
        # one winder's slice on every quality-only edit.
        new_gross = (
            float(body.gross_weight)
            if body.gross_weight is not None
            else round(sum(_f(r.gross_input_wt) for r in group_rows), 3)
        )

        trolly = _fetch_trolly(db, new_trolly)
        if not trolly:
            raise HTTPException(status_code=400, detail="Unknown trolly")
        spool = _fetch_trolly(db, new_spool)
        if not spool:
            raise HTTPException(status_code=400, detail="Unknown spool")
        trolly_wt = _f(trolly.trolly_weight)
        spool_wt = _f(spool.trolly_weight)

        n = len(group_rows)
        net_total = compute_winding_net(new_gross, trolly_wt, spool_wt)
        if net_total <= 0:
            raise HTTPException(status_code=400, detail=NET_GATE_MSG)
        nets = _equal_split(net_total, n)
        if not all(validate_winding_net(s) for s in nets):
            raise HTTPException(status_code=400, detail=NET_RANGE_MSG)
        gross_shares = _equal_split(new_gross, n)

        edited_net, edited_row_gross = nets[0], None
        for row, row_net, row_gross_input in zip(group_rows, nets, gross_shares):
            row_gross = compute_winding_row_gross_wt(row_net, trolly_wt, spool_wt)
            if row.winding_doff_id == entry_id:
                edited_net, edited_row_gross = row_net, row_gross
            db.execute(
                update_doff_row_query(),
                {
                    "id": row.winding_doff_id,
                    "item_id": new_quality,
                    "trolly_id": new_trolly,
                    "trolly_wt": trolly_wt,
                    "spool_id": new_spool,
                    "spool_wt": spool_wt,
                    "gross_input_wt": row_gross_input,
                    "production_qty": row_net,
                    "row_gross_wt": row_gross,
                    "updated_by": token_data.get("user_id"),
                },
            )
        db.commit()
        return {
            "data": {
                "winding_doff_id": entry_id,
                "weighing_id": existing.weighing_id,
                "winding_doff_ids": [r.winding_doff_id for r in group_rows],
                "net_total": net_total,
                "net": edited_net,
                "row_gross_wt": edited_row_gross,
            }
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/doff_delete/{entry_id}")
def doff_delete(
    entry_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Soft-delete the WEIGHING this row belongs to — all its winders' shares.

    Removing one share would leave the rest summing to a weighing that never
    happened, and the spinning planning grid would quietly lose that share.
    ``rows_deleted`` reports how many shares went.
    """
    _require_co_id(request)
    branch_id = _optional_branch_id(request)
    try:
        existing = db.execute(
            get_doff_active_by_id_query(), {"id": entry_id, "branch_id": branch_id}
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail=DOFF_NOT_FOUND_MSG)

        # Delete the whole weighing, not one winder's share of it — see
        # soft_delete_doff_group_query. A legacy row is its own group.
        result = db.execute(
            soft_delete_doff_group_query(),
            {
                "group_id": existing.weighing_id,
                "updated_by": token_data.get("user_id"),
            },
        )
        db.commit()
        return {
            "data": {
                "message": "Deleted",
                "weighing_id": existing.weighing_id,
                "rows_deleted": int(result.rowcount),
            }
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Jugar endpoints
# =============================================================================


@router.get("/jugar_setup")
def jugar_setup(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    _require_co_id(request)
    branch_id = _optional_branch_id(request)
    try:
        return {
            "data": {
                "workers": _fetch_workers(db, branch_id),
                "spells": _spells(db, branch_id),
            }
        }
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _saved_jugar_pair(db: Session, branch_id, tran_date_val, spell_id, eb_id) -> dict:
    """{'O': row, 'C': row} of what is already stored for this winder/spell.

    Keyed on branch_id, not co_id — see get_jugar_saved_pair_query.
    """
    rows = db.execute(
        get_jugar_saved_pair_query(),
        {
            "branch_id": int(branch_id),
            "tran_date": tran_date_val,
            "spell_id": spell_id,
            "eb_id": int(eb_id),
        },
    ).fetchall()
    # Ordered by id, so a later row overwrites an earlier duplicate.
    return {r.open_close: r for r in rows}


def _carried_jugar(db: Session, branch_id, tran_date_val, spell_id, eb_id, open_close):
    """Previous spell's jugar of one kind, in spell-sequence order (see query)."""
    return db.execute(
        get_jugar_prev_seq_query(),
        {
            "branch_id": int(branch_id),
            "eb_id": int(eb_id),
            "tran_date": tran_date_val,
            "spell_id": spell_id,
            "open_close": open_close,
        },
    ).fetchone()


@router.get("/jugar_state")
def jugar_state(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Opening AND closing jugar for one winder/date/spell — the two-field form.

    Per side, in precedence order:

    1. ``saved``      — the row already stored for this date/spell/winder. A
       manual entry therefore always beats the carry-forward.
    2. ``carry``      — the previous spell's CLOSING leftover in spell-sequence
       order (earlier spell same day, else the last spell of an earlier date):
       this spell's opening IS the last spell's closing. The closing field is
       seeded from the same value as a starting point for the weigher.
    3. ``carry_open`` — (opening only) the winder's previous OPENING when no
       closing was ever recorded (legacy 'OE'), so a mill that logs openings
       only still gets a number.
    4. ``none``       — nothing found; 0.

    ``winding_jugar_id`` is non-null only for a saved side (the save upserts it).
    Everything is scoped BRANCH + person — branch_id is the key (co_id is implied
    by it); when the caller omits it, it is derived from the winder's HRMS
    record. spell_id is required for the saved lookup and for same-day
    sequencing; without it only prior dates carry.
    """
    try:
        tran_date_s = request.query_params.get("tran_date")
        if not request.query_params.get("eb_id") or not tran_date_s:
            raise HTTPException(status_code=400, detail="eb_id and tran_date are required")
        eb_id = _required_eb_id(request)
        tran_date_val = date.fromisoformat(tran_date_s)

        branch_id = _optional_branch_id(request)
        if branch_id is None:
            branch_id = _worker_branch(db, eb_id)

        spell = request.query_params.get("spell")
        spell_id_param = _optional_spell_id_param(request)
        spell_id = (
            _resolve_spell(db, spell_id_param, spell, branch_id)
            if (spell or spell_id_param is not None)
            else None
        )

        saved = (
            _saved_jugar_pair(db, branch_id, tran_date_val, spell_id, eb_id)
            if spell_id is not None
            else {}
        )
        prev_close = _carried_jugar(db, branch_id, tran_date_val, spell_id, eb_id, "C")
        prev_open = (
            None
            if prev_close
            else _carried_jugar(db, branch_id, tran_date_val, spell_id, eb_id, "O")
        )

        def side(open_close: str, fallbacks) -> dict:
            row = saved.get(open_close)
            if row is not None:
                return {
                    "weight": _f(row.weight),
                    "winding_jugar_id": int(row.winding_jugar_id),
                    "source": "saved",
                }
            for src, found in fallbacks:
                if found is not None:
                    return {"weight": _f(found.weight), "winding_jugar_id": None, "source": src}
            return {"weight": 0.0, "winding_jugar_id": None, "source": "none"}

        return {
            "data": {
                "spell_id": spell_id,
                "opening": side("O", (("carry", prev_close), ("carry_open", prev_open))),
                "closing": side("C", (("carry", prev_close),)),
            }
        }
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid eb_id or tran_date")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/jugar_save")
def jugar_save(
    body: JugarSave,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Upsert this winder/spell's opening and/or closing leftover.

    The form posts both fields (the opening usually still holding the carried
    value), so an existing row is UPDATED rather than rejected as a duplicate —
    persisting the carry is what makes it count in reconciliation, which reads
    stored rows only. A side left out of the payload is left untouched. Weights
    are gated by _validate_jugar_weight (opening may be 0, closing may not).
    """
    try:
        sides = [(oc, w) for oc, w in (("O", body.opening), ("C", body.closing)) if w is not None]
        for open_close, raw in sides:
            _validate_jugar_weight(open_close, raw)

        worker_branch = _worker_branch(db, body.eb_id)
        branch_id = body.branch_id if body.branch_id is not None else worker_branch
        spell_id = _resolve_spell(db, body.spell_id, body.spell, branch_id)

        saved = _saved_jugar_pair(db, branch_id, body.tran_date, spell_id, body.eb_id)
        out = {}
        for open_close, raw in sides:
            weight = float(raw)
            existing = saved.get(open_close)
            if existing is not None:
                db.execute(
                    update_jugar_row_query(),
                    {
                        "id": int(existing.winding_jugar_id),
                        "weight": weight,
                        "updated_by": token_data.get("user_id"),
                    },
                )
                row_id = int(existing.winding_jugar_id)
            else:
                row_id = db.execute(
                    insert_jugar_row_query(),
                    {
                        "co_id": int(body.co_id),
                        "branch_id": branch_id,
                        "tran_date": body.tran_date,
                        "spell_id": spell_id,
                        "eb_id": int(body.eb_id),
                        "weight": weight,
                        "open_close": open_close,
                        "updated_by": token_data.get("user_id"),
                    },
                ).lastrowid
            key = "opening" if open_close == "O" else "closing"
            out[key] = {"winding_jugar_id": row_id, "weight": weight}

        db.commit()
        return {"data": out}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/jugar_update/{entry_id}")
def jugar_update(
    entry_id: int,
    body: JugarUpdate,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        # The row's own side decides the band (opening may be 0), so the lookup
        # comes first — same gate as jugar_save, which writes the same column.
        existing = db.execute(get_jugar_active_by_id_query(), {"id": entry_id}).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail=JUGAR_NOT_FOUND_MSG)

        weight = _validate_jugar_weight(existing.open_close, body.weight)

        db.execute(
            update_jugar_row_query(),
            {"id": entry_id, "weight": weight, "updated_by": token_data.get("user_id")},
        )
        db.commit()
        return {"data": {"winding_jugar_id": entry_id, "weight": weight}}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/jugar_by_date")
def jugar_by_date(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    # branch_id is the scope key here (co_id is implied by it and no longer filters).
    branch_id = _require_branch_id(request)
    d = request.query_params.get("tran_date")
    if not d:
        raise HTTPException(status_code=400, detail="tran_date is required")
    spell = request.query_params.get("spell") or None
    open_close_raw = request.query_params.get("open_close") or None
    try:
        d_val = date.fromisoformat(d)
        spell_id_param = _optional_spell_id_param(request)
        spell_id = (
            _resolve_spell(db, spell_id_param, spell, branch_id)
            if (spell_id_param is not None or spell)
            else None
        )
        open_close = _validate_open_close(open_close_raw) if open_close_raw else None
        rows = db.execute(
            get_jugar_by_date_query(),
            {
                "tran_date": d_val,
                "spell_id": spell_id,
                "open_close": open_close,
                "branch_id": branch_id,
            },
        ).fetchall()
        data = []
        for r in rows:
            row = dict(r._mapping)
            if row.get("weight") is not None:
                row["weight"] = float(row["weight"])
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
# Quality endpoints — the person -> quality map
# =============================================================================


@router.get("/quality_setup")
def quality_setup(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Auto-seed (if empty) then return the map rows + the pickers.

    If no active rows exist for the date/spell, the PERSONS of the previous spell
    are carried forward with their item_id + no_of_spindle. With no prior spell
    nothing is seeded (empty map — the user adds winders via /quality_add).
    ``workers`` feeds that "Add winder" picker.
    """
    # branch_id is the scope key; co_id is still needed as an INSERT value on the
    # seeded rows and for the yarn picker (item scope lives on item_grp_mst.co_id).
    co_id = _require_co_id(request)
    branch_id = _require_branch_id(request)
    d = request.query_params.get("tran_date")
    spell = request.query_params.get("spell")
    spell_id_param = _optional_spell_id_param(request)
    if not d or not (spell or spell_id_param is not None):
        raise HTTPException(
            status_code=400, detail="tran_date and spell_id (or spell) are required"
        )
    try:
        d_val = date.fromisoformat(d)
        spell_id = _resolve_spell(db, spell_id_param, spell, branch_id)

        cnt = db.execute(
            get_quality_exists_query(),
            {"tran_date": d_val, "spell_id": spell_id, "branch_id": branch_id},
        ).scalar()
        if not cnt or int(cnt) == 0:
            prev = db.execute(
                get_quality_prev_seed_date_spell_query(),
                {"tran_date": d_val, "spell_id": spell_id, "branch_id": branch_id},
            ).fetchone()
            db.execute(
                auto_seed_quality_query(),
                {
                    "co_id": co_id,
                    "tran_date": d_val,
                    "spell_id": spell_id,
                    "prev_date": prev.prev_date if prev else None,
                    "prev_spell_id": prev.prev_spell_id if prev else None,
                    "branch_id": branch_id,
                    "updated_by": token_data.get("user_id"),
                },
            )
            db.commit()

        rows = [
            _serialize_dates(dict(r._mapping))
            for r in db.execute(
                get_quality_by_date_query(),
                {
                    "tran_date": d_val,
                    "spell_id": spell_id,
                    "branch_id": branch_id,
                },
            ).fetchall()
        ]

        return {
            "data": {
                "rows": rows,
                "yarn_items": _yarn_items(db, co_id, branch_id),
                "workers": _fetch_workers(db, branch_id),
                "machines": _machines(db, branch_id),
            }
        }
    except HTTPException:
        db.rollback()
        raise
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tran_date format")
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/quality_add")
def quality_add(
    body: QualityAdd,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Add a winder to the day's person -> quality map.

    400 on a duplicate (branch, date, spell, eb) — one row per winder per spell.
    no_of_spindle may be 0 (not yet known), the same default the carry-forward
    seed uses; /quality_save then enforces the stricter 1..30 on edit.
    """
    try:
        spindle = int(body.no_of_spindle)
        if not (0 <= spindle <= SPINDLE_MAX):
            raise HTTPException(status_code=400, detail=SPINDLE_ADD_RANGE_MSG)

        worker_branch = _worker_branch(db, body.eb_id)
        branch_id = body.branch_id if body.branch_id is not None else worker_branch
        spell_id = _resolve_spell(db, body.spell_id, body.spell, branch_id)

        dup = db.execute(
            get_quality_duplicate_query(),
            {
                "branch_id": branch_id,
                "tran_date": body.tran_date,
                "spell_id": spell_id,
                "eb_id": int(body.eb_id),
                "exclude_id": 0,
            },
        ).fetchone()
        if dup:
            raise HTTPException(status_code=400, detail=DUP_QUALITY_MSG)

        result = db.execute(
            insert_quality_row_query(),
            {
                "co_id": int(body.co_id),
                "branch_id": branch_id,
                "tran_date": body.tran_date,
                "spell_id": spell_id,
                "eb_id": int(body.eb_id),
                "item_id": body.item_id,
                "machine_id": body.machine_id,
                "no_of_spindle": spindle,
                "updated_by": token_data.get("user_id"),
            },
        )
        db.commit()
        return {"data": {"winding_daily_qlty_id": result.lastrowid}}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/quality_save/{entry_id}")
def quality_save(
    entry_id: int,
    body: QualitySave,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Update a map row's item_id + no_of_spindle.

    Validates SPINDLE_MIN <= no_of_spindle <= SPINDLE_MAX and blocks a duplicate
    entry for the same winder/date/spell (excluding this row)."""
    try:
        spindle = int(body.no_of_spindle)
        if not (SPINDLE_MIN <= spindle <= SPINDLE_MAX):
            raise HTTPException(status_code=400, detail=SPINDLE_RANGE_MSG)

        existing = db.execute(get_quality_active_by_id_query(), {"id": entry_id}).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail=QUALITY_NOT_FOUND_MSG)

        dup = db.execute(
            get_quality_duplicate_query(),
            {
                "branch_id": existing.branch_id,
                "tran_date": existing.tran_date,
                "spell_id": int(existing.spell_id),
                "eb_id": existing.eb_id,
                "exclude_id": entry_id,
            },
        ).fetchone()
        if dup:
            raise HTTPException(status_code=400, detail=DUP_QUALITY_MSG)

        db.execute(
            update_quality_row_query(),
            {
                "id": entry_id,
                "item_id": body.item_id,
                "machine_id": body.machine_id,
                "no_of_spindle": spindle,
                "updated_by": token_data.get("user_id"),
            },
        )
        db.commit()
        return {"data": {"winding_daily_qlty_id": entry_id, "no_of_spindle": spindle}}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/quality_delete/{entry_id}")
def quality_delete(
    entry_id: int,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Soft-delete a map row — removes a carried-forward winder who is absent."""
    try:
        existing = db.execute(get_quality_active_by_id_query(), {"id": entry_id}).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail=QUALITY_NOT_FOUND_MSG)

        db.execute(
            soft_delete_quality_row_query(),
            {"id": entry_id, "updated_by": token_data.get("user_id")},
        )
        db.commit()
        return {"data": {"deleted": entry_id}}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/quality_by_date")
def quality_by_date(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    # branch_id is the scope key here (co_id is implied by it and no longer filters).
    branch_id = _require_branch_id(request)
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
        rows = db.execute(
            get_quality_by_date_query(),
            {"tran_date": d_val, "spell_id": spell_id, "branch_id": branch_id},
        ).fetchall()
        return {"data": [_serialize_dates(dict(r._mapping)) for r in rows]}
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tran_date format")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
