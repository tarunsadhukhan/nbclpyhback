"""One-off: load data/MC LIST.xlsx into <db>.machine_mst.

Usage: python dbqueries/migrations/import_machine_mst_from_mc_list.py <xlsx> <db> [--commit]
Without --commit it only prints what it would insert.

Excel columns: CODE, DES, DEPT (dept_code as int), UNIT (branch, ignored — dept carries it),
MTYPE (blank in the source file → inferred from the CODE prefix, see TYPE_BY_PREFIX), Active (Y/N).
"""
import os, re, sys, collections
import openpyxl, pymysql
from dotenv import load_dotenv

# ponytail: MTYPE is empty in the sheet, so machine_type_id (NOT NULL FK) is guessed from the
# code prefix → machine_type_mst.machine_type_id. Fix any wrong guess with one UPDATE per prefix.
TYPE_BY_PREFIX = {
    "SPDR": 8,   # Spreader
    "TSR": 12,   # Teaser
    "HW": 12,    # Hard-waste teaser (batching) — guess
    "HKLR": 9,   # Coarse Side Machine (batching) — guess
    "1DG": 14, "2DG": 14, "3DG": 14,  # Drawing
    "BRKC": 51,  # Breaker card
    "INTC": 13,  # Inter card → Carding Machine
    "FINC": 52,  # Finisher card
    "SPC": 36, "SPF": 36,  # Spinning frames
    "CPW": 47,   # Cop Winding
    "WPW": 48,   # Warp/Spool Winding
    "DM": 5, "SM": 5,  # Beaming (dressing / sizing)
    "10H": 27,   # Hand sewing → Sack Sewing — guess
    "HK": 26,    # Herackle
    "HM": 25,    # Hemming
    "PM": 31,    # Press machine (finishing) → Bale Press — guess
    "S": 6,      # Sacking Loom
    "H": 16,     # Hessian Conventional Loom
}


def machine_type(code: str) -> int:
    prefix = re.sub(r"\d+[A-Z]?$", "", code)  # SPF012 → SPF, WPW05A → WPW, 1DG03A → 1DG
    if prefix not in TYPE_BY_PREFIX:
        raise SystemExit(f"no machine type mapping for {code!r} (prefix {prefix!r})")
    return TYPE_BY_PREFIX[prefix]


def main(xlsx: str, db: str, commit: bool) -> None:
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", "env", "database.env"))
    conn = pymysql.connect(host=os.environ["DATABASE_HOST"], port=int(os.environ["DATABASE_PORT"]),
                           user=os.environ["DATABASE_USER"], password=os.environ["DATABASE_PASSWORD"],
                           database=db)
    cur = conn.cursor()
    cur.execute("SELECT dept_code, dept_id FROM dept_mst")
    dept_by_code = {code: did for code, did in cur.fetchall()}
    cur.execute("SELECT MIN(user_id) FROM user_mst")
    updated_by = cur.fetchone()[0]

    ws = openpyxl.load_workbook(xlsx, data_only=True).active
    rows = []
    for code, des, dept, _unit, _mtype, active in ws.iter_rows(min_row=2, values_only=True):
        if not code:
            continue
        code = str(code).strip()
        dept_code = str(dept).zfill(2)
        if dept_code not in dept_by_code:
            raise SystemExit(f"unknown dept_code {dept_code!r} for {code!r}")
        rows.append((dept_by_code[dept_code], str(des or code).strip(), machine_type(code),
                     updated_by, 1 if str(active).upper() == "Y" else 0, code))

    assert len(rows) == len({(r[0], r[5]) for r in rows}), "duplicate (dept, code) in sheet"
    print(f"{len(rows)} rows, updated_by={updated_by}")
    print("by machine_type_id:", dict(collections.Counter(r[2] for r in rows)))
    if not commit:
        print("dry run — pass --commit to insert")
        return
    cur.executemany(
        "INSERT INTO machine_mst (dept_id, machine_name, machine_type_id, updated_by, active, mech_code) "
        "VALUES (%s, %s, %s, %s, %s, %s)", rows)
    conn.commit()
    cur.execute("SELECT COUNT(*) FROM machine_mst")
    print("machine_mst count now:", cur.fetchone()[0])
    conn.close()


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], "--commit" in sys.argv)
