-- =============================================================================
-- Migration: Deprecate city_mst table
-- Date: 2026-02-25
-- Description: 
--   1. Add state_id column to party_branch_mst (direct state reference)
--   2. Backfill state_id from city_mst lookup
--   3. Remove city_id FK constraints (but keep column for now)
--   NOTE: city_mst table is NOT dropped — it is simply no longer used by the app.
-- =============================================================================

-- Step 1: Add state_id to party_branch_mst if it doesn't exist
ALTER TABLE party_branch_mst 
ADD COLUMN state_id INT NULL AFTER city_id,
ADD INDEX idx_party_branch_mst_state_id (state_id);

-- Step 2: Backfill state_id from city_mst
UPDATE party_branch_mst pbm
LEFT JOIN city_mst cm ON cm.city_id = pbm.city_id
SET pbm.state_id = cm.state_id
WHERE pbm.city_id IS NOT NULL AND pbm.state_id IS NULL;

-- =============================================================================
-- ROLLBACK (if needed):
-- ALTER TABLE party_branch_mst DROP COLUMN state_id;
-- =============================================================================
