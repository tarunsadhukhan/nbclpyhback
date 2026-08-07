-- Migration: Create jute_sqc_spreader_roll_wt — R-08-04 Spreader Roll Weight entries
-- Module: juteSQC (R-08-04 Spreader Roll Weight)
-- Date: 2026-06-26
--
-- Morrah-shaped: flat header + JSON-as-string readings (VARCHAR(500) +
-- json.dumps/json.loads, matching jute_sqc_morrah_wt) + persisted calc_*/band
-- columns. Insert-only + compute-on-read. std_mr_pct and band edges are
-- snapshotted onto the saved row at save time so historic rows survive master
-- edits.

CREATE TABLE IF NOT EXISTS jute_sqc_spreader_roll_wt (
    spreader_roll_wt_id INT           NOT NULL AUTO_INCREMENT,
    co_id               INT           NOT NULL,
    branch_id           INT           NULL,
    entry_date          DATE          NOT NULL,
    spell_id            INT           NULL,
    mc_id               INT           NULL,
    item_id             INT           NULL,
    feeder_name         VARCHAR(255)  NULL,
    roll_weights        VARCHAR(500)  NOT NULL,
    mr_pcts             VARCHAR(500)  NOT NULL,
    std_mr_pct          DECIMAL(5,2)  NULL,
    calc_avg_mr_pct     DECIMAL(5,2)  NULL,
    calc_avg_obs        DECIMAL(10,3) NULL,
    calc_avg_corr       DECIMAL(10,3) NULL,
    calc_stdev_obs      DECIMAL(10,4) NULL,
    calc_stdev_corr     DECIMAL(10,4) NULL,
    calc_cv_pct         DECIMAL(7,4)  NULL,
    band_counts_obs     VARCHAR(500)  NULL,
    band_counts_corr    VARCHAR(500)  NULL,
    active              INT           NOT NULL DEFAULT 1,
    updated_by          INT           NULL,
    updated_date_time   TIMESTAMP     NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (spreader_roll_wt_id),
    INDEX idx_jsrw_co_id (co_id),
    INDEX idx_jsrw_entry_date (entry_date),
    INDEX idx_jsrw_co_entry_date (co_id, entry_date),
    INDEX idx_jsrw_mc_id (mc_id),
    INDEX idx_jsrw_item_id (item_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Rollback:
-- DROP TABLE IF EXISTS jute_sqc_spreader_roll_wt;
