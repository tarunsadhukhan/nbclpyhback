-- Migration: Finishing machine types — one machine_type_mst row per finishing
--            sub-process (Damping, Calendering, Lapping, Cutting, Hemming, Bale Press).
-- Date: 2026-06-23
-- Applies to: tenant database dev3 (QA). Promote to other tenants later.
--
-- Context: Finishing production runs across six sub-processes; each is its own machine
-- type so the Finishing pages can filter the machine dropdown per process. The backend
-- resolves the type by NAME at runtime (FINISHING_MACHINE_TYPE_NAMES in
-- src/juteProduction/constants.py), exactly like Beaming resolves 'Beaming'.
-- machine_type_mst has updated_by INT NOT NULL (no default), active TINYINT.
-- Idempotent INSERT ... WHERE NOT EXISTS, mirroring
-- create_beaming_item_type_and_machine_type.sql.

-- Damping
INSERT INTO machine_type_mst (machine_type_name, updated_by, active)
SELECT 'Damping', 1, 1
WHERE NOT EXISTS (SELECT 1 FROM machine_type_mst WHERE machine_type_name = 'Damping');

-- Calendering
INSERT INTO machine_type_mst (machine_type_name, updated_by, active)
SELECT 'Calendering', 1, 1
WHERE NOT EXISTS (SELECT 1 FROM machine_type_mst WHERE machine_type_name = 'Calendering');

-- Lapping
INSERT INTO machine_type_mst (machine_type_name, updated_by, active)
SELECT 'Lapping', 1, 1
WHERE NOT EXISTS (SELECT 1 FROM machine_type_mst WHERE machine_type_name = 'Lapping');

-- Cutting
INSERT INTO machine_type_mst (machine_type_name, updated_by, active)
SELECT 'Cutting', 1, 1
WHERE NOT EXISTS (SELECT 1 FROM machine_type_mst WHERE machine_type_name = 'Cutting');

-- Hemming
INSERT INTO machine_type_mst (machine_type_name, updated_by, active)
SELECT 'Hemming', 1, 1
WHERE NOT EXISTS (SELECT 1 FROM machine_type_mst WHERE machine_type_name = 'Hemming');

-- Bale Press
INSERT INTO machine_type_mst (machine_type_name, updated_by, active)
SELECT 'Bale Press', 1, 1
WHERE NOT EXISTS (SELECT 1 FROM machine_type_mst WHERE machine_type_name = 'Bale Press');

-- =============================================================================
-- ROLLBACK:
-- DELETE FROM machine_type_mst
--  WHERE machine_type_name IN ('Damping','Calendering','Lapping','Cutting','Hemming','Bale Press');
-- =============================================================================
