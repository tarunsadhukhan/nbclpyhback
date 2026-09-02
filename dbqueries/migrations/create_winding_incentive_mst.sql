-- Winding Incentive scheme (source: WINDING INCENTIVE.xlsx).
-- One row per quality: warp qualities carry a flat incentive_amt per eligibility_hrs (96);
-- weft qualities carry one row per production slab (prod_from/prod_to bundles per 8 hrs),
-- with the grist range the slab applies to. rate_per_hr is a stored generated column
-- (incentive_amt / eligibility_hrs) — this is the winding production rate
-- (e.g. SACKING WARP: 40 / 96 = 0.41666667, matching the WINDING PRODUCTION sheet).
-- Role multipliers from the sheet (SIRDER 1.5x / MAZDOOR 0.75x / REALIVER 1x avg winder
-- incentive) are payroll-time rules, not master rows — not modelled here.
-- Tenant-wide (no co_id/branch_id), like tbl_nbcl_wages_quality_mst.
-- Target DB: nbcl
-- Rollback: DROP TABLE winding_incentive_mst;

CREATE TABLE IF NOT EXISTS winding_incentive_mst (
    winding_incentive_id INT PRIMARY KEY AUTO_INCREMENT,
    quality_code VARCHAR(10) NOT NULL,
    quality_name VARCHAR(100) NOT NULL,
    inc_code VARCHAR(10) NULL,
    grist_from DOUBLE NULL,
    grist_to DOUBLE NULL,
    prod_from DOUBLE NULL,
    prod_to DOUBLE NULL,
    incentive_amt DOUBLE NOT NULL,
    eligibility_hrs DOUBLE NOT NULL DEFAULT 96,
    rate_per_hr DOUBLE GENERATED ALWAYS AS (incentive_amt / eligibility_hrs) STORED,
    remarks VARCHAR(255) NULL,
    active INT NOT NULL DEFAULT 1,
    KEY idx_winding_incentive_quality (quality_code)
);

-- Seed straight from the sheet; runs only when the table is empty.
INSERT INTO winding_incentive_mst
    (quality_code, quality_name, inc_code, grist_from, grist_to, prod_from, prod_to, incentive_amt, eligibility_hrs, remarks)
SELECT * FROM (
    SELECT '01' code, 'HESS WARP' name_, '12' inc, NULL gf, NULL gt, NULL pf, NULL pt, 59 amt, 96 hrs, 'Rs. 59/- for 96 hrs' rem
    UNION ALL SELECT '02', 'SACKING WARP', '13', NULL, NULL, NULL, NULL, 40, 96, 'Rs. 40/- for 96 hrs'
    UNION ALL SELECT '05', 'SACKING WEFT 4.25"', '05', 20, 25, 16, 17.99, 30, 96, '16-17.99 bundles / 8 hrs'
    UNION ALL SELECT '05', 'SACKING WEFT 4.25"', '05', 20, 25, 18, 19.99, 35, 96, '18-19.99 bundles / 8 hrs'
    UNION ALL SELECT '05', 'SACKING WEFT 4.25"', '05', 20, 25, 20, 21.99, 45, 96, '20-21.99 bundles / 8 hrs'
    UNION ALL SELECT '05', 'SACKING WEFT 4.25"', '05', 20, 25, 22, NULL, 55, 96, '22 bundles & above / 8 hrs'
    UNION ALL SELECT '06', 'SACKING WEFT 5.50"', '06', 18, 21, NULL, NULL, 25.71, 96, 'Rs. 25.71/- for 96 hrs'
) s
WHERE NOT EXISTS (SELECT 1 FROM winding_incentive_mst);
