from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime, TIMESTAMP, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy import Float

# Create Base class for SQLAlchemy ORM
Base = declarative_base()

class ConUser(Base):
    __tablename__ = "user_mst"

    user_id = Column(Integer, primary_key=True, autoincrement=True)
    email_id = Column(String(255), nullable=False, unique=True)
    name = Column(String(255))
    password = Column(String(255))
    refresh_token = Column(String(255))
    active = Column(Boolean, nullable=False)
    updated_by_con_user = Column(Integer)
    updated_date_time = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())

class conRoleMaster(Base):
    __tablename__ = "roles_mst"

    role_id = Column(Integer, primary_key=True, autoincrement=True)
    role_name = Column(String(255), nullable=False, unique=True)
    active = Column(Boolean)
    updated_by_con_user = Column(Integer)
    updated_date_time = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())

class ConRoleMenuMap(Base):
    __tablename__ = "role_menu_map"

    role_menu_mapping_id = Column(Integer, primary_key=True, autoincrement=True)
    role_id = Column(Integer, ForeignKey('roles_mst.role_id'), nullable=False)
    menu_id = Column(Integer, nullable=False)
    access_type_id = Column(Integer, nullable=False)
    updated_by = Column(Integer)
    role = relationship('conRoleMaster', backref='menu_mappings')

class UserRoleMap(Base):
    __tablename__ = "user_role_map"

    user_role_map_id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("user_mst.user_id"), nullable=False)
    role_id = Column(Integer, ForeignKey("roles_mst.role_id"), nullable=False)
    co_id = Column(Integer, ForeignKey("co_mst.co_id"), nullable=False)
    branch_id = Column(Integer, ForeignKey("branch_mst.branch_id"), nullable=False)
    updated_by_con_user = Column(Integer)
    updated_date_time = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())

    user = relationship("ConUser", foreign_keys=[user_id], backref="role_maps")


class CoMst(Base):
    __tablename__ = "co_mst"

    co_id = Column(Integer, primary_key=True, autoincrement=True)
    co_name = Column(String(255), nullable=False, unique=True)
    co_prefix = Column(String(25), nullable=False, unique=True)
    co_address1 = Column(String(255), nullable=False)
    co_address2 = Column(String(255))
    co_zipcode = Column(Integer, nullable=False)
    country_id = Column(Integer, ForeignKey("country_mst.country_id"), nullable=False)
    state_id = Column(Integer, ForeignKey("state_mst.state_id"), nullable=False)
    co_logo = Column(String(255))
    auto_datetime_insert = Column(DateTime, default=func.now())
    created_by_con_user = Column(Integer)
    co_cin_no = Column(String(25))
    co_email_id = Column(String(255))
    co_pan_no = Column(String(25))
    s3bucket_name = Column(String(255))
    s3folder_name = Column(String(255))
    tally_sync = Column(String(255))
    alert_email_id = Column(String(255))

    country = relationship("CountryMst", foreign_keys=[country_id])
    state = relationship("StateMst", foreign_keys=[state_id])


class BranchMst(Base):
    __tablename__ = "branch_mst"

    branch_id = Column(Integer, primary_key=True, autoincrement=True)
    branch_name = Column(String(255), nullable=False, unique=True)
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
    active = Column(Boolean)
    gst_verified = Column(Boolean)
    co = relationship("CoMst", foreign_keys=[co_id])
    country = relationship("CountryMst", foreign_keys=[country_id])
    state  = relationship("StateMst",  foreign_keys=[state_id])


class CountryMst(Base):
    __tablename__ = "country_mst"

    country_id = Column(Integer, primary_key=True, autoincrement=True)
    country = Column(String(255), nullable=False, unique=True)

    states = relationship("StateMst", back_populates="country")


class StateMst(Base):
    __tablename__ = "state_mst"

    state_id = Column(Integer, primary_key=True, autoincrement=True)
    state = Column(String(255), nullable=False, unique=True)
    country_id = Column(Integer, ForeignKey("country_mst.country_id"), nullable=False)

    country = relationship("CountryMst", back_populates="states")


class ApprovalMst(Base):
    __tablename__ = "approval_mst"

    approval_mst_id   = Column(Integer, primary_key=True, autoincrement=True)
    menu_id           = Column(Integer, ForeignKey("menu_mst.menu_id"),   nullable=False)
    user_id           = Column(Integer, ForeignKey("user_mst.user_id"),   nullable=False)
    branch_id         = Column(Integer, ForeignKey("branch_mst.branch_id"), nullable=False)
    approval_level    = Column(Integer, nullable=False)
    max_amount_single = Column(Float)
    day_max_amount    = Column(Float)
    month_max_amount  = Column(Float)
    updated_by        = Column(Integer, nullable=False)
    updated_date_time = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())

    # relationships
    menu   = relationship("MenuMst",   foreign_keys=[menu_id])
    user   = relationship("ConUser",   foreign_keys=[user_id])
    branch = relationship("BranchMst", foreign_keys=[branch_id])
    class MenuMst(Base):
        __tablename__ = "menu_mst"

        menu_id        = Column(Integer, primary_key=True, autoincrement=True)
        menu_name      = Column(String(255), nullable=False, unique=True)
        menu_path      = Column(String(255))
        active         = Column(Boolean, nullable=False)
        menu_parent_id = Column(Integer, ForeignKey("menu_mst.menu_id"))
        menu_type_id   = Column(Integer)
        menu_icon      = Column(String(255))
        module_mst_id  = Column(Integer)

        parent   = relationship("MenuMst", remote_side=[menu_id],
                                backref="children", foreign_keys=[menu_parent_id])

