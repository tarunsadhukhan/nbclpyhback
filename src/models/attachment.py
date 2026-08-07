"""
SQLAlchemy ORM model for the generic file_attachment table.

Per-tenant table — created via dbqueries/migrations/create_file_attachment.sql.
Stores metadata for S3-backed file uploads (first consumer: Jute Bill Pass
invoice + challan PDFs). Module-agnostic via the `module` column.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, Integer, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for attachment models."""
    pass


class FileAttachment(Base):
    """Generic file-attachment metadata. One row per S3 object.

    Soft-delete via `active` column. Re-uploads soft-delete the prior row
    and insert a fresh one (audit trail retained in DB).
    """

    __tablename__ = "file_attachment"

    attachment_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    co_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    module: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    file_type: Mapped[str] = mapped_column(String(50), nullable=False)
    s3_bucket: Mapped[str] = mapped_column(String(100), nullable=False)
    s3_key: Mapped[str] = mapped_column(String(500), nullable=False)
    original_filename: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    mime_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    size_bytes: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    uploaded_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )
    active: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
