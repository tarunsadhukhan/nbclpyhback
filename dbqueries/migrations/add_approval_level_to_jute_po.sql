-- Add approval_level column to jute_po for multi-level approval support
-- This enables the shared approval utility (src/common/approval_utils.py) to track
-- which approval level the Jute PO is currently at during the approval workflow.
ALTER TABLE jute_po ADD COLUMN approval_level INT NULL DEFAULT NULL;

-- Rollback: ALTER TABLE jute_po DROP COLUMN approval_level;
