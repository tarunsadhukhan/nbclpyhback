-- =============================================================================
-- Migration: Seed Portal menus for the AMCL Enquiry Flow — Phase 1
-- =============================================================================
-- Date: 2026-07-06
-- Spec: docs/amcl-enquiry-flow-design.md §7 (Menus)
-- Applies to: tenant database dev3 (QA) FIRST — the tenant menu_mst +
--   role_menu_map rows. A COMMENTED template for the vowconsole3
--   portal_menu_mst master template is at the end of this file (separate DB —
--   run it separately against vowconsole3 after review).
-- Run AFTER create_amcl_enquiry_flow_phase1.sql (the ISO map master page needs
--   co_menu_iso_map, and the enquiry approval hierarchy anchors on the new
--   'Customer Enquiry' menu row's menu_id in approval_mst).
--
-- Menus seeded (Portal sidebar):
--   Sales       > Customer Enquiry     -> sales/enquiry
--   Sales       > Enquiry Flow Board   -> sales/enquiry/board
--   BOM Costing > Costing Review       -> BomCosting/costingReview
--   Procurement > Price Check          -> procurement/priceCheck
--   Masters     > ISO Document No Map  -> masters/isoDocMap
--
-- menu_path convention: NO '/dashboardportal' prefix and no leading slash —
--   the portal sidebar renders href as /dashboardportal/{menu_path}
--   (src/components/dashboard/sidebar.tsx), matching the juteSQC and
--   procurement/reports_1 seeds.
--
-- DEFENSIVE-BY-CONSTRUCTION (the DB is not reachable from the authoring
-- machine, so nothing here hardcodes a parent menu_id):
--   * menu_parent_id + module_mst_id are COPIED from a known SIBLING menu row
--     (e.g. the quotation page for the Sales section) — this works regardless
--     of the parent's display name or id on the target tenant.
--   * If no sibling row matches, the derived table is empty and the INSERT is
--     a silent no-op — run the VERIFICATION queries at the end afterwards.
--   * Idempotent: INSERT IGNORE (menu_name is UNIQUE) + NOT EXISTS guard on
--     menu_path. The NOT EXISTS uses a trailing LIKE so an existing row stored
--     with a '/dashboardportal/' prefix also blocks a duplicate.
--   * role_menu_map: grants role 1 (admin) with access_type_id 4 (edit) only,
--     guarded with NOT EXISTS. Grant further roles (costing / procurement /
--     sales users) via the Portal admin UI per tenant policy.
--
-- RUNNER NOTE (run-migration skill): statements are split on the semicolon
--   character and any chunk that STARTS with a comment marker is skipped.
--   Every comment block below is therefore terminated by a lone semicolon on
--   its own line. Comment prose must never contain a mid-line semicolon.
--
-- Rollback: see trailing comment block at end of file.
;

-- =============================================================================
-- 1. Sales > Customer Enquiry (enquiry list + create/edit/view pages).
--    Sibling anchor = the existing quotation or sales order menu row.
--    order_by 210 appends to the Sales section (reorder in admin if desired).
-- =============================================================================
;
INSERT IGNORE INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by, report)
SELECT 'Customer Enquiry', 'sales/enquiry', 1, s.menu_parent_id, NULL, 'contact_mail', s.module_mst_id, 210, NULL
FROM (
    SELECT menu_parent_id, module_mst_id
    FROM menu_mst
    WHERE (menu_path LIKE '%sales/quotation' OR menu_path LIKE '%sales/salesOrder')
      AND active = 1
      AND menu_parent_id IS NOT NULL
    ORDER BY menu_id
    LIMIT 1
) s
WHERE NOT EXISTS (SELECT 1 FROM menu_mst WHERE menu_path LIKE '%sales/enquiry');

-- =============================================================================
-- 2. Sales > Enquiry Flow Board (kanban-style stage board).
--    Same Sales sibling anchor. Sits beside (not under) Customer Enquiry —
--    the menu tree is driven by menu_parent_id, not by the path nesting.
-- =============================================================================
;
INSERT IGNORE INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by, report)
SELECT 'Enquiry Flow Board', 'sales/enquiry/board', 1, s.menu_parent_id, NULL, 'view_kanban', s.module_mst_id, 220, NULL
FROM (
    SELECT menu_parent_id, module_mst_id
    FROM menu_mst
    WHERE (menu_path LIKE '%sales/quotation' OR menu_path LIKE '%sales/salesOrder')
      AND active = 1
      AND menu_parent_id IS NOT NULL
    ORDER BY menu_id
    LIMIT 1
) s
WHERE NOT EXISTS (SELECT 1 FROM menu_mst WHERE menu_path LIKE '%sales/enquiry/board');

-- =============================================================================
-- 3. BOM Costing > Costing Review (Design & Costing worklist — enquiries in
--    COSTING_REVIEW, confirm-costing + raise-price-check actions).
--    Sibling anchor = any existing BomCosting page menu row.
-- =============================================================================
;
INSERT IGNORE INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by, report)
SELECT 'Costing Review', 'BomCosting/costingReview', 1, s.menu_parent_id, NULL, 'fact_check', s.module_mst_id, 210, NULL
FROM (
    SELECT menu_parent_id, module_mst_id
    FROM menu_mst
    WHERE (menu_path LIKE '%BomCosting/bomCosting'
           OR menu_path LIKE '%BomCosting/itemBomMaster'
           OR menu_path LIKE '%BomCosting/costElementMaster')
      AND active = 1
      AND menu_parent_id IS NOT NULL
    ORDER BY menu_id
    LIMIT 1
) s
WHERE NOT EXISTS (SELECT 1 FROM menu_mst WHERE menu_path LIKE '%BomCosting/costingReview');

-- =============================================================================
-- 4. Procurement > Price Check (procurement worklist of pending
--    enquiry_price_check requests, response form with last-PO prefill).
--    Sibling anchor = the existing indent or purchase order menu row.
-- =============================================================================
;
INSERT IGNORE INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by, report)
SELECT 'Price Check', 'procurement/priceCheck', 1, s.menu_parent_id, NULL, 'price_check', s.module_mst_id, 210, NULL
FROM (
    SELECT menu_parent_id, module_mst_id
    FROM menu_mst
    WHERE (menu_path LIKE '%procurement/indent' OR menu_path LIKE '%procurement/purchaseOrder')
      AND active = 1
      AND menu_parent_id IS NOT NULL
    ORDER BY menu_id
    LIMIT 1
) s
WHERE NOT EXISTS (SELECT 1 FROM menu_mst WHERE menu_path LIKE '%procurement/priceCheck');

-- =============================================================================
-- 5. Masters > ISO Document No Map (CRUD for co_menu_iso_map — company x
--    document-type menu -> ISO number, rendered on document views/prints).
--    Sibling anchor = the existing item or party master menu row.
-- =============================================================================
;
INSERT IGNORE INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by, report)
SELECT 'ISO Document No Map', 'masters/isoDocMap', 1, s.menu_parent_id, NULL, 'tag', s.module_mst_id, 210, NULL
FROM (
    SELECT menu_parent_id, module_mst_id
    FROM menu_mst
    WHERE (menu_path LIKE '%masters/itemMaster' OR menu_path LIKE '%masters/partyMaster')
      AND active = 1
      AND menu_parent_id IS NOT NULL
    ORDER BY menu_id
    LIMIT 1
) s
WHERE NOT EXISTS (SELECT 1 FROM menu_mst WHERE menu_path LIKE '%masters/isoDocMap');

-- =============================================================================
-- 6. Role grants — role 1 (admin), access_type_id 4 (edit), for every menu
--    seeded above. Re-runnable (NOT EXISTS per role+menu). Mirrors the
--    juteSQC morrah seed. updated_by 1 = system/admin seed user.
-- =============================================================================
;
INSERT INTO role_menu_map (role_id, menu_id, access_type_id, updated_by, updated_date_time)
SELECT 1, m.menu_id, 4, 1, NOW()
FROM menu_mst m
WHERE m.menu_path IN ('sales/enquiry', 'sales/enquiry/board', 'BomCosting/costingReview', 'procurement/priceCheck', 'masters/isoDocMap')
  AND NOT EXISTS (
      SELECT 1 FROM role_menu_map r
      WHERE r.menu_id = m.menu_id AND r.role_id = 1
  );

-- =============================================================================
-- VERIFICATION (run manually after applying — every query must return a row
-- for each of the five paths. A missing row means the sibling anchor for that
-- section did not resolve on this tenant and the menu must be added with an
-- explicit parent):
--
--   SELECT menu_id, menu_name, menu_path, menu_parent_id, module_mst_id, order_by
--     FROM menu_mst
--    WHERE menu_path IN ('sales/enquiry', 'sales/enquiry/board', 'BomCosting/costingReview', 'procurement/priceCheck', 'masters/isoDocMap');
--
--   SELECT r.role_id, m.menu_path, r.access_type_id
--     FROM role_menu_map r JOIN menu_mst m ON m.menu_id = r.menu_id
--    WHERE m.menu_path IN ('sales/enquiry', 'sales/enquiry/board', 'BomCosting/costingReview', 'procurement/priceCheck', 'masters/isoDocMap');
--
-- Post-seed manual steps:
--   1. Configure the enquiry approval hierarchy (dashboardadmin >
--      approvalHierarchy) — approval_mst rows anchor on the new
--      'Customer Enquiry' menu_id.
--   2. Grant the worklist menus to the operating roles (costing, procurement,
--      sales) via the Portal admin UI — role 1 only is seeded here.
-- =============================================================================
--
-- =============================================================================
-- vowconsole3 TEMPLATE (portal_menu_mst is the master template used when
-- provisioning tenant portal menus). COMMENTED OUT on purpose: this block
-- targets the vowconsole3 SYSTEM database, not the tenant DB — copy it into a
-- session against vowconsole3, resolve the parent anchors there, and confirm
-- with the user first (system-DB changes always need an explicit yes).
-- portal_menu_mst columns: menu_name (UNIQUE), menu_path, active,
-- menu_parent_id, menu_type_id, menu_icon, module_id — note module_id here,
-- NOT module_mst_id as in the tenant menu_mst.
--
--   INSERT IGNORE INTO portal_menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_id)
--   SELECT 'Customer Enquiry', 'sales/enquiry', 1, s.menu_parent_id, NULL, 'contact_mail', s.module_id
--   FROM (SELECT menu_parent_id, module_id FROM portal_menu_mst
--          WHERE (menu_path LIKE '%sales/quotation' OR menu_path LIKE '%sales/salesOrder')
--            AND active = 1 AND menu_parent_id IS NOT NULL ORDER BY menu_id LIMIT 1) s
--   WHERE NOT EXISTS (SELECT 1 FROM portal_menu_mst WHERE menu_path LIKE '%sales/enquiry');
--
--   INSERT IGNORE INTO portal_menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_id)
--   SELECT 'Enquiry Flow Board', 'sales/enquiry/board', 1, s.menu_parent_id, NULL, 'view_kanban', s.module_id
--   FROM (SELECT menu_parent_id, module_id FROM portal_menu_mst
--          WHERE (menu_path LIKE '%sales/quotation' OR menu_path LIKE '%sales/salesOrder')
--            AND active = 1 AND menu_parent_id IS NOT NULL ORDER BY menu_id LIMIT 1) s
--   WHERE NOT EXISTS (SELECT 1 FROM portal_menu_mst WHERE menu_path LIKE '%sales/enquiry/board');
--
--   INSERT IGNORE INTO portal_menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_id)
--   SELECT 'Costing Review', 'BomCosting/costingReview', 1, s.menu_parent_id, NULL, 'fact_check', s.module_id
--   FROM (SELECT menu_parent_id, module_id FROM portal_menu_mst
--          WHERE (menu_path LIKE '%BomCosting/bomCosting' OR menu_path LIKE '%BomCosting/itemBomMaster' OR menu_path LIKE '%BomCosting/costElementMaster')
--            AND active = 1 AND menu_parent_id IS NOT NULL ORDER BY menu_id LIMIT 1) s
--   WHERE NOT EXISTS (SELECT 1 FROM portal_menu_mst WHERE menu_path LIKE '%BomCosting/costingReview');
--
--   INSERT IGNORE INTO portal_menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_id)
--   SELECT 'Price Check', 'procurement/priceCheck', 1, s.menu_parent_id, NULL, 'price_check', s.module_id
--   FROM (SELECT menu_parent_id, module_id FROM portal_menu_mst
--          WHERE (menu_path LIKE '%procurement/indent' OR menu_path LIKE '%procurement/purchaseOrder')
--            AND active = 1 AND menu_parent_id IS NOT NULL ORDER BY menu_id LIMIT 1) s
--   WHERE NOT EXISTS (SELECT 1 FROM portal_menu_mst WHERE menu_path LIKE '%procurement/priceCheck');
--
--   INSERT IGNORE INTO portal_menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_id)
--   SELECT 'ISO Document No Map', 'masters/isoDocMap', 1, s.menu_parent_id, NULL, 'tag', s.module_id
--   FROM (SELECT menu_parent_id, module_id FROM portal_menu_mst
--          WHERE (menu_path LIKE '%masters/itemMaster' OR menu_path LIKE '%masters/partyMaster')
--            AND active = 1 AND menu_parent_id IS NOT NULL ORDER BY menu_id LIMIT 1) s
--   WHERE NOT EXISTS (SELECT 1 FROM portal_menu_mst WHERE menu_path LIKE '%masters/isoDocMap');
-- =============================================================================
--
-- =============================================================================
-- ROLLBACK (run manually against the tenant DB):
--
--   DELETE r FROM role_menu_map r JOIN menu_mst m ON m.menu_id = r.menu_id
--    WHERE m.menu_path IN ('sales/enquiry', 'sales/enquiry/board', 'BomCosting/costingReview', 'procurement/priceCheck', 'masters/isoDocMap');
--   DELETE FROM menu_mst
--    WHERE menu_path IN ('sales/enquiry', 'sales/enquiry/board', 'BomCosting/costingReview', 'procurement/priceCheck', 'masters/isoDocMap');
--
-- And against vowconsole3 (only if the template block above was applied):
--
--   DELETE FROM portal_menu_mst
--    WHERE menu_path IN ('sales/enquiry', 'sales/enquiry/board', 'BomCosting/costingReview', 'procurement/priceCheck', 'masters/isoDocMap');
-- =============================================================================
