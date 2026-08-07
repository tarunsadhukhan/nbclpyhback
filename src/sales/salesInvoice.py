from fastapi import Depends, Request, HTTPException, APIRouter, Query
import logging
from sqlalchemy.orm import Session
from sqlalchemy.sql import text
from datetime import datetime
from src.common.utils import now_ist
from src.common.rounding import round_amount, round_rate, fetch_item_rate_roundings
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.masters.query import get_branch_list, get_item_group_drodown
from src.procurement.indent import (
    calculate_financial_year,
    format_indent_no,
)
from src.procurement.query import (
    get_item_make_by_group_id,
)
from src.sales.quotation import (
    to_int,
    to_float,
    to_positive_float,
    format_date,
    get_fy_boundaries,
)
from src.common.approval_utils import (
    process_approval,
    process_rejection,
    calculate_approval_permissions,
)
from src.sales.query import (
    get_customers_for_sales,
    get_customer_branches_bulk,
    get_brokers_for_sales,
    get_transporters_for_sales,
    get_approved_delivery_orders_query,
    get_delivery_order_lines_for_invoice,
    get_sales_order_lines_for_invoice,
    get_item_by_group_id_saleable,
    get_item_uom_by_group_id_saleable,
    get_invoice_table_query,
    get_invoice_table_count_query,
    get_invoice_by_id_query,
    get_invoice_dtl_by_id_query,
    insert_sales_invoice,
    insert_invoice_line_item,
    update_sales_invoice,
    delete_invoice_line_items,
    update_invoice_status,
    get_invoice_with_approval_info,
    get_max_invoice_no_for_branch_fy,
    get_mukam_list,
    # GST (separate table)
    insert_sales_invoice_dtl_gst,
    delete_sales_invoice_dtl_gst,
    get_sales_invoice_dtl_gst_by_invoice_id,
    # Jute header (new table)
    insert_sales_invoice_jute,
    delete_sales_invoice_jute,
    get_sales_invoice_jute_by_id,
    # Jute detail (new table)
    insert_sales_invoice_jute_dtl,
    delete_sales_invoice_jute_dtl,
    get_sales_invoice_jute_dtl_by_invoice_id,
    # Govt SKG header
    insert_sales_invoice_govtskg,
    delete_sales_invoice_govtskg,
    get_sales_invoice_govtskg_by_id,
    # Govt SKG detail
    insert_sale_invoice_govtskg_dtl,
    delete_sale_invoice_govtskg_dtl,
    get_sale_invoice_govtskg_dtl_by_invoice_id,
    # Hessian detail
    insert_sales_invoice_hessian_dtl,
    delete_sales_invoice_hessian_dtl,
    get_sales_invoice_hessian_dtl_by_invoice_id,
    # Sales orders for invoice
    get_approved_sales_orders_for_invoice,
    # E-invoice functions
    get_transporter_branches,
    get_e_invoice_submission_history,
    # SO extension data for invoice pre-fill
    get_sales_order_govtskg_by_id,
    get_sales_order_additional_by_id,
    # Govt SKG freight (type 7)
    insert_sales_invoice_freight,
    update_sales_invoice_freight,
    get_sales_invoice_freight_by_invoice_id,
    insert_sales_invoice_freight_source,
    get_sales_invoice_freight_sources_by_freight_id,
    get_sales_invoice_freight_source_ids,
    get_govt_sacking_source_list,
    get_govt_sacking_source_list_count,
    get_govt_sacking_source_by_id,
    get_govt_sacking_source_lines,
    find_or_create_freight_item,
)
from src.sales.constants import SALES_DOC_TYPES, SALES_STATUS_IDS, INVOICE_TYPE_IDS
from src.sales.hessian_calculations import compute_hessian_fields, resolve_qty_rounding
from src.sales.query import get_hessian_mt_conversion

logger = logging.getLogger(__name__)

router = APIRouter()


# Order-identity fields for multi-source Govt Sacking freight invoices.
# All selected source invoices must agree on each of these; mismatches are
# rejected with HTTP 400 so the user can correct the source mix or raise
# multiple freight bills. Only invoice_id/invoice_no/invoice_date and the
# line-level quantity are allowed to differ across sources.
#
# Each entry is (header_column, human_readable_label).
FREIGHT_SOURCE_IDENTITY_FIELDS: list[tuple[str, str]] = [
    ("party_id", "buyer / party"),
    ("branch_id", "branch"),
    ("billing_to_id", "billing party"),
    ("shipping_to_id", "shipping party"),
    ("transporter_id", "transporter"),
    ("transporter_branch_id", "transporter branch"),
    ("sales_order_id", "sales order"),
    ("sales_delivery_order_id", "delivery order"),
    ("buyer_order_no", "buyer order number"),
    ("buyer_order_date", "buyer order date"),
    ("pcso_no", "PCSO number"),
    ("pcso_date", "PCSO date"),
    ("administrative_office_address", "administrative office address"),
    ("destination_rail_head", "destination rail head"),
    ("loading_point", "loading point"),
    ("mode_of_transport", "mode of transport"),
]


def _validate_freight_source_identity(
    src_headers: list[dict],
    src_first_lines: list[dict],
) -> None:
    """Raise HTTPException 400 if any two selected source invoices disagree on
    an order-identity field (or on the first line's item_id).

    Called from the type-7 create branch after all source rows are loaded.
    On the first mismatch found, surfaces a message naming the specific field
    and the two conflicting invoice numbers + values so the user knows exactly
    what to fix.
    """
    if len(src_headers) <= 1:
        return

    primary = src_headers[0]
    for hdr in src_headers[1:]:
        for col, label in FREIGHT_SOURCE_IDENTITY_FIELDS:
            if primary.get(col) != hdr.get(col):
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Source invoices must share the same {label}: "
                        f"invoice {primary.get('invoice_no')} has {col}={primary.get(col)}, "
                        f"invoice {hdr.get('invoice_no')} has {col}={hdr.get(col)}"
                    ),
                )

    primary_item = src_first_lines[0].get("item_id") if src_first_lines else None
    primary_inv_no = src_headers[0].get("invoice_no")
    for hdr, line in zip(src_headers[1:], src_first_lines[1:]):
        if line.get("item_id") != primary_item:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Source invoices must share the same item: "
                    f"invoice {primary_inv_no} has item_id={primary_item}, "
                    f"invoice {hdr.get('invoice_no')} has item_id={line.get('item_id')}"
                ),
            )


# =============================================================================
# SETUP ENDPOINTS
# =============================================================================


@router.get("/get_sales_invoice_setup_1")
def get_sales_invoice_setup_1(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Return branches, customers, transporters, approved DOs, and item groups for invoice creation."""
    try:
        q_branch_id = request.query_params.get("branch_id")
        q_co_id = request.query_params.get("co_id")
        branch_id = None
        co_id = None

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

        # Customers
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

        # Transporters
        transporter_query = get_transporters_for_sales(co_id=co_id)
        transporter_result = db.execute(transporter_query, {"co_id": co_id}).fetchall()
        transporters = [dict(r._mapping) for r in transporter_result]

        # Approved delivery orders for dropdown (optional reference)
        ado_query = get_approved_delivery_orders_query()
        ado_result = db.execute(ado_query, {"branch_id": branch_id, "co_id": co_id}).fetchall()
        approved_delivery_orders = []
        for row in ado_result:
            mapped = dict(row._mapping)
            raw_no = mapped.get("delivery_order_no")
            formatted_no = ""
            if raw_no is not None:
                try:
                    formatted_no = format_indent_no(
                        indent_no=int(raw_no) if raw_no else None,
                        co_prefix=mapped.get("co_prefix"),
                        branch_prefix=mapped.get("branch_prefix"),
                        indent_date=mapped.get("delivery_order_date"),
                        document_type=SALES_DOC_TYPES.get("DELIVERY_ORDER", "DO"),
                    )
                except Exception:
                    formatted_no = str(raw_no) if raw_no else ""
            approved_delivery_orders.append({
                "sales_delivery_order_id": mapped.get("sales_delivery_order_id"),
                "delivery_order_no": formatted_no,
                "delivery_order_date": format_date(mapped.get("delivery_order_date")),
                "party_id": mapped.get("party_id"),
                "party_name": mapped.get("party_name"),
                "net_amount": mapped.get("net_amount"),
                "sales_order_id": mapped.get("sales_order_id"),
                "sales_order_date": format_date(mapped.get("sales_order_date")),
                "sales_order_no": mapped.get("sales_order_no"),
                "invoice_type": mapped.get("invoice_type"),
                "billing_to_id": mapped.get("billing_to_id"),
                "shipping_to_id": mapped.get("shipping_to_id"),
                "transporter_id": mapped.get("transporter_id"),
            })

        # Item groups (for manual entry without delivery order)
        itemgrp_query = get_item_group_drodown(co_id=co_id)
        itemgrp_result = db.execute(itemgrp_query, {"co_id": co_id}).fetchall()
        item_groups = [dict(r._mapping) for r in itemgrp_result]

        # Invoice types mapped to company
        invoice_types_result = db.execute(
            text("""
                SELECT itm.invoice_type_id, itm.invoice_type_name
                FROM invoice_type_co_map itcm
                JOIN invoice_type_mst itm ON itm.invoice_type_id = itcm.invoice_type_id
                WHERE itcm.co_id = :co_id AND itcm.active = 1
                ORDER BY itm.invoice_type_name
            """),
            {"co_id": co_id},
        ).fetchall()
        invoice_types = [dict(r._mapping) for r in invoice_types_result]

        # Mukam list (for jute invoices)
        mukam_query = get_mukam_list()
        mukam_result = db.execute(mukam_query).fetchall()
        mukam_list = [dict(r._mapping) for r in mukam_result]

        # Approved sales orders for dropdown
        aso_query = get_approved_sales_orders_for_invoice()
        aso_result = db.execute(aso_query, {"branch_id": branch_id, "co_id": co_id}).fetchall()
        approved_sales_orders = []
        for row in aso_result:
            mapped = dict(row._mapping)
            raw_no = mapped.get("sales_no")
            formatted_no = ""
            if raw_no is not None:
                try:
                    formatted_no = format_indent_no(
                        indent_no=int(raw_no) if raw_no else None,
                        co_prefix=mapped.get("co_prefix"),
                        branch_prefix=mapped.get("branch_prefix"),
                        indent_date=mapped.get("sales_order_date"),
                        document_type=SALES_DOC_TYPES.get("SALES_ORDER", "SO"),
                    )
                except Exception:
                    formatted_no = str(raw_no) if raw_no else ""
            approved_sales_orders.append({
                "sales_order_id": mapped.get("sales_order_id"),
                "sales_order_no": formatted_no,
                "sales_order_date": format_date(mapped.get("sales_order_date")),
                "party_id": mapped.get("party_id"),
                "party_name": mapped.get("party_name"),
                "payment_terms": mapped.get("payment_terms"),
                "invoice_type": mapped.get("invoice_type"),
                "broker_id": mapped.get("broker_id"),
                "billing_to_id": mapped.get("billing_to_id"),
                "shipping_to_id": mapped.get("shipping_to_id"),
                "transporter_id": mapped.get("transporter_id"),
                "buyer_order_no": mapped.get("buyer_order_no"),
                "buyer_order_date": format_date(mapped.get("buyer_order_date")),
            })

        # Additional charges master
        from src.sales.query import get_additional_charges_dropdown
        charges_result = db.execute(get_additional_charges_dropdown()).fetchall()
        additional_charges_master = [dict(r._mapping) for r in charges_result]

        # Transport charge rates for Govt Sacking (scoped to this company)
        from src.sales.query import get_govtskg_transport_charge_rates
        transport_rates_result = db.execute(get_govtskg_transport_charge_rates(), {"co_id": co_id}).fetchall()
        transport_charge_rates = [dict(r._mapping) for r in transport_rates_result]

        # Company details for invoice header
        co_result = db.execute(
            text("""
                SELECT cm.co_name, cm.co_logo, cm.co_address1, cm.co_address2, cm.co_zipcode,
                       cm.co_cin_no, cm.co_email_id, cm.co_pan_no,
                       cm.state_id, sm.state AS state_name, sm.state_code
                FROM co_mst cm
                LEFT JOIN state_mst sm ON sm.state_id = cm.state_id
                WHERE cm.co_id = :co_id
            """),
            {"co_id": co_id},
        ).fetchone()
        company = dict(co_result._mapping) if co_result else {}

        # Bank details for dropdown
        bank_result = db.execute(
            text("""
                SELECT b.bank_detail_id, b.bank_name, b.bank_branch, b.acc_no, b.ifsc_code
                FROM bank_details_mst b
                WHERE b.co_id = :co_id AND b.active = 1
                ORDER BY b.bank_name
            """),
            {"co_id": co_id},
        ).fetchall()
        bank_details = [dict(r._mapping) for r in bank_result]

        return {
            "branches": branches,
            "customers": customers,
            "brokers": brokers,
            "transporters": transporters,
            "approved_delivery_orders": approved_delivery_orders,
            "item_groups": item_groups,
            "invoice_types": invoice_types,
            "mukam_list": mukam_list,
            "approved_sales_orders": approved_sales_orders,
            "additional_charges_master": additional_charges_master,
            "transport_charge_rates": transport_charge_rates,
            "company": company,
            "bank_details": bank_details,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching sales invoice setup 1")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_sales_invoice_setup_2")
def get_sales_invoice_setup_2(
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


@router.get("/get_delivery_order_lines")
def get_delivery_order_lines(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Get delivery order line items plus linked SO extension data to pre-fill a new invoice.

    Returns line items and, when a linked sales order exists, also returns
    govtskg header/detail and additional charges from the SO — so the
    frontend receives everything it needs in a single call.
    """
    try:
        q_id = request.query_params.get("sales_delivery_order_id")
        if q_id is None:
            raise HTTPException(status_code=400, detail="sales_delivery_order_id is required")

        sales_delivery_order_id = int(q_id)

        # 1. Line items
        query = get_delivery_order_lines_for_invoice()
        result = db.execute(query, {"sales_delivery_order_id": sales_delivery_order_id}).fetchall()
        data = [dict(r._mapping) for r in result]

        response: dict = {"data": data}

        # 2. Look up linked SO from the DO header
        do_header = db.execute(
            text("SELECT sales_order_id, invoice_type FROM sales_delivery_order WHERE sales_delivery_order_id = :id"),
            {"id": sales_delivery_order_id},
        ).fetchone()

        if do_header:
            do_hdr = dict(do_header._mapping)
            so_id = do_hdr.get("sales_order_id")
            inv_type = do_hdr.get("invoice_type")

            if inv_type is not None:
                response["invoice_type"] = inv_type

            if so_id:
                # 3a. Govtskg header (PCSO, mode of transport, etc.)
                govtskg_row = db.execute(
                    get_sales_order_govtskg_by_id(), {"sales_order_id": so_id}
                ).fetchone()
                if govtskg_row:
                    g = dict(govtskg_row._mapping)
                    response["so_govtskg"] = {
                        "pcso_no": g.get("pcso_no"),
                        "pcso_date": str(g["pcso_date"]) if g.get("pcso_date") else None,
                        "mode_of_transport": g.get("mode_of_transport"),
                        "administrative_office_address": g.get("administrative_office_address"),
                        "destination_rail_head": g.get("destination_rail_head"),
                        "loading_point": g.get("loading_point"),
                    }

                # 3b. SO additional charges (with GST)
                additional_results = db.execute(
                    get_sales_order_additional_by_id(), {"sales_order_id": so_id}
                ).fetchall()
                if additional_results:
                    response["so_additional_charges"] = [dict(r._mapping) for r in additional_results]

        return response
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_sales_order_lines")
def get_sales_order_lines(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Get sales order line items plus SO extension data to pre-fill a new invoice."""
    try:
        q_id = request.query_params.get("sales_order_id")
        if q_id is None:
            raise HTTPException(status_code=400, detail="sales_order_id is required")

        sales_order_id = int(q_id)
        query = get_sales_order_lines_for_invoice()
        result = db.execute(query, {"sales_order_id": sales_order_id}).fetchall()
        data = [dict(r._mapping) for r in result]

        response: dict = {"data": data}

        # SO header — invoice_type (so the frontend can align the invoice type)
        so_header = db.execute(
            text("SELECT invoice_type FROM sales_order WHERE sales_order_id = :id"),
            {"id": sales_order_id},
        ).fetchone()
        if so_header:
            inv_type = dict(so_header._mapping).get("invoice_type")
            if inv_type is not None:
                response["invoice_type"] = inv_type

        # SO extension data — govtskg header
        govtskg_row = db.execute(
            get_sales_order_govtskg_by_id(), {"sales_order_id": sales_order_id}
        ).fetchone()
        if govtskg_row:
            g = dict(govtskg_row._mapping)
            response["so_govtskg"] = {
                "pcso_no": g.get("pcso_no"),
                "pcso_date": str(g["pcso_date"]) if g.get("pcso_date") else None,
                "mode_of_transport": g.get("mode_of_transport"),
                "administrative_office_address": g.get("administrative_office_address"),
                "destination_rail_head": g.get("destination_rail_head"),
                "loading_point": g.get("loading_point"),
            }

        # SO additional charges (with GST)
        additional_results = db.execute(
            get_sales_order_additional_by_id(), {"sales_order_id": sales_order_id}
        ).fetchall()
        if additional_results:
            response["so_additional_charges"] = [dict(r._mapping) for r in additional_results]

        return response
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# CRUD ENDPOINTS
# =============================================================================


@router.get("/get_sales_invoice_table")
def get_sales_invoice_table(
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
    """Return paginated sales invoice list."""
    try:
        page = max(page, 1)
        limit = max(min(limit, 100), 1)
        offset = (page - 1) * limit
        search_like = f"%{search.strip()}%" if search else None

        params = {"co_id": co_id, "branch_id": branch_id, "status_id": status_id, "search_like": search_like, "limit": limit, "offset": offset}

        list_query = get_invoice_table_query()
        rows = db.execute(list_query, params).fetchall()
        data = []
        for row in rows:
            mapped = dict(row._mapping)
            raw_no = mapped.get("invoice_no")
            formatted_no = ""
            if raw_no is not None:
                try:
                    formatted_no = format_indent_no(
                        indent_no=int(raw_no) if raw_no else None,
                        co_prefix=mapped.get("co_prefix"),
                        branch_prefix=mapped.get("branch_prefix"),
                        indent_date=mapped.get("invoice_date"),
                        document_type=SALES_DOC_TYPES.get("INVOICE", "SI"),
                    )
                except Exception:
                    formatted_no = str(raw_no) if raw_no else ""

            raw_do_no = mapped.get("do_raw_no")
            formatted_do_no = None
            if raw_do_no is not None:
                try:
                    formatted_do_no = format_indent_no(
                        indent_no=int(raw_do_no) if raw_do_no else None,
                        co_prefix=mapped.get("co_prefix"),
                        branch_prefix=mapped.get("branch_prefix"),
                        indent_date=mapped.get("do_date"),
                        document_type=SALES_DOC_TYPES["DELIVERY_ORDER"],
                    )
                except Exception:
                    formatted_do_no = str(raw_do_no) if raw_do_no else None

            data.append({
                "invoice_id": mapped.get("invoice_id"),
                "invoice_no": formatted_no,
                "invoice_date": format_date(mapped.get("invoice_date")),
                "branch_id": mapped.get("branch_id"),
                "branch_name": mapped.get("branch_name"),
                "party_name": mapped.get("party_name"),
                "sales_delivery_order_id": mapped.get("sales_delivery_order_id"),
                "delivery_order_no": formatted_do_no,
                "invoice_amount": mapped.get("invoice_amount"),
                "status": mapped.get("status_name"),
                "status_id": mapped.get("status_id"),
            })

        count_query = get_invoice_table_count_query()
        count_result = db.execute(count_query, {"co_id": co_id, "branch_id": branch_id, "status_id": status_id, "search_like": search_like}).scalar()
        total = int(count_result) if count_result is not None else 0

        return {"data": data, "total": total}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching sales invoice table")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/govt_sacking_source_list")
def govt_sacking_source_list(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    co_id: int = Query(...),
    branch_id: int = Query(...),
    search: str | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
):
    """List finalized Govt Sacking (type-3) invoices as the freight-invoice source picker."""
    try:
        offset = (page - 1) * limit
        search_like = f"%{search.strip()}%" if search else None
        params = {
            "co_id": int(co_id),
            "branch_id": int(branch_id),
            "search_like": search_like,
            "limit": int(limit),
            "offset": int(offset),
        }

        rows = db.execute(get_govt_sacking_source_list(), params).fetchall()
        data = [dict(r._mapping) for r in rows]

        count_params = {
            "co_id": int(co_id),
            "branch_id": int(branch_id),
            "search_like": search_like,
        }
        count_result = db.execute(get_govt_sacking_source_list_count(), count_params).scalar()
        total = int(count_result) if count_result is not None else 0

        return {"data": data, "total": total}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching Govt Sacking source list")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/govt_sacking_source/{invoice_id}")
def govt_sacking_source_by_id(
    invoice_id: int,
    request: Request,
    co_id: int = Query(...),
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Return the full data needed to pre-fill a Govt Sacking Freight (type 7) invoice."""
    try:
        header_row = db.execute(
            get_govt_sacking_source_by_id(),
            {"invoice_id": int(invoice_id), "co_id": int(co_id)}
        ).fetchone()
        if not header_row:
            raise HTTPException(status_code=404, detail="Source Govt Sacking invoice not found")
        header = dict(header_row._mapping)

        # Validation: must be type 3
        if header.get("invoice_type") != 3:
            raise HTTPException(status_code=400, detail="Selected invoice is not a Govt Sacking invoice")

        # Format Sales Order number (FY-prefixed) so the freight preview mirrors
        # how Type 3 shows it in the approvedSalesOrders dropdown.
        raw_so_no = header.get("sales_order_no")
        if raw_so_no:
            try:
                header["sales_order_no_formatted"] = format_indent_no(
                    indent_no=int(raw_so_no),
                    co_prefix=header.get("co_prefix"),
                    branch_prefix=header.get("branch_prefix"),
                    indent_date=header.get("sales_order_date"),
                    document_type=SALES_DOC_TYPES.get("SALES_ORDER", "SO"),
                )
            except Exception:
                header["sales_order_no_formatted"] = str(raw_so_no)
        else:
            header["sales_order_no_formatted"] = None

        raw_inv_no = header.get("invoice_no")
        if raw_inv_no:
            try:
                header["invoice_no_formatted"] = format_indent_no(
                    indent_no=int(raw_inv_no),
                    co_prefix=header.get("co_prefix"),
                    branch_prefix=header.get("branch_prefix"),
                    indent_date=header.get("invoice_date"),
                    document_type=SALES_DOC_TYPES.get("INVOICE", "SI"),
                )
            except Exception:
                header["invoice_no_formatted"] = str(raw_inv_no)
        else:
            header["invoice_no_formatted"] = None

        raw_do_no = header.get("delivery_order_no")
        if raw_do_no:
            try:
                header["delivery_order_no_formatted"] = format_indent_no(
                    indent_no=int(raw_do_no),
                    co_prefix=header.get("co_prefix"),
                    branch_prefix=header.get("branch_prefix"),
                    indent_date=header.get("delivery_order_date"),
                    document_type=SALES_DOC_TYPES.get("DELIVERY_ORDER", "DO"),
                )
            except Exception:
                header["delivery_order_no_formatted"] = str(raw_do_no)
        else:
            header["delivery_order_no_formatted"] = None

        line_rows = db.execute(
            get_govt_sacking_source_lines(), {"invoice_id": int(invoice_id)}
        ).fetchall()
        lines = []
        for lr in line_rows:
            ld = dict(lr._mapping)
            lines.append({
                "item_id": ld.get("item_id"),
                "item_name": ld.get("item_name"),
                "hsn_code": ld.get("hsn_code"),
                "quantity": ld.get("quantity"),
                "uom_id": ld.get("uom_id"),
                "uom_name": ld.get("uom_name"),
                "pack_sheet": ld.get("pack_sheet"),
                "net_weight": ld.get("net_weight"),
                "total_weight": ld.get("total_weight"),
            })

        return {"data": {"header": header, "lines": lines}}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching Govt Sacking source by id")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_transporter_branches")
def get_transporter_branches_endpoint(
    request: Request,
    transporter_id: int = Query(..., description="Transporter party ID"),
    co_id: int = Query(..., description="Company ID"),
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Fetch all branches for a transporter party.
    Used to populate transporter branch dropdown and retrieve GST number.
    """
    try:
        if not transporter_id or not co_id:
            raise HTTPException(status_code=400, detail="transporter_id and co_id are required")

        query = get_transporter_branches(int(transporter_id))
        result = db.execute(query, {"transporter_id": int(transporter_id)}).fetchall()

        branches = [dict(r._mapping) for r in result]

        return {"data": branches}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching transporter branches")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_sales_invoice_by_id")
def get_sales_invoice_by_id(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Return invoice details by ID with line items."""
    try:
        q_id = request.query_params.get("invoice_id")
        q_co_id = request.query_params.get("co_id")
        if q_id is None:
            raise HTTPException(status_code=400, detail="invoice_id is required")
        if q_co_id is None:
            raise HTTPException(status_code=400, detail="co_id is required")

        try:
            invoice_id = int(q_id)
            co_id = int(q_co_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid invoice_id or co_id")

        # Header
        header_query = get_invoice_by_id_query()
        header_result = db.execute(header_query, {"invoice_id": invoice_id, "co_id": co_id}).fetchone()
        if not header_result:
            raise HTTPException(status_code=404, detail="Sales invoice not found or access denied")
        header = dict(header_result._mapping)

        # Details
        detail_query = get_invoice_dtl_by_id_query()
        detail_results = db.execute(detail_query, {"invoice_id": invoice_id}).fetchall()
        details = [dict(r._mapping) for r in detail_results]

        # Format invoice number
        raw_no = header.get("invoice_no")
        formatted_no = ""
        if raw_no is not None:
            try:
                formatted_no = format_indent_no(
                    indent_no=int(raw_no) if raw_no else None,
                    co_prefix=header.get("co_prefix"),
                    branch_prefix=header.get("branch_prefix"),
                    indent_date=header.get("invoice_date"),
                    document_type=SALES_DOC_TYPES.get("INVOICE", "SI"),
                )
            except Exception:
                formatted_no = str(raw_no) if raw_no else ""

        # Format Sales Order number (FY-prefixed) for Govt Sacking Freight (type 7)
        # so the print preview mirrors the formatted SO label used in the SO dropdown.
        # For freight invoices the header's branch_prefix == source SO's branch_prefix
        # (freight inserts use src_hdr.branch_id), so this is safe.
        raw_so_no = header.get("sales_order_no")
        formatted_so_no = None
        if raw_so_no and header.get("invoice_type") == INVOICE_TYPE_IDS.get("GOVT_SKG_FREIGHT"):
            try:
                formatted_so_no = format_indent_no(
                    indent_no=int(raw_so_no),
                    co_prefix=header.get("co_prefix"),
                    branch_prefix=header.get("branch_prefix"),
                    indent_date=header.get("sales_order_date"),
                    document_type=SALES_DOC_TYPES.get("SALES_ORDER", "SO"),
                )
            except Exception:
                formatted_so_no = str(raw_so_no)

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
                    current_approval_level=None,
                    db=db,
                )
            except Exception:
                logger.exception("Error calculating permissions")

        response = {
            "id": str(header.get("invoice_id", "")),
            "invoiceNo": formatted_no,
            "invoiceDate": format_date(header.get("invoice_date")),
            "challanNo": header.get("challan_no"),
            "challanDate": format_date(header.get("challan_date")),
            "branchId": str(header.get("branch_id", "")) if header.get("branch_id") else "",
            "salesDeliveryOrderId": header.get("sales_delivery_order_id"),
            "brokerId": header.get("broker_id"),
            "billingTo": header.get("billing_to_id"),
            "billingAddress": header.get("billing_address"),
            "billingGstNo": header.get("billing_gst_no"),
            "billingStateId": header.get("billing_state_id"),
            "billingStateName": header.get("billing_state_name"),
            "billingContactPerson": header.get("billing_contact_person"),
            "billingContactNo": header.get("billing_contact_no"),
            "shippingTo": header.get("shipping_to_id"),
            "shippingAddress": header.get("shipping_address"),
            "shippingGstNo": header.get("shipping_gst_no"),
            "shippingStateId": header.get("shipping_state_id"),
            "shippingStateName": header.get("shipping_state_name"),
            "shippingContactPerson": header.get("shipping_contact_person"),
            "shippingContactNo": header.get("shipping_contact_no"),
            "party": str(header.get("party_id", "")) if header.get("party_id") else "",
            "partyName": header.get("party_name"),
            "shippingStateCode": header.get("shipping_state_code"),
            "transporter": str(header.get("transporter_id", "")) if header.get("transporter_id") else None,
            "transporterName": header.get("transporter_name"),
            "transporterNameStored": header.get("transporter_name_stored"),
            "transporterAddress": header.get("transporter_address"),
            "transporterStateCode": header.get("transporter_state_code"),
            "transporterStateName": header.get("transporter_state_name"),
            "transporterBranchId": header.get("transporter_branch_id"),
            "transporterGstNo": header.get("transporter_gst_no"),
            "transporterDocNo": header.get("transporter_doc_no"),
            "transporterDocDate": format_date(header.get("transporter_doc_date")),
            "buyerOrderNo": header.get("buyer_order_no"),
            "buyerOrderDate": format_date(header.get("buyer_order_date")),
            "irn": header.get("irn"),
            "ackNo": header.get("ack_no"),
            "ackDate": format_date(header.get("ack_date")),
            "qrCode": header.get("qr_code"),
            "vehicleNo": header.get("vehicle_no"),
            "ewayBillNo": header.get("eway_bill_no"),
            "ewayBillDate": format_date(header.get("eway_bill_date")),
            "invoiceType": header.get("invoice_type"),
            "footerNote": header.get("footer_notes"),
            "internalNote": header.get("internal_note"),
            "termsConditions": header.get("terms_conditions"),
            "grossAmount": header.get("invoice_amount"),
            "taxAmount": header.get("tax_amount"),
            "taxPayable": header.get("tax_payable"),
            "freightCharges": header.get("freight_charges"),
            "roundOff": header.get("round_off"),
            "intraInterState": header.get("intra_inter_state"),
            "dueDate": format_date(header.get("due_date")),
            "typeOfSale": header.get("type_of_sale"),
            "taxId": header.get("tax_id"),
            "containerNo": header.get("container_no"),
            "contractNo": header.get("contract_no"),
            "contractDate": format_date(header.get("contract_date")),
            "consignmentNo": header.get("consignment_no"),
            "consignmentDate": format_date(header.get("consignment_date")),
            "paymentTerms": header.get("payment_terms"),
            "salesOrderId": header.get("sales_order_id"),
            "salesOrderDate": format_date(header.get("sales_order_date")),
            "salesOrderNo": formatted_so_no if formatted_so_no is not None else header.get("sales_order_no"),
            "billingStateCode": header.get("billing_state_code"),
            "bankDetailId": header.get("bank_detail_id"),
            "bankName": header.get("bank_name"),
            "bankAccNo": header.get("bank_acc_no"),
            "bankIfscCode": header.get("bank_ifsc_code"),
            "bankBranchName": header.get("bank_branch_name"),
            "companyName": header.get("co_name"),
            "companyLogo": header.get("co_logo"),
            "companyAddress1": header.get("co_address1"),
            "companyAddress2": header.get("co_address2"),
            "companyZipcode": header.get("co_zipcode"),
            "companyCinNo": header.get("co_cin_no"),
            "companyPanNo": header.get("co_pan_no"),
            "companyStateName": header.get("co_state_name"),
            "companyStateCode": header.get("co_state_code"),
            "branchAddress1": header.get("branch_address1"),
            "branchAddress2": header.get("branch_address2"),
            "branchZipcode": header.get("branch_zipcode"),
            "branchGstNo": header.get("branch_gst_no"),
            "branchStateName": header.get("branch_state_name"),
            "branchStateCode": header.get("branch_state_code"),
            "status": header.get("status_name"),
            "statusId": status_id,
            "updatedBy": str(header.get("updated_by", "")) if header.get("updated_by") else None,
            "updatedAt": str(header.get("updated_date_time")) if header.get("updated_date_time") else None,
            "lines": [],
        }

        if permissions is not None:
            response["permissions"] = permissions

        # Fetch GST data from separate table and build lookup map
        gst_results = db.execute(
            get_sales_invoice_dtl_gst_by_invoice_id(), {"invoice_id": invoice_id}
        ).fetchall()
        gst_map = {}
        for g in gst_results:
            gd = dict(g._mapping)
            gst_map[gd["invoice_line_item_id"]] = gd

        # Fetch jute header data from new table
        try:
            jute_result = db.execute(
                get_sales_invoice_jute_by_id(), {"invoice_id": invoice_id}
            ).fetchone()
            if jute_result:
                jute = dict(jute_result._mapping)
                response["jute"] = {
                    "mrNo": jute.get("mr_no"),
                    "mrId": jute.get("mr_id"),
                    "claimAmount": float(jute["claim_amount"]) if jute.get("claim_amount") is not None else None,
                    "otherReference": jute.get("other_reference"),
                    "unitConversion": jute.get("unit_conversion"),
                    "claimDescription": jute.get("claim_description"),
                    "mukamId": jute.get("mukam_id"),
                    "mukamName": jute.get("mukam_name"),
                }
        except Exception:
            pass

        # Fetch jute detail data from new table and build lookup map
        jute_dtl_map = {}
        try:
            jute_dtl_results = db.execute(
                get_sales_invoice_jute_dtl_by_invoice_id(), {"invoice_id": invoice_id}
            ).fetchall()
            for jd in jute_dtl_results:
                jdd = dict(jd._mapping)
                jute_dtl_map[jdd["invoice_line_item_id"]] = jdd
        except Exception:
            pass

        # Fetch govt SKG header data
        try:
            govtskg_result = db.execute(
                get_sales_invoice_govtskg_by_id(), {"invoice_id": invoice_id}
            ).fetchone()
            if govtskg_result:
                govtskg = dict(govtskg_result._mapping)
                response["govtskg"] = {
                    "pcsoNo": govtskg.get("pcso_no"),
                    "pcsoDate": str(govtskg["pcso_date"]) if govtskg.get("pcso_date") else None,
                    "administrativeOfficeAddress": govtskg.get("administrative_office_address"),
                    "destinationRailHead": govtskg.get("destination_rail_head"),
                    "loadingPoint": govtskg.get("loading_point"),
                    "modeOfTransport": govtskg.get("mode_of_transport"),
                    "packSheet": float(govtskg["pack_sheet"]) if govtskg.get("pack_sheet") is not None else None,
                    "netWeight": float(govtskg["net_weight"]) if govtskg.get("net_weight") is not None else None,
                    "totalWeight": float(govtskg["total_weight"]) if govtskg.get("total_weight") is not None else None,
                }
        except Exception:
            pass

        # Fetch freight data (type 7 only) + include source summary
        try:
            if header.get("invoice_type") == INVOICE_TYPE_IDS["GOVT_SKG_FREIGHT"]:
                freight_row = db.execute(
                    get_sales_invoice_freight_by_invoice_id(), {"invoice_id": invoice_id}
                ).fetchone()
                if freight_row:
                    fd = dict(freight_row._mapping)
                    freight_block = {
                        "salesInvoiceFreightId": fd.get("sales_invoice_freight_id"),
                        "sourceInvoiceId": fd.get("source_invoice_id"),
                        "iwBillNo": fd.get("iw_bill_no"),
                        "iwBillDate": format_date(fd.get("iw_bill_date")),
                        "updatedBy": fd.get("updated_by"),
                        "updatedDateTime": str(fd.get("updated_date_time")) if fd.get("updated_date_time") else None,
                    }
                    src_id = fd.get("source_invoice_id")
                    if src_id:
                        src_row = db.execute(
                            get_govt_sacking_source_by_id(),
                            {"invoice_id": int(src_id), "co_id": int(q_co_id) if q_co_id else None}
                        ).fetchone()
                        if src_row:
                            src = dict(src_row._mapping)
                            src_inv_no = src.get("invoice_no")
                            src_inv_no_fmt = None
                            if src_inv_no:
                                try:
                                    src_inv_no_fmt = format_indent_no(
                                        indent_no=int(src_inv_no),
                                        co_prefix=src.get("co_prefix"),
                                        branch_prefix=src.get("branch_prefix"),
                                        indent_date=src.get("invoice_date"),
                                        document_type=SALES_DOC_TYPES.get("INVOICE", "SI"),
                                    )
                                except Exception:
                                    src_inv_no_fmt = str(src_inv_no)
                            src_do_no = src.get("delivery_order_no")
                            src_do_no_fmt = None
                            if src_do_no is not None:
                                try:
                                    src_do_no_fmt = format_indent_no(
                                        indent_no=int(src_do_no),
                                        co_prefix=src.get("co_prefix"),
                                        branch_prefix=src.get("branch_prefix"),
                                        indent_date=src.get("invoice_date"),
                                        document_type=SALES_DOC_TYPES.get("DELIVERY_ORDER", "DO"),
                                    )
                                except Exception:
                                    src_do_no_fmt = str(src_do_no)
                            freight_block["source"] = {
                                "invoice_id": src.get("invoice_id"),
                                "invoice_no": src_inv_no,
                                "invoice_no_formatted": src_inv_no_fmt,
                                "invoice_date": format_date(src.get("invoice_date")),
                                "pcso_no": src.get("pcso_no"),
                                "delivery_order_no": src_do_no,
                                "delivery_order_no_formatted": src_do_no_fmt,
                                "delivery_order_date": format_date(src.get("delivery_order_date")),
                            }

                    # Full multi-source list (junction). Always present (possibly
                    # length 1 for legacy single-source rows after backfill).
                    sources_rows = db.execute(
                        get_sales_invoice_freight_sources_by_freight_id(),
                        {"sales_invoice_freight_id": fd.get("sales_invoice_freight_id")},
                    ).fetchall()
                    sources_list = []
                    for sr in sources_rows:
                        srd = dict(sr._mapping)
                        s_inv_no = srd.get("source_invoice_no")
                        s_inv_no_fmt = None
                        if s_inv_no is not None:
                            try:
                                s_inv_no_fmt = format_indent_no(
                                    indent_no=int(s_inv_no),
                                    co_prefix=srd.get("source_co_prefix"),
                                    branch_prefix=srd.get("source_branch_prefix"),
                                    indent_date=srd.get("source_invoice_date"),
                                    document_type=SALES_DOC_TYPES.get("INVOICE", "SI"),
                                )
                            except Exception:
                                s_inv_no_fmt = str(s_inv_no)
                        s_do_no = srd.get("source_delivery_order_no")
                        s_do_no_fmt = None
                        if s_do_no is not None:
                            try:
                                s_do_no_fmt = format_indent_no(
                                    indent_no=int(s_do_no),
                                    co_prefix=srd.get("source_co_prefix"),
                                    branch_prefix=srd.get("source_branch_prefix"),
                                    indent_date=srd.get("source_delivery_order_date") or srd.get("source_invoice_date"),
                                    document_type=SALES_DOC_TYPES.get("DELIVERY_ORDER", "DO"),
                                )
                            except Exception:
                                s_do_no_fmt = str(s_do_no)
                        sources_list.append({
                            "invoice_id": srd.get("source_invoice_id"),
                            "invoice_no": s_inv_no,
                            "invoice_no_formatted": s_inv_no_fmt,
                            "invoice_date": format_date(srd.get("source_invoice_date")),
                            "party_name": srd.get("source_party_name"),
                            "pcso_no": srd.get("source_pcso_no"),
                            "pcso_date": format_date(srd.get("source_pcso_date")),
                            "delivery_order_no": s_do_no,
                            "delivery_order_no_formatted": s_do_no_fmt,
                            "delivery_order_date": format_date(srd.get("source_delivery_order_date")),
                            "bales_qty": float(srd.get("source_bales_qty")) if srd.get("source_bales_qty") is not None else None,
                        })
                    freight_block["sources"] = sources_list
                    response["freight"] = freight_block
        except Exception:
            logger.exception("Error fetching freight block for invoice")

        # Fetch hessian detail data and build lookup map
        hessian_dtl_map = {}
        try:
            hessian_dtl_results = db.execute(
                get_sales_invoice_hessian_dtl_by_invoice_id(), {"invoice_id": invoice_id}
            ).fetchall()
            for hd in hessian_dtl_results:
                hdd = dict(hd._mapping)
                hessian_dtl_map[hdd["invoice_line_item_id"]] = hdd
        except Exception:
            pass

        # Fetch govt sacking detail data and build lookup map
        govtskg_dtl_map = {}
        try:
            govtskg_dtl_results = db.execute(
                get_sale_invoice_govtskg_dtl_by_invoice_id(), {"invoice_id": invoice_id}
            ).fetchall()
            for gd in govtskg_dtl_results:
                gdd = dict(gd._mapping)
                govtskg_dtl_map[gdd["invoice_line_item_id"]] = gdd
        except Exception:
            pass

        # Load additional charges
        try:
            from src.sales.query import get_sales_invoice_additional_by_id
            additional_results = db.execute(get_sales_invoice_additional_by_id(), {"invoice_id": invoice_id}).fetchall()
            response["additionalCharges"] = [dict(r._mapping) for r in additional_results]
        except Exception:
            response["additionalCharges"] = []

        for detail in details:
            lineitem_id = detail.get("invoice_line_item_id")
            gst_data = gst_map.get(lineitem_id)
            jute_dtl_data = jute_dtl_map.get(lineitem_id)
            hessian_dtl_data = hessian_dtl_map.get(lineitem_id)
            govtskg_dtl_data = govtskg_dtl_map.get(lineitem_id)

            line = {
                "id": str(lineitem_id) if lineitem_id else "",
                "hsnCode": detail.get("hsn_code"),
                "itemGroup": str(detail.get("item_grp_id", "")) if detail.get("item_grp_id") else "",
                "item": str(detail.get("item_id", "")) if detail.get("item_id") else "",
                "itemName": detail.get("item_name"),
                "fullItemCode": detail.get("full_item_code") or detail.get("item_code") or "",
                "itemMake": str(detail.get("item_make_id", "")) if detail.get("item_make_id") else None,
                "quantity": float(detail.get("quantity", 0)) if detail.get("quantity") is not None else 0,
                "uom": str(detail.get("uom_id", "")) if detail.get("uom_id") else "",
                "uomName": detail.get("uom_name"),
                "rate": detail.get("rate"),
                "discountType": detail.get("discount_type"),
                "discountedRate": detail.get("discounted_rate"),
                "discountAmount": detail.get("discount_amount"),
                "netAmount": detail.get("amount_without_tax"),
                "totalAmount": detail.get("total_amount"),
                "salesWeight": detail.get("sales_weight"),
                "remarks": detail.get("remarks"),
                "deliveryOrderDtlId": detail.get("delivery_order_dtl_id"),
                "salesOrderDtlId": detail.get("sales_order_dtl_id"),
            }

            # GST from separate table
            if gst_data:
                line["gst"] = {
                    "taxPercentage": gst_data.get("tax_percentage"),
                    "igstAmount": gst_data.get("igst_amount"),
                    "igstPercent": gst_data.get("igst_percentage"),
                    "cgstAmount": gst_data.get("cgst_amount"),
                    "cgstPercent": gst_data.get("cgst_percentage"),
                    "sgstAmount": gst_data.get("sgst_amount"),
                    "sgstPercent": gst_data.get("sgst_percentage"),
                    "taxAmount": gst_data.get("tax_amount"),
                }
            else:
                line["gst"] = None

            # Jute detail from separate table
            if jute_dtl_data:
                line["juteDtl"] = {
                    "claimAmountDtl": jute_dtl_data.get("claim_amount_dtl"),
                    "claimDesc": jute_dtl_data.get("claim_desc"),
                    "claimRate": jute_dtl_data.get("claim_rate"),
                    "unitConversion": jute_dtl_data.get("unit_conversion"),
                    "qtyUnitConversion": jute_dtl_data.get("qty_untit_conversion"),
                }
            else:
                line["juteDtl"] = None

            # Hessian detail from separate table
            if hessian_dtl_data:
                line["hessianDtl"] = {
                    "qtyBales": hessian_dtl_data.get("qty_bales"),
                    "ratePerBale": hessian_dtl_data.get("rate_per_bale"),
                    "billingRateMt": hessian_dtl_data.get("billing_rate_mt"),
                    "billingRateBale": hessian_dtl_data.get("billing_rate_bale"),
                }
            else:
                line["hessianDtl"] = None

            # Govt sacking detail from separate table
            if govtskg_dtl_data:
                line["govtskgDtl"] = {
                    "packSheet": govtskg_dtl_data.get("pack_sheet"),
                    "netWeight": govtskg_dtl_data.get("net_weight"),
                    "totalWeight": govtskg_dtl_data.get("total_weight"),
                }
            else:
                line["govtskgDtl"] = None

            response["lines"].append(line)

        # Get e-invoice submission history if any
        try:
            history_query = get_e_invoice_submission_history(int(invoice_id))
            history_result = db.execute(history_query, {"invoice_id": int(invoice_id)}).fetchall()
            response["e_invoice_submission_history"] = [dict(r._mapping) for r in history_result]
        except Exception:
            response["e_invoice_submission_history"] = []

        return response
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching sales invoice by ID")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/create_sales_invoice")
def create_sales_invoice(
    payload: dict,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Create a sales invoice with line items. Delivery order reference is optional."""
    try:
        # ---------------------------------------------------------------
        # Type 7 (GOVT_SKG_FREIGHT) branch — built from a source type-3 invoice.
        # Runs before the generic validation path because most header fields
        # are copied from the source and the frontend sends no items array.
        # ---------------------------------------------------------------
        incoming_type = payload.get("invoice_type")
        try:
            incoming_type_int = int(incoming_type) if incoming_type is not None else None
        except (TypeError, ValueError):
            incoming_type_int = None

        if incoming_type_int == INVOICE_TYPE_IDS["GOVT_SKG_FREIGHT"]:
            freight_block = payload.get("freight") or {}

            # Accept either the new multi-source array or the legacy single-source
            # field. The array takes precedence when both are sent so updated
            # frontends drive the canonical path.
            raw_source_ids = freight_block.get("source_invoice_ids")
            if raw_source_ids is None and freight_block.get("source_invoice_id") is not None:
                raw_source_ids = [freight_block.get("source_invoice_id")]
            if not raw_source_ids:
                raise HTTPException(
                    status_code=400,
                    detail="freight.source_invoice_ids must contain at least one invoice",
                )
            try:
                source_ids = [int(s) for s in raw_source_ids]
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="Invalid source_invoice_ids; expected integers")
            # Dedupe while preserving order
            seen = set()
            source_ids_ordered: list[int] = []
            for sid in source_ids:
                if sid not in seen:
                    seen.add(sid)
                    source_ids_ordered.append(sid)
            source_ids = source_ids_ordered

            try:
                user_id = int(token_data.get("user_id"))
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="Invalid user_id on token")

            # co_id is REQUIRED for type 7 — needed for cross-company tenancy enforcement
            # on the source-invoice fetch. Never derive co_id from the source itself, because
            # that defeats the purpose of the tenancy check.
            co_id_for_item_raw = payload.get("co_id")
            if not co_id_for_item_raw:
                raise HTTPException(status_code=400, detail="co_id is required for Govt Sacking Freight invoices")
            try:
                co_id_for_item = int(co_id_for_item_raw)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="Invalid co_id format")

            # 1. Load every source header + first line (scoped by co_id)
            src_headers: list[dict] = []
            src_first_lines: list[dict] = []
            for sid in source_ids:
                hdr_row = db.execute(
                    get_govt_sacking_source_by_id(),
                    {"invoice_id": sid, "co_id": co_id_for_item},
                ).fetchone()
                if not hdr_row:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Source Govt Sacking invoice {sid} not found, not type 3, or not in your company",
                    )
                hdr = dict(hdr_row._mapping)
                # Defense in depth: co_id_scoped query already filters, but assert.
                src_co_id = hdr.get("co_id")
                if src_co_id is not None and int(src_co_id) != co_id_for_item:
                    raise HTTPException(
                        status_code=403,
                        detail=f"Source invoice {sid} does not belong to your company",
                    )
                lines_rows = db.execute(
                    get_govt_sacking_source_lines(), {"invoice_id": sid}
                ).fetchall()
                if not lines_rows:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Source Govt Sacking invoice {sid} has no line items",
                    )
                src_headers.append(hdr)
                src_first_lines.append(dict(lines_rows[0]._mapping))

            # 2. Identity check across all selected sources
            _validate_freight_source_identity(src_headers, src_first_lines)

            # Primary source is the first one; header fields are copied from it.
            # All other sources are guaranteed identical on identity fields.
            src_hdr = src_headers[0]
            src_first_line = src_first_lines[0]
            primary_source_id = source_ids[0]

            # 3. Resolve freight item (find-or-create per co_id)
            freight_item_id, freight_item_grp_id = find_or_create_freight_item(
                db, co_id_for_item, user_id
            )

            # 4. Header payload — copy from primary source, overlay user-entered fields
            container_no = freight_block.get("container_no")
            vehicle_no = freight_block.get("vehicle_no") or src_hdr.get("vehicle_no")
            iw_bill_no = freight_block.get("iw_bill_no")
            iw_bill_date_raw = freight_block.get("iw_bill_date")
            iw_bill_date = None
            if iw_bill_date_raw:
                try:
                    iw_bill_date = datetime.strptime(str(iw_bill_date_raw), "%Y-%m-%d").date()
                except ValueError:
                    iw_bill_date = None
            pcso_no = src_hdr.get("pcso_no")
            pcso_date = src_hdr.get("pcso_date")
            if isinstance(pcso_date, str):
                try:
                    pcso_date = datetime.strptime(pcso_date, "%Y-%m-%d").date()
                except ValueError:
                    pcso_date = None

            # 5. Auto-generate footer_notes (truncate with ellipsis, not mid-word cut)
            def _fmt_date(d):
                if not d:
                    return ""
                if isinstance(d, str):
                    return d
                try:
                    return d.strftime("%d-%b-%Y")
                except Exception:
                    return str(d)

            # Format every source invoice number (and DO from primary) for the footer.
            # All sources share the same branch_prefix/co_prefix (identity-verified),
            # so use the primary's prefixes when formatting each source's invoice no.
            source_inv_labels: list[str] = []
            for h in src_headers:
                inv_no_raw = h.get("invoice_no")
                inv_no_fmt = str(inv_no_raw) if inv_no_raw is not None else ""
                if inv_no_raw is not None:
                    try:
                        inv_no_fmt = format_indent_no(
                            indent_no=int(inv_no_raw),
                            co_prefix=h.get("co_prefix") or src_hdr.get("co_prefix"),
                            branch_prefix=h.get("branch_prefix") or src_hdr.get("branch_prefix"),
                            indent_date=h.get("invoice_date"),
                            document_type=SALES_DOC_TYPES.get("INVOICE", "SI"),
                        )
                    except Exception:
                        inv_no_fmt = str(inv_no_raw)
                inv_date_fmt = _fmt_date(h.get("invoice_date"))
                if inv_date_fmt:
                    source_inv_labels.append(f"{inv_no_fmt} dated {inv_date_fmt}")
                else:
                    source_inv_labels.append(inv_no_fmt)

            # Format the (shared) source delivery order number for the footer.
            do_fmt = ""
            do_raw = src_hdr.get("delivery_order_no")
            if do_raw is not None:
                try:
                    do_fmt = format_indent_no(
                        indent_no=int(do_raw),
                        co_prefix=src_hdr.get("co_prefix"),
                        branch_prefix=src_hdr.get("branch_prefix"),
                        indent_date=src_hdr.get("invoice_date"),
                        document_type=SALES_DOC_TYPES.get("DELIVERY_ORDER", "DO"),
                    )
                except Exception:
                    do_fmt = str(do_raw)

            parts = []
            if source_inv_labels:
                parts.append("Source Invoices: " + ", ".join(source_inv_labels))
            if pcso_no:
                parts.append(f"PCSO No.{pcso_no} Date:{_fmt_date(pcso_date)}")
            if do_fmt:
                parts.append(f"DO {do_fmt}")
            if iw_bill_no:
                iw_label = "RR No." if (str(src_hdr.get("mode_of_transport") or "").upper().strip() == "RAIL") else "IW Bill No."
                parts.append(f"{iw_label}{iw_bill_no} Date:{_fmt_date(iw_bill_date)}")
            if container_no:
                parts.append(f"Container No.{container_no}")
            footer_raw = " | ".join(parts)
            footer_notes = footer_raw if len(footer_raw) <= 255 else footer_raw[:252] + "..."

            # 6. Compute GST 18%
            try:
                freight_amount = float(freight_block.get("freight_amount") or 0)
            except (TypeError, ValueError):
                freight_amount = 0.0
            try:
                bales_qty = float(freight_block.get("bales_qty") or 1)
            except (TypeError, ValueError):
                bales_qty = 1.0
            if bales_qty <= 0:
                bales_qty = 1.0
            rate_per_bale = freight_amount / bales_qty

            src_branch_state_code = src_hdr.get("branch_state_code")
            src_shipping_state_code = src_hdr.get("shipping_state_code")
            if src_branch_state_code is not None and src_shipping_state_code is not None:
                intra_inter = 0 if str(src_branch_state_code) == str(src_shipping_state_code) else 1
            else:
                intra_inter = src_hdr.get("intra_inter_state")

            tax_total = round(freight_amount * 0.18, 2)
            if str(intra_inter) == "0":
                cgst_amt = round(tax_total / 2, 2)
                sgst_amt = round(tax_total - cgst_amt, 2)
                igst_amt = 0.0
                cgst_pct = 9.0
                sgst_pct = 9.0
                igst_pct = 0.0
            else:
                cgst_amt = 0.0
                sgst_amt = 0.0
                igst_amt = tax_total
                cgst_pct = 0.0
                sgst_pct = 0.0
                igst_pct = 18.0

            total_amount = round(freight_amount + tax_total, 2)

            # 6. Parse payload date / due_date
            invoice_date_7 = None
            date_str_7 = payload.get("date")
            if date_str_7:
                try:
                    invoice_date_7 = datetime.strptime(str(date_str_7), "%Y-%m-%d").date()
                except ValueError:
                    invoice_date_7 = None
            due_date_7 = None
            if payload.get("due_date"):
                try:
                    due_date_7 = datetime.strptime(str(payload["due_date"]), "%Y-%m-%d").date()
                except ValueError:
                    due_date_7 = None
            eway_bill_date_7 = None
            if payload.get("eway_bill_date"):
                try:
                    eway_bill_date_7 = datetime.strptime(str(payload["eway_bill_date"]), "%Y-%m-%d").date()
                except ValueError:
                    eway_bill_date_7 = None
            transporter_doc_date_7 = freight_block.get("transporter_doc_date") or src_hdr.get("transporter_doc_date")
            if isinstance(transporter_doc_date_7, str):
                try:
                    transporter_doc_date_7 = datetime.strptime(transporter_doc_date_7, "%Y-%m-%d").date()
                except ValueError:
                    transporter_doc_date_7 = None

            buyer_order_date_7 = src_hdr.get("buyer_order_date")
            if isinstance(buyer_order_date_7, str):
                try:
                    buyer_order_date_7 = datetime.strptime(buyer_order_date_7, "%Y-%m-%d").date()
                except ValueError:
                    buyer_order_date_7 = None

            # 7. Insert header
            hdr_params_7 = {
                "invoice_date": invoice_date_7,
                "invoice_no": None,
                "branch_id": src_hdr.get("branch_id"),
                "party_id": src_hdr.get("party_id"),
                "sales_delivery_order_id": src_hdr.get("sales_delivery_order_id"),
                "broker_id": None,
                "billing_to_id": src_hdr.get("billing_to_id"),
                "shipping_to_id": src_hdr.get("shipping_to_id"),
                "challan_no": None,
                "challan_date": None,
                "transporter_id": src_hdr.get("transporter_id"),
                "vehicle_no": vehicle_no,
                "transporter_name": src_hdr.get("transporter_name"),
                "transporter_address": src_hdr.get("transporter_address"),
                "transporter_state_code": src_hdr.get("transporter_state_code"),
                "transporter_state_name": src_hdr.get("transporter_state_name"),
                "eway_bill_no": payload.get("eway_bill_no"),
                "eway_bill_date": eway_bill_date_7,
                "invoice_type": INVOICE_TYPE_IDS["GOVT_SKG_FREIGHT"],
                "footer_notes": footer_notes,
                "internal_note": payload.get("internal_note"),
                "terms": None,
                "terms_conditions": None,
                "invoice_amount": freight_amount,
                "tax_amount": tax_total,
                "tax_payable": tax_total,
                "freight_charges": None,
                "round_off": 0,
                "shipping_state_code": src_hdr.get("shipping_state_code"),
                "intra_inter_state": intra_inter,
                "status_id": SALES_STATUS_IDS["DRAFT"],
                "active": 1,
                "due_date": due_date_7,
                "type_of_sale": None,
                "tax_id": None,
                "container_no": container_no,
                "contract_no": None,
                "contract_date": None,
                "consignment_no": None,
                "consignment_date": None,
                "payment_terms": None,
                "sales_order_id": src_hdr.get("sales_order_id"),
                "billing_state_code": src_hdr.get("billing_state_code"),
                "bank_detail_id": None,
                "transporter_branch_id": src_hdr.get("transporter_branch_id"),
                "transporter_doc_no": freight_block.get("transporter_doc_no") or src_hdr.get("transporter_doc_no"),
                "transporter_doc_date": transporter_doc_date_7,
                "buyer_order_no": src_hdr.get("buyer_order_no"),
                "buyer_order_date": buyer_order_date_7,
                "irn": None,
                "ack_no": None,
                "ack_date": None,
                "qr_code": None,
                "updated_by": user_id,
            }
            hdr_result = db.execute(insert_sales_invoice(), hdr_params_7)
            invoice_id_7 = hdr_result.lastrowid
            if not invoice_id_7:
                raise HTTPException(status_code=500, detail="Failed to create Govt Sacking Freight invoice header")

            # 8. Insert single freight line item
            src_item_name = src_first_line.get("item_name") or ""
            line_remarks_raw = f"{src_item_name} — {int(bales_qty)} bales"
            line_remarks = line_remarks_raw if len(line_remarks_raw) <= 255 else line_remarks_raw[:252] + "..."
            dtl_params_7 = {
                "invoice_id": invoice_id_7,
                "hsn_code": "996519",
                "item_id": freight_item_id,
                "item_make_id": None,
                "quantity": bales_qty,
                "uom_id": 191,
                "rate": rate_per_bale,
                "discount_type": None,
                "discounted_rate": None,
                "discount_amount": None,
                "amount_without_tax": freight_amount,
                "total_amount": total_amount,
                "sales_weight": 0,
                "remarks": line_remarks,
                "delivery_order_dtl_id": None,
                "sales_order_dtl_id": None,
            }
            dtl_result = db.execute(insert_invoice_line_item(), dtl_params_7)
            line_id_7 = dtl_result.lastrowid

            # 9. Insert GST
            db.execute(insert_sales_invoice_dtl_gst(), {
                "invoice_line_item_id": line_id_7,
                "tax_percentage": 18.0,
                "cgst_amount": cgst_amt,
                "cgst_percentage": cgst_pct,
                "sgst_amount": sgst_amt,
                "sgst_percentage": sgst_pct,
                "igst_amount": igst_amt,
                "igst_percentage": igst_pct,
                "tax_amount": tax_total,
            })

            # 10. Copy govtskg header (PCSO etc.) from source
            db.execute(insert_sales_invoice_govtskg(), {
                "invoice_id": invoice_id_7,
                "pcso_no": pcso_no,
                "pcso_date": pcso_date,
                "administrative_office_address": src_hdr.get("administrative_office_address"),
                "destination_rail_head": src_hdr.get("destination_rail_head"),
                "loading_point": src_hdr.get("loading_point"),
                "mode_of_transport": src_hdr.get("mode_of_transport"),
                "pack_sheet": None,
                "net_weight": None,
                "total_weight": None,
            })

            # 11. Insert sales_invoice_freight row (primary source kept for back-compat)
            freight_result = db.execute(insert_sales_invoice_freight(), {
                "invoice_id": invoice_id_7,
                "source_invoice_id": primary_source_id,
                "iw_bill_no": iw_bill_no,
                "iw_bill_date": iw_bill_date,
                "updated_by": user_id,
                "updated_date_time": now_ist(),
            })
            sales_invoice_freight_id = freight_result.lastrowid
            if not sales_invoice_freight_id:
                raise HTTPException(status_code=500, detail="Failed to create freight extension row")

            # 12. Insert one junction row per source. Per-source bales_qty is read
            # off each source's first line so the breakdown is retrievable for
            # audit even though the freight invoice has a single aggregated line.
            now_ts = now_ist()
            for sid, line in zip(source_ids, src_first_lines):
                try:
                    per_source_qty = float(line.get("quantity") or 0)
                except (TypeError, ValueError):
                    per_source_qty = None
                db.execute(insert_sales_invoice_freight_source(), {
                    "sales_invoice_freight_id": sales_invoice_freight_id,
                    "source_invoice_id": sid,
                    "bales_qty": per_source_qty,
                    "created_date_time": now_ts,
                })

            db.commit()
            return {
                "message": "Sales invoice created successfully",
                "invoice_id": invoice_id_7,
                "invoice_no": None,
                "status_id": SALES_STATUS_IDS["DRAFT"],
            }

        # ---------------------------------------------------------------
        # Existing flow (all other invoice types)
        # ---------------------------------------------------------------
        branch_id = to_int(payload.get("branch"), "branch", required=True)
        party_id = to_int(payload.get("party"), "party", required=True)

        date_str = payload.get("date")
        if not date_str:
            raise HTTPException(status_code=400, detail="date is required")
        try:
            invoice_date = datetime.strptime(str(date_str), "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format, expected YYYY-MM-DD")

        raw_items = payload.get("items")
        if not isinstance(raw_items, list) or len(raw_items) == 0:
            raise HTTPException(status_code=400, detail="At least one item row is required")

        user_id = to_int(token_data.get("user_id"), "user_id")

        # Optional fields
        transporter_id = to_int(payload.get("transporter"), "transporter")
        sales_delivery_order_id = to_int(payload.get("sales_delivery_order_id"), "sales_delivery_order_id")
        broker_id = to_int(payload.get("broker_id") or payload.get("broker"), "broker_id")
        billing_to_id = to_int(payload.get("billing_to"), "billing_to")
        shipping_to_id = to_int(payload.get("shipping_to"), "shipping_to")

        gross_amount = round_amount(to_float(payload.get("gross_amount"), "gross_amount"))
        freight_charges = round_amount(to_float(payload.get("freight_charges"), "freight_charges"))
        round_off = round_amount(to_float(payload.get("round_off"), "round_off"))
        tax_amount = round_amount(to_float(payload.get("tax_amount"), "tax_amount"))
        tax_payable = round_amount(to_float(payload.get("tax_payable"), "tax_payable"))

        challan_date = None
        if payload.get("challan_date"):
            try:
                challan_date = datetime.strptime(str(payload["challan_date"]), "%Y-%m-%d").date()
            except ValueError:
                pass

        eway_bill_date = None
        if payload.get("eway_bill_date"):
            try:
                eway_bill_date = datetime.strptime(str(payload["eway_bill_date"]), "%Y-%m-%d").date()
            except ValueError:
                pass

        due_date = None
        if payload.get("due_date"):
            try:
                due_date = datetime.strptime(str(payload["due_date"]), "%Y-%m-%d").date()
            except ValueError:
                pass

        contract_date = None
        if payload.get("contract_date"):
            try:
                contract_date = datetime.strptime(str(payload["contract_date"]), "%Y-%m-%d").date()
            except ValueError:
                pass

        consignment_date = None
        if payload.get("consignment_date"):
            try:
                consignment_date = datetime.strptime(str(payload["consignment_date"]), "%Y-%m-%d").date()
            except ValueError:
                pass

        # Extract 9 new fields for e-invoice
        transporter_branch_id = to_int(payload.get("transporter_branch_id"), "transporter_branch_id")
        transporter_doc_no = payload.get("transporter_doc_no")
        transporter_doc_date = None
        if payload.get("transporter_doc_date"):
            try:
                transporter_doc_date = datetime.strptime(str(payload["transporter_doc_date"]), "%Y-%m-%d").date()
            except ValueError:
                pass
        buyer_order_no = payload.get("buyer_order_no")
        buyer_order_date = None
        if payload.get("buyer_order_date"):
            try:
                buyer_order_date = datetime.strptime(str(payload["buyer_order_date"]), "%Y-%m-%d").date()
            except ValueError:
                pass
        irn = payload.get("irn")
        ack_no = payload.get("ack_no")
        ack_date = None
        if payload.get("ack_date"):
            try:
                ack_date = datetime.strptime(str(payload["ack_date"]), "%Y-%m-%d").date()
            except ValueError:
                pass
        qr_code = payload.get("qr_code")

        # Look up co_id from branch
        branch_row = db.execute(
            text("SELECT co_id FROM branch_mst WHERE branch_id = :branch_id"),
            {"branch_id": branch_id},
        ).fetchone()
        co_id = dict(branch_row._mapping).get("co_id") if branch_row else None

        # invoice_type needed inside the normalize loop for Hessian recompute.
        invoice_type_early = to_int(payload.get("invoice_type"), "invoice_type")
        HESSIAN_INVOICE_TYPE_ID = INVOICE_TYPE_IDS.get("HESSIAN")

        # Pre-fetch rate_rounding from item_mst for every line so rates are rounded
        # to the per-item precision (default 2 when NULL).
        invoice_rate_rounding_map = fetch_item_rate_roundings(
            db,
            [to_int(it.get("item"), f"items[{i}].item")
             for i, it in enumerate(raw_items, start=1)
             if it.get("item")],
        )

        # Normalize items — sales_invoice_dtl uses int columns for item_id, item_make_id, uom_id
        normalized_items = []
        for idx, item in enumerate(raw_items, start=1):
            item_val = item.get("item")
            if not item_val:
                raise HTTPException(status_code=400, detail=f"items[{idx}].item is required")
            uom_val = item.get("uom")
            if not uom_val:
                raise HTTPException(status_code=400, detail=f"items[{idx}].uom is required")

            qty = to_positive_float(item.get("quantity"), f"items[{idx}].quantity")
            rate = to_float(item.get("rate"), f"items[{idx}].rate")
            rate_decimals = invoice_rate_rounding_map.get(to_int(item_val, f"items[{idx}].item"))
            rate = round_rate(rate, rate_decimals)

            # Hessian: recompute qty (MT), rate (billing rate MT, rounded to 2),
            # and hessian_dtl derived fields using the shared formula.
            # Mirrors vowerp3ui/src/utils/hessianCalculations.ts.
            if invoice_type_early == HESSIAN_INVOICE_TYPE_ID:
                hessian_dtl_data = item.get("hessian_dtl") or {}
                qty_bales = to_float(hessian_dtl_data.get("qty_bales"), "qty_bales")
                if hessian_dtl_data and qty_bales and qty_bales > 0 and rate:
                    item_id_for_conv = to_int(item_val, f"items[{idx}].item")
                    conv_row = db.execute(
                        get_hessian_mt_conversion(), {"item_id": item_id_for_conv}
                    ).fetchone()
                    if conv_row:
                        conv_map = dict(conv_row._mapping)
                        conv_factor = float(conv_map.get("relation_value") or 0)
                        if conv_factor > 0:
                            conv_rounding = resolve_qty_rounding(conv_map.get("rounding"))
                            h = compute_hessian_fields(qty_bales, rate, conv_factor, conv_rounding)
                            qty = h["qty_mt"]
                            rate = round_rate(h["billing_rate_mt"], rate_decimals)
                            hessian_dtl_data["qty_bales"] = qty_bales
                            hessian_dtl_data["rate_per_bale"] = round_amount(h["rate_per_bale"])
                            hessian_dtl_data["billing_rate_mt"] = rate
                            hessian_dtl_data["billing_rate_bale"] = round_rate(h["billing_rate_bale"], rate_decimals)
                            item["hessian_dtl"] = hessian_dtl_data

            # Calculate line amounts — always rounded to 2 decimals.
            amount_without_tax = to_float(item.get("net_amount"), f"items[{idx}].net_amount")
            if amount_without_tax is None and qty and rate:
                amount_without_tax = qty * rate
            if amount_without_tax is not None:
                amount_without_tax = round_amount(amount_without_tax)

            gst = item.get("gst") or {}
            cgst_amt = round_amount(to_float(gst.get("cgst_amount"), "cgst_amount"))
            sgst_amt = round_amount(to_float(gst.get("sgst_amount"), "sgst_amount"))
            igst_amt = round_amount(to_float(gst.get("igst_amount"), "igst_amount"))
            if isinstance(gst, dict) and gst:
                gst["cgst_amount"] = cgst_amt
                gst["sgst_amount"] = sgst_amt
                gst["igst_amount"] = igst_amt
                gst["gst_total"] = round_amount(to_float(gst.get("gst_total"), "gst_total"))

            line_total_amount = to_float(item.get("total_amount"), f"items[{idx}].total_amount")
            if line_total_amount is None and amount_without_tax is not None:
                line_tax = (cgst_amt or 0) + (sgst_amt or 0) + (igst_amt or 0)
                line_total_amount = round_amount((amount_without_tax or 0) + line_tax)
            else:
                line_total_amount = round_amount(line_total_amount)

            normalized_items.append({
                "hsn_code": item.get("hsn_code"),
                "item_id": to_int(item_val, f"items[{idx}].item"),
                "item_make_id": to_int(item.get("item_make"), f"items[{idx}].item_make"),
                "quantity": qty,
                "uom_id": to_int(uom_val, f"items[{idx}].uom"),
                "rate": rate,
                "discount_type": to_int(item.get("discount_type"), f"items[{idx}].discount_type"),
                "discounted_rate": round_rate(to_float(item.get("discounted_rate"), f"items[{idx}].discounted_rate"), rate_decimals),
                "discount_amount": round_amount(to_float(item.get("discount_amount"), f"items[{idx}].discount_amount")),
                "amount_without_tax": amount_without_tax,
                "total_amount": line_total_amount,
                "sales_weight": to_float(item.get("sales_weight"), f"items[{idx}].sales_weight"),
                "gst": gst if gst else None,
                "jute_dtl": item.get("jute_dtl") or None,
                "remarks": item.get("remarks"),
                "delivery_order_dtl_id": to_int(item.get("delivery_order_dtl_id"), f"items[{idx}].delivery_order_dtl_id"),
                "sales_order_dtl_id": to_int(item.get("sales_order_dtl_id"), f"items[{idx}].sales_order_dtl_id"),
            })

        invoice_type = to_int(payload.get("invoice_type"), "invoice_type")
        jute_data = payload.get("jute") or {}
        govtskg_data = payload.get("govtskg") or {}

        # Compute claim_amount as sum of line item claim_amount_dtl values
        claim_amount_from_lines = sum(
            to_float((item.get("jute_dtl") or {}).get("claim_amount_dtl"), "claim_amount_dtl") or 0
            for item in normalized_items
            if item.get("jute_dtl")
        )
        if claim_amount_from_lines:
            claim_amount = round(claim_amount_from_lines, 2)
        else:
            claim_amount = to_float(jute_data.get("claim_amount"), "claim_amount")

        # For jute invoices, invoice_amount = gross_amount - claim_amount
        effective_amount = gross_amount or 0
        if invoice_type and jute_data and claim_amount:
            effective_amount = round((gross_amount or 0) - claim_amount, 2)

        # Insert header
        insert_hdr = insert_sales_invoice()
        header_params = {
            "invoice_date": invoice_date,
            "invoice_no": None,
            "branch_id": branch_id,
            "party_id": party_id,
            "sales_delivery_order_id": sales_delivery_order_id,
            "broker_id": broker_id,
            "billing_to_id": billing_to_id,
            "shipping_to_id": shipping_to_id,
            "challan_no": payload.get("challan_no"),
            "challan_date": challan_date,
            "transporter_id": transporter_id,
            "vehicle_no": payload.get("vehicle_no"),
            "transporter_name": payload.get("transporter_name"),
            "transporter_address": payload.get("transporter_address"),
            "transporter_state_code": payload.get("transporter_state_code"),
            "transporter_state_name": payload.get("transporter_state_name"),
            "eway_bill_no": payload.get("eway_bill_no"),
            "eway_bill_date": eway_bill_date,
            "invoice_type": invoice_type,
            "footer_notes": payload.get("footer_note"),
            "internal_note": payload.get("internal_note"),
            "terms": payload.get("terms"),
            "terms_conditions": payload.get("terms_conditions"),
            "invoice_amount": gross_amount or 0,
            "tax_amount": tax_amount or 0,
            "tax_payable": tax_payable,
            "freight_charges": freight_charges or 0,
            "round_off": round_off or 0,
            "shipping_state_code": to_int(payload.get("shipping_state_code"), "shipping_state_code"),
            "intra_inter_state": payload.get("intra_inter_state"),
            "due_date": due_date,
            "type_of_sale": payload.get("type_of_sale"),
            "tax_id": to_int(payload.get("tax_id"), "tax_id"),
            "container_no": payload.get("container_no"),
            "contract_no": to_int(payload.get("contract_no"), "contract_no"),
            "contract_date": contract_date,
            "consignment_no": payload.get("consignment_no"),
            "consignment_date": consignment_date,
            "payment_terms": to_int(payload.get("payment_terms"), "payment_terms"),
            "sales_order_id": to_int(payload.get("sales_order_id"), "sales_order_id"),
            "billing_state_code": to_int(payload.get("billing_state_code"), "billing_state_code"),
            "bank_detail_id": to_int(payload.get("bank_detail_id"), "bank_detail_id"),
            "transporter_branch_id": transporter_branch_id,
            "transporter_doc_no": transporter_doc_no,
            "transporter_doc_date": transporter_doc_date,
            "buyer_order_no": buyer_order_no,
            "buyer_order_date": buyer_order_date,
            "irn": irn,
            "ack_no": ack_no,
            "ack_date": ack_date,
            "qr_code": qr_code,
            "status_id": 21,
            "active": 1,
            "updated_by": user_id,
        }

        result = db.execute(insert_hdr, header_params)
        invoice_id = result.lastrowid
        if not invoice_id:
            raise HTTPException(status_code=500, detail="Failed to create sales invoice header")

        # Insert line items + GST + type-specific detail
        line_query = insert_invoice_line_item()
        gst_query = insert_sales_invoice_dtl_gst()
        jute_dtl_query = insert_sales_invoice_jute_dtl()
        hessian_dtl_query = insert_sales_invoice_hessian_dtl()
        govtskg_dtl_query = insert_sale_invoice_govtskg_dtl()
        for item in normalized_items:
            dtl_result = db.execute(line_query, {
                "invoice_id": invoice_id,
                "hsn_code": item["hsn_code"],
                "item_id": item["item_id"],
                "item_make_id": item["item_make_id"],
                "quantity": item["quantity"] or 0,
                "uom_id": item["uom_id"],
                "rate": item["rate"] or 0,
                "discount_type": item["discount_type"],
                "discounted_rate": item["discounted_rate"],
                "discount_amount": item["discount_amount"],
                "amount_without_tax": item["amount_without_tax"] or 0,
                "total_amount": item["total_amount"] or 0,
                "sales_weight": item["sales_weight"],
                "remarks": item["remarks"],
                "delivery_order_dtl_id": item["delivery_order_dtl_id"],
                "sales_order_dtl_id": item["sales_order_dtl_id"],
            })
            lineitem_id = dtl_result.lastrowid

            # Insert GST into separate table
            gst_data = item.get("gst")
            if gst_data and isinstance(gst_data, dict) and lineitem_id:
                db.execute(gst_query, {
                    "invoice_line_item_id": lineitem_id,
                    "tax_percentage": to_float(gst_data.get("tax_percentage"), "tax_percentage"),
                    "cgst_amount": to_float(gst_data.get("cgst_amount"), "cgst_amount") or 0,
                    "cgst_percentage": to_float(gst_data.get("cgst_percent"), "cgst_percent") or 0,
                    "sgst_amount": to_float(gst_data.get("sgst_amount"), "sgst_amount") or 0,
                    "sgst_percentage": to_float(gst_data.get("sgst_percent"), "sgst_percent") or 0,
                    "igst_amount": to_float(gst_data.get("igst_amount"), "igst_amount") or 0,
                    "igst_percentage": to_float(gst_data.get("igst_percent"), "igst_percent") or 0,
                    "tax_amount": to_float(gst_data.get("tax_amount"), "gst_tax_amount") or 0,
                })

            # Insert jute detail into separate table
            jute_dtl_data = item.get("jute_dtl")
            if jute_dtl_data and isinstance(jute_dtl_data, dict) and lineitem_id:
                db.execute(jute_dtl_query, {
                    "invoice_line_item_id": lineitem_id,
                    "claim_amount_dtl": to_float(jute_dtl_data.get("claim_amount_dtl"), "claim_amount_dtl"),
                    "claim_desc": jute_dtl_data.get("claim_desc"),
                    "claim_rate": to_float(jute_dtl_data.get("claim_rate"), "claim_rate"),
                    "unit_conversion": jute_dtl_data.get("unit_conversion"),
                    "qty_untit_conversion": to_int(jute_dtl_data.get("qty_untit_conversion"), "qty_untit_conversion"),
                })

            # Insert hessian detail into separate table
            hessian_dtl_data = item.get("hessian_dtl")
            if hessian_dtl_data and isinstance(hessian_dtl_data, dict) and lineitem_id:
                db.execute(hessian_dtl_query, {
                    "invoice_line_item_id": lineitem_id,
                    "qty_bales": to_float(hessian_dtl_data.get("qty_bales"), "qty_bales"),
                    "rate_per_bale": to_float(hessian_dtl_data.get("rate_per_bale"), "rate_per_bale"),
                    "billing_rate_mt": to_float(hessian_dtl_data.get("billing_rate_mt"), "billing_rate_mt"),
                    "billing_rate_bale": to_float(hessian_dtl_data.get("billing_rate_bale"), "billing_rate_bale"),
                    "updated_by": user_id,
                })

            # Insert govt sacking detail into separate table
            govtskg_dtl_data = item.get("govtskg_dtl")
            if govtskg_dtl_data and isinstance(govtskg_dtl_data, dict) and lineitem_id:
                db.execute(govtskg_dtl_query, {
                    "invoice_line_item_id": lineitem_id,
                    "pack_sheet": to_float(govtskg_dtl_data.get("pack_sheet"), "pack_sheet"),
                    "net_weight": to_float(govtskg_dtl_data.get("net_weight"), "net_weight"),
                    "total_weight": to_float(govtskg_dtl_data.get("total_weight"), "total_weight"),
                    "updated_by": user_id,
                })

        # Insert jute header data if provided
        if jute_data:
            db.execute(insert_sales_invoice_jute(), {
                "invoice_id": invoice_id,
                "mr_no": jute_data.get("mr_no"),
                "mr_id": to_int(jute_data.get("mr_id"), "mr_id"),
                "claim_amount": claim_amount,
                "other_reference": jute_data.get("other_reference"),
                "unit_conversion": jute_data.get("unit_conversion"),
                "claim_description": jute_data.get("claim_description"),
                "mukam_id": to_int(jute_data.get("mukam_id"), "mukam_id"),
            })

        # Insert govt SKG header data if provided
        if govtskg_data:
            db.execute(insert_sales_invoice_govtskg(), {
                "invoice_id": invoice_id,
                "pcso_no": govtskg_data.get("pcso_no"),
                "pcso_date": format_date(govtskg_data.get("pcso_date")),
                "administrative_office_address": govtskg_data.get("administrative_office_address"),
                "destination_rail_head": govtskg_data.get("destination_rail_head"),
                "loading_point": govtskg_data.get("loading_point"),
                "mode_of_transport": govtskg_data.get("mode_of_transport"),
                "pack_sheet": to_float(govtskg_data.get("pack_sheet"), "pack_sheet"),
                "net_weight": to_float(govtskg_data.get("net_weight"), "net_weight"),
                "total_weight": to_float(govtskg_data.get("total_weight"), "total_weight"),
            })

        # Insert additional charges
        additional_charges_list = payload.get("additional_charges") or []
        if additional_charges_list:
            from src.sales.query import insert_sales_invoice_additional, insert_sales_invoice_additional_gst
            add_query = insert_sales_invoice_additional()
            add_gst_query = insert_sales_invoice_additional_gst()
            for charge in additional_charges_list:
                charge_result = db.execute(add_query, {
                    "invoice_id": invoice_id,
                    "additional_charges_id": to_int(charge.get("additional_charges_id"), "additional_charges_id"),
                    "qty": round_amount(to_float(charge.get("qty"), "qty")),
                    "rate": round_amount(to_float(charge.get("rate"), "rate")),
                    "net_amount": round_amount(to_float(charge.get("net_amount"), "net_amount")),
                    "remarks": charge.get("remarks"),
                    "updated_by": user_id,
                    "updated_date_time": now_ist(),
                })
                charge_id = charge_result.lastrowid
                gst_data = charge.get("gst")
                if gst_data and isinstance(gst_data, dict) and charge_id:
                    db.execute(add_gst_query, {
                        "sales_invoice_additional_id": charge_id,
                        "igst_amount": round_amount(to_float(gst_data.get("igst_amount"), "igst_amount")),
                        "igst_percent": to_float(gst_data.get("igst_percent"), "igst_percent"),
                        "cgst_amount": round_amount(to_float(gst_data.get("cgst_amount"), "cgst_amount")),
                        "cgst_percent": to_float(gst_data.get("cgst_percent"), "cgst_percent"),
                        "sgst_amount": round_amount(to_float(gst_data.get("sgst_amount"), "sgst_amount")),
                        "sgst_percent": to_float(gst_data.get("sgst_percent"), "sgst_percent"),
                        "gst_total": round_amount(to_float(gst_data.get("gst_total"), "gst_total")),
                    })

        db.commit()
        return {"message": "Sales invoice created successfully", "invoice_id": invoice_id}
    except HTTPException as exc:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error creating sales invoice")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/update_sales_invoice")
def update_sales_invoice_endpoint(
    payload: dict,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Update a sales invoice with line items (delete-reinsert pattern)."""
    try:
        invoice_id = to_int(payload.get("id"), "id", required=True)

        # ---------------------------------------------------------------
        # Type 7 (GOVT_SKG_FREIGHT) branch — only freight-specific fields
        # are editable; source binding is immutable. Header/party/branch
        # come from the existing row, NOT the payload.
        # ---------------------------------------------------------------
        incoming_type_raw = payload.get("invoice_type")
        try:
            incoming_type_int = int(incoming_type_raw) if incoming_type_raw is not None else None
        except (TypeError, ValueError):
            incoming_type_int = None

        if incoming_type_int == INVOICE_TYPE_IDS["GOVT_SKG_FREIGHT"]:
            try:
                user_id_7 = int(token_data.get("user_id"))
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="Invalid user_id on token")

            # 1. Load the existing freight row + its sales_invoice header (status check + source link)
            existing = db.execute(
                text(
                    """SELECT si.invoice_id, si.status_id, si.invoice_type, si.intra_inter_state,
                              sif.sales_invoice_freight_id, sif.source_invoice_id
                       FROM sales_invoice si
                       LEFT JOIN sales_invoice_freight sif ON sif.invoice_id = si.invoice_id
                       WHERE si.invoice_id = :id
                         AND (si.active = 1 OR si.active IS NULL)"""
                ),
                {"id": invoice_id},
            ).fetchone()
            if not existing:
                raise HTTPException(status_code=404, detail="Sales invoice not found or inactive")
            existing_d = dict(existing._mapping)

            if existing_d.get("invoice_type") != INVOICE_TYPE_IDS["GOVT_SKG_FREIGHT"]:
                raise HTTPException(
                    status_code=400,
                    detail="Invoice is not a Govt Sacking Freight invoice; use the standard update flow",
                )
            if existing_d.get("status_id") != SALES_STATUS_IDS["DRAFT"]:
                raise HTTPException(
                    status_code=400,
                    detail="Only Draft (status 21) freight invoices can be edited",
                )
            if not existing_d.get("sales_invoice_freight_id"):
                raise HTTPException(
                    status_code=500,
                    detail="Freight extension row missing for this invoice",
                )

            # 2. Reject any attempt to change the source set
            freight_block = payload.get("freight") or {}
            persisted_source_ids = [
                int(r._mapping["source_invoice_id"])
                for r in db.execute(
                    get_sales_invoice_freight_source_ids(), {"invoice_id": invoice_id}
                ).fetchall()
            ]
            # Legacy rows without junction entries fall back to the single primary
            # source on sales_invoice_freight.
            if not persisted_source_ids:
                persisted_source_ids = [int(existing_d["source_invoice_id"])]

            incoming_source_ids_raw = freight_block.get("source_invoice_ids")
            if incoming_source_ids_raw is None and freight_block.get("source_invoice_id") is not None:
                incoming_source_ids_raw = [freight_block.get("source_invoice_id")]
            if incoming_source_ids_raw is not None:
                try:
                    incoming_source_ids = [int(s) for s in incoming_source_ids_raw]
                except (TypeError, ValueError):
                    raise HTTPException(status_code=400, detail="Invalid source_invoice_ids; expected integers")
                if sorted(incoming_source_ids) != sorted(persisted_source_ids):
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            f"Source invoice set is immutable; create a new freight invoice instead. "
                            f"Persisted: {persisted_source_ids}. Incoming: {incoming_source_ids}."
                        ),
                    )

            # 3. Validate editable fields
            iw_bill_no_7 = freight_block.get("iw_bill_no")
            container_no_7 = freight_block.get("container_no")
            vehicle_no_7 = freight_block.get("vehicle_no")
            try:
                freight_amount_7 = float(freight_block.get("freight_amount") or 0)
            except (TypeError, ValueError):
                freight_amount_7 = 0.0
            try:
                bales_qty_7 = float(freight_block.get("bales_qty") or 0)
            except (TypeError, ValueError):
                bales_qty_7 = 0.0
            if freight_amount_7 <= 0:
                raise HTTPException(status_code=400, detail="freight.freight_amount must be greater than 0")
            if bales_qty_7 <= 0:
                raise HTTPException(status_code=400, detail="freight.bales_qty must be greater than 0")

            iw_bill_date_7 = None
            if freight_block.get("iw_bill_date"):
                try:
                    iw_bill_date_7 = datetime.strptime(str(freight_block["iw_bill_date"]), "%Y-%m-%d").date()
                except ValueError:
                    raise HTTPException(status_code=400, detail="Invalid freight.iw_bill_date; expected YYYY-MM-DD")

            invoice_date_7 = None
            if payload.get("date"):
                try:
                    invoice_date_7 = datetime.strptime(str(payload["date"]), "%Y-%m-%d").date()
                except ValueError:
                    raise HTTPException(status_code=400, detail="Invalid date; expected YYYY-MM-DD")

            # 4. Recompute footer notes + tax + totals (mirror create-flow logic)
            # Load every persisted source header so the regenerated footer keeps
            # the "Source Invoices: ..." list + DO segment that create wrote.
            src_headers_7: list[dict] = []
            for sid in persisted_source_ids:
                row = db.execute(
                    get_govt_sacking_source_by_id(),
                    {"invoice_id": sid, "co_id": None},
                ).fetchone()
                if row:
                    src_headers_7.append(dict(row._mapping))
            src_hdr_7 = src_headers_7[0] if src_headers_7 else {}

            def _fmt_d(d):
                if not d:
                    return ""
                if isinstance(d, str):
                    return d
                try:
                    return d.strftime("%d-%b-%Y")
                except Exception:
                    return str(d)

            source_inv_labels_7: list[str] = []
            for h in src_headers_7:
                inv_no_raw = h.get("invoice_no")
                inv_no_fmt = str(inv_no_raw) if inv_no_raw is not None else ""
                if inv_no_raw is not None:
                    try:
                        inv_no_fmt = format_indent_no(
                            indent_no=int(inv_no_raw),
                            co_prefix=h.get("co_prefix") or src_hdr_7.get("co_prefix"),
                            branch_prefix=h.get("branch_prefix") or src_hdr_7.get("branch_prefix"),
                            indent_date=h.get("invoice_date"),
                            document_type=SALES_DOC_TYPES.get("INVOICE", "SI"),
                        )
                    except Exception:
                        inv_no_fmt = str(inv_no_raw)
                inv_date_fmt = _fmt_d(h.get("invoice_date"))
                source_inv_labels_7.append(f"{inv_no_fmt} dated {inv_date_fmt}" if inv_date_fmt else inv_no_fmt)

            do_fmt_7 = ""
            do_raw_7 = src_hdr_7.get("delivery_order_no")
            if do_raw_7 is not None:
                try:
                    do_fmt_7 = format_indent_no(
                        indent_no=int(do_raw_7),
                        co_prefix=src_hdr_7.get("co_prefix"),
                        branch_prefix=src_hdr_7.get("branch_prefix"),
                        indent_date=src_hdr_7.get("invoice_date"),
                        document_type=SALES_DOC_TYPES.get("DELIVERY_ORDER", "DO"),
                    )
                except Exception:
                    do_fmt_7 = str(do_raw_7)

            pcso_no_7 = src_hdr_7.get("pcso_no")
            pcso_date_7 = src_hdr_7.get("pcso_date")
            parts_7 = []
            if source_inv_labels_7:
                parts_7.append("Source Invoices: " + ", ".join(source_inv_labels_7))
            if pcso_no_7:
                parts_7.append(f"PCSO No.{pcso_no_7} Date:{_fmt_d(pcso_date_7)}")
            if do_fmt_7:
                parts_7.append(f"DO {do_fmt_7}")
            if iw_bill_no_7:
                iw_label_7 = "RR No." if (str(src_hdr_7.get("mode_of_transport") or "").upper().strip() == "RAIL") else "IW Bill No."
                parts_7.append(f"{iw_label_7}{iw_bill_no_7} Date:{_fmt_d(iw_bill_date_7)}")
            if container_no_7:
                parts_7.append(f"Container No.{container_no_7}")
            footer_raw_7 = " | ".join(parts_7)
            footer_notes_7 = footer_raw_7 if len(footer_raw_7) <= 255 else footer_raw_7[:252] + "..."

            src_branch_state_code_7 = src_hdr_7.get("branch_state_code")
            src_shipping_state_code_7 = src_hdr_7.get("shipping_state_code")
            if src_branch_state_code_7 is not None and src_shipping_state_code_7 is not None:
                intra_inter_7 = 0 if str(src_branch_state_code_7) == str(src_shipping_state_code_7) else 1
            else:
                intra_inter_7 = existing_d.get("intra_inter_state")

            tax_total_7 = round(freight_amount_7 * 0.18, 2)
            if str(intra_inter_7) == "0":
                cgst_amt_7 = round(tax_total_7 / 2, 2)
                sgst_amt_7 = round(tax_total_7 - cgst_amt_7, 2)
                igst_amt_7 = 0.0
                cgst_pct_7, sgst_pct_7, igst_pct_7 = 9.0, 9.0, 0.0
            else:
                cgst_amt_7 = 0.0
                sgst_amt_7 = 0.0
                igst_amt_7 = tax_total_7
                cgst_pct_7, sgst_pct_7, igst_pct_7 = 0.0, 0.0, 18.0
            total_amount_7 = round(freight_amount_7 + tax_total_7, 2)
            rate_per_bale_7 = freight_amount_7 / bales_qty_7

            # 5. Update the four affected rows (header, single line, line GST, freight ext)
            db.execute(
                text(
                    """UPDATE sales_invoice
                       SET invoice_date = COALESCE(:invoice_date, invoice_date),
                           container_no = :container_no,
                           vehicle_no = :vehicle_no,
                           footer_notes = :footer_notes,
                           invoice_amount = :invoice_amount,
                           tax_amount = :tax_amount,
                           tax_payable = :tax_payable,
                           intra_inter_state = :intra_inter_state,
                           updated_by = :updated_by
                       WHERE invoice_id = :invoice_id"""
                ),
                {
                    "invoice_date": invoice_date_7,
                    "container_no": container_no_7,
                    "vehicle_no": vehicle_no_7,
                    "footer_notes": footer_notes_7,
                    "invoice_amount": freight_amount_7,
                    "tax_amount": tax_total_7,
                    "tax_payable": tax_total_7,
                    "intra_inter_state": intra_inter_7,
                    "updated_by": user_id_7,
                    "invoice_id": invoice_id,
                },
            )

            # Look up the single line so we can update its qty/rate/amount/GST in place
            line_row_7 = db.execute(
                text(
                    """SELECT invoice_line_item_id
                       FROM sales_invoice_dtl
                       WHERE invoice_id = :invoice_id
                         AND (active = 1 OR active IS NULL)
                       ORDER BY invoice_line_item_id
                       LIMIT 1"""
                ),
                {"invoice_id": invoice_id},
            ).fetchone()
            if not line_row_7:
                raise HTTPException(status_code=500, detail="Freight invoice has no line item to update")
            line_id_7 = int(dict(line_row_7._mapping)["invoice_line_item_id"])

            src_first_line_row_7 = db.execute(
                get_govt_sacking_source_lines(),
                {"invoice_id": int(existing_d["source_invoice_id"])},
            ).fetchone()
            src_item_name_7 = (dict(src_first_line_row_7._mapping).get("item_name") or "") if src_first_line_row_7 else ""
            line_remarks_raw_7 = f"{src_item_name_7} — {int(bales_qty_7)} bales"
            line_remarks_7 = line_remarks_raw_7 if len(line_remarks_raw_7) <= 255 else line_remarks_raw_7[:252] + "..."

            db.execute(
                text(
                    """UPDATE sales_invoice_dtl
                       SET quantity = :quantity,
                           rate = :rate,
                           amount_without_tax = :amount_without_tax,
                           total_amount = :total_amount,
                           remarks = :remarks
                       WHERE invoice_line_item_id = :line_id"""
                ),
                {
                    "quantity": bales_qty_7,
                    "rate": rate_per_bale_7,
                    "amount_without_tax": freight_amount_7,
                    "total_amount": total_amount_7,
                    "remarks": line_remarks_7,
                    "line_id": line_id_7,
                },
            )

            db.execute(
                text(
                    """UPDATE sales_invoice_dtl_gst
                       SET tax_percentage = 18.0,
                           cgst_amount = :cgst_amount,
                           cgst_percentage = :cgst_pct,
                           sgst_amount = :sgst_amount,
                           sgst_percentage = :sgst_pct,
                           igst_amount = :igst_amount,
                           igst_percentage = :igst_pct,
                           tax_amount = :tax_amount
                       WHERE invoice_line_item_id = :line_id"""
                ),
                {
                    "cgst_amount": cgst_amt_7,
                    "cgst_pct": cgst_pct_7,
                    "sgst_amount": sgst_amt_7,
                    "sgst_pct": sgst_pct_7,
                    "igst_amount": igst_amt_7,
                    "igst_pct": igst_pct_7,
                    "tax_amount": tax_total_7,
                    "line_id": line_id_7,
                },
            )

            db.execute(
                update_sales_invoice_freight(),
                {
                    "iw_bill_no": iw_bill_no_7,
                    "iw_bill_date": iw_bill_date_7,
                    "updated_by": user_id_7,
                    "updated_date_time": now_ist(),
                    "invoice_id": invoice_id,
                },
            )

            db.commit()
            return {
                "message": "Govt Sacking Freight invoice updated successfully",
                "invoice_id": invoice_id,
                "status_id": SALES_STATUS_IDS["DRAFT"],
            }

        # ---------------------------------------------------------------
        # Existing flow (all other invoice types)
        # ---------------------------------------------------------------
        branch_id = to_int(payload.get("branch"), "branch", required=True)
        party_id = to_int(payload.get("party"), "party", required=True)

        date_str = payload.get("date")
        if not date_str:
            raise HTTPException(status_code=400, detail="date is required")
        try:
            invoice_date = datetime.strptime(str(date_str), "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format, expected YYYY-MM-DD")

        raw_items = payload.get("items")
        if not isinstance(raw_items, list) or len(raw_items) == 0:
            raise HTTPException(status_code=400, detail="At least one item row is required")

        # Verify exists
        check_query = text("SELECT invoice_id, status_id, active FROM sales_invoice WHERE invoice_id = :id AND (active = 1 OR active IS NULL)")
        check_result = db.execute(check_query, {"id": invoice_id}).fetchone()
        if not check_result:
            raise HTTPException(status_code=404, detail="Sales invoice not found or inactive")

        user_id = to_int(token_data.get("user_id"), "user_id")

        transporter_id = to_int(payload.get("transporter"), "transporter")
        sales_delivery_order_id = to_int(payload.get("sales_delivery_order_id"), "sales_delivery_order_id")
        broker_id = to_int(payload.get("broker_id") or payload.get("broker"), "broker_id")
        # Frontend sends `billing_to` / `shipping_to` (matching the create endpoint).
        # `_id` suffix kept as a defensive fallback.
        billing_to_id = to_int(payload.get("billing_to") or payload.get("billing_to_id"), "billing_to")
        shipping_to_id = to_int(payload.get("shipping_to") or payload.get("shipping_to_id"), "shipping_to")

        gross_amount = round_amount(to_float(payload.get("gross_amount"), "gross_amount"))
        freight_charges = round_amount(to_float(payload.get("freight_charges"), "freight_charges"))
        round_off = round_amount(to_float(payload.get("round_off"), "round_off"))
        tax_amount = round_amount(to_float(payload.get("tax_amount"), "tax_amount"))
        tax_payable = round_amount(to_float(payload.get("tax_payable"), "tax_payable"))

        challan_date = None
        if payload.get("challan_date"):
            try:
                challan_date = datetime.strptime(str(payload["challan_date"]), "%Y-%m-%d").date()
            except ValueError:
                pass

        eway_bill_date = None
        if payload.get("eway_bill_date"):
            try:
                eway_bill_date = datetime.strptime(str(payload["eway_bill_date"]), "%Y-%m-%d").date()
            except ValueError:
                pass

        # Jute-specific: extract fields and adjust invoice_amount for claim deduction
        invoice_type = to_int(payload.get("invoice_type"), "invoice_type")
        jute_data = payload.get("jute") or {}
        govtskg_data = payload.get("govtskg") or {}

        due_date = None
        if payload.get("due_date"):
            try:
                due_date = datetime.strptime(str(payload["due_date"]), "%Y-%m-%d").date()
            except ValueError:
                pass

        contract_date = None
        if payload.get("contract_date"):
            try:
                contract_date = datetime.strptime(str(payload["contract_date"]), "%Y-%m-%d").date()
            except ValueError:
                pass

        consignment_date = None
        if payload.get("consignment_date"):
            try:
                consignment_date = datetime.strptime(str(payload["consignment_date"]), "%Y-%m-%d").date()
            except ValueError:
                pass

        # Extract 9 new fields for e-invoice
        transporter_branch_id = to_int(payload.get("transporter_branch_id"), "transporter_branch_id")
        transporter_doc_no = payload.get("transporter_doc_no")
        transporter_doc_date = None
        if payload.get("transporter_doc_date"):
            try:
                transporter_doc_date = datetime.strptime(str(payload["transporter_doc_date"]), "%Y-%m-%d").date()
            except ValueError:
                pass
        buyer_order_no = payload.get("buyer_order_no")
        buyer_order_date = None
        if payload.get("buyer_order_date"):
            try:
                buyer_order_date = datetime.strptime(str(payload["buyer_order_date"]), "%Y-%m-%d").date()
            except ValueError:
                pass
        irn = payload.get("irn")
        ack_no = payload.get("ack_no")
        ack_date = None
        if payload.get("ack_date"):
            try:
                ack_date = datetime.strptime(str(payload["ack_date"]), "%Y-%m-%d").date()
            except ValueError:
                pass
        qr_code = payload.get("qr_code")

        # Update header
        update_hdr = update_sales_invoice()
        db.execute(update_hdr, {
            "invoice_id": invoice_id,
            "invoice_date": invoice_date,
            "branch_id": branch_id,
            "party_id": party_id,
            "sales_delivery_order_id": sales_delivery_order_id,
            "broker_id": broker_id,
            "billing_to_id": billing_to_id,
            "shipping_to_id": shipping_to_id,
            "challan_no": payload.get("challan_no"),
            "challan_date": challan_date,
            "transporter_id": transporter_id,
            "vehicle_no": payload.get("vehicle_no"),
            "transporter_name": payload.get("transporter_name"),
            "transporter_address": payload.get("transporter_address"),
            "transporter_state_code": payload.get("transporter_state_code"),
            "transporter_state_name": payload.get("transporter_state_name"),
            "eway_bill_no": payload.get("eway_bill_no"),
            "eway_bill_date": eway_bill_date,
            "invoice_type": invoice_type,
            "footer_notes": payload.get("footer_note"),
            "internal_note": payload.get("internal_note"),
            "terms": payload.get("terms"),
            "terms_conditions": payload.get("terms_conditions"),
            "invoice_amount": gross_amount or 0,
            "tax_amount": tax_amount or 0,
            "tax_payable": tax_payable,
            "freight_charges": freight_charges or 0,
            "round_off": round_off or 0,
            "shipping_state_code": to_int(payload.get("shipping_state_code"), "shipping_state_code"),
            "intra_inter_state": payload.get("intra_inter_state"),
            "due_date": due_date,
            "type_of_sale": payload.get("type_of_sale"),
            "tax_id": to_int(payload.get("tax_id"), "tax_id"),
            "container_no": payload.get("container_no"),
            "contract_no": to_int(payload.get("contract_no"), "contract_no"),
            "contract_date": contract_date,
            "consignment_no": payload.get("consignment_no"),
            "consignment_date": consignment_date,
            "payment_terms": to_int(payload.get("payment_terms"), "payment_terms"),
            "sales_order_id": to_int(payload.get("sales_order_id"), "sales_order_id"),
            "billing_state_code": to_int(payload.get("billing_state_code"), "billing_state_code"),
            "bank_detail_id": to_int(payload.get("bank_detail_id"), "bank_detail_id"),
            "transporter_branch_id": transporter_branch_id,
            "transporter_doc_no": transporter_doc_no,
            "transporter_doc_date": transporter_doc_date,
            "buyer_order_no": buyer_order_no,
            "buyer_order_date": buyer_order_date,
            "irn": irn,
            "ack_no": ack_no,
            "ack_date": ack_date,
            "qr_code": qr_code,
            "updated_by": user_id,
        })

        # Delete old GST, jute detail, jute header, govtskg, and hessian detail before re-inserting
        db.execute(delete_sales_invoice_dtl_gst(), {"invoice_id": invoice_id})
        db.execute(delete_sales_invoice_jute_dtl(), {"invoice_id": invoice_id})
        db.execute(delete_sales_invoice_jute(), {"invoice_id": invoice_id})
        db.execute(delete_sales_invoice_govtskg(), {"invoice_id": invoice_id})
        db.execute(delete_sale_invoice_govtskg_dtl(), {"invoice_id": invoice_id})
        db.execute(delete_sales_invoice_hessian_dtl(), {"invoice_id": invoice_id})

        # Delete old additional charges
        from src.sales.query import delete_sales_invoice_additional_gst, delete_sales_invoice_additional
        db.execute(delete_sales_invoice_additional_gst(), {"invoice_id": invoice_id})
        db.execute(delete_sales_invoice_additional(), {"invoice_id": invoice_id})

        # Soft-delete old line items
        delete_q = delete_invoice_line_items()
        db.execute(delete_q, {"invoice_id": invoice_id})

        # Re-insert line items + GST + type-specific detail
        line_query = insert_invoice_line_item()
        gst_query = insert_sales_invoice_dtl_gst()
        jute_dtl_query = insert_sales_invoice_jute_dtl()
        hessian_dtl_query = insert_sales_invoice_hessian_dtl()
        govtskg_dtl_query = insert_sale_invoice_govtskg_dtl()
        normalized_items = []
        HESSIAN_INVOICE_TYPE_ID = INVOICE_TYPE_IDS.get("HESSIAN")

        # Pre-fetch rate_rounding for every line so per-item rate precision is applied.
        update_rate_rounding_map = fetch_item_rate_roundings(
            db,
            [to_int(it.get("item"), f"items[{i}].item")
             for i, it in enumerate(raw_items, start=1)
             if it.get("item")],
        )

        for idx, item in enumerate(raw_items, start=1):
            item_val = item.get("item")
            if not item_val:
                raise HTTPException(status_code=400, detail=f"items[{idx}].item is required")
            uom_val = item.get("uom")
            if not uom_val:
                raise HTTPException(status_code=400, detail=f"items[{idx}].uom is required")

            qty = to_positive_float(item.get("quantity"), f"items[{idx}].quantity")
            rate = to_float(item.get("rate"), f"items[{idx}].rate")
            rate_decimals = update_rate_rounding_map.get(to_int(item_val, f"items[{idx}].item"))
            rate = round_rate(rate, rate_decimals)

            # Hessian: recompute qty (MT), rate (billing rate MT, rounded to 2),
            # and hessian_dtl derived fields using the shared formula.
            # Mirrors vowerp3ui/src/utils/hessianCalculations.ts.
            if invoice_type == HESSIAN_INVOICE_TYPE_ID:
                hessian_dtl_data = item.get("hessian_dtl") or {}
                qty_bales = to_float(hessian_dtl_data.get("qty_bales"), "qty_bales")
                if hessian_dtl_data and qty_bales and qty_bales > 0 and rate:
                    item_id_for_conv = to_int(item_val, f"items[{idx}].item")
                    conv_row = db.execute(
                        get_hessian_mt_conversion(), {"item_id": item_id_for_conv}
                    ).fetchone()
                    if conv_row:
                        conv_map = dict(conv_row._mapping)
                        conv_factor = float(conv_map.get("relation_value") or 0)
                        if conv_factor > 0:
                            conv_rounding = resolve_qty_rounding(conv_map.get("rounding"))
                            h = compute_hessian_fields(qty_bales, rate, conv_factor, conv_rounding)
                            qty = h["qty_mt"]
                            rate = round_rate(h["billing_rate_mt"], rate_decimals)
                            hessian_dtl_data["qty_bales"] = qty_bales
                            hessian_dtl_data["rate_per_bale"] = round_amount(h["rate_per_bale"])
                            hessian_dtl_data["billing_rate_mt"] = rate
                            hessian_dtl_data["billing_rate_bale"] = round_rate(h["billing_rate_bale"], rate_decimals)
                            item["hessian_dtl"] = hessian_dtl_data

            amount_without_tax = to_float(item.get("net_amount"), f"items[{idx}].net_amount")
            if amount_without_tax is None and qty and rate:
                amount_without_tax = qty * rate
            if amount_without_tax is not None:
                amount_without_tax = round_amount(amount_without_tax)

            gst = item.get("gst") or {}
            cgst_amt = round_amount(to_float(gst.get("cgst_amount"), "cgst_amount"))
            sgst_amt = round_amount(to_float(gst.get("sgst_amount"), "sgst_amount"))
            igst_amt = round_amount(to_float(gst.get("igst_amount"), "igst_amount"))
            if isinstance(gst, dict) and gst:
                gst["cgst_amount"] = cgst_amt
                gst["sgst_amount"] = sgst_amt
                gst["igst_amount"] = igst_amt
                gst["gst_total"] = round_amount(to_float(gst.get("gst_total"), "gst_total"))

            line_total = to_float(item.get("total_amount"), f"items[{idx}].total_amount")
            if line_total is None and amount_without_tax is not None:
                line_tax = (cgst_amt or 0) + (sgst_amt or 0) + (igst_amt or 0)
                line_total = round_amount((amount_without_tax or 0) + line_tax)
            else:
                line_total = round_amount(line_total)

            dtl_result = db.execute(line_query, {
                "invoice_id": invoice_id,
                "hsn_code": item.get("hsn_code"),
                "item_id": to_int(item_val, f"items[{idx}].item"),
                "item_make_id": to_int(item.get("item_make"), f"items[{idx}].item_make"),
                "quantity": qty,
                "uom_id": to_int(uom_val, f"items[{idx}].uom"),
                "rate": rate,
                "discount_type": item.get("discount_type"),
                "discounted_rate": round_rate(to_float(item.get("discounted_rate"), f"items[{idx}].discounted_rate"), rate_decimals),
                "discount_amount": round_amount(to_float(item.get("discount_amount"), f"items[{idx}].discount_amount")),
                "amount_without_tax": amount_without_tax,
                "total_amount": line_total,
                "sales_weight": to_float(item.get("sales_weight"), f"items[{idx}].sales_weight"),
                "remarks": item.get("remarks"),
                "delivery_order_dtl_id": to_int(item.get("delivery_order_dtl_id"), f"items[{idx}].delivery_order_dtl_id"),
                "sales_order_dtl_id": to_int(item.get("sales_order_dtl_id"), f"items[{idx}].sales_order_dtl_id"),
            })
            lineitem_id = dtl_result.lastrowid

            # Insert GST into separate table
            gst_data = gst if gst else None
            if gst_data and isinstance(gst_data, dict) and lineitem_id:
                db.execute(gst_query, {
                    "invoice_line_item_id": lineitem_id,
                    "tax_percentage": to_float(gst_data.get("tax_percentage"), "tax_percentage"),
                    "cgst_amount": round_amount(to_float(gst_data.get("cgst_amount"), "cgst_amount")) or 0,
                    "cgst_percentage": to_float(gst_data.get("cgst_percent"), "cgst_percent") or 0,
                    "sgst_amount": round_amount(to_float(gst_data.get("sgst_amount"), "sgst_amount")) or 0,
                    "sgst_percentage": to_float(gst_data.get("sgst_percent"), "sgst_percent") or 0,
                    "igst_amount": round_amount(to_float(gst_data.get("igst_amount"), "igst_amount")) or 0,
                    "igst_percentage": to_float(gst_data.get("igst_percent"), "igst_percent") or 0,
                    "tax_amount": round_amount(to_float(gst_data.get("tax_amount"), "gst_tax_amount")) or 0,
                })

            # Insert jute detail into separate table
            jute_dtl_data = item.get("jute_dtl") or None
            if jute_dtl_data and isinstance(jute_dtl_data, dict) and lineitem_id:
                db.execute(jute_dtl_query, {
                    "invoice_line_item_id": lineitem_id,
                    "claim_amount_dtl": to_float(jute_dtl_data.get("claim_amount_dtl"), "claim_amount_dtl"),
                    "claim_desc": jute_dtl_data.get("claim_desc"),
                    "claim_rate": to_float(jute_dtl_data.get("claim_rate"), "claim_rate"),
                    "unit_conversion": jute_dtl_data.get("unit_conversion"),
                    "qty_untit_conversion": to_int(jute_dtl_data.get("qty_untit_conversion"), "qty_untit_conversion"),
                })

            # Insert hessian detail into separate table
            hessian_dtl_data = item.get("hessian_dtl") or None
            if hessian_dtl_data and isinstance(hessian_dtl_data, dict) and lineitem_id:
                db.execute(hessian_dtl_query, {
                    "invoice_line_item_id": lineitem_id,
                    "qty_bales": to_float(hessian_dtl_data.get("qty_bales"), "qty_bales"),
                    "rate_per_bale": to_float(hessian_dtl_data.get("rate_per_bale"), "rate_per_bale"),
                    "billing_rate_mt": to_float(hessian_dtl_data.get("billing_rate_mt"), "billing_rate_mt"),
                    "billing_rate_bale": to_float(hessian_dtl_data.get("billing_rate_bale"), "billing_rate_bale"),
                    "updated_by": user_id,
                })

            # Insert govt sacking detail into separate table
            govtskg_dtl_data = item.get("govtskg_dtl") or None
            if govtskg_dtl_data and isinstance(govtskg_dtl_data, dict) and lineitem_id:
                db.execute(govtskg_dtl_query, {
                    "invoice_line_item_id": lineitem_id,
                    "pack_sheet": to_float(govtskg_dtl_data.get("pack_sheet"), "pack_sheet"),
                    "net_weight": to_float(govtskg_dtl_data.get("net_weight"), "net_weight"),
                    "total_weight": to_float(govtskg_dtl_data.get("total_weight"), "total_weight"),
                    "updated_by": user_id,
                })

            normalized_items.append(item)

        # Re-insert jute header data if provided
        if jute_data:
            # Compute claim_amount as sum of line item claim_amount_dtl values
            claim_amount_from_lines = sum(
                to_float((it.get("jute_dtl") or {}).get("claim_amount_dtl"), "claim_amount_dtl") or 0
                for it in normalized_items
                if it.get("jute_dtl")
            )
            if claim_amount_from_lines:
                claim_amount = round(claim_amount_from_lines, 2)
            else:
                claim_amount = to_float(jute_data.get("claim_amount"), "claim_amount")

            db.execute(insert_sales_invoice_jute(), {
                "invoice_id": invoice_id,
                "mr_no": jute_data.get("mr_no"),
                "mr_id": to_int(jute_data.get("mr_id"), "mr_id"),
                "claim_amount": claim_amount,
                "other_reference": jute_data.get("other_reference"),
                "unit_conversion": jute_data.get("unit_conversion"),
                "claim_description": jute_data.get("claim_description"),
                "mukam_id": to_int(jute_data.get("mukam_id"), "mukam_id"),
            })

        # Re-insert govt SKG header data if provided
        if govtskg_data:
            db.execute(insert_sales_invoice_govtskg(), {
                "invoice_id": invoice_id,
                "pcso_no": govtskg_data.get("pcso_no"),
                "pcso_date": format_date(govtskg_data.get("pcso_date")),
                "administrative_office_address": govtskg_data.get("administrative_office_address"),
                "destination_rail_head": govtskg_data.get("destination_rail_head"),
                "loading_point": govtskg_data.get("loading_point"),
                "mode_of_transport": govtskg_data.get("mode_of_transport"),
                "pack_sheet": to_float(govtskg_data.get("pack_sheet"), "pack_sheet"),
                "net_weight": to_float(govtskg_data.get("net_weight"), "net_weight"),
                "total_weight": to_float(govtskg_data.get("total_weight"), "total_weight"),
            })

        # Re-insert additional charges
        additional_charges_list = payload.get("additional_charges") or []
        if additional_charges_list:
            from src.sales.query import insert_sales_invoice_additional, insert_sales_invoice_additional_gst
            add_query = insert_sales_invoice_additional()
            add_gst_query = insert_sales_invoice_additional_gst()
            for charge in additional_charges_list:
                charge_result = db.execute(add_query, {
                    "invoice_id": invoice_id,
                    "additional_charges_id": to_int(charge.get("additional_charges_id"), "additional_charges_id"),
                    "qty": round_amount(to_float(charge.get("qty"), "qty")),
                    "rate": round_amount(to_float(charge.get("rate"), "rate")),
                    "net_amount": round_amount(to_float(charge.get("net_amount"), "net_amount")),
                    "remarks": charge.get("remarks"),
                    "updated_by": user_id,
                    "updated_date_time": now_ist(),
                })
                charge_id = charge_result.lastrowid
                gst_data = charge.get("gst")
                if gst_data and isinstance(gst_data, dict) and charge_id:
                    db.execute(add_gst_query, {
                        "sales_invoice_additional_id": charge_id,
                        "igst_amount": round_amount(to_float(gst_data.get("igst_amount"), "igst_amount")),
                        "igst_percent": to_float(gst_data.get("igst_percent"), "igst_percent"),
                        "cgst_amount": round_amount(to_float(gst_data.get("cgst_amount"), "cgst_amount")),
                        "cgst_percent": to_float(gst_data.get("cgst_percent"), "cgst_percent"),
                        "sgst_amount": round_amount(to_float(gst_data.get("sgst_amount"), "sgst_amount")),
                        "sgst_percent": to_float(gst_data.get("sgst_percent"), "sgst_percent"),
                        "gst_total": round_amount(to_float(gst_data.get("gst_total"), "gst_total")),
                    })

        db.commit()
        return {"message": "Sales invoice updated successfully", "invoice_id": invoice_id}
    except HTTPException as exc:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error updating sales invoice")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# WORKFLOW ENDPOINTS
# =============================================================================


@router.post("/open_sales_invoice")
def open_sales_invoice(
    payload: dict,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Open a sales invoice (21 -> 1). Generates document number."""
    try:
        invoice_id = to_int(payload.get("invoice_id"), "invoice_id", required=True)
        branch_id = to_int(payload.get("branch_id"), "branch_id", required=True)
        user_id = int(token_data.get("user_id"))

        doc_query = get_invoice_with_approval_info()
        doc_result = db.execute(doc_query, {"invoice_id": invoice_id}).fetchone()
        if not doc_result:
            raise HTTPException(status_code=404, detail="Sales invoice not found")
        doc = dict(doc_result._mapping)

        if doc.get("status_id") != 21:
            raise HTTPException(status_code=400, detail=f"Cannot open invoice with status {doc.get('status_id')}. Expected 21 (Draft).")

        invoice_date = doc.get("invoice_date")
        if not invoice_date:
            raise HTTPException(status_code=400, detail="Invoice date is required to generate document number.")

        current_no = doc.get("invoice_no")
        new_no = None
        new_no_string = None
        if current_no is None or current_no == "" or current_no == 0:
            fy_start, fy_end = get_fy_boundaries(invoice_date)
            max_query = get_max_invoice_no_for_branch_fy()
            max_result = db.execute(max_query, {"branch_id": branch_id, "fy_start_date": fy_start, "fy_end_date": fy_end}).fetchone()
            max_no = dict(max_result._mapping).get("max_doc_no") or 0 if max_result else 0
            new_no = int(max_no) + 1

            # Get prefixes for formatted number string
            branch_row = db.execute(
                text("SELECT bm.branch_prefix, cm.co_prefix FROM branch_mst bm LEFT JOIN co_mst cm ON cm.co_id = bm.co_id WHERE bm.branch_id = :branch_id"),
                {"branch_id": branch_id},
            ).fetchone()
            if branch_row:
                bdata = dict(branch_row._mapping)
                try:
                    new_no_string = format_indent_no(
                        indent_no=new_no,
                        co_prefix=bdata.get("co_prefix"),
                        branch_prefix=bdata.get("branch_prefix"),
                        indent_date=invoice_date,
                        document_type=SALES_DOC_TYPES.get("INVOICE", "SI"),
                    )
                except Exception:
                    new_no_string = str(new_no)

        update_q = update_invoice_status()
        db.execute(update_q, {
            "invoice_id": invoice_id,
            "status_id": 1,
            "approval_level": None,
            "invoice_no": new_no,
            "updated_by": user_id,
            "updated_date_time": now_ist(),
        })
        db.commit()

        return {
            "status": "success",
            "new_status_id": 1,
            "message": "Sales invoice opened successfully.",
            "invoice_no": new_no_string if new_no_string else str(current_no) if current_no else None,
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error opening sales invoice")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cancel_draft_sales_invoice")
def cancel_draft_sales_invoice(
    payload: dict,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Cancel a draft sales invoice (21 -> 6)."""
    try:
        invoice_id = to_int(payload.get("invoice_id"), "invoice_id", required=True)
        user_id = int(token_data.get("user_id"))

        doc_query = get_invoice_with_approval_info()
        doc_result = db.execute(doc_query, {"invoice_id": invoice_id}).fetchone()
        if not doc_result:
            raise HTTPException(status_code=404, detail="Sales invoice not found")
        if dict(doc_result._mapping).get("status_id") != 21:
            raise HTTPException(status_code=400, detail="Cannot cancel. Expected status 21 (Draft).")

        update_q = update_invoice_status()
        db.execute(update_q, {
            "invoice_id": invoice_id,
            "status_id": 6,
            "approval_level": None,
            "invoice_no": None,
            "updated_by": user_id,
            "updated_date_time": now_ist(),
        })
        db.commit()
        return {"status": "success", "new_status_id": 6, "message": "Draft cancelled successfully."}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/send_sales_invoice_for_approval")
def send_sales_invoice_for_approval(
    payload: dict,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Send sales invoice for approval (1 -> 20, level=1)."""
    try:
        invoice_id = to_int(payload.get("invoice_id"), "invoice_id", required=True)
        user_id = int(token_data.get("user_id"))

        doc_query = get_invoice_with_approval_info()
        doc_result = db.execute(doc_query, {"invoice_id": invoice_id}).fetchone()
        if not doc_result:
            raise HTTPException(status_code=404, detail="Sales invoice not found")
        if dict(doc_result._mapping).get("status_id") != 1:
            raise HTTPException(status_code=400, detail="Cannot send for approval. Expected status 1 (Open).")

        update_q = update_invoice_status()
        db.execute(update_q, {
            "invoice_id": invoice_id,
            "status_id": 20,
            "approval_level": 1,
            "invoice_no": None,
            "updated_by": user_id,
            "updated_date_time": now_ist(),
        })
        db.commit()
        return {"status": "success", "new_status_id": 20, "new_approval_level": 1, "message": "Sales invoice sent for approval."}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/approve_sales_invoice")
def approve_sales_invoice(
    payload: dict,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Approve a sales invoice."""
    try:
        invoice_id = to_int(payload.get("invoice_id"), "invoice_id", required=True)
        menu_id = to_int(payload.get("menu_id"), "menu_id", required=True)
        user_id = int(token_data.get("user_id"))

        doc_query = get_invoice_with_approval_info()
        doc_result = db.execute(doc_query, {"invoice_id": invoice_id}).fetchone()
        if not doc_result:
            raise HTTPException(status_code=404, detail="Sales invoice not found")
        document_amount = float(dict(doc_result._mapping).get("invoice_amount", 0) or 0)

        result = process_approval(
            doc_id=invoice_id,
            user_id=user_id,
            menu_id=menu_id,
            db=db,
            get_doc_fn=get_invoice_with_approval_info,
            update_status_fn=update_invoice_status,
            id_param_name="invoice_id",
            doc_name="Sales invoice",
            document_amount=document_amount,
            extra_update_params={"invoice_no": None},
        )

        # Auto-post into accounting only on FINAL approval (status 3), AFTER
        # process_approval has committed — posting can never fail or roll back
        # the approval itself.
        if result.get("new_status_id") == 3:
            try:
                from src.accounting.posting_service import post_document
                result["accounting_posting"] = post_document(
                    db, "SALES_INVOICE", invoice_id, user_id
                )
            except Exception as posting_error:  # defensive: post_document never raises
                logger.error(
                    f"Accounting auto-posting failed for sales invoice "
                    f"{invoice_id}: {posting_error}"
                )
                result["accounting_posting"] = {
                    "status": "FAILED",
                    "acc_voucher_id": None,
                    "message": str(posting_error),
                }

        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reject_sales_invoice")
def reject_sales_invoice(
    payload: dict,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Reject a sales invoice (20 -> 4)."""
    try:
        invoice_id = to_int(payload.get("invoice_id"), "invoice_id", required=True)
        menu_id = to_int(payload.get("menu_id"), "menu_id")
        user_id = int(token_data.get("user_id"))
        reason = payload.get("reason")

        result = process_rejection(
            doc_id=invoice_id,
            user_id=user_id,
            menu_id=menu_id,
            db=db,
            get_doc_fn=get_invoice_with_approval_info,
            update_status_fn=update_invoice_status,
            id_param_name="invoice_id",
            doc_name="Sales invoice",
            reason=reason,
            extra_update_params={"invoice_no": None},
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reopen_sales_invoice")
def reopen_sales_invoice(
    payload: dict,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Reopen a cancelled (6 -> 21) or rejected (4 -> 1) sales invoice."""
    try:
        invoice_id = to_int(payload.get("invoice_id"), "invoice_id", required=True)
        user_id = int(token_data.get("user_id"))

        doc_query = get_invoice_with_approval_info()
        doc_result = db.execute(doc_query, {"invoice_id": invoice_id}).fetchone()
        if not doc_result:
            raise HTTPException(status_code=404, detail="Sales invoice not found")
        current_status = dict(doc_result._mapping).get("status_id")

        if current_status == 6:
            new_status_id = 21
        elif current_status == 4:
            new_status_id = 1
        else:
            raise HTTPException(status_code=400, detail=f"Cannot reopen with status {current_status}. Only 6 or 4.")

        update_q = update_invoice_status()
        db.execute(update_q, {
            "invoice_id": invoice_id,
            "status_id": new_status_id,
            "approval_level": None,
            "invoice_no": None,
            "updated_by": user_id,
            "updated_date_time": now_ist(),
        })
        db.commit()
        return {"status": "success", "new_status_id": new_status_id, "message": f"Sales invoice reopened (status: {new_status_id})."}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
