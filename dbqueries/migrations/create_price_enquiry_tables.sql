-- Migration: Price Enquiry Module Tables
-- Purpose: Adds missing columns to existing enquiry tables and creates
--          the proc_enquiry_supplier junction table for many-to-many
--          supplier associations.
-- Date: 2026-04-10
-- Run against: TENANT database (e.g., dev3, sls)
-- Rollback:
--   DROP TABLE IF EXISTS proc_enquiry_supplier;
--   ALTER TABLE proc_enquiry DROP COLUMN price_enquiry_squence_no, ... (drop the
--   columns added below individually; review data before dropping).
-- Note: Plain MySQL 8 DDL (no IF NOT EXISTS on ADD COLUMN). The migration
--       runner should catch "Duplicate column name" / "Duplicate key name"
--       errors and treat them as idempotent skips.

-- ═══════════════════════════════════════════════════════════════════
-- 1. ALTER proc_enquiry — add missing columns
-- ═══════════════════════════════════════════════════════════════════

ALTER TABLE proc_enquiry ADD COLUMN co_id INT NULL AFTER enquiry_id;
ALTER TABLE proc_enquiry ADD COLUMN enquiry_no INT NULL AFTER branch_id;
ALTER TABLE proc_enquiry ADD COLUMN enquiry_type VARCHAR(25) DEFAULT 'Regular' AFTER price_enquiry_squence_no;
ALTER TABLE proc_enquiry ADD COLUMN expense_type_id INT NULL;
ALTER TABLE proc_enquiry ADD COLUMN project_id INT NULL;
ALTER TABLE proc_enquiry ADD COLUMN approval_level INT NULL;
ALTER TABLE proc_enquiry ADD INDEX idx_enquiry_co (co_id);


-- ═══════════════════════════════════════════════════════════════════
-- 2. ALTER proc_price_enquiry_response — add missing columns
-- ═══════════════════════════════════════════════════════════════════

ALTER TABLE proc_price_enquiry_response ADD COLUMN credit_days INT NULL;
ALTER TABLE proc_price_enquiry_response ADD COLUMN supplier_branch_id INT NULL;
ALTER TABLE proc_price_enquiry_response ADD COLUMN payment_terms VARCHAR(255) NULL;
ALTER TABLE proc_price_enquiry_response ADD COLUMN is_selected INT NOT NULL DEFAULT 0;
ALTER TABLE proc_price_enquiry_response ADD COLUMN active INT NOT NULL DEFAULT 1;


-- ═══════════════════════════════════════════════════════════════════
-- 3. ALTER proc_price_enquiry_response_dtl — add missing columns
-- ═══════════════════════════════════════════════════════════════════

ALTER TABLE proc_price_enquiry_response_dtl ADD COLUMN proc_price_enquiry_response_id INT NULL AFTER proc_price_enquiry_response_dtl_id;
ALTER TABLE proc_price_enquiry_response_dtl ADD COLUMN active INT NOT NULL DEFAULT 1;
ALTER TABLE proc_price_enquiry_response_dtl ADD COLUMN updated_by INT NULL;
ALTER TABLE proc_price_enquiry_response_dtl ADD COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;
ALTER TABLE proc_price_enquiry_response_dtl ADD INDEX idx_resp_dtl_response (proc_price_enquiry_response_id);


-- ═══════════════════════════════════════════════════════════════════
-- 4. ALTER proc_enquiry_dtl — add missing columns used by queries
-- ═══════════════════════════════════════════════════════════════════

ALTER TABLE proc_enquiry_dtl ADD COLUMN indent_id INT NULL AFTER indent_dtl_id;
ALTER TABLE proc_enquiry_dtl ADD COLUMN dept_id INT NULL AFTER item_make_id;
ALTER TABLE proc_enquiry_dtl ADD INDEX idx_enq_dtl_indent (indent_id);
ALTER TABLE proc_enquiry_dtl ADD INDEX idx_enq_dtl_dept (dept_id);


-- ═══════════════════════════════════════════════════════════════════
-- 5. CREATE proc_enquiry_supplier — many-to-many junction table
-- ═══════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS proc_enquiry_supplier (
    enquiry_supplier_id  INT          NOT NULL AUTO_INCREMENT,
    enquiry_id           INT          NOT NULL,
    supplier_id          INT          NOT NULL,
    supplier_branch_id   INT          NULL,
    sent_date            DATE         NULL,
    sent_status          INT          NOT NULL DEFAULT 0,
    active               INT          NOT NULL DEFAULT 1,
    updated_by           INT          NOT NULL,
    updated_date_time    TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (enquiry_supplier_id),

    CONSTRAINT fk_enq_supp_enquiry
        FOREIGN KEY (enquiry_id) REFERENCES proc_enquiry(enquiry_id),

    CONSTRAINT fk_enq_supp_supplier
        FOREIGN KEY (supplier_id) REFERENCES party_mst(party_id),

    UNIQUE KEY uk_enquiry_supplier (enquiry_id, supplier_id),

    INDEX idx_enq_supp_enquiry (enquiry_id),
    INDEX idx_enq_supp_supplier (supplier_id)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
