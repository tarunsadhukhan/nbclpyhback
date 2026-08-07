-- ============================================================================
-- Migration: Yarn Master → Item Master Integration
-- Date: 2026-02-19
-- Description: 
--   Each jute_yarn_mst record should also have a corresponding item_mst record.
--   This migration:
--   1. Adds item_id column to jute_yarn_mst
--   2. Creates item_mst records for all existing jute_yarn_mst rows
--   3. Backfills the item_id FK in jute_yarn_mst
--
-- Rollback:
--   ALTER TABLE jute_yarn_mst DROP COLUMN item_id;
--   DELETE FROM item_mst WHERE item_code LIKE 'YARN-%';
-- ============================================================================

-- Step 1: Add item_id column to jute_yarn_mst
ALTER TABLE jute_yarn_mst
ADD COLUMN item_id INT NULL AFTER jute_yarn_remarks;

-- Step 2: Create item_mst records for each existing yarn
-- Default values: active=1, tangible=1, hsn_code='5304', tax_percentage=5,
-- saleable=1, consumable=1, purchaseable=1, manufacturable=1,
-- uom_rounding=0, rate_rounding=2, uom_id=163
-- item_code format: YARN-{jute_yarn_id} (guaranteed unique)
-- item_name: from jute_yarn_name
-- item_grp_id: from jute_yarn_mst.item_grp_id
INSERT INTO item_mst (
    active,
    updated_date_time,
    updated_by,
    item_grp_id,
    item_code,
    tangible,
    item_name,
    hsn_code,
    uom_id,
    tax_percentage,
    saleable,
    consumable,
    purchaseable,
    manufacturable,
    assembly,
    uom_rounding,
    rate_rounding
)
SELECT
    1,                                    -- active
    NOW(),                                -- updated_date_time
    ym.updated_by,                        -- updated_by (from yarn record)
    ym.item_grp_id,                       -- item_grp_id (same group)
    CONCAT('YARN-', ym.jute_yarn_id),     -- item_code (unique per yarn)
    1,                                    -- tangible
    ym.jute_yarn_name,                    -- item_name (from yarn name)
    '5304',                               -- hsn_code
    163,                                  -- uom_id
    5,                                    -- tax_percentage (5%)
    1,                                    -- saleable
    1,                                    -- consumable
    1,                                    -- purchaseable
    1,                                    -- manufacturable
    0,                                    -- assembly
    0,                                    -- uom_rounding
    2                                     -- rate_rounding
FROM jute_yarn_mst ym;

-- Step 3: Backfill item_id in jute_yarn_mst using item_code mapping
UPDATE jute_yarn_mst ym
INNER JOIN item_mst im ON im.item_code = CONCAT('YARN-', ym.jute_yarn_id)
SET ym.item_id = im.item_id;

-- Step 4: Verification queries (run these to confirm)
-- Check all yarns have item_id populated:
-- SELECT jute_yarn_id, jute_yarn_name, item_id FROM jute_yarn_mst WHERE item_id IS NULL;
-- Should return 0 rows.

-- Check item_mst records match:
-- SELECT im.item_id, im.item_code, im.item_name, im.item_grp_id, ym.jute_yarn_id, ym.jute_yarn_name
-- FROM jute_yarn_mst ym
-- INNER JOIN item_mst im ON ym.item_id = im.item_id
-- ORDER BY ym.jute_yarn_id;
-- Should show 15 rows (matching existing yarn count).
