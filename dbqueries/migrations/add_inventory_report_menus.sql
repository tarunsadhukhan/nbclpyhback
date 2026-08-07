-- Add the remaining inventory reports under Inventory Reports (menu_id 739) in a
-- tenant DB (default target: dev3). "Stores Inventory List" (menu 935) already
-- exists from add_stores_inventory_report_menu.sql; this adds the other 9.
--
-- Convention (matches jute + the existing 935 row):
--   report = 1, menu_icon = 'assessment', active = 1, parent = 739,
--   order_by in 10s, + role_menu_map rows for roles 1, 3, 12 @ access_type_id 4.
-- menu_path MUST match each Next.js route folder under
--   src/app/dashboardportal/inventory/reports/<slug>/page.tsx

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by, report)
VALUES ('Issue Item-wise', 'inventory/reports/issueItemwise', 1, 739, NULL, 'assessment', NULL, 20, 1);
SET @m = LAST_INSERT_ID();
INSERT INTO role_menu_map (role_id, menu_id, access_type_id, updated_by, updated_date_time)
VALUES (1, @m, 4, 1, NOW()), (3, @m, 4, 1, NOW()), (12, @m, 4, 1, NOW());

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by, report)
VALUES ('Item Ledger', 'inventory/reports/itemLedger', 1, 739, NULL, 'assessment', NULL, 30, 1);
SET @m = LAST_INSERT_ID();
INSERT INTO role_menu_map (role_id, menu_id, access_type_id, updated_by, updated_date_time)
VALUES (1, @m, 4, 1, NOW()), (3, @m, 4, 1, NOW()), (12, @m, 4, 1, NOW());

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by, report)
VALUES ('Item Month-wise', 'inventory/reports/itemMonthwise', 1, 739, NULL, 'assessment', NULL, 40, 1);
SET @m = LAST_INSERT_ID();
INSERT INTO role_menu_map (role_id, menu_id, access_type_id, updated_by, updated_date_time)
VALUES (1, @m, 4, 1, NOW()), (3, @m, 4, 1, NOW()), (12, @m, 4, 1, NOW());

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by, report)
VALUES ('Stores Min-Max', 'inventory/reports/inventoryMinMax', 1, 739, NULL, 'assessment', NULL, 50, 1);
SET @m = LAST_INSERT_ID();
INSERT INTO role_menu_map (role_id, menu_id, access_type_id, updated_by, updated_date_time)
VALUES (1, @m, 4, 1, NOW()), (3, @m, 4, 1, NOW()), (12, @m, 4, 1, NOW());

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by, report)
VALUES ('Consumption Report IS-01', 'inventory/reports/consumptionIs01', 1, 739, NULL, 'assessment', NULL, 60, 1);
SET @m = LAST_INSERT_ID();
INSERT INTO role_menu_map (role_id, menu_id, access_type_id, updated_by, updated_date_time)
VALUES (1, @m, 4, 1, NOW()), (3, @m, 4, 1, NOW()), (12, @m, 4, 1, NOW());

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by, report)
VALUES ('Consumption Report IS-02', 'inventory/reports/consumptionIs02', 1, 739, NULL, 'assessment', NULL, 70, 1);
SET @m = LAST_INSERT_ID();
INSERT INTO role_menu_map (role_id, menu_id, access_type_id, updated_by, updated_date_time)
VALUES (1, @m, 4, 1, NOW()), (3, @m, 4, 1, NOW()), (12, @m, 4, 1, NOW());

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by, report)
VALUES ('Consumption Report IS-03', 'inventory/reports/consumptionIs03', 1, 739, NULL, 'assessment', NULL, 80, 1);
SET @m = LAST_INSERT_ID();
INSERT INTO role_menu_map (role_id, menu_id, access_type_id, updated_by, updated_date_time)
VALUES (1, @m, 4, 1, NOW()), (3, @m, 4, 1, NOW()), (12, @m, 4, 1, NOW());

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by, report)
VALUES ('Consumption Report IS-05', 'inventory/reports/consumptionIs05', 1, 739, NULL, 'assessment', NULL, 90, 1);
SET @m = LAST_INSERT_ID();
INSERT INTO role_menu_map (role_id, menu_id, access_type_id, updated_by, updated_date_time)
VALUES (1, @m, 4, 1, NOW()), (3, @m, 4, 1, NOW()), (12, @m, 4, 1, NOW());

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by, report)
VALUES ('Consumption Report IS-06', 'inventory/reports/consumptionIs06', 1, 739, NULL, 'assessment', NULL, 100, 1);
SET @m = LAST_INSERT_ID();
INSERT INTO role_menu_map (role_id, menu_id, access_type_id, updated_by, updated_date_time)
VALUES (1, @m, 4, 1, NOW()), (3, @m, 4, 1, NOW()), (12, @m, 4, 1, NOW());

-- Rollback:
-- DELETE rmm FROM role_menu_map rmm JOIN menu_mst m ON m.menu_id = rmm.menu_id
--   WHERE m.menu_path IN ('inventory/reports/issueItemwise','inventory/reports/itemLedger',
--     'inventory/reports/itemMonthwise','inventory/reports/inventoryMinMax',
--     'inventory/reports/consumptionIs01','inventory/reports/consumptionIs02',
--     'inventory/reports/consumptionIs03','inventory/reports/consumptionIs05',
--     'inventory/reports/consumptionIs06');
-- DELETE FROM menu_mst WHERE menu_path IN ('inventory/reports/issueItemwise','inventory/reports/itemLedger',
--     'inventory/reports/itemMonthwise','inventory/reports/inventoryMinMax',
--     'inventory/reports/consumptionIs01','inventory/reports/consumptionIs02',
--     'inventory/reports/consumptionIs03','inventory/reports/consumptionIs05',
--     'inventory/reports/consumptionIs06');
