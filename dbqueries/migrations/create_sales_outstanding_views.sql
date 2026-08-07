-- Migration: Create sales outstanding/fulfillment tracking views
-- Prerequisite: Run add_sales_invoice_dtl_indexes.sql first
--
-- Three views:
--   1. vw_sales_order_outstanding  — per SO detail line, balance to deliver & invoice
--   2. vw_sales_do_outstanding     — per DO detail line, balance to invoice
--   3. vw_sales_fulfillment_summary — aggregate by co/branch/party/item
--
-- Consumed statuses: 3 (Approved), 5 (Closed), 20 (Pending Approval)
-- Source rows: only approved/closed headers (status 3, 5) with active detail lines
--
-- Rollback:
--   DROP VIEW IF EXISTS vw_sales_fulfillment_summary;
--   DROP VIEW IF EXISTS vw_sales_do_outstanding;
--   DROP VIEW IF EXISTS vw_sales_order_outstanding;


-- =============================================================================
-- VIEW 1: Sales Order Outstanding (per detail line)
-- =============================================================================
CREATE OR REPLACE VIEW vw_sales_order_outstanding AS
SELECT
    sod.sales_order_dtl_id,
    so.sales_order_id,
    so.sales_no,
    so.sales_order_date,
    so.branch_id,
    bm.co_id,
    so.party_id,
    so.invoice_type,
    so.status_id,
    sod.item_id,
    im.item_code,
    im.item_name,
    sod.uom_id,
    um.uom_name,
    sod.rate,

    -- Source quantity
    COALESCE(sod.quantity, 0) AS so_qty,

    -- DO consumption: sum of DO detail qty where DO header is approved/closed/pending
    COALESCE(do_agg.do_consumed_qty, 0) AS do_consumed_qty,

    -- Invoice consumption via DO path (SO -> DO -> Invoice)
    COALESCE(inv_via_do.inv_via_do_qty, 0) AS inv_via_do_qty,

    -- Invoice consumption via direct path (SO -> Invoice, no DO)
    COALESCE(inv_direct.inv_direct_qty, 0) AS inv_direct_qty,

    -- Total invoice consumption (both paths)
    (COALESCE(inv_via_do.inv_via_do_qty, 0) + COALESCE(inv_direct.inv_direct_qty, 0)) AS invoice_consumed_qty,

    -- Balance to deliver = so_qty - do_consumed_qty
    GREATEST(COALESCE(sod.quantity, 0) - COALESCE(do_agg.do_consumed_qty, 0), 0) AS bal_do_qty,

    -- Balance to invoice = so_qty - total_invoice_consumed_qty
    GREATEST(
        COALESCE(sod.quantity, 0)
        - COALESCE(inv_via_do.inv_via_do_qty, 0)
        - COALESCE(inv_direct.inv_direct_qty, 0),
        0
    ) AS bal_invoice_qty

FROM sales_order so
INNER JOIN sales_order_dtl sod
    ON sod.sales_order_id = so.sales_order_id
    AND sod.active = 1
LEFT JOIN branch_mst bm ON bm.branch_id = so.branch_id
LEFT JOIN item_mst im ON im.item_id = sod.item_id
LEFT JOIN uom_mst um ON um.uom_id = sod.uom_id

-- Subquery: DO consumption per SO detail line
LEFT JOIN (
    SELECT
        sdod.sales_order_dtl_id,
        SUM(COALESCE(sdod.quantity, 0)) AS do_consumed_qty
    FROM sales_delivery_order_dtl sdod
    INNER JOIN sales_delivery_order sdo
        ON sdo.sales_delivery_order_id = sdod.sales_delivery_order_id
    WHERE sdod.active = 1
      AND sdo.active = 1
      AND sdo.status_id IN (3, 5, 20)
    GROUP BY sdod.sales_order_dtl_id
) do_agg ON do_agg.sales_order_dtl_id = sod.sales_order_dtl_id

-- Subquery: Invoice consumption via DO path
LEFT JOIN (
    SELECT
        sdod.sales_order_dtl_id,
        SUM(COALESCE(sid.quantity, 0)) AS inv_via_do_qty
    FROM sales_invoice_dtl sid
    INNER JOIN sales_delivery_order_dtl sdod
        ON sdod.sales_delivery_order_dtl_id = sid.delivery_order_dtl_id
        AND sdod.active = 1
    INNER JOIN sales_invoice si
        ON si.invoice_id = sid.invoice_id
    WHERE si.active = 1
      AND si.status_id IN (3, 5, 20)
    GROUP BY sdod.sales_order_dtl_id
) inv_via_do ON inv_via_do.sales_order_dtl_id = sod.sales_order_dtl_id

-- Subquery: Invoice consumption via direct path (no DO)
LEFT JOIN (
    SELECT
        sid.sales_order_dtl_id,
        SUM(COALESCE(sid.quantity, 0)) AS inv_direct_qty
    FROM sales_invoice_dtl sid
    INNER JOIN sales_invoice si
        ON si.invoice_id = sid.invoice_id
    WHERE sid.delivery_order_dtl_id IS NULL
      AND sid.sales_order_dtl_id IS NOT NULL
      AND si.active = 1
      AND si.status_id IN (3, 5, 20)
    GROUP BY sid.sales_order_dtl_id
) inv_direct ON inv_direct.sales_order_dtl_id = sod.sales_order_dtl_id

WHERE so.active = 1
  AND so.status_id IN (3, 5);


-- =============================================================================
-- VIEW 2: Delivery Order Outstanding (per detail line)
-- =============================================================================
CREATE OR REPLACE VIEW vw_sales_do_outstanding AS
SELECT
    sdod.sales_delivery_order_dtl_id,
    sdo.sales_delivery_order_id,
    sdo.delivery_order_no,
    sdo.delivery_order_date,
    sdod.sales_order_dtl_id,
    sdo.sales_order_id,
    sdo.branch_id,
    bm.co_id,
    sdo.party_id,
    sdo.invoice_type,
    sdo.status_id,
    sdod.item_id,
    im.item_code,
    im.item_name,
    sdod.uom_id,
    um.uom_name,
    sdod.rate,

    -- Source quantity
    COALESCE(sdod.quantity, 0) AS do_qty,

    -- Invoice consumption against this DO line
    COALESCE(inv_agg.invoice_consumed_qty, 0) AS invoice_consumed_qty,

    -- Balance = do_qty - invoice_consumed
    GREATEST(COALESCE(sdod.quantity, 0) - COALESCE(inv_agg.invoice_consumed_qty, 0), 0) AS bal_do_qty

FROM sales_delivery_order sdo
INNER JOIN sales_delivery_order_dtl sdod
    ON sdod.sales_delivery_order_id = sdo.sales_delivery_order_id
    AND sdod.active = 1
LEFT JOIN branch_mst bm ON bm.branch_id = sdo.branch_id
LEFT JOIN item_mst im ON im.item_id = sdod.item_id
LEFT JOIN uom_mst um ON um.uom_id = sdod.uom_id

-- Subquery: invoice qty consumed against each DO detail line
LEFT JOIN (
    SELECT
        sid.delivery_order_dtl_id,
        SUM(COALESCE(sid.quantity, 0)) AS invoice_consumed_qty
    FROM sales_invoice_dtl sid
    INNER JOIN sales_invoice si
        ON si.invoice_id = sid.invoice_id
    WHERE sid.delivery_order_dtl_id IS NOT NULL
      AND si.active = 1
      AND si.status_id IN (3, 5, 20)
    GROUP BY sid.delivery_order_dtl_id
) inv_agg ON inv_agg.delivery_order_dtl_id = sdod.sales_delivery_order_dtl_id

WHERE sdo.active = 1
  AND sdo.status_id IN (3, 5);


-- =============================================================================
-- VIEW 3: Sales Fulfillment Summary (aggregate by co/branch/party/item)
-- =============================================================================
CREATE OR REPLACE VIEW vw_sales_fulfillment_summary AS
SELECT
    vso.co_id,
    vso.branch_id,
    vso.party_id,
    vso.item_id,
    vso.uom_id,

    -- Totals
    SUM(vso.so_qty) AS total_so_qty,
    SUM(vso.do_consumed_qty) AS total_do_qty,
    SUM(vso.invoice_consumed_qty) AS total_invoiced_qty,

    -- Balances
    SUM(vso.bal_do_qty) AS bal_so_to_deliver,
    SUM(vso.bal_invoice_qty) AS bal_so_to_invoice

FROM vw_sales_order_outstanding vso
GROUP BY vso.co_id, vso.branch_id, vso.party_id, vso.item_id, vso.uom_id;
