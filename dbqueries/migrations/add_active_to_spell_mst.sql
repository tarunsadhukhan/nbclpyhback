-- Migration: add `active` flag to spell_mst (Spell Master "Active" option)
-- Date: 2026-08-26
-- Already present in nbcl; needed on any tenant whose spell_mst lacks it (e.g. sjm),
-- because src/masters/spell.py now selects/inserts sp.active.

ALTER TABLE spell_mst ADD COLUMN `active` INT DEFAULT 1;

UPDATE spell_mst SET active = 1 WHERE active IS NULL;

-- Rollback:
-- ALTER TABLE spell_mst DROP COLUMN `active`;
