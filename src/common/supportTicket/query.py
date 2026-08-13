"""Raw SQL read queries for the support-ticket feature (maindata)."""

from sqlalchemy.sql import text


def get_manage_tickets_query():
    """List tickets for the Control Desk management screen (filtered + paged)."""
    sql = """
        SELECT
            t.ticket_id, t.ticket_no, t.source, t.con_org_id,
            com.con_org_shortname, com.con_org_name,
            t.co_id, t.branch_id, t.reporter_name, t.reporter_email,
            t.page_path, t.page_title, t.category, t.priority, t.subject,
            t.status_id, t.assigned_to_con_user_id, t.assigned_to_name,
            t.close_reason, t.created_date_time, t.updated_date_time
        FROM support_ticket t
        LEFT JOIN con_org_master com ON t.con_org_id = com.con_org_id
        WHERE t.active = 1
          AND (:status_id IS NULL OR t.status_id = :status_id)
          AND (:priority IS NULL OR t.priority = :priority)
          AND (:org_id IS NULL OR t.con_org_id = :org_id)
          AND (:assignee IS NULL OR t.assigned_to_con_user_id = :assignee)
          AND (:only_open = 0 OR t.status_id IN (1, 2, 3, 4))
          AND (:search IS NULL
               OR t.subject LIKE :search
               OR t.ticket_no LIKE :search
               OR t.reporter_name LIKE :search
               OR t.description LIKE :search)
        ORDER BY
            CASE WHEN t.status_id = 1 THEN 0 ELSE 1 END,
            t.priority DESC,
            t.updated_date_time DESC
        LIMIT :limit OFFSET :offset
    """
    return text(sql)


def get_manage_tickets_count_query():
    sql = """
        SELECT COUNT(*) AS total
        FROM support_ticket t
        WHERE t.active = 1
          AND (:status_id IS NULL OR t.status_id = :status_id)
          AND (:priority IS NULL OR t.priority = :priority)
          AND (:org_id IS NULL OR t.con_org_id = :org_id)
          AND (:assignee IS NULL OR t.assigned_to_con_user_id = :assignee)
          AND (:only_open = 0 OR t.status_id IN (1, 2, 3, 4))
          AND (:search IS NULL
               OR t.subject LIKE :search
               OR t.ticket_no LIKE :search
               OR t.reporter_name LIKE :search
               OR t.description LIKE :search)
    """
    return text(sql)


def get_ticket_by_id_query():
    """Full ticket header (with org names) for the management detail view."""
    sql = """
        SELECT t.*, com.con_org_shortname, com.con_org_name
        FROM support_ticket t
        LEFT JOIN con_org_master com ON t.con_org_id = com.con_org_id
        WHERE t.ticket_id = :ticket_id
    """
    return text(sql)


def get_ticket_comments_query(include_internal: bool = True):
    sql = """
        SELECT comment_id, ticket_id, author_type, author_user_id, author_name,
               comment_text, is_internal, created_date_time
        FROM support_ticket_comment
        WHERE ticket_id = :ticket_id
    """
    if not include_internal:
        sql += " AND is_internal = 0"
    sql += " ORDER BY created_date_time ASC, comment_id ASC"
    return text(sql)


def get_my_tickets_query(scope_org: bool):
    """Tickets raised by a single reporter (for the 'My tickets' tab)."""
    sql = """
        SELECT ticket_id, ticket_no, subject, category, priority, status_id,
               assigned_to_name, close_reason, created_date_time, updated_date_time
        FROM support_ticket
        WHERE active = 1
          AND source = :source
          AND reporter_user_id = :reporter_user_id
    """
    if scope_org:
        sql += " AND con_org_id = :org_id"
    sql += " ORDER BY updated_date_time DESC LIMIT 100"
    return text(sql)


def get_reporter_ticket_query(scope_org: bool):
    """A single ticket scoped to its reporter (ownership check)."""
    sql = """
        SELECT *
        FROM support_ticket
        WHERE ticket_id = :ticket_id
          AND source = :source
          AND reporter_user_id = :reporter_user_id
    """
    if scope_org:
        sql += " AND con_org_id = :org_id"
    return text(sql)


def get_assignees_query():
    """VOW team members eligible to be assigned tickets.

    Any non-org-scoped console user (con_org_id IS NULL) — both Control Desk
    super-admins (con_user_type = 0) and console-level admins (con_user_type = 1)
    — counts as VOW team. Org-scoped tenant admins (con_org_id set) are excluded.
    """
    return text(
        """
        SELECT con_user_id, con_user_name, con_user_login_email_id
        FROM con_user_master
        WHERE con_user_type IN (0, 1)
          AND con_org_id IS NULL
          AND active = 1
        ORDER BY con_user_name
        """
    )


def get_ticket_stats_query():
    return text(
        """
        SELECT status_id, COUNT(*) AS cnt
        FROM support_ticket
        WHERE active = 1
        GROUP BY status_id
        """
    )


def get_ticket_attachments_query():
    """Active attachments for a ticket (includes s3_key for presigning)."""
    return text(
        """
        SELECT attachment_id, ticket_id, kind, s3_key, original_filename,
               mime_type, size_bytes, uploaded_by_type, uploaded_by_name, uploaded_at
        FROM support_ticket_attachment
        WHERE ticket_id = :ticket_id AND active = 1
        ORDER BY uploaded_at ASC, attachment_id ASC
        """
    )


def get_attachment_row_query():
    """Single attachment row (for download / delete + ownership checks)."""
    return text(
        """
        SELECT attachment_id, ticket_id, s3_key, active,
               uploaded_by_type, uploaded_by_id
        FROM support_ticket_attachment
        WHERE attachment_id = :attachment_id
        """
    )


def soft_delete_attachment_query():
    return text(
        "UPDATE support_ticket_attachment SET active = 0 WHERE attachment_id = :attachment_id"
    )
