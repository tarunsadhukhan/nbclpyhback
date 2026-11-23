"""
Winsome Wages — port of the legacy Smart-Eye Winsome (WIL / Factory) "Process - F/N Wages" screen
(FrmWagesProcess_FYN, SType "Fort Night"): EXEC SP_WagesProcessing 'WIL','Factory','01',PCode,From,To,LWF.

The SP chain is ported 1:1 to MySQL in winsome_wages_process.sql (next to this module). It reads and writes
the legacy tables mirrored into the tenant DB under their legacy names (ATTEN, PayOEMP, PayOWagesRate,
PayODARate, PayWHoliday, PayJOLeave, PayM_Adjustment, PayOQTR, PayOLoan, PayPFTranDTL, PaySalaryPeriod,
PayWages ... — see dbqueries/migrations/migrate_payowagesrate_ocp.py) and writes the result into `PayWages`.
The period is then copied into `paywages` (shared columns) for the HRMS reports.

Legacy guard kept: a period whose bank file was generated (PayWagesH row) cannot be re-processed.
ponytail: "Lock Period" (SP_WagesProcessingH, bank file) and the Learner / Staff Salary STypes are not ported.
"""

from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy.sql import text

from src.authorization.utils import get_current_user_with_refresh
from src.common.utils import parse_json_body
from src.config.db import get_tenant_db
from src.hrms.staffSalaryProcess import _fill_not_null
from src.hrms.wagesSalaryProcess import EXPORT_COLUMNS, _json_rows

router = APIRouter()

# sidebar branch -> legacy CompCode / Location (Winsome MILL, co 153)
WINSOME_SCOPE = {110: ("WIL", "FACTORY")}
UNIT_CODE = "01"
MIN_FROM_DATE = date(2025, 4, 1)  # only the date branches live from FY 2025-26 are ported
_SQL = Path(__file__).with_name("winsome_wages_process.sql")
RENAME = {"CreateDate": "CreatedDate"}  # legacy PayWages name -> paywages name


def _scope(branch_id) -> tuple[str, str]:
    try:
        scope = WINSOME_SCOPE.get(int(branch_id))
    except (TypeError, ValueError):
        scope = None
    if not scope:
        raise HTTPException(status_code=400, detail="Select the Winsome MILL branch in the sidebar")
    return scope


def _period(db: Session, loc: str, pcode) -> dict:
    row = db.execute(text("""
        SELECT Code, Name, FromDate, ToDate FROM PaySalaryPeriod WHERE Location = :l AND Code = :p
    """), {"l": loc, "p": pcode or ""}).fetchone()
    if not row or not str(row.Code).upper().startswith("P"):
        raise HTTPException(status_code=400, detail="Select a wages (P) period")
    return {"code": row.Code, "name": row.Name or "", "from_date": row.FromDate, "to_date": row.ToDate}


def _sync_paywages(db: Session, k: dict) -> None:
    """Replace the period's rows in `paywages` with the processed PayWages rows (columns both share)."""
    cols = lambda t: [r[0] for r in db.execute(text(  # noqa: E731
        "SELECT column_name FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = :t "
        "ORDER BY ordinal_position"), {"t": t})]
    dst = set(cols("paywages"))
    # paywages column -> PayWages expression; paywages-only NOT NULL columns get 0 / '' / 1900-01-01
    m = _fill_not_null(db, "paywages", {RENAME.get(c, c): f"`{c}`" for c in cols("PayWages") if RENAME.get(c, c) in dst})
    where = "CompCode = :c AND Location = :l AND PCode = :p AND EDate = :t"
    db.execute(text(f"DELETE FROM paywages WHERE {where}"), k)
    db.execute(text("INSERT INTO paywages (%s) SELECT %s FROM PayWages WHERE %s" % (
        ",".join(f"`{c}`" for c in m), ",".join(m.values()), where)), k)


def run_winsome_wages(db: Session, branch_id: int, pcode: str, lwf_amt: float, check_bank_file: bool = True) -> dict:
    """SP_WagesProcessing for one Winsome FN period. Caller commits (or rolls back for a dry run —
    scripts/check_winsome_wages_parity.py passes check_bank_file=False to re-run paid legacy periods)."""
    comp, loc = _scope(branch_id)
    p = _period(db, loc, pcode)
    if p["from_date"] < MIN_FROM_DATE:
        raise HTTPException(status_code=400, detail="Winsome wages process supports periods from 01/04/2025 onwards")
    k = {"c": comp, "l": loc, "u": UNIT_CODE, "p": p["code"], "f": p["from_date"], "t": p["to_date"]}
    if check_bank_file and db.execute(text("""
        SELECT 1 FROM PayWagesH WHERE CompCode = :c AND Location = :l AND UnitCode = :u AND EDate = :t
          AND Grade = 'MILL-WORKMEN' LIMIT 1"""), k).first():
        raise HTTPException(status_code=409, detail="BANK FILE Generated, Unable to do Wages Process..")

    lines = [ln for ln in _SQL.read_text(encoding="utf-8").splitlines() if not ln.lstrip().startswith("--")]
    conn = db.connection()  # one connection: the script uses @variables and temporary tables
    # the legacy mirrors are utf8mb4_unicode_ci; @variables take the connection collation
    prev = conn.exec_driver_sql("SELECT @@collation_connection").scalar()
    conn.exec_driver_sql("SET collation_connection = 'utf8mb4_unicode_ci'")
    try:
        conn.exec_driver_sql("SET @c = %s, @l = %s, @u = %s, @p = %s, @f = %s, @t = %s, @lwf = %s",
                             (comp, loc, UNIT_CODE, p["code"], p["from_date"], p["to_date"], lwf_amt))
        for st in "\n".join(lines).split(";"):
            if st.strip():
                conn.exec_driver_sql(st.replace("%", "%%"))  # pymysql %-formats even without params (LIKE 'P%')
    finally:
        conn.exec_driver_sql(f"SET collation_connection = '{prev}'")
    _sync_paywages(db, k)

    s = db.execute(text("""
        SELECT COUNT(*) n, IFNULL(SUM(Wages_Gross), 0) gross, IFNULL(SUM(TotalDeduction), 0) ded,
               IFNULL(SUM(NetPayable), 0) net
        FROM PayWages WHERE CompCode = :c AND Location = :l AND PCode = :p AND EDate = :t
    """), k).fetchone()
    return {"period": p["code"], "employees": int(s.n), "wages_gross": float(s.gross),
            "total_deduction": float(s.ded), "net_payable": float(s.net)}


@router.get("/winsome_wages_setup")
def winsome_wages_setup(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Winsome wages (P) periods (legacy PaySalaryPeriod) with their processed row counts."""
    comp, loc = _scope(request.query_params.get("branch_id"))
    periods = db.execute(text("""
        SELECT pp.Code AS code, pp.Name AS name, pp.FromDate AS from_date, pp.ToDate AS to_date,
               (SELECT COUNT(*) FROM PayWages w WHERE w.CompCode = :c AND w.Location = :l AND w.PCode = pp.Code
                  AND w.EDate = pp.ToDate) AS row_count,
               EXISTS (SELECT 1 FROM PayWagesH h WHERE h.CompCode = :c AND h.Location = :l AND h.UnitCode = :u
                  AND h.EDate = pp.ToDate AND h.Grade = 'MILL-WORKMEN') AS bank_file
        FROM PaySalaryPeriod pp
        WHERE pp.Location = :l AND pp.Code LIKE 'P%' AND pp.FromDate >= :min
        ORDER BY pp.FromDate DESC
    """), {"c": comp, "l": loc, "u": UNIT_CODE, "min": MIN_FROM_DATE})
    return {"data": {"periods": _json_rows(periods)}}


@router.post("/winsome_wages_run")
def winsome_wages_run(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    body = parse_json_body(request)
    try:
        branch_id, pcode = int(body.get("branch_id")), str(body.get("pcode") or "")
        lwf = round(float(body.get("lwf_amt") or 0), 2)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="branch_id, pcode and lwf_amt are required")
    if lwf < 0:
        raise HTTPException(status_code=400, detail="LWF amount cannot be negative")
    try:
        result = run_winsome_wages(db, branch_id, pcode, lwf)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:  # noqa: BLE001 — surfaced to the page
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Wages processing failed: {e}")
    return {"message": "Wages Processed ..", "data": result}


@router.get("/winsome_wages_result")
def winsome_wages_result(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Processed rows of one period (grid under the Process button), WAGES and OT slips."""
    comp, loc = _scope(request.query_params.get("branch_id"))
    p = _period(db, loc, request.query_params.get("pcode"))
    page = max(int(request.query_params.get("page", 1)), 1)
    limit = min(max(int(request.query_params.get("limit", 50)), 1), 500)
    search = (request.query_params.get("search") or "").strip()
    args = {"c": comp, "l": loc, "p": p["code"], "t": p["to_date"], "q": search, "s": f"%{search}%",
            "lim": limit, "off": (page - 1) * limit}
    where = ("CompCode = :c AND Location = :l AND PCode = :p AND EDate = :t "
             "AND (:q = '' OR ECode LIKE :s OR EName LIKE :s)")
    total = db.execute(text(f"SELECT COUNT(*) FROM PayWages WHERE {where}"), args).scalar()
    rows = db.execute(text(f"""
        SELECT CONCAT(ECode, '-', PaySlipType) AS id, ECode AS ecode, EName AS ename, EGroup AS egroup,
               PaySlipType AS slip, DeptCode AS dept_code, Work_HR AS work_hr, OT_HR AS ot_hr, NS_HR AS ns_hr,
               Holiday_HR AS holiday_hr, Wages_Gross AS wages_gross, PFEmployee AS pf, ESI_Amt AS esi,
               HRDeduction AS hrd, TotalDeduction AS total_deduction, NetPayable AS net_payable
        FROM PayWages WHERE {where} ORDER BY PaySlipType DESC, SrlNo, ECode LIMIT :lim OFFSET :off
    """), args)
    totals = db.execute(text(f"""
        SELECT IFNULL(SUM(Wages_Gross), 0) AS wages_gross, IFNULL(SUM(TotalDeduction), 0) AS total_deduction,
               IFNULL(SUM(NetPayable), 0) AS net_payable FROM PayWages WHERE {where}
    """), args)
    return {"data": _json_rows(rows), "total": int(total or 0), "totals": _json_rows(totals)[0]}


@router.get("/winsome_wages_export")
def winsome_wages_export(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Every processed row of one period for the Excel / PDF wages register (same columns as NBJCL)."""
    comp, loc = _scope(request.query_params.get("branch_id"))
    p = _period(db, loc, request.query_params.get("pcode"))
    rows = db.execute(text(f"""
        SELECT {", ".join(EXPORT_COLUMNS)} FROM PayWages
        WHERE CompCode = :c AND Location = :l AND PCode = :p AND EDate = :t
        ORDER BY PaySlipType DESC, SrlNo, ECode
    """), {"c": comp, "l": loc, "p": p["code"], "t": p["to_date"]})
    return {"data": _json_rows(rows), "period": {"code": p["code"], "name": p["name"],
                                                 "from_date": p["from_date"].isoformat(),
                                                 "to_date": p["to_date"].isoformat()}}
