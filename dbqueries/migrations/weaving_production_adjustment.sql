-- =============================================================================
-- Migration: Wire less_production (reduce-jugar) into vw_weaving_daily.production_yds
-- =============================================================================
-- Date: 2026-06-24   |   Target tenant DB: dev3 (QA). Promote to other tenants later.
-- DO NOT auto-run — apply via the run-migration skill after review.
--
-- WHAT: Re-creates vw_weaving_daily so production_yds subtracts the reduce-jugar
--   term. In derived layer "b", production_yds becomes:
--     GREATEST(0, cuts + jugar/jc - less_production/jc) * finished_length
--   (jc = no_of_jugar_per_cut). open_jugar / close_jugar / jugar carry-forward are
--   UNCHANGED; production_kg/mt and efficiency derive from production_yds so they
--   flow automatically. No schema change — the less_production column already exists
--   on jute_prod_weaving_daily (DECIMAL(12,3) NULL DEFAULT 0). This migration only
--   issues CREATE OR REPLACE VIEW.
--
-- The view body below is copied VERBATIM from weaving_standards_machine_dimension.sql
-- (which is kept byte-identical with alter_weaving_daily_lean_and_view.sql and
-- create_weaving_tables.sql) AFTER the production_yds edit.

CREATE OR REPLACE VIEW vw_weaving_daily AS
SELECT
    c.weaving_daily_id, c.co_id, c.branch_id, c.tran_date,
    c.spell_id, c.spell_code, c.shift_bucket, c.spell_rank,
    c.machine_id, c.mech_code, c.machine_name, c.line_no,
    c.weaving_quality_id, c.item_id, c.item_code, c.item_name,
    c.weaving_quality_code, c.weaving_quality_name, c.is_composite,
    c.eb_id, c.beam_no,
    c.cuts, c.close_jugar, c.less_production,
    c.finished_length, c.ozs_yds, c.std_ozs_yds, c.no_of_jugar_per_cut,
    c.std_speed, c.act_speed, c.std_picks, c.act_picks, c.std_eff, c.target_eff,
    c.eff_speed, c.eff_picks, c.working_hours,
    c.open_jugar, c.jugar,
    ROUND(c.production_yds, 3)                                            AS production_yds,
    ROUND(c.production_yds * c.ozs_yds * 28.35 / 1000, 3)                 AS production_kg,
    ROUND(c.production_yds * c.ozs_yds * 28.35 / 1000 / 1000, 4)          AS production_mt,
    ROUND(c.std_prod_yds, 3)                                             AS std_prod_yds,
    ROUND(CASE WHEN c.target_eff > 0 THEN c.std_prod_yds * c.target_eff / 100 ELSE 0 END, 3) AS target_prod_yds,
    ROUND(CASE WHEN c.std_prod_yds > 0 THEN c.production_yds * 100 / c.std_prod_yds ELSE 0 END, 2) AS efficiency,
    ROUND(CASE WHEN c.std_ozs_yds IS NOT NULL THEN c.production_yds * c.std_ozs_yds * 28.35 / 1000 ELSE 0 END, 3) AS std_prod_kg,
    ROUND(CASE WHEN c.std_ozs_yds IS NOT NULL AND c.target_eff > 0
               THEN c.production_yds * c.std_ozs_yds * 28.35 / 1000 * (c.target_eff / 100) ELSE 0 END, 3) AS target_kg
FROM (
    SELECT
        b.*,
        GREATEST(0, CASE WHEN b.x_raw > b.no_of_jugar_per_cut
                         THEN b.x_raw - b.no_of_jugar_per_cut ELSE b.x_raw END) AS jugar,
        CASE WHEN b.no_of_jugar_per_cut > 0
             THEN GREATEST(0, b.cuts
                              + GREATEST(0, CASE WHEN b.x_raw > b.no_of_jugar_per_cut
                                                 THEN b.x_raw - b.no_of_jugar_per_cut ELSE b.x_raw END)
                                / b.no_of_jugar_per_cut
                              - COALESCE(b.less_production, 0) / b.no_of_jugar_per_cut) * b.finished_length
             ELSE 0 END AS production_yds,
        CASE WHEN (36 * b.eff_picks) > 0
             THEN (b.eff_speed * b.working_hours * 60) / (36 * b.eff_picks)
             ELSE 0 END AS std_prod_yds
    FROM (
        SELECT
            a.*,
            (a.no_of_jugar_per_cut - a.open_jugar + a.close_jugar) AS x_raw
        FROM (
            SELECT
                wd.weaving_daily_id, wd.co_id, wd.branch_id, wd.tran_date,
                wd.spell_id, sp.spell_code, LEFT(sp.spell_code, 1) AS shift_bucket,
                CASE sp.spell_code WHEN 'A1' THEN 1 WHEN 'B1' THEN 2 WHEN 'A2' THEN 3
                                   WHEN 'B2' THEN 4 WHEN 'C' THEN 5 ELSE 99 END AS spell_rank,
                wd.machine_id, m.mech_code, m.machine_name, m.line_no,
                wd.weaving_quality_id AS weaving_quality_id,
                q.item_id, im.item_code, im.item_name,
                q.weaving_quality_code, q.weaving_quality_name, q.is_composite,
                wd.eb_id, wd.beam_no,
                wd.cuts,
                COALESCE(wd.close_jugar, 0)                AS close_jugar,
                COALESCE(wd.less_production, 0)            AS less_production,
                COALESCE(q.finished_length, 0)            AS finished_length,
                COALESCE(q.ozs_yds, 0)                     AS ozs_yds,
                q.std_ozs_yds,
                COALESCE(q.no_of_jugar_per_cut, 0)        AS no_of_jugar_per_cut,
                COALESCE(s.std_speed, 0)                   AS std_speed,
                COALESCE(s.act_speed, 0)                   AS act_speed,
                COALESCE(s.std_picks, 0)                   AS std_picks,
                COALESCE(s.act_picks, 0)                   AS act_picks,
                COALESCE(s.std_eff, 0)                     AS std_eff,
                COALESCE(s.target_eff, 0)                  AS target_eff,
                CASE WHEN COALESCE(s.act_speed,0) > 0 THEN s.act_speed ELSE COALESCE(s.std_speed,0) END AS eff_speed,
                CASE WHEN COALESCE(s.act_picks,0) > 0 THEN s.act_picks ELSE COALESCE(s.std_picks,0) END AS eff_picks,
                GREATEST(0, COALESCE(sp.working_hours, 0) - COALESCE((
                    SELECT SUM(st.stoppage_hours) FROM jute_prod_stoppage_hours st
                    WHERE st.active = 1 AND st.co_id = wd.co_id AND st.machine_id = wd.machine_id
                      AND st.tran_date = wd.tran_date AND st.spell_id = wd.spell_id), 0)) AS working_hours,
                COALESCE(LAG(wd.close_jugar) OVER (
                    PARTITION BY wd.co_id, wd.machine_id, wd.weaving_quality_id
                    ORDER BY wd.tran_date,
                             CASE sp.spell_code WHEN 'A1' THEN 1 WHEN 'B1' THEN 2 WHEN 'A2' THEN 3
                                                WHEN 'B2' THEN 4 WHEN 'C' THEN 5 ELSE 99 END,
                             wd.weaving_daily_id), 0) AS open_jugar
            FROM jute_prod_weaving_daily wd
            LEFT JOIN spell_mst sp ON sp.spell_id = wd.spell_id
            LEFT JOIN machine_mst m ON m.machine_id = wd.machine_id
            LEFT JOIN jute_prod_weaving_quality q
                   ON q.weaving_quality_id = wd.weaving_quality_id
            LEFT JOIN item_mst im ON im.item_id = q.item_id
            LEFT JOIN (
                SELECT
                    d2.weaving_daily_id,
                    (SELECT tm.value FROM jute_prod_weaving_target_map tm
                      WHERE tm.co_id = d2.co_id AND tm.ref_id = d2.mid AND tm.id_type='mcid'
                        AND tm.value_role='standard' AND tm.param='speed' AND tm.active=1
                        AND tm.effective_date <= d2.tran_date
                      ORDER BY tm.effective_date DESC, tm.weaving_target_map_id DESC LIMIT 1) AS std_speed,
                    (SELECT tm.value FROM jute_prod_weaving_target_map tm
                      WHERE tm.co_id = d2.co_id AND tm.ref_id = d2.mid AND tm.id_type='mcid'
                        AND tm.value_role='actual' AND tm.param='speed' AND tm.active=1
                        AND tm.effective_date <= d2.tran_date
                      ORDER BY tm.effective_date DESC, tm.weaving_target_map_id DESC LIMIT 1) AS act_speed,
                    (SELECT tm.value FROM jute_prod_weaving_target_map tm
                      WHERE tm.co_id = d2.co_id AND tm.ref_id = d2.qid AND tm.id_type='qid'
                        AND tm.value_role='standard' AND tm.param='picks' AND tm.active=1
                        AND tm.effective_date <= d2.tran_date
                      ORDER BY tm.effective_date DESC, tm.weaving_target_map_id DESC LIMIT 1) AS std_picks,
                    (SELECT pv.avg_picks FROM vw_weaving_pick_act pv
                      WHERE pv.co_id = d2.co_id AND pv.weaving_quality_id = d2.qid
                        AND pv.entry_date <= d2.tran_date
                      ORDER BY pv.entry_date DESC LIMIT 1) AS act_picks,
                    (SELECT tm.value FROM jute_prod_weaving_target_map tm
                      WHERE tm.co_id = d2.co_id AND tm.ref_id = d2.qid AND tm.id_type='qid'
                        AND tm.value_role='standard' AND tm.param='eff' AND tm.active=1
                        AND tm.effective_date <= d2.tran_date
                      ORDER BY tm.effective_date DESC, tm.weaving_target_map_id DESC LIMIT 1) AS std_eff,
                    (SELECT tm.value FROM jute_prod_weaving_target_map tm
                      WHERE tm.co_id = d2.co_id AND tm.ref_id = d2.qid AND tm.id_type='qid'
                        AND tm.value_role='target' AND tm.param='eff' AND tm.active=1
                        AND tm.effective_date <= d2.tran_date
                      ORDER BY tm.effective_date DESC, tm.weaving_target_map_id DESC LIMIT 1) AS target_eff
                FROM (
                    SELECT w.weaving_daily_id, w.co_id, w.tran_date,
                           w.weaving_quality_id AS qid, w.machine_id AS mid
                    FROM jute_prod_weaving_daily w
                    WHERE w.active = 1
                ) d2
            ) s ON s.weaving_daily_id = wd.weaving_daily_id
            WHERE wd.active = 1
        ) a
    ) b
) c;

-- =============================================================================
-- ROLLBACK
-- =============================================================================
-- Rollback = re-apply the PRIOR view (production_yds WITHOUT the less_production
-- term and WITHOUT the outer GREATEST(0,...)), i.e. the version of vw_weaving_daily
-- in git immediately BEFORE this change. In that prior version, the production_yds
-- expression in derived layer "b" was:
--
--     CASE WHEN b.no_of_jugar_per_cut > 0
--          THEN (b.cuts + GREATEST(0, CASE WHEN b.x_raw > b.no_of_jugar_per_cut
--                                          THEN b.x_raw - b.no_of_jugar_per_cut ELSE b.x_raw END)
--                        / b.no_of_jugar_per_cut) * b.finished_length
--          ELSE 0 END AS production_yds,
--
-- To roll back, run CREATE OR REPLACE VIEW vw_weaving_daily AS ... with that prior
-- expression in place of the current one (the rest of the view body is unchanged).
-- No schema rollback is needed — this migration made no schema change.
-- =============================================================================
