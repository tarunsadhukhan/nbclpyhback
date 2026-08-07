"""
SQLAlchemy ORM models for the AMCL enquiry-to-delivery flow (Phase 1).
Covers: sales enquiry header/detail, generic flow stage master + log,
enquiry price checks, and the company x menu ISO document-number map.

Schema source: dbqueries/migrations/create_amcl_enquiry_flow_phase1.sql
(design: docs/amcl-enquiry-flow-design.md section 5.1).
"""

from datetime import date, datetime
from typing import Optional, List

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Double,
    ForeignKey,
    Index,
    Integer,
    BigInteger,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship, Mapped, mapped_column, DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all enquiry-flow models."""
    pass


# =============================================================================
# FLOW STAGE MASTER
# =============================================================================

class FlowStageMst(Base):
    """Generic flow stage master, keyed by (module, stage_code).

    Phase 1 seeds module 'ENQUIRY' (14 stages, design section 4). dept_hint is a
    display label ONLY — NOT an FK, because dept_mst rows are tenant/branch-specific.
    sequence_no uses gaps of 10; 999 marks the out-of-band terminal stage (LOST).
    """
    __tablename__ = "flow_stage_mst"
    __table_args__ = (
        UniqueConstraint("module", "stage_code", name="uk_flow_stage_module_code"),
        Index("idx_flow_stage_module_seq", "module", "sequence_no"),
    )

    stage_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    module: Mapped[str] = mapped_column(String(30), nullable=False)
    stage_code: Mapped[str] = mapped_column(String(30), nullable=False)
    stage_name: Mapped[str] = mapped_column(String(100), nullable=False)
    dept_hint: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    is_terminal: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    active: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")


# =============================================================================
# SALES ENQUIRY (HEADER + DETAIL)
# =============================================================================

class SalesEnquiry(Base):
    """Sales enquiry header.

    Full standard approval lifecycle (21 Draft -> 1 Open -> 20 Pending -> 3
    Approved / 4 Rejected; 21->6 cancel; 5 Closed at the end — "Lost" is
    status 5 + close_reason='lost' + stage LOST). Company scope derived via
    branch (no co_id — consistent with sales_quotation). current_stage_id is a
    denormalized pointer for board queries; source of truth is the latest
    flow_stage_log row. stage_since drives days-in-stage aging.
    """
    __tablename__ = "sales_enquiry"
    __table_args__ = (
        Index("idx_sales_enquiry_no", "enquiry_no"),
        Index("idx_sales_enquiry_branch", "branch_id"),
        Index("idx_sales_enquiry_party", "party_id"),
        Index("idx_sales_enquiry_stage", "current_stage_id", "hold_flag", "active"),
        Index("idx_sales_enquiry_status", "status_id"),
        CheckConstraint(
            "received_via IS NULL OR received_via IN ('email', 'phone', 'visit', 'tender', 'other')",
            name="chk_sales_enquiry_received_via",
        ),
        CheckConstraint(
            "close_reason IS NULL OR close_reason IN ('won', 'lost', 'cancelled')",
            name="chk_sales_enquiry_close_reason",
        ),
    )

    sales_enquiry_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    enquiry_no: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    enquiry_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    received_via: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    branch_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("branch_mst.branch_id"), nullable=True
    )
    party_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("party_mst.party_id"), nullable=True
    )
    contact_person: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    contact_detail: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    customer_ref_no: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    expected_delivery_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    enquiry_desc: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    internal_note: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    current_stage_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("flow_stage_mst.stage_id"), nullable=True
    )
    stage_since: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    hold_flag: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    status_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("status_mst.status_id"), nullable=True, default=21, server_default="21"
    )
    approval_level: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, default=0, server_default="0"
    )
    close_reason: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    lost_remarks: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    project_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("project_mst.project_id"), nullable=True
    )
    active: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    updated_by: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )

    # Relationships
    details: Mapped[List["SalesEnquiryDtl"]] = relationship(
        "SalesEnquiryDtl", back_populates="enquiry",
        foreign_keys="SalesEnquiryDtl.sales_enquiry_id",
    )
    current_stage: Mapped[Optional["FlowStageMst"]] = relationship(
        "FlowStageMst", foreign_keys=[current_stage_id]
    )


class SalesEnquiryDtl(Base):
    """Sales enquiry line — one enquired item.

    item_id is NULL when the item does not exist yet (new design); then
    item_desc_freetext is mandatory (app-enforced). cost_snapshot_id +
    confirmed_cost_per_unit are written by the costing-confirm action and stay
    as immutable evidence even if the snapshot is recomputed later. Per spec
    this dtl carries only `active` (no updated_by/updated_date_time).
    """
    __tablename__ = "sales_enquiry_dtl"
    __table_args__ = (
        Index("idx_enquiry_dtl_hdr", "sales_enquiry_id", "active"),
        Index("idx_enquiry_dtl_item", "item_id"),
        Index("idx_enquiry_dtl_bom", "bom_hdr_id"),
        Index("idx_enquiry_dtl_snapshot", "cost_snapshot_id"),
    )

    enquiry_dtl_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sales_enquiry_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sales_enquiry.sales_enquiry_id"), nullable=False
    )
    item_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("item_mst.item_id"), nullable=True
    )
    item_desc_freetext: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    is_new_item: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    design_change: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    qty: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    uom_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("uom_mst.uom_id"), nullable=True
    )
    target_price: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    bom_hdr_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("item_bom_hdr_mst.bom_hdr_id"), nullable=True
    )
    cost_snapshot_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("bom_cost_snapshot.bom_cost_snapshot_id"), nullable=True
    )
    confirmed_cost_per_unit: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    costing_confirmed_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("user_mst.user_id"), nullable=True
    )
    costing_confirmed_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    overhead_pct: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    margin_pct: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    remarks: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    active: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    # Relationships
    enquiry: Mapped[Optional["SalesEnquiry"]] = relationship(
        "SalesEnquiry", back_populates="details", foreign_keys=[sales_enquiry_id]
    )


# =============================================================================
# FLOW STAGE LOG (HANDOFF + FEEDBACK TRAIL)
# =============================================================================

class FlowStageLog(Base):
    """Handoff + feedback trail — deliberately generic (doc_type + doc_id, no FK
    to the document) so other flows can reuse it later without schema change.

    Phase 1 writes only doc_type='SALES_ENQUIRY'. `action` and
    `linked_doc_type` value sets are enforced in src/sales/enquiry_constants.py
    (no DB CHECK — Phase 2 extends the sets without DDL). feedback is mandatory
    when action='SEND_BACK' (app-enforced).
    """
    __tablename__ = "flow_stage_log"
    __table_args__ = (
        Index("idx_flow_stage_log_doc", "doc_type", "doc_id", "stage_log_id"),
    )

    stage_log_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    doc_type: Mapped[str] = mapped_column(String(30), nullable=False)
    doc_id: Mapped[int] = mapped_column(Integer, nullable=False)
    from_stage_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("flow_stage_mst.stage_id"), nullable=True
    )
    to_stage_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("flow_stage_mst.stage_id"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    feedback: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    linked_doc_type: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    linked_doc_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    action_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("user_mst.user_id"), nullable=False
    )
    action_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )

    # Relationships
    from_stage: Mapped[Optional["FlowStageMst"]] = relationship(
        "FlowStageMst", foreign_keys=[from_stage_id]
    )
    to_stage: Mapped[Optional["FlowStageMst"]] = relationship(
        "FlowStageMst", foreign_keys=[to_stage_id]
    )


# =============================================================================
# ENQUIRY PRICE CHECK (HEADER + DETAIL)
# =============================================================================

class EnquiryPriceCheck(Base):
    """Design/Costing -> Procurement pricing consult header.

    Internal and lightweight — no approval workflow. pc_status:
    pending / responded / cancelled.
    """
    __tablename__ = "enquiry_price_check"
    __table_args__ = (
        Index("idx_price_check_enquiry", "sales_enquiry_id", "active"),
        Index("idx_price_check_status", "pc_status", "active"),
        CheckConstraint(
            "pc_status IN ('pending', 'responded', 'cancelled')",
            name="chk_price_check_status",
        ),
    )

    price_check_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sales_enquiry_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sales_enquiry.sales_enquiry_id"), nullable=False
    )
    request_note: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    pc_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending"
    )
    requested_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("user_mst.user_id"), nullable=True
    )
    requested_date_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    responded_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("user_mst.user_id"), nullable=True
    )
    responded_date_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    response_note: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    active: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    updated_by: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )

    # Relationships
    enquiry: Mapped[Optional["SalesEnquiry"]] = relationship(
        "SalesEnquiry", foreign_keys=[sales_enquiry_id]
    )
    details: Mapped[List["EnquiryPriceCheckDtl"]] = relationship(
        "EnquiryPriceCheckDtl", back_populates="price_check",
        foreign_keys="EnquiryPriceCheckDtl.price_check_id",
    )


class EnquiryPriceCheckDtl(Base):
    """Per-item price check line.

    last_po_rate / last_po_date / last_supplier_id are auto-prefilled at
    request time from get_last_purchase_rates_by_item_group (snapshot, so the
    answer is evidence-stable). confirmed_rate is procurement's answer. Per
    spec this dtl carries no active/audit columns.
    """
    __tablename__ = "enquiry_price_check_dtl"
    __table_args__ = (
        Index("idx_pc_dtl_hdr", "price_check_id"),
        Index("idx_pc_dtl_enquiry_line", "enquiry_dtl_id"),
        Index("idx_pc_dtl_item", "item_id"),
        CheckConstraint(
            "rate_source IS NULL OR rate_source IN ('last_po', 'supplier_quote', 'estimate')",
            name="chk_pc_dtl_rate_source",
        ),
    )

    price_check_dtl_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    price_check_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("enquiry_price_check.price_check_id"), nullable=False
    )
    enquiry_dtl_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("sales_enquiry_dtl.enquiry_dtl_id"), nullable=True
    )
    item_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("item_mst.item_id"), nullable=False
    )
    last_po_rate: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    last_po_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    last_supplier_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("party_mst.party_id"), nullable=True
    )
    confirmed_rate: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    rate_source: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    supplier_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("party_mst.party_id"), nullable=True
    )
    remarks: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Relationships
    price_check: Mapped[Optional["EnquiryPriceCheck"]] = relationship(
        "EnquiryPriceCheck", back_populates="details", foreign_keys=[price_check_id]
    )


# =============================================================================
# COMPANY x MENU ISO DOCUMENT NUMBER MAP
# =============================================================================

class CoMenuIsoMap(Base):
    """ISO document number per (company x menu) — generic and reusable across
    all modules/tenants (NOT AMCL-specific).

    Document view/print headers look up by the page's menu_id + selected
    co_id; if a row exists the ISO number is shown, otherwise the space stays
    blank. Unique (co_id, menu_id).
    """
    __tablename__ = "co_menu_iso_map"
    __table_args__ = (
        UniqueConstraint("co_id", "menu_id", name="uk_co_menu_iso"),
        Index("idx_co_menu_iso_menu", "menu_id"),
    )

    iso_map_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    co_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("co_mst.co_id"), nullable=False
    )
    menu_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("menu_mst.menu_id"), nullable=False
    )
    iso_doc_no: Mapped[str] = mapped_column(String(50), nullable=False)
    active: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    updated_by: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )
