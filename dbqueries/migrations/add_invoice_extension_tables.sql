-- Migration: Add invoice extension tables for Hessian, Jute Yarn, and Govt SKG Detail
-- Date: 2026-03-15
-- Applies to: tenant databases (e.g., dev3, sls)

-- =============================================================================
-- 1. Hessian Invoice Header Extension
-- =============================================================================
CREATE TABLE IF NOT EXISTS sales_invoice_hessian (
    sales_invoice_hessian_id INT AUTO_INCREMENT PRIMARY KEY,
    invoice_id BIGINT NULL,
    qty_bales DOUBLE NULL,
    rate_per_bale DOUBLE NULL,
    billing_rate_mt DOUBLE NULL,
    billing_rate_bale DOUBLE NULL,
    updated_by INT NULL,
    updated_date_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_invoice_id (invoice_id),
    CONSTRAINT fk_sih_invoice FOREIGN KEY (invoice_id) REFERENCES sales_invoice(invoice_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 2. Hessian Invoice Detail Extension
CREATE TABLE IF NOT EXISTS sales_invoice_hessian_dtl (
    sales_invoice_hessian_dtl_id INT AUTO_INCREMENT PRIMARY KEY,
    invoice_line_item_id INT NULL,
    qty_bales DOUBLE NULL,
    rate_per_bale DOUBLE NULL,
    billing_rate_mt DOUBLE NULL,
    billing_rate_bale DOUBLE NULL,
    updated_by INT NULL,
    updated_date_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_invoice_line_item_id (invoice_line_item_id),
    CONSTRAINT fk_sihd_line_item FOREIGN KEY (invoice_line_item_id) REFERENCES sales_invoice_dtl(invoice_line_item_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 3. Jute Yarn Invoice Header Extension
CREATE TABLE IF NOT EXISTS sales_invoice_juteyarn (
    sales_invoice_juteyarn_id INT AUTO_INCREMENT PRIMARY KEY,
    invoice_id BIGINT NULL,
    pcso_no VARCHAR(100) NULL,
    container_no VARCHAR(100) NULL,
    customer_ref_no VARCHAR(100) NULL,
    updated_by INT NULL,
    updated_date_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_invoice_id (invoice_id),
    CONSTRAINT fk_sijy_invoice FOREIGN KEY (invoice_id) REFERENCES sales_invoice(invoice_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 4. Jute Yarn Invoice Detail Extension
CREATE TABLE IF NOT EXISTS sales_invoice_juteyarn_dtl (
    sales_invoice_juteyarn_dtl_id INT AUTO_INCREMENT PRIMARY KEY,
    invoice_line_item_id INT NULL,
    updated_by INT NULL,
    updated_date_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_invoice_line_item_id (invoice_line_item_id),
    CONSTRAINT fk_sijyd_line_item FOREIGN KEY (invoice_line_item_id) REFERENCES sales_invoice_dtl(invoice_line_item_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 5. Govt SKG Invoice Detail Extension
CREATE TABLE IF NOT EXISTS sale_invoice_govtskg_dtl (
    sale_invoice_govtskg_dtl_id INT AUTO_INCREMENT PRIMARY KEY,
    invoice_line_item_id INT NULL,
    pack_sheet DOUBLE NULL,
    net_weight DOUBLE NULL,
    total_weight DOUBLE NULL,
    updated_by INT NULL,
    updated_date_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_invoice_line_item_id (invoice_line_item_id),
    CONSTRAINT fk_sigd_line_item FOREIGN KEY (invoice_line_item_id) REFERENCES sales_invoice_dtl(invoice_line_item_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- =============================================================================
-- ROLLBACK (if needed):
-- DROP TABLE IF EXISTS sale_invoice_govtskg_dtl;
-- DROP TABLE IF EXISTS sales_invoice_juteyarn_dtl;
-- DROP TABLE IF EXISTS sales_invoice_juteyarn;
-- DROP TABLE IF EXISTS sales_invoice_hessian_dtl;
-- DROP TABLE IF EXISTS sales_invoice_hessian;
-- =============================================================================
