"""
Winsome Reports > excel — the legacy ORPSMTEye "EXCEL" reports. FrmSmartEyeReportMulti.Print_EXCEL runs
`Exec Excel_Report '<REPORT NAME>', SDt, EDt, Days` and dumps the result table into Excel as-is (title rows,
no totals); Excel_Report dispatches to Excel_PensionStatement / Excel_ESIStatement / Excel_ECRStatement /
Excel_BankStatement. Each proc only uses the To date (Pension / ESI / ECR: 1st of its month .. To date;
Bank: the fortnight ending on it), so the "Calculative Days" input box is ignored by all of them.

ponytail: legacy reads every company / location; PayWages / PaySalary are scoped to the branch here.
ponytail: legacy prefixes ECode / AccNo with ' to keep them text in Excel; the grid keeps them text.
"""
from datetime import date, timedelta

from src.hrms.winsomereports._common import _col, _num, rows, scope_args, spec

SC = "CompCode = :c AND Location = :l"
W = "w.CompCode = :c AND w.Location = :l"


def _month(b: int, t: date) -> dict:
    return scope_args(b, f=t.replace(day=1), t=t)


def _days(p: dict) -> list[date]:
    return [p["f"] + timedelta(n) for n in range((p["t"] - p["f"]).days + 1)]


def _holidays(db, p: dict) -> int:
    return rows(db, "SELECT COUNT(*) n FROM PayOHoliday WHERE HolidayDate BETWEEN :f AND :t", p)[0]["n"]


def _duty(db, p: dict, col: str) -> dict[str, float]:
    """Round(SUM(<col>), 0) of the legacy view AttendanceReport (ATTEN + PayOEMP / ODPT / Shift / OUNIT inner
    joins) for Work_Type 'DUTY', per ECode."""
    return {r["e"]: r["v"] or 0.0 for r in rows(db, f"""
        SELECT a.emp_code e, ROUND(SUM({col}), 0) v FROM ATTEN a
        JOIN PayOEMP e ON a.emp_code = e.ECode
        JOIN ODPT d ON a.dept_code = d.DeptCode AND a.ocp_code = d.OCPCode
        JOIN Shift s ON a.WShift = s.SHIFTMSTID
        JOIN OUNIT u ON a.WUnit = u.UCode
        WHERE a.work_type = 'DUTY' AND a.WDate BETWEEN :f AND :t GROUP BY a.emp_code""", p)}


def pension_statement(db, b, f, t, extra):
    """Excel_PensionStatement: mill workmen with PF / pension deducted this month, plus PF members not paid
    (zero line); ABDay = month days - Sundays - holidays - duty head count."""
    p = _month(b, t)
    off = sum(d.weekday() == 6 for d in _days(p)) + _holidays(db, p)
    duty = _duty(db, p, "a.HeadCount")
    paid = rows(db, f"""
        SELECT e.ECode, e.PensionNo, e.UAN, e.EName, e.Grade, SUM(w.PF_Gross) Wages_Gross,
               SUM(ROUND(IF(w.PFEmployee > 0, w.PF_Gross, 0), 0)) PF_Gross,
               SUM(IF(w.Pension > 0, w.Pension_Gross, 0)) Pension_Gross,
               SUM(w.PFEmployee) PFEmployee, SUM(w.Pension) Pension, SUM(w.COC) COC
        FROM PayOEMP e JOIN PayWages w ON e.ECode = w.ECode
        WHERE {W} AND w.EDate BETWEEN :f AND :t
          AND e.Grade = 'MILL-WORKMEN' AND w.PaySlipType = 'WAGES'
        GROUP BY e.ECode, e.PensionNo, e.UAN, e.EName, e.Grade
        HAVING SUM(w.PFEmployee) > 0 OR SUM(w.Pension) > 0""", p)
    done = {r["ECode"] for r in paid}
    idle = rows(db, """
        SELECT ECode, PensionNo, UAN, EName FROM PayOEMP
        WHERE Grade = 'MILL-WORKMEN' AND EGroup NOT IN ('OUTSIDER', 'RETIRE') AND (PFNo <> '' OR PensionNo <> '')
        GROUP BY ECode, EName, UAN, PensionNo""")
    det = []
    for r in paid + [dict(r, Grade="") for r in idle if r["ECode"] not in done]:
        ab = t.day - (off + duty.get(r["ECode"], 0.0))
        pension = r.get("Pension") or 0.0
        ab = t.day - 1 if pension > 0 and ab == t.day else max(ab, 0)
        det.append({"ECode": r["ECode"], "PensionNo": r["PensionNo"], "UAN": r["UAN"], "EName": r["EName"],
                    "Wages_Gross": r.get("Wages_Gross") or 0.0, "PF_Gross": r.get("PF_Gross") or 0.0,
                    "PF_Net": min(r.get("PF_Gross") or 0.0, 15000), "Pension_Gross": min(r.get("Pension_Gross") or 0.0, 15000),
                    "DLIWages": 0.0, "PFEmployee": r.get("PFEmployee") or 0.0, "Pension": pension,
                    "COC": r.get("COC") or 0.0, "ABDay": ab, "Grade": r["Grade"]})
    det.sort(key=lambda d: d["ECode"].upper())
    cols = [_col("ECode", "ECode", width=90), _col("PensionNo", "PensionNo", width=150), _col("UAN", "UAN", width=130),
            _col("EName", "EName", width=220)] + [_num(k, k, 100) for k in (
        "Wages_Gross", "PF_Gross", "PF_Net", "Pension_Gross", "DLIWages", "PFEmployee", "Pension", "COC", "ABDay")] + [
        _col("Grade", "Grade", width=130)]
    return cols, det


def esi_statement(db, b, f, t, extra):
    """Excel_ESIStatement: ESIC contribution per insured person for the month of the To date — mill workmen
    (days = Ceiling(hours / 8)), ESI members not paid (zero line) and staff (days = Present)."""
    p = _month(b, t)
    cap = {31: 27, 30: 26, 29: 24, 28: 24}.get(t.day, 0)
    wages = rows(db, f"""
        SELECT w.ECode EMPNO, e.ESINo IPNO, e.EName NAME,
               CEILING(SUM(w.Work_HR + w.NS_HR + w.Holiday_HR + w.STL_HR + w.PL_HR + w.CL_HR) / 8) days,
               SUM(w.ESI_Gross) gross, SUM(w.ESI_Amt) ee, SUM(w.ESIC) er
        FROM PayWages w LEFT JOIN PayOEMP e ON w.ECode = e.ECode
        WHERE {W} AND w.Grade = 'MILL-WORKMEN' AND w.EDate BETWEEN :f AND :t AND w.ESI_Amt <> 0
          AND w.PaySlipType = 'WAGES'
        GROUP BY w.ECode, e.EName, e.ESINo""", p)
    staff = rows(db, f"""
        SELECT w.ECode EMPNO, e.ESINo IPNO, e.EName NAME, CEILING(SUM(w.Present)) days,
               SUM(w.GROSS_ESI) gross, SUM(w.ESI) ee, SUM(w.ESIC) er
        FROM PaySalary w LEFT JOIN PayOEMP e ON w.ECode = e.ECode
        WHERE {W} AND w.Grade = 'STAFF' AND w.EDate BETWEEN :f AND :t AND w.ESI <> 0 AND w.PType = 'SALARY'
        GROUP BY w.ECode, e.EName, e.ESINo""", p)
    idle = rows(db, f"""
        SELECT ECode EMPNO, ESINo IPNO, EName NAME FROM PayOEMP
        WHERE Grade = 'MILL-WORKMEN' AND EGroup NOT IN ('OUTSIDER', 'RETIRE') AND ESINo <> ''
          AND ECode NOT IN (SELECT ECode FROM PayWages WHERE {SC} AND EDate BETWEEN :f AND :t AND ESI_Amt <> 0
                            AND PaySlipType = 'WAGES')
        GROUP BY ECode, EName, ESINo""", p)
    det = [{"EMPNO": r["EMPNO"], "IPNO": r["IPNO"], "NAME": r["NAME"],
            "days": min(r["days"] or 0, cap), "gross": r["gross"] or 0.0, "ee": r["ee"] or 0.0,
            "er": (r["er"] or 0.0) if (r["ee"] or 0) > 0 else 0.0} for r in wages + staff]
    det += [dict(r, days=0, gross=0.0, ee=0.0, er=0.0) for r in idle]
    det.sort(key=lambda d: d["EMPNO"].upper())
    cols = [_col("EMPNO", "EMPNO", width=90), _col("IPNO", "IPNO", width=130), _col("NAME", "NAME", width=220),
            _num("days", "No.of Days Worked", 130), _num("gross", "Total Wages", 110),
            _num("ee", "Employee's Cont.", 120), _num("er", "Employer's Cont.", 120)]
    return cols, det


def ecr_statement(db, b, f, t, extra):
    """Excel_ECRStatement: EPFO ECR lines for the month of the To date — mill workmen with PF / pension
    (NCP = month days - holidays - rest days - duty head count - night hrs / 8 - PL + CL leave) and staff
    (NCP = Absent). Wages capped at 15000; EPS wages are the ESI gross, as in legacy."""
    p = _month(b, t)
    days, hol = _days(p), _holidays(db, p)
    duty, night = _duty(db, p, "a.HeadCount"), _duty(db, p, "a.Night_HR / 8")
    leave = {r["ECode"]: r["n"] or 0.0 for r in rows(db, """SELECT ECode, SUM(PL + CL) n FROM PayJOLeave
        WHERE DocStatus = 'OPEN' AND FNEDate BETWEEN :f AND :t GROUP BY ECode""", p)}
    wages = rows(db, f"""
        SELECT e.UAN, e.ECode, e.EName, e.RestDay, SUM(w.PF_Gross) gross, ROUND(SUM(w.PF_Gross), 0) epf_w,
               ROUND(SUM(w.ESI_Gross), 0) eps_w, SUM(w.PFEmployee) epf, SUM(w.Pension) eps, SUM(w.COC) diff
        FROM PayOEMP e JOIN PayWages w ON e.ECode = w.ECode
        WHERE {W} AND e.Grade = 'MILL-WORKMEN' AND w.EGroup NOT IN ('OUTSIDER', 'RETIRE')
          AND w.EDate BETWEEN :f AND :t AND w.PaySlipType = 'WAGES'
        GROUP BY e.ECode, e.EName, e.UAN, e.PensionNo, e.RestDay
        HAVING SUM(w.PFEmployee) <> 0 OR SUM(w.Pension) <> 0""", p)
    for r in wages:
        rest = sum(d.strftime("%a").upper() == (r["RestDay"] or "").upper() for d in days)
        e = r["ECode"]
        r["ncp"] = t.day - (hol + rest + duty.get(e, 0.0) + night.get(e, 0.0) + leave.get(e, 0.0))
    staff = rows(db, f"""
        SELECT e.UAN, e.ECode, e.EName, SUM(w.PFGROSS) gross, ROUND(SUM(w.PFGROSS), 0) epf_w,
               ROUND(SUM(w.GROSS_ESI), 0) eps_w, SUM(w.PF_E) epf, SUM(w.FPF_833) eps, SUM(w.FPF_167) diff,
               SUM(w.Absent) ncp
        FROM PayOEMP e JOIN PaySalary w ON e.ECode = w.ECode
        WHERE {W} AND e.Grade = 'STAFF' AND w.EDate BETWEEN :f AND :t AND w.PType = 'SALARY'
        GROUP BY e.ECode, e.EName, e.UAN, e.PensionNo, e.RestDay
        HAVING SUM(w.PF_E) <> 0 OR SUM(w.FPF_833) <> 0""", p)
    det = [{"UAN": r["UAN"], "MEMBER_ID": r["ECode"], "MEMBER_NAME": r["EName"], "GROSS_WAGES": r["gross"] or 0.0,
            "EPF_WAGES": min(r["epf_w"] or 0.0, 15000), "EPS_WAGES": min(r["eps_w"] or 0.0, 15000),
            "EDLI_WAGES": min(r["epf_w"] or 0.0, 15000), "EPF_CONTRI_REMITTED": r["epf"] or 0.0,
            "EPS_CONTRI_REMITTED": r["eps"] or 0.0, "EPF_EPS_DIFF_REMITTED": r["diff"] or 0.0,
            "NCP_DAYS": max(r["ncp"] or 0.0, 0), "REFUND_OF_ADVANCES": ""} for r in wages + staff]
    det.sort(key=lambda d: (d["MEMBER_ID"].upper(), (d["MEMBER_NAME"] or "").upper()))
    cols = [_col("UAN", "UAN", width=130), _col("MEMBER_ID", "MEMBER_ID", width=100),
            _col("MEMBER_NAME", "MEMBER_NAME", width=220)] + [_num(k, k, 120) for k in (
        "GROSS_WAGES", "EPF_WAGES", "EPS_WAGES", "EDLI_WAGES", "EPF_CONTRI_REMITTED", "EPS_CONTRI_REMITTED",
        "EPF_EPS_DIFF_REMITTED", "NCP_DAYS")] + [_col("REFUND_OF_ADVANCES", "REFUND_OF_ADVANCES", width=150)]
    return cols, det


def bank_statement(db, b, f, t, extra):
    """Excel_BankStatement: NEFT pay-out per employee for the fortnight ending on the To date — wages net pay
    plus the OT slip's net pay, with department (ODPT) and employee group."""
    p = scope_args(b, t=t)
    det = rows(db, f"""
        SELECT MAX(DeptCode) DeptCode, MAX(DeptName) DeptName, TType, ECode, AccNo, EName, IFSC, `Leave`,
               SUM(NetPay) NetPay, SUM(OT_NetPay) OT_Amt, SUM(ROff) Roff, SUM(NetPayable) NetPayable,
               (SELECT MAX(EGroup) FROM PayOEMP o WHERE o.ECode = tx.ECode) EGroup
        FROM (
          SELECT xx.DeptCode, d.DeptName, TType, ECode, AccNo, EName, IFSC, `Leave`, SUM(NetPay) NetPay,
                 SUM(OT_NetPay) OT_NetPay, SUM(ROff) ROff, SUM(NetPayable) NetPayable
          FROM (
            SELECT w.DeptCode, 'NEFT' TType, w.ECode, w.AccNo, w.EName, e.IFSC, '' `Leave`, w.NetPay,
                   w.OT_Amt OT_NetPay, w.ROff, w.NetPayable
            FROM PayWages w JOIN PayOEMP e ON w.ECode = e.ECode
            WHERE {W} AND w.EDate = :t AND w.PaySlipType = 'WAGES'
            UNION ALL
            SELECT w.DeptCode, 'NEFT', w.ECode, w.AccNo, w.EName, e.IFSC, '', 0, w.NetPay, w.ROff, w.NetPayable
            FROM PayWages w JOIN PayOEMP e ON w.ECode = e.ECode
            WHERE {W} AND w.EDate = :t AND w.PaySlipType = 'OT'
          ) xx JOIN (SELECT DeptCode, DeptName FROM ODPT GROUP BY DeptCode, DeptName) d ON xx.DeptCode = d.DeptCode
          GROUP BY xx.DeptCode, d.DeptName, TType, ECode, AccNo, EName, IFSC, `Leave`
        ) tx
        GROUP BY TType, ECode, AccNo, EName, IFSC, `Leave`
        ORDER BY DeptCode, ECode""", p)
    cols = [_col("DeptCode", "DeptCode", width=80), _col("DeptName", "DeptName", width=160),
            _col("TType", "TType", width=70), _col("ECode", "ECode", width=90), _col("AccNo", "AccNo", width=150),
            _col("EName", "EName", width=200), _col("IFSC", "IFSC", width=120), _col("Leave", "Leave", width=70),
            _num("NetPay", "NetPay", 100), _num("OT_Amt", "OT_Amt", 100), _num("Roff", "Roff", 80),
            _num("NetPayable", "NetPayable", 110), _col("EGroup", "EGroup", width=110)]
    return cols, det


REPORTS: dict[str, dict[str, dict]] = {
    "excel": {
        "pensionStatement": spec("Pension Statement", pension_statement, dates="single", span="month"),
        "esiStatement": spec("ESI Statement", esi_statement, dates="single", span="month"),
        "ecrStatement": spec("ECR Statement", ecr_statement, dates="single", span="month"),
        "bankStatement": spec("Bank Statement", bank_statement, dates="single", span="fortnight"),
    },
}
