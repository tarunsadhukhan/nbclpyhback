-- Migration: Create jute_spreader_quality_attr — per-quality standards satellite
-- Module: juteSQC (R-08-04 Spreader Roll Weight)
-- Date: 2026-06-26
--
-- item_id-keyed satellite holding per-raw-jute-quality standards (std_mr_pct,
-- optional std_roll_wt). Mirrors jute_yarn_mst's role for spinning. Standards
-- live HERE, NOT as columns on item_mst. std_mr_pct is nullable; the backend
-- falls back to base 16 when no row / NULL is found.

CREATE TABLE IF NOT EXISTS jute_spreader_quality_attr (
    spreader_quality_attr_id INT           NOT NULL AUTO_INCREMENT,
    co_id                    INT           NOT NULL,
    item_id                  INT           NOT NULL,
    std_mr_pct               DECIMAL(5,2)  NULL,
    std_roll_wt              DECIMAL(10,3) NULL,
    active                   INT           NOT NULL DEFAULT 1,
    updated_by               INT           NULL,
    updated_date_time        TIMESTAMP     NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (spreader_quality_attr_id),
    INDEX idx_jsqa_item_id (item_id),
    INDEX idx_jsqa_co_id (co_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Rollback:
-- DROP TABLE IF EXISTS jute_spreader_quality_attr;
