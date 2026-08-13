-- Add pension number/date (PF) and ESI joining date to the employee
-- "Medical Enrollments, ESI, PF" step.
--
-- Rollback:
--   ALTER TABLE hrms_ed_pf DROP COLUMN pension_no, DROP COLUMN pension_date;
--   ALTER TABLE hrms_ed_esi DROP COLUMN esi_date;

ALTER TABLE hrms_ed_pf
  ADD COLUMN pension_no VARCHAR(10) NULL AFTER relationship_name,
  ADD COLUMN pension_date DATE NULL AFTER pension_no;

ALTER TABLE hrms_ed_esi
  ADD COLUMN esi_date DATE NULL AFTER medical_policy_no;
