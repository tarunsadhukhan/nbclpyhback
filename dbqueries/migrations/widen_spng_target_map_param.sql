-- Widen jute_prod_spng_target_map.param from VARCHAR(8) to VARCHAR(20).
-- Reason: original table only carried 'speed'|'tpi'|'eff' (<=5 chars). Machine
-- (mcid) params 'spindles' (8) and 'bobbin_wt' (9) were added later; 'bobbin_wt'
-- overflows VARCHAR(8) -> (1406, "Data too long for column 'param'").
--
-- Rollback:
--   ALTER TABLE jute_prod_spng_target_map MODIFY COLUMN param VARCHAR(8) NOT NULL;

ALTER TABLE jute_prod_spng_target_map
  MODIFY COLUMN param VARCHAR(20) NOT NULL;
