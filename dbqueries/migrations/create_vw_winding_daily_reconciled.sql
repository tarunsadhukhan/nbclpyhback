-- Migration: vw_winding_daily_reconciled — daily reconciled winding production (KG)
-- Date: 2026-06-15
-- Applies to: tenant databases dev3 (QA) [and sls when promoted]
-- Requires: MySQL 8. dev3 = 8.0.42 (verified).
--
-- Reproduces, in pure SQL, the legacy winding daily reconciliation (winding-production-design.md
-- §4.2 / winding_rules.py): per machine/spell, reconciled production in KG is the doff net total
-- corrected for the spindle carryover captured by the jugar opening/closing balance:
--
--     reconciled_qty = SUM(production_qty) - opening_jugar + closing_jugar
--
-- where, per (tran_date, spell_id, machine_id):
--     opening_jugar = MAX(weight WHERE open_close = 'O')
--     closing_jugar = MAX(weight WHERE open_close = 'C')
--
-- Subtracting the opening leftover and adding the closing leftover converts "weight doffed this
-- shift" into "weight actually produced this shift" net of yarn started but not yet doffed. The
-- bundle factor (BUNDLE_KG = 14) is kept as a documented constant only and is NOT applied here:
-- reconciled production is reported in KG (no per-quality target_prod / UOM master in vowerp3).
--
-- Grain: one row per (co_id, tran_date, spell_id, machine_id, yarn_quality_id). Quality is the doff
-- row's yarn_quality_id. co_id is derived machine_mst -> dept_mst -> branch_mst.co_id (mirroring
-- vw_spinning_planning_grid; the doff/jugar tables are branch-scoped). The jugar open/close maxima
-- are pulled via correlated subqueries keyed on the doff group's date/spell/machine, so a machine
-- with no jugar rows simply reconciles to its doff net total (COALESCE -> 0).
--
-- This view is the authoritative read-time source for winding production: it replaces the retired
-- manual aggregate jute_prod_winding_prod, and is read by vw_spinning_planning_grid and by the
-- spinning grid's get_winding_total_query (aggregated up to the shift bucket).

DROP VIEW IF EXISTS vw_winding_daily_reconciled;

CREATE VIEW vw_winding_daily_reconciled AS
SELECT
    bm.co_id AS co_id,
    d.branch_id AS branch_id,
    wd.tran_date AS tran_date,
    wd.spell_id AS spell_id,
    wd.machine_id AS machine_id,
    wd.yarn_quality_id AS yarn_quality_id,
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
GROUP BY bm.co_id, d.branch_id, wd.tran_date, wd.spell_id, wd.machine_id, wd.yarn_quality_id;

-- =============================================================================
-- ROLLBACK:
-- DROP VIEW IF EXISTS vw_winding_daily_reconciled;
-- =============================================================================
