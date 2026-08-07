-- Migration: Add `report` flag to menu_mst
-- Date: 2026-06-25
-- Applies to: tenant databases that don't already have the column (e.g., sls).
--   dev3 ALREADY has `report` (as int NULL) with rows flagged — this is a no-op there.
--
-- Why: report-type pages render a dynamic menu -> submenu -> sub-submenu selector
--   (ReportMenuSelect) populated from menu_mst rows flagged report = 1 that descend
--   from the page's own menu_path. Tenants missing the column raise
--   "Unknown column 'report'" in get_report_menu_tree() -> 500.
--
-- Additive. MySQL 8 has no `ADD COLUMN IF NOT EXISTS`, so guard with information_schema.

-- =============================================================================
-- 1. Add the column only if absent (idempotent).
-- =============================================================================
SET @col_exists := (
    SELECT COUNT(*) FROM information_schema.columns
    WHERE table_schema = DATABASE()
      AND table_name = 'menu_mst'
      AND column_name = 'report'
);
SET @ddl := IF(@col_exists = 0,
    'ALTER TABLE menu_mst ADD COLUMN report TINYINT(1) NOT NULL DEFAULT 0 COMMENT ''1 = report row shown in ReportMenuSelect''',
    'DO 0');
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- =============================================================================
-- 2. Flag the report rows. Reports are the descendants of a reports anchor page;
--    flag by parent (menu_path is inconsistent across these rows). EDIT the
--    anchor menu_path per tenant. These descendant rows must already exist.
-- =============================================================================
-- UPDATE menu_mst SET report = 1
-- WHERE menu_parent_id = (
--     SELECT menu_id FROM (
--         SELECT menu_id FROM menu_mst
--         WHERE LOWER(TRIM(menu_path)) = 'jutepurchase/reports' AND active = 1 LIMIT 1
--     ) anchor
-- );

-- =============================================================================
-- ROLLBACK:
-- ALTER TABLE menu_mst DROP COLUMN report;
-- =============================================================================
