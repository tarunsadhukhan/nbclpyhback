"""Raw SQL builders for R-08-15A Yarn QR% & CV% Special Purpose (jute SQC module).

HEADER + DETAIL (2 machines, flat 12 readings — no spindle structure). Clones the
jute_sqc_spinning_qr_cv / _dtl builders in spinning_sqc_query.py: header + detail pair,
insert-only (duplicates allowed), soft-delete the header only (detail follows the
active-header join). observed_count / mr_pct are OPERATOR-ENTERED on the header (the
special-purpose variant; NOT read from R-08-16) and stored. Stats are computed
server-side at read from the stored readings.

Branch-wise (like the carding reports): by_date + table reads are STRICTLY branch-scoped
((:branch_id IS NULL OR branch_id = :branch_id) — no NULL-branch leak). The machine picker
(get_card_section_machines_query) and yarn-quality picker (get_yarn_qualities_query) are
reused by the router; only the genuinely-new builders live here.
"""

from sqlalchemy import text, bindparam


def get_qr_cv_15a_by_date_query():
    """Active QR/CV-15A headers for a co/entry_date (branch optional, strict), labelled.

    Joins BOTH the spinning frame (mc_id) and the 3rd-drawing machine (drawing_mc_id)."""
    return text(
        """
        SELECT
            h.qr_cv_15a_id,
            h.co_id,
            h.branch_id,
            h.entry_date,
            h.drawing_mc_id,
            dm.mech_code  AS drawing_mech_code,
            dm.machine_name AS drawing_machine_name,
            h.mc_id,
            m.mech_code,
            m.machine_name,
            h.item_id,
            im.item_code,
            im.item_name,
            h.observed_count,
            h.mr_pct,
            h.updated_date_time
        FROM jute_sqc_qr_cv_15a h
        LEFT JOIN machine_mst m ON m.machine_id = h.mc_id
        LEFT JOIN machine_mst dm ON dm.machine_id = h.drawing_mc_id
        LEFT JOIN item_mst im ON im.item_id = h.item_id
        WHERE h.co_id = :co_id
          AND h.entry_date = :entry_date
          AND h.active = 1
          AND (:branch_id IS NULL OR h.branch_id = :branch_id)
        ORDER BY im.item_name, h.qr_cv_15a_id
        """
    )


def get_qr_cv_15a_dtl_query():
    """Reading rows for a set of header ids (single round-trip, expanding bind)."""
    return text(
        """
        SELECT qr_cv_15a_id, reading_no, reading_val
        FROM jute_sqc_qr_cv_15a_dtl
        WHERE qr_cv_15a_id IN :ids
        ORDER BY qr_cv_15a_id, reading_no
        """
    ).bindparams(bindparam("ids", expanding=True))


def insert_qr_cv_15a_header_query():
    """Insert a fresh active QR/CV-15A header (insert-only; read lastrowid)."""
    return text(
        """
        INSERT INTO jute_sqc_qr_cv_15a
            (co_id, branch_id, entry_date, drawing_mc_id, mc_id, item_id,
             observed_count, mr_pct, active, updated_by)
        VALUES
            (:co_id, :branch_id, :entry_date, :drawing_mc_id, :mc_id, :item_id,
             :observed_count, :mr_pct, 1, :updated_by)
        """
    )


def insert_qr_cv_15a_dtl_query():
    """Insert one reading detail row for a QR/CV-15A header."""
    return text(
        """
        INSERT INTO jute_sqc_qr_cv_15a_dtl
            (qr_cv_15a_id, reading_no, reading_val)
        VALUES
            (:hdr_id, :reading_no, :reading_val)
        """
    )


def get_qr_cv_15a_table_query(search: str = None):
    """Paginated active QR/CV-15A headers for a co (branch optional, strict), labelled."""
    search_filter = ""
    if search:
        search_filter = """
            AND (
                im.item_name LIKE :search
                OR m.machine_name LIKE :search
                OR m.mech_code LIKE :search
                OR dm.machine_name LIKE :search
            )
        """

    sql = f"""
        SELECT
            h.qr_cv_15a_id,
            h.co_id,
            h.branch_id,
            h.entry_date,
            h.drawing_mc_id,
            dm.machine_name AS drawing_machine_name,
            h.mc_id,
            m.machine_name,
            m.mech_code,
            h.item_id,
            im.item_name AS yarn_quality,
            im.item_code,
            h.observed_count,
            h.mr_pct,
            h.updated_date_time
        FROM jute_sqc_qr_cv_15a h
        LEFT JOIN machine_mst m ON m.machine_id = h.mc_id
        LEFT JOIN machine_mst dm ON dm.machine_id = h.drawing_mc_id
        LEFT JOIN item_mst im ON im.item_id = h.item_id
        WHERE h.co_id = :co_id
        AND h.active = 1
        AND (:branch_id IS NULL OR h.branch_id = :branch_id)
        {search_filter}
        ORDER BY h.entry_date DESC, h.qr_cv_15a_id DESC
        LIMIT :limit OFFSET :offset
    """
    return text(sql)


def get_qr_cv_15a_table_count_query(search: str = None):
    """Total count for the paginated QR/CV-15A table (same filters, no LIMIT)."""
    search_filter = ""
    if search:
        search_filter = """
            AND (
                im.item_name LIKE :search
                OR m.machine_name LIKE :search
                OR m.mech_code LIKE :search
                OR dm.machine_name LIKE :search
            )
        """

    sql = f"""
        SELECT COUNT(*) AS total
        FROM jute_sqc_qr_cv_15a h
        LEFT JOIN machine_mst m ON m.machine_id = h.mc_id
        LEFT JOIN machine_mst dm ON dm.machine_id = h.drawing_mc_id
        LEFT JOIN item_mst im ON im.item_id = h.item_id
        WHERE h.co_id = :co_id
        AND h.active = 1
        AND (:branch_id IS NULL OR h.branch_id = :branch_id)
        {search_filter}
    """
    return text(sql)


def get_qr_cv_15a_active_row_query():
    """The active QR/CV-15A header id (for the soft-delete guard)."""
    return text(
        """
        SELECT qr_cv_15a_id
        FROM jute_sqc_qr_cv_15a
        WHERE qr_cv_15a_id = :id
          AND active = 1
          AND (:co_id IS NULL OR co_id = :co_id)
        """
    )


def soft_delete_qr_cv_15a_query():
    """Soft-delete a QR/CV-15A header (active = 0); detail follows the header."""
    return text(
        """
        UPDATE jute_sqc_qr_cv_15a
        SET active = 0,
            updated_by = :updated_by
        WHERE qr_cv_15a_id = :id
          AND (:co_id IS NULL OR co_id = :co_id)
        """
    )
