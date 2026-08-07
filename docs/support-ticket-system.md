# Support Ticket System (Zendesk-style)

A cross-tenant support/issue tracker. End users raise tickets from a floating
widget on every Portal and Tenant Admin page; the VOW team triages, assigns and
resolves them from a Control Desk screen.

## Where data lives

All ticket data lives in the **central `vowconsole3` database** (not in tenant
DBs) because the feature is inherently cross-tenant and managed by the VOW team.

| Table | Purpose |
|-------|---------|
| `support_ticket` | Ticket header (one row per ticket) |
| `support_ticket_comment` | Conversation + audit thread (reporter / VOW / system) |
| `support_ticket_attachment` | Per-file metadata (screenshots + documents); bytes live in S3 |

Created by `dbqueries/migrations/create_support_ticket_tables.sql` (header +
comments + ctrldesk menu) and `dbqueries/migrations/create_support_ticket_attachment.sql`
(attachments). The first migration also registers the Control Desk
**"Support Tickets"** menu (`control_desk_menu`) and maps it to every Control
Desk role.

### Attachments

Files (PNG/JPG/GIF/WEBP screenshots + PDF/DOC/XLS/PPT/CSV/TXT documents, ≤ 10 MB
each) are uploaded to S3 via the shared `src/common/attachments/s3_client`
(reused for its boto3 wrapper) under keys `support/{ticket_id}/{kind}_{ts}.{ext}`.
Metadata is stored in `support_ticket_attachment`; downloads use short-lived
(5-minute) presigned GET URLs. Detail responses embed presigned `url`s so the UI
can render image thumbnails inline. Reporters may attach/remove their own files;
the VOW team may attach/remove on any ticket. Requires the same S3 env vars as
the generic attachments module (`S3_BUCKET`, `S3_AWS_*`).

### Captured context (for reproducibility / tracking)

`con_org_id`, `subdomain`, `co_id`, `branch_id`, reporter (`reporter_user_id` +
name/email), `page_path`, `page_title`, `user_agent`, `app_version`, `category`,
`priority`, plus assignment, close reason, resolution notes and timestamps.

## Status lifecycle

```
RAISED(1) ──assign/open──▶ OPEN(2) ──start──▶ IN_PROGRESS(3)
   │                         │  │  ▲              │  │
   │                         │  │  └──resume──┐    │  └──resolve──▶ RESOLVED(5) ──close──▶ CLOSED(6)
   │                         │  └──hold──▶ ON_HOLD(4)               │                        ▲
   └──reject──▶ REJECTED(7)  └──close/reject──┘                     └──reopen──▶ OPEN(2)      │
                  ▲                                                                            │
                  └────────────────────── reopen ◀──────────────────────────────────────────┘
```

- `close` and `reject` **require a reason** (`close_reason`); `resolve`/`close`
  accept resolution notes.
- `reject` = closed without work (e.g. "workflow not followed", "invalid").
- Every assignment / status change is recorded as a `system` comment, so the
  thread doubles as an audit trail.

Status ids are a **dedicated enum** for this feature (see
`src/common/supportTicket/constants.py`) — intentionally NOT the global
21/1/20/3/4/6 approval-workflow ids.

## Backend (prefix `/api/supportTicket`)

Code: `src/common/supportTicket/` — `report.py` (reporter endpoints),
`manage.py` (VOW endpoints), `query.py`, `models.py`, `schemas.py`, `constants.py`.

| Method | Path | Persona | Notes |
|--------|------|---------|-------|
| GET | `/meta` | any | statuses / priorities / categories / reasons |
| POST | `/portal/raise` | Portal | reporter resolved from `{tenant}.user_mst` |
| GET | `/portal/my-tickets` | Portal | reporter's own tickets |
| GET | `/portal/ticket/{id}` | Portal | own ticket + public comments |
| POST | `/portal/comment` | Portal | reporter reply |
| POST | `/admin/raise` | Tenant Admin | reporter resolved from `con_user_master` |
| GET | `/admin/my-tickets` | Tenant Admin | |
| GET | `/admin/ticket/{id}` | Tenant Admin | |
| POST | `/admin/comment` | Tenant Admin | |
| GET | `/manage/list` | Control Desk | filter (status/priority/org/assignee/open) + search + paging |
| GET | `/manage/stats` | Control Desk | counts per status |
| GET | `/manage/assignees` | Control Desk | VOW team users (`con_user_type=0`, `con_org_id IS NULL`) |
| GET | `/manage/ticket/{id}` | Control Desk | header + all comments (incl. internal) |
| POST | `/manage/assign` | Control Desk | assign owner (auto-opens a Raised ticket) |
| POST | `/manage/transition` | Control Desk | open/start/hold/resume/resolve/close/reject/reopen |
| POST | `/manage/comment` | Control Desk | public or internal note |
| POST | `/portal/ticket/{id}/attachment`, `/admin/ticket/{id}/attachment`, `/manage/ticket/{id}/attachment` | per persona | multipart upload (image/document) |
| GET | `/portal/attachment/{id}`, `/admin/attachment/{id}`, `/manage/attachment/{id}` | per persona | presigned download URL |
| DELETE | `/portal/attachment/{id}`, `/admin/attachment/{id}`, `/manage/attachment/{id}` | per persona | soft-delete (reporters: own uploads only) |

Reporter endpoints authenticate with `get_current_user_with_refresh`; management
endpoints with `verify_access_token` (console token). All write to `vowconsole3`
via `Session(default_engine)`. Attachment helpers live in
`src/common/supportTicket/attachment_utils.py`.

## Frontend

- **Widget** (`src/components/support/SupportTicketWidget.tsx`): floating FAB with
  a "Report an issue" form (Zod-validated, with a file picker) and a "My tickets"
  tab. Mounted in `dashboardportal/layout.tsx` (`variant="portal"`, reads
  company/branch from `SidebarContext`) and `dashboardadmin/layout.tsx`
  (`variant="admin"`).
- **Control Desk screen** (`src/app/dashboardctrldesk/supportTickets/`): list
  (`page.tsx`) + triage drawer (`_components/TicketManageDrawer.tsx`).
- **Attachments UI** (`src/components/support/AttachmentList.tsx`): shared
  `AttachmentList` (image thumbnails + document chips) and
  `AttachmentUploadButton` (validated picker), used by both the widget and the
  drawer.
- **Service / types**: `src/utils/supportTicketService.ts`,
  `src/utils/supportTicketTypes.ts`; routes in `src/utils/api.ts`
  (`apiRoutesSupport`).

## Activation

1. Run both migrations against **`vowconsole3`** (central DB), in order:
   `create_support_ticket_tables.sql`, then `create_support_ticket_attachment.sql`
   (via the `run-migration` skill / pymysql). These create the tables and the
   ctrldesk menu.
2. Ensure S3 env vars are set (`S3_BUCKET`, `S3_AWS_ACCESS_KEY_ID`,
   `S3_AWS_SECRET_ACCESS_KEY`, `S3_AWS_REGION`) — required for attachments only.
3. Deploy backend + frontend. The widget and Control Desk screen then work
   end-to-end.

## Possible future extensions

- One-way mirror to GitHub Issues (store issue number/URL on `support_ticket`).
- Email notifications on assignment / status change.
