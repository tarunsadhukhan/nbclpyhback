"""
SQL Queries for Onboarding Module
"""
GET_EMPLOYEE_BY_EMP_CODE = """
    SELECT p.eb_id,
           o.emp_code,
           CONCAT(p.first_name, ' ', COALESCE(p.middle_name, ''), ' ', COALESCE(p.last_name, '')) AS name,
           o.sub_dept_id,
           o.designation_id,
           o.branch_id,
           s.sub_dept_desc AS department_name,
           d.desig AS designation_name
    FROM hrms_ed_official_details o
    INNER JOIN hrms_ed_personal_details p ON o.eb_id = p.eb_id
    LEFT JOIN sub_dept_mst s ON o.sub_dept_id = s.sub_dept_id
    LEFT JOIN designation_mst d ON o.designation_id = d.designation_id
    WHERE o.emp_code = %s AND p.active = 1
      AND p.status_id = 35   -- JOINED: same eligibility as attendance's /employee/<code>
    LIMIT 1
"""
GET_EMPLOYEE_BY_EMP_CODE_AND_BRANCH = """
    SELECT p.eb_id,
           o.emp_code,
           CONCAT(p.first_name, ' ', COALESCE(p.middle_name, ''), ' ', COALESCE(p.last_name, '')) AS name,
           o.sub_dept_id,
           o.designation_id,
           o.branch_id,
           s.sub_dept_desc AS department_name,
           d.desig AS designation_name
    FROM hrms_ed_official_details o
    INNER JOIN hrms_ed_personal_details p ON o.eb_id = p.eb_id
    LEFT JOIN sub_dept_mst s ON o.sub_dept_id = s.sub_dept_id
    LEFT JOIN designation_mst d ON o.designation_id = d.designation_id
    WHERE o.emp_code = %s AND o.branch_id = %s AND p.active = 1
      AND p.status_id = 35   -- JOINED: same eligibility as attendance's /employee/<code>
    LIMIT 1
"""

# Why a code was NOT matched above: exists with another HR status (OPEN, RESIGNED, ...)
# so the operator hears "not JOINED" at enrolment instead of "not found" at attendance.
GET_EMPLOYEE_STATUS_ANY = """
    SELECT TRIM(CONCAT(p.first_name, ' ', COALESCE(p.middle_name, ''), ' ',
                       COALESCE(p.last_name, ''))) AS name,
           s.status_name
    FROM hrms_ed_official_details o
    INNER JOIN hrms_ed_personal_details p ON o.eb_id = p.eb_id
    LEFT JOIN status_mst s ON s.status_id = p.status_id
    WHERE o.emp_code = %s AND p.active = 1 AND (%s IS NULL OR o.branch_id = %s)
    LIMIT 1
"""
GET_FACE_COUNT = """
    SELECT COUNT(*) AS cnt
    FROM employee_face_mst
    WHERE eb_id = %s AND active = 1
"""
INSERT_FACE = """
    INSERT INTO employee_face_mst (eb_id, face_embedding, active, photo_html, updated_by, updated_date_time)
    VALUES (%s, %s, 1, %s, 0, NOW())
"""

# ── New outsider registration (the "+" on the mobile onboarding screen) ──────
# The series is the FIRST THREE CHARACTERS of emp_code (FOS / MOS); everything
# after them is the number, zero-padded to 4 (FOS0367 … FOS2196).
#
# The digits test is not decoration: CAST('TEMP' AS UNSIGNED) is 0 in MySQL, so
# one stray non-numeric code in the series would silently restart numbering at 1
# and hand out a code that already exists.

NEXT_NO_IN_BRANCH = """
    SELECT COALESCE(MAX(CAST(SUBSTRING(emp_code, 4) AS UNSIGNED)), 0) AS last_no
    FROM hrms_ed_official_details
    WHERE branch_id = %s
      AND LEFT(emp_code, 3) = %s
      AND SUBSTRING(emp_code, 4) REGEXP '^[0-9]+$'
"""

# Numbering is per branch, but emp_code is what every lookup keys on, so a
# number already used by ANY branch is skipped rather than duplicated.
CODE_EXISTS_ANYWHERE = """
    SELECT 1 FROM hrms_ed_official_details WHERE emp_code = %s LIMIT 1
"""

# NOT NULL columns the mobile form does not collect. Copied from the newest
# employee of the same series, so a new outsider is categorised exactly like the
# outsiders already in the system and no category id is hard-coded in the app.
SERIES_DEFAULTS = """
    SELECT catagory_id, reporting_eb_id, minimum_working_commitment
    FROM hrms_ed_official_details
    WHERE LEFT(emp_code, 3) = %s
    ORDER BY eb_id DESC
    LIMIT 1
"""

# status_id 35 = JOINED. Anything else and the worker is refused by both face
# enrolment and attendance the moment registration finishes.
INSERT_PERSONAL = """
    INSERT INTO hrms_ed_personal_details
        (first_name, gender, branch_id, active, status_id, updated_by, updated_date_time)
    VALUES (%s, %s, %s, 1, 35, %s, NOW())
"""

INSERT_OFFICIAL = """
    INSERT INTO hrms_ed_official_details
        (eb_id, emp_code, sub_dept_id, designation_id, branch_id, date_of_join,
         catagory_id, reporting_eb_id, minimum_working_commitment,
         active, updated_by, updated_date_time)
    VALUES (%s, %s, %s, %s, %s, CURDATE(), %s, %s, %s, 1, %s, NOW())
"""

# Same insert plus the device-computed MobileFaceNet embedding, so the new face
# is matchable offline straight away. Only valid after offline_sync.sql.
INSERT_FACE_WITH_MOBILE = """
    INSERT INTO employee_face_mst (eb_id, face_embedding, active, photo_html, updated_by,
                                   updated_date_time, face_embedding_mobile,
                                   mobile_model_ver, mobile_embed_updated)
    VALUES (%s, %s, 1, %s, 0, NOW(), %s, %s, NOW())
"""
