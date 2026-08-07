-- Cash Hands Report menu under HRMS Reports (955), mirroring the role access
-- rows of the Full Attendance report (956). Idempotent; applied to sls as
-- menu_id 980. Run against another tenant to add the report there.
--
-- The report also needs these tables in the target tenant:
--   outsider_rate_approve        (Cash/Daily Rate Entry master)
--   daily_cash_outsider_payment  (processed payment rows this report prints)

INSERT INTO menu_mst (menu_name, menu_path, menu_parent_id, menu_icon, report, active, order_by)
SELECT 'Cash Hands Report', 'hrms/hrmsreports/cashHands', 955, 'assessment', 1, 1, 65
WHERE NOT EXISTS (
    SELECT 1 FROM menu_mst m WHERE m.menu_path = 'hrms/hrmsreports/cashHands'
);

INSERT INTO role_menu_map (role_id, menu_id, access_type_id, updated_by)
SELECT src.role_id, m.menu_id, src.access_type_id, 4
FROM menu_mst m
JOIN (
    SELECT DISTINCT role_id, access_type_id FROM role_menu_map WHERE menu_id = 956
) AS src
WHERE m.menu_path = 'hrms/hrmsreports/cashHands'
  AND NOT EXISTS (
      SELECT 1 FROM role_menu_map r
      WHERE r.menu_id = m.menu_id AND r.role_id = src.role_id
        AND r.access_type_id = src.access_type_id
  );
