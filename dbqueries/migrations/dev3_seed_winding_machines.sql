-- Migration: Seed 'Winding' machine type + sample winding machines in dev3
-- Date: 2026-06-15
-- Applies to: dev3 ONLY (sls already has winding machines under legacy type_of_mechine=39)
--
-- Mirrors dev3_seed_spinning_machines.sql (same dept/branch scope):
--   dept_id = 2 ('Jute5', branch 2 'Factory' of co 1 — where dev3 jute machines live)
-- Run AFTER create_jute_prod_winding_tables.sql (which also creates the 'Winding' type).

-- 'Winding' machine type (idempotent; updated_by is NOT NULL without default — system/admin = 1).
INSERT INTO machine_type_mst (machine_type_name, active, updated_by)
SELECT 'Winding', 1, 1
WHERE NOT EXISTS (
  SELECT 1 FROM machine_type_mst WHERE machine_type_name = 'Winding'
);

-- Sample winding machines (mech_code '39xxx' mirrors legacy winding type_of_mechine=39).
-- Idempotent via NOT EXISTS (machine_mst has no unique key on mech_code).
INSERT INTO machine_mst (dept_id, machine_name, machine_type_id, mech_code, active, updated_by)
SELECT 2, 'Winding Machine - 1',
       (SELECT machine_type_id FROM machine_type_mst WHERE machine_type_name = 'Winding' LIMIT 1),
       '39001', 1, 1
WHERE NOT EXISTS (SELECT 1 FROM machine_mst WHERE mech_code = '39001');

INSERT INTO machine_mst (dept_id, machine_name, machine_type_id, mech_code, active, updated_by)
SELECT 2, 'Winding Machine - 2',
       (SELECT machine_type_id FROM machine_type_mst WHERE machine_type_name = 'Winding' LIMIT 1),
       '39002', 1, 1
WHERE NOT EXISTS (SELECT 1 FROM machine_mst WHERE mech_code = '39002');

INSERT INTO machine_mst (dept_id, machine_name, machine_type_id, mech_code, active, updated_by)
SELECT 2, 'Winding Machine - 3',
       (SELECT machine_type_id FROM machine_type_mst WHERE machine_type_name = 'Winding' LIMIT 1),
       '39003', 1, 1
WHERE NOT EXISTS (SELECT 1 FROM machine_mst WHERE mech_code = '39003');

-- =============================================================================
-- ROLLBACK:
-- DELETE FROM machine_mst WHERE mech_code IN ('39001','39002','39003');
-- DELETE FROM machine_type_mst WHERE machine_type_name = 'Winding';
-- =============================================================================
