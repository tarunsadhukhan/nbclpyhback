"""
SQLAlchemy ORM models for sales tables.
Covers: quotation, order, delivery order, and invoice.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Optional, List

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Double,
    Float,
    ForeignKey,
    Integer,
    BigInteger,
    String,
    Text,
    DECIMAL,
    TIMESTAMP,
    func,
)
from sqlalchemy.orm import relationship, Mapped, mapped_column, DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all sales models."""
    pass


# =============================================================================
# INVOICE MODELS
# =============================================================================

class InvoiceHdr(Base):
    """Invoice header table."""
    __tablename__ = "sales_invoice"

    invoice_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    invoice_no: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    invoice_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    invoice_type: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    invoice_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    branch_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, index=True)
    party_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, index=True)
    billing_to_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    shipping_to_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    sales_delivery_order_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("sales_delivery_order.sales_delivery_order_id"), nullable=True, index=True
    )
    broker_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    challan_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    challan_no: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    footer_notes: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    internal_note: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    freight_charges: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    intra_inter_state: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    active: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    shipping_state_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    approval_level: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=0)
    tax_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    tax_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    tax_payable: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    terms: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    terms_conditions: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    type_of_sale: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    updated_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_date_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, server_default=func.current_timestamp()
    )
    vehicle_no: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    transporter_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    transporter_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    transporter_address: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    transporter_state_code: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    transporter_state_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    transporter_branch_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("party_branch_mst.party_mst_branch_id"),
        nullable=True
    )
    transporter_doc_no: Mapped[str | None] = mapped_column(String(255), nullable=True)
    transporter_doc_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    buyer_order_no: Mapped[str | None] = mapped_column(String(255), nullable=True)
    buyer_order_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    irn: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ack_no: Mapped[str | None] = mapped_column(String(100), nullable=True)
    ack_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    qr_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    container_no: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    contract_no: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    contract_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    consignment_no: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    consignment_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    eway_bill_no: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    eway_bill_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    round_off: Mapped[Decimal] = mapped_column(DECIMAL(10, 2), nullable=False, default=Decimal("0.00"))
    payment_terms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sales_order_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("sales_order.sales_order_id"), nullable=True, index=True
    )
    billing_state_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    bank_detail_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    # Relationships
    line_items: Mapped[List["InvoiceLineItem"]] = relationship(
        "InvoiceLineItem", back_populates="invoice", lazy="selectin"
    )
    delivery_order: Mapped[Optional["SalesDeliveryOrder"]] = relationship("SalesDeliveryOrder")
    govtskg: Mapped[Optional["SaleInvoiceGovtskg"]] = relationship(
        "SaleInvoiceGovtskg", back_populates="invoice", uselist=False
    )
    jute: Mapped[Optional["SaleInvoiceJute"]] = relationship(
        "SaleInvoiceJute", back_populates="invoice", uselist=False
    )
    invoice_jute: Mapped[Optional["SalesInvoiceJute"]] = relationship(
        "SalesInvoiceJute", back_populates="invoice", uselist=False
    )
    hessian: Mapped[Optional["SalesInvoiceHessian"]] = relationship(
        "SalesInvoiceHessian", back_populates="invoice", uselist=False
    )
    juteyarn: Mapped[Optional["SalesInvoiceJuteYarn"]] = relationship(
        "SalesInvoiceJuteYarn", back_populates="invoice", uselist=False
    )
    freight: Mapped[Optional["SalesInvoiceFreight"]] = relationship(
        "SalesInvoiceFreight", back_populates="invoice",
        foreign_keys="SalesInvoiceFreight.invoice_id", uselist=False
    )
    additional_charges: Mapped[List["SalesInvoiceAdditional"]] = relationship(
        "SalesInvoiceAdditional", back_populates="invoice"
    )
    e_invoice_responses: Mapped[list["EInvoiceResponse"]] = relationship(
        "EInvoiceResponse",
        back_populates="invoice",
        cascade="all, delete-orphan"
    )


class InvoiceLineItem(Base):
    """Sales invoice detail/line items table."""
    __tablename__ = "sales_invoice_dtl"

    invoice_line_item_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    amount_without_tax: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    hsn_code: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    invoice_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("sales_invoice.invoice_id"), nullable=True, index=True
    )
    item_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    item_make_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    quantity: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    rate: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    total_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    uom_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sales_weight: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    invoice_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("sales_invoice.invoice_id"), nullable=True, index=True
    )
    hsn_code: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    item_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    item_make_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    quantity: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    uom_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    rate: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    discount_type: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    discounted_rate: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    discount_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    amount_without_tax: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    total_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    sales_weight: Mapped[Optional[float]] = mapped_column(Float, nullable=True, default=0)
    remarks: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    delivery_order_dtl_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sales_order_dtl_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Relationships
    invoice: Mapped[Optional["InvoiceHdr"]] = relationship(
        "InvoiceHdr", back_populates="line_items"
    )
    gst_details: Mapped[List["SalesInvoiceDtlGst"]] = relationship(
        "SalesInvoiceDtlGst", back_populates="invoice_line_item"
    )
    jute_dtl: Mapped[List["SalesInvoiceJuteDtl"]] = relationship(
        "SalesInvoiceJuteDtl", back_populates="invoice_line_item"
    )
    hessian_dtl: Mapped[Optional["SalesInvoiceHessianDtl"]] = relationship(
        "SalesInvoiceHessianDtl", back_populates="invoice_line_item", uselist=False
    )
    juteyarn_dtl: Mapped[Optional["SalesInvoiceJuteYarnDtl"]] = relationship(
        "SalesInvoiceJuteYarnDtl", back_populates="invoice_line_item", uselist=False
    )
    govtskg_dtl: Mapped[Optional["SaleInvoiceGovtskgDtl"]] = relationship(
        "SaleInvoiceGovtskgDtl", back_populates="invoice_line_item", uselist=False
    )


class SaleInvoiceGovtskg(Base):
    """Government/SKG-specific fields for sales invoices (shifted from sales_invoice)."""
    __tablename__ = "sales_invoice_govtskg"

    sale_invoice_govtskg_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    invoice_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("sales_invoice.invoice_id"), nullable=True, index=True
    )
    pcso_no: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    pcso_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    administrative_office_address: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    destination_rail_head: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    loading_point: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    mode_of_transport: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    pack_sheet: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(10, 3), nullable=True)
    net_weight: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(10, 3), nullable=True)
    total_weight: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(10, 3), nullable=True)

    # Relationships
    invoice: Mapped[Optional["InvoiceHdr"]] = relationship(
        "InvoiceHdr", back_populates="govtskg"
    )


class SalesInvoiceFreight(Base):
    """Freight-specific fields for Govt Sacking Freight sales invoices (type 7)."""
    __tablename__ = "sales_invoice_freight"

    sales_invoice_freight_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    invoice_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sales_invoice.invoice_id"), nullable=False, index=True
    )
    source_invoice_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sales_invoice.invoice_id"), nullable=False, index=True
    )
    iw_bill_no: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    iw_bill_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    updated_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_date_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, server_default=func.current_timestamp()
    )

    # Relationships
    invoice: Mapped[Optional["InvoiceHdr"]] = relationship(
        "InvoiceHdr", back_populates="freight", foreign_keys=[invoice_id]
    )


class SalesInvoiceJute(Base):
    """Jute-specific header fields for sales invoices (table: sales_invoice_jute)."""
    __tablename__ = "sales_invoice_jute"

    sales_invoice_jute_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    invoice_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("sales_invoice.invoice_id"), nullable=True, index=True
    )
    mr_no: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    mr_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    claim_amount: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(12, 2), nullable=True)
    other_reference: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    unit_conversion: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    claim_description: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    mukam_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Relationships
    invoice: Mapped[Optional["InvoiceHdr"]] = relationship(
        "InvoiceHdr", back_populates="invoice_jute"
    )


class SalesInvoiceJuteDtl(Base):
    """Jute-specific detail fields for invoice line items (table: sales_invoice_jute_dtl)."""
    __tablename__ = "sales_invoice_jute_dtl"

    sales_invoice_jute_dtl_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    invoice_line_item_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("sales_invoice_dtl.invoice_line_item_id"), nullable=True
    )
    claim_amount_dtl: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    claim_desc: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    claim_rate: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    unit_conversion: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    qty_untit_conversion: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # production typo — do not rename

    # Relationships
    invoice_line_item: Mapped[Optional["InvoiceLineItem"]] = relationship(
        "InvoiceLineItem", back_populates="jute_dtl"
    )


class SalesInvoiceDtlGst(Base):
    """GST breakdown for sales invoice line items (table: sales_invoice_dtl_gst)."""
    __tablename__ = "sales_invoice_dtl_gst"

    sales_invoice_dtl_gst_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    invoice_line_item_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("sales_invoice_dtl.invoice_line_item_id"), nullable=True
    )
    tax_percentage: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(5, 2), nullable=True)
    cgst_amount: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(10, 2), nullable=True)
    sgst_amount: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(10, 2), nullable=True)
    igst_amount: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(10, 2), nullable=True)
    cgst_percentage: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(5, 2), nullable=True)
    sgst_percentage: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(5, 2), nullable=True)
    igst_percentage: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(5, 2), nullable=True)
    tax_amount: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(10, 2), nullable=True)

    # Relationships
    invoice_line_item: Mapped[Optional["InvoiceLineItem"]] = relationship(
        "InvoiceLineItem", back_populates="gst_details"
    )


class InvoiceTypeMst(Base):
    """Invoice type master table."""
    __tablename__ = "invoice_type_mst"

    invoice_type_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    invoice_type_name: Mapped[str] = mapped_column(String(100), nullable=False)

    # Relationships
    company_mappings: Mapped[List["InvoiceTypeCoMap"]] = relationship(
        "InvoiceTypeCoMap", back_populates="invoice_type"
    )


class InvoiceTypeCoMap(Base):
    """Mapping table between invoice type and company."""
    __tablename__ = "invoice_type_co_map"

    invoice_type_co_map_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    co_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    invoice_type_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("invoice_type_mst.invoice_type_id"), nullable=False, index=True
    )
    active: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )

    # Relationships
    invoice_type: Mapped["InvoiceTypeMst"] = relationship(
        "InvoiceTypeMst", back_populates="company_mappings"
    )


# =============================================================================
# SALES QUOTATION MODELS
# =============================================================================

class SalesQuotation(Base):
    """Sales quotation header table."""
    __tablename__ = "sales_quotation"

    sales_quotation_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    updated_by: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )
    quotation_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    quotation_no: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    branch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    party_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    sales_broker_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    billing_address_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    shipping_address_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    quotation_expiry_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    footer_notes: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    brokerage_percentage: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    gross_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    net_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    round_off_value: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    payment_terms: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    delivery_terms: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    delivery_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    terms_condition: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    internal_note: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    approval_level: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=0)
    active: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # AMCL enquiry flow: quote traces to enquiry (model in src/models/enquiry.py)
    sales_enquiry_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("sales_enquiry.sales_enquiry_id"), nullable=True, index=True
    )

    # Relationships
    details: Mapped[List["SalesQuotationDtl"]] = relationship(
        "SalesQuotationDtl", back_populates="quotation"
    )


class SalesQuotationDtl(Base):
    """Sales quotation detail/line items table."""
    __tablename__ = "sales_quotation_dtl"

    quotation_lineitem_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    updated_by: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )
    sales_quotation_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("sales_quotation.sales_quotation_id"), nullable=True, index=True
    )
    hsn_code: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    item_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    item_make_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    quantity: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    uom_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    rate: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    discount_type: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    discounted_rate: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    discount_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    net_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    total_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    remarks: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    active: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # AMCL enquiry flow: auto-pricing cost basis on the quote line
    # (rate prefilled = base_cost x (1 + overhead_pct/100) x (1 + margin_pct/100), editable).
    # Logical references only — no FK constraints, mirroring quotation_lineitem_id loose-coupling.
    enquiry_dtl_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    cost_snapshot_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    base_cost: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    overhead_pct: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    margin_pct: Mapped[Optional[float]] = mapped_column(Double, nullable=True)

    # Relationships
    quotation: Mapped[Optional["SalesQuotation"]] = relationship(
        "SalesQuotation", back_populates="details"
    )
    gst_details: Mapped[List["SalesQuotationDtlGst"]] = relationship(
        "SalesQuotationDtlGst", back_populates="quotation_dtl"
    )


class SalesQuotationDtlGst(Base):
    """GST details for sales quotation line items."""
    __tablename__ = "sales_quotation_dtl_gst"

    sales_quotation_dtl_gst_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    quotation_lineitem_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("sales_quotation_dtl.quotation_lineitem_id"), nullable=True, index=True
    )
    igst_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    igst_percent: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    cgst_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    cgst_percent: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    sgst_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    sgst_percent: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    gst_total: Mapped[Optional[float]] = mapped_column(Double, nullable=True)

    # Relationships
    quotation_dtl: Mapped[Optional["SalesQuotationDtl"]] = relationship(
        "SalesQuotationDtl", back_populates="gst_details"
    )


# =============================================================================
# SALES ORDER MODELS
# =============================================================================

class SalesOrder(Base):
    """Sales order header table."""
    __tablename__ = "sales_order"

    sales_order_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    updated_by: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )
    sales_order_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    sales_no: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    invoice_type: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    branch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    quotation_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("sales_quotation.sales_quotation_id"), nullable=True, index=True
    )
    party_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    broker_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    billing_to_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    shipping_to_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    transporter_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sales_order_expiry_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    broker_commission_percent: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    footer_note: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    terms_conditions: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    internal_note: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    delivery_terms: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    payment_terms: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    delivery_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    freight_charges: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    gross_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    net_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    status_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    approval_level: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=0)
    active: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    buyer_order_no: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    buyer_order_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    # AMCL enquiry flow: committed delivery + advance commitment, and the SO's own
    # enquiry link for the direct/tender path (order without a quotation).
    committed_delivery_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    advance_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    advance_note: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    sales_enquiry_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("sales_enquiry.sales_enquiry_id"), nullable=True, index=True
    )

    # Relationships
    quotation: Mapped[Optional["SalesQuotation"]] = relationship("SalesQuotation")
    details: Mapped[List["SalesOrderDtl"]] = relationship(
        "SalesOrderDtl", back_populates="order"
    )
    jute: Mapped[Optional["SalesOrderJute"]] = relationship(
        "SalesOrderJute", back_populates="order", uselist=False
    )
    juteyarn: Mapped[Optional["SalesOrderJuteYarn"]] = relationship(
        "SalesOrderJuteYarn", back_populates="order", uselist=False
    )
    govtskg: Mapped[Optional["SalesOrderGovtskg"]] = relationship(
        "SalesOrderGovtskg", back_populates="order", uselist=False
    )
    additional_charges: Mapped[List["SalesOrderAdditional"]] = relationship(
        "SalesOrderAdditional", back_populates="order"
    )


class SalesOrderDtl(Base):
    """Sales order detail/line items table."""
    __tablename__ = "sales_order_dtl"

    sales_order_dtl_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    updated_by: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )
    sales_order_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("sales_order.sales_order_id"), nullable=True, index=True
    )
    quotation_lineitem_id: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, index=True
    )
    hsn_code: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    item_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    item_make_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    quantity: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    uom_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    rate: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    discount_type: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    discounted_rate: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    discount_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    net_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    total_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    remarks: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    active: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # Relationships
    order: Mapped[Optional["SalesOrder"]] = relationship(
        "SalesOrder", back_populates="details"
    )
    gst_details: Mapped[List["SalesOrderDtlGst"]] = relationship(
        "SalesOrderDtlGst", back_populates="order_dtl"
    )
    hessian: Mapped[Optional["SalesOrderDtlHessian"]] = relationship(
        "SalesOrderDtlHessian", back_populates="order_dtl", uselist=False
    )
    jute_dtl: Mapped[Optional["SalesOrderJuteDtl"]] = relationship(
        "SalesOrderJuteDtl", back_populates="order_dtl", uselist=False
    )
    govtskg_dtl: Mapped[Optional["SalesOrderGovtskgDtl"]] = relationship(
        "SalesOrderGovtskgDtl", back_populates="order_dtl", uselist=False
    )


class SalesOrderDtlGst(Base):
    """GST details for sales order line items."""
    __tablename__ = "sales_order_dtl_gst"

    sales_order_dtl_gst_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sales_order_dtl_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("sales_order_dtl.sales_order_dtl_id"), nullable=True, index=True
    )
    igst_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    igst_percent: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    cgst_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    cgst_percent: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    sgst_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    sgst_percent: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    gst_total: Mapped[Optional[float]] = mapped_column(Double, nullable=True)

    # Relationships
    order_dtl: Mapped[Optional["SalesOrderDtl"]] = relationship(
        "SalesOrderDtl", back_populates="gst_details"
    )


class SalesOrderDtlHessian(Base):
    """Hessian-specific fields for sales order line items (invoice_type=2).

    Stores bale-based quantities and pre-brokerage rate derivatives.
    The main sales_order_dtl stores MT values (qty in MT, rate = billing rate per MT).
    """
    __tablename__ = "sales_order_dtl_hessian"

    sales_order_dtl_hessian_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sales_order_dtl_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sales_order_dtl.sales_order_dtl_id"), nullable=False, unique=True, index=True
    )
    qty_bales: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    rate_per_bale: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    billing_rate_mt: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    billing_rate_bale: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    updated_by: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )

    # Relationships
    order_dtl: Mapped[Optional["SalesOrderDtl"]] = relationship(
        "SalesOrderDtl", back_populates="hessian"
    )


class SalesOrderJute(Base):
    """Jute-specific header fields for sales orders (invoice_type=4)."""
    __tablename__ = "sales_order_jute"

    sales_order_jute_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sales_order_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("sales_order.sales_order_id"), nullable=True, index=True
    )
    mr_no: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    mr_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    claim_amount: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(12, 2), nullable=True)
    other_reference: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    unit_conversion: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    claim_description: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    mukam_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_by: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )

    # Relationships
    order: Mapped[Optional["SalesOrder"]] = relationship(
        "SalesOrder", back_populates="jute"
    )


class SalesOrderJuteDtl(Base):
    """Jute-specific detail fields for sales order line items (invoice_type=4)."""
    __tablename__ = "sales_order_jute_dtl"

    sales_order_jute_dtl_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sales_order_dtl_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("sales_order_dtl.sales_order_dtl_id"), nullable=True, index=True
    )
    claim_amount_dtl: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    claim_desc: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    claim_rate: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    unit_conversion: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    qty_untit_conversion: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # production typo — do not rename
    updated_by: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )

    # Relationships
    order_dtl: Mapped[Optional["SalesOrderDtl"]] = relationship(
        "SalesOrderDtl", back_populates="jute_dtl"
    )


class SalesOrderJuteYarn(Base):
    """Jute Yarn-specific header fields for sales orders (invoice_type=3)."""
    __tablename__ = "sales_order_juteyarn"

    sales_order_juteyarn_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sales_order_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("sales_order.sales_order_id"), nullable=True, index=True
    )
    pcso_no: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    container_no: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    customer_ref_no: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    updated_by: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )

    # Relationships
    order: Mapped[Optional["SalesOrder"]] = relationship(
        "SalesOrder", back_populates="juteyarn"
    )


class SalesOrderGovtskg(Base):
    """Govt SKG-specific header fields for sales orders (invoice_type=5)."""
    __tablename__ = "sales_order_govtskg"

    sales_order_govtskg_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sales_order_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("sales_order.sales_order_id"), nullable=True, index=True
    )
    pcso_no: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    pcso_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    administrative_office_address: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    destination_rail_head: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    loading_point: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    mode_of_transport: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    updated_by: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )

    # Relationships
    order: Mapped[Optional["SalesOrder"]] = relationship(
        "SalesOrder", back_populates="govtskg"
    )


class SalesOrderGovtskgDtl(Base):
    """Govt SKG-specific detail fields for sales order line items (invoice_type=5)."""
    __tablename__ = "sales_order_govtskg_dtl"

    sales_order_govtskg_dtl_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sales_order_dtl_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("sales_order_dtl.sales_order_dtl_id"), nullable=True, index=True
    )
    pack_sheet: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    net_weight: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    total_weight: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    updated_by: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )

    # Relationships
    order_dtl: Mapped[Optional["SalesOrderDtl"]] = relationship(
        "SalesOrderDtl", back_populates="govtskg_dtl"
    )


# =============================================================================
# GOVT SKG TRANSPORT CHARGE RATE CONFIG
# =============================================================================


class GovtskgTransportChargeRate(Base):
    """Configurable charge rates per mode of transport for Govt Sacking."""
    __tablename__ = "govtskg_transport_charge_rate"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mode_of_transport: Mapped[str] = mapped_column(String(20), nullable=False)
    additional_charges_id: Mapped[int] = mapped_column(Integer, nullable=False)
    rate_per_100pcs: Mapped[float] = mapped_column(Double, nullable=False, default=0)
    active: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    co_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


# =============================================================================
# SALES ORDER / INVOICE ADDITIONAL CHARGES
# =============================================================================

class SalesOrderAdditional(Base):
    """Additional charges for sales orders (freight, printing, handling, etc.)."""
    __tablename__ = "sales_order_additional"

    sales_order_additional_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sales_order_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("sales_order.sales_order_id"), nullable=True, index=True
    )
    additional_charges_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    qty: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    rate: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    net_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    remarks: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    updated_by: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )

    # Relationships
    order: Mapped[Optional["SalesOrder"]] = relationship(
        "SalesOrder", back_populates="additional_charges"
    )
    gst_details: Mapped[List["SalesOrderAdditionalGst"]] = relationship(
        "SalesOrderAdditionalGst", back_populates="additional"
    )


class SalesOrderAdditionalGst(Base):
    """GST breakdown for sales order additional charges."""
    __tablename__ = "sales_order_additional_gst"

    sales_order_additional_gst_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sales_order_additional_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("sales_order_additional.sales_order_additional_id"), nullable=True, index=True
    )
    igst_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    igst_percent: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    cgst_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    cgst_percent: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    sgst_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    sgst_percent: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    gst_total: Mapped[Optional[float]] = mapped_column(Double, nullable=True)

    # Relationships
    additional: Mapped[Optional["SalesOrderAdditional"]] = relationship(
        "SalesOrderAdditional", back_populates="gst_details"
    )


class SalesInvoiceAdditional(Base):
    """Additional charges for sales invoices (freight, printing, handling, etc.)."""
    __tablename__ = "sales_invoice_additional"

    sales_invoice_additional_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    invoice_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("sales_invoice.invoice_id"), nullable=True, index=True
    )
    additional_charges_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    qty: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    rate: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    net_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    remarks: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    updated_by: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )

    # Relationships
    invoice: Mapped[Optional["InvoiceHdr"]] = relationship(
        "InvoiceHdr", back_populates="additional_charges"
    )
    gst_details: Mapped[List["SalesInvoiceAdditionalGst"]] = relationship(
        "SalesInvoiceAdditionalGst", back_populates="additional"
    )


class SalesInvoiceAdditionalGst(Base):
    """GST breakdown for sales invoice additional charges."""
    __tablename__ = "sales_invoice_additional_gst"

    sales_invoice_additional_gst_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sales_invoice_additional_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("sales_invoice_additional.sales_invoice_additional_id"), nullable=True, index=True
    )
    igst_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    igst_percent: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    cgst_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    cgst_percent: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    sgst_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    sgst_percent: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    gst_total: Mapped[Optional[float]] = mapped_column(Double, nullable=True)

    # Relationships
    additional: Mapped[Optional["SalesInvoiceAdditional"]] = relationship(
        "SalesInvoiceAdditional", back_populates="gst_details"
    )


# =============================================================================
# SALES DELIVERY ORDER MODELS
# =============================================================================

class SalesDeliveryOrder(Base):
    """Sales delivery order header table. Represents physical dispatch against a sales order."""
    __tablename__ = "sales_delivery_order"

    sales_delivery_order_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    updated_by: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )
    delivery_order_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    delivery_order_no: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    branch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    invoice_type: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sales_order_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("sales_order.sales_order_id"), nullable=True, index=True
    )
    party_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    billing_to_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    shipping_to_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    transporter_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    vehicle_no: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    driver_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    driver_contact: Mapped[Optional[str]] = mapped_column(String(25), nullable=True)
    expected_delivery_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    footer_note: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    internal_note: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    gross_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    net_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    freight_charges: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    round_off_value: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    status_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    approval_level: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=0)
    active: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # Relationships
    sales_order: Mapped[Optional["SalesOrder"]] = relationship("SalesOrder")
    details: Mapped[List["SalesDeliveryOrderDtl"]] = relationship(
        "SalesDeliveryOrderDtl", back_populates="delivery_order"
    )


class SalesDeliveryOrderDtl(Base):
    """Sales delivery order detail/line items table."""
    __tablename__ = "sales_delivery_order_dtl"

    sales_delivery_order_dtl_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    updated_by: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )
    sales_delivery_order_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("sales_delivery_order.sales_delivery_order_id"), nullable=True, index=True
    )
    sales_order_dtl_id: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, index=True
    )
    hsn_code: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    item_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    item_make_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    quantity: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    uom_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    rate: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    discount_type: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    discounted_rate: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    discount_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    net_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    total_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    remarks: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    active: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # Relationships
    delivery_order: Mapped[Optional["SalesDeliveryOrder"]] = relationship(
        "SalesDeliveryOrder", back_populates="details"
    )
    gst_details: Mapped[List["SalesDeliveryOrderDtlGst"]] = relationship(
        "SalesDeliveryOrderDtlGst", back_populates="delivery_order_dtl"
    )


class SalesDeliveryOrderDtlGst(Base):
    """GST details for sales delivery order line items."""
    __tablename__ = "sales_delivery_order_dtl_gst"

    sales_delivery_order_dtl_gst_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sales_delivery_order_dtl_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("sales_delivery_order_dtl.sales_delivery_order_dtl_id"), nullable=True, index=True
    )
    igst_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    igst_percent: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    cgst_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    cgst_percent: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    sgst_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    sgst_percent: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    gst_total: Mapped[Optional[float]] = mapped_column(Double, nullable=True)

    # Relationships
    delivery_order_dtl: Mapped[Optional["SalesDeliveryOrderDtl"]] = relationship(
        "SalesDeliveryOrderDtl", back_populates="gst_details"
    )


# =============================================================================
# INVOICE EXTENSION MODELS (Hessian, Jute Yarn, Govt SKG Detail)
# =============================================================================

class SalesInvoiceHessian(Base):
    """Hessian-specific header fields for sales invoices (invoice_type=2/Hessian)."""
    __tablename__ = "sales_invoice_hessian"

    sales_invoice_hessian_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    invoice_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("sales_invoice.invoice_id"), nullable=True, index=True
    )
    qty_bales: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    rate_per_bale: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    billing_rate_mt: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    billing_rate_bale: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    updated_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )

    # Relationships
    invoice: Mapped[Optional["InvoiceHdr"]] = relationship(
        "InvoiceHdr", back_populates="hessian"
    )


class SalesInvoiceHessianDtl(Base):
    """Hessian-specific detail fields for invoice line items (invoice_type=2/Hessian)."""
    __tablename__ = "sales_invoice_hessian_dtl"

    sales_invoice_hessian_dtl_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    invoice_line_item_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("sales_invoice_dtl.invoice_line_item_id"), nullable=True, index=True
    )
    qty_bales: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    rate_per_bale: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    billing_rate_mt: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    billing_rate_bale: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    updated_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )

    # Relationships
    invoice_line_item: Mapped[Optional["InvoiceLineItem"]] = relationship(
        "InvoiceLineItem", back_populates="hessian_dtl"
    )


class SalesInvoiceJuteYarn(Base):
    """Jute Yarn-specific header fields for sales invoices (invoice_type=3/Jute Yarn)."""
    __tablename__ = "sales_invoice_juteyarn"

    sales_invoice_juteyarn_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    invoice_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("sales_invoice.invoice_id"), nullable=True, index=True
    )
    pcso_no: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    container_no: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    customer_ref_no: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    updated_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )

    # Relationships
    invoice: Mapped[Optional["InvoiceHdr"]] = relationship(
        "InvoiceHdr", back_populates="juteyarn"
    )


class SalesInvoiceJuteYarnDtl(Base):
    """Jute Yarn-specific detail fields for invoice line items (invoice_type=3/Jute Yarn)."""
    __tablename__ = "sales_invoice_juteyarn_dtl"

    sales_invoice_juteyarn_dtl_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    invoice_line_item_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("sales_invoice_dtl.invoice_line_item_id"), nullable=True, index=True
    )
    updated_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )

    # Relationships
    invoice_line_item: Mapped[Optional["InvoiceLineItem"]] = relationship(
        "InvoiceLineItem", back_populates="juteyarn_dtl"
    )


class SaleInvoiceGovtskgDtl(Base):
    """Govt SKG-specific detail fields for invoice line items."""
    __tablename__ = "sale_invoice_govtskg_dtl"

    sale_invoice_govtskg_dtl_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    invoice_line_item_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("sales_invoice_dtl.invoice_line_item_id"), nullable=True, index=True
    )
    pack_sheet: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    net_weight: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    total_weight: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    updated_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )

    # Relationships
    invoice_line_item: Mapped[Optional["InvoiceLineItem"]] = relationship(
        "InvoiceLineItem", back_populates="govtskg_dtl"
    )


class EInvoiceResponse(Base):
    """Audit trail for e-invoice portal submissions"""
    __tablename__ = "e_invoice_responses"

    e_invoice_response_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    invoice_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("sales_invoice.invoice_id"), nullable=False)
    co_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("co_mst.co_id"), nullable=False)
    submission_status: Mapped[str] = mapped_column(String(50), nullable=False)
    submitted_date_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    api_response_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    irn_from_response: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    submitted_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("user_mst.user_id"), nullable=True)
    created_date_time: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())

    # Relationships
    invoice: Mapped["InvoiceHdr"] = relationship(back_populates="e_invoice_responses")


# =============================================================================
# SALES OUTSTANDING VIEWS (read-only)
# =============================================================================

class VwSalesOrderOutstanding(Base):
    """
    Read-only model for vw_sales_order_outstanding view.

    Per sales_order_dtl row (for approved/closed SOs), provides:
    - so_qty: original order quantity
    - do_consumed_qty: total qty consumed by DOs (status 3/5/20)
    - invoice_consumed_qty: total invoiced qty (both DO and direct paths)
    - bal_do_qty: remaining to deliver (so_qty - do_consumed_qty)
    - bal_invoice_qty: remaining to invoice (so_qty - invoice_consumed_qty)

    Consumed statuses: 3 (Approved), 5 (Closed), 20 (Pending Approval).
    """
    __tablename__ = "vw_sales_order_outstanding"
    __table_args__ = {"extend_existing": True}

    sales_order_dtl_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sales_order_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sales_no: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    sales_order_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    branch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    co_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    party_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    invoice_type: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    item_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    item_code: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    item_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    uom_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    uom_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    rate: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    so_qty: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    do_consumed_qty: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    inv_via_do_qty: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    inv_direct_qty: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    invoice_consumed_qty: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    bal_do_qty: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    bal_invoice_qty: Mapped[Optional[float]] = mapped_column(Double, nullable=True)


class VwSalesDoOutstanding(Base):
    """
    Read-only model for vw_sales_do_outstanding view.

    Per sales_delivery_order_dtl row (for approved/closed DOs), provides:
    - do_qty: delivery order line quantity
    - invoice_consumed_qty: total invoiced qty against this DO line (status 3/5/20)
    - bal_do_qty: remaining to invoice (do_qty - invoice_consumed_qty)
    """
    __tablename__ = "vw_sales_do_outstanding"
    __table_args__ = {"extend_existing": True}

    sales_delivery_order_dtl_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sales_delivery_order_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    delivery_order_no: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    delivery_order_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    sales_order_dtl_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sales_order_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    branch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    co_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    party_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    invoice_type: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    item_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    item_code: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    item_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    uom_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    uom_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    rate: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    do_qty: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    invoice_consumed_qty: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    bal_do_qty: Mapped[Optional[float]] = mapped_column(Double, nullable=True)


class VwSalesFulfillmentSummary(Base):
    """
    Read-only model for vw_sales_fulfillment_summary view.

    Aggregate view grouped by co_id + branch_id + party_id + item_id + uom_id.
    Provides totals and balances across all approved/closed sales orders.
    """
    __tablename__ = "vw_sales_fulfillment_summary"
    __table_args__ = {"extend_existing": True}

    co_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    branch_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    party_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uom_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    total_so_qty: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    total_do_qty: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    total_invoiced_qty: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    bal_so_to_deliver: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    bal_so_to_invoice: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
