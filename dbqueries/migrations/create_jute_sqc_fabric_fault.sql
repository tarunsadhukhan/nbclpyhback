-- Migration: R-08-28 Fabric Fault SQC — weaving woven-cloth defect tally.
-- Module: juteSQC. Target tenant database: dev3 (QA). Promote to other tenants later.
--
-- ONE save = ONE inspected piece (one loom/cloth column): a flat header (entry_date,
-- spell, cloth quality, loom, date_of_weaving, remarks, inspector) plus a FIXED 15-fault
-- checklist of integer counts stored as a JSON-string array of 15 ints (most are 0). NO
-- detail table. calc_piece_total = sum of the 15 counts, computed at save. The DAY roll-up
-- (per-fault totals + scores, grand total + score) is computed on read, NOT stored.
-- spell_id / item_id / loom_id are all nullable but normally selected.
;

CREATE TABLE IF NOT EXISTS jute_sqc_fabric_fault (
    fabric_fault_id   INT NOT NULL AUTO_INCREMENT,
    co_id             INT NOT NULL,
    branch_id         INT NULL,
    entry_date        DATE NOT NULL,
    spell_id          INT NULL,
    item_id           INT NULL,
    loom_id           INT NULL,
    date_of_weaving   DATE NULL,
    fault_counts      VARCHAR(500) NOT NULL,
    calc_piece_total  INT NULL,
    remarks           VARCHAR(255) NULL,
    inspector_name    VARCHAR(120) NULL,
    active            INT NOT NULL DEFAULT 1,
    updated_by        INT NULL,
    updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (fabric_fault_id),
    INDEX idx_jute_sqc_fabric_fault_co_id (co_id),
    INDEX idx_jute_sqc_fabric_fault_entry_date (entry_date)
);

-- Rollback:
-- DROP TABLE jute_sqc_fabric_fault;
