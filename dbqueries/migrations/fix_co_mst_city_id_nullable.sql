-- =============================================================================
-- Migration: Make co_mst.city_id nullable
-- Date: 2026-03-11
-- Description:
--   city_id is being deprecated (see deprecate_city_mst.sql).
--   co_mst.city_id was NOT NULL with no default, causing inserts to fail
--   since the create-company UI does not collect city_id.
--   This makes the column nullable so company creation works without it.
-- =============================================================================

ALTER TABLE co_mst MODIFY COLUMN city_id INT NULL;

-- =============================================================================
-- ROLLBACK (if needed):
-- ALTER TABLE co_mst MODIFY COLUMN city_id INT NOT NULL;
-- =============================================================================
