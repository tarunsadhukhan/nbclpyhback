-- Add the "Stores Inventory List" report under Inventory Reports (menu_id 739)
-- in a tenant DB (default target: dev3).
--
-- Mirrors the jute report-leaf convention:
--   report = 1, menu_icon = 'assessment', active = 1, order_by in 10s,
--   parent = the reports-page menu (739 = inventory/reports).
-- menu_path MUST match the Next.js route folder exactly:
--   src/app/dashboardportal/inventory/reports/storesInventory/page.tsx
--
-- Access: report_menu_tree (the navigator dropdown) ignores roles, and the
-- portal permission check inherits from the parent 'inventory/reports' via a
-- path segment-walk. The role_menu_map rows below are added only to match the
-- existing convention (roles 1, 3, 12 @ access_type_id = 4).

INSERT INTO menu_mst
  (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by, report)
VALUES
  ('Stores Inventory List', 'inventory/reports/storesInventory', 1, 739, NULL, 'assessment', NULL, 10, 1);

SET @new_menu_id = LAST_INSERT_ID();

INSERT INTO role_menu_map (role_id, menu_id, access_type_id, updated_by, updated_date_time)
VALUES
  (1,  @new_menu_id, 4, 1, NOW()),
  (3,  @new_menu_id, 4, 1, NOW()),
  (12, @new_menu_id, 4, 1, NOW());

-- Rollback:
-- DELETE FROM role_menu_map
--   WHERE menu_id = (SELECT menu_id FROM menu_mst WHERE menu_path = 'inventory/reports/storesInventory');
-- DELETE FROM menu_mst WHERE menu_path = 'inventory/reports/storesInventory';
