-- Migration: Seed Beaming menus under 'Jute Production' (menu_id 768, path 'juteProduction').
-- Date: 2026-06-21
-- Applies to: tenant database dev3 (QA).
--
-- Adds 3 rows: 'Beaming Production' (transaction) + 'Beaming Quality Master' and
-- 'Beaming Standards' (masters). Mirrors seed_stoppage_menu.sql / seed_spng_planning_menu.sql:
-- menu_mst ONLY. role_menu_map grants are applied per role by the tenant admin afterwards
-- (intentionally NOT seeded here). Path derived via CONCAT off the parent.
-- Run AFTER create_beaming_item_type_and_machine_type.sql.

-- 1. Beaming Production (transaction page)
INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'Beaming Production', CONCAT(p.menu_path, '/beaming'), 1, p.menu_id, NULL, 'view_week',
       (SELECT module_mst_id FROM module_mst WHERE module_name = 'Jute Production' AND active = 1 ORDER BY module_mst_id LIMIT 1),
       180
FROM (SELECT menu_id, menu_path FROM menu_mst WHERE menu_name = 'Jute Production' LIMIT 1) p
WHERE NOT EXISTS (SELECT 1 FROM menu_mst WHERE menu_name = 'Beaming Production');

-- 2. Beaming Quality Master (master, under Jute Production)
INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'Beaming Quality Master', CONCAT(p.menu_path, '/masters/beamingQualityMaster'), 1, p.menu_id, NULL, 'fact_check',
       (SELECT module_mst_id FROM module_mst WHERE module_name = 'Jute Production' AND active = 1 ORDER BY module_mst_id LIMIT 1),
       201
FROM (SELECT menu_id, menu_path FROM menu_mst WHERE menu_name = 'Jute Production' LIMIT 1) p
WHERE NOT EXISTS (SELECT 1 FROM menu_mst WHERE menu_name = 'Beaming Quality Master');

-- 3. Beaming Standards (standards/targets master, under Jute Production)
INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'Beaming Standards', CONCAT(p.menu_path, '/masters/beamingTargetMap'), 1, p.menu_id, NULL, 'tune',
       (SELECT module_mst_id FROM module_mst WHERE module_name = 'Jute Production' AND active = 1 ORDER BY module_mst_id LIMIT 1),
       202
FROM (SELECT menu_id, menu_path FROM menu_mst WHERE menu_name = 'Jute Production' LIMIT 1) p
WHERE NOT EXISTS (SELECT 1 FROM menu_mst WHERE menu_name = 'Beaming Standards');

-- =============================================================================
-- ROLLBACK:
-- DELETE FROM menu_mst WHERE menu_name IN ('Beaming Production', 'Beaming Quality Master', 'Beaming Standards');
-- =============================================================================
