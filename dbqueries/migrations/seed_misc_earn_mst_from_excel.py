"""
Seed misc_earn_mst from the mill's MISC EARN CALCULATION.xlsx (one-off loader).

The sheet's merged-cell layout isn't machine-parseable, so the rules are
transcribed below and resolved against dept_mst (by dept_code) and
designation_mst (by exact desig name within the dept) at run time:

  PREPARING (03)  GC COOLEY / PICKING MAZDOOR  MISC EARN     Rs. 75  per 96 hrs (2 designations)
  PREPARING (03)  KC FINISHER OPERATOR - AKRA  MISC EARN     Rs. 120 per 96 hrs
  BEAMING (07)    dept-wide (CAT-7 only)       BEAM CHANGES  450 / 880 hrs * 60%
  WEAVING (30+32) LINE SIRDER                  OIL CHARGE    Rs. 8   per 8 hrs (both depts)
  WEAVING (30+32) LINE HELPER                  OIL CHARGE    Rs. 3   per 8 hrs (both depts)
  ELECTRIC (17)   dept-wide                    MISC EARN     Rs. 25  per 104 hrs

Re-runnable: a dept/designation/type that already has an active rule is skipped.

    python dbqueries/migrations/seed_misc_earn_mst_from_excel.py [tenant_db]
"""

import os
import sys

import pymysql
from dotenv import load_dotenv

# (dept_code, desig name or None for dept-wide, cata_code or None for all categories,
#  earn_type, amount, per_hrs, rate_pct, remarks)
RULES = (
    ("03", "GC- COOLEY", None, "MISC EARN", 75, 96, 100, "RS. 75/- PER 96 HRS"),
    ("03", "GC- PICKING MAZDOOR/COLLEY", None, "MISC EARN", 75, 96, 100, "RS. 75/- PER 96 HRS"),
    ("03", "KC FINISHER OPERATOR -AKRA", None, "MISC EARN", 120, 96, 100, "RS. 120/- PER 96 HRS"),
    ("07", None, "07", "BEAM CHANGES", 450, 880, 60,
     "BEAM CHANGES ALLOWANCE - CAT 7 ONLY: TOTAL VALUE/DIVISIBLE HRS = RATE * 60% PER HRS"),
    ("30", "LINE SIRDER", None, "OIL CHARGE", 8, 8, 100, "RS. 8/- PER 8 HRS (RS. 1/- PER HRS)"),
    ("32", "LINE SIRDER", None, "OIL CHARGE", 8, 8, 100, "RS. 8/- PER 8 HRS (RS. 1/- PER HRS)"),
    ("30", "LINE HELPER", None, "OIL CHARGE", 3, 8, 100, "RS. 3/- PER 8 HRS (RS. 3/8 PER HRS)"),
    ("32", "LINE HELPER", None, "OIL CHARGE", 3, 8, 100, "RS. 3/- PER 8 HRS (RS. 3/8 PER HRS)"),
    ("17", None, None, "MISC EARN", 25, 104, 100, "RS. 25/- PER 104 HRS"),
)


def main(db: str) -> None:
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", "env", "database.env"))
    conn = pymysql.connect(
        host=os.environ["DATABASE_HOST"], port=int(os.environ["DATABASE_PORT"]),
        user=os.environ["DATABASE_USER"], password=os.environ["DATABASE_PASSWORD"],
        database=db, cursorclass=pymysql.cursors.DictCursor,
    )
    cur = conn.cursor()

    cur.execute("SELECT dept_id, dept_code, branch_id FROM dept_mst WHERE dept_code IS NOT NULL")
    dept_by_code = {str(r["dept_code"]).strip(): r for r in cur.fetchall()}

    cur.execute("SELECT designation_id, dept_id, desig FROM designation_mst WHERE active = 1")
    desig_by_key = {(r["dept_id"], str(r["desig"]).strip().upper()): r["designation_id"]
                    for r in cur.fetchall()}

    # cata_code -> cata_id; on duplicate codes the row most employees reference wins.
    cur.execute("""
        SELECT cm.cata_id, cm.cata_code, COUNT(o.eb_id) AS emps
        FROM category_mst cm
        LEFT JOIN hrms_ed_official_details o
               ON o.catagory_id = cm.cata_id AND o.active = 1
        WHERE cm.cata_code IS NOT NULL
        GROUP BY cm.cata_id, cm.cata_code
        ORDER BY cm.cata_code, emps DESC, cm.cata_id
    """)
    cata_by_code: dict[str, int] = {}
    for r in cur.fetchall():
        cata_by_code.setdefault(str(r["cata_code"]).strip(), r["cata_id"])

    inserted, skipped_dup, unmatched = 0, 0, []
    for dept_code, desig, cata_code, earn_type, amount, per_hrs, rate_pct, remarks in RULES:
        dept = dept_by_code.get(dept_code)
        if dept is None:
            unmatched.append(f"dept {dept_code}")
            continue
        designation_id = None
        if desig is not None:
            designation_id = desig_by_key.get((dept["dept_id"], desig.upper()))
            if designation_id is None:
                unmatched.append(f"{dept_code}/{desig}")
                continue
        cata_id = None
        if cata_code is not None:
            cata_id = cata_by_code.get(cata_code)
            if cata_id is None:
                unmatched.append(f"{dept_code}/cat {cata_code}")
                continue
        cur.execute(
            "SELECT COUNT(*) AS cnt FROM misc_earn_mst WHERE active = 1 "
            "AND branch_id = %s AND dept_id = %s AND earn_type = %s "
            "AND ((%s IS NULL AND designation_id IS NULL) OR designation_id = %s)",
            (dept["branch_id"], dept["dept_id"], earn_type, designation_id, designation_id),
        )
        if cur.fetchone()["cnt"] > 0:
            skipped_dup += 1
            continue
        cur.execute(
            "INSERT INTO misc_earn_mst "
            "(branch_id, dept_id, designation_id, cata_id, earn_type, amount, per_hrs, rate_pct, remarks, active) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 1)",
            (dept["branch_id"], dept["dept_id"], designation_id, cata_id, earn_type,
             amount, per_hrs, rate_pct, remarks),
        )
        inserted += 1

    conn.commit()
    print(f"inserted={inserted} skipped_existing={skipped_dup} unmatched={unmatched or 'none'}")
    cur.execute("""
        SELECT m.misc_earn_id, d.dept_code, d.dept_desc, g.desig, m.earn_type,
               m.amount, m.per_hrs, m.rate_pct, m.rate_per_hr
        FROM misc_earn_mst m
        LEFT JOIN dept_mst d ON d.dept_id = m.dept_id
        LEFT JOIN designation_mst g ON g.designation_id = m.designation_id
        WHERE m.active = 1 ORDER BY d.dept_code, g.desig
    """)
    for r in cur.fetchall():
        print(r)
    conn.close()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "nbcl")
