"""
NBJCL Reports > Salary — ports of the 12 legacy Smart-Eye Crystal reports of the "Salary" group
(report master ORPSMTEye, files Reports/SmartEyeReportMulti/*_NJB.rpt). See __init__.py for the spec.

Every report reads the legacy pay tables mirrored into the tenant DB under their own names: paywages
(PaySlipType 'STAFF SALARY' rows written by staffSalaryProcess.py, S-period EDate = month end), PaySalary,
PayMAtten, PayOEMP, PayLeaveDetails, PayCummOP, payoloan, payloanadjust, PayOMiscRate and
PayBonusProcessed_Staff. The Crystal SQL commands are translated one for one (the legacy quirks kept: the
dept summary has no company filter, LWF and P-Tax count workers too); the Crystal groups and footers are
laid out with _layout into display-ordered rows.

ponytail: legacy ADM1 (company address) is not mirrored — the page shows the title instead. The pay slips
(staff / clerk / bonus) come as one grid row per employee with the slip's fields as columns; the printable
slip layout is not ported.
"""
from datetime import date

from sqlalchemy.sql import text

from src.hrms.cashHands import amount_in_words
from src.hrms.nbjclAttendanceReports import _col, _layout, _num
from src.hrms.wagesSalaryProcess import UCI, _scope

CUT_OFF = date(2021, 3, 31)  # legacy @CutOffDate: cumulative PF / COC / advance history starts after it
MONTHS = ("", "JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE", "JULY", "AUGUST", "SEPTEMBER",
          "OCTOBER", "NOVEMBER", "DECEMBER")


def _rows(db, sql: str, **k) -> list[dict]:
    """Query rows as dicts with Decimals turned into floats and text stripped."""
    out = []
    for r in db.execute(text(sql), k):
        m = {}
        for key, v in r._mapping.items():
            if v is not None and type(v).__name__ == "Decimal":
                v = float(v)
            elif isinstance(v, str):
                v = v.strip()
            m[key] = v
        out.append(m)
    return out


def _params(b: int, f: date, t: date) -> dict:
    c, l = _scope(b)
    return {"c": c, "l": l, "f": f, "t": t, "cut": CUT_OFF, "fdate": t.replace(day=1)}


def _month(t: date) -> str:
    return f"{MONTHS[t.month]} - {t.year}"


def _num_cols(spec: list[tuple]) -> list[dict]:
    return [_num(f, h) for f, h in spec]


# ─── Pay slips ─────────────────────────────────────────────────────────────

CLERK_COLS = [
    ("pay_day", "Present"), ("cl_days", "CL Days"), ("payable_days", "Pay Days"), ("ot_hr", "OT HR"),
    ("ns_hr", "NS HR"), ("stl_days", "STL Days"), ("fes_hr", "Fes Hrs"), ("pl_days", "PL Days"),
    ("pl_bal", "PL Bal"), ("of_basic", "Basic Rt"), ("oda_rate", "DA Rt"), ("basic", "Basic"), ("da", "DA"),
    ("ns_amt", "NS Amt"), ("ot_amt", "OT Amt"), ("pf_adj", "PF Adj"), ("hra", "HRA Amt"), ("misc_earn", "Mis Er"),
    ("npf_adj", "NPF Adj"), ("gross", "Tot Earn"), ("pf", "PFC"), ("esi", "ESI"), ("ptax", "PTax"), ("lip", "LIP"),
    ("lwf", "LWF"), ("hrd", "HRD"), ("pf_loan", "PF Loan"), ("pf_int", "PFL Int"), ("other_ded", "Mis.Rec"),
    ("stl_adv", "STL Adv"), ("puja_adv", "Puj Adv"), ("advance", "Oth Adv"), ("total_ded", "Tot Ded."),
    ("net", "NetPayable"), ("ytd_pf_gross", "Cum-PFG"), ("ytd_bns", "Cum-B-E"), ("ytd_pfc", "Cum-PFC"),
    ("pf_loan_bal", "PFL-Bal"), ("pf_int_bal", "PFI-Bal"), ("ytd_days", "CB Day"), ("c_pnc", "C-PNC"),
    ("cum_cc", "Cum CC"),
]


def clerk_payslip(db, b, f, t, extra):
    """SalarySlip_Clerk2_NJB: monthly-paid CLERK / WATCH & WORD slips (PayOEMP Grade STAFF, SubGroup not STAFF)."""
    rows = _rows(db, f"""
        SELECT w.SlNo, w.Grade, w.SubGroup, w.DeptCode, w.ECode, w.EName, e.CardNo, e.ESINo, e.UAN,
               IFNULL(s.pay_day, 0) pay_day, IFNULL(s.ot_hr, 0) ot_hr, IFNULL(s.ns_hr, 0) ns_hr, 0 stl_days,
               IFNULL(s.fh, 0) * 8 fes_hr, IFNULL(s.pl, 0) pl_days, IFNULL(s.cl, 0) cl_days,
               IFNULL((SELECT MAX(ClPL) FROM PayLeaveDetails d WHERE d.EDate = :t AND d.ECode = w.ECode), 0) pl_bal,
               w.OFBasic of_basic, w.ODA_Rate oda_rate, w.FBasic_Amt basic, w.DA_Amt da, w.NS_Amt ns_amt,
               w.OT_Amt ot_amt, w.PFEarnAdj pf_adj, w.HRA_Amt hra, w.MiscEarn + w.Coal_All_Amt misc_earn,
               w.NPFEarnAdj npf_adj, w.Wages_Gross gross, w.PFEmployee pf, w.ESI_Amt esi, w.PTax_Amt ptax, w.LIP lip,
               w.LWF_Amt lwf, w.HRDeduction hrd, w.PFLoanCap pf_loan, w.PFLoanInt pf_int,
               w.Electricity + w.OtherDeduction other_ded, w.STLAdv stl_adv, 0 puja_adv, w.Advance advance,
               w.TotalDeduction total_ded, w.YTD_PFGross ytd_pf_gross, w.YTD_BNSGrs ytd_bns,
               w.YTD_PFEmployee ytd_pfc, w.YTD_LoanAmt pf_loan_bal, w.YTD_IntAmt pf_int_bal, w.YTD_Days ytd_days,
               w.FPF_Pension c_pnc, w.PF_Employer cum_cc, w.NetPayable net,
               e.PMode, e.BankName, e.Branch, e.IFSC, e.AccNo
        FROM paywages w
        JOIN PayOEMP e ON e.ECode {UCI} = w.ECode AND e.Grade = 'STAFF' AND e.SubGroup <> 'STAFF'
        LEFT JOIN (SELECT ECode, PCode, SUM(IF(EDate = :t, Present, 0)) pay_day, SUM(IF(EDate = :t, OTHrs, 0)) ot_hr,
                          SUM(IF(EDate = :t, NightHrs, 0)) ns_hr, SUM(FHDays) fh, SUM(PL) pl, SUM(CL) cl
                   FROM PaySalary GROUP BY ECode, PCode) s ON s.ECode = w.ECode AND s.PCode = w.PCode
        WHERE w.CompCode = :c AND w.Location = :l AND w.PCode LIKE 'S%' AND w.EDate = :t
        ORDER BY w.Grade, w.SubGroup, w.ECode
    """, **_params(b, f, t))
    last = {}
    for r in rows:  # slip no "n / last n of the Grade/SubGroup group"
        k = (r["Grade"], r["SubGroup"])
        last[k] = max(last.get(k, 0), int(r["SlNo"] or 0))
    for r in rows:
        r["grp"] = f"{r['Grade']}/{r['SubGroup']}"
        r["slip"] = f"{int(r['SlNo'] or 0)}/{last[(r['Grade'], r['SubGroup'])]}"
        r["payable_days"] = r["pay_day"] + r["cl_days"]
        r["month"] = _month(t)
    cols = [_col("grp", "Grade / SubGroup", width=170), _col("slip", "Slip No", width=80),
            _col("month", "Month", width=130), _col("DeptCode", "Dept", width=70), _col("ECode", "CN.No.", width=90),
            _col("EName", "E.Name", width=200), _col("CardNo", "Rec No", width=90), _col("ESINo", "ESI No", width=110),
            _col("UAN", "UAN", width=120), *_num_cols(CLERK_COLS), _col("PMode", "Pay Mode", width=90),
            _col("AccNo", "A/c No", width=140), _col("IFSC", "IFSC", width=110)]
    return cols, rows


STAFF_COLS = [
    ("WDays", "Working Days"), ("PayDay", "Payable Days"), ("AdjDays", "Adj. Days"), ("OT_HR", "OT Hrs."),
    ("PLDays", "PL Avail"), ("PLBal", "PL Balance"), ("OFBasic", "Basic Rate"), ("FBasic_Amt", "Basic"),
    ("Spl_All_Amt", "Special Allowance"), ("Gas_All_Amt", "Gas"), ("Washing_Amt", "Washing"),
    ("Conv_Amt", "Conveyance"), ("OT_Amt", "O. T."), ("HRA_Amt", "HRA Amt"), ("PFEarnAdj", "PF Adjustment"),
    ("MiscEarn", "Misc Earning"), ("LTAAmt", "L.T.A."), ("Wages_Gross", "Total Earning"),
    ("PFEmployee", "PF Contribution"), ("ESI_Amt", "ESI Contribution"), ("PTax_Amt", "P.Tax"), ("LIP", "L.I.P."),
    ("ITaxAmt", "I.Tax Amt"), ("Electricity", "Electric"), ("Advance", "Advance"), ("SplAdvance", "Special Advance"),
    ("PFLoanCap", "PF Loan"), ("PFLoanInt", "PF Loan Int."), ("OtherDeduction", "Misc Deduction"),
    ("TotalDeduction", "Total Deduction"), ("NetPayable", "NetPayable"), ("PFLoanBal", "PF Loan Bal"),
    ("YTD_Days", "Cum - Days"), ("YTD_BNSGrs", "Cum-Bon-Gross"), ("PFIntBal", "PF Int.Bal."),
    ("SalAdvBal", "Salary Adv.Bal."), ("CumPFC", "Cum-PFC"), ("CumCOC", "Cum-COC"), ("AdvBal", "Spl.Adv.Bal."),
]


def staff_payslip(db, b, f, t, extra):
    """SalarySlip_Staff_NJB: monthly-paid STAFF salary slips (PayOEMP Grade STAFF, SubGroup STAFF)."""
    rows = _rows(db, f"""
        SELECT w.SlNo, e.Grade, e.SubGroup, e.DeptName, e.Designation, e.DoB, e.DoJ, e.UAN, e.PFNo, e.ESINo,
               e.BankName, e.IFSC, e.AccNo, e.PMode, e.CardNo, w.ECode, w.EName,
               IFNULL((SELECT SUM(PresentDay) FROM PayMAtten a WHERE a.PCode = w.PCode AND a.ECode = w.ECode), 0) WDays,
               w.Work_Day PayDay, w.OT_HR,
               IFNULL((SELECT SUM(AdjDay) FROM PayMAtten a WHERE a.PCode = w.PCode AND a.ECode = w.ECode), 0) AdjDays,
               IFNULL((SELECT SUM(PLDay) FROM PayMAtten a WHERE a.PCode = w.PCode AND a.ECode = w.ECode), 0) PLDays,
               IFNULL((SELECT SUM(ClPL) FROM PayLeaveDetails d WHERE d.ECode = w.ECode AND d.EDate = :t), 0) PLBal,
               w.OFBasic, w.FBasic_Amt, w.Spl_All_Amt, w.Gas_All_Amt, w.Washing_Amt, w.Conv_Amt, w.OT_Amt,
               w.HRA_Amt, w.PFEarnAdj, w.NPFEarnAdj + w.MiscEarn + w.Mobile_Amt + w.Tiffin_Amt MiscEarn, w.LTAAmt,
               w.Wages_Gross, w.PFEmployee, w.ESI_Amt, w.PTax_Amt, w.LIP, w.ITaxAmt, w.Electricity, w.Advance,
               w.SplAdvance, w.PFLoanCap, w.PFLoanInt, w.OtherDeduction, w.TotalDeduction, w.NetPayable,
               w.YTD_Days, w.YTD_BNSGrs, w.YTD_LoanAmt PFLoanBal, w.YTD_IntAmt PFIntBal, 0 SalAdvBal,
               IFNULL((SELECT SUM(PFCBalance) FROM PayCummOP o WHERE o.ECode = w.ECode), 0)
                 + IFNULL((SELECT SUM(PFEmployee) FROM paywages h WHERE h.EDate > :cut AND h.EDate < :fdate
                           AND h.ECode = w.ECode), 0) + w.PFEmployee CumPFC,
               IFNULL((SELECT SUM(COCBalance) FROM PayCummOP o WHERE o.ECode = w.ECode), 0)
                 + IFNULL((SELECT SUM(COC) FROM paywages h WHERE h.EDate > :cut AND h.EDate < :fdate
                           AND h.ECode = w.ECode), 0) + w.COC CumCOC,
               IFNULL((SELECT SUM(LoanAmt) FROM payoloan n WHERE n.DocStatus = 'OPEN' AND n.LoanType = 'ADVANCE'
                       AND n.ECode = w.ECode AND n.LoanDate <= :t), 0)
                 - IFNULL((SELECT SUM(RepayCapital) FROM payloanadjust j WHERE j.LoanType = 'ADVANCE'
                           AND j.ToDate <= :t AND j.ECode = w.ECode), 0)
                 - IFNULL((SELECT SUM(Advance) FROM paywages h WHERE h.ECode = w.ECode AND h.EDate <= :t), 0) AdvBal
        FROM paywages w
        JOIN PayOEMP e ON e.ECode {UCI} = w.ECode AND e.Grade = 'STAFF' AND e.SubGroup = 'STAFF'
        WHERE w.CompCode = :c AND w.Location = :l AND w.PCode LIKE 'S%' AND w.EDate = :t
        ORDER BY w.Grade, w.SubGroup, w.ECode
    """, **_params(b, f, t))
    for r in rows:
        r["slip"] = str(int(r["SlNo"] or 0))
        r["month"] = _month(t)
        r["words"] = amount_in_words(r["NetPayable"])
        r["DoJ"] = r["DoJ"].strftime("%d/%m/%Y") if r["DoJ"] else ""
    cols = [_col("slip", "Slip No", width=80), _col("month", "Month", width=130), _col("ECode", "Emp Code", width=90),
            _col("EName", "Name", width=200), _col("DeptName", "Department", width=170),
            _col("Designation", "Designation", width=170), _col("DoJ", "Date of Joining", width=110),
            _col("PFNo", "P. F. No.", width=110), _col("UAN", "UAN No.", width=120), _col("ESINo", "ESI No.", width=110),
            *_num_cols(STAFF_COLS), _col("words", "Amount in words", width=320), _col("PMode", "PMode", width=80),
            _col("AccNo", "Bank A/c No.", width=140), _col("IFSC", "IFSC Code", width=110)]
    return cols, rows


def bonus_payslip(db, b, f, t, extra):
    """BonusSlip_Staff_NJB: the staff bonus processed for the year (PayBonusProcessed_Staff, PB = 'YYYY - YYYY')."""
    pb = f"{f.year} - {t.year}"  # legacy: From year - To year, so pick 01/04 .. 31/03 of the bonus year
    rows = _rows(db, """
        SELECT RecNo, ECode, EName, SubGroup, TotalDays, TotalPFG, TotalBnsG, BNSAmt, PayableBNSAmt, BNSBlocked,
               AccNo, IFSC, RptName
        FROM PayBonusProcessed_Staff WHERE PB = :pb ORDER BY SubGroup, ECode
    """, pb=pb)
    cols = [_col("RptName", "Slip", width=300), _col("RecNo", "RecNo", width=90), _col("ECode", "ECode", width=90),
            _col("EName", "Name", width=200), _col("SubGroup", "SubGroup", width=120), _num("TotalDays", "Days"),
            _num("TotalPFG", "PF - Gross", 110), _num("TotalBnsG", "Elg - Gross", 110), _num("BNSAmt", "BNSAmt", 100),
            _num("PayableBNSAmt", "Nett", 100), _col("BNSBlocked", "Blocked", width=80),
            _col("AccNo", "Bank A/c No", width=140), _col("IFSC", "IFSC", width=110)]
    return cols, rows


# ─── Statements ────────────────────────────────────────────────────────────


def leave_balance(db, b, f, t, extra):
    """LeaveBalStatement_NJB: staff CL / PL closing balance as on the To date."""
    det = _rows(db, f"""
        SELECT e.Grade, e.SubGroup, e.ECode, e.EName, d.ClCL, d.ClPL
        FROM PayOEMP e JOIN PayLeaveDetails d ON d.ECode = e.ECode {UCI}
        WHERE e.CompCode = :c AND e.Location = :l AND (d.ClCL > 0 OR d.ClPL > 0) AND e.Grade = 'STAFF'
          AND d.EDate = :t
        ORDER BY e.Grade, e.SubGroup, e.ECode
    """, **_params(b, f, t))
    cols = [_col("grp", "Grade / SubGroup", width=170), _col("ECode", "ECode", width=90), _col("EName", "Name", width=240),
            _num("ClCL", "CL Days"), _num("ClPL", "PL Days")]
    return cols, _layout(det, [lambda d: f"{d['Grade']} / {d['SubGroup']}"], [], "grp", "ECode",
                         grand=False, footers=False)


def _one_deduction(db, b, f, t, col: str, header: str, with_dept: bool):
    det = _rows(db, f"""
        SELECT e.Grade, e.SubGroup, e.DeptCode, e.CardNo, e.ECode, e.EName, w.{col} amt
        FROM PayOEMP e JOIN paywages w ON w.ECode = e.ECode {UCI}
        WHERE e.CompCode = :c AND e.Location = :l AND w.{col} > 0 AND e.Grade = 'STAFF' AND w.EDate = :t
        ORDER BY e.Grade, e.SubGroup, {'e.DeptCode, ' if with_dept else ''}e.ECode
    """, **_params(b, f, t))
    cols = [_col("grp", "Grade / SubGroup", width=170)]
    if with_dept:
        cols += [_col("DeptCode", "Dept", width=70)]
    cols += [_col("ECode", "ECode", width=90)]
    if with_dept:
        cols += [_col("CardNo", "Rec.No", width=90)]
    cols += [_col("EName", "Name", width=240), _num("amt", header, 120)]
    return cols, _layout(det, [lambda d: f"{d['Grade']} / {d['SubGroup']}"], ["amt"], "grp", "ECode")


def income_tax(db, b, f, t, extra):
    """IncomeTaxStatement_NJB: staff income tax deducted in the month."""
    return _one_deduction(db, b, f, t, "ITaxAmt", "Income Tax Amt", with_dept=False)


def lic_recovery(db, b, f, t, extra):
    """LIPRecoStatement_NJB: staff LIP (LIC premium) recovered in the month."""
    return _one_deduction(db, b, f, t, "LIP", "LIP Amt", with_dept=True)


LWF_EMPLOYER_RATE = 15  # Crystal @LWFAmt2 = employee count * 15 (the command's @Emp*5 is not printed)


def lwf_form_d(db, b, f, t, extra):
    """LWFStatement_FormD_NJB: everyone with a labour-welfare-fund deduction on the To date (workers too), then
    the Form-D figures: employees' contribution, employer's (count x 15) and the grand total."""
    det = _rows(db, f"""
        SELECT e.DeptCode, e.ECode, e.EName, w.LWF_Amt lwf
        FROM PayOEMP e JOIN paywages w ON w.ECode = e.ECode {UCI}
        WHERE e.CompCode = :c AND e.Location = :l AND w.LWF_Amt > 0 AND w.EDate = :t
        ORDER BY e.Grade, e.SubGroup, e.DeptCode, e.ECode
    """, **_params(b, f, t))
    emp = sum(d["lwf"] or 0 for d in det)
    n = len(det)
    cols = [_col("DeptCode", "Dept", width=90), _col("ECode", "ECode", width=90), _col("EName", "Name", width=240),
            _num("lwf", "Amount", 110)]
    foot = [{"DeptCode": "Total", "EName": f"Employees' contribution ({n} employees)", "lwf": emp},
            {"DeptCode": "Total", "EName": f"Employer's contribution ({n} x {LWF_EMPLOYER_RATE})",
             "lwf": n * LWF_EMPLOYER_RATE},
            {"DeptCode": "Grand Total", "EName": "Employees' + employer's contribution",
             "lwf": emp + n * LWF_EMPLOYER_RATE}] if det else []
    return cols, det + foot


PF_SPLIT = ("""CASE WHEN w.PFEmployee > 0 THEN 1 ELSE 0 END pf_member, CASE WHEN w.Pension > 0 THEN 1 ELSE 0 END pn_member,
               IF(w.PFEmployee > 0 AND w.PFEmployee = w.COC, w.PF_Gross, 0) pf_amt1,
               IF(w.PFEmployee > 0 AND w.PFEmployee = w.COC, w.PFEmployee, 0) pfc1,
               IF(w.PFEmployee > 0 AND w.PFEmployee = w.COC, w.Pension, 0) pnc1,
               IF(w.PFEmployee > 0 AND w.PFEmployee = w.COC, w.COC, 0) coc1,
               IF(w.PFEmployee > 0 AND w.PFEmployee <> w.COC, w.PF_Gross, 0) pf_amt2,
               IF(w.PFEmployee > 0 AND w.PFEmployee <> w.COC, w.PFEmployee, 0) pfc2,
               IF(w.PFEmployee > 0 AND w.PFEmployee <> w.COC, w.Pension, 0) pnc2,
               IF(w.PFEmployee > 0 AND w.PFEmployee <> w.COC, w.COC, 0) coc2""")
ADV_BAL = """IFNULL((SELECT SUM(LoanAmt) FROM payoloan n WHERE n.LoanType = 'ADVANCE' AND n.LoanDate > :cut
                     AND n.LoanDate <= :t AND n.ECode = w.ECode), 0)
             - IFNULL((SELECT SUM(Advance) FROM paywages h WHERE h.EDate > :cut AND h.EDate <= :t
                       AND h.ECode = w.ECode), 0)"""
PF_COLS = [("pf_gross", "PF Gross"), ("pfc", "PFC"), ("c_pfc", "C-PFC"), ("pension", "PNC"), ("c_pnc", "C-PNC"),
           ("coc", "COC"), ("c_coc", "C-COC"), ("advance", "Advance"), ("adv_bal", "Adv.Bal"), ("set_adv", "SetAdv"),
           ("set_bal", "SetBal"), ("stl_hr", "STL_HR"), ("pf_member", "PF Members"), ("pn_member", "Pen Members"),
           ("pf_amt1", "PF-Gross PF Member"), ("pfc1", "PFC 1"), ("pnc1", "PNC 1"), ("coc1", "COC 1"),
           ("pf_amt2", "PF-Gross FP Member"), ("pfc2", "PFC 2"), ("pnc2", "PNC 2"), ("coc2", "COC 2")]


def _pf_statement(det: list[dict], level):
    cols = [_col("grp", "Grade / SubGroup", width=220), _col("PFNo", "PFNo", width=120),
            _col("CardNo", "Rec.No", width=90), _col("ECode", "ECode", width=90), _col("EName", "Name", width=220),
            *_num_cols(PF_COLS), _col("nra_date", "NRADate", width=90)]
    return cols, _layout(det, [level], [f for f, _ in PF_COLS], "grp", "PFNo")


def pfc_adv(db, b, f, t, extra):
    """PFC_Adv_Statement_NJB: per staff member PF / pension / CoC contribution of the month with cumulative
    balances, and advance recovered / outstanding, by Grade / SubGroup / EGroup."""
    det = _rows(db, f"""
        SELECT e.Grade, e.SubGroup, e.EGroup, e.ECode, e.EName, e.PFNo, e.CardNo, w.PF_Gross pf_gross,
               w.PFEmployee pfc,
               IFNULL((SELECT SUM(PFCBalance) FROM PayCummOP o WHERE o.ECode = w.ECode), 0)
                 + IFNULL((SELECT SUM(PFEmployee) FROM paywages h WHERE h.EDate > :cut AND h.EDate < :t
                           AND h.ECode = w.ECode), 0) + w.PFEmployee c_pfc,
               w.Pension pension, w.FPF_Pension c_pnc, w.COC coc, w.PF_Employer c_coc, w.Advance advance,
               {ADV_BAL} adv_bal, 0 set_adv, 0 set_bal, w.STL_HR stl_hr, '' nra_date, {PF_SPLIT}
        FROM paywages w JOIN PayOEMP e ON e.ECode {UCI} = w.ECode
        WHERE w.PCode LIKE 'S%' AND w.EDate = :t
        ORDER BY e.Grade, e.SubGroup, e.EGroup, e.ECode
    """, **_params(b, f, t))
    return _pf_statement(det, lambda d: f"{d['Grade']} / {d['SubGroup']} / {d['EGroup']}")


def pfc_loan_bal(db, b, f, t, extra):
    """PFC_LoanBal_Statement_NJB: the same with cumulative PF / CoC net of open non-refundable PF loans."""
    det = _rows(db, f"""
        SELECT e.Grade, e.SubGroup, e.ECode, e.EName, e.PFNo, e.CardNo, w.PF_Gross pf_gross, w.PFEmployee pfc,
               IFNULL((SELECT SUM(PFCBalance) FROM PayCummOP o WHERE o.ECode = w.ECode), 0)
                 + IFNULL((SELECT SUM(PFEmployee) FROM paywages h WHERE h.EDate > :cut AND h.EDate <= :t
                           AND h.ECode = w.ECode), 0)
                 - IFNULL((SELECT SUM(EmployeeCont) FROM payoloan n WHERE n.DocStatus = 'OPEN' AND n.LoanType = 'NRLOAN'
                           AND n.LoanDate <= :t AND n.ECode = w.ECode), 0) c_pfc,
               w.COC coc,
               IFNULL((SELECT SUM(COCBalance) FROM PayCummOP o WHERE o.ECode = w.ECode), 0)
                 + IFNULL((SELECT SUM(COC) FROM paywages h WHERE h.EDate > :cut AND h.EDate <= :t
                           AND h.ECode = w.ECode), 0)
                 - IFNULL((SELECT SUM(EmployerCont) FROM payoloan n WHERE n.DocStatus = 'OPEN' AND n.LoanType = 'NRLOAN'
                           AND n.LoanDate <= :t AND n.ECode = w.ECode), 0) c_coc,
               w.Pension pension, w.FPF_Pension c_pnc, w.Advance advance, {ADV_BAL} adv_bal, 0 set_adv, 0 set_bal,
               w.STL_HR stl_hr, '' nra_date, {PF_SPLIT}
        FROM paywages w JOIN PayOEMP e ON e.ECode {UCI} = w.ECode AND e.Grade = 'STAFF'
        WHERE LEFT(w.PCode, 1) = 'S' AND w.EDate = :t
        ORDER BY e.Grade, e.SubGroup, e.EGroup, e.ECode
    """, **_params(b, f, t))
    return _pf_statement(det, lambda d: f"{d['Grade']} / {d['SubGroup']}")


# ─── Summaries ─────────────────────────────────────────────────────────────

# (field, heading, per-employee expression) in the legacy print order: attendance, earnings, deductions
SUMMARY = [
    ("hands", "No. of Employee", "1"), ("wday", "Working Day", "IFNULL(a.wday, 0)"),
    ("adj_day", "Adj. Day", "IFNULL(a.adj, 0)"), ("holiday", "Holiday", "IFNULL(a.hol, 0)"),
    ("cl_day", "CL Day", "IFNULL(a.cl, 0)"), ("pl_day", "PL Day", "IFNULL(a.pl, 0)"), ("sl_day", "SL Day", "IFNULL(a.sl, 0)"),
    ("stl_days", "STL Days", "0"), ("ot_hr", "OT HR", "w.OT_HR"), ("ns_hr", "NS HR", "w.NS_HR"),
    ("pf_gross", "PF Gross", "w.PF_Gross"),
    ("basic", "Basic", "w.FBasic_Amt"), ("da", "DA", "w.DA_Amt"), ("holiday_amt", "Holiday Amt", "w.Holiday_Amt"),
    ("ns_amt", "NS Amt", "w.NS_Amt"), ("stl_amt", "STL Amt", "w.STL_Amt"), ("hra", "HRA Amt", "w.HRA_Amt"),
    ("ot_amt", "OT Amt", "w.OT_Amt"), ("pf_adj", "Adj. PF", "w.PFEarnAdj"), ("npf_adj", "Adj. NPF", "w.NPFEarnAdj"),
    ("spl", "SPL Allowance", "w.Spl_All_Amt"), ("incentive", "Incentive Amt", "w.Incentive_Amt"),
    ("misc_earn", "Misc Earning", "w.MiscEarn"), ("oth_all", "Other Allowance", "0"),
    ("fuel", "Fuel & Gas", "w.Coal_All_Amt + w.Gas_All_Amt"), ("mobile", "Tele. Allowance", "w.Mobile_Amt"),
    ("tiffin", "Tiffine Allowance", "w.Tiffin_Amt"), ("med", "Med. Allowance", "0"), ("lta", "LTA", "w.LTAAmt"),
    ("washing", "Dress Allowance", "w.Washing_Amt"), ("adhoc", "Adhoc Allowance", "0"), ("conv", "Conveyance", "w.Conv_Amt"),
    ("gross", "Total Earnings", "w.Wages_Gross"),
    ("pf", "PF", "w.PFEmployee"), ("esi", "ESI", "w.ESI_Amt"), ("ptax", "P-Tax", "w.PTax_Amt"), ("lwf", "LWF", "w.LWF_Amt"),
    ("pf_loan", "PF Loan Recovery", "w.PFLoanCap"), ("pf_int", "PF Int. Recovery", "w.PFLoanInt"),
    ("stl_adv", "STL Adv", "w.STLAdv"), ("puja_adv", "Puja Adv", "0"), ("advance", "Advance", "w.Advance"),
    ("spl_adv", "SplAdvance", "w.SplAdvance"), ("lic", "LIC", "w.LIC"), ("lip", "LIP", "w.LIP"), ("mess", "Mess", "0"),
    ("itax", "Income Tax", "w.ITaxAmt"), ("tds", "TDS Amt", "w.TDSAmt"), ("elec", "Electricity", "w.Electricity"),
    ("other_ded", "OtherDeduction", "w.OtherDeduction"), ("total_ded", "Total Deductions", "w.TotalDeduction"),
    ("roff", "ROff", "w.ROff"), ("net", "NetPayable", "w.NetPayable"),
]
# grand summary only: PF / pension / ESI member counts, gross and contribution
MEMBERS = [
    ("pf_members", "No. of PF Members", "IF(w.PFEmployee > 0, 1, 0)"),
    ("pf_member_gross", "PF Gross (members)", "IF(w.PFEmployee > 0, w.PF_Gross, 0)"),
    ("pf_cont", "PF Cont.", "IF(w.PFEmployee > 0, w.PFEmployee, 0)"),
    ("pn_members", "No. of Pen Members", "IF(w.Pension > 0, 1, 0)"),
    ("pn_gross", "Pen Gross", "IF(w.Pension > 0, w.Pension_Gross, 0)"),
    ("pn_cont", "Pen Cont.", "IF(w.Pension > 0, w.Pension, 0)"),
    ("coc_cont", "COC Cont.", "IF(w.PFEmployee > 0, w.COC, 0)"),
    ("esi_members", "No. of ESI Members", "IF(w.ESI_Amt > 0, 1, 0)"),
    ("esi_gross", "ESI Gross", "IF(w.ESI_Amt > 0, w.ESI_Gross, 0)"),
    ("esi_cont", "ESI Cont.", "w.ESI_Amt"),
]
ATTEN = """LEFT JOIN (SELECT ECode, EDate, SUM(PresentDay) wday, SUM(AdjDay) adj, SUM(Holiday) hol, SUM(CLDay) cl,
                             SUM(PLDay) pl, SUM(SLDay) sl FROM PayMAtten WHERE EDate = :t GROUP BY ECode, EDate) a
                  ON a.ECode = w.ECode AND a.EDate = w.EDate"""


def dept_summary(db, b, f, t, extra):
    """SalarySummaryDept_NJB: active staff pay totals per department, sub-group and PF / NPF.
    Legacy has no company / location filter here: every PayOEMP STAFF row with a pay row on the To date."""
    sums = ", ".join(f"SUM({e}) {k}" for k, _, e in SUMMARY)
    det = _rows(db, f"""
        SELECT e.DeptCode, e.SubGroup, w.OPF,
               IFNULL((SELECT MAX(DeptName) FROM ODPT d WHERE d.DeptCode = e.DeptCode {UCI}), '') DeptName, {sums}
        FROM PayOEMP e JOIN paywages w ON w.ECode = e.ECode {UCI} {ATTEN}
        WHERE e.Active = 'Y' AND e.Grade = 'STAFF' AND w.EDate = :t
        GROUP BY e.DeptCode, e.SubGroup, w.OPF, w.WYear, w.WMonth
        ORDER BY e.DeptCode, e.SubGroup, w.OPF
    """, **_params(b, f, t))
    for d in det:
        d["dept"] = f"{d['DeptCode']} - {d['DeptName']}"
        d["sub"] = f"{d['SubGroup']} [ {'PF' if d['OPF'] == 'Y' else 'NPF'} ]"
    cols = [_col("dept", "Department", width=240), _col("sub", "SubGroup", width=170),
            *[_num(k, h, 110) for k, h, _ in SUMMARY]]
    return cols, _layout(det, [], [k for k, _, _ in SUMMARY], "dept", "sub")


def grand_summary(db, b, f, t, extra):
    """SalarySummaryGrand_NJB: staff pay totals per sub-group and PF / NPF with sub-group and grand totals,
    plus PF / pension / ESI members, gross and contribution."""
    # unlike the dept summary, coal + gas are folded into Misc Earning here and Fuel & Gas stays 0
    grand = {"misc_earn": "w.MiscEarn + w.Coal_All_Amt + w.Gas_All_Amt", "fuel": "0"}
    spec = [(k, h, grand.get(k, e)) for k, h, e in SUMMARY] + MEMBERS
    sums = ", ".join(f"SUM({e}) {k}" for k, _, e in spec)
    det = _rows(db, f"""
        SELECT e.SubGroup, w.OPF, {sums}
        FROM PayOEMP e JOIN paywages w ON w.ECode = e.ECode {UCI} {ATTEN}
        WHERE e.Grade = 'STAFF' AND w.EDate = :t AND w.Location = :l
        GROUP BY e.SubGroup, w.OPF, w.WYear, w.WMonth
        ORDER BY e.SubGroup, w.OPF
    """, **_params(b, f, t))
    for d in det:
        d["sub"] = f"{d['SubGroup']} [ {'PF' if d['OPF'] == 'Y' else 'NPF'} ]"
    cols = [_col("grp", "SubGroup", width=200), _col("sub", "SubGroup / PF", width=170),
            *[_num(k, h, 110) for k, h, _ in spec]]
    return cols, _layout(det, [lambda d: d["SubGroup"]], [k for k, _, _ in spec], "grp", "sub")


def ptax_statement(db, b, f, t, extra):
    """PTaxRegister_NJB (proc RPT_PTaxStatement): hands and P-Tax per slab of the month — mill workers, monthly
    (CLERK / WATCH & WORD), officers (STAFF) and head office. A person counts in the slab whose rate equals
    their P-Tax of the month (both fortnights summed for workers)."""
    k = _params(b, f, t)
    slabs = _rows(db, """
        SELECT DISTINCT FRate r1, SRate r2, FRate_HR rate FROM PayOMiscRate o
        WHERE CompCode = :c AND All_Type = 'PTAX'
          AND EffDate >= (SELECT MAX(EffDate) FROM PayOMiscRate WHERE CompCode = o.CompCode AND All_Type = 'PTAX'
                          AND EffDate <= :t)
        ORDER BY FRate_HR, FRate
    """, **k)
    per_emp = _rows(db, """
        SELECT CASE WHEN Location = :l AND Grade = 'MILL-WORKMEN' THEN 'worker'
                    WHEN Location = :l AND Grade = 'STAFF' AND SubGroup IN ('CLERK', 'WATCH & WORD') THEN 'monthly'
                    WHEN Location = :l AND Grade = 'STAFF' AND SubGroup = 'STAFF' THEN 'officer'
                    WHEN Location = 'HEAD OFFICE' AND Grade = 'STAFF' THEN 'ho' END cat,
               ECode, SUM(PTax_Amt) ptax
        FROM paywages WHERE WYear = YEAR(:t) AND WMonth = MONTH(:t)
        GROUP BY cat, ECode HAVING cat IS NOT NULL
    """, **k)
    hands: dict = {}
    for r in per_emp:
        key = (r["cat"], round(r["ptax"] or 0, 2))
        h = hands.setdefault(key, [0, 0.0])
        h[0] += 1
        h[1] += r["ptax"] or 0
    # legacy quirk kept: slabs sharing a rate (the two 0-rate slabs) each get the same hands, so the
    # Grand Total counts those hands twice — exactly as the Crystal footer does
    cats = ("worker", "monthly", "officer", "ho")
    det = []
    for s in slabs:
        d = {"r1": s["r1"], "r2": s["r2"], "rate": s["rate"]}
        for c in cats:
            d[f"{c}_h"], d[f"{c}_a"] = hands.get((c, round(s["rate"] or 0, 2)), (0, 0.0))
        d["total_h"] = sum(d[f"{c}_h"] for c in cats)
        d["total_a"] = sum(d[f"{c}_a"] for c in cats)
        det.append(d)
    sums = [f"{c}_{x}" for x in ("h", "a") for c in (*cats, "total")]
    cols = [_col("grp", "", width=110), _num("r1", "Slab From", 100), _num("r2", "Slab To", 100), _num("rate", "Rate"),
            _num("worker_h", "Worker Hands"), _num("monthly_h", "Monthly Hands"), _num("officer_h", "Officer Hands"),
            _num("ho_h", "HO Hands"), _num("total_h", "Total Hands"), _num("worker_a", "Worker Amt", 110),
            _num("monthly_a", "Monthly Amt", 110), _num("officer_a", "Officer Amt", 110), _num("ho_a", "HO Amt", 110),
            _num("total_a", "Total Amt", 110)]
    return cols, _layout(det, [], sums, "grp", "rate")


# key = last segment of the seeded menu path hrms/nbjclreports/salary/<key>
_M = {"span": "month"}
REPORTS: dict[str, dict[str, dict]] = {"salary": {
    "monthlyPaidStaffPayslip": {**_M, "title": "MONTHLY-PAID STAFF PAYSLIP", "dates": "single", "extra": None, "build": clerk_payslip},
    "monthlyPaidStaffSalarySlip": {**_M, "title": "MONTHLY-PAID STAFF SALARY SLIP", "dates": "single", "extra": None, "build": staff_payslip},
    "leaveBalanceStatement": {**_M, "title": "LEAVE BALANCE STATEMENT", "dates": "range", "extra": None, "build": leave_balance},
    "deptSummaryClerkStaff": {**_M, "title": "DEPT SUMMARY-CLERK -STAFF", "dates": "range", "extra": None, "build": dept_summary},
    "grandSummaryClerkStaff": {**_M, "title": "GRAND SUMMARY-CLERK -STAFF", "dates": "range", "extra": None, "build": grand_summary},
    "incomeTaxStatement": {**_M, "title": "INCOME TAX STATEMENT", "dates": "range", "extra": None, "build": income_tax},
    "licRecoveryStatement": {**_M, "title": "LIC RECOVERY STATEMENT", "dates": "range", "extra": None, "build": lic_recovery},
    "lwfReportFormD": {**_M, "title": "LWF REPORT [ FORM-D]", "dates": "range", "extra": None, "build": lwf_form_d},
    "pfcAdvStatement": {**_M, "title": "PFC / ADV STATEMENT", "dates": "range", "extra": None, "build": pfc_adv},
    "pfContLoanBalanceStatement": {**_M, "title": "PF CONT. / LOAN BALANCE STATEMENT", "dates": "range", "extra": None, "build": pfc_loan_bal},
    "pTaxStatement": {**_M, "title": "P-TAX STATEMENT", "dates": "range", "extra": None, "build": ptax_statement},
    "bonusPaySlipStaff": {**_M, "title": "BONUS PAY SLIP - STAFF", "dates": "range", "extra": None, "build": bonus_payslip},
}}
