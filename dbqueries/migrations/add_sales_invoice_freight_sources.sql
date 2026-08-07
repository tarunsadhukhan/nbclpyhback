-- =============================================================================
-- MIGRATION: Add sales_invoice_freight_source junction (multi-source freight)
-- =============================================================================
-- Run this script PER TENANT DATABASE (e.g. dev3, sls, etc.)
-- Depends on: add_sales_invoice_freight.sql (which creates sales_invoice_freight).
--
-- What this does:
-- 1. Creates the sales_invoice_freight_source junction table. A single freight
--    invoice (type 7) can now reference N source Govt Sacking (type 3)
--    invoices. The existing sales_invoice_freight.source_invoice_id column is
--    preserved as the "primary" source for back-compat (set to the first
--    selected source); the junction holds the full set including the primary.
-- 2. Backfills the junction from every existing sales_invoice_freight row so
--    legacy single-source invoices read back consistently through the new
--    junction-based lookup.
--
-- Idempotent: re-running this script is a no-op.
--
-- ROLLBACK instructions are at the bottom.
-- =============================================================================

-- =============================================================================
-- Step 1: Create sales_invoice_freight_source junction
-- =============================================================================
CREATE TABLE IF NOT EXISTS sales_invoice_freight_source (
    sales_invoice_freight_source_id INT AUTO_INCREMENT PRIMARY KEY,
    sales_invoice_freight_id INT NOT NULL,
    source_invoice_id BIGINT NOT NULL,
    bales_qty DECIMAL(18,3) NULL,
    created_date_time DATETIME NULL,
    INDEX idx_sifs_freight (sales_invoice_freight_id),
    INDEX idx_sifs_source (source_invoice_id),
    UNIQUE KEY uq_sifs_freight_source (sales_invoice_freight_id, source_invoice_id),
    CONSTRAINT fk_sifs_freight FOREIGN KEY (sales_invoice_freight_id)
        REFERENCES sales_invoice_freight(sales_invoice_freight_id),
    CONSTRAINT fk_sifs_source FOREIGN KEY (source_invoice_id)
        REFERENCES sales_invoice(invoice_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- =============================================================================
-- Step 2: Backfill from existing single-source rows
-- =============================================================================
INSERT INTO sales_invoice_freight_source (sales_invoice_freight_id, source_invoice_id, created_date_time)
SELECT sif.sales_invoice_freight_id, sif.source_invoice_id, sif.updated_date_time
FROM sales_invoice_freight sif
LEFT JOIN sales_invoice_freight_source sifs
    ON sifs.sales_invoice_freight_id = sif.sales_invoice_freight_id
   AND sifs.source_invoice_id = sif.source_invoice_id
WHERE sifs.sales_invoice_freight_source_id IS NULL;

-- =============================================================================
-- ROLLBACK (if needed):
-- DROP TABLE IF EXISTS sales_invoice_freight_source;
-- =============================================================================
