"""Winsome Reports > Registeration + HTML Reports (see __init__.py).

Legacy reads EmpImage (face registrations of the attendance app) against the legacy employee master
PayOEMP. Faces = the mirrored legacy EmpImage (2021..2026-11, re-sync with migrate_payowagesrate_ocp.py
EmpImage --skip=ActualImage --index=emp_code --execute --replace) PLUS faces registered since in VoWERP
(employee_face_mst, mapped to the ECode through hrms_ed_official_details). PayOEMP (the mirror) stays the
worker universe, as in legacy — all rows, no status filter. VoWERP updated_by 0 (the mobile app) shows as "".
"""
from src.hrms.wagesSalaryProcess import UCI

from ._common import _col, _layout, _num, rows, spec

# one row per face: legacy EmpImage + VoWERP registrations
_FACE_SRC = f"""
    SELECT emp_code {UCI} AS ecode, emp_name {UCI} AS fname, CreatedDate AS created, IFNULL(userid, '') {UCI} AS userid
    FROM EmpImage WHERE IFNULL(emp_code, '') <> ''
    UNION ALL
    SELECT o.emp_code {UCI}, CONCAT_WS(' ', p.first_name, p.middle_name, p.last_name) {UCI},
           fm.updated_date_time, IFNULL(u.name, '') {UCI}
    FROM employee_face_mst fm
    JOIN hrms_ed_official_details o ON o.eb_id = fm.eb_id AND o.active = 1 AND o.branch_id = :b
    LEFT JOIN hrms_ed_personal_details p ON p.eb_id = fm.eb_id
    LEFT JOIN user_mst u ON u.user_id = fm.updated_by
    WHERE fm.active = 1 AND IFNULL(o.emp_code, '') <> ''"""


def _faces(db, b, f=None, t=None) -> list[dict]:
    return rows(db, f"""
        SELECT x.ecode, e.ECode IS NOT NULL AS in_master, IFNULL(e.EName, x.fname) AS ename,
               IFNULL(e.Grade, '') AS grade, IFNULL(e.EGroup, '') AS egroup, IFNULL(e.SubGroup, '') AS subgroup,
               x.created, x.userid
        FROM ({_FACE_SRC}) x LEFT JOIN PayOEMP e ON e.ECode = x.ecode
        WHERE :f IS NULL OR DATE(x.created) BETWEEN :f AND :t""", {"b": b, "f": f, "t": t})


def _workers(db, b) -> list[dict]:
    """PayOEMP workers with their face count (legacy: PayOEMP left join EmpImage)."""
    return rows(db, f"""
        SELECT e.ECode AS ecode, e.EName AS ename, IFNULL(e.Grade, '') AS grade, IFNULL(e.SubGroup, '') AS subgroup,
               IFNULL(fc.n, 0) AS faces
        FROM PayOEMP e
        LEFT JOIN (SELECT ecode, COUNT(*) n FROM ({_FACE_SRC}) x GROUP BY ecode) fc ON fc.ecode = e.ECode""", {"b": b})


def _sl(det: list[dict]) -> list[dict]:
    for i, r in enumerate(det, start=1):
        r["sl"] = i
    return det


def registered_details(db, b, f, t, extra):
    """RegisteredEmployeeDetails_WIL: faces registered in the period, by worker code."""
    det = sorted(_faces(db, b, f, t), key=lambda r: (r["ecode"], r["ename"], r["created"]))
    for r in det:
        r["regd"] = r["created"].strftime("%d/%m/%Y %H:%M") if r["created"] else ""
    cols = [_num("sl", "SL#", 70), _col("ecode", "Worker Code", width=120), _col("ename", "Worker Name", width=260),
            _col("regd", "Regd.Date", width=140)]
    return cols, _sl(det)


def pending_summary(db, b, f, t, extra):
    """PendingForRegistrationSummary_WIL: workers, registered faces and pending per grade (desc) / sub group."""
    agg: dict = {}
    for w in _workers(db, b):
        s = agg.setdefault((w["grade"], w["subgroup"]), {"grade": w["grade"], "subgroup": w["subgroup"],
                                                         "total": 0, "regd": 0})
        s["total"] += max(w["faces"], 1)  # legacy left join counts a worker once per image
        s["regd"] += w["faces"]
    det = [agg[k] for k in sorted(sorted(agg), key=lambda k: k[0], reverse=True)]
    for s in det:
        s["pending"] = s["total"] - s["regd"]
    cols = [_col("grade", "Grade", width=150), _col("subgroup", "SubGroup", width=220), _num("total", "TotalWorker", 110),
            _num("regd", "Regd", 90), _num("pending", "Pending", 90)]
    return cols, _layout(det, [], ["total", "regd", "pending"], "grade", "subgroup")


def pending_details(db, b, f, t, extra):
    """PendingForRegistrationDetails_WIL: PayOEMP workers with no face, by grade (desc) and sub group."""
    det = [w for w in _workers(db, b) if not w["faces"]]
    det.sort(key=lambda w: w["ecode"])
    det.sort(key=lambda w: w["subgroup"])
    det.sort(key=lambda w: w["grade"], reverse=True)
    cols = [_num("sl", "SL#", 70), _col("grade", "Grade", width=150), _col("subgroup", "Sub Group", width=220),
            _col("ecode", "Worker Code", width=120), _col("ename", "Worker Name", width=260)]
    return cols, _sl(det)


def registered_user_date(db, b, f, t, extra):
    """RegisteredEmployeeUserWiseDateWise_WIL: every face per registering user in time order (legacy has
    no date filter; the period narrows it here)."""
    det = sorted(_faces(db, b, f, t), key=lambda r: (r["userid"], r["created"], r["ecode"]))
    for r in det:
        r["regd"] = r["created"].strftime("%d/%m/%Y %H:%M") if r["created"] else ""
    cols = [_num("sl", "SL", 60), _col("userid", "USER", width=150), _col("regd", "CREATED DATE", width=150),
            _col("ecode", "EMP_CODE", width=120), _col("ename", "EMP_NAME", width=260)]
    return cols, _sl(det)


def worker_list_with_photo(db, b, f, t, extra):
    """FuncEmployeeListWithImage (HTML): registered workers found in PayOEMP, by grade / group / sub group / code with user
    and time; `extra` = grade."""
    # ponytail: the legacy page embedded each photo (<img>); the grid lists the registrations only
    det = [r for r in _faces(db, b) if r["in_master"] and extra in ("", r["grade"])]
    det.sort(key=lambda r: (r["grade"], r["egroup"], r["subgroup"], r["ecode"]))
    for r in det:
        r["regd"] = r["created"].strftime("%d/%m/%Y %H:%M") if r["created"] else ""
    cols = [_num("sl", "Sl.No.", 70), _col("ecode", "ECode", width=110), _col("ename", "EName", width=240),
            _col("grade", "Grade", width=130), _col("egroup", "Group", width=150), _col("subgroup", "Sub Group", width=170),
            _col("userid", "User", width=120), _col("regd", "Time", width=140)]
    return cols, _sl(det)


def _grades(db, b):
    return [{"value": r["g"], "label": r["g"]}
            for r in rows(db, "SELECT DISTINCT Grade g FROM PayOEMP WHERE IFNULL(Grade, '') <> '' ORDER BY 1")]


REPORTS: dict[str, dict[str, dict]] = {
    "registeration": {
        "registeredEmployeeDetails": spec("Registered Employee Details", registered_details, span="month"),
        "pendingForRegisterationSummary": spec("Pending For Registeration Summary", pending_summary, dates="none"),
        "pendingForRegisterationDetails": spec("Pending For Registeration Details", pending_details, dates="none"),
        "registeredEmployeeUserWiseDateWise": spec("Registered Employee User Wise Date Wise", registered_user_date,
                                                   span="month"),
    },
    "htmlReports": {
        "workerListWithPhoto": spec("Worker List with Photo", worker_list_with_photo, dates="none",
                                    extra={"label": "Grade", "options": _grades}),
    },
}
