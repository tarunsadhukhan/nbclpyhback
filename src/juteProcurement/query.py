from sqlalchemy.sql import text

from src.juteProcurement.formatters import (
    get_jute_po_number_sql_expression,
    get_jute_gate_entry_number_sql_expression,
    get_jute_mr_number_sql_expression,
    get_jute_bill_pass_number_sql_expression,
)


def _group_path_cte():
    """
    Returns a recursive CTE that builds full hierarchical group paths.
    Creates a temp table `full_group_paths` with columns: item_grp_id, item_grp_name_path.
    Usage: prepend to any query, then JOIN full_group_paths fgp ON fgp.item_grp_id = ...
    and use COALESCE(fgp.item_grp_name_path, ig.item_grp_name) AS jute_group_name.
    """
    return """
        WITH RECURSIVE group_path AS (
            SELECT
                igm.item_grp_id AS target_id,
                igm.item_grp_id,
                igm.item_grp_name,
                igm.parent_grp_id,
                CAST(igm.item_grp_name AS CHAR(500)) AS item_grp_name_path
            FROM item_grp_mst igm

            UNION ALL

            SELECT
                child.target_id,
                p.item_grp_id,
                p.item_grp_name,
                p.parent_grp_id,
                CAST(CONCAT(p.item_grp_name, ' > ', child.item_grp_name_path) AS CHAR(500))
            FROM item_grp_mst p
            JOIN group_path child ON child.parent_grp_id = p.item_grp_id
        ),
        full_group_paths AS (
            SELECT target_id AS item_grp_id, item_grp_name_path
            FROM group_path
            WHERE parent_grp_id IS NULL
        )
    """


def get_jute_po_table_query(co_id: int, search: str = None):
    """
    Query to get jute PO list with pagination support.
    Joins with branch_mst for co_id filtering, co_mst for company prefix,
    jute_supplier_mst for supplier name, jute_supp_party_map + party_mst for party details,
    jute_mukam_mst for mukam name, and status_mst for status name.

    PO number format: {co_prefix}/{branch_prefix}/JPO/{year}/{sequence:05d}
    Optional :date_from / :date_to bind params bound jp.po_date.
    """
    # Get the formatted PO number SQL expression
    po_num_expr = get_jute_po_number_sql_expression()

    search_clause = ""
    if search:
        # Match against the formatted PO number (e.g. LCPL/JPO/26-27/00006) too,
        # not just the raw sequence integer — that's what users see and paste.
        search_clause = f"""
            AND (
                CAST(jp.po_no AS CHAR) LIKE :search
                OR {po_num_expr} LIKE :search
                OR jsm.supplier_name LIKE :search
                OR pm.supp_name LIKE :search
                OR jmm.mukam_name LIKE :search
            )
        """

    date_clause = """
            AND (:date_from IS NULL OR jp.po_date >= :date_from)
            AND (:date_to IS NULL OR jp.po_date <= :date_to)
    """

    # Status filter — :status_id always bound (None = all statuses). Mirrors the
    # sales-invoice list pattern. Jute POs always carry a status_id (create sets
    # 21/Draft), so no NULL-status branch is needed.
    status_clause = """
            AND (:status_id IS NULL OR jp.status_id = :status_id)
    """

    sql = f"""
        SELECT
            jp.jute_po_id,
            jp.po_no,
            {po_num_expr} AS po_num,
            jp.po_date,
            jp.party_id,
            pm.supp_name AS party_name,
            jp.supplier_id,
            jsm.supplier_name,
            jp.jute_mukam_id AS mukam_id,
            jmm.mukam_name AS mukam,
            jp.vehicle_type_id,
            jlm.lorry_type AS vehicle_type,
            jp.vehicle_quantity AS vehicle_qty,
            jp.status_id,
            COALESCE(sm.status_name, jp.status_id) AS status,
            jp.jute_po_value AS po_val_wt_tax,
            jp.jute_po_value AS po_val_wo_tax,
            jp.weight,
            jp.jute_uom AS jute_unit,
            jp.branch_id,
            jp.updated_date_time,
            jp.updated_by AS created_by,
            -- Lorries/qty received against this PO come from jute_mr gate entries
            -- (jute_gate_entry_no IS NOT NULL mirrors the gate-entry list query).
            -- Scalar correlated subqueries => one row per PO, so pagination/count stay intact.
            (
                SELECT COUNT(*) FROM jute_mr jm
                WHERE jm.po_id = jp.jute_po_id AND jm.jute_gate_entry_no IS NOT NULL
            ) AS received_lorries,
            GREATEST(
                COALESCE(jp.vehicle_quantity, 0) - (
                    SELECT COUNT(*) FROM jute_mr jm
                    WHERE jm.po_id = jp.jute_po_id AND jm.jute_gate_entry_no IS NOT NULL
                ), 0
            ) AS pending_lorries,
            -- net_weight stored in kg; 1 quintal = 100 kg
            ROUND((
                SELECT COALESCE(SUM(jm.net_weight), 0) FROM jute_mr jm
                WHERE jm.po_id = jp.jute_po_id AND jm.jute_gate_entry_no IS NOT NULL
            ) / 100.0, 3) AS received_qty_qtl,
            ROUND(GREATEST(
                COALESCE(jp.weight, 0) - (
                    SELECT COALESCE(SUM(jm.net_weight), 0) FROM jute_mr jm
                    WHERE jm.po_id = jp.jute_po_id AND jm.jute_gate_entry_no IS NOT NULL
                ), 0
            ) / 100.0, 3) AS pending_qty_qtl
        FROM jute_po jp
        INNER JOIN branch_mst bm ON bm.branch_id = jp.branch_id
        INNER JOIN co_mst cm ON cm.co_id = bm.co_id
        LEFT JOIN jute_lorry_mst jlm ON jlm.jute_lorry_type_id = jp.vehicle_type_id
        LEFT JOIN jute_supplier_mst jsm ON jsm.supplier_id = jp.supplier_id
        LEFT JOIN party_mst pm ON pm.party_id = jp.party_id
        LEFT JOIN jute_mukam_mst jmm ON jmm.mukam_id = jp.jute_mukam_id
        LEFT JOIN status_mst sm ON sm.status_id = jp.status_id
        WHERE bm.co_id = :co_id
        {search_clause}
        {date_clause}
        {status_clause}
        ORDER BY jp.po_date DESC, jp.jute_po_id DESC
        LIMIT :limit OFFSET :offset
    """
    return text(sql)


def get_jute_po_table_count_query(co_id: int, search: str = None):
    """
    Query to get total count of jute POs for pagination.
    Uses branch_mst to filter by co_id since jute_po doesn't have co_id column.
    Optional :date_from / :date_to bind params bound jp.po_date.
    """
    # Formatted PO number expression — kept in sync with the data query so search
    # matches the same displayed value (e.g. LCPL/JPO/26-27/00006).
    po_num_expr = get_jute_po_number_sql_expression()

    search_clause = ""
    if search:
        search_clause = f"""
            AND (
                CAST(jp.po_no AS CHAR) LIKE :search
                OR {po_num_expr} LIKE :search
                OR jsm.supplier_name LIKE :search
                OR pm.supp_name LIKE :search
                OR jmm.mukam_name LIKE :search
            )
        """

    date_clause = """
            AND (:date_from IS NULL OR jp.po_date >= :date_from)
            AND (:date_to IS NULL OR jp.po_date <= :date_to)
    """

    # Status filter — kept in sync with the data query so pagination totals match.
    status_clause = """
            AND (:status_id IS NULL OR jp.status_id = :status_id)
    """

    sql = f"""
        SELECT COUNT(DISTINCT jp.jute_po_id) AS total
        FROM jute_po jp
        INNER JOIN branch_mst bm ON bm.branch_id = jp.branch_id
        INNER JOIN co_mst cm ON cm.co_id = bm.co_id
        LEFT JOIN jute_supplier_mst jsm ON jsm.supplier_id = jp.supplier_id
        LEFT JOIN (
            SELECT jspm1.jute_supplier_id, jspm1.party_id
            FROM jute_supp_party_map jspm1
            INNER JOIN (
                SELECT jute_supplier_id, MAX(updated_date_time) as max_date
                FROM jute_supp_party_map
                GROUP BY jute_supplier_id
            ) jspm2 ON jspm1.jute_supplier_id = jspm2.jute_supplier_id
                   AND jspm1.updated_date_time = jspm2.max_date
        ) jspm_latest ON jspm_latest.jute_supplier_id = jp.supplier_id
        LEFT JOIN party_mst pm ON pm.party_id = jspm_latest.party_id
        LEFT JOIN jute_mukam_mst jmm ON jmm.mukam_id = jp.jute_mukam_id
        WHERE bm.co_id = :co_id
        {search_clause}
        {date_clause}
        {status_clause}
    """
    return text(sql)


def get_jute_po_by_id_query():
    """
    Query to get a single jute PO by ID.
    Uses branch_mst to filter by co_id since jute_po doesn't have co_id column.
    Includes formatted PO number with company and branch prefix.
    """
    po_num_expr = get_jute_po_number_sql_expression()
    
    sql = f"""
        SELECT 
            jp.jute_po_id,
            jp.po_no,
            {po_num_expr} AS po_num,
            jp.po_date,
            jp.party_id,
            pm.party_id,
            pm.supp_name AS supplier_name,
            jp.supplier_id,
            jsm.supplier_name AS broker_name,
            jp.jute_mukam_id AS mukam_id,
            jmm.mukam_name AS mukam,
            jp.vehicle_type_id,
            jlm.weight AS vehicle_capacity,
            jp.vehicle_quantity AS vehicle_qty,
            jp.status_id,
            COALESCE(sm.status_name, jp.status_id) AS status,
            jp.jute_po_value AS po_val_wt_tax,
            jp.jute_po_value AS po_val_wo_tax,
            jp.weight,
            jp.jute_uom AS jute_unit,
            jp.branch_id,
            jp.credit_term,
            jp.delivery_days AS delivery_timeline,
            jp.footer_note,
            jp.frieght_charge,
            jp.jute_indent_id AS indent_no,
            jp.remarks,
            jp.channel_code,
            jp.contract_no,
            jp.contract_date,
            jp.brokrage_rate,
            jp.brokrage_percentage,
            jp.penalty,
            jp.internal_note,
            jp.updated_date_time,
            cm.co_name,
            cm.co_logo
        FROM jute_po jp
        INNER JOIN branch_mst bm ON bm.branch_id = jp.branch_id
        INNER JOIN co_mst cm ON cm.co_id = bm.co_id
        LEFT JOIN jute_lorry_mst jlm ON jlm.jute_lorry_type_id = jp.vehicle_type_id
        LEFT JOIN jute_supplier_mst jsm ON jsm.supplier_id = jp.supplier_id
        LEFT JOIN party_mst pm ON pm.party_id = jp.party_id
        LEFT JOIN jute_mukam_mst jmm ON jmm.mukam_id = jp.jute_mukam_id
        LEFT JOIN status_mst sm ON sm.status_id = jp.status_id
        WHERE jp.jute_po_id = :jute_po_id AND bm.co_id = :co_id
    """
    return text(sql)


def get_jute_po_line_items_query():
    """
    Query to get line items for a jute PO.
    Uses item_grp_id for jute group and item_id for item (was quality).
    Uses recursive CTE for full group path names.
    """
    sql = _group_path_cte() + """
        SELECT 
            jpli.jute_po_li_id,
            jpli.jute_po_id,
            im.item_grp_id,
            COALESCE(fgp.item_grp_name_path, ig.item_grp_name) AS jute_group_name,
            jpli.item_id,
            im.item_name AS quality_name,
            jpli.crop_year,
            jpli.marka,
            jpli.quantity,
            jpli.percentage,
            jpli.rate,
            jpli.allowable_moisture,
            jpli.value AS amount,
            jpli.jute_uom,
            jpli.active,
            jpli.status_id,
            sm.status_name AS status
        FROM jute_po_li jpli
        LEFT JOIN item_mst im ON im.item_id = jpli.item_id
        LEFT JOIN item_grp_mst ig ON ig.item_grp_id = im.item_grp_id
        LEFT JOIN full_group_paths fgp ON fgp.item_grp_id = im.item_grp_id
        LEFT JOIN status_mst sm ON sm.status_id = jpli.status_id
        WHERE jpli.jute_po_id = :jute_po_id
        ORDER BY jpli.jute_po_li_id
    """
    return text(sql)


def get_mukam_list_query():
    """
    Query to get list of mukams.
    """
    sql = """
        SELECT 
            mukam_id,
            mukam_name
        FROM jute_mukam_mst
        ORDER BY mukam_name
    """
    return text(sql)


def get_vehicle_types_query():
    """
    Query to get list of vehicle/lorry types with weight capacity.
    """
    sql = """
        SELECT 
            jute_lorry_type_id AS vehicle_type_id,
            lorry_type AS vehicle_type,
            weight AS capacity_weight
        FROM jute_lorry_mst
        WHERE co_id = :co_id OR co_id IS NULL
        ORDER BY lorry_type
    """
    return text(sql)


def get_jute_groups_query():
    """
    Query to get jute subgroups (item groups whose parent is the top-level 'Jute' group).
    Returns subgroups from item_grp_mst where parent_grp_id points to a Jute parent group
    (identified by item_type_id = 2).
    Uses a recursive CTE to build the full group path (e.g. "Jute > Raw Jute").
    """
    sql = """
        WITH RECURSIVE group_path AS (
            -- Anchor: start from the jute subgroups themselves
            SELECT
                ig.item_grp_id AS target_id,
                ig.item_grp_id,
                ig.item_grp_code,
                ig.item_grp_name,
                ig.parent_grp_id,
                CAST(ig.item_grp_code AS CHAR(500)) AS item_grp_code_path,
                CAST(ig.item_grp_name AS CHAR(500)) AS item_grp_name_path
            FROM item_grp_mst ig
            INNER JOIN item_grp_mst parent ON parent.item_grp_id = ig.parent_grp_id
            WHERE parent.item_type_id = 2
              AND ig.co_id = :co_id
              AND (ig.active = '1' OR ig.active IS NULL)

            UNION ALL

            -- Walk up to parent, prepend parent name/code
            SELECT
                child.target_id,
                p.item_grp_id,
                p.item_grp_code,
                p.item_grp_name,
                p.parent_grp_id,
                CAST(CONCAT(p.item_grp_code, ' > ', child.item_grp_code_path) AS CHAR(500)),
                CAST(CONCAT(p.item_grp_name, ' > ', child.item_grp_name_path) AS CHAR(500))
            FROM item_grp_mst p
            JOIN group_path child ON child.parent_grp_id = p.item_grp_id
        )
        SELECT
            gp.target_id AS item_grp_id,
            gp.item_grp_code_path AS item_grp_code,
            gp.item_grp_name_path AS item_grp_name
        FROM group_path gp
        WHERE gp.parent_grp_id IS NULL
        ORDER BY gp.item_grp_name_path
    """
    return text(sql)


# Keep old name as alias for backward compatibility
def get_jute_items_query():
    """DEPRECATED: Use get_jute_groups_query() instead."""
    return get_jute_groups_query()


def get_items_by_jute_group_query():
    """
    Query to get items (formerly qualities) belonging to a specific jute subgroup.
    Items are now stored in item_mst with item_grp_id pointing to the subgroup.
    Returns item_id (quality IS an item; quality_id naming retired) and item_name as quality_name.
    """
    sql = """
        SELECT
            im.item_id,
            im.item_name AS quality_name,
            im.item_grp_id
        FROM item_mst im
        WHERE im.item_grp_id = :item_grp_id
        AND (im.active = 1 OR im.active IS NULL)
        ORDER BY im.item_name
    """
    return text(sql)


# Keep old name as alias for backward compatibility
def get_jute_qualities_by_item_query():
    """DEPRECATED: Use get_items_by_jute_group_query() instead."""
    return get_items_by_jute_group_query()


def get_suppliers_by_mukam_query():
    """
    Query to get jute suppliers filtered by mukam.
    """
    sql = """
        SELECT 
            jsm.supplier_id,
            jsm.supplier_name AS supplier_name
        FROM jute_supplier_mst jsm
        ORDER BY jsm.supplier_name
    """
    return text(sql)


def get_parties_by_supplier_query():
    """
    Query to get parties mapped to a jute supplier for a specific company.

    The supplier↔party relationship is per-company via jute_supp_party_map.co_id,
    so we MUST filter by co_id — the same supplier can be mapped to different
    parties in different companies, and not filtering would leak parties from
    other tenants/companies into the dropdown.
    """
    sql = """
        SELECT
            pm.party_id,
            pm.supp_name AS party_name
        FROM party_mst pm
        JOIN jute_supp_party_map jspm
            ON jspm.party_id = pm.party_id
        WHERE jspm.jute_supplier_id = :supplier_id
          AND jspm.co_id = :co_id
        ORDER BY pm.supp_name
    """
    return text(sql)


def get_all_suppliers_query():
    """
    Query to get jute suppliers available for a specific company.

    jute_supplier_mst itself has no co_id (suppliers are tenant-global),
    so company scoping is enforced by requiring at least one party mapping
    for this supplier in jute_supp_party_map for the given co_id. This
    prevents listing suppliers that aren't usable in the current company.
    """
    sql = """
        SELECT
            jsm.supplier_id AS supplier_id,
            jsm.supplier_name AS supplier_name
        FROM jute_supplier_mst jsm
        WHERE EXISTS (
            SELECT 1
            FROM jute_supp_party_map jspm
            WHERE jspm.jute_supplier_id = jsm.supplier_id
              AND jspm.co_id = :co_id
        )
        ORDER BY jsm.supplier_name
    """
    return text(sql)


def get_branches_query():
    """
    Query to get list of branches for the company.
    """
    sql = """
        SELECT 
            branch_id,
            branch_name
        FROM branch_mst
        WHERE co_id = :co_id
        AND (active = 1 OR active IS NULL)
        ORDER BY branch_name
    """
    return text(sql)


# =============================================================================
# JUTE GATE ENTRY QUERIES (using jute_mr table)
# =============================================================================

def get_jute_gate_entry_table_query(co_id: int, branch_ids: list = None, search: str = None):
    """
    Query to get jute gate entry list with pagination support.
    
    Updated 2026-01-15: Now uses jute_mr table (merged gate entry + MR).
    The old jute_gate_entry table was deleted - all gate entry data is now in jute_mr.
    
    Args:
        co_id: Company ID for filtering
        branch_ids: List of branch IDs to filter by (optional)
        search: Search term for gate entry no, challan no, or vehicle no
    
    Columns: gate entry no, gate entry date, in time, out time, challan no, 
    vehicle no, challan weight, gross weight.
    """
    # Get the formatted gate entry number SQL expression (using jm alias for jute_mr)
    gate_entry_num_expr = get_jute_gate_entry_number_sql_expression(
        gate_entry_no_column="jm.jute_gate_entry_no",
        entry_date_column="jm.jute_gate_entry_date",
        co_prefix_column="cm.co_prefix",
        branch_prefix_column="bm.branch_prefix"
    )
    
    search_clause = ""
    if search:
        # Match against the formatted gate entry number (e.g. LCPL/FAC/JGE/26-27/00007)
        # too, not just the raw sequence integer — that's what users see and paste.
        search_clause = f"""
            AND (
                CAST(jm.jute_gate_entry_no AS CHAR) LIKE :search
                OR jm.challan_no LIKE :search
                OR jm.vehicle_no LIKE :search
                OR {gate_entry_num_expr} LIKE :search
            )
        """

    # Branch filter clause - uses IN clause with branch_ids list
    branch_clause = ""
    if branch_ids and len(branch_ids) > 0:
        # Create placeholders for branch IDs
        branch_placeholders = ", ".join([f":branch_id_{i}" for i in range(len(branch_ids))])
        branch_clause = f"AND jm.branch_id IN ({branch_placeholders})"

    date_clause = """
            AND (:date_from IS NULL OR jm.jute_gate_entry_date >= :date_from)
            AND (:date_to IS NULL OR jm.jute_gate_entry_date <= :date_to)
    """

    sql = f"""
        SELECT
            jm.jute_mr_id,
            jm.jute_gate_entry_no,
            CASE
                WHEN jm.jute_gate_entry_no IS NOT NULL
                THEN {gate_entry_num_expr}
                ELSE NULL
            END AS gate_entry_num,
            jm.jute_gate_entry_date,
            jm.in_time,
            jm.out_date,
            jm.out_time,
            jm.challan_no,
            jm.challan_date,
            jm.challan_weight,
            jm.vehicle_no,
            jm.gross_weight,
            jm.tare_weight,
            jm.net_weight,
            jm.branch_id,
            bm.branch_name,
            jm.status_id,
            COALESCE(sm.status_name, 'IN') AS status,
            jm.updated_date_time
        FROM jute_mr jm
        INNER JOIN branch_mst bm ON bm.branch_id = jm.branch_id
        INNER JOIN co_mst cm ON cm.co_id = bm.co_id
        LEFT JOIN status_mst sm ON sm.status_id = jm.status_id
        WHERE bm.co_id = :co_id
        AND jm.jute_gate_entry_no IS NOT NULL
        {branch_clause}
        {search_clause}
        {date_clause}
        ORDER BY jm.jute_gate_entry_date DESC, jm.jute_mr_id DESC
        LIMIT :limit OFFSET :offset
    """
    return text(sql)


def get_jute_gate_entry_table_count_query(co_id: int, branch_ids: list = None, search: str = None):
    """
    Query to get total count of jute gate entries for pagination.
    
    Updated 2026-01-15: Now uses jute_mr table (merged gate entry + MR).
    
    Args:
        co_id: Company ID for filtering
        branch_ids: List of branch IDs to filter by (optional)
        search: Search term for gate entry no, challan no, or vehicle no
    """
    # Formatted gate entry number expression — kept in sync with the data query so
    # search matches the same displayed value (e.g. LCPL/FAC/JGE/26-27/00007).
    gate_entry_num_expr = get_jute_gate_entry_number_sql_expression(
        gate_entry_no_column="jm.jute_gate_entry_no",
        entry_date_column="jm.jute_gate_entry_date",
        co_prefix_column="cm.co_prefix",
        branch_prefix_column="bm.branch_prefix"
    )

    search_clause = ""
    if search:
        search_clause = f"""
            AND (
                CAST(jm.jute_gate_entry_no AS CHAR) LIKE :search
                OR jm.challan_no LIKE :search
                OR jm.vehicle_no LIKE :search
                OR {gate_entry_num_expr} LIKE :search
            )
        """

    # Branch filter clause - uses IN clause with branch_ids list
    branch_clause = ""
    if branch_ids and len(branch_ids) > 0:
        # Create placeholders for branch IDs
        branch_placeholders = ", ".join([f":branch_id_{i}" for i in range(len(branch_ids))])
        branch_clause = f"AND jm.branch_id IN ({branch_placeholders})"

    date_clause = """
            AND (:date_from IS NULL OR jm.jute_gate_entry_date >= :date_from)
            AND (:date_to IS NULL OR jm.jute_gate_entry_date <= :date_to)
    """

    sql = f"""
        SELECT COUNT(*) AS total
        FROM jute_mr jm
        INNER JOIN branch_mst bm ON bm.branch_id = jm.branch_id
        INNER JOIN co_mst cm ON cm.co_id = bm.co_id
        WHERE bm.co_id = :co_id
        AND jm.jute_gate_entry_no IS NOT NULL
        {branch_clause}
        {search_clause}
        {date_clause}
    """
    return text(sql)


# =============================================================================
# JUTE GATE ENTRY DETAIL QUERIES (using jute_mr table)
# =============================================================================

def get_jute_gate_entry_by_id_query():
    """
    Query to get a single jute gate entry by ID.
    
    Updated 2026-01-15: Now uses jute_mr table (merged gate entry + MR).
    Includes formatted PO number and gate entry number with company and branch prefix.
    """
    # Get the formatted PO number SQL expression (using jp alias for jute_po)
    po_num_expr = get_jute_po_number_sql_expression(
        po_no_column="jp.po_no",
        po_date_column="jp.po_date",
        co_prefix_column="cm.co_prefix",
        branch_prefix_column="bm.branch_prefix"
    )
    
    # Get the formatted gate entry number SQL expression
    gate_entry_num_expr = get_jute_gate_entry_number_sql_expression(
        gate_entry_no_column="jm.jute_gate_entry_no",
        entry_date_column="jm.jute_gate_entry_date",
        co_prefix_column="cm.co_prefix",
        branch_prefix_column="bm.branch_prefix"
    )
    
    sql = f"""
        SELECT 
            jm.jute_mr_id,
            jm.jute_gate_entry_no,
            CASE 
                WHEN jm.jute_gate_entry_no IS NOT NULL 
                THEN {gate_entry_num_expr} 
                ELSE NULL 
            END AS gate_entry_num,
            jm.branch_id,
            bm.branch_name,
            jm.jute_gate_entry_date,
            jm.in_time,
            jm.out_date,
            jm.out_time,
            jm.challan_no,
            jm.challan_date,
            jm.challan_weight,
            jm.vehicle_no,
            jm.driver_name,
            jm.transporter,
            jm.po_id,
            jp.po_no,
            CASE WHEN jp.jute_po_id IS NOT NULL THEN {po_num_expr} ELSE NULL END AS po_num,
            jm.jute_supplier_id,
            jsm.supplier_name,
            jm.party_id,
            pm.supp_name AS party_name,
            jm.mukam_id,
            jmm.mukam_name AS mukam,
            jm.unit_conversion AS jute_uom,
            jm.gross_weight,
            jm.tare_weight,
            jm.net_weight,
            jm.variable_shortage,
            jm.actual_weight,
            jm.remarks,
            jm.status_id,
            COALESCE(sm.status_name, 'IN') AS status,
            jm.qc_check,
            jm.marketing_slip,
            jm.updated_by,
            jm.updated_date_time
        FROM jute_mr jm
        INNER JOIN branch_mst bm ON bm.branch_id = jm.branch_id
        INNER JOIN co_mst cm ON cm.co_id = bm.co_id
        LEFT JOIN jute_po jp ON jp.jute_po_id = jm.po_id
        LEFT JOIN jute_supplier_mst jsm ON jsm.supplier_id = jm.jute_supplier_id
        LEFT JOIN party_mst pm ON pm.party_id = jm.party_id
        LEFT JOIN jute_mukam_mst jmm ON jmm.mukam_id = jm.mukam_id
        LEFT JOIN status_mst sm ON sm.status_id = jm.status_id
        WHERE jm.jute_mr_id = :jute_mr_id AND bm.co_id = :co_id
    """
    return text(sql)


def get_jute_gate_entry_line_items_query():
    """
    Query to get line items for a jute gate entry.
    
    Updated: Uses item_mst for quality lookup instead of jute_quality_mst.
    challan_item_id and actual_item_id now reference item_mst directly.
    """
    sql = """
        SELECT 
            jmli.jute_mr_li_id,
            jmli.jute_mr_id,
            jmli.jute_po_li_id,
            im_ch.item_grp_id AS challan_item_grp_id,
            ig_ch.item_grp_name AS challan_group_name,
            jmli.challan_item_id,
            im_ch.item_name AS challan_quality_name,
            jmli.challan_quantity,
            jmli.challan_weight,
            im_act.item_grp_id AS actual_item_grp_id,
            ig_act.item_grp_name AS actual_group_name,
            jmli.actual_item_id,
            im_act.item_name AS actual_quality_name,
            jmli.actual_qty,
            jmli.actual_weight,
            jmli.allowable_moisture,
            jm.unit_conversion,
            jmli.remarks,
            jmli.active
        FROM jute_mr_li jmli
        INNER JOIN jute_mr jm ON jm.jute_mr_id = jmli.jute_mr_id
        LEFT JOIN item_mst im_ch ON im_ch.item_id = jmli.challan_item_id
        LEFT JOIN item_grp_mst ig_ch ON ig_ch.item_grp_id = im_ch.item_grp_id
        LEFT JOIN item_mst im_act ON im_act.item_id = jmli.actual_item_id
        LEFT JOIN item_grp_mst ig_act ON ig_act.item_grp_id = im_act.item_grp_id
        WHERE jmli.jute_mr_id = :jute_mr_id
        AND (jmli.active = 1 OR jmli.active IS NULL)
        ORDER BY jmli.jute_mr_li_id
    """
    return text(sql)


def get_jute_gate_entry_moisture_readings_query():
    """
    Query to get all persisted moisture readings for the line items of a
    jute gate entry (joined via jute_mr_li so a single :jute_mr_id bind works).
    """
    sql = """
        SELECT r.jute_mr_li_id, r.moisture_percentage
        FROM jute_moisture_rdg r
        INNER JOIN jute_mr_li jmli ON jmli.jute_mr_li_id = r.jute_mr_li_id
        WHERE jmli.jute_mr_id = :jute_mr_id
        ORDER BY r.jute_moisture_rdg_id
    """
    return text(sql)


def get_jute_po_for_gate_entry_query():
    """
    Query to get PO details for gate entry auto-fill (when PO is selected).
    Returns PO header and line items.
    """
    sql = """
        SELECT 
            jp.jute_po_id,
            jp.po_no,
            jp.po_date,
            jp.supplier_id,
            jsm.supplier_name,
            jp.party_id,
            pm.supp_name AS party_name,
            jp.jute_mukam_id AS mukam_id,
            jmm.mukam_name,
            jp.jute_uom,
            jp.branch_id
        FROM jute_po jp
        LEFT JOIN jute_supplier_mst jsm ON jsm.supplier_id = jp.supplier_id
        LEFT JOIN party_mst pm ON pm.party_id = jp.party_id
        LEFT JOIN jute_mukam_mst jmm ON jmm.mukam_id = jp.jute_mukam_id
        INNER JOIN branch_mst bm ON bm.branch_id = jp.branch_id
        WHERE jp.jute_po_id = :po_id AND bm.co_id = :co_id
    """
    return text(sql)


def get_jute_po_line_items_for_gate_entry_query():
    """
    Query to get PO line items for gate entry auto-fill.
    Uses item_grp_id for jute group and item_id for item (was quality).
    Uses recursive CTE for full group path names.
    """
    sql = _group_path_cte() + """
        SELECT 
            jpli.jute_po_li_id,
            im.item_grp_id,
            COALESCE(fgp.item_grp_name_path, ig.item_grp_name) AS jute_group_name,
            jpli.item_id,
            im.item_name AS quality_name,
            jpli.quantity,
            jpli.value AS amount,
            jpli.allowable_moisture,
            jpli.jute_uom
        FROM jute_po_li jpli
        LEFT JOIN item_mst im ON im.item_id = jpli.item_id
        LEFT JOIN item_grp_mst ig ON ig.item_grp_id = im.item_grp_id
        LEFT JOIN full_group_paths fgp ON fgp.item_grp_id = im.item_grp_id
        WHERE jpli.jute_po_id = :po_id AND (jpli.active = 1 OR jpli.active IS NULL)
        ORDER BY jpli.jute_po_li_id
    """
    return text(sql)


def get_open_jute_pos_query():
    """
    Query to get list of approved Jute POs for selection in gate entry.
    Only shows POs with status_id = 3 (Approved).
    Formats PO number with company and branch prefix.
    """
    po_num_expr = get_jute_po_number_sql_expression()
    
    sql = f"""
        SELECT 
            jp.jute_po_id,
            {po_num_expr} AS po_num,
            jp.po_date,
            jp.branch_id,
            jsm.supplier_name,
            jp.supplier_id,
            jmm.mukam_name,
            jp.weight AS total_weight,
            jp.jute_uom
        FROM jute_po jp
        INNER JOIN branch_mst bm ON bm.branch_id = jp.branch_id
        INNER JOIN co_mst cm ON cm.co_id = bm.co_id
        LEFT JOIN jute_supplier_mst jsm ON jsm.supplier_id = jp.supplier_id
        LEFT JOIN jute_mukam_mst jmm ON jmm.mukam_id = jp.jute_mukam_id
        WHERE bm.co_id = :co_id
        AND jp.status_id = 3
        ORDER BY jp.po_date DESC, jp.jute_po_id DESC
    """
    return text(sql)


# =============================================================================
# JUTE QUALITY CHECK QUERIES (using jute_mr table)
# =============================================================================

def get_material_inspection_table_query(co_id: int, branch_ids: list = None, search: str = None):
    """
    Query to get jute MR entries pending QC check (qc_check IS NULL or qc_check = 0).
    Returns entries that need quality inspection.
    
    Updated 2026-01-16: Now uses jute_mr table (merged gate entry + MR).
    The old jute_gate_entry table was deleted.
    
    Args:
        co_id: Company ID for filtering
        branch_ids: List of branch IDs to filter by (optional)
        search: Search term
    """
    # Get the formatted gate entry number SQL expression
    gate_entry_num_expr = get_jute_gate_entry_number_sql_expression(
        gate_entry_no_column="jm.jute_gate_entry_no",
        entry_date_column="jm.jute_gate_entry_date",
        co_prefix_column="cm.co_prefix",
        branch_prefix_column="bm.branch_prefix"
    )
    
    search_clause = ""
    if search:
        # Match against the formatted gate entry number (e.g. LCPL/FAC/JGE/26-27/00007)
        # too, not just the raw sequence integer — that's what users see and paste.
        search_clause = f"""
            AND (
                CAST(jm.jute_mr_id AS CHAR) LIKE :search
                OR CAST(jm.jute_gate_entry_no AS CHAR) LIKE :search
                OR jmm.mukam_name LIKE :search
                OR jm.vehicle_no LIKE :search
                OR jm.challan_no LIKE :search
                OR {gate_entry_num_expr} LIKE :search
            )
        """

    # Branch filter clause
    branch_clause = ""
    if branch_ids and len(branch_ids) > 0:
        branch_placeholders = ", ".join([f":branch_id_{i}" for i in range(len(branch_ids))])
        branch_clause = f"AND jm.branch_id IN ({branch_placeholders})"

    date_clause = """
            AND (:date_from IS NULL OR jm.jute_gate_entry_date >= :date_from)
            AND (:date_to IS NULL OR jm.jute_gate_entry_date <= :date_to)
    """

    sql = f"""
        SELECT
            jm.jute_mr_id,
            jm.jute_gate_entry_no,
            CASE
                WHEN jm.jute_gate_entry_no IS NOT NULL
                THEN {gate_entry_num_expr}
                ELSE NULL
            END AS gate_entry_num,
            jm.branch_id,
            bm.branch_name,
            jm.jute_gate_entry_date,
            jm.unit_conversion,
            jm.mukam_id,
            jmm.mukam_name AS mukam,
            jm.vehicle_no,
            jm.challan_no,
            jm.challan_weight,
            jm.gross_weight,
            jm.tare_weight,
            jm.net_weight,
            jm.variable_shortage,
            jm.qc_check,
            jm.jute_supplier_id,
            jsm.supplier_name,
            jm.party_id,
            pm.supp_name AS party_name,
            jm.status_id,
            COALESCE(sm.status_name, 'Pending QC') AS status,
            jm.updated_date_time
        FROM jute_mr jm
        INNER JOIN branch_mst bm ON bm.branch_id = jm.branch_id
        INNER JOIN co_mst cm ON cm.co_id = bm.co_id
        LEFT JOIN jute_mukam_mst jmm ON jmm.mukam_id = jm.mukam_id
        LEFT JOIN jute_supplier_mst jsm ON jsm.supplier_id = jm.jute_supplier_id
        LEFT JOIN party_mst pm ON pm.party_id = jm.party_id
        LEFT JOIN status_mst sm ON sm.status_id = jm.status_id
        WHERE bm.co_id = :co_id
        AND jm.jute_gate_entry_no IS NOT NULL
        AND (jm.qc_check IS NULL OR jm.qc_check = 0)
        {branch_clause}
        {search_clause}
        {date_clause}
        ORDER BY jm.jute_gate_entry_date DESC, jm.jute_mr_id DESC
        LIMIT :limit OFFSET :offset
    """
    return text(sql)


def get_material_inspection_table_count_query(co_id: int, branch_ids: list = None, search: str = None):
    """
    Query to get total count of jute MR entries pending QC check.
    
    Updated 2026-01-16: Now uses jute_mr table (merged gate entry + MR).
    
    Args:
        co_id: Company ID for filtering
        branch_ids: List of branch IDs to filter by (optional)
        search: Search term
    """
    # Formatted gate entry number expression — kept in sync with the data query so
    # search matches the same displayed value (e.g. LCPL/FAC/JGE/26-27/00007).
    gate_entry_num_expr = get_jute_gate_entry_number_sql_expression(
        gate_entry_no_column="jm.jute_gate_entry_no",
        entry_date_column="jm.jute_gate_entry_date",
        co_prefix_column="cm.co_prefix",
        branch_prefix_column="bm.branch_prefix"
    )

    search_clause = ""
    if search:
        search_clause = f"""
            AND (
                CAST(jm.jute_mr_id AS CHAR) LIKE :search
                OR CAST(jm.jute_gate_entry_no AS CHAR) LIKE :search
                OR jmm.mukam_name LIKE :search
                OR jm.vehicle_no LIKE :search
                OR jm.challan_no LIKE :search
                OR {gate_entry_num_expr} LIKE :search
            )
        """

    # Branch filter clause
    branch_clause = ""
    if branch_ids and len(branch_ids) > 0:
        branch_placeholders = ", ".join([f":branch_id_{i}" for i in range(len(branch_ids))])
        branch_clause = f"AND jm.branch_id IN ({branch_placeholders})"

    date_clause = """
            AND (:date_from IS NULL OR jm.jute_gate_entry_date >= :date_from)
            AND (:date_to IS NULL OR jm.jute_gate_entry_date <= :date_to)
    """

    sql = f"""
        SELECT COUNT(*) AS total
        FROM jute_mr jm
        INNER JOIN branch_mst bm ON bm.branch_id = jm.branch_id
        INNER JOIN co_mst cm ON cm.co_id = bm.co_id
        LEFT JOIN jute_mukam_mst jmm ON jmm.mukam_id = jm.mukam_id
        WHERE bm.co_id = :co_id
        AND jm.jute_gate_entry_no IS NOT NULL
        AND (jm.qc_check IS NULL OR jm.qc_check = 0)
        {branch_clause}
        {search_clause}
        {date_clause}
    """
    return text(sql)


def get_material_inspection_by_id_query():
    """
    Query to get a single jute MR entry for quality check/material inspection.
    
    Updated 2026-01-16: Now uses jute_mr table (merged gate entry + MR).
    """
    # Get the formatted gate entry number SQL expression
    gate_entry_num_expr = get_jute_gate_entry_number_sql_expression(
        gate_entry_no_column="jm.jute_gate_entry_no",
        entry_date_column="jm.jute_gate_entry_date",
        co_prefix_column="cm.co_prefix",
        branch_prefix_column="bm.branch_prefix"
    )
    
    sql = f"""
        SELECT 
            jm.jute_mr_id,
            jm.jute_gate_entry_no,
            CASE 
                WHEN jm.jute_gate_entry_no IS NOT NULL 
                THEN {gate_entry_num_expr} 
                ELSE NULL 
            END AS gate_entry_num,
            jm.branch_id,
            bm.branch_name,
            jm.jute_gate_entry_date,
            jm.unit_conversion,
            jm.mukam_id,
            jmm.mukam_name AS mukam,
            jm.vehicle_no,
            jm.challan_no,
            jm.challan_date,
            jm.challan_weight,
            jm.gross_weight,
            jm.tare_weight,
            jm.net_weight,
            jm.variable_shortage,
            jm.jute_supplier_id,
            jsm.supplier_name,
            jm.party_id,
            pm.supp_name AS party_name,
            jm.po_id,
            jm.qc_check,
            jm.status_id,
            COALESCE(sm.status_name, 'Pending QC') AS status,
            jm.remarks,
            jm.updated_by,
            jm.updated_date_time
        FROM jute_mr jm
        INNER JOIN branch_mst bm ON bm.branch_id = jm.branch_id
        INNER JOIN co_mst cm ON cm.co_id = bm.co_id
        LEFT JOIN jute_mukam_mst jmm ON jmm.mukam_id = jm.mukam_id
        LEFT JOIN jute_supplier_mst jsm ON jsm.supplier_id = jm.jute_supplier_id
        LEFT JOIN party_mst pm ON pm.party_id = jm.party_id
        LEFT JOIN status_mst sm ON sm.status_id = jm.status_id
        WHERE jm.jute_mr_id = :jute_mr_id
    """
    return text(sql)


def get_material_inspection_line_items_query():
    """
    Query to get line items for quality check/material inspection.
    
    Updated: Uses item_mst for quality lookup instead of jute_quality_mst.
    """
    sql = """
        SELECT 
            jmli.jute_mr_li_id,
            jmli.jute_mr_id,
            jmli.jute_po_li_id,
            
            -- Challan details (group derived from item_mst)
            im_ch.item_grp_id AS challan_item_grp_id,
            ig_ch.item_grp_name AS challan_group_name,
            jmli.challan_item_id,
            im_ch.item_name AS challan_quality_name,
            jmli.challan_quantity,
            jmli.challan_weight,
            
            -- Actual (received) details (group derived from item_mst)
            im_act.item_grp_id AS actual_item_grp_id,
            ig_act.item_grp_name AS actual_group_name,
            jmli.actual_item_id,
            im_act.item_name AS actual_quality_name,
            jmli.actual_qty,
            jmli.actual_weight,
            
            -- QC fields
            jmli.allowable_moisture,
            jmli.actual_moisture,
            jmli.accepted_weight,
            jmli.rate,
            jmli.warehouse_id,
            jmli.marka,
            jmli.crop_year,
            
            jmli.unit_conversion,
            jmli.remarks,
            jmli.active
        FROM jute_mr_li jmli
        LEFT JOIN item_mst im_ch ON im_ch.item_id = jmli.challan_item_id
        LEFT JOIN item_grp_mst ig_ch ON ig_ch.item_grp_id = im_ch.item_grp_id
        LEFT JOIN item_mst im_act ON im_act.item_id = jmli.actual_item_id
        LEFT JOIN item_grp_mst ig_act ON ig_act.item_grp_id = im_act.item_grp_id
        WHERE jmli.jute_mr_id = :jute_mr_id
        AND (jmli.active = 1 OR jmli.active IS NULL)
        ORDER BY jmli.jute_mr_li_id
    """
    return text(sql)


def update_material_inspection_qc_complete():
    """
    Query to mark a jute MR entry as QC complete (qc_check = 1).
    
    Updated 2026-01-16: Now uses jute_mr table (merged gate entry + MR).
    Changed qc_check from 'Y' to 1 (integer flag).
    """
    sql = """
        UPDATE jute_mr
        SET qc_check = 1,
            updated_by = :updated_by,
            updated_date_time = :updated_date_time
        WHERE jute_mr_id = :jute_mr_id
    """
    return text(sql)


def insert_jute_mr_query():
    """
    Query to insert a new jute MR (Material Receipt) record.
    This is created when material inspection is completed.
    """
    sql = """
        INSERT INTO jute_mr (
            branch_id, branch_mr_no, jute_mr_date,
            jute_gate_entry_no, jute_gate_entry_date, 
            challan_no, challan_date,
            jute_supplier_id, party_id, mukam_id, unit_conversion,
            po_id, mr_weight, vehicle_no, status_id, remarks,
            updated_by, updated_date_time
        ) VALUES (
            :branch_id, :branch_mr_no, :jute_mr_date,
            :jute_gate_entry_no, :jute_gate_entry_date,
            :challan_no, :challan_date,
            :jute_supplier_id, :party_id, :mukam_id, :unit_conversion,
            :po_id, :mr_weight, :vehicle_no, :status_id, :remarks,
            :updated_by, :updated_date_time
        )
    """
    return text(sql)


def insert_jute_mr_li_query():
    """
    Query to insert a jute MR line item with QC data.
    QC data is now stored here instead of jute_gate_entry_li.
    """
    sql = """
        INSERT INTO jute_mr_li (
            jute_mr_id, jute_po_li_id,
            challan_item_id, challan_quality_id, challan_quantity, challan_weight,
            actual_item_id, actual_quality, actual_qty, actual_weight,
            allowable_moisture, actual_moisture, accepted_weight,
            rate, warehouse_id, marka, crop_year,
            remarks, status, active, updated_date_time
        ) VALUES (
            :jute_mr_id, :jute_po_li_id,
            :challan_item_id, :challan_quality_id, :challan_quantity, :challan_weight,
            :actual_item_id, :actual_quality, :actual_qty, :actual_weight,
            :allowable_moisture, :actual_moisture, :accepted_weight,
            :rate, :warehouse_id, :marka, :crop_year,
            :remarks, :status, 1, :updated_date_time
        )
    """
    return text(sql)


def insert_jute_moisture_rdg_query():
    """
    Query to insert moisture readings for a jute MR line item.
    """
    sql = """
        INSERT INTO jute_moisture_rdg (
            jute_mr_li_id, moisture_percentage
        ) VALUES (
            :jute_mr_li_id, :moisture_percentage
        )
    """
    return text(sql)


def get_moisture_readings_by_mr_li_id_query():
    """
    Query to get moisture readings for a specific jute MR line item.
    """
    sql = """
        SELECT 
            jute_moisture_rdg_id,
            jute_mr_li_id,
            moisture_percentage
        FROM jute_moisture_rdg
        WHERE jute_mr_li_id = :jute_mr_li_id
        ORDER BY jute_moisture_rdg_id
    """
    return text(sql)


def delete_moisture_readings_query():
    """
    Query to delete all moisture readings for a specific jute MR line item.
    """
    sql = """
        DELETE FROM jute_moisture_rdg
        WHERE jute_mr_li_id = :jute_mr_li_id
    """
    return text(sql)


def update_mr_li_actual_moisture_query():
    """
    Query to update actual_moisture on jute_mr_li for a specific line item.
    """
    sql = """
        UPDATE jute_mr_li
        SET actual_moisture = :actual_moisture
        WHERE jute_mr_li_id = :jute_mr_li_id
    """
    return text(sql)


def update_mr_li_accepted_weight_query():
    """
    Query to update accepted_weight on jute_mr_li for a specific line item.
    """
    sql = """
        UPDATE jute_mr_li
        SET accepted_weight = :accepted_weight
        WHERE jute_mr_li_id = :jute_mr_li_id
    """
    return text(sql)


# =============================================================================
# JUTE MR (MATERIAL RECEIPT) QUERIES
# =============================================================================

def get_jute_mr_table_query(co_id: int, search: str = None):
    """
    Query to get jute MR list with pagination support.
    Joins with branch_mst for co_id filtering, jute_supplier_mst for supplier name,
    party_mst for party details, jute_po for PO number, and jute_mukam_mst for mukam.
    
    Only shows entries where out_time IS NOT NULL (vehicle has exited).
    Entries without out_time continue to show in the gate entry table.
    """
    # Get the formatted gate entry number SQL expression
    gate_entry_num_expr = get_jute_gate_entry_number_sql_expression(
        gate_entry_no_column="jm.jute_gate_entry_no",
        entry_date_column="jm.jute_gate_entry_date",
        co_prefix_column="cm.co_prefix",
        branch_prefix_column="bm.branch_prefix"
    )
    # Get the formatted MR number SQL expression
    mr_num_expr = get_jute_mr_number_sql_expression()
    # Formatted PO number uses the PO's own branch prefix (po_bm), not the MR's
    po_num_expr = get_jute_po_number_sql_expression(
        branch_prefix_column="po_bm.branch_prefix"
    )

    search_clause = ""
    if search:
        search_clause = f"""
            AND (
                CAST(jm.branch_mr_no AS CHAR) LIKE :search
                OR {mr_num_expr} LIKE :search
                OR CAST(jp.po_no AS CHAR) LIKE :search
                OR {po_num_expr} LIKE :search
                OR jsm.supplier_name LIKE :search
                OR pm.supp_name LIKE :search
                OR jm.challan_no LIKE :search
                OR jm.vehicle_no LIKE :search
                OR {gate_entry_num_expr} LIKE :search
                OR jmm.mukam_name LIKE :search
                OR bm.branch_name LIKE :search
            )
        """

    date_clause = """
            AND (:date_from IS NULL OR jm.jute_mr_date >= :date_from)
            AND (:date_to IS NULL OR jm.jute_mr_date <= :date_to)
    """

    sql = f"""
        SELECT
            jm.jute_mr_id,
            jm.branch_mr_no,
            CASE
                WHEN jm.branch_mr_no IS NOT NULL
                THEN {mr_num_expr}
                ELSE NULL
            END AS mr_num,
            jm.jute_mr_date,
            jm.branch_id,
            bm.branch_name,
            jm.jute_supplier_id,
            jsm.supplier_name,
            jm.party_id,
            pm.supp_name AS party_name,
            jm.party_branch_id,
            pb.branch_name AS party_branch_name,
            jm.po_id,
            jp.po_no,
            CASE
                WHEN jp.po_no IS NOT NULL
                THEN {po_num_expr}
                ELSE NULL
            END AS po_num,
            jp.po_date,
            jm.challan_no,
            jm.challan_date,
            jm.mukam_id,
            jmm.mukam_name AS mukam,
            jm.vehicle_no,
            jm.unit_conversion,
            jm.mr_weight,
            jm.remarks,
            jm.status_id,
            COALESCE(sm.status_name, 'Open') AS status,
            jm.src_com_id,
            jm.jute_gate_entry_no,
            jm.jute_gate_entry_date,
            CASE 
                WHEN jm.jute_gate_entry_no IS NOT NULL 
                THEN {gate_entry_num_expr}
                ELSE NULL 
            END AS gate_entry_no,
            jm.updated_date_time
        FROM jute_mr jm
        INNER JOIN branch_mst bm ON bm.branch_id = jm.branch_id
        INNER JOIN co_mst cm ON cm.co_id = bm.co_id
        LEFT JOIN jute_supplier_mst jsm ON jsm.supplier_id = jm.jute_supplier_id
        LEFT JOIN party_mst pm ON pm.party_id = CAST(jm.party_id AS UNSIGNED)
        LEFT JOIN branch_mst pb ON pb.branch_id = jm.party_branch_id
        LEFT JOIN jute_po jp ON jp.jute_po_id = jm.po_id
        LEFT JOIN branch_mst po_bm ON po_bm.branch_id = jp.branch_id
        LEFT JOIN jute_mukam_mst jmm ON jmm.mukam_id = jm.mukam_id
        LEFT JOIN status_mst sm ON sm.status_id = jm.status_id
        WHERE bm.co_id = :co_id
        AND jm.out_time IS NOT NULL
        {search_clause}
        {date_clause}
        AND (
            :status_id IS NULL
            OR jm.status_id = :status_id
            OR (:status_id = 1 AND jm.status_id IS NULL)
        )
        ORDER BY jm.jute_gate_entry_date IS NULL, jm.jute_gate_entry_date DESC, jm.jute_mr_id DESC
        LIMIT :limit OFFSET :offset
    """
    return text(sql)


def get_jute_mr_table_count_query(co_id: int, search: str = None):
    """
    Query to get total count of jute MRs for pagination.
    Only counts entries where out_time IS NOT NULL (vehicle has exited).
    """
    gate_entry_num_expr = get_jute_gate_entry_number_sql_expression(
        gate_entry_no_column="jm.jute_gate_entry_no",
        entry_date_column="jm.jute_gate_entry_date",
        co_prefix_column="cm.co_prefix",
        branch_prefix_column="bm.branch_prefix"
    )
    mr_num_expr = get_jute_mr_number_sql_expression()
    po_num_expr = get_jute_po_number_sql_expression(
        branch_prefix_column="po_bm.branch_prefix"
    )

    search_clause = ""
    if search:
        search_clause = f"""
            AND (
                CAST(jm.branch_mr_no AS CHAR) LIKE :search
                OR {mr_num_expr} LIKE :search
                OR CAST(jp.po_no AS CHAR) LIKE :search
                OR {po_num_expr} LIKE :search
                OR jsm.supplier_name LIKE :search
                OR pm.supp_name LIKE :search
                OR jm.challan_no LIKE :search
                OR jm.vehicle_no LIKE :search
                OR {gate_entry_num_expr} LIKE :search
                OR jmm.mukam_name LIKE :search
                OR bm.branch_name LIKE :search
            )
        """

    date_clause = """
            AND (:date_from IS NULL OR jm.jute_mr_date >= :date_from)
            AND (:date_to IS NULL OR jm.jute_mr_date <= :date_to)
    """

    sql = f"""
        SELECT COUNT(*) AS total
        FROM jute_mr jm
        INNER JOIN branch_mst bm ON bm.branch_id = jm.branch_id
        INNER JOIN co_mst cm ON cm.co_id = bm.co_id
        LEFT JOIN jute_supplier_mst jsm ON jsm.supplier_id = jm.jute_supplier_id
        LEFT JOIN party_mst pm ON pm.party_id = CAST(jm.party_id AS UNSIGNED)
        LEFT JOIN jute_po jp ON jp.jute_po_id = jm.po_id
        LEFT JOIN branch_mst po_bm ON po_bm.branch_id = jp.branch_id
        LEFT JOIN jute_mukam_mst jmm ON jmm.mukam_id = jm.mukam_id
        WHERE bm.co_id = :co_id
        AND jm.out_time IS NOT NULL
        {search_clause}
        {date_clause}
        AND (
            :status_id IS NULL
            OR jm.status_id = :status_id
            OR (:status_id = 1 AND jm.status_id IS NULL)
        )
    """
    return text(sql)


def get_jute_mr_by_id_query():
    """
    Query to get a single jute MR by ID with all header details.
    Includes actual_weight from gate entry and party branch info from party_branch_mst.
    """
    mr_num_expr = get_jute_mr_number_sql_expression()
    po_num_expr = get_jute_po_number_sql_expression(
        po_no_column="jp.po_no",
        po_date_column="jp.po_date",
        co_prefix_column="cm.co_prefix",
        branch_prefix_column="bm.branch_prefix",
    )

    sql = f"""
        SELECT
            jm.jute_mr_id,
            jm.branch_mr_no,
            CASE
                WHEN jm.branch_mr_no IS NOT NULL
                THEN {mr_num_expr}
                ELSE NULL
            END AS mr_num,
            jm.jute_mr_date,
            jm.branch_id,
            bm.branch_name,
            jm.jute_supplier_id,
            jsm.supplier_name,
            jm.party_id,
            pm.supp_name AS party_name,
            jm.party_branch_id,
            CONCAT(COALESCE(pm.supp_name, ''), ' - ', COALESCE(pbm.address, '')) AS party_branch_name,
            pbm.address AS party_address,
            pbm.gst_no AS party_gst_no,
            jm.po_id,
            jp.po_no,
            CASE WHEN jp.jute_po_id IS NOT NULL THEN {po_num_expr} ELSE NULL END AS po_num,
            jp.po_date,
            jm.challan_no,
            jm.challan_date,
            jm.mukam_id,
            jmm.mukam_name AS mukam,
            jm.vehicle_no,
            jm.unit_conversion,
            jm.actual_weight,
            jm.mr_weight,
            jm.remarks,
            jm.status_id,
            jm.approval_level,
            COALESCE(sm.status_name, 'Open') AS status,
            jm.src_com_id,
            jm.jute_gate_entry_date,
            jm.updated_by,
            jm.updated_date_time,
            cm.co_name,
            cm.co_logo,
            cm.co_address1,
            cm.co_address2,
            cm.co_zipcode
        FROM jute_mr jm
        INNER JOIN branch_mst bm ON bm.branch_id = jm.branch_id
        INNER JOIN co_mst cm ON cm.co_id = bm.co_id
        LEFT JOIN jute_supplier_mst jsm ON jsm.supplier_id = jm.jute_supplier_id
        LEFT JOIN party_mst pm ON pm.party_id = CAST(jm.party_id AS UNSIGNED)
        LEFT JOIN party_branch_mst pbm ON pbm.party_mst_branch_id = jm.party_branch_id
        LEFT JOIN jute_po jp ON jp.jute_po_id = jm.po_id
        LEFT JOIN jute_mukam_mst jmm ON jmm.mukam_id = jm.mukam_id
        LEFT JOIN status_mst sm ON sm.status_id = jm.status_id
        WHERE jm.jute_mr_id = :mr_id
    """
    return text(sql)


def get_jute_mr_line_items_query():
    """
    Query to get line items for a jute MR.
    Includes warehouse_path using recursive CTE similar to item_group_path.
    Joins with jute_po_li to get rate from PO if not set on MR line item.
    """
    sql = """
        WITH RECURSIVE warehouse_hierarchy AS (
            SELECT 
                wm.warehouse_id,
                wm.branch_id,
                wm.warehouse_name,
                wm.parent_warehouse_id,
                CAST(wm.warehouse_name AS CHAR(500)) AS warehouse_path
            FROM warehouse_mst wm
            WHERE wm.parent_warehouse_id IS NULL
            UNION ALL
            SELECT 
                child.warehouse_id,
                child.branch_id,
                child.warehouse_name,
                child.parent_warehouse_id,
                CONCAT(parent.warehouse_path, '-', child.warehouse_name)
            FROM warehouse_mst child
            JOIN warehouse_hierarchy parent 
                ON child.parent_warehouse_id = parent.warehouse_id
        )
        SELECT 
            jmli.jute_mr_li_id,
            jmli.jute_mr_id,
            jmli.jute_po_li_id,
            im.item_grp_id AS actual_item_grp_id,
            ig.item_grp_name AS actual_group_name,
            jmli.actual_item_id,
            im.item_name AS actual_quality_name,
            jmli.actual_qty,
            jmli.challan_weight,
            jmli.actual_weight,
            jmli.actual_rate,
            jmli.allowable_moisture,
            jmli.actual_moisture,
            jmli.claim_dust,
            jmli.shortage_kgs,
            jmli.accepted_weight,
            COALESCE(NULLIF(jmli.rate, 0), jpli.rate) AS rate,
            jpli.rate AS po_rate,
            jmli.claim_rate,
            jmli.claim_quality,
            jmli.water_damage_amount,
            jmli.premium_amount,
            jmli.warehouse_id,
            wh.warehouse_path,
            jmli.unit_conversion,
            jmli.remarks,
            jmli.status,
            jmli.active
        FROM jute_mr_li jmli
        LEFT JOIN item_mst im ON im.item_id = jmli.actual_item_id
        LEFT JOIN item_grp_mst ig ON ig.item_grp_id = im.item_grp_id
        LEFT JOIN warehouse_hierarchy wh ON wh.warehouse_id = jmli.warehouse_id
        LEFT JOIN jute_po_li jpli ON jpli.jute_po_li_id = jmli.jute_po_li_id
        WHERE jmli.jute_mr_id = :mr_id
        AND (jmli.active = 1 OR jmli.active IS NULL)
        ORDER BY jmli.jute_mr_li_id
    """
    return text(sql)


def get_all_active_company_branches_query():
    """
    Query to get all active branches from all companies.
    Used for agent selection dropdown.
    Returns company name and branch name for display.
    """
    sql = """
        SELECT 
            bm.branch_id,
            cm.co_name AS company_name,
            bm.branch_name
        FROM branch_mst bm
        INNER JOIN co_mst cm ON cm.co_id = bm.co_id
        WHERE (bm.active = 1 OR bm.active IS NULL)
        ORDER BY cm.co_name, bm.branch_name
    """
    return text(sql)


def get_agent_map_options_query():
    """
    Query to get agent options from jute_agent_map table.
    Returns agent branch info with party branch details.
    Used for agent selection dropdown in MR.
    """
    sql = """
        SELECT DISTINCT
            jam.agent_branch_id,
            cm.co_name AS company_name,
            bm.branch_name,
            CONCAT(cm.co_name, ' - ', bm.branch_name) AS display
        FROM jute_agent_map jam
        INNER JOIN branch_mst bm ON bm.branch_id = jam.agent_branch_id
        INNER JOIN co_mst cm ON cm.co_id = bm.co_id
        WHERE jam.co_id = :co_id
            AND (bm.active = 1 OR bm.active IS NULL)
        ORDER BY cm.co_name, bm.branch_name
    """
    return text(sql)


def get_warehouse_options_query():
    """
    Query to get warehouse options with recursive path for dropdowns.
    Uses same recursive logic as warehouse master page.
    """
    sql = """
        WITH RECURSIVE warehouse_hierarchy AS (
            SELECT 
                wm.warehouse_id,
                wm.branch_id,
                wm.warehouse_name,
                wm.parent_warehouse_id,
                CAST(wm.warehouse_name AS CHAR(500)) AS warehouse_path
            FROM warehouse_mst wm
            WHERE wm.parent_warehouse_id IS NULL
                AND wm.branch_id = :branch_id
            UNION ALL
            SELECT 
                child.warehouse_id,
                child.branch_id,
                child.warehouse_name,
                child.parent_warehouse_id,
                CONCAT(parent.warehouse_path, '-', child.warehouse_name)
            FROM warehouse_mst child
            JOIN warehouse_hierarchy parent 
                ON child.parent_warehouse_id = parent.warehouse_id
            WHERE child.branch_id = :branch_id
        )
        SELECT 
            wh.warehouse_id,
            wh.warehouse_name,
            wh.warehouse_path
        FROM warehouse_hierarchy wh
        ORDER BY wh.warehouse_path
    """
    return text(sql)


# =============================================================================
# JUTE BILL PASS QUERIES
# =============================================================================

def get_jute_bill_pass_table_query(co_id: int, search: str = None):
    """
    Query to get jute bill pass list with pagination support.
    Bill passes are approved MRs (status_id = 3) from jute_mr table.

    Returns columns: bill_pass_no, bill_pass_date, mr_no, supplier, party,
                     invoice_no, invoice_date, amount (net_total)
    """
    mr_num_expr = get_jute_mr_number_sql_expression()
    bill_pass_num_expr = get_jute_bill_pass_number_sql_expression()

    search_clause = ""
    if search:
        # Match against the formatted bill pass number (e.g. ACPL/HO/JBP/26-27/00001)
        # and MR number too, not just the raw sequence integers — that's what users
        # see and paste. NULL guards mirror the SELECT CASE so the expr never matches
        # an unformatted row.
        search_clause = f"""
            AND (
                CAST(jm.bill_pass_no AS CHAR) LIKE :search
                OR CAST(jm.branch_mr_no AS CHAR) LIKE :search
                OR jsm.supplier_name LIKE :search
                OR pm.supp_name LIKE :search
                OR jm.invoice_no LIKE :search
                OR (jm.bill_pass_no IS NOT NULL AND {bill_pass_num_expr} LIKE :search)
                OR (jm.branch_mr_no IS NOT NULL AND {mr_num_expr} LIKE :search)
            )
        """

    date_clause = """
            AND (:date_from IS NULL OR jm.bill_pass_date >= :date_from)
            AND (:date_to IS NULL OR jm.bill_pass_date <= :date_to)
    """

    sql = f"""
        SELECT
            jm.jute_mr_id,
            jm.bill_pass_no,
            CASE
                WHEN jm.bill_pass_no IS NOT NULL
                THEN {bill_pass_num_expr}
                ELSE NULL
            END AS bill_pass_num,
            jm.bill_pass_date,
            jm.bill_pass_complete,
            jm.branch_mr_no AS mr_no,
            CASE
                WHEN jm.branch_mr_no IS NOT NULL
                THEN {mr_num_expr}
                ELSE NULL
            END AS mr_num,
            jm.jute_mr_date AS mr_date,
            jm.branch_id,
            bm.branch_name,
            jm.jute_supplier_id,
            jsm.supplier_name,
            jm.party_id,
            pm.supp_name AS party_name,
            jm.invoice_no,
            jm.invoice_date,
            jm.invoice_amount,
            jm.total_amount,
            jm.claim_amount,
            jm.roundoff,
            jm.net_total AS amount,
            jm.tds_amount,
            jm.payment_due_date,
            jm.status_id,
            COALESCE(sm.status_name, 'Approved') AS status,
            jm.updated_date_time
        FROM jute_mr jm
        INNER JOIN branch_mst bm ON bm.branch_id = jm.branch_id
        INNER JOIN co_mst cm ON cm.co_id = bm.co_id
        LEFT JOIN jute_supplier_mst jsm ON jsm.supplier_id = jm.jute_supplier_id
        LEFT JOIN party_mst pm ON pm.party_id = CAST(jm.party_id AS UNSIGNED)
        LEFT JOIN status_mst sm ON sm.status_id = jm.status_id
        WHERE bm.co_id = :co_id
        AND jm.status_id = 3
        {search_clause}
        {date_clause}
        ORDER BY jm.bill_pass_date DESC, jm.bill_pass_no DESC, jm.jute_mr_id DESC
        LIMIT :limit OFFSET :offset
    """
    return text(sql)


def get_jute_bill_pass_table_count_query(co_id: int, search: str = None):
    """
    Query to get total count of jute bill passes for pagination.
    Counts only approved MRs (status_id = 3).
    Optional :date_from / :date_to bind params bound jm.bill_pass_date.
    """
    # Formatted bill pass / MR number expressions — kept in sync with the data query
    # so search matches the same displayed values (e.g. ACPL/HO/JBP/26-27/00001).
    mr_num_expr = get_jute_mr_number_sql_expression()
    bill_pass_num_expr = get_jute_bill_pass_number_sql_expression()

    search_clause = ""
    if search:
        search_clause = f"""
            AND (
                CAST(jm.bill_pass_no AS CHAR) LIKE :search
                OR CAST(jm.branch_mr_no AS CHAR) LIKE :search
                OR jsm.supplier_name LIKE :search
                OR pm.supp_name LIKE :search
                OR jm.invoice_no LIKE :search
                OR (jm.bill_pass_no IS NOT NULL AND {bill_pass_num_expr} LIKE :search)
                OR (jm.branch_mr_no IS NOT NULL AND {mr_num_expr} LIKE :search)
            )
        """

    date_clause = """
            AND (:date_from IS NULL OR jm.bill_pass_date >= :date_from)
            AND (:date_to IS NULL OR jm.bill_pass_date <= :date_to)
    """

    sql = f"""
        SELECT COUNT(*) AS total
        FROM jute_mr jm
        INNER JOIN branch_mst bm ON bm.branch_id = jm.branch_id
        INNER JOIN co_mst cm ON cm.co_id = bm.co_id
        LEFT JOIN jute_supplier_mst jsm ON jsm.supplier_id = jm.jute_supplier_id
        LEFT JOIN party_mst pm ON pm.party_id = CAST(jm.party_id AS UNSIGNED)
        WHERE bm.co_id = :co_id
        AND jm.status_id = 3
        {search_clause}
        {date_clause}
    """
    return text(sql)


def get_jute_bill_pass_by_id_query():
    """
    Query to get a single jute bill pass (approved MR) by ID with all details.
    """
    mr_num_expr = get_jute_mr_number_sql_expression()
    bill_pass_num_expr = get_jute_bill_pass_number_sql_expression()

    sql = f"""
        SELECT
            jm.jute_mr_id,
            jm.bill_pass_no,
            CASE
                WHEN jm.bill_pass_no IS NOT NULL
                THEN {bill_pass_num_expr}
                ELSE NULL
            END AS bill_pass_num,
            jm.bill_pass_date,
            jm.bill_pass_complete,
            jm.branch_mr_no AS mr_no,
            CASE
                WHEN jm.branch_mr_no IS NOT NULL
                THEN {mr_num_expr}
                ELSE NULL
            END AS mr_num,
            jm.jute_mr_date AS mr_date,
            jm.jute_gate_entry_no AS gate_entry_no,
            jm.jute_gate_entry_date AS gate_entry_date,
            jm.branch_id,
            bm.branch_name,
            jm.jute_supplier_id,
            jsm.supplier_name,
            jm.party_id,
            pm.supp_name AS party_name,
            jm.party_branch_id,
            pb.branch_name AS party_branch_name,
            jm.po_id,
            jp.po_no,
            jp.po_date,
            jm.challan_no,
            jm.challan_date,
            jm.mukam_id,
            jmm.mukam_name AS mukam,
            jm.vehicle_no,
            jm.mr_weight,
            jm.frieght_paid AS freight_charges,
            jm.invoice_no,
            jm.invoice_date,
            jm.invoice_amount,
            jm.invoice_received_date,
            jm.total_amount,
            jm.claim_amount,
            jm.roundoff,
            jm.net_total AS amount,
            jm.tds_amount,
            jm.payment_due_date,
            jm.invoice_upload,
            jm.challan_upload,
            jm.remarks,
            jm.status_id,
            COALESCE(sm.status_name, 'Approved') AS status,
            jm.updated_by,
            jm.updated_date_time
        FROM jute_mr jm
        INNER JOIN branch_mst bm ON bm.branch_id = jm.branch_id
        INNER JOIN co_mst cm ON cm.co_id = bm.co_id
        LEFT JOIN jute_supplier_mst jsm ON jsm.supplier_id = jm.jute_supplier_id
        LEFT JOIN party_mst pm ON pm.party_id = CAST(jm.party_id AS UNSIGNED)
        LEFT JOIN branch_mst pb ON pb.branch_id = jm.party_branch_id
        LEFT JOIN jute_po jp ON jp.jute_po_id = jm.po_id
        LEFT JOIN jute_mukam_mst jmm ON jmm.mukam_id = jm.mukam_id
        LEFT JOIN status_mst sm ON sm.status_id = jm.status_id
        WHERE jm.jute_mr_id = :jute_mr_id
        AND jm.status_id = 3
        AND bm.co_id = :co_id
    """
    return text(sql)


# =============================================================================
# JUTE ISSUE QUERIES
# =============================================================================

def get_jute_issue_table_query(co_id: int, search: str = None):
    """
    Query to get jute issue list aggregated by date and branch with pagination support.
    Groups by issue_date and branch_id, sums weights, and determines aggregated status:
    - 'Approved' if all items for that date/branch are approved (status_id = 3)
    - 'Partial Approved' if some items are approved
    - 'Draft' if no items are approved
    """
    search_clause = ""
    if search:
        search_clause = """
            AND (
                CAST(ji.issue_date AS CHAR) LIKE :search
                OR bm.branch_name LIKE :search
            )
        """

    date_clause = """
            AND (:date_from IS NULL OR ji.issue_date >= :date_from)
            AND (:date_to IS NULL OR ji.issue_date <= :date_to)
    """

    sql = f"""
        SELECT
            ji.issue_date,
            ji.branch_id,
            bm.branch_name,
            SUM(COALESCE(ji.weight, 0)) AS total_weight,
            COUNT(*) AS total_entries,
            SUM(CASE WHEN ji.status_id = 3 THEN 1 ELSE 0 END) AS approved_count,
            CASE
                WHEN COUNT(*) = SUM(CASE WHEN ji.status_id = 3 THEN 1 ELSE 0 END) AND COUNT(*) > 0 THEN 'Approved'
                WHEN SUM(CASE WHEN ji.status_id = 3 THEN 1 ELSE 0 END) > 0 THEN 'Partial Approved'
                ELSE 'Draft'
            END AS status
        FROM jute_issue ji
        INNER JOIN branch_mst bm ON bm.branch_id = ji.branch_id
        WHERE bm.co_id = :co_id
        {search_clause}
        {date_clause}
        GROUP BY ji.issue_date, ji.branch_id, bm.branch_name
        ORDER BY ji.issue_date DESC, bm.branch_name
        LIMIT :limit OFFSET :offset
    """
    return text(sql)


def get_jute_issue_table_count_query(co_id: int, search: str = None):
    """
    Query to get total count of unique issue date+branch combinations for pagination.
    Uses branch_mst to filter by co_id since jute_issue doesn't have co_id column directly.
    Optional :date_from / :date_to bind params bound ji.issue_date.
    """
    search_clause = ""
    if search:
        search_clause = """
            AND (
                CAST(ji.issue_date AS CHAR) LIKE :search
                OR bm.branch_name LIKE :search
            )
        """

    date_clause = """
            AND (:date_from IS NULL OR ji.issue_date >= :date_from)
            AND (:date_to IS NULL OR ji.issue_date <= :date_to)
    """

    sql = f"""
        SELECT COUNT(*) AS total FROM (
            SELECT ji.issue_date, ji.branch_id
            FROM jute_issue ji
            INNER JOIN branch_mst bm ON bm.branch_id = ji.branch_id
            WHERE bm.co_id = :co_id
            {search_clause}
            {date_clause}
            GROUP BY ji.issue_date, ji.branch_id
        ) sub
    """
    return text(sql)


# =============================================================================
# JUTE ISSUE CREATE/EDIT QUERIES
# =============================================================================

def get_jute_issue_create_setup_query():
    """
    Query to get jute subgroups for issue dropdown.
    Returns subgroups from item_grp_mst where parent has item_type_id IN (2, 3).
    """
    sql = """
        SELECT 
            ig.item_grp_id,
            ig.item_grp_code,
            ig.item_grp_name
        FROM item_grp_mst ig
        INNER JOIN item_grp_mst parent ON parent.item_grp_id = ig.parent_grp_id
        WHERE parent.item_type_id IN (2, 3)
        AND ig.co_id = :co_id
        AND (ig.active = '1' OR ig.active IS NULL)
        ORDER BY ig.item_grp_name
    """
    return text(sql)


def get_jute_stock_outstanding_query():
    """
    Query to get available stock from vw_jute_stock_outstanding view.
    Uses actual_item_id and inward_date directly from the view.
    Joins with jute_mr_li only for jute_mr_id (not in view).
    Filters by branch_id and returns only records with positive balance quantity.
    Optionally filters by issue_date to exclude stock received after the issue date.
    """
    mr_num_expr = get_jute_mr_number_sql_expression(
        mr_no_column="vso.branch_mr_no",
        mr_date_column="jm.jute_mr_date",
        co_prefix_column="cm.co_prefix",
        branch_prefix_column="bm.branch_prefix"
    )

    sql = _group_path_cte() + f"""
        SELECT
            vso.jute_mr_li_id,
            vso.jute_gate_entry_no,
            vso.warehouse_name,
            vso.branch_id,
            vso.branch_mr_no,
            CASE
                WHEN vso.branch_mr_no IS NOT NULL
                THEN {mr_num_expr}
                ELSE NULL
            END AS mr_num,
            jml.jute_mr_id,
            im.item_grp_id AS item_grp_id,
            COALESCE(fgp.item_grp_name_path, ig.item_grp_name) AS jute_group_name,
            vso.actual_item_id AS item_id,
            im.item_name AS item_name,
            vso.actual_qty,
            vso.actual_weight,
            vso.actual_rate,
            vso.unit_conversion,
            vso.bal_qty AS balqty,
            vso.bal_weight AS balweight
        FROM vw_jute_stock_outstanding vso
        INNER JOIN jute_mr_li jml ON jml.jute_mr_li_id = vso.jute_mr_li_id
        INNER JOIN jute_mr jm ON jm.jute_mr_id = jml.jute_mr_id
        LEFT JOIN branch_mst bm ON bm.branch_id = vso.branch_id
        LEFT JOIN co_mst cm ON cm.co_id = bm.co_id
        LEFT JOIN item_mst im ON im.item_id = vso.actual_item_id
        LEFT JOIN item_grp_mst ig ON ig.item_grp_id = im.item_grp_id
        LEFT JOIN full_group_paths fgp ON fgp.item_grp_id = im.item_grp_id
        WHERE vso.branch_id = :branch_id
        AND vso.bal_qty > 0
        AND (vso.inward_date <= :issue_date)
        ORDER BY vso.branch_mr_no DESC, vso.jute_mr_li_id
    """
    return text(sql)


def get_jute_stock_outstanding_by_item_query():
    """
    Query to get available stock filtered by branch and item.
    Uses actual_item_id and inward_date directly from the view.
    Joins with jute_mr_li only for jute_mr_id (not in view).
    Optionally filters by issue_date to exclude stock received after the issue date.
    Uses recursive CTE for full group path names.
    """
    mr_num_expr = get_jute_mr_number_sql_expression(
        mr_no_column="vso.branch_mr_no",
        mr_date_column="jm.jute_mr_date",
        co_prefix_column="cm.co_prefix",
        branch_prefix_column="bm.branch_prefix"
    )

    sql = _group_path_cte() + f"""
        SELECT
            vso.jute_mr_li_id,
            vso.jute_gate_entry_no,
            vso.warehouse_name,
            vso.branch_id,
            vso.branch_mr_no,
            CASE
                WHEN vso.branch_mr_no IS NOT NULL
                THEN {mr_num_expr}
                ELSE NULL
            END AS mr_num,
            jml.jute_mr_id,
            im.item_grp_id AS item_grp_id,
            COALESCE(fgp.item_grp_name_path, ig.item_grp_name) AS jute_group_name,
            vso.actual_item_id AS item_id,
            im.item_name AS item_name,
            vso.actual_qty,
            vso.actual_weight,
            vso.actual_rate,
            vso.unit_conversion,
            vso.bal_qty AS balqty,
            vso.bal_weight AS balweight
        FROM vw_jute_stock_outstanding vso
        INNER JOIN jute_mr_li jml ON jml.jute_mr_li_id = vso.jute_mr_li_id
        INNER JOIN jute_mr jm ON jm.jute_mr_id = jml.jute_mr_id
        LEFT JOIN branch_mst bm ON bm.branch_id = vso.branch_id
        LEFT JOIN co_mst cm ON cm.co_id = bm.co_id
        LEFT JOIN item_mst im ON im.item_id = vso.actual_item_id
        LEFT JOIN item_grp_mst ig ON ig.item_grp_id = im.item_grp_id
        LEFT JOIN full_group_paths fgp ON fgp.item_grp_id = im.item_grp_id
        WHERE vso.branch_id = :branch_id
        AND vso.actual_item_id = :item_id
        AND vso.bal_qty > 0
        AND vso.inward_date <= :issue_date
        ORDER BY vso.branch_mr_no DESC, vso.jute_mr_li_id
    """
    return text(sql)


def get_jute_issues_by_date_query():
    """
    Query to get all jute issue line items for a specific branch and date.
    Used for the issue detail/edit page.

    Uses COALESCE to resolve item_id:
      1. ji.item_id  (new records store this directly)
      2. mrli.actual_item_id  (fallback from the MR line item)
    This ensures old records that only had jute_quality_id (now deprecated)
    still resolve to the correct item via the MR's actual_item_id.
    """
    mr_num_expr = get_jute_mr_number_sql_expression(
        mr_no_column="jm.branch_mr_no",
        mr_date_column="jm.jute_mr_date",
        co_prefix_column="cm.co_prefix",
        branch_prefix_column="bm.branch_prefix"
    )

    sql = _group_path_cte() + f"""
        SELECT
            ji.jute_issue_id,
            ji.branch_id,
            bm.branch_name,
            ji.issue_date,
            ji.status_id,
            COALESCE(sm.status_name, 'Draft') AS status,
            ji.jute_mr_li_id,
            mrli.jute_mr_id,
            jm.branch_mr_no,
            CASE
                WHEN jm.branch_mr_no IS NOT NULL
                THEN {mr_num_expr}
                ELSE NULL
            END AS mr_num,
            jm.jute_gate_entry_no,
            COALESCE(im.item_grp_id, im2.item_grp_id) AS item_grp_id,
            COALESCE(fgp.item_grp_name_path, ig.item_grp_name) AS jute_group_name,
            COALESCE(ji.item_id, mrli.actual_item_id) AS item_id,
            COALESCE(im.item_name, im2.item_name) AS item_name,
            ji.yarn_type_id,
            COALESCE(yim.item_name, jym.jute_yarn_name) AS yarn_type_name,
            ji.quantity,
            ji.weight,
            ji.unit_conversion,
            mrli.actual_rate,
            ji.issue_value,
            ji.updated_by,
            ji.update_date_time
        FROM jute_issue ji
        INNER JOIN branch_mst bm ON bm.branch_id = ji.branch_id
        INNER JOIN co_mst cm ON cm.co_id = bm.co_id
        LEFT JOIN status_mst sm ON sm.status_id = ji.status_id
        LEFT JOIN jute_mr_li mrli ON mrli.jute_mr_li_id = ji.jute_mr_li_id
        LEFT JOIN jute_mr jm ON jm.jute_mr_id = mrli.jute_mr_id
        LEFT JOIN item_mst im ON im.item_id = ji.item_id
        LEFT JOIN item_mst im2 ON im2.item_id = mrli.actual_item_id
        LEFT JOIN item_grp_mst ig ON ig.item_grp_id = COALESCE(im.item_grp_id, im2.item_grp_id)
        LEFT JOIN full_group_paths fgp ON fgp.item_grp_id = COALESCE(im.item_grp_id, im2.item_grp_id)
        LEFT JOIN jute_yarn_mst jym ON jym.jute_yarn_id = ji.yarn_type_id
        LEFT JOIN item_mst yim ON yim.item_id = jym.item_id
        WHERE ji.branch_id = :branch_id
        AND ji.issue_date = :issue_date
        AND bm.co_id = :co_id
        ORDER BY ji.jute_issue_id
    """
    return text(sql)


def get_yarn_types_query():
    """
    Query to get yarn options from jute_yarn_mst for issue dropdown.
    Uses jute_yarn_mst which contains specific yarn products (e.g., "10-SKWP-Gold").
    Resolves name from item_mst (via item_id) with fallback to jute_yarn_name.
    """
    sql = """
        SELECT 
            ym.jute_yarn_id AS jute_yarn_type_id,
            COALESCE(im.item_name, ym.jute_yarn_name) AS jute_yarn_type_name
        FROM jute_yarn_mst ym
        LEFT JOIN item_mst im ON im.item_id = ym.item_id
        WHERE ym.co_id = :co_id
        ORDER BY COALESCE(im.item_name, ym.jute_yarn_name)
    """
    return text(sql)


# =============================================================================
# BATCH DAILY ASSIGN QUERIES
# =============================================================================

def get_batch_daily_assign_table_query(search: str = None):
    """
    Query to get batch daily assignments aggregated by date and branch.
    Groups by assign_date and branch_id, counts assignments, determines status.
    """
    search_clause = ""
    if search:
        search_clause = """
            AND (
                CAST(bda.assign_date AS CHAR) LIKE :search
                OR bm.branch_name LIKE :search
            )
        """

    date_clause = """
            AND (:date_from IS NULL OR bda.assign_date >= :date_from)
            AND (:date_to IS NULL OR bda.assign_date <= :date_to)
    """

    sql = f"""
        SELECT
            bda.assign_date,
            bda.branch_id,
            bm.branch_name,
            COUNT(*) AS total_assignments,
            SUM(CASE WHEN bda.status_id = 3 THEN 1 ELSE 0 END) AS approved_count,
            CASE
                WHEN COUNT(*) = SUM(CASE WHEN bda.status_id = 3 THEN 1 ELSE 0 END) AND COUNT(*) > 0 THEN 'Approved'
                WHEN SUM(CASE WHEN bda.status_id = 3 THEN 1 ELSE 0 END) > 0 THEN 'Partial Approved'
                ELSE 'Draft'
            END AS status
        FROM jute_batch_daily_assign bda
        INNER JOIN branch_mst bm ON bm.branch_id = bda.branch_id
        WHERE bm.branch_id = :branch_id
        {search_clause}
        {date_clause}
        GROUP BY bda.assign_date, bda.branch_id, bm.branch_name
        ORDER BY bda.assign_date DESC, bm.branch_name
        LIMIT :limit OFFSET :offset
    """
    return text(sql)


def get_batch_daily_assign_table_count_query(search: str = None):
    """
    Count of unique assign_date+branch combinations for pagination.
    Optional :date_from / :date_to bind params bound bda.assign_date.
    """
    search_clause = ""
    if search:
        search_clause = """
            AND (
                CAST(bda.assign_date AS CHAR) LIKE :search
                OR bm.branch_name LIKE :search
            )
        """

    date_clause = """
            AND (:date_from IS NULL OR bda.assign_date >= :date_from)
            AND (:date_to IS NULL OR bda.assign_date <= :date_to)
    """

    sql = f"""
        SELECT COUNT(*) AS total FROM (
            SELECT bda.assign_date, bda.branch_id
            FROM jute_batch_daily_assign bda
            INNER JOIN branch_mst bm ON bm.branch_id = bda.branch_id
            WHERE bm.branch_id = :branch_id
            {search_clause}
            {date_clause}
            GROUP BY bda.assign_date, bda.branch_id
        ) sub
    """
    return text(sql)


def get_batch_daily_assigns_by_date_query():
    """
    All assignments for a specific date+branch, with yarn type and batch plan names.
    """
    sql = """
        SELECT
            bda.batch_daily_assign_id,
            bda.branch_id,
            bda.assign_date,
            bda.jute_yarn_id,
            ym.jute_yarn_name AS yarn_type_name,
            bda.batch_plan_id,
            bp.plan_name,
            bda.status_id,
            bda.updated_by,
            bda.updated_date_time
        FROM jute_batch_daily_assign bda
        LEFT JOIN jute_yarn_mst ym ON ym.jute_yarn_id = bda.jute_yarn_id
        LEFT JOIN jute_batch_plan bp ON bp.batch_plan_id = bda.batch_plan_id
        WHERE bda.branch_id = :branch_id
          AND bda.assign_date = :assign_date
        ORDER BY ym.jute_yarn_name
    """
    return text(sql)


def get_batch_daily_assign_create_setup_query():
    """
    Setup data for creating assignments: yarn types for the company.
    """
    sql = """
        SELECT jute_yarn_id, jute_yarn_name
        FROM jute_yarn_mst
        WHERE co_id = :co_id
        ORDER BY jute_yarn_name
    """
    return text(sql)


def get_batch_plans_for_branch_query():
    """
    Get batch plans available for a specific branch.
    """
    sql = """
        SELECT bp.batch_plan_id, bp.plan_name
        FROM jute_batch_plan bp
        WHERE bp.branch_id = :branch_id
        ORDER BY bp.plan_name
    """
    return text(sql)


def get_batch_daily_assign_max_date_query():
    """
    Get latest assignment date for a branch to auto-increment.
    """
    sql = """
        SELECT MAX(assign_date) AS max_date
        FROM jute_batch_daily_assign
        WHERE branch_id = :branch_id
    """
    return text(sql)


# =============================================================================
# APPROVAL UTILITY QUERY FUNCTIONS
# =============================================================================
# These functions are used by the shared approval utility (src/common/approval_utils.py)
# to integrate jute MR and jute PO with the multi-level approval workflow.


def get_mr_with_approval_info():
    """Get jute MR details required by the shared approval utility.

    Returns: status_id, approval_level, branch_id (required by process_approval).
    """
    sql = """SELECT
        jm.jute_mr_id,
        jm.status_id,
        jm.approval_level,
        jm.branch_id,
        jm.party_id,
        jm.party_branch_id,
        jm.jute_mr_date,
        jm.branch_mr_no
    FROM jute_mr jm
    WHERE jm.jute_mr_id = :jute_mr_id;"""
    return text(sql)


def update_mr_status():
    """Update jute MR status and approval level.

    Used by the shared approval utility to transition MR status during
    the approval workflow.
    """
    sql = """UPDATE jute_mr SET
        status_id = :status_id,
        approval_level = :approval_level,
        updated_by = :updated_by,
        updated_date_time = :updated_date_time
    WHERE jute_mr_id = :jute_mr_id;"""
    return text(sql)


def get_jute_po_with_approval_info():
    """Get jute PO details required by the shared approval utility.

    Returns: status_id, approval_level, branch_id (required by process_approval).
    Also joins branch_mst to get co_id for validation.
    """
    sql = """SELECT
        jp.jute_po_id,
        jp.status_id,
        jp.approval_level,
        jp.branch_id,
        jp.po_date,
        jp.po_no,
        bm.co_id
    FROM jute_po jp
    LEFT JOIN branch_mst bm ON bm.branch_id = jp.branch_id
    WHERE jp.jute_po_id = :jute_po_id;"""
    return text(sql)


def update_jute_po_status():
    """Update jute PO status and approval level.

    Used by the shared approval utility to transition Jute PO status during
    the approval workflow.
    """
    sql = """UPDATE jute_po SET
        status_id = :status_id,
        approval_level = :approval_level,
        updated_by = :updated_by,
        updated_date_time = :updated_date_time
    WHERE jute_po_id = :jute_po_id;"""
    return text(sql)
