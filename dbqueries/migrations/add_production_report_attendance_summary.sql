-- Add "Attendance Summary" report under Production Reports (menu_id 945) in a
-- tenant DB (default target: dev3). Mirrors the report-leaf convention:
--   report = 1, menu_icon = 'assessment', active = 1, order_by in 10s,
--   parent = 945 (juteProduction/report), + role_menu_map for roles 1, 3, 12.
-- menu_path MUST match the Next.js route folder:
--   src/app/dashboardportal/juteProduction/report/attendanceSummary/page.tsx

INSERT INTO menu_mst
  (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by, report)
VALUES
  ('Attendance Summary', 'juteProduction/report/attendanceSummary', 1, 945, NULL, 'assessment', NULL, 10, 1);

SET @m = LAST_INSERT_ID();

INSERT INTO role_menu_map (role_id, menu_id, access_type_id, updated_by, updated_date_time)
VALUES (1, @m, 4, 1, NOW()), (3, @m, 4, 1, NOW()), (12, @m, 4, 1, NOW());

-- Rollback:
-- DELETE rmm FROM role_menu_map rmm JOIN menu_mst m ON m.menu_id = rmm.menu_id
--   WHERE m.menu_path = 'juteProduction/report/attendanceSummary';
-- DELETE FROM menu_mst WHERE menu_path = 'juteProduction/report/attendanceSummary';
