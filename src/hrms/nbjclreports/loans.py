"""
NBJCL Reports > Loan & Advances — ports of the 12 legacy Smart-Eye Crystal reports of the
"Loan & Advances" group (PFLoanRegister*, PFNRLoanRegister*, AdvanceRegister*, *AdvanceList _NJB.rpt).
See src/hrms/nbjclreports/__init__.py for the spec shape.

The legacy registers are one SQL command each: per employee an opening row (01-OP: loans given before
From less wage deductions and loan adjustments before From), the period's loans (02-LOAN, PayOLoan),
wage deductions (03-DED, PayWages) and adjustments (04-REPAY, PayLoanAdjust), and a closing row
(05-Balance, the same as the opening up to To). The Summary report adds them up per employee, the
Fortnight / Worker Wise reports list them by date under an employee header. Here the same five parts
are read with plain grouped queries over the mirrored legacy tables (payoloan, paywages, payloanadjust,
PaySalary, PayOEMP) and laid out in Python. Column headings follow the legacy layout, where
"Adjustment" shows the PayLoanAdjust repayments and "Return" the wage deductions.

ponytail: the legacy SQL reads every company / location; here the tables are scoped to the branch's
legacy CompCode / Location (_scope), so the 7 HEAD OFFICE advances and their wages / salary rows drop out.
ponytail: the legacy Fortnight / Worker Wise reports print an (all zero) block for every employee who
ever had a loan; employees whose lines are all zero are left out here.
Legacy AdvanceRegister*_NJB no longer runs on the live legacy DB ("Ambiguous column DocStatus": PayOEMP
gained a DocStatus column); the loan's own DocStatus is what it meant and what is read here.
"""
import collections

from sqlalchemy.sql import text

from src.hrms.nbjclAttendanceReports import _col, _dmy, _layout, _num
from src.hrms.wagesSalaryProcess import _scope

# one register kind = which loan types, wage columns and adjustment rows make it up.
#   cap / intr     payoloan.LoanType of the capital / interest loans ('' = none)
#   wcap / wint    paywages deduction columns
#   adj            payloanadjust column holding the loan type (legacy PF reads DocType, advances LoanType)
#   open_only      only DocStatus 'OPEN' loans count (advances); legacy PF counts cancelled loans too
#   op_rebate / bal_rebate   (capital, interest): the adjustment's RebateAmt is netted off the repayment
#                  — legacy is inconsistent between opening and closing, kept as is
#   emp_typed      the employee list is limited to employees with loans of this kind (else: any loan)
KINDS = {
    "pf": {"cap": "PFLoan", "intr": "PFInt", "wcap": "PFLoanCap", "wint": "PFLoanInt", "adj": "DocType",
           "open_only": False, "op_rebate": (True, False), "bal_rebate": (False, True), "emp_typed": False},
    "adv": {"cap": "ADVANCE", "intr": "", "wcap": "Advance", "wint": "0", "adj": "LoanType",
            "open_only": True, "op_rebate": (True, False), "bal_rebate": (True, False), "emp_typed": True},
    # ponytail: legacy SpecialAdvanceRegister*_NJB.rpt was not available (would not load) — derived from
    # the Advance register with loan type 'SPL ADVANCE' and paywages.SplAdvance as the wages process reads
    # them (_loan_emi). Neither nbjcl nor legacy holds any such rows yet, so these reports come out empty.
    "spl": {"cap": "SPL ADVANCE", "intr": "", "wcap": "SplAdvance", "wint": "0", "adj": "LoanType",
            "open_only": True, "op_rebate": (True, False), "bal_rebate": (True, False), "emp_typed": True},
}
AMOUNTS = ("op", "op_int", "loan", "loan_int", "ded", "ded_int", "repay", "repay_int", "bal", "bal_int")
SC = "CompCode = :c AND Location = :l"


# ─── Data ──────────────────────────────────────────────────────────────────


def _employees(db) -> dict[str, tuple[str, str]]:
    """PayOEMP ECode -> (EName, Grade)."""
    return {r.ECode.strip(): ((r.EName or "").strip(), r.Grade or "")
            for r in db.execute(text("SELECT ECode, EName, Grade FROM PayOEMP"))}


def _balance(db, p: dict, k: dict, d, before: bool) -> dict[str, tuple[float, float]]:
    """Legacy 01-OP (before d) / 05-Balance (up to d): (capital, interest) per ECode."""
    cmp = "<" if before else "<="
    rc, ri = k["op_rebate"] if before else k["bal_rebate"]
    cap = "RepayCapital - RebateAmt" if rc else "RepayCapital"
    intr = "RepayInterest - RebateAmt" if ri else "RepayInterest"
    status = "AND DocStatus = 'OPEN'" if k["open_only"] else ""
    rows = db.execute(text(f"""
        SELECT ECode, SUM(cap) cap, SUM(intr) intr FROM (
          SELECT ECode, IF(LoanType = :cap, LoanAmt, 0) cap, IF(LoanType = :intr, InterestAmt, 0) intr
            FROM payoloan WHERE {SC} AND LoanDate {cmp} :d AND LoanType IN (:cap, :intr) {status}
          UNION ALL SELECT ECode, -{k['wcap']}, -{k['wint']} FROM paywages WHERE {SC} AND EDate {cmp} :d
          UNION ALL SELECT ECode, -IF({k['adj']} = :cap, {cap}, 0), -IF({k['adj']} = :intr, {intr}, 0)
            FROM payloanadjust WHERE {SC} AND ToDate {cmp} :d AND {k['adj']} IN (:cap, :intr)
        ) x GROUP BY ECode"""), {**p, "d": d})
    return {r.ECode.strip(): (float(r.cap or 0), float(r.intr or 0)) for r in rows}


def _register(db, b, f, t, kind: str, ecode: str = "") -> list[dict]:
    """The legacy register command: 01-OP / 02-LOAN / 03-DED / 04-REPAY / 05-Balance lines."""
    k = KINDS[kind]
    comp, loc = _scope(b)
    p = {"c": comp, "l": loc, "cap": k["cap"], "intr": k["intr"], "f": f, "t": t}
    emp = _employees(db)
    typed = f"AND {{col}} IN (:cap, :intr)" if k["emp_typed"] else ""
    ecodes = {r[0].strip() for r in db.execute(text(f"""
        SELECT ECode FROM payoloan WHERE {SC} {typed.format(col='LoanType')}
        UNION SELECT ECode FROM payloanadjust WHERE {SC} {typed.format(col='LoanType')}"""), p)}
    lines = []

    def add(e, ptype, lt, d, **amt):
        if e in emp and (not ecode or e == ecode):
            lines.append({"ecode": e, "ename": emp[e][0], "grade": emp[e][1], "ptype": ptype, "lt": lt,
                          "doc_date": d, **dict.fromkeys(AMOUNTS, 0.0), **amt})

    op, bal = _balance(db, p, k, f, True), _balance(db, p, k, t, False)
    for e in sorted(ecodes):
        add(e, "01-OP", k["cap"], f, op=op.get(e, (0, 0))[0], op_int=op.get(e, (0, 0))[1])
        add(e, "05-Balance", k["cap"], t, bal=bal.get(e, (0, 0))[0], bal_int=bal.get(e, (0, 0))[1])
    # legacy GROUP BY on the plain columns = DISTINCT: identical lines of one day count once
    status = "AND DocStatus = 'OPEN'" if k["open_only"] else ""
    for r in db.execute(text(f"""
        SELECT DISTINCT LoanType, ECode, LoanDate, LoanAmt, InterestAmt FROM payoloan
        WHERE {SC} AND LoanDate BETWEEN :f AND :t AND LoanType IN (:cap, :intr) {status}"""), p):
        add(r.ECode.strip(), "02-LOAN", r.LoanType, r.LoanDate, loan=float(r.LoanAmt), loan_int=float(r.InterestAmt))
    for r in db.execute(text(f"""
        SELECT DISTINCT ECode, EDate, {k['wcap']} cap, {k['wint']} intr FROM paywages
        WHERE {SC} AND EDate BETWEEN :f AND :t AND ({k['wcap']} <> 0 OR {k['wint']} <> 0)"""), p):
        add(r.ECode.strip(), "03-DED", k["cap"], r.EDate, ded=float(r.cap), ded_int=float(r.intr))
    for r in db.execute(text(f"""
        SELECT DISTINCT ECode, ToDate, RepayCapital, RepayInterest FROM payloanadjust
        WHERE {SC} AND {k['adj']} IN (:cap, :intr) AND FromDate >= :f AND ToDate <= :t"""), p):
        add(r.ECode.strip(), "04-REPAY", "", r.ToDate, repay=float(r.RepayCapital), repay_int=float(r.RepayInterest))
    return lines


def _summed(lines: list[dict], key) -> list[dict]:
    """Lines added up per key (legacy GROUP BY ... HAVING any sum <> 0)."""
    acc: dict = {}
    for ln in lines:
        s = acc.setdefault(key(ln), {**ln, **dict.fromkeys(AMOUNTS, 0.0)})
        for a in AMOUNTS:
            s[a] += ln[a]
    return [s for s in acc.values() if any(abs(s[a]) > 0.004 for a in AMOUNTS)]


# ─── Layouts ───────────────────────────────────────────────────────────────


def _amount_cols(interest: bool) -> list[dict]:
    if not interest:
        return [_num("op", "Opening", 110), _num("loan", "Addition", 110), _num("repay", "Adjustment", 110),
                _num("ded", "Return", 110), _num("bal", "Closing", 110)]
    return [_num("op", "Opening Capital", 120), _num("op_int", "Opening Interest", 120),
            _num("loan", "Addition Capital", 120), _num("loan_int", "Addition Interest", 120),
            _num("repay", "Adjustment Capital", 130), _num("repay_int", "Adjustment Interest", 130),
            _num("ded", "Return Capital", 120), _num("ded_int", "Return Interest", 120),
            _num("bal", "Closing Capital", 120), _num("bal_int", "Closing Interest", 120)]


def _sums(interest: bool) -> list[str]:
    return list(AMOUNTS) if interest else ["op", "loan", "repay", "ded", "bal"]


def _summary(db, b, f, t, kind: str):
    """*RegisterSummary_NJB: one line per employee (by grade, ECode) and a grand total."""
    interest = kind == "pf"
    det = _summed(_register(db, b, f, t, kind), lambda ln: ln["ecode"])
    det.sort(key=lambda d: (d["grade"], d["ecode"]))
    for d in det:
        d["emp"] = f"{d['ecode']} - {d['ename']}"
    cols = [_col("emp", "Employee", width=260), *_amount_cols(interest)]
    return cols, _layout(det, [], _sums(interest), "emp", "emp")


def _by_date(db, b, f, t, kind: str, ecode: str = ""):
    """*RegisterFortnight_NJB / *RegisterWorker_NJB: the lines by date under each employee."""
    interest = kind == "pf"
    lines = _register(db, b, f, t, kind, ecode)
    live = {ln["ecode"] for ln in lines if any(abs(ln[a]) > 0.004 for a in AMOUNTS)}
    det = [dict(ln, k_emp=f"{ln['ecode']} - {ln['ename']}", date=_dmy(ln["doc_date"]))
           for ln in lines if ln["ecode"] in live]
    # legacy: group sort on "ECode - EName", then ORDER BY DocDate, PType, LoanType DESC
    det.sort(key=lambda d: d["lt"].upper(), reverse=True)
    det.sort(key=lambda d: (d["k_emp"], d["doc_date"], d["ptype"]))
    cols = [_col("grp", "Employee", width=260), _col("date", "Date", width=110), *_amount_cols(interest)]
    # legacy PF layouts have no group footer; the advance ones total each employee
    return cols, _layout(det, [lambda d: d["k_emp"]], _sums(interest), "grp", "date", grand=False,
                         footers=not interest)


def _nr_summary(db, b, f, t, extra):
    """PFNRLoanRegisterSummary_NJB: NR loans per employee with the latest sanction. Legacy only fills
    Opening (NR loans before From) and Addition (NR loans in the period); Adjustment / Return / Closing
    are always 0 there and so here."""
    comp, loc = _scope(b)
    p = {"c": comp, "l": loc, "f": f, "t": t}
    emp = _employees(db)
    ecodes = {r[0].strip() for r in db.execute(text(
        f"SELECT ECode FROM payoloan WHERE {SC} UNION SELECT ECode FROM payloanadjust WHERE {SC}"), p)}
    latest, op = {}, collections.defaultdict(float)
    for r in db.execute(text(f"""
        SELECT ECode, LoanDate, LoanAmt FROM payoloan WHERE {SC} AND LoanType = 'NRLoan'
        ORDER BY LoanDate"""), p):
        e = r.ECode.strip()
        latest[e] = (r.LoanDate, float(r.LoanAmt))  # legacy TOP 1 ... ORDER BY LoanDate DESC
        if r.LoanDate < f:
            op[e] += float(r.LoanAmt)
    lines = [{"ecode": e, "loan_date": latest.get(e, (None, 0))[0], "sanction": latest.get(e, (None, 0))[1],
              "op": op[e], "loan": 0.0} for e in ecodes if e in emp]
    lines += [{"ecode": r.ECode.strip(), "loan_date": r.LoanDate, "sanction": float(r.LoanSanction),
               "op": 0.0, "loan": float(r.LoanAmt)} for r in db.execute(text(f"""
        SELECT DISTINCT ECode, LoanDate, LoanSanction, LoanAmt, InterestAmt FROM payoloan
        WHERE {SC} AND LoanType = 'NRLoan' AND LoanDate BETWEEN :f AND :t"""), p) if r.ECode.strip() in emp]
    acc: dict = {}
    for ln in lines:
        s = acc.setdefault((ln["ecode"], ln["loan_date"], ln["sanction"]), {**ln, "op": 0.0, "loan": 0.0})
        s["op"] += ln["op"]
        s["loan"] += ln["loan"]
    det = [dict(s, emp=f"{s['ecode']} - {emp[s['ecode']][0]}", grade=emp[s["ecode"]][1],
                ld=_dmy(s["loan_date"]), repay=0.0, ded=0.0, bal=0.0)
           for s in acc.values() if abs(s["op"]) > 0.004 or abs(s["loan"]) > 0.004]
    det.sort(key=lambda d: (d["grade"], d["ecode"], d["loan_date"] or f))
    cols = [_col("emp", "Employee", width=260), _num("sanction", "LoanSanction", 110),
            _col("ld", "LoanDate", width=110), *_amount_cols(False)]
    return cols, _layout(det, [], ["op", "loan", "repay", "ded", "bal"], "emp", "emp")


def _nr_worker(db, b, f, t, extra):
    """PFNRLoanRegisterWorker_NJB: opening and the period's NR loans by date under each employee
    (legacy fills no Adjustment / Return / Closing)."""
    comp, loc = _scope(b)
    p = {"c": comp, "l": loc, "f": f, "t": t}
    emp = _employees(db)
    lines = [(r.ECode, "01-OP", f, float(r.op), 0.0) for r in db.execute(text(f"""
        SELECT ECode, SUM(IF(LoanDate < :f, LoanAmt, 0)) op FROM payoloan
        WHERE {SC} AND LoanType = 'NRLoan' GROUP BY ECode"""), p)]
    lines += [(r.ECode, "02-LOAN", r.LoanDate, 0.0, float(r.LoanAmt)) for r in db.execute(text(f"""
        SELECT DISTINCT ECode, LoanDate, LoanAmt, InterestAmt FROM payoloan
        WHERE {SC} AND LoanType = 'NRLoan' AND LoanDate BETWEEN :f AND :t"""), p)]
    det = []
    for e, ptype, d, op, loan in lines:
        e = e.strip()
        if e in emp and (not extra or e == extra):
            det.append({"k_emp": f"{e} - {emp[e][0]}", "ecode": e, "doc_date": d, "ptype": ptype, "date": _dmy(d),
                        "op": op, "loan": loan, "repay": 0.0, "ded": 0.0, "bal": 0.0})
    live = {d["ecode"] for d in det if d["op"] or d["loan"]}
    det = sorted((d for d in det if d["ecode"] in live), key=lambda d: (d["k_emp"], d["doc_date"], d["ptype"]))
    cols = [_col("grp", "Employee", width=260), _col("date", "Date", width=110), *_amount_cols(False)]
    return cols, _layout(det, [lambda d: d["k_emp"]], [], "grp", "date", grand=False, footers=False)


def _salary_advance(db, b, t, column: str, prefix: str):
    """SpecialAdvanceList_NJB / WagesAdvanceList_NJB: staff salary advance given (+) and recovered (-)
    up to the FNE date, employees with a balance still out."""
    comp, loc = _scope(b)
    emp = _employees(db)
    rows = db.execute(text(f"""
        SELECT ECode, SUM(IF({column} > 0, {column}, 0)) given, SUM(IF({column} < 0, -{column}, 0)) taken
        FROM PaySalary WHERE {SC} AND EDate <= :t GROUP BY ECode HAVING SUM({column}) > 0
        ORDER BY ECode"""), {"c": comp, "l": loc, "t": t})
    det = [{"ecode": r.ECode.strip(), "ename": emp.get(r.ECode.strip(), ("", ""))[0], "given": float(r.given),
            "taken": float(r.taken), "bal": float(r.given) - float(r.taken)} for r in rows]
    cols = [_col("ecode", "ECode", width=110), _col("ename", "EName", width=260),
            _num("given", f"{prefix}Given", 120), _num("taken", f"{prefix}Taken", 120),
            _num("bal", f"{prefix}Bal", 120)]
    return cols, _layout(det, [], ["given", "taken", "bal"], "ecode", "ename")


def _ecode_options(kind: str):
    """Employee filter of the Worker Wise reports: employees with loans of the kind."""
    def options(db, branch_id):
        comp, loc = _scope(branch_id)
        k = KINDS.get(kind, {"cap": "NRLoan", "intr": ""})
        emp = _employees(db)
        rows = db.execute(text(f"SELECT DISTINCT ECode FROM payoloan WHERE {SC} AND LoanType IN (:cap, :intr)"),
                          {"c": comp, "l": loc, "cap": k["cap"], "intr": k["intr"]})
        codes = sorted({r[0].strip() for r in rows} & emp.keys())
        return [{"value": e, "label": f"{e} - {emp[e][0]}"} for e in codes]
    return options


def _spec(title, build, extra=None, dates="range"):
    return {"title": title, "dates": dates, "span": "month", "max_days": 400, "extra": extra, "build": build}


def _worker(kind):
    return {"label": "Employee", "options": _ecode_options(kind)}


REPORTS: dict[str, dict[str, dict]] = {"loanAndAdvances": {
    "pfLoanRegisterSummay": _spec("PF Loan Register Summay", lambda db, b, f, t, x: _summary(db, b, f, t, "pf")),
    "pfLoanRegisterFortnightWise": _spec("PF Loan Register Fortnight Wise",
                                         lambda db, b, f, t, x: _by_date(db, b, f, t, "pf")),
    "pfLoanRegisterWorkerWise": _spec("PF Loan Register Worker Wise",
                                      lambda db, b, f, t, x: _by_date(db, b, f, t, "pf", x), _worker("pf")),
    "pfNrLoanRegisterSummary": _spec("PF NR Loan Register Summary", _nr_summary),
    "pfNrLoanRegisterWorkerWise": _spec("PF NR Loan Register Worker Wise", _nr_worker, _worker("nr")),
    "advanceRegisterSummary": _spec("Advance Register Summary", lambda db, b, f, t, x: _summary(db, b, f, t, "adv")),
    "advanceRegisterFortnightWise": _spec("Advance Register Fortnight Wise",
                                          lambda db, b, f, t, x: _by_date(db, b, f, t, "adv")),
    # ponytail: legacy AdvanceRegisterWorker_NJB.rpt was not available (would not load) — derived as the
    # Fortnight report with the Employee filter, as PFLoanRegisterWorker_NJB is to PFLoanRegisterFortnight_NJB.
    "advanceRegisterWorkerWise": _spec("Advance Register Worker Wise",
                                       lambda db, b, f, t, x: _by_date(db, b, f, t, "adv", x), _worker("adv")),
    # ponytail: legacy SpecialAdvanceRegisterSummary_NJB.rpt was not available — derived (see KINDS["spl"]).
    "specialAdvanceRegisterSummary": _spec("Special Advance Register Summary",
                                           lambda db, b, f, t, x: _summary(db, b, f, t, "spl")),
    # ponytail: legacy "Special AdvanceRegisterWorker_NJB.rpt" was not available — derived (see KINDS["spl"]).
    "specialAdvanceRegisterWorkerWise": _spec("Special Advance Register Worker Wise",
                                              lambda db, b, f, t, x: _by_date(db, b, f, t, "spl", x), _worker("spl")),
    # legacy reads only ToDate (FNE date) for the two lists
    "detailsOfSpecialAdvance": _spec("DETAILS OF SPECIAL ADVANCE",
                                     lambda db, b, f, t, x: _salary_advance(db, b, t, "SpecialAdvance", "SpAdv"),
                                     dates="single"),
    "detailsOfWagesAdvance": _spec("DETAILS OF WAGES ADVANCE",
                                   lambda db, b, f, t, x: _salary_advance(db, b, t, "Advance", "WgAdv"),
                                   dates="single"),
}}
