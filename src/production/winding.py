"""
Winding production entries (winding_production) — production/windingproduction.

One row per worker + date + shift + quality, straight from the mill's
"WINDING PRODUCTION" sheet (ECODE, quality, grist, prod hrs, prod kg, rate,
amt, shift). The quality is selected from winding_quality_mst (wdg_q_id);
its quality_inc_code joins winding_incentive_mst.quality_code to find the
rate scheme. The rate is NOT keyed in: it is resolved from that scheme
(winding_incentive_mst.rate_per_hr = incentive_amt / eligibility_hrs) — for
slab-rated qualities the slab row matching prod_kg / prod_hrs * 8 — and
snapshotted on the row (winding_incentive_id points at the resolved slab row);
amount = rate * prod_hrs is a stored generated column.

Rows are scoped by branch_id (company filter via branch_mst.co_id); the
employee dropdown reuses the HRMS employee query.
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session
from sqlalchemy.sql import text

from src.authorization.utils import get_current_user_with_refresh
from src.common.utils import parse_json_body
from src.config.db import get_tenant_db
from src.hrms.outsiderRate import get_rate_shifts_query
from src.hrms.workerRate import get_rate_employees_query
from src.models.hrms import WindingProduction

router = APIRouter()


# ─── SQL Queries ──────────────────────────────────────────────────────────


def get_winding_prod_list_query():
    return text("""
        SELECT
            w.winding_prod_id, w.branch_id, w.prod_date, w.shift,
            w.eb_id, o.emp_code,
            CONCAT(IFNULL(p.first_name, ''), ' ', IFNULL(p.middle_name, ''), ' ',
                   IFNULL(p.last_name, '')) AS emp_name,
            w.wdg_q_id, w.winding_incentive_id,
            COALESCE(q.q_code, i.quality_code) AS quality_code,
            COALESCE(q.quality_desc, i.quality_name) AS quality_name,
            w.grist, w.prod_hrs, w.prod_kg, w.unit, w.rate, w.amount, w.remarks, w.active
        FROM winding_production w
        INNER JOIN branch_mst bm ON bm.branch_id = w.branch_id
        LEFT JOIN hrms_ed_personal_details p ON p.eb_id = w.eb_id
        LEFT JOIN hrms_ed_official_details o ON o.eb_id = w.eb_id AND o.active = 1
        LEFT JOIN winding_quality_mst q ON q.wdg_q_id = w.wdg_q_id
        LEFT JOIN winding_incentive_mst i ON i.winding_incentive_id = w.winding_incentive_id
        WHERE w.active = 1
          AND bm.co_id = :co_id
          AND (:branch_id IS NULL OR w.branch_id = :branch_id)
          AND (:from_date IS NULL OR w.prod_date >= :from_date)
          AND (:to_date IS NULL OR w.prod_date <= :to_date)
          AND (:search IS NULL
               OR o.emp_code LIKE :search
               OR CONCAT(IFNULL(p.first_name, ''), ' ', IFNULL(p.last_name, '')) LIKE :search
               OR q.quality_desc LIKE :search
               OR i.quality_name LIKE :search)
        ORDER BY w.prod_date DESC, o.emp_code, w.winding_prod_id
    """)


def get_winding_prod_by_id_query():
    return text("""
        SELECT w.winding_prod_id, w.branch_id, w.prod_date, w.shift, w.eb_id,
               w.wdg_q_id, w.winding_incentive_id,
               COALESCE(q.q_code, i.quality_code) AS quality_code,
               COALESCE(q.quality_desc, i.quality_name) AS quality_name,
               w.grist, w.prod_hrs, w.prod_kg, w.unit, w.rate, w.amount,
               w.remarks, w.active
        FROM winding_production w
        LEFT JOIN winding_quality_mst q ON q.wdg_q_id = w.wdg_q_id
        LEFT JOIN winding_incentive_mst i ON i.winding_incentive_id = w.winding_incentive_id
        WHERE w.winding_prod_id = :record_id
    """)


def get_quality_options_query():
    return text("""
        SELECT wdg_q_id, q_code, quality_desc, quality_inc_code, grist
        FROM winding_quality_mst
        WHERE active = 1
        ORDER BY q_code
    """)


def get_quality_by_id_query():
    return text("""
        SELECT wdg_q_id, quality_inc_code
        FROM winding_quality_mst
        WHERE wdg_q_id = :wdg_q_id AND active = 1
    """)


def get_incentive_options_query():
    return text("""
        SELECT winding_incentive_id, quality_code, quality_name,
               prod_from, prod_to, unit, rate_per_hr
        FROM winding_incentive_mst
        WHERE active = 1
        ORDER BY quality_code, prod_from, winding_incentive_id
    """)


def get_incentive_group_query():
    """All active incentive rows for a quality_code (flat row first, then
    slabs by prod_from — MySQL sorts NULL prod_from first)."""
    return text("""
        SELECT winding_incentive_id, prod_from, prod_to, rate_per_hr
        FROM winding_incentive_mst
        WHERE active = 1 AND quality_code = :quality_code
        ORDER BY prod_from, winding_incentive_id
    """)


def _duplicate_query():
    """Same worker + date + shift + quality already entered (ignoring one id)."""
    return text("""
        SELECT COUNT(*) AS cnt FROM winding_production
        WHERE active = 1
          AND eb_id = :eb_id
          AND prod_date = :prod_date
          AND shift = :shift
          AND wdg_q_id = :wdg_q_id
          AND (:record_id IS NULL OR winding_prod_id <> :record_id)
    """)


# ─── Helpers ──────────────────────────────────────────────────────────────


def _branch_param(request: Request) -> int | None:
    raw = request.query_params.get("branch_id")
    return int(raw) if raw not in (None, "", "null") else None


def _int(body: dict, name: str) -> int:
    v = body.get(name)
    if v in (None, "", "null"):
        raise HTTPException(status_code=400, detail=f"{name} is required")
    try:
        return int(v)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"{name} must be an integer")


def _num_or_none(body: dict, name: str) -> float | None:
    v = body.get(name)
    if v in (None, ""):
        return None
    try:
        val = float(v)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"{name} must be a number")
    if val < 0:
        raise HTTPException(status_code=400, detail=f"{name} must be zero or more")
    return val


def _parse_body(body: dict) -> dict:
    """Validate + normalise a create/edit payload into WindingProduction columns
    (everything except rate, which is resolved from the incentive master)."""
    raw_date = str(body.get("prod_date") or "").strip()
    if not raw_date:
        raise HTTPException(status_code=400, detail="prod_date is required")
    try:
        prod_date = date.fromisoformat(raw_date[:10])
    except ValueError:
        raise HTTPException(status_code=400, detail="prod_date must be YYYY-MM-DD")

    prod_hrs = _num_or_none(body, "prod_hrs")
    if not prod_hrs:
        raise HTTPException(status_code=400, detail="prod_hrs must be greater than 0")

    return {
        "branch_id": _int(body, "branch_id"),
        "prod_date": prod_date,
        "shift": (str(body.get("shift") or "").strip().upper() or "A")[:5],
        "eb_id": _int(body, "eb_id"),
        "wdg_q_id": _int(body, "wdg_q_id"),
        "grist": _num_or_none(body, "grist"),
        "prod_hrs": prod_hrs,
        "prod_kg": _num_or_none(body, "prod_kg"),
        "unit": (str(body.get("unit") or "").strip().upper() or "KG")[:10],
        "remarks": (str(body.get("remarks") or "").strip()[:255] or None),
    }


def _pick_slab(slabs, prod_hrs, prod_kg) -> tuple[int, float]:
    """Pick (winding_incentive_id, rate) from [(id, prod_from, prod_to, rate)]
    ordered by prod_from, for prod_kg produced in prod_hrs normalised to 8 hrs."""
    per8 = prod_kg / prod_hrs * 8
    picked = None
    for slab in slabs:
        if per8 >= slab[1]:
            picked = slab  # highest slab reached
            if slab[2] is None or per8 <= slab[2]:
                break  # inside this slab's range
    if picked is None:
        return slabs[0][0], 0.0  # ponytail: below the minimum slab no incentive is earned
    return picked[0], float(picked[3])


def _resolve_incentive(db: Session, wdg_q_id: int,
                       prod_hrs: float, prod_kg: float | None) -> tuple[int, float]:
    """Resolve the incentive row + rate to snapshot — never trusted from the client.
    The selected winding_quality_mst row's quality_inc_code finds the incentive
    scheme (winding_incentive_mst.quality_code). Flat quality: that row's rate.
    Slabbed quality: the slab row matching prod_kg / prod_hrs * 8."""
    quality = db.execute(get_quality_by_id_query(), {"wdg_q_id": wdg_q_id}).fetchone()
    if not quality:
        raise HTTPException(status_code=400, detail="Selected winding quality not found")

    rows = db.execute(get_incentive_group_query(), {
        "quality_code": quality.quality_inc_code,
    }).fetchall()
    if not rows:
        raise HTTPException(status_code=400,
                            detail="No winding incentive scheme configured for this quality")

    slabs = [(r.winding_incentive_id, r.prod_from, r.prod_to, r.rate_per_hr)
             for r in rows if r.prod_from is not None]
    if not slabs:  # flat quality
        return rows[0].winding_incentive_id, float(rows[0].rate_per_hr or 0)
    if not prod_kg:
        raise HTTPException(status_code=400,
                            detail="Production qty is required for a slab-rated quality")
    return _pick_slab(slabs, prod_hrs, prod_kg)


def _assert_not_duplicate(db: Session, values: dict, record_id: int | None) -> None:
    dup = db.execute(_duplicate_query(), {
        "eb_id": values["eb_id"],
        "prod_date": values["prod_date"],
        "shift": values["shift"],
        "wdg_q_id": values["wdg_q_id"],
        "record_id": record_id,
    }).fetchone()
    if dup and dup.cnt > 0:
        raise HTTPException(
            status_code=400,
            detail="This worker already has an entry for this date, shift and quality — edit it instead",
        )


def _parse_bulk_header(body: dict) -> dict:
    """branch_id/prod_date/shift shared by every line of a bulk-create payload
    — same rules as _parse_body, minus the per-line fields."""
    raw_date = str(body.get("prod_date") or "").strip()
    if not raw_date:
        raise HTTPException(status_code=400, detail="prod_date is required")
    try:
        prod_date = date.fromisoformat(raw_date[:10])
    except ValueError:
        raise HTTPException(status_code=400, detail="prod_date must be YYYY-MM-DD")

    return {
        "branch_id": _int(body, "branch_id"),
        "prod_date": prod_date,
        "shift": (str(body.get("shift") or "").strip().upper() or "A")[:5],
    }


def _parse_bulk_line(line: dict, index: int) -> dict:
    """One grid row — same field rules as _parse_body's per-line fields, with
    any error prefixed by row number so the UI can point at the failing line."""
    try:
        prod_hrs = _num_or_none(line, "prod_hrs")
        if not prod_hrs:
            raise HTTPException(status_code=400, detail="prod_hrs must be greater than 0")
        return {
            "eb_id": _int(line, "eb_id"),
            "wdg_q_id": _int(line, "wdg_q_id"),
            "grist": _num_or_none(line, "grist"),
            "prod_hrs": prod_hrs,
            "prod_kg": _num_or_none(line, "prod_kg"),
            "unit": (str(line.get("unit") or "").strip().upper() or "KG")[:10],
        }
    except HTTPException as e:
        raise HTTPException(status_code=400, detail=f"Line {index + 1}: {e.detail}")


def _parse_bulk_lines(lines) -> list[dict]:
    """Validate + normalise every line, rejecting worker+quality pairs
    duplicated within the same payload (DB-side duplicates are checked later,
    per line, against existing rows)."""
    if not isinstance(lines, list) or not lines:
        raise HTTPException(status_code=400, detail="At least one line is required")

    seen: set[tuple[int, int]] = set()
    parsed = []
    for i, line in enumerate(lines):
        values = _parse_bulk_line(line if isinstance(line, dict) else {}, i)
        key = (values["eb_id"], values["wdg_q_id"])
        if key in seen:
            raise HTTPException(
                status_code=400,
                detail=f"Line {i + 1}: duplicate worker + quality in this entry",
            )
        seen.add(key)
        parsed.append(values)
    return parsed


# ─── Endpoints ────────────────────────────────────────────────────────────


@router.get("/winding_prod_setup")
def winding_prod_setup(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Dropdown options: employees (company/branch scoped), shifts and the
    winding qualities from winding_quality_mst — one option per quality, with
    its grist and the rate scheme (unit, flat rate or slab list) found via
    quality_inc_code = winding_incentive_mst.quality_code. A quality with no
    incentive scheme is still listed (rate unresolvable — the save rejects it)."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        employees = db.execute(get_rate_employees_query(), {
            "co_id": int(co_id), "branch_id": _branch_param(request),
        }).fetchall()
        shifts = db.execute(get_rate_shifts_query()).fetchall()
        qualities = db.execute(get_quality_options_query()).fetchall()
        incentives = db.execute(get_incentive_options_query()).fetchall()

        schemes: dict[str, dict] = {}  # incentive rows grouped by quality_code
        for m in (dict(r._mapping) for r in incentives):
            scheme = schemes.setdefault(m["quality_code"], {
                "unit": m["unit"], "rate_per_hr": None, "slabs": [],
            })
            if m["prod_from"] is None:
                scheme["rate_per_hr"] = m["rate_per_hr"]
            else:
                scheme["slabs"].append({
                    "value": str(m["winding_incentive_id"]),
                    "prod_from": m["prod_from"],
                    "prod_to": m["prod_to"],
                    "rate_per_hr": m["rate_per_hr"],
                })
        for scheme in schemes.values():
            if scheme["slabs"]:  # slab-rated quality: rate comes from the picked slab
                scheme["rate_per_hr"] = None

        quality_options = [
            {
                "value": str(m["wdg_q_id"]),
                "label": f"{m['q_code']} - {m['quality_desc']}",
                "grist": float(m["grist"]) if m["grist"] is not None else None,
                **schemes.get(m["quality_inc_code"],
                              {"unit": "KG", "rate_per_hr": None, "slabs": []}),
            }
            for m in (dict(r._mapping) for r in qualities)
        ]

        return {
            "data": {
                "employees": [
                    {
                        "value": str(m["eb_id"]),
                        "label": f"{m['emp_code'] or m['eb_id']} - {(m['full_name'] or '').strip()}",
                    }
                    for m in (dict(r._mapping) for r in employees)
                ],
                "shifts": [
                    {"value": r.spell_name, "label": r.spell_name} for r in shifts
                ],
                "qualities": quality_options,
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_winding_prod_table")
def get_winding_prod_table(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Paginated list of winding production entries for the selected company/branch."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        search = request.query_params.get("search")
        page = int(request.query_params.get("page", 1))
        limit = int(request.query_params.get("limit", 10))

        rows = db.execute(get_winding_prod_list_query(), {
            "co_id": int(co_id),
            "branch_id": _branch_param(request),
            "from_date": request.query_params.get("from_date") or None,
            "to_date": request.query_params.get("to_date") or None,
            "search": f"%{search}%" if search else None,
        }).fetchall()
        all_data = [dict(r._mapping) for r in rows]

        # ponytail: in-memory pagination like the sibling pages; SQL LIMIT if it grows
        total = len(all_data)
        start = (page - 1) * limit
        return {
            "data": all_data[start:start + limit],
            "total": total,
            "page": page,
            "limit": limit,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_winding_prod_by_id/{record_id}")
def get_winding_prod_by_id(
    record_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        row = db.execute(get_winding_prod_by_id_query(), {"record_id": record_id}).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Winding production entry not found")
        return {"data": dict(row._mapping)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/winding_prod_create")
def winding_prod_create(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        values = _parse_body(parse_json_body(request))
        values["winding_incentive_id"], rate = _resolve_incentive(
            db, values["wdg_q_id"], values["prod_hrs"], values["prod_kg"])
        _assert_not_duplicate(db, values, None)

        record = WindingProduction(**values, rate=rate, active=1)
        db.add(record)
        db.commit()
        db.refresh(record)
        return {
            "message": "Winding production entry created successfully",
            "winding_prod_id": record.winding_prod_id,
            "rate": record.rate,
            "amount": record.amount,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/winding_prod_bulk_create")
def winding_prod_bulk_create(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Create several rows in one grid submit — shared branch/date/shift,
    one worker+quality line per row — all-or-nothing in a single commit."""
    try:
        body = parse_json_body(request)
        header = _parse_bulk_header(body)
        lines = _parse_bulk_lines(body.get("lines"))

        records = []
        for i, line in enumerate(lines):
            values = {**header, **line, "remarks": None}
            try:
                values["winding_incentive_id"], rate = _resolve_incentive(
                    db, values["wdg_q_id"], values["prod_hrs"], values["prod_kg"])
                _assert_not_duplicate(db, values, None)
            except HTTPException as e:
                raise HTTPException(status_code=400, detail=f"Line {i + 1}: {e.detail}")
            records.append(WindingProduction(**values, rate=rate, active=1))

        db.add_all(records)
        db.commit()
        for record in records:
            db.refresh(record)

        return {
            "message": "Winding production entries created successfully",
            "created": len(records),
            "ids": [record.winding_prod_id for record in records],
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/winding_prod_edit/{record_id}")
def winding_prod_edit(
    record_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        values = _parse_body(parse_json_body(request))
        existing = db.query(WindingProduction).filter(
            WindingProduction.winding_prod_id == record_id,
        ).first()
        if not existing:
            raise HTTPException(status_code=404, detail="Winding production entry not found")
        values["winding_incentive_id"], rate = _resolve_incentive(
            db, values["wdg_q_id"], values["prod_hrs"], values["prod_kg"])
        _assert_not_duplicate(db, values, record_id)

        for k, v in values.items():
            setattr(existing, k, v)
        existing.rate = rate
        db.commit()
        return {
            "message": "Winding production entry updated successfully",
            "winding_prod_id": record_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/winding_prod_delete/{record_id}")
def winding_prod_delete(
    record_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Soft-delete (active = 0), matching the list filter."""
    try:
        existing = db.query(WindingProduction).filter(
            WindingProduction.winding_prod_id == record_id,
        ).first()
        if not existing:
            raise HTTPException(status_code=404, detail="Winding production entry not found")
        existing.active = 0
        db.commit()
        return {"message": "Winding production entry deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
