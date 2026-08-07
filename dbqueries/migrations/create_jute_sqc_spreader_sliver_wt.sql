-- Migration: Create jute_sqc_spreader_sliver_wt — R-08-03 Spreader Roll Sliver Weight entries
-- Module: juteSQC (R-08-03 Spreader Roll Sliver Weight)
-- Date: 2026-06-27
--
-- Morrah-shaped: flat header + JSON-as-string readings (VARCHAR(500) +
-- json.dumps/json.loads, matching jute_sqc_morrah_wt / jute_sqc_spreader_roll_wt)
-- + persisted calc_* columns. Insert-only + compute-on-read. std_mr_pct is
-- snapshotted onto the saved row at save time so historic rows survive master
-- edits. Variable 1-12 readings (observed_weights / mr_pcts parallel JSON);
-- NO weight bands. Units are lb/100yds; sample_length_yds (default 5) and
-- weight_basis ("LB/100YDS") are nullable header constants. category is
-- nullable free-text (no master).

CREATE TABLE IF NOT EXISTS jute_sqc_spreader_sliver_wt (
    spreader_sliver_wt_id INT           NOT NULL AUTO_INCREMENT,
    co_id                 INT           NOT NULL,
    branch_id             INT           NULL,
    entry_date            DATE          NOT NULL,
    spell_id              INT           NULL,
    category              VARCHAR(100)  NULL,
    mc_id                 INT           NULL,
    item_id               INT           NULL,
    sample_length_yds     DECIMAL(5,2)  NULL,
    weight_basis          VARCHAR(20)   NULL,
    observed_weights      VARCHAR(500)  NOT NULL,
    mr_pcts               VARCHAR(500)  NOT NULL,
    std_mr_pct            DECIMAL(5,2)  NULL,
    calc_avg_obs          DECIMAL(10,3) NULL,
    calc_avg_corr         DECIMAL(10,3) NULL,
    calc_avg_mr           DECIMAL(5,2)  NULL,
    calc_stdev            DECIMAL(10,4) NULL,
    calc_cv_pct           DECIMAL(7,4)  NULL,
    active                INT           NOT NULL DEFAULT 1,
    updated_by            INT           NULL,
    updated_date_time     TIMESTAMP     NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (spreader_sliver_wt_id),
    INDEX idx_jssw_co_id (co_id),
    INDEX idx_jssw_entry_date (entry_date),
    INDEX idx_jssw_co_entry_date (co_id, entry_date),
    INDEX idx_jssw_mc_id (mc_id),
    INDEX idx_jssw_item_id (item_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Rollback:
-- DROP TABLE IF EXISTS jute_sqc_spreader_sliver_wt;
