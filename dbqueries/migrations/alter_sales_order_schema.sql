-- Migration: Alter sales_order and sales_order_dtl schema
-- Date: 2026-02-25
-- Changes:
--   sales_order: sales_no VARCHAR(255) -> BIGINT, drop party_branch_id
--   sales_order_dtl: rename uom_id -> qty_uom_id, add rate_uom_id

-- =============================================
-- sales_order: change sales_no to BIGINT
-- =============================================
ALTER TABLE sales_order MODIFY COLUMN sales_no BIGINT NULL;

-- =============================================
-- sales_order: drop party_branch_id
-- =============================================
ALTER TABLE sales_order DROP COLUMN party_branch_id;

-- =============================================
-- sales_order_dtl: rename uom_id -> qty_uom_id
-- =============================================
ALTER TABLE sales_order_dtl CHANGE COLUMN uom_id qty_uom_id INT NULL;

-- =============================================
-- sales_order_dtl: add rate_uom_id after rate
-- =============================================
ALTER TABLE sales_order_dtl ADD COLUMN rate_uom_id INT NULL AFTER rate;

-- Rollback:
-- ALTER TABLE sales_order MODIFY COLUMN sales_no VARCHAR(255) NULL;
-- ALTER TABLE sales_order ADD COLUMN party_branch_id INT NULL AFTER party_id;
-- ALTER TABLE sales_order_dtl CHANGE COLUMN qty_uom_id uom_id INT NULL;
-- ALTER TABLE sales_order_dtl DROP COLUMN rate_uom_id;
