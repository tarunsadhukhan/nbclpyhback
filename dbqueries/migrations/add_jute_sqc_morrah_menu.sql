-- Migration: Add Portal menu entry for Morrah Weight SQC (R-08-01)
-- Module: juteSQC (R-08-01 Morrah Weight -- raw-jute heap weight QC, Selection stage)
-- Date: 2026-06-28
-- Applies to: tenant database dev3 (QA). Promote to other tenants later.
--
-- The R-08-01 page was code-complete (BE router + FE juteSQC/r-08-01) but never had a
-- menu seeded on dev3. This adds it under the existing "Jute SQC" parent (menu_id 781,
-- module_mst_id 2) at order_by 5 so it leads the SQC list (Selection is first in the
-- process flow). Mirrors the sibling SQC menu migrations: also grants role 1 access.
-- All inserts idempotent (NOT EXISTS on menu_path / role_id+menu_id).
;

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by, report)
SELECT 'Morrah Weight SQC', 'juteSQC/r-08-01', 1, 781, NULL, 'scale', 2, 5, NULL
WHERE NOT EXISTS (SELECT 1 FROM menu_mst WHERE menu_path = 'juteSQC/r-08-01');

INSERT INTO role_menu_map (role_id, menu_id, access_type_id, updated_by, updated_date_time)
SELECT 1, m.menu_id, 4, 14, NOW() FROM menu_mst m
WHERE m.menu_path = 'juteSQC/r-08-01'
  AND NOT EXISTS (SELECT 1 FROM role_menu_map r WHERE r.menu_id = m.menu_id AND r.role_id = 1);

-- Rollback (run manually, removing the comment dashes):
--   DELETE r FROM role_menu_map r JOIN menu_mst m ON m.menu_id = r.menu_id WHERE m.menu_path = 'juteSQC/r-08-01'
--   DELETE FROM menu_mst WHERE menu_path = 'juteSQC/r-08-01'
