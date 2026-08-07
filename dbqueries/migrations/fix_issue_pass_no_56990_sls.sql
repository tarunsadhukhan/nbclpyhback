-- One-off DATA fix for tenant 'sls' ONLY. This is NOT a schema migration (no DDL).
--
-- Bug: the new app numbered draft consumption issue_id 56990 (branch 29,
-- FY2026-27) as 8901. It took the GLOBAL MAX(issue_pass_no)=8900 for the branch
-- (a stale FY2023-24 row, issue_id 36942 dated 2024-03-31) and added 1, instead
-- of scoping to the issue's own financial year.
--
-- Branch 29 FY2026-27 (2026-04-01 .. 2027-03-31) already holds issue_pass_no
-- 1..34 (issue_id 56736..56769), so the correct next number is 35. 35 is free.
--
-- The code fix (src/inventory/query.py get_max_issue_pass_no_for_branch +
-- src/inventory/issue.py create_issue) prevents recurrence; this corrects the
-- single already-written draft row.
--
-- The WHERE clause pins the exact row, the current wrong value, the draft status
-- and the branch, so re-running this (or running it against the wrong DB) is a
-- harmless no-op.

UPDATE issue_hdr
SET issue_pass_no = 35
WHERE issue_id = 56990
  AND issue_pass_no = 8901
  AND status_id = 21
  AND branch_id = 29;

-- Expected: 1 row affected.

-- ROLLBACK (only if needed; restores the buggy value):
-- UPDATE issue_hdr SET issue_pass_no = 8901
-- WHERE issue_id = 56990 AND issue_pass_no = 35 AND status_id = 21 AND branch_id = 29;
