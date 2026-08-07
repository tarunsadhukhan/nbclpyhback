-- Migration: R-08-24 Bag Checking SQC — finished-bag acceptance inspection.
-- Module: juteSQC. Target tenant database: dev3 (QA). Promote to other tenants later.
--
-- One save = ONE (entry_date, bag type) block = a header (date, bag type, free-text vendor
-- and id_code, and the 7 per-quality STANDARDS snapshotted at save) + N per-bag detail rows
-- (variable, >=1, up to 20 plus). Each bag carries 7 MEASURED inputs (length_cm, width_cm,
-- ends_dm, picks_dm, mr_pct, bag_wt_gm, stitch_dm) plus optional free-text defects, and one
-- server-computed value: corr_wt_gm = bag_wt_gm times (100 + std_mr_pct) over (100 + mr_pct)
-- (universal MR correction). Block aggregates (per-column avg / SAMPLE stdev / cv pct / min /
-- max plus obs and corr heavy-light percents vs std_bag_weight) are computed on read, NOT
-- stored. bag_type_label is VARCHAR(255) because real bag item names run about 150 chars;
-- vendor_name and id_code are free text (no master).
;

CREATE TABLE IF NOT EXISTS jute_sqc_bag_check (
    bag_check_id      INT NOT NULL AUTO_INCREMENT,
    co_id             INT NOT NULL,
    branch_id         INT NULL,
    entry_date        DATE NOT NULL,
    item_id           INT NULL,
    bag_type_label    VARCHAR(255) NULL,
    vendor_name       VARCHAR(120) NULL,
    id_code           VARCHAR(50) NULL,
    std_bag_weight    DECIMAL(8,2) NULL,
    std_length        DECIMAL(8,2) NULL,
    std_width         DECIMAL(8,2) NULL,
    std_ends          DECIMAL(8,2) NULL,
    std_picks         DECIMAL(8,2) NULL,
    std_stitch        DECIMAL(8,2) NULL,
    std_mr_pct        DECIMAL(5,2) NULL,
    active            INT NOT NULL DEFAULT 1,
    updated_by        INT NULL,
    updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (bag_check_id),
    INDEX idx_jute_sqc_bag_check_co_id (co_id),
    INDEX idx_jute_sqc_bag_check_entry_date (entry_date)
);

CREATE TABLE IF NOT EXISTS jute_sqc_bag_check_dtl (
    bag_check_dtl_id INT NOT NULL AUTO_INCREMENT,
    bag_check_id     INT NOT NULL,
    sl_no            INT NULL,
    length_cm        DECIMAL(8,2) NULL,
    width_cm         DECIMAL(8,2) NULL,
    ends_dm          DECIMAL(8,2) NULL,
    picks_dm         DECIMAL(8,2) NULL,
    mr_pct           DECIMAL(6,2) NULL,
    bag_wt_gm        DECIMAL(8,2) NULL,
    stitch_dm        DECIMAL(6,2) NULL,
    defects          VARCHAR(200) NULL,
    corr_wt_gm       DECIMAL(8,2) NULL,
    PRIMARY KEY (bag_check_dtl_id),
    INDEX idx_jute_sqc_bag_check_dtl_hdr (bag_check_id)
);

-- Rollback:
-- DROP TABLE jute_sqc_bag_check_dtl
-- DROP TABLE jute_sqc_bag_check
