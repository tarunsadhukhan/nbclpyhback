-- Migration: Add audit/display columns to daily_doff_frames_winding
-- Date: 2026-06-17
-- Applies to: tenant databases (dev3 default; run per tenant as needed)
--
-- Adds:
--   daily_doff_frames_winding.updated_by         INT NULL      (user_mst.user_id of last saver)
--   daily_doff_frames_winding.updated_date_time  DATETIME NULL (timestamp of last save)
--
-- Used by the Spinning Frame -> Quality mapping: every Save Map stamps these on the
-- upserted active S-row, and the grid surfaces the branch's most-recent
-- updated_date_time. Nullable-add-only, idempotent via INFORMATION_SCHEMA guard so
-- the script is safe to re-run. Mirrors the existing daily_doff_tbl columns.

-- ---------------------------------------------------------------------------
-- daily_doff_frames_winding.updated_by
SET @c := (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='daily_doff_frames_winding' AND COLUMN_NAME='updated_by');
SET @s := IF(@c=0,'ALTER TABLE daily_doff_frames_winding ADD COLUMN updated_by INT NULL','SELECT 1');
PREPARE st FROM @s; EXECUTE st; DEALLOCATE PREPARE st;

-- daily_doff_frames_winding.updated_date_time
SET @c := (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='daily_doff_frames_winding' AND COLUMN_NAME='updated_date_time');
SET @s := IF(@c=0,'ALTER TABLE daily_doff_frames_winding ADD COLUMN updated_date_time DATETIME NULL','SELECT 1');
PREPARE st FROM @s; EXECUTE st; DEALLOCATE PREPARE st;

-- =============================================================================
-- ROLLBACK:
-- ALTER TABLE daily_doff_frames_winding DROP COLUMN updated_by;
-- ALTER TABLE daily_doff_frames_winding DROP COLUMN updated_date_time;
-- =============================================================================
