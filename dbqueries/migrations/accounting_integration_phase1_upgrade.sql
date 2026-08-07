-- =============================================================================
-- Accounting integration upgrade (gap-analysis Phase 0 + Phase 1 schema)
-- Target: tenant DBs (run on dev3 first). Module is unused so tables are empty;
-- ALTERs are safe.
--
-- 1. acc_bill_ref gains co_id / party_id / pending_amount (bill-wise AP/AR
--    outstanding without joining through voucher lines).
-- 2. acc_company_settings — per-company posting behaviour (OFF / AUTO_DRAFT /
--    AUTO_APPROVED per doc type), due-date rule, TDS switch.
-- 3. acc_posting_queue — outbox for auto-posting attempts (failure isolation).
-- 4. acc_ageing_slab — configurable ageing buckets per company.
--
-- Rollback:
--   ALTER TABLE acc_bill_ref DROP COLUMN co_id, DROP COLUMN party_id,
--     DROP COLUMN pending_amount;
--   DROP TABLE IF EXISTS acc_posting_queue;
--   DROP TABLE IF EXISTS acc_company_settings;
--   DROP TABLE IF EXISTS acc_ageing_slab;
-- =============================================================================

ALTER TABLE acc_bill_ref
    ADD COLUMN co_id INT NOT NULL AFTER acc_bill_ref_id,
    ADD COLUMN party_id INT NULL AFTER acc_voucher_line_id,
    ADD COLUMN pending_amount DECIMAL(15,2) NULL AFTER amount,
    ADD KEY idx_billref_co_party (co_id, party_id),
    ADD KEY idx_billref_party_status (party_id, status);

CREATE TABLE IF NOT EXISTS acc_company_settings (
    acc_company_settings_id INT PRIMARY KEY AUTO_INCREMENT,
    co_id                   INT NOT NULL,
    posting_mode_purchase   VARCHAR(15) NOT NULL DEFAULT 'OFF' COMMENT 'OFF | AUTO_DRAFT | AUTO_APPROVED',
    posting_mode_jute_purchase VARCHAR(15) NOT NULL DEFAULT 'OFF',
    posting_mode_sales      VARCHAR(15) NOT NULL DEFAULT 'OFF',
    posting_mode_drcr       VARCHAR(15) NOT NULL DEFAULT 'OFF',
    due_date_rule           VARCHAR(20) NOT NULL DEFAULT 'PO_CREDIT_DAYS' COMMENT 'PO_CREDIT_DAYS | MANUAL',
    default_credit_days     INT NULL,
    enable_tds              TINYINT DEFAULT 1,
    expense_approval_required TINYINT DEFAULT 0,
    active                  TINYINT NOT NULL DEFAULT 1,
    updated_by              INT NOT NULL,
    updated_date_time       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_settings_co (co_id)
);

CREATE TABLE IF NOT EXISTS acc_posting_queue (
    acc_posting_queue_id BIGINT PRIMARY KEY AUTO_INCREMENT,
    co_id                INT NOT NULL,
    source_doc_type      VARCHAR(30) NOT NULL,
    source_doc_id        BIGINT NOT NULL,
    status               VARCHAR(10) NOT NULL DEFAULT 'PENDING' COMMENT 'PENDING | POSTED | DRAFTED | SKIPPED | FAILED',
    acc_voucher_id       BIGINT NULL,
    attempt_count        INT DEFAULT 0,
    last_error           VARCHAR(1000) NULL,
    active               TINYINT NOT NULL DEFAULT 1,
    updated_by           INT NOT NULL,
    updated_date_time    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_queue_source (source_doc_type, source_doc_id),
    KEY idx_queue_co_status (co_id, status)
);

CREATE TABLE IF NOT EXISTS acc_ageing_slab (
    acc_ageing_slab_id INT PRIMARY KEY AUTO_INCREMENT,
    co_id              INT NOT NULL,
    slab_name          VARCHAR(30) NOT NULL,
    from_days          INT NOT NULL,
    to_days            INT NULL COMMENT 'NULL = open-ended (e.g. 180+)',
    sequence_no        INT NULL,
    active             TINYINT NOT NULL DEFAULT 1,
    updated_by         INT NOT NULL,
    updated_date_time  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_ageing_co (co_id)
);
