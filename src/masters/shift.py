"""
Shift Master API endpoints.

Provides CRUD operations for the shift_mst table.
Shifts are scoped by branch_id (no co_id column).
"""

from fastapi import Depends, Request, HTTPException, APIRouter, Response
from sqlalchemy.sql import text
from sqlalchemy.orm import Session
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.models.mst import ShiftMst
from datetime import datetime, timedelta
from decimal import Decimal
from src.common.utils import parse_json_body

router = APIRouter()


def _format_timedelta(val):
    """Convert a timedelta (MySQL TIME) to HH:MM string."""
    if val is None:
        return None
    if isinstance(val, timedelta):
        total_seconds = int(val.total_seconds())
        hours, remainder = divmod(total_seconds, 3600)
        minutes = remainder // 60
        return f"{hours:02d}:{minutes:02d}"
    return str(val)


def _serialize_shift_row(row):
    """Convert a shift row to a JSON-safe dict with HH:MM times."""
    data = dict(row._mapping)
    for key in ("starting_time", "end_time"):
        if key in data:
            data[key] = _format_timedelta(data[key])
    for key, val in data.items():
        if isinstance(val, Decimal):
            data[key] = float(val)
    return data


# ─── SQL Queries ────────────────────────────────────────────────────


def get_shift_list_query(branch_ids=None):
    branch_filter = ""
    if branch_ids:
        placeholders = ",".join(str(int(b)) for b in branch_ids)
        branch_filter = f"AND s.branch_id IN ({placeholders})"
    return text(f"""
        SELECT
            s.shift_id,
            s.shift_name,
            s.status,
            s.branch_id,
            s.spell_type,
            TIME_FORMAT(s.starting_time, '%H:%i') AS starting_time,
            s.working_hours,
            s.minimum_work_hours,
            s.break_hours,
            s.halfday_work_hours,
            s.late_minutes,
            s.late_minutes2,
            s.week_off_day,
            s.week_off_day2,
            s.week_off_halfDay,
            s.is_overnight,
            TIME_FORMAT(s.end_time, '%H:%i') AS end_time,
            s.updated_by,
            s.update_date_time,
            b.branch_name
        FROM shift_mst s
        LEFT JOIN branch_mst b ON b.branch_id = s.branch_id
        WHERE 1=1
          {branch_filter}
          AND (:search IS NULL OR s.shift_name LIKE :search
               OR b.branch_name LIKE :search)
        ORDER BY s.shift_id DESC
    """)


def get_shift_by_id_query():
    return text("""
        SELECT
            s.shift_id,
            s.shift_name,
            s.status,
            s.branch_id,
            s.spell_type,
            TIME_FORMAT(s.starting_time, '%H:%i') AS starting_time,
            s.working_hours,
            s.minimum_work_hours,
            s.break_hours,
            s.halfday_work_hours,
            s.late_minutes,
            s.late_minutes2,
            s.week_off_day,
            s.week_off_day2,
            s.week_off_halfDay,
            s.is_overnight,
            TIME_FORMAT(s.end_time, '%H:%i') AS end_time,
            s.updated_by,
            s.update_date_time,
            b.branch_name
        FROM shift_mst s
        LEFT JOIN branch_mst b ON b.branch_id = s.branch_id
        WHERE s.shift_id = :shift_id
    """)


# ─── Endpoints ──────────────────────────────────────────────────────


@router.get("/get_shift_table")
def get_shift_table(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Get paginated list of shifts."""
    try:
        search = request.query_params.get("search")
        search_param = f"%{search}%" if search else None

        raw_branch_ids = request.query_params.get("branch_id")
        branch_ids = None
        if raw_branch_ids:
            try:
                branch_ids = [int(b) for b in raw_branch_ids.split(",") if b.strip()]
            except (ValueError, TypeError):
                branch_ids = None

        page = int(request.query_params.get("page", 1))
        limit = int(request.query_params.get("limit", 10))

        query = get_shift_list_query(branch_ids=branch_ids)
        result = db.execute(query, {"search": search_param}).fetchall()

        all_data = [_serialize_shift_row(row) for row in result]
        total = len(all_data)
        start_idx = (page - 1) * limit
        paginated_data = all_data[start_idx:start_idx + limit]

        return {
            "data": paginated_data,
            "total": total,
            "page": page,
            "limit": limit,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_shift_by_id/{shift_id}")
def get_shift_by_id(
    shift_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Get a single shift record by ID."""
    try:
        query = get_shift_by_id_query()
        result = db.execute(query, {"shift_id": shift_id}).fetchone()

        if not result:
            raise HTTPException(status_code=404, detail="Shift not found")

        return {"data": _serialize_shift_row(result)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/shift_create_setup")
def shift_create_setup(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Get dropdown options needed for shift creation (branches, spells)."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        branch_query = text("""
            SELECT branch_id, branch_name FROM branch_mst
            WHERE co_id = :co_id AND active = 1
            ORDER BY branch_name
        """)

        branches = db.execute(branch_query, {"co_id": int(co_id)}).fetchall()

        return {
            "branches": [dict(r._mapping) for r in branches],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/shift_create")
def shift_create(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Create a new shift record."""
    try:
        body = parse_json_body(request)

        shift_name = body.get("shift_name")
        if not shift_name:
            raise HTTPException(status_code=400, detail="Shift name is required")

        branch_id = body.get("branch_id")
        if not branch_id:
            raise HTTPException(status_code=400, detail="Branch is required")

        # Check duplicate name within same branch
        dup_query = text("""
            SELECT COUNT(*) AS cnt FROM shift_mst
            WHERE shift_name = :shift_name AND branch_id = :branch_id AND status = 1
        """)
        dup_result = db.execute(dup_query, {
            "shift_name": shift_name,
            "branch_id": int(branch_id),
        }).fetchone()

        if dup_result and dup_result.cnt > 0:
            raise HTTPException(
                status_code=400,
                detail="Shift with this name already exists in the selected branch",
            )

        user_id = token_data.get("user_id") if token_data else None

        insert_query = text("""
            INSERT INTO shift_mst
                (shift_name, status, branch_id, spell_type, starting_time,
                 working_hours, minimum_work_hours, break_hours, halfday_work_hours,
                 late_minutes, late_minutes2, week_off_day, week_off_day2,
                 week_off_halfDay, is_overnight, updated_by, update_date_time, end_time)
            VALUES
                (:shift_name, :status, :branch_id, :spell_type, :starting_time,
                 :working_hours, :minimum_work_hours, :break_hours, :halfday_work_hours,
                 :late_minutes, :late_minutes2, :week_off_day, :week_off_day2,
                 :week_off_halfDay, :is_overnight, :updated_by, :update_date_time, :end_time)
        """)
        result = db.execute(insert_query, {
            "shift_name": shift_name,
            "status": 1,
            "branch_id": int(branch_id),
            "spell_type": int(body["spell_type"]) if body.get("spell_type") else None,
            "starting_time": body.get("starting_time") or None,
            "working_hours": body.get("working_hours") or None,
            "minimum_work_hours": body.get("minimum_work_hours") or None,
            "break_hours": body.get("break_hours") or None,
            "halfday_work_hours": body.get("halfday_work_hours") or None,
            "late_minutes": int(body["late_minutes"]) if body.get("late_minutes") else None,
            "late_minutes2": int(body["late_minutes2"]) if body.get("late_minutes2") else None,
            "week_off_day": int(body["week_off_day"]) if body.get("week_off_day") else None,
            "week_off_day2": int(body["week_off_day2"]) if body.get("week_off_day2") else None,
            "week_off_halfDay": int(body["week_off_halfDay"]) if body.get("week_off_halfDay") else None,
            "is_overnight": int(body["is_overnight"]) if body.get("is_overnight") else 0,
            "updated_by": user_id,
            "update_date_time": datetime.now(),
            "end_time": body.get("end_time") or None,
        })
        db.commit()
        new_shift_id = result.lastrowid

        return {
            "message": "Shift created successfully",
            "shift_id": new_shift_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/shift_edit/{shift_id}")
def shift_edit(
    shift_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Update an existing shift record."""
    try:
        body = parse_json_body(request)

        shift_name = body.get("shift_name")
        if not shift_name:
            raise HTTPException(status_code=400, detail="Shift name is required")

        existing = db.query(ShiftMst).filter(
            ShiftMst.shift_id == shift_id,
        ).first()

        if not existing:
            raise HTTPException(status_code=404, detail="Shift not found")

        # Check duplicate name (excluding current record)
        dup_query = text("""
            SELECT COUNT(*) AS cnt FROM shift_mst
            WHERE shift_name = :shift_name AND branch_id = :branch_id
              AND status = 1 AND shift_id != :shift_id
        """)
        branch_id = body.get("branch_id", existing.branch_id)
        dup_result = db.execute(dup_query, {
            "shift_name": shift_name,
            "branch_id": int(branch_id) if branch_id else existing.branch_id,
            "shift_id": shift_id,
        }).fetchone()

        if dup_result and dup_result.cnt > 0:
            raise HTTPException(
                status_code=400,
                detail="Shift with this name already exists in the selected branch",
            )

        user_id = token_data.get("user_id") if token_data else None

        existing.shift_name = shift_name
        existing.branch_id = int(body["branch_id"]) if body.get("branch_id") else existing.branch_id
        existing.spell_type = int(body["spell_type"]) if body.get("spell_type") is not None else existing.spell_type
        existing.starting_time = body.get("starting_time", existing.starting_time)
        existing.working_hours = body.get("working_hours", existing.working_hours)
        existing.minimum_work_hours = body.get("minimum_work_hours", existing.minimum_work_hours)
        existing.break_hours = body.get("break_hours", existing.break_hours)
        existing.halfday_work_hours = body.get("halfday_work_hours", existing.halfday_work_hours)
        existing.late_minutes = int(body["late_minutes"]) if body.get("late_minutes") is not None else existing.late_minutes
        existing.late_minutes2 = int(body["late_minutes2"]) if body.get("late_minutes2") is not None else existing.late_minutes2
        existing.week_off_day = int(body["week_off_day"]) if body.get("week_off_day") is not None else existing.week_off_day
        existing.week_off_day2 = int(body["week_off_day2"]) if body.get("week_off_day2") is not None else existing.week_off_day2
        existing.week_off_halfDay = int(body["week_off_halfDay"]) if body.get("week_off_halfDay") is not None else existing.week_off_halfDay
        existing.is_overnight = int(body["is_overnight"]) if body.get("is_overnight") is not None else existing.is_overnight
        existing.end_time = body.get("end_time", existing.end_time)
        existing.updated_by = user_id
        existing.update_date_time = datetime.now()

        db.commit()

        return {"message": "Shift updated successfully", "shift_id": shift_id}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
