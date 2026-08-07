-- Migration: Add photo columns to hrms_ed_personal_details
-- Moves photo storage from hrms_employee_face into the personal details table
-- Run against TENANT database (e.g. dev3)
-- Date: 2026-03-16

ALTER TABLE hrms_ed_personal_details
  ADD COLUMN face_image LONGBLOB NULL AFTER co_id,
  ADD COLUMN file_name VARCHAR(255) NULL AFTER face_image,
  ADD COLUMN file_extension VARCHAR(10) NULL AFTER file_name;

-- Migrate existing photos from hrms_employee_face
UPDATE hrms_ed_personal_details p
INNER JOIN hrms_employee_face f ON f.eb_id = p.eb_id
SET p.face_image = f.face_image,
    p.file_name = f.file_name,
    p.file_extension = f.file_extension;

-- ROLLBACK:
-- ALTER TABLE hrms_ed_personal_details
--   DROP COLUMN face_image,
--   DROP COLUMN file_name,
--   DROP COLUMN file_extension;
