-- Migration: Create jute_draw_quality_std — (item_id, process)-keyed standards satellite
-- Module: juteSQC (R-08-05/06/07 Breaker Card; serves the whole carding/drawing family)
-- Date: 2026-06-27
-- Applies to: tenant database dev3 (QA). Promote to other tenants later.
--
-- A per-(line-quality, process) standards satellite. Unlike the spreader's
-- jute_spreader_quality_attr (item_id-keyed only), the carding/drawing family carries
-- a DIFFERENT band/MR for the SAME quality at breaker vs inter vs drawhead vs finisher,
-- so the satellite is keyed (item_id, process). std_mr_pct + std_cv_low/high are the
-- printed STD MR% / STD CV% band; std_weight/std_wt_tol are an optional sliver-weight
-- target (unused at breaker, present for downstream stages). ALL std columns are
-- NULLABLE with code fallbacks: std MR -> 16; CV pass/fail only when a band is seeded
-- (else cv_within_band = NULL). Standards live HERE, NOT as columns on item_mst.

CREATE TABLE IF NOT EXISTS jute_draw_quality_std (
    draw_quality_std_id INT           NOT NULL AUTO_INCREMENT,
    co_id               INT           NOT NULL,
    item_id             INT           NOT NULL,
    process             VARCHAR(30)   NOT NULL,
    std_mr_pct          DECIMAL(5,2)  NULL,
    std_cv_low          DECIMAL(5,2)  NULL,
    std_cv_high         DECIMAL(5,2)  NULL,
    std_weight          DECIMAL(10,3) NULL,
    std_wt_tol          DECIMAL(10,3) NULL,
    active              INT           NOT NULL DEFAULT 1,
    updated_by          INT           NULL,
    updated_date_time   TIMESTAMP     NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (draw_quality_std_id),
    INDEX idx_jdqs_item_process (item_id, process),
    INDEX idx_jdqs_co_id (co_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Rollback:
-- DROP TABLE IF EXISTS jute_draw_quality_std;
