"""
Winsome "Production" menu — port of the legacy Smart-Eye Winsome (WIL) production forms.

Legacy menu 35000 "Production" (OMNU) -> portal menu winsomeProduction/*:

    kind             legacy form              table          dept  amount rule
    winding          FrmProdWinding_WIL       PayOProdWDG    14    Prod1 * QRate
    beaming          FrmProdBeaming_WIL       PayOProdBMG    15    3-way split per machine hour (see _calc)
    weaving          FrmProdWeaving_WIL       PayOProdWVG    16    Prod1 = cuts.sixteenths
    sackSewing       FrmProdSackSewing_WIL    PayOProdSACK   18    Prod1 * QRate
    productionEntry  FrmProduction_WIL        PayProdAll     any   Qty * Rate
    dailyProduction  FrmDailyProd_WIL (*)     PayProdWIL     any   Qty * Rate

(*) the menu row exists in legacy but the form was never shipped in any DLL; PayProdWIL is the
    table it was meant for (same document shape as PayProdAll plus machine columns).

The tables are mirrored 1:1 from the legacy SQL Server into the winsome tenant DB (same names and
columns, history included — dbqueries/migrations/migrate_payowagesrate_ocp.py), so the wages
incentive port can read them exactly as legacy did. A document = all rows sharing one DocEntry;
saving deletes and re-inserts the document's rows, exactly like the legacy forms.

Lookups come from the native tenant tables where they line up 1:1 with legacy codes
(hrms emp_code = ECode = OrgECode, machine_mst.mech_code = OMCH.CODE, dept_mst.dept_code = DeptCode,
shift_mst/spell_mst = Shift); qualities (PayOQLT) and occupations (ODPT) are mirrors.
Amounts are recomputed here on save; the browser only previews them.
"""

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import bindparam
from sqlalchemy.orm import Session
from sqlalchemy.sql import text

from src.authorization.utils import get_current_user_with_refresh
from src.config.db import get_tenant_db
from src.hrms.workerRate import get_rate_employees_query

router = APIRouter()

# ponytail: Winsome has one legacy company/location; every legacy row carries these.
COMP_CODE, LOCATION, UNIT_CODE = "WIL", "FACTORY", "01"
PC_NAME = "VOWERP"
LEGACY_BLANK_DATE = datetime(1900, 1, 1)  # legacy writes '' into datetime columns
MAX_PROD_HR = 8  # legacy: hours > 8 or <= 0 snap to 8

FORMS: dict[str, dict] = {
    "winding": {"table": "PayOProdWDG", "frm": "FrmProdWinding_WIL", "obj": "WDG", "dept": "14", "calc": "plain"},
    "beaming": {"table": "PayOProdBMG", "frm": "FrmProdBeaming_WIL", "obj": "BMG", "dept": "15", "calc": "beaming"},
    # fill: legacy "Fill >>" — every loom of the machine type + weavers present (TBLF5 *_Weaver = OCP 1607).
    "weaving": {"table": "PayOProdWVG", "frm": "FrmProdWeaving_WIL", "obj": "WVG", "dept": "16", "calc": "weaving",
                "fill": {"desig": "Weaver", "ocp": "1607"}},
    "sackSewing": {"table": "PayOProdSACK", "frm": "FrmProdSackSewing_WIL", "obj": "SACK", "dept": "18",
                   "calc": "plain"},
    "productionEntry": {"table": "PayProdAll", "doc": True, "calc": "qty"},
    "dailyProduction": {"table": "PayProdWIL", "doc": True, "calc": "qty"},
}
# Beaming: occupations that also receive the 2.6003% head share.
BEAMING_HEAD_OCPS = {"22104", "22119"}
BEAMING_HEAD_SHARE = 0.026003

# Document tables (PayProdAll/PayProdWIL) name a few columns differently; the API always uses the
# machine-table names.
DOC_RENAME = {"DocDate": "WDate", "WShift": "Shift", "Qty": "Prod1", "Rate": "QRate"}
LINE_FIELDS = ("SecCode", "OcpCode", "MchType", "Mch1Code", "Mch2Code", "ECode", "Prod1", "Prod2",
               "Prod_HR", "Mch_HR", "QCode", "QRate", "Remarks")


def _form(kind: str) -> dict:
    form = FORMS.get(kind)
    if not form:
        raise HTTPException(status_code=404, detail=f"Unknown production form {kind}")
    return form


_COLS: dict[tuple[str, str], frozenset[str]] = {}  # (schema, table) -> columns; schemas never change at runtime


def _columns(db: Session, table: str) -> frozenset[str]:
    """Column names of a mirrored legacy table (they differ slightly between WDG/BMG/WVG/...)."""
    schema = db.execute(text("SELECT DATABASE()")).scalar()
    key = (schema, table)
    if key not in _COLS:
        rows = db.execute(text("""SELECT COLUMN_NAME FROM information_schema.COLUMNS
                                  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t"""), {"t": table}).fetchall()
        if not rows:
            raise HTTPException(status_code=500, detail=f"Table {table} is missing in this tenant")
        _COLS[key] = frozenset(r[0] for r in rows)
    return _COLS[key]


def _num(v, name: str, line: int) -> float:
    if v in (None, ""):
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"Line {line}: {name} must be a number")


def _calc(calc: str, ln: dict, line: int) -> dict:
    """Legacy amount rules. Returns CalcRate / Amount / PayableAmt for one line."""
    prod, rate, hr = ln["Prod1"], ln["QRate"], ln["Prod_HR"]
    if calc == "qty":
        return {"CalcRate": 0.0, "Amount": round(prod * rate, 2), "PayableAmt": 0.0}
    if calc == "weaving":
        cuts, frac = divmod(round(prod * 100), 100)  # Prod1 is cuts.sixteenths, e.g. 12.15
        if frac > 15:
            raise HTTPException(status_code=400, detail=f"Line {line}: decimal part of production can't exceed 15")
        amt = (cuts * rate + frac * 0.0625 * rate) if prod > 0 and hr > 0 else 0.0
        return {"CalcRate": 0.0, "Amount": round(amt, 2), "PayableAmt": 0.0}
    if calc == "beaming":
        mch_hr = ln["Mch_HR"]
        if prod > 0 and mch_hr <= 0:
            raise HTTPException(status_code=400, detail=f"Line {line}: machine hours are required")
        gross = prod * rate
        head = gross * BEAMING_HEAD_SHARE
        calc_rate = (gross - head) / 3 / mch_hr if mch_hr > 0 else 0.0
        amount = calc_rate * hr
        payable = amount + head if ln["OcpCode"] in BEAMING_HEAD_OCPS else amount
        return {"CalcRate": round(calc_rate, 6), "Amount": round(amount, 2), "PayableAmt": round(payable, 2)}
    amt = prod * rate if prod > 0 and hr > 0 else 0.0  # plain: winding / sack sewing
    return {"CalcRate": 0.0, "Amount": round(amt, 2), "PayableAmt": 0.0}


def _parse_lines(form: dict, body: dict) -> list[dict]:
    raw = body.get("lines")
    if not isinstance(raw, list) or not raw:
        raise HTTPException(status_code=400, detail="Enter at least one line")
    lines, seen = [], set()
    for i, r in enumerate(raw, start=1):
        if not isinstance(r, dict):
            raise HTTPException(status_code=400, detail=f"Line {i}: invalid")
        ln = {k: str(r.get(k) or "").strip() for k in LINE_FIELDS}
        for k in ("Prod1", "Prod2", "Prod_HR", "Mch_HR", "QRate"):
            ln[k] = _num(r.get(k), k, i)
        # Fill forms save idle looms too (machine, no worker) — legacy WVG history is full of them.
        if not ln["ECode"] and not (form.get("fill") and ln["Mch1Code"]):
            raise HTTPException(status_code=400, detail=f"Line {i}: employee is required")
        if not form.get("doc"):  # machine stays optional, as in legacy (sack sewing rows have none)
            if ln["Prod_HR"] > MAX_PROD_HR or ln["Prod_HR"] <= 0:
                ln["Prod_HR"] = MAX_PROD_HR
        elif ln["ECode"] in seen:  # legacy: "Employee Already Selected in Line No."
            raise HTTPException(status_code=400, detail=f"Line {i}: employee {ln['ECode']} already entered")
        if ln["ECode"]:
            seen.add(ln["ECode"])
        if ln["Prod1"] < 0 or ln["QRate"] < 0:
            raise HTTPException(status_code=400, detail=f"Line {i}: values can't be negative")
        ln.update(_calc(form["calc"], ln, i))
        lines.append(ln)
    return lines


def _lookup(db: Session, sql: str, codes: set[str], params: dict | None = None) -> dict[str, str]:
    if not codes:
        return {}
    stmt = text(sql).bindparams(bindparam("codes", expanding=True))
    rows = db.execute(stmt, {"codes": list(codes), **(params or {})}).fetchall()
    return {str(r[0]): r[1] or "" for r in rows}


# ─── Endpoints ────────────────────────────────────────────────────────────


@router.get("/setup/{kind}")
def prod_setup(kind: str, request: Request, db: Session = Depends(get_tenant_db),
               token_data: dict = Depends(get_current_user_with_refresh)):
    """Pickers for one form. Fixed-department forms use their legacy dept; the document forms
    (productionEntry/dailyProduction) pass dept_code from their header."""
    form = _form(kind)
    co_id = request.query_params.get("co_id")
    if not co_id:
        raise HTTPException(status_code=400, detail="co_id is required")
    raw_branch = request.query_params.get("branch_id")
    branch_id = int(raw_branch) if raw_branch not in (None, "", "null") else None
    dept = form.get("dept") or request.query_params.get("dept_code") or ""

    employees = db.execute(get_rate_employees_query(), {"co_id": int(co_id), "branch_id": branch_id}).fetchall()
    data = {
        "dept_code": dept,
        "employees": [{"value": r.emp_code, "label": f"{r.emp_code} - {' '.join((r.full_name or '').split())}"}
                      for r in employees if r.emp_code],
        "shifts": [r[0] for r in db.execute(text(
            "SELECT shift_name FROM shift_mst WHERE (:b IS NULL OR branch_id = :b) GROUP BY shift_name "
            "ORDER BY shift_name"), {"b": branch_id}).fetchall()],
        "depts": [{"value": r.dept_code, "label": f"{r.dept_code} - {r.dept_desc}"} for r in db.execute(text(
            "SELECT d.dept_code, MIN(d.dept_desc) AS dept_desc FROM dept_mst d "
            "JOIN branch_mst b ON b.branch_id = d.branch_id WHERE b.co_id = :co "
            "AND (:b IS NULL OR d.branch_id = :b) GROUP BY d.dept_code ORDER BY CAST(d.dept_code AS UNSIGNED)"),
            {"co": int(co_id), "b": branch_id}).fetchall()],
        "machines": [], "mch_types": [], "qualities": [], "occupations": [],
    }
    if dept:
        data["machines"] = [{"value": r.mech_code, "label": r.machine_name or r.mech_code} for r in db.execute(text(
            "SELECT m.mech_code, MIN(m.machine_name) AS machine_name FROM machine_mst m "
            "JOIN dept_mst d ON d.dept_id = m.dept_id WHERE d.dept_code = :dept AND m.active = 1 "
            "AND (:b IS NULL OR d.branch_id = :b) GROUP BY m.mech_code ORDER BY m.mech_code"),
            {"dept": dept, "b": branch_id}).fetchall()]
        # Machines used in this form's history but missing from machine_mst (e.g. winding WDG01).
        if "Mch1Code" in _columns(db, form["table"]):
            known = {m["value"] for m in data["machines"]}
            data["machines"] += [{"value": r[0], "label": r[0]} for r in db.execute(text(
                f"SELECT DISTINCT Mch1Code FROM `{form['table']}` WHERE DeptCode = :dept AND Mch1Code <> '' "
                "ORDER BY Mch1Code"), {"dept": dept}).fetchall() if r[0] not in known]
        data["qualities"] = [{"value": r.QCode, "label": f"{r.QCode} - {r.QName}".rstrip(" -"),
                              "rate": float(r.Rate or 0)} for r in db.execute(text(
            "SELECT QCode, MIN(QName) AS QName, MIN(Rate) AS Rate FROM PayOQLT "
            "WHERE DeptCode = :dept AND QCode <> '' GROUP BY QCode ORDER BY QCode"), {"dept": dept}).fetchall()]
        data["occupations"] = [{"value": r.OCPCode, "label": f"{r.OCPCode} - {r.OCPName}"} for r in db.execute(text(
            "SELECT OCPCode, MIN(OCPName) AS OCPName FROM ODPT WHERE DeptCode = :dept AND OCPCode <> '' "
            "GROUP BY OCPCode ORDER BY OCPCode"), {"dept": dept}).fetchall()]
    if "MchType" in _columns(db, form["table"]):
        data["mch_types"] = [r[0] for r in db.execute(text(
            f"SELECT DISTINCT MchType FROM `{form['table']}` WHERE MchType <> '' ORDER BY MchType")).fetchall()]
    return {"data": data}


# Machine-wise attendance. daily_ebmc_attendance.attendace_date/spell are never filled in this tenant:
# date and spell (-> shift) come from the parent daily_attendance row.
_ATTEN_FROM = """
        FROM daily_ebmc_attendance e
        JOIN daily_attendance da ON da.daily_atten_id = e.daily_atten_id AND COALESCE(da.is_active, 1) = 1
        JOIN machine_mst m ON m.machine_id = e.mc_id
        JOIN spell_mst sp ON sp.spell_id = da.spell_id
        JOIN shift_mst s ON s.shift_id = sp.shift_id
        JOIN hrms_ed_official_details o ON o.eb_id = da.eb_id AND o.active = 1
        LEFT JOIN hrms_ed_personal_details pd ON pd.eb_id = da.eb_id
        WHERE COALESCE(e.is_active, 1) = 1 AND"""


@router.get("/fill/{kind}")
def prod_fill(kind: str, request: Request, db: Session = Depends(get_tenant_db),
              token_data: dict = Depends(get_current_user_with_refresh)):
    """Legacy FrmProdWeaving_WIL "Fill >>": one line per loom of the machine type in the form's
    department, joined to the weavers present that date/shift (hours summed over the shift's
    spells), with the quality last woven on the loom and its rate. Idle looms come back with no
    worker, like legacy; a loom run by two weavers gives two lines."""
    form = _form(kind)
    fill = form.get("fill")
    if not fill:
        raise HTTPException(status_code=400, detail="This form has no Fill")
    q = request.query_params
    wdate, shift, mch_type = q.get("wdate") or "", q.get("shift") or "", q.get("mch_type") or ""
    if not wdate or not shift or not mch_type:
        raise HTTPException(status_code=400, detail="Select date, shift and machine type first")
    raw_branch = q.get("branch_id")
    branch_id = int(raw_branch) if raw_branch not in (None, "", "null") else None
    p = {"d": wdate, "shift": shift, "dept": form["dept"], "mt": mch_type, "b": branch_id, "desig": fill["desig"]}

    # Legacy MchType "SACKING" = machine_type_mst "Sacking Loom".
    looms = db.execute(text("""
        SELECT m.mech_code FROM machine_mst m
        JOIN dept_mst d ON d.dept_id = m.dept_id
        JOIN machine_type_mst mt ON mt.machine_type_id = m.machine_type_id
        WHERE d.dept_code = :dept AND m.active = 1 AND mt.machine_type_name LIKE CONCAT(:mt, '%')
          AND (:b IS NULL OR d.branch_id = :b)
        GROUP BY m.mech_code ORDER BY m.mech_code"""), p).fetchall()

    workers: dict[str, list] = {}
    for r in db.execute(text(f"""
        SELECT m.mech_code, o.emp_code,
               TRIM(CONCAT_WS(' ', pd.first_name, pd.middle_name, pd.last_name)) AS ename,
               SUM(da.working_hours) AS hrs
        {_ATTEN_FROM} da.attendance_date = :d AND s.shift_name = :shift
          AND (:b IS NULL OR da.branch_id = :b)
          AND da.worked_designation_id IN (SELECT designation_id FROM designation_mst WHERE desig = :desig)
        GROUP BY m.mech_code, o.emp_code, ename HAVING SUM(da.working_hours) > 0
        ORDER BY o.emp_code"""), p):
        workers.setdefault(r.mech_code, []).append(r)
    if not workers:
        raise HTTPException(status_code=404, detail="No attendance found — please do the attendance entry first.")

    # Quality last woven on each loom up to this date (latest date, then latest shift). MAX per loom
    # is a loose index scan on ix_mch; a correlated ORDER BY ... LIMIT 1 per loom took ~7 s.
    last_q = {r.Mch1Code: r.QCode for r in db.execute(text(f"""
        SELECT w.Mch1Code, w.QCode FROM `{form['table']}` w
        JOIN (SELECT Mch1Code, MAX(WDate) AS md FROM `{form['table']}` WHERE WDate <= :d GROUP BY Mch1Code) x
          ON x.Mch1Code = w.Mch1Code AND x.md = w.WDate
        ORDER BY w.Mch1Code, w.Shift"""), p)}
    rates = {r[0]: float(r[1] or 0) for r in db.execute(text(
        "SELECT QCode, MIN(Rate) FROM PayOQLT WHERE DeptCode = :dept GROUP BY QCode"), p)}
    dept_rate = next(iter(rates.values()), 0.0)  # legacy: TOP 1 rate of the department
    lines = []
    for lm in looms:
        qcode = last_q.get(lm.mech_code) or ""
        rate = rates.get(qcode, dept_rate)
        for w in workers.get(lm.mech_code) or [None]:
            lines.append({"Mch1Code": lm.mech_code, "QCode": qcode, "QRate": rate,
                          "ECode": w.emp_code if w else "", "EName": w.ename if w else "",
                          "OcpCode": fill["ocp"] if w else "", "Prod_HR": float(w.hrs) if w else 0.0})
    return {"data": lines}


@router.get("/machine_fill/{kind}")
def machine_fill(kind: str, request: Request, db: Session = Depends(get_tenant_db),
                 token_data: dict = Depends(get_current_user_with_refresh)):
    """Picking a machine pre-fills the worker allotted to it in that day's attendance and the
    quality/rate last produced on it (legacy GetWorkerAttenDetails + LastQCode)."""
    form = _form(kind)
    q = request.query_params
    mch, wdate, shift = q.get("mch1_code") or "", q.get("wdate") or "", q.get("shift") or ""
    if not mch or not wdate:
        raise HTTPException(status_code=400, detail="mch1_code and wdate are required")
    # Hours = the worker's total on this machine over all spells of the shift (A1 + A2 ...).
    worker = db.execute(text(f"""
        SELECT o.emp_code, SUM(da.working_hours) AS hrs {_ATTEN_FROM}
        da.attendance_date = :d AND m.mech_code = :mch AND (:shift = '' OR s.shift_name = :shift)
        GROUP BY o.emp_code HAVING SUM(da.working_hours) > 0
        ORDER BY MIN(sp.spell_code), o.emp_code LIMIT 1"""), {"d": wdate, "mch": mch, "shift": shift}).first()
    date_col = "DocDate" if form.get("doc") else "WDate"
    rate_col = "Rate" if form.get("doc") else "QRate"
    last = None if "Mch1Code" not in _columns(db, form["table"]) else db.execute(text(f"""
        SELECT QCode, {rate_col} AS QRate FROM `{form['table']}`
        WHERE Mch1Code = :mch AND QCode <> '' AND {date_col} <= :d
        ORDER BY {date_col} DESC LIMIT 1"""), {"mch": mch, "d": wdate}).first()
    return {"data": {"ECode": worker.emp_code if worker else "", "Hours": float(worker.hrs) if worker else 0.0,
                     "QCode": last.QCode if last else "",
                     "QRate": float(last.QRate) if last else None}}


@router.get("/list/{kind}")
def prod_list(kind: str, request: Request, db: Session = Depends(get_tenant_db),
              token_data: dict = Depends(get_current_user_with_refresh)):
    """One row per line (worker), newest first; doc_entry rides along so a row opens its document."""
    form = _form(kind)
    q = request.query_params
    page, limit = max(int(q.get("page", 1)), 1), min(max(int(q.get("limit", 25)), 1), 200)
    doc = form.get("doc")
    date_col, shift_col = ("DocDate", "WShift") if doc else ("WDate", "Shift")
    qty_col = "Qty" if doc else "Prod1"
    where = ["CompCode = :cc"]
    params: dict = {"cc": COMP_CODE}
    if not doc:
        where.append("FrmName = :frm")
        params["frm"] = form["frm"]
    if q.get("from_date"):
        where.append(f"{date_col} >= :fd")
        params["fd"] = q["from_date"]
    if q.get("to_date"):
        where.append(f"{date_col} <= :td")
        params["td"] = q["to_date"]
    if q.get("shift"):
        where.append(f"{shift_col} = :sh")
        params["sh"] = q["shift"]
    if q.get("search"):
        where.append(f"(ECode LIKE :s OR Mch1Code LIKE :s OR QCode LIKE :s OR CAST(DocEntry AS CHAR) = :se)"
                     if not doc else "(ECode LIKE :s OR DeptCode LIKE :s OR QCode LIKE :s OR CAST(DocEntry AS CHAR) = :se)")
        params["s"], params["se"] = f"%{q['search']}%", q["search"]
    w = " AND ".join(where)
    tbl = f"`{form['table']}`"
    cols = _columns(db, form["table"])
    total = db.execute(text(f"SELECT COUNT(*) FROM {tbl} WHERE {w}"), params).scalar() or 0
    amount_col = "PayableAmt" if "PayableAmt" in cols else "Amount"
    rate_col = "Rate" if doc else "QRate"
    mch = "Mch1Code" if "Mch1Code" in cols else "''"
    # Page the lines first, then name them (the employee join then touches only one page).
    rows = db.execute(text(f"""
        SELECT t.doc_entry, t.line_id, t.wdate, t.shift, t.dept_code, t.mch_code, t.eb_no,
               TRIM(CONCAT_WS(' ', p.first_name, p.middle_name, p.last_name)) AS name,
               t.quality, t.rate, t.prod, t.amount
        FROM (SELECT DocEntry AS doc_entry, LineID AS line_id, {date_col} AS wdate, {shift_col} AS shift,
                     DeptCode AS dept_code, {mch} AS mch_code, ECode AS eb_no, QCode AS quality,
                     {rate_col} AS rate, ROUND({qty_col}, 2) AS prod, ROUND({amount_col}, 2) AS amount
              FROM {tbl} WHERE {w}
              ORDER BY {date_col} DESC, DocEntry DESC, LineID
              LIMIT :lim OFFSET :off) t
        LEFT JOIN hrms_ed_official_details o
               ON o.emp_code = t.eb_no COLLATE utf8mb4_0900_ai_ci AND o.active = 1 AND t.eb_no <> ''
        LEFT JOIN hrms_ed_personal_details p ON p.eb_id = o.eb_id
        ORDER BY t.wdate DESC, t.doc_entry DESC, t.line_id"""),
        {**params, "lim": limit, "off": (page - 1) * limit}).fetchall()
    return {"data": [{**dict(r._mapping), "id": f"{r.doc_entry}-{r.line_id}"} for r in rows],
            "total": int(total), "page": page, "limit": limit}


@router.get("/doc/{kind}/{doc_entry}")
def prod_doc(kind: str, doc_entry: int, db: Session = Depends(get_tenant_db),
             token_data: dict = Depends(get_current_user_with_refresh)):
    form = _form(kind)
    rows = [dict(r._mapping) for r in db.execute(text(
        f"SELECT * FROM `{form['table']}` WHERE CompCode = :cc AND DocEntry = :de ORDER BY LineID"),
        {"cc": COMP_CODE, "de": doc_entry}).fetchall()]
    if not rows:
        raise HTTPException(status_code=404, detail="Document not found")
    rows = [{DOC_RENAME.get(k, k): v for k, v in r.items()} for r in rows]
    names = _lookup(db, """SELECT o.emp_code, TRIM(CONCAT(IFNULL(p.first_name,''),' ',IFNULL(p.last_name,'')))
                           FROM hrms_ed_official_details o JOIN hrms_ed_personal_details p ON p.eb_id = o.eb_id
                           WHERE o.emp_code IN :codes""", {r["ECode"] for r in rows if r.get("ECode")})
    first = rows[0]
    header = {"doc_entry": doc_entry, "wdate": first["WDate"], "shift": first.get("Shift") or "",
              "spell": first.get("Spell") or "", "dept_code": first.get("DeptCode") or "",
              "mch_type": first.get("MchType") or ""}
    lines = [{k: r.get(k) for k in (*LINE_FIELDS, "CalcRate", "Amount", "PayableAmt")} | {
        "EName": names.get(r.get("ECode") or "", r.get("EName") or "")} for r in rows]
    return {"data": {"header": header, "lines": lines}}


@router.post("/save/{kind}")
def prod_save(kind: str, body: dict, db: Session = Depends(get_tenant_db),
              token_data: dict = Depends(get_current_user_with_refresh)):
    """Create (no doc_entry) or replace (doc_entry) one production document."""
    form = _form(kind)
    table, doc = form["table"], form.get("doc")
    try:
        wdate = date.fromisoformat(str(body.get("wdate") or ""))
    except ValueError:
        raise HTTPException(status_code=400, detail="Production date is required")
    shift = str(body.get("shift") or "").strip()
    if not shift and not doc:
        raise HTTPException(status_code=400, detail="Shift is required")
    dept = form.get("dept") or str(body.get("dept_code") or "").strip()
    if not dept:
        raise HTTPException(status_code=400, detail="Department is required")
    spell, mch_type = str(body.get("spell") or "").strip(), str(body.get("mch_type") or "").strip()
    lines = _parse_lines(form, body)
    cols = _columns(db, table)
    user = str(token_data.get("user_id") or "")

    # Legacy stamps: new rows CreatedDate=now / UpdatedDate=1900-01-01; a re-save keeps CreatedDate.
    doc_entry = body.get("doc_entry")
    if doc_entry not in (None, "", 0):
        doc_entry = int(doc_entry)
        created, n = db.execute(text(f"SELECT MIN(CreatedDate), COUNT(*) FROM `{table}` "
                                     "WHERE CompCode = :cc AND DocEntry = :de"),
                                {"cc": COMP_CODE, "de": doc_entry}).first()
        if not n:
            raise HTTPException(status_code=404, detail="Document not found")
        db.execute(text(f"DELETE FROM `{table}` WHERE CompCode = :cc AND DocEntry = :de"),
                   {"cc": COMP_CODE, "de": doc_entry})
        is_update = True
    else:
        # ponytail: MAX+1 under this transaction's lock; a sequence table if saves ever collide.
        doc_entry = int(db.execute(text(f"SELECT COALESCE(MAX(DocEntry), 0) + 1 FROM `{table}` "
                                        "WHERE CompCode = :cc FOR UPDATE"), {"cc": COMP_CODE}).scalar())
        created, is_update = None, False

    if doc:
        depts = _lookup(db, "SELECT dept_code, MIN(dept_desc) FROM dept_mst WHERE dept_code IN :codes "
                            "GROUP BY dept_code", {dept})
        ocps = _lookup(db, "SELECT OCPCode, MIN(OCPName) FROM ODPT WHERE DeptCode = :dept AND OCPCode IN :codes "
                           "GROUP BY OCPCode", {ln["OcpCode"] for ln in lines if ln["OcpCode"]}, {"dept": dept})
        quals = _lookup(db, "SELECT QCode, MIN(QName) FROM PayOQLT WHERE DeptCode = :dept AND QCode IN :codes "
                            "GROUP BY QCode", {ln["QCode"] for ln in lines if ln["QCode"]}, {"dept": dept})
        names = _lookup(db, """SELECT o.emp_code, TRIM(CONCAT(IFNULL(p.first_name,''),' ',IFNULL(p.last_name,'')))
                               FROM hrms_ed_official_details o JOIN hrms_ed_personal_details p ON p.eb_id = o.eb_id
                               WHERE o.emp_code IN :codes""", {ln["ECode"] for ln in lines})

    for i, ln in enumerate(lines, start=1):
        row = {
            "CompCode": COMP_CODE, "Location": LOCATION, "UnitCode": UNIT_CODE,
            "DocEntry": doc_entry, "LineID": i, "DeptCode": dept,
            "SecCode": ln["SecCode"], "OcpCode": ln["OcpCode"], "MchType": mch_type or ln["MchType"],
            "Mch1Code": ln["Mch1Code"], "Mch2Code": ln["Mch2Code"], "ECode": ln["ECode"],
            "QCode": ln["QCode"], "CalcRate": ln["CalcRate"], "Amount": ln["Amount"],
            "PayableAmt": ln["PayableAmt"], "PCName": PC_NAME, "UserID": user,
        }
        if doc:
            row |= {"Series": "", "DocNum": doc_entry, "DocDate": wdate, "WShift": shift,
                    "DeptName": depts.get(dept, ""), "OcpName": ocps.get(ln["OcpCode"], ""),
                    "EName": names.get(ln["ECode"], ""), "QName": quals.get(ln["QCode"], ""),
                    "Qty": ln["Prod1"], "Rate": ln["QRate"], "OTAmount": 0}
        else:
            row |= {"FrmName": form["frm"], "ObjectCode": form["obj"], "WDate": wdate, "Shift": shift,
                    "Spell": spell, "OrgECode": ln["ECode"], "Prod1": ln["Prod1"], "Prod2": ln["Prod2"],
                    "Prod_HR": ln["Prod_HR"], "Mch_HR": ln["Mch_HR"], "QRate": ln["QRate"],
                    "Remarks": ln["Remarks"]}
        row |= {"CreatedDate": created or datetime.now(),
                "UpdatedDate": datetime.now() if is_update else LEGACY_BLANK_DATE}
        keys = [k for k in row if k in cols]
        db.execute(text(f"INSERT INTO `{table}` ({', '.join(keys)}) VALUES ({', '.join(':' + k for k in keys)})"),
                   {k: row[k] for k in keys})
    db.commit()
    return {"doc_entry": doc_entry, "message": f"Document {doc_entry} saved ({len(lines)} lines)"}


@router.delete("/doc/{kind}/{doc_entry}")
def prod_delete(kind: str, doc_entry: int, db: Session = Depends(get_tenant_db),
                token_data: dict = Depends(get_current_user_with_refresh)):
    form = _form(kind)
    n = db.execute(text(f"DELETE FROM `{form['table']}` WHERE CompCode = :cc AND DocEntry = :de"),
                   {"cc": COMP_CODE, "de": doc_entry}).rowcount
    if not n:
        raise HTTPException(status_code=404, detail="Document not found")
    db.commit()
    return {"message": f"Document {doc_entry} deleted"}
