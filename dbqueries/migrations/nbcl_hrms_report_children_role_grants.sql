-- HRMS Reports rendered as a leaf in the portal sidebar (nbcl): the hub row
-- (menu_path 'hrms/hrmsreports') and all 16 child report rows exist, but the
-- roles holding the hub had no role_menu_map grant on the children, so
-- get_portal_user_menus returned the hub with no descendants.
--
-- Fix: mirror every hub grant onto every active child, same access_type_id.
-- Idempotent (NOT EXISTS on role_id + menu_id); target DB: nbcl.

INSERT INTO role_menu_map (role_id, menu_id, access_type_id, updated_by, updated_date_time)
SELECT hub.role_id, c.menu_id, hub.access_type_id, 1, NOW()
FROM role_menu_map hub
JOIN menu_mst h ON h.menu_id = hub.menu_id AND h.menu_path = 'hrms/hrmsreports'
JOIN menu_mst c ON c.menu_parent_id = h.menu_id AND c.active = 1
WHERE NOT EXISTS (
    SELECT 1 FROM role_menu_map x
    WHERE x.role_id = hub.role_id AND x.menu_id = c.menu_id
);

-- Rollback: DELETE FROM role_menu_map WHERE updated_date_time = '<run timestamp>'
--   AND menu_id IN (SELECT menu_id FROM menu_mst WHERE menu_parent_id =
--       (SELECT menu_id FROM menu_mst WHERE menu_path = 'hrms/hrmsreports'));
