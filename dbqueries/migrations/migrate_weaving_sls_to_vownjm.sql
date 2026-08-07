-- Migration: backfill weaving-production objects into vownjm (structure only)
-- Source: sls | Target: vownjm | Date: 2026-07-06
-- Reason: /api/weavingProd/* 500s on vownjm — tables never migrated (schema drift).
-- ROLLBACK:
--   DROP VIEW IF EXISTS vw_weaving_daily
--   DROP TABLE IF EXISTS jute_prod_weaving_beam_map
--   DROP TABLE IF EXISTS jute_prod_weaving_daily
--   DROP TABLE IF EXISTS jute_prod_weaving_quality_map
--   DROP TABLE IF EXISTS jute_prod_weaving_quality

SET FOREIGN_KEY_CHECKS=0;

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
) ENGINE=InnoDB AUTO_INCREMENT=565 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

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
) ENGINE=InnoDB AUTO_INCREMENT=2531273 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

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

SET FOREIGN_KEY_CHECKS=1;

CREATE OR REPLACE VIEW `vw_weaving_daily` AS select `c`.`weaving_daily_id` AS `weaving_daily_id`,`c`.`co_id` AS `co_id`,`c`.`branch_id` AS `branch_id`,`c`.`tran_date` AS `tran_date`,`c`.`spell_id` AS `spell_id`,`c`.`spell_code` AS `spell_code`,`c`.`shift_bucket` AS `shift_bucket`,`c`.`spell_rank` AS `spell_rank`,`c`.`machine_id` AS `machine_id`,`c`.`mech_code` AS `mech_code`,`c`.`machine_name` AS `machine_name`,`c`.`line_no` AS `line_no`,`c`.`weaving_quality_id` AS `weaving_quality_id`,`c`.`item_id` AS `item_id`,`c`.`item_code` AS `item_code`,`c`.`item_name` AS `item_name`,`c`.`weaving_quality_code` AS `weaving_quality_code`,`c`.`weaving_quality_name` AS `weaving_quality_name`,`c`.`is_composite` AS `is_composite`,`c`.`eb_id` AS `eb_id`,`c`.`beam_no` AS `beam_no`,`c`.`cuts` AS `cuts`,`c`.`close_jugar` AS `close_jugar`,`c`.`less_production` AS `less_production`,`c`.`finished_length` AS `finished_length`,`c`.`ozs_yds` AS `ozs_yds`,`c`.`std_ozs_yds` AS `std_ozs_yds`,`c`.`no_of_jugar_per_cut` AS `no_of_jugar_per_cut`,`c`.`std_speed` AS `std_speed`,`c`.`act_speed` AS `act_speed`,`c`.`std_picks` AS `std_picks`,`c`.`act_picks` AS `act_picks`,`c`.`std_eff` AS `std_eff`,`c`.`target_eff` AS `target_eff`,`c`.`eff_speed` AS `eff_speed`,`c`.`eff_picks` AS `eff_picks`,`c`.`working_hours` AS `working_hours`,`c`.`open_jugar` AS `open_jugar`,`c`.`jugar` AS `jugar`,round(`c`.`production_yds`,3) AS `production_yds`,round((((`c`.`production_yds` * `c`.`ozs_yds`) * 28.35) / 1000),3) AS `production_kg`,round(((((`c`.`production_yds` * `c`.`ozs_yds`) * 28.35) / 1000) / 1000),4) AS `production_mt`,round(`c`.`std_prod_yds`,3) AS `std_prod_yds`,round((case when (`c`.`target_eff` > 0) then ((`c`.`std_prod_yds` * `c`.`target_eff`) / 100) else 0 end),3) AS `target_prod_yds`,round((case when (`c`.`std_prod_yds` > 0) then ((`c`.`production_yds` * 100) / `c`.`std_prod_yds`) else 0 end),2) AS `efficiency`,round((case when (`c`.`std_ozs_yds` is not null) then (((`c`.`production_yds` * `c`.`std_ozs_yds`) * 28.35) / 1000) else 0 end),3) AS `std_prod_kg`,round((case when ((`c`.`std_ozs_yds` is not null) and (`c`.`target_eff` > 0)) then ((((`c`.`production_yds` * `c`.`std_ozs_yds`) * 28.35) / 1000) * (`c`.`target_eff` / 100)) else 0 end),3) AS `target_kg` from (select `b`.`weaving_daily_id` AS `weaving_daily_id`,`b`.`co_id` AS `co_id`,`b`.`branch_id` AS `branch_id`,`b`.`tran_date` AS `tran_date`,`b`.`spell_id` AS `spell_id`,`b`.`spell_code` AS `spell_code`,`b`.`shift_bucket` AS `shift_bucket`,`b`.`spell_rank` AS `spell_rank`,`b`.`machine_id` AS `machine_id`,`b`.`mech_code` AS `mech_code`,`b`.`machine_name` AS `machine_name`,`b`.`line_no` AS `line_no`,`b`.`weaving_quality_id` AS `weaving_quality_id`,`b`.`item_id` AS `item_id`,`b`.`item_code` AS `item_code`,`b`.`item_name` AS `item_name`,`b`.`weaving_quality_code` AS `weaving_quality_code`,`b`.`weaving_quality_name` AS `weaving_quality_name`,`b`.`is_composite` AS `is_composite`,`b`.`eb_id` AS `eb_id`,`b`.`beam_no` AS `beam_no`,`b`.`cuts` AS `cuts`,`b`.`close_jugar` AS `close_jugar`,`b`.`less_production` AS `less_production`,`b`.`finished_length` AS `finished_length`,`b`.`ozs_yds` AS `ozs_yds`,`b`.`std_ozs_yds` AS `std_ozs_yds`,`b`.`no_of_jugar_per_cut` AS `no_of_jugar_per_cut`,`b`.`std_speed` AS `std_speed`,`b`.`act_speed` AS `act_speed`,`b`.`std_picks` AS `std_picks`,`b`.`act_picks` AS `act_picks`,`b`.`std_eff` AS `std_eff`,`b`.`target_eff` AS `target_eff`,`b`.`eff_speed` AS `eff_speed`,`b`.`eff_picks` AS `eff_picks`,`b`.`working_hours` AS `working_hours`,`b`.`open_jugar` AS `open_jugar`,`b`.`total_jugar` AS `total_jugar`,`b`.`total_jugar` AS `jugar`,(case when (`b`.`no_of_jugar_per_cut` > 0) then ((`b`.`total_jugar` * `b`.`finished_length`) / `b`.`no_of_jugar_per_cut`) else 0 end) AS `production_yds`,(case when ((36 * `b`.`std_picks`) > 0) then (((`b`.`eff_speed` * `b`.`working_hours`) * 60) / (36 * `b`.`std_picks`)) else 0 end) AS `std_prod_yds` from (select `a`.`weaving_daily_id` AS `weaving_daily_id`,`a`.`co_id` AS `co_id`,`a`.`branch_id` AS `branch_id`,`a`.`tran_date` AS `tran_date`,`a`.`spell_id` AS `spell_id`,`a`.`spell_code` AS `spell_code`,`a`.`shift_bucket` AS `shift_bucket`,`a`.`spell_rank` AS `spell_rank`,`a`.`machine_id` AS `machine_id`,`a`.`mech_code` AS `mech_code`,`a`.`machine_name` AS `machine_name`,`a`.`line_no` AS `line_no`,`a`.`weaving_quality_id` AS `weaving_quality_id`,`a`.`item_id` AS `item_id`,`a`.`item_code` AS `item_code`,`a`.`item_name` AS `item_name`,`a`.`weaving_quality_code` AS `weaving_quality_code`,`a`.`weaving_quality_name` AS `weaving_quality_name`,`a`.`is_composite` AS `is_composite`,`a`.`eb_id` AS `eb_id`,`a`.`beam_no` AS `beam_no`,`a`.`cuts` AS `cuts`,`a`.`close_jugar` AS `close_jugar`,`a`.`less_production` AS `less_production`,`a`.`finished_length` AS `finished_length`,`a`.`ozs_yds` AS `ozs_yds`,`a`.`std_ozs_yds` AS `std_ozs_yds`,`a`.`no_of_jugar_per_cut` AS `no_of_jugar_per_cut`,`a`.`std_speed` AS `std_speed`,`a`.`act_speed` AS `act_speed`,`a`.`std_picks` AS `std_picks`,`a`.`act_picks` AS `act_picks`,`a`.`std_eff` AS `std_eff`,`a`.`target_eff` AS `target_eff`,`a`.`eff_speed` AS `eff_speed`,`a`.`eff_picks` AS `eff_picks`,`a`.`working_hours` AS `working_hours`,`a`.`open_jugar` AS `open_jugar`,((((`a`.`cuts` * `a`.`no_of_jugar_per_cut`) + `a`.`close_jugar`) - `a`.`open_jugar`) - coalesce(`a`.`less_production`,0)) AS `total_jugar` from (select `wd`.`weaving_daily_id` AS `weaving_daily_id`,`wd`.`co_id` AS `co_id`,`wd`.`branch_id` AS `branch_id`,`wd`.`tran_date` AS `tran_date`,`wd`.`spell_id` AS `spell_id`,`sp`.`spell_code` AS `spell_code`,left(`sp`.`spell_code`,1) AS `shift_bucket`,(case `sp`.`spell_code` when 'A1' then 1 when 'B1' then 2 when 'A2' then 3 when 'B2' then 4 when 'C' then 5 else 99 end) AS `spell_rank`,`wd`.`machine_id` AS `machine_id`,`m`.`mech_code` AS `mech_code`,`m`.`machine_name` AS `machine_name`,`m`.`line_no` AS `line_no`,`wd`.`weaving_quality_id` AS `weaving_quality_id`,`q`.`item_id` AS `item_id`,`im`.`item_code` AS `item_code`,`im`.`item_name` AS `item_name`,`q`.`weaving_quality_code` AS `weaving_quality_code`,`q`.`weaving_quality_name` AS `weaving_quality_name`,`q`.`is_composite` AS `is_composite`,`wd`.`eb_id` AS `eb_id`,`wd`.`beam_no` AS `beam_no`,`wd`.`cuts` AS `cuts`,coalesce(`wd`.`close_jugar`,0) AS `close_jugar`,coalesce(`wd`.`less_production`,0) AS `less_production`,coalesce(`q`.`finished_length`,0) AS `finished_length`,coalesce(`q`.`ozs_yds`,0) AS `ozs_yds`,`q`.`std_ozs_yds` AS `std_ozs_yds`,coalesce(`q`.`no_of_jugar_per_cut`,0) AS `no_of_jugar_per_cut`,coalesce(`s`.`std_speed`,0) AS `std_speed`,coalesce(`s`.`act_speed`,0) AS `act_speed`,coalesce(`s`.`std_picks`,0) AS `std_picks`,coalesce(`s`.`act_picks`,0) AS `act_picks`,coalesce(`s`.`std_eff`,0) AS `std_eff`,coalesce(`s`.`target_eff`,0) AS `target_eff`,(case when (coalesce(`s`.`act_speed`,0) > 0) then `s`.`act_speed` else coalesce(`s`.`std_speed`,0) end) AS `eff_speed`,(case when (coalesce(`s`.`act_picks`,0) > 0) then `s`.`act_picks` else coalesce(`s`.`std_picks`,0) end) AS `eff_picks`,greatest(0,(coalesce(`sp`.`working_hours`,0) - coalesce((select sum(`st`.`stoppage_hours`) from `jute_prod_stoppage_hours` `st` where ((`st`.`active` = 1) and (`st`.`co_id` = `wd`.`co_id`) and (`st`.`machine_id` = `wd`.`machine_id`) and (`st`.`tran_date` = `wd`.`tran_date`) and (`st`.`spell_id` = `wd`.`spell_id`))),0))) AS `working_hours`,coalesce(lag(`wd`.`close_jugar`) OVER (PARTITION BY `wd`.`co_id`,`wd`.`machine_id`,`wd`.`weaving_quality_id` ORDER BY `wd`.`tran_date`,(case `sp`.`spell_code` when 'A1' then 1 when 'B1' then 2 when 'A2' then 3 when 'B2' then 4 when 'C' then 5 else 99 end),`wd`.`weaving_daily_id` ) ,0) AS `open_jugar` from (((((`jute_prod_weaving_daily` `wd` left join `spell_mst` `sp` on((`sp`.`spell_id` = `wd`.`spell_id`))) left join `machine_mst` `m` on((`m`.`machine_id` = `wd`.`machine_id`))) left join `jute_prod_weaving_quality` `q` on((`q`.`weaving_quality_id` = `wd`.`weaving_quality_id`))) left join `item_mst` `im` on((`im`.`item_id` = `q`.`item_id`))) left join (select `d2`.`weaving_daily_id` AS `weaving_daily_id`,(select `tm`.`value` from `jute_prod_weaving_target_map` `tm` where ((`tm`.`co_id` = `d2`.`co_id`) and (`tm`.`ref_id` = `d2`.`mid`) and (`tm`.`id_type` = 'mcid') and (`tm`.`value_role` = 'standard') and (`tm`.`param` = 'speed') and (`tm`.`active` = 1) and (`tm`.`effective_date` <= `d2`.`tran_date`)) order by `tm`.`effective_date` desc,`tm`.`weaving_target_map_id` desc limit 1) AS `std_speed`,(select `tm`.`value` from `jute_prod_weaving_target_map` `tm` where ((`tm`.`co_id` = `d2`.`co_id`) and (`tm`.`ref_id` = `d2`.`mid`) and (`tm`.`id_type` = 'mcid') and (`tm`.`value_role` = 'actual') and (`tm`.`param` = 'speed') and (`tm`.`active` = 1) and (`tm`.`effective_date` <= `d2`.`tran_date`)) order by `tm`.`effective_date` desc,`tm`.`weaving_target_map_id` desc limit 1) AS `act_speed`,(select `pv`.`avg_picks` from `vw_weaving_pick_act` `pv` where ((`pv`.`co_id` = `d2`.`co_id`) and (`pv`.`weaving_quality_id` = `d2`.`qid`) and (`pv`.`entry_date` = `d2`.`tran_date`)) limit 1) AS `std_picks`,(select `pv`.`avg_picks` from `vw_weaving_pick_act` `pv` where ((`pv`.`co_id` = `d2`.`co_id`) and (`pv`.`weaving_quality_id` = `d2`.`qid`) and (`pv`.`entry_date` <= `d2`.`tran_date`)) order by `pv`.`entry_date` desc limit 1) AS `act_picks`,(select `tm`.`value` from `jute_prod_weaving_target_map` `tm` where ((`tm`.`co_id` = `d2`.`co_id`) and (`tm`.`ref_id` = `d2`.`qid`) and (`tm`.`id_type` = 'qid') and (`tm`.`value_role` = 'standard') and (`tm`.`param` = 'eff') and (`tm`.`active` = 1) and (`tm`.`effective_date` <= `d2`.`tran_date`)) order by `tm`.`effective_date` desc,`tm`.`weaving_target_map_id` desc limit 1) AS `std_eff`,(select `tm`.`value` from `jute_prod_weaving_target_map` `tm` where ((`tm`.`co_id` = `d2`.`co_id`) and (`tm`.`ref_id` = `d2`.`qid`) and (`tm`.`id_type` = 'qid') and (`tm`.`value_role` = 'target') and (`tm`.`param` = 'eff') and (`tm`.`active` = 1) and (`tm`.`effective_date` <= `d2`.`tran_date`)) order by `tm`.`effective_date` desc,`tm`.`weaving_target_map_id` desc limit 1) AS `target_eff` from (select `w`.`weaving_daily_id` AS `weaving_daily_id`,`w`.`co_id` AS `co_id`,`w`.`tran_date` AS `tran_date`,`w`.`weaving_quality_id` AS `qid`,`w`.`machine_id` AS `mid` from `jute_prod_weaving_daily` `w` where (`w`.`active` = 1)) `d2`) `s` on((`s`.`weaving_daily_id` = `wd`.`weaving_daily_id`))) where (`wd`.`active` = 1)) `a`) `b`) `c`;
