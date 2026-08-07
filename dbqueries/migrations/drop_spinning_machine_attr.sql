-- Migration: Remove the Spinning Machine Attributes master.
-- Date: 2026-06-17
-- Applies to: tenant databases dev3 AND sls
--
-- Context:
--   Machine standards/config (bobbin weight, spindles, speed) moved to the
--   time-versioned jute_prod_spng_target_map master (id_type='mcid',
--   value_role='standard', param IN ('bobbin_wt','spindles','speed')). The old
--   per-machine table jute_prod_spinning_machine_attr and its CRUD page
--   (masters/spinningMachineAttr) are removed.
--
--   NO data migration: existing attr values are NOT copied. Until standard rows
--   are entered in the Spinning Standards/Targets page, doff tare = trolly+bucket
--   (bobbin 0) and planning spindles = 0. (Per decision.)
--
-- WARNING: DROP TABLE is destructive and irreversible. Confirm before running on sls.

-- 1) Drop the attribute table.
DROP TABLE IF EXISTS jute_prod_spinning_machine_attr;

-- 2) Deactivate the sidebar menu row for the removed page (sidebar filters active = 1).
UPDATE menu_mst SET active = 0 WHERE menu_name = 'Spinning Machine Master';

-- 3) Refresh vw_spinning_planning_grid: its `spindles` column previously sub-queried
--    jute_prod_spinning_machine_attr (now dropped) and was repointed to
--    jute_prod_spng_target_map (param='spindles'). The live /planning_grid endpoint
--    does NOT read this view (it builds the grid in Python), but re-run the corrected
--    DDL so the deployed view is not left referencing the dropped table:
--        re-run dbqueries/migrations/repoint_vw_spinning_planning_grid.sql

-- =============================================================================
-- ROLLBACK:
--
-- CREATE TABLE IF NOT EXISTS jute_prod_spinning_machine_attr (
--   spinning_machine_attr_id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
--   co_id INT NOT NULL,
--   machine_id INT NOT NULL,
--   frame_type VARCHAR(10) NULL,
--   speed DECIMAL(10,2) NULL,
--   no_of_spindle INT NULL,
--   bobbin_weight DECIMAL(10,3) NOT NULL DEFAULT 0.000,
--   active TINYINT(1) NOT NULL DEFAULT 1,
--   updated_by INT NULL,
--   updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
--   UNIQUE KEY uq_jpsma_co_machine (co_id, machine_id),
--   KEY idx_jpsma_co (co_id),
--   KEY idx_jpsma_machine (machine_id)
-- ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
-- UPDATE menu_mst SET active = 1 WHERE menu_name = 'Spinning Machine Master';
--
-- (Note: dropped row data is NOT recoverable by this rollback.)
-- =============================================================================
