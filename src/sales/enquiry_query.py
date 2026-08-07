"""
SQL query builders for the sales-enquiry (AMCL enquiry-to-delivery) module.

Covers: enquiry list + flow board, enquiry header/lines/timeline, price checks
(with last-PO-rate prefill), ISO document-number lookup, linked-doc summary,
document numbering, and the small statements used by the stage-engine hooks
in src/sales/enquiry_hooks.py.

Table/column names per docs/amcl-enquiry-flow-design.md §5.1 and
dbqueries/migrations/create_amcl_enquiry_flow_phase1.sql.

All functions return sqlalchemy text() objects with named binds; callers pass
parameters at execute time (None for SQL NULL, values type-cast).
"""

from sqlalchemy import bindparam
from sqlalchemy.sql import text


# =============================================================================
# ENQUIRY LIST / TABLE
# =============================================================================

def get_enquiry_table_query():
    """Paginated enquiry list with stage / status / party / date / search filters.

    Binds: :co_id, :branch_id, :stage_id, :status_id, :party_id,
           :from_date, :to_date, :search_like, :limit, :offset
    (any filter bind may be None to skip that filter).
    """
    sql = """SELECT
        se.sales_enquiry_id,
        se.enquiry_no,
        se.enquiry_date,
        se.received_via,
        se.branch_id,
        bm.branch_name,
        bm.branch_prefix,
        bm.co_id,
        cm.co_prefix,
        se.party_id,
        pm.supp_name AS party_name,
        se.contact_person,
        se.customer_ref_no,
        se.expected_delivery_date,
        se.current_stage_id,
        fsm.stage_code,
        fsm.stage_name,
        fsm.dept_hint,
        fsm.sequence_no,
        se.stage_since,
        DATEDIFF(NOW(), se.stage_since) AS days_in_stage,
        se.hold_flag,
        se.status_id,
        sm.status_name,
        se.close_reason,
        se.project_id
    FROM sales_enquiry AS se
    LEFT JOIN branch_mst AS bm ON bm.branch_id = se.branch_id
    LEFT JOIN co_mst AS cm ON cm.co_id = bm.co_id
    LEFT JOIN party_mst AS pm ON pm.party_id = se.party_id
    LEFT JOIN flow_stage_mst AS fsm ON fsm.stage_id = se.current_stage_id
    LEFT JOIN status_mst AS sm ON sm.status_id = se.status_id
    WHERE se.active = 1
        AND (:co_id IS NULL OR bm.co_id = :co_id)
        AND (:branch_id IS NULL OR se.branch_id = :branch_id)
        AND (:stage_id IS NULL OR se.current_stage_id = :stage_id)
        AND (:status_id IS NULL OR se.status_id = :status_id)
        AND (:party_id IS NULL OR se.party_id = :party_id)
        AND (:from_date IS NULL OR se.enquiry_date >= :from_date)
        AND (:to_date IS NULL OR se.enquiry_date <= :to_date)
        AND (
            :search_like IS NULL
            OR se.enquiry_no LIKE :search_like
            OR pm.supp_name LIKE :search_like
            OR se.customer_ref_no LIKE :search_like
            OR se.enquiry_desc LIKE :search_like
        )
    ORDER BY se.enquiry_date DESC, se.sales_enquiry_id DESC
    LIMIT :limit OFFSET :offset;"""
    return text(sql)


def get_enquiry_table_count_query():
    """Row count matching get_enquiry_table_query filters (same binds, no paging)."""
    sql = """SELECT COUNT(1) AS total
    FROM sales_enquiry AS se
    LEFT JOIN branch_mst AS bm ON bm.branch_id = se.branch_id
    LEFT JOIN party_mst AS pm ON pm.party_id = se.party_id
    WHERE se.active = 1
        AND (:co_id IS NULL OR bm.co_id = :co_id)
        AND (:branch_id IS NULL OR se.branch_id = :branch_id)
        AND (:stage_id IS NULL OR se.current_stage_id = :stage_id)
        AND (:status_id IS NULL OR se.status_id = :status_id)
        AND (:party_id IS NULL OR se.party_id = :party_id)
        AND (:from_date IS NULL OR se.enquiry_date >= :from_date)
        AND (:to_date IS NULL OR se.enquiry_date <= :to_date)
        AND (
            :search_like IS NULL
            OR se.enquiry_no LIKE :search_like
            OR pm.supp_name LIKE :search_like
            OR se.customer_ref_no LIKE :search_like
            OR se.enquiry_desc LIKE :search_like
        );"""
    return text(sql)


# =============================================================================
# FLOW BOARD
# =============================================================================

def get_enquiry_board_query():
    """Open (non-terminal-stage) enquiries for the Flow Board, ordered by stage.

    Per-card data: aging (DATEDIFF from stage_since), hold flag, latest feedback
    snippet (correlated subquery on flow_stage_log), line count.

    Binds: :co_id, :branch_id (None skips), :doc_type ('SALES_ENQUIRY').
    """
    sql = """SELECT
        se.sales_enquiry_id,
        se.enquiry_no,
        se.enquiry_date,
        se.branch_id,
        bm.branch_name,
        bm.branch_prefix,
        bm.co_id,
        cm.co_prefix,
        se.party_id,
        pm.supp_name AS party_name,
        se.customer_ref_no,
        se.expected_delivery_date,
        se.current_stage_id,
        fsm.stage_code,
        fsm.stage_name,
        fsm.dept_hint,
        fsm.sequence_no,
        se.stage_since,
        DATEDIFF(NOW(), se.stage_since) AS days_in_stage,
        se.hold_flag,
        se.status_id,
        sm.status_name,
        (
            SELECT fsl.feedback
            FROM flow_stage_log AS fsl
            WHERE fsl.doc_type = :doc_type
                AND fsl.doc_id = se.sales_enquiry_id
                AND fsl.feedback IS NOT NULL
                AND fsl.feedback <> ''
            ORDER BY fsl.stage_log_id DESC
            LIMIT 1
        ) AS latest_feedback,
        (
            SELECT COUNT(1)
            FROM sales_enquiry_dtl AS sed
            WHERE sed.sales_enquiry_id = se.sales_enquiry_id
                AND sed.active = 1
        ) AS line_count,
        (
            SELECT COUNT(1)
            FROM sales_enquiry_dtl AS sed2
            WHERE sed2.sales_enquiry_id = se.sales_enquiry_id
                AND sed2.active = 1
                AND sed2.cost_snapshot_id IS NOT NULL
                AND sed2.overhead_pct IS NOT NULL
                AND sed2.margin_pct IS NOT NULL
        ) AS costed_line_count
    FROM sales_enquiry AS se
    JOIN flow_stage_mst AS fsm ON fsm.stage_id = se.current_stage_id
    LEFT JOIN branch_mst AS bm ON bm.branch_id = se.branch_id
    LEFT JOIN co_mst AS cm ON cm.co_id = bm.co_id
    LEFT JOIN party_mst AS pm ON pm.party_id = se.party_id
    LEFT JOIN status_mst AS sm ON sm.status_id = se.status_id
    WHERE se.active = 1
        AND fsm.is_terminal = 0
        AND (:co_id IS NULL OR bm.co_id = :co_id)
        AND (:branch_id IS NULL OR se.branch_id = :branch_id)
    ORDER BY fsm.sequence_no, se.stage_since, se.sales_enquiry_id;"""
    return text(sql)


def get_enquiry_board_counts_query():
    """Per-stage enquiry + held counts for the board column headers.

    Returns every active non-terminal ENQUIRY stage (zero counts included).
    Binds: :module ('ENQUIRY'), :co_id, :branch_id (None skips).
    """
    sql = """SELECT
        fsm.stage_id,
        fsm.stage_code,
        fsm.stage_name,
        fsm.dept_hint,
        fsm.sequence_no,
        COUNT(se.sales_enquiry_id) AS enquiry_count,
        COALESCE(SUM(se.hold_flag), 0) AS held_count
    FROM flow_stage_mst AS fsm
    LEFT JOIN sales_enquiry AS se
        ON se.current_stage_id = fsm.stage_id
        AND se.active = 1
        AND (:branch_id IS NULL OR se.branch_id = :branch_id)
        AND (
            :co_id IS NULL
            OR EXISTS (
                SELECT 1 FROM branch_mst AS bm
                WHERE bm.branch_id = se.branch_id AND bm.co_id = :co_id
            )
        )
    WHERE fsm.module = :module
        AND fsm.active = 1
        AND fsm.is_terminal = 0
    GROUP BY fsm.stage_id, fsm.stage_code, fsm.stage_name, fsm.dept_hint, fsm.sequence_no
    ORDER BY fsm.sequence_no;"""
    return text(sql)


# =============================================================================
# ENQUIRY BY ID (header / lines / timeline)
# =============================================================================

def get_enquiry_by_id_query():
    """Enquiry header with party, stage, status, project and number-format prefixes.

    Binds: :sales_enquiry_id, :co_id (None skips company check).
    """
    sql = """SELECT
        se.sales_enquiry_id,
        se.enquiry_no,
        se.enquiry_date,
        se.received_via,
        se.branch_id,
        bm.branch_name,
        bm.branch_prefix,
        bm.co_id,
        cm.co_prefix,
        cm.co_name,
        se.party_id,
        pm.supp_name AS party_name,
        se.contact_person,
        se.contact_detail,
        se.customer_ref_no,
        se.expected_delivery_date,
        se.enquiry_desc,
        se.internal_note,
        se.current_stage_id,
        fsm.stage_code,
        fsm.stage_name,
        fsm.dept_hint,
        fsm.sequence_no,
        fsm.is_terminal,
        se.stage_since,
        DATEDIFF(NOW(), se.stage_since) AS days_in_stage,
        se.hold_flag,
        se.status_id,
        sm.status_name,
        se.close_reason,
        se.lost_remarks,
        se.project_id,
        prj.prj_name AS project_name,
        se.updated_by,
        se.updated_date_time,
        CASE
            WHEN se.status_id = 20 THEN se.approval_level
            ELSE NULL
        END AS approval_level
    FROM sales_enquiry AS se
    LEFT JOIN branch_mst AS bm ON bm.branch_id = se.branch_id
    LEFT JOIN co_mst AS cm ON cm.co_id = bm.co_id
    LEFT JOIN party_mst AS pm ON pm.party_id = se.party_id
    LEFT JOIN flow_stage_mst AS fsm ON fsm.stage_id = se.current_stage_id
    LEFT JOIN status_mst AS sm ON sm.status_id = se.status_id
    LEFT JOIN project_mst AS prj ON prj.project_id = se.project_id
    WHERE se.sales_enquiry_id = :sales_enquiry_id
        AND (:co_id IS NULL OR bm.co_id = :co_id);"""
    return text(sql)


def get_enquiry_dtl_by_id_query():
    """Enquiry lines with item, UOM, BOM link and confirmed cost snapshot.

    Binds: :sales_enquiry_id.
    """
    sql = """SELECT
        sed.enquiry_dtl_id,
        sed.sales_enquiry_id,
        sed.item_id,
        im.item_code,
        im.item_name,
        vip.full_item_code,
        sed.item_desc_freetext,
        sed.is_new_item,
        sed.design_change,
        sed.qty,
        sed.uom_id,
        um.uom_name,
        sed.target_price,
        sed.bom_hdr_id,
        bh.bom_version,
        bh.version_label,
        bh.is_current AS bom_is_current,
        sed.cost_snapshot_id,
        bcs.cost_per_unit AS snapshot_cost_per_unit,
        bcs.total_cost AS snapshot_total_cost,
        bcs.status AS snapshot_status,
        bcs.computed_at AS snapshot_computed_at,
        sed.confirmed_cost_per_unit,
        sed.overhead_pct,
        sed.margin_pct,
        CASE
            WHEN sed.confirmed_cost_per_unit IS NOT NULL
                 AND sed.overhead_pct IS NOT NULL
                 AND sed.margin_pct IS NOT NULL
            THEN sed.confirmed_cost_per_unit
                 * (1 + sed.overhead_pct/100)
                 * (1 + sed.margin_pct/100)
            ELSE NULL
        END AS sell_price_per_unit,
        sed.costing_confirmed_by,
        conf_u.name AS costing_confirmed_by_name,
        sed.costing_confirmed_date,
        sed.remarks
    FROM sales_enquiry_dtl AS sed
    LEFT JOIN item_mst AS im ON im.item_id = sed.item_id
    LEFT JOIN vw_item_with_group_path AS vip ON vip.item_id = sed.item_id
    LEFT JOIN uom_mst AS um ON um.uom_id = sed.uom_id
    LEFT JOIN item_bom_hdr_mst AS bh ON bh.bom_hdr_id = sed.bom_hdr_id
    LEFT JOIN bom_cost_snapshot AS bcs ON bcs.bom_cost_snapshot_id = sed.cost_snapshot_id
    LEFT JOIN user_mst AS conf_u ON conf_u.user_id = sed.costing_confirmed_by
    WHERE sed.sales_enquiry_id = :sales_enquiry_id
        AND sed.active = 1
    ORDER BY sed.enquiry_dtl_id;"""
    return text(sql)


def get_enquiry_stage_log_query():
    """Full stage-transition timeline for a document, oldest first.

    Binds: :doc_type ('SALES_ENQUIRY'), :doc_id (sales_enquiry_id).
    """
    sql = """SELECT
        fsl.stage_log_id,
        fsl.doc_type,
        fsl.doc_id,
        fsl.from_stage_id,
        f_from.stage_code AS from_stage_code,
        f_from.stage_name AS from_stage_name,
        fsl.to_stage_id,
        f_to.stage_code AS to_stage_code,
        f_to.stage_name AS to_stage_name,
        f_to.dept_hint AS to_dept_hint,
        fsl.action,
        fsl.feedback,
        fsl.linked_doc_type,
        fsl.linked_doc_id,
        fsl.action_by,
        um.name AS action_by_name,
        fsl.action_date_time
    FROM flow_stage_log AS fsl
    LEFT JOIN flow_stage_mst AS f_from ON f_from.stage_id = fsl.from_stage_id
    LEFT JOIN flow_stage_mst AS f_to ON f_to.stage_id = fsl.to_stage_id
    LEFT JOIN user_mst AS um ON um.user_id = fsl.action_by
    WHERE fsl.doc_type = :doc_type
        AND fsl.doc_id = :doc_id
    ORDER BY fsl.stage_log_id;"""
    return text(sql)


# =============================================================================
# PRICE CHECK (Design/Costing -> Procurement consult)
# =============================================================================

def get_price_check_list_query():
    """Price-check headers, newest first (procurement worklist when
    :pc_status = 'pending').

    Binds: :co_id, :branch_id, :pc_status (any may be None to skip).
    """
    sql = """SELECT
        epc.price_check_id,
        epc.sales_enquiry_id,
        se.enquiry_no,
        se.enquiry_date,
        se.branch_id,
        bm.branch_name,
        bm.co_id,
        se.party_id,
        pm.supp_name AS party_name,
        epc.request_note,
        epc.pc_status,
        epc.requested_by,
        req_u.name AS requested_by_name,
        epc.requested_date_time,
        epc.responded_by,
        resp_u.name AS responded_by_name,
        epc.responded_date_time,
        epc.response_note,
        (
            SELECT COUNT(1)
            FROM enquiry_price_check_dtl AS pcd
            WHERE pcd.price_check_id = epc.price_check_id
        ) AS line_count
    FROM enquiry_price_check AS epc
    JOIN sales_enquiry AS se ON se.sales_enquiry_id = epc.sales_enquiry_id
    LEFT JOIN branch_mst AS bm ON bm.branch_id = se.branch_id
    LEFT JOIN party_mst AS pm ON pm.party_id = se.party_id
    LEFT JOIN user_mst AS req_u ON req_u.user_id = epc.requested_by
    LEFT JOIN user_mst AS resp_u ON resp_u.user_id = epc.responded_by
    WHERE epc.active = 1
        AND (:co_id IS NULL OR bm.co_id = :co_id)
        AND (:branch_id IS NULL OR se.branch_id = :branch_id)
        AND (:pc_status IS NULL OR epc.pc_status = :pc_status)
    ORDER BY epc.price_check_id DESC;"""
    return text(sql)


def get_price_check_by_id_query():
    """Single price-check header with enquiry context. Binds: :price_check_id."""
    sql = """SELECT
        epc.price_check_id,
        epc.sales_enquiry_id,
        se.enquiry_no,
        se.enquiry_date,
        se.branch_id,
        bm.branch_name,
        bm.co_id,
        se.party_id,
        pm.supp_name AS party_name,
        se.current_stage_id,
        fsm.stage_code,
        epc.request_note,
        epc.pc_status,
        epc.requested_by,
        req_u.name AS requested_by_name,
        epc.requested_date_time,
        epc.responded_by,
        resp_u.name AS responded_by_name,
        epc.responded_date_time,
        epc.response_note,
        epc.updated_by,
        epc.updated_date_time
    FROM enquiry_price_check AS epc
    JOIN sales_enquiry AS se ON se.sales_enquiry_id = epc.sales_enquiry_id
    LEFT JOIN branch_mst AS bm ON bm.branch_id = se.branch_id
    LEFT JOIN party_mst AS pm ON pm.party_id = se.party_id
    LEFT JOIN flow_stage_mst AS fsm ON fsm.stage_id = se.current_stage_id
    LEFT JOIN user_mst AS req_u ON req_u.user_id = epc.requested_by
    LEFT JOIN user_mst AS resp_u ON resp_u.user_id = epc.responded_by
    WHERE epc.price_check_id = :price_check_id
        AND epc.active = 1;"""
    return text(sql)


def get_price_check_dtl_query():
    """Price-check detail rows with item + supplier names. Binds: :price_check_id."""
    sql = """SELECT
        pcd.price_check_dtl_id,
        pcd.price_check_id,
        pcd.enquiry_dtl_id,
        pcd.item_id,
        im.item_code,
        im.item_name,
        vip.full_item_code,
        pcd.last_po_rate,
        pcd.last_po_date,
        pcd.last_supplier_id,
        last_sup.supp_name AS last_supplier_name,
        pcd.confirmed_rate,
        pcd.rate_source,
        pcd.supplier_id,
        sup.supp_name AS supplier_name,
        pcd.remarks
    FROM enquiry_price_check_dtl AS pcd
    LEFT JOIN item_mst AS im ON im.item_id = pcd.item_id
    LEFT JOIN vw_item_with_group_path AS vip ON vip.item_id = pcd.item_id
    LEFT JOIN party_mst AS last_sup ON last_sup.party_id = pcd.last_supplier_id
    LEFT JOIN party_mst AS sup ON sup.party_id = pcd.supplier_id
    WHERE pcd.price_check_id = :price_check_id
    ORDER BY pcd.price_check_dtl_id;"""
    return text(sql)


def get_last_purchase_rates_by_item_ids():
    """Last approved-PO rate/date/supplier per item for an explicit item-id list.

    Item-id-list variant of src/procurement/query.py::
    get_last_purchase_rates_by_item_group (kept here so procurement is not
    touched). Feeds the price-check prefill snapshot
    (enquiry_price_check_dtl.last_po_rate / last_po_date / last_supplier_id).

    Binds: :item_ids (expanding list), :co_id.
    """
    sql = """SELECT ranked.item_id, ranked.last_po_rate,
           ranked.last_po_date, ranked.last_supplier_id, ranked.last_supplier_name
    FROM (
        SELECT ppd.item_id,
               ppd.rate AS last_po_rate,
               pp.po_date AS last_po_date,
               pp.supplier_id AS last_supplier_id,
               pm.supp_name AS last_supplier_name,
               ROW_NUMBER() OVER (
                   PARTITION BY ppd.item_id
                   ORDER BY pp.po_date DESC, pp.po_id DESC
               ) AS rn
        FROM proc_po_dtl ppd
        JOIN proc_po pp ON pp.po_id = ppd.po_id
        JOIN branch_mst bm ON bm.branch_id = pp.branch_id
        LEFT JOIN party_mst pm ON pm.party_id = pp.supplier_id
        WHERE ppd.item_id IN :item_ids
          AND pp.status_id = 3
          AND ppd.active = 1
          AND bm.co_id = :co_id
    ) ranked
    WHERE ranked.rn = 1;"""
    return text(sql).bindparams(bindparam("item_ids", expanding=True))


# =============================================================================
# ISO DOCUMENT NUMBER LOOKUP (co_menu_iso_map — decision Q2/Q7)
# =============================================================================

def get_iso_doc_no_query():
    """ISO document number for a (company, menu/document-type) pair.

    Returns at most one row (unique (co_id, menu_id)); the caller renders
    iso_doc_no when a row exists and leaves the space blank otherwise.

    Binds: :co_id, :menu_id.
    """
    sql = """SELECT
        cim.iso_map_id,
        cim.co_id,
        cim.menu_id,
        cim.iso_doc_no
    FROM co_menu_iso_map AS cim
    WHERE cim.co_id = :co_id
        AND cim.menu_id = :menu_id
        AND cim.active = 1;"""
    return text(sql)


# =============================================================================
# LINKED DOCUMENTS SUMMARY
# =============================================================================

def get_enquiry_linked_docs_query():
    """Quotations and sales orders traced to an enquiry.

    Quotations link via sales_quotation.sales_enquiry_id; sales orders link
    via sales_order.sales_enquiry_id (direct/tender path, decision Q3) OR via
    their quotation's sales_enquiry_id.

    Binds: :sales_enquiry_id.
    """
    sql = """SELECT
        'QUOTATION' AS doc_type,
        sq.sales_quotation_id AS doc_id,
        sq.quotation_no AS doc_no,
        sq.quotation_date AS doc_date,
        sq.status_id,
        sm.status_name,
        sq.net_amount
    FROM sales_quotation AS sq
    LEFT JOIN status_mst AS sm ON sm.status_id = sq.status_id
    WHERE sq.sales_enquiry_id = :sales_enquiry_id
        AND sq.active = 1
    UNION ALL
    SELECT
        'SALES_ORDER' AS doc_type,
        so.sales_order_id AS doc_id,
        so.sales_no AS doc_no,
        so.sales_order_date AS doc_date,
        so.status_id,
        sm.status_name,
        so.net_amount
    FROM sales_order AS so
    LEFT JOIN sales_quotation AS soq ON soq.sales_quotation_id = so.quotation_id
    LEFT JOIN status_mst AS sm ON sm.status_id = so.status_id
    WHERE so.active = 1
        AND (
            so.sales_enquiry_id = :sales_enquiry_id
            OR soq.sales_enquiry_id = :sales_enquiry_id
        )
    ORDER BY doc_type, doc_id;"""
    return text(sql)


# =============================================================================
# DOCUMENT NUMBERING / WORKFLOW STATE
# =============================================================================

def get_max_enquiry_no_for_branch_fy():
    """Max numeric enquiry_no for a branch within a financial year (numbering
    mirrors get_max_quotation_no_for_branch_fy — prefix ENQ applied at format
    time via format_indent_no + SALES_DOC_TYPES['ENQUIRY']).

    Binds: :branch_id, :fy_start_date, :fy_end_date.
    """
    sql = """SELECT COALESCE(MAX(CAST(se.enquiry_no AS UNSIGNED)), 0) AS max_doc_no
    FROM sales_enquiry se
    WHERE se.branch_id = :branch_id
        AND se.enquiry_date >= :fy_start_date
        AND se.enquiry_date <= :fy_end_date
        AND se.enquiry_no IS NOT NULL;"""
    return text(sql)


def get_enquiry_flow_state_query():
    """Workflow + stage state for one enquiry (approval endpoints, move_stage,
    and the stage-engine hooks). Binds: :sales_enquiry_id."""
    sql = """SELECT
        se.sales_enquiry_id,
        se.enquiry_no,
        se.enquiry_date,
        se.branch_id,
        bm.co_id,
        se.party_id,
        se.status_id,
        se.approval_level,
        se.current_stage_id,
        fsm.stage_code,
        fsm.sequence_no,
        fsm.is_terminal,
        se.stage_since,
        se.hold_flag,
        se.close_reason,
        se.project_id,
        se.active
    FROM sales_enquiry se
    LEFT JOIN branch_mst bm ON bm.branch_id = se.branch_id
    LEFT JOIN flow_stage_mst fsm ON fsm.stage_id = se.current_stage_id
    WHERE se.sales_enquiry_id = :sales_enquiry_id;"""
    return text(sql)


def get_enquiry_costing_pending_query():
    """Active enquiry lines NOT fully costed+priced (block Costing Complete).

    A line is done when cost_snapshot_id, overhead_pct and margin_pct are all
    set. Free-text/new-item lines (item_id IS NULL) can never be costed, so
    they are pending too. Binds: :sales_enquiry_id."""
    sql = """SELECT sed.enquiry_dtl_id, sed.item_id
    FROM sales_enquiry_dtl AS sed
    WHERE sed.sales_enquiry_id = :sales_enquiry_id
        AND sed.active = 1
        AND (
            sed.item_id IS NULL
            OR sed.cost_snapshot_id IS NULL
            OR sed.overhead_pct IS NULL
            OR sed.margin_pct IS NULL
        )
    ORDER BY sed.enquiry_dtl_id;"""
    return text(sql)


# =============================================================================
# STAGE MASTER LOOKUPS (used by hooks + /get_enquiry_setup)
# =============================================================================

def get_stage_by_code_query():
    """Stage master row by (module, stage_code). Binds: :module, :stage_code."""
    sql = """SELECT
        fsm.stage_id,
        fsm.stage_code,
        fsm.stage_name,
        fsm.dept_hint,
        fsm.sequence_no,
        fsm.is_terminal
    FROM flow_stage_mst fsm
    WHERE fsm.module = :module
        AND fsm.stage_code = :stage_code
        AND fsm.active = 1;"""
    return text(sql)


def get_stage_by_id_query():
    """Stage master row by stage_id. Binds: :stage_id."""
    sql = """SELECT
        fsm.stage_id,
        fsm.module,
        fsm.stage_code,
        fsm.stage_name,
        fsm.dept_hint,
        fsm.sequence_no,
        fsm.is_terminal
    FROM flow_stage_mst fsm
    WHERE fsm.stage_id = :stage_id;"""
    return text(sql)


def get_stages_by_module_query():
    """All active stages for a module, in sequence order. Binds: :module."""
    sql = """SELECT
        fsm.stage_id,
        fsm.stage_code,
        fsm.stage_name,
        fsm.dept_hint,
        fsm.sequence_no,
        fsm.is_terminal
    FROM flow_stage_mst fsm
    WHERE fsm.module = :module
        AND fsm.active = 1
    ORDER BY fsm.sequence_no;"""
    return text(sql)


# =============================================================================
# STAGE-ENGINE WRITE STATEMENTS (used by src/sales/enquiry_hooks.py)
# =============================================================================

def insert_flow_stage_log():
    """INSERT one flow_stage_log entry.

    Binds: :doc_type, :doc_id, :from_stage_id, :to_stage_id, :action,
           :feedback, :linked_doc_type, :linked_doc_id, :action_by,
           :action_date_time.
    """
    sql = """INSERT INTO flow_stage_log (
        doc_type, doc_id, from_stage_id, to_stage_id,
        action, feedback, linked_doc_type, linked_doc_id,
        action_by, action_date_time
    ) VALUES (
        :doc_type, :doc_id, :from_stage_id, :to_stage_id,
        :action, :feedback, :linked_doc_type, :linked_doc_id,
        :action_by, :action_date_time
    );"""
    return text(sql)


def update_enquiry_current_stage():
    """UPDATE the denormalized stage pointer + aging anchor on the header.

    Binds: :sales_enquiry_id, :current_stage_id, :stage_since,
           :updated_by, :updated_date_time.
    """
    sql = """UPDATE sales_enquiry SET
        current_stage_id = :current_stage_id,
        stage_since = :stage_since,
        updated_by = :updated_by,
        updated_date_time = :updated_date_time
    WHERE sales_enquiry_id = :sales_enquiry_id;"""
    return text(sql)


# =============================================================================
# CANONICAL MENU LOOKUP (approval permission checks)
# =============================================================================

def get_menu_id_by_path_query():
    """Canonical menu_id for a portal page path (menu_mst.menu_path).
    Binds: :menu_path."""
    sql = """SELECT menu_id
    FROM menu_mst
    WHERE menu_path = :menu_path
        AND active = 1
    ORDER BY menu_id
    LIMIT 1;"""
    return text(sql)


# =============================================================================
# AUTO-TRANSITION LINK LOOKUPS (quotation / sales-order approval hooks)
# =============================================================================

def get_quotation_enquiry_link_query():
    """Enquiry linked to a quotation. Binds: :sales_quotation_id."""
    sql = """SELECT
        sq.sales_quotation_id,
        sq.sales_enquiry_id
    FROM sales_quotation sq
    WHERE sq.sales_quotation_id = :sales_quotation_id;"""
    return text(sql)


def get_sales_order_enquiry_link_query():
    """Enquiry linked to a sales order — directly (tender path) or via its
    quotation. Binds: :sales_order_id."""
    sql = """SELECT
        so.sales_order_id,
        so.sales_enquiry_id,
        sq.sales_enquiry_id AS quotation_sales_enquiry_id
    FROM sales_order so
    LEFT JOIN sales_quotation sq ON sq.sales_quotation_id = so.quotation_id
    WHERE so.sales_order_id = :sales_order_id;"""
    return text(sql)
