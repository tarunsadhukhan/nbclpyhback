-- Migration: remap branch-2 spell 5 ('C') stamped on dev3 branch-12 weaving quality-map rows
-- Date: 2026-07-27. Target: dev3 ONLY (sls verified clean; all other spell-carrying tables clean).
-- Cause: same unscoped MIN(spell_id) resolver class as the sls spinning repair —
--        weaving quality-map saves on branch 12 stored branch-2's 'C' spell (id 5).
-- Target verified unique: spell 8 = code 'C', branch 12 (shift join), status=1.
-- Affected rows: 114 active, tran_date 2026-06-22..2026-06-27. User-approved 2026-07-27.

UPDATE jute_prod_weaving_quality_map SET spell_id = 8
WHERE spell_id = 5 AND branch_id = 12 AND active = 1;

-- Rollback:
-- UPDATE jute_prod_weaving_quality_map SET spell_id = 5
-- WHERE spell_id = 8 AND branch_id = 12 AND active = 1
--   AND tran_date BETWEEN '2026-06-22' AND '2026-06-27';
-- (date guard pins rollback to the pre-fix rows; verify with SELECT first)
