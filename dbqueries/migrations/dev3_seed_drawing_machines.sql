-- Migration: Seed 'Drawing' machine type + sample drawing machines + attrs in dev3
-- Date: 2026-06-11
-- Applies to: dev3 ONLY (sls already has machine type 'Drawing' id=14 with 52 machines)
--
-- Chosen seed IDs (deterministic rule: reuse dev3 spreader seed scope):
--   co_id = 1 (spreader_prod_entry / spreader_machine_attr co)
--   dept_id = 2 ('Jute5', branch 2 'Factory' of co 1 — where dev3 spreader machines live)
-- Run AFTER create_jute_prod_drawing_tables.sql.

-- updated_by is NOT NULL without default in dev3 masters; seed rows use 1 (system/admin).
INSERT IGNORE INTO machine_type_mst (machine_type_name, active, updated_by)
VALUES ('Drawing', 1, 1);

-- Sample machines (mech_code/machine_name mirror sls naming). Idempotent via NOT EXISTS
-- (machine_mst has no unique key on mech_code).
INSERT INTO machine_mst (dept_id, machine_name, machine_type_id, mech_code, active, updated_by)
SELECT 2, '1st  Drawing - 1',
       (SELECT machine_type_id FROM machine_type_mst WHERE machine_type_name = 'Drawing' LIMIT 1),
       '21001', 1, 1
WHERE NOT EXISTS (SELECT 1 FROM machine_mst WHERE mech_code = '21001');

INSERT INTO machine_mst (dept_id, machine_name, machine_type_id, mech_code, active, updated_by)
SELECT 2, '2nd Drawing - 1',
       (SELECT machine_type_id FROM machine_type_mst WHERE machine_type_name = 'Drawing' LIMIT 1),
       '22001', 1, 1
WHERE NOT EXISTS (SELECT 1 FROM machine_mst WHERE mech_code = '22001');

INSERT INTO machine_mst (dept_id, machine_name, machine_type_id, mech_code, active, updated_by)
SELECT 2, 'Finisher  Drawing - 1',
       (SELECT machine_type_id FROM machine_type_mst WHERE machine_type_name = 'Drawing' LIMIT 1),
       '25001', 1, 1
WHERE NOT EXISTS (SELECT 1 FROM machine_mst WHERE mech_code = '25001');

-- Drawing attributes for the seeded machines (co_id 1; const 8000 m/8h, wrap 10000)
INSERT INTO jute_prod_drawing_machine_attr (co_id, machine_id, const_meter, mc_group, meter_wrap_limit, active)
SELECT 1, m.machine_id, 8000.000, 'DRG', 10000, 1
FROM machine_mst m
WHERE m.mech_code IN ('21001', '22001', '25001')
  AND NOT EXISTS (
      SELECT 1 FROM jute_prod_drawing_machine_attr a
      WHERE a.co_id = 1 AND a.machine_id = m.machine_id
  );

-- =============================================================================
-- ROLLBACK:
-- DELETE FROM jute_prod_drawing_machine_attr WHERE co_id = 1 AND machine_id IN
--   (SELECT machine_id FROM machine_mst WHERE mech_code IN ('21001','22001','25001'));
-- DELETE FROM machine_mst WHERE mech_code IN ('21001','22001','25001');
-- DELETE FROM machine_type_mst WHERE machine_type_name = 'Drawing';
-- =============================================================================
