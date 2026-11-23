-- Winsome portal menu "Winsome Gratuity" (port of legacy Smart-Eye OMNU 40000 "Gratuity", Winsome).
-- Target DB: winsome ONLY. Pages: nxtfront src/app/dashboardportal/winsomeGratuity/*,
-- backend pyhback src/hrms/winsomeGratuity.py. Tables mirrored by migrate_payowagesrate_ocp.py
-- (PayOTSW PayGratEReason PayGratOSTL PayGratSTL1 PayGratOGratuity PayGratGratuity1 PayGratNominee
-- PayGrat_Voucher PayEmpNominee).
-- Role 13 gets the same access as the other Winsome menus: parent view(1), pages edit(4). Idempotent.
--
-- Rollback:
--   DELETE FROM role_menu_map WHERE menu_id IN (SELECT menu_id FROM menu_mst WHERE menu_path LIKE 'winsomeGratuity%');
--   DELETE FROM menu_mst WHERE menu_path LIKE 'winsomeGratuity/%';
--   DELETE FROM menu_mst WHERE menu_path = 'winsomeGratuity';

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'Winsome Gratuity', 'winsomeGratuity', 1, NULL, 1, 'payments', 1, NULL
WHERE NOT EXISTS (SELECT 1 FROM menu_mst WHERE menu_path = 'winsomeGratuity');

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT c.name, c.path, 1, p.menu_id, 2, '', 1, c.ord
FROM (SELECT 'TSW' name, 'winsomeGratuity/tsw' path, 30 ord
      UNION ALL SELECT 'Gratuity Calculation', 'winsomeGratuity/calculation', 40
      UNION ALL SELECT 'Gratuity Details', 'winsomeGratuity/details', 45
      UNION ALL SELECT 'Gratuity STL Entry', 'winsomeGratuity/stlEntry', 50
      UNION ALL SELECT 'Gratuity Payment Request', 'winsomeGratuity/paymentRequest', 55
      UNION ALL SELECT 'Gratuity Payment Approval', 'winsomeGratuity/paymentApproval', 60) c
JOIN menu_mst p ON p.menu_path = 'winsomeGratuity'
WHERE NOT EXISTS (SELECT 1 FROM menu_mst m WHERE m.menu_path = c.path)
ORDER BY c.ord;  -- the sidebar lists sub-menus by menu_id

INSERT INTO role_menu_map (role_id, menu_id, access_type_id, updated_by, updated_date_time)
SELECT 13, m.menu_id, IF(m.menu_path = 'winsomeGratuity', 1, 4), 4, NOW()
FROM menu_mst m
WHERE m.menu_path LIKE 'winsomeGratuity%'
  AND NOT EXISTS (SELECT 1 FROM role_menu_map r WHERE r.role_id = 13 AND r.menu_id = m.menu_id);
