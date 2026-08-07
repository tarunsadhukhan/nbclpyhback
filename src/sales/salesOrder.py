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
from src.sales.query import (
    get_item_by_group_id_saleable,
    get_item_uom_by_group_id_saleable,
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
from src.sales.enquiry_hooks import advance_enquiry_on_sales_order_approved
from src.sales.enquiry_query import get_enquiry_flow_state_query
from src.sales.query import (
    get_customers_for_sales,
    get_customer_branches_bulk,
    get_brokers_for_sales,
    get_transporters_for_sales,
    get_approved_quotations_query,
    get_quotation_lines_for_order,
    get_enquiries_for_sales_doc_query,
    get_enquiry_lines_for_sales_doc_query,
    insert_sales_order,
    insert_sales_order_dtl,
    insert_sales_order_dtl_gst,
    insert_sales_order_dtl_hessian,
    delete_sales_order_dtl_hessian,
    get_sales_order_hessian_by_id_query,
    update_sales_order,
    delete_sales_order_dtl,
    delete_sales_order_dtl_gst,
    get_sales_order_table_query,
    get_sales_order_table_count_query,
    get_sales_order_by_id_query,
    get_sales_order_dtl_by_id_query,
    get_sales_order_gst_by_id_query,
    update_sales_order_status,
    get_sales_order_with_approval_info,
    get_max_sales_order_no_for_branch_fy,
)
from src.sales.constants import (
    SALES_DOC_TYPES,
    INVOICE_TYPE_CODES,
    resolve_invoice_type_code,
)
from src.common.companyAdmin.query import get_co_config_by_id_query

logger = logging.getLogger(__name__)

router = APIRouter()


# =============================================================================
# VALIDATION HELPERS
# =============================================================================

# Required header fields when invoice type resolves to Govt Sacking.
_GOVT_SKG_REQUIRED_HEADER_FIELDS = (
    "pcso_no",
    "pcso_date",
)

# Required line-detail fields when invoice type resolves to Govt Sacking.
# pack_sheet / net_weight / total_weight were previously required at the line
# level but have been removed from the UI; the columns still exist in
# sales_order_govtskg_dtl and are written when provided, just no longer
# mandatory.
_GOVT_SKG_REQUIRED_LINE_FIELDS: tuple[str, ...] = ()


def _is_blank(value) -> bool:
    """Treat None and empty/whitespace-only strings as missing."""
    if value is None:
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    return False


def _validate_govt_skg_payload(invoice_type_code: str, payload: dict, raw_items) -> None:
    """Reject Govt Sacking sales order payloads that are missing the
    type-specific header or line fields.

    Raises HTTPException(400) with a clear message naming the missing field(s).
    No-op for non-Govt-SKG invoice types.
    """
    if invoice_type_code != INVOICE_TYPE_CODES["GOVT_SKG"]:
        return

    govtskg_hdr_raw = payload.get("govtskg")
    # Treat None / non-dict / empty dict all as "all fields missing" so the
    # error message always names the specific fields instead of a generic
    # "object required" which leaves the user guessing.
    govtskg_hdr = govtskg_hdr_raw if isinstance(govtskg_hdr_raw, dict) else {}

    missing_hdr = [f for f in _GOVT_SKG_REQUIRED_HEADER_FIELDS if _is_blank(govtskg_hdr.get(f))]
    if missing_hdr:
        raise HTTPException(
            status_code=400,
            detail=(
                "Govt Sacking sales order is missing required header field(s): "
                + ", ".join(f"govtskg.{f}" for f in missing_hdr)
            ),
        )

    if not isinstance(raw_items, list):
        return  # outer validation already rejects this case

    for idx, item in enumerate(raw_items, start=1):
        govtskg_dtl_raw = item.get("govtskg_dtl") if isinstance(item, dict) else None
        govtskg_dtl = govtskg_dtl_raw if isinstance(govtskg_dtl_raw, dict) else {}
        missing_line = [f for f in _GOVT_SKG_REQUIRED_LINE_FIELDS if _is_blank(govtskg_dtl.get(f))]
        if missing_line:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Govt Sacking sales order: items[{idx}] is missing required field(s): "
                    + ", ".join(f"govtskg_dtl.{f}" for f in missing_line)
                ),
            )


# =============================================================================
# SETUP ENDPOINTS
# =============================================================================

def _ensure_enquiry_project(db: Session, sales_enquiry_id: int, user_id: int) -> None:
    """Auto-create a project_mst row for an enquiry at ORDER_CONFIRMED and tag
    the enquiry with it (decision Q5). No-op when the enquiry already has a
    project. Runs inside the caller's transaction; the caller commits."""
    state_row = db.execute(
        get_enquiry_flow_state_query(), {"sales_enquiry_id": int(sales_enquiry_id)}
    ).fetchone()
    if not state_row:
        return
    state = dict(state_row._mapping)
    if state.get("project_id"):
        return

    party_name = None
    if state.get("party_id"):
        party_row = db.execute(
            text("SELECT supp_name FROM party_mst WHERE party_id = :party_id"),
            {"party_id": int(state["party_id"])},
        ).fetchone()
        if party_row:
            party_name = dict(party_row._mapping).get("supp_name")

    enquiry_no = state.get("enquiry_no") or f"ID {sales_enquiry_id}"
    prj_name = f"ENQ {enquiry_no}" + (f" - {party_name}" if party_name else "")
    now = now_ist()
    proj_result = db.execute(
        text("""INSERT INTO project_mst
            (prj_name, prj_desc, prj_start_dt, status_id, active, branch_id, party_id, updated_by, updated_date_time)
            VALUES (:prj_name, :prj_desc, :prj_start_dt, :status_id, 1, :branch_id, :party_id, :updated_by, :updated_date_time)"""),
        {
            "prj_name": prj_name[:255],
            "prj_desc": "Auto-created on sales order approval (enquiry flow)",
            "prj_start_dt": now.date(),
            "status_id": 1,
            "branch_id": state.get("branch_id"),
            "party_id": state.get("party_id"),
            "updated_by": int(user_id),
            "updated_date_time": now,
        },
    )
    project_id = proj_result.lastrowid
    if project_id:
        db.execute(
            text("""UPDATE sales_enquiry SET project_id = :project_id,
                updated_by = :updated_by, updated_date_time = :updated_date_time
                WHERE sales_enquiry_id = :sales_enquiry_id"""),
            {
                "project_id": int(project_id),
                "updated_by": int(user_id),
                "updated_date_time": now,
                "sales_enquiry_id": int(sales_enquiry_id),
            },
        )


@router.get("/get_sales_order_setup_1")
def get_sales_order_setup_1(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    branch_id: int | None = None,
    co_id: int | None = None,
):
    """Return branches, customers, brokers, transporters, approved quotations, item groups, and co_config."""
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

        # Co config (check quotation_required)
        co_config_query = get_co_config_by_id_query(co_id)
        co_config_result = db.execute(co_config_query, {"co_id": co_id}).fetchone()
        co_config = dict(co_config_result._mapping) if co_config_result else {}

        quotation_required_value = co_config.get("quotation_required") if co_config else None
        if isinstance(quotation_required_value, str):
            quotation_required = quotation_required_value.strip().lower() not in {"0", "false", "no", ""}
        else:
            quotation_required = bool(quotation_required_value)

        # Approved quotations for dropdown
        approved_quotations = []
        if quotation_required:
            aq_query = get_approved_quotations_query()
            aq_result = db.execute(aq_query, {"branch_id": branch_id, "co_id": co_id}).fetchall()
            for row in aq_result:
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
                approved_quotations.append({
                    "sales_quotation_id": mapped.get("sales_quotation_id"),
                    "quotation_no": formatted_no,
                    "quotation_date": format_date(mapped.get("quotation_date")),
                    "party_name": mapped.get("party_name"),
                    "net_amount": mapped.get("net_amount"),
                })

        # Item groups (only if quotation is NOT required)
        item_groups = []
        if not quotation_required:
            itemgrp_query = get_item_group_drodown(co_id=co_id)
            itemgrp_result = db.execute(itemgrp_query, {"co_id": co_id}).fetchall()
            item_groups = [dict(r._mapping) for r in itemgrp_result]

        # Invoice types mapped to this company
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

        # Mukam list (for jute invoice types)
        mukam_query = text("SELECT mukam_id, mukam_name FROM jute_mukam_mst ORDER BY mukam_name")
        mukam_result = db.execute(mukam_query).fetchall()
        mukam_list = [dict(r._mapping) for r in mukam_result]

        # Additional charges master
        from src.sales.query import get_additional_charges_dropdown
        charges_result = db.execute(get_additional_charges_dropdown()).fetchall()
        additional_charges_master = [dict(r._mapping) for r in charges_result]

        # Transport charge rates for Govt Sacking (scoped to this company)
        from src.sales.query import get_govtskg_transport_charge_rates
        transport_rates_result = db.execute(get_govtskg_transport_charge_rates(), {"co_id": co_id}).fetchall()
        transport_charge_rates = [dict(r._mapping) for r in transport_rates_result]

        # Open enquiries eligible for a direct sales order (tender path — Q3)
        enquiries_result = db.execute(
            get_enquiries_for_sales_doc_query(),
            {"branch_id": branch_id, "co_id": co_id},
        ).fetchall()
        enquiries = [dict(r._mapping) for r in enquiries_result]

        return {
            "branches": branches,
            "customers": customers,
            "brokers": brokers,
            "transporters": transporters,
            "co_config": co_config,
            "approved_quotations": approved_quotations,
            "item_groups": item_groups,
            "invoice_types": invoice_types,
            "mukam_list": mukam_list,
            "additional_charges_master": additional_charges_master,
            "transport_charge_rates": transport_charge_rates,
            "enquiries": enquiries,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching sales order setup 1")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_sales_order_setup_2")
def get_sales_order_setup_2(
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


@router.get("/get_quotation_lines")
def get_quotation_lines(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Get quotation line items to pre-fill a new sales order."""
    try:
        q_id = request.query_params.get("sales_quotation_id")
        if q_id is None:
            raise HTTPException(status_code=400, detail="sales_quotation_id is required")

        sales_quotation_id = int(q_id)
        query = get_quotation_lines_for_order()
        result = db.execute(query, {"sales_quotation_id": sales_quotation_id}).fetchall()
        data = [dict(r._mapping) for r in result]
        return {"data": data}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_enquiry_lines_for_sales_order")
def get_enquiry_lines_for_sales_order(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Enquiry lines (with confirmed cost basis) to pre-fill a direct sales
    order — the tender / customer-PO path with no quotation (decision Q3)."""
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
        logger.exception("Error fetching enquiry lines for sales order")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# CRUD ENDPOINTS
# =============================================================================

@router.get("/get_sales_order_table")
def get_sales_order_table(
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
    """Return paginated sales order list."""
    try:
        page = max(page, 1)
        limit = max(min(limit, 100), 1)
        offset = (page - 1) * limit
        search_like = f"%{search.strip()}%" if search else None

        params = {"co_id": co_id, "branch_id": branch_id, "status_id": status_id, "search_like": search_like, "limit": limit, "offset": offset}

        list_query = get_sales_order_table_query()
        rows = db.execute(list_query, params).fetchall()
        data = []
        for row in rows:
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

            data.append({
                "sales_order_id": mapped.get("sales_order_id"),
                "sales_no": formatted_no,
                "sales_order_date": format_date(mapped.get("sales_order_date")),
                "branch_id": mapped.get("branch_id"),
                "branch_name": mapped.get("branch_name"),
                "party_name": mapped.get("party_name"),
                "quotation_no": mapped.get("quotation_no"),
                "net_amount": mapped.get("net_amount"),
                "status": mapped.get("status_name"),
                "status_id": mapped.get("status_id"),
            })

        count_query = get_sales_order_table_count_query()
        count_result = db.execute(count_query, {"co_id": co_id, "branch_id": branch_id, "status_id": status_id, "search_like": search_like}).scalar()
        total = int(count_result) if count_result is not None else 0

        return {"data": data, "total": total}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_sales_order_by_id")
def get_sales_order_by_id(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Return sales order details by ID with line items and GST."""
    try:
        q_id = request.query_params.get("sales_order_id")
        q_co_id = request.query_params.get("co_id")
        if q_id is None:
            raise HTTPException(status_code=400, detail="sales_order_id is required")
        if q_co_id is None:
            raise HTTPException(status_code=400, detail="co_id is required")

        try:
            sales_order_id = int(q_id)
            co_id = int(q_co_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid sales_order_id or co_id")

        # Header
        header_query = get_sales_order_by_id_query()
        header_result = db.execute(header_query, {"sales_order_id": sales_order_id, "co_id": co_id}).fetchone()
        if not header_result:
            raise HTTPException(status_code=404, detail="Sales order not found or access denied")
        header = dict(header_result._mapping)

        # Details
        detail_query = get_sales_order_dtl_by_id_query()
        detail_results = db.execute(detail_query, {"sales_order_id": sales_order_id}).fetchall()
        details = [dict(r._mapping) for r in detail_results]

        # GST
        gst_query = get_sales_order_gst_by_id_query()
        gst_results = db.execute(gst_query, {"sales_order_id": sales_order_id}).fetchall()
        gst_map: dict[int, dict] = {}
        for g in gst_results:
            gd = dict(g._mapping)
            gst_map[gd.get("sales_order_dtl_id")] = gd

        # Resolve invoice type by NAME (id values are not stable across deployments)
        header_invoice_type_code = resolve_invoice_type_code(header.get("invoice_type"))

        # Hessian extension data
        hessian_map: dict[int, dict] = {}
        if header_invoice_type_code == INVOICE_TYPE_CODES["HESSIAN"]:
            hessian_query = get_sales_order_hessian_by_id_query()
            hessian_results = db.execute(hessian_query, {"sales_order_id": sales_order_id}).fetchall()
            for h in hessian_results:
                hd = dict(h._mapping)
                hessian_map[hd.get("sales_order_dtl_id")] = hd

        # Raw Jute extension
        jute_hdr = None
        jute_dtl_map: dict[int, dict] = {}
        if header_invoice_type_code == INVOICE_TYPE_CODES["RAW_JUTE"]:
            from src.sales.query import get_sales_order_jute_by_id, get_sales_order_jute_dtl_by_order_id
            jute_result = db.execute(get_sales_order_jute_by_id(), {"sales_order_id": sales_order_id}).fetchone()
            if jute_result:
                jute_hdr = dict(jute_result._mapping)
            jute_dtl_results = db.execute(get_sales_order_jute_dtl_by_order_id(), {"sales_order_id": sales_order_id}).fetchall()
            for jd in jute_dtl_results:
                jdd = dict(jd._mapping)
                jute_dtl_map[jdd.get("sales_order_dtl_id")] = jdd

        # Jute Yarn extension
        juteyarn_hdr = None
        if header_invoice_type_code == INVOICE_TYPE_CODES["JUTE_YARN"]:
            from src.sales.query import get_sales_order_juteyarn_by_id
            juteyarn_result = db.execute(get_sales_order_juteyarn_by_id(), {"sales_order_id": sales_order_id}).fetchone()
            if juteyarn_result:
                juteyarn_hdr = dict(juteyarn_result._mapping)

        # Govt SKG extension
        govtskg_hdr = None
        govtskg_dtl_map: dict[int, dict] = {}
        if header_invoice_type_code == INVOICE_TYPE_CODES["GOVT_SKG"]:
            from src.sales.query import get_sales_order_govtskg_by_id, get_sales_order_govtskg_dtl_by_order_id
            govtskg_result = db.execute(get_sales_order_govtskg_by_id(), {"sales_order_id": sales_order_id}).fetchone()
            if govtskg_result:
                govtskg_hdr = dict(govtskg_result._mapping)
            govtskg_dtl_results = db.execute(get_sales_order_govtskg_dtl_by_order_id(), {"sales_order_id": sales_order_id}).fetchall()
            for gd in govtskg_dtl_results:
                gdd = dict(gd._mapping)
                govtskg_dtl_map[gdd.get("sales_order_dtl_id")] = gdd

        # Additional charges
        from src.sales.query import get_sales_order_additional_by_id
        additional_results = db.execute(get_sales_order_additional_by_id(), {"sales_order_id": sales_order_id}).fetchall()
        additional_charges = [dict(r._mapping) for r in additional_results]

        # Format sales_no
        raw_no = header.get("sales_no")
        formatted_no = ""
        if raw_no is not None:
            try:
                formatted_no = format_indent_no(
                    indent_no=int(raw_no) if raw_no else None,
                    co_prefix=header.get("co_prefix"),
                    branch_prefix=header.get("branch_prefix"),
                    indent_date=header.get("sales_order_date"),
                    document_type=SALES_DOC_TYPES["SALES_ORDER"],
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
            "id": str(header.get("sales_order_id", "")),
            "salesNo": formatted_no,
            "salesOrderDate": format_date(header.get("sales_order_date")),
            "salesOrderExpiryDate": format_date(header.get("sales_order_expiry_date")),
            "invoiceType": header.get("invoice_type"),
            "branch": str(header.get("branch_id", "")) if header.get("branch_id") else "",
            "quotation": str(header.get("quotation_id", "")) if header.get("quotation_id") else None,
            "quotationNo": header.get("quotation_no"),
            "party": str(header.get("party_id", "")) if header.get("party_id") else "",
            "partyName": header.get("party_name"),
            "broker": str(header.get("broker_id", "")) if header.get("broker_id") else None,
            "brokerName": header.get("broker_name"),
            "billingTo": str(header.get("billing_to_id", "")) if header.get("billing_to_id") else None,
            "shippingTo": str(header.get("shipping_to_id", "")) if header.get("shipping_to_id") else None,
            "transporter": str(header.get("transporter_id", "")) if header.get("transporter_id") else None,
            "transporterName": header.get("transporter_name"),
            "brokerCommissionPercent": header.get("broker_commission_percent"),
            "footerNote": header.get("footer_note"),
            "termsConditions": header.get("terms_conditions"),
            "internalNote": header.get("internal_note"),
            "deliveryTerms": header.get("delivery_terms"),
            "paymentTerms": header.get("payment_terms"),
            "deliveryDays": header.get("delivery_days"),
            "freightCharges": header.get("freight_charges"),
            "grossAmount": header.get("gross_amount"),
            "netAmount": header.get("net_amount"),
            "buyerOrderNo": header.get("buyer_order_no"),
            "buyerOrderDate": format_date(header.get("buyer_order_date")),
            "committedDeliveryDate": format_date(header.get("committed_delivery_date")),
            "advanceAmount": header.get("advance_amount"),
            "advanceNote": header.get("advance_note"),
            "salesEnquiryId": str(header.get("sales_enquiry_id", "")) if header.get("sales_enquiry_id") else None,
            "enquiryNo": header.get("enquiry_no"),
            "status": header.get("status_name"),
            "statusId": status_id,
            "approvalLevel": approval_level,
            "updatedBy": str(header.get("updated_by", "")) if header.get("updated_by") else None,
            "updatedAt": format_date(header.get("updated_date_time")),
            "jute": jute_hdr,
            "juteyarn": juteyarn_hdr,
            "govtskg": govtskg_hdr,
            "additionalCharges": additional_charges,
            "lines": [],
        }

        if permissions is not None:
            response["permissions"] = permissions

        for detail in details:
            dtl_id = detail.get("sales_order_dtl_id")
            gst = gst_map.get(dtl_id, {})
            hessian = hessian_map.get(dtl_id, {})
            line = {
                "id": str(dtl_id) if dtl_id else "",
                "quotationLineitemId": detail.get("quotation_lineitem_id"),
                "hsnCode": detail.get("hsn_code"),
                "itemGroup": str(detail.get("item_grp_id", "")) if detail.get("item_grp_id") else "",
                "item": str(detail.get("item_id", "")) if detail.get("item_id") else "",
                "itemName": detail.get("item_name"),
                "fullItemCode": detail.get("full_item_code") or detail.get("item_code") or "",
                "itemMake": str(detail.get("item_make_id", "")) if detail.get("item_make_id") else None,
                "quantity": float(detail.get("quantity", 0)) if detail.get("quantity") is not None else 0,
                "qtyUom": str(detail.get("uom_id", "")) if detail.get("uom_id") else "",
                "qtyUomName": detail.get("uom_name"),
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
                "hessian": {
                    "qtyBales": hessian.get("qty_bales"),
                    "ratePerBale": hessian.get("rate_per_bale"),
                    "billingRateMt": hessian.get("billing_rate_mt"),
                    "billingRateBale": hessian.get("billing_rate_bale"),
                } if hessian else None,
            }
            # Jute detail
            jute_d = jute_dtl_map.get(dtl_id, {})
            if jute_d:
                line["juteDtl"] = {
                    "claimAmountDtl": jute_d.get("claim_amount_dtl"),
                    "claimDesc": jute_d.get("claim_desc"),
                    "claimRate": jute_d.get("claim_rate"),
                    "unitConversion": jute_d.get("unit_conversion"),
                    "qtyUnitConversion": jute_d.get("qty_untit_conversion"),
                }
            # Govt SKG detail
            govtskg_d = govtskg_dtl_map.get(dtl_id, {})
            if govtskg_d:
                line["govtskgDtl"] = {
                    "packSheet": govtskg_d.get("pack_sheet"),
                    "netWeight": govtskg_d.get("net_weight"),
                    "totalWeight": govtskg_d.get("total_weight"),
                }
            response["lines"].append(line)

        return response
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching sales order by ID")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/create_sales_order")
def create_sales_order(
    payload: dict,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Create a sales order with detail rows and GST."""
    try:
        branch_id = to_int(payload.get("branch"), "branch", required=True)
        party_id = to_int(payload.get("party"), "party")
        broker_id = to_int(payload.get("broker"), "broker")

        if not party_id and not broker_id:
            raise HTTPException(status_code=400, detail="Either party (customer) or broker is required")

        date_str = payload.get("date")
        if not date_str:
            raise HTTPException(status_code=400, detail="date is required")
        try:
            sales_order_date = datetime.strptime(str(date_str), "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format, expected YYYY-MM-DD")

        raw_items = payload.get("items")
        if not isinstance(raw_items, list) or len(raw_items) == 0:
            raise HTTPException(status_code=400, detail="At least one item row is required")

        updated_by = to_int(token_data.get("user_id"), "updated_by")
        created_at = now_ist()

        quotation_id = to_int(payload.get("quotation"), "quotation")
        billing_to_id = to_int(payload.get("billing_to"), "billing_to")
        shipping_to_id = to_int(payload.get("shipping_to"), "shipping_to")
        transporter_id = to_int(payload.get("transporter"), "transporter")
        invoice_type = to_int(payload.get("invoice_type"), "invoice_type")
        # Resolve canonical code from the seeded invoice_type_mst ids
        # (1=Regular, 2=Hessian, 3=Govt Sacking, 4=Yarn, 5=Raw Jute, 7=Govt Sacking Freight).
        invoice_type_code = resolve_invoice_type_code(invoice_type)
        broker_commission_percent = to_float(payload.get("broker_commission_percent"), "broker_commission_percent")
        freight_charges = round_amount(to_float(payload.get("freight_charges"), "freight_charges"))
        gross_amount = round_amount(to_float(payload.get("gross_amount"), "gross_amount"))
        net_amount = round_amount(to_float(payload.get("net_amount"), "net_amount"))
        delivery_days = to_int(payload.get("delivery_days"), "delivery_days")
        advance_amount = round_amount(to_float(payload.get("advance_amount"), "advance_amount"))
        advance_note = str(payload.get("advance_note", "")).strip()[:255] if payload.get("advance_note") else None
        sales_enquiry_id = to_int(payload.get("sales_enquiry_id"), "sales_enquiry_id")

        committed_delivery_date = None
        committed_str = payload.get("committed_delivery_date")
        if committed_str:
            try:
                committed_delivery_date = datetime.strptime(str(committed_str), "%Y-%m-%d").date()
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid committed_delivery_date format, expected YYYY-MM-DD")

        expiry_str = payload.get("expiry_date")
        sales_order_expiry_date = None
        if expiry_str:
            try:
                sales_order_expiry_date = datetime.strptime(str(expiry_str), "%Y-%m-%d").date()
            except ValueError:
                pass

        buyer_order_no_val = payload.get("buyer_order_no")
        buyer_order_date_val = None
        raw_buyer_date = payload.get("buyer_order_date")
        if raw_buyer_date:
            try:
                buyer_order_date_val = datetime.strptime(str(raw_buyer_date), "%Y-%m-%d").date()
            except ValueError:
                pass

        # Govt SKG payload validation — reject early to prevent silent data loss
        _validate_govt_skg_payload(invoice_type_code, payload, raw_items)

        # Look up rate_rounding decimals for all line items in one query so each
        # line can round its rate / discounted_rate consistently with item_mst.
        item_id_list = [to_int(it.get("item"), f"items[{i}].item", required=True)
                        for i, it in enumerate(raw_items, start=1)]
        rate_rounding_map = fetch_item_rate_roundings(db, item_id_list)

        # Normalize items
        normalized_items = []
        for idx, item in enumerate(raw_items, start=1):
            item_id = to_int(item.get("item"), f"items[{idx}].item", required=True)
            quantity = to_positive_float(item.get("quantity"), f"items[{idx}].quantity")
            uom_id = to_int(item.get("qty_uom"), f"items[{idx}].qty_uom", required=True)
            rate_decimals = rate_rounding_map.get(item_id)
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
                "quotation_lineitem_id": to_int(item.get("quotation_lineitem_id"), f"items[{idx}].quotation_lineitem_id"),
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
                # Per-line rate decimals from item_mst — used to round hessian
                # billing rates (post-brokerage) on insert.
                "rate_decimals": rate_decimals,
                # Type-specific extension payloads (resolved by code, not id)
                "hessian": item.get("hessian"),
                "jute_dtl": item.get("jute_dtl"),
                "govtskg_dtl": item.get("govtskg_dtl"),
            })

        # Insert header
        insert_header = insert_sales_order()
        header_params = {
            "updated_by": updated_by,
            "updated_date_time": created_at,
            "sales_order_date": sales_order_date,
            "sales_no": None,
            "invoice_type": invoice_type,
            "branch_id": branch_id,
            "quotation_id": quotation_id,
            "party_id": party_id,
            "broker_id": broker_id,
            "billing_to_id": billing_to_id,
            "shipping_to_id": shipping_to_id,
            "transporter_id": transporter_id,
            "sales_order_expiry_date": sales_order_expiry_date,
            "broker_commission_percent": broker_commission_percent,
            "footer_note": payload.get("footer_note"),
            "terms_conditions": payload.get("terms_conditions"),
            "internal_note": payload.get("internal_note"),
            "delivery_terms": payload.get("delivery_terms"),
            "payment_terms": payload.get("payment_terms"),
            "delivery_days": delivery_days,
            "freight_charges": freight_charges,
            "gross_amount": gross_amount,
            "net_amount": net_amount,
            "committed_delivery_date": committed_delivery_date,
            "advance_amount": advance_amount,
            "advance_note": advance_note,
            "sales_enquiry_id": sales_enquiry_id,
            "status_id": 21,
            "approval_level": 0,
            "active": 1,
            "buyer_order_no": buyer_order_no_val,
            "buyer_order_date": buyer_order_date_val,
        }

        result = db.execute(insert_header, header_params)
        sales_order_id = result.lastrowid
        if not sales_order_id:
            raise HTTPException(status_code=500, detail="Failed to create sales order header")

        # Insert details and GST
        dtl_query = insert_sales_order_dtl()
        gst_query = insert_sales_order_dtl_gst()
        hessian_query = insert_sales_order_dtl_hessian() if invoice_type_code == INVOICE_TYPE_CODES["HESSIAN"] else None

        # Raw Jute
        jute_hdr_data = payload.get("jute") or {}
        jute_dtl_query = None
        if invoice_type_code == INVOICE_TYPE_CODES["RAW_JUTE"]:
            from src.sales.query import insert_sales_order_jute_dtl
            jute_dtl_query = insert_sales_order_jute_dtl()

        # Govt SKG
        govtskg_hdr_data = payload.get("govtskg") or {}
        govtskg_dtl_query = None
        if invoice_type_code == INVOICE_TYPE_CODES["GOVT_SKG"]:
            from src.sales.query import insert_sales_order_govtskg_dtl
            govtskg_dtl_query = insert_sales_order_govtskg_dtl()

        # Jute Yarn — header only, no detail extension
        juteyarn_hdr_data = payload.get("juteyarn") or {}

        for item in normalized_items:
            dtl_result = db.execute(dtl_query, {
                "updated_by": updated_by,
                "updated_date_time": created_at,
                "sales_order_id": sales_order_id,
                "quotation_lineitem_id": item["quotation_lineitem_id"],
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
                    "sales_order_dtl_id": dtl_id,
                    "igst_amount": to_float(gst_data.get("igst_amount"), "igst_amount"),
                    "igst_percent": to_float(gst_data.get("igst_percent"), "igst_percent"),
                    "cgst_amount": to_float(gst_data.get("cgst_amount"), "cgst_amount"),
                    "cgst_percent": to_float(gst_data.get("cgst_percent"), "cgst_percent"),
                    "sgst_amount": to_float(gst_data.get("sgst_amount"), "sgst_amount"),
                    "sgst_percent": to_float(gst_data.get("sgst_percent"), "sgst_percent"),
                    "gst_total": to_float(gst_data.get("gst_total"), "gst_total"),
                })

            # Insert hessian extension row for invoice_type=2
            hessian_data = item.get("hessian")
            if hessian_query is not None and hessian_data and isinstance(hessian_data, dict) and dtl_id:
                line_rate_decimals = item.get("rate_decimals")
                db.execute(hessian_query, {
                    "sales_order_dtl_id": dtl_id,
                    "qty_bales": to_float(hessian_data.get("qty_bales"), "qty_bales"),
                    "rate_per_bale": round_amount(to_float(hessian_data.get("rate_per_bale"), "rate_per_bale")),
                    "billing_rate_mt": round_rate(to_float(hessian_data.get("billing_rate_mt"), "billing_rate_mt"), line_rate_decimals),
                    "billing_rate_bale": round_rate(to_float(hessian_data.get("billing_rate_bale"), "billing_rate_bale"), line_rate_decimals),
                    "updated_by": updated_by,
                    "updated_date_time": created_at,
                })

            # Jute detail
            jute_dtl_data = item.get("jute_dtl")
            if jute_dtl_query is not None and jute_dtl_data and isinstance(jute_dtl_data, dict) and dtl_id:
                db.execute(jute_dtl_query, {
                    "sales_order_dtl_id": dtl_id,
                    "claim_amount_dtl": to_float(jute_dtl_data.get("claim_amount_dtl"), "claim_amount_dtl"),
                    "claim_desc": jute_dtl_data.get("claim_desc"),
                    "claim_rate": to_float(jute_dtl_data.get("claim_rate"), "claim_rate"),
                    "unit_conversion": jute_dtl_data.get("unit_conversion"),
                    "qty_untit_conversion": to_int(jute_dtl_data.get("qty_untit_conversion"), "qty_untit_conversion"),
                    "updated_by": updated_by,
                    "updated_date_time": created_at,
                })

            # Govt SKG detail
            govtskg_dtl_data = item.get("govtskg_dtl")
            if govtskg_dtl_query is not None and govtskg_dtl_data and isinstance(govtskg_dtl_data, dict) and dtl_id:
                db.execute(govtskg_dtl_query, {
                    "sales_order_dtl_id": dtl_id,
                    "pack_sheet": to_float(govtskg_dtl_data.get("pack_sheet"), "pack_sheet"),
                    "net_weight": to_float(govtskg_dtl_data.get("net_weight"), "net_weight"),
                    "total_weight": to_float(govtskg_dtl_data.get("total_weight"), "total_weight"),
                    "updated_by": updated_by,
                    "updated_date_time": created_at,
                })

        # Insert header-level type extensions
        if jute_hdr_data and invoice_type_code == INVOICE_TYPE_CODES["RAW_JUTE"]:
            from src.sales.query import insert_sales_order_jute
            db.execute(insert_sales_order_jute(), {
                "sales_order_id": sales_order_id,
                "mr_no": jute_hdr_data.get("mr_no"),
                "mr_id": to_int(jute_hdr_data.get("mr_id"), "mr_id"),
                "claim_amount": to_float(jute_hdr_data.get("claim_amount"), "claim_amount"),
                "other_reference": jute_hdr_data.get("other_reference"),
                "unit_conversion": jute_hdr_data.get("unit_conversion"),
                "claim_description": jute_hdr_data.get("claim_description"),
                "mukam_id": to_int(jute_hdr_data.get("mukam_id"), "mukam_id"),
                "updated_by": updated_by,
                "updated_date_time": created_at,
            })

        if juteyarn_hdr_data and invoice_type_code == INVOICE_TYPE_CODES["JUTE_YARN"]:
            from src.sales.query import insert_sales_order_juteyarn
            db.execute(insert_sales_order_juteyarn(), {
                "sales_order_id": sales_order_id,
                "pcso_no": juteyarn_hdr_data.get("pcso_no"),
                "container_no": juteyarn_hdr_data.get("container_no"),
                "customer_ref_no": juteyarn_hdr_data.get("customer_ref_no"),
                "updated_by": updated_by,
                "updated_date_time": created_at,
            })

        if govtskg_hdr_data and invoice_type_code == INVOICE_TYPE_CODES["GOVT_SKG"]:
            from src.sales.query import insert_sales_order_govtskg
            db.execute(insert_sales_order_govtskg(), {
                "sales_order_id": sales_order_id,
                "pcso_no": govtskg_hdr_data.get("pcso_no"),
                "pcso_date": govtskg_hdr_data.get("pcso_date"),
                "administrative_office_address": govtskg_hdr_data.get("administrative_office_address"),
                "destination_rail_head": govtskg_hdr_data.get("destination_rail_head"),
                "loading_point": govtskg_hdr_data.get("loading_point"),
                "mode_of_transport": govtskg_hdr_data.get("mode_of_transport"),
                "updated_by": updated_by,
                "updated_date_time": created_at,
            })

        # Insert additional charges
        additional_charges_list = payload.get("additional_charges") or []
        if additional_charges_list:
            from src.sales.query import insert_sales_order_additional, insert_sales_order_additional_gst
            add_query = insert_sales_order_additional()
            add_gst_query = insert_sales_order_additional_gst()
            for charge in additional_charges_list:
                charge_result = db.execute(add_query, {
                    "sales_order_id": sales_order_id,
                    "additional_charges_id": to_int(charge.get("additional_charges_id"), "additional_charges_id"),
                    "qty": round_amount(to_float(charge.get("qty"), "qty")),
                    "rate": round_amount(to_float(charge.get("rate"), "rate")),
                    "net_amount": round_amount(to_float(charge.get("net_amount"), "net_amount")),
                    "remarks": charge.get("remarks"),
                    "updated_by": updated_by,
                    "updated_date_time": created_at,
                })
                charge_id = charge_result.lastrowid
                gst_data = charge.get("gst")
                if gst_data and isinstance(gst_data, dict) and charge_id:
                    db.execute(add_gst_query, {
                        "sales_order_additional_id": charge_id,
                        "igst_amount": round_amount(to_float(gst_data.get("igst_amount"), "igst_amount")),
                        "igst_percent": to_float(gst_data.get("igst_percent"), "igst_percent"),
                        "cgst_amount": round_amount(to_float(gst_data.get("cgst_amount"), "cgst_amount")),
                        "cgst_percent": to_float(gst_data.get("cgst_percent"), "cgst_percent"),
                        "sgst_amount": round_amount(to_float(gst_data.get("sgst_amount"), "sgst_amount")),
                        "sgst_percent": to_float(gst_data.get("sgst_percent"), "sgst_percent"),
                        "gst_total": round_amount(to_float(gst_data.get("gst_total"), "gst_total")),
                    })

        db.commit()
        return {"message": "Sales order created successfully", "sales_order_id": sales_order_id}
    except HTTPException as exc:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error creating sales order")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/update_sales_order")
def update_sales_order_endpoint(
    payload: dict,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Update a sales order with detail rows and GST."""
    try:
        sales_order_id = to_int(payload.get("id"), "id", required=True)
        branch_id = to_int(payload.get("branch"), "branch", required=True)
        party_id = to_int(payload.get("party"), "party")
        broker_id = to_int(payload.get("broker"), "broker")

        if not party_id and not broker_id:
            raise HTTPException(status_code=400, detail="Either party (customer) or broker is required")

        date_str = payload.get("date")
        if not date_str:
            raise HTTPException(status_code=400, detail="date is required")
        try:
            sales_order_date = datetime.strptime(str(date_str), "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format, expected YYYY-MM-DD")

        raw_items = payload.get("items")
        if not isinstance(raw_items, list) or len(raw_items) == 0:
            raise HTTPException(status_code=400, detail="At least one item row is required")

        # Verify exists
        check_query = text("SELECT sales_order_id, sales_no, active, status_id FROM sales_order WHERE sales_order_id = :id AND active = 1")
        check_result = db.execute(check_query, {"id": sales_order_id}).fetchone()
        if not check_result:
            raise HTTPException(status_code=404, detail="Sales order not found or inactive")
        existing = dict(check_result._mapping)

        updated_by = to_int(token_data.get("user_id"), "updated_by")
        updated_at = now_ist()

        quotation_id = to_int(payload.get("quotation"), "quotation")
        billing_to_id = to_int(payload.get("billing_to"), "billing_to")
        shipping_to_id = to_int(payload.get("shipping_to"), "shipping_to")
        transporter_id = to_int(payload.get("transporter"), "transporter")
        invoice_type = to_int(payload.get("invoice_type"), "invoice_type")
        invoice_type_code = resolve_invoice_type_code(invoice_type)
        broker_commission_percent = to_float(payload.get("broker_commission_percent"), "broker_commission_percent")
        freight_charges = round_amount(to_float(payload.get("freight_charges"), "freight_charges"))
        gross_amount = round_amount(to_float(payload.get("gross_amount"), "gross_amount"))
        net_amount = round_amount(to_float(payload.get("net_amount"), "net_amount"))
        delivery_days = to_int(payload.get("delivery_days"), "delivery_days")
        advance_amount = round_amount(to_float(payload.get("advance_amount"), "advance_amount"))
        advance_note = str(payload.get("advance_note", "")).strip()[:255] if payload.get("advance_note") else None
        sales_enquiry_id = to_int(payload.get("sales_enquiry_id"), "sales_enquiry_id")

        committed_delivery_date = None
        committed_str = payload.get("committed_delivery_date")
        if committed_str:
            try:
                committed_delivery_date = datetime.strptime(str(committed_str), "%Y-%m-%d").date()
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid committed_delivery_date format, expected YYYY-MM-DD")

        expiry_str = payload.get("expiry_date")
        sales_order_expiry_date = None
        if expiry_str:
            try:
                sales_order_expiry_date = datetime.strptime(str(expiry_str), "%Y-%m-%d").date()
            except ValueError:
                pass

        buyer_order_no_val = payload.get("buyer_order_no")
        buyer_order_date_val = None
        raw_buyer_date = payload.get("buyer_order_date")
        if raw_buyer_date:
            try:
                buyer_order_date_val = datetime.strptime(str(raw_buyer_date), "%Y-%m-%d").date()
            except ValueError:
                pass

        # Govt SKG payload validation — reject early to prevent silent data loss
        _validate_govt_skg_payload(invoice_type_code, payload, raw_items)

        # Look up rate_rounding decimals for all line items in one query so each
        # line can round its rate / discounted_rate consistently with item_mst.
        item_id_list = [to_int(it.get("item"), f"items[{i}].item", required=True)
                        for i, it in enumerate(raw_items, start=1)]
        rate_rounding_map = fetch_item_rate_roundings(db, item_id_list)

        # Normalize items
        normalized_items = []
        for idx, item in enumerate(raw_items, start=1):
            item_id = to_int(item.get("item"), f"items[{idx}].item", required=True)
            quantity = to_positive_float(item.get("quantity"), f"items[{idx}].quantity")
            uom_id = to_int(item.get("qty_uom"), f"items[{idx}].qty_uom", required=True)
            rate_decimals = rate_rounding_map.get(item_id)
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
                "quotation_lineitem_id": to_int(item.get("quotation_lineitem_id"), f"items[{idx}].quotation_lineitem_id"),
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
                # Per-line rate decimals from item_mst — used to round hessian
                # billing rates (post-brokerage) on insert.
                "rate_decimals": rate_decimals,
                # Type-specific extension payloads (resolved by code, not id)
                "hessian": item.get("hessian"),
                "jute_dtl": item.get("jute_dtl"),
                "govtskg_dtl": item.get("govtskg_dtl"),
            })

        # Update header
        update_header = update_sales_order()
        db.execute(update_header, {
            "sales_order_id": sales_order_id,
            "updated_by": updated_by,
            "updated_date_time": updated_at,
            "sales_order_date": sales_order_date,
            "invoice_type": invoice_type,
            "branch_id": branch_id,
            "quotation_id": quotation_id,
            "party_id": party_id,
            "broker_id": broker_id,
            "billing_to_id": billing_to_id,
            "shipping_to_id": shipping_to_id,
            "transporter_id": transporter_id,
            "sales_order_expiry_date": sales_order_expiry_date,
            "broker_commission_percent": broker_commission_percent,
            "footer_note": payload.get("footer_note"),
            "terms_conditions": payload.get("terms_conditions"),
            "internal_note": payload.get("internal_note"),
            "delivery_terms": payload.get("delivery_terms"),
            "payment_terms": payload.get("payment_terms"),
            "delivery_days": delivery_days,
            "freight_charges": freight_charges,
            "gross_amount": gross_amount,
            "net_amount": net_amount,
            "committed_delivery_date": committed_delivery_date,
            "advance_amount": advance_amount,
            "advance_note": advance_note,
            "sales_enquiry_id": sales_enquiry_id,
            "sales_no": existing.get("sales_no"),
            "active": existing.get("active"),
            "status_id": existing.get("status_id"),
            "buyer_order_no": buyer_order_no_val,
            "buyer_order_date": buyer_order_date_val,
        })

        # Delete old hessian, GST, then soft-delete old details
        delete_hessian_q = delete_sales_order_dtl_hessian()
        db.execute(delete_hessian_q, {"sales_order_id": sales_order_id})

        # Delete old type-specific extension data (by canonical code)
        if invoice_type_code == INVOICE_TYPE_CODES["RAW_JUTE"]:
            from src.sales.query import delete_sales_order_jute, delete_sales_order_jute_dtl
            db.execute(delete_sales_order_jute_dtl(), {"sales_order_id": sales_order_id})
            db.execute(delete_sales_order_jute(), {"sales_order_id": sales_order_id})
        elif invoice_type_code == INVOICE_TYPE_CODES["JUTE_YARN"]:
            from src.sales.query import delete_sales_order_juteyarn
            db.execute(delete_sales_order_juteyarn(), {"sales_order_id": sales_order_id})
        elif invoice_type_code == INVOICE_TYPE_CODES["GOVT_SKG"]:
            from src.sales.query import delete_sales_order_govtskg, delete_sales_order_govtskg_dtl
            db.execute(delete_sales_order_govtskg_dtl(), {"sales_order_id": sales_order_id})
            db.execute(delete_sales_order_govtskg(), {"sales_order_id": sales_order_id})

        # Delete old additional charges
        from src.sales.query import delete_sales_order_additional_gst, delete_sales_order_additional
        db.execute(delete_sales_order_additional_gst(), {"sales_order_id": sales_order_id})
        db.execute(delete_sales_order_additional(), {"sales_order_id": sales_order_id})

        delete_gst_q = delete_sales_order_dtl_gst()
        db.execute(delete_gst_q, {"sales_order_id": sales_order_id})

        delete_dtl_q = delete_sales_order_dtl()
        db.execute(delete_dtl_q, {
            "sales_order_id": sales_order_id,
            "updated_by": updated_by,
            "updated_date_time": updated_at,
        })

        # Re-insert details, GST, and type extensions
        dtl_query = insert_sales_order_dtl()
        gst_query = insert_sales_order_dtl_gst()
        hessian_query = insert_sales_order_dtl_hessian() if invoice_type_code == INVOICE_TYPE_CODES["HESSIAN"] else None

        # Raw Jute
        jute_hdr_data = payload.get("jute") or {}
        jute_dtl_query = None
        if invoice_type_code == INVOICE_TYPE_CODES["RAW_JUTE"]:
            from src.sales.query import insert_sales_order_jute_dtl
            jute_dtl_query = insert_sales_order_jute_dtl()

        # Govt SKG
        govtskg_hdr_data = payload.get("govtskg") or {}
        govtskg_dtl_query = None
        if invoice_type_code == INVOICE_TYPE_CODES["GOVT_SKG"]:
            from src.sales.query import insert_sales_order_govtskg_dtl
            govtskg_dtl_query = insert_sales_order_govtskg_dtl()

        # Jute Yarn — header only, no detail extension
        juteyarn_hdr_data = payload.get("juteyarn") or {}

        for item in normalized_items:
            dtl_result = db.execute(dtl_query, {
                "updated_by": updated_by,
                "updated_date_time": updated_at,
                "sales_order_id": sales_order_id,
                "quotation_lineitem_id": item["quotation_lineitem_id"],
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
                    "sales_order_dtl_id": dtl_id,
                    "igst_amount": to_float(gst_data.get("igst_amount"), "igst_amount"),
                    "igst_percent": to_float(gst_data.get("igst_percent"), "igst_percent"),
                    "cgst_amount": to_float(gst_data.get("cgst_amount"), "cgst_amount"),
                    "cgst_percent": to_float(gst_data.get("cgst_percent"), "cgst_percent"),
                    "sgst_amount": to_float(gst_data.get("sgst_amount"), "sgst_amount"),
                    "sgst_percent": to_float(gst_data.get("sgst_percent"), "sgst_percent"),
                    "gst_total": to_float(gst_data.get("gst_total"), "gst_total"),
                })

            # Insert hessian extension row for invoice_type=2
            hessian_data = item.get("hessian")
            if hessian_query is not None and hessian_data and isinstance(hessian_data, dict) and dtl_id:
                line_rate_decimals = item.get("rate_decimals")
                db.execute(hessian_query, {
                    "sales_order_dtl_id": dtl_id,
                    "qty_bales": to_float(hessian_data.get("qty_bales"), "qty_bales"),
                    "rate_per_bale": round_amount(to_float(hessian_data.get("rate_per_bale"), "rate_per_bale")),
                    "billing_rate_mt": round_rate(to_float(hessian_data.get("billing_rate_mt"), "billing_rate_mt"), line_rate_decimals),
                    "billing_rate_bale": round_rate(to_float(hessian_data.get("billing_rate_bale"), "billing_rate_bale"), line_rate_decimals),
                    "updated_by": updated_by,
                    "updated_date_time": updated_at,
                })

            # Jute detail
            jute_dtl_data = item.get("jute_dtl")
            if jute_dtl_query is not None and jute_dtl_data and isinstance(jute_dtl_data, dict) and dtl_id:
                db.execute(jute_dtl_query, {
                    "sales_order_dtl_id": dtl_id,
                    "claim_amount_dtl": to_float(jute_dtl_data.get("claim_amount_dtl"), "claim_amount_dtl"),
                    "claim_desc": jute_dtl_data.get("claim_desc"),
                    "claim_rate": to_float(jute_dtl_data.get("claim_rate"), "claim_rate"),
                    "unit_conversion": jute_dtl_data.get("unit_conversion"),
                    "qty_untit_conversion": to_int(jute_dtl_data.get("qty_untit_conversion"), "qty_untit_conversion"),
                    "updated_by": updated_by,
                    "updated_date_time": updated_at,
                })

            # Govt SKG detail
            govtskg_dtl_data = item.get("govtskg_dtl")
            if govtskg_dtl_query is not None and govtskg_dtl_data and isinstance(govtskg_dtl_data, dict) and dtl_id:
                db.execute(govtskg_dtl_query, {
                    "sales_order_dtl_id": dtl_id,
                    "pack_sheet": to_float(govtskg_dtl_data.get("pack_sheet"), "pack_sheet"),
                    "net_weight": to_float(govtskg_dtl_data.get("net_weight"), "net_weight"),
                    "total_weight": to_float(govtskg_dtl_data.get("total_weight"), "total_weight"),
                    "updated_by": updated_by,
                    "updated_date_time": updated_at,
                })

        # Insert header-level type extensions
        if jute_hdr_data and invoice_type_code == INVOICE_TYPE_CODES["RAW_JUTE"]:
            from src.sales.query import insert_sales_order_jute
            db.execute(insert_sales_order_jute(), {
                "sales_order_id": sales_order_id,
                "mr_no": jute_hdr_data.get("mr_no"),
                "mr_id": to_int(jute_hdr_data.get("mr_id"), "mr_id"),
                "claim_amount": to_float(jute_hdr_data.get("claim_amount"), "claim_amount"),
                "other_reference": jute_hdr_data.get("other_reference"),
                "unit_conversion": jute_hdr_data.get("unit_conversion"),
                "claim_description": jute_hdr_data.get("claim_description"),
                "mukam_id": to_int(jute_hdr_data.get("mukam_id"), "mukam_id"),
                "updated_by": updated_by,
                "updated_date_time": updated_at,
            })

        if juteyarn_hdr_data and invoice_type_code == INVOICE_TYPE_CODES["JUTE_YARN"]:
            from src.sales.query import insert_sales_order_juteyarn
            db.execute(insert_sales_order_juteyarn(), {
                "sales_order_id": sales_order_id,
                "pcso_no": juteyarn_hdr_data.get("pcso_no"),
                "container_no": juteyarn_hdr_data.get("container_no"),
                "customer_ref_no": juteyarn_hdr_data.get("customer_ref_no"),
                "updated_by": updated_by,
                "updated_date_time": updated_at,
            })

        if govtskg_hdr_data and invoice_type_code == INVOICE_TYPE_CODES["GOVT_SKG"]:
            from src.sales.query import insert_sales_order_govtskg
            db.execute(insert_sales_order_govtskg(), {
                "sales_order_id": sales_order_id,
                "pcso_no": govtskg_hdr_data.get("pcso_no"),
                "pcso_date": govtskg_hdr_data.get("pcso_date"),
                "administrative_office_address": govtskg_hdr_data.get("administrative_office_address"),
                "destination_rail_head": govtskg_hdr_data.get("destination_rail_head"),
                "loading_point": govtskg_hdr_data.get("loading_point"),
                "mode_of_transport": govtskg_hdr_data.get("mode_of_transport"),
                "updated_by": updated_by,
                "updated_date_time": updated_at,
            })

        # Insert additional charges
        additional_charges_list = payload.get("additional_charges") or []
        if additional_charges_list:
            from src.sales.query import insert_sales_order_additional, insert_sales_order_additional_gst
            add_query = insert_sales_order_additional()
            add_gst_query = insert_sales_order_additional_gst()
            for charge in additional_charges_list:
                charge_result = db.execute(add_query, {
                    "sales_order_id": sales_order_id,
                    "additional_charges_id": to_int(charge.get("additional_charges_id"), "additional_charges_id"),
                    "qty": to_float(charge.get("qty"), "qty"),
                    "rate": to_float(charge.get("rate"), "rate"),
                    "net_amount": to_float(charge.get("net_amount"), "net_amount"),
                    "remarks": charge.get("remarks"),
                    "updated_by": updated_by,
                    "updated_date_time": updated_at,
                })
                charge_id = charge_result.lastrowid
                gst_data = charge.get("gst")
                if gst_data and isinstance(gst_data, dict) and charge_id:
                    db.execute(add_gst_query, {
                        "sales_order_additional_id": charge_id,
                        "igst_amount": to_float(gst_data.get("igst_amount"), "igst_amount"),
                        "igst_percent": to_float(gst_data.get("igst_percent"), "igst_percent"),
                        "cgst_amount": to_float(gst_data.get("cgst_amount"), "cgst_amount"),
                        "cgst_percent": to_float(gst_data.get("cgst_percent"), "cgst_percent"),
                        "sgst_amount": to_float(gst_data.get("sgst_amount"), "sgst_amount"),
                        "sgst_percent": to_float(gst_data.get("sgst_percent"), "sgst_percent"),
                        "gst_total": to_float(gst_data.get("gst_total"), "gst_total"),
                    })

        db.commit()
        return {"message": "Sales order updated successfully", "sales_order_id": sales_order_id}
    except HTTPException as exc:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error updating sales order")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# WORKFLOW ENDPOINTS
# =============================================================================

@router.post("/open_sales_order")
def open_sales_order(
    payload: dict,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Open a sales order (21 -> 1). Generates document number."""
    try:
        sales_order_id = to_int(payload.get("sales_order_id"), "sales_order_id", required=True)
        branch_id = to_int(payload.get("branch_id"), "branch_id", required=True)
        user_id = int(token_data.get("user_id"))

        doc_query = get_sales_order_with_approval_info()
        doc_result = db.execute(doc_query, {"sales_order_id": sales_order_id}).fetchone()
        if not doc_result:
            raise HTTPException(status_code=404, detail="Sales order not found")
        doc = dict(doc_result._mapping)

        if doc.get("status_id") != 21:
            raise HTTPException(status_code=400, detail=f"Cannot open sales order with status_id {doc.get('status_id')}. Expected 21 (Draft).")

        order_date = doc.get("sales_order_date")
        if not order_date:
            raise HTTPException(status_code=400, detail="Sales order date is required to generate document number.")

        current_no = doc.get("sales_no")
        new_no = None
        if current_no is None or current_no == "" or current_no == "0":
            fy_start, fy_end = get_fy_boundaries(order_date)
            max_query = get_max_sales_order_no_for_branch_fy()
            max_result = db.execute(max_query, {"branch_id": branch_id, "fy_start_date": fy_start, "fy_end_date": fy_end}).fetchone()
            max_no = dict(max_result._mapping).get("max_doc_no") or 0 if max_result else 0
            new_no = str(max_no + 1)

        updated_at = now_ist()
        update_q = update_sales_order_status()
        db.execute(update_q, {
            "sales_order_id": sales_order_id,
            "status_id": 1,
            "approval_level": None,
            "updated_by": user_id,
            "updated_date_time": updated_at,
            "sales_no": new_no,
        })
        db.commit()

        return {
            "status": "success",
            "new_status_id": 1,
            "message": "Sales order opened successfully.",
            "sales_no": new_no if new_no else current_no,
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error opening sales order")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cancel_draft_sales_order")
def cancel_draft_sales_order(
    payload: dict,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Cancel a draft sales order (21 -> 6)."""
    try:
        sales_order_id = to_int(payload.get("sales_order_id"), "sales_order_id", required=True)
        user_id = int(token_data.get("user_id"))

        doc_query = get_sales_order_with_approval_info()
        doc_result = db.execute(doc_query, {"sales_order_id": sales_order_id}).fetchone()
        if not doc_result:
            raise HTTPException(status_code=404, detail="Sales order not found")
        if dict(doc_result._mapping).get("status_id") != 21:
            raise HTTPException(status_code=400, detail="Cannot cancel. Expected status 21 (Draft).")

        updated_at = now_ist()
        update_q = update_sales_order_status()
        db.execute(update_q, {
            "sales_order_id": sales_order_id, "status_id": 6, "approval_level": None,
            "updated_by": user_id, "updated_date_time": updated_at, "sales_no": None,
        })
        db.commit()
        return {"status": "success", "new_status_id": 6, "message": "Draft cancelled successfully."}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/send_sales_order_for_approval")
def send_sales_order_for_approval(
    payload: dict,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Send sales order for approval (1 -> 20, level=1)."""
    try:
        sales_order_id = to_int(payload.get("sales_order_id"), "sales_order_id", required=True)
        user_id = int(token_data.get("user_id"))

        doc_query = get_sales_order_with_approval_info()
        doc_result = db.execute(doc_query, {"sales_order_id": sales_order_id}).fetchone()
        if not doc_result:
            raise HTTPException(status_code=404, detail="Sales order not found")
        if dict(doc_result._mapping).get("status_id") != 1:
            raise HTTPException(status_code=400, detail="Cannot send for approval. Expected status 1 (Open).")

        updated_at = now_ist()
        update_q = update_sales_order_status()
        db.execute(update_q, {
            "sales_order_id": sales_order_id, "status_id": 20, "approval_level": 1,
            "updated_by": user_id, "updated_date_time": updated_at, "sales_no": None,
        })
        db.commit()
        return {"status": "success", "new_status_id": 20, "new_approval_level": 1, "message": "Sales order sent for approval."}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/approve_sales_order")
def approve_sales_order(
    payload: dict,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Approve a sales order (with value check)."""
    try:
        sales_order_id = to_int(payload.get("sales_order_id"), "sales_order_id", required=True)
        menu_id = to_int(payload.get("menu_id"), "menu_id", required=True)
        user_id = int(token_data.get("user_id"))

        doc_query = get_sales_order_with_approval_info()
        doc_result = db.execute(doc_query, {"sales_order_id": sales_order_id}).fetchone()
        if not doc_result:
            raise HTTPException(status_code=404, detail="Sales order not found")
        document_amount = float(dict(doc_result._mapping).get("net_amount", 0) or 0)

        result = process_approval(
            doc_id=sales_order_id,
            user_id=user_id,
            menu_id=menu_id,
            db=db,
            get_doc_fn=get_sales_order_with_approval_info,
            update_status_fn=update_sales_order_status,
            id_param_name="sales_order_id",
            doc_name="Sales order",
            document_amount=document_amount,
            extra_update_params={"sales_no": None},
            commit=False,
        )
        # Final approval: advance the linked enquiry to ORDER_CONFIRMED and
        # auto-create its project (decisions Q4/Q5) — same transaction.
        if result.get("new_status_id") == 3:
            enquiry_id = advance_enquiry_on_sales_order_approved(db, sales_order_id, user_id)
            if enquiry_id:
                _ensure_enquiry_project(db, enquiry_id, user_id)
        db.commit()
        return result
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reject_sales_order")
def reject_sales_order(
    payload: dict,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Reject a sales order (20 -> 4)."""
    try:
        sales_order_id = to_int(payload.get("sales_order_id"), "sales_order_id", required=True)
        menu_id = to_int(payload.get("menu_id"), "menu_id")
        user_id = int(token_data.get("user_id"))
        reason = payload.get("reason")

        result = process_rejection(
            doc_id=sales_order_id,
            user_id=user_id,
            menu_id=menu_id,
            db=db,
            get_doc_fn=get_sales_order_with_approval_info,
            update_status_fn=update_sales_order_status,
            id_param_name="sales_order_id",
            doc_name="Sales order",
            reason=reason,
            extra_update_params={"sales_no": None},
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reopen_sales_order")
def reopen_sales_order(
    payload: dict,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Reopen a cancelled (6 -> 21) or rejected (4 -> 1) sales order."""
    try:
        sales_order_id = to_int(payload.get("sales_order_id"), "sales_order_id", required=True)
        user_id = int(token_data.get("user_id"))

        doc_query = get_sales_order_with_approval_info()
        doc_result = db.execute(doc_query, {"sales_order_id": sales_order_id}).fetchone()
        if not doc_result:
            raise HTTPException(status_code=404, detail="Sales order not found")
        current_status = dict(doc_result._mapping).get("status_id")

        if current_status == 6:
            new_status_id = 21
        elif current_status == 4:
            new_status_id = 1
        else:
            raise HTTPException(status_code=400, detail=f"Cannot reopen with status_id {current_status}. Only 6 or 4.")

        updated_at = now_ist()
        update_q = update_sales_order_status()
        db.execute(update_q, {
            "sales_order_id": sales_order_id, "status_id": new_status_id, "approval_level": None,
            "updated_by": user_id, "updated_date_time": updated_at, "sales_no": None,
        })
        db.commit()
        return {"status": "success", "new_status_id": new_status_id, "message": f"Sales order reopened (status: {new_status_id})."}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
