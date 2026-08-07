-- Migration: Seed Procurement reports_1 menu entries (menu_mst report rows + role maps)
-- Applies to: dev3 (tenant DB). Run via run_seed_procurement_reports_menu.py (dry-run, then --commit).
--
-- Notes:
--   - Parent = menu_id 920 ("Procurement Report(1)", menu_path 'procurement/reports_1').
--   - report=1 makes a row appear in the reports_1 dropdown (get_report_menu_tree filters report=1, active=1).
--   - menu_path has NO '/dashboardportal' prefix (the hub prepends it on router.push), matching the parent.
--   - menu_name is UNIQUE -> INSERT IGNORE makes this re-runnable.
--   - role_menu_map: roles {1,12} (the procurement reports audience, same as sibling hub 738),
--     access_type_id=4 (edit), updated_by=1. Guarded with NOT EXISTS so re-runs don't duplicate.
--   - Also grants hub 920 to role 12 so role-12 users can reach the hub (it ships granted to role 1 only).

-- =============================================================================
-- 0. Make the hub reachable by role 12 too (matches sibling procurement hub 738).
-- =============================================================================
INSERT INTO role_menu_map (role_id, menu_id, access_type_id, updated_by)
SELECT 12, 920, 4, 1 FROM DUAL
 WHERE NOT EXISTS (
     SELECT 1 FROM role_menu_map WHERE role_id = 12 AND menu_id = 920
 );

-- =============================================================================
-- Report children of hub 920
-- =============================================================================
INSERT IGNORE INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by, report)
SELECT 'Indent Item-wise', 'procurement/reports_1/indentItemwise', 1, 920, NULL, 'assessment', NULL, 10, 1;

INSERT IGNORE INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by, report)
SELECT 'Outstanding Indents (Waiting for PO)', 'procurement/reports_1/indentOutstanding', 1, 920, NULL, 'assessment', NULL, 20, 1;

INSERT IGNORE INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by, report)
SELECT 'PO Item-wise', 'procurement/reports_1/poItemwise', 1, 920, NULL, 'assessment', NULL, 30, 1;

INSERT IGNORE INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by, report)
SELECT 'PO Supplier-wise', 'procurement/reports_1/poSupplierwise', 1, 920, NULL, 'assessment', NULL, 40, 1;

INSERT IGNORE INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by, report)
SELECT 'Outstanding POs', 'procurement/reports_1/poOutstanding', 1, 920, NULL, 'assessment', NULL, 50, 1;

INSERT IGNORE INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by, report)
SELECT 'Outstanding POs (Supplier-wise)', 'procurement/reports_1/poOutstandingSupplier', 1, 920, NULL, 'assessment', NULL, 60, 1;

INSERT IGNORE INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by, report)
SELECT 'Store Receipt / GRN Register', 'procurement/reports_1/srRegister', 1, 920, NULL, 'assessment', NULL, 70, 1;

-- Role maps for every report child inserted above (roles 1/12, access_type 4).
INSERT INTO role_menu_map (role_id, menu_id, access_type_id, updated_by)
SELECT r.role_id, m.menu_id, 4, 1
  FROM (SELECT 1 AS role_id UNION SELECT 12) r
  CROSS JOIN (
      SELECT menu_id FROM menu_mst
       WHERE menu_parent_id = 920 AND report = 1 AND active = 1
         AND menu_path LIKE 'procurement/reports_1/%'
  ) m
 WHERE NOT EXISTS (
      SELECT 1 FROM role_menu_map rm
       WHERE rm.role_id = r.role_id AND rm.menu_id = m.menu_id
 );

-- =============================================================================
-- ROLLBACK (manual):
--   DELETE rm FROM role_menu_map rm JOIN menu_mst m ON rm.menu_id = m.menu_id
--     WHERE m.menu_path LIKE 'procurement/reports_1/%';
--   DELETE FROM menu_mst WHERE menu_path LIKE 'procurement/reports_1/%' AND menu_parent_id = 920;
-- =============================================================================
