-- Migration: Add indexes to sales_invoice_dtl for view performance
-- These columns are used in JOIN/GROUP BY by the sales outstanding views
-- Rollback: ALTER TABLE sales_invoice_dtl DROP INDEX idx_sid_delivery_order_dtl_id;
--           ALTER TABLE sales_invoice_dtl DROP INDEX idx_sid_sales_order_dtl_id;

ALTER TABLE sales_invoice_dtl ADD INDEX idx_sid_delivery_order_dtl_id (delivery_order_dtl_id);
ALTER TABLE sales_invoice_dtl ADD INDEX idx_sid_sales_order_dtl_id (sales_order_dtl_id);
