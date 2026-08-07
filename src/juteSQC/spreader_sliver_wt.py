"""R-08-03 Spreader Roll Sliver Weight QC capture endpoints (jute SQC module).

Second report of the Sliver/Roll-weight family (R-08-04 Spreader Roll Weight is
the template). QC operators record a VARIABLE 1-12 sliver-weight readings
(lb/100yds) plus the parallel MR% readings for a spreader bench sample. Each
reading is moisture-corrected to a standard MR basis, then the sample's
avg_obs / avg_corr / avg_mr / sample-stdev (corrected) / CV% are computed
server-side and PERSISTED on the saved row (insert-only + compute-on-read,
mirroring Morrah / R-08-04). Unlike R-08-04 there are NO weight bands / buckets.

Standards: std_mr_pct is pulled from the item_id-keyed jute_spreader_quality_attr
satellite at save and SNAPSHOTTED onto the row (fallback to base 16 when absent),
so historic rows survive master edits. No new standards table — R-08-03 reuses
the R-08-04 satellite.

Units are lb/100yds with a 5-yd sample length; both are header constants the
operator's already-scaled value flows into (no system x20). sample_length_yds
(default 5), weight_basis ("LB/100YDS") and a free-text category are stored as
nullable header constants on the record.

Portal persona: get_tenant_db + get_current_user_with_refresh, {"data": ...}
responses, co_id (+ branch_id on setup) validation, None for SQL NULLs, type-cast
binds. The machine list (spreader-type) and the raw-jute quality list are reused
from existing builders.
"""

import json
import logging
import statistics
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.authorization.utils import get_current_user_with_refresh
from src.config.db import get_tenant_db
from src.juteProduction.constants import SPREADER_MACHINE_TYPE_NAME
from src.juteProduction.query import get_spreader_machines_query
from src.juteSQC.query import (
    get_morrah_wt_jute_qualities_query,
    get_spreader_quality_std_query,
    get_spreader_roll_wt_spells_query,
    get_spreader_sliver_wt_active_row_query,
    get_spreader_sliver_wt_by_date_query,
    get_spreader_sliver_wt_by_id_query,
    get_spreader_sliver_wt_table_count_query,
    get_spreader_sliver_wt_table_query,
    soft_delete_spreader_sliver_wt_query,
)
from src.models.jute import JuteSqcSpreaderSliverWt

logger = logging.getLogger(__name__)

router = APIRouter()

# Constants
MIN_READINGS = 1
MAX_READINGS = 12
DEFAULT_STD_MR_PCT = 16.0
DEFAULT_SAMPLE_LENGTH_YDS = 5.0
DEFAULT_WEIGHT_BASIS = "LB/100YDS"
NOT_FOUND_MSG = "Spreader sliver weight reading not found"


# =============================================================================
# Pydantic models
# =============================================================================


class SpreaderSliverWtCreateRequest(BaseModel):
    co_id: int
    branch_id: Optional[int] = None
    entry_date: date
    spell_id: Optional[int] = None
    category: Optional[str] = None
    mc_id: Optional[int] = None
    item_id: Optional[int] = None
    sample_length_yds: Optional[float] = None
    weight_basis: Optional[str] = None
    observed_weights: List[float] = Field(default_factory=list)
    mr_pcts: List[float] = Field(default_factory=list)


# =============================================================================
# Helpers
# =============================================================================


def _f(v, default: Optional[float] = None) -> Optional[float]:
    """Cast a possibly-None / Decimal value to float (None stays None)."""
    return default if v is None else float(v)


def compute_spreader_sliver_stats(
    observed: List[float],
    mr: List[float],
    std_mr_pct: Optional[float],
) -> dict:
    """Moisture-correct each sliver-weight reading, then compute sample stats.

    No weight bands (unlike R-08-04). Formulas (R-08-03 §2; verified worked
    example: 20.32 * 116 / 129 = 18.27):
        corrected_i = obs_i * (100 + std_mr_pct) / (100 + mr_i)   # std_mr fallback 16
        avg_obs   = mean(obs)
        avg_corr  = mean(corrected)
        avg_mr    = mean(mr)
        stdev     = statistics.stdev(corrected)   # sample n-1 on corrected; guard n<=1 -> 0.0
        cv_pct    = stdev / avg_corr              # ratio on corrected basis; guard avg_corr>0

    std_mr_pct falls back to 16.
    """
    std_mr = DEFAULT_STD_MR_PCT if std_mr_pct is None else float(std_mr_pct)

    obs = [float(o) for o in observed]
    mr_vals = [float(m) for m in mr]

    corrected = [
        o * (100.0 + std_mr) / (100.0 + m) if (100.0 + m) != 0 else 0.0
        for o, m in zip(obs, mr_vals)
    ]

    n = len(obs)
    avg_obs = sum(obs) / n if n else 0.0
    avg_corr = sum(corrected) / n if n else 0.0
    avg_mr = sum(mr_vals) / n if n else 0.0

    stdev = statistics.stdev(corrected) if n > 1 else 0.0

    cv_pct = stdev / avg_corr if avg_corr > 0 else 0.0

    return {
        "std_mr_pct": round(std_mr, 2),
        "corrected": [round(c, 3) for c in corrected],
        "calc_avg_obs": round(avg_obs, 3),
        "calc_avg_corr": round(avg_corr, 3),
        "calc_avg_mr": round(avg_mr, 2),
        "calc_stdev": round(stdev, 4),
        "calc_cv_pct": round(cv_pct, 4),
    }


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
    """Spreader machines (reusing the shared builder; wt_per_roll unused here)."""
    machines = []
    for r in db.execute(
        get_spreader_machines_query(),
        {"co_id": co_id, "spreader_type": SPREADER_MACHINE_TYPE_NAME, "branch_id": branch_id},
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


def _fetch_qualities(db: Session, co_id: int) -> list:
    """Raw-jute quality (QUALITY) picker rows, reusing the Morrah builder."""
    qualities = []
    for r in db.execute(
        get_morrah_wt_jute_qualities_query(), {"co_id": co_id}
    ).fetchall():
        m = dict(r._mapping)
        qualities.append(
            {
                "item_id": m["item_id"],
                "item_name": m.get("item_name"),
                "item_code": m.get("item_code"),
            }
        )
    return qualities


def _lookup_std_mr_pct(db: Session, item_id: Optional[int]) -> float:
    """std_mr_pct for a raw-jute quality, falling back to base 16."""
    if item_id is None:
        return DEFAULT_STD_MR_PCT
    row = db.execute(
        get_spreader_quality_std_query(), {"item_id": int(item_id)}
    ).fetchone()
    if row is None:
        return DEFAULT_STD_MR_PCT
    val = row._mapping.get("std_mr_pct")
    return DEFAULT_STD_MR_PCT if val is None else float(val)


def _by_date_row_out(r) -> dict:
    """Shape one date-driven row, json.loads-ing the persisted readings."""
    m = dict(r._mapping)
    return {
        "spreader_sliver_wt_id": m["spreader_sliver_wt_id"],
        "co_id": m["co_id"],
        "branch_id": m.get("branch_id"),
        "entry_date": str(m["entry_date"]) if m.get("entry_date") is not None else None,
        "spell_id": m.get("spell_id"),
        "spell_code": m.get("spell_code"),
        "category": m.get("category"),
        "mc_id": m.get("mc_id"),
        "machine_name": m.get("machine_name"),
        "mech_code": m.get("mech_code"),
        "item_id": m.get("item_id"),
        "jute_quality": m.get("jute_quality"),
        "item_code": m.get("item_code"),
        "sample_length_yds": _f(m.get("sample_length_yds")),
        "weight_basis": m.get("weight_basis"),
        "observed_weights": _loads(m.get("observed_weights")),
        "mr_pcts": _loads(m.get("mr_pcts")),
        "std_mr_pct": _f(m.get("std_mr_pct")),
        "calc_avg_obs": _f(m.get("calc_avg_obs")),
        "calc_avg_corr": _f(m.get("calc_avg_corr")),
        "calc_avg_mr": _f(m.get("calc_avg_mr")),
        "calc_stdev": _f(m.get("calc_stdev")),
        "calc_cv_pct": _f(m.get("calc_cv_pct")),
    }


def _loads(v):
    """json.loads a persisted JSON-as-string column (None / non-str passes through)."""
    if v and isinstance(v, str):
        try:
            return json.loads(v)
        except (ValueError, TypeError):
            return v
    return v


# =============================================================================
# Endpoints
# =============================================================================


@router.get("/get_spreader_sliver_wt_setup")
def get_spreader_sliver_wt_setup(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Picker data (spells / machines / qualities) + the day's existing entries."""
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
        qualities = _fetch_qualities(db, co_id)

        entries = []
        if parsed_date is not None:
            rows = db.execute(
                get_spreader_sliver_wt_by_date_query(),
                {"co_id": co_id, "entry_date": parsed_date, "branch_id": branch_id},
            ).fetchall()
            entries = [_by_date_row_out(r) for r in rows]

        return {
            "data": {
                "spells": spells,
                "machines": machines,
                "qualities": qualities,
                "entries": entries,
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching spreader sliver weight setup")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/create_spreader_sliver_wt")
def create_spreader_sliver_wt(
    body: SpreaderSliverWtCreateRequest,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Insert one sliver-weight reading; compute + persist all calc_* columns."""
    try:
        n = len(body.observed_weights)
        if n < MIN_READINGS or n > MAX_READINGS:
            raise HTTPException(
                status_code=400,
                detail=f"Between {MIN_READINGS} and {MAX_READINGS} sliver weights are required, got {n}",
            )
        if len(body.mr_pcts) != n:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"observed_weights and mr_pcts must have equal length, got "
                    f"{n} and {len(body.mr_pcts)}"
                ),
            )
        if any(w <= 0 for w in body.observed_weights):
            raise HTTPException(status_code=400, detail="All sliver weights must be positive")
        if any(m < 0 for m in body.mr_pcts):
            raise HTTPException(status_code=400, detail="All MR% readings must be non-negative")

        std_mr_pct = _lookup_std_mr_pct(db, body.item_id)

        stats = compute_spreader_sliver_stats(
            body.observed_weights, body.mr_pcts, std_mr_pct
        )

        sample_length = (
            float(body.sample_length_yds)
            if body.sample_length_yds is not None
            else DEFAULT_SAMPLE_LENGTH_YDS
        )
        weight_basis = body.weight_basis if body.weight_basis else DEFAULT_WEIGHT_BASIS

        record = JuteSqcSpreaderSliverWt(
            co_id=int(body.co_id),
            branch_id=int(body.branch_id) if body.branch_id is not None else None,
            entry_date=body.entry_date,
            spell_id=int(body.spell_id) if body.spell_id is not None else None,
            category=body.category,
            mc_id=int(body.mc_id) if body.mc_id is not None else None,
            item_id=int(body.item_id) if body.item_id is not None else None,
            sample_length_yds=sample_length,
            weight_basis=weight_basis,
            observed_weights=json.dumps([float(w) for w in body.observed_weights]),
            mr_pcts=json.dumps([float(m) for m in body.mr_pcts]),
            std_mr_pct=stats["std_mr_pct"],
            calc_avg_obs=stats["calc_avg_obs"],
            calc_avg_corr=stats["calc_avg_corr"],
            calc_avg_mr=stats["calc_avg_mr"],
            calc_stdev=stats["calc_stdev"],
            calc_cv_pct=stats["calc_cv_pct"],
            updated_by=token_data.get("user_id"),
        )

        db.add(record)
        db.commit()
        db.refresh(record)

        return {
            "data": {
                "message": "Spreader sliver weight QC log created successfully",
                "spreader_sliver_wt_id": record.spreader_sliver_wt_id,
            }
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error creating spreader sliver weight QC log")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_spreader_sliver_wt_table")
def get_spreader_sliver_wt_table(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Paginated table of saved sliver-weight rows (page / limit / search)."""
    co_id = _require_co_id(request)
    try:
        page = max(1, int(request.query_params.get("page", "1")))
        limit = max(1, min(100, int(request.query_params.get("limit", "10"))))
        offset = (page - 1) * limit
        search = request.query_params.get("search")

        params = {"co_id": co_id, "limit": limit, "offset": offset}
        if search:
            params["search"] = f"%{search}%"

        total_row = db.execute(
            get_spreader_sliver_wt_table_count_query(search=search), params
        ).fetchone()
        total = total_row.total if total_row else 0

        result = db.execute(
            get_spreader_sliver_wt_table_query(search=search), params
        ).fetchall()
        rows = [dict(r._mapping) for r in result]

        return {"data": rows, "total": total, "page": page, "page_size": limit}
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid pagination parameter")
    except Exception as e:
        logger.exception("Error fetching spreader sliver weight table")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_spreader_sliver_wt_by_id")
def get_spreader_sliver_wt_by_id(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """One saved row with readings JSON parsed."""
    raw_id = request.query_params.get("id")
    if not raw_id:
        raise HTTPException(status_code=400, detail="id is required")
    try:
        spreader_sliver_wt_id = int(raw_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid id format")

    # co_id is optional but, when supplied, scopes the lookup to the tenant
    # company so a guessed id can't surface another company's row.
    raw_co_id = request.query_params.get("co_id")
    try:
        co_id = int(raw_co_id) if raw_co_id else None
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid co_id format")

    try:
        result = db.execute(
            get_spreader_sliver_wt_by_id_query(),
            {"spreader_sliver_wt_id": spreader_sliver_wt_id, "co_id": co_id},
        ).fetchone()
        if not result:
            raise HTTPException(status_code=404, detail=NOT_FOUND_MSG)

        row = dict(result._mapping)
        row["observed_weights"] = _loads(row.get("observed_weights"))
        row["mr_pcts"] = _loads(row.get("mr_pcts"))

        return {"data": row}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching spreader sliver weight by id")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_spreader_sliver_wt_by_date")
def get_spreader_sliver_wt_by_date(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Date-driven rows for the summary grid (branch optional)."""
    co_id = _require_co_id(request)
    branch_id = _optional_branch_id(request)
    entry_date = _require_entry_date(request)
    try:
        rows = db.execute(
            get_spreader_sliver_wt_by_date_query(),
            {"co_id": co_id, "entry_date": entry_date, "branch_id": branch_id},
        ).fetchall()
        # Wrap rows under "readings" (the FE useSqcSliverWtByDate hook + the
        # SpreaderSliverWtByDateResponse type both read resp.data.readings).
        return {"data": {"readings": [_by_date_row_out(r) for r in rows]}}
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid entry_date format")
    except Exception as e:
        logger.exception("Error fetching spreader sliver weight by date")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/spreader_sliver_wt_delete/{spreader_sliver_wt_id}")
def spreader_sliver_wt_delete(
    spreader_sliver_wt_id: int,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Soft-delete a sliver-weight reading (active = 0), guarding the active row."""
    try:
        existing = db.execute(
            get_spreader_sliver_wt_active_row_query(),
            {"id": spreader_sliver_wt_id},
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail=NOT_FOUND_MSG)

        db.execute(
            soft_delete_spreader_sliver_wt_query(),
            {"id": spreader_sliver_wt_id, "updated_by": token_data.get("user_id")},
        )
        db.commit()
        return {"data": {"message": "Deleted"}}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error deleting spreader sliver weight reading")
        raise HTTPException(status_code=500, detail=str(e))
