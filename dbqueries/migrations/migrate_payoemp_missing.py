"""
Add the legacy Smart-Eye PayOEMP employees whose ECode is missing from the tenant HRMS tables.

    python dbqueries/migrations/migrate_payoemp_missing.py            # dry run (default)
    python dbqueries/migrations/migrate_payoemp_missing.py --execute  # insert
    python dbqueries/migrations/migrate_payoemp_missing.py 200991 48114 --execute  # only these ECodes
    python dbqueries/migrations/migrate_payoemp_missing.py --retire-only --execute  # skip the insert

Legacy Active='N' (user rule, 2026-10-25): every hrms_ed_* row of the employee gets active=1 and
hrms_ed_personal_details.status_id=42 (RETIRED) — applied to the inserted rows and, after a bak_<stamp>_*
backup, to the employees already in the tenant branch.

Env: tenant DB from env/database.env (run from pyhback/), MSSQL_PWD = SQL Server login password,
TENANT_DB (default nbjcl), BRANCH_ID (default 87).

Row → hrms_ed_* mapping is scripts/import_worker_muster.py's (the WORK MUSTER workbook was a
PayOEMP export). Differences: OcpCode → designation via the mirrored ODPTOCP.designation_id, and the
category falls back to Grade (OUTSIDER / CONTRACTOR) when EGroup is blank, matching the existing rows.
"""

import collections
import os
import sys
from datetime import date, datetime

STATUS_RETIRED = 42
# hrms tables keyed by eb_id with an `active` column
ACTIVE_TABLES = ("hrms_ed_personal_details", "hrms_ed_official_details", "hrms_ed_contact_details",
                 "hrms_ed_address_details", "hrms_ed_bank_details", "hrms_ed_pf", "hrms_ed_esi",
                 "hrms_ed_resign_details", "hrms_experience_details")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
from dotenv import load_dotenv  # noqa: E402

load_dotenv("env/database.env")
import pymysql  # noqa: E402
import pyodbc  # noqa: E402
from import_worker_muster import CHUNK, COUNTRY_INDIA, INSERTS, UNASSIGNED, build, norm  # noqa: E402

MSSQL = "DRIVER={ODBC Driver 17 for SQL Server};SERVER=162.245.218.10;DATABASE=Smart_Eye_Jute_Northbrook_Live;" \
        "UID=ERP;PWD=%s;TrustServerCertificate=yes"


def one(cur, sql, params=()):
    cur.execute(sql, params)
    row = cur.fetchone()
    return row[0] if row else None


def main() -> None:
    execute = "--execute" in sys.argv
    only = {a for a in sys.argv[1:] if not a.startswith("--")}
    tenant, branch = os.getenv("TENANT_DB", "nbjcl"), int(os.getenv("BRANCH_ID", "87"))
    my = pymysql.connect(host=os.environ["DATABASE_HOST"], user=os.environ["DATABASE_USER"],
                         password=os.environ["DATABASE_PASSWORD"], database=tenant, autocommit=False,
                         charset="utf8mb4")
    cur = my.cursor()
    ms = pyodbc.connect(MSSQL % os.environ["MSSQL_PWD"], timeout=30).cursor()

    # ── fallbacks (created by import_worker_muster) ────────────────────
    dept = one(cur, "SELECT dept_id FROM dept_mst WHERE dept_desc=%s AND branch_id=%s", (UNASSIGNED, branch))
    fb = {"sub_dept_id": one(cur, "SELECT sub_dept_id FROM sub_dept_mst WHERE dept_id=%s", (dept,)),
          "designation_id": one(cur, "SELECT designation_id FROM designation_mst WHERE dept_id=%s AND desig=%s",
                                (dept, UNASSIGNED)),
          "cata_id": one(cur, "SELECT MIN(cata_id) FROM category_mst WHERE cata_desc=%s AND branch_id=%s",
                         (UNASSIGNED, branch))}
    if None in fb.values():
        raise SystemExit(f"UNASSIGNED fallback masters missing in {tenant}: {fb}")

    # ── lookups ────────────────────────────────────────────────────────
    cur.execute("SELECT d.designation_id, d.dept_id, dm.dept_desc, d.desig FROM designation_mst d "
                "JOIN dept_mst dm ON dm.dept_id=d.dept_id WHERE d.branch_id=%s ORDER BY d.designation_id", (branch,))
    desigs = cur.fetchall()
    by_name = {}
    for d in desigs:
        by_name.setdefault((norm(d[2]), norm(d[3])), d[0])
    cur.execute("SELECT OCPCode, designation_id FROM ODPTOCP WHERE designation_id IS NOT NULL")
    ocp2desig = {int(c): d for c, d in cur.fetchall() if c and c.strip().isdigit()}
    cur.execute("SELECT sub_dept_id, dept_id FROM sub_dept_mst")
    dept2sub = {d: s for s, d in cur.fetchall()}
    cur.execute("SELECT dept_id, dept_desc FROM dept_mst WHERE branch_id=%s", (branch,))
    name2dept = {}
    for d, desc in cur.fetchall():
        name2dept.setdefault(norm(desc), d)
    # category_mst has duplicate descriptions — take the id the existing employees use most
    cur.execute("SELECT c.cata_desc, c.cata_id, COUNT(o.eb_id) n FROM category_mst c "
                "LEFT JOIN hrms_ed_official_details o ON o.catagory_id=c.cata_id "
                "WHERE c.branch_id=%s GROUP BY c.cata_id ORDER BY n DESC, c.cata_id", (branch,))
    categories = {}
    for desc, cid, _ in cur.fetchall():
        categories.setdefault(norm(desc), cid)
    cur.execute("SELECT state_id, state FROM state_mst WHERE country_id=%s", (COUNTRY_INDIA,))
    states = {norm(n): i for i, n in cur.fetchall()}
    lk = {"ocp2desig": ocp2desig, "by_name": by_name, "desig_dept": {d[0]: d[1] for d in desigs},
          "dept2sub": dept2sub, "name2dept": name2dept, "categories": categories, "states": states}

    # ── legacy rows missing from the tenant ────────────────────────────
    cur.execute("SELECT TRIM(emp_code) FROM hrms_ed_official_details WHERE emp_code IS NOT NULL")
    have = {c for (c,) in cur.fetchall()}  # all branches: emp_code is unique per tenant
    ms.execute("SELECT * FROM PayOEMP ORDER BY ECode")
    cols = [c[0] for c in ms.description]
    rows = []
    for t in ms.fetchall():
        r = dict(zip(cols, t))
        code = (r["ECode"] or "").strip()
        if not code or code in have or (only and code not in only):
            continue
        # import_worker_muster reads Excel cells: dates arrive as datetime, the code as "C.NO."
        r = {k: datetime(v.year, v.month, v.day) if isinstance(v, date) and not isinstance(v, datetime) else v
             for k, v in r.items()}
        r["C.NO."] = code
        r["EGroup"] = (r["EGroup"] or "").strip() or r["Grade"]
        rows.append(r)
    if only - {r["C.NO."] for r in rows}:
        print(f"already in {tenant} or not in PayOEMP: {sorted(only - {r['C.NO.'] for r in rows})}")

    if "--retire-only" in sys.argv:
        rows = []
    first_eb_id = one(cur, "SELECT COALESCE(MAX(eb_id), 0) + 1 FROM hrms_ed_personal_details")
    payloads, rep = build(rows, lk, fb, branch, first_eb_id, set(have))
    print(f"missing ECodes: {len(rows)}  (by Grade: {dict(collections.Counter(r['Grade'] for r in rows))})")
    for k, v in sorted(rep.items()):
        print(f"  {k:32} {v}")
    # personal tuple ends (..., branch_id, active, status_id)
    inactive = {r["C.NO."] for r in rows if norm(r["Active"]) == "N"}
    code_of = {t[0]: t[7] for t in payloads["official"]}
    payloads["personal"] = [t[:-2] + ((1, STATUS_RETIRED) if code_of[t[0]] in inactive else t[-2:])
                            for t in payloads["personal"]]
    for k in INSERTS:
        print(f"  rows {k:27} {len(payloads[k])}")

    # existing tenant employees inactive in legacy → active=1, RETIRED
    ms.execute("SELECT LTRIM(RTRIM(ECode)) FROM PayOEMP WHERE Active='N'")
    legacy_n = {c for (c,) in ms.fetchall() if not only or c in only}
    cur.execute("SELECT eb_id, TRIM(emp_code) FROM hrms_ed_official_details WHERE branch_id=%s", (branch,))
    retire = sorted({e for e, c in cur.fetchall() if c in legacy_n})
    cur.execute("CREATE TEMPORARY TABLE _retire (eb_id INT PRIMARY KEY)")
    cur.executemany("INSERT INTO _retire VALUES (%s)", [(e,) for e in retire])
    print(f"existing legacy Active='N' employees in branch {branch}: {len(retire)}")
    for t in ACTIVE_TABLES:
        extra = " OR x.status_id<>%d" % STATUS_RETIRED if t == "hrms_ed_personal_details" else ""
        n = one(cur, f"SELECT COUNT(*) FROM {t} x JOIN _retire USING (eb_id) WHERE x.active<>1{extra}")
        print(f"  to update {t:32} {n}")
    if not execute:
        print("DRY RUN — nothing written. Re-run with --execute.")
        return

    stamp = datetime.now().strftime("%Y%m%d%H%M")
    for t in ACTIVE_TABLES:  # DDL commits implicitly — backups go before the transaction's writes
        cur.execute(f"CREATE TABLE bak_{stamp}_{t} AS SELECT x.* FROM {t} x JOIN _retire USING (eb_id)")
    for t in ACTIVE_TABLES:
        cur.execute(f"UPDATE {t} x JOIN _retire USING (eb_id) SET x.active=1")
    cur.execute("UPDATE hrms_ed_personal_details x JOIN _retire USING (eb_id) SET x.status_id=%s",
                (STATUS_RETIRED,))
    print(f"updated {len(retire)} existing employees (backups bak_{stamp}_*)")

    for k, (sql, const) in INSERTS.items():  # dict order = FK parents first
        data = [t + const for t in payloads[k]]
        for i in range(0, len(data), CHUNK):
            cur.executemany(sql, data[i:i + CHUNK])
    my.commit()
    if rows:
        print(f"COMMITTED to {tenant} branch {branch}: eb_id {first_eb_id}..{first_eb_id + rep['employees'] - 1}")
    else:
        print("COMMITTED")


if __name__ == "__main__":
    main()
