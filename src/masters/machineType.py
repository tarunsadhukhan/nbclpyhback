"""
Machine Type Master API endpoints.

Provides CRUD operations for the machine_type_mst table.
"""

from fastapi import Depends, Request, HTTPException, APIRouter, Response
from sqlalchemy.sql import text
from sqlalchemy.orm import Session
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from datetime import datetime
from src.common.utils import parse_json_body

router = APIRouter()


# ─── SQL Queries ────────────────────────────────────────────────────


def get_machine_type_list_query():
    return text("""
        SELECT
            m.machine_type_id,
            m.machine_type_name,
            m.active,
            m.updated_by,
            m.updated_date_time
        FROM machine_type_mst m
        WHERE (:search IS NULL OR m.machine_type_name LIKE :search)
        ORDER BY m.machine_type_id DESC
    """)


def get_machine_type_by_id_query():
    return text("""
        SELECT
            m.machine_type_id,
            m.machine_type_name,
            m.active,
            m.updated_by,
            m.updated_date_time
        FROM machine_type_mst m
        WHERE m.machine_type_id = :machine_type_id
    """)


# ─── Endpoints ──────────────────────────────────────────────────────


@router.get("/get_machine_type_table")
def get_machine_type_table(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Get paginated list of machine types."""
    try:
        search = request.query_params.get("search")
        search_param = f"%{search}%" if search else None

        page = int(request.query_params.get("page", 1))
        limit = int(request.query_params.get("limit", 10))

        query = get_machine_type_list_query()
        result = db.execute(query, {"search": search_param}).fetchall()

        all_data = [dict(row._mapping) for row in result]
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


@router.get("/get_machine_type_by_id/{machine_type_id}")
def get_machine_type_by_id(
    machine_type_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Get a single machine type record by ID."""
    try:
        query = get_machine_type_by_id_query()
        result = db.execute(query, {"machine_type_id": machine_type_id}).fetchone()

        if not result:
            raise HTTPException(status_code=404, detail="Machine type not found")

        return {"data": dict(result._mapping)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/machine_type_create")
def machine_type_create(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Create a new machine type record."""
    try:
        body = parse_json_body(request)

        machine_type_name = body.get("machine_type_name")
        if not machine_type_name:
            raise HTTPException(status_code=400, detail="Machine type name is required")

        # Check duplicate name (matches DB unique constraint on machine_type_name)
        dup_query = text("""
            SELECT COUNT(*) AS cnt FROM machine_type_mst
            WHERE machine_type_name = :machine_type_name
        """)
        dup_result = db.execute(dup_query, {
            "machine_type_name": machine_type_name,
        }).fetchone()

        if dup_result and dup_result.cnt > 0:
            raise HTTPException(
                status_code=400,
                detail="Machine type with this name already exists",
            )

        user_id = token_data.get("user_id") if token_data else None

        insert_query = text("""
            INSERT INTO machine_type_mst
                (machine_type_name, updated_by, updated_date_time, active)
            VALUES
                (:machine_type_name, :updated_by, :updated_date_time, :active)
        """)
        active = body.get("active", 1)
        try:
            active = int(active)
        except (TypeError, ValueError):
            active = 1

        result = db.execute(insert_query, {
            "machine_type_name": machine_type_name,
            "updated_by": user_id,
            "updated_date_time": datetime.now(),
            "active": active,
        })
        db.commit()
        new_id = result.lastrowid

        return {
            "message": "Machine type created successfully",
            "machine_type_id": new_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/machine_type_edit/{machine_type_id}")
def machine_type_edit(
    machine_type_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Update an existing machine type record."""
    try:
        body = parse_json_body(request)

        machine_type_name = body.get("machine_type_name")
        if not machine_type_name:
            raise HTTPException(status_code=400, detail="Machine type name is required")

        # Check exists
        existing_query = text("""
            SELECT machine_type_id FROM machine_type_mst
            WHERE machine_type_id = :machine_type_id
        """)
        existing = db.execute(existing_query, {"machine_type_id": machine_type_id}).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Machine type not found")

        # Check duplicate name (matches DB unique constraint, excluding current record)
        dup_query = text("""
            SELECT COUNT(*) AS cnt FROM machine_type_mst
            WHERE machine_type_name = :machine_type_name
              AND machine_type_id != :machine_type_id
        """)
        dup_result = db.execute(dup_query, {
            "machine_type_name": machine_type_name,
            "machine_type_id": machine_type_id,
        }).fetchone()

        if dup_result and dup_result.cnt > 0:
            raise HTTPException(
                status_code=400,
                detail="Machine type with this name already exists",
            )

        user_id = token_data.get("user_id") if token_data else None

        active = body.get("active", 1)
        try:
            active = int(active)
        except (TypeError, ValueError):
            active = 1

        update_query = text("""
            UPDATE machine_type_mst
            SET machine_type_name = :machine_type_name,
                active = :active,
                updated_by = :updated_by,
                updated_date_time = :updated_date_time
            WHERE machine_type_id = :machine_type_id
        """)
        db.execute(update_query, {
            "machine_type_name": machine_type_name,
            "active": active,
            "updated_by": user_id,
            "updated_date_time": datetime.now(),
            "machine_type_id": machine_type_id,
        })
        db.commit()

        return {"message": "Machine type updated successfully", "machine_type_id": machine_type_id}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/machine_type_delete/{machine_type_id}")
def machine_type_delete(
    machine_type_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Soft-delete a machine type (set active = 0) after FK check."""
    try:
        # Check exists
        existing_query = text("""
            SELECT machine_type_id FROM machine_type_mst
            WHERE machine_type_id = :machine_type_id
        """)
        existing = db.execute(existing_query, {"machine_type_id": machine_type_id}).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Machine type not found")

        # FK check: ensure no machine_mst records reference this machine type
        fk_query = text("""
            SELECT COUNT(*) AS cnt FROM machine_mst
            WHERE machine_type_id = :machine_type_id AND active = 1
        """)
        fk_result = db.execute(fk_query, {"machine_type_id": machine_type_id}).fetchone()
        if fk_result and fk_result.cnt > 0:
            raise HTTPException(
                status_code=400,
                detail="Cannot delete: this machine type is in use by machines",
            )

        user_id = token_data.get("user_id") if token_data else None

        delete_query = text("""
            UPDATE machine_type_mst
            SET active = 0,
                updated_by = :updated_by,
                updated_date_time = :updated_date_time
            WHERE machine_type_id = :machine_type_id
        """)
        db.execute(delete_query, {
            "updated_by": user_id,
            "updated_date_time": datetime.now(),
            "machine_type_id": machine_type_id,
        })
        db.commit()

        return {"message": "Machine type deleted successfully", "machine_type_id": machine_type_id}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
