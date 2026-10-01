-- Portal sidebar entry: HRMS -> HRMS Reports -> Period Wise Attendance Register.
-- Legacy "Attendance Fort Night Wise": employee x day hours pivot, dept totals.
-- Mirrors the sibling report rows under hub 'hrms/hrmsreports' (report=1, icon 'assessment');
-- role grants are copied from the sibling 'Spell Wise Summary' row.
-- Target DBs: nbjcl, winsome
-- Rollback:
--   DELETE FROM role_menu_map WHERE menu_id = (SELECT menu_id FROM menu_mst WHERE menu_path = 'hrms/hrmsreports/periodAttendance');
--   DELETE FROM menu_mst WHERE menu_path = 'hrms/hrmsreports/periodAttendance';

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by, report)
SELECT 'Period Wise Attendance Register', 'hrms/hrmsreports/periodAttendance', 1, h.menu_id, NULL, 'assessment', NULL, 15, 1
FROM menu_mst h
WHERE h.menu_path = 'hrms/hrmsreports'
  AND NOT EXISTS (SELECT 1 FROM menu_mst x WHERE x.menu_path = 'hrms/hrmsreports/periodAttendance');

INSERT INTO role_menu_map (role_id, menu_id, access_type_id, updated_by)
SELECT r.role_id, m.menu_id, r.access_type_id, 4
FROM menu_mst m
JOIN menu_mst s ON s.menu_path = 'hrms/hrmsreports/spellWise'
JOIN role_menu_map r ON r.menu_id = s.menu_id
WHERE m.menu_path = 'hrms/hrmsreports/periodAttendance'
  AND NOT EXISTS (SELECT 1 FROM role_menu_map x WHERE x.menu_id = m.menu_id AND x.role_id = r.role_id);
