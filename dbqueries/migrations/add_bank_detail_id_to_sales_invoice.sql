-- Migration: Add bank_detail_id to sales_invoice
-- Date: 2026-03-31
-- Purpose: Link sales invoices to bank details for payment information on printed invoices

ALTER TABLE sales_invoice ADD COLUMN bank_detail_id INT NULL DEFAULT NULL;
ALTER TABLE sales_invoice ADD CONSTRAINT fk_sales_invoice_bank_detail
    FOREIGN KEY (bank_detail_id) REFERENCES bank_details_mst(bank_detail_id);

-- Rollback:
-- ALTER TABLE sales_invoice DROP FOREIGN KEY fk_sales_invoice_bank_detail;
-- ALTER TABLE sales_invoice DROP COLUMN bank_detail_id;
