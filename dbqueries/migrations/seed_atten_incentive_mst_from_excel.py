"""
Seed atten_incentive_mst from the mill's ATTEN_INCENTIVE.xlsx (one-off loader).

EMP_CAT ("CAT-1") is matched to category_mst.cata_code ("01"); where a code has
duplicate category_mst rows, the cata_id actually referenced by the most active
employees (hrms_ed_official_details.catagory_id) wins. The rate text
("RS. 1/- PER 8 HRS") is parsed into amount + per_hrs, eligibility
("96 HRS IN F/E") into eligibility_hrs. Re-runnable: a category that already
has an active rule is skipped.

    python dbqueries/migrations/seed_atten_incentive_mst_from_excel.py <xlsx> [tenant_db]
"""

import os
import re
import sys

import openpyxl
import pymysql
from dotenv import load_dotenv


def main(xlsx: str, db: str) -> None:
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", "env", "database.env"))
    conn = pymysql.connect(
        host=os.environ["DATABASE_HOST"], port=int(os.environ["DATABASE_PORT"]),
        user=os.environ["DATABASE_USER"], password=os.environ["DATABASE_PASSWORD"],
        database=db, cursorclass=pymysql.cursors.DictCursor,
    )
    cur = conn.cursor()

    # cata_code -> (cata_id, branch_id); on duplicate codes the row most
    # employees actually reference wins (ties -> lowest cata_id).
    cur.execute("""
        SELECT cm.cata_id, cm.cata_code, cm.branch_id, COUNT(o.eb_id) AS emps
        FROM category_mst cm
        LEFT JOIN hrms_ed_official_details o
               ON o.catagory_id = cm.cata_id AND o.active = 1
        WHERE cm.cata_code IS NOT NULL
        GROUP BY cm.cata_id, cm.cata_code, cm.branch_id
        ORDER BY cm.cata_code, emps DESC, cm.cata_id
    """)
    cat_by_code: dict[str, dict] = {}
    for r in cur.fetchall():
        cat_by_code.setdefault(str(r["cata_code"]).strip(), r)

    cur.execute("SELECT cata_id FROM atten_incentive_mst WHERE active = 1")
    existing = {r["cata_id"] for r in cur.fetchall()}

    ws = openpyxl.load_workbook(xlsx, data_only=True)["Sheet1"]
    inserted, skipped_dup, unmatched = 0, 0, []
    for row in ws.iter_rows(min_row=3, values_only=True):
        # columns: A(unused), B=EMP_CAT, C=rate text, D=eligibility, E=working includes, F=calc on
        _, emp_cat, rate_text, elig_text, includes, calc_on = (list(row) + [None] * 6)[:6]
        m = re.match(r"CAT-(\d+)", str(emp_cat or "").strip())
        if not m:
            continue
        code = m.group(1).zfill(2)
        cat = cat_by_code.get(code)
        if cat is None:
            unmatched.append(emp_cat)
            continue
        if cat["cata_id"] in existing:
            skipped_dup += 1
            continue
        nums = re.findall(r"\d+(?:\.\d+)?", str(rate_text or ""))
        if len(nums) < 2:
            unmatched.append(f"{emp_cat} (unparseable rate: {rate_text!r})")
            continue
        amount, per_hrs = float(nums[0]), float(nums[1])
        elig = re.findall(r"\d+(?:\.\d+)?", str(elig_text or ""))
        cur.execute(
            "INSERT INTO atten_incentive_mst "
            "(branch_id, cata_id, amount, per_hrs, eligibility_hrs, working_includes, calc_on, remarks, active) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 1)",
            (cat["branch_id"], cat["cata_id"], amount, per_hrs,
             float(elig[0]) if elig else 96.0,
             str(includes or "").strip() or None,
             str(calc_on or "").strip() or None,
             str(rate_text or "").strip() or None),
        )
        existing.add(cat["cata_id"])
        inserted += 1

    conn.commit()
    print(f"inserted={inserted} skipped_existing={skipped_dup} unmatched={unmatched or 'none'}")
    cur.execute("""
        SELECT m.atten_incentive_id, cm.cata_code, cm.cata_desc, m.amount, m.per_hrs,
               m.rate_per_hr, m.eligibility_hrs
        FROM atten_incentive_mst m
        LEFT JOIN category_mst cm ON cm.cata_id = m.cata_id
        WHERE m.active = 1 ORDER BY cm.cata_code
    """)
    for r in cur.fetchall():
        print(r)
    conn.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "nbcl")
