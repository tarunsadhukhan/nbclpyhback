"""
Load the legacy Smart-Eye fortnight production feeds (SQL Server `PayOProd*`) into the tenant's
production tables for a date range.

    python migrate_production_feeds.py 2026-09-01 2026-09-30            # dry run (default)
    python migrate_production_feeds.py 2026-09-01 2026-09-30 --execute

Env: tenant DB from env/database.env (run from pyhback/), MSSQL_PWD = SQL Server password,
TENANT_DB (default nbjcl), BRANCH_ID (default 87).

Targets and mappings follow how the 15/08 and 31/08 fortnights were loaded (verified 1:1 against them);
prod_date = legacy FNEDate (fortnight end), one tenant row per legacy row:

  PayOProdWvg   (dept 30) -> weaving_production   machine_id/machine_id2 = machine_mst.mech_code of MCH1/MCH2,
                             quality_id = tbl_nbcl_wages_quality_mst (code, dept), wk_hrs/prod_qty = Prod_HR/Prod_KG
  PayOProd      (dept 05) -> winding_production   QCode 0002 -> wdg_q_id 1 / incentive 2, 0005@18.0 -> 2 / 7,
                             unit KG, rate/amount = Inc_Rate/Inc_Amt
  PayOProdBmg   (dept 07) -> beaming_production   one row per document, quality 25, qty = ProdWT, amount = ProdValue
  PayOProdPress (dept 12) -> press_production     quality by (QCode, dept 12), rate_per_hrs = ROUND(Amount/Div_HR, 2)
  PayOProdSwg   (dept 11) -> payoprodswg          already a legacy-shaped copy: compared, loaded only if different

Not loaded (no target table in the tenant): PayOProdVBasic, PayOProdOcp, PayProdBmg1 detail lines.
Execute refuses when rows for the same fortnight dates already exist in a target (re-run safety).
"""

import collections
import os
import sys
from datetime import datetime

from dotenv import load_dotenv

load_dotenv("env/database.env")
import pymysql  # noqa: E402
import pyodbc  # noqa: E402

MSSQL = "DRIVER={ODBC Driver 17 for SQL Server};SERVER=162.245.218.10;DATABASE=Smart_Eye_Jute_Northbrook_Live;" \
        "UID=ERP;PWD=%s;TrustServerCertificate=yes"
BEAM_QUALITY_ID = 25
WINDING = {("0002", 9.5): (1, 2), ("0005", 18.0): (2, 7)}  # (QCode, grist) -> (wdg_q_id, winding_incentive_id)


def main() -> None:
    d0, d1 = sys.argv[1], sys.argv[2]
    execute = "--execute" in sys.argv
    tenant, branch = os.getenv("TENANT_DB", "nbjcl"), int(os.getenv("BRANCH_ID", "87"))
    my = pymysql.connect(host=os.environ["DATABASE_HOST"], user=os.environ["DATABASE_USER"],
                         password=os.environ["DATABASE_PASSWORD"], database=tenant, autocommit=False)
    cur = my.cursor()
    ms = pyodbc.connect(MSSQL % os.environ["MSSQL_PWD"]).cursor()

    cur.execute("SELECT emp_code, eb_id FROM hrms_ed_official_details WHERE branch_id=%s AND emp_code IS NOT NULL", (branch,))
    emp = {r[0].strip(): r[1] for r in cur.fetchall()}
    cur.execute("SELECT mech_code, machine_id FROM machine_mst WHERE active=1 ORDER BY machine_id")
    mach = {}
    for code, mid in cur.fetchall():
        mach.setdefault(code.strip(), mid)
    cur.execute("SELECT q.quality_code, d.dept_code, q.quality_id FROM tbl_nbcl_wages_quality_mst q "
                "JOIN dept_mst d ON d.dept_id=q.dept_id WHERE q.active=1 AND d.branch_id=%s ORDER BY q.quality_id", (branch,))
    qual = {}
    for code, dept, qid in cur.fetchall():
        qual.setdefault((code.strip(), dept), qid)

    skipped = collections.Counter()
    plans = {}  # target table -> (columns, rows, date-column)

    def fetch(sql):
        ms.execute(sql, (d0, d1))
        return ms.fetchall()

    # NB amount / payable_amt / divisible_hrs / rate_per_hrs are generated columns in the tenant tables
    # (rate x qty etc.) and reproduce the legacy figures, so they are not inserted.
    # weaving
    rows = []
    for r in fetch("SELECT FNEDate, WShift, ECode, MCH1, MCH2, Line_No, QCode, Prod_HR, Prod_KG, Rate, Amount, PayableAmt "
                   "FROM PayOProdWvg WHERE FNEDate BETWEEN ? AND ? ORDER BY FNEDate, LineID"):
        fne, sh, e, m1, m2, ln, qc, hr, kg, rate, amt, pay = r
        q = qual.get((qc.strip(), "30"))
        if e.strip() not in emp or m1.strip() not in mach or q is None:
            skipped["weaving: unmapped " + ("employee " + e.strip() if e.strip() not in emp else
                                           "machine " + m1.strip() if m1.strip() not in mach else "quality " + qc.strip())] += 1
            continue
        rows.append((branch, fne, sh.strip(), emp[e.strip()], mach[m1.strip()], mach.get(m2.strip()), int(ln), q,
                     float(hr), float(kg), float(rate), 1))
    plans["weaving_production"] = (
        "branch_id, prod_date, shift, eb_id, machine_id, machine_id2, line_no, quality_id, wk_hrs, prod_qty, rate, active", rows, "prod_date")

    # winding
    rows = []
    for r in fetch("SELECT FNEDate, WShift, ECode, QCode, Grist, Prod_HR, Prod_KG, Inc_Rate, Inc_Amt FROM PayOProd "
                   "WHERE FNEDate BETWEEN ? AND ? ORDER BY FNEDate, LineID"):
        fne, sh, e, qc, grist, hr, kg, irate, iamt = r
        key = (qc.strip(), float(grist))
        if e.strip() not in emp or key not in WINDING:
            skipped["winding: " + ("employee " + e.strip() if e.strip() not in emp else f"no rule for QCode/grist {key}")] += 1
            continue
        wq, wi = WINDING[key]
        rows.append((branch, fne, sh.strip(), emp[e.strip()], wq, wi, float(grist), float(hr), float(kg), "KG",
                     float(irate), 1))
    plans["winding_production"] = (
        "branch_id, prod_date, shift, eb_id, wdg_q_id, winding_incentive_id, grist, prod_hrs, prod_kg, unit, rate, active",
        rows, "prod_date")

    # beaming
    rows = []
    for r in fetch("SELECT FNEDate, WShift, MachCode, Mach_HR, Div_HR, Lost_HR, ProdWT, ProdValue FROM PayOProdBmg "
                   "WHERE FNEDate BETWEEN ? AND ? ORDER BY FNEDate, DocEntry"):
        fne, sh, mc, mhr, dhr, lhr, wt, val = r
        if mc.strip() not in mach:
            skipped["beaming: machine " + mc.strip()] += 1
            continue
        wt, val = float(wt), float(val)
        rows.append((branch, fne, sh.strip(), mach[mc.strip()], BEAM_QUALITY_ID, wt, val / wt if wt else 0,
                     float(mhr), float(lhr), 1))
    plans["beaming_production"] = (
        "branch_id, prod_date, shift, machine_id, quality_id, prod_qty, rate, wk_hrs, lost_hrs, active",
        rows, "prod_date")

    # press
    rows = []
    for r in fetch("SELECT FNEDate, WShift, MachCode, QCode, Prod_HR, Prod_DivHR, Prod_LHR, Prod_KG, Rate, Amount "
                   "FROM PayOProdPress WHERE FNEDate BETWEEN ? AND ? ORDER BY FNEDate, LineID"):
        fne, sh, mc, qc, hr, dhr, lhr, kg, rate, amt = r
        q = qual.get((qc.strip(), "12"))
        if mc.strip() not in mach or q is None:
            skipped["press: unmapped " + ("machine " + mc.strip() if mc.strip() not in mach else "quality " + qc.strip())] += 1
            continue
        dhr = float(dhr)
        rows.append((branch, fne, sh.strip(), mach[mc.strip()], q, float(kg), float(rate), float(hr),
                     float(lhr), 1))
    plans["press_production"] = (
        "branch_id, prod_date, shift, machine_id, quality_id, prod_qty, rate, wk_hrs, lost_hrs, active", rows, "prod_date")

    # sewing: legacy-shaped table already in the tenant — compare only
    ms.execute("SELECT COUNT(*), SUM(Amount), SUM(Prod_KG) FROM PayOProdSwg WHERE FNEDate BETWEEN ? AND ?", (d0, d1))
    lc = ms.fetchone()
    cur.execute("SELECT COUNT(*), SUM(Amount), SUM(Prod_KG) FROM payoprodswg WHERE FNEDate BETWEEN %s AND %s", (d0, d1))
    tc = cur.fetchone()
    same = (int(lc[0]), round(float(lc[1] or 0), 2), round(float(lc[2] or 0), 2)) == \
           (int(tc[0]), round(float(tc[1] or 0), 2), round(float(tc[2] or 0), 2))
    print(f"range {d0}..{d1} branch {branch} tenant {tenant}")
    print(f"sewing payoprodswg: legacy {lc[0]} rows / {lc[1]} vs tenant {tc[0]} rows / {tc[1]} -> "
          f"{'identical, nothing to load' if same else 'DIFFERENT - not loaded by this script'}")

    existing = {}
    for t, (cols, rows, dcol) in plans.items():
        dates = sorted({r[1] for r in rows})
        n = 0
        if dates:
            cur.execute(f"SELECT COUNT(*) FROM {t} WHERE {dcol} IN ({','.join(['%s'] * len(dates))})", dates)
            n = cur.fetchone()[0]
        existing[t] = n
        print(f"{t}: insert {len(rows)} rows for fortnights {[str(d) for d in dates]}; already present for those dates: {n}")
    print("skipped:", dict(skipped))
    if not execute:
        print("DRY RUN - nothing changed. Re-run with --execute.")
        return
    if any(existing.values()):
        sys.exit("Refusing: target rows already exist for these fortnight dates.")

    try:
        for t, (cols, rows, dcol) in plans.items():
            if rows:
                cur.executemany(f"INSERT INTO {t} ({cols}) VALUES ({','.join(['%s'] * len(rows[0]))})", rows)
        my.commit()
        print("COMMITTED", datetime.now().isoformat(timespec="seconds"))
    except Exception:
        my.rollback()
        print("FAILED - rolled back")
        raise


if __name__ == "__main__":
    main()
