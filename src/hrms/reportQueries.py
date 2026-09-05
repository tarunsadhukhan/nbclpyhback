"""
HRMS / labour report queries (surfaced under Jute Production > Production Reports).
Built on dev3's daily_attendance + employee/department/designation masters.
"""

from sqlalchemy import text


def get_attendance_summary_query():
    """
    Attendance summary: per department + designation, total worked hours
    (working_hours - idle_hours) and "Hands" (worked hours / 8 = man-days).

    Parameters:
        :co_id (int) - required
        :branch_id (int or NULL) - optional
        :date_from, :date_to (str) - required range
        :spell (str or NULL) - optional spell filter
    """
    sql = """
    SELECT
        sd.sub_dept_desc AS department,
        dsg.desig AS designation,
        ROUND(SUM(da.working_hours - COALESCE(da.idle_hours, 0)), 2) AS work_hours,
        ROUND(SUM(da.working_hours - COALESCE(da.idle_hours, 0)) / 8, 2) AS hands
    FROM daily_attendance AS da
    INNER JOIN branch_mst AS bm ON bm.branch_id = da.branch_id
    LEFT JOIN sub_dept_mst AS sd ON sd.sub_dept_id = da.worked_department_id
    LEFT JOIN designation_mst AS dsg ON dsg.designation_id = da.worked_designation_id
    LEFT JOIN spell_mst AS sp ON sp.spell_id = da.spell_id
    WHERE da.attendance_date >= :date_from
        AND da.attendance_date <= :date_to
        AND da.is_active = 1
        AND da.status_id = 3
        AND bm.co_id = :co_id
        AND (:branch_id IS NULL OR da.branch_id = :branch_id)
        AND (:spell IS NULL OR da.spell = :spell OR sp.spell_name = :spell)
    GROUP BY da.worked_department_id, sd.sub_dept_desc,
             da.worked_designation_id, dsg.desig
    ORDER BY sd.sub_dept_desc, dsg.desig;
    """
    return text(sql)


def get_worker_master_query():
    """
    Worker / employee master listing with last working day, sourced from the
    dev3 HRMS employee tables (hrms_ed_*). Department resolves via the employee's
    sub-department. Last working day = latest active attendance date.

    Parameters:
        :co_id (int) - required (scoped via the employee's branch)
        :branch_id (int or NULL) - optional
        :search_like (str or NULL) - emp_code / name LIKE
    """
    sql = """
    SELECT
        pd.eb_id,
        od.emp_code,
        CONCAT(
            pd.first_name, ' ',
            IFNULL(pd.middle_name, ''), ' ',
            IFNULL(pd.last_name, '')
        ) AS emp_name,
        pd.gender,
        dm.dept_desc,
        sd.sub_dept_desc,
        dsg.desig AS designation,
        cm.cata_desc AS category,
        pd.date_of_birth,
        od.date_of_join,
        cnt.contractor_name,
        esi.esi_no,
        pf.pf_no,
        pf.pf_uan_no,
        bd.bank_acc_no,
        bd.bank_name,
        ps.NAME AS pay_scheme,
        sm.status_name,
        CASE WHEN pd.active = 1 THEN 'Active' ELSE 'InActive' END AS is_active,
        da.last_working_day
    FROM hrms_ed_personal_details AS pd
    INNER JOIN branch_mst AS bm ON bm.branch_id = pd.branch_id
    LEFT JOIN hrms_ed_official_details AS od
        ON od.eb_id = pd.eb_id AND od.active = 1
    LEFT JOIN sub_dept_mst AS sd ON sd.sub_dept_id = od.sub_dept_id
    LEFT JOIN dept_mst AS dm ON dm.dept_id = sd.dept_id
    LEFT JOIN designation_mst AS dsg ON dsg.designation_id = od.designation_id
    LEFT JOIN category_mst AS cm ON cm.cata_id = od.catagory_id
    LEFT JOIN contractor_mst AS cnt ON cnt.cont_id = od.contractor_id
    LEFT JOIN hrms_ed_esi AS esi ON esi.eb_id = pd.eb_id AND esi.active = 1
    LEFT JOIN hrms_ed_pf AS pf ON pf.eb_id = pd.eb_id AND pf.active = 1
    LEFT JOIN hrms_ed_bank_details AS bd ON bd.eb_id = pd.eb_id AND bd.active = 1
    LEFT JOIN pay_employee_payscheme AS pep
        ON pep.EMPLOYEEID = pd.eb_id AND pep.STATUS = 1
    LEFT JOIN pay_scheme AS ps ON ps.ID = pep.PAY_SCHEME_ID
    LEFT JOIN status_mst AS sm ON sm.status_id = pd.status_id
    LEFT JOIN (
        SELECT eb_id, MAX(attendance_date) AS last_working_day
        FROM daily_attendance WHERE is_active = 1 GROUP BY eb_id
    ) AS da ON da.eb_id = pd.eb_id
    WHERE pd.active = 1
        AND bm.co_id = :co_id
        AND (:branch_id IS NULL OR pd.branch_id = :branch_id)
        AND (
            :search_like IS NULL
            OR od.emp_code LIKE :search_like
            OR CONCAT(pd.first_name, ' ', IFNULL(pd.last_name, '')) LIKE :search_like
        )
    ORDER BY od.emp_code, pd.eb_id;
    """
    return text(sql)


def get_man_machine_query():
    """
    Man-machine deployment (dev3-native): per machine, designation and spell,
    the number of workers deployed (hands) and total machine stoppage hours,
    from daily_ebmc_attendance.

    NOTE: the legacy report 684 pivoted precomputed shift-hands vs targets from a
    separate EMPMILL12 database that dev3 does not have; this is the equivalent
    built from dev3's own machine-attendance data.

    Parameters:
        :co_id (int) - required
        :branch_id (int or NULL) - optional
        :date_from, :date_to (str) - required range
    """
    sql = """
    SELECT
        mm.machine_name,
        dm.dept_desc AS department,
        dsg.desig AS designation,
        COALESCE(sp.spell_name, dea.spell) AS spell,
        COUNT(DISTINCT dea.eb_id) AS hands,
        ROUND(SUM(COALESCE(dea.mc_stoppage_hours, 0)), 2) AS stoppage_hours
    FROM daily_ebmc_attendance AS dea
    INNER JOIN branch_mst AS bm ON bm.branch_id = dea.branch_id
    LEFT JOIN machine_mst AS mm ON mm.machine_id = dea.mc_id
    LEFT JOIN designation_mst AS dsg ON dsg.designation_id = dea.designation_id
    LEFT JOIN dept_mst AS dm ON dm.dept_id = dsg.dept_id
    LEFT JOIN spell_mst AS sp ON sp.spell_id = dea.spell_id
    WHERE dea.attendace_date >= :date_from
        AND dea.attendace_date <= :date_to
        AND dea.is_active = 1
        AND bm.co_id = :co_id
        AND (:branch_id IS NULL OR dea.branch_id = :branch_id)
    GROUP BY dea.mc_id, mm.machine_name, dm.dept_desc,
             dea.designation_id, dsg.desig, COALESCE(sp.spell_name, dea.spell)
    ORDER BY mm.machine_name, dsg.desig, spell;
    """
    return text(sql)


def get_attendance_register_query():
    """
    Attendance register: flat daily_attendance detail rows (one per punch/spell)
    with employee name, department, designation, mark (P/A/HD/L), spell and hours.

    Parameters:
        :co_id (int) - required
        :branch_id (int or NULL) - optional
        :date_from, :date_to (str) - required range
    """
    sql = """
    SELECT
        da.daily_atten_id AS tran_no,
        COALESCE(od.emp_code, da.eb_no, da.eb_code) AS eb_no,
        CONCAT(
            IFNULL(pd.first_name, ''), ' ',
            IFNULL(pd.middle_name, ''), ' ',
            IFNULL(pd.last_name, '')
        ) AS emp_name,
        da.attendance_date,
        sd.sub_dept_desc AS department,
        dsg.desig AS designation,
        da.attendance_mark AS mark,
        COALESCE(sp.spell_name, da.spell) AS spell,
        da.idle_hours,
        da.spell_hours,
        da.working_hours,
        sm.status_name
    FROM daily_attendance AS da
    INNER JOIN branch_mst AS bm ON bm.branch_id = da.branch_id
    LEFT JOIN hrms_ed_personal_details AS pd ON pd.eb_id = da.eb_id
    LEFT JOIN hrms_ed_official_details AS od ON od.eb_id = da.eb_id AND od.active = 1
    LEFT JOIN sub_dept_mst AS sd ON sd.sub_dept_id = da.worked_department_id
    LEFT JOIN designation_mst AS dsg ON dsg.designation_id = da.worked_designation_id
    LEFT JOIN status_mst AS sm ON sm.status_id = da.status_id
    LEFT JOIN spell_mst AS sp ON sp.spell_id = da.spell_id
    WHERE da.attendance_date >= :date_from
        AND da.attendance_date <= :date_to
        AND da.is_active = 1
        AND bm.co_id = :co_id
        AND (:branch_id IS NULL OR da.branch_id = :branch_id)
    ORDER BY da.attendance_date, da.eb_no;
    """
    return text(sql)


def get_employee_working_query():
    """
    Employee working details (report 650): per employee per month, work days
    (worked hours / 7.5 for spell 'C', / 8 otherwise), leave days (approved
    leaves), and total. Holiday days are 0 — the tenant has no holiday table.

    Parameters:
        :co_id (int) - required
        :branch_id (int or NULL) - optional
        :date_from, :date_to (str) - required range
    """
    sql = """
    SELECT
        w.yearmn,
        od.emp_code,
        CONCAT(
            IFNULL(pd.first_name, ''), ' ',
            IFNULL(pd.middle_name, ''), ' ',
            IFNULL(pd.last_name, '')
        ) AS emp_name,
        dm.dept_desc AS department,
        cm.cata_desc AS category,
        sm.status_name,
        w.wdays,
        w.lvdays,
        w.hldays,
        (w.wdays + w.lvdays + w.hldays) AS total_days
    FROM (
        SELECT yearmn, eb_id,
               SUM(wdays) AS wdays, SUM(lvdays) AS lvdays, SUM(hldays) AS hldays
        FROM (
            SELECT
                CONCAT(YEAR(da.attendance_date), '-',
                       LPAD(MONTH(da.attendance_date), 2, '0')) AS yearmn,
                da.eb_id,
                CEIL(SUM(da.working_hours - COALESCE(da.idle_hours, 0)) / 7.5) AS wdays,
                0 AS lvdays, 0 AS hldays
            FROM daily_attendance AS da
            INNER JOIN branch_mst AS bm ON bm.branch_id = da.branch_id
            LEFT JOIN spell_mst AS sp ON sp.spell_id = da.spell_id
            WHERE da.is_active = 1 AND bm.co_id = :co_id
                AND (:branch_id IS NULL OR da.branch_id = :branch_id)
                AND da.attendance_date BETWEEN :date_from AND :date_to
                AND (da.spell = 'C' OR sp.spell_code = 'C')
                AND da.attendance_type = 'R'
            GROUP BY yearmn, da.eb_id
            UNION ALL
            SELECT
                CONCAT(YEAR(da.attendance_date), '-',
                       LPAD(MONTH(da.attendance_date), 2, '0')) AS yearmn,
                da.eb_id,
                CEIL(SUM(da.working_hours - COALESCE(da.idle_hours, 0)) / 8) AS wdays,
                0, 0
            FROM daily_attendance AS da
            INNER JOIN branch_mst AS bm ON bm.branch_id = da.branch_id
            LEFT JOIN spell_mst AS sp ON sp.spell_id = da.spell_id
            WHERE da.is_active = 1 AND bm.co_id = :co_id
                AND (:branch_id IS NULL OR da.branch_id = :branch_id)
                AND da.attendance_date BETWEEN :date_from AND :date_to
                AND COALESCE(da.spell, '') <> 'C' AND COALESCE(sp.spell_code, '') <> 'C'
                AND da.attendance_type = 'R'
            GROUP BY yearmn, da.eb_id
            UNION ALL
            SELECT
                CONCAT(YEAR(ltd.leave_date), '-',
                       LPAD(MONTH(ltd.leave_date), 2, '0')) AS yearmn,
                lt.eb_id, 0, COUNT(*) AS lvdays, 0
            FROM leave_tran_details AS ltd
            INNER JOIN leave_transactions AS lt
                ON lt.leave_transaction_id = ltd.ltran_id
            INNER JOIN branch_mst AS bm ON bm.branch_id = lt.branch_id
            WHERE ltd.is_active = 1 AND lt.status = 3 AND bm.co_id = :co_id
                AND (:branch_id IS NULL OR lt.branch_id = :branch_id)
                AND ltd.leave_date BETWEEN :date_from AND :date_to
            GROUP BY yearmn, lt.eb_id
        ) AS g
        GROUP BY yearmn, eb_id
    ) AS w
    LEFT JOIN hrms_ed_personal_details AS pd ON pd.eb_id = w.eb_id
    LEFT JOIN hrms_ed_official_details AS od ON od.eb_id = w.eb_id AND od.active = 1
    LEFT JOIN sub_dept_mst AS sd ON sd.sub_dept_id = od.sub_dept_id
    LEFT JOIN dept_mst AS dm ON dm.dept_id = sd.dept_id
    LEFT JOIN category_mst AS cm ON cm.cata_id = od.catagory_id
    LEFT JOIN status_mst AS sm ON sm.status_id = pd.status_id
    ORDER BY w.yearmn, od.emp_code, w.eb_id;
    """
    return text(sql)


def get_employee_headcount_query():
    """
    Employee headcount at the finest grain (department, sub-department,
    designation, category) for active employees. Feeds the legacy summary
    reports 505/506/508/509/517 — each frontend page aggregates this grain
    differently (by dept, by category, by designation, dept x category pivot).

    Parameters:
        :co_id (int) - required (scoped via the employee's branch)
        :branch_id (int or NULL) - optional
    """
    sql = """
    SELECT
        dm.dept_desc AS department,
        sd.sub_dept_desc AS sub_department,
        dsg.desig AS designation,
        cm.cata_desc AS category,
        COUNT(*) AS emp_count
    FROM hrms_ed_personal_details AS pd
    INNER JOIN branch_mst AS bm ON bm.branch_id = pd.branch_id
    LEFT JOIN hrms_ed_official_details AS od ON od.eb_id = pd.eb_id AND od.active = 1
    LEFT JOIN sub_dept_mst AS sd ON sd.sub_dept_id = od.sub_dept_id
    LEFT JOIN dept_mst AS dm ON dm.dept_id = sd.dept_id
    LEFT JOIN designation_mst AS dsg ON dsg.designation_id = od.designation_id
    LEFT JOIN category_mst AS cm ON cm.cata_id = od.catagory_id
    WHERE pd.active = 1
        AND bm.co_id = :co_id
        AND (:branch_id IS NULL OR pd.branch_id = :branch_id)
    GROUP BY dm.dept_desc, sd.sub_dept_desc, dsg.desig, cm.cata_desc
    ORDER BY dm.dept_desc, sd.sub_dept_desc, dsg.desig, cm.cata_desc;
    """
    return text(sql)


def get_spell_wise_query():
    """
    Spell-wise hands (legacy report 559): per worked department + designation
    and spell, hands = worked hours / 8. Long format — the frontend pivots
    spells into columns (spell names are tenant data, not fixed).

    Parameters:
        :co_id (int) - required
        :branch_id (int or NULL) - optional
        :date_from, :date_to (str) - required range
    """
    sql = """
    SELECT
        sd.sub_dept_desc AS department,
        dsg.desig AS designation,
        COALESCE(sp.spell_name, da.spell) AS spell,
        ROUND(SUM(da.working_hours - COALESCE(da.idle_hours, 0)) / 8, 2) AS hands
    FROM daily_attendance AS da
    INNER JOIN branch_mst AS bm ON bm.branch_id = da.branch_id
    LEFT JOIN sub_dept_mst AS sd ON sd.sub_dept_id = da.worked_department_id
    LEFT JOIN designation_mst AS dsg ON dsg.designation_id = da.worked_designation_id
    LEFT JOIN spell_mst AS sp ON sp.spell_id = da.spell_id
    WHERE da.attendance_date BETWEEN :date_from AND :date_to
        AND da.is_active = 1
        AND da.status_id = 3
        AND bm.co_id = :co_id
        AND (:branch_id IS NULL OR da.branch_id = :branch_id)
    GROUP BY sd.sub_dept_desc, dsg.desig, COALESCE(sp.spell_name, da.spell)
    ORDER BY sd.sub_dept_desc, dsg.desig, spell;
    """
    return text(sql)


def get_hands_complement_query():
    """
    Hands Complement (second sheet of the legacy Attendance Check List export,
    model Attendance_checklist_Model::directsummReport): per attendance date,
    master department and designation, hands (worked hours / 8) split two ways —
    by shift (A = spells A1/A2, B = B1/B2, C = C) and by employee category.

    Only the seven worker categories the legacy report counted are included
    (catagory_id 14,15,16,17,20,21,22). Filtering by id is deliberate: cata_code
    is NOT unique — 'C' is both PF BADLI (5) and CONTRACT (14), 'A' is both
    PERMANENTS (3) and APPRENTICE (21) — so the id filter is what makes the
    cata_code buckets below unambiguous.

    Note the spell comes from spell_mst: daily_attendance.spell is NULL on the
    migrated tenants, with the real spell carried by spell_id.

    Parameters:
        :co_id (int) - required
        :branch_id (int or NULL) - optional
        :date_from, :date_to (str) - required range
    """
    sql = """
    SELECT
        h.attendance_date,
        dm.dept_desc AS department,
        dsg.desig    AS designation,
        ROUND(SUM(CASE WHEN h.spell_name IN ('A1','A2') THEN h.hands ELSE 0 END), 4) AS shift_a,
        ROUND(SUM(CASE WHEN h.spell_name IN ('B1','B2') THEN h.hands ELSE 0 END), 4) AS shift_b,
        ROUND(SUM(CASE WHEN h.spell_name = 'C'          THEN h.hands ELSE 0 END), 4) AS shift_c,
        ROUND(SUM(h.hands), 4) AS shift_total,
        ROUND(SUM(CASE WHEN cm.cata_code = 'PER' THEN h.hands ELSE 0 END), 4) AS permanent,
        ROUND(SUM(CASE WHEN cm.cata_code = 'BUD' THEN h.hands ELSE 0 END), 4) AS budli,
        ROUND(SUM(CASE WHEN cm.cata_code = 'RTD' THEN h.hands ELSE 0 END), 4) AS retired,
        ROUND(SUM(CASE WHEN cm.cata_code = 'NB'  THEN h.hands ELSE 0 END), 4) AS new_budli,
        ROUND(SUM(CASE WHEN cm.cata_code = 'C'   THEN h.hands ELSE 0 END), 4) AS contract,
        ROUND(SUM(CASE WHEN cm.cata_code = 'O'   THEN h.hands ELSE 0 END), 4) AS outsider,
        ROUND(SUM(CASE WHEN cm.cata_code = 'A'   THEN h.hands ELSE 0 END), 4) AS apprentice,
        ROUND(SUM(h.hands), 4) AS total_hands
    FROM (
        SELECT da.attendance_date, da.eb_id,
               da.worked_department_id, da.worked_designation_id,
               COALESCE(sp.spell_name, da.spell) AS spell_name,
               SUM(da.working_hours - COALESCE(da.idle_hours, 0)) / 8 AS hands
        FROM daily_attendance AS da
        INNER JOIN branch_mst AS bm ON bm.branch_id = da.branch_id
        LEFT JOIN spell_mst AS sp ON sp.spell_id = da.spell_id
        WHERE da.attendance_date BETWEEN :date_from AND :date_to
            AND da.is_active = 1
            AND bm.co_id = :co_id
            AND (:branch_id IS NULL OR da.branch_id = :branch_id)
        GROUP BY da.attendance_date, da.eb_id, da.worked_department_id,
                 da.worked_designation_id, COALESCE(sp.spell_name, da.spell)
    ) AS h
    INNER JOIN hrms_ed_official_details AS od ON od.eb_id = h.eb_id AND od.active = 1
    INNER JOIN sub_dept_mst AS sd ON sd.sub_dept_id = h.worked_department_id
    INNER JOIN dept_mst AS dm ON dm.dept_id = sd.dept_id
    INNER JOIN designation_mst AS dsg ON dsg.designation_id = h.worked_designation_id
    INNER JOIN category_mst AS cm ON cm.cata_id = od.catagory_id
    WHERE od.catagory_id IN (14, 15, 16, 17, 20, 21, 22)
    GROUP BY h.attendance_date, dm.order_id, dm.dept_desc, dsg.desig
    ORDER BY h.attendance_date, dm.order_id, dm.dept_desc, dsg.desig;
    """
    return text(sql)


def get_bank_statement_query():
    """
    Employee bank statement (legacy report 534): per employee net pay for pay
    periods inside the date range, with bank name / account no / IFSC from
    hrms_ed_bank_details. Net comes straight from pay_employee_payperiod.NET
    (the legacy component-21 filter is unnecessary in the new schema). Only
    approved/processed periods (status 3 or 28) — rejected reruns are skipped.

    Parameters:
        :co_id (int) - required
        :branch_id (int or NULL) - optional
        :date_from, :date_to (str) - required range containing the pay periods
    """
    sql = """
    SELECT
        od.emp_code,
        CONCAT(IFNULL(pd.first_name, ''), ' ', IFNULL(pd.middle_name, ''), ' ',
               IFNULL(pd.last_name, '')) AS emp_name,
        bd.bank_name,
        bd.bank_acc_no,
        bd.ifsc_code,
        pp.FROM_DATE AS from_date,
        pp.TO_DATE AS to_date,
        pep.NET AS net_pay
    FROM pay_period AS pp
    INNER JOIN pay_employee_payperiod AS pep ON pep.PAY_PERIOD_ID = pp.ID
    INNER JOIN hrms_ed_personal_details AS pd ON pd.eb_id = pep.EMPLOYEEID
    LEFT JOIN hrms_ed_official_details AS od ON od.eb_id = pd.eb_id AND od.active = 1
    LEFT JOIN hrms_ed_bank_details AS bd ON bd.eb_id = pd.eb_id AND bd.active = 1
    WHERE pp.COMPANY_ID = :co_id
        AND (:branch_id IS NULL OR pp.branch_id = :branch_id)
        AND pp.FROM_DATE >= :date_from
        AND pp.TO_DATE <= :date_to
        AND pp.STATUS IN (3, 28)
    ORDER BY od.emp_code;
    """
    return text(sql)


def get_full_attendance_query():
    """
    Full attendance (legacy report 603): flat daily_attendance detail rows with
    decoded attendance source (Manual/Facial/Logs) and type (Regular/OT/Cash).

    Parameters:
        :co_id (int) - required
        :branch_id (int or NULL) - optional
        :date_from, :date_to (str) - required range
    """
    sql = """
    SELECT
        da.daily_atten_id AS tran_no,
        COALESCE(od.emp_code, da.eb_no, da.eb_code) AS eb_no,
        CONCAT(IFNULL(pd.first_name, ''), ' ', IFNULL(pd.middle_name, ''), ' ',
               IFNULL(pd.last_name, '')) AS emp_name,
        da.attendance_date,
        sd.sub_dept_desc AS department,
        dsg.desig AS designation,
        da.attendance_mark AS mark,
        COALESCE(sp.spell_name, da.spell) AS spell,
        da.idle_hours,
        da.spell_hours,
        da.working_hours,
        CASE WHEN da.attendance_source IN ('A', 'M', 'Manual') THEN 'Manual'
             WHEN da.attendance_source IN ('F', 'Face') THEN 'Facial'
             WHEN da.attendance_source = 'P' THEN 'Logs'
             ELSE COALESCE(da.attendance_source, '') END AS source,
        CASE da.attendance_type WHEN 'R' THEN 'Regular' WHEN 'O' THEN 'OT'
             WHEN 'C' THEN 'Cash' ELSE COALESCE(da.attendance_type, '') END AS att_type,
        sm.status_name,
        da.remarks
    FROM daily_attendance AS da
    INNER JOIN branch_mst AS bm ON bm.branch_id = da.branch_id
    LEFT JOIN hrms_ed_personal_details AS pd ON pd.eb_id = da.eb_id
    LEFT JOIN hrms_ed_official_details AS od ON od.eb_id = da.eb_id AND od.active = 1
    LEFT JOIN sub_dept_mst AS sd ON sd.sub_dept_id = da.worked_department_id
    LEFT JOIN designation_mst AS dsg ON dsg.designation_id = da.worked_designation_id
    LEFT JOIN status_mst AS sm ON sm.status_id = da.status_id
    LEFT JOIN spell_mst AS sp ON sp.spell_id = da.spell_id
    WHERE da.attendance_date BETWEEN :date_from AND :date_to
        AND da.is_active = 1
        AND bm.co_id = :co_id
        AND (:branch_id IS NULL OR da.branch_id = :branch_id)
    ORDER BY da.attendance_date, eb_no;
    """
    return text(sql)


def get_absenteeism_query():
    """
    Absenteeism (legacy report 673): per active employee, the last date they were
    seen (attendance or approved leave day) up to :as_on and the days absent
    since. Only employees absent for at least :min_days are returned. The legacy
    query also counted holidays as "seen" — the tenant has no holiday table.

    Parameters:
        :co_id (int) - required
        :branch_id (int or NULL) - optional (employee's branch)
        :as_on (str) - required as-on date
        :min_days (int) - required minimum days absent (>= 1)
    """
    sql = """
    SELECT
        od.emp_code,
        CONCAT(IFNULL(pd.first_name, ''), ' ', IFNULL(pd.middle_name, ''), ' ',
               IFNULL(pd.last_name, '')) AS emp_name,
        dm.dept_desc AS department,
        cm.cata_desc AS category,
        seen.last_seen,
        DATEDIFF(:as_on, seen.last_seen) AS absent_for
    FROM hrms_ed_personal_details AS pd
    INNER JOIN branch_mst AS bm ON bm.branch_id = pd.branch_id
    LEFT JOIN hrms_ed_official_details AS od ON od.eb_id = pd.eb_id AND od.active = 1
    LEFT JOIN sub_dept_mst AS sd ON sd.sub_dept_id = od.sub_dept_id
    LEFT JOIN dept_mst AS dm ON dm.dept_id = sd.dept_id
    LEFT JOIN category_mst AS cm ON cm.cata_id = od.catagory_id
    INNER JOIN (
        SELECT eb_id, MAX(seen_date) AS last_seen
        FROM (
            SELECT eb_id, attendance_date AS seen_date
            FROM daily_attendance
            WHERE is_active = 1 AND attendance_date <= :as_on
            UNION ALL
            SELECT lt.eb_id, ltd.leave_date
            FROM leave_tran_details AS ltd
            INNER JOIN leave_transactions AS lt
                ON lt.leave_transaction_id = ltd.ltran_id
            WHERE ltd.is_active = 1 AND lt.status = 3 AND ltd.leave_date <= :as_on
        ) AS g
        GROUP BY eb_id
    ) AS seen ON seen.eb_id = pd.eb_id
    WHERE pd.active = 1
        AND bm.co_id = :co_id
        AND (:branch_id IS NULL OR pd.branch_id = :branch_id)
        AND DATEDIFF(:as_on, seen.last_seen) >= :min_days
    ORDER BY dm.dept_desc, od.emp_code;
    """
    return text(sql)


def get_half_day_query():
    """
    Half-day absenteeism (legacy report 687): days where an employee worked only
    the first spell of a shift (A1 without A2, B1 without B2) and the day's total
    working hours are not a full 8 — the legacy half-day detection rule, minus
    the external EMPMILL12.half_day_data feed the tenant does not have. Window
    counts give per-month and range totals per employee.

    Parameters:
        :co_id (int) - required
        :branch_id (int or NULL) - optional
        :date_from, :date_to (str) - required range
    """
    sql = """
    SELECT
        od.emp_code,
        CONCAT(IFNULL(pd.first_name, ''), ' ', IFNULL(pd.middle_name, ''), ' ',
               IFNULL(pd.last_name, '')) AS emp_name,
        dm.dept_desc AS department,
        hd.attendance_date,
        hd.shift,
        hd.day_hours,
        COUNT(*) OVER (PARTITION BY hd.eb_id, YEAR(hd.attendance_date),
                       MONTH(hd.attendance_date)) AS halfdays_month,
        COUNT(*) OVER (PARTITION BY hd.eb_id) AS halfdays_total
    FROM (
        SELECT spl.eb_id, spl.attendance_date, spl.shift, tot.day_hours
        FROM (
            SELECT da.eb_id, da.attendance_date,
                   SUBSTRING(da.spell, 1, 1) AS shift,
                   SUM(CASE WHEN da.spell IN ('A1', 'B1')
                            THEN da.working_hours - COALESCE(da.idle_hours, 0)
                            ELSE 0 END) AS spell1_hours,
                   SUM(CASE WHEN da.spell IN ('A2', 'B2')
                            THEN da.working_hours - COALESCE(da.idle_hours, 0)
                            ELSE 0 END) AS spell2_hours
            FROM daily_attendance AS da
            INNER JOIN branch_mst AS bm ON bm.branch_id = da.branch_id
            WHERE da.attendance_type = 'R' AND da.is_active = 1
                AND da.spell IN ('A1', 'A2', 'B1', 'B2')
                AND da.attendance_date BETWEEN :date_from AND :date_to
                AND bm.co_id = :co_id
                AND (:branch_id IS NULL OR da.branch_id = :branch_id)
            GROUP BY da.eb_id, da.attendance_date, shift
        ) AS spl
        INNER JOIN (
            SELECT da.eb_id, da.attendance_date, SUM(da.working_hours) AS day_hours
            FROM daily_attendance AS da
            WHERE da.attendance_type = 'R' AND da.is_active = 1
                AND da.attendance_date BETWEEN :date_from AND :date_to
            GROUP BY da.eb_id, da.attendance_date
        ) AS tot ON tot.eb_id = spl.eb_id AND tot.attendance_date = spl.attendance_date
        WHERE spl.spell1_hours > 0 AND spl.spell2_hours = 0 AND tot.day_hours <> 8
    ) AS hd
    LEFT JOIN hrms_ed_personal_details AS pd ON pd.eb_id = hd.eb_id
    LEFT JOIN hrms_ed_official_details AS od ON od.eb_id = hd.eb_id AND od.active = 1
    LEFT JOIN sub_dept_mst AS sd ON sd.sub_dept_id = od.sub_dept_id
    LEFT JOIN dept_mst AS dm ON dm.dept_id = sd.dept_id
    ORDER BY od.emp_code, hd.attendance_date;
    """
    return text(sql)


def get_overstay_query():
    """
    Overstay after leave (legacy report 686): approved leaves ending in the date
    range where the employee did not resume the next day — overstay days =
    days between leave end and first attendance after it (or up to today when
    the employee has not rejoined at all). Only overstays of 1+ days.

    ponytail: rejoin lookup is a grouped scan of daily_attendance (no
    (eb_id, attendance_date) index on the big tenants) — ~10s on sls's 1.1M-row
    quarter; add that index if this becomes a hot report.

    Parameters:
        :co_id (int) - required
        :branch_id (int or NULL) - optional
        :date_from, :date_to (str) - required range (leave end dates)
    """
    sql = """
    SELECT * FROM (
        SELECT
            od.emp_code,
            CONCAT(IFNULL(pd.first_name, ''), ' ', IFNULL(pd.middle_name, ''), ' ',
                   IFNULL(pd.last_name, '')) AS emp_name,
            dm.dept_desc AS department,
            cm.cata_desc AS category,
            ltm.leave_type_description AS leave_type,
            l.leave_from_date,
            l.leave_to_date,
            rj.rejoin_date,
            CASE WHEN rj.rejoin_date IS NULL
                 THEN DATEDIFF(CURDATE(), l.leave_to_date) - 1
                 ELSE DATEDIFF(rj.rejoin_date, l.leave_to_date) - 1 END AS overstay_days
        FROM (
            SELECT lt.leave_transaction_id, lt.eb_id, lt.leave_type_id,
                   lt.leave_from_date, lt.leave_to_date
            FROM leave_transactions AS lt
            INNER JOIN branch_mst AS bm ON bm.branch_id = lt.branch_id
            WHERE lt.status = 3
                AND lt.leave_to_date BETWEEN :date_from AND :date_to
                AND bm.co_id = :co_id
                AND (:branch_id IS NULL OR lt.branch_id = :branch_id)
        ) AS l
        LEFT JOIN (
            SELECT l2.leave_transaction_id, MIN(da.attendance_date) AS rejoin_date
            FROM (
                SELECT lt.leave_transaction_id, lt.eb_id, lt.leave_to_date
                FROM leave_transactions AS lt
                INNER JOIN branch_mst AS bm ON bm.branch_id = lt.branch_id
                WHERE lt.status = 3
                    AND lt.leave_to_date BETWEEN :date_from AND :date_to
                    AND bm.co_id = :co_id
                    AND (:branch_id IS NULL OR lt.branch_id = :branch_id)
            ) AS l2
            INNER JOIN daily_attendance AS da
                ON da.eb_id = l2.eb_id
                AND da.attendance_date > l2.leave_to_date
                AND da.is_active = 1
            GROUP BY l2.leave_transaction_id
        ) AS rj ON rj.leave_transaction_id = l.leave_transaction_id
        INNER JOIN hrms_ed_personal_details AS pd ON pd.eb_id = l.eb_id AND pd.active = 1
        LEFT JOIN hrms_ed_official_details AS od ON od.eb_id = l.eb_id AND od.active = 1
        LEFT JOIN sub_dept_mst AS sd ON sd.sub_dept_id = od.sub_dept_id
        LEFT JOIN dept_mst AS dm ON dm.dept_id = sd.dept_id
        LEFT JOIN category_mst AS cm ON cm.cata_id = od.catagory_id
        LEFT JOIN hrms_leave_types_mst AS ltm ON ltm.leave_type_id = l.leave_type_id
    ) AS r
    WHERE r.overstay_days >= 1
    ORDER BY r.leave_to_date, r.emp_code;
    """
    return text(sql)


def get_occupation_deviation_query():
    """
    Occupation deviation (legacy report 601): approved attendance rows where the
    worked department/designation differs from the employee's advised (official)
    department/designation. Rows with no official record are excluded, matching
    the legacy NULL-comparison behaviour.

    Parameters:
        :co_id (int) - required
        :branch_id (int or NULL) - optional
        :date_from, :date_to (str) - required range
    """
    sql = """
    SELECT
        da.daily_atten_id AS tran_no,
        COALESCE(od.emp_code, da.eb_no, da.eb_code) AS eb_no,
        CONCAT(IFNULL(pd.first_name, ''), ' ', IFNULL(pd.middle_name, ''), ' ',
               IFNULL(pd.last_name, '')) AS emp_name,
        da.attendance_date,
        sd_w.sub_dept_desc AS actual_dept,
        dsg_w.desig AS actual_desig,
        sd.sub_dept_desc AS advised_dept,
        dsg_a.desig AS advised_desig,
        COALESCE(sp.spell_name, da.spell) AS spell,
        ROUND(da.working_hours - COALESCE(da.idle_hours, 0), 2) AS work_hours
    FROM daily_attendance AS da
    INNER JOIN branch_mst AS bm ON bm.branch_id = da.branch_id
    LEFT JOIN hrms_ed_personal_details AS pd ON pd.eb_id = da.eb_id
    LEFT JOIN hrms_ed_official_details AS od ON od.eb_id = da.eb_id AND od.active = 1
    LEFT JOIN sub_dept_mst AS sd ON sd.sub_dept_id = od.sub_dept_id
    LEFT JOIN designation_mst AS dsg_a ON dsg_a.designation_id = od.designation_id
    LEFT JOIN sub_dept_mst AS sd_w ON sd_w.sub_dept_id = da.worked_department_id
    LEFT JOIN designation_mst AS dsg_w ON dsg_w.designation_id = da.worked_designation_id
    LEFT JOIN spell_mst AS sp ON sp.spell_id = da.spell_id
    WHERE da.attendance_date BETWEEN :date_from AND :date_to
        AND da.is_active = 1
        AND da.status_id = 3
        AND bm.co_id = :co_id
        AND (:branch_id IS NULL OR da.branch_id = :branch_id)
        -- Both sides are sub-department ids: worked_department_id holds a
        -- sub_dept_id, so comparing it to the master dept_id flagged every row.
        AND (od.sub_dept_id <> da.worked_department_id
             OR od.designation_id <> da.worked_designation_id)
    ORDER BY da.attendance_date, eb_no;
    """
    return text(sql)


def get_cash_attendance_query():
    """
    Cash attendance (legacy report 610 "Cash in Hands"): cash-type attendance
    (attendance_type = 'C') hours per employee, date and spell. The legacy
    report priced hours at worker_master.cash_rate — the tenant schema has no
    cash rate column, so this lists hours only.

    Parameters:
        :co_id (int) - required
        :branch_id (int or NULL) - optional
        :date_from, :date_to (str) - required range
    """
    sql = """
    SELECT
        COALESCE(od.emp_code, da.eb_no, da.eb_code) AS eb_no,
        CONCAT(IFNULL(pd.first_name, ''), ' ', IFNULL(pd.middle_name, ''), ' ',
               IFNULL(pd.last_name, '')) AS emp_name,
        sd.sub_dept_desc AS department,
        dsg.desig AS designation,
        da.attendance_date,
        COALESCE(sp.spell_name, da.spell) AS spell,
        ROUND(SUM(da.working_hours - COALESCE(da.idle_hours, 0)), 2) AS hours
    FROM daily_attendance AS da
    INNER JOIN branch_mst AS bm ON bm.branch_id = da.branch_id
    LEFT JOIN hrms_ed_personal_details AS pd ON pd.eb_id = da.eb_id
    LEFT JOIN hrms_ed_official_details AS od ON od.eb_id = da.eb_id AND od.active = 1
    LEFT JOIN sub_dept_mst AS sd ON sd.sub_dept_id = da.worked_department_id
    LEFT JOIN designation_mst AS dsg ON dsg.designation_id = da.worked_designation_id
    LEFT JOIN spell_mst AS sp ON sp.spell_id = da.spell_id
    WHERE da.attendance_type = 'C'
        AND da.is_active = 1
        AND da.attendance_date BETWEEN :date_from AND :date_to
        AND bm.co_id = :co_id
        AND (:branch_id IS NULL OR da.branch_id = :branch_id)
    GROUP BY da.eb_id, COALESCE(od.emp_code, da.eb_no, da.eb_code),
             CONCAT(IFNULL(pd.first_name, ''), ' ', IFNULL(pd.middle_name, ''), ' ',
                    IFNULL(pd.last_name, '')),
             sd.sub_dept_desc, dsg.desig, da.attendance_date,
             COALESCE(sp.spell_name, da.spell)
    ORDER BY da.attendance_date, sd.sub_dept_desc, eb_no;
    """
    return text(sql)


def get_employee_face_query():
    """
    Employee face register (employee_face_mst) with the employee resolved to
    emp_code / name / department via hrms_ed_official_details. The embedding
    and photo blobs come back as presence flags only (they are 3-120 KB each).

    Parameters:
        :co_id (int) - required (scoped via the employee's branch)
        :branch_id (int or NULL) - optional
        :active (int or NULL) - optional employee_face_mst.active filter (0/1)
    """
    sql = """
    SELECT
        ef.emp_face_id,
        ef.eb_id,
        od.emp_code,
        CONCAT_WS(' ', pd.first_name, NULLIF(pd.middle_name, ''), NULLIF(pd.last_name, '')) AS emp_name,
        dm.dept_desc,
        sd.sub_dept_desc,
        ef.active,
        (ef.face_embedding IS NOT NULL AND ef.face_embedding <> '') AS has_face,
        (ef.face_embedding_mobile IS NOT NULL AND ef.face_embedding_mobile <> '') AS has_mobile_face,
        (ef.photo_html IS NOT NULL AND ef.photo_html <> '') AS has_photo,
        ef.mobile_model_ver,
        ef.mobile_embed_updated,
        ef.updated_by,
        ef.updated_date_time
    FROM employee_face_mst AS ef
    INNER JOIN hrms_ed_personal_details AS pd ON pd.eb_id = ef.eb_id
    INNER JOIN branch_mst AS bm ON bm.branch_id = pd.branch_id
    LEFT JOIN hrms_ed_official_details AS od
        ON od.eb_id = pd.eb_id AND od.active = 1
    LEFT JOIN sub_dept_mst AS sd ON sd.sub_dept_id = od.sub_dept_id
    LEFT JOIN dept_mst AS dm ON dm.dept_id = sd.dept_id
    WHERE bm.co_id = :co_id
        AND (:branch_id IS NULL OR pd.branch_id = :branch_id)
        AND (:active IS NULL OR ef.active = :active)
    ORDER BY ef.updated_date_time DESC, ef.emp_face_id DESC;
    """
    return text(sql)


def get_employee_face_photo_query():
    """
    One employee_face_mst.photo_html (base64 image) by emp_face_id, scoped to
    the company via the employee's branch.

    Parameters:
        :emp_face_id (int) - required
        :co_id (int) - required
    """
    sql = """
    SELECT ef.photo_html
    FROM employee_face_mst AS ef
    INNER JOIN hrms_ed_personal_details AS pd ON pd.eb_id = ef.eb_id
    INNER JOIN branch_mst AS bm ON bm.branch_id = pd.branch_id
    WHERE ef.emp_face_id = :emp_face_id
        AND bm.co_id = :co_id
    LIMIT 1;
    """
    return text(sql)
