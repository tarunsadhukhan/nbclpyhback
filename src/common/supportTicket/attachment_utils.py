"""Shared helpers for support-ticket attachments (screenshots + documents).

Files are stored in S3 via the generic ``src.common.attachments.s3_client``
(reused for its boto3 wrapper); metadata lives in ``support_ticket_attachment``
in ``vowconsole3``. Used by both the reporter (report.py) and VOW (manage.py)
endpoints.
"""

import logging
import time
from typing import Optional

from fastapi import HTTPException, UploadFile
from sqlalchemy.orm import Session

from src.common.attachments import s3_client

from . import constants as C
from .models import SupportTicketAttachment

logger = logging.getLogger(__name__)


def read_and_validate(file: UploadFile):
    """Validate the upload's MIME / size and return ``(data, mime, kind, ext)``."""
    info = C.attachment_kind_ext(file.content_type)
    if not info:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{file.content_type}'. Allowed: images (PNG/JPG/GIF/WEBP) and documents (PDF/DOC/XLS/PPT/CSV/TXT).",
        )
    kind, ext = info
    data = file.file.read()
    if len(data) == 0:
        raise HTTPException(status_code=400, detail="Empty file upload")
    if len(data) > C.MAX_ATTACHMENT_BYTES:
        raise HTTPException(status_code=400, detail="File size exceeds 10 MB limit")
    return data, file.content_type, kind, ext


def store_attachment(
    session: Session,
    *,
    ticket_id: int,
    data: bytes,
    filename: Optional[str],
    mime: str,
    kind: str,
    ext: str,
    by_type: str,
    by_id: Optional[int],
    by_name: Optional[str],
) -> SupportTicketAttachment:
    """Upload bytes to S3, then insert the metadata row.

    S3 first: if it fails we raise before touching the DB (no orphan rows).
    """
    s3_key = f"support/{ticket_id}/{kind}_{int(time.time() * 1000)}.{ext}"
    s3_client.upload_bytes(s3_key, data, mime)
    bucket = s3_client.get_bucket()

    attachment = SupportTicketAttachment(
        ticket_id=ticket_id,
        kind=kind,
        s3_bucket=bucket,
        s3_key=s3_key,
        original_filename=filename,
        mime_type=mime,
        size_bytes=len(data),
        uploaded_by_type=by_type,
        uploaded_by_id=by_id,
        uploaded_by_name=by_name,
        active=1,
    )
    session.add(attachment)
    session.flush()
    return attachment


def _presign_or_none(s3_key: str) -> Optional[str]:
    """Best-effort presigned GET URL — never let S3 trouble break a detail load."""
    try:
        return s3_client.presigned_get_url(s3_key, expires_in=300)
    except Exception:  # pragma: no cover - S3 misconfig / transient
        logger.warning("Could not presign support attachment %s", s3_key)
        return None


def public_attachment(mapping: dict, with_url: bool = False) -> dict:
    """Shape an attachment row for the API (omits bucket; presigns on request)."""
    out = {
        "attachment_id": mapping["attachment_id"],
        "ticket_id": mapping["ticket_id"],
        "kind": mapping["kind"],
        "original_filename": mapping.get("original_filename"),
        "mime_type": mapping.get("mime_type"),
        "size_bytes": mapping.get("size_bytes"),
        "uploaded_by_type": mapping.get("uploaded_by_type"),
        "uploaded_by_name": mapping.get("uploaded_by_name"),
        "uploaded_at": mapping.get("uploaded_at"),
    }
    if with_url:
        out["url"] = _presign_or_none(mapping["s3_key"])
    return out


def attachment_response(attachment: SupportTicketAttachment) -> dict:
    """Shape a freshly-created ORM attachment for the upload response."""
    return public_attachment(
        {
            "attachment_id": attachment.attachment_id,
            "ticket_id": attachment.ticket_id,
            "kind": attachment.kind,
            "s3_key": attachment.s3_key,
            "original_filename": attachment.original_filename,
            "mime_type": attachment.mime_type,
            "size_bytes": attachment.size_bytes,
            "uploaded_by_type": attachment.uploaded_by_type,
            "uploaded_by_name": attachment.uploaded_by_name,
            "uploaded_at": None,
        },
        with_url=True,
    )
