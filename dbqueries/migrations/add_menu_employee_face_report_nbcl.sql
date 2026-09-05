-- Portal sidebar entry: HRMS -> HRMS Reports -> Employee Face Register (nbcl tenant).
-- Report over employee_face_mst joined to emp_code / name / department.
-- Mirrors the sibling report rows under hub 'hrms/hrmsreports' (report=1, icon 'assessment');
-- role grants are copied from the hub row so whoever sees the hub sees this report.
-- No portal_menu_mst template row exists for the hrms report pages in vowconsole3, so none is added here.
-- Target DB: nbcl
-- Rollback:
--   DELETE FROM role_menu_map WHERE menu_id = (SELECT menu_id FROM menu_mst WHERE menu_path = 'hrms/hrmsreports/employeeFace');
--   DELETE FROM menu_mst WHERE menu_path = 'hrms/hrmsreports/employeeFace';

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by, report)
SELECT 'Employee Face Register', 'hrms/hrmsreports/employeeFace', 1, h.menu_id, NULL, 'assessment', NULL, 210, 1
FROM menu_mst h
WHERE h.menu_path = 'hrms/hrmsreports'
  AND NOT EXISTS (SELECT 1 FROM menu_mst x WHERE x.menu_path = 'hrms/hrmsreports/employeeFace');

INSERT INTO role_menu_map (role_id, menu_id, access_type_id, updated_by)
SELECT r.role_id, m.menu_id, r.access_type_id, 4
FROM menu_mst m
JOIN menu_mst h ON h.menu_path = 'hrms/hrmsreports'
JOIN role_menu_map r ON r.menu_id = h.menu_id
WHERE m.menu_path = 'hrms/hrmsreports/employeeFace'
  AND NOT EXISTS (SELECT 1 FROM role_menu_map x WHERE x.menu_id = m.menu_id AND x.role_id = r.role_id);
