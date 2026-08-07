"""Raw SQL builders for the spinning quality mapper (spec 5.3).

Grid = one row per active spinning machine + current helper state; save =
mapper INSERT + helper upsert + scoped retro UPDATE on daily_doff_tbl.
Retro range comparison is at (doff_date, spell) grain, spell order via
spell_mst.starting_time; effective_from_spell NULL = start of day.

Machine scoping replicates get_spinning_machines_query, the yarn list
replicates get_yarn_qualities_query (both in spinning_query.py) — kept as
local copies so grid-specific joins never leak back into the shared builders.
"""

from sqlalchemy import text

RETRO_MODES = ("fill", "synced", "all")

# Shared retro-range scope: doff rows of one machine at/after the effective
# (date, spell) point. LEFT JOIN keeps rows whose spell id no longer resolves
# (they still qualify on strictly-later dates). active IN (1, NULL) keeps
# legacy rows that pre-date the active flag; weight_type='SPG1' is the
# spinning discriminator every ERP doff query filters on.
#
# Upper cap (T5/T17): the range stops STRICTLY BEFORE the machine's next
# active mapper change-point (:next_date/:next_start_time, day-start =
# '00:00:00', NULL = no later rule) — a backdated rule must never overwrite
# rows a later rule already governs. Rows whose spell has no starting_time
# on the boundary date are conservatively excluded from the boundary day.
_RETRO_SCOPE = """
        dd.mc_id = :mc_id
          AND (dd.active = 1 OR dd.active IS NULL)
          AND dd.weight_type = 'SPG1'
          AND (
                dd.doff_date > :eff_date
                OR (dd.doff_date = :eff_date
                    AND (:eff_start_time IS NULL OR sp.starting_time >= :eff_start_time))
              )
          AND (
                :next_date IS NULL
                OR dd.doff_date < :next_date
                OR (dd.doff_date = :next_date AND sp.starting_time < :next_start_time)
              )
"""


def _retro_mode_condition(retro_mode: str) -> str:
    """Extra predicate per retro_mode (spec 5.3 step 4)."""
    if retro_mode == "fill":
        return "AND dd.item_id IS NULL"
    if retro_mode == "synced":
        return "AND (dd.item_id IS NULL OR dd.item_source IN ('helper','mapper'))"
    return ""  # 'all' — everything in range (Edit level enforced by the router)


def get_quality_map_grid_query():
    """One row per active spinning-type machine with its current helper mapping."""
    return text(
        """
        SELECT
            m.machine_id,
            m.mech_code,
            m.machine_name,
            d.branch_id,
            h.item_id,
            im.item_code,
            im.item_name,
            h.effective_from_date,
            h.effective_from_spell_id,
            sp.spell_code AS effective_from_spell_code,
            (SELECT COUNT(*) FROM spg_quality_mapper qm
              WHERE qm.mc_id = m.machine_id AND qm.active = 1) AS mapper_rows
        FROM machine_mst m
        INNER JOIN machine_type_mst mt ON mt.machine_type_id = m.machine_type_id
        INNER JOIN dept_mst d ON d.dept_id = m.dept_id
        LEFT JOIN spg_quality_helper h ON h.mc_id = m.machine_id
        LEFT JOIN item_mst im ON im.item_id = h.item_id
        LEFT JOIN spell_mst sp ON sp.spell_id = h.effective_from_spell_id
        WHERE m.active = 1
          AND mt.active = 1
          AND mt.machine_type_name = :spinning_type
          AND (:branch_id IS NULL OR d.branch_id = :branch_id)
        ORDER BY m.mech_code
        """
    )


def get_quality_map_yarns_query():
    """Active yarn items for the mapping dropdown (get_yarn_qualities_query join)."""
    return text(
        """
        SELECT
            ym.item_id,
            im.item_code,
            im.item_name,
            ym.jute_yarn_count AS std_count,
            ym.std_mr_pct
        FROM jute_yarn_mst ym
        JOIN item_mst im ON im.item_id = ym.item_id
        JOIN item_grp_mst ig ON ig.item_grp_id = im.item_grp_id
        WHERE ig.item_type_id = 4
          AND ig.co_id = :co_id
        ORDER BY im.item_name
        """
    )


def validate_spinning_machine_query():
    """Machine must be active AND of spinning type; returns its dept branch AND
    the branch's co — the lock gate / reprocess flag key on the machine's OWN
    co (spine-derived), never the caller-supplied body co_id (D3a)."""
    return text(
        """
        SELECT m.machine_id, d.branch_id, bm.co_id
        FROM machine_mst m
        INNER JOIN machine_type_mst mt ON mt.machine_type_id = m.machine_type_id
        INNER JOIN dept_mst d ON d.dept_id = m.dept_id
        INNER JOIN branch_mst bm ON bm.branch_id = d.branch_id
        WHERE m.machine_id = :machine_id
          AND m.active = 1
          AND mt.active = 1
          AND mt.machine_type_name = :spinning_type
        """
    )


def validate_yarn_item_query():
    """Item must exist active as a yarn (jute_yarn_mst + item_mst) under the co."""
    return text(
        """
        SELECT ym.item_id
        FROM jute_yarn_mst ym
        JOIN item_mst im ON im.item_id = ym.item_id
        JOIN item_grp_mst ig ON ig.item_grp_id = im.item_grp_id
        WHERE ym.item_id = :item_id
          AND im.active = 1
          AND ig.item_type_id = 4
          AND ig.co_id = :co_id
        """
    )


def get_spell_starting_time_query():
    """starting_time of the effective spell — the spell-order comparator."""
    return text(
        "SELECT starting_time FROM spell_mst WHERE spell_id = :spell_id"
    )


def get_next_change_point_query():
    """The machine's next active mapper change-point STRICTLY after this save's
    effective (date, spell-order) point — the retro range's upper cap. Run
    BEFORE the save's own mapper INSERT so the just-inserted row can never be
    its own cap (an equal point would not qualify anyway — strictly greater).
    NULL spell = day-start '00:00:00' on both sides of the comparison."""
    return text(
        """
        SELECT q.effective_from_date AS next_date,
               COALESCE(qs.starting_time, '00:00:00') AS next_start_time
        FROM spg_quality_mapper q
        LEFT JOIN spell_mst qs ON qs.spell_id = q.effective_from_spell_id
        WHERE q.mc_id = :mc_id
          AND q.active = 1
          AND (q.effective_from_date > :eff_date
               OR (q.effective_from_date = :eff_date
                   AND COALESCE(qs.starting_time, '00:00:00')
                       > COALESCE(:eff_start_time, '00:00:00')))
        ORDER BY q.effective_from_date ASC,
                 COALESCE(qs.starting_time, '00:00:00') ASC,
                 q.quality_mapper_id ASC
        LIMIT 1
        """
    )


def get_locked_units_in_retro_range_query():
    """DISTINCT locked (doff_date, spell) units a machine's retro range crosses.

    Mode-agnostic on purpose: crossing a locked unit needs Edit + an explicit
    reprocess flag regardless of how many rows the mode actually updates."""
    return text(
        f"""
        SELECT DISTINCT dd.doff_date AS tran_date, dd.spell AS spell_id
        FROM daily_doff_tbl dd
        LEFT JOIN spell_mst sp ON sp.spell_id = dd.spell
        INNER JOIN jute_prod_spinning_process_lock l
                ON l.tran_date = dd.doff_date
               AND l.spell_id = dd.spell
               AND l.co_id = :co_id
               AND l.is_locked = 1
               AND l.active = 1
        WHERE {_RETRO_SCOPE}
        """
    )


def count_retro_doff_rows_query(retro_mode: str):
    """Preview (confirm:false): count of rows the retro UPDATE would touch."""
    return text(
        f"""
        SELECT COUNT(*)
        FROM daily_doff_tbl dd
        LEFT JOIN spell_mst sp ON sp.spell_id = dd.spell
        WHERE {_RETRO_SCOPE}
          {_retro_mode_condition(retro_mode)}
        """
    )


def retro_update_doff_rows_query(retro_mode: str):
    """Scoped retro UPDATE — stamps item_id + item_source='mapper' (spec 5.3 step 4)."""
    return text(
        f"""
        UPDATE daily_doff_tbl dd
        LEFT JOIN spell_mst sp ON sp.spell_id = dd.spell
        SET dd.item_id = :item_id,
            dd.item_source = 'mapper',
            dd.updated_date_time = CURRENT_TIMESTAMP
        WHERE {_RETRO_SCOPE}
          {_retro_mode_condition(retro_mode)}
        """
    )


def insert_quality_mapper_query():
    """Append one mapper change-log row (retro_rows stamped after the UPDATE)."""
    return text(
        """
        INSERT INTO spg_quality_mapper
            (branch_id, mc_id, item_id, effective_from_date, effective_from_spell_id,
             retro_mode, retro_rows, active, updated_by)
        VALUES
            (:branch_id, :mc_id, :item_id, :eff_date, :eff_spell_id,
             :retro_mode, 0, 1, :updated_by)
        """
    )


def rederive_quality_helper_query():
    """Helper re-derivation on uq_sqh_mc — same transaction as the mapper
    INSERT (T3). NOT an unconditional upsert of the saved rule: a BACKDATED
    save must never regress the helper to an older rule, so the helper is
    rebuilt from the machine's LATEST active mapper row by
    (effective_from_date DESC, spell-order DESC, quality_mapper_id DESC) —
    the same ordering the as-of resolver uses. Derived-table form so the
    ON DUPLICATE KEY UPDATE can reference the SELECT's columns."""
    return text(
        """
        INSERT INTO spg_quality_helper
            (branch_id, mc_id, item_id, effective_from_date, effective_from_spell_id,
             quality_mapper_id, updated_by)
        SELECT latest.branch_id, latest.mc_id, latest.item_id,
               latest.effective_from_date, latest.effective_from_spell_id,
               latest.quality_mapper_id, :updated_by
        FROM (
            SELECT q.branch_id, q.mc_id, q.item_id, q.effective_from_date,
                   q.effective_from_spell_id, q.quality_mapper_id
            FROM spg_quality_mapper q
            LEFT JOIN spell_mst qs ON qs.spell_id = q.effective_from_spell_id
            WHERE q.mc_id = :mc_id AND q.active = 1
            ORDER BY q.effective_from_date DESC,
                     COALESCE(qs.starting_time, '00:00:00') DESC,
                     q.quality_mapper_id DESC
            LIMIT 1
        ) latest
        ON DUPLICATE KEY UPDATE
            branch_id = latest.branch_id,
            item_id = latest.item_id,
            effective_from_date = latest.effective_from_date,
            effective_from_spell_id = latest.effective_from_spell_id,
            quality_mapper_id = latest.quality_mapper_id,
            updated_by = :updated_by,
            updated_date_time = CURRENT_TIMESTAMP
        """
    )


def update_mapper_retro_rows_query():
    """Audit: stamp how many doff rows the retro update touched (spec 5.1)."""
    return text(
        """
        UPDATE spg_quality_mapper
        SET retro_rows = :retro_rows
        WHERE quality_mapper_id = :mapper_id
        """
    )
