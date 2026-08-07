-- Migration: Change claim_amount from BIGINT to DECIMAL(12,2) in sales_invoice_jute
-- Reason: claim_amount is computed as sum of line item claim_amount_dtl (Double), needs decimal precision
-- Target DB: dev3

ALTER TABLE sales_invoice_jute MODIFY COLUMN claim_amount DECIMAL(12, 2) NULL;

-- Rollback: ALTER TABLE sales_invoice_jute MODIFY COLUMN claim_amount BIGINT NULL;
