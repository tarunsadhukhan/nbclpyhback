"""
SQLAlchemy ORM models for jute tables (jute_*).
Auto-generated from database schema: sls
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Optional, List

from sqlalchemy import (
    BigInteger,
    Column,
    Date,
    DateTime,
    Double,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    TIMESTAMP,
    func,
)
from sqlalchemy.orm import relationship, Mapped, mapped_column, DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all jute models."""
    pass


# =============================================================================
# JUTE QUALITY MASTER
# =============================================================================

class JuteQualityMst(Base):
    """DEPRECATED: Jute quality master table.
    
    Quality is now managed via item_mst hierarchy:
    item_grp_mst (Jute parent) → item_grp_mst (subgroups) → item_mst (items = old qualities).
    This model is kept for backward compatibility / data migration only.
    """
    __tablename__ = "jute_quality_mst"

    jute_qlty_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    co_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    item_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    jute_quality: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    updated_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=True, server_default=func.current_timestamp()
    )


# =============================================================================
# JUTE MR (MATERIAL RECEIPT) MODELS
# =============================================================================

class JuteMr(Base):
    """Jute Material Receipt table - stores MR information (combined gate entry + MR).

    Updated based on dev3 schema (2026-01-15).
    Gate entry table was merged into MR - this table now handles both gate entry and material receipt.
    Fields include: gate entry info, weights, QC, bill pass, invoice, and file uploads.
    """
    __tablename__ = "jute_mr"

    jute_mr_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    branch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)

    # Gate Entry identification (merged from jute_gate_entry)
    jute_gate_entry_no: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    jute_gate_entry_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    # MR identification
    branch_mr_no: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    jute_mr_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    # PO reference
    po_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)

    # Supplier/Party information
    jute_supplier_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    party_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    party_branch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    src_com_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Challan details
    challan_no: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    challan_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    challan_weight: Mapped[Optional[float]] = mapped_column(Double, nullable=True)

    # Weight measurements (from gate entry)
    gross_weight: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    tare_weight: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    net_weight: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    variable_shortage: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    actual_weight: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    mr_weight: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Vehicle and transport details (from gate entry)
    vehicle_no: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    transporter: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    driver_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Time tracking (from gate entry) - Note: in_time, out_time are TIME type
    in_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    out_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    out_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Location and unit
    mukam_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    unit_conversion: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # QC and status
    qc_check: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    marketing_slip: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    approval_level: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=None)
    remarks: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Freight
    frieght_paid: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Bill pass details
    bill_pass_no: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    bill_pass_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    bill_pass_complete: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=0)

    # Financial amounts
    total_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    claim_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    roundoff: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    net_total: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    tds_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)

    # Invoice details
    invoice_no: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    invoice_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    invoice_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    payment_due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    invoice_received_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    # File uploads
    invoice_upload: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    challan_upload: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Audit fields
    updated_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_date_time: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())

    # Relationships
    line_items: Mapped[List["JuteMrLi"]] = relationship(
        "JuteMrLi", back_populates="jute_mr", foreign_keys="JuteMrLi.jute_mr_id"
    )


class JuteMrLi(Base):
    """Jute MR line item table - stores line items for material receipts.

    Updated based on dev3 schema (2026-01-15).
    Gate entry line item merged into MR line item - this table now handles both.
    Includes challan details, actual received details, QC data, claims, and pricing.
    """
    __tablename__ = "jute_mr_li"

    jute_mr_li_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    jute_mr_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("jute_mr.jute_mr_id"), nullable=True, index=True
    )
    jute_po_li_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)

    # Challan details — challan_item_id references item_mst; group is derived via item_mst.item_grp_id
    challan_item_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    challan_quantity: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    challan_weight: Mapped[Optional[float]] = mapped_column(Float, nullable=True, default=0)

    # Actual (received) details — actual_item_id references item_mst; group is derived via item_mst.item_grp_id
    actual_item_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    actual_qty: Mapped[Optional[float]] = mapped_column(Float, nullable=True, default=0)
    actual_weight: Mapped[Optional[float]] = mapped_column(Float, nullable=True, default=0)
    actual_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True, default=0)

    # UOM (LOOSE/BALE)
    unit_conversion: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Moisture details
    allowable_moisture: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    actual_moisture: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Claims and adjustments
    claim_dust: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    claim_quality: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    shortage_kgs: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=0)

    # Accepted and pricing
    accepted_weight: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True, default=0)
    claim_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    water_damage_amount: Mapped[Optional[Decimal]] = mapped_column(Double, nullable=True, default=0)
    premium_amount: Mapped[Optional[Decimal]] = mapped_column(Double, nullable=True, default=0)
    total_price: Mapped[Optional[Decimal]] = mapped_column(Double, nullable=True)

    # Storage details
    warehouse_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    marka: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    crop_year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Status and audit
    status: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    remarks: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    active: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=1)
    updated_date_time: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())

    # Relationships
    jute_mr: Mapped[Optional["JuteMr"]] = relationship(
        "JuteMr", back_populates="line_items", foreign_keys=[jute_mr_id]
    )
    moisture_readings: Mapped[List["JuteMoistureRdg"]] = relationship(
        "JuteMoistureRdg", back_populates="mr_line_item", foreign_keys="JuteMoistureRdg.jute_mr_li_id"
    )


class JuteMoistureRdg(Base):
    """Jute moisture reading table - stores multiple moisture readings per MR line item.

    Created based on dev3 schema (2026-01-07).
    """
    __tablename__ = "jute_moisture_rdg"

    jute_moisture_rdg_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    jute_mr_li_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("jute_mr_li.jute_mr_li_id"), nullable=True, index=True
    )
    moisture_percentage: Mapped[Optional[float]] = mapped_column(Double, nullable=True)

    # Relationships
    mr_line_item: Mapped[Optional["JuteMrLi"]] = relationship(
        "JuteMrLi", back_populates="moisture_readings", foreign_keys=[jute_mr_li_id]
    )


# =============================================================================
# JUTE ISSUE MODELS
# =============================================================================

class JuteIssue(Base):
    """Jute issue table - stores jute issue transactions to production/departments."""
    __tablename__ = "jute_issue"

    issue_no: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    branch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    fin_year: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Issue details
    issue_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    issue_status: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    issue_value: Mapped[Optional[Decimal]] = mapped_column(Double, nullable=True)

    # Jute details — item_id is the item (was jute_quality), jute_type is the subgroup name
    jute_type: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    item_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Quantity and stock
    quantity: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    no_bales: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    bale_loose: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    total_weight: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    open_stock: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    close_stock: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    stock_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Location/Assignment
    dept_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    godown_no: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    side: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # References
    mr_no: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    yarn_type_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    wastage_type_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=1)
    uom_code: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Status and audit
    is_active: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=1)
    created_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    create_date_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, server_default=func.current_timestamp()
    )
    updated_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    update_date_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class JuteIssuePrimary(Base):
    """Jute issue primary table - stores primary issue records for jute to production."""
    __tablename__ = "jute_issue_primary"

    jute_issue_primary_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)

    # Issue details
    issue_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Jute details — item_id is the item (was jute_quality), jute_type is the subgroup name
    jute_type: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    item_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Quantity and weight
    no_of_bales: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    no_of_bales_issued: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    bale_or_loose: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    gross_weight: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    tare_weight: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    net_weight: Mapped[Optional[float]] = mapped_column(Double, nullable=True)

    # Location/Assignment
    godown_no: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    side: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    trolly_no: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    yarn_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # References
    mr_line_item_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Status and audit
    is_active: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    auto_date_time_insert: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )


# =============================================================================
# JUTE SUPPLIER MODELS
# =============================================================================

class JuteSupplierMst(Base):
    """Jute supplier master table - stores jute supplier information."""
    __tablename__ = "jute_supplier_mst"

    supplier_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    supplier_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    contact_no: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    updated_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_date_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, server_default=func.current_timestamp()
    )

    # Relationships
    party_mappings: Mapped[List["JuteSuppPartyMap"]] = relationship(
        "JuteSuppPartyMap", back_populates="jute_supplier"
    )


class JuteSuppPartyMap(Base):
    """Jute supplier to party mapping table - maps jute suppliers to party master."""
    __tablename__ = "jute_supp_party_map"

    map_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    co_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    jute_supplier_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("jute_supplier_mst.supplier_id"), nullable=True, index=True
    )
    updated_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )
    party_id : Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)

    # Relationships
    jute_supplier: Mapped[Optional["JuteSupplierMst"]] = relationship(
        "JuteSupplierMst", back_populates="party_mappings"
    )


# =============================================================================
# JUTE MUKAM MASTER MODEL
# =============================================================================

class JuteMukamMst(Base):
    """Jute mukam master table - stores mukam (location) information for jute."""
    __tablename__ = "jute_mukam_mst"

    mukam_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mukam_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    updated_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_date_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, server_default=func.current_timestamp()
    )


# =============================================================================
# JUTE LORRY MASTER MODEL
# =============================================================================

class JuteLorryMst(Base):
    """Jute lorry master table - stores lorry type and weight information for jute logistics."""
    __tablename__ = "jute_lorry_mst"

    jute_lorry_type_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    lorry_type: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    weight: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    co_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    updated_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_date_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, server_default=func.current_timestamp()
    )


# =============================================================================
# JUTE AGENT MAP MODEL
# =============================================================================

class JuteAgentMap(Base):
    """Jute agent mapping table - maps agents (party branches) to branches."""
    __tablename__ = "jute_agent_map"

    agent_map_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    party_branch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    co_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    agent_branch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)

# =============================================================================
# JUTE PO MODELS
# =============================================================================

class JutePo(Base):
    """Jute purchase order header table - stores jute PO transactions.

    Updated based on dev3 schema (2026-01-08).
    """
    __tablename__ = "jute_po"

    jute_po_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    branch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    supplier_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    party_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    jute_mukam_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    jute_indent_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)

    # PO identification
    po_no: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    po_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    status_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    approval_level: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=None)

    # Contract details
    contract_no: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    contract_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    channel_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Terms and charges
    credit_term: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    delivery_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    frieght_charge: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    brokrage_rate: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    brokrage_percentage: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    penalty: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Vehicle details
    vehicle_type_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    vehicle_quantity: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Value and weight
    jute_po_value: Mapped[Optional[Decimal]] = mapped_column(Double, nullable=True)
    weight: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    jute_uom: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Notes and remarks
    remarks: Mapped[Optional[str]] = mapped_column(String(4000), nullable=True)
    internal_note: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    footer_note: Mapped[Optional[str]] = mapped_column(String(65535), nullable=True)  # longtext

    # Audit fields
    updated_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_date_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, server_default=func.current_timestamp()
    )

    # Relationships
    line_items: Mapped[List["JutePoLi"]] = relationship(
        "JutePoLi", back_populates="jute_po"
    )


class JutePoLi(Base):
    """Jute purchase order line item table - stores individual items in a jute PO.

    Updated based on dev3 schema (2026-01-08).
    """
    __tablename__ = "jute_po_li"

    jute_po_li_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    jute_po_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("jute_po.jute_po_id"), nullable=True, index=True
    )

    # Item details — item_id references item_mst; group is derived via item_mst.item_grp_id
    item_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)

    # Quantity and pricing
    quantity: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Percentage share of total PO weight (0-100). New POs use this to derive quantity.
    percentage: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    value: Mapped[Optional[Decimal]] = mapped_column(Double, nullable=True)

    # Jute details
    marka: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    crop_year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    allowable_moisture: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # UOM (LOOSE/BALE) — per line item
    jute_uom: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Status
    active: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=1)
    status_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)

    # Audit
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )

    # Relationships
    jute_po: Mapped[Optional["JutePo"]] = relationship(
        "JutePo", back_populates="line_items"
    )


# =============================================================================
# JUTE YARN TYPE MASTER
# =============================================================================

class JuteYarnTypeMst(Base):
    """DEPRECATED: Jute yarn type master table.
    
    Yarn types have been migrated to item_grp_mst with item_type_id=4.
    This model is kept for backward compatibility / rollback only.
    Do NOT use in new code — use ItemGrpMst with item_type_id=4 instead.
    """
    __tablename__ = "jute_yarn_type_mst"
    __table_args__ = {"extend_existing": True}

    jute_yarn_type_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    jute_yarn_type_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    co_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    updated_date_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, server_default=func.current_timestamp()
    )
    updated_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


# =============================================================================
# JUTE YARN MASTER
# =============================================================================

class JuteYarnMst(Base):
    """Jute yarn master table - stores yarn-specific details.

    Based on dev3 schema (2026-02-19).
    Each yarn also has a corresponding item_mst record (linked via item_id).
    - item_grp_id: FK to item_grp_mst (item_type_id=4) — the yarn type group.
    - item_id: FK to item_mst — the item record created alongside this yarn.
    - jute_yarn_name / co_id: Deprecated — kept for backward compatibility.
      The authoritative name comes from item_mst.item_name.
    """
    __tablename__ = "jute_yarn_mst"

    jute_yarn_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    jute_yarn_count: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    # std_mr_pct: standard moisture regain % — used by Spinning SQC corrected-count calc.
    std_mr_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # FK exists in DB but omitted from ORM — item_grp_mst uses a different DeclarativeBase
    item_grp_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, nullable=True, index=True
    )
    jute_yarn_remarks: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    item_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    # Deprecated: name now sourced from item_mst.item_name; kept for backward compat
    jute_yarn_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    # Deprecated: company scoping now via item_grp_mst.co_id; kept for backward compat
    co_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    updated_date_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, server_default=func.current_timestamp()
    )
    updated_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Note: No ORM relationship to ItemGrpMst or ItemMst because they use
    # a different DeclarativeBase. Use raw SQL joins for querying.

# =============================================================================
# JUTE BATCH PLAN MODELS
# =============================================================================

class JuteBatchPlan(Base):
    """Jute batch plan header table - stores batch plan information.

    Based on dev3 schema (2026-02-02).
    """
    __tablename__ = "jute_batch_plan"

    batch_plan_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    branch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    plan_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    updated_by: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    updated_date_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, server_default=func.current_timestamp()
    )

    # Relationships
    line_items: Mapped[List["JuteBatchPlanLi"]] = relationship(
        "JuteBatchPlanLi", back_populates="batch_plan"
    )


class JuteBatchPlanLi(Base):
    """Jute batch plan line item table - stores jute quality percentages for a batch plan.

    Based on dev3 schema (2026-02-02).
    """
    __tablename__ = "jute_batch_plan_li"

    batch_plan_li_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    batch_plan_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("jute_batch_plan.batch_plan_id"), nullable=True, index=True
    )
    jute_quality_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    percentage: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    updated_by: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )

    # Relationships
    batch_plan: Mapped[Optional["JuteBatchPlan"]] = relationship(
        "JuteBatchPlan", back_populates="line_items"
    )


# =============================================================================
# JUTE ISSUE (DEV3 SCHEMA)
# =============================================================================

class JuteIssueDev3(Base):
    """Jute issue table (dev3 schema) - stores jute issue transactions to production.

    Based on dev3 schema (2026-02-02). This schema is simpler than the legacy
    JuteIssue model and uses different column structure.

    Note: Use this model when working with the dev3 database. The legacy JuteIssue
    model remains for backward compatibility with older databases.
    """
    __tablename__ = "jute_issue"
    __table_args__ = {"extend_existing": True}  # Allow coexistence with legacy model

    jute_issue_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    branch_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, index=True)

    # Issue details
    issue_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    status_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    issue_value: Mapped[Optional[Decimal]] = mapped_column(Double, nullable=True)

    # References — item_id is the item (was jute_quality_id)
    item_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    jute_mr_li_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, index=True)
    yarn_type_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, index=True)

    # Quantity and weight
    quantity: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    weight: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    unit_conversion: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Audit fields
    updated_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    update_date_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


# =============================================================================
# JUTE STOCK OUTSTANDING VIEW
# =============================================================================

class VwJuteStockOutstanding(Base):
    """View model for vw_jute_stock_outstanding - shows available MR stock for issue.

    This view calculates balance quantity and weight by subtracting issued amounts
    from the original MR line item amounts.

    Only includes MRs with status_id IN (3, 13) (approved / finalised).
    Issued quantity excludes cancelled issues (status_id <> 4).

    Actual View Definition (from dev3, 2026-02-17):
    SELECT
        jml.jute_mr_li_id,
        jm.out_date            AS inward_date,
        jm.branch_id,
        jm.branch_mr_no,
        jm.jute_gate_entry_no,
        wm.warehouse_name,
        jml.actual_quality,
        jml.actual_item_id,
        jml.actual_qty,
        jml.actual_weight,
        jm.unit_conversion,
        (jml.actual_qty - IFNULL(iss.issqty, 0))                              AS bal_qty,
        ROUND((jml.actual_weight - IFNULL(iss.isswt, 0)), 3)                  AS bal_weight,
        jml.accepted_weight,
        ROUND((jml.accepted_weight / jml.actual_qty) * IFNULL(iss.issqty, 0), 3) AS bal_accepted_weight,
        jml.rate,
        jml.actual_rate
    FROM jute_mr jm
    JOIN jute_mr_li jml ON jm.jute_mr_id = jml.jute_mr_id
    LEFT JOIN warehouse_mst wm ON wm.warehouse_id = jml.warehouse_id
    LEFT JOIN (
        SELECT ji.jute_mr_li_id, SUM(ji.quantity) AS issqty, SUM(ji.weight) AS isswt
        FROM jute_issue ji
        WHERE ji.status_id <> 4
        GROUP BY ji.jute_mr_li_id
    ) iss ON iss.jute_mr_li_id = jml.jute_mr_li_id
    WHERE jm.status_id IN (3, 13)
    """
    __tablename__ = "vw_jute_stock_outstanding"

    # Primary key for ORM (view doesn't have PK, but ORM needs one)
    jute_mr_li_id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Inward date (from jm.out_date)
    inward_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    # Branch and MR info
    branch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    branch_mr_no: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Gate entry and warehouse info
    jute_gate_entry_no: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    warehouse_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Quality description (text from jute_mr_li.actual_quality)
    actual_quality: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Item reference — actual_item_id is the item from item_mst
    actual_item_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Original quantities from MR
    actual_qty: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    actual_weight: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Unit conversion (e.g., "LOOSE", "BALE")
    unit_conversion: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Calculated balance (available for issue)
    bal_qty: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bal_weight: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Weight fields
    accepted_weight: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bal_accepted_weight: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Rate fields
    rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    actual_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)


# =============================================================================
# JUTE BATCH DAILY ASSIGNMENT
# =============================================================================

class JuteBatchDailyAssign(Base):
    """Daily assignment of batch plans to yarn types per branch.

    Maps: Date + Branch + Yarn Type → Batch Plan.
    Each day+branch can have multiple yarn types, each assigned exactly one batch plan.
    Unique constraint: (branch_id, assign_date, jute_yarn_id).

    Status workflow: Draft (21) → Open (1) → Approved (3) / Rejected (4).

    Based on design doc 2026-02-20.
    """
    __tablename__ = "jute_batch_daily_assign"
    __table_args__ = (
        UniqueConstraint("branch_id", "assign_date", "jute_yarn_id", name="uq_branch_date_yarn"),
        {"extend_existing": True},
    )

    batch_daily_assign_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    branch_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    assign_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    jute_yarn_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    batch_plan_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    status_id: Mapped[int] = mapped_column(Integer, nullable=False, default=21)
    updated_by: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    updated_date_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, server_default=func.current_timestamp()
    )


# =============================================================================
# JUTE SQC MORRAH WEIGHT QC
# =============================================================================

class JuteSqcMorrahWt(Base):
    __tablename__ = "jute_sqc_morrah_wt"
    __table_args__ = {"extend_existing": True}

    morrah_wt_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    co_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    branch_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    inspector_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    dept_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    item_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    trolley_no: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    avg_mr_pct: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    weights: Mapped[str] = mapped_column(String(500), nullable=False)
    calc_avg_weight: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    calc_max_weight: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    calc_min_weight: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    calc_range: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    calc_cv_pct: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    count_lt: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    count_ok: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    count_hy: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    active: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    updated_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_date_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, server_default=func.current_timestamp()
    )


# =============================================================================
# JUTE SQC SPREADER ROLL WEIGHT QC (R-08-04)
# =============================================================================

class JuteSqcSpreaderRollWt(Base):
    """R-08-04 Spreader Roll Weight entry.

    Morrah-shaped: flat header + JSON-as-string readings (String(500) +
    json.dumps/json.loads) + persisted calc_*/band columns. Insert-only +
    compute-on-read. std_mr_pct and band edges are snapshotted at save time.
    """
    __tablename__ = "jute_sqc_spreader_roll_wt"
    __table_args__ = {"extend_existing": True}

    spreader_roll_wt_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    co_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    branch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    spell_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    mc_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    item_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    feeder_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    roll_weights: Mapped[str] = mapped_column(String(500), nullable=False)
    mr_pcts: Mapped[str] = mapped_column(String(500), nullable=False)
    std_mr_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    calc_avg_mr_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    calc_avg_obs: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 3), nullable=True)
    calc_avg_corr: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 3), nullable=True)
    calc_stdev_obs: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4), nullable=True)
    calc_stdev_corr: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4), nullable=True)
    calc_cv_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(7, 4), nullable=True)
    band_counts_obs: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    band_counts_corr: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    active: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    updated_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_date_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, server_default=func.current_timestamp()
    )


# =============================================================================
# JUTE SQC SPREADER ROLL SLIVER WEIGHT QC (R-08-03)
# =============================================================================

class JuteSqcSpreaderSliverWt(Base):
    """R-08-03 Spreader Roll Sliver Weight entry.

    Morrah-shaped: flat header + JSON-as-string readings (String(500) +
    json.dumps/json.loads) + persisted calc_* columns. Insert-only +
    compute-on-read. std_mr_pct is snapshotted at save time. Variable 1-12
    readings (observed_weights / mr_pcts parallel JSON); NO weight bands.
    Units are lb/100yds; sample_length_yds (default 5) and weight_basis
    ("LB/100YDS") are nullable header constants. category is nullable free-text
    (no master). Lockstep with create_jute_sqc_spreader_sliver_wt.sql.
    """
    __tablename__ = "jute_sqc_spreader_sliver_wt"
    __table_args__ = {"extend_existing": True}

    spreader_sliver_wt_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    co_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    branch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    spell_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    mc_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    item_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sample_length_yds: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    weight_basis: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    observed_weights: Mapped[str] = mapped_column(String(500), nullable=False)
    mr_pcts: Mapped[str] = mapped_column(String(500), nullable=False)
    std_mr_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    calc_avg_obs: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 3), nullable=True)
    calc_avg_corr: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 3), nullable=True)
    calc_avg_mr: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    calc_stdev: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4), nullable=True)
    calc_cv_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(7, 4), nullable=True)
    active: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    updated_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_date_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, server_default=func.current_timestamp()
    )


# =============================================================================
# JUTE SPREADER QUALITY STANDARDS SATELLITE (R-08-04)
# =============================================================================

class JuteSpreaderQualityAttr(Base):
    """Per-raw-jute-quality standards satellite for spreader SQC.

    item_id-keyed; mirrors jute_yarn_mst's role for spinning. std_mr_pct is
    nullable — the backend falls back to base 16 when absent. std_roll_wt is
    optional/unused until needed. Standards live HERE, NOT on item_mst.
    """
    __tablename__ = "jute_spreader_quality_attr"
    __table_args__ = {"extend_existing": True}

    spreader_quality_attr_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    co_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    item_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    std_mr_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    std_roll_wt: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 3), nullable=True)
    active: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    updated_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_date_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, server_default=func.current_timestamp()
    )


# =============================================================================
# JUTE DRAW QUALITY STANDARDS SATELLITE (carding/drawing family; R-08-05/06/07)
# =============================================================================

class JuteDrawQualityStd(Base):
    """Per-(line-quality, process) standards satellite for the carding/drawing family.

    Unlike jute_spreader_quality_attr (item_id-keyed only), the SAME line quality
    carries a DIFFERENT band/MR at breaker vs inter vs drawhead vs finisher, so this
    satellite is keyed (item_id, process). std_mr_pct + std_cv_low/high are the printed
    STD MR% / STD CV% band; std_weight/std_wt_tol are an optional sliver-weight target
    (unused at breaker, present for downstream stages). ALL std columns are NULLABLE with
    code fallbacks: std MR -> 16; CV pass/fail only when a band is seeded (else NULL).
    Standards live HERE, NOT on item_mst. Lockstep with create_jute_draw_quality_std.sql.
    """
    __tablename__ = "jute_draw_quality_std"
    __table_args__ = {"extend_existing": True}

    draw_quality_std_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    co_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    item_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    process: Mapped[str] = mapped_column(String(30), nullable=False)
    std_mr_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    std_cv_low: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    std_cv_high: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    std_weight: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 3), nullable=True)
    std_wt_tol: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 3), nullable=True)
    active: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    updated_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_date_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, server_default=func.current_timestamp()
    )


# =============================================================================
# JUTE SQC BREAKER CARD SLIVER WEIGHT QC (R-08-05/06/07, carding stage)
# =============================================================================

class JuteSqcBreakerCardSwt(Base):
    """R-08-05/06/07 Breaker Card (Coarse Side SWT) entry.

    Flat row-per-reading-set (one save inserts SEVERAL rows — the day's grid). Mirrors
    JuteSqcSpreaderSliverWt: flat header + JSON-as-string readings (String(500) +
    json.dumps/json.loads) + persisted calc_* columns. Insert-only + compute-on-read.
    Each row = one (machine, spell, quality) reading-set with EXACTLY 4 cut weights +
    4 MR%. std_mr_pct + std_cv_low/high are snapshotted from jute_draw_quality_std at
    (item_id, process='BREAKER') save time; std MR falls back to 16. cv_within_band is
    the computed pass flag (NULL when no band seeded). weights are LB per 5 yds. card_side
    defaults 'COARSE' for the future fine-side variant. The per-quality GRAND AVERAGE is
    recomputed at read from these rows — NOT stored. Lockstep with
    create_jute_sqc_breaker_card_swt.sql.
    """
    __tablename__ = "jute_sqc_breaker_card_swt"
    __table_args__ = {"extend_existing": True}

    breaker_card_swt_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    co_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    branch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    mc_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    spell_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    item_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    batch_plan_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    card_side: Mapped[Optional[str]] = mapped_column(String(10), nullable=True, server_default="COARSE")
    weights: Mapped[str] = mapped_column(String(500), nullable=False)
    mr_pcts: Mapped[str] = mapped_column(String(500), nullable=False)
    std_mr_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    std_cv_low: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    std_cv_high: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    calc_wt: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 3), nullable=True)
    calc_mr_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    calc_corr_wt: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 3), nullable=True)
    calc_sdev: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4), nullable=True)
    calc_cv_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(7, 4), nullable=True)
    cv_within_band: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    active: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    updated_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_date_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, server_default=func.current_timestamp()
    )


# =============================================================================
# JUTE SQC CARD SLIVER WEIGHT QC (R-08-07A, carding stage — inter/tow/hopper)
# =============================================================================

class JuteSqcCardSliverWt(Base):
    """R-08-07A Inter Card & Tow Breaker Sliver Weight entry.

    Clone of JuteSqcBreakerCardSwt with ONE delta: card_side -> section. Same flat
    row-per-reading-set (one save inserts SEVERAL rows — the day's grid), JSON-as-string
    readings (String(500) + json.dumps/json.loads), persisted calc_* columns, insert-only +
    compute-on-read. Each row = one (section, machine, spell, quality) reading-set with
    EXACTLY 4 cut weights + 4 MR%. `section` (INTER_CARD | TOW_BREAKER | HOPPER) is BOTH the
    stored sub-table label AND the (item_id, process) key into jute_draw_quality_std — the
    SAME line quality carries a different STD MR%/CV band per carding sub-process. std_mr_pct
    + std_cv_low/high are snapshotted from the satellite at (item_id, process=section) save
    time; std MR falls back to 20. cv_within_band is the computed pass flag (NULL when no band
    seeded). weights are LB per 5 yds. Section AVG + per-quality GRAND AVERAGE are recomputed
    at read — NOT stored. Lockstep with create_jute_sqc_card_sliver_wt.sql.
    """
    __tablename__ = "jute_sqc_card_sliver_wt"
    __table_args__ = {"extend_existing": True}

    card_sliver_wt_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    co_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    branch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    section: Mapped[str] = mapped_column(String(20), nullable=False)
    mc_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    spell_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    item_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    batch_plan_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    weights: Mapped[str] = mapped_column(String(500), nullable=False)
    mr_pcts: Mapped[str] = mapped_column(String(500), nullable=False)
    std_mr_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    std_cv_low: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    std_cv_high: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    calc_wt: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 3), nullable=True)
    calc_mr_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    calc_corr_wt: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 3), nullable=True)
    calc_sdev: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4), nullable=True)
    calc_cv_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(7, 4), nullable=True)
    cv_within_band: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    active: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    updated_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_date_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, server_default=func.current_timestamp()
    )


class JuteSqcFinDrawSliverWt(Base):
    """R-08-12/13/14 Finisher Drawing Sliver Weight entry.

    Clone of JuteSqcCardSliverWt with ONE extra column: dlv_nos (a JSON array of 4 delivery
    numbers, ints or null, stored String(500) + json.dumps/json.loads). Sections HESS / SWP /
    SWT. Same flat row-per-reading-set (one save inserts SEVERAL rows — the day's grid),
    persisted calc_* columns, insert-only + compute-on-read. Each row = one (section, machine,
    spell, batch) reading-set with EXACTLY 4 cut weights + 4 MR%. Quality is linked to a BATCH
    (jute_batch_plan), so there is no single (item_id, process) std row: std MR is fixed at 16
    (drawing default) and the CV band stays unevaluated (cv_within_band NULL). weights are LB
    per 5 yds. Section AVG + per-batch GRAND AVERAGE are recomputed at read — NOT stored.
    Lockstep with create_jute_sqc_fin_draw_sliver_wt.sql.
    """
    __tablename__ = "jute_sqc_fin_draw_sliver_wt"
    __table_args__ = {"extend_existing": True}

    fin_draw_sliver_wt_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    co_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    branch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    section: Mapped[str] = mapped_column(String(10), nullable=False)
    mc_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    spell_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    batch_plan_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    weights: Mapped[str] = mapped_column(String(500), nullable=False)
    mr_pcts: Mapped[str] = mapped_column(String(500), nullable=False)
    dlv_nos: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    std_mr_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    std_cv_low: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    std_cv_high: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    calc_wt: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 3), nullable=True)
    calc_mr_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    calc_corr_wt: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 3), nullable=True)
    calc_sdev: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4), nullable=True)
    calc_cv_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(7, 4), nullable=True)
    cv_within_band: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    active: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    updated_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_date_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, server_default=func.current_timestamp()
    )


class JuteSqcDrawSliverWt(Base):
    """R-08-08/09/10 Drawhead + Finisher Card Sliver Weight entry.

    Clone of JuteSqcCardSliverWt with ONE extra column: time_band (MORNING / AFTERNOON sheet
    header, String(10), nullable). Sections DRAWHEAD_SWT / DRAWHEAD_SWP / FINISHER_CARD. Same
    flat row-per-reading-set, persisted calc_* columns, insert-only + compute-on-read. Each row
    = one (section, time_band, machine, spell, batch) reading-set with EXACTLY 4 cut weights +
    4 MR%. Quality is linked to a BATCH (jute_batch_plan): std MR fixed at 16 (drawing default),
    CV band unevaluated (cv_within_band NULL). weights are LB per 5 yds. Section AVG + per-batch
    GRAND AVERAGE recomputed at read — NOT stored. Lockstep with
    create_jute_sqc_draw_sliver_wt.sql.
    """
    __tablename__ = "jute_sqc_draw_sliver_wt"
    __table_args__ = {"extend_existing": True}

    draw_sliver_wt_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    co_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    branch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    section: Mapped[str] = mapped_column(String(20), nullable=False)
    time_band: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    mc_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    spell_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    batch_plan_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    weights: Mapped[str] = mapped_column(String(500), nullable=False)
    mr_pcts: Mapped[str] = mapped_column(String(500), nullable=False)
    std_mr_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    std_cv_low: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    std_cv_high: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    calc_wt: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 3), nullable=True)
    calc_mr_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    calc_corr_wt: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 3), nullable=True)
    calc_sdev: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4), nullable=True)
    calc_cv_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(7, 4), nullable=True)
    cv_within_band: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    active: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    updated_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_date_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, server_default=func.current_timestamp()
    )


# =============================================================================
# JUTE SQC BEAM MR% QC (R-08-18)
# =============================================================================

class JuteSqcBeamMr(Base):
    """R-08-18 Beam MR% — warp-beam moisture-regain QC.

    Morrah-shaped flat header: one row per (entry_date, quality_group, beam machine) reading
    set. readings = JSON string of EXACTLY 5 MR% numbers (String(200) + json.dumps/json.loads).
    calc_avg_mr = mean of the 5, computed at save. std_mr_pct defaults by quality_group
    (HESSIAN 16 / SACKING 20) but is editable on the form and snapshotted here. deviation
    (avg_mr - std_mr_pct) and per-group overall_avg_mr are computed on read, NOT stored. No
    CV%, no pass/fail band. Lockstep with create_jute_sqc_beam_mr.sql.
    """
    __tablename__ = "jute_sqc_beam_mr"
    __table_args__ = {"extend_existing": True}

    beam_mr_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    co_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    branch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    quality_group: Mapped[str] = mapped_column(String(20), nullable=False)
    spell_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    item_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    mc_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    readings: Mapped[str] = mapped_column(String(200), nullable=False)
    calc_avg_mr: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 2), nullable=True)
    std_mr_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 2), nullable=True)
    active: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    updated_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_date_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, server_default=func.current_timestamp()
    )


class JuteSqcPackingMr(Base):
    """R-08-25 Packing MR% — finished-goods moisture at packing.

    Morrah-shaped flat header: one row per (entry_date, quality column) reading set.
    readings = JSON string of EXACTLY 10 MR% numbers (String(500) + json.dumps/json.loads).
    calc_avg_mr = mean of the 10, computed at save. quality_group (HESSIAN / SACKING) drives
    the by_date roll-up. item_id is an OPTIONAL JUTE CLOTH link (item_type_id=5); quality_label
    snapshots its name; construction_code is free text. No std, no CV%, no MR correction, no
    pass/fail (averages only). group_avg_mr (weighted mean of all readings per group) is
    computed on read, NOT stored. Lockstep with create_jute_sqc_packing_mr.sql.
    """
    __tablename__ = "jute_sqc_packing_mr"
    __table_args__ = {"extend_existing": True}

    packing_mr_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    co_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    branch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    item_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    quality_group: Mapped[str] = mapped_column(String(20), nullable=False)
    quality_label: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    construction_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    readings: Mapped[str] = mapped_column(String(500), nullable=False)
    calc_avg_mr: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 3), nullable=True)
    active: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    updated_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_date_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, server_default=func.current_timestamp()
    )


class JuteSqcStitch(Base):
    """R-08-22 Stitch SQC — finishing-stage sewing-stitch-density QC.

    Morrah-shaped flat header: one row per (entry_date, sewing machine) reading set.
    readings = JSON string of EXACTLY 5 stitch counts (stitches/dm); calc_avg = mean of
    the 5, computed at save. std_stitch is a fixed mill standard (9 stitches/dm) prefilled
    on the form, editable, and snapshotted here. flag (OK / LOW / HIGH) is computed on
    read, NOT stored. No quality column (machine-only report), no CV%, no MR correction.
    Lockstep with create_jute_sqc_stitch.sql.
    """
    __tablename__ = "jute_sqc_stitch"
    __table_args__ = {"extend_existing": True}

    stitch_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    co_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    branch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    mc_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    std_stitch: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 2), nullable=True)
    readings: Mapped[str] = mapped_column(String(200), nullable=False)
    calc_avg: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 2), nullable=True)
    inspector_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    active: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    updated_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_date_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, server_default=func.current_timestamp()
    )


class JuteSqcFabricConstruction(Base):
    """R-08-19 Fabric Construction — woven hessian cloth construction audit (header).

    One row per saved quality block: the cloth quality (item_id, item_type_id=5) plus the
    6 per-quality STANDARDS snapshotted at save (std_length_yds, std_width_cms, std_ends_dm,
    std_picks_dm, std_mr_pct, std_oz_per_yd). Sample rows hang off the _dtl table. The by_date
    summary (per-column AVG + Std-vs-Actual deviation) is computed on read, NOT stored.
    Lockstep with create_jute_sqc_fabric_construction.sql.
    """
    __tablename__ = "jute_sqc_fabric_construction"
    __table_args__ = {"extend_existing": True}

    fabric_const_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    co_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    branch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    item_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    quality_text: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    std_length_yds: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    std_width_cms: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    std_ends_dm: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    std_picks_dm: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    std_mr_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 2), nullable=True)
    std_oz_per_yd: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 3), nullable=True)
    active: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    updated_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_date_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, server_default=func.current_timestamp()
    )


class JuteSqcFabricConstructionDtl(Base):
    """R-08-19 Fabric Construction — one sample row (up to 5 per header).

    6 MEASURED inputs (length_yds, width_cms, ends_per_dm, picks_per_dm, mr_pct, obs_wt_kg)
    plus 2 server-computed per-row values stored at save:
      obs_ozs   = (obs_wt_kg * 1000 / 28.3495) / length_yds
      crcted_oz = obs_ozs * (100 + std_mr_pct) / (100 + mr_pct)
    Lockstep with create_jute_sqc_fabric_construction.sql.
    """
    __tablename__ = "jute_sqc_fabric_construction_dtl"
    __table_args__ = {"extend_existing": True}

    fabric_const_dtl_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fabric_const_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    sl: Mapped[int] = mapped_column(Integer, nullable=False)
    length_yds: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    width_cms: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    ends_per_dm: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    picks_per_dm: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    mr_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 2), nullable=True)
    obs_wt_kg: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 3), nullable=True)
    obs_ozs: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 3), nullable=True)
    crcted_oz: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 3), nullable=True)


class JuteSqcWidthPicks(Base):
    """R-08-21 Width and Picks — on-loom dimensional QC of woven cloth (header).

    One row per saved (entry_date, cloth-quality) group: the cloth quality (item_id,
    item_type_id=5) plus std_width_cm and std_picks SNAPSHOTTED at save (entered/editable
    on the form, NO change to any item master) and an optional inspector_name. Loom reading
    rows hang off the _dtl table. Width and Picks summaries are computed on read, NOT stored.
    Lockstep with create_jute_sqc_width_picks.sql.
    """
    __tablename__ = "jute_sqc_width_picks"
    __table_args__ = {"extend_existing": True}

    width_picks_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    co_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    branch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    item_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    std_width_cm: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 2), nullable=True)
    std_picks: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 2), nullable=True)
    inspector_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    active: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    updated_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_date_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, server_default=func.current_timestamp()
    )


class JuteSqcWidthPicksDtl(Base):
    """R-08-21 Width and Picks — one loom reading row.

    loom_id is the WEAVING (Loom) machine; width_cm is required per row; picks_dm is
    OPTIONAL (only a sampled subset of looms is pick-checked). Width/Picks summaries are
    computed on read. Lockstep with create_jute_sqc_width_picks.sql.
    """
    __tablename__ = "jute_sqc_width_picks_dtl"
    __table_args__ = {"extend_existing": True}

    width_picks_dtl_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    width_picks_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    loom_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    width_cm: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 2), nullable=True)
    picks_dm: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 2), nullable=True)


class JuteSqcFabricFault(Base):
    """R-08-28 Fabric Fault — weaving woven-cloth defect tally.

    Flat single-table morrah pattern (NO detail table). ONE row = ONE inspected piece
    (one loom/cloth column): header (entry_date, spell, cloth quality, loom, date_of_weaving,
    remarks, inspector) plus a FIXED 15-fault checklist of integer counts stored as a JSON
    string of 15 ints (FABRIC_FAULT_TYPES order; most counts are 0). calc_piece_total =
    sum of the 15 counts, computed at save. The DAY roll-up (per-fault totals + scores,
    grand total + score) is computed on read, NOT stored. spell_id / item_id / loom_id are
    all nullable but normally selected. Lockstep with create_jute_sqc_fabric_fault.sql.
    """
    __tablename__ = "jute_sqc_fabric_fault"
    __table_args__ = {"extend_existing": True}

    fabric_fault_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    co_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    branch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    spell_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    item_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    loom_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    date_of_weaving: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    fault_counts: Mapped[str] = mapped_column(String(500), nullable=False)
    calc_piece_total: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    remarks: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    inspector_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    active: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    updated_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_date_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, server_default=func.current_timestamp()
    )


class JuteSqcCuttingLength(Base):
    """R-08-20 Cutting Length — daily cut-piece length consistency.

    Flat single-table morrah pattern (NO detail table). One row per (entry_date)
    reading-set carries EXACTLY 20 cut-length readings in inches as a JSON string
    (readings String(500) + json.dumps / json.loads). std_length is entered on the
    form (prefilled 78, editable) and snapshotted here. avg / sample stdev (n-1) /
    cv_pct / deviation (avg - std_length) are computed at save and stored. Optional
    cloth quality link = JUTE CLOTH item (item_type_id=5), nullable. No MR correction,
    no pass/fail band. Lockstep with create_jute_sqc_cutting_length.sql.
    """
    __tablename__ = "jute_sqc_cutting_length"
    __table_args__ = {"extend_existing": True}

    cutting_length_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    co_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    branch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    item_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    std_length: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    readings: Mapped[str] = mapped_column(String(500), nullable=False)
    calc_avg: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 3), nullable=True)
    calc_stdev: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4), nullable=True)
    calc_cv_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4), nullable=True)
    calc_deviation: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 3), nullable=True)
    active: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    updated_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_date_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, server_default=func.current_timestamp()
    )


class JuteSqcBagWeight(Base):
    """R-08-23 Bag Weight — finished-bag weight control.

    Flat single-table morrah pattern (NO detail table). One row per (entry_date,
    bag type) block carries N reading rows (up to 24, variable >=1) as a JSON string
    array of objects {mr, obs} (readings String(2000) + json.dumps / json.loads).
    std_bag_weight + std_mr_pct are entered on the form (std_mr_pct prefills 20 for
    jute bags, editable) and snapshotted here. Per-row corr = obs * (100 + std_mr_pct)
    / (100 + mr). Block stats — avg_mr / avg_obs / row-wise avg_corr / sample stdev of
    obs (n-1) / cv_pct / observed & corrected heavy-light percents — are computed at
    save and stored. Bag type link = JUTE CLOTH item (item_type_id=5), nullable.
    Lockstep with create_jute_sqc_bag_weight.sql.
    """
    __tablename__ = "jute_sqc_bag_weight"
    __table_args__ = {"extend_existing": True}

    bag_weight_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    co_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    branch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    item_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    bag_type_label: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    std_bag_weight: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 2), nullable=True)
    std_mr_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    readings: Mapped[str] = mapped_column(String(2000), nullable=False)
    calc_avg_mr: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 3), nullable=True)
    calc_avg_obs_wt: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 2), nullable=True)
    calc_avg_corr_wt: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 2), nullable=True)
    calc_obs_stdev: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 3), nullable=True)
    calc_obs_cv_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 2), nullable=True)
    calc_obs_hy_lt_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 2), nullable=True)
    calc_corr_hy_lt_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 2), nullable=True)
    active: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    updated_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_date_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, server_default=func.current_timestamp()
    )


class JuteSqcEmulsion(Base):
    """R-08-02 Emulsion — daily batching jute-oil emulsion recipe log.

    Flat single-table, ONE row per (entry_date) save: recipe header + additive columns.
    NO readings array, NO StDev/CV (a recipe log, not a sampled QC report).
    oil_pct_in_emulsion is a MEASURED/typed input. std_oil_pct_low/high is the target band
    (prefilled 16/17, editable, snapshotted at save). theoretical_oil_pct
    (= oil_used_ltr / tank_capacity_ltr * 100) and oil_pct_status (OK/LOW/HIGH vs the band)
    are computed server-side on read, NOT stored. Lockstep with create_jute_sqc_emulsion.sql.
    """
    __tablename__ = "jute_sqc_emulsion"
    __table_args__ = {"extend_existing": True}

    emulsion_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    co_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    branch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    mc_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    oil_used_ltr: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    tank_capacity_ltr: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    oil_pct_in_emulsion: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    std_oil_pct_low: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    std_oil_pct_high: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    adco_used_ml: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    eco_fin_used_ltr: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    p40_gms: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    efjl_kg: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    glycerine_gms: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    castrol_oil: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    diesel_ltr: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    citric_acid_ltr: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    enzyme_gms: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    treated_water_ltr: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    rbo_ltr: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    jbo_ltr: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    molasses_kg: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    urea_kg: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    biochemical_kg: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    jsp66: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    feel_free_good_ve_kg: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    spreader_rolls_made: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    others: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    prepared_by: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    active: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    updated_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_date_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, server_default=func.current_timestamp()
    )


class JuteSqcBagCheck(Base):
    """R-08-24 Bag Checking — finished-bag acceptance inspection (header).

    One row per saved (entry_date, bag type) block: the bag type (item_id, item_type_id=5,
    nullable) plus free-text vendor_name / id_code (no master) and the 7 per-quality STANDARDS
    snapshotted at save (std_bag_weight, std_length, std_width, std_ends, std_picks, std_stitch,
    std_mr_pct — std_mr_pct prefills 20, all editable). Per-bag rows hang off the _dtl table.
    Block aggregates (per-column avg / SAMPLE stdev / cv% / min / max + obs & corr heavy-light
    percents) are computed on read, NOT stored. bag_type_label is String(255) (real bag item
    names run ~150 chars). Lockstep with create_jute_sqc_bag_check.sql.
    """
    __tablename__ = "jute_sqc_bag_check"
    __table_args__ = {"extend_existing": True}

    bag_check_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    co_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    branch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    item_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    bag_type_label: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    vendor_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    id_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    std_bag_weight: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 2), nullable=True)
    std_length: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 2), nullable=True)
    std_width: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 2), nullable=True)
    std_ends: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 2), nullable=True)
    std_picks: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 2), nullable=True)
    std_stitch: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 2), nullable=True)
    std_mr_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    active: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    updated_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_date_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, server_default=func.current_timestamp()
    )


class JuteSqcBagCheckDtl(Base):
    """R-08-24 Bag Checking — one per-bag inspection row (variable count, >=1 per header).

    7 MEASURED inputs (length_cm, width_cm, ends_dm, picks_dm, mr_pct, bag_wt_gm, stitch_dm)
    plus optional free-text defects and one server-computed value stored at save:
      corr_wt_gm = bag_wt_gm * (100 + std_mr_pct) / (100 + mr_pct)
    Lockstep with create_jute_sqc_bag_check.sql.
    """
    __tablename__ = "jute_sqc_bag_check_dtl"
    __table_args__ = {"extend_existing": True}

    bag_check_dtl_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bag_check_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    sl_no: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    length_cm: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 2), nullable=True)
    width_cm: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 2), nullable=True)
    ends_dm: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 2), nullable=True)
    picks_dm: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 2), nullable=True)
    mr_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 2), nullable=True)
    bag_wt_gm: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 2), nullable=True)
    stitch_dm: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 2), nullable=True)
    defects: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    corr_wt_gm: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 2), nullable=True)


class JuteSqcHumidity(Base):
    """Humidity Recording — plant-wide department temperature / RH log.

    Flat single-table morrah/bag_weight pattern (NO detail table). One row per saved
    (report_date, dept, round) reading-set carries 1..3 SPOT readings as a JSON string
    array of objects {spot_label, reading_time, temp_c, rh_pct} (spots String(1000) +
    json.dumps / json.loads). round_no 1=Morning, 2=Noon, 3=Evening. avg_temp =
    mean(temp_c over spots), avg_rh = mean(rh_pct over spots), both computed server-side
    at save and stored (2dp). No StDev/CV, no band/status (averages only). Coexists with
    the spinning RHMR report (JuteSqcSpinningRhmr); does NOT supersede it.
    Lockstep with create_jute_sqc_humidity.sql.
    """
    __tablename__ = "jute_sqc_humidity"
    __table_args__ = {"extend_existing": True}

    humidity_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    co_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    branch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    report_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    dept_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    round_no: Mapped[int] = mapped_column(Integer, nullable=False)
    spots: Mapped[str] = mapped_column(String(1000), nullable=False)
    calc_avg_temp: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    calc_avg_rh: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    prepared_by: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    active: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    updated_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_date_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, server_default=func.current_timestamp()
    )
