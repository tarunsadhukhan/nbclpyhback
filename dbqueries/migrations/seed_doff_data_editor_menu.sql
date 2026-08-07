-- Migration: Seed 'Doff Data Editor' menu entry under 'Jute Production' parent
-- Date: 2026-07-27
-- Applies to: dev3 ONLY (admin/editor correction page for spinning doff data)
--
-- Notes:
--   - Same parent (Jute Production) and same module_mst_id as the sibling
--     'Spinning Production' row (menu_id 776 in dev3: menu_parent_id=768,
--     module_mst_id=1).
--   - role_menu_map copied from whatever roles currently have 'Spinning
--     Production' access (dev3 currently: role_id=1 'Super Admin',
--     access_type_id=4 'edit' only) — trim/extend per tenant admin as needed.
--   - Does NOT touch vowconsole3/portal_menu_mst (template sync happens at
--     deploy time, per house rules).

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'Doff Data Editor', CONCAT(p.menu_path, '/doffDataEditor'), 1, s.menu_parent_id, NULL, 'edit_note',
       s.module_mst_id, 171
FROM (SELECT menu_id, menu_path FROM menu_mst WHERE menu_name = 'Jute Production' LIMIT 1) p
JOIN (SELECT menu_parent_id, module_mst_id FROM menu_mst WHERE menu_name = 'Spinning Production' LIMIT 1) s
WHERE NOT EXISTS (SELECT 1 FROM menu_mst WHERE menu_name = 'Doff Data Editor');

INSERT INTO role_menu_map (role_id, menu_id, access_type_id, updated_by)
SELECT rmm.role_id, m.menu_id, rmm.access_type_id, rmm.updated_by
FROM role_menu_map rmm
JOIN menu_mst spin ON spin.menu_id = rmm.menu_id AND spin.menu_name = 'Spinning Production'
JOIN menu_mst m ON m.menu_name = 'Doff Data Editor'
WHERE NOT EXISTS (
    SELECT 1 FROM role_menu_map x
    WHERE x.menu_id = m.menu_id AND x.role_id = rmm.role_id AND x.access_type_id = rmm.access_type_id
);

-- =============================================================================
-- ROLLBACK:
-- DELETE FROM role_menu_map WHERE menu_id = (SELECT menu_id FROM menu_mst WHERE menu_name = 'Doff Data Editor');
-- DELETE FROM menu_mst WHERE menu_name = 'Doff Data Editor';
-- =============================================================================
