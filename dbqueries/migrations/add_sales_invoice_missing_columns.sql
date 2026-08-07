-- Add missing columns to sales_invoice table
-- payment_terms: number of days for payment terms
-- sales_order_id: FK reference to sales_order
-- billing_state_code: numeric state code for billing address

ALTER TABLE sales_invoice
  ADD COLUMN payment_terms INT NULL,
  ADD COLUMN sales_order_id INT NULL,
  ADD COLUMN billing_state_code INT NULL;

-- Rollback:
-- ALTER TABLE sales_invoice
--   DROP COLUMN payment_terms,
--   DROP COLUMN sales_order_id,
--   DROP COLUMN billing_state_code;
