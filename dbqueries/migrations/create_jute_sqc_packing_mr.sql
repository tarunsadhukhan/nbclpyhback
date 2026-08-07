-- Migration: R-08-25 Packing MR% SQC — finished-goods moisture at packing.
-- Module: juteSQC. Target tenant database: dev3 (QA). Promote to other tenants later.
--
-- One save = one (entry_date, quality column) reading-set: a flat header (entry_date,
-- quality_group HESSIAN|SACKING, optional cloth-quality item, optional construction_code
-- free text) plus EXACTLY 10 MR% readings stored as a JSON string. calc_avg_mr computed at
-- save. No std, no CV%, no MR correction, no pass/fail (averages only). Group roll-up
-- (weighted mean of all readings per quality_group) is computed on read, NOT stored.
-- Morrah-shaped flat header, single table -- NO detail table.
;

CREATE TABLE IF NOT EXISTS jute_sqc_packing_mr (
    packing_mr_id     INT NOT NULL AUTO_INCREMENT,
    co_id             INT NOT NULL,
    branch_id         INT NULL,
    entry_date        DATE NOT NULL,
    item_id           INT NULL,
    quality_group     VARCHAR(20) NOT NULL,
    quality_label     VARCHAR(255) NULL,
    construction_code VARCHAR(50) NULL,
    readings          VARCHAR(500) NOT NULL,
    calc_avg_mr       DECIMAL(6,3) NULL,
    active            INT NOT NULL DEFAULT 1,
    updated_by        INT NULL,
    updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (packing_mr_id),
    INDEX idx_jute_sqc_packing_mr_co_id (co_id),
    INDEX idx_jute_sqc_packing_mr_entry_date (entry_date)
);

-- Rollback:
-- DROP TABLE jute_sqc_packing_mr;
