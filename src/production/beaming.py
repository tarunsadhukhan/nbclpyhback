"""
Beaming production entries (beaming_production) — production/beamproduction.

One row per machine + date + shift + quality, straight from the mill's
"BEAMING PROD" sheet (Q-CODE, quality, prod kg/yds, rate, amount, MC no,
shift, wk hrs, lost hrs, divisible hrs). The rate is NOT keyed in: it is
resolved from the wages quality master (tbl_nbcl_wages_quality_mst,
BEAMING dept) for the selected quality and snapshotted on the row;
amount = rate * prod_qty is a stored generated column.

Rows are scoped by branch_id (company filter via branch_mst.co_id); machines
come from machine_mst for the BEAMING department.
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session
from sqlalchemy.sql import text

from src.authorization.utils import get_current_user_with_refresh
from src.common.utils import parse_json_body
from src.config.db import get_tenant_db
from src.hrms.outsiderRate import get_rate_shifts_query
from src.models.hrms import BeamingProduction

router = APIRouter()

# ponytail: dept matched by name — the sheet's machines and Q-codes both live
# under dept_mst 'BEAMING'; make it configurable if another tenant names it differently
_BEAMING_DEPT = "BEAMING"


# ─── SQL Queries ──────────────────────────────────────────────────────────


def get_beaming_prod_list_query():
    return text("""
        SELECT
            b.beaming_prod_id, b.branch_id, b.prod_date, b.shift,
            b.machine_id, mc.machine_name,
            b.quality_id, q.quality_code, q.quality_desc,
            b.prod_qty, b.rate, b.amount,
            b.wk_hrs, b.lost_hrs, b.divisible_hrs, b.remarks, b.active
        FROM beaming_production b
        INNER JOIN branch_mst bm ON bm.branch_id = b.branch_id
        LEFT JOIN machine_mst mc ON mc.machine_id = b.machine_id
        LEFT JOIN tbl_nbcl_wages_quality_mst q ON q.quality_id = b.quality_id
        WHERE b.active = 1
          AND bm.co_id = :co_id
          AND (:branch_id IS NULL OR b.branch_id = :branch_id)
          AND (:from_date IS NULL OR b.prod_date >= :from_date)
          AND (:to_date IS NULL OR b.prod_date <= :to_date)
          AND (:search IS NULL
               OR mc.machine_name LIKE :search
               OR q.quality_code LIKE :search
               OR q.quality_desc LIKE :search)
        ORDER BY b.prod_date DESC, mc.machine_name, b.shift, b.beaming_prod_id
    """)


def get_beaming_prod_by_id_query():
    return text("""
        SELECT beaming_prod_id, branch_id, prod_date, shift, machine_id,
               quality_id, prod_qty, rate, amount, wk_hrs, lost_hrs,
               divisible_hrs, remarks, active
        FROM beaming_production
        WHERE beaming_prod_id = :record_id
    """)


def get_beaming_machines_query():
    return text("""
        SELECT mc.machine_id, mc.machine_name
        FROM machine_mst mc
        INNER JOIN dept_mst d ON d.dept_id = mc.dept_id
        WHERE mc.active = 1 AND d.dept_desc = :dept_desc
        ORDER BY mc.machine_name
    """)


def get_quality_options_query():
    return text("""
        SELECT q.quality_id, q.quality_code, q.quality_desc, q.quality_rate
        FROM tbl_nbcl_wages_quality_mst q
        INNER JOIN dept_mst d ON d.dept_id = q.dept_id
        WHERE q.active = 1 AND d.dept_desc = :dept_desc
        ORDER BY q.quality_code
    """)


def get_quality_rate_query():
    return text("""
        SELECT quality_rate FROM tbl_nbcl_wages_quality_mst
        WHERE quality_id = :quality_id AND active = 1
    """)


def _duplicate_query():
    """Same machine + date + shift + quality already entered (ignoring one id)."""
    return text("""
        SELECT COUNT(*) AS cnt FROM beaming_production
        WHERE active = 1
          AND machine_id = :machine_id
          AND prod_date = :prod_date
          AND shift = :shift
          AND quality_id = :quality_id
          AND (:record_id IS NULL OR beaming_prod_id <> :record_id)
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
    """Validate + normalise a create/edit payload into BeamingProduction columns
    (everything except rate, which is resolved from the quality master)."""
    raw_date = str(body.get("prod_date") or "").strip()
    if not raw_date:
        raise HTTPException(status_code=400, detail="prod_date is required")
    try:
        prod_date = date.fromisoformat(raw_date[:10])
    except ValueError:
        raise HTTPException(status_code=400, detail="prod_date must be YYYY-MM-DD")

    prod_qty = _num_or_none(body, "prod_qty")
    if not prod_qty:
        raise HTTPException(status_code=400, detail="prod_qty must be greater than 0")

    return {
        "branch_id": _int(body, "branch_id"),
        "prod_date": prod_date,
        "shift": (str(body.get("shift") or "").strip().upper() or "A")[:5],
        "machine_id": _int(body, "machine_id"),
        "quality_id": _int(body, "quality_id"),
        "prod_qty": prod_qty,
        "wk_hrs": _num_or_none(body, "wk_hrs"),
        "lost_hrs": _num_or_none(body, "lost_hrs"),
        "remarks": (str(body.get("remarks") or "").strip()[:255] or None),
    }


def _resolve_rate(db: Session, quality_id: int) -> float:
    """Beaming rate as per the wages quality master — never trusted from the client."""
    row = db.execute(get_quality_rate_query(), {"quality_id": quality_id}).fetchone()
    if not row or row.quality_rate is None:
        raise HTTPException(status_code=400, detail="Selected beaming quality not found")
    return float(row.quality_rate)


def _assert_not_duplicate(db: Session, values: dict, record_id: int | None) -> None:
    dup = db.execute(_duplicate_query(), {
        "machine_id": values["machine_id"],
        "prod_date": values["prod_date"],
        "shift": values["shift"],
        "quality_id": values["quality_id"],
        "record_id": record_id,
    }).fetchone()
    if dup and dup.cnt > 0:
        raise HTTPException(
            status_code=400,
            detail="This machine already has an entry for this date, shift and quality — edit it instead",
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
        prod_qty = _num_or_none(line, "prod_qty")
        if not prod_qty:
            raise HTTPException(status_code=400, detail="prod_qty must be greater than 0")
        return {
            "machine_id": _int(line, "machine_id"),
            "quality_id": _int(line, "quality_id"),
            "prod_qty": prod_qty,
            "wk_hrs": _num_or_none(line, "wk_hrs"),
            "lost_hrs": _num_or_none(line, "lost_hrs"),
        }
    except HTTPException as e:
        raise HTTPException(status_code=400, detail=f"Line {index + 1}: {e.detail}")


def _parse_bulk_lines(lines) -> list[dict]:
    """Validate + normalise every line, rejecting machine+quality pairs
    duplicated within the same payload (DB-side duplicates are checked later,
    per line, against existing rows)."""
    if not isinstance(lines, list) or not lines:
        raise HTTPException(status_code=400, detail="At least one line is required")

    seen: set[tuple[int, int]] = set()
    parsed = []
    for i, line in enumerate(lines):
        values = _parse_bulk_line(line if isinstance(line, dict) else {}, i)
        key = (values["machine_id"], values["quality_id"])
        if key in seen:
            raise HTTPException(
                status_code=400,
                detail=f"Line {i + 1}: duplicate machine + quality in this entry",
            )
        seen.add(key)
        parsed.append(values)
    return parsed


# ─── Endpoints ────────────────────────────────────────────────────────────


@router.get("/beaming_prod_setup")
def beaming_prod_setup(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Dropdown options: beaming machines, shifts and the beaming quality
    codes with their per-unit rate."""
    try:
        machines = db.execute(get_beaming_machines_query(), {
            "dept_desc": _BEAMING_DEPT,
        }).fetchall()
        shifts = db.execute(get_rate_shifts_query()).fetchall()
        qualities = db.execute(get_quality_options_query(), {
            "dept_desc": _BEAMING_DEPT,
        }).fetchall()

        return {
            "data": {
                "machines": [
                    {"value": str(r.machine_id), "label": r.machine_name}
                    for r in machines
                ],
                "shifts": [
                    {"value": r.spell_name, "label": r.spell_name} for r in shifts
                ],
                "qualities": [
                    {
                        "value": str(m["quality_id"]),
                        "label": f"{m['quality_code']} - {m['quality_desc'] or ''}".rstrip(" -"),
                        "quality_rate": float(m["quality_rate"]) if m["quality_rate"] is not None else None,
                    }
                    for m in (dict(r._mapping) for r in qualities)
                ],
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_beaming_prod_table")
def get_beaming_prod_table(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Paginated list of beaming production entries for the selected company/branch."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        search = request.query_params.get("search")
        page = int(request.query_params.get("page", 1))
        limit = int(request.query_params.get("limit", 10))

        rows = db.execute(get_beaming_prod_list_query(), {
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


@router.get("/get_beaming_prod_by_id/{record_id}")
def get_beaming_prod_by_id(
    record_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        row = db.execute(get_beaming_prod_by_id_query(), {"record_id": record_id}).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Beaming production entry not found")
        return {"data": dict(row._mapping)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/beaming_prod_create")
def beaming_prod_create(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        values = _parse_body(parse_json_body(request))
        _assert_not_duplicate(db, values, None)
        rate = _resolve_rate(db, values["quality_id"])

        record = BeamingProduction(**values, rate=rate, active=1)
        db.add(record)
        db.commit()
        db.refresh(record)
        return {
            "message": "Beaming production entry created successfully",
            "beaming_prod_id": record.beaming_prod_id,
            "rate": record.rate,
            "amount": record.amount,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/beaming_prod_bulk_create")
def beaming_prod_bulk_create(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Create several rows in one grid submit — shared branch/date/shift,
    one machine+quality line per row — all-or-nothing in a single commit."""
    try:
        body = parse_json_body(request)
        header = _parse_bulk_header(body)
        lines = _parse_bulk_lines(body.get("lines"))

        records = []
        for i, line in enumerate(lines):
            values = {**header, **line, "remarks": None}
            try:
                _assert_not_duplicate(db, values, None)
            except HTTPException as e:
                raise HTTPException(status_code=400, detail=f"Line {i + 1}: {e.detail}")
            rate = _resolve_rate(db, values["quality_id"])
            records.append(BeamingProduction(**values, rate=rate, active=1))

        db.add_all(records)
        db.commit()
        for record in records:
            db.refresh(record)

        return {
            "message": "Beaming production entries created successfully",
            "created": len(records),
            "ids": [record.beaming_prod_id for record in records],
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/beaming_prod_edit/{record_id}")
def beaming_prod_edit(
    record_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        values = _parse_body(parse_json_body(request))
        existing = db.query(BeamingProduction).filter(
            BeamingProduction.beaming_prod_id == record_id,
        ).first()
        if not existing:
            raise HTTPException(status_code=404, detail="Beaming production entry not found")
        _assert_not_duplicate(db, values, record_id)
        rate = _resolve_rate(db, values["quality_id"])

        for k, v in values.items():
            setattr(existing, k, v)
        existing.rate = rate
        db.commit()
        return {
            "message": "Beaming production entry updated successfully",
            "beaming_prod_id": record_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/beaming_prod_delete/{record_id}")
def beaming_prod_delete(
    record_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Soft-delete (active = 0), matching the list filter."""
    try:
        existing = db.query(BeamingProduction).filter(
            BeamingProduction.beaming_prod_id == record_id,
        ).first()
        if not existing:
            raise HTTPException(status_code=404, detail="Beaming production entry not found")
        existing.active = 0
        db.commit()
        return {"message": "Beaming production entry deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
