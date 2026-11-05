"""NBJCL Reports — Registeration + HTML Reports. See src/hrms/nbjclreports/__init__.py for the spec shape.

Legacy "registration" = the face / photo registration of the attendance app (table EmpImage, one row
per captured face with Emp_Code, userid, CreatedDate). Faces are now registered in VoWERP:
employee_face_mst (eb_id, photo_html = the JPEG, updated_by -> user_mst, updated_date_time), so these
reports read that, for the branch's employees (hrms_ed_official_details). Legacy Grade / SubGroup come
from the legacy employee master PayOEMP by employee code, falling back to the VoWERP category.

ponytail: hrms_employee_face (the newer photo table) is empty on nbjcl, so only employee_face_mst is
read; add it as a second source when faces start landing there. user id 0 (the mobile app) shows as "".
"""
from sqlalchemy.sql import text

from src.hrms.nbjclAttendanceReports import _col, _dmy, _layout, _num
from src.hrms.wagesSalaryProcess import UCI

ENAME = """CONCAT_WS(' ', NULLIF(TRIM(p.first_name), ''), NULLIF(TRIM(p.middle_name), ''),
                     NULLIF(TRIM(p.last_name), ''))"""


def _faces(db, b, f=None, t=None) -> list[dict]:
    """Active face registrations of the branch's employees (one row per face, as legacy EmpImage),
    optionally those registered in f..t."""
    rows = db.execute(text(f"""
        SELECT o.emp_code AS ecode, {ENAME} AS ename, fm.updated_date_time AS created, IFNULL(u.name, '') AS userid
        FROM employee_face_mst fm
        JOIN hrms_ed_official_details o ON o.eb_id = fm.eb_id AND o.active = 1 AND o.branch_id = :b
        LEFT JOIN hrms_ed_personal_details p ON p.eb_id = fm.eb_id
        LEFT JOIN user_mst u ON u.user_id = fm.updated_by
        WHERE fm.active = 1 AND IFNULL(o.emp_code, '') <> ''
          AND (:f IS NULL OR DATE(fm.updated_date_time) BETWEEN :f AND :t)"""), {"b": b, "f": f, "t": t})
    return [{**dict(r._mapping), "ename": r.ename or ""} for r in rows]


def _employees(db, b) -> list[dict]:
    """The branch's working employees (status 35) with legacy Grade / SubGroup, whether a face is
    registered, and the latest registration."""
    rows = db.execute(text(f"""
        SELECT o.emp_code AS ecode, {ENAME} AS ename,
               IFNULL(NULLIF(e.Grade, ''), '') AS grade, IFNULL(NULLIF(e.SubGroup, ''), IFNULL(cm.cata_desc, '')) AS subgroup,
               IFNULL(d.dept_desc, '') AS dept, IFNULL(g.desig, '') AS desig, IFNULL(cm.cata_desc, '') AS egroup,
               o.date_of_join, fc.created, IFNULL(u.name, '') AS userid
        FROM hrms_ed_official_details o
        JOIN hrms_ed_personal_details p ON p.eb_id = o.eb_id AND p.status_id = 35
        LEFT JOIN PayOEMP e ON e.ECode {UCI} = o.emp_code {UCI}
        LEFT JOIN category_mst cm ON cm.cata_id = o.catagory_id
        LEFT JOIN sub_dept_mst sd ON sd.sub_dept_id = o.sub_dept_id
        LEFT JOIN dept_mst d ON d.dept_id = sd.dept_id
        LEFT JOIN designation_mst g ON g.designation_id = o.designation_id
        LEFT JOIN (SELECT eb_id, MAX(updated_date_time) created,
                          SUBSTRING_INDEX(GROUP_CONCAT(updated_by ORDER BY updated_date_time DESC), ',', 1) by_id
                   FROM employee_face_mst WHERE active = 1 GROUP BY eb_id) fc ON fc.eb_id = o.eb_id
        LEFT JOIN user_mst u ON u.user_id = fc.by_id
        WHERE o.active = 1 AND o.branch_id = :b AND IFNULL(o.emp_code, '') <> ''"""), {"b": b})
    return [{**dict(r._mapping), "ename": r.ename or ""} for r in rows]


def _sl(rows: list[dict]) -> list[dict]:
    for i, r in enumerate(rows, start=1):
        r["sl"] = i
    return rows


def registered_details(db, b, f, t, extra):
    """RegisteredEmployeeDetails_NJB: faces registered in the period, by worker code."""
    det = sorted(_faces(db, b, f, t), key=lambda r: (r["ecode"], r["ename"], r["created"]))
    for r in det:
        r["regd"] = _dmy(r["created"])
    cols = [_num("sl", "SL#", 70), _col("ecode", "Worker Code", width=120), _col("ename", "Worker Name", width=260),
            _col("regd", "Regd.Date", width=110)]
    return cols, _sl(det)


def pending_summary(db, b, f, t, extra):
    """PendingForRegistrationSummary_NJB: workers, registered and pending per grade and sub group."""
    agg: dict = {}
    for e in _employees(db, b):
        s = agg.setdefault((e["grade"], e["subgroup"]), {"grade": e["grade"], "subgroup": e["subgroup"],
                                                         "total": 0, "regd": 0, "pending": 0})
        s["total"] += 1
        s["regd" if e["created"] else "pending"] += 1
    det = [agg[k] for k in sorted(agg, key=lambda k: (k[0], k[1]), reverse=True)]
    cols = [_col("grade", "Grade", width=150), _col("subgroup", "SubGroup", width=220), _num("total", "TotalWorker", 110),
            _num("regd", "Regd", 90), _num("pending", "Pending", 90)]
    return cols, _layout(det, [], ["total", "regd", "pending"], "grade", "subgroup")


def pending_details(db, b, f, t, extra):
    """PendingForRegistrationDetails_NJB: workers with no face registered, by grade (desc) and sub group."""
    det = [e for e in _employees(db, b) if not e["created"]]
    det.sort(key=lambda e: e["ecode"])
    det.sort(key=lambda e: e["subgroup"])
    det.sort(key=lambda e: e["grade"], reverse=True)
    cols = [_num("sl", "SL#", 70), _col("grade", "Grade", width=150), _col("subgroup", "Sub Group", width=220),
            _col("ecode", "Worker Code", width=120), _col("ename", "Worker Name", width=260)]
    return cols, _sl(det)


def registered_user_date(db, b, f, t, extra):
    """RegisteredEmployeeUserWiseDateWise_NJB: faces registered in the period per registering user, in
    time order, with a count per user."""
    det = sorted(_faces(db, b, f, t), key=lambda r: (r["userid"], r["created"], r["ecode"]))
    for r in det:
        r["regd"] = r["created"].strftime("%d/%m/%Y %H:%M") if r["created"] else ""
    cols = [_col("grp", "User", width=160), _col("regd", "Created Date", width=150),
            _col("ecode", "Emp_Code", width=120), _col("ename", "Emp_Name", width=260), _num("count", "Count", 80)]
    return cols, _layout(det, [lambda r: r["userid"] or "(mobile app)"], [], "grp", "regd", count_field="count")


def worker_list_with_photo(db, b, f, t, extra):
    """FuncEmployeeListWithImage (HTML): workers with their registration (user, time); legacy listed only
    the registered ones, `extra` Y / N narrows to with / without a photo."""
    # ponytail: the legacy page embedded each photo (<img>); the grid shows Photo Y / N only
    det = []
    for e in _employees(db, b):
        e["photo"] = "Y" if e["created"] else "N"
        if extra in ("", e["photo"]):
            e["doj"] = _dmy(e["date_of_join"])
            e["regd"] = e["created"].strftime("%d/%m/%Y %H:%M") if e["created"] else ""
            det.append(e)
    det.sort(key=lambda e: (e["grade"], e["egroup"], e["subgroup"], e["ecode"]))
    cols = [_num("sl", "Sl.No.", 70), _col("ecode", "ECode", width=110), _col("ename", "EName", width=240),
            _col("dept", "Department", width=180), _col("desig", "Designation", width=180),
            _col("egroup", "Group", width=170), _col("doj", "Joining Date", width=110),
            _col("userid", "User", width=130), _col("regd", "Time", width=140), _col("photo", "Photo", width=70)]
    return cols, _sl(det)


# group (menu folder after hrms/nbjclreports/) -> {report key: spec}
REPORTS: dict[str, dict[str, dict]] = {
    "registeration": {
        "registeredEmployeeDetails": {"title": "Registered Employee Details", "dates": "range", "span": "month",
                                      "extra": None, "build": registered_details},
        "pendingForRegisterationSummary": {"title": "Pending For Registeration Summary", "dates": "none",
                                           "extra": None, "build": pending_summary},
        "pendingForRegisterationDetails": {"title": "Pending For Registeration Details", "dates": "none",
                                           "extra": None, "build": pending_details},
        "registeredEmployeeUserWiseDateWise": {"title": "Registered Employee User Wise Date Wise", "dates": "range",
                                               "span": "month", "extra": None, "build": registered_user_date},
    },
    "htmlReports": {
        "workerListWithPhoto": {"title": "Worker List with Photo", "dates": "none",
                                "extra": {"label": "Photo", "options": [{"value": "Y", "label": "With photo"},
                                                                        {"value": "N", "label": "Without photo"}]},
                                "build": worker_list_with_photo},
    },
}
