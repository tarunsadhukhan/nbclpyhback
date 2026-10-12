"""
NBJCL Reports > Attendance Register — ports of the 16 legacy Smart-Eye Crystal reports of the
"Attendance Register" group (report master ORPSMTEye, files Reports/SmartEyeReportMulti/*_NJB.rpt).
Mounted at /api/hrmsReports/nbjcl/attendance-register.

Each legacy report is a SQL command over ATTEN + PayOEMP + ODPT with Crystal groups and totals.
Here one query reads the approved daily_attendance rows in legacy shape and each report lays its
rows out in Python: group headers, details, "Total" rows per group and a "Grand Total", already
in display order, so one generic page (ReportPanel, scroll mode) can show and export any of them.

Legacy -> tenant mapping: ATTEN = daily_attendance (approved, active); WShift = spell_mst.spell_code;
MainShift = shift_mst.shift_name; work type DUTY / OT = attendance_type R / O; Shift_HR = spell_hours;
GatePass_HR = idle_hours; Work_HR = working_hours (already net of the gate pass: every row with idle
hours has working_hours = spell_hours - idle_hours); Night_HR = 0.5 for a full night (C)
spell; dept / occupation = worked department / designation; EGroup = category_mst.cata_desc.

ponytail: the tenant keeps no Grade (MILL-WORKMEN / OUTSIDER / CONTRACTOR) on attendance, so every
worker counts as MILL-WORKMEN and the OUTSIDER / CONTRACTOR columns stay 0; no unit (single mill),
and designation_mst has no occupation code, so occupations show by name. Each report takes the one
filter that matters most (shift, department or main shift); add the rest when someone needs them.
"""
import collections
import logging
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy.sql import text

from src.authorization.utils import get_current_user_with_refresh
from src.config.db import get_tenant_db

logger = logging.getLogger(__name__)
router = APIRouter()

PERMANENT_GROUPS = ("01", "02", "03", "04", "07", "08", "09", "10", "11", "12", "13", "14", "15")
NIGHT_SPELLS = ("C", "C2")


# ─── Data ──────────────────────────────────────────────────────────────────


def _attendance(db: Session, branch_id: int, f: date, t: date, *, shift: str = "", dept: str = "",
                main_shift: str = "", machines: bool = False) -> list[dict]:
    """Approved attendance rows of the branch in legacy ATTEN / AttendanceReport shape."""
    mech: dict = {}
    if machines:
        mech = {r.daily_atten_id: r.codes for r in db.execute(text("""
            SELECT e.daily_atten_id, GROUP_CONCAT(DISTINCT m.mech_code ORDER BY m.mech_code) AS codes
            FROM daily_ebmc_attendance e JOIN machine_mst m ON m.machine_id = e.mc_id
            WHERE e.branch_id = :b AND e.attendace_date BETWEEN :f AND :t AND e.is_active = 1
            GROUP BY e.daily_atten_id"""), {"b": branch_id, "f": f, "t": t})}
    rows = db.execute(text("""
        SELECT da.attendance_date AS wdate, IFNULL(sp.spell_code, '') AS wshift,
               IFNULL(sh.shift_name, '') AS main_shift, o.emp_code AS ecode,
               CONCAT_WS(' ', NULLIF(TRIM(p.first_name), ''), NULLIF(TRIM(p.middle_name), ''),
                         NULLIF(TRIM(p.last_name), '')) AS ename,
               IFNULL(d.dept_code, '') AS dept_code, IFNULL(d.dept_desc, '') AS dept_name,
               IFNULL(g.desig, '') AS desig,
               CASE da.attendance_type WHEN 'R' THEN 'DUTY' WHEN 'O' THEN 'OT'
                    ELSE IFNULL(da.attendance_type, '') END AS work_type,
               IFNULL(da.spell_hours, 0) AS shift_hr, IFNULL(da.idle_hours, 0) AS gp_hr,
               IFNULL(da.working_hours, 0) AS work_hr,
               IFNULL(da.attendance_source, '') AS source, da.entry_time,
               IFNULL(cm.cata_desc, '') AS egroup, da.eb_id, da.device_id, da.created_by, da.daily_atten_id
        FROM daily_attendance da
        JOIN hrms_ed_official_details o ON o.eb_id = da.eb_id AND o.active = 1
        LEFT JOIN hrms_ed_personal_details p ON p.eb_id = da.eb_id
        LEFT JOIN sub_dept_mst sd ON sd.sub_dept_id = da.worked_department_id
        LEFT JOIN dept_mst d ON d.dept_id = sd.dept_id
        LEFT JOIN designation_mst g ON g.designation_id = da.worked_designation_id
        LEFT JOIN spell_mst sp ON sp.spell_id = da.spell_id
        LEFT JOIN shift_mst sh ON sh.shift_id = sp.shift_id
        LEFT JOIN category_mst cm ON cm.cata_id = o.catagory_id
        WHERE da.branch_id = :b AND da.attendance_date BETWEEN :f AND :t AND da.is_active = 1
          AND CAST(da.status_id AS UNSIGNED) = 3
          AND (:shift = '' OR sp.spell_code = :shift)
          AND (:dept = '' OR d.dept_code = :dept)
          AND (:ms = '' OR sh.shift_name = :ms)
        ORDER BY da.attendance_date, sp.spell_code, d.dept_code, g.desig, o.emp_code
    """), {"b": branch_id, "f": f, "t": t, "shift": shift, "dept": dept, "ms": main_shift})
    out = []
    for r in rows:
        m = dict(r._mapping)
        for k in ("shift_hr", "gp_hr", "work_hr"):
            m[k] = float(m[k] or 0)
        # night allowance hours: half an hour for a full night-spell shift (as the wages process counts it)
        m["night_hr"] = 0.5 if m["wshift"] in NIGHT_SPELLS and abs(m["work_hr"] - 7.5) < 0.001 else 0.0
        m["ename"] = m["ename"] or ""
        m["machine"] = mech.get(m["daily_atten_id"], "")
        out.append(m)
    return out


def _card_numbers(db: Session) -> dict[str, str]:
    """Legacy card number per employee code: not kept in the HR masters, taken from the latest slip."""
    rows = db.execute(text("""
        SELECT ECode, SUBSTRING_INDEX(GROUP_CONCAT(RecNo ORDER BY EDate DESC), ',', 1) AS card
        FROM paywages WHERE RecNo <> '' GROUP BY ECode"""))
    return {r.ECode.strip(): r.card for r in rows}


# ─── Layout helpers ────────────────────────────────────────────────────────


def _col(field: str, header: str, kind: str = "text", width: int = 110) -> dict:
    return {"field": field, "headerName": header, "type": kind, "width": width}


def _num(field: str, header: str, width: int = 90) -> dict:
    return _col(field, header, "number", width)


def _dmy(d) -> str:
    return d.strftime("%d/%m/%Y") if isinstance(d, (date, datetime)) else str(d or "")


def _layout(details: list[dict], levels: list, sums: list[str], lead: str, label: str,
            grand: bool = True, count_field: str | None = None, footers: bool = True) -> list[dict]:
    """Rows in print order: a header row when a group starts, the details, a "Total" row when it
    ends and a closing "Grand Total". `levels` = [key function], outer to inner; the key is the
    text shown. `sums` are added up (or, with `count_field`, the details are counted into it).
    The outer group's header and total sit in `lead`, inner ones in `label` — the grid shades
    total rows by that."""
    out: list[dict] = []
    n = len(levels)
    keys: list = [None] * n
    acc = [collections.defaultdict(float) for _ in range(n + 1)]

    def close(i: int) -> None:
        if not footers:
            return
        row = {lead: "Total", label: str(keys[i])} if i == 0 else {label: "Total"}
        row.update({k: round(v, 3) for k, v in acc[i].items()})
        out.append(row)
        acc[i] = collections.defaultdict(float)

    for d in details:
        new = [fn(d) for fn in levels]
        changed = next((i for i in range(n) if new[i] != keys[i]), n)
        if out:
            for i in range(n - 1, changed - 1, -1):
                close(i)
        for i in range(changed, n):
            keys[i] = new[i]
            out.append({lead: str(new[i])} if i == 0 else {label: str(new[i])})
        out.append(d)
        for i in range(n + 1):
            if count_field:
                acc[i][count_field] += 1
            for k in sums:
                acc[i][k] += float(d.get(k) or 0)
    if details:
        for i in range(n - 1, -1, -1):
            close(i)
        if grand:
            out.append({lead: "Grand Total", **{k: round(v, 3) for k, v in acc[n].items()}})
    return out


def _presence(r: dict) -> float:
    """Legacy head count of one attendance row: 1, less the gate-pass share of the shift."""
    if r["gp_hr"] and r["shift_hr"] and r["gp_hr"] == r["shift_hr"]:
        return 0.0
    if r["gp_hr"] and r["shift_hr"]:
        return round(1.0 - round(r["gp_hr"] / r["shift_hr"], 3), 3)
    return 1.0


def _work_type_buckets(r: dict, value: float, retire: bool = False) -> dict:
    """Spread one row's value over the legacy grade / work-type columns."""
    b = dict.fromkeys(("duty", "ot", "voucher", "other", "outsider", "contractor", "retire", "others"), 0.0)
    grp = r["egroup"][:2]
    if retire and grp == "05":
        b["retire"] = value
    elif retire and grp not in PERMANENT_GROUPS:
        pass  # legacy: a mill worker outside the listed categories falls in no column
    else:
        b[{"DUTY": "duty", "OT": "ot", "VOUCHER": "voucher"}.get(r["work_type"], "other")] = value
    b["total"] = value if any(b.values()) else 0.0
    return b


def _days(f: date, t: date, limit: int = 16) -> list[date]:
    n = min((t - f).days + 1, limit)
    return [f + timedelta(days=i) for i in range(max(n, 0))]


def _pivot_dates(rows: list[dict], key_fields: list[str], value: str, days: list[date]) -> list[dict]:
    """One line per key with a column per date and a row total."""
    grid: dict = collections.OrderedDict()
    for r in rows:
        k = tuple(r[x] for x in key_fields)
        line = grid.setdefault(k, {**{x: r[x] for x in key_fields}, **{f"d{i}": 0.0 for i in range(len(days))}})
        if r["wdate"] in days:
            line[f"d{days.index(r['wdate'])}"] += r[value]
    out = []
    for line in grid.values():
        line["total"] = round(sum(line[f"d{i}"] for i in range(len(days))), 2)
        out.append(line)
    return out


def _day_cols(days: list[date], width: int = 62) -> list[dict]:
    return [_num(f"d{i}", d.strftime("%d"), width) for i, d in enumerate(days)]


# ─── Reports ───────────────────────────────────────────────────────────────


def work_type_details(db, b, f, t, extra):
    """AttendanceWokTypeWiseDetails_NJB: who was present, per date / shift, department and occupation."""
    rows = _attendance(db, b, f, t, shift=extra, machines=True)
    det = []
    for r in rows:
        gone = 1.0 if (r["gp_hr"] and r["gp_hr"] == r["shift_hr"]) else 0.0
        det.append({"wdate": r["wdate"], "wshift": r["wshift"],
                    "k_ds": f"DATE : {_dmy(r['wdate'])}   SHIFT : {r['wshift']}",
                    "k_dept": f"{r['dept_code']}-{r['dept_name']}", "k_desig": r["desig"],
                    "ecode": r["ecode"], "ename": r["ename"],
                    "time": r["entry_time"].strftime("%H:%M") if r["entry_time"] else "",
                    "machine": r["machine"] or "", **_work_type_buckets(r, 1.0 - gone)})
    det.sort(key=lambda d: (d["wdate"], d["wshift"], d["k_dept"], d["k_desig"], d["ename"]))
    sums = ["duty", "ot", "voucher", "other", "outsider", "contractor", "others", "total"]
    cols = [_col("grp", "Date / Shift", width=230), _col("ecode", "ECode", width=160), _col("ename", "EName", width=220),
            _col("time", "Time", width=70), _col("machine", "Machine", width=110), _num("duty", "Duty"),
            _num("ot", "OT"), _num("voucher", "Vour"), _num("other", "Othr"), _num("outsider", "Outsider"),
            _num("contractor", "Contractor"), _num("others", "Others"), _num("total", "Total")]
    return cols, _layout(det, [lambda d: d["k_ds"], lambda d: d["k_dept"], lambda d: d["k_desig"]], sums, "grp", "ecode")


def _fortnight(db, b, f, t, extra, merge: bool):
    days = _days(f, t)
    rows = _attendance(db, b, f, t, shift=extra)
    for r in rows:
        r["hrs"] = r["work_hr"] if merge else r["shift_hr"] - r["gp_hr"]
        r["k_dept"] = f"{r['dept_code']} {r['dept_name']}"
    det = _pivot_dates(rows, ["k_dept", "ecode", "ename", "work_type"], "hrs", days)
    det.sort(key=lambda d: (d["k_dept"], d["ecode"], d["work_type"]))
    sums = [f"d{i}" for i in range(len(days))] + ["total"]
    cols = [_col("grp", "Department", width=190), _col("ecode", "ECode", width=90), _col("ename", "EName", width=200),
            _col("work_type", "WType", width=70), *_day_cols(days), _num("total", "Total")]
    return cols, _layout(det, [lambda d: d["k_dept"]], sums, "grp", "ecode")


def fortnight_wise(db, b, f, t, extra):
    """AttendanceRegisterFortNightWise_NJB (proc ATTN_Register): hours per day = shift hours less gate pass."""
    return _fortnight(db, b, f, t, extra, merge=False)


def fortnight_wise_merge(db, b, f, t, extra):
    """AttendanceRegisterFortNightWiseMERGE_NJB (proc ATTN_Register_Merge): hours per day = work hours."""
    return _fortnight(db, b, f, t, extra, merge=True)


def fortnight_shift_wise(db, b, f, t, extra):
    """AttendanceRegisterFortNightShiftWise_NJB: total hours per worker by shift and department."""
    agg: dict = collections.OrderedDict()
    for r in _attendance(db, b, f, t, shift=extra):
        k = (r["wshift"], f"{r['dept_name']}-{r['dept_code']}", r["ecode"], r["ename"], r["work_type"])
        agg[k] = agg.get(k, 0.0) + r["shift_hr"] - r["gp_hr"]
    det = [{"k_shift": f"SHIFT : {k[0]}", "k_dept": k[1], "ecode": k[2], "ename": k[3], "work_type": k[4],
            "total": round(v, 2)} for k, v in sorted(agg.items())]
    cols = [_col("grp", "Shift", width=120), _col("ecode", "ECode", width=200), _col("ename", "EName", width=230),
            _col("work_type", "WorkType", width=100), _num("total", "TotalHrs", 110)]
    return cols, _layout(det, [lambda d: d["k_shift"], lambda d: d["k_dept"]], ["total"], "grp", "ecode")


def muster_roll(db, b, f, t, extra):
    """WorkerRollRegister_NJB (proc SP_WagesBook_NJB): duty hours per day of the fortnight per worker,
    by shift / department and occupation, with work days, work / night / festival hours and basic rate."""
    days = _days(f, t)
    cards = _card_numbers(db)
    esi = {r.eb_id: r.esi_no for r in db.execute(text(
        "SELECT eb_id, MAX(esi_no) esi_no FROM hrms_ed_esi WHERE active = 1 GROUP BY eb_id"))}
    rate = {r.eb_id: float(r.fbasic or 0) for r in db.execute(text("""
        SELECT eb_id, fbasic FROM (SELECT r.*, ROW_NUMBER() OVER (PARTITION BY eb_id
               ORDER BY effective_date DESC, is_active DESC, worker_rate_id DESC) rn
               FROM worker_rate_mst r WHERE effective_date <= :f) x WHERE rn = 1"""), {"f": f})}
    hol = {r.eb_id: float(r.h or 0) for r in db.execute(text("""
        SELECT t.eb_id, SUM(t.holiday_hours) h FROM hrms_holiday_transactions t
        JOIN holiday_master h ON h.holiday_id = t.holiday_id
        WHERE t.branch_id = :b AND h.holiday_date BETWEEN :f AND :t GROUP BY t.eb_id"""), {"b": b, "f": f, "t": t})}
    grid: dict = collections.OrderedDict()
    for r in _attendance(db, b, f, t):
        if r["work_type"] != "DUTY":
            continue
        k = (r["wshift"], r["dept_code"], r["dept_name"], r["desig"], r["ecode"])
        g = grid.setdefault(k, {"k_sd": f"SHIFT : {r['wshift']}   DEPT : {r['dept_code']} - {r['dept_name']}",
                                "k_ocp": f"OCCP : {r['desig']}", "card": cards.get(r["ecode"], ""),
                                "ename": r["ename"], "ecode": r["ecode"], "esi": esi.get(r["eb_id"], "") or "",
                                "cat": "P" if r["egroup"][:2] in ("02", "03") else "T",
                                "rate": rate.get(r["eb_id"], 0.0), "dates": set(), "work_hr": 0.0, "ns_hr": 0.0,
                                "fest_hr": hol.get(r["eb_id"], 0.0), **{f"d{i}": 0.0 for i in range(len(days))}})
        if r["wdate"] in days:
            g[f"d{days.index(r['wdate'])}"] += r["work_hr"]
        g["dates"].add(r["wdate"])
        g["work_hr"] += r["work_hr"]
        g["ns_hr"] += r["night_hr"]
    det = []
    for k in sorted(grid):
        g = grid[k]
        g["work_day"] = len(g.pop("dates"))
        det.append(g)
    cols = [_col("grp", "Shift / Dept", width=260), _col("card", "RCNo", width=200), _col("ename", "EName", width=200),
            _col("ecode", "ECode", width=90), _col("esi", "ESINo", width=110), _col("cat", "CAT", width=60),
            _num("rate", "Basic Rate", 100), *_day_cols(days), _num("work_day", "Work Day"),
            _num("work_hr", "Work HR"), _num("ns_hr", "NS HR"), _num("fest_hr", "Fest HR")]
    return cols, _layout(det, [lambda d: d["k_sd"], lambda d: d["k_ocp"]], [], "grp", "card", grand=False,
                         footers=False)


def _hour_lines(rows: list[dict]) -> list[dict]:
    return [{"k_date": _dmy(r["wdate"]), "wdate": r["wdate"], "ecode": r["ecode"], "ename": r["ename"],
             "dept": f"{r['dept_code']} {r['dept_name']}".strip(), "desig": r["desig"], "wshift": r["wshift"],
             "shift_hr": r["shift_hr"], "gp_hr": r["gp_hr"], "work_hr": r["work_hr"]} for r in rows]


def manual_register(db, b, f, t, extra):
    """AttendanceRegisterManual_NJB: manually entered attendance, per date."""
    det = _hour_lines([r for r in _attendance(db, b, f, t, shift=extra) if r["source"] == "M"])
    cols = [_col("grp", "Date", width=110), _col("ecode", "ECode", width=90), _col("ename", "EName", width=220),
            _col("dept", "Dept", width=190), _col("desig", "Occupation", width=200), _col("wshift", "Shift", width=70),
            _num("shift_hr", "Sft_HR"), _num("gp_hr", "GP_HR"), _num("work_hr", "Work_HR")]
    return cols, _layout(det, [lambda d: d["k_date"]], ["shift_hr", "gp_hr", "work_hr"], "grp", "ecode")


def gate_pass_register(db, b, f, t, extra):
    """GatePassRegister_NJB: every attendance with gate-pass hours."""
    det = _hour_lines([r for r in _attendance(db, b, f, t) if r["gp_hr"] > 0])
    det.sort(key=lambda d: (d["wdate"], d["ecode"]))
    for d in det:
        d["grp"] = d["k_date"]
    cols = [_col("grp", "Date", width=110), _col("wshift", "Shift", width=70), _col("ecode", "ECode", width=90),
            _col("ename", "EName", width=220), _col("dept", "Dept", width=190), _col("desig", "Occupation", width=200),
            _num("shift_hr", "Shift_HR"), _num("gp_hr", "GP_HR"), _num("work_hr", "Work_HR")]
    return cols, _layout(det, [], ["shift_hr", "gp_hr", "work_hr"], "grp", "ecode")


def department_summary(db, b, f, t, extra):
    """DepartmentwiseSummary_NJB: hands per department for each date and shift (gate pass deducted)."""
    agg: dict = collections.OrderedDict()
    for r in _attendance(db, b, f, t, shift=extra):
        if r["work_hr"] <= 0:
            continue
        k = (r["wdate"], r["wshift"], f"{r['dept_code']}-{r['dept_name']}")
        line = agg.setdefault(k, collections.defaultdict(float))
        for c, v in _work_type_buckets(r, _presence(r), retire=True).items():
            line[c] += v
    det = [{"k_ds": f"DATE : {_dmy(k[0])}   SHIFT : {k[1]}", "dept": k[2], **{c: round(v, 3) for c, v in v_.items()}}
           for k, v_ in sorted(agg.items())]
    sums = ["duty", "ot", "voucher", "other", "outsider", "retire", "others", "total"]
    cols = [_col("grp", "Date / Shift", width=230), _col("dept", "Code - Department Name", width=240),
            _num("duty", "Duty"), _num("ot", "OT"), _num("voucher", "Voucher"), _num("other", "Others"),
            _num("outsider", "Outsider"), _num("retire", "Retire"), _num("others", "Others (non-mill)", 130),
            _num("total", "Total")]
    return cols, _layout(det, [lambda d: d["k_ds"]], sums, "grp", "dept")


def occupation_summary(db, b, f, t, extra):
    """OccupationWiseSummary_NJB: hands (work hours / 8) per occupation on one date."""
    agg: dict = collections.OrderedDict()
    for r in _attendance(db, b, t, t, shift=extra):
        if r["work_hr"] <= 0:
            continue
        k = (f"{r['dept_code']} {r['dept_name']}", r["desig"])
        line = agg.setdefault(k, collections.defaultdict(float))
        for c, v in _work_type_buckets(r, r["work_hr"] / 8.0).items():
            line[c] += v
    det = [{"k_dept": k[0], "desig": k[1], **{c: round(v, 3) for c, v in v_.items()}} for k, v_ in sorted(agg.items())]
    sums = ["duty", "ot", "voucher", "outsider", "contractor", "others", "total"]
    cols = [_col("grp", "Department", width=220), _col("desig", "Occupation Name", width=240), _num("duty", "Duty"),
            _num("ot", "OT"), _num("voucher", "Voucher"), _num("outsider", "Out Sider"),
            _num("contractor", "Contractor"), _num("others", "Others"), _num("total", "Total")]
    return cols, _layout(det, [lambda d: d["k_dept"]], sums, "grp", "desig")


def absenting_list(db, b, f, t, extra):
    """DeptWiseAbsentList_NJB: active workers with no duty in the period, with their last department
    and the fortnight their last duty fell in. Workers who never attended are left out, as in legacy."""
    cards = _card_numbers(db)
    rows = db.execute(text("""
        SELECT o.emp_code AS ecode,
               CONCAT_WS(' ', NULLIF(TRIM(p.first_name), ''), NULLIF(TRIM(p.middle_name), ''),
                         NULLIF(TRIM(p.last_name), '')) AS ename,
               LEFT(IFNULL(cm.cata_desc, ''), 2) AS cat, l.last_date,
               (SELECT d.dept_code FROM daily_attendance x
                  JOIN sub_dept_mst sd ON sd.sub_dept_id = x.worked_department_id
                  JOIN dept_mst d ON d.dept_id = sd.dept_id
                 WHERE x.eb_id = o.eb_id AND x.attendance_date = l.last_date AND x.attendance_type = 'R'
                   AND x.is_active = 1 LIMIT 1) AS dcode,
               (SELECT pp.TO_DATE FROM pay_period pp WHERE pp.branch_id = :b AND pp.code LIKE 'P%'
                   AND l.last_date BETWEEN pp.FROM_DATE AND pp.TO_DATE ORDER BY pp.ID LIMIT 1) AS fne_date
        FROM hrms_ed_official_details o
        JOIN (SELECT eb_id, MAX(attendance_date) last_date FROM daily_attendance
              WHERE branch_id = :b AND attendance_type = 'R' AND is_active = 1
                AND CAST(status_id AS UNSIGNED) = 3 GROUP BY eb_id) l ON l.eb_id = o.eb_id
        LEFT JOIN hrms_ed_personal_details p ON p.eb_id = o.eb_id
        LEFT JOIN category_mst cm ON cm.cata_id = o.catagory_id
        WHERE o.branch_id = :b AND o.active = 1 AND IFNULL(o.emp_code, '') <> '' AND l.last_date < :f
    """), {"b": b, "f": f})
    det = [{"k_dept": r.dcode or "", "ecode": r.ecode, "card": cards.get(r.ecode, ""), "cat": r.cat,
            "ename": r.ename or "", "last_date": _dmy(r.last_date), "fne_date": _dmy(r.fne_date)} for r in rows]
    det.sort(key=lambda d: (d["k_dept"], d["ecode"]))
    cols = [_col("grp", "D.Code", width=100), _col("ecode", "ECode", width=160), _col("card", "CardNo", width=100),
            _col("cat", "CAT", width=60), _col("ename", "EName", width=240), _col("last_date", "Last Duty", width=110),
            _col("fne_date", "Last FNEDate", width=120), _num("count", "Count", 80)]
    return cols, _layout(det, [lambda d: d["k_dept"]], [], "grp", "ecode", count_field="count")


def leave_register(db, b, f, t, extra):
    """LeaveRegister_NJB: approved leave that starts and ends inside the period, by department."""
    cards = _card_numbers(db)
    rows = db.execute(text("""
        SELECT IFNULL(d.dept_code, '') AS dept_code, IFNULL(d.dept_desc, '') AS dept_name, o.emp_code AS ecode,
               CONCAT_WS(' ', NULLIF(TRIM(p.first_name), ''), NULLIF(TRIM(p.middle_name), ''),
                         NULLIF(TRIM(p.last_name), '')) AS ename,
               IFNULL(e.esi_no, '') AS esi, IFNULL(m.leave_type_description, '') AS leave_type,
               lt.leave_from_date, lt.leave_to_date,
               DATEDIFF(lt.leave_to_date, lt.leave_from_date) + 1 AS days
        FROM leave_transactions lt
        JOIN hrms_ed_official_details o ON o.eb_id = lt.eb_id AND o.active = 1
        LEFT JOIN hrms_ed_personal_details p ON p.eb_id = lt.eb_id
        LEFT JOIN sub_dept_mst sd ON sd.sub_dept_id = o.sub_dept_id
        LEFT JOIN dept_mst d ON d.dept_id = sd.dept_id
        LEFT JOIN hrms_leave_types_mst m ON m.leave_type_id = lt.leave_type_id
        LEFT JOIN (SELECT eb_id, MAX(esi_no) esi_no FROM hrms_ed_esi WHERE active = 1 GROUP BY eb_id) e
               ON e.eb_id = lt.eb_id
        WHERE lt.branch_id = :b AND lt.status = '3' AND lt.leave_from_date >= :f AND lt.leave_to_date <= :t
        ORDER BY d.dept_code, o.emp_code, lt.leave_from_date
    """), {"b": b, "f": f, "t": t})
    det = [{"k_dept": f"Department : {r.dept_code} - {r.dept_name}", "slno": i, "ecode": r.ecode,
            "card": cards.get(r.ecode, ""), "esi": r.esi, "ename": r.ename or "", "leave_type": r.leave_type,
            "from_date": _dmy(r.leave_from_date), "to_date": _dmy(r.leave_to_date), "days": float(r.days or 0)}
           for i, r in enumerate(rows, start=1)]
    cols = [_col("grp", "Department", width=240), _col("ecode", "ECode", width=160), _num("slno", "SlNo", 70),
            _col("card", "CardNo", width=100), _col("esi", "ESINo", width=110), _col("ename", "Name", width=220),
            _col("leave_type", "LeaveType", width=140), _col("from_date", "FromDate", width=105),
            _col("to_date", "ToDate", width=105), _num("days", "Days", 80)]
    return cols, _layout(det, [lambda d: d["k_dept"]], ["days"], "grp", "ecode")


def _date_dept(db, b, f, t, extra, hands: bool):
    days = _days(f, t, limit=31)
    rows = _attendance(db, b, f, t, dept=extra)
    for r in rows:
        r["k_dept"] = f"{r['dept_code']}-{r['dept_name']}"
        r["val"] = r["work_hr"] / 8.0 if hands else r["work_hr"]
    det = _pivot_dates(rows, ["k_dept", "work_type"], "val", days)
    det.sort(key=lambda d: (d["k_dept"], d["work_type"]))
    sums = [f"d{i}" for i in range(len(days))] + ["total"]
    cols = [_col("grp", "Department", width=220), _col("work_type", "Work Type", width=110),
            *_day_cols(days, 70), _num("total", "Total", 100)]
    return cols, _layout(det, [lambda d: d["k_dept"]], sums, "grp", "work_type")


def date_dept_hours(db, b, f, t, extra):
    """Date_Dept_WT_WHr_NJB: work hours per department and work type, a column per date."""
    return _date_dept(db, b, f, t, extra, hands=False)


def date_dept_hands(db, b, f, t, extra):
    """Date_Dept_WT_WHands_NJB: the same in hands (work hours / 8)."""
    return _date_dept(db, b, f, t, extra, hands=True)


def worker_wise_hours(db, b, f, t, extra):
    """AttendanceReportFNMainShiftDeptWise_Emp_NJB: work hours per worker, department and work type,
    a column per date."""
    days = _days(f, t, limit=31)
    rows = _attendance(db, b, f, t, main_shift=extra)
    for r in rows:
        r["dept"] = f"{r['dept_code']} {r['dept_name']}".strip()
    det = _pivot_dates(rows, ["ecode", "ename", "dept", "work_type"], "work_hr", days)
    det.sort(key=lambda d: (d["ecode"], d["work_type"], d["dept"]))
    for d in det:
        d["grp"] = d["ecode"]
    sums = [f"d{i}" for i in range(len(days))] + ["total"]
    cols = [_col("grp", "ECode", width=110), _col("ename", "EName", width=210), _col("dept", "Dept", width=180),
            _col("work_type", "WType", width=80), *_day_cols(days, 62), _num("total", "Total", 90)]
    return cols, _layout(det, [], sums, "grp", "ename")


def time_report(db, b, f, t, extra):
    """AttendanceTimeReport_NBJCL: one date (and shift) in punch order, by entering user and device."""
    rows = _attendance(db, b, t, t, shift=extra)
    rows.sort(key=lambda r: (str(r["device_id"] or ""), str(r["created_by"] or ""), r["entry_time"] or datetime.min))
    det = [{"k_user": f"USER ID : {r['created_by'] or ''}   DEVICE ID : {r['device_id'] or ''}", "slno": i,
            "ecode": r["ecode"], "ename": r["ename"], "dept": r["dept_name"], "work_type": r["work_type"],
            "work_hr": r["work_hr"], "time": r["entry_time"].strftime("%H:%M:%S") if r["entry_time"] else ""}
           for i, r in enumerate(rows, start=1)]
    cols = [_col("grp", "User / Device", width=240), _col("ecode", "ECode", width=160), _num("slno", "SL No.", 80),
            _col("ename", "EName", width=220), _col("dept", "DeptName", width=190),
            _col("work_type", "Work type", width=100), _num("work_hr", "Work HR"), _col("time", "WTime", width=100)]
    return cols, _layout(det, [lambda d: d["k_user"]], ["work_hr"], "grp", "ecode")


def dept_ocp_hands(db, b, f, t, extra):
    """DepttWiseOcpWiseHandsSummary_NJB (proc RPT_DeptWiseOcpWiseSummary): hands per department and
    occupation for main shifts A / B / C; hands = (work + night hours) / 8."""
    agg: dict = collections.OrderedDict()
    for r in _attendance(db, b, f, t, dept=extra):
        if r["work_hr"] <= 0:
            continue
        k = (f"{r['dept_code']} - {r['dept_name']}", r["desig"])
        line = agg.setdefault(k, collections.defaultdict(float))
        hands = (r["work_hr"] + r["night_hr"]) / 8.0
        if r["main_shift"] in ("A", "B", "C"):
            line[r["main_shift"].lower()] += hands
        line["total"] += hands
    det = [{"k_dept": k[0], "desig": k[1], "a": round(v["a"], 3), "b": round(v["b"], 3), "c": round(v["c"], 3),
            "total": round(v["total"], 3)} for k, v in sorted(agg.items())]
    cols = [_col("grp", "Department", width=230), _col("desig", "Ocp. Name", width=240), _num("a", "A"),
            _num("b", "B"), _num("c", "C"), _num("total", "Total", 100)]
    return cols, _layout(det, [lambda d: d["k_dept"]], ["a", "b", "c", "total"], "grp", "desig")


# key = last segment of the seeded menu path hrms/nbjclreports/attendanceRegister/<key>
# (run_seed_nbjcl_reports_menu.py camel-cases the legacy report name)
REPORTS: dict[str, dict] = {
    "attendanceWorkTypeWiseDetails": {"span": "day", "title": "Attendance Work Type Wise Details", "dates": "range", "extra": "shift", "build": work_type_details},
    "attendanceFortNightWise": {"title": "Attendance Fort Night Wise", "dates": "range", "extra": "shift", "build": fortnight_wise},
    "attendanceFortNightWiseMerge": {"title": "Attendance Fort Night Wise MERGE", "dates": "range", "extra": "shift", "build": fortnight_wise_merge},
    "attendanceFortNightWiseShiftWise": {"title": "Attendance Fort Night Wise Shift Wise", "dates": "range", "extra": "shift", "build": fortnight_shift_wise},
    "workmenSMusterRollRegisterOfAdultWorkers": {"title": "Workmen's Muster Roll - Register Of Adult Workers", "dates": "range", "extra": None, "build": muster_roll},
    "attendanceRegisterManual": {"span": "day", "title": "Attendance Register (MANUAL)", "dates": "range", "extra": "shift", "build": manual_register},
    "gatePassRegister": {"title": "Gate Pass Register", "dates": "range", "extra": None, "build": gate_pass_register},
    "departmentWiseSummary": {"span": "day", "title": "Department Wise Summary", "dates": "range", "extra": "shift", "build": department_summary},
    "occupationWiseSummary": {"title": "Occupation Wise Summary", "dates": "single", "extra": "shift", "build": occupation_summary},
    "absentingList": {"title": "ABSENTING LIST", "dates": "range", "extra": None, "build": absenting_list},
    "leaveRegister": {"title": "LEAVE REGISTER", "dates": "range", "extra": None, "build": leave_register},
    "dateWiseDeptWiseWorkingHours": {"title": "DATE WISE DEPT WISE WORKING HOURS", "dates": "range", "extra": "dept", "build": date_dept_hours},
    "dateWiseDeptWiseWorkingHands": {"title": "DATE WISE DEPT WISE WORKING HANDS", "dates": "range", "extra": "dept", "build": date_dept_hands},
    "fortNightWiseWorkerWiseHands": {"title": "Fort Night Wise Worker Wise Hands", "dates": "range", "extra": "main_shift", "build": worker_wise_hours},
    "attendanceTimeReport": {"title": "Attendance Time Report", "dates": "single", "extra": "shift", "build": time_report},
    "deptWiseOcpWiseHandsSummary": {"title": "Dept. Wise. Ocp. Wise Hands Summary", "dates": "range", "extra": "dept", "build": dept_ocp_hands},
}
EXTRA_LABELS = {"shift": "Shift", "dept": "Department", "main_shift": "Main Shift"}


# ─── Endpoints ─────────────────────────────────────────────────────────────


def _date(value: str | None, name: str) -> date:
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"{name} is required (YYYY-MM-DD)")


@router.get("/nbjcl/attendance-register/setup")
def attendance_register_setup(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    branch_id: int | None = None,
):
    """Report list with each report's date mode and filter, plus the filter options of the branch."""
    if not branch_id:
        raise HTTPException(status_code=400, detail="branch_id is required")
    shifts = [r[0] for r in db.execute(text("""
        SELECT DISTINCT sp.spell_code FROM spell_mst sp JOIN shift_mst sh ON sh.shift_id = sp.shift_id
        WHERE sh.branch_id = :b AND IFNULL(sp.spell_code, '') <> '' ORDER BY sp.spell_code"""), {"b": branch_id})]
    main = [r[0] for r in db.execute(text(
        "SELECT DISTINCT shift_name FROM shift_mst WHERE branch_id = :b ORDER BY shift_name"), {"b": branch_id})]
    depts = [{"value": r.dept_code, "label": f"{r.dept_code} - {r.dept_desc}"} for r in db.execute(text("""
        SELECT dept_code, dept_desc FROM dept_mst WHERE branch_id = :b AND IFNULL(dept_code, '') <> ''
        ORDER BY dept_code"""), {"b": branch_id})]
    options = {"shift": [{"value": s, "label": s} for s in shifts],
               "main_shift": [{"value": s, "label": s} for s in main], "dept": depts}
    reports = {k: {"title": v["title"], "dates": v["dates"], "span": v.get("span", "fortnight"),
                   "extra": ({"label": EXTRA_LABELS[v["extra"]],
                              "options": [{"value": "", "label": "All"}, *options[v["extra"]]]} if v["extra"] else None)}
               for k, v in REPORTS.items()}
    return {"data": reports}


@router.get("/nbjcl/attendance-register/{report}")
def attendance_register_report(
    report: str,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    branch_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    extra: str = "",
):
    """One Attendance Register report as display-ordered rows plus its column list."""
    spec = REPORTS.get(report)
    if not spec:
        raise HTTPException(status_code=404, detail=f"Unknown report '{report}'")
    if not branch_id:
        raise HTTPException(status_code=400, detail="branch_id is required")
    t = _date(date_to, "date_to")
    f = t if spec["dates"] == "single" else _date(date_from, "date_from")
    if f > t:
        raise HTTPException(status_code=400, detail="From date is after To date")
    if (t - f).days > 92:
        raise HTTPException(status_code=400, detail="Select a period of three months or less")
    try:
        columns, rows = spec["build"](db, int(branch_id), f, t, (extra or "").strip())
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001 — surfaced to the page
        logger.error(f"NBJCL attendance report {report} failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    fields = [c["field"] for c in columns]
    data = [{"id": i, **{k: (round(v, 3) if isinstance(v, float) else v) for k, v in r.items() if k in fields}}
            for i, r in enumerate(rows)]
    return {"title": spec["title"], "columns": columns, "data": data, "total": len(data)}
