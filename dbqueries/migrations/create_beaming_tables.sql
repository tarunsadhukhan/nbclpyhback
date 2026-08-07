-- Migration: Beaming production tables — Quality Master, Standards/Targets Map,
--            and daily Production Entry (per SPEC §A.3, §B.3, §C.3).
-- Date: 2026-06-21
-- Applies to: tenant database dev3 (QA). Promote to other tenants later.
--
-- Context: Beaming is the warp-preparation stage (yarn/jute-cloth laid onto warp
-- beams in 'cuts' for weaving). This script creates the 3 ACTIVE beaming tables:
--   1. jute_prod_bm_quality        — item -> bm_quality master (ends, std_count)   (SPEC §A.3)
--   2. jute_prod_beaming_target_map — effective-dated machine-linked standards/targets (SPEC §B.3)
--   3. jute_prod_beaming_daily      — daily per-machine/per-quality production snapshot (SPEC §C.3)
-- Run AFTER create_beaming_item_type_and_machine_type.sql + seed_beaming_menu.sql.
--
-- The composite-warp detail table (jute_prod_bm_quality_dtl, SPEC §A.4) is DEFERRED
-- and kept here as a COMMENTED-OUT future block — do NOT create it active.

-- 1. Beaming Quality Master (SPEC §A.3) — item -> bm_quality (ends, std_count).
CREATE TABLE jute_prod_bm_quality (
    bm_quality_id     INT          NOT NULL AUTO_INCREMENT,
    co_id             INT          NOT NULL,
    branch_id         INT          NULL,
    item_id           INT          NOT NULL,
    bm_quality_code   VARCHAR(50)  NOT NULL,
    bm_quality_name   VARCHAR(100) NULL,
    ends              INT          NOT NULL,
    std_count         DECIMAL(10,3) NOT NULL,            -- from jute_yarn_mst.jute_yarn_count (§A.8)
    yarn_item_id      INT          NULL,                 -- linked jute yarn supplying the count (§A.8)
    is_composite      TINYINT      NOT NULL DEFAULT 0,   -- 1 = multi-component warp; needs _dtl; entry blocked till then
    active            TINYINT      NOT NULL DEFAULT 1,
    updated_by        INT          NULL,
    updated_date_time TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (bm_quality_id),
    KEY idx_bmq_co_item (co_id, item_id),
    CONSTRAINT fk_bmq_item FOREIGN KEY (item_id) REFERENCES item_mst (item_id)
);

-- 2. Beaming Standards / Targets Map (SPEC §B.3) — effective-dated machine-linked params.
CREATE TABLE jute_prod_beaming_target_map (
    beaming_target_map_id INT          NOT NULL AUTO_INCREMENT,
    co_id                 INT          NOT NULL,
    branch_id             INT          NULL,
    effective_date        DATE         NOT NULL,
    ref_id                INT          NOT NULL,
    id_type               VARCHAR(8)   NOT NULL,   -- 'mcid'
    value_role            VARCHAR(10)  NOT NULL,   -- 'standard' | 'target'
    param                 VARCHAR(20)  NOT NULL,   -- laid_length | cuts_per_beam | speed | eff
    value                 DECIMAL(12,4) NOT NULL DEFAULT 0.0000,
    active                TINYINT      NOT NULL DEFAULT 1,
    updated_by            INT          NULL,
    updated_date_time     TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (beaming_target_map_id),
    KEY idx_btm_lookup (co_id, ref_id, id_type, value_role, param, effective_date),
    KEY idx_btm_co (co_id)
);

-- 3. Beaming Production Entry (SPEC §C.3) — daily per-machine/per-quality snapshot.
CREATE TABLE jute_prod_beaming_daily (
    beaming_daily_id   INT NOT NULL AUTO_INCREMENT,
    co_id              INT NOT NULL,
    branch_id          INT NULL,
    tran_date          DATE NOT NULL,
    spell_id           INT NOT NULL,
    machine_id         INT NOT NULL,
    item_id            INT NOT NULL,
    bm_quality_id      INT NOT NULL,
    eb_id              INT NULL,
    act_cuts           INT NOT NULL,
    no_of_beam         INT NOT NULL,
    rpm_roller         DECIMAL(10,3) NULL,
    dia_roller         DECIMAL(10,3) NULL,
    ends               INT NULL,
    std_count          DECIMAL(10,3) NULL,
    act_count          DECIMAL(10,3) NULL,
    laid_length        DECIMAL(12,4) NULL,
    std_cuts_per_beam  DECIMAL(10,3) NULL,
    std_speed          DECIMAL(12,4) NULL,
    target_speed       DECIMAL(12,4) NULL,
    act_speed          DECIMAL(12,4) NULL,
    std_eff            DECIMAL(6,2)  NULL,
    target_eff         DECIMAL(6,2)  NULL,
    working_hours      DECIMAL(5,2)  NULL,
    yards_per_beam     DECIMAL(14,4) NULL,
    kg_per_cut         DECIMAL(14,6) NULL,
    kg_per_beam        DECIMAL(14,4) NULL,
    p100prod           DECIMAL(14,3) NULL,
    std_prod           DECIMAL(14,3) NULL,
    target_prod        DECIMAL(14,3) NULL,
    act_prod_kg        DECIMAL(14,3) NULL,
    act_prod_yards     DECIMAL(14,3) NULL,
    act_eff            DECIMAL(6,2)  NULL,
    active             TINYINT NOT NULL DEFAULT 1,
    updated_by         INT NULL,
    updated_date_time  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (beaming_daily_id),
    KEY idx_bd_co_branch_date (co_id, branch_id, tran_date),
    KEY idx_bd_key (co_id, tran_date, spell_id, machine_id, item_id, bm_quality_id),
    CONSTRAINT fk_bd_machine FOREIGN KEY (machine_id) REFERENCES machine_mst (machine_id),
    CONSTRAINT fk_bd_spell   FOREIGN KEY (spell_id)   REFERENCES spell_mst   (spell_id),
    CONSTRAINT fk_bd_quality FOREIGN KEY (bm_quality_id) REFERENCES jute_prod_bm_quality (bm_quality_id)
);

-- =============================================================================
-- DEFERRED (FUTURE) — DO NOT CREATE: jute_prod_bm_quality_dtl (SPEC §A.4)
-- Composite-warp components for Sigma_n kg/cut (codes like 272-13/240-20/32).
-- Each child row holds a component's (ends, count) so kg_per_cut sums over all
-- components. Simple qualities (is_composite = 0) do NOT need this. Until this
-- table exists, production entry is blocked for any is_composite = 1 quality (§C.5).
-- -----------------------------------------------------------------------------
-- CREATE TABLE jute_prod_bm_quality_dtl (
--     bm_quality_dtl_id INT NOT NULL AUTO_INCREMENT,
--     bm_quality_id     INT NOT NULL,
--     component_no      INT NOT NULL,             -- 1,2,...
--     ends              INT NOT NULL,
--     yarn_item_id      INT NULL,                 -- jute yarn supplying this component's count (§A.8)
--     count             DECIMAL(10,3) NOT NULL,   -- from jute_yarn_mst.jute_yarn_count
--     active            TINYINT NOT NULL DEFAULT 1,
--     PRIMARY KEY (bm_quality_dtl_id),
--     KEY idx_bmqd_parent (bm_quality_id),
--     CONSTRAINT fk_bmqd_parent FOREIGN KEY (bm_quality_id) REFERENCES jute_prod_bm_quality (bm_quality_id)
-- );
-- =============================================================================

-- =============================================================================
-- ROLLBACK (reverse FK order — drop the child that references jute_prod_bm_quality
-- first, then the standalone target map, then the parent quality table last):
-- DROP TABLE IF EXISTS jute_prod_beaming_daily;
-- DROP TABLE IF EXISTS jute_prod_beaming_target_map;
-- DROP TABLE IF EXISTS jute_prod_bm_quality;
-- (If the deferred jute_prod_bm_quality_dtl is ever created, drop it BEFORE
--  jute_prod_bm_quality: DROP TABLE IF EXISTS jute_prod_bm_quality_dtl;)
-- =============================================================================
