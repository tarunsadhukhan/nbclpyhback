-- Migration: Seed 'Winding Production' menu under 'Jute Production'
-- Date: 2026-06-15
-- Applies to: tenant databases dev3 (QA) [and sls when promoted]
--
-- Route /dashboardportal/juteProduction/winding (dev3 relative path 'juteProduction/winding').
-- Mirrors seed_spinning_menu.sql: menu_mst only; role_menu_map grants applied per role by the tenant
-- admin afterwards. Path derived via CONCAT off the parent so dev3 (relative) and sls (absolute) both work.
-- Run AFTER create_jute_prod_winding_tables.sql.

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'Winding Production', CONCAT(p.menu_path, '/winding'), 1, p.menu_id, NULL, 'cyclone',
       (SELECT module_mst_id FROM module_mst WHERE module_name = 'Jute Production' AND active = 1 ORDER BY module_mst_id LIMIT 1),
       165
FROM (SELECT menu_id, menu_path FROM menu_mst WHERE menu_name = 'Jute Production' LIMIT 1) p
WHERE NOT EXISTS (SELECT 1 FROM menu_mst WHERE menu_name = 'Winding Production');

-- =============================================================================
-- ROLLBACK:
-- DELETE FROM menu_mst WHERE menu_name = 'Winding Production';
-- =============================================================================
