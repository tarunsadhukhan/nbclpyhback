-- Migration: Create jute_sqc_qr_cv_15a (+ _dtl) — R-08-15A Yarn QR% & CV% Special Purpose
-- Module: juteSQC (R-08-15A, spinning stage)
-- Date: 2026-06-27
-- Applies to: tenant database dev3 (QA). Promote to other tenants later.
--
-- HEADER + DETAIL (2 machines, flat 12 readings — no spindle structure). yarn-quality
-- linked (NOT batch). Clones the jute_sqc_spinning_qr_cv header+detail shape. Each save
-- inserts one header + EXACTLY 12 detail reading rows (cells may be null). Stats
-- (avg_bs/max/min/std/qr_pct/cv_pct/qr_at_min) computed SERVER-SIDE at read from the
-- detail rows using the R-08-15 _qr_cv_stats formula — NOT stored. observed_count + mr_pct
-- are OPERATOR-ENTERED on the header (the special-purpose variant; NOT read from R-08-16).
-- drawing_mc_id = 3rd-drawing machine, mc_id = spinning frame. Insert-only; soft-delete
-- header. Branch-wise: save requires branch_id; reads are branch-scoped.
-- Rollback:
--   DROP TABLE IF EXISTS jute_sqc_qr_cv_15a_dtl;
--   DROP TABLE IF EXISTS jute_sqc_qr_cv_15a;

CREATE TABLE IF NOT EXISTS jute_sqc_qr_cv_15a (
    qr_cv_15a_id      INT           NOT NULL AUTO_INCREMENT,
    co_id             INT           NOT NULL,
    branch_id         INT           NULL,
    entry_date        DATE          NOT NULL,
    drawing_mc_id     INT           NULL,          -- 3rd-drawing machine (machine_mst.machine_id)
    mc_id             INT           NULL,          -- spinning frame (machine_mst.machine_id)
    item_id           INT           NULL,          -- yarn quality (item_mst.item_id)
    observed_count    DECIMAL(10,3) NULL,
    mr_pct            DECIMAL(5,2)  NULL,
    active            INT           NOT NULL DEFAULT 1,
    updated_by        INT           NULL,
    updated_date_time TIMESTAMP     NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (qr_cv_15a_id),
    INDEX idx_jqc15a_co_id (co_id),
    INDEX idx_jqc15a_entry_date (entry_date),
    INDEX idx_jqc15a_co_entry_date (co_id, entry_date),
    INDEX idx_jqc15a_mc_id (mc_id),
    INDEX idx_jqc15a_item_id (item_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS jute_sqc_qr_cv_15a_dtl (
    qr_cv_15a_dtl_id INT           NOT NULL AUTO_INCREMENT,
    qr_cv_15a_id     INT           NOT NULL,
    reading_no       INT           NOT NULL,
    reading_val      DECIMAL(10,3) NULL,
    PRIMARY KEY (qr_cv_15a_dtl_id),
    INDEX idx_jqc15a_dtl_hdr (qr_cv_15a_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
