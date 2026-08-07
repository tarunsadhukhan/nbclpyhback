-- Migration: repoint_vw_spinning_planning_grid.sql
-- Date: 2026-06-16
-- Applies to: tenant databases dev3 (QA) [and sls when promoted]
-- Requires: MySQL 8 (window functions). dev3 = 8.0.42 (verified).
--
-- Recreates vw_spinning_planning_grid for the "yarn IS an item" refactor:
--   (a) REMOVES all references to param_id. That column was already dropped from
--       daily_doff_frames_winding, so the previously-deployed view (which still
--       projected f.param_id) is broken — this recreation fixes that.
--   (b) Renames every yarn_quality_id -> item_id (f.item_id and the qid target/SQC
--       sub-selects key on t.ref_id = f.item_id, c.item_id, e.item_id, w.item_id).
--   (c) Replaces the yarn_quality_master join with:
--         LEFT JOIN item_mst      im ON im.item_id = f.item_id   (im.item_code AS quality_code)
--         LEFT JOIN jute_yarn_mst ym ON ym.item_id = f.item_id   (ym.jute_yarn_count AS std_count)
--
-- Output column names are unchanged from the prior view EXCEPT param_id is dropped
-- from the projection. quality_code is now im.item_code; std_count is ym.jute_yarn_count.
-- co_id is derived machine_mst -> dept_mst -> branch_mst.co_id.
--
-- DEPENDENCY: winding_total reads vw_winding_daily_reconciled. Its source column is
--   jute_prod_winding_daily_qlty.item_id (renamed). This view selects w.item_id, so
--   vw_winding_daily_reconciled must be recreated in lockstep to expose item_id.

DROP VIEW IF EXISTS vw_spinning_planning_grid;

CREATE VIEW vw_spinning_planning_grid AS
SELECT
    eff.co_id,
    eff.branch_id,
    eff.tran_date,
    eff.spell_id,
    eff.spell_code,
    eff.shift_bucket,
    eff.machine_id,
    eff.mech_code,
    eff.machine_name,
    eff.item_id,
    eff.quality_code,
    eff.eb_id,
    eff.spindles,
    eff.minutes,
    eff.act_count,
    eff.std_count,
    eff.std_speed,
    eff.actual_speed,
    eff.target_speed,
    eff.std_tpi,
    eff.actual_tpi,
    eff.target_tpi,
    eff.std_eff,
    eff.target_eff,
    eff.p100prod,
    eff.std_prod,
    eff.target_prod,
    eff.act_prod_doff,
    eff.winding_total,
    eff.act_prod_wind,
    eff.eff_doff,
    COALESCE(ROUND(eff.act_prod_wind / NULLIF(eff.p100prod, 0) * 100, 2), 0) AS eff_winding
FROM (
    -- Level 2: doff-share winding allocation (window SUM over the item+date+shift group)
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
        -- Level 1: production figures derived from the resolved inputs
        SELECT
            r.*,
            ROUND(r.p100prod * r.std_eff / 100, 3) AS std_prod,
            ROUND(r.p100prod * r.target_eff / 100, 3) AS target_prod,
            COALESCE(ROUND(r.act_prod_doff / NULLIF(r.p100prod, 0) * 100, 2), 0) AS eff_doff
        FROM (
            -- Level 0b: 100% production from resolved standards/actuals
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
                -- Level 0a: per-row resolved inputs (all correlated on the row's own tran_date)
                SELECT
                    bm.co_id AS co_id,
                    d.branch_id AS branch_id,
                    f.tran_date AS tran_date,
                    f.spell_id AS spell_id,
                    sp.spell_code AS spell_code,
                    LEFT(sp.spell_code, 1) AS shift_bucket,
                    f.mc_eb_id AS machine_id,
                    m.mech_code AS mech_code,
                    m.machine_name AS machine_name,
                    f.item_id AS item_id,
                    im.item_code AS quality_code,
                    CAST(NULL AS SIGNED) AS eb_id,  -- attendance mapping wired later
                    CAST(COALESCE((
                        SELECT t.value FROM jute_prod_spng_target_map t
                        WHERE t.co_id = bm.co_id AND t.ref_id = f.mc_eb_id AND t.id_type = 'mcid'
                          AND t.value_role = 'standard' AND t.param = 'spindles' AND t.active = 1
                          AND t.effective_date <= f.tran_date
                        ORDER BY t.effective_date DESC LIMIT 1
                    ), 0) AS SIGNED) AS spindles,
                    CASE
                        WHEN sp.working_hours IS NOT NULL THEN ROUND(sp.working_hours * 60)
                        WHEN sp.spell_code = 'A1' THEN 300
                        WHEN sp.spell_code = 'A2' THEN 180
                        ELSE 0
                    END AS minutes,
                    COALESCE((
                        SELECT AVG(c.observed_count) FROM jute_sqc_spinning_count c
                        WHERE c.co_id = bm.co_id AND c.item_id = f.item_id
                          AND c.entry_date = f.tran_date AND c.active = 1
                    ), 0) AS act_count,
                    COALESCE(ym.jute_yarn_count, 0) AS std_count,
                    COALESCE((
                        SELECT t.value FROM jute_prod_spng_target_map t
                        WHERE t.co_id = bm.co_id AND t.ref_id = f.mc_eb_id AND t.id_type = 'mcid'
                          AND t.value_role = 'standard' AND t.param = 'speed' AND t.active = 1
                          AND t.effective_date <= f.tran_date
                        ORDER BY t.effective_date DESC LIMIT 1
                    ), 0) AS std_speed,
                    COALESCE((
                        SELECT e.actual_speed FROM jute_sqc_spinning_entry e
                        WHERE e.co_id = bm.co_id AND e.mc_id = f.mc_eb_id
                          AND e.item_id = f.item_id AND e.active = 1
                          AND e.entry_date <= f.tran_date
                        ORDER BY e.entry_date DESC LIMIT 1
                    ), 0) AS actual_speed,
                    COALESCE((
                        SELECT t.value FROM jute_prod_spng_target_map t
                        WHERE t.co_id = bm.co_id AND t.ref_id = f.mc_eb_id AND t.id_type = 'mcid'
                          AND t.value_role = 'target' AND t.param = 'speed' AND t.active = 1
                          AND t.effective_date <= f.tran_date
                        ORDER BY t.effective_date DESC LIMIT 1
                    ), 0) AS target_speed,
                    COALESCE((
                        SELECT t.value FROM jute_prod_spng_target_map t
                        WHERE t.co_id = bm.co_id AND t.ref_id = f.item_id AND t.id_type = 'qid'
                          AND t.value_role = 'standard' AND t.param = 'tpi' AND t.active = 1
                          AND t.effective_date <= f.tran_date
                        ORDER BY t.effective_date DESC LIMIT 1
                    ), 0) AS std_tpi,
                    COALESCE((
                        SELECT e.actual_tpi FROM jute_sqc_spinning_entry e
                        WHERE e.co_id = bm.co_id AND e.mc_id = f.mc_eb_id
                          AND e.item_id = f.item_id AND e.active = 1
                          AND e.entry_date <= f.tran_date
                        ORDER BY e.entry_date DESC LIMIT 1
                    ), 0) AS actual_tpi,
                    COALESCE((
                        SELECT t.value FROM jute_prod_spng_target_map t
                        WHERE t.co_id = bm.co_id AND t.ref_id = f.item_id AND t.id_type = 'qid'
                          AND t.value_role = 'target' AND t.param = 'tpi' AND t.active = 1
                          AND t.effective_date <= f.tran_date
                        ORDER BY t.effective_date DESC LIMIT 1
                    ), 0) AS target_tpi,
                    COALESCE((
                        SELECT t.value FROM jute_prod_spng_target_map t
                        WHERE t.co_id = bm.co_id AND t.ref_id = f.item_id AND t.id_type = 'qid'
                          AND t.value_role = 'standard' AND t.param = 'eff' AND t.active = 1
                          AND t.effective_date <= f.tran_date
                        ORDER BY t.effective_date DESC LIMIT 1
                    ), 0) AS std_eff,
                    COALESCE((
                        SELECT t.value FROM jute_prod_spng_target_map t
                        WHERE t.co_id = bm.co_id AND t.ref_id = f.item_id AND t.id_type = 'qid'
                          AND t.value_role = 'target' AND t.param = 'eff' AND t.active = 1
                          AND t.effective_date <= f.tran_date
                        ORDER BY t.effective_date DESC LIMIT 1
                    ), 0) AS target_eff,
                    COALESCE((
                        SELECT SUM(dd.net_weight) FROM daily_doff_tbl dd
                        WHERE dd.doff_date = f.tran_date AND dd.spell = f.spell_id
                          AND dd.mc_id = f.mc_eb_id AND (dd.active = 1 OR dd.active IS NULL)
                    ), 0) AS act_prod_doff,
                    COALESCE((
                        SELECT SUM(w.reconciled_qty) FROM vw_winding_daily_reconciled w
                        INNER JOIN spell_mst wsp ON wsp.spell_id = w.spell_id
                        WHERE w.co_id = bm.co_id AND w.item_id = f.item_id
                          AND w.tran_date = f.tran_date
                          AND LEFT(wsp.spell_code, 1) = LEFT(sp.spell_code, 1)
                    ), 0) AS winding_total
                FROM daily_doff_frames_winding f
                INNER JOIN machine_mst m ON m.machine_id = f.mc_eb_id
                INNER JOIN machine_type_mst mt
                        ON mt.machine_type_id = m.machine_type_id
                       AND mt.active = 1
                       AND mt.machine_type_name = 'Spinning'
                INNER JOIN dept_mst d ON d.dept_id = m.dept_id
                INNER JOIN branch_mst bm ON bm.branch_id = d.branch_id
                LEFT JOIN (
                    SELECT spell_id, spell_code, working_hours FROM spell_mst WHERE status = 1
                ) sp ON sp.spell_id = f.spell_id
                LEFT JOIN item_mst im ON im.item_id = f.item_id
                LEFT JOIN jute_yarn_mst ym ON ym.item_id = f.item_id
                WHERE f.spg_wdg = 'S'
                  AND f.item_id IS NOT NULL
                  AND (f.active = 1 OR f.active IS NULL)
            ) b
        ) r
    ) calc
) eff;

-- =============================================================================
-- ROLLBACK:
-- DROP VIEW IF EXISTS vw_spinning_planning_grid;
-- (To fully restore the prior view, reverse rename_yarn_quality_id_to_item_id.sql
--  first, then re-run create_vw_spinning_planning_grid.sql.)
-- =============================================================================
