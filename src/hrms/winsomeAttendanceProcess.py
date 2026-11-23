"""
Winsome Attendance Process — port of the legacy Smart-Eye Winsome (Smart_Eye_Jute_Purnasar_Winsome_Live)
menu Reports > "Attendance Process" (ProcessFrm -> EXEC Attn_Process WDate, WShift) and
"Attendance Process - BULK" (FrmProcessBulk -> EXEC ATTEN_PROCESS_BULK FromDate, ToDate).

Attn_Process rebuilds the processed attendance `ATTEN` for one date + shift from the raw punches in
`ATTENDANCE` (latest row per worker), then applies the legacy work-type rules (DUTY -> OT). Every table is
the legacy one mirrored into the tenant DB under its legacy name (ATTENDANCE, ATTEN, PayOEMP, OMCH, OJOB,
Shift, ODPT, OUNIT, PayJOLeave, PayOHoliday, PaySalaryPeriod — dbqueries/migrations/migrate_payowagesrate_ocp.py).
Its output feeds the Winsome Wages process (winsomeWagesProcess.py), which reads ATTEN.

ponytail: not ported — the Atten_L date/shift lock (empty in legacy, never used), SP_PLog audit rows, and
Attn_Process's optional @SPECode (no legacy screen passes it).
"""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy.sql import text

from src.authorization.utils import get_current_user_with_refresh
from src.common.utils import parse_json_body
from src.config.db import get_tenant_db
from src.hrms.winsomeWagesProcess import _scope

router = APIRouter()

# ATTEN columns filled from the latest ATTENDANCE row of each worker (legacy INSERT column list)
_COPY = ("ID, entry_id, date_time, shift_id, emp_code, dept_code, ocp_code, mch1_code, mch2_code, Job1_code, "
         "Job2_code, work_type, userid, WUnit, WDate, WTime, WShift, IsManual, Shift_HR, GatePass_HR, Work_HR, "
         "Night_HR, LayOff_HR, FBasic_Amt, FBasicInc_Amt, VBasic_Amt, DA_Amt, NS_Amt, OT_Amt, BeamChange_Amt, "
         "Incentive_Amt, MiscEarn, Oil_Amt, HRA_Amt, HeadCount, Reason, AuthorisedBy, Remarks, CreatedDate, "
         "UpdatedDate, PCName, UpdatedBy, UpdatedPCName")

# legacy view AttendanceReport (only the columns Attn_Process reads; its inner joins drop unmapped rows)
_AR = """(SELECT T0.emp_code ECode, T0.WDate, T0.WShift, T0.work_type, T0.Work_HR, T1.Grade, T1.EGroup,
                 T3.DES MainShift
          FROM ATTEN T0
          JOIN PayOEMP T1 ON T0.emp_code = T1.ECode
          JOIN ODPT T2 ON T0.dept_code = T2.DeptCode AND T0.ocp_code = T2.OCPCode
          JOIN Shift T3 ON T0.WShift = T3.SHIFTMSTID
          JOIN OUNIT T4 ON T0.WUnit = T4.UCode)"""

# Attn_Process, statement by statement (:d = WDate, :s = WShift, :pf = FromDate of the P period holding :d).
# MySQL differences: same-table subqueries are wrapped in a derived table (error 1093), and the half-hours
# update sets GatePass_HR before Work_HR (MySQL SET reads already-updated columns, SQL Server does not).
_STEPS = [
    "DELETE FROM ATTEN WHERE WDate = :d AND WShift = :s",
    f"""INSERT INTO ATTEN ({_COPY})
    SELECT X5.ID, X5.entry_id, X5.date_time, X5.shift_id, X5.emp_code, X5.dept_code, X5.ocp_code,
      IF(IFNULL((SELECT O.DES FROM OMCH O WHERE O.CODE = X5.mch1_code AND O.DEPT = X5.dept_code LIMIT 1), '')
         <> '(NONE)', X5.mch1_code, '-1'),
      IF(IFNULL((SELECT O.DES FROM OMCH O WHERE O.CODE = X5.mch2_code AND O.DEPT = X5.dept_code LIMIT 1), '')
         <> '(NONE)', X5.mch2_code, '-1'),
      IF(IFNULL((SELECT O.DES FROM OJOB O WHERE O.CODE = X5.Job1_code AND O.DEPT = X5.dept_code LIMIT 1), '')
         <> '(NONE)', X5.Job1_code, '-1'),
      '-1', X5.work_type, X5.userid, X5.WUnit, X5.WDate, X5.WTime, X5.WShift, X5.IsManual,
      IFNULL((SELECT ShiftHrs FROM Shift WHERE SHIFTID = X5.WShift LIMIT 1), 0),
      X5.GatePass_HR,
      IFNULL((SELECT ShiftHrs FROM Shift WHERE SHIFTID = X5.WShift LIMIT 1), 0) - X5.GatePass_HR,
      0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
      IFNULL(X5.Reason, ''), IFNULL(X5.AuthorisedBy, ''), IFNULL(X5.Remarks, ''),
      X5.CreatedDate, X5.UpdatedDate, IFNULL(X5.PCName, ''), IFNULL(X5.UpdatedBy, ''), IFNULL(X5.UpdatedPCName, '')
    FROM (SELECT emp_code, MAX(ID) ID FROM ATTENDANCE
          WHERE WDate = :d AND WShift = :s
            AND emp_code NOT IN (SELECT ECode FROM PayOEMP WHERE Grade = 'STAFF')
          GROUP BY emp_code) X3
    JOIN ATTENDANCE X5 ON X5.emp_code = X3.emp_code AND X5.ID = X3.ID AND X5.WDate = :d AND X5.WShift = :s""",
    # mch2 '0000' entered against WDate 07/03/2021 / ECode 20202
    """UPDATE ATTEN SET mch2_code = '-1' WHERE WDate = :d AND WShift = :s AND dept_code = '111'
       AND ocp_code IN ('070304', '070305') AND mch1_code <> '-1' AND mch2_code = '0000' AND GatePass_HR = 0""",
    """UPDATE ATTEN SET GatePass_HR = Shift_HR - (Work_HR / 2), Work_HR = Work_HR / 2
       WHERE WDate = :d AND WShift = :s AND dept_code = '111' AND ocp_code IN ('070304', '070305')
         AND mch1_code <> '-1' AND mch2_code = '-1' AND GatePass_HR = 0""",
    "UPDATE ATTEN SET Night_HR = 0.5 WHERE WDate = :d AND WShift = 'C' AND Work_HR = 8",
    "UPDATE ATTEN SET HeadCount = Work_HR / 8 WHERE WDate = :d AND WShift = :s",
    "UPDATE PayOEMP SET OrgECode = ECode WHERE OrgECode = ''",
    # second spell of a worker already on DUTY earlier that day -> OT
    """UPDATE ATTEN SET work_type = 'OT' WHERE WDate = :d AND WShift IN ('B1', 'B2') AND work_type = 'DUTY'
       AND emp_code IN (SELECT emp_code FROM (SELECT emp_code FROM ATTEN WHERE WDate = :d AND work_type = 'DUTY'
                                              AND WShift IN ('A1', 'A2')) t)""",
    """UPDATE ATTEN SET work_type = 'OT' WHERE WDate = :d AND WShift = 'G2' AND work_type = 'DUTY'
       AND emp_code IN (SELECT emp_code FROM (SELECT emp_code FROM ATTEN WHERE WDate = :d AND work_type = 'DUTY'
                                              AND WShift IN ('G1', 'A1', 'A2')) t)""",
    """UPDATE ATTEN SET work_type = 'OT' WHERE WDate = :d AND WShift = 'C' AND work_type = 'DUTY'
       AND emp_code IN (SELECT emp_code FROM (SELECT emp_code FROM ATTEN WHERE WDate = :d AND work_type = 'DUTY'
                                              AND WShift IN ('A1', 'A2', 'B1', 'B2', 'G1', 'G2')) t)""",
    # outsiders (and retired before 01/12/2022) are always OT
    f"""UPDATE ATTEN SET work_type = 'OT' WHERE WDate = :d AND WShift = :s
       AND emp_code IN (SELECT ECode FROM {_AR} ar WHERE ar.WDate = :d AND ar.WShift = :s
                        AND (ar.EGroup = 'OUTSIDER' OR (ar.EGroup = 'RETIRE' AND :d < '2022-12-01')))""",
    # worker on open PL/CL leave that day
    """UPDATE ATTEN SET work_type = 'OT' WHERE WDate = :d AND WShift = :s
       AND emp_code IN (SELECT ECode FROM PayJOLeave WHERE DocStatus = 'OPEN' AND FromDate <= :d AND ToDate >= :d)""",
    # holiday: every shift of the day
    "UPDATE ATTEN SET work_type = 'OT' WHERE WDate = :d AND EXISTS (SELECT 1 FROM PayOHoliday WHERE HolidayDate = :d)",
    # more than 6 worked (date, main shift) DUTY slots in the last 7 days of this P period -> OT
    f"""UPDATE ATTEN SET work_type = 'OT' WHERE WDate = :d AND WShift = :s AND work_type = 'DUTY' AND :d >= :pf
       AND emp_code IN (
         SELECT ECode FROM (
           SELECT ECode FROM (
             SELECT ECode, WDate, MainShift, IF(SUM(Work_HR) > 0, 1, 0) cnt FROM {_AR} ar
             WHERE ar.Grade <> 'OUTSIDER' AND ar.work_type = 'DUTY'
               AND ar.WDate >= DATE_SUB(:d, INTERVAL 6 DAY) AND ar.WDate <= :d AND ar.WDate >= :pf
             GROUP BY ECode, MainShift, WDate) x
           GROUP BY ECode HAVING SUM(cnt) > 6) z)""",
]


def _locked(db: Session, to_d: date) -> None:
    """Legacy GetPeriodLockStatus(from, to): refuse when the period holding `to` is locked.
    ponytail: legacy takes TOP 1 of any period (P or S) with no ORDER BY; we check the wages (P) period."""
    if db.execute(text("""SELECT 1 FROM PaySalaryPeriod WHERE Code LIKE 'P%' AND FromDate <= :t AND ToDate >= :t
                          AND Locked = 'Y' LIMIT 1"""), {"t": to_d}).first():
        raise HTTPException(status_code=409, detail="Selected Period Locked Process Not Allowed.")


def attn_process(db: Session, wdate: date, wshift: str) -> int:
    """Legacy Attn_Process for one date + shift. Returns the ATTEN rows of that date/shift. Caller commits."""
    pf = db.execute(text("""SELECT FromDate FROM PaySalaryPeriod WHERE Code LIKE 'P%' AND FromDate <= :d
                            AND ToDate >= :d ORDER BY FromDate LIMIT 1"""), {"d": wdate}).scalar()
    k = {"d": wdate, "s": wshift, "pf": pf or date(1900, 1, 1)}  # legacy ISNULL(..., '') = 1900-01-01
    for st in _STEPS:
        db.execute(text(st), k)
    return int(db.execute(text("SELECT COUNT(*) FROM ATTEN WHERE WDate = :d AND WShift = :s"), k).scalar() or 0)


def atten_process_bulk(db: Session, from_d: date, to_d: date) -> list[dict]:
    """Legacy ATTEN_PROCESS_BULK: clear ATTEN for the range, then Attn_Process each raw (date, shift)."""
    db.execute(text("DELETE FROM ATTEN WHERE WDate >= :f AND WDate <= :t"), {"f": from_d, "t": to_d})
    pairs = db.execute(text("""SELECT WDate, WShift FROM ATTENDANCE WHERE WDate >= :f AND WDate <= :t
                               GROUP BY WDate, WShift ORDER BY WDate, WShift"""), {"f": from_d, "t": to_d}).all()
    return [{"wdate": d.isoformat(), "wshift": s, "rows": attn_process(db, d, s)} for d, s in pairs]


def _date(v, name: str) -> date:
    try:
        return date.fromisoformat(str(v))
    except ValueError:
        raise HTTPException(status_code=400, detail=f"{name} must be a date (YYYY-MM-DD)")


def _run(db: Session, fn, *args):
    try:
        result = fn(db, *args)
        db.commit()
        return result
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:  # noqa: BLE001 — surfaced to the page
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Problem In Process: {e}")


@router.get("/winsome_atten_shifts")
def winsome_atten_shifts(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Shift lookup (legacy F5: Select ShiftId From Shift)."""
    _scope(request.query_params.get("branch_id"))
    rows = db.execute(text("SELECT SHIFTID, DES, StartTime, EndTime, ShiftHrs, Active FROM Shift ORDER BY SHIFTID"))
    return {"data": [{"shift": r.SHIFTID, "main_shift": r.DES, "start": r.StartTime, "end": r.EndTime,
                      "hours": float(r.ShiftHrs or 0), "active": r.Active} for r in rows]}


@router.post("/winsome_atten_process")
def winsome_atten_process(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Attendance Process (ProcessFrm): one date + shift."""
    body = parse_json_body(request)
    _scope(body.get("branch_id"))
    wdate, wshift = _date(body.get("wdate"), "Date"), str(body.get("wshift") or "").strip()
    if not wshift:
        raise HTTPException(status_code=400, detail="Shift Can't Be Blank.")
    if not db.execute(text("SELECT 1 FROM Shift WHERE SHIFTID = :s"), {"s": wshift}).first():
        raise HTTPException(status_code=400, detail=f"Unknown shift {wshift}")
    _locked(db, wdate)
    rows = _run(db, attn_process, wdate, wshift)
    return {"message": "Process Completed.", "data": {"wdate": wdate.isoformat(), "wshift": wshift, "rows": rows}}


@router.post("/winsome_atten_process_bulk")
def winsome_atten_process_bulk(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Attendance Process - BULK (FrmProcessBulk): every date + shift in a date range."""
    body = parse_json_body(request)
    _scope(body.get("branch_id"))
    from_d, to_d = _date(body.get("from_date"), "From"), _date(body.get("to_date"), "To")
    if from_d > to_d:
        raise HTTPException(status_code=400, detail="Start Date can not be greater than End Date.")
    if to_d - from_d > timedelta(days=31):  # ponytail: ~2s per date/shift; cap keeps one request under ~5 min, move to a background job if longer runs are needed
        raise HTTPException(status_code=400, detail="Process at most 31 days at a time.")
    _locked(db, to_d)
    done = _run(db, atten_process_bulk, from_d, to_d)
    return {"message": "Process Completed.",
            "data": {"from_date": from_d.isoformat(), "to_date": to_d.isoformat(), "shifts": done,
                     "rows": sum(x["rows"] for x in done)}}
