"""
Loan Transactions — port of the legacy Smart-Eye (Northbrook) "Loan Transactions" menu.

    Loan / Advance Entry   FrmLoanAdvance_NJB     -> payoloan (+ payloan1 instalments)
    Loan Stop/ Change Bulk FrmLoanStopChangeBulk  -> payloanchange
    Loan Stop For ALL      FrmLoanStopALL         -> payloanstopall
    Loan Repayment         FrmLoanAdjustment      -> payloanadjust

The tables are the migrated legacy ones (no PK, keyed by CompCode/Location +
DocEntry, employees by legacy ECode = hrms_ed_official_details.emp_code) because
the wages process reads them in the legacy shape. Legacy PaySalaryPeriod is
pay_period (code/name/FROM_DATE/TO_DATE), legacy PayOEMP is the HRMS employee
tables, and an employee's Grade (MILL-WORKMEN / STAFF) is the latest paywages row.

ponytail: DocEntry/SLNO are MAX()+1 inside the save transaction, like the
legacy forms — fine for a handful of payroll clerks; add a sequence table if
concurrent saves ever collide. Period locking is not ported (pay_period has no
Locked flag).
"""

import calendar
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy.sql import text

from src.authorization.utils import get_current_user_with_refresh
from src.common.utils import parse_json_body
from src.config.db import get_tenant_db

router = APIRouter()

FRM_ENTRY = "FrmLoanAdvance_NJB"
FRM_BULK = "FrmLoanStopChangeBulk"
FRM_REPAY = "FrmLoanAdjustment"
PC_NAME = "VOWERP"
# Legacy PF-loan cut-over date used by GetLoanEMI.
PF_CUTOFF = date(2022, 3, 31)

# ponytail: branch -> legacy (CompCode, Location). One mapped branch today;
# add a column on branch_mst if more tenants get the legacy loan tables.
LEGACY_SCOPE = {87: ("NJB", "FACTORY")}

# hrms_* tables are utf8mb4_0900_ai_ci, the legacy tables utf8mb4_unicode_ci.
UCI = "COLLATE utf8mb4_unicode_ci"


# ─── Helpers ──────────────────────────────────────────────────────────────


def _scope(branch_id) -> tuple[str, str]:
    try:
        scope = LEGACY_SCOPE.get(int(branch_id))
    except (TypeError, ValueError):
        scope = None
    if not scope:
        raise HTTPException(status_code=400, detail="Select a branch that has legacy loan data (MILL)")
    return scope


def _qp_scope(request: Request) -> tuple[str, str]:
    return _scope(request.query_params.get("branch_id"))


def _user(token_data: dict | None) -> str:
    return str((token_data or {}).get("user_id") or "")[:30]


def _date(v, name: str) -> date:
    try:
        return date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"{name} must be a date (YYYY-MM-DD)")


def _num(v, name: str, minimum: float = 0) -> float:
    if v in (None, ""):
        return 0.0
    try:
        n = round(float(v), 2)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"{name} must be a number")
    if n < minimum:
        raise HTTPException(status_code=400, detail=f"{name} must be >= {minimum}")
    return n


def _rows(result) -> list[dict]:
    out = []
    for r in result.fetchall():
        m = dict(r._mapping)
        for k, v in m.items():
            if isinstance(v, (date, datetime)):
                m[k] = v.isoformat()[:10] if isinstance(v, date) and not isinstance(v, datetime) else v.isoformat()
            elif v is not None and type(v).__name__ == "Decimal":
                m[k] = float(v)
            elif isinstance(v, str):
                m[k] = v.strip()
        out.append(m)
    return out


def _period(db: Session, period_id) -> dict:
    row = db.execute(
        text("SELECT ID, code, name, FROM_DATE, TO_DATE FROM pay_period WHERE ID = :id"),
        {"id": period_id},
    ).fetchone()
    if not row or not row.TO_DATE:
        raise HTTPException(status_code=400, detail="Pay period not found")
    return {"id": row.ID, "code": row.code or "", "name": row.name or "",
            "from_date": row.FROM_DATE, "to_date": row.TO_DATE}


def _fy_start(d: date) -> date:
    return date(d.year if d.month >= 4 else d.year - 1, 4, 1)


def _last_day(y: int, m: int) -> date:
    return date(y, m, calendar.monthrange(y, m)[1])


def loan_balance(db: Session, comp: str, loc: str, ecode: str, to_date: date) -> dict:
    """Single-employee port of the legacy GetLoanEMI BalLoan/BalInt (PF loan only).

    Not renewed this FY: all open PFLOAN capital + PFINT interest, less
    repayments (payloanadjust) and wage deductions since the cut-over.
    Renewed this FY: the latest PFLOAN amount less wage deductions since it.
    ponytail: PaySalary (staff salary) deductions are not subtracted — that
    table is not in the tenant DB.
    """
    p = {"c": comp, "l": loc, "e": ecode, "d": to_date, "fy": _fy_start(to_date), "cut": PF_CUTOFF}
    base = "CompCode = :c AND Location = :l AND ECode = :e"
    last_renewal = db.execute(text(f"""
        SELECT MAX(LoanDate) FROM payoloan
        WHERE {base} AND DocStatus = 'OPEN' AND LoanType = 'PFLOAN'
          AND LoanDate BETWEEN :fy AND :d
    """), p).scalar()

    if last_renewal:
        p["ld"] = last_renewal
        cap = db.execute(text(f"""
            SELECT IFNULL(SUM(LoanAmt), 0) FROM payoloan
            WHERE {base} AND DocStatus = 'OPEN' AND LoanType = 'PFLOAN'
              AND EMIDate <= :d AND LoanDate = :ld
        """), p).scalar()
        paid = db.execute(text(f"""
            SELECT IFNULL(SUM(PFLoanCap + PFLoanInt), 0) FROM paywages
            WHERE {base} AND EDate > :cut AND EDate < :d AND EDate >= :ld
        """), p).scalar()
        return {"bal_loan": float(cap) - float(paid), "bal_int": 0.0}

    sums = db.execute(text(f"""
        SELECT
          IFNULL(SUM(CASE WHEN LoanType = 'PFLOAN' THEN LoanAmt END), 0) AS cap,
          IFNULL(SUM(CASE WHEN LoanType = 'PFINT' THEN InterestAmt END), 0) AS intr
        FROM payoloan
        WHERE {base} AND DocStatus = 'OPEN' AND EMIDate <= :d
    """), p).fetchone()
    repaid = db.execute(text(f"""
        SELECT IFNULL(SUM(RepayCapital + RepayInterest), 0) FROM payloanadjust
        WHERE {base} AND ToDate <= :d AND LoanType IN ('PFLOAN', 'PFINT')
    """), p).scalar()
    paid = db.execute(text(f"""
        SELECT IFNULL(SUM(PFLoanCap + PFLoanInt), 0) FROM paywages
        WHERE {base} AND EDate > :cut AND EDate < :d
    """), p).scalar()
    bal_loan = float(sums.cap) + float(sums.intr) - float(repaid) - float(paid)
    return {"bal_loan": bal_loan, "bal_int": float(sums.intr)}


def _employee(db: Session, branch_id: int, code: str) -> dict | None:
    row = db.execute(text(f"""
        SELECT o.emp_code AS ecode,
               TRIM(CONCAT(IFNULL(p.first_name, ''), ' ', IFNULL(p.middle_name, ''), ' ',
                           IFNULL(p.last_name, ''))) AS ename,
               IFNULL(d.dept_code, '') AS dept_code, IFNULL(d.dept_desc, '') AS dept_name,
               IFNULL(b.bank_name, '') AS bank_name, IFNULL(b.ifsc_code, '') AS ifsc_code,
               IFNULL(b.bank_acc_no, '') AS bank_acc_no
        FROM hrms_ed_official_details o
        LEFT JOIN hrms_ed_personal_details p ON p.eb_id = o.eb_id
        LEFT JOIN sub_dept_mst s ON s.sub_dept_id = o.sub_dept_id
        LEFT JOIN dept_mst d ON d.dept_id = s.dept_id
        LEFT JOIN hrms_ed_bank_details b ON b.eb_id = o.eb_id AND b.active = 1
        WHERE o.active = 1 AND o.branch_id = :b AND o.emp_code = :code
        LIMIT 1
    """), {"b": branch_id, "code": code}).fetchone()
    if not row:
        return None
    emp = dict(row._mapping)
    emp["grade"] = db.execute(text(f"""
        SELECT Grade FROM paywages WHERE ECode = :code {UCI} ORDER BY EDate DESC LIMIT 1
    """), {"code": code}).scalar() or ""
    return emp


# ─── Shared setup ─────────────────────────────────────────────────────────


@router.get("/loan_setup")
def loan_setup(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Loan types, grades and pay periods for the selected branch."""
    comp, loc = _qp_scope(request)
    branch_id = int(request.query_params["branch_id"])
    types = db.execute(text("""
        SELECT LoanName AS loan_name, LoanType AS loan_type, InterestRate AS interest_rate
        FROM payloantype
        WHERE CompCode = :c AND Location = :l AND Active = 'Y' AND SlNo > 0
        ORDER BY SlNo
    """), {"c": comp, "l": loc})
    grades = db.execute(text("""
        SELECT DISTINCT Grade FROM paywages WHERE CompCode = :c AND Location = :l AND Grade <> ''
        ORDER BY Grade
    """), {"c": comp, "l": loc}).scalars().all()
    periods = db.execute(text("""
        SELECT ID AS id, code, name, FROM_DATE AS from_date, TO_DATE AS to_date
        FROM pay_period
        WHERE branch_id = :b AND IFNULL(STATUS, 0) NOT IN (4, 6) AND code IS NOT NULL
        ORDER BY FROM_DATE DESC, ID DESC
    """), {"b": branch_id})
    return {"data": {"loan_types": _rows(types), "grades": list(grades), "periods": _rows(periods)}}


@router.get("/loan_employee")
def loan_employee(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Employee details by EB no, plus PF-loan balance as of `as_of`."""
    comp, loc = _qp_scope(request)
    code = (request.query_params.get("code") or "").strip()
    if not code:
        raise HTTPException(status_code=400, detail="code is required")
    emp = _employee(db, int(request.query_params["branch_id"]), code)
    if not emp:
        raise HTTPException(status_code=404, detail=f"Employee {code} not found in this branch")
    as_of = request.query_params.get("as_of")
    emp.update(loan_balance(db, comp, loc, code, _date(as_of, "as_of")) if as_of
               else {"bal_loan": 0.0, "bal_int": 0.0})
    return {"data": emp}


# ─── Loan / Advance Entry (payoloan) ──────────────────────────────────────


@router.get("/loan_entry_list")
def loan_entry_list(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    comp, loc = _qp_scope(request)
    search = request.query_params.get("search")
    page = int(request.query_params.get("page", 1))
    limit = int(request.query_params.get("limit", 10))
    params = {"c": comp, "l": loc, "f": FRM_ENTRY, "s": f"%{search}%" if search else None}
    where = """CompCode = :c AND Location = :l AND FrmName = :f
               AND (:s IS NULL OR DocType LIKE :s OR ECode LIKE :s OR EName LIKE :s
                    OR CAST(DocEntry AS CHAR) LIKE :s)"""
    total = db.execute(text(f"SELECT COUNT(DISTINCT DocEntry) FROM payoloan WHERE {where}"), params).scalar()
    rows = db.execute(text(f"""
        SELECT DocEntry AS doc_entry, MAX(LoanDate) AS loan_date, MAX(EMIDate) AS emi_date,
               MAX(DocType) AS doc_type, MAX(Grade) AS grade, MAX(DocStatus) AS doc_status,
               COUNT(*) AS line_count, SUM(LoanSanction) AS total_sanction,
               MIN(CASE WHEN DocLineID = 1 THEN CONCAT(ECode, ' - ', EName) END) AS first_employee
        FROM payoloan WHERE {where}
        GROUP BY DocEntry
        ORDER BY MAX(LoanDate) DESC, DocEntry DESC
        LIMIT :lim OFFSET :off
    """), {**params, "lim": limit, "off": (page - 1) * limit})
    return {"data": _rows(rows), "total": total, "page": page, "limit": limit}


@router.get("/loan_entry/{doc_entry}")
def loan_entry_get(
    doc_entry: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    comp, loc = _qp_scope(request)
    rows = _rows(db.execute(text("""
        SELECT * FROM payoloan
        WHERE CompCode = :c AND Location = :l AND FrmName = :f AND DocEntry = :d
        ORDER BY DocLineID
    """), {"c": comp, "l": loc, "f": FRM_ENTRY, "d": doc_entry}))
    if not rows:
        raise HTTPException(status_code=404, detail="Loan document not found")
    return {"data": rows}


@router.post("/loan_entry_save")
def loan_entry_save(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Create (no doc_entry) or replace (doc_entry) a loan document.

    Like the legacy Update, a replace deletes the document's payoloan +
    payloan1 rows (and any payloanadjust rows based on it) and re-inserts.
    Derived amounts are recomputed here: LoanAmt = Sanction, no interest
    (the NJB form never computed interest), FinalCapital = Sanction except
    for Advance.
    """
    body = parse_json_body(request)
    branch_id = body.get("branch_id")
    comp, loc = _scope(branch_id)
    doc_type = str(body.get("doc_type") or "").strip()
    grade = str(body.get("grade") or "").strip()
    if not doc_type:
        raise HTTPException(status_code=400, detail="Please select Doc Type")
    if not grade:
        raise HTTPException(status_code=400, detail="Please select Grade")
    loan_date = _date(body.get("loan_date"), "Loan Date")
    emi_date = _date(body.get("emi_date"), "EMI Date")
    if loan_date > date.today():
        raise HTTPException(status_code=400, detail="Loan Date cannot be in the future")

    ltype = db.execute(text("""
        SELECT LoanName, InterestRate FROM payloantype
        WHERE CompCode = :c AND Location = :l AND Active = 'Y' AND SlNo > 0 AND LoanName = :n
    """), {"c": comp, "l": loc, "n": doc_type}).fetchone()
    if not ltype:
        raise HTTPException(status_code=400, detail=f"Unknown Doc Type {doc_type}")
    if not db.execute(text("""
        SELECT 1 FROM pay_period WHERE branch_id = :b AND FROM_DATE <= :d AND TO_DATE >= :d LIMIT 1
    """), {"b": int(branch_id), "d": emi_date}).fetchone():
        raise HTTPException(status_code=400, detail="Period NOT Defined for the EMI Date, please contact the administrator")

    # NRLOAN is recovered outside the EMI schedule: legacy rows have 1 instalment,
    # usually no EMI, and no payloan1 schedule.
    is_nr = ltype.LoanName.upper() == "NRLOAN"
    lines, seen = [], set()
    for i, r in enumerate(body.get("lines") or []):
        ecode = str(r.get("ecode") or "").strip()
        if not ecode:
            continue
        if ecode in seen:
            raise HTTPException(status_code=400, detail=f"Emp Code {ecode} is entered twice")
        seen.add(ecode)
        emp = _employee(db, int(branch_id), ecode)
        if not emp:
            raise HTTPException(status_code=400, detail=f"Row {i + 1}: employee {ecode} not found")
        sanction = _num(r.get("sanction"), f"Row {i + 1} Sanction Amt")
        n_inst = 1 if is_nr else int(_num(r.get("no_of_inst"), f"Row {i + 1} No. Of Inst."))
        emi_cap = _num(r.get("emi_capital"), f"Row {i + 1} EMICap Amt")
        if is_nr and sanction <= 0:
            raise HTTPException(status_code=400, detail=f"Row {i + 1}: Sanction must be > 0")
        if not is_nr and (sanction <= 0 or n_inst <= 0 or emi_cap <= 0):
            raise HTTPException(status_code=400,
                                detail=f"Row {i + 1}: Sanction, No. Of Inst. and EMI must be > 0")
        lines.append({**emp, "sanction": sanction, "n_inst": n_inst, "emi_cap": emi_cap,
                      "remarks": str(r.get("remarks") or "")[:200]})
    if not lines:
        raise HTTPException(status_code=400, detail="At least 1 row should be in the grid")

    is_advance = doc_type.lower() == "advance"
    try:
        doc_entry = body.get("doc_entry")
        if doc_entry:
            doc_entry = int(doc_entry)
            p = {"c": comp, "l": loc, "f": FRM_ENTRY, "d": doc_entry}
            db.execute(text("DELETE FROM payoloan WHERE CompCode=:c AND Location=:l AND FrmName=:f AND DocEntry=:d"), p)
            db.execute(text("DELETE FROM payloan1 WHERE CompCode=:c AND Location=:l AND DocEntry=:d"), p)
            db.execute(text("DELETE FROM payloanadjust WHERE CompCode=:c AND Location=:l AND BaseFrmName=:f AND BaseDocEntry=:d"), p)
        else:
            doc_entry = int(db.execute(text("SELECT IFNULL(MAX(DocEntry), 0) + 1 FROM payoloan")).scalar())
        slno = int(db.execute(text("SELECT IFNULL(MAX(SLNO), 0) FROM payoloan")).scalar())
        inst_slno = int(db.execute(text("SELECT IFNULL(MAX(SLNO), 0) FROM payloan1")).scalar())
        now = datetime.now()
        user = _user(token_data)

        for line_id, ln in enumerate(lines, start=1):
            slno += 1
            db.execute(text("""
                INSERT INTO payoloan (CompCode, Location, FrmName, SLNO, DocEntry, Fyear, Period, LoanDate,
                    LoanType, DocType, DocMode, DocStatus, LoanCycle, DocLineID, OrgECode, ECode, EName,
                    DeptCode, DeptName, Grade, EGroup, SubGroup, InterestRate, LoanSanction, LoanAmt, NoOfInst,
                    InterestAmt, FinalCapital, FinalInterest, EMICapital, EMIInterest, EMIDate, RepayCapital,
                    RepayInterest, RebateAmt, BankName, IFSCCode, BankAccNo, Remarks, EmployeeCont,
                    EmployerCont, UserID, CreatedDate, PCName)
                VALUES (:c, :l, :f, :slno, :d, '', '', :loan_date,
                    :dt, :dt, 'APPROVED', 'OPEN', '', :line, :ecode, :ecode, :ename,
                    :dept_code, :dept_name, :grade, '', '', :rate, :sanction, :sanction, :n_inst,
                    0, :final_cap, 0, :emi_cap, 0, :emi_date, 0,
                    0, 0, :bank, :ifsc, :acc, :remarks, 0,
                    0, :user, :now, :pc)
            """), {
                "c": comp, "l": loc, "f": FRM_ENTRY, "slno": slno, "d": doc_entry, "loan_date": loan_date,
                "dt": ltype.LoanName, "line": line_id, "ecode": ln["ecode"], "ename": ln["ename"][:50],
                "dept_code": ln["dept_code"][:10], "dept_name": ln["dept_name"][:30], "grade": grade[:30],
                "rate": ltype.InterestRate, "sanction": ln["sanction"], "n_inst": ln["n_inst"],
                "final_cap": 0 if is_advance else ln["sanction"], "emi_cap": ln["emi_cap"],
                "emi_date": emi_date, "bank": ln["bank_name"][:100], "ifsc": ln["ifsc_code"][:20],
                "acc": ln["bank_acc_no"][:20], "remarks": ln["remarks"], "user": user, "now": now,
                "pc": PC_NAME,
            })
            # Instalment schedule: last day of the EMI month, then each following month-end.
            y, m = emi_date.year, emi_date.month
            for inst_no in range(1, 0 if is_nr else ln["n_inst"] + 1):
                inst_slno += 1
                db.execute(text("""
                    INSERT INTO payloan1 (CompCode, Location, SLNO, DocEntry, ECode, EName, InstNo,
                                          InstDate, InstAmt, InterestAmt)
                    VALUES (:c, :l, :slno, :d, :ecode, :ename, :no, :dt, :amt, 0)
                """), {"c": comp, "l": loc, "slno": inst_slno, "d": doc_entry, "ecode": ln["ecode"],
                       "ename": ln["ename"][:50], "no": inst_no, "dt": _last_day(y, m),
                       "amt": ln["emi_cap"]})
                y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        db.commit()
        return {"message": "Loan Data Saved", "doc_entry": doc_entry}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# ─── Loan Stop / Change Bulk (payloanchange) ──────────────────────────────


@router.get("/loan_change_fill")
def loan_change_fill(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Port of GetDataForLoanStop: open loans of a type with a capital or interest
    balance > 0 (PFINT loans carry only interest), with the current EMI (latest
    payloanchange up to the period, else the loan's)."""
    comp, loc = _qp_scope(request)
    period = _period(db, request.query_params.get("period_id"))
    loan_type = (request.query_params.get("loan_type") or "").strip()
    if not loan_type:
        raise HTTPException(status_code=400, detail="LoanType can't be blank")
    rows = db.execute(text("""
        SELECT * FROM (
          SELECT T0.OrgECode AS org_ecode, T0.ECode AS ecode, MAX(T0.EName) AS ename,
            T0.LoanType AS loan_type, MAX(T0.Grade) AS grade,
            IFNULL((SELECT EMICapital FROM payloanchange c WHERE c.LoanType = T0.LoanType
                      AND c.ECode = T0.ECode AND c.CapitalStop = 'N' AND c.ToDate <= :d
                    ORDER BY c.ToDate DESC, c.CreatedDate DESC LIMIT 1), SUM(T0.EMICapital)) AS old_emi_cap,
            IFNULL((SELECT EMIInterest FROM payloanchange c WHERE c.LoanType = T0.LoanType
                      AND c.ECode = T0.ECode AND c.InterestStop = 'N' AND c.ToDate <= :d
                    ORDER BY c.ToDate DESC, c.CreatedDate DESC LIMIT 1), SUM(T0.EMIInterest)) AS old_emi_int,
            SUM(T0.LoanAmt)
              - IFNULL((SELECT SUM(PFLoanCap) FROM paywages w WHERE w.ECode = T0.ECode AND w.EDate < :d), 0)
              - IFNULL((SELECT SUM(RepayCapital) FROM payloanadjust a WHERE a.DocType = T0.LoanType
                          AND a.ECode = T0.ECode AND a.ToDate < :d), 0) AS capital_bal,
            SUM(T0.InterestAmt)
              - IFNULL((SELECT SUM(PFLoanInt) FROM paywages w WHERE w.ECode = T0.ECode AND w.EDate < :d), 0)
              - IFNULL((SELECT SUM(RepayInterest + RebateAmt) FROM payloanadjust a WHERE a.DocType = T0.LoanType
                          AND a.ECode = T0.ECode AND a.ToDate < :d), 0) AS interest_bal
          FROM payoloan T0
          WHERE T0.CompCode = :c AND T0.Location = :l AND T0.DocStatus = 'OPEN'
            AND T0.LoanType = :lt AND (:g = '' OR T0.Grade = :g)
          GROUP BY T0.OrgECode, T0.ECode, T0.LoanType
        ) x WHERE capital_bal > 0 OR interest_bal > 0
        ORDER BY ecode
    """), {"c": comp, "l": loc, "d": period["to_date"], "lt": loan_type,
           "g": (request.query_params.get("grade") or "").strip()})
    return {"data": _rows(rows)}


@router.get("/loan_change_list")
def loan_change_list(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    comp, loc = _qp_scope(request)
    page = int(request.query_params.get("page", 1))
    limit = int(request.query_params.get("limit", 10))
    search = request.query_params.get("search")
    params = {"c": comp, "l": loc, "s": f"%{search}%" if search else None}
    where = """CompCode = :c AND Location = :l
               AND (:s IS NULL OR LoanType LIKE :s OR PCode LIKE :s OR Grade LIKE :s
                    OR CAST(DocEntry AS CHAR) LIKE :s)"""
    total = db.execute(text(f"SELECT COUNT(DISTINCT DocEntry) FROM payloanchange WHERE {where}"), params).scalar()
    rows = db.execute(text(f"""
        SELECT DocEntry AS doc_entry, MAX(PCode) AS pcode, MAX(FromDate) AS from_date, MAX(ToDate) AS to_date,
               MAX(Grade) AS grade, MAX(LoanType) AS loan_type, COUNT(*) AS line_count,
               SUM(CapitalStop = 'Y') AS cap_stops, SUM(InterestStop = 'Y') AS int_stops,
               MAX(CreatedDate) AS created_date
        FROM payloanchange WHERE {where}
        GROUP BY DocEntry
        ORDER BY MAX(ToDate) DESC, MAX(CreatedDate) DESC
        LIMIT :lim OFFSET :off
    """), {**params, "lim": limit, "off": (page - 1) * limit})
    return {"data": _rows(rows), "total": total, "page": page, "limit": limit}


@router.get("/loan_change/{doc_entry}")
def loan_change_get(
    doc_entry: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    comp, loc = _qp_scope(request)
    rows = _rows(db.execute(text("""
        SELECT * FROM payloanchange WHERE CompCode = :c AND Location = :l AND DocEntry = :d
        ORDER BY LineID
    """), {"c": comp, "l": loc, "d": doc_entry}))
    if not rows:
        raise HTTPException(status_code=404, detail="Loan change document not found")
    return {"data": rows}


@router.post("/loan_change_save")
def loan_change_save(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Save the modified rows of a bulk stop/change document (delete + insert by DocEntry).
    A zero new EMI keeps the old EMI, exactly as the legacy form saved it."""
    body = parse_json_body(request)
    comp, loc = _scope(body.get("branch_id"))
    loan_type = str(body.get("loan_type") or "").strip()
    if not loan_type:
        raise HTTPException(status_code=400, detail="Please select Loan Type")
    period = _period(db, body.get("period_id"))
    grade = str(body.get("grade") or "").strip()

    lines = []
    for r in body.get("lines") or []:
        if not r.get("ecode"):
            continue
        old_cap = _num(r.get("old_emi_cap"), "Old EMI Cap")
        old_int = _num(r.get("old_emi_int"), "Old EMI Int")
        new_cap = _num(r.get("emi_cap"), "EMI Cap")
        new_int = _num(r.get("emi_int"), "EMI Int")
        lines.append({
            "line": int(r.get("line_id") or len(lines) + 1),
            "org": str(r.get("org_ecode") or r["ecode"]), "ecode": str(r["ecode"]),
            "ename": str(r.get("ename") or "")[:50],
            "old_cap": old_cap, "old_int": old_int,
            "cap": new_cap or old_cap, "int": new_int or old_int,
            "cs": "Y" if r.get("cap_stop") else "N", "is": "Y" if r.get("int_stop") else "N",
        })
    if not lines:
        raise HTTPException(status_code=400, detail="Sorry, no record to save")

    try:
        doc_entry = body.get("doc_entry")
        p = {"c": comp, "l": loc}
        if doc_entry:
            doc_entry = int(doc_entry)
            db.execute(text("DELETE FROM payloanchange WHERE CompCode=:c AND Location=:l AND DocEntry=:d"),
                       {**p, "d": doc_entry})
        else:
            doc_entry = int(db.execute(text(
                "SELECT IFNULL(MAX(DocEntry), 0) + 1 FROM payloanchange WHERE CompCode = :c"), p).scalar())
        now = datetime.now()
        for ln in lines:
            db.execute(text("""
                INSERT INTO payloanchange (CompCode, Location, FrmName, UnitCode, DocEntry, LineID, Grade,
                    SubGroup, OrgECode, ECode, EName, LoanType, PCode, FromDate, ToDate, OldEMICapital,
                    OldEMIInterest, EMICapital, EMIInterest, CapitalStop, InterestStop, CreatedDate,
                    UpdatedDate, PCName, UserID)
                VALUES (:c, :l, :f, '01', :d, :line, :grade, '', :org, :ecode, :ename, :lt, :pcode,
                    :fd, :td, :old_cap, :old_int, :cap, :int, :cs, :is, :now, '1900-01-01', :pc, :user)
            """), {**p, **ln, "f": FRM_BULK, "d": doc_entry, "grade": grade[:50], "lt": loan_type,
                   "pcode": period["code"], "fd": period["from_date"], "td": period["to_date"],
                   "now": now, "pc": PC_NAME, "user": _user(token_data)})
        db.commit()
        return {"message": "Data Saved Successfully", "doc_entry": doc_entry}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# ─── Loan Stop For ALL (payloanstopall) ───────────────────────────────────


@router.get("/loan_stop_all_list")
def loan_stop_all_list(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    comp, loc = _qp_scope(request)
    rows = db.execute(text("""
        SELECT s.PCode AS pcode, s.EDate AS edate, s.Reason AS reason, s.UserID AS user_id,
               s.CreatedDate AS created_date,
               (SELECT pp.name FROM pay_period pp WHERE pp.code = s.PCode COLLATE utf8mb4_0900_ai_ci
                  AND pp.TO_DATE = s.EDate LIMIT 1) AS pname
        FROM payloanstopall s
        WHERE s.CompCode = :c AND s.Location = :l
        ORDER BY s.EDate DESC, s.CreatedDate DESC
    """), {"c": comp, "l": loc})
    data = _rows(rows)
    return {"data": data, "total": len(data)}


@router.post("/loan_stop_all_create")
def loan_stop_all_create(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    body = parse_json_body(request)
    comp, loc = _scope(body.get("branch_id"))
    period = _period(db, body.get("period_id"))
    reason = str(body.get("reason") or "").strip()
    if not reason:
        raise HTTPException(status_code=400, detail="Reason is required")
    p = {"c": comp, "l": loc, "pc": period["code"], "ed": period["to_date"]}
    if db.execute(text("SELECT 1 FROM payloanstopall WHERE CompCode=:c AND Location=:l AND PCode=:pc AND EDate=:ed"), p).fetchone():
        raise HTTPException(status_code=400, detail="Loans are already stopped for this period")
    try:
        db.execute(text("""
            INSERT INTO payloanstopall (CompCode, Location, PCode, EDate, Reason, CreatedDate, PCName, UserID)
            VALUES (:c, :l, :pc, :ed, :reason, :now, :pcname, :user)
        """), {**p, "reason": reason[:2000], "now": datetime.now(), "pcname": PC_NAME,
               "user": _user(token_data)[:20]})
        db.commit()
        return {"message": "Data Saved"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# ─── Loan Repayment (payloanadjust) ───────────────────────────────────────


@router.get("/loan_repay_list")
def loan_repay_list(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    comp, loc = _qp_scope(request)
    page = int(request.query_params.get("page", 1))
    limit = int(request.query_params.get("limit", 10))
    search = request.query_params.get("search")
    params = {"c": comp, "l": loc, "f": FRM_REPAY, "s": f"%{search}%" if search else None}
    where = """CompCode = :c AND Location = :l AND FrmName = :f
               AND (:s IS NULL OR ECode LIKE :s OR EName LIKE :s OR PName LIKE :s OR DocType LIKE :s)"""
    total = db.execute(text(f"SELECT COUNT(*) FROM payloanadjust WHERE {where}"), params).scalar()
    rows = db.execute(text(f"""
        SELECT DocEntry AS doc_entry, ECode AS ecode, EName AS ename, Grade AS grade, DocType AS doc_type,
               PCode AS pcode, PName AS pname, FromDate AS from_date, ToDate AS to_date,
               RepayCapital AS repay_capital, RepayInterest AS repay_interest, RebateAmt AS rebate_amt,
               Remarks AS remarks
        FROM payloanadjust WHERE {where}
        ORDER BY FNEDate DESC, DocEntry DESC
        LIMIT :lim OFFSET :off
    """), {**params, "lim": limit, "off": (page - 1) * limit})
    return {"data": _rows(rows), "total": total, "page": page, "limit": limit}


@router.post("/loan_repay_save")
def loan_repay_save(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Create (no doc_entry) or replace (doc_entry) a repayment. Like the legacy
    form it also zeroes the employee's payloan1 instalments inside the period."""
    body = parse_json_body(request)
    branch_id = body.get("branch_id")
    comp, loc = _scope(branch_id)
    doc_type = str(body.get("doc_type") or "").strip()
    ecode = str(body.get("ecode") or "").strip()
    if not doc_type:
        raise HTTPException(status_code=400, detail="Loan DocType must be selected")
    if not ecode:
        raise HTTPException(status_code=400, detail="Employee cannot be left blank")
    period = _period(db, body.get("period_id"))
    emp = _employee(db, int(branch_id), ecode)
    if not emp:
        raise HTTPException(status_code=400, detail=f"Employee {ecode} not found")
    # Negative amounts are reversals — the legacy data has them (e.g. -500 capital).
    cap = _num(body.get("repay_capital"), "Repay Capital Amt", minimum=-9_999_999)
    intr = _num(body.get("repay_interest"), "Repay Interest Amt", minimum=-9_999_999)
    rebate = _num(body.get("rebate_amt"), "Rebate Amt", minimum=-9_999_999)
    if cap == 0 and intr == 0 and rebate == 0:
        raise HTTPException(status_code=400, detail="Enter a repayment or rebate amount")
    grade = str(body.get("grade") or emp["grade"]).strip()

    try:
        doc_entry = body.get("doc_entry")
        if doc_entry:
            doc_entry = int(doc_entry)
            db.execute(text("""
                DELETE FROM payloanadjust WHERE CompCode=:c AND Location=:l AND FrmName=:f AND DocEntry=:d
            """), {"c": comp, "l": loc, "f": FRM_REPAY, "d": doc_entry})
        else:
            doc_entry = int(db.execute(text("SELECT IFNULL(MAX(DocEntry), 0) + 1 FROM payloanadjust")).scalar())
        db.execute(text("""
            INSERT INTO payloanadjust (CompCode, Location, FrmName, DocEntry, BaseFrmName, BaseDocEntry, Grade,
                OrgECode, ECode, EName, LoanType, DocType, PCode, PName, FNEDate, FromDate, ToDate,
                RepayCapital, RepayInterest, RebateAmt, Remarks, CreatedDate, UserID, PCName)
            VALUES (:c, :l, :f, :d, '', 0, :grade, :ecode, :ecode, :ename, :dt, :dt, :pcode, :pname,
                :td, :fd, :td, :cap, :intr, :rebate, :remarks, :now, :user, :pc)
        """), {"c": comp, "l": loc, "f": FRM_REPAY, "d": doc_entry, "grade": grade[:50], "ecode": ecode,
               "ename": emp["ename"][:50], "dt": doc_type[:20], "pcode": period["code"],
               "pname": period["name"][:50], "fd": period["from_date"], "td": period["to_date"],
               "cap": cap, "intr": intr, "rebate": rebate,
               "remarks": str(body.get("remarks") or "")[:500], "now": datetime.now(),
               "user": _user(token_data), "pc": PC_NAME})
        db.execute(text("""
            UPDATE payloan1 SET InstAmt = 0, InterestAmt = 0
            WHERE CompCode = :c AND Location = :l AND ECode = :ecode AND InstDate BETWEEN :fd AND :td
        """), {"c": comp, "l": loc, "ecode": ecode, "fd": period["from_date"], "td": period["to_date"]})
        db.commit()
        return {"message": "Amount Settled", "doc_entry": doc_entry}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

