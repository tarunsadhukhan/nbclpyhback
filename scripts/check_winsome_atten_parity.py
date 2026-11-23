"""
Parity check for the Winsome Attendance Process port (src/hrms/winsomeAttendanceProcess.py).

Runs ATTEN_PROCESS_BULK for a date range on the winsome mirror INSIDE a transaction, compares the rebuilt
ATTEN rows with legacy ATTEN on SQL Server, then rolls back (nothing is written).

    PYTHONPATH=. .venv/Scripts/python.exe scripts/check_winsome_atten_parity.py 2026-11-01 2026-11-05

Legacy creds come from sqlserver.env (host/database/username/password). Exit code 1 when any row differs.
"""

import sys
from datetime import date
from decimal import Decimal

from dotenv import dotenv_values, load_dotenv

load_dotenv("env/database.env")
import pyodbc  # noqa: E402
from sqlalchemy.sql import text  # noqa: E402

from src.config.db import get_tenant_engine  # noqa: E402

COLS = ["ID", "mch1_code", "mch2_code", "Job1_code", "work_type", "Shift_HR", "GatePass_HR", "Work_HR",
        "Night_HR", "HeadCount"]


def norm(v):
    if isinstance(v, (Decimal, float)):
        return round(float(v), 3)
    return str(v).strip().upper() if v is not None else None


def main(f: date, t: date) -> int:
    from sqlalchemy.orm import Session

    from src.hrms.winsomeAttendanceProcess import atten_process_bulk

    e = {k.strip(): (v or "").strip().strip("'") for k, v in dotenv_values("sqlserver.env").items()}
    ms = pyodbc.connect(f"DRIVER={{ODBC Driver 18 for SQL Server}};SERVER={e['host']};DATABASE={e['database']};"
                        f"UID={e['username']};PWD={e['password']};TrustServerCertificate=yes")
    sel = f"SELECT emp_code, WDate, WShift, {', '.join(COLS)} FROM ATTEN WHERE WDate >= ? AND WDate <= ?"
    legacy = {(r[0].strip(), str(r[1]), r[2].strip()): [norm(x) for x in r[3:]]
              for r in ms.cursor().execute(sel, f, t).fetchall()}
    raw_legacy = ms.cursor().execute("SELECT COUNT(*) FROM ATTENDANCE WHERE WDate >= ? AND WDate <= ?", f, t).fetchone()[0]

    with Session(get_tenant_engine("winsome")) as db:
        raw_mirror = db.execute(text("SELECT COUNT(*) FROM ATTENDANCE WHERE WDate >= :f AND WDate <= :t"),
                                {"f": f, "t": t}).scalar()
        done = atten_process_bulk(db, f, t)
        ours = {(r[0], str(r[1]), r[2]): [norm(x) for x in r[3:]]
                for r in db.execute(text(sel.replace("?", ":f", 1).replace("?", ":t")), {"f": f, "t": t})}
        db.rollback()

    print(f"raw ATTENDANCE rows legacy={raw_legacy} mirror={raw_mirror}; shifts processed={len(done)}")
    print(f"ATTEN rows legacy={len(legacy)} port={len(ours)}")
    only_l, only_o = legacy.keys() - ours.keys(), ours.keys() - legacy.keys()
    diff = [(k, c, legacy[k][i], ours[k][i]) for k in legacy.keys() & ours.keys()
            for i, c in enumerate(COLS) if legacy[k][i] != ours[k][i]]
    print(f"only legacy={len(only_l)} only port={len(only_o)} differing cells={len(diff)}")
    for x in sorted(only_l)[:5]:
        print("  only legacy", x)
    for x in sorted(only_o)[:5]:
        print("  only port", x)
    for x in diff[:15]:
        print("  diff", x)
    return 1 if (only_l or only_o or diff) else 0


if __name__ == "__main__":
    sys.exit(main(date.fromisoformat(sys.argv[1]), date.fromisoformat(sys.argv[2])))
