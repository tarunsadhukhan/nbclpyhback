-- Migration: drop_yarn_quality_master.sql
-- Date: 2026-06-16
-- Applies to: tenant databases dev3 (QA) [and sls when promoted]
-- Description: FINAL step of the "yarn IS an item" refactor. The separate Yarn Quality
--   master is removed entirely — a yarn is now identified by its item (item_mst.item_id),
--   with editable data on jute_yarn_mst (std_mr_pct added there) and standards/targets in
--   jute_prod_spng_target_map (qid = yarn item id). Run this LAST, only after:
--     1. rename_yarn_quality_id_to_item_id.sql (8 FK columns renamed)
--     2. repoint_vw_spinning_planning_grid.sql (view no longer joins yarn_quality_master)
--     3. clear_legacy_yarn_quality_data.sql (dev3 only)
--   and after the backend no longer references yarn_quality_master (this branch).

DROP TABLE IF EXISTS yarn_quality_master;

-- =============================================================================
-- ROLLBACK:
-- Recreate the table from create_yarn_quality_tables.sql +
-- alter_yarn_quality_master_item_link.sql, then restore the prior view via
-- create_vw_spinning_planning_grid.sql (and reverse rename_yarn_quality_id_to_item_id.sql).
-- Row data is NOT recoverable from this script — restore from a backup taken pre-drop.
-- =============================================================================
