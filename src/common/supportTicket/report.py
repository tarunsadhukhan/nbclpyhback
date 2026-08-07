"""Reporter-facing support-ticket endpoints.

Used by the floating widget on the Portal (`/portal/*`) and Tenant Admin
(`/admin/*`) dashboards to raise tickets, view one's own tickets, and reply.

Both dashboards write to the central ``vowconsole3`` database, but they resolve
the reporter's identity from different user tables:

* Portal  -> ``{tenant_db}.user_mst`` (via ``get_tenant_db``)
* Admin   -> ``vowconsole3.con_user_master``
"""

from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session
from sqlalchemy.sql import text

from src.authorization.utils import get_current_user_with_refresh, verify_access_token
from src.config.db import (
    default_engine,
    extract_subdomain_from_request,
    get_tenant_db,
)

from . import constants as C
from . import attachment_utils as A
from .models import SupportTicket, SupportTicketComment
from .query import (
    get_attachment_row_query,
    get_my_tickets_query,
    get_reporter_ticket_query,
    get_ticket_attachments_query,
    get_ticket_comments_query,
    soft_delete_attachment_query,
)
from .schemas import RaiseTicketRequest, ReporterCommentRequest

router = APIRouter()


def _portal_org_id(session: Session, subdomain: str):
    return session.execute(
        text("SELECT con_org_id FROM con_org_master WHERE con_org_shortname = :s"),
        {"s": subdomain},
    ).scalar()


def _reporter_attachments(session: Session, ticket_id: int) -> list:
    rows = session.execute(get_ticket_attachments_query(), {"ticket_id": ticket_id}).fetchall()
    return [A.public_attachment(dict(r._mapping), with_url=True) for r in rows]


def _insert_ticket(
    session: Session,
    *,
    source: str,
    con_org_id: Optional[int],
    subdomain: Optional[str],
    reporter_user_id: int,
    reporter_name: Optional[str],
    reporter_email: Optional[str],
    payload: RaiseTicketRequest,
) -> SupportTicket:
    ticket = SupportTicket(
        source=source,
        con_org_id=con_org_id,
        subdomain=subdomain,
        co_id=payload.co_id,
        branch_id=payload.branch_id,
        reporter_user_id=reporter_user_id,
        reporter_name=reporter_name,
        reporter_email=reporter_email,
        page_path=payload.page_path,
        page_title=payload.page_title,
        user_agent=payload.user_agent,
        app_version=payload.app_version,
        category=payload.category,
        priority=payload.priority,
        subject=payload.subject.strip(),
        description=payload.description.strip(),
        status_id=C.STATUS_RAISED,
        active=1,
    )
    session.add(ticket)
    session.flush()  # populate ticket_id
    ticket.ticket_no = f"TKT-{ticket.ticket_id:06d}"
    session.flush()
    return ticket


def _ticket_response(ticket: SupportTicket) -> dict:
    return {
        "data": {
            "ticket_id": ticket.ticket_id,
            "ticket_no": ticket.ticket_no,
            "status_id": ticket.status_id,
        }
    }


@router.get("/meta")
def support_meta(token_data: dict = Depends(verify_access_token)):
    """Reference data (statuses, priorities, categories) for the widget."""
    return {"data": C.build_meta()}


# ── Portal (dashboardportal) ────────────────────────────────────────────────────
@router.post("/portal/raise")
def portal_raise_ticket(
    request: Request,
    payload: RaiseTicketRequest,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        C.validate_raise_fields(payload.priority, payload.category)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))

    try:
        user_id = token_data.get("user_id")
        if not user_id:
            raise HTTPException(status_code=403, detail="User ID not found in token")

        subdomain = extract_subdomain_from_request(request)

        reporter_name = None
        reporter_email = None
        row = db.execute(
            text("SELECT name, email_id FROM user_mst WHERE user_id = :uid"),
            {"uid": user_id},
        ).fetchone()
        if row:
            reporter_name = row._mapping.get("name")
            reporter_email = row._mapping.get("email_id")

        with Session(default_engine) as session:
            org_id = session.execute(
                text("SELECT con_org_id FROM con_org_master WHERE con_org_shortname = :s"),
                {"s": subdomain},
            ).scalar()
            ticket = _insert_ticket(
                session,
                source="portal",
                con_org_id=org_id,
                subdomain=subdomain,
                reporter_user_id=int(user_id),
                reporter_name=reporter_name,
                reporter_email=reporter_email,
                payload=payload,
            )
            session.commit()
            return _ticket_response(ticket)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/portal/my-tickets")
def portal_my_tickets(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        user_id = token_data.get("user_id")
        if not user_id:
            raise HTTPException(status_code=403, detail="User ID not found in token")
        subdomain = extract_subdomain_from_request(request)
        with Session(default_engine) as session:
            org_id = session.execute(
                text("SELECT con_org_id FROM con_org_master WHERE con_org_shortname = :s"),
                {"s": subdomain},
            ).scalar()
            rows = session.execute(
                get_my_tickets_query(scope_org=True),
                {"source": "portal", "reporter_user_id": int(user_id), "org_id": org_id},
            ).fetchall()
            return {"data": [dict(r._mapping) for r in rows]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/portal/ticket/{ticket_id}")
def portal_ticket_detail(
    ticket_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        user_id = token_data.get("user_id")
        if not user_id:
            raise HTTPException(status_code=403, detail="User ID not found in token")
        subdomain = extract_subdomain_from_request(request)
        with Session(default_engine) as session:
            org_id = session.execute(
                text("SELECT con_org_id FROM con_org_master WHERE con_org_shortname = :s"),
                {"s": subdomain},
            ).scalar()
            ticket = session.execute(
                get_reporter_ticket_query(scope_org=True),
                {
                    "ticket_id": ticket_id,
                    "source": "portal",
                    "reporter_user_id": int(user_id),
                    "org_id": org_id,
                },
            ).fetchone()
            if not ticket:
                raise HTTPException(status_code=404, detail="Ticket not found")
            comments = session.execute(
                get_ticket_comments_query(include_internal=False),
                {"ticket_id": ticket_id},
            ).fetchall()
            return {
                "data": dict(ticket._mapping),
                "comments": [dict(c._mapping) for c in comments],
                "attachments": _reporter_attachments(session, ticket_id),
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/portal/comment")
def portal_add_comment(
    request: Request,
    payload: ReporterCommentRequest,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        user_id = token_data.get("user_id")
        if not user_id:
            raise HTTPException(status_code=403, detail="User ID not found in token")
        subdomain = extract_subdomain_from_request(request)
        with Session(default_engine) as session:
            org_id = session.execute(
                text("SELECT con_org_id FROM con_org_master WHERE con_org_shortname = :s"),
                {"s": subdomain},
            ).scalar()
            ticket = session.execute(
                get_reporter_ticket_query(scope_org=True),
                {
                    "ticket_id": payload.ticket_id,
                    "source": "portal",
                    "reporter_user_id": int(user_id),
                    "org_id": org_id,
                },
            ).fetchone()
            if not ticket:
                raise HTTPException(status_code=404, detail="Ticket not found")
            session.add(
                SupportTicketComment(
                    ticket_id=payload.ticket_id,
                    author_type="reporter",
                    author_user_id=int(user_id),
                    author_name=ticket._mapping.get("reporter_name"),
                    comment_text=payload.comment_text.strip(),
                    is_internal=0,
                )
            )
            session.commit()
            return {"data": {"ticket_id": payload.ticket_id}}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/portal/ticket/{ticket_id}/attachment")
def portal_add_attachment(
    ticket_id: int,
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Attach a screenshot / document to one of the reporter's own tickets."""
    try:
        user_id = token_data.get("user_id")
        if not user_id:
            raise HTTPException(status_code=403, detail="User ID not found in token")
        # Validate the file before any S3 / DB work.
        data, mime, kind, ext = A.read_and_validate(file)
        subdomain = extract_subdomain_from_request(request)
        with Session(default_engine) as session:
            org_id = _portal_org_id(session, subdomain)
            ticket = session.execute(
                get_reporter_ticket_query(scope_org=True),
                {
                    "ticket_id": ticket_id,
                    "source": "portal",
                    "reporter_user_id": int(user_id),
                    "org_id": org_id,
                },
            ).fetchone()
            if not ticket:
                raise HTTPException(status_code=404, detail="Ticket not found")
            attachment = A.store_attachment(
                session,
                ticket_id=ticket_id,
                data=data,
                filename=file.filename,
                mime=mime,
                kind=kind,
                ext=ext,
                by_type="reporter",
                by_id=int(user_id),
                by_name=ticket._mapping.get("reporter_name"),
            )
            session.commit()
            return {"data": A.attachment_response(attachment)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/portal/attachment/{attachment_id}")
def portal_download_attachment(
    attachment_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Short-lived presigned URL for an attachment on the reporter's ticket."""
    try:
        user_id = token_data.get("user_id")
        if not user_id:
            raise HTTPException(status_code=403, detail="User ID not found in token")
        subdomain = extract_subdomain_from_request(request)
        with Session(default_engine) as session:
            row = session.execute(
                get_attachment_row_query(), {"attachment_id": attachment_id}
            ).fetchone()
            if not row or int(row._mapping.get("active") or 0) != 1:
                raise HTTPException(status_code=404, detail="Attachment not found")
            org_id = _portal_org_id(session, subdomain)
            owns = session.execute(
                get_reporter_ticket_query(scope_org=True),
                {
                    "ticket_id": row._mapping["ticket_id"],
                    "source": "portal",
                    "reporter_user_id": int(user_id),
                    "org_id": org_id,
                },
            ).fetchone()
            if not owns:
                raise HTTPException(status_code=404, detail="Attachment not found")
            from src.common.attachments import s3_client

            url = s3_client.presigned_get_url(row._mapping["s3_key"], expires_in=300)
            return {"data": {"url": url, "expires_in": 300}}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/portal/attachment/{attachment_id}")
def portal_delete_attachment(
    attachment_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Soft-delete an attachment the reporter uploaded on their own ticket."""
    try:
        user_id = token_data.get("user_id")
        if not user_id:
            raise HTTPException(status_code=403, detail="User ID not found in token")
        subdomain = extract_subdomain_from_request(request)
        with Session(default_engine) as session:
            row = session.execute(
                get_attachment_row_query(), {"attachment_id": attachment_id}
            ).fetchone()
            if not row or int(row._mapping.get("active") or 0) != 1:
                raise HTTPException(status_code=404, detail="Attachment not found")
            org_id = _portal_org_id(session, subdomain)
            owns = session.execute(
                get_reporter_ticket_query(scope_org=True),
                {
                    "ticket_id": row._mapping["ticket_id"],
                    "source": "portal",
                    "reporter_user_id": int(user_id),
                    "org_id": org_id,
                },
            ).fetchone()
            # Reporters may only remove their own uploads.
            if not owns or row._mapping.get("uploaded_by_type") != "reporter":
                raise HTTPException(status_code=404, detail="Attachment not found")
            session.execute(soft_delete_attachment_query(), {"attachment_id": attachment_id})
            session.commit()
            return {"data": {"attachment_id": attachment_id}}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Tenant Admin (dashboardadmin) ───────────────────────────────────────────────
@router.post("/admin/raise")
def admin_raise_ticket(
    request: Request,
    payload: RaiseTicketRequest,
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        C.validate_raise_fields(payload.priority, payload.category)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))

    try:
        user_id = token_data.get("user_id")
        if not user_id:
            raise HTTPException(status_code=403, detail="User ID not found in token")

        with Session(default_engine) as session:
            row = session.execute(
                text(
                    "SELECT con_user_name, con_user_login_email_id, con_org_id "
                    "FROM con_user_master WHERE con_user_id = :uid"
                ),
                {"uid": user_id},
            ).fetchone()
            reporter_name = row._mapping.get("con_user_name") if row else None
            reporter_email = row._mapping.get("con_user_login_email_id") if row else None
            org_id = row._mapping.get("con_org_id") if row else None

            subdomain = None
            if org_id:
                subdomain = session.execute(
                    text("SELECT con_org_shortname FROM con_org_master WHERE con_org_id = :o"),
                    {"o": org_id},
                ).scalar()

            ticket = _insert_ticket(
                session,
                source="admin",
                con_org_id=org_id,
                subdomain=subdomain,
                reporter_user_id=int(user_id),
                reporter_name=reporter_name,
                reporter_email=reporter_email,
                payload=payload,
            )
            session.commit()
            return _ticket_response(ticket)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/admin/my-tickets")
def admin_my_tickets(
    request: Request,
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        user_id = token_data.get("user_id")
        if not user_id:
            raise HTTPException(status_code=403, detail="User ID not found in token")
        with Session(default_engine) as session:
            rows = session.execute(
                get_my_tickets_query(scope_org=False),
                {"source": "admin", "reporter_user_id": int(user_id)},
            ).fetchall()
            return {"data": [dict(r._mapping) for r in rows]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/admin/ticket/{ticket_id}")
def admin_ticket_detail(
    ticket_id: int,
    request: Request,
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        user_id = token_data.get("user_id")
        if not user_id:
            raise HTTPException(status_code=403, detail="User ID not found in token")
        with Session(default_engine) as session:
            ticket = session.execute(
                get_reporter_ticket_query(scope_org=False),
                {"ticket_id": ticket_id, "source": "admin", "reporter_user_id": int(user_id)},
            ).fetchone()
            if not ticket:
                raise HTTPException(status_code=404, detail="Ticket not found")
            comments = session.execute(
                get_ticket_comments_query(include_internal=False),
                {"ticket_id": ticket_id},
            ).fetchall()
            return {
                "data": dict(ticket._mapping),
                "comments": [dict(c._mapping) for c in comments],
                "attachments": _reporter_attachments(session, ticket_id),
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/admin/comment")
def admin_add_comment(
    request: Request,
    payload: ReporterCommentRequest,
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        user_id = token_data.get("user_id")
        if not user_id:
            raise HTTPException(status_code=403, detail="User ID not found in token")
        with Session(default_engine) as session:
            ticket = session.execute(
                get_reporter_ticket_query(scope_org=False),
                {
                    "ticket_id": payload.ticket_id,
                    "source": "admin",
                    "reporter_user_id": int(user_id),
                },
            ).fetchone()
            if not ticket:
                raise HTTPException(status_code=404, detail="Ticket not found")
            session.add(
                SupportTicketComment(
                    ticket_id=payload.ticket_id,
                    author_type="reporter",
                    author_user_id=int(user_id),
                    author_name=ticket._mapping.get("reporter_name"),
                    comment_text=payload.comment_text.strip(),
                    is_internal=0,
                )
            )
            session.commit()
            return {"data": {"ticket_id": payload.ticket_id}}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/admin/ticket/{ticket_id}/attachment")
def admin_add_attachment(
    ticket_id: int,
    request: Request,
    file: UploadFile = File(...),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Attach a screenshot / document to one of the admin reporter's own tickets."""
    try:
        user_id = token_data.get("user_id")
        if not user_id:
            raise HTTPException(status_code=403, detail="User ID not found in token")
        data, mime, kind, ext = A.read_and_validate(file)
        with Session(default_engine) as session:
            ticket = session.execute(
                get_reporter_ticket_query(scope_org=False),
                {"ticket_id": ticket_id, "source": "admin", "reporter_user_id": int(user_id)},
            ).fetchone()
            if not ticket:
                raise HTTPException(status_code=404, detail="Ticket not found")
            attachment = A.store_attachment(
                session,
                ticket_id=ticket_id,
                data=data,
                filename=file.filename,
                mime=mime,
                kind=kind,
                ext=ext,
                by_type="reporter",
                by_id=int(user_id),
                by_name=ticket._mapping.get("reporter_name"),
            )
            session.commit()
            return {"data": A.attachment_response(attachment)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/admin/attachment/{attachment_id}")
def admin_download_attachment(
    attachment_id: int,
    request: Request,
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Short-lived presigned URL for an attachment on the admin reporter's ticket."""
    try:
        user_id = token_data.get("user_id")
        if not user_id:
            raise HTTPException(status_code=403, detail="User ID not found in token")
        with Session(default_engine) as session:
            row = session.execute(
                get_attachment_row_query(), {"attachment_id": attachment_id}
            ).fetchone()
            if not row or int(row._mapping.get("active") or 0) != 1:
                raise HTTPException(status_code=404, detail="Attachment not found")
            owns = session.execute(
                get_reporter_ticket_query(scope_org=False),
                {
                    "ticket_id": row._mapping["ticket_id"],
                    "source": "admin",
                    "reporter_user_id": int(user_id),
                },
            ).fetchone()
            if not owns:
                raise HTTPException(status_code=404, detail="Attachment not found")
            from src.common.attachments import s3_client

            url = s3_client.presigned_get_url(row._mapping["s3_key"], expires_in=300)
            return {"data": {"url": url, "expires_in": 300}}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/admin/attachment/{attachment_id}")
def admin_delete_attachment(
    attachment_id: int,
    request: Request,
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Soft-delete an attachment the admin reporter uploaded on their own ticket."""
    try:
        user_id = token_data.get("user_id")
        if not user_id:
            raise HTTPException(status_code=403, detail="User ID not found in token")
        with Session(default_engine) as session:
            row = session.execute(
                get_attachment_row_query(), {"attachment_id": attachment_id}
            ).fetchone()
            if not row or int(row._mapping.get("active") or 0) != 1:
                raise HTTPException(status_code=404, detail="Attachment not found")
            owns = session.execute(
                get_reporter_ticket_query(scope_org=False),
                {
                    "ticket_id": row._mapping["ticket_id"],
                    "source": "admin",
                    "reporter_user_id": int(user_id),
                },
            ).fetchone()
            if not owns or row._mapping.get("uploaded_by_type") != "reporter":
                raise HTTPException(status_code=404, detail="Attachment not found")
            session.execute(soft_delete_attachment_query(), {"attachment_id": attachment_id})
            session.commit()
            return {"data": {"attachment_id": attachment_id}}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
