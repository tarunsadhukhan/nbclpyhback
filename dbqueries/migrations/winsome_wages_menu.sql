-- Portal menu "Winsome Wages" (Wages Menus > Winsome Wages) for the winsome tenant DB.
-- Page: nxtfront src/app/dashboardportal/wagesmenus/winsomeWages, backend src/hrms/winsomeWagesProcess.py.
-- Same parent / roles as "NBJCL Wages/Salary Process" (menu 1019). Idempotent.
INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'Winsome Wages', 'wagesmenus/winsomeWages', 1, 1014, 2, NULL, 1, 3
WHERE NOT EXISTS (SELECT 1 FROM menu_mst WHERE menu_path = 'wagesmenus/winsomeWages');

INSERT INTO role_menu_map (role_id, menu_id, access_type_id, updated_by, updated_date_time)
SELECT r.role_id, m.menu_id, r.access_type_id, r.updated_by, NOW()
FROM role_menu_map r JOIN menu_mst m ON m.menu_path = 'wagesmenus/winsomeWages'
WHERE r.menu_id = 1019
  AND NOT EXISTS (SELECT 1 FROM role_menu_map x WHERE x.role_id = r.role_id AND x.menu_id = m.menu_id);
