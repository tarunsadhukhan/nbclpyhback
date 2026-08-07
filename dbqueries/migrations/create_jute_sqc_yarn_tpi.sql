-- Migration: Create jute_sqc_yarn_tpi (+ _dtl) — R-08-17 Yarn TPI & TPI CV%
-- Module: juteSQC (R-08-17, spinning stage)
-- Date: 2026-06-27
-- Applies to: tenant database dev3 (QA). Promote to other tenants later.
--
-- HEADER + DETAIL (20-reading twist-uniformity study). yarn-quality linked (NOT batch).
-- Clones the jute_sqc_spinning_qr_cv header+detail shape. Each save inserts one header
-- + EXACTLY 20 detail reading rows (cells may be null). Stats (avg/std/cv/min/max) are
-- computed SERVER-SIDE at read from the detail rows — NOT stored. std_tpi / tp_value /
-- count_lbs are snapshotted from the form on the header. Insert-only; soft-delete header.
-- Branch-wise: save requires branch_id; reads are branch-scoped.
-- Rollback:
--   DROP TABLE IF EXISTS jute_sqc_yarn_tpi_dtl;
--   DROP TABLE IF EXISTS jute_sqc_yarn_tpi;

CREATE TABLE IF NOT EXISTS jute_sqc_yarn_tpi (
    yarn_tpi_id       INT           NOT NULL AUTO_INCREMENT,
    co_id             INT           NOT NULL,
    branch_id         INT           NULL,
    entry_date        DATE          NOT NULL,
    mc_id             INT           NULL,          -- spinning frame (machine_mst.machine_id)
    item_id           INT           NULL,          -- yarn quality (item_mst.item_id)
    count_lbs         DECIMAL(10,3) NULL,
    std_tpi           DECIMAL(10,3) NULL,
    tp_value          DECIMAL(10,3) NULL,
    prepared_by       VARCHAR(150)  NULL,
    active            INT           NOT NULL DEFAULT 1,
    updated_by        INT           NULL,
    updated_date_time TIMESTAMP     NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (yarn_tpi_id),
    INDEX idx_jytpi_co_id (co_id),
    INDEX idx_jytpi_entry_date (entry_date),
    INDEX idx_jytpi_co_entry_date (co_id, entry_date),
    INDEX idx_jytpi_mc_id (mc_id),
    INDEX idx_jytpi_item_id (item_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS jute_sqc_yarn_tpi_dtl (
    yarn_tpi_dtl_id INT           NOT NULL AUTO_INCREMENT,
    yarn_tpi_id     INT           NOT NULL,
    reading_no      INT           NOT NULL,
    reading_val     DECIMAL(10,3) NULL,
    PRIMARY KEY (yarn_tpi_dtl_id),
    INDEX idx_jytpi_dtl_hdr (yarn_tpi_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
