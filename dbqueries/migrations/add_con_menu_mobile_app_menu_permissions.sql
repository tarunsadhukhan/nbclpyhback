-- Tenant Admin sidebar: "Mobile App Menu Permissions" under "User Management Portal" (con_menu_id 6),
-- right after "Approval Hierarchy" (con_menu_id 24). Role access copied from Approval Hierarchy.
-- Target DB: console DB (maindata on the NBCL VPS).

INSERT INTO con_menu_master (con_menu_name, con_menu_parent_id, active, con_menu_path, con_menu_icon, order_by)
-- ponytail: con_menu_name is varchar(25), so "Mobile App Menu Permissions" (27) is shortened
SELECT 'Mobile Menu Permissions', 6, 1, '/dashboardadmin/mobileAppMenuPermissions', NULL, NULL
FROM DUAL WHERE NOT EXISTS (SELECT 1 FROM con_menu_master WHERE con_menu_path = '/dashboardadmin/mobileAppMenuPermissions');

INSERT INTO con_role_menu_map (con_role_id, con_menu_id)
SELECT r.con_role_id, m.con_menu_id
FROM con_role_menu_map r
JOIN con_menu_master m ON m.con_menu_path = '/dashboardadmin/mobileAppMenuPermissions'
WHERE r.con_menu_id = 24
  AND NOT EXISTS (SELECT 1 FROM con_role_menu_map x WHERE x.con_role_id = r.con_role_id AND x.con_menu_id = m.con_menu_id);

-- Rollback:
-- DELETE r FROM con_role_menu_map r JOIN con_menu_master m ON m.con_menu_id = r.con_menu_id
--   WHERE m.con_menu_path = '/dashboardadmin/mobileAppMenuPermissions';
-- DELETE FROM con_menu_master WHERE con_menu_path = '/dashboardadmin/mobileAppMenuPermissions';
