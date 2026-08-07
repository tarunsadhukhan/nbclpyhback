"""
Material Inspection API endpoints.
Handles quality check of received goods - update accepted/rejected quantities.
"""
import logging
from datetime import datetime, date
from src.common.utils import now_ist
from fastapi import Depends, Request, HTTPException, APIRouter
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List

from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.procurement.query import (
    get_pending_inspection_list_query,
    get_pending_inspection_count_query,
    get_inward_for_inspection_query,
    get_inward_dtl_for_inspection_query,
    update_inward_dtl_inspection,
    update_inward_inspection_complete,
)
from src.procurement.inward import format_inward_no
from src.procurement.po import extract_formatted_po_no

logger = logging.getLogger(__name__)

router = APIRouter()


# =============================================================================
# PYDANTIC MODELS
# =============================================================================

class InspectionLineItemUpdate(BaseModel):
    """Model for updating a single line item during inspection."""
    inward_dtl_id: int
    approved_qty: Optional[float] = None  # Optional - will be calculated if not provided
    rejected_qty: float = 0
    accepted_item_make_id: Optional[int] = None
    reasons: Optional[str] = None
    remarks: Optional[str] = None


class InspectionCompleteRequest(BaseModel):
    """Request body for completing material inspection."""
    inward_id: int
    line_items: List[InspectionLineItemUpdate]


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.get("/get_pending_inspection_list")
def get_pending_inspection_list(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    page: int = 1,
    limit: int = 10,
    search: str | None = None,
    co_id: int | None = None,
):
    """Return paginated list of inwards pending material inspection."""
    try:
        page = max(page, 1)
        limit = max(min(limit, 100), 1)
        offset = (page - 1) * limit
        search_like = f"%{search.strip()}%" if search else None

        params = {
            "co_id": co_id,
            "search_like": search_like,
            "limit": limit,
            "offset": offset,
        }

        list_query = get_pending_inspection_list_query()
        rows = db.execute(list_query, params).fetchall()
        
        data = []
        for row in rows:
            mapped = dict(row._mapping)
            
            # Format inward date
            inward_date_obj = mapped.get("inward_date")
            inward_date = inward_date_obj
            if hasattr(inward_date_obj, "isoformat"):
                inward_date = inward_date_obj.isoformat()
            
            # Format inspection date
            inspection_date_obj = mapped.get("material_inspection_date")
            inspection_date = None
            if inspection_date_obj and hasattr(inspection_date_obj, "isoformat"):
                inspection_date = inspection_date_obj.isoformat()
            
            # Format GRN/Inward number
            raw_inward_no = mapped.get("inward_sequence_no")
            formatted_inward_no = ""
            if raw_inward_no is not None and raw_inward_no != 0:
                try:
                    inward_no_int = int(raw_inward_no) if raw_inward_no else None
                    co_prefix = mapped.get("co_prefix")
                    branch_prefix = mapped.get("branch_prefix")
                    formatted_inward_no = format_inward_no(
                        inward_sequence_no=inward_no_int,
                        co_prefix=co_prefix,
                        branch_prefix=branch_prefix,
                        inward_date=inward_date_obj,
                    )
                except Exception:
                    logger.exception("Error formatting Inward number")
                    formatted_inward_no = str(raw_inward_no) if raw_inward_no else ""
            
            data.append({
                "inward_id": mapped.get("inward_id"),
                "inward_no": formatted_inward_no,
                "inward_date": inward_date,
                "branch_id": mapped.get("branch_id"),
                "branch_name": mapped.get("branch_name") or "",
                "supplier_id": mapped.get("supplier_id"),
                "supplier_name": mapped.get("supplier_name") or "",
                "inspection_check": mapped.get("inspection_check"),
                "material_inspection_date": inspection_date,
                "sr_status_name": mapped.get("sr_status_name") or "Pending",
            })

        count_query = get_pending_inspection_count_query()
        count_result = db.execute(count_query, params).scalar()
        total = int(count_result) if count_result is not None else 0

        return {"data": data, "total": total}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching pending inspection list")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/get_inspection_by_inward_id/{inward_id}")
def get_inspection_by_inward_id(
    inward_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    co_id: int | None = None,
):
    """Get inward header and line items for material inspection."""
    try:
        # Get header
        header_query = get_inward_for_inspection_query()
        header_result = db.execute(header_query, {"inward_id": inward_id, "co_id": co_id}).fetchone()
        
        if not header_result:
            raise HTTPException(status_code=404, detail="Inward not found")
        
        header = dict(header_result._mapping)
        
        # Format inward number
        inward_date_obj = header.get("inward_date")
        raw_inward_no = header.get("inward_sequence_no")
        formatted_inward_no = ""
        if raw_inward_no is not None and raw_inward_no != 0:
            formatted_inward_no = format_inward_no(
                inward_sequence_no=int(raw_inward_no),
                co_prefix=header.get("co_prefix"),
                branch_prefix=header.get("branch_prefix"),
                inward_date=inward_date_obj,
            )
        
        # Format dates
        inward_date = inward_date_obj.isoformat() if hasattr(inward_date_obj, "isoformat") else inward_date_obj
        inspection_date_obj = header.get("material_inspection_date")
        inspection_date = inspection_date_obj.isoformat() if inspection_date_obj and hasattr(inspection_date_obj, "isoformat") else None
        challan_date_obj = header.get("challan_date")
        challan_date = challan_date_obj.isoformat() if challan_date_obj and hasattr(challan_date_obj, "isoformat") else None
        
        # Get line items
        dtl_query = get_inward_dtl_for_inspection_query()
        dtl_result = db.execute(dtl_query, {"inward_id": inward_id}).fetchall()
        
        line_items = []
        for row in dtl_result:
            item = dict(row._mapping)
            item["po_no_formatted"] = extract_formatted_po_no(item) if item.get("po_no") else ""
            # Default approved_qty to inward_qty if not set
            if item.get("approved_qty") is None:
                item["approved_qty"] = item.get("inward_qty") or 0
            if item.get("rejected_qty") is None:
                item["rejected_qty"] = 0
            line_items.append(item)
        
        return {
            "header": {
                "inward_id": header.get("inward_id"),
                "inward_no": formatted_inward_no,
                "inward_date": inward_date,
                "branch_id": header.get("branch_id"),
                "branch_name": header.get("branch_name") or "",
                "supplier_id": header.get("supplier_id"),
                "supplier_name": header.get("supplier_name") or "",
                "inspection_check": header.get("inspection_check"),
                "material_inspection_date": inspection_date,
                "challan_no": header.get("challan_no") or "",
                "challan_date": challan_date,
            },
            "line_items": line_items,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching inward for inspection")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("/complete_inspection")
def complete_inspection(
    request_body: InspectionCompleteRequest,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Complete material inspection for an inward.
    Updates line items with approved_qty, rejected_qty, accepted_item_make_id, reasons.
    Sets inspection_check = true and material_inspection_date = today.
    """
    try:
        user_id = token_data.get("user_id")
        if not user_id:
            raise HTTPException(status_code=401, detail="User ID not found in token")
        
        now = now_ist()
        today = date.today()
        
        # Get current line item data to calculate approved_qty if not provided
        dtl_query = get_inward_dtl_for_inspection_query()
        dtl_result = db.execute(dtl_query, {"inward_id": request_body.inward_id}).fetchall()
        inward_qty_by_dtl_id = {row._mapping["inward_dtl_id"]: row._mapping["inward_qty"] for row in dtl_result}
        
        # Update each line item
        for line in request_body.line_items:
            # Calculate approved_qty if not provided
            approved_qty = line.approved_qty
            if approved_qty is None:
                inward_qty = inward_qty_by_dtl_id.get(line.inward_dtl_id, 0)
                approved_qty = inward_qty - (line.rejected_qty or 0)
            
            update_query = update_inward_dtl_inspection()
            db.execute(update_query, {
                "inward_dtl_id": line.inward_dtl_id,
                "approved_qty": approved_qty,
                "rejected_qty": line.rejected_qty,
                "accepted_item_make_id": line.accepted_item_make_id,
                "reasons": line.reasons,
                "remarks": line.remarks,
                "updated_by": user_id,
                "updated_date_time": now,
            })
        
        # Mark inward as inspection complete
        complete_query = update_inward_inspection_complete()
        db.execute(complete_query, {
            "inward_id": request_body.inward_id,
            "inspection_date": today,
            "inspection_approved_by": user_id,
            "updated_by": user_id,
            "updated_date_time": now,
        })
        
        db.commit()
        
        return {
            "success": True,
            "message": "Material inspection completed successfully",
            "inward_id": request_body.inward_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error completing inspection")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
