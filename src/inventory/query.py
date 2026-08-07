"""
SQL queries for inventory issue module.
Based on actual database schema from 'sls' database.
"""
from sqlalchemy.sql import text


def get_issue_table_query():
    """Get paginated list of issues for the index table."""
    sql = """SELECT
        ih.issue_id,
        ih.issue_pass_no AS issue_no,
        ih.issue_pass_print_no,
        ih.issue_date,
        ih.branch_id,
        bm.branch_name,
        bm.branch_prefix,
        bm.co_id,
        cm.co_prefix,
        dm.dept_desc AS department,
        ih.issued_to,
        ih.req_by,
        ih.internal_note,
        sm.status_name AS status
    FROM issue_hdr AS ih
    LEFT JOIN branch_mst AS bm ON bm.branch_id = ih.branch_id
    LEFT JOIN co_mst AS cm ON cm.co_id = bm.co_id
    LEFT JOIN dept_mst AS dm ON dm.dept_id = ih.dept_id
    LEFT JOIN status_mst AS sm ON sm.status_id = ih.status_id
    WHERE (ih.active = 1 OR ih.active IS NULL)
        AND (:co_id IS NULL OR bm.co_id = :co_id)
        AND (
            :search_like IS NULL
            OR CAST(ih.issue_pass_no AS CHAR) LIKE :search_like
            OR ih.issue_pass_print_no LIKE :search_like
            OR bm.branch_name LIKE :search_like
            OR dm.dept_desc LIKE :search_like
            OR ih.issued_to LIKE :search_like
        )
    ORDER BY ih.issue_date DESC, ih.issue_id DESC
    LIMIT :limit OFFSET :offset;"""
    return text(sql)


def get_issue_table_count_query():
    """Get total count of issues for pagination."""
    sql = """SELECT COUNT(1) AS total
    FROM issue_hdr AS ih
    LEFT JOIN branch_mst AS bm ON bm.branch_id = ih.branch_id
    LEFT JOIN dept_mst AS dm ON dm.dept_id = ih.dept_id
    WHERE (ih.active = 1 OR ih.active IS NULL)
        AND (:co_id IS NULL OR bm.co_id = :co_id)
        AND (
            :search_like IS NULL
            OR CAST(ih.issue_pass_no AS CHAR) LIKE :search_like
            OR ih.issue_pass_print_no LIKE :search_like
            OR bm.branch_name LIKE :search_like
            OR dm.dept_desc LIKE :search_like
            OR ih.issued_to LIKE :search_like
        );"""
    return text(sql)


def get_issue_by_id_query():
    """Get issue header by ID with company and branch print-header fields."""
    sql = """SELECT
        ih.issue_id,
        ih.issue_pass_no AS issue_no,
        ih.issue_pass_print_no,
        ih.issue_date,
        ih.branch_id,
        bm.branch_name,
        bm.branch_address1,
        bm.branch_address2,
        bm.branch_zipcode,
        bm.gst_no AS branch_gst_no,
        ih.dept_id,
        dm.dept_desc AS department,
        ih.project_id,
        pm.prj_name AS project_name,
        ih.customer_id,
        ih.issued_to,
        ih.req_by,
        ih.internal_note,
        ih.status_id,
        ih.approval_level,
        sm.status_name AS status,
        ih.approved_by,
        ih.approved_date,
        ih.updated_by,
        ih.updated_date_time,
        um.name AS updated_by_name,
        cm.co_id,
        cm.co_name,
        cm.co_logo,
        cm.co_address1,
        cm.co_address2,
        cm.co_zipcode,
        cm.co_cin_no,
        cm.co_pan_no,
        cm.co_email_id
    FROM issue_hdr AS ih
    LEFT JOIN branch_mst AS bm ON bm.branch_id = ih.branch_id
    LEFT JOIN co_mst AS cm ON cm.co_id = bm.co_id
    LEFT JOIN dept_mst AS dm ON dm.dept_id = ih.dept_id
    LEFT JOIN project_mst AS pm ON pm.project_id = ih.project_id
    LEFT JOIN status_mst AS sm ON sm.status_id = ih.status_id
    LEFT JOIN user_mst AS um ON um.user_id = ih.updated_by
    WHERE ih.issue_id = :issue_id
        AND (ih.active = 1 OR ih.active IS NULL);"""
    return text(sql)


def get_issue_details_query():
    """Get issue line items by issue ID.
    Uses vw_item_with_group_path for hierarchical item group path display."""
    sql = """SELECT
        il.issue_li_id,
        il.issue_id,
        il.item_id,
        vip.item_name,
        vip.item_code,
        vip.item_grp_id,
        vip.item_group_name_display AS item_grp_name,
        vip.item_group_code_display AS item_grp_code,
        vip.full_item_code,
        il.uom_id,
        um.uom_name,
        il.req_quantity,
        il.issue_qty,
        il.expense_type_id,
        etm.expense_type_name,
        il.cost_factor_id,
        cfm.cost_factor_name,
        il.machine_id,
        mm.machine_name,
        il.inward_dtl_id,
        il.remarks,
        pi.sr_no,
        COALESCE(pid.accepted_rate, pid.rate) AS rate
    FROM issue_li AS il
    LEFT JOIN vw_item_with_group_path AS vip ON vip.item_id = il.item_id
    LEFT JOIN uom_mst AS um ON um.uom_id = il.uom_id
    LEFT JOIN expense_type_mst AS etm ON etm.expense_type_id = il.expense_type_id
    LEFT JOIN cost_factor_mst AS cfm ON cfm.cost_factor_id = il.cost_factor_id
    LEFT JOIN machine_mst AS mm ON mm.machine_id = il.machine_id
    LEFT JOIN proc_inward_dtl AS pid ON pid.inward_dtl_id = il.inward_dtl_id
    LEFT JOIN proc_inward AS pi ON pi.inward_id = pid.inward_id
    WHERE il.issue_id = :issue_id
    ORDER BY il.issue_li_id;"""
    return text(sql)


def insert_issue_hdr():
    """Insert a new issue header."""
    sql = """INSERT INTO issue_hdr (
        branch_id,
        dept_id,
        issue_pass_no,
        issue_pass_print_no,
        active,
        issue_date,
        item_id,
        status_id,
        issued_to,
        req_by,
        project_id,
        customer_id,
        internal_note,
        updated_by,
        updated_date_time
    ) VALUES (
        :branch_id,
        :dept_id,
        :issue_pass_no,
        :issue_pass_print_no,
        :active,
        :issue_date,
        :item_id,
        :status_id,
        :issued_to,
        :req_by,
        :project_id,
        :customer_id,
        :internal_note,
        :updated_by,
        :updated_date_time
    );"""
    return text(sql)


def insert_issue_li():
    """Insert a new issue line item."""
    sql = """INSERT INTO issue_li (
        issue_id,
        item_id,
        uom_id,
        req_quantity,
        issue_qty,
        expense_type_id,
        cost_factor_id,
        machine_id,
        inward_dtl_id,
        remarks,
        updated_by,
        updated_date_time
    ) VALUES (
        :issue_id,
        :item_id,
        :uom_id,
        :req_quantity,
        :issue_qty,
        :expense_type_id,
        :cost_factor_id,
        :machine_id,
        :inward_dtl_id,
        :remarks,
        :updated_by,
        :updated_date_time
    );"""
    return text(sql)


def update_issue_hdr():
    """Update an existing issue header."""
    sql = """UPDATE issue_hdr SET
        branch_id = :branch_id,
        dept_id = :dept_id,
        issue_date = :issue_date,
        issued_to = :issued_to,
        req_by = :req_by,
        project_id = :project_id,
        customer_id = :customer_id,
        internal_note = :internal_note,
        status_id = :status_id,
        updated_by = :updated_by,
        updated_date_time = :updated_date_time
    WHERE issue_id = :issue_id;"""
    return text(sql)


def delete_issue_li():
    """Delete issue line items for a given issue (before re-inserting)."""
    sql = """DELETE FROM issue_li WHERE issue_id = :issue_id;"""
    return text(sql)


def get_max_issue_pass_no_for_branch():
    """Get the maximum issue_pass_no for a branch WITHIN a financial year.

    issue_pass_no is a per-financial-year sequence (legacy behaviour carried
    over from the old system). The caller passes the FY window
    [:fy_start, :fy_end] (Indian FY: 1 Apr .. 31 Mar) derived from the new
    issue's issue_date, so the next number = MAX(this branch, this FY, active) + 1.

    Without the FY filter a stale prior-year maximum (e.g. branch 29 reaching
    8900 in FY2023-24) poisons the current year and the number jumps
    (8901 instead of 35). issue_date is DATE (no time component), so the
    inclusive <= :fy_end bound correctly includes 31 Mar.
    """
    sql = """SELECT COALESCE(MAX(ih.issue_pass_no), 0) AS max_issue_no
    FROM issue_hdr ih
    WHERE ih.branch_id = :branch_id
        AND ih.issue_date >= :fy_start
        AND ih.issue_date <= :fy_end
        AND (ih.active = 1 OR ih.active IS NULL);"""
    return text(sql)


def update_issue_status():
    """Update the status of an issue."""
    sql = """UPDATE issue_hdr SET
        status_id = :status_id,
        approval_level = :approval_level,
        approved_by = :approved_by,
        approved_date = :approved_date,
        updated_by = :updated_by,
        updated_date_time = :updated_date_time
    WHERE issue_id = :issue_id;"""
    return text(sql)


def get_available_inward_inventory_query():
    """
    Get available inventory from inward details for issuing.
    Returns items with available qty (approved_qty - already issued qty).
    Used for selecting SR line items when creating an issue.
    Uses the vw_approved_inward_qty view for approved inwards.
    Uses vw_item_with_group_path for hierarchical item group path display.

    sr_no is the stored, already-formatted SR number (co/branch/SR/FY/seq) —
    minted at SR approval, and the view only returns sr_status = 3 rows.
    """
    sql = """SELECT
        v.inward_dtl_id,
        v.inward_id,
        pi.inward_sequence_no,
        pi.sr_no,
        v.inward_date,
        v.branch_id,
        bm.branch_name,
        v.item_id,
        vip.item_name,
        vip.item_code,
        vip.item_grp_id,
        vip.item_group_name_display AS item_grp_name,
        vip.item_group_code_display AS item_grp_code,
        vip.full_item_code,
        pid.item_make_id,
        imk.item_make_name,
        v.uom_id,
        um.uom_name,
        v.approved_qty,
        v.issue_qty,
        v.balance_qty AS available_qty,
        COALESCE(pid.accepted_rate, pid.rate) AS rate,
        pid.warehouse_id,
        wm.warehouse_name
    FROM vw_approved_inward_qty AS v
    INNER JOIN proc_inward AS pi ON pi.inward_id = v.inward_id
    INNER JOIN proc_inward_dtl AS pid ON pid.inward_dtl_id = v.inward_dtl_id
    LEFT JOIN branch_mst AS bm ON bm.branch_id = v.branch_id
    LEFT JOIN vw_item_with_group_path AS vip ON vip.item_id = v.item_id
    LEFT JOIN item_make AS imk ON imk.item_make_id = pid.item_make_id
    LEFT JOIN uom_mst AS um ON um.uom_id = v.uom_id
    LEFT JOIN warehouse_mst AS wm ON wm.warehouse_id = pid.warehouse_id
    WHERE v.branch_id = :branch_id
        AND v.balance_qty > 0
        AND (:item_id IS NULL OR v.item_id = :item_id)
        AND (:item_grp_id IS NULL OR vip.item_grp_id = :item_grp_id)
    ORDER BY v.inward_date ASC, v.inward_dtl_id ASC;"""
    return text(sql)


def get_searchable_inventory_list_query():
    """
    Get paginated searchable inventory list from approved inwards.
    Supports search by item group code/name, item code/name, full_item_code, and SR number.
    Uses vw_item_with_group_path for hierarchical item group path display and search.
    Used for the inventory search table in create issue page.

    sr_no is the stored, already-formatted SR number (co/branch/SR/FY/seq).
    """
    sql = """SELECT
        v.inward_dtl_id,
        v.inward_id,
        pi.inward_sequence_no,
        pi.sr_no,
        v.inward_date,
        v.branch_id,
        bm.branch_name,
        v.item_id,
        vip.item_name,
        vip.item_code,
        vip.item_grp_id,
        vip.item_group_name_display AS item_grp_name,
        vip.item_group_code_display AS item_grp_code,
        vip.full_item_code,
        pid.item_make_id,
        imk.item_make_name,
        v.uom_id,
        um.uom_name,
        v.approved_qty,
        v.issue_qty,
        v.balance_qty AS available_qty,
        COALESCE(pid.accepted_rate, pid.rate) AS rate,
        pid.warehouse_id,
        wm.warehouse_name
    FROM vw_approved_inward_qty AS v
    INNER JOIN proc_inward AS pi ON pi.inward_id = v.inward_id
    INNER JOIN proc_inward_dtl AS pid ON pid.inward_dtl_id = v.inward_dtl_id
    LEFT JOIN branch_mst AS bm ON bm.branch_id = v.branch_id
    LEFT JOIN vw_item_with_group_path AS vip ON vip.item_id = v.item_id
    LEFT JOIN item_make AS imk ON imk.item_make_id = pid.item_make_id
    LEFT JOIN uom_mst AS um ON um.uom_id = v.uom_id
    LEFT JOIN warehouse_mst AS wm ON wm.warehouse_id = pid.warehouse_id
    WHERE v.branch_id = :branch_id
        AND v.balance_qty > 0
        AND (
            :search_like IS NULL
            OR vip.item_code LIKE :search_like
            OR vip.item_name LIKE :search_like
            OR vip.item_group_code_display LIKE :search_like
            OR vip.item_group_name_display LIKE :search_like
            OR vip.full_item_code LIKE :search_like
            OR pi.sr_no LIKE :search_like
        )
    ORDER BY v.inward_date DESC, v.inward_dtl_id DESC
    LIMIT :limit OFFSET :offset;"""
    return text(sql)


def get_searchable_inventory_count_query():
    """
    Get total count for searchable inventory list.
    Uses vw_item_with_group_path for hierarchical search.
    """
    sql = """SELECT COUNT(1) AS total
    FROM vw_approved_inward_qty AS v
    INNER JOIN proc_inward AS pi ON pi.inward_id = v.inward_id
    INNER JOIN proc_inward_dtl AS pid ON pid.inward_dtl_id = v.inward_dtl_id
    LEFT JOIN vw_item_with_group_path AS vip ON vip.item_id = v.item_id
    WHERE v.branch_id = :branch_id
        AND v.balance_qty > 0
        AND (
            :search_like IS NULL
            OR vip.item_code LIKE :search_like
            OR vip.item_name LIKE :search_like
            OR vip.item_group_code_display LIKE :search_like
            OR vip.item_group_name_display LIKE :search_like
            OR vip.full_item_code LIKE :search_like
            OR pi.sr_no LIKE :search_like
        );"""
    return text(sql)


def get_cost_factors_by_branch_query():
    """Get cost factors for a branch."""
    sql = """SELECT
        cf.cost_factor_id,
        cf.cost_factor_name,
        cf.cost_factor_desc,
        cf.branch_id,
        cf.dept_id
    FROM cost_factor_mst AS cf
    WHERE cf.branch_id = :branch_id
    ORDER BY cf.cost_factor_name;"""
    return text(sql)


def get_machines_by_dept_query():
    """Get machines for a department."""
    sql = """SELECT
        m.machine_id,
        m.machine_name,
        m.dept_id,
        m.machine_type_id,
        mt.machine_type_name,
        m.mech_code
    FROM machine_mst AS m
    LEFT JOIN machine_type_mst AS mt ON mt.machine_type_id = m.machine_type_id
    WHERE m.dept_id = :dept_id
        AND m.active = 1
    ORDER BY m.machine_name;"""
    return text(sql)


def get_machines_by_branch_query():
    """
    Get all machines for a branch (across all departments).
    Machines are linked to departments, and departments have branch_id.
    Frontend will filter by selected department.
    """
    sql = """SELECT
        m.machine_id,
        m.machine_name,
        m.dept_id,
        dm.dept_desc AS dept_name,
        m.machine_type_id,
        mt.machine_type_name,
        m.mech_code
    FROM machine_mst AS m
    LEFT JOIN machine_type_mst AS mt ON mt.machine_type_id = m.machine_type_id
    LEFT JOIN dept_mst AS dm ON dm.dept_id = m.dept_id
    WHERE dm.branch_id = :branch_id
        AND m.active = 1
    ORDER BY m.machine_name;"""
    return text(sql)
