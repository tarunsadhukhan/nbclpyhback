"""
Runner for seed_procurement_reports_menu.sql — seeds the Procurement reports_1
menu rows (menu_mst report=1 children of menu 920) + their role_menu_map grants
into dev3.

Usage:
    cd d:/vownextjs/vowerp3be
    .venv/Scripts/activate
    python dbqueries/migrations/run_seed_procurement_reports_menu.py [--commit] [--db dev3]

Without --commit: dry-run inside a transaction; rolls back after printing the
resulting report-menu tree. Pass --commit to persist. Idempotent (INSERT IGNORE
on the UNIQUE menu_name + NOT EXISTS on role maps), so safe to re-run.
"""
import sys
import pathlib
import pymysql
from dotenv import dotenv_values

ROOT = pathlib.Path(__file__).resolve().parents[2]
ENV = dotenv_values(ROOT / "env" / "database.env")

SQL_FILE = ROOT / "dbqueries" / "migrations" / "seed_procurement_reports_menu.sql"

PARENT_MENU_ID = 920

# Target tenant DB. dev3 is the QA/dev tenant — the default for all new work.
DB = "dev3"
if "--db" in sys.argv:
    DB = sys.argv[sys.argv.index("--db") + 1]


def report_children(cursor):
    cursor.execute(
        """
        SELECT menu_id, menu_name, menu_path, order_by, active
          FROM menu_mst
         WHERE menu_parent_id = %s AND report = 1
         ORDER BY active DESC, order_by, menu_id
        """,
        (PARENT_MENU_ID,),
    )
    return cursor.fetchall()


def main():
    commit = "--commit" in sys.argv

    conn = pymysql.connect(
        host=ENV["DATABASE_HOST"],
        port=int(ENV["DATABASE_PORT"]),
        user=ENV["DATABASE_USER"],
        password=ENV["DATABASE_PASSWORD"],
        database=DB,
        autocommit=False,
    )
    try:
        with conn.cursor() as c:
            print(f"Target DB: {DB}; parent hub menu_id: {PARENT_MENU_ID}")
            print("\nReport children of hub BEFORE:")
            for row in report_children(c):
                print(" ", row)

            # Execute migration. Strip line comments first so ';' inside them
            # does not break the statement splitter.
            raw = SQL_FILE.read_text(encoding="utf-8")
            cleaned = "\n".join(
                line for line in raw.splitlines()
                if not line.lstrip().startswith("--")
            )
            statements = [s.strip() for s in cleaned.split(";") if s.strip()]
            affected = 0
            for stmt in statements:
                c.execute(stmt)
                affected += c.rowcount

            print(f"\nStatements run: {len(statements)}; rows affected: {affected}")

            print("\nReport children of hub AFTER:")
            for row in report_children(c):
                print(" ", row)

            c.execute(
                """
                SELECT m.menu_path, rm.role_id, rm.access_type_id
                  FROM role_menu_map rm
                  JOIN menu_mst m ON m.menu_id = rm.menu_id
                 WHERE m.menu_parent_id = %s AND m.report = 1 AND m.active = 1
                   AND m.menu_path LIKE 'procurement/reports_1/%%'
                 ORDER BY m.menu_path, rm.role_id
                """,
                (PARENT_MENU_ID,),
            )
            print("\nRole maps for active report rows:")
            for row in c.fetchall():
                print(" ", row)

            c.execute(
                "SELECT role_id, access_type_id FROM role_menu_map WHERE menu_id = %s ORDER BY role_id",
                (PARENT_MENU_ID,),
            )
            print(f"\nHub {PARENT_MENU_ID} role grants:", c.fetchall())

        if commit:
            conn.commit()
            print("\nCOMMITTED.")
        else:
            conn.rollback()
            print("\nDRY RUN — rolled back. Re-run with --commit to persist.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
