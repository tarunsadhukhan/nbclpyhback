"""
Mirror the legacy Smart-Eye SQL Server `PayOWagesRate_OCP` into nbjcl.PayOWagesRate_OCP (same name, like
PayOWagesRate / PayODARate already there).

    python dbqueries/migrations/migrate_payowagesrate_ocp.py            # dry run: columns, DDL, row count
    python dbqueries/migrations/migrate_payowagesrate_ocp.py --execute  # create table + load (refuses if it holds rows)
    python dbqueries/migrations/migrate_payowagesrate_ocp.py ODPTOCP --execute  # any other legacy table, same way

Env: tenant DB from env/database.env (run from pyhback/), MSSQL_PWD = SQL Server password (login ERP),
TENANT_DB (default nbjcl).

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
    ms = pyodbc.connect(MSSQL % os.environ["MSSQL_PWD"]).cursor()
    meta = ms.execute("""SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH, NUMERIC_PRECISION, NUMERIC_SCALE,
                                IS_NULLABLE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = ?
                         ORDER BY ORDINAL_POSITION""", TABLE).fetchall()
    if not meta:
        sys.exit(f"{TABLE} not found on SQL Server")
    cols = [m[0] for m in meta]
    ddl = "CREATE TABLE IF NOT EXISTS `%s` (\n  %s\n) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci" % (
        TABLE, ",\n  ".join(f"`{m[0]}` {my_type(m[1], m[2], m[3], m[4])}"
                             f"{' NOT NULL' if m[5] == 'NO' else ' NULL'}" for m in meta))
    rows = [tuple(v.rstrip() if isinstance(v, str) else v for v in r)
            for r in ms.execute("SELECT %s FROM %s" % (", ".join(f"[{c}]" for c in cols), TABLE)).fetchall()]
    print(ddl)
    print(f"legacy rows {len(rows)}")
    if not execute:
        print("DRY RUN - nothing changed. Re-run with --execute.")
        return

    my = pymysql.connect(host=os.environ["DATABASE_HOST"], port=int(os.environ["DATABASE_PORT"]),
                         user=os.environ["DATABASE_USER"], password=os.environ["DATABASE_PASSWORD"],
                         database=tenant, autocommit=False)
    cur = my.cursor()
    cur.execute(ddl)
    cur.execute(f"SELECT COUNT(*) FROM `{TABLE}`")
    if cur.fetchone()[0]:
        sys.exit(f"{tenant}.{TABLE} already holds rows - refusing to load again")
    try:
        sql = "INSERT INTO `%s` (%s) VALUES (%s)" % (TABLE, ",".join(f"`{c}`" for c in cols), ",".join(["%s"] * len(cols)))
        for i in range(0, len(rows), 5000):
            cur.executemany(sql, rows[i:i + 5000])
        cur.execute(f"SELECT COUNT(*) FROM `{TABLE}`")
        got = cur.fetchone()[0]
        assert got == len(rows), f"count mismatch {got}/{len(rows)}"
        my.commit()
        print(f"COMMITTED: {tenant}.{TABLE} rows {got}")
    except Exception:
        my.rollback()
        print("FAILED - rolled back")
        raise


if __name__ == "__main__":
    main()
