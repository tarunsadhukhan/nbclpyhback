-- Migration: R-08-22 Stitch SQC — finishing-stage sewing-stitch-density QC.
-- Module: juteSQC. Target tenant database: dev3 (QA). Promote to other tenants later.
--
-- One reading-set per (entry_date, sewing machine): EXACTLY 5 stitch counts
-- (stitches/dm) stored as a JSON string. calc_avg computed at save. std_stitch is a
-- fixed mill standard (9 stitches/dm) prefilled on the form, editable, and snapshotted
-- here. flag (OK / LOW / HIGH) is computed on read, NOT stored. No quality column
-- (machine-only report). No CV%, no MR correction. Morrah-shaped flat header.
;

CREATE TABLE IF NOT EXISTS jute_sqc_stitch (
    stitch_id         INT NOT NULL AUTO_INCREMENT,
    co_id             INT NOT NULL,
    branch_id         INT NULL,
    entry_date        DATE NOT NULL,
    mc_id             INT NULL,
    std_stitch        DECIMAL(6,2) NULL,
    readings          VARCHAR(200) NOT NULL,
    calc_avg          DECIMAL(6,2) NULL,
    inspector_name    VARCHAR(120) NULL,
    active            INT NOT NULL DEFAULT 1,
    updated_by        INT NULL,
    updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (stitch_id),
    INDEX idx_jute_sqc_stitch_co_id (co_id),
    INDEX idx_jute_sqc_stitch_entry_date (entry_date)
);

-- Rollback:
-- DROP TABLE jute_sqc_stitch;
