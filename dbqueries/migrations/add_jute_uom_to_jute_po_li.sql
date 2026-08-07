-- Migration: Add jute_uom column to jute_po_li table
-- Purpose: Move unit (LOOSE/BALE) from PO header to line items for mixed-unit support
-- Date: 2026-03-07

ALTER TABLE jute_po_li ADD COLUMN jute_uom VARCHAR(255) DEFAULT NULL AFTER allowable_moisture;

-- Backfill existing line items from their PO header
UPDATE jute_po_li jpli
INNER JOIN jute_po jp ON jp.jute_po_id = jpli.jute_po_id
SET jpli.jute_uom = jp.jute_uom
WHERE jpli.jute_uom IS NULL;

-- Rollback: ALTER TABLE jute_po_li DROP COLUMN jute_uom;
