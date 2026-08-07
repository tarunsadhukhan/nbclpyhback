-- Migration: Beaming composite-warp components + physical beam number.
--   1. jute_prod_bm_quality_dtl  — ACTIVATE the composite-warp detail table (SPEC §A.4).
--        Each child row holds one warp component's (ends, count) so kg_per_cut sums Sigma_n.
--        When jute_prod_bm_quality.is_composite = 1 the parent ends/std_count/yarn_item_id are
--        NULL/aggregate and the real (ends, count) pairs live here (>= 2 components). When
--        is_composite = 0 the parent holds ends/std_count/yarn_item_id and has NO _dtl rows.
--   2. jute_prod_beaming_daily.beam_no  — physical beam number holding material (like a trolley
--        no, NOT an auto doc-number) captured per production row.
-- Date: 2026-06-22
-- Applies to: tenant database dev3 (QA). Promote to other tenants later.
-- Run AFTER create_beaming_tables.sql (this references jute_prod_bm_quality and
--   jute_prod_beaming_daily, both created there).

-- 1. Composite-warp components (SPEC §A.4) — child of jute_prod_bm_quality.
CREATE TABLE jute_prod_bm_quality_dtl (
    bm_quality_dtl_id INT          NOT NULL AUTO_INCREMENT,
    bm_quality_id     INT          NOT NULL,
    component_no      INT          NOT NULL,            -- 1,2,... ordering within the warp
    ends              INT          NOT NULL,            -- this component's warp ends
    yarn_item_id      INT          NULL,                -- jute yarn supplying this component count
    count             DECIMAL(10,3) NOT NULL,           -- from jute_yarn_mst.jute_yarn_count
    active            TINYINT      NOT NULL DEFAULT 1,
    PRIMARY KEY (bm_quality_dtl_id),
    KEY idx_bmqd_parent (bm_quality_id),
    CONSTRAINT fk_bmqd_parent FOREIGN KEY (bm_quality_id) REFERENCES jute_prod_bm_quality (bm_quality_id)
);

-- 2. Physical beam number on the daily production snapshot (after eb_id).
ALTER TABLE jute_prod_beaming_daily ADD COLUMN beam_no VARCHAR(50) NULL AFTER eb_id;

-- 3. Composite parents store std_count = NULL (the real per-component counts live in
--    jute_prod_bm_quality_dtl). The original create_beaming_tables.sql declared std_count
--    NOT NULL; relax it so composite (is_composite = 1) parents can persist NULL.
--    ends stays NOT NULL (composite parent ends = SUM of component ends).
ALTER TABLE jute_prod_bm_quality MODIFY std_count DECIMAL(10,3) NULL;

-- =============================================================================
-- ROLLBACK (reverse order — drop the child added by statement 1 first, then the
-- column added by statement 2, then re-tighten std_count):
-- DROP TABLE jute_prod_bm_quality_dtl;
-- ALTER TABLE jute_prod_beaming_daily DROP COLUMN beam_no;
-- ALTER TABLE jute_prod_bm_quality MODIFY std_count DECIMAL(10,3) NOT NULL;
-- =============================================================================
