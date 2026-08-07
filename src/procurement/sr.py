"""
Stores Receipt (SR) API endpoints.
Handles accountant review of inspected goods, adds rates/taxes, creates official receipt.
"""
import logging
from datetime import datetime, date
from src.common.utils import now_ist
from fastapi import Depends, Request, HTTPException, APIRouter
from sqlalchemy.orm import Session
from sqlalchemy import text
from pydantic import BaseModel
from typing import Optional, List

from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.procurement.query import (
    get_sr_pending_list_query,
    get_sr_pending_count_query,
    get_inward_for_sr_query,
    get_inward_dtl_for_sr_query,
    update_inward_dtl_sr,
    update_inward_sr,
    insert_drcr_note,
    insert_drcr_note_dtl,
    insert_drcr_note_dtl_gst,
    get_additional_charges_mst_list,
    get_inward_additional_charges_query,
    insert_inward_additional,
    delete_inward_additional_by_inward,
    insert_proc_gst,
    delete_proc_gst_by_inward,
    delete_proc_gst_for_sr_additional_charges,
    get_po_additional_with_tax_by_id_query,
    count_active_po_dtl_query,
    get_inward_line_tax_pct_query,
    get_supplier_branches_for_gst_query,
)
from src.procurement.po import calculate_gst_amounts, extract_formatted_po_no
from src.common.companyAdmin.query import get_co_config_by_id_query
from src.procurement.inward import format_inward_no
from src.procurement.indent import calculate_financial_year

logger = logging.getLogger(__name__)

router = APIRouter()


# Status IDs for approval workflow
STATUS_DRAFT = 21
STATUS_OPEN = 1
STATUS_PENDING_APPROVAL = 20
STATUS_APPROVED = 3
STATUS_REJECTED = 4

# DRCR Note types
DRCR_TYPE_DEBIT = 1  # Supplier owes us (rate decrease, rejected qty)
DRCR_TYPE_CREDIT = 2  # We owe supplier (rate increase)


# =============================================================================
# PYDANTIC MODELS
# =============================================================================

class SRLineItemUpdate(BaseModel):
    """Model for updating a single line item during SR."""
    inward_dtl_id: int
    accepted_rate: float
    amount: Optional[float] = None
    discount_mode: Optional[int] = None
    discount_value: Optional[float] = None
    discount_amount: Optional[float] = None
    warehouse_id: Optional[int] = None
    hsn_code: Optional[str] = None
    # GST fields
    tax_percentage: Optional[float] = None
    igst_amount: Optional[float] = None
    cgst_amount: Optional[float] = None
    sgst_amount: Optional[float] = None
    tax_amount: Optional[float] = None


class SRAdditionalChargeUpdate(BaseModel):
    """Model for an additional charge in SR."""
    inward_additional_id: Optional[int] = None  # None for new charges
    additional_charges_id: int
    qty: int = 1
    rate: float
    net_amount: Optional[float] = None
    remarks: Optional[str] = None
    # Optional tax fields
    apply_tax: bool = False
    tax_pct: Optional[float] = None
    igst_amount: Optional[float] = None
    sgst_amount: Optional[float] = None
    cgst_amount: Optional[float] = None
    tax_amount: Optional[float] = None


class SRSaveRequest(BaseModel):
    """Request body for saving SR."""
    inward_id: int
    sr_date: str
    sr_remarks: Optional[str] = None
    supplier_branch_id: Optional[int] = None
    bill_branch_id: Optional[int] = None
    ship_branch_id: Optional[int] = None
    # Inward-level fields that can be corrected from the SR screen.
    # Date fields arrive as 'YYYY-MM-DD' strings and are parsed before UPDATE.
    invoice_no: Optional[str] = None
    invoice_date: Optional[str] = None
    invoice_amount: Optional[float] = None
    invoice_recvd_date: Optional[str] = None
    challan_no: Optional[str] = None
    challan_date: Optional[str] = None
    vehicle_number: Optional[str] = None
    driver_name: Optional[str] = None
    driver_contact_no: Optional[str] = None
    inspection_date: Optional[str] = None
    consignment_no: Optional[str] = None
    consignment_date: Optional[str] = None
    ewaybillno: Optional[str] = None
    ewaybill_date: Optional[str] = None
    despatch_remarks: Optional[str] = None
    receipts_remarks: Optional[str] = None
    line_items: List[SRLineItemUpdate]
    additional_charges: Optional[List[SRAdditionalChargeUpdate]] = None


class SRApproveRequest(BaseModel):
    """Request body for approving/rejecting SR."""
    inward_id: int
    reason: Optional[str] = None


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def generate_sr_no(db: Session, branch_id: int, sr_date) -> str:
    """Generate next SR number for the branch and financial year.

    Format matches Inward: 'co_prefix/branch_prefix/SR/FY/sequence_no'.
    Sequence is a per-branch per-financial-year counter (MAX+1) parsed from
    the trailing segment of existing sr_no values.
    """
    try:
        fy = calculate_financial_year(sr_date)

        prefix_query = text("""
            SELECT cm.co_prefix, bm.branch_prefix
            FROM branch_mst bm
            LEFT JOIN co_mst cm ON cm.co_id = bm.co_id
            WHERE bm.branch_id = :branch_id
        """)
        prefix_row = db.execute(prefix_query, {"branch_id": branch_id}).fetchone()
        co_prefix = prefix_row.co_prefix if prefix_row else None
        branch_prefix = prefix_row.branch_prefix if prefix_row else None

        counter_query = text("""
            SELECT MAX(CAST(SUBSTRING_INDEX(sr_no, '/', -1) AS UNSIGNED)) AS max_no
            FROM proc_inward
            WHERE branch_id = :branch_id
            AND sr_no LIKE :pattern
        """)
        pattern = f"%/SR/{fy}/%"
        result = db.execute(counter_query, {"branch_id": branch_id, "pattern": pattern}).fetchone()

        next_no = 1
        if result and result.max_no:
            next_no = int(result.max_no) + 1

        return format_inward_no(
            inward_sequence_no=next_no,
            co_prefix=co_prefix,
            branch_prefix=branch_prefix,
            inward_date=sr_date,
            doc_type="SR",
        )
    except Exception:
        return f"SR-{now_ist().strftime('%Y%m%d%H%M%S')}"


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.get("/get_sr_pending_list")
def get_sr_pending_list(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    page: int = 1,
    limit: int = 10,
    search: str | None = None,
    co_id: int | None = None,
):
    """Return paginated list of inwards ready for SR (inspection complete)."""
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

        list_query = get_sr_pending_list_query()
        rows = db.execute(list_query, params).fetchall()
        
        data = []
        for row in rows:
            mapped = dict(row._mapping)
            
            # Format dates
            inward_date_obj = mapped.get("inward_date")
            inward_date = inward_date_obj.isoformat() if hasattr(inward_date_obj, "isoformat") else inward_date_obj
            
            inspection_date_obj = mapped.get("material_inspection_date")
            inspection_date = inspection_date_obj.isoformat() if inspection_date_obj and hasattr(inspection_date_obj, "isoformat") else None
            
            sr_date_obj = mapped.get("sr_date")
            sr_date = sr_date_obj.isoformat() if sr_date_obj and hasattr(sr_date_obj, "isoformat") else None
            
            # Format GRN/Inward number
            raw_inward_no = mapped.get("inward_sequence_no")
            formatted_inward_no = ""
            if raw_inward_no is not None and raw_inward_no != 0:
                try:
                    formatted_inward_no = format_inward_no(
                        inward_sequence_no=int(raw_inward_no),
                        co_prefix=mapped.get("co_prefix"),
                        branch_prefix=mapped.get("branch_prefix"),
                        inward_date=inward_date_obj,
                    )
                except Exception:
                    formatted_inward_no = str(raw_inward_no)
            
            data.append({
                "inward_id": mapped.get("inward_id"),
                "inward_no": formatted_inward_no,
                "inward_date": inward_date,
                "branch_id": mapped.get("branch_id"),
                "branch_name": mapped.get("branch_name") or "",
                "supplier_id": mapped.get("supplier_id"),
                "supplier_name": mapped.get("supplier_name") or "",
                "material_inspection_date": inspection_date,
                "sr_no": mapped.get("sr_no") or "",
                "sr_date": sr_date,
                "sr_status": mapped.get("sr_status"),
                "sr_status_name": mapped.get("sr_status_name") or "Pending",
            })

        count_query = get_sr_pending_count_query()
        count_result = db.execute(count_query, params).scalar()
        total = int(count_result) if count_result is not None else 0

        return {"data": data, "total": total}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching SR pending list")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/get_sr_by_inward_id/{inward_id}")
def get_sr_by_inward_id(
    inward_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    co_id: int | None = None,
    branch_id: int | None = None,
):
    """Get inward header and line items for SR page.
    
    Args:
        inward_id: Required path parameter - the inward record ID
        co_id: Optional query parameter - company ID for tenant filtering
        branch_id: Optional query parameter - branch ID (not currently used in query but available for future filtering)
    """
    try:
        # Validate inward_id
        if not inward_id or inward_id <= 0:
            raise HTTPException(status_code=400, detail="Valid inward_id is required")
        
        # Get header
        header_query = get_inward_for_sr_query()
        header_result = db.execute(header_query, {"inward_id": inward_id, "co_id": co_id}).fetchone()
        
        if not header_result:
            raise HTTPException(status_code=404, detail="Inward not found")
        
        header = dict(header_result._mapping)
        
        # Check inspection is complete
        if not header.get("inspection_check"):
            raise HTTPException(status_code=400, detail="Material inspection not complete")
        
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
        def format_date(date_obj):
            if date_obj and hasattr(date_obj, "isoformat"):
                return date_obj.isoformat()
            return None
        
        # Get line items
        dtl_query = get_inward_dtl_for_sr_query()
        dtl_result = db.execute(dtl_query, {"inward_id": inward_id}).fetchall()
        
        line_items = []
        for row in dtl_result:
            item = dict(row._mapping)
            item["po_no_formatted"] = extract_formatted_po_no(item) if item.get("po_no") else ""
            # Default accepted_rate to PO rate if not set
            if item.get("accepted_rate") is None:
                item["accepted_rate"] = item.get("po_rate") or item.get("rate") or 0
            line_items.append(item)
        
        # Get warehouses for the branch — with recursive hierarchy path
        branch_id = header.get("branch_id")
        logger.info(f"Fetching warehouses for branch_id: {branch_id}")
        warehouse_query = text("""
            WITH RECURSIVE warehouse_hierarchy AS (
                SELECT
                    wm.warehouse_id,
                    wm.branch_id,
                    wm.warehouse_name,
                    wm.parent_warehouse_id,
                    CAST(wm.warehouse_name AS CHAR) AS warehouse_path
                FROM warehouse_mst wm
                WHERE wm.parent_warehouse_id IS NULL
                    AND (wm.branch_id IS NULL OR wm.branch_id = :branch_id)
                UNION ALL
                SELECT
                    child.warehouse_id,
                    child.branch_id,
                    child.warehouse_name,
                    child.parent_warehouse_id,
                    CONCAT(parent.warehouse_path, '-', child.warehouse_name)
                FROM warehouse_mst child
                JOIN warehouse_hierarchy parent
                    ON child.parent_warehouse_id = parent.warehouse_id
                WHERE (child.branch_id IS NULL OR child.branch_id = :branch_id)
            )
            SELECT warehouse_id, warehouse_name, warehouse_path, branch_id
            FROM warehouse_hierarchy
            ORDER BY warehouse_path
        """)
        warehouse_result = db.execute(warehouse_query, {"branch_id": branch_id}).fetchall()
        warehouses = [dict(row._mapping) for row in warehouse_result]
        logger.info(f"Found {len(warehouses)} warehouses")
        
        # Get additional charges master list
        addl_charges_mst_query = get_additional_charges_mst_list()
        addl_charges_mst_result = db.execute(addl_charges_mst_query).fetchall()
        additional_charges_options = [dict(row._mapping) for row in addl_charges_mst_result]
        
        # Get existing additional charges for this inward
        addl_charges_query = get_inward_additional_charges_query()
        addl_charges_result = db.execute(addl_charges_query, {"inward_id": inward_id}).fetchall()
        additional_charges = [dict(row._mapping) for row in addl_charges_result]

        # Supplier branch options for the GST-state picker. Needed when the
        # inward has no PO and the supplier has >1 branch (ambiguous state) — the
        # single-branch case is already auto-resolved in get_inward_for_sr_query.
        supplier_branch_options = []
        if header.get("supplier_id"):
            sb_rows = db.execute(
                get_supplier_branches_for_gst_query(),
                {"supplier_id": header.get("supplier_id")},
            ).fetchall()
            supplier_branch_options = [dict(r._mapping) for r in sb_rows]

        # --- PO additional charges candidate (for first-load auto-populate on SR page) ---
        po_candidate = {"eligible": False, "reason": None, "po_id": None, "charges": []}
        po_ids_raw = [item.get("po_id") for item in line_items]
        has_missing_po = any(pid is None for pid in po_ids_raw)
        distinct_po_ids = {pid for pid in po_ids_raw if pid is not None}

        if has_missing_po:
            po_candidate["reason"] = "missing_po_on_line"
        elif len(distinct_po_ids) == 0:
            po_candidate["reason"] = "no_po"
        elif len(distinct_po_ids) > 1:
            po_candidate["reason"] = "multiple_pos"
        else:
            only_po_id = next(iter(distinct_po_ids))
            po_candidate["po_id"] = only_po_id
            po_total = db.execute(count_active_po_dtl_query(), {"po_id": only_po_id}).scalar() or 0
            inward_po_dtl_ids = {item.get("po_dtl_id") for item in line_items if item.get("po_dtl_id")}
            if po_total == 0 or len(inward_po_dtl_ids) < po_total:
                po_candidate["reason"] = "incomplete_po_coverage"
            else:
                po_addl_rows = db.execute(
                    get_po_additional_with_tax_by_id_query(),
                    {"po_id": only_po_id},
                ).fetchall()
                po_candidate["eligible"] = True
                po_candidate["charges"] = [dict(r._mapping) for r in po_addl_rows]

        return {
            "header": {
                "inward_id": header.get("inward_id"),
                "inward_no": formatted_inward_no,
                "inward_date": format_date(inward_date_obj),
                "branch_id": header.get("branch_id"),
                "branch_name": header.get("branch_name") or "",
                "supplier_id": header.get("supplier_id"),
                "supplier_name": header.get("supplier_name") or "",
                "supplier_branch_id": header.get("supplier_branch_id"),
                "supplier_branch_options": supplier_branch_options,
                "supplier_state_id": header.get("supplier_state_id"),
                "supplier_state_name": header.get("supplier_state_name") or "",
                "bill_branch_id": header.get("bill_branch_id"),
                "billing_branch_name": header.get("billing_branch_name") or "",
                "billing_state_id": header.get("billing_state_id"),
                "billing_state_name": header.get("billing_state_name") or "",
                "ship_branch_id": header.get("ship_branch_id"),
                "shipping_branch_name": header.get("shipping_branch_name") or "",
                "shipping_state_id": header.get("shipping_state_id"),
                "shipping_state_name": header.get("shipping_state_name") or "",
                "india_gst": bool(header.get("india_gst")),
                "inspection_date": format_date(header.get("inspection_date")),
                "sr_no": header.get("sr_no") or "",
                "sr_date": format_date(header.get("sr_date")),
                "sr_status": header.get("sr_status"),
                "sr_status_name": header.get("sr_status_name") or "",
                "invoice_date": format_date(header.get("invoice_date")),
                "invoice_amount": header.get("invoice_amount"),
                "invoice_recvd_date": format_date(header.get("invoice_recvd_date")),
                "invoice_no": header.get("invoice_no") or "",
                "challan_no": header.get("challan_no") or "",
                "challan_date": format_date(header.get("challan_date")),
                "vehicle_number": header.get("vehicle_number") or "",
                "driver_name": header.get("driver_name") or "",
                "driver_contact_no": header.get("driver_contact_no") or "",
                "consignment_no": header.get("consignment_no") or "",
                "consignment_date": format_date(header.get("consignment_date")),
                "ewaybillno": header.get("ewaybillno") or "",
                "ewaybill_date": format_date(header.get("ewaybill_date")),
                "despatch_remarks": header.get("despatch_remarks") or "",
                "receipts_remarks": header.get("receipts_remarks") or "",
                "sr_value": header.get("sr_value"),
                "sr_remarks": header.get("sr_remarks") or "",
                "gross_amount": header.get("gross_amount"),
                "net_amount": header.get("net_amount"),
            },
            "line_items": line_items,
            "warehouses": warehouses,
            "additional_charges_options": additional_charges_options,
            "additional_charges": additional_charges,
            "po_additional_candidate": po_candidate,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching inward for SR")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("/save_sr")
def save_sr(
    request_body: SRSaveRequest,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Save SR details (draft mode)."""
    try:
        user_id = token_data.get("user_id")
        if not user_id:
            raise HTTPException(status_code=401, detail="User ID not found in token")
        
        now = now_ist()
        sr_date = datetime.strptime(request_body.sr_date, '%Y-%m-%d').date()
        
        # Calculate totals
        gross_amount = 0.0
        net_amount = 0.0
        
        # Update each line item
        for line in request_body.line_items:
            # Calculate amount
            amount = line.amount
            if amount is None:
                # Need to get approved_qty from database
                qty_query = text("SELECT approved_qty FROM proc_inward_dtl WHERE inward_dtl_id = :id")
                qty_result = db.execute(qty_query, {"id": line.inward_dtl_id}).fetchone()
                approved_qty = qty_result.approved_qty if qty_result else 0
                amount = (approved_qty or 0) * (line.accepted_rate or 0)
            
            gross_amount += amount or 0
            net_amount += (amount or 0) - (line.discount_amount or 0)
            
            # Log the warehouse_id being saved
            logger.info(f"Saving line item {line.inward_dtl_id}: warehouse_id={line.warehouse_id}, accepted_rate={line.accepted_rate}")
            
            update_query = update_inward_dtl_sr()
            db.execute(update_query, {
                "inward_dtl_id": line.inward_dtl_id,
                "accepted_rate": line.accepted_rate,
                "amount": amount,
                "discount_mode": line.discount_mode,
                "discount_value": line.discount_value,
                "discount_amount": line.discount_amount,
                "hsn_code": line.hsn_code,
                "warehouse_id": line.warehouse_id,
                "updated_by": user_id,
                "updated_date_time": now,
            })
        
        # Handle additional charges (delete-all + re-insert pattern, same as PO update)
        additional_charges_total = 0.0
        # Normalize charges for GST processing later
        normalized_additional = []

        # Delete existing GST records for additional charges first
        delete_addl_gst_query = delete_proc_gst_for_sr_additional_charges()
        db.execute(delete_addl_gst_query, {"inward_id": request_body.inward_id})

        # Delete all existing additional charges for this inward
        delete_all_addl_query = delete_inward_additional_by_inward()
        db.execute(delete_all_addl_query, {"inward_id": request_body.inward_id})

        if request_body.additional_charges:
            insert_addl_query = insert_inward_additional()
            for charge in request_body.additional_charges:
                charge_net_amount = charge.net_amount or (charge.qty * charge.rate)
                additional_charges_total += charge_net_amount
                remarks_raw = (charge.remarks or "").strip() or None

                result = db.execute(insert_addl_query, {
                    "inward_id": request_body.inward_id,
                    "additional_charges_id": charge.additional_charges_id,
                    "qty": charge.qty,
                    "rate": charge.rate,
                    "net_amount": charge_net_amount,
                    "remarks": remarks_raw,
                })

                normalized_additional.append({
                    "proc_inward_additional_id": result.lastrowid,
                    "apply_tax": charge.apply_tax,
                    "tax_pct": charge.tax_pct or 0,
                    "net_amount": charge_net_amount,
                })
        
        # Update totals to include additional charges
        gross_amount += additional_charges_total
        net_amount += additional_charges_total
        
        # Get branch_id and current SR status. SR number is NOT generated here —
        # it is minted on approval. Existing sr_no is preserved if already set.
        header_query = text("SELECT branch_id, sr_no, sr_status FROM proc_inward WHERE inward_id = :id")
        header_result = db.execute(header_query, {"id": request_body.inward_id}).fetchone()
        branch_id = header_result.branch_id if header_result else None
        sr_no = header_result.sr_no if header_result and header_result.sr_no else None
        current_sr_status = header_result.sr_status if header_result and header_result.sr_status else None

        # Preserve existing status; only default to Draft for new SRs
        sr_status = current_sr_status if current_sr_status and current_sr_status != 0 else STATUS_DRAFT
        
        # Parse inward-level date fields ('YYYY-MM-DD' → date, empty/invalid → None)
        def _parse_date(value):
            if not value:
                return None
            try:
                return datetime.strptime(value, '%Y-%m-%d').date()
            except ValueError:
                return None

        invoice_date = _parse_date(request_body.invoice_date)
        invoice_recvd_date = _parse_date(request_body.invoice_recvd_date)
        challan_date = _parse_date(request_body.challan_date)
        inspection_date = _parse_date(request_body.inspection_date)
        consignment_date = _parse_date(request_body.consignment_date)
        ewaybill_date = _parse_date(request_body.ewaybill_date)

        def _clean_text(value):
            if value is None:
                return None
            stripped = str(value).strip()
            return stripped or None

        # Update inward header
        update_header_query = update_inward_sr()
        db.execute(update_header_query, {
            "inward_id": request_body.inward_id,
            "sr_no": sr_no,
            "sr_date": sr_date,
            "sr_status": sr_status,
            "sr_value": net_amount,
            "sr_remarks": request_body.sr_remarks,
            "sr_approved_by": None,
            "supplier_branch_id": request_body.supplier_branch_id,
            "bill_branch_id": request_body.bill_branch_id,
            "ship_branch_id": request_body.ship_branch_id,
            "invoice_no": _clean_text(request_body.invoice_no),
            "invoice_date": invoice_date,
            "invoice_amount": request_body.invoice_amount,
            "invoice_recvd_date": invoice_recvd_date,
            "challan_no": _clean_text(request_body.challan_no),
            "challan_date": challan_date,
            "vehicle_number": _clean_text(request_body.vehicle_number),
            "driver_name": _clean_text(request_body.driver_name),
            "driver_contact_number": _clean_text(request_body.driver_contact_no),
            "inspection_date": inspection_date,
            "consignment_no": _clean_text(request_body.consignment_no),
            "consignment_date": consignment_date,
            "ewaybillno": _clean_text(request_body.ewaybillno),
            "ewaybill_date": ewaybill_date,
            "despatch_remarks": _clean_text(request_body.despatch_remarks),
            "receipts_remarks": _clean_text(request_body.receipts_remarks),
            "gross_amount": gross_amount,
            "net_amount": net_amount,
            "updated_by": user_id,
            "updated_date_time": now,
        })

        # --- GST Handling ---
        # Write proc_gst records for each line item when india_gst is enabled
        if request_body.line_items and branch_id:
            # Get co_id from branch
            co_query = text("SELECT co_id FROM branch_mst WHERE branch_id = :branch_id")
            co_result = db.execute(co_query, {"branch_id": branch_id}).fetchone()
            co_id = co_result[0] if co_result else None

            india_gst = False
            if co_id:
                config_query = get_co_config_by_id_query(co_id)
                config_result = db.execute(config_query, {"co_id": co_id}).fetchone()
                if config_result:
                    india_gst = bool(dict(config_result._mapping).get("india_gst", False))

            if india_gst:
                # Get supplier_branch_id from proc_inward directly, fall back to PO chain for legacy data
                # Same fallbacks as get_inward_for_sr_query so a persisted SR's
                # GST matches the footer: bill/ship default to the receiving
                # branch, supplier defaults to its sole active branch (no PO case).
                inward_info_query = text("""
                    SELECT
                        COALESCE(
                            pi.supplier_branch_id, pp.supplier_branch_id,
                            (SELECT MAX(pb_auto.party_mst_branch_id) FROM party_branch_mst pb_auto
                             WHERE pb_auto.party_id = pi.supplier_id AND pb_auto.active = 1 HAVING COUNT(*) = 1)
                        ) AS supplier_branch_id,
                        COALESCE(pi.bill_branch_id, pp.billing_branch_id, pi.branch_id) AS bill_branch_id,
                        COALESCE(pi.ship_branch_id, pp.shipping_branch_id, pi.branch_id) AS ship_branch_id
                    FROM proc_inward pi
                    LEFT JOIN proc_po AS pp ON pp.po_id = (
                        SELECT ppd.po_id
                        FROM proc_inward_dtl pid
                        JOIN proc_po_dtl ppd ON ppd.po_dtl_id = pid.po_dtl_id
                        WHERE pid.inward_id = pi.inward_id AND pid.active = 1
                        LIMIT 1
                    )
                    WHERE pi.inward_id = :inward_id
                """)
                inward_info_result = db.execute(
                    inward_info_query, {"inward_id": request_body.inward_id}
                ).fetchone()
                inward_info = dict(inward_info_result._mapping) if inward_info_result else {}
                supplier_branch_id = inward_info.get("supplier_branch_id")

                # Get supplier state from party_branch_mst
                supplier_state_id = None
                if supplier_branch_id:
                    supplier_state_query = text(
                        "SELECT state_id FROM party_branch_mst WHERE party_mst_branch_id = :branch_id"
                    )
                    sup_result = db.execute(
                        supplier_state_query, {"branch_id": supplier_branch_id}
                    ).fetchone()
                    supplier_state_id = sup_result[0] if sup_result else None

                # Get shipping state from inward's branch IDs (with PO fallback already resolved)
                ship_branch = inward_info.get("ship_branch_id") or inward_info.get("bill_branch_id")
                shipping_state_id = None
                if ship_branch:
                    ship_state_query = text(
                        "SELECT state_id FROM branch_mst WHERE branch_id = :branch_id"
                    )
                    ship_result = db.execute(
                        ship_state_query, {"branch_id": ship_branch}
                    ).fetchone()
                    shipping_state_id = ship_result[0] if ship_result else None

                if supplier_state_id and shipping_state_id:
                    # Delete existing GST records for line items
                    delete_gst_query = delete_proc_gst_by_inward()
                    db.execute(delete_gst_query, {"inward_id": request_body.inward_id})

                    gst_insert_query = insert_proc_gst()

                    # Insert GST records for each line item
                    tax_query = get_inward_line_tax_pct_query()
                    for line in request_body.line_items:
                        # Tax % is user-editable on the SR; honour the entered
                        # value. When absent, seed from the originating PO
                        # (po_gst) or, for a direct inward, from item_mst.
                        if line.tax_percentage is not None:
                            tax_pct = float(line.tax_percentage)
                        else:
                            tax_result = db.execute(
                                tax_query, {"inward_dtl_id": line.inward_dtl_id}
                            ).fetchone()
                            tax_pct = float(tax_result[0]) if tax_result and tax_result[0] else 0.0

                        if tax_pct > 0:
                            line_amount = float(line.amount or 0)
                            gst = calculate_gst_amounts(
                                line_amount, tax_pct, supplier_state_id, shipping_state_id
                            )

                            db.execute(gst_insert_query, {
                                "proc_inward_dtl": line.inward_dtl_id,
                                "proc_inward_additional_id": None,
                                "tax_pct": gst["tax_pct"],
                                "stax_percentage": gst["stax_percentage"],
                                "s_tax_amount": gst["s_tax_amount"],
                                "i_tax_amount": gst["i_tax_amount"],
                                "i_tax_percentage": gst["i_tax_percentage"],
                                "c_tax_amount": gst["c_tax_amount"],
                                "c_tax_percentage": gst["c_tax_percentage"],
                                "tax_amount": gst["tax_amount"],
                                "updated_by": user_id,
                            })

                    # Insert GST records for additional charges (same as PO pattern)
                    for addl in normalized_additional:
                        addl_tax_pct = float(addl["tax_pct"] or 0)
                        if addl_tax_pct <= 0 or not addl.get("apply_tax", True):
                            continue
                        addl_gst = calculate_gst_amounts(
                            addl["net_amount"], addl_tax_pct, supplier_state_id, shipping_state_id
                        )
                        db.execute(gst_insert_query, {
                            "proc_inward_dtl": None,
                            "proc_inward_additional_id": addl["proc_inward_additional_id"],
                            "tax_pct": addl_gst["tax_pct"],
                            "stax_percentage": addl_gst["stax_percentage"],
                            "s_tax_amount": addl_gst["s_tax_amount"],
                            "i_tax_amount": addl_gst["i_tax_amount"],
                            "i_tax_percentage": addl_gst["i_tax_percentage"],
                            "c_tax_amount": addl_gst["c_tax_amount"],
                            "c_tax_percentage": addl_gst["c_tax_percentage"],
                            "tax_amount": addl_gst["tax_amount"],
                            "updated_by": user_id,
                        })

        db.commit()

        return {
            "success": True,
            "message": "SR saved successfully",
            "inward_id": request_body.inward_id,
            "sr_no": sr_no,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error saving SR")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("/open_sr")
def open_sr(
    request_body: SRApproveRequest,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Open SR for approval."""
    try:
        user_id = token_data.get("user_id")
        now = now_ist()
        
        # Update status to Open
        query = text("""
            UPDATE proc_inward
            SET sr_status = :status_id, updated_by = :updated_by, updated_date_time = :updated_date_time
            WHERE inward_id = :inward_id
        """)
        db.execute(query, {
            "inward_id": request_body.inward_id,
            "status_id": STATUS_OPEN,
            "updated_by": user_id,
            "updated_date_time": now,
        })
        
        db.commit()
        
        return {"success": True, "message": "SR opened successfully"}
    except Exception as e:
        db.rollback()
        logger.exception("Error opening SR")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("/approve_sr")
def approve_sr(
    request_body: SRApproveRequest,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Approve SR. 
    Auto-creates DRCR Note if there are rate differences or rejected quantities.
    """
    try:
        user_id = token_data.get("user_id")
        if not user_id:
            raise HTTPException(status_code=401, detail="User ID not found in token")
        
        now = now_ist()
        today = date.today()
        
        # Get line items to check for rate differences and rejections
        dtl_query = get_inward_dtl_for_sr_query()
        line_items = db.execute(dtl_query, {"inward_id": request_body.inward_id}).fetchall()

        # --- GST prep for auto-DRCR lines ---
        india_gst = False
        supplier_state_id = None
        shipping_state_id = None
        tax_pct_by_inward_dtl: dict = {}

        inward_info_row = db.execute(
            text(
                """
                SELECT
                    COALESCE(
                        pi.supplier_branch_id, pp.supplier_branch_id,
                        (SELECT MAX(pb_auto.party_mst_branch_id) FROM party_branch_mst pb_auto
                         WHERE pb_auto.party_id = pi.supplier_id AND pb_auto.active = 1 HAVING COUNT(*) = 1)
                    ) AS supplier_branch_id,
                    COALESCE(pi.ship_branch_id, pi.bill_branch_id, pp.shipping_branch_id, pp.billing_branch_id, pi.branch_id) AS ship_branch_id,
                    bm.co_id AS co_id
                FROM proc_inward pi
                LEFT JOIN branch_mst bm ON bm.branch_id = pi.branch_id
                LEFT JOIN proc_po AS pp ON pp.po_id = (
                    SELECT ppd.po_id
                    FROM proc_inward_dtl pid
                    JOIN proc_po_dtl ppd ON ppd.po_dtl_id = pid.po_dtl_id
                    WHERE pid.inward_id = pi.inward_id AND pid.active = 1
                    LIMIT 1
                )
                WHERE pi.inward_id = :inward_id
                """
            ),
            {"inward_id": request_body.inward_id},
        ).fetchone()
        inward_info = dict(inward_info_row._mapping) if inward_info_row else {}
        co_id = inward_info.get("co_id")
        supplier_branch_id = inward_info.get("supplier_branch_id")
        ship_branch_id = inward_info.get("ship_branch_id")

        if co_id:
            config_row = db.execute(
                get_co_config_by_id_query(co_id), {"co_id": co_id}
            ).fetchone()
            if config_row:
                india_gst = bool(dict(config_row._mapping).get("india_gst", False))

        if india_gst:
            if supplier_branch_id:
                sup_row = db.execute(
                    text("SELECT state_id FROM party_branch_mst WHERE party_mst_branch_id = :branch_id"),
                    {"branch_id": supplier_branch_id},
                ).fetchone()
                supplier_state_id = sup_row[0] if sup_row else None
            if ship_branch_id:
                ship_row = db.execute(
                    text("SELECT state_id FROM branch_mst WHERE branch_id = :branch_id"),
                    {"branch_id": ship_branch_id},
                ).fetchone()
                shipping_state_id = ship_row[0] if ship_row else None

            inward_dtl_ids = [r._mapping.get("inward_dtl_id") for r in line_items if r._mapping.get("inward_dtl_id") is not None]
            if inward_dtl_ids:
                placeholders = ", ".join([f":d{i}" for i in range(len(inward_dtl_ids))])
                tax_params = {f"d{i}": v for i, v in enumerate(inward_dtl_ids)}
                tax_rows = db.execute(
                    text(
                        f"SELECT proc_inward_dtl, tax_pct FROM proc_gst "
                        f"WHERE proc_inward_dtl IN ({placeholders}) AND active = 1"
                    ),
                    tax_params,
                ).fetchall()
                for tr in tax_rows:
                    tr_map = dict(tr._mapping)
                    tax_pct_by_inward_dtl[tr_map.get("proc_inward_dtl")] = float(tr_map.get("tax_pct") or 0)

        gst_insert_dn_query = insert_drcr_note_dtl_gst()

        def _insert_drcr_gst(qty: float, rate: float, inward_dtl_id: int) -> None:
            if not india_gst or not supplier_state_id or not shipping_state_id:
                return
            tax_pct = tax_pct_by_inward_dtl.get(inward_dtl_id, 0.0)
            if tax_pct <= 0:
                return
            dtl_id_row = db.execute(text("SELECT LAST_INSERT_ID() AS id")).fetchone()
            drcr_note_dtl_id = dtl_id_row.id if dtl_id_row else None
            if not drcr_note_dtl_id:
                return
            exists = db.execute(
                text("SELECT 1 FROM drcr_note_dtl_gst WHERE drcr_note_dtl_id = :id LIMIT 1"),
                {"id": drcr_note_dtl_id},
            ).fetchone()
            if exists:
                return
            gst = calculate_gst_amounts(
                (qty or 0) * (rate or 0), tax_pct, supplier_state_id, shipping_state_id
            )
            db.execute(gst_insert_dn_query, {
                "drcr_note_dtl_id": drcr_note_dtl_id,
                "cgst_amount": gst["c_tax_amount"],
                "igst_amount": gst["i_tax_amount"],
                "sgst_amount": gst["s_tax_amount"],
            })

        # Check for rate differences and rejected quantities
        drcr_lines_debit = []  # For rate decrease or rejected qty
        drcr_lines_credit = []  # For rate increase
        
        for row in line_items:
            item = dict(row._mapping)
            po_rate = item.get("po_rate") or item.get("rate") or 0
            accepted_rate = item.get("accepted_rate") or po_rate
            rejected_qty = item.get("rejected_qty") or 0
            approved_qty = item.get("approved_qty") or 0
            
            rate_diff = po_rate - accepted_rate
            
            # Rejected quantity - always creates debit note
            if rejected_qty > 0:
                drcr_lines_debit.append({
                    "inward_dtl_id": item.get("inward_dtl_id"),
                    "debitnote_type": 1,  # Quantity rejection
                    "quantity": rejected_qty,
                    "rate": po_rate,
                })
            
            # Rate difference
            if rate_diff > 0:
                # Rate decreased - create debit note (supplier owes us)
                drcr_lines_debit.append({
                    "inward_dtl_id": item.get("inward_dtl_id"),
                    "debitnote_type": 2,  # Rate difference
                    "quantity": approved_qty,
                    "rate": rate_diff,
                })
            elif rate_diff < 0:
                # Rate increased - create credit note (we owe supplier)
                drcr_lines_credit.append({
                    "inward_dtl_id": item.get("inward_dtl_id"),
                    "debitnote_type": 2,  # Rate difference
                    "quantity": approved_qty,
                    "rate": abs(rate_diff),
                })

        # Create Debit Note if needed
        if drcr_lines_debit:
            gross_amount = sum(line["quantity"] * line["rate"] for line in drcr_lines_debit)
            
            # Insert debit note header
            insert_note = insert_drcr_note()
            db.execute(insert_note, {
                "note_date": today,
                "adjustment_type": DRCR_TYPE_DEBIT,
                "inward_id": request_body.inward_id,
                "remarks": "Auto-created on SR approval",
                "status_id": STATUS_DRAFT,
                "auto_create": 1,
                "updated_by": user_id,
                "updated_date_time": now,
                "gross_amount": gross_amount,
                "net_amount": gross_amount,
            })
            
            # Get the inserted note ID
            note_id_result = db.execute(text("SELECT LAST_INSERT_ID() as id")).fetchone()
            note_id = note_id_result.id if note_id_result else None
            
            # Insert line items
            if note_id:
                insert_dtl = insert_drcr_note_dtl()
                for line in drcr_lines_debit:
                    db.execute(insert_dtl, {
                        "debit_credit_note_id": note_id,
                        "inward_dtl_id": line["inward_dtl_id"],
                        "debitnote_type": line["debitnote_type"],
                        "quantity": line["quantity"],
                        "rate": line["rate"],
                        "discount_mode": None,
                        "discount_value": None,
                        "discount_amount": None,
                        "updated_by": user_id,
                        "updated_date_time": now,
                    })
                    _insert_drcr_gst(line["quantity"], line["rate"], line["inward_dtl_id"])

        # Create Credit Note if needed
        if drcr_lines_credit:
            gross_amount = sum(line["quantity"] * line["rate"] for line in drcr_lines_credit)
            
            # Insert credit note header
            insert_note = insert_drcr_note()
            db.execute(insert_note, {
                "note_date": today,
                "adjustment_type": DRCR_TYPE_CREDIT,
                "inward_id": request_body.inward_id,
                "remarks": "Auto-created on SR approval (rate increase)",
                "status_id": STATUS_DRAFT,
                "auto_create": 1,
                "updated_by": user_id,
                "updated_date_time": now,
                "gross_amount": gross_amount,
                "net_amount": gross_amount,
            })
            
            # Get the inserted note ID
            note_id_result = db.execute(text("SELECT LAST_INSERT_ID() as id")).fetchone()
            note_id = note_id_result.id if note_id_result else None
            
            # Insert line items
            if note_id:
                insert_dtl = insert_drcr_note_dtl()
                for line in drcr_lines_credit:
                    db.execute(insert_dtl, {
                        "debit_credit_note_id": note_id,
                        "inward_dtl_id": line["inward_dtl_id"],
                        "debitnote_type": line["debitnote_type"],
                        "quantity": line["quantity"],
                        "rate": line["rate"],
                        "discount_mode": None,
                        "discount_value": None,
                        "discount_amount": None,
                        "updated_by": user_id,
                        "updated_date_time": now,
                    })
                    _insert_drcr_gst(line["quantity"], line["rate"], line["inward_dtl_id"])

        # Fetch header to determine if SR number needs to be minted
        header_query = text(
            "SELECT branch_id, sr_no, sr_date FROM proc_inward WHERE inward_id = :inward_id"
        )
        header_result = db.execute(
            header_query, {"inward_id": request_body.inward_id}
        ).fetchone()
        existing_sr_no = header_result.sr_no if header_result else None
        branch_id = header_result.branch_id if header_result else None
        sr_date_value = (
            header_result.sr_date if header_result and header_result.sr_date else today
        )

        new_sr_no = None
        if not existing_sr_no and branch_id:
            new_sr_no = generate_sr_no(db, branch_id, sr_date_value)

        # Update SR status to Approved (and mint sr_no if first approval)
        if new_sr_no:
            query = text("""
                UPDATE proc_inward
                SET sr_status = :status_id,
                    sr_approved_by = :approved_by,
                    sr_no = :sr_no,
                    updated_by = :updated_by,
                    updated_date_time = :updated_date_time
                WHERE inward_id = :inward_id
            """)
            db.execute(query, {
                "inward_id": request_body.inward_id,
                "status_id": STATUS_APPROVED,
                "approved_by": user_id,
                "sr_no": new_sr_no,
                "updated_by": user_id,
                "updated_date_time": now,
            })
        else:
            query = text("""
                UPDATE proc_inward
                SET sr_status = :status_id, sr_approved_by = :approved_by, updated_by = :updated_by, updated_date_time = :updated_date_time
                WHERE inward_id = :inward_id
            """)
            db.execute(query, {
                "inward_id": request_body.inward_id,
                "status_id": STATUS_APPROVED,
                "approved_by": user_id,
                "updated_by": user_id,
                "updated_date_time": now,
            })

        db.commit()

        drcr_created = len(drcr_lines_debit) > 0 or len(drcr_lines_credit) > 0
        message = "SR approved successfully"
        if drcr_created:
            message += ". DRCR Note(s) auto-created."
        
        return {
            "success": True,
            "message": message,
            "drcr_created": drcr_created,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error approving SR")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("/reject_sr")
def reject_sr(
    request_body: SRApproveRequest,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Reject SR."""
    try:
        user_id = token_data.get("user_id")
        now = now_ist()
        
        query = text("""
            UPDATE proc_inward
            SET sr_status = :status_id, sr_remarks = :reason,
                updated_by = :updated_by, updated_date_time = :updated_date_time
            WHERE inward_id = :inward_id
        """)
        db.execute(query, {
            "inward_id": request_body.inward_id,
            "status_id": STATUS_REJECTED,
            "reason": request_body.reason or "No reason provided",
            "updated_by": user_id,
            "updated_date_time": now,
        })
        
        db.commit()
        
        return {"success": True, "message": "SR rejected"}
    except Exception as e:
        db.rollback()
        logger.exception("Error rejecting SR")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
