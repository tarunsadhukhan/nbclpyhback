-- Remove stale portal menus from sls: 'Yarn Quality Master', 'Yarn Quality Parameters'.
-- These were dropped in dev3 during the 2026-06-16 yarn consolidation.
-- FK role_menu_map_ibfk_2 (menu_mst) blocks the menu_mst delete while role_menu_map rows exist,
-- so the referencing role_menu_map rows must be deleted first.
-- Authorized 2026-06-23: delete the blocking role_menu_map refs too, then the menu_mst rows.
-- Rollback (role_menu_map rows captured before delete; re-insert menu_mst 726/783 first):
--   INSERT INTO role_menu_map (role_menu_mapping_id,role_id,menu_id,access_type_id,updated_by,updated_date_time) VALUES
--     (2068,14,726,4,14,'2026-04-24 14:46:59'),
--     (2499,17,726,1,4,'2026-06-04 13:19:15'),
--     (3188,13,726,4,4,'2026-06-17 15:12:05'),
--     (3240,13,783,4,4,'2026-06-17 15:12:07');

DELETE FROM role_menu_map WHERE menu_id IN (
  SELECT menu_id FROM (SELECT menu_id FROM menu_mst WHERE menu_name IN ('Yarn Quality Master','Yarn Quality Parameters')) x
);

DELETE FROM menu_mst WHERE menu_name IN ('Yarn Quality Master','Yarn Quality Parameters');
