-- Finishing (sewing) production entries (source: SEWING.xlsx).
-- One row per worker + date + shift + quality, from the mill's sewing sheets
-- (ECODE, ENAME, MC NAME, Q-CODE, TYPE, WK HRS, PROD, RATE, AMT, SHIFT).
-- The sheet's HIRAKOL / HEMMING sections are just machine groups (HK% / HM%
-- machines, both under dept_mst 'SEWING') — not stored.
-- Rate is snapshotted from tbl_nbcl_wages_quality_mst.quality_rate at save
-- time (sewing Q-codes live under dept_mst 'SEWING');
-- amount = rate * prod_qty (0.0567 * 1768 = 100.25, sheet AMT).
-- Scoped by branch_id (co filter via branch_mst); machine via machine_mst.
-- Target DB: nbcl
-- Rollback: DROP TABLE finishing_production;

CREATE TABLE IF NOT EXISTS finishing_production (
    finishing_prod_id INT PRIMARY KEY AUTO_INCREMENT,
    branch_id INT NOT NULL,
    prod_date DATE NOT NULL,
    shift VARCHAR(5) NOT NULL DEFAULT 'A',
    eb_id BIGINT NOT NULL,
    machine_id INT NOT NULL,
    quality_id INT NOT NULL,
    wk_hrs DOUBLE NULL,
    prod_qty DOUBLE NOT NULL,
    rate DOUBLE NOT NULL,
    amount DOUBLE GENERATED ALWAYS AS (ROUND(rate * prod_qty, 2)) STORED,
    remarks VARCHAR(255) NULL,
    active INT NOT NULL DEFAULT 1,
    KEY idx_finishing_prod_branch_date (branch_id, prod_date),
    KEY idx_finishing_prod_eb (eb_id)
);
