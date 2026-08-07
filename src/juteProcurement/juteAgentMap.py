"""
Jute Agent Mapping API endpoints.

This module provides endpoints for managing jute agent to party branch mappings.
Agent branches are company branches (from branch_mst), and party branches are
party branch locations (from party_branch_mst).

The mapping allows linking an agent (company branch) to a party branch for
jute procurement operations.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session
from sqlalchemy.sql import text
from datetime import datetime
from pydantic import BaseModel
from typing import Optional

from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.models.jute import JuteAgentMap

router = APIRouter()


# =============================================================================
# PYDANTIC MODELS
# =============================================================================

class JuteAgentMapCreate(BaseModel):
    """Request model for creating a jute agent mapping."""
    agent_branch_id: int
    party_branch_id: int


# =============================================================================
# QUERY FUNCTIONS
# =============================================================================

def get_agent_map_table_query():
    """
    Query to get jute agent map list with branch and party details.
    Displays: agent_branch (co_name - branch_name) and party_branch (party_name - address).
    """
    sql = """
        SELECT 
            jam.agent_map_id,
            jam.agent_branch_id,
            jam.party_branch_id,
            jam.co_id,
            -- Agent branch display: co_name - branch_name
            CONCAT(COALESCE(cm.co_name, ''), ' - ', COALESCE(bm.branch_name, '')) AS agent_branch_display,
            bm.branch_name AS agent_branch_name,
            cm.co_name AS agent_company_name,
            -- Party branch display: party_name - address
            CONCAT(COALESCE(pm.supp_name, ''), ' - ', COALESCE(pbm.address, '')) AS party_branch_display,
            pm.supp_name AS party_name,
            pm.supp_code AS party_code,
            pbm.address AS party_branch_address,
            pbm.gst_no AS party_branch_gst
        FROM jute_agent_map jam
        LEFT JOIN branch_mst bm ON bm.branch_id = jam.agent_branch_id
        LEFT JOIN co_mst cm ON cm.co_id = bm.co_id
        LEFT JOIN party_branch_mst pbm ON pbm.party_mst_branch_id = jam.party_branch_id
        LEFT JOIN party_mst pm ON pm.party_id = pbm.party_id
        WHERE jam.co_id = :co_id
            AND (:search IS NULL 
                OR bm.branch_name LIKE :search 
                OR cm.co_name LIKE :search
                OR pm.supp_name LIKE :search
                OR pbm.address LIKE :search)
        ORDER BY jam.agent_map_id DESC
        LIMIT :limit OFFSET :offset
    """
    return text(sql)


def get_agent_map_count_query():
    """Query to get total count of agent mappings for pagination."""
    sql = """
        SELECT COUNT(*) AS total
        FROM jute_agent_map jam
        LEFT JOIN branch_mst bm ON bm.branch_id = jam.agent_branch_id
        LEFT JOIN co_mst cm ON cm.co_id = bm.co_id
        LEFT JOIN party_branch_mst pbm ON pbm.party_mst_branch_id = jam.party_branch_id
        LEFT JOIN party_mst pm ON pm.party_id = pbm.party_id
        WHERE jam.co_id = :co_id
            AND (:search IS NULL 
                OR bm.branch_name LIKE :search 
                OR cm.co_name LIKE :search
                OR pm.supp_name LIKE :search
                OR pbm.address LIKE :search)
    """
    return text(sql)


def get_all_branches_with_company_query():
    """
    Query to get all branches with their company names for agent dropdown.
    Returns: branch_id, branch_name, co_id, co_name, display (co_name - branch_name)
    """
    sql = """
        SELECT 
            bm.branch_id,
            bm.branch_name,
            bm.co_id,
            cm.co_name,
            CONCAT(COALESCE(cm.co_name, ''), ' - ', COALESCE(bm.branch_name, '')) AS display
        FROM branch_mst bm
        LEFT JOIN co_mst cm ON cm.co_id = bm.co_id
        WHERE bm.active = 1
        ORDER BY cm.co_name, bm.branch_name
    """
    return text(sql)


def get_party_branches_with_party_query(co_id: int):
    """
    Query to get all party branches with their party names for party dropdown.
    Filters parties by the current co_id.
    Only includes parties with party_type_id containing "3" (jute supplying parties).
    Returns: party_mst_branch_id, party_id, party_name, address, display (party_name - address)
    """
    sql = """
        SELECT 
            pbm.party_mst_branch_id,
            pbm.party_id,
            pbm.address,
            pbm.gst_no,
            pm.supp_name AS party_name,
            pm.supp_code AS party_code,
            CONCAT(COALESCE(pm.supp_name, ''), ' - ', COALESCE(pbm.address, '')) AS display
        FROM party_branch_mst pbm
        LEFT JOIN party_mst pm ON pm.party_id = pbm.party_id
        WHERE pm.co_id = :co_id
            AND pbm.active = 1
            AND pm.active = 1
            AND FIND_IN_SET("3", REPLACE(REPLACE(pm.party_type_id, "{", ""), "}", "")) > 0
        ORDER BY pm.supp_name, pbm.address
    """
    return text(sql)


def check_duplicate_mapping_query():
    """Check if a mapping already exists for the given agent_branch_id and party_branch_id."""
    sql = """
        SELECT agent_map_id 
        FROM jute_agent_map 
        WHERE co_id = :co_id 
            AND agent_branch_id = :agent_branch_id 
            AND party_branch_id = :party_branch_id
        LIMIT 1
    """
    return text(sql)


# =============================================================================
# API ENDPOINTS
# =============================================================================

@router.get("/get_jute_agent_map_table")
def get_jute_agent_map_table(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    page: int = 1,
    limit: int = 10,
    search: str = None
):
    """
    Get paginated list of jute agent mappings.
    
    Returns agent branch (with company name) and party branch (with party name) info.
    Filtered by the current company (co_id).
    """
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")

        offset = (page - 1) * limit
        search_param = f"%{search}%" if search else None

        # Get data
        query = get_agent_map_table_query()
        result = db.execute(
            query,
            {"co_id": int(co_id), "search": search_param, "limit": limit, "offset": offset}
        ).fetchall()
        data = [dict(row._mapping) for row in result]

        # Get total count
        count_query = get_agent_map_count_query()
        count_result = db.execute(
            count_query,
            {"co_id": int(co_id), "search": search_param}
        ).fetchone()
        total = count_result._mapping.get("total", 0) if count_result else 0

        return {"data": data, "total": total, "page": page, "limit": limit}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/jute_agent_map_create_setup")
def jute_agent_map_create_setup(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh)
):
    """
    Get setup data for creating a jute agent mapping.
    
    Returns:
    - branches: All branches with their company names (for agent dropdown)
    """
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")

        # Get all branches with company names
        branches_query = get_all_branches_with_company_query()
        branches_result = db.execute(branches_query).fetchall()
        branches = [dict(row._mapping) for row in branches_result]

        return {"branches": branches}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_party_branches_for_agent")
def get_party_branches_for_agent(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh)
):
    """
    Get available party branches for mapping to an agent.
    
    Party branches are filtered by the current co_id.
    Returns party branches with their party names.
    """
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")

        # Get party branches filtered by co_id
        party_branches_query = get_party_branches_with_party_query(int(co_id))
        party_branches_result = db.execute(
            party_branches_query,
            {"co_id": int(co_id)}
        ).fetchall()
        party_branches = [dict(row._mapping) for row in party_branches_result]

        return {"party_branches": party_branches}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/jute_agent_map_create")
def jute_agent_map_create(
    request: Request,
    response: Response,
    payload: JuteAgentMapCreate,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh)
):
    """
    Create a new jute agent to party branch mapping.
    
    Validates:
    - agent_branch_id exists in branch_mst
    - party_branch_id exists in party_branch_mst
    - No duplicate mapping exists
    """
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")

        # Check for duplicate mapping
        dup_query = check_duplicate_mapping_query()
        dup_result = db.execute(
            dup_query,
            {
                "co_id": int(co_id),
                "agent_branch_id": payload.agent_branch_id,
                "party_branch_id": payload.party_branch_id
            }
        ).fetchone()

        if dup_result:
            raise HTTPException(
                status_code=400, 
                detail="A mapping already exists for this agent branch and party branch combination"
            )

        # Create new mapping
        new_mapping = JuteAgentMap(
            co_id=int(co_id),
            agent_branch_id=payload.agent_branch_id,
            party_branch_id=payload.party_branch_id
        )
        db.add(new_mapping)
        db.commit()
        db.refresh(new_mapping)

        return {
            "message": "Agent mapping created successfully",
            "agent_map_id": new_mapping.agent_map_id
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/jute_agent_map_delete/{agent_map_id}")
def jute_agent_map_delete(
    agent_map_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh)
):
    """
    Delete a jute agent mapping by ID.
    
    Validates that the mapping belongs to the current company (co_id).
    """
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")

        # Find the mapping
        mapping = db.query(JuteAgentMap).filter(
            JuteAgentMap.agent_map_id == agent_map_id,
            JuteAgentMap.co_id == int(co_id)
        ).first()

        if not mapping:
            raise HTTPException(status_code=404, detail="Agent mapping not found")

        db.delete(mapping)
        db.commit()

        return {"message": "Agent mapping deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_jute_agent_map_by_id/{agent_map_id}")
def get_jute_agent_map_by_id(
    agent_map_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh)
):
    """
    Get a single jute agent mapping by ID with full details.
    """
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")

        sql = """
            SELECT 
                jam.agent_map_id,
                jam.agent_branch_id,
                jam.party_branch_id,
                jam.co_id,
                CONCAT(COALESCE(cm.co_name, ''), ' - ', COALESCE(bm.branch_name, '')) AS agent_branch_display,
                bm.branch_name AS agent_branch_name,
                cm.co_name AS agent_company_name,
                CONCAT(COALESCE(pm.supp_name, ''), ' - ', COALESCE(pbm.address, '')) AS party_branch_display,
                pm.supp_name AS party_name,
                pm.supp_code AS party_code,
                pbm.address AS party_branch_address,
                pbm.gst_no AS party_branch_gst
            FROM jute_agent_map jam
            LEFT JOIN branch_mst bm ON bm.branch_id = jam.agent_branch_id
            LEFT JOIN co_mst cm ON cm.co_id = bm.co_id
            LEFT JOIN party_branch_mst pbm ON pbm.party_mst_branch_id = jam.party_branch_id
            LEFT JOIN party_mst pm ON pm.party_id = pbm.party_id
            WHERE jam.agent_map_id = :agent_map_id
                AND jam.co_id = :co_id
        """
        result = db.execute(text(sql), {"agent_map_id": agent_map_id, "co_id": int(co_id)}).fetchone()

        if not result:
            raise HTTPException(status_code=404, detail="Agent mapping not found")

        return dict(result._mapping)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
