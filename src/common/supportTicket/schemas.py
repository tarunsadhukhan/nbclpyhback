"""Pydantic request schemas for support-ticket endpoints."""

from typing import Optional

from pydantic import BaseModel, Field

from .constants import PRIORITY_MEDIUM


class RaiseTicketRequest(BaseModel):
    subject: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=3)
    category: Optional[str] = None
    priority: int = PRIORITY_MEDIUM
    # Context auto-captured by the widget
    page_path: Optional[str] = Field(default=None, max_length=255)
    page_title: Optional[str] = Field(default=None, max_length=150)
    user_agent: Optional[str] = Field(default=None, max_length=400)
    app_version: Optional[str] = Field(default=None, max_length=50)
    co_id: Optional[int] = None
    branch_id: Optional[int] = None


class ReporterCommentRequest(BaseModel):
    ticket_id: int
    comment_text: str = Field(min_length=1)


class AssignTicketRequest(BaseModel):
    ticket_id: int
    assignee_con_user_id: int


class TransitionTicketRequest(BaseModel):
    ticket_id: int
    action: str
    reason: Optional[str] = None
    notes: Optional[str] = None


class ManageCommentRequest(BaseModel):
    ticket_id: int
    comment_text: str = Field(min_length=1)
    is_internal: bool = False
