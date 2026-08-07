"""
Batch Daily Assignment API endpoints.
Maps yarn types to batch plans for each day and branch.
Status workflow: Draft (21) -> Open (1) -> Approved (3) / Rejected (4).
"""

from fastapi import Depends, Request, HTTPException, APIRouter
from typing import Optional, List
from pydantic import BaseModel
from datetime import date, datetime
import logging
from sqlalchemy.orm import Session
from sqlalchemy import text
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.juteProcurement.query import (
    get_batch_daily_assign_table_query,
    get_batch_daily_assign_table_count_query,
    get_batch_daily_assigns_by_date_query,
    get_batch_daily_assign_create_setup_query,
    get_batch_plans_for_branch_query,
    get_batch_daily_assign_max_date_query,
)
from src.juteProcurement._excel_utils import (
    parse_iso_date,
    build_excel_response,
    enforce_row_cap,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class BatchDailyAssignCreate(BaseModel):
    """Payload for creating a single daily batch assignment."""
    branch_id: int
    assign_date: date
    jute_yarn_id: int
    batch_plan_id: int


class BatchDailyAssignStatusUpdate(BaseModel):
    """Payload for bulk status transitions."""
    ids: List[int]


# ---------------------------------------------------------------------------
# READ endpoints
# ---------------------------------------------------------------------------

BATCH_DAILY_ASSIGN_DOWNLOAD_COLUMNS = [
    ("Assign Date", "assign_date"),
    ("Branch", "branch_name"),
    ("Total Assignments", "total_assignments"),
    ("Approved Count", "approved_count"),
    ("Status", "status"),
]


def _build_assign_params(branch_id: int, q_search: str, date_from, date_to):
    search_param = f"%{q_search}%" if q_search else None
    base = {
        "branch_id": branch_id,
        "date_from": date_from,
        "date_to": date_to,
    }
    if search_param:
        base["search"] = search_param
    return base


@router.get("/get_assign_table")
def get_assign_table(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """List page: aggregated by day+branch.

    Query params:
    - branch_id: required
    - page / limit / search
    - from_date / to_date: Optional ISO dates (YYYY-MM-DD) bounding assign_date
    """
    try:
        q_branch_id = request.query_params.get("branch_id")
        q_page = request.query_params.get("page", "1")
        q_limit = request.query_params.get("limit", "10")
        q_search = request.query_params.get("search", "").strip()
        q_from_date = (request.query_params.get("from_date") or "").strip()
        q_to_date = (request.query_params.get("to_date") or "").strip()

        if not q_branch_id:
            raise HTTPException(status_code=400, detail="branch_id is required")

        try:
            branch_id = int(q_branch_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid branch_id")

        date_from = parse_iso_date(q_from_date, "from_date")
        date_to = parse_iso_date(q_to_date, "to_date")

        try:
            page = max(1, int(q_page))
            limit = max(1, min(100, int(q_limit)))
        except ValueError:
            page = 1
            limit = 10

        offset = (page - 1) * limit
        base_params = _build_assign_params(branch_id, q_search, date_from, date_to)

        count_query = get_batch_daily_assign_table_count_query(search=q_search)
        count_result = db.execute(count_query, base_params).fetchone()
        total = count_result.total if count_result else 0

        data_query = get_batch_daily_assign_table_query(search=q_search)
        params = {**base_params, "limit": limit, "offset": offset}

        rows = db.execute(data_query, params).fetchall()
        data = [dict(r._mapping) for r in rows]

        return {
            "data": data,
            "total": total,
            "page": page,
            "page_size": limit,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching batch daily assign table: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error fetching batch daily assign records: {str(e)}")


@router.get("/download_assign_table")
def download_assign_table(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Download Batch Daily Assign list (aggregated) as .xlsx with same filters."""
    try:
        q_branch_id = request.query_params.get("branch_id")
        q_search = request.query_params.get("search", "").strip()
        q_from_date = (request.query_params.get("from_date") or "").strip()
        q_to_date = (request.query_params.get("to_date") or "").strip()

        if not q_branch_id:
            raise HTTPException(status_code=400, detail="branch_id is required")
        try:
            branch_id = int(q_branch_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid branch_id")

        date_from = parse_iso_date(q_from_date, "from_date")
        date_to = parse_iso_date(q_to_date, "to_date")

        base_params = _build_assign_params(branch_id, q_search, date_from, date_to)

        count_query = get_batch_daily_assign_table_count_query(search=q_search)
        count_result = db.execute(count_query, base_params).fetchone()
        total = int(count_result.total) if count_result and count_result.total else 0
        enforce_row_cap(total)

        rows = []
        if total > 0:
            data_query = get_batch_daily_assign_table_query(search=q_search)
            data_params = {**base_params, "limit": total, "offset": 0}
            result = db.execute(data_query, data_params).fetchall()
            rows = [dict(r._mapping) for r in result]

        return build_excel_response(
            rows=rows,
            columns=BATCH_DAILY_ASSIGN_DOWNLOAD_COLUMNS,
            sheet_title="Batch Daily Assign",
            filename_prefix="batch_daily_assign",
            from_date_str=q_from_date,
            to_date_str=q_to_date,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error downloading batch daily assign table")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_assigns_by_date")
def get_assigns_by_date(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Detail page: all assignments for a specific date+branch."""
    try:
        q_co_id = request.query_params.get("co_id")
        q_branch_id = request.query_params.get("branch_id")
        q_assign_date = request.query_params.get("assign_date")

        if not q_co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        if not q_branch_id:
            raise HTTPException(status_code=400, detail="branch_id is required")
        if not q_assign_date:
            raise HTTPException(status_code=400, detail="assign_date is required")

        branch_id = int(q_branch_id)

        query = get_batch_daily_assigns_by_date_query()
        rows = db.execute(query, {
            "branch_id": branch_id,
            "assign_date": q_assign_date,
        }).fetchall()

        data = [dict(r._mapping) for r in rows]

        # Build summary
        total = len(data)
        approved_count = sum(1 for r in data if r.get("status_id") == 3)
        if total == 0:
            status = "No Assignments"
            status_id = 0
        elif approved_count == total:
            status = "Approved"
            status_id = 3
        elif approved_count > 0:
            status = "Partial Approved"
            status_id = 20
        else:
            # Check if all draft
            draft_count = sum(1 for r in data if r.get("status_id") == 21)
            if draft_count == total:
                status = "Draft"
                status_id = 21
            else:
                status = "Open"
                status_id = 1

        return {
            "data": data,
            "summary": {
                "total_assignments": total,
                "status": status,
                "status_id": status_id,
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching assigns by date: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error fetching assignments: {str(e)}")


@router.get("/get_assign_create_setup")
def get_assign_create_setup(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Setup data: yarn types + batch plans for the branch."""
    try:
        q_co_id = request.query_params.get("co_id")
        q_branch_id = request.query_params.get("branch_id")

        if not q_co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        if not q_branch_id:
            raise HTTPException(status_code=400, detail="branch_id is required")

        co_id = int(q_co_id)
        branch_id = int(q_branch_id)

        # Yarn types
        yt_query = get_batch_daily_assign_create_setup_query()
        yarn_types_rows = db.execute(yt_query, {"co_id": co_id}).fetchall()
        yarn_types = [dict(r._mapping) for r in yarn_types_rows]

        # Batch plans for this branch
        bp_query = get_batch_plans_for_branch_query()
        batch_plans_rows = db.execute(bp_query, {"branch_id": branch_id}).fetchall()
        batch_plans = [dict(r._mapping) for r in batch_plans_rows]

        return {
            "yarn_types": yarn_types,
            "batch_plans": batch_plans,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching assign create setup: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error fetching setup data: {str(e)}")


@router.get("/get_max_assign_date")
def get_max_assign_date(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Get latest assignment date for auto-increment."""
    try:
        q_co_id = request.query_params.get("co_id")
        q_branch_id = request.query_params.get("branch_id")

        if not q_co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        if not q_branch_id:
            raise HTTPException(status_code=400, detail="branch_id is required")

        branch_id = int(q_branch_id)

        query = get_batch_daily_assign_max_date_query()
        result = db.execute(query, {"branch_id": branch_id}).fetchone()
        max_date = result.max_date if result else None

        return {
            "max_date": max_date.isoformat() if max_date else None
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching max assign date: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error fetching max assign date: {str(e)}")


# ---------------------------------------------------------------------------
# WRITE endpoints
# ---------------------------------------------------------------------------

@router.post("/create_assign")
def create_assign(
    payload: BatchDailyAssignCreate,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Create a single daily assignment. Status defaults to Draft (21)."""
    try:
        q_co_id = request.query_params.get("co_id")
        if not q_co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        user_id = token_data.get("user_id")

        # Check for duplicate
        dup_check = text("""
            SELECT batch_daily_assign_id FROM jute_batch_daily_assign
            WHERE branch_id = :branch_id AND assign_date = :assign_date AND jute_yarn_id = :jute_yarn_id
        """)
        existing = db.execute(dup_check, {
            "branch_id": payload.branch_id,
            "assign_date": payload.assign_date,
            "jute_yarn_id": payload.jute_yarn_id,
        }).fetchone()
        if existing:
            raise HTTPException(
                status_code=400,
                detail="Yarn type already assigned for this date and branch.",
            )

        insert_sql = text("""
            INSERT INTO jute_batch_daily_assign
                (branch_id, assign_date, jute_yarn_id, batch_plan_id, status_id, updated_by, updated_date_time)
            VALUES
                (:branch_id, :assign_date, :jute_yarn_id, :batch_plan_id, 21, :updated_by, NOW())
        """)
        db.execute(insert_sql, {
            "branch_id": payload.branch_id,
            "assign_date": payload.assign_date,
            "jute_yarn_id": payload.jute_yarn_id,
            "batch_plan_id": payload.batch_plan_id,
            "updated_by": user_id,
        })
        db.commit()

        # Get the inserted ID
        result = db.execute(text("SELECT LAST_INSERT_ID() AS id")).fetchone()
        new_id = result.id if result else None

        return {
            "message": "Assignment created successfully.",
            "batch_daily_assign_id": new_id,
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating assign: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error creating assignment: {str(e)}")


@router.delete("/delete_assign/{batch_daily_assign_id}")
def delete_assign(
    batch_daily_assign_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Delete a draft assignment."""
    try:
        q_co_id = request.query_params.get("co_id")
        if not q_co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        # Only allow deleting drafts
        check = text("""
            SELECT status_id FROM jute_batch_daily_assign
            WHERE batch_daily_assign_id = :id
        """)
        result = db.execute(check, {"id": batch_daily_assign_id}).fetchone()
        if result is None:
            raise HTTPException(status_code=404, detail="Assignment not found.")
        if result.status_id != 21:
            raise HTTPException(status_code=400, detail="Only draft assignments can be deleted.")

        delete_sql = text("""
            DELETE FROM jute_batch_daily_assign WHERE batch_daily_assign_id = :id
        """)
        db.execute(delete_sql, {"id": batch_daily_assign_id})
        db.commit()

        return {"message": "Assignment deleted."}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting assign: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error deleting assignment: {str(e)}")


# ---------------------------------------------------------------------------
# Status transition endpoints
# ---------------------------------------------------------------------------

def _bulk_status_change(db: Session, ids: List[int], from_status: int, to_status: int, user_id):
    """Helper: bulk status transition with validation."""
    if not ids:
        raise HTTPException(status_code=400, detail="No IDs provided.")

    placeholders = ", ".join([f":id_{i}" for i in range(len(ids))])
    params = {f"id_{i}": id_val for i, id_val in enumerate(ids)}

    # Validate all are in expected status
    check_sql = text(f"""
        SELECT batch_daily_assign_id, status_id FROM jute_batch_daily_assign
        WHERE batch_daily_assign_id IN ({placeholders})
    """)
    rows = db.execute(check_sql, params).fetchall()

    if len(rows) != len(ids):
        raise HTTPException(status_code=404, detail="Some assignments not found.")

    invalid = [r._mapping["batch_daily_assign_id"] for r in rows if r._mapping["status_id"] != from_status]
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=f"Assignments {invalid} are not in the expected status.",
        )

    update_sql = text(f"""
        UPDATE jute_batch_daily_assign
        SET status_id = :to_status, updated_by = :user_id, updated_date_time = NOW()
        WHERE batch_daily_assign_id IN ({placeholders})
    """)
    params["to_status"] = to_status
    params["user_id"] = user_id
    db.execute(update_sql, params)
    db.commit()


@router.post("/open_assigns")
def open_assigns(
    payload: BatchDailyAssignStatusUpdate,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Bulk Draft (21) -> Open (1)."""
    try:
        q_co_id = request.query_params.get("co_id")
        if not q_co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        user_id = token_data.get("user_id")
        _bulk_status_change(db, payload.ids, from_status=21, to_status=1, user_id=user_id)
        return {"message": f"{len(payload.ids)} assignment(s) opened."}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error opening assigns: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error opening assignments: {str(e)}")


@router.post("/approve_assigns")
def approve_assigns(
    payload: BatchDailyAssignStatusUpdate,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Bulk Open (1) -> Approved (3)."""
    try:
        q_co_id = request.query_params.get("co_id")
        if not q_co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        user_id = token_data.get("user_id")
        _bulk_status_change(db, payload.ids, from_status=1, to_status=3, user_id=user_id)
        return {"message": f"{len(payload.ids)} assignment(s) approved."}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error approving assigns: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error approving assignments: {str(e)}")


@router.post("/reject_assigns")
def reject_assigns(
    payload: BatchDailyAssignStatusUpdate,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Bulk Open (1) -> Rejected (4)."""
    try:
        q_co_id = request.query_params.get("co_id")
        if not q_co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        user_id = token_data.get("user_id")
        _bulk_status_change(db, payload.ids, from_status=1, to_status=4, user_id=user_id)
        return {"message": f"{len(payload.ids)} assignment(s) rejected."}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error rejecting assigns: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error rejecting assignments: {str(e)}")
