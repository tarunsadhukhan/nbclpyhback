-- Attendance Incentive rules (source: ATTEN_INCENTIVE.xlsx).
-- One rule per branch + employee category (category_mst): an amount paid per a block
-- of hours (e.g. "Rs. 1 per 8 hrs" for CAT-1..3/7, "Rs. 20 per 8 hrs" for CAT-4/8/9/10/14/15),
-- payable when the worker reaches eligibility_hrs (96) in the fortnight (F/E).
-- working_includes = hour buckets that count toward eligibility; calc_on = hour buckets
-- the incentive is actually paid on. rate_per_hr is a stored generated column = amount / per_hrs.
-- Scoped by branch_id (category_mst is branch-scoped); co_id comes via branch_mst.
-- Target DB: nbcl
-- Rollback: DROP TABLE atten_incentive_mst;

CREATE TABLE IF NOT EXISTS atten_incentive_mst (
    atten_incentive_id INT PRIMARY KEY AUTO_INCREMENT,
    branch_id INT NOT NULL,
    cata_id BIGINT NOT NULL,
    amount DOUBLE NOT NULL,
    per_hrs DOUBLE NOT NULL,
    eligibility_hrs DOUBLE NOT NULL DEFAULT 96,
    working_includes VARCHAR(100) NULL DEFAULT 'WK HRS+NS HRS+HOLIDAY HRS+LEAVE HRS',
    calc_on VARCHAR(100) NULL DEFAULT 'WK HRS+NS HRS',
    rate_per_hr DOUBLE GENERATED ALWAYS AS (amount / per_hrs) STORED,
    remarks VARCHAR(255) NULL,
    active INT NOT NULL DEFAULT 1,
    KEY idx_atten_incentive_branch_cat (branch_id, cata_id)
);
