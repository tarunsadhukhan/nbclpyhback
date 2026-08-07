-- Sync report menus missing in sls.menu_mst from dev3.menu_mst (2026-07-06)
-- 40 rows: 17 jute reports, 8 procurement reports (incl. parent 920), 10 inventory reports,
--          5 jute production reports (incl. parent 945).
-- menu_ids kept identical to dev3 EXCEPT dev3 900/901/902 -> sls 951/952/953
--   (sls 900-902 already hold Finisher Drawing SQC / Beam MR% SQC / Drawhead SQC).
-- parent remap: dev3 768 "Jute Production" = sls 769. Parents 10/5/739/741 match in both.
-- Skipped: dev3 799/804/805/810 (inactive dummy jute reports, active=0)
--          dev3 793 "Pay register Display Settings" (exists in sls id 793 under HRMS Master).
-- NOTE: rows are menu_mst only — role_menu_map entries still needed for sidebar visibility.

INSERT INTO sls.menu_mst (menu_id, menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by, report) VALUES
(814, 'MR List Report', 'jutePurchase/reports/mrList', 1, 10, NULL, 'assessment', NULL, 10, 1),
(815, 'Jute Stock Report', 'jutePurchase/reports/juteStock', 1, 10, NULL, 'assessment', NULL, 20, 1),
(816, 'Batch Cost Report', 'jutePurchase/reports/batchCost', 1, 10, NULL, 'assessment', NULL, 30, 1),
(844, 'Jute Quantity Wise', 'jutePurchase/reports/quantityWise', 1, 10, NULL, 'assessment', NULL, 40, 1),
(845, 'Jute Inventory Snapshot', 'jutePurchase/reports/inventorySnapshot', 1, 10, NULL, 'assessment', NULL, 50, 1),
(851, 'Jute Issue & Receipt Summary', 'jutePurchase/reports/issueReceiptSummary', 1, 10, NULL, 'assessment', NULL, 60, 1),
(852, 'Jute Month Wise', 'jutePurchase/reports/monthWise', 1, 10, NULL, 'assessment', NULL, 70, 1),
(853, 'Jute Day Wise', 'jutePurchase/reports/dayWise', 1, 10, NULL, 'assessment', NULL, 80, 1),
(862, 'Jute MR in Stock', 'jutePurchase/reports/mrInStock', 1, 10, NULL, 'assessment', NULL, 90, 1),
(863, 'Jute MR Wise', 'jutePurchase/reports/mrWise', 1, 10, NULL, 'assessment', NULL, 100, 1),
(864, 'Jute Godown Wise Stock', 'jutePurchase/reports/godownWise', 1, 10, NULL, 'assessment', NULL, 110, 1),
(887, 'Jute with Value', 'jutePurchase/reports/withValue', 1, 10, NULL, 'assessment', NULL, 120, 1),
(951, 'Jute Claim Deviation', 'jutePurchase/reports/claimDeviation', 1, 10, NULL, 'assessment', NULL, 150, 1),
(952, 'Jute MR Wise Sales', 'jutePurchase/reports/mrWiseSales', 1, 10, NULL, 'assessment', NULL, 160, 1),
(953, 'Jute Batch Deviation', 'jutePurchase/reports/batchDeviation', 1, 10, NULL, 'assessment', NULL, 170, 1),
(915, 'Jute Percent Claims', 'jutePurchase/reports/percentClaims', 1, 10, NULL, 'assessment', NULL, 130, 1),
(916, 'Mukham Moisture Analysis', 'jutePurchase/reports/mukhamMoisture', 1, 10, NULL, 'assessment', NULL, 140, 1),
(920, 'Procurement Report(1)', 'procurement/reports_1', 1, 5, 1, NULL, 4, 6, NULL),
(928, 'Indent Item-wise', 'procurement/reports_1/indentItemwise', 1, 920, NULL, 'assessment', NULL, 10, 1),
(929, 'Outstanding Indents (Waiting for PO)', 'procurement/reports_1/indentOutstanding', 1, 920, NULL, 'assessment', NULL, 20, 1),
(930, 'PO Item-wise', 'procurement/reports_1/poItemwise', 1, 920, NULL, 'assessment', NULL, 30, 1),
(931, 'PO Supplier-wise', 'procurement/reports_1/poSupplierwise', 1, 920, NULL, 'assessment', NULL, 40, 1),
(932, 'Outstanding POs', 'procurement/reports_1/poOutstanding', 1, 920, NULL, 'assessment', NULL, 50, 1),
(933, 'Outstanding POs (Supplier-wise)', 'procurement/reports_1/poOutstandingSupplier', 1, 920, NULL, 'assessment', NULL, 60, 1),
(934, 'Store Receipt / GRN Register', 'procurement/reports_1/srRegister', 1, 920, NULL, 'assessment', NULL, 70, 1),
(935, 'Stores Inventory List', 'inventory/reports/storesInventory', 1, 739, NULL, 'assessment', NULL, 10, 1),
(936, 'Issue Item-wise', 'inventory/reports/issueItemwise', 1, 739, NULL, 'assessment', NULL, 20, 1),
(937, 'Item Ledger', 'inventory/reports/itemLedger', 1, 739, NULL, 'assessment', NULL, 30, 1),
(938, 'Item Month-wise', 'inventory/reports/itemMonthwise', 1, 739, NULL, 'assessment', NULL, 40, 1),
(939, 'Stores Min-Max', 'inventory/reports/inventoryMinMax', 1, 739, NULL, 'assessment', NULL, 50, 1),
(940, 'Consumption Report IS-01', 'inventory/reports/consumptionIs01', 1, 739, NULL, 'assessment', NULL, 60, 1),
(941, 'Consumption Report IS-02', 'inventory/reports/consumptionIs02', 1, 739, NULL, 'assessment', NULL, 70, 1),
(942, 'Consumption Report IS-03', 'inventory/reports/consumptionIs03', 1, 739, NULL, 'assessment', NULL, 80, 1),
(943, 'Consumption Report IS-05', 'inventory/reports/consumptionIs05', 1, 739, NULL, 'assessment', NULL, 90, 1),
(944, 'Consumption Report IS-06', 'inventory/reports/consumptionIs06', 1, 739, NULL, 'assessment', NULL, 100, 1),
(945, 'Production Reports', 'juteProduction/report', 1, 769, NULL, 'layers', 2, 185, NULL),
(947, 'Attendance Summary', 'juteProduction/report/attendanceSummary', 1, 945, NULL, 'assessment', NULL, 10, 1),
(948, 'Worker Master', 'juteProduction/report/workerMaster', 1, 945, NULL, 'assessment', NULL, 20, 1),
(949, 'Man-Machine Deployment', 'juteProduction/report/manMachine', 1, 945, NULL, 'assessment', NULL, 30, 1),
(950, 'Attendance Register', 'juteProduction/report/attendanceRegister', 1, 945, NULL, 'assessment', NULL, 40, 1);

-- Rollback:
-- DELETE FROM sls.menu_mst WHERE menu_id IN (814,815,816,844,845,851,852,853,862,863,864,887,951,952,953,915,916,920,928,929,930,931,932,933,934,935,936,937,938,939,940,941,942,943,944,945,947,948,949,950);
