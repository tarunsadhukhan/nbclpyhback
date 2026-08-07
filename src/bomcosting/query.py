from sqlalchemy.sql import text


# ═══════════════════════════════════════════════════════════════
# COST ELEMENT QUERIES
# ═══════════════════════════════════════════════════════════════

def get_cost_element_tree_query():
    """Full cost element hierarchy via recursive CTE.
    Params: :co_id
    """
    sql = """
    WITH RECURSIVE element_tree AS (
        SELECT cost_element_id, element_code, element_name,
               parent_element_id, element_level, element_type,
               default_basis, is_leaf, sort_order, element_desc, active
        FROM cost_element_mst
        WHERE parent_element_id IS NULL
          AND co_id = :co_id AND active = 1
        UNION ALL
        SELECT c.cost_element_id, c.element_code, c.element_name,
               c.parent_element_id, c.element_level, c.element_type,
               c.default_basis, c.is_leaf, c.sort_order, c.element_desc, c.active
        FROM cost_element_mst c
        INNER JOIN element_tree p ON c.parent_element_id = p.cost_element_id
        WHERE c.co_id = :co_id AND c.active = 1
    )
    SELECT * FROM element_tree
    ORDER BY sort_order, element_level, element_code;
    """
    return text(sql)


def get_cost_element_flat_list_query():
    """Flat list of cost elements with optional search.
    Params: :co_id, :search (nullable)
    """
    sql = """
    SELECT cost_element_id, element_code, element_name,
           parent_element_id, element_level, element_type,
           default_basis, is_leaf, sort_order, element_desc, active
    FROM cost_element_mst
    WHERE co_id = :co_id AND active = 1
      AND (:search IS NULL OR element_code LIKE :search OR element_name LIKE :search)
    ORDER BY sort_order, element_level, element_code;
    """
    return text(sql)


def get_cost_element_children_query():
    """Direct children of a given parent element.
    Params: :parent_element_id, :co_id
    """
    sql = """
    SELECT cost_element_id, element_code, element_name,
           parent_element_id, element_level, element_type,
           default_basis, is_leaf, sort_order
    FROM cost_element_mst
    WHERE parent_element_id = :parent_element_id
      AND co_id = :co_id AND active = 1
    ORDER BY sort_order;
    """
    return text(sql)


def get_cost_element_ancestors_query():
    """Walk UP from a given element to root. Returns ancestors ordered deepest-first.
    Params: :cost_element_id, :co_id
    """
    sql = """
    WITH RECURSIVE ancestors AS (
        SELECT cost_element_id, parent_element_id, element_level
        FROM cost_element_mst
        WHERE cost_element_id = :cost_element_id AND co_id = :co_id
        UNION ALL
        SELECT p.cost_element_id, p.parent_element_id, p.element_level
        FROM cost_element_mst p
        INNER JOIN ancestors a ON a.parent_element_id = p.cost_element_id
        WHERE p.co_id = :co_id
    )
    SELECT cost_element_id, parent_element_id, element_level
    FROM ancestors
    WHERE cost_element_id != :cost_element_id
    ORDER BY element_level DESC;
    """
    return text(sql)


def get_cost_element_template_query():
    """Select all template elements (co_id = 0) for seeding.
    Params: none
    """
    sql = """
    SELECT cost_element_id, element_code, element_name,
           parent_element_id, element_level, element_type,
           default_basis, is_leaf, sort_order, element_desc
    FROM cost_element_mst
    WHERE co_id = 0 AND active = 1
    ORDER BY element_level, sort_order;
    """
    return text(sql)


def get_cost_element_descendant_ids_query():
    """Get all descendant IDs of a given element (for cascade operations).
    Params: :cost_element_id, :co_id
    """
    sql = """
    WITH RECURSIVE descendants AS (
        SELECT cost_element_id
        FROM cost_element_mst
        WHERE parent_element_id = :cost_element_id AND co_id = :co_id
        UNION ALL
        SELECT c.cost_element_id
        FROM cost_element_mst c
        INNER JOIN descendants d ON c.parent_element_id = d.cost_element_id
        WHERE c.co_id = :co_id
    )
    SELECT cost_element_id FROM descendants;
    """
    return text(sql)


# ═══════════════════════════════════════════════════════════════
# BOM HEADER QUERIES
# ═══════════════════════════════════════════════════════════════

def get_bom_costing_list_query():
    """List bom_hdr rows with item details and current snapshot totals.
    Params: :co_id, :search (nullable)
    """
    sql = """
    SELECT
        bh.bom_hdr_id,
        bh.item_id,
        im.item_code,
        vip.full_item_code,
        im.item_name,
        bh.bom_version,
        bh.version_label,
        bh.status_id,
        sm.status_name,
        bh.effective_from,
        bh.effective_to,
        bh.is_current,
        bh.cost_basis_qty,
        bh.remarks,
        bh.updated_date_time,
        COALESCE(snap.material_cost, 0) AS material_cost,
        COALESCE(snap.conversion_cost, 0) AS conversion_cost,
        COALESCE(snap.overhead_cost, 0) AS overhead_cost,
        COALESCE(snap.total_cost, 0) AS total_cost,
        COALESCE(snap.cost_per_unit, 0) AS cost_per_unit,
        snap.computed_at AS last_computed_at,
        snap.status AS snapshot_status
    FROM item_bom_hdr_mst bh
    INNER JOIN item_mst im ON im.item_id = bh.item_id
    LEFT JOIN vw_item_with_group_path AS vip ON vip.item_id = im.item_id
    LEFT JOIN status_mst sm ON sm.status_id = bh.status_id
    LEFT JOIN bom_cost_snapshot snap
        ON snap.bom_hdr_id = bh.bom_hdr_id
        AND snap.co_id = bh.co_id
        AND snap.is_current = 1
        AND snap.active = 1
    WHERE bh.co_id = :co_id AND bh.active = 1
      AND (:search IS NULL OR im.item_code LIKE :search OR im.item_name LIKE :search OR vip.full_item_code LIKE :search)
    ORDER BY bh.updated_date_time DESC;
    """
    return text(sql)


def get_bom_costing_detail_query():
    """Single BOM header with item details.
    Params: :bom_hdr_id, :co_id
    """
    sql = """
    SELECT
        bh.bom_hdr_id,
        bh.item_id,
        im.item_code,
        vip.full_item_code,
        im.item_name,
        bh.bom_version,
        bh.version_label,
        bh.status_id,
        sm.status_name,
        bh.effective_from,
        bh.effective_to,
        bh.is_current,
        bh.cost_basis_qty,
        bh.remarks,
        bh.co_id,
        bh.updated_by,
        bh.updated_date_time
    FROM item_bom_hdr_mst bh
    INNER JOIN item_mst im ON im.item_id = bh.item_id
    LEFT JOIN vw_item_with_group_path AS vip ON vip.item_id = im.item_id
    LEFT JOIN status_mst sm ON sm.status_id = bh.status_id
    WHERE bh.bom_hdr_id = :bom_hdr_id
      AND bh.co_id = :co_id
      AND bh.active = 1;
    """
    return text(sql)


def get_bom_cost_entries_for_hdr_query():
    """All active cost entries for a BOM, joined with cost element info.
    Params: :bom_hdr_id, :co_id
    """
    sql = """
    SELECT
        bce.bom_cost_entry_id,
        bce.bom_hdr_id,
        bce.cost_element_id,
        bce.amount,
        bce.source,
        bce.qty,
        bce.rate,
        bce.basis_override,
        bce.effective_date,
        bce.entered_by,
        bce.remarks,
        ce.element_code,
        ce.element_name,
        ce.parent_element_id,
        ce.element_level,
        ce.element_type,
        ce.default_basis,
        ce.is_leaf,
        ce.sort_order
    FROM bom_cost_entry bce
    INNER JOIN cost_element_mst ce ON ce.cost_element_id = bce.cost_element_id
    WHERE bce.bom_hdr_id = :bom_hdr_id
      AND bce.co_id = :co_id
      AND bce.active = 1
      AND ce.active = 1
    ORDER BY ce.sort_order, ce.element_level, ce.element_code;
    """
    return text(sql)


def get_next_bom_version_query():
    """Get next version number for a given item.
    Params: :item_id, :co_id
    """
    sql = """
    SELECT COALESCE(MAX(bom_version), 0) + 1 AS next_version
    FROM item_bom_hdr_mst
    WHERE item_id = :item_id AND co_id = :co_id;
    """
    return text(sql)


def get_items_for_bom_costing_dropdown_query():
    """Items dropdown for BOM costing creation.
    Params: :co_id, :search (nullable)
    """
    sql = """
    SELECT
        im.item_id,
        im.item_code,
        vip.full_item_code,
        im.item_name,
        ig.item_grp_name
    FROM item_mst im
    LEFT JOIN item_grp_mst ig ON ig.item_grp_id = im.item_grp_id
    LEFT JOIN vw_item_with_group_path AS vip ON vip.item_id = im.item_id
    WHERE ig.co_id = :co_id
      AND im.active = 1
      AND (:search IS NULL OR im.item_code LIKE :search OR im.item_name LIKE :search OR vip.full_item_code LIKE :search)
    ORDER BY im.item_code
    LIMIT 50;
    """
    return text(sql)


# ═══════════════════════════════════════════════════════════════
# BOM COST ENTRY QUERIES
# ═══════════════════════════════════════════════════════════════

def get_children_entries_sum_query():
    """SUM and COUNT of active child entries for a given parent element in a BOM.
    Params: :bom_hdr_id, :parent_element_id, :co_id
    """
    sql = """
    SELECT
        COALESCE(SUM(bce.amount), 0) AS total,
        COUNT(bce.bom_cost_entry_id) AS entry_count
    FROM bom_cost_entry bce
    INNER JOIN cost_element_mst ce ON ce.cost_element_id = bce.cost_element_id
    WHERE ce.parent_element_id = :parent_element_id
      AND bce.bom_hdr_id = :bom_hdr_id
      AND bce.co_id = :co_id
      AND bce.active = 1
      AND ce.active = 1;
    """
    return text(sql)


# ═══════════════════════════════════════════════════════════════
# SNAPSHOT QUERIES
# ═══════════════════════════════════════════════════════════════

def get_bom_cost_snapshot_list_query():
    """Snapshot history for a BOM.
    Params: :bom_hdr_id, :co_id
    """
    sql = """
    SELECT
        bom_cost_snapshot_id,
        bom_hdr_id,
        material_cost,
        conversion_cost,
        overhead_cost,
        total_cost,
        cost_per_unit,
        computed_at,
        computed_by,
        is_current,
        status
    FROM bom_cost_snapshot
    WHERE bom_hdr_id = :bom_hdr_id
      AND co_id = :co_id
      AND active = 1
    ORDER BY computed_at DESC;
    """
    return text(sql)


def get_bom_cost_snapshot_detail_query():
    """Single snapshot with detail JSON.
    Params: :bom_cost_snapshot_id, :co_id
    """
    sql = """
    SELECT
        bom_cost_snapshot_id,
        bom_hdr_id,
        material_cost,
        conversion_cost,
        overhead_cost,
        total_cost,
        cost_per_unit,
        detail_snapshot,
        computed_at,
        computed_by,
        is_current,
        status
    FROM bom_cost_snapshot
    WHERE bom_cost_snapshot_id = :bom_cost_snapshot_id
      AND co_id = :co_id
      AND active = 1;
    """
    return text(sql)


def get_bom_cost_summary_view_query():
    """Query the vw_bom_cost_summary reporting view.
    Params: :co_id, :item_id (nullable), :bom_hdr_id (nullable)
    """
    sql = """
    SELECT *
    FROM vw_bom_cost_summary
    WHERE co_id = :co_id
      AND (:item_id IS NULL OR item_id = :item_id)
      AND (:bom_hdr_id IS NULL OR bom_hdr_id = :bom_hdr_id)
    ORDER BY item_code, bom_version;
    """
    return text(sql)


def mark_previous_snapshots_superseded_query():
    """Mark all current snapshots for a BOM as superseded.
    Params: :bom_hdr_id, :co_id
    """
    sql = """
    UPDATE bom_cost_snapshot
    SET is_current = 0, status = 'superseded'
    WHERE bom_hdr_id = :bom_hdr_id
      AND co_id = :co_id
      AND is_current = 1;
    """
    return text(sql)


# ═══════════════════════════════════════════════════════════════
# STANDARD RATE CARD QUERIES
# ═══════════════════════════════════════════════════════════════

def get_std_rate_card_list_query():
    """List rate cards with polymorphic reference names resolved.
    Params: :co_id, :rate_type (nullable), :reference_type (nullable)
    """
    sql = """
    SELECT
        rc.std_rate_card_id,
        rc.rate_type,
        rc.reference_id,
        rc.reference_type,
        rc.rate,
        rc.uom,
        rc.valid_from,
        rc.valid_to,
        rc.active,
        COALESCE(mm.machine_name, dm.dept_desc, ce.element_name, '') AS reference_name
    FROM std_rate_card rc
    LEFT JOIN machine_mst mm
        ON rc.reference_type = 'machine' AND rc.reference_id = mm.machine_id
    LEFT JOIN dept_mst dm
        ON rc.reference_type = 'dept' AND rc.reference_id = dm.dept_id
    LEFT JOIN cost_element_mst ce
        ON rc.reference_type = 'cost_element' AND rc.reference_id = ce.cost_element_id
    WHERE rc.co_id = :co_id
      AND (:rate_type IS NULL OR rc.rate_type = :rate_type)
      AND (:reference_type IS NULL OR rc.reference_type = :reference_type)
    ORDER BY rc.rate_type, rc.valid_from DESC;
    """
    return text(sql)


def get_std_rate_card_current_query():
    """Get the currently valid rate card for a type + reference.
    Params: :co_id, :rate_type, :reference_type, :reference_id
    """
    sql = """
    SELECT
        std_rate_card_id, rate_type, reference_id, reference_type,
        rate, uom, valid_from, valid_to
    FROM std_rate_card
    WHERE co_id = :co_id
      AND rate_type = :rate_type
      AND ((:reference_type IS NULL AND reference_type IS NULL) OR reference_type = :reference_type)
      AND ((:reference_id IS NULL AND reference_id IS NULL) OR reference_id = :reference_id)
      AND active = 1
      AND valid_from <= CURDATE()
      AND (valid_to IS NULL OR valid_to >= CURDATE())
    ORDER BY valid_from DESC
    LIMIT 1;
    """
    return text(sql)


def get_std_rate_cards_for_bom_apply_query():
    """Get all current rate cards for pre-populating a BOM cost sheet.
    Params: :co_id
    """
    sql = """
    SELECT
        std_rate_card_id, rate_type, reference_id, reference_type,
        rate, uom, valid_from, valid_to
    FROM std_rate_card
    WHERE co_id = :co_id
      AND active = 1
      AND valid_from <= CURDATE()
      AND (valid_to IS NULL OR valid_to >= CURDATE())
    ORDER BY rate_type, valid_from DESC;
    """
    return text(sql)
