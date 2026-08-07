-- Add 4 HRMS portal menus to dev3 (synced from sls).
-- Parent resolved by name (HRMS); menu_type_id=2 (custom), module_mst_id=1 (HRMS).
-- menu_id is auto_increment - never specify it.
-- Rollback:
--   DELETE FROM menu_mst WHERE menu_name IN ('Attendance','Attendance Calendar','On boarding','Pay Roll');

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'Attendance', 'hrms/attendance', 1, m.menu_id, 2, NULL, 1, 2 FROM menu_mst m WHERE m.menu_name = 'HRMS';

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'Attendance Calendar', 'hrms/attendanceCalendar', 1, m.menu_id, 2, NULL, 1, 2 FROM menu_mst m WHERE m.menu_name = 'HRMS';

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'On boarding', 'hrms/onBoarding', 1, m.menu_id, 2, NULL, 1, 2 FROM menu_mst m WHERE m.menu_name = 'HRMS';

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'Pay Roll', 'hrms/payRoll', 1, m.menu_id, 2, NULL, 1, 2 FROM menu_mst m WHERE m.menu_name = 'HRMS';
