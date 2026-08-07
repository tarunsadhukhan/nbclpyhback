-- Add buyer order reference fields to sales_order
-- These fields already exist in sales_invoice and are being added to sales_order for consistency
-- Rollback: ALTER TABLE sales_order DROP COLUMN buyer_order_no, DROP COLUMN buyer_order_date;

ALTER TABLE sales_order ADD COLUMN buyer_order_no VARCHAR(255) NULL;
ALTER TABLE sales_order ADD COLUMN buyer_order_date DATE NULL;
