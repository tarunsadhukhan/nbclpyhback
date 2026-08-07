"""
SQLAlchemy ORM models for inventory tables (issue_hdr, issue_li).
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
    func,
)
from sqlalchemy.orm import relationship, Mapped, mapped_column, DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all inventory models."""
    pass


class IssueHdr(Base):
    """Issue header table - stores material issue transactions."""
    __tablename__ = "issue_hdr"

    issue_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    issue_no: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    issue_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    branch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    dept_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    expense_type_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    project_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    remarks: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    status_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    active: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True, default=True)
    updated_by: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )
    created_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_date_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, server_default=func.current_timestamp()
    )

    # Relationships
    details: Mapped[List["IssueLi"]] = relationship(
        "IssueLi", back_populates="issue_hdr"
    )


class IssueLi(Base):
    """Issue line item table - stores individual items in an issue."""
    __tablename__ = "issue_li"

    issue_li_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    issue_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("issue_hdr.issue_id"), nullable=True, index=True
    )
    item_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    item_make_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    uom_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    qty: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    rate: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    remarks: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    active: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True, default=True)
    updated_by: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )
    sr_dtl_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # Link to stores receipt detail
    material_inventory_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Relationships
    issue_hdr: Mapped[Optional["IssueHdr"]] = relationship(
        "IssueHdr", back_populates="details"
    )


__all__ = [
    "Base",
    "IssueHdr",
    "IssueLi",
]
