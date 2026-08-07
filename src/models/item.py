"""
SQLAlchemy ORM models for item-related tables (item_*).
Auto-generated from database schema: sls
"""

from datetime import datetime
from typing import Optional, List

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Double,
    ForeignKey,
    Integer,
    String,
    Text,
    BigInteger,
    func,
)
from sqlalchemy.orm import relationship, Mapped, mapped_column, DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all item models."""
    pass


# =============================================================================
# ITEM TYPE MODEL
# =============================================================================

class ItemTypeMaster(Base):
    """Item type master table."""
    __tablename__ = "item_type_master"

    item_type_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    item_type_name: Mapped[Optional[str]] = mapped_column(String(25), nullable=True)
    updated_by: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )

    # Relationships
    item_groups: Mapped[List["ItemGrpMst"]] = relationship(
        "ItemGrpMst", back_populates="item_type"
    )


# =============================================================================
# ITEM GROUP MODEL
# =============================================================================

class ItemGrpMst(Base):
    """Item group master table - hierarchical item categorization."""
    __tablename__ = "item_grp_mst"

    item_grp_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    parent_grp_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("item_grp_mst.item_grp_id"), nullable=True
    )
    active: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    co_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    updated_by: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )
    item_grp_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    item_grp_code: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    purchase_code: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    item_type_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("item_type_master.item_type_id"), nullable=True, index=True
    )

    # Relationships
    item_type: Mapped[Optional["ItemTypeMaster"]] = relationship(
        "ItemTypeMaster", back_populates="item_groups"
    )
    items: Mapped[List["ItemMst"]] = relationship(
        "ItemMst", back_populates="item_group"
    )
    item_makes: Mapped[List["ItemMake"]] = relationship(
        "ItemMake", back_populates="item_group"
    )
    # Self-referential relationship for parent group
    parent_group: Mapped[Optional["ItemGrpMst"]] = relationship(
        "ItemGrpMst",
        remote_side=[item_grp_id],
        foreign_keys=[parent_grp_id],
        back_populates="child_groups",
    )
    child_groups: Mapped[List["ItemGrpMst"]] = relationship(
        "ItemGrpMst",
        back_populates="parent_group",
        foreign_keys=[parent_grp_id],
    )


# =============================================================================
# ITEM MODEL
# =============================================================================

class ItemMst(Base):
    """Item master table - individual items/products/materials."""
    __tablename__ = "item_mst"

    item_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    active: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )
    updated_by: Mapped[int] = mapped_column(Integer, nullable=False)
    item_grp_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("item_grp_mst.item_grp_id"), nullable=True, index=True
    )
    item_code: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    tangible: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    item_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    item_photo: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    legacy_item_code: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    hsn_code: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    uom_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    tax_percentage: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    saleable: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    consumable: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    purchaseable: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    manufacturable: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    assembly: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    uom_rounding: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    rate_rounding: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Relationships
    item_group: Mapped[Optional["ItemGrpMst"]] = relationship(
        "ItemGrpMst", back_populates="items"
    )


# =============================================================================
# ITEM MAKE MODEL
# =============================================================================

class ItemMake(Base):
    """Item make/brand master table - manufacturer/brand info for items."""
    __tablename__ = "item_make"

    item_make_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    item_make_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    item_grp_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("item_grp_mst.item_grp_id"), nullable=True, index=True
    )
    updated_by: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )

    # Relationships
    item_group: Mapped[Optional["ItemGrpMst"]] = relationship(
        "ItemGrpMst", back_populates="item_makes"
    )


# =============================================================================
# CONVENIENCE EXPORTS
# =============================================================================

__all__ = [
    "Base",
    "ItemTypeMaster",
    "ItemGrpMst",
    "ItemMst",
    "ItemMake",
]
