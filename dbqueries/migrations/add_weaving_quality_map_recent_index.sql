-- Fix: quality_map_get 500 (Lost connection to MySQL server during query) on large tenants.
--
-- get_weaving_quality_map_query runs FOUR correlated subqueries per Loom (the prev_quality_*
-- carry-forward), each:
--     WHERE p.machine_id = ? AND p.co_id = ? AND p.active = 1 AND p.weaving_quality_id IS NOT NULL
--       AND NOT (p.tran_date = ? AND p.spell_id = ?)
--     ORDER BY p.tran_date DESC, p.weaving_quality_map_id DESC
--     LIMIT 1
-- The only existing index idx_wqm_key (co_id, tran_date, spell_id, machine_id) cannot serve this:
-- it refs on co_id alone (~half the table) then filesorts. On sls (2.26M rows, 1304 looms) each
-- subquery scanned ~1.1M rows x filesort x 4 x 1304 looms -> query never returns -> connection drop.
--
-- This index gives the subquery an equality prefix (machine_id, co_id, active) then tran_date +
-- weaving_quality_map_id in the ORDER BY direction: seek + short backward scan, no filesort.
-- InnoDB online DDL (INPLACE) -- no table rewrite, non-blocking.

CREATE INDEX idx_wqm_machine_recent
    ON jute_prod_weaving_quality_map (machine_id, co_id, active, tran_date, weaving_quality_map_id);

-- Rollback:
-- DROP INDEX idx_wqm_machine_recent ON jute_prod_weaving_quality_map;
