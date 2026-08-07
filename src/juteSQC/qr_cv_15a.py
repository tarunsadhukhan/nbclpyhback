"""R-08-15A Yarn QR% & CV% Special Purpose QC capture endpoints (jute SQC module).

The special-purpose variant of R-08-15: 2 machines (a 3rd-drawing machine + a spinning
frame) and a FLAT 12-reading b/s set (no spindle structure). A group = one saved test for
(date, machine, item_id) carrying EXACTLY 12 readings (cells may be null). yarn-quality
linked (NOT batch). Save is insert-only (duplicates allowed); a group is soft-deleted as a
unit. observed_count + mr_pct are OPERATOR-ENTERED on the header (NOT read from R-08-16 —
this is the special-purpose variant) and stored. Stats are computed SERVER-SIDE at read from
the stored readings using EXACTLY the R-08-15 _qr_cv_stats formula PLUS qr_at_min.

Clones the R-08-15 QR/CV section in spinning_sqc.py (header + 12 dtl rows via lastrowid;
_qr_cv_stats / _qr_cv_groups shape; helpers). The machine picker reuses
get_card_section_machines_query (all active branch machines, no type filter, branch-scoped);
the yarn picker reuses the spinning yarn-quality builder. Branch-wise (like the carding
reports): save REQUIRES branch_id and persists it; by_date + table reads are STRICTLY
branch-scoped (no NULL-branch leak).

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
from src.juteSQC.qr_cv_15a_query import (
    get_qr_cv_15a_active_row_query,
    get_qr_cv_15a_by_date_query,
    get_qr_cv_15a_dtl_query,
    get_qr_cv_15a_table_count_query,
    get_qr_cv_15a_table_query,
    insert_qr_cv_15a_dtl_query,
    insert_qr_cv_15a_header_query,
    soft_delete_qr_cv_15a_query,
)
from src.juteSQC.query import get_card_section_machines_query

logger = logging.getLogger(__name__)

router = APIRouter()

READINGS = 12
NOT_FOUND_MSG = "Yarn QR-CV special-purpose test not found"


# =============================================================================
# Pydantic models
# =============================================================================


class QrCv15aRow(BaseModel):
    """One QR/CV-15A test = drawing machine + spinning frame + yarn item + 12 flat readings
    (cells may be null). observed_count / mr_pct are operator-entered on the header."""

    drawing_mc_id: Optional[int] = None
    mc_id: Optional[int] = None
    item_id: int
    observed_count: Optional[float] = Field(default=None, ge=0)
    mr_pct: Optional[float] = Field(default=None, ge=0)
    readings: List[Optional[float]] = Field(default_factory=list)  # exactly 12


class QrCv15aSave(BaseModel):
    co_id: int
    branch_id: Optional[int] = None
    entry_date: date
    entries: List[QrCv15aRow] = Field(default_factory=list)


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
    """All active branch machines (no type filter; reuses get_card_section_machines_query).
    Serves both the 3rd-drawing-machine and spinning-frame pickers."""
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


def _qr_cv_stats(readings: list, observed_count) -> dict:
    """Compute QR/CV stats server-side — EXACTLY the R-08-15 _qr_cv_stats formula over the
    non-null readings, PLUS qr_at_min. std_dev is the SAMPLE (n-1) stdev via statistics.stdev
    (n>=2 else 0/None); QR%/CV% are guarded against divide-by-zero; all rounded to 2 dp.
    observed_count comes from the HEADER (operator-entered), not a count-AVG lookup."""
    vals = [r["reading_val"] for r in readings if r["reading_val"] is not None]
    n = len(vals)
    avg_bs = (sum(vals) / n) if n else None
    mx, mn = (max(vals), min(vals)) if vals else (None, None)
    std_dev = statistics.stdev(vals) if n >= 2 else (0.0 if n == 1 else None)
    qr_pct = (avg_bs / observed_count) * 100 if (avg_bs is not None and observed_count) else None
    cv_pct = (std_dev / qr_pct) * 100 if (qr_pct not in (None, 0) and std_dev is not None) else None
    qr_at_min = (mn / observed_count) * 100 if (mn is not None and observed_count) else None
    return {
        "max": None if mx is None else round(_f(mx), 2),
        "min": None if mn is None else round(_f(mn), 2),
        "std_dev": None if std_dev is None else round(std_dev, 2),
        "avg_bs": None if avg_bs is None else round(avg_bs, 2),
        "qr_pct": None if qr_pct is None else round(qr_pct, 2),
        "cv_pct": None if cv_pct is None else round(cv_pct, 2),
        "qr_at_min": None if qr_at_min is None else round(qr_at_min, 2),
        "n": n,
    }


def _qr_cv_groups(db: Session, co_id: int, branch_id: Optional[int], entry_date) -> list:
    """Active QR/CV-15A groups for (co, date, branch) with readings + computed stats.
    observed_count / mr_pct come from the HEADER (operator-entered) — no R-08-16 lookup."""
    headers = db.execute(
        get_qr_cv_15a_by_date_query(),
        {"co_id": co_id, "entry_date": entry_date, "branch_id": branch_id},
    ).fetchall()
    if not headers:
        return []

    hdr_ids = [int(dict(h._mapping)["qr_cv_15a_id"]) for h in headers]

    # Reading rows for all groups in one round-trip (expanding IN :ids bind).
    dtl_by_hdr: dict = {hid: [] for hid in hdr_ids}
    for d in db.execute(get_qr_cv_15a_dtl_query(), {"ids": hdr_ids}).fetchall():
        dm = dict(d._mapping)
        dtl_by_hdr.setdefault(int(dm["qr_cv_15a_id"]), []).append(
            {
                "reading_no": _i(dm.get("reading_no")),
                "reading_val": None if dm.get("reading_val") is None else _f(dm.get("reading_val")),
            }
        )

    groups = []
    for h in headers:
        m = dict(h._mapping)
        hid = int(m["qr_cv_15a_id"])
        readings = dtl_by_hdr.get(hid, [])
        observed_count = None if m.get("observed_count") is None else _f(m.get("observed_count"))
        mr_pct = None if m.get("mr_pct") is None else _f(m.get("mr_pct"))
        groups.append(
            {
                "qr_cv_15a_id": hid,
                "co_id": m["co_id"],
                "branch_id": m.get("branch_id"),
                "entry_date": str(m["entry_date"]) if m.get("entry_date") is not None else None,
                "drawing_mc_id": m.get("drawing_mc_id"),
                "drawing_mech_code": m.get("drawing_mech_code"),
                "drawing_machine_name": m.get("drawing_machine_name"),
                "mc_id": m.get("mc_id"),
                "mech_code": m.get("mech_code"),
                "machine_name": m.get("machine_name"),
                "item_id": m.get("item_id"),
                "item_code": m.get("item_code"),
                "item_name": m.get("item_name"),
                "observed_count": observed_count,
                "mr_pct": mr_pct,
                "readings": readings,
                "stats": _qr_cv_stats(readings, observed_count),
            }
        )
    return groups


# =============================================================================
# Endpoints
# =============================================================================


@router.get("/qr_cv_15a_setup")
def qr_cv_15a_setup(
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
        groups = _qr_cv_groups(db, co_id, branch_id, entry_date)
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
        logger.exception("Error fetching QR/CV-15A setup")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/qr_cv_15a_save")
def qr_cv_15a_save(
    body: QrCv15aSave,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Insert-only, multi-test save (mirrors sqc_qr_cv_save). Each entry inserts one header
    (read lastrowid) then its 12 detail reading rows. Requires branch_id; requires item_id;
    requires the readings array length == 12 (cells may be null). observed_count / mr_pct are
    operator-entered and snapshotted on the header."""
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
            if len(e.readings) != READINGS:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Entry {idx + 1}: exactly {READINGS} readings are required, "
                        f"got {len(e.readings)}"
                    ),
                )

            result = db.execute(
                insert_qr_cv_15a_header_query(),
                {
                    "co_id": int(body.co_id),
                    "branch_id": int(body.branch_id),
                    "entry_date": body.entry_date,
                    "drawing_mc_id": _i(e.drawing_mc_id),
                    "mc_id": _i(e.mc_id),
                    "item_id": int(e.item_id),
                    "observed_count": None if e.observed_count is None else float(e.observed_count),
                    "mr_pct": None if e.mr_pct is None else float(e.mr_pct),
                    "updated_by": user_id,
                },
            )
            hdr_id = result.lastrowid
            for r_idx in range(READINGS):
                reading_val = e.readings[r_idx]
                db.execute(
                    insert_qr_cv_15a_dtl_query(),
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
        logger.exception("Error saving QR/CV-15A test")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/qr_cv_15a_by_date")
def qr_cv_15a_by_date(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    co_id = _require_co_id(request)
    branch_id = _optional_branch_id(request)
    entry_date = _require_entry_date(request)
    try:
        groups = _qr_cv_groups(db, co_id, branch_id, entry_date)
        return {"data": {"groups": groups}}
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid entry_date format")
    except Exception as e:
        logger.exception("Error fetching QR/CV-15A by date")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/qr_cv_15a_table")
def qr_cv_15a_table(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Paginated table of saved QR/CV-15A tests (page / limit / search / branch-scoped)."""
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
            get_qr_cv_15a_table_count_query(search=search), params
        ).fetchone()
        total = total_row.total if total_row else 0

        result = db.execute(
            get_qr_cv_15a_table_query(search=search), params
        ).fetchall()
        rows = [dict(r._mapping) for r in result]

        return {"data": rows, "total": total, "page": page, "page_size": limit}
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid pagination parameter")
    except Exception as e:
        logger.exception("Error fetching QR/CV-15A table")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/qr_cv_15a_delete/{qr_cv_15a_id}")
def qr_cv_15a_delete(
    qr_cv_15a_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Soft-delete the header (active=0); detail rows stay (hidden via the active header join).
    Optional co_id query param scopes the delete to the tenant company so a guessed id can't
    soft-delete another company's row within the same tenant DB."""
    raw_co_id = request.query_params.get("co_id")
    try:
        co_id = int(raw_co_id) if raw_co_id else None
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid co_id format")
    try:
        existing = db.execute(
            get_qr_cv_15a_active_row_query(),
            {"id": qr_cv_15a_id, "co_id": co_id},
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail=NOT_FOUND_MSG)

        db.execute(
            soft_delete_qr_cv_15a_query(),
            {"id": qr_cv_15a_id, "co_id": co_id, "updated_by": token_data.get("user_id")},
        )
        db.commit()
        return {"data": {"message": "Deleted"}}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error deleting QR/CV-15A test")
        raise HTTPException(status_code=500, detail=str(e))
