-- Migration: Seed Weaving menus under 'Jute Production' (menu_id 768, path 'juteProduction').
-- Date: 2026-06-23
-- Applies to: tenant database dev3 (QA).
--
-- Adds 3 rows: 'Weaving Production' (transaction) + 'Weaving Quality Master' and
-- 'Weaving Standards' (masters). Mirrors seed_beaming_menu.sql: menu_mst ONLY.
-- role_menu_map grants are applied per role by the tenant admin afterwards
-- (intentionally NOT seeded here). Path derived via CONCAT off the parent.
-- order_by values sit just after the beaming rows (180/201/202).
-- Run AFTER seed_weaving_loom_machine_type.sql.

-- 1. Weaving Production (transaction page)
INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'Weaving Production', CONCAT(p.menu_path, '/weaving'), 1, p.menu_id, NULL, 'grid_on',
       (SELECT module_mst_id FROM module_mst WHERE module_name = 'Jute Production' AND active = 1 ORDER BY module_mst_id LIMIT 1),
       185
FROM (SELECT menu_id, menu_path FROM menu_mst WHERE menu_name = 'Jute Production' LIMIT 1) p
WHERE NOT EXISTS (SELECT 1 FROM menu_mst WHERE menu_name = 'Weaving Production');

-- 2. Weaving Quality Master (master, under Jute Production)
INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'Weaving Quality Master', CONCAT(p.menu_path, '/masters/weavingQualityMaster'), 1, p.menu_id, NULL, 'fact_check',
       (SELECT module_mst_id FROM module_mst WHERE module_name = 'Jute Production' AND active = 1 ORDER BY module_mst_id LIMIT 1),
       203
FROM (SELECT menu_id, menu_path FROM menu_mst WHERE menu_name = 'Jute Production' LIMIT 1) p
WHERE NOT EXISTS (SELECT 1 FROM menu_mst WHERE menu_name = 'Weaving Quality Master');

-- 3. Weaving Standards (standards/targets master, under Jute Production)
INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'Weaving Standards', CONCAT(p.menu_path, '/masters/weavingTargetMap'), 1, p.menu_id, NULL, 'tune',
       (SELECT module_mst_id FROM module_mst WHERE module_name = 'Jute Production' AND active = 1 ORDER BY module_mst_id LIMIT 1),
       204
FROM (SELECT menu_id, menu_path FROM menu_mst WHERE menu_name = 'Jute Production' LIMIT 1) p
WHERE NOT EXISTS (SELECT 1 FROM menu_mst WHERE menu_name = 'Weaving Standards');

-- =============================================================================
-- ROLLBACK:
-- DELETE FROM menu_mst WHERE menu_name IN ('Weaving Production', 'Weaving Quality Master', 'Weaving Standards');
-- =============================================================================
