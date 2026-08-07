from sqlalchemy.sql import text
from sqlalchemy.sql import bindparam
from sqlalchemy.sql.elements import TextClause

# Re-export shared approval query functions for backward compatibility.
# These were moved to src/common/approval_query.py but many modules still
# import them from here.
from src.common.approval_query import (  # noqa: F401
    get_approval_flow_by_menu_branch,
    get_user_approval_level,
    get_max_approval_level,
    check_approval_mst_exists,
    get_user_edit_access,
    get_user_consumed_amounts,
)

# For a direct (no-PO) inward the supplier branch (and thus the supplier's GST
# state) is never captured. Resolve it to the supplier's sole active party
# branch when — and only when — exactly one exists (unambiguous). MAX(...) with
# HAVING COUNT(*) = 1 returns that branch's id, or NULL when the supplier has 0
# or >1 branches (ambiguous → the SR page must let the user pick). `pi` must be
# the proc_inward alias in the surrounding query.
_AUTO_SINGLE_SUPPLIER_BRANCH = (
    "(SELECT MAX(pb_auto.party_mst_branch_id) FROM party_branch_mst pb_auto "
    "WHERE pb_auto.party_id = pi.supplier_id AND pb_auto.active = 1 HAVING COUNT(*) = 1)"
)

def get_expense_types():
    sql = f"""select expense_type_id, etm.expense_type_name  
    from expense_type_mst etm where etm.active =1 ;"""
    query = text(sql)
    return query

def get_project(branch_id: int = None):
    sql = f"""select pm.prj_name , pm.project_id 
    from project_mst pm where pm.branch_id = :branch_id and pm.active =1 ;"""
    query = text(sql)
    return query

def get_make(co_id: int = None):
    sql = f"""select igm.item_grp_id, im.item_make_id , im.item_make_name   from item_grp_mst igm
right join item_make im on im.item_grp_id = igm.item_grp_id 
where igm.co_id = :co_id;"""
    query = text(sql)
    return query

def get_item_by_group_id_purchaseable(item_group_id: int):
    sql = """Select im.item_id,
im.item_code, vip.full_item_code, im.item_name, im.uom_id, um.uom_name, im.tax_percentage, im.hsn_code
from item_mst im
left join uom_mst um on um.uom_id = im.uom_id
left join vw_item_with_group_path vip on vip.item_id = im.item_id
where im.item_grp_id = :item_group_id and im.active = 1 and im.purchaseable = 1;"""
    query = text(sql)
    return query

def get_last_purchase_rates_by_item_group():
    sql = """
    SELECT ranked.item_id, ranked.last_purchase_rate,
           ranked.last_purchase_date, ranked.last_supplier_name
    FROM (
        SELECT ppd.item_id,
               ppd.rate AS last_purchase_rate,
               pp.po_date AS last_purchase_date,
               pm.supp_name AS last_supplier_name,
               ROW_NUMBER() OVER (
                   PARTITION BY ppd.item_id
                   ORDER BY pp.po_date DESC, pp.po_id DESC
               ) AS rn
        FROM proc_po_dtl ppd
        JOIN proc_po pp ON pp.po_id = ppd.po_id
        JOIN branch_mst bm ON bm.branch_id = pp.branch_id
        LEFT JOIN party_mst pm ON pm.party_id = pp.supplier_id
        JOIN item_mst im ON im.item_id = ppd.item_id
        WHERE im.item_grp_id = :item_group_id
          AND pp.status_id = 3
          AND ppd.active = 1
          AND bm.co_id = :co_id
    ) ranked
    WHERE ranked.rn = 1
    """
    return text(sql)

def get_item_make_by_group_id(item_group_id: int):
    sql = f"""select im.item_make_id, im.item_make_name 
    from item_make im 
    where im.item_grp_id = :item_group_id;"""
    query = text(sql)
    return query

def get_item_uom_by_group_id(item_group_id: int):
    sql = """SELECT uimm.item_id,
       uimm.map_from_id,
       um_from.uom_name AS map_from_name,
       uimm.map_to_id,
       um_to.uom_name AS uom_name,
       uimm.relation_value,
       uimm.rounding
FROM uom_item_map_mst AS uimm
JOIN item_mst AS im
  ON im.item_id = uimm.item_id
 AND im.item_grp_id = :item_group_id
 AND im.purchaseable = 1
 AND im.active = 1
LEFT JOIN uom_mst AS um_to
  ON um_to.uom_id = uimm.map_to_id
LEFT JOIN uom_mst AS um_from
  ON um_from.uom_id = uimm.map_from_id;"""
    query = text(sql)
    return query


def insert_proc_indent():
    sql = """INSERT INTO proc_indent (
    indent_date,
    indent_no,
    active,
    indent_type_id,
    remarks,
    branch_id,
    expense_type_id,
    project_id,
    updated_by,
    updated_date_time,
    status_id,
    indent_title
) VALUES (
    :indent_date,
    :indent_no,
    :active,
    :indent_type_id,
    :remarks,
    :branch_id,
    :expense_type_id,
    :project_id,
    :updated_by,
    :updated_date_time,
    :status_id,
    :indent_title
);"""
    return text(sql)


def insert_proc_indent_detail():
    sql = """INSERT INTO proc_indent_dtl (
    indent_id,
    required_by_days,
    active,
    item_id,
    qty,
    uom_id,
    remarks,
    updated_by,
    updated_date_time,
    item_make_id,
    dept_id
) VALUES (
    :indent_id,
    :required_by_days,
    :active,
    :item_id,
    :qty,
    :uom_id,
    :remarks,
    :updated_by,
    :updated_date_time,
    :item_make_id,
    :dept_id
);"""
    return text(sql)


def get_indent_table_query():
        sql = """SELECT
        pi.indent_id,
        pi.indent_no,
        pi.indent_date,
        bm.branch_name,
        bm.branch_prefix,
        bm.co_id,
        cm.co_prefix,
        etm.expense_type_name,
        sm.status_name
FROM proc_indent AS pi
LEFT JOIN branch_mst AS bm ON bm.branch_id = pi.branch_id
LEFT JOIN co_mst AS cm ON cm.co_id = bm.co_id
LEFT JOIN expense_type_mst AS etm ON etm.expense_type_id = pi.expense_type_id
LEFT JOIN status_mst AS sm ON sm.status_id = pi.status_id
WHERE (:co_id IS NULL OR bm.co_id = :co_id)
    AND (:branch_id IS NULL OR pi.branch_id = :branch_id)
    AND (
                :search_like IS NULL
                OR pi.indent_no LIKE :search_like
                OR bm.branch_name LIKE :search_like
                OR etm.expense_type_name LIKE :search_like
            )
ORDER BY pi.indent_date DESC, pi.indent_id DESC
LIMIT :limit OFFSET :offset;"""
        return text(sql)


def get_all_approved_indents_query():
    """Get all approved indents (status_id = 3) for dropdown selection."""
    sql = """SELECT
        pi.indent_id,
        pi.indent_no,
        pi.indent_date,
        bm.branch_name,
        bm.branch_prefix,
        bm.co_id,
        cm.co_prefix,
        etm.expense_type_name
    FROM proc_indent AS pi
    LEFT JOIN branch_mst AS bm ON bm.branch_id = pi.branch_id
    LEFT JOIN co_mst AS cm ON cm.co_id = bm.co_id
    LEFT JOIN expense_type_mst AS etm ON etm.expense_type_id = pi.expense_type_id
    WHERE pi.status_id = 3
        AND (:branch_id IS NULL OR pi.branch_id = :branch_id)
        AND (:co_id IS NULL OR bm.co_id = :co_id)
        AND bm.active = 1
    ORDER BY pi.indent_date DESC, pi.indent_id DESC;"""
    return text(sql)


def get_indent_table_count_query():
        sql = """SELECT COUNT(1) AS total
FROM proc_indent AS pi
LEFT JOIN branch_mst AS bm ON bm.branch_id = pi.branch_id
LEFT JOIN expense_type_mst AS etm ON etm.expense_type_id = pi.expense_type_id
WHERE (:co_id IS NULL OR bm.co_id = :co_id)
    AND (:branch_id IS NULL OR pi.branch_id = :branch_id)
    AND (
                :search_like IS NULL
                OR pi.indent_no LIKE :search_like
                OR bm.branch_name LIKE :search_like
                OR etm.expense_type_name LIKE :search_like
            );"""
        return text(sql)


def get_po_table_query():
    sql = """SELECT
        pp.po_id,
        pp.po_no,
        pp.po_date,
        pm.supp_name,
        pp.total_amount AS po_value,
        pp.branch_id,
        bm.branch_name,
        bm.branch_prefix,
        bm.co_id,
        cm.co_prefix,
        prjm.prj_name AS project_name,
        sm.status_name
    FROM proc_po AS pp
    LEFT JOIN branch_mst AS bm ON bm.branch_id = pp.branch_id
    LEFT JOIN co_mst AS cm ON cm.co_id = bm.co_id
    LEFT JOIN party_mst AS pm ON pm.party_id = pp.supplier_id
    LEFT JOIN project_mst AS prjm ON prjm.project_id = pp.project_id
    LEFT JOIN status_mst AS sm ON sm.status_id = pp.status_id
    WHERE (:co_id IS NULL OR bm.co_id = :co_id)
        AND (
            :search_like IS NULL
            OR pp.po_no LIKE :search_like
            OR pm.supp_name LIKE :search_like
            OR bm.branch_name LIKE :search_like
        )
    ORDER BY pp.po_date DESC, pp.po_id DESC
    LIMIT :limit OFFSET :offset;"""
    return text(sql)


def get_po_table_count_query():
    sql = """SELECT COUNT(1) AS total
    FROM proc_po AS pp
    LEFT JOIN branch_mst AS bm ON bm.branch_id = pp.branch_id
    LEFT JOIN party_mst AS pm ON pm.party_id = pp.supplier_id
    WHERE (:co_id IS NULL OR bm.co_id = :co_id)
        AND (
            :search_like IS NULL
            OR pp.po_no LIKE :search_like
            OR pm.supp_name LIKE :search_like
            OR bm.branch_name LIKE :search_like
        );"""
    return text(sql)


def get_inward_table_query():
    sql = """SELECT
        pi.inward_id,
        pi.inward_sequence_no,
        pi.inward_date,
        pi.branch_id,
        pi.inspection_check,
        bm.branch_name,
        bm.branch_prefix,
        bm.co_id,
        cm.co_prefix,
        pp.po_id,
        pp.po_no,
        pp.po_date,
        pm.party_id AS supplier_id,
        pm.supp_name AS supplier_name,
        sm.status_name
    FROM proc_inward AS pi
    LEFT JOIN branch_mst AS bm ON bm.branch_id = pi.branch_id
    LEFT JOIN co_mst AS cm ON cm.co_id = bm.co_id
    LEFT JOIN proc_po AS pp ON pp.po_id = (
        SELECT DISTINCT ppd.po_id 
        FROM proc_inward_dtl AS pid 
        LEFT JOIN proc_po_dtl AS ppd ON ppd.po_dtl_id = pid.po_dtl_id
        WHERE pid.inward_id = pi.inward_id
        LIMIT 1
    )
    LEFT JOIN party_mst AS pm ON pm.party_id = pi.supplier_id
    LEFT JOIN status_mst AS sm ON sm.status_id = pi.sr_status
    WHERE (:co_id IS NULL OR bm.co_id = :co_id)
        AND EXISTS (
            SELECT 1 FROM proc_inward_dtl pid
            WHERE pid.inward_id = pi.inward_id AND pid.status_id <> 6
        )
        AND (
            :search_like IS NULL
            OR pi.inward_sequence_no LIKE :search_like
            OR pp.po_no LIKE :search_like
            OR pm.supp_name LIKE :search_like
            OR bm.branch_name LIKE :search_like
        )
    ORDER BY pi.inward_date DESC, pi.inward_id DESC
    LIMIT :limit OFFSET :offset;"""
    return text(sql)


def get_inward_table_count_query():
    sql = """SELECT COUNT(1) AS total
    FROM proc_inward AS pi
    LEFT JOIN branch_mst AS bm ON bm.branch_id = pi.branch_id
    LEFT JOIN proc_po AS pp ON pp.po_id = (
        SELECT DISTINCT ppd.po_id
        FROM proc_inward_dtl AS pid
        LEFT JOIN proc_po_dtl AS ppd ON ppd.po_dtl_id = pid.po_dtl_id
        WHERE pid.inward_id = pi.inward_id
        LIMIT 1
    )
    LEFT JOIN party_mst AS pm ON pm.party_id = pi.supplier_id
    WHERE (:co_id IS NULL OR bm.co_id = :co_id)
        AND EXISTS (
            SELECT 1 FROM proc_inward_dtl pid
            WHERE pid.inward_id = pi.inward_id AND pid.status_id <> 6
        )
        AND (
            :search_like IS NULL
            OR pi.inward_sequence_no LIKE :search_like
            OR pp.po_no LIKE :search_like
            OR pm.supp_name LIKE :search_like
            OR bm.branch_name LIKE :search_like
        );"""
    return text(sql)


def get_inward_by_id_query():
    """Fetch inward header by inward_id with related branch, supplier, and status."""
    sql = """SELECT
        pi.inward_id,
        pi.inward_sequence_no,
        pi.inward_date,
        pi.branch_id,
        bm.branch_name,
        bm.branch_prefix,
        bm.co_id,
        cm.co_prefix,
        cm.co_name,
        cm.co_logo,
        pi.supplier_id,
        pm.supp_name AS supplier_name,
        pi.challan_no,
        pi.challan_date,
        pi.invoice_no,
        pi.invoice_date,
        pi.invoice_amount,
        pi.invoice_recvd_date,
        pi.vehicle_number,
        pi.driver_name,
        pi.driver_contact_number AS driver_contact_no,
        pi.consignment_no,
        pi.consignment_date,
        pi.ewaybillno,
        pi.ewaybill_date,
        pi.despatch_remarks,
        pi.receipts_remarks,
        pi.project_id,
        prj.prj_name AS project_name,
        pi.sr_status AS status_id,
        sm.status_name,
        pi.inspection_check,
        pi.updated_by,
        pi.updated_date_time,
        pi.gross_amount,
        pi.net_amount
    FROM proc_inward AS pi
    LEFT JOIN branch_mst AS bm ON bm.branch_id = pi.branch_id
    LEFT JOIN co_mst AS cm ON cm.co_id = bm.co_id
    LEFT JOIN party_mst AS pm ON pm.party_id = pi.supplier_id
    LEFT JOIN project_mst AS prj ON prj.project_id = pi.project_id
    LEFT JOIN status_mst AS sm ON sm.status_id = pi.sr_status
    WHERE pi.inward_id = :inward_id
        AND (:co_id IS NULL OR bm.co_id = :co_id);"""
    return text(sql)


def get_inward_detail_by_id_query():
    """Fetch inward line items by inward_id with item and PO details."""
    sql = """SELECT
        pid.inward_dtl_id,
        pid.inward_id,
        pid.po_dtl_id,
        ppd.po_id,
        pp.po_no,
        pp.po_date,
        pid.item_id,
        im.item_code,
        im.item_name,
        im.item_grp_id,
        ig.item_grp_code,
        ig.item_grp_name,
        vip.full_item_code,
        pid.item_make_id,
        imk.item_make_name,
        pid.hsn_code,
        pid.inward_qty AS quantity,
        pid.uom_id,
        um.uom_name,
        pid.rate,
        pid.amount,
        pid.remarks,
        pid.status_id,
        bm.branch_prefix,
        cm.co_prefix
    FROM proc_inward_dtl AS pid
    LEFT JOIN proc_po_dtl AS ppd ON ppd.po_dtl_id = pid.po_dtl_id
    LEFT JOIN proc_po AS pp ON pp.po_id = ppd.po_id
    LEFT JOIN item_mst AS im ON im.item_id = pid.item_id
    LEFT JOIN item_grp_mst AS ig ON ig.item_grp_id = im.item_grp_id
    LEFT JOIN vw_item_with_group_path AS vip ON vip.item_id = im.item_id
    LEFT JOIN item_make AS imk ON imk.item_make_id = pid.item_make_id
    LEFT JOIN uom_mst AS um ON um.uom_id = pid.uom_id
    LEFT JOIN branch_mst AS bm ON bm.branch_id = pp.branch_id
    LEFT JOIN co_mst AS cm ON cm.co_id = bm.co_id
    WHERE pid.inward_id = :inward_id
        AND pid.active = 1
    ORDER BY pid.inward_dtl_id;"""
    return text(sql)


def get_indent_by_id_query():
    sql = """SELECT
        pi.indent_id,
        pi.indent_no,
        pi.indent_date,
        pi.branch_id,
        bm.branch_name,
        bm.branch_prefix,
        bm.co_id,
        cm.co_prefix,
        cm.co_name,
        cm.co_logo,
        pi.indent_type_id,
        pi.expense_type_id,
        etm.expense_type_name,
        pi.project_id,
        pm.prj_name AS project_name,
        pi.indent_title,
        pi.remarks,
        pi.status_id,
        sm.status_name,
        pi.updated_by,
        pi.updated_date_time,
        CASE 
            WHEN pi.status_id = 20 THEN pi.approval_level 
            ELSE NULL 
        END AS approval_level
    FROM proc_indent AS pi
    LEFT JOIN branch_mst AS bm ON bm.branch_id = pi.branch_id
    LEFT JOIN co_mst AS cm ON cm.co_id = bm.co_id
    LEFT JOIN expense_type_mst AS etm ON etm.expense_type_id = pi.expense_type_id
    LEFT JOIN project_mst AS pm ON pm.project_id = pi.project_id
    LEFT JOIN status_mst AS sm ON sm.status_id = pi.status_id
    WHERE pi.indent_id = :indent_id
        AND (:co_id IS NULL OR bm.co_id = :co_id);"""
    return text(sql)


def get_indent_detail_by_id_query():
    sql = """SELECT
        pid.indent_dtl_id,
        pid.item_id,
        im.item_code,
        im.item_name,
        im.item_grp_id,
        igm.item_grp_code,
        igm.item_grp_name,
        pid.qty,
        pid.uom_id,
        um.uom_name,
        pid.item_make_id,
        imk.item_make_name,
        pid.dept_id,
        dm.dept_desc AS dept_name,
        pid.remarks
    FROM proc_indent_dtl AS pid
    LEFT JOIN item_mst AS im ON im.item_id = pid.item_id
    LEFT JOIN item_grp_mst AS igm ON igm.item_grp_id = im.item_grp_id
    LEFT JOIN uom_mst AS um ON um.uom_id = pid.uom_id
    LEFT JOIN item_make AS imk ON imk.item_make_id = pid.item_make_id
    LEFT JOIN dept_mst AS dm ON dm.dept_id = pid.dept_id
    WHERE pid.indent_id = :indent_id
        AND pid.active = 1
    ORDER BY pid.indent_dtl_id;"""
    return text(sql)


def update_proc_indent():
    sql = """UPDATE proc_indent SET
        indent_date = :indent_date,
        branch_id = :branch_id,
        indent_type_id = :indent_type_id,
        expense_type_id = :expense_type_id,
        project_id = :project_id,
        indent_title = :indent_title,
        remarks = :remarks,
        updated_by = :updated_by,
        updated_date_time = :updated_date_time,
        indent_no = COALESCE(:indent_no, indent_no),
        active = COALESCE(:active, active),
        status_id = COALESCE(:status_id, status_id)
    WHERE indent_id = :indent_id;"""
    return text(sql)


def delete_proc_indent_detail():
    sql = """UPDATE proc_indent_dtl SET
        active = 0,
        updated_by = :updated_by,
        updated_date_time = :updated_date_time
    WHERE indent_id = :indent_id;"""
    return text(sql)


def update_proc_indent_detail():
    """Update an existing indent detail row in place (preserves indent_dtl_id)."""
    sql = """UPDATE proc_indent_dtl SET
        item_id = :item_id,
        qty = :qty,
        uom_id = :uom_id,
        item_make_id = :item_make_id,
        dept_id = :dept_id,
        remarks = :remarks,
        updated_by = :updated_by,
        updated_date_time = :updated_date_time
    WHERE indent_dtl_id = :indent_dtl_id
      AND indent_id = :indent_id;"""
    return text(sql)


def soft_delete_indent_detail_by_ids():
    """Soft-delete specific indent detail rows by their IDs."""
    sql = """UPDATE proc_indent_dtl SET
        active = 0,
        updated_by = :updated_by,
        updated_date_time = :updated_date_time
    WHERE indent_id = :indent_id
      AND indent_dtl_id IN :dtl_ids;"""
    return text(sql)



def update_indent_status():
    """Update indent status and approval level. Optionally update indent_no."""
    sql = """UPDATE proc_indent SET
        status_id = :status_id,
        approval_level = :approval_level,
        updated_by = :updated_by,
        updated_date_time = :updated_date_time,
        indent_no = CASE 
            WHEN :indent_no IS NOT NULL THEN :indent_no 
            ELSE indent_no 
        END
    WHERE indent_id = :indent_id;"""
    return text(sql)


def get_max_indent_no_for_branch_fy():
    """Get the maximum indent_no for a branch within a financial year.
    
    Financial year: April 1 to March 31
    - If month >= 4 (April-December): FY = year-04-01 to (year+1)-03-31
    - If month < 4 (January-March): FY = (year-1)-04-01 to year-03-31
    """
    sql = """SELECT COALESCE(MAX(pi.indent_no), 0) as max_indent_no
    FROM proc_indent pi
    WHERE pi.branch_id = :branch_id
        AND pi.indent_date >= :fy_start_date
        AND pi.indent_date <= :fy_end_date
        AND pi.indent_no IS NOT NULL;"""
    return text(sql)


def get_indent_with_approval_info():
    """Get indent details including approval level and status."""
    sql = """SELECT
        pi.indent_id,
        pi.status_id,
        pi.approval_level,
        pi.branch_id,
        pi.indent_date,
        pi.indent_no,
        bm.co_id
    FROM proc_indent pi
    LEFT JOIN branch_mst bm ON bm.branch_id = pi.branch_id
    WHERE pi.indent_id = :indent_id;"""
    return text(sql)


# ==================== PO QUERY FUNCTIONS ====================

def get_suppliers_with_party_type_1(co_id: int = None):
    """Get suppliers where party_type_id contains 1 with full details."""
    sql = """SELECT 
        pm.party_id,
        pm.supp_name AS supplier_name,
        pm.supp_code AS supplier_code,
        pm.supp_contact_person,
        pm.supp_contact_designation,
        pm.supp_email_id,
        pm.phone_no,
        pm.party_pan_no,
        pm.country_id,
        cm.country,
        pm.msme_certified,
        pm.entity_type_id,
        etm.entity_type_name
    FROM party_mst pm
    LEFT JOIN country_mst cm ON cm.country_id = pm.country_id
    LEFT JOIN entity_type_mst etm ON etm.entity_type_id = pm.entity_type_id
    WHERE FIND_IN_SET("1", REPLACE(REPLACE(pm.party_type_id, "{", ""), "}", "")) > 0
        AND (:co_id IS NULL OR pm.co_id = :co_id)
        AND pm.active = 1
    ORDER BY pm.supp_name;"""
    return text(sql)


def get_supplier_branches(party_id: int):
    """Get branch addresses for a supplier with full address details."""
    sql = """SELECT 
        pbm.party_mst_branch_id,
        pbm.party_id,
        pbm.address AS branch_address1,
        pbm.address_additional AS branch_address2,
        pbm.state_id,
        sm.state AS state,
        pbm.zip_code,
        pbm.contact_person,
        pbm.contact_no,
        pbm.gst_no
    FROM party_branch_mst pbm
    LEFT JOIN state_mst sm ON sm.state_id = pbm.state_id
    WHERE pbm.party_id = :party_id
        AND pbm.active = 1
    ORDER BY pbm.party_mst_branch_id;"""
    return text(sql)


def get_all_supplier_branches_bulk(co_id: int = None):
    """Get branch addresses for ALL active suppliers in a single query.
    This avoids the N+1 query problem when fetching branches for many suppliers.
    Results should be grouped by party_id in Python."""
    sql = """SELECT 
        pbm.party_mst_branch_id,
        pbm.party_id,
        pbm.address AS branch_address1,
        pbm.address_additional AS branch_address2,
        pbm.state_id,
        sm.state AS state,
        pbm.zip_code,
        pbm.contact_person,
        pbm.contact_no,
        pbm.gst_no
    FROM party_branch_mst pbm
    INNER JOIN party_mst pm ON pm.party_id = pbm.party_id
    LEFT JOIN state_mst sm ON sm.state_id = pbm.state_id
    WHERE pbm.active = 1
        AND pm.active = 1
        AND FIND_IN_SET("1", REPLACE(REPLACE(pm.party_type_id, "{", ""), "}", "")) > 0
        AND (:co_id IS NULL OR pm.co_id = :co_id)
    ORDER BY pbm.party_id, pbm.party_mst_branch_id;"""
    return text(sql)


def get_company_branch_addresses(co_id: int = None, branch_id: int = None):
    """Get branch addresses for company branches with state information. If branch_id is provided, filter by that branch."""
    sql = """SELECT 
        bm.branch_id,
        bm.branch_name,
        bm.branch_address1,
        bm.branch_address2,
        bm.state_id,
        sm.state AS state_name,
        bm.branch_zipcode,
        bm.co_id
    FROM branch_mst bm
    LEFT JOIN state_mst sm ON sm.state_id = bm.state_id
    WHERE (:co_id IS NULL OR bm.co_id = :co_id)
        AND (:branch_id IS NULL OR bm.branch_id = :branch_id)
        AND bm.active = 1
    ORDER BY bm.branch_name;"""
    return text(sql)


def get_indent_line_items_for_po(indent_id: int):
    """Get line items for an indent to be used in PO creation popup.
    Includes indent_type and outstanding (unfulfilled) qty from vw_proc_indent_outstanding.
    """
    sql = """SELECT
        pid.indent_dtl_id,
        pi.indent_id,
        pi.indent_no,
        pi.indent_date,
        pi.expense_type_id,
        pi.indent_type_id AS indent_type,
        cm.co_prefix,
        bm.branch_prefix,
        pid.item_id,
        im.item_code,
        im.item_name,
        im.item_grp_id,
        igm.item_grp_code,
        igm.item_grp_name,
        vip.full_item_code,
        pid.qty,
        COALESCE(oi.bal_ind_qty, 0) AS outstanding_qty,
        pid.uom_id,
        um.uom_name,
        pid.item_make_id,
        imk.item_make_name,
        pid.dept_id,
        dm.dept_desc AS dept_name,
        im.tax_percentage,
        pid.remarks,
        ibv.min_po_qty AS min_order_qty
    FROM proc_indent_dtl AS pid
    LEFT JOIN proc_indent AS pi ON pi.indent_id = pid.indent_id
    LEFT JOIN branch_mst AS bm ON bm.branch_id = pi.branch_id
    LEFT JOIN co_mst AS cm ON cm.co_id = bm.co_id
    LEFT JOIN item_mst AS im ON im.item_id = pid.item_id
    LEFT JOIN item_grp_mst AS igm ON igm.item_grp_id = im.item_grp_id
    LEFT JOIN vw_item_with_group_path AS vip ON vip.item_id = im.item_id
    LEFT JOIN uom_mst AS um ON um.uom_id = pid.uom_id
    LEFT JOIN item_make AS imk ON imk.item_make_id = pid.item_make_id
    LEFT JOIN dept_mst AS dm ON dm.dept_id = pid.dept_id
    LEFT JOIN vw_proc_indent_outstanding_new oi ON oi.indent_dtl_id = pid.indent_dtl_id
    LEFT JOIN vw_item_balance_qty_by_branch_new ibv ON ibv.item_id = pid.item_id AND ibv.branch_id = pi.branch_id
    WHERE pid.indent_id = :indent_id
        AND pid.active = 1
    ORDER BY pid.indent_dtl_id;"""
    return text(sql)


def insert_proc_po():
    """Insert PO header."""
    sql = """INSERT INTO proc_po (
        credit_days,
        delivery_instructions,
        expected_delivery_days,
        footer_notes,
        po_date,
        po_approve_date,
        po_no,
        remarks,
        delivery_mode,
        terms_conditions,
        branch_id,
        price_enquiry_id,
        project_id,
        supplier_id,
        status_id,
        supplier_branch_id,
        billing_branch_id,
        shipping_branch_id,
        total_amount,
        net_amount,
        advance_type,
        advance_value,
        advance_amount,
        contact_no,
        contact_person,
        updated_by,
        updated_date_time,
        approval_level,
        expense_type_id,
        po_type
    ) VALUES (
        :credit_days,
        :delivery_instructions,
        :expected_delivery_days,
        :footer_notes,
        :po_date,
        :po_approve_date,
        :po_no,
        :remarks,
        :delivery_mode,
        :terms_conditions,
        :branch_id,
        :price_enquiry_id,
        :project_id,
        :supplier_id,
        :status_id,
        :supplier_branch_id,
        :billing_branch_id,
        :shipping_branch_id,
        :total_amount,
        :net_amount,
        :advance_type,
        :advance_value,
        :advance_amount,
        :contact_no,
        :contact_person,
        :updated_by,
        :updated_date_time,
        :approval_level,
        :expense_type_id,
        :po_type
    );"""
    return text(sql)


def insert_proc_po_dtl():
    """Insert PO line item."""
    sql = """INSERT INTO proc_po_dtl (
        po_id,
        item_id,
        hsn_code,
        item_make_id,
        qty,
        rate,
        uom_id,
        remarks,
        discount_mode,
        discount_value,
        discount_amount,
        active,
        indent_dtl_id,
        updated_by,
        updated_date_time,
        state
    ) VALUES (
        :po_id,
        :item_id,
        :hsn_code,
        :item_make_id,
        :qty,
        :rate,
        :uom_id,
        :remarks,
        :discount_mode,
        :discount_value,
        :discount_amount,
        :active,
        :indent_dtl_id,
        :updated_by,
        :updated_date_time,
        :state
    );"""
    return text(sql)


def update_proc_po_dtl():
    """Update a single PO detail row in-place (preserving po_dtl_id)."""
    sql = """UPDATE proc_po_dtl SET
        item_id = :item_id,
        hsn_code = :hsn_code,
        item_make_id = :item_make_id,
        qty = :qty,
        rate = :rate,
        uom_id = :uom_id,
        remarks = :remarks,
        discount_mode = :discount_mode,
        discount_value = :discount_value,
        discount_amount = :discount_amount,
        indent_dtl_id = :indent_dtl_id,
        updated_by = :updated_by,
        updated_date_time = :updated_date_time
    WHERE po_dtl_id = :po_dtl_id AND po_id = :po_id;"""
    return text(sql)


def insert_proc_po_additional():
    """Insert PO additional charges."""
    sql = """INSERT INTO proc_po_additional (
        po_id,
        additional_charges_id,
        qty,
        rate,
        net_amount,
        remarks
    ) VALUES (
        :po_id,
        :additional_charges_id,
        :qty,
        :rate,
        :net_amount,
        :remarks
    );"""
    return text(sql)


def insert_po_gst():
    """Insert PO GST record."""
    sql = """INSERT INTO po_gst (
        po_dtl_id,
        po_additional_id,
        tax_pct,
        stax_percentage,
        s_tax_amount,
        i_tax_amount,
        i_tax_percentage,
        c_tax_amount,
        c_tax_percentage,
        tax_amount,
        active
    ) VALUES (
        :po_dtl_id,
        :po_additional_id,
        :tax_pct,
        :stax_percentage,
        :s_tax_amount,
        :i_tax_amount,
        :i_tax_percentage,
        :c_tax_amount,
        :c_tax_percentage,
        :tax_amount,
        1
    );"""
    return text(sql)


def get_inward_line_tax_pct_query():
    """Resolve an inward line's tax % for SR GST, inheriting from the PO.

    PO-linked line -> the PO's po_gst.tax_pct (0 when the PO carried no GST row,
    i.e. a genuinely zero-tax PO). Non-PO (direct) inward -> item_mst fallback.
    Deliberately does NOT use item_mst tax for PO-linked lines: SR tax must
    match the PO, not the current item master value.
    """
    sql = """
        SELECT CASE
            WHEN pid.po_dtl_id IS NOT NULL THEN COALESCE(pg.tax_pct, 0)
            ELSE COALESCE(im.tax_percentage, 0)
        END AS tax_pct
        FROM proc_inward_dtl pid
        LEFT JOIN po_gst pg
            ON pg.po_dtl_id = pid.po_dtl_id AND pg.active = 1
        LEFT JOIN item_mst im ON im.item_id = pid.item_id
        WHERE pid.inward_dtl_id = :inward_dtl_id
        LIMIT 1
    """
    return text(sql)


def insert_proc_gst():
    """Insert procurement inward GST record (for line items or additional charges)."""
    sql = """INSERT INTO proc_gst (
        proc_inward_dtl,
        proc_inward_additional_id,
        tax_pct,
        stax_percentage,
        s_tax_amount,
        i_tax_amount,
        i_tax_percentage,
        c_tax_amount,
        c_tax_percentage,
        tax_amount,
        active,
        updated_by
    ) VALUES (
        :proc_inward_dtl,
        :proc_inward_additional_id,
        :tax_pct,
        :stax_percentage,
        :s_tax_amount,
        :i_tax_amount,
        :i_tax_percentage,
        :c_tax_amount,
        :c_tax_percentage,
        :tax_amount,
        1,
        :updated_by
    );"""
    return text(sql)


def delete_proc_gst_by_inward():
    """Delete procurement GST records by inward ID."""
    sql = """DELETE FROM proc_gst
    WHERE proc_inward_dtl IN (
        SELECT inward_dtl_id FROM proc_inward_dtl WHERE inward_id = :inward_id
    );"""
    return text(sql)


def update_proc_po():
    """Update PO header."""
    sql = """UPDATE proc_po SET
        credit_days = :credit_days,
        delivery_instructions = :delivery_instructions,
        expected_delivery_days = :expected_delivery_days,
        footer_notes = :footer_notes,
        po_date = :po_date,
        remarks = :remarks,
        delivery_mode = :delivery_mode,
        terms_conditions = :terms_conditions,
        branch_id = :branch_id,
        project_id = :project_id,
        supplier_id = :supplier_id,
        supplier_branch_id = :supplier_branch_id,
        billing_branch_id = :billing_branch_id,
        shipping_branch_id = :shipping_branch_id,
        total_amount = :total_amount,
        net_amount = :net_amount,
        advance_type = :advance_type,
        advance_value = :advance_value,
        advance_amount = :advance_amount,
        contact_no = :contact_no,
        contact_person = :contact_person,
        updated_by = :updated_by,
        updated_date_time = :updated_date_time,
        po_no = COALESCE(:po_no, po_no),
        status_id = COALESCE(:status_id, status_id),
        approval_level = COALESCE(:approval_level, approval_level),
        expense_type_id = :expense_type_id,
        po_type = :po_type
    WHERE po_id = :po_id;"""
    return text(sql)


def delete_proc_po_dtl():
    """Soft delete PO line items."""
    sql = """UPDATE proc_po_dtl SET
        active = 0,
        updated_by = :updated_by,
        updated_date_time = :updated_date_time
    WHERE po_id = :po_id;"""
    return text(sql)


def delete_proc_po_additional():
    """Delete PO additional charges."""
    sql = """DELETE FROM proc_po_additional
    WHERE po_id = :po_id;"""
    return text(sql)


def delete_po_gst():
    """Delete PO GST records."""
    sql = """DELETE FROM po_gst
    WHERE po_dtl_id IN (
        SELECT po_dtl_id FROM proc_po_dtl WHERE po_id = :po_id
    ) OR po_additional_id IN (
        SELECT po_additional_id FROM proc_po_additional WHERE po_id = :po_id
    );"""
    return text(sql)


def delete_po_gst_by_dtl_id():
    """Delete GST records for a specific PO detail line."""
    sql = """DELETE FROM po_gst WHERE po_dtl_id = :po_dtl_id;"""
    return text(sql)


def delete_po_gst_for_additional_charges():
    """Delete GST records linked to additional charges for a given PO."""
    sql = """DELETE FROM po_gst
    WHERE po_additional_id IN (
        SELECT po_additional_id FROM proc_po_additional WHERE po_id = :po_id
    );"""
    return text(sql)


def get_po_by_id_query():
    """Get PO header by ID."""
    sql = """SELECT
        pp.po_id,
        pp.po_no,
        pp.po_date,
        pp.branch_id,
        bm.branch_name,
        bm.branch_prefix,
        bm.co_id,
        cm.co_prefix,
        cm.co_name,
        cm.co_logo,
        pp.supplier_id,
        pm.supp_name AS supplier_name,
        pp.supplier_branch_id,
        pbm.address AS supplier_branch_address,
        pbm.state_id AS supplier_state_id,
        sm_supplier.state AS supplier_state_name,
        pp.billing_branch_id,
        bm_billing.branch_name AS billing_branch_name,
        bm_billing.state_id AS billing_state_id,
        sm_billing.state AS billing_state_name,
        pp.shipping_branch_id,
        bm_shipping.branch_name AS shipping_branch_name,
        bm_shipping.state_id AS shipping_state_id,
        sm_shipping.state AS shipping_state_name,
        pp.project_id,
        prjm.prj_name AS project_name,
        pp.credit_days,
        pp.expected_delivery_days,
        pp.contact_person,
        pp.contact_no,
        pp.footer_notes,
        pp.remarks,
        pp.terms_conditions,
        pp.total_amount,
        pp.net_amount,
        pp.advance_type,
        pp.advance_value,
        pp.advance_amount,
        pp.status_id,
        sm.status_name,
        pp.updated_by,
        pp.updated_date_time AS update_date_time,
        CASE 
            WHEN pp.status_id = 20 THEN pp.approval_level 
            ELSE NULL 
        END AS approval_level,
        pp.expense_type_id,
        pp.po_type
    FROM proc_po AS pp
    LEFT JOIN branch_mst AS bm ON bm.branch_id = pp.branch_id
    LEFT JOIN co_mst AS cm ON cm.co_id = bm.co_id
    LEFT JOIN party_mst AS pm ON pm.party_id = pp.supplier_id
    LEFT JOIN party_branch_mst AS pbm ON pbm.party_mst_branch_id = pp.supplier_branch_id
    LEFT JOIN state_mst AS sm_supplier ON sm_supplier.state_id = pbm.state_id
    LEFT JOIN branch_mst AS bm_billing ON bm_billing.branch_id = pp.billing_branch_id
    LEFT JOIN state_mst AS sm_billing ON sm_billing.state_id = bm_billing.state_id
    LEFT JOIN branch_mst AS bm_shipping ON bm_shipping.branch_id = pp.shipping_branch_id
    LEFT JOIN state_mst AS sm_shipping ON sm_shipping.state_id = bm_shipping.state_id
    LEFT JOIN project_mst AS prjm ON prjm.project_id = pp.project_id
    LEFT JOIN status_mst AS sm ON sm.status_id = pp.status_id
    WHERE pp.po_id = :po_id
        AND (:co_id IS NULL OR bm.co_id = :co_id);"""
    return text(sql)


def get_po_dtl_by_id_query():
    """Get PO line items by PO ID."""
    sql = """SELECT
        pod.po_dtl_id,
        pod.po_id,
        pod.item_id,
        im.item_code,
        im.item_name,
        im.item_grp_id,
        igm.item_grp_code,
        igm.item_grp_name,
        vip.full_item_code,
        pod.hsn_code,
        pod.item_make_id,
        imk.item_make_name,
        pod.qty,
        pod.rate,
        pod.uom_id,
        um.uom_name,
        pod.remarks,
        pod.discount_mode,
        pod.discount_value,
        pod.discount_amount,
        pod.indent_dtl_id,
        pid.indent_id,
        pi.indent_no,
        pi.indent_date AS indent_date,
        ind_bm.branch_prefix AS indent_branch_prefix,
        ind_cm.co_prefix AS indent_co_prefix,
        dm.dept_id,
        dm.dept_desc AS dept_name
    FROM proc_po_dtl AS pod
    LEFT JOIN item_mst AS im ON im.item_id = pod.item_id
    LEFT JOIN item_grp_mst AS igm ON igm.item_grp_id = im.item_grp_id
    LEFT JOIN vw_item_with_group_path AS vip ON vip.item_id = im.item_id
    LEFT JOIN item_make AS imk ON imk.item_make_id = pod.item_make_id
    LEFT JOIN uom_mst AS um ON um.uom_id = pod.uom_id
    LEFT JOIN proc_indent_dtl AS pid ON pid.indent_dtl_id = pod.indent_dtl_id
    LEFT JOIN proc_indent AS pi ON pi.indent_id = pid.indent_id
    LEFT JOIN branch_mst AS ind_bm ON ind_bm.branch_id = pi.branch_id
    LEFT JOIN co_mst AS ind_cm ON ind_cm.co_id = ind_bm.co_id
    LEFT JOIN dept_mst AS dm ON dm.dept_id = (
        SELECT dept_id FROM proc_indent_dtl WHERE indent_dtl_id = pod.indent_dtl_id
    )
    WHERE pod.po_id = :po_id
        AND pod.active = 1
    ORDER BY pod.po_dtl_id;"""
    return text(sql)


def get_po_additional_by_id_query():
    """Get PO additional charges by PO ID."""
    sql = """SELECT
        ppa.po_additional_id,
        ppa.po_id,
        ppa.additional_charges_id,
        acm.additional_charges_name,
        ppa.qty,
        ppa.rate,
        ppa.net_amount,
        ppa.remarks
    FROM proc_po_additional AS ppa
    LEFT JOIN additional_charges_mst AS acm ON acm.additional_charges_id = ppa.additional_charges_id
    WHERE ppa.po_id = :po_id
    ORDER BY ppa.po_additional_id;"""
    return text(sql)


def get_po_additional_with_tax_by_id_query():
    """PO additional charges with tax_pct + GST amounts from po_gst.

    Used to auto-populate SR additional charges from the originating PO.
    Shape mirrors inward additional charges so the existing frontend
    `mapRawToCharges` can consume rows directly.
    """
    sql = """SELECT
        ppa.po_additional_id,
        ppa.po_id,
        ppa.additional_charges_id,
        acm.additional_charges_name,
        ppa.qty,
        ppa.rate,
        ppa.net_amount,
        ppa.remarks,
        COALESCE(pg.tax_pct, 0) AS tax_pct,
        COALESCE(pg.i_tax_amount, 0) AS igst_amount,
        COALESCE(pg.c_tax_amount, 0) AS cgst_amount,
        COALESCE(pg.s_tax_amount, 0) AS sgst_amount,
        (COALESCE(pg.i_tax_amount, 0)
         + COALESCE(pg.c_tax_amount, 0)
         + COALESCE(pg.s_tax_amount, 0)) AS tax_amount
    FROM proc_po_additional AS ppa
    LEFT JOIN additional_charges_mst AS acm ON acm.additional_charges_id = ppa.additional_charges_id
    LEFT JOIN po_gst AS pg ON pg.po_additional_id = ppa.po_additional_id
    WHERE ppa.po_id = :po_id
    ORDER BY ppa.po_additional_id;"""
    return text(sql)


def count_active_po_dtl_query():
    """Count active PO line items for a given PO ID (used for SR coverage check)."""
    return text("""
        SELECT COUNT(*) AS total
        FROM proc_po_dtl
        WHERE po_id = :po_id AND active = 1
    """)


def get_po_gst_by_id_query():
    """Get PO GST records by PO ID."""
    sql = """SELECT
        pg.po_gst_id,
        pg.po_dtl_id,
        pg.po_additional_id,
        pg.tax_pct,
        pg.stax_percentage,
        pg.s_tax_amount,
        pg.i_tax_amount,
        pg.i_tax_percentage,
        pg.c_tax_amount,
        pg.c_tax_percentage,
        pg.tax_amount
    FROM po_gst AS pg
    WHERE pg.po_dtl_id IN (
        SELECT po_dtl_id FROM proc_po_dtl WHERE po_id = :po_id
    ) OR pg.po_additional_id IN (
        SELECT po_additional_id FROM proc_po_additional WHERE po_id = :po_id
    )
    ORDER BY pg.po_gst_id;"""
    return text(sql)


def get_max_po_no_for_branch_fy():
    """Get the maximum po_no for a branch within a financial year.
    
    Financial year: April 1 to March 31
    - If month >= 4 (April-December): FY = year-04-01 to (year+1)-03-31
    - If month < 4 (January-March): FY = (year-1)-04-01 to year-03-31
    """
    sql = """SELECT COALESCE(MAX(pp.po_no), 0) as max_po_no
    FROM proc_po pp
    WHERE pp.branch_id = :branch_id
        AND pp.po_date >= :fy_start_date
        AND pp.po_date <= :fy_end_date
        AND pp.po_no IS NOT NULL;"""
    return text(sql)


def get_max_inward_no_for_branch_fy():
    """Get the maximum inward_sequence_no for a branch within a financial year.

    Financial year: April 1 to March 31
    - If month >= 4 (April-December): FY = year-04-01 to (year+1)-03-31
    - If month < 4 (January-March): FY = (year-1)-04-01 to year-03-31
    """
    sql = """SELECT COALESCE(MAX(CAST(pi.inward_sequence_no AS UNSIGNED)), 0) as max_inward_no
    FROM proc_inward pi
    WHERE pi.branch_id = :branch_id
        AND pi.inward_date >= :fy_start_date
        AND pi.inward_date <= :fy_end_date
        AND pi.inward_sequence_no IS NOT NULL
        AND pi.inward_sequence_no REGEXP '^[0-9]+$';"""
    return text(sql)


def get_po_with_approval_info():
    """Get PO details including approval level and status."""
    sql = """SELECT
        pp.po_id,
        pp.status_id,
        pp.approval_level,
        pp.branch_id,
        pp.po_date,
        pp.po_no,
        pp.total_amount,
        bm.co_id
    FROM proc_po pp
    LEFT JOIN branch_mst bm ON bm.branch_id = pp.branch_id
    WHERE pp.po_id = :po_id;"""
    return text(sql)


def get_po_header_query():
    """Get PO header by ID for cloning (simplified, no co_id filter)."""
    sql = """SELECT
        pp.po_id,
        pp.po_no,
        pp.po_date,
        pp.branch_id,
        pp.supplier_id,
        pp.supplier_branch_id,
        pp.billing_branch_id,
        pp.shipping_branch_id,
        pp.project_id,
        pp.credit_days,
        pp.expected_delivery_days,
        pp.contact_person,
        pp.contact_no,
        pp.footer_notes,
        pp.remarks,
        pp.terms_conditions,
        pp.delivery_mode,
        pp.delivery_instructions,
        pp.total_amount,
        pp.net_amount,
        pp.advance_type,
        pp.advance_value,
        pp.advance_amount,
        pp.status_id,
        pp.expense_type_id
    FROM proc_po AS pp
    WHERE pp.po_id = :po_id;"""
    return text(sql)


def get_po_dtl_query():
    """Get PO line items by PO ID for cloning."""
    sql = """SELECT
        pod.po_dtl_id,
        pod.po_id,
        pod.item_id,
        pod.item_group_id,
        pod.item_make_id,
        pod.item_code,
        pod.item_name,
        pod.quantity,
        pod.uom_id,
        pod.rate,
        pod.amount,
        pod.discount_type,
        pod.discount_value,
        pod.discount_amount,
        pod.net_amount,
        pod.remarks,
        pod.department_id,
        pod.indent_dtl_id
    FROM proc_po_dtl AS pod
    WHERE pod.po_id = :po_id;"""
    return text(sql)


def get_po_consumed_amounts():
    """Get total PO amounts approved by a user for the current day and month.
    Used for daily/monthly value-based approval limit enforcement.
    """
    sql = """SELECT
        COALESCE(SUM(CASE
            WHEN DATE(pp.updated_date_time) = CURDATE()
            THEN pp.total_amount ELSE 0 END), 0) as day_total,
        COALESCE(SUM(CASE
            WHEN YEAR(pp.updated_date_time) = YEAR(CURDATE())
            AND MONTH(pp.updated_date_time) = MONTH(CURDATE())
            THEN pp.total_amount ELSE 0 END), 0) as month_total
    FROM proc_po pp
    WHERE pp.updated_by = :user_id
        AND pp.status_id = 3;"""
    return text(sql)


def update_po_status():
    """Update PO status and approval level. Optionally update po_no."""
    sql = """UPDATE proc_po SET
        status_id = :status_id,
        approval_level = :approval_level,
        updated_by = :updated_by,
        updated_date_time = :updated_date_time,
        po_no = CASE 
            WHEN :po_no IS NOT NULL THEN :po_no 
            ELSE po_no 
        END
    WHERE po_id = :po_id;"""
    return text(sql)


def get_approved_pos_by_supplier_query():
    """
    Get approved POs for a specific supplier that have pending items to receive.
    
    Search parameters:
    - supplier_id (required): Filter by supplier
    - branch_id (optional): Filter by branch
    - status_id = 3 (hardcoded): Only approved POs
    
    Returns fields needed for PO number formatting (extract_formatted_po_no):
    - po_no, po_date, co_prefix, branch_prefix
    
    Also returns display fields for dropdown selection.
    """
    sql = """SELECT DISTINCT
        pp.po_id,
        pp.po_no,
        pp.po_date,
        pp.branch_id,
        bm.branch_name,
        bm.branch_prefix,
        cm.co_prefix,
        pp.supplier_id,
        pm.supp_name AS supplier_name
    FROM proc_po pp
    INNER JOIN branch_mst bm ON bm.branch_id = pp.branch_id
    INNER JOIN party_mst pm ON pm.party_id = pp.supplier_id
    INNER JOIN co_mst cm ON cm.co_id = bm.co_id
    WHERE pp.supplier_id = :supplier_id
        AND pp.status_id = 3
        AND (:branch_id IS NULL OR pp.branch_id = :branch_id)
        AND EXISTS (
            SELECT 1 FROM proc_po_dtl pod
            WHERE pod.po_id = pp.po_id
                AND pod.active = 1
                AND (pod.qty - COALESCE((
                    SELECT SUM(pid.inward_qty)
                    FROM proc_inward_dtl pid
                    WHERE pid.po_dtl_id = pod.po_dtl_id AND pid.active = 1
                ), 0)) > 0
        )
    ORDER BY pp.po_date DESC, pp.po_id DESC;"""
    return text(sql)


def get_po_line_items_for_inward_query():
    """
    Get PO line items for inward/GRN entry with pending quantities.
    Calculates pending qty as (ordered_qty - received_qty).
    Only returns items with pending_qty > 0.
    """
    sql = """SELECT
        pod.po_dtl_id,
        pod.po_id,
        pp.po_no,
        pp.po_date,
        pod.item_id,
        im.item_code,
        im.item_name,
        im.item_grp_id AS item_grp_id,
        ig.item_grp_code,
        ig.item_grp_name,
        vip.full_item_code,
        pod.item_make_id,
        imk.item_make_name,
        pod.qty AS ordered_qty,
        pod.uom_id,
        um.uom_name,
        pod.rate,
        pod.remarks,
        pod.hsn_code,
        im.tax_percentage,
        COALESCE(recv.received_qty, 0) AS received_qty,
        (pod.qty - COALESCE(recv.received_qty, 0)) AS pending_qty,
        (pod.qty * pod.rate) AS amount,
        bm.branch_prefix,
        cm.co_prefix
    FROM proc_po_dtl pod
    INNER JOIN proc_po pp ON pp.po_id = pod.po_id
    INNER JOIN item_mst im ON im.item_id = pod.item_id
    LEFT JOIN item_grp_mst ig ON ig.item_grp_id = im.item_grp_id
    LEFT JOIN vw_item_with_group_path AS vip ON vip.item_id = im.item_id
    LEFT JOIN item_make imk ON imk.item_make_id = pod.item_make_id
    LEFT JOIN uom_mst um ON um.uom_id = pod.uom_id
    LEFT JOIN branch_mst bm ON bm.branch_id = pp.branch_id
    LEFT JOIN co_mst cm ON cm.co_id = bm.co_id
    LEFT JOIN (
        SELECT po_dtl_id, COALESCE(SUM(inward_qty), 0) as received_qty
        FROM proc_inward_dtl
        WHERE active = 1
        GROUP BY po_dtl_id
    ) recv ON recv.po_dtl_id = pod.po_dtl_id
    WHERE pod.po_id = :po_id
        AND pod.active = 1
        AND (pod.qty - COALESCE(recv.received_qty, 0)) > 0
    ORDER BY pod.po_dtl_id;"""
    return text(sql)


def insert_proc_inward():
    """Insert a new proc_inward header record."""
    sql = """INSERT INTO proc_inward (
    inward_sequence_no,
    supplier_id,
    supplier_branch_id,
    vehicle_number,
    driver_name,
    driver_contact_number,
    inward_date,
    despatch_remarks,
    receipts_remarks,
    updated_date_time,
    updated_by,
    challan_no,
    challan_date,
    invoice_no,
    invoice_amount,
    invoice_date,
    invoice_recvd_date,
    consignment_no,
    consignment_date,
    ewaybillno,
    ewaybill_date,
    bill_branch_id,
    ship_branch_id,
    branch_id,
    project_id,
    gross_amount,
    net_amount
) VALUES (
    :inward_sequence_no,
    :supplier_id,
    :supplier_branch_id,
    :vehicle_number,
    :driver_name,
    :driver_contact_number,
    :inward_date,
    :despatch_remarks,
    :receipts_remarks,
    :updated_date_time,
    :updated_by,
    :challan_no,
    :challan_date,
    :invoice_no,
    :invoice_amount,
    :invoice_date,
    :invoice_recvd_date,
    :consignment_no,
    :consignment_date,
    :ewaybillno,
    :ewaybill_date,
    :bill_branch_id,
    :ship_branch_id,
    :branch_id,
    :project_id,
    :gross_amount,
    :net_amount
);"""
    return text(sql)


def insert_proc_inward_dtl():
    """Insert a new proc_inward_dtl line item record."""
    sql = """INSERT INTO proc_inward_dtl (
    inward_id,
    po_dtl_id,
    item_id,
    item_make_id,
    hsn_code,
    description,
    remarks,
    challan_qty,
    inward_qty,
    uom_id,
    rate,
    amount,
    warehouse_id,
    active,
    status_id,
    updated_date_time,
    updated_by
) VALUES (
    :inward_id,
    :po_dtl_id,
    :item_id,
    :item_make_id,
    :hsn_code,
    :description,
    :remarks,
    :challan_qty,
    :inward_qty,
    :uom_id,
    :rate,
    :amount,
    :warehouse_id,
    :active,
    :status_id,
    :updated_date_time,
    :updated_by
);"""
    return text(sql)


def update_proc_inward():
    """Update an existing proc_inward header record."""
    sql = """UPDATE proc_inward SET
    supplier_id = :supplier_id,
    vehicle_number = :vehicle_number,
    driver_name = :driver_name,
    driver_contact_number = :driver_contact_number,
    inward_date = :inward_date,
    despatch_remarks = :despatch_remarks,
    receipts_remarks = :receipts_remarks,
    challan_no = :challan_no,
    challan_date = :challan_date,
    invoice_no = :invoice_no,
    invoice_date = :invoice_date,
    invoice_recvd_date = :invoice_recvd_date,
    consignment_no = :consignment_no,
    consignment_date = :consignment_date,
    ewaybillno = :ewaybillno,
    ewaybill_date = :ewaybill_date,
    branch_id = :branch_id,
    updated_date_time = :updated_date_time,
    updated_by = :updated_by
WHERE inward_id = :inward_id;"""
    return text(sql)


def update_proc_inward_dtl():
    """Update an existing proc_inward_dtl line item record."""
    sql = """UPDATE proc_inward_dtl SET
    item_id = :item_id,
    hsn_code = :hsn_code,
    remarks = :remarks,
    challan_qty = :inward_qty,
    inward_qty = :inward_qty,
    uom_id = :uom_id,
    updated_date_time = :updated_date_time,
    updated_by = :updated_by
WHERE inward_dtl_id = :inward_dtl_id;"""
    return text(sql)


# =============================================================================
# PO NUMBER LOOKUP UTILITY
# =============================================================================

def get_po_number_by_dtl_id_query():
    """Get formatted PO number from po_dtl_id. Joins proc_po_dtl → proc_po."""
    sql = """SELECT 
        pp.po_id,
        pp.po_no,
        pp.po_date,
        bm.branch_prefix,
        cm.co_prefix
    FROM proc_po_dtl AS ppd
    JOIN proc_po AS pp ON pp.po_id = ppd.po_id
    LEFT JOIN branch_mst AS bm ON bm.branch_id = pp.branch_id
    LEFT JOIN co_mst AS cm ON cm.co_id = bm.co_id
    WHERE ppd.po_dtl_id = :po_dtl_id;"""
    return text(sql)


# =============================================================================
# MATERIAL INSPECTION QUERIES
# =============================================================================

def get_pending_inspection_list_query():
    """Get list of inwards pending material inspection (inspection_check = false)."""
    sql = """SELECT
        pi.inward_id,
        pi.inward_sequence_no,
        pi.inward_date,
        pi.branch_id,
        bm.branch_name,
        bm.branch_prefix,
        bm.co_id,
        cm.co_prefix,
        pi.supplier_id,
        pm.supp_name AS supplier_name,
        pi.inspection_check,
        pi.inspection_date AS material_inspection_date,
        sm.status_name AS sr_status_name
    FROM proc_inward AS pi
    LEFT JOIN branch_mst AS bm ON bm.branch_id = pi.branch_id
    LEFT JOIN co_mst AS cm ON cm.co_id = bm.co_id
    LEFT JOIN party_mst AS pm ON pm.party_id = pi.supplier_id
    LEFT JOIN status_mst AS sm ON sm.status_id = pi.sr_status
    WHERE (:co_id IS NULL OR bm.co_id = :co_id)
        AND (pi.inspection_check IS NULL OR pi.inspection_check = FALSE)
        AND EXISTS (
            SELECT 1 FROM proc_inward_dtl pid
            WHERE pid.inward_id = pi.inward_id AND pid.status_id <> 6
        )
        AND (
            :search_like IS NULL
            OR pi.inward_sequence_no LIKE :search_like
            OR pm.supp_name LIKE :search_like
            OR bm.branch_name LIKE :search_like
        )
    ORDER BY pi.inward_date DESC, pi.inward_id DESC
    LIMIT :limit OFFSET :offset;"""
    return text(sql)


def get_pending_inspection_count_query():
    """Count inwards pending material inspection."""
    sql = """SELECT COUNT(1) AS total
    FROM proc_inward AS pi
    LEFT JOIN branch_mst AS bm ON bm.branch_id = pi.branch_id
    LEFT JOIN party_mst AS pm ON pm.party_id = pi.supplier_id
    WHERE (:co_id IS NULL OR bm.co_id = :co_id)
        AND (pi.inspection_check IS NULL OR pi.inspection_check = FALSE)
        AND EXISTS (
            SELECT 1 FROM proc_inward_dtl pid
            WHERE pid.inward_id = pi.inward_id AND pid.status_id <> 6
        )
        AND (
            :search_like IS NULL
            OR pi.inward_sequence_no LIKE :search_like
            OR pm.supp_name LIKE :search_like
            OR bm.branch_name LIKE :search_like
        );"""
    return text(sql)


def get_inward_for_inspection_query():
    """Get inward header details for material inspection edit page."""
    sql = """SELECT
        pi.inward_id,
        pi.inward_sequence_no,
        pi.inward_date,
        pi.branch_id,
        bm.branch_name,
        bm.branch_prefix,
        bm.co_id,
        cm.co_prefix,
        pi.supplier_id,
        pm.supp_name AS supplier_name,
        pi.inspection_check,
        pi.inspection_date AS material_inspection_date,
        pi.inspection_approved_by,
        pi.challan_no,
        pi.challan_date
    FROM proc_inward AS pi
    LEFT JOIN branch_mst AS bm ON bm.branch_id = pi.branch_id
    LEFT JOIN co_mst AS cm ON cm.co_id = bm.co_id
    LEFT JOIN party_mst AS pm ON pm.party_id = pi.supplier_id
    WHERE pi.inward_id = :inward_id
        AND (:co_id IS NULL OR bm.co_id = :co_id);"""
    return text(sql)


def get_inward_dtl_for_inspection_query():
    """Get inward line items for material inspection with approved/rejected qty fields."""
    sql = """SELECT
        pid.inward_dtl_id,
        pid.inward_id,
        pid.po_dtl_id,
        ppd.po_id,
        pp.po_no,
        pp.po_date,
        bm.branch_prefix,
        cm.co_prefix,
        pid.item_id,
        im.item_code,
        im.item_name,
        im.item_grp_id,
        ig.item_grp_code,
        ig.item_grp_name,
        vip.full_item_code,
        pid.item_make_id,
        imk.item_make_name AS item_make_name,
        pid.accepted_item_make_id,
        aimk.item_make_name AS accepted_item_make_name,
        pid.uom_id,
        um.uom_name,
        pid.inward_qty,
        pid.approved_qty,
        pid.rejected_qty,
        pid.reasons,
        pid.remarks,
        pid.rate
    FROM proc_inward_dtl AS pid
    LEFT JOIN item_mst AS im ON im.item_id = pid.item_id
    LEFT JOIN item_grp_mst AS ig ON ig.item_grp_id = im.item_grp_id
    LEFT JOIN vw_item_with_group_path AS vip ON vip.item_id = pid.item_id
    LEFT JOIN item_make AS imk ON imk.item_make_id = pid.item_make_id
    LEFT JOIN item_make AS aimk ON aimk.item_make_id = pid.accepted_item_make_id
    LEFT JOIN uom_mst AS um ON um.uom_id = pid.uom_id
    LEFT JOIN proc_po_dtl AS ppd ON ppd.po_dtl_id = pid.po_dtl_id
    LEFT JOIN proc_po AS pp ON pp.po_id = ppd.po_id
    LEFT JOIN branch_mst AS bm ON bm.branch_id = pp.branch_id
    LEFT JOIN co_mst AS cm ON cm.co_id = bm.co_id
    WHERE pid.inward_id = :inward_id
        AND pid.active = 1
    ORDER BY pid.inward_dtl_id;"""
    return text(sql)


def update_inward_dtl_inspection():
    """Update inward detail with inspection results."""
    sql = """UPDATE proc_inward_dtl
    SET 
        approved_qty = :approved_qty,
        rejected_qty = :rejected_qty,
        accepted_item_make_id = :accepted_item_make_id,
        reasons = :reasons,
        remarks = :remarks,
        updated_by = :updated_by,
        updated_date_time = :updated_date_time
    WHERE inward_dtl_id = :inward_dtl_id;"""
    return text(sql)


def update_inward_inspection_complete():
    """Mark inward as inspection complete."""
    sql = """UPDATE proc_inward
    SET 
        inspection_check = TRUE,
        inspection_date = :inspection_date,
        inspection_approved_by = :inspection_approved_by,
        updated_by = :updated_by,
        updated_date_time = :updated_date_time
    WHERE inward_id = :inward_id;"""
    return text(sql)


# =============================================================================
# STORES RECEIPT (SR) QUERIES
# =============================================================================

def get_sr_pending_list_query():
    """Get list of inwards ready for SR (inspection_check = true, sr_status is null or draft)."""
    sql = """SELECT
        pi.inward_id,
        pi.inward_sequence_no,
        pi.inward_date,
        pi.branch_id,
        bm.branch_name,
        bm.branch_prefix,
        bm.co_id,
        cm.co_prefix,
        pi.supplier_id,
        pm.supp_name AS supplier_name,
        pi.inspection_check,
        pi.inspection_date AS material_inspection_date,
        pi.sr_no,
        pi.sr_date,
        pi.sr_status,
        sm.status_name AS sr_status_name
    FROM proc_inward AS pi
    LEFT JOIN branch_mst AS bm ON bm.branch_id = pi.branch_id
    LEFT JOIN co_mst AS cm ON cm.co_id = bm.co_id
    LEFT JOIN party_mst AS pm ON pm.party_id = pi.supplier_id
    LEFT JOIN status_mst AS sm ON sm.status_id = pi.sr_status
    WHERE (:co_id IS NULL OR bm.co_id = :co_id)
        AND pi.inspection_check = TRUE
        AND (
            :search_like IS NULL
            OR pi.inward_sequence_no LIKE :search_like
            OR pi.sr_no LIKE :search_like
            OR pm.supp_name LIKE :search_like
            OR bm.branch_name LIKE :search_like
        )
    ORDER BY pi.inward_date DESC, pi.inward_id DESC
    LIMIT :limit OFFSET :offset;"""
    return text(sql)


def get_sr_pending_count_query():
    """Count inwards ready for SR."""
    sql = """SELECT COUNT(1) AS total
    FROM proc_inward AS pi
    LEFT JOIN branch_mst AS bm ON bm.branch_id = pi.branch_id
    LEFT JOIN party_mst AS pm ON pm.party_id = pi.supplier_id
    WHERE (:co_id IS NULL OR bm.co_id = :co_id)
        AND pi.inspection_check = TRUE
        AND (
            :search_like IS NULL
            OR pi.inward_sequence_no LIKE :search_like
            OR pi.sr_no LIKE :search_like
            OR pm.supp_name LIKE :search_like
            OR bm.branch_name LIKE :search_like
        );"""
    return text(sql)


def get_inward_for_sr_query():
    """Get inward header details for SR page with state info for GST calculation.

    Uses COALESCE to fall back to the linked PO's branch IDs when the inward's
    own supplier_branch_id / bill_branch_id / ship_branch_id are NULL (legacy data
    created before these columns were populated during inward creation).
    """
    sql = """SELECT
        pi.inward_id,
        pi.inward_sequence_no,
        pi.inward_date,
        pi.branch_id,
        bm.branch_name,
        bm.branch_prefix,
        bm.co_id,
        cm.co_prefix,
        pi.supplier_id,
        pm.supp_name AS supplier_name,
        pbm.party_mst_branch_id AS supplier_branch_id,
        pbm.state_id AS supplier_state_id,
        sup_state.state AS supplier_state_name,
        COALESCE(pi.bill_branch_id, linked_po.billing_branch_id, pi.branch_id) AS bill_branch_id,
        bb.branch_name AS billing_branch_name,
        bb.state_id AS billing_state_id,
        bill_state.state AS billing_state_name,
        COALESCE(pi.ship_branch_id, linked_po.shipping_branch_id, pi.branch_id) AS ship_branch_id,
        sb.branch_name AS shipping_branch_name,
        sb.state_id AS shipping_state_id,
        ship_state.state AS shipping_state_name,
        pi.inspection_check,
        pi.inspection_date,
        pi.sr_no,
        pi.sr_date,
        pi.sr_status,
        sm.status_name AS sr_status_name,
        pi.invoice_date,
        pi.invoice_amount,
        pi.invoice_recvd_date,
        pi.invoice_no,
        pi.challan_no,
        pi.challan_date,
        pi.vehicle_number,
        pi.driver_name,
        pi.driver_contact_number AS driver_contact_no,
        pi.consignment_no,
        pi.consignment_date,
        pi.ewaybillno,
        pi.ewaybill_date,
        pi.despatch_remarks,
        pi.receipts_remarks,
        pi.sr_value,
        pi.sr_remarks,
        pi.gross_amount,
        pi.net_amount,
        COALESCE(cc.india_gst, 0) AS india_gst
    FROM proc_inward AS pi
    LEFT JOIN branch_mst AS bm ON bm.branch_id = pi.branch_id
    LEFT JOIN co_mst AS cm ON cm.co_id = bm.co_id
    LEFT JOIN co_config AS cc ON cc.co_id = bm.co_id
    LEFT JOIN party_mst AS pm ON pm.party_id = pi.supplier_id
    LEFT JOIN proc_po AS linked_po ON linked_po.po_id = (
        SELECT ppd.po_id
        FROM proc_inward_dtl pid2
        JOIN proc_po_dtl ppd ON ppd.po_dtl_id = pid2.po_dtl_id
        WHERE pid2.inward_id = pi.inward_id AND pid2.active = 1
        LIMIT 1
    )
    LEFT JOIN party_branch_mst AS pbm ON pbm.party_mst_branch_id = COALESCE(pi.supplier_branch_id, linked_po.supplier_branch_id, """ + _AUTO_SINGLE_SUPPLIER_BRANCH + """)
    LEFT JOIN state_mst AS sup_state ON sup_state.state_id = pbm.state_id
    LEFT JOIN branch_mst AS bb ON bb.branch_id = COALESCE(pi.bill_branch_id, linked_po.billing_branch_id, pi.branch_id)
    LEFT JOIN state_mst AS bill_state ON bill_state.state_id = bb.state_id
    LEFT JOIN branch_mst AS sb ON sb.branch_id = COALESCE(pi.ship_branch_id, linked_po.shipping_branch_id, pi.branch_id)
    LEFT JOIN state_mst AS ship_state ON ship_state.state_id = sb.state_id
    LEFT JOIN status_mst AS sm ON sm.status_id = pi.sr_status
    WHERE pi.inward_id = :inward_id
        AND (:co_id IS NULL OR bm.co_id = :co_id);"""
    return text(sql)


def get_supplier_branches_for_gst_query():
    """Active branches of a supplier for the SR supplier-state picker.

    A direct (no-PO) inward doesn't capture the supplier branch. When the
    supplier has more than one branch the SR page needs these options so the
    user can pick the correct GST state; a single branch is auto-resolved
    upstream in get_inward_for_sr_query.
    """
    sql = """SELECT
        pb.party_mst_branch_id,
        pb.state_id,
        sm.state AS state_name,
        pb.gst_no
    FROM party_branch_mst pb
    LEFT JOIN state_mst sm ON sm.state_id = pb.state_id
    WHERE pb.party_id = :supplier_id AND pb.active = 1
    ORDER BY pb.party_mst_branch_id;"""
    return text(sql)


def get_inward_dtl_for_sr_query():
    """Get inward line items for SR with rate, tax fields, and warehouse hierarchy path."""
    sql = """WITH RECURSIVE warehouse_hierarchy AS (
        SELECT
            wm.warehouse_id,
            wm.warehouse_name,
            wm.parent_warehouse_id,
            CAST(wm.warehouse_name AS CHAR) AS warehouse_path
        FROM warehouse_mst wm
        WHERE wm.parent_warehouse_id IS NULL
        UNION ALL
        SELECT
            child.warehouse_id,
            child.warehouse_name,
            child.parent_warehouse_id,
            CONCAT(parent.warehouse_path, '-', child.warehouse_name)
        FROM warehouse_mst child
        JOIN warehouse_hierarchy parent
            ON child.parent_warehouse_id = parent.warehouse_id
    )
    SELECT
        pid.inward_dtl_id,
        pid.inward_id,
        pid.po_dtl_id,
        ppd.po_id,
        pp.po_no,
        pp.po_date,
        bm_po.branch_prefix,
        cm_po.co_prefix,
        pid.item_id,
        im.item_code,
        im.item_name,
        im.item_grp_id,
        ig.item_grp_code,
        ig.item_grp_name,
        vip.full_item_code,
        pid.item_make_id,
        imk.item_make_name,
        pid.accepted_item_make_id,
        aimk.item_make_name AS accepted_item_make_name,
        pid.uom_id,
        um.uom_name,
        pid.approved_qty,
        pid.rejected_qty,
        pid.hsn_code,
        COALESCE(NULLIF(pid.rate, 0), ppd.rate) AS rate,
        pid.accepted_rate,
        pid.amount,
        COALESCE(pid.discount_mode, ppd.discount_mode) AS discount_mode,
        COALESCE(NULLIF(pid.discount_value, 0), ppd.discount_value) AS discount_value,
        COALESCE(NULLIF(pid.discount_amount, 0), ppd.discount_amount) AS discount_amount,
        pid.remarks,
        pid.warehouse_id,
        wh_hier.warehouse_name,
        wh_hier.warehouse_path,
        ppd.rate AS po_rate,
        CASE
            WHEN psg.tax_pct IS NOT NULL THEN psg.tax_pct
            WHEN pid.po_dtl_id IS NOT NULL THEN COALESCE(pg.tax_pct, 0)
            ELSE COALESCE(im.tax_percentage, 0)
        END AS tax_percentage
    FROM proc_inward_dtl AS pid
    LEFT JOIN proc_po_dtl AS ppd ON ppd.po_dtl_id = pid.po_dtl_id
    LEFT JOIN po_gst AS pg ON pg.po_dtl_id = pid.po_dtl_id AND pg.active = 1
    LEFT JOIN proc_gst AS psg ON psg.proc_inward_dtl = pid.inward_dtl_id AND psg.active = 1
    LEFT JOIN proc_po AS pp ON pp.po_id = ppd.po_id
    LEFT JOIN branch_mst AS bm_po ON bm_po.branch_id = pp.branch_id
    LEFT JOIN co_mst AS cm_po ON cm_po.co_id = bm_po.co_id
    LEFT JOIN item_mst AS im ON im.item_id = pid.item_id
    LEFT JOIN item_grp_mst AS ig ON ig.item_grp_id = im.item_grp_id
    LEFT JOIN vw_item_with_group_path AS vip ON vip.item_id = im.item_id
    LEFT JOIN item_make AS imk ON imk.item_make_id = pid.item_make_id
    LEFT JOIN item_make AS aimk ON aimk.item_make_id = pid.accepted_item_make_id
    LEFT JOIN uom_mst AS um ON um.uom_id = pid.uom_id
    LEFT JOIN warehouse_hierarchy AS wh_hier ON wh_hier.warehouse_id = pid.warehouse_id
    WHERE pid.inward_id = :inward_id
        AND pid.active = 1
    ORDER BY pid.inward_dtl_id;"""
    return text(sql)


def cancel_inward_dtl_query():
    """Cancel all proc_inward_dtl lines for an inward by setting status_id = 6."""
    return text("""
        UPDATE proc_inward_dtl
        SET status_id = 6,
            updated_by = :updated_by,
            updated_date_time = :updated_date_time
        WHERE inward_id = :inward_id
    """)


def update_inward_dtl_sr():
    """Update inward detail with SR rate, discount, and warehouse values."""
    sql = """UPDATE proc_inward_dtl
    SET 
        accepted_rate = :accepted_rate,
        amount = :amount,
        discount_mode = :discount_mode,
        discount_value = :discount_value,
        discount_amount = :discount_amount,
        hsn_code = :hsn_code,
        warehouse_id = :warehouse_id,
        updated_by = :updated_by,
        updated_date_time = :updated_date_time
    WHERE inward_dtl_id = :inward_dtl_id;"""
    return text(sql)


def update_inward_sr():
    """Update inward header with SR details and inward-level corrections."""
    sql = """UPDATE proc_inward
    SET
        sr_no = :sr_no,
        sr_date = :sr_date,
        sr_status = :sr_status,
        sr_value = :sr_value,
        sr_remarks = :sr_remarks,
        sr_approved_by = :sr_approved_by,
        supplier_branch_id = COALESCE(:supplier_branch_id, supplier_branch_id),
        bill_branch_id = :bill_branch_id,
        ship_branch_id = :ship_branch_id,
        invoice_no = :invoice_no,
        invoice_date = :invoice_date,
        invoice_amount = :invoice_amount,
        invoice_recvd_date = :invoice_recvd_date,
        challan_no = :challan_no,
        challan_date = :challan_date,
        vehicle_number = :vehicle_number,
        driver_name = :driver_name,
        driver_contact_number = :driver_contact_number,
        inspection_date = :inspection_date,
        consignment_no = :consignment_no,
        consignment_date = :consignment_date,
        ewaybillno = :ewaybillno,
        ewaybill_date = :ewaybill_date,
        despatch_remarks = :despatch_remarks,
        receipts_remarks = :receipts_remarks,
        gross_amount = :gross_amount,
        net_amount = :net_amount,
        updated_by = :updated_by,
        updated_date_time = :updated_date_time
    WHERE inward_id = :inward_id;"""
    return text(sql)


# =============================================================================
# DRCR NOTE QUERIES
# =============================================================================

def get_drcr_note_list_query():
    """Get list of DRCR notes with pagination."""
    sql = """SELECT
        dn.debit_credit_note_id,
        dn.date AS note_date,
        dn.adjustment_type,
        dn.inward_id,
        pi.inward_sequence_no,
        pi.sr_no,
        bm.branch_prefix,
        cm.co_prefix,
        pi.inward_date,
        pi.supplier_id,
        pm.supp_name AS supplier_name,
        dn.gross_amount,
        dn.net_amount,
        dn.status_id,
        sm.status_name,
        dn.auto_create,
        dn.remarks
    FROM drcr_note AS dn
    LEFT JOIN proc_inward AS pi ON pi.inward_id = dn.inward_id
    LEFT JOIN branch_mst AS bm ON bm.branch_id = pi.branch_id
    LEFT JOIN co_mst AS cm ON cm.co_id = bm.co_id
    LEFT JOIN party_mst AS pm ON pm.party_id = pi.supplier_id
    LEFT JOIN status_mst AS sm ON sm.status_id = dn.status_id
    WHERE (:co_id IS NULL OR bm.co_id = :co_id)
        AND (
            :search_like IS NULL
            OR pi.inward_sequence_no LIKE :search_like
            OR pm.supp_name LIKE :search_like
        )
    ORDER BY dn.date DESC, dn.debit_credit_note_id DESC
    LIMIT :limit OFFSET :offset;"""
    return text(sql)


def get_drcr_note_count_query():
    """Count DRCR notes."""
    sql = """SELECT COUNT(1) AS total
    FROM drcr_note AS dn
    LEFT JOIN proc_inward AS pi ON pi.inward_id = dn.inward_id
    LEFT JOIN branch_mst AS bm ON bm.branch_id = pi.branch_id
    LEFT JOIN party_mst AS pm ON pm.party_id = pi.supplier_id
    WHERE (:co_id IS NULL OR bm.co_id = :co_id)
        AND (
            :search_like IS NULL
            OR pi.inward_sequence_no LIKE :search_like
            OR pm.supp_name LIKE :search_like
        );"""
    return text(sql)


def get_drcr_note_by_id_query():
    """Get DRCR note header by ID."""
    sql = """SELECT
        dn.debit_credit_note_id,
        dn.date AS note_date,
        dn.adjustment_type,
        dn.inward_id,
        pi.inward_sequence_no,
        bm.branch_prefix,
        cm.co_prefix,
        pi.inward_date,
        pi.supplier_id,
        pm.supp_name AS supplier_name,
        dn.gross_amount,
        dn.net_amount,
        dn.round_off_value,
        dn.status_id,
        sm.status_name,
        dn.auto_create,
        dn.remarks,
        dn.approved_by,
        dn.approved_date,
        dn.updated_by,
        dn.updated_date_time,
        pi.invoice_no AS supplier_invoice_no,
        pi.invoice_date AS supplier_invoice_date,
        pi.sr_no,
        pi.sr_date,
        pi.challan_no,
        pi.challan_date,
        pi.branch_id,
        bm.branch_name,
        bm.gst_no AS branch_gst,
        bm.branch_address1,
        bm.branch_address2,
        bm.branch_zipcode,
        pbm.gst_no AS supplier_gst,
        cm.co_name,
        cm.co_address1,
        cm.co_address2,
        cm.co_zipcode
    FROM drcr_note AS dn
    LEFT JOIN proc_inward AS pi ON pi.inward_id = dn.inward_id
    LEFT JOIN branch_mst AS bm ON bm.branch_id = pi.branch_id
    LEFT JOIN co_mst AS cm ON cm.co_id = bm.co_id
    LEFT JOIN party_mst AS pm ON pm.party_id = pi.supplier_id
    LEFT JOIN party_branch_mst AS pbm ON pbm.party_mst_branch_id = pi.supplier_branch_id
    LEFT JOIN status_mst AS sm ON sm.status_id = dn.status_id
    WHERE dn.debit_credit_note_id = :drcr_note_id
        AND (:co_id IS NULL OR bm.co_id = :co_id);"""
    return text(sql)


def get_drcr_note_dtl_query():
    """Get DRCR note line items by note ID."""
    sql = """SELECT
        dnd.drcr_note_dtl_id,
        dnd.inward_dtl_id,
        dnd.debitnote_type,
        dnd.quantity,
        dnd.rate,
        dnd.discount_mode,
        dnd.discount_value,
        dnd.discount_amount,
        pid.item_id,
        im.item_code,
        vip.full_item_code,
        im.item_name,
        ig.item_grp_name,
        pid.uom_id,
        um.uom_name,
        pid.rate AS original_rate,
        pid.accepted_rate,
        pid.rejected_qty,
        pid.approved_qty,
        pid.reasons AS rejection_reason,
        pid.hsn_code,
        pg.tax_pct,
        dndg.cgst_amount,
        dndg.igst_amount,
        dndg.sgst_amount,
        ppd.po_id,
        pp.po_no,
        pp.po_date,
        bm.branch_prefix,
        cm.co_prefix
    FROM drcr_note_dtl AS dnd
    LEFT JOIN proc_inward_dtl AS pid ON pid.inward_dtl_id = dnd.inward_dtl_id
    LEFT JOIN item_mst AS im ON im.item_id = pid.item_id
    LEFT JOIN item_grp_mst AS ig ON ig.item_grp_id = im.item_grp_id
    LEFT JOIN vw_item_with_group_path AS vip ON vip.item_id = im.item_id
    LEFT JOIN uom_mst AS um ON um.uom_id = pid.uom_id
    LEFT JOIN drcr_note_dtl_gst AS dndg ON dndg.drcr_note_dtl_id = dnd.drcr_note_dtl_id
    LEFT JOIN proc_gst AS pg ON pg.proc_inward_dtl = pid.inward_dtl_id AND pg.active = 1
    LEFT JOIN proc_po_dtl AS ppd ON ppd.po_dtl_id = pid.po_dtl_id
    LEFT JOIN proc_po AS pp ON pp.po_id = ppd.po_id
    LEFT JOIN branch_mst AS bm ON bm.branch_id = pp.branch_id
    LEFT JOIN co_mst AS cm ON cm.co_id = bm.co_id
    WHERE dnd.debit_credit_note_id = :drcr_note_id
    ORDER BY dnd.drcr_note_dtl_id;"""
    return text(sql)


def insert_drcr_note():
    """Insert a new DRCR note header."""
    sql = """INSERT INTO drcr_note (
        date,
        adjustment_type,
        inward_id,
        remarks,
        status_id,
        auto_create,
        updated_by,
        updated_date_time,
        gross_amount,
        net_amount
    ) VALUES (
        :note_date,
        :adjustment_type,
        :inward_id,
        :remarks,
        :status_id,
        :auto_create,
        :updated_by,
        :updated_date_time,
        :gross_amount,
        :net_amount
    );"""
    return text(sql)


def insert_drcr_note_dtl():
    """Insert a new DRCR note line item."""
    sql = """INSERT INTO drcr_note_dtl (
        debit_credit_note_id,
        inward_dtl_id,
        debitnote_type,
        quantity,
        rate,
        discount_mode,
        discount_value,
        discount_amount,
        updated_by,
        updated_date_time
    ) VALUES (
        :debit_credit_note_id,
        :inward_dtl_id,
        :debitnote_type,
        :quantity,
        :rate,
        :discount_mode,
        :discount_value,
        :discount_amount,
        :updated_by,
        :updated_date_time
    );"""
    return text(sql)


def insert_drcr_note_dtl_gst():
    """Insert GST record for debit/credit note detail line."""
    sql = """INSERT INTO drcr_note_dtl_gst (
        drcr_note_dtl_id,
        cgst_amount,
        igst_amount,
        sgst_amount,
        active
    ) VALUES (
        :drcr_note_dtl_id,
        :cgst_amount,
        :igst_amount,
        :sgst_amount,
        1
    );"""
    return text(sql)


def update_drcr_note_status():
    """Update DRCR note status (for open/reject transitions)."""
    sql = """UPDATE drcr_note
    SET
        status_id = :status_id,
        updated_by = :updated_by,
        updated_date_time = :updated_date_time
    WHERE debit_credit_note_id = :drcr_note_id;"""
    return text(sql)


def approve_drcr_note_query():
    """Approve DRCR note — sets approver and approved date alongside status."""
    sql = """UPDATE drcr_note
    SET
        status_id = :status_id,
        approved_by = :approved_by,
        approved_date = :approved_date,
        updated_by = :updated_by,
        updated_date_time = :updated_date_time
    WHERE debit_credit_note_id = :drcr_note_id;"""
    return text(sql)


# =============================================================================
# BILL PASS QUERIES
# =============================================================================

def get_bill_pass_list_query():
    """
    Get paginated list of Bill Pass entries (computed view).
    Bill Pass is SR with DRCR note adjustments for final payment.
    Shows only approved SRs.
    """
    sql = """
    SELECT
        pi.inward_id,
        pi.inward_sequence_no,
        pi.inward_date,
        pi.sr_no AS bill_pass_no,
        pi.sr_date AS bill_pass_date,
        pi.invoice_date,
        pi.invoice_amount,
        pi.invoice_no,
        pi.supplier_id,
        pm.supp_name AS supplier_name,
        pi.branch_id,
        bm.branch_name,
        bm.branch_prefix,
        bm.co_id,
        cm.co_prefix,
        pi.sr_status,
        pi.billpass_status,
        sm.status_name AS sr_status_name,
        -- SR Total (sum from proc_inward_dtl - amount after discount + tax)
        COALESCE(sr_totals.sr_total, 0) AS sr_total,
        COALESCE(sr_totals.sr_taxable, 0) AS sr_taxable,
        COALESCE(sr_totals.sr_tax, 0) AS sr_tax,
        -- Debit Note Total (approved only)
        COALESCE(dr_totals.dr_total, 0) AS dr_total,
        COALESCE(dr_totals.dr_count, 0) AS dr_count,
        -- Credit Note Total (approved only)
        COALESCE(cr_totals.cr_total, 0) AS cr_total,
        COALESCE(cr_totals.cr_count, 0) AS cr_count,
        -- Net Payable = SR - DR + CR
        (COALESCE(sr_totals.sr_total, 0) - COALESCE(dr_totals.dr_total, 0) + COALESCE(cr_totals.cr_total, 0)) AS net_payable
    FROM proc_inward pi
    LEFT JOIN party_mst pm ON pm.party_id = pi.supplier_id
    LEFT JOIN branch_mst bm ON bm.branch_id = pi.branch_id
    LEFT JOIN co_mst cm ON cm.co_id = bm.co_id
    LEFT JOIN status_mst sm ON sm.status_id = pi.sr_status
    -- SR totals from inward detail lines + proc_gst for tax
    LEFT JOIN (
        SELECT
            pid.inward_id,
            SUM((COALESCE(pid.approved_qty, 0) * COALESCE(pid.accepted_rate, pid.rate, 0)) - COALESCE(pid.discount_amount, 0)) AS sr_taxable,
            SUM(COALESCE(pg.c_tax_amount, 0) + COALESCE(pg.s_tax_amount, 0) + COALESCE(pg.i_tax_amount, 0)) AS sr_tax,
            SUM(
                ((COALESCE(pid.approved_qty, 0) * COALESCE(pid.accepted_rate, pid.rate, 0)) - COALESCE(pid.discount_amount, 0)) +
                COALESCE(pg.c_tax_amount, 0) + COALESCE(pg.s_tax_amount, 0) + COALESCE(pg.i_tax_amount, 0)
            ) AS sr_total
        FROM proc_inward_dtl pid
        LEFT JOIN proc_gst pg ON pg.proc_inward_dtl = pid.inward_dtl_id AND pg.active = 1
        GROUP BY pid.inward_id
    ) sr_totals ON sr_totals.inward_id = pi.inward_id
    -- Debit Note totals (adjustment_type = 1, status_id = 3 approved)
    LEFT JOIN (
        SELECT
            inward_id,
            SUM(COALESCE(net_amount, gross_amount, 0)) AS dr_total,
            COUNT(*) AS dr_count
        FROM drcr_note
        WHERE adjustment_type = 1 AND status_id = 3
        GROUP BY inward_id
    ) dr_totals ON dr_totals.inward_id = pi.inward_id
    -- Credit Note totals (adjustment_type = 2, status_id = 3 approved)
    LEFT JOIN (
        SELECT
            inward_id,
            SUM(COALESCE(net_amount, gross_amount, 0)) AS cr_total,
            COUNT(*) AS cr_count
        FROM drcr_note
        WHERE adjustment_type = 2 AND status_id = 3
        GROUP BY inward_id
    ) cr_totals ON cr_totals.inward_id = pi.inward_id
    WHERE pi.sr_status = 3  -- Only approved SRs
        AND (:co_id IS NULL OR bm.co_id = :co_id)
        AND (
            :search_like IS NULL
            OR pi.sr_no LIKE :search_like
            OR CAST(pi.inward_sequence_no AS CHAR) LIKE :search_like
            OR pm.supp_name LIKE :search_like
        )
    ORDER BY pi.sr_date DESC, pi.inward_id DESC
    LIMIT :limit OFFSET :offset;
    """
    return text(sql)


def get_bill_pass_count_query():
    """Get total count of Bill Pass entries for pagination."""
    sql = """
    SELECT COUNT(1) AS total
    FROM proc_inward pi
    LEFT JOIN branch_mst bm ON bm.branch_id = pi.branch_id
    LEFT JOIN party_mst pm ON pm.party_id = pi.supplier_id
    WHERE pi.sr_status = 3
        AND (:co_id IS NULL OR bm.co_id = :co_id)
        AND (
            :search_like IS NULL
            OR pi.sr_no LIKE :search_like
            OR CAST(pi.inward_sequence_no AS CHAR) LIKE :search_like
            OR pm.supp_name LIKE :search_like
        );
    """
    return text(sql)


def get_bill_pass_by_id_query():
    """
    Get Bill Pass detail by inward_id.
    Returns header info with SR totals.
    """
    sql = """
    SELECT
        pi.inward_id,
        pi.inward_sequence_no,
        pi.inward_date,
        pi.sr_no AS bill_pass_no,
        pi.sr_date AS bill_pass_date,
        pi.invoice_date,
        pi.invoice_amount,
        pi.invoice_no,
        pi.invoice_recvd_date,
        pi.invoice_due_date,
        pi.supplier_id,
        pm.supp_name AS supplier_name,
        pi.branch_id,
        bm.branch_name,
        bm.branch_prefix,
        bm.co_id,
        cm.co_prefix,
        pi.sr_status,
        pi.billpass_status,
        sm.status_name AS sr_status_name,
        pi.sr_remarks,
        pi.challan_no,
        pi.challan_date,
        pi.round_off_value,
        pi.gross_amount,
        pi.net_amount,
        -- SR totals
        COALESCE(sr_totals.sr_taxable, 0) AS sr_taxable,
        COALESCE(sr_totals.sr_tax, 0) AS sr_tax,
        COALESCE(sr_totals.sr_cgst, 0) AS sr_cgst,
        COALESCE(sr_totals.sr_sgst, 0) AS sr_sgst,
        COALESCE(sr_totals.sr_igst, 0) AS sr_igst,
        COALESCE(sr_totals.sr_total, 0) AS sr_total,
        COALESCE(sr_totals.line_count, 0) AS sr_line_count,
        -- DR/CR totals
        COALESCE(dr_totals.dr_total, 0) AS dr_total,
        COALESCE(dr_totals.dr_count, 0) AS dr_count,
        COALESCE(cr_totals.cr_total, 0) AS cr_total,
        COALESCE(cr_totals.cr_count, 0) AS cr_count,
        -- Additional charges totals
        COALESCE(add_totals.additional_net, 0) AS additional_net,
        COALESCE(add_totals.additional_cgst, 0) AS additional_cgst,
        COALESCE(add_totals.additional_sgst, 0) AS additional_sgst,
        COALESCE(add_totals.additional_igst, 0) AS additional_igst,
        COALESCE(add_totals.additional_tax, 0) AS additional_tax,
        (COALESCE(add_totals.additional_net, 0) + COALESCE(add_totals.additional_tax, 0)) AS additional_total,
        COALESCE(add_totals.additional_count, 0) AS additional_count,
        -- Net payable (includes additional charges net + tax)
        (
            COALESCE(sr_totals.sr_total, 0)
            - COALESCE(dr_totals.dr_total, 0)
            + COALESCE(cr_totals.cr_total, 0)
            + COALESCE(add_totals.additional_net, 0)
            + COALESCE(add_totals.additional_tax, 0)
        ) AS net_payable
    FROM proc_inward pi
    LEFT JOIN party_mst pm ON pm.party_id = pi.supplier_id
    LEFT JOIN branch_mst bm ON bm.branch_id = pi.branch_id
    LEFT JOIN co_mst cm ON cm.co_id = bm.co_id
    LEFT JOIN status_mst sm ON sm.status_id = pi.sr_status
    LEFT JOIN (
        SELECT 
            pid.inward_id,
            COUNT(*) AS line_count,
            SUM((COALESCE(pid.approved_qty, 0) * COALESCE(pid.accepted_rate, pid.rate, 0)) - COALESCE(pid.discount_amount, 0)) AS sr_taxable,
            SUM(COALESCE(pg.c_tax_amount, 0)) AS sr_cgst,
            SUM(COALESCE(pg.s_tax_amount, 0)) AS sr_sgst,
            SUM(COALESCE(pg.i_tax_amount, 0)) AS sr_igst,
            SUM(COALESCE(pg.c_tax_amount, 0) + COALESCE(pg.s_tax_amount, 0) + COALESCE(pg.i_tax_amount, 0)) AS sr_tax,
            SUM(
                ((COALESCE(pid.approved_qty, 0) * COALESCE(pid.accepted_rate, pid.rate, 0)) - COALESCE(pid.discount_amount, 0)) +
                COALESCE(pg.c_tax_amount, 0) + COALESCE(pg.s_tax_amount, 0) + COALESCE(pg.i_tax_amount, 0)
            ) AS sr_total
        FROM proc_inward_dtl pid
        LEFT JOIN proc_gst pg ON pg.proc_inward_dtl = pid.inward_dtl_id AND pg.active = 1
        GROUP BY pid.inward_id
    ) sr_totals ON sr_totals.inward_id = pi.inward_id
    LEFT JOIN (
        SELECT 
            inward_id, 
            SUM(COALESCE(net_amount, gross_amount, 0)) AS dr_total,
            COUNT(*) AS dr_count
        FROM drcr_note
        WHERE adjustment_type = 1 AND status_id = 3
        GROUP BY inward_id
    ) dr_totals ON dr_totals.inward_id = pi.inward_id
    LEFT JOIN (
        SELECT
            inward_id,
            SUM(COALESCE(net_amount, gross_amount, 0)) AS cr_total,
            COUNT(*) AS cr_count
        FROM drcr_note
        WHERE adjustment_type = 2 AND status_id = 3
        GROUP BY inward_id
    ) cr_totals ON cr_totals.inward_id = pi.inward_id
    LEFT JOIN (
        SELECT
            pia.inward_id,
            COUNT(*) AS additional_count,
            SUM(COALESCE(pia.net_amount, 0)) AS additional_net,
            SUM(COALESCE(pg.c_tax_amount, 0)) AS additional_cgst,
            SUM(COALESCE(pg.s_tax_amount, 0)) AS additional_sgst,
            SUM(COALESCE(pg.i_tax_amount, 0)) AS additional_igst,
            SUM(
                COALESCE(pg.c_tax_amount, 0)
                + COALESCE(pg.s_tax_amount, 0)
                + COALESCE(pg.i_tax_amount, 0)
            ) AS additional_tax
        FROM proc_inward_additional pia
        LEFT JOIN proc_gst pg
            ON pg.proc_inward_additional_id = pia.proc_inward_additional_id
            AND pg.active = 1
        GROUP BY pia.inward_id
    ) add_totals ON add_totals.inward_id = pi.inward_id
    WHERE pi.inward_id = :inward_id;
    """
    return text(sql)


def get_bill_pass_sr_lines_query():
    """Get SR line items for Bill Pass detail view."""
    sql = """
    SELECT
        pid.inward_dtl_id,
        pid.item_id,
        COALESCE(NULLIF(pid.hsn_code, ''), NULLIF(ppd.hsn_code, ''), im.hsn_code) AS hsn_code,
        im.item_name,
        im.item_code,
        vip.full_item_code,
        igm.item_grp_name,
        pid.accepted_item_make_id,
        imk.item_make_name AS accepted_make_name,
        pid.uom_id,
        um.uom_name,
        pid.approved_qty,
        pid.rate AS po_rate,
        pid.accepted_rate,
        ((COALESCE(pid.approved_qty, 0) * COALESCE(pid.accepted_rate, pid.rate, 0)) - COALESCE(pid.discount_amount, 0)) AS line_amount,
        pid.discount_mode,
        pid.discount_value,
        pid.discount_amount,
        pg.c_tax_percentage AS cgst_percent,
        pg.c_tax_amount AS cgst_amount,
        pg.stax_percentage AS state_tax_percent,
        pg.s_tax_amount AS sgst_amount,
        pg.i_tax_percentage AS igst_percent,
        pg.i_tax_amount AS igst_amount,
        (COALESCE(pg.c_tax_amount, 0) + COALESCE(pg.s_tax_amount, 0) + COALESCE(pg.i_tax_amount, 0)) AS tax_amount,
        (
            ((COALESCE(pid.approved_qty, 0) * COALESCE(pid.accepted_rate, pid.rate, 0)) - COALESCE(pid.discount_amount, 0)) +
            COALESCE(pg.c_tax_amount, 0) + COALESCE(pg.s_tax_amount, 0) + COALESCE(pg.i_tax_amount, 0)
        ) AS line_total,
        ppd.po_id,
        pp.po_no,
        pp.po_date,
        bm.branch_prefix,
        cm.co_prefix
    FROM proc_inward_dtl pid
    LEFT JOIN proc_gst pg ON pg.proc_inward_dtl = pid.inward_dtl_id AND pg.active = 1
    LEFT JOIN item_mst im ON im.item_id = pid.item_id
    LEFT JOIN item_grp_mst igm ON igm.item_grp_id = im.item_grp_id
    LEFT JOIN vw_item_with_group_path AS vip ON vip.item_id = im.item_id
    LEFT JOIN item_make imk ON imk.item_make_id = pid.accepted_item_make_id
    LEFT JOIN uom_mst um ON um.uom_id = pid.uom_id
    LEFT JOIN proc_po_dtl ppd ON ppd.po_dtl_id = pid.po_dtl_id
    LEFT JOIN proc_po pp ON pp.po_id = ppd.po_id
    LEFT JOIN branch_mst bm ON bm.branch_id = pp.branch_id
    LEFT JOIN co_mst cm ON cm.co_id = bm.co_id
    WHERE pid.inward_id = :inward_id
        AND pid.approved_qty > 0
    ORDER BY pid.inward_dtl_id;
    """
    return text(sql)


def get_bill_pass_drcr_notes_query():
    """Get DRCR notes linked to an inward for Bill Pass detail view."""
    sql = """
    SELECT
        dn.debit_credit_note_id,
        dn.date AS note_date,
        dn.adjustment_type,
        CASE WHEN dn.adjustment_type = 1 THEN 'Debit Note' ELSE 'Credit Note' END AS note_type_name,
        dn.remarks,
        dn.gross_amount,
        dn.net_amount,
        dn.status_id,
        sm.status_name,
        -- Get line item details for each note
        (SELECT COUNT(*) FROM drcr_note_dtl dnd WHERE dnd.debit_credit_note_id = dn.debit_credit_note_id) AS line_count
    FROM drcr_note dn
    LEFT JOIN status_mst sm ON sm.status_id = dn.status_id
    WHERE dn.inward_id = :inward_id
        AND dn.status_id = 3  -- Only approved notes
    ORDER BY dn.adjustment_type, dn.date DESC;
    """
    return text(sql)


def get_bill_pass_drcr_note_lines_query():
    """Get DRCR note line items for Bill Pass detail view."""
    sql = """
    SELECT
        dnd.drcr_note_dtl_id,
        dnd.debit_credit_note_id,
        dnd.inward_dtl_id,
        dnd.debitnote_type,
        CASE
            WHEN dnd.debitnote_type = 1 THEN 'Quantity Rejection'
            WHEN dnd.debitnote_type = 2 THEN 'Rate Difference'
            ELSE 'Other'
        END AS adjustment_reason,
        dnd.quantity,
        dnd.rate,
        dnd.discount_mode,
        dnd.discount_value,
        dnd.discount_amount,
        (dnd.quantity * dnd.rate - COALESCE(dnd.discount_amount, 0)) AS line_amount,
        -- Get item details from inward_dtl
        im.item_name,
        im.item_code,
        vip.full_item_code,
        ppd.po_id,
        pp.po_no,
        pp.po_date,
        bm.branch_prefix,
        cm.co_prefix
    FROM drcr_note_dtl dnd
    LEFT JOIN proc_inward_dtl pid ON pid.inward_dtl_id = dnd.inward_dtl_id
    LEFT JOIN item_mst im ON im.item_id = pid.item_id
    LEFT JOIN vw_item_with_group_path AS vip ON vip.item_id = im.item_id
    LEFT JOIN proc_po_dtl ppd ON ppd.po_dtl_id = pid.po_dtl_id
    LEFT JOIN proc_po pp ON pp.po_id = ppd.po_id
    LEFT JOIN branch_mst bm ON bm.branch_id = pp.branch_id
    LEFT JOIN co_mst cm ON cm.co_id = bm.co_id
    WHERE dnd.debit_credit_note_id IN (
        SELECT debit_credit_note_id
        FROM drcr_note
        WHERE inward_id = :inward_id AND status_id = 3
    )
    ORDER BY dnd.debit_credit_note_id, dnd.drcr_note_dtl_id;
    """
    return text(sql)


def update_bill_pass_query():
    """
    Update bill pass fields on proc_inward.
    Only updates non-NULL parameters (dynamic update pattern).
    """
    sql = """
    UPDATE proc_inward
    SET
        invoice_no = COALESCE(:invoice_no, invoice_no),
        invoice_date = COALESCE(:invoice_date, invoice_date),
        invoice_amount = COALESCE(:invoice_amount, invoice_amount),
        invoice_recvd_date = COALESCE(:invoice_recvd_date, invoice_recvd_date),
        invoice_due_date = COALESCE(:invoice_due_date, invoice_due_date),
        round_off_value = COALESCE(:round_off_value, round_off_value),
        sr_remarks = COALESCE(:sr_remarks, sr_remarks),
        billpass_status = COALESCE(:billpass_status, billpass_status),
        billpass_date = COALESCE(:billpass_date, billpass_date),
        updated_by = :updated_by,
        updated_date_time = NOW()
    WHERE inward_id = :inward_id
        AND sr_status = 3;
    """
    return text(sql)


# =============================================================================
# ADDITIONAL CHARGES QUERIES
# =============================================================================

def get_additional_charges_mst_list():
    """Get list of all additional charges from master table."""
    sql = """
    SELECT 
        additional_charges_id,
        additional_charges_name,
        default_value
    FROM additional_charges_mst
    ORDER BY additional_charges_name;
    """
    return text(sql)


def get_inward_additional_charges_query():
    """Get additional charges for an inward/SR by inward_id, including GST from proc_gst."""
    sql = """
    SELECT
        pia.proc_inward_additional_id,
        pia.inward_id,
        pia.additional_charges_id,
        acm.additional_charges_name,
        acm.default_value AS default_tax_pct,
        pia.qty,
        pia.rate,
        pia.net_amount,
        pia.remarks,
        pg.tax_pct,
        pg.i_tax_amount AS igst_amount,
        pg.s_tax_amount AS sgst_amount,
        pg.c_tax_amount AS cgst_amount,
        pg.tax_amount
    FROM proc_inward_additional pia
    LEFT JOIN additional_charges_mst acm
        ON acm.additional_charges_id = pia.additional_charges_id
    LEFT JOIN proc_gst pg
        ON pg.proc_inward_additional_id = pia.proc_inward_additional_id
        AND pg.active = 1
    WHERE pia.inward_id = :inward_id
    ORDER BY pia.proc_inward_additional_id;
    """
    return text(sql)


def insert_inward_additional():
    """Insert a new additional charge for inward/SR."""
    sql = """
    INSERT INTO proc_inward_additional (
        inward_id,
        additional_charges_id,
        qty,
        rate,
        net_amount,
        remarks
    ) VALUES (
        :inward_id,
        :additional_charges_id,
        :qty,
        :rate,
        :net_amount,
        :remarks
    );
    """
    return text(sql)


def delete_inward_additional_by_inward():
    """Delete all additional charges for an inward (delete-all + re-insert pattern)."""
    sql = """
    DELETE FROM proc_inward_additional
    WHERE inward_id = :inward_id;
    """
    return text(sql)


def delete_proc_gst_for_sr_additional_charges():
    """Delete GST records linked to additional charges for a given inward."""
    sql = """DELETE FROM proc_gst
    WHERE proc_inward_additional_id IN (
        SELECT proc_inward_additional_id FROM proc_inward_additional WHERE inward_id = :inward_id
    );"""
    return text(sql)


# =============================================================================
# INDENT LINE ITEM VALIDATION QUERIES
# =============================================================================

def get_item_validation_data():
    """
    DEPRECATED — use get_item_validation_data_v2() which reads from
    the pre-aggregated view vw_item_balance_qty_by_branch_new.
    Kept for rollback safety.

    Get validation data for an item at a given branch:
    - Branch stock from vw_item_balance_qty_by_branch
    - Min/max/reorder from item_minmax_mst
    - Total outstanding indent qty from vw_proc_indent_outstanding
    - Whether an open indent exists for this item at this branch
    """
    sql = """
    SELECT
        COALESCE(stock.total_balance_qty, 0) AS branch_stock,
        imm.minqty,
        imm.maxqty,
        imm.min_order_qty,
        imm.lead_time,
        COALESCE(oi.outstanding_qty, 0) AS outstanding_indent_qty
    FROM (SELECT 1 AS dummy) d
    LEFT JOIN vw_item_balance_qty_by_branch stock
        ON stock.branch_id = :branch_id AND stock.item_id = :item_id
    LEFT JOIN item_minmax_mst imm
        ON imm.branch_id = :branch_id AND imm.item_id = :item_id AND imm.active = 1
    LEFT JOIN (
        SELECT SUM(v.Bal_ind_qty) AS outstanding_qty
        FROM vw_proc_indent_outstanding v
        JOIN proc_indent_dtl pid ON pid.indent_dtl_id = v.indent_dtl_id AND pid.active = 1
        JOIN proc_indent pi ON pi.indent_id = pid.indent_id AND pi.branch_id = :branch_id
        WHERE v.item_id = :item_id
          AND v.status_id NOT IN (4, 5, 6)
    ) oi ON 1 = 1;
    """
    return text(sql)


def get_item_fy_indent_check():
    """
    Check if an open-type indent already exists for the item
    within the current financial year at the given branch.
    Returns the matching indent number if found.
    """
    sql = """
    SELECT pi.indent_id, pi.indent_no, pi.status_id, pi.indent_date
    FROM proc_indent_dtl pid
    JOIN proc_indent pi ON pi.indent_id = pid.indent_id
    WHERE pid.item_id = :item_id
      AND pid.active = 1
      AND pi.branch_id = :branch_id
      AND pi.indent_type_id = 'Open'
      AND pi.status_id NOT IN (4, 5, 6)
      AND pi.indent_date >= :fy_start
      AND pi.indent_date <= :fy_end
    LIMIT 1;
    """
    return text(sql)


def get_item_regular_bom_outstanding():
    """
    DEPRECATED — the v2 validation query (get_item_validation_data_v2)
    returns regular_bom_outstanding directly from the aggregate view.
    Kept for rollback safety.

    Get outstanding indent qty from Regular/BOM indents only
    for the same item at a given branch. Used by Logic 2 (Open indent)
    to show an informational warning.
    """
    sql = """
    SELECT COALESCE(SUM(v.Bal_ind_qty), 0) AS regular_bom_outstanding
    FROM vw_proc_indent_outstanding v
    JOIN proc_indent_dtl pid ON pid.indent_dtl_id = v.indent_dtl_id AND pid.active = 1
    JOIN proc_indent pi ON pi.indent_id = pid.indent_id AND pi.branch_id = :branch_id
    WHERE v.item_id = :item_id
      AND v.indent_type_id IN ('Regular', 'BOM')
      AND v.status_id NOT IN (4, 5, 6);
    """
    return text(sql)


def get_expense_type_name_by_id():
    """Get expense type name by ID."""
    sql = """
    SELECT expense_type_name
    FROM expense_type_mst
    WHERE expense_type_id = :expense_type_id AND active = 1;
    """
    return text(sql)


# =============================================================================
# PO LINE ITEM VALIDATION QUERIES
# =============================================================================

def get_outstanding_po_qty():
    """
    DEPRECATED — use get_outstanding_po_qty_v2() which reads from
    the pre-aggregated view vw_item_balance_qty_by_branch_new.
    Kept for rollback safety.

    Compute the total outstanding (unreceived) PO quantity for a specific item
    at a given branch, across all active POs (status NOT IN 4=rejected, 5=closed, 6=cancelled).

    Outstanding qty per PO line = po_dtl.qty - SUM(approved inward qty linked to that PO line).
    Aggregated across all active PO lines for the item+branch.
    """
    sql = """
    SELECT COALESCE(SUM(ppd.qty - COALESCE(rcv.rcv_qty, 0)), 0) AS outstanding_po_qty
    FROM proc_po_dtl ppd
    JOIN proc_po pp ON pp.po_id = ppd.po_id
    LEFT JOIN (
        SELECT po_dtl_id, SUM(approved_qty) AS rcv_qty
        FROM proc_inward_dtl
        WHERE active = 1
        GROUP BY po_dtl_id
    ) rcv ON rcv.po_dtl_id = ppd.po_dtl_id
    WHERE ppd.item_id = :item_id
      AND pp.branch_id = :branch_id
      AND ppd.active = 1
      AND pp.status_id NOT IN (4, 5, 6);
    """
    return text(sql)


def check_open_po_for_item():
    """
    DEPRECATED — use check_open_po_for_item_v2() which reads
    from vw_proc_po_outstanding_new.
    Kept for rollback safety.

    Check if any active (non-rejected, non-closed, non-cancelled) PO already
    exists for a given item_id + branch_id.
    Returns po_id and po_no of the first match, or no rows if none found.
    Used in Direct PO Logic 1 Step 2.
    """
    sql = """
    SELECT pp.po_id, pp.po_no
    FROM proc_po_dtl ppd
    JOIN proc_po pp ON pp.po_id = ppd.po_id
    WHERE ppd.item_id = :item_id
      AND pp.branch_id = :branch_id
      AND ppd.active = 1
      AND pp.status_id NOT IN (4, 5, 6)
    LIMIT 1;
    """
    return text(sql)


def get_po_fy_check():
    """
    DEPRECATED — use get_po_fy_check_v2() which reads from
    vw_proc_po_outstanding_new (has po_date + po_type columns).
    Kept for rollback safety.

    Check if an open (non-rejected, non-closed, non-cancelled) PO already exists
    for a given item_id + branch_id within the current financial year
    (po_date between :fy_start and :fy_end).
    Returns po_id and po_no of the first match, or no rows if none found.
    Used in Direct PO Logic 2 Step 1.
    """
    sql = """
    SELECT pp.po_id, pp.po_no
    FROM proc_po_dtl ppd
    JOIN proc_po pp ON pp.po_id = ppd.po_id
    WHERE ppd.item_id = :item_id
      AND pp.branch_id = :branch_id
      AND ppd.active = 1
      AND pp.status_id NOT IN (4, 5, 6)
      AND pp.po_date >= :fy_start
      AND pp.po_date <= :fy_end
    LIMIT 1;
    """
    return text(sql)


# =============================================================================
# V2 INDENT VALIDATION QUERIES (using new aggregate views)
# =============================================================================
# These replace the original validation queries above by reading from
# pre-computed views instead of ad-hoc multi-table joins.  The old functions
# are kept (deprecated) for rollback safety.
# =============================================================================

def get_item_validation_data_v2():
    """
    V2: Get validation data for an item at a given branch from the
    pre-aggregated view `vw_item_balance_qty_by_branch_new`.

    This single SELECT replaces the 3-way LEFT JOIN in
    get_item_validation_data() — stock, min/max, and outstanding indent
    qty are all pre-computed in the view.

    Returned columns (raw view data):
        cur_stock          → branch_stock
        maxqty, minqty, min_order_qty  → unchanged
        bal_qty_ind_to_validate → outstanding_indent_qty  (Regular/BOM only — used for validation)
        bal_qty_ind_to_validate → regular_bom_outstanding (same value, kept for backward compat)
        bal_tot_ind_qty    → total_all_indent_outstanding  (all types incl. Open — informational only)
        open_bal_ind_tot_qty   → open_indent_outstanding
        bal_tot_po_qty     → total outstanding PO qty
        bal_qty_po_to_validate → po_outstanding_to_validate (Regular POs only — used for max recalc)

    Pre-computed validation columns (added 2026-02-24):
        max_indent_qty  → sentinel -2 (open outstanding), -1 (no minmax), or >=0 (limit)
        min_indent_qty  → sentinel -2/-1, or minqty (reorder point)
        max_po_qty      → sentinel -2 (open PO outstanding), -1 (no minmax), or >=0 (limit)
        min_po_qty      → sentinel -2/-1, or minqty (reorder point)
    """
    sql = """
    SELECT
        COALESCE(v.cur_stock, 0)               AS branch_stock,
        v.minqty,
        v.maxqty,
        v.min_order_qty,
        COALESCE(v.bal_qty_ind_to_validate, 0) AS outstanding_indent_qty,
        COALESCE(v.bal_qty_ind_to_validate, 0) AS regular_bom_outstanding,
        COALESCE(v.bal_tot_ind_qty, 0)         AS total_all_indent_outstanding,
        COALESCE(v.open_bal_ind_tot_qty, 0)    AS open_indent_outstanding,
        COALESCE(v.bal_tot_po_qty, 0)          AS outstanding_po_qty,
        COALESCE(v.open_bal_tot_po_qty, 0)     AS open_po_outstanding,
        COALESCE(v.bal_qty_po_to_validate, 0)  AS po_outstanding_to_validate,
        COALESCE(v.max_indent_qty, -1)         AS max_indent_qty,
        COALESCE(v.min_indent_qty, -1)         AS min_indent_qty,
        COALESCE(v.max_po_qty, -1)             AS max_po_qty,
        COALESCE(v.min_po_qty, -1)             AS min_po_qty
    FROM vw_item_balance_qty_by_branch_new v
    WHERE v.branch_id = :branch_id
      AND v.item_id   = :item_id;
    """
    return text(sql)


def get_indent_item_outstanding():
    """
    Get the outstanding indent quantity contributed by a specific indent
    for a given (branch_id, item_id) pair.

    Used during edit to exclude the current indent's own quantity from
    the aggregate outstanding total, preventing a self-referencing
    validation error.

    Returns a single row with `indent_outstanding` (float).
    """
    sql = """
    SELECT COALESCE(SUM(vpion.bal_ind_qty), 0) AS indent_outstanding
    FROM vw_proc_indent_outstanding_new vpion
    WHERE vpion.branch_id = :branch_id
      AND vpion.item_id   = :item_id
      AND vpion.indent_dtl_id IN (
          SELECT pid.indent_dtl_id
          FROM proc_indent_dtl pid
          WHERE pid.indent_id = :indent_id
            AND pid.active = 1
      )
    """
    return text(sql)


def get_item_fy_indent_check_v2():
    """
    V2: Check if an Open-type indent already exists for the item
    within the current financial year at the given branch.

    Uses `vw_proc_indent_outstanding_new` (which only contains
    approved/closed indents, status IN (3, 5)) joined back to
    `proc_indent` for indent_date filtering.

    Additionally checks `proc_indent` / `proc_indent_dtl` directly
    for non-approved statuses (draft=21, open=1, pending=20) that are
    NOT in the view, so we don't miss indents still in the pipeline.

    Returns the matching indent number if found.
    """
    sql = """
    SELECT pi.indent_id, pi.indent_no, pi.status_id, pi.indent_date
    FROM proc_indent_dtl pid
    JOIN proc_indent pi ON pi.indent_id = pid.indent_id
    WHERE pid.item_id   = :item_id
      AND pid.active     = 1
      AND pi.branch_id   = :branch_id
      AND pi.indent_type_id = 'Open'
      AND pi.status_id NOT IN (4, 5, 6)
      AND pi.indent_date >= :fy_start
      AND pi.indent_date <= :fy_end
    LIMIT 1;
    """
    return text(sql)


# =============================================================================
# V2 PO VALIDATION QUERIES (using new aggregate views)
# =============================================================================

def get_outstanding_po_qty_v2():
    """
    V2: Total outstanding PO qty for an item at a branch.
    Read directly from the aggregate view instead of computing
    from proc_po_dtl - inward subquery.

    Note: the aggregate view already accounts for approved/closed POs.
    For all-status outstanding we fall back to the original query.
    """
    sql = """
    SELECT COALESCE(v.bal_tot_po_qty, 0) AS outstanding_po_qty
    FROM vw_item_balance_qty_by_branch_new v
    WHERE v.branch_id = :branch_id
      AND v.item_id   = :item_id;
    """
    return text(sql)


def check_open_po_for_item_v2():
    """
    V2: Check if any active PO with outstanding qty exists for
    item + branch, using `vw_proc_po_outstanding_new`.
    Returns po_id, po_no of first match.
    """
    sql = """
    SELECT v.po_id, v.po_no
    FROM vw_proc_po_outstanding_new v
    WHERE v.item_id    = :item_id
      AND v.branch_id  = :branch_id
      AND v.bal_po_qty > 0
    LIMIT 1;
    """
    return text(sql)


def check_open_po_for_item_v2_exclude():
    """
    V2: Check if any active PO (other than the one being edited) with
    outstanding qty exists for item + branch.
    Returns po_id, po_no of first match.
    """
    sql = """
    SELECT v.po_id, v.po_no
    FROM vw_proc_po_outstanding_new v
    WHERE v.item_id    = :item_id
      AND v.branch_id  = :branch_id
      AND v.bal_po_qty > 0
      AND v.po_id     != :exclude_po_id
    LIMIT 1;
    """
    return text(sql)


def get_po_fy_check_v2():
    """
    V2: Check if an Open PO exists for item + branch within the
    current FY, using `vw_proc_po_outstanding_new` which already
    has po_date and po_type columns.
    """
    sql = """
    SELECT v.po_id, v.po_no
    FROM vw_proc_po_outstanding_new v
    WHERE v.item_id    = :item_id
      AND v.branch_id  = :branch_id
      AND v.po_type    = 'Open'
      AND v.bal_po_qty > 0
      AND v.po_date   >= :fy_start
      AND v.po_date   <= :fy_end
    LIMIT 1;
    """
    return text(sql)


def get_po_fy_check_v2_exclude():
    """
    V2: Check if an Open PO (other than the one being edited) exists
    for item + branch within the current FY.
    """
    sql = """
    SELECT v.po_id, v.po_no
    FROM vw_proc_po_outstanding_new v
    WHERE v.item_id    = :item_id
      AND v.branch_id  = :branch_id
      AND v.po_type    = 'Open'
      AND v.bal_po_qty > 0
      AND v.po_date   >= :fy_start
      AND v.po_date   <= :fy_end
      AND v.po_id     != :exclude_po_id
    LIMIT 1;
    """
    return text(sql)


def get_current_po_item_outstanding():
    """
    Get the current PO's outstanding qty for a specific item at a branch,
    from vw_proc_po_outstanding_new.
    Used during edit to subtract the current PO's qty from view aggregates,
    preventing double-counting in validation.
    """
    sql = """
    SELECT COALESCE(SUM(v.bal_po_qty), 0) AS current_po_outstanding
    FROM vw_proc_po_outstanding_new v
    WHERE v.po_id     = :po_id
      AND v.item_id   = :item_id
      AND v.branch_id = :branch_id;
    """
    return text(sql)


# ─── Indent Template / Indent Name queries ─────────────────────────────────

def get_distinct_indent_titles():
    """Return distinct non-empty indent_title values scoped by co_id and optionally branch_id."""
    sql = """
    SELECT DISTINCT pi.indent_title
    FROM proc_indent pi
    INNER JOIN branch_mst bm ON bm.branch_id = pi.branch_id
    WHERE pi.indent_title IS NOT NULL
      AND pi.indent_title != ''
      AND pi.active = 1
      AND bm.co_id = :co_id
      AND (:branch_id IS NULL OR pi.branch_id = :branch_id)
    ORDER BY pi.indent_title;
    """
    return text(sql)


def get_latest_indent_lines_by_title():
    """
    Fetch line items from the most recent indent that matches the given
    indent_title, co_id and branch_id.  Returns the detail rows joined with
    item/group/uom/make/dept metadata (same shape as get_indent_detail_by_id_query).
    """
    sql = """
    SELECT
        pid.indent_dtl_id,
        pid.item_id,
        im.item_code,
        im.item_name,
        im.item_grp_id,
        igm.item_grp_code,
        igm.item_grp_name,
        pid.qty,
        pid.uom_id,
        um.uom_name,
        pid.item_make_id,
        imk.item_make_name,
        pid.dept_id,
        dm.dept_desc AS dept_name,
        pid.remarks
    FROM proc_indent_dtl pid
    INNER JOIN proc_indent pi ON pi.indent_id = pid.indent_id
    INNER JOIN branch_mst bm ON bm.branch_id = pi.branch_id
    LEFT JOIN item_mst im ON im.item_id = pid.item_id
    LEFT JOIN item_grp_mst igm ON igm.item_grp_id = im.item_grp_id
    LEFT JOIN uom_mst um ON um.uom_id = pid.uom_id
    LEFT JOIN item_make imk ON imk.item_make_id = pid.item_make_id
    LEFT JOIN dept_mst dm ON dm.dept_id = pid.dept_id
    WHERE pi.indent_title = :indent_title
      AND bm.co_id = :co_id
      AND pi.branch_id = :branch_id
      AND pi.active = 1
      AND pid.active = 1
    ORDER BY pi.indent_id DESC, pid.indent_dtl_id ASC;
    """
    return text(sql)
