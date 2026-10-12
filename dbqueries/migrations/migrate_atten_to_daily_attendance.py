"""
Replace tenant attendance for a date range with the legacy Smart-Eye SQL Server `Atten` rows.

    python migrate_atten_to_daily_attendance.py 2026-09-01 2026-09-30            # dry run (default)
    python migrate_atten_to_daily_attendance.py 2026-09-01 2026-09-30 --execute  # backup, delete, insert

Env: tenant DB from env/database.env (run from pyhback/), MSSQL_PWD = SQL Server login password
(host/db/user below), TENANT_DB (default nbjcl), BRANCH_ID (default 87).

Steps (execute): back up the branch's rows of the range into bak_<stamp>_* tables, then in ONE
transaction delete daily_attendance + daily_ebmc_attendance + pay_attendance (derived, rebuilt by the
daily wages process) for the range and insert the legacy rows.

Mapping (verified against the manually entered Sep 1-12 rows): emp_code -> hrms_ed_official_details,
WShift A/B/C -> spell_id 109/110/108, dept_code -> mirrored sub_dept_mst, ocp_code -> designation by
(department, normalised name) with the existing rows' mapping taking precedence, mch1/mch2 ->
machine_mst.mech_code. DUTY -> type R / mark P / status 3 (approved); VOUCHER rows are skipped.
"""

import collections
import os
import re
import sys
from datetime import datetime

from dotenv import load_dotenv

load_dotenv("env/database.env")
import pymysql  # noqa: E402
import pyodbc  # noqa: E402

MSSQL = "DRIVER={ODBC Driver 17 for SQL Server};SERVER=162.245.218.10;DATABASE=Smart_Eye_Jute_Northbrook_Live;" \
        "UID=ERP;PWD=%s;TrustServerCertificate=yes"
SPELL = {"A": 109, "B": 110, "C": 108}
norm = lambda s: re.sub(r"\s+", " ", (s or "").strip().upper())  # noqa: E731


def main() -> None:
    d0, d1 = sys.argv[1], sys.argv[2]
    execute = "--execute" in sys.argv
    tenant, branch = os.getenv("TENANT_DB", "nbjcl"), int(os.getenv("BRANCH_ID", "87"))
    my = pymysql.connect(host=os.environ["DATABASE_HOST"], user=os.environ["DATABASE_USER"],
                         password=os.environ["DATABASE_PASSWORD"], database=tenant, autocommit=False)
    cur = my.cursor()
    ms = pyodbc.connect(MSSQL % os.environ["MSSQL_PWD"]).cursor()

    # ── masters ────────────────────────────────────────────────────────
    cur.execute("SELECT emp_code, eb_id FROM hrms_ed_official_details WHERE branch_id=%s AND emp_code IS NOT NULL", (branch,))
    emp = {r[0].strip(): r[1] for r in cur.fetchall()}
    cur.execute("SELECT d.dept_code, s.sub_dept_id FROM sub_dept_mst s JOIN dept_mst d ON d.dept_id=s.dept_id "
                "WHERE d.branch_id=%s", (branch,))
    subdept = {r[0]: r[1] for r in cur.fetchall()}
    cur.execute("SELECT dept_code, dept_id FROM dept_mst WHERE branch_id=%s", (branch,))
    dept_id = {r[0]: r[1] for r in cur.fetchall()}
    cur.execute("SELECT dept_id, desig, designation_id FROM designation_mst WHERE branch_id=%s AND active=1 "
                "ORDER BY designation_id", (branch,))
    desig = collections.defaultdict(list)
    for dpt, name, did in cur.fetchall():
        desig[(dpt, norm(name))].append(did)
    cur.execute("SELECT mech_code, machine_id FROM machine_mst WHERE active=1 ORDER BY machine_id")
    mach = {}
    for code, mid in cur.fetchall():
        mach.setdefault(code.strip(), mid)
    ms.execute("SELECT OcpCode, OcpName FROM ODPTOCP")
    ocp_name = {r[0].strip(): norm(r[1]) for r in ms.fetchall()}

    # existing rows' ocp -> designation (majority), read before anything is deleted
    cur.execute("""SELECT o.emp_code, d.attendance_date, sp.spell_code, d.worked_designation_id
                   FROM daily_attendance d JOIN hrms_ed_official_details o ON o.eb_id=d.eb_id AND o.branch_id=%s
                   LEFT JOIN spell_mst sp ON sp.spell_id=d.spell_id
                   WHERE d.branch_id=%s AND d.attendance_date BETWEEN %s AND %s AND d.attendance_source='M'
                     AND d.worked_designation_id IS NOT NULL""", (branch, branch, d0, d1))
    existing = {(r[0].strip(), str(r[1]), (r[2] or "").strip()): r[3] for r in cur.fetchall()}

    # ── legacy rows ────────────────────────────────────────────────────
    ms.execute("""SELECT ID, emp_code, dept_code, ocp_code, mch1_code, mch2_code, work_type, WDate, WTime, WShift,
                         Shift_HR, GatePass_HR, Work_HR FROM Atten WHERE WDate BETWEEN ? AND ? ORDER BY ID""", (d0, d1))
    legacy = ms.fetchall()
    vote = collections.defaultdict(collections.Counter)
    for r in legacy:
        k = (r[1].strip(), str(r[7]), (r[9] or "").strip())
        if k in existing:
            vote[r[3].strip()][existing[k]] += 1
    emp_map = {o: c.most_common(1)[0][0] for o, c in vote.items()}

    rows, ebmc, skipped = [], [], collections.Counter()
    for r in legacy:
        lid, e, dpt, ocp, m1, m2, wt, wdate, wtime, shift, shr, gp, whr = r
        e, dpt, ocp, shift = e.strip(), dpt.strip(), ocp.strip(), (shift or "").strip()
        if (wt or "").strip().upper() != "DUTY":
            skipped["non-DUTY (" + (wt or "").strip() + ")"] += 1
            continue
        if e not in emp:
            skipped["unknown employee " + e] += 1
            continue
        if shift not in SPELL or dpt not in subdept:
            skipped["unmapped shift/dept"] += 1
            continue
        des = emp_map.get(ocp)
        if des is None:
            cands = desig.get((dept_id.get(ocp[:2]), ocp_name.get(ocp, "")), [])
            des = cands[0] if cands else None
            if des is None:
                skipped["no designation for ocp " + ocp] += 1
        t = (wtime or "00:00:00").strip()
        rows.append((lid, emp[e], wdate, SPELL[shift], float(shr or 0), subdept[dpt], des, float(whr or 0),
                     float(gp or 0), f"{wdate} {t}"))
        for m in {m1.strip(), m2.strip()}:
            if m in mach:
                ebmc.append((lid, mach[m]))

    cur.execute("SELECT COUNT(*) FROM daily_attendance WHERE branch_id=%s AND attendance_date BETWEEN %s AND %s", (branch, d0, d1))
    n_att = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM daily_ebmc_attendance WHERE daily_atten_id IN (SELECT daily_atten_id FROM daily_attendance WHERE branch_id=%s AND attendance_date BETWEEN %s AND %s)", (branch, d0, d1))
    n_mc = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM pay_attendance WHERE branch_id=%s AND attendance_date BETWEEN %s AND %s", (branch, d0, d1))
    n_pay = cur.fetchone()[0]
    print(f"range {d0}..{d1} branch {branch} tenant {tenant}")
    print(f"will delete: daily_attendance {n_att}, daily_ebmc_attendance {n_mc}, pay_attendance {n_pay}")
    print(f"legacy Atten rows {len(legacy)} -> insert daily_attendance {len(rows)}, daily_ebmc_attendance {len(ebmc)}")
    print("skipped:", dict(skipped))
    print("rows without designation:", sum(1 for r in rows if r[6] is None))
    if not execute:
        print("DRY RUN - nothing changed. Re-run with --execute.")
        return

    # ── backup (DDL, outside the transaction) ──────────────────────────
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    wheres = {"daily_attendance": "branch_id=%s AND attendance_date BETWEEN %s AND %s",
              "daily_ebmc_attendance": "daily_atten_id IN (SELECT daily_atten_id FROM daily_attendance WHERE branch_id=%s AND attendance_date BETWEEN %s AND %s)",
              "pay_attendance": "branch_id=%s AND attendance_date BETWEEN %s AND %s"}
    for tbl, where in wheres.items():  # machine rows are found through their parent (some lack attendace_date)
        cur.execute(f"CREATE TABLE bak_{stamp}_{tbl} AS SELECT * FROM {tbl} WHERE {where}", (branch, d0, d1))
        cur.execute(f"SELECT COUNT(*) FROM bak_{stamp}_{tbl}")
        print(f"backup bak_{stamp}_{tbl}: {cur.fetchone()[0]} rows")
    my.commit()

    try:
        cur.execute("DELETE FROM daily_ebmc_attendance WHERE daily_atten_id IN (SELECT daily_atten_id FROM daily_attendance WHERE branch_id=%s AND attendance_date BETWEEN %s AND %s)", (branch, d0, d1))
        cur.execute("DELETE FROM pay_attendance WHERE branch_id=%s AND attendance_date BETWEEN %s AND %s", (branch, d0, d1))
        cur.execute("DELETE FROM daily_attendance WHERE branch_id=%s AND attendance_date BETWEEN %s AND %s", (branch, d0, d1))
        now = datetime.now()
        # eb_no carries the legacy Atten ID until the machine rows are linked
        cur.executemany("""INSERT INTO daily_attendance
              (eb_no, eb_id, attendance_date, attendance_source, attendance_type, attendance_mark, is_active, branch_id,
               spell_id, spell_hours, worked_department_id, worked_designation_id, status_id, working_hours,
               idle_hours, entry_time, update_date_time, created_date_time)
              VALUES (%s,%s,%s,'M','R','P',1,%s,%s,%s,%s,%s,'3',%s,%s,%s,%s,%s)""",
                        [(f"L{r[0]}", r[1], r[2], branch, r[3], r[4], r[5], r[6], r[7], r[8], r[9], now, now)
                         for r in rows])
        cur.execute("CREATE TEMPORARY TABLE _mc (atten_id INT, mc_id BIGINT)")
        cur.executemany("INSERT INTO _mc VALUES (%s,%s)", ebmc)
        cur.execute("""INSERT INTO daily_ebmc_attendance
              (daily_atten_id, eb_id, mc_id, branch_id, spell_id, attendace_date, designation_id, is_active, updated_date_time)
              SELECT d.daily_atten_id, d.eb_id, t.mc_id, d.branch_id, d.spell_id, d.attendance_date,
                     d.worked_designation_id, 1, NOW()
              FROM _mc t JOIN daily_attendance d ON d.eb_no = CONCAT('L', t.atten_id) AND d.branch_id=%s""", (branch,))
        cur.execute("UPDATE daily_attendance SET eb_no=NULL WHERE branch_id=%s AND attendance_date BETWEEN %s AND %s "
                    "AND eb_no LIKE 'L%%'", (branch, d0, d1))
        cur.execute("SELECT COUNT(*) FROM daily_attendance WHERE branch_id=%s AND attendance_date BETWEEN %s AND %s", (branch, d0, d1))
        got = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM daily_ebmc_attendance WHERE branch_id=%s AND attendace_date BETWEEN %s AND %s", (branch, d0, d1))
        got_mc = cur.fetchone()[0]
        assert got == len(rows) and got_mc == len(ebmc), f"count mismatch {got}/{len(rows)} {got_mc}/{len(ebmc)}"
        my.commit()
        print(f"COMMITTED: daily_attendance {got}, daily_ebmc_attendance {got_mc}")
    except Exception:
        my.rollback()
        print("FAILED - rolled back (backup tables kept)")
        raise


if __name__ == "__main__":
    main()
