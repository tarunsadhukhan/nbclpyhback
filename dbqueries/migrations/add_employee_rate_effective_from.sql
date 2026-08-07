-- Migration: add_employee_rate_effective_from.sql
-- Phase 1c join-key hygiene (weaving wages groundwork): employee_rate_table has
-- no effective-from date, so a rate edit silently rewrites PAST wage math. Add
-- effective_from DATE and resolve rates LAST-DATE, the exact pattern of
-- jute_prod_weaving_target_map (MAX(effective_from) <= :on_date per eb_id, see
-- src/juteProduction/weaving_query.py resolve_weaving_target_value_query).
--
-- Existing rows are backfilled to the sentinel 2000-01-01 so every historical
-- date keeps resolving to the current rate (behavior unchanged until a second,
-- newer-dated row is inserted for an employee). New rate revisions should be
-- INSERTED with their real effective_from, never UPDATEd in place.
--
-- No app writer exists for this table today (read-only in the codebase, single
-- reader: src/mobileapp/src/dashboard/attendance_dashboard.py) - readers keep
-- working unchanged until the wage engine starts resolving by date.
--
-- IDEMPOTENT backfill: filters effective_from IS NULL.
--
-- EXECUTOR CONSTRAINT: no semicolon in comment prose, header terminated by the
-- lone semicolon below.
--
-- ROLLBACK (as comments):
-- ALTER TABLE employee_rate_table DROP COLUMN effective_from
;

ALTER TABLE employee_rate_table
    ADD COLUMN effective_from DATE NULL DEFAULT NULL
        COMMENT 'rate valid from this date - resolve LAST-DATE like jute_prod_weaving_target_map, sentinel 2000-01-01 on backfilled rows';

UPDATE employee_rate_table
SET effective_from = '2000-01-01'
WHERE effective_from IS NULL
