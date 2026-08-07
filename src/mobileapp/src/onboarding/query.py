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
