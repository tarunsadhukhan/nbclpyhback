"""NBJCL Reports — Provident Fund Reports + Wages-Monthly Reports. See src/hrms/nbjclreports/__init__.py
for the spec shape.

Provident Fund Reports read the mirrored legacy PF ledger paypftrandtl (PayPFTranDTL: one row per
employee and posting, P = 1 opening, 2 wages / salary, 3 interest, 4 closing, 5 NR loan, 7 arrear),
as the legacy procs RPT_PayPFTranDTL / RPT_PF_EmpWiseMonthWise / RPT_PF_EmpWiseStatementSumm did;
the procs' #RPT temp tables are rebuilt as Python lists. Their MultiParameter ECode list was never
filled by the menu, so it is left out; the Grade filter is the report's `extra`.

Wages-Monthly Reports are the monthly statutory statements (legacy Excel_ECRStatement /
Excel_ESIStatement exported to Excel, PTaxSummary_ANG printed) over paywages (wages + staff salary
rows) for the month of the To date; the page's Excel export replaces the legacy Excel file.

ponytail: paypftrandtl holds FY 2022-23 only (legacy PayPFTranDTL is the same: the PF ledger was not
posted after 31/03/2023), so the PF reports show that year until someone posts the later years.
"""
import collections
import math
from datetime import date

from sqlalchemy import bindparam
from sqlalchemy.sql import text

from src.hrms.nbjclAttendanceReports import _col, _dmy, _layout, _num
from src.hrms.wagesSalaryProcess import UCI, _r, _scope

GRADE_EXTRA = {"label": "Grade", "options": [{"value": "MILL-WORKMEN", "label": "MILL-WORKMEN"},
                                             {"value": "STAFF", "label": "STAFF"}]}


def _f(v) -> float:
    return float(v or 0)


def _pf(db, b, f: date, t: date, grade: str, no_pf=("", "N/A")) -> list[dict]:
    """PF ledger rows of the company posted (ToDate) in the period, with a PF number (not in `no_pf`)."""
    comp, loc = _scope(b)
    rows = db.execute(text("""
        SELECT * FROM paypftrandtl
        WHERE CompCode = :c AND Location = :l AND ToDate BETWEEN :f AND :t AND PFNo NOT IN :no
          AND (:g = '' OR Grade = :g)
        ORDER BY PFNo, ToDate, P""").bindparams(bindparam("no", expanding=True)),
                      {"c": comp, "l": loc, "f": f, "t": t, "g": grade, "no": list(no_pf)})
    return [dict(r._mapping) for r in rows]


def _oemp(db, b) -> dict[str, dict]:
    """Legacy employee master (PayOEMP) by ECode."""
    comp, _ = _scope(b)
    rows = db.execute(text("""SELECT ECode, OrgECode, EName, DoJ, Grade, EGroup, PFNo FROM PayOEMP
                              WHERE CompCode = :c"""), {"c": comp})
    return {r.ECode: dict(r._mapping) for r in rows}


def _sort_pf(pf) -> tuple:
    return (pf is not None, (pf or "").upper())


# ─── Provident Fund Reports ────────────────────────────────────────────────

TRAN_NUMS = ["OP_PF_EMP", "OP_VPF_EMP", "OP_PF_Comp", "PF_EMP", "VPF_EMP", "PF_Comp", "NR_PF_EMP", "NR_VPF_EMP",
             "NR_PF_Comp", "INT_PF_EMP", "INT_VPF_EMP", "INT_PF_Comp", "Cumm_PF_EMP", "Cumm_VPF_EMP", "Cumm_PF_Comp"]


def pf_transaction_details(db, b, f, t, extra):
    """PayPFTranDTL_NBJCL (proc RPT_PayPFTranDTL): opening, contribution, NR loan, interest and closing
    per employee and month, grouped by PF number."""
    emp = _oemp(db, b)
    agg: dict = {}
    for r in _pf(db, b, f, t, extra, no_pf=("",)):  # legacy kept PF No. N/A here
        if r["Grade"] not in ("MILL-WORKMEN", "STAFF"):
            continue
        k = (r["PFNo"], r["ECode"], r["FYear"], r["ToDate"].year, r["ToDate"].month)
        line = agg.setdefault(k, {"month": r["ToDate"].strftime("%b").upper() + r["ToDate"].strftime(" - %y"),
                                  "ename": r["EName"], **dict.fromkeys(TRAN_NUMS, 0.0)})
        for c in TRAN_NUMS:
            line[c] += _f(r[c])
    det, heads = [], {}
    for k in sorted(agg, key=lambda k: (_sort_pf(k[0]), k[3], k[4], k[1])):
        pf, ecode = k[0], k[1]
        e = emp.get(ecode, {})
        # the Crystal group (PF No.) header: the first employee of the PF number
        heads.setdefault(pf, f"EMPLOYEE - {ecode} {e.get('EName') or agg[k]['ename'] or ''}   PF NO - {pf}   "
                             f"CAT - {e.get('EGroup') or ''}   JOINING DATE - {_dmy(e.get('DoJ'))}")
        det.append({"k_pf": heads[pf], **agg[k]})
    cols = [_col("grp", "Employee / Month", width=150),
            *[_num(c, h, 95) for c, h in zip(TRAN_NUMS, (
                "Op PF Emp", "Op VPF Emp", "Op PF Comp", "PF Emp", "VPF Emp", "PF Comp", "NR PF Emp", "NR VPF Emp",
                "NR PF Comp", "Int PF Emp", "Int VPF Emp", "Int PF Comp", "Cl PF Emp", "Cl VPF Emp", "Cl PF Comp"))]]
    for d in det:
        d["grp"] = d["month"]
    return cols, _layout(det, [lambda d: d["k_pf"]], [], "grp", "month", grand=False, footers=False)


CARD_NUMS = ["PF_Emp", "NR_Emp", "PF_Comp", "NR_Comp", "VPF", "Advance", "RepayAdv", "CashAdj", "AdvBal"]


def pf_card(db, b, f, t, extra):
    """PF_EmpWiseMonthWise_NBJCL (proc RPT_PF_EmpWiseMonthWise): the PF card — B/F, each month's
    contribution, sub total, C/B, interest and C/F per PF number."""
    emp = _oemp(db, b)
    src = _pf(db, b, f, t, extra)
    rpt: list[dict] = []

    def add(p, ttype, pf, ecode, ename, mname, wy, wm, **v):
        rpt.append({"P": p, "TType": ttype, "PFNo": pf, "ECode": ecode, "EName": ename, "MName": mname,
                    "WYear": int(wy or 0), "WMonth": int(wm or 0), **dict.fromkeys(CARD_NUMS, 0.0), **v})

    for r in src:
        if r["P"] == 1:  # PF interest opening balance
            add(1, "B/F", r["PFNo"], r["ECode"], r["EName"], f.strftime("%B"), r["WYear"], r["WMonth"],
                PF_Emp=_f(r["OP_PF_EMP"]), NR_Emp=_f(r["NR_PF_EMP"]), PF_Comp=_f(r["OP_PF_Comp"]),
                NR_Comp=_f(r["NR_PF_Comp"]), VPF=_f(r["OP_VPF_EMP"]), Advance=_f(r["OP_PF_LOAN"]),
                RepayAdv=_f(r["REPAY_PF_LOAN"]), CashAdj=_f(r["ADJ_PF_LOAN"]))
    tran: dict = {}
    for r in src:
        if r["P"] in (2, 5, 7):  # wages / salary, NR loan, arrear: one line per month
            k = (r["PFNo"], r["ECode"], r["EName"], r["ToDate"].strftime("%B"), r["WYear"], r["WMonth"])
            g = tran.setdefault(k, {**dict.fromkeys(CARD_NUMS, 0.0), "AdvBal": None})
            g["PF_Emp"] += _f(r["PF_EMP"])
            g["NR_Emp"] -= _f(r["NR_PF_EMP"])
            g["PF_Comp"] += _f(r["PF_Comp"])
            g["NR_Comp"] -= _f(r["NR_PF_Comp"])
            g["VPF"] += _f(r["VPF_EMP"])
            g["Advance"] += _f(r["NEW_PF_LOAN"])
            g["RepayAdv"] += _f(r["REPAY_PF_LOAN"])
            g["CashAdj"] += _f(r["ADJ_PF_LOAN"])
            g["AdvBal"] = _f(r["CL_PF_LOAN"]) if g["AdvBal"] is None else min(g["AdvBal"], _f(r["CL_PF_LOAN"]))
    for k, g in tran.items():
        add(2, "TRANSACTION", *k, **g)

    def per_emp(ttypes):
        out: dict = collections.OrderedDict()
        for x in rpt:
            if x["TType"] in ttypes:
                s = out.setdefault((x["ECode"], x["EName"]), dict.fromkeys(CARD_NUMS, 0.0))
                for c in CARD_NUMS:
                    s[c] += x[c]
        return out

    end = (t.strftime("%B"), t.year, t.month)
    for (ecode, ename), s in per_emp(("TRANSACTION",)).items():
        add(3, "SUB TOTAL", None, ecode, ename, *end, **{**s, "AdvBal": 0.0})
    for (ecode, ename), s in per_emp(("B/F", "SUB TOTAL")).items():
        # legacy C/B: PF less NR column (the transaction NR is negative, so it adds back)
        add(4, "C/B", None, ecode, ename, *end, **{**s, "PF_Emp": s["PF_Emp"] - s["NR_Emp"], "NR_Emp": 0.0,
                                                    "PF_Comp": s["PF_Comp"] - s["NR_Comp"], "NR_Comp": 0.0,
                                                    "AdvBal": 0.0})
    for r in src:
        # ponytail: legacy took interest only when a Grade was picked (Grade = @Grade); here All includes it
        if r["P"] == 3:
            add(5, "INTEREST", None, r["ECode"], r["EName"], *end, PF_Emp=_f(r["INT_PF_EMP"]),
                PF_Comp=_f(r["INT_PF_Comp"]), VPF=_f(r["INT_VPF_EMP"]))
        elif r["P"] == 4:
            add(6, "C/F", None, r["ECode"], r["EName"], *end, PF_Emp=_f(r["Cumm_PF_EMP"]), NR_Emp=_f(r["NR_PF_EMP"]),
                PF_Comp=_f(r["Cumm_PF_Comp"]), NR_Comp=_f(r["NR_PF_Comp"]), VPF=_f(r["Cumm_VPF_EMP"]),
                Advance=_f(r["NEW_PF_LOAN"]), RepayAdv=_f(r["REPAY_PF_LOAN"]), CashAdj=_f(r["ADJ_PF_LOAN"]))
    for x in rpt:  # PF number from the employee master, as legacy
        if x["ECode"] in emp:
            x["PFNo"] = emp[x["ECode"]]["PFNo"] or ""
    # a zero B/F, INTEREST and C/F line for every employee that has none
    for p, ttype, (mn, wy, wm) in ((1, "B/F", (f.strftime("%B"), f.year, f.month)), (5, "INTEREST", end),
                                   (6, "C/F", end)):
        have = {x["ECode"] for x in rpt if x["P"] == p}
        for pf, ecode, ename in dict.fromkeys((x["PFNo"], x["ECode"], x["EName"]) for x in rpt
                                              if x["ECode"] not in have):
            add(p, ttype, pf, ecode, ename, mn, wy, wm)
    slno = {pf: i for i, pf in enumerate(sorted({x["PFNo"] for x in rpt}, key=_sort_pf), start=1)}
    det = [x for x in rpt if x["PFNo"]]
    det.sort(key=lambda x: (_sort_pf(x["PFNo"]), x["P"], x["ECode"], x["WYear"], x["WMonth"]))
    for x in det:
        x["k_pf"] = f"P.F. No. {x['PFNo']}   Name : {x['EName'] or ''}   SRL NO: {slno[x['PFNo']]}"
        x["grp"] = x["MName"] if x["TType"] == "TRANSACTION" else x["TType"]
    cols = [_col("grp", "P.F. No. / Month", width=150), _num("PF_Emp", "Employees Subscript", 110),
            _num("NR_Emp", "Non-Refun Withdrawl", 110), _num("PF_Comp", "Employer Contribut", 110),
            _num("NR_Comp", "Non-Refun Withdrawl (Comp)", 120), _num("VPF", "Volunta Contrib", 100),
            _num("Advance", "Advance + Int", 100), _num("RepayAdv", "Re-pay of Adv", 100),
            _num("CashAdj", "Cash Real", 90), _num("AdvBal", "Advance Balance", 100)]
    return cols, _layout(det, [lambda d: d["k_pf"]], [], "grp", "TType", grand=False, footers=False)


SLIP_LABELS = {1: "1.  OPENING", 2: "2.  NON-REFUNDABLE WITHDRAWL", 3: "3.  NET OPENING BALANCE [ 1 - 2 ]",
               4: "4.  CONTRIBUTION DURING THE YEAR", 5: "5.  SUB-TOTAL [ 3 + 4 ]", 6: "6.  INTEREST FOR THE YEAR",
               7: "7.  CLOSING BALANCE"}


def pf_slip(db, b, f, t, extra):
    """PF_EmpWiseStatementSumm_NBJCL (proc RPT_PF_EmpWiseStatementSumm): the PF slip — opening, NR
    withdrawal, contribution, interest and closing (own / company / voluntary) per PF number."""
    src = _pf(db, b, f, t, extra)
    rpt: list[dict] = []

    def add(p, key, own=0.0, comp=0.0, vol=0.0, total=None, rate=0.0):
        rpt.append({"P": p, "PFNo": key[0], "OrgECode": key[1], "ECode": key[2], "EName": key[3], "own": own,
                    "comp": comp, "vol": vol, "total": own + comp + vol if total is None else total,
                    "rate": _f(rate)})

    def key(r):
        return r["PFNo"], r["OrgECode"], r["ECode"], r["EName"]

    def sum_of(ps, k_fn=lambda x: (x["PFNo"], x["OrgECode"], x["ECode"], x["EName"])):
        out: dict = collections.OrderedDict()
        for x in rpt:
            if x["P"] in ps:
                s = out.setdefault(k_fn(x), [0.0, 0.0, 0.0, 0.0])
                s[0] += x["own"]; s[1] += x["comp"]; s[2] += x["vol"]; s[3] = max(s[3], x["rate"])
        return out

    for r in src:
        if r["P"] == 1:
            add(1, key(r), _f(r["OP_PF_EMP"]), _f(r["OP_PF_Comp"]), _f(r["OP_VPF_EMP"]), rate=r["INT_Rate"])
    for r in src:
        if r["P"] == 5:  # legacy: own and company negated, voluntary and total not
            add(2, key(r), -_f(r["NR_PF_EMP"]), -_f(r["NR_PF_Comp"]), _f(r["NR_VPF_EMP"]),
                _f(r["NR_PF_EMP"]) + _f(r["NR_PF_Comp"]) + _f(r["NR_VPF_EMP"]), r["INT_Rate"])
    for k, s in sum_of((1, 2)).items():
        add(3, k, s[0], s[1], s[2], rate=s[3])
    contrib: dict = collections.OrderedDict()
    for r in src:
        if r["P"] in (2, 7):
            s = contrib.setdefault((*key(r), r["INT_Rate"]), [0.0, 0.0, 0.0])
            s[0] += _f(r["PF_EMP"]); s[1] += _f(r["PF_Comp"]); s[2] += _f(r["VPF_EMP"])
    for k, s in contrib.items():
        add(4, k[:4], *s, rate=k[4])
    for k, s in sum_of((3, 4)).items():
        add(5, k, s[0], s[1], s[2], rate=s[3])
    for r in src:
        # ponytail: legacy required a Grade (Grade = @Grade, blank gave an empty slip); here All = every grade
        if r["P"] == 3:
            add(6, key(r), _f(r["INT_PF_EMP"]), _f(r["INT_PF_Comp"]), _f(r["INT_VPF_EMP"]), rate=r["INT_Rate"])
        elif r["P"] == 4:
            add(7, key(r), _f(r["Cumm_PF_EMP"]), _f(r["Cumm_PF_Comp"]), _f(r["Cumm_VPF_EMP"]), rate=r["INT_Rate"])
    for p in range(1, 8):  # a zero line for every step an employee has none of
        have = {x["ECode"] for x in rpt if x["P"] == p}
        for k in dict.fromkeys((x["PFNo"], x["OrgECode"], x["ECode"], x["EName"]) for x in rpt
                               if x["ECode"] not in have):
            add(p, k)
    groups: dict = collections.OrderedDict()
    for x in sorted(rpt, key=lambda x: (_sort_pf(x["PFNo"]), x["P"])):
        groups.setdefault(x["PFNo"], []).append(x)
    out = []
    for slno, (pf, lines) in enumerate(groups.items(), start=1):
        out.append({"grp": f"P.F. Account No. {pf}   Name : {lines[0]['EName'] or ''}   SRL NO: {slno}"})
        out += [{"lbl": SLIP_LABELS[x["P"]], "own": x["own"], "comp": x["comp"], "vol": x["vol"], "total": x["total"]}
                for x in lines]
        # group footer: interest rate and the last line's (closing) total balance
        out.append({"lbl": "Total", "rate": max(x["rate"] for x in lines), "total": lines[-1]["total"]})
    cols = [_col("grp", "P.F. Account No.", width=120), _col("lbl", "Particulars", width=290),
            _num("own", "Own Details", 110), _num("comp", "Company Details", 120), _num("vol", "Voluntary Details", 120),
            _num("total", "Total", 110), _num("rate", "Interest Rate %", 110)]
    return cols, out


# ─── Wages-Monthly Reports ─────────────────────────────────────────────────


def _month(t: date) -> dict:
    return {"y": str(t.year), "m": str(t.month), "fdt": t.replace(day=1), "t": t}


def ecr_statement(db, b, f, t, extra):
    """Excel_ECRStatement: the EPFO ECR upload per member for the month of the To date — mill workers and
    staff with PF deducted, plus active mill workers with a UAN who were not paid at all (NCP 26)."""
    comp, loc = _scope(b)
    k = {"c": comp, "l": loc, "b": b, **_month(t)}
    paid = db.execute(text(f"""
        SELECT w.Grade, w.EGroup, w.ECode, MAX(e.UAN) AS uan, MAX(e.PensionNo) AS pen, MAX(e.EName) AS ename,
               SUM(w.Wages_Gross) gross, SUM(w.PF_Gross) pf_gross, SUM(w.PFEmployee) epf, SUM(w.Pension) eps,
               SUM(w.CoC) diff, SUM(w.Work_HR + w.Holiday_HR + w.STL_HR) hrs,
               SUM(w.PFLoanCap) loan_cap, SUM(w.PFLoanInt) loan_int
        FROM paywages w LEFT JOIN PayOEMP e ON e.ECode {UCI} = w.ECode AND e.CompCode {UCI} = w.CompCode
        WHERE w.CompCode = :c AND w.Location = :l AND w.WYear = :y AND w.WMonth = :m
          AND w.Grade IN ('MILL-WORKMEN', 'STAFF')
        GROUP BY w.Grade, w.EGroup, w.ECode HAVING SUM(w.PFEmployee) <> 0"""), k)
    det = []
    for r in paid:
        pfg = _r(_f(r.pf_gross))
        capped = 15000 if _f(r.pf_gross) > 15000 else pfg
        det.append({"grade": r.Grade, "uan": r.uan or "", "pen": r.pen or "", "member": r.ECode,
                    "ename": r.ename or "", "gross": _r(_f(r.gross)), "epf_wages": pfg, "eps_wages": capped,
                    "edli_wages": capped, "epf": _f(r.epf), "eps": _f(r.eps), "diff": _f(r.diff),
                    "ncp": max(0, 26 - math.ceil(_f(r.hrs) / 8)), "loan_cap": _f(r.loan_cap), "loan_int": _f(r.loan_int)})
    idle = db.execute(text(f"""
        SELECT e.Grade, e.UAN, e.PensionNo, e.ECode, e.EName FROM PayOEMP e
        WHERE e.CompCode = :c AND e.Grade = 'MILL-WORKMEN' AND e.Active = 'Y' AND e.EGroup NOT LIKE '%RETIRE%'
          AND e.UAN <> ''
          -- the PayOEMP mirror's Active flag is a snapshot; who still works is kept in VoWERP (status 35)
          AND e.ECode {UCI} IN (SELECT o.emp_code {UCI} FROM hrms_ed_official_details o
                                JOIN hrms_ed_personal_details p ON p.eb_id = o.eb_id AND p.status_id = 35
                                WHERE o.branch_id = :b AND o.active = 1)
          AND e.ECode {UCI} NOT IN (SELECT ECode FROM paywages WHERE CompCode = :c AND EDate BETWEEN :fdt AND :t)"""), k)
    det += [{"grade": r.Grade, "uan": r.UAN, "pen": r.PensionNo or "", "member": r.ECode, "ename": r.EName or "",
             "ncp": 26} for r in idle]
    det.sort(key=lambda d: (d["grade"].upper(), d["member"].upper()))
    for i, d in enumerate(det, start=1):
        d["sl"] = i
    sums = ["gross", "epf_wages", "eps_wages", "edli_wages", "epf", "eps", "diff", "ncp", "loan_cap", "loan_int"]
    cols = [_col("grade", "Grade", width=130), _num("sl", "SL", 60), _col("uan", "UAN", width=130),
            _col("pen", "PENACNO", width=150), _col("member", "MEMBER_ID", width=100),
            _col("ename", "MEMBER_NAME", width=220), _num("gross", "GROSS_WAGES", 110),
            _num("epf_wages", "EPF_WAGES", 100), _num("eps_wages", "EPS_WAGES", 100),
            _num("edli_wages", "EDLI_WAGES", 100), _num("epf", "EPF_CONTRI_REMITTED", 120),
            _num("eps", "EPS_CONTRI_REMITTED", 120), _num("diff", "EPF_EPS_DIFF_REMITTED", 130),
            _num("ncp", "NCP_DAYS", 90), _num("loan_cap", "RECOVERED_PFLoanCap", 130),
            _num("loan_int", "RECOVERED_PFLoanInt", 130)]
    # ponytail: legacy prefixed UAN / PENACNO / MEMBER_ID with ' to keep them text in Excel; the grid keeps them text
    return cols, _layout(det, [lambda d: d["grade"]], sums, "grade", "uan")


def esi_statement(db, b, f, t, extra):
    """Excel_ESIStatement: the ESIC monthly contribution per insured person for the month of the To
    date — days worked (capped at the month's days), ESI wages and both contributions."""
    comp, loc = _scope(b)
    k = {"c": comp, "l": loc, **_month(t), "f": f}
    wday = t.day

    def per_ecode(sql) -> dict:
        return {r[0]: _f(r[1]) for r in db.execute(text(sql), k)}

    # mill workers' days: attendance days of more than 4 work hours + adjusted days + paid holidays + leave
    att = per_ecode(f"""
        SELECT ECode, COUNT(*) FROM (SELECT ECode, WDate FROM AttendanceReport
            WHERE Work_Type IN ('DUTY', 'OT') AND WDate BETWEEN :f AND :t AND Grade = 'MILL-WORKMEN'
            GROUP BY ECode, WDate HAVING SUM(Work_HR) > 4) x GROUP BY ECode""")
    adj = per_ecode(f"""
        SELECT o.emp_code, SUM(a.Adj_Day) FROM PayM_AdjHR a JOIN hrms_ed_official_details o ON o.eb_id = a.eb_id
        WHERE a.CompCode = :c AND a.FNEDate BETWEEN :f AND :t GROUP BY o.emp_code""")
    hol = per_ecode("SELECT ECode, COUNT(*) FROM PayWHoliday WHERE CompCode = :c AND EDate BETWEEN :f AND :t "
                    "GROUP BY ECode")
    leave = per_ecode("SELECT ECode, SUM(LeaveDays) FROM PayJOLeave WHERE CompCode = :c AND FromDate >= :f "
                      "AND ToDate <= :t GROUP BY ECode")
    stl = per_ecode("SELECT ECode, SUM(LeaveDays) FROM PayJOLeave WHERE CompCode = :c AND LeaveType = 'STL Leave' "
                    "AND FNEDate = :t GROUP BY ECode")
    matt = {r[0]: (_f(r[1]), r[2]) for r in db.execute(text("""
        SELECT ECode, SUM(PresentDay + RestDay + Holiday + PLDay + CLDay + SLDay), COUNT(*) FROM PayMAtten
        WHERE CompCode = :c AND EDate BETWEEN :f AND :t GROUP BY ECode"""), k)}
    ot = {r[0]: (_f(r[1]), _f(r[2])) for r in db.execute(text("""
        SELECT o.emp_code, SUM(a.Amount), SUM(a.ESIAmt) FROM paywagesot a
        JOIN hrms_ed_official_details o ON o.eb_id = a.eb_id
        WHERE a.CompCode = :c AND a.FNEDate BETWEEN :f AND :t GROUP BY o.emp_code"""), k)}
    rows = db.execute(text(f"""
        SELECT w.Grade, w.ECode, MAX(e.ESINo) AS esi, MAX(e.EName) AS ename, SUM(w.ESI_Gross) esi_gross,
               SUM(w.ESI_Amt) esi_amt, SUM(w.ESIC) esic, SUM(w.OT_HR) ot_hr
        FROM paywages w LEFT JOIN PayOEMP e ON e.ECode {UCI} = w.ECode AND e.CompCode {UCI} = w.CompCode
        WHERE w.CompCode = :c AND w.Location = :l AND w.WYear = :y AND w.WMonth = :m
          AND (w.Grade = 'MILL-WORKMEN' OR (w.Grade = 'STAFF' AND w.PFEmployee > 0))
        GROUP BY w.Grade, w.ECode"""), k)
    det = []
    for r in rows:
        e = r.ECode
        if r.Grade == "MILL-WORKMEN":
            days = att.get(e, 0) + adj.get(e, 0) + hol.get(e, 0) + leave.get(e, 0)
            ot_amt, ot_esi = ot.get(e, (0.0, 0.0))
            wages, emp_c = ot_amt + _r(_f(r.esi_gross)), ot_esi + _f(r.esi_amt)
            empr_c = (_r(ot_amt * 3.25 / 100) if e in ot else 0) + _f(r.esic)
        else:
            # legacy summed the slip's OT hours (its PayMAtten has no OT column) when a PayMAtten row exists
            m_days, has = matt.get(e, (0.0, 0))
            days = (_r(_f(r.ot_hr) / 8) if has else 0) + _r(m_days) + _r(stl.get(e, 0))
            wages, emp_c = _r(_f(r.esi_gross)), _f(r.esi_amt)
            empr_c = _r(_f(r.esi_gross) * 3.25 / 100)
        det.append({"grade": r.Grade, "empno": e, "ipno": r.esi or "", "ename": r.ename or "",
                    "days": min(days, wday), "wages": wages, "emp_c": emp_c, "empr_c": empr_c})
    det.sort(key=lambda d: (d["grade"], d["empno"].upper()))
    for i, d in enumerate(det, start=1):
        d["sl"] = i
    cols = [_col("grade", "Grade", width=130), _num("sl", "SL", 60), _col("empno", "EMPNO", width=100),
            _col("ipno", "IPNO", width=130), _col("ename", "NAME", width=220), _num("days", "No.of Days Worked", 120),
            _num("wages", "Total Wages", 110), _num("emp_c", "Employee's Cont.", 120),
            _num("empr_c", "Employer's Cont.", 120)]
    return cols, _layout(det, [lambda d: d["grade"]], ["days", "wages", "emp_c", "empr_c"], "grade", "empno")


def ptax_statement(db, b, f, t, extra):
    """PTaxSummary_ANG: employees and P.Tax deducted per slab for the month of the To date (slabs of
    PayOMiscRate in force on the To date; an employee with no P.Tax counts in the nil slab)."""
    comp, loc = _scope(b)
    rows = db.execute(text("""
        SELECT r.FRate, r.SRate, r.FRate_HR, COUNT(x.ECode) emp, SUM(x.ptax) ptax
        FROM (SELECT ECode, SUM(PTax_Amt) ptax FROM paywages
              WHERE CompCode = :c AND Location = :l AND YEAR(EDate) = :y AND MONTH(EDate) = :m GROUP BY ECode) x
        JOIN PayOMiscRate r ON r.FRate_HR = x.ptax
        WHERE r.Location = :l AND r.All_Type = 'PTAX'
          AND r.EffDate = (SELECT MAX(EffDate) FROM PayOMiscRate
                           WHERE Location = :l AND All_Type = 'PTAX' AND EffDate <= :t)
        GROUP BY r.FRate, r.SRate, r.FRate_HR ORDER BY r.FRate"""), {"c": comp, "l": loc, **_month(t)})
    det = [{"month": t.strftime("%B-%Y").upper(), "slab": f"{_r(_f(r.FRate))} - {_r(_f(r.SRate))}",
            "rate": _f(r.FRate_HR), "emp": int(r.emp), "ptax": _f(r.ptax)} for r in rows]
    cols = [_col("month", "Month", width=140), _col("slab", "Slab", width=180), _num("rate", "Rate", 90),
            _num("emp", "No. of Employees", 130), _num("ptax", "Amount (Rs.)", 120)]
    return cols, _layout(det, [], ["emp", "ptax"], "month", "slab")


# group (menu folder after hrms/nbjclreports/) -> {report key: spec}
REPORTS: dict[str, dict[str, dict]] = {
    "providentFundReports": {
        "pfTransactionDetails": {"title": "PF Transaction Details", "dates": "range", "span": "month",
                                 "extra": GRADE_EXTRA, "build": pf_transaction_details},
        "pfEmpWiseMonthWiseTransactionPfCard": {"title": "PF Emp. Wise Month Wise Transaction [ PF Card ]",
                                                "dates": "range", "span": "month", "extra": GRADE_EXTRA,
                                                "build": pf_card},
        "employeeProvidentFundStatementPfSlip": {"title": "Employee Provident Fund Statement [ PF Slip ]",
                                                 "dates": "range", "span": "month", "extra": GRADE_EXTRA,
                                                 "build": pf_slip},
    },
    "wagesMonthlyReports": {
        "ecrStatement": {"title": "ECR Statement", "dates": "range", "span": "month", "extra": None,
                         "build": ecr_statement},
        "esiStatement": {"title": "ESI Statement", "dates": "range", "span": "month", "extra": None,
                         "build": esi_statement},
        "ptaxStatement": {"title": "PTax Statement", "dates": "range", "span": "month", "extra": None,
                          "build": ptax_statement},
    },
}
