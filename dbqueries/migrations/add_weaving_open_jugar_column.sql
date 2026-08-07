-- Migration: add_weaving_open_jugar_column.sql
-- Phase 1b of the weaving derived-data rework: persist the open_jugar
-- carry-forward on jute_prod_weaving_daily instead of re-deriving it per read
-- via the jugar-chain probes. The weaving_entry writers now resolve it at
-- write time and repair the single chain successor in the same transaction.
-- The read path (weaving_day_slice_sql / get_weaving_entry_inputs_query)
-- reads COALESCE(open_jugar, 0) directly - no chain probe per row.
--
-- Run backfill_weaving_open_jugar.sql IMMEDIATELY AFTER this (and after any
-- bulk import that bypasses the app writers, e.g. sls raw-SQL imports).
-- Weekly drift check: dbqueries/check_weaving_open_jugar_parity.sql
--
-- EXECUTOR CONSTRAINT: the run-migration pymysql runner splits this file on
-- semicolons and skips chunks whose stripped text starts with a comment dash
-- pair, so no comment line may contain a semicolon and this header block is
-- terminated by the lone semicolon on its own line below.
--
-- ROLLBACK (as comments):
-- ALTER TABLE jute_prod_weaving_daily DROP COLUMN open_jugar
;

ALTER TABLE jute_prod_weaving_daily
    ADD COLUMN open_jugar DECIMAL(10,3) NULL DEFAULT NULL
        COMMENT 'stored jugar-chain carry-forward - derived data maintained by weaving writers and backfill_weaving_open_jugar.sql'
    AFTER less_production
