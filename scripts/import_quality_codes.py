"""
One-off import of the NBCL "Quality Code and Rate list" sheet into
tbl_nbcl_wages_quality_mst (production/qualitymaster).

Usage:
    python scripts/import_quality_codes.py [path/to/QUILITY_CODE.xlsx] [--db nbcl]

Sheet layout (row 4 onwards): Dept Code | Qty Code | Qty Description | Rate | Conversion Factor
- Dept Code ("007") is matched to dept_mst.dept_code by integer value ("7").
  Unmatched dept codes are inserted with dept_id = NULL and reported.
- Rows without a Qty Code (title, "Total ..." footer, trailing notes) are skipped.
- Non-numeric Rate / Conversion Factor cells become NULL and are reported.
- Idempotent: an existing (dept_id, quality_code) pair is skipped.
"""

import os
import sys
from decimal import Decimal, InvalidOperation

import openpyxl
import pymysql
from dotenv import load_dotenv

load_dotenv("env/database.env")

DEFAULT_XLSX = r"e:\test\nbcl\data\QUILITY_CODE.xlsx"
DECIMAL_MAX = Decimal("999.9999999")  # decimal(10,7)


def to_decimal(raw):
    """Return (Decimal|None, error|None) for a numeric sheet cell."""
    if raw is None or str(raw).strip() == "":
        return None, None
    try:
        value = Decimal(str(raw).strip())
    except InvalidOperation:
        return None, f"non-numeric {raw!r}"
    if value < 0 or value > DECIMAL_MAX:
        return None, f"out of range {raw!r}"
    return value, None


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    xlsx = args[0] if args else DEFAULT_XLSX
    db = sys.argv[sys.argv.index("--db") + 1] if "--db" in sys.argv else "nbcl"

    conn = pymysql.connect(
        host=os.getenv("DATABASE_HOST"), port=int(os.getenv("DATABASE_PORT")),
        user=os.getenv("DATABASE_USER"), password=os.getenv("DATABASE_PASSWORD"),
        database=db, cursorclass=pymysql.cursors.DictCursor,
    )
    cur = conn.cursor()

    cur.execute("SELECT dept_id, dept_code FROM dept_mst")
    dept_by_int = {}
    for r in cur.fetchall():
        try:
            dept_by_int.setdefault(int(r["dept_code"]), r["dept_id"])
        except (TypeError, ValueError):
            pass

    cur.execute("SELECT dept_id, quality_code FROM tbl_nbcl_wages_quality_mst")
    existing = {(r["dept_id"], r["quality_code"]) for r in cur.fetchall()}

    ws = openpyxl.load_workbook(xlsx, data_only=True).worksheets[0]
    to_insert, skipped, warnings = [], [], []
    for row_no, row in enumerate(ws.iter_rows(min_row=4, values_only=True), start=4):
        dept_raw, code_raw, desc_raw, rate_raw, conv_raw = (list(row) + [None] * 5)[:5]
        code = str(code_raw).strip() if code_raw not in (None, "") else ""
        if not code:
            if any(v not in (None, "") for v in row):
                skipped.append((row_no, "no quality code", row))
            continue

        dept_id = None
        try:
            dept_id = dept_by_int.get(int(str(dept_raw).strip()))
        except (TypeError, ValueError):
            pass
        if dept_id is None:
            warnings.append((row_no, f"dept code {dept_raw!r} not in dept_mst -> dept_id NULL"))

        rate, err = to_decimal(rate_raw)
        if err:
            warnings.append((row_no, f"rate {err} -> NULL"))
        conv, err = to_decimal(conv_raw)
        if err:
            warnings.append((row_no, f"conv_factor {err} -> NULL"))

        if (dept_id, code) in existing:
            skipped.append((row_no, "already exists", (dept_raw, code)))
            continue
        existing.add((dept_id, code))
        desc = str(desc_raw).strip()[:100] if desc_raw not in (None, "") else None
        to_insert.append((dept_id, code[:10], desc, rate, conv))

    if to_insert:
        cur.executemany(
            "INSERT INTO tbl_nbcl_wages_quality_mst (dept_id, quality_code, quality_desc, quality_rate, conv_factor, active) "
            "VALUES (%s, %s, %s, %s, %s, 1)",
            to_insert,
        )
        conn.commit()

    cur.execute("SELECT COUNT(*) AS n FROM tbl_nbcl_wages_quality_mst")
    print(f"DB={db}  inserted={len(to_insert)}  skipped={len(skipped)}  warnings={len(warnings)}  table_total={cur.fetchone()['n']}")
    for row_no, why, data in skipped:
        print(f"  skip row {row_no}: {why}: {data}")
    for row_no, msg in warnings:
        print(f"  warn row {row_no}: {msg}")


if __name__ == "__main__":
    main()
