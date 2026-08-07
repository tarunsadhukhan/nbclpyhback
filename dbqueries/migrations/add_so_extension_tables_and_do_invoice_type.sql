-- Migration: Add Sales Order extension tables + DO invoice_type + Additional Charges
-- Date: 2026-03-18
-- Purpose:
--   1. Add invoice_type column to sales_delivery_order
--   2. Create SO extension tables for Jute, Jute Yarn, Govt SKG (mirrors SI extensions)
--   3. Create additional charges tables for SO and SI (mirrors proc_po_additional)

-- ============================================================
-- 1. Add invoice_type to sales_delivery_order
-- ============================================================
ALTER TABLE sales_delivery_order ADD COLUMN invoice_type INT NULL AFTER branch_id;

-- Backfill from linked sales orders
UPDATE sales_delivery_order sdo
  JOIN sales_order so ON so.sales_order_id = sdo.sales_order_id
  SET sdo.invoice_type = so.invoice_type
  WHERE sdo.sales_order_id IS NOT NULL AND sdo.invoice_type IS NULL;

-- ============================================================
-- 2. Sales Order — Jute extension (mirrors sales_invoice_jute)
-- ============================================================
CREATE TABLE IF NOT EXISTS sales_order_jute (
    sales_order_jute_id INT AUTO_INCREMENT PRIMARY KEY,
    sales_order_id INT NULL,
    mr_no VARCHAR(50) NULL,
    mr_id BIGINT NULL,
    claim_amount DECIMAL(12,2) NULL,
    other_reference VARCHAR(100) NULL,
    unit_conversion VARCHAR(50) NULL,
    claim_description VARCHAR(255) NULL,
    mukam_id INT NULL,
    updated_by INT NOT NULL,
    updated_date_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_sales_order_jute_order_id (sales_order_id),
    FOREIGN KEY (sales_order_id) REFERENCES sales_order(sales_order_id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS sales_order_jute_dtl (
    sales_order_jute_dtl_id INT AUTO_INCREMENT PRIMARY KEY,
    sales_order_dtl_id INT NULL,
    claim_amount_dtl DOUBLE NULL,
    claim_desc VARCHAR(255) NULL,
    claim_rate DOUBLE NULL,
    unit_conversion VARCHAR(255) NULL,
    qty_untit_conversion INT NULL,
    updated_by INT NOT NULL,
    updated_date_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_so_jute_dtl_dtl_id (sales_order_dtl_id),
    FOREIGN KEY (sales_order_dtl_id) REFERENCES sales_order_dtl(sales_order_dtl_id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ============================================================
-- 3. Sales Order — Jute Yarn extension (mirrors sales_invoice_juteyarn)
-- ============================================================
CREATE TABLE IF NOT EXISTS sales_order_juteyarn (
    sales_order_juteyarn_id INT AUTO_INCREMENT PRIMARY KEY,
    sales_order_id INT NULL,
    pcso_no VARCHAR(100) NULL,
    container_no VARCHAR(100) NULL,
    customer_ref_no VARCHAR(100) NULL,
    updated_by INT NOT NULL,
    updated_date_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_so_juteyarn_order_id (sales_order_id),
    FOREIGN KEY (sales_order_id) REFERENCES sales_order(sales_order_id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ============================================================
-- 4. Sales Order — Govt SKG extension (mirrors sales_invoice_govtskg)
-- ============================================================
CREATE TABLE IF NOT EXISTS sales_order_govtskg (
    sales_order_govtskg_id INT AUTO_INCREMENT PRIMARY KEY,
    sales_order_id INT NULL,
    pcso_no VARCHAR(100) NULL,
    pcso_date DATE NULL,
    administrative_office_address VARCHAR(500) NULL,
    destination_rail_head VARCHAR(100) NULL,
    loading_point VARCHAR(100) NULL,
    updated_by INT NOT NULL,
    updated_date_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_so_govtskg_order_id (sales_order_id),
    FOREIGN KEY (sales_order_id) REFERENCES sales_order(sales_order_id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS sales_order_govtskg_dtl (
    sales_order_govtskg_dtl_id INT AUTO_INCREMENT PRIMARY KEY,
    sales_order_dtl_id INT NULL,
    pack_sheet DOUBLE NULL,
    net_weight DOUBLE NULL,
    total_weight DOUBLE NULL,
    updated_by INT NOT NULL,
    updated_date_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_so_govtskg_dtl_dtl_id (sales_order_dtl_id),
    FOREIGN KEY (sales_order_dtl_id) REFERENCES sales_order_dtl(sales_order_dtl_id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ============================================================
-- 5. Additional Charges tables for Sales Order
--    (mirrors proc_po_additional pattern, uses existing additional_charges_mst)
-- ============================================================
CREATE TABLE IF NOT EXISTS sales_order_additional (
    sales_order_additional_id INT AUTO_INCREMENT PRIMARY KEY,
    sales_order_id INT NULL,
    additional_charges_id INT NULL,
    qty DOUBLE NULL,
    rate DOUBLE NULL,
    net_amount DOUBLE NULL,
    remarks VARCHAR(255) NULL,
    updated_by INT NOT NULL,
    updated_date_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_so_additional_order_id (sales_order_id),
    INDEX idx_so_additional_charges_id (additional_charges_id),
    FOREIGN KEY (sales_order_id) REFERENCES sales_order(sales_order_id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS sales_order_additional_gst (
    sales_order_additional_gst_id INT AUTO_INCREMENT PRIMARY KEY,
    sales_order_additional_id INT NULL,
    igst_amount DOUBLE NULL,
    igst_percent DOUBLE NULL,
    cgst_amount DOUBLE NULL,
    cgst_percent DOUBLE NULL,
    sgst_amount DOUBLE NULL,
    sgst_percent DOUBLE NULL,
    gst_total DOUBLE NULL,
    INDEX idx_so_additional_gst_id (sales_order_additional_id),
    FOREIGN KEY (sales_order_additional_id) REFERENCES sales_order_additional(sales_order_additional_id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ============================================================
-- 6. Additional Charges tables for Sales Invoice
-- ============================================================
CREATE TABLE IF NOT EXISTS sales_invoice_additional (
    sales_invoice_additional_id INT AUTO_INCREMENT PRIMARY KEY,
    invoice_id BIGINT NULL,
    additional_charges_id INT NULL,
    qty DOUBLE NULL,
    rate DOUBLE NULL,
    net_amount DOUBLE NULL,
    remarks VARCHAR(255) NULL,
    updated_by INT NOT NULL,
    updated_date_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_si_additional_invoice_id (invoice_id),
    INDEX idx_si_additional_charges_id (additional_charges_id),
    FOREIGN KEY (invoice_id) REFERENCES sales_invoice(invoice_id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS sales_invoice_additional_gst (
    sales_invoice_additional_gst_id INT AUTO_INCREMENT PRIMARY KEY,
    sales_invoice_additional_id INT NULL,
    igst_amount DOUBLE NULL,
    igst_percent DOUBLE NULL,
    cgst_amount DOUBLE NULL,
    cgst_percent DOUBLE NULL,
    sgst_amount DOUBLE NULL,
    sgst_percent DOUBLE NULL,
    gst_total DOUBLE NULL,
    INDEX idx_si_additional_gst_id (sales_invoice_additional_id),
    FOREIGN KEY (sales_invoice_additional_id) REFERENCES sales_invoice_additional(sales_invoice_additional_id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ============================================================
-- Rollback (run in reverse order):
-- ============================================================
-- DROP TABLE IF EXISTS sales_invoice_additional_gst;
-- DROP TABLE IF EXISTS sales_invoice_additional;
-- DROP TABLE IF EXISTS sales_order_additional_gst;
-- DROP TABLE IF EXISTS sales_order_additional;
-- DROP TABLE IF EXISTS sales_order_govtskg_dtl;
-- DROP TABLE IF EXISTS sales_order_govtskg;
-- DROP TABLE IF EXISTS sales_order_juteyarn;
-- DROP TABLE IF EXISTS sales_order_jute_dtl;
-- DROP TABLE IF EXISTS sales_order_jute;
-- ALTER TABLE sales_delivery_order DROP COLUMN invoice_type;
