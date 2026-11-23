"""Winsome Reports > PF & ESI Reports (see __init__.py) — ports of the *_WIL.rpt reports over the mirrored
legacy tables PayWages (fortnight pay rows), PayOEMP (employee master), ATTEN and PayPFTranDTL (PF ledger:
P = 1 opening, 2 wages, 3 salary, 5 interest, 8 closing, 11 PF loan opening, 13 NR loan, 14 PF loan).

The legacy procs' #RPT temp tables are rebuilt as Python lists. Filters: the two contribution ledgers and
PF Transaction Details take an employee (legacy ECode); PF Card and PF Slip take the Grade the legacy form
showed. The ledgers' interest rate (a Crystal prompt the form never filled; proc default 8.10) is the rate
of the latest PF interest posting on or before the To date.
"""
import collections
from datetime import date, timedelta

from src.hrms.nbjclreports.pf import CARD_NUMS, GRADE_EXTRA, SLIP_LABELS, TRAN_NUMS, _sort_pf
from src.hrms.wagesSalaryProcess import _r

from ._common import _col, _dmy, _layout, _num, rows, scope_args, spec

FORTNIGHTS = [(m, d) for m in (4, 5, 6, 7, 8, 9, 10, 11, 12, 1, 2, 3) for d in ("01", "02")]
MON = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _fn(m: int, d: str, suffix: str) -> str:
    return f"{MON[m]}{d}_{suffix}"


def _ecodes(db, b) -> list[dict]:
    """Employees with a PF number (mill workers and staff) for the ECode filter."""
    return [{"value": r["ECode"], "label": f"{r['ECode']} - {r['EName'] or ''}"} for r in rows(db, """
        SELECT ECode, EName FROM PayOEMP WHERE CompCode = :c AND Grade IN ('MILL-WORKMEN', 'STAFF')
          AND TRIM(PFNo) NOT IN ('', 'N/A') ORDER BY ECode""", scope_args(b))]


ECODE_EXTRA = {"label": "ECode", "options": _ecodes}


def _year_back(d: date) -> date:
    return d.replace(year=d.year - 1) if (d.month, d.day) != (2, 29) else d.replace(year=d.year - 1, day=28)


def _int_rate(db, t: date) -> float:
    r = rows(db, """SELECT INT_Rate FROM PayPFTranDTL WHERE P = 5 AND INT_Rate > 0 AND ToDate <= :t
                    ORDER BY ToDate DESC LIMIT 1""", {"t": t})
    return r[0]["INT_Rate"] if r else 8.10


def _ledger_base(db, b, f, t, extra, with_prev_year: bool):
    """RPT_PFContLedger / RPT_PFContLedgerEmpWise common part: mill workers with a PF number and attendance
    in the period (or the year before), their WAGES rows per fortnight column and last year's PF totals.

    ponytail: legacy took "last year" as DATEADD(Y, -1, date) — Y is day-of-year, so one day back — and read
    Jan-Mar from the From date's calendar year (YEAR(EDate)+1 = YEAR(From)+1). Here last year is the period one
    year back and Jan-Mar come from inside From..To, as the headings say. Legacy also picked an arbitrary row
    when a fortnight had both a WAGES and an OT slip; the OT slip carries no PF, so only WAGES rows are read."""
    pf, pt = _year_back(f), _year_back(t)
    k = scope_args(b, f=f, t=t, pf=pf, pt=pt, e=extra)
    prev_att = "OR ECode IN (SELECT emp_code FROM ATTEN WHERE WDate BETWEEN :pf AND :pt)" if with_prev_year else ""
    emps = rows(db, f"""
        SELECT e.*, (SELECT FName FROM FYEAR WHERE StartDate <= :t AND EndDate >= :f LIMIT 1) AS FYear
        FROM PayOEMP e
        WHERE CompCode = :c AND Grade = 'MILL-WORKMEN' AND TRIM(PFNo) <> '' AND (:e = '' OR ECode = :e)
          AND (ECode IN (SELECT emp_code FROM ATTEN WHERE WDate BETWEEN :f AND :t) {prev_att})
        ORDER BY DeptCode, ECode""", k)
    wages: dict = collections.defaultdict(lambda: collections.defaultdict(float))
    for w in rows(db, """
            SELECT ECode, MONTH(EDate) m, WDay, SUM(PFEmployee) E, SUM(Pension) P833, SUM(CoC) C,
                   SUM(PF_Gross) PFG, SUM(Work_Day) Day
            FROM PayWages WHERE CompCode = :c AND PaySlipType = 'WAGES' AND EDate BETWEEN :f AND :t
              AND (:e = '' OR ECode = :e)
            GROUP BY ECode, MONTH(EDate), WDay""", k):
        if (w["m"], w["WDay"]) in FORTNIGHTS:
            for s in ("E", "P833", "C", "PFG", "Day"):
                wages[w["ECode"]][_fn(w["m"], w["WDay"], s)] += w[s] or 0
    prev = {r["ECode"]: r for r in rows(db, """
        SELECT ECode, SUM(PFEmployee) E, SUM(CoC) C FROM PayWages
        WHERE CompCode = :c AND EDate BETWEEN :pf AND :pt AND (:e = '' OR ECode = :e) GROUP BY ECode""", k)}
    rate = _int_rate(db, t)
    for e in emps:
        p = prev.get(e["ECode"], {})
        e["w"] = wages[e["ECode"]]
        e["Prev_Emp_Total"] = p.get("E") or 0.0
        e["Prev_Emp_Int"] = _r(e["Prev_Emp_Total"] * rate / 100)
        e["Prev_EmpShare"] = e["Prev_Emp_Total"] + e["Prev_Emp_Int"]
        e["Prev_Comp_Total"] = p.get("C") or 0.0
        e["Prev_Comp_Int"] = _r(e["Prev_Comp_Total"] * rate / 100)
        e["Prev_CompShare"] = e["Prev_Comp_Total"] + e["Prev_Comp_Int"]
    return emps, rate


def pf_contribution_ledger(db, b, f, t, extra):
    """PFContLedger_WIL (proc RPT_PFContLedger): employee and employer (1.67%) PF share per fortnight of
    the year, last year's total with interest, per mill worker; grouped by department."""
    emps, rate = _ledger_base(db, b, f, t, extra, with_prev_year=True)
    det = []
    for e in emps:
        d = {"ECode": e["ECode"], "PFNo": e["PFNo"], "EName": e["EName"], "dept": e["DeptName"] or e["DeptCode"]}
        for s, src in (("E", "E"), ("C", "C")):
            for m, wd in FORTNIGHTS:
                d[_fn(m, wd, s)] = e["w"][_fn(m, wd, src)]
        d["Emp_Total"] = sum(d[_fn(m, wd, "E")] for m, wd in FORTNIGHTS)
        d["Comp_Total"] = sum(d[_fn(m, wd, "C")] for m, wd in FORTNIGHTS)
        for c in ("Prev_Emp_Total", "Prev_Emp_Int", "Prev_EmpShare", "Prev_Comp_Total", "Prev_Comp_Int",
                  "Prev_CompShare"):
            d[c] = e[c]
        d["Total"] = d["Prev_EmpShare"] + d["Prev_CompShare"]
        det.append(d)

    def share(s, total, prefix):
        return [*[_num(_fn(m, wd, s), f"{MON[m]} {wd}", 80) for m, wd in FORTNIGHTS], _num(total, "Total", 95),
                _num(f"Prev_{prefix}_Total", "Opening Balance", 100),
                _num(f"Prev_{prefix}_Int", f"Int on Opening Balance @ {rate:g} %", 120),
                _num(f"Prev_{prefix}Share", "Closing Balance", 100)]

    emp_cols, comp_cols = share("E", "Emp_Total", "Emp"), share("C", "Comp_Total", "Comp")
    cols = [_col("ECode", "ECode", width=110), _col("PFNo", "PFNo", width=90), _col("EName", "EName", width=180),
            *emp_cols, *comp_cols, _num("Total", "Total", 100)]
    sums = [c["field"] for c in emp_cols + comp_cols] + ["Total"]
    return cols, _layout(det, [lambda d: f"Department : {d['dept']}"], sums, "ECode", "EName")


LEDGER_LINES = [("PFG", "PF- GROSS"), ("E", "CONTRIBUTION EMP SHARE"), ("P833", "CONTRIBUTION EMPR SHARE 8.33%"),
                ("C", "CONTRIBUTION EMPR SHARE 1.67%"), ("Day", "WORKING DAYS")]


def pf_contribution_ledger_emp_wise(db, b, f, t, extra):
    """PFContLedgerEmpWise_WIL (proc RPT_PFContLedgerEmpWise): one card per mill worker with attendance in the
    period — PF gross, both shares and working days per fortnight, then last year's balance and interest."""
    emps, rate = _ledger_base(db, b, f, t, extra, with_prev_year=False)
    out = []
    for e in emps:
        out.append({"lbl": f"L.B./INE NO. : {e['ECode']}   NAME : {e['EName'] or ''}   P.F A/C NO : {e['PFNo']}   "
                           f"UAN NO : {e.get('UAN') or ''}   ESI.NO : {e.get('ESINo') or ''}   "
                           f"AADHAR NO : {e.get('AadharNo') or ''}   Department : {e['DeptName'] or ''}   "
                           f"DOB : {_dmy(e.get('DoB'))}   Egroup : {e['EGroup'] or ''}   DOJ : {_dmy(e.get('DoJ'))}   "
                           f"Occupation : {e.get('Designation') or ''}   Financial : {e['FYear'] or ''}"})
        for s, lbl in LEDGER_LINES:
            line = {"lbl": lbl, **{_fn(m, wd, "x"): e["w"][_fn(m, wd, s)] for m, wd in FORTNIGHTS}}
            line["total"] = sum(line[_fn(m, wd, "x")] for m, wd in FORTNIGHTS)
            out.append(line)
        out += [{"lbl": "OPENING BALANCE LAST YEAR CLOSING B. F.", "emp": e["Prev_Emp_Total"],
                 "empr": e["Prev_Comp_Total"]},
                {"lbl": f"INTEREST ON OPENING BALANCE @ {rate:g}%", "emp": e["Prev_Emp_Int"], "empr": e["Prev_Comp_Int"]},
                {"lbl": "CLOSING BALANCE C. F TO NEXT YEAR", "emp": e["Prev_EmpShare"], "empr": e["Prev_CompShare"]}]
    cols = [_col("lbl", "Particulars", width=280), *[_num(_fn(m, wd, "x"), f"{MON[m]} {wd}", 80) for m, wd in FORTNIGHTS],
            _num("total", "Total", 100), _num("emp", "Emp Share", 100), _num("empr", "Empr Share", 100)]
    return cols, out


def pf_esi_payable(db, b, f, t, extra):
    """PF_ESI_Payable_MonthWise_WIL: PF (10% / 8.33% / 1.67%) and ESI (0.75% / 3.25%) of the wages slips per
    month."""
    det = rows(db, """
        SELECT WYear, WMonth, CONCAT(MONTHNAME(MIN(EDate)), ' - ', WYear) MN, SUM(PFEmployee) PFEmployee,
               SUM(Pension) Pension, SUM(CoC) COC, SUM(ESI_Amt) ESI_Amt, SUM(ESIC) ESIC_Amt
        FROM PayWages WHERE CompCode = :c AND PaySlipType IN ('WAGES', 'DUTY OT') AND EDate BETWEEN :f AND :t
        GROUP BY WYear, WMonth, MONTHNAME(EDate)
        ORDER BY CAST(WYear AS UNSIGNED), CAST(WMonth AS UNSIGNED), MN""", scope_args(b, f=f, t=t))
    cols = [_col("MN", "Month/Year", width=160), _num("PFEmployee", "PF Employee Cont. [ 10.00% ]", 150),
            _num("Pension", "PF Employer Cont. [ 8.33% ]", 150), _num("COC", "PF Employer Cont. [ 1.67% ]", 150),
            _num("ESI_Amt", "ESI Employee Cont. [ 0.75% ]", 150), _num("ESIC_Amt", "ESI Employer Cont. [ 3.25% ]", 150)]
    return cols, det  # legacy prints no totals


def pf_transaction_details(db, b, f, t, extra):
    """PayPFTranDTL_WIL (proc RPT_PayPFTranDTL): opening, contribution, NR loan, interest and closing per
    employee and month, grouped by PF number."""
    sums = ", ".join(f"SUM({c}) {c}" for c in TRAN_NUMS)
    det = rows(db, f"""
        SELECT X.ECode, X1.EName, X1.DoJ, X1.EGroup, X.PFNo, X.WYear, X.WMonth, X.MName, {sums}
        FROM (SELECT T0.ECode, T0.PFNo, T0.FYear, YEAR(MAX(T0.ToDate)) WYear, MONTH(MAX(T0.ToDate)) WMonth,
                     CONCAT(UPPER(LEFT(MONTHNAME(MAX(T0.ToDate)), 3)), ' - ', RIGHT(YEAR(MAX(T0.ToDate)), 2)) MName,
                     {sums}
              FROM PayPFTranDTL T0
              WHERE T0.Location = :l AND T0.ToDate BETWEEN :f AND :t AND T0.PFNo <> ''
                AND T0.Grade IN ('MILL-WORKMEN', 'STAFF') AND (:e = '' OR T0.ECode = :e)
              GROUP BY T0.P, T0.PType, T0.ECode, T0.EName, T0.PFNo, T0.FYear, T0.WYear, T0.WMonth, T0.INT_Rate) X
        LEFT JOIN PayOEMP X1 ON X1.ECode = X.ECode
        GROUP BY X1.OrgECode, X.ECode, X1.EName, X1.DoJ, X1.Grade, X1.EGroup, X1.SubGroup, X.PFNo, X.FYear,
                 X.WYear, X.WMonth, X.MName
        ORDER BY X.PFNo, X.WYear, X.WMonth, X.ECode""", scope_args(b, f=f, t=t, e=extra))
    heads: dict = {}
    for d in det:
        # the Crystal group (PF No.) header shows the first employee of the PF number
        heads.setdefault(d["PFNo"].upper(), f"EMPLOYEE - {d['ECode']} {d['EName'] or ''}   PF NO - {d['PFNo']}   "
                                            f"CAT - {d['EGroup'] or ''}   JOINING DATE - {_dmy(d['DoJ'])}")
        d["k_pf"], d["grp"] = heads[d["PFNo"].upper()], d["MName"]
    cols = [_col("grp", "Employee / Month", width=150),
            *[_num(c, h, 95) for c, h in zip(TRAN_NUMS, (
                "Op PF Emp", "Op VPF Emp", "Op PF Comp", "PF Emp", "VPF Emp", "PF Comp", "NR PF Emp", "NR VPF Emp",
                "NR PF Comp", "Int PF Emp", "Int VPF Emp", "Int PF Comp", "Cl PF Emp", "Cl VPF Emp", "Cl PF Comp"))]]
    return cols, _layout(det, [lambda d: d["k_pf"]], [], "grp", "MName", grand=False, footers=False)


def _ledger(db, b, f, t, grade) -> list[dict]:
    """PF ledger rows posted (ToDate) in the period with a PF number, of the Grade (blank = all)."""
    return rows(db, """
        SELECT *, MONTHNAME(ToDate) AS MonthName FROM PayPFTranDTL
        WHERE Location = :l AND ToDate BETWEEN :f AND :t AND PFNo NOT IN ('', 'N/A') AND (:g = '' OR Grade = :g)""",
                scope_args(b, f=f, t=t, g=grade))


def _oemp(db, b) -> dict[str, dict]:
    return {r["ECode"]: r for r in rows(db, "SELECT ECode, OrgECode, PFNo FROM PayOEMP WHERE CompCode = :c",
                                        scope_args(b))}


def _f(v) -> float:
    return float(v or 0)


def pf_card(db, b, f, t, extra):
    """PF_EmpWiseMonthWise_WIL (proc RPT_PF_EmpWiseMonthWise): the PF card — B/F, each month's contribution
    and loan, sub total, C/B, interest and C/F per PF number."""
    src, emp = _ledger(db, b, f, t, extra), _oemp(db, b)
    rpt: list[dict] = []

    def add(p, ttype, pf, ecode, ename, mname, wy, wm, **v):
        rpt.append({"P": p, "TType": ttype, "PFNo": pf, "ECode": ecode, "EName": ename, "MName": mname,
                    "WYear": int(wy or 0), "WMonth": int(wm or 0), **dict.fromkeys(CARD_NUMS, 0.0), **v})

    def grouped(match, fold):
        g: dict = {}
        for r in src:
            if match(r):
                k = (r["PFNo"], r["ECode"], r["EName"], r["MonthName"], r["WYear"], r["WMonth"])
                fold(g.setdefault(k, {}), r)
        return g

    def fold_bf(a, r):
        for c, s in (("PF_Emp", "OP_PF_EMP"), ("NR_Emp", "NR_PF_EMP"), ("PF_Comp", "OP_PF_Comp"),
                     ("NR_Comp", "NR_PF_Comp"), ("VPF", "OP_VPF_EMP"), ("Advance", "OP_PF_LOAN"),
                     ("RepayAdv", "REPAY_PF_LOAN"), ("CashAdj", "REPAYM_PF_LOAN")):
            a[c] = a.get(c, 0.0) + _f(r[s])

    def fold_tr(a, r):
        for c, s, sign in (("PF_Emp", "PF_EMP", 1), ("NR_Emp", "NR_PF_EMP", -1), ("PF_Comp", "PF_Comp", 1),
                           ("NR_Comp", "NR_PF_Comp", -1), ("VPF", "VPF_EMP", 1), ("Advance", "NEW_PF_LOAN", 1),
                           ("RepayAdv", "REPAY_PF_LOAN", 1), ("CashAdj", "REPAYM_PF_LOAN", 1)):
            a[c] = a.get(c, 0.0) + sign * _f(r[s])
        a["AdvBal"] = min(a.get("AdvBal", _f(r["CL_PF_LOAN"])), _f(r["CL_PF_LOAN"]))

    bf_month = f.strftime("%B")
    for k, v in grouped(lambda r: (r["P"], r["PType"]) in ((1, "PF OPENING"), (11, "PFLOAN-OP")), fold_bf).items():
        add(1, "B/F", k[0], k[1], k[2], bf_month, k[4], k[5], **v)
    for k, v in grouped(lambda r: (r["P"], r["PType"]) in ((2, "WAGES"), (3, "SALARY"), (14, "PFLOAN")),
                        fold_tr).items():
        add(2, "TRANSACTION", *k, **v)

    def per_emp(ttypes):
        out: dict = {}
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
        add(4, "C/B", None, ecode, ename, *end, **{**s, "PF_Emp": s["PF_Emp"] - s["NR_Emp"], "NR_Emp": 0.0,
                                                    "PF_Comp": s["PF_Comp"] - s["NR_Comp"], "NR_Comp": 0.0,
                                                    "AdvBal": 0.0})
    for r in src:
        if (r["P"], r["PType"]) == (5, "INTEREST"):
            add(5, "INTEREST", None, r["ECode"], r["EName"], *end, PF_Emp=_f(r["INT_PF_EMP"]),
                PF_Comp=_f(r["INT_PF_Comp"]), VPF=_f(r["INT_VPF_EMP"]), Advance=_f(r["NEW_PF_INT"]))
    loan = per_emp(("C/B", "INTEREST"))
    for r in src:
        if (r["P"], r["PType"]) == (8, "CLOSING"):
            ln = loan.get((r["ECode"], r["EName"]))
            # legacy (#LnCl): the C/F advance is the loan left after the year's repayments, never negative
            adv = max(0.0, ln["Advance"] - ln["RepayAdv"] - ln["CashAdj"]) if ln else _f(r["NEW_PF_LOAN"])
            add(8, "C/F", None, r["ECode"], r["EName"], *end, PF_Emp=_f(r["Cumm_PF_EMP"]), NR_Emp=_f(r["NR_PF_EMP"]),
                PF_Comp=_f(r["Cumm_PF_Comp"]), NR_Comp=_f(r["NR_PF_Comp"]), VPF=_f(r["Cumm_VPF_EMP"]), Advance=adv,
                RepayAdv=_f(r["REPAY_PF_LOAN"]), CashAdj=_f(r["REPAYM_PF_LOAN"]))
    for x in rpt:  # PF number from the employee master, as legacy
        if x["ECode"] in emp:
            x["PFNo"] = emp[x["ECode"]]["PFNo"] or ""
    # a zero B/F, INTEREST and C/F line for every employee that has none
    for p, ttype, (mn, wy, wm) in ((1, "B/F", (bf_month, f.year, f.month)), (5, "INTEREST", end), (8, "C/F", end)):
        have = {x["ECode"] for x in rpt if x["P"] == p}
        for pf, ecode, ename in dict.fromkeys((x["PFNo"], x["ECode"], x["EName"]) for x in rpt
                                              if x["ECode"] not in have):
            add(p, ttype, pf, ecode, ename, mn, wy, wm)
    slno = {pf: i for i, pf in enumerate(sorted({(x["PFNo"] or "").upper() if x["PFNo"] is not None else None
                                                 for x in rpt}, key=_sort_pf), start=1)}
    det = [x for x in rpt if x["PFNo"]]
    det.sort(key=lambda x: (x["PFNo"].upper(), x["P"], x["ECode"], x["WYear"], x["WMonth"]))
    for x in det:
        x["k_pf"] = f"P.F. No. {x['PFNo']}   Name : {x['EName'] or ''}   SRL NO: {slno[x['PFNo'].upper()]}"
        x["grp"] = x["MName"] if x["TType"] == "TRANSACTION" else x["TType"]
    cols = [_col("grp", "P.F. No. / Month", width=150), _num("PF_Emp", "Employees Subscript", 110),
            _num("NR_Emp", "Non-Refun Withdrawl", 110), _num("PF_Comp", "Employer Contribut", 110),
            _num("NR_Comp", "Non-Refun Withdrawl (Comp)", 120), _num("VPF", "Volunta Contrib", 100),
            _num("Advance", "Advance + Int", 100), _num("RepayAdv", "Re-pay of Adv", 100),
            _num("CashAdj", "Cash Real", 90), _num("AdvBal", "Advance Balance", 100)]
    return cols, _layout(det, [lambda d: d["k_pf"]], [], "grp", "TType", grand=False, footers=False)


def pf_slip(db, b, f, t, extra):
    """PF_EmpWiseStatementSumm_WIL (proc RPT_PF_EmpWiseStatementSumm): the PF slip — opening, NR withdrawal,
    contribution, interest and closing (own / company / voluntary) per PF number."""
    src = _ledger(db, b, f, t, extra)
    rpt: list[dict] = []

    def add(p, key, own=0.0, comp=0.0, vol=0.0, total=None, rate=0.0):
        rpt.append({"P": p, "PFNo": key[0], "OrgECode": key[1], "ECode": key[2], "EName": key[3], "own": own,
                    "comp": comp, "vol": vol, "total": own + comp + vol if total is None else total,
                    "rate": _f(rate)})

    def key(r):
        return r["PFNo"], r["OrgECode"], r["ECode"], r["EName"]

    def sum_of(ps, sign=1):
        out: dict = {}
        for x in rpt:
            if x["P"] in ps:
                s = out.setdefault(key(x), [0.0, 0.0, 0.0, 0.0])
                s[0] += sign * x["own"]; s[1] += sign * x["comp"]; s[2] += sign * x["vol"]
                s[3] = max(s[3], x["rate"])
        return out

    op: dict = {}
    for r in src:
        if (r["P"], r["PType"]) == (1, "PF OPENING"):
            s = op.setdefault(key(r), [0.0, 0.0, 0.0, 0.0])
            s[0] += _f(r["OP_PF_EMP"]); s[1] += _f(r["OP_PF_Comp"]); s[2] += _f(r["OP_VPF_EMP"])
            s[3] = max(s[3], _f(r["INT_Rate"]))
    for k, s in op.items():
        add(1, k, *s[:3], rate=s[3])
    for r in src:
        if (r["P"], r["PType"]) == (13, "NRLOAN"):  # legacy: own and company negated, voluntary and total not
            add(2, key(r), -_f(r["NR_PF_EMP"]), -_f(r["NR_PF_Comp"]), _f(r["NR_VPF_EMP"]),
                _f(r["NR_PF_EMP"]) + _f(r["NR_PF_Comp"]) + _f(r["NR_VPF_EMP"]), r["INT_Rate"])
    # legacy "[ 1 - 2 ]" subtracts the already negated line 2 (so NR own / company add back)
    net = collections.defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])
    for part in (sum_of((1,)), sum_of((2,), -1)):
        for k, s in part.items():
            n = net[k]
            n[0] += s[0]; n[1] += s[1]; n[2] += s[2]; n[3] = max(n[3], s[3])
    for k, s in net.items():
        add(3, k, *s[:3], rate=s[3])
    contrib: dict = {}
    for r in src:
        if (r["P"], r["PType"]) in ((2, "WAGES"), (3, "SALARY")):
            s = contrib.setdefault((*key(r), _f(r["INT_Rate"])), [0.0, 0.0, 0.0])
            s[0] += _f(r["PF_EMP"]); s[1] += _f(r["PF_Comp"]); s[2] += _f(r["VPF_EMP"])
    for k, s in contrib.items():
        add(4, k[:4], *s, rate=k[4])
    for k, s in sum_of((3, 4)).items():
        add(5, k, *s[:3], rate=s[3])
    for r in src:
        # ponytail: legacy required a Grade (Grade = @Grade, blank gave an empty slip); here All = every grade
        if (r["P"], r["PType"]) == (5, "INTEREST"):
            add(6, key(r), _f(r["INT_PF_EMP"]), _f(r["INT_PF_Comp"]), _f(r["INT_VPF_EMP"]), rate=r["INT_Rate"])
        elif r["P"] == 8:
            add(7, key(r), _f(r["Cumm_PF_EMP"]), _f(r["Cumm_PF_Comp"]), _f(r["Cumm_VPF_EMP"]), rate=r["INT_Rate"])
    for p in range(1, 8):  # a zero line for every step an employee has none of
        have = {x["ECode"] for x in rpt if x["P"] == p}
        for k in dict.fromkeys(key(x) for x in rpt if x["ECode"] not in have):
            add(p, k)
    groups: dict = {}
    for x in sorted(rpt, key=lambda x: (x["PFNo"].upper(), x["P"])):
        groups.setdefault(x["PFNo"].upper(), []).append(x)
    out = []
    for slno, lines in enumerate(groups.values(), start=1):
        out.append({"grp": f"P.F. Account No. {lines[0]['PFNo']}   Name : {lines[0]['EName'] or ''}   SRL NO: {slno}"})
        out += [{"lbl": SLIP_LABELS[x["P"]], "own": x["own"], "comp": x["comp"], "vol": x["vol"], "total": x["total"]}
                for x in lines]
        # group footer: interest rate and the last line's (closing) total balance
        out.append({"lbl": "Total Balance", "rate": max(x["rate"] for x in lines), "total": lines[-1]["total"]})
    cols = [_col("grp", "P.F. Account No.", width=120), _col("lbl", "Particulars", width=290),
            _num("own", "Own Details", 110), _num("comp", "Company Details", 120), _num("vol", "Voluntary Details", 120),
            _num("total", "Total", 110), _num("rate", "Interest Rate %", 110)]
    return cols, out


REPORTS: dict[str, dict[str, dict]] = {
    "pfAndEsiReports": {
        "pfContributionLedger": spec("PF Contribution Ledger", pf_contribution_ledger, span="month",
                                     extra=ECODE_EXTRA),
        "pfContributionLedgerEmployeeWise": spec("PF Contribution Ledger - Employee Wise",
                                                 pf_contribution_ledger_emp_wise, span="month", extra=ECODE_EXTRA),
        "pfAndEsiPayableMonthWise": spec("PF & ESI Payable [ Month Wise ]", pf_esi_payable, span="month"),
        "pfTransactionDetails": spec("PF Transaction Details", pf_transaction_details, span="month",
                                     extra=ECODE_EXTRA),
        "pfEmpWiseMonthWiseTransactionPfCard": spec("PF Emp. Wise Month Wise Transaction [ PF Card ]", pf_card,
                                                    span="month", extra=GRADE_EXTRA),
        "employeeProvidentFundStatementPfSlip": spec("Employee Provident Fund Statement [ PF Slip ]", pf_slip,
                                                     span="month", extra=GRADE_EXTRA),
    },
}
