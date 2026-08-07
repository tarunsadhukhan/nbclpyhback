-- Migration: Support Ticket (Zendesk-style) system
-- Date: 2026-06-22
-- Target DB: vowconsole3 (central console DB — NOT a tenant DB)
-- Description:
--   Cross-tenant support tickets raised from the Portal / Tenant Admin dashboards
--   and managed by the VOW team via the Control Desk. Creates the ticket header,
--   the conversation/audit thread, and registers the Control Desk "Support Tickets"
--   menu so the management screen appears in the ctrldesk sidebar.

-- ===== Step 1: Ticket header =====
CREATE TABLE IF NOT EXISTS support_ticket (
    ticket_id               INT PRIMARY KEY AUTO_INCREMENT,
    ticket_no               VARCHAR(30) NULL,
    source                  VARCHAR(20) NOT NULL DEFAULT 'portal',   -- portal | admin
    con_org_id              INT NULL,
    subdomain               VARCHAR(50) NULL,
    co_id                   INT NULL,
    branch_id               INT NULL,
    reporter_user_id        INT NULL,
    reporter_name           VARCHAR(120) NULL,
    reporter_email          VARCHAR(120) NULL,
    page_path               VARCHAR(255) NULL,
    page_title              VARCHAR(150) NULL,
    user_agent              VARCHAR(400) NULL,
    app_version             VARCHAR(50) NULL,
    category                VARCHAR(30) NULL,         -- bug | feature | question | data_issue | other
    priority                INT NOT NULL DEFAULT 2,   -- 1 low | 2 medium | 3 high | 4 urgent
    subject                 VARCHAR(200) NOT NULL,
    description             TEXT NOT NULL,
    status_id               INT NOT NULL DEFAULT 1,   -- 1 raised | 2 open | 3 in progress | 4 on hold | 5 resolved | 6 closed | 7 rejected
    assigned_to_con_user_id INT NULL,
    assigned_to_name        VARCHAR(120) NULL,
    close_reason            VARCHAR(40) NULL,
    resolution_notes        TEXT NULL,
    resolved_date_time      DATETIME NULL,
    closed_date_time        DATETIME NULL,
    updated_by              INT NULL,
    created_date_time       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_date_time       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    active                  INT NOT NULL DEFAULT 1,
    INDEX idx_support_ticket_status (status_id),
    INDEX idx_support_ticket_org (con_org_id),
    INDEX idx_support_ticket_assignee (assigned_to_con_user_id),
    INDEX idx_support_ticket_reporter (reporter_user_id),
    CONSTRAINT fk_support_ticket_org
        FOREIGN KEY (con_org_id) REFERENCES con_org_master (con_org_id),
    CONSTRAINT fk_support_ticket_assignee
        FOREIGN KEY (assigned_to_con_user_id) REFERENCES con_user_master (con_user_id)
);

-- ===== Step 2: Ticket conversation / audit thread =====
CREATE TABLE IF NOT EXISTS support_ticket_comment (
    comment_id        INT PRIMARY KEY AUTO_INCREMENT,
    ticket_id         INT NOT NULL,
    author_type       VARCHAR(20) NOT NULL,           -- vow | reporter | system
    author_user_id    INT NULL,
    author_name       VARCHAR(120) NULL,
    comment_text      TEXT NOT NULL,
    is_internal       INT NOT NULL DEFAULT 0,         -- 1 = VOW-only note, hidden from reporter
    created_date_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_support_ticket_comment_ticket (ticket_id),
    CONSTRAINT fk_support_ticket_comment_ticket
        FOREIGN KEY (ticket_id) REFERENCES support_ticket (ticket_id)
);

-- ===== Step 3: Control Desk menu entry =====
INSERT INTO control_desk_menu
    (control_desk_menu_name, active, parent_id, menu_path, menu_icon_name, order_by, menu_type)
VALUES
    ('Support Tickets', 1, 0, '/dashboardctrldesk/supportTickets', 'LifeBuoy', 900, 0);

SET @support_menu_id = LAST_INSERT_ID();

-- Grant the new menu to every Control Desk role (con_org_id IS NULL) so it is
-- visible to non-superadmin ctrldesk users too. (user_id = 1 sees all menus
-- regardless, per get_menu_for_user1_query.)
INSERT INTO con_role_menu_map (con_role_id, con_menu_id)
SELECT crm.con_role_id, @support_menu_id
FROM con_role_master crm
WHERE crm.con_org_id IS NULL
  AND NOT EXISTS (
      SELECT 1 FROM con_role_menu_map m
      WHERE m.con_role_id = crm.con_role_id
        AND m.con_menu_id = @support_menu_id
  );

-- ===== Rollback (manual) =====
-- DELETE FROM con_role_menu_map WHERE con_menu_id =
--     (SELECT control_desk_menu_id FROM control_desk_menu WHERE menu_path = '/dashboardctrldesk/supportTickets');
-- DELETE FROM control_desk_menu WHERE menu_path = '/dashboardctrldesk/supportTickets';
-- DROP TABLE IF EXISTS support_ticket_comment;
-- DROP TABLE IF EXISTS support_ticket;
