-- Migration: Seed 'Stoppage Hours' menu under 'Jute Production'
-- Date: 2026-06-20
-- Applies to: tenant database dev3 (QA)
--
-- Route /dashboardportal/juteProduction/stoppageHours (dev3 relative path 'juteProduction/stoppageHours').
-- Mirrors seed_winding_menu.sql: menu_mst ONLY. role_menu_map grants are applied per role by the
-- tenant admin afterwards (intentionally NOT seeded here). Path derived via CONCAT off the parent.
-- Run AFTER create_jute_prod_stoppage_hours.sql.

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'Stoppage Hours', CONCAT(p.menu_path, '/stoppageHours'), 1, p.menu_id, NULL, 'timer',
       (SELECT module_mst_id FROM module_mst WHERE module_name = 'Jute Production' AND active = 1 ORDER BY module_mst_id LIMIT 1),
       200
FROM (SELECT menu_id, menu_path FROM menu_mst WHERE menu_name = 'Jute Production' LIMIT 1) p
WHERE NOT EXISTS (SELECT 1 FROM menu_mst WHERE menu_name = 'Stoppage Hours');

-- =============================================================================
-- ROLLBACK:
-- DELETE FROM menu_mst WHERE menu_name = 'Stoppage Hours';
-- =============================================================================
