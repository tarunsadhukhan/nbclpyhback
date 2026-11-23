"""
Winsome Reports > Loan & Advances — ports of PFLoanRegister{Summary,Fortnight,Worker}_WIL.rpt,
AdvanceRegisterSummary_WIL.rpt and NewLoanChecklist_WIL.rpt (proc RPT_NewLoanCheckList).

The registers are the NBJCL ones (src/hrms/nbjclreports/loans.py, same 01-OP / 02-LOAN / 03-DED /
04-REPAY / 05-Balance lines) read from the legacy mirrors PayOLoan / PayWages / PayLoanAdjust / PayOEMP.
The three PF _WIL commands differ: Summary and Worker count every loan and match PayLoanAdjust.DocType,
Fortnight only DocStatus 'OPEN' loans and matches PayLoanAdjust.LoanType. No _WIL register prints totals.

ponytail: legacy reads every company / location; scoped here to the branch (all mirrored rows are WIL / Factory).
ponytail: legacy Fortnight / Worker print an all-zero block for every employee who ever had a loan; dropped here.
"""
from datetime import date

from src.hrms.nbjclreports.loans import AMOUNTS, _amount_cols, _summed, _sums
from src.hrms.winsomereports._common import _col, _dmy, _layout, _num, rows, scope_args, spec

SC = "CompCode = :c AND Location = :l"
#   adj: PayLoanAdjust column holding the loan type; open_only: only DocStatus 'OPEN' loans;
#   op_rebate / bal_rebate: (capital, interest) net RebateAmt off the repayment (legacy is inconsistent);
#   emp_typed: employee list limited to employees with loans of this kind (else any loan / adjustment)
KINDS = {
    "pf": {"cap": "PFLoan", "intr": "PFInt", "wcap": "PFLoanCap", "wint": "PFLoanInt", "adj": "DocType",
           "open_only": False, "op_rebate": (True, False), "bal_rebate": (False, True), "emp_typed": False},
    "pf_open": {"cap": "PFLoan", "intr": "PFInt", "wcap": "PFLoanCap", "wint": "PFLoanInt", "adj": "LoanType",
                "open_only": True, "op_rebate": (True, False), "bal_rebate": (False, True), "emp_typed": False},
    "adv": {"cap": "ADVANCE", "intr": "", "wcap": "Advance", "wint": "0", "adj": "LoanType",
            "open_only": True, "op_rebate": (True, False), "bal_rebate": (True, False), "emp_typed": True},
}


def _employees(db) -> dict[str, tuple[str, str]]:
    return {r["ECode"]: (r["EName"] or "", r["Grade"] or "") for r in rows(db, "SELECT ECode, EName, Grade FROM PayOEMP")}


def _balance(db, p: dict, k: dict, d, before: bool) -> dict[str, tuple[float, float]]:
    """Legacy 01-OP (before d) / 05-Balance (up to d): (capital, interest) per ECode."""
    cmp = "<" if before else "<="
    rc, ri = k["op_rebate"] if before else k["bal_rebate"]
    cap = "RepayCapital - RebateAmt" if rc else "RepayCapital"
    intr = "RepayInterest - RebateAmt" if ri else "RepayInterest"
    status = "AND DocStatus = 'OPEN'" if k["open_only"] else ""
    return {r["ECode"]: (r["cap"] or 0.0, r["intr"] or 0.0) for r in rows(db, f"""
        SELECT ECode, SUM(cap) cap, SUM(intr) intr FROM (
          SELECT ECode, IF(LoanType = :cap, LoanAmt, 0) cap, IF(LoanType = :intr, InterestAmt, 0) intr
            FROM PayOLoan WHERE {SC} AND LoanDate {cmp} :d AND LoanType IN (:cap, :intr) {status}
          UNION ALL SELECT ECode, -{k['wcap']}, -{k['wint']} FROM PayWages WHERE {SC} AND EDate {cmp} :d
          UNION ALL SELECT ECode, -IF({k['adj']} = :cap, {cap}, 0), -IF({k['adj']} = :intr, {intr}, 0)
            FROM PayLoanAdjust WHERE {SC} AND ToDate {cmp} :d AND {k['adj']} IN (:cap, :intr)
        ) x GROUP BY ECode""", {**p, "d": d})}


def _register(db, b, f, t, kind: str, ecode: str = "") -> list[dict]:
    """The legacy register command lines."""
    k = KINDS[kind]
    p = scope_args(b, cap=k["cap"], intr=k["intr"], f=f, t=t)
    emp = _employees(db)
    typed = "AND LoanType IN (:cap, :intr)" if k["emp_typed"] else ""
    ecodes = {r["ECode"] for r in rows(db, f"""SELECT ECode FROM PayOLoan WHERE {SC} {typed}
        UNION SELECT ECode FROM PayLoanAdjust WHERE {SC} {typed}""", p)}
    status = "AND DocStatus = 'OPEN'" if k["open_only"] else ""
    lines = []

    def add(e, ptype, lt, d, **amt):
        if e in emp and (not ecode or e == ecode):
            lines.append({"ecode": e, "ename": emp[e][0], "grade": emp[e][1], "ptype": ptype, "lt": lt,
                          "doc_date": d, **dict.fromkeys(AMOUNTS, 0.0), **amt})

    op, bal = _balance(db, p, k, f, True), _balance(db, p, k, t, False)
    for e in sorted(ecodes):
        add(e, "01-OP", k["cap"], f, op=op.get(e, (0, 0))[0], op_int=op.get(e, (0, 0))[1])
        add(e, "05-Balance", k["cap"], t, bal=bal.get(e, (0, 0))[0], bal_int=bal.get(e, (0, 0))[1])
    # legacy GROUP BY on the plain columns = DISTINCT
    for r in rows(db, f"""SELECT DISTINCT LoanType, ECode, LoanDate, LoanAmt, InterestAmt FROM PayOLoan
            WHERE {SC} AND LoanDate BETWEEN :f AND :t AND LoanType IN (:cap, :intr) {status}""", p):
        add(r["ECode"], "02-LOAN", r["LoanType"], r["LoanDate"], loan=r["LoanAmt"], loan_int=r["InterestAmt"])
    for r in rows(db, f"""SELECT DISTINCT ECode, EDate, {k['wcap']} cap, {k['wint']} intr FROM PayWages
            WHERE {SC} AND EDate BETWEEN :f AND :t AND ({k['wcap']} <> 0 OR {k['wint']} <> 0)""", p):
        add(r["ECode"], "03-DED", k["cap"], r["EDate"], ded=r["cap"], ded_int=float(r["intr"]))
    for r in rows(db, f"""SELECT DISTINCT ECode, ToDate, RepayCapital, RepayInterest FROM PayLoanAdjust
            WHERE {SC} AND {k['adj']} IN (:cap, :intr) AND FromDate >= :f AND ToDate <= :t""", p):
        add(r["ECode"], "04-REPAY", "", r["ToDate"], repay=r["RepayCapital"], repay_int=r["RepayInterest"])
    return lines


def _summary(db, b, f, t, kind: str):
    """PFLoanRegisterSummary_WIL / AdvanceRegisterSummary_WIL: one line per employee by Grade, ECode."""
    interest = kind != "adv"
    det = sorted(_summed(_register(db, b, f, t, kind), lambda ln: ln["ecode"]), key=lambda d: (d["grade"], d["ecode"]))
    for d in det:
        d["emp"] = f"{d['ecode']} - {d['ename']}"
    return [_col("emp", "Employee", width=260), *_amount_cols(interest)], det


def _by_date(db, b, f, t, kind: str, ecode: str = ""):
    """PFLoanRegisterFortnight_WIL / PFLoanRegisterWorker_WIL: lines by date under each employee."""
    lines = _register(db, b, f, t, kind, ecode)
    live = {ln["ecode"] for ln in lines if any(abs(ln[a]) > 0.004 for a in AMOUNTS)}
    det = [dict(ln, k_emp=f"{ln['ecode']} - {ln['ename']}", date=_dmy(ln["doc_date"]))
           for ln in lines if ln["ecode"] in live]
    # group sort on "ECode - EName", then ORDER BY ECode, DocDate, PType, LoanType DESC
    det.sort(key=lambda d: d["lt"].upper(), reverse=True)
    det.sort(key=lambda d: (d["k_emp"], d["doc_date"], d["ptype"]))
    cols = [_col("grp", "Employee", width=260), _col("date", "Date", width=110), *_amount_cols(True)]
    return cols, _layout(det, [lambda d: d["k_emp"]], _sums(True), "grp", "date", grand=False, footers=False)


def _new_loan_checklist(db, b, f, t, extra):
    """NewLoanChecklist_WIL (proc RPT_NewLoanCheckList, grade 'MILL-WORKMEN'): the period's PF loans by
    loan date; Repay Cap. / Int. = the employee's first repayment of the To date's financial year."""
    fy = t.year if t.month >= 4 else t.year - 1  # legacy FYear rows are April..March (FYear not mirrored)
    p = scope_args(b, f=f, t=t, fys=date(fy, 4, 1), fye=date(fy + 1, 3, 31), g="MILL-WORKMEN")
    adj = """SELECT a.LoanType, a.ECode, a.RepayCapital, a.RepayInterest, a.ToDate FROM PayLoanAdjust a
        JOIN (SELECT LoanType, ECode, {fn}(ToDate) m FROM PayLoanAdjust WHERE ToDate >= :fys AND ToDate {cmp} :fye
              GROUP BY LoanType, ECode) b ON a.LoanType = b.LoanType AND a.ECode = b.ECode AND a.ToDate = b.m"""
    det = rows(db, f"""
        SELECT T0.LoanType, T0.LoanDate, T0.ECode, T0.EName, T0.LoanSanction, T0.InterestAmt, T0.LoanAmt,
          T0.NoOfInst, T0.EMICapital, T0.EMIInterest, T0.EMIDate,
          IF(T1.ToDate >= T2.ToDate, IFNULL(T2.RepayCapital, 0), 0) rcap,
          IF(T1.ToDate >= T2.ToDate, IFNULL(T2.RepayInterest, 0), 0) rint
        FROM PayOLoan T0
        LEFT JOIN ({adj.format(fn='MAX', cmp='<=')}) T1 ON T0.LoanType = T1.LoanType AND T0.ECode = T1.ECode
        LEFT JOIN ({adj.format(fn='MIN', cmp='<')}) T2 ON T0.LoanType = T2.LoanType AND T0.ECode = T2.ECode
        WHERE T0.CompCode = :c AND T0.Location = :l AND T0.LoanDate BETWEEN :f AND :t AND T0.LoanType = 'PFLOAN' AND T0.Grade = :g
        ORDER BY T0.LoanType, T0.LoanDate, T0.DocEntry""", p)
    for i, d in enumerate(det, 1):
        d.update(slno=i, payable=d["LoanSanction"] - (d["rcap"] + d["rint"]), emi_date=_dmy(d["EMIDate"]))
    cols = [_num("slno", "SLNo", 70), _col("ECode", "ECode", width=100), _col("EName", "EName", width=220),
            _num("LoanSanction", "Loan Sanction", 110), _num("InterestAmt", "Interest Amt", 110),
            _num("LoanAmt", "Total Amt", 110), _num("rcap", "Repay Cap.", 100), _num("rint", "Repay Int.", 100),
            _num("NoOfInst", "No Of Inst", 90), _num("EMICapital", "EMI Cap.", 100),
            _num("EMIInterest", "EMI Int.", 100), _num("payable", "PayableAmt", 110),
            _col("emi_date", "EMI Date", width=110)]
    sums = ["LoanSanction", "InterestAmt", "LoanAmt", "rcap", "rint", "payable"]
    # ponytail: the outer Loan Type group is always PFLOAN — one header row instead of a group level
    head = [{"ECode": f"Loan Type : {det[0]['LoanType']}"}] if det else []
    return cols, head + _layout(det, [lambda d: f"Loan Date : {_dmy(d['LoanDate'])}"], sums, "ECode", "EName")


def _ecode_options(db, branch_id):
    """Worker Wise Employee filter: employees with PF loans."""
    emp = _employees(db)
    codes = {r["ECode"] for r in rows(db, f"SELECT DISTINCT ECode FROM PayOLoan WHERE {SC} AND LoanType IN "
                                          "('PFLoan', 'PFInt')", scope_args(branch_id))}
    return [{"value": e, "label": f"{e} - {emp[e][0]}"} for e in sorted(codes & emp.keys())]


def _spec(title, build, extra=None):
    return spec(title, build, span="month", extra=extra, max_days=400)


REPORTS: dict[str, dict[str, dict]] = {"loanAndAdvances": {
    "pfLoanRegisterSummay": _spec("PF Loan Register Summay", lambda db, b, f, t, x: _summary(db, b, f, t, "pf")),
    "pfLoanRegisterFortnightWise": _spec("PF Loan Register Fortnight Wise",
                                         lambda db, b, f, t, x: _by_date(db, b, f, t, "pf_open")),
    "pfLoanRegisterWorkerWise": _spec("PF Loan Register Worker Wise", lambda db, b, f, t, x: _by_date(db, b, f, t, "pf", x),
                                      {"label": "Employee", "options": _ecode_options}),
    "advanceRegisterSummary": _spec("Advance Register Summary", lambda db, b, f, t, x: _summary(db, b, f, t, "adv")),
    "newLoanCheckList": _spec("New Loan Check List", _new_loan_checklist),
}}
