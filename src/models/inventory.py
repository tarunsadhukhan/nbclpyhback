"""
SQLAlchemy ORM models for inventory tables (issue_hdr, issue_li).
Based on actual database schema from 'sls' database.
"""

from datetime import date, datetime
from typing import Optional, List

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Double,
    ForeignKey,
    Integer,
    String,
    TIMESTAMP,
    func,
)
from sqlalchemy.orm import relationship, Mapped, mapped_column, DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all inventory models."""
    pass


class IssueHdr(Base):
    """
    Issue header table - stores material issue transactions.
    Table: issue_hdr in sls database.
    """
    __tablename__ = "issue_hdr"

    issue_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    branch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    dept_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    issue_pass_no: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    issue_pass_print_no: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    active: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True, default=True)
    issue_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    item_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    approved_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    approved_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    approval_level: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=None)
    issued_to: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    req_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    project_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    customer_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    internal_note: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    updated_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )

    # Relationships
    details: Mapped[List["IssueLi"]] = relationship(
        "IssueLi", back_populates="issue_hdr"
    )


class IssueLi(Base):
    """
    Issue line item table - stores individual items in an issue.
    Table: issue_li in sls database.
    """
    __tablename__ = "issue_li"

    issue_li_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    issue_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("issue_hdr.issue_id"), nullable=False, index=True
    )
    item_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    uom_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    req_quantity: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    issue_qty: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    expense_type_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    cost_factor_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    machine_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    inward_dtl_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    remarks: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    updated_date_time: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
    updated_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Relationships
    issue_hdr: Mapped["IssueHdr"] = relationship(
        "IssueHdr", back_populates="details"
    )


class VwApprovedInwardQty(Base):
    """
    Read-only model for vw_approved_inward_qty view.
    Shows approved inward quantities with issue and balance tracking.
    Only includes inwards with sr_status = 3 (approved).
    """
    __tablename__ = "vw_approved_inward_qty"
    __table_args__ = {"extend_existing": True}

    # Primary key for the view
    inward_dtl_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    inward_id: Mapped[int] = mapped_column(Integer)
    item_id: Mapped[int] = mapped_column(Integer)
    approved_qty: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    uom_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    rate: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    accepted_rate: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    inward_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    branch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sr_status: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    issue_qty: Mapped[float] = mapped_column(Double)  # COALESCE ensures non-null
    balance_qty: Mapped[float] = mapped_column(Double)  # Calculated: approved_qty - issue_qty


class VwItemBalanceQtyByBranch(Base):
    """
    Read-only model for vw_item_balance_qty_by_branch view.
    Aggregates balance quantities by branch and item.
    """
    __tablename__ = "vw_item_balance_qty_by_branch"
    __table_args__ = {"extend_existing": True}

    # Composite primary key for the view
    branch_id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(primary_key=True)
    total_balance_qty: Mapped[float] = mapped_column()


__all__ = [
    "Base",
    "IssueHdr",
    "IssueLi",
    "VwApprovedInwardQty",
    "VwItemBalanceQtyByBranch",
]
