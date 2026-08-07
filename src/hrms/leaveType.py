"""
HRMS Leave Type Master API endpoints.

Provides CRUD operations for the hrms_leave_types_mst table.
leave_type_code (name) must be globally unique per company.
"""

from fastapi import Depends, Request, HTTPException, APIRouter, Response
from sqlalchemy.sql import text
from sqlalchemy.orm import Session
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.models.mst import HrmsLeaveTypesMst
from datetime import datetime
from src.common.utils import parse_json_body

router = APIRouter()


# ─── SQL Queries ────────────────────────────────────────────────────


def get_leave_type_list_query():
    return text("""
        SELECT
            lt.leave_type_id,
            lt.leave_type_code,
            lt.leave_type_description,
            lt.payable,
            lt.company_id,
            lt.is_active,
            lt.updated_by,
            lt.updated_date_time,
            lt.Leave_hours
        FROM hrms_leave_types_mst lt
        WHERE lt.is_active = 1
          AND lt.company_id = :company_id
          AND (:search IS NULL
               OR lt.leave_type_code LIKE :search
               OR lt.leave_type_description LIKE :search)
        ORDER BY lt.leave_type_id DESC
    """)


def get_leave_type_by_id_query():
    return text("""
        SELECT
            lt.leave_type_id,
            lt.leave_type_code,
            lt.leave_type_description,
            lt.payable,
            lt.company_id,
            lt.is_active,
            lt.updated_by,
            lt.updated_date_time,
            lt.Leave_hours
        FROM hrms_leave_types_mst lt
        WHERE lt.leave_type_id = :leave_type_id
    """)


# ─── Endpoints ──────────────────────────────────────────────────────


@router.get("/get_leave_type_table")
def get_leave_type_table(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Get paginated list of leave types."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        search = request.query_params.get("search")
        search_param = f"%{search}%" if search else None

        page = int(request.query_params.get("page", 1))
        limit = int(request.query_params.get("limit", 10))

        query = get_leave_type_list_query()
        result = db.execute(query, {
            "company_id": int(co_id),
            "search": search_param,
        }).fetchall()

        all_data = [dict(row._mapping) for row in result]
        total = len(all_data)
        start_idx = (page - 1) * limit
        paginated_data = all_data[start_idx : start_idx + limit]

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


@router.get("/get_leave_type_by_id/{leave_type_id}")
def get_leave_type_by_id(
    leave_type_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Get a single leave type record by ID."""
    try:
        query = get_leave_type_by_id_query()
        result = db.execute(query, {"leave_type_id": leave_type_id}).fetchone()

        if not result:
            raise HTTPException(status_code=404, detail="Leave type not found")

        return {"data": dict(result._mapping)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/leave_type_create")
def leave_type_create(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Create a new leave type record."""
    try:
        body = parse_json_body(request)

        co_id = body.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        leave_type_code = body.get("leave_type_code")
        if not leave_type_code:
            raise HTTPException(status_code=400, detail="Leave type code is required")

        leave_type_desc = body.get("leave_type_description")
        if not leave_type_desc:
            raise HTTPException(status_code=400, detail="Leave type description is required")

        # Check duplicate leave_type_code within same company
        dup_query = text("""
            SELECT COUNT(*) AS cnt FROM hrms_leave_types_mst
            WHERE leave_type_code = :leave_type_code
              AND company_id = :company_id AND is_active = 1
        """)
        dup_result = db.execute(dup_query, {
            "leave_type_code": leave_type_code,
            "company_id": int(co_id),
        }).fetchone()

        if dup_result and dup_result.cnt > 0:
            raise HTTPException(
                status_code=400,
                detail="Leave type with this code already exists",
            )

        user_id = token_data.get("user_id") if token_data else None

        new_record = HrmsLeaveTypesMst(
            leave_type_code=leave_type_code,
            leave_type_description=leave_type_desc,
            payable=body.get("payable", "N"),
            company_id=int(co_id),
            is_active=1,
            updated_by=user_id,
            updated_date_time=datetime.now(),
            Leave_hours=body.get("leave_hours"),
        )
        db.add(new_record)
        db.commit()
        db.refresh(new_record)

        return {
            "message": "Leave type created successfully",
            "leave_type_id": new_record.leave_type_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/leave_type_edit/{leave_type_id}")
def leave_type_edit(
    leave_type_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Update an existing leave type record."""
    try:
        body = parse_json_body(request)

        leave_type_code = body.get("leave_type_code")
        if not leave_type_code:
            raise HTTPException(status_code=400, detail="Leave type code is required")

        existing = db.query(HrmsLeaveTypesMst).filter(
            HrmsLeaveTypesMst.leave_type_id == leave_type_id,
        ).first()

        if not existing:
            raise HTTPException(status_code=404, detail="Leave type not found")

        co_id = body.get("co_id", existing.company_id)

        # Check duplicate leave_type_code (excluding current record)
        dup_query = text("""
            SELECT COUNT(*) AS cnt FROM hrms_leave_types_mst
            WHERE leave_type_code = :leave_type_code
              AND company_id = :company_id AND is_active = 1
              AND leave_type_id != :leave_type_id
        """)
        dup_result = db.execute(dup_query, {
            "leave_type_code": leave_type_code,
            "company_id": int(co_id),
            "leave_type_id": leave_type_id,
        }).fetchone()

        if dup_result and dup_result.cnt > 0:
            raise HTTPException(
                status_code=400,
                detail="Leave type with this code already exists",
            )

        user_id = token_data.get("user_id") if token_data else None

        existing.leave_type_code = leave_type_code
        existing.leave_type_description = body.get("leave_type_description", existing.leave_type_description)
        existing.payable = body.get("payable", existing.payable)
        existing.Leave_hours = body.get("leave_hours", existing.Leave_hours)
        existing.updated_by = user_id
        existing.updated_date_time = datetime.now()

        db.commit()

        return {"message": "Leave type updated successfully", "leave_type_id": leave_type_id}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
