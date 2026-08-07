-- Migration: allow NULL weaving_quality_id on jute_prod_weaving_daily
-- Entry capture now precedes Loom->Quality mapping; quality is filled at Process.
-- Rollback: UPDATE jute_prod_weaving_daily SET weaving_quality_id = 0 WHERE weaving_quality_id IS NULL;
--           ALTER TABLE jute_prod_weaving_daily MODIFY weaving_quality_id INT NOT NULL;
ALTER TABLE jute_prod_weaving_daily MODIFY weaving_quality_id INT NULL;
