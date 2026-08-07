-- Migration: add per-line free-form note to item_bom detail rows.
-- The note is BOM-line scoped (NOT shared across BOMs that reference the same item),
-- so it lives on item_bom and not on item_mst.

-- Forward
ALTER TABLE item_bom
    ADD COLUMN additional_description TEXT NULL AFTER child_item_id;

-- Rollback
-- ALTER TABLE item_bom DROP COLUMN additional_description;
