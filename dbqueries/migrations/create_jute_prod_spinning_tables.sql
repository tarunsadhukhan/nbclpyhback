-- Migration: Create Spinning production tables (jute production module)
-- Date: 2026-06-11
-- Applies to: tenant databases dev3 AND sls
--
-- yarn_quality_param: per-yarn-quality spinning parameter sets (speed/tpi/count/spindle/eff)
-- jute_prod_spinning_machine_attr: per-machine spinning attributes (bobbin weight, speed, spindles)
--   (mirrors jute_prod_drawing_machine_attr)
-- jute_prod_spinning_act_count: datewise actual count mapping per yarn quality / param
-- jute_prod_spinning_daily: datewise spinning daily production snapshot + computed outputs
-- spinning_quality_xref: cross-ref legacy spinning_quality_mst -> yarn_quality / param
--   (created empty; seeded later by ops)

CREATE TABLE IF NOT EXISTS yarn_quality_param (
  param_id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  yarn_quality_id INT NOT NULL,
  co_id INT NOT NULL,
  set_name VARCHAR(60) NULL,
  speed DECIMAL(10,2) NULL,
  tpi DECIMAL(10,3) NULL,
  std_count DECIMAL(10,3) NULL,
  spindle INT NULL,
  frame_type VARCHAR(10) NULL,
  jbo_rbo VARCHAR(10) NULL,
  subgroup_type VARCHAR(20) NULL,
  target_eff DECIMAL(8,2) NULL,
  active TINYINT(1) NOT NULL DEFAULT 1,
  updated_by INT NULL,
  updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_yqp_quality (yarn_quality_id),
  KEY idx_yqp_co (co_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS jute_prod_spinning_machine_attr (
  spinning_machine_attr_id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  co_id INT NOT NULL,
  machine_id INT NOT NULL,
  frame_type VARCHAR(10) NULL,
  speed DECIMAL(10,2) NULL,
  no_of_spindle INT NULL,
  bobbin_weight DECIMAL(10,3) NOT NULL DEFAULT 0.000,
  active TINYINT(1) NOT NULL DEFAULT 1,
  updated_by INT NULL,
  updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_jpsma_co_machine (co_id, machine_id),
  KEY idx_jpsma_co (co_id),
  KEY idx_jpsma_machine (machine_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS jute_prod_spinning_act_count (
  spinning_act_count_id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  co_id INT NOT NULL,
  branch_id INT NULL,
  mapping_date DATE NOT NULL,
  yarn_quality_id INT NOT NULL,
  param_id INT NULL,
  spg_actual_count DECIMAL(10,3) NOT NULL DEFAULT 0.000,
  quality_type TINYINT NOT NULL DEFAULT 2,
  active TINYINT(1) NOT NULL DEFAULT 1,
  updated_by INT NULL,
  updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_jpsac_co_date (co_id, mapping_date),
  KEY idx_jpsac_quality (yarn_quality_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS jute_prod_spinning_daily (
  spinning_daily_id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  co_id INT NOT NULL,
  branch_id INT NULL,
  tran_date DATE NOT NULL,
  yarn_quality_id INT NOT NULL,
  param_id INT NULL,
  act_count DECIMAL(10,3) NOT NULL DEFAULT 0.000,
  speed DECIMAL(10,2) NOT NULL DEFAULT 0.00,
  tpi DECIMAL(10,3) NOT NULL DEFAULT 0.000,
  spindle INT NOT NULL DEFAULT 0,
  std_count DECIMAL(10,3) NOT NULL DEFAULT 0.000,
  tar_eff DECIMAL(8,2) NOT NULL DEFAULT 0.00,
  frames_a INT NOT NULL DEFAULT 0,
  frames_b INT NOT NULL DEFAULT 0,
  frames_c INT NOT NULL DEFAULT 0,
  prod_a DECIMAL(12,3) NOT NULL DEFAULT 0.000,
  prod_b DECIMAL(12,3) NOT NULL DEFAULT 0.000,
  prod_c DECIMAL(12,3) NOT NULL DEFAULT 0.000,
  hrs_a DECIMAL(5,2) NOT NULL DEFAULT 8.00,
  hrs_b DECIMAL(5,2) NOT NULL DEFAULT 8.00,
  hrs_c DECIMAL(5,2) NOT NULL DEFAULT 7.50,
  winders INT NOT NULL DEFAULT 0,
  p100a DECIMAL(12,3) NOT NULL DEFAULT 0.000,
  p100b DECIMAL(12,3) NOT NULL DEFAULT 0.000,
  p100c DECIMAL(12,3) NOT NULL DEFAULT 0.000,
  tar_prd DECIMAL(12,3) NOT NULL DEFAULT 0.000,
  hunprod DECIMAL(12,3) NOT NULL DEFAULT 0.000,
  act_eff DECIMAL(8,2) NOT NULL DEFAULT 0.00,
  eff_a DECIMAL(8,2) NOT NULL DEFAULT 0.00,
  eff_b DECIMAL(8,2) NOT NULL DEFAULT 0.00,
  eff_c DECIMAL(8,2) NOT NULL DEFAULT 0.00,
  active TINYINT(1) NOT NULL DEFAULT 1,
  updated_by INT NULL,
  updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_jpsd_co_date (co_id, tran_date),
  KEY idx_jpsd_quality (yarn_quality_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS spinning_quality_xref (
  xref_id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  co_id INT NULL,
  spg_quality_mst_id INT NOT NULL,
  yarn_quality_id INT NOT NULL,
  param_id INT NULL,
  active TINYINT(1) NOT NULL DEFAULT 1,
  KEY idx_sqx_spg_quality (spg_quality_mst_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- App-level uniqueness (not DB-enforced, soft-deleted rows must not block re-entry):
--   jute_prod_spinning_act_count: (co_id, mapping_date, yarn_quality_id, param_id, active=1)
--   jute_prod_spinning_daily:     (co_id, tran_date, yarn_quality_id, param_id, active=1)

-- =============================================================================
-- ROLLBACK:
-- DROP TABLE IF EXISTS spinning_quality_xref;
-- DROP TABLE IF EXISTS jute_prod_spinning_daily;
-- DROP TABLE IF EXISTS jute_prod_spinning_act_count;
-- DROP TABLE IF EXISTS jute_prod_spinning_machine_attr;
-- DROP TABLE IF EXISTS yarn_quality_param;
-- =============================================================================
