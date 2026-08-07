"""
SQLAlchemy ORM models for accounting tables (acc_*).
Phase 1: Chart of Accounts, Vouchers, GST, Bill References, and Supporting Tables.
"""

from datetime import date, datetime
from typing import Optional, List

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    DECIMAL,
    ForeignKey,
    Integer,
    String,
    Text,
    TIMESTAMP,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship, Mapped, mapped_column, DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all accounting models."""
    pass


# =============================================================================
# CHART OF ACCOUNTS - LEDGER GROUPS & LEDGERS
# =============================================================================

class AccLedgerGroup(Base):
    """Ledger group hierarchy for chart of accounts (e.g., Assets, Liabilities)."""
    __tablename__ = "acc_ledger_group"

    acc_ledger_group_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    co_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    parent_group_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("acc_ledger_group.acc_ledger_group_id"), nullable=True, index=True
    )
    group_name: Mapped[str] = mapped_column(String(100), nullable=False)
    group_code: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    nature: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    affects_gross_profit: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=0)
    is_revenue: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=0)
    normal_balance: Mapped[Optional[str]] = mapped_column(String(1), nullable=True)
    is_party_group: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=0)
    is_system_group: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=0)
    sequence_no: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    active: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_by: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )

    # Relationships
    children: Mapped[List["AccLedgerGroup"]] = relationship(
        "AccLedgerGroup", back_populates="parent",
        foreign_keys=[parent_group_id]
    )
    parent: Mapped[Optional["AccLedgerGroup"]] = relationship(
        "AccLedgerGroup", back_populates="children",
        remote_side=[acc_ledger_group_id], foreign_keys=[parent_group_id]
    )
    ledgers: Mapped[List["AccLedger"]] = relationship(
        "AccLedger", back_populates="group"
    )


class AccLedger(Base):
    """Individual ledger accounts within the chart of accounts."""
    __tablename__ = "acc_ledger"

    acc_ledger_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    co_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    acc_ledger_group_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("acc_ledger_group.acc_ledger_group_id"), nullable=False, index=True
    )
    ledger_name: Mapped[str] = mapped_column(String(150), nullable=False)
    ledger_code: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    ledger_type: Mapped[Optional[str]] = mapped_column(String(1), nullable=True)
    party_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    credit_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    credit_limit: Mapped[Optional[float]] = mapped_column(DECIMAL(15, 2), nullable=True)
    opening_balance: Mapped[Optional[float]] = mapped_column(DECIMAL(15, 2), nullable=True)
    opening_balance_type: Mapped[Optional[str]] = mapped_column(String(1), nullable=True)
    opening_fy_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("acc_financial_year.acc_financial_year_id"), nullable=True
    )
    gst_applicable: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=0)
    hsn_sac_code: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    is_system_ledger: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=0)
    is_related_party: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=0)
    active: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_by: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )

    # Relationships
    group: Mapped[Optional["AccLedgerGroup"]] = relationship(
        "AccLedgerGroup", back_populates="ledgers"
    )
    voucher_lines: Mapped[List["AccVoucherLine"]] = relationship(
        "AccVoucherLine", back_populates="ledger"
    )


# =============================================================================
# VOUCHER TYPES & FINANCIAL YEAR
# =============================================================================

class AccVoucherType(Base):
    """Voucher type definitions (Payment, Receipt, Journal, Contra, etc.)."""
    __tablename__ = "acc_voucher_type"
    __table_args__ = (
        UniqueConstraint("co_id", "type_category", name="uk_vtype_co_category"),
        UniqueConstraint("co_id", "type_name", name="uk_vtype_co_name"),
    )

    acc_voucher_type_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    co_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    type_name: Mapped[str] = mapped_column(String(50), nullable=False)
    type_code: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    type_category: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    auto_numbering: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=1)
    prefix: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    requires_bank_cash: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=0)
    is_system_type: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=0)
    active: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_by: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )


class AccFinancialYear(Base):
    """Financial year definitions with lock status."""
    __tablename__ = "acc_financial_year"

    acc_financial_year_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    co_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    fy_start: Mapped[date] = mapped_column(Date, nullable=False)
    fy_end: Mapped[date] = mapped_column(Date, nullable=False)
    fy_label: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    is_active: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=1)
    is_locked: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=0)
    locked_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    locked_date_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    updated_by: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )


# =============================================================================
# PERIOD LOCK & ACCOUNT DETERMINATION
# =============================================================================

class AccPeriodLock(Base):
    """Monthly period locks within a financial year."""
    __tablename__ = "acc_period_lock"

    acc_period_lock_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    acc_financial_year_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("acc_financial_year.acc_financial_year_id"), nullable=False, index=True
    )
    period_month: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    period_start: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    period_end: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    is_locked: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=0)
    locked_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    locked_date_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    updated_by: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )


class AccAccountDetermination(Base):
    """Automatic ledger mapping rules for document types (e.g., PO -> Purchase Ledger)."""
    __tablename__ = "acc_account_determination"

    acc_account_determination_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    co_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    doc_type: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    line_type: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    acc_ledger_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("acc_ledger.acc_ledger_id"), nullable=True, index=True
    )
    item_grp_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    is_default: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=0)
    active: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_by: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )


# =============================================================================
# VOUCHER HEADER & LINES
# =============================================================================

class AccVoucher(Base):
    """Accounting voucher header (Journal, Payment, Receipt, Contra, etc.)."""
    __tablename__ = "acc_voucher"
    __table_args__ = (
        UniqueConstraint(
            "co_id", "acc_financial_year_id", "voucher_no", name="uk_voucher_co_fy_no"
        ),
    )

    acc_voucher_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    co_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    branch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    acc_voucher_type_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("acc_voucher_type.acc_voucher_type_id"), nullable=False, index=True
    )
    acc_financial_year_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("acc_financial_year.acc_financial_year_id"), nullable=False, index=True
    )
    voucher_no: Mapped[Optional[str]] = mapped_column(String(30), nullable=True, index=True)
    voucher_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    party_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    ref_no: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    ref_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    narration: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    total_amount: Mapped[Optional[float]] = mapped_column(DECIMAL(15, 2), nullable=True)
    source_doc_type: Mapped[Optional[str]] = mapped_column(String(30), nullable=True, index=True)
    source_doc_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, index=True)
    is_auto_posted: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=0)
    is_reversed: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=0)
    reversed_by_voucher_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    reversal_of_voucher_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    status_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    approval_level: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    place_of_supply_state_code: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)
    branch_gstin: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    party_gstin: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    currency_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    exchange_rate: Mapped[Optional[float]] = mapped_column(DECIMAL(12, 6), nullable=True)
    approved_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    approved_date_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    active: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_by: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )

    # Relationships
    lines: Mapped[List["AccVoucherLine"]] = relationship(
        "AccVoucherLine", back_populates="voucher"
    )
    gst_details: Mapped[List["AccVoucherGst"]] = relationship(
        "AccVoucherGst", back_populates="voucher"
    )
    bill_refs: Mapped[List["AccBillRef"]] = relationship(
        "AccBillRef", back_populates="voucher"
    )
    voucher_type: Mapped[Optional["AccVoucherType"]] = relationship(
        "AccVoucherType"
    )
    approval_logs: Mapped[List["AccVoucherApprovalLog"]] = relationship(
        "AccVoucherApprovalLog", back_populates="voucher"
    )
    warnings: Mapped[List["AccVoucherWarning"]] = relationship(
        "AccVoucherWarning", back_populates="voucher"
    )


class AccVoucherLine(Base):
    """Individual debit/credit lines within a voucher."""
    __tablename__ = "acc_voucher_line"

    acc_voucher_line_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    acc_voucher_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("acc_voucher.acc_voucher_id"), nullable=False, index=True
    )
    acc_ledger_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("acc_ledger.acc_ledger_id"), nullable=False, index=True
    )
    dr_cr: Mapped[Optional[str]] = mapped_column(String(1), nullable=True)
    amount: Mapped[Optional[float]] = mapped_column(DECIMAL(15, 2), nullable=True)
    branch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    party_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    narration: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    source_line_type: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    cost_center_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    active: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_by: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )

    # Relationships
    voucher: Mapped[Optional["AccVoucher"]] = relationship(
        "AccVoucher", back_populates="lines"
    )
    ledger: Mapped[Optional["AccLedger"]] = relationship(
        "AccLedger", back_populates="voucher_lines"
    )


# =============================================================================
# GST DETAILS
# =============================================================================

class AccVoucherGst(Base):
    """GST tax breakup for voucher lines."""
    __tablename__ = "acc_voucher_gst"

    acc_voucher_gst_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    acc_voucher_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("acc_voucher.acc_voucher_id"), nullable=False, index=True
    )
    acc_voucher_line_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("acc_voucher_line.acc_voucher_line_id"), nullable=True, index=True
    )
    gst_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    supply_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    hsn_sac_code: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    taxable_amount: Mapped[Optional[float]] = mapped_column(DECIMAL(15, 2), nullable=True)
    cgst_rate: Mapped[Optional[float]] = mapped_column(DECIMAL(5, 2), nullable=True)
    cgst_amount: Mapped[Optional[float]] = mapped_column(DECIMAL(15, 2), nullable=True)
    sgst_rate: Mapped[Optional[float]] = mapped_column(DECIMAL(5, 2), nullable=True)
    sgst_amount: Mapped[Optional[float]] = mapped_column(DECIMAL(15, 2), nullable=True)
    igst_rate: Mapped[Optional[float]] = mapped_column(DECIMAL(5, 2), nullable=True)
    igst_amount: Mapped[Optional[float]] = mapped_column(DECIMAL(15, 2), nullable=True)
    cess_rate: Mapped[Optional[float]] = mapped_column(DECIMAL(5, 2), nullable=True)
    cess_amount: Mapped[Optional[float]] = mapped_column(DECIMAL(15, 2), nullable=True)
    total_gst_amount: Mapped[Optional[float]] = mapped_column(DECIMAL(15, 2), nullable=True)
    is_rcm: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=0)
    itc_eligibility: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    active: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_by: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )

    # Relationships
    voucher: Mapped[Optional["AccVoucher"]] = relationship(
        "AccVoucher", back_populates="gst_details"
    )


# =============================================================================
# BILL REFERENCES & SETTLEMENTS
# =============================================================================

class AccBillRef(Base):
    """Bill-by-bill references for party ledger entries (against invoice, new ref, on account)."""
    __tablename__ = "acc_bill_ref"

    acc_bill_ref_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    co_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    acc_voucher_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("acc_voucher.acc_voucher_id"), nullable=False, index=True
    )
    acc_voucher_line_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("acc_voucher_line.acc_voucher_line_id"), nullable=True, index=True
    )
    party_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    ref_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    bill_no: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    bill_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    amount: Mapped[Optional[float]] = mapped_column(DECIMAL(15, 2), nullable=True)
    pending_amount: Mapped[Optional[float]] = mapped_column(DECIMAL(15, 2), nullable=True)
    status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    active: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_by: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )

    # Relationships
    voucher: Mapped[Optional["AccVoucher"]] = relationship(
        "AccVoucher", back_populates="bill_refs"
    )
    settlements: Mapped[List["AccBillSettlement"]] = relationship(
        "AccBillSettlement", back_populates="bill_ref"
    )


class AccBillSettlement(Base):
    """Settlement records linking payment/receipt bills to invoice bills."""
    __tablename__ = "acc_bill_settlement"

    acc_bill_settlement_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    acc_bill_ref_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("acc_bill_ref.acc_bill_ref_id"), nullable=False, index=True
    )
    settled_against_bill_ref_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("acc_bill_ref.acc_bill_ref_id"), nullable=True, index=True
    )
    settled_amount: Mapped[Optional[float]] = mapped_column(DECIMAL(15, 2), nullable=True)
    settlement_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    active: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_by: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )

    # Relationships
    bill_ref: Mapped[Optional["AccBillRef"]] = relationship(
        "AccBillRef", back_populates="settlements", foreign_keys=[acc_bill_ref_id]
    )
    settled_against_bill: Mapped[Optional["AccBillRef"]] = relationship(
        "AccBillRef", foreign_keys=[settled_against_bill_ref_id]
    )


# =============================================================================
# VOUCHER NUMBERING
# =============================================================================

class AccVoucherNumbering(Base):
    """Auto-numbering sequence tracking per voucher type, branch, and financial year."""
    __tablename__ = "acc_voucher_numbering"

    acc_voucher_numbering_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    co_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    acc_voucher_type_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("acc_voucher_type.acc_voucher_type_id"), nullable=False, index=True
    )
    acc_financial_year_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("acc_financial_year.acc_financial_year_id"), nullable=False, index=True
    )
    branch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    prefix: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    last_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=0)
    active: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_by: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )


# =============================================================================
# VOUCHER APPROVAL & WARNINGS
# =============================================================================

class AccVoucherApprovalLog(Base):
    """Approval workflow audit trail for vouchers."""
    __tablename__ = "acc_voucher_approval_log"

    acc_voucher_approval_log_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    acc_voucher_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("acc_voucher.acc_voucher_id"), nullable=False, index=True
    )
    action: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    from_status_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    to_status_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    from_level: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    to_level: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    remarks: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    action_by: Mapped[int] = mapped_column(Integer, nullable=False)
    action_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )
    active: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_by: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )

    # Relationships
    voucher: Mapped[Optional["AccVoucher"]] = relationship(
        "AccVoucher", back_populates="approval_logs"
    )


class AccVoucherWarning(Base):
    """Warnings generated during voucher posting (e.g., negative balance, budget exceeded)."""
    __tablename__ = "acc_voucher_warning"

    acc_voucher_warning_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    acc_voucher_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("acc_voucher.acc_voucher_id"), nullable=False, index=True
    )
    warning_type: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    warning_message: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    severity: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    is_overridden: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=0)
    overridden_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    overridden_date_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    active: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_by: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )

    # Relationships
    voucher: Mapped[Optional["AccVoucher"]] = relationship(
        "AccVoucher", back_populates="warnings"
    )


# =============================================================================
# PER-COMPANY POSTING CONFIGURATION & QUEUE
# =============================================================================

class AccCompanySettings(Base):
    """Per-company accounting behaviour: posting modes, due-date rule, TDS switch."""
    __tablename__ = "acc_company_settings"

    acc_company_settings_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    co_id: Mapped[int] = mapped_column(Integer, nullable=False, unique=True, index=True)
    posting_mode_purchase: Mapped[str] = mapped_column(String(15), nullable=False, default="OFF")
    posting_mode_jute_purchase: Mapped[str] = mapped_column(String(15), nullable=False, default="OFF")
    posting_mode_sales: Mapped[str] = mapped_column(String(15), nullable=False, default="OFF")
    posting_mode_drcr: Mapped[str] = mapped_column(String(15), nullable=False, default="OFF")
    due_date_rule: Mapped[str] = mapped_column(String(20), nullable=False, default="PO_CREDIT_DAYS")
    default_credit_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    enable_tds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=1)
    expense_approval_required: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=0)
    active: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_by: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )


class AccPostingQueue(Base):
    """Outbox for auto-posting: one row per source document posting attempt."""
    __tablename__ = "acc_posting_queue"

    acc_posting_queue_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    co_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    source_doc_type: Mapped[str] = mapped_column(String(30), nullable=False)
    source_doc_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="PENDING", index=True)
    acc_voucher_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    attempt_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=0)
    last_error: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    active: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_by: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )


class AccAgeingSlab(Base):
    """Configurable ageing buckets per company for AP/AR ageing reports."""
    __tablename__ = "acc_ageing_slab"

    acc_ageing_slab_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    co_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    slab_name: Mapped[str] = mapped_column(String(30), nullable=False)
    from_days: Mapped[int] = mapped_column(Integer, nullable=False)
    to_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sequence_no: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    active: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_by: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )


# =============================================================================
# OPENING BILLS
# =============================================================================

class AccOpeningBill(Base):
    """Opening outstanding bills carried forward from previous system or financial year."""
    __tablename__ = "acc_opening_bill"

    acc_opening_bill_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    co_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    acc_ledger_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("acc_ledger.acc_ledger_id"), nullable=False, index=True
    )
    acc_financial_year_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("acc_financial_year.acc_financial_year_id"), nullable=False, index=True
    )
    bill_no: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    bill_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    bill_type: Mapped[Optional[str]] = mapped_column(String(1), nullable=True)
    amount: Mapped[Optional[float]] = mapped_column(DECIMAL(15, 2), nullable=True)
    pending_amount: Mapped[Optional[float]] = mapped_column(DECIMAL(15, 2), nullable=True)
    status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    active: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_by: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )
