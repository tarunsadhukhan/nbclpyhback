-- Migration: Create invoice_type_co_map table
-- Maps invoice types to companies (many-to-many)
-- Run against each tenant database (e.g., dev3, sls)

CREATE TABLE IF NOT EXISTS invoice_type_co_map (
    invoice_type_co_map_id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    co_id INT NOT NULL,
    invoice_type_id INT NOT NULL,
    active INT NOT NULL DEFAULT 1,
    updated_by INT NULL,
    updated_date_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_co_id (co_id),
    INDEX idx_invoice_type_id (invoice_type_id),
    FOREIGN KEY (invoice_type_id) REFERENCES invoice_type_mst(invoice_type_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Rollback:
-- DROP TABLE IF EXISTS invoice_type_co_map;
