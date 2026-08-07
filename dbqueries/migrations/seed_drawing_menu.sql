-- Migration: Seed Drawing menu entries under 'Jute Production' parent
-- Date: 2026-06-11
-- Applies to: tenant databases dev3 AND sls
--
-- Notes:
--   - Tenants use DIFFERENT menu_path styles (dev3 relative 'juteProduction/...',
--     sls absolute '/dashboardportal/juteProduction/...'). Children derive their
--     path from the parent row via CONCAT so the seed works on both.
--   - role_menu_map rows must be granted per role by the tenant admin afterwards
--     (same as the spreader menu rollout).
--   - Run AFTER create_jute_prod_drawing_tables.sql.

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'Drawing Production', CONCAT(p.menu_path, '/drawing'), 1, p.menu_id, NULL, 'speed',
       (SELECT module_mst_id FROM module_mst WHERE module_name LIKE '%Jute%' AND active = 1 ORDER BY module_mst_id LIMIT 1),
       160
FROM (SELECT menu_id, menu_path FROM menu_mst WHERE menu_name = 'Jute Production' LIMIT 1) p
WHERE NOT EXISTS (SELECT 1 FROM menu_mst WHERE menu_name = 'Drawing Production');

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'Drawing Machine Master', CONCAT(p.menu_path, '/masters/drawingMachineAttr'), 1, p.menu_id, NULL, 'straighten',
       (SELECT module_mst_id FROM module_mst WHERE module_name LIKE '%Jute%' AND active = 1 ORDER BY module_mst_id LIMIT 1),
       165
FROM (SELECT menu_id, menu_path FROM menu_mst WHERE menu_name = 'Jute Production' LIMIT 1) p
WHERE NOT EXISTS (SELECT 1 FROM menu_mst WHERE menu_name = 'Drawing Machine Master');

-- =============================================================================
-- ROLLBACK:
-- DELETE FROM menu_mst WHERE menu_name IN ('Drawing Production', 'Drawing Machine Master');
-- =============================================================================
