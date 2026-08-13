"""Apply nbcl_hrms_report_children_role_grants.sql.

HRMS Reports showed as a leaf in the portal sidebar because the roles holding
the hub menu (hrms/hrmsreports) had no role_menu_map grant on its child report
rows. This mirrors each hub grant onto every active child.

Usage:
    python dbqueries/migrations/run_nbcl_hrms_report_children_grants.py [--db nbcl]

Idempotent: NOT EXISTS on (role_id, menu_id).
"""
import pathlib
import sys

import pymysql
from dotenv import dotenv_values

ROOT = pathlib.Path(__file__).resolve().parents[2]
ENV = dotenv_values(ROOT / ".env")

DB = sys.argv[sys.argv.index("--db") + 1] if "--db" in sys.argv else "nbcl"
_RAW = (pathlib.Path(__file__).parent / "nbcl_hrms_report_children_role_grants.sql").read_text()
# Drop comment lines first — a bare split on ";" would cut inside one.
SQL = "\n".join(l for l in _RAW.splitlines() if not l.lstrip().startswith("--"))

con = pymysql.connect(
    host=ENV["DATABASE_HOST"],
    port=int(ENV.get("DATABASE_PORT", 3306)),
    user=ENV["DATABASE_USER"],
    password=ENV["DATABASE_PASSWORD"],
    database=DB,
    charset="utf8mb4",
)
cur = con.cursor()

for stmt in (s for s in SQL.split(";") if s.strip() and not s.strip().startswith("--")):
    cur.execute(stmt)
    print("grants added:", cur.rowcount)
con.commit()

cur.execute(
    "SELECT m.menu_id, m.menu_name,"
    " GROUP_CONCAT(DISTINCT CONCAT(r.role_id, ':', r.access_type_id) ORDER BY r.role_id)"
    " FROM menu_mst m LEFT JOIN role_menu_map r ON r.menu_id = m.menu_id"
    " WHERE m.menu_path = 'hrms/hrmsreports' OR m.menu_parent_id ="
    "   (SELECT menu_id FROM menu_mst WHERE menu_path = 'hrms/hrmsreports')"
    " GROUP BY m.menu_id, m.menu_name ORDER BY m.order_by")
print(f"\nHRMS Reports tree in {DB}:")
for row in cur.fetchall():
    print("  ", row)
con.close()
