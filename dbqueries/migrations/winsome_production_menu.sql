-- Winsome portal menu "Production" (port of legacy Smart-Eye OMNU 35000, Winsome).
-- Target DB: winsome ONLY. Pages: nxtfront src/app/dashboardportal/winsomeProduction/*.
-- Role 13 gets the same access as the existing "Productions" menu (1005): parent view(1), pages edit(4).
-- Tenant-only rows, like menus 1000-1005 (no portal_menu_mst template).
--
-- Rollback:
--   DELETE FROM role_menu_map WHERE menu_id IN (SELECT menu_id FROM menu_mst WHERE menu_path LIKE 'winsomeProduction%');
--   DELETE FROM menu_mst WHERE menu_path LIKE 'winsomeProduction/%';
--   DELETE FROM menu_mst WHERE menu_path = 'winsomeProduction';

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'Production', 'winsomeProduction', 1, NULL, 1, 'factory', 1, NULL
WHERE NOT EXISTS (SELECT 1 FROM menu_mst WHERE menu_path = 'winsomeProduction');

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT c.name, c.path, 1, p.menu_id, 2, '', 1, c.ord
FROM (SELECT 'Production Winding' name, 'winsomeProduction/winding' path, 5 ord
      UNION ALL SELECT 'Production Beaming', 'winsomeProduction/beaming', 10
      UNION ALL SELECT 'Production Weaving', 'winsomeProduction/weaving', 15
      UNION ALL SELECT 'Daily Production', 'winsomeProduction/dailyProduction', 20
      UNION ALL SELECT 'Production Entry', 'winsomeProduction/productionEntry', 30
      UNION ALL SELECT 'Production Sack Sewing', 'winsomeProduction/sackSewing', 35) c
JOIN menu_mst p ON p.menu_path = 'winsomeProduction'
WHERE NOT EXISTS (SELECT 1 FROM menu_mst m WHERE m.menu_path = c.path);

INSERT INTO role_menu_map (role_id, menu_id, access_type_id, updated_by, updated_date_time)
SELECT 13, m.menu_id, IF(m.menu_path = 'winsomeProduction', 1, 4), 4, NOW()
FROM menu_mst m
WHERE m.menu_path LIKE 'winsomeProduction%'
  AND NOT EXISTS (SELECT 1 FROM role_menu_map r WHERE r.role_id = 13 AND r.menu_id = m.menu_id);
