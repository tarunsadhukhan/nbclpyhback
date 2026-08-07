"""Raw SQL builders for the spinning standards/targets master (jute_prod_spng_target_map).

Time-versioned standards & targets with LAST-DATE resolution: for a given
(co_id, ref_id, id_type, value_role, param) the effective row on a date is the one
with MAX(effective_date) <= :on_date among active rows. This module only serves the
CRUD master (setup / list / create / edit / delete); the resolution query is provided
here too for downstream consumers, but the CRUD endpoints in spng_target_map.py do not
need it.

Mirrors spinning_query.py conventions: named binds, the ``:x IS NULL OR ...``
optional-filter idiom, soft-delete via active, and de-duplication left to callers.
Setup reuses get_spinning_machines_query / get_yarn_qualities_query from spinning_query.
"""

from sqlalchemy import text


def get_target_map_list_query():
    """Active target-map rows with optional id_type / ref_id / value_role / param filters.

    Newest effective_date first. Joins machine_mst (for mcid rows) and item_mst
    (for qid rows, where ref_id = yarn item_id) to surface a human-readable ref label.
    """
    return text(
        """
        SELECT
            tm.spng_target_map_id,
            tm.co_id,
            tm.branch_id,
            tm.effective_date,
            tm.ref_id,
            tm.id_type,
            tm.value_role,
            tm.param,
            tm.value,
            tm.active,
            CASE
                WHEN tm.id_type = 'mcid' THEN m.mech_code
                WHEN tm.id_type = 'qid' THEN im.item_code
                ELSE NULL
            END AS ref_code,
            CASE
                WHEN tm.id_type = 'mcid' THEN m.machine_name
                WHEN tm.id_type = 'qid' THEN im.item_name
                ELSE NULL
            END AS ref_name
        FROM jute_prod_spng_target_map tm
        LEFT JOIN machine_mst m
               ON tm.id_type = 'mcid' AND m.machine_id = tm.ref_id
        LEFT JOIN item_mst im
               ON tm.id_type = 'qid' AND im.item_id = tm.ref_id
        WHERE tm.co_id = :co_id
          AND tm.active = 1
          AND (:branch_id IS NULL OR tm.branch_id = :branch_id OR tm.branch_id IS NULL)
          AND (:id_type IS NULL OR tm.id_type = :id_type)
          AND (:ref_id IS NULL OR tm.ref_id = :ref_id)
          AND (:value_role IS NULL OR tm.value_role = :value_role)
          AND (:param IS NULL OR tm.param = :param)
        ORDER BY tm.effective_date DESC, tm.spng_target_map_id DESC
        """
    )


def get_target_map_row_query():
    """A single active target-map row by id (for edit / delete existence check)."""
    return text(
        """
        SELECT spng_target_map_id, co_id, branch_id, effective_date, ref_id,
               id_type, value_role, param, value, active
        FROM jute_prod_spng_target_map
        WHERE spng_target_map_id = :id
          AND active = 1
        """
    )


def insert_target_map_query():
    """Insert a fresh active standards/targets row."""
    return text(
        """
        INSERT INTO jute_prod_spng_target_map
            (co_id, branch_id, effective_date, ref_id, id_type, value_role,
             param, value, active, updated_by)
        VALUES
            (:co_id, :branch_id, :effective_date, :ref_id, :id_type, :value_role,
             :param, :value, 1, :updated_by)
        """
    )


def resolve_target_value_query():
    """LAST-DATE resolution: the value effective on :on_date for one resolution key.

    Returns the row with MAX(effective_date) <= :on_date among active rows for
    (co_id, ref_id, id_type, value_role, param). Provided for downstream consumers
    (e.g. the spinning-daily snapshot builder); not used by the CRUD endpoints.
    """
    return text(
        """
        SELECT value, effective_date
        FROM jute_prod_spng_target_map
        WHERE co_id = :co_id
          AND ref_id = :ref_id
          AND id_type = :id_type
          AND value_role = :value_role
          AND param = :param
          AND active = 1
          AND effective_date <= :on_date
        ORDER BY effective_date DESC, spng_target_map_id DESC
        LIMIT 1
        """
    )


# =============================================================================
# Inline-grid (target_map_grid / target_map_bulk_save)
# =============================================================================


def resolve_grid_cell_query():
    """LAST-DATE resolution for ONE grid cell, mirroring resolve_param semantics.

    Same WHERE/ORDER/LIMIT as spinning_standards.resolve_param (MAX(effective_date)
    <= :on_date among active rows for co_id/ref_id/id_type/value_role/param) -- and,
    like resolve_param, applies NO branch filter. Also returns effective_date so the
    grid can expose source_date / is_exact. The grid reads values exactly as
    production does, so the displayed cell matches what spinning planning will use.
    """
    return text(
        """
        SELECT value, effective_date
        FROM jute_prod_spng_target_map
        WHERE co_id = :co_id
          AND ref_id = :ref_id
          AND id_type = :id_type
          AND value_role = :value_role
          AND param = :param
          AND active = 1
          AND effective_date <= :on_date
        ORDER BY effective_date DESC, spng_target_map_id DESC
        LIMIT 1
        """
    )


def find_exact_grid_row_query():
    """Active row at the EXACT save key, BRANCH-AGNOSTIC (mirrors grid resolution).

    Used by target_map_bulk_save to decide insert-vs-update-vs-clear. Deliberately
    applies NO branch filter so that save targets the SAME row the grid prefilled:
    resolve_grid_cell_query (and production resolve_param) ignore branch_id, so a
    cell can be prefilled from a NULL-branch (or any-branch) row. Matching branch
    here too would miss that row and silently INSERT a divergent duplicate. The
    tiebreak (newest id first) matches resolve_grid_cell_query's ORDER BY for the
    is_exact case, so an update targets exactly the displayed row.
    """
    return text(
        """
        SELECT spng_target_map_id, value
        FROM jute_prod_spng_target_map
        WHERE co_id = :co_id
          AND ref_id = :ref_id
          AND id_type = :id_type
          AND value_role = :value_role
          AND param = :param
          AND effective_date = :effective_date
          AND active = 1
        ORDER BY spng_target_map_id DESC
        LIMIT 1
        """
    )


def update_grid_value_query():
    """Set value (+ audit cols) on one active grid row by id."""
    return text(
        """
        UPDATE jute_prod_spng_target_map
        SET value = :value,
            updated_by = :updated_by,
            updated_date_time = CURRENT_TIMESTAMP
        WHERE spng_target_map_id = :id
        """
    )


def clear_grid_value_query():
    """Soft-delete (active=0) one grid row by id, clearing the cell."""
    return text(
        """
        UPDATE jute_prod_spng_target_map
        SET active = 0,
            updated_by = :updated_by,
            updated_date_time = CURRENT_TIMESTAMP
        WHERE spng_target_map_id = :id
        """
    )
