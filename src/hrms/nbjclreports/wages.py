"""
NBJCL Reports > Wages — ports of the 12 legacy Smart-Eye reports of the "Wages" group (report master
ORPSMTEye, Reports/SmartEyeReportMulti/*_NJB.rpt plus the two DMP text slips of FrmSmartEyeReportMulti2).
See src/hrms/nbjclreports/__init__.py for the spec shape.

Most reports read the mirrored legacy tables directly (paywages, PayOEMP, PayCummOP, PaySalary,
PayJOLeave, PayOSTL, paywagesot, PayBonusProcessed_Worker, OWages, ODPT, Shift), with the legacy
SQL translated one for one. paywages is scoped by the branch's legacy CompCode / Location (_scope).
PayOEMP is utf8mb4_0900_ai_ci, the paywages-side mirrors utf8mb4_unicode_ci: joins add UCI.

Legacy ATTEN (daily attendance) -> live daily_attendance through _attendance() / _last_attendance();
the money of an OT day (legacy ATTEN FBasic/VBasic/DA/MiscEarn/Oil amounts) -> pay_attendance, which
the VoWERP wages process fills.

ponytail: PayOEMP is the legacy employee master as mirrored — its Active flag / Grade drive the
"active MILL-WORKMEN" filter exactly as legacy, so rows differ when the mirror's Active lags the live one.
"""
import collections
from datetime import date

from fastapi import HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.sql import text

from src.hrms.nbjclAttendanceReports import _attendance, _col, _dmy, _layout, _num
from src.hrms.wagesPayslipText import _num as _fmt, payslip_text
from src.hrms.wagesSalaryProcess import UCI, _scope, wages_payslip_rows

LINE_END = "\r\n"
PAGE_SKIP = "\f"

# Active mill workers of the legacy master, joined to their wages row of the FNE date.
_MILL = f"""
    FROM PayOEMP e JOIN paywages w ON w.ECode = e.ECode {UCI}
    WHERE e.Active = 'Y' AND e.Grade = 'MILL-WORKMEN' AND w.EDate = :t AND w.CompCode = :c AND w.Location = :l
"""


def _rows(db: Session, sql: str, args: dict) -> list[dict]:
    """Query rows as dicts with Decimal -> float and strings trimmed."""
    out = []
    for r in db.execute(text(sql), args):
        m = dict(r._mapping)
        for k, v in m.items():
            if isinstance(v, str):
                m[k] = v.strip()
            elif v is not None and not isinstance(v, (int, float, date)):
                m[k] = float(v)
        out.append(m)
    return out


def _args(b: int, t: date, **more) -> dict:
    comp, loc = _scope(b)
    return {"c": comp, "l": loc, "t": t, **more}


def _last_attendance(db: Session, b: int, t: date) -> dict[str, dict]:
    """Per employee code, the department / shift / occupation of the latest attendance on or before
    `t` (legacy: TOP 1 ... FROM Atten WHERE WDate <= @ToDate ORDER BY WDate DESC, WShift DESC)."""
    des = {r.SHIFTID: r.DES for r in db.execute(text("SELECT SHIFTID, DES FROM Shift"))}
    rows = db.execute(text("""
        SELECT ecode, dept_code, spell_code, occu_code FROM (
            SELECT o.emp_code AS ecode, IFNULL(d.dept_code, '') AS dept_code, IFNULL(sp.spell_code, '') AS spell_code,
                   IFNULL(g.occu_code, '') AS occu_code,
                   ROW_NUMBER() OVER (PARTITION BY da.eb_id ORDER BY da.attendance_date DESC, sp.spell_code DESC) rn
            FROM daily_attendance da
            JOIN hrms_ed_official_details o ON o.eb_id = da.eb_id AND o.active = 1
            LEFT JOIN sub_dept_mst sd ON sd.sub_dept_id = da.worked_department_id
            LEFT JOIN dept_mst d ON d.dept_id = sd.dept_id
            LEFT JOIN designation_mst g ON g.designation_id = da.worked_designation_id
            LEFT JOIN spell_mst sp ON sp.spell_id = da.spell_id
            WHERE da.branch_id = :b AND da.attendance_date <= :t AND da.is_active = 1
              AND CAST(da.status_id AS UNSIGNED) = 3) x
        WHERE rn = 1"""), {"b": b, "t": t})
    # legacy W.Shift = Shift.DES of the spell (A1 / A2 / G1 -> A ...)
    return {r.ecode: {"dept": r.dept_code, "shift": des.get(r.spell_code, ""), "ocp": r.occu_code} for r in rows}


# ─── Reports ───────────────────────────────────────────────────────────────


def daily_paysheet(db, b, f, t, extra):
    """WorkerDailyPaySheet_NJB: daily-paid workers of one date and shift, by grade.
    ponytail: legacy OWages is empty (in the live SQL Server too) — the daily pay sheet is not in use;
    ported as is so it shows whatever OWages gets."""
    rows = _rows(db, f"""
        SELECT e.Grade AS grade, w.ECode AS ecode, e.EName AS ename, w.OcpCode AS ocp, w.Rate AS rate,
               w.TotalHrs AS hrs, w.NetPay AS net
        FROM OWages w JOIN PayOEMP e ON e.ECode = w.ECode {UCI}
        WHERE w.WDate = :t AND (:s = '' OR w.WShift = :s)
        ORDER BY e.Grade, e.EName""", {"t": t, "s": extra[:1]})
    n: collections.Counter = collections.Counter()
    for r in rows:
        n[r["grade"]] += 1
        r["sl"] = n[r["grade"]]
    cols = [_col("grp", "Grade", width=150), _num("sl", "SL", 60), _col("ecode", "ECode", width=90),
            _col("ename", "EName", width=220), _col("ocp", "OcpCode", width=90), _num("rate", "Rate"),
            _num("hrs", "Hrs."), _num("net", "NetPay"), _col("sign", "Signature", width=120)]
    return cols, _layout(rows, [lambda d: d["grade"]], ["hrs", "net"], "grp", "ecode")


def dept_wise_list_ot(db, b, f, t, extra):
    """DeptWiseList_OT_NJB: OT work per worker, by department (and occupation), with its earnings.
    Legacy sums ATTEN Basic + DA / MiscEarn + OilAllowance — columns that no longer exist (the legacy
    report fails); read here as FBasic + VBasic + DA and MiscEarn + Oil of the OT day."""
    money = {(r.eb_id, r.attendance_date, r.spell_code): (float(r.pf or 0), float(r.oth or 0))
             for r in db.execute(text("""
        SELECT a.eb_id, a.attendance_date, IFNULL(sp.spell_code, '') AS spell_code,
               SUM(a.FBasic_Amt + a.VBasic_Amt + a.DA_Amt) AS pf, SUM(a.MiscEarn + a.Oil_Amt) AS oth
        FROM pay_attendance a LEFT JOIN spell_mst sp ON sp.spell_id = a.spell_id
        WHERE a.branch_id = :b AND a.attendance_date BETWEEN :f AND :t AND a.att_type = 'O'
        GROUP BY a.eb_id, a.attendance_date, sp.spell_code"""), {"b": b, "f": f, "t": t})}
    cards = {r.ECode: r.CardNo or "" for r in db.execute(text("SELECT ECode, CardNo FROM PayOEMP"))}
    agg: dict = collections.OrderedDict()
    for r in _attendance(db, b, f, t):
        if r["work_type"] != "OT" or r["work_hr"] <= 0:
            continue
        k = (r["dept_code"], r["desig"], r["ecode"])
        g = agg.setdefault(k, {"k_dept": f"{r['dept_code']} - {r['dept_name']}", "ecode": r["ecode"],
                               "card": cards.get(r["ecode"], ""), "ename": r["ename"], "work_hr": 0.0,
                               "work_day": 0, "pf_gross": 0.0, "other": 0.0})
        pf, oth = money.get((r["eb_id"], r["wdate"], r["wshift"]), (0.0, 0.0))
        g["work_hr"] += r["work_hr"]
        g["work_day"] += 1
        g["pf_gross"] += pf
        g["other"] += oth
    det = []
    for k in sorted(agg):
        g = agg[k]
        g["total"] = round(g["pf_gross"] + g["other"], 2)
        g["net"] = float(round(g["total"]))
        g["roff"] = round(g["net"] - g["total"], 2)
        g["advance"] = 0.0
        det.append(g)
    sums = ["work_hr", "work_day", "pf_gross", "other", "total", "advance", "roff", "net"]
    cols = [_col("grp", "Department", width=220), _col("ecode", "ECode", width=90), _col("card", "CardNo", width=90),
            _col("ename", "EName", width=220), _num("work_hr", "Work HR"), _num("work_day", "Work Day"),
            _num("pf_gross", "PFGross", 100), _num("other", "Other Earn", 100), _num("total", "Total Earn", 100),
            _num("advance", "Advance"), _num("roff", "ROff", 80), _num("net", "NetPay", 100)]
    return cols, _layout(det, [lambda d: d["k_dept"]], sums, "grp", "ecode")


def lwf_statement(db, b, f, t, extra):
    """LWFStatement_NJB: LWF deducted on the FNE date from active mill workers."""
    det = _rows(db, f"SELECT e.ECode AS ecode, e.CardNo AS card, e.EName AS ename, w.LWF_Amt AS lwf "
                    f"{_MILL} AND w.LWF_Amt > 0 ORDER BY e.ECode", _args(b, t))
    cols = [_col("grp", "ECode", width=110), _col("card", "Rec.No", width=100), _col("ename", "EName", width=240),
            _num("lwf", "LWFAmt", 100)]
    for d in det:
        d["grp"] = d["ecode"]
    return cols, _layout(det, [], ["lwf"], "grp", "card")


def pension_balance(db, b, f, t, extra):
    """PensionBalStatement_NJB: every active mill worker with pension amount 0 (as legacy)."""
    det = _rows(db, "SELECT ECode AS grp, CardNo AS card, EName AS ename, 0.0 AS pension FROM PayOEMP "
                    "WHERE Active = 'Y' AND Grade = 'MILL-WORKMEN' ORDER BY ECode", {})
    cols = [_col("grp", "ECode", width=110), _col("card", "Rec.No", width=100), _col("ename", "EName", width=240),
            _num("pension", "PensionAmt", 110)]
    return cols, _layout(det, [], ["pension"], "grp", "card")


def pf_cont_adv_balance(db, b, f, t, extra):
    """PFCont_AdvBalStatement_NJB: PF / pension / company contribution of the fortnight and to date,
    by PF-number series (first two characters), with advance balances in the totals.
    Legacy reads the PaySalary advance with single-row subqueries (an error when a worker has several
    rows); summed here — the same for the usual 0 or 1 row."""
    det = _rows(db, f"""
        SELECT e.PFNo AS pfno, e.ECode AS ecode, e.CardNo AS card, e.EName AS ename, w.PF_Gross AS pf_gross,
               w.PFEmployee AS pfc, IFNULL(op.bal, 0) + IFNULL(cw.pfe, 0) AS c_pfc, w.Pension AS pnc,
               w.FPF_Pension AS c_pnc, w.CoC AS coc, w.PF_Employer AS c_coc,
               IFNULL(s.adv_r, 0) AS adv_r, IFNULL(s.adv_bal, 0) AS adv_bal,
               IFNULL(s.adv_g, 0) AS set_g, IFNULL(s.adv_bal, 0) AS set_bal, 0.0 AS stl,
               IF(w.PFEmployee > 0, 1, 0) AS pensioner
        FROM PayOEMP e JOIN paywages w ON w.ECode = e.ECode {UCI}
        LEFT JOIN (SELECT ECode, SUM(PFCBalance) bal FROM PayCummOP GROUP BY ECode) op ON op.ECode = w.ECode
        LEFT JOIN (SELECT ECode, SUM(PFEmployee) pfe FROM paywages WHERE EDate <= :t GROUP BY ECode) cw
               ON cw.ECode = w.ECode
        LEFT JOIN (SELECT ECode, SUM(IF(Advance > 0, Advance, 0)) adv_g, SUM(IF(Advance < 0, -Advance, 0)) adv_r,
                          SUM(Advance) adv_bal FROM PaySalary WHERE EDate <= :t GROUP BY ECode) s ON s.ECode = w.ECode
        WHERE e.Active = 'Y' AND e.Grade = 'MILL-WORKMEN' AND w.EDate = :t AND w.CompCode = :c AND w.Location = :l
        ORDER BY LEFT(e.PFNo, 2), e.ECode""", _args(b, t))
    for d in det:
        d["k_pf"] = (d["pfno"] or "")[:2]
    sums = ["pf_gross", "pfc", "c_pfc", "pnc", "c_pnc", "coc", "c_coc", "pensioner", "adv_r", "adv_bal",
            "set_g", "set_bal", "stl"]
    cols = [_col("grp", "PF Series", width=100), _col("pfno", "PFNo", width=150), _col("ecode", "ECode", width=90),
            _col("card", "Rec.No", width=90), _col("ename", "EName", width=220), _num("pf_gross", "PF Gross", 100),
            _num("pfc", "PFC"), _num("c_pfc", "C.PFC", 100), _num("pnc", "PNC"), _num("c_pnc", "C.PNC", 100),
            _num("coc", "COC"), _num("c_coc", "C.COC", 100), _num("pensioner", "Pen-Members", 110),
            _num("adv_r", "Adv. Recv"), _num("adv_bal", "Adv. Bal"), _num("set_g", "SET Recv"),
            _num("set_bal", "SET Bal"), _num("stl", "STL Bal")]
    return cols, _layout(det, [lambda d: d["k_pf"]], sums, "grp", "pfno")


def record_on_statement(db, b, f, t, extra):
    """RecordOnStatement_NJB: hours and pay of the fortnight per active mill worker, with the
    department and shift of the latest attendance."""
    last = _last_attendance(db, b, t)
    det = _rows(db, f"""
        SELECT e.ECode AS ecode, e.CardNo AS card, e.EName AS ename, w.Work_HR + w.NS_HR AS work_hr,
               w.Holiday_HR AS hol_hr, w.STL_HR AS stl_hr, w.STL_Amt AS stl_amt, w.ROff AS roff,
               w.NetPayable AS net {_MILL} ORDER BY e.ECode""", _args(b, t))
    for d in det:
        a = last.get(d["ecode"], {})
        d.update(grp=d["ecode"], wdept=a.get("dept", ""), wshift=a.get("shift", ""))
    cols = [_col("grp", "ECode", width=100), _col("card", "Rec.No", width=90), _col("ename", "EName", width=220),
            _col("wdept", "W.Dept", width=80), _col("wshift", "W.Shift", width=80), _num("work_hr", "W.HR"),
            _num("hol_hr", "Hol.HR"), _num("stl_hr", "STL HR"), _num("stl_amt", "STL Amt", 100),
            _num("roff", "ROff", 80), _num("net", "NetPayable", 110)]
    return cols, det


# (field, header, kind) of the Wages Register, in the legacy print order (column by column, top to bottom).
_REGISTER = (
    ("card", "CardNo", "t"), ("ename", "EName", "t"), ("tp", "TP", "t"), ("ofbasic", "Basic Rate", "n"),
    ("cat", "Cat", "t"), ("gr", "GR", "t"), ("oda_rate", "DA Rate", "n"), ("ecode", "ECode", "t"),
    ("pf", "P/f", "t"), ("q", "Q", "t"), ("work_day", "Work Day", "n"), ("work_hr", "Work HR", "n"),
    ("esino", "ESINo", "t"), ("ns_hr", "NS HR", "n"), ("holiday_hr", "Hol HR", "n"), ("lost_hr", "Lost HR", "n"),
    ("stl_hr", "STL HR", "n"), ("fbasic_amt", "FBasic", "n"), ("vbasic_amt", "VBasic", "n"), ("da_amt", "DA", "n"),
    ("ns_amt", "NS Amt", "n"), ("holiday_amt", "Hol Amt", "n"), ("losthr_amt", "Lost Amt", "n"),
    ("atten_amt", "Atten Inc", "n"), ("pfearnadj", "PF Earn Adj", "n"), ("stl_amt", "STL Amt", "n"),
    ("def_wg", "Def Wg", "n"), ("pf_gross", "PF Gross", "n"), ("npfearnadj", "NPF Earn Adj", "n"),
    ("miscearn", "Misc Earn", "n"), ("incentive_amt", "Incentive", "n"), ("hrdeduction", "H Rent", "n"),
    ("wages_gross", "Wages Gross", "n"), ("pfcont", "PF Cont", "n"), ("esi_amt", "ESI", "n"),
    ("ptax_amt", "P.Tax", "n"), ("lwf_amt", "LWF", "n"), ("hra_amt", "HRA", "n"), ("stladv", "STL Adv", "n"),
    ("pfloancap", "PF Loan", "n"), ("advance", "Advance", "n"), ("set_adv", "SET Adv", "n"),
    ("handwg", "Hand Wg", "n"), ("pfloanint", "PF Loan Int", "n"), ("miscded", "Misc Ded", "n"),
    ("totaldeduction", "Total Ded", "n"), ("cpnc", "C.PNC", "n"), ("netpay", "Net Pay", "n"), ("roff", "ROff", "n"),
    ("netpayable", "Net Payable", "n"), ("ytd_days", "YTD Days", "n"), ("stl_day", "STL Day", "n"),
    ("stl_yr", "STL Yr", "n"), ("ytd_pfgross", "YTD PF Gross", "n"), ("ytd_pfemployee", "YTD PF Emp", "n"),
    ("ytd_pension", "YTD Pension", "n"), ("ytd_fpf", "YTD FPF", "n"), ("ytd_loanamt", "PF Loan Bal", "n"),
    ("ytd_intamt", "PF Int Bal", "n"), ("spl_bal", "Spl Bal", "n"),
)


def wages_register(db, b, f, t, extra):
    """WagesRegister_NJB: the fortnight's full wages line per active mill worker.
    ponytail: legacy TP = rate type (PayOWagesRate_OCP) of the latest attendance's department /
    occupation, else 'T'; here the same lookup on the latest daily_attendance (designation occu_code)."""
    last = _last_attendance(db, b, t)
    tp = {(r.DeptCode, r.OcpCode): r.RateType for r in db.execute(text(
        "SELECT DeptCode, OcpCode, MAX(RateType) RateType FROM PayOWagesRate_OCP GROUP BY DeptCode, OcpCode"))}
    det = _rows(db, f"""
        SELECT e.CardNo AS card, e.ECode AS ecode, e.EName AS ename, LEFT(e.EGroup, 2) AS cat, '' AS gr, '' AS pf,
               IF(w.HRDeduction > 0, 'H', '') AS q, w.Work_Day AS work_day, w.Work_HR AS work_hr, w.NS_HR AS ns_hr,
               w.NS_Amt AS ns_amt, w.Holiday_HR AS holiday_hr, w.Holiday_Amt AS holiday_amt, w.Lost_HR AS lost_hr,
               w.LostHR_Amt AS losthr_amt, w.FBasic_Amt AS fbasic_amt, w.VBasic_Amt AS vbasic_amt, w.DA_Amt AS da_amt,
               w.PFEarnAdj AS pfearnadj, w.STL_Amt AS stl_amt, w.PF_Gross AS pf_gross, w.NPFEarnAdj AS npfearnadj,
               w.MiscEarn AS miscearn, w.Incentive_Amt AS incentive_amt, w.PFEmployee AS pfcont,
               w.PTax_Amt AS ptax_amt, w.ESI_Amt AS esi_amt, w.HRA_Amt AS hra_amt, w.STLAdv AS stladv,
               w.PFLoanCap AS pfloancap, 0.0 AS set_adv, w.Advance AS advance, 0.0 AS handwg,
               w.TotalDeduction AS totaldeduction, w.FPF_Pension AS cpnc, w.ROff AS roff, w.YTD_Days AS ytd_days,
               0.0 AS stl_day, 0.0 AS stl_yr, w.YTD_PFGross AS ytd_pfgross, w.YTD_LoanAmt AS ytd_loanamt,
               w.YTD_IntAmt AS ytd_intamt, 0.0 AS spl_bal, w.OFBasic AS ofbasic, w.ODA_Rate AS oda_rate,
               e.ESINo AS esino, w.STL_HR AS stl_hr, w.Atten_Amt AS atten_amt, 0.0 AS def_wg,
               w.HRDeduction AS hrdeduction, w.Wages_Gross AS wages_gross, w.LWF_Amt AS lwf_amt,
               w.PFLoanInt AS pfloanint, 0.0 AS miscded, w.NetPay AS netpay, w.NetPayable AS netpayable,
               w.YTD_PFEmployee AS ytd_pfemployee, w.YTD_Pension AS ytd_pension, w.YTD_FPF AS ytd_fpf
        {_MILL} ORDER BY e.ECode""", _args(b, t))
    for d in det:
        a = last.get(d["ecode"])
        d["tp"] = tp.get((a["dept"], a["ocp"]), "T") if a else "T"
    cols = [_col(k, h, width=90) if kind == "t" else _num(k, h, 95) for k, h, kind in _REGISTER]
    cols[1]["width"] = 200
    return cols, det


# (field, header) of the department summary: hours / counts, earnings, then deductions, as printed.
_SUMMARY = (
    ("ecount", "No. of Payslip"), ("work_hr", "Wrk Hrs"), ("ns_hr", "NS HR"), ("holiday_hr", "Hol Hrs"),
    ("lost_hr", "Lost Hrs"), ("stl_hr", "STL Hrs"), ("stl_days", "STL Days"), ("ot_hr", "OT Hrs"),
    ("pfmember", "PF Members"), ("pnmember", "Pen Members"), ("esimember", "ESI Members"),
    ("fbasic_amt", "Fix Basic"), ("vbasic_amt", "Vr Basic"), ("da_amt", "F.D.A."), ("ns_amt", "NS Allow"),
    ("holiday_amt", "Holiday Wages"), ("losthr_amt", "Lost Wages"), ("stl_amt", "STL Wages"),
    ("pfearnadj", "Adj. PF"), ("def_wg", "Def. Wages"), ("pf_gross", "PF Gross"), ("pfgross", "PF Gross (PF Mem)"),
    ("pngross", "Pen Gross"), ("esigross", "ESI Gross"), ("fringe1", "Fringe Rate / Day (Gross)"),
    ("fringe2", "Fringe Rate / Day (PF Gross)"), ("miscearn", "Misc Earn"), ("atten_amt", "Attdn Inc"),
    ("npfearnadj", "Adj N.P.F."), ("ot_amt", "OT Amount"), ("incentive_amt", "Incentive"), ("hra_amt", "HRA"),
    ("wages_gross", "Gross Wgs"), ("netpay", "Net Pay"), ("bf", "BF"), ("cf", "CF"), ("roff", "R/Off"),
    ("netpayable", "Net Payable"), ("pfcont", "PF Cont (PF Mem)"), ("pncont", "Pen Cont"),
    ("esicont", "ESI Cont"), ("coccont", "COC Cont"), ("pfemployee", "PF Cont"), ("esi_amt", "ESI"),
    ("lwf_amt", "LWF"), ("stladv", "STL Adv"), ("advance", "Advance"), ("spladvance", "Spl Advance"),
    ("pfloancap", "PF Loan"), ("pfln_int", "PF Loan Int"), ("hrdeduction", "H Rent"), ("ptax_amt", "P.Tax"),
    ("handwg", "Hand Wages"), ("setadv", "SET Adv"), ("electricity", "Electric"), ("totaldeduction", "Total Ded."),
)


def _fringe(row: dict) -> None:
    """Legacy formulas: rate per day = amount / ((work + NS + holiday + STL hours) / 8)."""
    days = (row.get("work_hr", 0) + row.get("ns_hr", 0) + row.get("holiday_hr", 0) + row.get("stl_hr", 0)) / 8
    row["fringe1"] = round(row.get("wages_gross", 0) / days, 2) if days else 0.0
    row["fringe2"] = round(row.get("pf_gross", 0) / days, 2) if days else 0.0


def wages_dept_summary(db, b, f, t, extra):
    """WagesRegisterSummary_NJB: the fortnight's mill-worker payroll per department plus the grand
    summary, OT wages (paywagesot) included."""
    det = _rows(db, f"""
        SELECT w.DeptCode AS dept_code,
               IFNULL((SELECT MAX(DeptName) FROM ODPT WHERE DeptCode {UCI} = w.DeptCode), '') AS dept_name,
               COUNT(*) AS ecount, SUM(w.Work_HR) AS work_hr, SUM(w.NS_HR) AS ns_hr, SUM(w.Holiday_HR) AS holiday_hr,
               SUM(w.Lost_HR) AS lost_hr, SUM(w.STL_HR) AS stl_hr, SUM(w.STL_HR) / 8 AS stl_days,
               SUM(w.VBasic_Amt) AS vbasic_amt, SUM(w.FBasic_Amt) AS fbasic_amt, SUM(w.DA_Amt) AS da_amt,
               SUM(w.NS_Amt) AS ns_amt, SUM(w.Holiday_Amt) AS holiday_amt, SUM(w.LostHR_Amt) AS losthr_amt,
               SUM(w.STL_Amt) AS stl_amt, SUM(w.PFEarnAdj) AS pfearnadj, SUM(w.Atten_Amt) AS atten_amt,
               0.0 AS def_wg, SUM(w.PF_Gross) AS pf_gross, SUM(w.HRA_Amt) AS hra_amt,
               SUM(w.NPFEarnAdj) AS npfearnadj, SUM(w.Incentive_Amt) AS incentive_amt,
               SUM(w.BeamChange_Amt + w.Oil_Amt + w.MiscEarn) AS miscearn,
               SUM(w.Wages_Gross) + SUM(IFNULL(ot.amt, 0)) AS wages_gross,
               SUM(w.NetPay) + SUM(IFNULL(ot.amt, 0)) - SUM(IFNULL(ot.esi, 0)) AS netpay,
               SUM(w.BF) AS bf, SUM(w.CF) AS cf, SUM(w.ROff) + SUM(IFNULL(ot.roff, 0)) AS roff,
               SUM(w.NetPayable) + SUM(IFNULL(ot.payable, 0)) AS netpayable,
               SUM(w.PFEmployee) AS pfemployee, SUM(w.ESI_Amt) + SUM(IFNULL(ot.esi, 0)) AS esi_amt,
               SUM(w.LWF_Amt) AS lwf_amt, SUM(w.PFLoanCap) AS pfloancap, SUM(w.STLAdv) AS stladv,
               SUM(w.Advance) AS advance, SUM(w.SplAdvance) AS spladvance, SUM(w.Pension) AS pension,
               SUM(w.PTax_Amt) AS ptax_amt, SUM(w.HRDeduction) AS hrdeduction, SUM(w.PFLoanInt) AS pfln_int,
               0.0 AS handwg, 0.0 AS setadv, SUM(w.Electricity) AS electricity,
               SUM(w.TotalDeduction) + SUM(IFNULL(ot.esi, 0)) AS totaldeduction,
               SUM(w.PFEmployee > 0) AS pfmember, SUM(IF(w.PFEmployee > 0, w.PF_Gross, 0)) AS pfgross,
               SUM(IF(w.PFEmployee > 0, w.PFEmployee, 0)) AS pfcont, SUM(w.Pension > 0) AS pnmember,
               SUM(IF(w.Pension > 0, w.Pension_Gross, 0)) AS pngross, SUM(IF(w.Pension > 0, w.Pension, 0)) AS pncont,
               SUM(IF(w.PFEmployee > 0, w.CoC, 0)) AS coccont, SUM(w.ESI_Amt > 0) AS esimember,
               SUM(IF(w.ESI_Amt > 0, w.ESI_Gross, 0)) + SUM(IFNULL(ot.amt, 0)) AS esigross,
               SUM(w.ESI_Amt) + SUM(IFNULL(ot.esi, 0)) AS esicont,
               SUM(IFNULL(ot.hr, 0)) AS ot_hr, SUM(IFNULL(ot.amt, 0)) AS ot_amt
        FROM paywages w
        -- the paywagesot mirror keys OT by eb_id (legacy ECode -> emp_code)
        LEFT JOIN (SELECT o.emp_code AS ECode, SUM(x.Work_HR) hr, SUM(x.Amount) amt, SUM(x.ESIAmt) esi,
                          SUM(x.ROff) roff, SUM(x.PayableAmt) payable
                   FROM paywagesot x JOIN hrms_ed_official_details o ON o.eb_id = x.eb_id
                   WHERE x.FNEDate = :t GROUP BY o.emp_code) ot
               ON ot.ECode {UCI} = w.ECode
        WHERE w.Grade = 'MILL-WORKMEN' AND w.EDate = :t AND w.CompCode = :c AND w.Location = :l
        GROUP BY w.DeptCode ORDER BY w.DeptCode""", _args(b, t))
    for d in det:
        d["dept"] = f"{d['dept_code']} - {d['dept_name']}"
        _fringe(d)
    sums = [k for k, _ in _SUMMARY if not k.startswith("fringe")]
    rows = _layout(det, [], sums, "dept", "ecount")
    if rows:
        _fringe(rows[-1])  # grand fringe = summed amount / summed days (legacy Fringe11 / Fringe22)
    return [_col("dept", "Department", width=230), *[_num(k, h, 105) for k, h in _SUMMARY]], rows


def _stl(db, b, t, paid: bool):
    """STLChecklist_NJB / STLPaymentCheckList_NJB: STL leave entered for (or paid in) the FNE date."""
    join = "JOIN PayOSTL p ON p.BaseDocEntry = j.DocEntry" if paid else ""
    pay_in = "p.FNEDate" if paid else "j.FNEDate"
    det = _rows(db, f"""
        SELECT j.ECode AS ecode, j.EName AS ename, j.DeptCode AS dept, e.SubGroup AS gr, j.FromDate AS from_date,
               j.ToDate AS to_date, {pay_in} AS pay_in, j.STLDays AS days
        FROM PayJOLeave j {join} JOIN PayOEMP e ON e.ECode = j.ECode {UCI}
        WHERE j.LeaveType = 'STL Leave' AND {pay_in} = :t ORDER BY j.ECode""", {"t": t})
    for i, d in enumerate(det, start=1):
        d.update(slno=i, grp=str(i), from_date=_dmy(d["from_date"]), to_date=_dmy(d["to_date"]),
                 pay_in=_dmy(d["pay_in"]))
    cols = [_col("grp", "SlNo", width=80), _col("ecode", "ECode", width=90), _col("ename", "EName", width=220),
            _col("dept", "DEPT", width=70), _col("gr", "GR", width=140), _col("from_date", "STL From", width=105),
            _col("to_date", "STL To", width=105), _col("pay_in", "PAY IN", width=105), _num("days", "STL Days")]
    return cols, _layout(det, [], ["days"], "grp", "ecode")


def stl_checklist(db, b, f, t, extra):
    return _stl(db, b, t, paid=False)


def stl_payment_checklist(db, b, f, t, extra):
    return _stl(db, b, t, paid=True)


def wages_pay_slip(db, b, f, t, extra):
    """WAGES PAY SLIP (FrmSmartEyeReportMulti2.WagesPaySlip_NJB): the fortnight's slips as the
    pre-printed-stationery text file, with one grid line per slip."""
    pid = db.execute(text("SELECT ID FROM pay_period WHERE branch_id = :b AND TO_DATE = :t AND code LIKE 'P%' "
                          "ORDER BY ID LIMIT 1"), {"b": b, "t": t}).scalar()
    if not pid:
        raise HTTPException(status_code=400, detail=f"No wages period ends on {_dmy(t)}")
    p, rows = wages_payslip_rows(db, b, pid)
    det = [{"sno": r["SNo"], "card": r["RecNo"], "ecode": r["CNo"], "ename": r["EName"], "ocp": r["OcpDptSft"],
            "cpq": r["CPQ"], "work_hr": float(r["Work_HR"] or 0), "gross": float(r["TotalGross"] or 0),
            "ded": float(r["TotalDeduction"] or 0), "net": float(r["NetPayable"] or 0)} for r in rows]
    cols = [_num("sno", "S.No", 70), _col("card", "Rec.No", width=90), _col("ecode", "ECode", width=90),
            _col("ename", "EName", width=200), _col("ocp", "Ocp/Dpt/Sft", width=110), _col("cpq", "C/P/Q", width=90),
            _num("work_hr", "Work HR"), _num("gross", "Gross", 100), _num("ded", "Deduction", 100),
            _num("net", "Net Payable", 110)]
    download = {"filename": f"PAYSLIP_{p['code']}_{p['to_date'].isoformat()}.TXT", "text": payslip_text(rows)} if rows else None
    return cols, _layout(det, [], ["work_hr", "gross", "ded", "net"], "ename", "card"), download


def bonus_slip_lines(r: dict) -> list[str]:
    """One bonus slip, 16 lines, as legacy BonusPaySlip_NJB prints it (Print value, SPC(width - Len))."""
    amt = _fmt(r["PayableBNSAmt"], 0)
    bar = " " * 54 + "|"
    return [
        "", "", "",
        str(r["CompName"] or "").ljust(54) + "|",
        bar,
        str(r["RptName"] or "").ljust(54) + "|",
        "=" * 54 + "|",
        "DPT SH REC-NO CN-NO. DAYS  PF-GROSS ELG-GROSS BON-AMT |",
        bar,
        (str(r["DeptCode"] or "").ljust(4) + str(r["WShift"] or "").ljust(2) + " " + str(r["RecNo"] or "").ljust(7)
         + str(r["ECode"] or "").ljust(7) + _fmt(r["TotalDays"], 1).rjust(5) + " " + _fmt(r["TotalPFG"]).rjust(9)
         + " " + _fmt(r["TotalBnsG"]).rjust(7) + " " + amt.rjust(7) + " " + "|"),
        bar,
        "NAME : " + str(r["EName"] or "").ljust(25) + " NETT : " + amt.rjust(7) + "/-     |",
        bar,
        "BANK A/C NO.-" + str(r["AccNo"] or "").rjust(15) + " " * 5 + "IFSC-" + str(r["IFSC"] or "").rjust(15) + " |",
        bar,
        "-" * 55,
    ]


def bonus_slip_text(rows: list[dict]) -> str:
    """All bonus slips, a form feed after every fourth.
    ponytail: legacy also feeds 54 blank lines when PB changes; PB is the bonus year the query filters
    on, so it never changes and that branch is left out."""
    out: list[str] = []
    for i, r in enumerate(rows, start=1):
        out.extend(bonus_slip_lines(r))
        if i % 4 == 0:
            out.append(PAGE_SKIP)
    return "".join(line + LINE_END for line in out)


def bonus_pay_slip(db, b, f, t, extra):
    """BONUS PAY SLIP (FrmSmartEyeReportMulti2.BonusPaySlip_NJB, query TBLF5 'BonusSlip'): the
    processed worker bonus of the accounting year From..To ('2025 - 2026' from 01/04/2025..31/03/2026)."""
    fy = f"{f.year} - {t.year}"
    raw = [dict(r._mapping) for r in db.execute(text(
        "SELECT * FROM PayBonusProcessed_Worker WHERE PB = :fy AND PayableBNSAmt > 0 "
        "ORDER BY DeptCode, WShift, ECode"), {"fy": fy})]
    det = [{"k_dept": f"DEPT : {r['DeptCode']}", "wshift": r["WShift"], "card": r["RecNo"], "ecode": r["ECode"],
            "ename": r["EName"], "days": float(r["TotalDays"] or 0), "pfg": float(r["TotalPFG"] or 0),
            "bnsg": float(r["TotalBnsG"] or 0), "amt": float(r["PayableBNSAmt"] or 0), "acc": r["AccNo"],
            "ifsc": r["IFSC"]} for r in raw]
    cols = [_col("grp", "Dept", width=110), _col("wshift", "SH", width=60), _col("card", "Rec-No", width=90),
            _col("ecode", "CN-No.", width=90), _col("ename", "Name", width=220), _num("days", "Days"),
            _num("pfg", "PF-Gross", 110), _num("bnsg", "Elg-Gross", 110), _num("amt", "Bon-Amt", 100),
            _col("acc", "Bank A/C", width=140), _col("ifsc", "IFSC", width=120)]
    download = {"filename": f"BONUSSLIP_{f.year}_{t.year}.TXT", "text": bonus_slip_text(raw)} if raw else None
    return cols, _layout(det, [lambda d: d["k_dept"]], ["days", "pfg", "bnsg", "amt"], "grp", "card"), download


SHIFTS = [{"value": s, "label": s} for s in ("A", "B", "C")]

# key = last segment of the seeded menu path hrms/nbjclreports/wages/<key>
REPORTS: dict[str, dict[str, dict]] = {"wages": {
    "workerDailyPaysheet": {"title": "Worker Daily PaySheet", "dates": "single", "span": "day",
                            "extra": {"label": "Shift", "options": SHIFTS}, "build": daily_paysheet},
    "workersDeptWiseListOt": {"title": "WORKERS DEPT-WISE LIST [ OT ]", "dates": "range", "extra": None,
                              "build": dept_wise_list_ot},
    "lwfStatement": {"title": "LWF STATEMENT", "dates": "range", "extra": None, "build": lwf_statement},
    "pensionBalanceStatement": {"title": "PENSION BALANCE STATEMENT", "dates": "range", "extra": None,
                                "build": pension_balance},
    "workersPfContAdvBalanceStatement": {"title": "WORKERS PF CONT / ADV BALANCE STATEMENT", "dates": "single",
                                         "extra": None, "build": pf_cont_adv_balance},
    "recordOnStatement": {"title": "RECORD ON STATEMENT", "dates": "single", "extra": None,
                          "build": record_on_statement},
    "wagesRegister": {"title": "WAGES REGISTER", "dates": "single", "extra": None, "build": wages_register},
    "wagesDepartmentWiseSummary": {"title": "WAGES DEPARTMENT WISE SUMMARY", "dates": "single", "extra": None,
                                   "build": wages_dept_summary},
    "stlChecklist": {"title": "STL Checklist", "dates": "single", "extra": None, "build": stl_checklist},
    "stlPaymentChecklist": {"title": "STL Payment Checklist", "dates": "single", "extra": None,
                            "build": stl_payment_checklist},
    "wagesPaySlip": {"title": "WAGES PAY SLIP", "dates": "single", "extra": None, "build": wages_pay_slip},
    "bonusPaySlip": {"title": "BONUS PAY SLIP", "dates": "range", "span": "month", "extra": None,
                     "build": bonus_pay_slip},
}}


if __name__ == "__main__":
    # self-check of the bonus slip layout (no database)
    slip = bonus_slip_lines({"CompName": "NORTHBROOK JUTE COMPANY LTD", "RptName": "BONUS PAYSLIP FOR YEAR 2025 - 2026",
                             "DeptCode": "04", "WShift": "A", "RecNo": "HS1546", "ECode": "041216", "TotalDays": 224,
                             "TotalPFG": 103668.41, "TotalBnsG": 60331.83, "PayableBNSAmt": 5025,
                             "EName": "SONATON MODAK", "AccNo": "22348614173", "IFSC": "ALLA0211767"})
    assert len(slip) == 16 and len(slip[11]) == len(slip[13]) == 55, [len(s) for s in slip]
    # a value wider than its column pushes the rest right (ELG-GROSS 60331.83 is 8 wide in 7)
    assert slip[9] == "04  A  HS1546 041216 224.0 103668.41 60331.83    5025 |", slip[9]
    assert bonus_slip_text([{**{"CompName": "", "RptName": "", "DeptCode": "", "WShift": "", "RecNo": "", "ECode": "",
                                 "TotalDays": 0, "TotalPFG": 0, "TotalBnsG": 0, "PayableBNSAmt": 0, "EName": "",
                                 "AccNo": "", "IFSC": ""}}] * 4).count(PAGE_SKIP) == 1
    print("ok")
