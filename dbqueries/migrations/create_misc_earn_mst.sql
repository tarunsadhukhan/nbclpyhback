-- Misc Earn / Extra Allowance rules (source: MISC EARN CALCULATION.xlsx).
-- One rule per branch + department (+ optional occupation/designation) + earn type:
--   MISC EARN    -> "Rs. 75 per 96 hrs"                    amount=75,  per_hrs=96,  rate_pct=100
--   BEAM CHANGES -> "total value / divisible hrs * 60%"    amount=450, per_hrs=880, rate_pct=60
--   OIL CHARGE   -> "Rs. 8 per 8 hrs"                      amount=8,   per_hrs=8,   rate_pct=100
-- rate_per_hr is a stored generated column = amount / per_hrs * rate_pct / 100 (the xlsx formula).
-- Scoped by branch_id (dept_mst / designation_mst are branch-scoped); co_id comes via branch_mst.
-- Target DB: nbcl
-- Rollback: DROP TABLE misc_earn_mst;

CREATE TABLE IF NOT EXISTS misc_earn_mst (
    misc_earn_id INT PRIMARY KEY AUTO_INCREMENT,
    branch_id INT NOT NULL,
    dept_id INT NOT NULL,
    designation_id BIGINT NULL,
    earn_type VARCHAR(30) NOT NULL,
    amount DOUBLE NOT NULL,
    per_hrs DOUBLE NOT NULL,
    rate_pct DOUBLE NOT NULL DEFAULT 100,
    rate_per_hr DOUBLE GENERATED ALWAYS AS (amount / per_hrs * rate_pct / 100) STORED,
    remarks VARCHAR(255) NULL,
    active INT NOT NULL DEFAULT 1,
    KEY idx_misc_earn_branch_dept (branch_id, dept_id),
    KEY idx_misc_earn_desig (designation_id)
);
