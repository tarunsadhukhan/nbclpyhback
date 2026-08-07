"""Generic file-attachment API — upload, download, delete, list.

Portal-persona endpoints. Mounted at /api/attachments in main.py.

Flow summary
------------
- POST   /upload                multipart PDF → S3 + file_attachment row
- GET    /{attachment_id}/download    → short-lived presigned GET URL
- DELETE /{attachment_id}             → soft-delete row, NULL back-ref
- GET    /                            → list active attachments for entity

Security
--------
- Auth: get_current_user_with_refresh (cookie-based JWT).
- Tenancy: get_tenant_db routes to the caller's subdomain DB.
- Module / file_type are validated against ALLOWED_MODULES /
  ALLOWED_FILE_TYPES before any SQL or S3 call.
- The dynamic source-table column update (jute_mr.invoice_upload /
  challan_upload) uses an allow-listed map — user input never lands in
  an interpolated SQL string.
"""

import logging
import time

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session

from src.authorization.utils import get_current_user_with_refresh
from src.config.db import extract_subdomain_from_request, get_tenant_db

from . import s3_client
from .constants import (
    ALLOWED_FILE_TYPES,
    ALLOWED_MIME,
    ALLOWED_MODULES,
    MAX_SIZE_BYTES,
    MODULE_COLUMN_MAP,
)
from .query import (
    clear_jute_mr_attachment_col,
    get_attachment_by_id,
    insert_attachment,
    list_active_by_entity,
    soft_delete_by_id,
    soft_delete_existing_active,
    update_jute_mr_attachment_col,
)
from .schemas import AttachmentResponse

logger = logging.getLogger(__name__)

router = APIRouter()


def _validate_module_file_type(module: str, file_type: str) -> None:
    """Reject anything not on the allow-list. 400 on failure."""
    if module not in ALLOWED_MODULES:
        raise HTTPException(status_code=400, detail=f"Invalid module: {module}")
    allowed = ALLOWED_FILE_TYPES.get(module, set())
    if file_type not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file_type '{file_type}' for module '{module}'",
        )


def _row_to_response(row_mapping: dict) -> dict:
    """Build the API-shape AttachmentResponse dict from a row mapping."""
    return AttachmentResponse(
        attachment_id=row_mapping["attachment_id"],
        module=row_mapping["module"],
        entity_id=row_mapping["entity_id"],
        file_type=row_mapping["file_type"],
        original_filename=row_mapping.get("original_filename"),
        mime_type=row_mapping.get("mime_type"),
        size_bytes=row_mapping.get("size_bytes"),
        uploaded_at=row_mapping.get("uploaded_at"),
    ).model_dump(mode="json")


@router.post("/upload")
def upload_attachment(
    request: Request,
    file: UploadFile = File(...),
    module: str = Form(...),
    entity_id: int = Form(...),
    file_type: str = Form(...),
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Upload a PDF to S3 and record metadata. Soft-deletes any prior active row for the same slot."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        try:
            co_id_int = int(co_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid co_id format")

        # MIME / size guards FIRST — cheap, no DB / S3 work yet.
        if file.content_type not in ALLOWED_MIME:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid file type '{file.content_type}'. Allowed: application/pdf",
            )

        file_bytes = file.file.read()
        if len(file_bytes) > MAX_SIZE_BYTES:
            raise HTTPException(status_code=400, detail="File size exceeds 10 MB limit")
        if len(file_bytes) == 0:
            raise HTTPException(status_code=400, detail="Empty file upload")

        _validate_module_file_type(module, file_type)

        tenant = extract_subdomain_from_request(request)
        if not tenant:
            raise HTTPException(status_code=400, detail="tenant subdomain not resolved")

        s3_key = (
            f"{tenant}/{module}/{co_id_int}/{int(entity_id)}/"
            f"{file_type}_{int(time.time() * 1000)}.pdf"
        )

        # Upload to S3 first. If S3 fails we never touch the DB.
        s3_client.upload_bytes(s3_key, file_bytes, "application/pdf")

        bucket = s3_client.get_bucket()
        user_id = token_data.get("user_id", 0)

        # Soft-delete prior active row(s) for the same slot.
        db.execute(
            soft_delete_existing_active(),
            {
                "module": module,
                "entity_id": int(entity_id),
                "file_type": file_type,
            },
        )

        # Insert the new row.
        result = db.execute(
            insert_attachment(),
            {
                "co_id": co_id_int,
                "module": module,
                "entity_id": int(entity_id),
                "file_type": file_type,
                "s3_bucket": bucket,
                "s3_key": s3_key,
                "original_filename": file.filename or None,
                "mime_type": file.content_type,
                "size_bytes": len(file_bytes),
                "uploaded_by": user_id,
            },
        )
        new_id = getattr(result, "lastrowid", None)
        if not new_id:
            raise HTTPException(status_code=500, detail="Failed to obtain new attachment_id")

        # If this (module, file_type) maps to a source-table column, update it
        # via the allow-listed column name. NEVER interpolate user input here.
        col_info = MODULE_COLUMN_MAP.get((module, file_type))
        if col_info:
            _table, _pk_col, col = col_info
            db.execute(
                update_jute_mr_attachment_col(col),
                {"attachment_id": new_id, "entity_id": int(entity_id)},
            )

        db.commit()

        return {
            "data": _row_to_response(
                {
                    "attachment_id": new_id,
                    "module": module,
                    "entity_id": int(entity_id),
                    "file_type": file_type,
                    "original_filename": file.filename or None,
                    "mime_type": file.content_type,
                    "size_bytes": len(file_bytes),
                    "uploaded_at": None,
                }
            )
        }

    except HTTPException:
        try:
            db.rollback()
        except Exception:  # pragma: no cover — rollback best-effort
            pass
        raise
    except Exception as e:
        try:
            db.rollback()
        except Exception:  # pragma: no cover
            pass
        logger.exception("Attachment upload failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{attachment_id}/download")
def download_attachment(
    attachment_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Return a short-lived presigned GET URL for the attachment."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        try:
            co_id_int = int(co_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid co_id format")

        row = db.execute(
            get_attachment_by_id(), {"attachment_id": int(attachment_id)}
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Attachment not found")
        mapping = row._mapping
        if int(mapping.get("active") or 0) != 1:
            raise HTTPException(status_code=404, detail="Attachment not found")
        if int(mapping.get("co_id") or 0) != co_id_int:
            raise HTTPException(status_code=404, detail="Attachment not found")

        url = s3_client.presigned_get_url(mapping["s3_key"], expires_in=300)
        return {"data": {"url": url, "expires_in": 300}}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Attachment download failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{attachment_id}")
def delete_attachment(
    attachment_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Soft-delete an attachment and clear its back-ref column (if mapped)."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        try:
            co_id_int = int(co_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid co_id format")

        row = db.execute(
            get_attachment_by_id(), {"attachment_id": int(attachment_id)}
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Attachment not found")
        mapping = row._mapping
        if int(mapping.get("co_id") or 0) != co_id_int:
            raise HTTPException(status_code=404, detail="Attachment not found")

        db.execute(
            soft_delete_by_id(),
            {"attachment_id": int(attachment_id)},
        )

        col_info = MODULE_COLUMN_MAP.get((mapping["module"], mapping["file_type"]))
        if col_info:
            _table, _pk_col, col = col_info
            db.execute(
                clear_jute_mr_attachment_col(col),
                {"entity_id": int(mapping["entity_id"])},
            )

        db.commit()
        return {"data": {"message": "Attachment deleted"}}

    except HTTPException:
        try:
            db.rollback()
        except Exception:  # pragma: no cover
            pass
        raise
    except Exception as e:
        try:
            db.rollback()
        except Exception:  # pragma: no cover
            pass
        logger.exception("Attachment delete failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("")
@router.get("/")
def list_attachments(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """List all active attachments for (module, entity_id)."""
    try:
        co_id = request.query_params.get("co_id")
        module = request.query_params.get("module")
        entity_id = request.query_params.get("entity_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        if not module:
            raise HTTPException(status_code=400, detail="module is required")
        if not entity_id:
            raise HTTPException(status_code=400, detail="entity_id is required")

        if module not in ALLOWED_MODULES:
            raise HTTPException(status_code=400, detail=f"Invalid module: {module}")
        try:
            entity_id_int = int(entity_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid entity_id format")

        rows = db.execute(
            list_active_by_entity(),
            {"module": module, "entity_id": entity_id_int},
        ).fetchall()

        data = [_row_to_response(dict(r._mapping)) for r in rows]
        return {"data": data}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Attachment list failed")
        raise HTTPException(status_code=500, detail=str(e))
