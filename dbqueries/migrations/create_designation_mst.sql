-- Migration: Create designation_mst table
-- Source: vowsls.designation
-- Changes from source:
--   - id → designation_id (PK convention)
--   - company_id removed (no longer needed)
--   - Removed: created_by, mod_by, mod_on, auto_datetime_insert
--   - Added: active, updated_by, updated_date_time

CREATE TABLE IF NOT EXISTS designation_mst (
    designation_id BIGINT NOT NULL AUTO_INCREMENT,
    branch_id BIGINT NULL,
    department BIGINT NULL,
    desig VARCHAR(255) NULL,
    norms VARCHAR(255) NULL,
    time_piece VARCHAR(255) NULL,
    direct_indirect VARCHAR(255) NULL,
    on_machine VARCHAR(255) NULL,
    machine_type VARCHAR(255) NULL,
    no_of_machines VARCHAR(255) NULL,
    cost_code VARCHAR(255) NULL,
    cost_description VARCHAR(255) NULL,
    piece_rate_type VARCHAR(255) NULL,
    active INT NOT NULL DEFAULT 1,
    updated_by INT NULL,
    updated_date_time DATETIME NULL,
    PRIMARY KEY (designation_id),
    INDEX idx_designation_branch_id (branch_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Rollback:
-- DROP TABLE IF EXISTS designation_mst;
