from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, Integer, String, Boolean, DateTime, TIMESTAMP, ForeignKey, func
from sqlalchemy.orm import relationship

Base = declarative_base()

class ConMenuMaster(Base):
    __tablename__ = 'con_menu_master'

    con_menu_id = Column(Integer, primary_key=True, autoincrement=True)
    con_menu_name = Column(String(25), nullable=False)
    con_menu_parent_id = Column(Integer, nullable=True)
    active = Column(Boolean, default=True)
    con_menu_path = Column(String(255), nullable=True)
    con_menu_icon = Column(String(255), nullable=True)
    order_by = Column(Integer, nullable=True)

    def __repr__(self):
        return f"<ConMenuMaster(id={self.con_menu_id}, name='{self.con_menu_name}')>"

class ConRoleMenuMap(Base):
    __tablename__ = 'con_role_menu_map'

    con_role_menu_mapping_id = Column(Integer, primary_key=True, autoincrement=True)
    con_role_id = Column(Integer, ForeignKey('con_role_master.con_role_id'), nullable=False)
    con_menu_id = Column(Integer, ForeignKey('con_menu_master.con_menu_id'), nullable=False)

    menu = relationship('ConMenuMaster', backref='role_mappings')
    role = relationship('conRoleMaster', backref='menu_mappings')

    def __repr__(self):
        return (f"<ConRoleMenuMap(id={self.con_role_menu_mapping_id}, "
                f"role_id={self.con_role_id}, menu_id={self.con_menu_id})>")

class ConUser(Base):
    __tablename__ = "con_user_master"

    con_user_id = Column(Integer, primary_key=True, autoincrement=True)
    con_org_id = Column(Integer, ForeignKey('con_org_master.con_org_id'), nullable=True, index=True)
    con_user_login_email_id = Column(String(50), nullable=False)
    con_user_login_password = Column(String(500), nullable=False)
    con_user_name = Column(String(30), nullable=False)
    con_user_type = Column(Integer, nullable=False)
    created_by = Column(Integer, nullable=True)
    created_date_time = Column(DateTime, nullable=True, server_default=func.current_timestamp())
    active = Column(Integer, nullable=False, default=1)
    refresh_token = Column(String(255), nullable=True)

class ConOrgMaster(Base):
    __tablename__ = "con_org_master"

    con_org_id = Column(Integer, primary_key=True, autoincrement=True)
    con_org_name = Column(String(50), nullable=True)
    con_org_shortname = Column(String(10), nullable=True)
    con_org_email_id = Column(String(100), nullable=True)
    con_org_mobile = Column(String(20), nullable=True)
    con_org_contact_person = Column(String(30), nullable=True)
    con_org_address = Column(String(250), nullable=True)
    con_org_pincode = Column(Integer, nullable=True)
    con_org_main_url = Column(String(100), nullable=True)
    con_org_state_id = Column(Integer, nullable=True)
    con_org_master_status = Column(Integer, nullable=True)
    con_org_remarks = Column(String(250), nullable=True)
    con_modules_selected = Column(JSON, nullable=True)
    created_by = Column(Integer, nullable=True)
    created_date_time = Column(DateTime, nullable=True, server_default=func.current_timestamp())
    active = Column(Integer, nullable=True, default=1)

class conRoleMaster(Base):
    __tablename__ = "con_role_master"

    con_role_id = Column(Integer, primary_key=True, autoincrement=True)
    con_role_name = Column(String(50), nullable=False)
    con_org_id = Column(Integer, ForeignKey('con_org_master.con_org_id'), nullable=True)
    status = Column(Integer, nullable=False)
    created_by = Column(Integer, nullable=True)
    created_date_time = Column(DateTime, nullable=True, server_default=func.current_timestamp())
    con_company_id = Column(Integer, nullable=True)
    is_enable = Column(Integer, nullable=False, default=1)

class ConUserRoleMapping(Base):
    __tablename__ = "con_user_role_mapping"

    con_user_role_mapping_id = Column(Integer, primary_key=True, autoincrement=True)
    con_role_id = Column(Integer, ForeignKey('con_role_master.con_role_id'), nullable=False, index=True)
    con_user_id = Column(Integer, ForeignKey('con_user_master.con_user_id'), nullable=False, index=True)
    created_by = Column(Integer, nullable=False, index=True)
    created_date_time = Column(DateTime, nullable=True, server_default=func.now())


class CoMst(Base):
    __tablename__ = "co_mst"

    co_id = Column(Integer, primary_key=True, autoincrement=True)
    co_name = Column(String(255), nullable=False, unique=True)
    co_prefix = Column(String(25), nullable=False, unique=True)
    co_address1 = Column(String(255))
    co_address2 = Column(String(255))
    co_zipcode = Column(Integer)
    country_id = Column(Integer, ForeignKey("country_mst.country_id"))
    state_id = Column(Integer, ForeignKey("state_mst.state_id"))
    city_id = Column(Integer, nullable=True)
    co_logo = Column(String(255))
    auto_datetime_insert = Column(DateTime, server_default=func.current_timestamp())
    co_cin_no = Column(String(25))
    co_email_id = Column(String(255))
    co_pan_no = Column(String(25))
    s3bucket_name = Column(String(255))
    s3folder_name = Column(String(255))
    tally_sync = Column(String(255))
    alert_email_id = Column(String(255))

    # Relationships
    country = relationship("CountryMst", backref="companies")
    state = relationship("StateMst", backref="companies")
    def __repr__(self):
        return f"<CoMst(id={self.co_id}, name='{self.co_name}')>"




class BranchMst(Base):
    __tablename__ = "branch_mst"

    branch_id = Column(Integer, primary_key=True, autoincrement=True)
    branch_name = Column(String(255), nullable=False, unique=True)
    branch_prefix = Column(String(100))
    co_id = Column(Integer, ForeignKey("co_mst.co_id"), nullable=False)
    branch_address1 = Column(String(255))
    branch_address2 = Column(String(255))
    branch_zipcode = Column(Integer)
    country_id = Column(Integer, ForeignKey("country_mst.country_id"))
    state_id = Column(Integer, ForeignKey("state_mst.state_id"))
    gst_no = Column(String(25))
    contact_no = Column(Integer)
    contact_person = Column(String(255))
    branch_email = Column(String(255))
    active = Column(Boolean, default=True)
    gst_verified = Column(Boolean, default=False)
    updated_by = Column(Integer, nullable=False)

    def __repr__(self):
        return f"<BranchMst(id={self.branch_id}, name='{self.branch_name}')>"
class CountryMst(Base):
    __tablename__ = "country_mst"

    country_id = Column(Integer, primary_key=True, autoincrement=True)
    country = Column(String(255), nullable=False, unique=True)

    def __repr__(self):
        return f"<CountryMst(id={self.country_id}, country='{self.country}')>"


class StateMst(Base):
    __tablename__ = "state_mst"

    state_id = Column(Integer, primary_key=True, autoincrement=True)
    state = Column(String(255), nullable=False, unique=True)
    country_id = Column(Integer, ForeignKey("country_mst.country_id"), nullable=False)

    # Relationships
    country = relationship("CountryMst", backref="states")

    def __repr__(self):
        return f"<StateMst(id={self.state_id}, state='{self.state}', country_id={self.country_id})>"


class DeptMst(Base):
    __tablename__ = 'dept_mst'

    dept_id = Column(Integer, primary_key=True, autoincrement=True)
    branch_id = Column(Integer, ForeignKey('branch_mst.branch_id'), nullable=True)
    created_by = Column(Integer, nullable=True)
    dept_desc = Column(String(30), nullable=True)
    dept_code = Column(String(30), nullable=True)
    order_id = Column(Integer, nullable=True)
    created_date = Column(DateTime, nullable=False, default=func.now())

    # Relationship with BranchMst
    # branch = relationship("BranchMst", back_populates="departments")

    def __repr__(self):
        return f"<DeptMst(dept_id={self.dept_id}, dept_desc='{self.dept_desc}')>"
    


class CoConfig(Base):
    __tablename__ = "co_config"
    co_id = Column(Integer, ForeignKey("co_mst.co_id"), primary_key=True)
    currency_id = Column(Integer, ForeignKey("currency_mst.currency_id"))
    india_gst = Column(Boolean, default=False)
    india_tds = Column(Boolean, default=False)
    india_tcs = Column(Boolean, default=False)
    back_date_allowable = Column(Boolean, default=False)
    indent_required = Column(Boolean, default=False)
    po_required = Column(Boolean, default=False)
    material_inspection = Column(Boolean, default=False)
    quotation_required = Column(Boolean, default=False)
    do_required = Column(Boolean, default=False)
    gst_linked = Column(Boolean, default=False)
    updated_by = Column(Integer, nullable=True)
    updated_date_time = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())

    # Relationships
    company = relationship("CoMst", backref="config")
    currency = relationship("CurrencyMst", backref="co_configs")

class CurrencyMst(Base):
    __tablename__ = "currency_mst"
    currency_id = Column(Integer, primary_key=True, autoincrement=True)
    currency_prefix = Column(String(25), nullable=False)




