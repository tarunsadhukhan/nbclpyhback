"""Winding production reports (jute production module).

Two read-only reports over the read-time reconciliation view
(``get_winding_reconciliation_query``), registered under
``/api/juteProductionReports`` next to the existing jute-production reports:

* ``winding_spell_report``  — reconciled KG per winder + spell + quality for a
  date (the per-person reconciliation rows), plus a per-shift roll-up.
* ``winding_quality_wise``  — reconciled KG per quality, pivoted across the
  A/B/C shift buckets (shift = LEFT(spell_code, 1)).

Reconciled production = ``SUM(doff.production_qty) - opening_jugar + closing_jugar``
per person/spell (winding entry is person-keyed — see
docs/winding-person-keyed-entry-spec.md), computed at READ time (never
persisted). Values stay in KG.

LIMITATION (locked design): there is NO winding target master and NO winding
attendance link yet, so target / efficiency / performance / per-8hr / bundle
reports CANNOT be produced faithfully. These endpoints therefore return
**production KG only** and attach an explicit ``note`` — they deliberately do
NOT emit fabricated efficiency or bundle figures (BUNDLE_KG stays a constant,
not applied). Mirrors reports.py for conventions: get_tenant_db +
get_current_user_with_refresh, {"data": ...} responses and the try/except
(HTTPException raise / ValueError 400 / Exception 500) pattern.

Scope key is **branch_id (required)**, not co_id: one branch belongs to exactly
one company, so the branch is the stricter key and co_id is not read at all.
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from src.authorization.utils import get_current_user_with_refresh
from src.config.db import get_tenant_db
from src.juteProduction.constants import BUNDLE_KG
from src.juteProduction.winding_query import get_winding_reconciliation_query


router = APIRouter()

SHIFT_BUCKETS = ("A", "B", "C")

# Surfaced on every winding report so consumers know the numbers are production
# KG only — efficiency/target/bundle are intentionally NOT computed (no master).
LIMITATION_NOTE = (
    "Reconciled production in KG only. No winding target master or attendance "
    "link exists yet, so efficiency, target, per-8hr and bundle figures are not "
    f"computed (bundle factor BUNDLE_KG={BUNDLE_KG} kept as a constant, not applied)."
)


def _require_branch_id(request: Request) -> int:
    """branch_id is the scope key for winding reads — co_id is implied by it (one
    branch belongs to exactly one company), so it is mandatory and co_id is not
    read at all."""
    raw = request.query_params.get("branch_id")
    if not raw:
        raise HTTPException(status_code=400, detail="branch_id is required")
    try:
        return int(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid branch_id")


def _f(v, default: float = 0.0) -> float:
    return default if v is None else float(v)


def _fetch_reconciliation(db: Session, d_val, branch_id):
    """Run the reconciliation view (branch + date scoped; spell + quality open)."""
    return db.execute(
        get_winding_reconciliation_query(),
        {
            "tran_date": d_val,
            "spell_id": None,
            "branch_id": branch_id,
            "item_id": None,
        },
    ).fetchall()


@router.get("/winding_spell_report")
def winding_spell_report(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Reconciled KG per machine + spell + quality for a date, plus a shift roll-up.

    Each row carries sum_production (doff net), opening/closing jugar, and the
    reconciled production_kg. The roll-up sums production_kg per A/B/C shift.
    """
    branch_id = _require_branch_id(request)
    d = request.query_params.get("report_date") or request.query_params.get("tran_date")
    if not d:
        raise HTTPException(status_code=400, detail="report_date is required")
    try:
        d_val = date.fromisoformat(d)
        raw = _fetch_reconciliation(db, d_val, branch_id)

        rows = []
        shift_totals = {b: 0.0 for b in SHIFT_BUCKETS}
        total_kg = 0.0
        for r in raw:
            m = dict(r._mapping)
            prod_kg = _f(m.get("production_kg"))
            row = {
                "tran_date": str(m["tran_date"]) if m.get("tran_date") is not None else None,
                "spell_id": m.get("spell_id"),
                "spell_code": m.get("spell_code"),
                "shift": m.get("shift"),
                "eb_id": m.get("eb_id"),
                "emp_code": m.get("emp_code"),
                "worker_name": m.get("worker_name"),
                "item_id": m.get("item_id"),
                "item_code": m.get("item_code"),
                "item_name": m.get("item_name"),
                "sum_production": _f(m.get("sum_production")),
                "opening_jugar": _f(m.get("opening_jugar")),
                "closing_jugar": _f(m.get("closing_jugar")),
                "production_kg": round(prod_kg, 3),
            }
            rows.append(row)
            bucket = (row["shift"] or "")[:1].upper()
            if bucket in shift_totals:
                shift_totals[bucket] += prod_kg
            total_kg += prod_kg

        shift_rollup = [
            {"shift": b, "production_kg": round(shift_totals[b], 3)} for b in SHIFT_BUCKETS
        ]

        return {
            "data": {
                "rows": rows,
                "shift_rollup": shift_rollup,
                "total_production_kg": round(total_kg, 3),
                "note": LIMITATION_NOTE,
            }
        }
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid report_date format")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/winding_quality_wise")
def winding_quality_wise(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Reconciled KG per quality, pivoted across A/B/C shift buckets for a date.

    Each output row is one quality with its A/B/C reconciled KG and a Total
    (shift = LEFT(spell_code, 1)). Production KG only — see ``note``.
    """
    branch_id = _require_branch_id(request)
    d = request.query_params.get("report_date") or request.query_params.get("tran_date")
    if not d:
        raise HTTPException(status_code=400, detail="report_date is required")
    try:
        d_val = date.fromisoformat(d)
        raw = _fetch_reconciliation(db, d_val, branch_id)

        grouped: dict = {}
        for r in raw:
            m = dict(r._mapping)
            q_id = m.get("item_id")
            entry = grouped.setdefault(
                q_id,
                {
                    "item_id": q_id,
                    "item_code": m.get("item_code"),
                    "item_name": m.get("item_name"),
                    **{b: 0.0 for b in SHIFT_BUCKETS},
                },
            )
            bucket = (m.get("shift") or "")[:1].upper()
            if bucket in SHIFT_BUCKETS:
                entry[bucket] += _f(m.get("production_kg"))

        out = []
        for entry in grouped.values():
            for b in SHIFT_BUCKETS:
                entry[b] = round(entry[b], 3)
            entry["Total"] = round(sum(entry[b] for b in SHIFT_BUCKETS), 3)
            out.append(entry)
        out.sort(key=lambda x: (x.get("quality_code") or ""))

        return {"data": {"rows": out, "shifts": list(SHIFT_BUCKETS), "note": LIMITATION_NOTE}}
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid report_date format")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
