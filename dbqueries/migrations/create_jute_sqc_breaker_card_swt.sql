-- Migration: Create jute_sqc_breaker_card_swt — R-08-05/06/07 Breaker Card (Coarse Side SWT)
-- Module: juteSQC (R-08-05/06/07 Breaker Card, carding stage)
-- Date: 2026-06-27
-- Applies to: tenant database dev3 (QA). Promote to other tenants later.
--
-- Flat row-per-reading-set (one save inserts SEVERAL rows — the day's grid). Mirrors
-- jute_sqc_spreader_sliver_wt: flat header + JSON-as-string readings (VARCHAR(500) +
-- json.dumps/json.loads) + persisted calc_* columns. Insert-only + compute-on-read.
-- Each row = one (machine, spell, quality) reading-set with EXACTLY 4 cut weights +
-- 4 MR%. std_mr_pct + std_cv_low/high are snapshotted from jute_draw_quality_std at
-- (item_id, process='BREAKER') save time so historic rows survive master edits; std MR
-- falls back to 16. cv_within_band is the computed pass flag (NULL when no band seeded).
-- weights are LB per 5 yds (compared directly — no count conversion). card_side defaults
-- 'COARSE' for the future fine-side variant. The per-quality GRAND AVERAGE is recomputed
-- at read from these rows — NOT stored.

CREATE TABLE IF NOT EXISTS jute_sqc_breaker_card_swt (
    breaker_card_swt_id INT           NOT NULL AUTO_INCREMENT,
    co_id               INT           NOT NULL,
    branch_id           INT           NULL,
    entry_date          DATE          NOT NULL,
    mc_id               INT           NULL,
    spell_id            INT           NULL,
    item_id             INT           NULL,
    batch_plan_id       BIGINT        NULL,
    card_side           VARCHAR(10)   NULL DEFAULT 'COARSE',
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
    PRIMARY KEY (breaker_card_swt_id),
    INDEX idx_jbcsw_co_id (co_id),
    INDEX idx_jbcsw_entry_date (entry_date),
    INDEX idx_jbcsw_co_entry_date (co_id, entry_date),
    INDEX idx_jbcsw_mc_id (mc_id),
    INDEX idx_jbcsw_item_id (item_id),
    INDEX idx_jbcsw_batch_plan_id (batch_plan_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- NOTE: batch_plan_id is the carding quality linkage (a jute_batch_plan batch, not a single
-- line quality). FRESH tenants get it here. dev3 + tenants created BEFORE 2026-06-27 got it via
-- the follow-on add_batch_plan_id_to_breaker_card_swt.sql ALTER — SKIP that ALTER on fresh
-- tenants (this CREATE already includes the column + index).

-- Rollback:
-- DROP TABLE IF EXISTS jute_sqc_breaker_card_swt;
