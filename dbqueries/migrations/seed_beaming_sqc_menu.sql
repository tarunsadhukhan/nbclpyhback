-- Migration: Seed 'Beaming SQC' menu under the existing 'Jute SQC' parent.
-- Date: 2026-06-22
-- Applies to: tenant database dev3 (QA).
--
-- Parent: existing 'Jute SQC' top-level menu (menu_path 'juteSQC', seeded by
-- seed_spng_planning_menu.sql). Path derived via CONCAT off the parent, yielding
-- 'juteSQC/beaming' (route /dashboardportal/juteSQC/beaming). order_by 20 places it
-- after the existing 'Spinning SQC' child (order_by 10). Icon mirrors the Spinning
-- SQC sibling. menu_mst ONLY  role_menu_map grants are applied per role by the
-- tenant admin afterwards (intentionally NOT seeded here).

-- Beaming SQC (child of Jute SQC) — path derived from parent
INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'Beaming SQC', CONCAT(p.menu_path, '/beaming'), 1, p.menu_id, NULL, 'speed',
       (SELECT module_mst_id FROM module_mst WHERE module_name = 'Jute Production' AND active = 1 ORDER BY module_mst_id LIMIT 1),
       20
FROM (SELECT menu_id, menu_path FROM menu_mst WHERE menu_name = 'Jute SQC' LIMIT 1) p
WHERE NOT EXISTS (SELECT 1 FROM menu_mst WHERE menu_name = 'Beaming SQC');

-- =============================================================================
-- ROLLBACK:
-- DELETE FROM menu_mst WHERE menu_name = 'Beaming SQC';
-- =============================================================================
