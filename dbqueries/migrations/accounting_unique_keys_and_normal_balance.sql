-- =============================================================================
-- Accounting hardening: structural unique keys + normal_balance backfill
-- Target: tenant DBs (run on dev3 first). Module barely used; verify no
-- duplicates before applying (see pre-check below).
--
-- 1. acc_voucher: UNIQUE (co_id, acc_financial_year_id, voucher_no).
--    Numbering resets per company + FY ({prefix}-00001), so voucher_no alone
--    is NOT unique across FYs. voucher_no is nullable; MySQL permits multiple
--    NULLs in a unique index, so unnumbered drafts are unaffected.
-- 2. acc_voucher_type: UNIQUE (co_id, type_category) and UNIQUE (co_id, type_name).
--    Duplicate checks were app-level only; concurrent POSTs could double-insert.
-- 3. acc_ledger_group: backfill normal_balance from nature where NULL
--    (A/E assets+expenses carry debit balances, L/I liabilities+income credit).
--    Idempotent; new rows are derived in create_ledger_group going forward.
--
-- Pre-check (must return 0 rows before applying):
--   SELECT co_id, acc_financial_year_id, voucher_no, COUNT(*) c FROM acc_voucher
--     WHERE voucher_no IS NOT NULL GROUP BY 1,2,3 HAVING c > 1;
--   SELECT co_id, type_category, COUNT(*) c FROM acc_voucher_type
--     GROUP BY 1,2 HAVING c > 1;
--   SELECT co_id, type_name, COUNT(*) c FROM acc_voucher_type
--     GROUP BY 1,2 HAVING c > 1;
--
-- Rollback:
--   ALTER TABLE acc_voucher DROP INDEX uk_voucher_co_fy_no;
--   ALTER TABLE acc_voucher_type DROP INDEX uk_vtype_co_category;
--   ALTER TABLE acc_voucher_type DROP INDEX uk_vtype_co_name;
--   (normal_balance backfill is data-only; no rollback needed)
-- =============================================================================

ALTER TABLE acc_voucher
    ADD UNIQUE KEY uk_voucher_co_fy_no (co_id, acc_financial_year_id, voucher_no);

ALTER TABLE acc_voucher_type
    ADD UNIQUE KEY uk_vtype_co_category (co_id, type_category),
    ADD UNIQUE KEY uk_vtype_co_name (co_id, type_name);

UPDATE acc_ledger_group
SET normal_balance = CASE
    WHEN nature IN ('A', 'E') THEN 'D'
    WHEN nature IN ('L', 'I') THEN 'C'
END
WHERE normal_balance IS NULL
  AND nature IN ('A', 'E', 'L', 'I');
