-- Add a production machine-type marker to trolly_mst so each jute-production
-- stage (Spreader/Drawing/Spinning/Winding) lists only its own trolleys.
-- Target DB: dev3 (confirm before running on other tenants).
ALTER TABLE trolly_mst ADD COLUMN machine_type_id INT NULL;

-- Rollback:
-- ALTER TABLE trolly_mst DROP COLUMN machine_type_id;
