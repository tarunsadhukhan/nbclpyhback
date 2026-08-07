-- Migration: Add invoice_no to proc_inward table
-- Tracks the supplier's invoice number in bill pass module

ALTER TABLE proc_inward ADD COLUMN invoice_no VARCHAR(40) NULL DEFAULT NULL AFTER invoice_amount COMMENT 'Supplier invoice number';

-- Rollback: ALTER TABLE proc_inward DROP COLUMN invoice_no;
