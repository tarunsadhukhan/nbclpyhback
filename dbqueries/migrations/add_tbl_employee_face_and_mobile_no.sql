-- Migration: Create hrms_employee_face table and add mobile_no to hrms_ed_personal_details
-- Date: 2025-07-11 (updated 2026-03-15)
-- Applied to: dev3

-- 1. Drop legacy table if exists
DROP TABLE IF EXISTS tbl_employee_face;

-- 2. Create hrms_employee_face table for employee photo storage
-- branch_id references branch_mst(branch_id) with FK constraint
CREATE TABLE IF NOT EXISTS hrms_employee_face (
    face_id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    eb_id BIGINT NOT NULL,
    face_image LONGBLOB,
    face_image_type_id INT DEFAULT NULL,
    file_name VARCHAR(255) DEFAULT NULL,
    file_extension VARCHAR(10) DEFAULT NULL,
    branch_id INT NOT NULL,
    updated_by INT DEFAULT NULL,
    updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_eb_id (eb_id),
    INDEX idx_branch_id (branch_id),
    CONSTRAINT fk_employee_face_branch FOREIGN KEY (branch_id) REFERENCES branch_mst(branch_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 3. Add mobile_no column to hrms_ed_personal_details (before email_id, after blood_group)
ALTER TABLE hrms_ed_personal_details
ADD COLUMN mobile_no VARCHAR(15) DEFAULT NULL
AFTER blood_group;

-- Rollback:
-- DROP TABLE IF EXISTS hrms_employee_face;
-- ALTER TABLE hrms_ed_personal_details DROP COLUMN mobile_no;
