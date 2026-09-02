"""
Wages Quality Master API endpoints (production/qualitymaster).

CRUD for tbl_nbcl_wages_quality_mst.
Fields: dept_id (-> dept_mst), quality_code (max 10), quality_desc (optional, max 100),
quality_rate / conv_factor (decimal(10,7)), active (1/0, default 1).
Tenant-wide master - no co_id / branch_id scoping on the table.
"""

from decimal import Decimal, InvalidOperation

from fastapi import Depends, Request, HTTPException, APIRouter, Response
from sqlalchemy.sql import text
from sqlalchemy.orm import Session
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.models.mst import WagesQualityMst
from src.common.utils import parse_json_body

router = APIRouter()

# status_id lifecycle: created as Open, then Approved or Rejected
STATUS_OPEN, STATUS_APPROVED, STATUS_REJECTED = 1, 3, 4
STATUS_NAMES = {STATUS_OPEN: "Open", STATUS_APPROVED: "Approved", STATUS_REJECTED: "Rejected"}

# decimal(10,7) -> 3 integer digits
_DECIMAL_MAX = Decimal("999.9999999")


def _parse_decimal(raw, field):
    """Coerce an optional decimal(10,7) column; None/'' -> None, out of range -> 400."""
    if raw is None or raw == "":
        return None
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        raise HTTPException(status_code=400, detail=f"{field} must be a number")
    if value < 0 or value > _DECIMAL_MAX:
        raise HTTPException(status_code=400, detail=f"{field} must be between 0 and {_DECIMAL_MAX}")
    return value


def _validate_body(body):
    """Shared create/edit validation. Returns a dict of column values."""
    raw_dept = body.get("dept_id")
    try:
        dept_id = int(raw_dept) if raw_dept not in (None, "") else None
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="dept_id must be an integer")
    if dept_id is None:
        raise HTTPException(status_code=400, detail="Department is required")

    quality_code = (body.get("quality_code") or "").strip()
    if not quality_code:
        raise HTTPException(status_code=400, detail="Quality code is required")
    if len(quality_code) > 10:
        raise HTTPException(status_code=400, detail="Quality code cannot exceed 10 characters")

    # optional: most legacy rows carry a code + rate only
    quality_desc = (body.get("quality_desc") or "").strip()
    if len(quality_desc) > 100:
        raise HTTPException(status_code=400, detail="Quality description cannot exceed 100 characters")

    # active: 1/0; accepts bool or int, missing -> active
    raw_active = body.get("active")
    if raw_active in (None, ""):
        active = 1
    elif raw_active in (True, False, 0, 1, "0", "1", "true", "false"):
        active = 1 if raw_active in (True, 1, "1", "true") else 0
    else:
        raise HTTPException(status_code=400, detail="active must be 0 or 1")

    return {
        "dept_id": dept_id,
        "quality_code": quality_code,
        "quality_desc": quality_desc or None,
        "quality_rate": _parse_decimal(body.get("quality_rate"), "quality_rate"),
        "conv_factor": _parse_decimal(body.get("conv_factor"), "conv_factor"),
        "active": active,
    }


# ─── SQL Queries ──────────────────────────────────────────────────────────

_SELECT = """
        SELECT
            q.quality_id,
            q.dept_id,
            d.dept_desc AS dept_name,
            q.quality_code,
            q.quality_desc,
            q.quality_rate,
            q.conv_factor,
            q.active,
            q.status_id
        FROM tbl_nbcl_wages_quality_mst q
        LEFT JOIN dept_mst d ON d.dept_id = q.dept_id
"""


def get_quality_list_query():
    return text(_SELECT + """
        WHERE (:search IS NULL OR q.quality_code LIKE :search
               OR q.quality_desc LIKE :search OR d.dept_desc LIKE :search)
        ORDER BY q.quality_id DESC
    """)


def get_quality_by_id_query():
    return text(_SELECT + "WHERE q.quality_id = :quality_id")


# ─── Endpoints ────────────────────────────────────────────────────────────


@router.get("/get_quality_table")
def get_quality_table(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Get paginated list of wages qualities."""
    try:
        search = request.query_params.get("search")
        search_param = f"%{search}%" if search else None
        page = int(request.query_params.get("page", 1))
        limit = int(request.query_params.get("limit", 10))

        result = db.execute(get_quality_list_query(), {"search": search_param}).fetchall()
        all_data = [dict(row._mapping) for row in result]
        for row in all_data:
            row["status_name"] = STATUS_NAMES.get(row.get("status_id"), "")

        # ponytail: in-memory pagination, same as grade master; SQL LIMIT if the table grows
        total = len(all_data)
        start_idx = (page - 1) * limit
        return {
            "data": all_data[start_idx:start_idx + limit],
            "total": total,
            "page": page,
            "limit": limit,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_quality_by_id/{quality_id}")
def get_quality_by_id(
    quality_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Get a single wages quality record by ID."""
    try:
        result = db.execute(get_quality_by_id_query(), {"quality_id": quality_id}).fetchone()
        if not result:
            raise HTTPException(status_code=404, detail="Quality not found")
        data = dict(result._mapping)
        data["status_name"] = STATUS_NAMES.get(data.get("status_id"), "")
        return {"data": data}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _check_duplicate(db, values, quality_id=None):
    """quality_code must be unique within a department."""
    dup = db.execute(
        text("""
            SELECT COUNT(*) AS cnt FROM tbl_nbcl_wages_quality_mst
            WHERE quality_code = :quality_code AND dept_id = :dept_id
              AND (:quality_id IS NULL OR quality_id != :quality_id)
        """),
        {"quality_code": values["quality_code"], "dept_id": values["dept_id"], "quality_id": quality_id},
    ).fetchone()
    if dup and dup.cnt > 0:
        raise HTTPException(status_code=400, detail="Quality with this code already exists in this department")


@router.post("/quality_create")
def quality_create(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Create a new wages quality record."""
    try:
        values = _validate_body(parse_json_body(request))
        _check_duplicate(db, values)

        new_row = WagesQualityMst(**values, status_id=STATUS_OPEN)
        db.add(new_row)
        db.commit()
        db.refresh(new_row)
        return {"message": "Quality created successfully", "quality_id": new_row.quality_id}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/quality_edit/{quality_id}")
def quality_edit(
    quality_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Update an existing wages quality record."""
    try:
        values = _validate_body(parse_json_body(request))

        existing = db.query(WagesQualityMst).filter(WagesQualityMst.quality_id == quality_id).first()
        if not existing:
            raise HTTPException(status_code=404, detail="Quality not found")
        # Only Open (or legacy NULL) rows are editable; Approved/Rejected are read-only
        if existing.status_id not in (None, STATUS_OPEN):
            raise HTTPException(status_code=400, detail=f"{STATUS_NAMES.get(existing.status_id, 'This')} quality cannot be edited")

        _check_duplicate(db, values, quality_id=quality_id)

        for key, val in values.items():
            setattr(existing, key, val)
        db.commit()
        return {"message": "Quality updated successfully", "quality_id": quality_id}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# ponytail: single-level approve/reject straight from Open; add /send-for-approval (20) +
# approval_level if the hierarchy from dashboardadmin ever needs to apply here.
# action -> (allowed current statuses, new status). NULL status = legacy import, treated as Open.
_TRANSITIONS = {
    "approve": ((None, STATUS_OPEN), STATUS_APPROVED),
    "reject": ((None, STATUS_OPEN), STATUS_REJECTED),
    "reopen": ((STATUS_REJECTED,), STATUS_OPEN),
}


@router.put("/quality_status/{quality_id}")
def quality_status(
    quality_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Approve (1->3), reject (1->4) or reopen (4->1) a wages quality record."""
    try:
        action = str((parse_json_body(request) or {}).get("action") or "").lower()
        if action not in _TRANSITIONS:
            raise HTTPException(status_code=400, detail="action must be approve, reject or reopen")
        allowed_from, new_status = _TRANSITIONS[action]

        existing = db.query(WagesQualityMst).filter(WagesQualityMst.quality_id == quality_id).first()
        if not existing:
            raise HTTPException(status_code=404, detail="Quality not found")
        if existing.status_id not in allowed_from:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot {action} a quality in status {STATUS_NAMES.get(existing.status_id, existing.status_id)}",
            )

        existing.status_id = new_status
        db.commit()
        return {"message": f"Quality {STATUS_NAMES[new_status].lower()}", "quality_id": quality_id, "status_id": new_status}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
