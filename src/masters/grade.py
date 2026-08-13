"""
Grade Master API endpoints.

Provides CRUD operations for the grade_table table.
Fields: grade_code (max 4 chars), grade_name, grade_type (0 = Worker, 1 = Staff).
Tenant-wide master - no co_id / branch_id scoping on the table.
"""

from fastapi import Depends, Request, HTTPException, APIRouter, Response
from sqlalchemy.sql import text
from sqlalchemy.orm import Session
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.models.mst import GradeTable
from src.common.utils import parse_json_body

router = APIRouter()

GRADE_TYPES = {0: "Worker", 1: "Staff"}


def _parse_grade_type(raw):
    """Coerce grade_type to 0 or 1; anything else is a 400."""
    if raw is None or raw == "":
        return 0
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="grade_type must be 0 (Worker) or 1 (Staff)")
    if value not in GRADE_TYPES:
        raise HTTPException(status_code=400, detail="grade_type must be 0 (Worker) or 1 (Staff)")
    return value


def _validate_body(body):
    """Shared create/edit validation. Returns (grade_code, grade_name, grade_type)."""
    grade_code = (body.get("grade_code") or "").strip()
    if not grade_code:
        raise HTTPException(status_code=400, detail="Grade code is required")
    if len(grade_code) > 4:
        raise HTTPException(status_code=400, detail="Grade code cannot exceed 4 characters")

    grade_name = (body.get("grade_name") or "").strip()
    if not grade_name:
        raise HTTPException(status_code=400, detail="Grade name is required")
    if len(grade_name) > 100:
        raise HTTPException(status_code=400, detail="Grade name cannot exceed 100 characters")

    return grade_code, grade_name, _parse_grade_type(body.get("grade_type"))


# ─── SQL Queries ────────────────────────────────────────────────────


def get_grade_list_query(grade_type=None):
    type_filter = "AND g.grade_type = :grade_type" if grade_type is not None else ""
    return text(f"""
        SELECT
            g.grade_id,
            g.grade_code,
            g.grade_name,
            g.grade_type
        FROM grade_table g
        WHERE (:search IS NULL OR g.grade_code LIKE :search
               OR g.grade_name LIKE :search)
        {type_filter}
        ORDER BY g.grade_id DESC
    """)


def get_grade_by_id_query():
    return text("""
        SELECT
            g.grade_id,
            g.grade_code,
            g.grade_name,
            g.grade_type
        FROM grade_table g
        WHERE g.grade_id = :grade_id
    """)


# ─── Endpoints ──────────────────────────────────────────────────────


@router.get("/get_grade_table")
def get_grade_table(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Get paginated list of grades."""
    try:
        search = request.query_params.get("search")
        search_param = f"%{search}%" if search else None

        page = int(request.query_params.get("page", 1))
        limit = int(request.query_params.get("limit", 10))

        raw_type = request.query_params.get("grade_type")
        grade_type = _parse_grade_type(raw_type) if raw_type not in (None, "") else None

        params = {"search": search_param}
        if grade_type is not None:
            params["grade_type"] = grade_type

        result = db.execute(get_grade_list_query(grade_type=grade_type), params).fetchall()

        all_data = [dict(row._mapping) for row in result]
        for row in all_data:
            row["grade_type_name"] = GRADE_TYPES.get(row.get("grade_type"), "")

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


@router.get("/get_grade_by_id/{grade_id}")
def get_grade_by_id(
    grade_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Get a single grade record by ID."""
    try:
        result = db.execute(get_grade_by_id_query(), {"grade_id": grade_id}).fetchone()

        if not result:
            raise HTTPException(status_code=404, detail="Grade not found")

        data = dict(result._mapping)
        data["grade_type_name"] = GRADE_TYPES.get(data.get("grade_type"), "")
        return {"data": data}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/grade_create")
def grade_create(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Create a new grade record."""
    try:
        grade_code, grade_name, grade_type = _validate_body(parse_json_body(request))

        dup_query = text("SELECT COUNT(*) AS cnt FROM grade_table WHERE grade_code = :grade_code")
        dup_result = db.execute(dup_query, {"grade_code": grade_code}).fetchone()
        if dup_result and dup_result.cnt > 0:
            raise HTTPException(status_code=400, detail="Grade with this code already exists")

        new_grade = GradeTable(
            grade_code=grade_code,
            grade_name=grade_name,
            grade_type=grade_type,
        )
        db.add(new_grade)
        db.commit()
        db.refresh(new_grade)

        return {"message": "Grade created successfully", "grade_id": new_grade.grade_id}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/grade_edit/{grade_id}")
def grade_edit(
    grade_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Update an existing grade record."""
    try:
        grade_code, grade_name, grade_type = _validate_body(parse_json_body(request))

        existing = db.query(GradeTable).filter(GradeTable.grade_id == grade_id).first()
        if not existing:
            raise HTTPException(status_code=404, detail="Grade not found")

        dup_query = text("""
            SELECT COUNT(*) AS cnt FROM grade_table
            WHERE grade_code = :grade_code AND grade_id != :grade_id
        """)
        dup_result = db.execute(dup_query, {
            "grade_code": grade_code,
            "grade_id": grade_id,
        }).fetchone()
        if dup_result and dup_result.cnt > 0:
            raise HTTPException(status_code=400, detail="Grade with this code already exists")

        existing.grade_code = grade_code
        existing.grade_name = grade_name
        existing.grade_type = grade_type

        db.commit()

        return {"message": "Grade updated successfully", "grade_id": grade_id}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
