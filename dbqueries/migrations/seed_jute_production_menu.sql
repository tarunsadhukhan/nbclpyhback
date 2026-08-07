-- Migration: Seed Jute Production menu entries
-- Date: 2026-05-27
-- Applies to: tenant databases (e.g., dev3, sls)
--
-- Notes:
--   - menu_parent_id values are dynamic (auto_increment); inserts use SELECT to chain children to parent.
--   - module_mst_id defaults to existing "Jute" module if present; otherwise NULL (admin can attach later).
--   - Run AFTER create_jute_production_tables.sql.

-- =============================================================================
-- 1. Parent: Jute Production
-- =============================================================================
INSERT IGNORE INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'Jute Production', '/dashboardportal/juteProduction', 1, NULL, NULL, 'factory',
       (SELECT module_mst_id FROM module_mst WHERE module_name LIKE '%Jute%' AND active = 1 ORDER BY module_mst_id LIMIT 1),
       100;

-- Capture the parent menu_id for child inserts (uses subquery on each child for tenant-portability).
-- =============================================================================
-- 2. Children
-- =============================================================================
INSERT IGNORE INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'Spreader Production', '/dashboardportal/juteProduction/spreader', 1,
       (SELECT menu_id FROM (SELECT menu_id FROM menu_mst WHERE menu_name = 'Jute Production' LIMIT 1) t),
       NULL, 'precision_manufacturing',
       (SELECT module_mst_id FROM module_mst WHERE module_name LIKE '%Jute%' AND active = 1 ORDER BY module_mst_id LIMIT 1),
       110;

INSERT IGNORE INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'Roll Stock Reports', '/dashboardportal/juteProduction/rollStockReports', 1,
       (SELECT menu_id FROM (SELECT menu_id FROM menu_mst WHERE menu_name = 'Jute Production' LIMIT 1) t),
       NULL, 'assessment',
       (SELECT module_mst_id FROM module_mst WHERE module_name LIKE '%Jute%' AND active = 1 ORDER BY module_mst_id LIMIT 1),
       120;

INSERT IGNORE INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'Spreader Bin Master', '/dashboardportal/juteProduction/masters/bins', 1,
       (SELECT menu_id FROM (SELECT menu_id FROM menu_mst WHERE menu_name = 'Jute Production' LIMIT 1) t),
       NULL, 'inventory_2',
       (SELECT module_mst_id FROM module_mst WHERE module_name LIKE '%Jute%' AND active = 1 ORDER BY module_mst_id LIMIT 1),
       130;

INSERT IGNORE INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'Item Maturity Master', '/dashboardportal/juteProduction/masters/itemMaturity', 1,
       (SELECT menu_id FROM (SELECT menu_id FROM menu_mst WHERE menu_name = 'Jute Production' LIMIT 1) t),
       NULL, 'schedule',
       (SELECT module_mst_id FROM module_mst WHERE module_name LIKE '%Jute%' AND active = 1 ORDER BY module_mst_id LIMIT 1),
       140;

INSERT IGNORE INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'Spreader Machine Wt', '/dashboardportal/juteProduction/masters/spreaderMachineWt', 1,
       (SELECT menu_id FROM (SELECT menu_id FROM menu_mst WHERE menu_name = 'Jute Production' LIMIT 1) t),
       NULL, 'scale',
       (SELECT module_mst_id FROM module_mst WHERE module_name LIKE '%Jute%' AND active = 1 ORDER BY module_mst_id LIMIT 1),
       150;

-- =============================================================================
-- ROLLBACK:
-- DELETE FROM menu_mst WHERE menu_path LIKE '/dashboardportal/juteProduction%';
-- =============================================================================
