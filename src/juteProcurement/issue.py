"""
Jute Issue API endpoints.
Provides endpoints for viewing and managing jute issue records.
Jute issue records track yarn issued against MR line items.
"""

from fastapi import Depends, Request, HTTPException, APIRouter
from typing import Optional, List
from pydantic import BaseModel
from datetime import date, datetime
from src.common.utils import now_ist
import logging
from sqlalchemy.orm import Session
from sqlalchemy import text
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.juteProcurement.query import (
    get_jute_issue_table_query,
    get_jute_issue_table_count_query,
    get_jute_issue_create_setup_query,
    get_jute_stock_outstanding_query,
    get_jute_stock_outstanding_by_item_query,
    get_jute_issues_by_date_query,
    get_yarn_types_query,
)
from src.juteProcurement._excel_utils import (
    parse_iso_date,
    build_excel_response,
    enforce_row_cap,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# =============================================================================
# PYDANTIC MODELS
# =============================================================================

class JuteIssueCreate(BaseModel):
    """Model for creating a jute issue line item."""
    branch_id: int
    issue_date: date
    jute_mr_li_id: int
    yarn_type_id: int
    item_id: int
    quantity: float
    weight: float
    unit_conversion: Optional[str] = None
    issue_value: Optional[float] = None


class JuteIssueUpdate(BaseModel):
    """Model for updating a jute issue line item."""
    yarn_type_id: Optional[int] = None
    item_id: Optional[int] = None
    quantity: Optional[float] = None
    weight: Optional[float] = None
    unit_conversion: Optional[str] = None
    issue_value: Optional[float] = None


class JuteIssueBulkCreate(BaseModel):
    """Model for creating multiple jute issue line items."""
    branch_id: int
    issue_date: date
    items: List[JuteIssueCreate]


class JuteIssueStatusUpdate(BaseModel):
    """Model for updating issue status (open, approve, reject)."""
    branch_id: Optional[int] = None
    issue_date: Optional[date] = None
    status_id: int
    issue_ids: Optional[List[int]] = None  # Specific issue IDs to update (takes precedence)


# =============================================================================
# ENDPOINTS
# =============================================================================

JUTE_ISSUE_DOWNLOAD_COLUMNS = [
    ("Issue Date", "issue_date"),
    ("Branch", "branch_name"),
    ("Total Entries", "total_entries"),
    ("Total Weight", "total_weight"),
    ("Approved Count", "approved_count"),
    ("Status", "status"),
]


def _build_issue_params(co_id: int, q_search: str, date_from, date_to):
    search_param = f"%{q_search}%" if q_search else None
    base = {
        "co_id": co_id,
        "date_from": date_from,
        "date_to": date_to,
    }
    if search_param:
        base["search"] = search_param
    return base


@router.get("/get_issue_table")
def get_jute_issue_table(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Get paginated list of jute issue records.

    Query params:
    - co_id: Company ID (required)
    - page: Page number (default: 1)
    - limit: Records per page (default: 10)
    - search: Search term (optional)
    - from_date / to_date: Optional ISO dates (YYYY-MM-DD) bounding issue_date
    """
    try:
        q_co_id = request.query_params.get("co_id")
        q_page = request.query_params.get("page", "1")
        q_limit = request.query_params.get("limit", "10")
        q_search = request.query_params.get("search", "").strip()
        q_from_date = (request.query_params.get("from_date") or "").strip()
        q_to_date = (request.query_params.get("to_date") or "").strip()

        if not q_co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        try:
            co_id = int(q_co_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid co_id")

        date_from = parse_iso_date(q_from_date, "from_date")
        date_to = parse_iso_date(q_to_date, "to_date")

        try:
            page = max(1, int(q_page))
            limit = max(1, min(100, int(q_limit)))
        except ValueError:
            page = 1
            limit = 10

        offset = (page - 1) * limit
        base_params = _build_issue_params(co_id, q_search, date_from, date_to)

        count_query = get_jute_issue_table_count_query(co_id, q_search)
        count_result = db.execute(count_query, base_params).fetchone()
        total = count_result.total if count_result else 0

        data_query = get_jute_issue_table_query(co_id, q_search)
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
        logger.error(f"Error fetching jute issue table: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error fetching jute issue records: {str(e)}")


@router.get("/download_issue_table")
def download_jute_issue_table(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Download the Jute Issue list (aggregated by date+branch) as an .xlsx workbook."""
    try:
        q_co_id = request.query_params.get("co_id")
        q_search = request.query_params.get("search", "").strip()
        q_from_date = (request.query_params.get("from_date") or "").strip()
        q_to_date = (request.query_params.get("to_date") or "").strip()

        if not q_co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        try:
            co_id = int(q_co_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid co_id")

        date_from = parse_iso_date(q_from_date, "from_date")
        date_to = parse_iso_date(q_to_date, "to_date")

        base_params = _build_issue_params(co_id, q_search, date_from, date_to)

        count_query = get_jute_issue_table_count_query(co_id, q_search)
        count_result = db.execute(count_query, base_params).fetchone()
        total = int(count_result.total) if count_result and count_result.total else 0
        enforce_row_cap(total)

        rows = []
        if total > 0:
            data_query = get_jute_issue_table_query(co_id, q_search)
            data_params = {**base_params, "limit": total, "offset": 0}
            result = db.execute(data_query, data_params).fetchall()
            rows = [dict(r._mapping) for r in result]

        return build_excel_response(
            rows=rows,
            columns=JUTE_ISSUE_DOWNLOAD_COLUMNS,
            sheet_title="Jute Issue",
            filename_prefix="jute_issue",
            from_date_str=q_from_date,
            to_date_str=q_to_date,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error downloading Jute Issue table")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_issue_by_id/{issue_id}")
def get_jute_issue_by_id(
    issue_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Get a single jute issue record by ID.
    
    Path params:
    - issue_id: The jute issue ID
    
    Query params:
    - co_id: Company ID (required)
    """
    try:
        q_co_id = request.query_params.get("co_id")
        if not q_co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        
        try:
            co_id = int(q_co_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid co_id")

        sql = text("""
            SELECT
                ji.jute_issue_id,
                ji.branch_id,
                bm.branch_name,
                ji.issue_date,
                ji.status_id,
                COALESCE(sm.status_name, 'Draft') AS status,
                ji.issue_value,
                COALESCE(ji.item_id, mrli.actual_item_id) AS item_id,
                COALESCE(im.item_name, im2.item_name) AS item_name,
                ji.jute_mr_li_id,
                mrli.jute_mr_id,
                jm.jute_gate_entry_no,
                ji.yarn_type_id,
                COALESCE(yim.item_name, jym.jute_yarn_name) AS yarn_type_name,
                ji.quantity,
                ji.weight,
                ji.unit_conversion,
                ji.updated_by,
                ji.update_date_time
            FROM jute_issue ji
            INNER JOIN branch_mst bm ON bm.branch_id = ji.branch_id
            LEFT JOIN status_mst sm ON sm.status_id = ji.status_id
            LEFT JOIN jute_mr_li mrli ON mrli.jute_mr_li_id = ji.jute_mr_li_id
            LEFT JOIN jute_mr jm ON jm.jute_mr_id = mrli.jute_mr_id
            LEFT JOIN item_mst im ON im.item_id = ji.item_id
            LEFT JOIN item_mst im2 ON im2.item_id = mrli.actual_item_id
            LEFT JOIN jute_yarn_mst jym ON jym.jute_yarn_id = ji.yarn_type_id
            LEFT JOIN item_mst yim ON yim.item_id = jym.item_id
            WHERE ji.jute_issue_id = :issue_id
            AND bm.co_id = :co_id
        """)

        result = db.execute(sql, {"issue_id": issue_id, "co_id": co_id}).fetchone()
        
        if not result:
            raise HTTPException(status_code=404, detail="Jute issue record not found")

        return {"data": dict(result._mapping)}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching jute issue by ID: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error fetching jute issue record: {str(e)}")


@router.get("/get_issue_create_setup")
def get_issue_create_setup(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Get setup data for creating jute issue.
    Returns: jute items (item_grp_id 2 or 3), yarn types, and branches.
    """
    try:
        q_co_id = request.query_params.get("co_id")
        if not q_co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        
        co_id = int(q_co_id)

        # Get jute groups (subgroups from item_grp_mst)
        jute_items_query = get_jute_issue_create_setup_query()
        jute_items_rows = db.execute(jute_items_query, {"co_id": co_id}).fetchall()
        jute_groups = [dict(r._mapping) for r in jute_items_rows]

        # Get yarn types
        yarn_types_query = get_yarn_types_query()
        yarn_types_rows = db.execute(yarn_types_query, {"co_id": co_id}).fetchall()
        yarn_types = [dict(r._mapping) for r in yarn_types_rows]

        # Get branches
        branches_sql = text("""
            SELECT branch_id, branch_name 
            FROM branch_mst 
            WHERE co_id = :co_id 
            AND (active = 1 OR active IS NULL)
            ORDER BY branch_name
        """)
        branches_rows = db.execute(branches_sql, {"co_id": co_id}).fetchall()
        branches = [dict(r._mapping) for r in branches_rows]

        return {
            "jute_groups": jute_groups,
            "yarn_types": yarn_types,
            "branches": branches,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching issue create setup: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error fetching setup data: {str(e)}")


@router.get("/get_stock_outstanding")
def get_stock_outstanding(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Get available stock from vw_jute_stock_outstanding view.
    Filters by branch_id (required) and optionally by item_id and issue_date.
    Returns MR-wise available stock for issue.
    """
    try:
        q_co_id = request.query_params.get("co_id")
        q_branch_id = request.query_params.get("branch_id")
        q_item_id = request.query_params.get("item_id")
        q_issue_date = request.query_params.get("issue_date")

        if not q_co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        if not q_branch_id:
            raise HTTPException(status_code=400, detail="branch_id is required")

        branch_id = int(q_branch_id)
        
        if q_item_id:
            item_id = int(q_item_id)
            query = get_jute_stock_outstanding_by_item_query()
            params = {"branch_id": branch_id, "item_id": item_id}
        else:
            query = get_jute_stock_outstanding_query()
            params = {"branch_id": branch_id}
        
        # Add issue_date if provided, otherwise use empty string to disable date filtering
        params["issue_date"] = q_issue_date if q_issue_date else ""
        
        rows = db.execute(query, params).fetchall()

        data = [dict(r._mapping) for r in rows]
        return {"data": data}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching stock outstanding: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error fetching stock data: {str(e)}")


@router.get("/get_issues_by_date")
def get_issues_by_date(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Get all jute issue line items for a specific branch and date.
    Used for the issue detail/edit page.
    """
    try:
        q_co_id = request.query_params.get("co_id")
        q_branch_id = request.query_params.get("branch_id")
        q_issue_date = request.query_params.get("issue_date")

        if not q_co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        if not q_branch_id:
            raise HTTPException(status_code=400, detail="branch_id is required")
        if not q_issue_date:
            raise HTTPException(status_code=400, detail="issue_date is required")

        co_id = int(q_co_id)
        branch_id = int(q_branch_id)

        query = get_jute_issues_by_date_query()
        rows = db.execute(query, {
            "co_id": co_id,
            "branch_id": branch_id,
            "issue_date": q_issue_date,
        }).fetchall()

        data = [dict(r._mapping) for r in rows]

        # Calculate totals
        total_weight = sum(row.get("weight", 0) or 0 for row in data)
        total_value = sum(row.get("issue_value", 0) or 0 for row in data)
        total_qty = sum(row.get("quantity", 0) or 0 for row in data)
        
        # Determine aggregated status
        if not data:
            status = "Draft"
            status_id = 21
        else:
            approved_count = sum(1 for row in data if row.get("status_id") == 3)
            if approved_count == len(data):
                status = "Approved"
                status_id = 3
            elif approved_count > 0:
                status = "Partial Approved"
                status_id = 20
            else:
                # Check if any are open (status_id = 1)
                open_count = sum(1 for row in data if row.get("status_id") == 1)
                if open_count == len(data):
                    status = "Open"
                    status_id = 1
                elif open_count > 0:
                    status = "Partial Open"
                    status_id = 20
                else:
                    status = "Draft"
                    status_id = 21

        return {
            "data": data,
            "summary": {
                "total_entries": len(data),
                "total_weight": round(total_weight, 2),
                "total_value": round(total_value, 2),
                "total_qty": round(total_qty, 2),
                "status": status,
                "status_id": status_id,
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching issues by date: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error fetching issues: {str(e)}")


@router.get("/get_max_issue_date")
def get_max_issue_date(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Get the maximum issue date for a branch.
    Used to set default date for new issues (max_date + 1).
    
    Query params:
    - co_id: Company ID (required for tenant resolution)
    - branch_id: Branch ID (required)
    """
    try:
        q_co_id = request.query_params.get("co_id")
        q_branch_id = request.query_params.get("branch_id")

        if not q_co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        if not q_branch_id:
            raise HTTPException(status_code=400, detail="branch_id is required")

        branch_id = int(q_branch_id)

        query = text("""
            SELECT MAX(issue_date) as max_date
            FROM jute_issue
            WHERE branch_id = :branch_id
        """)
        
        result = db.execute(query, {"branch_id": branch_id}).fetchone()
        max_date = result.max_date if result else None

        return {
            "max_date": max_date.isoformat() if max_date else None
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching max issue date: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error fetching max issue date: {str(e)}")


@router.post("/create_issue")
def create_issue(
    body: JuteIssueCreate,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Create a new jute issue line item.
    Issue starts as Draft (status_id = 21).
    """
    try:
        q_co_id = request.query_params.get("co_id")
        if not q_co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        # Calculate issue_value: rate (per quintal) × (weight in kg / 100)
        # Rate is stored per quintal, weight is in kg
        # First get the actual_rate from the MR line item
        rate_query = text("""
            SELECT actual_rate FROM jute_mr_li WHERE jute_mr_li_id = :jute_mr_li_id
        """)
        rate_result = db.execute(rate_query, {"jute_mr_li_id": body.jute_mr_li_id}).fetchone()
        
        if not rate_result:
            raise HTTPException(status_code=400, detail="Invalid MR line item ID")

        actual_rate = rate_result.actual_rate or 0
        # Rate is per quintal (100 kg), weight is in kg
        issue_value = round((body.weight / 100) * actual_rate, 2) if body.weight else 0

        sql = text("""
            INSERT INTO jute_issue (
                branch_id, issue_date, jute_mr_li_id, yarn_type_id, item_id,
                quantity, weight, unit_conversion, issue_value, status_id,
                updated_by, update_date_time
            ) VALUES (
                :branch_id, :issue_date, :jute_mr_li_id, :yarn_type_id, :item_id,
                :quantity, :weight, :unit_conversion, :issue_value, :status_id,
                :updated_by, :update_date_time
            )
        """)

        username = token_data.get("sub", "system")
        
        db.execute(sql, {
            "branch_id": body.branch_id,
            "issue_date": body.issue_date,
            "jute_mr_li_id": body.jute_mr_li_id,
            "yarn_type_id": body.yarn_type_id,
            "item_id": body.item_id,
            "quantity": round(body.quantity, 2) if body.quantity else 0,
            "weight": round(body.weight, 2) if body.weight else 0,
            "unit_conversion": body.unit_conversion,
            "issue_value": issue_value,
            "status_id": 21,  # Draft
            "updated_by": username,
            "update_date_time": now_ist(),
        })
        db.commit()

        # Get the inserted ID
        result = db.execute(text("SELECT LAST_INSERT_ID() AS id")).fetchone()
        new_id = result.id if result else None

        return {
            "message": "Jute issue created successfully",
            "jute_issue_id": new_id,
            "issue_value": issue_value,
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating jute issue: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error creating jute issue: {str(e)}")


@router.put("/update_issue/{issue_id}")
def update_issue(
    issue_id: int,
    body: JuteIssueUpdate,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Update an existing jute issue line item.
    Only allowed if status is Draft (21).
    """
    try:
        q_co_id = request.query_params.get("co_id")
        if not q_co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        # Check if issue exists and is in draft status
        check_sql = text("""
            SELECT ji.jute_issue_id, ji.status_id, ji.jute_mr_li_id
            FROM jute_issue ji
            INNER JOIN branch_mst bm ON bm.branch_id = ji.branch_id
            WHERE ji.jute_issue_id = :issue_id AND bm.co_id = :co_id
        """)
        existing = db.execute(check_sql, {"issue_id": issue_id, "co_id": int(q_co_id)}).fetchone()
        
        if not existing:
            raise HTTPException(status_code=404, detail="Jute issue not found")
        if existing.status_id not in (21, None):  # Allow update only for Draft
            raise HTTPException(status_code=400, detail="Can only update issues in Draft status")

        # Build update fields dynamically
        update_fields = []
        update_params = {"issue_id": issue_id}

        if body.yarn_type_id is not None:
            update_fields.append("yarn_type_id = :yarn_type_id")
            update_params["yarn_type_id"] = body.yarn_type_id

        if body.item_id is not None:
            update_fields.append("item_id = :item_id")
            update_params["item_id"] = body.item_id

        if body.quantity is not None:
            update_fields.append("quantity = :quantity")
            update_params["quantity"] = round(body.quantity, 2)

        if body.weight is not None:
            update_fields.append("weight = :weight")
            update_params["weight"] = round(body.weight, 2)
            
            # Recalculate issue_value if weight changes
            rate_query = text("""
                SELECT actual_rate FROM jute_mr_li WHERE jute_mr_li_id = :jute_mr_li_id
            """)
            rate_result = db.execute(rate_query, {"jute_mr_li_id": existing.jute_mr_li_id}).fetchone()
            actual_rate = rate_result.actual_rate if rate_result else 0
            issue_value = round((body.weight / 100) * actual_rate, 2) if body.weight else 0
            update_fields.append("issue_value = :issue_value")
            update_params["issue_value"] = issue_value

        if body.unit_conversion is not None:
            update_fields.append("unit_conversion = :unit_conversion")
            update_params["unit_conversion"] = body.unit_conversion

        if not update_fields:
            return {"message": "No fields to update"}

        # Add audit fields
        username = token_data.get("sub", "system")
        update_fields.append("updated_by = :updated_by")
        update_fields.append("update_date_time = :update_date_time")
        update_params["updated_by"] = username
        update_params["update_date_time"] = now_ist()

        sql = text(f"""
            UPDATE jute_issue SET {", ".join(update_fields)}
            WHERE jute_issue_id = :issue_id
        """)
        db.execute(sql, update_params)
        db.commit()

        return {"message": "Jute issue updated successfully"}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating jute issue: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error updating jute issue: {str(e)}")


@router.delete("/delete_issue/{issue_id}")
def delete_issue(
    issue_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Delete a jute issue line item.
    Only allowed if status is Draft (21).
    """
    try:
        q_co_id = request.query_params.get("co_id")
        if not q_co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        # Check if issue exists and is in draft status
        check_sql = text("""
            SELECT ji.jute_issue_id, ji.status_id
            FROM jute_issue ji
            INNER JOIN branch_mst bm ON bm.branch_id = ji.branch_id
            WHERE ji.jute_issue_id = :issue_id AND bm.co_id = :co_id
        """)
        existing = db.execute(check_sql, {"issue_id": issue_id, "co_id": int(q_co_id)}).fetchone()
        
        if not existing:
            raise HTTPException(status_code=404, detail="Jute issue not found")
        if existing.status_id not in (21, None):
            raise HTTPException(status_code=400, detail="Can only delete issues in Draft status")

        sql = text("DELETE FROM jute_issue WHERE jute_issue_id = :issue_id")
        db.execute(sql, {"issue_id": issue_id})
        db.commit()

        return {"message": "Jute issue deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting jute issue: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error deleting jute issue: {str(e)}")


@router.post("/open_issues")
def open_issues(
    body: JuteIssueStatusUpdate,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Open jute issues. Changes status from Draft (21) to Open (1).
    
    Can operate in two modes:
    - Specific IDs: If issue_ids is provided, only those issues are updated
    - Bulk by date: If branch_id and issue_date are provided, all matching issues are updated
    """
    try:
        q_co_id = request.query_params.get("co_id")
        if not q_co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        username = token_data.get("sub", "system")
        update_params = {
            "co_id": int(q_co_id),
            "updated_by": username,
            "update_date_time": now_ist(),
        }

        # Mode 1: Specific issue IDs
        if body.issue_ids and len(body.issue_ids) > 0:
            placeholders = ", ".join([f":id_{i}" for i in range(len(body.issue_ids))])
            sql = text(f"""
                UPDATE jute_issue ji
                INNER JOIN branch_mst bm ON bm.branch_id = ji.branch_id
                SET ji.status_id = 1, ji.updated_by = :updated_by, ji.update_date_time = :update_date_time
                WHERE ji.jute_issue_id IN ({placeholders})
                AND ji.status_id = 21
                AND bm.co_id = :co_id
            """)
            for i, issue_id in enumerate(body.issue_ids):
                update_params[f"id_{i}"] = issue_id
        # Mode 2: Bulk by branch and date
        elif body.branch_id and body.issue_date:
            sql = text("""
                UPDATE jute_issue ji
                INNER JOIN branch_mst bm ON bm.branch_id = ji.branch_id
                SET ji.status_id = 1, ji.updated_by = :updated_by, ji.update_date_time = :update_date_time
                WHERE ji.branch_id = :branch_id
                AND ji.issue_date = :issue_date
                AND ji.status_id = 21
                AND bm.co_id = :co_id
            """)
            update_params["branch_id"] = body.branch_id
            update_params["issue_date"] = body.issue_date
        else:
            raise HTTPException(status_code=400, detail="Either issue_ids or (branch_id and issue_date) is required")
        
        result = db.execute(sql, update_params)
        db.commit()

        return {"message": f"Opened {result.rowcount} issue(s) successfully"}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error opening issues: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error opening issues: {str(e)}")


@router.post("/approve_issues")
def approve_issues(
    body: JuteIssueStatusUpdate,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Approve jute issues. Changes status from Open (1) to Approved (3).
    
    Can operate in two modes:
    - Specific IDs: If issue_ids is provided, only those issues are updated
    - Bulk by date: If branch_id and issue_date are provided, all matching issues are updated
    """
    try:
        q_co_id = request.query_params.get("co_id")
        if not q_co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        username = token_data.get("sub", "system")
        update_params = {
            "co_id": int(q_co_id),
            "updated_by": username,
            "update_date_time": now_ist(),
        }

        # Mode 1: Specific issue IDs
        if body.issue_ids and len(body.issue_ids) > 0:
            placeholders = ", ".join([f":id_{i}" for i in range(len(body.issue_ids))])
            sql = text(f"""
                UPDATE jute_issue ji
                INNER JOIN branch_mst bm ON bm.branch_id = ji.branch_id
                SET ji.status_id = 3, ji.updated_by = :updated_by, ji.update_date_time = :update_date_time
                WHERE ji.jute_issue_id IN ({placeholders})
                AND ji.status_id = 1
                AND bm.co_id = :co_id
            """)
            for i, issue_id in enumerate(body.issue_ids):
                update_params[f"id_{i}"] = issue_id
        # Mode 2: Bulk by branch and date
        elif body.branch_id and body.issue_date:
            sql = text("""
                UPDATE jute_issue ji
                INNER JOIN branch_mst bm ON bm.branch_id = ji.branch_id
                SET ji.status_id = 3, ji.updated_by = :updated_by, ji.update_date_time = :update_date_time
                WHERE ji.branch_id = :branch_id
                AND ji.issue_date = :issue_date
                AND ji.status_id = 1
                AND bm.co_id = :co_id
            """)
            update_params["branch_id"] = body.branch_id
            update_params["issue_date"] = body.issue_date
        else:
            raise HTTPException(status_code=400, detail="Either issue_ids or (branch_id and issue_date) is required")
        
        result = db.execute(sql, update_params)
        db.commit()

        return {"message": f"Approved {result.rowcount} issue(s) successfully"}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error approving issues: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error approving issues: {str(e)}")


@router.post("/reject_issues")
def reject_issues(
    body: JuteIssueStatusUpdate,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Reject jute issues. Changes status from Open (1) to Rejected (4).
    
    Can operate in two modes:
    - Specific IDs: If issue_ids is provided, only those issues are updated
    - Bulk by date: If branch_id and issue_date are provided, all matching issues are updated
    """
    try:
        q_co_id = request.query_params.get("co_id")
        if not q_co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        username = token_data.get("sub", "system")
        update_params = {
            "co_id": int(q_co_id),
            "updated_by": username,
            "update_date_time": now_ist(),
        }

        # Mode 1: Specific issue IDs
        if body.issue_ids and len(body.issue_ids) > 0:
            placeholders = ", ".join([f":id_{i}" for i in range(len(body.issue_ids))])
            sql = text(f"""
                UPDATE jute_issue ji
                INNER JOIN branch_mst bm ON bm.branch_id = ji.branch_id
                SET ji.status_id = 4, ji.updated_by = :updated_by, ji.update_date_time = :update_date_time
                WHERE ji.jute_issue_id IN ({placeholders})
                AND ji.status_id = 1
                AND bm.co_id = :co_id
            """)
            for i, issue_id in enumerate(body.issue_ids):
                update_params[f"id_{i}"] = issue_id
        # Mode 2: Bulk by branch and date
        elif body.branch_id and body.issue_date:
            sql = text("""
                UPDATE jute_issue ji
                INNER JOIN branch_mst bm ON bm.branch_id = ji.branch_id
                SET ji.status_id = 4, ji.updated_by = :updated_by, ji.update_date_time = :update_date_time
                WHERE ji.branch_id = :branch_id
                AND ji.issue_date = :issue_date
                AND ji.status_id = 1
                AND bm.co_id = :co_id
            """)
            update_params["branch_id"] = body.branch_id
            update_params["issue_date"] = body.issue_date
        else:
            raise HTTPException(status_code=400, detail="Either issue_ids or (branch_id and issue_date) is required")
        
        result = db.execute(sql, update_params)
        db.commit()

        return {"message": f"Rejected {result.rowcount} issue(s) successfully"}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error rejecting issues: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error rejecting issues: {str(e)}")