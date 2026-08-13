"""VOW team (Control Desk) support-ticket management endpoints.

Mounted under ``/api/supportTicket`` with the ``/manage/*`` sub-path. These are
Control Desk routes: they use ``Session(default_engine)`` against ``maindata``
and authenticate with ``verify_access_token`` (console token), matching the rest
of ``src/common/ctrldskAdmin``.
"""

from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from sqlalchemy.orm import Session
from sqlalchemy.sql import text

from src.authorization.utils import verify_access_token
from src.common.attachments import s3_client
from src.common.utils import now_ist
from src.config.db import default_engine

from . import attachment_utils as A
from . import constants as C
from .models import SupportTicket, SupportTicketComment
from .query import (
    get_assignees_query,
    get_attachment_row_query,
    get_manage_tickets_count_query,
    get_manage_tickets_query,
    get_ticket_attachments_query,
    get_ticket_by_id_query,
    get_ticket_comments_query,
    get_ticket_stats_query,
    soft_delete_attachment_query,
)
from .schemas import AssignTicketRequest, ManageCommentRequest, TransitionTicketRequest

router = APIRouter()


def _actor(session: Session, token_data: dict):
    """Resolve the acting Control Desk user (id + display name)."""
    user_id = token_data.get("user_id")
    if not user_id:
        raise HTTPException(status_code=403, detail="User ID not found in token")
    row = session.execute(
        text("SELECT con_user_name FROM con_user_master WHERE con_user_id = :uid"),
        {"uid": user_id},
    ).fetchone()
    name = row._mapping.get("con_user_name") if row else None
    return int(user_id), name


def _system_comment(session: Session, ticket_id: int, message: str) -> None:
    session.add(
        SupportTicketComment(
            ticket_id=ticket_id,
            author_type="system",
            author_user_id=None,
            author_name="System",
            comment_text=message,
            is_internal=0,
        )
    )


@router.get("/manage/list")
def manage_list_tickets(
    request: Request,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    status_id: Optional[int] = Query(None),
    priority: Optional[int] = Query(None),
    org_id: Optional[int] = Query(None),
    assignee: Optional[int] = Query(None),
    only_open: int = Query(0),
    search: Optional[str] = Query(None),
    token_data: dict = Depends(verify_access_token),
):
    try:
        offset = (page - 1) * limit
        filters = {
            "status_id": status_id,
            "priority": priority,
            "org_id": org_id,
            "assignee": assignee,
            "only_open": 1 if only_open else 0,
            "search": f"%{search}%" if search else None,
        }
        with Session(default_engine) as session:
            total = session.execute(get_manage_tickets_count_query(), filters).scalar()
            rows = session.execute(
                get_manage_tickets_query(),
                {**filters, "limit": limit, "offset": offset},
            ).fetchall()
            return {"data": [dict(r._mapping) for r in rows], "total": total or 0}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/manage/stats")
def manage_stats(token_data: dict = Depends(verify_access_token)):
    try:
        with Session(default_engine) as session:
            rows = session.execute(get_ticket_stats_query()).fetchall()
            counts = {int(r._mapping["status_id"]): int(r._mapping["cnt"]) for r in rows}
            data = [
                {"status_id": sid, "label": label, "count": counts.get(sid, 0)}
                for sid, label in C.STATUS_LABELS.items()
            ]
            return {"data": data, "total": sum(counts.values())}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/manage/assignees")
def manage_assignees(token_data: dict = Depends(verify_access_token)):
    try:
        with Session(default_engine) as session:
            rows = session.execute(get_assignees_query()).fetchall()
            return {"data": [dict(r._mapping) for r in rows]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/manage/ticket/{ticket_id}")
def manage_ticket_detail(
    ticket_id: int,
    token_data: dict = Depends(verify_access_token),
):
    try:
        with Session(default_engine) as session:
            ticket = session.execute(
                get_ticket_by_id_query(), {"ticket_id": ticket_id}
            ).fetchone()
            if not ticket:
                raise HTTPException(status_code=404, detail="Ticket not found")
            comments = session.execute(
                get_ticket_comments_query(include_internal=True),
                {"ticket_id": ticket_id},
            ).fetchall()
            attachments = session.execute(
                get_ticket_attachments_query(), {"ticket_id": ticket_id}
            ).fetchall()
            return {
                "data": dict(ticket._mapping),
                "comments": [dict(c._mapping) for c in comments],
                "attachments": [
                    A.public_attachment(dict(a._mapping), with_url=True) for a in attachments
                ],
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/manage/assign")
def manage_assign_ticket(
    request: Request,
    payload: AssignTicketRequest,
    token_data: dict = Depends(verify_access_token),
):
    try:
        with Session(default_engine) as session:
            actor_id, actor_name = _actor(session, token_data)
            ticket = session.get(SupportTicket, payload.ticket_id)
            if not ticket or ticket.active != 1:
                raise HTTPException(status_code=404, detail="Ticket not found")

            assignee = session.execute(
                text(
                    "SELECT con_user_name FROM con_user_master "
                    "WHERE con_user_id = :id AND con_user_type IN (0, 1) "
                    "AND con_org_id IS NULL AND active = 1"
                ),
                {"id": payload.assignee_con_user_id},
            ).fetchone()
            if not assignee:
                raise HTTPException(status_code=400, detail="Invalid assignee — not a VOW team member")

            assignee_name = assignee._mapping.get("con_user_name")
            ticket.assigned_to_con_user_id = payload.assignee_con_user_id
            ticket.assigned_to_name = assignee_name
            ticket.updated_by = actor_id
            # Triaging a brand-new ticket implicitly opens it.
            if ticket.status_id == C.STATUS_RAISED:
                ticket.status_id = C.STATUS_OPEN

            _system_comment(
                session,
                ticket.ticket_id,
                f"{actor_name or 'A VOW member'} assigned this ticket to {assignee_name}.",
            )
            session.commit()
            return {
                "data": {
                    "ticket_id": ticket.ticket_id,
                    "status_id": ticket.status_id,
                    "assigned_to_con_user_id": ticket.assigned_to_con_user_id,
                    "assigned_to_name": ticket.assigned_to_name,
                }
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/manage/transition")
def manage_transition_ticket(
    request: Request,
    payload: TransitionTicketRequest,
    token_data: dict = Depends(verify_access_token),
):
    try:
        action = (payload.action or "").lower().strip()
        with Session(default_engine) as session:
            actor_id, actor_name = _actor(session, token_data)
            ticket = session.get(SupportTicket, payload.ticket_id)
            if not ticket or ticket.active != 1:
                raise HTTPException(status_code=404, detail="Ticket not found")

            new_status, error = C.resolve_transition(ticket.status_id, action)
            if error:
                raise HTTPException(status_code=400, detail=error)

            if C.transition_requires_reason(action) and not (payload.reason and payload.reason.strip()):
                raise HTTPException(status_code=400, detail="A reason is required for this action")

            ticket.status_id = new_status
            ticket.updated_by = actor_id

            if action == "close":
                ticket.close_reason = payload.reason
                ticket.closed_date_time = now_ist()
                if payload.notes:
                    ticket.resolution_notes = payload.notes
            elif action == "reject":
                ticket.close_reason = (payload.reason or "invalid")
                ticket.closed_date_time = now_ist()
            elif action == "resolve":
                ticket.resolved_date_time = now_ist()
                if payload.notes:
                    ticket.resolution_notes = payload.notes
            elif action == "reopen":
                ticket.close_reason = None
                ticket.closed_date_time = None
                ticket.resolved_date_time = None

            message = f"{actor_name or 'A VOW member'} changed status to {C.STATUS_LABELS.get(new_status)}"
            if payload.reason and payload.reason.strip():
                message += f" — reason: {payload.reason.strip()}"
            _system_comment(session, ticket.ticket_id, message + ".")

            if payload.notes and payload.notes.strip():
                session.add(
                    SupportTicketComment(
                        ticket_id=ticket.ticket_id,
                        author_type="vow",
                        author_user_id=actor_id,
                        author_name=actor_name,
                        comment_text=payload.notes.strip(),
                        is_internal=0,
                    )
                )

            session.commit()
            return {
                "data": {
                    "ticket_id": ticket.ticket_id,
                    "status_id": ticket.status_id,
                    "close_reason": ticket.close_reason,
                }
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/manage/comment")
def manage_add_comment(
    request: Request,
    payload: ManageCommentRequest,
    token_data: dict = Depends(verify_access_token),
):
    try:
        with Session(default_engine) as session:
            actor_id, actor_name = _actor(session, token_data)
            ticket = session.get(SupportTicket, payload.ticket_id)
            if not ticket:
                raise HTTPException(status_code=404, detail="Ticket not found")
            session.add(
                SupportTicketComment(
                    ticket_id=payload.ticket_id,
                    author_type="vow",
                    author_user_id=actor_id,
                    author_name=actor_name,
                    comment_text=payload.comment_text.strip(),
                    is_internal=1 if payload.is_internal else 0,
                )
            )
            ticket.updated_by = actor_id
            session.commit()
            return {"data": {"ticket_id": payload.ticket_id}}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/manage/ticket/{ticket_id}/attachment")
def manage_add_attachment(
    ticket_id: int,
    request: Request,
    file: UploadFile = File(...),
    token_data: dict = Depends(verify_access_token),
):
    """Attach a screenshot / document to any ticket (VOW side)."""
    try:
        data, mime, kind, ext = A.read_and_validate(file)
        with Session(default_engine) as session:
            actor_id, actor_name = _actor(session, token_data)
            ticket = session.get(SupportTicket, ticket_id)
            if not ticket or ticket.active != 1:
                raise HTTPException(status_code=404, detail="Ticket not found")
            attachment = A.store_attachment(
                session,
                ticket_id=ticket_id,
                data=data,
                filename=file.filename,
                mime=mime,
                kind=kind,
                ext=ext,
                by_type="vow",
                by_id=actor_id,
                by_name=actor_name,
            )
            ticket.updated_by = actor_id
            session.commit()
            return {"data": A.attachment_response(attachment)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/manage/attachment/{attachment_id}")
def manage_download_attachment(
    attachment_id: int,
    token_data: dict = Depends(verify_access_token),
):
    """Short-lived presigned URL for any ticket attachment (VOW side)."""
    try:
        with Session(default_engine) as session:
            row = session.execute(
                get_attachment_row_query(), {"attachment_id": attachment_id}
            ).fetchone()
            if not row or int(row._mapping.get("active") or 0) != 1:
                raise HTTPException(status_code=404, detail="Attachment not found")
            url = s3_client.presigned_get_url(row._mapping["s3_key"], expires_in=300)
            return {"data": {"url": url, "expires_in": 300}}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/manage/attachment/{attachment_id}")
def manage_delete_attachment(
    attachment_id: int,
    token_data: dict = Depends(verify_access_token),
):
    """Soft-delete any ticket attachment (VOW side)."""
    try:
        with Session(default_engine) as session:
            _actor(session, token_data)
            row = session.execute(
                get_attachment_row_query(), {"attachment_id": attachment_id}
            ).fetchone()
            if not row or int(row._mapping.get("active") or 0) != 1:
                raise HTTPException(status_code=404, detail="Attachment not found")
            session.execute(soft_delete_attachment_query(), {"attachment_id": attachment_id})
            session.commit()
            return {"data": {"attachment_id": attachment_id}}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
