-- Migration: Create Jute Production tables (Spreader workflow)
-- Date: 2026-05-27
-- Applies to: tenant databases (e.g., dev3, sls)
--
-- Tables:
--   1. spreader_bin_mst        — bin master for spreader production
--   2. item_maturity_mst       — target maturity hours per jute/jute-waste item
--   3. spreader_machine_attr   — spreader-only attributes (wt_per_roll) extending machine_mst
--   4. spreader_prod_entry     — spreader production entries (rolls produced)
--   5. spreader_roll_issue     — roll issues (rolls dispatched downstream)
--
-- Notes:
--   - All tables tenant-scoped via co_id
--   - branch_id present (nullable) for branch-aware scoping
--   - wt_per_roll snapshotted onto spreader_prod_entry so historic rows survive master edits
--   - entry_id_grp groups production entries within a bin during a 4-hour window;
--     enforced in application code (src/juteProduction/services/spreader_rules.py),
--     NOT via DB triggers.

-- =============================================================================
-- 1. spreader_bin_mst
-- =============================================================================
CREATE TABLE IF NOT EXISTS spreader_bin_mst (
    bin_id INT AUTO_INCREMENT PRIMARY KEY,
    co_id INT NOT NULL,
    branch_id INT NULL,
    bin_code VARCHAR(50) NOT NULL,
    bin_no INT NULL,
    description VARCHAR(255) NULL,
    active TINYINT(1) NOT NULL DEFAULT 1,
    updated_by INT NULL,
    updated_date_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_bin_co_code (co_id, bin_code),
    INDEX idx_bin_co (co_id),
    INDEX idx_bin_branch (branch_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- =============================================================================
-- 2. item_maturity_mst
-- =============================================================================
CREATE TABLE IF NOT EXISTS item_maturity_mst (
    item_maturity_id INT AUTO_INCREMENT PRIMARY KEY,
    co_id INT NOT NULL,
    item_id INT NOT NULL,
    maturity_hours INT NOT NULL DEFAULT 48,
    active TINYINT(1) NOT NULL DEFAULT 1,
    updated_by INT NULL,
    updated_date_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_item_maturity_co_item (co_id, item_id),
    INDEX idx_item_maturity_co (co_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- =============================================================================
-- 3. spreader_machine_attr
-- =============================================================================
CREATE TABLE IF NOT EXISTS spreader_machine_attr (
    spreader_machine_attr_id INT AUTO_INCREMENT PRIMARY KEY,
    co_id INT NOT NULL,
    machine_id INT NOT NULL,
    wt_per_roll DECIMAL(10,3) NOT NULL DEFAULT 0.000,
    active TINYINT(1) NOT NULL DEFAULT 1,
    updated_by INT NULL,
    updated_date_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_sma_co_machine (co_id, machine_id),
    INDEX idx_sma_co (co_id),
    INDEX idx_sma_machine (machine_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- =============================================================================
-- 4. spreader_prod_entry
-- =============================================================================
CREATE TABLE IF NOT EXISTS spreader_prod_entry (
    spreader_prod_entry_id INT AUTO_INCREMENT PRIMARY KEY,
    co_id INT NOT NULL,
    branch_id INT NULL,
    entry_date DATE NOT NULL,
    entry_time INT NOT NULL,
    entry_dt DATETIME NOT NULL,
    spell CHAR(2) NOT NULL,
    machine_id INT NOT NULL,
    item_id INT NOT NULL,
    bin_id INT NOT NULL,
    trolley_no INT NULL,
    no_of_rolls INT NOT NULL,
    wt_per_roll DECIMAL(10,3) NOT NULL DEFAULT 0.000,
    entry_id_grp INT NOT NULL,
    status_id INT NULL,
    remarks VARCHAR(255) NULL,
    active TINYINT(1) NOT NULL DEFAULT 1,
    updated_by INT NULL,
    updated_date_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_spe_co (co_id),
    INDEX idx_spe_branch (branch_id),
    INDEX idx_spe_date (entry_date),
    INDEX idx_spe_dt (entry_dt),
    INDEX idx_spe_grp (entry_id_grp),
    INDEX idx_spe_bin (bin_id),
    INDEX idx_spe_machine (machine_id),
    INDEX idx_spe_item (item_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- =============================================================================
-- 5. spreader_roll_issue
-- =============================================================================
CREATE TABLE IF NOT EXISTS spreader_roll_issue (
    spreader_roll_issue_id INT AUTO_INCREMENT PRIMARY KEY,
    co_id INT NOT NULL,
    branch_id INT NULL,
    issue_date DATE NOT NULL,
    issue_time INT NOT NULL,
    issue_dt DATETIME NOT NULL,
    spell CHAR(2) NOT NULL,
    entry_id_grp INT NOT NULL,
    wt_per_roll DECIMAL(10,3) NOT NULL DEFAULT 0.000,
    no_of_rolls INT NOT NULL,
    breaker_inter_no VARCHAR(100) NULL,
    remarks VARCHAR(255) NULL,
    active TINYINT(1) NOT NULL DEFAULT 1,
    updated_by INT NULL,
    updated_date_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_sri_co (co_id),
    INDEX idx_sri_branch (branch_id),
    INDEX idx_sri_date (issue_date),
    INDEX idx_sri_dt (issue_dt),
    INDEX idx_sri_grp (entry_id_grp)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- =============================================================================
-- ROLLBACK (if needed):
-- DROP TABLE IF EXISTS spreader_roll_issue;
-- DROP TABLE IF EXISTS spreader_prod_entry;
-- DROP TABLE IF EXISTS spreader_machine_attr;
-- DROP TABLE IF EXISTS item_maturity_mst;
-- DROP TABLE IF EXISTS spreader_bin_mst;
-- =============================================================================
