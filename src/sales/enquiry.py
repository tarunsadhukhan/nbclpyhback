"""
Sales Enquiry router — the front door of the AMCL enquiry-to-delivery flow
(docs/amcl-enquiry-flow-design.md §6, Phase 1).

Portal persona: Depends(get_tenant_db) + get_current_user_with_refresh.
Registered in src/main.py under prefix /api/salesEnquiry (by a later change —
this module only defines the router).

Covers:
- Enquiry list / Flow Board / setup / by-id (with approval permissions block)
- Draft CRUD (create/update, 21 only) + open (mint ENQ number, stage ENQ_NOTED)
- Standard approval workflow (send/approve/reject/reopen via approval_utils;
  the enquiry is an amount-less document — see approve_enquiry)
- Stage engine endpoints: move_stage / close_enquiry (validate_transition +
  log_stage_transition from src/sales/enquiry_hooks.py, one transaction each)
- Costing confirm (bom_cost_snapshot status='approved' + line cost evidence)
- Price check (request with last-PO prefill, worklist, respond + return leg)

All handlers are plain `def` (CLAUDE.md "Sync Handler Policy"); JSON bodies are
read via parse_json_body(request).

NOTE: the enquiry-specific write statements (INSERT/UPDATE for sales_enquiry,
sales_enquiry_dtl, enquiry_price_check*) live in this file because
src/sales/enquiry_query.py only ships the read queries + the two stage-engine
write statements; a later cleanup may move them there.
"""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import bindparam
from sqlalchemy.orm import Session
from sqlalchemy.sql import text

from src.authorization.utils import get_current_user_with_refresh
from src.common.approval_utils import (
    calculate_approval_permissions,
    process_approval,
    process_rejection,
)
from src.common.utils import now_ist, parse_json_body
from src.config.db import get_tenant_db
from src.masters.query import get_uom_list
from src.procurement.indent import format_indent_no
from src.sales.constants import SALES_DOC_TYPES
from src.sales.enquiry_constants import (
    ACTION_AUTO,
    ACTION_CLOSE,
    ACTION_CREATE,
    ACTION_FORWARD,
    ACTION_HOLD,
    ACTION_MARK_LOST,
    ACTION_RESUME,
    ACTION_SEND_BACK,
    CLOSE_REASONS,
    ENQUIRY_FLOW_DOC_TYPE,
    ENQUIRY_MENU_PATH,
    ENQUIRY_STATUS_IDS,
    FLOW_MODULE_ENQUIRY,
    LINKED_DOC_PRICE_CHECK,
    PC_STATUS_PENDING,
    PC_STATUS_RESPONDED,
    PRICE_CHECK_STATUSES,
    RATE_SOURCES,
    RECEIVED_VIA_OPTIONS,
    STAGE_CLOSED,
    STAGE_COSTING_REVIEW,
    STAGE_ENQ_NOTED,
    STAGE_LOST,
    STAGE_ORDER_CONFIRMED,
    STAGE_PRICE_CHECK,
    STAGE_QUOTATION,
    TERMINAL_STAGES,
)
from src.sales.enquiry_hooks import (
    log_stage_transition,
    validate_transition,
)
from src.sales.enquiry_query import (
    get_enquiry_board_counts_query,
    get_enquiry_board_query,
    get_enquiry_by_id_query,
    get_enquiry_costing_pending_query,
    get_enquiry_dtl_by_id_query,
    get_enquiry_flow_state_query,
    get_enquiry_linked_docs_query,
    get_enquiry_stage_log_query,
    get_enquiry_table_count_query,
    get_enquiry_table_query,
    get_iso_doc_no_query,
    get_last_purchase_rates_by_item_ids,
    get_max_enquiry_no_for_branch_fy,
    get_menu_id_by_path_query,
    get_price_check_by_id_query,
    get_price_check_dtl_query,
    get_price_check_list_query,
    get_stages_by_module_query,
)
from src.sales.query import get_customers_for_sales
from src.sales.quotation import (
    format_date,
    get_fy_boundaries,
    to_float,
    to_int,
    to_positive_float,
)

logger = logging.getLogger(__name__)

router = APIRouter()

ENQ_DOC_TYPE = SALES_DOC_TYPES["ENQUIRY"]  # "ENQ" — document-number prefix


def resolve_enquiry_menu_id(db: Session, client_menu_id: int | None = None) -> int | None:
    """Canonical menu_id for enquiry approval checks.

    The approval hierarchy lives on the Customer Enquiry menu
    (menu_mst.menu_path = ENQUIRY_MENU_PATH), but the page is reachable from
    entry points that carry a different menu_id (Enquiry Flow Board, BOM
    costing review) or none at all (direct URL). Always resolve by path so
    every entry point evaluates the same approval config; fall back to the
    client's menu_id only when the canonical row is missing.
    """
    row = db.execute(
        get_menu_id_by_path_query(), {"menu_path": ENQUIRY_MENU_PATH}
    ).fetchone()
    if row:
        return int(dict(row._mapping)["menu_id"])
    return client_menu_id


# =============================================================================
# LOCAL WRITE / LOOKUP STATEMENTS
# (enquiry_query.py ships the reads + stage-engine writes; the CRUD writes for
# the enquiry tables live here — see module docstring.)
# =============================================================================

def insert_sales_enquiry():
    sql = """INSERT INTO sales_enquiry (
        enquiry_no, enquiry_date, received_via, branch_id, party_id,
        contact_person, contact_detail, customer_ref_no, expected_delivery_date,
        enquiry_desc, internal_note, current_stage_id, stage_since, hold_flag,
        status_id, approval_level, close_reason, lost_remarks, project_id,
        active, updated_by, updated_date_time
    ) VALUES (
        NULL, :enquiry_date, :received_via, :branch_id, :party_id,
        :contact_person, :contact_detail, :customer_ref_no, :expected_delivery_date,
        :enquiry_desc, :internal_note, NULL, NULL, 0,
        :status_id, :approval_level, NULL, NULL, :project_id,
        1, :updated_by, :updated_date_time
    );"""
    return text(sql)


def update_sales_enquiry():
    """Draft-only header update (status/stage untouched)."""
    sql = """UPDATE sales_enquiry SET
        enquiry_date = :enquiry_date,
        received_via = :received_via,
        branch_id = :branch_id,
        party_id = :party_id,
        contact_person = :contact_person,
        contact_detail = :contact_detail,
        customer_ref_no = :customer_ref_no,
        expected_delivery_date = :expected_delivery_date,
        enquiry_desc = :enquiry_desc,
        internal_note = :internal_note,
        project_id = :project_id,
        updated_by = :updated_by,
        updated_date_time = :updated_date_time
    WHERE sales_enquiry_id = :sales_enquiry_id;"""
    return text(sql)


def insert_sales_enquiry_dtl():
    sql = """INSERT INTO sales_enquiry_dtl (
        sales_enquiry_id, item_id, item_desc_freetext, is_new_item,
        design_change, qty, uom_id, target_price, remarks, active
    ) VALUES (
        :sales_enquiry_id, :item_id, :item_desc_freetext, :is_new_item,
        :design_change, :qty, :uom_id, :target_price, :remarks, 1
    );"""
    return text(sql)


def deactivate_sales_enquiry_dtl():
    """Soft-delete all active lines of an enquiry (replace-lines pattern)."""
    sql = """UPDATE sales_enquiry_dtl SET active = 0
    WHERE sales_enquiry_id = :sales_enquiry_id AND active = 1;"""
    return text(sql)


def update_enquiry_status():
    """Status/approval-level update; enquiry_no only when explicitly provided
    (mirrors update_quotation_status)."""
    sql = """UPDATE sales_enquiry SET
        status_id = :status_id,
        approval_level = :approval_level,
        updated_by = :updated_by,
        updated_date_time = :updated_date_time,
        enquiry_no = CASE
            WHEN :enquiry_no IS NOT NULL THEN :enquiry_no
            ELSE enquiry_no
        END
    WHERE sales_enquiry_id = :sales_enquiry_id;"""
    return text(sql)


def update_enquiry_close():
    """Terminal close: status 5 + close_reason (+ lost_remarks when lost)."""
    sql = """UPDATE sales_enquiry SET
        status_id = :status_id,
        close_reason = :close_reason,
        lost_remarks = :lost_remarks,
        updated_by = :updated_by,
        updated_date_time = :updated_date_time
    WHERE sales_enquiry_id = :sales_enquiry_id;"""
    return text(sql)


def update_enquiry_hold_flag():
    sql = """UPDATE sales_enquiry SET
        hold_flag = :hold_flag,
        updated_by = :updated_by,
        updated_date_time = :updated_date_time
    WHERE sales_enquiry_id = :sales_enquiry_id;"""
    return text(sql)


def update_enquiry_dtl_costing():
    """Write the confirmed cost basis onto an enquiry line (costing confirm)."""
    sql = """UPDATE sales_enquiry_dtl SET
        bom_hdr_id = :bom_hdr_id,
        cost_snapshot_id = :cost_snapshot_id,
        confirmed_cost_per_unit = :confirmed_cost_per_unit,
        costing_confirmed_by = :costing_confirmed_by,
        costing_confirmed_date = :costing_confirmed_date,
        overhead_pct = :overhead_pct,
        margin_pct = :margin_pct
    WHERE enquiry_dtl_id = :enquiry_dtl_id;"""
    return text(sql)


def get_enquiry_dtl_state_query():
    """One line + its enquiry's stage/status (costing confirm guard)."""
    sql = """SELECT
        sed.enquiry_dtl_id,
        sed.sales_enquiry_id,
        sed.item_id,
        se.status_id,
        se.hold_flag,
        se.active,
        fsm.stage_code
    FROM sales_enquiry_dtl sed
    JOIN sales_enquiry se ON se.sales_enquiry_id = sed.sales_enquiry_id
    LEFT JOIN flow_stage_mst fsm ON fsm.stage_id = se.current_stage_id
    WHERE sed.enquiry_dtl_id = :enquiry_dtl_id
        AND sed.active = 1
        AND se.active = 1;"""
    return text(sql)


def get_enquiry_active_lines_query():
    """Active line ids + items of an enquiry (price-check line validation)."""
    sql = """SELECT sed.enquiry_dtl_id, sed.item_id
    FROM sales_enquiry_dtl sed
    WHERE sed.sales_enquiry_id = :sales_enquiry_id
        AND sed.active = 1
    ORDER BY sed.enquiry_dtl_id;"""
    return text(sql)


def get_bom_hdr_for_confirm_query():
    sql = """SELECT bh.bom_hdr_id, bh.item_id, bh.is_current, bh.co_id
    FROM item_bom_hdr_mst bh
    WHERE bh.bom_hdr_id = :bom_hdr_id
        AND bh.active = 1;"""
    return text(sql)


def get_current_bom_cost_snapshot_query():
    sql = """SELECT bcs.bom_cost_snapshot_id, bcs.cost_per_unit,
        bcs.total_cost, bcs.status
    FROM bom_cost_snapshot bcs
    WHERE bcs.bom_hdr_id = :bom_hdr_id
        AND bcs.is_current = 1
        AND bcs.active = 1
    ORDER BY bcs.bom_cost_snapshot_id DESC
    LIMIT 1;"""
    return text(sql)


def approve_bom_cost_snapshot():
    sql = """UPDATE bom_cost_snapshot SET
        status = 'approved',
        updated_by = :updated_by,
        updated_date_time = :updated_date_time
    WHERE bom_cost_snapshot_id = :bom_cost_snapshot_id;"""
    return text(sql)


def insert_enquiry_price_check():
    sql = """INSERT INTO enquiry_price_check (
        sales_enquiry_id, request_note, pc_status,
        requested_by, requested_date_time,
        active, updated_by, updated_date_time
    ) VALUES (
        :sales_enquiry_id, :request_note, :pc_status,
        :requested_by, :requested_date_time,
        1, :updated_by, :updated_date_time
    );"""
    return text(sql)


def insert_enquiry_price_check_dtl():
    sql = """INSERT INTO enquiry_price_check_dtl (
        price_check_id, enquiry_dtl_id, item_id,
        last_po_rate, last_po_date, last_supplier_id, remarks
    ) VALUES (
        :price_check_id, :enquiry_dtl_id, :item_id,
        :last_po_rate, :last_po_date, :last_supplier_id, :remarks
    );"""
    return text(sql)


def get_price_check_state_query():
    sql = """SELECT epc.price_check_id, epc.sales_enquiry_id, epc.pc_status
    FROM enquiry_price_check epc
    WHERE epc.price_check_id = :price_check_id
        AND epc.active = 1;"""
    return text(sql)


def get_price_check_dtl_ids_query():
    sql = """SELECT pcd.price_check_dtl_id
    FROM enquiry_price_check_dtl pcd
    WHERE pcd.price_check_id = :price_check_id;"""
    return text(sql)


def update_price_check_response():
    sql = """UPDATE enquiry_price_check SET
        pc_status = :pc_status,
        responded_by = :responded_by,
        responded_date_time = :responded_date_time,
        response_note = :response_note,
        updated_by = :updated_by,
        updated_date_time = :updated_date_time
    WHERE price_check_id = :price_check_id;"""
    return text(sql)


def update_price_check_dtl_response():
    sql = """UPDATE enquiry_price_check_dtl SET
        confirmed_rate = :confirmed_rate,
        rate_source = :rate_source,
        supplier_id = :supplier_id,
        remarks = :remarks
    WHERE price_check_dtl_id = :price_check_dtl_id
        AND price_check_id = :price_check_id;"""
    return text(sql)


def get_items_with_group_query():
    """Items incl. their group (setup dropdown; company scope via item group)."""
    sql = """SELECT
        im.item_id,
        im.item_code,
        im.item_name,
        im.item_grp_id,
        ig.item_grp_name,
        MIN(vip.full_item_code) AS full_item_code,
        im.uom_id,
        um.uom_name
    FROM item_mst im
    JOIN item_grp_mst ig ON ig.item_grp_id = im.item_grp_id
    LEFT JOIN uom_mst um ON um.uom_id = im.uom_id
    LEFT JOIN vw_item_with_group_path vip ON vip.item_id = im.item_id
    WHERE ig.co_id = :co_id
        AND im.active = 1
    GROUP BY im.item_id, im.item_code, im.item_name,
        im.item_grp_id, ig.item_grp_name, im.uom_id, um.uom_name
    ORDER BY COALESCE(MIN(vip.full_item_code), im.item_code);"""
    return text(sql)


def get_quotation_counts_by_enquiry_query():
    """Quotation count per enquiry for a set of enquiry ids (board cards)."""
    sql = """SELECT sq.sales_enquiry_id, COUNT(1) AS quotation_count
    FROM sales_quotation sq
    WHERE sq.active = 1
        AND sq.sales_enquiry_id IN :enquiry_ids
    GROUP BY sq.sales_enquiry_id;"""
    return text(sql).bindparams(bindparam("enquiry_ids", expanding=True))


def get_sales_order_counts_by_enquiry_query():
    """Sales-order count per enquiry (direct link or via quotation)."""
    sql = """SELECT COALESCE(so.sales_enquiry_id, sq.sales_enquiry_id) AS sales_enquiry_id,
        COUNT(1) AS sales_order_count
    FROM sales_order so
    LEFT JOIN sales_quotation sq ON sq.sales_quotation_id = so.quotation_id
    WHERE so.active = 1
        AND COALESCE(so.sales_enquiry_id, sq.sales_enquiry_id) IN :enquiry_ids
    GROUP BY COALESCE(so.sales_enquiry_id, sq.sales_enquiry_id);"""
    return text(sql).bindparams(bindparam("enquiry_ids", expanding=True))


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def clip_str(value, max_len: int) -> str | None:
    """Trim a string payload field to max_len; empty/None -> None."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    return s[:max_len]


def parse_date_str(value, field_name: str, required: bool = False):
    """Parse a YYYY-MM-DD payload/query value to a date (None passthrough)."""
    if value is None or value == "":
        if required:
            raise HTTPException(status_code=400, detail=f"{field_name} is required")
        return None
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid {field_name} format, expected YYYY-MM-DD",
        )


def to_flag(value) -> int:
    """Normalize a payload boolean-ish value to 0/1."""
    if value in (True, 1, "1", "true", "True", "Y", "y"):
        return 1
    return 0


def format_enquiry_no(mapped: dict) -> str:
    """Format the stored numeric enquiry_no for display (ENQ document type)."""
    raw_no = mapped.get("enquiry_no")
    if raw_no is None or raw_no == "":
        return ""
    try:
        return format_indent_no(
            indent_no=int(raw_no) if raw_no else None,
            co_prefix=mapped.get("co_prefix"),
            branch_prefix=mapped.get("branch_prefix"),
            indent_date=mapped.get("enquiry_date"),
            document_type=ENQ_DOC_TYPE,
        )
    except Exception:
        return str(raw_no)


def normalize_enquiry_lines(raw_lines) -> list[dict]:
    """Validate + normalize the enquiry line payload.

    Line rule (design §5.1): item_id OR item_desc_freetext — every line must
    carry at least one of the two.
    """
    if not isinstance(raw_lines, list) or len(raw_lines) == 0:
        raise HTTPException(status_code=400, detail="At least one line is required")

    normalized = []
    for idx, line in enumerate(raw_lines, start=1):
        if not isinstance(line, dict):
            raise HTTPException(status_code=400, detail=f"Invalid line at position {idx}")
        item_id = to_int(line.get("item_id") or line.get("item"), f"lines[{idx}].item")
        item_desc_freetext = clip_str(line.get("item_desc_freetext"), 500)
        if item_id is None and not item_desc_freetext:
            raise HTTPException(
                status_code=400,
                detail=f"lines[{idx}]: either item_id or item_desc_freetext is required",
            )
        qty = line.get("qty")
        normalized.append({
            "item_id": item_id,
            "item_desc_freetext": item_desc_freetext,
            "is_new_item": to_flag(line.get("is_new_item")),
            "design_change": to_flag(line.get("design_change")),
            "qty": to_positive_float(qty, f"lines[{idx}].qty") if qty not in (None, "") else None,
            "uom_id": to_int(line.get("uom_id") or line.get("uom"), f"lines[{idx}].uom"),
            "target_price": to_float(line.get("target_price"), f"lines[{idx}].target_price"),
            "remarks": clip_str(line.get("remarks"), 500),
        })
    return normalized


def parse_enquiry_header(body: dict) -> dict:
    """Validate + normalize the enquiry header payload (create/update)."""
    branch_id = to_int(body.get("branch_id") or body.get("branch"), "branch_id", required=True)
    enquiry_date = parse_date_str(
        body.get("enquiry_date") or body.get("date"), "enquiry_date", required=True
    )

    received_via = clip_str(body.get("received_via"), 20)
    if received_via is not None and received_via not in RECEIVED_VIA_OPTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid received_via. Allowed: {', '.join(RECEIVED_VIA_OPTIONS)}",
        )

    return {
        "enquiry_date": enquiry_date,
        "received_via": received_via,
        "branch_id": branch_id,
        # Party is optional in Draft (brand-new prospects); required at Open.
        "party_id": to_int(body.get("party_id") or body.get("party"), "party_id"),
        "contact_person": clip_str(body.get("contact_person"), 255),
        "contact_detail": clip_str(body.get("contact_detail"), 255),
        "customer_ref_no": clip_str(body.get("customer_ref_no"), 100),
        "expected_delivery_date": parse_date_str(
            body.get("expected_delivery_date"), "expected_delivery_date"
        ),
        "enquiry_desc": clip_str(body.get("enquiry_desc"), 1000),
        "internal_note": clip_str(body.get("internal_note"), 1000),
        "project_id": to_int(body.get("project_id"), "project_id"),
    }


def fetch_enquiry_flow_state(db: Session, sales_enquiry_id: int) -> dict:
    """Enquiry workflow + stage state; 404 when missing or inactive."""
    row = db.execute(
        get_enquiry_flow_state_query(),
        {"sales_enquiry_id": int(sales_enquiry_id)},
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Enquiry not found")
    state = dict(row._mapping)
    if not state.get("active"):
        raise HTTPException(status_code=404, detail="Enquiry not found or inactive")
    return state


def ensure_not_on_hold(state: dict) -> None:
    """Stage moves are frozen while an enquiry is on hold (design §4)."""
    if int(state.get("hold_flag") or 0) == 1:
        raise HTTPException(
            status_code=400,
            detail="Enquiry is on hold — RESUME it before making stage moves",
        )


# =============================================================================
# LIST / BOARD / SETUP / BY-ID ENDPOINTS
# =============================================================================

@router.get("/get_enquiry_table")
def get_enquiry_table(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Paginated enquiry list with stage/status/party/date-range/search filters."""
    try:
        qp = request.query_params
        co_id = to_int(qp.get("co_id"), "co_id", required=True)
        branch_id = to_int(qp.get("branch_id"), "branch_id")
        status_id = to_int(qp.get("status_id"), "status_id")
        party_id = to_int(qp.get("party_id"), "party_id")
        from_date = parse_date_str(qp.get("from_date"), "from_date")
        to_date = parse_date_str(qp.get("to_date"), "to_date")

        # Stage filter — accept stage_id or stage_code.
        stage_id = to_int(qp.get("stage_id"), "stage_id")
        stage_code = qp.get("stage_code")
        if stage_id is None and stage_code:
            stage_row = db.execute(
                text("""SELECT stage_id FROM flow_stage_mst
                        WHERE module = :module AND stage_code = :stage_code AND active = 1;"""),
                {"module": FLOW_MODULE_ENQUIRY, "stage_code": str(stage_code)},
            ).fetchone()
            if not stage_row:
                raise HTTPException(status_code=400, detail=f"Unknown stage_code: {stage_code}")
            stage_id = int(dict(stage_row._mapping)["stage_id"])

        page = to_int(qp.get("page"), "page") or 1
        limit = to_int(qp.get("limit"), "limit") or 10
        page = max(page, 1)
        limit = max(min(limit, 100), 1)
        offset = (page - 1) * limit

        search = qp.get("search")
        search_like = f"%{search.strip()}%" if search and search.strip() else None

        params = {
            "co_id": co_id,
            "branch_id": branch_id,
            "stage_id": stage_id,
            "status_id": status_id,
            "party_id": party_id,
            "from_date": from_date,
            "to_date": to_date,
            "search_like": search_like,
        }

        rows = db.execute(
            get_enquiry_table_query(),
            {**params, "limit": limit, "offset": offset},
        ).fetchall()

        data = []
        for row in rows:
            mapped = dict(row._mapping)
            data.append({
                "sales_enquiry_id": mapped.get("sales_enquiry_id"),
                "enquiry_no": format_enquiry_no(mapped),
                "enquiry_no_raw": mapped.get("enquiry_no"),
                "enquiry_date": format_date(mapped.get("enquiry_date")),
                "received_via": mapped.get("received_via"),
                "branch_id": mapped.get("branch_id"),
                "branch_name": mapped.get("branch_name"),
                "party_id": mapped.get("party_id"),
                "party_name": mapped.get("party_name"),
                "contact_person": mapped.get("contact_person"),
                "customer_ref_no": mapped.get("customer_ref_no"),
                "expected_delivery_date": format_date(mapped.get("expected_delivery_date")),
                "current_stage_id": mapped.get("current_stage_id"),
                "stage_code": mapped.get("stage_code"),
                "stage_name": mapped.get("stage_name"),
                "dept_hint": mapped.get("dept_hint"),
                "days_in_stage": mapped.get("days_in_stage"),
                "hold_flag": mapped.get("hold_flag"),
                "status_id": mapped.get("status_id"),
                "status": mapped.get("status_name"),
                "close_reason": mapped.get("close_reason"),
                "project_id": mapped.get("project_id"),
            })

        count_result = db.execute(get_enquiry_table_count_query(), params).scalar()
        total = int(count_result) if count_result is not None else 0

        return {"data": data, "total": total}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_enquiry_board")
def get_enquiry_board(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Flow Board — open enquiries grouped per stage with aging, hold flag,
    latest feedback snippet and linked-doc counts."""
    try:
        qp = request.query_params
        co_id = to_int(qp.get("co_id"), "co_id", required=True)
        branch_id = to_int(qp.get("branch_id"), "branch_id")

        card_rows = db.execute(
            get_enquiry_board_query(),
            {"co_id": co_id, "branch_id": branch_id, "doc_type": ENQUIRY_FLOW_DOC_TYPE},
        ).fetchall()
        cards = [dict(r._mapping) for r in card_rows]

        # Linked-doc counts (quotations / sales orders) in bulk — no N+1.
        enquiry_ids = [c["sales_enquiry_id"] for c in cards]
        quotation_counts: dict[int, int] = {}
        sales_order_counts: dict[int, int] = {}
        if enquiry_ids:
            for row in db.execute(
                get_quotation_counts_by_enquiry_query(), {"enquiry_ids": enquiry_ids}
            ).fetchall():
                mapped = dict(row._mapping)
                quotation_counts[mapped["sales_enquiry_id"]] = int(mapped["quotation_count"] or 0)
            for row in db.execute(
                get_sales_order_counts_by_enquiry_query(), {"enquiry_ids": enquiry_ids}
            ).fetchall():
                mapped = dict(row._mapping)
                sales_order_counts[mapped["sales_enquiry_id"]] = int(mapped["sales_order_count"] or 0)

        cards_by_stage: dict[int, list[dict]] = {}
        for card in cards:
            enquiry_id = card.get("sales_enquiry_id")
            card["enquiry_no_raw"] = card.get("enquiry_no")
            card["enquiry_no"] = format_enquiry_no(card)
            card["enquiry_date"] = format_date(card.get("enquiry_date"))
            card["expected_delivery_date"] = format_date(card.get("expected_delivery_date"))
            card["quotation_count"] = quotation_counts.get(enquiry_id, 0)
            card["sales_order_count"] = sales_order_counts.get(enquiry_id, 0)
            cards_by_stage.setdefault(card.get("current_stage_id"), []).append(card)

        count_rows = db.execute(
            get_enquiry_board_counts_query(),
            {"module": FLOW_MODULE_ENQUIRY, "co_id": co_id, "branch_id": branch_id},
        ).fetchall()

        stages = []
        for row in count_rows:
            stage = dict(row._mapping)
            stage["enquiries"] = cards_by_stage.get(stage.get("stage_id"), [])
            stages.append(stage)

        return {"data": {"stages": stages}}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_enquiry_setup")
def get_enquiry_setup(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Masters for the enquiry create/edit page: customers (party type 2),
    UOMs, items (incl. item group), stage master and received-via options.
    When menu_id is also given, returns the company's ISO document number."""
    try:
        qp = request.query_params
        co_id = to_int(qp.get("co_id"), "co_id", required=True)
        menu_id = to_int(qp.get("menu_id"), "menu_id")

        customer_rows = db.execute(get_customers_for_sales(co_id=co_id), {"co_id": co_id}).fetchall()
        customers = [dict(r._mapping) for r in customer_rows]

        uom_rows = db.execute(get_uom_list(), {}).fetchall()
        uoms = [dict(r._mapping) for r in uom_rows]

        item_rows = db.execute(get_items_with_group_query(), {"co_id": co_id}).fetchall()
        items = [dict(r._mapping) for r in item_rows]

        stage_rows = db.execute(
            get_stages_by_module_query(), {"module": FLOW_MODULE_ENQUIRY}
        ).fetchall()
        stages = [dict(r._mapping) for r in stage_rows]

        iso_doc_no = None
        if menu_id is not None:
            iso_row = db.execute(
                get_iso_doc_no_query(), {"co_id": co_id, "menu_id": menu_id}
            ).fetchone()
            if iso_row:
                iso_doc_no = dict(iso_row._mapping).get("iso_doc_no")

        return {
            "data": {
                "customers": customers,
                "uoms": uoms,
                "items": items,
                "stages": stages,
                "received_via_options": list(RECEIVED_VIA_OPTIONS),
                "iso_doc_no": iso_doc_no,
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_enquiry_by_id")
def get_enquiry_by_id(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Enquiry header + lines + full stage-log timeline + linked-doc summary.
    When menu_id is passed, embeds the standard approval permissions block."""
    try:
        qp = request.query_params
        sales_enquiry_id = to_int(qp.get("sales_enquiry_id"), "sales_enquiry_id", required=True)
        co_id = to_int(qp.get("co_id"), "co_id", required=True)
        menu_id = resolve_enquiry_menu_id(db, to_int(qp.get("menu_id"), "menu_id"))

        header_row = db.execute(
            get_enquiry_by_id_query(),
            {"sales_enquiry_id": sales_enquiry_id, "co_id": co_id},
        ).fetchone()
        if not header_row:
            raise HTTPException(status_code=404, detail="Enquiry not found or access denied")
        header = dict(header_row._mapping)

        line_rows = db.execute(
            get_enquiry_dtl_by_id_query(), {"sales_enquiry_id": sales_enquiry_id}
        ).fetchall()
        lines = [dict(r._mapping) for r in line_rows]

        timeline_rows = db.execute(
            get_enquiry_stage_log_query(),
            {"doc_type": ENQUIRY_FLOW_DOC_TYPE, "doc_id": sales_enquiry_id},
        ).fetchall()
        timeline = [dict(r._mapping) for r in timeline_rows]

        linked_rows = db.execute(
            get_enquiry_linked_docs_query(), {"sales_enquiry_id": sales_enquiry_id}
        ).fetchall()
        linked_docs = [dict(r._mapping) for r in linked_rows]

        header["enquiry_no_raw"] = header.get("enquiry_no")
        header["enquiry_no"] = format_enquiry_no(header)
        header["enquiry_date"] = format_date(header.get("enquiry_date"))
        header["expected_delivery_date"] = format_date(header.get("expected_delivery_date"))

        approval_level = header.get("approval_level")
        if approval_level is not None:
            try:
                approval_level = int(approval_level)
            except (TypeError, ValueError):
                approval_level = None

        status_id = header.get("status_id")
        branch_id = header.get("branch_id")

        permissions = None
        if menu_id is not None and branch_id is not None and status_id is not None:
            try:
                permissions = calculate_approval_permissions(
                    user_id=int(token_data.get("user_id")),
                    menu_id=menu_id,
                    branch_id=branch_id,
                    status_id=status_id,
                    current_approval_level=approval_level,
                    db=db,
                )
            except Exception:
                logger.exception("Error calculating enquiry permissions")

        response_data = {
            **header,
            "lines": lines,
            "timeline": timeline,
            "linked_docs": linked_docs,
        }
        if permissions is not None:
            response_data["permissions"] = permissions

        return {"data": response_data}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching enquiry by ID")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# DRAFT CRUD ENDPOINTS
# =============================================================================

@router.post("/create_enquiry")
def create_enquiry(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Create a sales enquiry as Draft (21) with its lines."""
    try:
        body = parse_json_body(request)
        header = parse_enquiry_header(body)
        lines = normalize_enquiry_lines(body.get("lines") or body.get("items"))

        updated_by = to_int(token_data.get("user_id"), "updated_by")
        created_at = now_ist()

        result = db.execute(insert_sales_enquiry(), {
            **header,
            "status_id": ENQUIRY_STATUS_IDS["DRAFT"],
            "approval_level": 0,
            "updated_by": updated_by,
            "updated_date_time": created_at,
        })
        sales_enquiry_id = result.lastrowid
        if not sales_enquiry_id:
            raise HTTPException(status_code=500, detail="Failed to create enquiry header")

        dtl_query = insert_sales_enquiry_dtl()
        for line in lines:
            db.execute(dtl_query, {**line, "sales_enquiry_id": sales_enquiry_id})

        db.commit()
        return {
            "data": {"sales_enquiry_id": sales_enquiry_id},
            "message": "Enquiry created successfully",
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error creating enquiry")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/update_enquiry")
def update_enquiry(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Update a Draft (21) enquiry — header + replace lines."""
    try:
        body = parse_json_body(request)
        sales_enquiry_id = to_int(
            body.get("sales_enquiry_id") or body.get("id"), "sales_enquiry_id", required=True
        )
        header = parse_enquiry_header(body)
        lines = normalize_enquiry_lines(body.get("lines") or body.get("items"))

        state = fetch_enquiry_flow_state(db, sales_enquiry_id)
        if state.get("status_id") != ENQUIRY_STATUS_IDS["DRAFT"]:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Cannot update enquiry with status_id {state.get('status_id')}. "
                    f"Expected {ENQUIRY_STATUS_IDS['DRAFT']} (Draft)."
                ),
            )

        updated_by = to_int(token_data.get("user_id"), "updated_by")
        updated_at = now_ist()

        db.execute(update_sales_enquiry(), {
            **header,
            "sales_enquiry_id": sales_enquiry_id,
            "updated_by": updated_by,
            "updated_date_time": updated_at,
        })

        db.execute(deactivate_sales_enquiry_dtl(), {"sales_enquiry_id": sales_enquiry_id})

        dtl_query = insert_sales_enquiry_dtl()
        for line in lines:
            db.execute(dtl_query, {**line, "sales_enquiry_id": sales_enquiry_id})

        db.commit()
        return {
            "data": {"sales_enquiry_id": sales_enquiry_id},
            "message": "Enquiry updated successfully",
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error updating enquiry")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# WORKFLOW ENDPOINTS (standard 21 -> 1 -> 20 -> 3/4/6 lifecycle)
# =============================================================================

@router.post("/open_enquiry")
def open_enquiry(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Open an enquiry (21 -> 1): mint the ENQ document number (per branch +
    financial year) and set stage ENQ_NOTED via a CREATE stage-log entry —
    one transaction."""
    try:
        body = parse_json_body(request)
        sales_enquiry_id = to_int(body.get("sales_enquiry_id"), "sales_enquiry_id", required=True)
        user_id = int(token_data.get("user_id"))

        state = fetch_enquiry_flow_state(db, sales_enquiry_id)

        if state.get("status_id") != ENQUIRY_STATUS_IDS["DRAFT"]:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Cannot open enquiry with status_id {state.get('status_id')}. "
                    f"Expected {ENQUIRY_STATUS_IDS['DRAFT']} (Draft)."
                ),
            )
        # Party is optional in Draft but required to open (design §5.1).
        if state.get("party_id") is None:
            raise HTTPException(
                status_code=400,
                detail="A customer (party) is required before the enquiry can be opened",
            )
        branch_id = state.get("branch_id")
        if branch_id is None:
            raise HTTPException(status_code=400, detail="branch_id is required to open an enquiry")
        enquiry_date = state.get("enquiry_date")
        if not enquiry_date:
            raise HTTPException(
                status_code=400, detail="Enquiry date is required to generate the document number"
            )

        # CREATE is only legal when no current stage exists yet.
        validate_transition(
            current_stage_code=state.get("stage_code"),
            action=ACTION_CREATE,
            to_stage_code=STAGE_ENQ_NOTED,
            enquiry_status_id=state.get("status_id"),
            feedback=None,
        )

        # Mint the document number — same per-branch + FY pattern as quotation.
        current_no = state.get("enquiry_no")
        new_no = None
        if current_no is None or current_no == "" or current_no == "0":
            fy_start, fy_end = get_fy_boundaries(enquiry_date)
            max_result = db.execute(get_max_enquiry_no_for_branch_fy(), {
                "branch_id": int(branch_id),
                "fy_start_date": fy_start,
                "fy_end_date": fy_end,
            }).fetchone()
            max_no = dict(max_result._mapping).get("max_doc_no") or 0 if max_result else 0
            new_no = str(int(max_no) + 1)

        updated_at = now_ist()
        db.execute(update_enquiry_status(), {
            "sales_enquiry_id": sales_enquiry_id,
            "status_id": ENQUIRY_STATUS_IDS["OPEN"],
            "approval_level": None,
            "updated_by": user_id,
            "updated_date_time": updated_at,
            "enquiry_no": new_no,
        })

        # Stage -> ENQ_NOTED (CREATE log entry; also sets current_stage_id + stage_since).
        log_stage_transition(
            db,
            sales_enquiry_id=sales_enquiry_id,
            from_stage_id=None,
            to_stage_code=STAGE_ENQ_NOTED,
            action=ACTION_CREATE,
            feedback=clip_str(body.get("feedback"), 1000),
            linked_doc_type=None,
            linked_doc_id=None,
            user_id=user_id,
        )

        db.commit()
        return {
            "status": "success",
            "new_status_id": ENQUIRY_STATUS_IDS["OPEN"],
            "message": "Enquiry opened successfully.",
            "enquiry_no": new_no if new_no else current_no,
            "stage_code": STAGE_ENQ_NOTED,
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error opening enquiry")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cancel_draft_enquiry")
def cancel_draft_enquiry(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Cancel a draft enquiry (21 -> 6)."""
    try:
        body = parse_json_body(request)
        sales_enquiry_id = to_int(body.get("sales_enquiry_id"), "sales_enquiry_id", required=True)
        user_id = int(token_data.get("user_id"))

        state = fetch_enquiry_flow_state(db, sales_enquiry_id)
        if state.get("status_id") != ENQUIRY_STATUS_IDS["DRAFT"]:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Cannot cancel enquiry with status_id {state.get('status_id')}. "
                    f"Expected {ENQUIRY_STATUS_IDS['DRAFT']} (Draft)."
                ),
            )

        db.execute(update_enquiry_status(), {
            "sales_enquiry_id": sales_enquiry_id,
            "status_id": ENQUIRY_STATUS_IDS["CANCELLED"],
            "approval_level": None,
            "updated_by": user_id,
            "updated_date_time": now_ist(),
            "enquiry_no": None,
        })
        db.commit()
        return {
            "status": "success",
            "new_status_id": ENQUIRY_STATUS_IDS["CANCELLED"],
            "message": "Draft cancelled successfully.",
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error cancelling draft enquiry")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/send_enquiry_for_approval")
def send_enquiry_for_approval(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Send an enquiry for approval (1 -> 20, level = 1)."""
    try:
        body = parse_json_body(request)
        sales_enquiry_id = to_int(body.get("sales_enquiry_id"), "sales_enquiry_id", required=True)
        user_id = int(token_data.get("user_id"))

        state = fetch_enquiry_flow_state(db, sales_enquiry_id)
        if state.get("status_id") != ENQUIRY_STATUS_IDS["OPEN"]:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Cannot send for approval with status_id {state.get('status_id')}. "
                    f"Expected {ENQUIRY_STATUS_IDS['OPEN']} (Open)."
                ),
            )

        db.execute(update_enquiry_status(), {
            "sales_enquiry_id": sales_enquiry_id,
            "status_id": ENQUIRY_STATUS_IDS["PENDING_APPROVAL"],
            "approval_level": 1,
            "updated_by": user_id,
            "updated_date_time": now_ist(),
            "enquiry_no": None,
        })
        db.commit()
        return {
            "status": "success",
            "new_status_id": ENQUIRY_STATUS_IDS["PENDING_APPROVAL"],
            "new_approval_level": 1,
            "message": "Enquiry sent for approval.",
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error sending enquiry for approval")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/approve_enquiry")
def approve_enquiry(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Approve an enquiry (20 -> 20 next level, or 20 -> 3 on the final level).

    The enquiry is an amount-less document: document_amount is passed as None,
    which makes process_approval skip every value-based limit check entirely
    (passing 0 would instead trip the "within single-amount limit" branch and
    short-circuit multi-level hierarchies)."""
    try:
        body = parse_json_body(request)
        sales_enquiry_id = to_int(body.get("sales_enquiry_id"), "sales_enquiry_id", required=True)
        menu_id = resolve_enquiry_menu_id(db, to_int(body.get("menu_id"), "menu_id"))
        if menu_id is None:
            raise HTTPException(status_code=400, detail="menu_id is required")
        user_id = int(token_data.get("user_id"))

        result = process_approval(
            doc_id=sales_enquiry_id,
            user_id=user_id,
            menu_id=menu_id,
            db=db,
            get_doc_fn=get_enquiry_flow_state_query,
            update_status_fn=update_enquiry_status,
            id_param_name="sales_enquiry_id",
            doc_name="Enquiry",
            document_amount=None,
            extra_update_params={"enquiry_no": None},
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error approving enquiry")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reject_enquiry")
def reject_enquiry(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Reject an enquiry (20 -> 4). The rejection reason is PERSISTED into
    flow_stage_log as a stage-preserving AUTO entry with feedback = reason
    (fixing the repo-wide "reason logged but not stored" gap for this document)."""
    try:
        body = parse_json_body(request)
        sales_enquiry_id = to_int(body.get("sales_enquiry_id"), "sales_enquiry_id", required=True)
        menu_id = resolve_enquiry_menu_id(db, to_int(body.get("menu_id"), "menu_id"))
        user_id = int(token_data.get("user_id"))
        reason = clip_str(body.get("reason"), 1000)

        result = process_rejection(
            doc_id=sales_enquiry_id,
            user_id=user_id,
            menu_id=menu_id,
            db=db,
            get_doc_fn=get_enquiry_flow_state_query,
            update_status_fn=update_enquiry_status,
            id_param_name="sales_enquiry_id",
            doc_name="Enquiry",
            reason=reason,
            extra_update_params={"enquiry_no": None},
        )

        # process_rejection has already committed the status change; persist the
        # reason into the feedback trail (stage unchanged) as a follow-up write.
        if reason:
            state = fetch_enquiry_flow_state(db, sales_enquiry_id)
            if state.get("stage_code") and state.get("stage_code") not in TERMINAL_STAGES:
                log_stage_transition(
                    db,
                    sales_enquiry_id=sales_enquiry_id,
                    from_stage_id=state.get("current_stage_id"),
                    to_stage_code=state.get("stage_code"),
                    action=ACTION_AUTO,
                    feedback=reason,
                    linked_doc_type=None,
                    linked_doc_id=None,
                    user_id=user_id,
                )
                db.commit()

        return result
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error rejecting enquiry")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reopen_enquiry")
def reopen_enquiry(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Reopen a cancelled (6 -> 21) or rejected (4 -> 1) enquiry."""
    try:
        body = parse_json_body(request)
        sales_enquiry_id = to_int(body.get("sales_enquiry_id"), "sales_enquiry_id", required=True)
        user_id = int(token_data.get("user_id"))

        state = fetch_enquiry_flow_state(db, sales_enquiry_id)
        current_status = state.get("status_id")
        if current_status == ENQUIRY_STATUS_IDS["CANCELLED"]:
            new_status_id = ENQUIRY_STATUS_IDS["DRAFT"]
        elif current_status == ENQUIRY_STATUS_IDS["REJECTED"]:
            new_status_id = ENQUIRY_STATUS_IDS["OPEN"]
        else:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Cannot reopen enquiry with status_id {current_status}. "
                    f"Only {ENQUIRY_STATUS_IDS['CANCELLED']} (Cancelled) or "
                    f"{ENQUIRY_STATUS_IDS['REJECTED']} (Rejected)."
                ),
            )

        db.execute(update_enquiry_status(), {
            "sales_enquiry_id": sales_enquiry_id,
            "status_id": new_status_id,
            "approval_level": None,
            "updated_by": user_id,
            "updated_date_time": now_ist(),
            "enquiry_no": None,
        })
        db.commit()
        return {
            "status": "success",
            "new_status_id": new_status_id,
            "message": f"Enquiry reopened (status: {new_status_id}).",
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error reopening enquiry")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# STAGE ENGINE ENDPOINTS
# =============================================================================

@router.post("/move_stage")
def move_stage(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Move an enquiry through the stage model — one transaction.

    Payload: {sales_enquiry_id, action, to_stage_code?, feedback?,
    linked_doc_type?, linked_doc_id?, lost_remarks?}.

    Rules (validated via validate_transition, design §4): FORWARD only to an
    allowed next stage (incl. the status-3 approval gate out of ENQ_NOTED);
    SEND_BACK to an earlier stage with mandatory feedback; HOLD/RESUME toggle
    hold_flag without changing the stage; MARK_LOST (stage seq <= 50) sets
    stage LOST + status 5 + close_reason 'lost'."""
    try:
        body = parse_json_body(request)
        sales_enquiry_id = to_int(body.get("sales_enquiry_id"), "sales_enquiry_id", required=True)
        action = body.get("action")
        if not action:
            raise HTTPException(status_code=400, detail="action is required")
        action = str(action).strip().upper()
        to_stage_code = body.get("to_stage_code") or None
        feedback = clip_str(body.get("feedback"), 1000)
        linked_doc_type = body.get("linked_doc_type") or None
        linked_doc_id = to_int(body.get("linked_doc_id"), "linked_doc_id")
        user_id = int(token_data.get("user_id"))

        # Endpoint-scoped actions: CREATE belongs to /open_enquiry, CLOSE to
        # /close_enquiry, AUTO is written only by system hooks.
        if action == ACTION_CREATE:
            raise HTTPException(status_code=400, detail="Use /open_enquiry to open an enquiry")
        if action == ACTION_CLOSE:
            raise HTTPException(status_code=400, detail="Use /close_enquiry to close an enquiry")
        if action == ACTION_AUTO:
            raise HTTPException(status_code=400, detail="AUTO transitions are system-generated only")

        state = fetch_enquiry_flow_state(db, sales_enquiry_id)
        current_stage_code = state.get("stage_code")
        current_stage_id = state.get("current_stage_id")
        on_hold = int(state.get("hold_flag") or 0) == 1

        # Hold gate: a held enquiry only accepts RESUME; HOLD/RESUME must
        # actually toggle.
        if action == ACTION_HOLD:
            if on_hold:
                raise HTTPException(status_code=400, detail="Enquiry is already on hold")
        elif action == ACTION_RESUME:
            if not on_hold:
                raise HTTPException(status_code=400, detail="Enquiry is not on hold")
        else:
            ensure_not_on_hold(state)

        validate_transition(
            current_stage_code=current_stage_code,
            action=action,
            to_stage_code=to_stage_code,
            enquiry_status_id=state.get("status_id"),
            feedback=feedback,
        )

        # Costing completeness gate: forwarding COSTING_REVIEW to a priced
        # customer document (QUOTATION / direct-order ORDER_CONFIRMED) requires
        # every active line to be fully costed + priced. PRICE_CHECK is exempt —
        # it is exactly how a price is obtained while costing is incomplete, and
        # free-text lines can never clear the gate (design 2026-07-16, D5).
        if (
            action == ACTION_FORWARD
            and current_stage_code == STAGE_COSTING_REVIEW
            and to_stage_code in (STAGE_QUOTATION, STAGE_ORDER_CONFIRMED)
        ):
            pending = db.execute(
                get_enquiry_costing_pending_query(),
                {"sales_enquiry_id": sales_enquiry_id},
            ).fetchall()
            if pending:
                ids = ", ".join(str(r._mapping["enquiry_dtl_id"]) for r in pending)
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Costing is not complete — confirm cost and set overhead% + "
                        f"margin% (create the item + BOM for new-item lines) for line(s): {ids}"
                    ),
                )

        updated_at = now_ist()
        new_hold_flag = state.get("hold_flag") or 0

        if action in (ACTION_HOLD, ACTION_RESUME):
            new_hold_flag = 1 if action == ACTION_HOLD else 0
            db.execute(update_enquiry_hold_flag(), {
                "sales_enquiry_id": sales_enquiry_id,
                "hold_flag": new_hold_flag,
                "updated_by": user_id,
                "updated_date_time": updated_at,
            })
            result_stage_code = current_stage_code
        elif action == ACTION_MARK_LOST:
            lost_remarks = clip_str(body.get("lost_remarks"), 500) or (feedback[:500] if feedback else None)
            db.execute(update_enquiry_close(), {
                "sales_enquiry_id": sales_enquiry_id,
                "status_id": ENQUIRY_STATUS_IDS["CLOSED"],
                "close_reason": "lost",
                "lost_remarks": lost_remarks,
                "updated_by": user_id,
                "updated_date_time": updated_at,
            })
            result_stage_code = STAGE_LOST
        else:  # FORWARD / SEND_BACK
            result_stage_code = to_stage_code

        log_stage_transition(
            db,
            sales_enquiry_id=sales_enquiry_id,
            from_stage_id=current_stage_id,
            to_stage_code=result_stage_code,
            action=action,
            feedback=feedback,
            linked_doc_type=linked_doc_type,
            linked_doc_id=linked_doc_id,
            user_id=user_id,
        )

        db.commit()
        return {
            "status": "success",
            "message": f"{action} applied successfully.",
            "action": action,
            "stage_code": result_stage_code,
            "hold_flag": int(new_hold_flag),
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error moving enquiry stage")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/close_enquiry")
def close_enquiry(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Close an enquiry: {sales_enquiry_id, close_reason, remarks}.

    close_reason 'won'/'cancelled' -> stage CLOSED (action CLOSE);
    close_reason 'lost' -> stage LOST (action MARK_LOST, only before order
    confirmation). Status -> 5 in both cases — one transaction."""
    try:
        body = parse_json_body(request)
        sales_enquiry_id = to_int(body.get("sales_enquiry_id"), "sales_enquiry_id", required=True)
        close_reason = body.get("close_reason")
        if not close_reason:
            raise HTTPException(status_code=400, detail="close_reason is required")
        close_reason = str(close_reason).strip().lower()
        if close_reason not in CLOSE_REASONS:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid close_reason. Allowed: {', '.join(CLOSE_REASONS)}",
            )
        remarks = clip_str(body.get("remarks"), 1000)
        user_id = int(token_data.get("user_id"))

        state = fetch_enquiry_flow_state(db, sales_enquiry_id)
        ensure_not_on_hold(state)

        if close_reason == "lost":
            action = ACTION_MARK_LOST
            target_stage_code = STAGE_LOST
        else:
            action = ACTION_CLOSE
            target_stage_code = STAGE_CLOSED

        validate_transition(
            current_stage_code=state.get("stage_code"),
            action=action,
            to_stage_code=target_stage_code,
            enquiry_status_id=state.get("status_id"),
            feedback=remarks,
        )

        db.execute(update_enquiry_close(), {
            "sales_enquiry_id": sales_enquiry_id,
            "status_id": ENQUIRY_STATUS_IDS["CLOSED"],
            "close_reason": close_reason,
            "lost_remarks": remarks[:500] if (close_reason == "lost" and remarks) else None,
            "updated_by": user_id,
            "updated_date_time": now_ist(),
        })

        log_stage_transition(
            db,
            sales_enquiry_id=sales_enquiry_id,
            from_stage_id=state.get("current_stage_id"),
            to_stage_code=target_stage_code,
            action=action,
            feedback=remarks,
            linked_doc_type=None,
            linked_doc_id=None,
            user_id=user_id,
        )

        db.commit()
        return {
            "status": "success",
            "new_status_id": ENQUIRY_STATUS_IDS["CLOSED"],
            "message": f"Enquiry closed ({close_reason}).",
            "stage_code": target_stage_code,
            "close_reason": close_reason,
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error closing enquiry")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# COSTING CONFIRM
# =============================================================================

@router.post("/confirm_line_costing")
def confirm_line_costing(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Confirm the cost basis of an enquiry line: {enquiry_dtl_id, bom_hdr_id}.

    Requires the enquiry stage to be COSTING_REVIEW or PRICE_CHECK. Verifies
    the BOM header belongs to the line's item, approves its current
    bom_cost_snapshot (status='approved') and writes cost_snapshot_id +
    confirmed_cost_per_unit + confirmer onto the line — one transaction."""
    try:
        body = parse_json_body(request)
        enquiry_dtl_id = to_int(body.get("enquiry_dtl_id"), "enquiry_dtl_id", required=True)
        bom_hdr_id = to_int(body.get("bom_hdr_id"), "bom_hdr_id", required=True)
        user_id = int(token_data.get("user_id"))

        def _opt_pct(v, name):
            if v is None or v == "":
                return None
            try:
                f = float(v)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail=f"Invalid {name}")
            if f < 0:
                raise HTTPException(status_code=400, detail=f"{name} cannot be negative")
            return f

        overhead_pct = _opt_pct(body.get("overhead_pct"), "overhead_pct")
        margin_pct = _opt_pct(body.get("margin_pct"), "margin_pct")

        line_row = db.execute(
            get_enquiry_dtl_state_query(), {"enquiry_dtl_id": enquiry_dtl_id}
        ).fetchone()
        if not line_row:
            raise HTTPException(status_code=404, detail="Enquiry line not found")
        line = dict(line_row._mapping)

        stage_code = line.get("stage_code")
        if stage_code not in (STAGE_COSTING_REVIEW, STAGE_PRICE_CHECK):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Costing can only be confirmed while the enquiry is in "
                    f"{STAGE_COSTING_REVIEW} or {STAGE_PRICE_CHECK} (current: {stage_code})"
                ),
            )
        if line.get("item_id") is None:
            raise HTTPException(
                status_code=400,
                detail="This is a free-text line — create the item (and its BOM) before confirming costing",
            )

        bom_row = db.execute(
            get_bom_hdr_for_confirm_query(), {"bom_hdr_id": bom_hdr_id}
        ).fetchone()
        if not bom_row:
            raise HTTPException(status_code=404, detail="BOM header not found or inactive")
        bom = dict(bom_row._mapping)
        if int(bom.get("item_id")) != int(line.get("item_id")):
            raise HTTPException(
                status_code=400,
                detail="The selected BOM does not belong to the enquiry line's item",
            )

        snapshot_row = db.execute(
            get_current_bom_cost_snapshot_query(), {"bom_hdr_id": bom_hdr_id}
        ).fetchone()
        if not snapshot_row:
            raise HTTPException(
                status_code=404,
                detail="No current cost snapshot for this BOM — run the costing rollup first",
            )
        snapshot = dict(snapshot_row._mapping)
        cost_snapshot_id = int(snapshot["bom_cost_snapshot_id"])
        cost_per_unit = float(snapshot.get("cost_per_unit") or 0)

        confirmed_at = now_ist()
        db.execute(approve_bom_cost_snapshot(), {
            "bom_cost_snapshot_id": cost_snapshot_id,
            "updated_by": user_id,
            "updated_date_time": confirmed_at,
        })
        db.execute(update_enquiry_dtl_costing(), {
            "enquiry_dtl_id": enquiry_dtl_id,
            "bom_hdr_id": bom_hdr_id,
            "cost_snapshot_id": cost_snapshot_id,
            "confirmed_cost_per_unit": cost_per_unit,
            "costing_confirmed_by": user_id,
            "costing_confirmed_date": confirmed_at,
            "overhead_pct": overhead_pct,
            "margin_pct": margin_pct,
        })

        db.commit()
        return {
            "data": {
                "enquiry_dtl_id": enquiry_dtl_id,
                "bom_hdr_id": bom_hdr_id,
                "cost_snapshot_id": cost_snapshot_id,
                "confirmed_cost_per_unit": cost_per_unit,
                "overhead_pct": overhead_pct,
                "margin_pct": margin_pct,
            },
            "message": "Line costing confirmed successfully",
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error confirming line costing")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# PRICE CHECK (Design/Costing -> Procurement consult)
# =============================================================================

@router.post("/create_price_check")
def create_price_check(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Raise a price check: {sales_enquiry_id, request_note?, items?}.

    items: [{enquiry_dtl_id?, item_id?, remarks?}] — when omitted, all active
    enquiry lines that carry an item_id are used. last_po_rate / last_po_date /
    last_supplier_id are prefilled per item (evidence-stable snapshot). The
    enquiry is FORWARDed COSTING_REVIEW -> PRICE_CHECK with a stage-log entry —
    one transaction."""
    try:
        body = parse_json_body(request)
        sales_enquiry_id = to_int(body.get("sales_enquiry_id"), "sales_enquiry_id", required=True)
        request_note = clip_str(body.get("request_note"), 500)
        user_id = int(token_data.get("user_id"))

        state = fetch_enquiry_flow_state(db, sales_enquiry_id)
        ensure_not_on_hold(state)

        # The move is validated up-front so nothing is written for an illegal
        # request (e.g. a price check while not in COSTING_REVIEW).
        validate_transition(
            current_stage_code=state.get("stage_code"),
            action=ACTION_FORWARD,
            to_stage_code=STAGE_PRICE_CHECK,
            enquiry_status_id=state.get("status_id"),
            feedback=request_note,
        )

        # Enquiry lines (for enquiry_dtl_id validation / default row set).
        line_rows = db.execute(
            get_enquiry_active_lines_query(), {"sales_enquiry_id": sales_enquiry_id}
        ).fetchall()
        lines_by_id = {int(dict(r._mapping)["enquiry_dtl_id"]): dict(r._mapping) for r in line_rows}

        raw_items = body.get("items")
        pc_rows = []
        if isinstance(raw_items, list) and len(raw_items) > 0:
            for idx, item in enumerate(raw_items, start=1):
                if not isinstance(item, dict):
                    raise HTTPException(status_code=400, detail=f"Invalid item at position {idx}")
                enquiry_dtl_id = to_int(item.get("enquiry_dtl_id"), f"items[{idx}].enquiry_dtl_id")
                item_id = to_int(item.get("item_id"), f"items[{idx}].item_id")
                if enquiry_dtl_id is not None:
                    line = lines_by_id.get(enquiry_dtl_id)
                    if not line:
                        raise HTTPException(
                            status_code=400,
                            detail=f"items[{idx}]: enquiry_dtl_id {enquiry_dtl_id} does not belong to this enquiry",
                        )
                    if item_id is None:
                        item_id = line.get("item_id")
                if item_id is None:
                    raise HTTPException(
                        status_code=400,
                        detail=f"items[{idx}]: item_id is required (free-text lines cannot be price-checked)",
                    )
                pc_rows.append({
                    "enquiry_dtl_id": enquiry_dtl_id,
                    "item_id": int(item_id),
                    "remarks": clip_str(item.get("remarks"), 500),
                })
        else:
            # Default: every active enquiry line that carries an item.
            for line in lines_by_id.values():
                if line.get("item_id") is not None:
                    pc_rows.append({
                        "enquiry_dtl_id": int(line["enquiry_dtl_id"]),
                        "item_id": int(line["item_id"]),
                        "remarks": None,
                    })
            if not pc_rows:
                raise HTTPException(
                    status_code=400,
                    detail="No enquiry lines with an item to price-check (free-text lines need an item first)",
                )

        # Prefill last approved-PO rate/date/supplier per item (snapshot).
        last_po_map: dict[int, dict] = {}
        co_id = state.get("co_id")
        item_ids = sorted({row["item_id"] for row in pc_rows})
        if co_id is not None and item_ids:
            for row in db.execute(
                get_last_purchase_rates_by_item_ids(),
                {"item_ids": item_ids, "co_id": int(co_id)},
            ).fetchall():
                mapped = dict(row._mapping)
                last_po_map[int(mapped["item_id"])] = mapped

        created_at = now_ist()
        result = db.execute(insert_enquiry_price_check(), {
            "sales_enquiry_id": sales_enquiry_id,
            "request_note": request_note,
            "pc_status": PC_STATUS_PENDING,
            "requested_by": user_id,
            "requested_date_time": created_at,
            "updated_by": user_id,
            "updated_date_time": created_at,
        })
        price_check_id = result.lastrowid
        if not price_check_id:
            raise HTTPException(status_code=500, detail="Failed to create price check header")

        dtl_query = insert_enquiry_price_check_dtl()
        for row in pc_rows:
            last_po = last_po_map.get(row["item_id"], {})
            db.execute(dtl_query, {
                "price_check_id": price_check_id,
                "enquiry_dtl_id": row["enquiry_dtl_id"],
                "item_id": row["item_id"],
                "last_po_rate": last_po.get("last_po_rate"),
                "last_po_date": last_po.get("last_po_date"),
                "last_supplier_id": last_po.get("last_supplier_id"),
                "remarks": row["remarks"],
            })

        # Stage COSTING_REVIEW -> PRICE_CHECK, same transaction.
        log_stage_transition(
            db,
            sales_enquiry_id=sales_enquiry_id,
            from_stage_id=state.get("current_stage_id"),
            to_stage_code=STAGE_PRICE_CHECK,
            action=ACTION_FORWARD,
            feedback=request_note or "Price check requested",
            linked_doc_type=LINKED_DOC_PRICE_CHECK,
            linked_doc_id=price_check_id,
            user_id=user_id,
        )

        db.commit()
        return {
            "data": {"price_check_id": price_check_id, "sales_enquiry_id": sales_enquiry_id},
            "message": "Price check created successfully",
            "stage_code": STAGE_PRICE_CHECK,
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error creating price check")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_price_check_pending_list")
def get_price_check_pending_list(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Procurement worklist — price checks by status (default: pending)."""
    try:
        qp = request.query_params
        co_id = to_int(qp.get("co_id"), "co_id", required=True)
        branch_id = to_int(qp.get("branch_id"), "branch_id")
        pc_status = qp.get("pc_status") or PC_STATUS_PENDING
        pc_status = str(pc_status).strip().lower()
        if pc_status == "all":
            pc_status = None
        elif pc_status not in PRICE_CHECK_STATUSES:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid pc_status. Allowed: {', '.join(PRICE_CHECK_STATUSES)} or 'all'",
            )

        rows = db.execute(get_price_check_list_query(), {
            "co_id": co_id,
            "branch_id": branch_id,
            "pc_status": pc_status,
        }).fetchall()

        data = []
        for row in rows:
            mapped = dict(row._mapping)
            mapped["enquiry_no_raw"] = mapped.get("enquiry_no")
            # List query carries no prefixes — show the raw number as-is.
            mapped["enquiry_date"] = format_date(mapped.get("enquiry_date"))
            data.append(mapped)

        return {"data": data}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_price_check_by_id")
def get_price_check_by_id(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """One price check with its detail rows (incl. the last-PO prefill snapshot)."""
    try:
        qp = request.query_params
        price_check_id = to_int(qp.get("price_check_id"), "price_check_id", required=True)

        header_row = db.execute(
            get_price_check_by_id_query(), {"price_check_id": price_check_id}
        ).fetchone()
        if not header_row:
            raise HTTPException(status_code=404, detail="Price check not found")
        header = dict(header_row._mapping)
        header["enquiry_date"] = format_date(header.get("enquiry_date"))

        dtl_rows = db.execute(
            get_price_check_dtl_query(), {"price_check_id": price_check_id}
        ).fetchall()
        lines = []
        for row in dtl_rows:
            mapped = dict(row._mapping)
            mapped["last_po_date"] = format_date(mapped.get("last_po_date"))
            lines.append(mapped)

        return {"data": {**header, "lines": lines}}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/respond_price_check")
def respond_price_check(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Procurement answers a price check: {price_check_id, response_note?,
    items: [{price_check_dtl_id, confirmed_rate?, rate_source?, supplier_id?,
    remarks?}]}.

    Writes the confirmed rates, marks the header responded, and moves the
    enquiry back PRICE_CHECK -> COSTING_REVIEW with the response note as
    feedback — one transaction. If the enquiry has meanwhile moved past
    PRICE_CHECK (or is on hold), the response is still recorded and a
    stage-preserving AUTO entry keeps the feedback trail intact."""
    try:
        body = parse_json_body(request)
        price_check_id = to_int(body.get("price_check_id"), "price_check_id", required=True)
        response_note = clip_str(body.get("response_note"), 500)
        user_id = int(token_data.get("user_id"))

        raw_items = body.get("items")
        if not isinstance(raw_items, list) or len(raw_items) == 0:
            raise HTTPException(status_code=400, detail="At least one item row is required")

        pc_row = db.execute(
            get_price_check_state_query(), {"price_check_id": price_check_id}
        ).fetchone()
        if not pc_row:
            raise HTTPException(status_code=404, detail="Price check not found")
        pc = dict(pc_row._mapping)
        if pc.get("pc_status") != PC_STATUS_PENDING:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot respond to a price check with status '{pc.get('pc_status')}'. Expected 'pending'.",
            )
        sales_enquiry_id = int(pc["sales_enquiry_id"])

        valid_dtl_ids = {
            int(dict(r._mapping)["price_check_dtl_id"])
            for r in db.execute(
                get_price_check_dtl_ids_query(), {"price_check_id": price_check_id}
            ).fetchall()
        }

        normalized_items = []
        for idx, item in enumerate(raw_items, start=1):
            if not isinstance(item, dict):
                raise HTTPException(status_code=400, detail=f"Invalid item at position {idx}")
            price_check_dtl_id = to_int(
                item.get("price_check_dtl_id"), f"items[{idx}].price_check_dtl_id", required=True
            )
            if price_check_dtl_id not in valid_dtl_ids:
                raise HTTPException(
                    status_code=400,
                    detail=f"items[{idx}]: price_check_dtl_id {price_check_dtl_id} does not belong to this price check",
                )
            rate_source = item.get("rate_source") or None
            if rate_source is not None:
                rate_source = str(rate_source).strip().lower()
                if rate_source not in RATE_SOURCES:
                    raise HTTPException(
                        status_code=400,
                        detail=f"items[{idx}]: invalid rate_source. Allowed: {', '.join(RATE_SOURCES)}",
                    )
            normalized_items.append({
                "price_check_dtl_id": price_check_dtl_id,
                "confirmed_rate": to_float(item.get("confirmed_rate"), f"items[{idx}].confirmed_rate"),
                "rate_source": rate_source,
                "supplier_id": to_int(item.get("supplier_id"), f"items[{idx}].supplier_id"),
                "remarks": clip_str(item.get("remarks"), 500),
            })

        responded_at = now_ist()
        dtl_query = update_price_check_dtl_response()
        for item in normalized_items:
            db.execute(dtl_query, {**item, "price_check_id": price_check_id})

        db.execute(update_price_check_response(), {
            "price_check_id": price_check_id,
            "pc_status": PC_STATUS_RESPONDED,
            "responded_by": user_id,
            "responded_date_time": responded_at,
            "response_note": response_note,
            "updated_by": user_id,
            "updated_date_time": responded_at,
        })

        # Return leg: PRICE_CHECK -> COSTING_REVIEW with the response note as
        # feedback. If the enquiry moved on (or is held), keep the feedback via
        # a stage-preserving AUTO entry instead of forcing a backward move.
        state = fetch_enquiry_flow_state(db, sales_enquiry_id)
        current_stage_code = state.get("stage_code")
        feedback = response_note or "Price check responded"
        result_stage_code = current_stage_code

        if current_stage_code == STAGE_PRICE_CHECK and int(state.get("hold_flag") or 0) == 0:
            validate_transition(
                current_stage_code=current_stage_code,
                action=ACTION_FORWARD,
                to_stage_code=STAGE_COSTING_REVIEW,
                enquiry_status_id=state.get("status_id"),
                feedback=feedback,
            )
            log_stage_transition(
                db,
                sales_enquiry_id=sales_enquiry_id,
                from_stage_id=state.get("current_stage_id"),
                to_stage_code=STAGE_COSTING_REVIEW,
                action=ACTION_FORWARD,
                feedback=feedback,
                linked_doc_type=LINKED_DOC_PRICE_CHECK,
                linked_doc_id=price_check_id,
                user_id=user_id,
            )
            result_stage_code = STAGE_COSTING_REVIEW
        elif current_stage_code and current_stage_code not in TERMINAL_STAGES:
            log_stage_transition(
                db,
                sales_enquiry_id=sales_enquiry_id,
                from_stage_id=state.get("current_stage_id"),
                to_stage_code=current_stage_code,
                action=ACTION_AUTO,
                feedback=feedback,
                linked_doc_type=LINKED_DOC_PRICE_CHECK,
                linked_doc_id=price_check_id,
                user_id=user_id,
            )

        db.commit()
        return {
            "data": {"price_check_id": price_check_id, "sales_enquiry_id": sales_enquiry_id},
            "message": "Price check responded successfully",
            "stage_code": result_stage_code,
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error responding to price check")
        raise HTTPException(status_code=500, detail=str(e))
