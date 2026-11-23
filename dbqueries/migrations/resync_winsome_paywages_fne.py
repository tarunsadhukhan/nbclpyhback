"""
Re-sync one Winsome wages fortnight from legacy: replace winsome.PayWages rows of the FNE date with the live legacy
Smart_Eye_Jute_Purnasar_Winsome_Live PayWages rows (legacy re-ran its wages process after our mirror), then refresh
lowercase paywages the way the Winsome Wages process does (_sync_paywages). One transaction; dry run by default.
Before replacing, the current rows are copied to bak_<yyyymmddhhmm>_PayWages_<FNE> / _paywages_<FNE>.

    python dbqueries/migrations/resync_winsome_paywages_fne.py 2026-11-15            # dry run (rolls back)
    python dbqueries/migrations/resync_winsome_paywages_fne.py 2026-11-15 --execute

Env: env/database.env (MySQL) and sqlserver.env (legacy: host, database, username, password), run from pyhback/.
"""
import sys
from datetime import datetime

from dotenv import dotenv_values, load_dotenv

load_dotenv("env/database.env")
import os  # noqa: E402

import pyodbc  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from src.hrms.winsomeWagesProcess import _sync_paywages  # noqa: E402

FNE = sys.argv[1]
EXECUTE = "--execute" in sys.argv
COMP, LOC = "WIL", "Factory"


def main() -> None:
    e = {k.strip(): v.strip() for k, v in dotenv_values("sqlserver.env").items() if v}
    ms = pyodbc.connect(f"DRIVER={{ODBC Driver 18 for SQL Server}};SERVER={e['host']};DATABASE={e['database']};"
                        f"UID={e['username']};PWD={e['password']};TrustServerCertificate=yes").cursor()
    env = os.environ
    eng = create_engine(f"mysql+pymysql://{env['DATABASE_USER']}:{env['DATABASE_PASSWORD']}@{env['DATABASE_HOST']}:"
                        f"{env.get('DATABASE_PORT', 3306)}/winsome?charset=utf8mb4")
    with Session(eng) as db:
        mine = [r[0] for r in db.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_schema = DATABASE() "
            "AND table_name = 'PayWages' ORDER BY ordinal_position"))]
        legacy = {r[0].lower() for r in ms.execute(
            "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = 'PayWages'").fetchall()}
        cols = [c for c in mine if c.lower() in legacy]
        print("columns copied", len(cols), "| winsome-only:", [c for c in mine if c.lower() not in legacy])

        ms.execute("SELECT %s FROM PayWages WHERE CompCode = ? AND Location = ? AND EDate = ?"
                   % ", ".join(f"[{c}]" for c in cols), COMP, LOC, FNE)
        src = [tuple(v.rstrip() if isinstance(v, str) else v for v in r) for r in ms.fetchall()]
        pcodes = {r[cols.index("PCode")] for r in src}
        assert src and len(pcodes) == 1, f"expected legacy rows of one PCode, got {len(src)} rows {pcodes}"
        k = {"c": COMP, "l": LOC, "p": pcodes.pop(), "t": FNE}

        def stats(label):
            for t in ("PayWages", "paywages"):
                r = db.execute(text(f"SELECT COUNT(*), SUM(NetPayable) FROM {t} WHERE CompCode = :c AND Location = :l "
                                    "AND EDate = :t"), k).one()
                print(f"  {label} {t}: rows {r[0]}  NetPayable {r[1]}")

        stats("before")
        stamp = datetime.now().strftime("%Y%m%d%H%M")
        tag = FNE.replace("-", "")
        for t in ("PayWages", "paywages"):
            # CREATE TABLE ... SELECT commits implicitly in MySQL — only on --execute
            if EXECUTE:
                db.execute(text(f"CREATE TABLE bak_{stamp}_{t}_{tag} AS SELECT * FROM {t} "
                                "WHERE CompCode = :c AND Location = :l AND EDate = :t"), k)
        db.execute(text("DELETE FROM PayWages WHERE CompCode = :c AND Location = :l AND EDate = :t"), k)
        ins = "INSERT INTO PayWages (%s) VALUES (%s)" % (",".join(f"`{c}`" for c in cols),
                                                          ",".join(f":v{i}" for i in range(len(cols))))
        db.execute(text(ins), [{f"v{i}": v for i, v in enumerate(r)} for r in src])
        _sync_paywages(db, k)
        stats("after")
        legacy_sum = ms.execute("SELECT COUNT(*), SUM(NetPayable) FROM PayWages WHERE CompCode = ? AND Location = ? "
                                "AND EDate = ?", COMP, LOC, FNE).fetchone()
        print(f"  legacy PayWages: rows {legacy_sum[0]}  NetPayable {legacy_sum[1]}")
        if EXECUTE:
            db.commit()
            print(f"COMMITTED (backups bak_{stamp}_PayWages_{tag}, bak_{stamp}_paywages_{tag})")
        else:
            db.rollback()
            print("DRY RUN - rolled back")


if __name__ == "__main__":
    main()
