-- =====================================================================================
-- nbjcl.nbjcl_wages_data_collection : fortnight data collection, one INSERT per step.
-- Each step adds its own rows (eb_id, period_id, <step columns>, updt_from = step tag);
-- every other column keeps its default 0, so SUM(...) GROUP BY eb_id gives the employee total.
--
-- Field rules : E:\sme\Smart_Eye\PayWages_Field_Lineage.xlsx
-- Pattern     : E:\test\nbcl\data\insertdatacollection.txt (steps 1 and 2 are that file's queries)
--
-- Run top to bottom in ONE session (the loan steps use temporary tables, step 25 reads
-- the rows written by steps 1-4).
-- =====================================================================================

-- ---------- period to collect --------------------------------------------------------
SET @branch_id = 87;
SET @from_date = '2026-09-01';
SET @to_date   = '2026-09-15';
SET @period_id = (SELECT ID FROM nbjcl.pay_period
                  WHERE branch_id = @branch_id AND FROM_DATE = @from_date AND TO_DATE = @to_date
                    AND code LIKE 'P%'
                  ORDER BY ID LIMIT 1);
SET @lwf_amt = 0;   -- labour welfare fund per worker (2nd fortnight of June and December only)
-- Legacy tables (payoloan, payloanchange, payloanadjust, paywages) are scoped by
-- CompCode = 'NJB' AND Location = 'FACTORY' (= branch 87). Change the literals for another mill.

-- ---------- clear the period so the script can be re-run ------------------------------
DELETE FROM nbjcl.nbjcl_wages_data_collection WHERE period_id = @period_id;

-- From insertdatacollection.txt. Left commented: it removes the processed wages of the period.
-- DELETE FROM nbjcl.paywages WHERE EDate = @to_date;


-- =====================================================================================
-- 1. Attendance  ->  working_hours, ot_hr, gp_hr
-- =====================================================================================
INSERT INTO nbjcl.nbjcl_wages_data_collection
(
    eb_id,
    period_id,
    working_hours,
    ot_hr,
    gp_hr,
    updt_from
)
SELECT
    da.eb_id,
    pp.id AS payperiodid,
    SUM(
        CASE
            WHEN da.attendance_type = 'R'
            THEN da.working_hours - da.idle_hours
            ELSE 0
        END
    ) AS whours,
    SUM(
        CASE
            WHEN da.attendance_type = 'O'
            THEN da.working_hours - da.idle_hours
            ELSE 0
        END
    ) AS othours,
    SUM(da.idle_hours),
    'ATT' AS updt_from
FROM nbjcl.daily_attendance da
INNER JOIN nbjcl.pay_period pp
    ON da.attendance_date BETWEEN pp.FROM_DATE AND pp.TO_DATE
    AND da.branch_id = pp.branch_id
WHERE pp.ID = @period_id
  AND da.branch_id = @branch_id
  AND da.is_active = 1
  AND da.status_id = 3
  AND da.attendance_type IN ('R', 'O')
GROUP BY
    da.eb_id,
    pp.id;


-- =====================================================================================
-- 2. NSh (night shift)  ->  ns_hrs, ot_ns_hrs
--    C-shift days, per day on net hours (working - idle), 2 decimals, then summed:
--      8 hrs -> hrs x 0.0625 (0.50),  5 hrs or more -> hrs x 0.0667 (7.5 -> 0.50, 7 -> 0.47),
--      below 5 -> 0. Regular days -> ns_hrs, overtime days -> ot_ns_hrs.
-- =====================================================================================
INSERT INTO nbjcl.nbjcl_wages_data_collection
(
    eb_id,
    period_id,
    ns_hrs,
    ot_ns_hrs,
    updt_from
)
SELECT
    da.eb_id,
    pp.id AS pay_period_id,
    SUM(
        CASE
            WHEN da.attendance_type = 'R' THEN
                ROUND(CASE
                          WHEN (da.working_hours - IFNULL(da.idle_hours, 0)) = 8
                          THEN (da.working_hours - IFNULL(da.idle_hours, 0)) * 0.0625
                          WHEN (da.working_hours - IFNULL(da.idle_hours, 0)) >= 5
                          THEN (da.working_hours - IFNULL(da.idle_hours, 0)) * 0.0667
                          ELSE 0
                      END, 2)
            ELSE 0
        END
    ) AS ns_workinghrs,
    SUM(
        CASE
            WHEN da.attendance_type = 'O' THEN
                ROUND(CASE
                          WHEN (da.working_hours - IFNULL(da.idle_hours, 0)) = 8
                          THEN (da.working_hours - IFNULL(da.idle_hours, 0)) * 0.0625
                          WHEN (da.working_hours - IFNULL(da.idle_hours, 0)) >= 5
                          THEN (da.working_hours - IFNULL(da.idle_hours, 0)) * 0.0667
                          ELSE 0
                      END, 2)
            ELSE 0
        END
    ) AS nsothrs,
    'NSH'
FROM nbjcl.daily_attendance da
INNER JOIN nbjcl.pay_period pp
    ON da.attendance_date BETWEEN pp.FROM_DATE AND pp.TO_DATE
    AND da.branch_id = pp.branch_id
LEFT JOIN nbjcl.spell_mst sm
    ON da.spell_id = sm.spell_id
WHERE pp.ID = @period_id
  AND da.branch_id = @branch_id
  AND da.is_active = 1
  AND da.status_id = 3
  AND da.attendance_type IN ('R', 'O')
  AND sm.spell_name = 'C'
GROUP BY
    da.eb_id,
    pp.id;


-- =====================================================================================
-- 3. Fest Hours  ->  fest_hours
--    Lineage Holiday_HR: holiday rows of the fortnight per employee (legacy PayWHoliday,
--    here hrms_holiday_transactions x holiday_master). Approved holidays only (status 3).
-- =====================================================================================
INSERT INTO nbjcl.nbjcl_wages_data_collection
(
    eb_id,
    period_id,
    fest_hours,
    updt_from
)
SELECT
    t.eb_id,
    @period_id,
    SUM(t.holiday_hours) AS festhours,
    'FEST'
FROM nbjcl.hrms_holiday_transactions t
INNER JOIN nbjcl.holiday_master h
    ON h.holiday_id = t.holiday_id
WHERE t.branch_id = @branch_id
  AND h.holiday_date BETWEEN @from_date AND @to_date
  AND h.status = 3
GROUP BY
    t.eb_id;


-- =====================================================================================
-- 4. STL Days  ->  stl_days
--    Approved (status 3) leave days of payable leave types falling inside the fortnight.
--    Branch 87 has no leave type named STL; its paid-leave types are the payable = 'Y' ones.
-- =====================================================================================
INSERT INTO nbjcl.nbjcl_wages_data_collection
(
    eb_id,
    period_id,
    stl_days,
    updt_from
)
SELECT
    lt.eb_id,
    @period_id,
    COUNT(DISTINCT ltd.leave_date) AS stldays,
    'STL'
FROM nbjcl.leave_transactions lt
INNER JOIN nbjcl.leave_tran_details ltd
    ON ltd.ltran_id = lt.leave_transaction_id
    AND ltd.is_active = 1
INNER JOIN nbjcl.hrms_leave_types_mst ltm
    ON ltm.leave_type_id = lt.leave_type_id
WHERE lt.branch_id = @branch_id
  AND lt.status = '3'
  AND ltm.payable = 'Y'
  AND ltd.leave_date BETWEEN @from_date AND @to_date
GROUP BY
    lt.eb_id;


-- =====================================================================================
-- 5. lost_hr  ->  lost_hr
--    NO SOURCE in nbjcl. Lineage: Lost_HR is a constant 0 (legacy procedure only).
--    Fill in the FROM when a lost-hours entry table exists.
-- =====================================================================================
-- INSERT INTO nbjcl.nbjcl_wages_data_collection (eb_id, period_id, lost_hr, updt_from)
-- SELECT x.eb_id, @period_id, SUM(x.lost_hours), 'LOST'
-- FROM <lost hours table> x
-- WHERE x.branch_id = @branch_id AND x.<date> BETWEEN @from_date AND @to_date
-- GROUP BY x.eb_id;


-- =====================================================================================
-- 6. layoff_hr  ->  layoff_hr
--    NO SOURCE in nbjcl. Lineage: SUM(ATTEN.LayOff_HR), which legacy filled from the
--    Atten_LayOff table; neither table is kept in nbjcl for the new attendance.
-- =====================================================================================
-- INSERT INTO nbjcl.nbjcl_wages_data_collection (eb_id, period_id, layoff_hr, updt_from)
-- SELECT x.eb_id, @period_id, SUM(x.layoff_hours), 'LAYOFF'
-- FROM <layoff table> x
-- WHERE x.branch_id = @branch_id AND x.<date> BETWEEN @from_date AND @to_date
-- GROUP BY x.eb_id;


-- =====================================================================================
-- 7. adj_pf  ->  adj_pf        (approved rows of the adjustments entry table)
-- =====================================================================================
INSERT INTO nbjcl.nbjcl_wages_data_collection
(
    eb_id,
    period_id,
    adj_pf,
    updt_from
)
SELECT
    a.eb_id,
    @period_id,
    SUM(a.adj_pf_amt),
    'ADJPF'
FROM nbjcl.adjustments a
INNER JOIN nbjcl.hrms_ed_official_details o
    ON o.eb_id = a.eb_id AND o.active = 1 AND o.branch_id = @branch_id
WHERE a.adj_date BETWEEN @from_date AND @to_date
  AND a.status = 3
GROUP BY
    a.eb_id
HAVING SUM(a.adj_pf_amt) <> 0;


-- =====================================================================================
-- 8. adj_npf  ->  adj_npf
-- =====================================================================================
INSERT INTO nbjcl.nbjcl_wages_data_collection
(
    eb_id,
    period_id,
    adj_npf,
    updt_from
)
SELECT
    a.eb_id,
    @period_id,
    SUM(a.adj_npf_amt),
    'ADJNPF'
FROM nbjcl.adjustments a
INNER JOIN nbjcl.hrms_ed_official_details o
    ON o.eb_id = a.eb_id AND o.active = 1 AND o.branch_id = @branch_id
WHERE a.adj_date BETWEEN @from_date AND @to_date
  AND a.status = 3
GROUP BY
    a.eb_id
HAVING SUM(a.adj_npf_amt) <> 0;


-- =====================================================================================
-- 9. adj_hr  ->  working_hours
--    Lineage Work_HR: + SUM(PayM_AdjHR.Adj_HR) of the fortnight. The approved hours of
--    the adjustments entry table are added as well. As in legacy the adjustment is folded
--    into Work_HR (88 worked - 8 adjusted = 80) and PayWages.Adj_HR stays 0. Step 28 works
--    DA and the night amount out on attendance hours only (updt_from ATT / NSH / FEST).
-- =====================================================================================
INSERT INTO nbjcl.nbjcl_wages_data_collection
(
    eb_id,
    period_id,
    working_hours,
    updt_from
)
SELECT
    x.eb_id,
    @period_id,
    SUM(x.adj_hr),
    'ADJHR'
FROM (
    SELECT h.eb_id, h.Adj_HR AS adj_hr
    FROM nbjcl.PayM_AdjHR h
    WHERE h.branch_id = @branch_id
      AND h.FNEDate = @to_date
    UNION ALL
    SELECT a.eb_id, a.adj_hours
    FROM nbjcl.adjustments a
    INNER JOIN nbjcl.hrms_ed_official_details o
        ON o.eb_id = a.eb_id AND o.active = 1 AND o.branch_id = @branch_id
    WHERE a.adj_date BETWEEN @from_date AND @to_date
      AND a.status = 3
) x
WHERE x.eb_id IS NOT NULL
GROUP BY
    x.eb_id
HAVING SUM(x.adj_hr) <> 0;


-- =====================================================================================
-- Loan preparation for steps 10-12 (legacy GetLoanEMI, as ported in
-- pyhback/src/hrms/wagesSalaryProcess.py _loan_emi). Two temporary tables:
--   _dc_loan_bal : balance per ECode at the period end
--   _dc_loan_emi : this fortnight's instalment per ECode
-- The "pay must still cover the instalment" test needs Wages_Gross, so it belongs to the
-- wages calculation, not to data collection: these are the instalments DUE.
-- =====================================================================================
DROP TEMPORARY TABLE IF EXISTS _dc_loan_bal;
CREATE TEMPORARY TABLE _dc_loan_bal (PRIMARY KEY (ECode)) AS
SELECT
    x.ECode,
    SUM(x.loan)      AS bal_loan,
    SUM(x.intr)      AS bal_int,
    SUM(x.adv)       AS bal_adv,
    MAX(x.loan_date) AS loan_date
FROM (
    -- PF loan given
    SELECT ECode, SUM(LoanAmt) AS loan, 0 AS intr, 0 AS adv, MAX(LoanDate) AS loan_date
    FROM nbjcl.payoloan
    WHERE CompCode = 'NJB' AND Location = 'FACTORY' AND DocStatus = 'OPEN'
      AND EMIDate <= @to_date AND LoanType = 'PFLOAN'
    GROUP BY ECode
    UNION ALL  -- PF loan interest charged
    SELECT ECode, 0, SUM(InterestAmt), 0, NULL
    FROM nbjcl.payoloan
    WHERE CompCode = 'NJB' AND Location = 'FACTORY' AND DocStatus = 'OPEN'
      AND EMIDate <= @to_date AND LoanType = 'PFINT'
    GROUP BY ECode
    UNION ALL  -- advance given
    SELECT ECode, 0, 0, SUM(LoanAmt), NULL
    FROM nbjcl.payoloan
    WHERE CompCode = 'NJB' AND Location = 'FACTORY' AND DocStatus = 'OPEN'
      AND EMIDate <= @to_date AND LoanType = 'ADVANCE'
    GROUP BY ECode
    UNION ALL  -- already recovered through wages before this period
    SELECT ECode, -SUM(PFLoanCap), -SUM(PFLoanInt), -SUM(Advance), NULL
    FROM nbjcl.paywages
    WHERE CompCode = 'NJB' AND Location = 'FACTORY' AND EDate < @to_date
    GROUP BY ECode
    UNION ALL  -- manual repayments
    SELECT ECode, -SUM(RepayCapital), 0, 0, NULL
    FROM nbjcl.payloanadjust
    WHERE CompCode = 'NJB' AND Location = 'FACTORY' AND ToDate <= @to_date AND LoanType = 'PFLOAN'
    GROUP BY ECode
    UNION ALL
    SELECT ECode, 0, -SUM(RepayInterest), 0, NULL
    FROM nbjcl.payloanadjust
    WHERE CompCode = 'NJB' AND Location = 'FACTORY' AND ToDate <= @to_date AND LoanType = 'PFINT'
    GROUP BY ECode
    UNION ALL
    SELECT ECode, 0, 0, -SUM(RepayCapital), NULL
    FROM nbjcl.payloanadjust
    WHERE CompCode = 'NJB' AND Location = 'FACTORY' AND ToDate <= @to_date AND LoanType = 'ADVANCE'
    GROUP BY ECode
) x
GROUP BY x.ECode
HAVING SUM(x.loan) > 0.005 OR SUM(x.intr) > 0.005 OR SUM(x.adv) > 0.005;

DROP TEMPORARY TABLE IF EXISTS _dc_loan_emi;
CREATE TEMPORARY TABLE _dc_loan_emi (PRIMARY KEY (ECode)) AS
SELECT
    q.ECode,
    q.bal_loan,
    q.bal_int,
    q.bal_adv,
    -- PF loan capital: stopped for this period -> 0; last instalment -> the balance;
    -- otherwise the EMI of the latest change after the loan, else of the open loan.
    CASE
        WHEN q.bal_loan <= 0.005 THEN 0
        WHEN q.cap_stop = 1 THEN 0
        WHEN COALESCE(q.cap_chg_n_emi, q.cap_base_emi, 0) > q.bal_loan THEN q.bal_loan
        ELSE COALESCE(q.cap_since_emi, q.cap_open_emi, q.cap_newest_chg_emi, 0)
    END AS inst_cap,
    -- PF loan interest: only once the capital is cleared.
    CASE
        WHEN NOT (ABS(q.bal_loan) <= 0.005 AND q.bal_int > 0.005) THEN 0
        WHEN q.int_stop = 1 THEN 0
        WHEN q.bal_int <= COALESCE(q.int_chg_emi, q.int_open_emi, 0) THEN q.bal_int
        ELSE COALESCE(q.int_chg2_emi, q.int_chg_emi, q.int_open_emi, 0)
    END AS inst_int,
    -- Advance: stopped -> 0; changed for this period -> the changed EMI;
    -- otherwise the latest open advance's EMI, capped by the balance.
    CASE
        WHEN q.adv_stop = 1 THEN 0
        WHEN IFNULL(q.adv_chg_emi, 0) <> 0 THEN q.adv_chg_emi
        WHEN IFNULL(q.adv_open_emi, 0) > q.bal_adv THEN q.bal_adv
        ELSE IFNULL(q.adv_open_emi, 0)
    END AS inst_adv
FROM (
    SELECT
        b.ECode, b.bal_loan, b.bal_int, b.bal_adv,
        EXISTS (SELECT 1 FROM nbjcl.payloanchange c
                WHERE c.CompCode = 'NJB' AND c.Location = 'FACTORY' AND c.ECode = b.ECode
                  AND UPPER(c.LoanType) = 'PFLOAN' AND c.ToDate = @to_date AND c.CapitalStop = 'Y') AS cap_stop,
        (SELECT c.EMICapital FROM nbjcl.payloanchange c
          WHERE c.CompCode = 'NJB' AND c.Location = 'FACTORY' AND c.ECode = b.ECode
            AND UPPER(c.LoanType) = 'PFLOAN' AND c.ToDate <= @to_date
            AND (b.loan_date IS NULL OR c.ToDate >= b.loan_date)
            AND c.EMICapital > 0 AND c.CapitalStop = 'N'
          ORDER BY c.ToDate DESC, c.DocEntry DESC, c.LineID DESC LIMIT 1) AS cap_chg_n_emi,
        (SELECT l.EMICapital FROM nbjcl.payoloan l
          WHERE l.CompCode = 'NJB' AND l.Location = 'FACTORY' AND l.ECode = b.ECode
            AND UPPER(l.LoanType) = 'PFLOAN' AND l.EMICapital > 0
          ORDER BY l.LoanDate DESC, l.DocEntry DESC, l.DocLineID DESC LIMIT 1) AS cap_base_emi,
        (SELECT c.EMICapital FROM nbjcl.payloanchange c
          WHERE c.CompCode = 'NJB' AND c.Location = 'FACTORY' AND c.ECode = b.ECode
            AND UPPER(c.LoanType) = 'PFLOAN' AND c.ToDate <= @to_date
            AND (b.loan_date IS NULL OR c.ToDate >= b.loan_date)
            AND c.EMICapital > 0
          ORDER BY c.ToDate DESC, c.DocEntry DESC, c.LineID DESC LIMIT 1) AS cap_since_emi,
        (SELECT l.EMICapital FROM nbjcl.payoloan l
          WHERE l.CompCode = 'NJB' AND l.Location = 'FACTORY' AND l.ECode = b.ECode
            AND UPPER(l.LoanType) = 'PFLOAN' AND l.DocStatus = 'OPEN'
            AND l.EMIDate <= @to_date AND l.EMICapital > 0
          ORDER BY l.LoanDate DESC, l.DocEntry DESC, l.DocLineID DESC LIMIT 1) AS cap_open_emi,
        (SELECT c.EMICapital FROM nbjcl.payloanchange c
          WHERE c.CompCode = 'NJB' AND c.Location = 'FACTORY' AND c.ECode = b.ECode
            AND UPPER(c.LoanType) = 'PFLOAN' AND c.ToDate <= @to_date
          ORDER BY c.ToDate DESC, c.DocEntry DESC, c.LineID DESC LIMIT 1) AS cap_newest_chg_emi,
        EXISTS (SELECT 1 FROM nbjcl.payloanchange c
                WHERE c.CompCode = 'NJB' AND c.Location = 'FACTORY' AND c.ECode = b.ECode
                  AND UPPER(c.LoanType) = 'PFINT' AND c.ToDate = @to_date AND c.InterestStop = 'Y') AS int_stop,
        (SELECT c.EMIInterest FROM nbjcl.payloanchange c
          WHERE c.CompCode = 'NJB' AND c.Location = 'FACTORY' AND c.ECode = b.ECode
            AND UPPER(c.LoanType) = 'PFINT' AND c.ToDate <= @to_date
            AND c.EMIInterest > 0 AND c.InterestStop = 'N'
          ORDER BY c.ToDate DESC, c.DocEntry DESC, c.LineID DESC LIMIT 1) AS int_chg_emi,
        (SELECT l.EMIInterest FROM nbjcl.payoloan l
          WHERE l.CompCode = 'NJB' AND l.Location = 'FACTORY' AND l.ECode = b.ECode
            AND UPPER(l.LoanType) = 'PFINT' AND l.EMIInterest > 0 AND l.EMIDate <= @to_date
          ORDER BY l.LoanDate DESC, l.DocEntry DESC, l.DocLineID DESC LIMIT 1) AS int_open_emi,
        (SELECT c.EMIInterest FROM nbjcl.payloanchange c
          WHERE c.CompCode = 'NJB' AND c.Location = 'FACTORY' AND c.ECode = b.ECode
            AND UPPER(c.LoanType) = 'PFINT' AND c.ToDate <= @to_date
            AND (b.loan_date IS NULL OR c.ToDate >= b.loan_date)
            AND c.EMIInterest > 0 AND c.InterestStop = 'N'
          ORDER BY c.ToDate DESC, c.DocEntry DESC, c.LineID DESC LIMIT 1) AS int_chg2_emi,
        EXISTS (SELECT 1 FROM nbjcl.payloanchange c
                WHERE c.CompCode = 'NJB' AND c.Location = 'FACTORY' AND c.ECode = b.ECode
                  AND UPPER(c.LoanType) = 'ADVANCE' AND c.ToDate = @to_date AND c.CapitalStop = 'Y') AS adv_stop,
        (SELECT c.EMICapital FROM nbjcl.payloanchange c
          WHERE c.CompCode = 'NJB' AND c.Location = 'FACTORY' AND c.ECode = b.ECode
            AND UPPER(c.LoanType) = 'ADVANCE' AND c.ToDate = @to_date AND c.CapitalStop = 'N'
          ORDER BY c.DocEntry DESC, c.LineID DESC LIMIT 1) AS adv_chg_emi,
        (SELECT l.EMICapital FROM nbjcl.payoloan l
          WHERE l.CompCode = 'NJB' AND l.Location = 'FACTORY' AND l.ECode = b.ECode
            AND UPPER(l.LoanType) = 'ADVANCE' AND l.DocStatus = 'OPEN' AND l.EMIDate <= @to_date
          ORDER BY l.EMIDate DESC, l.LoanDate DESC, l.DocEntry DESC, l.DocLineID DESC LIMIT 1) AS adv_open_emi
    FROM _dc_loan_bal b
) q;


-- =====================================================================================
-- 10. pfloan  ->  pfloan      (PF loan capital instalment due)
--     Category 05 workers are not recovered from (as in the wages process).
-- =====================================================================================
INSERT INTO nbjcl.nbjcl_wages_data_collection
(
    eb_id,
    period_id,
    pfloan,
    updt_from
)
SELECT
    o.eb_id,
    @period_id,
    e.inst_cap,
    'PFLOAN'
FROM _dc_loan_emi e
INNER JOIN nbjcl.hrms_ed_official_details o
    ON o.emp_code COLLATE utf8mb4_unicode_ci = e.ECode
    AND o.branch_id = @branch_id AND o.active = 1
LEFT JOIN nbjcl.category_mst g
    ON g.cata_id = o.catagory_id
WHERE e.inst_cap > 0
  AND (e.bal_loan + e.bal_int) > 0
  AND LEFT(IFNULL(g.cata_desc, ''), 2) <> '05';


-- =====================================================================================
-- 11. pfloanint  ->  pfloanint      (PF loan interest instalment due)
-- =====================================================================================
INSERT INTO nbjcl.nbjcl_wages_data_collection
(
    eb_id,
    period_id,
    pfloanint,
    updt_from
)
SELECT
    o.eb_id,
    @period_id,
    e.inst_int,
    'PFINT'
FROM _dc_loan_emi e
INNER JOIN nbjcl.hrms_ed_official_details o
    ON o.emp_code COLLATE utf8mb4_unicode_ci = e.ECode
    AND o.branch_id = @branch_id AND o.active = 1
LEFT JOIN nbjcl.category_mst g
    ON g.cata_id = o.catagory_id
WHERE e.inst_int > 0
  AND (e.bal_loan + e.bal_int) > 0
  AND LEFT(IFNULL(g.cata_desc, ''), 2) <> '05';


-- =====================================================================================
-- 12. advance  ->  advance      (advance instalment due)
-- =====================================================================================
INSERT INTO nbjcl.nbjcl_wages_data_collection
(
    eb_id,
    period_id,
    advance,
    updt_from
)
SELECT
    o.eb_id,
    @period_id,
    e.inst_adv,
    'ADV'
FROM _dc_loan_emi e
INNER JOIN nbjcl.hrms_ed_official_details o
    ON o.emp_code COLLATE utf8mb4_unicode_ci = e.ECode
    AND o.branch_id = @branch_id AND o.active = 1
WHERE e.inst_adv > 0
  AND e.bal_adv > 0;


-- =====================================================================================
-- 13. winding production  ->  Incentive_Amt
--     Steps 13, 14, 16, 17: the production amount goes into Incentive_Amt (step 15 loom
--     production goes into VBasic_Amt, as in legacy);
--     updt_from tells which production it came from.
-- =====================================================================================
INSERT INTO nbjcl.nbjcl_wages_data_collection
(
    eb_id,
    period_id,
    Incentive_Amt,
    updt_from
)
SELECT
    w.eb_id,
    @period_id,
    ROUND(SUM(w.amount), 2),
    'WDGPROD'
FROM nbjcl.winding_production w
WHERE w.branch_id = @branch_id
  AND w.active = 1
  AND w.prod_date BETWEEN @from_date AND @to_date
GROUP BY
    w.eb_id;


-- =====================================================================================
-- 14. beaming prod  ->  Incentive_Amt
--     beaming_production is per machine + shift, not per worker. Each worker gets
--     the machine's rate per man-hour (amount / divisible_hrs) x the regular hours he
--     attended on that machine in that shift during the fortnight.
-- =====================================================================================
INSERT INTO nbjcl.nbjcl_wages_data_collection
(
    eb_id,
    period_id,
    Incentive_Amt,
    updt_from
)
SELECT
    a.eb_id,
    @period_id,
    ROUND(SUM(a.hrs * p.rate_per_hr), 2),
    'BMGPROD'
FROM (
    SELECT da.eb_id, e.mc_id, sh.shift_name,
           SUM(da.working_hours - da.idle_hours) AS hrs
    FROM nbjcl.daily_ebmc_attendance e
    INNER JOIN nbjcl.daily_attendance da ON da.daily_atten_id = e.daily_atten_id
    INNER JOIN nbjcl.spell_mst sp ON sp.spell_id = da.spell_id
    INNER JOIN nbjcl.shift_mst sh ON sh.shift_id = sp.shift_id
    WHERE e.is_active = 1
      AND da.branch_id = @branch_id
      AND da.attendance_date BETWEEN @from_date AND @to_date
      AND da.is_active = 1
      AND da.status_id = 3
      AND da.attendance_type = 'R'
    GROUP BY da.eb_id, e.mc_id, sh.shift_name
) a
INNER JOIN (
    SELECT b.machine_id, b.shift,
           SUM(b.amount) / NULLIF(SUM(b.divisible_hrs), 0) AS rate_per_hr
    FROM nbjcl.beaming_production b
    WHERE b.branch_id = @branch_id
      AND b.active = 1
      AND b.prod_date BETWEEN @from_date AND @to_date
    GROUP BY b.machine_id, b.shift
) p
    ON p.machine_id = a.mc_id
    AND p.shift = CONVERT(a.shift_name USING utf8mb4)
GROUP BY
    a.eb_id;


-- =====================================================================================
-- 15. loomprod  ->  VBasic_Amt
--     Weaver's share: payable_amt (80% of the production value). Legacy GetRate adds
--     PayOProdWvg.PayableAmt (= weaving_production) to VBasic_Amt, not Incentive_Amt, and only
--     for category 01 / 02 / 03.
-- =====================================================================================
INSERT INTO nbjcl.nbjcl_wages_data_collection
(
    eb_id,
    period_id,
    VBasic_Amt,
    updt_from
)
SELECT
    w.eb_id,
    @period_id,
    ROUND(SUM(w.payable_amt), 2),
    'LOOMPROD'
FROM nbjcl.weaving_production w
INNER JOIN nbjcl.hrms_ed_official_details o
    ON o.eb_id = w.eb_id AND o.active = 1 AND o.branch_id = @branch_id
INNER JOIN nbjcl.category_mst g
    ON g.cata_id = o.catagory_id
WHERE w.branch_id = @branch_id
  AND w.active = 1
  AND w.prod_date BETWEEN @from_date AND @to_date
  AND g.cata_code IN ('01', '02', '03')
GROUP BY
    w.eb_id;


-- =====================================================================================
-- 16. sewing prod  ->  Incentive_Amt
--     finishing_production = the mill's SEWING sheet (hirakol / hemming).
-- =====================================================================================
INSERT INTO nbjcl.nbjcl_wages_data_collection
(
    eb_id,
    period_id,
    Incentive_Amt,
    updt_from
)
SELECT
    f.eb_id,
    @period_id,
    ROUND(SUM(f.amount), 2),
    'SWGPROD'
FROM nbjcl.finishing_production f
WHERE f.branch_id = @branch_id
  AND f.active = 1
  AND f.prod_date BETWEEN @from_date AND @to_date
GROUP BY
    f.eb_id;


-- =====================================================================================
-- 17. press prod  ->  Incentive_Amt
--     Same allocation as beaming, with the press sheet's own rate:
--     amount / (divisible_hrs - lost_hrs).
-- =====================================================================================
INSERT INTO nbjcl.nbjcl_wages_data_collection
(
    eb_id,
    period_id,
    Incentive_Amt,
    updt_from
)
SELECT
    a.eb_id,
    @period_id,
    ROUND(SUM(a.hrs * p.rate_per_hr), 2),
    'PRSPROD'
FROM (
    SELECT da.eb_id, e.mc_id, sh.shift_name,
           SUM(da.working_hours - da.idle_hours) AS hrs
    FROM nbjcl.daily_ebmc_attendance e
    INNER JOIN nbjcl.daily_attendance da ON da.daily_atten_id = e.daily_atten_id
    INNER JOIN nbjcl.spell_mst sp ON sp.spell_id = da.spell_id
    INNER JOIN nbjcl.shift_mst sh ON sh.shift_id = sp.shift_id
    WHERE e.is_active = 1
      AND da.branch_id = @branch_id
      AND da.attendance_date BETWEEN @from_date AND @to_date
      AND da.is_active = 1
      AND da.status_id = 3
      AND da.attendance_type = 'R'
    GROUP BY da.eb_id, e.mc_id, sh.shift_name
) a
INNER JOIN (
    SELECT b.machine_id, b.shift,
           SUM(b.amount) / NULLIF(SUM(b.divisible_hrs - IFNULL(b.lost_hrs, 0)), 0) AS rate_per_hr
    FROM nbjcl.press_production b
    WHERE b.branch_id = @branch_id
      AND b.active = 1
      AND b.prod_date BETWEEN @from_date AND @to_date
    GROUP BY b.machine_id, b.shift
) p
    ON p.machine_id = a.mc_id
    AND p.shift = CONVERT(a.shift_name USING utf8mb4)
GROUP BY
    a.eb_id;


-- =====================================================================================
-- 18. beamchange amt  ->  BeamChange_Amt
--     misc_earn_mst rule 'BEAM CHANGES' (per-hour rate) x regular hours worked in the
--     rule's department, for the rule's designation / category when the rule names one.
-- =====================================================================================
INSERT INTO nbjcl.nbjcl_wages_data_collection
(
    eb_id,
    period_id,
    BeamChange_Amt,
    updt_from
)
SELECT
    da.eb_id,
    @period_id,
    ROUND(SUM((da.working_hours - da.idle_hours) * m.rate_per_hr), 2),
    'BEAMCHG'
FROM nbjcl.daily_attendance da
INNER JOIN nbjcl.sub_dept_mst sd
    ON sd.sub_dept_id = da.worked_department_id
INNER JOIN nbjcl.hrms_ed_official_details o
    ON o.eb_id = da.eb_id AND o.active = 1
INNER JOIN nbjcl.misc_earn_mst m
    ON m.branch_id = da.branch_id
    AND m.active = 1
    AND m.earn_type = 'BEAM CHANGES'
    AND m.dept_id = sd.dept_id
    AND (m.designation_id IS NULL OR m.designation_id = da.worked_designation_id)
    AND (m.cata_id IS NULL OR m.cata_id = o.catagory_id)
WHERE da.branch_id = @branch_id
  AND da.attendance_date BETWEEN @from_date AND @to_date
  AND da.is_active = 1
  AND da.status_id = 3
  AND da.attendance_type = 'R'
GROUP BY
    da.eb_id;


-- =====================================================================================
-- 19. oil amount  ->  Oil_Amt      (misc_earn_mst rule 'OIL CHARGE')
-- =====================================================================================
INSERT INTO nbjcl.nbjcl_wages_data_collection
(
    eb_id,
    period_id,
    Oil_Amt,
    updt_from
)
SELECT
    da.eb_id,
    @period_id,
    ROUND(SUM((da.working_hours - da.idle_hours) * m.rate_per_hr), 2),
    'OIL'
FROM nbjcl.daily_attendance da
INNER JOIN nbjcl.sub_dept_mst sd
    ON sd.sub_dept_id = da.worked_department_id
INNER JOIN nbjcl.hrms_ed_official_details o
    ON o.eb_id = da.eb_id AND o.active = 1
INNER JOIN nbjcl.misc_earn_mst m
    ON m.branch_id = da.branch_id
    AND m.active = 1
    AND m.earn_type = 'OIL CHARGE'
    AND m.dept_id = sd.dept_id
    AND (m.designation_id IS NULL OR m.designation_id = da.worked_designation_id)
    AND (m.cata_id IS NULL OR m.cata_id = o.catagory_id)
WHERE da.branch_id = @branch_id
  AND da.attendance_date BETWEEN @from_date AND @to_date
  AND da.is_active = 1
  AND da.status_id = 3
  AND da.attendance_type = 'R'
GROUP BY
    da.eb_id;


-- =====================================================================================
-- 20. pfearn adj  ->  PFEarnAdj
--     Lineage: SUM(PayM_Adjustment.AdjPF) for FNEDate = period end (nbjcl: PayM_AdjPF).
-- =====================================================================================
INSERT INTO nbjcl.nbjcl_wages_data_collection
(
    eb_id,
    period_id,
    PFEarnAdj,
    updt_from
)
SELECT
    a.eb_id,
    @period_id,
    SUM(a.Adj_Amt),
    'PFEARNADJ'
FROM nbjcl.PayM_AdjPF a
WHERE a.branch_id = @branch_id
  AND a.FNEDate = @to_date
  AND a.eb_id IS NOT NULL
GROUP BY
    a.eb_id;


-- =====================================================================================
-- 20a. DA / HRA arrears  ->  PFEarnAdj                                    updt_from ARREAR
--      Legacy #Arrear: PayM_AdjArrear rows not yet paid (Paid_FNEDate 1900-01-01, legacy '')
--      or already paid in this fortnight (re-run). Marked paid after step 42.
-- =====================================================================================
INSERT INTO nbjcl.nbjcl_wages_data_collection
(
    eb_id,
    period_id,
    PFEarnAdj,
    updt_from
)
SELECT
    a.eb_id,
    @period_id,
    SUM(a.Arrear_Amt),
    'ARREAR'
FROM nbjcl.PayM_AdjArrear a
WHERE a.branch_id = @branch_id
  AND a.Paid_FNEDate IN ('1900-01-01', @to_date)
  AND a.eb_id IS NOT NULL
GROUP BY
    a.eb_id;


-- =====================================================================================
-- 21. npf earn adj  ->  NPFEarnAdj
--     Lineage: SUM(PayM_Adjustment.AdjNPF) for FNEDate = period end (nbjcl: PayM_AdjNPF).
-- =====================================================================================
INSERT INTO nbjcl.nbjcl_wages_data_collection
(
    eb_id,
    period_id,
    NPFEarnAdj,
    updt_from
)
SELECT
    a.eb_id,
    @period_id,
    SUM(a.Adj_Amt),
    'NPFEARNADJ'
FROM nbjcl.PayM_AdjNPF a
WHERE a.branch_id = @branch_id
  AND a.FNEDate = @to_date
  AND a.eb_id IS NOT NULL
GROUP BY
    a.eb_id;


-- =====================================================================================
-- 22. misc earn  ->  MiscEarn      (misc_earn_mst rule 'MISC EARN')
-- =====================================================================================
INSERT INTO nbjcl.nbjcl_wages_data_collection
(
    eb_id,
    period_id,
    MiscEarn,
    updt_from
)
SELECT
    da.eb_id,
    @period_id,
    ROUND(SUM((da.working_hours - da.idle_hours) * m.rate_per_hr), 2),
    'MISC'
FROM nbjcl.daily_attendance da
INNER JOIN nbjcl.sub_dept_mst sd
    ON sd.sub_dept_id = da.worked_department_id
INNER JOIN nbjcl.hrms_ed_official_details o
    ON o.eb_id = da.eb_id AND o.active = 1
INNER JOIN nbjcl.misc_earn_mst m
    ON m.branch_id = da.branch_id
    AND m.active = 1
    AND m.earn_type = 'MISC EARN'
    AND m.dept_id = sd.dept_id
    AND (m.designation_id IS NULL OR m.designation_id = da.worked_designation_id)
    AND (m.cata_id IS NULL OR m.cata_id = o.catagory_id)
WHERE da.branch_id = @branch_id
  AND da.attendance_date BETWEEN @from_date AND @to_date
  AND da.is_active = 1
  AND da.status_id = 3
  AND da.attendance_type = 'R'
GROUP BY
    da.eb_id;


-- =====================================================================================
-- 23. adj basic  ->  fbasicamt                                           updt_from ADJBASIC
--     Basic amount of the fortnight's hour adjustments (PayM_AdjHR.Adj_BSAmt). As in legacy
--     GetRate it is folded into FBasic_Amt (attendance basic + Adj_BSAmt); PayWages.AdjBasic
--     stays 0. Step 28 works the night amount out on the attendance basic only.
-- =====================================================================================
INSERT INTO nbjcl.nbjcl_wages_data_collection
(
    eb_id,
    period_id,
    fbasicamt,
    updt_from
)
SELECT
    h.eb_id,
    @period_id,
    SUM(h.Adj_BSAmt),
    'ADJBASIC'
FROM nbjcl.PayM_AdjHR h
WHERE h.branch_id = @branch_id
  AND h.FNEDate = @to_date
  AND h.eb_id IS NOT NULL
GROUP BY
    h.eb_id
HAVING SUM(h.Adj_BSAmt) <> 0;


-- =====================================================================================
-- 23b. adj DA  ->  daamount                                              updt_from ADJDA
--     DA amount of the fortnight's hour adjustments (PayM_AdjHR.Adj_DAAmt), folded into
--     DA_Amt as in legacy GetRate (attendance DA + Adj_DAAmt).
-- =====================================================================================
INSERT INTO nbjcl.nbjcl_wages_data_collection
(
    eb_id,
    period_id,
    daamount,
    updt_from
)
SELECT
    h.eb_id,
    @period_id,
    SUM(h.Adj_DAAmt),
    'ADJDA'
FROM nbjcl.PayM_AdjHR h
WHERE h.branch_id = @branch_id
  AND h.FNEDate = @to_date
  AND h.eb_id IS NOT NULL
GROUP BY
    h.eb_id
HAVING SUM(h.Adj_DAAmt) <> 0;


-- =====================================================================================
-- 24. incentive  ->  Incentive_Amt
--     NO SOURCE in nbjcl. Lineage rule (per day line): Rs 20 where DeptCode = '16' and
--     OcpCode = '1609' and Work_HR >= 8; Rs 10 where OcpCode = '1608' and Work_HR >= 8;
--     plus Rs 50 when the 1609 worker's fortnight hours >= 46. designation_mst carries no
--     occupation code, so 1608 / 1609 cannot be identified yet.
-- =====================================================================================
-- INSERT INTO nbjcl.nbjcl_wages_data_collection (eb_id, period_id, Incentive_Amt, updt_from)
-- SELECT da.eb_id, @period_id,
--        SUM(CASE WHEN (da.working_hours - da.idle_hours) >= 8
--                 THEN CASE da.worked_designation_id WHEN <1609 id> THEN 20 WHEN <1608 id> THEN 10 ELSE 0 END
--                 ELSE 0 END)
--        + CASE WHEN MAX(da.worked_designation_id = <1609 id>) = 1
--                AND SUM(da.working_hours - da.idle_hours) >= 46 THEN 50 ELSE 0 END,
--        'INCENTIVE'
-- FROM nbjcl.daily_attendance da
-- WHERE da.branch_id = @branch_id AND da.attendance_date BETWEEN @from_date AND @to_date
--   AND da.is_active = 1 AND da.status_id = 3 AND da.attendance_type = 'R'
--   AND da.worked_designation_id IN (<1609 id>, <1608 id>)
-- GROUP BY da.eb_id;


-- =====================================================================================
-- 25. Attendance Incentive  ->  Atten_Amt
--     atten_incentive_mst rule of the worker's category. Eligible when
--     WK HRS + NS HRS + HOLIDAY HRS + LEAVE HRS >= eligibility_hrs (96); paid on
--     WK HRS + NS HRS: amount x ROUND(hours / per_hrs).
--     Reads the hours collected by steps 1-4, so it must run after them.
-- =====================================================================================
INSERT INTO nbjcl.nbjcl_wages_data_collection
(
    eb_id,
    period_id,
    Atten_Amt,
    updt_from
)
SELECT
    x.eb_id,
    @period_id,
    m.amount * ROUND((x.wk_hrs + x.ns_hrs) / m.per_hrs, 0),
    'ATTINC'
FROM (
    SELECT dc.eb_id,
           SUM(dc.working_hours) AS wk_hrs,
           SUM(dc.ns_hrs)        AS ns_hrs,
           SUM(dc.fest_hours)    AS fest_hrs,
           SUM(dc.stl_days) * 8  AS leave_hrs
    FROM nbjcl.nbjcl_wages_data_collection dc
    WHERE dc.period_id = @period_id
      AND dc.updt_from IN ('ATT', 'NSH', 'FEST', 'STL')
    GROUP BY dc.eb_id
) x
INNER JOIN nbjcl.hrms_ed_official_details o
    ON o.eb_id = x.eb_id AND o.active = 1
INNER JOIN nbjcl.atten_incentive_mst m
    ON m.branch_id = @branch_id
    AND m.cata_id = o.catagory_id
    AND m.active = 1
WHERE (x.wk_hrs + x.ns_hrs + x.fest_hrs + x.leave_hrs) >= m.eligibility_hrs
  AND m.per_hrs > 0;


-- =====================================================================================
-- 26. electricity  ->  Electricity      (electric_details rows tagged with the period)
-- =====================================================================================
INSERT INTO nbjcl.nbjcl_wages_data_collection
(
    eb_id,
    period_id,
    Electricity,
    updt_from
)
SELECT
    e.eb_id,
    @period_id,
    ROUND(SUM(e.amount), 2),
    'ELEC'
FROM nbjcl.electric_details e
WHERE e.branch_id = @branch_id
  AND e.period_id = @period_id
  AND e.active = 1
GROUP BY
    e.eb_id;


-- =====================================================================================
-- 27. Previous YTD  ->  Prev_YTD_Days, prev_YTD_BNSGrs, prev_YTD_PFGross, prev_YTD_UTHWAdv,
--                       prev_YTD_PFEmployee, prev_YTD_Pension, prev_YTD_FPF, prev_YTD_LoanAmt,
--                       prev_YTD_IntAmt, prev_YTD_SplAdvance, prev_YTD_Advance
--     The YTD_* figures of the worker's latest WAGES slip in the 12 months before this
--     period (paywages).
--     They are copied as they stand: in the first period of a new year the wages
--     calculation must still reset them (days: calendar year, PF: financial year).
-- =====================================================================================
INSERT INTO nbjcl.nbjcl_wages_data_collection
(
    eb_id,
    period_id,
    Prev_YTD_Days,
    prev_YTD_BNSGrs,
    prev_YTD_PFGross,
    prev_YTD_UTHWAdv,
    prev_YTD_PFEmployee,
    prev_YTD_Pension,
    prev_YTD_FPF,
    prev_YTD_LoanAmt,
    prev_YTD_IntAmt,
    prev_YTD_SplAdvance,
    prev_YTD_Advance,
    updt_from
)
SELECT
    o.eb_id,
    @period_id,
    w.YTD_Days,
    w.YTD_BNSGrs,
    w.YTD_PFGross,
    w.YTD_UTHWAdv,
    w.YTD_PFEmployee,
    w.YTD_Pension,
    w.YTD_FPF,
    w.YTD_LoanAmt,
    w.YTD_IntAmt,
    w.YTD_SplAdvance,
    w.YTD_Advance,
    'PREVYTD'
FROM (
    SELECT p.ECode, p.YTD_Days, p.YTD_BNSGrs, p.YTD_PFGross, p.YTD_UTHWAdv, p.YTD_PFEmployee,
           p.YTD_Pension, p.YTD_FPF, p.YTD_LoanAmt, p.YTD_IntAmt, p.YTD_SplAdvance, p.YTD_Advance,
           ROW_NUMBER() OVER (PARTITION BY p.ECode ORDER BY p.EDate DESC) AS rn
    FROM nbjcl.paywages p
    WHERE p.CompCode = 'NJB' AND p.Location = 'FACTORY'
      AND p.PaySlipType = 'WAGES'
      AND p.EDate < @from_date
      AND p.EDate >= DATE_SUB(@from_date, INTERVAL 1 YEAR)  -- an older slip's YTD is stale
) w
INNER JOIN nbjcl.hrms_ed_official_details o
    ON o.emp_code COLLATE utf8mb4_unicode_ci = w.ECode
    AND o.branch_id = @branch_id AND o.active = 1
WHERE w.rn = 1;


-- =====================================================================================
-- 27b. Fixed basic  ->  fbasicamt                                       updt_from FBASIC
--     Legacy SP_WagesProcessing_Daily. Employee rate: PayOWagesRate, latest EffDate on or
--     before the period end. Occupation rate: PayOWagesRate_OCP of the worked designation
--     (designation_mst.occu_code), latest EFFDate on or before the period start.
--       category (cata_code) 02 / 03 and the occupation has a rate : Rate   / FBasic_HR x hours
--       otherwise (no occupation check)                            : FBasic / FBasic_HR x hours
--     (legacy: LEFT(PayOEMP.EGroup, 2) IN ('02','03')). Legacy works out FBasic on DUTY and OT
--     rows, but GetRate carries only the DUTY rows into PayWages.FBasic_Amt, so regular (R)
--     hours are used here.
--     One row per employee per rate used, hours summed first, so the amount is rounded once
--     per rate and not per day. Working hours of regular (R) attendance, as step 1.
-- =====================================================================================
INSERT INTO nbjcl.nbjcl_wages_data_collection
(
    eb_id,
    period_id,
    fbasicamt,
    updt_from
)
SELECT
    f.eb_id,
    @period_id,
    ROUND(f.rate / f.fbasic_hr * f.hrs, 2),
    'FBASIC'
FROM (
    SELECT
        da.eb_id,
        por.FBasic_HR AS fbasic_hr,
        IFNULL(CASE WHEN g.cata_code IN ('02', '03') THEN poo.Rate END, por.FBasic) AS rate,
        SUM(da.working_hours - IFNULL(da.idle_hours, 0)) AS hrs
    FROM nbjcl.daily_attendance da
    LEFT JOIN nbjcl.designation_mst dm
        ON dm.designation_id = da.worked_designation_id
    LEFT JOIN nbjcl.hrms_ed_official_details o
        ON o.eb_id = da.eb_id AND o.active = 1
    LEFT JOIN nbjcl.category_mst g
        ON g.cata_id = o.catagory_id
    INNER JOIN (
        SELECT p.eb_id, p.FBasic, p.FBasic_HR
        FROM nbjcl.PayOWagesRate p
        INNER JOIN (
            SELECT eb_id, MAX(EffDate) AS me
            FROM nbjcl.PayOWagesRate
            WHERE EffDate <= @to_date
            GROUP BY eb_id
        ) m
            ON m.eb_id = p.eb_id AND m.me = p.EffDate
    ) por
        ON por.eb_id = da.eb_id
    LEFT JOIN (
        SELECT o.OcpCode, o.Rate
        FROM nbjcl.PayOWagesRate_OCP o
        INNER JOIN (
            SELECT OcpCode, MAX(EFFDate) AS me
            FROM nbjcl.PayOWagesRate_OCP
            WHERE EFFDate <= @from_date
            GROUP BY OcpCode
        ) m
            ON m.OcpCode = o.OcpCode AND m.me = o.EFFDate
    ) poo
        ON poo.OcpCode = dm.occu_code COLLATE utf8mb4_unicode_ci
    WHERE da.branch_id = @branch_id
      AND da.attendance_date BETWEEN @from_date AND @to_date
      AND da.is_active = 1
      AND da.status_id = 3
      AND da.attendance_type = 'R'
    GROUP BY
        da.eb_id,
        por.FBasic_HR,
        IFNULL(CASE WHEN g.cata_code IN ('02', '03') THEN poo.Rate END, por.FBasic)
) f
WHERE f.fbasic_hr > 0;


-- =====================================================================================
-- 27c. Variable basic  ->  VBasic_Amt                                    updt_from VBASIC
--     Work_HR x 0.51, only for employees of category (cata_code) 01 / 02 / 03 and only for
--     the regular working hours worked in occupation 0205 (worked designation's
--     designation_mst.occu_code). Other categories get no variable basic.
-- =====================================================================================
INSERT INTO nbjcl.nbjcl_wages_data_collection
(
    eb_id,
    period_id,
    VBasic_Amt,
    updt_from
)
SELECT
    da.eb_id,
    @period_id,
    ROUND(SUM(da.working_hours - IFNULL(da.idle_hours, 0)) * 0.51, 2),
    'VBASIC'
FROM nbjcl.daily_attendance da
INNER JOIN nbjcl.designation_mst dm
    ON dm.designation_id = da.worked_designation_id
INNER JOIN nbjcl.hrms_ed_official_details o
    ON o.eb_id = da.eb_id AND o.active = 1
INNER JOIN nbjcl.category_mst g
    ON g.cata_id = o.catagory_id
WHERE da.branch_id = @branch_id
  AND da.attendance_date BETWEEN @from_date AND @to_date
  AND da.is_active = 1
  AND da.status_id = 3
  AND da.attendance_type = 'R'
  AND dm.occu_code = '0205'
  AND g.cata_code IN ('01', '02', '03')
GROUP BY da.eb_id
HAVING SUM(da.working_hours - IFNULL(da.idle_hours, 0)) > 0;


-- =====================================================================================
-- 27d. Sewing production  ->  VBasic_Amt                                 updt_from VBASICSWG
--     Legacy GetOthAmt "11-SEWING": the fortnight's PayOProdSwg rows of dept 11 go to
--     PayOProdVBasic with their Amount, and GetRate sums them into VBasic_Amt for
--     categories 01 / 02 / 03 only.
-- =====================================================================================
INSERT INTO nbjcl.nbjcl_wages_data_collection
(
    eb_id,
    period_id,
    VBasic_Amt,
    updt_from
)
SELECT
    s.eb_id,
    @period_id,
    SUM(s.Amount),
    'VBASICSWG'
FROM nbjcl.payoprodswg s
INNER JOIN nbjcl.hrms_ed_official_details o
    ON o.eb_id = s.eb_id AND o.active = 1 AND o.branch_id = @branch_id
INNER JOIN nbjcl.category_mst g
    ON g.cata_id = o.catagory_id
WHERE s.branch_id = @branch_id
  AND s.FNEDate = @to_date
  AND s.DeptCode = '11'
  AND g.cata_code IN ('01', '02', '03')
GROUP BY s.eb_id
HAVING SUM(s.Amount) <> 0;


-- =====================================================================================
-- 27e. Winding production  ->  VBasic_Amt                                updt_from VBASICWDG
--     Legacy GetOthAmt "05-WINDING/0501-COP WINDER": production kg x the quality's rate in
--     PayOQLT (dept 05), summed by GetRate into VBasic_Amt for category 01 / 02 / 03.
--     Separate from step 13, which pays the winding incentive from the same rows.
--     winding_quality_mst codes do not follow the legacy QCode, so the quality is matched on
--     its name, ignoring spaces and no-break spaces.
-- =====================================================================================
INSERT INTO nbjcl.nbjcl_wages_data_collection
(
    eb_id,
    period_id,
    VBasic_Amt,
    updt_from
)
SELECT
    w.eb_id,
    @period_id,
    SUM(ROUND(w.prod_kg * q.Rate, 2)),
    'VBASICWDG'
FROM nbjcl.winding_production w
INNER JOIN nbjcl.winding_quality_mst wq
    ON wq.wdg_q_id = w.wdg_q_id
INNER JOIN nbjcl.PayOQLT q
    ON q.DeptCode = '05'
    AND REPLACE(REPLACE(q.QName, ' ', ''), CHAR(0xC2A0 USING utf8mb4), '')
      = REPLACE(REPLACE(wq.quality_desc, ' ', ''), CHAR(0xC2A0 USING utf8mb4), '') COLLATE utf8mb4_unicode_ci
INNER JOIN nbjcl.hrms_ed_official_details o
    ON o.eb_id = w.eb_id AND o.active = 1 AND o.branch_id = @branch_id
INNER JOIN nbjcl.category_mst g
    ON g.cata_id = o.catagory_id
WHERE w.branch_id = @branch_id
  AND w.active = 1
  AND w.prod_date BETWEEN @from_date AND @to_date
  AND g.cata_code IN ('01', '02', '03')
GROUP BY w.eb_id
HAVING SUM(ROUND(w.prod_kg * q.Rate, 2)) <> 0;


-- =====================================================================================
-- 27f. Weaving line sirder / line helper  ->  VBasic_Amt                 updt_from VBASICWVG
--     Legacy GetOthAmt "30-SACKING WEAVING" and "32-HESSIAN WEAVING", per shift (spell):
--       shift rate = loom production amount of the department's looms in the shift
--                    (weaving_production, loom dept from machine_mst = legacy PayOProdWvg
--                    DeptCode) / weaver working hours of the department in the shift
--       VBasic     = the employee's hours of the shift in the occupation x shift rate x factor
--         3001 sacking line sirder : dept 30, weavers 3005, factor 143.5 / 100
--         3004 sacking line helper : dept 30, weavers 3005, factor 1
--         3201 hessian line sirder : dept 32, weavers 3202, factor 143.5 / 100
--         3203 hessian line helper : dept 32, weavers 3202, factor 1
--     Rates held to 6 decimals as in legacy; amount rounded per employee, occupation and
--     shift, summed by GetRate for category 01 / 02 / 03.
-- =====================================================================================
INSERT INTO nbjcl.nbjcl_wages_data_collection
(
    eb_id,
    period_id,
    VBasic_Amt,
    updt_from
)
SELECT
    ls.eb_id,
    @period_id,
    SUM(ROUND(ls.hrs * ROUND(IFNULL(rx.rate, 0) * ls.factor, 6), 2)),
    'VBASICWVG'
FROM (
    SELECT da.eb_id, oc.dept, oc.factor, sp.spell_code AS shift,
           SUM(da.working_hours - IFNULL(da.idle_hours, 0)) AS hrs
    FROM nbjcl.daily_attendance da
    INNER JOIN nbjcl.designation_mst dm
        ON dm.designation_id = da.worked_designation_id
    INNER JOIN nbjcl.spell_mst sp
        ON sp.spell_id = da.spell_id
    INNER JOIN (
        SELECT '3001' AS occ, '30' AS dept, 1.435 AS factor
        UNION ALL SELECT '3004', '30', 1
        UNION ALL SELECT '3201', '32', 1.435
        UNION ALL SELECT '3203', '32', 1
    ) oc
        ON oc.occ = dm.occu_code
    WHERE da.branch_id = @branch_id
      AND da.attendance_date BETWEEN @from_date AND @to_date
      AND da.is_active = 1
      AND da.status_id = 3
      AND da.attendance_type = 'R'
    GROUP BY da.eb_id, dm.occu_code, oc.dept, oc.factor, sp.spell_code
) ls
LEFT JOIN (
    SELECT p.dept, p.shift, ROUND(p.amt / h.hrs, 6) AS rate
    FROM (
        SELECT d.dept_code AS dept, w.shift, SUM(w.amount) AS amt
        FROM nbjcl.weaving_production w
        INNER JOIN nbjcl.machine_mst m
            ON m.machine_id = w.machine_id
        INNER JOIN nbjcl.dept_mst d
            ON d.dept_id = m.dept_id
        WHERE w.branch_id = @branch_id
          AND w.active = 1
          AND w.prod_date BETWEEN @from_date AND @to_date
          AND d.dept_code IN ('30', '32')
        GROUP BY d.dept_code, w.shift
    ) p
    INNER JOIN (
        SELECT CASE dm.occu_code WHEN '3005' THEN '30' ELSE '32' END AS dept, sp.spell_code AS shift,
               SUM(da.working_hours - IFNULL(da.idle_hours, 0)) AS hrs
        FROM nbjcl.daily_attendance da
        INNER JOIN nbjcl.designation_mst dm
            ON dm.designation_id = da.worked_designation_id
        INNER JOIN nbjcl.spell_mst sp
            ON sp.spell_id = da.spell_id
        WHERE da.branch_id = @branch_id
          AND da.attendance_date BETWEEN @from_date AND @to_date
          AND da.is_active = 1
          AND da.status_id = 3
          AND da.attendance_type = 'R'
          AND dm.occu_code IN ('3005', '3202')
        GROUP BY CASE dm.occu_code WHEN '3005' THEN '30' ELSE '32' END, sp.spell_code
    ) h
        ON h.dept = p.dept AND h.shift = p.shift
    WHERE h.hrs > 0
) rx
    ON rx.dept = ls.dept AND rx.shift = ls.shift
INNER JOIN nbjcl.hrms_ed_official_details o
    ON o.eb_id = ls.eb_id AND o.active = 1 AND o.branch_id = @branch_id
INNER JOIN nbjcl.category_mst g
    ON g.cata_id = o.catagory_id
WHERE g.cata_code IN ('01', '02', '03')
GROUP BY ls.eb_id
HAVING SUM(ROUND(ls.hrs * ROUND(IFNULL(rx.rate, 0) * ls.factor, 6), 2)) <> 0;


-- =====================================================================================
-- 27g. Beaming  ->  VBasic_Amt                                           updt_from VBASICBMG
--     Legacy GetOthAmt "07-BEAMING" (PayOProdBmg). Per machine and shift of the fortnight
--     (beaming_production):
--       TotalValue = production value x machine hrs / (machine hrs - lost hrs)
--       KAV        = 5% of TotalValue
--       Rate1 = (TotalValue - KAV) / divisible hrs,  Rate2 = KAV / 32,  Rate3 = KAV / 48
--     An employee is matched to EVERY machine of the shift he or she worked in, and the
--     rate is averaged across those machines (legacy AVG(Rate) x AVG(Prod_HR)):
--       0701 beamer sirder : hours of the shift x AVG(Rate1 + Rate2)
--       0702 beamer        : hours of the shift x AVG(Rate1)
--       0703 head beamer   : hours of the shift x AVG(Rate1 + Rate3)
--     Rounded per employee, occupation and shift; GetRate sums it into VBasic_Amt for
--     category 01 / 02 / 03.
-- =====================================================================================
INSERT INTO nbjcl.nbjcl_wages_data_collection
(
    eb_id,
    period_id,
    VBasic_Amt,
    updt_from
)
SELECT
    a.eb_id,
    @period_id,
    SUM(ROUND(a.hrs * CASE a.occ WHEN '0701' THEN r.rate_0701
                                 WHEN '0702' THEN r.rate_0702
                                 ELSE r.rate_0703 END, 2)),
    'VBASICBMG'
FROM (
    SELECT da.eb_id, dm.occu_code AS occ, sh.shift_name,
           SUM(da.working_hours - IFNULL(da.idle_hours, 0)) AS hrs
    FROM nbjcl.daily_attendance da
    INNER JOIN nbjcl.designation_mst dm
        ON dm.designation_id = da.worked_designation_id
    INNER JOIN nbjcl.spell_mst sp
        ON sp.spell_id = da.spell_id
    INNER JOIN nbjcl.shift_mst sh
        ON sh.shift_id = sp.shift_id
    WHERE da.branch_id = @branch_id
      AND da.attendance_date BETWEEN @from_date AND @to_date
      AND da.is_active = 1
      AND da.status_id = 3
      AND da.attendance_type = 'R'
      AND dm.occu_code IN ('0701', '0702', '0703')
    GROUP BY da.eb_id, dm.occu_code, sh.shift_name
) a
INNER JOIN (
    SELECT m.shift,
           AVG(m.rate1 + m.rate2) AS rate_0701,
           AVG(m.rate1)           AS rate_0702,
           AVG(m.rate1 + m.rate3) AS rate_0703
    FROM (
        SELECT b.shift,
               ROUND(0.95 * b.tv / b.dh, 6) AS rate1,
               ROUND(0.05 * b.tv / 32, 6)   AS rate2,
               ROUND(0.05 * b.tv / 48, 6)   AS rate3
        FROM (
            SELECT bp.shift, bp.machine_id,
                   SUM(bp.amount) * SUM(bp.wk_hrs) / NULLIF(SUM(bp.wk_hrs) - SUM(bp.lost_hrs), 0) AS tv,
                   SUM(bp.divisible_hrs) AS dh
            FROM nbjcl.beaming_production bp
            WHERE bp.branch_id = @branch_id
              AND bp.active = 1
              AND bp.prod_date BETWEEN @from_date AND @to_date
            GROUP BY bp.shift, bp.machine_id
        ) b
        WHERE b.dh > 0 AND b.tv IS NOT NULL
    ) m
    GROUP BY m.shift
) r
    ON r.shift = CONVERT(a.shift_name USING utf8mb4)
INNER JOIN nbjcl.hrms_ed_official_details o
    ON o.eb_id = a.eb_id AND o.active = 1 AND o.branch_id = @branch_id
INNER JOIN nbjcl.category_mst g
    ON g.cata_id = o.catagory_id
WHERE g.cata_code IN ('01', '02', '03')
GROUP BY a.eb_id;


-- =====================================================================================
-- 27h. Finishing press  ->  VBasic_Amt                                   updt_from VBASICPRS
--     Legacy GetOthAmt "12-FINISHING" as is: the press rows of the fortnight
--     (payoprodpress, FNEDate = period end, dept 12) already carry Prod_HR and Rate1-4
--     (FrmProdPress). An employee who worked the occupation in a shift is matched to EVERY
--     press row of that shift; per shift and quality, the MACHINE hours and the rate are
--     averaged across the rows:
--       amount = AVG(Prod_HR) x AVG(rate)
--       1201 pressman 1 : Rate1 + Rate2      1202 pressman 2 : Rate1 + Rate3
--       1203 pressman 3 : Rate1 + Rate4      1204 pressman 4 : Rate1 + Rate4
--     Rounded per employee, occupation, shift and quality; GetRate sums it into VBasic_Amt
--     for category 01 / 02 / 03.
-- =====================================================================================
INSERT INTO nbjcl.nbjcl_wages_data_collection
(
    eb_id,
    period_id,
    VBasic_Amt,
    updt_from
)
SELECT
    a.eb_id,
    @period_id,
    SUM(ROUND(r.avg_hrs * CASE a.occ WHEN '1201' THEN r.rate_1201
                                     WHEN '1202' THEN r.rate_1202
                                     ELSE r.rate_1203 END, 2)),
    'VBASICPRS'
FROM (
    SELECT DISTINCT da.eb_id, dm.occu_code AS occ, sh.shift_name
    FROM nbjcl.daily_attendance da
    INNER JOIN nbjcl.designation_mst dm
        ON dm.designation_id = da.worked_designation_id
    INNER JOIN nbjcl.spell_mst sp
        ON sp.spell_id = da.spell_id
    INNER JOIN nbjcl.shift_mst sh
        ON sh.shift_id = sp.shift_id
    WHERE da.branch_id = @branch_id
      AND da.attendance_date BETWEEN @from_date AND @to_date
      AND da.is_active = 1
      AND da.status_id = 3
      AND da.attendance_type = 'R'
      AND dm.occu_code IN ('1201', '1202', '1203', '1204')
) a
INNER JOIN (
    SELECT m.WShift, m.QCode,
           AVG(m.Prod_HR)         AS avg_hrs,
           AVG(m.Rate1 + m.Rate2) AS rate_1201,
           AVG(m.Rate1 + m.Rate3) AS rate_1202,
           AVG(m.Rate1 + m.Rate4) AS rate_1203
    FROM (
        SELECT DISTINCT pr.WShift, pr.MachCode, pr.QCode, pr.Prod_HR, pr.Rate1, pr.Rate2, pr.Rate3, pr.Rate4
        FROM nbjcl.payoprodpress pr
        WHERE pr.branch_id = @branch_id
          AND pr.FNEDate = @to_date
          AND pr.DeptCode = '12'
    ) m
    GROUP BY m.WShift, m.QCode
) r
    ON r.WShift = CONVERT(a.shift_name USING utf8mb4)
INNER JOIN nbjcl.hrms_ed_official_details o
    ON o.eb_id = a.eb_id AND o.active = 1 AND o.branch_id = @branch_id
INNER JOIN nbjcl.category_mst g
    ON g.cata_id = o.catagory_id
WHERE g.cata_code IN ('01', '02', '03')
GROUP BY a.eb_id;


-- =====================================================================================
-- 28. Rates, basic, DA and night amount
--       ->  OFBasic, OFBasic_HR, FBasic_Rate, DA_Rate, daamount, NS_Amt
--     Rate in force at the period end (worker_rate_mst: latest effective row, the active
--     row wins a tie), applied to the hours collected by steps 1-3:
--       OFBasic     = fbasic                      OFBasic_HR = fbasic_hr (208)
--       FBasic_Rate = fbasic / fbasic_hr          fbasicamt  = sum of the FBASIC rows (27b)
--       DA_Rate     = da_rate when DA applies     daamount   = da_rate / fbasic_hr x working hours
--       NS_Amt      = (fbasicamt + VBasic_Amt + daamount) / working hours x night hours
--     Same rules as the migrated wage rows and the existing wages process. Reads the hours
--     of steps 1-2 and the basic of step 27b, so it must run after them.
-- =====================================================================================
INSERT INTO nbjcl.nbjcl_wages_data_collection
(
    eb_id,
    period_id,
    OFBasic,
    OFBasic_HR,
    FBasic_Rate,
    DA_Rate,
    daamount,
    NS_Amt,
    updt_from
)
SELECT
    y.eb_id,
    @period_id,
    y.fbasic,
    y.fbasic_hr,
    y.fbasic / y.fbasic_hr,
    y.da_rate,
    y.da_amt,
    CASE WHEN y.wk_hrs > 0 THEN ROUND((y.fb_amt + y.vb_amt + y.da_amt) / y.wk_hrs * y.ns_hrs, 2) ELSE 0 END,
    'RATE'
FROM (
    SELECT
        x.eb_id,
        x.wk_hrs,
        IFNULL(fb.vb_amt, 0) AS vb_amt,
        x.ns_hrs,
        r.fbasic,
        r.fbasic_hr,
        -- category 05 carries no DA rate on the slip
        CASE WHEN r.da_all = 'Y' AND LEFT(IFNULL(g.cata_desc, ''), 2) <> '05' THEN r.da_rate ELSE 0 END AS da_rate,
        IFNULL(fb.fb_amt, 0) AS fb_amt,
        CASE WHEN r.da_all = 'Y' THEN ROUND(r.da_rate / r.fbasic_hr * x.wk_hrs, 2) ELSE 0 END AS da_amt
    FROM (
        SELECT dc.eb_id,
               SUM(dc.working_hours) AS wk_hrs,
               SUM(dc.ns_hrs)        AS ns_hrs
        FROM nbjcl.nbjcl_wages_data_collection dc
        WHERE dc.period_id = @period_id
          AND dc.updt_from IN ('ATT', 'NSH', 'FEST')
        GROUP BY dc.eb_id
    ) x
    INNER JOIN (
        SELECT w.eb_id, w.fbasic, w.fbasic_hr, w.da_all, w.da_rate
        FROM (
            SELECT wr.*,
                   ROW_NUMBER() OVER (PARTITION BY wr.eb_id
                                      ORDER BY wr.effective_date DESC, wr.is_active DESC, wr.worker_rate_id DESC) AS rn
            FROM nbjcl.worker_rate_mst wr
            WHERE wr.effective_date <= @to_date
        ) w
        WHERE w.rn = 1
    ) r
        ON r.eb_id = x.eb_id
    LEFT JOIN (
        SELECT dc.eb_id, SUM(dc.fbasicamt) AS fb_amt, SUM(dc.VBasic_Amt) AS vb_amt
        FROM nbjcl.nbjcl_wages_data_collection dc
        WHERE dc.period_id = @period_id
          AND dc.updt_from IN ('FBASIC', 'VBASIC', 'VBASICSWG', 'VBASICWDG', 'VBASICWVG', 'VBASICBMG', 'VBASICPRS', 'LOOMPROD')
        GROUP BY dc.eb_id
    ) fb
        ON fb.eb_id = x.eb_id
    LEFT JOIN nbjcl.hrms_ed_official_details o
        ON o.eb_id = x.eb_id AND o.active = 1
    LEFT JOIN nbjcl.category_mst g
        ON g.cata_id = o.catagory_id
    WHERE r.fbasic_hr > 0
) y;


-- =====================================================================================
-- CALCULATION STEPS (29-41)
-- Every calculation is written to the collection table first, as its own rows with its
-- own updt_from tag, exactly like the collection steps. Each step reads the employee's
-- totals of the rows written so far, so the order matters. Rules: the existing wages
-- process (pyhback/src/hrms/wagesSalaryProcess.py) and the migrated wage rows.
--
-- Two temporary tables are prepared first:
--   _dc_rate  : per employee - legacy code, category group and the rate-master flags
--   _dc_month : per legacy code - what the EARLIER fortnight of the same month already
--               holds in paywages (PF, ESI and professional tax are monthly). Earlier only:
--               legacy runs the halves in order, so a 1st-half re-run must not see the 2nd half
-- =====================================================================================
DROP TEMPORARY TABLE IF EXISTS _dc_rate;
CREATE TEMPORARY TABLE _dc_rate (PRIMARY KEY (eb_id)) AS
SELECT
    o.eb_id,
    o.emp_code COLLATE utf8mb4_unicode_ci AS ECode,
    LEFT(IFNULL(g.cata_desc, ''), 2)      AS grp,
    IFNULL(r.hra, 'N')  AS hra,
    IFNULL(r.hrd, 'N')  AS hrd,
    IFNULL(r.pf, 'N')   AS pf,
    IFNULL(r.esi, 'N')  AS esi,
    IFNULL(r.ptax, 'N') AS ptax
FROM nbjcl.hrms_ed_official_details o
LEFT JOIN nbjcl.category_mst g
    ON g.cata_id = o.catagory_id
LEFT JOIN (
    SELECT w.eb_id, w.hra, w.hrd, w.pf, w.esi, w.ptax
    FROM (
        SELECT wr.*,
               ROW_NUMBER() OVER (PARTITION BY wr.eb_id
                                  ORDER BY wr.effective_date DESC, wr.is_active DESC, wr.worker_rate_id DESC) AS rn
        FROM nbjcl.worker_rate_mst wr
        WHERE wr.effective_date <= @to_date
    ) w
    WHERE w.rn = 1
) r
    ON r.eb_id = o.eb_id
WHERE o.active = 1
  AND o.branch_id = @branch_id
  AND IFNULL(o.emp_code, '') <> '';

DROP TEMPORARY TABLE IF EXISTS _dc_month;
CREATE TEMPORARY TABLE _dc_month (PRIMARY KEY (ECode)) AS
SELECT
    m.ECode,
    -- first-fortnight PF figures (PF members outside category 05)
    SUM(CASE WHEN m.WDay = '01' AND m.OPF = 'Y' AND LEFT(m.EGroup, 2) <> '05' THEN m.PF_Gross ELSE 0 END)   AS h_pf_gross,
    SUM(CASE WHEN m.WDay = '01' AND m.OPF = 'Y' AND LEFT(m.EGroup, 2) <> '05' THEN m.PFEmployee ELSE 0 END) AS h_pfe,
    SUM(CASE WHEN m.WDay = '01' AND m.OPF = 'Y' AND LEFT(m.EGroup, 2) <> '05' THEN m.Pension ELSE 0 END)    AS h_833,
    SUM(CASE WHEN m.WDay = '01' AND m.OPF = 'Y' AND LEFT(m.EGroup, 2) <> '05' THEN m.CoC ELSE 0 END)        AS h_167,
    SUM(m.ESI_Gross)                                            AS h_esi_gross,
    SUM(m.Wages_Gross)                                          AS h_wages,
    SUM(m.Work_HR + m.NS_HR + m.Holiday_HR + m.STL_HR)          AS h_hrs,
    SUM(CASE WHEN DAY(m.EDate) = 15 THEN m.ESI_Amt ELSE 0 END)  AS h_esi_amt,
    SUM(CASE WHEN m.WDay = '01' THEN m.PTax_Amt ELSE 0 END)     AS h_ptax_paid
FROM nbjcl.paywages m
WHERE m.CompCode = 'NJB' AND m.Location = 'FACTORY'
  AND m.Grade = 'MILL-WORKMEN'
  AND YEAR(m.EDate) = YEAR(@to_date) AND MONTH(m.EDate) = MONTH(@to_date)
  AND m.EDate < @to_date
GROUP BY m.ECode;


-- =====================================================================================
-- 29. Holiday amount  ->  Holiday_Amt                                   updt_from HOLAMT
--     Worked in the period : (basic + variable basic + DA) / working hours x festival hours
--     Holiday only         : (basic per hour + DA per hour) x festival hours
-- =====================================================================================
INSERT INTO nbjcl.nbjcl_wages_data_collection
(
    eb_id,
    period_id,
    Holiday_Amt,
    updt_from
)
SELECT
    s.eb_id,
    @period_id,
    CASE
        WHEN s.wk_hrs > 0 THEN ROUND((s.fb_amt + s.vb_amt + s.da_amt) / s.wk_hrs * s.fest_hrs, 2)
        WHEN s.of_hr > 0 THEN ROUND((s.fb_rate + s.da_rate / s.of_hr) * s.fest_hrs, 2)
        ELSE 0
    END,
    'HOLAMT'
FROM (
    SELECT dc.eb_id,
           SUM(dc.working_hours) AS wk_hrs,
           SUM(dc.fest_hours)    AS fest_hrs,
           SUM(dc.fbasicamt)     AS fb_amt,
           SUM(dc.VBasic_Amt)    AS vb_amt,
           SUM(dc.daamount)      AS da_amt,
           SUM(dc.FBasic_Rate)   AS fb_rate,
           SUM(dc.DA_Rate)       AS da_rate,
           SUM(dc.OFBasic_HR)    AS of_hr
    FROM nbjcl.nbjcl_wages_data_collection dc
    WHERE dc.period_id = @period_id
    GROUP BY dc.eb_id
    HAVING SUM(dc.fest_hours) > 0
) s;


-- =====================================================================================
-- 30. PF gross  ->  PF_Gross, HRA_Gross, BNSGrs                        updt_from PFGROSS
--     basic + variable basic + DA + night + holiday + STL + PF earning adjustment + lost-hour + layoff amount.
--     HRA gross and bonus gross are the same figure.
-- =====================================================================================
INSERT INTO nbjcl.nbjcl_wages_data_collection
(
    eb_id,
    period_id,
    PF_Gross,
    HRA_Gross,
    BNSGrs,
    updt_from
)
SELECT
    s.eb_id,
    @period_id,
    s.pf_gross,
    s.pf_gross,
    s.pf_gross,
    'PFGROSS'
FROM (
    SELECT dc.eb_id,
           SUM(dc.fbasicamt + dc.VBasic_Amt + dc.daamount + dc.NS_Amt + dc.Holiday_Amt + dc.STL_Amt
               + dc.adj_pf + dc.PFEarnAdj + dc.LostHR_Amt + dc.LayOffHR_Amt) AS pf_gross
    FROM nbjcl.nbjcl_wages_data_collection dc
    WHERE dc.period_id = @period_id
    GROUP BY dc.eb_id
) s
WHERE s.pf_gross <> 0;


-- =====================================================================================
-- 31. HRA  ->  HRA_Rate, HRA_Amt                                           updt_from HRA
--     7.5% of HRA gross, rounded to the rupee, for workers flagged for HRA in the rate master.
-- =====================================================================================
INSERT INTO nbjcl.nbjcl_wages_data_collection
(
    eb_id,
    period_id,
    HRA_Rate,
    HRA_Amt,
    updt_from
)
SELECT
    s.eb_id,
    @period_id,
    7.5,
    ROUND(s.hra_gross * 7.5 / 100, 0),
    'HRA'
FROM (
    SELECT dc.eb_id, SUM(dc.HRA_Gross) AS hra_gross
    FROM nbjcl.nbjcl_wages_data_collection dc
    WHERE dc.period_id = @period_id
    GROUP BY dc.eb_id
) s
INNER JOIN _dc_rate r
    ON r.eb_id = s.eb_id
WHERE r.hra = 'Y'
  AND s.hra_gross <> 0;


-- =====================================================================================
-- 32. Gross  ->  ESI_Gross, PTax_Gross, Wages_Gross, Pension_Gross       updt_from GROSS
--     PF gross + non-PF earning adjustment + HRA + misc earn + beam change + incentive
--     (production) + extra + oil + attendance incentive. Pension gross = PF gross rounded.
-- =====================================================================================
INSERT INTO nbjcl.nbjcl_wages_data_collection
(
    eb_id,
    period_id,
    ESI_Gross,
    PTax_Gross,
    Wages_Gross,
    Pension_Gross,
    updt_from
)
SELECT
    s.eb_id,
    @period_id,
    s.gross,
    s.gross,
    s.gross,
    ROUND(s.pf_gross, 0),
    'GROSS'
FROM (
    SELECT dc.eb_id,
           SUM(dc.PF_Gross) AS pf_gross,
           SUM(dc.PF_Gross + dc.adj_npf + dc.NPFEarnAdj + dc.HRA_Amt + dc.MiscEarn + dc.BeamChange_Amt
               + dc.Incentive_Amt + dc.Extra_Amt + dc.Oil_Amt + dc.Atten_Amt) AS gross
    FROM nbjcl.nbjcl_wages_data_collection dc
    WHERE dc.period_id = @period_id
    GROUP BY dc.eb_id
) s
WHERE s.gross <> 0 OR s.pf_gross <> 0;


-- =====================================================================================
-- 33. Provident fund  ->  PFEmployee, Pension, CoC                          updt_from PF
--     PF is monthly (wage ceiling 15,000: PF 1,500 = pension 1,250 + balance 250).
--       1st fortnight : 10% of its own PF gross; pension 8.33% (max 1,250); CoC = the rest.
--       2nd fortnight : the month's figure less what the 1st fortnight already took.
--     No UAN -> no pension share. Age 58 or more at the period start -> all PF goes to CoC.
--     PF members only (rate master PF = 'Y'), category 05 excluded.
-- =====================================================================================
INSERT INTO nbjcl.nbjcl_wages_data_collection
(
    eb_id,
    period_id,
    PFEmployee,
    Pension,
    CoC,
    updt_from
)
SELECT
    z.eb_id,
    @period_id,
    z.pf_emp,
    CASE WHEN z.no_uan = 1 OR z.age58 = 1 THEN 0 ELSE z.p833 END,
    CASE WHEN z.age58 = 1 THEN z.pf_emp ELSE z.p167 END,
    'PF'
FROM (
    SELECT
        y.eb_id, y.no_uan, y.age58,
        CASE
            WHEN DAY(@from_date) = 1 THEN ROUND(ROUND(y.g_cur, 0) * 10 / 100, 0)
            WHEN y.pfe1 >= 1500 THEN 0
            WHEN y.pfe1 = 0 THEN y.r10
            ELSE y.r10 - y.pfe1
        END AS pf_emp,
        CASE
            WHEN DAY(@from_date) = 1 THEN LEAST(1250, ROUND(y.g_cur * 8.33 / 100, 0))
            WHEN 1500 - y.pfe1 < 0 THEN 0
            WHEN y.r10 >= 1500 THEN 1250 - y.f833
            WHEN y.pfe1 > 0 THEN y.r833 - y.f833
            ELSE ROUND(y.g_cur * 8.33 / 100, 0)
        END AS p833,
        CASE
            WHEN DAY(@from_date) = 1 THEN
                CASE WHEN ROUND(y.g_cur * 8.33 / 100, 0) >= 1250 THEN 250
                     ELSE ROUND(y.g_cur * 10 / 100, 0) - ROUND(y.g_cur * 8.33 / 100, 0) END
            WHEN 1500 - y.pfe1 < 0 THEN 0
            WHEN y.r10 >= 1500 THEN 250 - y.f167
            WHEN y.pfe1 > 0 AND (y.r10 - y.r833) >= 250 THEN 250 - y.f167
            WHEN y.pfe1 > 0 THEN y.r10 - y.r833 - y.f167
            WHEN y.pfe1 = 0 THEN y.r10 - y.r833
            ELSE ROUND(y.g_cur * 10 / 100, 0) - ROUND(y.g_cur * 8.33 / 100, 0)
        END AS p167
    FROM (
        SELECT
            x.eb_id, x.g_cur, x.pfe1, x.f833, x.f167, x.no_uan, x.age58,
            ROUND(LEAST(15000, ROUND(x.g_first + x.g_cur, 0)) * 10 / 100, 0)   AS r10,
            ROUND(LEAST(15000, ROUND(x.g_first + x.g_cur, 0)) * 8.33 / 100, 0) AS r833
        FROM (
            SELECT
                s.eb_id,
                s.pf_gross               AS g_cur,
                IFNULL(h.h_pf_gross, 0)  AS g_first,
                IFNULL(h.h_pfe, 0)       AS pfe1,
                IFNULL(h.h_833, 0)       AS f833,
                IFNULL(h.h_167, 0)       AS f167,
                CASE WHEN IFNULL(pf.uan, '') = '' THEN 1 ELSE 0 END AS no_uan,
                CASE WHEN pf.pension_date IS NOT NULL
                      AND FLOOR(DATEDIFF(@from_date, pf.pension_date) / 365.25) >= 58 THEN 1 ELSE 0 END AS age58
            FROM (
                SELECT dc.eb_id, SUM(dc.PF_Gross) AS pf_gross
                FROM nbjcl.nbjcl_wages_data_collection dc
                WHERE dc.period_id = @period_id
                GROUP BY dc.eb_id
                HAVING SUM(dc.working_hours + dc.ot_hr + dc.fest_hours + dc.stl_days) > 0
            ) s
            INNER JOIN _dc_rate r
                ON r.eb_id = s.eb_id
            LEFT JOIN _dc_month h
                ON h.ECode = r.ECode
            LEFT JOIN (
                SELECT p.eb_id, MAX(p.pf_uan_no) AS uan, MAX(p.pension_date) AS pension_date
                FROM nbjcl.hrms_ed_pf p
                WHERE p.active = 1
                GROUP BY p.eb_id
            ) pf
                ON pf.eb_id = s.eb_id
            WHERE r.pf = 'Y'
              AND r.grp <> '05'
        ) x
    ) y
) z;


-- =====================================================================================
-- 34. ESI  ->  ESI_Amt, ESIC                                               updt_from ESI
--     Only when the gross per 8 hours is above 173 (hours = work + night + festival + STL).
--       1st fortnight : employee 0.75% and employer 3.25% of ESI gross, rounded up.
--       2nd fortnight : 0.75% of the month's ESI gross less the 1st fortnight's ESI; employer 0.
--     Workers flagged for ESI in the rate master.
-- =====================================================================================
INSERT INTO nbjcl.nbjcl_wages_data_collection
(
    eb_id,
    period_id,
    ESI_Amt,
    ESIC,
    updt_from
)
SELECT
    x.eb_id,
    @period_id,
    CASE WHEN DAY(@from_date) = 1 THEN CEILING(x.esi_gross * 0.75 / 100)
         ELSE CEILING(x.m_esi_gross * 0.75 / 100) - x.h_esi_amt END,
    CASE WHEN DAY(@from_date) = 1 THEN CEILING(x.esi_gross * 3.25 / 100) ELSE 0 END,
    'ESI'
FROM (
    SELECT
        s.eb_id,
        s.esi_gross,
        s.hrs,
        s.esi_gross + IFNULL(h.h_esi_gross, 0) AS m_esi_gross,
        s.wages_gross + IFNULL(h.h_wages, 0)   AS m_wages,
        s.hrs + IFNULL(h.h_hrs, 0)             AS m_hrs,
        IFNULL(h.h_esi_amt, 0)                 AS h_esi_amt
    FROM (
        SELECT dc.eb_id,
               SUM(dc.ESI_Gross)   AS esi_gross,
               SUM(dc.Wages_Gross) AS wages_gross,
               SUM(dc.working_hours + dc.ns_hrs + dc.fest_hours + dc.stl_days * 8) AS hrs
        FROM nbjcl.nbjcl_wages_data_collection dc
        WHERE dc.period_id = @period_id
        GROUP BY dc.eb_id
        HAVING SUM(dc.working_hours + dc.ot_hr + dc.fest_hours + dc.stl_days) > 0
    ) s
    INNER JOIN _dc_rate r
        ON r.eb_id = s.eb_id
    LEFT JOIN _dc_month h
        ON h.ECode = r.ECode
    WHERE r.esi = 'Y'
) x
WHERE (DAY(@from_date) = 1 AND x.hrs > 0 AND x.esi_gross / x.hrs * 8 > 173)
   OR (DAY(@from_date) <> 1 AND x.m_wages > 0 AND x.m_hrs > 0 AND x.m_esi_gross / x.m_hrs * 8 > 173);


-- =====================================================================================
-- 35. Professional tax  ->  PTax_BAmt, PTax_Amt                           updt_from PTAX
--     Slab on the month's wages gross from PayOMiscRate (All_Type PTAX, Location FACTORY, the
--     latest EffDate on or before the period start, as legacy: FRate..SRate -> FRate_HR).
--     The 2nd fortnight pays the slab less the 1st fortnight's tax.
--     Workers flagged for professional tax in the rate master.
-- =====================================================================================
INSERT INTO nbjcl.nbjcl_wages_data_collection
(
    eb_id,
    period_id,
    PTax_BAmt,
    PTax_Amt,
    updt_from
)
SELECT
    x.eb_id,
    @period_id,
    x.bamt,
    IFNULL((
        SELECT m.FRate_HR
        FROM nbjcl.PayOMiscRate m
        WHERE m.All_Type = 'PTAX' AND m.Location = 'FACTORY'
          AND x.bamt BETWEEN m.FRate AND m.SRate
          AND m.EffDate = (SELECT MAX(m2.EffDate) FROM nbjcl.PayOMiscRate m2
                           WHERE m2.All_Type = 'PTAX' AND m2.Location = 'FACTORY' AND m2.EffDate <= @from_date)
        LIMIT 1
    ), 0) - CASE WHEN DAY(@from_date) = 1 THEN 0 ELSE x.paid END,
    'PTAX'
FROM (
    SELECT
        s.eb_id,
        s.wages_gross + IFNULL(h.h_wages, 0) AS bamt,
        IFNULL(h.h_ptax_paid, 0)             AS paid
    FROM (
        SELECT dc.eb_id, SUM(dc.Wages_Gross) AS wages_gross
        FROM nbjcl.nbjcl_wages_data_collection dc
        WHERE dc.period_id = @period_id
        GROUP BY dc.eb_id
        HAVING SUM(dc.working_hours + dc.ot_hr + dc.fest_hours + dc.stl_days) > 0
    ) s
    INNER JOIN _dc_rate r
        ON r.eb_id = s.eb_id
    LEFT JOIN _dc_month h
        ON h.ECode = r.ECode
    WHERE r.ptax = 'Y'
) x;


-- =====================================================================================
-- 36. Labour welfare fund  ->  LWF_Amt                                     updt_from LWF
--     The amount entered for the run (@lwf_amt; only the 2nd fortnight of June and December).
-- =====================================================================================
INSERT INTO nbjcl.nbjcl_wages_data_collection
(
    eb_id,
    period_id,
    LWF_Amt,
    updt_from
)
SELECT
    s.eb_id,
    @period_id,
    @lwf_amt,
    'LWF'
FROM (
    SELECT dc.eb_id
    FROM nbjcl.nbjcl_wages_data_collection dc
    WHERE dc.period_id = @period_id
    GROUP BY dc.eb_id
    HAVING SUM(dc.working_hours + dc.ot_hr + dc.fest_hours + dc.stl_days) > 0
) s
WHERE IFNULL(@lwf_amt, 0) > 0;


-- =====================================================================================
-- 37. House rent deduction  ->  HRDeduction                                updt_from HRD
--     3.75% of HRA gross, rounded, for workers flagged for both HRA and HRD.
-- =====================================================================================
INSERT INTO nbjcl.nbjcl_wages_data_collection
(
    eb_id,
    period_id,
    HRDeduction,
    updt_from
)
SELECT
    s.eb_id,
    @period_id,
    ROUND(s.hra_gross * 3.75 / 100, 0),
    'HRD'
FROM (
    SELECT dc.eb_id, SUM(dc.HRA_Gross) AS hra_gross
    FROM nbjcl.nbjcl_wages_data_collection dc
    WHERE dc.period_id = @period_id
    GROUP BY dc.eb_id
) s
INNER JOIN _dc_rate r
    ON r.eb_id = s.eb_id
WHERE r.hra = 'Y'
  AND r.hrd = 'Y'
  AND s.hra_gross <> 0;


-- =====================================================================================
-- 38. Loan and advance recovery  ->  PFLoanCap, PFLoanInt_Ded, Advance_Ded
--                                                                      updt_from LOANDED
--     The instalments due (steps 10-12, _dc_loan_emi) are recovered only while the pay
--     still covers them, in this order:
--       PF loan (capital + interest) : gross - deductions so far - instalment > 0
--                                      (not for category 05)
--       advance                      : the same test after the PF loan is taken
--     Deductions so far = PF + ESI + professional tax + LWF + STL advance + electricity + HRD.
-- =====================================================================================
INSERT INTO nbjcl.nbjcl_wages_data_collection
(
    eb_id,
    period_id,
    PFLoanCap,
    PFLoanInt_Ded,
    Advance_Ded,
    updt_from
)
SELECT
    y.eb_id,
    @period_id,
    y.cap,
    y.intr,
    CASE WHEN (y.gross - y.ded - y.cap - y.intr) - y.inst_adv > 0 AND y.bal_adv > 0 THEN y.inst_adv ELSE 0 END,
    'LOANDED'
FROM (
    SELECT
        x.eb_id, x.gross, x.ded, x.inst_adv, x.bal_adv,
        CASE WHEN x.take_loan = 1 THEN x.inst_cap ELSE 0 END AS cap,
        CASE WHEN x.take_loan = 1 THEN x.inst_int ELSE 0 END AS intr
    FROM (
        SELECT
            s.eb_id, s.gross, s.ded,
            e.inst_cap, e.inst_int, e.inst_adv, e.bal_adv,
            CASE WHEN (s.gross - s.ded) - (e.inst_cap + e.inst_int) > 0
                  AND (e.bal_loan + e.bal_int) > 0
                  AND r.grp <> '05' THEN 1 ELSE 0 END AS take_loan
        FROM (
            SELECT dc.eb_id,
                   SUM(dc.Wages_Gross) AS gross,
                   SUM(dc.PFEmployee + dc.ESI_Amt + dc.PTax_Amt + dc.LWF_Amt + dc.STLAdv
                       + dc.Electricity + dc.HRDeduction) AS ded
            FROM nbjcl.nbjcl_wages_data_collection dc
            WHERE dc.period_id = @period_id
            GROUP BY dc.eb_id
            HAVING SUM(dc.working_hours + dc.ot_hr + dc.fest_hours + dc.stl_days) > 0
        ) s
        INNER JOIN _dc_rate r
            ON r.eb_id = s.eb_id
        INNER JOIN _dc_loan_emi e
            ON e.ECode = r.ECode
    ) x
) y
WHERE y.cap <> 0
   OR y.intr <> 0
   OR ((y.gross - y.ded - y.cap - y.intr) - y.inst_adv > 0 AND y.bal_adv > 0 AND y.inst_adv <> 0);


-- =====================================================================================
-- 39. Total deduction  ->  TotalDeduction                                updt_from TOTDED
--     PF + ESI + professional tax + LWF + STL advance + PF loan capital + PF loan interest
--     + special advance + advance + electricity + house rent deduction.
-- =====================================================================================
INSERT INTO nbjcl.nbjcl_wages_data_collection
(
    eb_id,
    period_id,
    TotalDeduction,
    updt_from
)
SELECT
    s.eb_id,
    @period_id,
    s.total_ded,
    'TOTDED'
FROM (
    SELECT dc.eb_id,
           SUM(dc.PFEmployee + dc.ESI_Amt + dc.PTax_Amt + dc.LWF_Amt + dc.STLAdv + dc.PFLoanCap
               + dc.PFLoanInt_Ded + dc.SplAdvance + dc.Advance_Ded + dc.Electricity + dc.HRDeduction) AS total_ded
    FROM nbjcl.nbjcl_wages_data_collection dc
    WHERE dc.period_id = @period_id
    GROUP BY dc.eb_id
    HAVING SUM(dc.working_hours + dc.ot_hr + dc.fest_hours + dc.stl_days) > 0
) s
WHERE s.total_ded <> 0;


-- =====================================================================================
-- 40. Net pay  ->  NetPay, ROff, NetPayable                              updt_from NETPAY
--     Net pay = wages gross - total deduction; net payable = net pay rounded to the rupee;
--     ROff = the rounding difference.
-- =====================================================================================
INSERT INTO nbjcl.nbjcl_wages_data_collection
(
    eb_id,
    period_id,
    NetPay,
    ROff,
    NetPayable,
    updt_from
)
SELECT
    s.eb_id,
    @period_id,
    s.net,
    ROUND(s.net, 0) - s.net,
    ROUND(s.net, 0),
    'NETPAY'
FROM (
    SELECT dc.eb_id,
           SUM(dc.Wages_Gross) - SUM(dc.TotalDeduction) AS net
    FROM nbjcl.nbjcl_wages_data_collection dc
    WHERE dc.period_id = @period_id
    GROUP BY dc.eb_id
    HAVING SUM(dc.working_hours + dc.ot_hr + dc.fest_hours + dc.stl_days) > 0
) s;


-- =====================================================================================
-- 41. Work days and year-to-date  ->  Work_Day, YTD_*, FPF_Pension, PF_Employer
--                                                                        updt_from YTD
--     Work days = (working hours + night hours) / 8. Each YTD figure is the previous
--     value (step 27) moved by this period, the way the migrated wage rows move:
--       YTD_Days + work days            YTD_BNSGrs + bonus gross
--       YTD_PFGross + pension + CoC     YTD_PFEmployee + PF
--       YTD_Pension + pension           YTD_FPF + CoC
--       YTD_LoanAmt - PF loan capital   YTD_IntAmt - PF loan interest
--     YTD_UTHWAdv, YTD_SplAdvance and YTD_Advance are carried forward unchanged.
--     FPF_Pension = YTD_Pension and PF_Employer = YTD_FPF, as on the migrated rows.
-- =====================================================================================
INSERT INTO nbjcl.nbjcl_wages_data_collection
(
    eb_id,
    period_id,
    Work_Day,
    YTD_Days,
    YTD_BNSGrs,
    YTD_PFGross,
    YTD_PFEmployee,
    YTD_Pension,
    YTD_FPF,
    YTD_LoanAmt,
    YTD_IntAmt,
    YTD_UTHWAdv,
    YTD_SplAdvance,
    YTD_Advance,
    FPF_Pension,
    PF_Employer,
    updt_from
)
SELECT
    s.eb_id,
    @period_id,
    s.work_day,
    s.p_days + ROUND(s.work_day, 2),
    s.p_bns + s.bns,
    s.p_pfgross + s.pension + s.coc,
    s.p_pfemp + s.pf_emp,
    s.p_pension + s.pension,
    s.p_fpf + s.coc,
    s.p_loan - s.loan_cap,
    s.p_int - s.loan_int,
    s.p_uthw,
    s.p_spl,
    s.p_adv,
    s.p_pension + s.pension,
    s.p_fpf + s.coc,
    'YTD'
FROM (
    SELECT dc.eb_id,
           ROUND(SUM(dc.working_hours + dc.ns_hrs) / 8, 3) AS work_day,
           SUM(dc.BNSGrs)              AS bns,
           SUM(dc.PFEmployee)          AS pf_emp,
           SUM(dc.Pension)             AS pension,
           SUM(dc.CoC)                 AS coc,
           SUM(dc.PFLoanCap)           AS loan_cap,
           SUM(dc.PFLoanInt_Ded)       AS loan_int,
           SUM(dc.Prev_YTD_Days)       AS p_days,
           SUM(dc.prev_YTD_BNSGrs)     AS p_bns,
           SUM(dc.prev_YTD_PFGross)    AS p_pfgross,
           SUM(dc.prev_YTD_PFEmployee) AS p_pfemp,
           SUM(dc.prev_YTD_Pension)    AS p_pension,
           SUM(dc.prev_YTD_FPF)        AS p_fpf,
           SUM(dc.prev_YTD_LoanAmt)    AS p_loan,
           SUM(dc.prev_YTD_IntAmt)     AS p_int,
           SUM(dc.prev_YTD_UTHWAdv)    AS p_uthw,
           SUM(dc.prev_YTD_SplAdvance) AS p_spl,
           SUM(dc.prev_YTD_Advance)    AS p_adv
    FROM nbjcl.nbjcl_wages_data_collection dc
    WHERE dc.period_id = @period_id
    GROUP BY dc.eb_id
    HAVING SUM(dc.working_hours + dc.ot_hr + dc.fest_hours + dc.stl_days) > 0
) s;


-- =====================================================================================
-- 42. Summary -> paywages
--     One paywages row (WAGES slip) per employee who has work, OT, festival or leave hours
--     in the period: every collected and calculated column summed across the step rows
--     (steps 1-41), plus the employee, bank and rate-flag columns from the HR masters and
--     the slip numbering (SrlNo overall, SlNo within the department).
--     Rows are tagged PCName = 'VOWERP PROCESS'. Only rows carrying that tag are deleted,
--     and nothing is inserted into a period that already holds other (migrated) wage rows.
-- =====================================================================================
DELETE FROM nbjcl.paywages
WHERE CompCode = 'NJB' AND Location = 'FACTORY' AND UnitCode = '01' AND EDate = @to_date
  AND PCode = (SELECT pp.code COLLATE utf8mb4_unicode_ci FROM nbjcl.pay_period pp WHERE pp.ID = @period_id)
  AND PCName = 'VOWERP PROCESS';

INSERT INTO nbjcl.paywages
(
    CompCode, Location, UnitCode, WYear, WMonth, WDay, PCode, EDate, DeptCode, OccpCode, TP, RecNo,
    OrgECode, ECode, EName, Grade, EGroup, SubGroup, OcpDptSft, C_P_Q, DoB, DoJ, Active, RestDay,
    SrlNo, SlNo, PaySlipType, Work_HR, Adj_HR, GP_HR, Holiday_HR, STL_HR, ESILeave_HR, NS_HR,
    OT_HR, Lost_HR, LayOff_HR, TotalDays, Work_Day, OFBasic, OFBasic_HR, FBasic_Rate, FBasic_Amt,
    OBasic, OBasic_HR, Basic_Rate, Basic_Amt, OVBasic, OVBasic_HR, VBasic_Rate, VBasic_Amt,
    ODA_All, ODA_Rate, ODA_HR, DA_Rate, DA_Amt, LostHR_Amt, LayOffHR_Amt, LSWgsRate, LSWgs_Amt,
    OADHOC_Rate, OADHOC_Amt, Holiday_Amt, STL_Amt, ONS_All, NS_Amt, OOT_All, OT_Amt,
    OBeamChange_All, BeamChange_Amt, PFEarnAdj, NPFEarnAdj, MiscEarn, AdjBasic, Increment,
    OIncentive, Incentive_Amt, OExtra_All, Extra_Amt, OOil_All, Oil_Amt, PF_Gross, HRA_Gross,
    OHRA_All, HRA_Rate, HRA_Amt, Spl_All_Amt, TA_Amt, Gas_All_Amt, Coal_All_Amt, Washing_Amt,
    Conv_Amt, Mobile_Amt, Tiffin_Amt, OAtndRate, Atten_Amt, ESI_Gross, PTax_Gross, Pension_Gross,
    Wages_Gross, LTAAmt, OPF, PFEmployee, OESI, ESI_Amt, OPTax, PTax_BAmt, PTax_Amt, ITaxAmt,
    TDSAmt, OLWF, LWF_Amt, STLAdv, OQuarter, OHRD_All, HRDeduction, UTHWAdv, PFLoanCap, PFLoanInt,
    SplAdvance, Advance, Electricity, LIC, LIP, OtherDeduction, TotalDeduction, NetPay, BF, ROff,
    NetPayable, CF, Pension, FPF_Pension, CoC, PF_Employer, ESIC, BNSGrs, YTD_Days, YTD_BNSGrs,
    YTD_PFGross, YTD_UTHWAdv, YTD_PFEmployee, YTD_Pension, YTD_FPF, YTD_LoanAmt, YTD_IntAmt,
    YTD_SplAdvance, YTD_Advance, BankName, Branch, IFSC, AccNo, BenificiaryName, JobNo,
    CreatedDate, UpdatedDate, PCName, UserID, UserName, period_id, branch_id
)
SELECT
    'NJB' AS CompCode,
    'FACTORY' AS Location,
    '01' AS UnitCode,
    YEAR(@from_date) AS WYear,
    MONTH(@from_date) AS WMonth,
    IF(DAY(@from_date) = 1, '01', '02') AS WDay,
    pp.code AS PCode,
    @to_date AS EDate,
    IFNULL(dp.dept_code, '') AS DeptCode,
    '' AS OccpCode,
    IF(LEFT(IFNULL(g.cata_desc, ''), 2) IN ('02', '03'), 'P', 'T') AS TP,
    IFNULL((SELECT pr.RecNo FROM nbjcl.paywages pr WHERE pr.ECode = o.emp_code COLLATE utf8mb4_unicode_ci AND pr.RecNo <> '' ORDER BY pr.EDate DESC LIMIT 1), '') AS RecNo,
    '' AS OrgECode,
    o.emp_code AS ECode,
    CONCAT_WS(' ', NULLIF(TRIM(pe.first_name), ''), NULLIF(TRIM(pe.middle_name), ''), NULLIF(TRIM(pe.last_name), '')) AS EName,
    'MILL-WORKMEN' AS Grade,
    IFNULL(g.cata_desc, '') AS EGroup,
    '' AS SubGroup,
    IFNULL(dp.ods, '') AS OcpDptSft,
    CONCAT(LEFT(IFNULL(g.cata_desc, ''), 2), '/ ', IF(IFNULL(r.quarter, 'N') = 'Y', 'H', ' ')) AS C_P_Q,
    IFNULL(pe.date_of_birth, '1900-01-01') AS DoB,
    IFNULL(o.date_of_join, '1900-01-01') AS DoJ,
    'Y' AS Active,
    IFNULL(o.off_day, '') AS RestDay,
    ROW_NUMBER() OVER (ORDER BY IFNULL(dp.dept_code, ''), IFNULL(dp.ods, ''), o.emp_code) AS SrlNo,
    ROW_NUMBER() OVER (PARTITION BY IFNULL(dp.dept_code, '') ORDER BY IFNULL(dp.ods, ''), o.emp_code) AS SlNo,
    'WAGES' AS PaySlipType,
    s.working_hours AS Work_HR,
    s.adj_hr AS Adj_HR,
    s.gp_hr AS GP_HR,
    s.fest_hours AS Holiday_HR,
    s.stl_days * 8 AS STL_HR,
    0 AS ESILeave_HR,
    s.ns_hrs AS NS_HR,
    s.ot_hr AS OT_HR,
    s.lost_hr AS Lost_HR,
    s.layoff_hr AS LayOff_HR,
    0 AS TotalDays,
    s.Work_Day AS Work_Day,
    s.OFBasic AS OFBasic,
    IF(s.OFBasic_HR > 0, s.OFBasic_HR, IFNULL(r.fbasic_hr, 208)) AS OFBasic_HR,
    s.FBasic_Rate AS FBasic_Rate,
    s.fbasicamt AS FBasic_Amt,
    0 AS OBasic,
    0 AS OBasic_HR,
    0 AS Basic_Rate,
    s.obasicamt AS Basic_Amt,
    'N' AS OVBasic,
    0 AS OVBasic_HR,
    IF(s.VBasic_Amt <> 0, 0.51, 0) AS VBasic_Rate,
    s.VBasic_Amt AS VBasic_Amt,
    IFNULL(r.da_all, 'N') AS ODA_All,
    s.DA_Rate AS ODA_Rate,
    IF(s.OFBasic_HR > 0, s.OFBasic_HR, IFNULL(r.fbasic_hr, 208)) AS ODA_HR,
    s.DA_Rate AS DA_Rate,
    s.daamount AS DA_Amt,
    s.LostHR_Amt AS LostHR_Amt,
    s.LayOffHR_Amt AS LayOffHR_Amt,
    0 AS LSWgsRate,
    s.LSWgs_Amt AS LSWgs_Amt,
    0 AS OADHOC_Rate,
    s.OADHOC_Amt AS OADHOC_Amt,
    s.Holiday_Amt AS Holiday_Amt,
    s.STL_Amt AS STL_Amt,
    'N' AS ONS_All,
    s.NS_Amt AS NS_Amt,
    'N' AS OOT_All,
    s.OT_Amt AS OT_Amt,
    'N' AS OBeamChange_All,
    s.BeamChange_Amt AS BeamChange_Amt,
    s.adj_pf + s.PFEarnAdj AS PFEarnAdj,
    s.adj_npf + s.NPFEarnAdj AS NPFEarnAdj,
    s.MiscEarn AS MiscEarn,
    s.AdjBasic AS AdjBasic,
    s.Increment AS Increment,
    IF(s.OIncentive = 'Y', 'Y', 'N') AS OIncentive,
    s.Incentive_Amt AS Incentive_Amt,
    'N' AS OExtra_All,
    s.Extra_Amt AS Extra_Amt,
    'N' AS OOil_All,
    s.Oil_Amt AS Oil_Amt,
    s.PF_Gross AS PF_Gross,
    s.HRA_Gross AS HRA_Gross,
    IFNULL(r.hra, 'N') AS OHRA_All,
    s.HRA_Rate AS HRA_Rate,
    s.HRA_Amt AS HRA_Amt,
    s.Spl_All_Amt AS Spl_All_Amt,
    s.TA_Amt AS TA_Amt,
    s.Gas_All_Amt AS Gas_All_Amt,
    s.Coal_All_Amt AS Coal_All_Amt,
    s.Washing_Amt AS Washing_Amt,
    s.Conv_Amt AS Conv_Amt,
    s.Mobile_Amt AS Mobile_Amt,
    s.Tiffin_Amt AS Tiffin_Amt,
    0 AS OAtndRate,
    s.Atten_Amt AS Atten_Amt,
    s.ESI_Gross AS ESI_Gross,
    s.PTax_Gross AS PTax_Gross,
    s.Pension_Gross AS Pension_Gross,
    s.Wages_Gross AS Wages_Gross,
    s.LTAAmt AS LTAAmt,
    IFNULL(r.pf, 'N') AS OPF,
    s.PFEmployee AS PFEmployee,
    IFNULL(r.esi, 'N') AS OESI,
    s.ESI_Amt AS ESI_Amt,
    IFNULL(r.ptax, 'N') AS OPTax,
    s.PTax_BAmt AS PTax_BAmt,
    s.PTax_Amt AS PTax_Amt,
    0 AS ITaxAmt,
    0 AS TDSAmt,
    'N' AS OLWF,
    s.LWF_Amt AS LWF_Amt,
    s.STLAdv AS STLAdv,
    IFNULL(r.quarter, 'N') AS OQuarter,
    IFNULL(r.hrd, 'N') AS OHRD_All,
    s.HRDeduction AS HRDeduction,
    0 AS UTHWAdv,
    s.PFLoanCap AS PFLoanCap,
    s.PFLoanInt_Ded AS PFLoanInt,
    s.SplAdvance AS SplAdvance,
    s.Advance_Ded AS Advance,
    s.Electricity AS Electricity,
    s.LIC AS LIC,
    s.LIP AS LIP,
    s.OtherDeduction AS OtherDeduction,
    s.TotalDeduction AS TotalDeduction,
    s.NetPay AS NetPay,
    0 AS BF,
    s.ROff AS ROff,
    s.NetPayable AS NetPayable,
    0 AS CF,
    s.Pension AS Pension,
    s.FPF_Pension AS FPF_Pension,
    s.CoC AS CoC,
    s.PF_Employer AS PF_Employer,
    s.ESIC AS ESIC,
    s.BNSGrs AS BNSGrs,
    s.YTD_Days AS YTD_Days,
    s.YTD_BNSGrs AS YTD_BNSGrs,
    s.YTD_PFGross AS YTD_PFGross,
    s.YTD_UTHWAdv AS YTD_UTHWAdv,
    s.YTD_PFEmployee AS YTD_PFEmployee,
    s.YTD_Pension AS YTD_Pension,
    s.YTD_FPF AS YTD_FPF,
    s.YTD_LoanAmt AS YTD_LoanAmt,
    s.YTD_IntAmt AS YTD_IntAmt,
    s.YTD_SplAdvance AS YTD_SplAdvance,
    s.YTD_Advance AS YTD_Advance,
    IFNULL(b.bank_name, '') AS BankName,
    IFNULL(b.bank_branch_name, '') AS Branch,
    IFNULL(b.ifsc_code, '') AS IFSC,
    IFNULL(b.bank_acc_no, '') AS AccNo,
    IFNULL(b.beneficiary_name, '') AS BenificiaryName,
    '' AS JobNo,
    NOW() AS CreatedDate,
    NOW() AS UpdatedDate,
    'VOWERP PROCESS' AS PCName,
    '' AS UserID,
    '' AS UserName,
    s.period_id AS period_id,
    @branch_id AS branch_id
FROM (
    SELECT
        nwdc.eb_id,
        nwdc.period_id,
        SUM(nwdc.working_hours) AS working_hours,
        SUM(nwdc.ns_hrs) AS ns_hrs,
        SUM(nwdc.fest_hours) AS fest_hours,
        SUM(nwdc.stl_days) AS stl_days,
        SUM(nwdc.gp_hr) AS gp_hr,
        SUM(nwdc.ot_hr) AS ot_hr,
        SUM(nwdc.lost_hr) AS lost_hr,
        SUM(nwdc.layoff_hr) AS layoff_hr,
        SUM(nwdc.adj_pf) AS adj_pf,
        SUM(nwdc.adj_npf) AS adj_npf,
        SUM(nwdc.adj_hr) AS adj_hr,
        SUM(nwdc.pfloan) AS pfloan,
        SUM(nwdc.pfloanint) AS pfloanint,
        SUM(nwdc.advance) AS advance,
        SUM(nwdc.fbasicamt) AS fbasicamt,
        SUM(nwdc.obasicamt) AS obasicamt,
        SUM(nwdc.VBasic_Amt) AS VBasic_Amt,
        SUM(nwdc.daamount) AS daamount,
        SUM(nwdc.LostHR_Amt) AS LostHR_Amt,
        SUM(nwdc.LayOffHR_Amt) AS LayOffHR_Amt,
        SUM(nwdc.LSWgs_Amt) AS LSWgs_Amt,
        SUM(nwdc.OADHOC_Amt) AS OADHOC_Amt,
        SUM(nwdc.Holiday_Amt) AS Holiday_Amt,
        SUM(nwdc.STL_Amt) AS STL_Amt,
        SUM(nwdc.NS_Amt) AS NS_Amt,
        SUM(nwdc.OT_Amt) AS OT_Amt,
        SUM(nwdc.BeamChange_Amt) AS BeamChange_Amt,
        SUM(nwdc.PFEarnAdj) AS PFEarnAdj,
        SUM(nwdc.NPFEarnAdj) AS NPFEarnAdj,
        SUM(nwdc.MiscEarn) AS MiscEarn,
        SUM(nwdc.AdjBasic) AS AdjBasic,
        SUM(nwdc.Increment) AS Increment,
        MAX(nwdc.OIncentive) AS OIncentive,
        SUM(nwdc.Incentive_Amt) AS Incentive_Amt,
        SUM(nwdc.Extra_Amt) AS Extra_Amt,
        SUM(nwdc.Oil_Amt) AS Oil_Amt,
        SUM(nwdc.Spl_All_Amt) AS Spl_All_Amt,
        SUM(nwdc.TA_Amt) AS TA_Amt,
        SUM(nwdc.Gas_All_Amt) AS Gas_All_Amt,
        SUM(nwdc.Coal_All_Amt) AS Coal_All_Amt,
        SUM(nwdc.Washing_Amt) AS Washing_Amt,
        SUM(nwdc.Conv_Amt) AS Conv_Amt,
        SUM(nwdc.Mobile_Amt) AS Mobile_Amt,
        SUM(nwdc.Tiffin_Amt) AS Tiffin_Amt,
        SUM(nwdc.Atten_Amt) AS Atten_Amt,
        SUM(nwdc.LTAAmt) AS LTAAmt,
        SUM(nwdc.LWF_Amt) AS LWF_Amt,
        SUM(nwdc.STLAdv) AS STLAdv,
        SUM(nwdc.PFLoanCap) AS PFLoanCap,
        SUM(nwdc.PFLoanInt_Ded) AS PFLoanInt_Ded,
        SUM(nwdc.SplAdvance) AS SplAdvance,
        SUM(nwdc.Advance_Ded) AS Advance_Ded,
        SUM(nwdc.Electricity) AS Electricity,
        SUM(nwdc.LIC) AS LIC,
        SUM(nwdc.LIP) AS LIP,
        SUM(nwdc.OtherDeduction) AS OtherDeduction,
        SUM(nwdc.ot_ns_hrs) AS ot_ns_hrs,
        SUM(nwdc.Prev_YTD_Days) AS Prev_YTD_Days,
        SUM(nwdc.prev_YTD_BNSGrs) AS prev_YTD_BNSGrs,
        SUM(nwdc.prev_YTD_PFGross) AS prev_YTD_PFGross,
        SUM(nwdc.prev_YTD_UTHWAdv) AS prev_YTD_UTHWAdv,
        SUM(nwdc.prev_YTD_PFEmployee) AS prev_YTD_PFEmployee,
        SUM(nwdc.prev_YTD_Pension) AS prev_YTD_Pension,
        SUM(nwdc.prev_YTD_FPF) AS prev_YTD_FPF,
        SUM(nwdc.prev_YTD_LoanAmt) AS prev_YTD_LoanAmt,
        SUM(nwdc.prev_YTD_IntAmt) AS prev_YTD_IntAmt,
        SUM(nwdc.prev_YTD_SplAdvance) AS prev_YTD_SplAdvance,
        SUM(nwdc.prev_YTD_Advance) AS prev_YTD_Advance,
        SUM(nwdc.OFBasic) AS OFBasic,
        SUM(nwdc.OFBasic_HR) AS OFBasic_HR,
        SUM(nwdc.FBasic_Rate) AS FBasic_Rate,
        SUM(nwdc.DA_Rate) AS DA_Rate,
        SUM(nwdc.PF_Gross) AS PF_Gross,
        SUM(nwdc.HRA_Gross) AS HRA_Gross,
        SUM(nwdc.HRA_Rate) AS HRA_Rate,
        SUM(nwdc.HRA_Amt) AS HRA_Amt,
        SUM(nwdc.ESI_Gross) AS ESI_Gross,
        SUM(nwdc.PTax_Gross) AS PTax_Gross,
        SUM(nwdc.Pension_Gross) AS Pension_Gross,
        SUM(nwdc.Wages_Gross) AS Wages_Gross,
        SUM(nwdc.PFEmployee) AS PFEmployee,
        SUM(nwdc.ESI_Amt) AS ESI_Amt,
        SUM(nwdc.PTax_BAmt) AS PTax_BAmt,
        SUM(nwdc.PTax_Amt) AS PTax_Amt,
        SUM(nwdc.HRDeduction) AS HRDeduction,
        SUM(nwdc.TotalDeduction) AS TotalDeduction,
        SUM(nwdc.NetPay) AS NetPay,
        SUM(nwdc.ROff) AS ROff,
        SUM(nwdc.NetPayable) AS NetPayable,
        SUM(nwdc.Pension) AS Pension,
        SUM(nwdc.CoC) AS CoC,
        SUM(nwdc.ESIC) AS ESIC,
        SUM(nwdc.BNSGrs) AS BNSGrs,
        SUM(nwdc.FPF_Pension) AS FPF_Pension,
        SUM(nwdc.PF_Employer) AS PF_Employer,
        SUM(nwdc.YTD_Days) AS YTD_Days,
        SUM(nwdc.YTD_BNSGrs) AS YTD_BNSGrs,
        SUM(nwdc.YTD_PFGross) AS YTD_PFGross,
        SUM(nwdc.YTD_PFEmployee) AS YTD_PFEmployee,
        SUM(nwdc.YTD_Pension) AS YTD_Pension,
        SUM(nwdc.YTD_FPF) AS YTD_FPF,
        SUM(nwdc.YTD_LoanAmt) AS YTD_LoanAmt,
        SUM(nwdc.YTD_IntAmt) AS YTD_IntAmt,
        SUM(nwdc.YTD_UTHWAdv) AS YTD_UTHWAdv,
        SUM(nwdc.YTD_SplAdvance) AS YTD_SplAdvance,
        SUM(nwdc.YTD_Advance) AS YTD_Advance,
        SUM(nwdc.Work_Day) AS Work_Day
    FROM nbjcl.nbjcl_wages_data_collection nwdc
    WHERE nwdc.period_id = @period_id
    GROUP BY
        nwdc.eb_id,
        nwdc.period_id
    HAVING SUM(nwdc.working_hours + nwdc.ot_hr + nwdc.fest_hours + nwdc.stl_days) > 0
) s
INNER JOIN nbjcl.pay_period pp
    ON pp.ID = s.period_id
INNER JOIN nbjcl.hrms_ed_official_details o
    ON o.eb_id = s.eb_id AND o.active = 1 AND o.branch_id = @branch_id
    AND IFNULL(o.emp_code, '') <> ''
LEFT JOIN nbjcl.hrms_ed_personal_details pe
    ON pe.eb_id = o.eb_id
LEFT JOIN nbjcl.category_mst g
    ON g.cata_id = o.catagory_id
LEFT JOIN nbjcl.hrms_ed_bank_details b
    ON b.eb_id = o.eb_id AND b.active = 1
LEFT JOIN (
    -- rate flags in force at the period end: latest effective row, active row wins a tie
    SELECT x.eb_id, x.fbasic_hr, x.da_all, x.hra, x.hrd, x.quarter, x.pf, x.esi, x.ptax
    FROM (
        SELECT wr.*,
               ROW_NUMBER() OVER (PARTITION BY wr.eb_id
                                  ORDER BY wr.effective_date DESC, wr.is_active DESC, wr.worker_rate_id DESC) AS rn
        FROM nbjcl.worker_rate_mst wr
        WHERE wr.effective_date <= @to_date
    ) x
    WHERE x.rn = 1
) r
    ON r.eb_id = o.eb_id
LEFT JOIN (
    -- department and shift the employee did regular duty in (slip code /dept/shift)
    SELECT da.eb_id, MAX(d.dept_code) AS dept_code,
           CONCAT('/', MAX(d.dept_code), '/', IFNULL(MAX(sp.spell_code), '')) AS ods
    FROM nbjcl.daily_attendance da
    INNER JOIN nbjcl.sub_dept_mst sd ON sd.sub_dept_id = da.worked_department_id
    INNER JOIN nbjcl.dept_mst d ON d.dept_id = sd.dept_id
    LEFT JOIN nbjcl.spell_mst sp ON sp.spell_id = da.spell_id
    WHERE da.branch_id = @branch_id
      AND da.attendance_date BETWEEN @from_date AND @to_date
      AND da.is_active = 1
      AND da.status_id = 3
      AND da.attendance_type = 'R'
    GROUP BY da.eb_id
) dp
    ON dp.eb_id = o.eb_id
WHERE NOT EXISTS (
    SELECT 1 FROM nbjcl.paywages m
    WHERE m.CompCode = 'NJB' AND m.Location = 'FACTORY' AND m.UnitCode = '01' AND m.EDate = @to_date
      AND m.PCode = pp.code COLLATE utf8mb4_unicode_ci
      AND m.PCName <> 'VOWERP PROCESS'
);


-- =====================================================================================
-- 43. Arrears of step 20a paid in this fortnight (only workers who got a wages row)
-- =====================================================================================
UPDATE nbjcl.PayM_AdjArrear a
INNER JOIN (
    SELECT DISTINCT w.ECode
    FROM nbjcl.paywages w
    WHERE w.CompCode = 'NJB' AND w.Location = 'FACTORY' AND w.UnitCode = '01' AND w.EDate = @to_date
) p
    ON p.ECode = a.ECode
SET a.Paid_FNEDate = @to_date,
    a.paid_period_id = @period_id,
    a.UpdatedDate = NOW()
WHERE a.branch_id = @branch_id
  AND a.Paid_FNEDate IN ('1900-01-01', @to_date);


-- =====================================================================================
-- Check: rows and totals per step
-- =====================================================================================
SELECT updt_from, COUNT(*) AS row_count, COUNT(DISTINCT eb_id) AS employees
FROM nbjcl.nbjcl_wages_data_collection
WHERE period_id = @period_id
GROUP BY updt_from
ORDER BY MIN(id);
