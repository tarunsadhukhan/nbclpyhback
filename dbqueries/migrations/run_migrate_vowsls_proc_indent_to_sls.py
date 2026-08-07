"""
Runner for migrate_vowsls_proc_indent_to_sls.sql.

Usage:
    cd c:/code/vowerp3be
    .venv/Scripts/activate
    python dbqueries/migrations/run_migrate_vowsls_proc_indent_to_sls.py [--commit]

Without --commit: dry-run inside a transaction; rolls back after printing
counts. Pass --commit to persist.
"""
import sys
import pathlib
import pymysql
from dotenv import dotenv_values

ROOT = pathlib.Path(__file__).resolve().parents[2]
ENV  = dotenv_values(ROOT / "env" / "database.env")

SQL_FILE = ROOT / "dbqueries" / "migrations" / "migrate_vowsls_proc_indent_to_sls.sql"


def main():
    commit = "--commit" in sys.argv

    conn = pymysql.connect(
        host       = ENV["DATABASE_HOST"],
        port       = int(ENV["DATABASE_PORT"]),
        user       = ENV["DATABASE_USER"],
        password   = ENV["DATABASE_PASSWORD"],
        autocommit = False,
    )
    try:
        with conn.cursor() as c:
            # Pre-flight
            c.execute("SELECT COUNT(*) FROM sls.proc_indent")
            (target_before,) = c.fetchone()
            print(f"sls.proc_indent rows before: {target_before}")

            c.execute(
                "SELECT COUNT(*) FROM vowsls.tbl_proc_indent WHERE is_active = 1"
            )
            (source_active,) = c.fetchone()
            print(f"vowsls.tbl_proc_indent active rows to migrate: {source_active}")

            if target_before > 0:
                c.execute("""
                    SELECT COUNT(*)
                      FROM sls.proc_indent t
                      JOIN vowsls.tbl_proc_indent s
                        ON s.indent_id = t.indent_id
                     WHERE s.is_active = 1
                """)
                (collisions,) = c.fetchone()
                if collisions > 0:
                    raise RuntimeError(
                        f"Aborting: {collisions} indent_id collisions in target."
                    )

            # Execute migration. Strip line comments first so ';' inside
            # them does not break the statement splitter.
            raw = SQL_FILE.read_text(encoding="utf-8")
            cleaned = "\n".join(
                line for line in raw.splitlines()
                if not line.lstrip().startswith("--")
            )
            statements = [s.strip() for s in cleaned.split(";") if s.strip()]
            inserted = 0
            for stmt in statements:
                c.execute(stmt)
                inserted += c.rowcount

            # Post-flight verification
            c.execute("SELECT COUNT(*) FROM sls.proc_indent")
            (target_after,) = c.fetchone()
            print(f"sls.proc_indent rows after:  {target_after}")
            print(f"Rows inserted:               {inserted}")

            c.execute("""
                SELECT indent_id, indent_date, indent_no, indent_type_id,
                       branch_id, expense_type_id, project_id,
                       status_id, approval_level, active
                  FROM sls.proc_indent
                 ORDER BY indent_id DESC
                 LIMIT 5
            """)
            print("\nLast 5 inserted rows:")
            for row in c.fetchall():
                print(" ", row)

            c.execute("""
                SELECT status_id, approval_level, COUNT(*)
                  FROM sls.proc_indent
                 GROUP BY status_id, approval_level
                 ORDER BY status_id
            """)
            print("\nStatus distribution:")
            for row in c.fetchall():
                print(" ", row)

            c.execute("""
                SELECT indent_type_id, COUNT(*)
                  FROM sls.proc_indent
                 GROUP BY indent_type_id
            """)
            print("\nIndent type distribution:")
            for row in c.fetchall():
                print(" ", row)

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
