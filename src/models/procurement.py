"""
SQLAlchemy ORM models for procurement tables (proc_*).
Auto-generated from database schema: sls
"""

from datetime import date, datetime
from typing import Optional, List

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Double,
    ForeignKey,
    Integer,
    String,
    Text,
    TIMESTAMP,
    func,
)
from sqlalchemy.orm import relationship, Mapped, mapped_column, DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all procurement models."""
    pass


# =============================================================================
# ENQUIRY MODELS
# =============================================================================

class ProcEnquiry(Base):
    """Price enquiry header table."""
    __tablename__ = "proc_enquiry"

    enquiry_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    co_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    updated_by: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )
    price_enquiry_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    price_enquiry_squence_no: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    enquiry_no: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    enquiry_type: Mapped[Optional[str]] = mapped_column(String(25), nullable=True, default="Regular")
    remarks: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    branch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    suppliers: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    terms_conditions: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    delivery_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    expense_type_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    project_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    approval_level: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    active: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # Relationships
    details: Mapped[List["ProcEnquiryDtl"]] = relationship(
        "ProcEnquiryDtl", back_populates="enquiry"
    )
    responses: Mapped[List["ProcPriceEnquiryResponse"]] = relationship(
        "ProcPriceEnquiryResponse", back_populates="enquiry"
    )
    enquiry_suppliers: Mapped[List["ProcEnquirySupplier"]] = relationship(
        "ProcEnquirySupplier", back_populates="enquiry"
    )


class ProcEnquiryDtl(Base):
    """Price enquiry detail/line items table."""
    __tablename__ = "proc_enquiry_dtl"

    enquiry_dtl_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    enquiry_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("proc_enquiry.enquiry_id"), nullable=True, index=True
    )
    indent_dtl_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    indent_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    item_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    item_make_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    dept_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    uom_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    qty: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    remarks: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    updated_by: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )
    active: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # Relationships
    enquiry: Mapped[Optional["ProcEnquiry"]] = relationship(
        "ProcEnquiry", back_populates="details"
    )


class ProcEnquirySupplier(Base):
    """Many-to-many junction between enquiry and suppliers."""
    __tablename__ = "proc_enquiry_supplier"

    enquiry_supplier_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    enquiry_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("proc_enquiry.enquiry_id"), nullable=False, index=True
    )
    supplier_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    supplier_branch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sent_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    sent_status: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_by: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )

    # Relationships
    enquiry: Mapped[Optional["ProcEnquiry"]] = relationship(
        "ProcEnquiry", back_populates="enquiry_suppliers"
    )


# =============================================================================
# GST MODEL
# =============================================================================

class ProcGst(Base):
    """GST details for procurement inward items and additional charges."""
    __tablename__ = "proc_gst"

    gst_invoice_type: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    proc_inward_dtl: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    proc_inward_additional_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    tax_pct: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    stax_percentage: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    s_tax_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    i_tax_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    i_tax_percentage: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    c_tax_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    c_tax_percentage: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    tax_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    active: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_by: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )


# =============================================================================
# INDENT MODELS
# =============================================================================

class ProcIndent(Base):
    """Purchase indent header table."""
    __tablename__ = "proc_indent"

    indent_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    indent_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    indent_no: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    active: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True, default=True)
    indent_type_id: Mapped[Optional[str]] = mapped_column(String(25), nullable=True)
    remarks: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    branch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    expense_type_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    project_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_by: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )
    status_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    indent_title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    dept_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    approval_level: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Relationships
    details: Mapped[List["ProcIndentDtl"]] = relationship(
        "ProcIndentDtl", back_populates="indent"
    )


class ProcIndentDtl(Base):
    """Purchase indent detail/line items table."""
    __tablename__ = "proc_indent_dtl"

    indent_dtl_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    indent_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("proc_indent.indent_id"), nullable=True, index=True
    )
    required_by_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    active: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True, default=True)
    item_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    qty: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    uom_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    remarks: Mapped[Optional[str]] = mapped_column(String(599), nullable=True)
    updated_by: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )
    item_make_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    dept_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    state: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Relationships
    indent: Mapped[Optional["ProcIndent"]] = relationship(
        "ProcIndent", back_populates="details"
    )
    cancellations: Mapped[List["ProcIndentDtlCancel"]] = relationship(
        "ProcIndentDtlCancel", back_populates="indent_dtl"
    )


class ProcIndentDtlCancel(Base):
    """Cancelled indent detail line items."""
    __tablename__ = "proc_indent_dtl_cancel"

    indent_dtl_cancel_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    indent_dtl_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("proc_indent_dtl.indent_dtl_id"), nullable=True, index=True
    )
    cancelled_by: Mapped[int] = mapped_column(Integer, nullable=False)
    cancelled_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )
    cancelled_qty: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    cancelled_reasons: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Relationships
    indent_dtl: Mapped[Optional["ProcIndentDtl"]] = relationship(
        "ProcIndentDtl", back_populates="cancellations"
    )


# =============================================================================
# INDENT OUTSTANDING VIEW
# =============================================================================

class VwProcIndentOutstanding(Base):
    """
    Read-only model for vw_proc_indent_outstanding view.
    Provides outstanding indent quantities per detail line, along with
    item min/max/reorder data from item_minmax_mst.
    """
    __tablename__ = "vw_proc_indent_outstanding"
    __table_args__ = {"extend_existing": True}

    # Primary key for ORM (view has no real PK, use indent_dtl_id)
    indent_dtl_id: Mapped[int] = mapped_column(Integer, primary_key=True)

    status_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    indent_no: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    item_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    item_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    uom_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    uom_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    indent_qty: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    Bal_ind_qty: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    expense_type_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    indent_type_id: Mapped[Optional[str]] = mapped_column(String(25), nullable=True)
    expense_type_name: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    bal_tot_ind_qty: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    minqty: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    maxqty: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    min_order_qty: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    lead_time: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


# =============================================================================
# NEW INDENT OUTSTANDING VIEW
# =============================================================================

class VwProcIndentOutstandingNew(Base):
    """
    Read-only model for vw_proc_indent_outstanding_new view.

    Provides outstanding indent quantities per detail line for approved/closed
    indents (status_id IN 3, 5). Joins proc_indent → proc_indent_dtl with
    cancellation and PO consumption adjustments.

    Key behaviour:
    - For 'Open' indent types: bal_ind_qty = indent_qty (full qty always
      outstanding since open indents are recurring/flexible).
    - For Regular/BOM types: bal_ind_qty = indent_qty − cancelled_qty − PO consumed qty
      (only POs in status 3 or 5 are counted as consumed).
    - Includes item_name, uom_name, and expense_type_name via joins.

    Used by the validation layer (Indent Logic 1/2, PO Logic 1/2) to look up
    outstanding indent quantities per branch+item without running ad-hoc queries.
    """
    __tablename__ = "vw_proc_indent_outstanding_new"
    __table_args__ = {"extend_existing": True}

    # PK for ORM (view has no real PK; indent_dtl_id is unique per row)
    indent_dtl_id: Mapped[int] = mapped_column(Integer, primary_key=True)

    branch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    indent_no: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    item_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    item_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    uom_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    uom_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    indent_qty: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    bal_ind_qty: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    expense_type_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    indent_type_id: Mapped[Optional[str]] = mapped_column(String(25), nullable=True)
    expense_type_name: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)


# =============================================================================
# NEW PO OUTSTANDING VIEW
# =============================================================================

class VwProcPoOutstandingNew(Base):
    """
    Read-only model for vw_proc_po_outstanding_new view.

    Provides outstanding PO quantities per PO detail line. Joins proc_po →
    proc_po_dtl with inward receipt and debit/credit note adjustments.

    Key columns:
    - bal_po_qty = po_qty − inward_qty + drcr_qty  (balance remaining on PO line)
    - po_type: 'Regular' or 'Open' (from proc_po.po_type)
    - maxqty, minqty, min_order_qty: from item_minmax_mst for the item
    - item_code, uom_name, expense_type_name: via joins for display

    Used by the validation layer (PO Logic 1/2, Open PO from indent) to look up
    outstanding PO quantities per branch+item without running ad-hoc queries.
    Also participates in the aggregate view vw_item_balance_qty_by_branch_new.
    """
    __tablename__ = "vw_proc_po_outstanding_new"
    __table_args__ = {"extend_existing": True}

    # PK for ORM (view has no real PK; po_dtl_id is unique per row)
    po_dtl_id: Mapped[int] = mapped_column(Integer, primary_key=True)

    branch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    po_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    po_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    po_approve_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    po_type: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    po_no: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    expense_type_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    expense_type_name: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    status_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    item_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    item_code: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    uom_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    uom_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    qty: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    rate: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    maxqty: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    minqty: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    min_order_qty: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    bal_po_qty: Mapped[Optional[float]] = mapped_column(Double, nullable=True)


# =============================================================================
# ITEM BALANCE QTY BY BRANCH VIEW (AGGREGATE)
# =============================================================================

class VwItemBalanceQtyByBranchNew(Base):
    """
    Read-only model for vw_item_balance_qty_by_branch_new view.

    Aggregate view that consolidates, per branch+item, the total outstanding
    indent quantities, outstanding PO quantities, item min/max/reorder settings,
    and current stock. This is the **primary view for min/max validation** on
    both Indent and PO creation screens.

    Driving table: ``item_minmax_mst`` — every item with a min/max configuration
    record appears in this view, even when it has zero indent outstanding, zero
    PO outstanding, and zero stock. The outstanding and stock tables are
    LEFT JOINed on top, so their columns default to 0 when no data exists.

    Columns — raw aggregates:
    - bal_tot_ind_qty: Total outstanding indent qty across all indent types
      (Regular + BOM + Open + Capital/Maintenance) for the branch+item.
    - open_bal_ind_tot_qty: Outstanding indent qty from Open-type indents only.
    - capital_maintance_bal_ind_tot_qty: Outstanding indent qty from
      Capital/Maintenance-type indents only. (Note: production typo "maintance".)
    - bal_qty_ind_to_validate: bal_tot_ind_qty − open_bal_ind_tot_qty.
      This is the outstanding indent qty from Regular/BOM indents (the portion
      that counts toward validation in Logic 1).
    - bal_tot_po_qty: Total outstanding PO qty across all PO types for the
      branch+item.
    - open_bal_tot_po_qty: Outstanding PO qty from Open-type POs only.
    - capital_maintainance_bal_tot_po_qty: Outstanding PO qty from
      Capital/Maintenance-type POs only. (Note: production spelling "maintainance".)
    - bal_qty_po_to_validate: PO equivalent of bal_qty_ind_to_validate — the
      outstanding PO qty used in validation (excludes Open/Capital POs).
    - maxqty: Max stock qty from item_minmax_mst (0 if not set).
    - minqty: Reorder point from item_minmax_mst (0 if not set).
    - min_order_qty: Minimum order batch size from item_minmax_mst (0 if not set).
    - cur_stock: Current stock at the branch, computed as:
      inward_qty − drcr_qty − issue_qty.

    Columns — pre-computed validation limits (added 2026-02-24):
    - max_indent_qty: Maximum indent qty allowed. Sentinel values:
        -2 = Open indent outstanding > 0 (UI: show warning)
        -1 = No min/max configured (UI: allow free entry)
        >= 0 = CEIL((maxqty - cur_stock - ind_outstanding - reg_po_outstanding)
               / min_order_qty) * min_order_qty
    - min_indent_qty: Minimum indent qty. Same sentinels as above.
        >= 0 = LEAST(CEIL(minqty / min_order_qty) * min_order_qty, max_indent_qty)
               i.e. minqty rounded UP to the nearest min_order_qty multiple,
               capped at max_indent_qty so min never exceeds max.
               If min_order_qty = 0: returned as raw minqty (no rounding).
    - max_po_qty: Maximum PO qty allowed. Sentinel values:
        -2 = Open PO outstanding > 0 (UI: show warning)
        -1 = No min/max configured (UI: allow free entry)
        >= 0 = Same formula as max_indent_qty
    - min_po_qty: Minimum PO qty. Same sentinels as above.
        >= 0 = LEAST(CEIL(minqty / min_order_qty) * min_order_qty, max_po_qty)
               Same rounding logic as min_indent_qty, capped at max_po_qty.

    Sentinel value reference:
    | Value | Meaning                           | UI action                    |
    |-------|-----------------------------------|------------------------------|
    | -2    | Open outstanding exists            | Display warning to user      |
    | -1    | No min/max configured              | Allow any quantity           |
    | >= 0  | Computed limit                     | Enforce min/max range        |

    Validation formula mapping (Indent Logic 1):
      outstanding_indent_qty  →  bal_qty_ind_to_validate
      branch_stock            →  cur_stock
      max_qty                 →  maxqty
      min_qty                 →  minqty
      reorder_qty             →  min_order_qty
      max_indent_allowed      →  max_indent_qty (pre-computed)
      min_indent_allowed      →  min_indent_qty (pre-computed)

    Validation formula mapping (Direct PO Logic 1):
      outstanding_indent_qty  →  bal_qty_ind_to_validate
      outstanding_po_qty      →  bal_tot_po_qty − open_bal_tot_po_qty
      branch_stock            →  cur_stock
      max_qty                 →  maxqty
      min_qty                 →  minqty
      reorder_qty             →  min_order_qty
      max_po_allowed          →  max_po_qty (pre-computed)
      min_po_allowed          →  min_po_qty (pre-computed)

    Source data:
    - Indent outstanding: aggregated from vw_proc_indent_outstanding_new
    - PO outstanding: aggregated from vw_proc_po_outstanding_new
    - Min/Max/Reorder: joined from item_minmax_mst
    - Current stock: computed from proc_inward_dtl − drcr_note_dtl − issue_li
    """
    __tablename__ = "vw_item_balance_qty_by_branch_new"
    __table_args__ = {"extend_existing": True}

    # Composite PK for ORM (view has no real PK; branch_id+item_id is unique)
    branch_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_id: Mapped[int] = mapped_column(Integer, primary_key=True)

    bal_tot_ind_qty: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    open_bal_ind_tot_qty: Mapped[Optional[float]] = mapped_column(
        "open_bal_Ind_tot_qty", Double, nullable=True
    )
    # Capital/maintenance outstanding indent qty (separate from Open/Regular/BOM breakdown)
    capital_maintance_bal_ind_tot_qty: Mapped[Optional[float]] = mapped_column(
        "capital_maintance_bal_Ind_tot_qty", Double, nullable=True
    )
    bal_qty_ind_to_validate: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    bal_tot_po_qty: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    open_bal_tot_po_qty: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    # Capital/maintenance outstanding PO qty (separate from Open/Regular breakdown)
    capital_maintainance_bal_tot_po_qty: Mapped[Optional[float]] = mapped_column(
        Double, nullable=True
    )
    # PO equivalent of bal_qty_ind_to_validate: outstanding PO qty used for validation
    bal_qty_po_to_validate: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    maxqty: Mapped[float] = mapped_column(Double, nullable=False, default=0)
    minqty: Mapped[float] = mapped_column(Double, nullable=False, default=0)
    min_order_qty: Mapped[float] = mapped_column(Double, nullable=False, default=0)
    cur_stock: Mapped[float] = mapped_column(Double, nullable=False, default=0)

    # --- Pre-computed validation columns (added 2026-02-24) ---
    # Sentinel values:
    #   -2 = Warning: open outstanding exists for this item+branch
    #        (open indent for indent cols, open PO for PO cols).
    #        UI should display a warning to the user.
    #   -1 = No min/max configured (maxqty = 0 or NULL).
    #        User may enter any quantity freely.
    #   >= 0 = Computed validation limit.
    #
    # Formula (when >= 0):
    #   regular_po_outstanding = bal_tot_po_qty − open_bal_tot_po_qty
    #   available = maxqty − cur_stock − bal_qty_ind_to_validate − regular_po_outstanding
    #   max = CEIL(GREATEST(available, 0) / min_order_qty) * min_order_qty
    #   min = LEAST(CEIL(minqty / min_order_qty) * min_order_qty, max)
    #         i.e. minqty rounded UP to nearest min_order_qty multiple, capped at max.
    #
    # If min_order_qty is 0: max = raw available, min = raw minqty (no rounding).

    max_indent_qty: Mapped[float] = mapped_column(Double, nullable=False, default=0)
    min_indent_qty: Mapped[float] = mapped_column(Double, nullable=False, default=0)
    max_po_qty: Mapped[float] = mapped_column(Double, nullable=False, default=0)
    min_po_qty: Mapped[float] = mapped_column(Double, nullable=False, default=0)


# =============================================================================
# INWARD MODELS
# =============================================================================

class ProcInward(Base):
    """Goods inward/receipt header table."""
    __tablename__ = "proc_inward"

    inward_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    inward_sequence_no: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    supplier_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    supplier_branch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    vehicle_number: Mapped[Optional[str]] = mapped_column(String(25), nullable=True)
    driver_name: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    driver_contact_number: Mapped[Optional[str]] = mapped_column(String(25), nullable=True)
    inward_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    despatch_remarks: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    receipts_remarks: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )
    updated_by: Mapped[int] = mapped_column(Integer, nullable=False)
    invoice_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    invoice_recvd_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    invoice_due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    invoice_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    invoice_no: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    challan_no: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    challan_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    consignment_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    consignment_no: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    ewaybillno: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    ewaybill_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    bill_branch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    ship_branch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    inspection_check: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    inspection_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    inspection_approved_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sr_no: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    sr_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    sr_approved_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sr_value: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    sr_remarks: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    sr_status: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    billpass_no: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    billpass_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    billpass_approve_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    billpass_approved_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    billpass_status: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    round_off_value: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    branch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    project_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    internal_no: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    customer_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    gross_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    net_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)

    # Relationships
    details: Mapped[List["ProcInwardDtl"]] = relationship(
        "ProcInwardDtl", back_populates="inward"
    )
    additional_charges: Mapped[List["ProcInwardAdditional"]] = relationship(
        "ProcInwardAdditional", back_populates="inward"
    )
    tds_details: Mapped[List["ProcTds"]] = relationship(
        "ProcTds", back_populates="inward"
    )
    drcr_notes: Mapped[List["DrcrNote"]] = relationship(
        "DrcrNote", back_populates="inward"
    )


class ProcInwardAdditional(Base):
    """Additional charges for inward/SR documents (freight, insurance, etc.)."""
    __tablename__ = "proc_inward_additional"

    proc_inward_additional_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    inward_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    additional_charges_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    qty: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    rate: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    net_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    remarks: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)


class ProcInwardDtl(Base):
    """Goods inward/receipt detail/line items table."""
    __tablename__ = "proc_inward_dtl"

    inward_dtl_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    inward_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("proc_inward.inward_id"), nullable=False, index=True
    )
    po_dtl_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # bigint in DB
    item_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    item_make_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    accepted_item_make_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    hsn_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    remarks: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    challan_qty: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    inward_qty: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    approved_qty: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    rejected_qty: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    reasons: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    uom_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    rate: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    accepted_rate: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    discount_mode: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    discount_value: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    discount_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    warehouse_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    updated_date_time: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
    updated_by: Mapped[int] = mapped_column(Integer, nullable=False)

    # Relationships
    inward: Mapped["ProcInward"] = relationship(
        "ProcInward", back_populates="details"
    )
    drcr_note_details: Mapped[List["DrcrNoteDtl"]] = relationship(
        "DrcrNoteDtl", back_populates="inward_dtl"
    )


# =============================================================================
# PURCHASE ORDER (PO) MODELS
# =============================================================================

class ProcPo(Base):
    """Purchase order header table."""
    __tablename__ = "proc_po"

    po_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    updated_by: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )
    credit_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    delivery_instructions: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    expected_delivery_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    footer_notes: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    po_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    po_approve_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    po_no: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    remarks: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    delivery_mode: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    terms_conditions: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    branch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    price_enquiry_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    project_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    supplier_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    supplier_branch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    billing_branch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    shipping_branch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    total_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    net_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    advance_type: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    advance_value: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    advance_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    contact_no: Mapped[Optional[str]] = mapped_column(String(25), nullable=True)
    contact_person: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    approval_level: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    expense_type_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Relationships
    details: Mapped[List["ProcPoDtl"]] = relationship(
        "ProcPoDtl", back_populates="po"
    )
    additional_charges: Mapped[List["ProcPoAdditional"]] = relationship(
        "ProcPoAdditional", back_populates="po"
    )


class ProcPoDtl(Base):
    """Purchase order detail/line items table."""
    __tablename__ = "proc_po_dtl"

    po_dtl_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    po_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("proc_po.po_id"), nullable=True, index=True
    )
    item_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    hsn_code: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    item_make_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    qty: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    rate: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    uom_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    remarks: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    discount_mode: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    discount_value: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    discount_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    active: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    indent_dtl_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    updated_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_date_time: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
    state: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Relationships
    po: Mapped[Optional["ProcPo"]] = relationship(
        "ProcPo", back_populates="details"
    )
    cancellations: Mapped[List["ProcPoDtlCancel"]] = relationship(
        "ProcPoDtlCancel", back_populates="po_dtl"
    )
    gst_details: Mapped[List["PoGst"]] = relationship(
        "PoGst", back_populates="po_dtl"
    )


class ProcPoAdditional(Base):
    """Purchase order additional charges table."""
    __tablename__ = "proc_po_additional"

    po_additional_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    po_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("proc_po.po_id"), nullable=True, index=True
    )
    additional_charges_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    qty: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    rate: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    net_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    remarks: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    updated_by: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )

    # Relationships
    po: Mapped[Optional["ProcPo"]] = relationship(
        "ProcPo", back_populates="additional_charges"
    )
    gst_details: Mapped[List["PoGst"]] = relationship(
        "PoGst", back_populates="po_additional"
    )


class ProcPoDtlCancel(Base):
    """Cancelled purchase order detail line items."""
    __tablename__ = "proc_po_dtl_cancel"

    po_dtl_cancel_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    po_dtl_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("proc_po_dtl.po_dtl_id"), nullable=True, index=True
    )
    cancel_qty: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    cancel_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    cancel_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_by: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )

    # Relationships
    po_dtl: Mapped[Optional["ProcPoDtl"]] = relationship(
        "ProcPoDtl", back_populates="cancellations"
    )


# =============================================================================
# PRICE ENQUIRY RESPONSE MODELS
# =============================================================================

class ProcPriceEnquiryResponse(Base):
    """Price enquiry response header table."""
    __tablename__ = "proc_price_enquiry_response"

    proc_price_enquiry_response_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    enquiry_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("proc_enquiry.enquiry_id"), nullable=True, index=True
    )
    response_date: Mapped[Optional[date]] = mapped_column("date", Date, nullable=True)
    updated_by: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )
    created_by_ip: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    supplier_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    supplier_branch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    credit_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    delivery_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    payment_terms: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    terms_conditions: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    remarks: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    gross_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    net_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    is_selected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # Relationships
    enquiry: Mapped[Optional["ProcEnquiry"]] = relationship(
        "ProcEnquiry", back_populates="responses"
    )
    details: Mapped[List["ProcPriceEnquiryResponseDtl"]] = relationship(
        "ProcPriceEnquiryResponseDtl", back_populates="response"
    )


class ProcPriceEnquiryResponseDtl(Base):
    """Price enquiry response detail/line items table."""
    __tablename__ = "proc_price_enquiry_response_dtl"

    proc_price_enquiry_response_dtl_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    proc_price_enquiry_response_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("proc_price_enquiry_response.proc_price_enquiry_response_id"),
        nullable=True, index=True
    )
    enquiry_dtl_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    item_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    item_make_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    uom_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    qty: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    rate: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    discount_mode: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    discount_value: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    discount_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    gross_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    net_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    active: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_by: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )

    # Relationships
    response: Mapped[Optional["ProcPriceEnquiryResponse"]] = relationship(
        "ProcPriceEnquiryResponse", back_populates="details"
    )


# =============================================================================
# TDS MODEL
# =============================================================================

class ProcTds(Base):
    """TDS (Tax Deducted at Source) details for procurement inward."""
    __tablename__ = "proc_tds"

    proc_tds_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    inward_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("proc_inward.inward_id"), nullable=True
    )
    itc_applicable: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    tds_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    tds_pctg: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    tds_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    tcs_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    updated_by: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )

    # Relationships
    inward: Mapped[Optional["ProcInward"]] = relationship(
        "ProcInward", back_populates="tds_details"
    )


# =============================================================================
# TRANSFER MODELS
# =============================================================================

class ProcTransfer(Base):
    """Stock/material transfer header table."""
    __tablename__ = "proc_transfer"

    transfer_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    transfer_type: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    transfer_no: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    transfer_sequence_no: Mapped[Optional[str]] = mapped_column(String(25), nullable=True)
    transfer_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    branch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    scrap: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    updated_by: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )
    approved_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    approved_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    remarks: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)

    # Relationships
    details: Mapped[List["ProcTransferDtl"]] = relationship(
        "ProcTransferDtl", back_populates="transfer"
    )


class ProcTransferDtl(Base):
    """Stock/material transfer detail/line items table."""
    __tablename__ = "proc_transfer_dtl"

    transfer_dtl_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    transfer_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("proc_transfer.transfer_id"), nullable=True, index=True
    )
    item_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    uom_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    qty: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    to_branch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    from_warehouse_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    to_warehouse_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    active: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    updated_by: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )

    # Relationships
    transfer: Mapped[Optional["ProcTransfer"]] = relationship(
        "ProcTransfer", back_populates="details"
    )


# =============================================================================
# PO GST MODEL
# =============================================================================

class PoGst(Base):
    """GST details for purchase order items and additional charges."""
    __tablename__ = "po_gst"

    po_gst_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    po_dtl_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("proc_po_dtl.po_dtl_id"), nullable=True, index=True
    )
    po_additional_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("proc_po_additional.po_additional_id"), nullable=True, index=True
    )
    tax_pct: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    stax_percentage: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    s_tax_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    i_tax_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    i_tax_percentage: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    c_tax_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    c_tax_percentage: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    tax_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    active: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # Relationships
    po_dtl: Mapped[Optional["ProcPoDtl"]] = relationship(
        "ProcPoDtl", back_populates="gst_details"
    )
    po_additional: Mapped[Optional["ProcPoAdditional"]] = relationship(
        "ProcPoAdditional", back_populates="gst_details"
    )


# =============================================================================
# DEBIT/CREDIT NOTE MODELS
# =============================================================================

class DrcrNote(Base):
    """Debit/Credit note header table."""
    __tablename__ = "drcr_note"

    debit_credit_note_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    note_date: Mapped[Optional[date]] = mapped_column("date", Date, nullable=True)
    adjustment_type: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    inward_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("proc_inward.inward_id"), nullable=True, index=True
    )
    remarks: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    auto_create: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )
    approved_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    approved_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    gross_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    net_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    round_off_value: Mapped[Optional[float]] = mapped_column(Double, nullable=True)

    # Relationships
    inward: Mapped[Optional["ProcInward"]] = relationship(
        "ProcInward", back_populates="drcr_notes"
    )
    details: Mapped[List["DrcrNoteDtl"]] = relationship(
        "DrcrNoteDtl", back_populates="drcr_note"
    )


class DrcrNoteDtl(Base):
    """Debit/Credit note detail/line items table."""
    __tablename__ = "drcr_note_dtl"

    drcr_note_dtl_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    debit_credit_note_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("drcr_note.debit_credit_note_id"), nullable=False, index=True
    )
    inward_dtl_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("proc_inward_dtl.inward_dtl_id"), nullable=True, index=True
    )
    debitnote_type: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    quantity: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    rate: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    discount_mode: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    discount_value: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    discount_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    updated_by: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )

    # Relationships
    drcr_note: Mapped[Optional["DrcrNote"]] = relationship(
        "DrcrNote", back_populates="details", foreign_keys="DrcrNoteDtl.debit_credit_note_id"
    )
    inward_dtl: Mapped[Optional["ProcInwardDtl"]] = relationship(
        "ProcInwardDtl", back_populates="drcr_note_details"
    )
    gst_details: Mapped[List["DrcrNoteDtlGst"]] = relationship(
        "DrcrNoteDtlGst", back_populates="drcr_note_dtl"
    )


class DrcrNoteDtlGst(Base):
    """GST details for debit/credit note line items."""
    __tablename__ = "drcr_note_dtl_gst"

    drcr_note_dtl_gst_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    drcr_note_dtl_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("drcr_note_dtl.drcr_note_dtl_id"), nullable=True, index=True
    )
    cgst_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    igst_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    sgst_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    active: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

    # Relationships
    drcr_note_dtl: Mapped[Optional["DrcrNoteDtl"]] = relationship(
        "DrcrNoteDtl", back_populates="gst_details"
    )


# =============================================================================
# CONVENIENCE EXPORTS
# =============================================================================

__all__ = [
    "Base",
    # Enquiry
    "ProcEnquiry",
    "ProcEnquiryDtl",
    # GST
    "ProcGst",
    # Indent
    "ProcIndent",
    "ProcIndentDtl",
    "ProcIndentDtlCancel",
    # Indent Outstanding View (legacy)
    "VwProcIndentOutstanding",
    # New Validation Views
    "VwProcIndentOutstandingNew",
    "VwProcPoOutstandingNew",
    "VwItemBalanceQtyByBranchNew",
    # Inward
    "ProcInward",
    "ProcInwardDtl",
    "ProcInwardAdditional",
    # PO
    "ProcPo",
    "ProcPoDtl",
    "ProcPoAdditional",
    "ProcPoDtlCancel",
    # PO GST
    "PoGst",
    # Price Enquiry Response
    "ProcPriceEnquiryResponse",
    "ProcPriceEnquiryResponseDtl",
    # TDS
    "ProcTds",
    # Transfer
    "ProcTransfer",
    "ProcTransferDtl",
    # Debit/Credit Notes
    "DrcrNote",
    "DrcrNoteDtl",
    "DrcrNoteDtlGst",
]
