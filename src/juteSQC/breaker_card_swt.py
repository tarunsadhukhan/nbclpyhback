"""R-08-05/06/07 Breaker Card (Coarse Side SWT) QC capture endpoints (jute SQC module).

First report of the carding/drawing sub-family — the carding stage. QC operators record,
for each (machine, spell, batch) reading-set, EXACTLY 4 sliver-cut weights (LB per 5 yds)
plus the parallel 4 MR% readings. Each cut is moisture-corrected to STD MR%, then the row's
avg-observed / avg-MR / avg-corrected weight / sample-stdev (on the corrected cuts) / CV% and
a CV-band pass flag are computed server-side and PERSISTED on the saved row (insert-only +
compute-on-read, mirroring Spreader Sliver / Morrah). A per-BATCH GRAND AVERAGE block is
recomputed at READ from that date's rows (pooled corrected cuts) — NOT stored.

Quality is linked to a BATCH (jute_batch_plan — a named mix of raw-jute qualities,
branch-scoped) instead of a single line quality. A batch has no single std, so std MR falls
back to 16 (breaker default) and the CV band stays unevaluated (cv_within_band NULL); the
grand average regroups by batch_plan_id. The save is per-branch (branch_id required) and
reads (by_date / table) are branch-scoped.

NEW vs the spreader family:
  * Breaker-card machine type (resolved by name BREAKER_CARD_MACHINE_TYPE_NAME).
  * MULTI-ROW create — one save inserts MANY rows (the day's grid).
  * Per-batch GRAND AVERAGE recomputed at read.

Portal persona: get_tenant_db + get_current_user_with_refresh, {"data": ...} responses,
co_id (+ branch_id on setup) validation, None for SQL NULLs, type-cast binds. The spell list
is reused from the spreader builder; machines + batch-plan picker use shared builders.
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
from src.juteProduction.query import get_spreader_machines_query  # noqa: F401  (pattern ref)
from src.juteSQC.constants import BREAKER_CARD_MACHINE_TYPE_NAME
from src.juteSQC.query import (
    get_breaker_card_machines_query,
    get_breaker_card_swt_active_row_query,
    get_breaker_card_swt_by_date_query,
    get_breaker_card_swt_by_id_query,
    get_breaker_card_swt_table_count_query,
    get_breaker_card_swt_table_query,
    get_card_section_batches_query,
    get_spreader_roll_wt_spells_query,
    soft_delete_breaker_card_swt_query,
)
from src.models.jute import JuteSqcBreakerCardSwt

logger = logging.getLogger(__name__)

router = APIRouter()

# Constants
SAMPLE_SIZE = 4
DEFAULT_STD_MR_PCT = 16.0
DEFAULT_CARD_SIDE = "COARSE"
NOT_FOUND_MSG = "Breaker card SWT reading not found"


# =============================================================================
# Pydantic models
# =============================================================================


class BreakerCardSwtRow(BaseModel):
    """One (machine, spell, batch) reading-set: EXACTLY 4 cut weights + 4 MR%.

    Quality is linked via batch_plan_id (jute_batch_plan) — the carding change from a single
    line quality. item_id is kept optional for back-compat but is no longer set by the form."""

    mc_id: Optional[int] = None
    spell_id: Optional[int] = None
    batch_plan_id: Optional[int] = None
    item_id: Optional[int] = None
    card_side: Optional[str] = None
    weights: List[float] = Field(default_factory=list)
    mr_pcts: List[float] = Field(default_factory=list)


class BreakerCardSwtCreateRequest(BaseModel):
    """One save = the day's grid: a header (co/branch/date) + an ARRAY of rows."""

    co_id: int
    branch_id: Optional[int] = None
    entry_date: date
    rows: List[BreakerCardSwtRow] = Field(default_factory=list)


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


def compute_breaker_card_stats(
    weights: List[float],
    mr: List[float],
    std_mr: Optional[float],
    std_cv_low: Optional[float],
    std_cv_high: Optional[float],
) -> dict:
    """Per-row breaker-card stats (R-08-05/06/07 §2, avg-then-correct path).

    Formulas (verified against the cached sheet — Row1 corr 18.26, sdev 0.795, cv 0.0436;
    Row3 corr 18.51, cv 0.0240):
        calc_wt      = mean(weights)                                # row avg observed
        calc_mr_pct  = mean(mr)                                     # row avg MR%
        calc_corr_wt = calc_wt * (100 + std_mr) / (100 + calc_mr_pct)
        corrected_i  = wt_i * (100 + std_mr) / (100 + mr_i)         # the 4 corrected cuts
        calc_sdev    = statistics.stdev(corrected_i)  (sample n-1; guard n<=1 -> 0.0)
        calc_cv_pct  = calc_sdev / calc_corr_wt       (ratio; render x100; guard corr>0)
        cv_within_band = (std_cv_high is not None) ? (calc_cv_pct*100 <= std_cv_high) : None

    std_mr falls back to 16. cv_within_band is None when no band high edge is seeded
    (the high edge is the upper tolerance; the low edge is informational).
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


def compute_grand_averages(rows: List[dict]) -> List[dict]:
    """Per-batch GRAND AVERAGE block, recomputed at read (R-08-05/06/07 §2).

    For each batch (batch_plan_id) across that date's rows:
        OBS  = mean(calc_wt for the batch's rows)
        MR%  = mean(calc_mr_pct ...)
        CORR = mean(calc_corr_wt ...)
        CV%  = stdev(ALL pooled corrected cuts) / mean(pooled corrected cuts)
               (pooled, NOT the mean of per-row CVs — needs the individual corrected cuts,
                which are re-derived from each row's stored weights/mr/std_mr)

    `rows` are the shaped by-date rows (the output of _by_date_row_out): they carry
    batch_plan_id, batch_plan_name, calc_wt/calc_mr_pct/calc_corr_wt, and the parsed
    weights/mr_pcts + std_mr_pct needed to re-pool the corrected cuts. Rows with no
    batch_plan_id are skipped.
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
        # Carry the quality's snapshot CV high edge (first non-null wins) so the
        # grand row can flag its pooled CV% against the band, like each row does.
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
    """Spell (SHIFT) picker rows, de-duplicated by spell_code (first row wins).

    Reuses the spreader spell builder (branch-scoped via the parent shift)."""
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
    """Breaker-card machines (machine_type resolved by name at runtime)."""
    machines = []
    for r in db.execute(
        get_breaker_card_machines_query(),
        {"breaker_type": BREAKER_CARD_MACHINE_TYPE_NAME, "branch_id": branch_id},
    ).fetchall():
        m = dict(r._mapping)
        machines.append(
            {
                "machine_id": m["machine_id"],
                "machine_name": m["machine_name"],
                "mech_code": m.get("mech_code"),
                "dept_id": m.get("dept_id"),
                "dept_name": m.get("dept_name"),
                "branch_id": m.get("branch_id"),
            }
        )
    return machines


def _fetch_batches(db: Session, branch_id: Optional[int]) -> list:
    """Batch-plan (jute_batch_plan) picker rows — the carding quality linkage.

    Branch-scoped (jute_batch_plan has no co_id). A batch is a named mix of raw-jute qualities,
    so it carries no single std MR%/CV band: std MR falls back to 16 (breaker default) and the
    band stays unevaluated (cv_within_band NULL)."""
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
        "breaker_card_swt_id": m["breaker_card_swt_id"],
        "co_id": m["co_id"],
        "branch_id": m.get("branch_id"),
        "entry_date": str(m["entry_date"]) if m.get("entry_date") is not None else None,
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
        "card_side": m.get("card_side"),
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


@router.get("/get_breaker_card_swt_setup")
def get_breaker_card_swt_setup(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Picker data (spells / breaker-card machines / batch plans) + the day's existing rows
    when entry_date is supplied."""
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
                get_breaker_card_swt_by_date_query(),
                {"co_id": co_id, "entry_date": parsed_date, "branch_id": branch_id},
            ).fetchall()
            entries = [_by_date_row_out(r) for r in rows]

        return {
            "data": {
                "spells": spells,
                "machines": machines,
                "batches": batches,
                "entries": entries,
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching breaker card SWT setup")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/create_breaker_card_swt")
def create_breaker_card_swt(
    body: BreakerCardSwtCreateRequest,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Insert MANY rows (the day's grid) in one save; compute + persist each row's calc_*
    + cv_within_band. Header requires branch_id (the log is saved per-branch). Per row:
    validate EXACTLY 4 (wt, mr) pairs, wt>0, mr>=0, a batch is selected; store batch_plan_id
    (the quality linkage); compute with std MR fallback 16 and no CV band, and insert. Returns
    the inserted ids."""
    try:
        if not body.rows:
            raise HTTPException(status_code=400, detail="At least one row is required")
        if body.branch_id is None:
            raise HTTPException(status_code=400, detail="branch_id is required")

        records: List[JuteSqcBreakerCardSwt] = []
        for idx, row in enumerate(body.rows):
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

            # Quality is linked via batch (a mix of qualities) -> no single (item_id, BREAKER)
            # std row to snapshot; std MR falls back to 16 and the CV band stays unevaluated.
            stats = compute_breaker_card_stats(
                row.weights, row.mr_pcts, None, None, None
            )

            records.append(
                JuteSqcBreakerCardSwt(
                    co_id=int(body.co_id),
                    branch_id=int(body.branch_id) if body.branch_id is not None else None,
                    entry_date=body.entry_date,
                    mc_id=int(row.mc_id) if row.mc_id is not None else None,
                    spell_id=int(row.spell_id) if row.spell_id is not None else None,
                    batch_plan_id=int(row.batch_plan_id) if row.batch_plan_id is not None else None,
                    item_id=int(row.item_id) if row.item_id is not None else None,
                    card_side=row.card_side if row.card_side else DEFAULT_CARD_SIDE,
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
                "message": "Breaker card SWT log(s) created successfully",
                "breaker_card_swt_ids": [rec.breaker_card_swt_id for rec in records],
                "count": len(records),
            }
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error creating breaker card SWT log")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_breaker_card_swt_by_date")
def get_breaker_card_swt_by_date(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Date-driven rows + the recomputed per-quality grand-average block.

    Returns an OBJECT envelope: {"data": {"rows": [...], "grand_averages": [...]}}."""
    co_id = _require_co_id(request)
    branch_id = _optional_branch_id(request)
    entry_date = _require_entry_date(request)
    try:
        result = db.execute(
            get_breaker_card_swt_by_date_query(),
            {"co_id": co_id, "entry_date": entry_date, "branch_id": branch_id},
        ).fetchall()
        rows = [_by_date_row_out(r) for r in result]
        grand_averages = compute_grand_averages(rows)
        return {"data": {"rows": rows, "grand_averages": grand_averages}}
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid entry_date format")
    except Exception as e:
        logger.exception("Error fetching breaker card SWT by date")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_breaker_card_swt_table")
def get_breaker_card_swt_table(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Paginated table of saved breaker-card rows (page / limit / search / optional branch)."""
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
            get_breaker_card_swt_table_count_query(search=search), params
        ).fetchone()
        total = total_row.total if total_row else 0

        result = db.execute(
            get_breaker_card_swt_table_query(search=search), params
        ).fetchall()
        rows = [dict(r._mapping) for r in result]

        return {"data": rows, "total": total, "page": page, "page_size": limit}
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid pagination parameter")
    except Exception as e:
        logger.exception("Error fetching breaker card SWT table")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_breaker_card_swt_by_id")
def get_breaker_card_swt_by_id(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """One saved row with readings JSON parsed (tenant-scoped via optional co_id)."""
    raw_id = request.query_params.get("id")
    if not raw_id:
        raise HTTPException(status_code=400, detail="id is required")
    try:
        breaker_card_swt_id = int(raw_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid id format")

    # co_id is optional but, when supplied, scopes the lookup to the tenant company so a
    # guessed id can't surface another company's row.
    raw_co_id = request.query_params.get("co_id")
    try:
        co_id = int(raw_co_id) if raw_co_id else None
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid co_id format")

    try:
        result = db.execute(
            get_breaker_card_swt_by_id_query(),
            {"breaker_card_swt_id": breaker_card_swt_id, "co_id": co_id},
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
        logger.exception("Error fetching breaker card SWT by id")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/breaker_card_swt_delete/{breaker_card_swt_id}")
def breaker_card_swt_delete(
    breaker_card_swt_id: int,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Soft-delete a breaker-card reading (active = 0), guarding the active row."""
    try:
        existing = db.execute(
            get_breaker_card_swt_active_row_query(),
            {"id": breaker_card_swt_id},
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail=NOT_FOUND_MSG)

        db.execute(
            soft_delete_breaker_card_swt_query(),
            {"id": breaker_card_swt_id, "updated_by": token_data.get("user_id")},
        )
        db.commit()
        return {"data": {"message": "Deleted"}}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error deleting breaker card SWT reading")
        raise HTTPException(status_code=500, detail=str(e))
