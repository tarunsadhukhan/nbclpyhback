-- Migration: Add band-edge columns to EXISTING spreader_machine_attr
-- Module: juteSQC (R-08-04 Spreader Roll Weight)
-- Date: 2026-06-26
--
-- The std roll weight already lives in spreader_machine_attr.wt_per_roll (already
-- returned by get_spreader_machines_query()). This adds 5 nullable band-edge
-- columns that define the 6-bucket weight histogram for the roll-weight report.
-- Default set is 55/60/65/70/75 (the helper falls back to that set when a machine
-- has no edges configured); Spreader-2 uses 85/90/95/100/105. Seed real per-machine
-- values later.

ALTER TABLE spreader_machine_attr
    ADD COLUMN band_edge_1 DECIMAL(10,3) NULL AFTER wt_per_roll,
    ADD COLUMN band_edge_2 DECIMAL(10,3) NULL AFTER band_edge_1,
    ADD COLUMN band_edge_3 DECIMAL(10,3) NULL AFTER band_edge_2,
    ADD COLUMN band_edge_4 DECIMAL(10,3) NULL AFTER band_edge_3,
    ADD COLUMN band_edge_5 DECIMAL(10,3) NULL AFTER band_edge_4;

-- Rollback:
-- ALTER TABLE spreader_machine_attr
--     DROP COLUMN band_edge_1,
--     DROP COLUMN band_edge_2,
--     DROP COLUMN band_edge_3,
--     DROP COLUMN band_edge_4,
--     DROP COLUMN band_edge_5;
