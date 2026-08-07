"""
Jute Supplier Party Map API endpoints.
Provides CRUD operations for mapping jute suppliers to party master.
Mappings are company-specific (filtered by co_id).
"""

from fastapi import Depends, Request, HTTPException, APIRouter, Response
from sqlalchemy.sql import text
from sqlalchemy.orm import Session
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.models.jute import JuteSuppPartyMap
from datetime import datetime
from src.common.utils import now_ist
from src.common.utils import parse_json_body

router = APIRouter()


def get_jute_supplier_map_list_query():
    """
    Get all jute supplier to party mappings for a company with joined names.
    """
    return text("""
        SELECT 
            jspm.map_id,
            jspm.co_id,
            jspm.jute_supplier_id,
            js.supplier_name,
            jspm.party_id,
            pm.supp_name AS party_name,
            pm.supp_code AS party_code,
            jspm.updated_by,
            jspm.updated_date_time
        FROM jute_supp_party_map jspm
        LEFT JOIN jute_supplier_mst js ON js.supplier_id = jspm.jute_supplier_id
        LEFT JOIN party_mst pm ON pm.party_id = jspm.party_id
        WHERE jspm.co_id = :co_id
        ORDER BY js.supplier_name ASC, pm.supp_name ASC
    """)


def get_jute_supplier_map_list_with_search_query():
    """
    Get all jute supplier to party mappings for a company with search filter.
    """
    return text("""
        SELECT 
            jspm.map_id,
            jspm.co_id,
            jspm.jute_supplier_id,
            js.supplier_name,
            jspm.party_id,
            pm.supp_name AS party_name,
            pm.supp_code AS party_code,
            jspm.updated_by,
            jspm.updated_date_time
        FROM jute_supp_party_map jspm
        LEFT JOIN jute_supplier_mst js ON js.supplier_id = jspm.jute_supplier_id
        LEFT JOIN party_mst pm ON pm.party_id = jspm.party_id
        WHERE jspm.co_id = :co_id
          AND (
              js.supplier_name LIKE :search
              OR pm.supp_name LIKE :search
              OR pm.supp_code LIKE :search
          )
        ORDER BY js.supplier_name ASC, pm.supp_name ASC
    """)


@router.get("/get_jute_supplier_map_table")
def get_jute_supplier_map_table(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    search: str = None,
    page: int = 1,
    limit: int = 10,
):
    """
    Get paginated list of jute supplier to party mappings for the current company.
    Joins with jute_supplier_mst and party_mst to get names.
    """
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")

        # Prepare search parameter for LIKE if provided
        search_param = f"%{search}%" if search else None

        # Choose query based on search
        if search_param:
            query = get_jute_supplier_map_list_with_search_query()
            params = {"co_id": int(co_id), "search": search_param}
        else:
            query = get_jute_supplier_map_list_query()
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


@router.get("/get_jute_supplier_map_by_id/{map_id}")
def get_jute_supplier_map_by_id(
    map_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Get a single jute supplier map record by ID.
    """
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")

        query = text("""
            SELECT 
                jspm.map_id,
                jspm.co_id,
                jspm.jute_supplier_id,
                js.supplier_name,
                jspm.party_id,
                pm.supp_name AS party_name,
                pm.supp_code AS party_code,
                jspm.updated_by,
                jspm.updated_date_time
            FROM jute_supp_party_map jspm
            LEFT JOIN jute_supplier_mst js ON js.supplier_id = jspm.jute_supplier_id
            LEFT JOIN party_mst pm ON pm.party_id = jspm.party_id
            WHERE jspm.map_id = :map_id
              AND jspm.co_id = :co_id
        """)

        result = db.execute(query, {"map_id": map_id, "co_id": int(co_id)}).fetchone()
        
        if not result:
            raise HTTPException(status_code=404, detail="Jute supplier map record not found")

        return {"data": dict(result._mapping)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/jute_supplier_map_create_setup")
def jute_supplier_map_create_setup(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Get setup data for creating a new jute supplier map record.
    Returns list of all jute suppliers (global).
    """
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")

        # Get all jute suppliers (global - not company-specific)
        suppliers_query = text("""
            SELECT 
                supplier_id,
                supplier_name
            FROM jute_supplier_mst
            ORDER BY supplier_name ASC
        """)
        suppliers_result = db.execute(suppliers_query).fetchall()
        suppliers = [dict(row._mapping) for row in suppliers_result]

        return {
            "suppliers": suppliers,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_available_parties_for_supplier/{supplier_id}")
def get_available_parties_for_supplier(
    supplier_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Get parties available for mapping to a specific supplier.
    Returns parties for the co_id that are NOT already mapped to this supplier.
    party_type_id contains "3" means it's a jute supplying party type.
    """
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")

        # Get parties for this co_id that are:
        # 1. Active
        # 2. Jute supplier type (party_type_id contains "3")
        # 3. NOT already mapped to this jute supplier
        parties_query = text("""
            SELECT 
                pm.party_id,
                pm.supp_name,
                pm.supp_code
            FROM party_mst pm
            WHERE pm.co_id = :co_id
              AND pm.active = 1
              AND FIND_IN_SET("3", REPLACE(REPLACE(pm.party_type_id, "{", ""), "}", "")) > 0
              AND pm.party_id NOT IN (
                  SELECT jspm.party_id 
                  FROM jute_supp_party_map jspm 
                  WHERE jspm.jute_supplier_id = :supplier_id
                    AND jspm.co_id = :co_id
                    AND jspm.party_id IS NOT NULL
              )
            ORDER BY pm.supp_name ASC
        """)
        
        parties_result = db.execute(parties_query, {
            "co_id": int(co_id),
            "supplier_id": supplier_id
        }).fetchall()
        parties = [dict(row._mapping) for row in parties_result]

        return {
            "parties": parties,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/jute_supplier_map_create")
def jute_supplier_map_create(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Create a new jute supplier to party mapping record.
    """
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")

        body = parse_json_body(request)
        jute_supplier_id = body.get("jute_supplier_id")
        party_id = body.get("party_id")

        if not jute_supplier_id:
            raise HTTPException(status_code=400, detail="Jute Supplier is required")
        if not party_id:
            raise HTTPException(status_code=400, detail="Party is required")

        # Check if mapping already exists for this supplier and party in this company
        duplicate_query = text("""
            SELECT map_id FROM jute_supp_party_map 
            WHERE jute_supplier_id = :jute_supplier_id
              AND party_id = :party_id
              AND co_id = :co_id
        """)
        existing = db.execute(duplicate_query, {
            "jute_supplier_id": int(jute_supplier_id),
            "party_id": int(party_id),
            "co_id": int(co_id)
        }).fetchone()
        
        if existing:
            raise HTTPException(
                status_code=400, 
                detail="This party is already mapped to the selected supplier"
            )

        # Get user ID from token
        user_id = token_data.get("user_id") if isinstance(token_data, dict) else None

        # Insert new mapping
        insert_query = text("""
            INSERT INTO jute_supp_party_map (co_id, jute_supplier_id, party_id, updated_by, updated_date_time)
            VALUES (:co_id, :jute_supplier_id, :party_id, :updated_by, :updated_date_time)
        """)
        
        db.execute(insert_query, {
            "co_id": int(co_id),
            "jute_supplier_id": int(jute_supplier_id),
            "party_id": int(party_id),
            "updated_by": user_id,
            "updated_date_time": now_ist(),
        })
        db.commit()

        return {"message": "Jute supplier party mapping created successfully"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/jute_supplier_map_delete/{map_id}")
def jute_supplier_map_delete(
    map_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Delete a jute supplier to party mapping record.
    """
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")

        # Check if mapping exists
        exists_query = text("""
            SELECT map_id FROM jute_supp_party_map 
            WHERE map_id = :map_id AND co_id = :co_id
        """)
        existing = db.execute(exists_query, {"map_id": map_id, "co_id": int(co_id)}).fetchone()
        
        if not existing:
            raise HTTPException(status_code=404, detail="Jute supplier map record not found")

        # Delete the mapping
        delete_query = text("""
            DELETE FROM jute_supp_party_map 
            WHERE map_id = :map_id AND co_id = :co_id
        """)
        
        db.execute(delete_query, {"map_id": map_id, "co_id": int(co_id)})
        db.commit()

        return {"message": "Jute supplier party mapping deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
