"""Jute Production reports: Maturity Time + Spreader Production summary."""

from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from src.authorization.utils import get_current_user_with_refresh
from src.config.db import get_tenant_db
from src.juteProduction.constants import A_SHIFT, B_SHIFT, SHIFT_BUCKETS
from src.juteProduction.reportQueries import (
    get_maturity_time_report_query,
    get_spreader_production_report_query,
)
from src.juteProduction.services.shift import shift_for_report


router = APIRouter()


def _require_co_id(request: Request) -> int:
    raw = request.query_params.get("co_id")
    if not raw:
        raise HTTPException(status_code=400, detail="co_id is required")
    try:
        return int(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid co_id")


def _parse_multi(request: Request, key: str) -> Optional[list]:
    """Parse repeated query params (?machines=1&machines=2) into a list of ints."""
    vals = request.query_params.getlist(key)
    if not vals:
        return None
    out = []
    for v in vals:
        for tok in str(v).split(","):
            tok = tok.strip()
            if not tok:
                continue
            try:
                out.append(int(tok))
            except ValueError:
                pass
    return out or None


def _parse_str_multi(request: Request, key: str) -> Optional[list]:
    vals = request.query_params.getlist(key)
    if not vals:
        return None
    out: list = []
    for v in vals:
        for tok in str(v).split(","):
            tok = tok.strip()
            if tok:
                out.append(tok)
    return out or None


@router.get("/maturity_time_report")
def maturity_time_report(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    co_id = _require_co_id(request)
    d = request.query_params.get("issue_date")
    if not d:
        raise HTTPException(status_code=400, detail="issue_date is required")
    try:
        rows = db.execute(
            get_maturity_time_report_query(), {"co_id": co_id, "d": date.fromisoformat(d)}
        ).fetchall()
        data = []
        for r in rows:
            m = dict(r._mapping)
            for k in ("wt_per_roll",):
                if m.get(k) is not None:
                    m[k] = float(m[k])
            for k in ("issue_dt", "prod_entry_dt"):
                if m.get(k) and isinstance(m[k], datetime):
                    m[k] = m[k].isoformat()
            data.append(m)
        return {"data": data}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _build_pivot(rows, entity_key: str, entity_label_key: str) -> list:
    """Build a list of pivot rows like {entity_id, entity_name, A1, B1, A2, B2, C, A, B, Total}."""
    bucket_init = {b: 0 for b in SHIFT_BUCKETS}
    grouped: dict = {}
    for r in rows:
        ent_id = r.get(entity_key)
        if ent_id is None:
            continue
        bucket = r.get("__shift")
        if not bucket:
            continue
        entry = grouped.setdefault(
            ent_id,
            {
                "entity_id": ent_id,
                "entity_name": r.get(entity_label_key) or str(ent_id),
                **bucket_init.copy(),
            },
        )
        entry[bucket] = entry.get(bucket, 0) + int(r.get("no_of_rolls", 0) or 0)
    out = []
    for entry in grouped.values():
        entry["A"] = sum(entry.get(s, 0) for s in A_SHIFT)
        entry["B"] = sum(entry.get(s, 0) for s in B_SHIFT)
        entry["Total"] = sum(entry.get(s, 0) for s in SHIFT_BUCKETS)
        out.append(entry)
    out.sort(key=lambda x: x["entity_name"])
    return out


@router.get("/spreader_production_summary")
def spreader_production_summary(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    co_id = _require_co_id(request)
    d = request.query_params.get("report_date")
    if not d:
        raise HTTPException(status_code=400, detail="report_date is required")

    try:
        report_d = date.fromisoformat(d)
        sel_machines = _parse_multi(request, "spreaders")
        sel_items = _parse_multi(request, "items")
        sel_shifts = _parse_str_multi(request, "shifts")

        raw = db.execute(
            get_spreader_production_report_query(), {"co_id": co_id, "d": report_d}
        ).fetchall()

        rows = []
        for r in raw:
            m = dict(r._mapping)
            shift = shift_for_report(m["entry_date"], m["entry_time"], report_d)
            if shift is None:
                continue
            if sel_shifts and shift not in sel_shifts:
                continue
            if sel_machines and int(m["machine_id"]) not in sel_machines:
                continue
            if sel_items and int(m["item_id"]) not in sel_items:
                continue
            m["__shift"] = shift
            if isinstance(m.get("entry_dt"), datetime):
                m["entry_dt"] = m["entry_dt"].isoformat()
            if m.get("wt_per_roll") is not None:
                m["wt_per_roll"] = float(m["wt_per_roll"])
            if m.get("weight_kg") is not None:
                m["weight_kg"] = float(m["weight_kg"])
            rows.append(m)

        # Aggregate pivots
        spreader_pivot = _build_pivot(rows, entity_key="machine_id", entity_label_key="machine_name")
        quality_pivot = _build_pivot(rows, entity_key="item_id", entity_label_key="item_name")

        total_rolls = sum(int(r.get("no_of_rolls", 0) or 0) for r in rows)
        total_weight_kg = round(sum(float(r.get("weight_kg", 0) or 0) for r in rows), 2)

        # Strip the internal __shift before returning
        for r in rows:
            r["shift"] = r.pop("__shift")

        return {
            "data": {
                "rows": rows,
                "spreader_pivot": spreader_pivot,
                "quality_pivot": quality_pivot,
                "totals": {
                    "rolls": total_rolls,
                    "weight_kg": total_weight_kg,
                    "weight_mt": round(total_weight_kg / 1000.0, 3),
                    "unique_spreaders": len({r["machine_id"] for r in rows if r.get("machine_id")}),
                    "unique_items": len({r["item_id"] for r in rows if r.get("item_id")}),
                },
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
