"""
Parity check of the Winsome wages port: run winsome_wages_process.sql for a period that legacy already
processed, compare every PayWages row with the legacy Winsome PayWages, then ROLL BACK (nothing is kept).

    python scripts/check_winsome_wages_parity.py P20260802 [P20260801 ...]

Env: tenant DB from env/database.env (run from pyhback/), MSSQL_CONN = ODBC string of the Winsome legacy DB.
Exit code 1 when any row or column differs by more than 0.01.
"""

import os
import sys
import time

from dotenv import load_dotenv

load_dotenv("env/database.env")
import pyodbc  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from src.hrms.winsomeWagesProcess import run_winsome_wages  # noqa: E402

COLS = ("DeptCode", "OccpCode", "Work_HR", "OT_HR", "NS_HR", "LayOff_HR", "Holiday_HR", "PL_HR", "CL_HR", "Work_Day",
        "FBasic_Amt", "FBasicInc_Amt", "PBasic_Amt", "DA_Amt", "NS_Amt", "Holiday_Amt", "PL_Amt", "CL_Amt",
        "LayOffHR_Amt", "OT_Amt", "Incentive_Amt", "PFEarnAdj", "NPFEarnAdj", "PF_Gross", "ESI_Gross",
        "Wages_Gross", "PFEmployee", "ESI_Amt", "ESIC", "LWF_Amt", "HRDeduction", "PFLoanCap", "Advance",
        "TotalDeduction", "NetPay", "ROff", "NetPayable", "Pension", "COC", "YTD_PFEmployee", "YTD_Pension",
        "YTD_Employer", "YTD_Days", "YTD_LoanAmt", "FBasic_Rate", "DA_Rate", "SrlNo", "SlNo")


def norm(v):
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return (v or "").strip() if isinstance(v, str) else v


def main() -> int:
    e = os.environ
    engine = create_engine(f"mysql+pymysql://{e['DATABASE_USER']}:{e['DATABASE_PASSWORD']}@{e['DATABASE_HOST']}:"
                           f"{e['DATABASE_PORT']}/winsome")
    ms = pyodbc.connect(e["MSSQL_CONN"]).cursor()
    sel = ", ".join(COLS)
    bad = 0
    for pcode in sys.argv[1:]:
        legacy = {(r.ECode.strip(), r.PaySlipType.strip()): r for r in ms.execute(
            f"SELECT ECode, PaySlipType, {sel} FROM PayWages WHERE PCode = ? AND CompCode = 'WIL'", pcode)}
        db = Session(engine)
        try:
            t0 = time.time()
            summary = run_winsome_wages(db, 110, pcode, 0, check_bank_file=False)
            took = time.time() - t0
            ours = {(r.ECode, r.PaySlipType): r for r in db.execute(text(
                f"SELECT ECode, PaySlipType, {sel} FROM PayWages WHERE PCode = :p AND CompCode = 'WIL'"), {"p": pcode})}
        finally:
            db.rollback()
            db.close()
        print(f"{pcode}: {took:.0f}s  ours {len(ours)} rows  legacy {len(legacy)} rows  net {summary['net_payable']:,.0f}"
              f"  legacy net {sum(float(r.NetPayable) for r in legacy.values()):,.0f}")
        only_l, only_o = legacy.keys() - ours.keys(), ours.keys() - legacy.keys()
        if only_l or only_o:
            bad += 1
            print(f"  only legacy: {sorted(only_l)[:15]}\n  only ours:   {sorted(only_o)[:15]}")
        diffs: dict[str, list] = {}
        for key in legacy.keys() & ours.keys():
            for c in COLS:
                a, b = norm(getattr(legacy[key], c)), norm(getattr(ours[key], c))
                if a != b and not (isinstance(a, float) and isinstance(b, float) and abs(a - b) <= 0.01):
                    diffs.setdefault(c, []).append((key, a, b))
        for c, lst in diffs.items():
            bad += 1
            print(f"  {c}: {len(lst)} rows differ, e.g. {lst[:3]}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
