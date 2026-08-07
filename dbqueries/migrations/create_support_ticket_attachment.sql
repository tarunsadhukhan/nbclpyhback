-- Migration: Support Ticket attachments (screenshots + documents)
-- Date: 2026-06-22
-- Target DB: vowconsole3 (central console DB — NOT a tenant DB)
-- Description:
--   Adds attachment support to the support-ticket system. Files (images +
--   documents) are stored in S3 via the shared attachments S3 client; this
--   table holds the per-file metadata, linked to support_ticket.
--   Depends on create_support_ticket_tables.sql having run first.

CREATE TABLE IF NOT EXISTS support_ticket_attachment (
    attachment_id       INT PRIMARY KEY AUTO_INCREMENT,
    ticket_id           INT NOT NULL,
    kind                VARCHAR(20) NOT NULL,          -- image | document
    s3_bucket           VARCHAR(120) NOT NULL,
    s3_key              VARCHAR(500) NOT NULL,
    original_filename   VARCHAR(255) NULL,
    mime_type           VARCHAR(100) NULL,
    size_bytes          BIGINT NULL,
    uploaded_by_type    VARCHAR(20) NOT NULL,          -- reporter | vow
    uploaded_by_id      INT NULL,
    uploaded_by_name    VARCHAR(120) NULL,
    uploaded_at         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    active              INT NOT NULL DEFAULT 1,
    INDEX idx_support_ticket_attachment_ticket (ticket_id),
    CONSTRAINT fk_support_ticket_attachment_ticket
        FOREIGN KEY (ticket_id) REFERENCES support_ticket (ticket_id)
);

-- ===== Rollback (manual) =====
-- DROP TABLE IF EXISTS support_ticket_attachment;
