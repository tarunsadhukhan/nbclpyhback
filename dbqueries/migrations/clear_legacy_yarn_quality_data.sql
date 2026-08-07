-- Migration: clear_legacy_yarn_quality_data.sql
-- Date: 2026-06-16
-- Applies to: dev3 ONLY (QA tenant). DO NOT run on production tenants.
--   sls has 0 of these rows (and lacks several of the tables) -> effectively a no-op there.
-- Description: After yarn_quality_id was renamed to item_id, the ~19 dev3 QA rows still
--   hold OLD yarn_quality ids that no longer reference anything (yarn_quality_master is
--   being dropped). Soft-clear those references so nothing points at dropped quality ids;
--   the rows are then re-entered through the new screens (item-based). Also remove the
--   stray qid target rows whose ref_id was an old quality id (the meaning of qid changes
--   to "yarn item id"; old qid rows are stale).
--
-- !!! APPLIER GUARD REQUIRED !!!
--   The applier MUST verify each table (and its item_id column) exists in the target DB
--   before running the matching statement, e.g.:
--     SELECT COUNT(*) FROM information_schema.COLUMNS
--      WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = '<t>' AND COLUMN_NAME = 'item_id';
--   Run the statement only when count = 1. Run this AFTER rename_yarn_quality_id_to_item_id.sql.

-- Null out the legacy yarn-quality references (now named item_id).
UPDATE jute_sqc_spinning_entry      SET item_id = NULL;
UPDATE jute_sqc_spinning_count      SET item_id = NULL;
UPDATE daily_doff_tbl               SET item_id = NULL;
UPDATE daily_doff_frames_winding    SET item_id = NULL;

-- Remove stale qid target rows (old quality ref). id_type='qid' now means yarn item id;
-- the new qid rows are entered fresh via the spinning standards/targets screen.
DELETE FROM jute_prod_spng_target_map WHERE id_type = 'qid';

-- =============================================================================
-- ROLLBACK:
-- Not reversible (the legacy ids were intentionally cleared). Restore from a dev3
-- backup taken before this migration if the old values are needed.
-- =============================================================================
