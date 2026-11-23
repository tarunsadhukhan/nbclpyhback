"""Winsome Reports > wages (see __init__.py): the legacy *_WIL wages / bonus reports on the mirrored legacy
tables PayWages (PaySlipType 'WAGES' / 'OT', EDate = fortnight end), PayOEMP, ODPT, OWages, PayOPWG and
PayBonusProcessed_Worker. Headings are the legacy ones, including the legacy bindings the Crystal layouts
print (e.g. "PF" shows PayWages.Pension, "FPF" shows CoC — WagesPaySlip_WIL_ColumnMapping.xlsx)."""
from src.hrms.winsomereports._common import _col, _layout, _num, rows, scope_args, spec

_DEPT = "IFNULL((SELECT CONCAT(d.DeptCode, ' - ', d.DeptName) FROM ODPT d WHERE d.DeptCode = w.DeptCode LIMIT 1), '')"
_OCCP = "IFNULL((SELECT d.OCPName FROM ODPT d WHERE d.DeptCode = w.OccpCode LIMIT 1), '')"  # legacy joins DeptCode

# (PayWages column, heading) of the pay sheets / slips, as the stacked legacy cells print them (top, bottom).
_SHEET_WAGES = (
    ("Work_HR", "W.HR"), ("LayOff_HR", "LF HR"), ("Holiday_HR", "Hol HR"), ("NS_HR", "NS HR"), ("CL_HR", "CL HR"),
    ("PL_HR", "PL HR"), ("FBasic_Amt", "Basic"), ("Pension", "PF"), ("FBasicInc_Amt", "IncBasic"), ("CoC", "FPF"),
    ("PBasic_Amt", "PBasic"), ("ESI_Amt", "ESI"), ("DA_Amt", "DA"), ("HRDeduction", "HRD"),
    ("Holiday_Amt", "HolAmt"), ("Incentive_Amt", "Inc.Amt"), ("PL_Amt", "PLAmt"), ("CL_Amt", "CLAmt"),
    ("NS_Amt", "NSAllow"), ("PFEarnAdj", "PFAdj"), ("NPFEarnAdj", "NPFAdj"), ("LayOffHR_Amt", "Lay Off"),
    ("PFLoanCap", "LoanCap"), ("ROff", "ROff"), ("TotalDeduction", "TotalDed"), ("Wages_Gross", "Gross Earn"),
    ("NetPayable", "NetPayable"),
)
_SHEET_OT = (
    ("Work_HR", "W.HR"), ("LayOff_HR", "LF HR"), ("NS_HR", "NS HR"), ("OT_HR", "OT HR"), ("FBasic_Amt", "Basic"),
    ("Pension", "PF"), ("FBasicInc_Amt", "IncBasic"), ("CoC", "FPF"), ("PBasic_Amt", "PBasic"), ("ESI_Amt", "ESI"),
    ("DA_Amt", "DA"), ("HRDeduction", "HRD"), ("Holiday_Amt", "HolAmt"), ("Incentive_Amt", "Inc.Amt"),
    ("NS_Amt", "NS Allow"), ("OT_Amt", "OT Amt"), ("PFEarnAdj", "PFAdj"), ("NPFEarnAdj", "NPFAdj"),
    ("LayOffHR_Amt", "Lay Off"), ("ROff", "ROff"), ("TotalDeduction", "Total Ded."), ("Wages_Gross", "Gross Earn"),
    ("NetPayable", "Net Payable"),
)
_YTD = (("YTD_Days", "YT.Days"), ("YTD_PFEmployee", "PF Emp."), ("YTD_Employer", "PF Comp."),
        ("YTD_Pension", "Pension"), ("YTD_LoanAmt", "Loan Bal."))
# WagesPaySlip_Hindi_WIL: the slip's Hindi captions; ESI-number caption shows PayOEMP.ESINo (legacy binds ECode there).
_HINDI = (
    ("dept", "विभाग", "t"), ("ECode", "दि० संख्या", "t"), ("EName", "नाम", "t"), ("occp", "पद का नाम", "t"),
    ("PFNo", "प्रो० फण्ड सख्या", "t"), ("ESINo", "रा० क० बीमा संख्या", "t"), ("UAN", "यु ए एन", "t"),
    ("Work_HR", "कुल काम के घंटे", "n"), ("LayOff_HR", "ले ऑफ घंटा", "n"), ("NS_HR", "'सि' पालि", "n"),
    ("Holiday_HR", "छुट्टी घंटा", "n"), ("STL_HR", "वार्षिक छुट्टी", "n"), ("FBasic_Amt", "मूल", "n"),
    ("FBasicInc_Amt", "मूल बढ़ोत्तरी", "n"), ("PBasic_Amt", "युक्त प्रता", "n"), ("DA_Amt", "महंगाई भत्ता", "n"),
    ("NS_Amt", "'सि' वेतन", "n"), ("Holiday_Amt", "छुट्टी वेतन", "n"), ("LayOffHR_Amt", "ले ऑफ वेतन", "n"),
    ("Wages_Gross", "कुल वेतन", "n"), ("PFEmployee", "प्रो० फण्ड जमा", "n"), ("FPF_Pension", "फ० पे० फण्ड जमा", "n"),
    ("PFLoanCap", "प्रो० फण्ड ॠण किस्त", "n"), ("ESI_Amt", "कर्मचारी राज्य बीमा कटौती", "n"),
    ("LWF_Amt", "बेल फेयर ट्रस्ट", "n"), ("HRDeduction", "घर भाड़ा", "n"), ("Advance", "चालू वेतन अगाऊ", "n"),
    ("OtherDeduction", "अन्य कटौती", "n"), ("TotalDeduction", "कुल कटौती", "n"), ("NetPayable", "देय वेतन", "n"),
)


def _paywages(db, b, t, slip_type: str) -> list[dict]:
    """PayWages rows of the fortnight + PayOEMP numbers and ODPT names, ordered DeptCode, ECode as legacy."""
    return rows(db, f"""
        SELECT w.*, e.PFNo, e.ESINo, e.UAN, {_DEPT} AS dept, {_OCCP} AS occp
        FROM PayWages w LEFT JOIN PayOEMP e ON e.ECode = w.ECode
        WHERE w.EDate = :t AND w.PaySlipType = :p AND w.CompCode = :c AND w.Location = :l
        ORDER BY w.DeptCode, w.ECode""", scope_args(b, t=t, p=slip_type))


def _sheet(db, b, t, slip_type, cells):
    """WagesPaySheet(_OT)_WIL: every pay line of the fortnight by department, with department / grand totals.
    ponytail: legacy group footers sum FBasic / Pension twice in place of CoC / FBasicInc; every column is summed here."""
    det = _paywages(db, b, t, slip_type)
    cols = [_col("grp", "Department", width=220), _col("ECode", "ECode", width=90), _col("EName", "EName", width=200),
            *[_num(k, h, 95) for k, h in cells]]
    return cols, _layout(det, [lambda d: d["dept"]], [k for k, _ in cells], "grp", "ECode")


def _slip(db, b, t, slip_type, cells, ytd=()):
    """WagesPaySlip(_OT)_WIL: one grid line per pay slip (legacy prints one slip per ECode, by department)."""
    det = _paywages(db, b, t, slip_type)
    cols = [_col("dept", "Department", width=200), _col("ECode", "ECode", width=90), _col("EName", "EName", width=200),
            _col("PFNo", "PFNo", width=140), _col("ESINo", "ESINo", width=120), _col("UAN", "UAN", width=130),
            *[_num(k, h, 95) for k, h in (*cells, *ytd)]]
    return cols, det


def wages_paysheet(db, b, f, t, extra):
    return _sheet(db, b, t, "WAGES", _SHEET_WAGES)


def wages_paysheet_ot(db, b, f, t, extra):
    return _sheet(db, b, t, "OT", _SHEET_OT)


def wages_payslip(db, b, f, t, extra):
    return _slip(db, b, t, "WAGES", _SHEET_WAGES, _YTD)


def wages_payslip_ot(db, b, f, t, extra):
    return _slip(db, b, t, "OT", _SHEET_OT)


def wages_payslip_hindi(db, b, f, t, extra):
    """WagesPaySlip_Hindi_WIL: the Hindi pay slip, one grid line per worker."""
    cols = [_col(k, h, width=150) if kind == "t" else _num(k, h, 110) for k, h, kind in _HINDI]
    return cols, _paywages(db, b, t, "WAGES")


# (field, heading, SQL) of WagesRegisterSummary_*_WIL, in print order; flag "W" = wages only (not in the OT copy).
_SUMMARY = (
    ("ecount", "NO. OF PAYSLIP", "COUNT(*)", ""), ("work_hr", "WRK HRS", "SUM(w.Work_HR)", ""),
    ("ns_hr", "NS HR", "SUM(w.NS_HR)", ""), ("holiday_hr", "HOL HRS", "SUM(w.Holiday_HR)", ""),
    ("lost_hr", "LOST HRS", "SUM(w.Lost_HR)", ""), ("stl_hr", "STL HRS", "SUM(w.STL_HR)", ""),
    ("stl_days", "STL DAYS", "SUM(w.STL_HR) / 8", ""), ("layoff_hr", "LOFF HRS", "SUM(w.LayOff_HR)", ""),
    ("ot_hr", "OT HRS", "SUM(w.OT_HR)", ""), ("pl_hr", "PL HRS", "SUM(w.PL_HR)", "W"),
    ("cl_hr", "CL HRS", "SUM(w.CL_HR)", "W"), ("total_days", "TotalDays", "SUM(w.TotalDays)", ""),
    ("pfmember", "NO. OF PF MEMBERS", "SUM(w.PFEmployee > 0)", ""),
    ("pnmember", "NO. OF PEN MEMBERS", "SUM(w.Pension > 0)", ""),
    ("esimember", "NO. OF ESI MEMBERS", "SUM(w.ESI_Amt > 0)", ""),
    ("fbasic", "FIX BASIC", "SUM(w.FBasic_Amt)", ""), ("fbasicinc", "FIX BASIC INC.", "SUM(w.FBasicInc_Amt)", ""),
    ("pbasic", "PRD BASIC", "SUM(w.PBasic_Amt)", ""), ("da", "F.D.A.", "SUM(w.DA_Amt)", ""),
    ("ns_amt", "NS ALLOW", "SUM(w.NS_Amt)", ""), ("holiday_amt", "HOLIDAY", "SUM(w.Holiday_Amt)", ""),
    ("pl_amt", "PL AMT", "SUM(w.PL_Amt)", "W"), ("cl_amt", "CL AMT", "SUM(w.CL_Amt)", "W"),
    ("layoff_amt", "LOFF", "SUM(w.LayOffHR_Amt)", ""), ("pfearnadj", "PFEarnAdj", "SUM(w.PFEarnAdj)", ""),
    ("npfearnadj", "NPFEarnAdj", "SUM(w.NPFEarnAdj)", ""), ("incentive", "INCENTIVE", "SUM(w.Incentive_Amt)", ""),
    ("ot_amt", "OTAmt", "SUM(w.OT_Amt)", ""), ("pf_gross", "PF GROSS", "SUM(w.PF_Gross)", ""),
    ("wages_gross", "GROSS WGS", "SUM(w.Wages_Gross)", ""),
    ("fringe1", "WITH FRINGE BENEFIT RATE PER DAY", "", ""),
    ("pfgross", "PF GROSS (PF MEMBERS)", "SUM(IF(w.PFEmployee > 0, w.PF_Gross, 0))", ""),
    ("pngross", "PEN GROSS", "SUM(IF(w.Pension > 0, w.Pension_Gross, 0))", ""),
    ("esigross", "ESI GROSS", "SUM(IF(w.ESI_Amt > 0, w.ESI_Gross, 0))", ""),
    ("bf", "BF", "SUM(w.BF)", ""), ("netpay", "NET PAY", "SUM(w.NetPay)", ""), ("cf", "CF", "SUM(w.CF)", ""),
    ("roff", "R/OFF", "SUM(w.ROff)", ""), ("netpayable", "NET PAYABLE", "SUM(w.NetPayable)", ""),
    ("fringe2", "WITH OUT FRINGE BENEFIT RATE PER DAY", "", ""),
    ("pfcont", "PF CONT", "SUM(IF(w.PFEmployee > 0, w.PFEmployee, 0))", ""),
    ("pncont", "PEN CONT", "SUM(IF(w.Pension > 0, w.Pension, 0))", ""),
    ("esicont", "ESI CONT", "SUM(w.ESI_Amt)", ""),
    ("coccont", "COC CONT", "SUM(IF(w.PFEmployee > 0, w.CoC, 0))", ""),
    ("pension", "PF", "SUM(w.Pension)", ""), ("coc", "FPF", "SUM(w.CoC)", ""), ("esi_amt", "ESI", "SUM(w.ESI_Amt)", ""),
    ("hrd", "H RENT", "SUM(w.HRDeduction)", ""), ("loan_cap", "Loan Cap.", "SUM(w.PFLoanCap)", "W"),
    ("loan_int", "Loan Int.", "SUM(w.PFLoanInt)", "W"), ("total_ded", "TOTAL DED.", "SUM(w.TotalDeduction)", ""),
    ("esic", "ESI EMPLOYER CONT [ 3.25 % ]", "SUM(w.ESIC)", ""),
    ("tot_pf", "PF EMPLOYEE + EMPLOYER CONT", "SUM(w.PFEmployee) + SUM(w.Pension) + SUM(w.CoC)", ""),
    ("tot_esi", "ESI EMPLOYEE + EMPLOYER CONT", "SUM(w.ESI_Amt) + SUM(w.ESIC)", ""),
)


def _fringe(r: dict, with_leave: bool) -> None:
    """Legacy @TotHR = paid days ((work + NS + holiday + STL + lay-off [+ PL + CL] hours) / 8);
    Fringe1 = gross wages / days, Fringe2 = PF gross of the PF members / days."""
    keys = ("work_hr", "ns_hr", "holiday_hr", "stl_hr", "layoff_hr") + (("pl_hr", "cl_hr") if with_leave else ())
    days = sum(r.get(k) or 0 for k in keys) / 8
    r["fringe1"] = round(r.get("wages_gross", 0) / days, 2) if days else 0.0
    r["fringe2"] = round(r.get("pfgross", 0) / days, 2) if days else 0.0


def _summary(db, b, t, slip_type):
    """WagesRegisterSummary_WAGES / _OT_WIL: the fortnight's MILL-WORKMEN payroll per department + grand total."""
    wages = slip_type == "WAGES"
    items = [s for s in _SUMMARY if wages or s[3] != "W"]
    sel = ", ".join(f"{sql} AS {k}" for k, _, sql, _ in items if sql)
    det = rows(db, f"""
        SELECT w.DeptCode AS dept_code,
               IFNULL((SELECT MAX(d.DeptName) FROM ODPT d WHERE d.DeptCode = w.DeptCode), '') AS dept_name, {sel}
        FROM PayOEMP e JOIN PayWages w ON w.ECode = e.ECode
        WHERE e.Grade = 'Mill-Workmen' AND w.PaySlipType = :p AND w.EDate = :t AND w.CompCode = :c AND w.Location = :l
        GROUP BY w.DeptCode ORDER BY w.DeptCode""", scope_args(b, t=t, p=slip_type))
    for d in det:
        d["dept"] = f"{d['dept_code']} - {d['dept_name']}"
        _fringe(d, wages)
    out = _layout(det, [], [k for k, _, sql, _ in items if sql], "dept", "ecount")
    if out:
        _fringe(out[-1], wages)  # grand fringe = summed amount / summed days (legacy Fringe11 / Fringe22)
    return [_col("dept", "Department", width=230), *[_num(k, h, 110) for k, h, _, _ in items]], out


def dept_summary(db, b, f, t, extra):
    return _summary(db, b, t, "WAGES")


def dept_summary_ot(db, b, f, t, extra):
    return _summary(db, b, t, "OT")


def daily_paysheet(db, b, f, t, extra):
    """WorkerDailyPaySheet_WIL: daily-paid workers (OWages) of one date and shift, by grade.
    ponytail: OWages ends 30/05/2022 in legacy too — kept for whatever it gets."""
    det = rows(db, """
        SELECT e.Grade AS grade, w.ECode AS ecode, e.EName AS ename, w.OcpCode AS ocp, w.Rate AS rate,
               w.TotalHrs AS hrs, w.NetPay AS net
        FROM OWages w JOIN PayOEMP e ON e.ECode = w.ECode
        WHERE w.WDate = :t AND (:s = '' OR w.WShift = :s)
        ORDER BY e.Grade, e.EName""", {"t": t, "s": extra[:1]})
    n: dict[str, int] = {}
    for r in det:
        n[r["grade"]] = r["sl"] = n.get(r["grade"], 0) + 1
    cols = [_col("grp", "Grade", width=150), _num("sl", "SL", 60), _col("ecode", "ECode", width=90),
            _col("ename", "EName", width=220), _col("ocp", "OcpCode", width=90), _num("rate", "Rate"),
            _num("hrs", "Hrs."), _num("net", "NetPay"), _col("sign", "Signature", width=120)]
    return cols, _layout(det, [lambda d: d["grade"]], ["hrs", "net"], "grp", "ecode")


def provisional_wages(db, b, f, t, extra):
    """PayOPWG_WIL: provisional daily wages of one date, by shift and department (SlNo per department).
    ponytail: PayOPWG is empty in legacy and in the mirror — kept for whatever it gets."""
    det = rows(db, """
        SELECT WShift AS shift, DeptCode AS dept_code, DeptName AS dept_name, ECode AS ecode, EName AS ename,
               Designation AS desig, Work_HR AS work_hr, Rate AS rate, PaidAmt AS paid
        FROM PayOPWG WHERE CompCode = :c AND Location = :l AND EffDate = :t AND (:s = '' OR WShift = :s)
        ORDER BY WShift, DeptCode, Designation""", scope_args(b, t=t, s=extra[:1]))
    n: dict[str, int] = {}
    for r in det:
        n[r["dept_code"]] = r["sl"] = n.get(r["dept_code"], 0) + 1
    cols = [_col("grp", "Shift / Department", width=220), _num("sl", "SlNo", 60), _col("ecode", "ECode", width=90),
            _col("ename", "EName", width=220), _col("desig", "Designation", width=150), _num("work_hr", "Work HR"),
            _num("rate", "Rate"), _num("paid", "Paid Amt", 100), _col("sign", "Signature", width=120)]
    levels = [lambda d: f"Shift : {d['shift']}", lambda d: f"{d['dept_name']} [ {d['dept_code']} ]"]
    return cols, _layout(det, levels, ["paid"], "grp", "ecode")


def bonus_register(db, b, f, t, extra):
    """BonusRegister_WIL (RPT_BonusRegister, branch From >= 01/04/2023): processed MILL-WORKMEN bonus whose
    year ends From..To, by department.
    ponytail: years before 2023-24 read BONUS_2122 / Given_PL_CL_2022, which are not mirrored — only
    PayBonusProcessed_Worker is ported."""
    det = rows(db, """
        SELECT DeptCode AS dept_code, DeptName AS dept_name, ECode AS ecode, EName AS ename, TotalDays AS days,
               TotalBnsG AS gross, PayableBNSAmt AS paid
        FROM PayBonusProcessed_Worker WHERE Grade = 'MILL-WORKMEN' AND EDate BETWEEN :f AND :t
        ORDER BY DeptCode, ECode""", {"f": f, "t": t})
    n: dict[str, int] = {}
    for r in det:
        n[r["dept_code"]] = r["sl"] = n.get(r["dept_code"], 0) + 1
    cols = [_col("grp", "DEPT", width=220), _num("sl", "SLNo", 70), _col("ecode", "ESI NO", width=100),
            _col("ename", "EMPLOYEE NAME", width=240), _num("days", "TOTAL DAYS WORKED", 110),
            _num("gross", "AMOUNT ON BONUS PAID", 130), _num("paid", "Amt Bonus Payable U/S 10-11", 130),
            _col("sign", "signature/Thumb impression of the employee", width=160)]
    return cols, _layout(det, [lambda d: f"{d['dept_code']} {d['dept_name']}"], ["days", "gross", "paid"], "grp", "ecode")


def bonus_slip(db, b, f, t, extra):
    """BonusSlip_WIL (RPT_BonusSlip): one grid line per bonus slip (legacy prints two slips side by side)."""
    det = rows(db, """
        SELECT Bonus_Year AS fyear, DeptName AS dept, ECode AS ecode, EName AS ename, PayableBNSAmt AS paid
        FROM PayBonusProcessed_Worker WHERE EDate BETWEEN :f AND :t AND PayableBNSAmt > 0
        ORDER BY DeptCode, ECode""", {"f": f, "t": t})
    for i, r in enumerate(det, start=1):
        r["sl"] = i
    cols = [_num("sl", "Slno", 70), _col("fyear", "Year", width=90), _col("dept", "Dept", width=200),
            _col("ecode", "Esino", width=100), _col("ename", "Name", width=240), _num("paid", "Total Amount", 120)]
    return cols, det


SHIFTS = {"label": "Shift", "options": [{"value": s, "label": s} for s in ("A", "B", "C")]}

# key = last segment of the seeded menu path hrms/winsomereports/wages/<key>
REPORTS: dict[str, dict[str, dict]] = {"wages": {
    "workerDailyPaysheet": spec("Worker Daily PaySheet", daily_paysheet, "single", "day", SHIFTS),
    "dailyProvisionalWagesSheet": spec("Daily Provisional Wages Sheet", provisional_wages, "single", "day", SHIFTS),
    "wagesPaysheet": spec("Wages PaySheet", wages_paysheet, "single"),
    "wagesPaysheetOt": spec("Wages PaySheet [ OT ]", wages_paysheet_ot, "single"),
    "wagesPayslip": spec("Wages PaySlip", wages_payslip, "single"),
    "wagesPayslipHindi": spec("Wages PaySlip Hindi", wages_payslip_hindi, "single"),
    "wagesPayslipOt": spec("Wages PaySlip [ OT ]", wages_payslip_ot, "single"),
    "departmentWiseWagesSummary": spec("Department Wise Wages Summary", dept_summary, "single"),
    "departmentWiseWagesSummaryOt": spec("Department Wise Wages Summary [ OT ]", dept_summary_ot, "single"),
    "bonusRegister": spec("Bonus Register", bonus_register, "range", "month"),
    "bonusSlip": spec("Bonus Slip", bonus_slip, "range", "month"),
}}
