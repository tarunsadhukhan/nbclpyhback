-- Migration: add std_mr_pct to jute_yarn_mst (single yarn master).
--
-- The yarn item (jute_yarn_mst) becomes the single source of yarn truth. jute_yarn_count
-- already IS the standard count, so std_mr_pct (standard moisture regain %) is the only new
-- yarn property to add here. It moves off yarn_quality_master (which is being removed) and is
-- used by Spinning SQC corrected count: corrected = observed/(100+mr_pct)*(100+std_mr_pct).
-- No branch_id — the value is the same for all branches.

ALTER TABLE jute_yarn_mst
    ADD COLUMN std_mr_pct DECIMAL(5,2) NULL AFTER jute_yarn_count;

-- ============================================================================
-- ROLLBACK
-- ============================================================================
-- ALTER TABLE jute_yarn_mst DROP COLUMN std_mr_pct;
