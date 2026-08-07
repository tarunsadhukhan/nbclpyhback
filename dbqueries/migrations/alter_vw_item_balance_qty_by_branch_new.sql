-- Migration: Add max/min indent/PO computed columns to vw_item_balance_qty_by_branch_new
-- Date: 2026-02-24
-- 
-- This migration adds 4 computed columns to the aggregate validation view:
--   max_indent_qty, min_indent_qty, max_po_qty, min_po_qty
--
-- Sentinel values:
--   -2 = Warning: open outstanding exists (open indent for indent cols, open PO for PO cols)
--   -1 = No min/max configured — user may enter any quantity
--   >= 0 = Computed validation limit
--
-- INSTRUCTIONS:
-- 1. Run: SHOW CREATE VIEW vw_item_balance_qty_by_branch_new\G
-- 2. Copy the existing SELECT statement
-- 3. Add the 4 column expressions below to the SELECT clause
-- 4. Run the full CREATE OR REPLACE VIEW statement
--
-- COLUMNS TO ADD (paste these at the end of the existing SELECT, before FROM):
-- ─────────────────────────────────────────────────────────────────────

-- max_indent_qty: Maximum indent quantity allowed for this branch+item
-- Sentinel -2 if open indent outstanding > 0
-- Sentinel -1 if no maxqty configured
-- Otherwise: CEIL((maxqty - cur_stock - bal_qty_ind_to_validate - regular_po_outstanding) / min_order_qty) * min_order_qty
,
CASE
    WHEN COALESCE(open_bal_Ind_tot_qty, 0) > 0 THEN -2
    WHEN COALESCE(maxqty, 0) = 0 THEN -1
    WHEN COALESCE(min_order_qty, 0) = 0 THEN
        GREATEST(
            COALESCE(maxqty, 0)
            - COALESCE(cur_stock, 0)
            - COALESCE(bal_qty_ind_to_validate, 0)
            - (COALESCE(bal_tot_po_qty, 0) - COALESCE(open_bal_tot_po_qty, 0)),
            0
        )
    ELSE
        GREATEST(
            CEILING(
                GREATEST(
                    COALESCE(maxqty, 0)
                    - COALESCE(cur_stock, 0)
                    - COALESCE(bal_qty_ind_to_validate, 0)
                    - (COALESCE(bal_tot_po_qty, 0) - COALESCE(open_bal_tot_po_qty, 0)),
                    0
                ) / COALESCE(min_order_qty, 1)
            ) * COALESCE(min_order_qty, 1),
            0
        )
END AS max_indent_qty

-- min_indent_qty: Minimum indent quantity for this branch+item
-- Sentinel -2 if open indent outstanding > 0
-- Sentinel -1 if no maxqty configured
-- Otherwise: minqty (reorder point from item_minmax_mst)
,
CASE
    WHEN COALESCE(open_bal_Ind_tot_qty, 0) > 0 THEN -2
    WHEN COALESCE(maxqty, 0) = 0 THEN -1
    ELSE COALESCE(minqty, 0)
END AS min_indent_qty

-- max_po_qty: Maximum PO quantity allowed for this branch+item
-- Sentinel -2 if open PO outstanding > 0
-- Sentinel -1 if no maxqty configured
-- Otherwise: CEIL((maxqty - cur_stock - bal_qty_ind_to_validate - regular_po_outstanding) / min_order_qty) * min_order_qty
,
CASE
    WHEN COALESCE(open_bal_tot_po_qty, 0) > 0 THEN -2
    WHEN COALESCE(maxqty, 0) = 0 THEN -1
    WHEN COALESCE(min_order_qty, 0) = 0 THEN
        GREATEST(
            COALESCE(maxqty, 0)
            - COALESCE(cur_stock, 0)
            - COALESCE(bal_qty_ind_to_validate, 0)
            - (COALESCE(bal_tot_po_qty, 0) - COALESCE(open_bal_tot_po_qty, 0)),
            0
        )
    ELSE
        GREATEST(
            CEILING(
                GREATEST(
                    COALESCE(maxqty, 0)
                    - COALESCE(cur_stock, 0)
                    - COALESCE(bal_qty_ind_to_validate, 0)
                    - (COALESCE(bal_tot_po_qty, 0) - COALESCE(open_bal_tot_po_qty, 0)),
                    0
                ) / COALESCE(min_order_qty, 1)
            ) * COALESCE(min_order_qty, 1),
            0
        )
END AS max_po_qty

-- min_po_qty: Minimum PO quantity for this branch+item
-- Sentinel -2 if open PO outstanding > 0
-- Sentinel -1 if no maxqty configured
-- Otherwise: minqty (reorder point from item_minmax_mst)
,
CASE
    WHEN COALESCE(open_bal_tot_po_qty, 0) > 0 THEN -2
    WHEN COALESCE(maxqty, 0) = 0 THEN -1
    ELSE COALESCE(minqty, 0)
END AS min_po_qty

-- ─────────────────────────────────────────────────────────────────────
-- VERIFICATION QUERIES:
-- 
-- 1. Item with min/max configured and no open outstanding:
--    SELECT * FROM vw_item_balance_qty_by_branch_new WHERE item_id = 269879;
--    Expected: max_indent_qty >= 0, min_indent_qty >= 0
--
-- 2. Item with open indent outstanding > 0:
--    SELECT * FROM vw_item_balance_qty_by_branch_new WHERE open_bal_Ind_tot_qty > 0 LIMIT 5;
--    Expected: max_indent_qty = -2, min_indent_qty = -2
--
-- 3. Item with no min/max configured:
--    SELECT * FROM vw_item_balance_qty_by_branch_new WHERE maxqty = 0 OR maxqty IS NULL LIMIT 5;
--    Expected: max_indent_qty = -1, min_indent_qty = -1
--
-- ROLLBACK:
-- Remove the 4 columns by recreating the view without them.
-- Use SHOW CREATE VIEW to get the original definition before applying this migration.
