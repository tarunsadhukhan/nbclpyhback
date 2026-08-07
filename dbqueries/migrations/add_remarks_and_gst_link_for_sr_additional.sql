-- Migration: Add remarks column to proc_inward_additional and GST link for additional charges
-- Purpose: Enable SR additional charges to store remarks and have GST records (mirroring PO pattern)
-- Date: 2026-03-04

-- 1. Add remarks column to proc_inward_additional (matching proc_po_additional.remarks)
ALTER TABLE proc_inward_additional ADD COLUMN remarks VARCHAR(255) NULL;

-- 2. Add proc_inward_additional_id column to proc_gst (matching po_gst.po_additional_id)
--    This allows GST records to be linked to additional charges, not just line items.
ALTER TABLE proc_gst ADD COLUMN proc_inward_additional_id INT NULL;
ALTER TABLE proc_gst ADD INDEX idx_proc_gst_additional (proc_inward_additional_id);

-- Rollback:
-- ALTER TABLE proc_inward_additional DROP COLUMN remarks;
-- ALTER TABLE proc_gst DROP INDEX idx_proc_gst_additional;
-- ALTER TABLE proc_gst DROP COLUMN proc_inward_additional_id;
