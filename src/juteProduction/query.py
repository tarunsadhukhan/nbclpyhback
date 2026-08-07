"""Raw SQL builders for the Jute Production module (transactional reads)."""

from sqlalchemy import text

from src.juteProduction.constants import JUTE_ITEM_TYPE_IDS, SPREADER_MACHINE_TYPE_NAME


def get_spreader_machines_query():
    """Spreader machines for a company, with their snapshot wt_per_roll (if any).

    Company-scoped via the machine's dept -> branch -> branch_mst.co_id chain (a
    machine belongs to exactly one branch); the attr join is branch-scoped so a
    weight row saved against another branch's machine can never surface here."""
    return text(
        """
        SELECT
            m.machine_id,
            m.machine_name,
            m.mech_code,
            d.dept_id,
            d.dept_desc AS dept_name,
            d.branch_id,
            COALESCE(sma.wt_per_roll, 0) AS wt_per_roll,
            sma.spreader_machine_attr_id
        FROM machine_mst m
        INNER JOIN machine_type_mst mt ON mt.machine_type_id = m.machine_type_id
        INNER JOIN dept_mst d ON d.dept_id = m.dept_id
        INNER JOIN branch_mst b ON b.branch_id = d.branch_id AND b.co_id = :co_id
        LEFT JOIN spreader_machine_attr sma
               ON sma.machine_id = m.machine_id AND sma.branch_id = d.branch_id AND sma.active = 1
        WHERE m.active = 1
          AND mt.active = 1
          AND mt.machine_type_name = :spreader_type
          AND (:branch_id IS NULL OR d.branch_id = :branch_id)
        ORDER BY m.machine_name
        """
    )


def get_active_bins_query():
    return text(
        """
        SELECT bin_id, bin_code, bin_no, description, branch_id
        FROM spreader_bin_mst
        WHERE co_id = :co_id AND active = 1
          AND (:branch_id IS NULL OR branch_id = :branch_id)
        ORDER BY bin_code
        """
    )


def get_jute_items_query():
    """All active jute / jute-waste items for the company (per the spec — no 90d filter)."""
    placeholders = ",".join(str(int(x)) for x in JUTE_ITEM_TYPE_IDS)
    return text(
        f"""
        SELECT i.item_id, i.item_code, i.item_name, g.item_grp_id, g.item_grp_name, g.item_type_id
        FROM item_mst i
        INNER JOIN item_grp_mst g ON g.item_grp_id = i.item_grp_id
        WHERE i.active = 1
          AND g.co_id = :co_id
          AND g.item_type_id IN ({placeholders})
        ORDER BY i.item_name
        """
    )


def get_item_maturity_map_query():
    return text(
        """
        SELECT item_id, maturity_hours
        FROM item_maturity_mst
        WHERE co_id = :co_id AND active = 1
        """
    )


def get_entries_by_date_query():
    return text(
        """
        SELECT
            p.spreader_prod_entry_id,
            p.entry_id_grp,
            p.bin_id,
            b.bin_code,
            p.entry_date,
            p.entry_time,
            p.entry_dt,
            p.spell,
            p.machine_id,
            m.machine_name,
            m.mech_code,
            p.item_id,
            i.item_name,
            p.no_of_rolls,
            p.wt_per_roll,
            (p.no_of_rolls * p.wt_per_roll) AS produced_kg,
            p.trolley_no,
            p.remarks
        FROM spreader_prod_entry p
        LEFT JOIN spreader_bin_mst b ON b.bin_id = p.bin_id
        LEFT JOIN machine_mst m ON m.machine_id = p.machine_id
        LEFT JOIN dept_mst d ON d.dept_id = m.dept_id
        LEFT JOIN item_mst i ON i.item_id = p.item_id
        WHERE p.co_id = :co_id
          AND p.active = 1
          AND p.entry_date = :d
          AND (:branch_id IS NULL OR COALESCE(p.branch_id, d.branch_id) = :branch_id)
        ORDER BY p.spreader_prod_entry_id DESC
        """
    )


def get_issues_by_date_query():
    return text(
        """
        SELECT
            r.spreader_roll_issue_id,
            r.entry_id_grp,
            r.issue_date,
            r.issue_time,
            r.issue_dt,
            r.spell,
            r.no_of_rolls,
            r.wt_per_roll,
            (r.no_of_rolls * r.wt_per_roll) AS issued_kg,
            r.breaker_inter_no,
            r.remarks,
            pg.bin_id,
            pg.bin_code,
            pg.item_id,
            pg.item_name
        FROM spreader_roll_issue r
        LEFT JOIN (
            SELECT
                p.entry_id_grp,
                MIN(p.bin_id) AS bin_id,
                MIN(b.bin_code) AS bin_code,
                MIN(p.item_id) AS item_id,
                MIN(i.item_name) AS item_name,
                MIN(COALESCE(p.branch_id, d.branch_id)) AS branch_id
            FROM spreader_prod_entry p
            LEFT JOIN spreader_bin_mst b ON b.bin_id = p.bin_id
            LEFT JOIN machine_mst m ON m.machine_id = p.machine_id
            LEFT JOIN dept_mst d ON d.dept_id = m.dept_id
            LEFT JOIN item_mst i ON i.item_id = p.item_id
            WHERE p.co_id = :co_id AND p.active = 1
            GROUP BY p.entry_id_grp
        ) pg ON pg.entry_id_grp = r.entry_id_grp
        WHERE r.co_id = :co_id
          AND r.active = 1
          AND r.issue_date = :d
          AND (:branch_id IS NULL OR COALESCE(r.branch_id, pg.branch_id) = :branch_id)
        ORDER BY r.spreader_roll_issue_id DESC
        """
    )


def get_bins_with_stock_query():
    """Bin/group/item-level current stock (rolls + weight + avg entry time)."""
    return text(
        """
        SELECT
            p.bin_id,
            b.bin_code,
            p.entry_id_grp,
            p.item_id,
            i.item_name,
            p.produced_rolls,
            p.produced_kg,
            COALESCE(iss.issued_rolls, 0) AS issued_rolls,
            COALESCE(iss.issued_kg, 0) AS issued_kg,
            (p.produced_rolls - COALESCE(iss.issued_rolls, 0)) AS current_rolls,
            (p.produced_kg - COALESCE(iss.issued_kg, 0)) AS current_kg,
            p.avg_entry_dt
        FROM (
            SELECT
                pe.bin_id,
                pe.entry_id_grp,
                pe.item_id,
                SUM(pe.no_of_rolls) AS produced_rolls,
                SUM(pe.no_of_rolls * pe.wt_per_roll) AS produced_kg,
                FROM_UNIXTIME(AVG(UNIX_TIMESTAMP(pe.entry_dt))) AS avg_entry_dt,
                MAX(COALESCE(pe.branch_id, d.branch_id)) AS branch_id
            FROM spreader_prod_entry pe
            LEFT JOIN machine_mst m ON m.machine_id = pe.machine_id
            LEFT JOIN dept_mst d ON d.dept_id = m.dept_id
            WHERE pe.co_id = :co_id AND pe.active = 1
            GROUP BY pe.bin_id, pe.entry_id_grp, pe.item_id
        ) p
        LEFT JOIN spreader_bin_mst b ON b.bin_id = p.bin_id
        LEFT JOIN item_mst i ON i.item_id = p.item_id
        LEFT JOIN (
            SELECT entry_id_grp,
                   SUM(no_of_rolls) AS issued_rolls,
                   SUM(no_of_rolls * wt_per_roll) AS issued_kg
            FROM spreader_roll_issue
            WHERE co_id = :co_id AND active = 1
            GROUP BY entry_id_grp
        ) iss ON iss.entry_id_grp = p.entry_id_grp
        WHERE (p.produced_rolls - COALESCE(iss.issued_rolls, 0)) > 0
          AND (:branch_id IS NULL OR p.branch_id = :branch_id)
        ORDER BY p.bin_id, p.entry_id_grp
        """
    )


def get_available_weights_for_group_query():
    """Per-weight stock for a single entry_id_grp."""
    return text(
        """
        SELECT
            p.wt_per_roll,
            p.produced_rolls,
            COALESCE(i.issued_rolls, 0) AS issued_rolls,
            (p.produced_rolls - COALESCE(i.issued_rolls, 0)) AS available_rolls
        FROM (
            SELECT wt_per_roll, SUM(no_of_rolls) AS produced_rolls
            FROM spreader_prod_entry
            WHERE co_id = :co_id AND active = 1 AND entry_id_grp = :grp
            GROUP BY wt_per_roll
        ) p
        LEFT JOIN (
            SELECT wt_per_roll, SUM(no_of_rolls) AS issued_rolls
            FROM spreader_roll_issue
            WHERE co_id = :co_id AND active = 1 AND entry_id_grp = :grp
            GROUP BY wt_per_roll
        ) i ON i.wt_per_roll = p.wt_per_roll
        WHERE (p.produced_rolls - COALESCE(i.issued_rolls, 0)) > 0
        ORDER BY p.wt_per_roll
        """
    )


def get_group_details_for_issue_query():
    """Resolve item / bin / first-entry datetime for an entry_id_grp."""
    return text(
        """
        SELECT
            MIN(p.item_id) AS item_id,
            MIN(p.bin_id) AS bin_id,
            MIN(b.bin_code) AS bin_code,
            MIN(i.item_name) AS item_name,
            MIN(p.entry_dt) AS first_entry_dt,
            MIN(COALESCE(p.branch_id, d.branch_id)) AS branch_id
        FROM spreader_prod_entry p
        LEFT JOIN spreader_bin_mst b ON b.bin_id = p.bin_id
        LEFT JOIN machine_mst m ON m.machine_id = p.machine_id
        LEFT JOIN dept_mst d ON d.dept_id = m.dept_id
        LEFT JOIN item_mst i ON i.item_id = p.item_id
        WHERE p.co_id = :co_id AND p.active = 1 AND p.entry_id_grp = :grp
        """
    )


def get_bins_with_stock_for_issue_query():
    """Bins that still have at least one open group (used to populate the Issue form's bin dropdown)."""
    return text(
        """
        SELECT
            p.bin_id,
            b.bin_code,
            p.entry_id_grp,
            p.item_id,
            i.item_name,
            (p.produced_rolls - COALESCE(iss.issued_rolls, 0)) AS current_rolls
        FROM (
            SELECT
                pe.bin_id, pe.entry_id_grp, pe.item_id,
                SUM(pe.no_of_rolls) AS produced_rolls,
                MAX(COALESCE(pe.branch_id, d.branch_id)) AS branch_id
            FROM spreader_prod_entry pe
            LEFT JOIN machine_mst m ON m.machine_id = pe.machine_id
            LEFT JOIN dept_mst d ON d.dept_id = m.dept_id
            WHERE pe.co_id = :co_id AND pe.active = 1
            GROUP BY pe.bin_id, pe.entry_id_grp, pe.item_id
        ) p
        LEFT JOIN spreader_bin_mst b ON b.bin_id = p.bin_id
        LEFT JOIN item_mst i ON i.item_id = p.item_id
        LEFT JOIN (
            SELECT entry_id_grp, SUM(no_of_rolls) AS issued_rolls
            FROM spreader_roll_issue
            WHERE co_id = :co_id AND active = 1
            GROUP BY entry_id_grp
        ) iss ON iss.entry_id_grp = p.entry_id_grp
        WHERE (p.produced_rolls - COALESCE(iss.issued_rolls, 0)) > 0
          AND (:branch_id IS NULL OR p.branch_id = :branch_id)
        ORDER BY b.bin_code, p.entry_id_grp DESC
        """
    )
