-- Migration: remap branch-4 spell ids stamped on sls branch-29 spinning rows
-- Date: 2026-07-27. Target: sls ONLY (dev3 verified clean; frozen/lock tables clean).
-- Cause: old _resolve_spell_id used MIN(spell_id) by code with no branch scoping,
--        so sls posts stored branch-4's A1/A2 (spell 91/92) on branch-29 rows.
--        Fixed go-forward by the branch-scoped spell_id contract; this repairs history.
-- Mapping (verified 1:1 via spell_mst+shift_mst): 91 (A1, br-4) -> 97 (A1, br-29);
--        92 (A2, br-4) -> 98 (A2, br-29). User-approved 2026-07-27.

UPDATE daily_doff_tbl SET spell = 97
WHERE spell = 91 AND branch_id = 29;

UPDATE daily_doff_tbl SET spell = 98
WHERE spell = 92 AND branch_id = 29;

UPDATE daily_doff_frames_winding SET spell_id = 97
WHERE spell_id = 91 AND branch_id = 29;

UPDATE spg_quality_mapper SET effective_from_spell_id = 97
WHERE effective_from_spell_id = 91 AND branch_id = 29;

UPDATE spg_quality_helper SET effective_from_spell_id = 97
WHERE effective_from_spell_id = 91 AND branch_id = 29;

-- (daily_doff_frames_winding.spell NAME column needs no change: 91 and 97 are both 'A1'.)
-- Rollback:
-- UPDATE daily_doff_tbl SET spell = 91 WHERE spell = 97 AND branch_id = 29 AND doff_date = '2026-01-02';
-- UPDATE daily_doff_tbl SET spell = 92 WHERE spell = 98 AND branch_id = 29 AND doff_date = '2026-01-02';
-- UPDATE daily_doff_frames_winding SET spell_id = 91 WHERE spell_id = 97 AND branch_id = 29 AND tran_date = '2026-01-02';
-- UPDATE spg_quality_mapper SET effective_from_spell_id = 91 WHERE effective_from_spell_id = 97 AND branch_id = 29;
-- UPDATE spg_quality_helper SET effective_from_spell_id = 91 WHERE effective_from_spell_id = 97 AND branch_id = 29;
-- NOTE rollback date guards: post-fix rows legitimately carry 97/98 — the guards pin
-- rollback to the pilot-era rows (all pre-fix data was doff_date/tran_date 2026-01-02);
-- verify with a SELECT before running rollback.
