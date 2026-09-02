-- Add a unit column to the winding incentive master: qualities are rated in
-- KG today, but the mill wants the unit stored explicitly per scheme row so
-- production entries can inherit it. Defaults every existing and new row to 'KG'.
-- Target DB: nbcl
-- Rollback: ALTER TABLE winding_incentive_mst DROP COLUMN unit;

ALTER TABLE winding_incentive_mst ADD COLUMN unit VARCHAR(10) NOT NULL DEFAULT 'KG' AFTER eligibility_hrs;
