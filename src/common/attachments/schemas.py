"""Pydantic schemas for attachment API responses."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class AttachmentResponse(BaseModel):
    """A single attachment metadata row exposed to the API."""

    attachment_id: int
    module: str
    entity_id: int
    file_type: str
    original_filename: Optional[str] = None
    mime_type: Optional[str] = None
    size_bytes: Optional[int] = None
    uploaded_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class PresignedUrlResponse(BaseModel):
    """A short-lived presigned S3 GET URL for downloading an attachment."""

    url: str
    expires_in: int
