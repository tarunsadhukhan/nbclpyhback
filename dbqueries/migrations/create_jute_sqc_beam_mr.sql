-- Migration: R-08-18 Beam MR% SQC — warp-beam moisture-regain QC.
-- Module: juteSQC. Target tenant database: dev3 (QA). Promote to other tenants later.
--
-- One reading-set per (entry_date, quality_group, beam machine): EXACTLY 5 MR% readings
-- stored as a JSON string. avg_mr computed at save; std_mr defaults by quality group
-- (HESSIAN 16, SACKING 20) but is editable on the form and snapshotted here. Two quality
-- groups: HESSIAN & SACKING. No CV%, no pass/fail band. Morrah-shaped flat header.

CREATE TABLE IF NOT EXISTS jute_sqc_beam_mr (
    beam_mr_id        INT NOT NULL AUTO_INCREMENT,
    co_id             INT NOT NULL,
    branch_id         INT NULL,
    entry_date        DATE NOT NULL,
    quality_group     VARCHAR(20) NOT NULL,
    spell_id          INT NULL,
    item_id           INT NULL,
    mc_id             INT NULL,
    readings          VARCHAR(200) NOT NULL,
    calc_avg_mr       DECIMAL(6,2) NULL,
    std_mr_pct        DECIMAL(6,2) NULL,
    active            INT NOT NULL DEFAULT 1,
    updated_by        INT NULL,
    updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (beam_mr_id),
    INDEX idx_jute_sqc_beam_mr_co_id (co_id),
    INDEX idx_jute_sqc_beam_mr_entry_date (entry_date)
);

-- Rollback:
-- DROP TABLE jute_sqc_beam_mr;
