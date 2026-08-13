"""SQL queries for HRMS employee and pay scheme endpoints."""
from sqlalchemy import text


# ─── Employee queries ───────────────────────────────────────────────

def get_employee_list(branch_ids=None):
    branch_filter = "p.branch_id = :branch_id"
    if branch_ids:
        placeholders = ",".join(str(int(b)) for b in branch_ids)
        branch_filter = f"p.branch_id IN ({placeholders})"
    return text(f"""
        SELECT
            p.eb_id,
            p.first_name,
            p.middle_name,
            p.last_name,
            CONCAT(p.first_name, ' ', COALESCE(p.middle_name, ''), ' ', COALESCE(p.last_name, '')) AS full_name,
            p.email_id,
            p.gender,
            p.date_of_birth,
            p.pan_no,
            p.aadhar_no,
            p.mobile_no,
            p.status_id,
            s.status_name,
            p.active,
            o.emp_code,
            o.date_of_join,
            o.sub_dept_id,
            o.designation_id,
            o.branch_id,
            CONCAT(sd.sub_dept_desc, ' (', COALESCE(d.dept_desc, ''), ')') AS sub_dept_name,
            des.desig AS designation_name,
            b.branch_name,
            cat.cata_desc AS category_name,
            esi.esi_no,
            pf.pf_uan_no,
            COALESCE(p.mobile_no, c.mobile_no) AS mobile_no
        FROM hrms_ed_personal_details p
        LEFT JOIN hrms_ed_official_details o ON o.eb_id = p.eb_id AND o.active = 1
        LEFT JOIN sub_dept_mst sd ON sd.sub_dept_id = o.sub_dept_id
        LEFT JOIN dept_mst d ON d.dept_id = sd.dept_id
        LEFT JOIN designation_mst des ON des.designation_id = o.designation_id
        LEFT JOIN branch_mst b ON b.branch_id = o.branch_id
        LEFT JOIN category_mst cat ON cat.cata_id = o.catagory_id
        LEFT JOIN hrms_ed_esi esi ON esi.eb_id = p.eb_id AND esi.active = 1
        LEFT JOIN hrms_ed_pf pf ON pf.eb_id = p.eb_id AND pf.active = 1
        LEFT JOIN hrms_ed_contact_details c ON c.eb_id = p.eb_id AND c.active = 1
        LEFT JOIN status_mst s ON s.status_id = p.status_id
        WHERE {branch_filter}
          AND (:search IS NULL OR p.first_name LIKE :search
               OR p.last_name LIKE :search
               OR o.emp_code LIKE :search
               OR p.email_id LIKE :search)
          AND (:status_id IS NULL OR p.status_id = :status_id)
          AND (:sub_dept_id IS NULL OR o.sub_dept_id = :sub_dept_id)
          AND (:is_active IS NULL OR p.active = :is_active)
          AND (:cata_id IS NULL OR o.catagory_id = :cata_id)
          AND (:f_emp_code IS NULL OR o.emp_code LIKE :f_emp_code)
          AND (:f_full_name IS NULL OR CONCAT(p.first_name, ' ', COALESCE(p.middle_name, ''), ' ', COALESCE(p.last_name, '')) LIKE :f_full_name)
          AND (:f_designation IS NULL OR des.desig LIKE :f_designation)
          AND (:f_mobile IS NULL OR COALESCE(p.mobile_no, c.mobile_no) LIKE :f_mobile)
          AND (:f_esi_no IS NULL OR esi.esi_no LIKE :f_esi_no)
          AND (:f_uan_no IS NULL OR pf.pf_uan_no LIKE :f_uan_no)
        ORDER BY p.eb_id DESC
        LIMIT :page_size OFFSET :offset
    """)


def get_employee_list_count(branch_ids=None):
    branch_filter = "p.branch_id = :branch_id"
    if branch_ids:
        placeholders = ",".join(str(int(b)) for b in branch_ids)
        branch_filter = f"p.branch_id IN ({placeholders})"
    return text(f"""
        SELECT COUNT(*) AS total
        FROM hrms_ed_personal_details p
        LEFT JOIN hrms_ed_official_details o ON o.eb_id = p.eb_id AND o.active = 1
        LEFT JOIN designation_mst des ON des.designation_id = o.designation_id
        LEFT JOIN hrms_ed_esi esi ON esi.eb_id = p.eb_id AND esi.active = 1
        LEFT JOIN hrms_ed_pf pf ON pf.eb_id = p.eb_id AND pf.active = 1
        LEFT JOIN hrms_ed_contact_details c ON c.eb_id = p.eb_id AND c.active = 1
        WHERE {branch_filter}
          AND (:search IS NULL OR p.first_name LIKE :search
               OR p.last_name LIKE :search
               OR o.emp_code LIKE :search
               OR p.email_id LIKE :search)
          AND (:status_id IS NULL OR p.status_id = :status_id)
          AND (:sub_dept_id IS NULL OR o.sub_dept_id = :sub_dept_id)
          AND (:is_active IS NULL OR p.active = :is_active)
          AND (:cata_id IS NULL OR o.catagory_id = :cata_id)
          AND (:f_emp_code IS NULL OR o.emp_code LIKE :f_emp_code)
          AND (:f_full_name IS NULL OR CONCAT(p.first_name, ' ', COALESCE(p.middle_name, ''), ' ', COALESCE(p.last_name, '')) LIKE :f_full_name)
          AND (:f_designation IS NULL OR des.desig LIKE :f_designation)
          AND (:f_mobile IS NULL OR COALESCE(p.mobile_no, c.mobile_no) LIKE :f_mobile)
          AND (:f_esi_no IS NULL OR esi.esi_no LIKE :f_esi_no)
          AND (:f_uan_no IS NULL OR pf.pf_uan_no LIKE :f_uan_no)
    """)


def get_employee_personal_by_id():
    return text("""
        SELECT p.eb_id, p.first_name, p.middle_name, p.last_name, p.gender,
               p.date_of_birth, p.blood_group, p.mobile_no, p.email_id,
               p.marital_status, p.country_id, p.relegion_name, p.fixed_eb_id,
               p.father_spouse_name, p.passport_no, p.driving_licence_no,
               p.pan_no, p.aadhar_no, p.voter_card_no, p.branch_id, p.updated_by, p.updated_date_time,
               p.active, p.status_id,
               CASE WHEN f.face_image IS NOT NULL THEN 1 ELSE 0 END AS has_photo
        FROM hrms_ed_personal_details p
        LEFT JOIN hrms_employee_face f ON f.eb_id = p.eb_id
        WHERE p.eb_id = :eb_id AND p.branch_id = :branch_id AND p.active = 1
    """)


def get_employee_contact_by_eb_id():
    return text("""
        SELECT * FROM hrms_ed_contact_details
        WHERE eb_id = :eb_id AND active = 1
    """)


def get_employee_address_by_eb_id():
    return text("""
        SELECT * FROM hrms_ed_address_details
        WHERE eb_id = :eb_id AND active = 1
    """)


def get_employee_official_by_eb_id():
    return text("""
        SELECT o.*,
               CONCAT(sd.sub_dept_desc, ' (', COALESCE(d.dept_desc, ''), ')') AS sub_dept_name,
               des.desig AS designation_name,
               b.branch_name,
               CONCAT(rp.first_name, ' ', COALESCE(rp.last_name, '')) AS reporting_to_name
        FROM hrms_ed_official_details o
        LEFT JOIN sub_dept_mst sd ON sd.sub_dept_id = o.sub_dept_id
        LEFT JOIN dept_mst d ON d.dept_id = sd.dept_id
        LEFT JOIN designation_mst des ON des.designation_id = o.designation_id
        LEFT JOIN branch_mst b ON b.branch_id = o.branch_id
        LEFT JOIN hrms_ed_personal_details rp ON rp.eb_id = o.reporting_eb_id
        WHERE o.eb_id = :eb_id AND o.active = 1
    """)


def get_employee_bank_by_eb_id():
    return text("""
        SELECT * FROM hrms_ed_bank_details
        WHERE eb_id = :eb_id AND active = 1
    """)


def get_employee_pf_by_eb_id():
    return text("""
        SELECT * FROM hrms_ed_pf
        WHERE eb_id = :eb_id AND active = 1
    """)


def get_employee_esi_by_eb_id():
    return text("""
        SELECT * FROM hrms_ed_esi
        WHERE eb_id = :eb_id AND active = 1
    """)


def get_employee_experience_by_eb_id():
    return text("""
        SELECT * FROM hrms_experience_details
        WHERE eb_id = :eb_id AND active = 1
    """)


def get_employee_resign_by_eb_id():
    return text("""
        SELECT * FROM hrms_ed_resign_details
        WHERE eb_id = :eb_id AND active = 1
    """)


def get_employee_create_setup():
    """Fetches all dropdown master data needed for employee creation (except designations which depend on branch).

    :branch_id is a comma-separated branch id list (matches the portal sidebar's multi-branch selection).
    """
    return text("""
        SELECT 'blood_groups' AS source, blood_group_id AS id, blood_group_name AS name FROM hrms_blood_group
        UNION ALL
        SELECT 'sub_departments', sd.sub_dept_id, CONCAT(sd.sub_dept_desc, ' (', COALESCE(d.dept_desc, ''), ')') FROM sub_dept_mst sd LEFT JOIN dept_mst d ON d.dept_id = sd.dept_id WHERE (:branch_id IS NULL OR FIND_IN_SET(d.branch_id, :branch_id))
        UNION ALL
        SELECT 'branches', branch_id, branch_name FROM branch_mst WHERE co_id = :co_id AND active = 1
        UNION ALL
        SELECT 'categories', cata_id, cata_desc FROM category_mst WHERE (:branch_id IS NULL OR FIND_IN_SET(branch_id, :branch_id))
        UNION ALL
        SELECT 'contractors', cont_id, contractor_name FROM contractor_mst WHERE (:branch_id IS NULL OR FIND_IN_SET(branch_id, :branch_id))
    """)


def get_designations_by_branch():
    """Fetches designations filtered by branch_id."""
    return text("""
        SELECT designation_id, desig
        FROM designation_mst
        WHERE branch_id = :branch_id AND active = 1
        ORDER BY desig
    """)


def get_designations_by_sub_dept():
    """Fetches designations by sub_dept_id -> dept_id lookup."""
    return text("""
        SELECT d.designation_id, d.desig
        FROM designation_mst d
        INNER JOIN sub_dept_mst sd ON sd.dept_id = d.dept_id
        WHERE sd.sub_dept_id = :sub_dept_id AND d.active = 1
        ORDER BY d.desig
    """)


def get_reporting_employees():
    return text("""
        SELECT p.eb_id AS id,
               CONCAT(p.first_name, ' ', COALESCE(p.last_name, '')) AS name,
               o.emp_code
        FROM hrms_ed_personal_details p
        LEFT JOIN hrms_ed_official_details o ON o.eb_id = p.eb_id AND o.active = 1
        WHERE FIND_IN_SET(p.branch_id, :branch_id) AND p.active = 1 AND p.status_id != 6
        ORDER BY p.first_name
    """)


def get_employee_by_emp_code():
    """Look up an existing employee by emp_code in official details. Returns full data for pre-fill."""
    return text("""
        SELECT o.eb_id, o.emp_code,
               p.first_name, p.middle_name, p.last_name, p.gender,
               p.date_of_birth, p.blood_group, p.mobile_no, p.email_id,
               p.marital_status, p.country_id, p.relegion_name,
               p.father_spouse_name, p.passport_no, p.driving_licence_no,
               p.pan_no, p.aadhar_no, p.voter_card_no
        FROM hrms_ed_official_details o
        JOIN hrms_ed_personal_details p ON p.eb_id = o.eb_id AND p.active = 1
        WHERE o.emp_code = :emp_code AND o.active = 1
        LIMIT 1
    """)


def check_emp_code_duplicate():
    """Check if emp_code already exists within a branch. Optionally exclude a specific eb_id (for edit mode)."""
    return text("""
        SELECT COUNT(*) AS cnt
        FROM hrms_ed_official_details
        WHERE emp_code = :emp_code AND active = 1
          AND branch_id = :branch_id
          AND (:exclude_eb_id IS NULL OR eb_id != :exclude_eb_id)
    """)


# ─── Pay Scheme queries (pay_scheme_master / pay_scheme_details) ───

def get_pay_scheme_master_list():
    return text("""
        SELECT
            ps.payscheme_id,
            ps.co_id,
            ps.payscheme_code,
            ps.payscheme_name,
            ps.record_status,
            ps.wage_type,
            ps.branch_id,
            ps.effective_from,
            ps.updated_by,
            ps.updated_date_time,
            wm.NAME AS wage_type_name,
            CASE ps.record_status
                WHEN 1 THEN 'Active'
                WHEN 32 THEN 'Locked'
                WHEN 0 THEN 'Deactivated'
                ELSE 'Draft'
            END AS status_desc
        FROM pay_scheme_master ps
        LEFT JOIN pay_wages_mode wm ON wm.ID = ps.wage_type
        WHERE (:co_id IS NULL OR ps.co_id = :co_id)
          AND (:search IS NULL OR ps.payscheme_name LIKE :search OR ps.payscheme_code LIKE :search)
        ORDER BY ps.payscheme_id DESC
        LIMIT :page_size OFFSET :offset
    """)


def get_pay_scheme_master_count():
    return text("""
        SELECT COUNT(*) AS total
        FROM pay_scheme_master ps
        WHERE (:co_id IS NULL OR ps.co_id = :co_id)
          AND (:search IS NULL OR ps.payscheme_name LIKE :search OR ps.payscheme_code LIKE :search)
    """)


def get_pay_scheme_master_by_id():
    return text("""
        SELECT
            ps.payscheme_id,
            ps.co_id,
            ps.payscheme_code,
            ps.payscheme_name,
            ps.record_status,
            ps.wage_type,
            ps.branch_id,
            ps.effective_from,
            ps.updated_by,
            ps.updated_date_time,
            wm.NAME AS wage_type_name
        FROM pay_scheme_master ps
        LEFT JOIN pay_wages_mode wm ON wm.ID = ps.wage_type
        WHERE ps.payscheme_id = :payscheme_id
    """)


def get_pay_scheme_details_by_scheme_id():
    return text("""
        SELECT
            d.ID AS id,
            d.COMPONENT_ID AS component_id,
            d.FORMULA AS formula,
            d.PAY_SCHEME_ID AS pay_scheme_id,
            d.TYPE AS type,
            d.STATUS AS status,
            d.DEFAULT_VALUE AS default_value,
            pc.NAME AS component_name,
            pc.CODE AS component_code,
            pc.ROUNDOF AS roundof,
            pc.ROUNDOF_TYPE AS roundof_type
        FROM pay_scheme_details d
        LEFT JOIN pay_components pc ON pc.ID = d.COMPONENT_ID
        WHERE d.PAY_SCHEME_ID = :payscheme_id
          AND (d.STATUS IS NULL OR d.STATUS = 1)
        ORDER BY d.TYPE, d.ID
    """)


def get_pay_scheme_dropdown():
    """Pay schemes for clone dropdown."""
    return text("""
        SELECT
            ps.payscheme_id,
            ps.payscheme_code,
            ps.payscheme_name,
            ps.co_id
        FROM pay_scheme_master ps
        WHERE (:co_id IS NULL OR ps.co_id = :co_id)
          AND ps.record_status IN (1, 32)
        ORDER BY ps.payscheme_name
    """)


def get_wage_type_list():
    """Pay wages modes list."""
    return text("""
        SELECT
            ID AS id,
            CODE AS code,
            NAME AS name,
            DESCRIPTION AS description
        FROM pay_wages_mode
        WHERE STATUS = 1 OR STATUS IS NULL
        ORDER BY NAME
    """)


def get_pay_components_for_scheme():
    """All active pay components for adding items to a scheme."""
    return text("""
        SELECT
            pc.ID AS id,
            pc.CODE AS code,
            pc.NAME AS name,
            pc.TYPE AS type,
            pc.DEFAULT_VALUE AS default_value,
            pc.ROUNDOF AS roundof,
            pc.ROUNDOF_TYPE AS roundof_type,
            CASE pc.TYPE
                WHEN 0 THEN 'No Calculation'
                WHEN 1 THEN 'Earning'
                WHEN 2 THEN 'Deduction'
                WHEN 3 THEN 'Summary'
                ELSE 'Unknown'
            END AS type_label
        FROM pay_components pc
        WHERE pc.STATUS IN (1, 3)
        ORDER BY pc.TYPE, pc.NAME
    """)


def get_co_mst_list():
    """Simple company list from co_mst."""
    return text("""
        SELECT co_id, co_name
        FROM co_mst
        ORDER BY co_name
    """)


def get_pay_scheme_create_setup():
    """Setup data for creating pay scheme — components by type."""
    return text("""
        SELECT
            pc.ID AS id,
            pc.CODE AS code,
            pc.NAME AS name,
            pc.TYPE AS type,
            pc.DEFAULT_VALUE AS default_value,
            pc.IS_CUSTOM_COMPONENT AS is_custom_component
        FROM pay_components pc
        WHERE (:co_id IS NULL OR pc.company_id = :co_id)
          AND pc.STATUS IN (1, 3)
        ORDER BY pc.TYPE, pc.NAME
    """)


# ─── Pay Component (pay_components CRUD) queries ───────────────────

def get_pay_component_list():
    return text("""
        SELECT
            pc.ID AS id,
            pc.CODE AS code,
            pc.NAME AS name,
            pc.DESCRIPTION AS description,
            pc.TYPE AS type,
            CASE pc.TYPE
                WHEN 0 THEN 'No Calculation'
                WHEN 1 THEN 'Earning'
                WHEN 2 THEN 'Deduction'
                WHEN 3 THEN 'Summary'
                ELSE 'Unknown'
            END AS type_label,
            pc.EFFECTIVE_FROM AS effective_from,
            pc.ENDS_ON AS ends_on,
            pc.DEFAULT_VALUE AS default_value,
            pc.PARENT_ID AS parent_id,
            p.NAME AS parent_name,
            pc.IS_CUSTOM_COMPONENT AS is_custom_component,
            pc.IS_DISPLAYABLE_IN_PAYSLIP AS is_displayable_in_payslip,
            pc.IS_OCCASIONALLY AS is_occasionally,
            pc.IS_EXCEL_DOWNLOADABLE AS is_excel_downloadable,
            pc.ROUNDOF AS roundof,
            pc.ROUNDOF_TYPE AS roundof_type,
            pc.STATUS AS status_id
        FROM pay_components pc
        LEFT JOIN pay_components p ON p.ID = pc.PARENT_ID
        WHERE (:co_id IS NULL OR pc.company_id = :co_id)
          AND (:type IS NULL OR pc.TYPE = :type)
          AND (:search IS NULL OR pc.NAME LIKE :search OR pc.CODE LIKE :search)
        ORDER BY pc.TYPE, pc.NAME
        LIMIT :page_size OFFSET :offset
    """)


def get_pay_component_count():
    return text("""
        SELECT COUNT(*) AS total
        FROM pay_components pc
        WHERE (:co_id IS NULL OR pc.company_id = :co_id)
          AND (:type IS NULL OR pc.TYPE = :type)
          AND (:search IS NULL OR pc.NAME LIKE :search OR pc.CODE LIKE :search)
    """)


def get_pay_component_by_id():
    return text("""
        SELECT
            pc.ID AS id,
            pc.CODE AS code,
            pc.NAME AS name,
            pc.DESCRIPTION AS description,
            pc.TYPE AS type,
            pc.EFFECTIVE_FROM AS effective_from,
            pc.ENDS_ON AS ends_on,
            pc.DEFAULT_VALUE AS default_value,
            pc.PARENT_ID AS parent_id,
            pc.IS_CUSTOM_COMPONENT AS is_custom_component,
            pc.IS_DISPLAYABLE_IN_PAYSLIP AS is_displayable_in_payslip,
            pc.IS_OCCASIONALLY AS is_occasionally,
            pc.IS_EXCEL_DOWNLOADABLE AS is_excel_downloadable,
            pc.ROUNDOF AS roundof,
            pc.ROUNDOF_TYPE AS roundof_type,
            pc.IS_COMMULATIVE AS is_commulative,
            pc.cumulative_component_id,
            pc.cumulative_period_from,
            pc.cumulative_period_to,
            pc.STATUS AS status_id
        FROM pay_components pc
        WHERE pc.ID = :id AND (:co_id IS NULL OR pc.company_id = :co_id)
    """)


# ─── Pay Param (pay period) queries ────────────────────────────────

def get_pay_param_list():
    return text("""
        SELECT
            pp.ID AS id,
            pp.FROM_DATE AS from_date,
            pp.TO_DATE AS to_date,
            pp.PAYSCHEME_ID AS payscheme_id,
            pp.STATUS AS status_id,
            s.status_name,
            pp.branch_id,
            ps.NAME AS scheme_name,
            b.branch_name
        FROM pay_period pp
        LEFT JOIN pay_components ps ON ps.ID = pp.PAYSCHEME_ID
        LEFT JOIN branch_mst b ON b.branch_id = pp.branch_id
        LEFT JOIN status_mst s ON s.status_id = pp.STATUS
        WHERE ps.company_id = :co_id
          AND (:search IS NULL OR ps.NAME LIKE :search)
        ORDER BY pp.ID DESC
        LIMIT :page_size OFFSET :offset
    """)


# ─── Pay Register queries ───────────────────────────────────────────

def get_pay_register_list():
    # Keys are camelCase to match the frontend grid (PayRegisterListRow). Pay
    # schemes live in pay_scheme_master (NOT pay_components); wage_type and the
    # net-pay total come from there / pay_employee_payperiod.
    return text("""
        SELECT
            pp.ID AS id,
            psm.payscheme_name AS payscheme,
            pp.PAYSCHEME_ID AS paySchemeId,
            DATE_FORMAT(pp.FROM_DATE, '%d-%m-%Y') AS fromDateDesc,
            DATE_FORMAT(pp.TO_DATE, '%d-%m-%Y') AS toDateDesc,
            CASE psm.wage_type
                WHEN 1 THEN 'Daily'
                WHEN 2 THEN 'Weekly'
                WHEN 3 THEN 'Fortnight'
                WHEN 4 THEN 'Monthly'
                ELSE NULL
            END AS wageType,
            (SELECT SUM(epp.NET)
               FROM pay_employee_payperiod epp
              WHERE epp.PAY_PERIOD_ID = pp.ID
                AND epp.PAY_SCHEME_ID = pp.PAYSCHEME_ID) AS netPay,
            s.status_name AS status,
            pp.STATUS AS status_id,
            u.name AS createdBy,
            pp.branch_id AS branchId,
            pp.COMPANY_ID AS companyId
        FROM pay_period pp
        LEFT JOIN pay_scheme_master psm ON psm.payscheme_id = pp.PAYSCHEME_ID
        LEFT JOIN branch_mst b ON b.branch_id = pp.branch_id
        LEFT JOIN status_mst s ON s.status_id = pp.STATUS
        LEFT JOIN user_mst u ON u.user_id = pp.updated_by
        WHERE pp.COMPANY_ID = :co_id
          AND (:search IS NULL OR psm.payscheme_name LIKE :search)
          AND (:from_date IS NULL OR pp.FROM_DATE >= :from_date)
          AND (:to_date IS NULL OR pp.TO_DATE <= :to_date)
          AND (:status_id IS NULL OR pp.STATUS = :status_id)
        ORDER BY pp.ID DESC
        LIMIT :page_size OFFSET :offset
    """)


def get_pay_register_list_count():
    return text("""
        SELECT COUNT(*) AS total
        FROM pay_period pp
        LEFT JOIN pay_scheme_master psm ON psm.payscheme_id = pp.PAYSCHEME_ID
        WHERE pp.COMPANY_ID = :co_id
          AND (:search IS NULL OR psm.payscheme_name LIKE :search)
          AND (:from_date IS NULL OR pp.FROM_DATE >= :from_date)
          AND (:to_date IS NULL OR pp.TO_DATE <= :to_date)
          AND (:status_id IS NULL OR pp.STATUS = :status_id)
    """)


def get_pay_register_by_id():
    # camelCase keys to match the frontend PayRegisterDetail; scheme name from
    # pay_scheme_master (NOT pay_components).
    return text("""
        SELECT
            pp.ID AS id,
            pp.FROM_DATE AS fromDate,
            pp.TO_DATE AS toDate,
            DATE_FORMAT(pp.FROM_DATE, '%d-%m-%Y') AS fromDateDesc,
            DATE_FORMAT(pp.TO_DATE, '%d-%m-%Y') AS toDateDesc,
            pp.PAYSCHEME_ID AS paySchemeId,
            psm.payscheme_name AS payscheme,
            psm.payscheme_code AS paySchemeCode,
            pp.STATUS AS status_id,
            s.status_name AS status,
            pp.branch_id AS branchId,
            b.branch_name AS branchName,
            pp.COMPANY_ID AS companyId
        FROM pay_period pp
        LEFT JOIN pay_scheme_master psm ON psm.payscheme_id = pp.PAYSCHEME_ID
        LEFT JOIN branch_mst b ON b.branch_id = pp.branch_id
        LEFT JOIN status_mst s ON s.status_id = pp.STATUS
        WHERE pp.ID = :id AND pp.COMPANY_ID = :co_id
    """)


def check_duplicate_pay_register():
    return text("""
        SELECT COUNT(*) AS cnt
        FROM pay_period
        WHERE FROM_DATE = :from_date
          AND TO_DATE = :to_date
          AND PAYSCHEME_ID = :payscheme_id
          AND COMPANY_ID = :co_id
          AND STATUS NOT IN (4, 6, 28)
    """)


def get_pay_register_salary():
    """Monthly salary payment data — builds per-employee rows with component columns."""
    return text("""
        SELECT
            ep.EMPLOYEEID AS employee_id,
            o.emp_code AS emp_code,
            CONCAT(p.first_name, ' ', COALESCE(p.middle_name, ''), ' ', COALESCE(p.last_name, '')) AS emp_name,
            COALESCE(sd.sub_dept_desc, '') AS department_name,
            pc.ID AS component_id,
            pc.NAME AS component_name,
            pc.TYPE AS component_type,
            COALESCE(ep.AMOUNT, 0) AS amount
        FROM pay_employee_payperiod epp
        JOIN pay_employee_payroll ep
            ON ep.EMPLOYEEID = epp.EMPLOYEEID
           AND ep.PAYPERIOD_ID = epp.PAY_PERIOD_ID
           AND ep.PAYSCHEME_ID = epp.PAY_SCHEME_ID
        JOIN pay_components pc ON pc.ID = ep.COMPONENT_ID
        JOIN hrms_ed_personal_details p ON p.eb_id = ep.EMPLOYEEID
        LEFT JOIN hrms_ed_official_details o ON o.eb_id = ep.EMPLOYEEID AND o.active = 1
        LEFT JOIN sub_dept_mst sd ON sd.sub_dept_id = o.sub_dept_id
        WHERE epp.PAY_PERIOD_ID = :pay_period_id
          AND epp.PAY_SCHEME_ID = :pay_scheme_id
          AND (:branch_id IS NULL OR ep.BUSINESSUNIT_ID = :branch_id)
        ORDER BY p.first_name, pc.TYPE, pc.ID
    """)


# ─── Pay Register Export / Payslip Print queries ───────────────────


def get_payslip_print_components():
    """Configured payslip/export columns for a payscheme + company + branch.

    Drives BOTH the Excel export columns and the payslip PDF lines. When this
    returns no rows the caller falls back to all of the pay scheme's components
    (get_pay_scheme_details_by_scheme_id). Only call this with a non-NULL
    branch_id — the table's branch_id is NOT NULL, so a NULL period branch can
    never match and should go straight to the fallback.
    """
    return text("""
        SELECT
            component_id,
            desc_print,
            payslip_order,
            fixed_var_cols,
            total_print,
            payslip_print
        FROM tbl_payslip_print_component
        WHERE payscheme_id = :payscheme_id
          AND company_id = :company_id
          AND branch_id = :branch_id
          AND is_active = 1
        ORDER BY payslip_order, pay_id
    """)


def get_employee_pf_map():
    """PF number + UAN for a set of employees (active PF rows only).

    Drives the meta columns PF No (-4) and UAN No (-5) on the pay register /
    export / payslip. :eb_ids is a CSV of employee eb_ids (FIND_IN_SET).
    """
    return text("""
        SELECT eb_id, pf_no, pf_uan_no
        FROM hrms_ed_pf
        WHERE active = 1
          AND FIND_IN_SET(eb_id, :eb_ids)
    """)


def get_employee_esi_map():
    """ESI number for a set of employees (active ESI rows only).

    Drives the meta column ESI No (-6). :eb_ids is a CSV of employee eb_ids.
    """
    return text("""
        SELECT eb_id, esi_no
        FROM hrms_ed_esi
        WHERE active = 1
          AND FIND_IN_SET(eb_id, :eb_ids)
    """)


def get_company_name():
    """Company display name for export / payslip headers."""
    return text("""
        SELECT co_name
        FROM co_mst
        WHERE co_id = :co_id
    """)


# ─── Payslip Print Component config (tbl_payslip_print_component) ────


def list_payslip_print_components():
    """Configured payslip/export columns, joined to scheme/component/branch names.

    Filters: company (required), optional branch CSV (FIND_IN_SET), optional
    payscheme, optional search on component name/print label. Paginated.
    """
    return text("""
        SELECT
            t.pay_id,
            t.payscheme_id,
            t.company_id,
            t.branch_id,
            t.component_id,
            t.desc_print,
            t.payslip_order,
            t.fixed_var_cols,
            t.total_print,
            t.payslip_print,
            t.is_active,
            ps.payscheme_name,
            ps.payscheme_code,
            pc.NAME AS component_name,
            pc.CODE AS component_code,
            b.branch_name
        FROM tbl_payslip_print_component t
        LEFT JOIN pay_scheme_master ps ON ps.payscheme_id = t.payscheme_id
        LEFT JOIN pay_components pc ON pc.ID = t.component_id
        LEFT JOIN branch_mst b ON b.branch_id = t.branch_id
        WHERE t.company_id = :company_id
          AND (:branch_ids IS NULL OR FIND_IN_SET(t.branch_id, :branch_ids))
          AND (:payscheme_id IS NULL OR t.payscheme_id = :payscheme_id)
          AND (:search IS NULL OR pc.NAME LIKE :search OR t.desc_print LIKE :search)
        ORDER BY t.payscheme_id, t.payslip_order, t.pay_id
        LIMIT :page_size OFFSET :offset
    """)


def count_payslip_print_components():
    return text("""
        SELECT COUNT(*) AS total
        FROM tbl_payslip_print_component t
        LEFT JOIN pay_components pc ON pc.ID = t.component_id
        WHERE t.company_id = :company_id
          AND (:branch_ids IS NULL OR FIND_IN_SET(t.branch_id, :branch_ids))
          AND (:payscheme_id IS NULL OR t.payscheme_id = :payscheme_id)
          AND (:search IS NULL OR pc.NAME LIKE :search OR t.desc_print LIKE :search)
    """)


def get_payslip_print_component_by_id():
    return text("""
        SELECT
            t.pay_id,
            t.payscheme_id,
            t.company_id,
            t.branch_id,
            t.component_id,
            t.desc_print,
            t.payslip_order,
            t.fixed_var_cols,
            t.total_print,
            t.payslip_print,
            t.is_active
        FROM tbl_payslip_print_component t
        WHERE t.pay_id = :pay_id
          AND t.company_id = :company_id
    """)


def check_payslip_print_component_duplicate():
    """Existing ACTIVE row for the same scheme+company+branch+component.

    Pass :exclude_pay_id = the row being edited (or 0 on create) to ignore self.
    """
    return text("""
        SELECT t.pay_id
        FROM tbl_payslip_print_component t
        WHERE t.payscheme_id = :payscheme_id
          AND t.company_id = :company_id
          AND t.branch_id = :branch_id
          AND t.component_id = :component_id
          AND t.is_active = 1
          AND t.pay_id <> :exclude_pay_id
        LIMIT 1
    """)


# ─── Payroll Processing queries ─────────────────────────────────────

def get_payscheme_mapped_employees():
    """Get employees mapped to a pay scheme (active, with optional branch filter)."""
    return text("""
        SELECT DISTINCT
            eps.EMPLOYEEID AS eb_id,
            p.first_name,
            p.middle_name,
            p.last_name,
            o.emp_code,
            o.branch_id
        FROM pay_employee_payscheme eps
        JOIN hrms_ed_personal_details p ON p.eb_id = eps.EMPLOYEEID AND p.active = 1
        LEFT JOIN hrms_ed_official_details o ON o.eb_id = eps.EMPLOYEEID AND o.active = 1
        WHERE eps.PAY_SCHEME_ID = :pay_scheme_id
          AND eps.STATUS = 1
          AND (:branch_id IS NULL OR o.branch_id = :branch_id)
        ORDER BY p.first_name
    """)


def get_pay_scheme_details_by_id():
    """Get all formulas for a pay scheme, ordered by component type (so inputs resolve first)."""
    return text("""
        SELECT
            psd.ID AS id,
            psd.COMPONENT_ID AS component_id,
            psd.FORMULA AS formula,
            psd.PAY_SCHEME_ID AS pay_scheme_id,
            psd.TYPE AS type,
            psd.STATUS AS status_id,
            psd.DEFAULT_VALUE AS default_value
        FROM pay_scheme_details psd
        WHERE psd.PAY_SCHEME_ID = :pay_scheme_id
          AND psd.STATUS = 1
        ORDER BY psd.TYPE, psd.COMPONENT_ID
    """)


def get_all_pay_components_for_company():
    """Get pay component metadata (code, name, type, rounding) used by the payroll
    calculator. Components are tenant-global with NULL company_id and approved
    STATUS=3, so they are not scoped by company (matching the rest of the payroll
    component queries)."""
    return text("""
        SELECT
            pc.ID AS id,
            pc.CODE AS code,
            pc.NAME AS name,
            pc.TYPE AS type,
            pc.DEFAULT_VALUE AS default_value,
            pc.IS_CUSTOM_COMPONENT AS is_custom_component,
            pc.IS_EXCEL_DOWNLOADABLE AS is_excel_downloadable,
            pc.ROUNDOF AS roundof,
            pc.ROUNDOF_TYPE AS roundof_type
        FROM pay_components pc
        WHERE pc.STATUS = 3
        ORDER BY pc.TYPE, pc.ID
    """)


def get_employee_pay_structure():
    """Get base values from pay_employee_structure for employees in a pay scheme."""
    return text("""
        SELECT
            pes.EMPLOYEEID AS eb_id,
            pes.COMPONENT_ID AS component_id,
            COALESCE(pes.AMOUNT, 0) AS amount
        FROM pay_employee_structure pes
        WHERE pes.PAYSCHEME_ID = :pay_scheme_id
          AND pes.STATUS = 1
          AND pes.EMPLOYEEID IN (
              SELECT eps.EMPLOYEEID
              FROM pay_employee_payscheme eps
              WHERE eps.PAY_SCHEME_ID = :pay_scheme_id AND eps.STATUS = 1
          )
    """)


def get_custom_component_values():
    """Get custom component values (manual / Excel grid) for a pay period.

    Matches by pay_period_id when rows carry one, but always falls back to the
    exact date range — saved rows stamp FROM_DATE/TO_DATE even when PAY_PERIOD_ID
    is NULL, so the values entered on the payroll grid are picked up regardless.
    """
    return text("""
        SELECT
            pcc.EMPLOYEEID AS eb_id,
            pcc.COMPONENT_ID AS component_id,
            pcc.VALUE AS value
        FROM pay_components_custom pcc
        WHERE pcc.STATUS = 1
          AND (
                (:pay_period_id IS NOT NULL AND pcc.PAY_PERIOD_ID = :pay_period_id)
             OR (pcc.FROM_DATE = :from_date AND pcc.TO_DATE = :to_date)
          )
    """)


def delete_existing_payroll_for_period():
    """Delete existing payroll records for a pay period before re-processing."""
    return text("""
        DELETE FROM pay_employee_payroll
        WHERE PAYPERIOD_ID = :pay_period_id
          AND PAYSCHEME_ID = :pay_scheme_id
    """)


def delete_existing_payperiod_entries():
    """Delete existing pay_employee_payperiod entries before re-processing."""
    return text("""
        DELETE FROM pay_employee_payperiod
        WHERE PAY_PERIOD_ID = :pay_period_id
          AND PAY_SCHEME_ID = :pay_scheme_id
    """)


# ─── Pay Roll (pay_components_custom) queries ───────────────────────

def get_pay_roll_custom_components():
    """Manual-entry pay components for a single pay scheme.

    These are the editable columns shown in the payroll grid / Excel template:
    the scheme's TYPE=0 components flagged IS_EXCEL_DOWNLOADABLE=1. Scoped to
    the selected pay scheme via pay_scheme_details so only that scheme's
    components appear (not every excel-downloadable component in the tenant).
    """
    return text("""
        SELECT DISTINCT pc.ID AS id, pc.CODE AS code, pc.NAME AS name
        FROM pay_scheme_details psd
        JOIN pay_components pc ON pc.ID = psd.COMPONENT_ID
        WHERE psd.PAY_SCHEME_ID = :pay_scheme_id
          AND pc.`TYPE` = 0
          AND pc.STATUS = 3
          AND pc.IS_EXCEL_DOWNLOADABLE = 1
          AND psd.STATUS = 1
        ORDER BY pc.ID
    """)


def get_excel_downloadable_component_codes():
    """code -> id map for every TYPE=0 IS_EXCEL_DOWNLOADABLE=1 component.

    Used by the Excel upload to resolve column headers (component CODEs) to
    component ids. Component CODEs are unique, so a global lookup correctly
    maps whatever columns were downloaded for the selected scheme, without
    needing the (blank) PayScheme column from the uploaded file.
    """
    return text("""
        SELECT pc.ID AS id, pc.CODE AS code
        FROM pay_components pc
        WHERE pc.`TYPE` = 0
          AND pc.STATUS = 3
          AND pc.IS_EXCEL_DOWNLOADABLE = 1
    """)


def get_pay_roll_employee_list():
    """Employees mapped to a pay scheme, filtered by branch / dept / category.

    Returns one row per active employee with their assigned pay scheme.
    """
    return text("""
        SELECT DISTINCT
            p.eb_id AS emp_id,
            o.emp_code AS emp_code,
            TRIM(CONCAT(p.first_name, ' ', COALESCE(p.middle_name, ''), ' ', COALESCE(p.last_name, ''))) AS emp_name,
            pc.NAME AS pay_scheme_name,
            eps.PAY_SCHEME_ID AS pay_scheme_id
        FROM hrms_ed_personal_details p
        JOIN hrms_ed_official_details o ON o.eb_id = p.eb_id AND o.active = 1
        JOIN pay_employee_payscheme eps ON eps.EMPLOYEEID = p.eb_id AND eps.STATUS = 1
        LEFT JOIN pay_components pc ON pc.ID = eps.PAY_SCHEME_ID
        WHERE p.active = 1
          AND o.branch_id = :branch_id
          AND (:pay_scheme_id IS NULL OR eps.PAY_SCHEME_ID = :pay_scheme_id)
          AND (:dept_id IS NULL OR o.sub_dept_id IN (
                SELECT sub_dept_id FROM sub_dept_mst WHERE dept_id = :dept_id
              ))
          AND (:emp_category_id IS NULL OR o.catagory_id = :emp_category_id)
        ORDER BY o.emp_code
    """)


def get_pay_roll_existing_pcc():
    """Custom component values previously saved for a pay_period or date range.

    Matches by the resolved pay_period_id when the rows carry one, but always
    falls back to the exact date range — saved rows stamp FROM_DATE/TO_DATE even
    when PAY_PERIOD_ID is NULL, so the date match surfaces prior values regardless
    of which (or whether a) pay_period was resolved.
    """
    return text("""
        SELECT
            pcc.EMPLOYEEID AS emp_id,
            pcc.COMPONENT_ID AS component_id,
            pcc.VALUE AS value
        FROM pay_components_custom pcc
        WHERE pcc.STATUS = 1
          AND (
                (:pay_period_id IS NOT NULL AND pcc.PAY_PERIOD_ID = :pay_period_id)
             OR (pcc.FROM_DATE = :from_date AND pcc.TO_DATE = :to_date)
          )
    """)


def find_pay_period_by_dates():
    """Find an existing PayPeriod for a (co_id, from_date, to_date)."""
    return text("""
SELECT id
        FROM pay_period
        WHERE branch_id= :branch_id
          AND from_date = :from_date
          AND to_date = :to_date
        ORDER BY id DESC
        LIMIT 1
            """)


def soft_delete_pcc_for_period():
    """Soft-delete (STATUS=0) existing pcc rows for a (period, employees) tuple
    so the upsert that follows can re-insert clean rows.
    """
    from sqlalchemy import bindparam
    return text("""
        UPDATE pay_components_custom
        SET STATUS = 0, updated_by = :updated_by, updated_date_time = NOW()
        WHERE (
                (:pay_period_id IS NOT NULL AND PAY_PERIOD_ID = :pay_period_id)
             OR (:pay_period_id IS NULL AND FROM_DATE = :from_date AND TO_DATE = :to_date)
          )
          AND EMPLOYEEID IN :emp_ids
          AND STATUS = 1
    """).bindparams(bindparam("emp_ids", expanding=True))


def get_branches_for_company():
    return text("""
        SELECT branch_id AS id, branch_name AS name
        FROM branch_mst
        WHERE co_id = :co_id AND (active = 1 OR active IS NULL)
        ORDER BY branch_name
    """)


def get_pay_schemes_for_company():
    return text("""
        SELECT payscheme_id AS id, payscheme_name AS name
        FROM pay_scheme_master
        WHERE (:co_id IS NULL OR co_id = :co_id)
        ORDER BY payscheme_name
    """)


def get_departments_for_company():
    return text("""
        SELECT d.dept_id AS id, d.dept_desc AS name
        FROM dept_mst d
        JOIN branch_mst b ON b.branch_id = d.branch_id
        WHERE b.co_id = :co_id
          AND (:branch_id IS NULL OR d.branch_id = :branch_id)
        ORDER BY d.dept_desc
    """)


def get_categories_for_company():
    return text("""
        SELECT c.cata_id AS id, c.cata_desc AS name
        FROM category_mst c
        JOIN branch_mst b ON b.branch_id = c.branch_id
        WHERE b.co_id = :co_id
          AND (:branch_id IS NULL OR c.branch_id = :branch_id)
        ORDER BY c.cata_desc
    """)


# ─── Employee Photo queries (stored in hrms_employee_face) ──────────

def get_employee_photo_by_eb_id():
    return text("""
        SELECT eb_id, face_image, file_name, file_extension
        FROM hrms_employee_face
        WHERE eb_id = :eb_id
          AND face_image IS NOT NULL
        LIMIT 1
    """)


def upsert_employee_photo():
    """Insert or update photo in hrms_employee_face (ON DUPLICATE KEY UPDATE on eb_id)."""
    return text("""
        INSERT INTO hrms_employee_face (eb_id, face_image, file_name, file_extension, branch_id, updated_by)
        VALUES (:eb_id, :face_image, :file_name, :file_extension, :branch_id, :updated_by)
        ON DUPLICATE KEY UPDATE
            face_image = VALUES(face_image),
            file_name = VALUES(file_name),
            file_extension = VALUES(file_extension),
            updated_by = VALUES(updated_by)
    """)


def delete_employee_photo():
    return text("""
        DELETE FROM hrms_employee_face
        WHERE eb_id = :eb_id
    """)


# ─── Employee Salary Structure queries ────────────────────────────────

def get_active_pay_scheme_dropdown():
    return text("""
        SELECT payscheme_id, payscheme_name, payscheme_code
        FROM pay_scheme_master
        WHERE (:co_id IS NULL OR co_id = :co_id)
          AND record_status IN (1, 32)
        ORDER BY payscheme_name
    """)


def get_employee_payscheme_by_eb_id():
    return text("""
        SELECT eps.ID AS id, eps.EMPLOYEEID AS eb_id, eps.PAY_SCHEME_ID AS pay_scheme_id,
               eps.STATUS AS status_id,
               (SELECT MAX(pes.EFFECTIVE_FROM)
                  FROM pay_employee_structure pes
                 WHERE pes.EMPLOYEEID = eps.EMPLOYEEID
                   AND pes.PAYSCHEME_ID = eps.PAY_SCHEME_ID
                   AND pes.STATUS = 1) AS effective_from,
               ps.payscheme_name, ps.payscheme_code
        FROM pay_employee_payscheme eps
        LEFT JOIN pay_scheme_master ps ON ps.payscheme_id = eps.PAY_SCHEME_ID
        WHERE eps.EMPLOYEEID = :eb_id AND eps.STATUS = 1
        ORDER BY eps.ID DESC
        LIMIT 1
    """)


def get_employee_structure_by_eb_id():
    return text("""
        SELECT pes.COMPONENT_ID AS component_id, COALESCE(pes.AMOUNT, 0) AS amount
        FROM pay_employee_structure pes
        WHERE pes.EMPLOYEEID = :eb_id AND pes.PAYSCHEME_ID = :pay_scheme_id AND pes.STATUS = 1
    """)
