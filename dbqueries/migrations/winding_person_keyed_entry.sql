-- Winding production: re-key doff / jugar / daily-quality from MACHINE to PERSON (eb_id).
--
-- Context: winding entry moves from "pick a machine" to "pick a winder (EB no)".
-- Quality becomes a person -> quality map; the machine is no longer part of the
-- entry at all (person -> machine mapping continues to live in
-- daily_ebmc_attendance and is used for other purposes only).
--
-- Safe on live data: every column added is NULL-able and machine_id merely loses
-- its NOT NULL. Existing machine-keyed rows keep their machine_id and simply
-- carry eb_id = NULL (legacy rows). No backfill (decision: forward-only).
--
-- jute_prod_winding_doff.operator_id was declared as "eb_id; back-filled from
-- attendance later" and is 0% populated on every tenant, so it is RENAMED rather
-- than duplicated by a new column.
--
-- ROLLBACK
--   ALTER TABLE jute_prod_winding_doff       DROP INDEX `idx_jpwd_co_date_spell_eb`;
--   ALTER TABLE jute_prod_winding_doff       CHANGE COLUMN `eb_id` `operator_id` INT NULL;
--   ALTER TABLE jute_prod_winding_doff       MODIFY COLUMN `machine_id` INT NOT NULL;
--   ALTER TABLE jute_prod_winding_doff       MODIFY COLUMN `no_of_machines` INT NOT NULL DEFAULT 1;
--   ALTER TABLE jute_prod_winding_jugar      DROP INDEX `idx_jpwj_co_date_spell_eb_oc`;
--   ALTER TABLE jute_prod_winding_jugar      DROP COLUMN `eb_id`;
--   ALTER TABLE jute_prod_winding_jugar      MODIFY COLUMN `machine_id` INT NOT NULL;
--   ALTER TABLE jute_prod_winding_daily_qlty DROP INDEX `idx_jpwdq_co_date_spell_eb`;
--   ALTER TABLE jute_prod_winding_daily_qlty DROP COLUMN `eb_id`;
--   ALTER TABLE jute_prod_winding_daily_qlty MODIFY COLUMN `machine_id` INT NOT NULL;

-- ---------------------------------------------------------------------------
-- 1. jute_prod_winding_doff — one row per weighing per person
-- ---------------------------------------------------------------------------
ALTER TABLE `jute_prod_winding_doff`
    CHANGE COLUMN `operator_id` `eb_id` INT NULL COMMENT 'hrms_ed_personal_details.eb_id - the winder - primary identity of the row';

ALTER TABLE `jute_prod_winding_doff`
    MODIFY COLUMN `machine_id` INT NULL COMMENT 'legacy machine-keyed rows only - never written by person-keyed entry';

ALTER TABLE `jute_prod_winding_doff`
    MODIFY COLUMN `no_of_machines` INT NULL COMMENT 'legacy combined-doff split factor - never written by person-keyed entry';

ALTER TABLE `jute_prod_winding_doff`
    ADD INDEX `idx_jpwd_co_date_spell_eb` (`co_id`, `tran_date`, `spell_id`, `eb_id`);

-- ---------------------------------------------------------------------------
-- 2. jute_prod_winding_jugar — spindle open/close leftover, per person
-- ---------------------------------------------------------------------------
ALTER TABLE `jute_prod_winding_jugar`
    ADD COLUMN `eb_id` INT NULL COMMENT 'hrms_ed_personal_details.eb_id - the winder' AFTER `machine_id`;

ALTER TABLE `jute_prod_winding_jugar`
    MODIFY COLUMN `machine_id` INT NULL COMMENT 'legacy machine-keyed rows only - never written by person-keyed entry';

ALTER TABLE `jute_prod_winding_jugar`
    ADD INDEX `idx_jpwj_co_date_spell_eb_oc` (`co_id`, `tran_date`, `spell_id`, `eb_id`, `open_close`);

-- ---------------------------------------------------------------------------
-- 3. jute_prod_winding_daily_qlty — the person -> quality map
-- ---------------------------------------------------------------------------
ALTER TABLE `jute_prod_winding_daily_qlty`
    ADD COLUMN `eb_id` INT NULL COMMENT 'hrms_ed_personal_details.eb_id - the winder this quality is mapped to' AFTER `machine_id`;

ALTER TABLE `jute_prod_winding_daily_qlty`
    MODIFY COLUMN `machine_id` INT NULL COMMENT 'legacy machine-keyed rows only - never written by person-keyed entry';

ALTER TABLE `jute_prod_winding_daily_qlty`
    ADD INDEX `idx_jpwdq_co_date_spell_eb` (`co_id`, `tran_date`, `spell_id`, `eb_id`);
