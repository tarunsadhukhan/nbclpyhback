"""Winsome Reports > Attendance Register (see __init__.py).

All reports read the legacy ATTEN mirror joined to PayOEMP / ODPT / Shift / OUNIT, exactly as the
*_WIL Crystal commands (and procs ATTN_Register, ATTN_Register_Merge, RPT_DeptWiseOcpWiseSummary) do.
Legacy view AttendanceReport = ATTEN inner-joined to PayOEMP, ODPT (dept + ocp), Shift and OUNIT.
Scope: the branch's unit (ATTEN.WUnit = '01'); the legacy commands carry no company filter.
"""
import collections
from datetime import timedelta

from src.hrms.winsomereports._common import _col, _dmy, _layout, _num, rows, scope_args, spec

WORK_GROUPS = ("PERMANENT", "CASUAL-1", "CASUAL-2", "CASUAL-3", "SPECIAL BADLI")


def _atten(db, b, f, t, shift: str = "") -> list[dict]:
    """ATTEN rows of the period with employee, ODPT, Shift and unit columns (outer-joined: each
    report applies its own legacy join rule via `odpt` / `main_shift`)."""
    out = rows(db, """
        SELECT A.ID, A.WDate AS wdate, IFNULL(A.WTime, '') AS wtime, A.WUnit AS unit, A.WShift AS wshift,
               IFNULL(A.shift_id, '') AS shift_id, A.emp_code AS ecode, IFNULL(E.EName, '') AS ename,
               IFNULL(E.Grade, '') AS grade, IFNULL(E.EGroup, '') AS egroup,
               IFNULL(E.DeptCode, '') AS e_dept, IFNULL(E.DeptName, '') AS e_dname,
               A.dept_code AS dept, A.ocp_code AS ocp, D.DeptCode IS NOT NULL AS odpt,
               IFNULL(D.OCPName, '') AS oname, IFNULL(D.EType, '') AS etype,
               CONCAT(IFNULL(D.DeptGrpCode, ''), '-', IFNULL(D.DeptGrpName, '')) AS mdept,
               IFNULL(DN.DeptName, '') AS dname, S.DES AS main_shift, IFNULL(S.ShiftHrs, 0) AS spell_hr,
               U.UName AS uname, UPPER(IFNULL(A.work_type, '')) AS work_type,
               IFNULL(A.Shift_HR, 0) AS shift_hr, IFNULL(A.GatePass_HR, 0) AS gp_hr, IFNULL(A.Work_HR, 0) AS work_hr,
               IFNULL(A.IsManual, '') AS manual,
               CASE WHEN IFNULL(A.mch1_code, '') = '-1' THEN '' ELSE IFNULL(A.mch1_code, '') END AS mch1
        FROM ATTEN A
        JOIN PayOEMP E ON E.ECode = A.emp_code
        LEFT JOIN ODPT D ON D.DeptCode = A.dept_code AND D.OCPCode = A.ocp_code
        LEFT JOIN (SELECT DeptCode, MIN(DeptName) DeptName FROM ODPT GROUP BY DeptCode) DN ON DN.DeptCode = A.dept_code
        LEFT JOIN Shift S ON S.SHIFTMSTID = A.WShift
        LEFT JOIN OUNIT U ON U.UCode = A.WUnit
        WHERE A.WDate BETWEEN :f AND :t AND A.WUnit = :u AND (:s = '' OR A.WShift = :s)
        ORDER BY A.WDate, A.ID""", scope_args(b, f=f, t=t, s=shift))
    for r in out:
        # legacy head count: 1, or 0 when the whole shift went on gate pass
        r["head"] = 0.0 if (r["gp_hr"] and r["gp_hr"] == r["shift_hr"]) else 1.0
    return out


def _shifts(db, b):
    return [{"value": r["SHIFTMSTID"], "label": r["SHIFTMSTID"]}
            for r in rows(db, "SELECT SHIFTMSTID FROM Shift ORDER BY SHIFTMSTID")]


SHIFT = {"label": "Shift", "options": _shifts}


def _uds(r) -> str:
    return f"UNIT : {r['unit']}   DATE : {_dmy(r['wdate'])}   SHIFT : {r['wshift']}"


def _agg(items, key, fields) -> list[dict]:
    """Sum `fields` of items per key(item) -> dict; key returns (sort tuple, base row)."""
    acc: dict = {}
    for it in items:
        k, base = key(it)
        line = acc.setdefault(k, {**base, **dict.fromkeys(fields, 0.0)})
        for c in fields:
            line[c] += it[c]
    return [{**v, **{c: round(v[c], 3) for c in fields}} for _, v in sorted(acc.items())]


def _wt4(r) -> dict:
    """DUTY / OT / VOUCHER / IN PLACE head counts and the row total of the summary reports."""
    h = r["head"]
    wt = r["work_type"]
    return {"duty": h if wt == "DUTY" else 0.0, "ot": h if wt == "OT" else 0.0,
            "voucher": h if wt == "VOUCHER" else 0.0, "inplace": h if wt == "IN PLACE" else 0.0, "total": h}


# ─── Reports ───────────────────────────────────────────────────────────────


def worktype_summary(db, b, f, t, extra):
    """AttendanceWorkTypeWiseSummary_WIL: head count per unit/date/shift, department and designation."""
    items = [{**r, **_wt4(r)} for r in _atten(db, b, f, t, extra) if r["odpt"]]
    fields = ["duty", "ot", "voucher", "inplace", "total"]
    det = _agg(items, lambda r: ((r["unit"], r["wdate"], r["wshift"], r["dept"], r["dname"], r["oname"]),
                                 {"k_uds": _uds(r), "k_dept": f"{r['dept']}-{r['dname']}", "desig": r["oname"]}),
               fields)
    cols = [_col("grp", "Unit / Date / Shift", width=300), _col("desig", "Desgination", width=240),
            _num("duty", "DUTY"), _num("ot", "OT"), _num("voucher", "VOUCHER"), _num("inplace", "INPLACE"),
            _num("total", "TOTAL")]
    return cols, _layout(det, [lambda d: d["k_uds"], lambda d: d["k_dept"]], fields, "grp", "desig")


def worktype_details(db, b, f, t, extra):
    """AttendanceWokTypeWiseDetails_WIL: every attendance by unit/date/shift, department and occupation,
    head count spread over MILL-WORKMEN work types / OUTSIDER / CONTRACTOR / OTHERS grades."""
    fields = ["duty", "ot", "voucher", "other", "outsider", "contractor", "others", "total"]
    det = []
    for r in _atten(db, b, f, t, extra):
        if not r["odpt"]:
            continue
        h, g, wt = r["head"], r["grade"].upper(), r["work_type"]
        mill = g == "MILL-WORKMEN"
        v = {"duty": h if mill and wt == "DUTY" else 0.0, "ot": h if mill and wt == "OT" else 0.0,
             "voucher": h if mill and wt == "VOUCHER" else 0.0,
             "other": h if mill and wt not in ("DUTY", "OT", "VOUCHER") else 0.0,
             "outsider": h if g == "OUTSIDER" else 0.0, "contractor": h if g == "CONTRACTOR" else 0.0,
             "others": h if g not in ("MILL-WORKMEN", "OUTSIDER", "CONTRACTOR") else 0.0}
        v["total"] = sum(v.values())
        desig = f"{r['ocp']} - {r['oname']}"
        det.append({"_s": (r["unit"], r["wdate"], r["wshift"], f"{r['dept']}-{r['dname']}", desig, r["mch1"],
                           r["grade"], r["ename"]),
                    "k_uds": _uds(r), "k_dept": f"{r['dept']}-{r['dname']}", "k_desig": desig,
                    "ecode": r["ecode"], "ename": r["ename"], "time": r["wtime"], "machine": r["mch1"], **v})
    det.sort(key=lambda d: d.pop("_s"))
    cols = [_col("grp", "Unit / Date / Shift", width=300), _col("ecode", "ECODE", width=200),
            _col("ename", "ENAME", width=220), _col("time", "TIME", width=70), _col("machine", "MACHINE", width=90),
            _num("duty", "DUTY"), _num("ot", "OT"), _num("voucher", "VOUR"), _num("other", "OTHR"),
            _num("outsider", "OUTSIDER"), _num("contractor", "CONTRACTOR", 100), _num("others", "OTHERS"),
            _num("total", "TOTAL")]
    return cols, _layout(det, [lambda d: d["k_uds"], lambda d: d["k_dept"], lambda d: d["k_desig"]],
                         fields, "grp", "ecode")


def ecode_details(db, b, f, t, extra):
    """AttendanceECodeWiseDetails_WIL: one line per attendance (date / shift / work type) in ECode order."""
    fields = ["duty", "ot", "voucher", "inplace"]
    items = [{**r, **_wt4(r)} for r in _atten(db, b, f, t, extra) if r["odpt"]]
    det = _agg(items, lambda r: ((r["ecode"], r["wdate"], r["wshift"], r["dept"], r["ocp"], r["work_type"]),
                                 {"ecode": r["ecode"], "ename": r["ename"], "dept": r["dname"],
                                  "desig": r["oname"]}), fields)
    cols = [_col("ecode", "ECODE", width=110), _col("ename", "ENAME", width=220),
            _col("dept", "DEPARTMENT", width=200), _col("desig", "OCCUPATION", width=220),
            _num("duty", "DUTY"), _num("ot", "OT"), _num("voucher", "VCHR"), _num("inplace", "INPLAC")]
    return cols, _layout(det, [], fields, "ecode", "ename")


def _fortnight(db, b, f, t, extra, merge: bool):
    days = [f + timedelta(days=i) for i in range((t - f).days + 1)]
    per_day: dict = collections.defaultdict(float)
    for r in _atten(db, b, f, t, "" if merge else extra):
        if "STAFF" in r["grade"].upper():
            continue
        if merge:  # AttendanceReport inner joins; MainShift starts with the shift's first letter
            if not (r["odpt"] and r["main_shift"] is not None and r["uname"] is not None):
                continue
            if extra and not (r["main_shift"] or "").startswith(extra[:1]):
                continue
        k = (r["dept"], r["dname"], r["ecode"], r["unit"], r["work_type"], r["ename"])
        per_day[k, r["wdate"]] += r["work_hr"] if merge else r["shift_hr"] - r["gp_hr"]
    grid: dict = {}
    for (k, d), hrs in per_day.items():
        if merge and hrs <= 0:  # HAVING SUM(Work_HR) > 0
            continue
        line = grid.setdefault(k, {"k_dept": f"{k[0]} {k[1]}", "unit": k[3], "ecode": k[2], "ename": k[5],
                                   "work_type": k[4], **{f"d{i}": 0.0 for i in range(len(days))}, "total": 0.0})
        line[f"d{days.index(d)}"] += hrs
        line["total"] += hrs
    det = [grid[k] for k in sorted(grid)]
    sums = [f"d{i}" for i in range(len(days))] + ["total"]
    for line in det:
        for c in sums:
            line[c] = round(line[c], 2)
    cols = [_col("grp", "Department", width=220), _col("unit", "Unit", width=60), _col("ecode", "ECode", width=90),
            _col("ename", "EName", width=200), _col("work_type", "WType", width=70),
            *[_num(f"d{i}", d.strftime("%d"), 62) for i, d in enumerate(days)], _num("total", "Total")]
    return cols, _layout(det, [lambda d: d["k_dept"]], sums, "grp", "ecode")


def fortnight_wise(db, b, f, t, extra):
    """AttendanceRegisterFortNightWise_WIL (proc ATTN_Register): shift hours less gate pass, a column per date."""
    return _fortnight(db, b, f, t, extra, merge=False)


def fortnight_wise_merge(db, b, f, t, extra):
    """AttendanceRegisterFortNightWiseMERGE_WIL (proc ATTN_Register_Merge): work hours, a column per date;
    the filter matches the main shift (A1/A2 -> A)."""
    return _fortnight(db, b, f, t, extra, merge=True)


def fortnight_shift_wise(db, b, f, t, extra):
    """AttendanceRegisterFortNightShiftWise_WIL: hours (shift less gate pass) per worker by shift and
    the worker's master department."""
    items = [{**r, "hrs": r["shift_hr"] - r["gp_hr"]} for r in _atten(db, b, f, t, extra)
             if "WORK" in r["grade"].upper()]
    det = _agg(items, lambda r: ((r["wshift"], f"{r['e_dname']}-{r['e_dept']}", r["e_dept"], r["ecode"],
                                  r["work_type"], r["ename"]),
                                 {"k_shift": f"SHIFT : {r['wshift']}", "k_dept": f"{r['e_dname']}-{r['e_dept']}",
                                  "ecode": r["ecode"], "ename": r["ename"], "work_type": r["work_type"]}), ["hrs"])
    cols = [_col("grp", "Shift", width=120), _col("ecode", "ECode", width=220), _col("ename", "EName", width=230),
            _col("work_type", "WorkType", width=100), _num("hrs", "TotalHrs", 110)]
    return cols, _layout(det, [lambda d: d["k_shift"], lambda d: d["k_dept"]], ["hrs"], "grp", "ecode")


def _hour_lines(rs) -> list[dict]:
    return [{"k_date": _dmy(r["wdate"]), "emp": 1, "unit": r["unit"], "wshift": r["wshift"], "ecode": r["ecode"],
             "ename": r["ename"], "dept": r["dname"],
             "desig": r["oname"] if r["odpt"] else "", "shift_hr": r["shift_hr"], "gp_hr": r["gp_hr"],
             "work_hr": r["work_hr"]} for r in rs]


def manual_register(db, b, f, t, extra):
    """AttendanceRegisterManual_WIL: manually entered attendance (IsManual = 'Y'), per date."""
    det = _hour_lines([r for r in _atten(db, b, f, t, extra) if r["manual"].upper() == "Y"])
    cols = [_col("grp", "DATE", width=110), _num("emp", "No. Of Emp", 90), _col("unit", "UNIT", width=60),
            _col("ecode", "ECODE", width=90), _col("ename", "ENAME", width=220), _col("dept", "DEPARTMENT", width=190),
            _col("desig", "OCCUPATION", width=200), _col("wshift", "SHIFT", width=70), _num("shift_hr", "SFT_HR"),
            _num("gp_hr", "GP_HR"), _num("work_hr", "WORK_HR")]
    return cols, _layout(det, [lambda d: d["k_date"]], ["emp", "shift_hr", "gp_hr", "work_hr"], "grp", "ecode")


def gate_pass_register(db, b, f, t, extra):
    """GatePassRegister_WIL: every attendance with gate-pass hours, per date (and shift)."""
    rs = sorted((r for r in _atten(db, b, f, t) if r["gp_hr"] > 0),
                key=lambda r: (r["wdate"], r["shift_id"], r["ecode"]))
    det = _hour_lines(rs)
    cols = [_col("grp", "Date", width=110), _num("emp", "No. Of Emp", 90), _col("unit", "Unit", width=60),
            _col("wshift", "Shift", width=70), _col("ecode", "ECode", width=90), _col("ename", "EName", width=220),
            _col("dept", "DptName", width=190), _col("desig", "OCPName", width=200), _num("shift_hr", "Shift_HR"),
            _num("gp_hr", "GP_HR"), _num("work_hr", "Work_HR")]
    return cols, _layout(det, [lambda d: d["k_date"]], ["emp", "shift_hr", "gp_hr", "work_hr"], "grp", "ecode")


HANDS = ["duty", "ot", "voucher", "other", "outsider", "retire", "others", "total"]


def _hands(r) -> dict:
    """Department / Occupation summary columns: presence less the gate-pass share of the shift.
    MILL-WORKMEN outside the listed groups (GENERAL, FIX RATED ...) fall in no column, as in legacy."""
    gp, sh = r["gp_hr"], r["shift_hr"]
    h = 0.0 if (gp and gp == sh) else (1.0 - round(gp / sh, 3) if gp and sh else 1.0)
    g, eg, wt = r["grade"].upper(), r["egroup"].upper(), r["work_type"]
    perm = g == "MILL-WORKMEN" and eg in WORK_GROUPS
    v = {"duty": h if perm and wt == "DUTY" else 0.0, "ot": h if perm and wt == "OT" else 0.0,
         "voucher": h if perm and wt == "VOUCHER" else 0.0,
         "other": h if perm and wt not in ("DUTY", "OT", "VOUCHER") else 0.0,
         "outsider": h if g == "MILL-WORKMEN" and eg == "OUTSIDER" else 0.0,
         "retire": h if g == "MILL-WORKMEN" and eg == "RETIRE" else 0.0,
         "others": h if g != "MILL-WORKMEN" else 0.0}
    v["total"] = sum(v.values())
    return v


def _hands_cols(first: str, second: str) -> list[dict]:
    return [_col("grp", first, width=300), _col("dept", second, width=260), _num("duty", "DUTY"), _num("ot", "OT"),
            _num("voucher", "VOUCHER"), _num("other", "OTHERS"), _num("outsider", "OUTSIDER"),
            _num("retire", "RETIRE"), _num("others", "OTHERS (NON MILL)", 130), _num("total", "TOTAL")]


def department_summary(db, b, f, t, extra):
    """DepartmentwiseSummary_WIL: hands per department for each unit / date / shift (gate pass deducted);
    totals also show the hands converted to 8-hour spells (total x spell hours / 8)."""
    items = []
    for r in _atten(db, b, f, t, extra):
        if r["odpt"]:
            v = _hands(r)
            items.append({**r, **v, "spell": v["total"] * round(r["spell_hr"] / 8.0, 3)})
    fields = HANDS + ["spell"]
    det = _agg(items, lambda r: ((r["unit"], r["wdate"], r["wshift"], f"{r['dept']}-{r['dname']}"),
                                 {"k_unit": f"UNIT : {r['uname'] or r['unit']}",
                                  "k_ds": f"DATE : {_dmy(r['wdate'])}   SHIFT : {r['wshift']}",
                                  "dept": f"{r['dept']}-{r['dname']}"}), fields)
    out = _layout(det, [lambda d: d["k_unit"], lambda d: d["k_ds"]], fields, "grp", "dept")
    for row in out:
        if "k_unit" in row:  # legacy shows the spell total on Shift / Unit / Grand Total lines only
            row["spell"] = None
    return _hands_cols("Unit / Date / Shift", "Code - Department Name") + [_num("spell", "Spell Hands (/8)", 120)], out


def occupation_summary(db, b, f, t, extra):
    """Occupationwisesummary_WIL: hands per occupation over the period, by unit, shift and department."""
    items = [{**r, **_hands(r)} for r in _atten(db, b, f, t, extra) if r["odpt"]]
    det = _agg(items, lambda r: ((r["unit"], r["wshift"], f"{r['dept']}-{r['dname']}", f"{r['ocp']} - {r['oname']}"),
                                 {"k_unit": f"UNIT : {r['uname'] or r['unit']}", "k_shift": f"SHIFT : {r['wshift']}",
                                  "k_dept": f"{r['dept']}-{r['dname']}", "dept": f"{r['ocp']} - {r['oname']}"}),
               HANDS)
    levels = [lambda d: d["k_unit"], lambda d: d["k_shift"], lambda d: d["k_dept"]]
    return _hands_cols("Unit / Shift / Department", "Occupation"), _layout(det, levels, HANDS, "grp", "dept")


def dept_ocp_hands(db, b, f, t, extra):
    """DepttWiseOcpWiseHandsSummary_WIL (proc RPT_DeptWiseOcpWiseSummary): worker hands (work hours / 8)
    per WORKER occupation of ODPT, by main shift A / B / C."""
    agg: dict = {}
    for r in _atten(db, b, f, t):
        if not (r["odpt"] and r["main_shift"] is not None and r["uname"] is not None and r["work_hr"] > 0
                and r["etype"].upper() == "WORKER"):
            continue
        line = agg.setdefault((r["mdept"], f"{r['dept']} - {r['dname']}", r["ocp"]),
                              {"k_mdept": r["mdept"], "k_dept": f"{r['dept']} - {r['dname']}", "ocp": r["ocp"],
                               "oname": r["oname"], "a": 0.0, "b": 0.0, "c": 0.0, "total": 0.0})
        hands = r["work_hr"] / 8.0
        if r["main_shift"] in ("A", "B", "C"):
            line[r["main_shift"].lower()] += hands
        line["total"] += hands
    det = [{**v, **{c: round(v[c], 3) for c in ("a", "b", "c", "total")}} for _, v in sorted(agg.items())]
    cols = [_col("grp", "Department", width=260), _col("ocp", "Ocp. CD.", width=90), _col("oname", "Ocp. Name", width=240),
            _num("a", "A"), _num("b", "B"), _num("c", "C"), _num("total", "TOTAL", 100)]
    return cols, _layout(det, [lambda d: d["k_mdept"], lambda d: d["k_dept"]], ["a", "b", "c", "total"], "grp", "ocp")


REPORTS: dict[str, dict[str, dict]] = {"attendanceRegister": {
    "attendanceWorktypeWiseSummary": spec("Attendance WorkType Wise Summary", worktype_summary, span="day", extra=SHIFT),
    "attendanceWorkTypeWiseDetails": spec("Attendance Work Type Wise Details", worktype_details, span="day", extra=SHIFT),
    "attendanceEcodeWiseDetails": spec("Attendance ECode Wise Details", ecode_details, extra=SHIFT),
    "attendanceFortNightWise": spec("Attendance Fort Night Wise", fortnight_wise, extra=SHIFT, max_days=31),
    "attendanceFortNightWiseMerge": spec("Attendance Fort Night Wise MERGE", fortnight_wise_merge, extra=SHIFT,
                                         max_days=31),
    "attendanceFortNightWiseShiftWise": spec("Attendance Fort Night Wise Shift Wise", fortnight_shift_wise, extra=SHIFT),
    "attendanceRegisterManual": spec("Attendance Register (MANUAL)", manual_register, extra=SHIFT),
    "gatePassRegister": spec("Gate Pass Register", gate_pass_register),
    "departmentWiseSummary": spec("Department Wise Summary", department_summary, span="day", extra=SHIFT),
    "occupationWiseSummary": spec("Occupation Wise Summary", occupation_summary, span="day", extra=SHIFT),
    "deptWiseOcpWiseHandsSummary": spec("Dept. Wise. Ocp. Wise Hands Summary", dept_ocp_hands, span="day"),
}}
