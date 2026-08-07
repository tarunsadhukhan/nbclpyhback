"""Raw SQL builders for the Jute Production — Stoppage Hours module.

Stoppage Hours is a daily machine-downtime event log (see SPEC.md). Each row is
a reason-tagged stoppage interval for a machine on a (date, spell). Department is
NOT stored — it is a cascading UI filter only and is resolved on read via the
canonical machine_mst -> dept_mst join. branch_id is derived from the machine's
department on insert and read-tolerant of legacy NULLs via COALESCE.

Conventions mirror winding_query.py / query.py: sqlalchemy.text() with named
binds, the ``:x IS NULL OR ...`` optional-filter idiom, and spell_id (INT) joined
to spell_mst (which keys activity by ``status``, NOT ``active``).

LOCKED DECISION: the setup machine query exposes ALL active machines — it does
NOT filter by machine_type_name (so a stoppage can be logged for any department's
machine). Narrowing to the four jute stage types would be a one-line
``AND mt.machine_type_name IN (...)`` if ever desired.
"""

from sqlalchemy import text


# =============================================================================
# Setup / lookup builders
# =============================================================================


def get_stoppage_machines_query():
    """ALL active machines with their dept + derived branch (canonical join).

    Reuses the canonical stage->machine join (query.py get_spreader_machines_query
    pattern) so dept/branch travel along for the department->machine cascade.
    Per the locked decision this is NOT filtered by machine_type_name — only
    ``m.active = 1 AND mt.active = 1`` gate the rows. branch_id is the
    department's branch (machine_mst has no branch_id of its own).
    """
    return text(
        """
        SELECT
            m.machine_id,
            m.machine_name,
            m.mech_code,
            m.machine_type_id,
            mt.machine_type_name,
            d.dept_id,
            d.dept_desc AS dept_name,
            d.branch_id
        FROM machine_mst m
        INNER JOIN machine_type_mst mt ON mt.machine_type_id = m.machine_type_id
        INNER JOIN dept_mst d ON d.dept_id = m.dept_id
        WHERE m.active = 1
          AND mt.active = 1
          AND (:branch_id IS NULL OR d.branch_id = :branch_id)
        ORDER BY d.dept_desc, m.machine_name
        """
    )


def get_stoppage_spells_query():
    """Active spells with working hours from spell_mst (branch scoped via shift).

    Trimmed copy of spinning_query.get_spells_query — only the fields the stoppage
    page needs (spell_id, spell_code, spell_name, working_hours). spell_mst keys
    activity by ``status`` (1 = active), NOT an ``active`` column; the parent
    shift is likewise filtered by status. Callers de-duplicate by spell_code
    (some tenants carry a duplicate spell_code under a second branch's shift).
    """
    return text(
        """
        SELECT sp.spell_id, sp.spell_code, sp.spell_name, sp.working_hours
        FROM spell_mst sp
        INNER JOIN shift_mst sh ON sh.shift_id = sp.shift_id
        WHERE sp.status = 1
          AND sh.status = 1
          AND (:branch_id IS NULL OR sh.branch_id = :branch_id)
        ORDER BY sp.starting_time
        """
    )


def get_spell_working_hours_query():
    """Planned working_hours for a single spell_id (validation baseline).

    No status guard by design: the row stores spell_id and joins by it, so even a
    retired spell yields the correct planned working_hours for the
    0 < stoppage_hours <= working_hours single-event bound.
    """
    return text(
        """
        SELECT working_hours
        FROM spell_mst
        WHERE spell_id = :spell_id
        """
    )


def derive_branch_for_machine_query():
    """Branch derivation on INSERT: machine -> dept -> branch.

    machine_mst has no branch_id; branch is reachable only via dept_mst.branch_id
    (itself nullable). Mirrors spreader_entry.py / winding_query.py derivation.
    """
    return text(
        """
        SELECT d.branch_id
        FROM machine_mst m
        INNER JOIN dept_mst d ON d.dept_id = m.dept_id
        WHERE m.machine_id = :machine_id
        """
    )


# =============================================================================
# CRUD builders
# =============================================================================


def insert_stoppage_row_query():
    """Insert one stoppage event (active = 1)."""
    return text(
        """
        INSERT INTO jute_prod_stoppage_hours
            (co_id, branch_id, tran_date, spell_id, machine_id,
             stoppage_hours, reason_code, remarks, active, updated_by)
        VALUES
            (:co_id, :branch_id, :tran_date, :spell_id, :machine_id,
             :stoppage_hours, :reason_code, :remarks, 1, :updated_by)
        """
    )


def get_stoppage_active_by_id_query():
    """One active stoppage row by id (for edit / delete guards)."""
    return text(
        """
        SELECT stoppage_hours_id, co_id, branch_id, tran_date, spell_id,
               machine_id, stoppage_hours, reason_code, remarks
        FROM jute_prod_stoppage_hours
        WHERE stoppage_hours_id = :id AND active = 1
        """
    )


def update_stoppage_row_query():
    """Edit only stoppage_hours / reason_code / remarks / spell_id (per SPEC §8.2)."""
    return text(
        """
        UPDATE jute_prod_stoppage_hours
        SET stoppage_hours = :stoppage_hours,
            reason_code    = :reason_code,
            remarks        = :remarks,
            spell_id       = :spell_id,
            updated_by     = :updated_by
        WHERE stoppage_hours_id = :id AND active = 1
        """
    )


def soft_delete_stoppage_row_query():
    """Soft delete (active = 0)."""
    return text(
        """
        UPDATE jute_prod_stoppage_hours
        SET active = 0, updated_by = :updated_by
        WHERE stoppage_hours_id = :id AND active = 1
        """
    )


def get_stoppage_by_date_query():
    """Day-grid read: resolve dept_name / machine_name / spell_code for display.

    COALESCE(s.branch_id, d.branch_id) tolerates legacy NULL branch_id on the row
    (dept_mst.branch_id is itself nullable — the legacy-NULL safety net per §10).
    """
    return text(
        """
        SELECT
            s.stoppage_hours_id,
            s.tran_date,
            s.spell_id,
            sp.spell_code,
            s.machine_id,
            m.machine_name,
            d.dept_id,
            d.dept_desc AS dept_name,
            s.stoppage_hours,
            s.reason_code,
            s.remarks,
            COALESCE(s.branch_id, d.branch_id) AS branch_id
        FROM jute_prod_stoppage_hours s
        INNER JOIN machine_mst m ON m.machine_id = s.machine_id
        INNER JOIN dept_mst d ON d.dept_id = m.dept_id
        LEFT JOIN spell_mst sp ON sp.spell_id = s.spell_id
        WHERE s.active = 1
          AND s.co_id = :co_id
          AND s.tran_date = :tran_date
          AND (:branch_id IS NULL OR COALESCE(s.branch_id, d.branch_id) = :branch_id)
        ORDER BY d.dept_desc, m.machine_name, s.stoppage_hours_id
        """
    )
