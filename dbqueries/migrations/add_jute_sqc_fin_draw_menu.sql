-- Migration: Add Portal menu entry for the new Jute SQC page (Finisher Drawing)
-- Module: juteSQC (R-08-12/13/14 Finisher Drawing Sliver Weight)
-- Date: 2026-06-27
-- Applies to: tenant database dev3 (QA). Promote to other tenants later.
--
-- New page lives under the existing "Jute SQC" parent (menu_mst.menu_id = 781,
-- module_mst_id = 2), next to Inter Card (order 60). FE route:
--   juteSQC/finDraw  -> Finisher Drawing SQC (R-08-12/13/14)
-- Mirrors add_jute_sqc_inter_card_menu.sql: ALSO grants access — role_menu_map mirrors the
-- current sibling SQC children (role_id=1, access_type_id=4 edit, updated_by=14). All inserts
-- idempotent (NOT EXISTS on menu_path / (role_id, menu_id)); ids are auto_increment.

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by, report)
SELECT 'Finisher Drawing SQC', 'juteSQC/finDraw', 1, 781, NULL, 'view_week', 2, 70, NULL
WHERE NOT EXISTS (SELECT 1 FROM menu_mst WHERE menu_path = 'juteSQC/finDraw');

INSERT INTO role_menu_map (role_id, menu_id, access_type_id, updated_by, updated_date_time)
SELECT 1, m.menu_id, 4, 14, NOW() FROM menu_mst m
WHERE m.menu_path = 'juteSQC/finDraw'
  AND NOT EXISTS (SELECT 1 FROM role_menu_map r WHERE r.menu_id = m.menu_id AND r.role_id = 1);

-- Rollback:
-- DELETE r FROM role_menu_map r JOIN menu_mst m ON m.menu_id = r.menu_id
--   WHERE m.menu_path = 'juteSQC/finDraw';
-- DELETE FROM menu_mst WHERE menu_path = 'juteSQC/finDraw';
