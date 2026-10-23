"""
Legacy Smart-Eye holidays -> tenant: PayOHoliday -> holiday_master, PayWHoliday -> hrms_holiday_transactions.

    python dbqueries/migrations/migrate_holidays.py            # dry run
    python dbqueries/migrations/migrate_holidays.py --execute  # insert

Env: tenant DB from env/database.env (run from pyhback/), MSSQL_PWD = SQL Server password,
TENANT_DB (default nbjcl), BRANCH_ID (default 87, the legacy NJB FACTORY).

holiday_master : one row per holiday date - PayOHoliday's dates (HolidayEvent as the name) plus the
                 eligible PayWHoliday dates PayOHoliday lacks (manual 2022-2025 holidays, named 'HOLIDAY').
                 holiday_type 1 (occasional), status 3 (approved - the wages process reads approved only).
hrms_holiday_transactions : one row per eligible PayWHoliday row (Eligible = 'Y'; legacy pays COUNT(*) * 8
                 hours), eb_id by emp_code, holiday_hours 8, eligibility_date = holiday date,
                 manual = 1 when IsManual = 'Y'. Workers not in the tenant are skipped (reported).
Dates the tenant already has in holiday_master (e.g. entered on the holiday screen) are left untouched,
so the script is safe to re-run.
"""

import collections
import os
import sys

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

    cur.execute("SELECT holiday_date FROM holiday_master WHERE branch_id = %s AND holiday_date IS NOT NULL", (branch,))
    have = {r[0] for r in cur.fetchall()}
    cur.execute("SELECT emp_code, eb_id FROM hrms_ed_official_details WHERE branch_id = %s AND emp_code IS NOT NULL", (branch,))
    emp = {r[0].strip(): r[1] for r in cur.fetchall()}

    ms.execute("SELECT HolidayDate, MAX(HolidayEvent) FROM PayOHoliday WHERE UPPER(Location) = 'FACTORY' GROUP BY HolidayDate")
    names = {d: (n or "").strip() or "HOLIDAY" for d, n in ms.fetchall()}
    ms.execute("SELECT ECode, HolidayDate, IsManual FROM PayWHoliday WHERE UPPER(Location) = 'FACTORY' AND Eligible = 'Y'")
    tran = [((e or "").strip(), d, (m or "").strip()) for e, d, m in ms.fetchall()]
    for _, d, _ in tran:
        names.setdefault(d, "HOLIDAY")

    new_dates = sorted(d for d in names if d not in have)
    rows, skipped = [], collections.Counter()
    for e, d, m in tran:
        if d in have:
            skipped["date already in holiday_master"] += 1
        elif e not in emp:
            skipped["worker not in tenant"] += 1
        else:
            rows.append((d, emp[e], 1 if m == "Y" else 0))
    print(f"holiday dates: legacy {len(names)}, already in tenant {len(names) - len(new_dates)}, to insert {len(new_dates)}")
    print(f"eligible legacy transactions {len(tran)} -> insert {len(rows)}; skipped {dict(skipped)}")
    if not execute:
        print("DRY RUN - nothing changed. Re-run with --execute.")
        return
    try:
        cur.executemany("INSERT INTO holiday_master (branch_id, holiday, holiday_date, holiday_type, status) "
                        "VALUES (%s, %s, %s, 1, 3)", [(branch, names[d], d) for d in new_dates])
        cur.execute("SELECT holiday_date, holiday_id FROM holiday_master WHERE branch_id = %s", (branch,))
        hid = dict(cur.fetchall())
        # placeholders only: pymysql batches executemany into multi-row INSERTs only then (a literal in
        # VALUES makes it send one statement per row - ~20 min for 60k rows to the remote server)
        cur.executemany("INSERT INTO hrms_holiday_transactions (holiday_id, eb_id, holiday_hours, eligibility_date, "
                        "branch_id, manual) VALUES (%s, %s, %s, %s, %s, %s)",
                        [(hid[d], eb, 8, d, branch, m) for d, eb, m in rows])
        my.commit()
        print(f"COMMITTED: holiday_master {len(new_dates)}, hrms_holiday_transactions {len(rows)}")
    except Exception:
        my.rollback()
        print("FAILED - rolled back")
        raise


if __name__ == "__main__":
    main()
