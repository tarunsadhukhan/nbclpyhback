-- Portal sidebar entry: HRMS Master -> Winding Incentive Master (nbcl tenant).
-- Mirrors the sibling 'Attendance Incentive Master' row (menu_id 1008): parent 762, role 13, access 4.
-- The Winding Production menu already exists (menu_id 1003, 'production/windingproduction',
-- parent 1005 'Productions', role 13 access 4) — nothing to insert for it.
-- Target DB: nbcl
-- Rollback:
--   DELETE FROM role_menu_map WHERE menu_id = (SELECT menu_id FROM menu_mst WHERE menu_path = 'hrmsmasters/windingIncentiveMaster');
--   DELETE FROM menu_mst WHERE menu_path = 'hrmsmasters/windingIncentiveMaster';

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by, report)
SELECT 'Winding Incentive Master', 'hrmsmasters/windingIncentiveMaster', 1, 762, 1, NULL, 1, 8, NULL
WHERE NOT EXISTS (SELECT 1 FROM menu_mst WHERE menu_path = 'hrmsmasters/windingIncentiveMaster');

INSERT INTO role_menu_map (role_id, menu_id, access_type_id, updated_by)
SELECT 13, m.menu_id, 4, 4
FROM menu_mst m
WHERE m.menu_path = 'hrmsmasters/windingIncentiveMaster'
  AND NOT EXISTS (SELECT 1 FROM role_menu_map r WHERE r.menu_id = m.menu_id AND r.role_id = 13);
