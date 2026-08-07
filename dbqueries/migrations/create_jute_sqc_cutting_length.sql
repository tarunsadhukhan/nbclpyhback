-- Migration: R-08-20 Cutting Length SQC table (jute_sqc_cutting_length)
-- Module: juteSQC (daily cut-piece length consistency)
-- Date: 2026-06-28
-- Applies to: tenant database dev3 (QA). Promote to other tenants later.
--
-- Flat single-table morrah pattern (NO detail table). One row per (entry_date)
-- reading-set carries EXACTLY 20 cut-length readings in inches as a JSON-string
-- array (readings VARCHAR(500), json.dumps / json.loads). std_length is entered
-- on the form (prefilled 78, editable) and snapshotted here. avg / sample stdev
-- (n-1) / cv_pct / deviation are computed at save and stored. Optional cloth
-- quality link = JUTE CLOTH item (item_type_id=5), nullable.
--
-- NOTE the documented migration runner splits on the statement terminator so
-- comment lines carry NO semicolons.

CREATE TABLE jute_sqc_cutting_length (
    cutting_length_id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    co_id INT NOT NULL,
    branch_id INT NULL,
    entry_date DATE NOT NULL,
    item_id INT NULL,
    std_length DECIMAL(10,2) NOT NULL,
    readings VARCHAR(500) NOT NULL,
    calc_avg DECIMAL(10,3) NULL,
    calc_stdev DECIMAL(10,4) NULL,
    calc_cv_pct DECIMAL(10,4) NULL,
    calc_deviation DECIMAL(10,3) NULL,
    active INT NOT NULL DEFAULT 1,
    updated_by INT NULL,
    updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_cutting_length_co_id (co_id),
    INDEX idx_cutting_length_entry_date (entry_date)
);

-- Rollback:
-- DROP TABLE jute_sqc_cutting_length
