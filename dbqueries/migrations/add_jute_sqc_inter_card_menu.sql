-- Migration: Add Portal menu entry for the new Jute SQC page (Inter Card & Tow Breaker)
-- Module: juteSQC (R-08-07A Inter Card & Tow Breaker Sliver Weight)
-- Date: 2026-06-27
-- Applies to: tenant database dev3 (QA). Promote to other tenants later.
--
-- New page lives under the existing "Jute SQC" parent (menu_mst.menu_id = 781,
-- module_mst_id = 2), next to Spreader (order 40) and Breaker Card (order 50). FE route:
--   juteSQC/interCard  -> Inter Card & Tow Breaker SQC (R-08-07A)
-- Mirrors add_jute_sqc_spreader_breaker_menus.sql: ALSO grants access (the request is "for
-- access") — role_menu_map mirrors the current sibling SQC children (role_id=1,
-- access_type_id=4 edit, updated_by=14). All inserts idempotent (NOT EXISTS on menu_path /
-- (role_id, menu_id)); menu_id and role_menu_mapping_id are auto_increment.

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by, report)
SELECT 'Inter Card SQC', 'juteSQC/interCard', 1, 781, NULL, 'view_week', 2, 60, NULL
WHERE NOT EXISTS (SELECT 1 FROM menu_mst WHERE menu_path = 'juteSQC/interCard');

INSERT INTO role_menu_map (role_id, menu_id, access_type_id, updated_by, updated_date_time)
SELECT 1, m.menu_id, 4, 14, NOW() FROM menu_mst m
WHERE m.menu_path = 'juteSQC/interCard'
  AND NOT EXISTS (SELECT 1 FROM role_menu_map r WHERE r.menu_id = m.menu_id AND r.role_id = 1);

-- Rollback:
-- DELETE r FROM role_menu_map r JOIN menu_mst m ON m.menu_id = r.menu_id
--   WHERE m.menu_path = 'juteSQC/interCard';
-- DELETE FROM menu_mst WHERE menu_path = 'juteSQC/interCard';
