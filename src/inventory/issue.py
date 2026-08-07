"""
FastAPI router for inventory issue endpoints.
"""
from fastapi import Depends, Request, HTTPException, APIRouter
import logging
from sqlalchemy.orm import Session
from sqlalchemy.sql import text
from pydantic import BaseModel, Field
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.inventory.query import (
    get_issue_table_query,
    get_issue_table_count_query,
    get_issue_by_id_query,
    get_issue_details_query,
    insert_issue_hdr,
    insert_issue_li,
    update_issue_hdr,
    delete_issue_li,
    get_max_issue_pass_no_for_branch,
    update_issue_status,
    get_available_inward_inventory_query,
    get_cost_factors_by_branch_query,
    get_machines_by_dept_query,
    get_machines_by_branch_query,
    get_searchable_inventory_list_query,
    get_searchable_inventory_count_query,
)
from datetime import datetime, date
from src.procurement.indent import get_fy_boundaries
from src.common.utils import now_ist
from src.common.approval_utils import (
    process_approval,
    process_rejection,
    calculate_approval_permissions,
)
from typing import Optional, List

logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================================================
# Pydantic Models for Request/Response
# ============================================================================

class IssueLineItemCreate(BaseModel):
    """Line item for creating/updating an issue.
    Accepts both backend names (issue_qty, expense_type_id) and
    frontend names (qty, expense_id) via aliases.
    """
    model_config = {"populate_by_name": True}

    item_id: int
    item_group_id: Optional[int] = Field(default=None, description="Item group ID (accepted but not stored in issue_li)")
    uom_id: int
    req_quantity: Optional[float] = None
    issue_qty: float = Field(validation_alias="qty")
    expense_type_id: Optional[int] = Field(default=None, validation_alias="expense_id")
    cost_factor_id: Optional[int] = None
    machine_id: Optional[int] = None
    inward_dtl_id: Optional[int] = None
    remarks: Optional[str] = None


class IssueCreate(BaseModel):
    """Request body for creating an issue.
    Accepts both 'lines' and 'line_items' as the line items field.
    """
    model_config = {"populate_by_name": True}

    branch_id: int
    dept_id: int
    issue_date: str  # YYYY-MM-DD
    issued_to: Optional[str] = None
    req_by: Optional[str] = None
    project_id: Optional[int] = None
    customer_id: Optional[int] = None
    internal_note: Optional[str] = None
    lines: List[IssueLineItemCreate] = Field(validation_alias="line_items")


class IssueUpdate(BaseModel):
    """Request body for updating an issue."""
    model_config = {"populate_by_name": True}

    branch_id: Optional[int] = None
    dept_id: Optional[int] = None
    issue_date: Optional[str] = None
    issued_to: Optional[str] = None
    req_by: Optional[str] = None
    project_id: Optional[int] = None
    customer_id: Optional[int] = None
    internal_note: Optional[str] = None
    lines: Optional[List[IssueLineItemCreate]] = Field(default=None, validation_alias="line_items")


class IssueStatusUpdate(BaseModel):
    """Request body for updating issue status."""
    status_id: int
    remarks: Optional[str] = None


@router.get("/get_issue_table")
def get_issue_table(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    co_id: int | None = None,
    page: int = 1,
    limit: int = 10,
    search: str | None = None,
):
    """
    Get paginated list of inventory issues for the index table.
    
    Args:
        co_id: Company ID to filter issues
        page: Page number (1-indexed)
        limit: Number of records per page
        search: Search term to filter by issue no, branch, department, expense type
    
    Returns:
        {
            "data": [...],
            "total": int,
            "page": int,
            "page_size": int
        }
    """
    try:
        # Parse query params
        q_co_id = request.query_params.get("co_id")
        q_page = request.query_params.get("page")
        q_limit = request.query_params.get("limit")
        q_search = request.query_params.get("search")

        if q_co_id is not None:
            try:
                co_id = int(q_co_id)
            except Exception:
                raise HTTPException(status_code=400, detail="Invalid co_id")

        if q_page is not None:
            try:
                page = int(q_page)
            except Exception:
                page = 1

        if q_limit is not None:
            try:
                limit = int(q_limit)
            except Exception:
                limit = 10

        if q_search is not None:
            search = q_search.strip() if q_search else None

        # Validate pagination
        if page < 1:
            page = 1
        if limit < 1:
            limit = 10
        if limit > 100:
            limit = 100

        offset = (page - 1) * limit
        search_like = f"%{search}%" if search else None

        # Get total count
        count_query = get_issue_table_count_query()
        count_result = db.execute(
            count_query,
            {"co_id": co_id, "search_like": search_like}
        ).fetchone()
        total = count_result.total if count_result else 0

        # Get paginated data
        data_query = get_issue_table_query()
        rows = db.execute(
            data_query,
            {
                "co_id": co_id,
                "search_like": search_like,
                "limit": limit,
                "offset": offset,
            }
        ).fetchall()

        data = []
        for row in rows:
            row_dict = dict(row._mapping)
            # Format issue date
            if row_dict.get("issue_date"):
                row_dict["issue_date"] = str(row_dict["issue_date"])
            data.append(row_dict)

        return {
            "data": data,
            "total": total,
            "page": page,
            "page_size": limit,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching issue table: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_issue_by_id/{issue_id}")
def get_issue_by_id(
    issue_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Get issue details by ID including header and line items.
    
    Args:
        issue_id: The issue ID to fetch
    
    Returns:
        Issue header with nested line items
    """
    try:
        # Get header
        header_query = get_issue_by_id_query()
        header_row = db.execute(header_query, {"issue_id": issue_id}).fetchone()

        if not header_row:
            raise HTTPException(status_code=404, detail="Issue not found")

        header = dict(header_row._mapping)

        # Format dates
        if header.get("issue_date"):
            header["issue_date"] = str(header["issue_date"])
        if header.get("updated_date_time"):
            header["updated_date_time"] = str(header["updated_date_time"])

        # Get approval_level
        approval_level = header.get("approval_level")
        if approval_level is not None:
            try:
                approval_level = int(approval_level)
            except (TypeError, ValueError):
                approval_level = None

        # Get status_id and branch_id for permission calculation
        status_id = header.get("status_id")
        branch_id = header.get("branch_id")

        # Parse menu_id from query params
        menu_id = request.query_params.get("menu_id")
        if menu_id:
            try:
                menu_id = int(menu_id)
            except (TypeError, ValueError):
                menu_id = None

        # Calculate permissions if menu_id is provided
        permissions = None
        if menu_id is not None and branch_id is not None and status_id is not None:
            try:
                user_id = int(token_data.get("user_id"))
                permissions = calculate_approval_permissions(
                    user_id=user_id,
                    menu_id=menu_id,
                    branch_id=branch_id,
                    status_id=status_id,
                    current_approval_level=approval_level,
                    db=db,
                )
            except Exception as e:
                logger.exception("Error calculating permissions, continuing without them")
                permissions = None

        # Get max approval level for the menu/branch
        max_approval_level = None
        if menu_id is not None and branch_id is not None:
            try:
                from src.common.approval_query import get_max_approval_level
                max_level_query = get_max_approval_level()
                max_level_result = db.execute(
                    max_level_query,
                    {"menu_id": menu_id, "branch_id": branch_id}
                ).fetchone()
                if max_level_result:
                    max_approval_level = dict(max_level_result._mapping).get("max_level")
            except Exception:
                logger.exception("Error fetching max approval level")

        # Get line items
        details_query = get_issue_details_query()
        detail_rows = db.execute(details_query, {"issue_id": issue_id}).fetchall()

        lines = []
        for row in detail_rows:
            line = dict(row._mapping)
            lines.append(line)

        header["lines"] = lines
        header["approval_level"] = approval_level
        header["max_approval_level"] = max_approval_level

        # Add permissions if calculated
        if permissions is not None:
            header["permissions"] = permissions

        return header

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching issue by ID: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_issue_setup_1")
def get_issue_setup_1(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    branch_id: int | None = None,
    co_id: int | None = None,
):
    """
    Get setup data for creating/editing an issue.
    Returns branches, departments, expense types, projects, cost factors, and machines.
    Items are now sourced from inventory search table, so item_groups are no longer needed here.
    Machines are returned for the branch; frontend filters by selected department.
    """
    try:
        from src.masters.query import get_branch_list, get_dept_list_by_branch_id
        from src.procurement.query import get_project, get_expense_types

        # Parse query params
        q_branch_id = request.query_params.get("branch_id")
        q_co_id = request.query_params.get("co_id")

        if q_branch_id is not None:
            try:
                branch_id = int(q_branch_id)
            except Exception:
                raise HTTPException(status_code=400, detail="Invalid branch_id")

        if q_co_id is not None:
            try:
                co_id = int(q_co_id)
            except Exception:
                raise HTTPException(status_code=400, detail="Invalid co_id")

        if co_id is None:
            raise HTTPException(status_code=400, detail="co_id is required")

        # Get branches
        branch_ids_list = [branch_id] if branch_id is not None else None
        branch_query = get_branch_list(branch_ids=branch_ids_list) if branch_ids_list else get_branch_list()
        branch_result = db.execute(branch_query, {"branch_ids": branch_ids_list} if branch_ids_list else {}).fetchall()
        branches = [dict(r._mapping) for r in branch_result]

        # Get departments
        dept_query = get_dept_list_by_branch_id(branch_ids_list if branch_ids_list is not None else [])
        dept_result = db.execute(dept_query, {"branch_ids": branch_ids_list, "co_id": co_id}).fetchall()
        departments = [dict(r._mapping) for r in dept_result]

        # Get projects
        projects = []
        if branch_id is not None:
            project_query = get_project(branch_id=branch_id)
            proj_result = db.execute(project_query, {"branch_id": branch_id}).fetchall()
            projects = [dict(r._mapping) for r in proj_result]

        # Get expense types
        expense_query = get_expense_types()
        exp_result = db.execute(expense_query).fetchall()
        expense_types = [dict(r._mapping) for r in exp_result]

        # Get cost factors for branch
        cost_factors = []
        if branch_id is not None:
            cost_factor_query = get_cost_factors_by_branch_query()
            cf_result = db.execute(cost_factor_query, {"branch_id": branch_id}).fetchall()
            cost_factors = [dict(r._mapping) for r in cf_result]

        # Get machines for branch (includes dept_id for frontend filtering)
        machines = []
        if branch_id is not None:
            machine_query = get_machines_by_branch_query()
            machine_result = db.execute(machine_query, {"branch_id": branch_id}).fetchall()
            machines = [dict(r._mapping) for r in machine_result]

        return {
            "branches": branches,
            "departments": departments,
            "projects": projects,
            "expense_types": expense_types,
            "cost_factors": cost_factors,
            "machines": machines,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching issue setup: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_available_inventory")
def get_available_inventory(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    branch_id: int | None = None,
    item_id: int | None = None,
    item_grp_id: int | None = None,
):
    """
    Get available inventory from approved inward details.
    Used for selecting SR line items when creating an issue.
    Returns items with available qty (approved_qty - already issued qty).
    """
    try:
        q_branch_id = request.query_params.get("branch_id")
        q_item_id = request.query_params.get("item_id")
        q_item_grp_id = request.query_params.get("item_grp_id")

        if q_branch_id is not None:
            try:
                branch_id = int(q_branch_id)
            except Exception:
                raise HTTPException(status_code=400, detail="Invalid branch_id")

        if q_item_id is not None:
            try:
                item_id = int(q_item_id)
            except Exception:
                item_id = None

        if q_item_grp_id is not None:
            try:
                item_grp_id = int(q_item_grp_id)
            except Exception:
                item_grp_id = None

        if branch_id is None:
            raise HTTPException(status_code=400, detail="branch_id is required")

        query = get_available_inward_inventory_query()
        rows = db.execute(query, {
            "branch_id": branch_id,
            "item_id": item_id,
            "item_grp_id": item_grp_id,
        }).fetchall()

        data = []
        for row in rows:
            row_dict = dict(row._mapping)
            if row_dict.get("inward_date"):
                row_dict["inward_date"] = str(row_dict["inward_date"])
            data.append(row_dict)

        return {"data": data, "total": len(data)}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching available inventory: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_inventory_list")
def get_inventory_list(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    branch_id: int | None = None,
    page: int = 1,
    limit: int = 10,
    search: str | None = None,
):
    """
    Get paginated searchable inventory list from approved inwards.
    Supports search by item group code/name, item code/name, and SR number.
    Used for the inventory search table in create issue page.

    Args:
        branch_id: Branch ID to filter inventory
        page: Page number (1-indexed)
        limit: Number of records per page (max 50)
        search: Search term to filter by item code, item name, group code, group name, or SR no
    """
    try:
        q_branch_id = request.query_params.get("branch_id")
        q_page = request.query_params.get("page")
        q_limit = request.query_params.get("limit")
        q_search = request.query_params.get("search")

        if q_branch_id is not None:
            try:
                branch_id = int(q_branch_id)
            except Exception:
                raise HTTPException(status_code=400, detail="Invalid branch_id")

        if q_page is not None:
            try:
                page = int(q_page)
            except Exception:
                page = 1

        if q_limit is not None:
            try:
                limit = int(q_limit)
            except Exception:
                limit = 10

        if q_search is not None:
            search = q_search.strip() if q_search else None

        if branch_id is None:
            raise HTTPException(status_code=400, detail="branch_id is required")

        # Clamp limit to reasonable bounds
        limit = max(1, min(limit, 50))
        page = max(1, page)
        offset = (page - 1) * limit

        search_like = f"%{search}%" if search else None

        # Get count
        count_query = get_searchable_inventory_count_query()
        count_result = db.execute(count_query, {
            "branch_id": branch_id,
            "search_like": search_like,
        }).fetchone()
        total = count_result.total if count_result else 0

        # Get data
        query = get_searchable_inventory_list_query()
        rows = db.execute(query, {
            "branch_id": branch_id,
            "search_like": search_like,
            "limit": limit,
            "offset": offset,
        }).fetchall()

        data = []
        for row in rows:
            row_dict = dict(row._mapping)
            if row_dict.get("inward_date"):
                row_dict["inward_date"] = str(row_dict["inward_date"])
            data.append(row_dict)

        return {
            "data": data,
            "total": total,
            "page": page,
            "limit": limit,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching inventory list: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_cost_factors")
def get_cost_factors(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    branch_id: int | None = None,
):
    """Get cost factors for a branch."""
    try:
        q_branch_id = request.query_params.get("branch_id")
        if q_branch_id is not None:
            try:
                branch_id = int(q_branch_id)
            except Exception:
                raise HTTPException(status_code=400, detail="Invalid branch_id")

        if branch_id is None:
            raise HTTPException(status_code=400, detail="branch_id is required")

        query = get_cost_factors_by_branch_query()
        rows = db.execute(query, {"branch_id": branch_id}).fetchall()
        data = [dict(r._mapping) for r in rows]

        return {"data": data}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching cost factors: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_machines")
def get_machines(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    dept_id: int | None = None,
):
    """Get machines for a department."""
    try:
        q_dept_id = request.query_params.get("dept_id")
        if q_dept_id is not None:
            try:
                dept_id = int(q_dept_id)
            except Exception:
                raise HTTPException(status_code=400, detail="Invalid dept_id")

        if dept_id is None:
            raise HTTPException(status_code=400, detail="dept_id is required")

        query = get_machines_by_dept_query()
        rows = db.execute(query, {"dept_id": dept_id}).fetchall()
        data = [dict(r._mapping) for r in rows]

        return {"data": data}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching machines: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/create_issue")
def create_issue(
    request: Request,
    issue_data: IssueCreate,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Create a new issue with line items.
    """
    try:
        user_id = token_data.get("user_id") or token_data.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="User not authenticated")

        now = now_ist()

        # Get next issue pass number for branch, scoped to the financial year of
        # issue_date. issue_pass_no is a per-FY sequence (legacy); without the FY
        # filter a stale prior-year max (e.g. branch 29 reaching 8900 in FY2023-24)
        # poisons the current year and the number jumps (8901 instead of 35).
        # Matches the procurement/sales numbering pattern.
        if not issue_data.issue_date:
            raise HTTPException(status_code=400, detail="issue_date is required")
        fy_start, fy_end = get_fy_boundaries(issue_data.issue_date)
        max_query = get_max_issue_pass_no_for_branch()
        max_result = db.execute(max_query, {
            "branch_id": issue_data.branch_id,
            "fy_start": fy_start,
            "fy_end": fy_end,
        }).fetchone()
        next_issue_no = (max_result.max_issue_no if max_result else 0) + 1

        # Insert header
        header_query = insert_issue_hdr()
        db.execute(header_query, {
            "branch_id": issue_data.branch_id,
            "dept_id": issue_data.dept_id,
            "issue_pass_no": next_issue_no,
            "issue_pass_print_no": None,
            "active": 1,
            "issue_date": issue_data.issue_date,
            "item_id": None,  # Deprecated field
            "status_id": 21,  # Draft
            "issued_to": issue_data.issued_to,
            "req_by": issue_data.req_by,
            "project_id": issue_data.project_id,
            "customer_id": issue_data.customer_id,
            "internal_note": issue_data.internal_note,
            "updated_by": user_id,
            "updated_date_time": now,
        })
        db.flush()

        # Get the inserted ID
        result = db.execute(text("SELECT LAST_INSERT_ID() AS issue_id")).fetchone()
        issue_id = result.issue_id

        # Insert line items
        line_query = insert_issue_li()
        for line in issue_data.lines:
            db.execute(line_query, {
                "issue_id": issue_id,
                "item_id": line.item_id,
                "uom_id": line.uom_id,
                "req_quantity": line.req_quantity,
                "issue_qty": line.issue_qty,
                "expense_type_id": line.expense_type_id,
                "cost_factor_id": line.cost_factor_id,
                "machine_id": line.machine_id,
                "inward_dtl_id": line.inward_dtl_id,
                "remarks": line.remarks,
                "updated_by": user_id,
                "updated_date_time": now,
            })

        db.commit()

        return {
            "success": True,
            "issue_id": issue_id,
            "issue_no": next_issue_no,
            "message": "Issue created successfully",
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating issue: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/update_issue/{issue_id}")
def update_issue_endpoint(
    issue_id: int,
    request: Request,
    issue_data: IssueUpdate,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Update an existing issue and its line items.
    """
    try:
        user_id = token_data.get("user_id") or token_data.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="User not authenticated")

        now = now_ist()

        # Check if issue exists
        check_query = get_issue_by_id_query()
        existing = db.execute(check_query, {"issue_id": issue_id}).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Issue not found")

        # Update header if fields provided
        if any([
            issue_data.branch_id, issue_data.dept_id, issue_data.issue_date,
            issue_data.issued_to is not None, issue_data.req_by is not None,
            issue_data.project_id is not None, issue_data.customer_id is not None,
            issue_data.internal_note is not None
        ]):
            existing_dict = dict(existing._mapping)
            header_query = update_issue_hdr()
            db.execute(header_query, {
                "issue_id": issue_id,
                "branch_id": issue_data.branch_id or existing_dict.get("branch_id"),
                "dept_id": issue_data.dept_id or existing_dict.get("dept_id"),
                "issue_date": issue_data.issue_date or existing_dict.get("issue_date"),
                "issued_to": issue_data.issued_to if issue_data.issued_to is not None else existing_dict.get("issued_to"),
                "req_by": issue_data.req_by if issue_data.req_by is not None else existing_dict.get("req_by"),
                "project_id": issue_data.project_id if issue_data.project_id is not None else existing_dict.get("project_id"),
                "customer_id": issue_data.customer_id if issue_data.customer_id is not None else existing_dict.get("customer_id"),
                "internal_note": issue_data.internal_note if issue_data.internal_note is not None else existing_dict.get("internal_note"),
                "status_id": existing_dict.get("status_id"),
                "updated_by": user_id,
                "updated_date_time": now,
            })

        # Replace line items if provided
        if issue_data.lines is not None:
            # Delete existing line items
            delete_query = delete_issue_li()
            db.execute(delete_query, {"issue_id": issue_id})

            # Insert new line items
            line_query = insert_issue_li()
            for line in issue_data.lines:
                db.execute(line_query, {
                    "issue_id": issue_id,
                    "item_id": line.item_id,
                    "uom_id": line.uom_id,
                    "req_quantity": line.req_quantity,
                    "issue_qty": line.issue_qty,
                    "expense_type_id": line.expense_type_id,
                    "cost_factor_id": line.cost_factor_id,
                    "machine_id": line.machine_id,
                    "inward_dtl_id": line.inward_dtl_id,
                    "remarks": line.remarks,
                    "updated_by": user_id,
                    "updated_date_time": now,
                })

        db.commit()

        return {
            "success": True,
            "issue_id": issue_id,
            "message": "Issue updated successfully",
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating issue: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/update_issue_status/{issue_id}")
def update_issue_status_endpoint(
    issue_id: int,
    request: Request,
    status_data: IssueStatusUpdate,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Update the status of an issue (for approval workflow).

    For approve (status_id=3) and reject (status_id=4), uses the generic
    process_approval / process_rejection utilities which handle approval
    levels, permission checks, and auto-transitions.

    For other status changes (open, cancel, reopen), uses direct update.
    """
    try:
        user_id = token_data.get("user_id") or token_data.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="User not authenticated")

        # Parse menu_id from query params (needed for approval permission checks)
        menu_id = request.query_params.get("menu_id")
        if menu_id:
            try:
                menu_id = int(menu_id)
            except (TypeError, ValueError):
                menu_id = None

        now = now_ist()

        # Route approve/reject through the generic approval utilities
        if status_data.status_id == 3:  # Approve
            if not menu_id:
                raise HTTPException(status_code=400, detail="menu_id is required for approval")
            result = process_approval(
                doc_id=issue_id,
                user_id=int(user_id),
                menu_id=menu_id,
                db=db,
                get_doc_fn=get_issue_by_id_query,
                update_status_fn=update_issue_status,
                id_param_name="issue_id",
                doc_name="Issue",
                extra_update_params={
                    "approved_by": int(user_id),
                    "approved_date": now.date(),
                },
            )
            return {
                "success": True,
                "issue_id": issue_id,
                **result,
            }

        if status_data.status_id == 4:  # Reject
            if not menu_id:
                raise HTTPException(status_code=400, detail="menu_id is required for rejection")
            result = process_rejection(
                doc_id=issue_id,
                user_id=int(user_id),
                menu_id=menu_id,
                db=db,
                get_doc_fn=get_issue_by_id_query,
                update_status_fn=update_issue_status,
                id_param_name="issue_id",
                doc_name="Issue",
                reason=status_data.remarks,
                extra_update_params={
                    "approved_by": None,
                    "approved_date": None,
                },
            )
            return {
                "success": True,
                "issue_id": issue_id,
                **result,
            }

        # For other status changes (open, cancel, reopen) — direct update
        check_query = get_issue_by_id_query()
        existing = db.execute(check_query, {"issue_id": issue_id}).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Issue not found")

        # Determine approval_level for the new status
        approval_level = None
        approved_by = None
        approved_date = None

        query = update_issue_status()
        db.execute(query, {
            "issue_id": issue_id,
            "status_id": status_data.status_id,
            "approval_level": approval_level,
            "approved_by": approved_by,
            "approved_date": approved_date,
            "updated_by": user_id,
            "updated_date_time": now,
        })

        db.commit()

        status_labels = {
            21: "Draft",
            1: "Open",
            20: "Pending Approval",
            3: "Approved",
            4: "Rejected",
            5: "Closed",
            6: "Cancelled",
        }

        return {
            "success": True,
            "issue_id": issue_id,
            "status_id": status_data.status_id,
            "status_name": status_labels.get(status_data.status_id, "Unknown"),
            "message": f"Issue status updated to {status_labels.get(status_data.status_id, 'Unknown')}",
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating issue status: {e}")
        raise HTTPException(status_code=500, detail=str(e))
