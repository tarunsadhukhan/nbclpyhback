GET_EMPLOYEE_BY_CODE = """
    SELECT p.eb_id,
           o.emp_code,
           CONCAT(p.first_name, ' ', COALESCE(p.middle_name, ''), ' ', COALESCE(p.last_name, '')) AS name,
           o.sub_dept_id,
           o.designation_id,
           o.branch_id,
           s.sub_dept_desc AS department_name,
           d.desig         AS designation_name,
           (SELECT f.photo_html
              FROM employee_face_mst f
             WHERE f.eb_id = p.eb_id AND f.active = 1
             ORDER BY f.updated_date_time DESC, f.emp_face_id DESC
             LIMIT 1)      AS photo_html
    FROM hrms_ed_official_details o
    INNER JOIN hrms_ed_personal_details p ON o.eb_id = p.eb_id
    LEFT JOIN sub_dept_mst    s ON o.sub_dept_id    = s.sub_dept_id
    LEFT JOIN designation_mst d ON o.designation_id = d.designation_id
    WHERE o.emp_code = %s AND o.branch_id = %s AND p.active = 1
    AND p.status_id=35
    LIMIT 1
"""


GET_EMPLOYEE_WITH_DETAILS = GET_EMPLOYEE_BY_CODE


# Most recent attendance row for an employee — used to pre-fill the attendance
# entry screen with the last-worked department/designation and machines.
GET_LAST_WORKED_BY_EB = """
    SELECT worked_department_id,
           worked_designation_id,
           daily_atten_id
    FROM daily_attendance
    WHERE eb_id = %s AND branch_id = %s AND (is_active IS NULL OR is_active = 1)
    ORDER BY attendance_date DESC, daily_atten_id DESC
    LIMIT 1
"""
print(f"{GET_LAST_WORKED_BY_EB} GET_LAST_WORKED_BY_EB query loaded")

GET_LAST_WORKED_MACHINES = """
    SELECT mc_id
    FROM daily_ebmc_attendance
    WHERE daily_atten_id = %s AND is_active = 1
"""

GET_ALL_EMPLOYEES = """
    SELECT p.eb_id,
           o.emp_code,
           CONCAT(p.first_name, ' ', COALESCE(p.middle_name, ''), ' ', COALESCE(p.last_name, '')) AS name,
           o.sub_dept_id,
           o.designation_id,
           o.branch_id,
           s.sub_dept_desc AS department_name,
           d.desig         AS designation_name,
           COUNT(f.emp_face_id) AS face_count,
           MAX(f.photo_html)    AS photo_html
    FROM hrms_ed_official_details o
    INNER JOIN hrms_ed_personal_details p ON o.eb_id = p.eb_id
    LEFT JOIN sub_dept_mst    s ON o.sub_dept_id    = s.sub_dept_id
    LEFT JOIN designation_mst d ON o.designation_id = d.designation_id
    LEFT JOIN employee_face_mst f ON p.eb_id = f.eb_id AND f.active = 1
    WHERE p.active = 1
    GROUP BY p.eb_id, o.emp_code, p.first_name, p.middle_name, p.last_name,
             o.sub_dept_id, o.designation_id, o.branch_id, s.sub_dept_desc, d.desig
    ORDER BY name
"""

GET_ALL_EMPLOYEES_WITH_FACE = """
    SELECT p.eb_id,
           o.emp_code,
           CONCAT(p.first_name, ' ', COALESCE(p.middle_name, ''), ' ', COALESCE(p.last_name, '')) AS name,
           o.sub_dept_id,
           o.designation_id,
           o.branch_id,
           f.face_embedding,
           s.sub_dept_desc AS department_name,
           d.desig         AS designation_name,
           f.photo_html
    FROM employee_face_mst f
    INNER JOIN hrms_ed_official_details o ON f.eb_id = o.eb_id
    INNER JOIN hrms_ed_personal_details p ON f.eb_id = p.eb_id
    LEFT JOIN sub_dept_mst    s ON o.sub_dept_id    = s.sub_dept_id
    LEFT JOIN designation_mst d ON o.designation_id = d.designation_id
    WHERE p.active = 1 AND f.active = 1 and p.status_id=35
"""

# lookup helpers used during registration
GET_DEPT_ID_BY_NAME  = "SELECT sub_dept_id AS id FROM sub_dept_mst WHERE sub_dept_name = %s"
GET_DESIG_ID_BY_NAME = "SELECT id FROM occupations WHERE name = %s"
GET_SHIFT_ID_BY_NAME = "SELECT id FROM shifts WHERE name = %s"

INSERT_EMPLOYEE = """
    INSERT INTO employees
      (emp_code, name, department_id, designation_id, shift_id, face_embedding, photo_html)
    VALUES (%s, %s, %s, %s, %s, %s, %s)
"""

UPDATE_EMPLOYEE_FACE = "UPDATE employees SET face_embedding = %s WHERE emp_code = %s"

SOFT_DELETE_EMPLOYEE = "UPDATE employees SET is_active = 0 WHERE id = %s"


# Bulk form of GET_LAST_WORKED_BY_EB + GET_LAST_WORKED_MACHINES: every active
# employee's most recent attendance in a branch, plus that row's machines, in
# one round trip. The app's masters warm-up fills its offline last_entry table
# from this — the per-employee form would be one request per employee.
# Same employee filter as GET_EMPLOYEE_BY_CODE, so the offline pre-fill matches
# what the online lookup would have returned.
GET_LAST_ENTRIES_BY_BRANCH = """
    SELECT t.emp_code,
           t.worked_department_id,
           t.worked_designation_id,
           m.mc_id
    FROM (
        SELECT o.emp_code,
               a.worked_department_id,
               a.worked_designation_id,
               a.daily_atten_id,
               ROW_NUMBER() OVER (PARTITION BY a.eb_id
                                  ORDER BY a.attendance_date DESC,
                                           a.daily_atten_id  DESC) AS rn
        FROM daily_attendance a
        INNER JOIN hrms_ed_official_details o
                ON o.eb_id = a.eb_id AND o.branch_id = a.branch_id
        INNER JOIN hrms_ed_personal_details p
                ON p.eb_id = o.eb_id AND p.active = 1 AND p.status_id = 35
        WHERE a.branch_id = %s AND (a.is_active IS NULL OR a.is_active = 1)
    ) t
    LEFT JOIN daily_ebmc_attendance m
           ON m.daily_atten_id = t.daily_atten_id AND m.is_active = 1
    WHERE t.rn = 1
"""
