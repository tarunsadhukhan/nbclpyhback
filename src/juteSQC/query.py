"""
SQL query functions for Jute SQC module.
Morrah Weight QC queries.
"""

from sqlalchemy.sql import text


def get_morrah_wt_table_query(search: str = None):
    search_filter = ""
    if search:
        search_filter = """
            AND (
                mw.trolley_no LIKE :search
                OR mw.inspector_name LIKE :search
                OR im.item_name LIKE :search
            )
        """

    sql = f"""
        SELECT
            mw.morrah_wt_id,
            mw.entry_date,
            mw.trolley_no,
            mw.inspector_name,
            mw.avg_mr_pct,
            mw.calc_avg_weight,
            mw.calc_max_weight,
            mw.calc_min_weight,
            mw.calc_range,
            mw.calc_cv_pct,
            mw.count_lt,
            mw.count_ok,
            mw.count_hy,
            mw.branch_id,
            dm.dept_desc AS department,
            im.item_name AS jute_quality,
            mw.updated_date_time
        FROM jute_sqc_morrah_wt mw
        LEFT JOIN dept_mst dm ON dm.dept_id = mw.dept_id
        LEFT JOIN item_mst im ON im.item_id = mw.item_id
        WHERE mw.co_id = :co_id
        AND mw.active = 1
        {search_filter}
        ORDER BY mw.entry_date DESC, mw.morrah_wt_id DESC
        LIMIT :limit OFFSET :offset
    """
    return text(sql)


def get_morrah_wt_table_count_query(search: str = None):
    search_filter = ""
    if search:
        search_filter = """
            AND (
                mw.trolley_no LIKE :search
                OR mw.inspector_name LIKE :search
                OR im.item_name LIKE :search
            )
        """

    sql = f"""
        SELECT COUNT(*) AS total
        FROM jute_sqc_morrah_wt mw
        LEFT JOIN dept_mst dm ON dm.dept_id = mw.dept_id
        LEFT JOIN item_mst im ON im.item_id = mw.item_id
        WHERE mw.co_id = :co_id
        AND mw.active = 1
        {search_filter}
    """
    return text(sql)


def get_morrah_wt_by_id_query():
    sql = """
        SELECT
            mw.morrah_wt_id,
            mw.co_id,
            mw.branch_id,
            mw.entry_date,
            mw.inspector_name,
            mw.dept_id,
            mw.item_id,
            mw.trolley_no,
            mw.avg_mr_pct,
            mw.weights,
            mw.calc_avg_weight,
            mw.calc_max_weight,
            mw.calc_min_weight,
            mw.calc_range,
            mw.calc_cv_pct,
            mw.count_lt,
            mw.count_ok,
            mw.count_hy,
            mw.updated_date_time,
            dm.dept_desc AS department,
            im.item_name AS jute_quality
        FROM jute_sqc_morrah_wt mw
        LEFT JOIN dept_mst dm ON dm.dept_id = mw.dept_id
        LEFT JOIN item_mst im ON im.item_id = mw.item_id
        WHERE mw.morrah_wt_id = :morrah_wt_id
        AND mw.active = 1
    """
    return text(sql)


def get_morrah_wt_departments_query():
    sql = """
        SELECT dept_id, dept_desc, dept_code
        FROM dept_mst
        WHERE branch_id = :branch_id
        ORDER BY dept_desc
    """
    return text(sql)


def get_morrah_wt_jute_qualities_query():
    sql = """
        SELECT im.item_id, im.item_name, im.item_code
        FROM item_mst im
        JOIN item_grp_mst igm ON igm.item_grp_id = im.item_grp_id
        JOIN item_grp_mst parent ON parent.item_grp_id = igm.parent_grp_id
        WHERE parent.item_type_id = 2
        AND igm.co_id = :co_id
        AND (im.active = 1 OR im.active IS NULL)
        ORDER BY im.item_name
    """
    return text(sql)


# =============================================================================
# R-08-04 Spreader Roll Weight QC queries
# =============================================================================
#
# The machine list (spreader-type, with snapshot wt_per_roll + band edges) and
# the raw-jute quality list are REUSED from existing builders:
#   * get_spreader_machines_query        (src/juteProduction/query.py)
#   * get_morrah_wt_jute_qualities_query  (above, this module)
# Only the genuinely-new builders live here.


def get_spreader_roll_wt_spells_query():
    """Active spells for the spell (SHIFT) picker, branch-scoped via the parent
    shift. spell_mst has no branch_id/co_id; branch comes from shift_mst. Filter
    is status = 1 (NOT active). Callers de-duplicate by spell_code in Python.

    Mirrors get_spells_query() in src/juteProduction/spinning_query.py.
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


def get_spreader_quality_std_query():
    """std_mr_pct snapshot for a raw-jute quality (used to correct readings at
    save). Reads the item_id-keyed satellite jute_spreader_quality_attr; the
    router falls back to base 16 when no active row / NULL is found."""
    return text(
        """
        SELECT std_mr_pct
        FROM jute_spreader_quality_attr
        WHERE item_id = :item_id
          AND active = 1
        ORDER BY spreader_quality_attr_id DESC
        LIMIT 1
        """
    )


def get_spreader_machine_band_edges_query():
    """The 5 band-edge columns snapshot for a machine (used to bucket readings at
    save). Reads spreader_machine_attr; the router falls back to the default
    55/60/65/70/75 edge set when no active row / NULL edges are found."""
    return text(
        """
        SELECT band_edge_1, band_edge_2, band_edge_3, band_edge_4, band_edge_5
        FROM spreader_machine_attr
        WHERE machine_id = :mc_id
          AND co_id = :co_id
          AND active = 1
        ORDER BY spreader_machine_attr_id DESC
        LIMIT 1
        """
    )


def get_spreader_roll_wt_table_query(search: str = None):
    search_filter = ""
    if search:
        search_filter = """
            AND (
                rw.feeder_name LIKE :search
                OR im.item_name LIKE :search
                OR m.machine_name LIKE :search
            )
        """

    sql = f"""
        SELECT
            rw.spreader_roll_wt_id,
            rw.co_id,
            rw.branch_id,
            rw.entry_date,
            rw.spell_id,
            sp.spell_code,
            rw.mc_id,
            m.machine_name,
            m.mech_code,
            rw.item_id,
            im.item_name AS jute_quality,
            im.item_code,
            rw.feeder_name,
            rw.std_mr_pct,
            rw.calc_avg_mr_pct,
            rw.calc_avg_obs,
            rw.calc_avg_corr,
            rw.calc_stdev_obs,
            rw.calc_stdev_corr,
            rw.calc_cv_pct,
            rw.updated_date_time
        FROM jute_sqc_spreader_roll_wt rw
        LEFT JOIN machine_mst m ON m.machine_id = rw.mc_id
        LEFT JOIN item_mst im ON im.item_id = rw.item_id
        LEFT JOIN (
            SELECT spell_id, MIN(spell_code) AS spell_code FROM spell_mst WHERE status = 1 GROUP BY spell_id
        ) sp ON sp.spell_id = rw.spell_id
        WHERE rw.co_id = :co_id
        AND rw.active = 1
        {search_filter}
        ORDER BY rw.entry_date DESC, rw.spreader_roll_wt_id DESC
        LIMIT :limit OFFSET :offset
    """
    return text(sql)


def get_spreader_roll_wt_table_count_query(search: str = None):
    search_filter = ""
    if search:
        search_filter = """
            AND (
                rw.feeder_name LIKE :search
                OR im.item_name LIKE :search
                OR m.machine_name LIKE :search
            )
        """

    sql = f"""
        SELECT COUNT(*) AS total
        FROM jute_sqc_spreader_roll_wt rw
        LEFT JOIN machine_mst m ON m.machine_id = rw.mc_id
        LEFT JOIN item_mst im ON im.item_id = rw.item_id
        WHERE rw.co_id = :co_id
        AND rw.active = 1
        {search_filter}
    """
    return text(sql)


def get_spreader_roll_wt_by_id_query():
    sql = """
        SELECT
            rw.spreader_roll_wt_id,
            rw.co_id,
            rw.branch_id,
            rw.entry_date,
            rw.spell_id,
            sp.spell_code,
            rw.mc_id,
            m.machine_name,
            m.mech_code,
            rw.item_id,
            im.item_name AS jute_quality,
            im.item_code,
            rw.feeder_name,
            rw.roll_weights,
            rw.mr_pcts,
            rw.std_mr_pct,
            rw.calc_avg_mr_pct,
            rw.calc_avg_obs,
            rw.calc_avg_corr,
            rw.calc_stdev_obs,
            rw.calc_stdev_corr,
            rw.calc_cv_pct,
            rw.band_counts_obs,
            rw.band_counts_corr,
            rw.updated_date_time
        FROM jute_sqc_spreader_roll_wt rw
        LEFT JOIN machine_mst m ON m.machine_id = rw.mc_id
        LEFT JOIN item_mst im ON im.item_id = rw.item_id
        LEFT JOIN (
            SELECT spell_id, MIN(spell_code) AS spell_code FROM spell_mst WHERE status = 1 GROUP BY spell_id
        ) sp ON sp.spell_id = rw.spell_id
        WHERE rw.spreader_roll_wt_id = :spreader_roll_wt_id
        AND rw.active = 1
        AND (:co_id IS NULL OR rw.co_id = :co_id)
    """
    return text(sql)


def get_spreader_roll_wt_by_date_query():
    """Active roll-weight rows for a co/entry_date (branch optional), labelled.

    Returns the persisted readings + calc_*/band JSON so the caller can json.loads
    them for the date-driven grid.
    """
    sql = """
        SELECT
            rw.spreader_roll_wt_id,
            rw.co_id,
            rw.branch_id,
            rw.entry_date,
            rw.spell_id,
            sp.spell_code,
            rw.mc_id,
            m.machine_name,
            m.mech_code,
            rw.item_id,
            im.item_name AS jute_quality,
            im.item_code,
            rw.feeder_name,
            rw.roll_weights,
            rw.mr_pcts,
            rw.std_mr_pct,
            rw.calc_avg_mr_pct,
            rw.calc_avg_obs,
            rw.calc_avg_corr,
            rw.calc_stdev_obs,
            rw.calc_stdev_corr,
            rw.calc_cv_pct,
            rw.band_counts_obs,
            rw.band_counts_corr,
            rw.updated_date_time
        FROM jute_sqc_spreader_roll_wt rw
        LEFT JOIN machine_mst m ON m.machine_id = rw.mc_id
        LEFT JOIN item_mst im ON im.item_id = rw.item_id
        LEFT JOIN (
            SELECT spell_id, MIN(spell_code) AS spell_code FROM spell_mst WHERE status = 1 GROUP BY spell_id
        ) sp ON sp.spell_id = rw.spell_id
        WHERE rw.co_id = :co_id
        AND rw.entry_date = :entry_date
        AND rw.active = 1
        AND (:branch_id IS NULL OR rw.branch_id = :branch_id OR rw.branch_id IS NULL)
        ORDER BY im.item_name, rw.spreader_roll_wt_id DESC
    """
    return text(sql)


def get_spreader_roll_wt_active_row_query():
    """The active roll-weight row id (for the soft-delete guard)."""
    return text(
        """
        SELECT spreader_roll_wt_id
        FROM jute_sqc_spreader_roll_wt
        WHERE spreader_roll_wt_id = :id
          AND active = 1
        """
    )


def soft_delete_spreader_roll_wt_query():
    """Soft-delete a roll-weight reading (active = 0)."""
    return text(
        """
        UPDATE jute_sqc_spreader_roll_wt
        SET active = 0,
            updated_by = :updated_by
        WHERE spreader_roll_wt_id = :id
        """
    )


# =============================================================================
# R-08-03 Spreader Roll Sliver Weight QC queries
# =============================================================================
#
# Second report of the Sliver/Roll-weight family. Mirrors the R-08-04 roll-weight
# builders above with NO band columns and variable 1-12 readings. The spell /
# machine / quality / std-MR% builders are REUSED verbatim:
#   * get_spreader_roll_wt_spells_query   (above, this module)
#   * get_spreader_machines_query          (src/juteProduction/query.py)
#   * get_morrah_wt_jute_qualities_query   (above, this module)
#   * get_spreader_quality_std_query       (above, this module)
# Only the genuinely-new builders live here.


def get_spreader_sliver_wt_table_query(search: str = None):
    search_filter = ""
    if search:
        search_filter = """
            AND (
                sw.category LIKE :search
                OR im.item_name LIKE :search
                OR m.machine_name LIKE :search
            )
        """

    sql = f"""
        SELECT
            sw.spreader_sliver_wt_id,
            sw.co_id,
            sw.branch_id,
            sw.entry_date,
            sw.spell_id,
            sp.spell_code,
            sw.category,
            sw.mc_id,
            m.machine_name,
            m.mech_code,
            sw.item_id,
            im.item_name AS jute_quality,
            im.item_code,
            sw.sample_length_yds,
            sw.weight_basis,
            sw.std_mr_pct,
            sw.calc_avg_obs,
            sw.calc_avg_corr,
            sw.calc_avg_mr,
            sw.calc_stdev,
            sw.calc_cv_pct,
            sw.updated_date_time
        FROM jute_sqc_spreader_sliver_wt sw
        LEFT JOIN machine_mst m ON m.machine_id = sw.mc_id
        LEFT JOIN item_mst im ON im.item_id = sw.item_id
        LEFT JOIN (
            SELECT spell_id, MIN(spell_code) AS spell_code FROM spell_mst WHERE status = 1 GROUP BY spell_id
        ) sp ON sp.spell_id = sw.spell_id
        WHERE sw.co_id = :co_id
        AND sw.active = 1
        {search_filter}
        ORDER BY sw.entry_date DESC, sw.spreader_sliver_wt_id DESC
        LIMIT :limit OFFSET :offset
    """
    return text(sql)


def get_spreader_sliver_wt_table_count_query(search: str = None):
    search_filter = ""
    if search:
        search_filter = """
            AND (
                sw.category LIKE :search
                OR im.item_name LIKE :search
                OR m.machine_name LIKE :search
            )
        """

    sql = f"""
        SELECT COUNT(*) AS total
        FROM jute_sqc_spreader_sliver_wt sw
        LEFT JOIN machine_mst m ON m.machine_id = sw.mc_id
        LEFT JOIN item_mst im ON im.item_id = sw.item_id
        WHERE sw.co_id = :co_id
        AND sw.active = 1
        {search_filter}
    """
    return text(sql)


def get_spreader_sliver_wt_by_id_query():
    sql = """
        SELECT
            sw.spreader_sliver_wt_id,
            sw.co_id,
            sw.branch_id,
            sw.entry_date,
            sw.spell_id,
            sp.spell_code,
            sw.category,
            sw.mc_id,
            m.machine_name,
            m.mech_code,
            sw.item_id,
            im.item_name AS jute_quality,
            im.item_code,
            sw.sample_length_yds,
            sw.weight_basis,
            sw.observed_weights,
            sw.mr_pcts,
            sw.std_mr_pct,
            sw.calc_avg_obs,
            sw.calc_avg_corr,
            sw.calc_avg_mr,
            sw.calc_stdev,
            sw.calc_cv_pct,
            sw.updated_date_time
        FROM jute_sqc_spreader_sliver_wt sw
        LEFT JOIN machine_mst m ON m.machine_id = sw.mc_id
        LEFT JOIN item_mst im ON im.item_id = sw.item_id
        LEFT JOIN (
            SELECT spell_id, MIN(spell_code) AS spell_code FROM spell_mst WHERE status = 1 GROUP BY spell_id
        ) sp ON sp.spell_id = sw.spell_id
        WHERE sw.spreader_sliver_wt_id = :spreader_sliver_wt_id
        AND sw.active = 1
        AND (:co_id IS NULL OR sw.co_id = :co_id)
    """
    return text(sql)


def get_spreader_sliver_wt_by_date_query():
    """Active sliver-weight rows for a co/entry_date (branch optional), labelled.

    Returns the persisted readings + calc_* JSON/scalars so the caller can
    json.loads them for the date-driven grid.
    """
    sql = """
        SELECT
            sw.spreader_sliver_wt_id,
            sw.co_id,
            sw.branch_id,
            sw.entry_date,
            sw.spell_id,
            sp.spell_code,
            sw.category,
            sw.mc_id,
            m.machine_name,
            m.mech_code,
            sw.item_id,
            im.item_name AS jute_quality,
            im.item_code,
            sw.sample_length_yds,
            sw.weight_basis,
            sw.observed_weights,
            sw.mr_pcts,
            sw.std_mr_pct,
            sw.calc_avg_obs,
            sw.calc_avg_corr,
            sw.calc_avg_mr,
            sw.calc_stdev,
            sw.calc_cv_pct,
            sw.updated_date_time
        FROM jute_sqc_spreader_sliver_wt sw
        LEFT JOIN machine_mst m ON m.machine_id = sw.mc_id
        LEFT JOIN item_mst im ON im.item_id = sw.item_id
        LEFT JOIN (
            SELECT spell_id, MIN(spell_code) AS spell_code FROM spell_mst WHERE status = 1 GROUP BY spell_id
        ) sp ON sp.spell_id = sw.spell_id
        WHERE sw.co_id = :co_id
        AND sw.entry_date = :entry_date
        AND sw.active = 1
        AND (:branch_id IS NULL OR sw.branch_id = :branch_id OR sw.branch_id IS NULL)
        ORDER BY im.item_name, sw.spreader_sliver_wt_id DESC
    """
    return text(sql)


def get_spreader_sliver_wt_active_row_query():
    """The active sliver-weight row id (for the soft-delete guard)."""
    return text(
        """
        SELECT spreader_sliver_wt_id
        FROM jute_sqc_spreader_sliver_wt
        WHERE spreader_sliver_wt_id = :id
          AND active = 1
        """
    )


def soft_delete_spreader_sliver_wt_query():
    """Soft-delete a sliver-weight reading (active = 0)."""
    return text(
        """
        UPDATE jute_sqc_spreader_sliver_wt
        SET active = 0,
            updated_by = :updated_by
        WHERE spreader_sliver_wt_id = :id
        """
    )


# =============================================================================
# R-08-05/06/07 Breaker Card (Coarse Side SWT) QC queries — carding stage
# =============================================================================
#
# First report of the carding/drawing sub-family. Multi-row sheet (one save inserts
# several rows). Uses LINE qualities (item_type_id=5, NOT raw jute) and a NEW
# (item_id, process)-keyed standards satellite jute_draw_quality_std. The spell builder
# and the spreader-machine pattern are REUSED:
#   * get_spreader_roll_wt_spells_query    (above, this module)  -> spells
#   * get_spreader_machines_query          (src/juteProduction/query.py) is the COPY
#     template for get_breaker_card_machines_query below (machine-type swap, no attr join).
# Only the genuinely-new builders live here.


def get_breaker_card_machines_query():
    """Breaker-card machines for a company (machine_type resolved by name).

    Copied from get_spreader_machines_query (src/juteProduction/query.py): same
    machine_mst -> machine_type_mst -> dept_mst walk, branch-scoped via dept_mst.branch_id.
    The machine type is bound at call time via :breaker_type (BREAKER_CARD_MACHINE_TYPE_NAME)
    instead of a hardcoded spreader type. No spreader_machine_attr / wt_per_roll join (the
    breaker card has no per-machine roll-weight snapshot)."""
    return text(
        """
        SELECT
            m.machine_id,
            m.machine_name,
            m.mech_code,
            d.dept_id,
            d.dept_desc AS dept_name,
            d.branch_id
        FROM machine_mst m
        INNER JOIN machine_type_mst mt ON mt.machine_type_id = m.machine_type_id
        INNER JOIN dept_mst d ON d.dept_id = m.dept_id
        WHERE m.active = 1
          AND mt.active = 1
          AND mt.machine_type_name = :breaker_type
          AND (:branch_id IS NULL OR d.branch_id = :branch_id)
        ORDER BY m.machine_name
        """
    )


def get_line_quality_items_query():
    """Active LINE-quality items (item_type_id = 5 'Jute Cloth') for the quality picker.

    Copied from get_finishing_items_query (src/juteProduction/finishing_query.py): the
    item lives in item_mst, while company scope + item type hang off item_grp_mst (item_mst
    has no co_id / item_type). Filtered to item_grp_mst.item_type_id = 5 — the line
    qualities, NOT raw jute (item_type_id=2). full_item_code rides along from
    vw_item_with_group_path for display."""
    return text(
        """
        SELECT i.item_id, i.item_code, vip.full_item_code, i.item_name,
               g.item_grp_id, g.item_grp_name, g.item_type_id
        FROM item_mst i
        INNER JOIN item_grp_mst g ON g.item_grp_id = i.item_grp_id
        LEFT JOIN vw_item_with_group_path vip ON vip.item_id = i.item_id
        WHERE i.active = 1
          AND g.co_id = :co_id
          AND g.item_type_id = 5
        ORDER BY i.item_name
        """
    )


def get_draw_quality_std_query():
    """std_mr_pct + std CV band snapshot for a (line-quality, process) pair.

    Reads the (item_id, process)-keyed satellite jute_draw_quality_std; the router falls
    back to base 16 for std MR and to NULL band edges (no cv_within_band) when no active
    row / NULL is found. process is bound (BREAKER_PROCESS = 'BREAKER' for this report)."""
    return text(
        """
        SELECT std_mr_pct, std_cv_low, std_cv_high, std_weight, std_wt_tol
        FROM jute_draw_quality_std
        WHERE item_id = :item_id
          AND process = :process
          AND active = 1
        ORDER BY draw_quality_std_id DESC
        LIMIT 1
        """
    )


def get_breaker_card_swt_table_query(search: str = None):
    search_filter = ""
    if search:
        search_filter = """
            AND (
                im.item_name LIKE :search
                OR bp.plan_name LIKE :search
                OR m.machine_name LIKE :search
                OR m.mech_code LIKE :search
            )
        """

    sql = f"""
        SELECT
            bc.breaker_card_swt_id,
            bc.co_id,
            bc.branch_id,
            bc.entry_date,
            bc.spell_id,
            sp.spell_code,
            bc.mc_id,
            m.machine_name,
            m.mech_code,
            bc.item_id,
            im.item_name AS jute_quality,
            im.item_code,
            bc.batch_plan_id,
            bp.plan_name AS batch_plan_name,
            bc.card_side,
            bc.std_mr_pct,
            bc.std_cv_low,
            bc.std_cv_high,
            bc.calc_wt,
            bc.calc_mr_pct,
            bc.calc_corr_wt,
            bc.calc_sdev,
            bc.calc_cv_pct,
            bc.cv_within_band,
            bc.updated_date_time
        FROM jute_sqc_breaker_card_swt bc
        LEFT JOIN machine_mst m ON m.machine_id = bc.mc_id
        LEFT JOIN item_mst im ON im.item_id = bc.item_id
        LEFT JOIN jute_batch_plan bp ON bp.batch_plan_id = bc.batch_plan_id
        LEFT JOIN (
            SELECT spell_id, MIN(spell_code) AS spell_code FROM spell_mst WHERE status = 1 GROUP BY spell_id
        ) sp ON sp.spell_id = bc.spell_id
        WHERE bc.co_id = :co_id
        AND bc.active = 1
        AND (:branch_id IS NULL OR bc.branch_id = :branch_id)
        {search_filter}
        ORDER BY bc.entry_date DESC, bc.breaker_card_swt_id DESC
        LIMIT :limit OFFSET :offset
    """
    return text(sql)


def get_breaker_card_swt_table_count_query(search: str = None):
    search_filter = ""
    if search:
        search_filter = """
            AND (
                im.item_name LIKE :search
                OR bp.plan_name LIKE :search
                OR m.machine_name LIKE :search
                OR m.mech_code LIKE :search
            )
        """

    sql = f"""
        SELECT COUNT(*) AS total
        FROM jute_sqc_breaker_card_swt bc
        LEFT JOIN machine_mst m ON m.machine_id = bc.mc_id
        LEFT JOIN item_mst im ON im.item_id = bc.item_id
        LEFT JOIN jute_batch_plan bp ON bp.batch_plan_id = bc.batch_plan_id
        WHERE bc.co_id = :co_id
        AND bc.active = 1
        AND (:branch_id IS NULL OR bc.branch_id = :branch_id)
        {search_filter}
    """
    return text(sql)


def get_breaker_card_swt_by_id_query():
    """One breaker-card row by id, tenant-scoped via the optional :co_id guard."""
    sql = """
        SELECT
            bc.breaker_card_swt_id,
            bc.co_id,
            bc.branch_id,
            bc.entry_date,
            bc.spell_id,
            sp.spell_code,
            bc.mc_id,
            m.machine_name,
            m.mech_code,
            bc.item_id,
            im.item_name AS jute_quality,
            im.item_code,
            bc.batch_plan_id,
            bp.plan_name AS batch_plan_name,
            bc.card_side,
            bc.weights,
            bc.mr_pcts,
            bc.std_mr_pct,
            bc.std_cv_low,
            bc.std_cv_high,
            bc.calc_wt,
            bc.calc_mr_pct,
            bc.calc_corr_wt,
            bc.calc_sdev,
            bc.calc_cv_pct,
            bc.cv_within_band,
            bc.updated_date_time
        FROM jute_sqc_breaker_card_swt bc
        LEFT JOIN machine_mst m ON m.machine_id = bc.mc_id
        LEFT JOIN item_mst im ON im.item_id = bc.item_id
        LEFT JOIN jute_batch_plan bp ON bp.batch_plan_id = bc.batch_plan_id
        LEFT JOIN (
            SELECT spell_id, MIN(spell_code) AS spell_code FROM spell_mst WHERE status = 1 GROUP BY spell_id
        ) sp ON sp.spell_id = bc.spell_id
        WHERE bc.breaker_card_swt_id = :breaker_card_swt_id
        AND bc.active = 1
        AND (:co_id IS NULL OR bc.co_id = :co_id)
    """
    return text(sql)


def get_breaker_card_swt_by_date_query():
    """Active breaker-card rows for a co/entry_date (branch optional), labelled.

    Returns the persisted readings (weights / mr_pcts JSON) + batch + calc_*/std band columns
    so the caller can json.loads them AND re-pool the corrected cuts for the per-batch grand
    average. Ordered by batch so grand-average grouping is contiguous. Branch-scoped strictly
    (no NULL-branch leak) so the day's grid is per-branch."""
    sql = """
        SELECT
            bc.breaker_card_swt_id,
            bc.co_id,
            bc.branch_id,
            bc.entry_date,
            bc.spell_id,
            sp.spell_code,
            bc.mc_id,
            m.machine_name,
            m.mech_code,
            bc.item_id,
            im.item_name AS jute_quality,
            im.item_code,
            bc.batch_plan_id,
            bp.plan_name AS batch_plan_name,
            bc.card_side,
            bc.weights,
            bc.mr_pcts,
            bc.std_mr_pct,
            bc.std_cv_low,
            bc.std_cv_high,
            bc.calc_wt,
            bc.calc_mr_pct,
            bc.calc_corr_wt,
            bc.calc_sdev,
            bc.calc_cv_pct,
            bc.cv_within_band,
            bc.updated_date_time
        FROM jute_sqc_breaker_card_swt bc
        LEFT JOIN machine_mst m ON m.machine_id = bc.mc_id
        LEFT JOIN item_mst im ON im.item_id = bc.item_id
        LEFT JOIN jute_batch_plan bp ON bp.batch_plan_id = bc.batch_plan_id
        LEFT JOIN (
            SELECT spell_id, MIN(spell_code) AS spell_code FROM spell_mst WHERE status = 1 GROUP BY spell_id
        ) sp ON sp.spell_id = bc.spell_id
        WHERE bc.co_id = :co_id
        AND bc.entry_date = :entry_date
        AND bc.active = 1
        AND (:branch_id IS NULL OR bc.branch_id = :branch_id)
        ORDER BY bp.plan_name, im.item_name, bc.breaker_card_swt_id DESC
    """
    return text(sql)


def get_breaker_card_swt_active_row_query():
    """The active breaker-card row id (for the soft-delete guard)."""
    return text(
        """
        SELECT breaker_card_swt_id
        FROM jute_sqc_breaker_card_swt
        WHERE breaker_card_swt_id = :id
          AND active = 1
        """
    )


def soft_delete_breaker_card_swt_query():
    """Soft-delete a breaker-card reading (active = 0)."""
    return text(
        """
        UPDATE jute_sqc_breaker_card_swt
        SET active = 0,
            updated_by = :updated_by
        WHERE breaker_card_swt_id = :id
        """
    )


# =============================================================================
# R-08-07A Inter Card & Tow Breaker Sliver Weight — query builders
# Clone of the breaker-card builders (table jute_sqc_card_sliver_wt, PK
# card_sliver_wt_id, card_side -> section). Quality is linked to a BATCH (jute_batch_plan),
# NOT a line quality, so the std satellite is no longer consulted at this stage (std MR fixed
# at the report default, CV band unevaluated). Master builders used:
#   * get_spreader_roll_wt_spells_query  -> spells (reused)
#   * get_card_section_machines_query    -> shared carding pool (no machine-type filter)
#   * get_card_section_batches_query     -> batch plans (jute_batch_plan, branch-scoped)
# =============================================================================


def get_card_section_machines_query():
    """Shared carding-pool machines for a branch (R-08-07A, owner decision: section is a
    label, machines are NOT filtered by a per-section machine type).

    Copied from get_breaker_card_machines_query but the machine_type_name filter is DROPPED
    — every active machine in the branch is offered and the operator picks the right one for
    the chosen section (Inter Card / Tow Breaker / Hopper). machine_type_mst is LEFT-joined
    for an optional display label only; dept_mst gives the branch scope (dept_mst.branch_id).
    """
    return text(
        """
        SELECT
            m.machine_id,
            m.machine_name,
            m.mech_code,
            mt.machine_type_name,
            d.dept_id,
            d.dept_desc AS dept_name,
            d.branch_id
        FROM machine_mst m
        LEFT JOIN machine_type_mst mt ON mt.machine_type_id = m.machine_type_id
        INNER JOIN dept_mst d ON d.dept_id = m.dept_id
        WHERE m.active = 1
          AND (:branch_id IS NULL OR d.branch_id = :branch_id)
        ORDER BY m.machine_name
        """
    )


def get_card_section_batches_query():
    """Batch plans (jute_batch_plan) for the branch — the R-08-07A quality linkage.

    Carding/drawing SQC links quality to a BATCH (a named mix of raw-jute qualities) rather
    than a single line quality. jute_batch_plan is branch-scoped (no co_id), so the picker is
    filtered by branch_id, mirroring the spell builder. line_qty = how many qualities the
    batch mixes (label hint)."""
    return text(
        """
        SELECT
            bp.batch_plan_id,
            bp.plan_name,
            bp.branch_id,
            COUNT(bpli.batch_plan_li_id) AS line_qty
        FROM jute_batch_plan bp
        LEFT JOIN jute_batch_plan_li bpli ON bpli.batch_plan_id = bp.batch_plan_id
        WHERE (:branch_id IS NULL OR bp.branch_id = :branch_id)
        GROUP BY bp.batch_plan_id, bp.plan_name, bp.branch_id
        ORDER BY bp.batch_plan_id DESC
        """
    )


def get_card_sliver_wt_by_date_query():
    """Active card-sliver rows for a co/entry_date (branch optional), labelled.

    Returns the persisted readings (weights / mr_pcts JSON) + section + calc_*/std band so the
    caller can json.loads them AND re-pool the corrected cuts for the per-section AND
    per-quality averages. Ordered by section then quality so both groupings are contiguous."""
    sql = """
        SELECT
            cs.card_sliver_wt_id,
            cs.co_id,
            cs.branch_id,
            cs.entry_date,
            cs.section,
            cs.spell_id,
            sp.spell_code,
            cs.mc_id,
            m.machine_name,
            m.mech_code,
            cs.item_id,
            im.item_name AS jute_quality,
            im.item_code,
            cs.batch_plan_id,
            bp.plan_name AS batch_plan_name,
            cs.weights,
            cs.mr_pcts,
            cs.std_mr_pct,
            cs.std_cv_low,
            cs.std_cv_high,
            cs.calc_wt,
            cs.calc_mr_pct,
            cs.calc_corr_wt,
            cs.calc_sdev,
            cs.calc_cv_pct,
            cs.cv_within_band,
            cs.updated_date_time
        FROM jute_sqc_card_sliver_wt cs
        LEFT JOIN machine_mst m ON m.machine_id = cs.mc_id
        LEFT JOIN item_mst im ON im.item_id = cs.item_id
        LEFT JOIN jute_batch_plan bp ON bp.batch_plan_id = cs.batch_plan_id
        LEFT JOIN (
            SELECT spell_id, MIN(spell_code) AS spell_code FROM spell_mst WHERE status = 1 GROUP BY spell_id
        ) sp ON sp.spell_id = cs.spell_id
        WHERE cs.co_id = :co_id
        AND cs.entry_date = :entry_date
        AND cs.active = 1
        AND (:branch_id IS NULL OR cs.branch_id = :branch_id)
        ORDER BY cs.section, bp.plan_name, im.item_name, cs.card_sliver_wt_id DESC
    """
    return text(sql)


def get_card_sliver_wt_table_query(search: str = None):
    search_filter = ""
    if search:
        search_filter = """
            AND (
                im.item_name LIKE :search
                OR bp.plan_name LIKE :search
                OR m.machine_name LIKE :search
                OR m.mech_code LIKE :search
                OR cs.section LIKE :search
            )
        """

    sql = f"""
        SELECT
            cs.card_sliver_wt_id,
            cs.co_id,
            cs.branch_id,
            cs.entry_date,
            cs.section,
            cs.spell_id,
            sp.spell_code,
            cs.mc_id,
            m.machine_name,
            m.mech_code,
            cs.item_id,
            im.item_name AS jute_quality,
            im.item_code,
            cs.batch_plan_id,
            bp.plan_name AS batch_plan_name,
            cs.std_mr_pct,
            cs.std_cv_low,
            cs.std_cv_high,
            cs.calc_wt,
            cs.calc_mr_pct,
            cs.calc_corr_wt,
            cs.calc_sdev,
            cs.calc_cv_pct,
            cs.cv_within_band,
            cs.updated_date_time
        FROM jute_sqc_card_sliver_wt cs
        LEFT JOIN machine_mst m ON m.machine_id = cs.mc_id
        LEFT JOIN item_mst im ON im.item_id = cs.item_id
        LEFT JOIN jute_batch_plan bp ON bp.batch_plan_id = cs.batch_plan_id
        LEFT JOIN (
            SELECT spell_id, MIN(spell_code) AS spell_code FROM spell_mst WHERE status = 1 GROUP BY spell_id
        ) sp ON sp.spell_id = cs.spell_id
        WHERE cs.co_id = :co_id
        AND cs.active = 1
        AND (:branch_id IS NULL OR cs.branch_id = :branch_id)
        {search_filter}
        ORDER BY cs.entry_date DESC, cs.card_sliver_wt_id DESC
        LIMIT :limit OFFSET :offset
    """
    return text(sql)


def get_card_sliver_wt_table_count_query(search: str = None):
    search_filter = ""
    if search:
        search_filter = """
            AND (
                im.item_name LIKE :search
                OR bp.plan_name LIKE :search
                OR m.machine_name LIKE :search
                OR m.mech_code LIKE :search
                OR cs.section LIKE :search
            )
        """

    sql = f"""
        SELECT COUNT(*) AS total
        FROM jute_sqc_card_sliver_wt cs
        LEFT JOIN machine_mst m ON m.machine_id = cs.mc_id
        LEFT JOIN item_mst im ON im.item_id = cs.item_id
        LEFT JOIN jute_batch_plan bp ON bp.batch_plan_id = cs.batch_plan_id
        WHERE cs.co_id = :co_id
        AND cs.active = 1
        AND (:branch_id IS NULL OR cs.branch_id = :branch_id)
        {search_filter}
    """
    return text(sql)


def get_card_sliver_wt_by_id_query():
    """One card-sliver row by id, tenant-scoped via the optional :co_id guard."""
    sql = """
        SELECT
            cs.card_sliver_wt_id,
            cs.co_id,
            cs.branch_id,
            cs.entry_date,
            cs.section,
            cs.spell_id,
            sp.spell_code,
            cs.mc_id,
            m.machine_name,
            m.mech_code,
            cs.item_id,
            im.item_name AS jute_quality,
            im.item_code,
            cs.batch_plan_id,
            bp.plan_name AS batch_plan_name,
            cs.weights,
            cs.mr_pcts,
            cs.std_mr_pct,
            cs.std_cv_low,
            cs.std_cv_high,
            cs.calc_wt,
            cs.calc_mr_pct,
            cs.calc_corr_wt,
            cs.calc_sdev,
            cs.calc_cv_pct,
            cs.cv_within_band,
            cs.updated_date_time
        FROM jute_sqc_card_sliver_wt cs
        LEFT JOIN machine_mst m ON m.machine_id = cs.mc_id
        LEFT JOIN item_mst im ON im.item_id = cs.item_id
        LEFT JOIN jute_batch_plan bp ON bp.batch_plan_id = cs.batch_plan_id
        LEFT JOIN (
            SELECT spell_id, MIN(spell_code) AS spell_code FROM spell_mst WHERE status = 1 GROUP BY spell_id
        ) sp ON sp.spell_id = cs.spell_id
        WHERE cs.card_sliver_wt_id = :card_sliver_wt_id
        AND cs.active = 1
        AND (:co_id IS NULL OR cs.co_id = :co_id)
    """
    return text(sql)


def get_card_sliver_wt_active_row_query():
    """The active card-sliver row id (for the soft-delete guard)."""
    return text(
        """
        SELECT card_sliver_wt_id
        FROM jute_sqc_card_sliver_wt
        WHERE card_sliver_wt_id = :id
          AND active = 1
        """
    )


def soft_delete_card_sliver_wt_query():
    """Soft-delete a card-sliver reading (active = 0)."""
    return text(
        """
        UPDATE jute_sqc_card_sliver_wt
        SET active = 0,
            updated_by = :updated_by
        WHERE card_sliver_wt_id = :id
        """
    )


# =============================================================================
# R-08-12/13/14 Finisher Drawing Sliver Weight — query builders
# Clone of the card-sliver builders (table jute_sqc_fin_draw_sliver_wt, PK
# fin_draw_sliver_wt_id) with ONE extra column: dlv_nos (JSON array of 4 delivery numbers).
# Sections HESS / SWP / SWT. Quality is linked to a BATCH (jute_batch_plan). Reuses the
# shared pickers get_card_section_machines_query / get_card_section_batches_query /
# get_spreader_roll_wt_spells_query — no new picker builders here.
# =============================================================================


def get_fin_draw_sliver_wt_by_date_query():
    """Active finisher-drawing rows for a co/entry_date (branch optional), labelled.

    Returns the persisted readings (weights / mr_pcts / dlv_nos JSON) + section + calc_*/std
    band so the caller can json.loads them AND re-pool the corrected cuts for the per-section
    AND per-batch averages. Ordered by section then batch so both groupings are contiguous.
    Branch-scoped strictly (no NULL-branch leak)."""
    sql = """
        SELECT
            fd.fin_draw_sliver_wt_id,
            fd.co_id,
            fd.branch_id,
            fd.entry_date,
            fd.section,
            fd.spell_id,
            sp.spell_code,
            fd.mc_id,
            m.machine_name,
            m.mech_code,
            fd.batch_plan_id,
            bp.plan_name AS batch_plan_name,
            fd.weights,
            fd.mr_pcts,
            fd.dlv_nos,
            fd.std_mr_pct,
            fd.std_cv_low,
            fd.std_cv_high,
            fd.calc_wt,
            fd.calc_mr_pct,
            fd.calc_corr_wt,
            fd.calc_sdev,
            fd.calc_cv_pct,
            fd.cv_within_band,
            fd.updated_date_time
        FROM jute_sqc_fin_draw_sliver_wt fd
        LEFT JOIN machine_mst m ON m.machine_id = fd.mc_id
        LEFT JOIN jute_batch_plan bp ON bp.batch_plan_id = fd.batch_plan_id
        LEFT JOIN (
            SELECT spell_id, MIN(spell_code) AS spell_code FROM spell_mst WHERE status = 1 GROUP BY spell_id
        ) sp ON sp.spell_id = fd.spell_id
        WHERE fd.co_id = :co_id
        AND fd.entry_date = :entry_date
        AND fd.active = 1
        AND (:branch_id IS NULL OR fd.branch_id = :branch_id)
        ORDER BY fd.section, bp.plan_name, fd.fin_draw_sliver_wt_id DESC
    """
    return text(sql)


def get_fin_draw_sliver_wt_table_query(search: str = None):
    search_filter = ""
    if search:
        search_filter = """
            AND (
                bp.plan_name LIKE :search
                OR m.machine_name LIKE :search
                OR m.mech_code LIKE :search
                OR fd.section LIKE :search
            )
        """

    sql = f"""
        SELECT
            fd.fin_draw_sliver_wt_id,
            fd.co_id,
            fd.branch_id,
            fd.entry_date,
            fd.section,
            fd.spell_id,
            sp.spell_code,
            fd.mc_id,
            m.machine_name,
            m.mech_code,
            fd.batch_plan_id,
            bp.plan_name AS batch_plan_name,
            fd.std_mr_pct,
            fd.std_cv_low,
            fd.std_cv_high,
            fd.calc_wt,
            fd.calc_mr_pct,
            fd.calc_corr_wt,
            fd.calc_sdev,
            fd.calc_cv_pct,
            fd.cv_within_band,
            fd.updated_date_time
        FROM jute_sqc_fin_draw_sliver_wt fd
        LEFT JOIN machine_mst m ON m.machine_id = fd.mc_id
        LEFT JOIN jute_batch_plan bp ON bp.batch_plan_id = fd.batch_plan_id
        LEFT JOIN (
            SELECT spell_id, MIN(spell_code) AS spell_code FROM spell_mst WHERE status = 1 GROUP BY spell_id
        ) sp ON sp.spell_id = fd.spell_id
        WHERE fd.co_id = :co_id
        AND fd.active = 1
        AND (:branch_id IS NULL OR fd.branch_id = :branch_id)
        {search_filter}
        ORDER BY fd.entry_date DESC, fd.fin_draw_sliver_wt_id DESC
        LIMIT :limit OFFSET :offset
    """
    return text(sql)


def get_fin_draw_sliver_wt_table_count_query(search: str = None):
    search_filter = ""
    if search:
        search_filter = """
            AND (
                bp.plan_name LIKE :search
                OR m.machine_name LIKE :search
                OR m.mech_code LIKE :search
                OR fd.section LIKE :search
            )
        """

    sql = f"""
        SELECT COUNT(*) AS total
        FROM jute_sqc_fin_draw_sliver_wt fd
        LEFT JOIN machine_mst m ON m.machine_id = fd.mc_id
        LEFT JOIN jute_batch_plan bp ON bp.batch_plan_id = fd.batch_plan_id
        WHERE fd.co_id = :co_id
        AND fd.active = 1
        AND (:branch_id IS NULL OR fd.branch_id = :branch_id)
        {search_filter}
    """
    return text(sql)


def get_fin_draw_sliver_wt_by_id_query():
    """One finisher-drawing row by id, tenant-scoped via the optional :co_id guard."""
    sql = """
        SELECT
            fd.fin_draw_sliver_wt_id,
            fd.co_id,
            fd.branch_id,
            fd.entry_date,
            fd.section,
            fd.spell_id,
            sp.spell_code,
            fd.mc_id,
            m.machine_name,
            m.mech_code,
            fd.batch_plan_id,
            bp.plan_name AS batch_plan_name,
            fd.weights,
            fd.mr_pcts,
            fd.dlv_nos,
            fd.std_mr_pct,
            fd.std_cv_low,
            fd.std_cv_high,
            fd.calc_wt,
            fd.calc_mr_pct,
            fd.calc_corr_wt,
            fd.calc_sdev,
            fd.calc_cv_pct,
            fd.cv_within_band,
            fd.updated_date_time
        FROM jute_sqc_fin_draw_sliver_wt fd
        LEFT JOIN machine_mst m ON m.machine_id = fd.mc_id
        LEFT JOIN jute_batch_plan bp ON bp.batch_plan_id = fd.batch_plan_id
        LEFT JOIN (
            SELECT spell_id, MIN(spell_code) AS spell_code FROM spell_mst WHERE status = 1 GROUP BY spell_id
        ) sp ON sp.spell_id = fd.spell_id
        WHERE fd.fin_draw_sliver_wt_id = :fin_draw_sliver_wt_id
        AND fd.active = 1
        AND (:co_id IS NULL OR fd.co_id = :co_id)
    """
    return text(sql)


def get_fin_draw_sliver_wt_active_row_query():
    """The active finisher-drawing row id (for the soft-delete guard)."""
    return text(
        """
        SELECT fin_draw_sliver_wt_id
        FROM jute_sqc_fin_draw_sliver_wt
        WHERE fin_draw_sliver_wt_id = :id
          AND active = 1
        """
    )


def soft_delete_fin_draw_sliver_wt_query():
    """Soft-delete a finisher-drawing reading (active = 0)."""
    return text(
        """
        UPDATE jute_sqc_fin_draw_sliver_wt
        SET active = 0,
            updated_by = :updated_by
        WHERE fin_draw_sliver_wt_id = :id
        """
    )


# =============================================================================
# R-08-08/09/10 Drawhead + Finisher Card Sliver Weight — query builders
# Clone of the card-sliver builders (table jute_sqc_draw_sliver_wt, PK draw_sliver_wt_id)
# with ONE extra column: time_band (MORNING / AFTERNOON sheet header). Sections
# DRAWHEAD_SWT / DRAWHEAD_SWP / FINISHER_CARD. Quality is linked to a BATCH (jute_batch_plan).
# Reuses the shared pickers (machines / batches / spells) — no new picker builders here.
# =============================================================================


def get_draw_sliver_wt_by_date_query():
    """Active drawhead/finisher-card rows for a co/entry_date (branch optional), labelled.

    Returns the persisted readings (weights / mr_pcts JSON) + section + time_band + calc_*/std
    band so the caller can json.loads them AND re-pool the corrected cuts for the per-section
    AND per-batch averages. Ordered by section then batch so both groupings are contiguous.
    Branch-scoped strictly (no NULL-branch leak)."""
    sql = """
        SELECT
            dw.draw_sliver_wt_id,
            dw.co_id,
            dw.branch_id,
            dw.entry_date,
            dw.section,
            dw.time_band,
            dw.spell_id,
            sp.spell_code,
            dw.mc_id,
            m.machine_name,
            m.mech_code,
            dw.batch_plan_id,
            bp.plan_name AS batch_plan_name,
            dw.weights,
            dw.mr_pcts,
            dw.std_mr_pct,
            dw.std_cv_low,
            dw.std_cv_high,
            dw.calc_wt,
            dw.calc_mr_pct,
            dw.calc_corr_wt,
            dw.calc_sdev,
            dw.calc_cv_pct,
            dw.cv_within_band,
            dw.updated_date_time
        FROM jute_sqc_draw_sliver_wt dw
        LEFT JOIN machine_mst m ON m.machine_id = dw.mc_id
        LEFT JOIN jute_batch_plan bp ON bp.batch_plan_id = dw.batch_plan_id
        LEFT JOIN (
            SELECT spell_id, MIN(spell_code) AS spell_code FROM spell_mst WHERE status = 1 GROUP BY spell_id
        ) sp ON sp.spell_id = dw.spell_id
        WHERE dw.co_id = :co_id
        AND dw.entry_date = :entry_date
        AND dw.active = 1
        AND (:branch_id IS NULL OR dw.branch_id = :branch_id)
        ORDER BY dw.section, bp.plan_name, dw.draw_sliver_wt_id DESC
    """
    return text(sql)


def get_draw_sliver_wt_table_query(search: str = None):
    search_filter = ""
    if search:
        search_filter = """
            AND (
                bp.plan_name LIKE :search
                OR m.machine_name LIKE :search
                OR m.mech_code LIKE :search
                OR dw.section LIKE :search
            )
        """

    sql = f"""
        SELECT
            dw.draw_sliver_wt_id,
            dw.co_id,
            dw.branch_id,
            dw.entry_date,
            dw.section,
            dw.time_band,
            dw.spell_id,
            sp.spell_code,
            dw.mc_id,
            m.machine_name,
            m.mech_code,
            dw.batch_plan_id,
            bp.plan_name AS batch_plan_name,
            dw.std_mr_pct,
            dw.std_cv_low,
            dw.std_cv_high,
            dw.calc_wt,
            dw.calc_mr_pct,
            dw.calc_corr_wt,
            dw.calc_sdev,
            dw.calc_cv_pct,
            dw.cv_within_band,
            dw.updated_date_time
        FROM jute_sqc_draw_sliver_wt dw
        LEFT JOIN machine_mst m ON m.machine_id = dw.mc_id
        LEFT JOIN jute_batch_plan bp ON bp.batch_plan_id = dw.batch_plan_id
        LEFT JOIN (
            SELECT spell_id, MIN(spell_code) AS spell_code FROM spell_mst WHERE status = 1 GROUP BY spell_id
        ) sp ON sp.spell_id = dw.spell_id
        WHERE dw.co_id = :co_id
        AND dw.active = 1
        AND (:branch_id IS NULL OR dw.branch_id = :branch_id)
        {search_filter}
        ORDER BY dw.entry_date DESC, dw.draw_sliver_wt_id DESC
        LIMIT :limit OFFSET :offset
    """
    return text(sql)


def get_draw_sliver_wt_table_count_query(search: str = None):
    search_filter = ""
    if search:
        search_filter = """
            AND (
                bp.plan_name LIKE :search
                OR m.machine_name LIKE :search
                OR m.mech_code LIKE :search
                OR dw.section LIKE :search
            )
        """

    sql = f"""
        SELECT COUNT(*) AS total
        FROM jute_sqc_draw_sliver_wt dw
        LEFT JOIN machine_mst m ON m.machine_id = dw.mc_id
        LEFT JOIN jute_batch_plan bp ON bp.batch_plan_id = dw.batch_plan_id
        WHERE dw.co_id = :co_id
        AND dw.active = 1
        AND (:branch_id IS NULL OR dw.branch_id = :branch_id)
        {search_filter}
    """
    return text(sql)


def get_draw_sliver_wt_by_id_query():
    """One drawhead/finisher-card row by id, tenant-scoped via the optional :co_id guard."""
    sql = """
        SELECT
            dw.draw_sliver_wt_id,
            dw.co_id,
            dw.branch_id,
            dw.entry_date,
            dw.section,
            dw.time_band,
            dw.spell_id,
            sp.spell_code,
            dw.mc_id,
            m.machine_name,
            m.mech_code,
            dw.batch_plan_id,
            bp.plan_name AS batch_plan_name,
            dw.weights,
            dw.mr_pcts,
            dw.std_mr_pct,
            dw.std_cv_low,
            dw.std_cv_high,
            dw.calc_wt,
            dw.calc_mr_pct,
            dw.calc_corr_wt,
            dw.calc_sdev,
            dw.calc_cv_pct,
            dw.cv_within_band,
            dw.updated_date_time
        FROM jute_sqc_draw_sliver_wt dw
        LEFT JOIN machine_mst m ON m.machine_id = dw.mc_id
        LEFT JOIN jute_batch_plan bp ON bp.batch_plan_id = dw.batch_plan_id
        LEFT JOIN (
            SELECT spell_id, MIN(spell_code) AS spell_code FROM spell_mst WHERE status = 1 GROUP BY spell_id
        ) sp ON sp.spell_id = dw.spell_id
        WHERE dw.draw_sliver_wt_id = :draw_sliver_wt_id
        AND dw.active = 1
        AND (:co_id IS NULL OR dw.co_id = :co_id)
    """
    return text(sql)


def get_draw_sliver_wt_active_row_query():
    """The active drawhead/finisher-card row id (for the soft-delete guard)."""
    return text(
        """
        SELECT draw_sliver_wt_id
        FROM jute_sqc_draw_sliver_wt
        WHERE draw_sliver_wt_id = :id
          AND active = 1
        """
    )


def soft_delete_draw_sliver_wt_query():
    """Soft-delete a drawhead/finisher-card reading (active = 0)."""
    return text(
        """
        UPDATE jute_sqc_draw_sliver_wt
        SET active = 0,
            updated_by = :updated_by
        WHERE draw_sliver_wt_id = :id
        """
    )


# =============================================================================
# R-08-18 BEAM MR% QC (jute_sqc_beam_mr)
# Morrah-shaped: paginated table + count + by-date grouping + by-id.
# =============================================================================


def get_beam_mr_table_query(search: str = None):
    """Paginated active beam-MR rows for a company, newest first (morrah table clone)."""
    search_filter = ""
    if search:
        search_filter = """
            AND (
                bm.quality_group LIKE :search
                OR im.item_name LIKE :search
                OR m.machine_name LIKE :search
                OR m.mech_code LIKE :search
            )
        """

    sql = f"""
        SELECT
            bm.beam_mr_id,
            bm.entry_date,
            bm.quality_group,
            bm.spell_id,
            sp.spell_code,
            bm.mc_id,
            m.machine_name,
            m.mech_code,
            bm.item_id,
            im.item_name,
            bm.calc_avg_mr,
            bm.std_mr_pct,
            bm.branch_id,
            bm.updated_date_time
        FROM jute_sqc_beam_mr bm
        LEFT JOIN machine_mst m ON m.machine_id = bm.mc_id
        LEFT JOIN item_mst im ON im.item_id = bm.item_id
        LEFT JOIN (
            SELECT spell_id, spell_code FROM spell_mst WHERE status = 1
        ) sp ON sp.spell_id = bm.spell_id
        WHERE bm.co_id = :co_id
        AND bm.active = 1
        {search_filter}
        ORDER BY bm.entry_date DESC, bm.beam_mr_id DESC
        LIMIT :limit OFFSET :offset
    """
    return text(sql)


def get_beam_mr_table_count_query(search: str = None):
    """Row count for the paginated beam-MR table (same filters as the data query)."""
    search_filter = ""
    if search:
        search_filter = """
            AND (
                bm.quality_group LIKE :search
                OR im.item_name LIKE :search
                OR m.machine_name LIKE :search
                OR m.mech_code LIKE :search
            )
        """

    sql = f"""
        SELECT COUNT(*) AS total
        FROM jute_sqc_beam_mr bm
        LEFT JOIN machine_mst m ON m.machine_id = bm.mc_id
        LEFT JOIN item_mst im ON im.item_id = bm.item_id
        WHERE bm.co_id = :co_id
        AND bm.active = 1
        {search_filter}
    """
    return text(sql)


def get_beam_mr_by_date_query():
    """Active beam-MR reading-sets for one (co_id, branch_id, entry_date), with labels.

    Joins machine/item/spell for readable columns. spell join is pre-aggregated (MIN
    spell_id per code) so a duplicate spell_code under another branch's shift can't fan
    out the result (mirrors get_beaming_entries_by_date_query). Branch filter is
    NULL-tolerant. Per-machine avg/deviation and per-group overall_avg are computed in
    Python from calc_avg_mr / std_mr_pct.
    """
    return text(
        """
        SELECT
            bm.beam_mr_id,
            bm.quality_group,
            bm.mc_id,
            m.machine_name,
            m.mech_code,
            bm.item_id,
            im.item_name,
            bm.spell_id,
            sp.spell_code,
            bm.readings,
            bm.calc_avg_mr,
            bm.std_mr_pct
        FROM jute_sqc_beam_mr bm
        LEFT JOIN machine_mst m ON m.machine_id = bm.mc_id
        LEFT JOIN item_mst im ON im.item_id = bm.item_id
        LEFT JOIN (
            SELECT spell_code, MIN(spell_id) AS spell_id
            FROM spell_mst WHERE status = 1 GROUP BY spell_code
        ) sp ON sp.spell_id = bm.spell_id
        WHERE bm.co_id = :co_id
        AND bm.active = 1
        AND bm.entry_date = :entry_date
        AND (:branch_id IS NULL OR bm.branch_id = :branch_id OR bm.branch_id IS NULL)
        ORDER BY bm.quality_group, m.mech_code, bm.beam_mr_id
        """
    )


def get_beam_mr_by_id_query():
    """A single active beam-MR row by id + co_id (delete existence check, co_id-scoped)."""
    return text(
        """
        SELECT beam_mr_id, co_id, branch_id, entry_date, quality_group,
               spell_id, item_id, mc_id, readings, calc_avg_mr, std_mr_pct, active
        FROM jute_sqc_beam_mr
        WHERE beam_mr_id = :beam_mr_id
          AND co_id = :co_id
          AND active = 1
        """
    )


def soft_delete_beam_mr_query():
    """Soft-delete (active = 0) one beam-MR row by id + co_id (co_id-scoped)."""
    return text(
        """
        UPDATE jute_sqc_beam_mr
        SET active = 0,
            updated_by = :updated_by,
            updated_date_time = CURRENT_TIMESTAMP
        WHERE beam_mr_id = :beam_mr_id
          AND co_id = :co_id
        """
    )


# =============================================================================
# R-08-19 Fabric Construction (jute_sqc_fabric_construction + _dtl) builders
# =============================================================================
# Header carries the cloth quality + 6 snapshotted std values; _dtl carries up to 5
# sample rows (6 measured inputs + obs_ozs/crcted_oz computed at save). by_date loads
# active headers then their detail rows; per-column avg + Std-vs-Actual deviation are
# computed in Python. Mirrors the beam_mr table/count/by_date/by_id/delete builders.


def get_fabric_construction_table_query(search: str = None):
    """Paginated active fabric-construction headers for a company, newest first."""
    search_filter = ""
    if search:
        search_filter = """
            AND (
                im.item_name LIKE :search
                OR im.item_code LIKE :search
                OR fc.quality_text LIKE :search
            )
        """

    sql = f"""
        SELECT
            fc.fabric_const_id,
            fc.entry_date,
            fc.branch_id,
            fc.item_id,
            im.item_code,
            im.item_name,
            fc.quality_text,
            fc.std_length_yds,
            fc.std_width_cms,
            fc.std_ends_dm,
            fc.std_picks_dm,
            fc.std_mr_pct,
            fc.std_oz_per_yd,
            fc.updated_date_time,
            (SELECT COUNT(*) FROM jute_sqc_fabric_construction_dtl d
                WHERE d.fabric_const_id = fc.fabric_const_id) AS sample_count
        FROM jute_sqc_fabric_construction fc
        LEFT JOIN item_mst im ON im.item_id = fc.item_id
        WHERE fc.co_id = :co_id
          AND fc.active = 1
          {search_filter}
        ORDER BY fc.entry_date DESC, fc.fabric_const_id DESC
        LIMIT :limit OFFSET :offset
    """
    return text(sql)


def get_fabric_construction_table_count_query(search: str = None):
    """Row count for the paginated fabric-construction table (same filters as data query)."""
    search_filter = ""
    if search:
        search_filter = """
            AND (
                im.item_name LIKE :search
                OR im.item_code LIKE :search
                OR fc.quality_text LIKE :search
            )
        """

    sql = f"""
        SELECT COUNT(*) AS total
        FROM jute_sqc_fabric_construction fc
        LEFT JOIN item_mst im ON im.item_id = fc.item_id
        WHERE fc.co_id = :co_id
          AND fc.active = 1
          {search_filter}
    """
    return text(sql)


def get_fabric_construction_by_date_query():
    """Active fabric-construction headers for one (co_id, branch_id, entry_date), labelled.

    Branch filter is NULL-tolerant. Sample rows are loaded per header via
    get_fabric_construction_dtl_query; the averages + Std-vs-Actual deviation are
    computed in Python.
    """
    return text(
        """
        SELECT
            fc.fabric_const_id,
            fc.entry_date,
            fc.branch_id,
            fc.item_id,
            im.item_code,
            im.item_name,
            fc.quality_text,
            fc.std_length_yds,
            fc.std_width_cms,
            fc.std_ends_dm,
            fc.std_picks_dm,
            fc.std_mr_pct,
            fc.std_oz_per_yd
        FROM jute_sqc_fabric_construction fc
        LEFT JOIN item_mst im ON im.item_id = fc.item_id
        WHERE fc.co_id = :co_id
          AND fc.active = 1
          AND fc.entry_date = :entry_date
          AND (:branch_id IS NULL OR fc.branch_id = :branch_id OR fc.branch_id IS NULL)
        ORDER BY im.item_name, fc.fabric_const_id
        """
    )


def get_fabric_construction_by_id_query():
    """A single active fabric-construction header by id + co_id (delete existence check)."""
    return text(
        """
        SELECT fabric_const_id, co_id, branch_id, entry_date, item_id, active
        FROM jute_sqc_fabric_construction
        WHERE fabric_const_id = :fabric_const_id
          AND co_id = :co_id
          AND active = 1
        """
    )


def get_fabric_construction_dtl_query():
    """Sample rows for one fabric-construction header (ordered by sl)."""
    return text(
        """
        SELECT
            fabric_const_dtl_id,
            fabric_const_id,
            sl,
            length_yds,
            width_cms,
            ends_per_dm,
            picks_per_dm,
            mr_pct,
            obs_wt_kg,
            obs_ozs,
            crcted_oz
        FROM jute_sqc_fabric_construction_dtl
        WHERE fabric_const_id = :fabric_const_id
        ORDER BY sl
        """
    )


def soft_delete_fabric_construction_query():
    """Soft-delete (active = 0) one fabric-construction header by id + co_id (co_id-scoped)."""
    return text(
        """
        UPDATE jute_sqc_fabric_construction
        SET active = 0,
            updated_by = :updated_by,
            updated_date_time = CURRENT_TIMESTAMP
        WHERE fabric_const_id = :fabric_const_id
          AND co_id = :co_id
        """
    )


# =============================================================================
# R-08-20 Cutting Length QC (jute_sqc_cutting_length)
# Flat single-table morrah clone: paginated table + count + by-date + by-id + delete.
# Stats (avg / sample stdev / cv_pct / deviation) are computed at save and stored,
# so the read queries just project the stored columns (no Python re-pooling).
# =============================================================================


def get_cutting_length_table_query(search: str = None):
    """Paginated active cutting-length rows for a company, newest first (history = trend)."""
    search_filter = ""
    if search:
        search_filter = """
            AND (
                im.item_name LIKE :search
                OR im.item_code LIKE :search
            )
        """

    sql = f"""
        SELECT
            cl.cutting_length_id,
            cl.entry_date,
            cl.branch_id,
            cl.item_id,
            im.item_name,
            im.item_code,
            cl.std_length,
            cl.calc_avg AS avg,
            cl.calc_stdev AS stdev,
            cl.calc_cv_pct AS cv_pct,
            cl.calc_deviation AS deviation,
            cl.updated_date_time
        FROM jute_sqc_cutting_length cl
        LEFT JOIN item_mst im ON im.item_id = cl.item_id
        WHERE cl.co_id = :co_id
          AND cl.active = 1
          AND (:branch_id IS NULL OR cl.branch_id = :branch_id)
          {search_filter}
        ORDER BY cl.entry_date DESC, cl.cutting_length_id DESC
        LIMIT :limit OFFSET :offset
    """
    return text(sql)


def get_cutting_length_table_count_query(search: str = None):
    """Row count for the paginated cutting-length table (same filters as data query)."""
    search_filter = ""
    if search:
        search_filter = """
            AND (
                im.item_name LIKE :search
                OR im.item_code LIKE :search
            )
        """

    sql = f"""
        SELECT COUNT(*) AS total
        FROM jute_sqc_cutting_length cl
        LEFT JOIN item_mst im ON im.item_id = cl.item_id
        WHERE cl.co_id = :co_id
          AND cl.active = 1
          AND (:branch_id IS NULL OR cl.branch_id = :branch_id)
          {search_filter}
    """
    return text(sql)


def get_cutting_length_by_date_query():
    """Active cutting-length reading-sets for one (co_id, branch_id, entry_date), labelled.

    Branch filter is NULL-tolerant. readings (JSON) + stored stats project straight through;
    the caller json.loads readings for the grid. Stats are stored, NOT recomputed on read.
    """
    return text(
        """
        SELECT
            cl.cutting_length_id,
            cl.item_id,
            im.item_name,
            im.item_code,
            cl.std_length,
            cl.readings,
            cl.calc_avg AS avg,
            cl.calc_stdev AS stdev,
            cl.calc_cv_pct AS cv_pct,
            cl.calc_deviation AS deviation
        FROM jute_sqc_cutting_length cl
        LEFT JOIN item_mst im ON im.item_id = cl.item_id
        WHERE cl.co_id = :co_id
          AND cl.active = 1
          AND cl.entry_date = :entry_date
          AND (:branch_id IS NULL OR cl.branch_id = :branch_id OR cl.branch_id IS NULL)
        ORDER BY cl.cutting_length_id
        """
    )


def get_cutting_length_by_id_query():
    """A single active cutting-length row by id + co_id (delete existence check, co_id-scoped)."""
    return text(
        """
        SELECT cutting_length_id, co_id, branch_id, entry_date, item_id,
               std_length, readings, active
        FROM jute_sqc_cutting_length
        WHERE cutting_length_id = :cutting_length_id
          AND co_id = :co_id
          AND active = 1
        """
    )


def soft_delete_cutting_length_query():
    """Soft-delete (active = 0) one cutting-length row by id + co_id (co_id-scoped)."""
    return text(
        """
        UPDATE jute_sqc_cutting_length
        SET active = 0,
            updated_by = :updated_by,
            updated_date_time = CURRENT_TIMESTAMP
        WHERE cutting_length_id = :cutting_length_id
          AND co_id = :co_id
        """
    )


# =============================================================================
# R-08-21 Width and Picks QC (jute_sqc_width_picks + _dtl) builders
# =============================================================================
# Header carries the cloth quality + std_width_cm/std_picks snapshotted; _dtl carries N
# loom reading rows (width_cm required, picks_dm optional). by_date loads active headers
# then their detail rows; the Width remark (two-sided +/-0.5% band) and Picks summary
# (avg / SAMPLE stdev / max / min / count over non-null picks_dm) are computed in Python.
# Mirrors the fabric_construction table/count/by_date/by_id/dtl/delete builders.


def get_width_picks_table_query(search: str = None):
    """Paginated active width-and-picks headers for a company, newest first."""
    search_filter = ""
    if search:
        search_filter = """
            AND (
                im.item_name LIKE :search
                OR im.item_code LIKE :search
                OR wp.inspector_name LIKE :search
            )
        """

    sql = f"""
        SELECT
            wp.width_picks_id,
            wp.entry_date,
            wp.branch_id,
            wp.item_id,
            im.item_code,
            im.item_name,
            wp.std_width_cm,
            wp.std_picks,
            wp.inspector_name,
            wp.updated_date_time,
            (SELECT COUNT(*) FROM jute_sqc_width_picks_dtl d
                WHERE d.width_picks_id = wp.width_picks_id) AS loom_count
        FROM jute_sqc_width_picks wp
        LEFT JOIN item_mst im ON im.item_id = wp.item_id
        WHERE wp.co_id = :co_id
          AND wp.active = 1
          {search_filter}
        ORDER BY wp.entry_date DESC, wp.width_picks_id DESC
        LIMIT :limit OFFSET :offset
    """
    return text(sql)


def get_width_picks_table_count_query(search: str = None):
    """Row count for the paginated width-and-picks table (same filters as data query)."""
    search_filter = ""
    if search:
        search_filter = """
            AND (
                im.item_name LIKE :search
                OR im.item_code LIKE :search
                OR wp.inspector_name LIKE :search
            )
        """

    sql = f"""
        SELECT COUNT(*) AS total
        FROM jute_sqc_width_picks wp
        LEFT JOIN item_mst im ON im.item_id = wp.item_id
        WHERE wp.co_id = :co_id
          AND wp.active = 1
          {search_filter}
    """
    return text(sql)


def get_width_picks_by_date_query():
    """Active width-and-picks headers for one (co_id, branch_id, entry_date), labelled.

    Branch filter is NULL-tolerant. Loom rows are loaded per header via
    get_width_picks_dtl_query; the Width remark + Picks summary are computed in Python.
    """
    return text(
        """
        SELECT
            wp.width_picks_id,
            wp.entry_date,
            wp.branch_id,
            wp.item_id,
            im.item_code,
            im.item_name,
            wp.std_width_cm,
            wp.std_picks,
            wp.inspector_name
        FROM jute_sqc_width_picks wp
        LEFT JOIN item_mst im ON im.item_id = wp.item_id
        WHERE wp.co_id = :co_id
          AND wp.active = 1
          AND wp.entry_date = :entry_date
          AND (:branch_id IS NULL OR wp.branch_id = :branch_id OR wp.branch_id IS NULL)
        ORDER BY im.item_name, wp.width_picks_id
        """
    )


def get_width_picks_by_id_query():
    """A single active width-and-picks header by id + co_id (delete existence check)."""
    return text(
        """
        SELECT width_picks_id, co_id, branch_id, entry_date, item_id, active
        FROM jute_sqc_width_picks
        WHERE width_picks_id = :width_picks_id
          AND co_id = :co_id
          AND active = 1
        """
    )


def get_width_picks_dtl_query():
    """Loom reading rows for one width-and-picks header, labelled with loom name/code."""
    return text(
        """
        SELECT
            d.width_picks_dtl_id,
            d.width_picks_id,
            d.loom_id,
            m.machine_name AS loom_name,
            m.mech_code,
            d.width_cm,
            d.picks_dm
        FROM jute_sqc_width_picks_dtl d
        LEFT JOIN machine_mst m ON m.machine_id = d.loom_id
        WHERE d.width_picks_id = :width_picks_id
        ORDER BY d.width_picks_dtl_id
        """
    )


def soft_delete_width_picks_query():
    """Soft-delete (active = 0) one width-and-picks header by id + co_id (co_id-scoped)."""
    return text(
        """
        UPDATE jute_sqc_width_picks
        SET active = 0,
            updated_by = :updated_by,
            updated_date_time = CURRENT_TIMESTAMP
        WHERE width_picks_id = :width_picks_id
          AND co_id = :co_id
        """
    )


# =============================================================================
# R-08-22 Stitch SQC (jute_sqc_stitch) builders
# =============================================================================
def get_stitch_machines_query():
    """Sewing/stitch machines for a branch (machine_type resolved by name).

    Cloned from get_breaker_card_machines_query: same machine_mst -> machine_type_mst ->
    dept_mst walk, branch-scoped via dept_mst.branch_id. The machine type is bound at call
    time via :stitch_type (STITCH_MACHINE_TYPE_NAME = 'HEMMING' in dev3 — the bag-sewing
    operation) instead of the breaker type. The router de-dups by machine_id (dev3 may
    carry duplicate machine rows)."""
    return text(
        """
        SELECT
            m.machine_id,
            m.machine_name,
            m.mech_code,
            d.dept_id,
            d.dept_desc AS dept_name,
            d.branch_id
        FROM machine_mst m
        INNER JOIN machine_type_mst mt ON mt.machine_type_id = m.machine_type_id
        INNER JOIN dept_mst d ON d.dept_id = m.dept_id
        WHERE m.active = 1
          AND mt.active = 1
          AND mt.machine_type_name = :stitch_type
          AND (:branch_id IS NULL OR d.branch_id = :branch_id)
        ORDER BY m.machine_name
        """
    )


def get_stitch_table_query(search: str = None):
    """Paginated active stitch rows for a company, newest first (beam_mr table clone)."""
    search_filter = ""
    if search:
        search_filter = """
            AND (
                m.machine_name LIKE :search
                OR m.mech_code LIKE :search
                OR st.inspector_name LIKE :search
            )
        """

    sql = f"""
        SELECT
            st.stitch_id,
            st.entry_date,
            st.mc_id,
            m.machine_name,
            m.mech_code,
            st.std_stitch,
            st.calc_avg,
            st.inspector_name,
            st.branch_id,
            st.updated_date_time
        FROM jute_sqc_stitch st
        LEFT JOIN machine_mst m ON m.machine_id = st.mc_id
        WHERE st.co_id = :co_id
        AND st.active = 1
        {search_filter}
        ORDER BY st.entry_date DESC, st.stitch_id DESC
        LIMIT :limit OFFSET :offset
    """
    return text(sql)


def get_stitch_table_count_query(search: str = None):
    """Row count for the paginated stitch table (same filters as the data query)."""
    search_filter = ""
    if search:
        search_filter = """
            AND (
                m.machine_name LIKE :search
                OR m.mech_code LIKE :search
                OR st.inspector_name LIKE :search
            )
        """

    sql = f"""
        SELECT COUNT(*) AS total
        FROM jute_sqc_stitch st
        LEFT JOIN machine_mst m ON m.machine_id = st.mc_id
        WHERE st.co_id = :co_id
        AND st.active = 1
        {search_filter}
    """
    return text(sql)


def get_stitch_by_date_query():
    """Active stitch reading-sets for one (co_id, branch_id, entry_date), with machine
    labels. Branch filter is NULL-tolerant. avg/flag computed in Python from calc_avg /
    std_stitch (round(avg)==round(std) -> OK, avg<std -> LOW, else HIGH)."""
    return text(
        """
        SELECT
            st.stitch_id,
            st.mc_id,
            m.machine_name,
            m.mech_code,
            st.std_stitch,
            st.readings,
            st.calc_avg,
            st.inspector_name
        FROM jute_sqc_stitch st
        LEFT JOIN machine_mst m ON m.machine_id = st.mc_id
        WHERE st.co_id = :co_id
        AND st.active = 1
        AND st.entry_date = :entry_date
        AND (:branch_id IS NULL OR st.branch_id = :branch_id OR st.branch_id IS NULL)
        ORDER BY m.mech_code, st.stitch_id
        """
    )


def get_stitch_by_id_query():
    """A single active stitch row by id + co_id (delete existence check, co_id-scoped)."""
    return text(
        """
        SELECT stitch_id, co_id, branch_id, entry_date, mc_id, std_stitch,
               readings, calc_avg, inspector_name, active
        FROM jute_sqc_stitch
        WHERE stitch_id = :stitch_id
          AND co_id = :co_id
          AND active = 1
        """
    )


def soft_delete_stitch_query():
    """Soft-delete (active = 0) one stitch row by id + co_id (co_id-scoped)."""
    return text(
        """
        UPDATE jute_sqc_stitch
        SET active = 0,
            updated_by = :updated_by,
            updated_date_time = CURRENT_TIMESTAMP
        WHERE stitch_id = :stitch_id
          AND co_id = :co_id
        """
    )


# =============================================================================
# R-08-23 Bag Weight QC (jute_sqc_bag_weight)
# Flat single-table morrah clone: paginated table + count + by-date + by-id + delete.
# Per-row corr + block stats are computed at save and stored in calc_* columns, so the
# read queries just project the stored columns (no Python re-pooling on read).
# =============================================================================


def get_bag_weight_table_query(search: str = None):
    """Paginated active bag-weight blocks for a company, newest first (history = trend)."""
    search_filter = ""
    if search:
        search_filter = """
            AND (
                im.item_name LIKE :search
                OR im.item_code LIKE :search
                OR bw.bag_type_label LIKE :search
            )
        """

    sql = f"""
        SELECT
            bw.bag_weight_id,
            bw.entry_date,
            bw.branch_id,
            bw.item_id,
            im.item_name,
            im.item_code,
            bw.bag_type_label,
            bw.std_bag_weight,
            bw.std_mr_pct,
            bw.calc_avg_mr AS avg_mr,
            bw.calc_avg_obs_wt AS avg_obs,
            bw.calc_avg_corr_wt AS avg_corr,
            bw.calc_obs_stdev AS obs_stdev,
            bw.calc_obs_cv_pct AS obs_cv_pct,
            bw.calc_obs_hy_lt_pct AS obs_hy_lt_pct,
            bw.calc_corr_hy_lt_pct AS corr_hy_lt_pct,
            bw.updated_date_time
        FROM jute_sqc_bag_weight bw
        LEFT JOIN item_mst im ON im.item_id = bw.item_id
        WHERE bw.co_id = :co_id
          AND bw.active = 1
          AND (:branch_id IS NULL OR bw.branch_id = :branch_id)
          {search_filter}
        ORDER BY bw.entry_date DESC, bw.bag_weight_id DESC
        LIMIT :limit OFFSET :offset
    """
    return text(sql)


def get_bag_weight_table_count_query(search: str = None):
    """Row count for the paginated bag-weight table (same filters as data query)."""
    search_filter = ""
    if search:
        search_filter = """
            AND (
                im.item_name LIKE :search
                OR im.item_code LIKE :search
                OR bw.bag_type_label LIKE :search
            )
        """

    sql = f"""
        SELECT COUNT(*) AS total
        FROM jute_sqc_bag_weight bw
        LEFT JOIN item_mst im ON im.item_id = bw.item_id
        WHERE bw.co_id = :co_id
          AND bw.active = 1
          AND (:branch_id IS NULL OR bw.branch_id = :branch_id)
          {search_filter}
    """
    return text(sql)


def get_bag_weight_by_date_query():
    """Active bag-weight blocks for one (co_id, branch_id, entry_date), labelled.

    Branch filter is NULL-tolerant. readings (JSON of {mr, obs}) + stored stats project
    straight through; the caller json.loads readings and adds per-row corr for the grid.
    Block stats are stored, NOT recomputed on read.
    """
    return text(
        """
        SELECT
            bw.bag_weight_id,
            bw.item_id,
            im.item_name,
            im.item_code,
            bw.bag_type_label,
            bw.std_bag_weight,
            bw.std_mr_pct,
            bw.readings,
            bw.calc_avg_mr AS avg_mr,
            bw.calc_avg_obs_wt AS avg_obs,
            bw.calc_avg_corr_wt AS avg_corr,
            bw.calc_obs_stdev AS obs_stdev,
            bw.calc_obs_cv_pct AS obs_cv_pct,
            bw.calc_obs_hy_lt_pct AS obs_hy_lt_pct,
            bw.calc_corr_hy_lt_pct AS corr_hy_lt_pct
        FROM jute_sqc_bag_weight bw
        LEFT JOIN item_mst im ON im.item_id = bw.item_id
        WHERE bw.co_id = :co_id
          AND bw.active = 1
          AND bw.entry_date = :entry_date
          AND (:branch_id IS NULL OR bw.branch_id = :branch_id OR bw.branch_id IS NULL)
        ORDER BY bw.bag_weight_id
        """
    )


def get_bag_weight_by_id_query():
    """A single active bag-weight row by id + co_id (delete existence check, co_id-scoped)."""
    return text(
        """
        SELECT bag_weight_id, co_id, branch_id, entry_date, item_id,
               bag_type_label, std_bag_weight, std_mr_pct, readings, active
        FROM jute_sqc_bag_weight
        WHERE bag_weight_id = :bag_weight_id
          AND co_id = :co_id
          AND active = 1
        """
    )


def soft_delete_bag_weight_query():
    """Soft-delete (active = 0) one bag-weight row by id + co_id (co_id-scoped)."""
    return text(
        """
        UPDATE jute_sqc_bag_weight
        SET active = 0,
            updated_by = :updated_by,
            updated_date_time = CURRENT_TIMESTAMP
        WHERE bag_weight_id = :bag_weight_id
          AND co_id = :co_id
        """
    )


# =============================================================================
# R-08-24 Bag Checking QC (jute_sqc_bag_check + _dtl)
# Header + detail clone of the fabric_construction builders. by_date loads the headers,
# the router then loads each block's per-bag rows via get_bag_check_dtl_query and computes
# the per-column aggregates + HY/LT percents in Python (NOT stored). table/delete co_id-scoped.
# =============================================================================


def get_bag_check_table_query(search: str = None):
    """Paginated active bag-check blocks for a company, newest first; bag count per block."""
    search_filter = ""
    if search:
        search_filter = """
            AND (
                im.item_name LIKE :search
                OR im.item_code LIKE :search
                OR bc.bag_type_label LIKE :search
                OR bc.vendor_name LIKE :search
                OR bc.id_code LIKE :search
            )
        """

    # The trend row needs the same per-block weight aggregates the by_date view shows
    # (avg bag wt / avg corr / sample stdev / CV% + OBS & CORR HY/LT vs std bag wt).
    # Compute them in one grouped derived table over the detail rows so a single SELECT
    # feeds the FE history table (matches the Python by_date math: 2dp avg base for HY/LT,
    # STDDEV_SAMP -> NULL for a single bag, CV = stdev/avg*100). agg.* is NULL when a block
    # has no detail rows; the LEFT JOIN keeps the block visible.
    sql = f"""
        SELECT
            bc.bag_check_id,
            bc.entry_date,
            bc.branch_id,
            bc.item_id,
            im.item_name,
            im.item_code,
            bc.bag_type_label,
            bc.vendor_name,
            bc.id_code,
            bc.std_bag_weight,
            bc.std_length,
            bc.std_width,
            bc.std_ends,
            bc.std_picks,
            bc.std_stitch,
            bc.std_mr_pct,
            agg.bag_count,
            ROUND(agg.avg_bag_wt, 2) AS avg_bag_wt,
            ROUND(agg.avg_corr_wt, 2) AS avg_corr_wt,
            ROUND(agg.bag_wt_stdev, 3) AS bag_wt_stdev,
            CASE WHEN agg.bag_wt_stdev IS NOT NULL AND agg.avg_bag_wt > 0
                 THEN ROUND(agg.bag_wt_stdev / agg.avg_bag_wt * 100, 2) END AS bag_wt_cv_pct,
            CASE WHEN bc.std_bag_weight > 0
                 THEN ROUND((ROUND(agg.avg_bag_wt, 2) - bc.std_bag_weight)
                            / bc.std_bag_weight * 100, 2) END AS obs_hy_lt_pct,
            CASE WHEN bc.std_bag_weight > 0
                 THEN ROUND((ROUND(agg.avg_corr_wt, 2) - bc.std_bag_weight)
                            / bc.std_bag_weight * 100, 2) END AS corr_hy_lt_pct,
            bc.updated_date_time
        FROM jute_sqc_bag_check bc
        LEFT JOIN item_mst im ON im.item_id = bc.item_id
        LEFT JOIN (
            SELECT
                d.bag_check_id,
                COUNT(*)                  AS bag_count,
                AVG(d.bag_wt_gm)          AS avg_bag_wt,
                AVG(d.corr_wt_gm)         AS avg_corr_wt,
                STDDEV_SAMP(d.bag_wt_gm)  AS bag_wt_stdev
            FROM jute_sqc_bag_check_dtl d
            GROUP BY d.bag_check_id
        ) agg ON agg.bag_check_id = bc.bag_check_id
        WHERE bc.co_id = :co_id
          AND bc.active = 1
          AND (:branch_id IS NULL OR bc.branch_id = :branch_id)
          {search_filter}
        ORDER BY bc.entry_date DESC, bc.bag_check_id DESC
        LIMIT :limit OFFSET :offset
    """
    return text(sql)


def get_bag_check_table_count_query(search: str = None):
    """Row count for the paginated bag-check table (same filters as data query)."""
    search_filter = ""
    if search:
        search_filter = """
            AND (
                im.item_name LIKE :search
                OR im.item_code LIKE :search
                OR bc.bag_type_label LIKE :search
                OR bc.vendor_name LIKE :search
                OR bc.id_code LIKE :search
            )
        """

    sql = f"""
        SELECT COUNT(*) AS total
        FROM jute_sqc_bag_check bc
        LEFT JOIN item_mst im ON im.item_id = bc.item_id
        WHERE bc.co_id = :co_id
          AND bc.active = 1
          AND (:branch_id IS NULL OR bc.branch_id = :branch_id)
          {search_filter}
    """
    return text(sql)


def get_bag_check_by_date_query():
    """Active bag-check block headers for one (co_id, branch_id, entry_date), labelled.

    Branch filter is NULL-tolerant. The router loads each block's per-bag rows via
    get_bag_check_dtl_query and computes the aggregates + HY/LT percents in Python.
    """
    return text(
        """
        SELECT
            bc.bag_check_id,
            bc.entry_date,
            bc.branch_id,
            bc.item_id,
            im.item_name,
            im.item_code,
            bc.bag_type_label,
            bc.vendor_name,
            bc.id_code,
            bc.std_bag_weight,
            bc.std_length,
            bc.std_width,
            bc.std_ends,
            bc.std_picks,
            bc.std_stitch,
            bc.std_mr_pct
        FROM jute_sqc_bag_check bc
        LEFT JOIN item_mst im ON im.item_id = bc.item_id
        WHERE bc.co_id = :co_id
          AND bc.active = 1
          AND bc.entry_date = :entry_date
          AND (:branch_id IS NULL OR bc.branch_id = :branch_id OR bc.branch_id IS NULL)
        ORDER BY bc.bag_check_id
        """
    )


def get_bag_check_dtl_query():
    """Per-bag inspection rows for one bag-check block, in entry order."""
    return text(
        """
        SELECT
            bag_check_dtl_id,
            sl_no,
            length_cm,
            width_cm,
            ends_dm,
            picks_dm,
            mr_pct,
            bag_wt_gm,
            stitch_dm,
            defects,
            corr_wt_gm
        FROM jute_sqc_bag_check_dtl
        WHERE bag_check_id = :bag_check_id
        ORDER BY sl_no, bag_check_dtl_id
        """
    )


def get_bag_check_by_id_query():
    """A single active bag-check header by id + co_id (delete existence check, co_id-scoped)."""
    return text(
        """
        SELECT bag_check_id, co_id, branch_id, entry_date, item_id, active
        FROM jute_sqc_bag_check
        WHERE bag_check_id = :bag_check_id
          AND co_id = :co_id
          AND active = 1
        """
    )


def soft_delete_bag_check_query():
    """Soft-delete (active = 0) one bag-check header by id + co_id (co_id-scoped)."""
    return text(
        """
        UPDATE jute_sqc_bag_check
        SET active = 0,
            updated_by = :updated_by,
            updated_date_time = CURRENT_TIMESTAMP
        WHERE bag_check_id = :bag_check_id
          AND co_id = :co_id
        """
    )


# =============================================================================
# R-08-25 PACKING MR% QC (jute_sqc_packing_mr)
# Morrah-shaped flat header: paginated table + count + by-date + by-id + delete.
# avg_mr stored at save; the per-group WEIGHTED roll-up is computed in Python.
# =============================================================================


def get_packing_mr_table_query(search: str = None):
    """Paginated active packing-MR rows for a company, newest first (morrah table clone)."""
    search_filter = ""
    if search:
        search_filter = """
            AND (
                pm.quality_group LIKE :search
                OR pm.quality_label LIKE :search
                OR pm.construction_code LIKE :search
                OR im.item_name LIKE :search
            )
        """

    sql = f"""
        SELECT
            pm.packing_mr_id,
            pm.entry_date,
            pm.quality_group,
            pm.item_id,
            im.item_name,
            pm.quality_label,
            pm.construction_code,
            pm.calc_avg_mr AS avg_mr,
            pm.branch_id,
            pm.updated_date_time
        FROM jute_sqc_packing_mr pm
        LEFT JOIN item_mst im ON im.item_id = pm.item_id
        WHERE pm.co_id = :co_id
        AND pm.active = 1
        {search_filter}
        ORDER BY pm.entry_date DESC, pm.packing_mr_id DESC
        LIMIT :limit OFFSET :offset
    """
    return text(sql)


def get_packing_mr_table_count_query(search: str = None):
    """Row count for the paginated packing-MR table (same filters as the data query)."""
    search_filter = ""
    if search:
        search_filter = """
            AND (
                pm.quality_group LIKE :search
                OR pm.quality_label LIKE :search
                OR pm.construction_code LIKE :search
                OR im.item_name LIKE :search
            )
        """

    sql = f"""
        SELECT COUNT(*) AS total
        FROM jute_sqc_packing_mr pm
        LEFT JOIN item_mst im ON im.item_id = pm.item_id
        WHERE pm.co_id = :co_id
        AND pm.active = 1
        {search_filter}
    """
    return text(sql)


def get_packing_mr_by_date_query():
    """Active packing-MR reading-sets for one (co_id, branch_id, entry_date), with labels.

    Branch filter is NULL-tolerant. Per-column avg and the per-group WEIGHTED roll-up
    (sum of all readings / count of all readings) are computed in Python from readings.
    """
    return text(
        """
        SELECT
            pm.packing_mr_id,
            pm.quality_group,
            pm.item_id,
            im.item_name,
            pm.quality_label,
            pm.construction_code,
            pm.readings,
            pm.calc_avg_mr
        FROM jute_sqc_packing_mr pm
        LEFT JOIN item_mst im ON im.item_id = pm.item_id
        WHERE pm.co_id = :co_id
        AND pm.active = 1
        AND pm.entry_date = :entry_date
        AND (:branch_id IS NULL OR pm.branch_id = :branch_id OR pm.branch_id IS NULL)
        ORDER BY pm.quality_group, pm.packing_mr_id
        """
    )


def get_packing_mr_by_id_query():
    """A single active packing-MR row by id + co_id (delete existence check, co_id-scoped)."""
    return text(
        """
        SELECT packing_mr_id, co_id, branch_id, entry_date, item_id, quality_group,
               quality_label, construction_code, readings, calc_avg_mr, active
        FROM jute_sqc_packing_mr
        WHERE packing_mr_id = :packing_mr_id
          AND co_id = :co_id
          AND active = 1
        """
    )


def soft_delete_packing_mr_query():
    """Soft-delete (active = 0) one packing-MR row by id + co_id (co_id-scoped)."""
    return text(
        """
        UPDATE jute_sqc_packing_mr
        SET active = 0,
            updated_by = :updated_by,
            updated_date_time = CURRENT_TIMESTAMP
        WHERE packing_mr_id = :packing_mr_id
          AND co_id = :co_id
        """
    )


# =============================================================================
# R-08-28 Fabric Fault QC (jute_sqc_fabric_fault)
# Flat single-table morrah clone (stitch precedent). ONE row = ONE inspected piece; the
# 15 fault counts live in a JSON string (fault_counts). calc_piece_total stored at save.
# The DAY roll-up (per-fault totals/scores + grand total/score) is computed in Python in
# the router over the parsed fault_counts arrays, so by_date just projects raw columns.
# =============================================================================


def get_fabric_fault_table_query(search: str = None):
    """Paginated active fabric-fault pieces for a company, newest first (history = trend)."""
    search_filter = ""
    if search:
        search_filter = """
            AND (
                im.item_name LIKE :search
                OR im.item_code LIKE :search
                OR m.machine_name LIKE :search
                OR sp.spell_code LIKE :search
                OR ff.inspector_name LIKE :search
            )
        """

    sql = f"""
        SELECT
            ff.fabric_fault_id,
            ff.entry_date,
            ff.branch_id,
            ff.item_id,
            im.item_name,
            ff.loom_id,
            m.machine_name AS loom_name,
            sp.spell_code,
            ff.calc_piece_total AS piece_total,
            ff.updated_date_time
        FROM jute_sqc_fabric_fault ff
        LEFT JOIN item_mst im ON im.item_id = ff.item_id
        LEFT JOIN machine_mst m ON m.machine_id = ff.loom_id
        LEFT JOIN spell_mst sp ON sp.spell_id = ff.spell_id
        WHERE ff.co_id = :co_id
        AND ff.active = 1
        {search_filter}
        ORDER BY ff.entry_date DESC, ff.fabric_fault_id DESC
        LIMIT :limit OFFSET :offset
    """
    return text(sql)


def get_fabric_fault_table_count_query(search: str = None):
    """Row count for the paginated fabric-fault table (same filters as the data query)."""
    search_filter = ""
    if search:
        search_filter = """
            AND (
                im.item_name LIKE :search
                OR im.item_code LIKE :search
                OR m.machine_name LIKE :search
                OR sp.spell_code LIKE :search
                OR ff.inspector_name LIKE :search
            )
        """

    sql = f"""
        SELECT COUNT(*) AS total
        FROM jute_sqc_fabric_fault ff
        LEFT JOIN item_mst im ON im.item_id = ff.item_id
        LEFT JOIN machine_mst m ON m.machine_id = ff.loom_id
        LEFT JOIN spell_mst sp ON sp.spell_id = ff.spell_id
        WHERE ff.co_id = :co_id
        AND ff.active = 1
        {search_filter}
    """
    return text(sql)


def get_fabric_fault_by_date_query():
    """Active fabric-fault pieces for one (co_id, branch_id, entry_date), with cloth/loom/
    spell labels. Branch filter is NULL-tolerant. The day roll-up matrix is computed in the
    router from each piece's parsed fault_counts JSON."""
    return text(
        """
        SELECT
            ff.fabric_fault_id,
            ff.spell_id,
            sp.spell_code,
            ff.item_id,
            im.item_name,
            ff.loom_id,
            m.machine_name AS loom_name,
            m.mech_code,
            ff.date_of_weaving,
            ff.remarks,
            ff.inspector_name,
            ff.fault_counts,
            ff.calc_piece_total
        FROM jute_sqc_fabric_fault ff
        LEFT JOIN item_mst im ON im.item_id = ff.item_id
        LEFT JOIN machine_mst m ON m.machine_id = ff.loom_id
        LEFT JOIN spell_mst sp ON sp.spell_id = ff.spell_id
        WHERE ff.co_id = :co_id
        AND ff.active = 1
        AND ff.entry_date = :entry_date
        AND (:branch_id IS NULL OR ff.branch_id = :branch_id OR ff.branch_id IS NULL)
        ORDER BY ff.fabric_fault_id
        """
    )


def get_fabric_fault_by_id_query():
    """A single active fabric-fault piece by id + co_id (delete existence check)."""
    return text(
        """
        SELECT fabric_fault_id, co_id, branch_id, entry_date, spell_id, item_id,
               loom_id, date_of_weaving, fault_counts, calc_piece_total,
               remarks, inspector_name, active
        FROM jute_sqc_fabric_fault
        WHERE fabric_fault_id = :fabric_fault_id
          AND co_id = :co_id
          AND active = 1
        """
    )


def soft_delete_fabric_fault_query():
    """Soft-delete (active = 0) one fabric-fault piece by id + co_id (co_id-scoped)."""
    return text(
        """
        UPDATE jute_sqc_fabric_fault
        SET active = 0,
            updated_by = :updated_by,
            updated_date_time = CURRENT_TIMESTAMP
        WHERE fabric_fault_id = :fabric_fault_id
          AND co_id = :co_id
        """
    )


# =============================================================================
# R-08-02 Emulsion QC (jute_sqc_emulsion)
# Flat single-row recipe log (NO readings array, NO StDev/CV). Machine picker = SPREADER
# machines (clone of get_breaker_card_machines_query binding :spreader_type). by_date/by_id
# LEFT JOIN machine_mst for the name; theoretical_oil_pct + oil_pct_status are computed in the
# router on read (NOT stored). table/delete co_id-scoped.
# =============================================================================

# All stored recipe + additive columns (shared by the table / by_date / by_id selects).
_EMULSION_COLS = """
            e.emulsion_id,
            e.co_id,
            e.branch_id,
            e.entry_date,
            e.mc_id,
            e.oil_used_ltr,
            e.tank_capacity_ltr,
            e.oil_pct_in_emulsion,
            e.std_oil_pct_low,
            e.std_oil_pct_high,
            e.adco_used_ml,
            e.eco_fin_used_ltr,
            e.p40_gms,
            e.efjl_kg,
            e.glycerine_gms,
            e.castrol_oil,
            e.diesel_ltr,
            e.citric_acid_ltr,
            e.enzyme_gms,
            e.treated_water_ltr,
            e.rbo_ltr,
            e.jbo_ltr,
            e.molasses_kg,
            e.urea_kg,
            e.biochemical_kg,
            e.jsp66,
            e.feel_free_good_ve_kg,
            e.spreader_rolls_made,
            e.others,
            e.prepared_by,
            e.updated_date_time
"""


def get_emulsion_machines_query():
    """SPREADER machines for a branch (machine_type resolved by name).

    Cloned from get_breaker_card_machines_query: same machine_mst -> machine_type_mst ->
    dept_mst walk, branch-scoped via dept_mst.branch_id. The machine type is bound at call
    time via :spreader_type (SPREADER_MACHINE_TYPE_NAME from src.juteProduction.constants).
    The router de-dups by machine_id (dev3 may carry duplicate machine rows). mc_id is
    OPTIONAL on create."""
    return text(
        """
        SELECT
            m.machine_id,
            m.machine_name,
            m.mech_code,
            d.dept_id,
            d.dept_desc AS dept_name,
            d.branch_id
        FROM machine_mst m
        INNER JOIN machine_type_mst mt ON mt.machine_type_id = m.machine_type_id
        INNER JOIN dept_mst d ON d.dept_id = m.dept_id
        WHERE m.active = 1
          AND mt.active = 1
          AND mt.machine_type_name = :spreader_type
          AND (:branch_id IS NULL OR d.branch_id = :branch_id)
        ORDER BY m.machine_name
        """
    )


def get_emulsion_table_query(search: str = None):
    """Paginated active emulsion rows for a company, newest first."""
    search_filter = ""
    if search:
        search_filter = """
            AND (
                m.machine_name LIKE :search
                OR e.prepared_by LIKE :search
                OR e.others LIKE :search
            )
        """

    sql = f"""
        SELECT
            e.emulsion_id,
            e.entry_date,
            e.branch_id,
            e.mc_id,
            m.machine_name,
            e.oil_used_ltr,
            e.tank_capacity_ltr,
            e.oil_pct_in_emulsion,
            e.std_oil_pct_low,
            e.std_oil_pct_high,
            e.updated_date_time
        FROM jute_sqc_emulsion e
        LEFT JOIN machine_mst m ON m.machine_id = e.mc_id
        WHERE e.co_id = :co_id
          AND e.active = 1
          AND (:branch_id IS NULL OR e.branch_id = :branch_id)
          {search_filter}
        ORDER BY e.entry_date DESC, e.emulsion_id DESC
        LIMIT :limit OFFSET :offset
    """
    return text(sql)


def get_emulsion_table_count_query(search: str = None):
    """Row count for the paginated emulsion table (same filters as the data query)."""
    search_filter = ""
    if search:
        search_filter = """
            AND (
                m.machine_name LIKE :search
                OR e.prepared_by LIKE :search
                OR e.others LIKE :search
            )
        """

    sql = f"""
        SELECT COUNT(*) AS total
        FROM jute_sqc_emulsion e
        LEFT JOIN machine_mst m ON m.machine_id = e.mc_id
        WHERE e.co_id = :co_id
          AND e.active = 1
          AND (:branch_id IS NULL OR e.branch_id = :branch_id)
          {search_filter}
    """
    return text(sql)


def get_emulsion_by_date_query():
    """Active emulsion rows for one (co_id, branch_id, entry_date), with the machine name.

    Branch filter is NULL-tolerant. All stored fields project straight through; the router
    adds the computed theoretical_oil_pct + oil_pct_status on read.
    """
    sql = f"""
        SELECT
        {_EMULSION_COLS},
            m.machine_name
        FROM jute_sqc_emulsion e
        LEFT JOIN machine_mst m ON m.machine_id = e.mc_id
        WHERE e.co_id = :co_id
          AND e.active = 1
          AND e.entry_date = :entry_date
          AND (:branch_id IS NULL OR e.branch_id = :branch_id OR e.branch_id IS NULL)
        ORDER BY e.emulsion_id
    """
    return text(sql)


def get_emulsion_by_id_query():
    """A single active emulsion row by id + co_id (delete existence check, co_id-scoped)."""
    return text(
        """
        SELECT emulsion_id, co_id, branch_id, entry_date, mc_id, active
        FROM jute_sqc_emulsion
        WHERE emulsion_id = :emulsion_id
          AND co_id = :co_id
          AND active = 1
        """
    )


def soft_delete_emulsion_query():
    """Soft-delete (active = 0) one emulsion row by id + co_id (co_id-scoped)."""
    return text(
        """
        UPDATE jute_sqc_emulsion
        SET active = 0,
            updated_by = :updated_by,
            updated_date_time = CURRENT_TIMESTAMP
        WHERE emulsion_id = :emulsion_id
          AND co_id = :co_id
        """
    )


# =============================================================================
# Humidity Recording SQC queries (plant-wide department temperature / RH log)
# =============================================================================
#
# Flat single-table (jute_sqc_humidity). One row per (report_date, dept, round)
# reading-set; 1..3 spots stored as a JSON string array. Department dropdown reuses
# get_morrah_wt_departments_query (dept_mst by branch) — not re-implemented here.


def get_humidity_table_query(search: str = None):
    """Paginated active humidity reading-sets for a company, newest first."""
    search_filter = ""
    if search:
        search_filter = """
            AND (
                dm.dept_desc LIKE :search
                OR h.prepared_by LIKE :search
            )
        """

    sql = f"""
        SELECT
            h.humidity_id,
            h.report_date,
            h.branch_id,
            h.dept_id,
            dm.dept_desc,
            h.round_no,
            h.calc_avg_temp AS avg_temp,
            h.calc_avg_rh AS avg_rh,
            h.prepared_by,
            h.updated_date_time
        FROM jute_sqc_humidity h
        LEFT JOIN dept_mst dm ON dm.dept_id = h.dept_id
        WHERE h.co_id = :co_id
          AND h.active = 1
          AND (:branch_id IS NULL OR h.branch_id = :branch_id)
          {search_filter}
        ORDER BY h.report_date DESC, h.humidity_id DESC
        LIMIT :limit OFFSET :offset
    """
    return text(sql)


def get_humidity_table_count_query(search: str = None):
    """Row count for the paginated humidity table (same filters as data query)."""
    search_filter = ""
    if search:
        search_filter = """
            AND (
                dm.dept_desc LIKE :search
                OR h.prepared_by LIKE :search
            )
        """

    sql = f"""
        SELECT COUNT(*) AS total
        FROM jute_sqc_humidity h
        LEFT JOIN dept_mst dm ON dm.dept_id = h.dept_id
        WHERE h.co_id = :co_id
          AND h.active = 1
          AND (:branch_id IS NULL OR h.branch_id = :branch_id)
          {search_filter}
    """
    return text(sql)


def get_humidity_by_date_query():
    """Active humidity reading-sets for one (co_id, branch_id, report_date), dept-labelled.

    Branch filter is NULL-tolerant. spots (JSON) + stored avgs project straight through;
    the caller json.loads spots and groups rows by dept then round.
    """
    return text(
        """
        SELECT
            h.humidity_id,
            h.dept_id,
            dm.dept_desc,
            h.round_no,
            h.spots,
            h.calc_avg_temp AS avg_temp,
            h.calc_avg_rh AS avg_rh,
            h.prepared_by
        FROM jute_sqc_humidity h
        LEFT JOIN dept_mst dm ON dm.dept_id = h.dept_id
        WHERE h.co_id = :co_id
          AND h.active = 1
          AND h.report_date = :report_date
          AND (:branch_id IS NULL OR h.branch_id = :branch_id OR h.branch_id IS NULL)
        ORDER BY h.dept_id, h.round_no, h.humidity_id
        """
    )


def get_humidity_by_id_query():
    """A single active humidity row by id + co_id (delete existence check, co_id-scoped)."""
    return text(
        """
        SELECT humidity_id, co_id, branch_id, report_date, dept_id,
               round_no, spots, active
        FROM jute_sqc_humidity
        WHERE humidity_id = :humidity_id
          AND co_id = :co_id
          AND active = 1
        """
    )


def soft_delete_humidity_query():
    """Soft-delete (active = 0) one humidity row by id + co_id (co_id-scoped)."""
    return text(
        """
        UPDATE jute_sqc_humidity
        SET active = 0,
            updated_by = :updated_by,
            updated_date_time = CURRENT_TIMESTAMP
        WHERE humidity_id = :humidity_id
          AND co_id = :co_id
        """
    )
