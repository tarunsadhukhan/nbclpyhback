-- Portal sidebar entry: HRMS Master -> Misc Earn Master (nbcl tenant).
-- Mirrors the sibling 'Worker Rate Muster' row (menu_id 1006): parent 762, role 13, access 4.
-- No portal_menu_mst template row exists for any hrmsmasters page in vowconsole3, so none is added here.
-- Target DB: nbcl
-- Rollback:
--   DELETE FROM role_menu_map WHERE menu_id = (SELECT menu_id FROM menu_mst WHERE menu_path = 'hrmsmasters/miscEarnMaster');
--   DELETE FROM menu_mst WHERE menu_path = 'hrmsmasters/miscEarnMaster';

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by, report)
SELECT 'Misc Earn Master', 'hrmsmasters/miscEarnMaster', 1, 762, 1, NULL, 1, 8, NULL
WHERE NOT EXISTS (SELECT 1 FROM menu_mst WHERE menu_path = 'hrmsmasters/miscEarnMaster');

INSERT INTO role_menu_map (role_id, menu_id, access_type_id, updated_by)
SELECT 13, m.menu_id, 4, 4
FROM menu_mst m
WHERE m.menu_path = 'hrmsmasters/miscEarnMaster'
  AND NOT EXISTS (SELECT 1 FROM role_menu_map r WHERE r.menu_id = m.menu_id AND r.role_id = 13);
