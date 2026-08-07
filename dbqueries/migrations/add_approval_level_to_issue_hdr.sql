-- Add approval_level column to issue_hdr for approval workflow support
-- This column tracks which approval level the document is currently at (used when status_id = 20)

ALTER TABLE issue_hdr
ADD COLUMN approval_level INT NULL DEFAULT NULL AFTER status_id;

-- Rollback: ALTER TABLE issue_hdr DROP COLUMN approval_level;
