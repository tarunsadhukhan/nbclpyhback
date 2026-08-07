-- Migration: Seed Finishing menus (SPEC §8). 3 rows under 'Jute Production'
--            (juteProduction) + 1 row under the existing 'Jute SQC' (juteSQC) parent.
-- Date: 2026-06-23
-- Applies to: tenant database dev3 (QA).
--
-- Adds:
--   1. 'Finishing Quality Master' (master)  -> juteProduction/masters/finishingQualityMaster
--   2. 'Finishing Spec Sheet'     (master)  -> juteProduction/masters/finishingSpecSheet
--   3. 'Finishing Production'     (txn)      -> juteProduction/finishing
--   4. 'Finishing SQC'           (sqc child) -> juteSQC/finishing
-- Mirrors seed_beaming_menu.sql / seed_beaming_sqc_menu.sql: menu_mst ONLY.
-- role_menu_map grants are applied per role by the tenant admin afterwards
-- (intentionally NOT seeded here). Paths derived via CONCAT off the parent.
-- Run AFTER create_finishing_machine_types.sql.

-- 1. Finishing Quality Master (master, under Jute Production)
INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'Finishing Quality Master', CONCAT(p.menu_path, '/masters/finishingQualityMaster'), 1, p.menu_id, NULL, 'fact_check',
       (SELECT module_mst_id FROM module_mst WHERE module_name = 'Jute Production' AND active = 1 ORDER BY module_mst_id LIMIT 1),
       203
FROM (SELECT menu_id, menu_path FROM menu_mst WHERE menu_name = 'Jute Production' LIMIT 1) p
WHERE NOT EXISTS (SELECT 1 FROM menu_mst WHERE menu_name = 'Finishing Quality Master');

-- 2. Finishing Spec Sheet (standards/targets master, under Jute Production)
INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'Finishing Spec Sheet', CONCAT(p.menu_path, '/masters/finishingSpecSheet'), 1, p.menu_id, NULL, 'tune',
       (SELECT module_mst_id FROM module_mst WHERE module_name = 'Jute Production' AND active = 1 ORDER BY module_mst_id LIMIT 1),
       204
FROM (SELECT menu_id, menu_path FROM menu_mst WHERE menu_name = 'Jute Production' LIMIT 1) p
WHERE NOT EXISTS (SELECT 1 FROM menu_mst WHERE menu_name = 'Finishing Spec Sheet');

-- 3. Finishing Production (transaction page, under Jute Production)
INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'Finishing Production', CONCAT(p.menu_path, '/finishing'), 1, p.menu_id, NULL, 'layers',
       (SELECT module_mst_id FROM module_mst WHERE module_name = 'Jute Production' AND active = 1 ORDER BY module_mst_id LIMIT 1),
       185
FROM (SELECT menu_id, menu_path FROM menu_mst WHERE menu_name = 'Jute Production' LIMIT 1) p
WHERE NOT EXISTS (SELECT 1 FROM menu_mst WHERE menu_name = 'Finishing Production');

-- 4. Finishing SQC (child of Jute SQC) — path derived from parent -> 'juteSQC/finishing'
INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'Finishing SQC', CONCAT(p.menu_path, '/finishing'), 1, p.menu_id, NULL, 'layers',
       (SELECT module_mst_id FROM module_mst WHERE module_name = 'Jute Production' AND active = 1 ORDER BY module_mst_id LIMIT 1),
       30
FROM (SELECT menu_id, menu_path FROM menu_mst WHERE menu_name = 'Jute SQC' LIMIT 1) p
WHERE NOT EXISTS (SELECT 1 FROM menu_mst WHERE menu_name = 'Finishing SQC');

-- =============================================================================
-- ROLLBACK:
-- DELETE FROM menu_mst WHERE menu_name IN
--   ('Finishing Quality Master', 'Finishing Spec Sheet', 'Finishing Production', 'Finishing SQC');
-- =============================================================================
