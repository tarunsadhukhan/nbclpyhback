-- =============================================================================
-- MIGRATION: Add sales_invoice_freight table + invoice_type_mst row for type 7
-- =============================================================================
-- Run this script PER TENANT DATABASE (e.g. dev3, sls, etc.)
-- This must be run BEFORE deploying the Govt Sacking Freight (type 7) feature.
--
-- What this does:
-- 1. Ensures item_type_id=1 ('Regular') exists in item_type_master (required
--    because the type-7 create flow auto-provisions a "Freight" item group
--    under item_type_id=1).
-- 2. Ensures invoice_type_id=7 ('Govt Sacking Freight') exists in
--    invoice_type_mst.
-- 3. Creates the sales_invoice_freight extension table linking each freight
--    invoice (type 7) to its source Govt Sacking invoice (type 3), and storing
--    the IW Bill fields specific to the freight leg.
--
-- ROLLBACK instructions are in comments at the bottom.
-- =============================================================================

-- =============================================================================
-- Step 1: Ensure item_type_id=1 ('Regular') exists in item_type_master
-- =============================================================================
INSERT INTO item_type_master (item_type_id, item_type_name, updated_by, updated_date_time)
SELECT 1, 'Regular', 1, NOW()
FROM DUAL
WHERE NOT EXISTS (
    SELECT 1 FROM item_type_master WHERE item_type_id = 1
);

-- =============================================================================
-- Step 2: Ensure invoice_type_id=7 ('Govt Sacking Freight') exists
-- =============================================================================
INSERT INTO invoice_type_mst (invoice_type_id, invoice_type_name)
SELECT 7, 'Govt Sacking Freight'
FROM DUAL
WHERE NOT EXISTS (
    SELECT 1 FROM invoice_type_mst WHERE invoice_type_id = 7
);

-- =============================================================================
-- Step 3: Create sales_invoice_freight extension table
-- =============================================================================
CREATE TABLE IF NOT EXISTS sales_invoice_freight (
    sales_invoice_freight_id INT AUTO_INCREMENT PRIMARY KEY,
    invoice_id BIGINT NOT NULL,
    source_invoice_id BIGINT NOT NULL,
    iw_bill_no VARCHAR(100) NULL,
    iw_bill_date DATE NULL,
    updated_by INT NULL,
    updated_date_time DATETIME NULL,
    INDEX idx_sif_invoice_id (invoice_id),
    INDEX idx_sif_source_invoice_id (source_invoice_id),
    CONSTRAINT fk_sif_invoice FOREIGN KEY (invoice_id) REFERENCES sales_invoice(invoice_id),
    CONSTRAINT fk_sif_source FOREIGN KEY (source_invoice_id) REFERENCES sales_invoice(invoice_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- =============================================================================
-- ROLLBACK (if needed):
-- DROP TABLE IF EXISTS sales_invoice_freight;
-- DELETE FROM invoice_type_mst WHERE invoice_type_id=7;
-- -- Note: item_type_id=1 ('Regular') is intentionally NOT removed on rollback
-- --       because it may be referenced by other item groups.
-- =============================================================================
