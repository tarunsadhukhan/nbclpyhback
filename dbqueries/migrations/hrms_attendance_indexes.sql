-- Indexes for the large attendance / HRMS / payroll tables, chosen from the WHERE/JOIN
-- columns the backend actually uses (src/hrms/*, src/mobileapp/*).
-- One ALTER per table so each table is rebuilt once. InnoDB builds these online
-- (reads and writes continue), but run off-peak: paywages is ~175 MB.
-- Not re-runnable: MySQL has no ADD INDEX IF NOT EXISTS, a second run fails on duplicate key name.
-- Rollback: ALTER TABLE <table> DROP INDEX <index_name>;

-- daily_attendance (72 query sites): list/report screens filter branch + date range + is_active.
-- eb_id + date is already covered by idx_da_dedupe.
ALTER TABLE `daily_attendance`
  ADD INDEX `idx_da_branch_date` (`branch_id`, `attendance_date`, `is_active`);

-- pay_attendance (PK only): wages process filters branch + date range, then groups by eb_id.
ALTER TABLE `pay_attendance`
  ADD INDEX `idx_pa_branch_date_eb` (`branch_id`, `attendance_date`, `eb_id`),
  ADD INDEX `idx_pa_eb_date` (`eb_id`, `attendance_date`);

-- paywages: loan screens sum per employee up to a date (ECode = ? AND EDate < ?).
ALTER TABLE `paywages`
  ADD INDEX `idx_paywages_ecode_edate` (`ECode`, `EDate`);

-- hrms_ed_official_details: employee lookup by legacy code (attendance, leave, loans, wages joins).
ALTER TABLE `hrms_ed_official_details`
  ADD INDEX `idx_hrms_official_emp_code` (`emp_code`, `branch_id`);

-- bio_attendance_table: processing reads punches per employee over a date window.
ALTER TABLE `bio_attendance_table`
  ADD INDEX `idx_bio_att_eb_date` (`eb_id`, `log_date`);

-- leave_transactions / leave_tran_details: no indexes at all today.
ALTER TABLE `leave_transactions`
  ADD INDEX `idx_leave_tran_id` (`leave_transaction_id`),
  ADD INDEX `idx_leave_tran_eb_from` (`eb_id`, `leave_from_date`),
  ADD INDEX `idx_leave_tran_branch_status` (`branch_id`, `status`);

ALTER TABLE `leave_tran_details`
  ADD INDEX `idx_leave_dtl_ltran` (`ltran_id`),
  ADD INDEX `idx_leave_dtl_date` (`leave_date`, `is_active`);

-- Payroll tables (PK only): always read by pay period + pay scheme, then per employee.
ALTER TABLE `pay_employee_payroll`
  ADD INDEX `idx_pay_payroll_period_scheme_emp` (`PAYPERIOD_ID`, `PAYSCHEME_ID`, `EMPLOYEEID`);

ALTER TABLE `pay_employee_payperiod`
  ADD INDEX `idx_pay_payperiod_period_scheme_emp` (`PAY_PERIOD_ID`, `PAY_SCHEME_ID`, `EMPLOYEEID`);

ALTER TABLE `pay_employee_structure`
  ADD INDEX `idx_pay_structure_scheme_emp` (`PAYSCHEME_ID`, `EMPLOYEEID`);

ALTER TABLE `pay_employee_payscheme`
  ADD INDEX `idx_pay_emp_scheme_scheme` (`PAY_SCHEME_ID`, `STATUS`, `EMPLOYEEID`),
  ADD INDEX `idx_pay_emp_scheme_emp` (`EMPLOYEEID`);

ALTER TABLE `pay_components_custom`
  ADD INDEX `idx_pay_comp_custom_period` (`PAY_PERIOD_ID`, `STATUS`),
  ADD INDEX `idx_pay_comp_custom_emp` (`EMPLOYEEID`);

-- hrms_holiday_transactions: joined to holiday_master by holiday_id, grouped per employee.
ALTER TABLE `hrms_holiday_transactions`
  ADD INDEX `idx_hrms_holiday_tran_holiday_eb` (`holiday_id`, `eb_id`);
