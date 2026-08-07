-- Migration: Beaming foundations — new 'Jute Cloth' item type, re-tag cloth item
--            groups (regular -> Jute Cloth), add 'Beaming' machine type.
-- Date: 2026-06-21
-- Applies to: tenant database dev3 (QA). Promote to other tenants later.
--
-- Context: Beaming production (warp-beam prep for weaving) consumes jute-cloth items.
-- The cloth item groups were created as item_type 'regular' (1); they need a dedicated
-- 'Jute Cloth' type so the Beaming pages can filter the item dropdown.
-- item_type_master / machine_type_mst both have updated_by INT NOT NULL (no default).

-- 1. New item type 'Jute Cloth' (idempotent).
INSERT INTO item_type_master (item_type_name, updated_by)
SELECT 'Jute Cloth', 1
WHERE NOT EXISTS (SELECT 1 FROM item_type_master WHERE item_type_name = 'Jute Cloth');

-- 2. Re-tag the cloth item groups from 'regular' (1) to 'Jute Cloth'.
--    Groups: 625 HESSIAN(2), 626 SACKING, 640 Hessian(501), 642 Sale Yarn,
--            1266 HESSIAN(), 1716 HESSIAN 3.
UPDATE item_grp_mst
SET item_type_id = (SELECT item_type_id FROM item_type_master WHERE item_type_name = 'Jute Cloth')
WHERE item_grp_id IN (625, 626, 640, 642, 1266, 1716);

-- 3. New machine type 'Beaming' (idempotent).
INSERT INTO machine_type_mst (machine_type_name, updated_by, active)
SELECT 'Beaming', 1, 1
WHERE NOT EXISTS (SELECT 1 FROM machine_type_mst WHERE machine_type_name = 'Beaming');

-- =============================================================================
-- ROLLBACK:
-- UPDATE item_grp_mst SET item_type_id = 1 WHERE item_grp_id IN (625,626,640,642,1266,1716);
-- DELETE FROM machine_type_mst WHERE machine_type_name = 'Beaming';
-- DELETE FROM item_type_master WHERE item_type_name = 'Jute Cloth';
-- =============================================================================
