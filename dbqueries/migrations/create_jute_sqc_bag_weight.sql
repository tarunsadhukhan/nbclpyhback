-- Migration: R-08-23 Bag Weight SQC table (jute_sqc_bag_weight)
-- Module: juteSQC (finished-bag weight control)
-- Date: 2026-06-28
-- Applies to: tenant database dev3 (QA). Promote to other tenants later.
--
-- Flat single-table morrah pattern (NO detail table). One row per (entry_date, bag
-- type) block carries N reading rows as a JSON-string array of objects {mr, obs}
-- (readings VARCHAR(2000), json.dumps / json.loads). Up to 24 rows, variable (>=1).
-- std_bag_weight + std_mr_pct entered on the form (std_mr_pct prefills 20 for jute
-- bags, editable) and snapshotted here. Per-row corr = obs * (100 + std_mr_pct) /
-- (100 + mr). Block stats (avg_mr / avg_obs / avg_corr row-wise / sample stdev of
-- obs / cv_pct / heavy-light percents) are computed at save and stored. Bag type =
-- JUTE CLOTH item (item_type_id=5), nullable.
--
-- NOTE the documented migration runner splits on the statement terminator so
-- comment lines carry NO semicolons.
;

CREATE TABLE jute_sqc_bag_weight (
    bag_weight_id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    co_id INT NOT NULL,
    branch_id INT NULL,
    entry_date DATE NOT NULL,
    item_id INT NULL,
    bag_type_label VARCHAR(255) NULL,
    std_bag_weight DECIMAL(8,2) NULL,
    std_mr_pct DECIMAL(5,2) NULL,
    readings VARCHAR(2000) NOT NULL,
    calc_avg_mr DECIMAL(6,3) NULL,
    calc_avg_obs_wt DECIMAL(8,2) NULL,
    calc_avg_corr_wt DECIMAL(8,2) NULL,
    calc_obs_stdev DECIMAL(8,3) NULL,
    calc_obs_cv_pct DECIMAL(6,2) NULL,
    calc_obs_hy_lt_pct DECIMAL(6,2) NULL,
    calc_corr_hy_lt_pct DECIMAL(6,2) NULL,
    active INT NOT NULL DEFAULT 1,
    updated_by INT NULL,
    updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_bag_weight_co_id (co_id),
    INDEX idx_bag_weight_entry_date (entry_date)
);

-- Rollback:
-- DROP TABLE jute_sqc_bag_weight
