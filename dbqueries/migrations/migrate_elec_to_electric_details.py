"""
Legacy electricity bills nbjcl.PayM_Elec (mirrored from Smart-Eye) -> electric_details (Others > Electric Data).

    python dbqueries/migrations/migrate_elec_to_electric_details.py            # dry run
    python dbqueries/migrations/migrate_elec_to_electric_details.py --execute  # insert

Env: tenant DB from env/database.env (run from pyhback/), TENANT_DB (default nbjcl), BRANCH_ID (default 87).
Reads the mirrored nbjcl.PayM_Elec (refresh it first with
`migrate_payowagesrate_ocp.py PayM_Elec` if new legacy bills matter).

amount = TotalAmt (opening balance + Amt, what legacy recovers), unit_rate = Rate, no_of_units = ElecUnit
rounded (the column is an int; amount stays exact), tran_date = EDate, period_id = pay_period by legacy
Period code, remarks = legacy Remarks ('OPENING' for opening-balance rows without one).
A legacy row is skipped when its worker is not in the tenant or the worker already has an
electric_details row for that period, so the script is safe to re-run.
"""

import collections
import os
import sys

from dotenv import load_dotenv

load_dotenv("env/database.env")
import pymysql  # noqa: E402


def main() -> None:
    execute = "--execute" in sys.argv
    tenant, branch = os.getenv("TENANT_DB", "nbjcl"), int(os.getenv("BRANCH_ID", "87"))
    my = pymysql.connect(host=os.environ["DATABASE_HOST"], user=os.environ["DATABASE_USER"],
                         password=os.environ["DATABASE_PASSWORD"], database=tenant, autocommit=False)
    cur = my.cursor()
    cur.execute("SELECT emp_code, eb_id FROM hrms_ed_official_details WHERE branch_id = %s AND emp_code IS NOT NULL", (branch,))
    emp = {r[0].strip(): r[1] for r in cur.fetchall()}
    cur.execute("SELECT code, ID FROM pay_period WHERE branch_id = %s", (branch,))
    period = {r[0]: r[1] for r in cur.fetchall()}
    cur.execute("SELECT eb_id, period_id FROM electric_details WHERE branch_id = %s", (branch,))
    have = set(cur.fetchall())
    cur.execute("SELECT ECode, EDate, Period, ElecUnit, Rate, OpeningAmt, TotalAmt, Remarks FROM PayM_Elec "
                "WHERE UPPER(Location) = 'FACTORY' ORDER BY EDate, DocEntry, LineID")
    rows, skipped, seen = [], collections.Counter(), set()
    for ecode, edate, pcode, units, rate, opening, total, remarks in cur.fetchall():
        eb, pid = emp.get((ecode or "").strip()), period.get((pcode or "").strip())
        if eb is None:
            skipped["worker not in tenant"] += 1
        elif pid is None:
            skipped["period code not in pay_period"] += 1
        elif (eb, pid) in have:
            skipped["worker already has a row for the period"] += 1
        else:
            seen.add((eb, pid))
            note = (remarks or "").strip() or ("OPENING" if opening else None)
            rows.append((branch, edate, eb, float(total), note, 1, pid, float(rate), int(round(float(units)))))
    print(f"legacy bills -> insert {len(rows)} ({len(seen)} worker-periods); skipped {dict(skipped)}")
    print(f"total amount {sum(r[3] for r in rows):,.2f}")
    if not execute:
        print("DRY RUN - nothing changed. Re-run with --execute.")
        return
    try:
        cur.executemany("INSERT INTO electric_details (branch_id, tran_date, eb_id, amount, remarks, active, period_id, "
                        "unit_rate, no_of_units) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)", rows)
        my.commit()
        print(f"COMMITTED: electric_details {len(rows)}")
    except Exception:
        my.rollback()
        print("FAILED - rolled back")
        raise


if __name__ == "__main__":
    main()
