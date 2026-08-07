"""Roll Stock view endpoints (current bin/group inventory + per-item summary)."""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from src.authorization.utils import get_current_user_with_refresh
from src.config.db import get_tenant_db
from src.juteProduction.constants import DEFAULT_MATURITY_HOURS
from src.juteProduction.query import (
    get_bins_with_stock_query,
    get_item_maturity_map_query,
)


router = APIRouter()


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


@router.get("/roll_stock")
def roll_stock(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    co_id = _require_co_id(request)
    branch_id = _optional_branch_id(request)
    try:
        rows = db.execute(
            get_bins_with_stock_query(), {"co_id": co_id, "branch_id": branch_id}
        ).fetchall()
        maturity_map: dict = {
            int(r._mapping["item_id"]): int(r._mapping["maturity_hours"])
            for r in db.execute(get_item_maturity_map_query(), {"co_id": co_id}).fetchall()
        }
        now = datetime.now()
        data = []
        for r in rows:
            m = dict(r._mapping)
            avg_dt: Optional[datetime] = m.get("avg_entry_dt")
            if avg_dt and not isinstance(avg_dt, datetime):
                try:
                    avg_dt = datetime.fromisoformat(str(avg_dt))
                except Exception:
                    avg_dt = None
            maturity_hours = (
                max(int((now - avg_dt).total_seconds() // 3600), 0) if avg_dt else 0
            )
            data.append(
                {
                    "bin_id": int(m["bin_id"]),
                    "bin_code": m.get("bin_code"),
                    "entry_id_grp": int(m["entry_id_grp"]),
                    "item_id": int(m["item_id"]),
                    "item_name": m.get("item_name"),
                    "produced_rolls": int(m["produced_rolls"]),
                    "issued_rolls": int(m["issued_rolls"]),
                    "current_rolls": int(m["current_rolls"]),
                    "produced_kg": float(m["produced_kg"] or 0),
                    "issued_kg": float(m["issued_kg"] or 0),
                    "current_kg": float(m["current_kg"] or 0),
                    "current_mt": round(float(m["current_kg"] or 0) / 1000.0, 3),
                    "avg_entry_dt": avg_dt.isoformat() if avg_dt else None,
                    "maturity_hrs": maturity_hours,
                    "target_maturity_hrs": maturity_map.get(int(m["item_id"]), DEFAULT_MATURITY_HOURS),
                }
            )
        return {"data": data}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/roll_stock_quality_summary")
def roll_stock_quality_summary(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    co_id = _require_co_id(request)
    branch_id = _optional_branch_id(request)
    try:
        rows = db.execute(
            get_bins_with_stock_query(), {"co_id": co_id, "branch_id": branch_id}
        ).fetchall()
        summary: dict = {}
        for r in rows:
            m = dict(r._mapping)
            item_id = int(m["item_id"])
            entry = summary.setdefault(
                item_id,
                {
                    "item_id": item_id,
                    "item_name": m.get("item_name"),
                    "closing_rolls": 0,
                    "closing_kg": 0.0,
                },
            )
            entry["closing_rolls"] += int(m["current_rolls"])
            entry["closing_kg"] += float(m["current_kg"] or 0)
        data = []
        for entry in summary.values():
            entry["closing_mt"] = round(entry["closing_kg"] / 1000.0, 3)
            data.append(entry)
        data.sort(key=lambda x: (x["item_name"] or ""))
        return {"data": data}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
