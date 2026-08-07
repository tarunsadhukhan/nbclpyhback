-- 2026-07-12: prevent duplicate ACTIVE jute_prod_weaving_daily rows per unit+loom.
-- Race fix: no unique key existed and the writers do check-then-insert, so two
-- concurrent saves could both insert for the same (co_id, tran_date, spell_id,
-- machine_id). Switch to NULL-soft-delete (active 1 = live, NULL = deleted --
-- MySQL unique keys never collide on NULL) and add the composite unique key.
-- Readers filter active = 1 and are unaffected. Apply BEFORE deploying the code
-- that writes active = NULL on delete.
--
-- Statements, in order:
--   (a) active becomes NULLable (was TINYINT NOT NULL DEFAULT 1)
--   (b) convert legacy soft-deleted rows 0 -> NULL
--   (c) pre-dedup guard: among active=1 duplicates per (co_id, tran_date,
--       spell_id, machine_id) keep only the highest weaving_daily_id and
--       soft-delete the rest. The HAVING COUNT > 1 derived table is empty
--       when there are no duplicates, making the statement a no-op then.
--   (d) the unique key: at most ONE active=1 row per (co_id, tran_date,
--       spell_id, machine_id) -- NULL (deleted) rows may repeat freely.
--
-- NOTE for the runner: statements split on semicolons -- this header ends with
-- a bare semicolon so every chunk below starts with SQL, and comments stay
-- semicolon-free.
;

ALTER TABLE jute_prod_weaving_daily
    MODIFY COLUMN active TINYINT NULL DEFAULT 1;

UPDATE jute_prod_weaving_daily
SET active = NULL
WHERE active = 0;

UPDATE jute_prod_weaving_daily d
JOIN (
    SELECT co_id, tran_date, spell_id, machine_id,
           MAX(weaving_daily_id) AS keep_id
    FROM jute_prod_weaving_daily
    WHERE active = 1
    GROUP BY co_id, tran_date, spell_id, machine_id
    HAVING COUNT(*) > 1
) k
  ON d.co_id = k.co_id
 AND d.tran_date = k.tran_date
 AND d.spell_id = k.spell_id
 AND d.machine_id = k.machine_id
SET d.active = NULL
WHERE d.active = 1
  AND d.weaving_daily_id < k.keep_id;

ALTER TABLE jute_prod_weaving_daily
    ADD UNIQUE KEY uq_weaving_daily_unit_machine
        (co_id, tran_date, spell_id, machine_id, active);

-- =============================================================================
-- ROLLBACK (manual, run in this order)
-- =============================================================================
-- ALTER TABLE jute_prod_weaving_daily
--     DROP KEY uq_weaving_daily_unit_machine
-- UPDATE jute_prod_weaving_daily SET active = 0 WHERE active IS NULL
-- ALTER TABLE jute_prod_weaving_daily
--     MODIFY COLUMN active TINYINT NOT NULL DEFAULT 1
-- (rows soft-deleted by the dedup guard in step c are NOT distinguishable
--  afterwards -- they roll back to active = 0 like ordinary deletes)
