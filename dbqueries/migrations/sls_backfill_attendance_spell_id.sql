-- Backfill spell_id on sls attendance tables from spell_mst (matched by branch + spell code).
-- Target DB: sls
-- daily_attendance.spell_id already exists (all NULL); daily_ebmc_attendance needs the column added.
-- Codes with no master entry ('A', 'General', 'GEN 1') remain NULL.

ALTER TABLE daily_ebmc_attendance ADD COLUMN spell_id INT NULL AFTER spell;

UPDATE daily_attendance da
JOIN shift_mst sh ON sh.branch_id = da.branch_id
JOIN spell_mst sp ON sp.shift_id = sh.shift_id AND sp.spell_code = da.spell
SET da.spell_id = sp.spell_id
WHERE da.spell_id IS NULL;

UPDATE daily_ebmc_attendance dea
JOIN shift_mst sh ON sh.branch_id = dea.branch_id
JOIN spell_mst sp ON sp.shift_id = sh.shift_id AND sp.spell_code = dea.spell
SET dea.spell_id = sp.spell_id
WHERE dea.spell_id IS NULL;

-- Rollback:
-- UPDATE daily_attendance SET spell_id = NULL;
-- ALTER TABLE daily_ebmc_attendance DROP COLUMN spell_id;
