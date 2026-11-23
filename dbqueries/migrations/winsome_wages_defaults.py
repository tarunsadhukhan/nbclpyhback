"""
Copy the legacy column defaults ('' / 0 / 'N') of the tables the Winsome wages process INSERTs into
(PayWages, PayWagesDetails, PayWagesHRALiab) onto their winsome mirrors. migrate_payowagesrate_ocp.py
builds the mirror DDL without defaults, and the ported SP inserts only a subset of columns (strict mode).

    python dbqueries/migrations/winsome_wages_defaults.py            # dry run: prints the ALTERs
    python dbqueries/migrations/winsome_wages_defaults.py --execute

Env: tenant DB from env/database.env (run from pyhback/), MSSQL_CONN = ODBC string of the Winsome legacy DB.
"""

import os
import sys

from dotenv import load_dotenv

load_dotenv("env/database.env")
import pymysql  # noqa: E402
import pyodbc  # noqa: E402

TABLES = ("PayWages", "PayWagesDetails", "PayWagesHRALiab")


def main() -> None:
    ms = pyodbc.connect(os.environ["MSSQL_CONN"]).cursor()
    my = pymysql.connect(host=os.environ["DATABASE_HOST"], port=int(os.environ["DATABASE_PORT"]),
                         user=os.environ["DATABASE_USER"], password=os.environ["DATABASE_PASSWORD"],
                         database="winsome")
    cur = my.cursor()
    for t in TABLES:
        for col, definition in ms.execute("""
                SELECT c.name, dc.definition FROM sys.columns c
                JOIN sys.default_constraints dc ON dc.parent_object_id = c.object_id AND dc.parent_column_id = c.column_id
                WHERE c.object_id = OBJECT_ID(?)""", t).fetchall():
            value = definition.strip("()").lstrip("N")  # ((0)) -> 0, (N'N') -> 'N', ('') -> ''
            cur.execute("SELECT data_type FROM information_schema.columns WHERE table_schema = 'winsome' "
                        "AND table_name = %s AND column_name = %s", (t, col))
            if cur.fetchone()[0] in ("date", "datetime") and value == "''":
                value = "'1900-01-01'"  # SQL Server casts '' to 1900-01-01
            sql = f"ALTER TABLE `{t}` ALTER COLUMN `{col}` SET DEFAULT {value}"
            print(sql)
            if "--execute" in sys.argv:
                cur.execute(sql)
    if "--execute" not in sys.argv:
        print("DRY RUN - nothing changed. Re-run with --execute.")


if __name__ == "__main__":
    main()
