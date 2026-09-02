-- Weaving production entries (source: WEAVING PROD.xlsx).
-- One row per worker + date + shift + quality, from the mill's HESS/SACK
-- weaving sheets (C.NO., NAME, MC-1, MC-2, LINE NO., Q-CODE, QUALITY, TYPE,
-- WK HRS, PROD, RATE, VALUE/AMOUNT, PAYBLE AMT, SHIFT).
-- Rate is snapshotted from tbl_nbcl_wages_quality_mst.quality_rate at save
-- time; weaving Q-codes live under dept_mst 'HESSIAN WEAVING' /
-- 'SACKING WEAVING', and that dept is the sheet's TYPE column (HESS / SACK).
-- amount = rate * prod_qty (0.003474 * 2600 = 9.03, sheet VALUE);
-- payable_amt = amount * 0.8 (9.03 -> 7.22, 45 -> 36, sheet PAYBLE AMT).
-- A weaver runs a pair of looms: machine_id = MC-1, machine_id2 = MC-2.
-- Scoped by branch_id (co filter via branch_mst); looms via machine_mst.
-- Target DB: nbcl
-- Rollback: DROP TABLE weaving_production;

CREATE TABLE IF NOT EXISTS weaving_production (
    weaving_prod_id INT PRIMARY KEY AUTO_INCREMENT,
    branch_id INT NOT NULL,
    prod_date DATE NOT NULL,
    shift VARCHAR(5) NOT NULL DEFAULT 'A',
    eb_id BIGINT NOT NULL,
    machine_id INT NOT NULL,
    machine_id2 INT NULL,
    line_no VARCHAR(10) NULL,
    quality_id INT NOT NULL,
    wk_hrs DOUBLE NULL,
    prod_qty DOUBLE NOT NULL,
    rate DOUBLE NOT NULL,
    amount DOUBLE GENERATED ALWAYS AS (ROUND(rate * prod_qty, 2)) STORED,
    -- ponytail: payable is a flat 80% of value on every sheet row; switch to a
    -- keyed-in column if the percentage ever varies per worker or quality
    payable_amt DOUBLE GENERATED ALWAYS AS (ROUND(amount * 0.8, 2)) STORED,
    remarks VARCHAR(255) NULL,
    active INT NOT NULL DEFAULT 1,
    KEY idx_weaving_prod_branch_date (branch_id, prod_date),
    KEY idx_weaving_prod_eb (eb_id)
);
