"""
Pay adjustments — Other Menus -> Adjustment Hour / Adjustment PF / Adjustment NPF.

Ports legacy Smart Eye FrmMAdjHour / FrmMAdjPF / FrmMAdjNPF onto the mirrored
tables PayM_AdjHR / PayM_AdjPF / PayM_AdjNPF, which the wages process
(wagesSalaryProcess.py) already reads by FNEDate.

As in legacy, an entry is a document keyed by (branch, FNEDate, DeptCode,
WShift) holding employee lines; saving deletes the document and re-inserts
its lines. FNEDate is the selected pay period's TO_DATE, and a period
earlier than the branch's latest FNEDate is refused (legacy "You can't make
Earlier Day Entry").

Adjustment Hour: the user keys hours; Adj_Day = hours / shift hours,
Adj_BSAmt = hours x FBasic / FBasic_HR (PayOWagesRate) and Adj_DAAmt =
hours x DA_Amt / DA_HR (PayODARate, only when DA_All = 'Y'), both at the
latest EffDate on or before FNEDate — always computed here, never trusted
from the client. PF / NPF: the user keys hours (optional) and an amount.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import bindparam
from sqlalchemy.orm import Session
from sqlalchemy.sql import text

from src.authorization.utils import get_current_user_with_refresh
from src.common.utils import parse_json_body
from src.config.db import get_tenant_db
from src.hrms.canteenDetails import get_canteen_employees_query

router = APIRouter()

# Pay periods of the company/branch, any status (nbjcl's migrated periods all carry status 4).
PERIODS_SQL = text("""
    SELECT pp.ID AS id, pp.TO_DATE AS to_date,
           CONCAT(IFNULL(CONCAT(pp.code, ': '), ''), DATE_FORMAT(pp.FROM_DATE, '%d-%m-%Y'), ' to ',
                  DATE_FORMAT(pp.TO_DATE, '%d-%m-%Y')) AS label
    FROM pay_period pp
    WHERE pp.COMPANY_ID = :co_id
      AND (:branch_id IS NULL OR pp.branch_id IS NULL OR pp.branch_id = :branch_id)
      AND pp.TO_DATE IS NOT NULL
    ORDER BY pp.TO_DATE DESC, pp.ID DESC
""")

TABLES = {"hour": "PayM_AdjHR", "pf": "PayM_AdjPF", "npf": "PayM_AdjNPF"}
DOC_KEY = "branch_id = :b AND FNEDate = :fne AND DeptCode = :dept AND WShift = :shift"


def _table(kind: str) -> str:
    if kind not in TABLES:
        raise HTTPException(status_code=404, detail=f"Unknown adjustment kind '{kind}'")
    return TABLES[kind]


def _int_param(request: Request, name: str, required: bool = True) -> int | None:
    raw = request.query_params.get(name)
    if raw in (None, "", "null"):
        if required:
            raise HTTPException(status_code=400, detail=f"{name} is required")
        return None
    try:
        return int(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"{name} must be an integer")


def _doc_params(request: Request) -> dict:
    p = {
        "b": _int_param(request, "branch_id"),
        "fne": request.query_params.get("fne_date"),
        "dept": request.query_params.get("dept_code"),
        "shift": request.query_params.get("wshift"),
    }
    if not (p["fne"] and p["dept"] and p["shift"]):
        raise HTTPException(status_code=400, detail="fne_date, dept_code and wshift are required")
    return p


def _num(v, name: str, line: int, lo: float, hi: float) -> float:
    try:
        n = round(float(v or 0), 2)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"Line {line}: {name} must be a number")
    if n < lo or n > hi:
        raise HTTPException(status_code=400, detail=f"Line {line}: {name} must be between {lo:g} and {hi:g}")
    return n


# Per-hour basic / DA at a cut-off date (legacy FrmMAdjHour.GetRate).
RATES_SQL = text("""
    SELECT w.eb_id,
           IF(w.FBasic_HR > 0, w.FBasic / w.FBasic_HR, 0) bs_hr,
           IF(w.DA_All = 'Y' AND d.DA_HR > 0, d.DA_Amt / d.DA_HR, 0) da_hr
    FROM PayOWagesRate w
    JOIN (SELECT eb_id, MAX(EffDate) me FROM PayOWagesRate
          WHERE EffDate <= :fne AND eb_id IN :ids GROUP BY eb_id) m
      ON m.eb_id = w.eb_id AND m.me = w.EffDate
    LEFT JOIN (
        SELECT d.eb_id, MAX(d.DA_Amt) DA_Amt, MAX(d.DA_HR) DA_HR FROM PayODARate d
        JOIN (SELECT eb_id, MAX(EffDate) me FROM PayODARate
              WHERE EffDate <= :fne AND eb_id IN :ids GROUP BY eb_id) m
          ON m.eb_id = d.eb_id AND m.me = d.EffDate
        GROUP BY d.eb_id) d ON d.eb_id = w.eb_id
""").bindparams(bindparam("ids", expanding=True))

EMPLOYEES_SQL = text("""
    SELECT p.eb_id, o.emp_code,
           CONCAT_WS(' ', NULLIF(TRIM(p.first_name), ''), NULLIF(TRIM(p.middle_name), ''),
                     NULLIF(TRIM(p.last_name), '')) ename
    FROM hrms_ed_personal_details p
    LEFT JOIN hrms_ed_official_details o ON o.eb_id = p.eb_id AND o.active = 1
    WHERE p.eb_id IN :ids AND p.branch_id = :b
""").bindparams(bindparam("ids", expanding=True))


# ─── Endpoints ────────────────────────────────────────────────────────────


@router.get("/pay_adj_setup")
def pay_adj_setup(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Employees, pay periods, departments and shifts of the selected company/branch."""
    try:
        scope = {"co_id": _int_param(request, "co_id"), "branch_id": _int_param(request, "branch_id", False)}
        employees = db.execute(get_canteen_employees_query(), scope).fetchall()
        periods = db.execute(PERIODS_SQL, scope).fetchall()
        depts = db.execute(text("""
            SELECT d.dept_code, MAX(d.dept_desc) dept_desc FROM dept_mst d
            JOIN branch_mst bm ON bm.branch_id = d.branch_id
            WHERE bm.co_id = :co_id AND (:branch_id IS NULL OR d.branch_id = :branch_id)
              AND IFNULL(d.dept_code, '') <> ''
            GROUP BY d.dept_code ORDER BY d.dept_code
        """), scope).fetchall()
        # WShift is varchar(2) in the legacy tables
        shifts = db.execute(text("""
            SELECT spell_code, MAX(working_hours) hrs FROM spell_mst
            WHERE IFNULL(status, 1) = 1 AND CHAR_LENGTH(spell_code) <= 2
            GROUP BY spell_code ORDER BY spell_code
        """)).fetchall()
        return {
            "data": {
                "employees": [
                    {"value": str(r.eb_id), "label": f"{r.emp_code or r.eb_id} - {(r.full_name or '').strip()}"}
                    for r in employees
                ],
                "periods": [
                    {"value": str(r.id), "label": r.label,
                     "to_date": r.to_date.isoformat() if r.to_date else None}
                    for r in periods
                ],
                "depts": [{"value": r.dept_code, "label": f"{r.dept_code} - {r.dept_desc or ''}"} for r in depts],
                "shifts": [{"value": r.spell_code, "label": f"{r.spell_code} ({float(r.hrs or 0):g} hrs)",
                            "hours": float(r.hrs or 0)} for r in shifts],
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/pay_adj_rates")
def pay_adj_rates(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Per-hour basic / DA of employees (?eb_ids=1,2,3) at a pay period's TO_DATE —
    for the live Adjustment Hour grid preview; save recomputes them."""
    try:
        period_id = _int_param(request, "period_id")
        try:
            ids = [int(x) for x in (request.query_params.get("eb_ids") or "").split(",") if x.strip()]
        except ValueError:
            raise HTTPException(status_code=400, detail="eb_ids must be integers")
        fne = db.execute(text("SELECT TO_DATE FROM pay_period WHERE ID = :id"), {"id": period_id}).scalar()
        if fne is None:
            raise HTTPException(status_code=400, detail="Pay period not found or has no to-date")
        rows = db.execute(RATES_SQL, {"ids": ids, "fne": fne}).fetchall() if ids else []
        return {"data": {str(r.eb_id): {"bs_hr": float(r.bs_hr), "da_hr": float(r.da_hr)} for r in rows}}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/pay_adj_list/{kind}")
def pay_adj_list(
    kind: str,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Documents (FNEDate + dept + shift) of the branch, newest first."""
    try:
        tbl = _table(kind)
        amount = "SUM(Adj_BSAmt + Adj_DAAmt)" if kind == "hour" else "SUM(Adj_Amt)"
        search = request.query_params.get("search")
        page = int(request.query_params.get("page", 1))
        limit = int(request.query_params.get("limit", 10))
        rows = db.execute(text(f"""
            SELECT FNEDate fne_date, DeptCode dept_code, MAX(DeptName) dept_name, WShift wshift,
                   COUNT(*) line_count, SUM(Adj_HR) adj_hr, {amount} adj_amt
            FROM {tbl}
            WHERE branch_id = :b
              AND (:search IS NULL OR DeptCode LIKE :search OR DeptName LIKE :search
                   OR DATE_FORMAT(FNEDate, '%d-%m-%Y') LIKE :search)
            GROUP BY FNEDate, DeptCode, WShift
            ORDER BY FNEDate DESC, DeptCode, WShift
        """), {"b": _int_param(request, "branch_id"), "search": f"%{search}%" if search else None}).fetchall()
        data = [
            {**dict(r._mapping), "id": f"{r.fne_date}|{r.dept_code}|{r.wshift}",
             "adj_hr": float(r.adj_hr or 0), "adj_amt": float(r.adj_amt or 0)}
            for r in rows
        ]
        # ponytail: in-memory pagination like the sibling pages; SQL LIMIT if it grows
        start = (page - 1) * limit
        return {"data": data[start:start + limit], "total": len(data), "page": page, "limit": limit}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/pay_adj_doc/{kind}")
def pay_adj_doc(
    kind: str,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Lines of one document, plus the pay period whose TO_DATE is its FNEDate."""
    try:
        tbl = _table(kind)
        p = _doc_params(request)
        extra = "Adj_Day adj_day, Adj_BSAmt adj_bs, Adj_DAAmt adj_da" if kind == "hour" else "Adj_Amt adj_amt"
        rows = db.execute(text(f"""
            SELECT eb_id, EName ename, Adj_HR adj_hr, {extra}
            FROM {tbl} WHERE {DOC_KEY} ORDER BY LineID
        """), p).fetchall()
        period_id = db.execute(text("""
            SELECT ID FROM pay_period WHERE TO_DATE = :fne AND (branch_id IS NULL OR branch_id = :b)
            ORDER BY branch_id IS NULL, code NOT LIKE 'P%', ID DESC LIMIT 1
        """), p).scalar()
        return {
            "period_id": period_id,
            "data": [
                {k: (float(v) if k.startswith("adj_") and v is not None else v) for k, v in r._mapping.items()}
                for r in rows
            ],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/pay_adj_save/{kind}")
def pay_adj_save(
    kind: str,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Replace one document. Body: {branch_id, period_id, dept_code, wshift,
    orig?: {fne_date, dept_code, wshift} (the document being edited),
    lines: [{eb_id, adj_hr, adj_amt?}]}."""
    try:
        tbl = _table(kind)
        body = parse_json_body(request)
        try:
            b, period_id = int(body.get("branch_id")), int(body.get("period_id"))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="branch_id and period_id are required")
        dept, shift = str(body.get("dept_code") or "").strip(), str(body.get("wshift") or "").strip()
        if not dept:
            raise HTTPException(status_code=400, detail="Department can't be blank")
        if not shift:
            raise HTTPException(status_code=400, detail="Shift can't be blank")
        lines = body.get("lines") or []
        if not lines:
            raise HTTPException(status_code=400, detail="Kindly enter at least one employee line")

        fne = db.execute(text("SELECT TO_DATE FROM pay_period WHERE ID = :id"), {"id": period_id}).scalar()
        if fne is None:
            raise HTTPException(status_code=400, detail="Pay period not found or has no to-date")
        dept_name = db.execute(text(
            "SELECT dept_desc FROM dept_mst WHERE branch_id = :b AND dept_code = :d LIMIT 1"
        ), {"b": b, "d": dept}).scalar()
        if dept_name is None:
            raise HTTPException(status_code=400, detail=f"Department {dept} not found in this branch")
        shift_hr = float(db.execute(text(
            "SELECT MAX(working_hours) FROM spell_mst WHERE spell_code = :s"
        ), {"s": shift}).scalar() or 0)
        if kind == "hour" and shift_hr <= 0:
            raise HTTPException(status_code=400, detail=f"Shift {shift} has no working hours")

        last = db.execute(text(f"SELECT MAX(FNEDate) FROM {tbl} WHERE branch_id = :b"), {"b": b}).scalar()
        if last and last > fne:
            raise HTTPException(
                status_code=400,
                detail=f"Previous FNE date is {last:%d/%m/%Y} — you can't make an earlier entry",
            )

        eb_ids = []
        for i, ln in enumerate(lines, 1):
            try:
                eb_ids.append(int(ln.get("eb_id")))
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail=f"Line {i}: select an employee")
        if len(set(eb_ids)) != len(eb_ids):
            raise HTTPException(status_code=400, detail="An employee appears on more than one line")
        emps = {r.eb_id: r for r in db.execute(EMPLOYEES_SQL, {"ids": eb_ids, "b": b})}
        rates = {r.eb_id: r for r in db.execute(RATES_SQL, {"ids": eb_ids, "fne": fne})} if kind == "hour" else {}

        # legacy CompCode / Location of the branch (unused by the wages process)
        cl = db.execute(text(f"""
            SELECT CompCode, Location FROM {tbl} WHERE branch_id = :b ORDER BY FNEDate DESC LIMIT 1
        """), {"b": b}).fetchone()
        comp, loc = (cl.CompCode, cl.Location) if cl else ("", "")
        user_id = token_data.get("user_id") if token_data else None

        rows = []
        for i, (ln, eb) in enumerate(zip(lines, eb_ids), 1):
            emp = emps.get(eb)
            if emp is None:
                raise HTTPException(status_code=400, detail=f"Line {i}: employee not found in this branch")
            hr = _num(ln.get("adj_hr"), "Adj HR", i, -999, 999)
            row = {
                "eb_id": eb, "branch_id": b, "comp": comp, "loc": loc, "fne": fne, "dept": dept,
                "dept_name": dept_name or "", "shift": shift, "line": i, "ename": emp.ename or "",
                "hr": hr, "pc": "VOWERP", "user": user_id,
            }
            if kind == "hour":
                if hr == 0:
                    raise HTTPException(status_code=400, detail=f"Line {i}: kindly enter Adj. Hour")
                r = rates.get(eb)
                if r is None:
                    raise HTTPException(status_code=400, detail=f"Line {i}: {emp.emp_code} has no wages rate on or before {fne:%d/%m/%Y}")
                row.update(period_id=period_id, shift_hr=shift_hr, day=round(hr / shift_hr, 3),
                           bs=round(hr * float(r.bs_hr), 2), da=round(hr * float(r.da_hr), 2))
            else:
                amt = _num(ln.get("adj_amt"), "Adj Amt", i, -9_999_999, 9_999_999)
                if amt == 0:
                    raise HTTPException(status_code=400, detail=f"Line {i}: kindly enter Adj. Amt.")
                row.update(ecode=emp.emp_code or "", amt=amt, user=str(user_id or ""))
            rows.append(row)

        orig = body.get("orig") or {}
        keys = [{"b": b, "fne": fne, "dept": dept, "shift": shift}]
        if orig.get("fne_date"):
            keys.append({"b": b, "fne": orig["fne_date"], "dept": orig.get("dept_code"), "shift": orig.get("wshift")})
        for k in keys:
            db.execute(text(f"DELETE FROM {tbl} WHERE {DOC_KEY}"), k)
        if kind == "hour":
            db.execute(text("""
                INSERT INTO PayM_AdjHR (eb_id, branch_id, period_id, CompCode, Location, FNEDate, DeptCode,
                    DeptName, WShift, ShiftHR, LineID, EName, Adj_HR, Adj_Day, Adj_BSAmt, Adj_DAAmt, EffDate,
                    CreateDate, UpdatedDate, PCName, UserID)
                VALUES (:eb_id, :branch_id, :period_id, :comp, :loc, :fne, :dept, :dept_name, :shift, :shift_hr,
                    :line, :ename, :hr, :day, :bs, :da, '1900-01-01', NOW(), '1900-01-01', :pc, :user)
            """), rows)
        else:
            db.execute(text(f"""
                INSERT INTO {tbl} (eb_id, branch_id, CompCode, Location, UnitCode, FNEDate, DeptCode, DeptName,
                    WShift, LineID, ECode, EName, Adj_HR, Adj_Amt, EffDate, CreateDate, UpdatedDate, PCName, UserID)
                VALUES (:eb_id, :branch_id, :comp, :loc, '01', :fne, :dept, :dept_name, :shift, :line, :ecode,
                    :ename, :hr, :amt, '1900-01-01', NOW(), '1900-01-01', :pc, :user)
            """), rows)
        db.commit()
        return {"message": f"Saved {len(rows)} line(s)", "fne_date": fne.isoformat()}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/pay_adj_delete/{kind}")
def pay_adj_delete(
    kind: str,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Delete one whole document."""
    try:
        tbl = _table(kind)
        n = db.execute(text(f"DELETE FROM {tbl} WHERE {DOC_KEY}"), _doc_params(request)).rowcount
        if not n:
            raise HTTPException(status_code=404, detail="Adjustment document not found")
        db.commit()
        return {"message": f"Deleted {n} line(s)"}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
