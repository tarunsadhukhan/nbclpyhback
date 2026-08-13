
from sqlalchemy import Column, Integer, BigInteger, String, Boolean, ForeignKey, DateTime, func, Date, JSON, Text
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import relationship, Mapped, mapped_column
from sqlalchemy import Float, Double

try:
    from src.common.companyAdmin.models import CoMst
except Exception:
    # optional import: some test environments may not have src.common dependencies available
    CoMst = None


Base = declarative_base()

class ItemGrpMst(Base):
    __tablename__ = "item_grp_mst"

    item_grp_id = Column(BigInteger, primary_key=True, autoincrement=True)
    parent_grp_id = Column(BigInteger, nullable=True)
    active = Column(String(255), nullable=True)
    co_id = Column(Integer, nullable=True)
    # co_id = Column(Integer, ForeignKey("co_mst.co_id"))
    updated_by = Column(Integer, nullable=False)
    updated_date_time = Column(DateTime, nullable=False, default=func.now())
    item_grp_name = Column(String(255), nullable=True)
    item_grp_code = Column(String(255), nullable=True)
    purchase_code = Column(BigInteger, nullable=True)
    item_type_id = Column(Integer, nullable=True)
    # item_type_id = Column(Integer, ForeignKey("item_type_master.item_type_id"))

    # co = relationship("CoMst", foreign_keys=[co_id])
    # item_type = relationship("ItemTypeMaster", foreign_keys=[item_type_id])

class ItemMake(Base):
    __tablename__ = "item_make"

    item_make_id = Column(Integer, primary_key=True, autoincrement=True)
    item_make_name = Column(String(255), nullable=True)
    item_grp_id = Column(BigInteger, ForeignKey("item_grp_mst.item_grp_id"), nullable=True)
    updated_by = Column(Integer, nullable=False)
    updated_date_time = Column(DateTime, nullable=False, default=func.now())

    # item_group = relationship("ItemGrpMst", foreign_keys=[item_grp_id])

class ItemMst(Base):
    __tablename__ = "item_mst"
    item_id = Column(Integer, primary_key=True, autoincrement=True)
    active = Column(Integer, nullable=False, default=1)
    updated_date_time = Column(DateTime, nullable=False, default=func.now())
    updated_by = Column(Integer, nullable=False)
    item_grp_id = Column(BigInteger, ForeignKey("item_grp_mst.item_grp_id"), nullable=True)
    item_code = Column(String(255), nullable=True)
    tangible = Column(Boolean, nullable=True)
    item_name = Column(String(255), nullable=True)
    item_photo = Column(String(16777215), nullable=True)  # MEDIUMTEXT equivalent
    legacy_item_code = Column(String(255), nullable=True)
    hsn_code = Column(String(255), nullable=True)
    uom_id = Column(Integer, ForeignKey("uom_mst.uom_id"), nullable=True)
    tax_percentage = Column(Float, nullable=True)
    saleable = Column(Boolean, nullable=True)
    consumable = Column(Boolean, nullable=True)
    purchaseable = Column(Boolean, nullable=True)
    manufacturable = Column(Boolean, nullable=True)
    assembly = Column(Boolean, nullable=True)
    uom_rounding = Column(Integer, nullable=True)
    rate_rounding = Column(Integer, nullable=True)
    # item_group = relationship("ItemGrpMst", foreign_keys=[item_grp_id])
    # uom = relationship("UomMst", foreign_keys=[uom_id])

class ItemTypeMaster(Base):
    __tablename__ = "item_type_master"
    item_type_id = Column(Integer, primary_key=True, autoincrement=True)
    item_type_name = Column(String(25), unique=True, nullable=True)
    updated_by = Column(Integer, nullable=False)
    updated_date_time = Column(DateTime, nullable=False, default=func.now())
    # optional reverse relation
    # item_groups = relationship("ItemGrpMst", back_populates="item_type")


class UomMst(Base):
    __tablename__ = "uom_mst"

    uom_id = Column(Integer, primary_key=True, autoincrement=True)
    active = Column(Boolean, nullable=False, default=True)
    uom_name = Column(String(255), nullable=True)
    updated_by = Column(Integer, nullable=False)
    updated_date_time = Column(DateTime, nullable=False, default=func.now())


class ItemMinmaxMst(Base):
    __tablename__ = "item_minmax_mst"

    item_minmax_id = Column(Integer, primary_key=True, autoincrement=True)
    branch_id = Column(Integer, ForeignKey("branch_mst.branch_id"), nullable=True)
    item_id = Column(Integer, ForeignKey("item_mst.item_id"), nullable=True)
    minqty = Column(Float, nullable=True)
    maxqty = Column(Float, nullable=True)
    min_order_qty = Column(Float, nullable=True)
    lead_time = Column(Integer, nullable=True)
    updated_by = Column(Integer, nullable=False)
    updated_date_time = Column(DateTime, nullable=False, default=func.now())
    active = Column(Integer, nullable=True, default=1)

    # branch = relationship("BranchMst", foreign_keys=[branch_id])
    # item = relationship("ItemMst", foreign_keys=[item_id])


class UomItemMapMst(Base):
    __tablename__ = "uom_item_map_mst"

    uom_item_map_id = Column(Integer, primary_key=True, autoincrement=True)
    item_id = Column(Integer, ForeignKey("item_mst.item_id"), nullable=True)
    map_from_id = Column(Integer, ForeignKey("uom_mst.uom_id"), nullable=True)
    map_to_id = Column(Integer, ForeignKey("uom_mst.uom_id"), nullable=True)
    is_fixed = Column(Integer, nullable=True)  # 1 = fixed, 0 = variable
    relation_value = Column(Float, nullable=True)
    rounding = Column(Integer, nullable=True)
    updated_by = Column(Integer, nullable=False)
    updated_date_time = Column(DateTime, nullable=False, default=func.now())

    # item = relationship("ItemMst", foreign_keys=[item_id])
    # map_from = relationship("UomMst", foreign_keys=[map_from_id])
    # map_to = relationship("UomMst", foreign_keys=[map_to_id])

                
                
class DeptMst(Base):
    __tablename__ = 'dept_mst'

    dept_id = Column(Integer, primary_key=True, autoincrement=True)
    branch_id = Column(Integer, nullable=True)
    created_by = Column(Integer, nullable=True)
    dept_desc = Column(String(30), nullable=True)
    dept_code = Column(String(30), nullable=True)
    order_id = Column(Integer, nullable=True)
    created_date = Column(DateTime, nullable=False, default=func.now())
    updated_by = Column(Integer, nullable=True)
    updated_date_time = Column(DateTime, nullable=True)
    # 1 = Worker, 2 = Staff (DB column is `Worker_staff`)
    worker_staff = Column("Worker_staff", Integer, nullable=True, default=1)

 #   def __repr__(self):
        # include branch_id and dept_code for easier debugging
 #       return (f"<DeptMst(dept_id={self.dept_id}, branch_id={self.branch_id}, "
 #               f"dept_code={self.dept_code!r}, dept_desc={self.dept_desc!r})>")

# ...existing code...


# ...existing code...
class SubDeptMst(Base):
    __tablename__ = "sub_dept_mst"

    sub_dept_id = Column(Integer, primary_key=True, autoincrement=True)
    updated_by = Column(Integer, nullable=False)
    sub_dept_code = Column(String(25), nullable=True)
    sub_dept_desc = Column(String(30), nullable=True)
    dept_id = Column(Integer, nullable=True)
    updated_date_time = Column(DateTime, nullable=False, default=func.now())
    order_no = Column(Integer, nullable=True)

    # optional relationship to DeptMst
#    dept = relationship("DeptMst", foreign_keys=[dept_id])

#    def __repr__(self):
#        return f"<SubDeptMst(sub_dept_id={self.sub_dept_id}, dept_id={self.dept_id}, code={self.sub_dept_code!r})>"

class MachineTypeMst(Base):
    __tablename__ = "machine_type_mst"

    machine_type_id = Column(Integer, primary_key=True, autoincrement=True)
    machine_type_name = Column(String(255), nullable=True)
    updated_by = Column(Integer, nullable=False)
    updated_date_time = Column(DateTime, nullable=False, default=func.now())
    active = Column(Integer, nullable=False, default=1)

    # relationship to DeptMst (optional, convenient for joins)
    #dept = relationship("DeptMst", foreign_keys=[dept_id])


class MachineMst(Base):
    __tablename__ = "machine_mst"

    machine_id = Column(Integer, primary_key=True, autoincrement=True)
    dept_id = Column(Integer, ForeignKey("dept_mst.dept_id"), nullable=False)
    machine_name = Column(String(255), nullable=False)
    machine_type_id = Column(Integer, nullable=False)
    updated_by = Column(Integer, nullable=False)
    remarks = Column(String(255), nullable=True)
    updated_date_time = Column(DateTime, nullable=False, default=func.now())
    active = Column(Integer, nullable=False, default=1)
    mech_posting_code = Column(Integer, nullable=True)
    mech_code = Column(String(100), nullable=False)

    # relationships
  #  dept = relationship("DeptMst", foreign_keys=[dept_id])
  #  machine_type = relationship("MachineTypeMst", foreign_keys=[machine_type_id])

class ProjectMst(Base):
    __tablename__ = "project_mst"

    project_id = Column(Integer, primary_key=True, autoincrement=True)
    prj_desc = Column(String(255), nullable=True)
    prj_end_dt = Column(Date, nullable=True)
    prj_name = Column(String(255), nullable=True)
    prj_start_dt = Column(Date, nullable=True)
    status_id = Column(Integer, nullable=True)
    active = Column(Integer, nullable=False, default=1)
    branch_id = Column(Integer, nullable=True)
    updated_by = Column(Integer, nullable=True)
    updated_date_time = Column(DateTime, nullable=True)
    party_id = Column(Integer, nullable=True)
    dept_id = Column(Integer, nullable=True)

    # optional relationships for convenience
 #   status = relationship("StatusMst", foreign_keys=[status_id], lazy="joined")
 #   branch = relationship("BranchMst", foreign_keys=[branch_id], lazy="joined")
 #   party = relationship("PartyMst", foreign_keys=[party_id], lazy="joined")
 #   dept = relationship("DeptMst", foreign_keys=[dept_id], lazy="joined")

 #   def __repr__(self):
 #       return f"<ProjectMst(project_id={self.project_id}, prj_name={self.prj_name!r})>"
# ...existing code...


class PartyMst(Base):
    __tablename__ = "party_mst"

    party_id = Column(Integer, primary_key=True, autoincrement=True)
    active = Column(Integer, nullable=False, default=1)
    prefix = Column(String(25), nullable=True)
    updated_date_time = Column(DateTime, nullable=False, default=func.now())
    updated_by = Column(Integer, nullable=False)
    phone_no = Column(String(25), nullable=True)
    cin = Column(String(25), nullable=True)
    co_id = Column(Integer, nullable=True)
    supp_contact_person = Column(String(255), nullable=True)
    supp_contact_designation = Column(String(255), nullable=True)
    supp_email_id = Column(String(255), nullable=True)
    supp_code = Column(String(25), nullable=True)
    party_pan_no = Column(String(255), nullable=True)
    entity_type_id = Column(Integer, nullable=True)
    supp_name = Column(String(255), nullable=True)
    msme_certified = Column(Integer, nullable=True)  # 1 = certified, 0 = not certified
    country_id = Column(Integer, nullable=True)
    party_type_id = Column(String(255), nullable=True)

    # Relationships (optional, only if the related models exist)
    # company = relationship("CoMst", foreign_keys=[co_id])
    # entity_type = relationship("EntityTypeMst", foreign_keys=[entity_type_id])
    # country = relationship("CountryMst", foreign_keys=[country_id])
    branches = relationship(
    "PartyBranchMst",
    back_populates="party",
    cascade="all, delete-orphan",
    passive_deletes=True,
    )

class PartyBranchMst(Base):
    __tablename__ = "party_branch_mst"

    party_mst_branch_id = Column(Integer, primary_key=True, autoincrement=True)
    party_id = Column(Integer, ForeignKey("party_mst.party_id"), nullable=True)
    active = Column(Integer, nullable=True)
    created_date = Column(DateTime, nullable=True)
    created_by = Column(Integer, nullable=True)
    gst_no = Column(String(255), nullable=True)
    address = Column(String(255), nullable=True)
    address_additional = Column(String(255), nullable=True)
    zip_code = Column(Integer, nullable=True)
    state_id = Column(Integer, nullable=True)
    contact_no = Column(String(25), nullable=True)
    contact_person = Column(String(255), nullable=True)
    updated_by = Column(Integer, nullable=False)
    updated_date_time = Column(DateTime, nullable=False, default=func.now())

    party = relationship("PartyMst", back_populates="branches")


class EntityTypeMst(Base):
    __tablename__ = "entity_type_mst"

    entity_type_id = Column(Integer, primary_key=True)
    entity_type_name = Column(String(30), nullable=True)


class WarehouseMst(Base):
    __tablename__ = "warehouse_mst"

    warehouse_id = Column(Integer, primary_key=True, autoincrement=True)
    warehouse_name = Column(String(30), nullable=True)
    updated_date_time = Column(DateTime, nullable=True)
    updated_by = Column(Integer, nullable=True)
    warehouse_type = Column(String(20), nullable=True)
    branch_id = Column(Integer, nullable=True)
    parent_warehouse_id = Column(Integer, nullable=True)

    # branch = relationship("BranchMst", foreign_keys=[branch_id])
    # Optionally, add relationship for parent warehouse if needed
    # parent_warehouse = relationship("WarehouseMst", remote_side=[warehouse_id])

class ItemBom(Base):
    __tablename__ = "item_bom"

    bom_id = Column(Integer, primary_key=True, autoincrement=True)
    parent_item_id = Column(Integer, ForeignKey("item_mst.item_id"), nullable=False)
    child_item_id = Column(Integer, ForeignKey("item_mst.item_id"), nullable=False)
    additional_description = Column(Text, nullable=True)
    qty = Column(Float, nullable=False, default=1)
    uom_id = Column(Integer, ForeignKey("uom_mst.uom_id"), nullable=False)
    co_id = Column(Integer, nullable=False)
    sequence_no = Column(Integer, default=0)
    active = Column(Integer, nullable=False, default=1)
    updated_by = Column(Integer, nullable=True)
    updated_date_time = Column(DateTime, nullable=True)


class CostFactorMst(Base):
    __tablename__ = "cost_factor_mst"

    cost_factor_id = Column(Integer, primary_key=True, autoincrement=True)
    cost_factor_name = Column(String(255), nullable=True)
    cost_factor_desc = Column(String(255), nullable=True)
    updated_by = Column(Integer, nullable=False)
    updated_date_time = Column(DateTime, nullable=False, default=func.now())
    branch_id = Column(Integer, nullable=False)
    dept_id = Column(Integer, nullable=True)


class BomHdr(Base):
    __tablename__ = "item_bom_hdr_mst"

    bom_hdr_id = Column(Integer, primary_key=True, autoincrement=True)
    item_id = Column(Integer, ForeignKey("item_mst.item_id"), nullable=False)
    bom_version = Column(Integer, nullable=False, default=1)
    version_label = Column(String(50), nullable=True)
    status_id = Column(Integer, nullable=False, default=21)
    # Lifecycle status (New / Certified / Under Development / Closed) — independent
    # of status_id, which feeds BOM Costing approval. See src/masters/constants.py.
    bom_status = Column(String(32), nullable=False, default="New", server_default="New")
    effective_from = Column(Date, nullable=True)
    effective_to = Column(Date, nullable=True)
    is_current = Column(Integer, nullable=False, default=0)
    remarks = Column(Text, nullable=True)
    co_id = Column(Integer, nullable=False)
    active = Column(Integer, nullable=False, default=1)
    updated_by = Column(Integer, nullable=False)
    updated_date_time = Column(DateTime, nullable=False, default=func.now())
    # Output-qty divisor for the cost rollup: cost_per_unit = total_cost / cost_basis_qty.
    # Default 1 preserves pre-existing snapshot numbers (AMCL enquiry flow, design section 5.2).
    cost_basis_qty: Mapped[float] = mapped_column(Double, nullable=False, default=1, server_default="1")


class CostElementMst(Base):
    __tablename__ = "cost_element_mst"

    cost_element_id = Column(Integer, primary_key=True, autoincrement=True)
    element_code = Column(String(30), nullable=False)
    element_name = Column(String(100), nullable=False)
    parent_element_id = Column(Integer, ForeignKey("cost_element_mst.cost_element_id"), nullable=True)
    element_level = Column(Integer, nullable=False, default=0)
    element_type = Column(String(30), nullable=False)
    default_basis = Column(String(30), nullable=True)
    is_leaf = Column(Integer, nullable=False, default=0)
    sort_order = Column(Integer, nullable=False, default=0)
    element_desc = Column(Text, nullable=True)
    co_id = Column(Integer, nullable=False)
    active = Column(Integer, nullable=False, default=1)
    updated_by = Column(Integer, nullable=False)
    updated_date_time = Column(DateTime, nullable=False, default=func.now())


class BomCostEntry(Base):
    __tablename__ = "bom_cost_entry"

    bom_cost_entry_id = Column(Integer, primary_key=True, autoincrement=True)
    bom_hdr_id = Column(Integer, ForeignKey("item_bom_hdr_mst.bom_hdr_id"), nullable=False)
    cost_element_id = Column(Integer, ForeignKey("cost_element_mst.cost_element_id"), nullable=False)
    amount = Column(Float, nullable=False, default=0)
    source = Column(String(30), nullable=False, default='manual')
    qty = Column(Float, nullable=True)
    rate = Column(Float, nullable=True)
    basis_override = Column(String(30), nullable=True)
    effective_date = Column(Date, nullable=False)
    entered_by = Column(Integer, nullable=True)
    remarks = Column(Text, nullable=True)
    co_id = Column(Integer, nullable=False)
    active = Column(Integer, nullable=False, default=1)
    updated_by = Column(Integer, nullable=False)
    updated_date_time = Column(DateTime, nullable=False, default=func.now())


class StdRateCard(Base):
    __tablename__ = "std_rate_card"

    std_rate_card_id = Column(Integer, primary_key=True, autoincrement=True)
    rate_type = Column(String(30), nullable=False)
    reference_id = Column(Integer, nullable=True)
    reference_type = Column(String(30), nullable=True)
    rate = Column(Float, nullable=False, default=0)
    uom = Column(String(30), nullable=True)
    valid_from = Column(Date, nullable=False)
    valid_to = Column(Date, nullable=True)
    co_id = Column(Integer, nullable=False)
    active = Column(Integer, nullable=False, default=1)
    updated_by = Column(Integer, nullable=False)
    updated_date_time = Column(DateTime, nullable=False, default=func.now())


class BomCostSnapshot(Base):
    __tablename__ = "bom_cost_snapshot"

    bom_cost_snapshot_id = Column(Integer, primary_key=True, autoincrement=True)
    bom_hdr_id = Column(Integer, ForeignKey("item_bom_hdr_mst.bom_hdr_id"), nullable=False)
    material_cost = Column(Float, nullable=False, default=0)
    conversion_cost = Column(Float, nullable=False, default=0)
    overhead_cost = Column(Float, nullable=False, default=0)
    total_cost = Column(Float, nullable=False, default=0)
    cost_per_unit = Column(Float, nullable=False, default=0)
    detail_snapshot = Column(JSON, nullable=True)
    computed_at = Column(DateTime, nullable=False, default=func.now())
    computed_by = Column(Integer, nullable=True)
    is_current = Column(Integer, nullable=False, default=0)
    status = Column(String(30), nullable=False, default='draft')
    co_id = Column(Integer, nullable=False)
    active = Column(Integer, nullable=False, default=1)
    updated_by = Column(Integer, nullable=False)
    updated_date_time = Column(DateTime, nullable=False, default=func.now())

