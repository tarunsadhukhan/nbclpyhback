-- Migration: repoint vw_winding_daily_reconciled after yarn_quality_id -> item_id rename.
--
-- jute_prod_winding_doff.yarn_quality_id was renamed to item_id (the yarn item identity).
-- This view sourced + exposed that column, so it is recreated to read/expose `item_id`.
-- Consumers (vw_spinning_planning_grid, get_winding_total_query) now read v.item_id.
-- Run AFTER rename_yarn_quality_id_to_item_id.sql. sls lacks jute_prod_winding_doff — skip there.

DROP VIEW IF EXISTS vw_winding_daily_reconciled;

-- DOCTRINE: views may format, never accumulate — no window functions, no GROUP BY
-- over full history, no view-on-view in any request path. vw_winding_daily_reconciled
-- is REFERENCE SEMANTICS + DIFF ORACLE ONLY: never query it unfiltered on large
-- tenants (it GROUPs the full jute_prod_winding_doff history); request-path readers
-- must use day-scoped queries against the base tables.
CREATE VIEW vw_winding_daily_reconciled AS
SELECT
    bm.co_id AS co_id,
    d.branch_id AS branch_id,
    wd.tran_date AS tran_date,
    wd.spell_id AS spell_id,
    wd.machine_id AS machine_id,
    wd.item_id AS item_id,
    (
        SUM(wd.production_qty)
        - COALESCE((
            SELECT MAX(jo.weight)
            FROM jute_prod_winding_jugar jo
            WHERE jo.tran_date = wd.tran_date
              AND jo.spell_id = wd.spell_id
              AND jo.machine_id = wd.machine_id
              AND jo.open_close = 'O'
              AND jo.active = 1
        ), 0)
        + COALESCE((
            SELECT MAX(jc.weight)
            FROM jute_prod_winding_jugar jc
            WHERE jc.tran_date = wd.tran_date
              AND jc.spell_id = wd.spell_id
              AND jc.machine_id = wd.machine_id
              AND jc.open_close = 'C'
              AND jc.active = 1
        ), 0)
    ) AS reconciled_qty
FROM jute_prod_winding_doff wd
INNER JOIN machine_mst m ON m.machine_id = wd.machine_id
INNER JOIN dept_mst d ON d.dept_id = m.dept_id
INNER JOIN branch_mst bm ON bm.branch_id = d.branch_id
WHERE wd.active = 1
GROUP BY bm.co_id, d.branch_id, wd.tran_date, wd.spell_id, wd.machine_id, wd.item_id;

-- =============================================================================
-- ROLLBACK: restore from create_vw_winding_daily_reconciled.sql (yarn_quality_id form).
-- DROP VIEW IF EXISTS vw_winding_daily_reconciled;
-- =============================================================================
