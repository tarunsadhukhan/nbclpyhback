"""R-08-12/13/14 Finisher Drawing Sliver Weight QC capture endpoints (jute SQC module).

Drawing-stage sliver-weight uniformity for the three sections HESS / SWP / SWT. Clone of
card_sliver_wt.py (R-08-07A) with TWO deltas: the section enum is FIN_DRAW_SECTIONS, and each
reading carries a per-cut delivery (DLV) number array. Each reading-set records EXACTLY 4
sliver-cut weights (LB per 5 yds) + 4 MR% (+ 4 DLV numbers), moisture-corrects each cut to the
quality's STD MR%, then the row's avg-observed / avg-MR / avg-corrected weight / sample-stdev
(on the corrected cuts) / CV% and a CV-band pass flag are computed server-side and PERSISTED
(insert-only + compute-on-read).

Quality is linked to a BATCH (jute_batch_plan — a named mix of raw-jute qualities,
branch-scoped). A batch has no single std, so std MR falls back to the DRAWING default 16 and
the CV band stays unevaluated (cv_within_band NULL); the per-batch GRAND AVERAGE regroups by
batch_plan_id. The compute / section-average / grand-average helpers are REUSED from
card_sliver_wt — only the std-MR default (16, passed EXPLICITLY) differs.

Portal persona: get_tenant_db + get_current_user_with_refresh, {"data": ...} responses,
co_id (+ branch_id on setup) validation, None for SQL NULLs, type-cast binds. The spell and
shared-machine and batch builders are REUSED from the card family.
"""

import json
import logging
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.authorization.utils import get_current_user_with_refresh
from src.config.db import get_tenant_db
from src.juteSQC.card_sliver_wt import (
    compute_card_sliver_stats,
    compute_grand_averages,
    compute_section_averages,
)
from src.juteSQC.constants import FIN_DRAW_SECTIONS
from src.juteSQC.query import (
    get_card_section_batches_query,
    get_card_section_machines_query,
    get_fin_draw_sliver_wt_active_row_query,
    get_fin_draw_sliver_wt_by_date_query,
    get_fin_draw_sliver_wt_by_id_query,
    get_fin_draw_sliver_wt_table_count_query,
    get_fin_draw_sliver_wt_table_query,
    get_spreader_roll_wt_spells_query,
    soft_delete_fin_draw_sliver_wt_query,
)
from src.models.jute import JuteSqcFinDrawSliverWt

logger = logging.getLogger(__name__)

router = APIRouter()

# Constants
SAMPLE_SIZE = 4
DRAW_STD_MR_PCT = 16.0  # drawing-stage std MR default (owner decision; passed explicitly)
NOT_FOUND_MSG = "Finisher drawing sliver weight reading not found"


# =============================================================================
# Pydantic models
# =============================================================================


class FinDrawSliverWtRow(BaseModel):
    """One (section, machine, spell, batch) reading-set: EXACTLY 4 cut weights + 4 MR% (+ 4
    DLV numbers). Quality is linked via batch_plan_id (jute_batch_plan)."""

    section: str
    mc_id: Optional[int] = None
    spell_id: Optional[int] = None
    batch_plan_id: Optional[int] = None
    dlv_nos: List[Optional[int]] = Field(default_factory=lambda: [None, None, None, None])
    weights: List[float] = Field(default_factory=list)
    mr_pcts: List[float] = Field(default_factory=list)


class FinDrawSliverWtCreateRequest(BaseModel):
    """One save = the day's grid: a header (co/branch/date) + an ARRAY of rows."""

    co_id: int
    branch_id: Optional[int] = None
    entry_date: date
    rows: List[FinDrawSliverWtRow] = Field(default_factory=list)


# =============================================================================
# Helpers — request parsing / fetchers
# =============================================================================


def _f(v, default: Optional[float] = None) -> Optional[float]:
    return default if v is None else float(v)


def _require_co_id(request: Request) -> int:
    raw = request.query_params.get("co_id")
    if not raw:
        raise HTTPException(status_code=400, detail="co_id is required")
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid co_id format")


def _require_branch_id(request: Request) -> int:
    raw = request.query_params.get("branch_id")
    if not raw:
        raise HTTPException(status_code=400, detail="branch_id is required")
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid branch_id format")


def _optional_branch_id(request: Request) -> Optional[int]:
    raw = request.query_params.get("branch_id")
    if not raw:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid branch_id format")


def _require_entry_date(request: Request) -> date:
    raw = request.query_params.get("entry_date")
    if not raw:
        raise HTTPException(status_code=400, detail="entry_date is required")
    try:
        return date.fromisoformat(raw)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid entry_date format")


def _loads(v):
    """json.loads a persisted JSON-as-string column (None / non-str passes through)."""
    if v and isinstance(v, str):
        try:
            return json.loads(v)
        except (ValueError, TypeError):
            return v
    return v


def _fetch_spells(db: Session, branch_id: Optional[int]) -> list:
    """Spell (SHIFT) picker rows, de-duplicated by spell_code (first row wins)."""
    spells = []
    seen = set()
    for r in db.execute(
        get_spreader_roll_wt_spells_query(), {"branch_id": branch_id}
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
                "spell_name": m.get("spell_name"),
                "working_hours": _f(m.get("working_hours")),
            }
        )
    return spells


def _fetch_machines(db: Session, branch_id: Optional[int]) -> list:
    """Shared carding/drawing-pool machines (no machine-type filter — section is a label)."""
    machines = []
    for r in db.execute(
        get_card_section_machines_query(), {"branch_id": branch_id}
    ).fetchall():
        m = dict(r._mapping)
        machines.append(
            {
                "machine_id": m["machine_id"],
                "machine_name": m["machine_name"],
                "mech_code": m.get("mech_code"),
                "machine_type_name": m.get("machine_type_name"),
                "dept_id": m.get("dept_id"),
                "dept_name": m.get("dept_name"),
                "branch_id": m.get("branch_id"),
            }
        )
    return machines


def _fetch_batches(db: Session, branch_id: Optional[int]) -> list:
    """Batch-plan (jute_batch_plan) picker rows — the drawing quality linkage (branch-scoped)."""
    batches = []
    for r in db.execute(
        get_card_section_batches_query(), {"branch_id": branch_id}
    ).fetchall():
        m = dict(r._mapping)
        batches.append(
            {
                "batch_plan_id": int(m["batch_plan_id"]),
                "plan_name": m.get("plan_name"),
                "branch_id": m.get("branch_id"),
                "line_qty": int(m["line_qty"]) if m.get("line_qty") is not None else 0,
            }
        )
    return batches


def _by_date_row_out(r) -> dict:
    """Shape one date-driven row, json.loads-ing the persisted readings."""
    m = dict(r._mapping)
    return {
        "fin_draw_sliver_wt_id": m["fin_draw_sliver_wt_id"],
        "co_id": m["co_id"],
        "branch_id": m.get("branch_id"),
        "entry_date": str(m["entry_date"]) if m.get("entry_date") is not None else None,
        "section": m.get("section"),
        "spell_id": m.get("spell_id"),
        "spell_code": m.get("spell_code"),
        "mc_id": m.get("mc_id"),
        "machine_name": m.get("machine_name"),
        "mech_code": m.get("mech_code"),
        "batch_plan_id": m.get("batch_plan_id"),
        "batch_plan_name": m.get("batch_plan_name"),
        "weights": _loads(m.get("weights")),
        "mr_pcts": _loads(m.get("mr_pcts")),
        "dlv_nos": _loads(m.get("dlv_nos")),
        "std_mr_pct": _f(m.get("std_mr_pct")),
        "std_cv_low": _f(m.get("std_cv_low")),
        "std_cv_high": _f(m.get("std_cv_high")),
        "calc_wt": _f(m.get("calc_wt")),
        "calc_mr_pct": _f(m.get("calc_mr_pct")),
        "calc_corr_wt": _f(m.get("calc_corr_wt")),
        "calc_sdev": _f(m.get("calc_sdev")),
        "calc_cv_pct": _f(m.get("calc_cv_pct")),
        "cv_within_band": m.get("cv_within_band"),
    }


# =============================================================================
# Endpoints
# =============================================================================


@router.get("/get_fin_draw_sliver_wt_setup")
def get_fin_draw_sliver_wt_setup(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Picker data (sections / spells / shared machines / batch plans) + the day's existing
    rows when entry_date is supplied."""
    co_id = _require_co_id(request)
    branch_id = _require_branch_id(request)
    entry_date = request.query_params.get("entry_date")
    try:
        parsed_date = date.fromisoformat(entry_date) if entry_date else None
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid entry_date format")

    try:
        spells = _fetch_spells(db, branch_id)
        machines = _fetch_machines(db, branch_id)
        batches = _fetch_batches(db, branch_id)

        entries = []
        if parsed_date is not None:
            rows = db.execute(
                get_fin_draw_sliver_wt_by_date_query(),
                {"co_id": co_id, "entry_date": parsed_date, "branch_id": branch_id},
            ).fetchall()
            entries = [_by_date_row_out(r) for r in rows]

        return {
            "data": {
                "sections": list(FIN_DRAW_SECTIONS),
                "spells": spells,
                "machines": machines,
                "batches": batches,
                "entries": entries,
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching finisher drawing sliver weight setup")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/create_fin_draw_sliver_wt")
def create_fin_draw_sliver_wt(
    body: FinDrawSliverWtCreateRequest,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Insert MANY rows (the day's grid) in one save; compute + persist each row's calc_* +
    cv_within_band. Per row: validate section ∈ FIN_DRAW_SECTIONS, EXACTLY 4 (wt, mr) pairs,
    wt>0, mr>=0, a batch is selected; store batch_plan_id + dlv_nos (default 4 nulls if absent);
    compute with std MR fixed at 16 (passed explicitly) and no CV band, and insert. Returns the
    inserted ids."""
    try:
        if not body.rows:
            raise HTTPException(status_code=400, detail="At least one row is required")
        if body.branch_id is None:
            raise HTTPException(status_code=400, detail="branch_id is required")

        records: List[JuteSqcFinDrawSliverWt] = []
        for idx, row in enumerate(body.rows):
            section = (row.section or "").strip().upper()
            if section not in FIN_DRAW_SECTIONS:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Row {idx + 1}: section must be one of "
                        f"{', '.join(FIN_DRAW_SECTIONS)}, got '{row.section}'"
                    ),
                )
            if len(row.weights) != SAMPLE_SIZE:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Row {idx + 1}: exactly {SAMPLE_SIZE} weights are required, "
                        f"got {len(row.weights)}"
                    ),
                )
            if len(row.mr_pcts) != SAMPLE_SIZE:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Row {idx + 1}: exactly {SAMPLE_SIZE} MR% readings are required, "
                        f"got {len(row.mr_pcts)}"
                    ),
                )
            if any(w <= 0 for w in row.weights):
                raise HTTPException(
                    status_code=400,
                    detail=f"Row {idx + 1}: all weights must be positive",
                )
            if any(m < 0 for m in row.mr_pcts):
                raise HTTPException(
                    status_code=400,
                    detail=f"Row {idx + 1}: all MR% readings must be non-negative",
                )
            if row.batch_plan_id is None:
                raise HTTPException(
                    status_code=400,
                    detail=f"Row {idx + 1}: a batch must be selected",
                )

            # Quality is linked via batch -> no single (item_id, section) std; std MR fixed at
            # the DRAWING default 16 (passed explicitly) and the CV band stays unevaluated.
            stats = compute_card_sliver_stats(
                row.weights, row.mr_pcts, DRAW_STD_MR_PCT, None, None
            )

            # dlv_nos: persist the per-cut delivery numbers (default 4 nulls if absent — never
            # 400 on missing DLV). Ints or null, normalised to length 4.
            dlv = list(row.dlv_nos) if row.dlv_nos else []
            dlv = (dlv + [None, None, None, None])[:SAMPLE_SIZE]

            records.append(
                JuteSqcFinDrawSliverWt(
                    co_id=int(body.co_id),
                    branch_id=int(body.branch_id) if body.branch_id is not None else None,
                    entry_date=body.entry_date,
                    section=section,
                    mc_id=int(row.mc_id) if row.mc_id is not None else None,
                    spell_id=int(row.spell_id) if row.spell_id is not None else None,
                    batch_plan_id=int(row.batch_plan_id) if row.batch_plan_id is not None else None,
                    weights=json.dumps([float(w) for w in row.weights]),
                    mr_pcts=json.dumps([float(m) for m in row.mr_pcts]),
                    dlv_nos=json.dumps([int(d) if d is not None else None for d in dlv]),
                    std_mr_pct=stats["std_mr_pct"],
                    std_cv_low=stats["std_cv_low"],
                    std_cv_high=stats["std_cv_high"],
                    calc_wt=stats["calc_wt"],
                    calc_mr_pct=stats["calc_mr_pct"],
                    calc_corr_wt=stats["calc_corr_wt"],
                    calc_sdev=stats["calc_sdev"],
                    calc_cv_pct=stats["calc_cv_pct"],
                    cv_within_band=stats["cv_within_band"],
                    updated_by=token_data.get("user_id"),
                )
            )

        db.add_all(records)
        db.commit()
        for rec in records:
            db.refresh(rec)

        return {
            "data": {
                "message": "Finisher drawing sliver weight log(s) created successfully",
                "fin_draw_sliver_wt_ids": [rec.fin_draw_sliver_wt_id for rec in records],
                "count": len(records),
            }
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error creating finisher drawing sliver weight log")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_fin_draw_sliver_wt_by_date")
def get_fin_draw_sliver_wt_by_date(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Date-driven rows + the recomputed per-section AND per-batch average blocks.

    Returns an OBJECT envelope:
    {"data": {"rows": [...], "section_averages": [...], "grand_averages": [...]}}."""
    co_id = _require_co_id(request)
    branch_id = _optional_branch_id(request)
    entry_date = _require_entry_date(request)
    try:
        result = db.execute(
            get_fin_draw_sliver_wt_by_date_query(),
            {"co_id": co_id, "entry_date": entry_date, "branch_id": branch_id},
        ).fetchall()
        rows = [_by_date_row_out(r) for r in result]
        section_averages = compute_section_averages(rows)
        grand_averages = compute_grand_averages(rows)
        return {
            "data": {
                "rows": rows,
                "section_averages": section_averages,
                "grand_averages": grand_averages,
            }
        }
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid entry_date format")
    except Exception as e:
        logger.exception("Error fetching finisher drawing sliver weight by date")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_fin_draw_sliver_wt_table")
def get_fin_draw_sliver_wt_table(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Paginated table of saved finisher-drawing rows (page / limit / search / optional branch)."""
    co_id = _require_co_id(request)
    branch_id = _optional_branch_id(request)
    try:
        page = max(1, int(request.query_params.get("page", "1")))
        limit = max(1, min(100, int(request.query_params.get("limit", "10"))))
        offset = (page - 1) * limit
        search = request.query_params.get("search")

        params = {"co_id": co_id, "branch_id": branch_id, "limit": limit, "offset": offset}
        if search:
            params["search"] = f"%{search}%"

        total_row = db.execute(
            get_fin_draw_sliver_wt_table_count_query(search=search), params
        ).fetchone()
        total = total_row.total if total_row else 0

        result = db.execute(
            get_fin_draw_sliver_wt_table_query(search=search), params
        ).fetchall()
        rows = [dict(r._mapping) for r in result]

        return {"data": rows, "total": total, "page": page, "page_size": limit}
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid pagination parameter")
    except Exception as e:
        logger.exception("Error fetching finisher drawing sliver weight table")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_fin_draw_sliver_wt_by_id")
def get_fin_draw_sliver_wt_by_id(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """One saved row with readings JSON parsed (tenant-scoped via optional co_id)."""
    raw_id = request.query_params.get("id")
    if not raw_id:
        raise HTTPException(status_code=400, detail="id is required")
    try:
        fin_draw_sliver_wt_id = int(raw_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid id format")

    raw_co_id = request.query_params.get("co_id")
    try:
        co_id = int(raw_co_id) if raw_co_id else None
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid co_id format")

    try:
        result = db.execute(
            get_fin_draw_sliver_wt_by_id_query(),
            {"fin_draw_sliver_wt_id": fin_draw_sliver_wt_id, "co_id": co_id},
        ).fetchone()
        if not result:
            raise HTTPException(status_code=404, detail=NOT_FOUND_MSG)

        row = dict(result._mapping)
        row["weights"] = _loads(row.get("weights"))
        row["mr_pcts"] = _loads(row.get("mr_pcts"))
        row["dlv_nos"] = _loads(row.get("dlv_nos"))

        return {"data": row}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching finisher drawing sliver weight by id")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/fin_draw_sliver_wt_delete/{fin_draw_sliver_wt_id}")
def fin_draw_sliver_wt_delete(
    fin_draw_sliver_wt_id: int,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Soft-delete a finisher-drawing reading (active = 0), guarding the active row."""
    try:
        existing = db.execute(
            get_fin_draw_sliver_wt_active_row_query(),
            {"id": fin_draw_sliver_wt_id},
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail=NOT_FOUND_MSG)

        db.execute(
            soft_delete_fin_draw_sliver_wt_query(),
            {"id": fin_draw_sliver_wt_id, "updated_by": token_data.get("user_id")},
        )
        db.commit()
        return {"data": {"message": "Deleted"}}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error deleting finisher drawing sliver weight reading")
        raise HTTPException(status_code=500, detail=str(e))
