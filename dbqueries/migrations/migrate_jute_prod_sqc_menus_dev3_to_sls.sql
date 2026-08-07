-- Migration: jute production + jute SQC portal menus  dev3 -> sls  (menu_mst only)
-- 27 menus. Parent resolved by name; module_mst_id=2 (Jute Production).
-- menu_type_id NULL (matches dev3 rows). menu_id is AUTO_INCREMENT - never specified.
-- Idempotent: each INSERT guarded by NOT EXISTS on the unique menu_name.
-- No role_menu_map (per request: menu_mst only) - map roles via dashboardadmin.
-- Rollback:
--   DELETE FROM menu_mst WHERE menu_name IN (
--     'Weaving Production',
--     'Finishing Production',
--     'Weaving Quality Master',
--     'Finishing Quality Master',
--     'Weaving Standards',
--     'Finishing Spec Sheet',
--     'Morrah Weight SQC',
--     'Weaving SQC',
--     'Finishing SQC',
--     'Spreader SQC',
--     'Breaker Card SQC',
--     'Inter Card SQC',
--     'Finisher Drawing SQC',
--     'Beam MR% SQC',
--     'Drawhead SQC',
--     'Fabric Construction SQC',
--     'Yarn TPI SQC',
--     'Cutting Length SQC',
--     'Yarn QR-CV Special SQC',
--     'Width & Picks SQC',
--     'Stitch SQC',
--     'Bag Weight SQC',
--     'Bag Checking SQC',
--     'Packing MR% SQC',
--     'Fabric Fault SQC',
--     'Emulsion SQC',
--     'Humidity Recording SQC');

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'Weaving Production', 'juteProduction/weaving', 1, p.menu_id, NULL, 'grid_on', 2, 185
FROM menu_mst p WHERE p.menu_name='Jute Production'
  AND NOT EXISTS (SELECT 1 FROM menu_mst e WHERE e.menu_name='Weaving Production');

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'Finishing Production', 'juteProduction/finishing', 1, p.menu_id, NULL, 'layers', 2, 185
FROM menu_mst p WHERE p.menu_name='Jute Production'
  AND NOT EXISTS (SELECT 1 FROM menu_mst e WHERE e.menu_name='Finishing Production');

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'Weaving Quality Master', 'juteProduction/masters/weavingQualityMaster', 1, p.menu_id, NULL, 'fact_check', 2, 203
FROM menu_mst p WHERE p.menu_name='Jute Production'
  AND NOT EXISTS (SELECT 1 FROM menu_mst e WHERE e.menu_name='Weaving Quality Master');

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'Finishing Quality Master', 'juteProduction/masters/finishingQualityMaster', 1, p.menu_id, NULL, 'fact_check', 2, 203
FROM menu_mst p WHERE p.menu_name='Jute Production'
  AND NOT EXISTS (SELECT 1 FROM menu_mst e WHERE e.menu_name='Finishing Quality Master');

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'Weaving Standards', 'juteProduction/masters/weavingTargetMap', 1, p.menu_id, NULL, 'tune', 2, 204
FROM menu_mst p WHERE p.menu_name='Jute Production'
  AND NOT EXISTS (SELECT 1 FROM menu_mst e WHERE e.menu_name='Weaving Standards');

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'Finishing Spec Sheet', 'juteProduction/masters/finishingSpecSheet', 1, p.menu_id, NULL, 'tune', 2, 204
FROM menu_mst p WHERE p.menu_name='Jute Production'
  AND NOT EXISTS (SELECT 1 FROM menu_mst e WHERE e.menu_name='Finishing Spec Sheet');

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'Morrah Weight SQC', 'juteSQC/r-08-01', 1, p.menu_id, NULL, 'scale', 2, 5
FROM menu_mst p WHERE p.menu_name='Jute SQC'
  AND NOT EXISTS (SELECT 1 FROM menu_mst e WHERE e.menu_name='Morrah Weight SQC');

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'Weaving SQC', 'juteSQC/weaving', 1, p.menu_id, NULL, 'speed', 2, 30
FROM menu_mst p WHERE p.menu_name='Jute SQC'
  AND NOT EXISTS (SELECT 1 FROM menu_mst e WHERE e.menu_name='Weaving SQC');

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'Finishing SQC', 'juteSQC/finishing', 1, p.menu_id, NULL, 'layers', 2, 30
FROM menu_mst p WHERE p.menu_name='Jute SQC'
  AND NOT EXISTS (SELECT 1 FROM menu_mst e WHERE e.menu_name='Finishing SQC');

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'Spreader SQC', 'juteSQC/spreader', 1, p.menu_id, NULL, 'settings', 2, 40
FROM menu_mst p WHERE p.menu_name='Jute SQC'
  AND NOT EXISTS (SELECT 1 FROM menu_mst e WHERE e.menu_name='Spreader SQC');

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'Breaker Card SQC', 'juteSQC/breakerCard', 1, p.menu_id, NULL, 'grid_view', 2, 50
FROM menu_mst p WHERE p.menu_name='Jute SQC'
  AND NOT EXISTS (SELECT 1 FROM menu_mst e WHERE e.menu_name='Breaker Card SQC');

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'Inter Card SQC', 'juteSQC/interCard', 1, p.menu_id, NULL, 'view_week', 2, 60
FROM menu_mst p WHERE p.menu_name='Jute SQC'
  AND NOT EXISTS (SELECT 1 FROM menu_mst e WHERE e.menu_name='Inter Card SQC');

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'Finisher Drawing SQC', 'juteSQC/finDraw', 1, p.menu_id, NULL, 'view_week', 2, 70
FROM menu_mst p WHERE p.menu_name='Jute SQC'
  AND NOT EXISTS (SELECT 1 FROM menu_mst e WHERE e.menu_name='Finisher Drawing SQC');

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'Beam MR% SQC', 'juteSQC/beamMr', 1, p.menu_id, NULL, 'water_drop', 2, 70
FROM menu_mst p WHERE p.menu_name='Jute SQC'
  AND NOT EXISTS (SELECT 1 FROM menu_mst e WHERE e.menu_name='Beam MR% SQC');

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'Drawhead SQC', 'juteSQC/drawhead', 1, p.menu_id, NULL, 'view_week', 2, 80
FROM menu_mst p WHERE p.menu_name='Jute SQC'
  AND NOT EXISTS (SELECT 1 FROM menu_mst e WHERE e.menu_name='Drawhead SQC');

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'Fabric Construction SQC', 'juteSQC/fabricConstruction', 1, p.menu_id, NULL, 'grid_on', 2, 80
FROM menu_mst p WHERE p.menu_name='Jute SQC'
  AND NOT EXISTS (SELECT 1 FROM menu_mst e WHERE e.menu_name='Fabric Construction SQC');

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'Yarn TPI SQC', 'juteSQC/yarnTpi', 1, p.menu_id, NULL, 'settings', 2, 90
FROM menu_mst p WHERE p.menu_name='Jute SQC'
  AND NOT EXISTS (SELECT 1 FROM menu_mst e WHERE e.menu_name='Yarn TPI SQC');

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'Cutting Length SQC', 'juteSQC/cuttingLength', 1, p.menu_id, NULL, 'straighten', 2, 90
FROM menu_mst p WHERE p.menu_name='Jute SQC'
  AND NOT EXISTS (SELECT 1 FROM menu_mst e WHERE e.menu_name='Cutting Length SQC');

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'Yarn QR-CV Special SQC', 'juteSQC/qrCv15a', 1, p.menu_id, NULL, 'grid_view', 2, 100
FROM menu_mst p WHERE p.menu_name='Jute SQC'
  AND NOT EXISTS (SELECT 1 FROM menu_mst e WHERE e.menu_name='Yarn QR-CV Special SQC');

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'Width & Picks SQC', 'juteSQC/widthPicks', 1, p.menu_id, NULL, 'straighten', 2, 100
FROM menu_mst p WHERE p.menu_name='Jute SQC'
  AND NOT EXISTS (SELECT 1 FROM menu_mst e WHERE e.menu_name='Width & Picks SQC');

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'Stitch SQC', 'juteSQC/stitch', 1, p.menu_id, NULL, 'content_cut', 2, 110
FROM menu_mst p WHERE p.menu_name='Jute SQC'
  AND NOT EXISTS (SELECT 1 FROM menu_mst e WHERE e.menu_name='Stitch SQC');

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'Bag Weight SQC', 'juteSQC/bagWeight', 1, p.menu_id, NULL, 'shopping_bag', 2, 120
FROM menu_mst p WHERE p.menu_name='Jute SQC'
  AND NOT EXISTS (SELECT 1 FROM menu_mst e WHERE e.menu_name='Bag Weight SQC');

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'Bag Checking SQC', 'juteSQC/bagCheck', 1, p.menu_id, NULL, 'fact_check', 2, 130
FROM menu_mst p WHERE p.menu_name='Jute SQC'
  AND NOT EXISTS (SELECT 1 FROM menu_mst e WHERE e.menu_name='Bag Checking SQC');

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'Packing MR% SQC', 'juteSQC/packingMr', 1, p.menu_id, NULL, 'inventory_2', 2, 140
FROM menu_mst p WHERE p.menu_name='Jute SQC'
  AND NOT EXISTS (SELECT 1 FROM menu_mst e WHERE e.menu_name='Packing MR% SQC');

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'Fabric Fault SQC', 'juteSQC/fabricFault', 1, p.menu_id, NULL, 'report_problem', 2, 150
FROM menu_mst p WHERE p.menu_name='Jute SQC'
  AND NOT EXISTS (SELECT 1 FROM menu_mst e WHERE e.menu_name='Fabric Fault SQC');

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'Emulsion SQC', 'juteSQC/emulsion', 1, p.menu_id, NULL, 'opacity', 2, 160
FROM menu_mst p WHERE p.menu_name='Jute SQC'
  AND NOT EXISTS (SELECT 1 FROM menu_mst e WHERE e.menu_name='Emulsion SQC');

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT 'Humidity Recording SQC', 'juteSQC/humidity', 1, p.menu_id, NULL, 'thermostat', 2, 170
FROM menu_mst p WHERE p.menu_name='Jute SQC'
  AND NOT EXISTS (SELECT 1 FROM menu_mst e WHERE e.menu_name='Humidity Recording SQC');
