"""
Idempotent migration for the dynamic menu / role-based permission system.

Creates 5 tables + 1 view in the main `sjm` database and seeds them on the
first run.  Safe to call on every startup -- table creation uses
IF NOT EXISTS and seed inserts are gated by COUNT(*) checks.

The Admin role is auto-assigned to ``user_mst.user_id = 1`` if that row
exists and isn't already mapped.
"""

from src.mobileapp.db import get_db


_CREATE_TABLES_SQL = [
    """
    CREATE TABLE IF NOT EXISTS roles (
        id           INT AUTO_INCREMENT PRIMARY KEY,
        role_name    VARCHAR(50)  NOT NULL UNIQUE,
        description  VARCHAR(255) NULL,
        is_active    TINYINT(1)   NOT NULL DEFAULT 1,
        created_at   TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS menu_mst (
        id              INT AUTO_INCREMENT PRIMARY KEY,
        menu_key        VARCHAR(80)  NOT NULL UNIQUE,
        menu_name       VARCHAR(100) NOT NULL,
        parent_id       INT          NULL,
        menu_order      INT          NOT NULL DEFAULT 0,
        icon            VARCHAR(80)  NULL,
        activity_class  VARCHAR(120) NULL,
        is_group        TINYINT(1)   NOT NULL DEFAULT 0,
        is_active       TINYINT(1)   NOT NULL DEFAULT 1,
        KEY idx_menus_parent (parent_id),
        FOREIGN KEY (parent_id) REFERENCES menu_mst(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS role_menu_map (
        id          INT AUTO_INCREMENT PRIMARY KEY,
        role_id     INT NOT NULL,
        menu_id     INT NOT NULL,
        can_view    TINYINT(1) NOT NULL DEFAULT 0,
        can_add     TINYINT(1) NOT NULL DEFAULT 0,
        can_modify  TINYINT(1) NOT NULL DEFAULT 0,
        can_delete  TINYINT(1) NOT NULL DEFAULT 0,
        can_print   TINYINT(1) NOT NULL DEFAULT 0,
        can_all     TINYINT(1) NOT NULL DEFAULT 0,
        UNIQUE KEY uq_role_menu (role_id, menu_id),
        FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE,
        FOREIGN KEY (menu_id) REFERENCES menu_mst(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS user_menu_permissions (
        id          INT AUTO_INCREMENT PRIMARY KEY,
        user_id     INT NOT NULL,
        menu_id     INT NOT NULL,
        can_view    TINYINT(1) NOT NULL DEFAULT 0,
        can_add     TINYINT(1) NOT NULL DEFAULT 0,
        can_modify  TINYINT(1) NOT NULL DEFAULT 0,
        can_delete  TINYINT(1) NOT NULL DEFAULT 0,
        can_print   TINYINT(1) NOT NULL DEFAULT 0,
        can_all     TINYINT(1) NOT NULL DEFAULT 0,
        UNIQUE KEY uq_user_menu (user_id, menu_id),
        FOREIGN KEY (menu_id) REFERENCES menu_mst(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS user_role_map (
        id        INT AUTO_INCREMENT PRIMARY KEY,
        user_id   INT NOT NULL,
        role_id   INT NOT NULL,
        UNIQUE KEY uq_user_role (user_id, role_id),
        FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
]

_CREATE_VIEW_SQL = """
CREATE OR REPLACE VIEW v_user_effective_permissions AS
SELECT
    ur.user_id                                       AS user_id,
    m.id                                             AS menu_id,
    m.menu_key                                       AS menu_key,
    MAX(COALESCE(ump.can_view  , rmp.can_view , 0))  AS can_view,
    MAX(COALESCE(ump.can_add   , rmp.can_add  , 0))  AS can_add,
    MAX(COALESCE(ump.can_modify, rmp.can_modify, 0)) AS can_modify,
    MAX(COALESCE(ump.can_delete, rmp.can_delete, 0)) AS can_delete,
    MAX(COALESCE(ump.can_print , rmp.can_print , 0)) AS can_print,
    MAX(COALESCE(ump.can_all   , rmp.can_all   , 0)) AS can_all
FROM user_role_map ur
CROSS JOIN menu_mst m
LEFT JOIN role_menu_map rmp
        ON rmp.role_id = ur.role_id AND rmp.menu_id = m.id
LEFT JOIN user_menu_permissions ump
        ON ump.user_id = ur.user_id AND ump.menu_id = m.id
GROUP BY ur.user_id, m.id, m.menu_key
"""


_ROLES = [
    ("Admin",      "Full access to all modules"),
    ("Manager",    "View / Add / Edit, no delete, can print reports"),
    ("Supervisor", "View and Add production / attendance entries"),
    ("Operator",   "Limited entry - attendance & basic production"),
    ("Viewer",     "Read-only across the system"),
]


# (menu_key, menu_name, order, icon, activity_class) -- top-level cards.
_TOP_CARDS = [
    ("card_present", "Present (Dept-wise)", 1, "ic_check",    None),
    ("card_jute",    "Jute (Quick)",        2, "ic_employee", "JuteReceivedActivity"),
    ("card_spg",     "SPG (Quick)",         3, "ic_employee", "SpinningDoffActivity"),
    ("card_winding", "Winding (Quick)",     4, "ic_employee", "WindingEntryActivity"),
    ("card_others",  "Others (Quick)",      5, "ic_employee", "OtherEntriesActivity"),
    ("card_bales",   "Bales (Quick)",       6, "ic_employee", "BalesProductionEntryActivity"),
]


# Tree of groups -> children. Leaves are (key, name, order, icon, activity, is_group).
# Mirrors the IDs used in MyHrms app/src/main/res/layout/activity_dashboard.xml.
_MENU_TREE = [
    {
        "group": ("grp_attendance", "Attendance", 10, "ic_attendance"),
        "children": [
            ("menu_attendance_dashboard", "Attendance Dashboard", 1, "ic_report",        "AttendanceDashboardActivity", 0),
            ("menu_onboarding",           "Face Registration",    2, "ic_face_register", "OnBoardingActivity",          0),
            ("menu_attendance_entry",     "Attendance Entry",     3, "ic_face",          "AttendanceActivity",          0),
            ("menu_attendance_reports",   "Attendance Reports",   4, "ic_report",        "AttendanceReportsActivity",   0),
            {
                "group": ("grp_other_entries", "Other Entries", 5, "ic_masters"),
                "children": [
                    ("menu_leave_entries", "Leave Entries", 1, "ic_edit", "LeaveEntryActivity", 0),
                ],
            },
        ],
    },
    {
        "group": ("grp_production", "Production", 20, "ic_masters"),
        "children": [
            {
                "group": ("grp_jute", "Jute", 1, "ic_masters"),
                "children": [
                    ("menu_jute_received",   "Jute Received",   1, "ic_add", "JuteReceivedActivity",   0),
                    ("menu_assorting_entry", "Assorting Entry", 2, "ic_add", "AssortingEntryActivity", 0),
                ],
            },
            {
                "group": ("grp_spreader_entry", "Spreader Entry", 2, "ic_masters"),
                "children": [
                    ("menu_production_entry", "Spreader Production", 1, "ic_add", "SpreaderProdEntryActivity",  0),
                    ("menu_issue_entry",      "Spreader Issue",      2, "ic_add", "SpreaderIssueEntryActivity", 0),
                ],
            },
            ("menu_drawing_meter_entry", "Drawing Meter Entry", 3, "ic_add", "DrawingMeterEntryActivity", 0),
            ("menu_spinning_doff_entry", "Spinning Doff",       4, "ic_add", "SpinningDoffActivity",      0),
            {
                "group": ("grp_doff_entry", "Doff Entry", 5, "ic_masters"),
                "children": [
                    ("menu_spellwise_frame_entry", "Spell-wise Frame Entry", 1, "ic_add", "SpellWiseFrameEntryActivity", 0),
                    ("menu_spg_doff_entry",        "Spg Doff Entry",         2, "ic_add", "NewDoffEntryActivity",        0),
                    ("menu_spg_doff_entry1",       "Spg Doff Entry 1",       3, "ic_add", "SpgDoffEntry1Activity",       0),
                    ("menu_spg_running_hours",     "SPG Running Hours",      4, "ic_add", "SpgRunningHoursActivity",     0),
                ],
            },
            {
                "group": ("grp_winding_entry", "Winding Entry", 6, "ic_masters"),
                "children": [
                    ("menu_winding_entry",      "Winding Entry",            1, "ic_add", "WindingEntryActivity",     0),
                    ("menu_cont_winding_entry", "Continuous Winding Entry", 2, "ic_add", "ContWindingEntryActivity", 0),
                ],
            },
            ("menu_weaving_entry", "Weaving Entry", 7, "ic_add", "MenuPlaceholderActivity", 0),
            {
                "group": ("grp_finishing_entry", "Finishing", 8, "ic_masters"),
                "children": [
                    ("menu_other_entries",          "Other Entries",          1, "ic_add", "OtherEntriesActivity",         0),
                    ("menu_bales_production_entry", "Bales Production Entry", 2, "ic_add", "BalesProductionEntryActivity", 0),
                    ("menu_bales_issue_entry",      "Bales Issue Entry",      3, "ic_add", "BalesIssueEntryActivity",      0),
                ],
            },
            {
                "group": ("grp_stocks", "Stocks", 9, "ic_masters"),
                "children": [
                    ("menu_roll_stock", "Roll Stock", 1, "ic_report", "RollStockActivity", 0),
                ],
            },
            ("menu_weight_entry", "Weight Entry", 10, "ic_add", "WeightEntryActivity", 0),
        ],
    },
]


_SUPERVISOR_KEYS = (
    "card_present", "card_jute", "card_spg", "card_winding", "card_others", "card_bales",
    "grp_attendance", "menu_attendance_dashboard", "menu_onboarding",
    "menu_attendance_entry", "menu_attendance_reports",
    "grp_other_entries", "menu_leave_entries",
    "grp_production", "grp_jute", "menu_jute_received", "menu_assorting_entry",
    "grp_spreader_entry", "menu_production_entry", "menu_issue_entry",
    "menu_drawing_meter_entry", "menu_spinning_doff_entry",
    "grp_doff_entry", "menu_spellwise_frame_entry", "menu_spg_doff_entry",
    "menu_spg_doff_entry1", "menu_spg_running_hours",
    "grp_winding_entry", "menu_winding_entry", "menu_cont_winding_entry", "menu_weaving_entry",
    "grp_finishing_entry", "menu_other_entries", "menu_bales_production_entry",
    "menu_bales_issue_entry", "grp_stocks", "menu_roll_stock", "menu_weight_entry",
)

_OPERATOR_KEYS = (
    "card_present",
    "grp_attendance", "menu_attendance_entry", "menu_onboarding",
    "grp_production", "grp_jute", "menu_jute_received", "menu_assorting_entry",
    "menu_drawing_meter_entry", "menu_spinning_doff_entry",
    "grp_winding_entry", "menu_winding_entry", "menu_cont_winding_entry", "menu_weight_entry",
)


def _insert_menu(cursor, key, name, parent_id, order, icon, activity_class, is_group):
    cursor.execute(
        """
        INSERT INTO menu_mst
            (menu_key, menu_name, parent_id, menu_order, icon, activity_class, is_group)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (key, name, parent_id, order, icon, activity_class, is_group),
    )
    return cursor.lastrowid


def _seed_menu_tree(cursor, nodes, parent_id):
    for node in nodes:
        if isinstance(node, dict):
            gkey, gname, gorder, gicon = node["group"]
            gid = _insert_menu(cursor, gkey, gname, parent_id, gorder, gicon, None, 1)
            _seed_menu_tree(cursor, node["children"], gid)
        else:
            key, name, order, icon, activity, is_group = node
            _insert_menu(cursor, key, name, parent_id, order, icon, activity, is_group)


def init_permissions_db():
    """Create permission tables / view if missing, seed defaults, and grant
    Admin to user_mst.user_id = 1.  Safe to call on every startup."""
    try:
        db = get_db()
        cursor = db.cursor()

        for ddl in _CREATE_TABLES_SQL:
            cursor.execute(ddl)
        cursor.execute(_CREATE_VIEW_SQL)
        db.commit()

        # ---- Seed roles --------------------------------------------------
        cursor.execute("SELECT COUNT(*) FROM roles")
        (roles_count,) = cursor.fetchone()
        if roles_count == 0:
            cursor.executemany(
                "INSERT INTO roles (role_name, description) VALUES (%s, %s)",
                _ROLES,
            )
            db.commit()
            print(f"   [OK] Seeded {len(_ROLES)} roles")

        # ---- Seed menus + role defaults ---------------------------------
        cursor.execute("SELECT COUNT(*) FROM menu_mst")
        (menu_count,) = cursor.fetchone()
        if menu_count == 0:
            for key, name, order, icon, activity in _TOP_CARDS:
                _insert_menu(cursor, key, name, None, order, icon, activity, 0)
            _seed_menu_tree(cursor, _MENU_TREE, None)
            db.commit()

            # Admin -> can_all on every menu
            cursor.execute(
                """
                INSERT INTO role_menu_map
                    (role_id, menu_id, can_view, can_add, can_modify,
                     can_delete, can_print, can_all)
                SELECT r.id, m.id, 1, 1, 1, 1, 1, 1
                FROM   roles r, menu_mst m
                WHERE  r.role_name = 'Admin'
                """
            )
            # Manager -> everything except delete
            cursor.execute(
                """
                INSERT INTO role_menu_map
                    (role_id, menu_id, can_view, can_add, can_modify,
                     can_delete, can_print, can_all)
                SELECT r.id, m.id, 1, 1, 1, 0, 1, 0
                FROM   roles r, menu_mst m
                WHERE  r.role_name = 'Manager'
                """
            )
            # Supervisor -> production + attendance subset
            ph = ", ".join(["%s"] * len(_SUPERVISOR_KEYS))
            cursor.execute(
                f"""
                INSERT INTO role_menu_map
                    (role_id, menu_id, can_view, can_add, can_modify,
                     can_delete, can_print, can_all)
                SELECT r.id, m.id, 1, 1, 0, 0, 1, 0
                FROM   roles r, menu_mst m
                WHERE  r.role_name = 'Supervisor'
                  AND  m.menu_key IN ({ph})
                """,
                _SUPERVISOR_KEYS,
            )
            # Operator -> very small subset
            ph = ", ".join(["%s"] * len(_OPERATOR_KEYS))
            cursor.execute(
                f"""
                INSERT INTO role_menu_map
                    (role_id, menu_id, can_view, can_add, can_modify,
                     can_delete, can_print, can_all)
                SELECT r.id, m.id, 1, 1, 0, 0, 0, 0
                FROM   roles r, menu_mst m
                WHERE  r.role_name = 'Operator'
                  AND  m.menu_key IN ({ph})
                """,
                _OPERATOR_KEYS,
            )
            # Viewer -> view + print on every menu
            cursor.execute(
                """
                INSERT INTO role_menu_map
                    (role_id, menu_id, can_view, can_add, can_modify,
                     can_delete, can_print, can_all)
                SELECT r.id, m.id, 1, 0, 0, 0, 1, 0
                FROM   roles r, menu_mst m
                WHERE  r.role_name = 'Viewer'
                """
            )
            db.commit()
            print("   [OK] Seeded menus and default role permissions")

        # ---- Assign user_mst.user_id = 1 to Admin -----------------------
        cursor.execute(
            """
            SELECT 1 FROM user_role_map ur
            JOIN roles r ON r.id = ur.role_id
            WHERE ur.user_id = 1 AND r.role_name = 'Admin'
            """
        )
        if cursor.fetchone() is None:
            cursor.execute("SELECT 1 FROM user_mst WHERE user_id = 1")
            if cursor.fetchone() is not None:
                cursor.execute(
                    """
                    INSERT IGNORE INTO user_role_map (user_id, role_id)
                    SELECT 1, id FROM roles WHERE role_name = 'Admin'
                    """
                )
                db.commit()
                print("   [OK] Granted Admin to user_mst.user_id = 1")

        cursor.close()
        db.close()
        print("[OK] Permission tables ready")
    except Exception as e:
        print(f"[WARN] Permissions migration error (non-fatal): {e}")
