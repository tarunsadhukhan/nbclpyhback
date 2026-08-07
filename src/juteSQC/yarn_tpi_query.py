"""Raw SQL builders for R-08-17 Yarn TPI & TPI CV% (jute SQC module).

HEADER + DETAIL (20-reading twist-uniformity study). Clones the
jute_sqc_spinning_qr_cv / _dtl builders in spinning_sqc_query.py: header + detail
pair, insert-only (duplicates allowed), soft-delete the header only (detail follows
the active-header join). count_lbs / std_tpi / tp_value are snapshotted on the header;
stats are computed server-side at read from the stored readings.

Branch-wise (like the carding reports): by_date + table reads are STRICTLY branch-scoped
((:branch_id IS NULL OR branch_id = :branch_id) — no NULL-branch leak). The machine picker
(get_card_section_machines_query) and yarn-quality picker (get_yarn_qualities_query) are
reused by the router; only the genuinely-new builders live here.
"""

from sqlalchemy import text, bindparam


def get_yarn_tpi_by_date_query():
    """Active TPI study headers for a co/entry_date (branch optional, strict), labelled."""
    return text(
        """
        SELECT
            h.yarn_tpi_id,
            h.co_id,
            h.branch_id,
            h.entry_date,
            h.mc_id,
            m.mech_code,
            m.machine_name,
            h.item_id,
            im.item_code,
            im.item_name,
            h.count_lbs,
            h.std_tpi,
            h.tp_value,
            h.prepared_by,
            h.updated_date_time
        FROM jute_sqc_yarn_tpi h
        LEFT JOIN machine_mst m ON m.machine_id = h.mc_id
        LEFT JOIN item_mst im ON im.item_id = h.item_id
        WHERE h.co_id = :co_id
          AND h.entry_date = :entry_date
          AND h.active = 1
          AND (:branch_id IS NULL OR h.branch_id = :branch_id)
        ORDER BY im.item_name, h.yarn_tpi_id
        """
    )


def get_yarn_tpi_dtl_query():
    """Reading rows for a set of study ids (single round-trip, expanding bind)."""
    return text(
        """
        SELECT yarn_tpi_id, reading_no, reading_val
        FROM jute_sqc_yarn_tpi_dtl
        WHERE yarn_tpi_id IN :ids
        ORDER BY yarn_tpi_id, reading_no
        """
    ).bindparams(bindparam("ids", expanding=True))


def insert_yarn_tpi_header_query():
    """Insert a fresh active TPI study header (insert-only; read lastrowid)."""
    return text(
        """
        INSERT INTO jute_sqc_yarn_tpi
            (co_id, branch_id, entry_date, mc_id, item_id,
             count_lbs, std_tpi, tp_value, prepared_by, active, updated_by)
        VALUES
            (:co_id, :branch_id, :entry_date, :mc_id, :item_id,
             :count_lbs, :std_tpi, :tp_value, :prepared_by, 1, :updated_by)
        """
    )


def insert_yarn_tpi_dtl_query():
    """Insert one reading detail row for a TPI study."""
    return text(
        """
        INSERT INTO jute_sqc_yarn_tpi_dtl
            (yarn_tpi_id, reading_no, reading_val)
        VALUES
            (:hdr_id, :reading_no, :reading_val)
        """
    )


def get_yarn_tpi_table_query(search: str = None):
    """Paginated active TPI study headers for a co (branch optional, strict), labelled."""
    search_filter = ""
    if search:
        search_filter = """
            AND (
                im.item_name LIKE :search
                OR m.machine_name LIKE :search
                OR m.mech_code LIKE :search
                OR h.prepared_by LIKE :search
            )
        """

    sql = f"""
        SELECT
            h.yarn_tpi_id,
            h.co_id,
            h.branch_id,
            h.entry_date,
            h.mc_id,
            m.machine_name,
            m.mech_code,
            h.item_id,
            im.item_name AS yarn_quality,
            im.item_code,
            h.count_lbs,
            h.std_tpi,
            h.tp_value,
            h.prepared_by,
            h.updated_date_time
        FROM jute_sqc_yarn_tpi h
        LEFT JOIN machine_mst m ON m.machine_id = h.mc_id
        LEFT JOIN item_mst im ON im.item_id = h.item_id
        WHERE h.co_id = :co_id
        AND h.active = 1
        AND (:branch_id IS NULL OR h.branch_id = :branch_id)
        {search_filter}
        ORDER BY h.entry_date DESC, h.yarn_tpi_id DESC
        LIMIT :limit OFFSET :offset
    """
    return text(sql)


def get_yarn_tpi_table_count_query(search: str = None):
    """Total count for the paginated TPI table (same filters, no LIMIT)."""
    search_filter = ""
    if search:
        search_filter = """
            AND (
                im.item_name LIKE :search
                OR m.machine_name LIKE :search
                OR m.mech_code LIKE :search
                OR h.prepared_by LIKE :search
            )
        """

    sql = f"""
        SELECT COUNT(*) AS total
        FROM jute_sqc_yarn_tpi h
        LEFT JOIN machine_mst m ON m.machine_id = h.mc_id
        LEFT JOIN item_mst im ON im.item_id = h.item_id
        WHERE h.co_id = :co_id
        AND h.active = 1
        AND (:branch_id IS NULL OR h.branch_id = :branch_id)
        {search_filter}
    """
    return text(sql)


def get_yarn_tpi_active_row_query():
    """The active TPI study header id (for the soft-delete guard)."""
    return text(
        """
        SELECT yarn_tpi_id
        FROM jute_sqc_yarn_tpi
        WHERE yarn_tpi_id = :id
          AND active = 1
          AND (:co_id IS NULL OR co_id = :co_id)
        """
    )


def soft_delete_yarn_tpi_query():
    """Soft-delete a TPI study header (active = 0); detail follows the header."""
    return text(
        """
        UPDATE jute_sqc_yarn_tpi
        SET active = 0,
            updated_by = :updated_by
        WHERE yarn_tpi_id = :id
          AND (:co_id IS NULL OR co_id = :co_id)
        """
    )
