-- Migration: Create jute_sqc_draw_sliver_wt — R-08-08/09/10 Drawhead + Finisher Card Sliver Wt
-- Module: juteSQC (R-08-08/09/10, drawing stage — drawhead SWT/SWP + finisher card sliver)
-- Date: 2026-06-27
-- Applies to: tenant database dev3 (QA). Promote to other tenants later.
--
-- Clone of jute_sqc_card_sliver_wt with ONE extra column: time_band (MORNING / AFTERNOON sheet
-- header, NULLABLE). Same multi-row 4-cut batch-linked sliver-weight shape; rows split into
-- three sections (DRAWHEAD_SWT / DRAWHEAD_SWP / FINISHER_CARD). Quality is linked to a BATCH
-- (jute_batch_plan, a named mix of raw-jute qualities) rather than a single line quality, so
-- the std satellite is NOT consulted: std_mr_pct is fixed at the DRAWING default 16 and
-- std_cv_low/high stay NULL, leaving cv_within_band NULL (band unevaluated). The machine picker
-- is the shared carding/drawing pool (all active branch machines); the operator picks the
-- section + time-band. weights are LB per 5 yds. Insert-only + compute-on-read. Section AVG +
-- per-batch GRAND AVERAGE are recomputed at read from these rows — NOT stored.

CREATE TABLE IF NOT EXISTS jute_sqc_draw_sliver_wt (
    draw_sliver_wt_id  INT           NOT NULL AUTO_INCREMENT,
    co_id              INT           NOT NULL,
    branch_id          INT           NULL,
    entry_date         DATE          NOT NULL,
    section            VARCHAR(20)   NOT NULL,
    time_band          VARCHAR(20)   NULL,
    mc_id              INT           NULL,
    spell_id           INT           NULL,
    batch_plan_id      BIGINT        NULL,
    weights            VARCHAR(500)  NOT NULL,
    mr_pcts            VARCHAR(500)  NOT NULL,
    std_mr_pct         DECIMAL(5,2)  NULL,
    std_cv_low         DECIMAL(5,2)  NULL,
    std_cv_high        DECIMAL(5,2)  NULL,
    calc_wt            DECIMAL(10,3) NULL,
    calc_mr_pct        DECIMAL(5,2)  NULL,
    calc_corr_wt       DECIMAL(10,3) NULL,
    calc_sdev          DECIMAL(10,4) NULL,
    calc_cv_pct        DECIMAL(7,4)  NULL,
    cv_within_band     INT           NULL,
    active             INT           NOT NULL DEFAULT 1,
    updated_by         INT           NULL,
    updated_date_time  TIMESTAMP     NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (draw_sliver_wt_id),
    INDEX idx_jdsw_co_id (co_id),
    INDEX idx_jdsw_entry_date (entry_date),
    INDEX idx_jdsw_co_entry_date (co_id, entry_date),
    INDEX idx_jdsw_section (section),
    INDEX idx_jdsw_mc_id (mc_id),
    INDEX idx_jdsw_batch_plan_id (batch_plan_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- NOTE: time_band labels the AM/PM sheet column (MORNING / AFTERNOON), nullable. batch_plan_id
-- is the drawing quality linkage (a jute_batch_plan batch, not a single line quality). This
-- CREATE already includes both columns + indexes.

-- Rollback:
-- DROP TABLE IF EXISTS jute_sqc_draw_sliver_wt;
