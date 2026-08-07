-- Migration: add_weaving_dayslice_indexes.sql
-- Purpose: indexes supporting the day-slice weaving queries in
-- src/juteProduction/weaving_query.py (weaving_day_slice_sql + two-probe
-- open_jugar + flattened pick-SQC probes). Fixes the 504 caused by endpoints
-- reading the full-history vw_weaving_daily on large tenants.
--
-- EXECUTOR CONSTRAINT: the run-migration pymysql runner splits this file on
-- semicolons and skips any chunk whose stripped text starts with a comment
-- dash pair. Therefore NO comment line may contain a semicolon, and this
-- header block is terminated by the lone semicolon on its own line below so
-- the header forms its own skipped chunk and each ALTER starts a fresh chunk.
-- Verify post-apply with: SHOW INDEX FROM jute_prod_weaving_daily
--
-- PRE-EXISTING INDEX NOTES (checked against create_weaving_tables.sql,
-- create_jute_prod_stoppage_hours.sql, 2026-06-23_weaving_pick_sqc.sql):
--   * jute_sqc_weaving_pick already has idx_jswp_co_quality_date on
--     (co_id, weaving_quality_id, entry_date, active) -- the planned
--     idx_pick_day (co_id, weaving_quality_id, entry_date) is a strict prefix
--     of it, so that statement is SKIPPED (no idx_pick_day created)
--   * jute_prod_weaving_daily already has idx_wd_key
--     (co_id, tran_date, spell_id, machine_id, weaving_quality_id) -- its
--     (co_id, tran_date) prefix serves the day scan, so the originally
--     planned idx_wd_day is SKIPPED as redundant (reviewer finding)
--   * jute_prod_stoppage_hours already has idx_stoppage_machine_date_spell
--     (machine_id, tran_date, spell_id) -- near-duplicate but not same-column
--     (no co_id lead, no active), idx_stop_probe is still added
--
-- ROLLBACK (as comments):
-- ALTER TABLE jute_prod_weaving_daily DROP INDEX idx_wd_jugar_chain
-- ALTER TABLE jute_prod_stoppage_hours DROP INDEX idx_stop_probe
;

ALTER TABLE jute_prod_weaving_daily
    ADD INDEX idx_wd_jugar_chain (co_id, machine_id, weaving_quality_id, tran_date, weaving_daily_id),
    ALGORITHM=INPLACE, LOCK=NONE;

ALTER TABLE jute_prod_stoppage_hours
    ADD INDEX idx_stop_probe (co_id, machine_id, tran_date, spell_id, active),
    ALGORITHM=INPLACE, LOCK=NONE;

-- idx_pick_day on jute_sqc_weaving_pick intentionally omitted: covered by the
-- pre-existing idx_jswp_co_quality_date (co_id, weaving_quality_id, entry_date, active)
-- idx_wd_day intentionally omitted: covered by idx_wd_key (co_id, tran_date, ...) prefix
