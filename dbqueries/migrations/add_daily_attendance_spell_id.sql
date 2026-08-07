-- Migration: add_daily_attendance_spell_id.sql
-- Phase 1c join-key hygiene (weaving wages groundwork): daily_attendance stores
-- the spell as a NAME/CODE string in the VARCHAR column `spell` (see
-- src/juteProduction/spinning_query.py operator_stamp_query - the documented
-- name join), which forces every consumer into brittle string joins. Add a real
-- spell_id INT NULL and backfill it branch-aware: spell_mst has no branch column,
-- a spell fans out per branch VIA shift_mst (the pattern documented in
-- src/juteProduction/weaving_query.py resolve_weaving_spell_id_query).
--
-- Backfill runs TWO passes, each restricted to (branch, label) pairs that
-- resolve to EXACTLY ONE active spell (HAVING guard) so an ambiguous fanout is
-- never guessed: pass 1 matches spell_mst.spell_name (what the attendance
-- writers store), pass 2 matches spell_mst.spell_code for tenants where the
-- stored string is the code. Rows with no unambiguous match keep NULL.
--
-- IDEMPOTENT: both UPDATEs filter spell_id IS NULL - rerunnable to pick up
-- rows written after this migration (the attendance writers in src/hrms and
-- src/mobileapp still write only the string column - wiring them to stamp
-- spell_id is Phase 3 territory, the weaving_operator_map rebuild).
--
-- EXECUTOR CONSTRAINT: no semicolon in comment prose, header terminated by the
-- lone semicolon below.
--
-- ROLLBACK (as comments):
-- ALTER TABLE daily_attendance DROP COLUMN spell_id
;

ALTER TABLE daily_attendance
    ADD COLUMN spell_id INT NULL DEFAULT NULL
        COMMENT 'resolved spell_mst id for the spell name string - backfilled branch-aware, NULL when ambiguous'
    AFTER spell;

UPDATE daily_attendance da
JOIN (
    SELECT sh.branch_id, sp.spell_name AS label, MIN(sp.spell_id) AS spell_id
    FROM spell_mst sp
    JOIN shift_mst sh ON sh.shift_id = sp.shift_id
    WHERE sp.status = 1 AND sh.status = 1
    GROUP BY sh.branch_id, sp.spell_name
    HAVING COUNT(DISTINCT sp.spell_id) = 1
) r ON r.branch_id = da.branch_id AND r.label = da.spell
SET da.spell_id = r.spell_id
WHERE da.spell_id IS NULL;

UPDATE daily_attendance da
JOIN (
    SELECT sh.branch_id, sp.spell_code AS label, MIN(sp.spell_id) AS spell_id
    FROM spell_mst sp
    JOIN shift_mst sh ON sh.shift_id = sp.shift_id
    WHERE sp.status = 1 AND sh.status = 1
    GROUP BY sh.branch_id, sp.spell_code
    HAVING COUNT(DISTINCT sp.spell_id) = 1
) r ON r.branch_id = da.branch_id AND r.label = da.spell
SET da.spell_id = r.spell_id
WHERE da.spell_id IS NULL
