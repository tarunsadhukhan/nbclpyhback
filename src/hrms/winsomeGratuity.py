"""
Winsome "Gratuity" menu — port of the legacy Smart-Eye Winsome (WIL) gratuity forms (OMNU 40000).

    page              legacy form                    tables
    tsw               FrmTSW                         PayOTSW (strike / lock-out / lock-down days per year)
    stl               FrmGratuityCalcActive_WIL      PayGratOSTL + PayGratSTL1 (+ PayGratNominee)
    calc              FrmGratuityCalc                PayGratOGratuity + PayGratGratuity1 (+ PayGratNominee)
    details           FrmGratuityDetails             PayGratOGratuity (read-only list)
    voucher           FrmPayGratVoucher              PayGrat_Voucher (payment request, one row per cheque)
    voucher approve   PayGratVoucherChequeUpdate     PayGrat_Voucher (cheque no/date, DocMode APPROVED)

Flow: TSW days -> "Gratuity STL Entry" records year-wise working days of serving staff up to a cut-off
-> "Gratuity Calculation" for a leaver starts from that STL record, appends the years up to the leaving
date and is saved as the gratuity (the STL record turns APPROVED) -> payment request -> cheque approval.

The tables are mirrored 1:1 from the legacy SQL Server (dbqueries/migrations/migrate_payowagesrate_ocp.py,
TENANT_DB=winsome), every column NOT NULL — writes fill unset columns with legacy blanks ('' / 0 /
1900-01-01). Like legacy, the year-wise eligibility and amounts are computed by the screen
(nxtfront winsomeGratuity/_components/calc.ts) and stored as sent.
"""

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy.sql import text

from src.authorization.utils import get_current_user_with_refresh
from src.config.db import get_tenant_db

router = APIRouter()

# ponytail: Winsome has one legacy company/location; every legacy row carries these.
COMP_CODE, LOCATION, UNIT_CODE = "WIL", "FACTORY", "01"
PC_NAME = "VOWERP"
BLANK_DATE = date(1900, 1, 1)  # legacy blank date
APPROVED = "APPROVED"
STL_CUTOFF = "2023-03-31"  # legacy STL form default "Last Worked Upto"
DOC_TYPES = ["GENERAL", "BADLI WITH DATE OF PERMANENT", "BADLI WITHOUT DATE OF PERMANENT"]

KINDS = {
    "stl": {"master": "PayGratOSTL", "lines": "PayGratSTL1", "frm": "FrmGratuityCalcActive_WIL"},
    "calc": {"master": "PayGratOGratuity", "lines": "PayGratGratuity1", "frm": "FrmGratuityCalc"},
}
NOMINEES = "PayGratNominee"
VOUCHER = "PayGrat_Voucher"
# Master columns the server owns; everything else in the header comes from the screen.
SYSTEM_COLS = {"CompCode", "Location", "DocEntry", "FrmName", "CreateDate", "PCName", "UserID",
               "UpdateDate", "UpdatePCName", "UpdateUserID"}
LINE_COLS = ("GYear", "WorkingDays", "StrikeDays", "TSWAllow", "LockOutDays", "LockDownDays", "LayOffDays",
             "PreviousSTL", "STLEarned", "STLAvailed", "AdjDays", "Eligible", "Settled", "FinalCount", "TotalDays",
             "Remarks", "LineStatus")
NOMINEE_COLS = ("NomineeName", "PShare", "GShare", "GAmount", "Relation", "Address")
LIST_COLS = ("DocEntry", "ECode", "EName", "Grade", "Occupation", "DoJ", "DoP", "DoL", "TEReason",
             "MaxApplicableYrs", "NoOfApplicableYrs", "WagesRate", "GratuityAmt", "FinalNetAmt", "DocStatus", "DocMode")

_TYPES: dict[tuple[str, str], dict[str, str]] = {}  # (schema, table) -> {column: data_type}


def _types(db: Session, table: str) -> dict[str, str]:
    schema = db.execute(text("SELECT DATABASE()")).scalar()
    if (schema, table) not in _TYPES:
        rows = db.execute(text("SELECT COLUMN_NAME, DATA_TYPE FROM information_schema.COLUMNS "
                               "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t"), {"t": table}).fetchall()
        if not rows:
            raise HTTPException(status_code=500, detail=f"Table {table} is missing in this tenant")
        _TYPES[(schema, table)] = {r[0]: r[1] for r in rows}
    return _TYPES[(schema, table)]


def _coerce(dtype: str, v, col: str):
    """Screen value -> legacy column value ('' / null become the legacy blank)."""
    if dtype in ("date", "datetime"):
        if v in (None, ""):
            return BLANK_DATE
        if isinstance(v, (date, datetime)):
            return v
        try:
            return date.fromisoformat(str(v)[:10])
        except ValueError:
            raise HTTPException(status_code=400, detail=f"{col}: invalid date")
    if dtype in ("decimal", "int", "bigint", "smallint", "tinyint", "double", "float"):
        if v in (None, ""):
            return 0
        try:
            return float(v)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail=f"{col} must be a number")
    return "" if v is None else str(v).strip()


def _insert(db: Session, table: str, row: dict) -> None:
    """INSERT with every NOT NULL legacy column filled: unknown keys dropped, missing ones blank."""
    types = _types(db, table)
    vals = {c: _coerce(t, row.get(c), c) for c, t in types.items()}
    cols = list(vals)
    db.execute(text(f"INSERT INTO `{table}` ({', '.join(f'`{c}`' for c in cols)}) "
                    f"VALUES ({', '.join(':' + c for c in cols)})"), vals)


def _out(row) -> dict:
    """DB row -> JSON: legacy blank dates become '', decimals plain numbers."""
    d = {}
    for k, v in row._mapping.items():
        if isinstance(v, datetime):
            v = v.date()
        if isinstance(v, date):
            v = "" if v <= BLANK_DATE else v.isoformat()
        elif v is not None and not isinstance(v, (str, int, float)):
            v = float(v)
        d[k] = v
    return d


def _kind(kind: str) -> dict:
    k = KINDS.get(kind)
    if not k:
        raise HTTPException(status_code=404, detail=f"Unknown gratuity form {kind}")
    return k


def _user(token_data: dict) -> str:
    return str(token_data.get("user_id") or "")[:10]


def _next_doc_entry(db: Session, table: str) -> int:
    # ponytail: MAX+1 under this transaction's lock, like the production port.
    return int(db.execute(text(f"SELECT COALESCE(MAX(DocEntry), 0) + 1 FROM `{table}` WHERE CompCode = :cc "
                               "FOR UPDATE"), {"cc": COMP_CODE}).scalar())


def _years(db: Session, y1: int, y2: int) -> list[dict]:
    """Legacy FillGrid: one line per calendar year y1..y2, TSW/lock-out/lock-down days from PayOTSW."""
    sums = {int(r[0]): r for r in db.execute(text(
        "SELECT TYear, SUM(TSW), SUM(LockOut), SUM(LockDown) FROM PayOTSW WHERE TYear BETWEEN :a AND :b "
        "GROUP BY TYear"), {"a": y1, "b": y2}).fetchall()}
    out = []
    for y in range(y1, y2 + 1):
        s = sums.get(y)
        out.append({"GYear": y, "StrikeDays": float(s[1] or 0) if s else 0, "TSWAllow": "Y",
                    "LockOutDays": float(s[2] or 0) if s else 0, "LockDownDays": float(s[3] or 0) if s else 0})
    return out


def _year_of(v: str) -> int:
    try:
        return date.fromisoformat(str(v)[:10]).year
    except ValueError:
        raise HTTPException(status_code=400, detail="Enter valid dates")


# ─── Setup / TSW ──────────────────────────────────────────────────────────


@router.get("/setup")
def grat_setup(db: Session = Depends(get_tenant_db), token_data: dict = Depends(get_current_user_with_refresh)):
    reasons = [r[0] for r in db.execute(text("SELECT ExitReason FROM PayGratEReason ORDER BY SLNo")).fetchall()]
    return {"data": {"exit_reasons": reasons, "doc_types": DOC_TYPES}}


@router.get("/years")
def grat_years(request: Request, db: Session = Depends(get_tenant_db),
               token_data: dict = Depends(get_current_user_with_refresh)):
    q = request.query_params
    y1, y2 = _year_of(q.get("from") or ""), _year_of(q.get("to") or "")
    if y2 < y1 or y2 - y1 > 80:
        raise HTTPException(status_code=400, detail="Date of joining must be before the leaving date")
    return {"data": _years(db, y1, y2)}


@router.get("/tsw")
def tsw_list(db: Session = Depends(get_tenant_db), token_data: dict = Depends(get_current_user_with_refresh)):
    rows = db.execute(text("SELECT * FROM PayOTSW WHERE CompCode = :cc ORDER BY TYear, FromDate"),
                      {"cc": COMP_CODE}).fetchall()
    return {"data": [_out(r) for r in rows]}


TSW_COLS = ("TYear", "TMonth", "FortNight", "FromDate", "ToDate", "TSW", "LockOut", "LockDown", "Others", "Remarks")


@router.post("/tsw")
def tsw_save(body: dict, db: Session = Depends(get_tenant_db),
             token_data: dict = Depends(get_current_user_with_refresh)):
    """Replace the un-approved TSW rows (legacy: delete + re-insert the grid). Approved rows are kept
    untouched, as legacy showed them read-only."""
    raw = body.get("rows")
    if not isinstance(raw, list) or not raw:
        raise HTTPException(status_code=400, detail="Enter at least one year")
    rows = []
    for i, r in enumerate(raw, start=1):
        if not isinstance(r, dict) or str(r.get("Approved") or "").upper() == "Y":
            continue
        row = {k: r.get(k) for k in TSW_COLS}
        try:
            y = int(row["TYear"])
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail=f"Row {i}: year is required")
        if not 1950 <= y <= 2100:
            raise HTTPException(status_code=400, detail=f"Row {i}: invalid year {y}")
        nums = [_coerce("decimal", row[k], k) for k in ("TSW", "LockOut", "LockDown", "Others")]
        if any(n < 0 for n in nums):
            raise HTTPException(status_code=400, detail=f"Row {i}: days can't be negative")
        row["Total"] = sum(nums)  # legacy Grd_CellEndEdit: TSW + LockOut + LockDown + Others
        rows.append(row)
    user = _user(token_data)
    db.execute(text("DELETE FROM PayOTSW WHERE CompCode = :cc AND UnitCode = :u AND Approved <> 'Y'"),
               {"cc": COMP_CODE, "u": UNIT_CODE})
    for row in rows:
        _insert(db, "PayOTSW", row | {"CompCode": COMP_CODE, "Location": LOCATION, "UnitCode": UNIT_CODE,
                                      "Approved": "N", "CreatedDate": datetime.now(), "PCName": PC_NAME,
                                      "UserID": user, "Transferred": "N"})
    db.commit()
    return {"message": f"Saved {len(rows)} rows"}


# ─── Payment request / approval (registered before /{kind}/... so "voucher" is not taken as a kind) ─

V_LINE_COLS = ("GPercent", "GPAmt", "Remarks", "NomineeName", "NomineeRel")


@router.get("/voucher/list")
def voucher_list(request: Request, db: Session = Depends(get_tenant_db),
                 token_data: dict = Depends(get_current_user_with_refresh)):
    """One row per payment request. pending=1 -> not yet approved."""
    q = request.query_params
    search = (q.get("search") or "").strip()
    where = "CompCode = :cc" + (" AND (ECode LIKE :s OR EName LIKE :s)" if search else "")
    if q.get("pending") == "1":
        where += " AND DocMode <> 'APPROVED'"
    rows = db.execute(text(f"""SELECT DocEntry, MIN(DocDate) AS DocDate, MIN(ECode) AS ECode, MIN(EName) AS EName,
                                      MAX(GratAmount) AS GratAmount, SUM(GPAmt) AS Total, COUNT(*) AS LineCount,
                                      MIN(DocMode) AS DocMode, MIN(MillSLNo) AS MillSLNo
                               FROM `{VOUCHER}` WHERE {where}
                               GROUP BY DocEntry ORDER BY DocEntry DESC LIMIT 500"""),
                      {"cc": COMP_CODE, "s": f"%{search}%"}).fetchall()
    return {"data": [_out(r) for r in rows]}


@router.get("/voucher/emp_search")
def voucher_emp_search(request: Request, db: Session = Depends(get_tenant_db),
                       token_data: dict = Depends(get_current_user_with_refresh)):
    """Legacy TBLF5 EmpDetails: calculated gratuities without a payment request."""
    s = f"{(request.query_params.get('q') or '').strip()}%"
    rows = db.execute(text(f"""SELECT ECode, EName, FinalNetAmt AS GAmt FROM PayGratOGratuity
                               WHERE ECode NOT IN (SELECT ECode FROM `{VOUCHER}`) AND (ECode LIKE :s OR EName LIKE :s)
                               ORDER BY ECode LIMIT 50"""), {"s": s}).fetchall()
    return {"data": [_out(r) for r in rows]}


@router.get("/voucher/doc/{doc_entry}")
def voucher_doc(doc_entry: int, db: Session = Depends(get_tenant_db),
                token_data: dict = Depends(get_current_user_with_refresh)):
    rows = [_out(r) for r in db.execute(text(f"SELECT * FROM `{VOUCHER}` WHERE CompCode = :cc AND DocEntry = :de "
                                             "ORDER BY LineID"), {"cc": COMP_CODE, "de": doc_entry}).fetchall()]
    if not rows:
        raise HTTPException(status_code=404, detail="Payment request not found")
    h = rows[0]
    header = {k: h[k] for k in ("DocEntry", "DocDate", "DocStatus", "DocMode", "ECode", "EName", "GratAmount",
                                "Nominee", "MillSLNo")}
    lines = [{k: r[k] for k in ("LineID", *V_LINE_COLS, "ChequeNo", "ChequeDate")} for r in rows]
    return {"data": {"header": header, "lines": lines}}


@router.post("/voucher/save")
def voucher_save(body: dict, db: Session = Depends(get_tenant_db),
                 token_data: dict = Depends(get_current_user_with_refresh)):
    """Create or replace a payment request (legacy: delete + insert, lines with an amount only)."""
    h = body.get("header") if isinstance(body.get("header"), dict) else {}
    ecode, ename = str(h.get("ECode") or "").strip(), str(h.get("EName") or "").strip()
    if not ecode or not ename:
        raise HTTPException(status_code=400, detail="Please select the employee")
    doc_date = _coerce("date", h.get("DocDate"), "Date")
    if doc_date == BLANK_DATE:
        raise HTTPException(status_code=400, detail="Date is required")
    lines = [ln for ln in (body.get("lines") or []) if isinstance(ln, dict)
             and _coerce("decimal", ln.get("GPAmt"), "Amt") != 0]
    if not lines:
        raise HTTPException(status_code=400, detail="Enter at least one amount")
    g_amt = _coerce("decimal", h.get("GratAmount"), "Gratuity amount")
    total = round(sum(_coerce("decimal", ln.get("GPAmt"), "Amt") for ln in lines), 2)

    raw_de = h.get("DocEntry")
    doc_entry = int(raw_de) if raw_de not in (None, "", 0, "0") else 0
    if doc_entry:
        cur = db.execute(text(f"SELECT ECode, DocMode FROM `{VOUCHER}` WHERE CompCode = :cc AND DocEntry = :de "
                              "FOR UPDATE"), {"cc": COMP_CODE, "de": doc_entry}).fetchall()
        if not cur or cur[0].ECode != ecode:
            raise HTTPException(status_code=404, detail="Payment request not found")
        if any(r.DocMode == APPROVED for r in cur):
            raise HTTPException(status_code=400, detail="Payment is already approved")
        if total != round(g_amt, 2):  # legacy btnUpdate_Click
            raise HTTPException(status_code=400, detail=f"Total {total:.2f} and gratuity amount {g_amt:.2f} differ")
        db.execute(text(f"DELETE FROM `{VOUCHER}` WHERE CompCode = :cc AND DocEntry = :de"),
                   {"cc": COMP_CODE, "de": doc_entry})
    else:
        if db.execute(text(f"SELECT 1 FROM `{VOUCHER}` WHERE ECode = :e"), {"e": ecode}).first():
            raise HTTPException(status_code=400, detail=f"Payment of {ecode} is already requested")
        doc_entry = _next_doc_entry(db, VOUCHER)

    user, now = _user(token_data), datetime.now()
    for i, ln in enumerate(lines, start=1):
        _insert(db, VOUCHER, {c: ln.get(c) for c in V_LINE_COLS} | {
            "CompCode": COMP_CODE, "Location": LOCATION, "DocEntry": doc_entry, "DocDate": doc_date,
            "DocStatus": "OPEN", "DocMode": "DRAFT", "BaseDocEntry": doc_entry, "ECode": ecode, "EName": ename,
            "GratAmount": g_amt, "LineID": i, "Nominee": "Y" if h.get("Nominee") in ("Y", True) else "N",
            "MillSLNo": h.get("MillSLNo"), "CreatedDate": now, "UserID": user, "PCName": PC_NAME,
            "UpdateDate": now, "UpdatedUserId": user, "UpdatedPCName": PC_NAME})
    db.commit()
    return {"doc_entry": doc_entry, "message": f"Payment request {doc_entry} saved"}


@router.post("/voucher/approve")
def voucher_approve(body: dict, db: Session = Depends(get_tenant_db),
                    token_data: dict = Depends(get_current_user_with_refresh)):
    """Legacy PayGratVoucherChequeUpdate: cheque no/date per line, then DocMode APPROVED."""
    try:
        doc_entry = int(body.get("DocEntry") or 0)
    except (TypeError, ValueError):
        doc_entry = 0
    if not doc_entry:
        raise HTTPException(status_code=400, detail="Select a payment request")
    have = {int(r[0]): r[1] for r in db.execute(text(
        f"SELECT LineID, DocMode FROM `{VOUCHER}` WHERE CompCode = :cc AND DocEntry = :de FOR UPDATE"),
        {"cc": COMP_CODE, "de": doc_entry}).fetchall()}
    if not have:
        raise HTTPException(status_code=404, detail="Payment request not found")
    if APPROVED in have.values():
        raise HTTPException(status_code=400, detail="Payment is already approved")
    lines = body.get("lines") if isinstance(body.get("lines"), list) else []
    if {int(_coerce("int", ln.get("LineID"), "Line")) for ln in lines if isinstance(ln, dict)} != set(have):
        raise HTTPException(status_code=400, detail="Enter the cheque for every line")
    cheques = []  # validate every line before writing any
    for ln in lines:
        no = str(ln.get("ChequeNo") or "").strip()
        cdate = _coerce("date", ln.get("ChequeDate"), "Cheque date")
        if not no or cdate == BLANK_DATE:
            raise HTTPException(status_code=400, detail=f"Line {ln.get('LineID')}: cheque no and date are required")
        if no in (c[0] for c in cheques):
            raise HTTPException(status_code=400, detail=f"Cheque no {no} is entered twice")
        cheques.append((no, cdate, int(ln.get("LineID"))))
    for no, cdate, line_id in cheques:
        db.execute(text(f"""UPDATE `{VOUCHER}` SET ChequeNo = :no, ChequeDate = :d, DocMode = 'APPROVED',
                                   UpdateDate = :now, UpdatedUserId = :u, UpdatedPCName = :pc
                            WHERE CompCode = :cc AND DocEntry = :de AND LineID = :l"""),
                   {"no": no, "d": cdate, "now": datetime.now(), "u": _user(token_data), "pc": PC_NAME,
                    "cc": COMP_CODE, "de": doc_entry, "l": line_id})
    db.commit()
    return {"message": f"Payment request {doc_entry} approved"}


# ─── STL entry / Gratuity calculation ─────────────────────────────────────


@router.get("/{kind}/list")
def grat_list(kind: str, request: Request, db: Session = Depends(get_tenant_db),
              token_data: dict = Depends(get_current_user_with_refresh)):
    t = _kind(kind)["master"]
    q = request.query_params
    search = (q.get("search") or "").strip()
    page, limit = max(int(q.get("page") or 1), 1), min(max(int(q.get("limit") or 25), 1), 500)
    where = "CompCode = :cc" + (" AND (ECode LIKE :s OR EName LIKE :s)" if search else "")
    p = {"cc": COMP_CODE, "s": f"%{search}%", "lim": limit, "off": (page - 1) * limit}
    total = db.execute(text(f"SELECT COUNT(*) FROM `{t}` WHERE {where}"), p).scalar()
    rows = db.execute(text(f"SELECT {', '.join(LIST_COLS)} FROM `{t}` WHERE {where} "
                           "ORDER BY DocEntry DESC LIMIT :lim OFFSET :off"), p).fetchall()
    return {"data": [_out(r) for r in rows], "total": total}


@router.get("/{kind}/emp_search")
def grat_emp_search(kind: str, request: Request, db: Session = Depends(get_tenant_db),
                    token_data: dict = Depends(get_current_user_with_refresh)):
    """Legacy TBLF5 EmpDetails: STL lists employees with no STL/gratuity yet; Calculation lists leavers
    (LeavingDate > DoJ) with no gratuity yet."""
    _kind(kind)
    s = f"{(request.query_params.get('q') or '').strip()}%"
    if kind == "stl":
        cond = "ECode NOT IN (SELECT ECode FROM PayGratOSTL UNION SELECT ECode FROM PayGratOGratuity)"
    else:
        cond = "LeavingDate > DoJ AND ECode NOT IN (SELECT ECode FROM PayGratOGratuity)"
    rows = db.execute(text(f"""SELECT ECode, EName, DeptName, DoJ, LeavingDate,
                                      ECode IN (SELECT ECode FROM PayGratOSTL) AS has_stl
                               FROM PayOEMP WHERE ECode <> '' AND {cond} AND (ECode LIKE :s OR EName LIKE :s)
                               ORDER BY ECode LIMIT 50"""), {"s": s}).fetchall()
    return {"data": [_out(r) for r in rows]}


def _load(db: Session, kind: str, doc_entry: int) -> dict:
    k = _kind(kind)
    head = db.execute(text(f"SELECT * FROM `{k['master']}` WHERE CompCode = :cc AND DocEntry = :de"),
                      {"cc": COMP_CODE, "de": doc_entry}).first()
    if not head:
        raise HTTPException(status_code=404, detail="Document not found")
    header = _out(head)
    lines = [_out(r) for r in db.execute(text(
        f"SELECT * FROM `{k['lines']}` WHERE CompCode = :cc AND DocEntry = :de AND ECode = :e ORDER BY GYear"),
        {"cc": COMP_CODE, "de": doc_entry, "e": header["ECode"]}).fetchall()]
    nominees = [_out(r) for r in db.execute(text(
        f"SELECT * FROM `{NOMINEES}` WHERE ECode = :e ORDER BY LineId"), {"e": header["ECode"]}).fetchall()]
    return {"header": header, "lines": lines, "nominees": nominees}


@router.get("/{kind}/doc/{doc_entry}")
def grat_doc(kind: str, doc_entry: int, db: Session = Depends(get_tenant_db),
             token_data: dict = Depends(get_current_user_with_refresh)):
    return {"data": _load(db, kind, doc_entry)}


@router.get("/{kind}/new/{ecode}")
def grat_new(kind: str, ecode: str, db: Session = Depends(get_tenant_db),
             token_data: dict = Depends(get_current_user_with_refresh)):
    """A new document prefilled for one employee (legacy GetEmpDetails / GetDocDetails1).
    Calculation of an employee with an STL record starts from it and appends the years after it."""
    _kind(kind)
    emp = db.execute(text("SELECT * FROM PayOEMP WHERE ECode = :e"), {"e": ecode}).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    if db.execute(text("SELECT 1 FROM PayGratOGratuity WHERE ECode = :e"), {"e": ecode}).first():
        raise HTTPException(status_code=400, detail=f"Gratuity of {ecode} is already calculated")
    e = _out(emp)
    reasons = [r[0] for r in db.execute(text("SELECT ExitReason FROM PayGratEReason ORDER BY SLNo")).fetchall()]
    header = {
        "ECode": e["ECode"], "EName": e["EName"], "Grade": e.get("Grade") or "", "DeptCode": e.get("DeptCode") or "",
        "DeptName": e.get("DeptName") or "", "Designation": e.get("Designation") or "",
        "Occupation": e.get("Designation") or "", "DoB": e.get("DoB") or "", "DoJ": e.get("DoJ") or "",
        "DoP": e.get("DoP") or "", "DoL": e.get("LeavingDate") or "" if kind == "calc" else STL_CUTOFF,
        "DocType": "GENERAL" if kind == "calc" else "", "LotNo": "01" if kind == "calc" else "",
        "TEReason": (reasons[0] if kind == "calc" else reasons[-1]) if reasons else "",
        "FiveYear240Validation": "Y", "DocStatus": "OPEN", "DocMode": "DRAFT", "EligiblityStartingYear": 0,
    }
    lines: list[dict] = []
    stl = db.execute(text("SELECT DocEntry FROM PayGratOSTL WHERE ECode = :e ORDER BY DocEntry DESC LIMIT 1"),
                     {"e": ecode}).first() if kind == "calc" else None
    if stl:
        doc = _load(db, "stl", int(stl[0]))
        keep = {k: v for k, v in doc["header"].items() if k not in SYSTEM_COLS and k not in ("DoL", "DocMode")}
        header |= keep | {"DocType": keep.get("DocType") or "GENERAL", "EligiblityStartingYear": 0,
                          "FromSTL": int(stl[0])}
        lines = doc["lines"]
        if lines and header["DoL"]:
            last = int(max(ln["GYear"] for ln in lines))
            lines += _years(db, last + 1, _year_of(header["DoL"]))
    nominees = [{"NomineeName": r.NomineeName or "", "PShare": r.PShare or 0, "GShare": r.GShare or 0,
                 "GAmount": 0, "Relation": r.Relation or "", "Address": r.Address or ""}
                for r in db.execute(text("SELECT * FROM PayEmpNominee WHERE ECode = :e ORDER BY LineID"),
                                    {"e": ecode}).fetchall()]
    return {"data": {"header": header, "lines": lines, "nominees": nominees}}


@router.post("/{kind}/save")
def grat_save(kind: str, body: dict, db: Session = Depends(get_tenant_db),
              token_data: dict = Depends(get_current_user_with_refresh)):
    """Create (no DocEntry) or update one STL / gratuity document with its year lines and nominees."""
    k = _kind(kind)
    master, line_t = k["master"], k["lines"]
    header = body.get("header") if isinstance(body.get("header"), dict) else {}
    raw_lines, raw_noms = body.get("lines"), body.get("nominees") or []
    ecode = str(header.get("ECode") or "").strip()
    if not ecode:
        raise HTTPException(status_code=400, detail="Employee can't be blank")
    if not isinstance(raw_lines, list) or not raw_lines:
        raise HTTPException(status_code=400, detail="Fill the year-wise lines first")
    if not str(header.get("TEReason") or "").strip():
        raise HTTPException(status_code=400, detail="Exit reason can't be blank")
    if not isinstance(raw_noms, list):
        raise HTTPException(status_code=400, detail="Invalid nominees")
    years = [ln.get("GYear") for ln in raw_lines if isinstance(ln, dict)]
    if len(years) != len(raw_lines) or len(set(map(str, years))) != len(years):
        raise HTTPException(status_code=400, detail="Each year can appear only once")

    raw_de = header.get("DocEntry")
    doc_entry = int(raw_de) if raw_de not in (None, "", 0, "0") else 0
    if doc_entry:
        cur = db.execute(text(f"SELECT ECode, DocMode, CreateDate, PCName, UserID FROM `{master}` "
                              "WHERE CompCode = :cc AND DocEntry = :de FOR UPDATE"),
                         {"cc": COMP_CODE, "de": doc_entry}).first()
        if not cur or cur.ECode != ecode:
            raise HTTPException(status_code=404, detail="Document not found")
        if cur.DocMode == APPROVED:
            raise HTTPException(status_code=400, detail="Document is approved and can't be changed")
        if kind == "calc" and db.execute(text(f"SELECT 1 FROM `{VOUCHER}` WHERE ECode = :e"), {"e": ecode}).first():
            raise HTTPException(status_code=400, detail="Payment is already requested for this gratuity")
    elif db.execute(text(f"SELECT 1 FROM `{master}` WHERE ECode = :e"), {"e": ecode}).first():
        raise HTTPException(status_code=400, detail=f"{ecode} is already entered")

    policy = str(header.get("PolicyID") or "").strip()
    if policy:
        dup = db.execute(text(f"SELECT ECode, EName FROM `{master}` WHERE PolicyID = :p AND DocEntry <> :de"),
                         {"p": policy, "de": doc_entry}).first()
        if dup:
            raise HTTPException(status_code=400,
                                detail=f"LIC-ID={policy} found already entered for ECode {dup.ECode}, {dup.EName}")

    user, now = _user(token_data), datetime.now()
    row = {c: v for c, v in header.items() if c not in SYSTEM_COLS}
    # Legacy SaveData: WagesRate = avg rate per day; "Advance" and "AdvanceAgainstGrat" are the same box.
    row["WagesRate"] = row.get("AvgRatePerDay")
    row["Advance"] = row.get("AdvanceAgainstGrat")
    row |= {"CompCode": COMP_CODE, "Location": LOCATION, "FrmName": k["frm"]}
    if doc_entry:
        row |= {"DocEntry": doc_entry, "CreateDate": cur.CreateDate, "PCName": cur.PCName, "UserID": cur.UserID,
                "UpdateDate": now, "UpdatePCName": PC_NAME, "UpdateUserID": user}
        for t in (master, line_t):
            db.execute(text(f"DELETE FROM `{t}` WHERE CompCode = :cc AND DocEntry = :de"),
                       {"cc": COMP_CODE, "de": doc_entry})
    else:
        doc_entry = _next_doc_entry(db, master)
        row |= {"DocEntry": doc_entry, "CreateDate": now, "PCName": PC_NAME, "UserID": user,
                "DocStatus": "OPEN", "DocMode": "DRAFT"}
    _insert(db, master, row)

    for i, ln in enumerate(raw_lines, start=1):
        line = {c: ln.get(c) for c in LINE_COLS}
        if not line.get("Settled"):
            line["Settled"] = "0"  # legacy grid defaults
        if not line.get("LineStatus"):
            line["LineStatus"] = "0"
        _insert(db, line_t, line | {"CompCode": COMP_CODE, "Location": LOCATION, "DocEntry": doc_entry,
                                    "ECode": ecode, "LineId": i})

    # Nominees are keyed by employee (legacy reads them back by ECode).
    db.execute(text(f"DELETE FROM `{NOMINEES}` WHERE ECode = :e"), {"e": ecode})
    for i, n in enumerate((n for n in raw_noms if isinstance(n, dict) and str(n.get("NomineeName") or "").strip()),
                          start=1):
        _insert(db, NOMINEES, {c: n.get(c) for c in NOMINEE_COLS} | {
            "CompCode": COMP_CODE, "Location": LOCATION, "DocEntry": doc_entry, "ECode": ecode, "LineId": i,
            "UserID": user, "PCName": PC_NAME, "CreatedDate": now})

    if kind == "calc":  # legacy: the STL record is closed once the gratuity is calculated
        db.execute(text("UPDATE PayGratOSTL SET DocMode = 'APPROVED' WHERE ECode = :e"), {"e": ecode})
    db.commit()
    return {"doc_entry": doc_entry, "message": f"Document {doc_entry} saved"}
