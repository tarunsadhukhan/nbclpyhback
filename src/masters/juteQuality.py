"""
Jute Quality Master API endpoints.
Provides CRUD operations for jute quality data.

DEPRECATED: This module is deprecated. The jute quality concept has been replaced
by the item_mst hierarchy (Jute Group → Subgroup via item_grp_mst → Item via item_mst).
New code should use item_mst directly. These endpoints are retained only for backward
compatibility and should not be used in new features.
"""

from fastapi import Depends, Request, HTTPException, APIRouter, Response
from sqlalchemy.sql import text
from sqlalchemy.orm import Session
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.models.jute import JuteQualityMst
from datetime import datetime
from src.common.utils import now_ist
from src.common.utils import parse_json_body

router = APIRouter()


def get_jute_quality_list_query():
    """
    Get all jute qualities for a company with item names joined from item_mst.
    """
    return text("""
        SELECT 
            jq.jute_qlty_id,
            jq.co_id,
            jq.item_id,
            jq.jute_quality,
            jq.updated_by,
            jq.updated_date_time,
            im.item_name,
            im.item_code
        FROM jute_quality_mst jq
        LEFT JOIN item_mst im ON jq.item_id = im.item_id
        WHERE jq.co_id = :co_id
        ORDER BY jq.jute_qlty_id DESC
    """)


def get_jute_quality_list_with_search_query():
    """
    Get all jute qualities for a company with search filter.
    """
    return text("""
        SELECT 
            jq.jute_qlty_id,
            jq.co_id,
            jq.item_id,
            jq.jute_quality,
            jq.updated_by,
            jq.updated_date_time,
            im.item_name,
            im.item_code
        FROM jute_quality_mst jq
        LEFT JOIN item_mst im ON jq.item_id = im.item_id
        WHERE jq.co_id = :co_id
          AND (
              jq.jute_quality LIKE :search
              OR im.item_name LIKE :search
              OR im.item_code LIKE :search
          )
        ORDER BY jq.jute_qlty_id DESC
    """)


@router.get("/get_jute_quality_table", deprecated=True)
def get_jute_quality_table(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    search: str = None,
    page: int = 1,
    limit: int = 10,
):
    """
    Get paginated list of jute qualities for the current company.
    Joins with item_mst to get item names.
    """
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")

        # Prepare search parameter for LIKE if provided
        search_param = f"%{search}%" if search else None

        # Choose query based on search
        if search_param:
            query = get_jute_quality_list_with_search_query()
            params = {"co_id": int(co_id), "search": search_param}
        else:
            query = get_jute_quality_list_query()
            params = {"co_id": int(co_id)}

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


@router.get("/get_jute_quality_by_id/{jute_qlty_id}", deprecated=True)
def get_jute_quality_by_id(
    jute_qlty_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Get a single jute quality record by ID.
    """
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")

        query = text("""
            SELECT 
                jq.jute_qlty_id,
                jq.co_id,
                jq.item_id,
                jq.jute_quality,
                jq.updated_by,
                jq.updated_date_time,
                im.item_name,
                im.item_code
            FROM jute_quality_mst jq
            LEFT JOIN item_mst im ON jq.item_id = im.item_id
            WHERE jq.jute_qlty_id = :jute_qlty_id
              AND jq.co_id = :co_id
        """)

        result = db.execute(query, {"jute_qlty_id": jute_qlty_id, "co_id": int(co_id)}).fetchone()
        
        if not result:
            raise HTTPException(status_code=404, detail="Jute quality record not found")

        return {"data": dict(result._mapping)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/jute_quality_create_setup", deprecated=True)
def jute_quality_create_setup(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Get setup data for creating a new jute quality record.
    Returns list of items (filtered by jute category if applicable).
    """
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")

        # Query items - get all items that can be associated with jute quality
        # Join through item_grp_mst to filter by co_id and item_type_id = 2 (jute items)
        items_query = text("""
            SELECT 
                im.item_id,
                im.item_code,
                im.item_name,
                im.item_grp_id
            FROM item_mst im
            INNER JOIN item_grp_mst ig ON im.item_grp_id = ig.item_grp_id
            WHERE ig.co_id = :co_id
              AND ig.item_type_id = 2
              AND im.active = 1
            ORDER BY im.item_name
        """)
        items_result = db.execute(items_query, {"co_id": int(co_id)}).fetchall()
        items = [dict(row._mapping) for row in items_result]

        return {"items": items}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/jute_quality_edit_setup/{jute_qlty_id}", deprecated=True)
def jute_quality_edit_setup(
    jute_qlty_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Get setup data for editing an existing jute quality record.
    Returns list of items and the current jute quality details.
    """
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")

        # Get existing jute quality details
        details_query = text("""
            SELECT 
                jq.jute_qlty_id,
                jq.co_id,
                jq.item_id,
                jq.jute_quality,
                jq.updated_by,
                jq.updated_date_time,
                im.item_name,
                im.item_code
            FROM jute_quality_mst jq
            LEFT JOIN item_mst im ON jq.item_id = im.item_id
            WHERE jq.jute_qlty_id = :jute_qlty_id
              AND jq.co_id = :co_id
        """)
        details_result = db.execute(details_query, {"jute_qlty_id": jute_qlty_id, "co_id": int(co_id)}).fetchone()
        
        if not details_result:
            raise HTTPException(status_code=404, detail="Jute quality record not found")

        # Query items - join through item_grp_mst to filter by co_id and item_type_id = 2 (jute items)
        items_query = text("""
            SELECT 
                im.item_id,
                im.item_code,
                im.item_name,
                im.item_grp_id
            FROM item_mst im
            INNER JOIN item_grp_mst ig ON im.item_grp_id = ig.item_grp_id
            WHERE ig.co_id = :co_id
              AND ig.item_type_id = 2
              AND im.active = 1
            ORDER BY im.item_name
        """)
        items_result = db.execute(items_query, {"co_id": int(co_id)}).fetchall()
        items = [dict(row._mapping) for row in items_result]

        return {
            "items": items,
            "jute_quality_details": dict(details_result._mapping)
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/jute_quality_create", deprecated=True)
def jute_quality_create(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Create a new jute quality record.
    """
    try:
        payload = parse_json_body(request)
        co_id_query = request.query_params.get("co_id")
        co_id = payload.get("co_id") if payload.get("co_id") is not None else co_id_query

        if co_id is None:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")

        # Derive updated_by from token
        updated_by = None
        if token_data and token_data.get("user_id"):
            try:
                updated_by = int(token_data.get("user_id"))
            except Exception:
                updated_by = None

        # Parse inputs
        item_id = payload.get("item_id")
        if item_id is not None:
            try:
                item_id = int(item_id)
            except Exception:
                raise HTTPException(status_code=400, detail="Invalid item_id")

        jute_quality = payload.get("jute_quality")
        if not jute_quality:
            raise HTTPException(status_code=400, detail="jute_quality is required")

        # Create model instance
        jq = JuteQualityMst(
            co_id=int(co_id),
            item_id=item_id,
            jute_quality=jute_quality,
            updated_by=updated_by,
            updated_date_time=now_ist(),
        )

        db.add(jq)
        db.commit()
        db.refresh(jq)

        return {
            "message": "Jute quality created successfully",
            "jute_qlty_id": jq.jute_qlty_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/jute_quality_edit/{jute_qlty_id}", deprecated=True)
def jute_quality_edit(
    jute_qlty_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Update an existing jute quality record.
    """
    try:
        payload = parse_json_body(request)
        co_id = request.query_params.get("co_id")

        if not co_id:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")

        # Find existing record
        jq = db.query(JuteQualityMst).filter(
            JuteQualityMst.jute_qlty_id == jute_qlty_id,
            JuteQualityMst.co_id == int(co_id)
        ).first()

        if not jq:
            raise HTTPException(status_code=404, detail="Jute quality record not found")

        # Derive updated_by from token
        updated_by = None
        if token_data and token_data.get("user_id"):
            try:
                updated_by = int(token_data.get("user_id"))
            except Exception:
                updated_by = None

        # Update fields
        if "item_id" in payload:
            item_id = payload.get("item_id")
            if item_id is not None:
                try:
                    jq.item_id = int(item_id)
                except Exception:
                    raise HTTPException(status_code=400, detail="Invalid item_id")
            else:
                jq.item_id = None

        if "jute_quality" in payload:
            jute_quality = payload.get("jute_quality")
            if not jute_quality:
                raise HTTPException(status_code=400, detail="jute_quality cannot be empty")
            jq.jute_quality = jute_quality

        jq.updated_by = updated_by
        jq.updated_date_time = now_ist()

        db.commit()

        return {"message": "Jute quality updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
