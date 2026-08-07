-- Migration: Add Portal menu entry for the new Jute SQC page (Humidity Recording)
-- Module: juteSQC (plant-wide department temperature / RH log)
-- Date: 2026-06-28
-- Applies to: tenant database dev3 (QA). Promote to other tenants later.
--
-- New page lives under the existing "Jute SQC" parent (menu_mst.menu_id = 781,
-- module_mst_id = 2). FE route:
--   juteSQC/humidity  -> Humidity Recording SQC
-- Mirrors add_jute_sqc_emulsion_menu.sql: ALSO grants access -- role_menu_map mirrors the
-- current sibling SQC children (role_id=1, access_type_id=4 edit, updated_by=14). All inserts
-- idempotent (NOT EXISTS on menu_path / role_id+menu_id) plus menu_id and role_menu_mapping_id
-- are auto_increment.
;

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by, report)
SELECT 'Humidity Recording SQC', 'juteSQC/humidity', 1, 781, NULL, 'thermostat', 2, 170, NULL
WHERE NOT EXISTS (SELECT 1 FROM menu_mst WHERE menu_path = 'juteSQC/humidity');

INSERT INTO role_menu_map (role_id, menu_id, access_type_id, updated_by, updated_date_time)
SELECT 1, m.menu_id, 4, 14, NOW() FROM menu_mst m
WHERE m.menu_path = 'juteSQC/humidity'
  AND NOT EXISTS (SELECT 1 FROM role_menu_map r WHERE r.menu_id = m.menu_id AND r.role_id = 1);

-- Rollback (run the two statements below manually, removing the comment dashes):
-- DELETE r FROM role_menu_map r JOIN menu_mst m ON m.menu_id = r.menu_id WHERE m.menu_path = 'juteSQC/humidity'
-- DELETE FROM menu_mst WHERE menu_path = 'juteSQC/humidity'
