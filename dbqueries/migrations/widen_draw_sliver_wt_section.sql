-- Migration: Widen jute_sqc_draw_sliver_wt.section + time_band to VARCHAR(20)
-- Module: juteSQC (R-08-08/09/10 Drawhead + Finisher Card)
-- Date: 2026-06-27
-- Applies to: tenant database dev3 (QA). Promote to other tenants later.
--
-- Bug fix: section was created VARCHAR(10) but the DRAW_SECTIONS enum values exceed 10 chars
-- ('DRAWHEAD_SWT'/'DRAWHEAD_SWP' = 12, 'FINISHER_CARD' = 13), so every drawhead save failed
-- with pymysql 1406 "Data too long for column 'section'". The sibling jute_sqc_card_sliver_wt
-- correctly uses VARCHAR(20). This widens section (and time_band, for parity) to VARCHAR(20).
-- Non-destructive (widening only — no truncation, no data loss). The CREATE migration
-- (create_jute_sqc_draw_sliver_wt.sql) and the ORM model now declare VARCHAR(20)/String(20),
-- so fresh tenants are correct and this ALTER is only for tenants created before this fix.

ALTER TABLE jute_sqc_draw_sliver_wt
    MODIFY COLUMN section   VARCHAR(20) NOT NULL,
    MODIFY COLUMN time_band VARCHAR(20) NULL;

-- Rollback (only safe if no row has section/time_band longer than 10 chars):
-- ALTER TABLE jute_sqc_draw_sliver_wt
--     MODIFY COLUMN section   VARCHAR(10) NOT NULL,
--     MODIFY COLUMN time_band VARCHAR(10) NULL;
