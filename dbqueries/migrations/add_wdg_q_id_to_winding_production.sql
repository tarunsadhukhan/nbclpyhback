-- Rewire winding production quality selection: the quality picked in the UI is
-- now a winding_quality_mst row (wdg_q_id); the resolved winding_incentive_id
-- stays on the row as the rate snapshot. NULL for legacy rows entered before
-- the quality master existed.
-- Target DB: nbcl
-- Rollback: ALTER TABLE winding_production DROP KEY idx_winding_prod_quality, DROP COLUMN wdg_q_id;

ALTER TABLE winding_production
    ADD COLUMN wdg_q_id INT NULL AFTER eb_id,
    ADD KEY idx_winding_prod_quality (wdg_q_id);
