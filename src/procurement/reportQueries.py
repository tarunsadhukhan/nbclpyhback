"""
Procurement Report Queries.
Contains SQL queries for procurement reports (item-wise indent report, etc.).
"""

from sqlalchemy import text


def get_indent_itemwise_report_query():
    """
    Item-wise indent report query.

    Returns one row per indent detail line with outstanding tracking.
    Joins proc_indent + proc_indent_dtl + outstanding view + master tables.

    Parameters:
        :co_id (int) - required
        :branch_id (int or NULL) - optional branch filter
        :date_from (str or NULL) - date range start (YYYY-MM-DD)
        :date_to (str or NULL) - date range end (YYYY-MM-DD)
        :indent_type (str or NULL) - 'Regular', 'Open', 'BOM', or NULL for all
        :outstanding_filter (str or NULL) - 'outstanding', 'non_outstanding', or NULL for all
        :search_like (str or NULL) - LIKE pattern for item_name, branch_name
        :limit (int) - pagination limit
        :offset (int) - pagination offset
    """
    sql = """
    SELECT
        pid.indent_dtl_id,
        pi.indent_id,
        pi.indent_no,
        pi.indent_date,
        bm.branch_name,
        bm.branch_prefix,
        cm.co_prefix,
        im.item_name,
        igm.item_grp_name,
        um.uom_name,
        pid.qty AS indent_qty,
        COALESCE(oi.bal_ind_qty, 0) AS outstanding_qty,
        pid.qty - COALESCE(oi.bal_ind_qty, 0) AS po_consumed_qty,
        pi.indent_type_id,
        etm.expense_type_name,
        sm.status_name
    FROM proc_indent AS pi
    INNER JOIN proc_indent_dtl AS pid ON pid.indent_id = pi.indent_id
    LEFT JOIN branch_mst AS bm ON bm.branch_id = pi.branch_id
    LEFT JOIN co_mst AS cm ON cm.co_id = bm.co_id
    LEFT JOIN item_mst AS im ON im.item_id = pid.item_id
    LEFT JOIN item_grp_mst AS igm ON igm.item_grp_id = im.item_grp_id
    LEFT JOIN uom_mst AS um ON um.uom_id = pid.uom_id
    LEFT JOIN expense_type_mst AS etm ON etm.expense_type_id = pi.expense_type_id
    LEFT JOIN status_mst AS sm ON sm.status_id = pi.status_id
    LEFT JOIN vw_proc_indent_outstanding_new oi ON oi.indent_dtl_id = pid.indent_dtl_id
    WHERE pi.active = 1
        AND pid.active = 1
        AND bm.co_id = :co_id
        AND pi.status_id IN (1, 3, 5, 20)
        AND (:status_id IS NULL OR pi.status_id = :status_id)
        AND (:branch_id IS NULL OR pi.branch_id = :branch_id)
        AND (:date_from IS NULL OR pi.indent_date >= :date_from)
        AND (:date_to IS NULL OR pi.indent_date <= :date_to)
        AND (:indent_type IS NULL OR pi.indent_type_id = :indent_type)
        AND (
            :outstanding_filter IS NULL
            OR (:outstanding_filter = 'outstanding' AND COALESCE(oi.bal_ind_qty, 0) > 0)
            OR (:outstanding_filter = 'non_outstanding' AND COALESCE(oi.bal_ind_qty, 0) <= 0)
        )
        AND (
            :search_like IS NULL
            OR im.item_name LIKE :search_like
            OR bm.branch_name LIKE :search_like
            OR igm.item_grp_name LIKE :search_like
        )
    ORDER BY pi.indent_date DESC, pi.indent_id DESC, pid.indent_dtl_id
    LIMIT :limit OFFSET :offset;
    """
    return text(sql)


def get_indent_itemwise_report_count_query():
    """
    Count query for item-wise indent report pagination.
    Same joins and filters as the data query, returns total count.
    """
    sql = """
    SELECT COUNT(1) AS total
    FROM proc_indent AS pi
    INNER JOIN proc_indent_dtl AS pid ON pid.indent_id = pi.indent_id
    LEFT JOIN branch_mst AS bm ON bm.branch_id = pi.branch_id
    LEFT JOIN item_mst AS im ON im.item_id = pid.item_id
    LEFT JOIN item_grp_mst AS igm ON igm.item_grp_id = im.item_grp_id
    LEFT JOIN expense_type_mst AS etm ON etm.expense_type_id = pi.expense_type_id
    LEFT JOIN vw_proc_indent_outstanding_new oi ON oi.indent_dtl_id = pid.indent_dtl_id
    WHERE pi.active = 1
        AND pid.active = 1
        AND bm.co_id = :co_id
        AND pi.status_id IN (1, 3, 5, 20)
        AND (:status_id IS NULL OR pi.status_id = :status_id)
        AND (:branch_id IS NULL OR pi.branch_id = :branch_id)
        AND (:date_from IS NULL OR pi.indent_date >= :date_from)
        AND (:date_to IS NULL OR pi.indent_date <= :date_to)
        AND (:indent_type IS NULL OR pi.indent_type_id = :indent_type)
        AND (
            :outstanding_filter IS NULL
            OR (:outstanding_filter = 'outstanding' AND COALESCE(oi.bal_ind_qty, 0) > 0)
            OR (:outstanding_filter = 'non_outstanding' AND COALESCE(oi.bal_ind_qty, 0) <= 0)
        )
        AND (
            :search_like IS NULL
            OR im.item_name LIKE :search_like
            OR bm.branch_name LIKE :search_like
            OR igm.item_grp_name LIKE :search_like
        );
    """
    return text(sql)


def get_po_itemwise_report_query():
    """
    Item-wise PO report query.

    Returns one row per PO detail line with outstanding tracking.
    Joins proc_po + proc_po_dtl + outstanding view + master tables.

    Parameters:
        :co_id (int) - required
        :branch_id (int or NULL) - optional branch filter
        :date_from (str or NULL) - date range start (YYYY-MM-DD)
        :date_to (str or NULL) - date range end (YYYY-MM-DD)
        :po_type (str or NULL) - 'Regular', 'Open', or NULL for all
        :outstanding_filter (str or NULL) - 'outstanding', 'non_outstanding', or NULL for all
        :search_like (str or NULL) - LIKE pattern for item_name, branch_name, supplier_name
        :limit (int) - pagination limit
        :offset (int) - pagination offset
    """
    sql = """
    SELECT
        ppd.po_dtl_id,
        pp.po_id,
        pp.po_no,
        pp.po_date,
        bm.branch_name,
        bm.branch_prefix,
        cm.co_prefix,
        pm.supp_name AS supplier_name,
        im.item_name,
        igm.item_grp_name,
        um.uom_name,
        ppd.qty AS po_qty,
        ppd.rate,
        ppd.qty - COALESCE(opo.bal_po_qty, 0) AS inward_consumed_qty,
        COALESCE(opo.bal_po_qty, 0) AS outstanding_qty,
        pp.po_type,
        etm.expense_type_name,
        sm.status_name
    FROM proc_po AS pp
    INNER JOIN proc_po_dtl AS ppd ON ppd.po_id = pp.po_id
    LEFT JOIN branch_mst AS bm ON bm.branch_id = pp.branch_id
    LEFT JOIN co_mst AS cm ON cm.co_id = bm.co_id
    LEFT JOIN party_mst AS pm ON pm.party_id = pp.supplier_id
    LEFT JOIN item_mst AS im ON im.item_id = ppd.item_id
    LEFT JOIN item_grp_mst AS igm ON igm.item_grp_id = im.item_grp_id
    LEFT JOIN uom_mst AS um ON um.uom_id = ppd.uom_id
    LEFT JOIN expense_type_mst AS etm ON etm.expense_type_id = pp.expense_type_id
    LEFT JOIN status_mst AS sm ON sm.status_id = pp.status_id
    LEFT JOIN vw_proc_po_outstanding_new opo ON opo.po_dtl_id = ppd.po_dtl_id
    WHERE ppd.active = 1
        AND bm.co_id = :co_id
        AND pp.status_id IN (1, 3, 5, 20)
        AND (:branch_id IS NULL OR pp.branch_id = :branch_id)
        AND (:date_from IS NULL OR pp.po_date >= :date_from)
        AND (:date_to IS NULL OR pp.po_date <= :date_to)
        AND (:po_type IS NULL OR pp.po_type = :po_type)
        AND (
            :outstanding_filter IS NULL
            OR (:outstanding_filter = 'outstanding' AND COALESCE(opo.bal_po_qty, 0) > 0)
            OR (:outstanding_filter = 'non_outstanding' AND COALESCE(opo.bal_po_qty, 0) <= 0)
        )
        AND (
            :search_like IS NULL
            OR im.item_name LIKE :search_like
            OR bm.branch_name LIKE :search_like
            OR igm.item_grp_name LIKE :search_like
            OR pm.supp_name LIKE :search_like
        )
    ORDER BY pp.po_date DESC, pp.po_id DESC, ppd.po_dtl_id
    LIMIT :limit OFFSET :offset;
    """
    return text(sql)


def get_po_itemwise_report_count_query():
    """
    Count query for item-wise PO report pagination.
    Same joins and filters as the data query, returns total count.
    """
    sql = """
    SELECT COUNT(1) AS total
    FROM proc_po AS pp
    INNER JOIN proc_po_dtl AS ppd ON ppd.po_id = pp.po_id
    LEFT JOIN branch_mst AS bm ON bm.branch_id = pp.branch_id
    LEFT JOIN party_mst AS pm ON pm.party_id = pp.supplier_id
    LEFT JOIN item_mst AS im ON im.item_id = ppd.item_id
    LEFT JOIN item_grp_mst AS igm ON igm.item_grp_id = im.item_grp_id
    LEFT JOIN expense_type_mst AS etm ON etm.expense_type_id = pp.expense_type_id
    LEFT JOIN vw_proc_po_outstanding_new opo ON opo.po_dtl_id = ppd.po_dtl_id
    WHERE ppd.active = 1
        AND bm.co_id = :co_id
        AND pp.status_id IN (1, 3, 5, 20)
        AND (:branch_id IS NULL OR pp.branch_id = :branch_id)
        AND (:date_from IS NULL OR pp.po_date >= :date_from)
        AND (:date_to IS NULL OR pp.po_date <= :date_to)
        AND (:po_type IS NULL OR pp.po_type = :po_type)
        AND (
            :outstanding_filter IS NULL
            OR (:outstanding_filter = 'outstanding' AND COALESCE(opo.bal_po_qty, 0) > 0)
            OR (:outstanding_filter = 'non_outstanding' AND COALESCE(opo.bal_po_qty, 0) <= 0)
        )
        AND (
            :search_like IS NULL
            OR im.item_name LIKE :search_like
            OR bm.branch_name LIKE :search_like
            OR igm.item_grp_name LIKE :search_like
            OR pm.supp_name LIKE :search_like
        );
    """
    return text(sql)


def get_sr_itemwise_report_query():
    """
    Item-wise SR report query.

    Returns one row per inward detail line with SR header info,
    item details, and quantities.

    Parameters:
        :co_id (int) - required
        :branch_id (int or NULL) - optional branch filter
        :date_from (str or NULL) - date range start (YYYY-MM-DD)
        :date_to (str or NULL) - date range end (YYYY-MM-DD)
        :search_like (str or NULL) - LIKE pattern for item_name, branch_name, supplier_name
        :limit (int) - pagination limit
        :offset (int) - pagination offset
    """
    sql = """
    SELECT
        pid.inward_dtl_id,
        pi.inward_id,
        pi.inward_sequence_no,
        pi.inward_date,
        bm.branch_name,
        bm.branch_prefix,
        cm.co_prefix,
        pm.supp_name AS supplier_name,
        im.item_name,
        igm.item_grp_name,
        um.uom_name,
        pid.approved_qty,
        pid.rejected_qty,
        pid.accepted_rate AS rate,
        pid.amount,
        sm.status_name
    FROM proc_inward AS pi
    INNER JOIN proc_inward_dtl AS pid ON pid.inward_id = pi.inward_id
    LEFT JOIN branch_mst AS bm ON bm.branch_id = pi.branch_id
    LEFT JOIN co_mst AS cm ON cm.co_id = bm.co_id
    LEFT JOIN party_mst AS pm ON pm.party_id = pi.supplier_id
    LEFT JOIN item_mst AS im ON im.item_id = pid.item_id
    LEFT JOIN item_grp_mst AS igm ON igm.item_grp_id = im.item_grp_id
    LEFT JOIN uom_mst AS um ON um.uom_id = pid.uom_id
    LEFT JOIN status_mst AS sm ON sm.status_id = pi.sr_status
    WHERE pid.active = 1
        AND bm.co_id = :co_id
        AND pi.sr_status IN (1, 3, 5, 20)
        AND (:branch_id IS NULL OR pi.branch_id = :branch_id)
        AND (:date_from IS NULL OR pi.inward_date >= :date_from)
        AND (:date_to IS NULL OR pi.inward_date <= :date_to)
        AND (
            :search_like IS NULL
            OR im.item_name LIKE :search_like
            OR bm.branch_name LIKE :search_like
            OR igm.item_grp_name LIKE :search_like
            OR pm.supp_name LIKE :search_like
        )
    ORDER BY pi.inward_date DESC, pi.inward_id DESC, pid.inward_dtl_id
    LIMIT :limit OFFSET :offset;
    """
    return text(sql)


def get_sr_itemwise_report_count_query():
    """
    Count query for item-wise SR report pagination.
    Same joins and filters as the data query, returns total count.
    """
    sql = """
    SELECT COUNT(1) AS total
    FROM proc_inward AS pi
    INNER JOIN proc_inward_dtl AS pid ON pid.inward_id = pi.inward_id
    LEFT JOIN branch_mst AS bm ON bm.branch_id = pi.branch_id
    LEFT JOIN party_mst AS pm ON pm.party_id = pi.supplier_id
    LEFT JOIN item_mst AS im ON im.item_id = pid.item_id
    LEFT JOIN item_grp_mst AS igm ON igm.item_grp_id = im.item_grp_id
    WHERE pid.active = 1
        AND bm.co_id = :co_id
        AND pi.sr_status IN (1, 3, 5, 20)
        AND (:branch_id IS NULL OR pi.branch_id = :branch_id)
        AND (:date_from IS NULL OR pi.inward_date >= :date_from)
        AND (:date_to IS NULL OR pi.inward_date <= :date_to)
        AND (
            :search_like IS NULL
            OR im.item_name LIKE :search_like
            OR bm.branch_name LIKE :search_like
            OR igm.item_grp_name LIKE :search_like
            OR pm.supp_name LIKE :search_like
        );
    """
    return text(sql)