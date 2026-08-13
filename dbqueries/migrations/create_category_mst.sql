-- Migration: Create category_mst table for Worker Category Master
-- Date: 2026-03-16 (updated 2026-08-13: added grade_id, updated_by now int,
--                   dropped unused auto_datetime_insert / user_id)

CREATE TABLE IF NOT EXISTS category_mst (
  `cata_id` bigint NOT NULL AUTO_INCREMENT,
  `cata_code` varchar(255) DEFAULT NULL,
  `cata_desc` varchar(255) DEFAULT NULL,
  `branch_id` int DEFAULT NULL,
  `updated_by` int DEFAULT NULL,
  `updated_date_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `grade_id` int DEFAULT NULL,
  PRIMARY KEY (`cata_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- For tenants that already have the old shape, run instead:
-- ALTER TABLE category_mst
--   ADD COLUMN `grade_id` int DEFAULT NULL,
--   MODIFY COLUMN `updated_by` int DEFAULT NULL,
--   DROP COLUMN `auto_datetime_insert`,
--   DROP COLUMN `user_id`;

-- Rollback:
-- DROP TABLE IF EXISTS category_mst;
