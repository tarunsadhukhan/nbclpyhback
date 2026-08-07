-- Migration: Create machine_type_mst table
-- Source: vowsls.machine_types_master
-- Changes from source:
--   - Renamed id → machine_type_id
--   - Renamed type_of_machine → machine_type_name
--   - Removed created_by, created_date_time
--   - Added updated_by, updated_date_time, active

CREATE TABLE IF NOT EXISTS machine_type_mst (
    machine_type_id INT AUTO_INCREMENT PRIMARY KEY,
    machine_type_name VARCHAR(255) NULL,
    updated_by INT NOT NULL DEFAULT 0,
    updated_date_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    active INT NOT NULL DEFAULT 1
);

-- Seed from vowsls (run only once, skip if table already has data):
-- INSERT INTO machine_type_mst (machine_type_name, updated_by, updated_date_time, active)
-- SELECT type_of_machine, COALESCE(created_by, 0), created_date_time, 1
-- FROM vowsls.machine_types_master;

-- Rollback:
-- DROP TABLE IF EXISTS machine_type_mst;
