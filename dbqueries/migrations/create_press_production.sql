-- Press production entries (source: PRESS.xlsx).
-- One row per machine + date + shift + quality: production pcs keyed in,
-- rate snapshotted from tbl_nbcl_wages_quality_mst.quality_rate at save time,
-- amount = rate * prod_qty as a stored generated column
-- (e.g. 0.2669 * 1125 = 300.26, matching the sheet's AMOUNT column).
-- divisible_hrs is derived: wk_hrs * 4 (sheet: 120->480, 96->384) — note the
-- multiplier differs from beaming_production, which uses wk_hrs * 3.
-- The press machines (PM%) and Q-codes both live under dept_mst 'FINISHING'.
-- Scoped by branch_id (co filter via branch_mst); machine via machine_mst.
-- Target DB: nbcl
-- Rollback: DROP TABLE press_production;

CREATE TABLE IF NOT EXISTS press_production (
    press_prod_id INT PRIMARY KEY AUTO_INCREMENT,
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
    divisible_hrs DOUBLE GENERATED ALWAYS AS (wk_hrs * 4) STORED,
    remarks VARCHAR(255) NULL,
    active INT NOT NULL DEFAULT 1,
    KEY idx_press_prod_branch_date (branch_id, prod_date),
    KEY idx_press_prod_machine (machine_id)
);
