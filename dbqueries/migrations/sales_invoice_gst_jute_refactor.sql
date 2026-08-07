-- Migration: Sales Invoice GST separation + Jute table replacement
-- Date: 2026-03-05
-- Description:
--   1. Create sales_invoice_dtl_gst table (GST per line item, replacing inline columns)
--   2. Create sales_invoice_jute table (new header-level jute data, replacing sale_invoice_jute)
--   3. Create sales_invoice_jute_dtl table (per-line-item jute detail data)
--   4. Migrate existing inline GST data to new table
--   5. Migrate existing sale_invoice_jute data to new table

-- =============================================================================
-- 1. sales_invoice_dtl_gst
-- =============================================================================

CREATE TABLE IF NOT EXISTS sales_invoice_dtl_gst (
    sales_invoice_dtl_gst_id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    invoice_line_item_id INT NULL,
    tax_percentage DECIMAL(5,2) NULL,
    cgst_amount DECIMAL(10,2) NULL,
    sgst_amount DECIMAL(10,2) NULL,
    igst_amount DECIMAL(10,2) NULL,
    cgst_percentage DECIMAL(5,2) NULL,
    sgst_percentage DECIMAL(5,2) NULL,
    igst_percentage DECIMAL(5,2) NULL,
    tax_amount DECIMAL(10,2) NULL,
    INDEX idx_sidg_line_item_id (invoice_line_item_id),
    FOREIGN KEY (invoice_line_item_id) REFERENCES sales_invoice_dtl(invoice_line_item_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- =============================================================================
-- 2. sales_invoice_jute (replaces sale_invoice_jute)
-- =============================================================================

CREATE TABLE IF NOT EXISTS sales_invoice_jute (
    sales_invoice_jute_id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    invoice_id BIGINT NULL,
    mr_no VARCHAR(50) NULL,
    mr_id BIGINT NULL,
    claim_amount BIGINT NULL,
    other_reference VARCHAR(100) NULL,
    unit_conversion VARCHAR(50) NULL,
    claim_description VARCHAR(255) NULL,
    INDEX idx_sij_invoice_id (invoice_id),
    FOREIGN KEY (invoice_id) REFERENCES sales_invoice(invoice_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- =============================================================================
-- 3. sales_invoice_jute_dtl (per-line-item jute detail)
-- =============================================================================

CREATE TABLE IF NOT EXISTS sales_invoice_jute_dtl (
    sales_invoice_jute_dtl_id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    invoice_line_item_id INT NULL,
    claim_amount_dtl DOUBLE NULL,
    claim_desc VARCHAR(255) NULL,
    claim_rate DOUBLE NULL,
    unit_conversion VARCHAR(255) NULL,
    qty_untit_conversion INT NULL,
    INDEX idx_sijd_line_item_id (invoice_line_item_id),
    FOREIGN KEY (invoice_line_item_id) REFERENCES sales_invoice_dtl(invoice_line_item_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- =============================================================================
-- 4. Data migration: inline GST -> sales_invoice_dtl_gst
-- =============================================================================
-- Rollback: DELETE FROM sales_invoice_dtl_gst WHERE sales_invoice_dtl_gst_id > 0;

INSERT INTO sales_invoice_dtl_gst (
    invoice_line_item_id,
    cgst_amount, cgst_percentage,
    sgst_amount, sgst_percentage,
    igst_amount, igst_percentage,
    tax_amount
)
SELECT
    invoice_line_item_id,
    cgst_amt, cgst_per,
    sgst_amt, sgst_per,
    igst_amt, igst_per,
    tax_amount
FROM sales_invoice_dtl
WHERE is_active = 1
  AND (
    (cgst_amt IS NOT NULL AND cgst_amt != 0)
    OR (sgst_amt IS NOT NULL AND sgst_amt != 0)
    OR (igst_amt IS NOT NULL AND igst_amt != 0)
  );

-- =============================================================================
-- 5. Data migration: sale_invoice_jute -> sales_invoice_jute
-- =============================================================================
-- Rollback: DELETE FROM sales_invoice_jute WHERE sales_invoice_jute_id > 0;

INSERT INTO sales_invoice_jute (
    invoice_id, mr_no, mr_id,
    claim_amount, other_reference, unit_conversion
)
SELECT
    invoice_id, mr_no, mr_id,
    claim_amount, other_reference, unit_conversion
FROM sale_invoice_jute;

-- NOTE: Old tables (sale_invoice_jute) and inline GST columns (cgst_amt, sgst_amt, etc.)
-- are NOT dropped. They remain for backward compatibility during transition.
