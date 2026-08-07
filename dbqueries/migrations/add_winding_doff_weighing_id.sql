-- Shared-weighing group key on jute_prod_winding_doff.
--
-- Since the person-keyed refactor one weighing (one trolly + one spool) may be
-- shared by several winders and writes ONE ROW PER WINDER, each carrying that
-- winder's share of the net. Nothing tied those rows together, so doff_edit and
-- doff_delete acted on a single share: deleting 1 of 4 left three rows summing
-- to less than any real weighing, and the spinning planning grid -- which sums
-- production_qty per item + shift bucket -- silently lost that share.
--
-- weighing_id is the FIRST row's winding_doff_id, stamped right after the split
-- insert. Rows written before this column keep NULL and readers treat NULL as a
-- solo group via COALESCE(weighing_id, winding_doff_id), so no backfill is
-- needed and legacy single-winder rows behave exactly as before.
--
-- RUN THIS ON EVERY TENANT BEFORE DEPLOYING THE CODE -- the new write path
-- references weighing_id and would 500 with Unknown column on a tenant that
-- has not been migrated.

ALTER TABLE jute_prod_winding_doff
    ADD COLUMN weighing_id INT NULL AFTER winding_doff_id,
    ADD INDEX idx_wd_weighing_id (weighing_id);

-- ROLLBACK:
-- ALTER TABLE jute_prod_winding_doff
--     DROP INDEX idx_wd_weighing_id,
--     DROP COLUMN weighing_id
