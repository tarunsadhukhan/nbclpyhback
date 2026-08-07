-- Migration: Seed 'Weaving SQC' menu under the existing 'Jute SQC' parent.
-- Date: 2026-06-23
-- Applies to: tenant database dev3 (QA).
--
-- Parent: existing 'Jute SQC' top-level menu (menu_id 781, menu_path 'juteSQC').
-- Path derived via CONCAT off the parent, yielding 'juteSQC/weaving'
-- (route /dashboardportal/juteSQC/weaving). order_by 30 places it after the
-- existing 'Spinning SQC' (10) and 'Beaming SQC' (20) children. Icon mirrors the
-- SQC siblings. menu_mst ONLY — role_menu_map grants applied per role by the
-- tenant admin afterwards (intentionally NOT seeded here). Mirrors seed_beaming_sqc_menu.sql.

-- Weaving SQC (child of Jute SQC) — path derived from parent
INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'Weaving SQC', CONCAT(p.menu_path, '/weaving'), 1, p.menu_id, NULL, 'speed',
       (SELECT module_mst_id FROM module_mst WHERE module_name = 'Jute Production' AND active = 1 ORDER BY module_mst_id LIMIT 1),
       30
FROM (SELECT menu_id, menu_path FROM menu_mst WHERE menu_name = 'Jute SQC' LIMIT 1) p
WHERE NOT EXISTS (SELECT 1 FROM menu_mst WHERE menu_name = 'Weaving SQC');

-- =============================================================================
-- ROLLBACK:
-- DELETE FROM menu_mst WHERE menu_name = 'Weaving SQC';
-- =============================================================================
