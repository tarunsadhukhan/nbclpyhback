"""
Jute Supplier Master API endpoints.
Provides CRUD operations for jute supplier data.
Suppliers are global (not company-specific) - they exist across all tenants.
"""

from fastapi import Depends, Request, HTTPException, APIRouter, Response
from sqlalchemy.sql import text
from sqlalchemy.orm import Session
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.models.jute import JuteSupplierMst
from datetime import datetime
from src.common.utils import now_ist
from src.common.utils import parse_json_body

router = APIRouter()


def get_jute_supplier_list_query():
    """
    Get all jute suppliers (global - not company-specific).
    """
    return text("""
        SELECT 
            js.supplier_id,
            js.supplier_name,
            js.email,
            js.contact_no,
            js.updated_by,
            js.updated_date_time
        FROM jute_supplier_mst js
        ORDER BY js.supplier_name ASC
    """)


def get_jute_supplier_list_with_search_query():
    """
    Get all jute suppliers with search filter.
    """
    return text("""
        SELECT 
            js.supplier_id,
            js.supplier_name,
            js.email,
            js.contact_no,
            js.updated_by,
            js.updated_date_time
        FROM jute_supplier_mst js
        WHERE js.supplier_name LIKE :search
        ORDER BY js.supplier_name ASC
    """)


@router.get("/get_jute_supplier_table")
def get_jute_supplier_table(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    search: str = None,
    page: int = 1,
    limit: int = 10,
):
    """
    Get paginated list of jute suppliers.
    Suppliers are global - not filtered by company.
    """
    try:
        # Prepare search parameter for LIKE if provided
        search_param = f"%{search}%" if search else None

        # Choose query based on search
        if search_param:
            query = get_jute_supplier_list_with_search_query()
            params = {"search": search_param}
        else:
            query = get_jute_supplier_list_query()
            params = {}

        result = db.execute(query, params).fetchall()
        all_data = [dict(row._mapping) for row in result]

        # Calculate pagination
        total = len(all_data)
        start_idx = (page - 1) * limit
        end_idx = start_idx + limit
        paginated_data = all_data[start_idx:end_idx]

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


@router.get("/get_jute_supplier_by_id/{supplier_id}")
def get_jute_supplier_by_id(
    supplier_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Get a single jute supplier record by ID.
    """
    try:
        query = text("""
            SELECT 
                js.supplier_id,
                js.supplier_name,
                js.email,
                js.contact_no,
                js.updated_by,
                js.updated_date_time
            FROM jute_supplier_mst js
            WHERE js.supplier_id = :supplier_id
        """)

        result = db.execute(query, {"supplier_id": supplier_id}).fetchone()
        
        if not result:
            raise HTTPException(status_code=404, detail="Jute supplier record not found")

        return {"data": dict(result._mapping)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/jute_supplier_edit_setup/{supplier_id}")
def jute_supplier_edit_setup(
    supplier_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Get setup data for editing a jute supplier record.
    Returns the existing supplier details.
    """
    try:
        query = text("""
            SELECT 
                js.supplier_id,
                js.supplier_name,
                js.email,
                js.contact_no,
                js.updated_by,
                js.updated_date_time
            FROM jute_supplier_mst js
            WHERE js.supplier_id = :supplier_id
        """)

        result = db.execute(query, {"supplier_id": supplier_id}).fetchone()
        
        if not result:
            raise HTTPException(status_code=404, detail="Jute supplier record not found")

        return {
            "jute_supplier_details": dict(result._mapping)
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/jute_supplier_create")
def jute_supplier_create(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Create a new jute supplier record.
    """
    try:
        body = parse_json_body(request)
        supplier_name = (body.get("supplier_name") or "").strip()
        email = (body.get("email") or "").strip() or None
        contact_no = (body.get("contact_no") or "").strip() or None

        if not supplier_name:
            raise HTTPException(status_code=400, detail="Supplier name is required")

        # Check for duplicate supplier name
        duplicate_query = text("""
            SELECT supplier_id FROM jute_supplier_mst 
            WHERE LOWER(supplier_name) = LOWER(:supplier_name)
        """)
        existing = db.execute(duplicate_query, {"supplier_name": supplier_name}).fetchone()
        if existing:
            raise HTTPException(
                status_code=400, 
                detail=f"A supplier with the name '{supplier_name}' already exists"
            )

        # Get user ID from token
        user_id = token_data.get("user_id") if isinstance(token_data, dict) else None

        # Insert new supplier
        insert_query = text("""
            INSERT INTO jute_supplier_mst (supplier_name, email, contact_no, updated_by, updated_date_time)
            VALUES (:supplier_name, :email, :contact_no, :updated_by, :updated_date_time)
        """)
        
        db.execute(insert_query, {
            "supplier_name": supplier_name,
            "email": email,
            "contact_no": contact_no,
            "updated_by": user_id,
            "updated_date_time": now_ist(),
        })
        db.commit()

        return {"message": "Jute supplier created successfully"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/jute_supplier_edit/{supplier_id}")
def jute_supplier_edit(
    supplier_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Update an existing jute supplier record.
    """
    try:
        body = parse_json_body(request)
        supplier_name = (body.get("supplier_name") or "").strip()
        email = (body.get("email") or "").strip() or None
        contact_no = (body.get("contact_no") or "").strip() or None

        if not supplier_name:
            raise HTTPException(status_code=400, detail="Supplier name is required")

        # Check if supplier exists
        exists_query = text("""
            SELECT supplier_id FROM jute_supplier_mst 
            WHERE supplier_id = :supplier_id
        """)
        existing = db.execute(exists_query, {"supplier_id": supplier_id}).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Jute supplier not found")

        # Check for duplicate supplier name (excluding current record)
        duplicate_query = text("""
            SELECT supplier_id FROM jute_supplier_mst 
            WHERE LOWER(supplier_name) = LOWER(:supplier_name)
              AND supplier_id != :supplier_id
        """)
        duplicate = db.execute(duplicate_query, {
            "supplier_name": supplier_name,
            "supplier_id": supplier_id
        }).fetchone()
        if duplicate:
            raise HTTPException(
                status_code=400, 
                detail=f"A supplier with the name '{supplier_name}' already exists"
            )

        # Get user ID from token
        user_id = token_data.get("user_id") if isinstance(token_data, dict) else None

        # Update supplier
        update_query = text("""
            UPDATE jute_supplier_mst 
            SET supplier_name = :supplier_name,
                email = :email,
                contact_no = :contact_no,
                updated_by = :updated_by,
                updated_date_time = :updated_date_time
            WHERE supplier_id = :supplier_id
        """)
        
        db.execute(update_query, {
            "supplier_id": supplier_id,
            "supplier_name": supplier_name,
            "email": email,
            "contact_no": contact_no,
            "updated_by": user_id,
            "updated_date_time": now_ist(),
        })
        db.commit()

        return {"message": "Jute supplier updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
