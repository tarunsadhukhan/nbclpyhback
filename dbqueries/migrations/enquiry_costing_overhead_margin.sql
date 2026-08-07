-- Enquiry costing: overhead% + margin% on the enquiry line. Base cost excludes overhead.
-- Date: 2026-07-16 | Run against: TENANT database (dev3 first, then sls + others BEFORE code deploy)

-- 1) Per-line overhead% + margin% (set by the costing/enquiry person at COSTING_REVIEW).
ALTER TABLE sales_enquiry_dtl
    ADD COLUMN overhead_pct DOUBLE NULL AFTER confirmed_cost_per_unit,
    ADD COLUMN margin_pct   DOUBLE NULL AFTER overhead_pct;

-- 2) Cost-sheet base excludes overhead: total_cost = material + conversion only.
CREATE OR REPLACE VIEW vw_bom_cost_summary AS
SELECT
    bh.bom_hdr_id,
    bh.item_id,
    im.item_code,
    im.item_name,
    bh.bom_version,
    bh.version_label,
    bh.status_id,
    bce.co_id,
    bce.effective_date,

    -- Material cost subtotal (leaf entries only)
    SUM(CASE WHEN ce.element_type = 'material' THEN bce.amount ELSE 0 END) AS material_cost,

    -- Conversion cost subtotal
    SUM(CASE WHEN ce.element_type = 'conversion' THEN bce.amount ELSE 0 END) AS conversion_cost,

    -- Overhead cost subtotal
    SUM(CASE WHEN ce.element_type = 'overhead' THEN bce.amount ELSE 0 END) AS overhead_cost,

    -- Base cost total: material + conversion only (overhead applied later as a % on top)
    SUM(CASE WHEN ce.element_type IN ('material','conversion') THEN bce.amount ELSE 0 END) AS total_cost,

    -- Count of cost entries
    COUNT(*) AS entry_count

FROM bom_cost_entry bce
INNER JOIN cost_element_mst ce
    ON bce.cost_element_id = ce.cost_element_id
INNER JOIN item_bom_hdr_mst bh
    ON bce.bom_hdr_id = bh.bom_hdr_id
INNER JOIN item_mst im
    ON bh.item_id = im.item_id
WHERE bce.active = 1
  AND ce.active = 1
  AND bh.active = 1
GROUP BY
    bh.bom_hdr_id,
    bh.item_id,
    im.item_code,
    im.item_name,
    bh.bom_version,
    bh.version_label,
    bh.status_id,
    bce.co_id,
    bce.effective_date;

-- ROLLBACK:
-- ALTER TABLE sales_enquiry_dtl DROP COLUMN margin_pct, DROP COLUMN overhead_pct;
-- (restore vw_bom_cost_summary from create_bom_costing_tables.sql: total_cost = SUM(bce.amount))
