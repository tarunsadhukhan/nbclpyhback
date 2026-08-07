-- Migration: Add missing columns to sales_invoice_dtl
-- Date: 2026-03-15
-- Description: Add discount_type, discounted_rate, discount_amount, remarks, delivery_order_dtl_id
--              These columns are referenced by ORM models, queries, router, and UI but were missing from the DB.

ALTER TABLE sales_invoice_dtl ADD COLUMN discount_type int NULL;
ALTER TABLE sales_invoice_dtl ADD COLUMN discounted_rate double NULL;
ALTER TABLE sales_invoice_dtl ADD COLUMN discount_amount double NULL;
ALTER TABLE sales_invoice_dtl ADD COLUMN remarks varchar(255) NULL;
ALTER TABLE sales_invoice_dtl ADD COLUMN delivery_order_dtl_id int NULL;

-- Rollback:
-- ALTER TABLE sales_invoice_dtl DROP COLUMN discount_type;
-- ALTER TABLE sales_invoice_dtl DROP COLUMN discounted_rate;
-- ALTER TABLE sales_invoice_dtl DROP COLUMN discount_amount;
-- ALTER TABLE sales_invoice_dtl DROP COLUMN remarks;
-- ALTER TABLE sales_invoice_dtl DROP COLUMN delivery_order_dtl_id;
