-- Migration: add Jute SQC portal menus to sls tenant (copied from dev3.menu_mst 781/782)
-- Target DB: sls
-- menu_mst only (role_menu_map intentionally NOT added per request)
-- Rollback:
--   DELETE FROM menu_mst WHERE menu_id IN (784, 785);

INSERT INTO menu_mst (menu_id, menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
VALUES (784, 'Jute SQC', 'juteSQC', 1, NULL, NULL, 'fact_check', 2, 110);

INSERT INTO menu_mst (menu_id, menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
VALUES (785, 'Spinning SQC', 'juteSQC/spinning', 1, 784, NULL, 'speed', 2, 10);
