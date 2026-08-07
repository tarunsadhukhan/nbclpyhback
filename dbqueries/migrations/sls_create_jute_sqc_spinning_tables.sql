-- Migration: create Jute SQC spinning tables in sls tenant (schema copied from dev3)
-- Target DB: sls
-- Schema only -- no data (dev3 rows are QA/test data, tables are co_id-scoped transactional)
-- Rollback:
--   DROP TABLE IF EXISTS jute_sqc_spinning_count;
--   DROP TABLE IF EXISTS jute_sqc_spinning_entry;
--   DROP TABLE IF EXISTS jute_sqc_spinning_rhmr;

CREATE TABLE IF NOT EXISTS `jute_sqc_spinning_count` (
  `spinning_sqc_count_id` int NOT NULL AUTO_INCREMENT,
  `co_id` int NOT NULL,
  `branch_id` int DEFAULT NULL,
  `entry_date` date NOT NULL,
  `spell_id` int DEFAULT NULL,
  `mc_id` int DEFAULT NULL,
  `item_id` int DEFAULT NULL,
  `dp` decimal(10,3) DEFAULT NULL,
  `tp` decimal(10,3) DEFAULT NULL,
  `wt_450_gms` decimal(10,3) DEFAULT NULL,
  `mr_pct` decimal(5,2) DEFAULT NULL,
  `observed_count` decimal(10,3) NOT NULL DEFAULT '0.000',
  `corrected_count` decimal(10,3) DEFAULT NULL,
  `active` tinyint(1) NOT NULL DEFAULT '1',
  `updated_by` int DEFAULT NULL,
  `updated_date_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`spinning_sqc_count_id`),
  KEY `idx_jssc_avg` (`co_id`,`item_id`,`entry_date`),
  KEY `idx_jssc_co_date` (`co_id`,`entry_date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `jute_sqc_spinning_entry` (
  `spinning_sqc_entry_id` int NOT NULL AUTO_INCREMENT,
  `co_id` int NOT NULL,
  `branch_id` int DEFAULT NULL,
  `entry_date` date NOT NULL,
  `mc_id` int NOT NULL,
  `item_id` int DEFAULT NULL,
  `actual_speed` decimal(10,2) DEFAULT NULL,
  `actual_tpi` decimal(10,3) DEFAULT NULL,
  `active` tinyint(1) NOT NULL DEFAULT '1',
  `updated_by` int DEFAULT NULL,
  `updated_date_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`spinning_sqc_entry_id`),
  KEY `idx_jsse_lookup` (`co_id`,`mc_id`,`item_id`,`entry_date`),
  KEY `idx_jsse_co_date` (`co_id`,`entry_date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `jute_sqc_spinning_rhmr` (
  `spinning_sqc_rhmr_id` int NOT NULL AUTO_INCREMENT,
  `co_id` int NOT NULL,
  `branch_id` int DEFAULT NULL,
  `entry_date` date NOT NULL,
  `spell_id` int NOT NULL,
  `temperature` decimal(5,1) DEFAULT NULL,
  `humidity` decimal(5,1) DEFAULT NULL,
  `active` tinyint(1) NOT NULL DEFAULT '1',
  `updated_by` int DEFAULT NULL,
  `updated_date_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`spinning_sqc_rhmr_id`),
  KEY `idx_jssr_lookup` (`co_id`,`entry_date`,`spell_id`),
  KEY `idx_jssr_co_date` (`co_id`,`entry_date`),
  KEY `idx_jssr_spell` (`spell_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
