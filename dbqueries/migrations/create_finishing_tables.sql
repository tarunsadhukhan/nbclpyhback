-- Migration: Finishing production tables — Finishing Quality Master, Spec Sheet
--            (Standards/Targets Map), and daily Production Entry (per SPEC §4.1–§4.3).
-- Date: 2026-06-23
-- Applies to: tenant database dev3 (QA). Promote to other tenants later.
--
-- Context: Finishing is the post-weaving line that turns grey cloth into hessian
-- cloth (rolls) and jute bags (bales) across SIX sub-processes — Damping,
-- Calendering, Lapping, Cutting, Hemming, Bale Press. This script creates the 4
-- ACTIVE finishing tables (mirroring the Beaming pattern, plus ONE new dimension
-- `process`):
--   1. jute_prod_finishing_quality     — cloth & bag qualities (+ fixed structural specs) (SPEC §4.1)
--   2. jute_prod_finishing_target_map  — effective-dated spec sheet; adds a `process` column
--                                         and an index that LEADS with process            (SPEC §4.2)
--   3. jute_prod_finishing_daily        — daily per-process/per-machine/per-quality snapshot (SPEC §4.3)
--   4. jute_prod_finishing_daily_param  — process-specific captured params (EAV child)      (SPEC §4.3)
-- Run AFTER create_finishing_machine_types.sql + seed_finishing_menu.sql.
--
-- Conventions match create_beaming_tables.sql: co_id + branch_id scoping, soft-delete
-- (active TINYINT DEFAULT 1), audit cols updated_by + updated_date_time (triggers handle
-- the rest — NO created_*). Target tenant dev3 first.

-- 1. Finishing Quality Master (SPEC §4.1) — cloth (quality_type=1) & bag (quality_type=2)
--    qualities. Type-specific columns are nullable; bag rows reference a cloth quality
--    via cloth_quality_id (self-FK).
CREATE TABLE jute_prod_finishing_quality (
    finishing_quality_id   INT          NOT NULL AUTO_INCREMENT,
    co_id                  INT          NOT NULL,
    branch_id              INT          NULL,
    quality_type           TINYINT      NOT NULL,            -- 1=cloth, 2=bag
    item_id                INT          NOT NULL,            -- finished item (cloth roll / bag) in item_mst
    fin_quality_code       VARCHAR(50)  NOT NULL,
    fin_quality_name       VARCHAR(100) NULL,
    -- cloth structural specs (quality_type=1) --------------------------------
    width_in               DECIMAL(10,3) NULL,               -- finished cloth width (inches)
    ports                  INT          NULL,                -- ends per dent / porter
    ends                   INT          NULL,                -- total warp ends
    shots                  DECIMAL(10,3) NULL,               -- picks per inch (weft)
    oz_per_yd              DECIMAL(10,3) NULL,               -- weight per linear yard (oz)
    std_oz_per_yd          DECIMAL(10,3) NULL,               -- reference/standard oz/yd
    lead_length            DECIMAL(12,4) NULL,               -- warp lead length
    finished_length        DECIMAL(12,4) NULL,               -- standard cut/roll length
    mc_teeth               INT          NULL,
    -- bag structural specs (quality_type=2) ----------------------------------
    cloth_quality_id       INT          NULL,                -- cloth quality the bag is made from (self-FK)
    bag_length_in          DECIMAL(10,3) NULL,
    bag_width_in           DECIMAL(10,3) NULL,
    mouth_type             VARCHAR(30)  NULL,                -- open / hemmed / B.Twill / overhead
    bags_per_bale          INT          NULL,
    active                 TINYINT      NOT NULL DEFAULT 1,
    updated_by             INT          NULL,
    updated_date_time      TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (finishing_quality_id),
    KEY idx_fq_co_item (co_id, item_id),
    KEY idx_fq_type (co_id, quality_type),
    CONSTRAINT fk_fq_item FOREIGN KEY (item_id) REFERENCES item_mst (item_id)
);

-- 2. Finishing Spec Sheet (SPEC §4.2) — effective-dated EAV standards/targets/actuals,
--    one row per (process, ref_id, id_type, value_role, param, effective_date). The
--    lookup index LEADS with process (the new finishing dimension).
CREATE TABLE jute_prod_finishing_target_map (
    finishing_target_map_id INT          NOT NULL AUTO_INCREMENT,
    co_id                   INT          NOT NULL,
    branch_id               INT          NULL,
    process                 VARCHAR(20)  NOT NULL,   -- damping|calendering|lapping|cutting|hemming|balepress
    effective_date          DATE         NOT NULL,
    ref_id                  INT          NOT NULL,   -- machine_id (mcid) | finishing_quality_id (qid)
    id_type                 VARCHAR(8)   NOT NULL,   -- 'mcid' | 'qid'
    value_role              VARCHAR(10)  NOT NULL,   -- 'standard' | 'target' | 'actual'
    param                   VARCHAR(24)  NOT NULL,   -- see SPEC §5 matrix
    value                   DECIMAL(12,4) NOT NULL DEFAULT 0.0000,
    active                  TINYINT      NOT NULL DEFAULT 1,
    updated_by              INT          NULL,
    updated_date_time       TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (finishing_target_map_id),
    KEY idx_ftm_lookup (co_id, process, ref_id, id_type, value_role, param, effective_date),
    KEY idx_ftm_co (co_id)
);

-- 3. Finishing Production Entry (SPEC §4.3) — daily per-process/per-machine/per-quality
--    snapshot. Universal production/efficiency columns are typed here; process-specific
--    captured params live in the EAV child (table 4).
CREATE TABLE jute_prod_finishing_daily (
    finishing_daily_id     INT NOT NULL AUTO_INCREMENT,
    co_id                  INT NOT NULL,
    branch_id              INT NULL,
    tran_date              DATE NOT NULL,
    spell_id               INT NOT NULL,
    process                VARCHAR(20) NOT NULL,           -- which sub-process
    machine_id             INT NOT NULL,
    finishing_quality_id   INT NOT NULL,
    eb_id                  INT NULL,                        -- worker (labour-based stages)
    -- inputs / outputs (UoM depends on process; see SPEC §5) ------------------
    input_qty              DECIMAL(14,4) NULL,             -- e.g. cloth metres in / pieces in
    input_uom              VARCHAR(10)  NULL,              -- 'm' | 'pcs' | 'bag'
    prod_qty               DECIMAL(14,4) NOT NULL,         -- output (m / rolls / pcs / bags / bales)
    prod_uom               VARCHAR(10)  NOT NULL,          -- 'm' | 'roll' | 'pcs' | 'bag' | 'bale'
    prod_wt_kg             DECIMAL(14,3) NULL,             -- output weight (cloth stages)
    wastage_kg             DECIMAL(14,3) NULL,             -- net wastage (gross-tare resolved on entry)
    -- resolved standards snapshot (from spec sheet at save) ------------------
    std_speed              DECIMAL(12,4) NULL,
    target_speed           DECIMAL(12,4) NULL,
    act_speed              DECIMAL(12,4) NULL,
    std_eff                DECIMAL(6,2)  NULL,
    target_eff             DECIMAL(6,2)  NULL,
    working_hours          DECIMAL(5,2)  NULL,
    -- computed outputs (snapshot) -------------------------------------------
    p100prod               DECIMAL(14,3) NULL,             -- 100% production for the period
    std_prod               DECIMAL(14,3) NULL,
    target_prod            DECIMAL(14,3) NULL,
    act_eff                DECIMAL(6,2)  NULL,             -- prod_qty / p100prod × 100
    active                 TINYINT NOT NULL DEFAULT 1,
    updated_by             INT NULL,
    updated_date_time      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (finishing_daily_id),
    KEY idx_fd_co_branch_date (co_id, branch_id, tran_date),
    KEY idx_fd_key (co_id, tran_date, spell_id, process, machine_id, finishing_quality_id),
    CONSTRAINT fk_fd_machine FOREIGN KEY (machine_id) REFERENCES machine_mst (machine_id),
    CONSTRAINT fk_fd_spell   FOREIGN KEY (spell_id)   REFERENCES spell_mst   (spell_id),
    CONSTRAINT fk_fd_quality FOREIGN KEY (finishing_quality_id) REFERENCES jute_prod_finishing_quality (finishing_quality_id)
);

-- 4. Finishing Production Entry — process-specific captured params (SPEC §4.3, EAV child).
CREATE TABLE jute_prod_finishing_daily_param (
    finishing_daily_param_id INT NOT NULL AUTO_INCREMENT,
    finishing_daily_id       INT NOT NULL,
    param                    VARCHAR(24) NOT NULL,   -- e.g. bowl_temp, nip_pressure, lap_length, cut_length…
    value                    DECIMAL(14,4) NULL,
    active                   TINYINT NOT NULL DEFAULT 1,
    PRIMARY KEY (finishing_daily_param_id),
    KEY idx_fdp_parent (finishing_daily_id),
    CONSTRAINT fk_fdp_parent FOREIGN KEY (finishing_daily_id)
        REFERENCES jute_prod_finishing_daily (finishing_daily_id)
);

-- =============================================================================
-- ROLLBACK (reverse FK order — drop the EAV child first, then the daily snapshot,
-- then the standalone spec-sheet map, then the parent quality table last):
-- DROP TABLE IF EXISTS jute_prod_finishing_daily_param;
-- DROP TABLE IF EXISTS jute_prod_finishing_daily;
-- DROP TABLE IF EXISTS jute_prod_finishing_target_map;
-- DROP TABLE IF EXISTS jute_prod_finishing_quality;
-- =============================================================================
