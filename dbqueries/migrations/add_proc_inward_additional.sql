-- Migration: Add proc_inward_additional table for SR additional charges
-- Date: 2026-01-02
-- Description: Creates table for storing additional charges at inward/SR level
--              and adds inward_additional_id to proc_gst for GST tracking

-- =============================================================================
-- Step 1: Create proc_inward_additional table
-- =============================================================================
CREATE TABLE IF NOT EXISTS proc_inward_additional (
    inward_additional_id INT PRIMARY KEY AUTO_INCREMENT,
    inward_id INT NOT NULL,
    additional_charges_id INT NOT NULL,
    qty INT NOT NULL DEFAULT 1,
    rate DOUBLE,
    net_amount DOUBLE,
    remarks VARCHAR(255),
    active BOOLEAN NOT NULL DEFAULT TRUE,
    updated_by INT NOT NULL,
    updated_date_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    
    -- Foreign Keys
    CONSTRAINT fk_inward_additional_inward 
        FOREIGN KEY (inward_id) REFERENCES proc_inward(inward_id),
    CONSTRAINT fk_inward_additional_charges 
        FOREIGN KEY (additional_charges_id) REFERENCES additional_charges_master(additional_charges_id),
    
    -- Indexes
    INDEX idx_inward_additional_inward (inward_id),
    INDEX idx_inward_additional_charges (additional_charges_id)
);

-- =============================================================================
-- Step 2: Add inward_additional_id column to proc_gst table
-- =============================================================================
ALTER TABLE proc_gst 
    ADD COLUMN inward_additional_id INT NULL AFTER proc_inward_dtl,
    ADD INDEX idx_proc_gst_inward_additional (inward_additional_id),
    ADD CONSTRAINT fk_proc_gst_inward_additional 
        FOREIGN KEY (inward_additional_id) REFERENCES proc_inward_additional(inward_additional_id);

-- =============================================================================
-- Rollback Script (if needed):
-- =============================================================================
-- ALTER TABLE proc_gst DROP FOREIGN KEY fk_proc_gst_inward_additional;
-- ALTER TABLE proc_gst DROP INDEX idx_proc_gst_inward_additional;
-- ALTER TABLE proc_gst DROP COLUMN inward_additional_id;
-- DROP TABLE IF EXISTS proc_inward_additional;
