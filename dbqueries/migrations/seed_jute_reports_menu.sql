-- Migration: Seed Jute Procurement report menu entries (menu_mst report rows + role maps)
-- Applies to: dev3 (tenant DB). Run via run_seed_jute_reports_menu.py (dry-run, then --commit).
--
-- Notes:
--   - Parent = menu_id 10 ("Jute Report", menu_path 'jutePurchase/reports').
--   - report=1 makes a row appear in the reports dropdown (get_report_menu_tree filters report=1, active=1).
--   - menu_path has NO '/dashboardportal' prefix (the hub prepends it on router.push), matching the parent.
--   - menu_name is UNIQUE -> INSERT IGNORE makes this re-runnable.
--   - role_menu_map: roles {1,3,12} (same audience as parent menu 10), access_type_id=4 (edit), updated_by=1.
--     Guarded with NOT EXISTS so re-runs don't duplicate.
--   - Idempotent; safe to re-run as later waves append rows below.

-- =============================================================================
-- 0. Retire the dummy seed report rows that currently surface in the dropdown
--    and route to dead pages (no role maps, placeholder paths).
-- =============================================================================
UPDATE menu_mst SET active = 0 WHERE menu_id IN (799, 804, 805, 810) AND active = 1;

-- =============================================================================
-- Wave 0 — the 3 already-backed reports (MR List, Jute Stock, Batch Cost)
-- =============================================================================
INSERT IGNORE INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by, report)
SELECT 'MR List Report', 'jutePurchase/reports/mrList', 1, 10, NULL, 'assessment', NULL, 10, 1;

INSERT IGNORE INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by, report)
SELECT 'Jute Stock Report', 'jutePurchase/reports/juteStock', 1, 10, NULL, 'assessment', NULL, 20, 1;

INSERT IGNORE INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by, report)
SELECT 'Batch Cost Report', 'jutePurchase/reports/batchCost', 1, 10, NULL, 'assessment', NULL, 30, 1;

-- =============================================================================
-- Wave 1 — Cluster A core (Quantity Wise #2, Inventory Snapshot #14)
-- =============================================================================
INSERT IGNORE INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by, report)
SELECT 'Jute Quantity Wise', 'jutePurchase/reports/quantityWise', 1, 10, NULL, 'assessment', NULL, 40, 1;

INSERT IGNORE INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by, report)
SELECT 'Jute Inventory Snapshot', 'jutePurchase/reports/inventorySnapshot', 1, 10, NULL, 'assessment', NULL, 50, 1;

-- =============================================================================
-- Wave 2 — Cluster A txn + time-series (Issue & Receipt Summary #3, Month #10, Day #11)
-- =============================================================================
INSERT IGNORE INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by, report)
SELECT 'Jute Issue & Receipt Summary', 'jutePurchase/reports/issueReceiptSummary', 1, 10, NULL, 'assessment', NULL, 60, 1;

INSERT IGNORE INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by, report)
SELECT 'Jute Month Wise', 'jutePurchase/reports/monthWise', 1, 10, NULL, 'assessment', NULL, 70, 1;

INSERT IGNORE INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by, report)
SELECT 'Jute Day Wise', 'jutePurchase/reports/dayWise', 1, 10, NULL, 'assessment', NULL, 80, 1;

-- =============================================================================
-- Wave 3 — Cluster B outstanding balance (MR in Stock #4, MR Wise #6, Godown Wise #5)
-- =============================================================================
INSERT IGNORE INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by, report)
SELECT 'Jute MR in Stock', 'jutePurchase/reports/mrInStock', 1, 10, NULL, 'assessment', NULL, 90, 1;

INSERT IGNORE INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by, report)
SELECT 'Jute MR Wise', 'jutePurchase/reports/mrWise', 1, 10, NULL, 'assessment', NULL, 100, 1;

INSERT IGNORE INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by, report)
SELECT 'Jute Godown Wise Stock', 'jutePurchase/reports/godownWise', 1, 10, NULL, 'assessment', NULL, 110, 1;

-- =============================================================================
-- Wave 4 — Cluster A value (Jute with Value #1)
-- =============================================================================
INSERT IGNORE INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by, report)
SELECT 'Jute with Value', 'jutePurchase/reports/withValue', 1, 10, NULL, 'assessment', NULL, 120, 1;

-- =============================================================================
-- Wave 5 — Cluster C claims/moisture (Percent Claims #7, Mukham Moisture #9)
-- =============================================================================
INSERT IGNORE INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by, report)
SELECT 'Jute Percent Claims', 'jutePurchase/reports/percentClaims', 1, 10, NULL, 'assessment', NULL, 130, 1;

INSERT IGNORE INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by, report)
SELECT 'Mukham Moisture Analysis', 'jutePurchase/reports/mukhamMoisture', 1, 10, NULL, 'assessment', NULL, 140, 1;

-- =============================================================================
-- Wave 6 — stub reports (no current-schema data source; placeholder pages)
--   #8 Claim Deviation, #12 MR Wise Sales, #13 Batch Deviation
-- =============================================================================
INSERT IGNORE INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by, report)
SELECT 'Jute Claim Deviation', 'jutePurchase/reports/claimDeviation', 1, 10, NULL, 'assessment', NULL, 150, 1;

INSERT IGNORE INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by, report)
SELECT 'Jute MR Wise Sales', 'jutePurchase/reports/mrWiseSales', 1, 10, NULL, 'assessment', NULL, 160, 1;

INSERT IGNORE INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by, report)
SELECT 'Jute Batch Deviation', 'jutePurchase/reports/batchDeviation', 1, 10, NULL, 'assessment', NULL, 170, 1;

-- Role maps for every jute report row inserted above (roles 1/3/12, access_type 4).
-- Matches new rows by menu_path prefix so each wave's role grants are covered by this one statement.
INSERT INTO role_menu_map (role_id, menu_id, access_type_id, updated_by)
SELECT r.role_id, m.menu_id, 4, 1
  FROM (SELECT 1 AS role_id UNION SELECT 3 UNION SELECT 12) r
  CROSS JOIN (
      SELECT menu_id FROM menu_mst
       WHERE menu_parent_id = 10 AND report = 1 AND active = 1
         AND menu_path LIKE 'jutePurchase/reports/%'
  ) m
 WHERE NOT EXISTS (
      SELECT 1 FROM role_menu_map rm
       WHERE rm.role_id = r.role_id AND rm.menu_id = m.menu_id
 );

-- =============================================================================
-- ROLLBACK (manual):
--   DELETE rm FROM role_menu_map rm JOIN menu_mst m ON rm.menu_id = m.menu_id
--     WHERE m.menu_path LIKE 'jutePurchase/reports/%';
--   DELETE FROM menu_mst WHERE menu_path LIKE 'jutePurchase/reports/%' AND menu_parent_id = 10;
--   UPDATE menu_mst SET active = 1 WHERE menu_id IN (799,804,805,810);
-- =============================================================================
