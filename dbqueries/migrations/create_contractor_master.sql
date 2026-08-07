-- Migration: Create contractor_mst table
-- Database: dev3 (tenant DB)
-- Date: 2026-03-16

CREATE TABLE `contractor_mst` (
  `cont_id` int NOT NULL AUTO_INCREMENT,
  `address_1` varchar(255) DEFAULT NULL,
  `address_2` varchar(255) DEFAULT NULL,
  `address_3` varchar(255) DEFAULT NULL,
  `bank_acc_no` varchar(255) DEFAULT NULL,
  `bank_name` varchar(25) DEFAULT NULL,
  `ifsc_code` varchar(25) DEFAULT NULL,
  `branch_id` int DEFAULT NULL,
  `email_id` varchar(255) DEFAULT NULL,
  `esi_code` varchar(25) DEFAULT NULL,
  `contractor_name` varchar(50) DEFAULT NULL,
  `aadhar_no` varchar(20) DEFAULT NULL,
  `pan_no` varchar(25) DEFAULT NULL,
  `pf_code` varchar(25) DEFAULT NULL,
  `phone_no` varchar(255) DEFAULT NULL,
  `date_of_registration` date DEFAULT NULL,
  `date_of_registration_mill` date DEFAULT NULL,
  `updated_by` int DEFAULT NULL,
  `updated_date_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`cont_id`)
);

-- Rollback:
-- DROP TABLE IF EXISTS `contractor_mst`;
