-- divisible_hrs is derived: always wk_hrs * 3 (sheet: 104->312, 96->288).
-- Convert it to a stored generated column so the DB owns the rule, like amount.
-- MySQL cannot MODIFY a plain column into a generated one, so DROP + ADD
-- (table is freshly created, no production data).
-- Target DB: nbcl
-- Rollback:
--   ALTER TABLE beaming_production DROP COLUMN divisible_hrs;
--   ALTER TABLE beaming_production ADD COLUMN divisible_hrs DOUBLE NULL AFTER lost_hrs;

ALTER TABLE beaming_production DROP COLUMN divisible_hrs;
ALTER TABLE beaming_production
    ADD COLUMN divisible_hrs DOUBLE GENERATED ALWAYS AS (wk_hrs * 3) STORED AFTER lost_hrs;
