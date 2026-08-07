-- =============================================================================
-- Migration: create jute_sqc_spinning_rhmr
-- =============================================================================
-- RHMR (Relative Humidity / temperature record) capture for the Spinning SQC
-- module. One active row per (co_id, entry_date, spell_id) — upserted: re-saving
-- the same date+spell overwrites Temperature/Humidity (the router confirms the
-- overwrite with the caller first). Soft-delete via active=0.
--
-- App-uniqueness key: (co_id, entry_date, spell_id, active=1).
-- Mirrors jute_sqc_spinning_count conventions (co_id/branch_id/active/updated_*).
-- =============================================================================

CREATE TABLE IF NOT EXISTS jute_sqc_spinning_rhmr (
  spinning_sqc_rhmr_id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  co_id INT NOT NULL,
  branch_id INT NULL,
  entry_date DATE NOT NULL,
  spell_id INT NOT NULL,
  temperature DECIMAL(5,1) NULL,
  humidity DECIMAL(5,1) NULL,
  active TINYINT(1) NOT NULL DEFAULT 1,
  updated_by INT NULL,
  updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_jssr_lookup (co_id, entry_date, spell_id),
  KEY idx_jssr_co_date (co_id, entry_date),
  KEY idx_jssr_spell (spell_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Rollback:
-- DROP TABLE IF EXISTS jute_sqc_spinning_rhmr;
