"""
Batch Plan Master API endpoints.
Provides CRUD operations for jute batch plan master data.

Schema (jute_batch_plan):
- batch_plan_id: bigint (PK, auto)
- branch_id: int (nullable)
- plan_name: str(255) (nullable)
- updated_by: bigint
- updated_date_time: datetime

Schema (jute_batch_plan_li):
- batch_plan_li_id: bigint (PK, auto)
- batch_plan_id: bigint (FK to jute_batch_plan)
- jute_quality_id: int (FK to item_mst — the item/quality)
- percentage: double (nullable)
- updated_by: bigint
- updated_date_time: datetime
"""

from fastapi import Depends, Request, HTTPException, APIRouter, Response
from sqlalchemy.sql import text
from sqlalchemy.orm import Session
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.models.jute import JuteBatchPlan, JuteBatchPlanLi
from datetime import datetime
from src.common.utils import now_ist
from pydantic import BaseModel
from typing import Optional, List

router = APIRouter()


# =============================================================================
# PYDANTIC MODELS
# =============================================================================

class BatchPlanLineItem(BaseModel):
    """Line item for batch plan - item (was quality) and percentage."""
    item_id: int
    percentage: float
    item_grp_id: Optional[int] = None  # For reference, not stored in line item


class BatchPlanCreate(BaseModel):
    """Request body for creating/updating a batch plan."""
    plan_name: str
    branch_id: Optional[int] = None
    line_items: List[BatchPlanLineItem]


# =============================================================================
# QUERY FUNCTIONS
# =============================================================================

def get_batch_plan_list_query():
    """
    Get all batch plans for a branch with line item count and branch name.
    """
    return text("""
        SELECT 
            bp.batch_plan_id,
            bp.plan_name,
            bp.branch_id,
            bm.branch_name,
            bp.updated_by,
            bp.updated_date_time,
            COUNT(bpli.batch_plan_li_id) AS line_item_count
        FROM jute_batch_plan bp
        LEFT JOIN jute_batch_plan_li bpli ON bp.batch_plan_id = bpli.batch_plan_id
        LEFT JOIN branch_mst bm ON bp.branch_id = bm.branch_id
        WHERE bp.branch_id = :branch_id
        GROUP BY bp.batch_plan_id, bp.plan_name, bp.branch_id, bm.branch_name, bp.updated_by, bp.updated_date_time
        ORDER BY bp.batch_plan_id DESC
    """)


def get_batch_plan_list_with_search_query():
    """
    Get all batch plans with search filter and branch name.
    """
    return text("""
        SELECT 
            bp.batch_plan_id,
            bp.plan_name,
            bp.branch_id,
            bm.branch_name,
            bp.updated_by,
            bp.updated_date_time,
            COUNT(bpli.batch_plan_li_id) AS line_item_count
        FROM jute_batch_plan bp
        LEFT JOIN jute_batch_plan_li bpli ON bp.batch_plan_id = bpli.batch_plan_id
        LEFT JOIN branch_mst bm ON bp.branch_id = bm.branch_id
        WHERE bp.branch_id = :branch_id
          AND bp.plan_name LIKE :search
        GROUP BY bp.batch_plan_id, bp.plan_name, bp.branch_id, bm.branch_name, bp.updated_by, bp.updated_date_time
        ORDER BY bp.batch_plan_id DESC
    """)


def get_batch_plan_detail_query():
    """
    Get batch plan with line items detail.
    """
    return text("""
        SELECT 
            bp.batch_plan_id,
            bp.plan_name,
            bp.branch_id,
            bp.updated_by,
            bp.updated_date_time
        FROM jute_batch_plan bp
        WHERE bp.batch_plan_id = :batch_plan_id
          AND bp.branch_id = :branch_id
    """)


def get_batch_plan_line_items_query():
    """
    Get line items for a batch plan with item and group names.
    Uses recursive CTE to build full group path.
    """
    return text("""
        WITH RECURSIVE group_path AS (
            SELECT
                igm.item_grp_id AS target_id,
                igm.item_grp_id,
                igm.item_grp_name,
                igm.parent_grp_id,
                CAST(igm.item_grp_name AS CHAR(500)) AS item_grp_name_path
            FROM item_grp_mst igm

            UNION ALL

            SELECT
                child.target_id,
                p.item_grp_id,
                p.item_grp_name,
                p.parent_grp_id,
                CAST(CONCAT(p.item_grp_name, ' > ', child.item_grp_name_path) AS CHAR(500))
            FROM item_grp_mst p
            JOIN group_path child ON child.parent_grp_id = p.item_grp_id
        ),
        full_paths AS (
            SELECT target_id, item_grp_name_path
            FROM group_path
            WHERE parent_grp_id IS NULL
        )
        SELECT 
            bpli.batch_plan_li_id,
            bpli.batch_plan_id,
            bpli.jute_quality_id AS item_id,
            bpli.percentage,
            im.item_name AS quality_name,
            im.item_grp_id,
            COALESCE(fp.item_grp_name_path, ig.item_grp_name) AS jute_group_name
        FROM jute_batch_plan_li bpli
        LEFT JOIN item_mst im ON bpli.jute_quality_id = im.item_id
        LEFT JOIN item_grp_mst ig ON im.item_grp_id = ig.item_grp_id
        LEFT JOIN full_paths fp ON fp.target_id = ig.item_grp_id
        WHERE bpli.batch_plan_id = :batch_plan_id
        ORDER BY bpli.batch_plan_li_id
    """)


def get_jute_items_query():
    """
    Get jute subgroups for a company with recursive group path names.
    Returns subgroups from item_grp_mst where parent has item_type_id = 2.
    """
    return text("""
        WITH RECURSIVE group_path AS (
            SELECT
                ig.item_grp_id AS target_id,
                ig.item_grp_id,
                ig.item_grp_code,
                ig.item_grp_name,
                ig.parent_grp_id,
                CAST(ig.item_grp_code AS CHAR(500)) AS item_grp_code_path,
                CAST(ig.item_grp_name AS CHAR(500)) AS item_grp_name_path
            FROM item_grp_mst ig
            INNER JOIN item_grp_mst parent ON parent.item_grp_id = ig.parent_grp_id
            WHERE parent.item_type_id = 2
              AND ig.co_id = :co_id
              AND (ig.active = '1' OR ig.active IS NULL)

            UNION ALL

            SELECT
                child.target_id,
                p.item_grp_id,
                p.item_grp_code,
                p.item_grp_name,
                p.parent_grp_id,
                CAST(CONCAT(p.item_grp_code, ' > ', child.item_grp_code_path) AS CHAR(500)),
                CAST(CONCAT(p.item_grp_name, ' > ', child.item_grp_name_path) AS CHAR(500))
            FROM item_grp_mst p
            JOIN group_path child ON child.parent_grp_id = p.item_grp_id
        )
        SELECT
            gp.target_id AS item_grp_id,
            gp.item_grp_code_path AS item_grp_code,
            gp.item_grp_name_path AS item_grp_name
        FROM group_path gp
        WHERE gp.parent_grp_id IS NULL
        ORDER BY gp.item_grp_name_path
    """)


def get_quality_for_item_query():
    """
    Get items (formerly qualities) for a specific jute subgroup.
    Items are now in item_mst filtered by item_grp_id.
    """
    return text("""
        SELECT 
            im.item_id,
            im.item_name AS jute_quality,
            im.item_grp_id
        FROM item_mst im
        WHERE im.item_grp_id = :item_grp_id
          AND (im.active = 1 OR im.active IS NULL)
        ORDER BY im.item_name
    """)


def check_duplicate_plan_name_query():
    """
    Check if a batch plan with the same name exists for the branch.
    """
    return text("""
        SELECT COUNT(*) as cnt
        FROM jute_batch_plan
        WHERE plan_name = :plan_name
          AND branch_id = :branch_id
          AND (:batch_plan_id IS NULL OR batch_plan_id != :batch_plan_id)
    """)


# =============================================================================
# API ENDPOINTS
# =============================================================================

@router.get("/get_batch_plan_table")
def get_batch_plan_table(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    search: str = None,
    page: int = 1,
    limit: int = 10,
):
    """
    Get paginated list of batch plans for the current branch.
    """
    try:
        branch_id = request.query_params.get("branch_id")
        if not branch_id:
            raise HTTPException(status_code=400, detail="Branch ID (branch_id) is required")

        # Prepare search parameter for LIKE if provided
        search_param = f"%{search}%" if search else None

        # Choose query based on search
        if search_param:
            query = get_batch_plan_list_with_search_query()
            params = {"branch_id": int(branch_id), "search": search_param}
        else:
            query = get_batch_plan_list_query()
            params = {"branch_id": int(branch_id)}

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


@router.get("/get_batch_plan_by_id/{batch_plan_id}")
def get_batch_plan_by_id(
    batch_plan_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Get a single batch plan with its line items.
    """
    try:
        branch_id = request.query_params.get("branch_id")
        if not branch_id:
            raise HTTPException(status_code=400, detail="Branch ID (branch_id) is required")

        # Get batch plan header
        query = get_batch_plan_detail_query()
        result = db.execute(query, {
            "batch_plan_id": batch_plan_id,
            "branch_id": int(branch_id)
        }).fetchone()
        
        if not result:
            raise HTTPException(status_code=404, detail="Batch plan not found")

        batch_plan = dict(result._mapping)

        # Get line items
        line_items_query = get_batch_plan_line_items_query()
        line_items_result = db.execute(line_items_query, {"batch_plan_id": batch_plan_id}).fetchall()
        line_items = [dict(row._mapping) for row in line_items_result]

        batch_plan["line_items"] = line_items

        return {"data": batch_plan}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/batch_plan_create_setup")
def batch_plan_create_setup(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Get setup data for creating a new batch plan.
    Returns list of jute items (item_type = 2).
    """
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")

        # Get jute items (item_type = 2) for this company
        items_query = get_jute_items_query()
        items_result = db.execute(items_query, {"co_id": int(co_id)}).fetchall()
        items = [dict(row._mapping) for row in items_result]

        return {
            "items": items,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/batch_plan_edit_setup/{batch_plan_id}")
def batch_plan_edit_setup(
    batch_plan_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Get setup data for editing a batch plan.
    Returns jute items and existing batch plan details.
    """
    try:
        co_id = request.query_params.get("co_id")
        branch_id = request.query_params.get("branch_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")
        if not branch_id:
            raise HTTPException(status_code=400, detail="Branch ID (branch_id) is required")

        # Get jute items (item_type = 2) for this company
        items_query = get_jute_items_query()
        items_result = db.execute(items_query, {"co_id": int(co_id)}).fetchall()
        items = [dict(row._mapping) for row in items_result]

        # Get batch plan details
        query = get_batch_plan_detail_query()
        result = db.execute(query, {
            "batch_plan_id": batch_plan_id,
            "branch_id": int(branch_id)
        }).fetchone()
        
        if not result:
            raise HTTPException(status_code=404, detail="Batch plan not found")

        batch_plan = dict(result._mapping)

        # Get line items
        line_items_query = get_batch_plan_line_items_query()
        line_items_result = db.execute(line_items_query, {"batch_plan_id": batch_plan_id}).fetchall()
        line_items = [dict(row._mapping) for row in line_items_result]

        return {
            "items": items,
            "batch_plan_details": batch_plan,
            "line_items": line_items,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_qualities_for_item/{item_grp_id}")
def get_qualities_for_item(
    item_grp_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Get items (formerly qualities) for a specific jute subgroup.
    Called when user selects a group in the line item grid.
    """
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")

        query = get_quality_for_item_query()
        result = db.execute(query, {"item_grp_id": item_grp_id}).fetchall()
        qualities = [dict(row._mapping) for row in result]

        return {"qualities": qualities}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/batch_plan_create")
def batch_plan_create(
    payload: BatchPlanCreate,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Create a new batch plan with line items.
    """
    try:
        branch_id = request.query_params.get("branch_id")
        if not branch_id:
            raise HTTPException(status_code=400, detail="Branch ID (branch_id) is required")

        # Validate
        if not payload.plan_name or not payload.plan_name.strip():
            raise HTTPException(status_code=400, detail="Plan name is required")
        
        if not payload.line_items or len(payload.line_items) == 0:
            raise HTTPException(status_code=400, detail="At least one line item is required")

        # Check for duplicate plan name
        duplicate_check = db.execute(check_duplicate_plan_name_query(), {
            "plan_name": payload.plan_name.strip(),
            "branch_id": int(branch_id),
            "batch_plan_id": None,
        }).fetchone()
        
        if duplicate_check and duplicate_check.cnt > 0:
            raise HTTPException(status_code=400, detail=f"A batch plan with name '{payload.plan_name}' already exists")

        # Validate total percentage
        total_percentage = sum(li.percentage for li in payload.line_items)
        if abs(total_percentage - 100.0) > 0.01:
            raise HTTPException(
                status_code=400, 
                detail=f"Total percentage must equal 100%. Current total: {total_percentage:.2f}%"
            )

        # Get user ID from token
        user_id = token_data.get("user_id", 1)

        # Create batch plan header
        batch_plan = JuteBatchPlan(
            branch_id=int(branch_id),
            plan_name=payload.plan_name.strip(),
            updated_by=user_id,
            updated_date_time=now_ist(),
        )
        db.add(batch_plan)
        db.flush()  # Get the auto-generated ID

        # Create line items
        for li in payload.line_items:
            line_item = JuteBatchPlanLi(
                batch_plan_id=batch_plan.batch_plan_id,
                jute_quality_id=li.item_id,
                percentage=li.percentage,
                updated_by=user_id,
                updated_date_time=now_ist(),
            )
            db.add(line_item)

        db.commit()

        return {
            "message": "Batch plan created successfully",
            "batch_plan_id": batch_plan.batch_plan_id,
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/batch_plan_edit/{batch_plan_id}")
def batch_plan_edit(
    batch_plan_id: int,
    payload: BatchPlanCreate,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Update an existing batch plan with line items.
    """
    try:
        branch_id = request.query_params.get("branch_id")
        if not branch_id:
            raise HTTPException(status_code=400, detail="Branch ID (branch_id) is required")

        # Validate
        if not payload.plan_name or not payload.plan_name.strip():
            raise HTTPException(status_code=400, detail="Plan name is required")
        
        if not payload.line_items or len(payload.line_items) == 0:
            raise HTTPException(status_code=400, detail="At least one line item is required")

        # Check if batch plan exists
        batch_plan = db.query(JuteBatchPlan).filter(
            JuteBatchPlan.batch_plan_id == batch_plan_id,
            JuteBatchPlan.branch_id == int(branch_id),
        ).first()

        if not batch_plan:
            raise HTTPException(status_code=404, detail="Batch plan not found")

        # Check for duplicate plan name (excluding current)
        duplicate_check = db.execute(check_duplicate_plan_name_query(), {
            "plan_name": payload.plan_name.strip(),
            "branch_id": int(branch_id),
            "batch_plan_id": batch_plan_id,
        }).fetchone()
        
        if duplicate_check and duplicate_check.cnt > 0:
            raise HTTPException(status_code=400, detail=f"A batch plan with name '{payload.plan_name}' already exists")

        # Validate total percentage
        total_percentage = sum(li.percentage for li in payload.line_items)
        if abs(total_percentage - 100.0) > 0.01:
            raise HTTPException(
                status_code=400, 
                detail=f"Total percentage must equal 100%. Current total: {total_percentage:.2f}%"
            )

        # Get user ID from token
        user_id = token_data.get("user_id", 1)

        # Update batch plan header
        batch_plan.plan_name = payload.plan_name.strip()
        batch_plan.updated_by = user_id
        batch_plan.updated_date_time = now_ist()

        # Delete existing line items
        db.query(JuteBatchPlanLi).filter(
            JuteBatchPlanLi.batch_plan_id == batch_plan_id
        ).delete()

        # Create new line items
        for li in payload.line_items:
            line_item = JuteBatchPlanLi(
                batch_plan_id=batch_plan_id,
                jute_quality_id=li.item_id,
                percentage=li.percentage,
                updated_by=user_id,
                updated_date_time=now_ist(),
            )
            db.add(line_item)

        db.commit()

        return {
            "message": "Batch plan updated successfully",
            "batch_plan_id": batch_plan_id,
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
