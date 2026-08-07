-- Migration: Create e_invoice_responses audit table for GST portal submission tracking
-- Date: 2026-04-01
-- Rollback: DROP TABLE e_invoice_responses;

CREATE TABLE e_invoice_responses (
    e_invoice_response_id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    invoice_id BIGINT NOT NULL,
    co_id BIGINT NOT NULL,
    submission_status VARCHAR(50) NOT NULL COMMENT 'Draft/Submitted/Accepted/Rejected/Error',
    submitted_date_time DATETIME NOT NULL,
    api_response_json LONGTEXT NULL COMMENT 'Full JSON response from e-invoice API',
    irn_from_response VARCHAR(255) NULL COMMENT 'IRN extracted if accepted',
    error_message VARCHAR(500) NULL COMMENT 'Error if submission failed',
    submitted_by BIGINT NULL,
    created_date_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_e_invoice_responses_invoice FOREIGN KEY (invoice_id) REFERENCES sales_invoice(invoice_id),
    CONSTRAINT fk_e_invoice_responses_company FOREIGN KEY (co_id) REFERENCES co_mst(co_id),
    CONSTRAINT fk_e_invoice_responses_user FOREIGN KEY (submitted_by) REFERENCES user_mst(user_id),

    INDEX idx_invoice_date (invoice_id, submitted_date_time DESC),
    INDEX idx_co_id (co_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ROLLBACK:
-- DROP TABLE e_invoice_responses;
