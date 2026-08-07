from sqlalchemy.sql import text, bindparam


# ==================== ENQUIRY TABLE / LIST QUERIES ====================


def get_enquiry_table_query(branch_ids, status_filter=None, search=None, page=0, page_size=10):
    """Get paginated list of price enquiries with branch, status, expense type,
    and counts of line items, suppliers, and responses. Scoped to ``branch_ids``."""
    conditions = ["pe.active = 1", "pe.branch_id IN :branch_ids"]
    if status_filter:
        conditions.append("pe.status_id = :status_filter")
    if search:
        conditions.append(
            "(pe.price_enquiry_squence_no LIKE :search_like"
            " OR pe.enquiry_no LIKE :search_like"
            " OR bm.branch_name LIKE :search_like"
            " OR etm.expense_type_name LIKE :search_like"
            " OR pe.remarks LIKE :search_like"
            " OR EXISTS (SELECT 1 FROM proc_enquiry_supplier pes_s"
            "     JOIN party_mst pm_s ON pm_s.party_id = pes_s.supplier_id"
            "     WHERE pes_s.enquiry_id = pe.enquiry_id"
            "         AND pes_s.active = 1"
            "         AND pm_s.supp_name LIKE :search_like))"
        )

    where_clause = " AND ".join(conditions)

    sql = f"""SELECT
        pe.enquiry_id,
        pe.price_enquiry_date,
        pe.price_enquiry_squence_no,
        pe.enquiry_no,
        pe.remarks,
        pe.status_id,
        pe.branch_id,
        pe.enquiry_type,
        bm.branch_name,
        sm.status_name,
        etm.expense_type_name,
        (SELECT COUNT(*) FROM proc_enquiry_dtl ped
            WHERE ped.enquiry_id = pe.enquiry_id AND ped.active = 1) AS item_count,
        (SELECT COUNT(*) FROM proc_enquiry_supplier pes
            WHERE pes.enquiry_id = pe.enquiry_id AND pes.active = 1) AS supplier_count,
        (SELECT COUNT(*) FROM proc_price_enquiry_response per
            WHERE per.enquiry_id = pe.enquiry_id AND per.active = 1) AS response_count
    FROM proc_enquiry pe
    LEFT JOIN branch_mst bm ON bm.branch_id = pe.branch_id
    LEFT JOIN status_mst sm ON sm.status_id = pe.status_id
    LEFT JOIN expense_type_mst etm ON etm.expense_type_id = pe.expense_type_id
    WHERE {where_clause}
    ORDER BY pe.price_enquiry_date DESC, pe.enquiry_id DESC
    LIMIT :limit OFFSET :offset;"""
    return text(sql).bindparams(bindparam("branch_ids", expanding=True))


def get_enquiry_table_count_query(branch_ids, status_filter=None, search=None):
    """Get total count of price enquiries matching the same filter conditions."""
    conditions = ["pe.active = 1", "pe.branch_id IN :branch_ids"]
    if status_filter:
        conditions.append("pe.status_id = :status_filter")
    if search:
        conditions.append(
            "(pe.price_enquiry_squence_no LIKE :search_like"
            " OR pe.enquiry_no LIKE :search_like"
            " OR bm.branch_name LIKE :search_like"
            " OR etm.expense_type_name LIKE :search_like"
            " OR pe.remarks LIKE :search_like"
            " OR EXISTS (SELECT 1 FROM proc_enquiry_supplier pes_s"
            "     JOIN party_mst pm_s ON pm_s.party_id = pes_s.supplier_id"
            "     WHERE pes_s.enquiry_id = pe.enquiry_id"
            "         AND pes_s.active = 1"
            "         AND pm_s.supp_name LIKE :search_like))"
        )

    where_clause = " AND ".join(conditions)

    sql = f"""SELECT COUNT(1) AS total
    FROM proc_enquiry pe
    LEFT JOIN branch_mst bm ON bm.branch_id = pe.branch_id
    LEFT JOIN expense_type_mst etm ON etm.expense_type_id = pe.expense_type_id
    WHERE {where_clause};"""
    return text(sql).bindparams(bindparam("branch_ids", expanding=True))


# ==================== ENQUIRY HEADER CRUD ====================


def insert_proc_enquiry():
    """Insert a new price enquiry header."""
    sql = """INSERT INTO proc_enquiry (
        co_id,
        price_enquiry_date,
        price_enquiry_squence_no,
        enquiry_no,
        enquiry_type,
        remarks,
        branch_id,
        expense_type_id,
        project_id,
        status_id,
        approval_level,
        active,
        updated_by,
        updated_date_time
    ) VALUES (
        :co_id,
        :price_enquiry_date,
        :price_enquiry_squence_no,
        :enquiry_no,
        :enquiry_type,
        :remarks,
        :branch_id,
        :expense_type_id,
        :project_id,
        :status_id,
        :approval_level,
        :active,
        :updated_by,
        :updated_date_time
    );"""
    return text(sql)


def update_proc_enquiry():
    """Update an existing price enquiry header."""
    sql = """UPDATE proc_enquiry SET
        price_enquiry_date = :price_enquiry_date,
        enquiry_type = :enquiry_type,
        remarks = :remarks,
        branch_id = :branch_id,
        co_id = COALESCE(:co_id, co_id),
        expense_type_id = :expense_type_id,
        project_id = :project_id,
        updated_by = :updated_by,
        updated_date_time = :updated_date_time,
        enquiry_no = COALESCE(:enquiry_no, enquiry_no),
        active = COALESCE(:active, active),
        status_id = COALESCE(:status_id, status_id)
    WHERE enquiry_id = :enquiry_id;"""
    return text(sql)


def update_enquiry_status():
    """Update status_id, approval_level, updated_by and updated_date_time for an enquiry."""
    sql = """UPDATE proc_enquiry SET
        status_id = :status_id,
        approval_level = :approval_level,
        updated_by = :updated_by,
        updated_date_time = :updated_date_time,
        enquiry_no = CASE
            WHEN :enquiry_no IS NOT NULL THEN :enquiry_no
            ELSE enquiry_no
        END
    WHERE enquiry_id = :enquiry_id;"""
    return text(sql)


# ==================== ENQUIRY DETAIL CRUD ====================


def get_indent_info_by_dtl_id():
    """Fetch indent_id and dept_id from proc_indent_dtl for a given indent_dtl_id."""
    sql = """SELECT indent_id, dept_id
    FROM proc_indent_dtl
    WHERE indent_dtl_id = :indent_dtl_id;"""
    return text(sql)


def insert_proc_enquiry_dtl():
    """Insert a new enquiry detail (line item) row."""
    sql = """INSERT INTO proc_enquiry_dtl (
        enquiry_id,
        item_id,
        item_make_id,
        uom_id,
        qty,
        remarks,
        indent_dtl_id,
        indent_id,
        dept_id,
        active,
        updated_by,
        updated_date_time
    ) VALUES (
        :enquiry_id,
        :item_id,
        :item_make_id,
        :uom_id,
        :qty,
        :remarks,
        :indent_dtl_id,
        :indent_id,
        :dept_id,
        :active,
        :updated_by,
        :updated_date_time
    );"""
    return text(sql)


def delete_proc_enquiry_dtl(enquiry_id):
    """Soft delete all detail lines for an enquiry (set active = 0)."""
    sql = """UPDATE proc_enquiry_dtl SET
        active = 0,
        updated_by = :updated_by,
        updated_date_time = :updated_date_time
    WHERE enquiry_id = :enquiry_id;"""
    return text(sql)


# ==================== ENQUIRY SUPPLIER CRUD ====================


def insert_proc_enquiry_supplier():
    """Insert a supplier entry for an enquiry."""
    sql = """INSERT INTO proc_enquiry_supplier (
        enquiry_id,
        supplier_id,
        supplier_branch_id,
        active,
        updated_by,
        updated_date_time
    ) VALUES (
        :enquiry_id,
        :supplier_id,
        :supplier_branch_id,
        :active,
        :updated_by,
        :updated_date_time
    );"""
    return text(sql)


def delete_proc_enquiry_supplier(enquiry_id):
    """Soft delete all supplier entries for an enquiry (set active = 0)."""
    sql = """UPDATE proc_enquiry_supplier SET
        active = 0,
        updated_by = :updated_by,
        updated_date_time = :updated_date_time
    WHERE enquiry_id = :enquiry_id;"""
    return text(sql)


def upsert_proc_enquiry_supplier():
    """Insert a supplier entry, reactivating a soft-deleted row if the
    (enquiry_id, supplier_id) pair already exists (uk_enquiry_supplier)."""
    sql = """INSERT INTO proc_enquiry_supplier (
        enquiry_id,
        supplier_id,
        supplier_branch_id,
        active,
        updated_by,
        updated_date_time
    ) VALUES (
        :enquiry_id,
        :supplier_id,
        :supplier_branch_id,
        :active,
        :updated_by,
        :updated_date_time
    )
    ON DUPLICATE KEY UPDATE
        supplier_branch_id = VALUES(supplier_branch_id),
        active = VALUES(active),
        updated_by = VALUES(updated_by),
        updated_date_time = VALUES(updated_date_time);"""
    return text(sql)


# ==================== ENQUIRY GET-BY-ID QUERIES ====================


def get_enquiry_by_id_query():
    """Get enquiry header by enquiry_id with branch_name, status_name, expense_type_name."""
    sql = """SELECT
        pe.enquiry_id,
        pe.price_enquiry_date,
        pe.price_enquiry_squence_no,
        pe.enquiry_no,
        pe.enquiry_type,
        pe.remarks,
        pe.status_id,
        pe.branch_id,
        pe.expense_type_id,
        pe.project_id,
        pe.approval_level,
        pe.active,
        pe.updated_by,
        pe.updated_date_time,
        bm.branch_name,
        bm.branch_prefix,
        bm.co_id,
        cm.co_prefix,
        cm.co_name,
        cm.co_logo,
        sm.status_name,
        etm.expense_type_name,
        prjm.prj_name AS project_name,
        CASE
            WHEN pe.status_id = 20 THEN pe.approval_level
            ELSE NULL
        END AS current_approval_level
    FROM proc_enquiry pe
    LEFT JOIN branch_mst bm ON bm.branch_id = pe.branch_id
    LEFT JOIN co_mst cm ON cm.co_id = bm.co_id
    LEFT JOIN status_mst sm ON sm.status_id = pe.status_id
    LEFT JOIN expense_type_mst etm ON etm.expense_type_id = pe.expense_type_id
    LEFT JOIN project_mst prjm ON prjm.project_id = pe.project_id
    WHERE pe.enquiry_id = :enquiry_id
        AND (:co_id IS NULL OR bm.co_id = :co_id);"""
    return text(sql)


def get_enquiry_dtl_by_id_query():
    """Get enquiry detail lines with item, UOM, item make, and indent info."""
    sql = """SELECT
        ped.enquiry_dtl_id,
        ped.enquiry_id,
        ped.item_id,
        im.item_code,
        im.item_name,
        im.item_grp_id,
        igm.item_grp_code,
        igm.item_grp_name,
        ped.qty,
        ped.uom_id,
        um.uom_name,
        ped.item_make_id,
        imk.item_make_name,
        ped.dept_id,
        dm.dept_desc AS dept_name,
        ped.remarks,
        ped.indent_dtl_id,
        ped.indent_id,
        pi.indent_no
    FROM proc_enquiry_dtl ped
    LEFT JOIN item_mst im ON im.item_id = ped.item_id
    LEFT JOIN item_grp_mst igm ON igm.item_grp_id = im.item_grp_id
    LEFT JOIN uom_mst um ON um.uom_id = ped.uom_id
    LEFT JOIN item_make imk ON imk.item_make_id = ped.item_make_id
    LEFT JOIN dept_mst dm ON dm.dept_id = ped.dept_id
    LEFT JOIN proc_indent pi ON pi.indent_id = ped.indent_id
    WHERE ped.enquiry_id = :enquiry_id
        AND ped.active = 1
    ORDER BY ped.enquiry_dtl_id;"""
    return text(sql)


def get_enquiry_suppliers_query():
    """Get suppliers for an enquiry from proc_enquiry_supplier joined with party_mst."""
    sql = """SELECT
        pes.enquiry_supplier_id,
        pes.enquiry_id,
        pes.supplier_id,
        pes.supplier_branch_id,
        pes.sent_date,
        pes.sent_status,
        pm.supp_name,
        pm.supp_code,
        pm.supp_email_id,
        pm.phone_no,
        pbm.address AS branch_address1,
        pbm.address_additional AS branch_address2,
        pbm.state_id,
        sm.state AS state_name,
        pbm.gst_no
    FROM proc_enquiry_supplier pes
    LEFT JOIN party_mst pm ON pm.party_id = pes.supplier_id
    LEFT JOIN party_branch_mst pbm ON pbm.party_mst_branch_id = pes.supplier_branch_id
    LEFT JOIN state_mst sm ON sm.state_id = pbm.state_id
    WHERE pes.enquiry_id = :enquiry_id
        AND pes.active = 1
    ORDER BY pm.supp_name;"""
    return text(sql)


# ==================== ENQUIRY RESPONSE CRUD ====================


def insert_enquiry_response():
    """Insert a new price enquiry response header."""
    sql = """INSERT INTO proc_price_enquiry_response (
        enquiry_id,
        supplier_id,
        supplier_branch_id,
        `date`,
        credit_days,
        delivery_days,
        terms_conditions,
        payment_terms,
        remarks,
        gross_amount,
        net_amount,
        is_selected,
        active,
        updated_by,
        updated_date_time
    ) VALUES (
        :enquiry_id,
        :supplier_id,
        :supplier_branch_id,
        :response_date,
        :credit_days,
        :delivery_days,
        :terms_conditions,
        :payment_terms,
        :remarks,
        :gross_amount,
        :net_amount,
        :is_selected,
        :active,
        :updated_by,
        :updated_date_time
    );"""
    return text(sql)


def insert_enquiry_response_dtl():
    """Insert a price enquiry response detail line."""
    sql = """INSERT INTO proc_price_enquiry_response_dtl (
        proc_price_enquiry_response_id,
        enquiry_dtl_id,
        item_id,
        item_make_id,
        uom_id,
        qty,
        rate,
        discount_mode,
        discount_value,
        discount_amount,
        gross_amount,
        net_amount,
        active,
        updated_by,
        updated_date_time
    ) VALUES (
        :proc_price_enquiry_response_id,
        :enquiry_dtl_id,
        :item_id,
        :item_make_id,
        :uom_id,
        :qty,
        :rate,
        :discount_mode,
        :discount_value,
        :discount_amount,
        :gross_amount,
        :net_amount,
        :active,
        :updated_by,
        :updated_date_time
    );"""
    return text(sql)


def update_enquiry_response():
    """Update an existing price enquiry response header."""
    sql = """UPDATE proc_price_enquiry_response SET
        supplier_id = :supplier_id,
        supplier_branch_id = :supplier_branch_id,
        `date` = :response_date,
        credit_days = :credit_days,
        delivery_days = :delivery_days,
        terms_conditions = :terms_conditions,
        payment_terms = :payment_terms,
        remarks = :remarks,
        gross_amount = :gross_amount,
        net_amount = :net_amount,
        updated_by = :updated_by,
        updated_date_time = :updated_date_time
    WHERE proc_price_enquiry_response_id = :proc_price_enquiry_response_id;"""
    return text(sql)


def delete_enquiry_response_dtl(response_id):
    """Soft delete all response detail lines for a response (set active = 0)."""
    sql = """UPDATE proc_price_enquiry_response_dtl SET
        active = 0,
        updated_by = :updated_by,
        updated_date_time = :updated_date_time
    WHERE proc_price_enquiry_response_id = :proc_price_enquiry_response_id;"""
    return text(sql)


# ==================== COMPARISON / ANALYSIS QUERIES ====================


def get_responses_for_comparison_query():
    """Get all responses for an enquiry with supplier info and response detail lines.
    Returns all data needed for the comparison view, ordered by supplier and line item."""
    sql = """SELECT
        per.proc_price_enquiry_response_id,
        per.enquiry_id,
        per.supplier_id,
        per.supplier_branch_id,
        per.`date`,
        per.credit_days,
        per.delivery_days,
        per.terms_conditions,
        per.payment_terms,
        per.remarks AS response_remarks,
        per.is_selected,
        per.gross_amount AS resp_gross_amount,
        per.net_amount AS resp_net_amount,
        pm.supp_name,
        pm.supp_code,
        perd.proc_price_enquiry_response_dtl_id,
        perd.enquiry_dtl_id,
        perd.item_id,
        perd.qty,
        perd.rate,
        perd.discount_mode,
        perd.discount_value,
        perd.discount_amount,
        perd.gross_amount AS dtl_gross_amount,
        perd.net_amount AS dtl_net_amount,
        im.item_code,
        im.item_name,
        um.uom_name
    FROM proc_price_enquiry_response per
    JOIN party_mst pm ON pm.party_id = per.supplier_id
    LEFT JOIN proc_price_enquiry_response_dtl perd
        ON perd.proc_price_enquiry_response_id = per.proc_price_enquiry_response_id
        AND perd.active = 1
    LEFT JOIN item_mst im ON im.item_id = perd.item_id
    LEFT JOIN uom_mst um ON um.uom_id = perd.uom_id
    WHERE per.enquiry_id = :enquiry_id
        AND per.active = 1
    ORDER BY per.supplier_id, perd.enquiry_dtl_id;"""
    return text(sql)


# ==================== INDENT ITEMS FOR ENQUIRY ====================


def get_approved_indent_items_for_enquiry():
    """Get approved indent line items (status 3 = Approved) with outstanding
    quantity available for inclusion in a price enquiry, filtered by branch.

    Mirrors the filters used by the PO flow (`get_indent_line_items_for_po`
    + `get_all_approved_indents_query`):
      - indent status = 3 (Approved)
      - line is still active (pid.active = 1)
      - outstanding qty > 0 (not already consumed by prior POs)
    """
    sql = """SELECT
        pid.indent_dtl_id,
        pi.indent_id,
        pi.indent_no,
        pid.item_id,
        pid.item_make_id,
        pid.uom_id,
        pid.qty,
        COALESCE(oi.bal_ind_qty, pid.qty) AS outstanding_qty,
        pid.remarks,
        pid.dept_id,
        im.item_code,
        im.item_name,
        um.uom_name,
        imk.item_make_name
    FROM proc_indent_dtl pid
    JOIN proc_indent pi ON pi.indent_id = pid.indent_id
    LEFT JOIN item_mst im ON im.item_id = pid.item_id
    LEFT JOIN uom_mst um ON um.uom_id = pid.uom_id
    LEFT JOIN item_make imk ON imk.item_make_id = pid.item_make_id
    LEFT JOIN vw_proc_indent_outstanding_new oi ON oi.indent_dtl_id = pid.indent_dtl_id
    WHERE pi.status_id = 3
        AND pid.active = 1
        AND pi.branch_id = :branch_id
        AND COALESCE(oi.bal_ind_qty, pid.qty) > 0
    ORDER BY pi.indent_no, pid.indent_dtl_id;"""
    return text(sql)


# ==================== SEQUENCE / NUMBERING ====================


def get_max_enquiry_no_for_branch_fy():
    """Get the maximum enquiry_no for a branch within a financial year date range.

    Financial year: April 1 to March 31
    - If month >= 4 (April-December): FY = year-04-01 to (year+1)-03-31
    - If month < 4 (January-March): FY = (year-1)-04-01 to year-03-31
    """
    sql = """SELECT COALESCE(MAX(pe.enquiry_no), 0) AS max_enquiry_no
    FROM proc_enquiry pe
    WHERE pe.branch_id = :branch_id
        AND pe.price_enquiry_date >= :fy_start_date
        AND pe.price_enquiry_date <= :fy_end_date
        AND pe.enquiry_no IS NOT NULL;"""
    return text(sql)


# ==================== APPROVAL INFO ====================


def get_enquiry_with_approval_info():
    """Get enquiry with status_id, approval_level, branch_id for approval processing."""
    sql = """SELECT
        pe.enquiry_id,
        pe.status_id,
        pe.approval_level,
        pe.branch_id,
        pe.price_enquiry_date,
        pe.enquiry_no,
        bm.co_id
    FROM proc_enquiry pe
    LEFT JOIN branch_mst bm ON bm.branch_id = pe.branch_id
    WHERE pe.enquiry_id = :enquiry_id;"""
    return text(sql)


# ==================== PO PREFILL FROM RESPONSE ====================


def get_po_prefill_from_response():
    """Get response data formatted for PO prefill. Returns supplier info,
    enquiry header fields, and response detail lines with item metadata."""
    sql = """SELECT
        per.supplier_id,
        per.supplier_branch_id,
        per.credit_days,
        per.delivery_days,
        per.terms_conditions,
        per.payment_terms,
        per.enquiry_id,
        per.is_selected,
        pe.branch_id,
        pe.expense_type_id,
        pe.project_id,
        perd.enquiry_dtl_id,
        perd.item_id,
        perd.item_make_id,
        perd.uom_id,
        perd.qty,
        perd.rate,
        perd.discount_mode,
        perd.discount_value,
        perd.discount_amount,
        ped.indent_dtl_id,
        im.item_code,
        im.item_name,
        im.item_grp_id,
        im.hsn_code,
        um.uom_name,
        imk.item_make_name
    FROM proc_price_enquiry_response per
    JOIN proc_enquiry pe ON pe.enquiry_id = per.enquiry_id
    LEFT JOIN proc_price_enquiry_response_dtl perd
        ON perd.proc_price_enquiry_response_id = per.proc_price_enquiry_response_id
        AND perd.active = 1
    LEFT JOIN proc_enquiry_dtl ped ON ped.enquiry_dtl_id = perd.enquiry_dtl_id
    LEFT JOIN item_mst im ON im.item_id = perd.item_id
    LEFT JOIN uom_mst um ON um.uom_id = perd.uom_id
    LEFT JOIN item_make imk ON imk.item_make_id = perd.item_make_id
    WHERE per.proc_price_enquiry_response_id = :response_id
        AND per.active = 1;"""
    return text(sql)


# ==================== RESPONSE SELECTION ====================


def select_response_atomic():
    """Atomically award a single response for an enquiry: set the chosen
    response's is_selected = 1 and every other active response for the same
    enquiry to 0 in one statement. This closes the race window where two
    concurrent selects could each leave their pick marked as selected."""
    sql = """UPDATE proc_price_enquiry_response SET
        is_selected = CASE
            WHEN proc_price_enquiry_response_id = :proc_price_enquiry_response_id THEN 1
            ELSE 0
        END,
        updated_by = :updated_by,
        updated_date_time = :updated_date_time
    WHERE enquiry_id = :enquiry_id
        AND active = 1;"""
    return text(sql)


def get_response_enquiry_status():
    """Fetch the parent enquiry's status for a given response, used to gate
    award selection so a supplier can only be selected once the enquiry is
    Approved."""
    sql = """SELECT
        per.proc_price_enquiry_response_id,
        per.enquiry_id,
        per.is_selected,
        pe.status_id
    FROM proc_price_enquiry_response per
    JOIN proc_enquiry pe ON pe.enquiry_id = per.enquiry_id
    WHERE per.proc_price_enquiry_response_id = :proc_price_enquiry_response_id
        AND per.active = 1;"""
    return text(sql)


def mark_enquiry_suppliers_sent(supplier_ids=None):
    """Mark RFQ as sent for an enquiry's suppliers (all, or a subset)."""
    sql = """UPDATE proc_enquiry_supplier SET
        sent_status = 1,
        sent_date = :sent_date,
        updated_by = :updated_by,
        updated_date_time = :updated_date_time
    WHERE enquiry_id = :enquiry_id
        AND active = 1"""
    if supplier_ids:
        sql += "\n        AND supplier_id IN :supplier_ids"
        return text(sql + ";").bindparams(bindparam("supplier_ids", expanding=True))
    return text(sql + ";")


def get_enquiry_response_guards():
    """Fetch the enquiry status plus whether a supplier is invited and already
    has an active response — used to gate add_response."""
    sql = """SELECT
        pe.status_id,
        (SELECT COUNT(*) FROM proc_enquiry_supplier pes
            WHERE pes.enquiry_id = pe.enquiry_id
                AND pes.supplier_id = :supplier_id
                AND pes.active = 1) AS invited,
        (SELECT COUNT(*) FROM proc_price_enquiry_response per
            WHERE per.enquiry_id = pe.enquiry_id
                AND per.supplier_id = :supplier_id
                AND per.active = 1) AS existing_responses
    FROM proc_enquiry pe
    WHERE pe.enquiry_id = :enquiry_id
        AND pe.active = 1;"""
    return text(sql)


def get_response_detail_query():
    """Get a single response header with supplier name and all detail lines,
    shaped for the response view/edit page."""
    sql = """SELECT
        per.proc_price_enquiry_response_id,
        per.enquiry_id,
        per.supplier_id,
        per.supplier_branch_id,
        per.`date` AS response_date,
        per.credit_days,
        per.delivery_days,
        per.terms_conditions,
        per.payment_terms,
        per.remarks AS response_remarks,
        per.is_selected,
        per.gross_amount AS resp_gross_amount,
        per.net_amount AS resp_net_amount,
        pm.supp_name,
        pm.supp_code,
        perd.proc_price_enquiry_response_dtl_id,
        perd.enquiry_dtl_id,
        perd.item_id,
        perd.item_make_id,
        perd.uom_id,
        perd.qty,
        perd.rate,
        perd.discount_mode,
        perd.discount_value,
        perd.discount_amount,
        perd.gross_amount AS dtl_gross_amount,
        perd.net_amount AS dtl_net_amount,
        NULL AS dtl_remarks,
        im.item_code,
        im.item_name,
        imk.item_make_name,
        um.uom_name
    FROM proc_price_enquiry_response per
    JOIN party_mst pm ON pm.party_id = per.supplier_id
    LEFT JOIN proc_price_enquiry_response_dtl perd
        ON perd.proc_price_enquiry_response_id = per.proc_price_enquiry_response_id
        AND perd.active = 1
    LEFT JOIN item_mst im ON im.item_id = perd.item_id
    LEFT JOIN item_make imk ON imk.item_make_id = perd.item_make_id
    LEFT JOIN uom_mst um ON um.uom_id = perd.uom_id
    WHERE per.proc_price_enquiry_response_id = :response_id
        AND per.active = 1
    ORDER BY perd.enquiry_dtl_id;"""
    return text(sql)
