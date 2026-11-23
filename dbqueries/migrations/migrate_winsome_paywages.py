"""
Replace the P-period (wages) rows of winsome.paywages with legacy Winsome `PayWages`.

winsome.paywages was cloned from nbjcl and held Northbrook's wages (found 2026-11-22); the S-period
(salary) rows are left alone. Only the columns both tables share are copied (legacy CreateDate ->
CreatedDate); the Winsome-only columns (PL/CL/FBasicInc/PBasic...) live in the full mirror `PayWages`
(migrate_payowagesrate_ocp.py PayWages).

    python dbqueries/migrations/migrate_winsome_paywages.py            # dry run
    python dbqueries/migrations/migrate_winsome_paywages.py --execute  # backup bak_<stamp>_paywages_P, delete, load

Env: tenant DB from env/database.env (run from pyhback/), MSSQL_CONN = ODBC string of the Winsome legacy DB.
"""

import os
import sys
from datetime import datetime

from dotenv import load_dotenv

load_dotenv("env/database.env")
import pymysql  # noqa: E402
import pyodbc  # noqa: E402

RENAME = {"CreateDate": "CreatedDate"}  # legacy Winsome name -> paywages name


def main() -> None:
    execute = "--execute" in sys.argv
    ms = pyodbc.connect(os.environ["MSSQL_CONN"]).cursor()
    my = pymysql.connect(host=os.environ["DATABASE_HOST"], port=int(os.environ["DATABASE_PORT"]),
                         user=os.environ["DATABASE_USER"], password=os.environ["DATABASE_PASSWORD"],
                         database="winsome", autocommit=False)
    cur = my.cursor()
    cur.execute("SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA='winsome' AND TABLE_NAME='paywages'")
    dst = {r[0] for r in cur.fetchall()}
    src = [r[0] for r in ms.execute("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME='PayWages' "
                                    "ORDER BY ORDINAL_POSITION").fetchall()]
    cols = [c for c in src if RENAME.get(c, c) in dst]
    print("not copied (Winsome-only):", [c for c in src if c not in cols])
    # paywages-only NOT NULL columns without a default (strict mode): 0 / '' / 1900-01-01
    cur.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_schema = 'winsome' "
                "AND table_name = 'paywages' AND is_nullable = 'NO' AND column_default IS NULL")
    have = {RENAME.get(c, c) for c in cols}
    fill = {c: ("" if t in ("varchar", "char", "text", "longtext") else "1900-01-01" if t in ("date", "datetime") else 0)
            for c, t in cur.fetchall() if c not in have}
    print("filled with defaults:", sorted(fill))
    rows = [tuple(v.rstrip() if isinstance(v, str) else v for v in r) + tuple(fill.values())
            for r in ms.execute("SELECT %s FROM PayWages WHERE PCode LIKE 'P%%'" % ",".join(f"[{c}]" for c in cols))]
    cur.execute("SELECT COUNT(*), SUM(PCName='VOWERP PROCESS') FROM paywages WHERE PCode LIKE 'P%'")
    print("winsome.paywages P rows now %s (VOWERP PROCESS %s) -> legacy rows %d" % (*cur.fetchone(), len(rows)))
    if not execute:
        print("DRY RUN - nothing changed. Re-run with --execute.")
        return

    bak = f"bak_{datetime.now():%Y%m%d_%H%M}_paywages_P"
    cur.execute(f"CREATE TABLE {bak} AS SELECT * FROM paywages WHERE PCode LIKE 'P%'")
    my.commit()
    print("backup", bak)
    try:
        cur.execute("DELETE FROM paywages WHERE PCode LIKE 'P%'")
        names = [RENAME.get(c, c) for c in cols] + list(fill)
        sql = "INSERT INTO paywages (%s) VALUES (%s)" % (",".join(f"`{c}`" for c in names),
                                                         ",".join(["%s"] * len(names)))
        for i in range(0, len(rows), 5000):
            cur.executemany(sql, rows[i:i + 5000])
        cur.execute("SELECT COUNT(*) FROM paywages WHERE PCode LIKE 'P%'")
        got = cur.fetchone()[0]
        assert got == len(rows), f"count mismatch {got}/{len(rows)}"
        my.commit()
        print(f"COMMITTED: paywages P rows {got}")
    except Exception:
        my.rollback()
        print("FAILED - rolled back (backup kept)")
        raise


if __name__ == "__main__":
    main()
