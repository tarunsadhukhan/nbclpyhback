-- Seed the 8 missing HRMS report menus in the sls tenant DB, mirroring the role
-- access rows of the existing Full Attendance report (menu_id 956).
-- Idempotent: skips menu paths already present.
-- Target DB: sls (run via the run-migration flow).
--
-- Attendance Checklist (legacy report 657) is included: its page has existed at
-- hrms/attendanceChecklist all along but had NO menu_mst row, which both hid it
-- from the reports dropdown and made portal middleware deny the route. It is
-- parented to HRMS Reports (955) but keeps its own top-level page path.
--
-- NOT seeded here: Attendance Register / Attendance Summary / Worker Master /
-- Man-Machine Deployment / Employee Working Details. Those pages and menus
-- already exist as menu_id 947-954 under Jute Production > Production Reports
-- (945). menu_mst.menu_name carries a UNIQUE index, so they cannot be listed
-- under HRMS Reports as well without renaming or reparenting them.

INSERT INTO menu_mst (menu_name, menu_path, menu_parent_id, menu_icon, report, active, order_by)
SELECT t.menu_name, t.menu_path, 955, 'assessment', 1, 1, t.order_by
FROM (
    SELECT 'Attendance Checklist' AS menu_name, 'hrms/attendanceChecklist' AS menu_path, 85 AS order_by
    UNION ALL SELECT 'Department Wise Summary', 'hrms/hrmsreports/departmentSummary', 140
    UNION ALL SELECT 'Sub-Department Wise Summary', 'hrms/hrmsreports/deptSubSummary', 150
    UNION ALL SELECT 'Category Wise Summary', 'hrms/hrmsreports/categorySummary', 160
    UNION ALL SELECT 'Designation Wise Summary', 'hrms/hrmsreports/designationSummary', 170
    UNION ALL SELECT 'Department Category Summary', 'hrms/hrmsreports/deptCatSummary', 180
    UNION ALL SELECT 'Spell Wise Summary', 'hrms/hrmsreports/spellWise', 190
    UNION ALL SELECT 'Employee Bank Statement', 'hrms/hrmsreports/bankStatement', 200
) AS t
WHERE NOT EXISTS (SELECT 1 FROM menu_mst m WHERE m.menu_path = t.menu_path);

-- Give every role that can see Full Attendance (956) the same access to each
-- new report menu.
INSERT INTO role_menu_map (role_id, menu_id, access_type_id, updated_by)
SELECT src.role_id, m.menu_id, src.access_type_id, 4
FROM menu_mst m
JOIN (
    SELECT DISTINCT role_id, access_type_id
    FROM role_menu_map WHERE menu_id = 956
) AS src
WHERE m.menu_parent_id = 955
    AND m.menu_path IN (
        'hrms/attendanceChecklist',
        'hrms/hrmsreports/departmentSummary',
        'hrms/hrmsreports/deptSubSummary',
        'hrms/hrmsreports/categorySummary',
        'hrms/hrmsreports/designationSummary',
        'hrms/hrmsreports/deptCatSummary',
        'hrms/hrmsreports/spellWise',
        'hrms/hrmsreports/bankStatement'
    )
    AND NOT EXISTS (
        SELECT 1 FROM role_menu_map r
        WHERE r.menu_id = m.menu_id AND r.role_id = src.role_id
            AND r.access_type_id = src.access_type_id
    );
