"""Raw SQL builders for the Winding production module (jute production).

Winding is the mill-floor stage after spinning. Entry is **person-keyed**
(``docs/winding-person-keyed-entry-spec.md``): a doff is one weighing by one
winder, identified by ``eb_id``; no machine appears on any entry form. Three
entry screens share a Date + Spell + Winder header and write to three tables:

* ``jute_prod_winding_doff``       — one row per weighing per person.
* ``jute_prod_winding_jugar``      — spindle open/close leftover weight per
  person/spell (``open_close`` CHAR(1) 'O'/'C').
* ``jute_prod_winding_daily_qlty`` — the person -> yarn-quality map (+ machine and
  spindle count), carried forward from the previous spell.

Schema source of truth: ``src/juteProduction/winding_models.py`` (ORM). These
builders are raw SQL because the entry flows need multi-table joins, carry-forward
seeds, and a read-time reconciliation view.

Quality identity is the yarn ITEM (``item_id`` -> ``item_mst.item_id``) — there is
NO separate quality master. Reconciled production (``SUM(production_qty) - opening +
closing``) is computed at READ time, never persisted.

**Unresolved-worker rule:** ``eb_id`` is always set — every write path requires it,
and no row without one exists. Reads still join the worker with a LEFT JOIN so that a
row whose ``eb_id`` finds no matching ACTIVE hrms_ed_personal_details row (employee
deleted or deactivated) still appears in the grid with a blank worker instead of
vanishing from the day's production.

**Scope key is ``branch_id``, never ``co_id``** (2026-08-02): a branch belongs to
exactly one company, so the branch is the stricter key and co_id adds nothing.
Every read here filters ``branch_id = :branch_id`` (required — no NULL-tolerant
form); ``co_id`` survives only as an INSERT column value. Writes derive the
branch from the winder's HRMS record and reject a worker without one, so no row
can exist that these reads cannot see.

Conventions mirror spinning_query.py: named binds, the ``:x IS NULL OR ...``
optional-filter idiom, ``(active = 1 OR active IS NULL)`` tolerance for legacy
rows, and ``spell_id`` (INT) on the boundary (resolved from spell_code via
spinning_entry._resolve_spell). The production typo ``trolly_mst.busket_weight``
is kept; responses alias it ``bucket_weight``.

``emp_code`` on the grids comes from a scalar subquery, NOT a join:
hrms_ed_official_details can hold more than one row per eb (branch transfers), and
a join would fan a grid out into duplicate rows.
"""

from sqlalchemy import bindparam, text


def _emp_code_sql(alias: str) -> str:
    """Scalar subquery yielding the worker's emp_code for a row of ``alias``."""
    return f"""(SELECT NULLIF(TRIM(o.emp_code), '')
                  FROM hrms_ed_official_details o
                 WHERE o.eb_id = {alias}.eb_id AND o.active = 1
                 LIMIT 1) AS emp_code"""


# Display name of the worker, from the LEFT-JOINed hrms_ed_personal_details alias.
_WORKER_NAME_SQL = (
    "TRIM(CONCAT_WS(' ', p.first_name, p.middle_name, p.last_name)) AS worker_name"
)


# =============================================================================
# Setup / lookup builders
# =============================================================================


def get_winding_workers_query():
    """The winder picker — HRMS masters, NOT attendance (spec §3.1 / decision D1).

    Deliberately **not** designation-filtered: the mill's winding designations
    ('WINDER SPOOL', 'SPOOL WINDER SWP', 'HESS WFT WINDER', 'P.W. WINDING',
    'RE WINDER', ...) share no prefix or substring, so any gate would silently
    hide real winders. Designation is returned for display only.

    ``label`` is concatenated server-side (same convention as spinning's
    get_active_workers_query) so every screen shows the identical
    '02413 - LAXMI DEBI' string.
    """
    return text(
        """
        SELECT p.eb_id,
               o.emp_code,
               TRIM(CONCAT_WS(' ', p.first_name, p.middle_name, p.last_name)) AS worker_name,
               dm.desig AS designation,
               CONCAT(COALESCE(o.emp_code, p.eb_id), ' - ',
                      TRIM(CONCAT_WS(' ', p.first_name, p.middle_name, p.last_name))) AS label
        FROM hrms_ed_personal_details p
        INNER JOIN hrms_ed_official_details o ON o.eb_id = p.eb_id AND o.active = 1
        LEFT  JOIN designation_mst dm ON dm.designation_id = o.designation_id
        WHERE p.active = 1
          AND (:branch_id IS NULL OR o.branch_id = :branch_id)
          AND (:search IS NULL OR o.emp_code LIKE :search
               OR TRIM(CONCAT_WS(' ', p.first_name, p.middle_name, p.last_name)) LIKE :search)
        ORDER BY o.emp_code
        LIMIT :limit
        """
    )


def get_winding_machines_query():
    """Winding-type machines for the person -> quality map's machine column.

    Mirrors spinning_query.get_spinning_machines_query, but the type name is a
    bind (:machine_type_name -> constants.WINDING_MACHINE_TYPE_NAME) instead of
    a hardcoded literal. Branch comes from the machine's department.
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
          AND mt.machine_type_name = :machine_type_name
          AND (:branch_id IS NULL OR d.branch_id = :branch_id)
        ORDER BY m.mech_code
        """
    )


def get_winding_trollies_query():
    """Trolly / spool master rows filtered by trolly_type ('T'=trolly, 'S'=spool)
    and constrained to a production machine type.

    :machine_type_name resolves to machine_type_id via JOIN; untagged rows
    (machine_type_id NULL) are excluded because NULL never equals a name.
    Keeps the busket_weight column name; the response aliases it bucket_weight.
    """
    return text(
        """
        SELECT
            t.trolly_id,
            t.trolly_name,
            t.trolly_weight,
            t.busket_weight AS bucket_weight,
            t.trolly_posting_code,
            t.trolly_type,
            t.branch_id,
            t.machine_type_id
        FROM trolly_mst t
        LEFT JOIN machine_type_mst mt ON mt.machine_type_id = t.machine_type_id AND mt.active = 1
        WHERE t.trolly_type = :trolly_type
          AND (:branch_id IS NULL OR t.branch_id = :branch_id)
          AND mt.machine_type_name = :machine_type_name
        ORDER BY t.trolly_name
        """
    )


def get_winding_trolly_query():
    """One trolly/spool row (trolly_weight + busket_weight) for tare/lookup."""
    return text(
        """
        SELECT trolly_id, trolly_weight, busket_weight, trolly_type
        FROM trolly_mst
        WHERE trolly_id = :trolly_id
        """
    )


def derive_branch_for_worker_query():
    """branch_id for a winder from HRMS (spec §4.4; replaces the machine -> dept
    derivation). Doubles as the "is this a real eb?" probe — no row means an
    unknown eb_id, which the caller rejects with 400.

    LIMIT 1 on the newest official-details row: hrms_ed_official_details can hold
    several rows per eb after a branch transfer.
    """
    return text(
        """
        SELECT o.branch_id
        FROM hrms_ed_official_details o
        WHERE o.eb_id = :eb_id AND o.active = 1
        ORDER BY o.tbl_hrms_ed_official_detail_id DESC
        LIMIT 1
        """
    )


# =============================================================================
# Doff (jute_prod_winding_doff) builders
# =============================================================================


def get_doff_prev_state_query():
    """The latest active doff row for a WINDER, to prefill the form.

    Returns trolly/spool/quality + their weights from the most recent active doff
    of that person (any date/spell), mirroring legacy getwndprvDoffData
    (MAX(auto_id) where is_active=1) re-keyed from machine to person.
    """
    return text(
        """
        SELECT
            wd.winding_doff_id,
            wd.tran_date,
            wd.spell_id,
            wd.eb_id,
            wd.item_id,
            wd.trolly_id,
            wd.trolly_wt,
            wd.spool_id,
            wd.spool_wt,
            wd.gross_input_wt,
            wd.production_qty
        FROM jute_prod_winding_doff wd
        WHERE wd.branch_id = :branch_id
          AND wd.eb_id = :eb_id
          AND (wd.active = 1 OR wd.active IS NULL)
        ORDER BY wd.winding_doff_id DESC
        LIMIT 1
        """
    )


def insert_doff_row_query():
    """Insert ONE doff row for ONE winder.

    A weighing shared by N winders runs this N times in a single transaction:
    ``production_qty`` / ``gross_input_wt`` carry that winder's share of the
    weighing (the last row absorbing the rounding remainder), while ``trolly_wt``
    and ``spool_wt`` are stored in full on every row — one weighing is one trolly
    plus one spool, so the tare is deducted once for the whole split, not per row.

    machine_id and no_of_machines are deliberately absent from the column list —
    they stay NULL (decisions D3/D4). Both are dead columns: no write path sets
    them and no row uses them.
    """
    return text(
        """
        INSERT INTO jute_prod_winding_doff
            (co_id, branch_id, tran_date, spell_id, eb_id, item_id,
             trolly_id, trolly_wt, spool_id, spool_wt,
             gross_input_wt, production_qty, row_gross_wt,
             active, updated_by)
        VALUES
            (:co_id, :branch_id, :tran_date, :spell_id, :eb_id, :item_id,
             :trolly_id, :trolly_wt, :spool_id, :spool_wt,
             :gross_input_wt, :production_qty, :row_gross_wt,
             1, :updated_by)
        """
    )


def stamp_doff_weighing_id_query():
    """Stamp the shared-weighing group key on the rows just inserted.

    The key is the FIRST row's id, so it needs the ids back from the inserts and
    cannot ride on insert_doff_row_query itself. Without it edit and delete see
    only one winder's share of a shared weighing — and a partial split leaves the
    spinning planning grid (SUM(production_qty) per item + shift) short.
    """
    return text(
        """
        UPDATE jute_prod_winding_doff
        SET weighing_id = :weighing_id
        WHERE winding_doff_id IN :ids
        """
    ).bindparams(bindparam("ids", expanding=True))


def get_doff_group_rows_query():
    """Every active row of one weighing — the shares of all its winders.

    ``COALESCE(weighing_id, winding_doff_id)`` makes a pre-column row its own
    group, so legacy single-winder rows resolve to exactly themselves. Ordered by
    id so a re-split re-applies in insertion order and the last row keeps
    absorbing the rounding remainder.
    """
    return text(
        """
        SELECT winding_doff_id, eb_id, gross_input_wt, production_qty
        FROM jute_prod_winding_doff
        WHERE COALESCE(weighing_id, winding_doff_id) = :group_id
          AND (active = 1 OR active IS NULL)
        ORDER BY winding_doff_id
        """
    )


def get_doff_by_date_query():
    """Doff rows for the day grid (spell_id and eb_id optional).

    LEFT JOIN to the worker so a row whose eb_id no longer resolves to an active
    HRMS employee (deleted or deactivated) is still returned with a blank worker
    rather than dropped off the day's grid.
    """
    return text(
        f"""
        SELECT
            wd.winding_doff_id,
            COALESCE(wd.weighing_id, wd.winding_doff_id) AS weighing_id,
            wd.co_id,
            wd.branch_id,
            wd.tran_date,
            wd.spell_id,
            sp.spell_code,
            wd.eb_id,
            {_emp_code_sql("wd")},
            {_WORKER_NAME_SQL},
            wd.item_id,
            im.item_code,
            im.item_name,
            wd.trolly_id,
            t.trolly_name,
            wd.trolly_wt,
            wd.spool_id,
            s.trolly_name AS spool_name,
            wd.spool_wt,
            wd.gross_input_wt,
            wd.production_qty,
            wd.row_gross_wt
        FROM jute_prod_winding_doff wd
        LEFT JOIN hrms_ed_personal_details p ON p.eb_id = wd.eb_id
        LEFT JOIN trolly_mst t ON t.trolly_id = wd.trolly_id
        LEFT JOIN trolly_mst s ON s.trolly_id = wd.spool_id
        LEFT JOIN item_mst im ON im.item_id = wd.item_id
        LEFT JOIN (
            SELECT spell_code, MIN(spell_id) AS spell_id
            FROM spell_mst WHERE status = 1 GROUP BY spell_code
        ) sp ON sp.spell_id = wd.spell_id
        WHERE wd.branch_id = :branch_id
          AND wd.tran_date = :tran_date
          AND (wd.active = 1 OR wd.active IS NULL)
          AND (:spell_id IS NULL OR wd.spell_id = :spell_id)
          AND (:eb_id IS NULL OR wd.eb_id = :eb_id)
        ORDER BY emp_code, wd.winding_doff_id
        """
    )


def get_doff_active_by_id_query():
    """One active doff row (full body) for edit/delete validation.

    ``weighing_id`` comes back COALESCEd to the row's own id so callers can use
    it as the group key unconditionally.
    """
    return text(
        """
        SELECT
            winding_doff_id,
            COALESCE(weighing_id, winding_doff_id) AS weighing_id,
            co_id, branch_id, tran_date, spell_id, eb_id,
            item_id, trolly_id, trolly_wt, spool_id, spool_wt,
            gross_input_wt, production_qty, row_gross_wt
        FROM jute_prod_winding_doff
        WHERE winding_doff_id = :id
          AND (active = 1 OR active IS NULL)
          AND (:branch_id IS NULL OR branch_id = :branch_id)
        """
    )


def update_doff_row_query():
    """Update one doff row's quality + recomputed weights."""
    return text(
        """
        UPDATE jute_prod_winding_doff
        SET item_id = :item_id,
            trolly_id = :trolly_id,
            trolly_wt = :trolly_wt,
            spool_id = :spool_id,
            spool_wt = :spool_wt,
            gross_input_wt = :gross_input_wt,
            production_qty = :production_qty,
            row_gross_wt = :row_gross_wt,
            updated_by = :updated_by
        WHERE winding_doff_id = :id
        """
    )


def soft_delete_doff_group_query():
    """Soft-delete a whole weighing — every winder's share of it.

    Deleting one share of a shared weighing would leave the survivors summing to
    less than any real weighing, and the spinning planning grid (which sums
    production_qty per item + shift bucket) would silently lose that share. A
    legacy single-winder row is its own group, so this is the old per-row delete
    for every row written before the split existed.
    """
    return text(
        """
        UPDATE jute_prod_winding_doff
        SET active = 0,
            updated_by = :updated_by
        WHERE COALESCE(weighing_id, winding_doff_id) = :group_id
          AND (active = 1 OR active IS NULL)
        """
    )


# =============================================================================
# Jugar (jute_prod_winding_jugar) builders
# =============================================================================


def get_jugar_saved_pair_query():
    """Both saved jugar rows (O and C) for one branch/date/spell/winder.

    Drives the two-field jugar form: what is already stored wins over the
    carry-forward, and the ids let the save UPSERT instead of 400-ing on a
    duplicate. Highest id per open_close wins (caller keeps the last row).

    Scoped on branch_id, NOT co_id: a branch belongs to exactly one company, so
    the branch is the stricter key and co_id adds nothing. Every winding row
    carries a branch (writes derive it from the winder's HRMS record and reject
    a worker without one), so this is a plain required equality.
    """
    return text(
        """
        SELECT open_close, winding_jugar_id, weight
        FROM jute_prod_winding_jugar
        WHERE branch_id = :branch_id
          AND tran_date = :tran_date
          AND spell_id = :spell_id
          AND eb_id = :eb_id
          AND (active = 1 OR active IS NULL)
        ORDER BY winding_jugar_id
        """
    )


def get_jugar_prev_seq_query():
    """Latest :open_close jugar for a winder strictly BEFORE this spell, in spell
    sequence order.

    "Before" = an earlier date, OR the same date at an earlier
    ``spell_mst.starting_time`` — so the carry crosses spells within one day
    (A -> B -> C) and wraps back to the last spell of an earlier date, skipping
    any spell the winder did not work. Scoped BRANCH + person (a branch belongs
    to one company, so branch_id supersedes co_id). The current row can never
    match itself (``starting_time <`` its own is false).

    :spell_id NULL (no spell on the request) degrades to prior dates only.
    Binds: :branch_id :eb_id :tran_date :spell_id :open_close.
    """
    return text(
        """
        SELECT j.winding_jugar_id, j.weight, j.tran_date, j.spell_id
        FROM jute_prod_winding_jugar j
        JOIN spell_mst sp ON sp.spell_id = j.spell_id
        WHERE j.branch_id = :branch_id
          AND j.eb_id = :eb_id
          AND j.open_close = :open_close
          AND (j.active = 1 OR j.active IS NULL)
          AND (
                j.tran_date < :tran_date
             OR (j.tran_date = :tran_date
                 AND sp.starting_time < (
                     SELECT s2.starting_time FROM spell_mst s2 WHERE s2.spell_id = :spell_id
                 ))
              )
        ORDER BY j.tran_date DESC, sp.starting_time DESC, j.winding_jugar_id DESC
        LIMIT 1
        """
    )


def insert_jugar_row_query():
    """Insert a fresh active jugar row (person-keyed; machine_id stays NULL)."""
    return text(
        """
        INSERT INTO jute_prod_winding_jugar
            (co_id, branch_id, tran_date, spell_id, eb_id, weight,
             open_close, active, updated_by)
        VALUES
            (:co_id, :branch_id, :tran_date, :spell_id, :eb_id, :weight,
             :open_close, 1, :updated_by)
        """
    )


def update_jugar_row_query():
    """Update an existing active jugar row's weight."""
    return text(
        """
        UPDATE jute_prod_winding_jugar
        SET weight = :weight,
            updated_by = :updated_by
        WHERE winding_jugar_id = :id
        """
    )


def get_jugar_active_by_id_query():
    """One active jugar row (id + side) for update/validation.

    ``open_close`` comes back because the weight band differs per side — an
    opening may be 0, a closing may not.
    """
    return text(
        """
        SELECT winding_jugar_id, open_close
        FROM jute_prod_winding_jugar
        WHERE winding_jugar_id = :id
          AND (active = 1 OR active IS NULL)
        """
    )


def get_jugar_by_date_query():
    """Jugar rows for the grid, BRANCH-scoped (spell_id and open_close optional).

    LEFT JOIN to the worker keeps a row visible when its eb_id no longer resolves
    to an active HRMS employee.
    """
    return text(
        f"""
        SELECT
            wj.winding_jugar_id,
            wj.co_id,
            wj.branch_id,
            wj.tran_date,
            wj.spell_id,
            sp.spell_code,
            wj.eb_id,
            {_emp_code_sql("wj")},
            {_WORKER_NAME_SQL},
            wj.weight,
            wj.open_close
        FROM jute_prod_winding_jugar wj
        LEFT JOIN hrms_ed_personal_details p ON p.eb_id = wj.eb_id
        LEFT JOIN (
            SELECT spell_code, MIN(spell_id) AS spell_id
            FROM spell_mst WHERE status = 1 GROUP BY spell_code
        ) sp ON sp.spell_id = wj.spell_id
        WHERE wj.branch_id = :branch_id
          AND wj.tran_date = :tran_date
          AND (wj.active = 1 OR wj.active IS NULL)
          AND (:spell_id IS NULL OR wj.spell_id = :spell_id)
          AND (:open_close IS NULL OR wj.open_close = :open_close)
        ORDER BY emp_code, wj.open_close, wj.winding_jugar_id
        """
    )


# =============================================================================
# Quality (jute_prod_winding_daily_qlty) — the person -> quality map
# =============================================================================


def get_quality_exists_query():
    """Count active quality rows for branch/date/spell (gate for auto-seed)."""
    return text(
        """
        SELECT COUNT(*) AS cnt
        FROM jute_prod_winding_daily_qlty
        WHERE branch_id = :branch_id
          AND tran_date = :tran_date
          AND spell_id = :spell_id
          AND (active = 1 OR active IS NULL)
        """
    )


def get_quality_prev_seed_date_spell_query():
    """The latest prior (date, spell) that has active quality rows (auto-seed source).

    Mirrors legacy getwndqcData: MAX(tran_date) <= the target date, then the
    highest spell on that date. Returns the previous tran_date + spell_id whose
    winders (with their item_id / no_of_spindle) should be carried forward.
    """
    return text(
        """
        SELECT q.tran_date AS prev_date, q.spell_id AS prev_spell_id
        FROM jute_prod_winding_daily_qlty q
        WHERE q.branch_id = :branch_id
          AND (q.active = 1 OR q.active IS NULL)
          AND (
                q.tran_date < :tran_date
             OR (q.tran_date = :tran_date AND q.spell_id <> :spell_id)
          )
        ORDER BY q.tran_date DESC, q.spell_id DESC
        LIMIT 1
        """
    )


def auto_seed_quality_query():
    """Carry the previous spell's WINDERS forward into date/spell.

    One row per person who had a quality mapped in the previous (date, spell),
    keeping their item_id + no_of_spindle + machine_id. A day with no prior rows
    seeds NOTHING (empty map — the user adds winders via /quality_add), because
    prev_date / prev_spell_id NULL selects zero rows.

    Guarded by NOT EXISTS on (branch, date, spell, eb) so a re-run is idempotent.
    Source and guard are BRANCH-scoped (co_id is still written, never filtered on);
    co_id and updated_by are parameterised (fixes the legacy hardcoded
    company_id=2 / created_by=26586).
    """
    return text(
        """
        INSERT INTO jute_prod_winding_daily_qlty
            (co_id, branch_id, tran_date, spell_id, eb_id, item_id,
             machine_id, no_of_spindle, active, updated_by)
        SELECT
            :co_id, :branch_id, :tran_date, :spell_id,
            pq.eb_id, pq.item_id, pq.machine_id,
            COALESCE(pq.no_of_spindle, 0), 1, :updated_by
        FROM jute_prod_winding_daily_qlty pq
        WHERE pq.branch_id = :branch_id
          AND pq.tran_date = :prev_date
          AND pq.spell_id = :prev_spell_id
          AND pq.eb_id IS NOT NULL
          AND (pq.active = 1 OR pq.active IS NULL)
          AND NOT EXISTS (
              SELECT 1 FROM jute_prod_winding_daily_qlty x
              WHERE x.branch_id = :branch_id
                AND x.tran_date = :tran_date
                AND x.spell_id = :spell_id
                AND x.eb_id = pq.eb_id
                AND (x.active = 1 OR x.active IS NULL)
          )
        """
    )


def insert_quality_row_query():
    """Add one winder to the day's person -> quality map (POST /quality_add)."""
    return text(
        """
        INSERT INTO jute_prod_winding_daily_qlty
            (co_id, branch_id, tran_date, spell_id, eb_id, item_id,
             machine_id, no_of_spindle, active, updated_by)
        VALUES
            (:co_id, :branch_id, :tran_date, :spell_id, :eb_id, :item_id,
             :machine_id, :no_of_spindle, 1, :updated_by)
        """
    )


def get_quality_by_date_query():
    """Person -> quality map rows for the grid (spell_id optional).

    LEFT JOIN to the worker keeps a row visible when its eb_id no longer resolves
    to an active HRMS employee; the machine join is LEFT for the same reason —
    a row with a NULL or stale machine_id still shows, with a blank machine.
    """
    return text(
        f"""
        SELECT
            q.winding_daily_qlty_id,
            q.co_id,
            q.branch_id,
            q.tran_date,
            q.spell_id,
            sp.spell_code,
            q.eb_id,
            {_emp_code_sql("q")},
            {_WORKER_NAME_SQL},
            q.item_id,
            im.item_code,
            im.item_name,
            q.machine_id,
            m.machine_name,
            m.mech_code,
            q.no_of_spindle
        FROM jute_prod_winding_daily_qlty q
        LEFT JOIN hrms_ed_personal_details p ON p.eb_id = q.eb_id
        LEFT JOIN item_mst im ON im.item_id = q.item_id
        LEFT JOIN machine_mst m ON m.machine_id = q.machine_id
        LEFT JOIN (
            SELECT spell_code, MIN(spell_id) AS spell_id
            FROM spell_mst WHERE status = 1 GROUP BY spell_code
        ) sp ON sp.spell_id = q.spell_id
        WHERE q.branch_id = :branch_id
          AND q.tran_date = :tran_date
          AND (q.active = 1 OR q.active IS NULL)
          AND (:spell_id IS NULL OR q.spell_id = :spell_id)
        ORDER BY emp_code, q.winding_daily_qlty_id
        """
    )


def get_quality_active_by_id_query():
    """One active quality row (id + eb/date/spell) for update/delete validation."""
    return text(
        """
        SELECT winding_daily_qlty_id, co_id, branch_id, eb_id, tran_date, spell_id
        FROM jute_prod_winding_daily_qlty
        WHERE winding_daily_qlty_id = :id
          AND (active = 1 OR active IS NULL)
        """
    )


def get_quality_duplicate_query():
    """Another active quality row for the same winder/date/spell (duplicate guard).

    Excludes the row being updated (:exclude_id) so a self-update is not blocked;
    pass 0 when adding a new winder (there is no row to exclude).
    """
    return text(
        """
        SELECT winding_daily_qlty_id
        FROM jute_prod_winding_daily_qlty
        WHERE branch_id = :branch_id
          AND tran_date = :tran_date
          AND spell_id = :spell_id
          AND eb_id = :eb_id
          AND winding_daily_qlty_id <> :exclude_id
          AND (active = 1 OR active IS NULL)
        LIMIT 1
        """
    )


def update_quality_row_query():
    """Update one quality row's quality + machine + spindle count."""
    return text(
        """
        UPDATE jute_prod_winding_daily_qlty
        SET item_id = :item_id,
            machine_id = :machine_id,
            no_of_spindle = :no_of_spindle,
            updated_by = :updated_by
        WHERE winding_daily_qlty_id = :id
        """
    )


def soft_delete_quality_row_query():
    """Soft-delete one quality row (drops a carried-forward winder who is absent)."""
    return text(
        """
        UPDATE jute_prod_winding_daily_qlty
        SET active = 0,
            updated_by = :updated_by
        WHERE winding_daily_qlty_id = :id
        """
    )


# =============================================================================
# Reconciliation + reports
# =============================================================================


def get_winding_reconciliation_query():
    """Reconciled production (kg) per winder/spell/quality for a date (spec §6).

    production_kg = SUM(doff.production_qty) - opening_jugar + closing_jugar
    where opening = MAX(weight WHERE open_close='O') and
          closing = MAX(weight WHERE open_close='C')
    per (branch_id, tran_date, spell_id, eb_id) — the jugar adjustment is applied
    once per person/spell, as it was once per machine/spell before.

    The yarn comes from the doff row itself, falling back to the person -> quality
    map: COALESCE(doff.item_id, dq.item_id). A winder runs one quality per spell
    (that is what the map means), so MAX(item_id) inside the doff group IS that
    quality. ponytail: if a winder ever runs two qualities in one spell their kg
    collapses onto one of them — the same grain the machine-keyed version had;
    split the group by item only if the mill starts doing that.

    spell_id and yarn-item filters are optional. shift bucket = LEFT(spell_code,1).
    The jugar and quality-map joins are LEFT so a winder who doffed but logged no
    jugar (or has no quality mapped) still reports their raw doff sum; the worker
    join is LEFT so an eb_id that no longer resolves in HRMS still reports its kg
    with a blank worker name.

    Scope key is :branch_id (REQUIRED), not :co_id — a branch belongs to exactly
    one company, so the branch is the stricter key and co_id adds nothing. All
    three subqueries filter on it and join branch-to-branch, so one branch's
    jugar can never adjust another branch's doff for a winder whose eb_id
    appears in both. Every winding row carries a branch (writes derive it from
    the winder's HRMS record and reject a worker without one).
    """
    return text(
        """
        SELECT
            doff.tran_date,
            doff.spell_id,
            sp.spell_code,
            LEFT(sp.spell_code, 1) AS shift,
            doff.eb_id,
            (SELECT NULLIF(TRIM(o.emp_code), '')
               FROM hrms_ed_official_details o
              WHERE o.eb_id = doff.eb_id AND o.active = 1
              LIMIT 1) AS emp_code,
            TRIM(CONCAT_WS(' ', p.first_name, p.middle_name, p.last_name)) AS worker_name,
            COALESCE(doff.item_id, dq.item_id) AS item_id,
            im.item_code,
            im.item_name,
            doff.sum_production,
            COALESCE(jg.opening_wt, 0) AS opening_jugar,
            COALESCE(jg.closing_wt, 0) AS closing_jugar,
            (doff.sum_production - COALESCE(jg.opening_wt, 0) + COALESCE(jg.closing_wt, 0))
                AS production_kg
        FROM (
            SELECT branch_id, tran_date, spell_id, eb_id,
                   MAX(item_id) AS item_id,
                   SUM(production_qty) AS sum_production
            FROM jute_prod_winding_doff
            WHERE branch_id = :branch_id
              AND tran_date = :tran_date
              AND (active = 1 OR active IS NULL)
              AND (:spell_id IS NULL OR spell_id = :spell_id)
            GROUP BY branch_id, tran_date, spell_id, eb_id
        ) doff
        LEFT JOIN (
            SELECT branch_id, tran_date, spell_id, eb_id,
                   MAX(CASE WHEN open_close = 'O' THEN weight END) AS opening_wt,
                   MAX(CASE WHEN open_close = 'C' THEN weight END) AS closing_wt
            FROM jute_prod_winding_jugar
            WHERE branch_id = :branch_id
              AND tran_date = :tran_date
              AND (active = 1 OR active IS NULL)
            GROUP BY branch_id, tran_date, spell_id, eb_id
        ) jg
               ON jg.branch_id = doff.branch_id
              AND jg.tran_date = doff.tran_date
              AND jg.spell_id = doff.spell_id
              AND jg.eb_id = doff.eb_id
        LEFT JOIN (
            SELECT branch_id, tran_date, spell_id, eb_id,
                   MAX(item_id) AS item_id
            FROM jute_prod_winding_daily_qlty
            WHERE branch_id = :branch_id
              AND tran_date = :tran_date
              AND (active = 1 OR active IS NULL)
            GROUP BY branch_id, tran_date, spell_id, eb_id
        ) dq
               ON dq.branch_id = doff.branch_id
              AND dq.tran_date = doff.tran_date
              AND dq.spell_id = doff.spell_id
              AND dq.eb_id = doff.eb_id
        LEFT JOIN hrms_ed_personal_details p ON p.eb_id = doff.eb_id
        LEFT JOIN (
            SELECT spell_code, MIN(spell_id) AS spell_id
            FROM spell_mst WHERE status = 1 GROUP BY spell_code
        ) sp ON sp.spell_id = doff.spell_id
        LEFT JOIN item_mst im ON im.item_id = COALESCE(doff.item_id, dq.item_id)
        WHERE (:item_id IS NULL OR COALESCE(doff.item_id, dq.item_id) = :item_id)
        ORDER BY sp.spell_code, emp_code
        """
    )
