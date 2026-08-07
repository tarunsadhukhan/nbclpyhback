-- =============================================
-- VoWERP3 Accounting Module - Phase 1 Migration
-- Date: 2026-04-01
-- Tables: 15 core accounting tables
-- =============================================

-- =============================================
-- Table: acc_ledger_group
-- =============================================
CREATE TABLE IF NOT EXISTS acc_ledger_group (
    acc_ledger_group_id INT NOT NULL AUTO_INCREMENT,
    co_id INT NOT NULL,
    parent_group_id INT NULL,
    group_name VARCHAR(100) NOT NULL,
    group_code VARCHAR(20) NULL,
    nature VARCHAR(20) NULL,
    affects_gross_profit INT NULL DEFAULT 0,
    is_revenue INT NULL DEFAULT 0,
    normal_balance VARCHAR(1) NULL,
    is_party_group INT NULL DEFAULT 0,
    is_system_group INT NULL DEFAULT 0,
    sequence_no INT NULL,
    active INT NOT NULL DEFAULT 1,
    updated_by INT NOT NULL,
    updated_date_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (acc_ledger_group_id),
    INDEX idx_acc_ledger_group_co_id (co_id),
    INDEX idx_acc_ledger_group_parent_group_id (parent_group_id),
    CONSTRAINT fk_acc_ledger_group_parent FOREIGN KEY (parent_group_id)
        REFERENCES acc_ledger_group (acc_ledger_group_id)
);

-- =============================================
-- Table: acc_financial_year
-- =============================================
CREATE TABLE IF NOT EXISTS acc_financial_year (
    acc_financial_year_id INT NOT NULL AUTO_INCREMENT,
    co_id INT NOT NULL,
    fy_start DATE NOT NULL,
    fy_end DATE NOT NULL,
    fy_label VARCHAR(20) NULL,
    is_active INT NULL DEFAULT 1,
    is_locked INT NULL DEFAULT 0,
    locked_by INT NULL,
    locked_date_time DATETIME NULL,
    updated_by INT NOT NULL,
    updated_date_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (acc_financial_year_id),
    INDEX idx_acc_financial_year_co_id (co_id)
);

-- =============================================
-- Table: acc_ledger
-- =============================================
CREATE TABLE IF NOT EXISTS acc_ledger (
    acc_ledger_id INT NOT NULL AUTO_INCREMENT,
    co_id INT NOT NULL,
    acc_ledger_group_id INT NOT NULL,
    ledger_name VARCHAR(150) NOT NULL,
    ledger_code VARCHAR(20) NULL,
    ledger_type VARCHAR(1) NULL,
    party_id INT NULL,
    credit_days INT NULL,
    credit_limit DECIMAL(15,2) NULL,
    opening_balance DECIMAL(15,2) NULL,
    opening_balance_type VARCHAR(1) NULL,
    opening_fy_id INT NULL,
    gst_applicable INT NULL DEFAULT 0,
    hsn_sac_code VARCHAR(20) NULL,
    is_system_ledger INT NULL DEFAULT 0,
    is_related_party INT NULL DEFAULT 0,
    active INT NOT NULL DEFAULT 1,
    updated_by INT NOT NULL,
    updated_date_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (acc_ledger_id),
    INDEX idx_acc_ledger_co_id (co_id),
    INDEX idx_acc_ledger_group_id (acc_ledger_group_id),
    INDEX idx_acc_ledger_party_id (party_id),
    CONSTRAINT fk_acc_ledger_group FOREIGN KEY (acc_ledger_group_id)
        REFERENCES acc_ledger_group (acc_ledger_group_id),
    CONSTRAINT fk_acc_ledger_opening_fy FOREIGN KEY (opening_fy_id)
        REFERENCES acc_financial_year (acc_financial_year_id)
);

-- =============================================
-- Table: acc_voucher_type
-- =============================================
CREATE TABLE IF NOT EXISTS acc_voucher_type (
    acc_voucher_type_id INT NOT NULL AUTO_INCREMENT,
    co_id INT NOT NULL,
    type_name VARCHAR(50) NOT NULL,
    type_code VARCHAR(10) NULL,
    type_category VARCHAR(20) NULL,
    auto_numbering INT NULL DEFAULT 1,
    prefix VARCHAR(10) NULL,
    requires_bank_cash INT NULL DEFAULT 0,
    is_system_type INT NULL DEFAULT 0,
    active INT NOT NULL DEFAULT 1,
    updated_by INT NOT NULL,
    updated_date_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (acc_voucher_type_id),
    INDEX idx_acc_voucher_type_co_id (co_id)
);

-- =============================================
-- Table: acc_period_lock
-- =============================================
CREATE TABLE IF NOT EXISTS acc_period_lock (
    acc_period_lock_id INT NOT NULL AUTO_INCREMENT,
    acc_financial_year_id INT NOT NULL,
    period_month INT NULL,
    period_start DATE NULL,
    period_end DATE NULL,
    is_locked INT NULL DEFAULT 0,
    locked_by INT NULL,
    locked_date_time DATETIME NULL,
    updated_by INT NOT NULL,
    updated_date_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (acc_period_lock_id),
    INDEX idx_acc_period_lock_fy_id (acc_financial_year_id),
    CONSTRAINT fk_acc_period_lock_fy FOREIGN KEY (acc_financial_year_id)
        REFERENCES acc_financial_year (acc_financial_year_id)
);

-- =============================================
-- Table: acc_account_determination
-- =============================================
CREATE TABLE IF NOT EXISTS acc_account_determination (
    acc_account_determination_id INT NOT NULL AUTO_INCREMENT,
    co_id INT NOT NULL,
    doc_type VARCHAR(30) NULL,
    line_type VARCHAR(30) NULL,
    acc_ledger_id INT NULL,
    item_grp_id INT NULL,
    is_default INT NULL DEFAULT 0,
    active INT NOT NULL DEFAULT 1,
    updated_by INT NOT NULL,
    updated_date_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (acc_account_determination_id),
    INDEX idx_acc_account_determination_co_id (co_id),
    INDEX idx_acc_account_determination_ledger_id (acc_ledger_id),
    INDEX idx_acc_account_determination_item_grp_id (item_grp_id),
    CONSTRAINT fk_acc_account_determination_ledger FOREIGN KEY (acc_ledger_id)
        REFERENCES acc_ledger (acc_ledger_id)
);

-- =============================================
-- Table: acc_voucher
-- =============================================
CREATE TABLE IF NOT EXISTS acc_voucher (
    acc_voucher_id BIGINT NOT NULL AUTO_INCREMENT,
    co_id INT NOT NULL,
    branch_id INT NULL,
    acc_voucher_type_id INT NOT NULL,
    acc_financial_year_id INT NOT NULL,
    voucher_no VARCHAR(30) NULL,
    voucher_date DATE NOT NULL,
    party_id INT NULL,
    ref_no VARCHAR(50) NULL,
    ref_date DATE NULL,
    narration VARCHAR(500) NULL,
    total_amount DECIMAL(15,2) NULL,
    source_doc_type VARCHAR(30) NULL,
    source_doc_id BIGINT NULL,
    is_auto_posted INT NULL DEFAULT 0,
    is_reversed INT NULL DEFAULT 0,
    reversed_by_voucher_id BIGINT NULL,
    reversal_of_voucher_id BIGINT NULL,
    status_id INT NULL,
    approval_level INT NULL,
    place_of_supply_state_code VARCHAR(5) NULL,
    branch_gstin VARCHAR(20) NULL,
    party_gstin VARCHAR(20) NULL,
    currency_id INT NULL,
    exchange_rate DECIMAL(12,6) NULL,
    approved_by INT NULL,
    approved_date_time DATETIME NULL,
    active INT NOT NULL DEFAULT 1,
    updated_by INT NOT NULL,
    updated_date_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (acc_voucher_id),
    INDEX idx_acc_voucher_co_id (co_id),
    INDEX idx_acc_voucher_branch_id (branch_id),
    INDEX idx_acc_voucher_type_id (acc_voucher_type_id),
    INDEX idx_acc_voucher_fy_id (acc_financial_year_id),
    INDEX idx_acc_voucher_voucher_no (voucher_no),
    INDEX idx_acc_voucher_voucher_date (voucher_date),
    INDEX idx_acc_voucher_party_id (party_id),
    INDEX idx_acc_voucher_source_doc_type (source_doc_type),
    INDEX idx_acc_voucher_source_doc_id (source_doc_id),
    INDEX idx_acc_voucher_status_id (status_id),
    CONSTRAINT fk_acc_voucher_type FOREIGN KEY (acc_voucher_type_id)
        REFERENCES acc_voucher_type (acc_voucher_type_id),
    CONSTRAINT fk_acc_voucher_fy FOREIGN KEY (acc_financial_year_id)
        REFERENCES acc_financial_year (acc_financial_year_id)
);

-- =============================================
-- Table: acc_voucher_line
-- =============================================
CREATE TABLE IF NOT EXISTS acc_voucher_line (
    acc_voucher_line_id BIGINT NOT NULL AUTO_INCREMENT,
    acc_voucher_id BIGINT NOT NULL,
    acc_ledger_id INT NOT NULL,
    dr_cr VARCHAR(1) NULL,
    amount DECIMAL(15,2) NULL,
    branch_id INT NULL,
    party_id INT NULL,
    narration VARCHAR(255) NULL,
    source_line_type VARCHAR(30) NULL,
    cost_center_id INT NULL,
    active INT NOT NULL DEFAULT 1,
    updated_by INT NOT NULL,
    updated_date_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (acc_voucher_line_id),
    INDEX idx_acc_voucher_line_voucher_id (acc_voucher_id),
    INDEX idx_acc_voucher_line_ledger_id (acc_ledger_id),
    INDEX idx_acc_voucher_line_branch_id (branch_id),
    INDEX idx_acc_voucher_line_party_id (party_id),
    INDEX idx_acc_voucher_line_cost_center_id (cost_center_id),
    CONSTRAINT fk_acc_voucher_line_voucher FOREIGN KEY (acc_voucher_id)
        REFERENCES acc_voucher (acc_voucher_id),
    CONSTRAINT fk_acc_voucher_line_ledger FOREIGN KEY (acc_ledger_id)
        REFERENCES acc_ledger (acc_ledger_id)
);

-- =============================================
-- Table: acc_voucher_gst
-- =============================================
CREATE TABLE IF NOT EXISTS acc_voucher_gst (
    acc_voucher_gst_id BIGINT NOT NULL AUTO_INCREMENT,
    acc_voucher_id BIGINT NOT NULL,
    acc_voucher_line_id BIGINT NULL,
    gst_type VARCHAR(20) NULL,
    supply_type VARCHAR(20) NULL,
    hsn_sac_code VARCHAR(20) NULL,
    taxable_amount DECIMAL(15,2) NULL,
    cgst_rate DECIMAL(5,2) NULL,
    cgst_amount DECIMAL(15,2) NULL,
    sgst_rate DECIMAL(5,2) NULL,
    sgst_amount DECIMAL(15,2) NULL,
    igst_rate DECIMAL(5,2) NULL,
    igst_amount DECIMAL(15,2) NULL,
    cess_rate DECIMAL(5,2) NULL,
    cess_amount DECIMAL(15,2) NULL,
    total_gst_amount DECIMAL(15,2) NULL,
    is_rcm INT NULL DEFAULT 0,
    itc_eligibility VARCHAR(20) NULL,
    active INT NOT NULL DEFAULT 1,
    updated_by INT NOT NULL,
    updated_date_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (acc_voucher_gst_id),
    INDEX idx_acc_voucher_gst_voucher_id (acc_voucher_id),
    INDEX idx_acc_voucher_gst_line_id (acc_voucher_line_id),
    CONSTRAINT fk_acc_voucher_gst_voucher FOREIGN KEY (acc_voucher_id)
        REFERENCES acc_voucher (acc_voucher_id),
    CONSTRAINT fk_acc_voucher_gst_line FOREIGN KEY (acc_voucher_line_id)
        REFERENCES acc_voucher_line (acc_voucher_line_id)
);

-- =============================================
-- Table: acc_bill_ref
-- =============================================
CREATE TABLE IF NOT EXISTS acc_bill_ref (
    acc_bill_ref_id BIGINT NOT NULL AUTO_INCREMENT,
    acc_voucher_id BIGINT NOT NULL,
    acc_voucher_line_id BIGINT NULL,
    ref_type VARCHAR(20) NULL,
    bill_no VARCHAR(50) NULL,
    bill_date DATE NULL,
    due_date DATE NULL,
    amount DECIMAL(15,2) NULL,
    status VARCHAR(20) NULL,
    active INT NOT NULL DEFAULT 1,
    updated_by INT NOT NULL,
    updated_date_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (acc_bill_ref_id),
    INDEX idx_acc_bill_ref_voucher_id (acc_voucher_id),
    INDEX idx_acc_bill_ref_line_id (acc_voucher_line_id),
    INDEX idx_acc_bill_ref_bill_no (bill_no),
    CONSTRAINT fk_acc_bill_ref_voucher FOREIGN KEY (acc_voucher_id)
        REFERENCES acc_voucher (acc_voucher_id),
    CONSTRAINT fk_acc_bill_ref_line FOREIGN KEY (acc_voucher_line_id)
        REFERENCES acc_voucher_line (acc_voucher_line_id)
);

-- =============================================
-- Table: acc_bill_settlement
-- =============================================
CREATE TABLE IF NOT EXISTS acc_bill_settlement (
    acc_bill_settlement_id BIGINT NOT NULL AUTO_INCREMENT,
    acc_bill_ref_id BIGINT NOT NULL,
    settled_against_bill_ref_id BIGINT NULL,
    settled_amount DECIMAL(15,2) NULL,
    settlement_date DATE NULL,
    active INT NOT NULL DEFAULT 1,
    updated_by INT NOT NULL,
    updated_date_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (acc_bill_settlement_id),
    INDEX idx_acc_bill_settlement_ref_id (acc_bill_ref_id),
    INDEX idx_acc_bill_settlement_against_id (settled_against_bill_ref_id),
    CONSTRAINT fk_acc_bill_settlement_ref FOREIGN KEY (acc_bill_ref_id)
        REFERENCES acc_bill_ref (acc_bill_ref_id),
    CONSTRAINT fk_acc_bill_settlement_against FOREIGN KEY (settled_against_bill_ref_id)
        REFERENCES acc_bill_ref (acc_bill_ref_id)
);

-- =============================================
-- Table: acc_voucher_numbering
-- =============================================
CREATE TABLE IF NOT EXISTS acc_voucher_numbering (
    acc_voucher_numbering_id INT NOT NULL AUTO_INCREMENT,
    co_id INT NOT NULL,
    acc_voucher_type_id INT NOT NULL,
    acc_financial_year_id INT NOT NULL,
    branch_id INT NULL,
    prefix VARCHAR(10) NULL,
    last_number INT NULL DEFAULT 0,
    active INT NOT NULL DEFAULT 1,
    updated_by INT NOT NULL,
    updated_date_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (acc_voucher_numbering_id),
    INDEX idx_acc_voucher_numbering_co_id (co_id),
    INDEX idx_acc_voucher_numbering_type_id (acc_voucher_type_id),
    INDEX idx_acc_voucher_numbering_fy_id (acc_financial_year_id),
    INDEX idx_acc_voucher_numbering_branch_id (branch_id),
    CONSTRAINT fk_acc_voucher_numbering_type FOREIGN KEY (acc_voucher_type_id)
        REFERENCES acc_voucher_type (acc_voucher_type_id),
    CONSTRAINT fk_acc_voucher_numbering_fy FOREIGN KEY (acc_financial_year_id)
        REFERENCES acc_financial_year (acc_financial_year_id)
);

-- =============================================
-- Table: acc_voucher_approval_log
-- =============================================
CREATE TABLE IF NOT EXISTS acc_voucher_approval_log (
    acc_voucher_approval_log_id BIGINT NOT NULL AUTO_INCREMENT,
    acc_voucher_id BIGINT NOT NULL,
    action VARCHAR(20) NULL,
    from_status_id INT NULL,
    to_status_id INT NULL,
    from_level INT NULL,
    to_level INT NULL,
    remarks VARCHAR(255) NULL,
    action_by INT NOT NULL,
    action_date_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    active INT NOT NULL DEFAULT 1,
    updated_by INT NOT NULL,
    updated_date_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (acc_voucher_approval_log_id),
    INDEX idx_acc_voucher_approval_log_voucher_id (acc_voucher_id),
    CONSTRAINT fk_acc_voucher_approval_log_voucher FOREIGN KEY (acc_voucher_id)
        REFERENCES acc_voucher (acc_voucher_id)
);

-- =============================================
-- Table: acc_voucher_warning
-- =============================================
CREATE TABLE IF NOT EXISTS acc_voucher_warning (
    acc_voucher_warning_id BIGINT NOT NULL AUTO_INCREMENT,
    acc_voucher_id BIGINT NOT NULL,
    warning_type VARCHAR(30) NULL,
    warning_message VARCHAR(500) NULL,
    severity VARCHAR(10) NULL,
    is_overridden INT NULL DEFAULT 0,
    overridden_by INT NULL,
    overridden_date_time DATETIME NULL,
    active INT NOT NULL DEFAULT 1,
    updated_by INT NOT NULL,
    updated_date_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (acc_voucher_warning_id),
    INDEX idx_acc_voucher_warning_voucher_id (acc_voucher_id),
    CONSTRAINT fk_acc_voucher_warning_voucher FOREIGN KEY (acc_voucher_id)
        REFERENCES acc_voucher (acc_voucher_id)
);

-- =============================================
-- Table: acc_opening_bill
-- =============================================
CREATE TABLE IF NOT EXISTS acc_opening_bill (
    acc_opening_bill_id BIGINT NOT NULL AUTO_INCREMENT,
    co_id INT NOT NULL,
    acc_ledger_id INT NOT NULL,
    acc_financial_year_id INT NOT NULL,
    bill_no VARCHAR(50) NULL,
    bill_date DATE NULL,
    due_date DATE NULL,
    bill_type VARCHAR(1) NULL,
    amount DECIMAL(15,2) NULL,
    pending_amount DECIMAL(15,2) NULL,
    status VARCHAR(20) NULL,
    active INT NOT NULL DEFAULT 1,
    updated_by INT NOT NULL,
    updated_date_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (acc_opening_bill_id),
    INDEX idx_acc_opening_bill_co_id (co_id),
    INDEX idx_acc_opening_bill_ledger_id (acc_ledger_id),
    INDEX idx_acc_opening_bill_fy_id (acc_financial_year_id),
    INDEX idx_acc_opening_bill_bill_no (bill_no),
    CONSTRAINT fk_acc_opening_bill_ledger FOREIGN KEY (acc_ledger_id)
        REFERENCES acc_ledger (acc_ledger_id),
    CONSTRAINT fk_acc_opening_bill_fy FOREIGN KEY (acc_financial_year_id)
        REFERENCES acc_financial_year (acc_financial_year_id)
);

-- =============================================
-- ROLLBACK: DROP TABLE IF EXISTS (in reverse order)
-- =============================================
-- DROP TABLE IF EXISTS acc_opening_bill;
-- DROP TABLE IF EXISTS acc_voucher_warning;
-- DROP TABLE IF EXISTS acc_voucher_approval_log;
-- DROP TABLE IF EXISTS acc_voucher_numbering;
-- DROP TABLE IF EXISTS acc_bill_settlement;
-- DROP TABLE IF EXISTS acc_bill_ref;
-- DROP TABLE IF EXISTS acc_voucher_gst;
-- DROP TABLE IF EXISTS acc_voucher_line;
-- DROP TABLE IF EXISTS acc_voucher;
-- DROP TABLE IF EXISTS acc_account_determination;
-- DROP TABLE IF EXISTS acc_period_lock;
-- DROP TABLE IF EXISTS acc_voucher_type;
-- DROP TABLE IF EXISTS acc_ledger;
-- DROP TABLE IF EXISTS acc_financial_year;
-- DROP TABLE IF EXISTS acc_ledger_group;
