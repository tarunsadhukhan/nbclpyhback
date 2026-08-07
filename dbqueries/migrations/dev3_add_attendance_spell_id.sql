-- Add spell_id to dev3 attendance tables so saves store the spell_mst id
-- alongside the legacy spell string (mirrors sls_backfill_attendance_spell_id.sql).
-- Target DB: dev3
-- No backfill needed: both tables are empty in dev3 as of 2026-07-07.

ALTER TABLE daily_attendance ADD COLUMN spell_id INT NULL AFTER spell;
ALTER TABLE daily_ebmc_attendance ADD COLUMN spell_id INT NULL AFTER spell;

-- Rollback:
-- ALTER TABLE daily_attendance DROP COLUMN spell_id;
-- ALTER TABLE daily_ebmc_attendance DROP COLUMN spell_id;
