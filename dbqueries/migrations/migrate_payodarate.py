"""
Mirror the legacy Smart-Eye SQL Server `PayODARate` (DA rate history) into nbjcl.payodarate.

    python migrate_payodarate.py            # dry run (default)
    python migrate_payodarate.py --execute  # create table + load (refuses if it already holds rows)

Env: tenant DB from env/database.env (run from pyhback/), MSSQL_PWD = SQL Server password,
TENANT_DB (default nbjcl), BRANCH_ID (default 87).

Legacy-shaped copy (same columns, utf8mb4_unicode_ci like paywages) plus eb_id / branch_id, filled
for workers whose ECode is an emp_code of the branch (others keep NULL — they are not in the tenant).
The rate the wages process uses is still worker_rate_mst; this table is the full history.
"""

import os
import sys

from dotenv import load_dotenv

load_dotenv("env/database.env")
import pymysql  # noqa: E402
import pyodbc  # noqa: E402

MSSQL = "DRIVER={ODBC Driver 17 for SQL Server};SERVER=162.245.218.10;DATABASE=Smart_Eye_Jute_Northbrook_Live;" \
        "UID=ERP;PWD=%s;TrustServerCertificate=yes"
DDL = """CREATE TABLE IF NOT EXISTS payodarate (
  eb_id BIGINT NULL, branch_id INT NULL,
  CompCode VARCHAR(10) NOT NULL, Location VARCHAR(50) NOT NULL, UnitCode VARCHAR(50) NOT NULL,
  DocEntry DECIMAL(18,0) NOT NULL, EffDate DATE NOT NULL, Grade VARCHAR(80) NOT NULL,
  EGroup VARCHAR(50) NOT NULL, SubGroup VARCHAR(50) NOT NULL, Category VARCHAR(50) NOT NULL,
  OrgECode VARCHAR(10) NOT NULL, ECode VARCHAR(10) NOT NULL, EName VARCHAR(100) NOT NULL,
  DA_Amt DECIMAL(10,2) NOT NULL, DA_HR DECIMAL(5,2) NOT NULL, CreateDate DATETIME NULL,
  PCName VARCHAR(30) NULL, UserID VARCHAR(50) NULL,
  KEY idx_payodarate_ecode (ECode, EffDate), KEY idx_payodarate_eb (eb_id), KEY idx_payodarate_eff (EffDate)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""


def main() -> None:
    execute = "--execute" in sys.argv
    tenant, branch = os.getenv("TENANT_DB", "nbjcl"), int(os.getenv("BRANCH_ID", "87"))
    my = pymysql.connect(host=os.environ["DATABASE_HOST"], user=os.environ["DATABASE_USER"],
                         password=os.environ["DATABASE_PASSWORD"], database=tenant, autocommit=False)
    cur = my.cursor()
    ms = pyodbc.connect(MSSQL % os.environ["MSSQL_PWD"]).cursor()
    cur.execute("SELECT emp_code, eb_id FROM hrms_ed_official_details WHERE branch_id=%s AND emp_code IS NOT NULL", (branch,))
    emp = {r[0].strip(): r[1] for r in cur.fetchall()}
    ms.execute("""SELECT CompCode, Location, UnitCode, DocEntry, EffDate, Grade, EGroup, SubGroup, Category, OrgECode,
                         ECode, EName, DA_Amt, DA_HR, CreateDate, PCName, UserID FROM PayODARate ORDER BY DocEntry, ECode""")
    s = lambda v: (v or "").strip()  # noqa: E731
    rows = [(emp.get(s(r[10])), branch if s(r[10]) in emp else None, s(r[0]), s(r[1]), s(r[2]), r[3], r[4], s(r[5]),
             s(r[6]), s(r[7]), s(r[8]), s(r[9]), s(r[10]), s(r[11]), r[12], r[13], r[14], s(r[15]), s(r[16]))
            for r in ms.fetchall()]
    matched = sum(1 for r in rows if r[0] is not None)
    print(f"legacy rows {len(rows)}; with tenant eb_id/branch {matched}; without {len(rows) - matched}")
    if not execute:
        print("DRY RUN - nothing changed. Re-run with --execute.")
        return
    cur.execute(DDL)
    cur.execute("SELECT COUNT(*) FROM payodarate")
    if cur.fetchone()[0]:
        sys.exit("payodarate already holds rows - refusing to load again")
    try:
        sql = f"INSERT INTO payodarate VALUES ({','.join(['%s'] * 19)})"
        for i in range(0, len(rows), 5000):
            cur.executemany(sql, rows[i:i + 5000])
        cur.execute("SELECT COUNT(*), COUNT(eb_id), COUNT(DISTINCT ECode), ROUND(SUM(DA_Amt),2) FROM payodarate")
        got = cur.fetchone()
        assert got[0] == len(rows), f"count mismatch {got[0]}/{len(rows)}"
        my.commit()
        print(f"COMMITTED: rows {got[0]}, with eb_id {got[1]}, workers {got[2]}, sum DA_Amt {got[3]}")
    except Exception:
        my.rollback()
        print("FAILED - rolled back")
        raise


if __name__ == "__main__":
    main()
