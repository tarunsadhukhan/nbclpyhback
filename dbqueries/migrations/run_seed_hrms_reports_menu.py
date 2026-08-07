"""
Seed the HRMS Reports menu (hrms/hrmsreports) child report rows + role grants.

Requires the hub row (menu_name 'HRMS Reports', menu_path 'hrms/hrmsreports',
parent = the HRMS menu) to exist already. Children mirror the Production
Reports convention: report=1, menu_icon='assessment', order_by in 10s.
Role grants: roles 1, 3, 12 at access_type_id 4 (updated_by 1).

Usage:
    cd d:/vownextjs/vowerp3be
    python dbqueries/migrations/run_seed_hrms_reports_menu.py [--db dev3]

Idempotent: NOT EXISTS on menu_path and on (role_id, menu_id, access_type_id).
Applied to dev3 on 2026-07-14 (menu ids 953-960 under hub 952).
"""
import sys
import pymysql
from dotenv import dotenv_values
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
ENV = dotenv_values(ROOT / ".env")

DB = "dev3"
if "--db" in sys.argv:
    DB = sys.argv[sys.argv.index("--db") + 1]

HUB_PATH = "hrms/hrmsreports"
CHILDREN = [
    ("Full Attendance", "hrms/hrmsreports/fullAttendance", 10),
    ("Absenteeism", "hrms/hrmsreports/absenteeism", 20),
    ("Half Day Absenteeism", "hrms/hrmsreports/halfDay", 30),
    ("Overstay After Leave", "hrms/hrmsreports/overstay", 40),
    ("Occupation Deviation", "hrms/hrmsreports/occupationDeviation", 50),
    ("Cash Attendance", "hrms/hrmsreports/cashAttendance", 60),
    ("Payscheme Wise Salary", "hrms/hrmsreports/payschemeSalary", 70),
    ("Daily Cash Outsider Payment", "hrms/hrmsreports/cashOutsider", 80),
]
ROLES = (1, 3, 12)

con = pymysql.connect(
    host=ENV["DATABASE_HOST"],
    port=int(ENV.get("DATABASE_PORT", 3306)),
    user=ENV["DATABASE_USER"],
    password=ENV["DATABASE_PASSWORD"],
    database=DB,
    charset="utf8mb4",
)
cur = con.cursor()

cur.execute("SELECT menu_id FROM menu_mst WHERE menu_path = %s", (HUB_PATH,))
hub = cur.fetchone()
assert hub, f"hub menu {HUB_PATH} not found in {DB} — create it under the HRMS menu first"
hub_id = hub[0]
print("hub menu_id:", hub_id)

menu_ids = []
for name, path, order_by in CHILDREN:
    cur.execute("SELECT menu_id FROM menu_mst WHERE menu_path = %s", (path,))
    row = cur.fetchone()
    if row:
        print(f"exists: {name} -> {row[0]}")
        menu_ids.append(row[0])
        continue
    cur.execute(
        "INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id,"
        " menu_type_id, menu_icon, module_mst_id, order_by, report)"
        " VALUES (%s, %s, 1, %s, NULL, 'assessment', NULL, %s, 1)",
        (name, path, hub_id, order_by))
    print(f"inserted: {name} -> {cur.lastrowid}")
    menu_ids.append(cur.lastrowid)

granted = 0
for mid in [hub_id] + menu_ids:
    for role in ROLES:
        cur.execute(
            "INSERT INTO role_menu_map (role_id, menu_id, access_type_id, updated_by)"
            " SELECT %s, %s, 4, 1 FROM DUAL WHERE NOT EXISTS ("
            "   SELECT 1 FROM role_menu_map WHERE role_id = %s AND menu_id = %s"
            "   AND access_type_id = 4)",
            (role, mid, role, mid))
        granted += cur.rowcount
print("role grants added:", granted)

con.commit()

cur.execute(
    "SELECT menu_id, menu_name, menu_path, order_by, active, report FROM menu_mst"
    " WHERE menu_parent_id = %s ORDER BY order_by", (hub_id,))
print(f"\nfinal {HUB_PATH} tree in {DB}:")
for r in cur.fetchall():
    print("  ", r)
con.close()
