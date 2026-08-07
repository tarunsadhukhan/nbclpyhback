-- Migration: Create category_mst table for Worker Category Master
-- Date: 2026-03-16

CREATE TABLE IF NOT EXISTS category_mst (
  `cata_id` bigint NOT NULL AUTO_INCREMENT,
  `auto_datetime_insert` datetime DEFAULT CURRENT_TIMESTAMP,
  `cata_code` varchar(255) DEFAULT NULL,
  `cata_desc` varchar(255) DEFAULT NULL,
  `branch_id` int DEFAULT NULL,
  `updated_by` varchar(255) DEFAULT NULL,
  `updated_date_time` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `user_id` int DEFAULT NULL,
  PRIMARY KEY (`cata_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Rollback:
-- DROP TABLE IF EXISTS category_mst;
