"""
SQLAlchemy ORM models for master tables (*_mst) from the 'sls' database.
Auto-generated from database schema.
"""
from sqlalchemy import (
    Column,
    Integer,
    BigInteger,
    String,
    Text,
    Date,
    DateTime,
    Double,
    Boolean,
    DECIMAL,
    TIMESTAMP,
    Time,
    ForeignKey,
    func,
)
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


# =============================================================================
# APPROVAL MASTER
# =============================================================================
class ApprovalMst(Base):
    """Approval configuration master - defines approval levels and limits per menu/branch/user."""
    __tablename__ = "approval_mst"

    approval_mst_id = Column(Integer, primary_key=True, autoincrement=True)
    menu_id = Column(Integer, ForeignKey("menu_mst.menu_id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("user_mst.user_id"), nullable=False, index=True)
    branch_id = Column(Integer, ForeignKey("branch_mst.branch_id"), nullable=False, index=True)
    approval_level = Column(Integer, nullable=False)
    max_amount_single = Column(Double, nullable=True)
    day_max_amount = Column(Double, nullable=True)
    month_max_amount = Column(Double, nullable=True)
    updated_date_time = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
    updated_by = Column(Integer, nullable=False)


# =============================================================================
# BANK DETAILS MASTER
# =============================================================================
class BankDetailsMst(Base):
    """Bank details master - company bank accounts."""
    __tablename__ = "bank_details_mst"

    bank_detail_id = Column(Integer, primary_key=True, autoincrement=True)
    bank_name = Column(String(255), nullable=False)
    bank_branch = Column(String(255), nullable=False)
    acc_no = Column(String(50), nullable=False)
    ifsc_code = Column(String(25), nullable=False)
    mcr_code = Column(String(25), nullable=True)
    swift_code = Column(String(25), nullable=True)
    co_id = Column(Integer, ForeignKey("co_mst.co_id"), nullable=False, index=True)
    active = Column(Integer, nullable=False, default=1, server_default="1")
    updated_by = Column(Integer, nullable=True)
    updated_date_time = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())


# =============================================================================
# BRANCH MASTER
# =============================================================================
class BranchMst(Base):
    """Branch master - company branch locations with address and GST details."""
    __tablename__ = "branch_mst"

    branch_id = Column(Integer, primary_key=True, autoincrement=True)
    branch_name = Column(String(255), nullable=False)
    co_id = Column(Integer, ForeignKey("co_mst.co_id"), nullable=False, index=True)
    branch_address1 = Column(String(255), nullable=True)
    branch_address2 = Column(String(255), nullable=True)
    branch_zipcode = Column(Integer, nullable=True)
    country_id = Column(Integer, ForeignKey("country_mst.country_id"), nullable=True, index=True)
    state_id = Column(Integer, ForeignKey("state_mst.state_id"), nullable=True, index=True)
    gst_no = Column(String(25), nullable=True)
    contact_no = Column(Integer, nullable=True)
    contact_person = Column(String(255), nullable=True)
    branch_email = Column(String(255), nullable=True)
    active = Column(Boolean, nullable=True)
    gst_verified = Column(Boolean, nullable=True)
    updated_date_time = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
    updated_by = Column(Integer, nullable=False)
    branch_prefix = Column(String(100), nullable=True)


# =============================================================================
# COMPANY MASTER
# =============================================================================
class CoMst(Base):
    """Company master - main company/tenant configuration."""
    __tablename__ = "co_mst"

    co_id = Column(Integer, primary_key=True, autoincrement=True)
    co_name = Column(String(255), nullable=False, unique=True)
    co_prefix = Column(String(25), nullable=False, unique=True)
    co_address1 = Column(String(255), nullable=False)
    co_address2 = Column(String(255), nullable=False)
    co_zipcode = Column(Integer, nullable=False)
    country_id = Column(Integer, ForeignKey("country_mst.country_id"), nullable=False, index=True)
    state_id = Column(Integer, ForeignKey("state_mst.state_id"), nullable=False, index=True)
    co_logo = Column(String(16777215), nullable=True)  # LONGTEXT ~16MB
    auto_datetime_insert = Column(DateTime, nullable=True)
    created_by_con_user = Column(Integer, nullable=True)
    co_cin_no = Column(String(25), nullable=True)
    co_email_id = Column(String(255), nullable=True)
    co_pan_no = Column(String(25), nullable=True)
    s3bucket_name = Column(String(255), nullable=True)
    s3folder_name = Column(String(255), nullable=True)
    tally_sync = Column(String(255), nullable=True)
    alert_email_id = Column(String(255), nullable=True)
    updated_by = Column(Integer, nullable=True)
    updated_date_time = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())


# =============================================================================
# COST FACTOR MASTER
# =============================================================================
class CostFactorMst(Base):
    """Cost factor master - cost allocation factors for inventory/production."""
    __tablename__ = "cost_factor_mst"

    cost_factor_id = Column(Integer, primary_key=True, autoincrement=True)
    cost_factor_name = Column(String(255), nullable=True)
    cost_factor_desc = Column(String(255), nullable=True)
    updated_by = Column(Integer, nullable=False)
    updated_date_time = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
    branch_id = Column(Integer, ForeignKey("branch_mst.branch_id"), nullable=False, index=True)
    dept_id = Column(Integer, ForeignKey("dept_mst.dept_id"), nullable=True, index=True)


# =============================================================================
# COUNTRY MASTER
# =============================================================================
class CountryMst(Base):
    """Country master - list of countries."""
    __tablename__ = "country_mst"

    country_id = Column(Integer, primary_key=True, autoincrement=True)
    country = Column(String(255), nullable=False, unique=True)


# =============================================================================
# CURRENCY MASTER
# =============================================================================
class CurrencyMst(Base):
    """Currency master - currency definitions."""
    __tablename__ = "currency_mst"

    currency_id = Column(Integer, primary_key=True, autoincrement=True)
    currency_prefix = Column(String(25), nullable=True)


# =============================================================================
# DEPARTMENT MASTER
# =============================================================================
class DeptMst(Base):
    """Department master - company departments by branch."""
    __tablename__ = "dept_mst"

    dept_id = Column(Integer, primary_key=True, autoincrement=True)
    branch_id = Column(Integer, ForeignKey("branch_mst.branch_id"), nullable=True, index=True)
    created_by = Column(Integer, nullable=True)
    dept_desc = Column(String(30), nullable=True)
    dept_code = Column(String(30), nullable=True)
    order_id = Column(Integer, nullable=True)
    created_date = Column(DateTime, nullable=False)


# =============================================================================
# DESIGNATION MASTER
# =============================================================================
class DesignationMst(Base):
    """Designation master - employee designations scoped by company and branch.
    Migrated from vowsls.designation with branch_id replacing company_id."""
    __tablename__ = "designation_mst"

    designation_id = Column(BigInteger, primary_key=True, autoincrement=True)
    branch_id = Column(BigInteger, nullable=True, index=True)
    dept_id = Column(BigInteger, nullable=True)
    desig = Column(String(255), nullable=True)
    norms = Column(String(255), nullable=True)
    time_piece = Column(String(255), nullable=True)
    direct_indirect = Column(String(255), nullable=True)
    on_machine = Column(String(255), nullable=True)
    machine_type = Column(String(255), nullable=True)
    no_of_machines = Column(String(255), nullable=True)
    cost_code = Column(String(255), nullable=True)
    cost_description = Column(String(255), nullable=True)
    piece_rate_type = Column(String(255), nullable=True)
    active = Column(Integer, default=1, server_default="1")
    updated_by = Column(Integer, nullable=True)
    updated_date_time = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())


# =============================================================================
# HRMS LEAVE TYPES MASTER
# =============================================================================
class HrmsLeaveTypesMst(Base):
    """HRMS leave types master - defines leave type codes and descriptions per company."""
    __tablename__ = "hrms_leave_types_mst"

    leave_type_id = Column(BigInteger, primary_key=True)
    leave_type_code = Column(String(255), nullable=True)
    leave_type_description = Column(String(255), nullable=True)
    payable = Column(String(255), nullable=True)
    company_id = Column(Integer, nullable=True, index=True)
    is_active = Column(Integer, nullable=True)
    updated_by = Column(BigInteger, nullable=True)
    updated_date_time = Column(DateTime, nullable=True)
    Leave_hours = Column(Double, nullable=True)


# =============================================================================
# WORKER CATEGORY MASTER
# =============================================================================
class CategoryMst(Base):
    """Worker category master - employee worker categories."""
    __tablename__ = "category_mst"

    cata_id = Column(BigInteger, primary_key=True, autoincrement=True)
    cata_code = Column(String(255), nullable=True)
    cata_desc = Column(String(255), nullable=True)
    branch_id = Column(Integer, nullable=True)
    updated_by = Column(Integer, nullable=True)
    updated_date_time = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
    grade_id = Column(Integer, nullable=True)


# =============================================================================
# GRADE MASTER
# =============================================================================
class GradeTable(Base):
    """Employee grade master. grade_type: 0 = Worker, 1 = Staff.
    Legacy table name (grade_table, not *_mst); tenant-wide (no co_id/branch_id)."""
    __tablename__ = "grade_table"

    grade_id = Column(Integer, primary_key=True, autoincrement=True)
    grade_code = Column(String(4), nullable=True)
    grade_name = Column(String(100), nullable=True)
    grade_type = Column(Integer, nullable=True, default=0, server_default="0")


# =============================================================================
# SHIFT MASTER
# =============================================================================
class ShiftMst(Base):
    """Shift master - defines work shifts with timing, week-off, and overtime rules.
    Scoped by branch_id (no co_id column)."""
    __tablename__ = "shift_mst"

    shift_id = Column(Integer, primary_key=True, autoincrement=True)
    shift_name = Column(String(25), nullable=False)
    status = Column(Integer, default=1, server_default="1")
    branch_id = Column(Integer, nullable=True, index=True)
    spell_type = Column(Integer, nullable=True)
    starting_time = Column(Time, nullable=True)
    working_hours = Column(DECIMAL(5, 2), nullable=True)
    minimum_work_hours = Column(DECIMAL(5, 2), nullable=True)
    break_hours = Column(String(10), nullable=True)
    halfday_work_hours = Column(DECIMAL(5, 2), nullable=True)
    late_minutes = Column(Integer, nullable=True)
    late_minutes2 = Column(Integer, nullable=True)
    week_off_day = Column(Integer, nullable=True)
    week_off_day2 = Column(Integer, nullable=True)
    week_off_halfDay = Column(Integer, nullable=True)  # camelCase — production typo, do NOT rename
    is_overnight = Column(Integer, default=0, server_default="0")
    updated_by = Column(Integer, nullable=True)
    update_date_time = Column(TIMESTAMP, nullable=True, server_default=func.current_timestamp())
    end_time = Column(Time, nullable=True)


# =============================================================================
# SPELL MASTER
# =============================================================================
class SpellMst(Base):
    """Spell master - time periods within a shift (e.g. morning, afternoon, night spells).
    Each spell belongs to a shift via shift_id FK."""
    __tablename__ = "spell_mst"

    spell_id = Column(Integer, primary_key=True, autoincrement=True)
    spell_code = Column(String(25), nullable=False, server_default="")
    spell_name = Column(String(25), nullable=False)
    status = Column(Integer, default=1, server_default="1")
    shift_id = Column(Integer, nullable=True, index=True)
    end_time = Column(Time, nullable=True)
    starting_time = Column(Time, nullable=True)
    working_hours = Column(DECIMAL(5, 2), nullable=True)
    minimum_work_hours = Column(DECIMAL(5, 2), nullable=True)
    break_hours = Column(String(10), nullable=True)
    halfday_work_hours = Column(DECIMAL(5, 2), nullable=True)
    late_minutes = Column(Integer, nullable=True)
    late_minutes2 = Column(Integer, nullable=True)
    is_overnight = Column(Integer, default=0, server_default="0")
    updated_by = Column(Integer, nullable=True)
    update_date_time = Column(TIMESTAMP, nullable=True, server_default=func.current_timestamp())


# =============================================================================
# CONTRACTOR MASTER
# =============================================================================
class ContractorMst(Base):
    """Contractor master - contractor registration and details."""
    __tablename__ = "contractor_mst"

    cont_id = Column(Integer, primary_key=True, autoincrement=True)
    address_1 = Column(String(255), nullable=True)
    address_2 = Column(String(255), nullable=True)
    address_3 = Column(String(255), nullable=True)
    bank_acc_no = Column(String(255), nullable=True)
    bank_name = Column(String(25), nullable=True)
    ifsc_code = Column(String(25), nullable=True)
    branch_id = Column(Integer, nullable=True)
    email_id = Column(String(255), nullable=True)
    esi_code = Column(String(25), nullable=True)
    contractor_name = Column(String(50), nullable=True)
    aadhar_no = Column(String(20), nullable=True)
    pan_no = Column(String(25), nullable=True)
    pf_code = Column(String(25), nullable=True)
    phone_no = Column(String(255), nullable=True)
    date_of_registration = Column(Date, nullable=True)
    date_of_registration_mill = Column(Date, nullable=True)
    updated_by = Column(Integer, nullable=True)
    updated_date_time = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())


# =============================================================================
# ENTITY TYPE MASTER
# =============================================================================
class EntityTypeMst(Base):
    """Entity type master - business entity classifications (Individual, Company, etc.)."""
    __tablename__ = "entity_type_mst"

    entity_type_id = Column(Integer, primary_key=True)  # No auto_increment
    entity_type_name = Column(String(30), nullable=True)


# =============================================================================
# EXPENSE TYPE MASTER
# =============================================================================
class ExpenseTypeMst(Base):
    """Expense type master - types of expenses for cost tracking."""
    __tablename__ = "expense_type_mst"

    expense_type_id = Column(Integer, primary_key=True, autoincrement=True)
    expense_type_name = Column(String(45), nullable=True)
    active = Column(Integer, nullable=True)


# =============================================================================
# ITEM GROUP MASTER
# =============================================================================
class ItemGrpMst(Base):
    """Item group master - hierarchical item categorization."""
    __tablename__ = "item_grp_mst"

    item_grp_id = Column(BigInteger, primary_key=True, autoincrement=True)
    parent_grp_id = Column(BigInteger, nullable=True)  # Self-referencing for hierarchy
    active = Column(String(255), nullable=True)
    co_id = Column(Integer, ForeignKey("co_mst.co_id"), nullable=True, index=True)
    updated_by = Column(Integer, nullable=False)
    updated_date_time = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
    item_grp_name = Column(String(255), nullable=True)
    item_grp_code = Column(String(255), nullable=True)
    purchase_code = Column(BigInteger, nullable=True)
    item_type_id = Column(Integer, nullable=True, index=True)


# =============================================================================
# ITEM MIN/MAX MASTER
# =============================================================================
class ItemMinmaxMst(Base):
    """Item min/max master - inventory reorder levels per item/branch."""
    __tablename__ = "item_minmax_mst"

    item_minmax_id = Column(Integer, primary_key=True, autoincrement=True)
    branch_id = Column(Integer, ForeignKey("branch_mst.branch_id"), nullable=True, index=True)
    item_id = Column(Integer, ForeignKey("item_mst.item_id"), nullable=True, index=True)
    minqty = Column(Double, nullable=True)
    maxqty = Column(Double, nullable=True)
    min_order_qty = Column(Double, nullable=True)
    lead_time = Column(Integer, nullable=True)
    updated_by = Column(Integer, nullable=False)
    updated_date_time = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
    active = Column(Integer, nullable=True)


# =============================================================================
# ITEM MASTER
# =============================================================================
class ItemMst(Base):
    """Item master - main inventory item definitions."""
    __tablename__ = "item_mst"

    item_id = Column(Integer, primary_key=True, autoincrement=True)
    active = Column(Integer, nullable=False)
    updated_date_time = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
    updated_by = Column(Integer, nullable=False)
    item_grp_id = Column(BigInteger, ForeignKey("item_grp_mst.item_grp_id"), nullable=True, index=True)
    item_code = Column(String(255), nullable=True)
    tangible = Column(Boolean, nullable=True)
    item_name = Column(String(255), nullable=True)
    item_photo = Column(Text, nullable=True)  # mediumtext
    legacy_item_code = Column(String(255), nullable=True)
    hsn_code = Column(String(255), nullable=True)
    uom_id = Column(Integer, ForeignKey("uom_mst.uom_id"), nullable=True, index=True)
    tax_percentage = Column(Double, nullable=True)
    saleable = Column(Boolean, nullable=True)
    consumable = Column(Boolean, nullable=True)
    purchaseable = Column(Boolean, nullable=True)
    manufacturable = Column(Boolean, nullable=True)
    assembly = Column(Boolean, nullable=True)
    uom_rounding = Column(Integer, nullable=True)
    rate_rounding = Column(Integer, nullable=True)


# =============================================================================
# MACHINE MASTER
# =============================================================================
class MachineMst(Base):
    """Machine master - production machines per department."""
    __tablename__ = "machine_mst"

    machine_id = Column(Integer, primary_key=True, autoincrement=True)
    dept_id = Column(Integer, ForeignKey("dept_mst.dept_id"), nullable=False, index=True)
    machine_name = Column(String(255), nullable=False)
    machine_type_id = Column(Integer, nullable=False)
    updated_by = Column(Integer, nullable=False)
    remarks = Column(String(255), nullable=True)
    updated_date_time = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
    active = Column(Integer, nullable=False)
    mech_posting_code = Column(Integer, nullable=True)
    mech_code = Column(String(100), nullable=False)
    mech_shr_code = Column(String(100), nullable=True)
    line_no = Column(Integer, nullable=True)
    no_of_mechines = Column(Integer, nullable=True)


# =============================================================================
# MACHINE TYPE MASTER
# =============================================================================
class MachineTypeMst(Base):
    """Machine type master - categories of machines."""
    __tablename__ = "machine_type_mst"

    machine_type_id = Column(Integer, primary_key=True, autoincrement=True)
    machine_type_name = Column(String(255), nullable=True, unique=True)
    updated_by = Column(Integer, nullable=False)
    updated_date_time = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
    active = Column(Integer, nullable=False)


# =============================================================================
# MENU MASTER
# =============================================================================
class MenuMst(Base):
    """Menu master - application menu/navigation items."""
    __tablename__ = "menu_mst"

    menu_id = Column(Integer, primary_key=True, autoincrement=True)
    menu_name = Column(String(255), nullable=False, unique=True)
    menu_path = Column(String(255), nullable=True)
    active = Column(Boolean, nullable=False)
    menu_parent_id = Column(Integer, nullable=True)  # Self-referencing for hierarchy
    menu_type_id = Column(Integer, ForeignKey("menu_type_mst.menu_type_id"), nullable=True, index=True)
    menu_icon = Column(String(255), nullable=True)
    module_mst_id = Column(Integer, nullable=True)
    order_by = Column(Integer, nullable=True)


# =============================================================================
# MENU TYPE MASTER
# =============================================================================
class MenuTypeMst(Base):
    """Menu type master - menu classifications."""
    __tablename__ = "menu_type_mst"

    menu_type_id = Column(Integer, primary_key=True, autoincrement=True)
    menu_type = Column(String(25), nullable=False, unique=True)


# =============================================================================
# MODULE MASTER
# =============================================================================
class ModuleMst(Base):
    """Module master - application module definitions."""
    __tablename__ = "module_mst"

    module_mst_id = Column(Integer, primary_key=True, autoincrement=True)
    module_name = Column(String(255), nullable=False, unique=True)
    module_type = Column(Integer, nullable=True)
    active = Column(Boolean, nullable=True)


# =============================================================================
# PARTY BRANCH MASTER
# =============================================================================
class PartyBranchMst(Base):
    """Party branch master - supplier/customer branch locations with GST details."""
    __tablename__ = "party_branch_mst"

    party_mst_branch_id = Column(Integer, primary_key=True, autoincrement=True)
    party_id = Column(Integer, ForeignKey("party_mst.party_id"), nullable=True, index=True)
    active = Column(Integer, nullable=True)
    created_date = Column(DateTime, nullable=True)
    created_by = Column(Integer, nullable=True)
    gst_no = Column(String(255), nullable=True)
    address = Column(String(255), nullable=True)
    address_additional = Column(String(255), nullable=True)
    zip_code = Column(Integer, nullable=True)
    state_id = Column(Integer, ForeignKey("state_mst.state_id"), nullable=True, index=True)
    contact_no = Column(String(25), nullable=True)
    contact_person = Column(String(255), nullable=True)
    updated_by = Column(Integer, nullable=False)
    updated_date_time = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())


# =============================================================================
# PARTY MASTER
# =============================================================================
class PartyMst(Base):
    """Party master - suppliers, customers, and other business partners."""
    __tablename__ = "party_mst"

    party_id = Column(Integer, primary_key=True, autoincrement=True)
    active = Column(Integer, nullable=False)
    prefix = Column(String(25), nullable=True)
    updated_date_time = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
    updated_by = Column(Integer, nullable=False)
    phone_no = Column(String(25), nullable=True)
    cin = Column(String(25), nullable=True)
    co_id = Column(Integer, ForeignKey("co_mst.co_id"), nullable=True, index=True)
    supp_contact_person = Column(String(255), nullable=True)
    supp_contact_designation = Column(String(255), nullable=True)
    supp_email_id = Column(String(255), nullable=True)
    supp_code = Column(String(25), nullable=True)
    party_pan_no = Column(String(255), nullable=True)
    entity_type_id = Column(Integer, ForeignKey("entity_type_mst.entity_type_id"), nullable=True, index=True)
    supp_name = Column(String(255), nullable=True)
    msme_certified = Column(Integer, nullable=True)
    country_id = Column(Integer, ForeignKey("country_mst.country_id"), nullable=True, index=True)
    party_type_id = Column(String(255), nullable=True)  # Stored as comma-separated values


# =============================================================================
# PARTY TYPE MASTER
# =============================================================================
class PartyTypeMst(Base):
    """Party type master - classifications for parties (Supplier, Customer, etc.)."""
    __tablename__ = "party_type_mst"

    party_types_mst_id = Column(Integer, primary_key=True)  # No auto_increment
    party_types_mst_name = Column(String(25), nullable=True)
    party_types_mst_prefix = Column(String(25), nullable=True)
    module_id = Column(Integer, ForeignKey("module_mst.module_mst_id"), nullable=False, index=True)


# =============================================================================
# PROJECT MASTER
# =============================================================================
class ProjectMst(Base):
    """Project master - projects for cost tracking and allocation."""
    __tablename__ = "project_mst"

    project_id = Column(Integer, primary_key=True, autoincrement=True)
    prj_desc = Column(String(255), nullable=True)
    prj_end_dt = Column(Date, nullable=True)
    prj_name = Column(String(255), nullable=True)
    prj_start_dt = Column(Date, nullable=True)
    status_id = Column(Integer, ForeignKey("status_mst.status_id"), nullable=True, index=True)
    active = Column(Integer, nullable=False)
    branch_id = Column(Integer, ForeignKey("branch_mst.branch_id"), nullable=True, index=True)
    updated_by = Column(Integer, nullable=True)
    updated_date_time = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
    party_id = Column(Integer, ForeignKey("party_mst.party_id"), nullable=True, index=True)
    dept_id = Column(Integer, ForeignKey("dept_mst.dept_id"), nullable=True, index=True)


# =============================================================================
# ROLES MASTER
# =============================================================================
class RolesMst(Base):
    """Roles master - user role definitions."""
    __tablename__ = "roles_mst"

    role_id = Column(Integer, primary_key=True, autoincrement=True)
    role_name = Column(String(255), nullable=False, unique=True)
    active = Column(Boolean, nullable=True)
    updated_by_con_user = Column(Integer, nullable=True)
    updated_date_time = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())


# =============================================================================
# STATE MASTER
# =============================================================================
class StateMst(Base):
    """State master - states/provinces by country."""
    __tablename__ = "state_mst"

    state_id = Column(Integer, primary_key=True, autoincrement=True)
    state = Column(String(255), nullable=False, unique=True)
    state_code = Column(String(3), nullable=True)
    country_id = Column(Integer, ForeignKey("country_mst.country_id"), nullable=False, index=True)


# =============================================================================
# STATUS MASTER
# =============================================================================
class StatusMst(Base):
    """Status master - transaction/document status definitions."""
    __tablename__ = "status_mst"

    status_id = Column(Integer, primary_key=True, autoincrement=True)
    status_name = Column(String(255), nullable=True)
    created_date = Column(DateTime, nullable=True)
    created_by = Column(Integer, nullable=True)
    status_grp = Column(String(255), nullable=True)


# =============================================================================
# SUB-DEPARTMENT MASTER
# =============================================================================
class SubDeptMst(Base):
    """Sub-department master - sub-departments within departments."""
    __tablename__ = "sub_dept_mst"

    sub_dept_id = Column(Integer, primary_key=True, autoincrement=True)
    updated_by = Column(Integer, nullable=False)
    sub_dept_code = Column(String(25), nullable=True)
    sub_dept_desc = Column(String(30), nullable=True)
    dept_id = Column(Integer, ForeignKey("dept_mst.dept_id"), nullable=True, index=True)
    updated_date_time = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
    order_no = Column(Integer, nullable=True)


# =============================================================================
# TAX MASTER
# =============================================================================
class TaxMst(Base):
    """Tax master - tax rate definitions."""
    __tablename__ = "tax_mst"

    tax_id = Column(BigInteger, primary_key=True)  # No auto_increment
    updated_by = Column(Integer, nullable=False)
    updated_date_time = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
    tax_name = Column(String(255), nullable=True)
    tax_percentage = Column(DECIMAL(10, 2), nullable=True)
    is_active = Column(Boolean, nullable=False)
    tax_type_id = Column(Integer, ForeignKey("tax_type_mst.tax_type_id"), nullable=True, index=True)


# =============================================================================
# TAX TYPE MASTER
# =============================================================================
class TaxTypeMst(Base):
    """Tax type master - tax classifications (GST, VAT, etc.)."""
    __tablename__ = "tax_type_mst"

    tax_type_id = Column(Integer, primary_key=True, autoincrement=True)
    tax_type_name = Column(String(255), nullable=True, unique=True)


# =============================================================================
# TDS MASTER
# =============================================================================
class TdsMst(Base):
    """TDS master - Tax Deducted at Source configurations."""
    __tablename__ = "tds_mst"

    tds_id = Column(Integer, primary_key=True, autoincrement=True)
    tds_name = Column(String(25), nullable=True)
    tds_percentage = Column(Double, nullable=True)
    tds_single_transaction = Column(Double, nullable=True)
    tds_ytd_transaction = Column(Double, nullable=True)
    tds_entity_type_id = Column(String(25), nullable=True)  # Stored as comma-separated values


# =============================================================================
# UOM ITEM MAP MASTER
# =============================================================================
class UomItemMapMst(Base):
    """UOM item mapping master - unit of measure conversions per item."""
    __tablename__ = "uom_item_map_mst"

    uom_item_map_id = Column(Integer, primary_key=True, autoincrement=True)
    item_id = Column(Integer, ForeignKey("item_mst.item_id"), nullable=True, index=True)
    map_from_id = Column(Integer, ForeignKey("uom_mst.uom_id"), nullable=True, index=True)
    map_to_id = Column(Integer, ForeignKey("uom_mst.uom_id"), nullable=True, index=True)
    is_fixed = Column(Integer, nullable=True)
    relation_value = Column(Double, nullable=True)
    rounding = Column(Integer, nullable=True)
    updated_by = Column(Integer, nullable=False)
    updated_date_time = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())


# =============================================================================
# UOM MASTER
# =============================================================================
class UomMst(Base):
    """UOM master - units of measure definitions."""
    __tablename__ = "uom_mst"

    uom_id = Column(Integer, primary_key=True, autoincrement=True)
    active = Column(Boolean, nullable=False)
    uom_name = Column(String(255), nullable=True)
    updated_by = Column(Integer, nullable=False)
    updated_date_time = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())


# =============================================================================
# USER MASTER
# =============================================================================
class UserMst(Base):
    """User master - application user accounts."""
    __tablename__ = "user_mst"

    user_id = Column(Integer, primary_key=True, autoincrement=True)
    email_id = Column(String(255), nullable=False, unique=True)
    name = Column(String(255), nullable=True)
    password = Column(String(255), nullable=True)
    refresh_token = Column(String(255), nullable=True)
    active = Column(Boolean, nullable=False)
    updated_by_con_user = Column(Integer, nullable=False)
    updated_date_time = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())


# =============================================================================
# WAREHOUSE MASTER
# =============================================================================
class WarehouseMst(Base):
    """Warehouse master - storage locations per branch."""
    __tablename__ = "warehouse_mst"

    warehouse_id = Column(Integer, primary_key=True, autoincrement=True)
    warehouse_name = Column(String(30), nullable=True)
    updated_date_time = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
    updated_by = Column(Integer, nullable=True)
    warehouse_type = Column(String(20), nullable=True)
    branch_id = Column(Integer, ForeignKey("branch_mst.branch_id"), nullable=True, index=True)
    parent_warehouse_id = Column(Integer, nullable=True)  # Self-referencing for hierarchy


# =============================================================================
# ADDITIONAL CHARGES MASTER
# =============================================================================
class AdditionalChargesMst(Base):
    """Additional charges master - defines extra charges like freight, insurance, etc."""
    __tablename__ = "additional_charges_mst"

    additional_charges_id = Column(Integer, primary_key=True, autoincrement=True)
    additional_charges_name = Column(String(100), nullable=True)
    default_value = Column(Double, nullable=True)  # Default tax percentage
    active = Column(Boolean, nullable=True, default=True)
    updated_date_time = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
    updated_by = Column(Integer, nullable=True)
