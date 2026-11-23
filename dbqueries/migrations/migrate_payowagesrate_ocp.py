"""
Mirror the legacy Smart-Eye SQL Server `PayOWagesRate_OCP` into nbjcl.PayOWagesRate_OCP (same name, like
PayOWagesRate / PayODARate already there).

    python dbqueries/migrations/migrate_payowagesrate_ocp.py            # dry run: columns, DDL, row count
    python dbqueries/migrations/migrate_payowagesrate_ocp.py --execute  # create table + load (refuses if it holds rows)
    python dbqueries/migrations/migrate_payowagesrate_ocp.py ODPTOCP --execute  # any other legacy table, same way
    python dbqueries/migrations/migrate_payowagesrate_ocp.py PayMAtten --execute --replace  # re-sync: delete + reload

Face registrations for Winsome Reports: EmpImage --skip=ActualImage --index=emp_code
Re-sync a date range only: ATTEN "--where=WDate BETWEEN '2026-11-01' AND '2026-11-15'" --execute --replace
Filtered + indexed (Winsome wages inputs): ATTEN "--where=WDate>='2025-01-01'" --index=emp_code,WDate;WDate

--replace is for pure mirrors that legacy still owns (PayOEMP, PayOSAL, PayMAtten); never PaySalary or other
tables the tenant processes write to.

Env: tenant DB from env/database.env (run from pyhback/), MSSQL_PWD = SQL Server password (login ERP),
TENANT_DB (default nbjcl), MSSQL_CONN = full ODBC string to use another legacy source instead.

Winsome production (menu "Production"): TENANT_DB=winsome MSSQL_CONN="DRIVER={ODBC Driver 18 for SQL Server};
SERVER=localhost;DATABASE=Smart_Eye_Jute_Purnasar_Winsome_Live;Trusted_Connection=yes;TrustServerCertificate=yes"
for PayOProdWDG PayOProdBMG PayOProdWVG PayOProdSACK PayProdAll PayProdWIL PayOQLT ODPT.

The MySQL DDL is built from the legacy INFORMATION_SCHEMA, so the copy has exactly the legacy columns
(utf8mb4_unicode_ci like paywages). Text values are right-trimmed (legacy CHAR padding).
"""

import os
import sys

from dotenv import load_dotenv

load_dotenv("env/database.env")
import pymysql  # noqa: E402
import pyodbc  # noqa: E402

TABLE = next((a for a in sys.argv[1:] if not a.startswith("--")), "PayOWagesRate_OCP")
# --where=<T-SQL filter> copies only matching rows (e.g. ATTEN from 2025); --index=ECode,EDate;WDate adds
# one MySQL index per ';'-separated column list after the load.
OPT = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
MSSQL = "DRIVER={ODBC Driver 17 for SQL Server};SERVER=162.245.218.10;DATABASE=Smart_Eye_Jute_Northbrook_Live;" \
        "UID=ERP;PWD=%s;TrustServerCertificate=yes"


def my_type(t: str, size, prec, scale) -> str:
    """SQL Server column type -> MySQL column type."""
    t = t.lower()
    if t in ("char", "varchar", "nchar", "nvarchar"):
        return "LONGTEXT" if size == -1 or size > 4000 else f"VARCHAR({size})"
    if t in ("text", "ntext", "xml"):
        return "LONGTEXT"
    if t in ("decimal", "numeric"):
        return f"DECIMAL({prec},{scale})"
    if t in ("money", "smallmoney"):
        return "DECIMAL(19,4)"
    if t in ("datetime", "datetime2", "smalldatetime"):
        return "DATETIME"
    return {"int": "INT", "bigint": "BIGINT", "smallint": "SMALLINT", "tinyint": "TINYINT", "bit": "TINYINT(1)",
            "float": "DOUBLE", "real": "FLOAT", "date": "DATE", "time": "TIME",
            "uniqueidentifier": "CHAR(36)"}.get(t, "LONGTEXT")  # ponytail: unknown types land as text


def main() -> None:
    execute = "--execute" in sys.argv
    tenant = os.getenv("TENANT_DB", "nbjcl")
    # MSSQL_CONN overrides the source, e.g. the local Winsome copy (Windows auth) for TENANT_DB=winsome
    ms = pyodbc.connect(os.getenv("MSSQL_CONN") or MSSQL % os.environ["MSSQL_PWD"]).cursor()
    meta = ms.execute("""SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH, NUMERIC_PRECISION, NUMERIC_SCALE,
                                IS_NULLABLE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = ?
                         ORDER BY ORDINAL_POSITION""", TABLE).fetchall()
    if not meta:
        sys.exit(f"{TABLE} not found on SQL Server")
    # --skip=ActualImage leaves heavy columns out (EmpImage photos are ~450 MB of base64 no report reads)
    skip = {c.lower() for c in OPT.get("skip", "").split(",") if c}
    meta = [m for m in meta if m[0].lower() not in skip]
    cols = [m[0] for m in meta]
    ddl = "CREATE TABLE IF NOT EXISTS `%s` (\n  %s\n) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci" % (
        TABLE, ",\n  ".join(f"`{m[0]}` {my_type(m[1], m[2], m[3], m[4])}"
                             f"{' NOT NULL' if m[5] == 'NO' else ' NULL'}" for m in meta))
    where = f" WHERE {OPT['where']}" if "where" in OPT else ""
    n_src = ms.execute(f"SELECT COUNT(*) FROM {TABLE}{where}").fetchone()[0]
    print(ddl)
    print(f"legacy rows {n_src}")
    if not execute:
        print("DRY RUN - nothing changed. Re-run with --execute.")
        return

    my = pymysql.connect(host=os.environ["DATABASE_HOST"], port=int(os.environ["DATABASE_PORT"]),
                         user=os.environ["DATABASE_USER"], password=os.environ["DATABASE_PASSWORD"],
                         database=tenant, autocommit=False)
    cur = my.cursor()
    cur.execute(ddl)
    cur.execute(f"SELECT COUNT(*) FROM `{TABLE}`")
    if cur.fetchone()[0] and "--replace" not in sys.argv:
        sys.exit(f"{tenant}.{TABLE} already holds rows - refusing to load again")
    try:
        if "--replace" in sys.argv:
            # with --where only those rows are replaced (the filter must be valid in T-SQL and MySQL alike)
            cur.execute(f"DELETE FROM `{TABLE}`{where}")
        sql = "INSERT INTO `%s` (%s) VALUES (%s)" % (TABLE, ",".join(f"`{c}`" for c in cols), ",".join(["%s"] * len(cols)))
        # streamed in 5000-row batches: ATTEN/ATTENDANCE (2M+ rows) don't fit in memory as one list
        ms.execute("SELECT %s FROM %s%s" % (", ".join(f"[{c}]" for c in cols), TABLE, where))
        sent = 0  # legacy is live: rows read, not the earlier COUNT, are what must land
        while batch := ms.fetchmany(5000):
            cur.executemany(sql, [tuple(v.rstrip() if isinstance(v, str) else v for v in r) for r in batch])
            sent += len(batch)
        cur.execute(f"SELECT COUNT(*) FROM `{TABLE}`{where if '--replace' in sys.argv else ''}")
        got = cur.fetchone()[0]
        assert got == sent, f"count mismatch {got}/{sent}"
        my.commit()
        for i, ix in enumerate(filter(None, OPT.get("index", "").split(";"))):
            try:
                cur.execute(f"CREATE INDEX ix_mirror_{i} ON `{TABLE}` (%s)" % ",".join(f"`{c}`" for c in ix.split(",")))
            except pymysql.err.OperationalError as e:  # already there on a --replace re-sync
                print("index", ix, e.args[1])
        print(f"COMMITTED: {tenant}.{TABLE} rows {got}")
    except Exception:
        my.rollback()
        print("FAILED - rolled back")
        raise


if __name__ == "__main__":
    main()
