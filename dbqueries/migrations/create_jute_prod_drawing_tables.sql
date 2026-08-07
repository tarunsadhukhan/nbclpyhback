-- Migration: Create Drawing production tables (jute production module)
-- Date: 2026-06-11
-- Applies to: tenant databases dev3 AND sls
--
-- jute_prod_drawing_machine_attr: per-machine drawing attributes
--   (legacy EMPMILL12.drawing_master: const_meter + mc_group, plus configurable wrap)
-- jute_prod_drawing_entry: daily spellwise drawing meter entry
--   (legacy EMPMILL12.daily_drawing_transaction for type_of_mechine=14)

CREATE TABLE IF NOT EXISTS jute_prod_drawing_machine_attr (
  drawing_machine_attr_id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  co_id INT NOT NULL,
  machine_id INT NOT NULL,
  const_meter DECIMAL(12,3) NOT NULL DEFAULT 0.000,
  mc_group VARCHAR(50) NULL,
  meter_wrap_limit INT NOT NULL DEFAULT 10000,
  active TINYINT(1) NOT NULL DEFAULT 1,
  updated_by INT NULL,
  updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_jpdma_co_machine (co_id, machine_id),
  KEY idx_jpdma_co (co_id),
  KEY idx_jpdma_machine (machine_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS jute_prod_drawing_entry (
  drawing_entry_id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  co_id INT NOT NULL,
  branch_id INT NULL,
  tran_date DATE NOT NULL,
  spell VARCHAR(10) NOT NULL,
  machine_id INT NOT NULL,
  open_meter DECIMAL(12,3) NOT NULL DEFAULT 0.000,
  close_meter DECIMAL(12,3) NOT NULL DEFAULT 0.000,
  diff_meter DECIMAL(12,3) NOT NULL DEFAULT 0.000,
  const_meter DECIMAL(12,3) NOT NULL DEFAULT 0.000,
  wrk_hours DECIMAL(5,2) NOT NULL DEFAULT 0.00,
  actual_eff DECIMAL(8,2) NOT NULL DEFAULT 0.00,
  remarks VARCHAR(255) NULL,
  active TINYINT(1) NOT NULL DEFAULT 1,
  updated_by INT NULL,
  updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_jpde_co (co_id),
  KEY idx_jpde_branch (branch_id),
  KEY idx_jpde_date (tran_date),
  KEY idx_jpde_machine (machine_id),
  KEY idx_jpde_co_date_spell (co_id, tran_date, spell)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- No unique key on entry (co_id, tran_date, spell, machine_id): soft-deleted rows
-- must not block re-entry; duplicate enforcement is app-level (drawing_entry.py).

-- =============================================================================
-- ROLLBACK:
-- DROP TABLE IF EXISTS jute_prod_drawing_entry;
-- DROP TABLE IF EXISTS jute_prod_drawing_machine_attr;
-- =============================================================================
