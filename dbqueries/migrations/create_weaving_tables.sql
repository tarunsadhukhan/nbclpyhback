-- Migration: Weaving production tables — Quality Master (+ composite _dtl),
--            Standards/Targets Map, daily Production Entry, Loom->Quality map,
--            and Beam-change map. (per SPEC §4.1/§5.1/§6.1/§6.6/§6.7 +
--            weaving-production-design.md "Tables").
-- Date: 2026-06-23
-- Applies to: tenant database dev3 (QA). Promote to other tenants later.
--
-- Context: Weaving is the jute-production stage AFTER Beaming. Warp beams are
-- mounted on looms and weft is interlaced to weave jute cloth, measured per CUT
-- (a fixed finished length) and per JUGAR (a partial/leftover cut carried across
-- shifts). This script clones the beaming module's table shapes (rename bm->weaving)
-- and adds the spinning-style Loom->Quality map + a beam-change map.
--
-- Persona: Portal. Soft delete (active TINYINT default 1). No created_* columns
-- (audit via DB triggers). Run AFTER seed_weaving_loom_machine_type.sql.

-- 1. Weaving Quality Master (SPEC §4.1) — item -> weaving_quality (construction attrs).
CREATE TABLE jute_prod_weaving_quality (
    weaving_quality_id   INT          NOT NULL AUTO_INCREMENT,
    co_id                INT          NOT NULL,
    branch_id            INT          NULL,
    item_id              INT          NOT NULL,                  -- woven cloth (item_grp_mst.item_type_id=5)
    weaving_quality_code VARCHAR(50)  NOT NULL,                  -- join key (legacy quality_code)
    weaving_quality_name VARCHAR(100) NULL,
    ends                 INT          NOT NULL,                  -- warp ends
    finished_length      DECIMAL(12,3) NOT NULL,                -- yds per full cut (= per piece, Q15)
    ozs_yds              DECIMAL(10,4) NOT NULL,                 -- ACTUAL oz/yd -> production_kg (legacy q_ozs_yds)
    std_ozs_yds          DECIMAL(10,4) NULL,                    -- STANDARD oz/yd -> std_prod_kg (distinct from ozs_yds)
    no_of_jugar_per_cut  DECIMAL(10,3) NOT NULL,                -- jugars per full cut (>0) — jugar->yds divisor
    width                DECIMAL(10,3) NULL,                    -- fabric width (reference)
    ports                DECIMAL(10,3) NULL,                    -- reed ports (distinct from reed_porter, Q16)
    reed_porter          DECIMAL(10,3) NULL,                    -- reed porter (ends-in-beam input, Q16 distinct)
    shrinkage_pct        DECIMAL(6,3)  NULL,                    -- width-wise shrinkage % (reference, Q14)
    shots                DECIMAL(10,3) NULL,                    -- target shots/pick (reference)
    mc_teeth             INT          NULL,                     -- change-gear teeth
    jbo_rbo              VARCHAR(10)  NULL,                      -- single/double-loom indicator (legacy jbo_rbo)
    reed_space           DECIMAL(10,3) NULL,                    -- reed space (legacy q_reed_space)
    tpi                  DECIMAL(10,3) NULL,                     -- twist per inch (reporting)
    yarn_count           VARCHAR(20)  NULL,                      -- reporting (legacy yarn_count)
    is_composite         TINYINT      NOT NULL DEFAULT 0,        -- 1 = multi-warp, needs _dtl (mirror beaming)
    active               TINYINT      NOT NULL DEFAULT 1,
    updated_by           INT          NULL,
    updated_date_time    TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (weaving_quality_id),
    KEY idx_wq_co_item (co_id, item_id),
    CONSTRAINT fk_wq_item FOREIGN KEY (item_id) REFERENCES item_mst (item_id)
);

-- 1b. Composite-warp components (SPEC §4.1 Q6) — child of jute_prod_weaving_quality.
--     Mirror jute_prod_bm_quality_dtl: each child row holds one component's (ends, count).
CREATE TABLE jute_prod_weaving_quality_dtl (
    weaving_quality_dtl_id INT          NOT NULL AUTO_INCREMENT,
    weaving_quality_id     INT          NOT NULL,
    component_no           INT          NOT NULL,                -- 1,2,... ordering within the warp
    ends                   INT          NOT NULL,                -- this component's warp ends
    yarn_item_id           INT          NULL,                    -- jute yarn supplying this component count
    count                  DECIMAL(10,3) NOT NULL,
    active                 TINYINT      NOT NULL DEFAULT 1,
    PRIMARY KEY (weaving_quality_dtl_id),
    KEY idx_wqd_parent (weaving_quality_id),
    CONSTRAINT fk_wqd_parent FOREIGN KEY (weaving_quality_id) REFERENCES jute_prod_weaving_quality (weaving_quality_id)
);

-- 2. Weaving Standards / Targets Map (SPEC §5.1) — effective-dated, QUALITY-ONLY (qid).
--    Same shape as jute_prod_beaming_target_map (PK renamed). id_type kept for table-shape
--    parity but only 'qid' rows are written (Q5: no loom mcid standards).
CREATE TABLE jute_prod_weaving_target_map (
    weaving_target_map_id INT          NOT NULL AUTO_INCREMENT,
    co_id                 INT          NOT NULL,
    branch_id             INT          NULL,
    effective_date        DATE         NOT NULL,
    ref_id                INT          NOT NULL,                 -- weaving_quality_id (qid)
    id_type               VARCHAR(8)   NOT NULL,                 -- 'qid' (quality-only, Q5)
    value_role            VARCHAR(10)  NOT NULL,                 -- 'standard' | 'target' | 'actual'
    param                 VARCHAR(20)  NOT NULL,                 -- speed | picks | eff
    value                 DECIMAL(12,4) NOT NULL DEFAULT 0.0000,
    active                TINYINT      NOT NULL DEFAULT 1,
    updated_by            INT          NULL,
    updated_date_time     TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (weaving_target_map_id),
    KEY idx_wtm_lookup (co_id, ref_id, id_type, value_role, param, effective_date),
    KEY idx_wtm_co (co_id)
);

-- 2b. Loom -> Quality map (SPEC §6.6) — spinning-style per (date, spell, loom) assignment.
--     One active row per (tran_date, spell_id, machine_id) (upsert). Production inherits quality.
CREATE TABLE jute_prod_weaving_quality_map (
    weaving_quality_map_id INT       NOT NULL AUTO_INCREMENT,
    co_id                  INT       NOT NULL,
    branch_id              INT       NULL,
    tran_date              DATE      NOT NULL,
    spell_id               INT       NOT NULL,
    machine_id             INT       NOT NULL,                   -- loom (machine_type 'Loom')
    weaving_quality_id     INT       NOT NULL,                   -- the assigned quality
    active                 TINYINT   NOT NULL DEFAULT 1,
    updated_by             INT       NULL,
    updated_date_time      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (weaving_quality_map_id),
    KEY idx_wqm_key (co_id, tran_date, spell_id, machine_id)
);

-- 2c. Beam-change map (SPEC §6.7) — beam -> loom assignment recorded on each beam change.
CREATE TABLE jute_prod_weaving_beam_map (
    weaving_beam_map_id INT          NOT NULL AUTO_INCREMENT,
    co_id               INT          NOT NULL,
    branch_id           INT          NULL,
    tran_date           DATE         NOT NULL,
    spell_id            INT          NOT NULL,
    machine_id          INT          NOT NULL,                   -- loom
    beam_no             VARCHAR(50)  NOT NULL,                   -- physical beam mounted
    active              TINYINT      NOT NULL DEFAULT 1,
    updated_by          INT          NULL,
    updated_date_time   TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (weaving_beam_map_id),
    KEY idx_wbm_key (co_id, tran_date, spell_id, machine_id)
);

-- 3. Weaving Production Entry (SPEC §6.1) — daily per loom+quality+spell INPUTS.
--    Grain: (co_id, tran_date, spell_id, machine_id, weaving_quality_id, active=1).
--    weaving_quality_id inherited from §6.6 map; eb_id via attendance view; beam_no from §6.7 map.
--    STORAGE MODEL = FREEZE NOTHING + VIEW (2026-06-24): this table is INPUTS-ONLY.
--    open_jugar, jugar, the resolved-standards snapshot and every computed output are
--    NOT stored — they are recomputed on read by vw_weaving_daily (below). cj is the
--    operator-entered closing jugar (DECIMAL; 0 <= cj <= no_of_jugar_per_cut, enforced
--    at write time); oj/jugar/production/std/efficiency all live in the view.
CREATE TABLE jute_prod_weaving_daily (
    weaving_daily_id    INT NOT NULL AUTO_INCREMENT,
    co_id               INT NOT NULL,
    branch_id           INT NULL,
    tran_date           DATE NOT NULL,
    spell_id            INT NOT NULL,
    machine_id          INT NOT NULL,                            -- loom
    weaving_quality_id  INT NOT NULL,                            -- inherited from quality map (§6.6)
    eb_id               INT NULL,                                -- resolved via attendance view (Q7)
    beam_no             VARCHAR(50) NULL,                        -- resolved from beam map (§6.7)
    -- entry inputs ONLY --
    cuts                INT NOT NULL,
    close_jugar         DECIMAL(10,3) NULL DEFAULT 0,            -- operator closing-jugar reading (0 <= cj <= jc)
    less_production     DECIMAL(12,3) NULL DEFAULT 0,            -- operator deduction (legacy less_production_{spell})
    active              TINYINT NOT NULL DEFAULT 1,
    updated_by          INT NULL,
    updated_date_time   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (weaving_daily_id),
    KEY idx_wd_co_branch_date (co_id, branch_id, tran_date),
    KEY idx_wd_key (co_id, tran_date, spell_id, machine_id, weaving_quality_id),
    CONSTRAINT fk_wd_machine FOREIGN KEY (machine_id)         REFERENCES machine_mst (machine_id),
    CONSTRAINT fk_wd_spell   FOREIGN KEY (spell_id)           REFERENCES spell_mst   (spell_id),
    CONSTRAINT fk_wd_quality FOREIGN KEY (weaving_quality_id) REFERENCES jute_prod_weaving_quality (weaving_quality_id)
);

-- 4. vw_weaving_daily (SPEC §6.1a) — computes EVERY derived column on read from the
--    INPUTS-ONLY jute_prod_weaving_daily + current masters + as-of standards.
--    Nothing is frozen; reads always reflect current masters. open_jugar via LAG over
--    existing active rows in spell order A1->B1->A2->B2->C across days (skips empty
--    spells); jugar/production/std/efficiency derived per the revised jugar model.
--    Standards resolve LAST-DATE from jute_prod_weaving_target_map (qid; standard/
--    target/actual); act_picks from vw_weaving_pick_act (avg_picks). Guards every
--    divisor (jc>0, 36*eff_picks>0, std_prod_yds>0). Requires MySQL 8.0+ (window fn).
--
-- !!! DUPLICATED DDL !!! This vw_weaving_daily definition is duplicated VERBATIM in
-- alter_weaving_daily_lean_and_view.sql. The two copies MUST stay byte-for-byte
-- identical — edit BOTH files together on every change.
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
-- ROLLBACK (reverse FK order — children before parents):
-- DROP VIEW  IF EXISTS vw_weaving_daily;
-- DROP TABLE IF EXISTS jute_prod_weaving_daily;
-- DROP TABLE IF EXISTS jute_prod_weaving_beam_map;
-- DROP TABLE IF EXISTS jute_prod_weaving_quality_map;
-- DROP TABLE IF EXISTS jute_prod_weaving_target_map;
-- DROP TABLE IF EXISTS jute_prod_weaving_quality_dtl;
-- DROP TABLE IF EXISTS jute_prod_weaving_quality;
-- =============================================================================
