-- Add approval_level column to jute_mr for multi-level approval support
-- This enables the shared approval utility (src/common/approval_utils.py) to track
-- which approval level the MR is currently at during the approval workflow.
ALTER TABLE jute_mr ADD COLUMN approval_level INT NULL DEFAULT NULL;

-- Rollback: ALTER TABLE jute_mr DROP COLUMN approval_level;
