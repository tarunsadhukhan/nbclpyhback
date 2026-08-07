-- Add supplier_branch_id to proc_inward for GST state determination
-- The bill_branch_id and ship_branch_id columns already exist but are never populated.
-- This migration adds supplier_branch_id and backfills all three from the linked PO.

ALTER TABLE proc_inward
    ADD COLUMN supplier_branch_id INT NULL AFTER supplier_id;

-- Backfill supplier_branch_id, bill_branch_id, ship_branch_id from linked PO
-- Uses the first active line item's PO to find the branch IDs.
UPDATE proc_inward pi
JOIN (
    SELECT
        pid.inward_id,
        pp.supplier_branch_id,
        pp.billing_branch_id,
        pp.shipping_branch_id
    FROM proc_inward_dtl pid
    JOIN proc_po_dtl ppd ON ppd.po_dtl_id = pid.po_dtl_id
    JOIN proc_po pp ON pp.po_id = ppd.po_id
    WHERE pid.active = 1
    GROUP BY pid.inward_id
) po_info ON po_info.inward_id = pi.inward_id
SET
    pi.supplier_branch_id = COALESCE(pi.supplier_branch_id, po_info.supplier_branch_id),
    pi.bill_branch_id = COALESCE(pi.bill_branch_id, po_info.billing_branch_id),
    pi.ship_branch_id = COALESCE(pi.ship_branch_id, po_info.shipping_branch_id);

-- Rollback:
-- ALTER TABLE proc_inward DROP COLUMN supplier_branch_id;
