-- Migration: Create grade_table for Grade Master (HRMS)
-- Date: 2026-08-13
-- grade_type: 0 = Worker, 1 = Staff

CREATE TABLE IF NOT EXISTS grade_table (
  `grade_id` int NOT NULL AUTO_INCREMENT,
  `grade_code` varchar(4) DEFAULT NULL,
  `grade_name` varchar(100) DEFAULT NULL,
  `grade_type` int DEFAULT '0',
  PRIMARY KEY (`grade_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Rollback:
-- DROP TABLE IF EXISTS grade_table;
