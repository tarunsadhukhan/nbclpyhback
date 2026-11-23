"""Winsome Reports > leave (see __init__.py).

Legacy LeaveRegisterPL/CL_WIL (Crystal command on PayJOLeave) and LeaveSummary/LeaveDetails_WIL
(procs RPT_LeaveSummary / RPT_LeaveDetails over PayLeaveDetails + PayJOLeave + PayLeaveAdj), read
from the mirrored legacy tables. Like legacy, no CompCode/Location filter (winsome holds WIL only).
"""
from src.hrms.winsomereports._common import _col, _dmy, _layout, _num, rows, spec

# ─── Leave Register [PL] / [CL] ──────────────────────────────────────────────

REG_COLS = [
    _col("ECode", "ECode", width=90), _col("EName", "EName", width=200),
    _col("FromDate", "FromDate", width=95), _col("ToDate", "ToDate", width=95),
    _num("PL", "PL", 60), _num("CL", "CL", 60), _num("PF_833", "PF"), _num("BasicAmt", "Basic"),
    _num("BasicInc", "Basic Inc"), _num("FPF_167", "FPF"), _num("ESI_0075", "ESI"), _num("DAAmt", "DA"),
    _num("TotalDed", "TotalDed"), _num("TotalEarn", "Gross Earn"), _num("NETPay", "NET PAY"),
    _num("ROff", "ROff", 70), _num("NETPayable", "NETPayable", 100),
]
REG_SUMS = [c["field"] for c in REG_COLS[4:]]


def _register(kind: str):
    def build(db, b, f, t, extra=""):
        """LeaveRegister{kind}_WIL: PayJOLeave of fortnight `t` with {kind} > 0, grouped by DeptName."""
        det = rows(db, f"""
            SELECT ECode, EName, DeptName, FromDate, ToDate, {", ".join(REG_SUMS)}
            FROM PayJOLeave WHERE FNEDate = :t AND {kind} > 0
            ORDER BY DeptCode, DocDate, DocEntry, DocLineID""", {"t": t})
        for d in det:
            d["FromDate"], d["ToDate"] = _dmy(d["FromDate"]), _dmy(d["ToDate"])
        # ponytail: Crystal group sort is NoSortOrder = data order (DeptCode), so group by DeptName in that order
        return REG_COLS, _layout(det, [lambda d: d["DeptName"]], REG_SUMS, "ECode", "EName")
    return build


# ─── Leave Summary / Details (RPT_LeaveSummary / RPT_LeaveDetails) ───────────

BAL = ("OpPL", "OpCL", "TakenPL", "TakenCL", "AdjPL", "AdjCL", "ClPL", "ClCL")


def _balances(db, f, t, detail: bool) -> list[dict]:
    """The proc's #RPT: per ECode (detail: per ECode, P, FNEDate) opening / taken / adjust / closing PL+CL.
    Kept as the T-SQL (incl. its final UNION, which de-duplicates) so the numbers match."""
    p = (lambda n, d: f"{n} P, {d} FNEDate,") if detail else (lambda n, d: "")
    sql = f"""
    SELECT * FROM (
    WITH lt AS (SELECT ECode, MAX(EDate) MEDate FROM PayLeaveDetails WHERE EDate < :t GROUP BY ECode),
         le AS (SELECT ECode, MAX(EDate) MEDate FROM PayLeaveDetails WHERE EDate <= :t GROUP BY ECode)
    SELECT {"P, FNEDate," if detail else ""} A.ECode, IFNULL(E.EName,'') EName, IFNULL(E.EGroup,'') EGroup,
           IFNULL(E.DeptCode,'') DeptCode, IFNULL(E.DeptName,'') DeptName,
           SUM(OpPL) OpPL, SUM(OpCL) OpCL, SUM(TakenPL) TakenPL, SUM(TakenCL) TakenCL,
           SUM(AdjPL) AdjPL, SUM(AdjCL) AdjCL, SUM(ClPL) ClPL, SUM(ClCL) ClCL,
           SUM(OpML) OpML, SUM(TakenML) TakenML, SUM(AdjML) AdjML, SUM(ClML) ClML
    FROM (
        SELECT {p(1, "CAST(:f AS DATE)")} ECode, SUM(ClPL) OpPL, SUM(ClCL) OpCL, SUM(ClML) OpML, 0 TakenPL, 0 TakenCL, 0 TakenML,
               0 AdjPL, 0 AdjCL, 0 AdjML, 0 ClPL, 0 ClCL, 0 ClML
        FROM (
            SELECT T0.ECode, T0.ClPL, T0.ClCL, T0.ClML FROM PayLeaveDetails T0
            JOIN lt ON T0.ECode = lt.ECode AND T0.EDate = lt.MEDate
            UNION ALL
            SELECT T0.ECode, -SUM(PL), -SUM(CL), -SUM(ML) FROM PayJOLeave T0
            JOIN lt ON T0.ECode = lt.ECode WHERE T0.FNEDate >= lt.MEDate AND T0.FNEDate < :f GROUP BY T0.ECode
            UNION ALL
            SELECT T0.ECode, -SUM(PL), -SUM(CL), -SUM(ML) FROM PayLeaveAdj T0
            JOIN lt ON T0.ECode = lt.ECode WHERE T0.AdjDate >= lt.MEDate AND T0.AdjDate < :f GROUP BY T0.ECode
        ) X GROUP BY ECode
        UNION ALL
        SELECT {p(2, "FNEDate")} ECode, 0, 0, 0, SUM(PL), SUM(CL), SUM(ML), 0, 0, 0, 0, 0, 0
        FROM PayJOLeave WHERE FNEDate BETWEEN :f AND :t GROUP BY ECode{", FNEDate" if detail else ""}
        UNION ALL
        SELECT {p(3, "T0.AdjDate")} T0.ECode, 0, 0, 0, 0, 0, 0, SUM(PL), SUM(CL), SUM(ML), 0, 0, 0
        FROM PayLeaveAdj T0 JOIN lt ON T0.ECode = lt.ECode
        WHERE T0.AdjDate >= lt.MEDate AND T0.AdjDate <= :t GROUP BY T0.ECode, T0.AdjDate
        UNION
        SELECT {p(4, "CAST(:t AS DATE)")} ECode, 0, 0, 0, 0, 0, 0, 0, 0, 0, SUM(ClPL), SUM(ClCL), SUM(ClML)
        FROM (
            SELECT T0.ECode, T0.ClPL, T0.ClCL, T0.ClML FROM PayLeaveDetails T0
            JOIN le ON T0.ECode = le.ECode AND T0.EDate = le.MEDate
            UNION ALL
            SELECT T0.ECode, -SUM(PL), -SUM(CL), -SUM(ML) FROM PayJOLeave T0
            JOIN lt ON T0.ECode = lt.ECode WHERE T0.FNEDate >= lt.MEDate AND T0.FNEDate <= :t GROUP BY T0.ECode
            UNION ALL
            SELECT T0.ECode, -SUM(PL), -SUM(CL), -SUM(ML) FROM PayLeaveAdj T0
            JOIN lt ON T0.ECode = lt.ECode WHERE T0.AdjDate >= lt.MEDate AND T0.AdjDate <= :t GROUP BY T0.ECode
        ) X GROUP BY ECode
    ) A LEFT JOIN PayOEMP E ON E.ECode = A.ECode
    GROUP BY A.ECode{", P, FNEDate" if detail else ""}, E.EName, E.EGroup, E.DeptCode, E.DeptName
    ) R WHERE OpPL <> 0 OR OpCL <> 0 OR OpML <> 0 OR TakenPL <> 0 OR TakenCL <> 0 OR TakenML <> 0
        OR AdjPL <> 0 OR AdjCL <> 0 OR AdjML <> 0 OR ClPL <> 0 OR ClCL <> 0 OR ClML <> 0
    ORDER BY DeptCode, EGroup, ECode{", P, FNEDate" if detail else ""}"""
    return rows(db, sql, {"f": f, "t": t})


def _bal_cols(*lead) -> list[dict]:
    return [*lead, *(_num(k, f"{h} {k[-2:]}", 85) for k, h in zip(BAL, (
        "Opening", "Opening", "Taken", "Taken", "Adjust", "Adjust", "Closing", "Closing")))]


def leave_summary(db, b, f, t, extra=""):
    """LeaveSummary_WIL: one line per employee (no group bands / totals in the legacy layout)."""
    cols = _bal_cols(_col("ECode", "ECode", width=90), _col("EName", "EName", width=200),
                     _col("DeptCode", "Dept Code", width=80), _col("EGroup", "EGroup", width=120))
    return cols, _balances(db, f, t, False)


def leave_details(db, b, f, t, extra=""):
    """LeaveDetails_WIL: Dept / EGroup band, employee header, dated lines (opening, taken per fortnight,
    adjustments, closing) and a TOTAL per employee."""
    out, dept, emp = [], None, None
    for d in _balances(db, f, t, True):
        if (d["DeptCode"], d["EGroup"]) != dept:
            dept = (d["DeptCode"], d["EGroup"])
            out.append({"ECode": f"{d['DeptCode']} - {d['DeptName']}", "EName": d["EGroup"]})
        if d["ECode"] != emp:
            emp = d["ECode"]
            out.append({"ECode": emp, "EName": d["EName"]})
            out.append(tot := {"FNEDate": "TOTAL", **dict.fromkeys(BAL, 0.0)})
        out.insert(len(out) - 1, {"FNEDate": _dmy(d["FNEDate"]), **{k: d[k] for k in BAL}})
        for k in BAL:
            tot[k] = round(tot[k] + d[k], 2)
    cols = _bal_cols(_col("ECode", "ECode", width=200), _col("EName", "EName", width=200),
                     _col("FNEDate", "Date", width=95))
    return cols, out


REPORTS: dict[str, dict[str, dict]] = {"leave": {
    "leaveRegisterPl": spec("Leave Register [ PL ]", _register("PL"), dates="single"),
    "leaveRegisterCl": spec("Leave Register [ CL ]", _register("CL"), dates="single"),
    "leaveSummary": spec("Leave Summary", leave_summary),
    "leaveDetails": spec("Leave Details", leave_details),
}}
