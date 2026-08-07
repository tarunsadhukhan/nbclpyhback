"""
Yarn Type Master API endpoints.

Yarn types are stored in item_grp_mst with item_type_id = 4.
Previously used jute_yarn_type_mst (now deprecated).
Provides CRUD operations filtered to item_type_id = 4, parent_grp_id IS NULL.
"""

from fastapi import Depends, Request, HTTPException, APIRouter, Response
from sqlalchemy.sql import text
from sqlalchemy.orm import Session
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.masters.models import ItemGrpMst
from datetime import datetime
from src.common.utils import now_ist
from src.common.utils import parse_json_body

router = APIRouter()

# item_type_id for Yarn in item_type_master
YARN_ITEM_TYPE_ID = 4


def get_yarn_type_list_query():
    """
    Get all yarn types (item groups with item_type_id=4) for a company.
    """
    return text("""
        SELECT 
            ig.item_grp_id,
            ig.item_grp_name,
            ig.item_grp_code,
            ig.co_id,
            ig.active,
            ig.updated_by,
            ig.updated_date_time
        FROM item_grp_mst ig
        WHERE ig.co_id = :co_id
          AND ig.item_type_id = :item_type_id
          AND ig.parent_grp_id IS NULL
        ORDER BY ig.item_grp_id DESC
    """)


def get_yarn_type_list_with_search_query():
    """
    Get all yarn types for a company with search filter.
    """
    return text("""
        SELECT 
            ig.item_grp_id,
            ig.item_grp_name,
            ig.item_grp_code,
            ig.co_id,
            ig.active,
            ig.updated_by,
            ig.updated_date_time
        FROM item_grp_mst ig
        WHERE ig.co_id = :co_id
          AND ig.item_type_id = :item_type_id
          AND ig.parent_grp_id IS NULL
          AND (ig.item_grp_name LIKE :search OR ig.item_grp_code LIKE :search)
        ORDER BY ig.item_grp_id DESC
    """)


@router.get("/get_yarn_type_table")
def get_yarn_type_table(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    search: str = None,
    page: int = 1,
    limit: int = 10,
):
    """
    Get paginated list of yarn types for the current company.
    Yarn types are stored as item groups with item_type_id=4.
    """
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")

        # Prepare search parameter for LIKE if provided
        search_param = f"%{search}%" if search else None

        # Choose query based on search
        if search_param:
            query = get_yarn_type_list_with_search_query()
            params = {"co_id": int(co_id), "item_type_id": YARN_ITEM_TYPE_ID, "search": search_param}
        else:
            query = get_yarn_type_list_query()
            params = {"co_id": int(co_id), "item_type_id": YARN_ITEM_TYPE_ID}

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


@router.get("/get_yarn_type_by_id/{yarn_type_id}")
def get_yarn_type_by_id(
    yarn_type_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Get a single yarn type record by ID.
    """
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")

        query = text("""
            SELECT 
                ig.item_grp_id,
                ig.item_grp_name,
                ig.item_grp_code,
                ig.co_id,
                ig.active,
                ig.updated_by,
                ig.updated_date_time
            FROM item_grp_mst ig
            WHERE ig.item_grp_id = :yarn_type_id
              AND ig.co_id = :co_id
              AND ig.item_type_id = :item_type_id
        """)

        result = db.execute(query, {
            "yarn_type_id": yarn_type_id,
            "co_id": int(co_id),
            "item_type_id": YARN_ITEM_TYPE_ID,
        }).fetchone()
        
        if not result:
            raise HTTPException(status_code=404, detail="Yarn type record not found")

        return {"data": dict(result._mapping)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/yarn_type_edit_setup/{yarn_type_id}")
def yarn_type_edit_setup(
    yarn_type_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Get setup data for editing a yarn type record.
    Returns the existing yarn type details.
    """
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")

        # Get the existing yarn type record
        query = text("""
            SELECT 
                ig.item_grp_id,
                ig.item_grp_name,
                ig.item_grp_code,
                ig.co_id,
                ig.active,
                ig.updated_by,
                ig.updated_date_time
            FROM item_grp_mst ig
            WHERE ig.item_grp_id = :yarn_type_id
              AND ig.co_id = :co_id
              AND ig.item_type_id = :item_type_id
        """)

        result = db.execute(query, {
            "yarn_type_id": yarn_type_id,
            "co_id": int(co_id),
            "item_type_id": YARN_ITEM_TYPE_ID,
        }).fetchone()
        
        if not result:
            raise HTTPException(status_code=404, detail="Yarn type record not found")

        return {
            "yarn_type_details": dict(result._mapping)
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/yarn_type_create")
def yarn_type_create(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Create a new yarn type record in item_grp_mst with item_type_id=4.
    Requires both item_grp_name and item_grp_code.
    Validates uniqueness of item_grp_code per co_id (across all item types).
    """
    try:
        body = parse_json_body(request)
        co_id = body.get("co_id") or request.query_params.get("co_id")
        
        if not co_id:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")

        item_grp_name = body.get("item_grp_name")
        if not item_grp_name:
            raise HTTPException(status_code=400, detail="Yarn type name (item_grp_name) is required")

        item_grp_code = body.get("item_grp_code")
        if not item_grp_code:
            raise HTTPException(status_code=400, detail="Yarn type code (item_grp_code) is required")

        # Check for duplicate name within yarn types (item_type_id=4) for this company
        check_name_query = text("""
            SELECT COUNT(*) as cnt FROM item_grp_mst 
            WHERE co_id = :co_id 
              AND item_type_id = :item_type_id
              AND item_grp_name = :item_grp_name
        """)
        check_name_result = db.execute(check_name_query, {
            "co_id": int(co_id),
            "item_type_id": YARN_ITEM_TYPE_ID,
            "item_grp_name": item_grp_name,
        }).fetchone()
        
        if check_name_result and check_name_result.cnt > 0:
            raise HTTPException(status_code=400, detail="Yarn type with this name already exists")

        # Check for duplicate code across all item groups for this company
        check_code_query = text("""
            SELECT COUNT(*) as cnt FROM item_grp_mst 
            WHERE co_id = :co_id 
              AND item_grp_code = :item_grp_code
        """)
        check_code_result = db.execute(check_code_query, {
            "co_id": int(co_id),
            "item_grp_code": item_grp_code,
        }).fetchone()
        
        if check_code_result and check_code_result.cnt > 0:
            raise HTTPException(status_code=400, detail="Item group code already exists for this company")

        # Get user ID from token
        user_id = token_data.get("user_id") if token_data else None

        # Create new yarn type as item group row
        new_yarn_type = ItemGrpMst(
            item_grp_name=item_grp_name,
            item_grp_code=item_grp_code,
            co_id=int(co_id),
            item_type_id=YARN_ITEM_TYPE_ID,
            parent_grp_id=None,
            active="1",
            updated_by=user_id,
            updated_date_time=now_ist(),
        )
        db.add(new_yarn_type)
        db.commit()
        db.refresh(new_yarn_type)

        return {
            "message": "Yarn type created successfully",
            "item_grp_id": new_yarn_type.item_grp_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/yarn_type_edit/{yarn_type_id}")
def yarn_type_edit(
    yarn_type_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Update an existing yarn type record in item_grp_mst.
    """
    try:
        body = parse_json_body(request)
        co_id = body.get("co_id") or request.query_params.get("co_id")
        
        if not co_id:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")

        item_grp_name = body.get("item_grp_name")
        if not item_grp_name:
            raise HTTPException(status_code=400, detail="Yarn type name (item_grp_name) is required")

        item_grp_code = body.get("item_grp_code")
        if not item_grp_code:
            raise HTTPException(status_code=400, detail="Yarn type code (item_grp_code) is required")

        # Check record exists and is a yarn type
        existing = db.query(ItemGrpMst).filter(
            ItemGrpMst.item_grp_id == yarn_type_id,
            ItemGrpMst.co_id == int(co_id),
            ItemGrpMst.item_type_id == YARN_ITEM_TYPE_ID,
        ).first()

        if not existing:
            raise HTTPException(status_code=404, detail="Yarn type record not found")

        # Check for duplicate name (excluding current record)
        check_name_query = text("""
            SELECT COUNT(*) as cnt FROM item_grp_mst 
            WHERE co_id = :co_id
              AND item_type_id = :item_type_id
              AND item_grp_name = :item_grp_name
              AND item_grp_id != :yarn_type_id
        """)
        check_name_result = db.execute(check_name_query, {
            "co_id": int(co_id),
            "item_type_id": YARN_ITEM_TYPE_ID,
            "item_grp_name": item_grp_name,
            "yarn_type_id": yarn_type_id,
        }).fetchone()
        
        if check_name_result and check_name_result.cnt > 0:
            raise HTTPException(status_code=400, detail="Yarn type with this name already exists")

        # Check for duplicate code (excluding current record)
        check_code_query = text("""
            SELECT COUNT(*) as cnt FROM item_grp_mst 
            WHERE co_id = :co_id
              AND item_grp_code = :item_grp_code
              AND item_grp_id != :yarn_type_id
        """)
        check_code_result = db.execute(check_code_query, {
            "co_id": int(co_id),
            "item_grp_code": item_grp_code,
            "yarn_type_id": yarn_type_id,
        }).fetchone()
        
        if check_code_result and check_code_result.cnt > 0:
            raise HTTPException(status_code=400, detail="Item group code already exists for this company")

        # Get user ID from token
        user_id = token_data.get("user_id") if token_data else None

        # Update the record
        existing.item_grp_name = item_grp_name
        existing.item_grp_code = item_grp_code
        existing.updated_by = user_id
        existing.updated_date_time = now_ist()
        
        db.commit()

        return {
            "message": "Yarn type updated successfully",
            "item_grp_id": yarn_type_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
