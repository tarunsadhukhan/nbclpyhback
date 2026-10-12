"""
Bring worker_rate_mst DA rates in line with the legacy Smart-Eye SQL Server `PayODARate`.

    python migrate_da_rate_to_worker_rate.py            # dry run (default)
    python migrate_da_rate_to_worker_rate.py --execute

Env: tenant DB from env/database.env (run from pyhback/), MSSQL_PWD = SQL Server password,
TENANT_DB (default nbjcl), BRANCH_ID (default 87).

The tenant keeps DA in worker_rate_mst (one row per worker and effective date, one active row per
worker; the rate screen deactivates the old row when it adds a new one). For every branch worker whose
active da_rate differs from the legacy latest DA_Amt (max EffDate, then max DocEntry) this script
deactivates the active row and inserts a copy of it with da_rate = legacy DA_Amt, keeping the same
effective_date so it stays the row the wages process picks. The old row remains as history.
Workers without a tenant rate row or employee are skipped. A full backup copy of worker_rate_mst is
created before anything changes.
"""

import os
import sys
from datetime import datetime

from dotenv import load_dotenv

load_dotenv("env/database.env")
import pymysql  # noqa: E402
import pyodbc  # noqa: E402

MSSQL = "DRIVER={ODBC Driver 17 for SQL Server};SERVER=162.245.218.10;DATABASE=Smart_Eye_Jute_Northbrook_Live;" \
        "UID=ERP;PWD=%s;TrustServerCertificate=yes"


def main() -> None:
    execute = "--execute" in sys.argv
    tenant, branch = os.getenv("TENANT_DB", "nbjcl"), int(os.getenv("BRANCH_ID", "87"))
    my = pymysql.connect(host=os.environ["DATABASE_HOST"], user=os.environ["DATABASE_USER"],
                         password=os.environ["DATABASE_PASSWORD"], database=tenant, autocommit=False)
    cur = my.cursor()
    ms = pyodbc.connect(MSSQL % os.environ["MSSQL_PWD"]).cursor()

    ms.execute("""SELECT T0.ECode, T0.DA_Amt, T0.EffDate FROM PayODARate T0
                  JOIN (SELECT ECode, MAX(EffDate) m FROM PayODARate GROUP BY ECode) T1
                    ON T1.ECode = T0.ECode AND T1.m = T0.EffDate
                  WHERE T0.DocEntry = (SELECT MAX(DocEntry) FROM PayODARate x WHERE x.ECode = T0.ECode AND x.EffDate = T0.EffDate)""")
    legacy = {r[0].strip(): (round(float(r[1]), 2), r[2]) for r in ms.fetchall()}

    cur.execute("""SELECT o.emp_code, w.worker_rate_id, w.eb_id, w.da_rate FROM worker_rate_mst w
                   JOIN hrms_ed_official_details o ON o.eb_id = w.eb_id AND o.branch_id = %s
                   WHERE w.is_active = 1""", (branch,))
    active = {}
    for code, rid, eb, da in cur.fetchall():
        active.setdefault(code.strip(), []).append((rid, eb, float(da or 0)))

    changes, stats = [], {"legacy workers": len(legacy), "no active tenant rate": 0, "already equal": 0,
                          "multiple active rows": 0}
    for code, (da, _eff) in legacy.items():
        rows = active.get(code)
        if not rows:
            stats["no active tenant rate"] += 1
        elif len(rows) > 1:
            stats["multiple active rows"] += 1
        elif abs(rows[0][2] - da) <= 0.01:
            stats["already equal"] += 1
        else:
            changes.append((rows[0][0], da))
    print(f"branch {branch} tenant {tenant}: {stats}")
    print(f"to update: {len(changes)} workers")
    if not execute:
        print("DRY RUN - nothing changed. Re-run with --execute.")
        return

    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    cur.execute(f"CREATE TABLE bak_{stamp}_worker_rate_mst AS SELECT * FROM worker_rate_mst")
    cur.execute(f"SELECT COUNT(*) FROM bak_{stamp}_worker_rate_mst")
    print(f"backup bak_{stamp}_worker_rate_mst: {cur.fetchone()[0]} rows")
    my.commit()
    try:
        cur.execute("CREATE TEMPORARY TABLE _da (rid INT PRIMARY KEY, da DOUBLE)")
        cur.executemany("INSERT INTO _da VALUES (%s, %s)", changes)
        cur.execute("""INSERT INTO worker_rate_mst
                         (eb_id, effective_date, fbasic, fbasic_hr, da_all, da_rate, hra, hrd, quarter, pf, esi, ptax, is_active)
                       SELECT w.eb_id, w.effective_date, w.fbasic, w.fbasic_hr, w.da_all, d.da, w.hra, w.hrd, w.quarter,
                              w.pf, w.esi, w.ptax, 1
                       FROM worker_rate_mst w JOIN _da d ON d.rid = w.worker_rate_id""")
        added = cur.rowcount
        cur.execute("UPDATE worker_rate_mst w JOIN _da d ON d.rid = w.worker_rate_id SET w.is_active = 0")
        cur.execute("""SELECT COUNT(*) FROM (SELECT eb_id FROM worker_rate_mst WHERE is_active = 1
                       GROUP BY eb_id HAVING COUNT(*) > 1) x""")
        dup = cur.fetchone()[0]
        assert added == len(changes) and dup == 0, f"unexpected: added {added}/{len(changes)}, multi-active {dup}"
        my.commit()
        print(f"COMMITTED: {added} rate rows inserted, {len(changes)} old rows deactivated")
    except Exception:
        my.rollback()
        print("FAILED - rolled back (backup table kept)")
        raise


if __name__ == "__main__":
    main()
