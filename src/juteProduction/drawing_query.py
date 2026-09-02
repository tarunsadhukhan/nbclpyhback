"""Raw SQL builders for the Drawing production entry feature (jute production module)."""

from sqlalchemy import text


def get_drawing_machines_query():
    """Drawing machines for a company, with their drawing attributes (if configured)."""
    return text(
        """
        SELECT
            m.machine_id,
            m.machine_name,
            m.mech_code,
            m.dept_id,
            d.dept_desc AS dept_name,
            d.branch_id,
            COALESCE(jda.const_meter, 0) AS const_meter,
            COALESCE(jda.meter_wrap_limit, 10000) AS meter_wrap_limit,
            jda.mc_group,
            jda.drawing_machine_attr_id
        FROM machine_mst m
        INNER JOIN machine_type_mst mt ON mt.machine_type_id = m.machine_type_id
        INNER JOIN dept_mst d ON d.dept_id = m.dept_id
        LEFT JOIN jute_prod_drawing_machine_attr jda
               ON jda.machine_id = m.machine_id AND jda.co_id = :co_id AND jda.active = 1
        WHERE m.active = 1
          AND mt.active = 1
          AND mt.machine_type_name = :drawing_type
          AND (:branch_id IS NULL OR d.branch_id = :branch_id)
        ORDER BY m.mech_code
        """
    )


def get_spells_query():
    """Active spells with working hours from spell_mst (branch scoped via parent shift).

    Callers must de-duplicate by spell_code in Python (sls carries a duplicate A1
    under a second branch's shift) keeping the first row per code.
    """
    return text(
        """
        SELECT sp.spell_code, sp.spell_name, sp.working_hours, sp.starting_time, sp.is_overnight
        FROM spell_mst sp
        INNER JOIN shift_mst sh ON sh.shift_id = sp.shift_id
        WHERE sp.status = 1
          AND COALESCE(sp.active, 1) = 1
          AND sh.status = 1
          AND (:branch_id IS NULL OR sh.branch_id = :branch_id)
        ORDER BY sp.starting_time
        """
    )


def get_duplicate_entry_query(exclude: bool = False):
    """Count active entries for the same co/date/spell/machine (legacy 'Mc Already entered')."""
    exclude_clause = "AND drawing_entry_id <> :exclude_id" if exclude else ""
    return text(
        f"""
        SELECT COUNT(*) AS cnt
        FROM jute_prod_drawing_entry
        WHERE co_id = :co_id
          AND tran_date = :tran_date
          AND spell = :spell
          AND machine_id = :machine_id
          AND active = 1
          {exclude_clause}
        """
    )


def get_prev_close_meter_query():
    """Previous close meter for a machine WITHIN THE SAME SHIFT — pre-fill default
    for the open meter.

    Each machine carries one physical counter meter per shift (A/B/C), so the
    counter is continuous across the spells of a shift (e.g. A1 → A2) but
    independent between shifts. The pre-fill therefore restricts to entries whose
    spell belongs to the same shift_id as the requested :spell, then takes the
    latest by tran_date, then spell chronological order (deduped spell_mst derived
    table guards against duplicate spell_code fanout), then drawing_entry_id.
    """
    return text(
        """
        SELECT e.close_meter
        FROM jute_prod_drawing_entry e
        LEFT JOIN (
            SELECT spell_code, MIN(shift_id) AS shift_id, MIN(starting_time) AS starting_time
            FROM spell_mst
            WHERE status = 1
            GROUP BY spell_code
        ) sp ON sp.spell_code = e.spell
        WHERE e.co_id = :co_id
          AND e.machine_id = :machine_id
          AND e.active = 1
          AND sp.shift_id = (
              SELECT MIN(shift_id) FROM spell_mst
              WHERE spell_code = :spell AND status = 1
          )
        ORDER BY e.tran_date DESC, sp.starting_time DESC, e.drawing_entry_id DESC
        LIMIT 1
        """
    )


def get_entries_by_date_query():
    """Daily drawing entries for the records grid (spell optional — legacy grid ignored shift)."""
    return text(
        """
        SELECT
            e.drawing_entry_id,
            e.co_id,
            e.branch_id,
            e.tran_date,
            e.spell,
            e.machine_id,
            m.mech_code,
            m.machine_name,
            e.const_meter,
            e.open_meter,
            e.close_meter,
            e.diff_meter,
            e.actual_eff,
            e.wrk_hours,
            e.remarks
        FROM jute_prod_drawing_entry e
        LEFT JOIN machine_mst m ON m.machine_id = e.machine_id
        WHERE e.co_id = :co_id
          AND e.tran_date = :tran_date
          AND e.active = 1
          AND (:spell IS NULL OR e.spell = :spell)
          AND (:branch_id IS NULL OR e.branch_id = :branch_id)
        ORDER BY m.mech_code
        """
    )


def get_drawing_machine_attr_list_query():
    """ALL Drawing-type machines LEFT JOIN attr — serves master grid rows AND the
    create-dialog machine options (rows with drawing_machine_attr_id IS NULL)."""
    return text(
        """
        SELECT
            jda.drawing_machine_attr_id,
            m.machine_id,
            m.mech_code,
            m.machine_name,
            d.dept_desc AS dept_name,
            d.branch_id,
            jda.const_meter,
            jda.mc_group,
            jda.meter_wrap_limit,
            jda.active
        FROM machine_mst m
        INNER JOIN machine_type_mst mt ON mt.machine_type_id = m.machine_type_id
        INNER JOIN dept_mst d ON d.dept_id = m.dept_id
        LEFT JOIN jute_prod_drawing_machine_attr jda
               ON jda.machine_id = m.machine_id AND jda.co_id = :co_id
        WHERE m.active = 1
          AND mt.active = 1
          AND mt.machine_type_name = :drawing_type
        ORDER BY m.mech_code
        """
    )
