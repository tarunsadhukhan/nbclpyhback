from fastapi import Depends, Request, HTTPException, APIRouter
import logging
from sqlalchemy.orm import Session
from sqlalchemy.sql import text
from datetime import datetime
from typing import Optional
from src.common.utils import now_ist
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.masters.query import get_branch_list, get_item_group_drodown
from src.procurement.indent import (
    calculate_financial_year,
    format_indent_no,
)
from src.procurement.query import (
    get_item_make_by_group_id,
    get_company_branch_addresses,
)
from src.common.approval_utils import (
    process_approval,
    process_rejection,
    calculate_approval_permissions,
)
from src.sales.query import (
    get_item_by_group_id_saleable,
    get_item_uom_by_group_id_saleable,
    get_customers_for_sales,
    get_customer_branches_bulk,
    get_brokers_for_sales,
    insert_sales_quotation,
    insert_sales_quotation_dtl,
    insert_sales_quotation_dtl_gst,
    update_sales_quotation,
    delete_sales_quotation_dtl,
    delete_sales_quotation_dtl_gst,
    get_quotation_table_query,
    get_quotation_table_count_query,
    get_quotation_by_id_query,
    get_quotation_dtl_by_id_query,
    get_quotation_gst_by_dtl_id_query,
    update_quotation_status,
    get_quotation_with_approval_info,
    get_max_quotation_no_for_branch_fy,
    get_enquiries_for_sales_doc_query,
    get_enquiry_lines_for_sales_doc_query,
)
from src.common.companyAdmin.query import get_co_config_by_id_query
from src.sales.constants import SALES_DOC_TYPES
from src.sales.enquiry_constants import (
    ACTION_FORWARD,
    LINKED_DOC_QUOTATION,
    STAGE_COSTING_REVIEW,
    STAGE_PRICE_CHECK,
    STAGE_QUOTATION,
)
from src.sales.enquiry_hooks import (
    advance_enquiry_on_quotation_approved,
    log_stage_transition,
)
from src.sales.enquiry_query import get_enquiry_flow_state_query

logger = logging.getLogger(__name__)

router = APIRouter()


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def to_int(value, field_name: str, required: bool = False) -> int | None:
    if value is None or value == "":
        if required:
            raise HTTPException(status_code=400, detail=f"{field_name} is required")
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"Invalid {field_name}")


def to_float(value, field_name: str) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"Invalid {field_name}")


def to_positive_float(value, field_name: str) -> float:
    try:
        val = float(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"Invalid {field_name}")
    if val <= 0:
        raise HTTPException(status_code=400, detail=f"{field_name} must be greater than zero")
    return val


def format_date(date_val) -> str:
    """Convert a date/datetime to ISO string."""
    if date_val is None:
        return ""
    if hasattr(date_val, "date"):
        return date_val.date().isoformat()
    if hasattr(date_val, "isoformat"):
        return date_val.isoformat()
    return str(date_val)


def _sync_enquiry_stage_to_quotation(db: Session, sales_enquiry_id: int, sales_quotation_id: int, user_id: int) -> None:
    """FORWARD the linked enquiry to the QUOTATION stage when a quotation is
    created/updated against it (design §4) — no-op if the enquiry is already
    at QUOTATION or beyond, or has no stage yet. Runs inside the caller's
    transaction; the caller commits."""
    state_row = db.execute(
        get_enquiry_flow_state_query(), {"sales_enquiry_id": int(sales_enquiry_id)}
    ).fetchone()
    if not state_row:
        raise HTTPException(status_code=400, detail="Linked enquiry not found")
    state = dict(state_row._mapping)
    if state.get("stage_code") in (STAGE_COSTING_REVIEW, STAGE_PRICE_CHECK):
        log_stage_transition(
            db,
            sales_enquiry_id=int(sales_enquiry_id),
            from_stage_id=state.get("current_stage_id"),
            to_stage_code=STAGE_QUOTATION,
            action=ACTION_FORWARD,
            feedback="Quotation prepared",
            linked_doc_type=LINKED_DOC_QUOTATION,
            linked_doc_id=int(sales_quotation_id),
            user_id=int(user_id),
        )


def get_fy_boundaries(doc_date):
    """Calculate financial year start/end dates from a document date."""
    if hasattr(doc_date, "year") and hasattr(doc_date, "month"):
        year = doc_date.year
        month = doc_date.month
    elif hasattr(doc_date, "date"):
        d = doc_date.date()
        year = d.year
        month = d.month
    else:
        if isinstance(doc_date, str):
            d = datetime.strptime(doc_date, "%Y-%m-%d").date()
        else:
            d = datetime.fromisoformat(str(doc_date)).date()
        year = d.year
        month = d.month

    if month >= 4:
        fy_start_year = year
        fy_end_year = year + 1
    else:
        fy_start_year = year - 1
        fy_end_year = year

    return datetime(fy_start_year, 4, 1).date(), datetime(fy_end_year, 3, 31).date()


# =============================================================================
# SETUP ENDPOINTS
# =============================================================================

@router.get("/get_quotation_setup_1")
def get_quotation_setup_1(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    branch_id: int | None = None,
    co_id: int | None = None,
):
    """Return branches, customers, brokers, item groups, and branch addresses for quotation creation."""
    try:
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

        # Customers (party_type 2)
        customer_query = get_customers_for_sales(co_id=co_id)
        customer_result = db.execute(customer_query, {"co_id": co_id}).fetchall()
        customers = [dict(r._mapping) for r in customer_result]

        # Customer branches in bulk
        cust_branches_query = get_customer_branches_bulk(co_id=co_id)
        cust_branches_result = db.execute(cust_branches_query, {"co_id": co_id}).fetchall()
        branches_by_party: dict[int, list[dict]] = {}
        for row in cust_branches_result:
            bd = dict(row._mapping)
            pid = bd.get("party_id")
            if pid is not None:
                if pid not in branches_by_party:
                    branches_by_party[pid] = []
                branches_by_party[pid].append(bd)
        for cust in customers:
            cust["branches"] = branches_by_party.get(cust.get("party_id"), [])

        # Brokers
        broker_query = get_brokers_for_sales(co_id=co_id)
        broker_result = db.execute(broker_query, {"co_id": co_id}).fetchall()
        brokers = [dict(r._mapping) for r in broker_result]

        # Item groups
        itemgrp_query = get_item_group_drodown(co_id=co_id)
        itemgrp_result = db.execute(itemgrp_query, {"co_id": co_id}).fetchall()
        item_groups = [dict(r._mapping) for r in itemgrp_result]

        # Company branch addresses (for billing and shipping)
        branch_addresses_query = get_company_branch_addresses(co_id=co_id, branch_id=None)
        branch_addresses_result = db.execute(branch_addresses_query, {"co_id": co_id, "branch_id": None}).fetchall()
        branch_addresses = [dict(r._mapping) for r in branch_addresses_result]

        # Company config
        co_config_query = get_co_config_by_id_query(co_id)
        co_config_result = db.execute(co_config_query, {"co_id": co_id}).fetchone()
        co_config = dict(co_config_result._mapping) if co_config_result else {}

        # Build flat customer_branches list for frontend
        customer_branches = []
        for cust in customers:
            for branch in cust.get("branches", []):
                branch["party_id"] = cust.get("party_id")
                customer_branches.append(branch)

        # Open enquiries eligible as quotation source (approved, in a quotable stage)
        enquiries_result = db.execute(
            get_enquiries_for_sales_doc_query(),
            {"branch_id": branch_id, "co_id": co_id},
        ).fetchall()
        enquiries = [dict(r._mapping) for r in enquiries_result]

        return {
            "branches": branches,
            "customers": customers,
            "brokers": brokers,
            "item_groups": item_groups,
            "branch_addresses": branch_addresses,
            "co_config": co_config,
            "customer_branches": customer_branches,
            "enquiries": enquiries,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_quotation_setup_2")
def get_quotation_setup_2(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Return items, makes, and UOMs by item_group_id."""
    try:
        q_item_group = request.query_params.get("item_group")
        if q_item_group is None:
            raise HTTPException(status_code=400, detail="item_group is required")

        try:
            item_group_id = int(q_item_group)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid item_group")

        items_query = get_item_by_group_id_saleable(item_group_id=item_group_id)
        items_result = db.execute(items_query, {"item_group_id": item_group_id}).fetchall()
        items = [dict(r._mapping) for r in items_result]

        makes_query = get_item_make_by_group_id(item_group_id=item_group_id)
        makes_result = db.execute(makes_query, {"item_group_id": item_group_id}).fetchall()
        makes = [dict(r._mapping) for r in makes_result]

        uoms_query = get_item_uom_by_group_id_saleable(item_group_id=item_group_id)
        uoms_result = db.execute(uoms_query, {"item_group_id": item_group_id}).fetchall()
        uoms = [dict(r._mapping) for r in uoms_result]

        return {"items": items, "makes": makes, "uoms": uoms}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_enquiry_lines_for_quotation")
def get_enquiry_lines_for_quotation(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Enquiry lines (with confirmed cost basis) to pre-fill quotation lines."""
    try:
        q_enquiry_id = request.query_params.get("sales_enquiry_id")
        if q_enquiry_id is None:
            raise HTTPException(status_code=400, detail="sales_enquiry_id is required")
        try:
            sales_enquiry_id = int(q_enquiry_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid sales_enquiry_id")

        header_row = db.execute(
            get_enquiry_flow_state_query(), {"sales_enquiry_id": sales_enquiry_id}
        ).fetchone()
        if not header_row:
            raise HTTPException(status_code=404, detail="Enquiry not found")
        header = dict(header_row._mapping)

        lines_result = db.execute(
            get_enquiry_lines_for_sales_doc_query(),
            {"sales_enquiry_id": sales_enquiry_id},
        ).fetchall()
        lines = [dict(r._mapping) for r in lines_result]

        return {"data": lines, "master": {"enquiry": header}}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching enquiry lines for quotation")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# CRUD ENDPOINTS
# =============================================================================

@router.get("/get_quotation_table")
def get_quotation_table(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    page: int = 1,
    limit: int = 10,
    search: str | None = None,
    co_id: int | None = None,
    branch_id: int | None = None,
    status_id: int | None = None,
):
    """Return paginated sales quotation list."""
    try:
        page = max(page, 1)
        limit = max(min(limit, 100), 1)
        offset = (page - 1) * limit
        search_like = f"%{search.strip()}%" if search else None

        params = {
            "co_id": co_id,
            "branch_id": branch_id,
            "status_id": status_id,
            "search_like": search_like,
            "limit": limit,
            "offset": offset,
        }

        list_query = get_quotation_table_query()
        rows = db.execute(list_query, params).fetchall()
        data = []
        for row in rows:
            mapped = dict(row._mapping)
            raw_no = mapped.get("quotation_no")
            formatted_no = ""
            if raw_no is not None:
                try:
                    formatted_no = format_indent_no(
                        indent_no=int(raw_no) if raw_no else None,
                        co_prefix=mapped.get("co_prefix"),
                        branch_prefix=mapped.get("branch_prefix"),
                        indent_date=mapped.get("quotation_date"),
                        document_type=SALES_DOC_TYPES["QUOTATION"],
                    )
                except Exception:
                    formatted_no = str(raw_no) if raw_no else ""

            data.append({
                "sales_quotation_id": mapped.get("sales_quotation_id"),
                "quotation_no": formatted_no,
                "quotation_date": format_date(mapped.get("quotation_date")),
                "quotation_expiry_date": format_date(mapped.get("quotation_expiry_date")),
                "branch_id": mapped.get("branch_id"),
                "branch_name": mapped.get("branch_name"),
                "party_name": mapped.get("party_name"),
                "net_amount": mapped.get("net_amount"),
                "status": mapped.get("status_name"),
                "status_id": mapped.get("status_id"),
            })

        count_query = get_quotation_table_count_query()
        count_result = db.execute(count_query, {"co_id": co_id, "branch_id": branch_id, "status_id": status_id, "search_like": search_like}).scalar()
        total = int(count_result) if count_result is not None else 0

        return {"data": data, "total": total}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_quotation_by_id")
def get_quotation_by_id(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Return quotation details by ID with all line items and GST."""
    try:
        q_id = request.query_params.get("sales_quotation_id")
        q_co_id = request.query_params.get("co_id")

        if q_id is None:
            raise HTTPException(status_code=400, detail="sales_quotation_id is required")
        if q_co_id is None:
            raise HTTPException(status_code=400, detail="co_id is required")

        try:
            sales_quotation_id = int(q_id)
            co_id = int(q_co_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid sales_quotation_id or co_id")

        # Header
        header_query = get_quotation_by_id_query()
        header_result = db.execute(header_query, {"sales_quotation_id": sales_quotation_id, "co_id": co_id}).fetchone()
        if not header_result:
            raise HTTPException(status_code=404, detail="Quotation not found or access denied")
        header = dict(header_result._mapping)

        # Details
        detail_query = get_quotation_dtl_by_id_query()
        detail_results = db.execute(detail_query, {"sales_quotation_id": sales_quotation_id}).fetchall()
        details = [dict(r._mapping) for r in detail_results]

        # GST
        gst_query = get_quotation_gst_by_dtl_id_query()
        gst_results = db.execute(gst_query, {"sales_quotation_id": sales_quotation_id}).fetchall()
        gst_map: dict[int, dict] = {}
        for g in gst_results:
            gd = dict(g._mapping)
            gst_map[gd.get("quotation_lineitem_id")] = gd

        # Format quotation_no
        raw_no = header.get("quotation_no")
        formatted_no = ""
        if raw_no is not None:
            try:
                formatted_no = format_indent_no(
                    indent_no=int(raw_no) if raw_no else None,
                    co_prefix=header.get("co_prefix"),
                    branch_prefix=header.get("branch_prefix"),
                    indent_date=header.get("quotation_date"),
                    document_type=SALES_DOC_TYPES["QUOTATION"],
                )
            except Exception:
                formatted_no = str(raw_no) if raw_no else ""

        approval_level = header.get("approval_level")
        if approval_level is not None:
            try:
                approval_level = int(approval_level)
            except (TypeError, ValueError):
                approval_level = None

        status_id = header.get("status_id")
        branch_id = header.get("branch_id")

        # Permissions
        q_menu_id = request.query_params.get("menu_id")
        permissions = None
        if q_menu_id is not None and branch_id is not None and status_id is not None:
            try:
                permissions = calculate_approval_permissions(
                    user_id=int(token_data.get("user_id")),
                    menu_id=int(q_menu_id),
                    branch_id=branch_id,
                    status_id=status_id,
                    current_approval_level=approval_level,
                    db=db,
                )
            except Exception:
                logger.exception("Error calculating permissions")

        # Build response
        response = {
            "id": str(header.get("sales_quotation_id", "")),
            "quotationNo": formatted_no,
            "quotationDate": format_date(header.get("quotation_date")),
            "quotationExpiryDate": format_date(header.get("quotation_expiry_date")),
            "branch": str(header.get("branch_id", "")) if header.get("branch_id") else "",
            "party": str(header.get("party_id", "")) if header.get("party_id") else "",
            "partyName": header.get("party_name"),
            "broker": str(header.get("sales_broker_id", "")) if header.get("sales_broker_id") else None,
            "brokerName": header.get("broker_name"),
            "billingAddress": str(header.get("billing_address_id", "")) if header.get("billing_address_id") else None,
            "shippingAddress": str(header.get("shipping_address_id", "")) if header.get("shipping_address_id") else None,
            "billingAddressState": header.get("billing_state_name"),
            "shippingAddressState": header.get("shipping_state_name"),
            "branchStateName": header.get("branch_state_name"),
            "brokeragePercentage": header.get("brokerage_percentage"),
            "footerNotes": header.get("footer_notes"),
            "grossAmount": header.get("gross_amount"),
            "netAmount": header.get("net_amount"),
            "roundOffValue": header.get("round_off_value"),
            "paymentTerms": header.get("payment_terms"),
            "deliveryTerms": header.get("delivery_terms"),
            "deliveryDays": header.get("delivery_days"),
            "termsCondition": header.get("terms_condition"),
            "internalNote": header.get("internal_note"),
            "salesEnquiryId": str(header.get("sales_enquiry_id", "")) if header.get("sales_enquiry_id") else None,
            "enquiryNo": header.get("enquiry_no"),
            "status": header.get("status_name"),
            "statusId": status_id,
            "approvalLevel": approval_level,
            "updatedBy": str(header.get("updated_by", "")) if header.get("updated_by") else None,
            "updatedAt": format_date(header.get("updated_date_time")),
            "lines": [],
        }

        if permissions is not None:
            response["permissions"] = permissions

        for detail in details:
            line_id = detail.get("quotation_lineitem_id")
            gst = gst_map.get(line_id, {})
            line = {
                "id": str(line_id) if line_id else "",
                "hsnCode": detail.get("hsn_code"),
                "itemGroup": str(detail.get("item_grp_id", "")) if detail.get("item_grp_id") else "",
                "item": str(detail.get("item_id", "")) if detail.get("item_id") else "",
                "itemName": detail.get("item_name"),
                "itemMake": str(detail.get("item_make_id", "")) if detail.get("item_make_id") else None,
                "quantity": float(detail.get("quantity", 0)) if detail.get("quantity") is not None else 0,
                "uom": str(detail.get("uom_id", "")) if detail.get("uom_id") else "",
                "uomName": detail.get("uom_name"),
                "rate": detail.get("rate"),
                "discountType": detail.get("discount_type"),
                "discountedRate": detail.get("discounted_rate"),
                "discountAmount": detail.get("discount_amount"),
                "netAmount": detail.get("net_amount"),
                "totalAmount": detail.get("total_amount"),
                "remarks": detail.get("remarks"),
                "enquiryDtlId": str(detail.get("enquiry_dtl_id", "")) if detail.get("enquiry_dtl_id") else None,
                "costSnapshotId": str(detail.get("cost_snapshot_id", "")) if detail.get("cost_snapshot_id") else None,
                "baseCost": detail.get("base_cost"),
                "overheadPct": detail.get("overhead_pct"),
                "marginPct": detail.get("margin_pct"),
                "gst": {
                    "igstAmount": gst.get("igst_amount"),
                    "igstPercent": gst.get("igst_percent"),
                    "cgstAmount": gst.get("cgst_amount"),
                    "cgstPercent": gst.get("cgst_percent"),
                    "sgstAmount": gst.get("sgst_amount"),
                    "sgstPercent": gst.get("sgst_percent"),
                    "gstTotal": gst.get("gst_total"),
                } if gst else None,
            }
            response["lines"].append(line)

        return response
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching quotation by ID")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/create_quotation")
def create_quotation(
    payload: dict,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Create a sales quotation with detail rows and GST."""
    try:
        # Accept both short names (branch, party) and suffixed names (branch_id, party_id)
        branch_id = to_int(payload.get("branch_id") or payload.get("branch"), "branch", required=True)
        party_id = to_int(payload.get("party_id") or payload.get("party"), "party")
        sales_broker_id_check = to_int(payload.get("sales_broker_id") or payload.get("broker"), "broker")
        if not party_id and not sales_broker_id_check:
            raise HTTPException(status_code=400, detail="At least one of customer or broker is required")

        date_str = payload.get("quotation_date") or payload.get("date")
        if not date_str:
            raise HTTPException(status_code=400, detail="date is required")
        try:
            quotation_date = datetime.strptime(str(date_str), "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format, expected YYYY-MM-DD")

        raw_items = payload.get("items")
        if not isinstance(raw_items, list) or len(raw_items) == 0:
            raise HTTPException(status_code=400, detail="At least one item row is required")

        updated_by = to_int(token_data.get("user_id"), "updated_by")
        created_at = now_ist()

        # Optional header fields — accept both short and suffixed names
        sales_broker_id = sales_broker_id_check
        billing_address_id = to_int(payload.get("billing_address_id") or payload.get("billing_address"), "billing_address")
        shipping_address_id = to_int(payload.get("shipping_address_id") or payload.get("shipping_address"), "shipping_address")
        expiry_str = payload.get("quotation_expiry_date") or payload.get("expiry_date")
        quotation_expiry_date = None
        if expiry_str:
            try:
                quotation_expiry_date = datetime.strptime(str(expiry_str), "%Y-%m-%d").date()
            except ValueError:
                pass
        brokerage_percentage = to_float(payload.get("brokerage_percentage"), "brokerage_percentage")
        gross_amount = to_float(payload.get("gross_amount"), "gross_amount")
        net_amount = to_float(payload.get("net_amount"), "net_amount")
        round_off_value = to_float(payload.get("round_off_value"), "round_off_value")
        delivery_days = to_int(payload.get("delivery_days"), "delivery_days")
        sales_enquiry_id = to_int(payload.get("sales_enquiry_id"), "sales_enquiry_id")

        # Normalize items — accept both short and suffixed field names
        normalized_items = []
        for idx, item in enumerate(raw_items, start=1):
            item_id = to_int(item.get("item_id") or item.get("item"), f"items[{idx}].item", required=True)
            quantity = to_positive_float(item.get("quantity"), f"items[{idx}].quantity")
            uom_id = to_int(item.get("uom_id") or item.get("uom"), f"items[{idx}].uom", required=True)
            normalized_items.append({
                "item_id": item_id,
                "item_make_id": to_int(item.get("item_make_id") or item.get("item_make"), f"items[{idx}].item_make"),
                "hsn_code": item.get("hsn_code"),
                "quantity": quantity,
                "uom_id": uom_id,
                "rate": to_float(item.get("rate"), f"items[{idx}].rate"),
                "discount_type": to_int(item.get("discount_type"), f"items[{idx}].discount_type"),
                "discounted_rate": to_float(item.get("discounted_rate"), f"items[{idx}].discounted_rate"),
                "discount_amount": to_float(item.get("discount_amount"), f"items[{idx}].discount_amount"),
                "net_amount": to_float(item.get("net_amount"), f"items[{idx}].net_amount"),
                "total_amount": to_float(item.get("total_amount"), f"items[{idx}].total_amount"),
                "remarks": str(item.get("remarks", "")).strip()[:255] if item.get("remarks") else None,
                "enquiry_dtl_id": to_int(item.get("enquiry_dtl_id"), f"items[{idx}].enquiry_dtl_id"),
                "cost_snapshot_id": to_int(item.get("cost_snapshot_id"), f"items[{idx}].cost_snapshot_id"),
                "base_cost": to_float(item.get("base_cost"), f"items[{idx}].base_cost"),
                "overhead_pct": to_float(item.get("overhead_pct"), f"items[{idx}].overhead_pct"),
                "margin_pct": to_float(item.get("margin_pct"), f"items[{idx}].margin_pct"),
                "gst": item.get("gst"),
            })

        # Insert header
        insert_header = insert_sales_quotation()
        header_params = {
            "updated_by": updated_by,
            "updated_date_time": created_at,
            "quotation_date": quotation_date,
            "quotation_no": None,
            "branch_id": branch_id,
            "party_id": party_id,
            "sales_broker_id": sales_broker_id,
            "billing_address_id": billing_address_id,
            "shipping_address_id": shipping_address_id,
            "quotation_expiry_date": quotation_expiry_date,
            "footer_notes": payload.get("footer_notes"),
            "brokerage_percentage": brokerage_percentage,
            "gross_amount": gross_amount,
            "net_amount": net_amount,
            "round_off_value": round_off_value,
            "payment_terms": payload.get("payment_terms"),
            "delivery_terms": payload.get("delivery_terms"),
            "delivery_days": delivery_days,
            "terms_condition": payload.get("terms_condition"),
            "internal_note": payload.get("internal_note"),
            "sales_enquiry_id": sales_enquiry_id,
            "status_id": 21,
            "approval_level": 0,
            "active": 1,
        }

        result = db.execute(insert_header, header_params)
        sales_quotation_id = result.lastrowid
        if not sales_quotation_id:
            raise HTTPException(status_code=500, detail="Failed to create quotation header")

        # Insert details and GST
        dtl_query = insert_sales_quotation_dtl()
        gst_query = insert_sales_quotation_dtl_gst()
        for item in normalized_items:
            dtl_result = db.execute(dtl_query, {
                "updated_by": updated_by,
                "updated_date_time": created_at,
                "sales_quotation_id": sales_quotation_id,
                "hsn_code": item["hsn_code"],
                "item_id": item["item_id"],
                "item_make_id": item["item_make_id"],
                "quantity": item["quantity"],
                "uom_id": item["uom_id"],
                "rate": item["rate"],
                "discount_type": item["discount_type"],
                "discounted_rate": item["discounted_rate"],
                "discount_amount": item["discount_amount"],
                "net_amount": item["net_amount"],
                "total_amount": item["total_amount"],
                "remarks": item["remarks"],
                "enquiry_dtl_id": item["enquiry_dtl_id"],
                "cost_snapshot_id": item["cost_snapshot_id"],
                "base_cost": item["base_cost"],
                "overhead_pct": item["overhead_pct"],
                "margin_pct": item["margin_pct"],
                "active": 1,
            })
            lineitem_id = dtl_result.lastrowid

            # Insert GST if provided
            gst_data = item.get("gst")
            if gst_data and isinstance(gst_data, dict) and lineitem_id:
                db.execute(gst_query, {
                    "quotation_lineitem_id": lineitem_id,
                    "igst_amount": to_float(gst_data.get("igst_amount"), "igst_amount"),
                    "igst_percent": to_float(gst_data.get("igst_percent"), "igst_percent"),
                    "cgst_amount": to_float(gst_data.get("cgst_amount"), "cgst_amount"),
                    "cgst_percent": to_float(gst_data.get("cgst_percent"), "cgst_percent"),
                    "sgst_amount": to_float(gst_data.get("sgst_amount"), "sgst_amount"),
                    "sgst_percent": to_float(gst_data.get("sgst_percent"), "sgst_percent"),
                    "gst_total": to_float(gst_data.get("gst_total"), "gst_total"),
                })

        # Keep the linked enquiry's stage in sync (design §4)
        if sales_enquiry_id:
            _sync_enquiry_stage_to_quotation(db, sales_enquiry_id, sales_quotation_id, updated_by)

        db.commit()
        return {
            "message": "Quotation created successfully",
            "sales_quotation_id": sales_quotation_id,
        }
    except HTTPException as exc:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error creating quotation")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/update_quotation")
def update_quotation(
    payload: dict,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Update a sales quotation with detail rows and GST."""
    try:
        sales_quotation_id = to_int(payload.get("sales_quotation_id") or payload.get("id"), "id", required=True)
        branch_id = to_int(payload.get("branch_id") or payload.get("branch"), "branch", required=True)
        party_id = to_int(payload.get("party_id") or payload.get("party"), "party")
        sales_broker_id_check = to_int(payload.get("sales_broker_id") or payload.get("broker"), "broker")
        if not party_id and not sales_broker_id_check:
            raise HTTPException(status_code=400, detail="At least one of customer or broker is required")

        date_str = payload.get("quotation_date") or payload.get("date")
        if not date_str:
            raise HTTPException(status_code=400, detail="date is required")
        try:
            quotation_date = datetime.strptime(str(date_str), "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format, expected YYYY-MM-DD")

        raw_items = payload.get("items")
        if not isinstance(raw_items, list) or len(raw_items) == 0:
            raise HTTPException(status_code=400, detail="At least one item row is required")

        # Verify exists
        check_query = text("SELECT sales_quotation_id, quotation_no, active, status_id FROM sales_quotation WHERE sales_quotation_id = :id AND active = 1")
        check_result = db.execute(check_query, {"id": sales_quotation_id}).fetchone()
        if not check_result:
            raise HTTPException(status_code=404, detail="Quotation not found or inactive")
        existing = dict(check_result._mapping)

        updated_by = to_int(token_data.get("user_id"), "updated_by")
        updated_at = now_ist()

        # Optional fields — accept both short and suffixed names
        sales_broker_id = sales_broker_id_check
        billing_address_id = to_int(payload.get("billing_address_id") or payload.get("billing_address"), "billing_address")
        shipping_address_id = to_int(payload.get("shipping_address_id") or payload.get("shipping_address"), "shipping_address")
        expiry_str = payload.get("quotation_expiry_date") or payload.get("expiry_date")
        quotation_expiry_date = None
        if expiry_str:
            try:
                quotation_expiry_date = datetime.strptime(str(expiry_str), "%Y-%m-%d").date()
            except ValueError:
                pass
        brokerage_percentage = to_float(payload.get("brokerage_percentage"), "brokerage_percentage")
        gross_amount = to_float(payload.get("gross_amount"), "gross_amount")
        net_amount = to_float(payload.get("net_amount"), "net_amount")
        round_off_value = to_float(payload.get("round_off_value"), "round_off_value")
        delivery_days = to_int(payload.get("delivery_days"), "delivery_days")
        sales_enquiry_id = to_int(payload.get("sales_enquiry_id"), "sales_enquiry_id")

        # Normalize items — accept both short and suffixed field names
        normalized_items = []
        for idx, item in enumerate(raw_items, start=1):
            item_id = to_int(item.get("item_id") or item.get("item"), f"items[{idx}].item", required=True)
            quantity = to_positive_float(item.get("quantity"), f"items[{idx}].quantity")
            uom_id = to_int(item.get("uom_id") or item.get("uom"), f"items[{idx}].uom", required=True)
            normalized_items.append({
                "item_id": item_id,
                "item_make_id": to_int(item.get("item_make_id") or item.get("item_make"), f"items[{idx}].item_make"),
                "hsn_code": item.get("hsn_code"),
                "quantity": quantity,
                "uom_id": uom_id,
                "rate": to_float(item.get("rate"), f"items[{idx}].rate"),
                "discount_type": to_int(item.get("discount_type"), f"items[{idx}].discount_type"),
                "discounted_rate": to_float(item.get("discounted_rate"), f"items[{idx}].discounted_rate"),
                "discount_amount": to_float(item.get("discount_amount"), f"items[{idx}].discount_amount"),
                "net_amount": to_float(item.get("net_amount"), f"items[{idx}].net_amount"),
                "total_amount": to_float(item.get("total_amount"), f"items[{idx}].total_amount"),
                "remarks": str(item.get("remarks", "")).strip()[:255] if item.get("remarks") else None,
                "enquiry_dtl_id": to_int(item.get("enquiry_dtl_id"), f"items[{idx}].enquiry_dtl_id"),
                "cost_snapshot_id": to_int(item.get("cost_snapshot_id"), f"items[{idx}].cost_snapshot_id"),
                "base_cost": to_float(item.get("base_cost"), f"items[{idx}].base_cost"),
                "overhead_pct": to_float(item.get("overhead_pct"), f"items[{idx}].overhead_pct"),
                "margin_pct": to_float(item.get("margin_pct"), f"items[{idx}].margin_pct"),
                "gst": item.get("gst"),
            })

        # Update header
        update_header = update_sales_quotation()
        db.execute(update_header, {
            "sales_quotation_id": sales_quotation_id,
            "updated_by": updated_by,
            "updated_date_time": updated_at,
            "quotation_date": quotation_date,
            "branch_id": branch_id,
            "party_id": party_id,
            "sales_broker_id": sales_broker_id,
            "billing_address_id": billing_address_id,
            "shipping_address_id": shipping_address_id,
            "quotation_expiry_date": quotation_expiry_date,
            "footer_notes": payload.get("footer_notes"),
            "brokerage_percentage": brokerage_percentage,
            "gross_amount": gross_amount,
            "net_amount": net_amount,
            "round_off_value": round_off_value,
            "payment_terms": payload.get("payment_terms"),
            "delivery_terms": payload.get("delivery_terms"),
            "delivery_days": delivery_days,
            "terms_condition": payload.get("terms_condition"),
            "internal_note": payload.get("internal_note"),
            "sales_enquiry_id": sales_enquiry_id,
            "quotation_no": existing.get("quotation_no"),
            "active": existing.get("active"),
            "status_id": existing.get("status_id"),
        })

        # Delete old GST, then soft-delete old details
        delete_gst_q = delete_sales_quotation_dtl_gst()
        db.execute(delete_gst_q, {"sales_quotation_id": sales_quotation_id})

        delete_dtl_q = delete_sales_quotation_dtl()
        db.execute(delete_dtl_q, {
            "sales_quotation_id": sales_quotation_id,
            "updated_by": updated_by,
            "updated_date_time": updated_at,
        })

        # Re-insert details and GST
        dtl_query = insert_sales_quotation_dtl()
        gst_query = insert_sales_quotation_dtl_gst()
        for item in normalized_items:
            dtl_result = db.execute(dtl_query, {
                "updated_by": updated_by,
                "updated_date_time": updated_at,
                "sales_quotation_id": sales_quotation_id,
                "hsn_code": item["hsn_code"],
                "item_id": item["item_id"],
                "item_make_id": item["item_make_id"],
                "quantity": item["quantity"],
                "uom_id": item["uom_id"],
                "rate": item["rate"],
                "discount_type": item["discount_type"],
                "discounted_rate": item["discounted_rate"],
                "discount_amount": item["discount_amount"],
                "net_amount": item["net_amount"],
                "total_amount": item["total_amount"],
                "remarks": item["remarks"],
                "enquiry_dtl_id": item["enquiry_dtl_id"],
                "cost_snapshot_id": item["cost_snapshot_id"],
                "base_cost": item["base_cost"],
                "overhead_pct": item["overhead_pct"],
                "margin_pct": item["margin_pct"],
                "active": 1,
            })
            lineitem_id = dtl_result.lastrowid

            gst_data = item.get("gst")
            if gst_data and isinstance(gst_data, dict) and lineitem_id:
                db.execute(gst_query, {
                    "quotation_lineitem_id": lineitem_id,
                    "igst_amount": to_float(gst_data.get("igst_amount"), "igst_amount"),
                    "igst_percent": to_float(gst_data.get("igst_percent"), "igst_percent"),
                    "cgst_amount": to_float(gst_data.get("cgst_amount"), "cgst_amount"),
                    "cgst_percent": to_float(gst_data.get("cgst_percent"), "cgst_percent"),
                    "sgst_amount": to_float(gst_data.get("sgst_amount"), "sgst_amount"),
                    "sgst_percent": to_float(gst_data.get("sgst_percent"), "sgst_percent"),
                    "gst_total": to_float(gst_data.get("gst_total"), "gst_total"),
                })

        # Keep the linked enquiry's stage in sync (design §4)
        if sales_enquiry_id:
            _sync_enquiry_stage_to_quotation(db, sales_enquiry_id, sales_quotation_id, updated_by)

        db.commit()
        return {
            "message": "Quotation updated successfully",
            "sales_quotation_id": sales_quotation_id,
        }
    except HTTPException as exc:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error updating quotation")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# WORKFLOW ENDPOINTS
# =============================================================================

@router.post("/open_quotation")
def open_quotation(
    payload: dict,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Open a quotation (21 -> 1). Generates document number."""
    try:
        sales_quotation_id = to_int(payload.get("sales_quotation_id"), "sales_quotation_id", required=True)
        branch_id = to_int(payload.get("branch_id"), "branch_id", required=True)

        user_id = int(token_data.get("user_id"))

        doc_query = get_quotation_with_approval_info()
        doc_result = db.execute(doc_query, {"sales_quotation_id": sales_quotation_id}).fetchone()
        if not doc_result:
            raise HTTPException(status_code=404, detail="Quotation not found")
        doc = dict(doc_result._mapping)

        if doc.get("status_id") != 21:
            raise HTTPException(status_code=400, detail=f"Cannot open quotation with status_id {doc.get('status_id')}. Expected 21 (Draft).")

        quotation_date = doc.get("quotation_date")
        if not quotation_date:
            raise HTTPException(status_code=400, detail="Quotation date is required to generate document number.")

        current_no = doc.get("quotation_no")
        new_no = None
        if current_no is None or current_no == "" or current_no == "0":
            fy_start, fy_end = get_fy_boundaries(quotation_date)
            max_query = get_max_quotation_no_for_branch_fy()
            max_result = db.execute(max_query, {
                "branch_id": branch_id,
                "fy_start_date": fy_start,
                "fy_end_date": fy_end,
            }).fetchone()
            max_no = dict(max_result._mapping).get("max_doc_no") or 0 if max_result else 0
            new_no = str(max_no + 1)

        updated_at = now_ist()
        update_q = update_quotation_status()
        db.execute(update_q, {
            "sales_quotation_id": sales_quotation_id,
            "status_id": 1,
            "approval_level": None,
            "updated_by": user_id,
            "updated_date_time": updated_at,
            "quotation_no": new_no,
        })
        db.commit()

        return {
            "status": "success",
            "new_status_id": 1,
            "message": "Quotation opened successfully.",
            "quotation_no": new_no if new_no else current_no,
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error opening quotation")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cancel_draft_quotation")
def cancel_draft_quotation(
    payload: dict,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Cancel a draft quotation (21 -> 6)."""
    try:
        sales_quotation_id = to_int(payload.get("sales_quotation_id"), "sales_quotation_id", required=True)
        user_id = int(token_data.get("user_id"))

        doc_query = get_quotation_with_approval_info()
        doc_result = db.execute(doc_query, {"sales_quotation_id": sales_quotation_id}).fetchone()
        if not doc_result:
            raise HTTPException(status_code=404, detail="Quotation not found")
        doc = dict(doc_result._mapping)

        if doc.get("status_id") != 21:
            raise HTTPException(status_code=400, detail=f"Cannot cancel quotation with status_id {doc.get('status_id')}. Expected 21 (Draft).")

        updated_at = now_ist()
        update_q = update_quotation_status()
        db.execute(update_q, {
            "sales_quotation_id": sales_quotation_id,
            "status_id": 6,
            "approval_level": None,
            "updated_by": user_id,
            "updated_date_time": updated_at,
            "quotation_no": None,
        })
        db.commit()
        return {"status": "success", "new_status_id": 6, "message": "Draft cancelled successfully."}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error cancelling draft quotation")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/send_quotation_for_approval")
def send_quotation_for_approval(
    payload: dict,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Send quotation for approval (1 -> 20, level=1)."""
    try:
        sales_quotation_id = to_int(payload.get("sales_quotation_id"), "sales_quotation_id", required=True)
        user_id = int(token_data.get("user_id"))

        doc_query = get_quotation_with_approval_info()
        doc_result = db.execute(doc_query, {"sales_quotation_id": sales_quotation_id}).fetchone()
        if not doc_result:
            raise HTTPException(status_code=404, detail="Quotation not found")
        doc = dict(doc_result._mapping)

        if doc.get("status_id") != 1:
            raise HTTPException(status_code=400, detail=f"Cannot send for approval with status_id {doc.get('status_id')}. Expected 1 (Open).")

        updated_at = now_ist()
        update_q = update_quotation_status()
        db.execute(update_q, {
            "sales_quotation_id": sales_quotation_id,
            "status_id": 20,
            "approval_level": 1,
            "updated_by": user_id,
            "updated_date_time": updated_at,
            "quotation_no": None,
        })
        db.commit()
        return {"status": "success", "new_status_id": 20, "new_approval_level": 1, "message": "Quotation sent for approval."}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error sending quotation for approval")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/approve_quotation")
def approve_quotation(
    payload: dict,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Approve a quotation (with value check)."""
    try:
        sales_quotation_id = to_int(payload.get("sales_quotation_id"), "sales_quotation_id", required=True)
        menu_id = to_int(payload.get("menu_id"), "menu_id", required=True)
        user_id = int(token_data.get("user_id"))

        # Get document amount for value-based approval
        doc_query = get_quotation_with_approval_info()
        doc_result = db.execute(doc_query, {"sales_quotation_id": sales_quotation_id}).fetchone()
        if not doc_result:
            raise HTTPException(status_code=404, detail="Quotation not found")
        document_amount = float(dict(doc_result._mapping).get("net_amount", 0) or 0)

        result = process_approval(
            doc_id=sales_quotation_id,
            user_id=user_id,
            menu_id=menu_id,
            db=db,
            get_doc_fn=get_quotation_with_approval_info,
            update_status_fn=update_quotation_status,
            id_param_name="sales_quotation_id",
            doc_name="Quotation",
            document_amount=document_amount,
            extra_update_params={"quotation_no": None},
            commit=False,
        )
        # Final approval: log an AUTO entry on the linked enquiry (same transaction)
        if result.get("new_status_id") == 3:
            advance_enquiry_on_quotation_approved(db, sales_quotation_id, user_id)
        db.commit()
        return result
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error approving quotation")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reject_quotation")
def reject_quotation(
    payload: dict,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Reject a quotation (20 -> 4)."""
    try:
        sales_quotation_id = to_int(payload.get("sales_quotation_id"), "sales_quotation_id", required=True)
        menu_id = to_int(payload.get("menu_id"), "menu_id")
        user_id = int(token_data.get("user_id"))
        reason = payload.get("reason")

        result = process_rejection(
            doc_id=sales_quotation_id,
            user_id=user_id,
            menu_id=menu_id,
            db=db,
            get_doc_fn=get_quotation_with_approval_info,
            update_status_fn=update_quotation_status,
            id_param_name="sales_quotation_id",
            doc_name="Quotation",
            reason=reason,
            extra_update_params={"quotation_no": None},
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error rejecting quotation")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reopen_quotation")
def reopen_quotation(
    payload: dict,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Reopen a cancelled (6 -> 21) or rejected (4 -> 1) quotation."""
    try:
        sales_quotation_id = to_int(payload.get("sales_quotation_id"), "sales_quotation_id", required=True)
        user_id = int(token_data.get("user_id"))

        doc_query = get_quotation_with_approval_info()
        doc_result = db.execute(doc_query, {"sales_quotation_id": sales_quotation_id}).fetchone()
        if not doc_result:
            raise HTTPException(status_code=404, detail="Quotation not found")
        doc = dict(doc_result._mapping)

        current_status = doc.get("status_id")
        if current_status == 6:
            new_status_id = 21
        elif current_status == 4:
            new_status_id = 1
        else:
            raise HTTPException(status_code=400, detail=f"Cannot reopen quotation with status_id {current_status}. Only 6 (Cancelled) or 4 (Rejected).")

        updated_at = now_ist()
        update_q = update_quotation_status()
        db.execute(update_q, {
            "sales_quotation_id": sales_quotation_id,
            "status_id": new_status_id,
            "approval_level": None,
            "updated_by": user_id,
            "updated_date_time": updated_at,
            "quotation_no": None,
        })
        db.commit()
        return {"status": "success", "new_status_id": new_status_id, "message": f"Quotation reopened (status: {new_status_id})."}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error reopening quotation")
        raise HTTPException(status_code=500, detail=str(e))
