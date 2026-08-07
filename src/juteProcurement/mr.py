"""
Jute Material Receipt (MR) API endpoints.
Provides endpoints for viewing and managing jute MR records.
"""

from io import BytesIO
from fastapi import Depends, Request, HTTPException, APIRouter
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, date
from src.common.utils import now_ist
import logging
from sqlalchemy.orm import Session
from sqlalchemy import text
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.juteProcurement.query import (
    get_jute_mr_table_query,
    get_jute_mr_table_count_query,
    get_jute_mr_by_id_query,
    get_jute_mr_line_items_query,
    get_all_active_company_branches_query,
    get_agent_map_options_query,
    get_warehouse_options_query,
    get_mr_with_approval_info,
    update_mr_status,
)
from src.common.approval_utils import process_approval, process_rejection, calculate_approval_permissions
from src.common.approval_query import get_max_approval_level
from src.juteProcurement.totals import compute_jute_totals
from src.juteProcurement.formatters import (
    get_financial_year_sql_expression,
    format_jute_mr_number,
    format_jute_bill_pass_number,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# =============================================================================
# PYDANTIC MODELS
# =============================================================================

class MRLineItemUpdate(BaseModel):
    """Model for updating a jute_mr_li record."""
    jute_mr_li_id: int
    actual_item_id: Optional[int] = None
    actual_quality: Optional[int] = None
    actual_qty: Optional[float] = None
    actual_weight: Optional[float] = None
    allowable_moisture: Optional[float] = None
    actual_moisture: Optional[str] = None
    claim_dust: Optional[float] = None
    shortage_kgs: Optional[int] = None
    accepted_weight: Optional[float] = None
    rate: Optional[float] = None
    claim_rate: Optional[float] = None
    claim_quality: Optional[str] = None
    water_damage_amount: Optional[float] = None
    premium_amount: Optional[float] = None
    remarks: Optional[str] = None
    warehouse_id: Optional[int] = None


class MRUpdateRequest(BaseModel):
    """Request model for updating MR header and line items."""
    mr_weight: Optional[float] = None
    party_branch_id: Optional[int] = None
    remarks: Optional[str] = None
    line_items: List[MRLineItemUpdate] = []


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.get("/get_mr_table")
def get_jute_mr_table(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Get paginated list of jute MR records.
    
    Query params:
    - co_id: Company ID (required)
    - page: Page number (default: 1)
    - limit: Records per page (default: 10)
    - search: Search term
    - from_date / to_date: Optional ISO dates (YYYY-MM-DD) bounding jute_mr_date
    """
    try:
        # Get query parameters
        q_co_id = request.query_params.get("co_id")
        q_page = request.query_params.get("page", "1")
        q_limit = request.query_params.get("limit", "10")
        q_search = request.query_params.get("search", "").strip()
        q_from_date = (request.query_params.get("from_date") or "").strip()
        q_to_date = (request.query_params.get("to_date") or "").strip()
        q_status_id = (request.query_params.get("status_id") or "").strip()

        # Validate co_id
        if not q_co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        try:
            co_id = int(q_co_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid co_id")

        def _parse_iso_date(value: str, field_name: str):
            if not value:
                return None
            try:
                return datetime.strptime(value, "%Y-%m-%d").date()
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid {field_name}; expected YYYY-MM-DD",
                )

        date_from = _parse_iso_date(q_from_date, "from_date")
        date_to = _parse_iso_date(q_to_date, "to_date")

        status_id = None
        if q_status_id:
            try:
                status_id = int(q_status_id)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid status_id")

        # Parse pagination
        try:
            page = max(1, int(q_page))
            limit = min(100, max(1, int(q_limit)))
        except ValueError:
            page = 1
            limit = 10

        offset = (page - 1) * limit

        # Build search parameter
        search_param = f"%{q_search}%" if q_search else None

        # Get total count
        count_query = get_jute_mr_table_count_query(co_id=co_id, search=q_search if q_search else None)
        count_params = {
            "co_id": co_id,
            "date_from": date_from,
            "date_to": date_to,
            "status_id": status_id,
        }
        if search_param:
            count_params["search"] = search_param

        count_result = db.execute(count_query, count_params).fetchone()
        total = count_result.total if count_result else 0

        # Get paginated data
        data_query = get_jute_mr_table_query(co_id=co_id, search=q_search if q_search else None)
        data_params = {
            "co_id": co_id,
            "limit": limit,
            "offset": offset,
            "date_from": date_from,
            "date_to": date_to,
            "status_id": status_id,
        }
        if search_param:
            data_params["search"] = search_param

        result = db.execute(data_query, data_params).fetchall()
        rows = [dict(r._mapping) for r in result]

        # Format dates for JSON serialization
        for row in rows:
            for field in ["jute_mr_date", "challan_date", "po_date", "jute_gate_entry_date", "updated_date_time"]:
                if row.get(field):
                    dt = row[field]
                    if isinstance(dt, (datetime, date)):
                        row[field] = str(dt) if isinstance(dt, date) else dt.isoformat()

        return {
            "data": rows,
            "total": total,
            "page": page,
            "page_size": limit,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching jute MR table")
        raise HTTPException(status_code=500, detail=str(e))


MR_DOWNLOAD_MAX_ROWS = 50000

MR_DOWNLOAD_COLUMNS = [
    ("MR No", "mr_num"),
    ("MR Date", "jute_mr_date"),
    ("Branch", "branch_name"),
    ("Supplier", "supplier_name"),
    ("Party", "party_name"),
    ("Challan No", "challan_no"),
    ("Gate Entry No", "gate_entry_no"),
    ("Gate Entry Date", "jute_gate_entry_date"),
    ("Mukam", "mukam"),
    ("Vehicle No", "vehicle_no"),
    ("MR Weight", "mr_weight"),
    ("Status", "status"),
]


@router.get("/download_mr_table")
def download_jute_mr_table(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Download the jute MR list as an .xlsx workbook, applying the same filters
    (search, from_date, to_date) as /get_mr_table. No pagination — exports the
    entire filtered set up to MR_DOWNLOAD_MAX_ROWS.

    Query params:
    - co_id: Company ID (required)
    - search: Optional search term
    - from_date / to_date: Optional ISO dates (YYYY-MM-DD) bounding jute_mr_date
    """
    try:
        q_co_id = request.query_params.get("co_id")
        q_search = request.query_params.get("search", "").strip()
        q_from_date = (request.query_params.get("from_date") or "").strip()
        q_to_date = (request.query_params.get("to_date") or "").strip()
        q_status_id = (request.query_params.get("status_id") or "").strip()

        if not q_co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        try:
            co_id = int(q_co_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid co_id")

        def _parse_iso_date(value: str, field_name: str):
            if not value:
                return None
            try:
                return datetime.strptime(value, "%Y-%m-%d").date()
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid {field_name}; expected YYYY-MM-DD",
                )

        date_from = _parse_iso_date(q_from_date, "from_date")
        date_to = _parse_iso_date(q_to_date, "to_date")

        status_id = None
        if q_status_id:
            try:
                status_id = int(q_status_id)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid status_id")

        search_param = f"%{q_search}%" if q_search else None

        count_query = get_jute_mr_table_count_query(co_id=co_id, search=q_search if q_search else None)
        count_params = {
            "co_id": co_id,
            "date_from": date_from,
            "date_to": date_to,
            "status_id": status_id,
        }
        if search_param:
            count_params["search"] = search_param

        count_result = db.execute(count_query, count_params).fetchone()
        total = int(count_result.total) if count_result and count_result.total else 0

        if total > MR_DOWNLOAD_MAX_ROWS:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Result set too large — max {MR_DOWNLOAD_MAX_ROWS} rows, "
                    f"got {total}. Narrow the date range or search term."
                ),
            )

        rows = []
        if total > 0:
            data_query = get_jute_mr_table_query(co_id=co_id, search=q_search if q_search else None)
            data_params = {
                "co_id": co_id,
                "limit": total,
                "offset": 0,
                "date_from": date_from,
                "date_to": date_to,
                "status_id": status_id,
            }
            if search_param:
                data_params["search"] = search_param

            result = db.execute(data_query, data_params).fetchall()
            rows = [dict(r._mapping) for r in result]

        wb = Workbook()
        ws = wb.active
        ws.title = "Jute MR"

        for col_idx, (header, _) in enumerate(MR_DOWNLOAD_COLUMNS, start=1):
            ws.cell(row=1, column=col_idx, value=header)

        for row_idx, row in enumerate(rows, start=2):
            mr_no = row.get("mr_num") or row.get("branch_mr_no")
            mr_date = row.get("jute_mr_date")
            if isinstance(mr_date, (datetime, date)):
                mr_date = str(mr_date) if isinstance(mr_date, date) else mr_date.isoformat()

            values = {
                "mr_num": mr_no,
                "jute_mr_date": mr_date,
                "branch_name": row.get("branch_name"),
                "supplier_name": row.get("supplier_name"),
                "party_name": row.get("party_name"),
                "challan_no": row.get("challan_no"),
                "gate_entry_no": row.get("gate_entry_no"),
                "mukam": row.get("mukam"),
                "vehicle_no": row.get("vehicle_no"),
                "mr_weight": row.get("mr_weight"),
                "status": row.get("status") or "Open",
            }
            for col_idx, (_, key) in enumerate(MR_DOWNLOAD_COLUMNS, start=1):
                ws.cell(row=row_idx, column=col_idx, value=values[key])

        bio = BytesIO()
        wb.save(bio)
        bio.seek(0)
        xlsx_bytes = bio.getvalue()

        date_suffix_parts = []
        if q_from_date:
            date_suffix_parts.append(q_from_date)
        if q_to_date:
            date_suffix_parts.append(q_to_date)
        date_suffix = "_".join(date_suffix_parts) if date_suffix_parts else "all"
        filename = f"jute_mr_{date_suffix}.xlsx"

        return StreamingResponse(
            iter([xlsx_bytes]),
            media_type=(
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            ),
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error downloading jute MR table")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_agent_options")
def get_agent_options(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Get agent options from jute_agent_map table.
    Returns agent branches that have been mapped for the current company.
    """
    try:
        q_co_id = request.query_params.get("co_id")
        if not q_co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        
        try:
            co_id = int(q_co_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid co_id")

        query = get_agent_map_options_query()
        result = db.execute(query, {"co_id": co_id}).fetchall()
        branches = [dict(r._mapping) for r in result]

        return {
            "branches": branches,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching agent options")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_warehouse_options")
def get_warehouse_options(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Get warehouse options for a specific branch.
    Returns warehouses with hierarchical path (e.g., 'Main-Section A-Bin 1').
    """
    try:
        q_branch_id = request.query_params.get("branch_id")
        if not q_branch_id:
            raise HTTPException(status_code=400, detail="branch_id is required")
        
        try:
            branch_id = int(q_branch_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid branch_id")

        query = get_warehouse_options_query()
        result = db.execute(query, {"branch_id": branch_id}).fetchall()
        warehouses = [dict(r._mapping) for r in result]

        return {
            "warehouses": warehouses,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching warehouse options")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_party_branches")
def get_party_branches(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Get party branches for a specific party.
    Returns party branches with address info for the dropdown.
    Used in MR edit to select party branch (mandatory field).
    
    Query params:
    - party_id: Party ID (required)
    """
    try:
        q_party_id = request.query_params.get("party_id")
        if not q_party_id:
            raise HTTPException(status_code=400, detail="party_id is required")
        
        try:
            party_id = int(q_party_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid party_id")

        query = text("""
            SELECT 
                pbm.party_mst_branch_id,
                pbm.party_id,
                pbm.address,
                pbm.gst_no,
                pm.supp_name AS party_name,
                CONCAT(COALESCE(pm.supp_name, ''), ' - ', COALESCE(pbm.address, '')) AS display
            FROM party_branch_mst pbm
            LEFT JOIN party_mst pm ON pm.party_id = pbm.party_id
            WHERE pbm.party_id = :party_id
                AND pbm.active = 1
            ORDER BY pbm.address
        """)
        result = db.execute(query, {"party_id": party_id}).fetchall()
        branches = [dict(r._mapping) for r in result]

        return {
            "branches": branches,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching party branches")
        raise HTTPException(status_code=500, detail=str(e))


def _build_mr_permissions(
    db: Session,
    menu_id: Optional[int],
    branch_id: Optional[int],
    status_id: Optional[int],
    approval_level: Optional[int],
    user_id: Optional[int],
) -> tuple[dict, Optional[int]]:
    """Compute the current user's approval permissions + the configured max level.

    Drives the MR action buttons so they follow the approval hierarchy:
      - Approve/Reject show only for the approver whose level matches the MR's
        current approval level (level-aware, via calculate_approval_permissions).
        Reject only surfaces once the MR is in Pending Approval (status 20) —
        matching the shared approval bar and the other transaction modules.
      - The frontend additionally shows Pending only at the highest level
        (canApprove AND approval_level == max_approval_level).

    Returns (permissions_dict, max_approval_level). When no menu context or no
    hierarchy is available, returns ({}, None) — the frontend then falls back to
    its status-based defaults (which do NOT grant approve, i.e. fail closed).
    """
    if not menu_id or not branch_id or not user_id:
        return {}, None
    try:
        permissions = calculate_approval_permissions(
            user_id=user_id,
            menu_id=menu_id,
            branch_id=branch_id,
            status_id=status_id,
            current_approval_level=approval_level,
            db=db,
        )

        max_row = db.execute(
            get_max_approval_level(),
            {"menu_id": menu_id, "branch_id": branch_id},
        ).fetchone()
        max_level = dict(max_row._mapping).get("max_level") if max_row else None
        return permissions, max_level
    except Exception:
        logger.exception("Error building MR approval permissions")
        return {}, None


@router.get("/get_mr_by_id")
def get_jute_mr_by_id(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Get a single jute MR with line items.
    
    Query params:
    - id: MR ID (required)
    """
    try:
        q_id = request.query_params.get("id")
        if not q_id:
            raise HTTPException(status_code=400, detail="id is required")
        
        try:
            mr_id = int(q_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid id")

        # Get header data
        header_query = get_jute_mr_by_id_query()
        header_result = db.execute(header_query, {"mr_id": mr_id}).fetchone()
        
        if not header_result:
            raise HTTPException(status_code=404, detail="MR not found")

        header = dict(header_result._mapping)

        # Format dates
        for field in ["jute_mr_date", "challan_date", "po_date", "jute_gate_entry_date", "updated_date_time"]:
            if header.get(field):
                dt = header[field]
                if isinstance(dt, (datetime, date)):
                    header[field] = str(dt) if isinstance(dt, date) else dt.isoformat()

        # Get line items
        line_items_query = get_jute_mr_line_items_query()
        line_items_result = db.execute(line_items_query, {"mr_id": mr_id}).fetchall()
        line_items = [dict(r._mapping) for r in line_items_result]

        # Level-aware approval permissions so the UI action buttons follow the
        # approval hierarchy (Approve/Reject only for the current level's
        # approver; Pending only at the highest level). menu_id is optional —
        # when absent the frontend falls back to status-based defaults.
        menu_id_param = request.query_params.get("menu_id")
        menu_id_val = None
        if menu_id_param:
            try:
                menu_id_val = int(menu_id_param)
            except ValueError:
                menu_id_val = None
        permissions, max_approval_level = _build_mr_permissions(
            db,
            menu_id_val,
            header.get("branch_id"),
            header.get("status_id"),
            header.get("approval_level"),
            token_data.get("user_id"),
        )
        header["permissions"] = permissions
        header["max_approval_level"] = max_approval_level

        return {
            "header": header,
            "line_items": line_items,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching jute MR by ID")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/update_mr/{mr_id}")
def update_jute_mr(
    mr_id: int,
    request: Request,
    body: MRUpdateRequest,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Update jute MR header and line items.
    Recalculates accepted_weight for each line item and updates mr_weight as sum of accepted weights.
    """
    try:
        q_co_id = request.query_params.get("co_id")
        if not q_co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        
        try:
            co_id = int(q_co_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid co_id")

        # Verify MR exists
        header_query = get_jute_mr_by_id_query()
        header_result = db.execute(header_query, {"mr_id": mr_id}).fetchone()
        
        if not header_result:
            raise HTTPException(status_code=404, detail="MR not found")

        # Get user info for audit
        user_id = token_data.get("user_id")
        now = now_ist()

        # Update line items and calculate accepted weights
        total_accepted_weight = 0.0
        
        for item in body.line_items:
            # Calculate shortage_kgs and accepted_weight
            actual_weight = float(item.actual_weight or 0.0)
            allowable_moisture = float(item.allowable_moisture) if item.allowable_moisture is not None else None
            actual_moisture_str = item.actual_moisture or "0"
            try:
                actual_moisture = float(actual_moisture_str)
            except (ValueError, TypeError):
                actual_moisture = 0.0
            
            claim_dust = float(item.claim_dust) if item.claim_dust is not None else 0.0
            
            # Calculate shortage_kgs first — all weights rounded to 0 decimals (whole kg)
            shortage_kgs = 0.0
            rounded_weight = round(actual_weight)
            accepted_weight = rounded_weight
            
            if actual_weight > 0:
                moisture_diff = 0.0
                if allowable_moisture is not None and actual_moisture > allowable_moisture:
                    moisture_diff = actual_moisture - allowable_moisture
                
                deduction_percentage = moisture_diff + claim_dust
                if deduction_percentage > 0:
                    # Formula: shortage_kgs = actual_weight * (moisture diff % + claim_dust%)
                    # Round to 0 decimals to match Integer column type
                    shortage_kgs = round(rounded_weight * deduction_percentage / 100.0)
                    # Formula: accepted_weight = actual_weight - shortage_kgs (both integers)
                    accepted_weight = max(0, rounded_weight - int(shortage_kgs))
                
                total_accepted_weight += accepted_weight
            
            # Update line item
            # Note: actual_rate is set to the same value as rate automatically
            update_query = text("""
                UPDATE jute_mr_li
                SET actual_item_id = :actual_item_id,
                    actual_quality = :actual_quality,
                    actual_qty = :actual_qty,
                    actual_weight = :actual_weight,
                    actual_rate = :rate,
                    allowable_moisture = :allowable_moisture,
                    actual_moisture = :actual_moisture,
                    claim_dust = :claim_dust,
                    shortage_kgs = :shortage_kgs,
                    accepted_weight = :accepted_weight,
                    rate = :rate,
                    claim_rate = :claim_rate,
                    claim_quality = :claim_quality,
                    water_damage_amount = :water_damage_amount,
                    premium_amount = :premium_amount,
                    remarks = :remarks,
                    warehouse_id = :warehouse_id,
                    updated_date_time = :updated_date_time
                WHERE jute_mr_li_id = :jute_mr_li_id
            """)
            
            db.execute(update_query, {
                "jute_mr_li_id": item.jute_mr_li_id,
                "actual_item_id": item.actual_item_id,
                "actual_quality": item.actual_quality,
                "actual_qty": item.actual_qty,
                "actual_weight": item.actual_weight,
                "allowable_moisture": item.allowable_moisture,
                "actual_moisture": item.actual_moisture,
                "claim_dust": item.claim_dust,
                "shortage_kgs": int(round(shortage_kgs)),
                "accepted_weight": int(round(accepted_weight)),
                "rate": item.rate,
                "claim_rate": item.claim_rate,
                "claim_quality": item.claim_quality,
                "water_damage_amount": item.water_damage_amount,
                "premium_amount": item.premium_amount,
                "remarks": item.remarks,
                "warehouse_id": item.warehouse_id,
                "updated_date_time": now,
            })

        # Update MR header with calculated weight
        mr_weight = round(body.mr_weight) if body.mr_weight is not None else round(total_accepted_weight)
        
        update_header_query = text("""
            UPDATE jute_mr
            SET mr_weight = :mr_weight,
                party_branch_id = :party_branch_id,
                remarks = :remarks,
                updated_by = :updated_by,
                updated_date_time = :updated_date_time
            WHERE jute_mr_id = :mr_id
        """)
        
        db.execute(update_header_query, {
            "mr_id": mr_id,
            "mr_weight": mr_weight,
            "party_branch_id": body.party_branch_id,
            "remarks": body.remarks,
            "updated_by": user_id,
            "updated_date_time": now,
        })

        db.commit()

        return {
            "success": True,
            "message": "MR updated successfully",
            "mr_id": mr_id,
            "mr_weight": mr_weight,
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error updating jute MR")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# STATUS CHANGE SCHEMA
# =============================================================================

class MRStatusChangeRequest(BaseModel):
    """Request model for changing MR status."""
    new_status_id: int
    remarks: Optional[str] = None


# =============================================================================
# STATUS CHANGE ENDPOINT
# =============================================================================

@router.put("/change_status/{mr_id}")
def change_mr_status(
    mr_id: int,
    request: Request,
    body: MRStatusChangeRequest,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Change the status of a jute MR.
    
    Validates that party_branch_id is set before allowing status changes from draft.
    Status IDs:
    - 21: Draft
    - 1: Open
    - 3: Approved
    - 4: Rejected
    - 5: Closed
    """
    try:
        q_co_id = request.query_params.get("co_id")
        if not q_co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        
        try:
            co_id = int(q_co_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid co_id")

        user_id = token_data.get("user_id")
        if not user_id:
            raise HTTPException(status_code=401, detail="User not authenticated")

        # Get current MR details
        check_query = text("""
            SELECT jute_mr_id, status_id, party_id, party_branch_id
            FROM jute_mr
            WHERE jute_mr_id = :mr_id
        """)
        mr_row = db.execute(check_query, {"mr_id": mr_id}).fetchone()
        
        if not mr_row:
            raise HTTPException(status_code=404, detail=f"MR with id {mr_id} not found")

        mr = dict(mr_row._mapping)
        current_status_id = mr.get("status_id")
        party_id = mr.get("party_id")
        party_branch_id = mr.get("party_branch_id")

        # Validate party and party_branch before allowing status change from draft
        # Draft status_id is typically 21
        if current_status_id == 21 and body.new_status_id != 21:
            if not party_id:
                raise HTTPException(
                    status_code=400,
                    detail="Cannot change status: Party must be selected before changing MR status."
                )
            if not party_branch_id:
                raise HTTPException(
                    status_code=400, 
                    detail="Cannot change status: Party branch must be selected. Please add a branch for this party in Party Master if none exist."
                )

        now = now_ist()

        # Update the status
        update_query = text("""
            UPDATE jute_mr
            SET status_id = :new_status_id,
                updated_by = :updated_by,
                updated_date_time = :updated_date_time
            WHERE jute_mr_id = :mr_id
        """)
        
        db.execute(update_query, {
            "mr_id": mr_id,
            "new_status_id": body.new_status_id,
            "updated_by": user_id,
            "updated_date_time": now,
        })

        db.commit()

        # Get status name
        status_query = text("SELECT status_name FROM status_mst WHERE status_id = :status_id")
        status_row = db.execute(status_query, {"status_id": body.new_status_id}).fetchone()
        status_name = status_row[0] if status_row else str(body.new_status_id)

        return {
            "success": True,
            "message": f"MR status changed to {status_name}",
            "mr_id": mr_id,
            "status_id": body.new_status_id,
            "status_name": status_name,
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error changing MR status")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# APPROVAL WORKFLOW SCHEMAS
# =============================================================================

class MRApprovalRequest(BaseModel):
    """Request model for MR approval actions."""
    mr_id: str
    branch_id: str
    reason: Optional[str] = None  # For reject action
    party_branch_id: Optional[int] = None  # For approve action - use if provided
    mr_date: Optional[str] = None  # For approve action - YYYY-MM-DD format, mandatory for final approval
    menu_id: Optional[int] = None  # For multi-level approval via shared utility


# =============================================================================
# MR STATUS CONSTANTS
# =============================================================================

MR_STATUS_DRAFT = 21
MR_STATUS_OPEN = 1
MR_STATUS_PENDING = 13
MR_STATUS_PENDING_APPROVAL = 20
MR_STATUS_APPROVED = 3
MR_STATUS_REJECTED = 4
MR_STATUS_CANCELLED = 6


# =============================================================================
# APPROVAL WORKFLOW ENDPOINTS
# =============================================================================

def get_next_branch_mr_no(db: Session, branch_id: int) -> int:
    """Get the next branch_mr_no for the given branch (simple increment, no FY)."""
    query = text("""
        SELECT COALESCE(MAX(branch_mr_no), 0) + 1 AS next_no
        FROM jute_mr
        WHERE branch_id = :branch_id
    """)
    result = db.execute(query, {"branch_id": branch_id}).fetchone()
    return result[0] if result else 1


def get_next_mr_no_for_fy(db: Session, branch_id: int, mr_date: date) -> int:
    """
    Get the next MR number for the given branch and financial year.
    
    MR numbering is per branch per financial year.
    Financial year: April 1 to March 31.
    
    Args:
        db: Database session
        branch_id: Branch ID
        mr_date: MR date to determine the financial year
    
    Returns:
        Next MR number (1-based)
    """
    # Build the financial year SQL expression for jute_mr_date
    fy_expr = get_financial_year_sql_expression("jute_mr_date")
    
    # Determine the current financial year from mr_date
    if mr_date.month >= 4:  # April onwards
        fy_start_year = mr_date.year
    else:  # January to March
        fy_start_year = mr_date.year - 1
    
    fy_string = f"{fy_start_year % 100:02d}-{(fy_start_year + 1) % 100:02d}"
    
    query = text(f"""
        SELECT COALESCE(MAX(branch_mr_no), 0) + 1 AS next_no
        FROM jute_mr
        WHERE branch_id = :branch_id
          AND jute_mr_date IS NOT NULL
          AND {fy_expr} = :fy_string
    """)
    
    result = db.execute(query, {"branch_id": branch_id, "fy_string": fy_string}).fetchone()
    return result[0] if result else 1


def get_next_bill_pass_no_for_fy(db: Session, branch_id: int, bill_pass_date: date) -> int:
    """
    Get the next Bill Pass number for the given branch and financial year.
    
    Bill Pass numbering is per branch per financial year.
    Financial year: April 1 to March 31.
    
    Args:
        db: Database session
        branch_id: Branch ID
        bill_pass_date: Bill Pass date to determine the financial year
    
    Returns:
        Next Bill Pass number (1-based)
    """
    # Build the financial year SQL expression for bill_pass_date
    fy_expr = get_financial_year_sql_expression("bill_pass_date")
    
    # Determine the current financial year from bill_pass_date
    if bill_pass_date.month >= 4:  # April onwards
        fy_start_year = bill_pass_date.year
    else:  # January to March
        fy_start_year = bill_pass_date.year - 1
    
    fy_string = f"{fy_start_year % 100:02d}-{(fy_start_year + 1) % 100:02d}"
    
    query = text(f"""
        SELECT COALESCE(MAX(bill_pass_no), 0) + 1 AS next_no
        FROM jute_mr
        WHERE branch_id = :branch_id
          AND bill_pass_date IS NOT NULL
          AND {fy_expr} = :fy_string
    """)
    
    result = db.execute(query, {"branch_id": branch_id, "fy_string": fy_string}).fetchone()
    return result[0] if result else 1


# =============================================================================
# TDS CALCULATION HELPERS
# =============================================================================

# TDS threshold: Rs. 50 lacs (50,00,000)
TDS_THRESHOLD = 5000000.0

# TDS rate: 0.1% (0.001)
TDS_RATE = 0.001


def get_cumulative_mr_value_for_party_in_fy(db: Session, party_id: str, mr_date: date, exclude_mr_id: int = None) -> float:
    """
    Get the cumulative value of all approved MRs for a party in the given financial year.
    
    Args:
        db: Database session
        party_id: Party ID
        mr_date: MR date to determine the financial year
        exclude_mr_id: MR ID to exclude from the calculation (for current MR)
    
    Returns:
        Total value of approved MRs for the party in the FY (uses total_amount column)
    """
    # Build the financial year SQL expression for jute_mr_date
    fy_expr = get_financial_year_sql_expression("jute_mr_date")
    
    # Determine the current financial year from mr_date
    if mr_date.month >= 4:  # April onwards
        fy_start_year = mr_date.year
    else:  # January to March
        fy_start_year = mr_date.year - 1
    
    fy_string = f"{fy_start_year % 100:02d}-{(fy_start_year + 1) % 100:02d}"
    
    exclude_clause = ""
    params = {"party_id": party_id, "fy_string": fy_string, "status_approved": MR_STATUS_APPROVED}
    
    if exclude_mr_id:
        exclude_clause = "AND jute_mr_id != :exclude_mr_id"
        params["exclude_mr_id"] = exclude_mr_id
    
    query = text(f"""
        SELECT COALESCE(SUM(COALESCE(total_amount, 0)), 0) AS cumulative_value
        FROM jute_mr
        WHERE party_id = :party_id
          AND status_id = :status_approved
          AND jute_mr_date IS NOT NULL
          AND {fy_expr} = :fy_string
          {exclude_clause}
    """)
    
    result = db.execute(query, params).fetchone()
    return float(result[0]) if result and result[0] else 0.0


def calculate_mr_amounts(db: Session, mr_id: int) -> dict:
    """
    Calculate total_amount, claim_amount for an MR from its line items.
    
    Formulas:
    - total_amount = sum of (accepted_weight / 100) * rate  [weight in KG, rate per quintal]
    - claim_amount = sum of (accepted_weight / 100) * claim_rate
    
    Returns:
        dict with total_amount and claim_amount
    """
    query = text("""
        SELECT 
            COALESCE(SUM((COALESCE(accepted_weight, actual_weight, 0) / 100) * COALESCE(rate, 0)), 0) AS total_amount,
            COALESCE(SUM((COALESCE(accepted_weight, actual_weight, 0) / 100) * COALESCE(claim_rate, 0)), 0) AS claim_amount
        FROM jute_mr_li
        WHERE jute_mr_id = :mr_id
          AND (active = 1 OR active IS NULL)
    """)
    
    result = db.execute(query, {"mr_id": mr_id}).fetchone()
    
    if result:
        return {
            "total_amount": float(result[0]) if result[0] else 0.0,
            "claim_amount": float(result[1]) if result[1] else 0.0,
        }
    return {"total_amount": 0.0, "claim_amount": 0.0}


def calculate_tds_amount(cumulative_previous: float, current_total: float) -> tuple:
    """
    Calculate TDS amount based on cumulative MR value and threshold.
    
    TDS Logic:
    - TDS is 0.1% of the net total
    - TDS applies only if cumulative MR value for the party in FY exceeds Rs. 50 lacs
    - If crossing threshold with current bill, TDS applies only on amount exceeding threshold
    
    Args:
        cumulative_previous: Sum of all previous approved MRs for the party in FY
        current_total: Total amount of the current MR
    
    Returns:
        tuple: (tds_amount, tds_applicable_amount, is_tds_applicable)
    """
    cumulative_after = cumulative_previous + current_total
    
    # If cumulative (including current) is below threshold, no TDS
    if cumulative_after <= TDS_THRESHOLD:
        return (0.0, 0.0, False)
    
    # Calculate the amount on which TDS applies
    if cumulative_previous >= TDS_THRESHOLD:
        # Already crossed threshold - TDS on full current amount
        tds_applicable_amount = current_total
    else:
        # Crossing threshold with this MR - TDS only on amount exceeding threshold
        tds_applicable_amount = cumulative_after - TDS_THRESHOLD
    
    tds_amount = round(tds_applicable_amount * TDS_RATE, 2)
    
    return (tds_amount, tds_applicable_amount, True)


def calculate_roundoff(amount: float) -> float:
    """
    Calculate roundoff to nearest rupee.
    
    Returns the roundoff adjustment (can be positive or negative).
    """
    rounded = round(amount)
    return round(rounded - amount, 2)


@router.post("/open_mr")
def open_mr(
    request: Request,
    body: MRApprovalRequest,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Open MR - Changes status from Draft (21) to Open (1).
    Validates that party_id and party_branch_id are set.
    """
    try:
        mr_id = int(body.mr_id)
        user_id = token_data.get("user_id")

        if not user_id:
            raise HTTPException(status_code=401, detail="User not authenticated")

        # Get current MR details
        check_query = text("""
            SELECT jute_mr_id, status_id, party_id, party_branch_id
            FROM jute_mr
            WHERE jute_mr_id = :mr_id
        """)
        mr_row = db.execute(check_query, {"mr_id": mr_id}).fetchone()

        if not mr_row:
            raise HTTPException(status_code=404, detail=f"MR with id {mr_id} not found")

        mr = dict(mr_row._mapping)
        current_status = mr.get("status_id")
        party_id = mr.get("party_id")
        party_branch_id = mr.get("party_branch_id")

        # Validate current status - can only open from Draft
        if current_status != MR_STATUS_DRAFT:
            raise HTTPException(status_code=400, detail="MR can only be opened from Draft status")

        # Validate party_id is set
        if not party_id:
            raise HTTPException(
                status_code=400,
                detail="Cannot open MR: Party must be selected before opening."
            )

        # Validate party_branch_id is set
        if not party_branch_id:
            raise HTTPException(
                status_code=400,
                detail="Cannot open MR: Party branch must be selected before opening. Please add a branch for this party in Party Master if none exist."
            )

        now = now_ist()

        # Update status to Open
        update_query = text("""
            UPDATE jute_mr
            SET status_id = :new_status,
                updated_by = :updated_by,
                updated_date_time = :updated_date_time
            WHERE jute_mr_id = :mr_id
        """)

        db.execute(update_query, {
            "mr_id": mr_id,
            "new_status": MR_STATUS_OPEN,
            "updated_by": user_id,
            "updated_date_time": now,
        })

        db.commit()

        return {
            "success": True,
            "message": "MR opened successfully",
            "mr_id": mr_id,
            "status_id": MR_STATUS_OPEN,
            "status_name": "Open",
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error opening MR")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/pending_mr")
def pending_mr(
    request: Request,
    body: MRApprovalRequest,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Set MR to Pending status (13).
    This is a terminal state on this screen - handled by external system.
    Can only be done from Open status.
    """
    try:
        mr_id = int(body.mr_id)
        user_id = token_data.get("user_id")

        if not user_id:
            raise HTTPException(status_code=401, detail="User not authenticated")

        # Get current MR details
        check_query = text("""
            SELECT jute_mr_id, status_id
            FROM jute_mr
            WHERE jute_mr_id = :mr_id
        """)
        mr_row = db.execute(check_query, {"mr_id": mr_id}).fetchone()
        
        if not mr_row:
            raise HTTPException(status_code=404, detail=f"MR with id {mr_id} not found")

        mr = dict(mr_row._mapping)
        current_status = mr.get("status_id")

        # Validate current status. Pending is a top-of-hierarchy action shown
        # by the UI only to the highest-level approver, so the MR may be Open
        # (single-level) or already walking the approval levels (Pending Approval).
        if current_status not in (MR_STATUS_OPEN, MR_STATUS_PENDING_APPROVAL):
            raise HTTPException(
                status_code=400,
                detail="MR can only be set to Pending from Open or Pending Approval status",
            )

        now = now_ist()

        # Update status to Pending
        update_query = text("""
            UPDATE jute_mr
            SET status_id = :new_status,
                updated_by = :updated_by,
                updated_date_time = :updated_date_time
            WHERE jute_mr_id = :mr_id
        """)
        
        db.execute(update_query, {
            "mr_id": mr_id,
            "new_status": MR_STATUS_PENDING,
            "updated_by": user_id,
            "updated_date_time": now,
        })

        db.commit()

        return {
            "success": True,
            "message": "MR set to Pending",
            "mr_id": mr_id,
            "status_id": MR_STATUS_PENDING,
            "status_name": "Pending",
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error setting MR to pending")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/approve_mr")
def approve_mr(
    request: Request,
    body: MRApprovalRequest,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Approve MR - Changes status to Approved (3) or advances approval level.
    Can only be done from Open (1) or Pending Approval (20) status.

    If party_branch_id is provided in the request, it will be used to update the MR
    before approval (handles case where branch was selected but not saved).

    For final approval:
    - mr_date is MANDATORY (YYYY-MM-DD format)
    - branch_mr_no will be auto-generated based on branch + financial year

    When menu_id is provided, uses the shared approval utility for multi-level
    approval hierarchy support. When menu_id is omitted, falls back to direct
    approval (backward compatible).
    """
    try:
        mr_id = int(body.mr_id)
        branch_id = int(body.branch_id)
        user_id = token_data.get("user_id")
        request_party_branch_id = body.party_branch_id
        request_mr_date = body.mr_date
        menu_id = body.menu_id

        if not user_id:
            raise HTTPException(status_code=401, detail="User not authenticated")

        # Get current MR details
        check_query = text("""
            SELECT jute_mr_id, status_id, party_id, party_branch_id, branch_id,
                   branch_mr_no, jute_mr_date
            FROM jute_mr
            WHERE jute_mr_id = :mr_id
        """)
        mr_row = db.execute(check_query, {"mr_id": mr_id}).fetchone()

        if not mr_row:
            raise HTTPException(status_code=404, detail=f"MR with id {mr_id} not found")

        mr = dict(mr_row._mapping)
        current_status = mr.get("status_id")
        party_id = mr.get("party_id")
        db_party_branch_id = mr.get("party_branch_id")
        db_branch_id = mr.get("branch_id")
        db_branch_mr_no = mr.get("branch_mr_no")

        # Use request party_branch_id if provided, otherwise use database value
        effective_party_branch_id = (
            request_party_branch_id
            if request_party_branch_id is not None
            else db_party_branch_id
        )

        # Validate current status
        if current_status not in [MR_STATUS_OPEN, MR_STATUS_PENDING_APPROVAL]:
            raise HTTPException(
                status_code=400,
                detail="MR can only be approved from Open or Pending Approval status",
            )

        # Validate party_branch_id (using effective value)
        if party_id and not effective_party_branch_id:
            raise HTTPException(
                status_code=400,
                detail="Cannot approve MR: Please select a party branch before approving.",
            )

        now = now_ist()

        # Determine approval status via shared utility or direct approval
        if menu_id is not None:
            # Use shared approval utility for multi-level approval
            approval_result = process_approval(
                doc_id=mr_id,
                user_id=user_id,
                menu_id=menu_id,
                db=db,
                get_doc_fn=get_mr_with_approval_info,
                update_status_fn=update_mr_status,
                id_param_name="jute_mr_id",
                doc_name="MR",
                document_amount=None,  # Jute never checks values
                # Defer the commit: on final approval this endpoint then
                # generates branch_mr_no / bill_pass_no / amounts and commits
                # once, so the status change and those writes stay atomic. If
                # that second phase raises, the whole approval rolls back.
                commit=False,
            )
            new_status = approval_result["new_status_id"]
            is_final_approval = new_status == MR_STATUS_APPROVED
        else:
            # Backward compatible: direct approval (no approval hierarchy)
            is_final_approval = True
            new_status = MR_STATUS_APPROVED

        # For final approval, mr_date is MANDATORY
        if is_final_approval:
            if not request_mr_date:
                raise HTTPException(
                    status_code=400,
                    detail="MR Date is required for final approval. Please enter the MR date.",
                )

            # Parse and validate mr_date
            try:
                parsed_mr_date = datetime.strptime(request_mr_date, "%Y-%m-%d").date()
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid MR date format. Please use YYYY-MM-DD format.",
                )

            # Generate MR number based on branch + financial year if not already set
            if not db_branch_mr_no:
                new_branch_mr_no = get_next_mr_no_for_fy(db, db_branch_id, parsed_mr_date)
            else:
                new_branch_mr_no = db_branch_mr_no
        else:
            # Not final approval - mr_date is optional
            parsed_mr_date = None
            new_branch_mr_no = db_branch_mr_no
            if request_mr_date:
                try:
                    parsed_mr_date = datetime.strptime(request_mr_date, "%Y-%m-%d").date()
                except ValueError:
                    pass  # Ignore invalid date for non-final approval

        # Build update query for business data fields
        # Note: status_id and approval_level are already set by process_approval()
        # when menu_id is provided. For backward compat (no menu_id), we set status here.
        update_fields = ["updated_by = :updated_by", "updated_date_time = :updated_date_time"]
        update_params = {
            "mr_id": mr_id,
            "updated_by": user_id,
            "updated_date_time": now,
        }

        # When menu_id is not provided, we must set the status ourselves
        if menu_id is None:
            update_fields.append("status_id = :new_status")
            update_params["new_status"] = new_status

        # Add party_branch_id if changed
        if request_party_branch_id is not None and request_party_branch_id != db_party_branch_id:
            update_fields.append("party_branch_id = :party_branch_id")
            update_params["party_branch_id"] = request_party_branch_id

        # Add mr_date if provided for final approval
        if is_final_approval and parsed_mr_date:
            update_fields.append("jute_mr_date = :jute_mr_date")
            update_params["jute_mr_date"] = parsed_mr_date

        # Add branch_mr_no if generated
        if is_final_approval and new_branch_mr_no and new_branch_mr_no != db_branch_mr_no:
            update_fields.append("branch_mr_no = :branch_mr_no")
            update_params["branch_mr_no"] = new_branch_mr_no

        # For final approval, also set bill_pass_date = mr_date and generate bill_pass_no
        new_bill_pass_no = None
        calculated_amounts = {}
        if is_final_approval and parsed_mr_date:
            # bill_pass_date = jute_mr_date (same date)
            update_fields.append("bill_pass_date = :bill_pass_date")
            update_params["bill_pass_date"] = parsed_mr_date

            # Generate bill_pass_no based on branch + financial year
            new_bill_pass_no = get_next_bill_pass_no_for_fy(db, db_branch_id, parsed_mr_date)
            update_fields.append("bill_pass_no = :bill_pass_no")
            update_params["bill_pass_no"] = new_bill_pass_no

            # Calculate amounts from line items
            mr_amounts = calculate_mr_amounts(db, mr_id)
            total_amount = mr_amounts["total_amount"]
            claim_amount = mr_amounts["claim_amount"]

            # Calculate TDS based on cumulative party MR value in FY
            tds_amount = 0.0
            tds_applicable_amount = 0.0
            is_tds_applicable = False
            cumulative_previous = 0.0

            if party_id:
                cumulative_previous = get_cumulative_mr_value_for_party_in_fy(
                    db, party_id, parsed_mr_date, exclude_mr_id=mr_id
                )
                tds_amount, tds_applicable_amount, is_tds_applicable = calculate_tds_amount(
                    cumulative_previous, total_amount
                )

            # Net total = total_amount - claim_amount - tds_amount + roundoff
            # (TDS is deducted — owner decision 2; shared helper keeps this in
            # sync with billPass.py and the accounting posting service)
            roundoff, net_total = compute_jute_totals(total_amount, claim_amount, tds_amount)

            # Store all calculated amounts
            update_fields.append("total_amount = :total_amount")
            update_params["total_amount"] = total_amount

            update_fields.append("claim_amount = :claim_amount")
            update_params["claim_amount"] = claim_amount

            update_fields.append("roundoff = :roundoff")
            update_params["roundoff"] = roundoff

            update_fields.append("net_total = :net_total")
            update_params["net_total"] = net_total

            update_fields.append("tds_amount = :tds_amount")
            update_params["tds_amount"] = tds_amount

            calculated_amounts = {
                "total_amount": total_amount,
                "claim_amount": claim_amount,
                "roundoff": roundoff,
                "net_total": net_total,
                "tds_amount": tds_amount,
                "tds_applicable_amount": tds_applicable_amount,
                "is_tds_applicable": is_tds_applicable,
                "cumulative_previous": cumulative_previous,
                "cumulative_after": cumulative_previous + total_amount,
                "tds_threshold": TDS_THRESHOLD,
            }

        update_query = text(f"""
            UPDATE jute_mr
            SET {', '.join(update_fields)}
            WHERE jute_mr_id = :mr_id
        """)

        db.execute(update_query, update_params)
        db.commit()

        # Fetch company and branch prefix for formatted document numbers
        mr_num = None
        bill_pass_num = None
        prefix_result = db.execute(
            text("""
                SELECT cm.co_prefix, bm.branch_prefix
                FROM branch_mst bm
                INNER JOIN co_mst cm ON cm.co_id = bm.co_id
                WHERE bm.branch_id = :branch_id
            """),
            {"branch_id": db_branch_id},
        ).fetchone()

        co_prefix = prefix_result.co_prefix if prefix_result else None
        branch_prefix = prefix_result.branch_prefix if prefix_result else None

        if new_branch_mr_no and parsed_mr_date:
            mr_num = format_jute_mr_number(new_branch_mr_no, parsed_mr_date, co_prefix, branch_prefix)
        if new_bill_pass_no and parsed_mr_date:
            bill_pass_num = format_jute_bill_pass_number(
                new_bill_pass_no, parsed_mr_date, co_prefix, branch_prefix
            )

        response = {
            "success": True,
            "message": "MR approved successfully" if is_final_approval else "MR moved to next approval level",
            "mr_id": mr_id,
            "status_id": new_status,
            "status_name": "Approved" if is_final_approval else "Pending Approval",
            "branch_mr_no": new_branch_mr_no,
            "mr_num": mr_num,
            "jute_mr_date": str(parsed_mr_date) if parsed_mr_date else None,
            "bill_pass_no": new_bill_pass_no,
            "bill_pass_num": bill_pass_num,
            "bill_pass_date": str(parsed_mr_date) if parsed_mr_date else None,
            "calculated_amounts": calculated_amounts,
        }

        return response

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error approving MR")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reject_mr")
def reject_mr(
    request: Request,
    body: MRApprovalRequest,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Reject MR - Changes status to Rejected (4).
    Can only be done from Open (1) or Pending Approval (20) status.

    When menu_id is provided, uses the shared rejection utility for
    level-based permission checks. When omitted, falls back to direct
    rejection (backward compatible).
    """
    try:
        mr_id = int(body.mr_id)
        user_id = token_data.get("user_id")
        reason = body.reason or ""
        menu_id = body.menu_id

        if not user_id:
            raise HTTPException(status_code=401, detail="User not authenticated")

        if menu_id is not None:
            # Use shared rejection utility for level-based permission checks
            process_rejection(
                doc_id=mr_id,
                user_id=user_id,
                menu_id=menu_id,
                db=db,
                get_doc_fn=get_mr_with_approval_info,
                update_status_fn=update_mr_status,
                id_param_name="jute_mr_id",
                doc_name="MR",
                reason=reason,
            )
        else:
            # Backward compatible: direct rejection without hierarchy checks
            check_query = text("""
                SELECT jute_mr_id, status_id
                FROM jute_mr
                WHERE jute_mr_id = :mr_id
            """)
            mr_row = db.execute(check_query, {"mr_id": mr_id}).fetchone()

            if not mr_row:
                raise HTTPException(status_code=404, detail=f"MR with id {mr_id} not found")

            mr = dict(mr_row._mapping)
            current_status = mr.get("status_id")

            if current_status not in [MR_STATUS_OPEN, MR_STATUS_PENDING_APPROVAL]:
                raise HTTPException(
                    status_code=400,
                    detail="MR can only be rejected from Open or Pending Approval status",
                )

            now = now_ist()
            update_query = text("""
                UPDATE jute_mr
                SET status_id = :new_status,
                    approval_level = NULL,
                    updated_by = :updated_by,
                    updated_date_time = :updated_date_time
                WHERE jute_mr_id = :mr_id
            """)
            db.execute(update_query, {
                "mr_id": mr_id,
                "new_status": MR_STATUS_REJECTED,
                "updated_by": user_id,
                "updated_date_time": now,
            })
            db.commit()

        # Append rejection reason to remarks (both paths)
        if reason:
            remarks_query = text("""
                UPDATE jute_mr
                SET remarks = CONCAT(COALESCE(remarks, ''), ' [Rejected: ', :reason, ']')
                WHERE jute_mr_id = :mr_id
            """)
            db.execute(remarks_query, {"mr_id": mr_id, "reason": reason})
            db.commit()

        return {
            "success": True,
            "message": "MR rejected",
            "mr_id": mr_id,
            "status_id": MR_STATUS_REJECTED,
            "status_name": "Rejected",
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error rejecting MR")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cancel_mr")
def cancel_mr(
    request: Request,
    body: MRApprovalRequest,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Cancel MR - Changes status to Cancelled (6).
    Can only be done from Open (1) status.
    """
    try:
        mr_id = int(body.mr_id)
        user_id = token_data.get("user_id")

        if not user_id:
            raise HTTPException(status_code=401, detail="User not authenticated")

        # Get current MR details
        check_query = text("""
            SELECT jute_mr_id, status_id
            FROM jute_mr
            WHERE jute_mr_id = :mr_id
        """)
        mr_row = db.execute(check_query, {"mr_id": mr_id}).fetchone()
        
        if not mr_row:
            raise HTTPException(status_code=404, detail=f"MR with id {mr_id} not found")

        mr = dict(mr_row._mapping)
        current_status = mr.get("status_id")

        # Validate current status - can only cancel from Open
        if current_status != MR_STATUS_OPEN:
            raise HTTPException(status_code=400, detail="Only Open MRs can be cancelled")

        now = now_ist()

        # Update status to Cancelled
        update_query = text("""
            UPDATE jute_mr
            SET status_id = :new_status,
                updated_by = :updated_by,
                updated_date_time = :updated_date_time
            WHERE jute_mr_id = :mr_id
        """)
        
        db.execute(update_query, {
            "mr_id": mr_id,
            "new_status": MR_STATUS_CANCELLED,
            "updated_by": user_id,
            "updated_date_time": now,
        })

        db.commit()

        return {
            "success": True,
            "message": "MR cancelled",
            "mr_id": mr_id,
            "status_id": MR_STATUS_CANCELLED,
            "status_name": "Cancelled",
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error cancelling MR")
        raise HTTPException(status_code=500, detail=str(e))
