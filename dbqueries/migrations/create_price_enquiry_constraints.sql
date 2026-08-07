-- Migration: Price Enquiry Module — Integrity Constraints
-- Purpose: Add the durable data-integrity guards that the initial
--          create_price_enquiry_tables.sql migration did not include:
--            1. UNIQUE document number per branch + financial year
--            2. FK on proc_enquiry_supplier.supplier_branch_id
--            3. FK on proc_enquiry_dtl.enquiry_id
-- Date: 2026-06-29
-- Run AFTER create_price_enquiry_tables.sql, against the TENANT database.
-- Note: Plain MySQL 8 DDL. The migration runner should catch
--       "Duplicate key name" / "Duplicate foreign key constraint name" /
--       errno 121/150 and treat them as idempotent skips. Requires MySQL
--       8.0.13+ for the functional key part on the financial-year expression.
--       Financial year = April–March, so the FY-start year is derived by
--       shifting the date back three months: YEAR(date - INTERVAL 3 MONTH).

-- ═══════════════════════════════════════════════════════════════════
-- 1. UNIQUE document number — prevents duplicate enquiry_no under
--    concurrent create_enquiry calls within the same branch + FY.
--    NULL enquiry_no rows are exempt (MySQL allows multiple NULLs),
--    so reopened/blank drafts do not collide.
-- ═══════════════════════════════════════════════════════════════════

ALTER TABLE proc_enquiry
    ADD UNIQUE KEY uk_enq_branch_fy
    (branch_id, enquiry_no, (YEAR(price_enquiry_date - INTERVAL 3 MONTH)));


-- ═══════════════════════════════════════════════════════════════════
-- 2. FK: proc_enquiry_supplier.supplier_branch_id -> party_branch_mst
--    Prevents orphaned/stale supplier-branch references.
-- ═══════════════════════════════════════════════════════════════════

ALTER TABLE proc_enquiry_supplier
    ADD CONSTRAINT fk_enq_supp_branch
    FOREIGN KEY (supplier_branch_id) REFERENCES party_branch_mst(party_mst_branch_id);


-- ═══════════════════════════════════════════════════════════════════
-- 3. FK: proc_enquiry_dtl.enquiry_id -> proc_enquiry
--    Enforces header/detail referential integrity at the DB level to
--    match the ORM relationship.
-- ═══════════════════════════════════════════════════════════════════

ALTER TABLE proc_enquiry_dtl
    ADD CONSTRAINT fk_enq_dtl_enquiry
    FOREIGN KEY (enquiry_id) REFERENCES proc_enquiry(enquiry_id);


-- ───────────────────────────────────────────────────────────────────
-- ROLLBACK (manual):
--   ALTER TABLE proc_enquiry_dtl DROP FOREIGN KEY fk_enq_dtl_enquiry;
--   ALTER TABLE proc_enquiry_supplier DROP FOREIGN KEY fk_enq_supp_branch;
--   ALTER TABLE proc_enquiry DROP INDEX uk_enq_branch_fy;
-- ───────────────────────────────────────────────────────────────────
