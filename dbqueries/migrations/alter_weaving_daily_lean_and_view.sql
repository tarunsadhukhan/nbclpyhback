-- =============================================================================
-- Migration: SLIM jute_prod_weaving_daily to INPUTS-ONLY + add vw_weaving_daily
-- =============================================================================
-- Date: 2026-06-24   |   Target tenant DB: dev3 (QA). Promote to other tenants later.
-- DO NOT auto-run against dev3 — apply via the run-migration skill after review.
--
-- STORAGE MODEL = FREEZE NOTHING + VIEW (user decision, 2026-06-24).
--   jute_prod_weaving_daily stores ONLY the operator inputs + identity. Every
--   derived/standard/computed column is REPRODUCIBLE on read, so it is DROPPED
--   from the table and recomputed by the view vw_weaving_daily, which JOINs the
--   current masters and as-of-resolves standards. Nothing is frozen — reads always
--   reflect current masters + as-of standards. There is NO compute-on-save and NO
--   recompute cascade (the view's LAG-over-existing-rows inherently skips empty
--   spells and auto-propagates the open-jugar carry-forward across days).
--
-- REVISED PRODUCTION MODEL 2026-06-30 (server math is authoritative):
--   oj = open_jugar  = LAST AVAILABLE close_jugar for THIS (co_id, machine_id,
--        weaving_quality_id) strictly before this (tran_date, spell) in spell order
--        A1->B1->A2->B2->C across the day boundary; 0 when none. Skips empty spells.
--   cj = close_jugar = operator input (0 <= cj <= jc; cj > jc rejected at write time).
--   jc = no_of_jugar_per_cut (quality master, > 0).
--   adj = less_production (reduce-jugar, Adjustment tab; COALESCE 0).
--   total_jugar = cuts*jc + cj - oj - adj   (jugar column = total_jugar; no wrap/clamp:
--                 cuts*jc keeps it non-negative, so no GREATEST(0) guard is needed.)
--   production_yds = total_jugar * finished_length / jc   (guard jc > 0 else 0)
--   production_kg  = production_yds * ozs_yds * 28.35 / 1000 ; production_mt = kg/1000
--   std_picks ("actual PPI") = AVG picks from vw_weaving_pick_act for the EXACT tran_date
--                 (SQC R-08-21 jute_sqc_weaving_pick); no SQC that day => 0 (no last-date carry,
--                 no target-map fallback). REPLACES the old target-map qid/standard/picks lookup.
--   std_prod_yds ("100prod" = 100% eff theoretical) = (eff_speed*working_hours*60)/(36*std_picks) (guard denom>0)
--   efficiency (ACTUAL eff) = production_yds * 100 / std_prod_yds(100prod)  (guard >0)
--   std_prod_eff ("std prod") = std_prod_yds * std_eff / 100  (computed in planning_grid serializer)
--   eff_speed = COALESCE(act_speed, std_speed) ; act_picks/eff_picks now VESTIGIAL (std_prod uses std_picks)
--   working_hours  = max(0, spell_mst.working_hours - SUM(jute_prod_stoppage_hours))
-- Constants WEAVING_GRAMS_PER_OZ=28.35, WEAVING_YARD_FACTOR=36 are NOT simplified.
-- MySQL 8.0.42 on dev3 (verified 2026-06-24) -> window function in view is supported.

-- -----------------------------------------------------------------------------
-- PART 1 — slim the daily table to INPUTS ONLY
-- -----------------------------------------------------------------------------
-- The pre-2026-06-24 table had close_jugar INT. Change it to DECIMAL(10,3) (cj may
-- be fractional, 0 <= cj <= jc). Keep cuts INT and less_production DECIMAL(12,3).
ALTER TABLE jute_prod_weaving_daily
    MODIFY COLUMN close_jugar     DECIMAL(10,3) NULL DEFAULT 0,
    MODIFY COLUMN less_production DECIMAL(12,3) NULL DEFAULT 0;

-- Drop the 23 reproducible columns (carry-forward + resolved standards + computed).
-- open_jugar + jugar (carry-forward/derived), the resolved-standards snapshot, and
-- every computed output — all recomputed by vw_weaving_daily below.
ALTER TABLE jute_prod_weaving_daily
    DROP COLUMN open_jugar,
    DROP COLUMN jugar,
    DROP COLUMN finished_length,
    DROP COLUMN ozs_yds,
    DROP COLUMN std_ozs_yds,
    DROP COLUMN no_of_jugar_per_cut,
    DROP COLUMN std_speed,
    DROP COLUMN act_speed,
    DROP COLUMN std_picks,
    DROP COLUMN act_picks,
    DROP COLUMN std_eff,
    DROP COLUMN target_eff,
    DROP COLUMN working_hours,
    DROP COLUMN production_yds,
    DROP COLUMN production_kg,
    DROP COLUMN production_mt,
    DROP COLUMN std_prod_yds,
    DROP COLUMN target_prod_yds,
    DROP COLUMN efficiency,
    DROP COLUMN std_prod_kg,
    DROP COLUMN target_kg,
    DROP COLUMN actual_eff,
    DROP COLUMN aports;

-- Resulting LEAN table columns (inputs + identity only):
--   weaving_daily_id, co_id, branch_id, tran_date, spell_id, machine_id,
--   weaving_quality_id, eb_id, beam_no, cuts, close_jugar, less_production,
--   active, updated_by, updated_date_time.

-- -----------------------------------------------------------------------------
-- PART 2 — vw_weaving_daily: compute EVERY derived column on read
-- -----------------------------------------------------------------------------
-- Nesting: layer (a) resolves raw inputs + as-of standards + open_jugar (LAG);
--          layer (b) derives x_raw, jugar, production_yds, std_prod_yds;
--          outer layer (c) rounds + derives kg/mt/efficiency/target columns.
-- Standards resolve LAST-DATE (effective_date <= tran_date, MAX) from
-- jute_prod_weaving_target_map (id_type='qid', ref_id=weaving_quality_id,
-- value_role standard|target|actual), branch-agnostic. act_picks comes from the
-- Weaving Pick-SQC view vw_weaving_pick_act (avg_picks, LAST-DATE by entry_date) —
-- NOT the target map (mirrors services/weaving_standards.resolve_act_picks).
-- Quality is INHERITED via COALESCE(daily.weaving_quality_id, quality_map.*).
-- open_jugar via LAG over EXISTING active rows (skips empty spells, crosses days).
-- Every divisor is guarded (jc>0, 36*eff_picks>0, std_prod_yds>0). co_id is a
-- selectable column so every caller filters by co_id; only active=1 base rows.
--
-- !!! DUPLICATED DDL !!! This vw_weaving_daily definition is duplicated VERBATIM in
-- create_weaving_tables.sql. The two copies MUST stay byte-for-byte identical — edit
-- BOTH files together on every change.
--
-- DOCTRINE: views may format, never accumulate — no window functions, no GROUP BY
-- over full history, no view-on-view in any request path. vw_weaving_daily is
-- REFERENCE SEMANTICS + DIFF ORACLE ONLY: never query it on large tenants;
-- endpoints use the day-slice queries in src/juteProduction/weaving_query.py.

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
        b.total_jugar AS jugar,
        CASE WHEN b.no_of_jugar_per_cut > 0
             THEN b.total_jugar * b.finished_length / b.no_of_jugar_per_cut
             ELSE 0 END AS production_yds,
        -- std_prod_yds uses std_picks (exact-day SQC avg), NOT eff_picks: no SQC that day
        -- => std_picks 0 => std_prod_yds 0 => efficiency 0 (no last-date/target-map fallback).
        CASE WHEN (36 * b.std_picks) > 0
             THEN (b.eff_speed * b.working_hours * 60) / (36 * b.std_picks)
             ELSE 0 END AS std_prod_yds
    FROM (
        SELECT
            a.*,
            (a.cuts * a.no_of_jugar_per_cut + a.close_jugar - a.open_jugar
             - COALESCE(a.less_production, 0)) AS total_jugar
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
                    -- std_picks = exact-day SQC quality-average picks (R-08-21 jute_sqc_weaving_pick
                    -- via vw_weaving_pick_act). entry_date = tran_date EXACTLY (no last-date carry,
                    -- no target-map fallback): no SQC reading that day => NULL => std_prod_yds/eff 0.
                    (SELECT pv.avg_picks FROM vw_weaving_pick_act pv
                      WHERE pv.co_id = d2.co_id AND pv.weaving_quality_id = d2.qid
                        AND pv.entry_date = d2.tran_date
                      LIMIT 1) AS std_picks,
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
-- DROP VIEW IF EXISTS vw_weaving_daily;
--
-- -- Restore the dropped columns (types per create_weaving_tables.sql pre-2026-06-24):
-- ALTER TABLE jute_prod_weaving_daily
--     ADD COLUMN jugar               INT          NOT NULL DEFAULT 0 AFTER close_jugar,
--     ADD COLUMN open_jugar          INT          NULL,
--     ADD COLUMN finished_length     DECIMAL(12,3) NULL,
--     ADD COLUMN ozs_yds             DECIMAL(10,4) NULL,
--     ADD COLUMN std_ozs_yds         DECIMAL(10,4) NULL,
--     ADD COLUMN no_of_jugar_per_cut DECIMAL(10,3) NULL,
--     ADD COLUMN std_speed           DECIMAL(12,4) NULL,
--     ADD COLUMN act_speed           DECIMAL(12,4) NULL,
--     ADD COLUMN std_picks           DECIMAL(12,4) NULL,
--     ADD COLUMN act_picks           DECIMAL(12,4) NULL,
--     ADD COLUMN std_eff             DECIMAL(6,2)  NULL,
--     ADD COLUMN target_eff          DECIMAL(6,2)  NULL,
--     ADD COLUMN working_hours       DECIMAL(5,2)  NULL,
--     ADD COLUMN production_yds      DECIMAL(14,3) NULL,
--     ADD COLUMN production_kg       DECIMAL(14,3) NULL,
--     ADD COLUMN production_mt       DECIMAL(14,4) NULL,
--     ADD COLUMN std_prod_yds        DECIMAL(14,3) NULL,
--     ADD COLUMN target_prod_yds     DECIMAL(14,3) NULL,
--     ADD COLUMN efficiency          DECIMAL(6,2)  NULL,
--     ADD COLUMN std_prod_kg         DECIMAL(14,3) NULL,
--     ADD COLUMN target_kg           DECIMAL(14,3) NULL,
--     ADD COLUMN actual_eff          DECIMAL(6,2)  NULL,
--     ADD COLUMN aports              DECIMAL(10,3) NULL;
-- -- (Optionally MODIFY COLUMN close_jugar INT NULL to fully revert the input type.)
-- =============================================================================
