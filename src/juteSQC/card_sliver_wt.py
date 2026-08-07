"""R-08-07A Inter Card & Tow Breaker Sliver Weight QC capture endpoints (jute SQC module).

Carding-stage sliver-weight uniformity for the three sub-sections INTER_CARD / TOW_BREAKER /
HOPPER. Clone of breaker_card_swt.py with ONE structural delta: card_side -> `section`. Each
reading-set records EXACTLY 4 sliver-cut weights (LB per 5 yds) + 4 MR%, moisture-corrects
each cut to the quality's STD MR%, then the row's avg-observed / avg-MR / avg-corrected weight
/ sample-stdev (on the corrected cuts) / CV% and a CV-band pass flag are computed server-side
and PERSISTED (insert-only + compute-on-read, like breaker / spreader / morrah).

`section` is BOTH the stored sub-table label AND the (item_id, process) key into
jute_draw_quality_std — the SAME line quality carries a different band/MR per carding
sub-process. NO machine type is seeded: the picker is the shared carding pool (all active
branch machines); the operator picks the section. std MR falls back to 20 (owner decision).

Two aggregation blocks are recomputed at READ from that date's rows (NOT stored):
  * SECTION AVG — mean of per-row Avg / MR% / COR WT / sdev / CV% across the section's rows
    (matches the R07A sheet's section footer).
  * per-quality GRAND AVERAGE — pooled corrected cuts, like breaker card.

Quality is linked to a BATCH (jute_batch_plan — a named mix of raw-jute qualities,
branch-scoped) instead of a single line quality. A batch has no single std, so std MR falls
back to 20 and the CV band stays unevaluated (cv_within_band NULL); the per-batch GRAND
AVERAGE regroups by batch_plan_id. The section AVG block is unchanged.

Portal persona: get_tenant_db + get_current_user_with_refresh, {"data": ...} responses,
co_id (+ branch_id on setup) validation, None for SQL NULLs, type-cast binds. The spell and
shared-machine builders are REUSED from the breaker family.
"""

import json
import logging
import statistics
from collections import OrderedDict
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.authorization.utils import get_current_user_with_refresh
from src.config.db import get_tenant_db
from src.juteSQC.constants import CARD_SLIVER_SECTIONS
from src.juteSQC.query import (
    get_card_section_batches_query,
    get_card_section_machines_query,
    get_card_sliver_wt_active_row_query,
    get_card_sliver_wt_by_date_query,
    get_card_sliver_wt_by_id_query,
    get_card_sliver_wt_table_count_query,
    get_card_sliver_wt_table_query,
    get_spreader_roll_wt_spells_query,
    soft_delete_card_sliver_wt_query,
)
from src.models.jute import JuteSqcCardSliverWt

logger = logging.getLogger(__name__)

router = APIRouter()

# Constants
SAMPLE_SIZE = 4
DEFAULT_STD_MR_PCT = 20.0  # owner decision (universal Sacking std); satellite rows override
NOT_FOUND_MSG = "Card sliver weight reading not found"


# =============================================================================
# Pydantic models
# =============================================================================


class CardSliverWtRow(BaseModel):
    """One (section, machine, spell, batch) reading-set: EXACTLY 4 cut weights + 4 MR%.

    Quality is linked via batch_plan_id (jute_batch_plan) — the carding/drawing change from a
    single line quality. item_id is kept optional for back-compat but is no longer set by the
    form."""

    section: str
    mc_id: Optional[int] = None
    spell_id: Optional[int] = None
    batch_plan_id: Optional[int] = None
    item_id: Optional[int] = None
    weights: List[float] = Field(default_factory=list)
    mr_pcts: List[float] = Field(default_factory=list)


class CardSliverWtCreateRequest(BaseModel):
    """One save = the day's grid: a header (co/branch/date) + an ARRAY of rows."""

    co_id: int
    branch_id: Optional[int] = None
    entry_date: date
    rows: List[CardSliverWtRow] = Field(default_factory=list)


# =============================================================================
# Helpers — formulas
# =============================================================================


def _f(v, default: Optional[float] = None) -> Optional[float]:
    """Cast a possibly-None / Decimal value to float (None stays None)."""
    return default if v is None else float(v)


def _corrected_cuts(weights: List[float], mr: List[float], std_mr: float) -> List[float]:
    """The 4 moisture-corrected cuts: wt_i * (100 + std_mr) / (100 + mr_i)."""
    return [
        w * (100.0 + std_mr) / (100.0 + m) if (100.0 + m) != 0 else 0.0
        for w, m in zip(weights, mr)
    ]


def compute_card_sliver_stats(
    weights: List[float],
    mr: List[float],
    std_mr: Optional[float],
    std_cv_low: Optional[float],
    std_cv_high: Optional[float],
) -> dict:
    """Per-row card-sliver stats (R-08-07A §4, avg-then-correct path).

    Formulas (verified against the cached sheet — Inter-Card row1 SACKING WEFT std16:
    Avg 20.723, MR% 26.75, COR WT 19.617, sdev 0.38128, CV% 0.01944):
        calc_wt      = mean(weights)
        calc_mr_pct  = mean(mr)
        calc_corr_wt = calc_wt * (100 + std_mr) / (100 + calc_mr_pct)
        corrected_i  = wt_i * (100 + std_mr) / (100 + mr_i)
        calc_sdev    = statistics.stdev(corrected_i)  (sample n-1; guard n<=1 -> 0.0)
        calc_cv_pct  = calc_sdev / calc_corr_wt       (ratio; render x100; guard corr>0)
        cv_within_band = (std_cv_high is not None) ? (calc_cv_pct*100 <= std_cv_high) : None

    std_mr falls back to 20 (owner decision). cv_within_band is None when no band high edge
    is seeded (the high edge is the upper tolerance; the low edge is informational).
    """
    std = DEFAULT_STD_MR_PCT if std_mr is None else float(std_mr)

    wt_vals = [float(w) for w in weights]
    mr_vals = [float(m) for m in mr]

    n = len(wt_vals)
    calc_wt = sum(wt_vals) / n if n else 0.0
    calc_mr = sum(mr_vals) / n if n else 0.0
    calc_corr_wt = (
        calc_wt * (100.0 + std) / (100.0 + calc_mr) if (100.0 + calc_mr) != 0 else 0.0
    )

    corrected = _corrected_cuts(wt_vals, mr_vals, std)
    calc_sdev = statistics.stdev(corrected) if n > 1 else 0.0
    calc_cv_pct = calc_sdev / calc_corr_wt if calc_corr_wt > 0 else 0.0

    cv_within_band: Optional[int]
    if std_cv_high is None:
        cv_within_band = None
    else:
        cv_within_band = 1 if (calc_cv_pct * 100.0 <= float(std_cv_high)) else 0

    return {
        "std_mr_pct": round(std, 2),
        "std_cv_low": None if std_cv_low is None else round(float(std_cv_low), 2),
        "std_cv_high": None if std_cv_high is None else round(float(std_cv_high), 2),
        "corrected": [round(c, 3) for c in corrected],
        "calc_wt": round(calc_wt, 3),
        "calc_mr_pct": round(calc_mr, 2),
        "calc_corr_wt": round(calc_corr_wt, 3),
        "calc_sdev": round(calc_sdev, 4),
        "calc_cv_pct": round(calc_cv_pct, 4),
        "cv_within_band": cv_within_band,
    }


def compute_section_averages(rows: List[dict]) -> List[dict]:
    """Per-SECTION footer block, recomputed at read (R-08-07A §4).

    For each section across that date's rows:
        AVG OBS  = mean(calc_wt for the section's rows)
        AVG MR%  = mean(calc_mr_pct ...)
        AVG CORR = mean(calc_corr_wt ...)   (cached Inter-Card 3 rows: 17.880)
        AVG SDEV = mean(calc_sdev ...)       (the spec footer's mean-of-row-sdev)
        AVG CV%  = mean(calc_cv_pct ...)     (mean of per-row CV ratios; render ×100)

    Unweighted mean of the per-row stats (spec §8 default; not weight-weighted).
    """
    groups: "OrderedDict[str, dict]" = OrderedDict()
    for r in rows:
        section = r.get("section")
        if section is None:
            continue
        g = groups.setdefault(
            section,
            {"section": section, "row_count": 0, "_obs": [], "_mr": [], "_corr": [], "_sdev": [], "_cv": []},
        )
        g["row_count"] += 1
        for key, col in (
            ("_obs", "calc_wt"),
            ("_mr", "calc_mr_pct"),
            ("_corr", "calc_corr_wt"),
            ("_sdev", "calc_sdev"),
            ("_cv", "calc_cv_pct"),
        ):
            v = _f(r.get(col))
            if v is not None:
                g[key].append(v)

    out: List[dict] = []
    for g in groups.values():
        out.append(
            {
                "section": g["section"],
                "row_count": g["row_count"],
                "avg_obs": round(sum(g["_obs"]) / len(g["_obs"]), 3) if g["_obs"] else None,
                "avg_mr_pct": round(sum(g["_mr"]) / len(g["_mr"]), 2) if g["_mr"] else None,
                "avg_corr_wt": round(sum(g["_corr"]) / len(g["_corr"]), 3) if g["_corr"] else None,
                "avg_sdev": round(sum(g["_sdev"]) / len(g["_sdev"]), 4) if g["_sdev"] else None,
                "avg_cv_pct": round(sum(g["_cv"]) / len(g["_cv"]), 4) if g["_cv"] else None,
            }
        )
    return out


def compute_grand_averages(rows: List[dict]) -> List[dict]:
    """Per-BATCH GRAND AVERAGE block, recomputed at read (mirrors breaker card §2).

    Quality is linked via batch, so the grand-average regroups by batch_plan_id (was item_id).
    For each batch across that date's rows:
        OBS  = mean(calc_wt), MR% = mean(calc_mr_pct), CORR = mean(calc_corr_wt)
        CV%  = stdev(ALL pooled corrected cuts) / mean(pooled corrected cuts)
               (pooled, NOT the mean of per-row CVs — re-derived from each row's
                stored weights/mr/std_mr). Rows with no batch_plan_id are skipped.
    """
    groups: "OrderedDict[int, dict]" = OrderedDict()
    for r in rows:
        batch_plan_id = r.get("batch_plan_id")
        if batch_plan_id is None:
            continue
        g = groups.setdefault(
            int(batch_plan_id),
            {
                "batch_plan_id": int(batch_plan_id),
                "batch_plan_name": r.get("batch_plan_name"),
                "row_count": 0,
                "std_cv_high": None,
                "_obs": [],
                "_mr": [],
                "_corr": [],
                "_pooled": [],
            },
        )
        g["row_count"] += 1
        if g["std_cv_high"] is None:
            g["std_cv_high"] = _f(r.get("std_cv_high"))

        calc_wt = _f(r.get("calc_wt"))
        calc_mr = _f(r.get("calc_mr_pct"))
        calc_corr = _f(r.get("calc_corr_wt"))
        if calc_wt is not None:
            g["_obs"].append(calc_wt)
        if calc_mr is not None:
            g["_mr"].append(calc_mr)
        if calc_corr is not None:
            g["_corr"].append(calc_corr)

        weights = r.get("weights") or []
        mr_vals = r.get("mr_pcts") or []
        std_mr = _f(r.get("std_mr_pct"), DEFAULT_STD_MR_PCT)
        if isinstance(weights, list) and isinstance(mr_vals, list) and weights and mr_vals:
            g["_pooled"].extend(
                _corrected_cuts(
                    [float(w) for w in weights], [float(m) for m in mr_vals], float(std_mr)
                )
            )

    out: List[dict] = []
    for g in groups.values():
        obs = g["_obs"]
        mr = g["_mr"]
        corr = g["_corr"]
        pooled = g["_pooled"]

        grand_obs = round(sum(obs) / len(obs), 3) if obs else None
        grand_mr = round(sum(mr) / len(mr), 2) if mr else None
        grand_corr = round(sum(corr) / len(corr), 3) if corr else None

        if pooled:
            pooled_mean = sum(pooled) / len(pooled)
            pooled_sdev = statistics.stdev(pooled) if len(pooled) > 1 else 0.0
            grand_cv = round(pooled_sdev / pooled_mean, 4) if pooled_mean > 0 else 0.0
        else:
            grand_cv = None

        std_cv_high = g["std_cv_high"]
        cv_within_band = (
            (1 if grand_cv * 100 <= std_cv_high else 0)
            if (std_cv_high is not None and grand_cv is not None)
            else None
        )

        out.append(
            {
                "batch_plan_id": g["batch_plan_id"],
                "batch_plan_name": g["batch_plan_name"],
                "row_count": g["row_count"],
                "grand_obs": grand_obs,
                "grand_mr_pct": grand_mr,
                "grand_corr_wt": grand_corr,
                "grand_cv_pct": grand_cv,
                "std_cv_high": std_cv_high,
                "cv_within_band": cv_within_band,
            }
        )
    return out


# =============================================================================
# Helpers — request parsing / fetchers
# =============================================================================


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


def _fetch_machines(db: Session, co_id: int, branch_id: Optional[int]) -> list:
    """Shared carding-pool machines (no machine-type filter — section is a label)."""
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
    """Batch-plan (jute_batch_plan) picker rows — the carding/drawing quality linkage.

    Branch-scoped (jute_batch_plan has no co_id). A batch is a named mix of raw-jute
    qualities, so it carries no single std MR%/CV band: std MR falls back to 20 and the band
    stays unevaluated (cv_within_band NULL) at this stage, unchanged from before."""
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
        "card_sliver_wt_id": m["card_sliver_wt_id"],
        "co_id": m["co_id"],
        "branch_id": m.get("branch_id"),
        "entry_date": str(m["entry_date"]) if m.get("entry_date") is not None else None,
        "section": m.get("section"),
        "spell_id": m.get("spell_id"),
        "spell_code": m.get("spell_code"),
        "mc_id": m.get("mc_id"),
        "machine_name": m.get("machine_name"),
        "mech_code": m.get("mech_code"),
        "item_id": m.get("item_id"),
        "jute_quality": m.get("jute_quality"),
        "item_code": m.get("item_code"),
        "batch_plan_id": m.get("batch_plan_id"),
        "batch_plan_name": m.get("batch_plan_name"),
        "weights": _loads(m.get("weights")),
        "mr_pcts": _loads(m.get("mr_pcts")),
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


@router.get("/get_card_sliver_wt_setup")
def get_card_sliver_wt_setup(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Picker data (sections / spells / shared carding machines / batch plans) + the day's
    existing rows when entry_date is supplied."""
    co_id = _require_co_id(request)
    branch_id = _require_branch_id(request)
    entry_date = request.query_params.get("entry_date")
    try:
        parsed_date = date.fromisoformat(entry_date) if entry_date else None
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid entry_date format")

    try:
        spells = _fetch_spells(db, branch_id)
        machines = _fetch_machines(db, co_id, branch_id)
        batches = _fetch_batches(db, branch_id)

        entries = []
        if parsed_date is not None:
            rows = db.execute(
                get_card_sliver_wt_by_date_query(),
                {"co_id": co_id, "entry_date": parsed_date, "branch_id": branch_id},
            ).fetchall()
            entries = [_by_date_row_out(r) for r in rows]

        return {
            "data": {
                "sections": list(CARD_SLIVER_SECTIONS),
                "spells": spells,
                "machines": machines,
                "batches": batches,
                "entries": entries,
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching card sliver weight setup")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/create_card_sliver_wt")
def create_card_sliver_wt(
    body: CardSliverWtCreateRequest,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Insert MANY rows (the day's grid) in one save; compute + persist each row's calc_*
    + cv_within_band. Per row: validate section ∈ {INTER_CARD, TOW_BREAKER, HOPPER}, EXACTLY
    4 (wt, mr) pairs, wt>0, mr>=0; store batch_plan_id (the quality linkage); compute with std
    MR fallback 20 and no CV band, and insert. Returns the inserted ids."""
    try:
        if not body.rows:
            raise HTTPException(status_code=400, detail="At least one row is required")
        if body.branch_id is None:
            raise HTTPException(status_code=400, detail="branch_id is required")

        records: List[JuteSqcCardSliverWt] = []
        for idx, row in enumerate(body.rows):
            section = (row.section or "").strip().upper()
            if section not in CARD_SLIVER_SECTIONS:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Row {idx + 1}: section must be one of "
                        f"{', '.join(CARD_SLIVER_SECTIONS)}, got '{row.section}'"
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

            # Quality is linked via batch (a mix of qualities) -> no single (item_id, section)
            # std row to snapshot; std MR falls back to 20 and the CV band stays unevaluated.
            stats = compute_card_sliver_stats(
                row.weights, row.mr_pcts, None, None, None
            )

            records.append(
                JuteSqcCardSliverWt(
                    co_id=int(body.co_id),
                    branch_id=int(body.branch_id) if body.branch_id is not None else None,
                    entry_date=body.entry_date,
                    section=section,
                    mc_id=int(row.mc_id) if row.mc_id is not None else None,
                    spell_id=int(row.spell_id) if row.spell_id is not None else None,
                    batch_plan_id=int(row.batch_plan_id) if row.batch_plan_id is not None else None,
                    item_id=int(row.item_id) if row.item_id is not None else None,
                    weights=json.dumps([float(w) for w in row.weights]),
                    mr_pcts=json.dumps([float(m) for m in row.mr_pcts]),
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
                "message": "Card sliver weight log(s) created successfully",
                "card_sliver_wt_ids": [rec.card_sliver_wt_id for rec in records],
                "count": len(records),
            }
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error creating card sliver weight log")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_card_sliver_wt_by_date")
def get_card_sliver_wt_by_date(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Date-driven rows + the recomputed per-section AND per-quality average blocks.

    Returns an OBJECT envelope:
    {"data": {"rows": [...], "section_averages": [...], "grand_averages": [...]}}."""
    co_id = _require_co_id(request)
    branch_id = _optional_branch_id(request)
    entry_date = _require_entry_date(request)
    try:
        result = db.execute(
            get_card_sliver_wt_by_date_query(),
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
        logger.exception("Error fetching card sliver weight by date")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_card_sliver_wt_table")
def get_card_sliver_wt_table(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Paginated table of saved card-sliver rows (page / limit / search / optional branch)."""
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
            get_card_sliver_wt_table_count_query(search=search), params
        ).fetchone()
        total = total_row.total if total_row else 0

        result = db.execute(
            get_card_sliver_wt_table_query(search=search), params
        ).fetchall()
        rows = [dict(r._mapping) for r in result]

        return {"data": rows, "total": total, "page": page, "page_size": limit}
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid pagination parameter")
    except Exception as e:
        logger.exception("Error fetching card sliver weight table")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_card_sliver_wt_by_id")
def get_card_sliver_wt_by_id(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """One saved row with readings JSON parsed (tenant-scoped via optional co_id)."""
    raw_id = request.query_params.get("id")
    if not raw_id:
        raise HTTPException(status_code=400, detail="id is required")
    try:
        card_sliver_wt_id = int(raw_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid id format")

    raw_co_id = request.query_params.get("co_id")
    try:
        co_id = int(raw_co_id) if raw_co_id else None
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid co_id format")

    try:
        result = db.execute(
            get_card_sliver_wt_by_id_query(),
            {"card_sliver_wt_id": card_sliver_wt_id, "co_id": co_id},
        ).fetchone()
        if not result:
            raise HTTPException(status_code=404, detail=NOT_FOUND_MSG)

        row = dict(result._mapping)
        row["weights"] = _loads(row.get("weights"))
        row["mr_pcts"] = _loads(row.get("mr_pcts"))

        return {"data": row}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching card sliver weight by id")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/card_sliver_wt_delete/{card_sliver_wt_id}")
def card_sliver_wt_delete(
    card_sliver_wt_id: int,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Soft-delete a card-sliver reading (active = 0), guarding the active row."""
    try:
        existing = db.execute(
            get_card_sliver_wt_active_row_query(),
            {"id": card_sliver_wt_id},
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail=NOT_FOUND_MSG)

        db.execute(
            soft_delete_card_sliver_wt_query(),
            {"id": card_sliver_wt_id, "updated_by": token_data.get("user_id")},
        )
        db.commit()
        return {"data": {"message": "Deleted"}}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error deleting card sliver weight reading")
        raise HTTPException(status_code=500, detail=str(e))
