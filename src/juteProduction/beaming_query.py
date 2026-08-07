"""Raw SQL builders for the three Beaming pages (jute production module).

Covers all three routers (SPEC §A.6 / §B.5 / §C.4):

* **Page A — Beaming Quality Master** (`jute_prod_bm_quality`): jute-cloth item list,
  jute-yarn picker, quality list, duplicate-check, insert / update / soft-delete.
* **Page B — Beaming Standards/Targets Map** (`jute_prod_beaming_target_map`): a
  near-verbatim clone of ``spng_target_map_query`` against the dedicated beaming table
  (setup machine list, flat list, single-row CRUD, LAST-DATE grid prefill + bulk-save
  exact-key lookups).
* **Page C — Beaming Production Entry** (`jute_prod_beaming_daily`): create-setup
  lookups, entries-by-date day grid, and the planning-grid driver select.

Mirrors spinning_query.py / spng_target_map_query.py conventions throughout: named
binds, the ``:x IS NULL OR ...`` optional-filter idiom, soft-delete via active=1, and
de-duplication left to the router. ``machine_mst`` / ``machine_type_mst`` filter
``active = 1``; ``spell_mst`` filters ``status = 1`` (NOT active) — SPEC §9.

The Beaming machine type resolves against ``machine_type_mst.machine_type_name`` =
'Beaming' (dev3 machine_type_id 12, SPEC §0.1), bound at call time via :beaming_type so
no not-yet-defined constant is imported here. Column names/types match beaming_models.py
exactly.
"""

from sqlalchemy import text


# =============================================================================
# PAGE A — Beaming Quality Master (jute_prod_bm_quality)
# =============================================================================


def get_beaming_cloth_items_query():
    """Active jute-cloth items for the company — item_grp_mst.item_type_id = 5.

    Adapted from query.py:47-60 (get_jute_items_query), swapping the jute/jute-waste
    ``item_type_id IN (2,3)`` predicate for Jute Cloth ``= 5`` (SPEC §0.1, §A.6).
    Company scope lives on item_grp_mst.co_id (item_mst has no co_id by design).
    """
    return text(
        """
        SELECT i.item_id, i.item_code, i.item_name,
               g.item_grp_id, g.item_grp_name, g.item_type_id
        FROM item_mst i
        INNER JOIN item_grp_mst g ON g.item_grp_id = i.item_grp_id
        WHERE i.active = 1
          AND g.co_id = :co_id
          AND g.item_type_id = 5
        ORDER BY i.item_name
        """
    )


def get_beaming_yarns_query():
    """Active jute yarns for the §A.8 count picker (item_type_id = 4).

    Mirrors spinning_query.get_yarn_qualities_query: a yarn IS an item (item_mst); its
    count lives on jute_yarn_mst.jute_yarn_count. Returns item_id (canonical key),
    item_code/item_name, and jute_yarn_count so the create dialog can auto-fill
    std_count from the chosen yarn. Company scope is on item_grp_mst.co_id.
    """
    return text(
        """
        SELECT
            ym.item_id,
            im.item_code,
            im.item_name,
            ym.jute_yarn_count
        FROM jute_yarn_mst ym
        JOIN item_mst im ON im.item_id = ym.item_id
        JOIN item_grp_mst ig ON ig.item_grp_id = im.item_grp_id
        WHERE ig.item_type_id = 4
          AND ig.co_id = :co_id
        ORDER BY im.item_name
        """
    )


def get_bm_quality_list_query():
    """Active beaming-quality rows for a company, with item label join.

    Optional :item_id filter (one item's qualities); optional branch filter that
    tolerates NULL branch rows (company-scoped master). Newest first.
    """
    return text(
        """
        SELECT
            q.bm_quality_id,
            q.co_id,
            q.branch_id,
            q.item_id,
            im.item_code,
            im.item_name,
            q.bm_quality_code,
            q.bm_quality_name,
            q.ends,
            q.std_count,
            q.yarn_item_id,
            q.is_composite,
            q.active
        FROM jute_prod_bm_quality q
        LEFT JOIN item_mst im ON im.item_id = q.item_id
        WHERE q.co_id = :co_id
          AND q.active = 1
          AND (:item_id IS NULL OR q.item_id = :item_id)
          AND (:branch_id IS NULL OR q.branch_id = :branch_id OR q.branch_id IS NULL)
        ORDER BY q.bm_quality_id DESC
        """
    )


def get_bm_quality_row_query():
    """A single active beaming-quality row by id (edit / delete existence check)."""
    return text(
        """
        SELECT bm_quality_id, co_id, branch_id, item_id, bm_quality_code,
               bm_quality_name, ends, std_count, yarn_item_id, is_composite, active
        FROM jute_prod_bm_quality
        WHERE bm_quality_id = :bm_quality_id
          AND active = 1
        """
    )


def check_bm_quality_duplicate_query():
    """Active duplicate guard on (co_id, item_id, bm_quality_code) — SPEC §A.2.

    Optional :exclude_id excludes the row being edited so an update to itself is not
    flagged as a duplicate. Mirrors the item_maturity_mst duplicate-guard pattern.
    """
    return text(
        """
        SELECT bm_quality_id
        FROM jute_prod_bm_quality
        WHERE co_id = :co_id
          AND item_id = :item_id
          AND bm_quality_code = :bm_quality_code
          AND active = 1
          AND (:exclude_id IS NULL OR bm_quality_id <> :exclude_id)
        LIMIT 1
        """
    )


def insert_bm_quality_query():
    """Insert a fresh active beaming-quality row (no created_* — trigger-based audit)."""
    return text(
        """
        INSERT INTO jute_prod_bm_quality
            (co_id, branch_id, item_id, bm_quality_code, bm_quality_name,
             ends, std_count, yarn_item_id, is_composite, active, updated_by)
        VALUES
            (:co_id, :branch_id, :item_id, :bm_quality_code, :bm_quality_name,
             :ends, :std_count, :yarn_item_id, :is_composite, 1, :updated_by)
        """
    )


def update_bm_quality_query():
    """Patch update one beaming-quality row by id.

    COALESCE keeps the existing value when a bind is NULL, so the router can pass only
    the fields the client sent (mirrors the spng edit pattern). active is updatable so
    a soft-deleted row can be reactivated via edit if needed.
    """
    return text(
        """
        UPDATE jute_prod_bm_quality
        SET bm_quality_code = COALESCE(:bm_quality_code, bm_quality_code),
            bm_quality_name = COALESCE(:bm_quality_name, bm_quality_name),
            ends            = COALESCE(:ends, ends),
            std_count       = COALESCE(:std_count, std_count),
            yarn_item_id    = COALESCE(:yarn_item_id, yarn_item_id),
            is_composite    = COALESCE(:is_composite, is_composite),
            active          = COALESCE(:active, active),
            updated_by      = :updated_by,
            updated_date_time = CURRENT_TIMESTAMP
        WHERE bm_quality_id = :bm_quality_id
        """
    )


def soft_delete_bm_quality_query():
    """Soft-delete (active=0) one beaming-quality row by id."""
    return text(
        """
        UPDATE jute_prod_bm_quality
        SET active = 0,
            updated_by = :updated_by,
            updated_date_time = CURRENT_TIMESTAMP
        WHERE bm_quality_id = :bm_quality_id
        """
    )


def null_composite_parent_fields_query():
    """Force std_count / yarn_item_id to NULL on a composite parent (§Q3).

    update_bm_quality_query COALESCEs NULL binds (keeping existing values), so it cannot
    clear std_count / yarn_item_id. When a quality is composite the real (ends, count)
    pairs live in jute_prod_bm_quality_dtl and the parent's std_count / yarn_item_id MUST
    be NULL; the router runs this right after the COALESCE update to enforce that.
    """
    return text(
        """
        UPDATE jute_prod_bm_quality
        SET std_count = NULL,
            yarn_item_id = NULL
        WHERE bm_quality_id = :bm_quality_id
        """
    )


def get_bm_quality_detail_query():
    """A single active beaming-quality parent row by id + co_id (edit dialog, §Q3).

    Co-scoped variant of get_bm_quality_row_query for the bm_quality_detail/{id}
    endpoint — the router fetches the component rows separately via
    get_bm_quality_components_query and nests them under ``components``.
    """
    return text(
        """
        SELECT bm_quality_id, co_id, branch_id, item_id, bm_quality_code,
               bm_quality_name, ends, std_count, yarn_item_id, is_composite, active
        FROM jute_prod_bm_quality
        WHERE bm_quality_id = :bm_quality_id
          AND co_id = :co_id
          AND active = 1
        """
    )


def get_bm_quality_components_query():
    """Active component rows for a composite beaming quality (SPEC §A.4 / §Q3).

    Returns the real (ends, count) warp-component pairs ordered by component_no for
    the edit dialog and the composite kg_per_cut computation
    (laid_length × SUM_n(ends_n × count_n) / (14400 × 2.20462)). Only populated when
    the parent is_composite=1 (>=2 rows); non-composite qualities have no rows here.
    """
    return text(
        """
        SELECT bm_quality_dtl_id, component_no, ends, yarn_item_id, count
        FROM jute_prod_bm_quality_dtl
        WHERE bm_quality_id = :bm_quality_id
          AND active = 1
        ORDER BY component_no
        """
    )


def insert_bm_quality_component_query():
    """Insert one active component row for a composite beaming quality (§A.4 / §Q3)."""
    return text(
        """
        INSERT INTO jute_prod_bm_quality_dtl
            (bm_quality_id, component_no, ends, yarn_item_id, count, active)
        VALUES
            (:bm_quality_id, :component_no, :ends, :yarn_item_id, :count, 1)
        """
    )


def soft_delete_bm_quality_components_query():
    """Soft-delete (active=0) ALL components of a beaming quality (replace-on-edit, §Q3).

    Edit re-inserts the full component set, so the router clears the existing set
    first via this builder, then re-inserts via insert_bm_quality_component_query.
    """
    return text(
        """
        UPDATE jute_prod_bm_quality_dtl
        SET active = 0
        WHERE bm_quality_id = :bm_quality_id
          AND active = 1
        """
    )


# =============================================================================
# PAGE B — Beaming Standards/Targets Map (jute_prod_beaming_target_map)
# Copy of spng_target_map_query.py against the dedicated beaming table.
# TWO id_types: 'mcid' (ref label from machine_mst) and 'qid' (ref label from the
# Beaming Quality Master jute_prod_bm_quality) — mirrors spng_target_map_query's
# machine/quality ref split.
# =============================================================================


def get_beaming_target_machines_query():
    """Beaming-type machines for the target-map setup row list (SPEC §B.5).

    Mirrors spinning_query.get_spinning_machines_query but for the Beaming type
    (:beaming_type -> 'Beaming'). machine_mst / machine_type_mst filter active=1.
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
          AND mt.machine_type_name = :beaming_type
          AND (:branch_id IS NULL OR d.branch_id = :branch_id)
        ORDER BY m.mech_code
        """
    )


def get_beaming_target_qualities_query():
    """Active Beaming-Quality rows for the target-map QID grid refs (SPEC §B.5).

    Mirrors get_beaming_target_machines_query's shape but for id_type='qid':
    the grid ref is the beaming QUALITY (jute_prod_bm_quality) rather than a machine,
    because laid_length / cuts_per_beam / eff are quality-linked standards. Returns
    ref_id = bm_quality_id, ref_code = bm_quality_code, ref_name = bm_quality_name so
    the router can build the same {ref_id, ref_code, ref_name} ref rows it builds for
    machines. Company-scoped (co_id) like the Quality Master; the :branch_id bind is
    accepted for call-shape parity but quality is branch-agnostic (NULL-tolerant), so
    NULL-branch qualities are always listed. Newest first.
    """
    return text(
        """
        SELECT
            q.bm_quality_id,
            q.bm_quality_code,
            q.bm_quality_name,
            q.branch_id
        FROM jute_prod_bm_quality q
        WHERE q.co_id = :co_id
          AND q.active = 1
          AND (:branch_id IS NULL OR q.branch_id = :branch_id OR q.branch_id IS NULL)
        ORDER BY q.bm_quality_id DESC
        """
    )


def get_beaming_target_map_list_query():
    """Active beaming target-map rows with optional id_type / ref_id / value_role / param
    filters. Newest effective_date first. The ref label comes from machine_mst for
    id_type='mcid' rows and from the Beaming Quality Master (jute_prod_bm_quality) for
    id_type='qid' rows (ref_id = bm_quality_id) — mirrors spng_target_map_query."""
    return text(
        """
        SELECT
            tm.beaming_target_map_id,
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
                WHEN tm.id_type = 'qid' THEN q.bm_quality_code
                ELSE NULL
            END AS ref_code,
            CASE
                WHEN tm.id_type = 'mcid' THEN m.machine_name
                WHEN tm.id_type = 'qid' THEN q.bm_quality_name
                ELSE NULL
            END AS ref_name
        FROM jute_prod_beaming_target_map tm
        LEFT JOIN machine_mst m
               ON tm.id_type = 'mcid' AND m.machine_id = tm.ref_id
        LEFT JOIN jute_prod_bm_quality q
               ON tm.id_type = 'qid' AND q.bm_quality_id = tm.ref_id
        WHERE tm.co_id = :co_id
          AND tm.active = 1
          AND (:branch_id IS NULL OR tm.branch_id = :branch_id OR tm.branch_id IS NULL)
          AND (:id_type IS NULL OR tm.id_type = :id_type)
          AND (:ref_id IS NULL OR tm.ref_id = :ref_id)
          AND (:value_role IS NULL OR tm.value_role = :value_role)
          AND (:param IS NULL OR tm.param = :param)
        ORDER BY tm.effective_date DESC, tm.beaming_target_map_id DESC
        """
    )


def get_beaming_target_map_row_query():
    """A single active beaming target-map row by id (for edit / delete existence check)."""
    return text(
        """
        SELECT beaming_target_map_id, co_id, branch_id, effective_date, ref_id,
               id_type, value_role, param, value, active
        FROM jute_prod_beaming_target_map
        WHERE beaming_target_map_id = :id
          AND active = 1
        """
    )


def insert_beaming_target_map_query():
    """Insert a fresh active beaming standards/targets row."""
    return text(
        """
        INSERT INTO jute_prod_beaming_target_map
            (co_id, branch_id, effective_date, ref_id, id_type, value_role,
             param, value, active, updated_by)
        VALUES
            (:co_id, :branch_id, :effective_date, :ref_id, :id_type, :value_role,
             :param, :value, 1, :updated_by)
        """
    )


def update_beaming_target_map_query():
    """Patch update one beaming target-map row by id (value + effective_date + audit)."""
    return text(
        """
        UPDATE jute_prod_beaming_target_map
        SET value = COALESCE(:value, value),
            effective_date = COALESCE(:effective_date, effective_date),
            updated_by = :updated_by,
            updated_date_time = CURRENT_TIMESTAMP
        WHERE beaming_target_map_id = :id
        """
    )


def soft_delete_beaming_target_map_query():
    """Soft-delete (active=0) one beaming target-map row by id."""
    return text(
        """
        UPDATE jute_prod_beaming_target_map
        SET active = 0,
            updated_by = :updated_by,
            updated_date_time = CURRENT_TIMESTAMP
        WHERE beaming_target_map_id = :id
        """
    )


def resolve_beaming_target_value_query():
    """LAST-DATE resolution: the value effective on :on_date for one resolution key.

    MAX(effective_date) <= :on_date among active rows for
    (co_id, ref_id, id_type, value_role, param). Branch-agnostic (mirrors spng /
    resolve_param). Consumed by the Page C standards snapshot builder.
    """
    return text(
        """
        SELECT value, effective_date
        FROM jute_prod_beaming_target_map
        WHERE co_id = :co_id
          AND ref_id = :ref_id
          AND id_type = :id_type
          AND value_role = :value_role
          AND param = :param
          AND active = 1
          AND effective_date <= :on_date
        ORDER BY effective_date DESC, beaming_target_map_id DESC
        LIMIT 1
        """
    )


def resolve_beaming_grid_cell_query():
    """LAST-DATE resolution for ONE grid cell, mirroring resolve_param semantics.

    Same WHERE/ORDER/LIMIT as resolve_beaming_target_value_query and applies NO branch
    filter, returning effective_date so the grid can expose source_date / is_exact
    (effective_date == :on_date). The grid reads values exactly as production does.
    """
    return text(
        """
        SELECT value, effective_date
        FROM jute_prod_beaming_target_map
        WHERE co_id = :co_id
          AND ref_id = :ref_id
          AND id_type = :id_type
          AND value_role = :value_role
          AND param = :param
          AND active = 1
          AND effective_date <= :on_date
        ORDER BY effective_date DESC, beaming_target_map_id DESC
        LIMIT 1
        """
    )


def find_exact_beaming_grid_row_query():
    """Active row at the EXACT save key, BRANCH-AGNOSTIC (mirrors grid resolution).

    Used by target_map_bulk_save to decide insert-vs-update-vs-clear. Applies NO branch
    filter so save targets the SAME row the grid prefilled (resolve_beaming_grid_cell_query
    ignores branch_id); the newest-id tiebreak matches the grid's is_exact ORDER BY.
    """
    return text(
        """
        SELECT beaming_target_map_id, value
        FROM jute_prod_beaming_target_map
        WHERE co_id = :co_id
          AND ref_id = :ref_id
          AND id_type = :id_type
          AND value_role = :value_role
          AND param = :param
          AND effective_date = :effective_date
          AND active = 1
        ORDER BY beaming_target_map_id DESC
        LIMIT 1
        """
    )


def update_beaming_grid_value_query():
    """Set value (+ audit cols) on one active grid row by id."""
    return text(
        """
        UPDATE jute_prod_beaming_target_map
        SET value = :value,
            updated_by = :updated_by,
            updated_date_time = CURRENT_TIMESTAMP
        WHERE beaming_target_map_id = :id
        """
    )


def clear_beaming_grid_value_query():
    """Soft-delete (active=0) one grid row by id, clearing the cell."""
    return text(
        """
        UPDATE jute_prod_beaming_target_map
        SET active = 0,
            updated_by = :updated_by,
            updated_date_time = CURRENT_TIMESTAMP
        WHERE beaming_target_map_id = :id
        """
    )


# =============================================================================
# PAGE C — Beaming Production Entry (jute_prod_beaming_daily)
# create_setup lookups + entries_by_date day grid + planning-grid driver select.
# =============================================================================


def get_beaming_entry_machines_query():
    """Beaming-type machines for the entry create-setup (SPEC §C.4).

    Identical shape to get_beaming_target_machines_query — machine identity only;
    standards resolve per-date from the target map. machine_mst/machine_type_mst
    filter active=1.
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
          AND mt.machine_type_name = :beaming_type
          AND (:branch_id IS NULL OR d.branch_id = :branch_id)
        ORDER BY m.mech_code
        """
    )


def get_beaming_spells_query():
    """Active spells with working hours for the entry header (SPEC §9).

    spell_mst filters status = 1 (NOT active); shift_mst filters status = 1. Returns
    spell_id (daily table stores INT spell_id) plus the code/name/hours. Callers must
    de-dup by spell_code in Python (branch fanout), keeping the first row per code.
    """
    return text(
        """
        SELECT sp.spell_id, sp.spell_code, sp.spell_name, sp.working_hours,
               sp.starting_time, sp.is_overnight, sp.shift_id
        FROM spell_mst sp
        INNER JOIN shift_mst sh ON sh.shift_id = sp.shift_id
        WHERE sp.status = 1
          AND sh.status = 1
          AND (:branch_id IS NULL OR sh.branch_id = :branch_id)
        ORDER BY sp.starting_time
        """
    )


def get_beaming_eb_list_query():
    """Active employee (eb) list for the entry header eb_no picker.

    The eb identity is the HRMS employee (hrms_ed_personal_details, keyed by eb_id);
    there is no eb_master table. Joins hrms_ed_official_details (active=1) for emp_code
    and branch scope (the spelling/branch source attendance.py uses). Branch-scoped,
    NULL-tolerant.
    """
    return text(
        """
        SELECT
            p.eb_id,
            o.emp_code,
            CONCAT(p.first_name, ' ', COALESCE(p.last_name, '')) AS eb_name,
            o.branch_id
        FROM hrms_ed_personal_details p
        LEFT JOIN hrms_ed_official_details o ON o.eb_id = p.eb_id AND o.active = 1
        WHERE p.active = 1
          AND (:branch_id IS NULL OR o.branch_id = :branch_id OR o.branch_id IS NULL)
        ORDER BY o.emp_code, p.first_name
        """
    )


def get_beaming_entry_qualities_query():
    """All active beaming qualities for the company (entry form item->quality picker).

    Returns the item label and the quality's ends/std_count/is_composite so the FE can
    filter qualities by the chosen item and the entry validator can block composite
    qualities (is_composite=1) before save (SPEC §C.5). Optional :item_id filter.
    """
    return text(
        """
        SELECT
            q.bm_quality_id,
            q.item_id,
            im.item_code,
            im.item_name,
            q.bm_quality_code,
            q.bm_quality_name,
            q.ends,
            q.std_count,
            q.is_composite
        FROM jute_prod_bm_quality q
        LEFT JOIN item_mst im ON im.item_id = q.item_id
        WHERE q.co_id = :co_id
          AND q.active = 1
          AND (:item_id IS NULL OR q.item_id = :item_id)
        ORDER BY im.item_name, q.bm_quality_code
        """
    )


def get_beaming_entries_by_date_query():
    """Raw beaming-daily entries for the day grid (SPEC §C.4 BEAMING_ENTRIES_BY_DATE).

    Joins machine/spell/item/quality for human-readable labels. spell join is
    pre-aggregated (one row per code via MIN) so a duplicate spell_code under a second
    branch's shift can't fan out the result. spell_id, machine_id optional filters.
    """
    return text(
        """
        SELECT
            bd.beaming_daily_id,
            bd.co_id,
            bd.branch_id,
            bd.tran_date,
            bd.spell_id,
            sp.spell_code,
            bd.machine_id,
            m.mech_code,
            m.machine_name,
            bd.item_id,
            im.item_code,
            im.item_name,
            bd.bm_quality_id,
            q.bm_quality_code,
            q.bm_quality_name,
            bd.eb_id,
            bd.beam_no,
            bd.act_cuts,
            bd.no_of_beam,
            bd.rpm_roller,
            bd.dia_roller,
            bd.ends,
            bd.std_count,
            bd.act_count,
            bd.laid_length,
            bd.std_cuts_per_beam,
            bd.std_speed,
            bd.target_speed,
            bd.act_speed,
            bd.std_eff,
            bd.target_eff,
            bd.working_hours,
            bd.yards_per_beam,
            bd.kg_per_cut,
            bd.kg_per_beam,
            bd.p100prod,
            bd.std_prod,
            bd.target_prod,
            bd.act_prod_kg,
            bd.act_prod_yards,
            bd.act_eff
        FROM jute_prod_beaming_daily bd
        LEFT JOIN machine_mst m ON m.machine_id = bd.machine_id
        LEFT JOIN (
            SELECT spell_code, MIN(spell_id) AS spell_id
            FROM spell_mst WHERE status = 1 GROUP BY spell_code
        ) sp ON sp.spell_id = bd.spell_id
        LEFT JOIN item_mst im ON im.item_id = bd.item_id
        LEFT JOIN jute_prod_bm_quality q ON q.bm_quality_id = bd.bm_quality_id
        WHERE bd.co_id = :co_id
          AND bd.active = 1
          AND bd.tran_date = :tran_date
          AND (:spell_id IS NULL OR bd.spell_id = :spell_id)
          AND (:machine_id IS NULL OR bd.machine_id = :machine_id)
          AND (:branch_id IS NULL OR bd.branch_id = :branch_id OR bd.branch_id IS NULL)
        ORDER BY m.mech_code, bd.beaming_daily_id DESC
        """
    )


def get_beaming_plan_driver_query():
    """Driver rows for the planning grid: active jute_prod_beaming_daily snapshots.

    Each row is one machine+quality entry for a (tran_date, spell_id). Surfaces the
    machine/spell/item/quality identity and the quality's master ends/std_count so the
    planning grid (BEAMING_PLANNING_GRID) can render/recompute per row. spell_id,
    machine_id optional. The spell working_hours feed the §3 length basis.
    """
    return text(
        """
        SELECT
            bd.beaming_daily_id,
            bd.machine_id,
            bd.spell_id,
            bd.item_id,
            bd.bm_quality_id,
            bd.eb_id,
            bd.beam_no,
            bd.act_cuts,
            bd.no_of_beam,
            bd.rpm_roller,
            bd.dia_roller,
            m.mech_code,
            m.machine_name,
            d.branch_id,
            sp.spell_code,
            sp.working_hours,
            im.item_code,
            im.item_name,
            q.bm_quality_code,
            q.bm_quality_name,
            q.ends,
            q.std_count,
            q.is_composite
        FROM jute_prod_beaming_daily bd
        INNER JOIN machine_mst m ON m.machine_id = bd.machine_id
        INNER JOIN machine_type_mst mt ON mt.machine_type_id = m.machine_type_id
        INNER JOIN dept_mst d ON d.dept_id = m.dept_id
        LEFT JOIN (
            SELECT spell_id, spell_code, working_hours
            FROM spell_mst WHERE status = 1
        ) sp ON sp.spell_id = bd.spell_id
        LEFT JOIN item_mst im ON im.item_id = bd.item_id
        LEFT JOIN jute_prod_bm_quality q ON q.bm_quality_id = bd.bm_quality_id
        WHERE bd.co_id = :co_id
          AND bd.active = 1
          AND bd.tran_date = :tran_date
          AND mt.active = 1
          AND mt.machine_type_name = :beaming_type
          AND (:spell_id IS NULL OR bd.spell_id = :spell_id)
          AND (:branch_id IS NULL OR d.branch_id = :branch_id)
        ORDER BY m.mech_code, bd.spell_id
        """
    )


def get_beaming_daily_active_row_query():
    """Active beaming_daily row id for the entry/plan grain (upsert lookup).

    App-uniqueness: (co_id, tran_date, spell_id, machine_id, item_id, bm_quality_id,
    active=1) — SPEC §C.1.
    """
    return text(
        """
        SELECT beaming_daily_id
        FROM jute_prod_beaming_daily
        WHERE co_id = :co_id
          AND tran_date = :tran_date
          AND spell_id = :spell_id
          AND machine_id = :machine_id
          AND item_id = :item_id
          AND bm_quality_id = :bm_quality_id
          AND active = 1
        ORDER BY beaming_daily_id DESC
        LIMIT 1
        """
    )


def insert_beaming_daily_query():
    """Insert a full per-machine/per-quality planning snapshot (entry inputs +
    resolved standards + computed outputs). No created_* — trigger-based audit."""
    return text(
        """
        INSERT INTO jute_prod_beaming_daily
            (co_id, branch_id, tran_date, spell_id, machine_id, item_id, bm_quality_id,
             eb_id, beam_no, act_cuts, no_of_beam, rpm_roller, dia_roller,
             ends, std_count, act_count, laid_length, std_cuts_per_beam,
             std_speed, target_speed, act_speed, std_eff, target_eff, working_hours,
             yards_per_beam, kg_per_cut, kg_per_beam,
             p100prod, std_prod, target_prod, act_prod_kg, act_prod_yards, act_eff,
             active, updated_by)
        VALUES
            (:co_id, :branch_id, :tran_date, :spell_id, :machine_id, :item_id, :bm_quality_id,
             :eb_id, :beam_no, :act_cuts, :no_of_beam, :rpm_roller, :dia_roller,
             :ends, :std_count, :act_count, :laid_length, :std_cuts_per_beam,
             :std_speed, :target_speed, :act_speed, :std_eff, :target_eff, :working_hours,
             :yards_per_beam, :kg_per_cut, :kg_per_beam,
             :p100prod, :std_prod, :target_prod, :act_prod_kg, :act_prod_yards, :act_eff,
             1, :updated_by)
        """
    )


def update_beaming_daily_query():
    """Update a full per-machine/per-quality planning snapshot by id."""
    return text(
        """
        UPDATE jute_prod_beaming_daily
        SET branch_id = :branch_id,
            eb_id = :eb_id,
            beam_no = :beam_no,
            act_cuts = :act_cuts,
            no_of_beam = :no_of_beam,
            rpm_roller = :rpm_roller,
            dia_roller = :dia_roller,
            ends = :ends,
            std_count = :std_count,
            act_count = :act_count,
            laid_length = :laid_length,
            std_cuts_per_beam = :std_cuts_per_beam,
            std_speed = :std_speed,
            target_speed = :target_speed,
            act_speed = :act_speed,
            std_eff = :std_eff,
            target_eff = :target_eff,
            working_hours = :working_hours,
            yards_per_beam = :yards_per_beam,
            kg_per_cut = :kg_per_cut,
            kg_per_beam = :kg_per_beam,
            p100prod = :p100prod,
            std_prod = :std_prod,
            target_prod = :target_prod,
            act_prod_kg = :act_prod_kg,
            act_prod_yards = :act_prod_yards,
            act_eff = :act_eff,
            updated_by = :updated_by,
            updated_date_time = CURRENT_TIMESTAMP
        WHERE beaming_daily_id = :id
        """
    )


def soft_delete_beaming_daily_query():
    """Soft-delete (active=0) one beaming-daily row by id."""
    return text(
        """
        UPDATE jute_prod_beaming_daily
        SET active = 0,
            updated_by = :updated_by,
            updated_date_time = CURRENT_TIMESTAMP
        WHERE beaming_daily_id = :id
        """
    )


def get_beaming_idle_hours_query():
    """Total active idle (stoppage) hours for one machine/date/spell (SPEC §Q8).

    SUM of jute_prod_stoppage_hours.stoppage_hours, COALESCE'd to 0 when no stoppage
    rows exist. Net working_hours = max(0, spell_mst.working_hours - idle_hours) is
    computed by the router/compute layer before compute_beaming_daily on entry
    create/edit and planning_grid_save.
    """
    return text(
        """
        SELECT COALESCE(SUM(stoppage_hours), 0) AS idle_hours
        FROM jute_prod_stoppage_hours
        WHERE active = 1
          AND co_id = :co_id
          AND machine_id = :machine_id
          AND tran_date = :tran_date
          AND spell_id = :spell_id
        """
    )
