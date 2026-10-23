"""
Wages Process — port of the legacy Smart-Eye (Northbrook) "Process - FN Wages / Salary"
screen (FrmWagesProcess_FYN), fortnight wages ("Fort Night") branch only.

Legacy runs `SP_WagesProcessing`, which chains:

    0 (daily_attendance -> pay_attendance rows)
    1 _Daily     daily rates into ATTEN          -> pay_attendance (FBasic/DA/NS/OT/Beam/... amounts)
    2 _GetAtten  one PayWages row per employee   -> paywages (hours, flags, bank, Work_Day)
    4 _GetRate   earnings / PF / ESI / PTax / net -> paywages
    6 numbering  SrlNo / SlNo

Mapping legacy -> tenant DB: PayOEMP = hrms_ed_* tables (ECode = emp_code, EGroup =
category_mst.cata_desc), PayOWagesRate/PayODARate = worker_rate_mst, PaySalaryPeriod =
pay_period, ATTEN = pay_attendance (att_type R = DUTY, O = OT).

ponytail: only periods from 16/11/2025 (the legacy monthly-PF era) are supported; the
pre-2025 PF/ESI/Atten branches are not ported. Not ported yet (source tables missing or
unmapped): step 3 _GetOthAmt (VBasic / production incentive), STL (PayOSTL /
PayJOLeave), step 5 _Cumm (balances / YTD) and SP_GenInterest. Occupation-wise basic / MiscEarn / Oil
use the legacy OcpCode of a designation: designation_mst.occu_code. Salary (S) processing is a separate screen.
Process rows are tagged paywages.PCName = PROCESS_TAG so re-runs replace only their own
rows; a period that holds migrated (untagged) paid rows is refused (409).
"""

import collections
import re
import threading
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import bindparam
from sqlalchemy.sql import text

from src.authorization.utils import get_current_user_with_refresh
from src.common.utils import parse_json_body
from src.config.db import extract_subdomain_from_request, get_tenant_engine, get_tenant_db
from src.hrms.loanTransactions import LEGACY_SCOPE
from src.hrms.wagesPayslipText import payslip_text

router = APIRouter()

PROCESS_TAG = "VOWERP PROCESS"
UNIT_CODE = "01"
MIN_FROM_DATE = date(2025, 11, 16)
# HRA %: legacy PayOWagesRate.HRA_Rate (7.50 for every NJB worker); worker_rate_mst has no column.
HRA_PCT = 7.5
# Night-shift spells whose Night_HR counts as NS_HR (legacy WShift IN ('C','C2','G3')).
NIGHT_SPELLS = ("C", "C2", "G3")
# Legacy _Daily per-hour allowances by occupation (DUTY rows): (column, OcpCodes, rate, + Night_HR).
OCP_ALLOWANCES = (("MiscEarn", ("0316", "0334"), 1.25, False), ("MiscEarn", ("0322", "0323", "0335"), 0.78125, False),
                  ("MiscEarn", ("1705",), 0.240385, False), ("Oil_Amt", ("3001", "3201"), 1, True),
                  ("Oil_Amt", ("3004", "3203"), 0.375, True))
# hrms_* tables are utf8mb4_0900_ai_ci, the legacy paywages table utf8mb4_unicode_ci.
UCI = "COLLATE utf8mb4_unicode_ci"


def _scope(branch_id) -> tuple[str, str]:
    try:
        scope = LEGACY_SCOPE.get(int(branch_id))
    except (TypeError, ValueError):
        scope = None
    if not scope:
        raise HTTPException(status_code=400, detail="Select a branch that has legacy wages data (MILL)")
    return scope


def _period(db: Session, period_id, branch_id) -> dict:
    row = db.execute(text(
        "SELECT ID, code, name, FROM_DATE, TO_DATE FROM pay_period WHERE ID = :id AND branch_id = :b"
    ), {"id": period_id, "b": branch_id}).fetchone()
    if not row or not row.FROM_DATE or not row.TO_DATE or not row.code:
        raise HTTPException(status_code=400, detail="Pay period not found for this branch")
    if not str(row.code).upper().startswith("P"):
        raise HTTPException(status_code=400, detail="Select a wages (P) period")
    return {"id": row.ID, "code": row.code, "name": row.name or "",
            "from_date": row.FROM_DATE, "to_date": row.TO_DATE}


def _json_rows(result) -> list[dict]:
    out = []
    for r in result.fetchall():
        m = dict(r._mapping)
        for k, v in m.items():
            if isinstance(v, Decimal):
                m[k] = float(v)
            elif isinstance(v, (date, datetime)):
                m[k] = v.isoformat()[:10]
            elif isinstance(v, str):
                m[k] = v.strip()
        out.append(m)
    return out


def _ptax_slabs(db: Session, loc: str, from_date: date) -> list[tuple[float, float, float]]:
    """PayOMiscRate 'PTAX' slabs (FRate, SRate, FRate_HR = tax) of the latest EffDate on or before
    the period start, for the location — as legacy SP_WagesProcessing_GetRate."""
    rows = db.execute(text("""
        SELECT FRate, SRate, FRate_HR FROM PayOMiscRate
        WHERE All_Type = 'PTAX' AND Location = :l
          AND EffDate = (SELECT MAX(EffDate) FROM PayOMiscRate
                         WHERE All_Type = 'PTAX' AND Location = :l AND EffDate <= :f)
    """), {"l": loc, "f": from_date}).fetchall()
    return [(float(r.FRate), float(r.SRate), float(r.FRate_HR)) for r in rows]


def _ptax(gross: float, slabs: list[tuple[float, float, float]]) -> float:
    for lo, hi, tax in slabs:
        if lo <= gross <= hi:
            return tax
    return 0


# ─── PF monthly (legacy #PFMonthly, SP_WagesProcessing_GetRate, ToDate >= 16/11/2025) ──────────

MAX_PF, MAX_833, MAX_167, PF_WAGE_CAP = 1500, 1250, 250, 15000


def _r(x: float) -> int:
    """SQL Server ROUND(x, 0): half away from zero."""
    return int(x + 0.5) if x >= 0 else -int(-x + 0.5)


def _pf_split(pf_gross: float, g1: float, pfe1: float, f833_1: float, f167_1: float, g2: float):
    """Return ((PFEmployee, Pension, CoC) for the 1st half, same for the 2nd half)."""
    pfg = PF_WAGE_CAP if _r(pf_gross) >= PF_WAGE_CAP else _r(pf_gross)
    r10, r833 = _r(pfg * 10 / 100), _r(pfg * 8.33 / 100)
    # 1st half
    if pfe1 != 0:
        a_pf, a_833, a_167 = pfe1, f833_1, f167_1
    else:
        a_pf = _r(_r(g1) * 10 / 100)
        a_833 = MAX_833 if _r(g1 * 8.33 / 100) >= MAX_833 else _r(g1 * 8.33 / 100)
        a_167 = MAX_167 if _r(g1 * 8.33 / 100) >= MAX_833 else _r(g1 * 10 / 100) - _r(g1 * 8.33 / 100)
    # 2nd half
    if pfe1 >= MAX_PF:
        b_pf = 0
    elif pfe1 == 0:
        b_pf = r10
    else:
        b_pf = r10 - pfe1
    if MAX_PF - pfe1 < 0:
        b_833 = b_167 = 0
    else:
        if r10 >= MAX_PF:
            b_833 = MAX_833 - f833_1
        elif pfe1 > 0 and r10 < MAX_PF:
            b_833 = r833 - f833_1
        else:
            b_833 = _r(g2 * 8.33 / 100)
        if r10 >= MAX_PF:
            b_167 = MAX_167 - f167_1
        elif pfe1 > 0 and (r10 - r833) >= MAX_167:
            b_167 = MAX_167 - f167_1
        elif pfe1 > 0 and r10 < MAX_PF:
            b_167 = r10 - r833 - f167_1
        elif pfe1 == 0:
            b_167 = r10 - r833
        else:
            b_167 = _r(g2 * 10 / 100) - _r(g2 * 8.33 / 100)
    return (a_pf, a_833, a_167), (b_pf, b_833, b_167)


def _bulk_apply(db: Session, table: str, ddl: str, values: str, params: list[dict], update_sql: str,
                k: dict) -> None:
    """Load computed per-employee values into a temp table (one batched INSERT) and apply them with one UPDATE."""
    if not params:
        return
    db.execute(text(f"DROP TEMPORARY TABLE IF EXISTS {table}"))
    db.execute(text(f"CREATE TEMPORARY TABLE {table} {ddl}"))
    db.execute(text(f"INSERT INTO {table} VALUES {values}"), params)
    db.execute(text(update_sql), k)


# ─── Loans / advances (legacy GetLoanEMI + the way SP_WagesProcessing_GetRate applies it) ───────────


def _loan_emi(db: Session, comp: str, loc: str, to_date: date, ecodes: list[str]) -> dict[str, dict]:
    """Per worker: balances and this fortnight's instalments of PF loan, PF-loan interest, advance and
    special advance — a port of the legacy GetLoanEMI table function."""
    if not ecodes:
        return {}
    k = {"c": comp, "l": loc, "t": to_date, "e": tuple(ecodes)}
    ol = "FROM payoloan WHERE CompCode = :c AND Location = :l AND ECode IN :e"
    ad = "FROM payloanadjust WHERE CompCode = :c AND Location = :l AND ECode IN :e AND ToDate <= :t"
    exp = bindparam("e", expanding=True)
    bal = {}
    for r in db.execute(text(f"""
        SELECT ECode, SUM(LoanAmt) loan, SUM(IntAmt) intr, SUM(BalAdv) adv, SUM(BalSpl) spl, MAX(LoanDate) loan_date FROM (
          SELECT ECode, MAX(LoanDate) LoanDate, SUM(LoanAmt) LoanAmt, 0 IntAmt, 0 BalAdv, 0 BalSpl
            {ol} AND DocStatus = 'OPEN' AND EMIDate <= :t AND LoanType = 'PFLOAN' GROUP BY ECode
          UNION ALL SELECT ECode, NULL, 0, SUM(InterestAmt), 0, 0
            {ol} AND DocStatus = 'OPEN' AND EMIDate <= :t AND LoanType = 'PFINT' GROUP BY ECode
          UNION ALL SELECT ECode, NULL, -SUM(PFLoanCap), -SUM(PFLoanInt), -SUM(Advance), -SUM(SplAdvance)
            FROM paywages WHERE CompCode = :c AND Location = :l AND ECode IN :e AND EDate < :t GROUP BY ECode
          UNION ALL SELECT ECode, NULL, -SUM(RepayCapital), 0, 0, 0 {ad} AND LoanType = 'PFLOAN' GROUP BY ECode
          UNION ALL SELECT ECode, NULL, 0, -SUM(RepayInterest), 0, 0 {ad} AND LoanType = 'PFINT' GROUP BY ECode
          UNION ALL SELECT ECode, NULL, 0, 0, SUM(LoanAmt), 0
            {ol} AND DocStatus = 'OPEN' AND EMIDate <= :t AND LoanType = 'ADVANCE' GROUP BY ECode
          UNION ALL SELECT ECode, NULL, 0, 0, -SUM(RepayCapital), 0 {ad} AND LoanType = 'ADVANCE' GROUP BY ECode
          UNION ALL SELECT ECode, NULL, 0, 0, 0, SUM(LoanAmt)
            {ol} AND DocStatus = 'OPEN' AND EMIDate <= :t AND LoanType = 'SPL ADVANCE' GROUP BY ECode
          UNION ALL SELECT ECode, NULL, 0, 0, 0, -SUM(RepayCapital) {ad} AND LoanType = 'SPL ADVANCE' GROUP BY ECode
        ) x GROUP BY ECode
    """).bindparams(exp), k):
        bal[r.ECode.strip()] = r
    if not bal:
        return {}
    ol_rows = collections.defaultdict(list)  # (ecode, UPPER type) -> loan rows, newest loan first
    for r in db.execute(text(f"""
        SELECT ECode, UPPER(LoanType) lt, DocStatus, EMICapital, EMIInterest, EMIDate, LoanDate, DocEntry, DocLineID
        {ol} AND UPPER(LoanType) IN ('PFLOAN', 'PFINT', 'ADVANCE', 'SPL ADVANCE')
        ORDER BY LoanDate DESC, DocEntry DESC, DocLineID DESC""").bindparams(exp), k):
        ol_rows[(r.ECode.strip(), r.lt)].append(r)
    ch_rows = collections.defaultdict(list)  # (ecode, UPPER type) -> change rows, newest first
    for r in db.execute(text("""
        SELECT ECode, UPPER(LoanType) lt, ToDate, DocEntry, LineID, EMICapital, EMIInterest, CapitalStop, InterestStop
        FROM payloanchange WHERE CompCode = :c AND Location = :l AND ECode IN :e AND ToDate <= :t
          AND UPPER(LoanType) IN ('PFLOAN', 'PFINT', 'ADVANCE')
        ORDER BY ToDate DESC, DocEntry DESC, LineID DESC""").bindparams(exp), k):
        ch_rows[(r.ECode.strip(), r.lt)].append(r)

    def first(rows, pred):
        return next((r for r in rows if pred(r)), None)

    def amt(v) -> float:
        return float(v or 0)

    out = {}
    for e, b in bal.items():
        loan, intr, adv, spl = amt(b.loan), amt(b.intr), amt(b.adv), amt(b.spl)
        loan_date = b.loan_date
        pfl_ch, pfi_ch, adv_ch = ch_rows[(e, "PFLOAN")], ch_rows[(e, "PFINT")], ch_rows[(e, "ADVANCE")]
        pfl_ol = ol_rows[(e, "PFLOAN")]
        after_loan = lambda r: loan_date is None or r.ToDate >= loan_date  # noqa: E731
        # PF loan capital instalment
        cap = 0.0
        if loan > 0.005:
            stop = first(pfl_ch, lambda r: r.ToDate == to_date and r.CapitalStop == "Y")
            base = first(pfl_ol, lambda r: amt(r.EMICapital) > 0)
            chg_n = first(pfl_ch, lambda r: after_loan(r) and amt(r.EMICapital) > 0 and r.CapitalStop == "N")
            last_emi = amt(chg_n.EMICapital) if chg_n else (amt(base.EMICapital) if base else 0.0)
            if stop:
                cap = 0.0
            elif last_emi > loan:
                cap = loan  # last instalment
            else:
                since = first(pfl_ch, lambda r: after_loan(r) and amt(r.EMICapital) > 0)
                open_emi = first(pfl_ol, lambda r: r.DocStatus == "OPEN" and r.EMIDate <= to_date and amt(r.EMICapital) > 0)
                cap = amt(since.EMICapital) if since else (
                    amt(open_emi.EMICapital) if open_emi else (amt(pfl_ch[0].EMICapital) if pfl_ch else 0.0))
        # PF loan interest instalment (only once the capital is cleared)
        inst_int = 0.0
        if abs(loan) <= 0.005 and intr > 0.005:
            stop = first(pfi_ch, lambda r: r.ToDate == to_date and r.InterestStop == "Y")
            chg = first(pfi_ch, lambda r: amt(r.EMIInterest) > 0 and r.InterestStop == "N")
            opn = first(ol_rows[(e, "PFINT")], lambda r: amt(r.EMIInterest) > 0 and r.EMIDate <= to_date)
            emi = amt(chg.EMIInterest) if chg else (amt(opn.EMIInterest) if opn else 0.0)
            if stop:
                inst_int = 0.0
            elif intr <= emi:
                inst_int = intr
            else:
                chg2 = first(pfi_ch, lambda r: after_loan(r) and amt(r.EMIInterest) > 0 and r.InterestStop == "N")
                inst_int = amt(chg2.EMIInterest) if chg2 else emi
        # advance instalment: latest open advance's EMI (legacy TOP 1 by EMIDate DESC), capped by the balance
        opens = [r for r in ol_rows[(e, "ADVANCE")] if r.DocStatus == "OPEN" and r.EMIDate <= to_date]
        open_inst = amt(max(opens, key=lambda r: r.EMIDate).EMICapital) if opens else 0.0
        a_stop = first(adv_ch, lambda r: r.ToDate == to_date and r.CapitalStop == "Y")
        a_chg = first(adv_ch, lambda r: r.ToDate == to_date and r.CapitalStop == "N")
        if a_stop:
            inst_adv = 0.0
        elif a_chg and amt(a_chg.EMICapital) != 0:
            inst_adv = amt(a_chg.EMICapital)
        elif open_inst > adv:
            inst_adv = adv
        else:
            inst_adv = open_inst
        spl_open = [r for r in ol_rows[(e, "SPL ADVANCE")] if r.DocStatus == "OPEN" and r.EMIDate <= to_date]
        inst_spl = amt(max(spl_open, key=lambda r: r.EMIDate).EMICapital) if spl_open else 0.0
        out[e] = {"bal_loan": loan, "bal_int": intr, "inst_cap": cap, "inst_int": inst_int,
                  "bal_adv": adv, "inst_adv": inst_adv, "bal_spl": spl, "inst_spl": inst_spl}
    return out


def _apply_loans(db: Session, comp: str, loc: str, k: dict, W: str, to_date: date) -> None:
    """Take PF loan / advance / special-advance instalments only while the worker's pay still covers them
    (legacy order: PF loan, advance, special advance; each re-checks wages gross less deductions so far)."""
    rows = db.execute(text(f"""
        SELECT w.ECode, w.EGroup, w.Wages_Gross,
               w.PFEmployee + w.ESI_Amt + w.PTax_Amt + w.LWF_Amt + w.STLAdv + w.Electricity + w.HRDeduction ded
        FROM paywages w WHERE {W}"""), k).fetchall()
    emi = _loan_emi(db, comp, loc, to_date, [r.ECode.strip() for r in rows])
    upd = []
    for r in rows:
        m = emi.get(r.ECode.strip())
        if not m:
            continue
        gross, ded = float(r.Wages_Gross), float(r.ded)
        cap = intr = adv = spl = 0.0
        if ((gross - ded) - (m["inst_cap"] + m["inst_int"]) > 0 and (m["bal_loan"] + m["bal_int"]) > 0
                and not r.EGroup.startswith("05")):
            cap, intr = m["inst_cap"], m["inst_int"]
        ded += cap + intr
        if (gross - ded) - m["inst_adv"] > 0 and m["bal_adv"] > 0:
            adv = m["inst_adv"]
        ded += adv
        if (gross - ded) - m["inst_spl"] > 0 and m["bal_spl"] > 0:
            spl = m["inst_spl"]
        if cap or intr or adv or spl:
            upd.append({"e": r.ECode.strip(), "a": cap, "b": intr, "c2": adv, "d": spl})
    _bulk_apply(db, "_wp_loan", "(ECode VARCHAR(20) NOT NULL PRIMARY KEY, cap DOUBLE, intr DOUBLE, adv DOUBLE, spl DOUBLE)",
                "(:e, :a, :b, :c2, :d)", upd,
                f"""UPDATE paywages w JOIN _wp_loan q ON q.ECode = w.ECode {UCI}
                    SET w.PFLoanCap = q.cap, w.PFLoanInt = q.intr, w.Advance = q.adv, w.SplAdvance = q.spl
                    WHERE {W}""", k)


# ─── Core ──────────────────────────────────────────────────────────────────


def run_wages_process(db: Session, branch_id: int, period_id: int, lwf_amt: float, user: str,
                      rate_cutoff: date | None = None) -> dict:
    """Run the fortnight wages chain for one pay period. Caller commits / rolls back.

    `rate_cutoff` overrides the worker-rate "effective on or before" date (default: the period
    end date, as in legacy) — only the verification script uses it.
    """
    comp, loc = _scope(branch_id)
    p = _period(db, period_id, branch_id)
    f, t, pcode = p["from_date"], p["to_date"], p["code"]
    if f < MIN_FROM_DATE:
        raise HTTPException(status_code=400,
                            detail="Wages process supports periods from 16/11/2025 onwards")
    wday = "01" if f.day == 1 else "02"
    k = {"pid": p["id"], "b": branch_id, "c": comp, "l": loc, "u": UNIT_CODE, "f": f, "t": t, "p": pcode,
         "wd": wday, "cut": rate_cutoff or t, "lwf": lwf_amt, "usr": user[:30],
         "tag": PROCESS_TAG, "y": f.year, "m": f.month}
    W = "w.CompCode = :c AND w.Location = :l AND w.UnitCode = :u AND w.PCode = :p AND w.EDate = :t"

    migrated = db.execute(text(f"""
        SELECT COUNT(*) FROM paywages w WHERE {W} AND IFNULL(w.PCName, '') <> :tag AND w.NetPayable <> 0
    """), k).scalar()
    if migrated:
        raise HTTPException(status_code=409,
                            detail=f"Period {pcode} already holds {migrated} paid wage rows that were not "
                                   f"created by this process; it cannot be re-processed")

    # ── 0 daily attendance -> pay_attendance (legacy ATTEN; 1:1 with the approved daily rows) ──
    db.execute(text("DELETE FROM pay_attendance WHERE branch_id = :b AND attendance_date BETWEEN :f AND :t"), k)
    db.execute(text("""
        INSERT INTO pay_attendance
            (attendance_date, spell_id, eb_id, dept_id, desig_id, mech_codes, att_type, branch_id, manual,
             shift_hr, working_hrs, idle_hrs, ns_hrs, FBasic_Amt, VBasic_Amt, DA_Amt, NS_Amt, OT_Amt,
             BeamChange_Amt, Incentive_Amt, MiscEarn, Oil_Amt, HRA_Amt, HeadCount, Reason, updated_by,
             updated_date_time)
        SELECT d.attendance_date, d.spell_id, d.eb_id, d.worked_department_id, d.worked_designation_id, mc.codes,
               d.attendance_type, d.branch_id, 1, IFNULL(d.spell_hours, 0),
               -- working_hours is gross (Work_HR + GP_HR); pay_attendance keeps the legacy net Work_HR
               IFNULL(d.working_hours, 0) - IFNULL(d.idle_hours, 0), IFNULL(d.idle_hours, 0),
               -- night allowance: half an hour per full 7.5-hour night shift, pro rata (legacy Atten.Night_HR:
               -- 7.5 -> 0.50, 7 -> 0.47, 8 -> 0.53 whatever the shift's own hours)
               IF(sp.spell_code IN ('C', 'C2', 'G3') AND d.working_hours - IFNULL(d.idle_hours, 0) > 0,
                  ROUND(0.5 * (d.working_hours - IFNULL(d.idle_hours, 0)) / 7.5, 2), 0),
               0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
               IF(d.spell_hours > 0, ROUND((d.working_hours - IFNULL(d.idle_hours, 0)) / d.spell_hours, 2), 0), '', :uid, NOW()
        FROM daily_attendance d LEFT JOIN spell_mst sp ON sp.spell_id = d.spell_id
        -- machines aggregated once for the period (a per-row subquery here ran ~3 min: MySQL scanned
        -- daily_ebmc_attendance for every row); machine rows are found through their parent
        LEFT JOIN (SELECT e.daily_atten_id, GROUP_CONCAT(m.mech_code ORDER BY m.mech_code) codes
                   FROM daily_ebmc_attendance e
                   JOIN daily_attendance p ON p.daily_atten_id = e.daily_atten_id AND p.branch_id = :b
                        AND p.attendance_date BETWEEN :f AND :t
                   JOIN machine_mst m ON m.machine_id = e.mc_id
                   WHERE e.is_active = 1 GROUP BY e.daily_atten_id) mc ON mc.daily_atten_id = d.daily_atten_id
        WHERE d.branch_id = :b AND d.attendance_date BETWEEN :f AND :t AND d.is_active = 1
          AND d.attendance_type IN ('R', 'O') AND CAST(d.status_id AS UNSIGNED) = 3
    """), {**k, "uid": int(user) if str(user).isdigit() else 0})

    # Rates in force at the cut-off: latest effective row; the active row wins a same-date tie.
    db.execute(text("DROP TEMPORARY TABLE IF EXISTS _wp_rate"))
    db.execute(text("""
        CREATE TEMPORARY TABLE _wp_rate (PRIMARY KEY (eb_id)) AS
        SELECT eb_id, fbasic, fbasic_hr, da_all, da_rate, hra, hrd, quarter, pf, esi, ptax FROM (
            SELECT r.*, ROW_NUMBER() OVER (PARTITION BY eb_id
                   ORDER BY effective_date DESC, is_active DESC, worker_rate_id DESC) rn
            FROM worker_rate_mst r WHERE effective_date <= :cut) x
        WHERE rn = 1
    """), k)

    # ── 1 _Daily: rates into pay_attendance ───────────────────────────────
    ATT = "a.branch_id = :b AND a.attendance_date BETWEEN :f AND :t"
    db.execute(text(f"""
        UPDATE pay_attendance a SET a.FBasic_Amt = 0, a.VBasic_Amt = 0, a.DA_Amt = 0, a.NS_Amt = 0,
               a.OT_Amt = 0, a.BeamChange_Amt = 0, a.MiscEarn = 0, a.Oil_Amt = 0, a.HRA_Amt = 0
        WHERE {ATT}
    """), k)  # Incentive_Amt is owned by the incentive screens — not reset (legacy comments it out)
    # legacy OcpCode per designation (designation_mst.occu_code) + its PayOWagesRate_OCP rate, latest
    # EFFDate on or before the period start
    db.execute(text("DROP TEMPORARY TABLE IF EXISTS _wp_ocp"))
    db.execute(text(f"""
        CREATE TEMPORARY TABLE _wp_ocp (PRIMARY KEY (designation_id)) AS
        SELECT dm.designation_id, dm.occu_code {UCI} ocp,
               (SELECT r.Rate FROM PayOWagesRate_OCP r WHERE r.OcpCode = dm.occu_code {UCI} AND r.EFFDate <= :f
                ORDER BY r.EFFDate DESC LIMIT 1) rate
        FROM designation_mst dm WHERE dm.occu_code <> ''
    """), k)
    # FBasic (legacy #PayOWagesRate): the employee's PayOWagesRate row with the latest EffDate on or
    # before the cut-off. Rows of a worker without one keep FBasic_Amt = 0, as in legacy.
    db.execute(text("DROP TEMPORARY TABLE IF EXISTS _wp_fbasic"))
    db.execute(text("""
        CREATE TEMPORARY TABLE _wp_fbasic (PRIMARY KEY (eb_id)) AS
        SELECT p.eb_id, MAX(p.FBasic) fbasic, MAX(p.FBasic_HR) fbasic_hr FROM PayOWagesRate p
        JOIN (SELECT eb_id, MAX(EffDate) me FROM PayOWagesRate WHERE EffDate <= :cut AND eb_id IS NOT NULL
              GROUP BY eb_id) m ON m.eb_id = p.eb_id AND m.me = p.EffDate
        GROUP BY p.eb_id
    """), k)
    # Occupation rate when the worked occupation has one, else the employee's FBasic — groups 02 / 03
    # (piece-rated) only: staff FBasic_HR is monthly, so an occupation rate over it would be nonsense.
    db.execute(text(f"""
        UPDATE pay_attendance a JOIN _wp_fbasic r ON r.eb_id = a.eb_id
        LEFT JOIN _wp_ocp q ON q.designation_id = a.desig_id
        LEFT JOIN hrms_ed_official_details o ON o.eb_id = a.eb_id AND o.active = 1
        LEFT JOIN category_mst g ON g.cata_id = o.catagory_id
        SET a.FBasic_Amt = ROUND(IF(LEFT(g.cata_desc, 2) IN ('02', '03'), IFNULL(q.rate, r.fbasic), r.fbasic)
                                 / r.fbasic_hr * a.working_hrs, 2)
        WHERE {ATT} AND a.att_type IN ('R', 'O') AND r.fbasic_hr > 0
    """), k)
    db.execute(text(f"""
        UPDATE pay_attendance a JOIN _wp_rate r ON r.eb_id = a.eb_id
        SET a.DA_Amt = ROUND(r.da_rate / r.fbasic_hr * a.working_hrs, 2)
        WHERE {ATT} AND a.att_type IN ('R', 'O') AND r.fbasic_hr > 0 AND r.da_all = 'Y'
    """), k)
    db.execute(text(f"""
        UPDATE pay_attendance a
        SET a.NS_Amt = ROUND((a.FBasic_Amt + a.DA_Amt + a.VBasic_Amt) / a.working_hrs * a.ns_hrs, 2)
        WHERE {ATT} AND a.att_type = 'R' AND a.working_hrs > 0
    """), k)
    db.execute(text(f"""
        UPDATE pay_attendance a JOIN _wp_rate r ON r.eb_id = a.eb_id
        SET a.OT_Amt = ROUND((a.FBasic_Amt / r.fbasic_hr + a.DA_Amt / r.fbasic_hr) * a.working_hrs, 2)
        WHERE {ATT} AND a.att_type = 'O' AND r.fbasic_hr > 0
    """), k)  # sic — legacy formula
    db.execute(text(f"""
        UPDATE pay_attendance a
        JOIN sub_dept_mst s ON s.sub_dept_id = a.dept_id JOIN dept_mst d ON d.dept_id = s.dept_id
        JOIN hrms_ed_official_details o ON o.eb_id = a.eb_id AND o.active = 1
        JOIN category_mst g ON g.cata_id = o.catagory_id
        SET a.BeamChange_Amt = ROUND(0.35 * a.working_hrs, 2)
        WHERE {ATT} AND a.att_type = 'R' AND d.dept_code = '07' AND LEFT(g.cata_desc, 2) = '07'
    """), k)  # 07 = beaming dept & group
    for col, codes, rate, night in OCP_ALLOWANCES:
        db.execute(text(f"""
            UPDATE pay_attendance a JOIN _wp_ocp q ON q.designation_id = a.desig_id
            JOIN sub_dept_mst s ON s.sub_dept_id = a.dept_id JOIN dept_mst d ON d.dept_id = s.dept_id
            SET a.{col} = ROUND({rate} * (a.working_hrs{" + a.ns_hrs" if night else ""}), 2)
            WHERE {ATT} AND a.att_type = 'R' AND q.ocp IN ({", ".join(repr(c) for c in codes)})
              AND d.dept_code {UCI} = LEFT(q.ocp, 2)
        """), k)

    # ── 2 _GetAtten: one paywages row per employee ────────────────────────
    db.execute(text(f"DELETE w FROM paywages w WHERE {W}"), k)
    db.execute(text("DROP TEMPORARY TABLE IF EXISTS _wp_att"))
    db.execute(text(f"""
        CREATE TEMPORARY TABLE _wp_att (PRIMARY KEY (eb_id)) AS
        SELECT a.eb_id,
               MAX(CASE WHEN a.att_type = 'R' THEN d.dept_code END) dept_code,
               SUM(CASE WHEN a.att_type = 'R' THEN a.working_hrs ELSE 0 END) work_hr,
               SUM(CASE WHEN a.att_type = 'O' THEN a.working_hrs ELSE 0 END) ot_hr,
               SUM(CASE WHEN a.att_type = 'R' THEN a.idle_hrs ELSE 0 END) gp_hr,
               SUM(CASE WHEN a.att_type = 'R' AND sp.spell_code IN ('C', 'C2', 'G3') THEN a.ns_hrs ELSE 0 END) ns_hr
        FROM pay_attendance a
        LEFT JOIN sub_dept_mst s ON s.sub_dept_id = a.dept_id LEFT JOIN dept_mst d ON d.dept_id = s.dept_id
        LEFT JOIN spell_mst sp ON sp.spell_id = a.spell_id
        WHERE {ATT} AND a.att_type IN ('R', 'O')
        GROUP BY a.eb_id HAVING SUM(a.working_hrs) > 0
    """), k)
    # manual hour / basic / DA adjustments of the fortnight (legacy PayM_AdjHR, keyed by eb_id here)
    db.execute(text("DROP TEMPORARY TABLE IF EXISTS _wp_adj"))
    db.execute(text("""
        CREATE TEMPORARY TABLE _wp_adj (PRIMARY KEY (eb_id)) AS
        SELECT eb_id, SUM(Adj_HR) hr, SUM(Adj_BSAmt) bs, SUM(Adj_DAAmt) da,
               CONCAT('/', MAX(DeptCode), '/', MAX(WShift)) ods
        FROM PayM_AdjHR WHERE FNEDate = :t AND eb_id IS NOT NULL GROUP BY eb_id
    """), k)
    db.execute(text("DROP TEMPORARY TABLE IF EXISTS _wp_hol"))
    db.execute(text("""
        CREATE TEMPORARY TABLE _wp_hol (PRIMARY KEY (eb_id)) AS
        SELECT t.eb_id, SUM(t.holiday_hours) hol_hr
        FROM hrms_holiday_transactions t JOIN holiday_master h ON h.holiday_id = t.holiday_id
        WHERE h.holiday_date BETWEEN :f AND :t AND IFNULL(h.status, 1) = 1
        GROUP BY t.eb_id
    """), k)

    emp = {  # explicit values; every other NOT NULL column of paywages gets 0 / '' (strict mode, no defaults)
        "CompCode": ":c", "Location": ":l", "UnitCode": ":u", "WYear": ":y", "WMonth": ":m", "WDay": ":wd",
        "PCode": ":p", "EDate": ":t", "period_id": ":pid", "branch_id": ":b", "DeptCode": "IFNULL(x.dept_code, '')", "ECode": "o.emp_code",
        "EName": "TRIM(CONCAT(IFNULL(pe.first_name, ''), ' ', IFNULL(pe.middle_name, ''), ' ', IFNULL(pe.last_name, '')))",
        "Grade": "'MILL-WORKMEN'", "EGroup": "IFNULL(g.cata_desc, '')", "DoB": "IFNULL(pe.date_of_birth, '1900-01-01')",
        "DoJ": "IFNULL(o.date_of_join, '1900-01-01')", "Active": "'Y'", "RestDay": "IFNULL(o.off_day, '')", "PaySlipType": "'WAGES'",
        "Work_HR": "IFNULL(x.work_hr, 0) + IFNULL(j.hr, 0)", "GP_HR": "IFNULL(x.gp_hr, 0)", "Holiday_HR": "IFNULL(h.hol_hr, 0)", "NS_HR": "IFNULL(x.ns_hr, 0)",
        "OT_HR": "IFNULL(x.ot_hr, 0)", "OFBasic_HR": "IFNULL(r.fbasic_hr, 208)", "ODA_HR": "IFNULL(r.fbasic_hr, 208)",
        "ODA_All": "IFNULL(r.da_all, 'N')", "OHRA_All": "IFNULL(r.hra, 'N')", "OPF": "IFNULL(r.pf, 'N')",
        "OESI": "IFNULL(r.esi, 'N')", "OPTax": "IFNULL(r.ptax, 'N')", "OQuarter": "IFNULL(r.quarter, 'N')",
        "OHRD_All": "IFNULL(r.hrd, 'N')", "BankName": "IFNULL(b.bank_name, '')",
        "Branch": "IFNULL(b.bank_branch_name, '')", "IFSC": "IFNULL(b.ifsc_code, '')",
        "AccNo": "IFNULL(b.bank_acc_no, '')", "BenificiaryName": "IFNULL(b.beneficiary_name, '')",
        "CreatedDate": "NOW()", "UpdatedDate": "NOW()", "PCName": ":tag", "UserID": ":usr", "UserName": ":usr",
        "OVBasic": "'N'", "ONS_All": "'N'", "OOT_All": "'N'", "OBeamChange_All": "'N'", "OIncentive": "'N'",
        "OExtra_All": "'N'", "OOil_All": "'N'", "OLWF": "'N'",
    }
    for col, dtype in db.execute(text(
            "SELECT column_name, data_type FROM information_schema.columns WHERE table_schema = DATABASE() "
            "AND table_name = 'paywages' AND is_nullable = 'NO' AND column_default IS NULL")):
        if col not in emp:
            emp[col] = "''" if dtype in ("varchar", "char") else "0"
    db.execute(text(f"""
        INSERT INTO paywages ({", ".join(emp)})
        SELECT {", ".join(emp.values())}
        FROM hrms_ed_official_details o
        LEFT JOIN _wp_att x ON x.eb_id = o.eb_id
        LEFT JOIN _wp_hol h ON h.eb_id = o.eb_id
        LEFT JOIN _wp_adj j ON j.eb_id = o.eb_id
        LEFT JOIN _wp_rate r ON r.eb_id = o.eb_id
        LEFT JOIN hrms_ed_personal_details pe ON pe.eb_id = o.eb_id
        LEFT JOIN category_mst g ON g.cata_id = o.catagory_id
        LEFT JOIN hrms_ed_bank_details b ON b.eb_id = o.eb_id AND b.active = 1
        WHERE o.active = 1 AND o.branch_id = :b AND o.emp_code IS NOT NULL AND o.emp_code <> ''
          AND (x.eb_id IS NOT NULL OR j.eb_id IS NOT NULL OR (h.eb_id IS NOT NULL AND h.hol_hr > 0))
    """), k)

    # Work_Day (legacy: from 16/02/2026, per (spell, shift hours) of DUTY rows, plus Adj_HR — sic, hours)
    db.execute(text(f"""
        UPDATE paywages w JOIN hrms_ed_official_details o ON o.emp_code {UCI} = w.ECode AND o.branch_id = :b
        JOIN (SELECT eb_id, SUM((working_hrs + ns_hrs) / shift_hr) wd
              FROM pay_attendance a WHERE {ATT} AND a.att_type = 'R' AND a.working_hrs > 0 AND a.shift_hr > 0
              GROUP BY eb_id) q ON q.eb_id = o.eb_id
        LEFT JOIN _wp_adj j ON j.eb_id = o.eb_id
        SET w.Work_Day = ROUND(q.wd + IFNULL(j.hr, 0), 2) WHERE {W}
    """), k)

    # ── 4 _GetRate ────────────────────────────────────────────────────────
    db.execute(text(f"""
        UPDATE paywages w SET w.TP = IF(LEFT(w.EGroup, 2) IN ('02', '03'), 'P', 'T'),
               w.C_P_Q = CONCAT(LEFT(w.EGroup, 2), '/ ', IF(w.OQuarter = 'Y', 'H', ' ')),
               w.OcpDptSft = '/  /'
        WHERE {W}
    """), k)
    db.execute(text(f"""
        UPDATE paywages w JOIN hrms_ed_official_details o ON o.emp_code {UCI} = w.ECode AND o.branch_id = :b
        JOIN (SELECT a.eb_id, CONCAT('/', MAX(d.dept_code), '/', MAX(sp.spell_code)) ods
              FROM pay_attendance a
              LEFT JOIN sub_dept_mst s ON s.sub_dept_id = a.dept_id LEFT JOIN dept_mst d ON d.dept_id = s.dept_id
              LEFT JOIN spell_mst sp ON sp.spell_id = a.spell_id
              WHERE {ATT} AND a.att_type = 'R' AND a.working_hrs > 0 GROUP BY a.eb_id) q ON q.eb_id = o.eb_id
        SET w.OcpDptSft = q.ods WHERE {W}
    """), k)
    db.execute(text(f"""
        UPDATE paywages w JOIN hrms_ed_official_details o ON o.emp_code {UCI} = w.ECode AND o.branch_id = :b
        JOIN _wp_adj j ON j.eb_id = o.eb_id
        SET w.OcpDptSft = j.ods WHERE {W} AND w.OcpDptSft = '/  /' AND j.hr > 0
    """), k)

    # Earnings from the daily amounts (DUTY rows only)
    db.execute(text(f"""
        UPDATE paywages w JOIN hrms_ed_official_details o ON o.emp_code {UCI} = w.ECode AND o.branch_id = :b
        JOIN (SELECT eb_id, SUM(FBasic_Amt) fb, SUM(DA_Amt) da, SUM(NS_Amt) ns, SUM(BeamChange_Amt) bc,
                     SUM(MiscEarn) me, SUM(Oil_Amt) oil, SUM(Incentive_Amt) inc
              FROM pay_attendance a WHERE {ATT} AND a.att_type = 'R' GROUP BY eb_id) q ON q.eb_id = o.eb_id
        SET w.FBasic_Amt = q.fb, w.DA_Amt = q.da, w.NS_Amt = q.ns, w.OT_Amt = 0, w.BeamChange_Amt = q.bc,
            w.MiscEarn = q.me, w.Oil_Amt = q.oil, w.Incentive_Amt = q.inc,
            w.FBasic_Rate = IF(w.Work_HR > 0, q.fb / w.Work_HR, 0)
        WHERE {W}
    """), k)
    # + PayM_AdjHR basic / DA; workers with only an adjustment get their rate from it too
    db.execute(text(f"""
        UPDATE paywages w JOIN hrms_ed_official_details o ON o.emp_code {UCI} = w.ECode AND o.branch_id = :b
        JOIN _wp_adj j ON j.eb_id = o.eb_id
        SET w.FBasic_Amt = w.FBasic_Amt + j.bs, w.DA_Amt = w.DA_Amt + j.da WHERE {W}
    """), k)
    db.execute(text(f"""
        UPDATE paywages w JOIN hrms_ed_official_details o ON o.emp_code {UCI} = w.ECode AND o.branch_id = :b
        JOIN _wp_adj j ON j.eb_id = o.eb_id
        SET w.FBasic_Rate = IF(w.Work_HR > 0, w.FBasic_Amt / w.Work_HR, 0) WHERE {W}
    """), k)
    db.execute(text(f"""
        UPDATE paywages w JOIN hrms_ed_official_details o ON o.emp_code {UCI} = w.ECode AND o.branch_id = :b
        JOIN _wp_rate r ON r.eb_id = o.eb_id
        SET w.DA_Rate = IF(LEFT(w.EGroup, 2) = '05', 0, IF(r.da_all = 'Y', r.da_rate, 0))
        WHERE {W}
    """), k)
    # Holiday-only workers: hourly rates
    db.execute(text(f"""
        UPDATE paywages w JOIN hrms_ed_official_details o ON o.emp_code {UCI} = w.ECode AND o.branch_id = :b
        JOIN _wp_rate r ON r.eb_id = o.eb_id
        SET w.FBasic_Rate = r.fbasic / r.fbasic_hr,
            w.DA_Rate = IF(LEFT(w.EGroup, 2) = '05', 0, r.da_rate / r.fbasic_hr)
        WHERE {W} AND w.Work_HR = 0 AND w.Holiday_HR > 0 AND r.fbasic_hr > 0
    """), k)
    db.execute(text(f"UPDATE paywages w SET w.OFBasic = w.FBasic_Rate * w.OFBasic_HR, w.ODA_Rate = w.DA_Rate WHERE {W}"), k)

    db.execute(text(f"""
        UPDATE paywages w SET
          w.NS_Amt = IF(w.Work_HR > 0, (w.FBasic_Amt + w.VBasic_Amt + w.DA_Amt) / w.Work_HR * w.NS_HR, 0),
          w.Holiday_Amt = IF(w.Work_HR > 0, (w.FBasic_Amt + w.VBasic_Amt + w.DA_Amt) / w.Work_HR * w.Holiday_HR,
                             ROUND((w.FBasic_Rate + w.DA_Rate) * w.Holiday_HR, 2))
        WHERE {W}
    """), k)
    # manual PF / non-PF earning adjustments of the fortnight (PayM_AdjPF / PayM_AdjNPF)
    for tbl, col in (("PayM_AdjPF", "PFEarnAdj"), ("PayM_AdjNPF", "NPFEarnAdj")):
        db.execute(text(f"""
            UPDATE paywages w JOIN (SELECT ECode, SUM(Adj_Amt) amt FROM {tbl} WHERE FNEDate = :t GROUP BY ECode) a
              ON a.ECode = w.ECode {UCI}
            SET w.{col} = a.amt WHERE {W}
        """), k)
    # DA / HRA arrears not yet paid (1900-01-01 = legacy '') or paid by this period go into PFEarnAdj,
    # then are marked paid in this period (a re-run picks the same rows up again)
    arrear = "a.Paid_FNEDate IN ('1900-01-01', :t)"
    db.execute(text(f"""
        UPDATE paywages w JOIN (SELECT a.ECode, SUM(a.Arrear_Amt) amt FROM PayM_AdjArrear a WHERE {arrear}
                                GROUP BY a.ECode) a ON a.ECode = w.ECode
        SET w.PFEarnAdj = w.PFEarnAdj + a.amt WHERE {W}
    """), k)
    db.execute(text(f"""
        UPDATE PayM_AdjArrear a JOIN (SELECT DISTINCT w.ECode FROM paywages w WHERE {W}) p ON p.ECode = a.ECode
        SET a.Paid_FNEDate = :t, a.paid_period_id = :pid, a.UpdatedDate = NOW()
        WHERE {arrear}
    """), k)
    db.execute(text(f"""
        UPDATE paywages w SET
          w.PF_Gross = w.FBasic_Amt + w.VBasic_Amt + w.DA_Amt + w.NS_Amt + w.Holiday_Amt + w.STL_Amt
                       + w.PFEarnAdj + w.LostHR_Amt + w.LayOffHR_Amt,
          w.HRA_Gross = w.FBasic_Amt + w.VBasic_Amt + w.DA_Amt + w.NS_Amt + w.Holiday_Amt + w.STL_Amt
                       + w.PFEarnAdj + w.LostHR_Amt + w.LayOffHR_Amt
        WHERE {W}
    """), k)
    db.execute(text(f"UPDATE paywages w SET w.HRA_Rate = :hra, w.HRA_Amt = ROUND(w.HRA_Gross * :hra / 100, 0) "
                     f"WHERE {W} AND w.OHRA_All = 'Y'"), {**k, "hra": HRA_PCT})
    # Attendance allowance (legacy era from 16/02/2024)
    for groups, rate in ((("01", "02", "03", "07"), 1), (("04", "08", "09", "10", "14", "15"), 20)):
        db.execute(text(f"""
            UPDATE paywages w SET w.Atten_Amt = {rate} * ROUND((w.Work_HR + w.NS_HR) / 8, 0)
            WHERE {W} AND (w.Work_HR + w.NS_HR + w.Holiday_HR + w.LayOff_HR) >= 96
              AND LEFT(w.EGroup, 2) IN ({", ".join(repr(g) for g in groups)})
        """), k)
    gross = ("w.PF_Gross + w.NPFEarnAdj + w.HRA_Amt + w.MiscEarn + w.BeamChange_Amt + w.Incentive_Amt "
             "+ w.Extra_Amt + w.Oil_Amt + w.Atten_Amt")
    db.execute(text(f"""
        UPDATE paywages w SET w.ESI_Gross = {gross}, w.PTax_Gross = {gross}, w.Pension_Gross = ROUND(w.PF_Gross, 0),
          w.Wages_Gross = w.FBasic_Amt + w.VBasic_Amt + w.DA_Amt + w.Incentive_Amt + w.NS_Amt + w.Holiday_Amt
              + w.STL_Amt + w.PFEarnAdj + w.NPFEarnAdj + w.LostHR_Amt + w.LayOffHR_Amt + w.HRA_Amt + w.MiscEarn
              + w.BeamChange_Amt + w.Extra_Amt + w.Oil_Amt + w.Atten_Amt
        WHERE {W}
    """), k)

    # PF — monthly, both halves of the month
    month = {"y": t.year, "m": t.month}
    rows = db.execute(text(f"""
        SELECT w.ECode,
               SUM(w.PF_Gross) pf_gross,
               SUM(CASE WHEN w.WDay = '01' THEN w.PF_Gross ELSE 0 END) g1,
               SUM(CASE WHEN w.WDay = '01' THEN w.PFEmployee ELSE 0 END) pfe1,
               SUM(CASE WHEN w.WDay = '01' THEN w.Pension ELSE 0 END) f833,
               SUM(CASE WHEN w.WDay = '01' THEN w.CoC ELSE 0 END) f167,
               SUM(CASE WHEN w.WDay = '02' THEN w.PF_Gross ELSE 0 END) g2
        FROM paywages w
        WHERE w.CompCode = :c AND w.Location = :l AND w.Grade = 'MILL-WORKMEN' AND w.OPF = 'Y'
          AND YEAR(w.EDate) = :y AND MONTH(w.EDate) = :m AND LEFT(w.EGroup, 2) <> '05'
          AND w.ECode IN (SELECT ECode FROM paywages w WHERE {W})
        GROUP BY w.ECode
    """), {**k, **month}).fetchall()
    pf_rows = []
    for r in rows:
        first, second = _pf_split(*(float(v or 0) for v in r[1:]))
        pf_rows.append((r[0], *(first if wday == "01" else second)))
    _bulk_apply(db, "_wp_pf", "(ECode VARCHAR(20) NOT NULL PRIMARY KEY, pf DOUBLE, pen DOUBLE, coc DOUBLE)",
                "(:e, :a, :b, :c2)", [{"e": e, "a": a, "b": b, "c2": c2} for e, a, b, c2 in pf_rows],
                f"""UPDATE paywages w JOIN _wp_pf q ON q.ECode = w.ECode {UCI}
                    SET w.PFEmployee = q.pf, w.Pension = q.pen, w.CoC = q.coc
                    WHERE {W} AND w.OPF = 'Y' AND w.PaySlipType = 'WAGES'""", k)
    # no UAN -> no pension share; age >= 58 at period start -> whole PF goes to CoC
    db.execute(text(f"""
        UPDATE paywages w JOIN hrms_ed_official_details o ON o.emp_code {UCI} = w.ECode AND o.branch_id = :b
        LEFT JOIN hrms_ed_pf pf ON pf.eb_id = o.eb_id AND pf.active = 1
        SET w.Pension = 0 WHERE {W} AND w.OPF = 'Y' AND IFNULL(pf.pf_uan_no, '') = ''
    """), k)
    db.execute(text(f"""
        UPDATE paywages w JOIN hrms_ed_official_details o ON o.emp_code {UCI} = w.ECode AND o.branch_id = :b
        JOIN hrms_ed_pf pf ON pf.eb_id = o.eb_id AND pf.active = 1 AND pf.pension_date IS NOT NULL
        SET w.Pension = 0, w.CoC = w.PFEmployee
        WHERE {W} AND w.OPF = 'Y' AND FLOOR(DATEDIFF(:f, pf.pension_date) / 365.25) >= 58
    """), k)

    # ESI
    if f.day == 16:  # 2nd half: month total less what the 1st half already took
        db.execute(text(f"""
            UPDATE paywages w JOIN (
                SELECT m.ECode, CEILING(SUM(m.ESI_Gross) * 0.75 / 100) esi2,
                       IFNULL(SUM(CASE WHEN DAY(m.EDate) = 15 THEN m.ESI_Amt END), 0) esi1
                FROM paywages m
                WHERE m.CompCode = :c AND m.Location = :l AND m.Grade = 'MILL-WORKMEN'
                  AND YEAR(m.EDate) = :y AND MONTH(m.EDate) = :m
                GROUP BY m.ECode
                HAVING SUM(m.Wages_Gross) > 0 AND SUM(m.Work_HR + m.NS_HR + m.Holiday_HR + m.STL_HR) > 0
                   AND SUM(m.ESI_Gross) / SUM(m.Work_HR + m.NS_HR + m.Holiday_HR + m.STL_HR) * 8 > 173
            ) q ON q.ECode = w.ECode
            SET w.ESI_Amt = q.esi2 - q.esi1, w.ESIC = 0
            WHERE {W} AND w.OESI = 'Y'
        """), {**k, **month})  # ESIC = ESIC2 - ESIC2 = 0 in legacy
    else:
        db.execute(text(f"""
            UPDATE paywages w SET w.ESI_Amt = CEILING(w.ESI_Gross * 0.75 / 100), w.ESIC = CEILING(w.ESI_Gross * 3.25 / 100)
            WHERE {W} AND w.OESI = 'Y' AND (w.Work_HR + w.NS_HR + w.Holiday_HR + w.STL_HR) > 0
              AND w.ESI_Gross / (w.Work_HR + w.NS_HR + w.Holiday_HR + w.STL_HR) * 8 > 173
        """), k)

    # Professional tax: slab on the month's wages gross so far; 2nd half pays the balance. By EDate, not
    # PCode: a 1st-half re-run must not count an already processed 2nd half (legacy runs them in order)
    pt_rows = db.execute(text(f"""
        SELECT w.ECode, (SELECT SUM(m.Wages_Gross) FROM paywages m WHERE m.ECode = w.ECode
                         AND YEAR(m.EDate) = :y AND MONTH(m.EDate) = :m AND m.EDate <= :t) bamt,
               (SELECT IFNULL(SUM(m.PTax_Amt), 0) FROM paywages m WHERE m.ECode = w.ECode AND m.WDay = '01'
                         AND YEAR(m.EDate) = :y AND MONTH(m.EDate) = :m AND m.EDate < :t) paid
        FROM paywages w WHERE {W} AND w.OPTax = 'Y'
    """), {**k, **month}).fetchall()
    slabs = _ptax_slabs(db, loc, f)
    _bulk_apply(db, "_wp_ptax", "(ECode VARCHAR(20) NOT NULL PRIMARY KEY, bamt DOUBLE, tax DOUBLE)",
                "(:e, :b, :t2)",
                [{"e": r.ECode, "b": float(r.bamt or 0),
                  "t2": _ptax(float(r.bamt or 0), slabs) - (float(r.paid) if wday == "02" else 0)} for r in pt_rows],
                f"""UPDATE paywages w JOIN _wp_ptax q ON q.ECode = w.ECode {UCI}
                    SET w.PTax_BAmt = q.bamt, w.PTax_Amt = q.tax WHERE {W} AND w.OPTax = 'Y'""", k)

    db.execute(text(f"UPDATE paywages w SET w.LWF_Amt = :lwf, w.UTHWAdv = 0 WHERE {W}"), k)
    db.execute(text(f"UPDATE paywages w SET w.HRDeduction = ROUND(w.HRA_Gross * 3.75 / 100, 0) "
                     f"WHERE {W} AND w.OHRA_All = 'Y' AND w.OHRD_All = 'Y'"), k)
    _apply_loans(db, comp, loc, k, W, t)
    db.execute(text(f"""
        UPDATE paywages w SET
          w.TotalDeduction = w.PFEmployee + w.ESI_Amt + w.PTax_Amt + w.LWF_Amt + w.STLAdv + w.PFLoanCap
                             + w.PFLoanInt + w.SplAdvance + w.Advance + w.Electricity + w.HRDeduction,
          w.BF = 0, w.CF = 0
        WHERE {W}
    """), k)
    db.execute(text(f"""
        UPDATE paywages w SET w.NetPay = (w.Wages_Gross + w.BF) - w.TotalDeduction,
          w.ROff = ROUND((w.Wages_Gross + w.BF) - w.TotalDeduction, 0) - ((w.Wages_Gross + w.BF) - w.TotalDeduction),
          w.NetPayable = ROUND((w.Wages_Gross + w.BF) - w.TotalDeduction, 0)
        WHERE {W}
    """), k)
    # Electricity recovery (2nd half only): bills (PayM_Elec) less everything recovered so far, at most
    # the net pay and 200 a fortnight; then deductions / net again
    if wday == "02":
        db.execute(text(f"""
            UPDATE paywages w JOIN (
                SELECT e.ECode, SUM(e.TotalAmt) - IFNULL((SELECT SUM(p.Electricity) FROM paywages p
                       WHERE p.ECode = e.ECode AND p.Electricity <> 0 AND p.EDate <= :t), 0) due
                FROM PayM_Elec e WHERE e.EDate <= :t
                  AND e.ECode IN (SELECT w2.ECode FROM paywages w2 WHERE {W.replace("w.", "w2.")})
                GROUP BY e.ECode) x ON x.ECode = w.ECode
            SET w.Electricity = LEAST(IF(w.NetPay > x.due, x.due, w.NetPay), 200)
            WHERE {W}
        """), k)
        db.execute(text(f"""
            UPDATE paywages w SET
              w.TotalDeduction = w.PFEmployee + w.ESI_Amt + w.PTax_Amt + w.LWF_Amt + w.STLAdv + w.PFLoanCap
                                 + w.PFLoanInt + w.SplAdvance + w.Advance + w.Electricity + w.HRDeduction
            WHERE {W}
        """), k)
        db.execute(text(f"""
            UPDATE paywages w SET w.NetPay = (w.Wages_Gross + w.BF) - w.TotalDeduction,
              w.ROff = ROUND((w.Wages_Gross + w.BF) - w.TotalDeduction, 0) - ((w.Wages_Gross + w.BF) - w.TotalDeduction),
              w.NetPayable = ROUND((w.Wages_Gross + w.BF) - w.TotalDeduction, 0)
            WHERE {W}
        """), k)

    # ── 6 numbering (parent SP: SrlNo overall, SlNo within department) ────
    db.execute(text(f"""
        UPDATE paywages w JOIN (
            SELECT ECode, ROW_NUMBER() OVER (ORDER BY DeptCode, OcpDptSft, C_P_Q, ECode) srl,
                   ROW_NUMBER() OVER (PARTITION BY DeptCode ORDER BY OcpDptSft, C_P_Q, ECode) sl
            FROM paywages w WHERE {W}) q ON q.ECode = w.ECode
        SET w.SrlNo = q.srl, w.SlNo = q.sl, w.UpdatedDate = NOW()
        WHERE {W}
    """), k)

    s = db.execute(text(f"""
        SELECT COUNT(*) n, IFNULL(SUM(w.Wages_Gross), 0) gross, IFNULL(SUM(w.TotalDeduction), 0) ded,
               IFNULL(SUM(w.NetPayable), 0) net
        FROM paywages w WHERE {W}
    """), k).fetchone()
    return {"period": pcode, "from_date": f.isoformat(), "to_date": t.isoformat(),
            "employees": int(s.n), "wages_gross": float(s.gross), "total_deduction": float(s.ded),
            "net_payable": float(s.net)}


# ─── Endpoints ─────────────────────────────────────────────────────────────


@router.get("/wages_process_setup")
def wages_process_setup(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Wages (P) periods of the branch with how many rows each already holds."""
    branch_id = request.query_params.get("branch_id")
    comp, loc = _scope(branch_id)
    periods = db.execute(text("""
        SELECT pp.ID AS id, pp.code, pp.name, pp.FROM_DATE AS from_date, pp.TO_DATE AS to_date,
               (SELECT COUNT(*) FROM paywages w WHERE w.CompCode = :c AND w.Location = :l
                  AND w.PCode = pp.code COLLATE utf8mb4_unicode_ci AND w.EDate = pp.TO_DATE) AS row_count,
               (SELECT COUNT(*) FROM paywages w WHERE w.CompCode = :c AND w.Location = :l
                  AND w.PCode = pp.code COLLATE utf8mb4_unicode_ci AND w.EDate = pp.TO_DATE AND IFNULL(w.PCName, '') <> :tag) AS legacy_rows
        FROM pay_period pp
        WHERE pp.branch_id = :b AND pp.code LIKE 'P%' AND pp.FROM_DATE >= :min
        ORDER BY pp.FROM_DATE DESC, pp.ID DESC
    """), {"b": int(branch_id), "c": comp, "l": loc, "tag": PROCESS_TAG, "min": MIN_FROM_DATE})
    return {"data": {"periods": _json_rows(periods), "unit_code": UNIT_CODE}}


# A run takes minutes — longer than the web proxy waits — so POST only starts it in a background
# thread; the page polls /wages_process_status. ponytail: state is per server process (single worker);
# move to a table if the API is ever run with several workers.
_JOBS: dict[int, dict] = {}
_JOBS_LOCK = threading.Lock()


def _run_job(engine, branch_id: int, period_id: int, lwf: float, user: str) -> None:
    db = Session(engine, autoflush=False)
    try:
        result = run_wages_process(db, branch_id, period_id, lwf, user)
        db.commit()
        state = {"state": "done", "message": "Wages Processed ..", "data": result}
    except HTTPException as e:
        db.rollback()
        state = {"state": "error", "message": str(e.detail)}
    except Exception as e:  # noqa: BLE001 — surfaced to the page
        db.rollback()
        state = {"state": "error", "message": f"Wages processing failed: {e}"}
    finally:
        db.close()
    with _JOBS_LOCK:
        _JOBS[period_id] = {**state, "finished": datetime.now().isoformat(timespec="seconds")}


@router.post("/wages_process_run")
def wages_process_run(
    request: Request,
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
    _scope(branch_id)
    with _JOBS_LOCK:
        if _JOBS.get(period_id, {}).get("state") == "running":
            raise HTTPException(status_code=409, detail="This period is already being processed")
        _JOBS[period_id] = {"state": "running", "started": datetime.now().isoformat(timespec="seconds")}
    engine = get_tenant_engine(extract_subdomain_from_request(request))
    threading.Thread(target=_run_job, daemon=True,
                     args=(engine, branch_id, period_id, lwf, str((token_data or {}).get("user_id") or ""))).start()
    return {"message": "Wages processing started", "data": {"state": "running"}}


@router.get("/wages_process_status")
def wages_process_status(
    request: Request,
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """State of the last run of a period in this server process: idle | running | done | error."""
    try:
        period_id = int(request.query_params.get("period_id"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="period_id is required")
    with _JOBS_LOCK:
        job = dict(_JOBS.get(period_id) or {"state": "idle"})
    return {"data": job}


# ─── Process (1): data collection ──────────────────────────────────────────
# Runs wages_data_collection.sql (the mill's step-by-step collection script, kept next to this
# module) for one period: one INSERT per step into nbjcl_wages_data_collection.
_COLLECTION_SQL = Path(__file__).with_name("wages_data_collection.sql")
# The script's own period variables are replaced by the period picked on the page.
_SCRIPT_VARS = re.compile(r"SET\s+@(branch_id|from_date|to_date|period_id|lwf_amt)\b", re.I)


def run_wages_data_collection(db: Session, branch_id: int, period_id: int, lwf_amt: float = 0) -> dict:
    """Collect, calculate and write the period's paywages rows (the script does all three, each
    calculation as its own tagged rows in the collection table). Returns the rows per step and
    the period totals. Caller commits."""
    # ponytail: the script hardcodes CompCode 'NJB' / Location 'FACTORY' for the legacy loan tables,
    # so only that scope is accepted; parameterise the literals when a second mill needs it.
    if _scope(branch_id) != ("NJB", "FACTORY"):
        raise HTTPException(status_code=400, detail="Data collection is set up for the NJB factory branch only")
    p = _period(db, period_id, branch_id)
    # The script's last step rewrites the period's paywages rows; it only replaces rows this
    # screen created, so a period holding migrated wage rows is refused up front.
    migrated = db.execute(text("""
        SELECT COUNT(*) FROM paywages WHERE CompCode = 'NJB' AND Location = 'FACTORY' AND UnitCode = :u
          AND PCode = :p AND EDate = :t AND IFNULL(PCName, '') <> :tag
    """), {"u": UNIT_CODE, "p": p["code"], "t": p["to_date"], "tag": PROCESS_TAG}).scalar()
    if migrated:
        raise HTTPException(status_code=409,
                            detail=f"Period {p['code']} already holds {migrated} wage rows that were not "
                                   f"created by this process; it cannot be re-processed")
    lines = [ln for ln in _COLLECTION_SQL.read_text(encoding="utf-8").splitlines()
             if not ln.lstrip().startswith("--")]
    # the script is written against the nbjcl schema; run it in the tenant's own database
    statements = [st.strip() for st in "\n".join(lines).replace("nbjcl.", "").split(";") if st.strip()]
    conn = db.connection()  # one connection: the script relies on @variables and temporary tables
    conn.exec_driver_sql("SET @branch_id = %s, @from_date = %s, @to_date = %s, @period_id = %s, @lwf_amt = %s",
                         (branch_id, p["from_date"], p["to_date"], p["id"], lwf_amt))
    steps: list[dict] = []
    for st in statements:
        if _SCRIPT_VARS.match(st):
            continue
        result = conn.exec_driver_sql(st)
        if result.returns_rows:  # the closing check query
            steps = _json_rows(result)
    tot = db.execute(text("""
        SELECT COUNT(*) n, IFNULL(SUM(Wages_Gross), 0) gross, IFNULL(SUM(TotalDeduction), 0) ded,
               IFNULL(SUM(NetPayable), 0) net
        FROM paywages WHERE CompCode = 'NJB' AND Location = 'FACTORY' AND UnitCode = :u
          AND PCode = :p AND EDate = :t
    """), {"u": UNIT_CODE, "p": p["code"], "t": p["to_date"]}).fetchone()
    return {"steps": steps,
            "summary": {"period": p["code"], "employees": int(tot.n), "wages_gross": float(tot.gross),
                        "total_deduction": float(tot.ded), "net_payable": float(tot.net)}}


@router.post("/wages_data_collection_run")
def wages_data_collection_run(
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
    try:
        result = run_wages_data_collection(db, branch_id, period_id, lwf)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:  # noqa: BLE001 — surfaced to the page
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Data collection failed: {e}")
    return {"message": "Wages Processed ..", "data": result}


@router.get("/wages_process_result")
def wages_process_result(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Processed rows of one period (read-only grid under the Process button)."""
    branch_id = request.query_params.get("branch_id")
    comp, loc = _scope(branch_id)
    p = _period(db, request.query_params.get("period_id"), int(branch_id))
    page = max(int(request.query_params.get("page", 1)), 1)
    limit = min(max(int(request.query_params.get("limit", 50)), 1), 500)
    search = (request.query_params.get("search") or "").strip()
    args = {"c": comp, "l": loc, "p": p["code"], "t": p["to_date"], "q": search, "s": f"%{search}%",
            "lim": limit, "off": (page - 1) * limit}
    where = ("CompCode = :c AND Location = :l AND PCode = :p AND EDate = :t "
             "AND (:q = '' OR ECode LIKE :s OR EName LIKE :s)")
    total = db.execute(text(f"SELECT COUNT(*) FROM paywages WHERE {where}"), args).scalar()
    rows = db.execute(text(f"""
        SELECT ECode AS ecode, EName AS ename, EGroup AS egroup, DeptCode AS dept_code, Work_HR AS work_hr,
               NS_HR AS ns_hr, Holiday_HR AS holiday_hr, Wages_Gross AS wages_gross, PFEmployee AS pf,
               ESI_Amt AS esi, PTax_Amt AS ptax, TotalDeduction AS total_deduction, NetPayable AS net_payable
        FROM paywages WHERE {where} ORDER BY SrlNo, ECode LIMIT :lim OFFSET :off
    """), args)
    totals = db.execute(text(f"""
        SELECT IFNULL(SUM(Wages_Gross), 0) AS wages_gross, IFNULL(SUM(TotalDeduction), 0) AS total_deduction,
               IFNULL(SUM(NetPayable), 0) AS net_payable FROM paywages WHERE {where}
    """), args)
    return {"data": _json_rows(rows), "total": int(total or 0), "totals": _json_rows(totals)[0]}


# Columns of the printed Wages Register / Excel export, in paywages naming.
EXPORT_COLUMNS = (
    "RecNo", "ECode", "EName", "EGroup", "DeptCode", "TP", "C_P_Q", "Work_Day", "Work_HR", "NS_HR", "Holiday_HR",
    "STL_HR", "Lost_HR", "FBasic_Rate", "DA_Rate", "FBasic_Amt", "VBasic_Amt", "DA_Amt", "NS_Amt", "Holiday_Amt",
    "STL_Amt", "LostHR_Amt", "PFEarnAdj", "NPFEarnAdj", "MiscEarn", "Incentive_Amt", "Atten_Amt", "PF_Gross",
    "HRA_Amt", "Wages_Gross", "PFEmployee", "CoC", "Pension", "ESI_Amt", "PTax_Amt", "LWF_Amt", "HRDeduction",
    "STLAdv", "Advance", "SplAdvance", "PFLoanCap", "PFLoanInt", "Electricity", "TotalDeduction", "NetPay",
    "ROff", "NetPayable", "YTD_Days", "YTD_PFGross", "YTD_PFEmployee", "YTD_Pension", "YTD_FPF", "YTD_LoanAmt",
    "YTD_IntAmt",
)


@router.get("/wages_process_export")
def wages_process_export(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Every processed row of one period (no paging) for the Excel / PDF wages register."""
    branch_id = request.query_params.get("branch_id")
    comp, loc = _scope(branch_id)
    p = _period(db, request.query_params.get("period_id"), int(branch_id))
    rows = db.execute(text(f"""
        SELECT {", ".join(EXPORT_COLUMNS)} FROM paywages
        WHERE CompCode = :c AND Location = :l AND PCode = :p AND EDate = :t
        ORDER BY SrlNo, ECode
    """), {"c": comp, "l": loc, "p": p["code"], "t": p["to_date"]})
    return {"data": _json_rows(rows), "period": {"code": p["code"], "name": p["name"],
                                                 "from_date": p["from_date"].isoformat(),
                                                 "to_date": p["to_date"].isoformat()}}


def wages_payslip_rows(db: Session, branch_id: int, period_id: int) -> tuple[dict, list[dict]]:
    """Rows of the legacy 'WagesSlip' query (TBLF5) for one period, in legacy column names and
    print order. PayOEMP's bank / UAN / ESI come from the HRMS masters; the card number (RecNo)
    is not kept there, so a blank one falls back to the worker's latest earlier slip."""
    comp, loc = _scope(branch_id)
    p = _period(db, period_id, branch_id)
    rows = db.execute(text("""
        SELECT CONCAT('A/C No. : ', IFNULL(b.bank_acc_no, '')) AS ACNo,
               CONCAT('IFSC: ', IFNULL(b.ifsc_code, '')) AS IFSC,
               CONCAT('UAN: ', IFNULL(pf.uan, '')) AS UAN,
               w.EDate, w.SlNo AS SNo,
               IF(w.RecNo <> '', w.RecNo, IFNULL((SELECT pr.RecNo FROM paywages pr WHERE pr.ECode = w.ECode
                    AND pr.RecNo <> '' ORDER BY pr.EDate DESC LIMIT 1), '')) AS RecNo,
               w.EName, w.TP, w.ECode AS CNo, w.OcpDptSft, w.C_P_Q AS CPQ, IFNULL(esi.esi_no, '') AS ESINo,
               0 AS Prod, w.Work_Day, w.Work_HR, w.NS_HR, 0 AS FB_HR, w.Holiday_HR, w.Lost_HR, 0 AS OT_HR,
               w.LayOff_HR, w.OFBasic AS BasicRate, w.ODA_Rate AS DARate, w.VBasic_Amt AS Basic,
               w.FBasic_Amt AS FBasic, w.AdjBasic, w.DA_Amt, w.NS_Amt, w.Holiday_Amt, w.LayOffHR_Amt, w.STL_Amt,
               w.Increment, w.PFEarnAdj, w.PF_Gross, w.Incentive_Amt, w.OT_Amt, w.NPFEarnAdj, w.HRA_Amt,
               (w.MiscEarn + w.BeamChange_Amt + w.Oil_Amt) AS MiscEarn, w.Atten_Amt, w.Wages_Gross AS TotalGross,
               w.PFEmployee, w.ESI_Amt, w.PTax_Amt, w.LWF_Amt, w.HRDeduction, w.STLAdv, w.Advance, w.UTHWAdv,
               w.PFLoanCap, w.PFLoanInt, 0 AS PFDedAdj, w.Electricity AS NPFDedAdj, w.TotalDeduction, w.NetPay,
               w.BF, w.CF, w.NetPayable, IFNULL(el.units, 0) AS ElecMeter, w.STL_HR / 8 AS STL_Days,
               w.YTD_Pension AS PenBal, w.YTD_FPF AS COC, w.YTD_Days, w.YTD_PFGross, w.YTD_BNSGrs AS YTD_BnsGrs,
               w.YTD_LoanAmt AS PFLoanBal, w.YTD_IntAmt AS PFIntBal, 0 AS SPLAdvBal, w.DeptCode AS PB
        FROM paywages w
        LEFT JOIN hrms_ed_official_details o
               ON o.emp_code COLLATE utf8mb4_unicode_ci = w.ECode AND o.branch_id = :b AND o.active = 1
        LEFT JOIN hrms_ed_bank_details b ON b.eb_id = o.eb_id AND b.active = 1
        LEFT JOIN (SELECT eb_id, MAX(pf_uan_no) uan FROM hrms_ed_pf WHERE active = 1 GROUP BY eb_id) pf
               ON pf.eb_id = o.eb_id
        LEFT JOIN (SELECT eb_id, MAX(esi_no) esi_no FROM hrms_ed_esi WHERE active = 1 GROUP BY eb_id) esi
               ON esi.eb_id = o.eb_id
        LEFT JOIN (SELECT eb_id, SUM(no_of_units) units FROM electric_details
                   WHERE period_id = :pid AND active = 1 GROUP BY eb_id) el ON el.eb_id = o.eb_id
        WHERE w.CompCode = :c AND w.Location = :l AND w.PCode = :p AND w.EDate = :t
        ORDER BY w.OcpDptSft, w.C_P_Q, w.ECode
    """), {"b": branch_id, "pid": p["id"], "c": comp, "l": loc, "p": p["code"], "t": p["to_date"]})
    return p, [dict(r._mapping) for r in rows]


@router.get("/wages_payslip_text")
def wages_payslip_text(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Wages pay slips of one period as the legacy fixed-position text file (pre-printed stationery)."""
    try:
        branch_id, period_id = int(request.query_params.get("branch_id")), int(request.query_params.get("period_id"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="branch_id and period_id are required")
    p, rows = wages_payslip_rows(db, branch_id, period_id)
    if not rows:
        raise HTTPException(status_code=404, detail="No wages found for this period - process it first")
    return {"data": {"filename": f"PAYSLIP_{p['code']}_{p['to_date'].isoformat()}.TXT", "slips": len(rows),
                     "text": payslip_text(rows)}}
