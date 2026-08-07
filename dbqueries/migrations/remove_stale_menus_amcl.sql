-- Remove stale portal menus from amcl: 'Spg Mechine Details', 'Yarn Quality Master'.
-- 'Spg Mechine Details' (masters/machinespgdetails) and 'Yarn Quality Master' are gone from dev3.
-- FK role_menu_map_ibfk_2 (menu_mst) blocks the menu_mst delete while role_menu_map rows exist,
-- so the referencing role_menu_map rows must be deleted first.
-- Authorized 2026-06-23: delete the blocking role_menu_map refs too, then the menu_mst rows.
-- Rollback (role_menu_map rows captured before delete; re-insert menu_mst 726/727 first):
--   INSERT INTO role_menu_map (role_menu_mapping_id,role_id,menu_id,access_type_id,updated_by,updated_date_time) VALUES
--     (1784,17,727,1,20,'2026-04-24 10:50:52'),
--     (1783,17,726,1,20,'2026-04-24 10:50:52');

DELETE FROM role_menu_map WHERE menu_id IN (
  SELECT menu_id FROM (SELECT menu_id FROM menu_mst WHERE menu_name IN ('Spg Mechine Details','Yarn Quality Master')) x
);

DELETE FROM menu_mst WHERE menu_name IN ('Spg Mechine Details','Yarn Quality Master');
