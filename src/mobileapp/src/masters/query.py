# ── Departments ──────────────────────────────────────────────
# ponytail: GROUP BY name — same name can repeat under different parent rows;
# attendance-report filters match sibling ids by name so MIN(id) is safe
GET_ALL_DEPARTMENTS = """
    SELECT MIN(sub_dept_id) AS id, sub_dept_desc AS name
    FROM sub_dept_mst
    GROUP BY sub_dept_desc
    ORDER BY sub_dept_desc
"""

GET_DEPARTMENTS_BY_BRANCH = """
    SELECT MIN(s.sub_dept_id) AS id, s.sub_dept_desc AS name
    FROM sub_dept_mst s
    JOIN dept_mst d ON s.dept_id = d.dept_id
    WHERE d.branch_id = %s
    GROUP BY s.sub_dept_desc
    ORDER BY s.sub_dept_desc
"""

GET_DEPARTMENTS_BY_COMPANY_BRANCH = """
    SELECT MIN(s.sub_dept_id) AS id, s.sub_dept_desc AS name
    FROM sub_dept_mst s
    JOIN dept_mst d ON s.dept_id = d.dept_id
    JOIN branch_mst b ON d.branch_id = b.branch_id
    WHERE b.co_id = %s AND d.branch_id = %s
    GROUP BY s.sub_dept_desc
    ORDER BY s.sub_dept_desc
"""

GET_DEPARTMENTS_BY_COMPANY = """
    SELECT MIN(s.sub_dept_id) AS id, s.sub_dept_desc AS name
    FROM sub_dept_mst s
    JOIN dept_mst d ON s.dept_id = d.dept_id
    JOIN branch_mst b ON d.branch_id = b.branch_id
    WHERE b.co_id = %s
    GROUP BY s.sub_dept_desc
    ORDER BY s.sub_dept_desc
"""

GET_DEPT_BY_NAME    = "SELECT sub_dept_id AS id FROM sub_dept_mst WHERE sub_dept_desc = %s"
INSERT_DEPARTMENT   = "INSERT INTO sub_dept_mst (sub_dept_desc) VALUES (%s)"
UPDATE_DEPARTMENT   = "UPDATE sub_dept_mst SET sub_dept_desc = %s WHERE sub_dept_id = %s"
DELETE_DEPARTMENT   = "DELETE FROM sub_dept_mst WHERE sub_dept_id = %s"

# Designations (from designation_mst)
GET_DESIGNATIONS_BY_BRANCH = """
    SELECT MIN(designation_id) AS id, desig AS name
    FROM designation_mst
    WHERE branch_id = %s AND active = 1
    GROUP BY desig
    ORDER BY desig
"""

GET_DESIGNATIONS_BY_DEPT_BRANCH = """
    SELECT MIN(dm.designation_id) AS id, dm.desig AS name
    FROM designation_mst dm
    JOIN sub_dept_mst s   ON dm.dept_id = s.dept_id
    JOIN sub_dept_mst sel ON sel.sub_dept_desc = s.sub_dept_desc
    WHERE sel.sub_dept_id = %s AND dm.branch_id = %s AND dm.active = 1
    GROUP BY dm.desig
    ORDER BY dm.desig
"""

# ── Shifts ────────────────────────────────────────────────────
GET_ALL_SHIFTS    = "SELECT id, name, start_time, end_time FROM shifts ORDER BY start_time"
GET_SHIFT_BY_NAME = "SELECT id FROM shifts WHERE name = %s"
INSERT_SHIFT      = "INSERT INTO shifts (name, start_time, end_time) VALUES (%s, %s, %s)"
UPDATE_SHIFT      = "UPDATE shifts SET name = %s, start_time = %s, end_time = %s WHERE id = %s"
DELETE_SHIFT      = "DELETE FROM shifts WHERE id = %s"

# ── Occupations ───────────────────────────────────────────────
GET_ALL_OCCUPATIONS = "SELECT id, name, created_at FROM occupations ORDER BY name"
GET_OCC_BY_NAME     = "SELECT id FROM occupations WHERE name = %s"
INSERT_OCCUPATION   = "INSERT INTO occupations (name) VALUES (%s)"
UPDATE_OCCUPATION   = "UPDATE occupations SET name = %s WHERE id = %s"
DELETE_OCCUPATION   = "DELETE FROM occupations WHERE id = %s"

# ── Companies / Branches (SLS masters) ─────────────────────────────
GET_ALL_COMPANIES = """
    SELECT
        co_id,
        co_name,
        co_logo
    FROM co_mst cm
    ORDER BY co_name
"""



GET_BRANCHES_BY_COMPANY = """
    SELECT
        branch_id AS br_id,
        co_id,
        branch_name AS br_name
    FROM branch_mst
    WHERE co_id = %s
    ORDER BY branch_name
"""


# Companies the logged-in user is mapped to (user_role_map.co_id).
GET_COMPANIES_BY_USER = """
    SELECT DISTINCT
        cm.co_id,
        cm.co_name,
        cm.co_logo
    FROM user_role_map urm
    JOIN co_mst cm ON cm.co_id = urm.co_id
    WHERE urm.user_id = %s
    ORDER BY cm.co_name
"""


# Branches the user is mapped to within a company (user_role_map.branch_id).
GET_BRANCHES_BY_USER_COMPANY = """
    SELECT DISTINCT
        bm.branch_id AS br_id,
        bm.co_id,
        bm.branch_name AS br_name
    FROM user_role_map urm
    JOIN branch_mst bm ON bm.branch_id = urm.branch_id
    WHERE urm.user_id = %s AND urm.co_id = %s
    ORDER BY bm.branch_name
"""


