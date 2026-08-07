-- Migration: R-08-19 Fabric Construction SQC — woven hessian cloth construction audit.
-- Module: juteSQC. Target tenant database: dev3 (QA). Promote to other tenants later.
--
-- One save = ONE quality block = a header (date, cloth quality, its 6 std values) + up to 5
-- sample rows. Each sample row carries 6 MEASURED inputs plus 2 server-computed values:
--   obs_ozs   = (obs_wt_kg * 1000 / 28.3495) / length_yds        (oz per yard)
--   crcted_oz = obs_ozs * (100 + std_mr_pct) / (100 + mr_pct)    (universal MR correction)
-- The 6 per-quality STANDARDS are snapshotted on the header at save (std_mr_pct prefills 16 for
-- hessian, all editable). by_date summary (per-column AVG + Std-vs-Actual deviation) computed on read.

CREATE TABLE IF NOT EXISTS jute_sqc_fabric_construction (
    fabric_const_id   INT NOT NULL AUTO_INCREMENT,
    co_id             INT NOT NULL,
    branch_id         INT NULL,
    entry_date        DATE NOT NULL,
    item_id           INT NULL,
    quality_text      VARCHAR(150) NULL,
    std_length_yds    DECIMAL(10,2) NULL,
    std_width_cms     DECIMAL(10,2) NULL,
    std_ends_dm       DECIMAL(10,2) NULL,
    std_picks_dm      DECIMAL(10,2) NULL,
    std_mr_pct        DECIMAL(6,2) NULL,
    std_oz_per_yd     DECIMAL(10,3) NULL,
    active            INT NOT NULL DEFAULT 1,
    updated_by        INT NULL,
    updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (fabric_const_id),
    INDEX idx_jute_sqc_fabric_const_co_id (co_id),
    INDEX idx_jute_sqc_fabric_const_entry_date (entry_date)
);

CREATE TABLE IF NOT EXISTS jute_sqc_fabric_construction_dtl (
    fabric_const_dtl_id INT NOT NULL AUTO_INCREMENT,
    fabric_const_id     INT NOT NULL,
    sl                  INT NOT NULL,
    length_yds          DECIMAL(10,2) NULL,
    width_cms           DECIMAL(10,2) NULL,
    ends_per_dm         DECIMAL(10,2) NULL,
    picks_per_dm        DECIMAL(10,2) NULL,
    mr_pct              DECIMAL(6,2) NULL,
    obs_wt_kg           DECIMAL(10,3) NULL,
    obs_ozs             DECIMAL(10,3) NULL,
    crcted_oz           DECIMAL(10,3) NULL,
    PRIMARY KEY (fabric_const_dtl_id),
    INDEX idx_jute_sqc_fabric_const_dtl_hdr (fabric_const_id)
);

-- Rollback:
-- DROP TABLE jute_sqc_fabric_construction_dtl
-- DROP TABLE jute_sqc_fabric_construction
