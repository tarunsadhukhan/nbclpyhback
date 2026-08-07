-- Migration: Seed Spinning menu entries under 'Jute Production' parent
-- Date: 2026-06-11
-- Applies to: tenant databases dev3 AND sls
--
-- Notes:
--   - Tenants use DIFFERENT menu_path styles (dev3 relative 'juteProduction/...',
--     sls absolute '/dashboardportal/juteProduction/...'). Children derive their
--     path from the parent row via CONCAT so the seed works on both.
--   - role_menu_map rows must be granted per role by the tenant admin afterwards
--     (same as the drawing menu rollout).
--   - Run AFTER create_jute_prod_spinning_tables.sql.

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'Spinning Production', CONCAT(p.menu_path, '/spinning'), 1, p.menu_id, NULL, 'disc',
       (SELECT module_mst_id FROM module_mst WHERE module_name LIKE '%Jute%' AND active = 1 ORDER BY module_mst_id LIMIT 1),
       170
FROM (SELECT menu_id, menu_path FROM menu_mst WHERE menu_name = 'Jute Production' LIMIT 1) p
WHERE NOT EXISTS (SELECT 1 FROM menu_mst WHERE menu_name = 'Spinning Production');

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'Spinning Machine Master', CONCAT(p.menu_path, '/masters/spinningMachineAttr'), 1, p.menu_id, NULL, 'settings',
       (SELECT module_mst_id FROM module_mst WHERE module_name LIKE '%Jute%' AND active = 1 ORDER BY module_mst_id LIMIT 1),
       175
FROM (SELECT menu_id, menu_path FROM menu_mst WHERE menu_name = 'Jute Production' LIMIT 1) p
WHERE NOT EXISTS (SELECT 1 FROM menu_mst WHERE menu_name = 'Spinning Machine Master');

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'Trolly Master', CONCAT(p.menu_path, '/masters/trollyMaster'), 1, p.menu_id, NULL, 'inventory_2',
       (SELECT module_mst_id FROM module_mst WHERE module_name LIKE '%Jute%' AND active = 1 ORDER BY module_mst_id LIMIT 1),
       180
FROM (SELECT menu_id, menu_path FROM menu_mst WHERE menu_name = 'Jute Production' LIMIT 1) p
WHERE NOT EXISTS (SELECT 1 FROM menu_mst WHERE menu_name = 'Trolly Master');

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'Yarn Quality Parameters', CONCAT(p.menu_path, '/masters/yarnQualityParam'), 1, p.menu_id, NULL, 'tune',
       (SELECT module_mst_id FROM module_mst WHERE module_name LIKE '%Jute%' AND active = 1 ORDER BY module_mst_id LIMIT 1),
       185
FROM (SELECT menu_id, menu_path FROM menu_mst WHERE menu_name = 'Jute Production' LIMIT 1) p
WHERE NOT EXISTS (SELECT 1 FROM menu_mst WHERE menu_name = 'Yarn Quality Parameters');

-- =============================================================================
-- ROLLBACK:
-- DELETE FROM menu_mst WHERE menu_name IN
--   ('Spinning Production', 'Spinning Machine Master', 'Trolly Master', 'Yarn Quality Parameters');
-- =============================================================================
