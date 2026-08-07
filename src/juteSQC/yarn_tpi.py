"""R-08-17 Yarn TPI & TPI CV% QC capture endpoints (jute SQC module).

A 20-reading twist-uniformity study. A group = one saved test for (date, machine, item_id)
carrying EXACTLY 20 TPI readings (cells may be null). yarn-quality linked (NOT batch —
batch was carding/drawing only). Save is insert-only (duplicates allowed); a group is
soft-deleted as a unit. count_lbs / std_tpi / tp_value are snapshotted on the header from
the form. Stats (avg/std/cv/min/max) are computed SERVER-SIDE at read from the stored
readings (RAW readings, NO MR correction).

Clones the R-08-15 QR/CV section in spinning_sqc.py (header + 20 dtl rows via lastrowid;
_qr_cv_stats / _qr_cv_groups shape; _require_co_id / _optional_branch_id / _require_entry_date
/ _fetch_qualities / _f / _i helpers). The machine picker reuses get_card_section_machines_query
(all active branch machines, no type filter, branch-scoped); the yarn picker reuses the
spinning yarn-quality builder. Branch-wise (like the carding reports): save REQUIRES branch_id
and persists it; by_date + table reads are STRICTLY branch-scoped (no NULL-branch leak).

Portal persona: get_tenant_db + get_current_user_with_refresh, {"data": ...} responses, None
for SQL NULLs, type-cast binds.
"""

import logging
import statistics
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.authorization.utils import get_current_user_with_refresh
from src.config.db import get_tenant_db
from src.juteProduction.spinning_query import get_yarn_qualities_query
from src.juteSQC.query import get_card_section_machines_query
from src.juteSQC.yarn_tpi_query import (
    get_yarn_tpi_active_row_query,
    get_yarn_tpi_by_date_query,
    get_yarn_tpi_dtl_query,
    get_yarn_tpi_table_count_query,
    get_yarn_tpi_table_query,
    insert_yarn_tpi_dtl_query,
    insert_yarn_tpi_header_query,
    soft_delete_yarn_tpi_query,
)

logger = logging.getLogger(__name__)

router = APIRouter()

SAMPLE_SIZE = 20
NOT_FOUND_MSG = "Yarn TPI study not found"


# =============================================================================
# Pydantic models
# =============================================================================


class YarnTpiRow(BaseModel):
    """One TPI study = machine + yarn item + 20 flat readings (cells may be null).
    count_lbs / std_tpi / tp_value / prepared_by are snapshotted on the header."""

    mc_id: Optional[int] = None
    item_id: int
    count_lbs: Optional[float] = Field(default=None, ge=0)
    std_tpi: Optional[float] = Field(default=None, ge=0)
    tp_value: Optional[float] = Field(default=None, ge=0)
    prepared_by: Optional[str] = None
    readings: List[Optional[float]] = Field(default_factory=list)  # exactly 20


class YarnTpiSave(BaseModel):
    co_id: int
    branch_id: Optional[int] = None
    entry_date: date
    entries: List[YarnTpiRow] = Field(default_factory=list)


# =============================================================================
# Helpers (mirrored from spinning_sqc.py)
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


def _require_entry_date(request: Request) -> date:
    raw = request.query_params.get("entry_date")
    if not raw:
        raise HTTPException(status_code=400, detail="entry_date is required")
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid entry_date format")


def _f(v, default: float = 0.0) -> float:
    """Cast a possibly-None / Decimal value to float."""
    return default if v is None else float(v)


def _i(v, default: Optional[int] = None) -> Optional[int]:
    return default if v is None else int(v)


def _fetch_machines(db: Session, co_id: int, branch_id: Optional[int]) -> list:
    """All active branch machines (no type filter; reuses get_card_section_machines_query)."""
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


def _fetch_qualities(db: Session, co_id: int, branch_id: Optional[int]) -> list:
    """Yarn-quality (yarn item) picker — reuses the spinning yarn-quality builder."""
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


def _tpi_stats(readings: list, std_tpi) -> dict:
    """Compute TPI stats server-side over the non-null readings (RAW, NO MR correction).
    std_dev is the SAMPLE (n-1) stdev via statistics.stdev (n>=2 else 0/None); cv_pct =
    std_dev / avg_tpi * 100 (guard avg_tpi>0). Echoes the std_tpi snapshot + tpi_diff =
    avg_tpi - std_tpi (no OK/LOW/HIGH thresholds — tolerance unconfirmed). Round 2dp."""
    vals = [r["reading_val"] for r in readings if r["reading_val"] is not None]
    n = len(vals)
    avg_tpi = (sum(vals) / n) if n else None
    mx, mn = (max(vals), min(vals)) if vals else (None, None)
    std_dev = statistics.stdev(vals) if n >= 2 else (0.0 if n == 1 else None)
    cv_pct = (std_dev / avg_tpi) * 100 if (std_dev is not None and avg_tpi) else None
    std_tpi_f = None if std_tpi is None else _f(std_tpi)
    tpi_diff = (avg_tpi - std_tpi_f) if (avg_tpi is not None and std_tpi_f is not None) else None
    return {
        "avg_tpi": None if avg_tpi is None else round(avg_tpi, 2),
        "std_dev": None if std_dev is None else round(std_dev, 2),
        "cv_pct": None if cv_pct is None else round(cv_pct, 2),
        "min_tpi": None if mn is None else round(_f(mn), 2),
        "max_tpi": None if mx is None else round(_f(mx), 2),
        "std_tpi": None if std_tpi_f is None else round(std_tpi_f, 2),
        "tpi_diff": None if tpi_diff is None else round(tpi_diff, 2),
        "n": n,
    }


def _tpi_groups(db: Session, co_id: int, branch_id: Optional[int], entry_date) -> list:
    """Active TPI study groups for (co, date, branch) with readings + computed stats."""
    headers = db.execute(
        get_yarn_tpi_by_date_query(),
        {"co_id": co_id, "entry_date": entry_date, "branch_id": branch_id},
    ).fetchall()
    if not headers:
        return []

    hdr_ids = [int(dict(h._mapping)["yarn_tpi_id"]) for h in headers]

    # Reading rows for all groups in one round-trip (expanding IN :ids bind).
    dtl_by_hdr: dict = {hid: [] for hid in hdr_ids}
    for d in db.execute(get_yarn_tpi_dtl_query(), {"ids": hdr_ids}).fetchall():
        dm = dict(d._mapping)
        dtl_by_hdr.setdefault(int(dm["yarn_tpi_id"]), []).append(
            {
                "reading_no": _i(dm.get("reading_no")),
                "reading_val": None if dm.get("reading_val") is None else _f(dm.get("reading_val")),
            }
        )

    groups = []
    for h in headers:
        m = dict(h._mapping)
        hid = int(m["yarn_tpi_id"])
        readings = dtl_by_hdr.get(hid, [])
        std_tpi = m.get("std_tpi")
        groups.append(
            {
                "yarn_tpi_id": hid,
                "co_id": m["co_id"],
                "branch_id": m.get("branch_id"),
                "entry_date": str(m["entry_date"]) if m.get("entry_date") is not None else None,
                "mc_id": m.get("mc_id"),
                "mech_code": m.get("mech_code"),
                "machine_name": m.get("machine_name"),
                "item_id": m.get("item_id"),
                "item_code": m.get("item_code"),
                "item_name": m.get("item_name"),
                "count_lbs": None if m.get("count_lbs") is None else _f(m.get("count_lbs")),
                "std_tpi": None if std_tpi is None else _f(std_tpi),
                "tp_value": None if m.get("tp_value") is None else _f(m.get("tp_value")),
                "prepared_by": m.get("prepared_by"),
                "readings": readings,
                "stats": _tpi_stats(readings, std_tpi),
            }
        )
    return groups


# =============================================================================
# Endpoints
# =============================================================================


@router.get("/yarn_tpi_setup")
def yarn_tpi_setup(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    co_id = _require_co_id(request)
    branch_id = _optional_branch_id(request)
    entry_date = _require_entry_date(request)
    try:
        machines = _fetch_machines(db, co_id, branch_id)
        yarn_items = _fetch_qualities(db, co_id, branch_id)
        groups = _tpi_groups(db, co_id, branch_id, entry_date)
        return {
            "data": {
                "machines": machines,
                "yarn_items": yarn_items,
                "groups": groups,
            }
        }
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid entry_date format")
    except Exception as e:
        logger.exception("Error fetching yarn TPI setup")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/yarn_tpi_save")
def yarn_tpi_save(
    body: YarnTpiSave,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Insert-only, multi-study save (mirrors sqc_qr_cv_save). Each entry inserts one header
    (read lastrowid) then its 20 detail reading rows. Requires branch_id; requires item_id;
    requires the readings array length == 20 (cells may be null). count_lbs / std_tpi /
    tp_value are snapshotted from the body."""
    try:
        if body.branch_id is None:
            raise HTTPException(status_code=400, detail="branch_id is required")

        user_id = token_data.get("user_id")
        saved_ids = []
        for idx, e in enumerate(body.entries):
            if e.item_id is None:
                raise HTTPException(
                    status_code=400, detail=f"Entry {idx + 1}: item_id is required"
                )
            if len(e.readings) != SAMPLE_SIZE:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Entry {idx + 1}: exactly {SAMPLE_SIZE} readings are required, "
                        f"got {len(e.readings)}"
                    ),
                )

            result = db.execute(
                insert_yarn_tpi_header_query(),
                {
                    "co_id": int(body.co_id),
                    "branch_id": int(body.branch_id),
                    "entry_date": body.entry_date,
                    "mc_id": _i(e.mc_id),
                    "item_id": int(e.item_id),
                    "count_lbs": None if e.count_lbs is None else float(e.count_lbs),
                    "std_tpi": None if e.std_tpi is None else float(e.std_tpi),
                    "tp_value": None if e.tp_value is None else float(e.tp_value),
                    "prepared_by": e.prepared_by if e.prepared_by else None,
                    "updated_by": user_id,
                },
            )
            hdr_id = result.lastrowid
            for r_idx in range(SAMPLE_SIZE):
                reading_val = e.readings[r_idx]
                db.execute(
                    insert_yarn_tpi_dtl_query(),
                    {
                        "hdr_id": hdr_id,
                        "reading_no": r_idx + 1,
                        "reading_val": None if reading_val is None else float(reading_val),
                    },
                )
            saved_ids.append(hdr_id)
        db.commit()
        return {"data": {"saved": len(saved_ids), "ids": saved_ids}}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error saving yarn TPI study")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/yarn_tpi_by_date")
def yarn_tpi_by_date(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    co_id = _require_co_id(request)
    branch_id = _optional_branch_id(request)
    entry_date = _require_entry_date(request)
    try:
        groups = _tpi_groups(db, co_id, branch_id, entry_date)
        return {"data": {"groups": groups}}
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid entry_date format")
    except Exception as e:
        logger.exception("Error fetching yarn TPI by date")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/yarn_tpi_table")
def yarn_tpi_table(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Paginated table of saved TPI studies (page / limit / search / branch-scoped)."""
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
            get_yarn_tpi_table_count_query(search=search), params
        ).fetchone()
        total = total_row.total if total_row else 0

        result = db.execute(
            get_yarn_tpi_table_query(search=search), params
        ).fetchall()
        rows = [dict(r._mapping) for r in result]

        return {"data": rows, "total": total, "page": page, "page_size": limit}
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid pagination parameter")
    except Exception as e:
        logger.exception("Error fetching yarn TPI table")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/yarn_tpi_delete/{yarn_tpi_id}")
def yarn_tpi_delete(
    yarn_tpi_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Soft-delete the study header (active=0); detail rows stay (hidden via the active
    header join). Optional co_id query param scopes the delete to the tenant company so a
    guessed id can't soft-delete another company's row within the same tenant DB."""
    raw_co_id = request.query_params.get("co_id")
    try:
        co_id = int(raw_co_id) if raw_co_id else None
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid co_id format")
    try:
        existing = db.execute(
            get_yarn_tpi_active_row_query(),
            {"id": yarn_tpi_id, "co_id": co_id},
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail=NOT_FOUND_MSG)

        db.execute(
            soft_delete_yarn_tpi_query(),
            {"id": yarn_tpi_id, "co_id": co_id, "updated_by": token_data.get("user_id")},
        )
        db.commit()
        return {"data": {"message": "Deleted"}}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error deleting yarn TPI study")
        raise HTTPException(status_code=500, detail=str(e))
