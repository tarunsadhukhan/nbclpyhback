-- Migration: Carding foundation — seed the 'Breaker Card' machine type (idempotent).
-- Module: juteSQC (R-08-05/06/07 Breaker Card, carding stage)
-- Date: 2026-06-27
-- Applies to: tenant database dev3 (QA). Promote to other tenants later.
--
-- Context: Breaker-card SWT readings are taken on BREAKER CARD machines. The backend
-- resolves them at runtime by NAME (machine_type_mst.machine_type_name = 'Breaker Card',
-- constant BREAKER_CARD_MACHINE_TYPE_NAME), mirroring the spreader/loom precedent. MySQL
-- string comparison is case-insensitive under the default collation. There is no
-- 'Breaker Card' machine_type seeded yet, so this creates it.
--
-- machine_type_mst REAL schema (src/models/mst.py MachineTypeMst):
--   machine_type_id   INT PK AUTO_INCREMENT
--   machine_type_name VARCHAR(255) UNIQUE NULL
--   updated_by        INT NOT NULL        <-- must be supplied
--   updated_date_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
--   active            INT NOT NULL        <-- must be supplied
-- So the INSERT lists (machine_type_name, updated_by, active); updated_date_time defaults.
-- Idempotent via NOT EXISTS (case-insensitive), so re-running is a no-op.
--
-- PREREQUISITE TO FLAG: this migration ships only the TYPE. Usability needs the owner to
-- TAG the breaker-card machines with this type in the machine master (one-time admin task,
-- same as 'Spreader') so get_breaker_card_machines_query() returns them.

INSERT INTO machine_type_mst (machine_type_name, updated_by, active)
SELECT 'Breaker Card', 1, 1
WHERE NOT EXISTS (
    SELECT 1 FROM machine_type_mst WHERE machine_type_name = 'Breaker Card'
);

-- =============================================================================
-- ROLLBACK: (only drop the row THIS migration created, and only if no machine uses it)
-- -- DELETE FROM machine_type_mst
-- --   WHERE machine_type_name = 'Breaker Card'
-- --     AND NOT EXISTS (
-- --       SELECT 1 FROM machine_mst m WHERE m.machine_type_id = machine_type_mst.machine_type_id
-- --     );
-- =============================================================================
