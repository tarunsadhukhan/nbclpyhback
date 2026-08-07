-- Migration: Add jute-specific columns to sale_invoice_jute
-- Date: 2026-02-26
-- Purpose: Support standalone jute sales invoice workflow with despatch info, mukam, and claim details

-- Add new columns
ALTER TABLE sale_invoice_jute
    ADD COLUMN despatch_doc_no VARCHAR(100) NULL AFTER unit_conversion,
    ADD COLUMN despatched_through VARCHAR(50) NULL AFTER despatch_doc_no,
    ADD COLUMN mukam_id INT NULL AFTER despatched_through,
    ADD COLUMN claim_note VARCHAR(500) NULL AFTER mukam_id;

-- Change claim_amount from BIGINT to DECIMAL for proper monetary storage
ALTER TABLE sale_invoice_jute
    MODIFY COLUMN claim_amount DECIMAL(12,2) NULL;

-- Rollback:
-- ALTER TABLE sale_invoice_jute
--     DROP COLUMN despatch_doc_no,
--     DROP COLUMN despatched_through,
--     DROP COLUMN mukam_id,
--     DROP COLUMN claim_note;
-- ALTER TABLE sale_invoice_jute MODIFY COLUMN claim_amount BIGINT NULL;
