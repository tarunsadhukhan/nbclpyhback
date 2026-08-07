"""Raw SQL builders for the Spinning SQC capture feature (jute SQC module).

Two capture surfaces feed the spinning planning grid:
  * jute_sqc_spinning_entry  - single-value actual Speed/TPI per (date, machine,
    quality); resolved downstream by last-date. Upsert one active row per key.
  * jute_sqc_spinning_count  - multi-observation count readings; Act Count is the
    AVG(observed_count) per (date, quality). Each save is a NEW reading (no upsert).

Mirrors spinning_query.py conventions: named binds, the ``:x IS NULL OR ...``
optional-filter idiom, and active = 1 soft-delete (active IS NULL legacy rows are
not expected on these freshly-created tables). The yarn-quality and spell lookups
are reused directly from spinning_query.py by the router; the machine list builder
get_spinning_machines_query is also imported there.
"""

from sqlalchemy import text, bindparam


# =============================================================================
# jute_sqc_spinning_entry (single-value actual Speed / TPI) builders
# =============================================================================


def get_sqc_entry_by_date_query():
    """Active SQC entry rows for a co/entry_date (branch optional), with display labels."""
    return text(
        """
        SELECT
            e.spinning_sqc_entry_id,
            e.co_id,
            e.branch_id,
            e.entry_date,
            e.mc_id,
            m.mech_code,
            m.machine_name,
            e.item_id,
            im.item_code,
            im.item_name,
            e.actual_speed,
            e.actual_tpi
        FROM jute_sqc_spinning_entry e
        LEFT JOIN machine_mst m ON m.machine_id = e.mc_id
        LEFT JOIN item_mst im ON im.item_id = e.item_id
        WHERE e.co_id = :co_id
          AND e.entry_date = :entry_date
          AND e.active = 1
          AND (:branch_id IS NULL OR e.branch_id = :branch_id OR e.branch_id IS NULL)
        ORDER BY m.mech_code, e.spinning_sqc_entry_id
        """
    )


def get_sqc_entry_active_row_query():
    """The active entry row id for (co/date/machine/quality) — upsert lookup."""
    return text(
        """
        SELECT spinning_sqc_entry_id
        FROM jute_sqc_spinning_entry
        WHERE co_id = :co_id
          AND entry_date = :entry_date
          AND mc_id = :mc_id
          AND item_id = :item_id
          AND active = 1
        ORDER BY spinning_sqc_entry_id DESC
        LIMIT 1
        """
    )


def update_sqc_entry_query():
    """Update an existing active entry row's actual_speed / actual_tpi."""
    return text(
        """
        UPDATE jute_sqc_spinning_entry
        SET actual_speed = :actual_speed,
            actual_tpi = :actual_tpi,
            updated_by = :updated_by
        WHERE spinning_sqc_entry_id = :id
        """
    )


def insert_sqc_entry_query():
    """Insert a fresh active entry row."""
    return text(
        """
        INSERT INTO jute_sqc_spinning_entry
            (co_id, branch_id, entry_date, mc_id, item_id,
             actual_speed, actual_tpi, active, updated_by)
        VALUES
            (:co_id, :branch_id, :entry_date, :mc_id, :item_id,
             :actual_speed, :actual_tpi, 1, :updated_by)
        """
    )


# =============================================================================
# jute_sqc_spinning_count (multi-observation count) builders
# =============================================================================


def get_sqc_count_by_date_query():
    """Active count reading rows for a co/entry_date (branch optional), with labels.

    Each row is a single observation (no upsert); the planning grid averages these.
    """
    return text(
        """
        SELECT
            c.spinning_sqc_count_id,
            c.co_id,
            c.branch_id,
            c.entry_date,
            c.spell_id,
            sp.spell_code,
            c.mc_id,
            m.mech_code,
            m.machine_name,
            c.item_id,
            im.item_code,
            im.item_name,
            ym.std_mr_pct,
            c.dp,
            c.tp,
            c.wt_450_gms,
            c.mr_pct,
            c.observed_count,
            c.corrected_count
        FROM jute_sqc_spinning_count c
        LEFT JOIN machine_mst m ON m.machine_id = c.mc_id
        LEFT JOIN item_mst im ON im.item_id = c.item_id
        LEFT JOIN jute_yarn_mst ym ON ym.item_id = c.item_id
        LEFT JOIN (
            SELECT spell_id, spell_code FROM spell_mst WHERE status = 1
        ) sp ON sp.spell_id = c.spell_id
        WHERE c.co_id = :co_id
          AND c.entry_date = :entry_date
          AND c.active = 1
          AND (:branch_id IS NULL OR c.branch_id = :branch_id OR c.branch_id IS NULL)
        ORDER BY im.item_name, c.spinning_sqc_count_id
        """
    )


def get_sqc_count_avg_query():
    """AVG(observed_count) per yarn item for a co/entry_date (branch optional)."""
    return text(
        """
        SELECT
            c.item_id,
            im.item_code,
            im.item_name,
            AVG(c.observed_count) AS avg_count,
            AVG(c.corrected_count) AS avg_corrected,
            COUNT(*) AS obs_count
        FROM jute_sqc_spinning_count c
        LEFT JOIN item_mst im ON im.item_id = c.item_id
        WHERE c.co_id = :co_id
          AND c.entry_date = :entry_date
          AND c.active = 1
          AND (:branch_id IS NULL OR c.branch_id = :branch_id OR c.branch_id IS NULL)
        GROUP BY c.item_id, im.item_code, im.item_name
        ORDER BY im.item_name
        """
    )


def insert_sqc_count_query():
    """Insert one count observation (a fresh active row per reading).

    observed_count and corrected_count are computed by the router from the raw
    inputs (wt_450_gms, mr_pct, and the quality's std_mr_pct).
    """
    return text(
        """
        INSERT INTO jute_sqc_spinning_count
            (co_id, branch_id, entry_date, spell_id, mc_id, item_id,
             dp, tp, wt_450_gms, mr_pct, observed_count, corrected_count,
             active, updated_by)
        VALUES
            (:co_id, :branch_id, :entry_date, :spell_id, :mc_id, :item_id,
             :dp, :tp, :wt_450_gms, :mr_pct, :observed_count, :corrected_count,
             1, :updated_by)
        """
    )


def get_quality_std_mr_query():
    """std_mr_pct for a yarn item (used to compute corrected count at save).

    Reads jute_yarn_mst.std_mr_pct by the yarn item_id (was yarn_quality_master).
    """
    return text(
        """
        SELECT std_mr_pct
        FROM jute_yarn_mst
        WHERE item_id = :item_id
        """
    )


def get_sqc_count_active_row_query():
    """The active count row id (for the soft-delete guard)."""
    return text(
        """
        SELECT spinning_sqc_count_id
        FROM jute_sqc_spinning_count
        WHERE spinning_sqc_count_id = :id
          AND active = 1
        """
    )


def soft_delete_sqc_count_query():
    """Soft-delete a count reading (active = 0)."""
    return text(
        """
        UPDATE jute_sqc_spinning_count
        SET active = 0,
            updated_by = :updated_by
        WHERE spinning_sqc_count_id = :id
        """
    )


# =============================================================================
# jute_sqc_spinning_rhmr (Temperature / Humidity per date+spell) builders
# =============================================================================
# Upsert one active row per (co_id, entry_date, spell_id). Search is by co plus
# optional entry_date and/or spell_id (the :x IS NULL OR ... optional-filter idiom).


def get_sqc_rhmr_search_query():
    """Active RHMR rows for a co, filtered by optional entry_date and/or spell_id."""
    return text(
        """
        SELECT
            r.spinning_sqc_rhmr_id,
            r.co_id,
            r.branch_id,
            r.entry_date,
            r.spell_id,
            sp.spell_code,
            sp.spell_name,
            r.temperature,
            r.humidity
        FROM jute_sqc_spinning_rhmr r
        LEFT JOIN (
            SELECT spell_id, MIN(spell_code) AS spell_code, MIN(spell_name) AS spell_name
            FROM spell_mst WHERE status = 1 GROUP BY spell_id
        ) sp ON sp.spell_id = r.spell_id
        WHERE r.co_id = :co_id
          AND r.active = 1
          AND (:entry_date IS NULL OR r.entry_date = :entry_date)
          AND (:spell_id IS NULL OR r.spell_id = :spell_id)
          AND (:branch_id IS NULL OR r.branch_id = :branch_id OR r.branch_id IS NULL)
        ORDER BY r.entry_date DESC, r.spell_id, r.spinning_sqc_rhmr_id DESC
        """
    )


def get_sqc_rhmr_active_row_query():
    """The active RHMR row for (co/date/spell) — upsert + exists-check lookup."""
    return text(
        """
        SELECT spinning_sqc_rhmr_id, temperature, humidity
        FROM jute_sqc_spinning_rhmr
        WHERE co_id = :co_id
          AND entry_date = :entry_date
          AND spell_id = :spell_id
          AND active = 1
        ORDER BY spinning_sqc_rhmr_id DESC
        LIMIT 1
        """
    )


def get_sqc_rhmr_by_id_query():
    """The active RHMR row id (for the soft-delete guard)."""
    return text(
        """
        SELECT spinning_sqc_rhmr_id
        FROM jute_sqc_spinning_rhmr
        WHERE spinning_sqc_rhmr_id = :id
          AND active = 1
        """
    )


def insert_sqc_rhmr_query():
    """Insert a fresh active RHMR row."""
    return text(
        """
        INSERT INTO jute_sqc_spinning_rhmr
            (co_id, branch_id, entry_date, spell_id, temperature, humidity,
             active, updated_by)
        VALUES
            (:co_id, :branch_id, :entry_date, :spell_id, :temperature, :humidity,
             1, :updated_by)
        """
    )


def update_sqc_rhmr_query():
    """Overwrite an existing active RHMR row's temperature / humidity."""
    return text(
        """
        UPDATE jute_sqc_spinning_rhmr
        SET temperature = :temperature,
            humidity = :humidity,
            updated_by = :updated_by
        WHERE spinning_sqc_rhmr_id = :id
        """
    )


def soft_delete_sqc_rhmr_query():
    """Soft-delete an RHMR row (active = 0)."""
    return text(
        """
        UPDATE jute_sqc_spinning_rhmr
        SET active = 0,
            updated_by = :updated_by
        WHERE spinning_sqc_rhmr_id = :id
        """
    )


# =============================================================================
# jute_sqc_spinning_qr_cv / _dtl (R-08-15 Yarn QR & CV %) builders
# =============================================================================
# A group = one saved test for (date, machine, item_id) carrying 30 readings
# (6 spindles x 5 readings). Header + detail pair; insert-only (duplicates
# allowed), soft-delete the header only (detail follows the header's active flag).
# observed_count / mr_pct are NOT stored here — they are read from R-08-16's
# already-saved values in jute_sqc_spinning_count (AVG per item_id) at read time.


def get_sqc_count_obs_mr_avg_query():
    """Per-yarn AVG(observed_count) + AVG(mr_pct) for a co/entry_date (branch
    optional). Source for R-08-15 observed count + MR% obtained (D1), read from
    R-08-16's already-saved observed_count/mr_pct columns (D6). Optional :item_id
    narrows to one yarn item."""
    return text(
        """
        SELECT
            c.item_id,
            im.item_code,
            im.item_name,
            AVG(c.observed_count) AS observed_count,
            AVG(c.mr_pct)         AS mr_pct,
            COUNT(*)              AS obs_count
        FROM jute_sqc_spinning_count c
        LEFT JOIN item_mst im ON im.item_id = c.item_id
        WHERE c.co_id = :co_id
          AND c.entry_date = :entry_date
          AND c.active = 1
          AND (:branch_id IS NULL OR c.branch_id = :branch_id OR c.branch_id IS NULL)
          AND (:item_id IS NULL OR c.item_id = :item_id)
        GROUP BY c.item_id, im.item_code, im.item_name
        ORDER BY im.item_name
        """
    )


def get_sqc_qr_cv_by_date_query():
    """Active QR/CV group headers for a co/entry_date (branch optional), labelled."""
    return text(
        """
        SELECT
            h.spinning_sqc_qr_cv_id,
            h.co_id,
            h.branch_id,
            h.entry_date,
            h.mc_id,
            m.mech_code,
            m.machine_name,
            h.item_id,
            im.item_code,
            im.item_name
        FROM jute_sqc_spinning_qr_cv h
        LEFT JOIN machine_mst m ON m.machine_id = h.mc_id
        LEFT JOIN item_mst im ON im.item_id = h.item_id
        WHERE h.co_id = :co_id
          AND h.entry_date = :entry_date
          AND h.active = 1
          AND (:branch_id IS NULL OR h.branch_id = :branch_id OR h.branch_id IS NULL)
        ORDER BY im.item_name, h.spinning_sqc_qr_cv_id
        """
    )


def get_sqc_qr_cv_dtl_query():
    """Reading rows for a set of group ids (single round-trip, expanding bind)."""
    return text(
        """
        SELECT spinning_sqc_qr_cv_id, spindle_no, reading_no, reading_val
        FROM jute_sqc_spinning_qr_cv_dtl
        WHERE spinning_sqc_qr_cv_id IN :ids
        ORDER BY spinning_sqc_qr_cv_id, spindle_no, reading_no
        """
    ).bindparams(bindparam("ids", expanding=True))


def insert_sqc_qr_cv_header_query():
    """Insert a fresh active QR/CV group header (insert-only; read lastrowid)."""
    return text(
        """
        INSERT INTO jute_sqc_spinning_qr_cv
            (co_id, branch_id, entry_date, mc_id, item_id, active, updated_by)
        VALUES
            (:co_id, :branch_id, :entry_date, :mc_id, :item_id, 1, :updated_by)
        """
    )


def insert_sqc_qr_cv_dtl_query():
    """Insert one spindle reading detail row for a QR/CV group."""
    return text(
        """
        INSERT INTO jute_sqc_spinning_qr_cv_dtl
            (spinning_sqc_qr_cv_id, spindle_no, reading_no, reading_val)
        VALUES
            (:hdr_id, :spindle_no, :reading_no, :reading_val)
        """
    )


def get_sqc_qr_cv_active_row_query():
    """The active QR/CV header id (for the soft-delete guard)."""
    return text(
        """
        SELECT spinning_sqc_qr_cv_id
        FROM jute_sqc_spinning_qr_cv
        WHERE spinning_sqc_qr_cv_id = :id
          AND active = 1
        """
    )


def soft_delete_sqc_qr_cv_query():
    """Soft-delete a QR/CV group header (active = 0); detail follows the header."""
    return text(
        """
        UPDATE jute_sqc_spinning_qr_cv
        SET active = 0,
            updated_by = :updated_by
        WHERE spinning_sqc_qr_cv_id = :id
        """
    )
