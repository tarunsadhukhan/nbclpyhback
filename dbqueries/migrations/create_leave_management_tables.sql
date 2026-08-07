-- Migration: create leave-management tables (present in sls, missing from dev3)
-- Target tenant DB: dev3
-- Tables: hrms_leave_types_mst, leave_transactions, leave_tran_details, leave_ledger_tran
-- DDL mirrored from sls. Reference data NOT copied (sls rows are company_id 1/2 specific).
--
-- ROLLBACK:
--   DROP TABLE IF EXISTS leave_tran_details;
--   DROP TABLE IF EXISTS leave_transactions;
--   DROP TABLE IF EXISTS leave_ledger_tran;
--   DROP TABLE IF EXISTS hrms_leave_types_mst;

CREATE TABLE IF NOT EXISTS `hrms_leave_types_mst` (
  `leave_type_id` bigint NOT NULL DEFAULT '0',
  `company_id` int DEFAULT NULL,
  `is_active` int DEFAULT NULL,
  `leave_type_code` varchar(255) CHARACTER SET latin1 DEFAULT NULL,
  `leave_type_description` varchar(255) CHARACTER SET latin1 DEFAULT NULL,
  `payable` varchar(255) CHARACTER SET latin1 DEFAULT NULL COMMENT 'Y OR N',
  `updated_by` bigint DEFAULT NULL,
  `updated_date_time` datetime DEFAULT NULL,
  `Leave_hours` double DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `leave_ledger_tran` (
  `leave_ledger_id` int NOT NULL AUTO_INCREMENT,
  `eb_id` int DEFAULT NULL,
  `leave_type_id` int DEFAULT NULL,
  `entitled_from_date` date DEFAULT NULL,
  `entitled_to_date` date DEFAULT NULL,
  `no_of_leaves_entitled` int DEFAULT NULL,
  `carry_forward` int DEFAULT NULL,
  PRIMARY KEY (`leave_ledger_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `leave_transactions` (
  `leave_transaction_id` bigint NOT NULL DEFAULT '0',
  `branch_id` int DEFAULT NULL,
  `eb_id` bigint DEFAULT NULL,
  `leave_from_date` date DEFAULT NULL,
  `leave_ledger_id` bigint DEFAULT NULL,
  `leave_purpose` varchar(255) CHARACTER SET latin1 DEFAULT NULL,
  `leave_to_date` date DEFAULT NULL,
  `leave_type_id` bigint DEFAULT NULL,
  `remarks` varchar(255) CHARACTER SET latin1 DEFAULT NULL,
  `status` varchar(255) CHARACTER SET latin1 DEFAULT NULL,
  `updated_by` bigint DEFAULT NULL,
  `updated_date_time` datetime DEFAULT NULL,
  `non_working_days` int DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `leave_tran_details` (
  `lvd_tran_id` bigint NOT NULL DEFAULT '0',
  `leave_date` date DEFAULT NULL,
  `ltran_id` bigint DEFAULT NULL,
  `auto_datetime_insert` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `created_by` varchar(20) CHARACTER SET latin1 DEFAULT NULL,
  `company_id` int DEFAULT NULL,
  `is_active` int DEFAULT '1'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
