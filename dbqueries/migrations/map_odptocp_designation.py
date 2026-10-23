"""
Link the mirrored legacy occupation master nbjcl.ODPTOCP to designation_mst (adds ODPTOCP.designation_id and
fills empty designation_mst.occu_code),
so the wages process can find a worker's legacy OcpCode from pay_attendance.desig_id.

    python dbqueries/migrations/map_odptocp_designation.py            # dry run
    python dbqueries/migrations/map_odptocp_designation.py --execute  # add column (once) + fill

Env: tenant DB from env/database.env (run from pyhback/), MSSQL_PWD = SQL Server password,
TENANT_DB (default nbjcl), BRANCH_ID (default 87). Re-runnable; run again after re-migrating attendance.

1. Observed: legacy Atten (emp, date, shift) -> ocp_code joined to the migrated daily_attendance rows
   -> worked_designation_id; the majority designation per OcpCode wins.
2. Fallback for occupations never worked: designation of the department OcpCode[:2] with the same
   normalised name (first one).
"""

import collections
import os
import re
import sys

from dotenv import load_dotenv

load_dotenv("env/database.env")
import pymysql  # noqa: E402
import pyodbc  # noqa: E402

MSSQL = "DRIVER={ODBC Driver 17 for SQL Server};SERVER=162.245.218.10;DATABASE=Smart_Eye_Jute_Northbrook_Live;" \
        "UID=ERP;PWD=%s;TrustServerCertificate=yes"
norm = lambda s: re.sub(r"\s+", " ", (s or "").strip().upper())  # noqa: E731


def main() -> None:
    execute = "--execute" in sys.argv
    tenant, branch = os.getenv("TENANT_DB", "nbjcl"), int(os.getenv("BRANCH_ID", "87"))
    my = pymysql.connect(host=os.environ["DATABASE_HOST"], user=os.environ["DATABASE_USER"],
                         password=os.environ["DATABASE_PASSWORD"], database=tenant, autocommit=False)
    cur = my.cursor()
    ms = pyodbc.connect(MSSQL % os.environ["MSSQL_PWD"]).cursor()

    cur.execute("""SELECT o.emp_code, DATE_FORMAT(d.attendance_date, '%%Y-%%m-%%d'), sp.spell_code, d.worked_designation_id
                   FROM daily_attendance d JOIN hrms_ed_official_details o ON o.eb_id = d.eb_id AND o.branch_id = %s
                   JOIN spell_mst sp ON sp.spell_id = d.spell_id
                   WHERE d.branch_id = %s AND d.attendance_type = 'R' AND d.worked_designation_id IS NOT NULL""",
                (branch, branch))
    tenant_rows = {(e.strip(), dt, s.strip()): des for e, dt, s, des in cur.fetchall()}
    lo = min(k[1] for k in tenant_rows)
    ms.execute("SELECT emp_code, CONVERT(varchar(10), WDate, 23), WShift, ocp_code FROM Atten "
               "WHERE WDate >= ? AND work_type = 'DUTY'", lo)
    vote = collections.defaultdict(collections.Counter)
    for e, dt, s, ocp in ms.fetchall():
        des = tenant_rows.get(((e or "").strip(), dt, (s or "").strip()))
        if des:
            vote[(ocp or "").strip()][des] += 1

    cur.execute("SELECT d.dept_code, g.desig, g.designation_id FROM designation_mst g JOIN dept_mst d ON d.dept_id = g.dept_id "
                "WHERE g.branch_id = %s AND g.active = 1 ORDER BY g.designation_id", (branch,))
    by_name = {}
    for dept, name, did in cur.fetchall():
        by_name.setdefault((dept, norm(name)), did)

    cur.execute("SELECT OCPCode, OCPName FROM ODPTOCP")
    mapping, how = {}, collections.Counter()
    for code, name in cur.fetchall():
        if vote.get(code):
            mapping[code] = vote[code].most_common(1)[0][0]
            how["attendance"] += 1
        elif (code[:2], norm(name)) in by_name:
            mapping[code] = by_name[(code[:2], norm(name))]
            how["name"] += 1
        else:
            how["unmapped"] += 1
    split = {c: v for c, v in vote.items() if len(v) > 1}
    print(f"occupations mapped: {dict(how)}; occupations seen on >1 designation: {len(split)}")
    if not execute:
        print("DRY RUN - nothing changed. Re-run with --execute.")
        return
    cur.execute("SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = DATABASE() "
                "AND table_name = 'ODPTOCP' AND column_name = 'designation_id'")
    if not cur.fetchone()[0]:
        cur.execute("ALTER TABLE ODPTOCP ADD COLUMN designation_id INT NULL, ADD KEY idx_odptocp_desig (designation_id), "
                    "ADD KEY idx_odptocp_code (OCPCode)")
    cur.execute("UPDATE ODPTOCP SET designation_id = NULL")
    cur.executemany("UPDATE ODPTOCP SET designation_id = %s WHERE OCPCode = %s", [(d, c) for c, d in mapping.items()])
    # designation_mst.occu_code = legacy OcpCode (lowest when two share a designation); only empty
    # values are filled, so codes entered on the designation master are kept
    cur.execute("""UPDATE designation_mst g
                   JOIN (SELECT designation_id, MIN(OCPCode) code FROM ODPTOCP WHERE designation_id IS NOT NULL
                         GROUP BY designation_id) m ON m.designation_id = g.designation_id
                   SET g.occu_code = m.code
                   WHERE g.branch_id = %s AND IFNULL(g.occu_code, '') = ''""", (branch,))
    filled = cur.rowcount
    my.commit()
    cur.execute("SELECT COUNT(*), COUNT(designation_id), COUNT(DISTINCT designation_id) FROM ODPTOCP")
    print("COMMITTED: rows / with designation / distinct designations:", cur.fetchone())
    cur.execute("SELECT COUNT(*), SUM(IFNULL(occu_code, '') <> '') FROM designation_mst WHERE branch_id = %s", (branch,))
    print(f"designation_mst.occu_code filled now: {filled}; branch {branch} designations / with code:", cur.fetchone())


if __name__ == "__main__":
    main()
