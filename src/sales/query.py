"""
SQL query functions for the sales module.
Covers: sales quotation, sales order, and sales delivery order.
"""

from sqlalchemy.sql import text


# =============================================================================
# SHARED / SETUP QUERIES
# =============================================================================

def get_customers_for_sales(co_id: int = None):
    """Get customers (party_type_id contains 2) with full details."""
    sql = """SELECT
        pm.party_id,
        pm.supp_name AS party_name,
        pm.supp_code AS party_code,
        pm.supp_contact_person AS contact_person,
        pm.supp_contact_designation AS contact_designation,
        pm.supp_email_id AS email,
        pm.phone_no,
        pm.party_pan_no AS pan_no,
        pm.country_id,
        cm.country,
        pm.msme_certified,
        pm.entity_type_id,
        etm.entity_type_name
    FROM party_mst pm
    LEFT JOIN country_mst cm ON cm.country_id = pm.country_id
    LEFT JOIN entity_type_mst etm ON etm.entity_type_id = pm.entity_type_id
    WHERE FIND_IN_SET("2", REPLACE(REPLACE(pm.party_type_id, "{", ""), "}", "")) > 0
        AND (:co_id IS NULL OR pm.co_id = :co_id)
        AND pm.active = 1
    ORDER BY pm.supp_name;"""
    return text(sql)


def get_customer_branches_bulk(co_id: int = None):
    """Get all customer branch addresses in bulk (avoids N+1 query problem)."""
    sql = """SELECT
        pbm.party_mst_branch_id,
        pbm.party_id,
        COALESCE(pbm.address, '') AS address,
        COALESCE(pbm.address_additional, '') AS address_additional,
        COALESCE(pbm.zip_code, '') AS zip_code,
        pbm.state_id,
        sm.state AS state_name,
        sm.state_code,
        pbm.gst_no
    FROM party_branch_mst pbm
    LEFT JOIN party_mst pm ON pm.party_id = pbm.party_id
    LEFT JOIN state_mst sm ON sm.state_id = pbm.state_id
    WHERE pbm.active = 1
        AND FIND_IN_SET("2", REPLACE(REPLACE(pm.party_type_id, "{", ""), "}", "")) > 0
        AND (:co_id IS NULL OR pm.co_id = :co_id)
    ORDER BY pbm.party_id, pbm.party_mst_branch_id;"""
    return text(sql)


def get_brokers_for_sales(co_id: int = None):
    """Get brokers (party_type_id contains 4) for sales."""
    sql = """SELECT
        pm.party_id AS broker_id,
        pm.supp_name AS broker_name,
        pm.supp_code AS broker_code
    FROM party_mst pm
    WHERE FIND_IN_SET("4", REPLACE(REPLACE(pm.party_type_id, "{", ""), "}", "")) > 0
        AND (:co_id IS NULL OR pm.co_id = :co_id)
        AND pm.active = 1
    ORDER BY pm.supp_name;"""
    return text(sql)


def get_transporters_for_sales(co_id: int = None):
    """Get transporters (party_type_id contains 5) for sales."""
    sql = """SELECT
        pm.party_id AS transporter_id,
        pm.supp_name AS transporter_name,
        pm.supp_code AS transporter_code
    FROM party_mst pm
    WHERE FIND_IN_SET("5", REPLACE(REPLACE(pm.party_type_id, "{", ""), "}", "")) > 0
        AND (:co_id IS NULL OR pm.co_id = :co_id)
        AND pm.active = 1
    ORDER BY pm.supp_name;"""
    return text(sql)


# =============================================================================
# SALES ITEM / GROUP QUERIES (for setup_2)
# =============================================================================

def get_item_by_group_id_saleable(item_group_id: int):
    """Get saleable items for a given item group, including tax_percentage and hsn_code."""
    sql = """SELECT im.item_id,
        im.item_code, vip.full_item_code, im.item_name,
        im.uom_id, um.uom_name,
        im.tax_percentage, im.hsn_code,
        im.uom_rounding, im.rate_rounding
    FROM item_mst im
    LEFT JOIN uom_mst um ON um.uom_id = im.uom_id
    LEFT JOIN vw_item_with_group_path vip ON vip.item_id = im.item_id
    WHERE im.item_grp_id = :item_group_id
        AND im.active = 1
        AND im.saleable = 1;"""
    return text(sql)


def get_item_uom_by_group_id_saleable(item_group_id: int):
    """Get UOM mappings for saleable items in a given item group."""
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
     AND im.saleable = 1
     AND im.active = 1
    LEFT JOIN uom_mst AS um_to
      ON um_to.uom_id = uimm.map_to_id
    LEFT JOIN uom_mst AS um_from
      ON um_from.uom_id = uimm.map_from_id;"""
    return text(sql)


def get_hessian_mt_conversion():
    """Return the Bales ↔ MT UOM mapping for a single item.

    Used by the Sales Invoice hessian pipeline to recompute qty_mt from
    qty_bales and to honour uom_item_map_mst.rounding. Caller filters by
    :item_id. Returns relation_value (treated as bales-per-MT regardless
    of direction) and rounding.
    """
    sql = """
    SELECT uimm.relation_value, uimm.rounding,
           uimm.map_from_id, uimm.map_to_id,
           uf.uom_name AS from_name,
           ut.uom_name AS to_name
    FROM uom_item_map_mst uimm
    JOIN uom_mst uf ON uf.uom_id = uimm.map_from_id
    JOIN uom_mst ut ON ut.uom_id = uimm.map_to_id
    WHERE uimm.item_id = :item_id
      AND ((uf.uom_name REGEXP 'Bale' AND ut.uom_name REGEXP '^(MT|Metric[[:space:]]*Tonne|Tonne)$')
        OR (uf.uom_name REGEXP '^(MT|Metric[[:space:]]*Tonne|Tonne)$' AND ut.uom_name REGEXP 'Bale'))
    LIMIT 1;
    """
    return text(sql)


# =============================================================================
# SALES QUOTATION QUERIES
# =============================================================================

def insert_sales_quotation():
    sql = """INSERT INTO sales_quotation (
        updated_by, updated_date_time,
        quotation_date, quotation_no, branch_id, party_id,
        sales_broker_id, billing_address_id, shipping_address_id,
        quotation_expiry_date, footer_notes, brokerage_percentage,
        gross_amount, net_amount, round_off_value,
        payment_terms, delivery_terms, delivery_days,
        terms_condition, internal_note, sales_enquiry_id,
        status_id, approval_level, active
    ) VALUES (
        :updated_by, :updated_date_time,
        :quotation_date, :quotation_no, :branch_id, :party_id,
        :sales_broker_id, :billing_address_id, :shipping_address_id,
        :quotation_expiry_date, :footer_notes, :brokerage_percentage,
        :gross_amount, :net_amount, :round_off_value,
        :payment_terms, :delivery_terms, :delivery_days,
        :terms_condition, :internal_note, :sales_enquiry_id,
        :status_id, :approval_level, :active
    );"""
    return text(sql)


def insert_sales_quotation_dtl():
    sql = """INSERT INTO sales_quotation_dtl (
        updated_by, updated_date_time,
        sales_quotation_id, hsn_code, item_id, item_make_id,
        quantity, uom_id, rate,
        discount_type, discounted_rate, discount_amount,
        net_amount, total_amount, remarks,
        enquiry_dtl_id, cost_snapshot_id, base_cost, overhead_pct, margin_pct,
        active
    ) VALUES (
        :updated_by, :updated_date_time,
        :sales_quotation_id, :hsn_code, :item_id, :item_make_id,
        :quantity, :uom_id, :rate,
        :discount_type, :discounted_rate, :discount_amount,
        :net_amount, :total_amount, :remarks,
        :enquiry_dtl_id, :cost_snapshot_id, :base_cost, :overhead_pct, :margin_pct,
        :active
    );"""
    return text(sql)


def insert_sales_quotation_dtl_gst():
    sql = """INSERT INTO sales_quotation_dtl_gst (
        quotation_lineitem_id,
        igst_amount, igst_percent,
        cgst_amount, cgst_percent,
        sgst_amount, sgst_percent,
        gst_total
    ) VALUES (
        :quotation_lineitem_id,
        :igst_amount, :igst_percent,
        :cgst_amount, :cgst_percent,
        :sgst_amount, :sgst_percent,
        :gst_total
    );"""
    return text(sql)


def update_sales_quotation():
    sql = """UPDATE sales_quotation SET
        updated_by = :updated_by,
        updated_date_time = :updated_date_time,
        quotation_date = :quotation_date,
        branch_id = :branch_id,
        party_id = :party_id,
        sales_broker_id = :sales_broker_id,
        billing_address_id = :billing_address_id,
        shipping_address_id = :shipping_address_id,
        quotation_expiry_date = :quotation_expiry_date,
        footer_notes = :footer_notes,
        brokerage_percentage = :brokerage_percentage,
        gross_amount = :gross_amount,
        net_amount = :net_amount,
        round_off_value = :round_off_value,
        payment_terms = :payment_terms,
        delivery_terms = :delivery_terms,
        delivery_days = :delivery_days,
        terms_condition = :terms_condition,
        internal_note = :internal_note,
        sales_enquiry_id = :sales_enquiry_id,
        quotation_no = COALESCE(:quotation_no, quotation_no),
        active = COALESCE(:active, active),
        status_id = COALESCE(:status_id, status_id)
    WHERE sales_quotation_id = :sales_quotation_id;"""
    return text(sql)


def delete_sales_quotation_dtl():
    """Soft delete all detail rows for a quotation."""
    sql = """UPDATE sales_quotation_dtl SET
        active = 0,
        updated_by = :updated_by,
        updated_date_time = :updated_date_time
    WHERE sales_quotation_id = :sales_quotation_id;"""
    return text(sql)


def delete_sales_quotation_dtl_gst():
    """Hard delete GST rows for a quotation's details (they are re-inserted on update)."""
    sql = """DELETE FROM sales_quotation_dtl_gst
    WHERE quotation_lineitem_id IN (
        SELECT quotation_lineitem_id FROM sales_quotation_dtl
        WHERE sales_quotation_id = :sales_quotation_id
    );"""
    return text(sql)


def get_quotation_table_query():
    sql = """SELECT
        sq.sales_quotation_id,
        sq.quotation_no,
        sq.quotation_date,
        sq.quotation_expiry_date,
        sq.branch_id,
        bm.branch_name,
        bm.branch_prefix,
        bm.co_id,
        cm.co_prefix,
        sq.party_id,
        pm.supp_name AS party_name,
        sq.gross_amount,
        sq.net_amount,
        sq.status_id,
        sm.status_name
    FROM sales_quotation AS sq
    LEFT JOIN branch_mst AS bm ON bm.branch_id = sq.branch_id
    LEFT JOIN co_mst AS cm ON cm.co_id = bm.co_id
    LEFT JOIN party_mst AS pm ON pm.party_id = sq.party_id
    LEFT JOIN status_mst AS sm ON sm.status_id = sq.status_id
    WHERE sq.active = 1
        AND (:co_id IS NULL OR bm.co_id = :co_id)
        AND (:branch_id IS NULL OR sq.branch_id = :branch_id)
        AND (:status_id IS NULL OR sq.status_id = :status_id)
        AND (
            :search_like IS NULL
            OR sq.quotation_no LIKE :search_like
            OR pm.supp_name LIKE :search_like
            OR bm.branch_name LIKE :search_like
        )
    ORDER BY sq.quotation_date DESC, sq.sales_quotation_id DESC
    LIMIT :limit OFFSET :offset;"""
    return text(sql)


def get_quotation_table_count_query():
    sql = """SELECT COUNT(1) AS total
    FROM sales_quotation AS sq
    LEFT JOIN branch_mst AS bm ON bm.branch_id = sq.branch_id
    LEFT JOIN party_mst AS pm ON pm.party_id = sq.party_id
    WHERE sq.active = 1
        AND (:co_id IS NULL OR bm.co_id = :co_id)
        AND (:branch_id IS NULL OR sq.branch_id = :branch_id)
        AND (:status_id IS NULL OR sq.status_id = :status_id)
        AND (
            :search_like IS NULL
            OR sq.quotation_no LIKE :search_like
            OR pm.supp_name LIKE :search_like
            OR bm.branch_name LIKE :search_like
        );"""
    return text(sql)


def get_quotation_by_id_query():
    sql = """SELECT
        sq.sales_quotation_id,
        sq.quotation_no,
        sq.quotation_date,
        sq.quotation_expiry_date,
        sq.branch_id,
        bm.branch_name,
        bm.branch_prefix,
        bm.co_id,
        cm.co_prefix,
        cm.co_name,
        cm.co_logo,
        bm.state_id AS branch_state_id,
        bsm.state AS branch_state_name,
        sq.party_id,
        pm.supp_name AS party_name,
        sq.sales_broker_id,
        brkr.supp_name AS broker_name,
        sq.billing_address_id,
        sq.shipping_address_id,
        pbill.address AS billing_address_text,
        pbill.party_mst_branch_id AS billing_party_branch_id,
        pbill.state_id AS billing_state_id,
        sbill.state AS billing_state_name,
        pship.address AS shipping_address_text,
        pship.party_mst_branch_id AS shipping_party_branch_id,
        pship.state_id AS shipping_state_id,
        sship.state AS shipping_state_name,
        sq.footer_notes,
        sq.brokerage_percentage,
        sq.gross_amount,
        sq.net_amount,
        sq.round_off_value,
        sq.payment_terms,
        sq.delivery_terms,
        sq.delivery_days,
        sq.terms_condition,
        sq.internal_note,
        sq.sales_enquiry_id,
        se.enquiry_no,
        sq.status_id,
        sm.status_name,
        sq.updated_by,
        sq.updated_date_time,
        CASE
            WHEN sq.status_id = 20 THEN sq.approval_level
            ELSE NULL
        END AS approval_level
    FROM sales_quotation AS sq
    LEFT JOIN sales_enquiry AS se ON se.sales_enquiry_id = sq.sales_enquiry_id
    LEFT JOIN branch_mst AS bm ON bm.branch_id = sq.branch_id
    LEFT JOIN state_mst AS bsm ON bsm.state_id = bm.state_id
    LEFT JOIN co_mst AS cm ON cm.co_id = bm.co_id
    LEFT JOIN party_mst AS pm ON pm.party_id = sq.party_id
    LEFT JOIN party_mst AS brkr ON brkr.party_id = sq.sales_broker_id
    LEFT JOIN status_mst AS sm ON sm.status_id = sq.status_id
    LEFT JOIN party_branch_mst AS pbill ON pbill.party_mst_branch_id = sq.billing_address_id
    LEFT JOIN state_mst AS sbill ON sbill.state_id = pbill.state_id
    LEFT JOIN party_branch_mst AS pship ON pship.party_mst_branch_id = sq.shipping_address_id
    LEFT JOIN state_mst AS sship ON sship.state_id = pship.state_id
    WHERE sq.sales_quotation_id = :sales_quotation_id
        AND (:co_id IS NULL OR bm.co_id = :co_id);"""
    return text(sql)


def get_quotation_dtl_by_id_query():
    sql = """SELECT
        sqd.quotation_lineitem_id,
        sqd.sales_quotation_id,
        sqd.hsn_code,
        sqd.item_id,
        im.item_code,
        im.item_name,
        im.item_grp_id,
        igm.item_grp_code,
        igm.item_grp_name,
        sqd.item_make_id,
        imk.item_make_name,
        sqd.quantity,
        sqd.uom_id,
        um.uom_name,
        sqd.rate,
        sqd.discount_type,
        sqd.discounted_rate,
        sqd.discount_amount,
        sqd.net_amount,
        sqd.total_amount,
        sqd.remarks,
        sqd.enquiry_dtl_id,
        sqd.cost_snapshot_id,
        sqd.base_cost,
        sqd.overhead_pct,
        sqd.margin_pct
    FROM sales_quotation_dtl AS sqd
    LEFT JOIN item_mst AS im ON im.item_id = sqd.item_id
    LEFT JOIN item_grp_mst AS igm ON igm.item_grp_id = im.item_grp_id
    LEFT JOIN item_make AS imk ON imk.item_make_id = sqd.item_make_id
    LEFT JOIN uom_mst AS um ON um.uom_id = sqd.uom_id
    WHERE sqd.sales_quotation_id = :sales_quotation_id
        AND sqd.active = 1
    ORDER BY sqd.quotation_lineitem_id;"""
    return text(sql)


def get_quotation_gst_by_dtl_id_query():
    sql = """SELECT
        sqg.sales_quotation_dtl_gst_id,
        sqg.quotation_lineitem_id,
        sqg.igst_amount, sqg.igst_percent,
        sqg.cgst_amount, sqg.cgst_percent,
        sqg.sgst_amount, sqg.sgst_percent,
        sqg.gst_total
    FROM sales_quotation_dtl_gst AS sqg
    WHERE sqg.quotation_lineitem_id IN (
        SELECT quotation_lineitem_id FROM sales_quotation_dtl
        WHERE sales_quotation_id = :sales_quotation_id AND active = 1
    )
    ORDER BY sqg.quotation_lineitem_id;"""
    return text(sql)


def update_quotation_status():
    """Update quotation status and approval level. Optionally update quotation_no."""
    sql = """UPDATE sales_quotation SET
        status_id = :status_id,
        approval_level = :approval_level,
        updated_by = :updated_by,
        updated_date_time = :updated_date_time,
        quotation_no = CASE
            WHEN :quotation_no IS NOT NULL THEN :quotation_no
            ELSE quotation_no
        END
    WHERE sales_quotation_id = :sales_quotation_id;"""
    return text(sql)


def get_quotation_with_approval_info():
    sql = """SELECT
        sq.sales_quotation_id,
        sq.status_id,
        sq.approval_level,
        sq.branch_id,
        sq.quotation_date,
        sq.quotation_no,
        sq.net_amount,
        bm.co_id
    FROM sales_quotation sq
    LEFT JOIN branch_mst bm ON bm.branch_id = sq.branch_id
    WHERE sq.sales_quotation_id = :sales_quotation_id;"""
    return text(sql)


def get_max_quotation_no_for_branch_fy():
    sql = """SELECT COALESCE(MAX(CAST(sq.quotation_no AS UNSIGNED)), 0) AS max_doc_no
    FROM sales_quotation sq
    WHERE sq.branch_id = :branch_id
        AND sq.quotation_date >= :fy_start_date
        AND sq.quotation_date <= :fy_end_date
        AND sq.quotation_no IS NOT NULL;"""
    return text(sql)


def get_approved_quotations_query():
    """Get all approved quotations (status_id = 3) for dropdown when creating sales order."""
    sql = """SELECT
        sq.sales_quotation_id,
        sq.quotation_no,
        sq.quotation_date,
        sq.party_id,
        pm.supp_name AS party_name,
        sq.branch_id,
        bm.branch_name,
        bm.branch_prefix,
        bm.co_id,
        cm.co_prefix,
        sq.net_amount
    FROM sales_quotation AS sq
    LEFT JOIN branch_mst AS bm ON bm.branch_id = sq.branch_id
    LEFT JOIN co_mst AS cm ON cm.co_id = bm.co_id
    LEFT JOIN party_mst AS pm ON pm.party_id = sq.party_id
    WHERE sq.status_id = 3
        AND sq.active = 1
        AND (:branch_id IS NULL OR sq.branch_id = :branch_id)
        AND (:co_id IS NULL OR bm.co_id = :co_id)
    ORDER BY sq.quotation_date DESC, sq.sales_quotation_id DESC;"""
    return text(sql)


def get_quotation_lines_for_order():
    """Get quotation line items to pre-fill sales order lines."""
    sql = """SELECT
        sqd.quotation_lineitem_id,
        sqd.hsn_code,
        sqd.item_id,
        im.item_code,
        im.item_name,
        im.item_grp_id,
        sqd.item_make_id,
        imk.item_make_name,
        sqd.quantity,
        sqd.uom_id,
        um.uom_name,
        sqd.rate,
        sqd.discount_type,
        sqd.discounted_rate,
        sqd.discount_amount,
        sqd.net_amount,
        sqd.total_amount,
        sqd.remarks
    FROM sales_quotation_dtl AS sqd
    LEFT JOIN item_mst AS im ON im.item_id = sqd.item_id
    LEFT JOIN item_make AS imk ON imk.item_make_id = sqd.item_make_id
    LEFT JOIN uom_mst AS um ON um.uom_id = sqd.uom_id
    WHERE sqd.sales_quotation_id = :sales_quotation_id
        AND sqd.active = 1
    ORDER BY sqd.quotation_lineitem_id;"""
    return text(sql)


# =============================================================================
# ENQUIRY SOURCE QUERIES (shared by quotation + direct sales order)
# =============================================================================

def get_enquiries_for_sales_doc_query():
    """Approved enquiries eligible as source for a quotation or a direct sales order.

    Eligible = approved (status 3), active, and currently in a quotable stage
    (COSTING_REVIEW / PRICE_CHECK / QUOTATION). Company scope derived via branch.
    """
    sql = """SELECT
        se.sales_enquiry_id,
        se.enquiry_no,
        se.enquiry_date,
        se.customer_ref_no,
        se.expected_delivery_date,
        se.party_id,
        pm.supp_name AS party_name,
        se.branch_id,
        fsm.stage_code,
        fsm.stage_name
    FROM sales_enquiry AS se
    LEFT JOIN party_mst AS pm ON pm.party_id = se.party_id
    LEFT JOIN flow_stage_mst AS fsm ON fsm.stage_id = se.current_stage_id
    LEFT JOIN branch_mst AS bm ON bm.branch_id = se.branch_id
    WHERE se.active = 1
        AND se.status_id = 3
        AND fsm.stage_code IN ('COSTING_REVIEW', 'PRICE_CHECK', 'QUOTATION')
        AND (:branch_id IS NULL OR se.branch_id = :branch_id)
        AND (:co_id IS NULL OR bm.co_id = :co_id)
    ORDER BY se.enquiry_date DESC, se.sales_enquiry_id DESC;"""
    return text(sql)


def get_enquiry_lines_for_sales_doc_query():
    """Enquiry lines with confirmed cost basis, to pre-fill quotation / SO lines."""
    sql = """SELECT
        sed.enquiry_dtl_id,
        sed.sales_enquiry_id,
        sed.item_id,
        im.item_code,
        im.item_name,
        im.item_grp_id,
        im.hsn_code,
        sed.item_desc_freetext,
        sed.is_new_item,
        sed.design_change,
        sed.qty,
        sed.uom_id,
        um.uom_name,
        sed.target_price,
        sed.bom_hdr_id,
        sed.cost_snapshot_id,
        sed.confirmed_cost_per_unit,
        sed.overhead_pct,
        sed.margin_pct,
        sed.remarks
    FROM sales_enquiry_dtl AS sed
    LEFT JOIN item_mst AS im ON im.item_id = sed.item_id
    LEFT JOIN uom_mst AS um ON um.uom_id = sed.uom_id
    WHERE sed.sales_enquiry_id = :sales_enquiry_id
        AND sed.active = 1
    ORDER BY sed.enquiry_dtl_id;"""
    return text(sql)


# =============================================================================
# SALES ORDER QUERIES
# =============================================================================

def insert_sales_order():
    sql = """INSERT INTO sales_order (
        updated_by, updated_date_time,
        sales_order_date, sales_no, invoice_type,
        branch_id, quotation_id, party_id,
        broker_id, billing_to_id, shipping_to_id, transporter_id,
        sales_order_expiry_date, broker_commission_percent,
        footer_note, terms_conditions, internal_note,
        delivery_terms, payment_terms, delivery_days,
        freight_charges, gross_amount, net_amount,
        committed_delivery_date, advance_amount, advance_note, sales_enquiry_id,
        status_id, approval_level, active,
        buyer_order_no, buyer_order_date
    ) VALUES (
        :updated_by, :updated_date_time,
        :sales_order_date, :sales_no, :invoice_type,
        :branch_id, :quotation_id, :party_id,
        :broker_id, :billing_to_id, :shipping_to_id, :transporter_id,
        :sales_order_expiry_date, :broker_commission_percent,
        :footer_note, :terms_conditions, :internal_note,
        :delivery_terms, :payment_terms, :delivery_days,
        :freight_charges, :gross_amount, :net_amount,
        :committed_delivery_date, :advance_amount, :advance_note, :sales_enquiry_id,
        :status_id, :approval_level, :active,
        :buyer_order_no, :buyer_order_date
    );"""
    return text(sql)


def insert_sales_order_dtl():
    sql = """INSERT INTO sales_order_dtl (
        updated_by, updated_date_time,
        sales_order_id, quotation_lineitem_id,
        hsn_code, item_id, item_make_id,
        quantity, uom_id, rate,
        discount_type, discounted_rate, discount_amount,
        net_amount, total_amount, remarks, active
    ) VALUES (
        :updated_by, :updated_date_time,
        :sales_order_id, :quotation_lineitem_id,
        :hsn_code, :item_id, :item_make_id,
        :quantity, :uom_id, :rate,
        :discount_type, :discounted_rate, :discount_amount,
        :net_amount, :total_amount, :remarks, :active
    );"""
    return text(sql)


def insert_sales_order_dtl_gst():
    sql = """INSERT INTO sales_order_dtl_gst (
        sales_order_dtl_id,
        igst_amount, igst_percent,
        cgst_amount, cgst_percent,
        sgst_amount, sgst_percent,
        gst_total
    ) VALUES (
        :sales_order_dtl_id,
        :igst_amount, :igst_percent,
        :cgst_amount, :cgst_percent,
        :sgst_amount, :sgst_percent,
        :gst_total
    );"""
    return text(sql)


def update_sales_order():
    sql = """UPDATE sales_order SET
        updated_by = :updated_by,
        updated_date_time = :updated_date_time,
        sales_order_date = :sales_order_date,
        invoice_type = :invoice_type,
        branch_id = :branch_id,
        quotation_id = :quotation_id,
        party_id = :party_id,
        broker_id = :broker_id,
        billing_to_id = :billing_to_id,
        shipping_to_id = :shipping_to_id,
        transporter_id = :transporter_id,
        sales_order_expiry_date = :sales_order_expiry_date,
        broker_commission_percent = :broker_commission_percent,
        footer_note = :footer_note,
        terms_conditions = :terms_conditions,
        internal_note = :internal_note,
        delivery_terms = :delivery_terms,
        payment_terms = :payment_terms,
        delivery_days = :delivery_days,
        buyer_order_no = :buyer_order_no,
        buyer_order_date = :buyer_order_date,
        freight_charges = :freight_charges,
        gross_amount = :gross_amount,
        net_amount = :net_amount,
        committed_delivery_date = :committed_delivery_date,
        advance_amount = :advance_amount,
        advance_note = :advance_note,
        sales_enquiry_id = :sales_enquiry_id,
        sales_no = COALESCE(:sales_no, sales_no),
        active = COALESCE(:active, active),
        status_id = COALESCE(:status_id, status_id)
    WHERE sales_order_id = :sales_order_id;"""
    return text(sql)


def delete_sales_order_dtl():
    sql = """UPDATE sales_order_dtl SET
        active = 0,
        updated_by = :updated_by,
        updated_date_time = :updated_date_time
    WHERE sales_order_id = :sales_order_id;"""
    return text(sql)


def delete_sales_order_dtl_gst():
    sql = """DELETE FROM sales_order_dtl_gst
    WHERE sales_order_dtl_id IN (
        SELECT sales_order_dtl_id FROM sales_order_dtl
        WHERE sales_order_id = :sales_order_id
    );"""
    return text(sql)


def insert_sales_order_dtl_hessian():
    sql = """INSERT INTO sales_order_dtl_hessian (
        sales_order_dtl_id,
        qty_bales, rate_per_bale,
        billing_rate_mt, billing_rate_bale,
        updated_by, updated_date_time
    ) VALUES (
        :sales_order_dtl_id,
        :qty_bales, :rate_per_bale,
        :billing_rate_mt, :billing_rate_bale,
        :updated_by, :updated_date_time
    );"""
    return text(sql)


def delete_sales_order_dtl_hessian():
    sql = """DELETE FROM sales_order_dtl_hessian
    WHERE sales_order_dtl_id IN (
        SELECT sales_order_dtl_id FROM sales_order_dtl
        WHERE sales_order_id = :sales_order_id
    );"""
    return text(sql)


def get_sales_order_hessian_by_id_query():
    sql = """SELECT
        soh.sales_order_dtl_hessian_id,
        soh.sales_order_dtl_id,
        soh.qty_bales,
        soh.rate_per_bale,
        soh.billing_rate_mt,
        soh.billing_rate_bale
    FROM sales_order_dtl_hessian AS soh
    WHERE soh.sales_order_dtl_id IN (
        SELECT sales_order_dtl_id FROM sales_order_dtl
        WHERE sales_order_id = :sales_order_id AND active = 1
    )
    ORDER BY soh.sales_order_dtl_id;"""
    return text(sql)


def get_sales_order_table_query():
    sql = """SELECT
        so.sales_order_id,
        so.sales_no,
        so.sales_order_date,
        so.sales_order_expiry_date,
        so.branch_id,
        bm.branch_name,
        bm.branch_prefix,
        bm.co_id,
        cm.co_prefix,
        so.party_id,
        pm.supp_name AS party_name,
        so.quotation_id,
        sq.quotation_no,
        so.gross_amount,
        so.net_amount,
        so.status_id,
        sm.status_name
    FROM sales_order AS so
    LEFT JOIN branch_mst AS bm ON bm.branch_id = so.branch_id
    LEFT JOIN co_mst AS cm ON cm.co_id = bm.co_id
    LEFT JOIN party_mst AS pm ON pm.party_id = so.party_id
    LEFT JOIN sales_quotation AS sq ON sq.sales_quotation_id = so.quotation_id
    LEFT JOIN status_mst AS sm ON sm.status_id = so.status_id
    WHERE so.active = 1
        AND (:co_id IS NULL OR bm.co_id = :co_id)
        AND (:branch_id IS NULL OR so.branch_id = :branch_id)
        AND (:status_id IS NULL OR so.status_id = :status_id)
        AND (
            :search_like IS NULL
            OR so.sales_no LIKE :search_like
            OR pm.supp_name LIKE :search_like
            OR bm.branch_name LIKE :search_like
            OR sq.quotation_no LIKE :search_like
        )
    ORDER BY so.sales_order_date DESC, so.sales_order_id DESC
    LIMIT :limit OFFSET :offset;"""
    return text(sql)


def get_sales_order_table_count_query():
    sql = """SELECT COUNT(1) AS total
    FROM sales_order AS so
    LEFT JOIN branch_mst AS bm ON bm.branch_id = so.branch_id
    LEFT JOIN party_mst AS pm ON pm.party_id = so.party_id
    LEFT JOIN sales_quotation AS sq ON sq.sales_quotation_id = so.quotation_id
    WHERE so.active = 1
        AND (:co_id IS NULL OR bm.co_id = :co_id)
        AND (:branch_id IS NULL OR so.branch_id = :branch_id)
        AND (:status_id IS NULL OR so.status_id = :status_id)
        AND (
            :search_like IS NULL
            OR so.sales_no LIKE :search_like
            OR pm.supp_name LIKE :search_like
            OR bm.branch_name LIKE :search_like
            OR sq.quotation_no LIKE :search_like
        );"""
    return text(sql)


def get_sales_order_by_id_query():
    sql = """SELECT
        so.sales_order_id,
        so.sales_no,
        so.sales_order_date,
        so.sales_order_expiry_date,
        so.invoice_type,
        so.branch_id,
        bm.branch_name,
        bm.branch_prefix,
        bm.co_id,
        cm.co_prefix,
        cm.co_name,
        cm.co_logo,
        so.quotation_id,
        sq.quotation_no,
        so.party_id,
        pm.supp_name AS party_name,
        so.broker_id,
        brkr.supp_name AS broker_name,
        so.billing_to_id,
        so.shipping_to_id,
        so.transporter_id,
        trns.supp_name AS transporter_name,
        so.broker_commission_percent,
        so.footer_note,
        so.terms_conditions,
        so.internal_note,
        so.delivery_terms,
        so.payment_terms,
        so.delivery_days,
        so.freight_charges,
        so.buyer_order_no,
        so.buyer_order_date,
        so.gross_amount,
        so.net_amount,
        so.committed_delivery_date,
        so.advance_amount,
        so.advance_note,
        so.sales_enquiry_id,
        se.enquiry_no,
        so.status_id,
        sm.status_name,
        so.updated_by,
        so.updated_date_time,
        CASE
            WHEN so.status_id = 20 THEN so.approval_level
            ELSE NULL
        END AS approval_level
    FROM sales_order AS so
    LEFT JOIN sales_enquiry AS se ON se.sales_enquiry_id = so.sales_enquiry_id
    LEFT JOIN branch_mst AS bm ON bm.branch_id = so.branch_id
    LEFT JOIN co_mst AS cm ON cm.co_id = bm.co_id
    LEFT JOIN sales_quotation AS sq ON sq.sales_quotation_id = so.quotation_id
    LEFT JOIN party_mst AS pm ON pm.party_id = so.party_id
    LEFT JOIN party_mst AS brkr ON brkr.party_id = so.broker_id
    LEFT JOIN party_mst AS trns ON trns.party_id = so.transporter_id
    LEFT JOIN status_mst AS sm ON sm.status_id = so.status_id
    WHERE so.sales_order_id = :sales_order_id
        AND (:co_id IS NULL OR bm.co_id = :co_id);"""
    return text(sql)


def get_sales_order_dtl_by_id_query():
    sql = """SELECT
        sod.sales_order_dtl_id,
        sod.sales_order_id,
        sod.quotation_lineitem_id,
        sod.hsn_code,
        sod.item_id,
        im.item_code,
        vip.full_item_code,
        im.item_name,
        im.item_grp_id,
        igm.item_grp_code,
        igm.item_grp_name,
        sod.item_make_id,
        imk.item_make_name,
        sod.quantity,
        sod.uom_id,
        qum.uom_name AS uom_name,
        sod.rate,
        sod.discount_type,
        sod.discounted_rate,
        sod.discount_amount,
        sod.net_amount,
        sod.total_amount,
        sod.remarks
    FROM sales_order_dtl AS sod
    LEFT JOIN item_mst AS im ON im.item_id = sod.item_id
    LEFT JOIN vw_item_with_group_path AS vip ON vip.item_id = im.item_id
    LEFT JOIN item_grp_mst AS igm ON igm.item_grp_id = im.item_grp_id
    LEFT JOIN item_make AS imk ON imk.item_make_id = sod.item_make_id
    LEFT JOIN uom_mst AS qum ON qum.uom_id = sod.uom_id
    WHERE sod.sales_order_id = :sales_order_id
        AND sod.active = 1
    ORDER BY sod.sales_order_dtl_id;"""
    return text(sql)


def get_sales_order_gst_by_id_query():
    sql = """SELECT
        sog.sales_order_dtl_gst_id,
        sog.sales_order_dtl_id,
        sog.igst_amount, sog.igst_percent,
        sog.cgst_amount, sog.cgst_percent,
        sog.sgst_amount, sog.sgst_percent,
        sog.gst_total
    FROM sales_order_dtl_gst AS sog
    WHERE sog.sales_order_dtl_id IN (
        SELECT sales_order_dtl_id FROM sales_order_dtl
        WHERE sales_order_id = :sales_order_id AND active = 1
    )
    ORDER BY sog.sales_order_dtl_id;"""
    return text(sql)


def update_sales_order_status():
    sql = """UPDATE sales_order SET
        status_id = :status_id,
        approval_level = :approval_level,
        updated_by = :updated_by,
        updated_date_time = :updated_date_time,
        sales_no = CASE
            WHEN :sales_no IS NOT NULL THEN :sales_no
            ELSE sales_no
        END
    WHERE sales_order_id = :sales_order_id;"""
    return text(sql)


def get_sales_order_with_approval_info():
    sql = """SELECT
        so.sales_order_id,
        so.status_id,
        so.approval_level,
        so.branch_id,
        so.sales_order_date,
        so.sales_no,
        so.net_amount,
        bm.co_id
    FROM sales_order so
    LEFT JOIN branch_mst bm ON bm.branch_id = so.branch_id
    WHERE so.sales_order_id = :sales_order_id;"""
    return text(sql)


def get_max_sales_order_no_for_branch_fy():
    sql = """SELECT COALESCE(MAX(CAST(so.sales_no AS UNSIGNED)), 0) AS max_doc_no
    FROM sales_order so
    WHERE so.branch_id = :branch_id
        AND so.sales_order_date >= :fy_start_date
        AND so.sales_order_date <= :fy_end_date
        AND so.sales_no IS NOT NULL;"""
    return text(sql)


def get_approved_sales_orders_query():
    """Get all approved sales orders (status_id = 3) for dropdown when creating delivery order."""
    sql = """SELECT
        so.sales_order_id,
        so.sales_no,
        so.sales_order_date,
        so.party_id,
        pm.supp_name AS party_name,
        so.branch_id,
        bm.branch_name,
        bm.branch_prefix,
        bm.co_id,
        cm.co_prefix,
        so.net_amount,
        so.invoice_type,
        so.broker_id,
        so.billing_to_id,
        so.shipping_to_id,
        so.transporter_id,
        sog.pcso_no,
        sog.pcso_date
    FROM sales_order AS so
    LEFT JOIN branch_mst AS bm ON bm.branch_id = so.branch_id
    LEFT JOIN co_mst AS cm ON cm.co_id = bm.co_id
    LEFT JOIN party_mst AS pm ON pm.party_id = so.party_id
    LEFT JOIN sales_order_govtskg AS sog ON sog.sales_order_id = so.sales_order_id
    WHERE so.status_id = 3
        AND so.active = 1
        AND (:branch_id IS NULL OR so.branch_id = :branch_id)
        AND (:co_id IS NULL OR bm.co_id = :co_id)
    ORDER BY so.sales_order_date DESC, so.sales_order_id DESC;"""
    return text(sql)


def get_sales_order_lines_for_delivery():
    """Get sales order line items to pre-fill delivery order lines.
    Joins vw_sales_order_outstanding to include balance columns and
    filters out fully-delivered lines (bal_do_qty = 0)."""
    sql = """SELECT
        sod.sales_order_dtl_id,
        sod.quotation_lineitem_id,
        sod.hsn_code,
        sod.item_id,
        im.item_code,
        vip.full_item_code,
        im.item_name,
        im.item_grp_id,
        igm.item_grp_code,
        igm.item_grp_name,
        sod.item_make_id,
        imk.item_make_name,
        sod.quantity,
        sod.uom_id,
        qum.uom_name AS uom_name,
        sod.rate,
        sod.discount_type,
        sod.discounted_rate,
        sod.discount_amount,
        sod.net_amount,
        sod.total_amount,
        sod.remarks,
        sodh.qty_bales,
        sodh.rate_per_bale,
        COALESCE(vso.so_qty, sod.quantity) AS so_qty,
        COALESCE(vso.do_consumed_qty, 0) AS do_consumed_qty,
        COALESCE(vso.bal_do_qty, sod.quantity) AS bal_do_qty
    FROM sales_order_dtl AS sod
    LEFT JOIN item_mst AS im ON im.item_id = sod.item_id
    LEFT JOIN vw_item_with_group_path AS vip ON vip.item_id = im.item_id
    LEFT JOIN item_grp_mst AS igm ON igm.item_grp_id = im.item_grp_id
    LEFT JOIN item_make AS imk ON imk.item_make_id = sod.item_make_id
    LEFT JOIN uom_mst AS qum ON qum.uom_id = sod.uom_id
    LEFT JOIN sales_order_dtl_hessian AS sodh ON sodh.sales_order_dtl_id = sod.sales_order_dtl_id
    LEFT JOIN vw_sales_order_outstanding AS vso ON vso.sales_order_dtl_id = sod.sales_order_dtl_id
    WHERE sod.sales_order_id = :sales_order_id
        AND sod.active = 1
        AND (vso.bal_do_qty > 0 OR vso.bal_do_qty IS NULL)
    ORDER BY sod.sales_order_dtl_id;"""
    return text(sql)


# =============================================================================
# SALES DELIVERY ORDER QUERIES
# =============================================================================

def insert_sales_delivery_order():
    sql = """INSERT INTO sales_delivery_order (
        updated_by, updated_date_time,
        delivery_order_date, delivery_order_no,
        branch_id, invoice_type, sales_order_id, party_id,
        billing_to_id, shipping_to_id, transporter_id,
        vehicle_no, driver_name, driver_contact,
        expected_delivery_date,
        footer_note, internal_note,
        gross_amount, net_amount, freight_charges, round_off_value,
        status_id, approval_level, active
    ) VALUES (
        :updated_by, :updated_date_time,
        :delivery_order_date, :delivery_order_no,
        :branch_id, :invoice_type, :sales_order_id, :party_id,
        :billing_to_id, :shipping_to_id, :transporter_id,
        :vehicle_no, :driver_name, :driver_contact,
        :expected_delivery_date,
        :footer_note, :internal_note,
        :gross_amount, :net_amount, :freight_charges, :round_off_value,
        :status_id, :approval_level, :active
    );"""
    return text(sql)


def insert_sales_delivery_order_dtl():
    sql = """INSERT INTO sales_delivery_order_dtl (
        updated_by, updated_date_time,
        sales_delivery_order_id, sales_order_dtl_id,
        hsn_code, item_id, item_make_id,
        quantity, uom_id, rate,
        discount_type, discounted_rate, discount_amount,
        net_amount, total_amount, remarks, active
    ) VALUES (
        :updated_by, :updated_date_time,
        :sales_delivery_order_id, :sales_order_dtl_id,
        :hsn_code, :item_id, :item_make_id,
        :quantity, :uom_id, :rate,
        :discount_type, :discounted_rate, :discount_amount,
        :net_amount, :total_amount, :remarks, :active
    );"""
    return text(sql)


def insert_sales_delivery_order_dtl_gst():
    sql = """INSERT INTO sales_delivery_order_dtl_gst (
        sales_delivery_order_dtl_id,
        igst_amount, igst_percent,
        cgst_amount, cgst_percent,
        sgst_amount, sgst_percent,
        gst_total
    ) VALUES (
        :sales_delivery_order_dtl_id,
        :igst_amount, :igst_percent,
        :cgst_amount, :cgst_percent,
        :sgst_amount, :sgst_percent,
        :gst_total
    );"""
    return text(sql)


def update_sales_delivery_order():
    sql = """UPDATE sales_delivery_order SET
        updated_by = :updated_by,
        updated_date_time = :updated_date_time,
        delivery_order_date = :delivery_order_date,
        branch_id = :branch_id,
        invoice_type = :invoice_type,
        sales_order_id = :sales_order_id,
        party_id = :party_id,
        billing_to_id = :billing_to_id,
        shipping_to_id = :shipping_to_id,
        transporter_id = :transporter_id,
        vehicle_no = :vehicle_no,
        driver_name = :driver_name,
        driver_contact = :driver_contact,
        expected_delivery_date = :expected_delivery_date,
        footer_note = :footer_note,
        internal_note = :internal_note,
        gross_amount = :gross_amount,
        net_amount = :net_amount,
        freight_charges = :freight_charges,
        round_off_value = :round_off_value,
        delivery_order_no = COALESCE(:delivery_order_no, delivery_order_no),
        active = COALESCE(:active, active),
        status_id = COALESCE(:status_id, status_id)
    WHERE sales_delivery_order_id = :sales_delivery_order_id;"""
    return text(sql)


def delete_sales_delivery_order_dtl():
    sql = """UPDATE sales_delivery_order_dtl SET
        active = 0,
        updated_by = :updated_by,
        updated_date_time = :updated_date_time
    WHERE sales_delivery_order_id = :sales_delivery_order_id;"""
    return text(sql)


def delete_sales_delivery_order_dtl_gst():
    sql = """DELETE FROM sales_delivery_order_dtl_gst
    WHERE sales_delivery_order_dtl_id IN (
        SELECT sales_delivery_order_dtl_id FROM sales_delivery_order_dtl
        WHERE sales_delivery_order_id = :sales_delivery_order_id
    );"""
    return text(sql)


def get_delivery_order_table_query():
    sql = """SELECT
        sdo.sales_delivery_order_id,
        sdo.delivery_order_no,
        sdo.delivery_order_date,
        sdo.expected_delivery_date,
        sdo.branch_id,
        bm.branch_name,
        bm.branch_prefix,
        bm.co_id,
        cm.co_prefix,
        sdo.party_id,
        pm.supp_name AS party_name,
        sdo.sales_order_id,
        so.sales_no,
        sdo.gross_amount,
        sdo.net_amount,
        sdo.status_id,
        sm.status_name
    FROM sales_delivery_order AS sdo
    LEFT JOIN branch_mst AS bm ON bm.branch_id = sdo.branch_id
    LEFT JOIN co_mst AS cm ON cm.co_id = bm.co_id
    LEFT JOIN party_mst AS pm ON pm.party_id = sdo.party_id
    LEFT JOIN sales_order AS so ON so.sales_order_id = sdo.sales_order_id
    LEFT JOIN status_mst AS sm ON sm.status_id = sdo.status_id
    WHERE sdo.active = 1
        AND (:co_id IS NULL OR bm.co_id = :co_id)
        AND (:branch_id IS NULL OR sdo.branch_id = :branch_id)
        AND (:status_id IS NULL OR sdo.status_id = :status_id)
        AND (
            :search_like IS NULL
            OR sdo.delivery_order_no LIKE :search_like
            OR pm.supp_name LIKE :search_like
            OR bm.branch_name LIKE :search_like
            OR so.sales_no LIKE :search_like
        )
    ORDER BY sdo.delivery_order_date DESC, sdo.sales_delivery_order_id DESC
    LIMIT :limit OFFSET :offset;"""
    return text(sql)


def get_delivery_order_table_count_query():
    sql = """SELECT COUNT(1) AS total
    FROM sales_delivery_order AS sdo
    LEFT JOIN branch_mst AS bm ON bm.branch_id = sdo.branch_id
    LEFT JOIN party_mst AS pm ON pm.party_id = sdo.party_id
    LEFT JOIN sales_order AS so ON so.sales_order_id = sdo.sales_order_id
    WHERE sdo.active = 1
        AND (:co_id IS NULL OR bm.co_id = :co_id)
        AND (:branch_id IS NULL OR sdo.branch_id = :branch_id)
        AND (:status_id IS NULL OR sdo.status_id = :status_id)
        AND (
            :search_like IS NULL
            OR sdo.delivery_order_no LIKE :search_like
            OR pm.supp_name LIKE :search_like
            OR bm.branch_name LIKE :search_like
            OR so.sales_no LIKE :search_like
        );"""
    return text(sql)


def get_delivery_order_by_id_query():
    sql = """SELECT
        sdo.sales_delivery_order_id,
        sdo.delivery_order_no,
        sdo.delivery_order_date,
        sdo.expected_delivery_date,
        sdo.branch_id,
        bm.branch_name,
        bm.branch_prefix,
        bm.co_id,
        cm.co_prefix,
        cm.co_name,
        cm.co_logo,
        sdo.invoice_type,
        sdo.sales_order_id,
        so.sales_no,
        sdo.party_id,
        pm.supp_name AS party_name,
        sdo.billing_to_id,
        sdo.shipping_to_id,
        sdo.transporter_id,
        trns.supp_name AS transporter_name,
        sdo.vehicle_no,
        sdo.driver_name,
        sdo.driver_contact,
        sdo.footer_note,
        sdo.internal_note,
        sdo.gross_amount,
        sdo.net_amount,
        sdo.freight_charges,
        sdo.round_off_value,
        sdo.status_id,
        sm.status_name,
        sdo.updated_by,
        sdo.updated_date_time,
        CASE
            WHEN sdo.status_id = 20 THEN sdo.approval_level
            ELSE NULL
        END AS approval_level
    FROM sales_delivery_order AS sdo
    LEFT JOIN branch_mst AS bm ON bm.branch_id = sdo.branch_id
    LEFT JOIN co_mst AS cm ON cm.co_id = bm.co_id
    LEFT JOIN sales_order AS so ON so.sales_order_id = sdo.sales_order_id
    LEFT JOIN party_mst AS pm ON pm.party_id = sdo.party_id
    LEFT JOIN party_mst AS trns ON trns.party_id = sdo.transporter_id
    LEFT JOIN status_mst AS sm ON sm.status_id = sdo.status_id
    WHERE sdo.sales_delivery_order_id = :sales_delivery_order_id
        AND (:co_id IS NULL OR bm.co_id = :co_id);"""
    return text(sql)


def get_delivery_order_dtl_by_id_query():
    sql = """SELECT
        sdod.sales_delivery_order_dtl_id,
        sdod.sales_delivery_order_id,
        sdod.sales_order_dtl_id,
        sdod.hsn_code,
        sdod.item_id,
        im.item_code,
        vip.full_item_code,
        im.item_name,
        im.item_grp_id,
        igm.item_grp_code,
        igm.item_grp_name,
        sdod.item_make_id,
        imk.item_make_name,
        sdod.quantity,
        sdod.uom_id,
        um.uom_name,
        sdod.rate,
        sdod.discount_type,
        sdod.discounted_rate,
        sdod.discount_amount,
        sdod.net_amount,
        sdod.total_amount,
        sdod.remarks
    FROM sales_delivery_order_dtl AS sdod
    LEFT JOIN item_mst AS im ON im.item_id = sdod.item_id
    LEFT JOIN vw_item_with_group_path AS vip ON vip.item_id = im.item_id
    LEFT JOIN item_grp_mst AS igm ON igm.item_grp_id = im.item_grp_id
    LEFT JOIN item_make AS imk ON imk.item_make_id = sdod.item_make_id
    LEFT JOIN uom_mst AS um ON um.uom_id = sdod.uom_id
    WHERE sdod.sales_delivery_order_id = :sales_delivery_order_id
        AND sdod.active = 1
    ORDER BY sdod.sales_delivery_order_dtl_id;"""
    return text(sql)


def get_delivery_order_gst_by_id_query():
    sql = """SELECT
        sdog.sales_delivery_order_dtl_gst_id,
        sdog.sales_delivery_order_dtl_id,
        sdog.igst_amount, sdog.igst_percent,
        sdog.cgst_amount, sdog.cgst_percent,
        sdog.sgst_amount, sdog.sgst_percent,
        sdog.gst_total
    FROM sales_delivery_order_dtl_gst AS sdog
    WHERE sdog.sales_delivery_order_dtl_id IN (
        SELECT sales_delivery_order_dtl_id FROM sales_delivery_order_dtl
        WHERE sales_delivery_order_id = :sales_delivery_order_id AND active = 1
    )
    ORDER BY sdog.sales_delivery_order_dtl_id;"""
    return text(sql)


def update_delivery_order_status():
    sql = """UPDATE sales_delivery_order SET
        status_id = :status_id,
        approval_level = :approval_level,
        updated_by = :updated_by,
        updated_date_time = :updated_date_time,
        delivery_order_no = CASE
            WHEN :delivery_order_no IS NOT NULL THEN :delivery_order_no
            ELSE delivery_order_no
        END
    WHERE sales_delivery_order_id = :sales_delivery_order_id;"""
    return text(sql)


def get_delivery_order_with_approval_info():
    sql = """SELECT
        sdo.sales_delivery_order_id,
        sdo.status_id,
        sdo.approval_level,
        sdo.branch_id,
        sdo.delivery_order_date,
        sdo.delivery_order_no,
        sdo.net_amount,
        bm.co_id
    FROM sales_delivery_order sdo
    LEFT JOIN branch_mst bm ON bm.branch_id = sdo.branch_id
    WHERE sdo.sales_delivery_order_id = :sales_delivery_order_id;"""
    return text(sql)


def get_max_delivery_order_no_for_branch_fy():
    sql = """SELECT COALESCE(MAX(CAST(sdo.delivery_order_no AS UNSIGNED)), 0) AS max_doc_no
    FROM sales_delivery_order sdo
    WHERE sdo.branch_id = :branch_id
        AND sdo.delivery_order_date >= :fy_start_date
        AND sdo.delivery_order_date <= :fy_end_date
        AND sdo.delivery_order_no IS NOT NULL;"""
    return text(sql)


# =============================================================================
# SALES INVOICE QUERIES
# =============================================================================


def get_approved_delivery_orders_query():
    """Get all approved delivery orders (status_id = 3) for dropdown when creating invoice."""
    sql = """SELECT
        sdo.sales_delivery_order_id,
        sdo.delivery_order_no,
        sdo.delivery_order_date,
        sdo.party_id,
        pm.supp_name AS party_name,
        sdo.branch_id,
        bm.branch_name,
        bm.branch_prefix,
        bm.co_id,
        cm.co_prefix,
        sdo.net_amount,
        sdo.sales_order_id,
        so.sales_order_date,
        so.sales_no AS sales_order_no,
        sdo.party_id,
        sdo.invoice_type,
        sdo.billing_to_id,
        sdo.shipping_to_id,
        sdo.transporter_id
    FROM sales_delivery_order AS sdo
    LEFT JOIN branch_mst AS bm ON bm.branch_id = sdo.branch_id
    LEFT JOIN co_mst AS cm ON cm.co_id = bm.co_id
    LEFT JOIN party_mst AS pm ON pm.party_id = sdo.party_id
    LEFT JOIN sales_order AS so ON so.sales_order_id = sdo.sales_order_id
    WHERE sdo.status_id = 3
        AND sdo.active = 1
        AND (:branch_id IS NULL OR sdo.branch_id = :branch_id)
        AND (:co_id IS NULL OR bm.co_id = :co_id)
    ORDER BY sdo.delivery_order_date DESC, sdo.sales_delivery_order_id DESC;"""
    return text(sql)


def get_delivery_order_lines_for_invoice():
    """Get delivery order line items to pre-fill invoice lines.
    Joins vw_sales_do_outstanding to include balance columns and
    filters out fully-invoiced lines (bal_do_qty = 0)."""
    sql = """SELECT
        sdod.sales_delivery_order_dtl_id AS delivery_order_dtl_id,
        sdod.hsn_code,
        sdod.item_id,
        im.item_code,
        vip.full_item_code,
        im.item_name,
        im.item_grp_id,
        igm.item_grp_code AS item_grp_code,
        igm.item_grp_name AS item_grp_name,
        sdod.item_make_id,
        imk.item_make_name,
        sdod.quantity,
        sdod.uom_id,
        um.uom_name,
        sdod.rate,
        sdod.discount_type,
        sdod.discounted_rate,
        sdod.discount_amount,
        sdod.net_amount,
        sdod.total_amount,
        sdod.remarks,
        COALESCE(im.tax_percentage, 0) AS tax_percentage,
        sogd.pack_sheet AS govtskg_pack_sheet,
        sogd.net_weight AS govtskg_net_weight,
        sogd.total_weight AS govtskg_total_weight,
        COALESCE(vdo.do_qty, sdod.quantity) AS do_qty,
        COALESCE(vdo.invoice_consumed_qty, 0) AS invoice_consumed_qty,
        COALESCE(vdo.bal_do_qty, sdod.quantity) AS bal_do_qty
    FROM sales_delivery_order_dtl AS sdod
    LEFT JOIN item_mst AS im ON im.item_id = sdod.item_id
    LEFT JOIN vw_item_with_group_path AS vip ON vip.item_id = im.item_id
    LEFT JOIN item_grp_mst AS igm ON igm.item_grp_id = im.item_grp_id
    LEFT JOIN item_make AS imk ON imk.item_make_id = sdod.item_make_id
    LEFT JOIN uom_mst AS um ON um.uom_id = sdod.uom_id
    LEFT JOIN sales_order_govtskg_dtl AS sogd ON sogd.sales_order_dtl_id = sdod.sales_order_dtl_id
    LEFT JOIN vw_sales_do_outstanding AS vdo ON vdo.sales_delivery_order_dtl_id = sdod.sales_delivery_order_dtl_id
    WHERE sdod.sales_delivery_order_id = :sales_delivery_order_id
        AND sdod.active = 1
        AND (vdo.bal_do_qty > 0 OR vdo.bal_do_qty IS NULL)
    ORDER BY sdod.sales_delivery_order_dtl_id;"""
    return text(sql)


def get_sales_order_lines_for_invoice():
    """Get sales order line items to pre-fill invoice lines.
    Joins vw_sales_order_outstanding to include balance columns and
    filters out fully-invoiced lines (bal_invoice_qty = 0)."""
    sql = """SELECT
        sod.sales_order_dtl_id,
        sod.hsn_code,
        sod.item_id,
        im.item_code,
        vip.full_item_code,
        im.item_name,
        im.item_grp_id,
        igm.item_grp_code AS item_grp_code,
        igm.item_grp_name AS item_grp_name,
        sod.item_make_id,
        imk.item_make_name,
        sod.quantity,
        sod.uom_id,
        um.uom_name,
        sod.rate,
        sod.discount_type,
        sod.discounted_rate,
        sod.discount_amount,
        sod.net_amount,
        sod.total_amount,
        sod.remarks,
        COALESCE(im.tax_percentage, 0) AS tax_percentage,
        COALESCE(vso.so_qty, sod.quantity) AS so_qty,
        COALESCE(vso.invoice_consumed_qty, 0) AS invoice_consumed_qty,
        COALESCE(vso.bal_invoice_qty, sod.quantity) AS bal_invoice_qty
    FROM sales_order_dtl AS sod
    LEFT JOIN item_mst AS im ON im.item_id = sod.item_id
    LEFT JOIN vw_item_with_group_path AS vip ON vip.item_id = im.item_id
    LEFT JOIN item_grp_mst AS igm ON igm.item_grp_id = im.item_grp_id
    LEFT JOIN item_make AS imk ON imk.item_make_id = sod.item_make_id
    LEFT JOIN uom_mst AS um ON um.uom_id = sod.uom_id
    LEFT JOIN vw_sales_order_outstanding AS vso ON vso.sales_order_dtl_id = sod.sales_order_dtl_id
    WHERE sod.sales_order_id = :sales_order_id
        AND sod.active = 1
        AND (vso.bal_invoice_qty > 0 OR vso.bal_invoice_qty IS NULL)
    ORDER BY sod.sales_order_dtl_id;"""
    return text(sql)


def get_approved_sales_orders_for_invoice():
    """Get approved sales orders (status_id=3) for dropdown when creating invoice."""
    sql = """SELECT
        so.sales_order_id,
        so.sales_no,
        so.sales_order_date,
        so.party_id,
        pm.supp_name AS party_name,
        so.branch_id,
        bm.branch_name,
        bm.branch_prefix,
        bm.co_id,
        cm.co_prefix,
        so.payment_terms,
        so.invoice_type,
        so.broker_id,
        so.billing_to_id,
        so.shipping_to_id,
        so.transporter_id,
        so.buyer_order_no,
        so.buyer_order_date
    FROM sales_order AS so
    LEFT JOIN branch_mst AS bm ON bm.branch_id = so.branch_id
    LEFT JOIN co_mst AS cm ON cm.co_id = bm.co_id
    LEFT JOIN party_mst AS pm ON pm.party_id = so.party_id
    WHERE so.status_id = 3
        AND so.active = 1
        AND (:branch_id IS NULL OR so.branch_id = :branch_id)
        AND (:co_id IS NULL OR bm.co_id = :co_id)
    ORDER BY so.sales_order_date DESC, so.sales_order_id DESC;"""
    return text(sql)


def get_invoice_table_query():
    sql = """SELECT
        si.invoice_id,
        si.invoice_no,
        si.invoice_date,
        si.branch_id,
        bm.branch_name,
        bm.branch_prefix,
        bm.co_id,
        cm.co_prefix,
        si.party_id,
        pm.supp_name AS party_name,
        si.sales_delivery_order_id,
        sdo.delivery_order_no AS do_raw_no,
        sdo.delivery_order_date AS do_date,
        si.invoice_amount,
        si.status_id,
        sm.status_name
    FROM sales_invoice AS si
    LEFT JOIN branch_mst AS bm ON bm.branch_id = si.branch_id
    LEFT JOIN co_mst AS cm ON cm.co_id = bm.co_id
    LEFT JOIN party_mst AS pm ON pm.party_id = si.party_id
    LEFT JOIN sales_delivery_order AS sdo ON sdo.sales_delivery_order_id = si.sales_delivery_order_id
    LEFT JOIN status_mst AS sm ON sm.status_id = si.status_id
    WHERE (si.active = 1 OR si.active IS NULL)
        AND (:co_id IS NULL OR bm.co_id = :co_id)
        AND (:branch_id IS NULL OR si.branch_id = :branch_id)
        AND (:status_id IS NULL OR si.status_id = :status_id)
        AND (
            :search_like IS NULL
            OR CAST(si.invoice_no AS CHAR) LIKE :search_like
            OR pm.supp_name LIKE :search_like
            OR bm.branch_name LIKE :search_like
        )
    ORDER BY si.invoice_date DESC, si.invoice_id DESC
    LIMIT :limit OFFSET :offset;"""
    return text(sql)


def get_invoice_table_count_query():
    sql = """SELECT COUNT(1) AS total
    FROM sales_invoice AS si
    LEFT JOIN branch_mst AS bm ON bm.branch_id = si.branch_id
    LEFT JOIN party_mst AS pm ON pm.party_id = si.party_id
    WHERE (si.active = 1 OR si.active IS NULL)
        AND (:co_id IS NULL OR bm.co_id = :co_id)
        AND (:branch_id IS NULL OR si.branch_id = :branch_id)
        AND (:status_id IS NULL OR si.status_id = :status_id)
        AND (
            :search_like IS NULL
            OR CAST(si.invoice_no AS CHAR) LIKE :search_like
            OR pm.supp_name LIKE :search_like
            OR bm.branch_name LIKE :search_like
        );"""
    return text(sql)


def get_invoice_by_id_query():
    sql = """SELECT
        si.invoice_id,
        si.invoice_no,
        si.invoice_date,
        si.challan_no,
        si.challan_date,
        si.branch_id,
        bm.branch_name,
        bm.branch_prefix,
        bm.co_id,
        cm.co_prefix,
        si.party_id,
        pm.supp_name AS party_name,
        si.sales_delivery_order_id,
        si.broker_id,
        si.billing_to_id,
        pbill.address AS billing_address,
        pbill.gst_no AS billing_gst_no,
        pbill.state_id AS billing_state_id,
        sbill.state AS billing_state_name,
        pbill.contact_person AS billing_contact_person,
        pbill.contact_no AS billing_contact_no,
        si.shipping_to_id,
        pship.address AS shipping_address,
        pship.gst_no AS shipping_gst_no,
        pship.state_id AS shipping_state_id,
        sship.state AS shipping_state_name,
        pship.contact_person AS shipping_contact_person,
        pship.contact_no AS shipping_contact_no,
        si.internal_note,
        si.shipping_state_code,
        si.transporter_id,
        trns.supp_name AS transporter_name,
        si.transporter_name AS transporter_name_stored,
        si.transporter_address,
        si.transporter_state_code,
        si.transporter_state_name,
        si.transporter_branch_id,
        si.transporter_doc_no,
        si.transporter_doc_date,
        si.buyer_order_no,
        si.buyer_order_date,
        si.irn,
        si.ack_no,
        si.ack_date,
        si.qr_code,
        pbm_transporter.gst_no AS transporter_gst_no,
        si.vehicle_no,
        si.eway_bill_no,
        si.eway_bill_date,
        si.invoice_type,
        si.footer_notes,
        si.terms,
        si.terms_conditions,
        si.invoice_amount,
        si.tax_amount,
        si.tax_payable,
        si.freight_charges,
        si.round_off,
        si.due_date,
        si.type_of_sale,
        si.tax_id,
        si.container_no,
        si.contract_no,
        si.contract_date,
        si.consignment_no,
        si.consignment_date,
        si.status_id,
        sm.status_name,
        si.updated_by,
        si.updated_date_time,
        si.intra_inter_state,
        si.payment_terms,
        si.sales_order_id,
        si.billing_state_code,
        si.bank_detail_id,
        bdm.bank_name,
        bdm.acc_no AS bank_acc_no,
        bdm.ifsc_code AS bank_ifsc_code,
        bdm.bank_branch AS bank_branch_name,
        cm.co_name,
        cm.co_logo,
        cm.co_address1,
        cm.co_address2,
        cm.co_zipcode,
        cm.co_cin_no,
        cm.co_pan_no,
        scm.state AS co_state_name,
        scm.state_code AS co_state_code,
        bm.branch_address1,
        bm.branch_address2,
        bm.branch_zipcode,
        bm.gst_no AS branch_gst_no,
        sbm.state AS branch_state_name,
        sbm.state_code AS branch_state_code,
        so.sales_order_date,
        so.sales_no AS sales_order_no
    FROM sales_invoice AS si
    LEFT JOIN branch_mst AS bm ON bm.branch_id = si.branch_id
    LEFT JOIN co_mst AS cm ON cm.co_id = bm.co_id
    LEFT JOIN state_mst AS scm ON scm.state_id = cm.state_id
    LEFT JOIN state_mst AS sbm ON sbm.state_id = bm.state_id
    LEFT JOIN party_mst AS pm ON pm.party_id = si.party_id
    LEFT JOIN party_mst AS trns ON trns.party_id = si.transporter_id
    LEFT JOIN status_mst AS sm ON sm.status_id = si.status_id
    LEFT JOIN party_branch_mst AS pbill ON pbill.party_mst_branch_id = si.billing_to_id
    LEFT JOIN state_mst AS sbill ON sbill.state_id = pbill.state_id
    LEFT JOIN party_branch_mst AS pship ON pship.party_mst_branch_id = si.shipping_to_id
    LEFT JOIN state_mst AS sship ON sship.state_id = pship.state_id
    LEFT JOIN sales_order AS so ON so.sales_order_id = si.sales_order_id
    LEFT JOIN bank_details_mst AS bdm ON bdm.bank_detail_id = si.bank_detail_id
    LEFT JOIN party_branch_mst AS pbm_transporter ON pbm_transporter.party_mst_branch_id = si.transporter_branch_id
    WHERE si.invoice_id = :invoice_id
        AND (:co_id IS NULL OR bm.co_id = :co_id);"""
    return text(sql)


def get_invoice_dtl_by_id_query():
    sql = """SELECT
        ili.invoice_line_item_id,
        ili.invoice_id,
        ili.hsn_code,
        ili.item_id,
        im.item_code,
        vip.full_item_code,
        im.item_name,
        im.item_grp_id,
        ili.item_make_id,
        ili.quantity,
        ili.uom_id,
        um.uom_name,
        ili.rate,
        ili.discount_type,
        ili.discounted_rate,
        ili.discount_amount,
        ili.amount_without_tax,
        ili.total_amount,
        ili.sales_weight,
        ili.remarks,
        ili.delivery_order_dtl_id,
        ili.sales_order_dtl_id
    FROM sales_invoice_dtl AS ili
    LEFT JOIN item_mst AS im ON im.item_id = ili.item_id
    LEFT JOIN vw_item_with_group_path AS vip ON vip.item_id = im.item_id
    LEFT JOIN uom_mst AS um ON um.uom_id = ili.uom_id
    WHERE ili.invoice_id = :invoice_id
    ORDER BY ili.invoice_line_item_id;"""
    return text(sql)


def insert_sales_invoice(
    invoice_date=None, invoice_no=None,
    branch_id=None, party_id=None,
    sales_delivery_order_id=None, broker_id=None,
    billing_to_id=None, shipping_to_id=None,
    challan_no=None, challan_date=None,
    transporter_id=None, vehicle_no=None,
    transporter_name=None, transporter_address=None,
    transporter_state_code=None, transporter_state_name=None,
    eway_bill_no=None, eway_bill_date=None,
    invoice_type=None, footer_notes=None, internal_note=None, terms=None, terms_conditions=None,
    invoice_amount=None, tax_amount=None, tax_payable=None,
    freight_charges=None, round_off=None,
    shipping_state_code=None,
    intra_inter_state=None,
    status_id=None, active=None,
    due_date=None, type_of_sale=None, tax_id=None,
    container_no=None, contract_no=None, contract_date=None,
    consignment_no=None, consignment_date=None,
    payment_terms=None, sales_order_id=None, billing_state_code=None,
    bank_detail_id=None,
    updated_by=None,
    transporter_branch_id=None,
    transporter_doc_no=None,
    transporter_doc_date=None,
    buyer_order_no=None,
    buyer_order_date=None,
    irn=None,
    ack_no=None,
    ack_date=None,
    qr_code=None,
):
    sql = """INSERT INTO sales_invoice (
        invoice_date, invoice_no,
        branch_id, party_id,
        sales_delivery_order_id, broker_id,
        billing_to_id, shipping_to_id,
        challan_no, challan_date,
        transporter_id, vehicle_no,
        transporter_name, transporter_address,
        transporter_state_code, transporter_state_name,
        eway_bill_no, eway_bill_date,
        invoice_type, footer_notes, internal_note, terms, terms_conditions,
        invoice_amount, tax_amount, tax_payable,
        freight_charges, round_off,
        shipping_state_code,
        intra_inter_state,
        status_id, active,
        due_date, type_of_sale, tax_id,
        container_no, contract_no, contract_date,
        consignment_no, consignment_date,
        payment_terms, sales_order_id, billing_state_code,
        bank_detail_id,
        transporter_branch_id,
        transporter_doc_no,
        transporter_doc_date,
        buyer_order_no,
        buyer_order_date,
        irn,
        ack_no,
        ack_date,
        qr_code,
        updated_by, updated_date_time
    ) VALUES (
        :invoice_date, :invoice_no,
        :branch_id, :party_id,
        :sales_delivery_order_id, :broker_id,
        :billing_to_id, :shipping_to_id,
        :challan_no, :challan_date,
        :transporter_id, :vehicle_no,
        :transporter_name, :transporter_address,
        :transporter_state_code, :transporter_state_name,
        :eway_bill_no, :eway_bill_date,
        :invoice_type, :footer_notes, :internal_note, :terms, :terms_conditions,
        :invoice_amount, :tax_amount, :tax_payable,
        :freight_charges, :round_off,
        :shipping_state_code,
        :intra_inter_state,
        :status_id, :active,
        :due_date, :type_of_sale, :tax_id,
        :container_no, :contract_no, :contract_date,
        :consignment_no, :consignment_date,
        :payment_terms, :sales_order_id, :billing_state_code,
        :bank_detail_id,
        :transporter_branch_id,
        :transporter_doc_no,
        :transporter_doc_date,
        :buyer_order_no,
        :buyer_order_date,
        :irn,
        :ack_no,
        :ack_date,
        :qr_code,
        :updated_by, NOW()
    );"""
    return text(sql)


def insert_invoice_line_item():
    sql = """INSERT INTO sales_invoice_dtl (
        invoice_id,
        hsn_code, item_id, item_make_id,
        quantity, uom_id, rate,
        discount_type, discounted_rate, discount_amount,
        amount_without_tax, total_amount,
        sales_weight, remarks, delivery_order_dtl_id, sales_order_dtl_id
    ) VALUES (
        :invoice_id,
        :hsn_code, :item_id, :item_make_id,
        :quantity, :uom_id, :rate,
        :discount_type, :discounted_rate, :discount_amount,
        :amount_without_tax, :total_amount,
        :sales_weight, :remarks, :delivery_order_dtl_id, :sales_order_dtl_id
    );"""
    return text(sql)


def update_sales_invoice(
    invoice_date=None, branch_id=None, party_id=None,
    sales_delivery_order_id=None, broker_id=None,
    billing_to_id=None, shipping_to_id=None,
    challan_no=None, challan_date=None,
    transporter_id=None, vehicle_no=None,
    transporter_name=None, transporter_address=None,
    transporter_state_code=None, transporter_state_name=None,
    eway_bill_no=None, eway_bill_date=None,
    invoice_type=None, footer_notes=None, internal_note=None,
    terms=None, terms_conditions=None,
    invoice_amount=None, tax_amount=None, tax_payable=None,
    freight_charges=None, round_off=None,
    shipping_state_code=None, intra_inter_state=None,
    due_date=None, type_of_sale=None, tax_id=None,
    container_no=None, contract_no=None, contract_date=None,
    consignment_no=None, consignment_date=None,
    payment_terms=None, sales_order_id=None, billing_state_code=None,
    bank_detail_id=None, updated_by=None,
    transporter_branch_id=None,
    transporter_doc_no=None,
    transporter_doc_date=None,
    buyer_order_no=None,
    buyer_order_date=None,
    irn=None,
    ack_no=None,
    ack_date=None,
    qr_code=None,
):
    sql = """UPDATE sales_invoice SET
        invoice_date = :invoice_date,
        branch_id = :branch_id,
        party_id = :party_id,
        sales_delivery_order_id = :sales_delivery_order_id,
        broker_id = :broker_id,
        billing_to_id = :billing_to_id,
        shipping_to_id = :shipping_to_id,
        challan_no = :challan_no,
        challan_date = :challan_date,
        transporter_id = :transporter_id,
        vehicle_no = :vehicle_no,
        transporter_name = :transporter_name,
        transporter_address = :transporter_address,
        transporter_state_code = :transporter_state_code,
        transporter_state_name = :transporter_state_name,
        eway_bill_no = :eway_bill_no,
        eway_bill_date = :eway_bill_date,
        invoice_type = :invoice_type,
        footer_notes = :footer_notes,
        internal_note = :internal_note,
        terms = :terms,
        terms_conditions = :terms_conditions,
        invoice_amount = :invoice_amount,
        tax_amount = :tax_amount,
        tax_payable = :tax_payable,
        freight_charges = :freight_charges,
        round_off = :round_off,
        shipping_state_code = :shipping_state_code,
        intra_inter_state = :intra_inter_state,
        due_date = :due_date,
        type_of_sale = :type_of_sale,
        tax_id = :tax_id,
        container_no = :container_no,
        contract_no = :contract_no,
        contract_date = :contract_date,
        consignment_no = :consignment_no,
        consignment_date = :consignment_date,
        payment_terms = :payment_terms,
        sales_order_id = :sales_order_id,
        billing_state_code = :billing_state_code,
        bank_detail_id = :bank_detail_id,
        transporter_branch_id = :transporter_branch_id,
        transporter_doc_no = :transporter_doc_no,
        transporter_doc_date = :transporter_doc_date,
        buyer_order_no = :buyer_order_no,
        buyer_order_date = :buyer_order_date,
        irn = :irn,
        ack_no = :ack_no,
        ack_date = :ack_date,
        qr_code = :qr_code,
        updated_by = :updated_by,
        updated_date_time = NOW()
    WHERE invoice_id = :invoice_id;"""
    return text(sql)


def delete_invoice_line_items():
    sql = """DELETE FROM sales_invoice_dtl
    WHERE invoice_id = :invoice_id;"""
    return text(sql)


def insert_invoice_dtl_gst():
    """Insert GST breakup for a sales invoice line item."""
    sql = """INSERT INTO sales_invoice_dtl_gst (
        invoice_line_item_id,
        igst_amount, igst_percent,
        cgst_amount, cgst_percent,
        sgst_amount, sgst_percent,
        gst_total
    ) VALUES (
        :invoice_line_item_id,
        :igst_amount, :igst_percent,
        :cgst_amount, :cgst_percent,
        :sgst_amount, :sgst_percent,
        :gst_total
    );"""
    return text(sql)


def delete_invoice_dtl_gst():
    """Delete GST breakup rows for all line items of an invoice."""
    sql = """DELETE FROM sales_invoice_dtl_gst
    WHERE invoice_line_item_id IN (
        SELECT invoice_line_item_id FROM sales_invoice_dtl WHERE invoice_id = :invoice_id
    );"""
    return text(sql)


def get_invoice_dtl_gst_by_id_query():
    """Get GST details for all line items of an invoice."""
    sql = """SELECT
        g.sales_invoice_dtl_gst_id,
        g.invoice_line_item_id,
        g.igst_amount, g.igst_percent,
        g.cgst_amount, g.cgst_percent,
        g.sgst_amount, g.sgst_percent,
        g.gst_total
    FROM sales_invoice_dtl_gst AS g
    INNER JOIN sales_invoice_dtl AS d ON d.invoice_line_item_id = g.invoice_line_item_id
    WHERE d.invoice_id = :invoice_id
    ORDER BY g.invoice_line_item_id;"""
    return text(sql)


def update_invoice_status():
    sql = """UPDATE sales_invoice SET
        status_id = :status_id,
        approval_level = :approval_level,
        invoice_no = CASE
            WHEN :invoice_no IS NOT NULL THEN :invoice_no
            ELSE invoice_no
        END,
        updated_by = :updated_by,
        updated_date_time = :updated_date_time
    WHERE invoice_id = :invoice_id;"""
    return text(sql)


def get_invoice_with_approval_info():
    sql = """SELECT
        si.invoice_id,
        si.status_id,
        si.approval_level,
        si.invoice_no,
        si.branch_id,
        si.invoice_date,
        si.invoice_amount,
        bm.co_id
    FROM sales_invoice si
    LEFT JOIN branch_mst bm ON bm.branch_id = si.branch_id
    WHERE si.invoice_id = :invoice_id;"""
    return text(sql)


def get_max_invoice_no_for_branch_fy():
    sql = """SELECT COALESCE(MAX(si.invoice_no), 0) AS max_doc_no
    FROM sales_invoice si
    WHERE si.branch_id = :branch_id
        AND si.invoice_date >= :fy_start_date
        AND si.invoice_date <= :fy_end_date
        AND si.invoice_no IS NOT NULL;"""
    return text(sql)


# =============================================================================
# JUTE INVOICE QUERIES
# =============================================================================


def get_mukam_list():
    """Get all mukam entries for dropdown."""
    sql = """SELECT mukam_id, mukam_name
    FROM jute_mukam_mst
    ORDER BY mukam_name;"""
    return text(sql)


def insert_sale_invoice_jute():
    """Insert jute-specific data for a sales invoice (DEPRECATED — use insert_sales_invoice_jute)."""
    sql = """INSERT INTO sale_invoice_jute (
        invoice_id, mr_no, mr_id,
        claim_amount, other_reference, unit_conversion,
        despatch_doc_no, despatched_through, mukam_id, claim_note
    ) VALUES (
        :invoice_id, :mr_no, :mr_id,
        :claim_amount, :other_reference, :unit_conversion,
        :despatch_doc_no, :despatched_through, :mukam_id, :claim_note
    );"""
    return text(sql)


def delete_sale_invoice_jute():
    """Delete jute-specific data for a sales invoice (DEPRECATED — use delete_sales_invoice_jute)."""
    sql = """DELETE FROM sale_invoice_jute
    WHERE invoice_id = :invoice_id;"""
    return text(sql)


def get_sale_invoice_jute_by_id():
    """Get jute-specific data for a sales invoice (DEPRECATED — use get_sales_invoice_jute_by_id)."""
    sql = """SELECT
        sij.sale_invoice_jute_id,
        sij.invoice_id,
        sij.mr_no,
        sij.mr_id,
        sij.claim_amount,
        sij.other_reference,
        sij.unit_conversion,
        sij.despatch_doc_no,
        sij.despatched_through,
        sij.mukam_id,
        jm.mukam_name,
        sij.claim_note
    FROM sale_invoice_jute AS sij
    LEFT JOIN jute_mukam_mst AS jm ON jm.mukam_id = sij.mukam_id
    WHERE sij.invoice_id = :invoice_id;"""
    return text(sql)


# =============================================================================
# SALES INVOICE — GST (separate table)
# =============================================================================

def insert_sales_invoice_dtl_gst():
    """Insert GST breakdown for a sales invoice line item."""
    sql = """INSERT INTO sales_invoice_dtl_gst (
        invoice_line_item_id,
        tax_percentage,
        cgst_amount, cgst_percentage,
        sgst_amount, sgst_percentage,
        igst_amount, igst_percentage,
        tax_amount
    ) VALUES (
        :invoice_line_item_id,
        :tax_percentage,
        :cgst_amount, :cgst_percentage,
        :sgst_amount, :sgst_percentage,
        :igst_amount, :igst_percentage,
        :tax_amount
    );"""
    return text(sql)


def delete_sales_invoice_dtl_gst():
    """Hard delete GST rows for all line items of an invoice (re-inserted on update)."""
    sql = """DELETE FROM sales_invoice_dtl_gst
    WHERE invoice_line_item_id IN (
        SELECT invoice_line_item_id FROM sales_invoice_dtl
        WHERE invoice_id = :invoice_id
    );"""
    return text(sql)


def get_sales_invoice_dtl_gst_by_invoice_id():
    """Get all GST rows for an invoice's line items."""
    sql = """SELECT
        g.sales_invoice_dtl_gst_id,
        g.invoice_line_item_id,
        g.tax_percentage,
        g.cgst_amount, g.cgst_percentage,
        g.sgst_amount, g.sgst_percentage,
        g.igst_amount, g.igst_percentage,
        g.tax_amount
    FROM sales_invoice_dtl_gst AS g
    WHERE g.invoice_line_item_id IN (
        SELECT invoice_line_item_id FROM sales_invoice_dtl
        WHERE invoice_id = :invoice_id
    );"""
    return text(sql)


# =============================================================================
# SALES INVOICE — JUTE (new tables: sales_invoice_jute + sales_invoice_jute_dtl)
# =============================================================================

def insert_sales_invoice_jute():
    """Insert header-level jute data for a sales invoice."""
    sql = """INSERT INTO sales_invoice_jute (
        invoice_id, mr_no, mr_id,
        claim_amount, other_reference, unit_conversion,
        claim_description, mukam_id
    ) VALUES (
        :invoice_id, :mr_no, :mr_id,
        :claim_amount, :other_reference, :unit_conversion,
        :claim_description, :mukam_id
    );"""
    return text(sql)


def delete_sales_invoice_jute():
    """Delete header-level jute data for a sales invoice."""
    sql = """DELETE FROM sales_invoice_jute
    WHERE invoice_id = :invoice_id;"""
    return text(sql)


def get_sales_invoice_jute_by_id():
    """Get header-level jute data for a sales invoice."""
    sql = """SELECT
        sij.sales_invoice_jute_id,
        sij.invoice_id,
        sij.mr_no,
        sij.mr_id,
        sij.claim_amount,
        sij.other_reference,
        sij.unit_conversion,
        sij.claim_description,
        sij.mukam_id,
        jm.mukam_name
    FROM sales_invoice_jute AS sij
    LEFT JOIN jute_mukam_mst AS jm ON jm.mukam_id = sij.mukam_id
    WHERE sij.invoice_id = :invoice_id;"""
    return text(sql)


def insert_sales_invoice_jute_dtl():
    """Insert per-line-item jute detail data."""
    sql = """INSERT INTO sales_invoice_jute_dtl (
        invoice_line_item_id,
        claim_amount_dtl, claim_desc, claim_rate,
        unit_conversion, qty_untit_conversion
    ) VALUES (
        :invoice_line_item_id,
        :claim_amount_dtl, :claim_desc, :claim_rate,
        :unit_conversion, :qty_untit_conversion
    );"""
    return text(sql)


def delete_sales_invoice_jute_dtl():
    """Delete per-line-item jute detail rows for an invoice."""
    sql = """DELETE FROM sales_invoice_jute_dtl
    WHERE invoice_line_item_id IN (
        SELECT invoice_line_item_id FROM sales_invoice_dtl
        WHERE invoice_id = :invoice_id
    );"""
    return text(sql)


def get_sales_invoice_jute_dtl_by_invoice_id():
    """Get all per-line-item jute detail rows for an invoice."""
    sql = """SELECT
        jd.sales_invoice_jute_dtl_id,
        jd.invoice_line_item_id,
        jd.claim_amount_dtl,
        jd.claim_desc,
        jd.claim_rate,
        jd.unit_conversion,
        jd.qty_untit_conversion
    FROM sales_invoice_jute_dtl AS jd
    WHERE jd.invoice_line_item_id IN (
        SELECT invoice_line_item_id FROM sales_invoice_dtl
        WHERE invoice_id = :invoice_id
    );"""
    return text(sql)


# =============================================================================
# HESSIAN INVOICE EXTENSION QUERIES
# =============================================================================

def insert_sales_invoice_hessian():
    """Insert header-level hessian data for a sales invoice."""
    sql = """INSERT INTO sales_invoice_hessian (
        invoice_id, qty_bales, rate_per_bale,
        billing_rate_mt, billing_rate_bale,
        updated_by, updated_date_time
    ) VALUES (
        :invoice_id, :qty_bales, :rate_per_bale,
        :billing_rate_mt, :billing_rate_bale,
        :updated_by, NOW()
    );"""
    return text(sql)


def delete_sales_invoice_hessian():
    """Delete header-level hessian data for a sales invoice."""
    sql = """DELETE FROM sales_invoice_hessian
    WHERE invoice_id = :invoice_id;"""
    return text(sql)


def get_sales_invoice_hessian_by_id():
    """Get header-level hessian data for a sales invoice."""
    sql = """SELECT
        sih.sales_invoice_hessian_id,
        sih.invoice_id,
        sih.qty_bales,
        sih.rate_per_bale,
        sih.billing_rate_mt,
        sih.billing_rate_bale
    FROM sales_invoice_hessian AS sih
    WHERE sih.invoice_id = :invoice_id;"""
    return text(sql)


def insert_sales_invoice_hessian_dtl():
    """Insert per-line-item hessian detail data."""
    sql = """INSERT INTO sales_invoice_hessian_dtl (
        invoice_line_item_id,
        qty_bales, rate_per_bale,
        billing_rate_mt, billing_rate_bale,
        updated_by, updated_date_time
    ) VALUES (
        :invoice_line_item_id,
        :qty_bales, :rate_per_bale,
        :billing_rate_mt, :billing_rate_bale,
        :updated_by, NOW()
    );"""
    return text(sql)


def delete_sales_invoice_hessian_dtl():
    """Delete per-line-item hessian detail rows for an invoice."""
    sql = """DELETE FROM sales_invoice_hessian_dtl
    WHERE invoice_line_item_id IN (
        SELECT invoice_line_item_id FROM sales_invoice_dtl
        WHERE invoice_id = :invoice_id
    );"""
    return text(sql)


def get_sales_invoice_hessian_dtl_by_invoice_id():
    """Get all per-line-item hessian detail rows for an invoice."""
    sql = """SELECT
        hd.sales_invoice_hessian_dtl_id,
        hd.invoice_line_item_id,
        hd.qty_bales,
        hd.rate_per_bale,
        hd.billing_rate_mt,
        hd.billing_rate_bale
    FROM sales_invoice_hessian_dtl AS hd
    WHERE hd.invoice_line_item_id IN (
        SELECT invoice_line_item_id FROM sales_invoice_dtl
        WHERE invoice_id = :invoice_id
    );"""
    return text(sql)


# =============================================================================
# JUTE YARN INVOICE EXTENSION QUERIES
# =============================================================================

def insert_sales_invoice_juteyarn():
    """Insert header-level jute yarn data for a sales invoice."""
    sql = """INSERT INTO sales_invoice_juteyarn (
        invoice_id, pcso_no, container_no, customer_ref_no,
        updated_by, updated_date_time
    ) VALUES (
        :invoice_id, :pcso_no, :container_no, :customer_ref_no,
        :updated_by, NOW()
    );"""
    return text(sql)


def delete_sales_invoice_juteyarn():
    """Delete header-level jute yarn data for a sales invoice."""
    sql = """DELETE FROM sales_invoice_juteyarn
    WHERE invoice_id = :invoice_id;"""
    return text(sql)


def get_sales_invoice_juteyarn_by_id():
    """Get header-level jute yarn data for a sales invoice."""
    sql = """SELECT
        sijy.sales_invoice_juteyarn_id,
        sijy.invoice_id,
        sijy.pcso_no,
        sijy.container_no,
        sijy.customer_ref_no
    FROM sales_invoice_juteyarn AS sijy
    WHERE sijy.invoice_id = :invoice_id;"""
    return text(sql)


def insert_sales_invoice_juteyarn_dtl():
    """Insert per-line-item jute yarn detail data."""
    sql = """INSERT INTO sales_invoice_juteyarn_dtl (
        invoice_line_item_id,
        updated_by, updated_date_time
    ) VALUES (
        :invoice_line_item_id,
        :updated_by, NOW()
    );"""
    return text(sql)


def delete_sales_invoice_juteyarn_dtl():
    """Delete per-line-item jute yarn detail rows for an invoice."""
    sql = """DELETE FROM sales_invoice_juteyarn_dtl
    WHERE invoice_line_item_id IN (
        SELECT invoice_line_item_id FROM sales_invoice_dtl
        WHERE invoice_id = :invoice_id
    );"""
    return text(sql)


def get_sales_invoice_juteyarn_dtl_by_invoice_id():
    """Get all per-line-item jute yarn detail rows for an invoice."""
    sql = """SELECT
        jyd.sales_invoice_juteyarn_dtl_id,
        jyd.invoice_line_item_id
    FROM sales_invoice_juteyarn_dtl AS jyd
    WHERE jyd.invoice_line_item_id IN (
        SELECT invoice_line_item_id FROM sales_invoice_dtl
        WHERE invoice_id = :invoice_id
    );"""
    return text(sql)


# =============================================================================
# GOVT SKG INVOICE HEADER EXTENSION QUERIES
# =============================================================================

def insert_sales_invoice_govtskg():
    """Insert header-level govt SKG data for a sales invoice."""
    sql = """INSERT INTO sales_invoice_govtskg (
        invoice_id, pcso_no, pcso_date,
        administrative_office_address, destination_rail_head,
        loading_point, mode_of_transport, pack_sheet, net_weight, total_weight
    ) VALUES (
        :invoice_id, :pcso_no, :pcso_date,
        :administrative_office_address, :destination_rail_head,
        :loading_point, :mode_of_transport, :pack_sheet, :net_weight, :total_weight
    );"""
    return text(sql)


def delete_sales_invoice_govtskg():
    """Delete header-level govt SKG data for a sales invoice."""
    sql = """DELETE FROM sales_invoice_govtskg
    WHERE invoice_id = :invoice_id;"""
    return text(sql)


def get_sales_invoice_govtskg_by_id():
    """Get header-level govt SKG data for a sales invoice."""
    sql = """SELECT
        sg.sale_invoice_govtskg_id,
        sg.invoice_id,
        sg.pcso_no,
        sg.pcso_date,
        sg.administrative_office_address,
        sg.destination_rail_head,
        sg.loading_point,
        sg.mode_of_transport,
        sg.pack_sheet,
        sg.net_weight,
        sg.total_weight
    FROM sales_invoice_govtskg AS sg
    WHERE sg.invoice_id = :invoice_id;"""
    return text(sql)


# =============================================================================
# GOVT SKG INVOICE DETAIL EXTENSION QUERIES
# =============================================================================

def insert_sale_invoice_govtskg_dtl():
    """Insert per-line-item govt SKG detail data."""
    sql = """INSERT INTO sale_invoice_govtskg_dtl (
        invoice_line_item_id,
        pack_sheet, net_weight, total_weight,
        updated_by, updated_date_time
    ) VALUES (
        :invoice_line_item_id,
        :pack_sheet, :net_weight, :total_weight,
        :updated_by, NOW()
    );"""
    return text(sql)


def delete_sale_invoice_govtskg_dtl():
    """Delete per-line-item govt SKG detail rows for an invoice."""
    sql = """DELETE FROM sale_invoice_govtskg_dtl
    WHERE invoice_line_item_id IN (
        SELECT invoice_line_item_id FROM sales_invoice_dtl
        WHERE invoice_id = :invoice_id
    );"""
    return text(sql)


def get_sale_invoice_govtskg_dtl_by_invoice_id():
    """Get all per-line-item govt SKG detail rows for an invoice."""
    sql = """SELECT
        gd.sale_invoice_govtskg_dtl_id,
        gd.invoice_line_item_id,
        gd.pack_sheet,
        gd.net_weight,
        gd.total_weight
    FROM sale_invoice_govtskg_dtl AS gd
    WHERE gd.invoice_line_item_id IN (
        SELECT invoice_line_item_id FROM sales_invoice_dtl
        WHERE invoice_id = :invoice_id
    );"""
    return text(sql)


# =============================================================================
# SALES ORDER JUTE EXTENSION QUERIES
# =============================================================================

def insert_sales_order_jute():
    sql = """INSERT INTO sales_order_jute (
        sales_order_id, mr_no, mr_id, claim_amount, other_reference,
        unit_conversion, claim_description, mukam_id, updated_by, updated_date_time
    ) VALUES (
        :sales_order_id, :mr_no, :mr_id, :claim_amount, :other_reference,
        :unit_conversion, :claim_description, :mukam_id, :updated_by, :updated_date_time
    );"""
    return text(sql)


def delete_sales_order_jute():
    sql = """DELETE FROM sales_order_jute WHERE sales_order_id = :sales_order_id;"""
    return text(sql)


def get_sales_order_jute_by_id():
    sql = """SELECT soj.*, jm.mukam_name
    FROM sales_order_jute soj
    LEFT JOIN jute_mukam_mst jm ON jm.mukam_id = soj.mukam_id
    WHERE soj.sales_order_id = :sales_order_id;"""
    return text(sql)


def insert_sales_order_jute_dtl():
    sql = """INSERT INTO sales_order_jute_dtl (
        sales_order_dtl_id, claim_amount_dtl, claim_desc, claim_rate,
        unit_conversion, qty_untit_conversion, updated_by, updated_date_time
    ) VALUES (
        :sales_order_dtl_id, :claim_amount_dtl, :claim_desc, :claim_rate,
        :unit_conversion, :qty_untit_conversion, :updated_by, :updated_date_time
    );"""
    return text(sql)


def delete_sales_order_jute_dtl():
    sql = """DELETE sojd FROM sales_order_jute_dtl sojd
    INNER JOIN sales_order_dtl sod ON sod.sales_order_dtl_id = sojd.sales_order_dtl_id
    WHERE sod.sales_order_id = :sales_order_id;"""
    return text(sql)


def get_sales_order_jute_dtl_by_order_id():
    sql = """SELECT sojd.*
    FROM sales_order_jute_dtl sojd
    INNER JOIN sales_order_dtl sod ON sod.sales_order_dtl_id = sojd.sales_order_dtl_id
    WHERE sod.sales_order_id = :sales_order_id AND sod.active = 1;"""
    return text(sql)


# =============================================================================
# SALES ORDER JUTE YARN EXTENSION QUERIES
# =============================================================================

def insert_sales_order_juteyarn():
    sql = """INSERT INTO sales_order_juteyarn (
        sales_order_id, pcso_no, container_no, customer_ref_no,
        updated_by, updated_date_time
    ) VALUES (
        :sales_order_id, :pcso_no, :container_no, :customer_ref_no,
        :updated_by, :updated_date_time
    );"""
    return text(sql)


def delete_sales_order_juteyarn():
    sql = """DELETE FROM sales_order_juteyarn WHERE sales_order_id = :sales_order_id;"""
    return text(sql)


def get_sales_order_juteyarn_by_id():
    sql = """SELECT * FROM sales_order_juteyarn WHERE sales_order_id = :sales_order_id;"""
    return text(sql)


# =============================================================================
# SALES ORDER GOVT SKG EXTENSION QUERIES
# =============================================================================

def insert_sales_order_govtskg():
    sql = """INSERT INTO sales_order_govtskg (
        sales_order_id, pcso_no, pcso_date, administrative_office_address,
        destination_rail_head, loading_point, mode_of_transport, updated_by, updated_date_time
    ) VALUES (
        :sales_order_id, :pcso_no, :pcso_date, :administrative_office_address,
        :destination_rail_head, :loading_point, :mode_of_transport, :updated_by, :updated_date_time
    );"""
    return text(sql)


def delete_sales_order_govtskg():
    sql = """DELETE FROM sales_order_govtskg WHERE sales_order_id = :sales_order_id;"""
    return text(sql)


def get_sales_order_govtskg_by_id():
    sql = """SELECT * FROM sales_order_govtskg WHERE sales_order_id = :sales_order_id;"""
    return text(sql)


def insert_sales_order_govtskg_dtl():
    sql = """INSERT INTO sales_order_govtskg_dtl (
        sales_order_dtl_id, pack_sheet, net_weight, total_weight,
        updated_by, updated_date_time
    ) VALUES (
        :sales_order_dtl_id, :pack_sheet, :net_weight, :total_weight,
        :updated_by, :updated_date_time
    );"""
    return text(sql)


def delete_sales_order_govtskg_dtl():
    sql = """DELETE sogd FROM sales_order_govtskg_dtl sogd
    INNER JOIN sales_order_dtl sod ON sod.sales_order_dtl_id = sogd.sales_order_dtl_id
    WHERE sod.sales_order_id = :sales_order_id;"""
    return text(sql)


def get_sales_order_govtskg_dtl_by_order_id():
    sql = """SELECT sogd.*
    FROM sales_order_govtskg_dtl sogd
    INNER JOIN sales_order_dtl sod ON sod.sales_order_dtl_id = sogd.sales_order_dtl_id
    WHERE sod.sales_order_id = :sales_order_id AND sod.active = 1;"""
    return text(sql)


# =============================================================================
# GOVT SKG TRANSPORT CHARGE RATE QUERIES
# =============================================================================


def get_govtskg_transport_charge_rates():
    """Fetch active transport charge rates for a company. Returns mode, charge_id, and rate.

    Scoped by :co_id so one company never sees another company's rates (rows with
    co_id IS NULL are treated as shared/global defaults).
    """
    sql = """SELECT id, mode_of_transport, additional_charges_id, rate_per_100pcs, co_id
    FROM govtskg_transport_charge_rate
    WHERE active = 1
        AND (:co_id IS NULL OR co_id = :co_id OR co_id IS NULL)
    ORDER BY mode_of_transport, additional_charges_id;"""
    return text(sql)


def get_govtskg_transport_modes():
    """Fetch distinct active transport modes."""
    sql = """SELECT DISTINCT mode_of_transport
    FROM govtskg_transport_charge_rate
    WHERE active = 1
    ORDER BY mode_of_transport;"""
    return text(sql)


# =============================================================================
# SALES ORDER ADDITIONAL CHARGES QUERIES
# =============================================================================

def get_additional_charges_dropdown():
    sql = """SELECT additional_charges_id, additional_charges_name, default_value
    FROM additional_charges_mst
    ORDER BY additional_charges_name;"""
    return text(sql)


def insert_sales_order_additional():
    sql = """INSERT INTO sales_order_additional (
        sales_order_id, additional_charges_id, qty, rate, net_amount,
        remarks, updated_by, updated_date_time
    ) VALUES (
        :sales_order_id, :additional_charges_id, :qty, :rate, :net_amount,
        :remarks, :updated_by, :updated_date_time
    );"""
    return text(sql)


def insert_sales_order_additional_gst():
    sql = """INSERT INTO sales_order_additional_gst (
        sales_order_additional_id,
        igst_amount, igst_percent, cgst_amount, cgst_percent,
        sgst_amount, sgst_percent, gst_total
    ) VALUES (
        :sales_order_additional_id,
        :igst_amount, :igst_percent, :cgst_amount, :cgst_percent,
        :sgst_amount, :sgst_percent, :gst_total
    );"""
    return text(sql)


def delete_sales_order_additional_gst():
    sql = """DELETE soag FROM sales_order_additional_gst soag
    INNER JOIN sales_order_additional soa ON soa.sales_order_additional_id = soag.sales_order_additional_id
    WHERE soa.sales_order_id = :sales_order_id;"""
    return text(sql)


def delete_sales_order_additional():
    sql = """DELETE FROM sales_order_additional WHERE sales_order_id = :sales_order_id;"""
    return text(sql)


def get_sales_order_additional_by_id():
    sql = """SELECT soa.*, acm.additional_charges_name,
        soag.igst_amount, soag.igst_percent, soag.cgst_amount, soag.cgst_percent,
        soag.sgst_amount, soag.sgst_percent, soag.gst_total
    FROM sales_order_additional soa
    LEFT JOIN additional_charges_mst acm ON acm.additional_charges_id = soa.additional_charges_id
    LEFT JOIN sales_order_additional_gst soag ON soag.sales_order_additional_id = soa.sales_order_additional_id
    WHERE soa.sales_order_id = :sales_order_id
    ORDER BY soa.sales_order_additional_id;"""
    return text(sql)


# =============================================================================
# SALES INVOICE ADDITIONAL CHARGES QUERIES
# =============================================================================

def insert_sales_invoice_additional():
    sql = """INSERT INTO sales_invoice_additional (
        invoice_id, additional_charges_id, qty, rate, net_amount,
        remarks, updated_by, updated_date_time
    ) VALUES (
        :invoice_id, :additional_charges_id, :qty, :rate, :net_amount,
        :remarks, :updated_by, :updated_date_time
    );"""
    return text(sql)


def insert_sales_invoice_additional_gst():
    sql = """INSERT INTO sales_invoice_additional_gst (
        sales_invoice_additional_id,
        igst_amount, igst_percent, cgst_amount, cgst_percent,
        sgst_amount, sgst_percent, gst_total
    ) VALUES (
        :sales_invoice_additional_id,
        :igst_amount, :igst_percent, :cgst_amount, :cgst_percent,
        :sgst_amount, :sgst_percent, :gst_total
    );"""
    return text(sql)


def delete_sales_invoice_additional_gst():
    sql = """DELETE siag FROM sales_invoice_additional_gst siag
    INNER JOIN sales_invoice_additional sia ON sia.sales_invoice_additional_id = siag.sales_invoice_additional_id
    WHERE sia.invoice_id = :invoice_id;"""
    return text(sql)


def delete_sales_invoice_additional():
    sql = """DELETE FROM sales_invoice_additional WHERE invoice_id = :invoice_id;"""
    return text(sql)


def get_sales_invoice_additional_by_id():
    sql = """SELECT sia.*, acm.additional_charges_name,
        siag.igst_amount, siag.igst_percent, siag.cgst_amount, siag.cgst_percent,
        siag.sgst_amount, siag.sgst_percent, siag.gst_total
    FROM sales_invoice_additional sia
    LEFT JOIN additional_charges_mst acm ON acm.additional_charges_id = sia.additional_charges_id
    LEFT JOIN sales_invoice_additional_gst siag ON siag.sales_invoice_additional_id = sia.sales_invoice_additional_id
    WHERE sia.invoice_id = :invoice_id
    ORDER BY sia.sales_invoice_additional_id;"""
    return text(sql)


def get_transporter_branches(transporter_id: int):
    """
    Fetch all branches for a transporter party.
    Returns: party_mst_branch_id, gst_no, address, state_id
    """
    sql = """
    SELECT
        pbm.party_mst_branch_id AS id,
        pbm.gst_no,
        pbm.address,
        pbm.state_id,
        pm.supp_name AS party_name
    FROM party_branch_mst pbm
    INNER JOIN party_mst pm ON pm.party_id = pbm.party_id
    WHERE pbm.party_id = :transporter_id
    AND pbm.active = 1
    ORDER BY pbm.party_mst_branch_id ASC
    """
    return text(sql)


def get_e_invoice_submission_history(invoice_id: int):
    """
    Fetch all e-invoice submission attempts for an invoice.
    Returns most recent first.
    """
    sql = """
    SELECT
        e_invoice_response_id AS response_id,
        submission_status,
        submitted_date_time,
        irn_from_response,
        error_message,
        submitted_by
    FROM e_invoice_responses
    WHERE invoice_id = :invoice_id
    ORDER BY submitted_date_time DESC
    """
    return text(sql)


# =============================================================================
# SALES OUTSTANDING / FULFILLMENT VIEW QUERIES
# =============================================================================

def get_sales_order_outstanding():
    """Query vw_sales_order_outstanding with optional filters."""
    sql = """SELECT
        sales_order_dtl_id,
        sales_order_id,
        sales_no,
        sales_order_date,
        branch_id,
        co_id,
        party_id,
        invoice_type,
        status_id,
        item_id,
        item_code,
        item_name,
        uom_id,
        uom_name,
        rate,
        so_qty,
        do_consumed_qty,
        inv_via_do_qty,
        inv_direct_qty,
        invoice_consumed_qty,
        bal_do_qty,
        bal_invoice_qty
    FROM vw_sales_order_outstanding
    WHERE (:co_id IS NULL OR co_id = :co_id)
      AND (:branch_id IS NULL OR branch_id = :branch_id)
      AND (:party_id IS NULL OR party_id = :party_id)
      AND (:item_id IS NULL OR item_id = :item_id)
    ORDER BY sales_order_date DESC, sales_order_dtl_id;"""
    return text(sql)


def get_sales_do_outstanding():
    """Query vw_sales_do_outstanding with optional filters."""
    sql = """SELECT
        sales_delivery_order_dtl_id,
        sales_delivery_order_id,
        delivery_order_no,
        delivery_order_date,
        sales_order_dtl_id,
        sales_order_id,
        branch_id,
        co_id,
        party_id,
        invoice_type,
        status_id,
        item_id,
        item_code,
        item_name,
        uom_id,
        uom_name,
        rate,
        do_qty,
        invoice_consumed_qty,
        bal_do_qty
    FROM vw_sales_do_outstanding
    WHERE (:co_id IS NULL OR co_id = :co_id)
      AND (:branch_id IS NULL OR branch_id = :branch_id)
      AND (:party_id IS NULL OR party_id = :party_id)
      AND (:item_id IS NULL OR item_id = :item_id)
    ORDER BY delivery_order_date DESC, sales_delivery_order_dtl_id;"""
    return text(sql)


def get_sales_fulfillment_summary():
    """Query vw_sales_fulfillment_summary with optional filters."""
    sql = """SELECT
        co_id,
        branch_id,
        party_id,
        item_id,
        uom_id,
        total_so_qty,
        total_do_qty,
        total_invoiced_qty,
        bal_so_to_deliver,
        bal_so_to_invoice
    FROM vw_sales_fulfillment_summary
    WHERE (:co_id IS NULL OR co_id = :co_id)
      AND (:branch_id IS NULL OR branch_id = :branch_id)
      AND (:party_id IS NULL OR party_id = :party_id)
      AND (:item_id IS NULL OR item_id = :item_id)
    ORDER BY co_id, branch_id, party_id, item_id;"""
    return text(sql)


# =============================================================================
# GOVT SKG FREIGHT QUERIES
# =============================================================================

def insert_sales_invoice_freight():
    """Insert a sales_invoice_freight row linking a type-7 freight invoice to its type-3 source."""
    sql = """INSERT INTO sales_invoice_freight (
        invoice_id, source_invoice_id, iw_bill_no, iw_bill_date,
        updated_by, updated_date_time
    ) VALUES (
        :invoice_id, :source_invoice_id, :iw_bill_no, :iw_bill_date,
        :updated_by, :updated_date_time
    );"""
    return text(sql)


def get_sales_invoice_freight_by_invoice_id():
    """Fetch the sales_invoice_freight row for a given invoice_id."""
    sql = """SELECT sales_invoice_freight_id, invoice_id, source_invoice_id,
           iw_bill_no, iw_bill_date, updated_by, updated_date_time
    FROM sales_invoice_freight
    WHERE invoice_id = :invoice_id;"""
    return text(sql)


def delete_sales_invoice_freight():
    """Delete the sales_invoice_freight row for a given invoice_id."""
    sql = """DELETE FROM sales_invoice_freight WHERE invoice_id = :invoice_id;"""
    return text(sql)


def update_sales_invoice_freight():
    """Update the editable IW Bill fields on the sales_invoice_freight row.

    source_invoice_id is intentionally NOT updateable — once a freight invoice
    is bound to a source, that link is immutable for audit/IRN integrity.
    """
    sql = """UPDATE sales_invoice_freight
    SET iw_bill_no = :iw_bill_no,
        iw_bill_date = :iw_bill_date,
        updated_by = :updated_by,
        updated_date_time = :updated_date_time
    WHERE invoice_id = :invoice_id;"""
    return text(sql)


def insert_sales_invoice_freight_source():
    """Insert one junction row linking a freight invoice to one of its source invoices.

    A freight invoice can reference multiple Govt Sacking source invoices; this
    junction stores every source plus the per-source bales_qty (read off the
    source's first line at create time, kept for audit/breakdown).
    """
    sql = """INSERT INTO sales_invoice_freight_source (
        sales_invoice_freight_id, source_invoice_id, bales_qty, created_date_time
    ) VALUES (
        :sales_invoice_freight_id, :source_invoice_id, :bales_qty, :created_date_time
    );"""
    return text(sql)


def get_sales_invoice_freight_sources_by_freight_id():
    """Fetch every source linked to a freight invoice, enriched with source header
    + delivery_order_no for the printable preview footer."""
    sql = """SELECT
        sifs.sales_invoice_freight_source_id,
        sifs.sales_invoice_freight_id,
        sifs.source_invoice_id,
        sifs.bales_qty AS source_bales_qty,
        si.invoice_no            AS source_invoice_no,
        si.invoice_date          AS source_invoice_date,
        bm.co_id                 AS source_co_id,
        bm.branch_prefix         AS source_branch_prefix,
        cm.co_prefix             AS source_co_prefix,
        sg.pcso_no               AS source_pcso_no,
        sg.pcso_date             AS source_pcso_date,
        si.sales_delivery_order_id AS source_sales_delivery_order_id,
        sdo.delivery_order_no    AS source_delivery_order_no,
        sdo.delivery_order_date  AS source_delivery_order_date,
        pm.supp_name             AS source_party_name
    FROM sales_invoice_freight_source sifs
    JOIN sales_invoice si             ON si.invoice_id = sifs.source_invoice_id
    LEFT JOIN branch_mst bm           ON bm.branch_id = si.branch_id
    LEFT JOIN co_mst cm               ON cm.co_id = bm.co_id
    LEFT JOIN sales_invoice_govtskg sg ON sg.invoice_id = si.invoice_id
    LEFT JOIN party_mst pm            ON pm.party_id = si.party_id
    LEFT JOIN sales_delivery_order sdo ON sdo.sales_delivery_order_id = si.sales_delivery_order_id
    WHERE sifs.sales_invoice_freight_id = :sales_invoice_freight_id
    ORDER BY sifs.sales_invoice_freight_source_id;"""
    return text(sql)


def get_sales_invoice_freight_source_ids():
    """Return ordered list of source_invoice_id values for a given freight invoice
    (used by the type-7 update branch to enforce immutability of the source set)."""
    sql = """SELECT sifs.source_invoice_id
    FROM sales_invoice_freight sif
    JOIN sales_invoice_freight_source sifs
        ON sifs.sales_invoice_freight_id = sif.sales_invoice_freight_id
    WHERE sif.invoice_id = :invoice_id
    ORDER BY sifs.sales_invoice_freight_source_id;"""
    return text(sql)


def get_govt_sacking_source_list():
    """List finalized Govt Sacking (type-3) invoices as the freight-invoice source picker."""
    sql = """SELECT
        si.invoice_id,
        si.invoice_no,
        si.invoice_date,
        si.party_id,
        pm.supp_name AS party_name,
        si.sales_order_id,
        so.sales_no AS sales_order_no,
        si.sales_delivery_order_id,
        sdo.delivery_order_no,
        sg.pcso_no,
        si.status_id
    FROM sales_invoice AS si
    LEFT JOIN branch_mst AS bm ON bm.branch_id = si.branch_id
    LEFT JOIN party_mst AS pm ON pm.party_id = si.party_id
    LEFT JOIN sales_order AS so ON so.sales_order_id = si.sales_order_id
    LEFT JOIN sales_delivery_order AS sdo ON sdo.sales_delivery_order_id = si.sales_delivery_order_id
    LEFT JOIN sales_invoice_govtskg AS sg ON sg.invoice_id = si.invoice_id
    WHERE si.invoice_type = 3
        AND si.active = 1
        AND si.status_id IN (1, 3)
        AND (:co_id IS NULL OR bm.co_id = :co_id)
        AND (:branch_id IS NULL OR si.branch_id = :branch_id)
        AND (
            :search_like IS NULL
            OR CAST(si.invoice_no AS CHAR) LIKE :search_like
            OR pm.supp_name LIKE :search_like
        )
    ORDER BY si.invoice_date DESC, si.invoice_id DESC
    LIMIT :limit OFFSET :offset;"""
    return text(sql)


def get_govt_sacking_source_list_count():
    """Count of finalized Govt Sacking (type-3) invoices matching the picker filters."""
    sql = """SELECT COUNT(1) AS total
    FROM sales_invoice AS si
    LEFT JOIN branch_mst AS bm ON bm.branch_id = si.branch_id
    LEFT JOIN party_mst AS pm ON pm.party_id = si.party_id
    WHERE si.invoice_type = 3
        AND si.active = 1
        AND si.status_id IN (1, 3)
        AND (:co_id IS NULL OR bm.co_id = :co_id)
        AND (:branch_id IS NULL OR si.branch_id = :branch_id)
        AND (
            :search_like IS NULL
            OR CAST(si.invoice_no AS CHAR) LIKE :search_like
            OR pm.supp_name LIKE :search_like
        );"""
    return text(sql)


def get_govt_sacking_source_by_id():
    """Fetch header + govtskg columns for a type-3 source invoice used to pre-fill a freight invoice.

    Requires :co_id for cross-company tenancy enforcement. Pass :co_id = None only from
    trusted contexts (e.g. derived from the same-row branch after validation).
    """
    sql = """SELECT
        si.invoice_id,
        si.invoice_no,
        si.invoice_date,
        si.invoice_type,
        si.party_id,
        pm.supp_name AS party_name,
        si.billing_to_id,
        pbill.address            AS billing_address,
        pbill.address_additional AS billing_address_additional,
        pbill.zip_code           AS billing_zip_code,
        pbill.gst_no             AS billing_gst_no,
        sbill.state              AS billing_state_name,
        si.shipping_to_id,
        pship.address            AS shipping_address,
        pship.address_additional AS shipping_address_additional,
        pship.zip_code           AS shipping_zip_code,
        pship.gst_no             AS shipping_gst_no,
        sship.state              AS shipping_state_name,
        si.billing_state_code,
        si.shipping_state_code,
        si.intra_inter_state,
        si.branch_id,
        sbm.state_code AS branch_state_code,
        bm.co_id AS co_id,
        bm.branch_prefix,
        cm.co_prefix,
        si.sales_order_id,
        so.sales_no AS sales_order_no,
        so.sales_order_date,
        si.sales_delivery_order_id,
        sdo.delivery_order_no,
        sdo.delivery_order_date,
        si.transporter_id,
        si.transporter_name,
        si.transporter_address,
        si.transporter_state_code,
        si.transporter_state_name,
        si.transporter_branch_id,
        pbm_transporter.gst_no   AS transporter_gst_no,
        si.transporter_doc_no,
        si.transporter_doc_date,
        si.buyer_order_no,
        si.buyer_order_date,
        si.vehicle_no,
        si.container_no,
        si.eway_bill_no,
        si.eway_bill_date,
        sg.pcso_no,
        sg.pcso_date,
        sg.administrative_office_address,
        sg.destination_rail_head,
        sg.loading_point,
        sg.mode_of_transport
    FROM sales_invoice AS si
    LEFT JOIN party_mst AS pm ON pm.party_id = si.party_id
    LEFT JOIN sales_order AS so ON so.sales_order_id = si.sales_order_id
    LEFT JOIN sales_delivery_order AS sdo ON sdo.sales_delivery_order_id = si.sales_delivery_order_id
    LEFT JOIN sales_invoice_govtskg AS sg ON sg.invoice_id = si.invoice_id
    LEFT JOIN branch_mst AS bm ON bm.branch_id = si.branch_id
    LEFT JOIN state_mst AS sbm ON sbm.state_id = bm.state_id
    LEFT JOIN co_mst AS cm ON cm.co_id = bm.co_id
    LEFT JOIN party_branch_mst AS pbill ON pbill.party_mst_branch_id = si.billing_to_id
    LEFT JOIN state_mst AS sbill ON sbill.state_id = pbill.state_id
    LEFT JOIN party_branch_mst AS pship ON pship.party_mst_branch_id = si.shipping_to_id
    LEFT JOIN state_mst AS sship ON sship.state_id = pship.state_id
    LEFT JOIN party_branch_mst AS pbm_transporter ON pbm_transporter.party_mst_branch_id = si.transporter_branch_id
    WHERE si.invoice_id = :invoice_id
        AND si.invoice_type = 3
        AND si.active = 1
        AND (:co_id IS NULL OR bm.co_id = :co_id);"""
    return text(sql)


def get_govt_sacking_source_lines():
    """Fetch line items (with govtskg dtl) for a type-3 source invoice."""
    sql = """SELECT
        ili.invoice_line_item_id,
        ili.invoice_id,
        ili.item_id,
        im.item_name,
        ili.hsn_code,
        ili.quantity,
        ili.uom_id,
        um.uom_name,
        ili.rate,
        ili.amount_without_tax,
        ili.total_amount,
        ili.remarks,
        gd.pack_sheet,
        gd.net_weight,
        gd.total_weight
    FROM sales_invoice_dtl AS ili
    LEFT JOIN item_mst AS im ON im.item_id = ili.item_id
    LEFT JOIN uom_mst AS um ON um.uom_id = ili.uom_id
    LEFT JOIN sale_invoice_govtskg_dtl AS gd ON gd.invoice_line_item_id = ili.invoice_line_item_id
    WHERE ili.invoice_id = :invoice_id
    ORDER BY ili.invoice_line_item_id;"""
    return text(sql)


def find_or_create_freight_item(db, co_id: int, user_id: int):
    """Find-or-create the 'Freight' item group and 'Freight Charges' item for a co_id; return (item_id, item_grp_id).

    Guards against the check-then-insert race: two concurrent first-use requests for the
    same co_id would both pass the `if not grp` guard. On IntegrityError at flush time we
    rollback-partial and re-fetch the winner's row.
    """
    from src.masters.models import ItemGrpMst, ItemMst
    from src.common.utils import now_ist
    from sqlalchemy.exc import IntegrityError

    # 1. Find or create item group "Freight" for this co_id
    grp = db.query(ItemGrpMst).filter(
        ItemGrpMst.co_id == co_id,
        ItemGrpMst.item_grp_name == "Freight",
    ).first()
    if not grp:
        grp = ItemGrpMst(
            co_id=co_id,
            item_grp_name="Freight",
            item_grp_code="FREIGHT",
            item_type_id=1,
            parent_grp_id=None,
            active=1,
            updated_by=user_id,
            updated_date_time=now_ist(),
        )
        db.add(grp)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            grp = db.query(ItemGrpMst).filter(
                ItemGrpMst.co_id == co_id,
                ItemGrpMst.item_grp_name == "Freight",
            ).first()
            if not grp:
                raise

    # 2. Find item "Freight Charges" scoped to any item_grp of this co
    group_ids = [g.item_grp_id for g in db.query(ItemGrpMst).filter(ItemGrpMst.co_id == co_id).all()]
    item = None
    if group_ids:
        item = db.query(ItemMst).filter(
            ItemMst.item_grp_id.in_(group_ids),
            ItemMst.item_name == "Freight Charges",
        ).first()
    if not item:
        item = ItemMst(
            item_grp_id=grp.item_grp_id,
            item_code="FREIGHT-CHARGES",
            item_name="Freight Charges",
            hsn_code="996519",
            tax_percentage=18.0,
            tangible=False,
            uom_id=191,
            saleable=True,
            consumable=False,
            purchaseable=False,
            manufacturable=False,
            assembly=False,
            active=1,
            updated_by=user_id,
            updated_date_time=now_ist(),
        )
        db.add(item)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            item = db.query(ItemMst).filter(
                ItemMst.item_grp_id.in_(group_ids + [grp.item_grp_id]),
                ItemMst.item_name == "Freight Charges",
            ).first()
            if not item:
                raise

    return item.item_id, grp.item_grp_id
