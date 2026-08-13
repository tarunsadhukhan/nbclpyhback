-- Migration: Add voter_card_no to hrms_ed_personal_details
-- Run against TENANT database (e.g. dev3)
-- Date: 2026-08-13

ALTER TABLE hrms_ed_personal_details
  ADD COLUMN voter_card_no VARCHAR(20) NULL AFTER aadhar_no;

-- ROLLBACK:
-- ALTER TABLE hrms_ed_personal_details DROP COLUMN voter_card_no;
