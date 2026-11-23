-- Portal menu HRMS > Process Reports > Attendance Process / Attendance Process - BULK for the winsome tenant DB
-- (legacy Smart-Eye Winsome menu Reports > ...). menu_name is UNIQUE and 'Reports' is taken (accounting),
-- hence 'Process Reports'. Page: nxtfront hrms/processReports/*, backend src/hrms/winsomeAttendanceProcess.py.
-- Roles copied from "Winsome Wages" (menu_path wagesmenus/winsomeWages). Idempotent.
INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'Process Reports', NULL, 1, 741, 2, NULL, 1, 4  -- group row: NULL path (a path makes the sidebar navigate -> 404)
WHERE NOT EXISTS (SELECT 1 FROM menu_mst WHERE menu_name = 'Process Reports');

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT x.n, x.p, 1, m.menu_id, 2, NULL, 1, x.o
FROM (SELECT 'Attendance Process' n, 'hrms/processReports/attendanceProcess' p, 1 o
      UNION ALL SELECT 'Attendance Process - BULK', 'hrms/processReports/attendanceProcessBulk', 2) x
JOIN menu_mst m ON m.menu_name = 'Process Reports'
WHERE NOT EXISTS (SELECT 1 FROM menu_mst e WHERE e.menu_path = x.p);

INSERT INTO role_menu_map (role_id, menu_id, access_type_id, updated_by, updated_date_time)
SELECT r.role_id, m.menu_id, r.access_type_id, r.updated_by, NOW()
FROM role_menu_map r
JOIN menu_mst w ON w.menu_id = r.menu_id AND w.menu_path = 'wagesmenus/winsomeWages'
JOIN menu_mst m ON m.menu_name = 'Process Reports' OR m.menu_path LIKE 'hrms/processReports/%'
WHERE NOT EXISTS (SELECT 1 FROM role_menu_map x WHERE x.role_id = r.role_id AND x.menu_id = m.menu_id);
