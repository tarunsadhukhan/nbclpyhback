-- Migration: New finishing machine types — adds the three machine_type_mst rows
--            introduced by the finishing process/param redesign (Herackle, Rolling,
--            Sack Sewing).
-- Date: 2026-06-25
-- Applies to: tenant database dev3 (QA). Promote to other tenants later.
--
-- Context: The finishing module now spans nine sub-processes; rolling, herackle and
-- sacksewing are new. Each is its own machine type so the Finishing pages can filter the
-- machine dropdown per process. The backend resolves the type by NAME at runtime
-- (FINISHING_MACHINE_TYPE_NAMES in src/juteProduction/constants.py), exactly like the
-- original six seeded in create_finishing_machine_types.sql. Machine LINKING is currently
-- unused — these types exist for the future only.
-- machine_type_mst has updated_by INT NOT NULL (no default), active TINYINT.
-- Idempotent INSERT ... WHERE NOT EXISTS, mirroring create_finishing_machine_types.sql.

-- Herackle
INSERT INTO machine_type_mst (machine_type_name, updated_by, active)
SELECT 'Herackle', 1, 1
WHERE NOT EXISTS (SELECT 1 FROM machine_type_mst WHERE machine_type_name = 'Herackle');

-- Rolling
INSERT INTO machine_type_mst (machine_type_name, updated_by, active)
SELECT 'Rolling', 1, 1
WHERE NOT EXISTS (SELECT 1 FROM machine_type_mst WHERE machine_type_name = 'Rolling');

-- Sack Sewing
INSERT INTO machine_type_mst (machine_type_name, updated_by, active)
SELECT 'Sack Sewing', 1, 1
WHERE NOT EXISTS (SELECT 1 FROM machine_type_mst WHERE machine_type_name = 'Sack Sewing');

-- =============================================================================
-- ROLLBACK:
-- DELETE FROM machine_type_mst
--  WHERE machine_type_name IN ('Herackle','Rolling','Sack Sewing');
-- =============================================================================
