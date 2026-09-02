-- Add a unit column to winding production entries: the sheet's kg figures are
-- always in KG today, but the mill wants the unit stored explicitly per row.
-- Defaults every existing and new row to 'KG'.
-- Target DB: nbcl
-- Rollback: ALTER TABLE winding_production DROP COLUMN unit;

ALTER TABLE winding_production ADD COLUMN unit VARCHAR(10) NOT NULL DEFAULT 'KG' AFTER prod_kg;
