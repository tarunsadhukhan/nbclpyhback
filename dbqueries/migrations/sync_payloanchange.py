"""
Copy legacy Smart-Eye `PayLoanChange` rows (PF loan / interest / advance EMI changes and stops) that the
tenant does not have yet: every legacy row with ToDate after the tenant's latest ToDate.

    python dbqueries/migrations/sync_payloanchange.py            # dry run
    python dbqueries/migrations/sync_payloanchange.py --execute  # insert

Env: tenant DB from env/database.env (run from pyhback/), MSSQL_PWD = SQL Server password,
TENANT_DB (default nbjcl). Same columns on both sides; text right-trimmed (legacy CHAR padding).
"""

import os
import sys

from dotenv import load_dotenv

load_dotenv("env/database.env")
import pymysql  # noqa: E402
import pyodbc  # noqa: E402

MSSQL = "DRIVER={ODBC Driver 17 for SQL Server};SERVER=162.245.218.10;DATABASE=Smart_Eye_Jute_Northbrook_Live;" \
        "UID=ERP;PWD=%s;TrustServerCertificate=yes"
COLS = ("CompCode", "Location", "FrmName", "UnitCode", "DocEntry", "LineID", "Grade", "SubGroup", "OrgECode", "ECode",
        "EName", "LoanType", "PCode", "FromDate", "ToDate", "OldEMICapital", "OldEMIInterest", "EMICapital",
        "EMIInterest", "CapitalStop", "InterestStop", "CreatedDate", "UpdatedDate", "PCName", "UserID")


def main() -> None:
    execute = "--execute" in sys.argv
    my = pymysql.connect(host=os.environ["DATABASE_HOST"], user=os.environ["DATABASE_USER"],
                         password=os.environ["DATABASE_PASSWORD"], database=os.getenv("TENANT_DB", "nbjcl"),
                         autocommit=False)
    cur = my.cursor()
    cur.execute("SELECT MAX(ToDate) FROM payloanchange")
    since = cur.fetchone()[0]
    ms = pyodbc.connect(MSSQL % os.environ["MSSQL_PWD"]).cursor()
    ms.execute(f"SELECT {', '.join(COLS)} FROM PayLoanChange WHERE ToDate > ? ORDER BY DocEntry, LineID", since)
    rows = [tuple(v.rstrip() if isinstance(v, str) else v for v in r) for r in ms.fetchall()]
    summary = {}
    for r in rows:
        key = (str(r[14]), r[11], r[19], r[20])  # ToDate, LoanType, CapitalStop, InterestStop
        summary[key] = summary.get(key, 0) + 1
    print(f"tenant latest ToDate {since}; legacy rows after it: {len(rows)}")
    for k, n in sorted(summary.items()):
        print("  ", k, n)
    if not execute or not rows:
        print("DRY RUN - nothing changed. Re-run with --execute." if not execute else "nothing to copy")
        return
    try:
        cur.executemany(f"INSERT INTO payloanchange ({', '.join(COLS)}) VALUES ({', '.join(['%s'] * len(COLS))})", rows)
        cur.execute("SELECT COUNT(*) FROM payloanchange WHERE ToDate > %s", (since,))
        got = cur.fetchone()[0]
        assert got == len(rows), f"count mismatch {got}/{len(rows)}"
        my.commit()
        print(f"COMMITTED: {got} rows")
    except Exception:
        my.rollback()
        print("FAILED - rolled back")
        raise


if __name__ == "__main__":
    main()
