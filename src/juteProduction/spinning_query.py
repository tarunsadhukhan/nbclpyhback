"""Raw SQL builders for the Spinning / Doff production entry feature (jute production module).

Mirrors drawing_query.py conventions: named binds, the ``:x IS NULL OR ...``
optional-filter idiom, and de-duplication left to the router where spell_code
fanout can occur. Reuses the mobile-app doff tables (daily_doff_tbl,
daily_doff_frames_winding) by raw SQL only — see SHARED BUILD SPEC for the exact
columns those tables expose.
"""

from sqlalchemy import bindparam, text


# =============================================================================
# Setup / lookup builders
# =============================================================================


def get_spinning_machines_query():
    """Spinning-type machines for a company (identity only).

    Machine standards/config (bobbin weight, spindles, speed) live in the
    time-versioned jute_prod_spng_target_map and are resolved per-date by the
    caller (resolve_param); this query no longer joins any attribute table.
    The :co_id bind is kept for caller compatibility (machine scope is by type).
    """
    return text(
        """
        SELECT
            m.machine_id,
            m.machine_name,
            m.mech_code,
            m.dept_id,
            d.dept_desc AS dept_name,
            d.branch_id
        FROM machine_mst m
        INNER JOIN machine_type_mst mt ON mt.machine_type_id = m.machine_type_id
        INNER JOIN dept_mst d ON d.dept_id = m.dept_id
        WHERE m.active = 1
          AND mt.active = 1
          AND mt.machine_type_name = :spinning_type
          AND (:branch_id IS NULL OR d.branch_id = :branch_id)
        ORDER BY m.mech_code
        """
    )


def get_spells_query():
    """Active spells with working hours from spell_mst (branch scoped via parent shift).

    Unlike the drawing variant this ALSO returns spell_id, because doff tables
    store spell_id (INT), not the spell_code string. Callers must de-duplicate by
    spell_code in Python (sls carries a duplicate A1 under a second branch's
    shift) keeping the first row per code.
    """
    return text(
        """
        SELECT sp.spell_id, sp.spell_code, sp.spell_name, sp.working_hours,
               sp.starting_time, sp.is_overnight, sp.shift_id
        FROM spell_mst sp
        INNER JOIN shift_mst sh ON sh.shift_id = sp.shift_id
        WHERE sp.status = 1
          AND COALESCE(sp.active, 1) = 1
          AND sh.status = 1
          AND (:branch_id IS NULL OR sh.branch_id = :branch_id)
        ORDER BY sp.starting_time
        """
    )


def resolve_spell_id_query():
    """Resolve a spell_code string to its canonical spell_id (MIN dedupes branch fanout)."""
    return text(
        """
        SELECT MIN(spell_id) AS spell_id
        FROM spell_mst
        WHERE spell_code = :spell_code AND status = 1
        """
    )


def get_trollies_query():
    """Trolly master rows (branch + machine-type optional). Keep busket_weight
    column name; alias bucket_weight in the response.

    :machine_type_name NULL -> all rows (master list). When a stage name is
    passed it resolves to its machine_type_id and filters strictly, so untagged
    (NULL) trolleys are excluded from that stage's page.
    """
    return text(
        """
        SELECT
            t.trolly_id,
            t.trolly_name,
            t.trolly_weight,
            t.busket_weight AS bucket_weight,
            t.trolly_posting_code,
            t.branch_id,
            COALESCE(t.trolly_type, 'T') AS trolly_type,
            t.machine_type_id,
            mt.machine_type_name
        FROM trolly_mst t
        LEFT JOIN machine_type_mst mt ON mt.machine_type_id = t.machine_type_id AND mt.active = 1
        WHERE (:branch_id IS NULL OR t.branch_id = :branch_id)
          AND (:machine_type_name IS NULL OR mt.machine_type_name = :machine_type_name)
        ORDER BY t.trolly_name
        """
    )


def get_yarn_qualities_query():
    """Active yarn ITEMS (item_type_id=4) — the single yarn identity.

    A yarn IS an item (item_mst); its editable data lives on jute_yarn_mst. Returns
    item_id (the canonical key, was yarn_quality_id), item_code/item_name from
    item_mst, std_count from jute_yarn_mst.jute_yarn_count, and std_mr_pct (exposed
    for the Spinning SQC corrected-count calculation).

    Company scope lives on item_grp_mst.co_id (item_mst has no co_id by design), so
    the dropdown MUST filter ig.co_id = :co_id — otherwise items that share a code
    across companies (e.g. "13-SKWP" under both co 1 and co 9) appear duplicated.
    The :branch_id bind is kept for caller compatibility but unused — a yarn has no
    branch.
    """
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
          AND (:branch_id IS NULL OR :branch_id IS NOT NULL)
        ORDER BY im.item_name
        """
    )


# =============================================================================
# Doff entry builders
# =============================================================================


def get_doff_running_total_query():
    """Running net total and doff count for a machine within co/date/spell_id.

    Used to pre-fill the running total and next doff number. active IN (1, NULL)
    keeps legacy rows that pre-date the active flag.
    """
    return text(
        """
        SELECT
            COALESCE(SUM(net_weight), 0) AS total_net,
            COUNT(*) AS doff_count
        FROM daily_doff_tbl
        WHERE doff_date = :tran_date
          AND spell = :spell_id
          AND mc_id = :machine_id
          AND (active = 1 OR active IS NULL)
        """
    )


def get_doff_entries_by_date_query():
    """Doff entries for the records grid (spell_id and machine optional).

    Yarn resolves from the doff row's OWN item_id only — stamping at post time
    (helper/mapper, spec 5.2) plus /doff_sync own item identity now; the old
    frames_winding fallback is retired. Also surfaces eb_id/eb_source/item_source
    and the operator display label (the eb identity is the HRMS employee; there
    is no eb_master table).

    eb_name arrives pre-concatenated as 'E1234 - Ramesh Das'. emp_code comes
    from a scalar subquery, NOT a join: hrms_ed_official_details can hold more
    than one row per eb (branch transfers), and a join would fan the doff grid
    out into duplicate rows.
    """
    return text(
        """
        SELECT
            dd.daily_doff_tbl_id,
            dd.branch_id,
            dd.doff_date,
            dd.spell AS spell_id,
            sp.spell_code,
            dd.mc_id,
            m.mech_code,
            m.machine_name,
            dd.trolly_id,
            t.trolly_name,
            dd.item_id,
            dd.item_source,
            im.item_code,
            im.item_name,
            dd.eb_id,
            dd.eb_source,
            CASE WHEN p.eb_id IS NULL THEN NULL
                 ELSE CONCAT_WS(' - ',
                          (SELECT NULLIF(TRIM(o.emp_code), '')
                             FROM hrms_ed_official_details o
                            WHERE o.eb_id = dd.eb_id AND o.active = 1
                            LIMIT 1),
                          CONCAT_WS(' ', NULLIF(TRIM(p.first_name), ''),
                                         NULLIF(TRIM(p.last_name), ''))
                      )
            END AS eb_name,
            dd.gross_weight,
            dd.tare_weight,
            dd.net_weight
        FROM daily_doff_tbl dd
        LEFT JOIN machine_mst m ON m.machine_id = dd.mc_id
        LEFT JOIN trolly_mst t ON t.trolly_id = dd.trolly_id
        LEFT JOIN (
            SELECT spell_code, MIN(spell_id) AS spell_id
            FROM spell_mst WHERE status = 1 GROUP BY spell_code
        ) sp ON sp.spell_id = dd.spell
        LEFT JOIN item_mst im ON im.item_id = dd.item_id
        LEFT JOIN hrms_ed_personal_details p ON p.eb_id = dd.eb_id
        WHERE dd.doff_date = :tran_date
          AND (dd.active = 1 OR dd.active IS NULL)
          AND (:spell_id IS NULL OR dd.spell = :spell_id)
          AND (:branch_id IS NULL OR dd.branch_id = :branch_id)
          AND (:machine_id IS NULL OR dd.mc_id = :machine_id)
        ORDER BY m.mech_code, dd.daily_doff_tbl_id
        """
    )


def get_exact_duplicate_doff_ids_query():
    """EXACT-duplicate doff rows to deactivate within a (date, spell) unit —
    spec 6 W10 hardening. A duplicate group = same mc_id + trolly_id +
    gross_weight + tare_weight; the LOWEST id per group is kept, the rest are
    returned for preview + deactivation (weights included for the D8 confirm
    dialog). NULL-safe (<=>) join so NULL trolly / weights group together the
    same way GROUP BY groups them. Legitimate multi-doff rows (different
    trolly or weights) are never touched. Co-scope rides the machine spine
    (D3c) on BOTH the group build and the row select — daily_doff_tbl has no
    co column."""
    return text(
        """
        SELECT dd.daily_doff_tbl_id, dd.mc_id, k.keep_id,
               dd.gross_weight, dd.tare_weight, dd.net_weight
        FROM daily_doff_tbl dd
        INNER JOIN (
            SELECT di.mc_id, di.trolly_id, di.gross_weight, di.tare_weight,
                   MIN(di.daily_doff_tbl_id) AS keep_id
            FROM daily_doff_tbl di
            WHERE di.doff_date = :tran_date
              AND di.spell = :spell_id
              AND (di.active = 1 OR di.active IS NULL)
              AND EXISTS (
                  SELECT 1
                  FROM machine_mst mi
                  INNER JOIN dept_mst dpi ON dpi.dept_id = mi.dept_id
                  INNER JOIN branch_mst bri ON bri.branch_id = dpi.branch_id
                  WHERE mi.machine_id = di.mc_id AND bri.co_id = :co_id
              )
            GROUP BY di.mc_id, di.trolly_id, di.gross_weight, di.tare_weight
            HAVING COUNT(*) > 1
        ) k ON k.mc_id = dd.mc_id
           AND k.trolly_id <=> dd.trolly_id
           AND k.gross_weight <=> dd.gross_weight
           AND k.tare_weight <=> dd.tare_weight
        WHERE dd.doff_date = :tran_date
          AND dd.spell = :spell_id
          AND (dd.active = 1 OR dd.active IS NULL)
          AND dd.daily_doff_tbl_id <> k.keep_id
        ORDER BY dd.daily_doff_tbl_id
        """
    )


def deactivate_doff_entries_query():
    """Soft-delete a preview-confirmed id list (expanding IN bind)."""
    return text(
        """
        UPDATE daily_doff_tbl
        SET active = 0, updated_date_time = NOW()
        WHERE daily_doff_tbl_id IN :ids
        """
    ).bindparams(bindparam("ids", expanding=True))


# =============================================================================
# Frame-map (daily_doff_frames_winding, spg_wdg = 'S') builders
# =============================================================================


def get_frame_map_query():
    """All Spinning machines with today's SAVED mapping + the frame's most recent
    saved mapping (any spell) as an unsaved-draft suggestion.

    Join is on mc_eb_id = machine_id (mc_eb_id holds machine_id for spinning rows),
    today's tran_date, the resolved spell_id, and active.

    item_id/item_code/item_name      = today's SAVED mapping for this spell (NULL when
                                       nothing saved yet).
    prev_item_id/prev_item_name/prev_date = the frame's most recent saved S-mapping
                                       across ANY spell/date, EXCLUDING the current
                                       (tran_date, spell_id) cell (correlated subquery,
                                       one row per machine, latest tran_date then id).
                                       Surfaced so the client can prefill the dropdown
                                       and flag it unsaved until the operator clicks
                                       Save Map. Lets a never-mapped spell (e.g. a new
                                       B1) bootstrap from the latest A1 setup.
    """
    return text(
        """
        SELECT
            m.machine_id,
            m.mech_code,
            m.machine_name,
            d.branch_id,
            f.daily_doff_frm_wdg_id,
            f.item_id,
            im.item_code,
            im.item_name,
            (
                SELECT p.item_id
                FROM daily_doff_frames_winding p
                WHERE p.mc_eb_id = m.machine_id
                  AND p.spg_wdg = 'S'
                  AND (p.active = 1 OR p.active IS NULL)
                  AND NOT (p.tran_date = :tran_date AND p.spell_id = :spell_id)
                ORDER BY p.tran_date DESC, p.daily_doff_frm_wdg_id DESC
                LIMIT 1
            ) AS prev_item_id,
            (
                SELECT pim.item_name
                FROM daily_doff_frames_winding p
                JOIN item_mst pim ON pim.item_id = p.item_id
                WHERE p.mc_eb_id = m.machine_id
                  AND p.spg_wdg = 'S'
                  AND (p.active = 1 OR p.active IS NULL)
                  AND NOT (p.tran_date = :tran_date AND p.spell_id = :spell_id)
                ORDER BY p.tran_date DESC, p.daily_doff_frm_wdg_id DESC
                LIMIT 1
            ) AS prev_item_name,
            (
                SELECT p.tran_date
                FROM daily_doff_frames_winding p
                WHERE p.mc_eb_id = m.machine_id
                  AND p.spg_wdg = 'S'
                  AND (p.active = 1 OR p.active IS NULL)
                  AND NOT (p.tran_date = :tran_date AND p.spell_id = :spell_id)
                ORDER BY p.tran_date DESC, p.daily_doff_frm_wdg_id DESC
                LIMIT 1
            ) AS prev_date
        FROM machine_mst m
        INNER JOIN machine_type_mst mt ON mt.machine_type_id = m.machine_type_id
        INNER JOIN dept_mst d ON d.dept_id = m.dept_id
        LEFT JOIN daily_doff_frames_winding f
               ON f.mc_eb_id = m.machine_id
              AND f.spg_wdg = 'S'
              AND f.tran_date = :tran_date
              AND f.spell_id = :spell_id
              AND (f.active = 1 OR f.active IS NULL)
        LEFT JOIN item_mst im ON im.item_id = f.item_id
        WHERE m.active = 1
          AND mt.active = 1
          AND mt.machine_type_name = :spinning_type
          AND (:branch_id IS NULL OR d.branch_id = :branch_id)
        ORDER BY m.mech_code
        """
    )


def get_frame_map_active_row_query():
    """The active S-row id for one machine on a tran_date/spell_id (upsert lookup)."""
    return text(
        """
        SELECT daily_doff_frm_wdg_id
        FROM daily_doff_frames_winding
        WHERE spg_wdg = 'S'
          AND tran_date = :tran_date
          AND spell_id = :spell_id
          AND mc_eb_id = :machine_id
          AND (active = 1 OR active IS NULL)
        ORDER BY daily_doff_frm_wdg_id DESC
        LIMIT 1
        """
    )


def update_frame_map_row_query():
    """Update an existing active S-row's quality mapping (stamps who/when)."""
    return text(
        """
        UPDATE daily_doff_frames_winding
        SET item_id = :item_id,
            updated_by = :updated_by,
            updated_date_time = NOW()
        WHERE daily_doff_frm_wdg_id = :id
        """
    )


def insert_frame_map_row_query():
    """Insert a fresh active S-row for a machine's quality mapping (stamps who/when)."""
    return text(
        """
        INSERT INTO daily_doff_frames_winding
            (tran_date, spell, spell_id, mc_eb_id, item_id,
             spg_wdg, branch_id, active, updated_by, updated_date_time)
        VALUES
            (:tran_date, :spell, :spell_id, :machine_id, :item_id,
             'S', :branch_id, 1, :updated_by, NOW())
        """
    )


def get_frame_map_last_updated_query():
    """The most recent save timestamp across a branch's active S-mapping rows.

    Surfaced in the Frame -> Quality grid so the operator can see when the branch's
    mapping was last touched. Branch-scoped (NULL branch_id = whole tenant)."""
    return text(
        """
        SELECT MAX(updated_date_time) AS last_updated
        FROM daily_doff_frames_winding
        WHERE spg_wdg = 'S'
          AND (active = 1 OR active IS NULL)
          AND (:branch_id IS NULL OR branch_id = :branch_id)
        """
    )


# =============================================================================
# Doff identity stamping (spec 5.2) + Sync (spec 5.4) builders
# =============================================================================

# Mapper as-of applicability: the mapper row's effective point (date, spell-order)
# must be <= the doff's (tran_date, spell). Spell order within a day =
# spell_mst.starting_time (sibling convention: spinning_quality_map_query.py);
# effective_from_spell_id NULL = start of day; a NULL :spell_start (doff spell
# without a starting_time) sorts as end of day, so every same-date rule applies.
_MAPPER_ASOF_WHERE = """
              q.active = 1
              AND (q.effective_from_date < :tran_date
                   OR (q.effective_from_date = :tran_date
                       AND (q.effective_from_spell_id IS NULL
                            OR :spell_start IS NULL
                            OR qs.starting_time <= :spell_start)))
"""

_MAPPER_ASOF_ORDER = """
              q.effective_from_date DESC,
              COALESCE(qs.starting_time, '00:00:00') DESC,
              q.quality_mapper_id DESC
"""


def get_helper_item_query():
    """Current-state helper row for one machine (fast path — today's doffs).

    Also returns the rule's effective point (effective_from_date + the
    effective spell's starting_time) so the caller can verify the helper
    actually APPLIES to the doff's (tran_date, spell) — a rule effective from
    a later spell today must not stamp an earlier spell's doff (D4)."""
    return text(
        """
        SELECT h.item_id, im.item_name, h.effective_from_date,
               hs.starting_time AS effective_start_time
        FROM spg_quality_helper h
        LEFT JOIN item_mst im ON im.item_id = h.item_id
        LEFT JOIN spell_mst hs ON hs.spell_id = h.effective_from_spell_id
        WHERE h.mc_id = :mc_id
        """
    )


def get_mapper_asof_item_query():
    """As-of mapper resolution for ONE machine at (tran_date, spell) — the
    backdated path (spec 5.2.2). NEVER the helper: it holds today's state."""
    return text(
        f"""
        SELECT q.item_id, im.item_name
        FROM spg_quality_mapper q
        LEFT JOIN spell_mst qs ON qs.spell_id = q.effective_from_spell_id
        LEFT JOIN item_mst im ON im.item_id = q.item_id
        WHERE q.mc_id = :mc_id
          AND {_MAPPER_ASOF_WHERE}
        ORDER BY {_MAPPER_ASOF_ORDER}
        LIMIT 1
        """
    )


# One as-of winner per machine (ROW_NUMBER rn=1) — the set-based form the sync
# UPDATE joins against.
_MAPPER_ASOF_ALL_SQL = f"""
            SELECT t.mc_id, t.item_id
            FROM (
                SELECT q.mc_id, q.item_id,
                       ROW_NUMBER() OVER (
                           PARTITION BY q.mc_id
                           ORDER BY {_MAPPER_ASOF_ORDER}
                       ) AS rn
                FROM spg_quality_mapper q
                LEFT JOIN spell_mst qs ON qs.spell_id = q.effective_from_spell_id
                WHERE {_MAPPER_ASOF_WHERE}
            ) t
            WHERE t.rn = 1
"""

# Sync scope = the unit's active SPG1 doff rows (branch optional).
# daily_doff_tbl has no co column, so co-scope rides the machine's
# dept -> branch -> co spine (D3b) — without it a sync would stamp another
# company's rows for the same (date, spell). EXISTS form so the one shared
# fragment works inside UPDATE and SELECT statements alike.
_SYNC_SCOPE_WHERE = """
          d.doff_date = :tran_date
          AND d.spell = :spell_id
          AND (d.active = 1 OR d.active IS NULL)
          AND d.weight_type = 'SPG1'
          AND (:branch_id IS NULL OR d.branch_id = :branch_id)
          AND EXISTS (
              SELECT 1
              FROM machine_mst mm
              INNER JOIN dept_mst dmm ON dmm.dept_id = mm.dept_id
              INNER JOIN branch_mst bmm ON bmm.branch_id = dmm.branch_id
              WHERE mm.machine_id = d.mc_id AND bmm.co_id = :co_id
          )
"""


def sync_quality_stamp_query():
    """Stamp item_id from the mapper as-of resolution onto the unit's doff rows.

    :force = 0 (fill): only item_id IS NULL rows. :force = 1: every row whose
    item_source is not 'manual' (manual rows are NEVER touched in ANY mode)."""
    return text(
        f"""
        UPDATE daily_doff_tbl d
        INNER JOIN (
        {_MAPPER_ASOF_ALL_SQL}
        ) mp ON mp.mc_id = d.mc_id
        SET d.item_id = mp.item_id,
            d.item_source = 'mapper',
            d.updated_date_time = NOW()
        WHERE {_SYNC_SCOPE_WHERE}
          AND ((:force = 0 AND d.item_id IS NULL)
               OR (:force = 1 AND (d.item_source IS NULL OR d.item_source <> 'manual')))
        """
    )


def get_sync_item_override_preview_query():
    """force-mode preview: rows whose stamped item would CHANGE (item_overridden
    exception) — non-manual rows already carrying a different item_id."""
    return text(
        f"""
        SELECT d.daily_doff_tbl_id, d.mc_id,
               d.item_id AS old_item_id, mp.item_id AS new_item_id
        FROM daily_doff_tbl d
        INNER JOIN (
        {_MAPPER_ASOF_ALL_SQL}
        ) mp ON mp.mc_id = d.mc_id
        WHERE {_SYNC_SCOPE_WHERE}
          AND d.item_id IS NOT NULL
          AND (d.item_source IS NULL OR d.item_source <> 'manual')
          AND d.item_id <> mp.item_id
        ORDER BY d.daily_doff_tbl_id
        """
    )


# The doff's operator is the SPINNER on the frame. PREFIX match, never
# substring: sls carries 'SPINNER (F)' / 'SPINNER (C)' (the operator) alongside
# 'EXTRA SPINNER@1/8 FRM (F)' — a relief hand bulk-assigned across 8+ frames at
# once. Measured on sls 2026-01-02 br-29: substring left 16 of 23 frames with
# two candidates; the prefix resolves 23/23 (and 22/22 on the other spell) to
# exactly one eb. Exact '=' matches nothing — every desig carries an (F)/(C)
# suffix.
SPINNER_DESIG_PREFIX = "spinner%"


def get_operator_candidates_query():
    """Operator candidates per machine for one (date, spell_id, branch) unit.

    daily_ebmc_attendance (mc_id, is_active) joined to daily_attendance by
    daily_atten_id; date/spell/branch predicates live on the HEADER — branch via
    da.branch_id NEVER dea.branch_id (mobile leaves it NULL, spec T11).

    Spell joins on spell_id, NOT the spell name: spell_code repeats once per
    shift generation (sls 'A1' = 91/97/102), so a name join silently rakes in
    another generation's attendance rows.

    Designation gate = the SPINNER_DESIG_PREFIX match on designation_mst.desig,
    with the ignore_designation escape. It replaces the old on_machine = 'Yes'
    gate, which stamped ZERO operators on sls silently: that tenant has no 'Yes'
    value at all ('Y'/'N'/''/'No') and flags all 64 of its spinning designations
    'N'. Cascade + ambiguity handled in Python."""
    return text(
        """
        SELECT DISTINCT dea.mc_id, da.eb_id, da.daily_atten_id
        FROM daily_ebmc_attendance dea
        INNER JOIN daily_attendance da
                ON da.daily_atten_id = dea.daily_atten_id
               AND da.is_active = 1
               AND da.attendance_date = :tran_date
               AND da.spell_id = :spell_id
               AND (:branch_id IS NULL OR da.branch_id = :branch_id)
        LEFT JOIN designation_mst dm
                ON dm.designation_id = da.worked_designation_id
        WHERE dea.is_active = 1
          AND (:ignore_designation = 1
               OR LOWER(COALESCE(dm.desig, '')) LIKE :desig_prefix)
        ORDER BY dea.mc_id, da.daily_atten_id
        """
    )


def stamp_operator_query():
    """Stamp one resolved eb_id onto one machine's doff rows in the unit.

    fill: only eb_id IS NULL rows. force: every row whose eb_source is not
    'manual' — manual rows are NEVER touched in ANY mode (spec T9)."""
    return text(
        f"""
        UPDATE daily_doff_tbl d
        SET d.eb_id = :eb_id,
            d.eb_source = 'sync',
            d.updated_date_time = NOW()
        WHERE {_SYNC_SCOPE_WHERE}
          AND d.mc_id = :mc_id
          AND ((:force = 0 AND d.eb_id IS NULL)
               OR (:force = 1 AND (d.eb_source IS NULL OR d.eb_source <> 'manual')))
        """
    )


def get_sync_scope_summary_query():
    """Per-machine post-sync summary of the unit: rows still without item / eb.
    Feeds the machines_unmapped / doffs_no_operator / bobbin_missing exceptions."""
    return text(
        f"""
        SELECT d.mc_id,
               COUNT(*) AS doff_rows,
               SUM(CASE WHEN d.item_id IS NULL THEN 1 ELSE 0 END) AS null_item_rows,
               SUM(CASE WHEN d.eb_id IS NULL THEN 1 ELSE 0 END) AS null_eb_rows
        FROM daily_doff_tbl d
        WHERE {_SYNC_SCOPE_WHERE}
        GROUP BY d.mc_id
        """
    )


def get_machine_codes_query():
    """mech_code lookup for an id list (W7 attendance_no_doffs display)."""
    return text(
        "SELECT machine_id, mech_code FROM machine_mst WHERE machine_id IN :ids"
    ).bindparams(bindparam("ids", expanding=True))


def get_active_workers_query():
    """Active branch workers for the Doff Data Editor operator picker (spec 5.8).

    hrms_ed_official_details (active, branch scope, emp_code) joined to
    hrms_ed_personal_details for the display name — the weaving eb-list pattern
    (get_weaving_eb_list_query).

    Emits ONE ready-to-render label, 'E1234 - Ramesh Das'. CONCAT_WS drops a
    NULL/blank emp_code (NULLIF) instead of leaving a dangling ' - ', so the
    caller never re-assembles parts."""
    return text(
        """
        SELECT o.eb_id,
               CONCAT_WS(' - ',
                   NULLIF(TRIM(o.emp_code), ''),
                   CONCAT_WS(' ', NULLIF(TRIM(p.first_name), ''),
                                  NULLIF(TRIM(p.last_name), ''))
               ) AS worker_name
        FROM hrms_ed_official_details o
        INNER JOIN hrms_ed_personal_details p ON p.eb_id = o.eb_id AND p.active = 1
        WHERE o.active = 1
          AND (:branch_id IS NULL OR o.branch_id = :branch_id)
        ORDER BY worker_name
        """
    )


# =============================================================================
# Day-slice + Process/Lock builders (weaving Phase-1 pattern)
# =============================================================================


# Driver for the day slice + Process probes (spec 5.5.2).
#
# Source of truth = the stamped item_id on the day's doff rows, grouped
# (mc_id, spell, item_id) — item comes from the ROW, no frames_winding join.
# UNION branch = helper rows for mapped-but-idle spinning machines, included
# ONLY when :tran_date = CURRENT_DATE() (the helper holds today's state;
# past-day idle frames simply have no row, spec T13). Idle = zero active doffs
# for the (machine, spell); a machine that produced a DIFFERENT item is not
# idle. Helper has no spell grain (D9 pending), so idle rows fan across the
# canonical spell set (MIN spell_id per code — the same dedupe
# resolve_spell_id applies); callers filter :spell_id, so freeze/Process see
# exactly one. Day filter stays FIRST inside the driver WHERE. TRIPWIRE:
# moving :tran_date out of the driver WHERE re-materializes full history — do
# not "optimize" it away. Emits the legacy alias mc_eb_id so downstream joins
# stay untouched.
_SLICE_DRIVER_SQL = """
                            SELECT dd.mc_id AS mc_eb_id, dd.spell AS spell_id,
                                   dd.item_id AS item_id
                            FROM daily_doff_tbl dd
                            WHERE dd.doff_date = :tran_date
                              AND (dd.active = 1 OR dd.active IS NULL)
                              AND dd.item_id IS NOT NULL
                            GROUP BY dd.mc_id, dd.spell, dd.item_id
                            UNION
                            SELECT h.mc_id, spx.spell_id, h.item_id
                            FROM spg_quality_helper h
                            INNER JOIN (
                                SELECT MIN(spell_id) AS spell_id
                                FROM spell_mst WHERE status = 1
                                GROUP BY spell_code
                            ) spx ON 1 = 1
                            WHERE :tran_date = CURRENT_DATE()
                              AND NOT EXISTS (
                                  SELECT 1 FROM daily_doff_tbl dx
                                  WHERE dx.doff_date = :tran_date
                                    AND dx.mc_id = h.mc_id
                                    AND dx.spell = spx.spell_id
                                    AND (dx.active = 1 OR dx.active IS NULL)
                              )
"""


def spinning_day_slice_sql() -> str:
    """Day-sliced planning-grid compute — the request-path replacement for BOTH the
    per-row resolver N+1 and the unbounded winding-reconciliation view read.

    (The retired winding-reconciliation and spinning-planning-grid view names are
    described, not spelled, so the unbounded-view CI tripwire's bare-name match does
    not false-trip on this docstring — do NOT re-add the literal vw_ tokens here.)

    Structure mirrors the spinning-planning-grid reference oracle view (the REFERENCE
    ORACLE — never read in app code) with three deliberate changes:
      1. The driver is _SLICE_DRIVER_SQL (stamped doff rows grouped
         mc/spell/item UNION today-only helper idle rows) — day-filtered FIRST,
         so nothing accumulates over history (tripwire above).
      2. Correlated per-row probes become once-per-request derived tables:
         tmm/tmq (ROW_NUMBER rn=1 last-date target-map pivots, keyed machine/item),
         cnt (count AVG), dff (doff SUM keyed mc/spell/item — the driver grain),
         wnd (day-scoped winding reconciliation with set-based jugar MAX lookups
         instead of correlated subqueries; the jugar lookups key on BRANCH (not
         co_id — a branch belongs to one company) so one branch's leftover never
         adjusts another's doff; PERSON-keyed on jute_prod_winding_doff
         .eb_id and co/branch-scoped from the doff row itself — the old
         machine_mst/dept_mst/branch_mst spine would drop every person-keyed row
         and silently zero winding_total, hence eff_winding).
      3. Minutes attribution (spec 5.5.4 / W6): single-item frame/spell keeps the
         full spell minutes; a multi-item (mid-shift) frame splits minutes by
         item_net / frame_net weight share (dff carries frame_net via a window
         SUM). Idle helper rows (no dff row) keep full minutes.
    The window allocation (act_prod_wind) is day-bounded — the partition only ever
    contains this slice's rows, which is why a window function is allowed here.
    Binds: :co_id :tran_date :spell_id (nullable) :branch_id (nullable)
    :spinning_type.
    """
    return f"""
        SELECT
            eff.co_id, eff.branch_id, eff.tran_date, eff.spell_id, eff.spell_code,
            eff.shift_bucket, eff.machine_id, eff.mech_code, eff.machine_name,
            eff.item_id, eff.item_code, eff.item_name,
            eff.spindles, eff.minutes, eff.act_count, eff.std_count,
            eff.std_speed, eff.actual_speed, eff.target_speed,
            eff.std_tpi, eff.actual_tpi, eff.target_tpi,
            eff.std_eff, eff.target_eff,
            eff.p100prod, eff.std_prod, eff.target_prod,
            eff.act_prod_doff, eff.winding_total, eff.act_prod_wind, eff.eff_doff,
            COALESCE(ROUND(eff.act_prod_wind / NULLIF(eff.p100prod, 0) * 100, 2), 0) AS eff_winding
        FROM (
            SELECT
                calc.*,
                COALESCE(
                    ROUND(
                        calc.winding_total * calc.act_prod_doff
                        / NULLIF(SUM(calc.act_prod_doff) OVER (
                            PARTITION BY calc.co_id, calc.tran_date, calc.item_id, calc.shift_bucket
                          ), 0),
                        3
                    ), 0
                ) AS act_prod_wind
            FROM (
                SELECT
                    r.*,
                    ROUND(r.p100prod * r.std_eff / 100, 3) AS std_prod,
                    ROUND(r.p100prod * r.target_eff / 100, 3) AS target_prod,
                    COALESCE(ROUND(r.act_prod_doff / NULLIF(r.p100prod, 0) * 100, 2), 0) AS eff_doff
                FROM (
                    SELECT
                        b.*,
                        COALESCE(
                            ROUND(
                                (b.std_speed * b.minutes * b.act_count * b.spindles)
                                / (36 * 14400 * 2.2046 * NULLIF(b.std_tpi, 0)),
                                0
                            ), 0
                        ) AS p100prod
                    FROM (
                        SELECT
                            bm.co_id AS co_id,
                            d.branch_id AS branch_id,
                            :tran_date AS tran_date,
                            f.spell_id AS spell_id,
                            sp.spell_code AS spell_code,
                            LEFT(sp.spell_code, 1) AS shift_bucket,
                            f.mc_eb_id AS machine_id,
                            m.mech_code AS mech_code,
                            m.machine_name AS machine_name,
                            f.item_id AS item_id,
                            im.item_code AS item_code,
                            im.item_name AS item_name,
                            CAST(COALESCE(tmm.spindles_raw, 0) AS SIGNED) AS spindles,
                            CAST(ROUND(
                                (CASE
                                    WHEN sp.working_hours IS NOT NULL THEN sp.working_hours * 60
                                    WHEN sp.spell_code = 'A1' THEN 300
                                    WHEN sp.spell_code = 'A2' THEN 180
                                    ELSE 0
                                END)
                                * COALESCE(dff.act_prod_doff / NULLIF(dff.frame_net, 0), 1)
                            ) AS SIGNED) AS minutes,
                            COALESCE(cnt.act_count, 0) AS act_count,
                            COALESCE(ym.jute_yarn_count, 0) AS std_count,
                            COALESCE(tmm.std_speed_raw, 0) AS std_speed,
                            COALESCE(tmm.actual_speed_raw, 0) AS actual_speed,
                            COALESCE(tmm.target_speed_raw, 0) AS target_speed,
                            COALESCE(tmq.std_tpi_raw, 0) AS std_tpi,
                            COALESCE(tmq.actual_tpi_raw, 0) AS actual_tpi,
                            COALESCE(tmq.target_tpi_raw, 0) AS target_tpi,
                            COALESCE(tmq.std_eff_raw, 0) AS std_eff,
                            COALESCE(tmq.target_eff_raw, 0) AS target_eff,
                            COALESCE(dff.act_prod_doff, 0) AS act_prod_doff,
                            COALESCE(wnd.winding_total, 0) AS winding_total
                        FROM (
{_SLICE_DRIVER_SQL}
                        ) f
                        INNER JOIN machine_mst m ON m.machine_id = f.mc_eb_id
                        INNER JOIN machine_type_mst mt
                                ON mt.machine_type_id = m.machine_type_id
                               AND mt.active = 1
                               AND mt.machine_type_name = :spinning_type
                        INNER JOIN dept_mst d ON d.dept_id = m.dept_id
                        INNER JOIN branch_mst bm ON bm.branch_id = d.branch_id
                        LEFT JOIN (
                            SELECT spell_id, spell_code, working_hours
                            FROM spell_mst WHERE status = 1
                        ) sp ON sp.spell_id = f.spell_id
                        LEFT JOIN item_mst im ON im.item_id = f.item_id
                        LEFT JOIN jute_yarn_mst ym ON ym.item_id = f.item_id
                        LEFT JOIN (
                            SELECT t.ref_id,
                                   MAX(CASE WHEN t.value_role = 'standard' AND t.param = 'spindles' THEN t.value END) AS spindles_raw,
                                   MAX(CASE WHEN t.value_role = 'standard' AND t.param = 'speed' THEN t.value END) AS std_speed_raw,
                                   MAX(CASE WHEN t.value_role = 'actual'   AND t.param = 'speed' THEN t.value END) AS actual_speed_raw,
                                   MAX(CASE WHEN t.value_role = 'target'   AND t.param = 'speed' THEN t.value END) AS target_speed_raw
                            FROM (
                                SELECT t2.ref_id, t2.value_role, t2.param, t2.value,
                                       ROW_NUMBER() OVER (
                                           PARTITION BY t2.ref_id, t2.value_role, t2.param
                                           ORDER BY t2.effective_date DESC, t2.spng_target_map_id DESC
                                       ) AS rn
                                FROM jute_prod_spng_target_map t2
                                WHERE t2.co_id = :co_id AND t2.id_type = 'mcid'
                                  AND t2.param IN ('speed', 'spindles')
                                  AND t2.value_role IN ('standard', 'target', 'actual')
                                  AND t2.active = 1 AND t2.effective_date <= :tran_date
                            ) t
                            WHERE t.rn = 1
                            GROUP BY t.ref_id
                        ) tmm ON tmm.ref_id = f.mc_eb_id
                        LEFT JOIN (
                            SELECT t.ref_id,
                                   MAX(CASE WHEN t.value_role = 'standard' AND t.param = 'tpi' THEN t.value END) AS std_tpi_raw,
                                   MAX(CASE WHEN t.value_role = 'actual'   AND t.param = 'tpi' THEN t.value END) AS actual_tpi_raw,
                                   MAX(CASE WHEN t.value_role = 'target'   AND t.param = 'tpi' THEN t.value END) AS target_tpi_raw,
                                   MAX(CASE WHEN t.value_role = 'standard' AND t.param = 'eff' THEN t.value END) AS std_eff_raw,
                                   MAX(CASE WHEN t.value_role = 'target'   AND t.param = 'eff' THEN t.value END) AS target_eff_raw
                            FROM (
                                SELECT t2.ref_id, t2.value_role, t2.param, t2.value,
                                       ROW_NUMBER() OVER (
                                           PARTITION BY t2.ref_id, t2.value_role, t2.param
                                           ORDER BY t2.effective_date DESC, t2.spng_target_map_id DESC
                                       ) AS rn
                                FROM jute_prod_spng_target_map t2
                                WHERE t2.co_id = :co_id AND t2.id_type = 'qid'
                                  AND t2.param IN ('tpi', 'eff')
                                  AND t2.value_role IN ('standard', 'target', 'actual')
                                  AND t2.active = 1 AND t2.effective_date <= :tran_date
                            ) t
                            WHERE t.rn = 1
                            GROUP BY t.ref_id
                        ) tmq ON tmq.ref_id = f.item_id
                        LEFT JOIN (
                            SELECT item_id, AVG(observed_count) AS act_count
                            FROM jute_sqc_spinning_count
                            WHERE co_id = :co_id AND entry_date = :tran_date AND active = 1
                            GROUP BY item_id
                        ) cnt ON cnt.item_id = f.item_id
                        LEFT JOIN (
                            SELECT mc_id, spell, item_id,
                                   SUM(net_weight) AS act_prod_doff,
                                   SUM(SUM(net_weight)) OVER (
                                       PARTITION BY mc_id, spell
                                   ) AS frame_net
                            FROM daily_doff_tbl
                            WHERE doff_date = :tran_date
                              AND (active = 1 OR active IS NULL)
                              AND item_id IS NOT NULL
                            GROUP BY mc_id, spell, item_id
                        ) dff ON dff.mc_id = f.mc_eb_id AND dff.spell = f.spell_id
                             AND dff.item_id = f.item_id
                        LEFT JOIN (
                            SELECT wdr.item_id,
                                   LEFT(wsp.spell_code, 1) AS shift_bucket,
                                   SUM(wdr.reconciled_qty) AS winding_total
                            FROM (
                                SELECT wd.co_id, wd.branch_id AS branch_id,
                                       wd.spell_id, wd.eb_id, wd.item_id,
                                       SUM(wd.production_qty)
                                       - COALESCE(MAX(jo.open_w), 0)
                                       + COALESCE(MAX(jc.close_w), 0) AS reconciled_qty
                                FROM jute_prod_winding_doff wd
                                LEFT JOIN (
                                    SELECT branch_id, spell_id, eb_id, MAX(weight) AS open_w
                                    FROM jute_prod_winding_jugar
                                    WHERE tran_date = :tran_date AND open_close = 'O' AND active = 1
                                    GROUP BY branch_id, spell_id, eb_id
                                ) jo ON jo.branch_id = wd.branch_id
                                    AND jo.spell_id = wd.spell_id AND jo.eb_id = wd.eb_id
                                LEFT JOIN (
                                    SELECT branch_id, spell_id, eb_id, MAX(weight) AS close_w
                                    FROM jute_prod_winding_jugar
                                    WHERE tran_date = :tran_date AND open_close = 'C' AND active = 1
                                    GROUP BY branch_id, spell_id, eb_id
                                ) jc ON jc.branch_id = wd.branch_id
                                    AND jc.spell_id = wd.spell_id AND jc.eb_id = wd.eb_id
                                WHERE wd.active = 1
                                  AND wd.tran_date = :tran_date
                                  AND wd.co_id = :co_id
                                GROUP BY wd.co_id, wd.branch_id, wd.spell_id, wd.eb_id, wd.item_id
                            ) wdr
                            INNER JOIN spell_mst wsp ON wsp.spell_id = wdr.spell_id
                            WHERE (:branch_id IS NULL OR wdr.branch_id = :branch_id OR wdr.branch_id IS NULL)
                            GROUP BY wdr.item_id, LEFT(wsp.spell_code, 1)
                        ) wnd ON wnd.item_id = f.item_id AND wnd.shift_bucket = LEFT(sp.spell_code, 1)
                        WHERE bm.co_id = :co_id
                          AND (:spell_id IS NULL OR f.spell_id = :spell_id)
                          AND (:branch_id IS NULL OR d.branch_id = :branch_id)
                    ) b
                ) r
            ) calc
        ) eff
    """


def get_spinning_planning_slice_query():
    """The slice as an executable, ordered like the old driver (mech_code, spell)."""
    return text(spinning_day_slice_sql() + "\n        ORDER BY eff.mech_code, eff.spell_id")


def get_spinning_unmapped_produced_machines_query():
    """BLOCK probe B1 (spec 5.5.3): active doff rows in the unit with
    item_id IS NULL — after stamping-at-post + fill-sync, NULL means unmapped at
    post time and unrepaired (no COALESCE, no frames_winding join).

    daily_doff_tbl has no co column, so co-scope rides the machine's
    dept -> branch -> co spine (bm.co_id = :co_id) — otherwise another co's
    unmapped rows would 400-block this co's Process."""
    return text(
        """
        SELECT dd.mc_id AS machine_id, m.mech_code
        FROM daily_doff_tbl dd
        INNER JOIN machine_mst m ON m.machine_id = dd.mc_id
        INNER JOIN dept_mst d ON d.dept_id = m.dept_id
        INNER JOIN branch_mst bm ON bm.branch_id = d.branch_id
        WHERE dd.doff_date = :tran_date
          AND dd.spell = :spell_id
          AND (dd.active = 1 OR dd.active IS NULL)
          AND dd.item_id IS NULL
          AND bm.co_id = :co_id
        GROUP BY dd.mc_id, m.mech_code
        """
    )


def get_spinning_process_no_standard_query():
    """WARN probe: unit driver rows (stamped doff mc/spell/item + today-only
    helper idle rows) missing a std speed (machine) or a std tpi (item) as of
    the tran_date."""
    return text(
        f"""
        SELECT f.mc_eb_id AS machine_id, m.mech_code, f.item_id
        FROM (
{_SLICE_DRIVER_SQL}
        ) f
        LEFT JOIN machine_mst m ON m.machine_id = f.mc_eb_id
        LEFT JOIN jute_prod_spng_target_map spd
               ON spd.co_id = :co_id AND spd.id_type = 'mcid' AND spd.param = 'speed'
              AND spd.value_role = 'standard' AND spd.ref_id = f.mc_eb_id
              AND spd.active = 1 AND spd.effective_date <= :tran_date
        LEFT JOIN jute_prod_spng_target_map tpi
               ON tpi.co_id = :co_id AND tpi.id_type = 'qid' AND tpi.param = 'tpi'
              AND tpi.value_role = 'standard' AND tpi.ref_id = f.item_id
              AND tpi.active = 1 AND tpi.effective_date <= :tran_date
        WHERE f.spell_id = :spell_id
        GROUP BY f.mc_eb_id, m.mech_code, f.item_id
        HAVING COUNT(spd.spng_target_map_id) = 0 OR COUNT(tpi.spng_target_map_id) = 0
        """
    )


def get_spinning_process_no_count_query():
    """WARN probe: unit driver items with no SQC count observation for the day."""
    return text(
        f"""
        SELECT f.item_id, MIN(m.mech_code) AS mech_code
        FROM (
{_SLICE_DRIVER_SQL}
        ) f
        LEFT JOIN machine_mst m ON m.machine_id = f.mc_eb_id
        LEFT JOIN jute_sqc_spinning_count c
               ON c.co_id = :co_id AND c.item_id = f.item_id
              AND c.entry_date = :tran_date AND c.active = 1
        WHERE f.spell_id = :spell_id
        GROUP BY f.item_id
        HAVING COUNT(c.spinning_sqc_count_id) = 0
        """
    )


def get_spinning_attendance_inactive_query():
    """WARN probe W11: sync-stamped eb_id whose backing attendance is now
    is_active = 0 or status rejected (status_id 4) — i.e. no live matching
    daily_attendance row remains for (eb, date, spell name).

    Scoped to eb_source = 'sync' rows: those are the ones attendance backed;
    manual stamps are a supervisor's word, not an attendance row's. Co-scope via
    the machine spine (daily_doff_tbl has no co column). Spell joins on spell_id
    — same key as the operator cascade, for the same reason (spell_code repeats
    per shift generation, so a name join spans generations)."""
    return text(
        """
        SELECT dd.daily_doff_tbl_id, dd.mc_id AS machine_id, dd.eb_id
        FROM daily_doff_tbl dd
        INNER JOIN machine_mst m ON m.machine_id = dd.mc_id
        INNER JOIN dept_mst d ON d.dept_id = m.dept_id
        INNER JOIN branch_mst bm ON bm.branch_id = d.branch_id
        WHERE dd.doff_date = :tran_date
          AND dd.spell = :spell_id
          AND (dd.active = 1 OR dd.active IS NULL)
          AND bm.co_id = :co_id
          AND dd.eb_id IS NOT NULL
          AND dd.eb_source = 'sync'
          AND NOT EXISTS (
              SELECT 1 FROM daily_attendance da
              WHERE da.eb_id = dd.eb_id
                AND da.attendance_date = :tran_date
                AND da.spell_id = :spell_id
                AND da.is_active = 1
                AND (da.status_id IS NULL OR CAST(da.status_id AS UNSIGNED) <> 4)
          )
        ORDER BY dd.daily_doff_tbl_id
        """
    )


def soft_delete_spinning_log_for_unit_query():
    """Soft-delete existing active frozen rows for the unit (reprocess idempotency)."""
    return text(
        """
        UPDATE jute_prod_spinning_daily
        SET active = 0, updated_by = :updated_by, updated_date_time = CURRENT_TIMESTAMP
        WHERE co_id = :co_id AND tran_date = :tran_date AND spell_id = :spell_id
          AND active = 1
        """
    )


def insert_spinning_log_from_slice_query():
    """Freeze the unit's computed rows into jute_prod_spinning_daily in ONE statement.

    SELECT source = spinning_day_slice_sql() — the same SQL the live grid serves, so
    frozen == last-rendered. Explicit column list (slice emits display columns the
    table does not store)."""
    slice_sql = spinning_day_slice_sql()
    return text(
        f"""
        INSERT INTO jute_prod_spinning_daily (
            co_id, branch_id, tran_date, spell_id, machine_id, item_id,
            spindles, minutes, act_count, std_count,
            std_speed, actual_speed, target_speed,
            std_tpi, actual_tpi, target_tpi,
            std_eff, target_eff,
            p100prod, std_prod, target_prod,
            act_prod_doff, winding_total, act_prod_wind,
            eff_doff, eff_winding, active, updated_by
        )
        SELECT
            v.co_id, v.branch_id, v.tran_date, v.spell_id, v.machine_id, v.item_id,
            v.spindles, v.minutes, v.act_count, v.std_count,
            v.std_speed, v.actual_speed, v.target_speed,
            v.std_tpi, v.actual_tpi, v.target_tpi,
            v.std_eff, v.target_eff,
            v.p100prod, v.std_prod, v.target_prod,
            v.act_prod_doff, v.winding_total, v.act_prod_wind,
            v.eff_doff, v.eff_winding, 1, :updated_by
        FROM (
        {slice_sql}
        ) v
        """
    )


def get_spinning_process_lock_row_query():
    """Active lock header id for the unit (upsert probe).

    Branch-scoped like weaving's template: without it, branch B's Process finds
    and UPDATEs branch A's header (stays branch=A), so branch B never sees the
    locked state and a non-Edit branch-B user could silently re-freeze and clear
    A's reprocess flag."""
    return text(
        """
        SELECT spinning_process_lock_id FROM jute_prod_spinning_process_lock
        WHERE co_id = :co_id AND tran_date = :tran_date AND spell_id = :spell_id
          AND (:branch_id IS NULL OR branch_id = :branch_id OR branch_id IS NULL)
          AND active = 1
        ORDER BY spinning_process_lock_id DESC LIMIT 1
        """
    )


def insert_spinning_process_lock_query():
    """Insert a fresh locked header for the unit."""
    return text(
        """
        INSERT INTO jute_prod_spinning_process_lock
            (co_id, branch_id, tran_date, spell_id, is_locked, reprocess_needed,
             processed_by, processed_date_time, active, updated_by)
        VALUES
            (:co_id, :branch_id, :tran_date, :spell_id, 1, 0,
             :processed_by, CURRENT_TIMESTAMP, 1, :processed_by)
        """
    )


def update_spinning_process_lock_query():
    """Re-lock + clear reprocess on an existing header (reprocess run)."""
    return text(
        """
        UPDATE jute_prod_spinning_process_lock
        SET is_locked = 1, reprocess_needed = 0, processed_by = :processed_by,
            processed_date_time = CURRENT_TIMESTAMP, updated_by = :processed_by,
            updated_date_time = CURRENT_TIMESTAMP
        WHERE spinning_process_lock_id = :id
        """
    )


def update_spinning_process_lock_reprocess_query():
    """Raise reprocess_needed on a lock header (drift detected on read)."""
    return text(
        """
        UPDATE jute_prod_spinning_process_lock
        SET reprocess_needed = 1, updated_date_time = CURRENT_TIMESTAMP
        WHERE spinning_process_lock_id = :id
        """
    )


def flag_spinning_unit_reprocess_query():
    """Raise reprocess_needed on the ACTIVE locked header for a (co, date, spell)
    unit — called after any Edit-user mutation of a processed unit. No-op unlocked."""
    return text(
        """
        UPDATE jute_prod_spinning_process_lock
        SET reprocess_needed = 1, updated_date_time = CURRENT_TIMESTAMP
        WHERE co_id = :co_id AND tran_date = :tran_date AND spell_id = :spell_id
          AND is_locked = 1 AND active = 1
        """
    )


def get_spinning_drift_query():
    """One row when the frozen unit disagrees with a fresh recompute of any drift
    source: SQC count AVG (per item), doff SUM (per machine/spell/item — the
    frozen-row grain, so an item reassignment that moves weight between groups
    trips it), or the winding total (per item/shift). All three are frozen as
    ordinary snapshot columns, so the compare needs no extra fingerprint columns.
    Round both sides to the stored DECIMAL scale so an unchanged value never
    trips.

    The wnd block MUST stay byte-for-byte equivalent to the slice's (BRANCH-keyed
    jugar lookups — not co_id, a branch belongs to one company — joined
    branch-to-branch, branch in the GROUP BY): the freeze writes what the slice
    computes, so any divergence here reads as permanent drift and pins
    reprocess_needed on every locked unit. Change one, change both."""
    return text(
        """
        SELECT sd.spinning_daily_id
        FROM jute_prod_spinning_daily sd
        LEFT JOIN spell_mst sp ON sp.spell_id = sd.spell_id AND sp.status = 1
        LEFT JOIN (
            SELECT item_id, AVG(observed_count) AS act_count
            FROM jute_sqc_spinning_count
            WHERE co_id = :co_id AND entry_date = :tran_date AND active = 1
            GROUP BY item_id
        ) cnt ON cnt.item_id = sd.item_id
        LEFT JOIN (
            SELECT mc_id, spell, item_id, SUM(net_weight) AS act_prod_doff
            FROM daily_doff_tbl
            WHERE doff_date = :tran_date
              AND (active = 1 OR active IS NULL)
              AND item_id IS NOT NULL
            GROUP BY mc_id, spell, item_id
        ) dff ON dff.mc_id = sd.machine_id AND dff.spell = sd.spell_id
             AND dff.item_id = sd.item_id
        LEFT JOIN (
            SELECT wdr.item_id, LEFT(wsp.spell_code, 1) AS shift_bucket,
                   SUM(wdr.reconciled_qty) AS winding_total
            FROM (
                SELECT wd.co_id, wd.branch_id, wd.spell_id, wd.eb_id, wd.item_id,
                       SUM(wd.production_qty)
                       - COALESCE(MAX(jo.open_w), 0)
                       + COALESCE(MAX(jc.close_w), 0) AS reconciled_qty
                FROM jute_prod_winding_doff wd
                LEFT JOIN (
                    SELECT branch_id, spell_id, eb_id, MAX(weight) AS open_w
                    FROM jute_prod_winding_jugar
                    WHERE tran_date = :tran_date AND open_close = 'O' AND active = 1
                    GROUP BY branch_id, spell_id, eb_id
                ) jo ON jo.branch_id = wd.branch_id
                    AND jo.spell_id = wd.spell_id AND jo.eb_id = wd.eb_id
                LEFT JOIN (
                    SELECT branch_id, spell_id, eb_id, MAX(weight) AS close_w
                    FROM jute_prod_winding_jugar
                    WHERE tran_date = :tran_date AND open_close = 'C' AND active = 1
                    GROUP BY branch_id, spell_id, eb_id
                ) jc ON jc.branch_id = wd.branch_id
                    AND jc.spell_id = wd.spell_id AND jc.eb_id = wd.eb_id
                WHERE wd.active = 1
                  AND wd.tran_date = :tran_date
                  AND wd.co_id = :co_id
                GROUP BY wd.co_id, wd.branch_id, wd.spell_id, wd.eb_id, wd.item_id
            ) wdr
            INNER JOIN spell_mst wsp ON wsp.spell_id = wdr.spell_id
            GROUP BY wdr.item_id, LEFT(wsp.spell_code, 1)
        ) wnd ON wnd.item_id = sd.item_id AND wnd.shift_bucket = LEFT(sp.spell_code, 1)
        WHERE sd.co_id = :co_id AND sd.tran_date = :tran_date AND sd.spell_id = :spell_id
          AND sd.active = 1
          AND (
            ROUND(COALESCE(sd.act_count, 0), 3) <> ROUND(COALESCE(cnt.act_count, 0), 3)
            OR ROUND(COALESCE(sd.act_prod_doff, 0), 3) <> ROUND(COALESCE(dff.act_prod_doff, 0), 3)
            OR ROUND(COALESCE(sd.winding_total, 0), 3) <> ROUND(COALESCE(wnd.winding_total, 0), 3)
          )
        LIMIT 1
        """
    )


def get_spinning_log_rows_query():
    """Frozen unit rows projected with the SAME aliases as the slice so the
    planning-grid read is source-agnostic (display names joined live — masters may
    format, never accumulate)."""
    return text(
        """
        SELECT sd.co_id, sd.branch_id, sd.tran_date, sd.spell_id, sp.spell_code,
               LEFT(sp.spell_code, 1) AS shift_bucket,
               sd.machine_id, m.mech_code, m.machine_name,
               sd.item_id, im.item_code, im.item_name,
               sd.spindles, sd.minutes, sd.act_count, sd.std_count,
               sd.std_speed, sd.actual_speed, sd.target_speed,
               sd.std_tpi, sd.actual_tpi, sd.target_tpi,
               sd.std_eff, sd.target_eff,
               sd.p100prod, sd.std_prod, sd.target_prod,
               sd.act_prod_doff, sd.winding_total, sd.act_prod_wind,
               sd.eff_doff, sd.eff_winding
        FROM jute_prod_spinning_daily sd
        LEFT JOIN spell_mst sp ON sp.spell_id = sd.spell_id AND sp.status = 1
        LEFT JOIN machine_mst m ON m.machine_id = sd.machine_id
        LEFT JOIN item_mst im ON im.item_id = sd.item_id
        WHERE sd.co_id = :co_id AND sd.tran_date = :tran_date AND sd.spell_id = :spell_id
          AND (:branch_id IS NULL OR sd.branch_id = :branch_id OR sd.branch_id IS NULL)
          AND sd.active = 1
        ORDER BY m.mech_code, sd.spinning_daily_id
        """
    )


def get_machine_bobbin_batch_query():
    """Last-date standard bobbin_wt for ALL machines of a company in one pass
    (replaces the per-machine resolve_param loop in doff_entry_create_setup)."""
    return text(
        """
        SELECT t.ref_id AS machine_id, t.value AS bobbin_weight
        FROM (
            SELECT t2.ref_id, t2.value,
                   ROW_NUMBER() OVER (
                       PARTITION BY t2.ref_id
                       ORDER BY t2.effective_date DESC, t2.spng_target_map_id DESC
                   ) AS rn
            FROM jute_prod_spng_target_map t2
            WHERE t2.co_id = :co_id AND t2.id_type = 'mcid'
              AND t2.value_role = 'standard' AND t2.param = 'bobbin_wt'
              AND t2.active = 1 AND t2.effective_date <= :on_date
        ) t
        WHERE t.rn = 1
        """
    )
