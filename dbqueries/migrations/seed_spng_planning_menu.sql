-- Migration: Seed menus for spinning planning refactor (SQC + standards master)
-- Date: 2026-06-13
-- Applies to: tenant databases dev3 (QA) [and sls when promoted]
--
-- Adds:
--   1. 'Spinning Standards' under the existing 'Jute Production' parent
--      (route /dashboardportal/juteProduction/masters/spngTargetMap).
--   2. 'Jute SQC' top-level parent (if absent) + 'Spinning SQC' child
--      (route /dashboardportal/juteSQC/spinning).
-- Mirrors seed_spinning_menu.sql: menu_mst only (tenant). role_menu_map grants
-- are applied per role by the tenant admin afterwards. CONCAT off the parent path
-- supports both dev3 relative ('juteProduction') and sls absolute path styles.
-- Run AFTER create_spng_planning_refactor.sql.

-- 1. Spinning Standards master (under Jute Production)
INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'Spinning Standards', CONCAT(p.menu_path, '/masters/spngTargetMap'), 1, p.menu_id, NULL, 'tune',
       (SELECT module_mst_id FROM module_mst WHERE module_name = 'Jute Production' AND active = 1 ORDER BY module_mst_id LIMIT 1),
       190
FROM (SELECT menu_id, menu_path FROM menu_mst WHERE menu_name = 'Jute Production' LIMIT 1) p
WHERE NOT EXISTS (SELECT 1 FROM menu_mst WHERE menu_name = 'Spinning Standards');

-- 2a. Jute SQC parent (top-level) — created only if no juteSQC parent exists yet
INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'Jute SQC', 'juteSQC', 1, NULL, NULL, 'fact_check',
       (SELECT module_mst_id FROM module_mst WHERE module_name = 'Jute Production' AND active = 1 ORDER BY module_mst_id LIMIT 1),
       110
WHERE NOT EXISTS (SELECT 1 FROM menu_mst WHERE menu_name = 'Jute SQC' OR menu_path = 'juteSQC');

-- 2b. Spinning SQC child (under Jute SQC) — path derived from parent
INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'Spinning SQC', CONCAT(p.menu_path, '/spinning'), 1, p.menu_id, NULL, 'speed',
       (SELECT module_mst_id FROM module_mst WHERE module_name = 'Jute Production' AND active = 1 ORDER BY module_mst_id LIMIT 1),
       10
FROM (SELECT menu_id, menu_path FROM menu_mst WHERE menu_name = 'Jute SQC' LIMIT 1) p
WHERE NOT EXISTS (SELECT 1 FROM menu_mst WHERE menu_name = 'Spinning SQC');

-- =============================================================================
-- ROLLBACK:
-- DELETE FROM menu_mst WHERE menu_name IN ('Spinning Standards', 'Spinning SQC');
-- DELETE FROM menu_mst WHERE menu_name = 'Jute SQC' AND menu_path = 'juteSQC';
-- -- (only drop the 'Jute SQC' parent if no other children you want to keep depend on it)
-- =============================================================================
