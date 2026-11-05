"""
Staff Salary Process — port of the "Staff Salary" branch of the legacy Smart-Eye (Northbrook)
"Process - FN Wages / Salary" screen (FrmWagesProcess_FYN, SType = Staff Salary).

Legacy runs `SP_SalaryProcessing` for one SubGroup (STAFF / CLERK / WATCH & WORD) of a monthly S-period:

    PaySalary   PayMAtten (monthly staff attendance) x PayOEMP (Grade STAFF, SubGroup) x latest PayOSAL
                -> basic / DA / allowances / OT / gross / PF / ESI / PTax / TDS / loans / LIC / net
    PayWages    the result mirrored as PaySlipType 'STAFF SALARY', bank from PayOEMP, SrlNo / SlNo
    _Cumm       pension / CoC / FPF / PF employer / BNS gross / YTD days, gross, PF, loan balances

PayMAtten, PayOSAL, PaySalary and PayCummOP are legacy tables mirrored into the tenant DB (same names and
columns); PayOEMP is the mirrored employee master, PaySalaryPeriod = pay_period (S codes).

ponytail: only the post-01/01/2024 gross rule is ported (periods before it are refused). Not ported:
SP_GenInterest, SP_PayLeaveDetail_STP and the auto-lock of earlier periods — same gaps as the wages port.
Process rows are tagged PCName = PROCESS_TAG; a period/sub-group holding migrated (untagged) paid rows is
refused (409), so legacy months are never overwritten.
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy.sql import text

from src.authorization.utils import get_current_user_with_refresh
from src.common.utils import parse_json_body
from src.config.db import get_tenant_db
from src.hrms.wagesSalaryProcess import PROCESS_TAG, UCI, UNIT_CODE, _bulk_apply, _json_rows, _loan_emi, _scope

router = APIRouter()

SUB_GROUPS = ("STAFF", "CLERK", "WATCH & WORD")
MIN_FROM_DATE = date(2024, 1, 1)
# PayOEMP is mirrored as utf8mb4_0900_ai_ci, the other legacy tables as utf8mb4_unicode_ci.
OEMP = f"PayOEMP e ON e.ECode {UCI} = {{}}.ECode"

PS = ("s.CompCode = :c AND s.Location = :l AND s.UnitCode = :u AND s.PCode = :p AND s.EDate = :t "
      "AND s.SubGroup = :sg")
W = ("w.CompCode = :c AND w.Location = :l AND w.UnitCode = :u AND w.PCode = :p AND w.EDate = :t "
     "AND w.SubGroup = :sg")
TOTAL_DED = ("s.PFAmt + s.ESIAmt + s.PTaxAmt + s.TDSAmt + s.ITaxAmt + s.PFLoan + s.PFInst + s.Advance"
             " + s.SpecialAdvance + s.LICAmt + s.LIPAmt + s.LWFund + s.HRDAmt + s.ElectricityAmt"
             " + s.Misc1Ded + s.Misc2Ded")
NET = ("s.ROff = ROUND(s.GrossEarning - s.TotalDed, 0) - (s.GrossEarning - s.TotalDed), "
       "s.NetPay = ROUND(s.GrossEarning - s.TotalDed, 0)")


def _period(db: Session, period_id, branch_id) -> dict:
    row = db.execute(text(
        "SELECT ID, code, name, FROM_DATE, TO_DATE FROM pay_period WHERE ID = :id AND branch_id = :b"
    ), {"id": period_id, "b": branch_id}).fetchone()
    if not row or not row.FROM_DATE or not row.TO_DATE or not row.code:
        raise HTTPException(status_code=400, detail="Pay period not found for this branch")
    if not str(row.code).upper().startswith("S"):
        raise HTTPException(status_code=400, detail="Select a staff salary (S) period")
    return {"id": row.ID, "code": row.code, "name": row.name or "",
            "from_date": row.FROM_DATE, "to_date": row.TO_DATE}


def _fill_not_null(db: Session, table: str, cols: dict) -> dict:
    """Mirrored legacy tables have NOT NULL columns without defaults (strict mode): 0 / '' / 1900-01-01."""
    for col, dtype in db.execute(text(
            "SELECT column_name, data_type FROM information_schema.columns WHERE table_schema = DATABASE() "
            "AND table_name = :t AND is_nullable = 'NO' AND column_default IS NULL"), {"t": table}):
        if col not in cols:
            cols[col] = ("''" if dtype in ("varchar", "char", "longtext", "text")
                         else "'1900-01-01'" if dtype in ("date", "datetime") else "0")
    return cols


def run_salary_process(db: Session, branch_id: int, period_id: int, sub_group: str, lwf_amt: float,
                       user: str) -> dict:
    """SP_SalaryProcessing + SP_SalaryProcessing_Cumm for one S-period and sub-group. Caller commits."""
    comp, loc = _scope(branch_id)
    if sub_group not in SUB_GROUPS:
        raise HTTPException(status_code=400, detail=f"Sub group must be one of {', '.join(SUB_GROUPS)}")
    p = _period(db, period_id, branch_id)
    f, t, pcode = p["from_date"], p["to_date"], p["code"]
    if f < MIN_FROM_DATE:
        raise HTTPException(status_code=400, detail="Salary process supports periods from 01/01/2024 onwards")
    fys = date(t.year if t.month >= 4 else t.year - 1, 4, 1)
    k = {"c": comp, "l": loc, "u": UNIT_CODE, "p": pcode, "pn": p["name"], "f": f, "t": t, "sg": sub_group,
         "maxd": 26 if sub_group in ("CLERK", "WATCH & WORD") else t.day, "lwf": lwf_amt, "tag": PROCESS_TAG,
         "usr": user[:30], "pid": p["id"], "b": branch_id, "fys": fys, "op": date(2021, 3, 31)}

    migrated = db.execute(text(f"""
        SELECT (SELECT COUNT(*) FROM PaySalary s WHERE {PS} AND IFNULL(s.PCName, '') <> :tag AND s.NetPay <> 0)
             + (SELECT COUNT(*) FROM paywages w WHERE {W} AND IFNULL(w.PCName, '') <> :tag AND w.NetPayable <> 0)
    """), k).scalar()
    if migrated:
        raise HTTPException(status_code=409,
                            detail=f"{pcode} / {sub_group} already holds {migrated} paid salary rows that were not "
                                   f"created by this process; it cannot be re-processed")

    # latest salary master per employee (legacy #PayOSAL: MAX(EffDate) <= period end)
    db.execute(text("DROP TEMPORARY TABLE IF EXISTS _sp_osal"))
    db.execute(text("""
        CREATE TEMPORARY TABLE _sp_osal (KEY (ECode)) AS
        SELECT o.* FROM PayOSAL o
        JOIN (SELECT ECode, MAX(EffDate) me FROM PayOSAL WHERE EffDate <= :t GROUP BY ECode) m
          ON m.ECode = o.ECode AND m.me = o.EffDate
    """), k)

    # ── PaySalary rows ─────────────────────────────────────────────────────
    db.execute(text(f"DELETE s FROM PaySalary s WHERE {PS}"), k)
    k["dl"] = db.execute(text("SELECT IFNULL(MAX(DocLine), 0) FROM PaySalary")).scalar()
    cols = _fill_not_null(db, "PaySalary", {
        "DocLine": ":dl + ROW_NUMBER() OVER (ORDER BY e.Grade, e.SubGroup, a.ECode)",
        "CompCode": "a.CompCode", "Location": "a.Location", "UnitCode": ":u", "LineID": "a.LineID", "ECode": "a.ECode",
        "SType": "'Staff Salary'", "PCode": "a.PCode", "PName": ":pn", "EDate": "a.EDate", "Shift": "'A'",
        "PType": "a.WType", "Grade": "e.Grade", "EGroup": "e.EGroup", "SubGroup": "e.SubGroup",
        "DeptCode": "e.DeptCode", "DeptName": "e.DeptName", "Designation": "e.Designation",
        "MonthDays": "a.TotalDay", "Present": "a.PresentDay", "DO": "a.RestDay", "FHDays": "a.Holiday",
        "PL": "a.PLDay", "CL": "a.CLDay", "SL": "a.SLDay", "Absent": "a.AbsentDay", "PayableDays": "a.PayableDay",
        "OTHrs": "a.OT_Hrs", "NightHrs": "a.NS_Hrs",
        "BasicAmt": "IFNULL(IF(a.TotalDay = a.PayableDay, m.BasicAmt, m.BasicAmt / :maxd * a.PayableDay), 0)",
        "DAAmt": "IFNULL(IF(a.TotalDay = a.PayableDay, m.DAAmt, m.DAAmt / :maxd * a.PayableDay), 0)",
        "PFAdj": "a.PFAdj", "Other": "a.MiscEarn", "NPFAdj": "a.NPFAdj", "LTAAmt": "a.LTAAmt", "LWFund": ":lwf",
        "Misc1Ded": "a.MiscDudc", "PaidOn": ":t", "ProcessDate": "NOW()", "PCName": ":tag", "UserName": ":usr",
    })
    db.execute(text(f"""
        INSERT INTO PaySalary ({", ".join(cols)})
        SELECT {", ".join(cols.values())}
        FROM PayMAtten a JOIN {OEMP.format("a")} AND e.Active = 'Y'
        LEFT JOIN _sp_osal m ON m.ECode = a.ECode
        WHERE a.CompCode = :c AND a.Location = :l AND a.PCode = :p AND a.Grade = 'STAFF'
          AND e.SubGroup {UCI} = :sg AND (a.PayableDay > 0 OR a.OT_Hrs > 0 OR a.NS_Hrs > 0)
    """), k)

    def upd(sets: str, cond: str = "", join: bool = True) -> None:
        db.execute(text(f"UPDATE PaySalary s {'JOIN _sp_osal o ON o.ECode = s.ECode' if join else ''} "
                        f"SET {sets} WHERE {PS} {('AND ' + cond) if cond else ''}"), k)

    upd("s.NightAmt = IFNULL((s.BasicAmt + s.DAAmt) / (s.PayableDays * 8) * s.NightHrs, 0)",
        "o.NightAllow = 'Y' AND s.NightHrs > 0")
    upd("s.PFGross = ROUND(s.BasicAmt + s.DAAmt + s.NightAmt, 0)", join=False)
    upd("s.HRAAmt = ROUND(s.PFGross * o.HRARate / 100, 0)", "o.HRA = 'Y'")
    for col, flag in (("ConveyanceAmt", "Conveyance"), ("SpecialAmt", "Special"), ("WashingAmt", "Washing"),
                      ("GasAmt", "Gas"), ("MobileAmt", "Mobile"), ("FoodingAmt", "Fooding")):
        upd(f"s.{col} = o.{col} / :maxd * s.PayableDays", f"o.{flag} = 'Y'")
    upd("s.TAAmt = 0", "o.TA = 'Y'")
    upd("s.CoalAmt = IF(s.Present + s.PL > :maxd, o.CoalRate, IFNULL(o.CoalRate / o.CoalDays * (s.Present + s.PL), 0))",
        "o.Coal = 'Y'")
    upd("s.OTAmt = IF(o.OTHR > 0, o.OTRate / o.OTHR * s.OTHrs, 0)",
        "o.OTAllow = 'Y' AND s.SubGroup IN ('CLERK', 'WATCH & WORD')")
    upd("s.OTAmt = IFNULL((s.BasicAmt + s.SpecialAmt) / (s.PayableDays * 8) * s.OTHrs, 0)",
        "o.OTAllow = 'Y' AND s.SubGroup = 'STAFF'")
    upd("""s.GrossEarning = s.PFGross + s.HRAAmt + s.ConveyanceAmt + s.SpecialAmt + s.WashingAmt + s.TAAmt + s.GasAmt
                           + s.CoalAmt + s.MobileAmt + s.FoodingAmt + s.OTAmt + s.LTAAmt + s.PFAdj + s.NPFAdj + s.Other,
           s.ESIGross = s.PFGross + s.HRAAmt + s.ConveyanceAmt + s.SpecialAmt + s.WashingAmt + s.TAAmt + s.GasAmt
                       + s.CoalAmt + s.MobileAmt + s.FoodingAmt + s.LTAAmt + s.PFAdj + s.NPFAdj""", join=False)
    upd("""s.PFAmt = IF(s.PFGross * 10 / 100 > 1500, 1500, ROUND(s.PFGross * 10 / 100, 0)),
           s.PFCAmt = IF(s.PFGross * 10 / 100 > 1500, ROUND(15000 * 8.33 / 100, 0), ROUND(s.PFGross * 8.33 / 100, 0))""",
        "o.PF = 'Y'")
    upd("s.FPCAmt = s.PFAmt - s.PFCAmt", "o.PF = 'Y'")
    upd("s.LWFund = 0", "o.PF = 'N'")  # legacy: no LWF for non-PF staff (01/01/2024)
    upd("s.ESIAmt = IF(s.ESIGross >= 21000, 0, CEILING(s.ESIGross * 0.75 / 100))", "o.ESI = 'Y'")
    upd("""s.PTaxAmt = IFNULL((SELECT r.FRate_HR FROM PayOMiscRate r WHERE r.Location = :l AND r.All_Type = 'PTAX'
                               AND r.FRate <= s.ESIGross AND r.SRate >= s.ESIGross
                               AND r.EffDate = (SELECT MAX(EffDate) FROM PayOMiscRate WHERE All_Type = 'PTAX'
                                                AND Location = :l AND EffDate <= :f) LIMIT 1), 0)""",
        "o.PTax = 'Y'")
    def from_atten(col: str, src: str, flag: str) -> None:
        upd(f"s.{col} = IFNULL((SELECT MAX(a.{src}) FROM PayMAtten a WHERE a.ECode = s.ECode AND a.PCode = :p), 0)",
            f"o.{flag} = 'Y'")

    from_atten("TDSAmt", "TDSAmt", "TDS")
    from_atten("ITaxAmt", "ITaxAmt", "ITAX")
    upd(f"s.TotalDed = {TOTAL_DED}", join=False)

    # loans (legacy GetLoanEMI): PF loan + interest, then advance — each only while the pay still covers it
    rows = db.execute(text(f"SELECT s.ECode, s.GrossEarning, s.TotalDed FROM PaySalary s WHERE {PS}"), k).fetchall()
    emi = _loan_emi(db, comp, loc, t, [r.ECode.strip() for r in rows])
    loans = []
    for r in rows:
        m = emi.get(r.ECode.strip())
        if not m:
            continue
        net = float(r.GrossEarning) - float(r.TotalDed)
        cap = intr = adv = 0.0
        if net - (m["inst_cap"] + m["inst_int"]) > 0 and m["bal_loan"] + m["bal_int"] > 0:
            cap, intr = m["inst_cap"], m["inst_int"]
        if net - cap - intr - m["inst_adv"] > 0 and m["bal_adv"] > 0:
            adv = m["inst_adv"]
        if cap or intr or adv:
            loans.append({"e": r.ECode.strip(), "a": cap, "b2": intr, "d": adv})
    _bulk_apply(db, "_sp_loan", "(ECode VARCHAR(20) NOT NULL PRIMARY KEY, cap DOUBLE, intr DOUBLE, adv DOUBLE)",
                "(:e, :a, :b2, :d)", loans,
                f"""UPDATE PaySalary s JOIN _sp_loan q ON q.ECode = s.ECode {UCI}
                    SET s.PFLoan = q.cap, s.PFInst = q.intr, s.Advance = q.adv WHERE {PS}""", k)
    upd("s.LICAmt = o.LICAmt", "o.LIC = 'Y'")
    upd("s.LIPAmt = o.LIPAmt", "o.LIP = 'Y'")
    upd("s.HRDAmt = 0", "o.HRD = 'Y'")
    from_atten("ElectricityAmt", "ElecAmt", "ELEC")
    upd(f"s.TotalDed = {TOTAL_DED}", join=False)
    upd(NET, join=False)
    # negative net: drop electricity (and LWF, sic), then PF loan, then advance, then LIC / LIP
    for drop in ("s.ElectricityAmt = 0, s.LWFund = 0", "s.PFLoan = 0, s.PFInst = 0", "s.Advance = 0, s.SpecialAdvance = 0",
                 "s.LICAmt = 0, s.LIPAmt = 0"):
        upd(f"{drop}, s.TotalDed = {TOTAL_DED}", "s.NetPay < 0", join=False)
        upd(NET, "s.NetPay < 0", join=False)

    # ── mirror into paywages ───────────────────────────────────────────────
    db.execute(text(f"DELETE w FROM paywages w WHERE {W}"), k)
    wcols = _fill_not_null(db, "paywages", {
        "CompCode": ":c", "Location": ":l", "UnitCode": ":u", "WYear": "YEAR(:f)", "WMonth": "MONTH(:f)",
        "WDay": "RIGHT(:p, 2)", "PCode": ":p", "EDate": ":t", "period_id": ":pid", "branch_id": ":b",
        "ECode": "s.ECode", "EName": "e.EName", "Grade": "e.Grade", "EGroup": "e.EGroup", "SubGroup": "e.SubGroup",
        "DoB": "IFNULL(e.DoB, '1900-01-01')", "DoJ": "IFNULL(e.DoJ, '1900-01-01')", "Active": "e.Active",
        "RestDay": "IFNULL(e.RestDay, '')", "PaySlipType": "'STAFF SALARY'",
        "NS_HR": "s.NightHrs", "OT_HR": "s.OTHrs", "TotalDays": "s.MonthDays", "Work_Day": "s.PayableDays",
        "OFBasic": "IFNULL(o.BasicAmt, 0)", "OFBasic_HR": "IFNULL(o.BasicHR, 0)",
        "FBasic_Rate": "IFNULL(o.BasicAmt, 0) / DAY(:t)", "FBasic_Amt": "s.BasicAmt", "OVBasic": "'0'",
        "ODA_All": "IF(o.DAAmt > 0, 'Y', 'N')", "ODA_Rate": "IFNULL(o.DAAmt, 0)",
        "DA_Rate": "IFNULL(o.DAAmt / IF(o.DAHR > 0, o.DAHR, 1), 0)", "DA_Amt": "s.DAAmt",
        "ONS_All": "IFNULL(o.NightAllow, 'N')", "NS_Amt": "s.NightAmt", "OOT_All": "IFNULL(o.OTAllow, 'N')",
        "OT_Amt": "s.OTAmt", "OBeamChange_All": "'N'", "PFEarnAdj": "s.PFAdj", "NPFEarnAdj": "s.NPFAdj",
        "MiscEarn": "s.Other", "OIncentive": "'0'", "OExtra_All": "'N'", "OOil_All": "'N'",
        "PF_Gross": "s.PFGross", "HRA_Gross": "s.PFGross", "OHRA_All": "IFNULL(o.HRA, 'N')", "HRA_Amt": "s.HRAAmt",
        "Spl_All_Amt": "s.SpecialAmt", "TA_Amt": "s.TAAmt", "Gas_All_Amt": "s.GasAmt", "Coal_All_Amt": "s.CoalAmt",
        "Washing_Amt": "s.WashingAmt", "Conv_Amt": "s.ConveyanceAmt", "Mobile_Amt": "s.MobileAmt",
        "Tiffin_Amt": "s.FoodingAmt", "ESI_Gross": "s.ESIGross", "PTax_Gross": "s.ESIGross",
        "Pension_Gross": "ROUND(s.PFGross, 0)", "Wages_Gross": "s.GrossEarning", "LTAAmt": "s.LTAAmt",
        "OPF": "IFNULL(o.PF, 'N')", "PFEmployee": "s.PFAmt", "OESI": "IFNULL(o.ESI, 'N')", "ESI_Amt": "s.ESIAmt",
        "OPTax": "IFNULL(o.PTax, 'N')", "PTax_BAmt": "s.ESIGross", "PTax_Amt": "s.PTaxAmt", "TDSAmt": "s.TDSAmt",
        "ITaxAmt": "s.ITaxAmt", "OLWF": "IF(s.LWFund > 0, 'Y', 'N')", "LWF_Amt": "s.LWFund", "OQuarter": "'N'",
        "HRDeduction": "s.HRDAmt", "PFLoanCap": "s.PFLoan", "PFLoanInt": "s.PFInst", "Advance": "s.Advance",
        "SplAdvance": "s.SpecialAdvance", "Electricity": "s.ElectricityAmt", "LIC": "s.LICAmt", "LIP": "s.LIPAmt",
        "OtherDeduction": "s.Misc1Ded + s.Misc2Ded", "TotalDeduction": "s.TotalDed", "BF": "s.BF",
        "NetPay": "s.GrossEarning - s.TotalDed", "CF": "s.CF", "ROff": "s.ROff", "NetPayable": "s.NetPay",
        "BankName": "IFNULL(e.BankName, '')", "Branch": "IFNULL(e.Branch, '')", "IFSC": "IFNULL(e.IFSC, '')",
        "AccNo": "IFNULL(e.AccNo, '')", "BenificiaryName": "IFNULL(e.EDisplayName, '')",
        "CreatedDate": "NOW()", "UpdatedDate": "NOW()", "PCName": ":tag", "UserID": ":usr", "UserName": ":usr",
    })
    db.execute(text(f"""
        INSERT INTO paywages ({", ".join(wcols)})
        SELECT {", ".join(wcols.values())}
        FROM PaySalary s JOIN {OEMP.format("s")} LEFT JOIN _sp_osal o ON o.ECode = s.ECode
        WHERE {PS}
    """), k)
    # numbering over every sub-group of the period (legacy: SlNo restarts per SubGroup)
    db.execute(text("""
        UPDATE paywages w JOIN (
            SELECT ECode, ROW_NUMBER() OVER (ORDER BY EGroup, SubGroup, ECode) srl,
                   ROW_NUMBER() OVER (PARTITION BY SubGroup ORDER BY EGroup, SubGroup, ECode) sl
            FROM paywages WHERE PCode = :p AND Location = :l) q ON q.ECode = w.ECode
        SET w.SrlNo = q.srl, w.SlNo = q.sl
        WHERE w.PCode = :p AND w.Location = :l
    """), k)

    # ── _Cumm: pension / CoC / balances / YTD ──────────────────────────────
    db.execute(text(f"""UPDATE paywages w SET w.Pension = IF(w.PFEmployee = 1500, ROUND(15000 * 8.33 / 100, 0),
                                                   ROUND(ROUND(w.Pension_Gross, 0) * 8.33 / 100, 0))
                        WHERE {W} AND w.OPF = 'Y'"""), k)
    db.execute(text(f"""UPDATE paywages w JOIN {OEMP.format("w")} SET w.Pension = 0
                        WHERE {W} AND w.OPF = 'Y' AND FLOOR(DATEDIFF(:f, e.PensionDate) / 365.25) >= 58"""), k)
    db.execute(text(f"UPDATE paywages w SET w.CoC = w.PFEmployee - w.Pension WHERE {W} AND w.OPF = 'Y'"), k)
    db.execute(text(f"UPDATE paywages w SET w.BNSGrs = ROUND(w.FBasic_Amt + w.DA_Amt + w.NS_Amt + w.Spl_All_Amt, 0) WHERE {W}"), k)
    # history sums go through a temp table (MySQL cannot read paywages in a subquery of its own UPDATE)
    db.execute(text("DROP TEMPORARY TABLE IF EXISTS _sp_cum"))
    db.execute(text(f"""
        CREATE TEMPORARY TABLE _sp_cum (PRIMARY KEY (ECode)) AS
        SELECT w.ECode,
               (SELECT IFNULL(SUM(h.Pension), 0) FROM paywages h WHERE h.ECode = w.ECode AND h.EDate > :op AND h.EDate < :f) pen,
               (SELECT IFNULL(SUM(h.PFEmployee - h.Pension), 0) FROM paywages h WHERE h.ECode = w.ECode AND h.EDate > :op AND h.EDate < :f) coc,
               (SELECT IFNULL(SUM(h.PFEmployee), 0) FROM paywages h WHERE h.ECode = w.ECode AND h.EDate > :op AND h.EDate < :f) pfe,
               (SELECT IFNULL(SUM(h.BNSGrs), 0) FROM paywages h WHERE h.ECode = w.ECode AND h.EDate >= :fys AND h.EDate <= :t) bns,
               (SELECT IFNULL(SUM(h.PF_Gross), 0) FROM paywages h WHERE h.ECode = w.ECode AND h.EDate >= :fys AND h.EDate <= :t) pfg,
               (SELECT IFNULL(SUM(c.PenBalance), 0) FROM PayCummOP c WHERE c.ECode = w.ECode) op_pen,
               (SELECT IFNULL(SUM(c.COCBalance), 0) FROM PayCummOP c WHERE c.ECode = w.ECode) op_coc,
               (SELECT IFNULL(SUM(c.PFCBalance), 0) FROM PayCummOP c WHERE c.ECode = w.ECode) op_pfc,
               (SELECT SUM(LEAST(a.PresentDay + a.RestDay + a.Holiday + a.PLDay + a.CLDay + a.SLDay
                                 + ROUND(a.NS_Hrs / 8, 0) + a.AdjDay, DAY(a.EDate)))
                FROM PayMAtten a WHERE a.ECode = w.ECode AND a.EDate > :fys AND a.EDate <= :t) ytd_days
        FROM paywages w WHERE {W}
    """), k)
    db.execute(text(f"""
        UPDATE paywages w JOIN _sp_cum q ON q.ECode = w.ECode
        SET w.FPF_Pension = IF(w.OPF = 'Y', q.op_pen + q.pen + w.Pension, w.FPF_Pension),
            w.PF_Employer = IF(w.OPF = 'Y', q.op_coc + q.coc + w.CoC, w.PF_Employer),
            w.YTD_Days = IFNULL(q.ytd_days, w.YTD_Days), w.YTD_BNSGrs = q.bns, w.YTD_PFGross = q.pfg,
            w.YTD_PFEmployee = q.op_pfc + q.pfe + w.PFEmployee
        WHERE {W}
    """), k)
    _bulk_apply(db, "_sp_bal", "(ECode VARCHAR(20) NOT NULL PRIMARY KEY, bl DOUBLE, bi DOUBLE)", "(:e, :a, :b2)",
                [{"e": e, "a": m["bal_loan"], "b2": m["bal_int"]} for e, m in emi.items()],
                f"""UPDATE paywages w JOIN _sp_bal q ON q.ECode = w.ECode {UCI}
                    SET w.YTD_LoanAmt = q.bl - w.PFLoanCap, w.YTD_IntAmt = q.bi - w.PFLoanInt WHERE {W}""", k)

    s = db.execute(text(f"""
        SELECT COUNT(*) n, IFNULL(SUM(s.GrossEarning), 0) gross, IFNULL(SUM(s.TotalDed), 0) ded,
               IFNULL(SUM(s.NetPay), 0) net FROM PaySalary s WHERE {PS}
    """), k).fetchone()
    return {"period": pcode, "sub_group": sub_group, "from_date": f.isoformat(), "to_date": t.isoformat(),
            "employees": int(s.n), "gross": float(s.gross), "total_deduction": float(s.ded), "net_pay": float(s.net)}


# ─── Endpoints ─────────────────────────────────────────────────────────────


@router.get("/salary_process_setup")
def salary_process_setup(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Staff salary (S) periods of the branch, with attendance / processed row counts, and the sub-groups."""
    branch_id = request.query_params.get("branch_id")
    comp, loc = _scope(branch_id)
    periods = db.execute(text("""
        SELECT pp.ID AS id, pp.code, pp.name, pp.FROM_DATE AS from_date, pp.TO_DATE AS to_date,
               (SELECT COUNT(*) FROM PayMAtten a WHERE a.CompCode = :c AND a.Location = :l AND a.Grade = 'STAFF'
                  AND a.PCode = pp.code COLLATE utf8mb4_unicode_ci) AS attendance_rows,
               (SELECT COUNT(*) FROM PaySalary s WHERE s.CompCode = :c AND s.Location = :l
                  AND s.PCode = pp.code COLLATE utf8mb4_unicode_ci AND s.EDate = pp.TO_DATE) AS row_count
        FROM pay_period pp
        WHERE pp.branch_id = :b AND pp.code LIKE 'S%' AND pp.FROM_DATE >= :min
        ORDER BY pp.FROM_DATE DESC, pp.ID DESC
    """), {"b": int(branch_id), "c": comp, "l": loc, "min": MIN_FROM_DATE})
    return {"data": {"periods": _json_rows(periods), "sub_groups": list(SUB_GROUPS), "unit_code": UNIT_CODE}}


@router.post("/salary_process_run")
def salary_process_run(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    body = parse_json_body(request)
    try:
        branch_id, period_id = int(body.get("branch_id")), int(body.get("period_id"))
        lwf = round(float(body.get("lwf_amt") or 0), 2)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="branch_id, period_id and lwf_amt must be numbers")
    if lwf < 0:
        raise HTTPException(status_code=400, detail="LWF amount cannot be negative")
    try:  # a sub-group is ~20-60 staff: seconds, so no background job (unlike the wages run)
        result = run_salary_process(db, branch_id, period_id, str(body.get("sub_group") or ""), lwf,
                                    str((token_data or {}).get("user_id") or ""))
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:  # noqa: BLE001 — surfaced to the page
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Salary processing failed: {e}")
    return {"message": "Salary Processed ..", "data": result}


@router.get("/salary_process_result")
def salary_process_result(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Processed PaySalary rows of one period and sub-group (read-only grid under the Process button)."""
    branch_id = request.query_params.get("branch_id")
    comp, loc = _scope(branch_id)
    p = _period(db, request.query_params.get("period_id"), int(branch_id))
    rows = db.execute(text("""
        SELECT s.ECode AS ecode, e.EName AS ename, s.SubGroup AS sub_group, s.Designation AS designation,
               s.PayableDays AS payable_days, s.BasicAmt AS basic, s.DAAmt AS da, s.HRAAmt AS hra,
               s.OTAmt AS ot, s.GrossEarning AS gross, s.PFAmt AS pf, s.ESIAmt AS esi, s.PTaxAmt AS ptax,
               s.PFLoan + s.PFInst + s.Advance AS loans, s.TotalDed AS total_deduction, s.NetPay AS net_pay
        FROM PaySalary s LEFT JOIN PayOEMP e ON e.ECode COLLATE utf8mb4_unicode_ci = s.ECode
        WHERE s.CompCode = :c AND s.Location = :l AND s.PCode = :p AND s.EDate = :t
          AND (:sg = '' OR s.SubGroup = :sg)
        ORDER BY s.SubGroup, s.ECode
    """), {"c": comp, "l": loc, "p": p["code"], "t": p["to_date"],
           "sg": (request.query_params.get("sub_group") or "").strip()})
    return {"data": _json_rows(rows)}
