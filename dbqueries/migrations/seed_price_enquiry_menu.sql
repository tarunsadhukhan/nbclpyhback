-- Migration: Price Enquiry Module — Menu Registration
-- Purpose: Register the Price Enquiry page in the portal menu system so the
--          sidebar shows it, useMenuId can resolve a menu_id, and the portal
--          permission check (view/print/create/edit) allows the route.
--
-- Run in TWO places:
--   Part 1 -> against the TENANT database(s) (e.g. dev3, sls): menu_mst + role_menu_map
--   Part 2 -> against vowconsole3: portal_menu_mst template (for future tenants)
--
-- Both parts are idempotent (guarded by NOT EXISTS) and derive parent/module/
-- role grants from the existing Indent menu so no IDs are hardcoded.
--
-- Rollback:
--   DELETE rmm FROM role_menu_map rmm JOIN menu_mst m ON m.menu_id = rmm.menu_id
--     WHERE m.menu_path LIKE '%procurement/priceEnquiry%';
--   DELETE FROM menu_mst WHERE menu_path LIKE '%procurement/priceEnquiry%';
--   DELETE FROM vowconsole3.portal_menu_mst WHERE menu_path LIKE '%procurement/priceEnquiry%';

-- ============================================================================
-- Part 1a: TENANT DB — menu_mst entry (path pattern copied from the Indent menu)
-- ============================================================================
INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by)
SELECT
    'Price Enquiry',
    REPLACE(m.menu_path, 'indent', 'priceEnquiry'),
    1,
    m.menu_parent_id,
    m.menu_type_id,
    m.menu_icon,
    m.module_mst_id,
    COALESCE(m.order_by, 0) + 1
FROM menu_mst m
WHERE LOWER(m.menu_path) LIKE '%procurement/indent'
  AND NOT EXISTS (
      SELECT 1 FROM menu_mst e WHERE LOWER(e.menu_path) LIKE '%procurement/priceenquiry'
  )
LIMIT 1;

-- ============================================================================
-- Part 1b: TENANT DB — grant every role that can use Indent the same access
--          levels (view=1 / print=2 / create=3 / edit=4) on Price Enquiry
-- ============================================================================
INSERT INTO role_menu_map (role_id, menu_id, access_type_id, updated_by)
SELECT rmm.role_id, pe.menu_id, rmm.access_type_id, rmm.updated_by
FROM role_menu_map rmm
JOIN menu_mst mi ON mi.menu_id = rmm.menu_id AND LOWER(mi.menu_path) LIKE '%procurement/indent'
JOIN menu_mst pe ON LOWER(pe.menu_path) LIKE '%procurement/priceenquiry'
WHERE NOT EXISTS (
    SELECT 1 FROM role_menu_map e
    WHERE e.role_id = rmm.role_id
      AND e.menu_id = pe.menu_id
      AND e.access_type_id = rmm.access_type_id
);

-- ============================================================================
-- Part 2: vowconsole3 — portal_menu_mst template entry (run against vowconsole3)
-- ============================================================================
-- INSERT INTO portal_menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_id)
-- SELECT
--     'Price Enquiry',
--     REPLACE(m.menu_path, 'indent', 'priceEnquiry'),
--     1,
--     m.menu_parent_id,
--     m.menu_type_id,
--     m.menu_icon,
--     m.module_id
-- FROM portal_menu_mst m
-- WHERE LOWER(m.menu_path) LIKE '%procurement/indent'
--   AND NOT EXISTS (
--       SELECT 1 FROM portal_menu_mst e WHERE LOWER(e.menu_path) LIKE '%procurement/priceenquiry'
--   )
-- LIMIT 1;
