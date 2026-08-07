-- Migration: Replace co_id with branch_id in hrms_ed_personal_details
-- Date: 2025-07-15
-- Description: Remove co_id column and add branch_id column.
--              Existing rows get branch_id from hrms_ed_official_details if available,
--              otherwise from the first branch of their company.

-- Step 1: Add branch_id column (nullable initially for data migration)
ALTER TABLE hrms_ed_personal_details
  ADD COLUMN branch_id INT NULL AFTER aadhar_no;

-- Step 2: Populate branch_id from official details where available
UPDATE hrms_ed_personal_details p
  JOIN hrms_ed_official_details o ON o.eb_id = p.eb_id AND o.active = 1
SET p.branch_id = o.branch_id
WHERE o.branch_id IS NOT NULL;

-- Step 3: For any remaining rows without branch_id, set from the first active branch of their company
UPDATE hrms_ed_personal_details p
  JOIN branch_mst b ON b.co_id = p.co_id AND b.active = 1
SET p.branch_id = b.branch_id
WHERE p.branch_id IS NULL;

-- Step 4: Make branch_id NOT NULL after data migration
ALTER TABLE hrms_ed_personal_details
  MODIFY COLUMN branch_id INT NOT NULL;

-- Step 5: Drop co_id column
ALTER TABLE hrms_ed_personal_details
  DROP COLUMN co_id;

-- Rollback (if needed):
-- ALTER TABLE hrms_ed_personal_details ADD COLUMN co_id BIGINT NOT NULL AFTER aadhar_no;
-- UPDATE hrms_ed_personal_details p JOIN branch_mst b ON b.branch_id = p.branch_id SET p.co_id = b.co_id;
-- ALTER TABLE hrms_ed_personal_details DROP COLUMN branch_id;
