-- =============================================================================
-- Migration: create file_attachment table
-- Purpose:   Generic per-tenant attachment metadata for S3-backed file uploads.
--            First consumer: Jute Bill Pass invoice + challan PDF uploads.
--            Reusable for other modules via the `module` column.
-- Target:    Each tenant database (dev3, sls, org1, etc.) — NOT vowconsole3.
-- Date:      2026-05-23
-- =============================================================================

CREATE TABLE IF NOT EXISTS file_attachment (
    attachment_id      INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    co_id              INT NOT NULL,
    module             VARCHAR(50) NOT NULL,
    entity_id          INT NOT NULL,
    file_type          VARCHAR(50) NOT NULL,
    s3_bucket          VARCHAR(100) NOT NULL,
    s3_key             VARCHAR(500) NOT NULL,
    original_filename  VARCHAR(255) NULL,
    mime_type          VARCHAR(100) NULL,
    size_bytes         BIGINT NULL,
    uploaded_by        INT NULL,
    uploaded_at        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    active             TINYINT NOT NULL DEFAULT 1,
    INDEX idx_lookup (module, entity_id, file_type, active),
    INDEX idx_co (co_id)
);

-- =============================================================================
-- ROLLBACK
-- DROP TABLE IF EXISTS file_attachment;
-- =============================================================================
