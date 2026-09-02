-- Beaming production entries (source: BEAMING PROD.xlsx).
-- One row per machine + date + shift + quality: production qty (kg/yds) keyed in,
-- rate snapshotted from tbl_nbcl_wages_quality_mst.quality_rate (BEAMING dept)
-- at save time, amount = rate * prod_qty as a stored generated column
-- (e.g. 0.000757 * 155000 = 117.34, matching the sheet's AMOUNT column).
-- WK HRS / LOST HRS / DIVISIBLE HRS are keyed on the machine+shift group row.
-- Scoped by branch_id (co filter via branch_mst); machine via machine_mst.
-- Target DB: nbcl
-- Rollback: DROP TABLE beaming_production;

CREATE TABLE IF NOT EXISTS beaming_production (
    beaming_prod_id INT PRIMARY KEY AUTO_INCREMENT,
    branch_id INT NOT NULL,
    prod_date DATE NOT NULL,
    shift VARCHAR(5) NOT NULL DEFAULT 'A',
    machine_id INT NOT NULL,
    quality_id INT NOT NULL,
    prod_qty DOUBLE NOT NULL,
    rate DOUBLE NOT NULL,
    amount DOUBLE GENERATED ALWAYS AS (ROUND(rate * prod_qty, 2)) STORED,
    wk_hrs DOUBLE NULL,
    lost_hrs DOUBLE NULL,
    divisible_hrs DOUBLE NULL,
    remarks VARCHAR(255) NULL,
    active INT NOT NULL DEFAULT 1,
    KEY idx_beaming_prod_branch_date (branch_id, prod_date),
    KEY idx_beaming_prod_machine (machine_id)
);
