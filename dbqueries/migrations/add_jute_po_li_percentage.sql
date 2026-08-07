-- Add percentage column to jute_po_li for percentage-based PO line entry.
-- Rollback: ALTER TABLE jute_po_li DROP COLUMN percentage;
ALTER TABLE jute_po_li ADD COLUMN percentage DECIMAL(5,2) NULL AFTER quantity;
