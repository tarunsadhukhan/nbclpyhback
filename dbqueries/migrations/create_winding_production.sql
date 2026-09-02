-- Winding production entries (source: WINDING PRODUCTION.xlsx).
-- One row per worker + date + shift + quality: production hours and kg keyed in,
-- rate snapshotted from winding_incentive_mst.rate_per_hr at save time,
-- amount = rate * prod_hrs as a stored generated column
-- (e.g. 0.41666667 * 32 hrs = 13.33, matching the sheet's AMT column).
-- Scoped by branch_id (co filter via branch_mst); employee via eb_id.
-- Target DB: nbcl
-- Rollback: DROP TABLE winding_production;

CREATE TABLE IF NOT EXISTS winding_production (
    winding_prod_id INT PRIMARY KEY AUTO_INCREMENT,
    branch_id INT NOT NULL,
    prod_date DATE NOT NULL,
    shift VARCHAR(5) NOT NULL DEFAULT 'A',
    eb_id BIGINT NOT NULL,
    winding_incentive_id INT NOT NULL,
    grist DOUBLE NULL,
    prod_hrs DOUBLE NOT NULL,
    prod_kg DOUBLE NULL,
    rate DOUBLE NOT NULL,
    amount DOUBLE GENERATED ALWAYS AS (ROUND(rate * prod_hrs, 2)) STORED,
    remarks VARCHAR(255) NULL,
    active INT NOT NULL DEFAULT 1,
    KEY idx_winding_prod_branch_date (branch_id, prod_date),
    KEY idx_winding_prod_emp (eb_id)
);
