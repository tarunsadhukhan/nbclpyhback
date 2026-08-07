"""Raw SQL builders for the Finishing pages (jute production + jute SQC modules).

Clone of beaming_query.py against the dedicated finishing tables, adding ONE new
dimension — ``process`` — to every WHERE clause and exact-key lookup. Covers:

* **Finishing Quality Master** (``jute_prod_finishing_quality``): the finished item
  IS the identity — one active row per (co_id, quality_type, item_id). quality_type
  1=Hessian, 2=Sacking (DISPLAY-only labels; stored as INT). Three optional params
  attach to the item: packsheet_wt (kg), std_bale_weight (kg), no_of_bags (pcs).
  Covers item picker, quality list/detail, duplicate-check, insert / update /
  soft-delete.
* **Finishing Spec Sheet** (``jute_prod_finishing_target_map``): setup machine/quality
  lists, flat list, single-row CRUD, LAST-DATE grid prefill + bulk-save exact-key
  lookups — all process-aware.
* **Finishing Production Entry** (``jute_prod_finishing_daily`` + ``_param``):
  create-setup lookups, entries-by-date day grid, soft-delete, and the per-process
  EAV param insert/clear.

Mirrors beaming_query.py / spng_target_map_query.py conventions throughout: named
binds, the ``:x IS NULL OR ...`` optional-filter idiom, soft-delete via active=1, and
de-duplication left to the router. ``machine_mst`` / ``machine_type_mst`` filter
``active = 1``; ``spell_mst`` filters ``status = 1`` (NOT active). The per-process
machine type resolves against ``machine_type_mst.machine_type_name`` bound at call time
via :machine_type (FINISHING_MACHINE_TYPE_NAMES) so no constant is imported here. Column
names/types match finishing_models.py exactly.
"""

from sqlalchemy import text


# =============================================================================
# Finishing Quality Master (jute_prod_finishing_quality)
# =============================================================================


def get_finishing_items_query():
    """Active 'Jute Cloth' items for the finishing-quality item picker (company-scoped).

    The finished item lives in item_mst; company scope + item type live on item_grp_mst
    (item_mst has no co_id / item_type by design — both hang off item_grp_id). Filtered to
    item_grp_mst.item_type_id = :item_type_id ('Jute Cloth' = 5). full_item_code comes from
    vw_item_with_group_path (the full code other tables display). Optional :item_grp_id
    narrows by group.
    """
    return text(
        """
        SELECT i.item_id, i.item_code, vip.full_item_code, i.item_name,
               g.item_grp_id, g.item_grp_name, g.item_type_id
        FROM item_mst i
        INNER JOIN item_grp_mst g ON g.item_grp_id = i.item_grp_id
        LEFT JOIN vw_item_with_group_path vip ON vip.item_id = i.item_id
        WHERE i.active = 1
          AND g.co_id = :co_id
          AND g.item_type_id = :item_type_id
          AND (:item_grp_id IS NULL OR g.item_grp_id = :item_grp_id)
        ORDER BY i.item_name
        """
    )


def get_finishing_quality_list_query():
    """Active finishing-quality rows for a company, with item label join.

    Optional :quality_type filter (1=Hessian, 2=Sacking); optional :item_id filter;
    optional branch filter that tolerates NULL branch rows (company-scoped master). The
    three optional item params (packsheet_wt, std_bale_weight, no_of_bags) ride along.
    Newest first.
    """
    return text(
        """
        SELECT
            q.finishing_quality_id,
            q.co_id,
            q.branch_id,
            q.quality_type,
            q.item_id,
            im.item_code,
            im.item_name,
            q.packsheet_wt,
            q.std_bale_weight,
            q.no_of_bags,
            q.active
        FROM jute_prod_finishing_quality q
        LEFT JOIN item_mst im ON im.item_id = q.item_id
        WHERE q.co_id = :co_id
          AND q.active = 1
          AND (:quality_type IS NULL OR q.quality_type = :quality_type)
          AND (:item_id IS NULL OR q.item_id = :item_id)
          AND (:branch_id IS NULL OR q.branch_id = :branch_id OR q.branch_id IS NULL)
        ORDER BY q.finishing_quality_id DESC
        """
    )


def get_finishing_quality_row_query():
    """A single active finishing-quality row by id (edit / delete existence check)."""
    return text(
        """
        SELECT finishing_quality_id, co_id, branch_id, quality_type, item_id, active
        FROM jute_prod_finishing_quality
        WHERE finishing_quality_id = :finishing_quality_id
          AND active = 1
        """
    )


def get_finishing_quality_detail_query():
    """A single active finishing-quality row by id + co_id (edit dialog, full columns)."""
    return text(
        """
        SELECT
            q.finishing_quality_id,
            q.co_id,
            q.branch_id,
            q.quality_type,
            q.item_id,
            im.item_code,
            im.item_name,
            q.packsheet_wt,
            q.std_bale_weight,
            q.no_of_bags,
            q.active
        FROM jute_prod_finishing_quality q
        LEFT JOIN item_mst im ON im.item_id = q.item_id
        WHERE q.finishing_quality_id = :finishing_quality_id
          AND q.co_id = :co_id
          AND q.active = 1
        """
    )


def check_finishing_quality_duplicate_query():
    """Active duplicate guard on (co_id, quality_type, item_id) — the item is the identity.

    Optional :exclude_id excludes the row being edited so an update to itself is not
    flagged as a duplicate.
    """
    return text(
        """
        SELECT finishing_quality_id
        FROM jute_prod_finishing_quality
        WHERE co_id = :co_id
          AND quality_type = :quality_type
          AND item_id = :item_id
          AND active = 1
          AND (:exclude_id IS NULL OR finishing_quality_id <> :exclude_id)
        LIMIT 1
        """
    )


def insert_finishing_quality_query():
    """Insert a fresh active finishing-quality row (no created_* — trigger-based audit)."""
    return text(
        """
        INSERT INTO jute_prod_finishing_quality
            (co_id, branch_id, quality_type, item_id,
             packsheet_wt, std_bale_weight, no_of_bags,
             active, updated_by)
        VALUES
            (:co_id, :branch_id, :quality_type, :item_id,
             :packsheet_wt, :std_bale_weight, :no_of_bags,
             1, :updated_by)
        """
    )


def update_finishing_quality_query():
    """Patch update one finishing-quality row by id.

    COALESCE keeps the existing value when a bind is NULL, so the router can pass only
    the fields the client sent. active is updatable so a soft-deleted row can be
    reactivated via edit if needed.
    """
    return text(
        """
        UPDATE jute_prod_finishing_quality
        SET item_id         = COALESCE(:item_id, item_id),
            packsheet_wt    = COALESCE(:packsheet_wt, packsheet_wt),
            std_bale_weight = COALESCE(:std_bale_weight, std_bale_weight),
            no_of_bags      = COALESCE(:no_of_bags, no_of_bags),
            active          = COALESCE(:active, active),
            updated_by      = :updated_by,
            updated_date_time = CURRENT_TIMESTAMP
        WHERE finishing_quality_id = :finishing_quality_id
        """
    )


def soft_delete_finishing_quality_query():
    """Soft-delete (active=0) one finishing-quality row by id."""
    return text(
        """
        UPDATE jute_prod_finishing_quality
        SET active = 0,
            updated_by = :updated_by,
            updated_date_time = CURRENT_TIMESTAMP
        WHERE finishing_quality_id = :finishing_quality_id
        """
    )


# =============================================================================
# Finishing Spec Sheet (jute_prod_finishing_target_map)
# TWO id_types: 'mcid' (ref label from machine_mst) and 'qid' (ref label from the
# Finishing Quality Master). Every WHERE/key carries the NEW `process` dimension.
# =============================================================================


def get_finishing_machines_query():
    """Machines whose machine_type matches the process's type name (spec-sheet / entry).

    The process-to-type-name mapping is FINISHING_MACHINE_TYPE_NAMES; the resolved name
    is bound at call time via :machine_type. machine_mst / machine_type_mst filter
    active=1; branch scopes via dept_mst.branch_id (NULL bind => all branches).
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
          AND mt.machine_type_name = :machine_type
          AND (:branch_id IS NULL OR d.branch_id = :branch_id)
        ORDER BY m.mech_code
        """
    )


def get_finishing_qualities_query():
    """Active Finishing-Quality rows for the qid grid refs.

    Optional :quality_type filter (1=Hessian, 2=Sacking) so the qid ref list matches the
    process. Company-scoped (co_id); the :branch_id bind is accepted for call-shape
    parity but quality is branch-agnostic (NULL-tolerant). The ref label is the item:
    item_code AS fin_quality_code / item_name AS fin_quality_name — keeping those keys
    stable so the router still builds {ref_id, ref_code, ref_name} ref rows. Newest first.
    """
    return text(
        """
        SELECT
            q.finishing_quality_id,
            im.item_code AS fin_quality_code,
            im.item_name AS fin_quality_name,
            q.quality_type,
            q.item_id,
            q.branch_id
        FROM jute_prod_finishing_quality q
        LEFT JOIN item_mst im ON im.item_id = q.item_id
        WHERE q.co_id = :co_id
          AND q.active = 1
          AND (:quality_type IS NULL OR q.quality_type = :quality_type)
          AND (:branch_id IS NULL OR q.branch_id = :branch_id OR q.branch_id IS NULL)
        ORDER BY q.finishing_quality_id DESC
        """
    )


def get_finishing_target_map_list_query():
    """Active finishing spec-sheet rows with optional process / id_type / ref_id /
    value_role / param filters. Newest effective_date first. The ref label comes from
    machine_mst for id_type='mcid' rows and from the Finishing Quality Master for
    id_type='qid' rows (ref_id = finishing_quality_id)."""
    return text(
        """
        SELECT
            tm.finishing_target_map_id,
            tm.co_id,
            tm.branch_id,
            tm.process,
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
        FROM jute_prod_finishing_target_map tm
        LEFT JOIN machine_mst m
               ON tm.id_type = 'mcid' AND m.machine_id = tm.ref_id
        LEFT JOIN jute_prod_finishing_quality q
               ON tm.id_type = 'qid' AND q.finishing_quality_id = tm.ref_id
        LEFT JOIN item_mst im ON im.item_id = q.item_id
        WHERE tm.co_id = :co_id
          AND tm.active = 1
          AND (:process IS NULL OR tm.process = :process)
          AND (:branch_id IS NULL OR tm.branch_id = :branch_id OR tm.branch_id IS NULL)
          AND (:id_type IS NULL OR tm.id_type = :id_type)
          AND (:ref_id IS NULL OR tm.ref_id = :ref_id)
          AND (:value_role IS NULL OR tm.value_role = :value_role)
          AND (:param IS NULL OR tm.param = :param)
        ORDER BY tm.effective_date DESC, tm.finishing_target_map_id DESC
        """
    )


def get_finishing_target_map_row_query():
    """A single active finishing spec-sheet row by id (for edit / delete existence check)."""
    return text(
        """
        SELECT finishing_target_map_id, co_id, branch_id, process, effective_date, ref_id,
               id_type, value_role, param, value, active
        FROM jute_prod_finishing_target_map
        WHERE finishing_target_map_id = :id
          AND active = 1
        """
    )


def insert_finishing_target_map_query():
    """Insert a fresh active finishing spec-sheet row (process-aware)."""
    return text(
        """
        INSERT INTO jute_prod_finishing_target_map
            (co_id, branch_id, process, effective_date, ref_id, id_type, value_role,
             param, value, active, updated_by)
        VALUES
            (:co_id, :branch_id, :process, :effective_date, :ref_id, :id_type, :value_role,
             :param, :value, 1, :updated_by)
        """
    )


def resolve_finishing_grid_cell_query():
    """LAST-DATE resolution for ONE grid cell (mirrors resolve_param semantics).

    The active row with MAX(effective_date) <= :on_date among
    (co_id, process, ref_id, id_type, value_role, param). BRANCH-AGNOSTIC (no branch
    filter) so the grid cell shows the same value production logic uses. Returns
    effective_date so the grid can expose source_date / is_exact.
    """
    return text(
        """
        SELECT value, effective_date
        FROM jute_prod_finishing_target_map
        WHERE co_id = :co_id
          AND process = :process
          AND ref_id = :ref_id
          AND id_type = :id_type
          AND value_role = :value_role
          AND param = :param
          AND active = 1
          AND effective_date <= :on_date
        ORDER BY effective_date DESC, finishing_target_map_id DESC
        LIMIT 1
        """
    )


def find_exact_finishing_grid_row_query():
    """Active row at the EXACT save key, BRANCH-AGNOSTIC (mirrors grid resolution).

    Used by target_map_bulk_save to decide insert-vs-update-vs-clear. Applies NO branch
    filter so save targets the SAME row the grid prefilled; the newest-id tiebreak
    matches the grid's is_exact ORDER BY. Process is part of the exact key.
    """
    return text(
        """
        SELECT finishing_target_map_id, value
        FROM jute_prod_finishing_target_map
        WHERE co_id = :co_id
          AND process = :process
          AND ref_id = :ref_id
          AND id_type = :id_type
          AND value_role = :value_role
          AND param = :param
          AND effective_date = :effective_date
          AND active = 1
        ORDER BY finishing_target_map_id DESC
        LIMIT 1
        """
    )


def update_finishing_grid_value_query():
    """Set value (+ audit cols) on one active spec-sheet row by id."""
    return text(
        """
        UPDATE jute_prod_finishing_target_map
        SET value = :value,
            updated_by = :updated_by,
            updated_date_time = CURRENT_TIMESTAMP
        WHERE finishing_target_map_id = :id
        """
    )


def clear_finishing_grid_value_query():
    """Soft-delete (active=0) one spec-sheet row by id, clearing the cell."""
    return text(
        """
        UPDATE jute_prod_finishing_target_map
        SET active = 0,
            updated_by = :updated_by,
            updated_date_time = CURRENT_TIMESTAMP
        WHERE finishing_target_map_id = :id
        """
    )


# =============================================================================
# Finishing Production Entry (jute_prod_finishing_daily + _param)
# =============================================================================


def get_finishing_spells_query():
    """Active spells with working hours for the entry header.

    spell_mst filters status = 1 (NOT active); shift_mst filters status = 1. Callers
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


def get_finishing_daily_active_row_query():
    """Active finishing_daily row id for the entry grain (upsert lookup).

    App-uniqueness: (co_id, tran_date, spell_id, process, machine_id,
    finishing_quality_id, active=1).
    """
    return text(
        """
        SELECT finishing_daily_id
        FROM jute_prod_finishing_daily
        WHERE co_id = :co_id
          AND tran_date = :tran_date
          AND spell_id = :spell_id
          AND process = :process
          AND machine_id = :machine_id
          AND finishing_quality_id = :finishing_quality_id
          AND active = 1
        ORDER BY finishing_daily_id DESC
        LIMIT 1
        """
    )


def get_finishing_daily_active_row_by_emp_query():
    """Active finishing_daily row id for the LABOUR (no-machine) entry grain.

    Sacksewing has no machine, so the row is keyed by the worker instead. App-uniqueness:
    (co_id, tran_date, spell_id, process, machine_id IS NULL, eb_id, finishing_quality_id,
    active=1).
    """
    return text(
        """
        SELECT finishing_daily_id
        FROM jute_prod_finishing_daily
        WHERE co_id = :co_id
          AND tran_date = :tran_date
          AND spell_id = :spell_id
          AND process = :process
          AND machine_id IS NULL
          AND eb_id = :eb_id
          AND finishing_quality_id = :finishing_quality_id
          AND active = 1
        ORDER BY finishing_daily_id DESC
        LIMIT 1
        """
    )


def get_finishing_employee_query():
    """Resolve a worker (eb) by emp_code OR eb_id, scoped to a branch (labour stages).

    The eb identity is the HRMS employee (no eb_master): hrms_ed_personal_details holds the
    name, hrms_ed_official_details holds emp_code + branch scope (both keyed by eb_id; the
    same source attendance.py / beaming use). Branch is enforced (:branch_id), so a code from
    another branch resolves to nothing. Pass exactly one of :emp_code / :eb_id (the other
    NULL). Returns eb_id, emp_code, and the display name = emp_code + first/middle/last name.
    """
    return text(
        """
        SELECT
            p.eb_id,
            o.emp_code,
            TRIM(CONCAT_WS(' ', p.first_name, p.middle_name, p.last_name)) AS employee_name
        FROM hrms_ed_official_details o
        INNER JOIN hrms_ed_personal_details p ON p.eb_id = o.eb_id AND p.active = 1
        WHERE o.active = 1
          AND o.branch_id = :branch_id
          AND (:emp_code IS NULL OR o.emp_code = :emp_code)
          AND (:eb_id IS NULL OR o.eb_id = :eb_id)
        ORDER BY o.eb_id DESC
        LIMIT 1
        """
    )


def insert_finishing_daily_query():
    """Insert a full per-process/per-machine/per-quality daily snapshot (entry inputs +
    resolved standards + computed outputs). No created_* — trigger-based audit."""
    return text(
        """
        INSERT INTO jute_prod_finishing_daily
            (co_id, branch_id, tran_date, spell_id, process, machine_id, finishing_quality_id,
             eb_id, input_qty, input_uom, prod_qty, prod_uom, prod_wt_kg, wastage_kg,
             std_speed, target_speed, act_speed, std_eff, target_eff, working_hours,
             p100prod, std_prod, target_prod, act_eff,
             active, updated_by)
        VALUES
            (:co_id, :branch_id, :tran_date, :spell_id, :process, :machine_id, :finishing_quality_id,
             :eb_id, :input_qty, :input_uom, :prod_qty, :prod_uom, :prod_wt_kg, :wastage_kg,
             :std_speed, :target_speed, :act_speed, :std_eff, :target_eff, :working_hours,
             :p100prod, :std_prod, :target_prod, :act_eff,
             1, :updated_by)
        """
    )


def update_finishing_daily_query():
    """Update a full per-process/per-machine/per-quality daily snapshot by id."""
    return text(
        """
        UPDATE jute_prod_finishing_daily
        SET branch_id = :branch_id,
            eb_id = :eb_id,
            input_qty = :input_qty,
            input_uom = :input_uom,
            prod_qty = :prod_qty,
            prod_uom = :prod_uom,
            prod_wt_kg = :prod_wt_kg,
            wastage_kg = :wastage_kg,
            std_speed = :std_speed,
            target_speed = :target_speed,
            act_speed = :act_speed,
            std_eff = :std_eff,
            target_eff = :target_eff,
            working_hours = :working_hours,
            p100prod = :p100prod,
            std_prod = :std_prod,
            target_prod = :target_prod,
            act_eff = :act_eff,
            updated_by = :updated_by,
            updated_date_time = CURRENT_TIMESTAMP
        WHERE finishing_daily_id = :id
        """
    )


def soft_delete_finishing_daily_query():
    """Soft-delete (active=0) one finishing-daily row by id."""
    return text(
        """
        UPDATE jute_prod_finishing_daily
        SET active = 0,
            updated_by = :updated_by,
            updated_date_time = CURRENT_TIMESTAMP
        WHERE finishing_daily_id = :id
        """
    )


def get_finishing_entries_by_date_query():
    """Raw finishing-daily entries for the day grid, joined for human-readable labels.

    spell join is pre-aggregated (one row per code via MIN) so a duplicate spell_code
    under a second branch's shift can't fan out the result. Optional process / spell_id /
    machine_id filters.
    """
    return text(
        """
        SELECT
            fd.finishing_daily_id,
            fd.co_id,
            fd.branch_id,
            fd.tran_date,
            fd.spell_id,
            sp.spell_code,
            fd.process,
            fd.machine_id,
            m.mech_code,
            m.machine_name,
            fd.finishing_quality_id,
            im.item_code AS fin_quality_code,
            im.item_name AS fin_quality_name,
            q.quality_type,
            fd.eb_id,
            eo.emp_code,
            TRIM(CONCAT_WS(' ', ep.first_name, ep.middle_name, ep.last_name)) AS emp_name,
            fd.input_qty,
            fd.input_uom,
            fd.prod_qty,
            fd.prod_uom,
            fd.prod_wt_kg,
            fd.wastage_kg,
            fd.std_speed,
            fd.target_speed,
            fd.act_speed,
            fd.std_eff,
            fd.target_eff,
            fd.working_hours,
            fd.p100prod,
            fd.std_prod,
            fd.target_prod,
            fd.act_eff
        FROM jute_prod_finishing_daily fd
        LEFT JOIN machine_mst m ON m.machine_id = fd.machine_id
        LEFT JOIN hrms_ed_official_details eo ON eo.eb_id = fd.eb_id AND eo.active = 1
        LEFT JOIN hrms_ed_personal_details ep ON ep.eb_id = fd.eb_id AND ep.active = 1
        LEFT JOIN (
            SELECT spell_code, MIN(spell_id) AS spell_id
            FROM spell_mst WHERE status = 1 GROUP BY spell_code
        ) sp ON sp.spell_id = fd.spell_id
        LEFT JOIN jute_prod_finishing_quality q ON q.finishing_quality_id = fd.finishing_quality_id
        LEFT JOIN item_mst im ON im.item_id = q.item_id
        WHERE fd.co_id = :co_id
          AND fd.active = 1
          AND fd.tran_date = :tran_date
          AND (:process IS NULL OR fd.process = :process)
          AND (:spell_id IS NULL OR fd.spell_id = :spell_id)
          AND (:machine_id IS NULL OR fd.machine_id = :machine_id)
          AND (:branch_id IS NULL OR fd.branch_id = :branch_id OR fd.branch_id IS NULL)
        ORDER BY m.mech_code, fd.finishing_daily_id DESC
        """
    )


def get_finishing_quality_for_entry_query():
    """Active finishing-quality row (co_id-scoped) for entry std/weight resolution.

    Returns the item identity plus the three optional params (packsheet_wt,
    std_bale_weight, no_of_bags) and quality_type so the router can validate the quality
    against the process and resolve weights.
    """
    return text(
        """
        SELECT finishing_quality_id, co_id, quality_type, item_id,
               packsheet_wt, std_bale_weight, no_of_bags
        FROM jute_prod_finishing_quality
        WHERE finishing_quality_id = :finishing_quality_id
          AND co_id = :co_id
          AND active = 1
        """
    )
