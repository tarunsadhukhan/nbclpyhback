-- Migration: Create Winding production tables (jute production module)
-- Date: 2026-06-15
-- Applies to: tenant databases (dev3 default; production tenants on rollout)
--
-- Winding is the mill-floor stage after spinning. Three entry screens share a
-- Date + Spell + Winding-machine header:
--   jute_prod_winding_doff       -- one row per machine per doff (combined-doff EQUAL split 1..3 mcs)
--   jute_prod_winding_jugar      -- spindle open/close leftover weight per machine/spell
--   jute_prod_winding_daily_qlty -- yarn quality + spindle count per machine/spell
--
-- Conventions (mirror spinning/drawing): co_id + branch_id scoping, soft delete
-- active TINYINT(1) DEFAULT 1, audit cols updated_by + updated_date_time (NO created_*),
-- spell stored as spell_id INT (resolved from spell_code at the boundary).
--
-- Quality identity REUSES yarn_quality_master (yarn_quality_id) — there is NO winding
-- quality master. Reconciled production is computed at READ time (view), not persisted.
--
-- Also: ADD trolly_mst.trolly_type ('T'=trolly,'S'=spool) to distinguish trolly vs spool
-- (legacy overloaded trollymst.process_type 39/101); seed the 'Winding' machine type;
-- and DROP the retired round-1 manual aggregate jute_prod_winding_prod.

-- -----------------------------------------------------------------------------
-- 1. Doff production — one row per machine per doff
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS jute_prod_winding_doff (
  winding_doff_id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  co_id INT NOT NULL,
  branch_id INT NULL,
  tran_date DATE NOT NULL,
  spell_id INT NOT NULL,
  machine_id INT NOT NULL,
  yarn_quality_id INT NULL,
  trolly_id INT NULL,
  trolly_wt DECIMAL(10,3) NOT NULL DEFAULT 0.000,
  spool_id INT NULL,
  spool_wt DECIMAL(10,3) NOT NULL DEFAULT 0.000,
  no_of_machines INT NOT NULL DEFAULT 1,
  gross_input_wt DECIMAL(12,3) NOT NULL DEFAULT 0.000,
  production_qty DECIMAL(12,3) NOT NULL DEFAULT 0.000,
  row_gross_wt DECIMAL(12,3) NOT NULL DEFAULT 0.000,
  operator_id INT NULL,
  active TINYINT(1) NOT NULL DEFAULT 1,
  updated_by INT NULL,
  updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_jpwd_co_date_spell_mc (co_id, tran_date, spell_id, machine_id),
  KEY idx_jpwd_co (co_id),
  KEY idx_jpwd_quality (yarn_quality_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- -----------------------------------------------------------------------------
-- 2. Jugar — spindle open/close leftover weight per machine/spell
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS jute_prod_winding_jugar (
  winding_jugar_id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  co_id INT NOT NULL,
  branch_id INT NULL,
  tran_date DATE NOT NULL,
  spell_id INT NOT NULL,
  machine_id INT NOT NULL,
  weight DECIMAL(10,3) NOT NULL DEFAULT 0.000,
  open_close CHAR(1) NOT NULL DEFAULT 'O',
  active TINYINT(1) NOT NULL DEFAULT 1,
  updated_by INT NULL,
  updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_jpwj_co_date_spell_mc_oc (co_id, tran_date, spell_id, machine_id, open_close),
  KEY idx_jpwj_co (co_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- -----------------------------------------------------------------------------
-- 3. Daily quality — yarn quality + spindle count per machine/spell
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS jute_prod_winding_daily_qlty (
  winding_daily_qlty_id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  co_id INT NOT NULL,
  branch_id INT NULL,
  tran_date DATE NOT NULL,
  spell_id INT NOT NULL,
  machine_id INT NOT NULL,
  yarn_quality_id INT NULL,
  no_of_spindle INT NOT NULL DEFAULT 0,
  active TINYINT(1) NOT NULL DEFAULT 1,
  updated_by INT NULL,
  updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_jpwdq_co_date_spell_mc (co_id, tran_date, spell_id, machine_id),
  KEY idx_jpwdq_co (co_id),
  KEY idx_jpwdq_quality (yarn_quality_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- App-level uniqueness (not DB-enforced; soft-deleted rows must not block re-entry):
--   jute_prod_winding_jugar:       (co_id, tran_date, spell_id, machine_id, open_close, active=1)
--   jute_prod_winding_daily_qlty:  (co_id, tran_date, spell_id, machine_id, active=1)

-- -----------------------------------------------------------------------------
-- 4. trolly_mst: add trolly_type to distinguish trolly ('T') vs spool ('S')
--    (legacy overloaded trollymst.process_type 39=trolly / 101=spool)
-- -----------------------------------------------------------------------------
ALTER TABLE trolly_mst ADD COLUMN trolly_type VARCHAR(1) NOT NULL DEFAULT 'T';

-- -----------------------------------------------------------------------------
-- 5. Seed the 'Winding' machine type (idempotent; updated_by is NOT NULL w/o default)
-- -----------------------------------------------------------------------------
INSERT INTO machine_type_mst (machine_type_name, active, updated_by)
SELECT 'Winding', 1, 1
WHERE NOT EXISTS (
  SELECT 1 FROM machine_type_mst WHERE machine_type_name = 'Winding'
);

-- -----------------------------------------------------------------------------
-- 6. Retire the round-1 manual aggregate. The spinning grid winding_total now
--    reads the reconciliation view instead of this persisted summary.
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS jute_prod_winding_prod;

-- =============================================================================
-- ROLLBACK:
-- DROP TABLE IF EXISTS jute_prod_winding_daily_qlty;
-- DROP TABLE IF EXISTS jute_prod_winding_jugar;
-- DROP TABLE IF EXISTS jute_prod_winding_doff;
-- ALTER TABLE trolly_mst DROP COLUMN trolly_type;
-- DELETE FROM machine_type_mst WHERE machine_type_name = 'Winding';
-- -- jute_prod_winding_prod cannot be auto-restored; recreate from
-- --   create_jute_prod_spinning_tables.sql history if a rollback of the retirement is needed.
-- =============================================================================
