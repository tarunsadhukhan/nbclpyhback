-- Add 7 Jute Production / Jute SQC portal menus to sls (synced from dev3).
-- Parents resolved by name (Jute Production / Jute SQC); module_mst_id=2 (Jute Production).
-- menu_type_id left NULL (matches dev3 source rows). menu_id is auto_increment - never specify it.
-- Rollback:
--   DELETE FROM menu_mst WHERE menu_name IN
--     ('Beaming Production','Beaming Quality Master','Beaming SQC','Beaming Standards',
--      'Spinning Standards','Stoppage Hours','Winding Production');

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'Beaming Production', 'juteProduction/beaming', 1, m.menu_id, NULL, 'view_week', 2, 180 FROM menu_mst m WHERE m.menu_name = 'Jute Production';

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'Beaming Quality Master', 'juteProduction/masters/beamingQualityMaster', 1, m.menu_id, NULL, 'fact_check', 2, 201 FROM menu_mst m WHERE m.menu_name = 'Jute Production';

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'Beaming SQC', 'juteSQC/beaming', 1, m.menu_id, NULL, 'speed', 2, 20 FROM menu_mst m WHERE m.menu_name = 'Jute SQC';

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'Beaming Standards', 'juteProduction/masters/beamingTargetMap', 1, m.menu_id, NULL, 'tune', 2, 202 FROM menu_mst m WHERE m.menu_name = 'Jute Production';

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'Spinning Standards', 'juteProduction/masters/spngTargetMap', 1, m.menu_id, NULL, 'tune', 2, 190 FROM menu_mst m WHERE m.menu_name = 'Jute Production';

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'Stoppage Hours', 'juteProduction/stoppageHours', 1, m.menu_id, NULL, 'timer', 2, 200 FROM menu_mst m WHERE m.menu_name = 'Jute Production';

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'Winding Production', 'juteProduction/winding', 1, m.menu_id, NULL, 'cyclone', 2, 165 FROM menu_mst m WHERE m.menu_name = 'Jute Production';
