-- Back-date seeded spinning standards so back-dated doff entries resolve.
--
-- Problem: jute_prod_spng_target_map rows were seeded with effective_date = the
-- day the seed ran. src/juteProduction/services/spinning_standards.py::resolve_param
-- filters `effective_date <= :on_date`, so any doff entry whose tran_date predates
-- the seed day finds NO row, resolve_param returns 0.0, and
-- src/juteProduction/spinning_entry.py::_resolve_bobbin raises
-- 400 "No spinning attributes configured for this machine" — even though the row
-- exists and is active.
--
-- Target: sls, co_id = 2 (58 machines x 8 rows seeded on 2026-07-22).
-- New floor: 2025-04-01 (FY start).
--
-- Backup before running:
--   SELECT spng_target_map_id, co_id, ref_id, id_type, value_role, param, effective_date
--   FROM jute_prod_spng_target_map WHERE co_id = 2 AND effective_date = '2026-07-22';

UPDATE jute_prod_spng_target_map
SET effective_date = '2025-04-01'
WHERE co_id = 2
  AND effective_date = '2026-07-22';

-- Verify — must return value 24.0000 (previously zero rows):
--   SELECT value FROM jute_prod_spng_target_map
--   WHERE co_id = 2 AND ref_id = 608 AND id_type = 'mcid' AND value_role = 'standard'
--     AND param = 'bobbin_wt' AND active = 1 AND effective_date <= '2026-01-02'
--   ORDER BY effective_date DESC LIMIT 1;

-- ROLLBACK:
-- UPDATE jute_prod_spng_target_map
-- SET effective_date = '2026-07-22'
-- WHERE co_id = 2
--   AND effective_date = '2025-04-01';
