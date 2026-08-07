from datetime import datetime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import Integer, String, BigInteger, Date, DateTime, Float, Boolean, TIMESTAMP, DECIMAL, LargeBinary, func

class Base(DeclarativeBase):
	pass

# Cash / daily rate approved per outsider worker, per date and shift.
# No co_id/branch_id of its own — scope comes from the employee (eb_id).
class OutsiderRateApprove(Base):
	__tablename__ = "outsider_rate_approve"
	outsider_rate_app_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
	eb_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
	rate_approve: Mapped[int | None] = mapped_column(Integer, nullable=True)
	is_active: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
	app_date: Mapped[Date | None] = mapped_column(Date, nullable=True)
	app_shift: Mapped[str | None] = mapped_column(String(2), nullable=True)
	desig_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


# Canteen meals taken by an employee on a date, at an agreed rate.
class CanteenDetails(Base):
	__tablename__ = "canteen_details"
	tran_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
	branch_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
	tran_date: Mapped[Date | None] = mapped_column(Date, nullable=True)
	no_of_meals: Mapped[int | None] = mapped_column(Integer, nullable=True)
	rate_of_meals: Mapped[int | None] = mapped_column(Integer, nullable=True, server_default="40")
	eb_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
	updated_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
	updated_date_time: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp())
	status_id: Mapped[int] = mapped_column(Integer, nullable=False, server_default="3")


# tbl_hrms_ed_personal_details → hrms_ed_personal_details
class HrmsEdPersonalDetails(Base):
	__tablename__ = "hrms_ed_personal_details"
	eb_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
	first_name: Mapped[str] = mapped_column(String(50), nullable=False)
	middle_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
	last_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
	gender: Mapped[str | None] = mapped_column(String(25), nullable=True)
	date_of_birth: Mapped[Date | None] = mapped_column(Date, nullable=True)
	blood_group: Mapped[str | None] = mapped_column(String(5), nullable=True)
	mobile_no: Mapped[str | None] = mapped_column(String(15), nullable=True)
	email_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
	marital_status: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0)
	country_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, default=73)
	relegion_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
	fixed_eb_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
	father_spouse_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
	passport_no: Mapped[str | None] = mapped_column(String(20), nullable=True)
	driving_licence_no: Mapped[str | None] = mapped_column(String(50), nullable=True)
	pan_no: Mapped[str | None] = mapped_column(String(15), nullable=True)
	aadhar_no: Mapped[str | None] = mapped_column(String(20), nullable=True)
	branch_id: Mapped[int] = mapped_column(Integer, nullable=False)
	updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
	updated_date_time: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
	active: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
	status_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=21)

# tbl_hrms_ed_address_details → hrms_ed_address_details
class HrmsEdAddressDetails(Base):
	__tablename__ = "hrms_ed_address_details"
	tbl_hrms_ed_contact_details_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
	eb_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
	address_type: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
	country_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
	state_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
	city_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
	address_line_1: Mapped[str] = mapped_column(String(150), nullable=False)
	address_line_2: Mapped[str | None] = mapped_column(String(150), nullable=True)
	pin_code: Mapped[int] = mapped_column(Integer, nullable=False)
	active: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
	is_correspondent_address: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
	updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
	updated_date_time: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())

# tbl_hrms_ed_bank_details → hrms_ed_bank_details
class HrmsEdBankDetails(Base):
	__tablename__ = "hrms_ed_bank_details"
	tbl_hrms_ed_bank_detail_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
	ifsc_code: Mapped[str] = mapped_column(String(15), nullable=False)
	bank_acc_no: Mapped[str] = mapped_column(String(20), nullable=False)
	active: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
	updated_by: Mapped[int] = mapped_column(Integer, nullable=False)
	updated_date_time: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
	bank_name: Mapped[str] = mapped_column(String(100), nullable=False)
	is_verified: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
	bank_branch_name: Mapped[str] = mapped_column(String(300), nullable=False)
	eb_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

# tbl_hrms_ed_contact_details → hrms_ed_contact_details
class HrmsEdContactDetails(Base):
	__tablename__ = "hrms_ed_contact_details"
	contact_detail_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
	eb_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
	mobile_no: Mapped[str] = mapped_column(String(15), nullable=False)
	emergency_no: Mapped[str | None] = mapped_column(String(15), nullable=True)
	active: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
	updated_by: Mapped[int] = mapped_column(Integer, nullable=False)
	updated_date_time: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())

# tbl_hrms_ed_official_details → hrms_ed_official_details
class HrmsEdOfficialDetails(Base):
	__tablename__ = "hrms_ed_official_details"
	tbl_hrms_ed_official_detail_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
	eb_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
	updated_by: Mapped[int] = mapped_column(Integer, nullable=False)
	updated_date_time: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
	active: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
	sub_dept_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
	catagory_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
	designation_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
	branch_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
	date_of_join: Mapped[Date | None] = mapped_column(Date, nullable=True)
	probation_period: Mapped[int | None] = mapped_column(Integer, nullable=True)
	minimum_working_commitment: Mapped[int] = mapped_column(Integer, nullable=False)
	reporting_eb_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
	emp_code: Mapped[str] = mapped_column(String(20), nullable=False)
	legacy_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
	contractor_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
	office_mobile_no: Mapped[str | None] = mapped_column(String(255), nullable=True)
	office_email_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

# tbl_hrms_ed_pf → hrms_ed_pf
class HrmsEdPf(Base):
	__tablename__ = "hrms_ed_pf"
	tbl_hrms_ed_pf_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
	eb_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
	active: Mapped[int] = mapped_column(Integer, nullable=False)
	updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
	updated_date_time: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
	pf_date_of_join: Mapped[Date | None] = mapped_column(Date, nullable=True)
	pf_no: Mapped[str] = mapped_column(String(50), nullable=False)
	pf_uan_no: Mapped[str] = mapped_column(String(50), nullable=False)
	pf_transfer_no: Mapped[str | None] = mapped_column(String(50), nullable=True)
	pf_previous_no: Mapped[str] = mapped_column(String(50), nullable=False)
	nominee_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
	relationship_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

# tbl_hrms_ed_esi → hrms_ed_esi
class HrmsEdEsi(Base):
	__tablename__ = "hrms_ed_esi"
	tbl_hrms_ed_esi_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
	eb_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
	active: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
	esi_no: Mapped[str] = mapped_column(String(50), nullable=False)
	updated_by: Mapped[int] = mapped_column(Integer, nullable=False)
	updated_date_time: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
	medical_policy_no: Mapped[str | None] = mapped_column(String(50), nullable=True)

# tbl_hrms_ed_resign_details → hrms_ed_resign_details
class HrmsEdResignDetails(Base):
	__tablename__ = "hrms_ed_resign_details"
	tbl_hrms_ed_resignation_details_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
	eb_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
	updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
	updated_date_time: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
	active: Mapped[int] = mapped_column(Integer, nullable=False)
	date_of_inactive: Mapped[Date | None] = mapped_column(Date, nullable=True)
	fnf_date: Mapped[Date | None] = mapped_column(Date, nullable=True)
	net_settlement_amount: Mapped[float | None] = mapped_column(DECIMAL(24,2), nullable=True)
	notice_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
	release_date: Mapped[Date | None] = mapped_column(Date, nullable=True)
	resign_reasons: Mapped[str | None] = mapped_column(String(500), nullable=True)
	resign_remarks: Mapped[str | None] = mapped_column(String(500), nullable=True)
	resigned_date: Mapped[Date | None] = mapped_column(Date, nullable=True)
	type_of_resign: Mapped[str | None] = mapped_column(String(45), nullable=True)
	retired_date: Mapped[Date | None] = mapped_column(Date, nullable=True)

# tbl_hrms_experience_details → hrms_experience_details
class HrmsExperienceDetails(Base):
	__tablename__ = "hrms_experience_details"
	auto_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
	updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
	updated_date_time: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
	eb_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
	company_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
	from_date: Mapped[Date | None] = mapped_column(Date, nullable=True)
	to_date: Mapped[Date | None] = mapped_column(Date, nullable=True)
	designation: Mapped[str | None] = mapped_column(String(255), nullable=True)
	project: Mapped[str | None] = mapped_column(String(255), nullable=True)
	co_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
	active: Mapped[int | None] = mapped_column(Integer, nullable=True)
	contact: Mapped[str | None] = mapped_column(String(50), nullable=True)

# tbl_hrms_blood_group → hrms_blood_group
class HrmsBloodGroup(Base):
	__tablename__ = "hrms_blood_group"
	blood_group_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
	blood_group_name: Mapped[str] = mapped_column(String(10), nullable=False)
	updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
	updated_date_time: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())


# tbl_pay_company_components -> pay_company_components
class PayCompanyComponents(Base):
	__tablename__ = "pay_company_components"
	updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
	updated_date_time: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
	id: Mapped[int] = mapped_column("ID", Integer, primary_key=True, autoincrement=True)
	component_id: Mapped[int | None] = mapped_column("COMPONENT_ID", Integer, nullable=True)
	businessunit_id: Mapped[int | None] = mapped_column("BUSINESSUNIT_ID", Integer, nullable=True)
	code: Mapped[str | None] = mapped_column("CODE", String(20), nullable=True)
	name: Mapped[str | None] = mapped_column("NAME", String(60), nullable=True)
	effective_from: Mapped[Date | None] = mapped_column("EFFECTIVE_FROM", Date, nullable=True)
	ends_on: Mapped[Date | None] = mapped_column("ENDS_ON", Date, nullable=True)
	status_id: Mapped[int | None] = mapped_column("STATUS", Integer, nullable=True)


# tbl_pay_components -> pay_components
class PayComponents(Base):
	__tablename__ = "pay_components"
	updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
	updated_date_time: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
	id: Mapped[int] = mapped_column("ID", Integer, primary_key=True, autoincrement=True)
	code: Mapped[str | None] = mapped_column("CODE", String(20), nullable=True)
	name: Mapped[str | None] = mapped_column("NAME", String(60), nullable=True)
	description: Mapped[str | None] = mapped_column("DESCRIPTION", String(199), nullable=True)
	type: Mapped[int] = mapped_column("TYPE", Integer, nullable=False, default=1)
	effective_from: Mapped[Date | None] = mapped_column("EFFECTIVE_FROM", Date, nullable=True)
	ends_on: Mapped[Date | None] = mapped_column("ENDS_ON", Date, nullable=True)
	is_custom_component: Mapped[int | None] = mapped_column("IS_CUSTOM_COMPONENT", Integer, nullable=True)
	is_displayable_in_payslip: Mapped[int | None] = mapped_column("IS_DISPLAYABLE_IN_PAYSLIP", Integer, nullable=True)
	is_occasionally: Mapped[int | None] = mapped_column("IS_OCCASIONALLY", Integer, nullable=True)
	parent_id: Mapped[int | None] = mapped_column("PARENT_ID", Integer, nullable=True)
	co_id: Mapped[int | None] = mapped_column("company_id", Integer, nullable=True)
	default_value: Mapped[float | None] = mapped_column("DEFAULT_VALUE", Float, nullable=True)
	status_id: Mapped[int | None] = mapped_column("STATUS", Integer, nullable=True)
	roundof: Mapped[int | None] = mapped_column("ROUNDOF", Integer, nullable=True)
	roundof_type: Mapped[int | None] = mapped_column("ROUNDOF_TYPE", Integer, nullable=True)
	is_excel_downloadable: Mapped[int | None] = mapped_column("IS_EXCEL_DOWNLOADABLE", Integer, nullable=True)
	is_commulative: Mapped[int | None] = mapped_column("IS_COMMULATIVE", Integer, nullable=True)
	cumulative_component_id: Mapped[int | None] = mapped_column("cumulative_component_id", Integer, nullable=True)
	cumulative_period_from: Mapped[DateTime | None] = mapped_column("cumulative_period_from", DateTime, nullable=True)
	cumulative_period_to: Mapped[DateTime | None] = mapped_column("cumulative_period_to", DateTime, nullable=True)


# tbl_pay_components_custom -> pay_components_custom
class PayComponentsCustom(Base):
	__tablename__ = "pay_components_custom"
	updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
	updated_date_time: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
	id: Mapped[int] = mapped_column("ID", Integer, primary_key=True, autoincrement=True)
	component_id: Mapped[int | None] = mapped_column("COMPONENT_ID", Integer, nullable=True)
	value: Mapped[str | None] = mapped_column("VALUE", String(30), nullable=True)
	employeeid: Mapped[int | None] = mapped_column("EMPLOYEEID", Integer, nullable=True)
	status_id: Mapped[int | None] = mapped_column("STATUS", Integer, nullable=True)
	pay_period_id: Mapped[int | None] = mapped_column("PAY_PERIOD_ID", Integer, nullable=True)
	from_date: Mapped[Date | None] = mapped_column("FROM_DATE", Date, nullable=True)
	to_date: Mapped[Date | None] = mapped_column("TO_DATE", Date, nullable=True)


# tbl_pay_custemp_components_custom -> pay_custemp_components_custom
class PayCustempComponentsCustom(Base):
	__tablename__ = "pay_custemp_components_custom"
	updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
	updated_date_time: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
	id: Mapped[int] = mapped_column("ID", Integer, primary_key=True, autoincrement=True)
	component_id: Mapped[int | None] = mapped_column("COMPONENT_ID", Integer, nullable=True)
	value: Mapped[str | None] = mapped_column("VALUE", String(30), nullable=True)
	customerid: Mapped[int | None] = mapped_column("CUSTOMERID", Integer, nullable=True)
	employeeid: Mapped[int | None] = mapped_column("EMPLOYEEID", Integer, nullable=True)
	status_id: Mapped[int | None] = mapped_column("STATUS", Integer, nullable=True)
	pay_period_id: Mapped[int | None] = mapped_column("PAY_PERIOD_ID", Integer, nullable=True)


# tbl_pay_customer_employee_payroll -> pay_customer_employee_payroll
class PayCustomerEmployeePayroll(Base):
	__tablename__ = "pay_customer_employee_payroll"
	updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
	updated_date_time: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
	id: Mapped[int] = mapped_column("ID", Integer, primary_key=True, autoincrement=True)
	employeeid: Mapped[int | None] = mapped_column("EMPLOYEEID", Integer, nullable=True)
	component_id: Mapped[int | None] = mapped_column("COMPONENT_ID", Integer, nullable=True)
	payperiod_id: Mapped[int | None] = mapped_column("PAYPERIOD_ID", Integer, nullable=True)
	amount: Mapped[float | None] = mapped_column("AMOUNT", Float, nullable=True)
	status_id: Mapped[int | None] = mapped_column("STATUS", Integer, nullable=True)
	businessunit_id: Mapped[int | None] = mapped_column("BUSINESSUNIT_ID", Integer, nullable=True)
	payscheme_id: Mapped[int | None] = mapped_column("PAYSCHEME_ID", Integer, nullable=True)
	source: Mapped[str | None] = mapped_column("SOURCE", String(20), nullable=True)


# tbl_pay_customer_employee_payscheme -> pay_customer_employee_payscheme
class PayCustomerEmployeePayscheme(Base):
	__tablename__ = "pay_customer_employee_payscheme"
	updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
	updated_date_time: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
	id: Mapped[int] = mapped_column("ID", Integer, primary_key=True, autoincrement=True)
	customerid: Mapped[int | None] = mapped_column("CUSTOMERID", Integer, nullable=True)
	employeeid: Mapped[int | None] = mapped_column("EMPLOYEEID", Integer, nullable=True)
	pay_scheme_id: Mapped[int | None] = mapped_column("PAY_SCHEME_ID", Integer, nullable=True)
	status_id: Mapped[int | None] = mapped_column("STATUS", Integer, nullable=True)


# tbl_pay_customer_employee_period -> pay_customer_employee_period
class PayCustomerEmployeePeriod(Base):
	__tablename__ = "pay_customer_employee_period"
	updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
	updated_date_time: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
	id: Mapped[int] = mapped_column("ID", Integer, primary_key=True, autoincrement=True)
	from_date: Mapped[Date | None] = mapped_column("FROM_DATE", Date, nullable=True)
	to_date: Mapped[Date | None] = mapped_column("TO_DATE", Date, nullable=True)
	payscheme_id: Mapped[int | None] = mapped_column("PAYSCHEME_ID", Integer, nullable=True)
	customer_id: Mapped[int | None] = mapped_column("CUSTOMER_ID", Integer, nullable=True)
	status_id: Mapped[int | None] = mapped_column("STATUS", Integer, nullable=True)
	branch_id: Mapped[int | None] = mapped_column("branch_id", Integer, nullable=True)


# tbl_pay_customer_employee_structure -> pay_customer_employee_structure
class PayCustomerEmployeeStructure(Base):
	__tablename__ = "pay_customer_employee_structure"
	updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
	updated_date_time: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
	id: Mapped[int] = mapped_column("ID", Integer, primary_key=True, autoincrement=True)
	employeeid: Mapped[int | None] = mapped_column("EMPLOYEEID", Integer, nullable=True)
	payscheme_id: Mapped[int | None] = mapped_column("PAYSCHEME_ID", Integer, nullable=True)
	component_id: Mapped[int | None] = mapped_column("COMPONENT_ID", Integer, nullable=True)
	amount: Mapped[float | None] = mapped_column("AMOUNT", Float, nullable=True)
	status_id: Mapped[int | None] = mapped_column("STATUS", Integer, nullable=True)
	effective_from: Mapped[DateTime | None] = mapped_column("EFFECTIVE_FROM", DateTime, nullable=True)
	ends_on: Mapped[Date | None] = mapped_column("ENDS_ON", Date, nullable=True)
	remarks: Mapped[str | None] = mapped_column("REMARKS", String(599), nullable=True)
	customer_id: Mapped[int] = mapped_column("CUSTOMERID", Integer, nullable=False)


# tbl_pay_employee_payperiod -> pay_employee_payperiod
class PayEmployeePayperiod(Base):
	__tablename__ = "pay_employee_payperiod"
	updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
	updated_date_time: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
	id: Mapped[int] = mapped_column("ID", Integer, primary_key=True, autoincrement=True)
	employeeid: Mapped[int | None] = mapped_column("EMPLOYEEID", Integer, nullable=True)
	pay_period_id: Mapped[int | None] = mapped_column("PAY_PERIOD_ID", Integer, nullable=True)
	pay_scheme_id: Mapped[int | None] = mapped_column("PAY_SCHEME_ID", Integer, nullable=True)
	basic: Mapped[float | None] = mapped_column("BASIC", DECIMAL(20, 5), nullable=True)
	net: Mapped[float | None] = mapped_column("NET", DECIMAL(20, 5), nullable=True)
	gross: Mapped[float | None] = mapped_column("GROSS", DECIMAL(20, 5), nullable=True)
	status_id: Mapped[int | None] = mapped_column("STATUS", Integer, nullable=True)


# tbl_pay_employee_payroll -> pay_employee_payroll
class PayEmployeePayroll(Base):
	__tablename__ = "pay_employee_payroll"
	updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
	updated_date_time: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
	id: Mapped[int] = mapped_column("ID", Integer, primary_key=True, autoincrement=True)
	eb_id: Mapped[int | None] = mapped_column("EMPLOYEEID", Integer, nullable=True)
	component_id: Mapped[int | None] = mapped_column("COMPONENT_ID", Integer, nullable=True)
	payperiod_id: Mapped[int | None] = mapped_column("PAYPERIOD_ID", Integer, nullable=True)
	amount: Mapped[float | None] = mapped_column("AMOUNT", Float, nullable=True)
	status_id: Mapped[int | None] = mapped_column("STATUS", Integer, nullable=True)
	businessunit_id: Mapped[int | None] = mapped_column("BUSINESSUNIT_ID", Integer, nullable=True)
	payscheme_id: Mapped[int | None] = mapped_column("PAYSCHEME_ID", Integer, nullable=True)
	source: Mapped[str | None] = mapped_column("SOURCE", String(20), nullable=True)


# tbl_pay_employee_payroll_status -> pay_employee_payroll_status
class PayEmployeePayrollStatus(Base):
	__tablename__ = "pay_employee_payroll_status"
	updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
	updated_date_time: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
	id: Mapped[int] = mapped_column("ID", Integer, primary_key=True, autoincrement=True)
	pay_scheme_id: Mapped[int | None] = mapped_column("PAYSCHEME_ID", Integer, nullable=True)
	business_unit_id: Mapped[int | None] = mapped_column("BUSINESSUNIT_ID", Integer, nullable=True)
	pay_period_id: Mapped[int | None] = mapped_column("PAYPERIOD_ID", Integer, nullable=True)
	status_id: Mapped[int | None] = mapped_column("STATUS", Integer, nullable=True)
	iteration_cnt: Mapped[int | None] = mapped_column("ITERATION_CNT", Integer, nullable=True)
	comments: Mapped[str | None] = mapped_column("COMMENTS", String(599), nullable=True)


# tbl_pay_employee_payroll_status_log -> pay_employee_payroll_status_log
class PayEmployeePayrollStatusLog(Base):
	__tablename__ = "pay_employee_payroll_status_log"
	updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
	updated_date_time: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
	id: Mapped[int] = mapped_column("ID", Integer, primary_key=True)
	pay_scheme_id: Mapped[int | None] = mapped_column("PAYSCHEME_ID", Integer, nullable=True)
	business_unit_id: Mapped[int | None] = mapped_column("BUSINESSUNIT_ID", Integer, nullable=True)
	pay_period_id: Mapped[int] = mapped_column("PAYPERIOD_ID", Integer, nullable=False)
	status_id: Mapped[int | None] = mapped_column("STATUS", Integer, nullable=True)
	iteration_cnt: Mapped[int | None] = mapped_column("ITERATION_CNT", Integer, nullable=True)
	comments: Mapped[str | None] = mapped_column("COMMENTS", String(599), nullable=True)


# tbl_pay_employee_payscheme -> pay_employee_payscheme
class PayEmployeePayscheme(Base):
	__tablename__ = "pay_employee_payscheme"
	updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
	updated_date_time: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
	id: Mapped[int] = mapped_column("ID", Integer, primary_key=True, autoincrement=True)
	eb_id: Mapped[int | None] = mapped_column("EMPLOYEEID", Integer, nullable=True)
	pay_scheme_id: Mapped[int | None] = mapped_column("PAY_SCHEME_ID", Integer, nullable=True)
	status_id: Mapped[int | None] = mapped_column("STATUS", Integer, nullable=True)


# tbl_pay_employee_structure -> pay_employee_structure
class PayEmployeeStructure(Base):
	__tablename__ = "pay_employee_structure"
	updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
	updated_date_time: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
	id: Mapped[int] = mapped_column("ID", Integer, primary_key=True, autoincrement=True)
	eb_id: Mapped[int | None] = mapped_column("EMPLOYEEID", Integer, nullable=True)
	pay_scheme_id: Mapped[int | None] = mapped_column("PAYSCHEME_ID", Integer, nullable=True)
	component_id: Mapped[int | None] = mapped_column("COMPONENT_ID", Integer, nullable=True)
	amount: Mapped[float | None] = mapped_column("AMOUNT", Float, nullable=True)
	status_id: Mapped[int | None] = mapped_column("STATUS", Integer, nullable=True)
	effective_from: Mapped[DateTime | None] = mapped_column("EFFECTIVE_FROM", DateTime, nullable=True)
	ends_on: Mapped[Date | None] = mapped_column("ENDS_ON", Date, nullable=True)
	remarks: Mapped[str | None] = mapped_column("REMARKS", String(599), nullable=True)


# tbl_pay_external_components -> pay_external_components
class PayExternalComponents(Base):
	__tablename__ = "pay_external_components"
	updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
	updated_date_time: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
	id: Mapped[int] = mapped_column("ID", Integer, primary_key=True, autoincrement=True)
	eb_id: Mapped[int | None] = mapped_column("EMPLOYEEID", Integer, nullable=True)
	component_id: Mapped[int | None] = mapped_column("COMPONENT_ID", Integer, nullable=True)
	value: Mapped[str | None] = mapped_column("VALUE", String(99), nullable=True)
	status_id: Mapped[int | None] = mapped_column("STATUS", Integer, nullable=True)
	pay_period_id: Mapped[int | None] = mapped_column("PAYPERIOD_ID", Integer, nullable=True)


# tbl_pay_generic -> pay_generic
class PayGeneric(Base):
	__tablename__ = "pay_generic"
	updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
	updated_date_time: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
	id: Mapped[int] = mapped_column("id", Integer, primary_key=True, autoincrement=True)
	date_time: Mapped[DateTime | None] = mapped_column("date_time", DateTime, nullable=True)
	component_id: Mapped[int | None] = mapped_column("component_id", Integer, nullable=True)
	value: Mapped[str | None] = mapped_column("VALUE", String(30), nullable=True)
	eb_id: Mapped[int | None] = mapped_column("employeeId", BigInteger, nullable=True)


# tbl_pay_period -> pay_period
class PayPeriod(Base):
	__tablename__ = "pay_period"
	updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
	updated_date_time: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
	id: Mapped[int] = mapped_column("ID", Integer, primary_key=True, autoincrement=True)
	from_date: Mapped[Date | None] = mapped_column("FROM_DATE", Date, nullable=True)
	to_date: Mapped[Date | None] = mapped_column("TO_DATE", Date, nullable=True)
	payscheme_id: Mapped[int | None] = mapped_column("PAYSCHEME_ID", Integer, nullable=True)
	status_id: Mapped[int | None] = mapped_column("STATUS", Integer, nullable=True)
	branch_id: Mapped[int | None] = mapped_column("branch_id", Integer, nullable=True)
	co_id: Mapped[int | None] = mapped_column("COMPANY_ID", Integer, nullable=True)


# tbl_pay_period_status -> pay_period_status
class PayPeriodStatus(Base):
	__tablename__ = "pay_period_status"
	updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
	updated_date_time: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
	id: Mapped[int] = mapped_column("ID", Integer, primary_key=True, autoincrement=True)
	pay_scheme_id: Mapped[int | None] = mapped_column("PAY_SCHEME_ID", Integer, nullable=True)
	fromdate: Mapped[Date | None] = mapped_column("FROMDATE", Date, nullable=True)
	todate: Mapped[Date | None] = mapped_column("TODATE", Date, nullable=True)
	status_id: Mapped[int | None] = mapped_column("STATUS", Integer, nullable=True)


# tbl_pay_report -> pay_report
class PayReport(Base):
	__tablename__ = "pay_report"
	updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
	updated_date_time: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
	id: Mapped[int] = mapped_column("id", Integer, primary_key=True)
	co_id: Mapped[int | None] = mapped_column("company_id", Integer, nullable=True)
	type: Mapped[int | None] = mapped_column("type", Integer, nullable=True)
	value: Mapped[str | None] = mapped_column("value", String(60), nullable=True)
	status_id: Mapped[int | None] = mapped_column("status", Integer, nullable=True)


# tbl_pay_report_combinations -> pay_report_combinations
class PayReportCombinations(Base):
	__tablename__ = "pay_report_combinations"
	updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
	updated_date_time: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
	id: Mapped[int] = mapped_column("id", Integer, primary_key=True)
	report_id: Mapped[int | None] = mapped_column("report_id", Integer, nullable=True)
	status_id: Mapped[int | None] = mapped_column("status", Integer, nullable=True)


# tbl_pay_scheme -> pay_scheme
class PayScheme(Base):
	__tablename__ = "pay_scheme"
	updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
	updated_date_time: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
	id: Mapped[int] = mapped_column("ID", Integer, primary_key=True, autoincrement=True)
	wage_id: Mapped[int | None] = mapped_column("WAGE_ID", Integer, nullable=True)
	businessunit_id: Mapped[int | None] = mapped_column("BUSINESSUNIT_ID", Integer, nullable=True)
	name: Mapped[str | None] = mapped_column("NAME", String(45), nullable=True)
	code: Mapped[str | None] = mapped_column("CODE", String(20), nullable=True)
	description: Mapped[str | None] = mapped_column("DESCRIPTION", String(599), nullable=True)
	status_id: Mapped[int | None] = mapped_column("STATUS", Integer, nullable=True)
	customer_branch_id: Mapped[int | None] = mapped_column("customer_branch_id", BigInteger, nullable=True)
	designation: Mapped[int | None] = mapped_column("designation", BigInteger, nullable=True)


# tbl_pay_scheme_details -> pay_scheme_details
class PaySchemeDetails(Base):
	__tablename__ = "pay_scheme_details"
	updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
	updated_date_time: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
	id: Mapped[int] = mapped_column("ID", Integer, primary_key=True, autoincrement=True)
	component_id: Mapped[int | None] = mapped_column("COMPONENT_ID", Integer, nullable=True)
	formula: Mapped[str | None] = mapped_column("FORMULA", String(599), nullable=True)
	pay_scheme_id: Mapped[int | None] = mapped_column("PAY_SCHEME_ID", BigInteger, nullable=True)
	type: Mapped[str | None] = mapped_column("TYPE", String(1), nullable=True)
	status_id: Mapped[int | None] = mapped_column("STATUS", Integer, nullable=True)
	default_value: Mapped[float | None] = mapped_column("DEFAULT_VALUE", Float, nullable=True)


# tbl_pay_wages_mode -> pay_wages_mode
class PayWagesMode(Base):
	__tablename__ = "pay_wages_mode"
	updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
	updated_date_time: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
	id: Mapped[int] = mapped_column("ID", Integer, primary_key=True, autoincrement=True)
	businessunit_id: Mapped[int | None] = mapped_column("BUSINESSUNIT_ID", Integer, nullable=True)
	code: Mapped[str | None] = mapped_column("CODE", String(20), nullable=True)
	name: Mapped[str | None] = mapped_column("NAME", String(60), nullable=True)
	description: Mapped[str | None] = mapped_column("DESCRIPTION", String(599), nullable=True)
	status_id: Mapped[int | None] = mapped_column("STATUS", Integer, nullable=True)


# pay_register
class PayRegister(Base):
	__tablename__ = "pay_register"
	updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
	updated_date_time: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
	rec_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
	advance: Mapped[int | None] = mapped_column(Integer, nullable=True)
	amount: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
	basic: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
	cont_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
	cont_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
	conveyance: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
	days: Mapped[int | None] = mapped_column(Integer, nullable=True)
	dept_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
	dept_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
	eb_id: Mapped[int | None] = mapped_column("employeeId", BigInteger, nullable=True)
	education: Mapped[int | None] = mapped_column(Integer, nullable=True)
	esi_employer: Mapped[int | None] = mapped_column(Integer, nullable=True)
	esi_employee: Mapped[int | None] = mapped_column(Integer, nullable=True)
	from_date: Mapped[Date | None] = mapped_column(Date, nullable=True)
	gross1: Mapped[int | None] = mapped_column(Integer, nullable=True)
	gross2: Mapped[int | None] = mapped_column(Integer, nullable=True)
	gross3: Mapped[int | None] = mapped_column(Integer, nullable=True)
	hra: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
	lock_status: Mapped[str | None] = mapped_column(String(255), nullable=True)
	mdept_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
	mdept_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
	medical: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
	net: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
	other_allowance: Mapped[int | None] = mapped_column(Integer, nullable=True)
	pf_employee: Mapped[int | None] = mapped_column(Integer, nullable=True)
	pf_employer: Mapped[int | None] = mapped_column(Integer, nullable=True)
	plus_balance: Mapped[int | None] = mapped_column(Integer, nullable=True)
	rate1: Mapped[int | None] = mapped_column(Integer, nullable=True)
	ta: Mapped[int | None] = mapped_column(Integer, nullable=True)
	telephone: Mapped[int | None] = mapped_column(Integer, nullable=True)
	to_date: Mapped[Date | None] = mapped_column(Date, nullable=True)
	training: Mapped[int | None] = mapped_column(Integer, nullable=True)
	uniform: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
	auto_datetime_insert: Mapped[DateTime] = mapped_column(DateTime, nullable=False)
	co_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


# holiday_wage_pay_register
class HolidayWagePayRegister(Base):
	__tablename__ = "pay_holiday_wage_pay_register"
	updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
	updated_date_time: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
	rec_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
	cata_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
	cata_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
	da_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
	dept_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
	dept_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
	diff: Mapped[float | None] = mapped_column(Float, nullable=True)
	eb_id: Mapped[int | None] = mapped_column("employeeId", BigInteger, nullable=True)
	from_date: Mapped[Date | None] = mapped_column(Date, nullable=True)
	lock_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
	mb: Mapped[float | None] = mapped_column(Float, nullable=True)
	mdept_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
	mdept_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
	p_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
	p_wages: Mapped[float | None] = mapped_column(Float, nullable=True)
	paid: Mapped[float | None] = mapped_column(Float, nullable=True)
	round: Mapped[float | None] = mapped_column(Float, nullable=True)
	to_date: Mapped[Date | None] = mapped_column(Date, nullable=True)
	total: Mapped[float | None] = mapped_column(Float, nullable=True)
	auto_datetime_insert: Mapped[DateTime] = mapped_column(DateTime, nullable=False)


# payscheme_parameter_category
class PayschemeParameterCategory(Base):
	__tablename__ = "pay_scheme_parameter_category"
	updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
	updated_date_time: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
	ppcid: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
	category_name: Mapped[str | None] = mapped_column(String(255), nullable=True)


# processed_payscheme
class ProcessedPayscheme(Base):
	__tablename__ = "pay_processed_payscheme"
	updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
	updated_date_time: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
	processed_payscheme_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
	basic_pay: Mapped[float | None] = mapped_column(Float, nullable=True)
	co_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
	da: Mapped[float | None] = mapped_column(Float, nullable=True)
	empresi: Mapped[float | None] = mapped_column(Float, nullable=True)
	emprpf: Mapped[float | None] = mapped_column(Float, nullable=True)
	esi: Mapped[float | None] = mapped_column(Float, nullable=True)
	from_date: Mapped[Date | None] = mapped_column(Date, nullable=True)
	gross: Mapped[float | None] = mapped_column(Float, nullable=True)
	hra: Mapped[float | None] = mapped_column(Float, nullable=True)
	net: Mapped[float | None] = mapped_column(Float, nullable=True)
	othear: Mapped[float | None] = mapped_column(Float, nullable=True)
	othded: Mapped[float | None] = mapped_column(Float, nullable=True)
	payscheme_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
	pf: Mapped[float | None] = mapped_column(Float, nullable=True)
	status_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
	to_date: Mapped[Date | None] = mapped_column(Date, nullable=True)
	wage_type: Mapped[str | None] = mapped_column(String(255), nullable=True)


# seq_payroll
class SeqPayroll(Base):
	__tablename__ = "pay_seq_payroll"
	updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
	updated_date_time: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
	next_val: Mapped[int] = mapped_column(Integer, primary_key=True)


# tbl_payscheme_master -> payscheme_master
class PayschemeMaster(Base):
	__tablename__ = "pay_scheme_master"
	payscheme_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
	co_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
	effective_from: Mapped[str | None] = mapped_column(String(255), nullable=True)
	payscheme_code: Mapped[str | None] = mapped_column(String(255), nullable=True)
	payscheme_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
	record_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
	updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
	updated_date_time: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
	wage_type: Mapped[int | None] = mapped_column(Integer, nullable=True)
	branch_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


# tbl_payslip -> payslip
class Payslip(Base):
	__tablename__ = "pay_slip"
	payslip_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
	co_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
	dept_desc: Mapped[str | None] = mapped_column(String(255), nullable=True)
	dept_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
	eb_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
	emp_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
	esi_no: Mapped[str | None] = mapped_column(String(255), nullable=True)
	lock_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
	month: Mapped[int | None] = mapped_column(Integer, nullable=True)
	occu_desc: Mapped[str | None] = mapped_column(String(255), nullable=True)
	occu_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
	payscheme_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
	pf_no: Mapped[str | None] = mapped_column(String(255), nullable=True)
	record_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
	updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
	updated_date_time: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
	year: Mapped[int | None] = mapped_column(Integer, nullable=True)


# tbl_payslip_components -> payslip_components
class PayslipComponents(Base):
	__tablename__ = "pay_slip_components"
	updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
	updated_date_time: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
	component_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
	processed_payscheme_seq_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
	co_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
	is_active: Mapped[int | None] = mapped_column(Integer, nullable=True)
	from_date: Mapped[Date | None] = mapped_column(Date, nullable=True)
	to_date: Mapped[Date | None] = mapped_column(Date, nullable=True)
	payscheme_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
	m_dept_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
	m_dept_desc: Mapped[str | None] = mapped_column(String(20), nullable=True)
	sub_dept_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
	sub_dept_desc: Mapped[str | None] = mapped_column(String(20), nullable=True)
	eb_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
	eb_no: Mapped[str | None] = mapped_column(String(20), nullable=True)
	emp_name: Mapped[str | None] = mapped_column(String(20), nullable=True)
	pf: Mapped[str | None] = mapped_column(String(50), nullable=True)
	esi: Mapped[str | None] = mapped_column(String(50), nullable=True)
	designation_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
	designation_desc: Mapped[str | None] = mapped_column(String(20), nullable=True)
	esid: Mapped[float | None] = mapped_column(DECIMAL(20, 2), nullable=True)
	thr: Mapped[float | None] = mapped_column(DECIMAL(20, 2), nullable=True)
	phrs: Mapped[float | None] = mapped_column(DECIMAL(20, 2), nullable=True)
	lohrs: Mapped[float | None] = mapped_column(DECIMAL(20, 2), nullable=True)
	ld: Mapped[float | None] = mapped_column(DECIMAL(20, 2), nullable=True)
	adjded: Mapped[float | None] = mapped_column(DECIMAL(20, 2), nullable=True)
	adjpay: Mapped[float | None] = mapped_column(DECIMAL(20, 2), nullable=True)
	pl: Mapped[float | None] = mapped_column(DECIMAL(20, 2), nullable=True)
	upl: Mapped[float | None] = mapped_column(DECIMAL(20, 2), nullable=True)
	othr: Mapped[float | None] = mapped_column(DECIMAL(20, 2), nullable=True)
	pothrs: Mapped[float | None] = mapped_column(DECIMAL(20, 2), nullable=True)
	potwage: Mapped[float | None] = mapped_column(DECIMAL(20, 2), nullable=True)
	pwage: Mapped[float | None] = mapped_column(DECIMAL(20, 2), nullable=True)
	rent_status: Mapped[float | None] = mapped_column(DECIMAL(20, 2), nullable=True)
	rent_ded: Mapped[float | None] = mapped_column(DECIMAL(20, 2), nullable=True)
	tds: Mapped[float | None] = mapped_column(DECIMAL(20, 2), nullable=True)
	ptax: Mapped[float | None] = mapped_column(DECIMAL(20, 2), nullable=True)
	da: Mapped[float | None] = mapped_column(DECIMAL(20, 2), nullable=True)
	basic: Mapped[float | None] = mapped_column(DECIMAL(20, 2), nullable=True)
	gross: Mapped[float | None] = mapped_column(DECIMAL(20, 2), nullable=True)
	net: Mapped[float | None] = mapped_column(DECIMAL(20, 2), nullable=True)
	days: Mapped[float | None] = mapped_column(DECIMAL(20, 2), nullable=True)
	hra: Mapped[float | None] = mapped_column(DECIMAL(20, 2), nullable=True)
	pf_empl_amt: Mapped[float | None] = mapped_column(DECIMAL(20, 2), nullable=True)
	pf_empr_amt: Mapped[float | None] = mapped_column(DECIMAL(20, 2), nullable=True)
	esi_empl_amt: Mapped[float | None] = mapped_column(DECIMAL(20, 2), nullable=True)
	esi_empr_amt: Mapped[float | None] = mapped_column(DECIMAL(20, 2), nullable=True)
	totalsal: Mapped[float | None] = mapped_column("TOTALSAL", Float, nullable=True)
	moballow: Mapped[float | None] = mapped_column("MOBALLOW", Float, nullable=True)
	cnh: Mapped[float | None] = mapped_column("CNH", Float, nullable=True)
	tallowance: Mapped[float | None] = mapped_column("TALLOWANCE", Float, nullable=True)
	bah: Mapped[float | None] = mapped_column("BAH", Float, nullable=True)
	abc: Mapped[float | None] = mapped_column("ABC", Float, nullable=True)
	abcdef: Mapped[float | None] = mapped_column("ABCDEF", Float, nullable=True)


# tbl_payslip_parameters -> payslip_parameters
class PayslipParameters(Base):
	__tablename__ = "pay_slip_parameters"
	payslip_param_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
	co_id: Mapped[int] = mapped_column(Integer, nullable=False)
	emp_salary_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
	parameter_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
	parameter_value: Mapped[str | None] = mapped_column(String(255), nullable=True)
	record_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
	updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
	updated_date_time: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
	payslip_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


# tbl_cm_job_payment_links -> cm_job_payment_links
class CmJobPaymentLinks(Base):
	__tablename__ = "pay_cm_job_payment_links"
	updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
	updated_date_time: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
	id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
	payment_link: Mapped[str | None] = mapped_column(String(599), nullable=True)
	validity: Mapped[int | None] = mapped_column(Integer, nullable=True)
	job_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
	co_id: Mapped[int] = mapped_column(Integer, nullable=False)


# hrms_employee_face → employee photo/face image storage
class HrmsEmployeeFace(Base):
	__tablename__ = "hrms_employee_face"
	face_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
	eb_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
	face_image: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
	face_image_type_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
	file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
	file_extension: Mapped[str | None] = mapped_column(String(10), nullable=True)
	branch_id: Mapped[int] = mapped_column(Integer, nullable=False)
	updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
	updated_date_time: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())

# leave-management tables (synced from sls → dev3)
class HrmsLeaveTypesMst(Base):
	__tablename__ = "hrms_leave_types_mst"
	leave_type_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=0)
	company_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
	is_active: Mapped[int | None] = mapped_column(Integer, nullable=True)
	leave_type_code: Mapped[str | None] = mapped_column(String(255), nullable=True)
	leave_type_description: Mapped[str | None] = mapped_column(String(255), nullable=True)
	payable: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="Y OR N")
	updated_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
	updated_date_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
	Leave_hours: Mapped[float | None] = mapped_column(Float, nullable=True)

class LeaveLedgerTran(Base):
	__tablename__ = "leave_ledger_tran"
	leave_ledger_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
	eb_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
	leave_type_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
	entitled_from_date: Mapped[Date | None] = mapped_column(Date, nullable=True)
	entitled_to_date: Mapped[Date | None] = mapped_column(Date, nullable=True)
	no_of_leaves_entitled: Mapped[int | None] = mapped_column(Integer, nullable=True)
	carry_forward: Mapped[int | None] = mapped_column(Integer, nullable=True)

class LeaveTransactions(Base):
	__tablename__ = "leave_transactions"
	leave_transaction_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=0)
	branch_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
	eb_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
	leave_from_date: Mapped[Date | None] = mapped_column(Date, nullable=True)
	leave_ledger_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
	leave_purpose: Mapped[str | None] = mapped_column(String(255), nullable=True)
	leave_to_date: Mapped[Date | None] = mapped_column(Date, nullable=True)
	leave_type_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
	remarks: Mapped[str | None] = mapped_column(String(255), nullable=True)
	status: Mapped[str | None] = mapped_column(String(255), nullable=True)
	updated_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
	updated_date_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
	non_working_days: Mapped[int | None] = mapped_column(Integer, nullable=True)

class LeaveTranDetails(Base):
	__tablename__ = "leave_tran_details"
	lvd_tran_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=0)
	leave_date: Mapped[Date | None] = mapped_column(Date, nullable=True)
	ltran_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
	auto_datetime_insert: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp())
	created_by: Mapped[str | None] = mapped_column(String(20), nullable=True)
	company_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
	is_active: Mapped[int | None] = mapped_column(Integer, nullable=True, default=1)


# tbl_payslip_print_component → payslip print/export column configuration
class TblPayslipPrintComponent(Base):
	__tablename__ = "tbl_payslip_print_component"
	pay_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
	payscheme_id: Mapped[int] = mapped_column(Integer, nullable=False)
	company_id: Mapped[int] = mapped_column(Integer, nullable=False)
	branch_id: Mapped[int] = mapped_column(Integer, nullable=False)
	component_id: Mapped[int] = mapped_column(Integer, nullable=False)
	desc_print: Mapped[str | None] = mapped_column(String(255), nullable=True)
	payslip_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
	fixed_var_cols: Mapped[str] = mapped_column(String(2), nullable=False)
	total_print: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
	payslip_print: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
	is_active: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
	updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
	updated_date_time: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
