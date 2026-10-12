"""
Mirror the legacy Smart-Eye SQL Server `PayM_AdjPF` and `PayM_AdjNPF` (manual PF / non-PF earning
adjustments per fortnight, read by the wages process as PFEarnAdj / NPFEarnAdj) into the tenant.

    python migrate_adj_pf_npf.py            # dry run (default)
    python migrate_adj_pf_npf.py --execute  # create tables + load (refuses a table that already holds rows)

Env: tenant DB from env/database.env (run from pyhback/), MSSQL_PWD = SQL Server password,
TENANT_DB (default nbjcl), BRANCH_ID (default 87).

Legacy-shaped copies (same columns, utf8mb4_unicode_ci like paywages) plus eb_id / branch_id, filled
for workers whose ECode is an emp_code of the branch. All legacy rows are loaded.
"""

import os
import sys

from dotenv import load_dotenv

load_dotenv("env/database.env")
import pymysql  # noqa: E402
import pyodbc  # noqa: E402

MSSQL = "DRIVER={ODBC Driver 17 for SQL Server};SERVER=162.245.218.10;DATABASE=Smart_Eye_Jute_Northbrook_Live;" \
        "UID=ERP;PWD=%s;TrustServerCertificate=yes"
TABLES = ("PayM_AdjNPF", "PayM_AdjPF")
DDL = """CREATE TABLE IF NOT EXISTS {t} (
  eb_id BIGINT NULL, branch_id INT NULL,
  CompCode VARCHAR(10) NOT NULL, Location VARCHAR(50) NOT NULL, UnitCode VARCHAR(50) NOT NULL,
  FNEDate DATE NOT NULL, DeptCode VARCHAR(50) NOT NULL, DeptName VARCHAR(250) NOT NULL, WShift VARCHAR(2) NOT NULL,
  LineID DECIMAL(18,0) NOT NULL, ECode VARCHAR(10) NOT NULL, EName VARCHAR(250) NOT NULL,
  Adj_HR DECIMAL(18,2) NOT NULL, Adj_Amt DECIMAL(18,2) NOT NULL, EffDate DATE NULL,
  CreateDate DATETIME NULL, UpdatedDate DATETIME NULL, PCName VARCHAR(30) NULL, UserID VARCHAR(50) NULL,
  KEY idx_{t}_fne (FNEDate, ECode), KEY idx_{t}_eb (eb_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""
COLS = ("CompCode, Location, UnitCode, FNEDate, DeptCode, DeptName, WShift, LineID, ECode, EName, Adj_HR, Adj_Amt, "
        "EffDate, CreateDate, UpdatedDate, PCName, UserID")


def main() -> None:
    execute = "--execute" in sys.argv
    tenant, branch = os.getenv("TENANT_DB", "nbjcl"), int(os.getenv("BRANCH_ID", "87"))
    my = pymysql.connect(host=os.environ["DATABASE_HOST"], user=os.environ["DATABASE_USER"],
                         password=os.environ["DATABASE_PASSWORD"], database=tenant, autocommit=False)
    cur = my.cursor()
    ms = pyodbc.connect(MSSQL % os.environ["MSSQL_PWD"]).cursor()
    cur.execute("SELECT emp_code, eb_id FROM hrms_ed_official_details WHERE branch_id=%s AND emp_code IS NOT NULL", (branch,))
    emp = {r[0].strip(): r[1] for r in cur.fetchall()}
    s = lambda v: (v or "").strip()  # noqa: E731

    plans = {}
    for t in TABLES:
        ms.execute(f"SELECT {COLS} FROM {t} ORDER BY FNEDate, LineID")
        rows = []
        for r in ms.fetchall():
            e = s(r[8])
            rows.append((emp.get(e), branch if e in emp else None, s(r[0]), s(r[1]), s(r[2]), r[3], s(r[4]), s(r[5]),
                         s(r[6]), r[7], e, s(r[9]), r[10], r[11], r[12], r[13], r[14], s(r[15]), s(r[16])))
        plans[t] = rows
        print(f"{t}: legacy rows {len(rows)}, with tenant eb_id {sum(1 for x in rows if x[0] is not None)}, "
              f"sum Adj_Amt {round(sum(float(x[13]) for x in rows), 2)}")
    if not execute:
        print("DRY RUN - nothing changed. Re-run with --execute.")
        return
    try:
        for t, rows in plans.items():
            cur.execute(DDL.format(t=t))
            cur.execute(f"SELECT COUNT(*) FROM {t}")
            if cur.fetchone()[0]:
                raise SystemExit(f"{t} already holds rows - refusing to load again")
            cur.executemany(f"INSERT INTO {t} VALUES ({','.join(['%s'] * 19)})", rows)
            cur.execute(f"SELECT COUNT(*), ROUND(SUM(Adj_Amt),2) FROM {t}")
            n, tot = cur.fetchone()
            assert n == len(rows), f"{t}: count mismatch {n}/{len(rows)}"
            print(f"{t}: loaded {n} rows, sum Adj_Amt {tot}")
        my.commit()
        print("COMMITTED")
    except BaseException:
        my.rollback()
        print("FAILED - rolled back")
        raise


if __name__ == "__main__":
    main()
