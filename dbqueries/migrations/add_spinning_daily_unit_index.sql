-- Migration: composite unit index on jute_prod_spinning_daily.
-- Serves the Process freeze soft-delete, the frozen-read unit scan, and the drift
-- compare — the old per-column singles (idx_jpsd_co_date etc) cannot serve a
-- 5-column unit lookup efficiently.
-- Rollback: ALTER TABLE jute_prod_spinning_daily DROP INDEX idx_jpsd_unit;
ALTER TABLE jute_prod_spinning_daily
  ADD INDEX idx_jpsd_unit (co_id, tran_date, spell_id, machine_id, item_id);
