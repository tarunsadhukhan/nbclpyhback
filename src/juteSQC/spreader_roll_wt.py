"""R-08-04 Spreader Roll Weight QC capture endpoints (jute SQC module).

QC operators record exactly 10 roll-weight readings (kg) plus the parallel 10
MR% readings for a spreader bench sample. Each reading is moisture-corrected to a
standard MR basis, then the sample's average / sample-stdev / CV and a 6-bucket
weight histogram (observed + corrected) are computed server-side and PERSISTED on
the saved row (insert-only + compute-on-read, mirroring Morrah / R-08-01).

Standards are pulled from masters at save and SNAPSHOTTED onto the row so historic
rows survive master edits:
  * std_mr_pct — from the item_id-keyed jute_spreader_quality_attr satellite
    (fallback to base 16 when absent, matching the verified worked example).
  * band edges — from spreader_machine_attr.band_edge_1..5 for the chosen machine
    (fallback to the default 55/60/65/70/75 edge set when unset).

Portal persona: get_tenant_db + get_current_user_with_refresh, {"data": ...}
responses, co_id (+ branch_id on setup) validation, None for SQL NULLs, type-cast
binds. The machine list (spreader-type, with snapshot wt_per_roll) and the
raw-jute quality list are reused from existing builders.
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
    get_spreader_machine_band_edges_query,
    get_spreader_quality_std_query,
    get_spreader_roll_wt_active_row_query,
    get_spreader_roll_wt_by_date_query,
    get_spreader_roll_wt_by_id_query,
    get_spreader_roll_wt_spells_query,
    get_spreader_roll_wt_table_query,
    get_spreader_roll_wt_table_count_query,
    soft_delete_spreader_roll_wt_query,
)
from src.models.jute import JuteSqcSpreaderRollWt

logger = logging.getLogger(__name__)

router = APIRouter()

# Constants
SAMPLE_SIZE = 10
DEFAULT_STD_MR_PCT = 16.0
DEFAULT_BAND_EDGES = [55.0, 60.0, 65.0, 70.0, 75.0]
NOT_FOUND_MSG = "Spreader roll weight reading not found"


# =============================================================================
# Pydantic models
# =============================================================================


class SpreaderRollWtCreateRequest(BaseModel):
    co_id: int
    branch_id: Optional[int] = None
    entry_date: date
    spell_id: Optional[int] = None
    mc_id: Optional[int] = None
    item_id: Optional[int] = None
    feeder_name: Optional[str] = None
    roll_weights: List[float] = Field(default_factory=list)
    mr_pcts: List[float] = Field(default_factory=list)


# =============================================================================
# Helpers
# =============================================================================


def _f(v, default: Optional[float] = None) -> Optional[float]:
    """Cast a possibly-None / Decimal value to float (None stays None)."""
    return default if v is None else float(v)


def compute_spreader_roll_wt_stats(
    observed: List[float],
    mr: List[float],
    std_mr_pct: Optional[float],
    band_edges: Optional[List[float]],
) -> dict:
    """Moisture-correct each roll-weight reading, then compute sample stats and a
    6-bucket weight histogram for both the observed and corrected series.

    Formulas (R-08-04 §2, verified worked example):
        corrected_i = obs_i * (100 + std_mr_pct) / (100 + mr_i)   # std_mr fallback 16
        avg_obs   = mean(obs)
        avg_mr    = mean(mr)
        avg_corr  = mean(corrected)
        stdev_obs  = statistics.stdev(obs)    # sample n-1; guard n<=1 -> 0.0
        stdev_corr = statistics.stdev(corrected)
        cv_pct    = stdev_corr / avg_corr     # ratio on corrected basis; guard avg_corr>0
        band_counts via 5-edge bucketer (<e1 / e1-e2 / e2+1..e3 / .. / >e5)

    band_edges falls back to [55,60,65,70,75]; std_mr_pct falls back to 16.
    """
    std_mr = DEFAULT_STD_MR_PCT if std_mr_pct is None else float(std_mr_pct)
    edges = DEFAULT_BAND_EDGES if not band_edges else [float(e) for e in band_edges]

    obs = [float(o) for o in observed]
    mr_vals = [float(m) for m in mr]

    corrected = [
        o * (100.0 + std_mr) / (100.0 + m) if (100.0 + m) != 0 else 0.0
        for o, m in zip(obs, mr_vals)
    ]

    n = len(obs)
    avg_obs = sum(obs) / n if n else 0.0
    avg_mr = sum(mr_vals) / n if n else 0.0
    avg_corr = sum(corrected) / n if n else 0.0

    stdev_obs = statistics.stdev(obs) if n > 1 else 0.0
    stdev_corr = statistics.stdev(corrected) if n > 1 else 0.0

    cv_pct = stdev_corr / avg_corr if avg_corr > 0 else 0.0

    return {
        "std_mr_pct": round(std_mr, 2),
        "band_edges": edges,
        "corrected": [round(c, 3) for c in corrected],
        "calc_avg_obs": round(avg_obs, 3),
        "calc_avg_mr_pct": round(avg_mr, 2),
        "calc_avg_corr": round(avg_corr, 3),
        "calc_stdev_obs": round(stdev_obs, 4),
        "calc_stdev_corr": round(stdev_corr, 4),
        "calc_cv_pct": round(cv_pct, 4),
        "band_counts_obs": _bucket_counts(obs, edges),
        "band_counts_corr": _bucket_counts(corrected, edges),
    }


def _bucket_counts(values: List[float], edges: List[float]) -> List[int]:
    """5-edge bucketer -> 6 counts.

    For default edges [55,60,65,70,75] the buckets are:
        <55 / 55-60 / 61-65 / 66-70 / 71-75 / >75
    A value is placed in the FIRST bucket whose upper edge it does not exceed
    (v <= e1 -> bucket 0; e1 < v <= e2 -> bucket 1; ...; v > e5 -> bucket 5).
    """
    counts = [0] * (len(edges) + 1)
    for v in values:
        placed = False
        for i, e in enumerate(edges):
            if v <= e:
                counts[i] += 1
                placed = True
                break
        if not placed:
            counts[-1] += 1
    return counts


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
    """Spreader machines with their snapshot wt_per_roll (std roll weight)."""
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
                "wt_per_roll": _f(m.get("wt_per_roll"), 0.0),
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


def _lookup_band_edges(db: Session, co_id: int, mc_id: Optional[int]) -> List[float]:
    """Per-machine band edges, falling back to the default 55/60/65/70/75 set."""
    if mc_id is None:
        return list(DEFAULT_BAND_EDGES)
    row = db.execute(
        get_spreader_machine_band_edges_query(),
        {"mc_id": int(mc_id), "co_id": int(co_id)},
    ).fetchone()
    if row is None:
        return list(DEFAULT_BAND_EDGES)
    m = dict(row._mapping)
    edges = [
        m.get("band_edge_1"),
        m.get("band_edge_2"),
        m.get("band_edge_3"),
        m.get("band_edge_4"),
        m.get("band_edge_5"),
    ]
    if any(e is None for e in edges):
        return list(DEFAULT_BAND_EDGES)
    return [float(e) for e in edges]


def _by_date_row_out(r) -> dict:
    """Shape one date-driven row, json.loads-ing the persisted readings + bands."""
    m = dict(r._mapping)
    return {
        "spreader_roll_wt_id": m["spreader_roll_wt_id"],
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
        "feeder_name": m.get("feeder_name"),
        "roll_weights": _loads(m.get("roll_weights")),
        "mr_pcts": _loads(m.get("mr_pcts")),
        "std_mr_pct": _f(m.get("std_mr_pct")),
        "calc_avg_mr_pct": _f(m.get("calc_avg_mr_pct")),
        "calc_avg_obs": _f(m.get("calc_avg_obs")),
        "calc_avg_corr": _f(m.get("calc_avg_corr")),
        "calc_stdev_obs": _f(m.get("calc_stdev_obs")),
        "calc_stdev_corr": _f(m.get("calc_stdev_corr")),
        "calc_cv_pct": _f(m.get("calc_cv_pct")),
        "band_counts_obs": _loads(m.get("band_counts_obs")),
        "band_counts_corr": _loads(m.get("band_counts_corr")),
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


@router.get("/get_spreader_roll_wt_setup")
def get_spreader_roll_wt_setup(
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
                get_spreader_roll_wt_by_date_query(),
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
        logger.exception("Error fetching spreader roll weight setup")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/create_spreader_roll_wt")
def create_spreader_roll_wt(
    body: SpreaderRollWtCreateRequest,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Insert one roll-weight reading; compute + persist all calc_*/band columns."""
    try:
        if len(body.roll_weights) != SAMPLE_SIZE:
            raise HTTPException(
                status_code=400,
                detail=f"Exactly {SAMPLE_SIZE} roll weights are required, got {len(body.roll_weights)}",
            )
        if len(body.mr_pcts) != SAMPLE_SIZE:
            raise HTTPException(
                status_code=400,
                detail=f"Exactly {SAMPLE_SIZE} MR% readings are required, got {len(body.mr_pcts)}",
            )
        if any(w <= 0 for w in body.roll_weights):
            raise HTTPException(status_code=400, detail="All roll weights must be positive")

        std_mr_pct = _lookup_std_mr_pct(db, body.item_id)
        band_edges = _lookup_band_edges(db, body.co_id, body.mc_id)

        stats = compute_spreader_roll_wt_stats(
            body.roll_weights, body.mr_pcts, std_mr_pct, band_edges
        )

        record = JuteSqcSpreaderRollWt(
            co_id=int(body.co_id),
            branch_id=int(body.branch_id) if body.branch_id is not None else None,
            entry_date=body.entry_date,
            spell_id=int(body.spell_id) if body.spell_id is not None else None,
            mc_id=int(body.mc_id) if body.mc_id is not None else None,
            item_id=int(body.item_id) if body.item_id is not None else None,
            feeder_name=body.feeder_name,
            roll_weights=json.dumps([float(w) for w in body.roll_weights]),
            mr_pcts=json.dumps([float(m) for m in body.mr_pcts]),
            std_mr_pct=stats["std_mr_pct"],
            calc_avg_mr_pct=stats["calc_avg_mr_pct"],
            calc_avg_obs=stats["calc_avg_obs"],
            calc_avg_corr=stats["calc_avg_corr"],
            calc_stdev_obs=stats["calc_stdev_obs"],
            calc_stdev_corr=stats["calc_stdev_corr"],
            calc_cv_pct=stats["calc_cv_pct"],
            band_counts_obs=json.dumps(stats["band_counts_obs"]),
            band_counts_corr=json.dumps(stats["band_counts_corr"]),
            updated_by=token_data.get("user_id"),
        )

        db.add(record)
        db.commit()
        db.refresh(record)

        return {
            "data": {
                "message": "Spreader roll weight QC log created successfully",
                "spreader_roll_wt_id": record.spreader_roll_wt_id,
            }
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error creating spreader roll weight QC log")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_spreader_roll_wt_table")
def get_spreader_roll_wt_table(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Paginated table of saved roll-weight rows (page / limit / search)."""
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
            get_spreader_roll_wt_table_count_query(search=search), params
        ).fetchone()
        total = total_row.total if total_row else 0

        result = db.execute(
            get_spreader_roll_wt_table_query(search=search), params
        ).fetchall()
        rows = [dict(r._mapping) for r in result]

        return {"data": rows, "total": total, "page": page, "page_size": limit}
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid pagination parameter")
    except Exception as e:
        logger.exception("Error fetching spreader roll weight table")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_spreader_roll_wt_by_id")
def get_spreader_roll_wt_by_id(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """One saved row with readings + band JSON parsed."""
    raw_id = request.query_params.get("id")
    if not raw_id:
        raise HTTPException(status_code=400, detail="id is required")
    try:
        spreader_roll_wt_id = int(raw_id)
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
            get_spreader_roll_wt_by_id_query(),
            {"spreader_roll_wt_id": spreader_roll_wt_id, "co_id": co_id},
        ).fetchone()
        if not result:
            raise HTTPException(status_code=404, detail=NOT_FOUND_MSG)

        row = dict(result._mapping)
        row["roll_weights"] = _loads(row.get("roll_weights"))
        row["mr_pcts"] = _loads(row.get("mr_pcts"))
        row["band_counts_obs"] = _loads(row.get("band_counts_obs"))
        row["band_counts_corr"] = _loads(row.get("band_counts_corr"))

        return {"data": row}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching spreader roll weight by id")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_spreader_roll_wt_by_date")
def get_spreader_roll_wt_by_date(
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
            get_spreader_roll_wt_by_date_query(),
            {"co_id": co_id, "entry_date": entry_date, "branch_id": branch_id},
        ).fetchall()
        # Wrap rows under "readings" (the FE useSqcRollWtByDate hook + the
        # SpreaderRollWtByDateResponse type both read resp.data.readings).
        return {"data": {"readings": [_by_date_row_out(r) for r in rows]}}
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid entry_date format")
    except Exception as e:
        logger.exception("Error fetching spreader roll weight by date")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/spreader_roll_wt_delete/{spreader_roll_wt_id}")
def spreader_roll_wt_delete(
    spreader_roll_wt_id: int,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Soft-delete a roll-weight reading (active = 0), guarding the active row."""
    try:
        existing = db.execute(
            get_spreader_roll_wt_active_row_query(),
            {"id": spreader_roll_wt_id},
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail=NOT_FOUND_MSG)

        db.execute(
            soft_delete_spreader_roll_wt_query(),
            {"id": spreader_roll_wt_id, "updated_by": token_data.get("user_id")},
        )
        db.commit()
        return {"data": {"message": "Deleted"}}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error deleting spreader roll weight reading")
        raise HTTPException(status_code=500, detail=str(e))
