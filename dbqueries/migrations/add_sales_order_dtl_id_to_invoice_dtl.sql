-- Add sales_order_dtl_id to sales_invoice_dtl for line-level traceability to sales orders
ALTER TABLE sales_invoice_dtl ADD COLUMN sales_order_dtl_id INT NULL AFTER delivery_order_dtl_id;

-- Rollback: ALTER TABLE sales_invoice_dtl DROP COLUMN sales_order_dtl_id;
