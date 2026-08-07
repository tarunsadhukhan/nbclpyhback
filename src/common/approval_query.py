"""Shared approval-related SQL query functions.

These queries operate on the `approval_mst` table and related tables
to support the multi-level approval workflow used across all modules
(procurement, sales, jute, etc.).
"""

from sqlalchemy.sql import text


def get_approval_flow_by_menu_branch():
    """Get approval flow details for a specific menu and branch.
    Returns all approval levels configured for the menu/branch combination.
    """
    sql = """SELECT
        am.approval_mst_id,
        am.menu_id,
        am.user_id,
        am.branch_id,
        am.approval_level,
        am.max_amount_single,
        am.day_max_amount,
        am.month_max_amount,
        um.user_name,
        mm.menu_name
    FROM approval_mst am
    LEFT JOIN user_mst um ON um.user_id = am.user_id
    LEFT JOIN menu_mst mm ON mm.menu_id = am.menu_id
    WHERE am.menu_id = :menu_id
        AND am.branch_id = :branch_id
    ORDER BY am.approval_level ASC;"""
    return text(sql)


def get_user_approval_level():
    """Get approval level(s) of a specific user for a menu and branch.
    A user may have entries at multiple approval levels (e.g., level 1 and level 2).
    Returns all matching rows ordered by approval_level so callers can find the
    row matching the document's current approval level.
    """
    sql = """SELECT
        am.approval_level,
        am.max_amount_single,
        am.day_max_amount,
        am.month_max_amount
    FROM approval_mst am
    WHERE am.menu_id = :menu_id
        AND am.branch_id = :branch_id
        AND am.user_id = :user_id
    ORDER BY am.approval_level ASC;"""
    return text(sql)


def get_max_approval_level():
    """Get the maximum approval level configured for a menu and branch."""
    sql = """SELECT MAX(am.approval_level) as max_level
    FROM approval_mst am
    WHERE am.menu_id = :menu_id
        AND am.branch_id = :branch_id;"""
    return text(sql)


def get_user_consumed_amounts():
    """Get amounts already consumed by user for the day and month.
    This aggregates amounts from documents approved by the user today/this month.
    Note: This is hardcoded to proc_indent for now — module-specific versions
    should be created as needed.
    """
    sql = """SELECT
        COALESCE(SUM(CASE WHEN DATE(pi.updated_date_time) = CURDATE() THEN 1 ELSE 0 END), 0) as day_count,
        COALESCE(SUM(CASE WHEN YEAR(pi.updated_date_time) = YEAR(CURDATE())
                          AND MONTH(pi.updated_date_time) = MONTH(CURDATE()) THEN 1 ELSE 0 END), 0) as month_count
    FROM proc_indent pi
    WHERE pi.approval_level = :approval_level
        AND pi.status_id = 3
        AND EXISTS (
            SELECT 1 FROM approval_mst am
            WHERE am.menu_id = :menu_id
                AND am.branch_id = :branch_id
                AND am.user_id = :user_id
                AND am.approval_level = :approval_level
        );"""
    return text(sql)


def check_approval_mst_exists():
    """Check if approval_mst has any entries for a menu and branch."""
    sql = """SELECT COUNT(*) as count
    FROM approval_mst am
    WHERE am.menu_id = :menu_id
        AND am.branch_id = :branch_id;"""
    return text(sql)


def get_user_edit_access():
    """Check if user has edit access (access_type_id >= 4) for a menu and branch."""
    sql = """SELECT
        MAX(CASE WHEN ccm.access_type = 1 THEN 1 ELSE rmm.access_type_id END) as max_access_type_id
    FROM user_role_map urm
    LEFT JOIN role_menu_map rmm ON rmm.role_id = urm.role_id
    LEFT JOIN menu_mst mm ON mm.menu_id = rmm.menu_id AND mm.active = 1
    LEFT JOIN control_co_module ccm ON urm.co_id = ccm.co_id AND ccm.module_id = mm.module_mst_id
    WHERE urm.user_id = :user_id
        AND urm.branch_id = :branch_id
        AND rmm.menu_id = :menu_id
        AND IFNULL(ccm.access_type, 0) NOT IN (2);"""
    return text(sql)
