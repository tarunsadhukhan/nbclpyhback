-- Migration: add_weaving_pick_spell_id.sql
-- Phase 1c join-key hygiene (weaving wages groundwork): jute_sqc_weaving_pick
-- has no spell, so a pick reading cannot be traced to the spell it was taken
-- in (wage-side attribution). Add a NULLABLE spell_id - the Act Picks average
-- stays quality/date-grained (vw_weaving_pick_act and the day-slice pick
-- derived tables are untouched), the spell is pure added traceability.
--
-- NO BACKFILL: historical readings carry no spell information anywhere, so
-- legacy rows correctly stay NULL. The capture endpoint
-- (src/juteSQC/weaving_sqc.py weaving_sqc_pick_save) now accepts an optional
-- spell code and stamps spell_id on new readings.
--
-- ORM updated in step: src/juteProduction/weaving_models.py WeavingSqcPick.
--
-- EXECUTOR CONSTRAINT: no semicolon in comment prose, header terminated by the
-- lone semicolon below.
--
-- ROLLBACK (as comments):
-- ALTER TABLE jute_sqc_weaving_pick DROP COLUMN spell_id
;

ALTER TABLE jute_sqc_weaving_pick
    ADD COLUMN spell_id INT NULL DEFAULT NULL
        COMMENT 'optional spell of the reading - wage traceability only, NULL on legacy rows'
    AFTER machine_id
