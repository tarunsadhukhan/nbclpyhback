-- Migration: Add batch_plan_id to jute_sqc_breaker_card_swt — R-08-05/06/07 batch-linked quality
-- Module: juteSQC (R-08-05/06/07 Breaker Card, carding stage)
-- Date: 2026-06-27
-- Applies to: tenant database dev3 (QA). Promote to other tenants later.
--
-- Breaker card quality is now linked to a BATCH (jute_batch_plan — a named mix of raw-jute
-- qualities, branch-scoped), matching the inter-card (R-08-07A) change. A batch has no single
-- quality, so the (item_id, process) std lookup no longer runs: std MR falls back to 16
-- (breaker default) and cv_within_band stays NULL. The legacy item_id column is kept nullable
-- for pre-existing rows; new rows carry batch_plan_id. The per-quality GRAND AVERAGE regroups
-- by batch_plan_id.
--
-- ⚠️ PRE-EXISTING-TENANT PATCH ONLY. dev3 (and any tenant whose jute_sqc_breaker_card_swt was
-- created before 2026-06-27) needs this ALTER. FRESH tenants get batch_plan_id directly from
-- create_jute_sqc_breaker_card_swt.sql and must SKIP this file (re-running errors with
-- "Duplicate column name 'batch_plan_id'").

ALTER TABLE jute_sqc_breaker_card_swt
    ADD COLUMN batch_plan_id BIGINT NULL AFTER item_id,
    ADD INDEX idx_jbcsw_batch_plan_id (batch_plan_id);

-- Rollback:
-- ALTER TABLE jute_sqc_breaker_card_swt DROP INDEX idx_jbcsw_batch_plan_id, DROP COLUMN batch_plan_id;
