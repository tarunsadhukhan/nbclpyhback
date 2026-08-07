-- Migration: jute production + jute SQC tables/views  dev3 -> sls
-- Structure only (no data). 49 tables + 4 views.
-- Generated from dev3 via SHOW CREATE. Idempotent (IF NOT EXISTS / CREATE OR REPLACE).
-- ROLLBACK (views first, then tables):
--   DROP VIEW IF EXISTS vw_spinning_planning_grid;
--   DROP VIEW IF EXISTS vw_winding_daily_reconciled;
--   DROP VIEW IF EXISTS vw_weaving_daily;
--   DROP VIEW IF EXISTS vw_weaving_pick_act;
--   DROP TABLE IF EXISTS jute_draw_quality_std;
--   DROP TABLE IF EXISTS jute_prod_beaming_daily;
--   DROP TABLE IF EXISTS jute_prod_beaming_target_map;
--   DROP TABLE IF EXISTS jute_prod_bm_quality;
--   DROP TABLE IF EXISTS jute_prod_bm_quality_dtl;
--   DROP TABLE IF EXISTS jute_prod_finishing_daily;
--   DROP TABLE IF EXISTS jute_prod_finishing_daily_param;
--   DROP TABLE IF EXISTS jute_prod_finishing_quality;
--   DROP TABLE IF EXISTS jute_prod_finishing_target_map;
--   DROP TABLE IF EXISTS jute_prod_spng_target_map;
--   DROP TABLE IF EXISTS jute_prod_stoppage_hours;
--   DROP TABLE IF EXISTS jute_prod_weaving_beam_map;
--   DROP TABLE IF EXISTS jute_prod_weaving_daily;
--   DROP TABLE IF EXISTS jute_prod_weaving_quality;
--   DROP TABLE IF EXISTS jute_prod_weaving_quality_dtl;
--   DROP TABLE IF EXISTS jute_prod_weaving_quality_map;
--   DROP TABLE IF EXISTS jute_prod_weaving_target_map;
--   DROP TABLE IF EXISTS jute_prod_winding_daily_qlty;
--   DROP TABLE IF EXISTS jute_prod_winding_doff;
--   DROP TABLE IF EXISTS jute_prod_winding_jugar;
--   DROP TABLE IF EXISTS jute_spreader_quality_attr;
--   DROP TABLE IF EXISTS jute_sqc_bag_check;
--   DROP TABLE IF EXISTS jute_sqc_bag_check_dtl;
--   DROP TABLE IF EXISTS jute_sqc_bag_weight;
--   DROP TABLE IF EXISTS jute_sqc_beam_mr;
--   DROP TABLE IF EXISTS jute_sqc_breaker_card_swt;
--   DROP TABLE IF EXISTS jute_sqc_card_sliver_wt;
--   DROP TABLE IF EXISTS jute_sqc_cutting_length;
--   DROP TABLE IF EXISTS jute_sqc_draw_sliver_wt;
--   DROP TABLE IF EXISTS jute_sqc_emulsion;
--   DROP TABLE IF EXISTS jute_sqc_fabric_construction;
--   DROP TABLE IF EXISTS jute_sqc_fabric_construction_dtl;
--   DROP TABLE IF EXISTS jute_sqc_fabric_fault;
--   DROP TABLE IF EXISTS jute_sqc_fin_draw_sliver_wt;
--   DROP TABLE IF EXISTS jute_sqc_humidity;
--   DROP TABLE IF EXISTS jute_sqc_morrah_wt;
--   DROP TABLE IF EXISTS jute_sqc_packing_mr;
--   DROP TABLE IF EXISTS jute_sqc_qr_cv_15a;
--   DROP TABLE IF EXISTS jute_sqc_qr_cv_15a_dtl;
--   DROP TABLE IF EXISTS jute_sqc_spinning_qr_cv;
--   DROP TABLE IF EXISTS jute_sqc_spinning_qr_cv_dtl;
--   DROP TABLE IF EXISTS jute_sqc_spreader_roll_wt;
--   DROP TABLE IF EXISTS jute_sqc_spreader_sliver_wt;
--   DROP TABLE IF EXISTS jute_sqc_stitch;
--   DROP TABLE IF EXISTS jute_sqc_weaving_pick;
--   DROP TABLE IF EXISTS jute_sqc_width_picks;
--   DROP TABLE IF EXISTS jute_sqc_width_picks_dtl;
--   DROP TABLE IF EXISTS jute_sqc_yarn_tpi;
--   DROP TABLE IF EXISTS jute_sqc_yarn_tpi_dtl;

SET FOREIGN_KEY_CHECKS=0;

CREATE TABLE IF NOT EXISTS `jute_draw_quality_std` (
  `draw_quality_std_id` int NOT NULL AUTO_INCREMENT,
  `co_id` int NOT NULL,
  `item_id` int NOT NULL,
  `process` varchar(30) NOT NULL,
  `std_mr_pct` decimal(5,2) DEFAULT NULL,
  `std_cv_low` decimal(5,2) DEFAULT NULL,
  `std_cv_high` decimal(5,2) DEFAULT NULL,
  `std_weight` decimal(10,3) DEFAULT NULL,
  `std_wt_tol` decimal(10,3) DEFAULT NULL,
  `active` int NOT NULL DEFAULT '1',
  `updated_by` int DEFAULT NULL,
  `updated_date_time` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`draw_quality_std_id`),
  KEY `idx_jdqs_item_process` (`item_id`,`process`),
  KEY `idx_jdqs_co_id` (`co_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `jute_prod_beaming_daily` (
  `beaming_daily_id` int NOT NULL AUTO_INCREMENT,
  `co_id` int NOT NULL,
  `branch_id` int DEFAULT NULL,
  `tran_date` date NOT NULL,
  `spell_id` int NOT NULL,
  `machine_id` int NOT NULL,
  `item_id` int NOT NULL,
  `bm_quality_id` int NOT NULL,
  `eb_id` int DEFAULT NULL,
  `beam_no` varchar(50) DEFAULT NULL,
  `act_cuts` int NOT NULL,
  `no_of_beam` int NOT NULL,
  `rpm_roller` decimal(10,3) DEFAULT NULL,
  `dia_roller` decimal(10,3) DEFAULT NULL,
  `ends` int DEFAULT NULL,
  `std_count` decimal(10,3) DEFAULT NULL,
  `act_count` decimal(10,3) DEFAULT NULL,
  `laid_length` decimal(12,4) DEFAULT NULL,
  `std_cuts_per_beam` decimal(10,3) DEFAULT NULL,
  `std_speed` decimal(12,4) DEFAULT NULL,
  `target_speed` decimal(12,4) DEFAULT NULL,
  `act_speed` decimal(12,4) DEFAULT NULL,
  `std_eff` decimal(6,2) DEFAULT NULL,
  `target_eff` decimal(6,2) DEFAULT NULL,
  `working_hours` decimal(5,2) DEFAULT NULL,
  `yards_per_beam` decimal(14,4) DEFAULT NULL,
  `kg_per_cut` decimal(14,6) DEFAULT NULL,
  `kg_per_beam` decimal(14,4) DEFAULT NULL,
  `p100prod` decimal(14,3) DEFAULT NULL,
  `std_prod` decimal(14,3) DEFAULT NULL,
  `target_prod` decimal(14,3) DEFAULT NULL,
  `act_prod_kg` decimal(14,3) DEFAULT NULL,
  `act_prod_yards` decimal(14,3) DEFAULT NULL,
  `act_eff` decimal(6,2) DEFAULT NULL,
  `active` tinyint NOT NULL DEFAULT '1',
  `updated_by` int DEFAULT NULL,
  `updated_date_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`beaming_daily_id`),
  KEY `idx_bd_co_branch_date` (`co_id`,`branch_id`,`tran_date`),
  KEY `idx_bd_key` (`co_id`,`tran_date`,`spell_id`,`machine_id`,`item_id`,`bm_quality_id`),
  KEY `fk_bd_machine` (`machine_id`),
  KEY `fk_bd_spell` (`spell_id`),
  KEY `fk_bd_quality` (`bm_quality_id`),
  CONSTRAINT `fk_bd_machine` FOREIGN KEY (`machine_id`) REFERENCES `machine_mst` (`machine_id`),
  CONSTRAINT `fk_bd_quality` FOREIGN KEY (`bm_quality_id`) REFERENCES `jute_prod_bm_quality` (`bm_quality_id`),
  CONSTRAINT `fk_bd_spell` FOREIGN KEY (`spell_id`) REFERENCES `spell_mst` (`spell_id`)
) ENGINE=InnoDB AUTO_INCREMENT=9 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `jute_prod_beaming_target_map` (
  `beaming_target_map_id` int NOT NULL AUTO_INCREMENT,
  `co_id` int NOT NULL,
  `branch_id` int DEFAULT NULL,
  `effective_date` date NOT NULL,
  `ref_id` int NOT NULL,
  `id_type` varchar(8) NOT NULL,
  `value_role` varchar(10) NOT NULL,
  `param` varchar(20) NOT NULL,
  `value` decimal(12,4) NOT NULL DEFAULT '0.0000',
  `active` tinyint NOT NULL DEFAULT '1',
  `updated_by` int DEFAULT NULL,
  `updated_date_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`beaming_target_map_id`),
  KEY `idx_btm_lookup` (`co_id`,`ref_id`,`id_type`,`value_role`,`param`,`effective_date`),
  KEY `idx_btm_co` (`co_id`)
) ENGINE=InnoDB AUTO_INCREMENT=21 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `jute_prod_bm_quality` (
  `bm_quality_id` int NOT NULL AUTO_INCREMENT,
  `co_id` int NOT NULL,
  `branch_id` int DEFAULT NULL,
  `item_id` int NOT NULL,
  `bm_quality_code` varchar(50) NOT NULL,
  `bm_quality_name` varchar(100) DEFAULT NULL,
  `ends` int NOT NULL,
  `std_count` decimal(10,3) DEFAULT NULL,
  `yarn_item_id` int DEFAULT NULL,
  `is_composite` tinyint NOT NULL DEFAULT '0',
  `active` tinyint NOT NULL DEFAULT '1',
  `updated_by` int DEFAULT NULL,
  `updated_date_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`bm_quality_id`),
  KEY `idx_bmq_co_item` (`co_id`,`item_id`),
  KEY `fk_bmq_item` (`item_id`),
  CONSTRAINT `fk_bmq_item` FOREIGN KEY (`item_id`) REFERENCES `item_mst` (`item_id`)
) ENGINE=InnoDB AUTO_INCREMENT=5 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `jute_prod_bm_quality_dtl` (
  `bm_quality_dtl_id` int NOT NULL AUTO_INCREMENT,
  `bm_quality_id` int NOT NULL,
  `component_no` int NOT NULL,
  `ends` int NOT NULL,
  `yarn_item_id` int DEFAULT NULL,
  `count` decimal(10,3) NOT NULL,
  `active` tinyint NOT NULL DEFAULT '1',
  PRIMARY KEY (`bm_quality_dtl_id`),
  KEY `idx_bmqd_parent` (`bm_quality_id`),
  CONSTRAINT `fk_bmqd_parent` FOREIGN KEY (`bm_quality_id`) REFERENCES `jute_prod_bm_quality` (`bm_quality_id`)
) ENGINE=InnoDB AUTO_INCREMENT=7 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `jute_prod_finishing_daily` (
  `finishing_daily_id` int NOT NULL AUTO_INCREMENT,
  `co_id` int NOT NULL,
  `branch_id` int DEFAULT NULL,
  `tran_date` date NOT NULL,
  `spell_id` int NOT NULL,
  `process` varchar(20) NOT NULL,
  `machine_id` int DEFAULT NULL,
  `finishing_quality_id` int NOT NULL,
  `eb_id` int DEFAULT NULL,
  `input_qty` decimal(14,4) DEFAULT NULL,
  `input_uom` varchar(10) DEFAULT NULL,
  `prod_qty` decimal(14,4) NOT NULL,
  `prod_uom` varchar(10) NOT NULL,
  `prod_wt_kg` decimal(14,3) DEFAULT NULL,
  `wastage_kg` decimal(14,3) DEFAULT NULL,
  `std_speed` decimal(12,4) DEFAULT NULL,
  `target_speed` decimal(12,4) DEFAULT NULL,
  `act_speed` decimal(12,4) DEFAULT NULL,
  `std_eff` decimal(6,2) DEFAULT NULL,
  `target_eff` decimal(6,2) DEFAULT NULL,
  `working_hours` decimal(5,2) DEFAULT NULL,
  `p100prod` decimal(14,3) DEFAULT NULL,
  `std_prod` decimal(14,3) DEFAULT NULL,
  `target_prod` decimal(14,3) DEFAULT NULL,
  `act_eff` decimal(6,2) DEFAULT NULL,
  `active` tinyint NOT NULL DEFAULT '1',
  `updated_by` int DEFAULT NULL,
  `updated_date_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`finishing_daily_id`),
  KEY `idx_fd_co_branch_date` (`co_id`,`branch_id`,`tran_date`),
  KEY `idx_fd_key` (`co_id`,`tran_date`,`spell_id`,`process`,`machine_id`,`finishing_quality_id`),
  KEY `fk_fd_machine` (`machine_id`),
  KEY `fk_fd_spell` (`spell_id`),
  KEY `fk_fd_quality` (`finishing_quality_id`),
  CONSTRAINT `fk_fd_machine` FOREIGN KEY (`machine_id`) REFERENCES `machine_mst` (`machine_id`),
  CONSTRAINT `fk_fd_quality` FOREIGN KEY (`finishing_quality_id`) REFERENCES `jute_prod_finishing_quality` (`finishing_quality_id`),
  CONSTRAINT `fk_fd_spell` FOREIGN KEY (`spell_id`) REFERENCES `spell_mst` (`spell_id`)
) ENGINE=InnoDB AUTO_INCREMENT=2 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `jute_prod_finishing_daily_param` (
  `finishing_daily_param_id` int NOT NULL AUTO_INCREMENT,
  `finishing_daily_id` int NOT NULL,
  `param` varchar(24) NOT NULL,
  `value` decimal(14,4) DEFAULT NULL,
  `active` tinyint NOT NULL DEFAULT '1',
  PRIMARY KEY (`finishing_daily_param_id`),
  KEY `idx_fdp_parent` (`finishing_daily_id`),
  CONSTRAINT `fk_fdp_parent` FOREIGN KEY (`finishing_daily_id`) REFERENCES `jute_prod_finishing_daily` (`finishing_daily_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `jute_prod_finishing_quality` (
  `finishing_quality_id` int NOT NULL AUTO_INCREMENT,
  `co_id` int NOT NULL,
  `branch_id` int DEFAULT NULL,
  `quality_type` tinyint NOT NULL,
  `item_id` int NOT NULL,
  `packsheet_wt` decimal(14,3) DEFAULT NULL,
  `std_bale_weight` decimal(14,3) DEFAULT NULL,
  `no_of_bags` int DEFAULT NULL,
  `active` tinyint NOT NULL DEFAULT '1',
  `updated_by` int DEFAULT NULL,
  `updated_date_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`finishing_quality_id`),
  KEY `idx_fq_co_item` (`co_id`,`item_id`),
  KEY `idx_fq_type` (`co_id`,`quality_type`),
  KEY `fk_fq_item` (`item_id`),
  CONSTRAINT `fk_fq_item` FOREIGN KEY (`item_id`) REFERENCES `item_mst` (`item_id`)
) ENGINE=InnoDB AUTO_INCREMENT=4 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `jute_prod_finishing_target_map` (
  `finishing_target_map_id` int NOT NULL AUTO_INCREMENT,
  `co_id` int NOT NULL,
  `branch_id` int DEFAULT NULL,
  `process` varchar(20) NOT NULL,
  `effective_date` date NOT NULL,
  `ref_id` int NOT NULL,
  `id_type` varchar(8) NOT NULL,
  `value_role` varchar(10) NOT NULL,
  `param` varchar(24) NOT NULL,
  `value` decimal(12,4) NOT NULL DEFAULT '0.0000',
  `active` tinyint NOT NULL DEFAULT '1',
  `updated_by` int DEFAULT NULL,
  `updated_date_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`finishing_target_map_id`),
  KEY `idx_ftm_lookup` (`co_id`,`process`,`ref_id`,`id_type`,`value_role`,`param`,`effective_date`),
  KEY `idx_ftm_co` (`co_id`)
) ENGINE=InnoDB AUTO_INCREMENT=18 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `jute_prod_spng_target_map` (
  `spng_target_map_id` int NOT NULL AUTO_INCREMENT,
  `co_id` int NOT NULL,
  `branch_id` int DEFAULT NULL,
  `effective_date` date NOT NULL,
  `ref_id` int NOT NULL,
  `id_type` varchar(8) NOT NULL,
  `value_role` varchar(10) NOT NULL,
  `param` varchar(20) NOT NULL,
  `value` decimal(12,4) NOT NULL DEFAULT '0.0000',
  `active` tinyint(1) NOT NULL DEFAULT '1',
  `updated_by` int DEFAULT NULL,
  `updated_date_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`spng_target_map_id`),
  KEY `idx_jpstm_lookup` (`co_id`,`ref_id`,`id_type`,`value_role`,`param`,`effective_date`),
  KEY `idx_jpstm_co` (`co_id`)
) ENGINE=InnoDB AUTO_INCREMENT=62 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `jute_prod_stoppage_hours` (
  `stoppage_hours_id` int NOT NULL AUTO_INCREMENT,
  `co_id` int NOT NULL,
  `branch_id` int DEFAULT NULL,
  `tran_date` date NOT NULL,
  `spell_id` int NOT NULL,
  `machine_id` int NOT NULL,
  `stoppage_hours` decimal(5,2) NOT NULL,
  `reason_code` varchar(20) NOT NULL,
  `remarks` varchar(255) DEFAULT NULL,
  `active` tinyint NOT NULL DEFAULT '1',
  `updated_by` int DEFAULT NULL,
  `updated_date_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`stoppage_hours_id`),
  KEY `idx_stoppage_co_branch_date` (`co_id`,`branch_id`,`tran_date`),
  KEY `idx_stoppage_machine_date_spell` (`machine_id`,`tran_date`,`spell_id`),
  KEY `idx_stoppage_spell` (`spell_id`),
  CONSTRAINT `fk_stoppage_machine` FOREIGN KEY (`machine_id`) REFERENCES `machine_mst` (`machine_id`),
  CONSTRAINT `fk_stoppage_spell` FOREIGN KEY (`spell_id`) REFERENCES `spell_mst` (`spell_id`)
) ENGINE=InnoDB AUTO_INCREMENT=2 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `jute_prod_weaving_beam_map` (
  `weaving_beam_map_id` int NOT NULL AUTO_INCREMENT,
  `co_id` int NOT NULL,
  `branch_id` int DEFAULT NULL,
  `tran_date` date NOT NULL,
  `spell_id` int NOT NULL,
  `machine_id` int NOT NULL,
  `beam_no` varchar(50) NOT NULL,
  `active` tinyint NOT NULL DEFAULT '1',
  `updated_by` int DEFAULT NULL,
  `updated_date_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`weaving_beam_map_id`),
  KEY `idx_wbm_key` (`co_id`,`tran_date`,`spell_id`,`machine_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `jute_prod_weaving_daily` (
  `weaving_daily_id` int NOT NULL AUTO_INCREMENT,
  `co_id` int NOT NULL,
  `branch_id` int DEFAULT NULL,
  `tran_date` date NOT NULL,
  `spell_id` int NOT NULL,
  `machine_id` int NOT NULL,
  `weaving_quality_id` int NOT NULL,
  `eb_id` int DEFAULT NULL,
  `beam_no` varchar(50) DEFAULT NULL,
  `cuts` int NOT NULL,
  `less_production` decimal(12,3) DEFAULT '0.000',
  `close_jugar` decimal(10,3) DEFAULT '0.000',
  `active` tinyint NOT NULL DEFAULT '1',
  `updated_by` int DEFAULT NULL,
  `updated_date_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`weaving_daily_id`),
  KEY `idx_wd_co_branch_date` (`co_id`,`branch_id`,`tran_date`),
  KEY `idx_wd_key` (`co_id`,`tran_date`,`spell_id`,`machine_id`,`weaving_quality_id`),
  KEY `fk_wd_machine` (`machine_id`),
  KEY `fk_wd_spell` (`spell_id`),
  KEY `fk_wd_quality` (`weaving_quality_id`),
  CONSTRAINT `fk_wd_machine` FOREIGN KEY (`machine_id`) REFERENCES `machine_mst` (`machine_id`),
  CONSTRAINT `fk_wd_quality` FOREIGN KEY (`weaving_quality_id`) REFERENCES `jute_prod_weaving_quality` (`weaving_quality_id`),
  CONSTRAINT `fk_wd_spell` FOREIGN KEY (`spell_id`) REFERENCES `spell_mst` (`spell_id`)
) ENGINE=InnoDB AUTO_INCREMENT=107 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `jute_prod_weaving_quality` (
  `weaving_quality_id` int NOT NULL AUTO_INCREMENT,
  `co_id` int NOT NULL,
  `branch_id` int DEFAULT NULL,
  `item_id` int NOT NULL,
  `weaving_quality_code` varchar(50) NOT NULL,
  `weaving_quality_name` varchar(100) DEFAULT NULL,
  `ends` int NOT NULL,
  `finished_length` decimal(12,3) NOT NULL,
  `ozs_yds` decimal(10,4) NOT NULL,
  `std_ozs_yds` decimal(10,4) DEFAULT NULL,
  `no_of_jugar_per_cut` decimal(10,3) NOT NULL,
  `width` decimal(10,3) DEFAULT NULL,
  `ports` decimal(10,3) DEFAULT NULL,
  `reed_porter` decimal(10,3) DEFAULT NULL,
  `shrinkage_pct` decimal(6,3) DEFAULT NULL,
  `shots` decimal(10,3) DEFAULT NULL,
  `mc_teeth` int DEFAULT NULL,
  `jbo_rbo` varchar(10) DEFAULT NULL,
  `reed_space` decimal(10,3) DEFAULT NULL,
  `tpi` decimal(10,3) DEFAULT NULL,
  `yarn_count` varchar(20) DEFAULT NULL,
  `is_composite` tinyint NOT NULL DEFAULT '0',
  `active` tinyint NOT NULL DEFAULT '1',
  `updated_by` int DEFAULT NULL,
  `updated_date_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`weaving_quality_id`),
  KEY `idx_wq_co_item` (`co_id`,`item_id`),
  KEY `fk_wq_item` (`item_id`),
  CONSTRAINT `fk_wq_item` FOREIGN KEY (`item_id`) REFERENCES `item_mst` (`item_id`)
) ENGINE=InnoDB AUTO_INCREMENT=4 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `jute_prod_weaving_quality_dtl` (
  `weaving_quality_dtl_id` int NOT NULL AUTO_INCREMENT,
  `weaving_quality_id` int NOT NULL,
  `component_no` int NOT NULL,
  `ends` int NOT NULL,
  `yarn_item_id` int DEFAULT NULL,
  `count` decimal(10,3) NOT NULL,
  `active` tinyint NOT NULL DEFAULT '1',
  PRIMARY KEY (`weaving_quality_dtl_id`),
  KEY `idx_wqd_parent` (`weaving_quality_id`),
  CONSTRAINT `fk_wqd_parent` FOREIGN KEY (`weaving_quality_id`) REFERENCES `jute_prod_weaving_quality` (`weaving_quality_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `jute_prod_weaving_quality_map` (
  `weaving_quality_map_id` int NOT NULL AUTO_INCREMENT,
  `co_id` int NOT NULL,
  `branch_id` int DEFAULT NULL,
  `tran_date` date NOT NULL,
  `spell_id` int NOT NULL,
  `machine_id` int NOT NULL,
  `weaving_quality_id` int NOT NULL,
  `active` tinyint NOT NULL DEFAULT '1',
  `updated_by` int DEFAULT NULL,
  `updated_date_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`weaving_quality_map_id`),
  KEY `idx_wqm_key` (`co_id`,`tran_date`,`spell_id`,`machine_id`)
) ENGINE=InnoDB AUTO_INCREMENT=362 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `jute_prod_weaving_target_map` (
  `weaving_target_map_id` int NOT NULL AUTO_INCREMENT,
  `co_id` int NOT NULL,
  `branch_id` int DEFAULT NULL,
  `effective_date` date NOT NULL,
  `ref_id` int NOT NULL,
  `id_type` varchar(8) NOT NULL,
  `value_role` varchar(10) NOT NULL,
  `param` varchar(20) NOT NULL,
  `value` decimal(12,4) NOT NULL DEFAULT '0.0000',
  `active` tinyint NOT NULL DEFAULT '1',
  `updated_by` int DEFAULT NULL,
  `updated_date_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`weaving_target_map_id`),
  KEY `idx_wtm_lookup` (`co_id`,`ref_id`,`id_type`,`value_role`,`param`,`effective_date`),
  KEY `idx_wtm_co` (`co_id`)
) ENGINE=InnoDB AUTO_INCREMENT=57 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `jute_prod_winding_daily_qlty` (
  `winding_daily_qlty_id` int NOT NULL AUTO_INCREMENT,
  `co_id` int NOT NULL,
  `branch_id` int DEFAULT NULL,
  `tran_date` date NOT NULL,
  `spell_id` int NOT NULL,
  `machine_id` int NOT NULL,
  `item_id` int DEFAULT NULL,
  `no_of_spindle` int NOT NULL DEFAULT '0',
  `active` tinyint(1) NOT NULL DEFAULT '1',
  `updated_by` int DEFAULT NULL,
  `updated_date_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`winding_daily_qlty_id`),
  KEY `idx_jpwdq_co_date_spell_mc` (`co_id`,`tran_date`,`spell_id`,`machine_id`),
  KEY `idx_jpwdq_co` (`co_id`),
  KEY `idx_jpwdq_quality` (`item_id`)
) ENGINE=InnoDB AUTO_INCREMENT=10 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `jute_prod_winding_doff` (
  `winding_doff_id` int NOT NULL AUTO_INCREMENT,
  `co_id` int NOT NULL,
  `branch_id` int DEFAULT NULL,
  `tran_date` date NOT NULL,
  `spell_id` int NOT NULL,
  `machine_id` int NOT NULL,
  `item_id` int DEFAULT NULL,
  `trolly_id` int DEFAULT NULL,
  `trolly_wt` decimal(10,3) NOT NULL DEFAULT '0.000',
  `spool_id` int DEFAULT NULL,
  `spool_wt` decimal(10,3) NOT NULL DEFAULT '0.000',
  `no_of_machines` int NOT NULL DEFAULT '1',
  `gross_input_wt` decimal(12,3) NOT NULL DEFAULT '0.000',
  `production_qty` decimal(12,3) NOT NULL DEFAULT '0.000',
  `row_gross_wt` decimal(12,3) NOT NULL DEFAULT '0.000',
  `operator_id` int DEFAULT NULL,
  `active` tinyint(1) NOT NULL DEFAULT '1',
  `updated_by` int DEFAULT NULL,
  `updated_date_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`winding_doff_id`),
  KEY `idx_jpwd_co_date_spell_mc` (`co_id`,`tran_date`,`spell_id`,`machine_id`),
  KEY `idx_jpwd_co` (`co_id`),
  KEY `idx_jpwd_quality` (`item_id`)
) ENGINE=InnoDB AUTO_INCREMENT=11 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `jute_prod_winding_jugar` (
  `winding_jugar_id` int NOT NULL AUTO_INCREMENT,
  `co_id` int NOT NULL,
  `branch_id` int DEFAULT NULL,
  `tran_date` date NOT NULL,
  `spell_id` int NOT NULL,
  `machine_id` int NOT NULL,
  `weight` decimal(10,3) NOT NULL DEFAULT '0.000',
  `open_close` char(1) NOT NULL DEFAULT 'O',
  `active` tinyint(1) NOT NULL DEFAULT '1',
  `updated_by` int DEFAULT NULL,
  `updated_date_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`winding_jugar_id`),
  KEY `idx_jpwj_co_date_spell_mc_oc` (`co_id`,`tran_date`,`spell_id`,`machine_id`,`open_close`),
  KEY `idx_jpwj_co` (`co_id`)
) ENGINE=InnoDB AUTO_INCREMENT=6 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `jute_spreader_quality_attr` (
  `spreader_quality_attr_id` int NOT NULL AUTO_INCREMENT,
  `co_id` int NOT NULL,
  `item_id` int NOT NULL,
  `std_mr_pct` decimal(5,2) DEFAULT NULL,
  `std_roll_wt` decimal(10,3) DEFAULT NULL,
  `active` int NOT NULL DEFAULT '1',
  `updated_by` int DEFAULT NULL,
  `updated_date_time` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`spreader_quality_attr_id`),
  KEY `idx_jsqa_item_id` (`item_id`),
  KEY `idx_jsqa_co_id` (`co_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `jute_sqc_bag_check` (
  `bag_check_id` int NOT NULL AUTO_INCREMENT,
  `co_id` int NOT NULL,
  `branch_id` int DEFAULT NULL,
  `entry_date` date NOT NULL,
  `item_id` int DEFAULT NULL,
  `bag_type_label` varchar(255) DEFAULT NULL,
  `vendor_name` varchar(120) DEFAULT NULL,
  `id_code` varchar(50) DEFAULT NULL,
  `std_bag_weight` decimal(8,2) DEFAULT NULL,
  `std_length` decimal(8,2) DEFAULT NULL,
  `std_width` decimal(8,2) DEFAULT NULL,
  `std_ends` decimal(8,2) DEFAULT NULL,
  `std_picks` decimal(8,2) DEFAULT NULL,
  `std_stitch` decimal(8,2) DEFAULT NULL,
  `std_mr_pct` decimal(5,2) DEFAULT NULL,
  `active` int NOT NULL DEFAULT '1',
  `updated_by` int DEFAULT NULL,
  `updated_date_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`bag_check_id`),
  KEY `idx_jute_sqc_bag_check_co_id` (`co_id`),
  KEY `idx_jute_sqc_bag_check_entry_date` (`entry_date`)
) ENGINE=InnoDB AUTO_INCREMENT=3 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `jute_sqc_bag_check_dtl` (
  `bag_check_dtl_id` int NOT NULL AUTO_INCREMENT,
  `bag_check_id` int NOT NULL,
  `sl_no` int DEFAULT NULL,
  `length_cm` decimal(8,2) DEFAULT NULL,
  `width_cm` decimal(8,2) DEFAULT NULL,
  `ends_dm` decimal(8,2) DEFAULT NULL,
  `picks_dm` decimal(8,2) DEFAULT NULL,
  `mr_pct` decimal(6,2) DEFAULT NULL,
  `bag_wt_gm` decimal(8,2) DEFAULT NULL,
  `stitch_dm` decimal(6,2) DEFAULT NULL,
  `defects` varchar(200) DEFAULT NULL,
  `corr_wt_gm` decimal(8,2) DEFAULT NULL,
  PRIMARY KEY (`bag_check_dtl_id`),
  KEY `idx_jute_sqc_bag_check_dtl_hdr` (`bag_check_id`)
) ENGINE=InnoDB AUTO_INCREMENT=5 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `jute_sqc_bag_weight` (
  `bag_weight_id` int NOT NULL AUTO_INCREMENT,
  `co_id` int NOT NULL,
  `branch_id` int DEFAULT NULL,
  `entry_date` date NOT NULL,
  `item_id` int DEFAULT NULL,
  `bag_type_label` varchar(255) DEFAULT NULL,
  `std_bag_weight` decimal(8,2) DEFAULT NULL,
  `std_mr_pct` decimal(5,2) DEFAULT NULL,
  `readings` varchar(2000) NOT NULL,
  `calc_avg_mr` decimal(6,3) DEFAULT NULL,
  `calc_avg_obs_wt` decimal(8,2) DEFAULT NULL,
  `calc_avg_corr_wt` decimal(8,2) DEFAULT NULL,
  `calc_obs_stdev` decimal(8,3) DEFAULT NULL,
  `calc_obs_cv_pct` decimal(6,2) DEFAULT NULL,
  `calc_obs_hy_lt_pct` decimal(6,2) DEFAULT NULL,
  `calc_corr_hy_lt_pct` decimal(6,2) DEFAULT NULL,
  `active` int NOT NULL DEFAULT '1',
  `updated_by` int DEFAULT NULL,
  `updated_date_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`bag_weight_id`),
  KEY `idx_bag_weight_co_id` (`co_id`),
  KEY `idx_bag_weight_entry_date` (`entry_date`)
) ENGINE=InnoDB AUTO_INCREMENT=4 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `jute_sqc_beam_mr` (
  `beam_mr_id` int NOT NULL AUTO_INCREMENT,
  `co_id` int NOT NULL,
  `branch_id` int DEFAULT NULL,
  `entry_date` date NOT NULL,
  `quality_group` varchar(20) NOT NULL,
  `spell_id` int DEFAULT NULL,
  `item_id` int DEFAULT NULL,
  `mc_id` int DEFAULT NULL,
  `readings` varchar(200) NOT NULL,
  `calc_avg_mr` decimal(6,2) DEFAULT NULL,
  `std_mr_pct` decimal(6,2) DEFAULT NULL,
  `active` int NOT NULL DEFAULT '1',
  `updated_by` int DEFAULT NULL,
  `updated_date_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`beam_mr_id`),
  KEY `idx_jute_sqc_beam_mr_co_id` (`co_id`),
  KEY `idx_jute_sqc_beam_mr_entry_date` (`entry_date`)
) ENGINE=InnoDB AUTO_INCREMENT=7 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `jute_sqc_breaker_card_swt` (
  `breaker_card_swt_id` int NOT NULL AUTO_INCREMENT,
  `co_id` int NOT NULL,
  `branch_id` int DEFAULT NULL,
  `entry_date` date NOT NULL,
  `mc_id` int DEFAULT NULL,
  `spell_id` int DEFAULT NULL,
  `item_id` int DEFAULT NULL,
  `batch_plan_id` bigint DEFAULT NULL,
  `card_side` varchar(10) DEFAULT 'COARSE',
  `weights` varchar(500) NOT NULL,
  `mr_pcts` varchar(500) NOT NULL,
  `std_mr_pct` decimal(5,2) DEFAULT NULL,
  `std_cv_low` decimal(5,2) DEFAULT NULL,
  `std_cv_high` decimal(5,2) DEFAULT NULL,
  `calc_wt` decimal(10,3) DEFAULT NULL,
  `calc_mr_pct` decimal(5,2) DEFAULT NULL,
  `calc_corr_wt` decimal(10,3) DEFAULT NULL,
  `calc_sdev` decimal(10,4) DEFAULT NULL,
  `calc_cv_pct` decimal(7,4) DEFAULT NULL,
  `cv_within_band` int DEFAULT NULL,
  `active` int NOT NULL DEFAULT '1',
  `updated_by` int DEFAULT NULL,
  `updated_date_time` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`breaker_card_swt_id`),
  KEY `idx_jbcsw_co_id` (`co_id`),
  KEY `idx_jbcsw_entry_date` (`entry_date`),
  KEY `idx_jbcsw_co_entry_date` (`co_id`,`entry_date`),
  KEY `idx_jbcsw_mc_id` (`mc_id`),
  KEY `idx_jbcsw_item_id` (`item_id`),
  KEY `idx_jbcsw_batch_plan_id` (`batch_plan_id`)
) ENGINE=InnoDB AUTO_INCREMENT=7 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `jute_sqc_card_sliver_wt` (
  `card_sliver_wt_id` int NOT NULL AUTO_INCREMENT,
  `co_id` int NOT NULL,
  `branch_id` int DEFAULT NULL,
  `entry_date` date NOT NULL,
  `section` varchar(20) NOT NULL,
  `mc_id` int DEFAULT NULL,
  `spell_id` int DEFAULT NULL,
  `item_id` int DEFAULT NULL,
  `batch_plan_id` bigint DEFAULT NULL,
  `weights` varchar(500) NOT NULL,
  `mr_pcts` varchar(500) NOT NULL,
  `std_mr_pct` decimal(5,2) DEFAULT NULL,
  `std_cv_low` decimal(5,2) DEFAULT NULL,
  `std_cv_high` decimal(5,2) DEFAULT NULL,
  `calc_wt` decimal(10,3) DEFAULT NULL,
  `calc_mr_pct` decimal(5,2) DEFAULT NULL,
  `calc_corr_wt` decimal(10,3) DEFAULT NULL,
  `calc_sdev` decimal(10,4) DEFAULT NULL,
  `calc_cv_pct` decimal(7,4) DEFAULT NULL,
  `cv_within_band` int DEFAULT NULL,
  `active` int NOT NULL DEFAULT '1',
  `updated_by` int DEFAULT NULL,
  `updated_date_time` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`card_sliver_wt_id`),
  KEY `idx_jcsw_co_id` (`co_id`),
  KEY `idx_jcsw_entry_date` (`entry_date`),
  KEY `idx_jcsw_co_entry_date` (`co_id`,`entry_date`),
  KEY `idx_jcsw_section` (`section`),
  KEY `idx_jcsw_mc_id` (`mc_id`),
  KEY `idx_jcsw_item_id` (`item_id`),
  KEY `idx_jcsw_batch_plan_id` (`batch_plan_id`)
) ENGINE=InnoDB AUTO_INCREMENT=11 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `jute_sqc_cutting_length` (
  `cutting_length_id` int NOT NULL AUTO_INCREMENT,
  `co_id` int NOT NULL,
  `branch_id` int DEFAULT NULL,
  `entry_date` date NOT NULL,
  `item_id` int DEFAULT NULL,
  `std_length` decimal(10,2) NOT NULL,
  `readings` varchar(500) NOT NULL,
  `calc_avg` decimal(10,3) DEFAULT NULL,
  `calc_stdev` decimal(10,4) DEFAULT NULL,
  `calc_cv_pct` decimal(10,4) DEFAULT NULL,
  `calc_deviation` decimal(10,3) DEFAULT NULL,
  `active` int NOT NULL DEFAULT '1',
  `updated_by` int DEFAULT NULL,
  `updated_date_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`cutting_length_id`),
  KEY `idx_cutting_length_co_id` (`co_id`),
  KEY `idx_cutting_length_entry_date` (`entry_date`)
) ENGINE=InnoDB AUTO_INCREMENT=4 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `jute_sqc_draw_sliver_wt` (
  `draw_sliver_wt_id` int NOT NULL AUTO_INCREMENT,
  `co_id` int NOT NULL,
  `branch_id` int DEFAULT NULL,
  `entry_date` date NOT NULL,
  `section` varchar(20) NOT NULL,
  `time_band` varchar(20) DEFAULT NULL,
  `mc_id` int DEFAULT NULL,
  `spell_id` int DEFAULT NULL,
  `batch_plan_id` bigint DEFAULT NULL,
  `weights` varchar(500) NOT NULL,
  `mr_pcts` varchar(500) NOT NULL,
  `std_mr_pct` decimal(5,2) DEFAULT NULL,
  `std_cv_low` decimal(5,2) DEFAULT NULL,
  `std_cv_high` decimal(5,2) DEFAULT NULL,
  `calc_wt` decimal(10,3) DEFAULT NULL,
  `calc_mr_pct` decimal(5,2) DEFAULT NULL,
  `calc_corr_wt` decimal(10,3) DEFAULT NULL,
  `calc_sdev` decimal(10,4) DEFAULT NULL,
  `calc_cv_pct` decimal(7,4) DEFAULT NULL,
  `cv_within_band` int DEFAULT NULL,
  `active` int NOT NULL DEFAULT '1',
  `updated_by` int DEFAULT NULL,
  `updated_date_time` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`draw_sliver_wt_id`),
  KEY `idx_jdsw_co_id` (`co_id`),
  KEY `idx_jdsw_entry_date` (`entry_date`),
  KEY `idx_jdsw_co_entry_date` (`co_id`,`entry_date`),
  KEY `idx_jdsw_section` (`section`),
  KEY `idx_jdsw_mc_id` (`mc_id`),
  KEY `idx_jdsw_batch_plan_id` (`batch_plan_id`)
) ENGINE=InnoDB AUTO_INCREMENT=4 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `jute_sqc_emulsion` (
  `emulsion_id` int NOT NULL AUTO_INCREMENT,
  `co_id` int NOT NULL,
  `branch_id` int DEFAULT NULL,
  `entry_date` date NOT NULL,
  `mc_id` int DEFAULT NULL,
  `oil_used_ltr` decimal(10,2) DEFAULT NULL,
  `tank_capacity_ltr` decimal(10,2) DEFAULT NULL,
  `oil_pct_in_emulsion` decimal(5,2) DEFAULT NULL,
  `std_oil_pct_low` decimal(5,2) DEFAULT NULL,
  `std_oil_pct_high` decimal(5,2) DEFAULT NULL,
  `adco_used_ml` decimal(10,2) DEFAULT NULL,
  `eco_fin_used_ltr` decimal(10,2) DEFAULT NULL,
  `p40_gms` decimal(10,2) DEFAULT NULL,
  `efjl_kg` decimal(10,2) DEFAULT NULL,
  `glycerine_gms` decimal(10,2) DEFAULT NULL,
  `castrol_oil` decimal(10,2) DEFAULT NULL,
  `diesel_ltr` decimal(10,2) DEFAULT NULL,
  `citric_acid_ltr` decimal(10,2) DEFAULT NULL,
  `enzyme_gms` decimal(10,2) DEFAULT NULL,
  `treated_water_ltr` decimal(10,2) DEFAULT NULL,
  `rbo_ltr` decimal(10,2) DEFAULT NULL,
  `jbo_ltr` decimal(10,2) DEFAULT NULL,
  `molasses_kg` decimal(10,2) DEFAULT NULL,
  `urea_kg` decimal(10,2) DEFAULT NULL,
  `biochemical_kg` decimal(10,2) DEFAULT NULL,
  `jsp66` decimal(10,2) DEFAULT NULL,
  `feel_free_good_ve_kg` decimal(10,2) DEFAULT NULL,
  `spreader_rolls_made` int DEFAULT NULL,
  `others` varchar(255) DEFAULT NULL,
  `prepared_by` varchar(150) DEFAULT NULL,
  `active` int NOT NULL DEFAULT '1',
  `updated_by` int DEFAULT NULL,
  `updated_date_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`emulsion_id`),
  KEY `idx_jute_sqc_emulsion_co_id` (`co_id`),
  KEY `idx_jute_sqc_emulsion_entry_date` (`entry_date`)
) ENGINE=InnoDB AUTO_INCREMENT=4 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `jute_sqc_fabric_construction` (
  `fabric_const_id` int NOT NULL AUTO_INCREMENT,
  `co_id` int NOT NULL,
  `branch_id` int DEFAULT NULL,
  `entry_date` date NOT NULL,
  `item_id` int DEFAULT NULL,
  `quality_text` varchar(150) DEFAULT NULL,
  `std_length_yds` decimal(10,2) DEFAULT NULL,
  `std_width_cms` decimal(10,2) DEFAULT NULL,
  `std_ends_dm` decimal(10,2) DEFAULT NULL,
  `std_picks_dm` decimal(10,2) DEFAULT NULL,
  `std_mr_pct` decimal(6,2) DEFAULT NULL,
  `std_oz_per_yd` decimal(10,3) DEFAULT NULL,
  `active` int NOT NULL DEFAULT '1',
  `updated_by` int DEFAULT NULL,
  `updated_date_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`fabric_const_id`),
  KEY `idx_jute_sqc_fabric_const_co_id` (`co_id`),
  KEY `idx_jute_sqc_fabric_const_entry_date` (`entry_date`)
) ENGINE=InnoDB AUTO_INCREMENT=3 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `jute_sqc_fabric_construction_dtl` (
  `fabric_const_dtl_id` int NOT NULL AUTO_INCREMENT,
  `fabric_const_id` int NOT NULL,
  `sl` int NOT NULL,
  `length_yds` decimal(10,2) DEFAULT NULL,
  `width_cms` decimal(10,2) DEFAULT NULL,
  `ends_per_dm` decimal(10,2) DEFAULT NULL,
  `picks_per_dm` decimal(10,2) DEFAULT NULL,
  `mr_pct` decimal(6,2) DEFAULT NULL,
  `obs_wt_kg` decimal(10,3) DEFAULT NULL,
  `obs_ozs` decimal(10,3) DEFAULT NULL,
  `crcted_oz` decimal(10,3) DEFAULT NULL,
  PRIMARY KEY (`fabric_const_dtl_id`),
  KEY `idx_jute_sqc_fabric_const_dtl_hdr` (`fabric_const_id`)
) ENGINE=InnoDB AUTO_INCREMENT=5 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `jute_sqc_fabric_fault` (
  `fabric_fault_id` int NOT NULL AUTO_INCREMENT,
  `co_id` int NOT NULL,
  `branch_id` int DEFAULT NULL,
  `entry_date` date NOT NULL,
  `spell_id` int DEFAULT NULL,
  `item_id` int DEFAULT NULL,
  `loom_id` int DEFAULT NULL,
  `date_of_weaving` date DEFAULT NULL,
  `fault_counts` varchar(500) NOT NULL,
  `calc_piece_total` int DEFAULT NULL,
  `remarks` varchar(255) DEFAULT NULL,
  `inspector_name` varchar(120) DEFAULT NULL,
  `active` int NOT NULL DEFAULT '1',
  `updated_by` int DEFAULT NULL,
  `updated_date_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`fabric_fault_id`),
  KEY `idx_jute_sqc_fabric_fault_co_id` (`co_id`),
  KEY `idx_jute_sqc_fabric_fault_entry_date` (`entry_date`)
) ENGINE=InnoDB AUTO_INCREMENT=8 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `jute_sqc_fin_draw_sliver_wt` (
  `fin_draw_sliver_wt_id` int NOT NULL AUTO_INCREMENT,
  `co_id` int NOT NULL,
  `branch_id` int DEFAULT NULL,
  `entry_date` date NOT NULL,
  `section` varchar(10) NOT NULL,
  `mc_id` int DEFAULT NULL,
  `spell_id` int DEFAULT NULL,
  `batch_plan_id` bigint DEFAULT NULL,
  `weights` varchar(500) NOT NULL,
  `mr_pcts` varchar(500) NOT NULL,
  `dlv_nos` varchar(500) DEFAULT NULL,
  `std_mr_pct` decimal(5,2) DEFAULT NULL,
  `std_cv_low` decimal(5,2) DEFAULT NULL,
  `std_cv_high` decimal(5,2) DEFAULT NULL,
  `calc_wt` decimal(10,3) DEFAULT NULL,
  `calc_mr_pct` decimal(5,2) DEFAULT NULL,
  `calc_corr_wt` decimal(10,3) DEFAULT NULL,
  `calc_sdev` decimal(10,4) DEFAULT NULL,
  `calc_cv_pct` decimal(7,4) DEFAULT NULL,
  `cv_within_band` int DEFAULT NULL,
  `active` int NOT NULL DEFAULT '1',
  `updated_by` int DEFAULT NULL,
  `updated_date_time` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`fin_draw_sliver_wt_id`),
  KEY `idx_jfdsw_co_id` (`co_id`),
  KEY `idx_jfdsw_entry_date` (`entry_date`),
  KEY `idx_jfdsw_co_entry_date` (`co_id`,`entry_date`),
  KEY `idx_jfdsw_section` (`section`),
  KEY `idx_jfdsw_mc_id` (`mc_id`),
  KEY `idx_jfdsw_batch_plan_id` (`batch_plan_id`)
) ENGINE=InnoDB AUTO_INCREMENT=5 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `jute_sqc_humidity` (
  `humidity_id` int NOT NULL AUTO_INCREMENT,
  `co_id` int NOT NULL,
  `branch_id` int DEFAULT NULL,
  `report_date` date NOT NULL,
  `dept_id` int DEFAULT NULL,
  `round_no` int NOT NULL,
  `spots` varchar(1000) NOT NULL,
  `calc_avg_temp` decimal(5,2) DEFAULT NULL,
  `calc_avg_rh` decimal(5,2) DEFAULT NULL,
  `prepared_by` varchar(150) DEFAULT NULL,
  `active` int NOT NULL DEFAULT '1',
  `updated_by` int DEFAULT NULL,
  `updated_date_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`humidity_id`),
  KEY `idx_humidity_co_id` (`co_id`),
  KEY `idx_humidity_report_date` (`report_date`)
) ENGINE=InnoDB AUTO_INCREMENT=7 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `jute_sqc_morrah_wt` (
  `morrah_wt_id` int NOT NULL AUTO_INCREMENT,
  `co_id` int NOT NULL,
  `branch_id` int NOT NULL,
  `entry_date` date NOT NULL,
  `inspector_name` varchar(100) DEFAULT NULL,
  `dept_id` int DEFAULT NULL,
  `item_id` int DEFAULT NULL,
  `trolley_no` varchar(50) DEFAULT NULL,
  `avg_mr_pct` double DEFAULT NULL,
  `weights` json NOT NULL,
  `calc_avg_weight` double DEFAULT NULL,
  `calc_max_weight` int DEFAULT NULL,
  `calc_min_weight` int DEFAULT NULL,
  `calc_range` int DEFAULT NULL,
  `calc_cv_pct` double DEFAULT NULL,
  `count_lt` int DEFAULT NULL,
  `count_ok` int DEFAULT NULL,
  `count_hy` int DEFAULT NULL,
  `active` int NOT NULL DEFAULT '1',
  `updated_by` int DEFAULT NULL,
  `updated_date_time` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`morrah_wt_id`),
  KEY `idx_morrah_wt_co_id` (`co_id`),
  KEY `idx_morrah_wt_branch_id` (`branch_id`),
  KEY `idx_morrah_wt_entry_date` (`entry_date`)
) ENGINE=InnoDB AUTO_INCREMENT=5 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `jute_sqc_packing_mr` (
  `packing_mr_id` int NOT NULL AUTO_INCREMENT,
  `co_id` int NOT NULL,
  `branch_id` int DEFAULT NULL,
  `entry_date` date NOT NULL,
  `item_id` int DEFAULT NULL,
  `quality_group` varchar(20) NOT NULL,
  `quality_label` varchar(255) DEFAULT NULL,
  `construction_code` varchar(50) DEFAULT NULL,
  `readings` varchar(500) NOT NULL,
  `calc_avg_mr` decimal(6,3) DEFAULT NULL,
  `active` int NOT NULL DEFAULT '1',
  `updated_by` int DEFAULT NULL,
  `updated_date_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`packing_mr_id`),
  KEY `idx_jute_sqc_packing_mr_co_id` (`co_id`),
  KEY `idx_jute_sqc_packing_mr_entry_date` (`entry_date`)
) ENGINE=InnoDB AUTO_INCREMENT=5 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `jute_sqc_qr_cv_15a` (
  `qr_cv_15a_id` int NOT NULL AUTO_INCREMENT,
  `co_id` int NOT NULL,
  `branch_id` int DEFAULT NULL,
  `entry_date` date NOT NULL,
  `drawing_mc_id` int DEFAULT NULL,
  `mc_id` int DEFAULT NULL,
  `item_id` int DEFAULT NULL,
  `observed_count` decimal(10,3) DEFAULT NULL,
  `mr_pct` decimal(5,2) DEFAULT NULL,
  `active` int NOT NULL DEFAULT '1',
  `updated_by` int DEFAULT NULL,
  `updated_date_time` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`qr_cv_15a_id`),
  KEY `idx_jqc15a_co_id` (`co_id`),
  KEY `idx_jqc15a_entry_date` (`entry_date`),
  KEY `idx_jqc15a_co_entry_date` (`co_id`,`entry_date`),
  KEY `idx_jqc15a_mc_id` (`mc_id`),
  KEY `idx_jqc15a_item_id` (`item_id`)
) ENGINE=InnoDB AUTO_INCREMENT=4 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `jute_sqc_qr_cv_15a_dtl` (
  `qr_cv_15a_dtl_id` int NOT NULL AUTO_INCREMENT,
  `qr_cv_15a_id` int NOT NULL,
  `reading_no` int NOT NULL,
  `reading_val` decimal(10,3) DEFAULT NULL,
  PRIMARY KEY (`qr_cv_15a_dtl_id`),
  KEY `idx_jqc15a_dtl_hdr` (`qr_cv_15a_id`)
) ENGINE=InnoDB AUTO_INCREMENT=37 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `jute_sqc_spinning_qr_cv` (
  `spinning_sqc_qr_cv_id` int NOT NULL AUTO_INCREMENT,
  `co_id` int NOT NULL,
  `branch_id` int DEFAULT NULL,
  `entry_date` date NOT NULL,
  `mc_id` int DEFAULT NULL,
  `item_id` int NOT NULL,
  `active` int NOT NULL DEFAULT '1',
  `updated_by` int DEFAULT NULL,
  `updated_date_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`spinning_sqc_qr_cv_id`),
  KEY `idx_qrcv_co` (`co_id`),
  KEY `idx_qrcv_date` (`entry_date`),
  KEY `idx_qrcv_item` (`item_id`)
) ENGINE=InnoDB AUTO_INCREMENT=3 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `jute_sqc_spinning_qr_cv_dtl` (
  `spinning_sqc_qr_cv_dtl_id` int NOT NULL AUTO_INCREMENT,
  `spinning_sqc_qr_cv_id` int NOT NULL,
  `spindle_no` int NOT NULL,
  `reading_no` smallint NOT NULL,
  `reading_val` decimal(10,3) DEFAULT NULL,
  PRIMARY KEY (`spinning_sqc_qr_cv_dtl_id`),
  KEY `idx_qrcv_dtl_hdr` (`spinning_sqc_qr_cv_id`)
) ENGINE=InnoDB AUTO_INCREMENT=61 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `jute_sqc_spreader_roll_wt` (
  `spreader_roll_wt_id` int NOT NULL AUTO_INCREMENT,
  `co_id` int NOT NULL,
  `branch_id` int DEFAULT NULL,
  `entry_date` date NOT NULL,
  `spell_id` int DEFAULT NULL,
  `mc_id` int DEFAULT NULL,
  `item_id` int DEFAULT NULL,
  `feeder_name` varchar(255) DEFAULT NULL,
  `roll_weights` varchar(500) NOT NULL,
  `mr_pcts` varchar(500) NOT NULL,
  `std_mr_pct` decimal(5,2) DEFAULT NULL,
  `calc_avg_mr_pct` decimal(5,2) DEFAULT NULL,
  `calc_avg_obs` decimal(10,3) DEFAULT NULL,
  `calc_avg_corr` decimal(10,3) DEFAULT NULL,
  `calc_stdev_obs` decimal(10,4) DEFAULT NULL,
  `calc_stdev_corr` decimal(10,4) DEFAULT NULL,
  `calc_cv_pct` decimal(7,4) DEFAULT NULL,
  `band_counts_obs` varchar(500) DEFAULT NULL,
  `band_counts_corr` varchar(500) DEFAULT NULL,
  `active` int NOT NULL DEFAULT '1',
  `updated_by` int DEFAULT NULL,
  `updated_date_time` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`spreader_roll_wt_id`),
  KEY `idx_jsrw_co_id` (`co_id`),
  KEY `idx_jsrw_entry_date` (`entry_date`),
  KEY `idx_jsrw_co_entry_date` (`co_id`,`entry_date`),
  KEY `idx_jsrw_mc_id` (`mc_id`),
  KEY `idx_jsrw_item_id` (`item_id`)
) ENGINE=InnoDB AUTO_INCREMENT=3 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `jute_sqc_spreader_sliver_wt` (
  `spreader_sliver_wt_id` int NOT NULL AUTO_INCREMENT,
  `co_id` int NOT NULL,
  `branch_id` int DEFAULT NULL,
  `entry_date` date NOT NULL,
  `spell_id` int DEFAULT NULL,
  `category` varchar(100) DEFAULT NULL,
  `mc_id` int DEFAULT NULL,
  `item_id` int DEFAULT NULL,
  `sample_length_yds` decimal(5,2) DEFAULT NULL,
  `weight_basis` varchar(20) DEFAULT NULL,
  `observed_weights` varchar(500) NOT NULL,
  `mr_pcts` varchar(500) NOT NULL,
  `std_mr_pct` decimal(5,2) DEFAULT NULL,
  `calc_avg_obs` decimal(10,3) DEFAULT NULL,
  `calc_avg_corr` decimal(10,3) DEFAULT NULL,
  `calc_avg_mr` decimal(5,2) DEFAULT NULL,
  `calc_stdev` decimal(10,4) DEFAULT NULL,
  `calc_cv_pct` decimal(7,4) DEFAULT NULL,
  `active` int NOT NULL DEFAULT '1',
  `updated_by` int DEFAULT NULL,
  `updated_date_time` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`spreader_sliver_wt_id`),
  KEY `idx_jssw_co_id` (`co_id`),
  KEY `idx_jssw_entry_date` (`entry_date`),
  KEY `idx_jssw_co_entry_date` (`co_id`,`entry_date`),
  KEY `idx_jssw_mc_id` (`mc_id`),
  KEY `idx_jssw_item_id` (`item_id`)
) ENGINE=InnoDB AUTO_INCREMENT=3 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `jute_sqc_stitch` (
  `stitch_id` int NOT NULL AUTO_INCREMENT,
  `co_id` int NOT NULL,
  `branch_id` int DEFAULT NULL,
  `entry_date` date NOT NULL,
  `mc_id` int DEFAULT NULL,
  `std_stitch` decimal(6,2) DEFAULT NULL,
  `readings` varchar(200) NOT NULL,
  `calc_avg` decimal(6,2) DEFAULT NULL,
  `inspector_name` varchar(120) DEFAULT NULL,
  `active` int NOT NULL DEFAULT '1',
  `updated_by` int DEFAULT NULL,
  `updated_date_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`stitch_id`),
  KEY `idx_jute_sqc_stitch_co_id` (`co_id`),
  KEY `idx_jute_sqc_stitch_entry_date` (`entry_date`)
) ENGINE=InnoDB AUTO_INCREMENT=5 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `jute_sqc_weaving_pick` (
  `weaving_sqc_pick_id` int NOT NULL AUTO_INCREMENT,
  `co_id` int NOT NULL,
  `branch_id` int DEFAULT NULL,
  `entry_date` date NOT NULL,
  `weaving_quality_id` int NOT NULL,
  `machine_id` int NOT NULL,
  `width` decimal(10,3) DEFAULT NULL,
  `picks` decimal(10,3) NOT NULL,
  `active` tinyint(1) NOT NULL DEFAULT '1',
  `updated_by` int DEFAULT NULL,
  `updated_date_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`weaving_sqc_pick_id`),
  KEY `idx_jswp_co_date` (`co_id`,`entry_date`,`active`),
  KEY `idx_jswp_co_quality_date` (`co_id`,`weaving_quality_id`,`entry_date`,`active`)
) ENGINE=InnoDB AUTO_INCREMENT=26 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `jute_sqc_width_picks` (
  `width_picks_id` int NOT NULL AUTO_INCREMENT,
  `co_id` int NOT NULL,
  `branch_id` int DEFAULT NULL,
  `entry_date` date NOT NULL,
  `item_id` int DEFAULT NULL,
  `std_width_cm` decimal(6,2) DEFAULT NULL,
  `std_picks` decimal(6,2) DEFAULT NULL,
  `inspector_name` varchar(120) DEFAULT NULL,
  `active` int NOT NULL DEFAULT '1',
  `updated_by` int DEFAULT NULL,
  `updated_date_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`width_picks_id`),
  KEY `idx_width_picks_co_id` (`co_id`),
  KEY `idx_width_picks_entry_date` (`entry_date`)
) ENGINE=InnoDB AUTO_INCREMENT=5 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `jute_sqc_width_picks_dtl` (
  `width_picks_dtl_id` int NOT NULL AUTO_INCREMENT,
  `width_picks_id` int NOT NULL,
  `loom_id` int DEFAULT NULL,
  `width_cm` decimal(6,2) DEFAULT NULL,
  `picks_dm` decimal(6,2) DEFAULT NULL,
  PRIMARY KEY (`width_picks_dtl_id`),
  KEY `idx_width_picks_dtl_hdr` (`width_picks_id`)
) ENGINE=InnoDB AUTO_INCREMENT=10 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `jute_sqc_yarn_tpi` (
  `yarn_tpi_id` int NOT NULL AUTO_INCREMENT,
  `co_id` int NOT NULL,
  `branch_id` int DEFAULT NULL,
  `entry_date` date NOT NULL,
  `mc_id` int DEFAULT NULL,
  `item_id` int DEFAULT NULL,
  `count_lbs` decimal(10,3) DEFAULT NULL,
  `std_tpi` decimal(10,3) DEFAULT NULL,
  `tp_value` decimal(10,3) DEFAULT NULL,
  `prepared_by` varchar(150) DEFAULT NULL,
  `active` int NOT NULL DEFAULT '1',
  `updated_by` int DEFAULT NULL,
  `updated_date_time` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`yarn_tpi_id`),
  KEY `idx_jytpi_co_id` (`co_id`),
  KEY `idx_jytpi_entry_date` (`entry_date`),
  KEY `idx_jytpi_co_entry_date` (`co_id`,`entry_date`),
  KEY `idx_jytpi_mc_id` (`mc_id`),
  KEY `idx_jytpi_item_id` (`item_id`)
) ENGINE=InnoDB AUTO_INCREMENT=4 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `jute_sqc_yarn_tpi_dtl` (
  `yarn_tpi_dtl_id` int NOT NULL AUTO_INCREMENT,
  `yarn_tpi_id` int NOT NULL,
  `reading_no` int NOT NULL,
  `reading_val` decimal(10,3) DEFAULT NULL,
  PRIMARY KEY (`yarn_tpi_dtl_id`),
  KEY `idx_jytpi_dtl_hdr` (`yarn_tpi_id`)
) ENGINE=InnoDB AUTO_INCREMENT=61 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

SET FOREIGN_KEY_CHECKS=1;

-- Views (base tables now exist)
CREATE OR REPLACE VIEW `vw_weaving_pick_act` AS select `jute_sqc_weaving_pick`.`co_id` AS `co_id`,`jute_sqc_weaving_pick`.`weaving_quality_id` AS `weaving_quality_id`,`jute_sqc_weaving_pick`.`entry_date` AS `entry_date`,avg(`jute_sqc_weaving_pick`.`picks`) AS `avg_picks`,coalesce(stddev_samp(`jute_sqc_weaving_pick`.`picks`),0) AS `std_picks`,min(`jute_sqc_weaving_pick`.`picks`) AS `min_picks`,max(`jute_sqc_weaving_pick`.`picks`) AS `max_picks`,avg(`jute_sqc_weaving_pick`.`width`) AS `avg_width`,min(`jute_sqc_weaving_pick`.`width`) AS `min_width`,max(`jute_sqc_weaving_pick`.`width`) AS `max_width`,count(0) AS `n_obs` from `jute_sqc_weaving_pick` where (`jute_sqc_weaving_pick`.`active` = 1) group by `jute_sqc_weaving_pick`.`co_id`,`jute_sqc_weaving_pick`.`weaving_quality_id`,`jute_sqc_weaving_pick`.`entry_date`;

CREATE OR REPLACE VIEW `vw_weaving_daily` AS select `c`.`weaving_daily_id` AS `weaving_daily_id`,`c`.`co_id` AS `co_id`,`c`.`branch_id` AS `branch_id`,`c`.`tran_date` AS `tran_date`,`c`.`spell_id` AS `spell_id`,`c`.`spell_code` AS `spell_code`,`c`.`shift_bucket` AS `shift_bucket`,`c`.`spell_rank` AS `spell_rank`,`c`.`machine_id` AS `machine_id`,`c`.`mech_code` AS `mech_code`,`c`.`machine_name` AS `machine_name`,`c`.`line_no` AS `line_no`,`c`.`weaving_quality_id` AS `weaving_quality_id`,`c`.`item_id` AS `item_id`,`c`.`item_code` AS `item_code`,`c`.`item_name` AS `item_name`,`c`.`weaving_quality_code` AS `weaving_quality_code`,`c`.`weaving_quality_name` AS `weaving_quality_name`,`c`.`is_composite` AS `is_composite`,`c`.`eb_id` AS `eb_id`,`c`.`beam_no` AS `beam_no`,`c`.`cuts` AS `cuts`,`c`.`close_jugar` AS `close_jugar`,`c`.`less_production` AS `less_production`,`c`.`finished_length` AS `finished_length`,`c`.`ozs_yds` AS `ozs_yds`,`c`.`std_ozs_yds` AS `std_ozs_yds`,`c`.`no_of_jugar_per_cut` AS `no_of_jugar_per_cut`,`c`.`std_speed` AS `std_speed`,`c`.`act_speed` AS `act_speed`,`c`.`std_picks` AS `std_picks`,`c`.`act_picks` AS `act_picks`,`c`.`std_eff` AS `std_eff`,`c`.`target_eff` AS `target_eff`,`c`.`eff_speed` AS `eff_speed`,`c`.`eff_picks` AS `eff_picks`,`c`.`working_hours` AS `working_hours`,`c`.`open_jugar` AS `open_jugar`,`c`.`jugar` AS `jugar`,round(`c`.`production_yds`,3) AS `production_yds`,round((((`c`.`production_yds` * `c`.`ozs_yds`) * 28.35) / 1000),3) AS `production_kg`,round(((((`c`.`production_yds` * `c`.`ozs_yds`) * 28.35) / 1000) / 1000),4) AS `production_mt`,round(`c`.`std_prod_yds`,3) AS `std_prod_yds`,round((case when (`c`.`target_eff` > 0) then ((`c`.`std_prod_yds` * `c`.`target_eff`) / 100) else 0 end),3) AS `target_prod_yds`,round((case when (`c`.`std_prod_yds` > 0) then ((`c`.`production_yds` * 100) / `c`.`std_prod_yds`) else 0 end),2) AS `efficiency`,round((case when (`c`.`std_ozs_yds` is not null) then (((`c`.`production_yds` * `c`.`std_ozs_yds`) * 28.35) / 1000) else 0 end),3) AS `std_prod_kg`,round((case when ((`c`.`std_ozs_yds` is not null) and (`c`.`target_eff` > 0)) then ((((`c`.`production_yds` * `c`.`std_ozs_yds`) * 28.35) / 1000) * (`c`.`target_eff` / 100)) else 0 end),3) AS `target_kg` from (select `b`.`weaving_daily_id` AS `weaving_daily_id`,`b`.`co_id` AS `co_id`,`b`.`branch_id` AS `branch_id`,`b`.`tran_date` AS `tran_date`,`b`.`spell_id` AS `spell_id`,`b`.`spell_code` AS `spell_code`,`b`.`shift_bucket` AS `shift_bucket`,`b`.`spell_rank` AS `spell_rank`,`b`.`machine_id` AS `machine_id`,`b`.`mech_code` AS `mech_code`,`b`.`machine_name` AS `machine_name`,`b`.`line_no` AS `line_no`,`b`.`weaving_quality_id` AS `weaving_quality_id`,`b`.`item_id` AS `item_id`,`b`.`item_code` AS `item_code`,`b`.`item_name` AS `item_name`,`b`.`weaving_quality_code` AS `weaving_quality_code`,`b`.`weaving_quality_name` AS `weaving_quality_name`,`b`.`is_composite` AS `is_composite`,`b`.`eb_id` AS `eb_id`,`b`.`beam_no` AS `beam_no`,`b`.`cuts` AS `cuts`,`b`.`close_jugar` AS `close_jugar`,`b`.`less_production` AS `less_production`,`b`.`finished_length` AS `finished_length`,`b`.`ozs_yds` AS `ozs_yds`,`b`.`std_ozs_yds` AS `std_ozs_yds`,`b`.`no_of_jugar_per_cut` AS `no_of_jugar_per_cut`,`b`.`std_speed` AS `std_speed`,`b`.`act_speed` AS `act_speed`,`b`.`std_picks` AS `std_picks`,`b`.`act_picks` AS `act_picks`,`b`.`std_eff` AS `std_eff`,`b`.`target_eff` AS `target_eff`,`b`.`eff_speed` AS `eff_speed`,`b`.`eff_picks` AS `eff_picks`,`b`.`working_hours` AS `working_hours`,`b`.`open_jugar` AS `open_jugar`,`b`.`total_jugar` AS `total_jugar`,`b`.`total_jugar` AS `jugar`,(case when (`b`.`no_of_jugar_per_cut` > 0) then ((`b`.`total_jugar` * `b`.`finished_length`) / `b`.`no_of_jugar_per_cut`) else 0 end) AS `production_yds`,(case when ((36 * `b`.`std_picks`) > 0) then (((`b`.`eff_speed` * `b`.`working_hours`) * 60) / (36 * `b`.`std_picks`)) else 0 end) AS `std_prod_yds` from (select `a`.`weaving_daily_id` AS `weaving_daily_id`,`a`.`co_id` AS `co_id`,`a`.`branch_id` AS `branch_id`,`a`.`tran_date` AS `tran_date`,`a`.`spell_id` AS `spell_id`,`a`.`spell_code` AS `spell_code`,`a`.`shift_bucket` AS `shift_bucket`,`a`.`spell_rank` AS `spell_rank`,`a`.`machine_id` AS `machine_id`,`a`.`mech_code` AS `mech_code`,`a`.`machine_name` AS `machine_name`,`a`.`line_no` AS `line_no`,`a`.`weaving_quality_id` AS `weaving_quality_id`,`a`.`item_id` AS `item_id`,`a`.`item_code` AS `item_code`,`a`.`item_name` AS `item_name`,`a`.`weaving_quality_code` AS `weaving_quality_code`,`a`.`weaving_quality_name` AS `weaving_quality_name`,`a`.`is_composite` AS `is_composite`,`a`.`eb_id` AS `eb_id`,`a`.`beam_no` AS `beam_no`,`a`.`cuts` AS `cuts`,`a`.`close_jugar` AS `close_jugar`,`a`.`less_production` AS `less_production`,`a`.`finished_length` AS `finished_length`,`a`.`ozs_yds` AS `ozs_yds`,`a`.`std_ozs_yds` AS `std_ozs_yds`,`a`.`no_of_jugar_per_cut` AS `no_of_jugar_per_cut`,`a`.`std_speed` AS `std_speed`,`a`.`act_speed` AS `act_speed`,`a`.`std_picks` AS `std_picks`,`a`.`act_picks` AS `act_picks`,`a`.`std_eff` AS `std_eff`,`a`.`target_eff` AS `target_eff`,`a`.`eff_speed` AS `eff_speed`,`a`.`eff_picks` AS `eff_picks`,`a`.`working_hours` AS `working_hours`,`a`.`open_jugar` AS `open_jugar`,((((`a`.`cuts` * `a`.`no_of_jugar_per_cut`) + `a`.`close_jugar`) - `a`.`open_jugar`) - coalesce(`a`.`less_production`,0)) AS `total_jugar` from (select `wd`.`weaving_daily_id` AS `weaving_daily_id`,`wd`.`co_id` AS `co_id`,`wd`.`branch_id` AS `branch_id`,`wd`.`tran_date` AS `tran_date`,`wd`.`spell_id` AS `spell_id`,`sp`.`spell_code` AS `spell_code`,left(`sp`.`spell_code`,1) AS `shift_bucket`,(case `sp`.`spell_code` when 'A1' then 1 when 'B1' then 2 when 'A2' then 3 when 'B2' then 4 when 'C' then 5 else 99 end) AS `spell_rank`,`wd`.`machine_id` AS `machine_id`,`m`.`mech_code` AS `mech_code`,`m`.`machine_name` AS `machine_name`,`m`.`line_no` AS `line_no`,`wd`.`weaving_quality_id` AS `weaving_quality_id`,`q`.`item_id` AS `item_id`,`im`.`item_code` AS `item_code`,`im`.`item_name` AS `item_name`,`q`.`weaving_quality_code` AS `weaving_quality_code`,`q`.`weaving_quality_name` AS `weaving_quality_name`,`q`.`is_composite` AS `is_composite`,`wd`.`eb_id` AS `eb_id`,`wd`.`beam_no` AS `beam_no`,`wd`.`cuts` AS `cuts`,coalesce(`wd`.`close_jugar`,0) AS `close_jugar`,coalesce(`wd`.`less_production`,0) AS `less_production`,coalesce(`q`.`finished_length`,0) AS `finished_length`,coalesce(`q`.`ozs_yds`,0) AS `ozs_yds`,`q`.`std_ozs_yds` AS `std_ozs_yds`,coalesce(`q`.`no_of_jugar_per_cut`,0) AS `no_of_jugar_per_cut`,coalesce(`s`.`std_speed`,0) AS `std_speed`,coalesce(`s`.`act_speed`,0) AS `act_speed`,coalesce(`s`.`std_picks`,0) AS `std_picks`,coalesce(`s`.`act_picks`,0) AS `act_picks`,coalesce(`s`.`std_eff`,0) AS `std_eff`,coalesce(`s`.`target_eff`,0) AS `target_eff`,(case when (coalesce(`s`.`act_speed`,0) > 0) then `s`.`act_speed` else coalesce(`s`.`std_speed`,0) end) AS `eff_speed`,(case when (coalesce(`s`.`act_picks`,0) > 0) then `s`.`act_picks` else coalesce(`s`.`std_picks`,0) end) AS `eff_picks`,greatest(0,(coalesce(`sp`.`working_hours`,0) - coalesce((select sum(`st`.`stoppage_hours`) from `jute_prod_stoppage_hours` `st` where ((`st`.`active` = 1) and (`st`.`co_id` = `wd`.`co_id`) and (`st`.`machine_id` = `wd`.`machine_id`) and (`st`.`tran_date` = `wd`.`tran_date`) and (`st`.`spell_id` = `wd`.`spell_id`))),0))) AS `working_hours`,coalesce(lag(`wd`.`close_jugar`) OVER (PARTITION BY `wd`.`co_id`,`wd`.`machine_id`,`wd`.`weaving_quality_id` ORDER BY `wd`.`tran_date`,(case `sp`.`spell_code` when 'A1' then 1 when 'B1' then 2 when 'A2' then 3 when 'B2' then 4 when 'C' then 5 else 99 end),`wd`.`weaving_daily_id` ) ,0) AS `open_jugar` from (((((`jute_prod_weaving_daily` `wd` left join `spell_mst` `sp` on((`sp`.`spell_id` = `wd`.`spell_id`))) left join `machine_mst` `m` on((`m`.`machine_id` = `wd`.`machine_id`))) left join `jute_prod_weaving_quality` `q` on((`q`.`weaving_quality_id` = `wd`.`weaving_quality_id`))) left join `item_mst` `im` on((`im`.`item_id` = `q`.`item_id`))) left join (select `d2`.`weaving_daily_id` AS `weaving_daily_id`,(select `tm`.`value` from `jute_prod_weaving_target_map` `tm` where ((`tm`.`co_id` = `d2`.`co_id`) and (`tm`.`ref_id` = `d2`.`mid`) and (`tm`.`id_type` = 'mcid') and (`tm`.`value_role` = 'standard') and (`tm`.`param` = 'speed') and (`tm`.`active` = 1) and (`tm`.`effective_date` <= `d2`.`tran_date`)) order by `tm`.`effective_date` desc,`tm`.`weaving_target_map_id` desc limit 1) AS `std_speed`,(select `tm`.`value` from `jute_prod_weaving_target_map` `tm` where ((`tm`.`co_id` = `d2`.`co_id`) and (`tm`.`ref_id` = `d2`.`mid`) and (`tm`.`id_type` = 'mcid') and (`tm`.`value_role` = 'actual') and (`tm`.`param` = 'speed') and (`tm`.`active` = 1) and (`tm`.`effective_date` <= `d2`.`tran_date`)) order by `tm`.`effective_date` desc,`tm`.`weaving_target_map_id` desc limit 1) AS `act_speed`,(select `pv`.`avg_picks` from `vw_weaving_pick_act` `pv` where ((`pv`.`co_id` = `d2`.`co_id`) and (`pv`.`weaving_quality_id` = `d2`.`qid`) and (`pv`.`entry_date` = `d2`.`tran_date`)) limit 1) AS `std_picks`,(select `pv`.`avg_picks` from `vw_weaving_pick_act` `pv` where ((`pv`.`co_id` = `d2`.`co_id`) and (`pv`.`weaving_quality_id` = `d2`.`qid`) and (`pv`.`entry_date` <= `d2`.`tran_date`)) order by `pv`.`entry_date` desc limit 1) AS `act_picks`,(select `tm`.`value` from `jute_prod_weaving_target_map` `tm` where ((`tm`.`co_id` = `d2`.`co_id`) and (`tm`.`ref_id` = `d2`.`qid`) and (`tm`.`id_type` = 'qid') and (`tm`.`value_role` = 'standard') and (`tm`.`param` = 'eff') and (`tm`.`active` = 1) and (`tm`.`effective_date` <= `d2`.`tran_date`)) order by `tm`.`effective_date` desc,`tm`.`weaving_target_map_id` desc limit 1) AS `std_eff`,(select `tm`.`value` from `jute_prod_weaving_target_map` `tm` where ((`tm`.`co_id` = `d2`.`co_id`) and (`tm`.`ref_id` = `d2`.`qid`) and (`tm`.`id_type` = 'qid') and (`tm`.`value_role` = 'target') and (`tm`.`param` = 'eff') and (`tm`.`active` = 1) and (`tm`.`effective_date` <= `d2`.`tran_date`)) order by `tm`.`effective_date` desc,`tm`.`weaving_target_map_id` desc limit 1) AS `target_eff` from (select `w`.`weaving_daily_id` AS `weaving_daily_id`,`w`.`co_id` AS `co_id`,`w`.`tran_date` AS `tran_date`,`w`.`weaving_quality_id` AS `qid`,`w`.`machine_id` AS `mid` from `jute_prod_weaving_daily` `w` where (`w`.`active` = 1)) `d2`) `s` on((`s`.`weaving_daily_id` = `wd`.`weaving_daily_id`))) where (`wd`.`active` = 1)) `a`) `b`) `c`;

CREATE OR REPLACE VIEW `vw_winding_daily_reconciled` AS select `bm`.`co_id` AS `co_id`,`d`.`branch_id` AS `branch_id`,`wd`.`tran_date` AS `tran_date`,`wd`.`spell_id` AS `spell_id`,`wd`.`machine_id` AS `machine_id`,`wd`.`item_id` AS `item_id`,((sum(`wd`.`production_qty`) - coalesce((select max(`jo`.`weight`) from `jute_prod_winding_jugar` `jo` where ((`jo`.`tran_date` = `wd`.`tran_date`) and (`jo`.`spell_id` = `wd`.`spell_id`) and (`jo`.`machine_id` = `wd`.`machine_id`) and (`jo`.`open_close` = 'O') and (`jo`.`active` = 1))),0)) + coalesce((select max(`jc`.`weight`) from `jute_prod_winding_jugar` `jc` where ((`jc`.`tran_date` = `wd`.`tran_date`) and (`jc`.`spell_id` = `wd`.`spell_id`) and (`jc`.`machine_id` = `wd`.`machine_id`) and (`jc`.`open_close` = 'C') and (`jc`.`active` = 1))),0)) AS `reconciled_qty` from (((`jute_prod_winding_doff` `wd` join `machine_mst` `m` on((`m`.`machine_id` = `wd`.`machine_id`))) join `dept_mst` `d` on((`d`.`dept_id` = `m`.`dept_id`))) join `branch_mst` `bm` on((`bm`.`branch_id` = `d`.`branch_id`))) where (`wd`.`active` = 1) group by `bm`.`co_id`,`d`.`branch_id`,`wd`.`tran_date`,`wd`.`spell_id`,`wd`.`machine_id`,`wd`.`item_id`;

CREATE OR REPLACE VIEW `vw_spinning_planning_grid` AS select `eff`.`co_id` AS `co_id`,`eff`.`branch_id` AS `branch_id`,`eff`.`tran_date` AS `tran_date`,`eff`.`spell_id` AS `spell_id`,`eff`.`spell_code` AS `spell_code`,`eff`.`shift_bucket` AS `shift_bucket`,`eff`.`machine_id` AS `machine_id`,`eff`.`mech_code` AS `mech_code`,`eff`.`machine_name` AS `machine_name`,`eff`.`item_id` AS `item_id`,`eff`.`quality_code` AS `quality_code`,`eff`.`eb_id` AS `eb_id`,`eff`.`spindles` AS `spindles`,`eff`.`minutes` AS `minutes`,`eff`.`act_count` AS `act_count`,`eff`.`std_count` AS `std_count`,`eff`.`std_speed` AS `std_speed`,`eff`.`actual_speed` AS `actual_speed`,`eff`.`target_speed` AS `target_speed`,`eff`.`std_tpi` AS `std_tpi`,`eff`.`actual_tpi` AS `actual_tpi`,`eff`.`target_tpi` AS `target_tpi`,`eff`.`std_eff` AS `std_eff`,`eff`.`target_eff` AS `target_eff`,`eff`.`p100prod` AS `p100prod`,`eff`.`std_prod` AS `std_prod`,`eff`.`target_prod` AS `target_prod`,`eff`.`act_prod_doff` AS `act_prod_doff`,`eff`.`winding_total` AS `winding_total`,`eff`.`act_prod_wind` AS `act_prod_wind`,`eff`.`eff_doff` AS `eff_doff`,coalesce(round(((`eff`.`act_prod_wind` / nullif(`eff`.`p100prod`,0)) * 100),2),0) AS `eff_winding` from (select `calc`.`co_id` AS `co_id`,`calc`.`branch_id` AS `branch_id`,`calc`.`tran_date` AS `tran_date`,`calc`.`spell_id` AS `spell_id`,`calc`.`spell_code` AS `spell_code`,`calc`.`shift_bucket` AS `shift_bucket`,`calc`.`machine_id` AS `machine_id`,`calc`.`mech_code` AS `mech_code`,`calc`.`machine_name` AS `machine_name`,`calc`.`item_id` AS `item_id`,`calc`.`quality_code` AS `quality_code`,`calc`.`eb_id` AS `eb_id`,`calc`.`spindles` AS `spindles`,`calc`.`minutes` AS `minutes`,`calc`.`act_count` AS `act_count`,`calc`.`std_count` AS `std_count`,`calc`.`std_speed` AS `std_speed`,`calc`.`actual_speed` AS `actual_speed`,`calc`.`target_speed` AS `target_speed`,`calc`.`std_tpi` AS `std_tpi`,`calc`.`actual_tpi` AS `actual_tpi`,`calc`.`target_tpi` AS `target_tpi`,`calc`.`std_eff` AS `std_eff`,`calc`.`target_eff` AS `target_eff`,`calc`.`act_prod_doff` AS `act_prod_doff`,`calc`.`winding_total` AS `winding_total`,`calc`.`p100prod` AS `p100prod`,`calc`.`std_prod` AS `std_prod`,`calc`.`target_prod` AS `target_prod`,`calc`.`eff_doff` AS `eff_doff`,coalesce(round(((`calc`.`winding_total` * `calc`.`act_prod_doff`) / nullif(sum(`calc`.`act_prod_doff`) OVER (PARTITION BY `calc`.`co_id`,`calc`.`tran_date`,`calc`.`item_id`,`calc`.`shift_bucket` ) ,0)),3),0) AS `act_prod_wind` from (select `r`.`co_id` AS `co_id`,`r`.`branch_id` AS `branch_id`,`r`.`tran_date` AS `tran_date`,`r`.`spell_id` AS `spell_id`,`r`.`spell_code` AS `spell_code`,`r`.`shift_bucket` AS `shift_bucket`,`r`.`machine_id` AS `machine_id`,`r`.`mech_code` AS `mech_code`,`r`.`machine_name` AS `machine_name`,`r`.`item_id` AS `item_id`,`r`.`quality_code` AS `quality_code`,`r`.`eb_id` AS `eb_id`,`r`.`spindles` AS `spindles`,`r`.`minutes` AS `minutes`,`r`.`act_count` AS `act_count`,`r`.`std_count` AS `std_count`,`r`.`std_speed` AS `std_speed`,`r`.`actual_speed` AS `actual_speed`,`r`.`target_speed` AS `target_speed`,`r`.`std_tpi` AS `std_tpi`,`r`.`actual_tpi` AS `actual_tpi`,`r`.`target_tpi` AS `target_tpi`,`r`.`std_eff` AS `std_eff`,`r`.`target_eff` AS `target_eff`,`r`.`act_prod_doff` AS `act_prod_doff`,`r`.`winding_total` AS `winding_total`,`r`.`p100prod` AS `p100prod`,round(((`r`.`p100prod` * `r`.`std_eff`) / 100),3) AS `std_prod`,round(((`r`.`p100prod` * `r`.`target_eff`) / 100),3) AS `target_prod`,coalesce(round(((`r`.`act_prod_doff` / nullif(`r`.`p100prod`,0)) * 100),2),0) AS `eff_doff` from (select `b`.`co_id` AS `co_id`,`b`.`branch_id` AS `branch_id`,`b`.`tran_date` AS `tran_date`,`b`.`spell_id` AS `spell_id`,`b`.`spell_code` AS `spell_code`,`b`.`shift_bucket` AS `shift_bucket`,`b`.`machine_id` AS `machine_id`,`b`.`mech_code` AS `mech_code`,`b`.`machine_name` AS `machine_name`,`b`.`item_id` AS `item_id`,`b`.`quality_code` AS `quality_code`,`b`.`eb_id` AS `eb_id`,`b`.`spindles` AS `spindles`,`b`.`minutes` AS `minutes`,`b`.`act_count` AS `act_count`,`b`.`std_count` AS `std_count`,`b`.`std_speed` AS `std_speed`,`b`.`actual_speed` AS `actual_speed`,`b`.`target_speed` AS `target_speed`,`b`.`std_tpi` AS `std_tpi`,`b`.`actual_tpi` AS `actual_tpi`,`b`.`target_tpi` AS `target_tpi`,`b`.`std_eff` AS `std_eff`,`b`.`target_eff` AS `target_eff`,`b`.`act_prod_doff` AS `act_prod_doff`,`b`.`winding_total` AS `winding_total`,coalesce(round(((((`b`.`std_speed` * `b`.`minutes`) * `b`.`act_count`) * `b`.`spindles`) / (((36 * 14400) * 2.2046) * nullif(`b`.`std_tpi`,0))),0),0) AS `p100prod` from (select `bm`.`co_id` AS `co_id`,`d`.`branch_id` AS `branch_id`,`f`.`tran_date` AS `tran_date`,`f`.`spell_id` AS `spell_id`,`sp`.`spell_code` AS `spell_code`,left(`sp`.`spell_code`,1) AS `shift_bucket`,`f`.`mc_eb_id` AS `machine_id`,`m`.`mech_code` AS `mech_code`,`m`.`machine_name` AS `machine_name`,`f`.`item_id` AS `item_id`,`im`.`item_code` AS `quality_code`,cast(NULL as signed) AS `eb_id`,cast(coalesce((select `t`.`value` from `jute_prod_spng_target_map` `t` where ((`t`.`co_id` = `bm`.`co_id`) and (`t`.`ref_id` = `f`.`mc_eb_id`) and (`t`.`id_type` = 'mcid') and (`t`.`value_role` = 'standard') and (`t`.`param` = 'spindles') and (`t`.`active` = 1) and (`t`.`effective_date` <= `f`.`tran_date`)) order by `t`.`effective_date` desc limit 1),0) as signed) AS `spindles`,(case when (`sp`.`working_hours` is not null) then round((`sp`.`working_hours` * 60),0) when (`sp`.`spell_code` = 'A1') then 300 when (`sp`.`spell_code` = 'A2') then 180 else 0 end) AS `minutes`,coalesce((select avg(`c`.`observed_count`) from `jute_sqc_spinning_count` `c` where ((`c`.`co_id` = `bm`.`co_id`) and (`c`.`item_id` = `f`.`item_id`) and (`c`.`entry_date` = `f`.`tran_date`) and (`c`.`active` = 1))),0) AS `act_count`,coalesce(`ym`.`jute_yarn_count`,0) AS `std_count`,coalesce((select `t`.`value` from `jute_prod_spng_target_map` `t` where ((`t`.`co_id` = `bm`.`co_id`) and (`t`.`ref_id` = `f`.`mc_eb_id`) and (`t`.`id_type` = 'mcid') and (`t`.`value_role` = 'standard') and (`t`.`param` = 'speed') and (`t`.`active` = 1) and (`t`.`effective_date` <= `f`.`tran_date`)) order by `t`.`effective_date` desc limit 1),0) AS `std_speed`,coalesce((select `t`.`value` from `jute_prod_spng_target_map` `t` where ((`t`.`co_id` = `bm`.`co_id`) and (`t`.`ref_id` = `f`.`mc_eb_id`) and (`t`.`id_type` = 'mcid') and (`t`.`value_role` = 'actual') and (`t`.`param` = 'speed') and (`t`.`active` = 1) and (`t`.`effective_date` <= `f`.`tran_date`)) order by `t`.`effective_date` desc limit 1),0) AS `actual_speed`,coalesce((select `t`.`value` from `jute_prod_spng_target_map` `t` where ((`t`.`co_id` = `bm`.`co_id`) and (`t`.`ref_id` = `f`.`mc_eb_id`) and (`t`.`id_type` = 'mcid') and (`t`.`value_role` = 'target') and (`t`.`param` = 'speed') and (`t`.`active` = 1) and (`t`.`effective_date` <= `f`.`tran_date`)) order by `t`.`effective_date` desc limit 1),0) AS `target_speed`,coalesce((select `t`.`value` from `jute_prod_spng_target_map` `t` where ((`t`.`co_id` = `bm`.`co_id`) and (`t`.`ref_id` = `f`.`item_id`) and (`t`.`id_type` = 'qid') and (`t`.`value_role` = 'standard') and (`t`.`param` = 'tpi') and (`t`.`active` = 1) and (`t`.`effective_date` <= `f`.`tran_date`)) order by `t`.`effective_date` desc limit 1),0) AS `std_tpi`,coalesce((select `t`.`value` from `jute_prod_spng_target_map` `t` where ((`t`.`co_id` = `bm`.`co_id`) and (`t`.`ref_id` = `f`.`item_id`) and (`t`.`id_type` = 'qid') and (`t`.`value_role` = 'actual') and (`t`.`param` = 'tpi') and (`t`.`active` = 1) and (`t`.`effective_date` <= `f`.`tran_date`)) order by `t`.`effective_date` desc limit 1),0) AS `actual_tpi`,coalesce((select `t`.`value` from `jute_prod_spng_target_map` `t` where ((`t`.`co_id` = `bm`.`co_id`) and (`t`.`ref_id` = `f`.`item_id`) and (`t`.`id_type` = 'qid') and (`t`.`value_role` = 'target') and (`t`.`param` = 'tpi') and (`t`.`active` = 1) and (`t`.`effective_date` <= `f`.`tran_date`)) order by `t`.`effective_date` desc limit 1),0) AS `target_tpi`,coalesce((select `t`.`value` from `jute_prod_spng_target_map` `t` where ((`t`.`co_id` = `bm`.`co_id`) and (`t`.`ref_id` = `f`.`item_id`) and (`t`.`id_type` = 'qid') and (`t`.`value_role` = 'standard') and (`t`.`param` = 'eff') and (`t`.`active` = 1) and (`t`.`effective_date` <= `f`.`tran_date`)) order by `t`.`effective_date` desc limit 1),0) AS `std_eff`,coalesce((select `t`.`value` from `jute_prod_spng_target_map` `t` where ((`t`.`co_id` = `bm`.`co_id`) and (`t`.`ref_id` = `f`.`item_id`) and (`t`.`id_type` = 'qid') and (`t`.`value_role` = 'target') and (`t`.`param` = 'eff') and (`t`.`active` = 1) and (`t`.`effective_date` <= `f`.`tran_date`)) order by `t`.`effective_date` desc limit 1),0) AS `target_eff`,coalesce((select sum(`dd`.`net_weight`) from `daily_doff_tbl` `dd` where ((`dd`.`doff_date` = `f`.`tran_date`) and (`dd`.`spell` = `f`.`spell_id`) and (`dd`.`mc_id` = `f`.`mc_eb_id`) and ((`dd`.`active` = 1) or (`dd`.`active` is null)))),0) AS `act_prod_doff`,coalesce((select sum(`w`.`reconciled_qty`) from (`vw_winding_daily_reconciled` `w` join `spell_mst` `wsp` on((`wsp`.`spell_id` = `w`.`spell_id`))) where ((`w`.`co_id` = `bm`.`co_id`) and (`w`.`item_id` = `f`.`item_id`) and (`w`.`tran_date` = `f`.`tran_date`) and (left(`wsp`.`spell_code`,1) = left(`sp`.`spell_code`,1)))),0) AS `winding_total` from (((((((`daily_doff_frames_winding` `f` join `machine_mst` `m` on((`m`.`machine_id` = `f`.`mc_eb_id`))) join `machine_type_mst` `mt` on(((`mt`.`machine_type_id` = `m`.`machine_type_id`) and (`mt`.`active` = 1) and (`mt`.`machine_type_name` = 'Spinning')))) join `dept_mst` `d` on((`d`.`dept_id` = `m`.`dept_id`))) join `branch_mst` `bm` on((`bm`.`branch_id` = `d`.`branch_id`))) left join (select `spell_mst`.`spell_id` AS `spell_id`,`spell_mst`.`spell_code` AS `spell_code`,`spell_mst`.`working_hours` AS `working_hours` from `spell_mst` where (`spell_mst`.`status` = 1)) `sp` on((`sp`.`spell_id` = `f`.`spell_id`))) left join `item_mst` `im` on((`im`.`item_id` = `f`.`item_id`))) left join `jute_yarn_mst` `ym` on((`ym`.`item_id` = `f`.`item_id`))) where ((`f`.`spg_wdg` = 'S') and (`f`.`item_id` is not null) and ((`f`.`active` = 1) or (`f`.`active` is null)))) `b`) `r`) `calc`) `eff`;
