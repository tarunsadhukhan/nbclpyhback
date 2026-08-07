-- Migration: Add mode_of_transport to Govt Sacking tables + transport charge rate config table
-- Date: 2026-04-13

-- 1. New config table for transport-specific charge rates
CREATE TABLE IF NOT EXISTS govtskg_transport_charge_rate (
    id INT AUTO_INCREMENT PRIMARY KEY,
    mode_of_transport VARCHAR(20) NOT NULL,
    additional_charges_id INT NOT NULL,
    rate_per_100pcs DOUBLE NOT NULL DEFAULT 0,
    active TINYINT(1) NOT NULL DEFAULT 1,
    co_id INT NULL,
    INDEX idx_mode (mode_of_transport),
    INDEX idx_charge (additional_charges_id)
) ENGINE=InnoDB;

-- 2. Seed data (global defaults, co_id = NULL)
INSERT INTO govtskg_transport_charge_rate (mode_of_transport, additional_charges_id, rate_per_100pcs) VALUES
('CONCOR', 7, 50.00),
('RAIL',   7, 50.00),
('ROAD',   7, 50.00),
('CONCOR', 6, 21.54),
('RAIL',   6, 20.16);
-- No ROAD + charge 6 row = 2nd Handling Charges not applicable for ROAD

-- 3. Add mode_of_transport column to sales order govtskg header
ALTER TABLE sales_order_govtskg ADD COLUMN mode_of_transport VARCHAR(20) NULL AFTER loading_point;

-- 4. Add mode_of_transport column to sales invoice govtskg header
ALTER TABLE sales_invoice_govtskg ADD COLUMN mode_of_transport VARCHAR(20) NULL AFTER loading_point;

-- Rollback:
-- DROP TABLE IF EXISTS govtskg_transport_charge_rate;
-- ALTER TABLE sales_order_govtskg DROP COLUMN mode_of_transport;
-- ALTER TABLE sales_invoice_govtskg DROP COLUMN mode_of_transport;
