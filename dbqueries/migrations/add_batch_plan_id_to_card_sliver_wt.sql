-- Migration: Add batch_plan_id to jute_sqc_card_sliver_wt — R-08-07A batch-linked quality
-- Module: juteSQC (R-08-07A Inter Card & Tow Breaker Sliver Weight)
-- Date: 2026-06-27
-- Applies to: tenant database dev3 (QA). Promote to other tenants later.
--
-- ⚠️ PRE-EXISTING-TENANT PATCH ONLY. dev3 (and any tenant whose jute_sqc_card_sliver_wt was
-- created before 2026-06-27) needs this ALTER. FRESH tenants get batch_plan_id directly from
-- create_jute_sqc_card_sliver_wt.sql and must SKIP this file (re-running it errors with
-- "Duplicate column name 'batch_plan_id'").
--
-- Carding/drawing SQC quality is linked to a BATCH (jute_batch_plan — a named mix of raw-jute
-- qualities, branch-scoped) instead of a single line quality (item_mst, item_type_id=5). A
-- batch has no single quality, so std MR%/CV band cannot be keyed by item_id at this stage:
-- std MR falls back to 20 and cv_within_band stays NULL (unchanged runtime behaviour — the
-- carding jute_draw_quality_std satellite was never seeded). The legacy item_id column is kept
-- nullable for pre-existing rows; new rows carry batch_plan_id instead. The per-quality GRAND
-- AVERAGE block regroups by batch_plan_id.

ALTER TABLE jute_sqc_card_sliver_wt
    ADD COLUMN batch_plan_id BIGINT NULL AFTER item_id,
    ADD INDEX idx_jcsw_batch_plan_id (batch_plan_id);

-- Rollback:
-- ALTER TABLE jute_sqc_card_sliver_wt DROP INDEX idx_jcsw_batch_plan_id, DROP COLUMN batch_plan_id;
