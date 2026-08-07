-- Migration: Seed 'Spinning' machine type + sample spinning machines + attrs in dev3
-- Date: 2026-06-11
-- Applies to: dev3 ONLY (sls already has spinning machines under legacy type_of_mechine=36)
--
-- Chosen seed IDs (deterministic rule: reuse dev3 drawing seed scope):
--   co_id = 1 (drawing/spreader seed co)
--   dept_id = 2 ('Jute5', branch 2 'Factory' of co 1 — where dev3 jute machines live)
-- Run AFTER create_jute_prod_spinning_tables.sql.

-- updated_by is NOT NULL without default in dev3 masters; seed rows use 1 (system/admin).
INSERT IGNORE INTO machine_type_mst (machine_type_name, active, updated_by)
VALUES ('Spinning', 1, 1);

-- Sample machines (mech_code '36xxx' mirrors legacy spinning type_of_mechine=36). Idempotent
-- via NOT EXISTS (machine_mst has no unique key on mech_code).
INSERT INTO machine_mst (dept_id, machine_name, machine_type_id, mech_code, active, updated_by)
SELECT 2, 'Spinning Frame - 1',
       (SELECT machine_type_id FROM machine_type_mst WHERE machine_type_name = 'Spinning' LIMIT 1),
       '36001', 1, 1
WHERE NOT EXISTS (SELECT 1 FROM machine_mst WHERE mech_code = '36001');

INSERT INTO machine_mst (dept_id, machine_name, machine_type_id, mech_code, active, updated_by)
SELECT 2, 'Spinning Frame - 2',
       (SELECT machine_type_id FROM machine_type_mst WHERE machine_type_name = 'Spinning' LIMIT 1),
       '36002', 1, 1
WHERE NOT EXISTS (SELECT 1 FROM machine_mst WHERE mech_code = '36002');

INSERT INTO machine_mst (dept_id, machine_name, machine_type_id, mech_code, active, updated_by)
SELECT 2, 'Spinning Frame - 3',
       (SELECT machine_type_id FROM machine_type_mst WHERE machine_type_name = 'Spinning' LIMIT 1),
       '36003', 1, 1
WHERE NOT EXISTS (SELECT 1 FROM machine_mst WHERE mech_code = '36003');

-- Spinning attributes for the seeded machines (co_id 1; bobbin 0.500, 100 spindles, 650 speed, JBO)
INSERT INTO jute_prod_spinning_machine_attr (co_id, machine_id, frame_type, speed, no_of_spindle, bobbin_weight, active)
SELECT 1, m.machine_id, 'JBO', 650.00, 100, 0.500, 1
FROM machine_mst m
WHERE m.mech_code IN ('36001', '36002', '36003')
  AND NOT EXISTS (
      SELECT 1 FROM jute_prod_spinning_machine_attr a
      WHERE a.co_id = 1 AND a.machine_id = m.machine_id
  );

-- =============================================================================
-- ROLLBACK:
-- DELETE FROM jute_prod_spinning_machine_attr WHERE co_id = 1 AND machine_id IN
--   (SELECT machine_id FROM machine_mst WHERE mech_code IN ('36001','36002','36003'));
-- DELETE FROM machine_mst WHERE mech_code IN ('36001','36002','36003');
-- DELETE FROM machine_type_mst WHERE machine_type_name = 'Spinning';
-- =============================================================================
