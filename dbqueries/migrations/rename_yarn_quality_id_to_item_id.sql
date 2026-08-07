-- Migration: rename_yarn_quality_id_to_item_id.sql
-- Date: 2026-06-16
-- Applies to: tenant databases dev3 (QA) [and sls when promoted]
-- Description: Collapse "Yarn Quality" into the yarn ITEM. The FK column
--   yarn_quality_id (it now holds item_mst.item_id) is renamed to item_id across the
--   8 transaction tables that carry it.
--
-- !!! APPLIER GUARD REQUIRED !!!
--   Some tenants lack some of these tables/columns (sls has NO jute_sqc_* and NO
--   winding tables). Before each ALTER, the applier MUST check information_schema and
--   skip the statement when the table or the yarn_quality_id column is absent, e.g.:
--     SELECT COUNT(*) FROM information_schema.COLUMNS
--      WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = '<t>' AND COLUMN_NAME = 'yarn_quality_id';
--   Run the matching ALTER only when that count = 1. (CHANGE on a missing
--   table/column errors out and aborts the batch otherwise.)
--
-- NOTE: keep the column NULLable (INT NULL) exactly as the existing schema; the
--   value is the yarn item id (item_mst.item_id).

-- juteSQC tables (absent on sls)
ALTER TABLE jute_sqc_spinning_entry  CHANGE yarn_quality_id item_id INT NULL;
ALTER TABLE jute_sqc_spinning_count  CHANGE yarn_quality_id item_id INT NULL;

-- spinning planning / doff tables
ALTER TABLE daily_doff_tbl            CHANGE yarn_quality_id item_id INT NULL;
ALTER TABLE daily_doff_frames_winding CHANGE yarn_quality_id item_id INT NULL;
ALTER TABLE jute_prod_spinning_daily  CHANGE yarn_quality_id item_id INT NULL;
ALTER TABLE spinning_quality_xref     CHANGE yarn_quality_id item_id INT NULL;

-- winding tables (absent on sls)
ALTER TABLE jute_prod_winding_doff       CHANGE yarn_quality_id item_id INT NULL;
ALTER TABLE jute_prod_winding_daily_qlty CHANGE yarn_quality_id item_id INT NULL;

-- =============================================================================
-- ROLLBACK (same existence guards apply per table):
-- ALTER TABLE jute_sqc_spinning_entry      CHANGE item_id yarn_quality_id INT NULL;
-- ALTER TABLE jute_sqc_spinning_count      CHANGE item_id yarn_quality_id INT NULL;
-- ALTER TABLE daily_doff_tbl               CHANGE item_id yarn_quality_id INT NULL;
-- ALTER TABLE daily_doff_frames_winding    CHANGE item_id yarn_quality_id INT NULL;
-- ALTER TABLE jute_prod_spinning_daily     CHANGE item_id yarn_quality_id INT NULL;
-- ALTER TABLE spinning_quality_xref        CHANGE item_id yarn_quality_id INT NULL;
-- ALTER TABLE jute_prod_winding_doff       CHANGE item_id yarn_quality_id INT NULL;
-- ALTER TABLE jute_prod_winding_daily_qlty CHANGE item_id yarn_quality_id INT NULL;
-- =============================================================================
