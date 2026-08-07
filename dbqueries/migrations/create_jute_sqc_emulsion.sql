-- Migration: create jute_sqc_emulsion (R-08-02 Emulsion)
-- Module: juteSQC. Daily batching jute-oil emulsion recipe log.
-- ONE flat row per (entry_date) save: header recipe fields + additive columns. NO readings
-- array, NO StDev/CV (this is a recipe log, not a sampled QC report). oil_pct_in_emulsion is
-- a MEASURED/typed input. std_oil_pct_low/high is the target band (prefilled 16/17, editable,
-- snapshotted at save). theoretical_oil_pct and oil_pct_status are computed server-side on
-- read (NOT stored).
-- Applies to: tenant database dev3 (QA). Promote to other tenants later.
;

CREATE TABLE IF NOT EXISTS jute_sqc_emulsion (
    emulsion_id INT NOT NULL AUTO_INCREMENT,
    co_id INT NOT NULL,
    branch_id INT NULL,
    entry_date DATE NOT NULL,
    mc_id INT NULL,
    oil_used_ltr DECIMAL(10,2) NULL,
    tank_capacity_ltr DECIMAL(10,2) NULL,
    oil_pct_in_emulsion DECIMAL(5,2) NULL,
    std_oil_pct_low DECIMAL(5,2) NULL,
    std_oil_pct_high DECIMAL(5,2) NULL,
    adco_used_ml DECIMAL(10,2) NULL,
    eco_fin_used_ltr DECIMAL(10,2) NULL,
    p40_gms DECIMAL(10,2) NULL,
    efjl_kg DECIMAL(10,2) NULL,
    glycerine_gms DECIMAL(10,2) NULL,
    castrol_oil DECIMAL(10,2) NULL,
    diesel_ltr DECIMAL(10,2) NULL,
    citric_acid_ltr DECIMAL(10,2) NULL,
    enzyme_gms DECIMAL(10,2) NULL,
    treated_water_ltr DECIMAL(10,2) NULL,
    rbo_ltr DECIMAL(10,2) NULL,
    jbo_ltr DECIMAL(10,2) NULL,
    molasses_kg DECIMAL(10,2) NULL,
    urea_kg DECIMAL(10,2) NULL,
    biochemical_kg DECIMAL(10,2) NULL,
    jsp66 DECIMAL(10,2) NULL,
    feel_free_good_ve_kg DECIMAL(10,2) NULL,
    spreader_rolls_made INT NULL,
    others VARCHAR(255) NULL,
    prepared_by VARCHAR(150) NULL,
    active INT NOT NULL DEFAULT 1,
    updated_by INT NULL,
    updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (emulsion_id),
    INDEX idx_jute_sqc_emulsion_co_id (co_id),
    INDEX idx_jute_sqc_emulsion_entry_date (entry_date)
);

-- Rollback (run manually, removing the comment dashes):
-- DROP TABLE IF EXISTS jute_sqc_emulsion
