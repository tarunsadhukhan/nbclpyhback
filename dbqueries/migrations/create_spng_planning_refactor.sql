-- Migration: Spinning planning refactor + SQC capture + winding aggregate
-- Date: 2026-06-13
-- Applies to: tenant databases dev3 (QA) [and sls when promoted]
--
-- Implements the spinning & winding planning-grid model (per the doc
-- spinning_production_documentation.md + winding-production-design.md):
--   * jute_prod_spng_target_map  - time-versioned standards/targets (last-date)
--   * jute_sqc_spinning_entry     - single-value actual speed/TPI (last-date)
--   * jute_sqc_spinning_count     - multi-observation count (averaged -> Act Count)
--   * jute_prod_winding_prod      - winding aggregate (summed per quality+date+shift)
--   * jute_prod_spinning_daily    - REBUILT to per-frame-per-spell grain
--   * jute_prod_spinning_act_count - DROPPED (count now from jute_sqc_spinning_count)
--
-- App-level uniqueness (not DB-enforced; soft-deleted rows must not block re-entry):
--   jute_prod_spng_target_map: (co_id, ref_id, id_type, value_role, param, effective_date, active=1)
--   jute_sqc_spinning_entry:   (co_id, entry_date, mc_id, yarn_quality_id, active=1)
--   jute_prod_winding_prod:    (co_id, prod_date, shift, yarn_quality_id, active=1)
--   jute_prod_spinning_daily:  (co_id, tran_date, spell_id, machine_id, yarn_quality_id, active=1)

-- -----------------------------------------------------------------------------
-- 1. Time-versioned standards & targets (replaces standards in yarn_quality_param)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS jute_prod_spng_target_map (
  spng_target_map_id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  co_id INT NOT NULL,
  branch_id INT NULL,
  effective_date DATE NOT NULL,
  ref_id INT NOT NULL,                       -- machine_id (mcid) or yarn_quality_id (qid)
  id_type VARCHAR(8) NOT NULL,               -- 'mcid' | 'qid'
  value_role VARCHAR(10) NOT NULL,           -- 'standard' | 'target' | 'actual'
  param VARCHAR(8) NOT NULL,                 -- 'speed' | 'tpi' | 'eff'
  value DECIMAL(12,4) NOT NULL DEFAULT 0.0000,
  active TINYINT(1) NOT NULL DEFAULT 1,
  updated_by INT NULL,
  updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_jpstm_lookup (co_id, ref_id, id_type, value_role, param, effective_date),
  KEY idx_jpstm_co (co_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- -----------------------------------------------------------------------------
-- 2. SQC single-value actual speed/TPI (last-date)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS jute_sqc_spinning_entry (
  spinning_sqc_entry_id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  co_id INT NOT NULL,
  branch_id INT NULL,
  entry_date DATE NOT NULL,
  mc_id INT NOT NULL,
  yarn_quality_id INT NOT NULL,
  actual_speed DECIMAL(10,2) NULL,
  actual_tpi DECIMAL(10,3) NULL,
  active TINYINT(1) NOT NULL DEFAULT 1,
  updated_by INT NULL,
  updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_jsse_lookup (co_id, mc_id, yarn_quality_id, entry_date),
  KEY idx_jsse_co_date (co_id, entry_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- -----------------------------------------------------------------------------
-- 3. SQC multi-observation count (AVG per date+quality -> Act Count)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS jute_sqc_spinning_count (
  spinning_sqc_count_id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  co_id INT NOT NULL,
  branch_id INT NULL,
  entry_date DATE NOT NULL,
  spell_id INT NULL,
  mc_id INT NULL,
  yarn_quality_id INT NOT NULL,
  observed_count DECIMAL(10,3) NOT NULL DEFAULT 0.000,
  active TINYINT(1) NOT NULL DEFAULT 1,
  updated_by INT NULL,
  updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_jssc_avg (co_id, yarn_quality_id, entry_date),
  KEY idx_jssc_co_date (co_id, entry_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- -----------------------------------------------------------------------------
-- 4. Winding aggregate (SUM per quality+date+shift -> winding total W)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS jute_prod_winding_prod (
  winding_prod_id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  co_id INT NOT NULL,
  branch_id INT NULL,
  prod_date DATE NOT NULL,
  shift VARCHAR(2) NOT NULL,                 -- 'A' | 'B' | 'C' (shift bucket, not spell)
  yarn_quality_id INT NOT NULL,
  qty_wind DECIMAL(12,3) NOT NULL DEFAULT 0.000,
  active TINYINT(1) NOT NULL DEFAULT 1,
  updated_by INT NULL,
  updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_jpwp_group (co_id, yarn_quality_id, prod_date, shift),
  KEY idx_jpwp_co_date (co_id, prod_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- -----------------------------------------------------------------------------
-- 5. Rebuild jute_prod_spinning_daily -> per-frame-per-spell grain
--    (drops the old per-quality-shift snapshot; QA data in dev3 only)
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS jute_prod_spinning_daily;

CREATE TABLE jute_prod_spinning_daily (
  spinning_daily_id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  co_id INT NOT NULL,
  branch_id INT NULL,
  tran_date DATE NOT NULL,
  spell_id INT NOT NULL,
  machine_id INT NOT NULL,
  yarn_quality_id INT NOT NULL,
  param_id INT NULL,
  spindles INT NOT NULL DEFAULT 0,
  minutes INT NOT NULL DEFAULT 0,
  act_count DECIMAL(10,3) NOT NULL DEFAULT 0.000,
  std_count DECIMAL(10,3) NOT NULL DEFAULT 0.000,
  std_speed DECIMAL(10,2) NOT NULL DEFAULT 0.00,
  actual_speed DECIMAL(10,2) NOT NULL DEFAULT 0.00,
  target_speed DECIMAL(10,2) NOT NULL DEFAULT 0.00,
  std_tpi DECIMAL(10,3) NOT NULL DEFAULT 0.000,
  actual_tpi DECIMAL(10,3) NOT NULL DEFAULT 0.000,
  target_tpi DECIMAL(10,3) NOT NULL DEFAULT 0.000,
  std_eff DECIMAL(8,2) NOT NULL DEFAULT 0.00,
  target_eff DECIMAL(8,2) NOT NULL DEFAULT 0.00,
  p100prod DECIMAL(12,3) NOT NULL DEFAULT 0.000,
  std_prod DECIMAL(12,3) NOT NULL DEFAULT 0.000,
  target_prod DECIMAL(12,3) NOT NULL DEFAULT 0.000,
  act_prod_doff DECIMAL(12,3) NOT NULL DEFAULT 0.000,
  winding_total DECIMAL(12,3) NOT NULL DEFAULT 0.000,
  act_prod_wind DECIMAL(12,3) NOT NULL DEFAULT 0.000,
  eff_doff DECIMAL(8,2) NOT NULL DEFAULT 0.00,
  eff_winding DECIMAL(8,2) NOT NULL DEFAULT 0.00,
  active TINYINT(1) NOT NULL DEFAULT 1,
  updated_by INT NULL,
  updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_jpsd_co_date (co_id, tran_date),
  KEY idx_jpsd_spell (spell_id),
  KEY idx_jpsd_machine (machine_id),
  KEY idx_jpsd_quality (yarn_quality_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- -----------------------------------------------------------------------------
-- 6. Drop superseded single-entry act count table (count now averaged from SQC)
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS jute_prod_spinning_act_count;

-- =============================================================================
-- ROLLBACK:
-- DROP TABLE IF EXISTS jute_prod_spng_target_map;
-- DROP TABLE IF EXISTS jute_sqc_spinning_entry;
-- DROP TABLE IF EXISTS jute_sqc_spinning_count;
-- DROP TABLE IF EXISTS jute_prod_winding_prod;
-- DROP TABLE IF EXISTS jute_prod_spinning_daily;
-- -- (re-create old jute_prod_spinning_daily + jute_prod_spinning_act_count from
-- --  create_jute_prod_spinning_tables.sql lines 49-102 to fully revert)
-- =============================================================================
