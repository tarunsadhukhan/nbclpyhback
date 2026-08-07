-- Migration: Create jute_sqc_card_sliver_wt — R-08-07A Inter Card & Tow Breaker Sliver Weight
-- Module: juteSQC (R-08-07A, carding stage — inter-card / tow-breaker / hopper sliver)
-- Date: 2026-06-27
-- Applies to: tenant database dev3 (QA). Promote to other tenants later.
--
-- Clone of jute_sqc_breaker_card_swt with ONE delta: card_side -> section. R-08-07A is the
-- same multi-row 4-cut sliver-weight shape, but its rows split into three sub-sections
-- (INTER_CARD / TOW_BREAKER / HOPPER). `section` is BOTH the stored sub-table label AND the
-- (item_id, process) key into jute_draw_quality_std — the SAME line quality carries a
-- different STD MR%/CV band per carding sub-process. No new machine type is seeded: the
-- machine picker is the shared carding pool (all active branch machines); the operator picks
-- the section. std_mr_pct + std_cv_low/high are snapshotted from jute_draw_quality_std at
-- (item_id, process=section) save time; std MR falls back to 20 (owner decision — the
-- universal Sacking std; per-quality satellite rows override it). cv_within_band is the
-- computed pass flag (NULL when no band seeded). weights are LB per 5 yds (compared directly).
-- Insert-only + compute-on-read. Section AVG + per-quality GRAND AVERAGE are recomputed at
-- read from these rows — NOT stored.

CREATE TABLE IF NOT EXISTS jute_sqc_card_sliver_wt (
    card_sliver_wt_id   INT           NOT NULL AUTO_INCREMENT,
    co_id               INT           NOT NULL,
    branch_id           INT           NULL,
    entry_date          DATE          NOT NULL,
    section             VARCHAR(20)   NOT NULL,
    mc_id               INT           NULL,
    spell_id            INT           NULL,
    item_id             INT           NULL,
    batch_plan_id       BIGINT        NULL,
    weights             VARCHAR(500)  NOT NULL,
    mr_pcts             VARCHAR(500)  NOT NULL,
    std_mr_pct          DECIMAL(5,2)  NULL,
    std_cv_low          DECIMAL(5,2)  NULL,
    std_cv_high         DECIMAL(5,2)  NULL,
    calc_wt             DECIMAL(10,3) NULL,
    calc_mr_pct         DECIMAL(5,2)  NULL,
    calc_corr_wt        DECIMAL(10,3) NULL,
    calc_sdev           DECIMAL(10,4) NULL,
    calc_cv_pct         DECIMAL(7,4)  NULL,
    cv_within_band      INT           NULL,
    active              INT           NOT NULL DEFAULT 1,
    updated_by          INT           NULL,
    updated_date_time   TIMESTAMP     NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (card_sliver_wt_id),
    INDEX idx_jcsw_co_id (co_id),
    INDEX idx_jcsw_entry_date (entry_date),
    INDEX idx_jcsw_co_entry_date (co_id, entry_date),
    INDEX idx_jcsw_section (section),
    INDEX idx_jcsw_mc_id (mc_id),
    INDEX idx_jcsw_item_id (item_id),
    INDEX idx_jcsw_batch_plan_id (batch_plan_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- NOTE: batch_plan_id is the carding/drawing quality linkage (a jute_batch_plan batch, not a
-- single line quality). FRESH tenants get it here. dev3 + any tenant created BEFORE 2026-06-27
-- got it via the follow-on add_batch_plan_id_to_card_sliver_wt.sql ALTER — SKIP that ALTER on
-- fresh tenants (this CREATE already includes the column + index).

-- Rollback:
-- DROP TABLE IF EXISTS jute_sqc_card_sliver_wt;
