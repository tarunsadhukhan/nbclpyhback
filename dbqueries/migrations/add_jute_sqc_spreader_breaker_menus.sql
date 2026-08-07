-- Migration: Add Portal menu entries for the new Jute SQC pages (Spreader + Breaker Card)
-- Module: juteSQC (R-08-03/04 Spreader, R-08-05/06/07 Breaker Card)
-- Date: 2026-06-27
-- Applies to: tenant database dev3 (QA). Promote to other tenants later.
--
-- Two new pages live under the existing "Jute SQC" parent (menu_mst.menu_id = 781,
-- module_mst_id = 2). FE routes already exist:
--   juteSQC/spreader     -> Spreader SQC  (R-08-04 Roll Wt + R-08-03 Sliver Wt tabs)
--   juteSQC/breakerCard  -> Breaker Card SQC (R-08-05/06/07)
-- Unlike seed_beaming_sqc_menu.sql (menu row only), this ALSO grants access because the
-- request is "for access": role_menu_map mirrors the current sibling SQC children
-- (Spinning 782, Beaming 788, ...): role_id=1, access_type_id=4 (edit), updated_by=14.
-- All inserts idempotent (NOT EXISTS on menu_path / (role_id, menu_id)); menu_id and
-- role_menu_mapping_id are auto_increment.

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by, report)
SELECT 'Spreader SQC', 'juteSQC/spreader', 1, 781, NULL, 'settings', 2, 40, NULL
WHERE NOT EXISTS (SELECT 1 FROM menu_mst WHERE menu_path = 'juteSQC/spreader');

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by, report)
SELECT 'Breaker Card SQC', 'juteSQC/breakerCard', 1, 781, NULL, 'grid_view', 2, 50, NULL
WHERE NOT EXISTS (SELECT 1 FROM menu_mst WHERE menu_path = 'juteSQC/breakerCard');

INSERT INTO role_menu_map (role_id, menu_id, access_type_id, updated_by, updated_date_time)
SELECT 1, m.menu_id, 4, 14, NOW() FROM menu_mst m
WHERE m.menu_path = 'juteSQC/spreader'
  AND NOT EXISTS (SELECT 1 FROM role_menu_map r WHERE r.menu_id = m.menu_id AND r.role_id = 1);

INSERT INTO role_menu_map (role_id, menu_id, access_type_id, updated_by, updated_date_time)
SELECT 1, m.menu_id, 4, 14, NOW() FROM menu_mst m
WHERE m.menu_path = 'juteSQC/breakerCard'
  AND NOT EXISTS (SELECT 1 FROM role_menu_map r WHERE r.menu_id = m.menu_id AND r.role_id = 1);

-- Rollback:
-- DELETE r FROM role_menu_map r JOIN menu_mst m ON m.menu_id = r.menu_id
--   WHERE m.menu_path IN ('juteSQC/spreader','juteSQC/breakerCard');
-- DELETE FROM menu_mst WHERE menu_path IN ('juteSQC/spreader','juteSQC/breakerCard');
