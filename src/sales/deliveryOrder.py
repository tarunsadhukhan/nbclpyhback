from fastapi import Depends, Request, HTTPException, APIRouter
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
    get_approved_sales_orders_query,
    get_sales_order_lines_for_delivery,
    get_item_by_group_id_saleable,
    get_item_uom_by_group_id_saleable,
    insert_sales_delivery_order,
    insert_sales_delivery_order_dtl,
    insert_sales_delivery_order_dtl_gst,
    update_sales_delivery_order,
    delete_sales_delivery_order_dtl,
    delete_sales_delivery_order_dtl_gst,
    get_delivery_order_table_query,
    get_delivery_order_table_count_query,
    get_delivery_order_by_id_query,
    get_delivery_order_dtl_by_id_query,
    get_delivery_order_gst_by_id_query,
    update_delivery_order_status,
    get_delivery_order_with_approval_info,
    get_max_delivery_order_no_for_branch_fy,
)
from src.sales.constants import SALES_DOC_TYPES

logger = logging.getLogger(__name__)

router = APIRouter()


# =============================================================================
# SETUP ENDPOINTS
# =============================================================================

@router.get("/get_delivery_order_setup_1")
def get_delivery_order_setup_1(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    branch_id: int | None = None,
    co_id: int | None = None,
):
    """Return branches, customers, transporters, and approved sales orders for delivery order creation."""
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

        # Approved sales orders for dropdown
        aso_query = get_approved_sales_orders_query()
        aso_result = db.execute(aso_query, {"branch_id": branch_id, "co_id": co_id}).fetchall()
        approved_orders = []
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
                        document_type=SALES_DOC_TYPES["SALES_ORDER"],
                    )
                except Exception:
                    formatted_no = str(raw_no) if raw_no else ""
            approved_orders.append({
                "sales_order_id": mapped.get("sales_order_id"),
                "sales_no": formatted_no,
                "sales_order_date": format_date(mapped.get("sales_order_date")),
                "party_id": mapped.get("party_id"),
                "party_name": mapped.get("party_name"),
                "net_amount": mapped.get("net_amount"),
                "invoice_type": mapped.get("invoice_type"),
                "broker_id": mapped.get("broker_id"),
                "billing_to_id": mapped.get("billing_to_id"),
                "shipping_to_id": mapped.get("shipping_to_id"),
                "transporter_id": mapped.get("transporter_id"),
            })

        # Item groups (for manual entry without sales order)
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

        return {
            "branches": branches,
            "customers": customers,
            "brokers": brokers,
            "transporters": transporters,
            "approved_sales_orders": approved_orders,
            "item_groups": item_groups,
            "invoice_types": invoice_types,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching delivery order setup 1")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_delivery_order_setup_2")
def get_delivery_order_setup_2(
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


@router.get("/get_sales_order_lines")
def get_sales_order_lines(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Get sales order line items to pre-fill a new delivery order."""
    try:
        q_id = request.query_params.get("sales_order_id")
        if q_id is None:
            raise HTTPException(status_code=400, detail="sales_order_id is required")

        sales_order_id = int(q_id)
        query = get_sales_order_lines_for_delivery()
        result = db.execute(query, {"sales_order_id": sales_order_id}).fetchall()
        data = [dict(r._mapping) for r in result]
        return {"data": data}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# CRUD ENDPOINTS
# =============================================================================

@router.get("/get_delivery_order_table")
def get_delivery_order_table(
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
    """Return paginated delivery order list."""
    try:
        page = max(page, 1)
        limit = max(min(limit, 100), 1)
        offset = (page - 1) * limit
        search_like = f"%{search.strip()}%" if search else None

        params = {"co_id": co_id, "branch_id": branch_id, "status_id": status_id, "search_like": search_like, "limit": limit, "offset": offset}

        list_query = get_delivery_order_table_query()
        rows = db.execute(list_query, params).fetchall()
        data = []
        for row in rows:
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
                        document_type=SALES_DOC_TYPES["DELIVERY_ORDER"],
                    )
                except Exception:
                    formatted_no = str(raw_no) if raw_no else ""

            data.append({
                "sales_delivery_order_id": mapped.get("sales_delivery_order_id"),
                "delivery_order_no": formatted_no,
                "delivery_order_date": format_date(mapped.get("delivery_order_date")),
                "expected_delivery_date": format_date(mapped.get("expected_delivery_date")),
                "branch_id": mapped.get("branch_id"),
                "branch_name": mapped.get("branch_name"),
                "party_name": mapped.get("party_name"),
                "sales_no": mapped.get("sales_no"),
                "net_amount": mapped.get("net_amount"),
                "status": mapped.get("status_name"),
                "status_id": mapped.get("status_id"),
            })

        count_query = get_delivery_order_table_count_query()
        count_result = db.execute(count_query, {"co_id": co_id, "branch_id": branch_id, "status_id": status_id, "search_like": search_like}).scalar()
        total = int(count_result) if count_result is not None else 0

        return {"data": data, "total": total}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_delivery_order_by_id")
def get_delivery_order_by_id(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Return delivery order details by ID with line items and GST."""
    try:
        q_id = request.query_params.get("sales_delivery_order_id")
        q_co_id = request.query_params.get("co_id")
        if q_id is None:
            raise HTTPException(status_code=400, detail="sales_delivery_order_id is required")
        if q_co_id is None:
            raise HTTPException(status_code=400, detail="co_id is required")

        try:
            sales_delivery_order_id = int(q_id)
            co_id = int(q_co_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid sales_delivery_order_id or co_id")

        # Header
        header_query = get_delivery_order_by_id_query()
        header_result = db.execute(header_query, {"sales_delivery_order_id": sales_delivery_order_id, "co_id": co_id}).fetchone()
        if not header_result:
            raise HTTPException(status_code=404, detail="Delivery order not found or access denied")
        header = dict(header_result._mapping)

        # Details
        detail_query = get_delivery_order_dtl_by_id_query()
        detail_results = db.execute(detail_query, {"sales_delivery_order_id": sales_delivery_order_id}).fetchall()
        details = [dict(r._mapping) for r in detail_results]

        # GST
        gst_query = get_delivery_order_gst_by_id_query()
        gst_results = db.execute(gst_query, {"sales_delivery_order_id": sales_delivery_order_id}).fetchall()
        gst_map: dict[int, dict] = {}
        for g in gst_results:
            gd = dict(g._mapping)
            gst_map[gd.get("sales_delivery_order_dtl_id")] = gd

        # Format delivery_order_no
        raw_no = header.get("delivery_order_no")
        formatted_no = ""
        if raw_no is not None:
            try:
                formatted_no = format_indent_no(
                    indent_no=int(raw_no) if raw_no else None,
                    co_prefix=header.get("co_prefix"),
                    branch_prefix=header.get("branch_prefix"),
                    indent_date=header.get("delivery_order_date"),
                    document_type=SALES_DOC_TYPES["DELIVERY_ORDER"],
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

        response = {
            "id": str(header.get("sales_delivery_order_id", "")),
            "deliveryOrderNo": formatted_no,
            "deliveryOrderDate": format_date(header.get("delivery_order_date")),
            "expectedDeliveryDate": format_date(header.get("expected_delivery_date")),
            "branch": str(header.get("branch_id", "")) if header.get("branch_id") else "",
            "invoiceType": str(header.get("invoice_type", "")) if header.get("invoice_type") else None,
            "salesOrder": str(header.get("sales_order_id", "")) if header.get("sales_order_id") else None,
            "salesNo": header.get("sales_no"),
            "party": str(header.get("party_id", "")) if header.get("party_id") else "",
            "partyName": header.get("party_name"),
            "billingTo": str(header.get("billing_to_id", "")) if header.get("billing_to_id") else None,
            "shippingTo": str(header.get("shipping_to_id", "")) if header.get("shipping_to_id") else None,
            "transporter": str(header.get("transporter_id", "")) if header.get("transporter_id") else None,
            "transporterName": header.get("transporter_name"),
            "vehicleNo": header.get("vehicle_no"),
            "driverName": header.get("driver_name"),
            "driverContact": header.get("driver_contact"),
            "footerNote": header.get("footer_note"),
            "internalNote": header.get("internal_note"),
            "grossAmount": header.get("gross_amount"),
            "netAmount": header.get("net_amount"),
            "freightCharges": header.get("freight_charges"),
            "roundOffValue": header.get("round_off_value"),
            "status": header.get("status_name"),
            "statusId": status_id,
            "approvalLevel": approval_level,
            "updatedBy": str(header.get("updated_by", "")) if header.get("updated_by") else None,
            "updatedAt": format_date(header.get("updated_date_time")),
            "lines": [],
        }

        # Load SO extension data for read-only display on DO
        so_extension = {}
        so_id = header.get("sales_order_id")
        inv_type = header.get("invoice_type")
        if so_id and inv_type:
            try:
                from src.sales.constants import INVOICE_TYPE_IDS
                if inv_type == INVOICE_TYPE_IDS["GOVT_SKG"]:  # 3
                    from src.sales.query import get_sales_order_govtskg_by_id
                    govtskg_row = db.execute(get_sales_order_govtskg_by_id(), {"sales_order_id": so_id}).fetchone()
                    if govtskg_row:
                        so_extension["govtskg"] = dict(govtskg_row._mapping)
                elif inv_type == INVOICE_TYPE_IDS["JUTE_YARN"]:  # 4
                    from src.sales.query import get_sales_order_juteyarn_by_id
                    juteyarn_row = db.execute(get_sales_order_juteyarn_by_id(), {"sales_order_id": so_id}).fetchone()
                    if juteyarn_row:
                        so_extension["juteyarn"] = dict(juteyarn_row._mapping)
                elif inv_type == INVOICE_TYPE_IDS["RAW_JUTE"]:  # 5
                    from src.sales.query import get_sales_order_jute_by_id
                    jute_row = db.execute(get_sales_order_jute_by_id(), {"sales_order_id": so_id}).fetchone()
                    if jute_row:
                        so_extension["jute"] = dict(jute_row._mapping)
            except Exception:
                logger.exception("Error loading SO extension data for DO")

        if so_extension:
            response["soExtensionData"] = so_extension

        if permissions is not None:
            response["permissions"] = permissions

        for detail in details:
            dtl_id = detail.get("sales_delivery_order_dtl_id")
            gst = gst_map.get(dtl_id, {})
            line = {
                "id": str(dtl_id) if dtl_id else "",
                "salesOrderDtlId": detail.get("sales_order_dtl_id"),
                "hsnCode": detail.get("hsn_code"),
                "itemGroup": str(detail.get("item_grp_id", "")) if detail.get("item_grp_id") else "",
                "item": str(detail.get("item_id", "")) if detail.get("item_id") else "",
                "itemCode": detail.get("full_item_code") or detail.get("item_code") or "",
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
        logger.exception("Error fetching delivery order by ID")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/create_delivery_order")
def create_delivery_order(
    payload: dict,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Create a delivery order with detail rows and GST."""
    try:
        branch_id = to_int(payload.get("branch"), "branch", required=True)
        party_id = to_int(payload.get("party"), "party", required=True)

        date_str = payload.get("date")
        if not date_str:
            raise HTTPException(status_code=400, detail="date is required")
        try:
            delivery_order_date = datetime.strptime(str(date_str), "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format, expected YYYY-MM-DD")

        raw_items = payload.get("items")
        if not isinstance(raw_items, list) or len(raw_items) == 0:
            raise HTTPException(status_code=400, detail="At least one item row is required")

        updated_by = to_int(token_data.get("user_id"), "updated_by")
        created_at = now_ist()

        sales_order_id = to_int(payload.get("sales_order"), "sales_order")
        invoice_type = to_int(payload.get("invoice_type"), "invoice_type")
        billing_to_id = to_int(payload.get("billing_to"), "billing_to")
        shipping_to_id = to_int(payload.get("shipping_to"), "shipping_to")
        transporter_id = to_int(payload.get("transporter"), "transporter")
        gross_amount = round_amount(to_float(payload.get("gross_amount"), "gross_amount"))
        net_amount = round_amount(to_float(payload.get("net_amount"), "net_amount"))
        freight_charges = round_amount(to_float(payload.get("freight_charges"), "freight_charges"))
        round_off_value = round_amount(to_float(payload.get("round_off_value"), "round_off_value"))

        expected_delivery_str = payload.get("expected_delivery_date")
        expected_delivery_date = None
        if expected_delivery_str:
            try:
                expected_delivery_date = datetime.strptime(str(expected_delivery_str), "%Y-%m-%d").date()
            except ValueError:
                pass

        # Pre-fetch rate_rounding for every line so per-item rate precision is applied.
        do_rate_rounding_map = fetch_item_rate_roundings(
            db,
            [to_int(it.get("item"), f"items[{i}].item", required=True)
             for i, it in enumerate(raw_items, start=1)],
        )

        # Normalize items
        normalized_items = []
        for idx, item in enumerate(raw_items, start=1):
            item_id = to_int(item.get("item"), f"items[{idx}].item", required=True)
            quantity = to_positive_float(item.get("quantity"), f"items[{idx}].quantity")
            uom_id = to_int(item.get("uom"), f"items[{idx}].uom", required=True)
            rate_decimals = do_rate_rounding_map.get(item_id)
            gst_in = item.get("gst") or {}
            gst_out = None
            if isinstance(gst_in, dict) and gst_in:
                gst_out = {
                    **gst_in,
                    "igst_amount": round_amount(gst_in.get("igst_amount")),
                    "cgst_amount": round_amount(gst_in.get("cgst_amount")),
                    "sgst_amount": round_amount(gst_in.get("sgst_amount")),
                    "gst_total": round_amount(gst_in.get("gst_total")),
                }
            normalized_items.append({
                "item_id": item_id,
                "item_make_id": to_int(item.get("item_make"), f"items[{idx}].item_make"),
                "sales_order_dtl_id": to_int(item.get("sales_order_dtl_id"), f"items[{idx}].sales_order_dtl_id"),
                "hsn_code": item.get("hsn_code"),
                "quantity": quantity,
                "uom_id": uom_id,
                "rate": round_rate(to_float(item.get("rate"), f"items[{idx}].rate"), rate_decimals),
                "discount_type": to_int(item.get("discount_type"), f"items[{idx}].discount_type"),
                "discounted_rate": round_rate(to_float(item.get("discounted_rate"), f"items[{idx}].discounted_rate"), rate_decimals),
                "discount_amount": round_amount(to_float(item.get("discount_amount"), f"items[{idx}].discount_amount")),
                "net_amount": round_amount(to_float(item.get("net_amount"), f"items[{idx}].net_amount")),
                "total_amount": round_amount(to_float(item.get("total_amount"), f"items[{idx}].total_amount")),
                "remarks": str(item.get("remarks", "")).strip()[:255] if item.get("remarks") else None,
                "gst": gst_out,
            })

        # Insert header
        insert_header = insert_sales_delivery_order()
        header_params = {
            "updated_by": updated_by,
            "updated_date_time": created_at,
            "delivery_order_date": delivery_order_date,
            "delivery_order_no": None,
            "branch_id": branch_id,
            "invoice_type": invoice_type,
            "sales_order_id": sales_order_id,
            "party_id": party_id,
            "billing_to_id": billing_to_id,
            "shipping_to_id": shipping_to_id,
            "transporter_id": transporter_id,
            "vehicle_no": payload.get("vehicle_no"),
            "driver_name": payload.get("driver_name"),
            "driver_contact": payload.get("driver_contact"),
            "expected_delivery_date": expected_delivery_date,
            "footer_note": payload.get("footer_note"),
            "internal_note": payload.get("internal_note"),
            "gross_amount": gross_amount,
            "net_amount": net_amount,
            "freight_charges": freight_charges,
            "round_off_value": round_off_value,
            "status_id": 21,
            "approval_level": 0,
            "active": 1,
        }

        result = db.execute(insert_header, header_params)
        delivery_order_id = result.lastrowid
        if not delivery_order_id:
            raise HTTPException(status_code=500, detail="Failed to create delivery order header")

        # Insert details and GST
        dtl_query = insert_sales_delivery_order_dtl()
        gst_query = insert_sales_delivery_order_dtl_gst()
        for item in normalized_items:
            dtl_result = db.execute(dtl_query, {
                "updated_by": updated_by,
                "updated_date_time": created_at,
                "sales_delivery_order_id": delivery_order_id,
                "sales_order_dtl_id": item["sales_order_dtl_id"],
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
                "active": 1,
            })
            dtl_id = dtl_result.lastrowid

            gst_data = item.get("gst")
            if gst_data and isinstance(gst_data, dict) and dtl_id:
                db.execute(gst_query, {
                    "sales_delivery_order_dtl_id": dtl_id,
                    "igst_amount": to_float(gst_data.get("igst_amount"), "igst_amount"),
                    "igst_percent": to_float(gst_data.get("igst_percent"), "igst_percent"),
                    "cgst_amount": to_float(gst_data.get("cgst_amount"), "cgst_amount"),
                    "cgst_percent": to_float(gst_data.get("cgst_percent"), "cgst_percent"),
                    "sgst_amount": to_float(gst_data.get("sgst_amount"), "sgst_amount"),
                    "sgst_percent": to_float(gst_data.get("sgst_percent"), "sgst_percent"),
                    "gst_total": to_float(gst_data.get("gst_total"), "gst_total"),
                })

        db.commit()
        return {"message": "Delivery order created successfully", "sales_delivery_order_id": delivery_order_id}
    except HTTPException as exc:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error creating delivery order")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/update_delivery_order")
def update_delivery_order_endpoint(
    payload: dict,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Update a delivery order with detail rows and GST."""
    try:
        sales_delivery_order_id = to_int(payload.get("id"), "id", required=True)
        branch_id = to_int(payload.get("branch"), "branch", required=True)
        party_id = to_int(payload.get("party"), "party", required=True)

        date_str = payload.get("date")
        if not date_str:
            raise HTTPException(status_code=400, detail="date is required")
        try:
            delivery_order_date = datetime.strptime(str(date_str), "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format, expected YYYY-MM-DD")

        raw_items = payload.get("items")
        if not isinstance(raw_items, list) or len(raw_items) == 0:
            raise HTTPException(status_code=400, detail="At least one item row is required")

        # Verify exists
        check_query = text("SELECT sales_delivery_order_id, delivery_order_no, active, status_id FROM sales_delivery_order WHERE sales_delivery_order_id = :id AND active = 1")
        check_result = db.execute(check_query, {"id": sales_delivery_order_id}).fetchone()
        if not check_result:
            raise HTTPException(status_code=404, detail="Delivery order not found or inactive")
        existing = dict(check_result._mapping)

        updated_by = to_int(token_data.get("user_id"), "updated_by")
        updated_at = now_ist()

        sales_order_id = to_int(payload.get("sales_order"), "sales_order")
        invoice_type = to_int(payload.get("invoice_type"), "invoice_type")
        billing_to_id = to_int(payload.get("billing_to"), "billing_to")
        shipping_to_id = to_int(payload.get("shipping_to"), "shipping_to")
        transporter_id = to_int(payload.get("transporter"), "transporter")
        gross_amount = round_amount(to_float(payload.get("gross_amount"), "gross_amount"))
        net_amount = round_amount(to_float(payload.get("net_amount"), "net_amount"))
        freight_charges = round_amount(to_float(payload.get("freight_charges"), "freight_charges"))
        round_off_value = round_amount(to_float(payload.get("round_off_value"), "round_off_value"))

        expected_delivery_str = payload.get("expected_delivery_date")
        expected_delivery_date = None
        if expected_delivery_str:
            try:
                expected_delivery_date = datetime.strptime(str(expected_delivery_str), "%Y-%m-%d").date()
            except ValueError:
                pass

        # Pre-fetch rate_rounding for every line so per-item rate precision is applied.
        do_rate_rounding_map = fetch_item_rate_roundings(
            db,
            [to_int(it.get("item"), f"items[{i}].item", required=True)
             for i, it in enumerate(raw_items, start=1)],
        )

        # Normalize items
        normalized_items = []
        for idx, item in enumerate(raw_items, start=1):
            item_id = to_int(item.get("item"), f"items[{idx}].item", required=True)
            quantity = to_positive_float(item.get("quantity"), f"items[{idx}].quantity")
            uom_id = to_int(item.get("uom"), f"items[{idx}].uom", required=True)
            rate_decimals = do_rate_rounding_map.get(item_id)
            gst_in = item.get("gst") or {}
            gst_out = None
            if isinstance(gst_in, dict) and gst_in:
                gst_out = {
                    **gst_in,
                    "igst_amount": round_amount(gst_in.get("igst_amount")),
                    "cgst_amount": round_amount(gst_in.get("cgst_amount")),
                    "sgst_amount": round_amount(gst_in.get("sgst_amount")),
                    "gst_total": round_amount(gst_in.get("gst_total")),
                }
            normalized_items.append({
                "item_id": item_id,
                "item_make_id": to_int(item.get("item_make"), f"items[{idx}].item_make"),
                "sales_order_dtl_id": to_int(item.get("sales_order_dtl_id"), f"items[{idx}].sales_order_dtl_id"),
                "hsn_code": item.get("hsn_code"),
                "quantity": quantity,
                "uom_id": uom_id,
                "rate": round_rate(to_float(item.get("rate"), f"items[{idx}].rate"), rate_decimals),
                "discount_type": to_int(item.get("discount_type"), f"items[{idx}].discount_type"),
                "discounted_rate": round_rate(to_float(item.get("discounted_rate"), f"items[{idx}].discounted_rate"), rate_decimals),
                "discount_amount": round_amount(to_float(item.get("discount_amount"), f"items[{idx}].discount_amount")),
                "net_amount": round_amount(to_float(item.get("net_amount"), f"items[{idx}].net_amount")),
                "total_amount": round_amount(to_float(item.get("total_amount"), f"items[{idx}].total_amount")),
                "remarks": str(item.get("remarks", "")).strip()[:255] if item.get("remarks") else None,
                "gst": gst_out,
            })

        # Update header
        update_header = update_sales_delivery_order()
        db.execute(update_header, {
            "sales_delivery_order_id": sales_delivery_order_id,
            "updated_by": updated_by,
            "updated_date_time": updated_at,
            "delivery_order_date": delivery_order_date,
            "branch_id": branch_id,
            "invoice_type": invoice_type,
            "sales_order_id": sales_order_id,
            "party_id": party_id,
            "billing_to_id": billing_to_id,
            "shipping_to_id": shipping_to_id,
            "transporter_id": transporter_id,
            "vehicle_no": payload.get("vehicle_no"),
            "driver_name": payload.get("driver_name"),
            "driver_contact": payload.get("driver_contact"),
            "expected_delivery_date": expected_delivery_date,
            "footer_note": payload.get("footer_note"),
            "internal_note": payload.get("internal_note"),
            "gross_amount": gross_amount,
            "net_amount": net_amount,
            "freight_charges": freight_charges,
            "round_off_value": round_off_value,
            "delivery_order_no": existing.get("delivery_order_no"),
            "active": existing.get("active"),
            "status_id": existing.get("status_id"),
        })

        # Delete old GST then soft-delete old details
        delete_gst_q = delete_sales_delivery_order_dtl_gst()
        db.execute(delete_gst_q, {"sales_delivery_order_id": sales_delivery_order_id})

        delete_dtl_q = delete_sales_delivery_order_dtl()
        db.execute(delete_dtl_q, {
            "sales_delivery_order_id": sales_delivery_order_id,
            "updated_by": updated_by,
            "updated_date_time": updated_at,
        })

        # Re-insert details and GST
        dtl_query = insert_sales_delivery_order_dtl()
        gst_query = insert_sales_delivery_order_dtl_gst()
        for item in normalized_items:
            dtl_result = db.execute(dtl_query, {
                "updated_by": updated_by,
                "updated_date_time": updated_at,
                "sales_delivery_order_id": sales_delivery_order_id,
                "sales_order_dtl_id": item["sales_order_dtl_id"],
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
                "active": 1,
            })
            dtl_id = dtl_result.lastrowid

            gst_data = item.get("gst")
            if gst_data and isinstance(gst_data, dict) and dtl_id:
                db.execute(gst_query, {
                    "sales_delivery_order_dtl_id": dtl_id,
                    "igst_amount": to_float(gst_data.get("igst_amount"), "igst_amount"),
                    "igst_percent": to_float(gst_data.get("igst_percent"), "igst_percent"),
                    "cgst_amount": to_float(gst_data.get("cgst_amount"), "cgst_amount"),
                    "cgst_percent": to_float(gst_data.get("cgst_percent"), "cgst_percent"),
                    "sgst_amount": to_float(gst_data.get("sgst_amount"), "sgst_amount"),
                    "sgst_percent": to_float(gst_data.get("sgst_percent"), "sgst_percent"),
                    "gst_total": to_float(gst_data.get("gst_total"), "gst_total"),
                })

        db.commit()
        return {"message": "Delivery order updated successfully", "sales_delivery_order_id": sales_delivery_order_id}
    except HTTPException as exc:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error updating delivery order")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# WORKFLOW ENDPOINTS
# =============================================================================

@router.post("/open_delivery_order")
def open_delivery_order(
    payload: dict,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Open a delivery order (21 -> 1). Generates document number."""
    try:
        sales_delivery_order_id = to_int(payload.get("sales_delivery_order_id"), "sales_delivery_order_id", required=True)
        branch_id = to_int(payload.get("branch_id"), "branch_id", required=True)
        user_id = int(token_data.get("user_id"))

        doc_query = get_delivery_order_with_approval_info()
        doc_result = db.execute(doc_query, {"sales_delivery_order_id": sales_delivery_order_id}).fetchone()
        if not doc_result:
            raise HTTPException(status_code=404, detail="Delivery order not found")
        doc = dict(doc_result._mapping)

        if doc.get("status_id") != 21:
            raise HTTPException(status_code=400, detail=f"Cannot open delivery order with status_id {doc.get('status_id')}. Expected 21 (Draft).")

        order_date = doc.get("delivery_order_date")
        if not order_date:
            raise HTTPException(status_code=400, detail="Delivery order date is required to generate document number.")

        current_no = doc.get("delivery_order_no")
        new_no = None
        if current_no is None or current_no == "" or current_no == "0":
            fy_start, fy_end = get_fy_boundaries(order_date)
            max_query = get_max_delivery_order_no_for_branch_fy()
            max_result = db.execute(max_query, {"branch_id": branch_id, "fy_start_date": fy_start, "fy_end_date": fy_end}).fetchone()
            max_no = dict(max_result._mapping).get("max_doc_no") or 0 if max_result else 0
            new_no = str(max_no + 1)

        updated_at = now_ist()
        update_q = update_delivery_order_status()
        db.execute(update_q, {
            "sales_delivery_order_id": sales_delivery_order_id,
            "status_id": 1,
            "approval_level": None,
            "updated_by": user_id,
            "updated_date_time": updated_at,
            "delivery_order_no": new_no,
        })
        db.commit()

        return {
            "status": "success",
            "new_status_id": 1,
            "message": "Delivery order opened successfully.",
            "delivery_order_no": new_no if new_no else current_no,
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error opening delivery order")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cancel_draft_delivery_order")
def cancel_draft_delivery_order(
    payload: dict,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Cancel a draft delivery order (21 -> 6)."""
    try:
        sales_delivery_order_id = to_int(payload.get("sales_delivery_order_id"), "sales_delivery_order_id", required=True)
        user_id = int(token_data.get("user_id"))

        doc_query = get_delivery_order_with_approval_info()
        doc_result = db.execute(doc_query, {"sales_delivery_order_id": sales_delivery_order_id}).fetchone()
        if not doc_result:
            raise HTTPException(status_code=404, detail="Delivery order not found")
        if dict(doc_result._mapping).get("status_id") != 21:
            raise HTTPException(status_code=400, detail="Cannot cancel. Expected status 21 (Draft).")

        updated_at = now_ist()
        update_q = update_delivery_order_status()
        db.execute(update_q, {
            "sales_delivery_order_id": sales_delivery_order_id, "status_id": 6, "approval_level": None,
            "updated_by": user_id, "updated_date_time": updated_at, "delivery_order_no": None,
        })
        db.commit()
        return {"status": "success", "new_status_id": 6, "message": "Draft cancelled successfully."}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/send_delivery_order_for_approval")
def send_delivery_order_for_approval(
    payload: dict,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Send delivery order for approval (1 -> 20, level=1)."""
    try:
        sales_delivery_order_id = to_int(payload.get("sales_delivery_order_id"), "sales_delivery_order_id", required=True)
        user_id = int(token_data.get("user_id"))

        doc_query = get_delivery_order_with_approval_info()
        doc_result = db.execute(doc_query, {"sales_delivery_order_id": sales_delivery_order_id}).fetchone()
        if not doc_result:
            raise HTTPException(status_code=404, detail="Delivery order not found")
        if dict(doc_result._mapping).get("status_id") != 1:
            raise HTTPException(status_code=400, detail="Cannot send for approval. Expected status 1 (Open).")

        updated_at = now_ist()
        update_q = update_delivery_order_status()
        db.execute(update_q, {
            "sales_delivery_order_id": sales_delivery_order_id, "status_id": 20, "approval_level": 1,
            "updated_by": user_id, "updated_date_time": updated_at, "delivery_order_no": None,
        })
        db.commit()
        return {"status": "success", "new_status_id": 20, "new_approval_level": 1, "message": "Delivery order sent for approval."}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/approve_delivery_order")
def approve_delivery_order(
    payload: dict,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Approve a delivery order (with value check)."""
    try:
        sales_delivery_order_id = to_int(payload.get("sales_delivery_order_id"), "sales_delivery_order_id", required=True)
        menu_id = to_int(payload.get("menu_id"), "menu_id", required=True)
        user_id = int(token_data.get("user_id"))

        doc_query = get_delivery_order_with_approval_info()
        doc_result = db.execute(doc_query, {"sales_delivery_order_id": sales_delivery_order_id}).fetchone()
        if not doc_result:
            raise HTTPException(status_code=404, detail="Delivery order not found")
        document_amount = float(dict(doc_result._mapping).get("net_amount", 0) or 0)

        result = process_approval(
            doc_id=sales_delivery_order_id,
            user_id=user_id,
            menu_id=menu_id,
            db=db,
            get_doc_fn=get_delivery_order_with_approval_info,
            update_status_fn=update_delivery_order_status,
            id_param_name="sales_delivery_order_id",
            doc_name="Delivery order",
            document_amount=document_amount,
            extra_update_params={"delivery_order_no": None},
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reject_delivery_order")
def reject_delivery_order(
    payload: dict,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Reject a delivery order (20 -> 4)."""
    try:
        sales_delivery_order_id = to_int(payload.get("sales_delivery_order_id"), "sales_delivery_order_id", required=True)
        menu_id = to_int(payload.get("menu_id"), "menu_id")
        user_id = int(token_data.get("user_id"))
        reason = payload.get("reason")

        result = process_rejection(
            doc_id=sales_delivery_order_id,
            user_id=user_id,
            menu_id=menu_id,
            db=db,
            get_doc_fn=get_delivery_order_with_approval_info,
            update_status_fn=update_delivery_order_status,
            id_param_name="sales_delivery_order_id",
            doc_name="Delivery order",
            reason=reason,
            extra_update_params={"delivery_order_no": None},
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reopen_delivery_order")
def reopen_delivery_order(
    payload: dict,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Reopen a cancelled (6 -> 21) or rejected (4 -> 1) delivery order."""
    try:
        sales_delivery_order_id = to_int(payload.get("sales_delivery_order_id"), "sales_delivery_order_id", required=True)
        user_id = int(token_data.get("user_id"))

        doc_query = get_delivery_order_with_approval_info()
        doc_result = db.execute(doc_query, {"sales_delivery_order_id": sales_delivery_order_id}).fetchone()
        if not doc_result:
            raise HTTPException(status_code=404, detail="Delivery order not found")
        current_status = dict(doc_result._mapping).get("status_id")

        if current_status == 6:
            new_status_id = 21
        elif current_status == 4:
            new_status_id = 1
        else:
            raise HTTPException(status_code=400, detail=f"Cannot reopen with status_id {current_status}. Only 6 or 4.")

        updated_at = now_ist()
        update_q = update_delivery_order_status()
        db.execute(update_q, {
            "sales_delivery_order_id": sales_delivery_order_id, "status_id": new_status_id, "approval_level": None,
            "updated_by": user_id, "updated_date_time": updated_at, "delivery_order_no": None,
        })
        db.commit()
        return {"status": "success", "new_status_id": new_status_id, "message": f"Delivery order reopened (status: {new_status_id})."}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
