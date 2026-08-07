-- Migration: Create jute_sqc_morrah_wt table for Morrah Weight QC
-- Module: juteSQC (r-08-01)
-- Date: 2026-02-24

CREATE TABLE IF NOT EXISTS jute_sqc_morrah_wt (
    morrah_wt_id      INT           NOT NULL AUTO_INCREMENT,
    co_id             INT           NOT NULL,
    branch_id         INT           NOT NULL,
    entry_date        DATE          NOT NULL,
    inspector_name    VARCHAR(100)  NULL,
    dept_id           INT           NULL,
    item_id           INT           NULL,
    trolley_no        VARCHAR(50)   NULL,
    avg_mr_pct        DOUBLE        NULL,
    weights           JSON          NOT NULL,
    calc_avg_weight   DOUBLE        NULL,
    calc_max_weight   INT           NULL,
    calc_min_weight   INT           NULL,
    calc_range        INT           NULL,
    calc_cv_pct       DOUBLE        NULL,
    count_lt          INT           NULL,
    count_ok          INT           NULL,
    count_hy          INT           NULL,
    active            INT           NOT NULL DEFAULT 1,
    updated_by        INT           NULL,
    updated_date_time DATETIME      DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (morrah_wt_id),
    INDEX idx_morrah_wt_co_id (co_id),
    INDEX idx_morrah_wt_branch_id (branch_id),
    INDEX idx_morrah_wt_entry_date (entry_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Rollback:
-- DROP TABLE IF EXISTS jute_sqc_morrah_wt;
