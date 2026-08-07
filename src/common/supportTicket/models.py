"""ORM models for the support-ticket tables (live in ``vowconsole3``).

The tables are created via ``dbqueries/migrations/create_support_ticket_tables.sql``;
these models are the authoritative schema reference and are used for inserts.

Foreign keys to ``con_org_master`` / ``con_user_master`` are enforced at the
database level (see the migration) but are intentionally NOT declared here as
SQLAlchemy ``ForeignKey``/relationships, to avoid cross-Base mapper resolution
against the console models which use a separate declarative base.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class SupportTicket(Base):
    __tablename__ = "support_ticket"

    ticket_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticket_no: Mapped[str | None] = mapped_column(String(30), nullable=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="portal", server_default="portal")
    con_org_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    subdomain: Mapped[str | None] = mapped_column(String(50), nullable=True)
    co_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    branch_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reporter_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    reporter_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    reporter_email: Mapped[str | None] = mapped_column(String(120), nullable=True)
    page_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    page_title: Mapped[str | None] = mapped_column(String(150), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(400), nullable=True)
    app_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    category: Mapped[str | None] = mapped_column(String(30), nullable=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=2, server_default="2")
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status_id: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1", index=True)
    assigned_to_con_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    assigned_to_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    close_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    resolution_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_date_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    closed_date_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )
    active: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")


class SupportTicketComment(Base):
    __tablename__ = "support_ticket_comment"

    comment_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticket_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("support_ticket.ticket_id"), nullable=False, index=True
    )
    author_type: Mapped[str] = mapped_column(String(20), nullable=False)  # vow | reporter | system
    author_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    author_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    comment_text: Mapped[str] = mapped_column(Text, nullable=False)
    is_internal: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )


class SupportTicketAttachment(Base):
    __tablename__ = "support_ticket_attachment"

    attachment_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticket_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("support_ticket.ticket_id"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)  # image | document
    s3_bucket: Mapped[str] = mapped_column(String(120), nullable=False)
    s3_key: Mapped[str] = mapped_column(String(500), nullable=False)
    original_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    uploaded_by_type: Mapped[str] = mapped_column(String(20), nullable=False)  # reporter | vow
    uploaded_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    uploaded_by_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )
    active: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
