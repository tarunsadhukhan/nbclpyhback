-- Migration: R-08-21 Width and Picks SQC (on-loom dimensional QC of woven cloth)
-- Module: juteSQC
-- Date: 2026-06-28
-- Applies to: tenant database dev3 (QA). Promote to other tenants later.
--
-- Header plus detail. ONE save = ONE (entry_date, cloth-quality) group:
--   jute_sqc_width_picks      header: entry_date, cloth quality, std_width_cm,
--                             std_picks snapshotted at save (NO change to item master),
--                             optional inspector_name.
--   jute_sqc_width_picks_dtl  N loom reading rows: loom machine, width_cm (required),
--                             picks_dm (optional, only a sampled subset of looms checked).
-- Width and Picks summaries are computed on read, NOT stored.
;

CREATE TABLE IF NOT EXISTS jute_sqc_width_picks (
    width_picks_id INT NOT NULL AUTO_INCREMENT,
    co_id INT NOT NULL,
    branch_id INT NULL,
    entry_date DATE NOT NULL,
    item_id INT NULL,
    std_width_cm DECIMAL(6,2) NULL,
    std_picks DECIMAL(6,2) NULL,
    inspector_name VARCHAR(120) NULL,
    active INT NOT NULL DEFAULT 1,
    updated_by INT NULL,
    updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (width_picks_id),
    INDEX idx_width_picks_co_id (co_id),
    INDEX idx_width_picks_entry_date (entry_date)
);

CREATE TABLE IF NOT EXISTS jute_sqc_width_picks_dtl (
    width_picks_dtl_id INT NOT NULL AUTO_INCREMENT,
    width_picks_id INT NOT NULL,
    loom_id INT NULL,
    width_cm DECIMAL(6,2) NULL,
    picks_dm DECIMAL(6,2) NULL,
    PRIMARY KEY (width_picks_dtl_id),
    INDEX idx_width_picks_dtl_hdr (width_picks_id)
);

-- Rollback (run the two statements below manually, removing the comment dashes):
-- DROP TABLE jute_sqc_width_picks_dtl
-- DROP TABLE jute_sqc_width_picks
