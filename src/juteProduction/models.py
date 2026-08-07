"""SQLAlchemy ORM models for the Jute Production (spreader) module.

These reuse the same declarative Base as src/models/mst.py so they participate
in the existing metadata if anyone runs create_all().
"""

from sqlalchemy import (
    Column,
    Integer,
    String,
    Date,
    DateTime,
    DECIMAL,
    TIMESTAMP,
    func,
)

from src.models.mst import Base


class SpreaderBinMst(Base):
    __tablename__ = "spreader_bin_mst"

    bin_id = Column(Integer, primary_key=True, autoincrement=True)
    co_id = Column(Integer, nullable=False, index=True)
    branch_id = Column(Integer, nullable=True, index=True)
    bin_code = Column(String(50), nullable=False)
    bin_no = Column(Integer, nullable=True)
    description = Column(String(255), nullable=True)
    active = Column(Integer, nullable=False, default=1, server_default="1")
    updated_by = Column(Integer, nullable=True)
    updated_date_time = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())


class ItemMaturityMst(Base):
    __tablename__ = "item_maturity_mst"

    item_maturity_id = Column(Integer, primary_key=True, autoincrement=True)
    co_id = Column(Integer, nullable=False, index=True)
    item_id = Column(Integer, nullable=False)
    maturity_hours = Column(Integer, nullable=False, default=48, server_default="48")
    active = Column(Integer, nullable=False, default=1, server_default="1")
    updated_by = Column(Integer, nullable=True)
    updated_date_time = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())


class SpreaderMachineAttr(Base):
    __tablename__ = "spreader_machine_attr"

    spreader_machine_attr_id = Column(Integer, primary_key=True, autoincrement=True)
    co_id = Column(Integer, nullable=False, index=True)
    # Owning branch of the machine (machine -> dept -> branch); authoritative scope.
    branch_id = Column(Integer, nullable=True, index=True)
    machine_id = Column(Integer, nullable=False, index=True)
    wt_per_roll = Column(DECIMAL(10, 3), nullable=False, default=0, server_default="0.000")
    # Roll-weight SQC (R-08-04) band cut-points; 5 edges -> 6 buckets.
    # NULL = use the default 55/60/65/70/75 set (Spreader-2 uses 85..105).
    band_edge_1 = Column(DECIMAL(10, 3), nullable=True)
    band_edge_2 = Column(DECIMAL(10, 3), nullable=True)
    band_edge_3 = Column(DECIMAL(10, 3), nullable=True)
    band_edge_4 = Column(DECIMAL(10, 3), nullable=True)
    band_edge_5 = Column(DECIMAL(10, 3), nullable=True)
    active = Column(Integer, nullable=False, default=1, server_default="1")
    updated_by = Column(Integer, nullable=True)
    updated_date_time = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())


class SpreaderProdEntry(Base):
    __tablename__ = "spreader_prod_entry"

    spreader_prod_entry_id = Column(Integer, primary_key=True, autoincrement=True)
    co_id = Column(Integer, nullable=False, index=True)
    branch_id = Column(Integer, nullable=True, index=True)
    entry_date = Column(Date, nullable=False, index=True)
    entry_time = Column(Integer, nullable=False)
    entry_dt = Column(DateTime, nullable=False, index=True)
    spell = Column(String(2), nullable=False)
    machine_id = Column(Integer, nullable=False, index=True)
    item_id = Column(Integer, nullable=False, index=True)
    bin_id = Column(Integer, nullable=False, index=True)
    trolley_no = Column(Integer, nullable=True)
    no_of_rolls = Column(Integer, nullable=False)
    wt_per_roll = Column(DECIMAL(10, 3), nullable=False, default=0, server_default="0.000")
    entry_id_grp = Column(Integer, nullable=False, index=True)
    status_id = Column(Integer, nullable=True)
    remarks = Column(String(255), nullable=True)
    active = Column(Integer, nullable=False, default=1, server_default="1")
    updated_by = Column(Integer, nullable=True)
    updated_date_time = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())


class JuteProdDrawingMachineAttr(Base):
    __tablename__ = "jute_prod_drawing_machine_attr"

    drawing_machine_attr_id = Column(Integer, primary_key=True, autoincrement=True)
    co_id = Column(Integer, nullable=False, index=True)
    machine_id = Column(Integer, nullable=False, index=True)
    const_meter = Column(DECIMAL(12, 3), nullable=False, default=0, server_default="0.000")
    mc_group = Column(String(50), nullable=True)
    meter_wrap_limit = Column(Integer, nullable=False, default=10000, server_default="10000")
    active = Column(Integer, nullable=False, default=1, server_default="1")
    updated_by = Column(Integer, nullable=True)
    updated_date_time = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())


class JuteProdDrawingEntry(Base):
    __tablename__ = "jute_prod_drawing_entry"

    drawing_entry_id = Column(Integer, primary_key=True, autoincrement=True)
    co_id = Column(Integer, nullable=False, index=True)
    branch_id = Column(Integer, nullable=True, index=True)
    tran_date = Column(Date, nullable=False, index=True)
    spell = Column(String(10), nullable=False)
    machine_id = Column(Integer, nullable=False, index=True)
    open_meter = Column(DECIMAL(12, 3), nullable=False, default=0, server_default="0.000")
    close_meter = Column(DECIMAL(12, 3), nullable=False, default=0, server_default="0.000")
    diff_meter = Column(DECIMAL(12, 3), nullable=False, default=0, server_default="0.000")
    const_meter = Column(DECIMAL(12, 3), nullable=False, default=0, server_default="0.000")
    wrk_hours = Column(DECIMAL(5, 2), nullable=False, default=0, server_default="0.00")
    actual_eff = Column(DECIMAL(8, 2), nullable=False, default=0, server_default="0.00")
    remarks = Column(String(255), nullable=True)
    active = Column(Integer, nullable=False, default=1, server_default="1")
    updated_by = Column(Integer, nullable=True)
    updated_date_time = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())


class SpreaderRollIssue(Base):
    __tablename__ = "spreader_roll_issue"

    spreader_roll_issue_id = Column(Integer, primary_key=True, autoincrement=True)
    co_id = Column(Integer, nullable=False, index=True)
    branch_id = Column(Integer, nullable=True, index=True)
    issue_date = Column(Date, nullable=False, index=True)
    issue_time = Column(Integer, nullable=False)
    issue_dt = Column(DateTime, nullable=False, index=True)
    spell = Column(String(2), nullable=False)
    entry_id_grp = Column(Integer, nullable=False, index=True)
    wt_per_roll = Column(DECIMAL(10, 3), nullable=False, default=0, server_default="0.000")
    no_of_rolls = Column(Integer, nullable=False)
    breaker_inter_no = Column(String(100), nullable=True)
    remarks = Column(String(255), nullable=True)
    active = Column(Integer, nullable=False, default=1, server_default="1")
    updated_by = Column(Integer, nullable=True)
    updated_date_time = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
