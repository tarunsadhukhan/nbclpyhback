-- Worker Rate Muster: date each rate row takes effect. Existing seeded rows
-- (imported from WORKER RATE MUSTER.xlsx, which had no date) stay NULL.
-- Target DB: nbcl
-- Rollback: ALTER TABLE worker_rate_mst DROP COLUMN effective_date;

ALTER TABLE worker_rate_mst ADD COLUMN effective_date DATE NULL AFTER eb_id;
