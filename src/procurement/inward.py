import logging
from datetime import datetime
from src.common.utils import now_ist
from fastapi import Depends, Request, HTTPException, APIRouter
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.procurement.query import (
    get_inward_table_query,
    get_inward_table_count_query,
    get_inward_by_id_query,
    get_inward_detail_by_id_query,
    get_suppliers_with_party_type_1,
    get_item_by_group_id_purchaseable,
    get_item_make_by_group_id,
    get_item_uom_by_group_id,
    get_approved_pos_by_supplier_query,
    get_po_line_items_for_inward_query,
    insert_proc_inward,
    insert_proc_inward_dtl,
    get_max_inward_no_for_branch_fy,
)
from src.masters.query import get_item_group_drodown, get_branch_list
from src.common.companyAdmin.query import get_co_config_by_id_query
from src.procurement.indent import calculate_financial_year
from src.procurement.po import format_po_no, extract_formatted_po_no
from src.common.utils import parse_json_body

logger = logging.getLogger(__name__)

router = APIRouter()


def format_inward_no(
    inward_sequence_no: Optional[int],
    co_prefix: Optional[str],
    branch_prefix: Optional[str],
    inward_date,
    doc_type: str = "IN",
) -> str:
    """Format doc number as 'co_prefix/branch_prefix/{doc_type}/financial_year/sequence_no'.

    Shared formatter for procurement document numbers. Pass doc_type="SR" for
    Stores Receipt, default "IN" for Inward/GRN.
    """
    if inward_sequence_no is None or inward_sequence_no == 0:
        return ""

    fy = calculate_financial_year(inward_date)
    co_pref = co_prefix or ""
    branch_pref = branch_prefix or ""

    parts = []
    if co_pref:
        parts.append(co_pref)
    if branch_pref:
        parts.append(branch_pref)
    # SR numbers are zero-padded to 6 digits to match the legacy sls convention
    # (e.g. .../000009). Inward/GRN numbers stay unpadded. The counter reads the
    # seq back via CAST(... AS UNSIGNED) so padding is stripped on the next MAX+1.
    seq_str = f"{inward_sequence_no:06d}" if doc_type == "SR" else str(inward_sequence_no)
    parts.extend([doc_type, fy, seq_str])

    return "/".join(parts)


@router.get("/get_inward_table")
def get_inward_table(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    page: int = 1,
    limit: int = 10,
    search: str | None = None,
    co_id: int | None = None,
):
    """Return paginated procurement inward/GRN list."""

    try:
        page = max(page, 1)
        limit = max(min(limit, 100), 1)
        offset = (page - 1) * limit
        search_like = None
        if search:
            search_like = f"%{search.strip()}%"

        params = {
            "co_id": co_id,
            "search_like": search_like,
            "limit": limit,
            "offset": offset,
        }

        list_query = get_inward_table_query()
        rows = db.execute(list_query, params).fetchall()
        data = []
        for row in rows:
            mapped = dict(row._mapping)
            
            # Format inward date
            inward_date_obj = mapped.get("inward_date")
            inward_date = inward_date_obj
            if hasattr(inward_date_obj, "isoformat"):
                inward_date = inward_date_obj.isoformat()
            
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
                except Exception as e:
                    logger.exception("Error formatting Inward number in list, using raw value")
                    formatted_inward_no = str(raw_inward_no) if raw_inward_no else ""
            
            # Format PO number using helper
            formatted_po_no = extract_formatted_po_no(mapped)
            
            data.append(
                {
                    "inward_id": mapped.get("inward_id"),
                    "inward_no": formatted_inward_no,
                    "inward_date": inward_date,
                    "branch_id": mapped.get("branch_id"),
                    "branch_name": mapped.get("branch_name") or "",
                    "po_id": mapped.get("po_id"),
                    "po_no": formatted_po_no,
                    "supplier_id": mapped.get("supplier_id"),
                    "supplier_name": mapped.get("supplier_name") or "",
                    "inspection_check": bool(mapped.get("inspection_check")),
                    "status": mapped.get("status_name") or "Pending",
                }
            )

        count_query = get_inward_table_count_query()
        count_result = db.execute(count_query, params).scalar()
        total = int(count_result) if count_result is not None else 0

        return {"data": data, "total": total}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching Inward table")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/get_inward_setup_1")
def get_inward_setup_1(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    branch_id: int | None = None,
    co_id: int | None = None,
):
    """Return suppliers, item_groups, and co_config for inward/GRN creation."""
    try:
        # Get query parameters
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

        # Branches
        branch_ids_list = [branch_id] if branch_id is not None else None
        branchquery = get_branch_list(branch_ids=branch_ids_list) if branch_ids_list else get_branch_list()
        branch_result = db.execute(branchquery, {"branch_ids": branch_ids_list} if branch_ids_list else {}).fetchall()
        branches = [dict(r._mapping) for r in branch_result]

        # Suppliers (party_type_id contains 1)
        supplier_query = get_suppliers_with_party_type_1(co_id=co_id)
        supplier_result = db.execute(supplier_query, {"co_id": co_id}).fetchall()
        suppliers = [dict(r._mapping) for r in supplier_result]

        # NOTE: Supplier branches are NOT fetched here — the inward frontend
        # does not use them. If a supplier-branch dropdown is needed in the
        # future, add a lazy endpoint (e.g. /get_supplier_branches?supplier_id=X)
        # instead of pre-loading branches for all 874+ suppliers.

        # Item groups
        itemgrp_query = get_item_group_drodown(co_id=co_id)
        itemgrp_result = db.execute(itemgrp_query, {"co_id": co_id}).fetchall()
        item_groups = [dict(r._mapping) for r in itemgrp_result]

        # Co config
        co_config_query = get_co_config_by_id_query(co_id)
        co_config_result = db.execute(co_config_query, {"co_id": co_id}).fetchone()
        co_config = dict(co_config_result._mapping) if co_config_result else {}

        return {
            "branches": branches,
            "suppliers": suppliers,
            "item_groups": item_groups,
            "co_config": co_config,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching inward setup 1")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/get_inward_setup_2")
def get_inward_setup_2(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    item_group: int | None = None,
):
    """Return items, makes, and UOMs for a given item group (for manual line item entry)."""
    try:
        q_item_group = request.query_params.get("item_group")
        if q_item_group is not None:
            try:
                item_group = int(q_item_group)
            except Exception:
                raise HTTPException(status_code=400, detail="Invalid item_group")

        if item_group is None:
            raise HTTPException(status_code=400, detail="item_group is required")

        # Items for the group
        items_query = get_item_by_group_id_purchaseable(item_group_id=item_group)
        items_result = db.execute(items_query, {"item_group_id": item_group}).fetchall()
        items = [dict(r._mapping) for r in items_result]

        # Makes for the group
        makes_query = get_item_make_by_group_id(item_group_id=item_group)
        makes_result = db.execute(makes_query, {"item_group_id": item_group}).fetchall()
        makes = [dict(r._mapping) for r in makes_result]

        # UOMs for the group
        uom_query = get_item_uom_by_group_id(item_group_id=item_group)
        uom_result = db.execute(uom_query, {"item_group_id": item_group}).fetchall()
        uoms = [dict(r._mapping) for r in uom_result]

        return {
            "items": items,
            "makes": makes,
            "uoms": uoms,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching inward setup 2")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/get_approved_pos_by_supplier")
def get_approved_pos_by_supplier(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    supplier_id: int | None = None,
    branch_id: int | None = None,
):
    """
    Return approved POs for a specific supplier that have pending items to receive.
    Used in Inward/GRN creation to select from which PO to receive goods.
    
    Parameters:
    - supplier_id (required): Filter by supplier
    - branch_id (optional): Filter by branch
    - status_id = 3 (hardcoded in query): Only approved POs
    """
    try:
        # Parse query parameters
        q_supplier_id = request.query_params.get("supplier_id")
        q_branch_id = request.query_params.get("branch_id")

        if q_supplier_id is not None:
            try:
                supplier_id = int(q_supplier_id)
            except Exception:
                raise HTTPException(status_code=400, detail="Invalid supplier_id")

        if q_branch_id is not None:
            try:
                branch_id = int(q_branch_id)
            except Exception:
                raise HTTPException(status_code=400, detail="Invalid branch_id")

        if supplier_id is None:
            raise HTTPException(status_code=400, detail="supplier_id is required")

        params = {
            "supplier_id": supplier_id,
            "branch_id": branch_id,
        }

        query = get_approved_pos_by_supplier_query()
        rows = db.execute(query, params).fetchall()

        data = []
        for row in rows:
            mapped = dict(row._mapping)

            # Format PO date
            po_date_obj = mapped.get("po_date")
            po_date_str = po_date_obj.isoformat() if hasattr(po_date_obj, "isoformat") else str(po_date_obj) if po_date_obj else ""

            # Format PO number using helper
            formatted_po_no = extract_formatted_po_no(mapped)

            data.append({
                "po_id": mapped.get("po_id"),
                "po_no": formatted_po_no,
                "po_date": po_date_str,
                "branch_id": mapped.get("branch_id"),
                "branch_name": mapped.get("branch_name") or "",
                "supplier_id": mapped.get("supplier_id"),
                "supplier_name": mapped.get("supplier_name") or "",
            })

        return {"data": data, "total": len(data)}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching approved POs by supplier")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/get_po_line_items")
def get_po_line_items(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    po_id: int | None = None,
):
    """
    Return PO line items for inward/GRN entry with pending quantities.
    Only returns items with pending_qty > 0 (ordered - already received).
    """
    try:
        q_po_id = request.query_params.get("po_id")
        if q_po_id is not None:
            try:
                po_id = int(q_po_id)
            except Exception:
                raise HTTPException(status_code=400, detail="Invalid po_id")

        if po_id is None:
            raise HTTPException(status_code=400, detail="po_id is required")

        query = get_po_line_items_for_inward_query()
        rows = db.execute(query, {"po_id": po_id}).fetchall()

        line_items = []
        for row in rows:
            mapped = dict(row._mapping)

            # Format PO number using helper
            formatted_po_no = extract_formatted_po_no(mapped)

            line_items.append({
                "po_dtl_id": mapped.get("po_dtl_id"),
                "po_id": mapped.get("po_id"),
                "po_no": formatted_po_no,
                "item_id": mapped.get("item_id"),
                "item_code": mapped.get("item_code") or "",
                "full_item_code": mapped.get("full_item_code") or "",
                "item_name": mapped.get("item_name") or "",
                "item_grp_id": mapped.get("item_grp_id"),
                "item_grp_code": mapped.get("item_grp_code") or "",
                "item_grp_name": mapped.get("item_grp_name") or "",
                "item_make_id": mapped.get("item_make_id"),
                "item_make_name": mapped.get("item_make_name") or "",
                "ordered_qty": mapped.get("ordered_qty") or 0,
                "received_qty": mapped.get("received_qty") or 0,
                "pending_qty": mapped.get("pending_qty") or 0,
                "uom_id": mapped.get("uom_id"),
                "uom_name": mapped.get("uom_name") or "",
                "rate": mapped.get("rate") or 0,
                "amount": mapped.get("amount") or 0,
                "remarks": mapped.get("remarks") or "",
                "tax_percentage": mapped.get("tax_percentage"),
                "hsn_code": mapped.get("hsn_code") or "",
            })

        return {
            "po_id": po_id,
            "line_items": line_items,
            "total": len(line_items),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching PO line items for inward")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/get_inward_by_id")
def get_inward_by_id(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Return inward/GRN details by ID with all line items."""
    try:
        # Get query parameters
        q_inward_id = request.query_params.get("inward_id")
        q_co_id = request.query_params.get("co_id")

        if q_inward_id is None:
            raise HTTPException(status_code=400, detail="inward_id is required")
        if q_co_id is None:
            raise HTTPException(status_code=400, detail="co_id is required")

        try:
            inward_id = int(q_inward_id)
            co_id = int(q_co_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid inward_id or co_id")

        # Fetch header data
        header_query = get_inward_by_id_query()
        header_params = {"inward_id": inward_id, "co_id": co_id}
        header_result = db.execute(header_query, header_params).fetchone()

        if not header_result:
            raise HTTPException(status_code=404, detail="Inward not found or access denied")

        header = dict(header_result._mapping)

        # Fetch line items
        detail_query = get_inward_detail_by_id_query()
        detail_params = {"inward_id": inward_id}
        detail_results = db.execute(detail_query, detail_params).fetchall()
        details = [dict(r._mapping) for r in detail_results]

        # Format dates - frontend expects YYYY-MM-DD format
        inward_date = header.get("inward_date")
        if inward_date and hasattr(inward_date, "isoformat"):
            inward_date_str = inward_date.isoformat()
        elif inward_date:
            inward_date_str = str(inward_date)
        else:
            inward_date_str = ""

        challan_date = header.get("challan_date")
        if challan_date and hasattr(challan_date, "isoformat"):
            challan_date_str = challan_date.isoformat()
        else:
            challan_date_str = str(challan_date) if challan_date else None

        invoice_date = header.get("invoice_date")
        if invoice_date and hasattr(invoice_date, "isoformat"):
            invoice_date_str = invoice_date.isoformat()
        else:
            invoice_date_str = str(invoice_date) if invoice_date else None

        updated_at = header.get("updated_date_time")
        updated_at_str = None
        if updated_at:
            if hasattr(updated_at, "isoformat"):
                updated_at_str = updated_at.isoformat()
            else:
                updated_at_str = str(updated_at)

        # Get status_id
        status_id = header.get("status_id")
        branch_id = header.get("branch_id")

        # Format inward number
        raw_inward_no = header.get("inward_sequence_no")
        formatted_inward_no = ""
        if raw_inward_no is not None and raw_inward_no != 0:
            try:
                inward_no_int = int(raw_inward_no) if raw_inward_no else None
                co_prefix = header.get("co_prefix")
                branch_prefix = header.get("branch_prefix")
                formatted_inward_no = format_inward_no(
                    inward_sequence_no=inward_no_int,
                    co_prefix=co_prefix,
                    branch_prefix=branch_prefix,
                    inward_date=inward_date,
                )
            except Exception as e:
                logger.exception("Error formatting inward number, using raw value")
                formatted_inward_no = str(raw_inward_no) if raw_inward_no else ""

        # Helper to format dates
        def format_date_field(date_val):
            if date_val and hasattr(date_val, "isoformat"):
                return date_val.isoformat()
            elif date_val:
                return str(date_val)
            return None

        # Build response matching InwardDetails type from frontend
        response = {
            "id": str(header.get("inward_id", "")),
            "inwardNo": formatted_inward_no,
            "inwardDate": inward_date_str,
            "branch": str(header.get("branch_id", "")) if header.get("branch_id") else "",
            "branchId": str(header.get("branch_id", "")) if header.get("branch_id") else "",
            "supplier": str(header.get("supplier_id", "")) if header.get("supplier_id") else "",
            "supplierId": str(header.get("supplier_id", "")) if header.get("supplier_id") else "",
            "challanNo": header.get("challan_no") if header.get("challan_no") else None,
            "challanDate": challan_date_str,
            "invoiceNo": header.get("invoice_no") if header.get("invoice_no") else None,
            "invoiceDate": invoice_date_str,
            "invoiceRecvdDate": format_date_field(header.get("invoice_recvd_date")),
            "vehicleNo": header.get("vehicle_number") if header.get("vehicle_number") else None,
            "driverName": header.get("driver_name") if header.get("driver_name") else None,
            "driverContactNo": header.get("driver_contact_no") if header.get("driver_contact_no") else None,
            "consignmentNo": header.get("consignment_no") if header.get("consignment_no") else None,
            "consignmentDate": format_date_field(header.get("consignment_date")),
            "ewaybillno": header.get("ewaybillno") if header.get("ewaybillno") else None,
            "ewaybillDate": format_date_field(header.get("ewaybill_date")),
            "despatchRemarks": header.get("despatch_remarks") if header.get("despatch_remarks") else None,
            "receiptsRemarks": header.get("receipts_remarks") if header.get("receipts_remarks") else None,
            "status": header.get("status_name") if header.get("status_name") else None,
            "statusId": status_id,
            "inspection_check": bool(header.get("inspection_check")) if header.get("inspection_check") is not None else False,
            "approvalLevel": None,  # Not implemented for inward yet
            "maxApprovalLevel": None,
            "updatedBy": str(header.get("updated_by", "")) if header.get("updated_by") else None,
            "updatedAt": updated_at_str,
            "lines": [],
        }

        # Map line items
        for detail in details:
            # Format PO number for line item
            po_no_formatted = ""
            raw_po_no = detail.get("po_no")
            if raw_po_no is not None and raw_po_no != 0:
                try:
                    po_no_formatted = extract_formatted_po_no(detail)
                except Exception:
                    po_no_formatted = str(raw_po_no) if raw_po_no else ""

            line = {
                "inward_dtl_id": str(detail.get("inward_dtl_id", "")) if detail.get("inward_dtl_id") else "",
                "id": str(detail.get("inward_dtl_id", "")) if detail.get("inward_dtl_id") else "",
                "po_dtl_id": str(detail.get("po_dtl_id", "")) if detail.get("po_dtl_id") else None,
                "po_no": po_no_formatted,
                "item_grp_id": str(detail.get("item_grp_id", "")) if detail.get("item_grp_id") else "",
                "item_id": str(detail.get("item_id", "")) if detail.get("item_id") else "",
                "item_code": detail.get("full_item_code") or detail.get("item_code") or None,
                "item_make_id": str(detail.get("item_make_id", "")) if detail.get("item_make_id") else None,
                "quantity": float(detail.get("quantity", 0)) if detail.get("quantity") is not None else 0,
                "rate": float(detail.get("rate", 0)) if detail.get("rate") is not None else 0,
                "uom_id": str(detail.get("uom_id", "")) if detail.get("uom_id") else "",
                "amount": float(detail.get("amount", 0)) if detail.get("amount") is not None else 0,
                "remarks": detail.get("remarks") if detail.get("remarks") else None,
                "hsn_code": detail.get("hsn_code") if detail.get("hsn_code") else None,
            }
            response["lines"].append(line)

        return response
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching inward by ID")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/create_inward")
def create_inward(
    payload: dict,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Create a procurement inward/GRN with detail rows."""

    def to_int(value, field_name: str, required: bool = False) -> int | None:
        if value is None or value == "":
            if required:
                raise HTTPException(status_code=400, detail=f"{field_name} is required")
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail=f"Invalid {field_name}")

    def to_positive_float(value, field_name: str, allow_zero: bool = False) -> float:
        if value is None or value == "":
            if allow_zero:
                return 0.0
            raise HTTPException(status_code=400, detail=f"{field_name} is required")
        try:
            num = float(value)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail=f"Invalid {field_name}")
        if not allow_zero and num <= 0:
            raise HTTPException(status_code=400, detail=f"{field_name} must be greater than zero")
        if num < 0:
            raise HTTPException(status_code=400, detail=f"{field_name} cannot be negative")
        return num

    try:
        # Parse required header fields
        branch_id = to_int(payload.get("branch"), "branch", required=True)
        supplier_id = to_int(payload.get("supplier"), "supplier", required=True)

        date_str = payload.get("inward_date")
        if not date_str:
            raise HTTPException(status_code=400, detail="inward_date is required")
        try:
            inward_date = datetime.strptime(str(date_str), "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid inward_date format, expected YYYY-MM-DD")

        # Parse optional header fields
        challan_no = payload.get("challan_no")
        if challan_no:
            challan_no = str(challan_no).strip()[:255]
        
        challan_date_str = payload.get("challan_date")
        challan_date = None
        if challan_date_str:
            try:
                challan_date = datetime.strptime(str(challan_date_str), "%Y-%m-%d").date()
            except ValueError:
                pass  # Ignore invalid date

        invoice_no = payload.get("invoice_no")
        invoice_date_str = payload.get("invoice_date")
        invoice_date = None
        if invoice_date_str:
            try:
                invoice_date = datetime.strptime(str(invoice_date_str), "%Y-%m-%d").date()
            except ValueError:
                pass  # Ignore invalid date

        # Invoice received date
        invoice_recvd_date_str = payload.get("invoice_recvd_date")
        invoice_recvd_date = None
        if invoice_recvd_date_str:
            try:
                invoice_recvd_date = datetime.strptime(str(invoice_recvd_date_str), "%Y-%m-%d").date()
            except ValueError:
                pass  # Ignore invalid date

        vehicle_no = payload.get("vehicle_no")
        if vehicle_no:
            vehicle_no = str(vehicle_no).strip()[:25]

        driver_name = payload.get("driver_name")
        if driver_name:
            driver_name = str(driver_name).strip()[:30]

        driver_contact_no = payload.get("driver_contact_no")
        if driver_contact_no:
            driver_contact_no = str(driver_contact_no).strip()[:25]

        # Consignment fields
        consignment_no = payload.get("consignment_no")
        if consignment_no:
            consignment_no = str(consignment_no).strip()[:255]

        consignment_date_str = payload.get("consignment_date")
        consignment_date = None
        if consignment_date_str:
            try:
                consignment_date = datetime.strptime(str(consignment_date_str), "%Y-%m-%d").date()
            except ValueError:
                pass  # Ignore invalid date

        # E-Way Bill fields
        ewaybillno = payload.get("ewaybillno")
        if ewaybillno:
            ewaybillno = str(ewaybillno).strip()[:255]

        ewaybill_date_str = payload.get("ewaybill_date")
        ewaybill_date = None
        if ewaybill_date_str:
            try:
                ewaybill_date = datetime.strptime(str(ewaybill_date_str), "%Y-%m-%d").date()
            except ValueError:
                pass  # Ignore invalid date

        # Remarks fields
        despatch_remarks = payload.get("despatch_remarks")
        if despatch_remarks:
            despatch_remarks = str(despatch_remarks).strip()[:500]

        receipts_remarks = payload.get("receipts_remarks")
        if receipts_remarks:
            receipts_remarks = str(receipts_remarks).strip()[:500]

        project_id = to_int(payload.get("project_id"), "project_id")

        # Parse items
        raw_items = payload.get("items")
        if not isinstance(raw_items, list) or len(raw_items) == 0:
            raise HTTPException(status_code=400, detail="At least one item row is required")

        updated_by = to_int(token_data.get("user_id"), "updated_by")
        created_at = now_ist()

        # Normalize line items
        normalized_items = []
        total_amount = 0.0
        for idx, item in enumerate(raw_items, start=1):
            po_dtl_id = to_int(item.get("po_dtl_id"), f"items[{idx}].po_dtl_id")
            item_id = to_int(item.get("item"), f"items[{idx}].item", required=True)
            qty = to_positive_float(item.get("quantity"), f"items[{idx}].quantity")
            rate = to_positive_float(item.get("rate"), f"items[{idx}].rate", allow_zero=True)
            uom_id = to_int(item.get("uom"), f"items[{idx}].uom", required=True)
            item_make_id = to_int(item.get("item_make"), f"items[{idx}].item_make")
            warehouse_id = to_int(item.get("warehouse_id"), f"items[{idx}].warehouse_id")

            item_remarks = item.get("remarks")
            if item_remarks:
                item_remarks = str(item_remarks).strip()[:255]

            hsn_code = item.get("hsn_code")
            if hsn_code:
                hsn_code = str(hsn_code).strip()[:50]

            amount = qty * rate
            total_amount += amount

            normalized_items.append({
                "po_dtl_id": po_dtl_id,
                "item_id": item_id,
                "qty": qty,
                "rate": rate,
                "uom_id": uom_id,
                "item_make_id": item_make_id,
                "warehouse_id": warehouse_id,
                "hsn_code": hsn_code,
                "remarks": item_remarks,
                "amount": amount,
            })

        logger.debug("Normalized inward items: %s", normalized_items)

        # Derive supplier_branch_id, bill_branch_id, ship_branch_id from linked PO
        supplier_branch_id = None
        bill_branch_id = None
        ship_branch_id = None
        first_po_dtl_id = next(
            (item["po_dtl_id"] for item in normalized_items if item.get("po_dtl_id")),
            None,
        )
        if first_po_dtl_id:
            from sqlalchemy import text as sa_text
            po_info = db.execute(
                sa_text("""
                    SELECT pp.supplier_branch_id, pp.billing_branch_id, pp.shipping_branch_id
                    FROM proc_po_dtl ppd
                    JOIN proc_po pp ON pp.po_id = ppd.po_id
                    WHERE ppd.po_dtl_id = :po_dtl_id
                    LIMIT 1
                """),
                {"po_dtl_id": first_po_dtl_id},
            ).fetchone()
            if po_info:
                po_row = dict(po_info._mapping)
                supplier_branch_id = po_row.get("supplier_branch_id")
                bill_branch_id = po_row.get("billing_branch_id")
                ship_branch_id = po_row.get("shipping_branch_id")

        # Compute per-branch per-financial-year inward sequence number.
        # Financial year: April 1 to March 31
        if inward_date.month >= 4:
            fy_start_year = inward_date.year
            fy_end_year = inward_date.year + 1
        else:
            fy_start_year = inward_date.year - 1
            fy_end_year = inward_date.year

        fy_start_date = datetime(fy_start_year, 4, 1).date()
        fy_end_date = datetime(fy_end_year, 3, 31).date()

        max_inward_query = get_max_inward_no_for_branch_fy()
        max_inward_result = db.execute(
            max_inward_query,
            {
                "branch_id": branch_id,
                "fy_start_date": fy_start_date,
                "fy_end_date": fy_end_date,
            },
        ).fetchone()

        if max_inward_result:
            max_inward_no = dict(max_inward_result._mapping).get("max_inward_no") or 0
            next_inward_no = max_inward_no + 1
        else:
            next_inward_no = 1

        # Insert header
        insert_header_query = insert_proc_inward()
        header_params = {
            "inward_sequence_no": next_inward_no,
            "supplier_id": supplier_id,
            "supplier_branch_id": supplier_branch_id,
            "vehicle_number": vehicle_no,
            "driver_name": driver_name,
            "driver_contact_number": driver_contact_no,
            "inward_date": inward_date,
            "despatch_remarks": despatch_remarks,
            "receipts_remarks": receipts_remarks,
            "updated_date_time": created_at,
            "updated_by": updated_by,
            "challan_no": challan_no,
            "challan_date": challan_date,
            "invoice_no": invoice_no,
            "invoice_amount": None,
            "invoice_date": invoice_date,
            "invoice_recvd_date": invoice_recvd_date,
            "consignment_no": consignment_no,
            "consignment_date": consignment_date,
            "ewaybillno": ewaybillno,
            "ewaybill_date": ewaybill_date,
            "bill_branch_id": bill_branch_id,
            "ship_branch_id": ship_branch_id,
            "branch_id": branch_id,
            "project_id": project_id,
            "gross_amount": total_amount,
            "net_amount": total_amount,
        }

        logger.info(
            "Creating inward: branch=%s, supplier=%s, item_rows=%s",
            branch_id,
            supplier_id,
            len(normalized_items),
        )
        logger.debug("Inward header params: %s", header_params)

        result = db.execute(insert_header_query, header_params)
        inward_id = result.lastrowid
        if not inward_id:
            raise HTTPException(status_code=500, detail="Failed to create inward header")

        # Insert detail rows
        detail_query = insert_proc_inward_dtl()
        for detail in normalized_items:
            db.execute(
                detail_query,
                {
                    "inward_id": inward_id,
                    "po_dtl_id": detail["po_dtl_id"],
                    "item_id": detail["item_id"],
                    "item_make_id": detail["item_make_id"],
                    "hsn_code": detail.get("hsn_code"),
                    "description": None,
                    "remarks": detail["remarks"],
                    "challan_qty": detail["qty"],
                    "inward_qty": detail["qty"],
                    "uom_id": detail["uom_id"],
                    "rate": detail["rate"],
                    "amount": detail["amount"],
                    "warehouse_id": detail["warehouse_id"],
                    "active": 1,
                    "status_id": 21,  # Draft status
                    "updated_date_time": created_at,
                    "updated_by": updated_by,
                },
            )

        db.commit()
        return {
            "message": "Inward created successfully",
            "inward_id": inward_id,
            "inward_no": next_inward_no,
        }
    except HTTPException as exc:
        db.rollback()
        logger.warning("Inward create failed with HTTP error: %s", getattr(exc, "detail", exc))
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Unexpected error while creating inward")
        raise HTTPException(
            status_code=500,
            detail={
                "message": "Failed to create inward",
                "error": str(e),
            },
        )


@router.put("/update_inward")
def update_inward(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Update an existing inward/GRN record with header and line items."""
    from src.procurement.query import update_proc_inward, update_proc_inward_dtl

    try:
        body = parse_json_body(request)
        inward_id = body.get("id")
        if not inward_id:
            raise HTTPException(status_code=400, detail="Inward ID is required")

        # Guard: prevent updates after material inspection is completed
        inspection_row = db.execute(
            text("SELECT inspection_check FROM proc_inward WHERE inward_id = :inward_id"),
            {"inward_id": int(inward_id)},
        ).fetchone()
        if inspection_row and inspection_row[0]:
            raise HTTPException(
                status_code=403,
                detail="Cannot modify inward after material inspection is completed",
            )

        # Guard: prevent updates to a fully cancelled inward
        cancelled_row = db.execute(
            text("SELECT COUNT(*) FROM proc_inward_dtl WHERE inward_id = :inward_id AND status_id != 6"),
            {"inward_id": int(inward_id)},
        ).fetchone()
        if cancelled_row and cancelled_row[0] == 0:
            raise HTTPException(status_code=403, detail="Cannot modify a cancelled inward")

        updated_by = token_data.get("user_id") if token_data else None
        updated_at = now_ist()

        # Parse header fields
        branch_id = body.get("branch")
        supplier_id = body.get("supplier")
        inward_date = body.get("inward_date")
        vehicle_number = body.get("vehicle_no")
        driver_name = body.get("driver_name")
        driver_contact_no = body.get("driver_contact_no")
        challan_no = body.get("challan_no")
        challan_date = body.get("challan_date")
        invoice_no = body.get("invoice_no")
        invoice_date = body.get("invoice_date")
        invoice_recvd_date = body.get("invoice_recvd_date")
        consignment_no = body.get("consignment_no")
        consignment_date = body.get("consignment_date")
        ewaybillno = body.get("ewaybillno")
        ewaybill_date = body.get("ewaybill_date")
        despatch_remarks = body.get("despatch_remarks")
        receipts_remarks = body.get("receipts_remarks")

        # Convert dates
        inward_date_obj = None
        if inward_date:
            try:
                inward_date_obj = datetime.strptime(inward_date[:10], "%Y-%m-%d").date()
            except ValueError:
                pass

        challan_date_obj = None
        if challan_date:
            try:
                challan_date_obj = datetime.strptime(challan_date[:10], "%Y-%m-%d").date()
            except ValueError:
                pass

        invoice_date_obj = None
        if invoice_date:
            try:
                invoice_date_obj = datetime.strptime(invoice_date[:10], "%Y-%m-%d").date()
            except ValueError:
                pass

        invoice_recvd_date_obj = None
        if invoice_recvd_date:
            try:
                invoice_recvd_date_obj = datetime.strptime(invoice_recvd_date[:10], "%Y-%m-%d").date()
            except ValueError:
                pass

        consignment_date_obj = None
        if consignment_date:
            try:
                consignment_date_obj = datetime.strptime(consignment_date[:10], "%Y-%m-%d").date()
            except ValueError:
                pass

        ewaybill_date_obj = None
        if ewaybill_date:
            try:
                ewaybill_date_obj = datetime.strptime(ewaybill_date[:10], "%Y-%m-%d").date()
            except ValueError:
                pass

        # Update header
        header_params = {
            "inward_id": int(inward_id),
            "supplier_id": int(supplier_id) if supplier_id else None,
            "vehicle_number": vehicle_number,
            "driver_name": driver_name,
            "driver_contact_number": driver_contact_no,
            "inward_date": inward_date_obj,
            "despatch_remarks": despatch_remarks,
            "receipts_remarks": receipts_remarks,
            "challan_no": challan_no,
            "challan_date": challan_date_obj,
            "invoice_no": invoice_no,
            "invoice_date": invoice_date_obj,
            "invoice_recvd_date": invoice_recvd_date_obj,
            "consignment_no": consignment_no,
            "consignment_date": consignment_date_obj,
            "ewaybillno": ewaybillno,
            "ewaybill_date": ewaybill_date_obj,
            "branch_id": int(branch_id) if branch_id else None,
            "updated_date_time": updated_at,
            "updated_by": updated_by,
        }

        update_header_query = update_proc_inward()
        db.execute(update_header_query, header_params)

        # Update line items
        items = body.get("items", [])
        for item in items:
            item_id = item.get("item")
            inward_qty = item.get("quantity")
            uom_id = item.get("uom")
            remarks = item.get("remarks")
            hsn_code = item.get("hsn_code")
            if hsn_code:
                hsn_code = str(hsn_code).strip()[:50]
            po_dtl_id = item.get("po_dtl_id")
            inward_dtl_id = item.get("inward_dtl_id")

            # Resolve the line: by inward_dtl_id when sent (covers no-PO inwards
            # where po_dtl_id is NULL), else by po_dtl_id.
            if inward_dtl_id:
                find_dtl_query = text("""
                    SELECT inward_dtl_id FROM proc_inward_dtl
                    WHERE inward_id = :inward_id AND inward_dtl_id = :inward_dtl_id
                """)
                dtl_result = db.execute(
                    find_dtl_query,
                    {"inward_id": int(inward_id), "inward_dtl_id": int(inward_dtl_id)},
                ).fetchone()
            elif po_dtl_id:
                find_dtl_query = text("""
                    SELECT inward_dtl_id FROM proc_inward_dtl
                    WHERE inward_id = :inward_id AND po_dtl_id = :po_dtl_id
                """)
                dtl_result = db.execute(
                    find_dtl_query,
                    {"inward_id": int(inward_id), "po_dtl_id": int(po_dtl_id)},
                ).fetchone()
            else:
                dtl_result = None

            if not dtl_result:
                raise HTTPException(
                    status_code=400,
                    detail=f"Line item (item {item_id}) could not be matched to an existing inward line",
                )

            update_dtl_query = update_proc_inward_dtl()
            db.execute(
                update_dtl_query,
                {
                    "inward_dtl_id": dtl_result[0],
                    "item_id": int(item_id) if item_id else None,
                    "hsn_code": hsn_code,
                    "remarks": remarks,
                    "inward_qty": float(inward_qty) if inward_qty else 0,
                    "uom_id": int(uom_id) if uom_id else None,
                    "updated_date_time": updated_at,
                    "updated_by": updated_by,
                },
            )

        db.commit()
        return {
            "message": "Inward updated successfully",
            "inward_id": inward_id,
        }
    except HTTPException as exc:
        db.rollback()
        logger.warning("Inward update failed with HTTP error: %s", getattr(exc, "detail", exc))
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Unexpected error while updating inward")
        raise HTTPException(
            status_code=500,
            detail={
                "message": "Failed to update inward",
                "error": str(e),
            },
        )


@router.post("/cancel_inward")
def cancel_inward(
    payload: dict,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Cancel an inward by setting all proc_inward_dtl lines to status_id = 6."""
    from src.procurement.query import cancel_inward_dtl_query

    try:
        inward_id = payload.get("inward_id")
        if inward_id is None:
            raise HTTPException(status_code=400, detail="inward_id is required")
        try:
            inward_id = int(inward_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid inward_id")

        # Verify inward exists and inspection has not been completed
        inspection_row = db.execute(
            text("SELECT inspection_check FROM proc_inward WHERE inward_id = :inward_id"),
            {"inward_id": inward_id},
        ).fetchone()
        if not inspection_row:
            raise HTTPException(status_code=404, detail="Inward not found")
        if inspection_row[0]:
            raise HTTPException(
                status_code=403,
                detail="Cannot cancel inward after material inspection is completed",
            )

        # Verify there are still active (non-cancelled) lines
        active_row = db.execute(
            text(
                "SELECT COUNT(*) FROM proc_inward_dtl "
                "WHERE inward_id = :inward_id AND status_id != 6"
            ),
            {"inward_id": inward_id},
        ).fetchone()
        if not active_row or active_row[0] == 0:
            raise HTTPException(status_code=400, detail="Inward is already cancelled")

        user_id = token_data.get("user_id") if token_data else None
        updated_at = now_ist()

        db.execute(
            cancel_inward_dtl_query(),
            {
                "inward_id": inward_id,
                "updated_by": user_id,
                "updated_date_time": updated_at,
            },
        )
        db.commit()

        return {
            "status": "success",
            "new_status_id": 6,
            "message": "Inward cancelled successfully",
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error cancelling inward")
        raise HTTPException(status_code=500, detail=str(e))


# from fastapi import Depends, Request, HTTPException, APIRouter
# import logging
# from sqlalchemy.orm import Session
# from typing import Optional
# from src.config.db import get_tenant_db
# from src.authorization.utils import get_current_user_with_refresh
# from src.procurement.query import (
# 	get_inward_table_query,
# 	get_inward_table_count_query,
# )
# from src.procurement.indent import (
# 	format_indent_no,
# 	calculate_financial_year,
# )

# logger = logging.getLogger(__name__)

# router = APIRouter()


# def format_inward_no(
# 	inward_sequence_no: Optional[int],
# 	co_prefix: Optional[str],
# 	branch_prefix: Optional[str],
# 	inward_date,
# ) -> str:
# 	"""Format inward number as 'co_prefix/branch_prefix/INW/financial_year/inward_sequence_no'."""
# 	if inward_sequence_no is None or inward_sequence_no == 0:
# 		return ""
	
# 	fy = calculate_financial_year(inward_date)
# 	co_pref = co_prefix or ""
# 	branch_pref = branch_prefix or ""
	
# 	parts = []
# 	if co_pref:
# 		parts.append(co_pref)
# 	if branch_pref:
# 		parts.append(branch_pref)
# 	parts.extend(["INW", fy, str(inward_sequence_no)])
	
# 	return "/".join(parts)


# def format_po_no(
# 	po_no: Optional[int],
# 	co_prefix: Optional[str],
# 	branch_prefix: Optional[str],
# 	po_date,
# ) -> str:
# 	"""Format PO number as 'co_prefix/branch_prefix/PO/financial_year/po_no'."""
# 	if po_no is None or po_no == 0:
# 		return ""
	
# 	fy = calculate_financial_year(po_date)
# 	co_pref = co_prefix or ""
# 	branch_pref = branch_prefix or ""
	
# 	parts = []
# 	if co_pref:
# 		parts.append(co_pref)
# 	if branch_pref:
# 		parts.append(branch_pref)
# 	parts.extend(["PO", fy, str(po_no)])
	
# 	return "/".join(parts)


# @router.get("/get_inward_table")
# async def get_inward_table(
# 	request: Request,
# 	db: Session = Depends(get_tenant_db),
# 	token_data: dict = Depends(get_current_user_with_refresh),
# 	page: int = 1,
# 	limit: int = 10,
# 	search: str | None = None,
# 	co_id: int | None = None,
# ):
# 	"""Return paginated inward list."""
# 	try:
# 		page = max(page, 1)
# 		limit = max(min(limit, 100), 1)
# 		offset = (page - 1) * limit
# 		search_like = None
# 		if search:
# 			search_like = f"%{search.strip()}%"

# 		params = {
# 			"co_id": co_id,
# 			"search_like": search_like,
# 			"limit": limit,
# 			"offset": offset,
# 		}

# 		list_query = get_inward_table_query()
# 		rows = db.execute(list_query, params).fetchall()
# 		data = []
# 		for row in rows:
# 			mapped = dict(row._mapping)
# 			inward_date_obj = mapped.get("inward_date")
# 			inward_date = inward_date_obj
# 			if hasattr(inward_date_obj, "isoformat"):
# 				inward_date = inward_date_obj.isoformat()

# 			# Format inward_no
# 			raw_inward_no = mapped.get("inward_sequence_no")
# 			formatted_inward_no = ""
# 			if raw_inward_no is not None and raw_inward_no != 0:
# 				try:
# 					inward_no_int = int(raw_inward_no) if raw_inward_no else None
# 					co_prefix = mapped.get("co_prefix")
# 					branch_prefix = mapped.get("branch_prefix")
# 					formatted_inward_no = format_inward_no(
# 						inward_sequence_no=inward_no_int,
# 						co_prefix=co_prefix,
# 						branch_prefix=branch_prefix,
# 						inward_date=inward_date_obj,
# 					)
# 				except Exception as e:
# 					logger.exception("Error formatting inward number, using raw value")
# 					formatted_inward_no = str(raw_inward_no) if raw_inward_no else ""

# 			# Format po_no
# 			raw_po_no = mapped.get("po_no")
# 			po_date_obj = mapped.get("po_date")
# 			formatted_po_no = ""
# 			if raw_po_no is not None and raw_po_no != 0:
# 				try:
# 					po_no_int = int(raw_po_no) if raw_po_no else None
# 					co_prefix = mapped.get("co_prefix")
# 					branch_prefix = mapped.get("branch_prefix")
# 					formatted_po_no = format_po_no(
# 						po_no=po_no_int,
# 						co_prefix=co_prefix,
# 						branch_prefix=branch_prefix,
# 						po_date=po_date_obj,
# 					)
# 				except Exception as e:
# 					logger.exception("Error formatting PO number, using raw value")
# 					formatted_po_no = str(raw_po_no) if raw_po_no else ""

# 			data.append(
# 				{
# 					"inward_id": mapped.get("inward_id"),
# 					"inward_no": formatted_inward_no,
# 					"inward_date": inward_date,
# 					"branch_name": mapped.get("branch_name") or "",
# 					"po_no": formatted_po_no,
# 					"supplier_name": mapped.get("supplier_name") or "",
# 					"status": mapped.get("status_name") or "Pending",
# 				}
# 			)

# 		count_query = get_inward_table_count_query()
# 		count_result = db.execute(count_query, params).scalar()
# 		total = int(count_result) if count_result is not None else 0

# 		return {"data": data, "total": total}
# 	except HTTPException:
# 		raise
# 	except Exception as e:
# 		logger.exception("Error fetching inward table")
# 		raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
