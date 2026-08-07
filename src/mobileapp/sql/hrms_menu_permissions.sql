-- =============================================================================
-- HRMS menu seed + effective-permissions view
-- =============================================================================
-- Mirrors the menu currently shown in vowerp3ui's portal HRMS section
-- (src/app/dashboardportal/hrms/*). Creates NO new tables -- it only seeds the
-- existing `menus` table and (re)creates the `v_user_effective_permissions`
-- view, which both already exist in the target HRMS database (e.g. sjm).
--
-- Usage:
--   USE sjm;            -- or whichever tenant DB has the menu/permission tables
--   SOURCE hrms_menu_permissions.sql;
--
-- The script is idempotent: re-running it updates the rows in place (matched on
-- menu_key) and replaces the view. Parent links are resolved by menu_key, so it
-- does not depend on any hard-coded auto-increment id.
-- =============================================================================

-- ── 1. HRMS parent group ─────────────────────────────────────────────────────
INSERT INTO menus
    (menu_key, menu_name, parent_id, menu_order, icon, activity_class, is_group, is_active)
VALUES
    ('grp_hrms', 'HRMS', NULL, 100, 'ic_employee', NULL, 1, 1)
ON DUPLICATE KEY UPDATE
    menu_name = VALUES(menu_name),
    menu_order = VALUES(menu_order),
    icon       = VALUES(icon),
    is_group   = VALUES(is_group),
    is_active  = VALUES(is_active);

-- Capture the parent id by key (cannot subquery the INSERT target table inline).
SET @hrms_parent := (SELECT id FROM menus WHERE menu_key = 'grp_hrms');

-- ── 2. HRMS leaf menus (order matches the vowerp3ui sidebar) ──────────────────
INSERT INTO menus
    (menu_key, menu_name, parent_id, menu_order, icon, activity_class, is_group, is_active)
VALUES
    ('hrms_employee_database', 'Employee Database',  @hrms_parent, 1, 'ic_employee', '/dashboardportal/hrms/employeeDatabase',            0, 1),
    ('hrms_pay_scheme',        'Pay Schemes',         @hrms_parent, 2, 'ic_masters',  '/dashboardportal/hrms/payScheme',                   0, 1),
    ('hrms_pay_param',         'Pay Periods',         @hrms_parent, 3, 'ic_masters',  '/dashboardportal/hrms/payParam',                    0, 1),
    ('hrms_pay_register',      'Pay Register',        @hrms_parent, 4, 'ic_report',   '/dashboardportal/hrms/payRegister',                 0, 1),
    ('hrms_payroll',           'Payroll',             @hrms_parent, 5, 'ic_report',   '/dashboardportal/hrms/payRoll',                     0, 1),
    ('hrms_leave_request',     'Leave Requests',      @hrms_parent, 6, 'ic_edit',     '/dashboardportal/hrms/hrmsmasters/leaveRequest',    0, 1),
    ('hrms_leave_master',      'Leave Type Master',   @hrms_parent, 7, 'ic_masters',  '/dashboardportal/hrmsmasters/LeaveMaster',          0, 1)
ON DUPLICATE KEY UPDATE
    menu_name      = VALUES(menu_name),
    parent_id      = VALUES(parent_id),
    menu_order     = VALUES(menu_order),
    icon           = VALUES(icon),
    activity_class = VALUES(activity_class),
    is_group       = VALUES(is_group),
    is_active      = VALUES(is_active);

-- ── 3. Effective-permissions view (same structure as the existing one) ────────
-- can_* = per-user override (user_menu_permissions) if present, else the role
-- default (role_menu_permissions), else 0. One row per (user, menu).
CREATE OR REPLACE
    ALGORITHM = UNDEFINED
    SQL SECURITY DEFINER
VIEW v_user_effective_permissions AS
SELECT
    ur.user_id   AS user_id,
    m.id         AS menu_id,
    m.menu_key   AS menu_key,
    MAX(COALESCE(ump.can_view,   rmp.can_view,   0)) AS can_view,
    MAX(COALESCE(ump.can_add,    rmp.can_add,    0)) AS can_add,
    MAX(COALESCE(ump.can_modify, rmp.can_modify, 0)) AS can_modify,
    MAX(COALESCE(ump.can_delete, rmp.can_delete, 0)) AS can_delete,
    MAX(COALESCE(ump.can_print,  rmp.can_print,  0)) AS can_print,
    MAX(COALESCE(ump.can_all,    rmp.can_all,    0)) AS can_all
FROM user_roles ur
JOIN menus m
LEFT JOIN role_menu_permissions rmp
       ON rmp.role_id = ur.role_id
      AND rmp.menu_id = m.id
LEFT JOIN user_menu_permissions ump
       ON ump.user_id = ur.user_id
      AND ump.menu_id = m.id
GROUP BY ur.user_id, m.id, m.menu_key;
