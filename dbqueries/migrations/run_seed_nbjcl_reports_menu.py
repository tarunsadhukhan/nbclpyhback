"""
Seed the legacy "Smart Eye Reports" tree as portal menus: HRMS -> NBJCL Reports
-> <group> -> <report>, plus full-access (access_type_id 4) grants for one role.

Shape mirrors the existing HRMS Reports hub (hrms/hrmsreports): the hub is a
routed node, groups are path-less nodes (the sidebar just expands them), leaves
are report=1 / icon 'assessment' with path hrms/nbjclreports/<group>/<report>.
The legacy "RR Wages" group is deliberately left out.

menu_mst.menu_name is UNIQUE, so a name already used by another menu gets a
" (NBJCL)" suffix (e.g. 'Attendance Register', 'Department Wise Summary').

Usage (dry run prints the plan and writes nothing):
    python dbqueries/migrations/run_seed_nbjcl_reports_menu.py --db nbjcl --role slssuperadmin
    python dbqueries/migrations/run_seed_nbjcl_reports_menu.py --db nbjcl --role slssuperadmin --apply

Idempotent: rows are matched on menu_path (groups: on parent + name).
Rollback:
    DELETE r FROM role_menu_map r JOIN menu_mst m ON m.menu_id = r.menu_id
     WHERE m.menu_path LIKE 'hrms/nbjclreports%' OR m.menu_parent_id =
           (SELECT menu_id FROM (SELECT menu_id FROM menu_mst WHERE menu_path = 'hrms/nbjclreports') h);
    DELETE FROM menu_mst WHERE menu_path LIKE 'hrms/nbjclreports/%';
    DELETE FROM menu_mst WHERE menu_parent_id =
           (SELECT menu_id FROM (SELECT menu_id FROM menu_mst WHERE menu_path = 'hrms/nbjclreports') h);
    DELETE FROM menu_mst WHERE menu_path = 'hrms/nbjclreports';
"""
import argparse
import pathlib
import re

import pymysql
from dotenv import dotenv_values

HUB_NAME, HUB_PATH, HRMS_PATH = "NBJCL Reports", "hrms/nbjclreports", "hrms"
SUFFIX = " (NBJCL)"

# Names are kept exactly as the legacy tree spells them (typos included).
TREE = [
    ("Attendance Register", [
        "Attendance Work Type Wise Details",
        "Attendance Fort Night Wise",
        "Attendance Fort Night Wise MERGE",
        "Attendance Fort Night Wise Shift Wise",
        "Workmen`s Muster Roll-Register Of Adult Workers",
        "Attendance Register (MANUAL)",
        "Gate Pass Register",
        "Department Wise Summary",
        "Occupation Wise Summary",
        "ABSENTING LIST",
        "LEAVE REGISTER",
        "DATE WISE DEPT WISE WORKING HOURS",
        "DATE WISE DEPT WISE WORKING HANDS",
        "Fort Night Wise Worker Wise Hands",
        "Attendance Time Report",
        "Dept. Wise. Ocp. Wise Hands Summary",
    ]),
    ("Registeration", [
        "Registered Employee Details",
        "Pending For Registeration Summary",
        "Pending For Registeration Details",
        "Registered Employee User Wise Date Wise",
    ]),
    ("Wages", [
        "Worker Daily PaySheet",
        "WORKERS DEPT-WISE LIST [ OT ]",
        "LWF STATEMENT",
        "PENSION BALANCE STATEMENT",
        "WORKERS PF CONT / ADV BALANCE STATEMENT",
        "RECORD ON STATEMENT",
        "WAGES REGISTER",
        "WAGES DEPARTMENT WISE SUMMARY",
        "STL Checklist",
        "STL Payment Checklist",
        "WAGES PAY SLIP",
        "BONUS PAY SLIP",
    ]),
    ("Loan & Advances", [
        "PF Loan Register Summay",
        "PF Loan Register Fortnight Wise",
        "PF Loan Register Worker Wise",
        "PF NR Loan Register Summary",
        "PF NR Loan Register Worker Wise",
        "Advance Register Summary",
        "Advance Register Fortnight Wise",
        "Advance Register Worker Wise",
        "Special Advance Register Summary",
        "Special Advance Register Worker Wise",
        "DETAILS OF SPECIAL ADVANCE",
        "DETAILS OF WAGES ADVANCE",
    ]),
    ("HTML Reports", [
        "Worker List with Photo",
    ]),
    ("Salary", [
        "MONTHLY-PAID STAFF PAYSLIP",
        "MONTHLY-PAID STAFF SALARY SLIP",
        "LEAVE BALANCE STATEMENT",
        "DEPT SUMMARY-CLERK -STAFF",
        "GRAND SUMMARY-CLERK -STAFF",
        "INCOME TAX STATEMENT",
        "LIC RECOVERY STATEMENT",
        "LWF REPORT [ FORM-D]",
        "PFC / ADV STATEMENT",
        "PF CONT. / LOAN BALANCE STATEMENT",
        "P-TAX STATEMENT",
        "BONUS PAY SLIP - STAFF",
    ]),
    ("Outsider", [
        "Daily Provisional Wages Sheet",
        "Outsider Payment Summary",
        "Outsider Payment Summary [ DeptCode Wise ]",
        "Outsider Payment Details",
        "Outsider Payment Summary [ Dept. Wise]",
    ]),
    ("NEW", [
        "Non-Working Worker List",
        "Advance Statement [ Worker ]",
        "Advance Statement [ STAFF ]",
        "PF Loan Register Summay - 2",
        "Loan & PF Statement",
    ]),
    ("Wages-Monthly Reports", [
        "ECR Statement",
        "ESI Statement",
        "PTax Statement",
    ]),
    ("Provident Fund Reports", [
        "PF Transaction Details",
        "PF Emp. Wise Month Wise Transaction [ PF Card ]",
        "Employee Provident Fund Statement [ PF Slip ]",
    ]),
]


def camel(name: str) -> str:
    """'WORKERS DEPT-WISE LIST [ OT ]' -> 'workersDeptWiseListOt'."""
    words = re.findall(r"[A-Za-z0-9]+", name.replace("&", " and "))
    return words[0].lower() + "".join(w.capitalize() for w in words[1:])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--role", required=True, help="roles_mst.role_name to grant full access")
    ap.add_argument("--apply", action="store_true", help="commit (default: dry run)")
    args = ap.parse_args()

    paths = [f"{HUB_PATH}/{camel(g)}/{camel(n)}" for g, leaves in TREE for n in leaves]
    assert len(paths) == len(set(paths)), "duplicate generated menu_path"

    env = dotenv_values(pathlib.Path(__file__).resolve().parents[2] / "env" / "database.env")
    con = pymysql.connect(
        host=env["DATABASE_HOST"], port=int(env.get("DATABASE_PORT", 3306)),
        user=env["DATABASE_USER"], password=env["DATABASE_PASSWORD"],
        database=args.db, charset="utf8mb4",
    )
    cur = con.cursor()

    cur.execute("SELECT role_id FROM roles_mst WHERE role_name = %s", (args.role,))
    row = cur.fetchone()
    assert row, f"role {args.role!r} not found in {args.db}.roles_mst"
    role_id = row[0]
    cur.execute("SELECT menu_id FROM menu_mst WHERE menu_path = %s", (HRMS_PATH,))
    row = cur.fetchone()
    assert row, f"HRMS root menu ({HRMS_PATH}) not found in {args.db}"
    hrms_id = row[0]

    stats = {"menus": 0, "grants": 0}

    def ensure(name, path, parent_id, type_id, icon, module_id, order_by, report):
        """Return the menu_id for this node, inserting it if absent."""
        if path:
            cur.execute("SELECT menu_id FROM menu_mst WHERE menu_path = %s", (path,))
        else:
            cur.execute(
                "SELECT menu_id FROM menu_mst WHERE menu_parent_id = %s AND menu_name IN (%s, %s)",
                (parent_id, name, name + SUFFIX))
        found = cur.fetchone()
        if found:
            return found[0]
        cur.execute("SELECT 1 FROM menu_mst WHERE menu_name = %s", (name,))
        if cur.fetchone():
            name += SUFFIX
        cur.execute(
            "INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id,"
            " menu_type_id, menu_icon, module_mst_id, order_by, report)"
            " VALUES (%s, %s, 1, %s, %s, %s, %s, %s, %s)",
            (name, path, parent_id, type_id, icon, module_id, order_by, report))
        stats["menus"] += 1
        print(f"  + [{cur.lastrowid}] {name}  ({path or 'group'})")
        return cur.lastrowid

    def grant(menu_id):
        cur.execute(
            "INSERT INTO role_menu_map (role_id, menu_id, access_type_id, updated_by)"
            " SELECT %s, %s, 4, 1 FROM DUAL WHERE NOT EXISTS ("
            "   SELECT 1 FROM role_menu_map WHERE role_id = %s AND menu_id = %s"
            "   AND access_type_id = 4)",
            (role_id, menu_id, role_id, menu_id))
        stats["grants"] += cur.rowcount

    # Hub copies the HRMS Reports hub row's shape (type 2 'custom', module 1).
    hub_id = ensure(HUB_NAME, HUB_PATH, hrms_id, 2, None, 1, 3, None)
    grant(hub_id)
    for gi, (group, leaves) in enumerate(TREE, start=1):
        gid = ensure(group, None, hub_id, None, None, None, gi * 10, None)
        grant(gid)
        for li, leaf in enumerate(leaves, start=1):
            mid = ensure(leaf, f"{HUB_PATH}/{camel(group)}/{camel(leaf)}",
                         gid, None, "assessment", None, li * 10, 1)
            grant(mid)

    print(f"\n{args.db}: {stats['menus']} menus, {stats['grants']} grants for"
          f" role {args.role} ({role_id})")
    if args.apply:
        con.commit()
        print("COMMITTED")
    else:
        con.rollback()
        print("DRY RUN - rolled back, nothing written (pass --apply to commit)")
    con.close()


if __name__ == "__main__":
    main()
