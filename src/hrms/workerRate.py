"""
Worker Rate Muster master (worker_rate_mst).

Monthly rate parameters per worker — basic, hourly basic, DA rate plus the
Y/N applicability flags (DA, HRA, HRD, quarter, PF, ESI, PTAX) exactly as
kept in the mill's rate muster. One active row per employee, dated by
effective_date: creating a new row for a worker deactivates their previous
one (rate history stays as inactive rows), and the bulk endpoint versions
every scoped row the same way with one column changed. The table carries no
co_id/branch_id of its own, so every read is scoped through the employee's
branch (hrms_ed_personal_details.branch_id -> branch_mst.co_id) — the
portal company/branch sidebar selection drives the list and dropdown.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import bindparam
from sqlalchemy.orm import Session
from sqlalchemy.sql import text

from src.authorization.utils import get_current_user_with_refresh
from src.common.utils import parse_json_body
from src.config.db import get_tenant_db
from src.models.hrms import WorkerRateMst

router = APIRouter()

FLAG_FIELDS = ("da_all", "hra", "hrd", "quarter", "pf", "esi", "ptax")
RATE_FIELDS = ("fbasic", "fbasic_hr", "da_rate")
# Columns the bulk endpoint may change — whitelist, interpolated into SQL.
BULK_COLUMNS = RATE_FIELDS
BULK_OPS = ("add", "set")


# ─── SQL Queries ────────────────────────────────────────────────────


def get_worker_rate_list_query():
    """List rows joined to employee, scoped by company/branch."""
    return text("""
        SELECT
            w.worker_rate_id,
            w.eb_id,
            w.effective_date,
            o.emp_code,
            CONCAT(IFNULL(p.first_name, ''), ' ', IFNULL(p.middle_name, ''), ' ',
                   IFNULL(p.last_name, '')) AS emp_name,
            w.fbasic,
            w.fbasic_hr,
            w.da_all,
            w.da_rate,
            w.hra,
            w.hrd,
            w.quarter,
            w.pf,
            w.esi,
            w.ptax,
            w.is_active
        FROM worker_rate_mst w
        INNER JOIN hrms_ed_personal_details p ON p.eb_id = w.eb_id
        INNER JOIN branch_mst bm ON bm.branch_id = p.branch_id
        LEFT JOIN hrms_ed_official_details o ON o.eb_id = w.eb_id AND o.active = 1
        WHERE w.is_active = 1
          AND bm.co_id = :co_id
          AND (:branch_id IS NULL OR p.branch_id = :branch_id)
          AND (:search IS NULL
               OR o.emp_code LIKE :search
               OR CONCAT(IFNULL(p.first_name, ''), ' ', IFNULL(p.last_name, '')) LIKE :search)
        ORDER BY o.emp_code, w.worker_rate_id
    """)


def get_worker_rate_by_id_query():
    """Includes the employee's code/name — the edit dialog shows them read-only
    (the worker may be inactive and so absent from the employee dropdown)."""
    return text("""
        SELECT
            w.worker_rate_id, w.eb_id, w.effective_date, w.fbasic, w.fbasic_hr, w.da_all,
            w.da_rate, w.hra, w.hrd, w.quarter, w.pf, w.esi, w.ptax, w.is_active,
            o.emp_code,
            CONCAT(IFNULL(p.first_name, ''), ' ', IFNULL(p.middle_name, ''), ' ',
                   IFNULL(p.last_name, '')) AS emp_name
        FROM worker_rate_mst w
        LEFT JOIN hrms_ed_personal_details p ON p.eb_id = w.eb_id
        LEFT JOIN hrms_ed_official_details o ON o.eb_id = w.eb_id AND o.active = 1
        WHERE w.worker_rate_id = :record_id
    """)


def get_rate_employees_query():
    """Active employees for the dropdown, scoped by company/branch."""
    return text("""
        SELECT
            p.eb_id,
            o.emp_code,
            CONCAT(IFNULL(p.first_name, ''), ' ', IFNULL(p.middle_name, ''), ' ',
                   IFNULL(p.last_name, '')) AS full_name
        FROM hrms_ed_personal_details p
        INNER JOIN branch_mst bm ON bm.branch_id = p.branch_id
        LEFT JOIN hrms_ed_official_details o ON o.eb_id = p.eb_id AND o.active = 1
        WHERE COALESCE(p.active, 1) = 1
          AND bm.co_id = :co_id
          AND (:branch_id IS NULL OR p.branch_id = :branch_id)
        ORDER BY o.emp_code IS NULL, o.emp_code, p.eb_id
    """)


def _duplicate_query():
    """A worker already has an active rate row (ignoring one id)."""
    return text("""
        SELECT COUNT(*) AS cnt FROM worker_rate_mst
        WHERE is_active = 1
          AND eb_id = :eb_id
          AND (:record_id IS NULL OR worker_rate_id <> :record_id)
    """)


# ─── Helpers ────────────────────────────────────────────────────────


def _branch_param(request: Request) -> int | None:
    raw = request.query_params.get("branch_id")
    return int(raw) if raw not in (None, "", "null") else None


def _flag(body: dict, name: str) -> str:
    """Normalize a Y/N flag: accepts 'Y'/'N', truthy booleans, defaults to 'N'."""
    v = body.get(name)
    if isinstance(v, str):
        return "Y" if v.strip().upper() == "Y" else "N"
    return "Y" if v else "N"


def _rate(body: dict, name: str) -> float | None:
    v = body.get(name)
    if v in (None, ""):
        return None
    try:
        val = float(v)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"{name} must be a number")
    if val < 0:
        raise HTTPException(status_code=400, detail=f"{name} cannot be negative")
    return val


def _require_eb_id(body: dict) -> int:
    eb_id = body.get("eb_id")
    if not eb_id:
        raise HTTPException(status_code=400, detail="Employee is required")
    return int(eb_id)


def _eff_date(body: dict):
    raw = body.get("effective_date")
    if not raw:
        raise HTTPException(status_code=400, detail="Effective date is required")
    try:
        return datetime.strptime(str(raw), "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Effective date must be YYYY-MM-DD")


def _validate_bulk(body: dict) -> tuple[str, str, float]:
    """Validates the bulk-change request: whitelisted column, op, numeric value."""
    column = body.get("column")
    if column not in BULK_COLUMNS:
        raise HTTPException(status_code=400, detail=f"column must be one of {', '.join(BULK_COLUMNS)}")
    op = body.get("op")
    if op not in BULK_OPS:
        raise HTTPException(status_code=400, detail="op must be 'add' or 'set'")
    value = body.get("value")
    try:
        val = float(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="value must be a number")
    return column, op, val


def _serialize(m: dict) -> dict:
    if m.get("effective_date"):
        m["effective_date"] = m["effective_date"].isoformat()
    return m


# ─── Endpoints ──────────────────────────────────────────────────────


@router.get("/worker_rate_setup")
def worker_rate_setup(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Dropdown options: employees for the selected company/branch."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        employees = db.execute(get_rate_employees_query(), {
            "co_id": int(co_id), "branch_id": _branch_param(request),
        }).fetchall()

        return {
            "data": {
                "employees": [
                    {
                        "value": str(m["eb_id"]),
                        "label": f"{m['emp_code'] or m['eb_id']} - {(m['full_name'] or '').strip()}",
                    }
                    for m in (dict(r._mapping) for r in employees)
                ],
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_worker_rate_table")
def get_worker_rate_table(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Paginated list of worker rate rows."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        search = request.query_params.get("search")
        page = int(request.query_params.get("page", 1))
        limit = int(request.query_params.get("limit", 10))

        rows = db.execute(get_worker_rate_list_query(), {
            "co_id": int(co_id),
            "branch_id": _branch_param(request),
            "search": f"%{search}%" if search else None,
        }).fetchall()

        all_data = []
        for row in rows:
            m = _serialize(dict(row._mapping))
            m["emp_name"] = (m.get("emp_name") or "").strip()
            all_data.append(m)

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


@router.get("/get_worker_rate_by_id/{record_id}")
def get_worker_rate_by_id(
    record_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Single rate row, for the edit dialog."""
    try:
        row = db.execute(get_worker_rate_by_id_query(), {"record_id": record_id}).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Worker rate not found")
        m = _serialize(dict(row._mapping))
        m["emp_name"] = (m.get("emp_name") or "").strip()
        return {"data": m}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/worker_rate_create")
def worker_rate_create(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Create a worker rate row; any previous active row for the worker becomes inactive."""
    try:
        body = parse_json_body(request)
        eb_id = _require_eb_id(body)
        eff = _eff_date(body)

        superseded = db.execute(
            text("UPDATE worker_rate_mst SET is_active = 0 WHERE eb_id = :eb_id AND is_active = 1"),
            {"eb_id": eb_id},
        ).rowcount

        record = WorkerRateMst(
            eb_id=eb_id,
            effective_date=eff,
            **{f: _rate(body, f) for f in RATE_FIELDS},
            **{f: _flag(body, f) for f in FLAG_FIELDS},
            is_active=1,
        )
        db.add(record)
        db.commit()
        db.refresh(record)

        return {
            "message": "Worker rate created successfully"
            + (" (previous rate deactivated)" if superseded else ""),
            "worker_rate_id": record.worker_rate_id,
            "superseded": superseded,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/worker_rate_edit/{record_id}")
def worker_rate_edit(
    record_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Update a worker rate row in place (a correction, not a new version)."""
    try:
        body = parse_json_body(request)
        eb_id = _require_eb_id(body)

        existing = db.query(WorkerRateMst).filter(
            WorkerRateMst.worker_rate_id == record_id,
        ).first()
        if not existing:
            raise HTTPException(status_code=404, detail="Worker rate not found")

        dup = db.execute(_duplicate_query(), {
            "eb_id": eb_id, "record_id": record_id,
        }).fetchone()
        if dup and dup.cnt > 0:
            raise HTTPException(
                status_code=400,
                detail="This worker already has an active rate row",
            )

        existing.eb_id = eb_id
        existing.effective_date = _eff_date(body)
        for f in RATE_FIELDS:
            setattr(existing, f, _rate(body, f))
        for f in FLAG_FIELDS:
            setattr(existing, f, _flag(body, f))
        db.commit()

        return {
            "message": "Worker rate updated successfully",
            "worker_rate_id": record_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/worker_rate_bulk_update")
def worker_rate_bulk_update(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Change one rate column for every active worker in scope, as new versions.

    Body: {column: fbasic|fbasic_hr|da_rate, op: add|set, value, effective_date,
    co_id, branch_id?}. Each worker gets a new active row with the column
    adjusted (add: COALESCE(col,0)+value; set: value) and the new effective
    date; their previous row goes inactive — same history rule as create.
    """
    try:
        body = parse_json_body(request)
        column, op, val = _validate_bulk(body)
        eff = _eff_date(body)
        co_id = body.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        raw_branch = body.get("branch_id")
        branch_id = int(raw_branch) if raw_branch not in (None, "", "null") else None

        # DA rate only applies where DA is allowed — workers with da_all = 'N'
        # keep their row untouched by a DA RATE bulk change.
        flag_filter = "AND w.da_all = 'Y'" if column == "da_rate" else ""
        ids = [r[0] for r in db.execute(text(f"""
            SELECT w.worker_rate_id
            FROM worker_rate_mst w
            INNER JOIN hrms_ed_personal_details p ON p.eb_id = w.eb_id
            INNER JOIN branch_mst bm ON bm.branch_id = p.branch_id
            WHERE w.is_active = 1
              AND bm.co_id = :co_id
              AND (:branch_id IS NULL OR p.branch_id = :branch_id)
              {flag_filter}
        """), {"co_id": int(co_id), "branch_id": branch_id}).fetchall()]
        if not ids:
            return {"message": "No active worker rates in scope", "updated": 0}

        # column/op are whitelist-validated above, so interpolation is safe.
        # 'add' takes negative values (a decrease); the result floors at 0 — a
        # rate below zero is never meaningful in payroll.
        expr = f"GREATEST(COALESCE(w.{column}, 0) + :val, 0)" if op == "add" else ":val"
        select_rates = ", ".join(expr if f == column else f"w.{f}" for f in RATE_FIELDS)
        db.execute(
            text(f"""
                INSERT INTO worker_rate_mst
                    (eb_id, effective_date, fbasic, fbasic_hr, da_rate,
                     da_all, hra, hrd, quarter, pf, esi, ptax, is_active)
                SELECT w.eb_id, :eff, {select_rates},
                       w.da_all, w.hra, w.hrd, w.quarter, w.pf, w.esi, w.ptax, 1
                FROM worker_rate_mst w
                WHERE w.worker_rate_id IN :ids
            """).bindparams(bindparam("ids", expanding=True)),
            {"eff": eff, "val": val, "ids": ids},
        )
        db.execute(
            text("UPDATE worker_rate_mst SET is_active = 0 WHERE worker_rate_id IN :ids")
            .bindparams(bindparam("ids", expanding=True)),
            {"ids": ids},
        )
        db.commit()

        return {
            "message": f"{column} {'adjusted by' if op == 'add' else 'set to'} {val} "
                       f"for {len(ids)} workers",
            "updated": len(ids),
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/worker_rate_delete/{record_id}")
def worker_rate_delete(
    record_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Soft-delete a worker rate row (is_active = 0), matching the list filter."""
    try:
        existing = db.query(WorkerRateMst).filter(
            WorkerRateMst.worker_rate_id == record_id,
        ).first()
        if not existing:
            raise HTTPException(status_code=404, detail="Worker rate not found")

        existing.is_active = 0
        db.commit()
        return {"message": "Worker rate deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
