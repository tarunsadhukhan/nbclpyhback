"""
NBJCL Reports > Outsider and NBJCL Reports > NEW — ports of the legacy Smart-Eye Crystal reports
(Reports/SmartEyeReportMulti/*_NJB.rpt) of those two report-master groups.

Every report reads the legacy pay tables mirrored into the tenant DB under their legacy names:
PayOPWG (outsider / provisional daily wages), paywages (fortnight wages), PaySalary, PayOEMP,
PayCummOP, payoloan (legacy PayOLoan; the upper-case PayOLoan copy is older) and payloanadjust.
Each Crystal SQL command is translated as-is (T-SQL -> MySQL) and its groups / totals are laid out
with nbjclAttendanceReports._layout. PayOEMP is utf8mb4_0900_ai_ci and the other mirrors
utf8mb4_unicode_ci, so every comparison against a PayOEMP column carries UCI.

ponytail: like legacy, only Daily Provisional Wages Sheet filters on CompCode / Location; the rest
read the whole mirror (one mill, NJB). _scope() still refuses branches without legacy pay data.
"""
import collections

from sqlalchemy.sql import text

from src.hrms.nbjclAttendanceReports import _col, _days, _dmy, _layout, _num
from src.hrms.wagesSalaryProcess import UCI, _scope


def _rows(db, sql: str, **k) -> list[dict]:
    return [dict(r._mapping) for r in db.execute(text(sql), k)]


def _f(v) -> float:
    return float(v or 0)


# ─── Outsider ──────────────────────────────────────────────────────────────


# filter options are built for every report by the shared /setup call, so they must not raise for a
# branch without legacy data (_scope would): they just list what PayOPWG holds


def _main_shifts(db, b) -> list[dict]:
    return [{"value": r[0], "label": r[0]} for r in db.execute(text(
        "SELECT DISTINCT LEFT(WShift, 1) FROM PayOPWG WHERE IFNULL(WShift, '') <> '' ORDER BY 1"))]


def _opwg_depts(db, b) -> list[dict]:
    return [{"value": r.DeptCode, "label": f"{r.DeptCode} - {r.DeptName}"} for r in db.execute(text("""
        SELECT DeptCode, MAX(DeptName) DeptName FROM PayOPWG WHERE IFNULL(DeptCode, '') <> ''
        GROUP BY DeptCode ORDER BY DeptCode"""))]


def provisional_wages(db, b, f, t, extra):
    """PayOPWG_NJB: one day's provisional wages per worker by shift, department and occupation, with
    the department's paid total. SlNo restarts per department (legacy ROW_NUMBER by DeptCode)."""
    comp, loc = _scope(b)
    rows = _rows(db, """
        SELECT ECode, EName, DeptCode, DeptName, OcpCode, Designation, LEFT(WShift, 1) AS wshift,
               SUM(Shift_HR) shift_hr, SUM(Work_HR) work_hr, Rate, SUM(PaidAmt) paid
        FROM PayOPWG
        WHERE CompCode = :c AND Location = :l AND EffDate = :t AND (:ms = '' OR LEFT(WShift, 1) = :ms)
        GROUP BY LEFT(WShift, 1), ECode, EName, DeptCode, DeptName, OcpCode, Designation, Rate
    """, c=comp, l=loc, t=t, ms=extra)
    # legacy groups: shift (record order), "DeptName [ DeptCode ]" (record order = DeptCode),
    # "Designation [ OcpCode ]" ascending
    rows.sort(key=lambda r: (r["wshift"], r["DeptCode"], f"{r['Designation']} [ {r['OcpCode']} ] ", r["ECode"]))
    slno: collections.Counter = collections.Counter()
    det = []
    for r in rows:
        slno[r["DeptCode"]] += 1
        det.append({"k_shift": f"SHIFT : {r['wshift']}", "k_dept": f"{r['DeptName']} [ {r['DeptCode']} ] ",
                    "slno": slno[r["DeptCode"]], "ecode": r["ECode"], "ename": r["EName"],
                    "desig": r["Designation"], "work_hr": _f(r["work_hr"]), "rate": _f(r["Rate"]),
                    "paid": _f(r["paid"])})
    cols = [_col("grp", "Shift / Department", width=230), _num("slno", "SlNo", 70), _col("ecode", "ECode", width=110),
            _col("ename", "EName", width=220), _col("desig", "Designation", width=200), _num("work_hr", "Work HR"),
            _num("rate", "Rate"), _num("paid", "Paid Amt", 100), _col("sign", "Signature", width=120)]
    return cols, _layout(det, [lambda d: d["k_shift"], lambda d: d["k_dept"]], ["work_hr", "paid"], "grp", "ecode")


def _opwg_summary(db, f, t) -> list[dict]:
    """OutSiderPaymentSummary(2)_NJB command: heads / hands / hours / paid per date and department."""
    return _rows(db, """
        SELECT EffDate, DeptCode, DeptName, COUNT(*) heads, SUM(Work_HR) / 8 hands, SUM(Work_HR) work_hr,
               SUM(PaidAmt) paid
        FROM PayOPWG WHERE EffDate BETWEEN :f AND :t
        GROUP BY EffDate, DeptCode, DeptName ORDER BY EffDate, DeptCode, DeptName
    """, f=f, t=t)


def _xtab(db, b, f, t, code: bool, measures: list[tuple[str, str]]):
    """The legacy cross-tab: a line per department and measure, a column per date and a Total column,
    closed by a Total line of the paid amount (as printed)."""
    _scope(b)
    days = _days(f, t, limit=31)
    grid: dict = {}
    for r in _opwg_summary(db, f, t):
        k = (r["DeptCode"], r["DeptName"]) if code else r["DeptName"]
        g = grid.setdefault(k, {m: [0.0] * len(days) for m, _ in measures})
        if r["EffDate"] in days:
            for m, _ in measures:
                g[m][days.index(r["EffDate"])] += _f(r[m])
    out, paid = [], [0.0] * len(days)
    for k in sorted(grid):
        for j, (m, label) in enumerate(measures):
            line = {"measure": label, **{f"d{i}": round(v, 3) for i, v in enumerate(grid[k][m])},
                    "total": round(sum(grid[k][m]), 3)}
            if j == 0:
                line.update({"code": k[0], "dept": k[1]} if code else {"dept": k})
            out.append(line)
        paid = [a + c for a, c in zip(paid, grid[k]["paid"])]
    if out:
        out.append({("code" if code else "dept"): "Total", "measure": "Paid Amt",
                    **{f"d{i}": round(v, 3) for i, v in enumerate(paid)}, "total": round(sum(paid), 3)})
    cols = ([_col("code", "Code", width=80)] if code else []) + [
        _col("dept", "DEPARTMENT", width=200), _col("measure", "", width=90),
        *[_num(f"d{i}", d.strftime("%d/%m"), 75) for i, d in enumerate(days)], _num("total", "Total", 100)]
    return cols, out


def payment_summary(db, b, f, t, extra):
    """OutSiderPaymentSummary_NJB (cross-tab): per department name paid amount, hands and work hours
    for each date of the period."""
    return _xtab(db, b, f, t, False, [("paid", "Paid Amt"), ("hands", "Hands"), ("work_hr", "Work HR")])


def payment_summary_dept(db, b, f, t, extra):
    """OutSiderPaymentSummary2_NJB (cross-tab): per department code paid amount and hands for each date."""
    return _xtab(db, b, f, t, True, [("paid", "Paid Amt"), ("hands", "Hands")])


_SUMM = ["heads", "hands", "work_hr", "paid"]


def payment_details(db, b, f, t, extra):
    """OutSiderPaymentDtl_NJB: paid lines (rate > 0) per date and department, with department, date
    and grand totals of work hours and paid amount."""
    _scope(b)
    rows = _rows(db, """
        SELECT EffDate, DeptCode, DeptName, OcpCode, Designation, ECode, EName, COUNT(*) heads,
               SUM(Work_HR) work_hr, SUM(PaidAmt) paid
        FROM PayOPWG WHERE EffDate BETWEEN :f AND :t AND Rate > 0 AND (:d = '' OR DeptCode = :d)
        GROUP BY EffDate, DeptCode, DeptName, OcpCode, Designation, ECode, EName
        ORDER BY EffDate, DeptCode, DeptName
    """, f=f, t=t, d=extra)
    det = [{"wdate": r["EffDate"], "k_dept": f"{r['DeptCode']} - {r['DeptName']}", "ecode": r["ECode"],
            "ename": r["EName"], "desig": r["Designation"], "work_hr": _f(r["work_hr"]), "paid": _f(r["paid"])}
           for r in rows]
    det.sort(key=lambda d: (d["wdate"], d["k_dept"]))  # stable: keeps the command's order inside a group
    cols = [_col("grp", "Date", width=110), _col("ecode", "ECode", width=230), _col("ename", "EName", width=220),
            _col("desig", "Designation", width=200), _num("work_hr", "Work HR"), _num("paid", "Paid Amt", 110),
            _col("sign", "Dept. Incharge", width=130)]
    return cols, _layout(det, [lambda d: _dmy(d["wdate"]), lambda d: d["k_dept"]], ["work_hr", "paid"], "grp", "ecode")


def payment_summary_dept_wise(db, b, f, t, extra):
    """Outsider Payment Summary [ Dept. Wise] — PayOPWG_DeptWiseSumm_NJB.
    ponytail: legacy .rpt not available (it fails to load); derived from PayOPWG_NJB: the day's
    provisional wages per shift and department as heads, hands, work hours and paid amount."""
    comp, loc = _scope(b)
    rows = _rows(db, """
        SELECT LEFT(WShift, 1) wshift, DeptCode, DeptName, COUNT(DISTINCT ECode) heads,
               SUM(Work_HR) / 8 hands, SUM(Work_HR) work_hr, SUM(PaidAmt) paid
        FROM PayOPWG WHERE CompCode = :c AND Location = :l AND EffDate = :t
        GROUP BY LEFT(WShift, 1), DeptCode, DeptName ORDER BY 1, DeptCode
    """, c=comp, l=loc, t=t)
    det = [{"k_shift": f"SHIFT : {r['wshift']}", "dept": f"{r['DeptName']} [ {r['DeptCode']} ]",
            **{k: _f(r[k]) for k in _SUMM}} for r in rows]
    cols = [_col("grp", "Shift", width=110), _col("dept", "Department", width=240), _num("heads", "Heads"),
            _num("hands", "Hands"), _num("work_hr", "Work HR"), _num("paid", "Paid Amt", 110)]
    return cols, _layout(det, [lambda d: d["k_shift"]], _SUMM, "grp", "dept")


# ─── NEW ───────────────────────────────────────────────────────────────────


def non_working(db, b, f, t, extra):
    """NonWorkingList_NJB: workers paid in some fortnight since 1 January of the date's year but not in
    the fortnight ending on the date, with their work days and last fortnight (LWFN)."""
    _scope(b)
    jan1 = t.replace(month=1, day=1)
    rows = _rows(db, f"""
        SELECT T0.ECode, T1.CardNo, T1.EGroup, T1.EName, SUM(T0.Work_Day) work_day, MAX(T0.EDate) lwfn
        FROM paywages T0 JOIN PayOEMP T1 ON T1.ECode {UCI} = T0.ECode
        WHERE T0.EDate >= :f
          AND T0.ECode NOT IN (SELECT ECode FROM paywages WHERE EDate = :t)
        GROUP BY T0.ECode, T1.CardNo, T1.EGroup, T1.EName
        ORDER BY T0.ECode, T1.CardNo, T1.EGroup, T1.EName
    """, f=jan1, t=t)
    det = [{"ecode": r["ECode"], "card": r["CardNo"], "egroup": r["EGroup"], "ename": r["EName"],
            "work_day": _f(r["work_day"]), "lwfn": _dmy(r["lwfn"])} for r in rows]
    cols = [_col("ecode", "ECode", width=100), _col("card", "CardNo", width=100), _col("egroup", "EGroup", width=200),
            _col("ename", "EName", width=240), _num("work_day", "W.Days"), _col("lwfn", "LWFN", width=110)]
    return cols, _layout(det, [], ["work_day"], "ecode", "card")


def _advance_statement(db, b, t, staff: bool):
    """AdvanceStatement_Worker / _Staff_NJB: the fortnight's advance and special-advance deductions and
    the balances (loans given less adjustments less wage deductions) on the date. The staff variant
    only counts wage deductions of slips with an advance (legacy @CutOff = '' is 1900, i.e. no cut)."""
    _scope(b)
    only_adv = "AND Advance > 0" if staff else ""
    rows = _rows(db, f"""
        SELECT * FROM (
          SELECT T0.ECode, T0.CardNo, T0.EName, T1.SplAdvance, T1.Advance,
            IFNULL((SELECT SUM(LoanAmt) FROM payoloan WHERE DocStatus = 'OPEN' AND LoanType = 'Spl Advance'
                      AND LoanDate <= :t AND ECode = T0.ECode {UCI}), 0)
            - IFNULL((SELECT SUM(RepayCapital) FROM payloanadjust WHERE LoanType = 'SPL ADVANCE'
                      AND ToDate <= :t AND ECode = T0.ECode {UCI}), 0)
            - IFNULL((SELECT SUM(SplAdvance) FROM paywages WHERE EDate <= :t AND ECode = T0.ECode {UCI}
                      {only_adv}), 0) AS spl_bal,
            IFNULL((SELECT SUM(LoanAmt) FROM payoloan WHERE DocStatus = 'OPEN' AND LoanType = 'Advance'
                      AND LoanDate <= :t AND ECode = T0.ECode {UCI}), 0)
            - IFNULL((SELECT SUM(RepayCapital) FROM payloanadjust WHERE LoanType = 'ADVANCE'
                      AND ToDate <= :t AND ECode = T0.ECode {UCI}), 0)
            - IFNULL((SELECT SUM(Advance) FROM paywages WHERE EDate <= :t AND ECode = T0.ECode {UCI}
                      {only_adv}), 0) AS adv_bal
          FROM PayOEMP T0 JOIN paywages T1 ON T1.ECode = T0.ECode {UCI}
          WHERE T1.EDate = :t AND T0.Grade = :g
        ) x
        WHERE SplAdvance <> 0 OR Advance <> 0 OR spl_bal <> 0 OR adv_bal <> 0
        ORDER BY ECode, CardNo, EName
    """, t=t, g="STAFF" if staff else "MILL-WORKMEN")
    det = [{"ecode": r["ECode"], "card": r["CardNo"], "ename": r["EName"], "spl": _f(r["SplAdvance"]),
            "spl_bal": _f(r["spl_bal"]), "adv": _f(r["Advance"]), "adv_bal": _f(r["adv_bal"])} for r in rows]
    cols = [_col("ecode", "ECode", width=100), _col("card", "CardNo", width=100), _col("ename", "EName", width=240),
            _num("spl", "Spl Adv Ded", 110), _num("spl_bal", "Spl Adv Bal", 110), _num("adv", "Advance", 100),
            _num("adv_bal", "AdvanceBal", 110)]
    return cols, _layout(det, [], ["spl", "spl_bal", "adv", "adv_bal"], "ecode", "card")


def advance_worker(db, b, f, t, extra):
    return _advance_statement(db, b, t, staff=False)


def advance_staff(db, b, f, t, extra):
    return _advance_statement(db, b, t, staff=True)


_PFL = ["op_loan", "op_int", "loan", "loan_int", "repay_loan", "repay_int", "ded_loan", "ded_int", "bal_loan", "bal_int"]


def pf_loan_summary(db, b, f, t, extra):
    """PFLoanRegisterSummary_NJB_2: per employee the PF loan and interest opening, additions,
    adjustments (repayments), wage deductions ("Return") and closing for the period. A line is keyed by
    the latest loan date / sanction like legacy, so an employee can show on more than one line.
    Legacy quirks kept: the capital opening nets RebateAmt off repayments, the interest closing too."""
    _scope(b)
    E = f"T0.ECode {UCI}"
    has_loan = f"{E} IN (SELECT ECode FROM payoloan UNION ALL SELECT ECode FROM payloanadjust)"
    rows = _rows(db, f"""
        SELECT ECode, EName, Grade, LoanDate, LoanSanction,
               SUM(OpLoan) op_loan, SUM(OpInt) op_int, SUM(Loan) loan, SUM(LoanInt) loan_int,
               SUM(DedLoan) ded_loan, SUM(DedInt) ded_int, SUM(RepayLoan) repay_loan, SUM(RepayInt) repay_int,
               SUM(BalLoan) bal_loan, SUM(BalInt) bal_int
        FROM (
          SELECT T0.Grade, T0.ECode {UCI} ECode, T0.EName {UCI} EName,
            (SELECT LoanDate FROM payoloan WHERE ECode = {E} AND LoanType = 'PFLoan' ORDER BY LoanDate DESC LIMIT 1) LoanDate,
            IFNULL((SELECT LoanSanction FROM payoloan WHERE ECode = {E} AND LoanType = 'PFLoan'
                    ORDER BY LoanDate DESC LIMIT 1), 0) LoanSanction,
            IFNULL((SELECT SUM(LoanAmt) FROM payoloan WHERE LoanDate < :f AND ECode = {E} AND LoanType = 'PFLoan'), 0)
            - IFNULL((SELECT SUM(PFLoanCap) FROM paywages WHERE EDate < :f AND ECode = {E}), 0)
            - IFNULL((SELECT SUM(RepayCapital - RebateAmt) FROM payloanadjust WHERE DocType = 'PFLoan'
                      AND ToDate < :f AND ECode = {E}), 0) OpLoan,
            IFNULL((SELECT SUM(InterestAmt) FROM payoloan WHERE LoanDate < :f AND ECode = {E} AND LoanType = 'PFInt'), 0)
            - IFNULL((SELECT SUM(PFLoanInt) FROM paywages WHERE EDate < :f AND ECode = {E}), 0)
            - IFNULL((SELECT SUM(RepayInterest) FROM payloanadjust WHERE DocType = 'PFInt'
                      AND ToDate < :f AND ECode = {E}), 0) OpInt,
            0 Loan, 0 LoanInt, 0 DedLoan, 0 DedInt, 0 RepayLoan, 0 RepayInt, 0 BalLoan, 0 BalInt
          FROM PayOEMP T0 WHERE {has_loan}
          UNION ALL
          SELECT T1.Grade, T0.ECode, T1.EName {UCI}, T0.LoanDate, T0.LoanSanction, 0, 0,
                 T0.LoanAmt, T0.InterestAmt, 0, 0, 0, 0, 0, 0
          FROM payoloan T0 JOIN PayOEMP T1 ON T1.ECode {UCI} = T0.ECode
          WHERE T0.LoanDate BETWEEN :f AND :t AND T0.LoanType IN ('PFLoan', 'PFInt')
          GROUP BY T1.Grade, T0.LoanType, T0.ECode, T1.EName, T0.LoanDate, T0.LoanSanction, T0.LoanAmt, T0.InterestAmt
          UNION ALL
          SELECT T1.Grade, T0.ECode, T1.EName {UCI}, NULL, 0, 0, 0, 0, 0, T0.PFLoanCap, T0.PFLoanInt, 0, 0, 0, 0
          FROM paywages T0 JOIN PayOEMP T1 ON T1.ECode {UCI} = T0.ECode
          WHERE T0.EDate BETWEEN :f AND :t AND (T0.PFLoanCap <> 0 OR T0.PFLoanInt <> 0)
          GROUP BY T1.Grade, T0.ECode, T0.EDate, T1.EName, T0.PFLoanCap, T0.PFLoanInt
          UNION ALL
          SELECT T1.Grade, T0.ECode, T1.EName {UCI}, NULL, 0, 0, 0, 0, 0, 0, 0, T0.RepayCapital, T0.RepayInterest, 0, 0
          FROM payloanadjust T0 JOIN PayOEMP T1 ON T1.ECode {UCI} = T0.ECode
          WHERE T0.DocType IN ('PFLoan', 'PFInt') AND T0.FromDate >= :f AND T0.ToDate <= :t
          GROUP BY T1.Grade, T0.ECode, T0.ToDate, T1.EName, T0.RepayCapital, T0.RepayInterest
          UNION ALL
          SELECT T0.Grade, T0.ECode {UCI}, T0.EName {UCI}, NULL, 0, 0, 0, 0, 0, 0, 0, 0, 0,
            IFNULL((SELECT SUM(LoanAmt) FROM payoloan WHERE LoanDate <= :t AND ECode = {E} AND LoanType = 'PFLoan'), 0)
            - IFNULL((SELECT SUM(PFLoanCap) FROM paywages WHERE EDate <= :t AND ECode = {E}), 0)
            - IFNULL((SELECT SUM(RepayCapital) FROM payloanadjust WHERE DocType = 'PFLoan'
                      AND ToDate <= :t AND ECode = {E}), 0),
            IFNULL((SELECT SUM(InterestAmt) FROM payoloan WHERE LoanDate <= :t AND ECode = {E} AND LoanType = 'PFInt'), 0)
            - IFNULL((SELECT SUM(PFLoanInt) FROM paywages WHERE EDate <= :t AND ECode = {E}), 0)
            - IFNULL((SELECT SUM(RepayInterest - RebateAmt) FROM payloanadjust WHERE DocType = 'PFInt'
                      AND ToDate <= :t AND ECode = {E}), 0)
          FROM PayOEMP T0 WHERE {has_loan}
        ) x
        GROUP BY Grade, ECode, EName, LoanDate, LoanSanction
        HAVING SUM(OpLoan) <> 0 OR SUM(OpInt) <> 0 OR SUM(Loan) <> 0 OR SUM(LoanInt) <> 0 OR SUM(DedLoan) <> 0
            OR SUM(DedInt) <> 0 OR SUM(RepayLoan) <> 0 OR SUM(RepayInt) <> 0 OR SUM(BalLoan) <> 0 OR SUM(BalInt) <> 0
        ORDER BY Grade, ECode
    """, f=f, t=t)
    det = [{"emp": f"{r['ECode']} - {r['EName']}", "sanction": _f(r["LoanSanction"]), "loan_date": _dmy(r["LoanDate"]),
            **{k: _f(r[k]) for k in _PFL}} for r in rows]
    cols = [_col("emp", "Employee", width=260), _num("sanction", "LoanSanction", 110), _col("loan_date", "LoanDate", width=105),
            _num("op_loan", "Opening Capital", 120), _num("op_int", "Opening Interest", 120),
            _num("loan", "Addition Capital", 120), _num("loan_int", "Addition Interest", 120),
            _num("repay_loan", "Adjustment Capital", 130), _num("repay_int", "Adjustment Interest", 130),
            _num("ded_loan", "Return Capital", 120), _num("ded_int", "Return Interest", 120),
            _num("bal_loan", "Closing Capital", 120), _num("bal_int", "Closing Interest", 120)]
    return cols, _layout(det, [], _PFL, "emp", "loan_date")


_PFS = ["pf_gross", "pfc", "c_pfc", "pnc", "c_pnc", "coc", "c_coc", "nremp", "nrcomp", "pf_loan_cap", "ytd_loan",
        "pf_loan_int", "ytd_int", "pensioner", "adv_r", "adv_bal", "set_adv_g", "set_adv_bal", "stl"]
_MILL_GROUPS = "('01','02','03','05','06','07','08','09','10','14','15')"


def loan_pf_statement(db, b, f, t, extra):
    """PFCont_AdvBalStatement_NJB_2: mill workers' PF gross, PF / pension / company contributions for the
    period and cumulative to date, NR loans, and PF-loan recovery / balance (YTD on the last slip),
    grouped by the first two characters of the PF number. Workers with no slip in the period but a
    cumulative opening (PayCummOP) are listed with their cumulative figures only.
    The per-worker legacy subqueries are read once per table into dicts (PayCummOP / PaySalary have no
    ECode index in the mirror).
    ponytail: legacy reads PaySalary advances with a bare scalar subquery (one row or an error); summed
    here, which is the same for one row. Pensioner / advance / SET / STL show on detail lines too
    (legacy prints them only on the group / grand totals)."""
    _scope(b)

    def by_ecode(sql: str) -> dict:
        return {r["ECode"]: r for r in _rows(db, sql, f=f, t=t)}

    sal = by_ecode("""SELECT ECode, SUM(CASE WHEN Advance > 0 THEN Advance ELSE 0 END) adv_g,
                      SUM(CASE WHEN Advance < 0 THEN -Advance ELSE 0 END) adv_r, SUM(Advance) adv_bal
                      FROM PaySalary WHERE EDate <= :t GROUP BY ECode""")
    # NR (non-refundable) PF loans: from the legacy @NRDate 01/04/2023 for workers paid in the period,
    # up to the date for the cumulative-only ones
    nr = by_ecode("""SELECT ECode, SUM(CASE WHEN LoanDate >= '2023-04-01' THEN EmployeeCont ELSE 0 END) emp_since,
                     SUM(CASE WHEN LoanDate >= '2023-04-01' THEN EmployerCont ELSE 0 END) comp_since,
                     SUM(CASE WHEN LoanDate <= :t THEN EmployeeCont ELSE 0 END) emp_to,
                     SUM(CASE WHEN LoanDate <= :t THEN EmployerCont ELSE 0 END) comp_to
                     FROM payoloan WHERE DocStatus = 'OPEN' AND LoanType = 'NRLOAN' GROUP BY ECode""")
    last = f"(SELECT {{}} FROM paywages WHERE ECode = T0.ECode {UCI} AND EDate <= :t ORDER BY EDate DESC LIMIT 1)"
    paid = _rows(db, f"""
        SELECT T0.CardNo, T0.ECode {UCI} ECode, T0.EName, T0.PFNo, SUM(T1.PF_Gross) pf_gross, SUM(T1.PFEmployee) pfc,
               SUM(T1.PFLoanCap) pf_loan_cap, SUM(T1.PFLoanInt) pf_loan_int, SUM(T1.Pension) pnc, SUM(T1.CoC) coc,
               {last.format('YTD_LoanAmt')} ytd_loan, {last.format('YTD_IntAmt')} ytd_int,
               {last.format('YTD_PFEmployee')} c_pfc, {last.format('YTD_Pension')} c_pnc, {last.format('YTD_FPF')} c_coc
        FROM PayOEMP T0 JOIN paywages T1 ON T1.ECode = T0.ECode {UCI}
        WHERE T0.Grade = 'Mill-Workmen' AND T1.EDate BETWEEN :f AND :t AND LEFT(T0.EGroup, 2) IN {_MILL_GROUPS}
        GROUP BY T0.CardNo, T0.ECode, T0.EName, T0.PFNo
    """, f=f, t=t)
    rows = []
    for r in paid:
        n, a = nr.get(r["ECode"], {}), sal.get(r["ECode"], {})
        rows.append({**r, "nremp": n.get("emp_since"), "nrcomp": n.get("comp_since"), "pensioner": 1 if _f(r["pfc"]) > 0 else 0,
                     "adv_r": a.get("adv_r"), "adv_bal": a.get("adv_bal"), "set_adv_g": a.get("adv_g"),
                     "set_adv_bal": a.get("adv_bal"), "stl": 0})
    tot = by_ecode("SELECT ECode, SUM(PFEmployee) pfc, SUM(Pension) pnc, SUM(COC) coc FROM paywages "
                   "WHERE EDate <= :t GROUP BY ECode")
    cumm = by_ecode("SELECT ECode, SUM(PFCBalance) pfc, SUM(PenBalance) pnc, SUM(COCBalance) coc FROM PayCummOP GROUP BY ECode")
    for r in _rows(db, f"""
        SELECT DISTINCT T0.CardNo, T0.ECode {UCI} ECode, T0.EName, T0.PFNo
        FROM PayOEMP T0 JOIN PayCummOP C0 ON C0.ECode = T0.ECode {UCI}
        WHERE T0.Grade = 'Mill-Workmen' AND LEFT(T0.EGroup, 2) IN {_MILL_GROUPS}
          AND T0.ECode {UCI} NOT IN (SELECT ECode FROM paywages WHERE EDate BETWEEN :f AND :t)
          AND (C0.PFCBalance <> 0 OR C0.PenBalance <> 0 OR C0.COCBalance <> 0 OR C0.YTDDays <> 0)
    """, f=f, t=t):
        n, w, c = nr.get(r["ECode"], {}), tot.get(r["ECode"], {}), cumm.get(r["ECode"], {})
        rows.append({**r, "c_pfc": _f(c.get("pfc")) + _f(w.get("pfc")) - _f(n.get("emp_to")),
                     "c_pnc": _f(c.get("pnc")) + _f(w.get("pnc")),
                     "c_coc": _f(c.get("coc")) + _f(w.get("coc")) - _f(n.get("comp_to")),
                     "nremp": n.get("emp_to"), "nrcomp": n.get("comp_to")})
    rows.sort(key=lambda r: r["ECode"])
    det = [{"k_pf": (r["PFNo"] or "")[:2], "pf_no": r["PFNo"], "ecode": r["ECode"], "card": r["CardNo"],
            "ename": r["EName"], **{k: _f(r.get(k)) for k in _PFS}} for r in rows]
    det.sort(key=lambda d: d["k_pf"])  # stable: ECode order inside a PF group
    cols = [_col("grp", "PF Group", width=90), _col("pf_no", "PFNo", width=110), _col("ecode", "ECode", width=90),
            _col("card", "Rec.No", width=90), _col("ename", "EName", width=220), _num("pf_gross", "PF Gross", 100),
            _num("pfc", "PFC 10%"), _num("c_pfc", "C.PFC 10%", 100), _num("pnc", "PNC 8.33%"),
            _num("c_pnc", "C.PNC 8.33%", 100), _num("coc", "COC 1.67%"), _num("c_coc", "C.COC 1.67%", 100),
            _num("nremp", "NREMP"), _num("nrcomp", "NRCOMP"), _num("pf_loan_cap", "PFLoan Capital", 110),
            _num("ytd_loan", "PFLoan Balance", 110), _num("pf_loan_int", "PFLoan Interest", 110),
            _num("ytd_int", "PFInt Balance", 110), _num("pensioner", "Pen-Members", 100), _num("adv_r", "Adv. Recv"),
            _num("adv_bal", "Adv. Bal"), _num("set_adv_g", "SET Recv"), _num("set_adv_bal", "SET Bal"),
            _num("stl", "STL Bal")]
    return cols, _layout(det, [lambda d: d["k_pf"]], _PFS, "grp", "pf_no")


# group (menu folder after hrms/nbjclreports/) -> {report key: spec}
REPORTS: dict[str, dict[str, dict]] = {
    "outsider": {
        "dailyProvisionalWagesSheet": {"title": "Daily Provisional Wages Sheet", "dates": "single", "span": "day",
                                       "extra": {"label": "Main Shift", "options": _main_shifts}, "build": provisional_wages},
        "outsiderPaymentSummary": {"title": "Outsider Payment Summary", "dates": "range", "max_days": 30, "extra": None,
                                   "build": payment_summary},
        "outsiderPaymentSummaryDeptcodeWise": {"title": "Outsider Payment Summary [ DeptCode Wise ]", "dates": "range", "max_days": 30,
                                               "extra": None, "build": payment_summary_dept},
        "outsiderPaymentDetails": {"title": "Outsider Payment Details", "dates": "range",
                                   "extra": {"label": "Department", "options": _opwg_depts}, "build": payment_details},
        "outsiderPaymentSummaryDeptWise": {"title": "Outsider Payment Summary [ Dept. Wise]", "dates": "single",
                                           "span": "day", "extra": None, "build": payment_summary_dept_wise},
    },
    "new": {
        "nonWorkingWorkerList": {"title": "Non-Working Worker List", "dates": "single", "extra": None, "build": non_working},
        "advanceStatementWorker": {"title": "Advance Statement [ Worker ]", "dates": "single", "extra": None,
                                   "build": advance_worker},
        "advanceStatementStaff": {"title": "Advance Statement [ STAFF ]", "dates": "single", "extra": None,
                                  "build": advance_staff},
        "pfLoanRegisterSummay2": {"title": "PF Loan Register Summay - 2", "dates": "range", "span": "month",
                                  "extra": None, "build": pf_loan_summary},
        "loanAndPfStatement": {"title": "Loan & PF Statement", "dates": "range", "span": "month", "extra": None,
                               "build": loan_pf_statement},
    },
}
