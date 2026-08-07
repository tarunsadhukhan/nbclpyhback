-- Migration: Make all updated_date_time columns TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
-- Run against TENANT database (e.g. dev3, sls)
-- Date: 2026-03-16
--
-- Rollback: Change each column back to DATETIME NULL (comment at bottom)

-- ═══════════════════════════════════════════════════════════════════
-- HRMS Tables
-- ═══════════════════════════════════════════════════════════════════

-- First, backfill any NULL values so NOT NULL constraint doesn't fail
UPDATE hrms_ed_personal_details SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE hrms_ed_personal_details MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE hrms_ed_address_details SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE hrms_ed_address_details MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE hrms_ed_bank_details SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE hrms_ed_bank_details MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE hrms_ed_contact_details SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE hrms_ed_contact_details MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE hrms_ed_official_details SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE hrms_ed_official_details MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE hrms_ed_pf SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE hrms_ed_pf MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE hrms_ed_esi SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE hrms_ed_esi MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE hrms_ed_resign_details SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE hrms_ed_resign_details MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE hrms_experience_details SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE hrms_experience_details MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE hrms_blood_group SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE hrms_blood_group MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE hrms_employee_face SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE hrms_employee_face MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

-- ═══════════════════════════════════════════════════════════════════
-- Pay Tables
-- ═══════════════════════════════════════════════════════════════════

UPDATE pay_company_components SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE pay_company_components MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE pay_components SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE pay_components MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE pay_components_custom SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE pay_components_custom MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE pay_custemp_components_custom SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE pay_custemp_components_custom MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE pay_customer_employee_payroll SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE pay_customer_employee_payroll MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE pay_customer_employee_payscheme SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE pay_customer_employee_payscheme MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE pay_customer_employee_period SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE pay_customer_employee_period MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE pay_customer_employee_structure SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE pay_customer_employee_structure MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE pay_employee_payperiod SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE pay_employee_payperiod MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE pay_employee_payroll SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE pay_employee_payroll MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE pay_employee_payroll_status SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE pay_employee_payroll_status MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE pay_employee_payroll_status_log SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE pay_employee_payroll_status_log MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE pay_employee_payscheme SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE pay_employee_payscheme MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE pay_employee_structure SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE pay_employee_structure MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE pay_external_components SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE pay_external_components MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE pay_generic SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE pay_generic MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE pay_period SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE pay_period MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE pay_period_status SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE pay_period_status MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE pay_report SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE pay_report MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE pay_report_combinations SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE pay_report_combinations MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE pay_scheme SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE pay_scheme MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE pay_scheme_details SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE pay_scheme_details MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE pay_wages_mode SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE pay_wages_mode MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE pay_register SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE pay_register MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE pay_holiday_wage_pay_register SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE pay_holiday_wage_pay_register MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE pay_scheme_parameter_category SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE pay_scheme_parameter_category MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE pay_processed_payscheme SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE pay_processed_payscheme MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE pay_seq_payroll SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE pay_seq_payroll MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE pay_scheme_master SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE pay_scheme_master MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE pay_slip SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE pay_slip MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE pay_slip_components SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE pay_slip_components MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE pay_slip_parameters SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE pay_slip_parameters MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE pay_cm_job_payment_links SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE pay_cm_job_payment_links MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

-- ═══════════════════════════════════════════════════════════════════
-- Master Tables (tenant DB)
-- ═══════════════════════════════════════════════════════════════════

UPDATE approval_mst SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE approval_mst MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE branch_mst SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE branch_mst MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE co_mst SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE co_mst MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE cost_factor_mst SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE cost_factor_mst MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE country_mst SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE country_mst MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE currency_mst SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE currency_mst MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE dept_mst SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE dept_mst MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE designation_mst SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE designation_mst MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE entity_type_mst SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE entity_type_mst MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE expense_type_mst SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE expense_type_mst MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE item_grp_mst SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE item_grp_mst MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE item_minmax_mst SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE item_minmax_mst MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE item_mst SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE item_mst MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE machine_mst SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE machine_mst MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE machine_type_mst SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE machine_type_mst MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE menu_mst SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE menu_mst MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE menu_type_mst SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE menu_type_mst MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE module_mst SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE module_mst MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE party_branch_mst SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE party_branch_mst MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE party_mst SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE party_mst MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE party_type_mst SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE party_type_mst MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE project_mst SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE project_mst MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE roles_mst SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE roles_mst MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE state_mst SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE state_mst MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE status_mst SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE status_mst MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE sub_dept_mst SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE sub_dept_mst MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE tax_mst SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE tax_mst MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE tax_type_mst SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE tax_type_mst MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE tds_mst SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE tds_mst MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE uom_item_map_mst SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE uom_item_map_mst MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE uom_mst SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE uom_mst MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE user_mst SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE user_mst MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE warehouse_mst SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE warehouse_mst MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE additional_charges_mst SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE additional_charges_mst MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

-- ═══════════════════════════════════════════════════════════════════
-- Inventory Tables (tenant DB)
-- ═══════════════════════════════════════════════════════════════════

UPDATE issue_hdr SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE issue_hdr MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE issue_li SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE issue_li MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

-- ═══════════════════════════════════════════════════════════════════
-- Portal Tables (tenant DB)
-- ═══════════════════════════════════════════════════════════════════

UPDATE user_role_map SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE user_role_map MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE approval_mst SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE approval_mst MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

-- ═══════════════════════════════════════════════════════════════════
-- Jute Tables (tenant DB) — only the 2 that were nullable without default
-- ═══════════════════════════════════════════════════════════════════

UPDATE jute_mr SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE jute_mr MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE jute_mr_li SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE jute_mr_li MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

-- ═══════════════════════════════════════════════════════════════════
-- Procurement Tables (tenant DB) — only the 2 that were missing default
-- ═══════════════════════════════════════════════════════════════════

UPDATE proc_inward SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE proc_inward MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

UPDATE proc_po_dtl SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
ALTER TABLE proc_po_dtl MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;


-- ═══════════════════════════════════════════════════════════════════
-- Console DB Tables (run against vowconsole3)
-- ═══════════════════════════════════════════════════════════════════
-- NOTE: Run these against the vowconsole3 database, NOT the tenant DB

-- UPDATE con_user_master SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
-- ALTER TABLE con_user_master MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

-- UPDATE con_org_master SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
-- ALTER TABLE con_org_master MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

-- UPDATE con_role_master SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
-- ALTER TABLE con_role_master MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

-- UPDATE con_user_role_mapping SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
-- ALTER TABLE con_user_role_mapping MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

-- UPDATE co_config SET updated_date_time = NOW() WHERE updated_date_time IS NULL;
-- ALTER TABLE co_config MODIFY COLUMN updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;


-- ═══════════════════════════════════════════════════════════════════
-- ROLLBACK (if needed, run each line individually):
-- ═══════════════════════════════════════════════════════════════════
-- ALTER TABLE <table_name> MODIFY COLUMN updated_date_time DATETIME NULL;
