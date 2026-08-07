-- Migration: Add spinning linkage columns to reused mobile doff tables
-- Date: 2026-06-11
-- Applies to: tenant databases dev3 AND sls
--
-- Nullable-add-only, idempotent via INFORMATION_SCHEMA.COLUMNS existence guard so the
-- script is safe to re-run and works whether or not the columns already exist.
--   daily_doff_tbl:            ADD yarn_quality_id, param_id, eb_id
--   daily_doff_frames_winding: ADD yarn_quality_id, param_id

-- ---------------------------------------------------------------------------
-- daily_doff_tbl.yarn_quality_id
SET @c := (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='daily_doff_tbl' AND COLUMN_NAME='yarn_quality_id');
SET @s := IF(@c=0,'ALTER TABLE daily_doff_tbl ADD COLUMN yarn_quality_id INT NULL','SELECT 1');
PREPARE st FROM @s; EXECUTE st; DEALLOCATE PREPARE st;

-- daily_doff_tbl.param_id
SET @c := (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='daily_doff_tbl' AND COLUMN_NAME='param_id');
SET @s := IF(@c=0,'ALTER TABLE daily_doff_tbl ADD COLUMN param_id INT NULL','SELECT 1');
PREPARE st FROM @s; EXECUTE st; DEALLOCATE PREPARE st;

-- daily_doff_tbl.eb_id
SET @c := (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='daily_doff_tbl' AND COLUMN_NAME='eb_id');
SET @s := IF(@c=0,'ALTER TABLE daily_doff_tbl ADD COLUMN eb_id INT NULL','SELECT 1');
PREPARE st FROM @s; EXECUTE st; DEALLOCATE PREPARE st;

-- ---------------------------------------------------------------------------
-- daily_doff_frames_winding.yarn_quality_id
SET @c := (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='daily_doff_frames_winding' AND COLUMN_NAME='yarn_quality_id');
SET @s := IF(@c=0,'ALTER TABLE daily_doff_frames_winding ADD COLUMN yarn_quality_id INT NULL','SELECT 1');
PREPARE st FROM @s; EXECUTE st; DEALLOCATE PREPARE st;

-- daily_doff_frames_winding.param_id
SET @c := (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='daily_doff_frames_winding' AND COLUMN_NAME='param_id');
SET @s := IF(@c=0,'ALTER TABLE daily_doff_frames_winding ADD COLUMN param_id INT NULL','SELECT 1');
PREPARE st FROM @s; EXECUTE st; DEALLOCATE PREPARE st;

-- =============================================================================
-- ROLLBACK:
-- ALTER TABLE daily_doff_tbl DROP COLUMN yarn_quality_id;
-- ALTER TABLE daily_doff_tbl DROP COLUMN param_id;
-- ALTER TABLE daily_doff_tbl DROP COLUMN eb_id;
-- ALTER TABLE daily_doff_frames_winding DROP COLUMN yarn_quality_id;
-- ALTER TABLE daily_doff_frames_winding DROP COLUMN param_id;
-- =============================================================================
