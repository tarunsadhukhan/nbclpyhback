-- Migration: Create sales_order_dtl_hessian table
-- Purpose: Stores hessian (invoice_type=2) specific line item data (bale qty, raw rates, billing rates)
-- The main sales_order_dtl stores MT values (quantity in MT, rate = billing rate per MT).
-- This extension table stores the user-entered bale values and pre-brokerage rate derivatives.
-- Date: 2026-02-26

CREATE TABLE IF NOT EXISTS sales_order_dtl_hessian (
    sales_order_dtl_hessian_id INT AUTO_INCREMENT PRIMARY KEY,
    sales_order_dtl_id INT NOT NULL,
    qty_bales DOUBLE DEFAULT NULL COMMENT 'User-entered quantity in bales',
    rate_per_bale DOUBLE DEFAULT NULL COMMENT 'Raw entered rate / conversion factor (pre-brokerage)',
    billing_rate_mt DOUBLE DEFAULT NULL COMMENT 'Rate after brokerage deduction per MT',
    billing_rate_bale DOUBLE DEFAULT NULL COMMENT 'Billing rate per bale (billing_rate_mt / conversion factor)',
    updated_by INT NOT NULL,
    updated_date_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_sales_order_dtl_id (sales_order_dtl_id),
    CONSTRAINT fk_so_dtl_hessian_dtl FOREIGN KEY (sales_order_dtl_id)
        REFERENCES sales_order_dtl (sales_order_dtl_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Rollback:
-- DROP TABLE IF EXISTS sales_order_dtl_hessian;
