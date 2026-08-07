-- Migration: Create jute_sqc_fin_draw_sliver_wt — R-08-12/13/14 Finisher Drawing Sliver Weight
-- Module: juteSQC (R-08-12/13/14, drawing stage — HESS / SWP / SWT sliver)
-- Date: 2026-06-27
-- Applies to: tenant database dev3 (QA). Promote to other tenants later.
--
-- Clone of jute_sqc_card_sliver_wt with ONE extra column: dlv_nos (a JSON array of 4 delivery
-- numbers, ints or null). Same multi-row 4-cut batch-linked sliver-weight shape; rows split
-- into three sections (HESS / SWP / SWT). Quality is linked to a BATCH (jute_batch_plan, a
-- named mix of raw-jute qualities) rather than a single line quality, so the std satellite is
-- NOT consulted: std_mr_pct is fixed at the DRAWING default 16 and std_cv_low/high stay NULL,
-- leaving cv_within_band NULL (band unevaluated). The machine picker is the shared carding/
-- drawing pool (all active branch machines); the operator picks the section. weights are LB
-- per 5 yds (compared directly). Insert-only + compute-on-read. Section AVG + per-batch GRAND
-- AVERAGE are recomputed at read from these rows — NOT stored.

CREATE TABLE IF NOT EXISTS jute_sqc_fin_draw_sliver_wt (
    fin_draw_sliver_wt_id  INT           NOT NULL AUTO_INCREMENT,
    co_id                  INT           NOT NULL,
    branch_id              INT           NULL,
    entry_date             DATE          NOT NULL,
    section                VARCHAR(10)   NOT NULL,
    mc_id                  INT           NULL,
    spell_id               INT           NULL,
    batch_plan_id          BIGINT        NULL,
    weights                VARCHAR(500)  NOT NULL,
    mr_pcts                VARCHAR(500)  NOT NULL,
    dlv_nos                VARCHAR(500)  NULL,
    std_mr_pct             DECIMAL(5,2)  NULL,
    std_cv_low             DECIMAL(5,2)  NULL,
    std_cv_high            DECIMAL(5,2)  NULL,
    calc_wt                DECIMAL(10,3) NULL,
    calc_mr_pct            DECIMAL(5,2)  NULL,
    calc_corr_wt           DECIMAL(10,3) NULL,
    calc_sdev              DECIMAL(10,4) NULL,
    calc_cv_pct            DECIMAL(7,4)  NULL,
    cv_within_band         INT           NULL,
    active                 INT           NOT NULL DEFAULT 1,
    updated_by             INT           NULL,
    updated_date_time      TIMESTAMP     NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (fin_draw_sliver_wt_id),
    INDEX idx_jfdsw_co_id (co_id),
    INDEX idx_jfdsw_entry_date (entry_date),
    INDEX idx_jfdsw_co_entry_date (co_id, entry_date),
    INDEX idx_jfdsw_section (section),
    INDEX idx_jfdsw_mc_id (mc_id),
    INDEX idx_jfdsw_batch_plan_id (batch_plan_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- NOTE: dlv_nos is a JSON-as-string array of the 4 per-cut delivery numbers (ints or null).
-- batch_plan_id is the drawing quality linkage (a jute_batch_plan batch, not a single line
-- quality). This CREATE already includes both columns + indexes.

-- Rollback:
-- DROP TABLE IF EXISTS jute_sqc_fin_draw_sliver_wt;
