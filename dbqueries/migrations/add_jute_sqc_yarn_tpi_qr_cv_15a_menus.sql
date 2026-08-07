-- Migration: Add Portal menu entries for the two new spinning Jute SQC pages
-- Module: juteSQC (R-08-17 Yarn TPI, R-08-15A Yarn QR-CV Special Purpose)
-- Date: 2026-06-27
-- Applies to: tenant database dev3 (QA). Promote to other tenants later.
--
-- Two new pages live under the existing "Jute SQC" parent (menu_mst.menu_id = 781,
-- module_mst_id = 2). FE routes:
--   juteSQC/yarnTpi   -> Yarn TPI SQC            (R-08-17, order 90)
--   juteSQC/qrCv15a   -> Yarn QR-CV Special SQC  (R-08-15A, order 100)
-- Mirrors add_jute_sqc_spreader_breaker_menus.sql: role_menu_map grants access for
-- role_id=1, access_type_id=4 (edit), updated_by=14. All inserts idempotent (NOT EXISTS
-- on menu_path / (role_id, menu_id)); menu_id and role_menu_mapping_id are auto_increment.

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by, report)
SELECT 'Yarn TPI SQC', 'juteSQC/yarnTpi', 1, 781, NULL, 'settings', 2, 90, NULL
WHERE NOT EXISTS (SELECT 1 FROM menu_mst WHERE menu_path = 'juteSQC/yarnTpi');

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by, report)
SELECT 'Yarn QR-CV Special SQC', 'juteSQC/qrCv15a', 1, 781, NULL, 'grid_view', 2, 100, NULL
WHERE NOT EXISTS (SELECT 1 FROM menu_mst WHERE menu_path = 'juteSQC/qrCv15a');

INSERT INTO role_menu_map (role_id, menu_id, access_type_id, updated_by, updated_date_time)
SELECT 1, m.menu_id, 4, 14, NOW() FROM menu_mst m
WHERE m.menu_path = 'juteSQC/yarnTpi'
  AND NOT EXISTS (SELECT 1 FROM role_menu_map r WHERE r.menu_id = m.menu_id AND r.role_id = 1);

INSERT INTO role_menu_map (role_id, menu_id, access_type_id, updated_by, updated_date_time)
SELECT 1, m.menu_id, 4, 14, NOW() FROM menu_mst m
WHERE m.menu_path = 'juteSQC/qrCv15a'
  AND NOT EXISTS (SELECT 1 FROM role_menu_map r WHERE r.menu_id = m.menu_id AND r.role_id = 1);

-- Rollback:
-- DELETE r FROM role_menu_map r JOIN menu_mst m ON m.menu_id = r.menu_id
--   WHERE m.menu_path IN ('juteSQC/yarnTpi','juteSQC/qrCv15a');
-- DELETE FROM menu_mst WHERE menu_path IN ('juteSQC/yarnTpi','juteSQC/qrCv15a');
