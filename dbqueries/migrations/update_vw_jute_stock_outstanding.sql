-- Migration: Update vw_jute_stock_outstanding view to include gate_entry_no and warehouse_name
-- Purpose: Add gate entry number and warehouse name information to stock outstanding view
-- Date: 2026-02-08
-- Run this migration in your tenant database

-- Drop existing view if it exists
DROP VIEW IF EXISTS vw_jute_stock_outstanding;

-- Create/Recreate view with all required columns including the new ones
CREATE VIEW vw_jute_stock_outstanding AS
SELECT
    jml.jute_mr_li_id,
    jm.jute_gate_entry_no,
    COALESCE(wm.warehouse_name, 'Unknown') AS warehouse_name,
    jm.branch_id,
    jm.branch_mr_no,
    jml.actual_quality,
    jml.actual_qty,
    jml.actual_weight,
    jm.unit_conversion,
    (jml.actual_qty - IFNULL(iss.issqty, 0)) AS bal_qty,
    ROUND((jml.actual_weight - IFNULL(iss.isswt, 0)), 3) AS bal_weight,
    jml.accepted_weight,
    ROUND((jml.accepted_weight / jml.actual_qty) * IFNULL(iss.issqty, 0), 3) AS bal_accepted_weight,
    jml.rate,
    jml.actual_rate
FROM jute_mr jm
JOIN jute_mr_li jml ON jm.jute_mr_id = jml.jute_mr_id
LEFT JOIN warehouse_mst wm ON wm.warehouse_id = jml.warehouse_id
LEFT JOIN (
    SELECT ji.jute_mr_li_id, SUM(ji.quantity) AS issqty, SUM(ji.weight) AS isswt
    FROM jute_issue ji
    GROUP BY ji.jute_mr_li_id
) iss ON iss.jute_mr_li_id = jml.jute_mr_li_id;
