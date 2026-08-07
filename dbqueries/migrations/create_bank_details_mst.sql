-- Migration: Create bank_details_mst table
-- Purpose: Master table for company bank account details
-- Date: 2026-03-31

CREATE TABLE IF NOT EXISTS bank_details_mst (
    bank_detail_id INT NOT NULL AUTO_INCREMENT,
    bank_name VARCHAR(255) NOT NULL,
    bank_branch VARCHAR(255) NOT NULL,
    acc_no VARCHAR(50) NOT NULL,
    ifsc_code VARCHAR(25) NOT NULL,
    mcr_code VARCHAR(25) DEFAULT NULL,
    swift_code VARCHAR(25) DEFAULT NULL,
    co_id INT NOT NULL,
    active INT NOT NULL DEFAULT 1,
    updated_by INT DEFAULT NULL,
    updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (bank_detail_id),
    INDEX idx_bank_details_co (co_id),
    UNIQUE KEY uk_bank_acc_co (acc_no, ifsc_code, co_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Rollback:
-- DROP TABLE IF EXISTS bank_details_mst;
