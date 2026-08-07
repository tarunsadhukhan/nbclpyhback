-- =============================================================================
-- MIGRATION: Move yarn types from jute_yarn_type_mst to item_grp_mst
-- =============================================================================
-- Run this script PER TENANT DATABASE (e.g. dev3, sls, etc.)
-- This must be run BEFORE deploying the updated backend code.
--
-- What this does:
-- 1. Inserts item_type_id=4 ('Yarn') into item_type_master (if not exists)
-- 2. Copies all jute_yarn_type_mst rows into item_grp_mst with item_type_id=4
-- 3. Creates a temp mapping table for old→new IDs
-- 4. Updates jute_yarn_mst.jute_yarn_type_id to point to new item_grp_mst IDs
-- 5. Updates yarn_quality_master.yarn_type_id to point to new item_grp_mst IDs
-- 6. Renames columns: jute_yarn_mst.jute_yarn_type_id → item_grp_id
--                      yarn_quality_master.yarn_type_id → item_grp_id
--
-- ROLLBACK instructions are in comments at the bottom.
-- =============================================================================

-- Step 0: Safety check — verify tables exist
SELECT COUNT(*) INTO @jyt_exists FROM information_schema.tables 
WHERE table_schema = DATABASE() AND table_name = 'jute_yarn_type_mst';

SELECT COUNT(*) INTO @igm_exists FROM information_schema.tables 
WHERE table_schema = DATABASE() AND table_name = 'item_grp_mst';

-- Abort if source table doesn't exist
-- (If jute_yarn_type_mst doesn't exist, this tenant may not have yarn data)

-- =============================================================================
-- Step 1: Ensure item_type_id=4 ('Yarn') exists in item_type_master
-- =============================================================================
INSERT INTO item_type_master (item_type_id, item_type_name, updated_by, updated_date_time)
SELECT 4, 'Yarn', 1, NOW()
FROM DUAL
WHERE NOT EXISTS (
    SELECT 1 FROM item_type_master WHERE item_type_id = 4
);

-- =============================================================================
-- Step 2: Create temporary mapping table
-- =============================================================================
DROP TABLE IF EXISTS _yarn_type_migration_map;
CREATE TABLE _yarn_type_migration_map (
    old_jute_yarn_type_id INT NOT NULL,
    new_item_grp_id BIGINT NULL,
    co_id INT,
    yarn_type_name VARCHAR(255),
    PRIMARY KEY (old_jute_yarn_type_id)
);

-- =============================================================================
-- Step 3: Insert existing yarn types into item_grp_mst
-- =============================================================================

-- First, populate the mapping table with source data
INSERT INTO _yarn_type_migration_map (old_jute_yarn_type_id, co_id, yarn_type_name)
SELECT jute_yarn_type_id, co_id, jute_yarn_type_name
FROM jute_yarn_type_mst;

-- Insert into item_grp_mst
-- item_grp_code = 'YT-' + old ID (to ensure uniqueness)
-- parent_grp_id = NULL (top-level groups)
-- active = 'Y'
-- item_type_id = 4 (Yarn)
INSERT INTO item_grp_mst (
    parent_grp_id, active, co_id, updated_by, updated_date_time,
    item_grp_name, item_grp_code, purchase_code, item_type_id
)
SELECT 
    NULL,                                       -- parent_grp_id
    'Y',                                        -- active
    jyt.co_id,                                  -- co_id
    COALESCE(jyt.updated_by, 1),                -- updated_by
    COALESCE(jyt.updated_date_time, NOW()),     -- updated_date_time
    jyt.jute_yarn_type_name,                    -- item_grp_name
    CONCAT('YT-', jyt.jute_yarn_type_id),       -- item_grp_code
    NULL,                                       -- purchase_code
    4                                           -- item_type_id (Yarn)
FROM jute_yarn_type_mst jyt;

-- Update the mapping table with the new item_grp_id values
-- Match by name + co_id + item_type_id=4 to find newly inserted rows
UPDATE _yarn_type_migration_map m
INNER JOIN item_grp_mst ig 
    ON ig.item_grp_name = m.yarn_type_name 
    AND ig.co_id = m.co_id 
    AND ig.item_type_id = 4
    AND ig.item_grp_code = CONCAT('YT-', m.old_jute_yarn_type_id)
SET m.new_item_grp_id = ig.item_grp_id;

-- Verify all mappings were created
SELECT 
    COUNT(*) AS total_mappings,
    SUM(CASE WHEN new_item_grp_id IS NOT NULL THEN 1 ELSE 0 END) AS successful_mappings,
    SUM(CASE WHEN new_item_grp_id IS NULL THEN 1 ELSE 0 END) AS failed_mappings
FROM _yarn_type_migration_map;

-- =============================================================================
-- Step 4: Update jute_yarn_mst — replace old IDs with new item_grp_mst IDs
-- =============================================================================
UPDATE jute_yarn_mst ym
INNER JOIN _yarn_type_migration_map m ON ym.jute_yarn_type_id = m.old_jute_yarn_type_id
SET ym.jute_yarn_type_id = m.new_item_grp_id;

-- =============================================================================
-- Step 5: Update yarn_quality_master — replace old IDs with new item_grp_mst IDs
-- =============================================================================
UPDATE yarn_quality_master yq
INNER JOIN _yarn_type_migration_map m ON yq.yarn_type_id = m.old_jute_yarn_type_id
SET yq.yarn_type_id = m.new_item_grp_id;

-- =============================================================================
-- Step 6: Rename columns to match new FK target
-- =============================================================================

-- Rename jute_yarn_mst.jute_yarn_type_id → item_grp_id
ALTER TABLE jute_yarn_mst 
CHANGE COLUMN jute_yarn_type_id item_grp_id BIGINT NULL;

-- Rename yarn_quality_master.yarn_type_id → item_grp_id
ALTER TABLE yarn_quality_master 
CHANGE COLUMN yarn_type_id item_grp_id INT NULL;

-- =============================================================================
-- Step 7: Verify migration
-- =============================================================================

-- Check jute_yarn_mst references are valid
SELECT 'jute_yarn_mst orphans' AS check_name, COUNT(*) AS orphan_count
FROM jute_yarn_mst ym
WHERE ym.item_grp_id IS NOT NULL
AND NOT EXISTS (SELECT 1 FROM item_grp_mst ig WHERE ig.item_grp_id = ym.item_grp_id);

-- Check yarn_quality_master references are valid
SELECT 'yarn_quality_master orphans' AS check_name, COUNT(*) AS orphan_count
FROM yarn_quality_master yq
WHERE yq.item_grp_id IS NOT NULL
AND NOT EXISTS (SELECT 1 FROM item_grp_mst ig WHERE ig.item_grp_id = yq.item_grp_id);

-- Show mapping summary
SELECT * FROM _yarn_type_migration_map;

-- =============================================================================
-- Step 8: Cleanup (run after verifying everything works)
-- =============================================================================
-- Uncomment these after verifying the migration is correct:
-- DROP TABLE IF EXISTS _yarn_type_migration_map;
-- The jute_yarn_type_mst table is kept for rollback safety.
-- DROP TABLE IF EXISTS jute_yarn_type_mst;  -- only after full verification

-- =============================================================================
-- ROLLBACK (if needed — run BEFORE dropping _yarn_type_migration_map)
-- =============================================================================
-- 
-- -- Rename columns back
-- ALTER TABLE jute_yarn_mst CHANGE COLUMN item_grp_id jute_yarn_type_id INT NULL;
-- ALTER TABLE yarn_quality_master CHANGE COLUMN item_grp_id yarn_type_id INT NULL;
--
-- -- Restore old IDs in jute_yarn_mst
-- UPDATE jute_yarn_mst ym
-- INNER JOIN _yarn_type_migration_map m ON ym.jute_yarn_type_id = m.new_item_grp_id
-- SET ym.jute_yarn_type_id = m.old_jute_yarn_type_id;
--
-- -- Restore old IDs in yarn_quality_master
-- UPDATE yarn_quality_master yq
-- INNER JOIN _yarn_type_migration_map m ON yq.yarn_type_id = m.new_item_grp_id
-- SET yq.yarn_type_id = m.old_jute_yarn_type_id;
--
-- -- Remove migrated item_grp_mst rows
-- DELETE ig FROM item_grp_mst ig
-- INNER JOIN _yarn_type_migration_map m ON ig.item_grp_id = m.new_item_grp_id;
--
-- -- Cleanup
-- DROP TABLE IF EXISTS _yarn_type_migration_map;
