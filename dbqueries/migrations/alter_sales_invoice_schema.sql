-- Migration: Restructure sales_invoice table for dev3
-- Removes unused columns, adds new columns, changes column types,
-- and creates two new child tables: sale_invoice_govtskg, sale_invoice_jute.
-- Run against: dev3

-- =============================================================================
-- 1. CREATE NEW CHILD TABLES (before dropping columns, so data can be migrated)
-- =============================================================================

CREATE TABLE IF NOT EXISTS sale_invoice_govtskg (
    sale_invoice_govtskg_id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    invoice_id BIGINT NULL,
    pcso_no VARCHAR(100) NULL,
    pcso_date DATE NULL,
    administrative_office_address VARCHAR(500) NULL,
    destination_rail_head VARCHAR(100) NULL,
    loading_point VARCHAR(100) NULL,
    pack_sheet DECIMAL(10, 3) NULL,
    net_weight DECIMAL(10, 3) NULL,
    total_weight DECIMAL(10, 3) NULL,
    INDEX idx_invoice_id (invoice_id),
    FOREIGN KEY (invoice_id) REFERENCES sales_invoice(invoice_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS sale_invoice_jute (
    sale_invoice_jute_id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    invoice_id BIGINT NULL,
    mr_no VARCHAR(50) NULL,
    mr_id BIGINT NULL,
    claim_amount BIGINT NULL,
    other_reference VARCHAR(100) NULL,
    unit_conversion VARCHAR(50) NULL,
    INDEX idx_invoice_id (invoice_id),
    FOREIGN KEY (invoice_id) REFERENCES sales_invoice(invoice_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- =============================================================================
-- 2. MIGRATE EXISTING DATA into new child tables
-- =============================================================================

INSERT INTO sale_invoice_govtskg (invoice_id, pcso_no, pcso_date, administrative_office_address,
    destination_rail_head, loading_point, pack_sheet, net_weight, total_weight)
SELECT invoice_id, pcso_no, pcso_date, administrative_office_address,
    destination_rail_head, loading_point, pack_sheet, net_weight, total_weight
FROM sales_invoice
WHERE pcso_no IS NOT NULL
   OR pcso_date IS NOT NULL
   OR administrative_office_address IS NOT NULL
   OR destination_rail_head IS NOT NULL
   OR loading_point IS NOT NULL
   OR pack_sheet IS NOT NULL
   OR net_weight IS NOT NULL
   OR total_weight IS NOT NULL;

INSERT INTO sale_invoice_jute (invoice_id, mr_no, mr_id, claim_amount, other_reference, unit_conversion)
SELECT invoice_id, mr_no, mr_id, claim_amount, other_reference, unit_conversion
FROM sales_invoice
WHERE mr_no IS NOT NULL
   OR mr_id IS NOT NULL
   OR claim_amount IS NOT NULL
   OR other_reference IS NOT NULL
   OR unit_conversion IS NOT NULL;

-- =============================================================================
-- 3. ADD NEW COLUMNS to sales_invoice
-- =============================================================================

ALTER TABLE sales_invoice ADD COLUMN invoice_no BIGINT NULL AFTER invoice_id;
ALTER TABLE sales_invoice ADD COLUMN sales_delivery_order_id INT NULL AFTER party_id;
ALTER TABLE sales_invoice ADD COLUMN broker_id INT NULL AFTER sales_delivery_order_id;
ALTER TABLE sales_invoice ADD COLUMN status_id INT NULL AFTER is_active;
ALTER TABLE sales_invoice ADD COLUMN updated_date_time DATETIME NULL DEFAULT CURRENT_TIMESTAMP AFTER updated_by;

ALTER TABLE sales_invoice ADD INDEX idx_sales_delivery_order_id (sales_delivery_order_id);
ALTER TABLE sales_invoice ADD INDEX idx_status_id (status_id);
ALTER TABLE sales_invoice ADD FOREIGN KEY (sales_delivery_order_id) REFERENCES sales_delivery_order(sales_delivery_order_id);

-- =============================================================================
-- 4. CHANGE COLUMN TYPES
-- =============================================================================

ALTER TABLE sales_invoice MODIFY COLUMN invoice_type INT NULL;
ALTER TABLE sales_invoice MODIFY COLUMN shipping_state_code INT NULL;
ALTER TABLE sales_invoice MODIFY COLUMN tax_payable DOUBLE NULL;

-- =============================================================================
-- 5. DROP REMOVED COLUMNS from sales_invoice
-- =============================================================================

-- NOTE: MySQL 8.0 does not support DROP COLUMN IF EXISTS (MariaDB only).
-- Verify columns exist before running these statements.
ALTER TABLE sales_invoice DROP COLUMN co_id;
ALTER TABLE sales_invoice DROP COLUMN created_by;
ALTER TABLE sales_invoice DROP COLUMN created_date;
ALTER TABLE sales_invoice DROP COLUMN party_branch_id;
ALTER TABLE sales_invoice DROP COLUMN del_order_no;
ALTER TABLE sales_invoice DROP COLUMN del_order_date;
ALTER TABLE sales_invoice DROP COLUMN delivery_order_id;
ALTER TABLE sales_invoice DROP COLUMN due_amount;
ALTER TABLE sales_invoice DROP COLUMN grand_total;
ALTER TABLE sales_invoice DROP COLUMN invoice_no_string;
ALTER TABLE sales_invoice DROP COLUMN invoice_unique_no;
ALTER TABLE sales_invoice DROP COLUMN quote_id;
ALTER TABLE sales_invoice DROP COLUMN sale_no;
ALTER TABLE sales_invoice DROP COLUMN shipping_address;
ALTER TABLE sales_invoice DROP COLUMN shipping_state_name;
ALTER TABLE sales_invoice DROP COLUMN status;
ALTER TABLE sales_invoice DROP COLUMN updated_date;
ALTER TABLE sales_invoice DROP COLUMN sale_order_date;
ALTER TABLE sales_invoice DROP COLUMN payable_tax;
ALTER TABLE sales_invoice DROP COLUMN tds_payable;
ALTER TABLE sales_invoice DROP COLUMN tds_reason;
ALTER TABLE sales_invoice DROP COLUMN tds_amount;
ALTER TABLE sales_invoice DROP COLUMN broker_name;
ALTER TABLE sales_invoice DROP COLUMN date_of_removal_of_goods;
ALTER TABLE sales_invoice DROP COLUMN fatory_address;
ALTER TABLE sales_invoice DROP COLUMN packing_id;
ALTER TABLE sales_invoice DROP COLUMN tcs_percentage;
ALTER TABLE sales_invoice DROP COLUMN tcs_amount;
ALTER TABLE sales_invoice DROP COLUMN destination;
ALTER TABLE sales_invoice DROP COLUMN sale_order_type;
ALTER TABLE sales_invoice DROP COLUMN tally_sync;

-- Drop columns shifted to sale_invoice_govtskg
ALTER TABLE sales_invoice DROP COLUMN pcso_no;
ALTER TABLE sales_invoice DROP COLUMN pcso_date;
ALTER TABLE sales_invoice DROP COLUMN administrative_office_address;
ALTER TABLE sales_invoice DROP COLUMN destination_rail_head;
ALTER TABLE sales_invoice DROP COLUMN loading_point;
ALTER TABLE sales_invoice DROP COLUMN pack_sheet;
ALTER TABLE sales_invoice DROP COLUMN net_weight;
ALTER TABLE sales_invoice DROP COLUMN total_weight;

-- Drop columns shifted to sale_invoice_jute
ALTER TABLE sales_invoice DROP COLUMN mr_no;
ALTER TABLE sales_invoice DROP COLUMN mr_id;
ALTER TABLE sales_invoice DROP COLUMN claim_amount;
ALTER TABLE sales_invoice DROP COLUMN other_reference;
ALTER TABLE sales_invoice DROP COLUMN unit_conversion;

-- =============================================================================
-- ROLLBACK (run in reverse order if needed):
-- =============================================================================
-- NOTE: Rollback is destructive - the ADD COLUMN statements below restore structure
-- but migrated data in child tables would need manual re-merge.
--
-- DROP TABLE IF EXISTS sale_invoice_jute;
-- DROP TABLE IF EXISTS sale_invoice_govtskg;
-- (Then re-add all dropped columns and revert type changes manually)
