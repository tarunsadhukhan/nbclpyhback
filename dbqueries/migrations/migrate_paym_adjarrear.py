"""
Mirror the legacy Smart-Eye SQL Server `PayM_AdjArrear` (DA / HRA arrears per fortnight, with the
fortnight they were paid in) into the tenant.

    python migrate_paym_adjarrear.py            # dry run (default)
    python migrate_paym_adjarrear.py --execute  # create table + load (refuses if it already holds rows)

Env: tenant DB from env/database.env (run from pyhback/), MSSQL_PWD = SQL Server password,
TENANT_DB (default nbjcl), BRANCH_ID (default 87).

Legacy-shaped copy plus eb_id / branch_id, filled for workers whose ECode is an emp_code of the branch.
Legacy FNEDate is a 'dd/mm/yyyy' varchar -> DATE; float columns -> DECIMAL (drops float noise such as
131.70000000000002). All legacy rows are loaded.
"""

import os
import sys
from datetime import datetime
from decimal import Decimal

from dotenv import load_dotenv

load_dotenv("env/database.env")
import pymysql  # noqa: E402
import pyodbc  # noqa: E402

MSSQL = "DRIVER={ODBC Driver 17 for SQL Server};SERVER=162.245.218.10;DATABASE=Smart_Eye_Jute_Northbrook_Live;" \
        "UID=ERP;PWD=%s;TrustServerCertificate=yes"
DDL = """CREATE TABLE IF NOT EXISTS PayM_AdjArrear (
  eb_id BIGINT NULL, branch_id INT NULL,
  ECode VARCHAR(255) NULL, EName VARCHAR(255) NULL, FNEDate DATE NOT NULL,
  WHR DECIMAL(18,2) NULL, DA_Rate DECIMAL(18,4) NULL, HRA_Rate DECIMAL(3,2) NOT NULL,
  DA_Amt DECIMAL(18,2) NULL, HRA_Amt DECIMAL(18,2) NULL, Arrear_Amt DECIMAL(18,2) NULL,
  CreatedDate DATETIME NOT NULL, Paid_FNEDate DATE NULL, UpdatedDate DATETIME NOT NULL,
  KEY idx_PayM_AdjArrear_fne (FNEDate, ECode), KEY idx_PayM_AdjArrear_paid (Paid_FNEDate), KEY idx_PayM_AdjArrear_eb (eb_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""


def dec(v, places: str):
    return None if v is None else Decimal(str(v)).quantize(Decimal(places))


def main() -> None:
    execute = "--execute" in sys.argv
    tenant, branch = os.getenv("TENANT_DB", "nbjcl"), int(os.getenv("BRANCH_ID", "87"))
    my = pymysql.connect(host=os.environ["DATABASE_HOST"], user=os.environ["DATABASE_USER"],
                         password=os.environ["DATABASE_PASSWORD"], database=tenant, autocommit=False)
    cur = my.cursor()
    ms = pyodbc.connect(MSSQL % os.environ["MSSQL_PWD"]).cursor()
    cur.execute("SELECT emp_code, eb_id FROM hrms_ed_official_details WHERE branch_id=%s AND emp_code IS NOT NULL", (branch,))
    emp = {r[0].strip(): r[1] for r in cur.fetchall()}
    ms.execute("""SELECT ECode, EName, FNEDate, WHR, DA_Rate, HRA_Rate, DA_Amt, HRA_Amt, Arrear_Amt, CreatedDate,
                         Paid_FNEDate, UpdatedDate FROM PayM_AdjArrear""")
    rows = []
    for r in ms.fetchall():
        e = (r[0] or "").strip()
        rows.append((emp.get(e), branch if e in emp else None, e, (r[1] or "").strip(),
                     datetime.strptime(r[2].strip(), "%d/%m/%Y").date(), dec(r[3], "0.01"), dec(r[4], "0.0001"),
                     r[5], dec(r[6], "0.01"), dec(r[7], "0.01"), dec(r[8], "0.01"), r[9], r[10], r[11]))
    matched = sum(1 for r in rows if r[0] is not None)
    total = sum((r[10] or 0) for r in rows)
    print(f"legacy rows {len(rows)}; with tenant eb_id/branch {matched}; without {len(rows) - matched}; "
          f"sum Arrear_Amt {total}")
    if not execute:
        print("DRY RUN - nothing changed. Re-run with --execute.")
        return
    cur.execute(DDL)
    cur.execute("SELECT COUNT(*) FROM PayM_AdjArrear")
    if cur.fetchone()[0]:
        sys.exit("PayM_AdjArrear already holds rows - refusing to load again")
    try:
        cur.executemany(f"INSERT INTO PayM_AdjArrear VALUES ({','.join(['%s'] * 14)})", rows)
        cur.execute("SELECT COUNT(*), COUNT(eb_id), SUM(Arrear_Amt) FROM PayM_AdjArrear")
        got = cur.fetchone()
        assert got[0] == len(rows) and got[2] == total, f"mismatch {got} vs {len(rows)}/{total}"
        my.commit()
        print(f"COMMITTED: rows {got[0]}, with eb_id {got[1]}, sum Arrear_Amt {got[2]}")
    except Exception:
        my.rollback()
        print("FAILED - rolled back")
        raise


if __name__ == "__main__":
    main()
