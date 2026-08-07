-- Seed the Stores Issue Check List report menu (inventory reports navigator).
-- Target: tenant DB (applied to dev3 and sls on 2026-08-04; menu_id 968 in both).
-- Note: the role list below is dev3's convention (roles 1/3/12). On sls the
-- role rows were instead cloned from sibling report menu 935 (roles 13/20 at
-- access 4 + operational roles at access 1) — clone from a sibling when
-- applying to other tenants.

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_icon, order_by, report)
SELECT 'Stores Issue Check List', 'inventory/reports/issueCheckList', 1, 739, 'assessment', 25, 1
WHERE NOT EXISTS (
    SELECT 1 FROM menu_mst WHERE menu_path = 'inventory/reports/issueCheckList'
);

INSERT INTO role_menu_map (role_id, menu_id, access_type_id, updated_by, updated_date_time)
SELECT r.role_id, m.menu_id, 4, 1, NOW()
FROM (SELECT 1 AS role_id UNION SELECT 3 UNION SELECT 12) AS r
JOIN menu_mst AS m ON m.menu_path = 'inventory/reports/issueCheckList'
WHERE NOT EXISTS (
    SELECT 1 FROM role_menu_map x
    WHERE x.role_id = r.role_id AND x.menu_id = m.menu_id AND x.access_type_id = 4
);
