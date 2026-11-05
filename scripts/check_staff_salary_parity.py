"""Parity check: run the staff salary port for a legacy-processed S-period in a transaction, diff PaySalary / paywages
against legacy SQL Server, roll back.  MSSQL_PWD=... python scripts/check_staff_salary_parity.py S20260902 2026-09-01 2026-09-30"""
import os, sys, collections
from decimal import Decimal
from dotenv import load_dotenv
load_dotenv("env/database.env")
sys.path.insert(0, ".")
import pyodbc
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from src.hrms.staffSalaryProcess import run_salary_process, SUB_GROUPS

PCODE, F, T = sys.argv[1], sys.argv[2], sys.argv[3]
eng = create_engine("mysql+pymysql://%s:%s@%s:%s/nbjcl" % (os.environ["DATABASE_USER"], os.environ["DATABASE_PASSWORD"].replace("@", "%40").replace("#", "%23"),
                    os.environ["DATABASE_HOST"], os.environ.get("DATABASE_PORT", "3306")))
ms = pyodbc.connect("DRIVER={ODBC Driver 17 for SQL Server};SERVER=162.245.218.10;DATABASE=Smart_Eye_Jute_Northbrook_Live;UID=ERP;PWD=%s;TrustServerCertificate=yes" % os.environ["MSSQL_PWD"]).cursor()

def legacy(table):
    ms.execute(f"SELECT * FROM {table} WHERE PCode=? AND Location='Factory'", PCODE)
    cols = [c[0] for c in ms.description]
    return {(r.ECode.strip()): dict(zip(cols, r)) for r in ms.fetchall()}

LS, LW = legacy("PaySalary"), legacy("PayWages")
db = Session(eng)
try:
    pid = db.execute(text("SELECT ID FROM pay_period WHERE code=:p AND branch_id=87"), {"p": PCODE}).scalar()
    if not pid:
        db.execute(text("INSERT INTO pay_period (code, name, FROM_DATE, TO_DATE, branch_id, COMPANY_ID, year, no_of_days, STATUS, updated_by, updated_date_time) "
                        "VALUES (:p, 'TEST', :f, :t, 87, 106, 2026, DAY(:t), 1, 0, NOW())"), {"p": PCODE, "f": F, "t": T})
        pid = db.execute(text("SELECT LAST_INSERT_ID()")).scalar()
    db.execute(text("DELETE FROM PaySalary WHERE PCode=:p"), {"p": PCODE})
    db.execute(text("DELETE FROM paywages WHERE PCode=:p"), {"p": PCODE})
    for sg in SUB_GROUPS:
        print(run_salary_process(db, 87, pid, sg, 0, "parity"))
    for name, leg, sql in (("PaySalary", LS, "SELECT * FROM PaySalary WHERE PCode=:p"), ("paywages", LW, "SELECT * FROM paywages WHERE PCode=:p")):
        mine = {r.ECode.strip(): dict(r._mapping) for r in db.execute(text(sql), {"p": PCODE})}
        print(f"\n{name}: legacy {len(leg)} rows, port {len(mine)}; only legacy {sorted(set(leg)-set(mine))[:10]} only port {sorted(set(mine)-set(leg))[:10]}")
        diff = collections.Counter(); ex = {}
        for e in set(leg) & set(mine):
            for c, v in leg[e].items():
                m = mine[e].get(c) if c in mine[e] else mine[e].get({"COC": "CoC"}.get(c, c))
                if isinstance(v, (Decimal, float, int)) and not isinstance(v, bool) and m is not None:
                    try:
                        if abs(float(v) - float(m)) > 0.011:
                            diff[c] += 1; ex.setdefault(c, (e, float(v), float(m)))
                    except (TypeError, ValueError):
                        pass
        for c, n in diff.most_common():
            print(f"  {c:18} {n:3} rows differ  e.g. {ex[c]} (legacy, port)")
        print("  net legacy", sum(float(r.get("NetPay" if name == "PaySalary" else "NetPayable") or 0) for r in leg.values()),
              "port", sum(float(r.get("NetPay" if name == "PaySalary" else "NetPayable") or 0) for r in mine.values()))
finally:
    db.rollback(); db.close()
