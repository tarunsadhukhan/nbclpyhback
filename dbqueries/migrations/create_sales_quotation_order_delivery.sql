-- Migration: create_sales_quotation_order_delivery.sql
-- Date: 2026-02-17
-- Description: Create sales quotation, sales order, and delivery order tables
--              with detail and GST parallel tables for each.
-- Note: co_id omitted from all tables — derived via branch_id -> branch_mst.co_id (dbmanager §5.6)
--       uom stored as uom_id INT (not VARCHAR) — JOIN uom_mst for display (dbmanager §5.6 Rule 1)
--       party_id kept alongside nullable party_branch_id (dbmanager §5.6 nullable exception)

-- =============================================================================
-- SALES QUOTATION
-- =============================================================================

CREATE TABLE IF NOT EXISTS sales_quotation (
    sales_quotation_id INT AUTO_INCREMENT PRIMARY KEY,
    updated_by INT NOT NULL,
    updated_date_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    quotation_date DATE,
    quotation_no VARCHAR(255),
    branch_id INT,
    party_id INT,
    sales_broker_id INT,
    billing_address_id INT,
    shipping_address_id INT,
    quotation_expiry_date DATE,
    footer_notes VARCHAR(255),
    brokerage_percentage DOUBLE,
    gross_amount DOUBLE,
    net_amount DOUBLE,
    round_off_value DOUBLE,
    payment_terms VARCHAR(255),
    delivery_terms VARCHAR(255),
    delivery_days INT,
    terms_condition VARCHAR(1000),
    internal_note VARCHAR(255),
    status_id INT DEFAULT 21,
    approval_level INT DEFAULT 0,
    active INT NOT NULL DEFAULT 1,
    INDEX idx_sq_branch (branch_id),
    INDEX idx_sq_party (party_id),
    INDEX idx_sq_status (status_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS sales_quotation_dtl (
    quotation_lineitem_id INT AUTO_INCREMENT PRIMARY KEY,
    updated_by INT NOT NULL,
    updated_date_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    sales_quotation_id INT,
    hsn_code VARCHAR(255),
    item_id INT,
    item_make_id INT,
    quantity DOUBLE,
    uom_id INT,
    rate DOUBLE,
    discount_type INT,
    discounted_rate DOUBLE,
    discount_amount DOUBLE,
    net_amount DOUBLE,
    total_amount DOUBLE,
    remarks VARCHAR(255),
    active INT NOT NULL DEFAULT 1,
    INDEX idx_sqd_quotation (sales_quotation_id),
    INDEX idx_sqd_item (item_id),
    INDEX idx_sqd_item_make (item_make_id),
    INDEX idx_sqd_uom (uom_id),
    FOREIGN KEY (sales_quotation_id) REFERENCES sales_quotation(sales_quotation_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS sales_quotation_dtl_gst (
    sales_quotation_dtl_gst_id INT AUTO_INCREMENT PRIMARY KEY,
    quotation_lineitem_id INT,
    igst_amount DOUBLE,
    igst_percent DOUBLE,
    cgst_amount DOUBLE,
    cgst_percent DOUBLE,
    sgst_amount DOUBLE,
    sgst_percent DOUBLE,
    gst_total DOUBLE,
    INDEX idx_sqdg_lineitem (quotation_lineitem_id),
    FOREIGN KEY (quotation_lineitem_id) REFERENCES sales_quotation_dtl(quotation_lineitem_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- =============================================================================
-- SALES ORDER
-- =============================================================================

CREATE TABLE IF NOT EXISTS sales_order (
    sales_order_id INT AUTO_INCREMENT PRIMARY KEY,
    updated_by INT NOT NULL,
    updated_date_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    sales_order_date DATE,
    sales_no VARCHAR(255),
    invoice_type INT,
    branch_id INT,
    quotation_id INT,
    party_id INT,
    party_branch_id INT,
    broker_id INT,
    billing_to_id INT,
    shipping_to_id INT,
    transporter_id INT,
    sales_order_expiry_date DATE,
    broker_commission_percent DOUBLE,
    footer_note VARCHAR(255),
    terms_conditions VARCHAR(255),
    internal_note VARCHAR(255),
    delivery_terms VARCHAR(255),
    payment_terms VARCHAR(255),
    delivery_days INT,
    freight_charges DOUBLE,
    gross_amount DOUBLE,
    net_amount DOUBLE,
    status_id INT DEFAULT 21,
    approval_level INT DEFAULT 0,
    active INT NOT NULL DEFAULT 1,
    INDEX idx_so_branch (branch_id),
    INDEX idx_so_party (party_id),
    INDEX idx_so_quotation (quotation_id),
    INDEX idx_so_status (status_id),
    FOREIGN KEY (quotation_id) REFERENCES sales_quotation(sales_quotation_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS sales_order_dtl (
    sales_order_dtl_id INT AUTO_INCREMENT PRIMARY KEY,
    updated_by INT NOT NULL,
    updated_date_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    sales_order_id INT,
    quotation_lineitem_id INT,
    hsn_code VARCHAR(255),
    item_id INT,
    item_make_id INT,
    quantity DOUBLE,
    uom_id INT,
    rate DOUBLE,
    discount_type INT,
    discounted_rate DOUBLE,
    discount_amount DOUBLE,
    net_amount DOUBLE,
    total_amount DOUBLE,
    remarks VARCHAR(255),
    active INT NOT NULL DEFAULT 1,
    INDEX idx_sod_order (sales_order_id),
    INDEX idx_sod_quotation_li (quotation_lineitem_id),
    INDEX idx_sod_item (item_id),
    INDEX idx_sod_item_make (item_make_id),
    INDEX idx_sod_uom (uom_id),
    FOREIGN KEY (sales_order_id) REFERENCES sales_order(sales_order_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS sales_order_dtl_gst (
    sales_order_dtl_gst_id INT AUTO_INCREMENT PRIMARY KEY,
    sales_order_dtl_id INT,
    igst_amount DOUBLE,
    igst_percent DOUBLE,
    cgst_amount DOUBLE,
    cgst_percent DOUBLE,
    sgst_amount DOUBLE,
    sgst_percent DOUBLE,
    gst_total DOUBLE,
    INDEX idx_sodg_dtl (sales_order_dtl_id),
    FOREIGN KEY (sales_order_dtl_id) REFERENCES sales_order_dtl(sales_order_dtl_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- =============================================================================
-- SALES DELIVERY ORDER
-- =============================================================================

CREATE TABLE IF NOT EXISTS sales_delivery_order (
    sales_delivery_order_id INT AUTO_INCREMENT PRIMARY KEY,
    updated_by INT NOT NULL,
    updated_date_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    delivery_order_date DATE,
    delivery_order_no VARCHAR(255),
    branch_id INT,
    sales_order_id INT,
    party_id INT,
    party_branch_id INT,
    billing_to_id INT,
    shipping_to_id INT,
    transporter_id INT,
    vehicle_no VARCHAR(50),
    driver_name VARCHAR(100),
    driver_contact VARCHAR(25),
    eway_bill_no VARCHAR(100),
    eway_bill_date DATE,
    expected_delivery_date DATE,
    footer_note VARCHAR(255),
    internal_note VARCHAR(255),
    gross_amount DOUBLE,
    net_amount DOUBLE,
    freight_charges DOUBLE,
    round_off_value DOUBLE,
    status_id INT DEFAULT 21,
    approval_level INT DEFAULT 0,
    active INT NOT NULL DEFAULT 1,
    INDEX idx_sdo_branch (branch_id),
    INDEX idx_sdo_party (party_id),
    INDEX idx_sdo_order (sales_order_id),
    INDEX idx_sdo_status (status_id),
    FOREIGN KEY (sales_order_id) REFERENCES sales_order(sales_order_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS sales_delivery_order_dtl (
    sales_delivery_order_dtl_id INT AUTO_INCREMENT PRIMARY KEY,
    updated_by INT NOT NULL,
    updated_date_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    sales_delivery_order_id INT,
    sales_order_dtl_id INT,
    hsn_code VARCHAR(255),
    item_id INT,
    item_make_id INT,
    quantity DOUBLE,
    uom_id INT,
    rate DOUBLE,
    discount_type INT,
    discounted_rate DOUBLE,
    discount_amount DOUBLE,
    net_amount DOUBLE,
    total_amount DOUBLE,
    remarks VARCHAR(255),
    active INT NOT NULL DEFAULT 1,
    INDEX idx_sdod_delivery (sales_delivery_order_id),
    INDEX idx_sdod_order_dtl (sales_order_dtl_id),
    INDEX idx_sdod_item (item_id),
    INDEX idx_sdod_item_make (item_make_id),
    INDEX idx_sdod_uom (uom_id),
    FOREIGN KEY (sales_delivery_order_id) REFERENCES sales_delivery_order(sales_delivery_order_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS sales_delivery_order_dtl_gst (
    sales_delivery_order_dtl_gst_id INT AUTO_INCREMENT PRIMARY KEY,
    sales_delivery_order_dtl_id INT,
    igst_amount DOUBLE,
    igst_percent DOUBLE,
    cgst_amount DOUBLE,
    cgst_percent DOUBLE,
    sgst_amount DOUBLE,
    sgst_percent DOUBLE,
    gst_total DOUBLE,
    INDEX idx_sdodg_dtl (sales_delivery_order_dtl_id),
    FOREIGN KEY (sales_delivery_order_dtl_id) REFERENCES sales_delivery_order_dtl(sales_delivery_order_dtl_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- =============================================================================
-- Rollback:
-- DROP TABLE IF EXISTS sales_delivery_order_dtl_gst;
-- DROP TABLE IF EXISTS sales_delivery_order_dtl;
-- DROP TABLE IF EXISTS sales_delivery_order;
-- DROP TABLE IF EXISTS sales_order_dtl_gst;
-- DROP TABLE IF EXISTS sales_order_dtl;
-- DROP TABLE IF EXISTS sales_order;
-- DROP TABLE IF EXISTS sales_quotation_dtl_gst;
-- DROP TABLE IF EXISTS sales_quotation_dtl;
-- DROP TABLE IF EXISTS sales_quotation;
-- =============================================================================
