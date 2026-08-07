-- Migration: tie yarn_quality_master to a yarn ITEM (item_type_id=4) and add Std MR%.
--
-- Why: a yarn is an item in item_mst (its group has item_type_id=4). Yarn qualities
-- should be driven by the actual yarn item, not by the yarn-type group. Std MR%
-- (standard moisture regain) is a per-quality standard used by Spinning SQC to compute
-- corrected count: corrected = observed/(100+MR%)*(100+StdMR%).
--
-- item_grp_id is KEPT (nullable, deprecated) so legacy rows keep resolving.

ALTER TABLE yarn_quality_master
    ADD COLUMN item_id INT NULL AFTER quality_code,
    ADD COLUMN std_mr_pct DECIMAL(5,2) NULL AFTER target_eff;

-- Optional index for the new item link (lookups by yarn item).
ALTER TABLE yarn_quality_master
    ADD KEY idx_yqm_item (item_id);

-- ============================================================================
-- ROLLBACK
-- ============================================================================
-- ALTER TABLE yarn_quality_master DROP KEY idx_yqm_item;
-- ALTER TABLE yarn_quality_master DROP COLUMN std_mr_pct;
-- ALTER TABLE yarn_quality_master DROP COLUMN item_id;
