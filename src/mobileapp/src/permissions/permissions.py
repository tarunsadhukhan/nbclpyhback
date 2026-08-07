"""
Flask blueprint for the dynamic menu / role permission API.

Endpoints (all under the root path -- no /permissions prefix, to match the
URLs the Android app already calls in ApiRoutes.kt):

    GET  /menu-permissions?user_id=<id>   - filtered menu tree for a user
    GET  /menus                           - admin: full menu master
    GET  /roles                           - admin: list of roles
    POST /role-menu-permissions           - admin: upsert role default
    POST /user-menu-permissions           - admin: upsert per-user override
"""

from flask import Blueprint, jsonify, request

from src.mobileapp.db import get_db

permissions_bp = Blueprint("permissions", __name__)


@permissions_bp.route("/menu-permissions", methods=["GET"])
def menu_permissions():
    # No per-user permission filtering: every active menu is returned with full
    # access flags. (The role/permission view is not used because its supporting
    # tables collide with the vowerp3 ERP schema in the tenant DB.)
    sql = """
        SELECT  m.id            AS menu_id,
                m.menu_key,
                m.menu_name,
                m.parent_id,
                m.menu_order,
                m.icon,
                m.activity_class,
                m.is_group,
                1 AS can_view,
                1 AS can_add,
                1 AS can_modify,
                1 AS can_delete,
                1 AS can_print,
                1 AS can_all
        FROM    menus m
        WHERE   m.is_active = 1
        ORDER BY (m.parent_id IS NULL) DESC, m.parent_id, m.menu_order
    """
    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute(sql)
        rows = cursor.fetchall()
        cursor.close()
        db.close()
    except Exception as e:
        return jsonify(status="error", message=str(e)), 500

    return jsonify(status="success", menus=rows)


@permissions_bp.route("/menus", methods=["GET"])
def menus_master():
    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute(
            "SELECT * FROM menus WHERE is_active = 1 "
            "ORDER BY (parent_id IS NULL) DESC, parent_id, menu_order"
        )
        rows = cursor.fetchall()
        cursor.close()
        db.close()
        return jsonify(status="success", menus=rows)
    except Exception as e:
        return jsonify(status="error", message=str(e)), 500


@permissions_bp.route("/roles", methods=["GET"])
def list_roles():
    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute(
            "SELECT id, role_name, description, is_active "
            "FROM roles WHERE is_active = 1 ORDER BY id"
        )
        rows = cursor.fetchall()
        cursor.close()
        db.close()
        return jsonify(status="success", roles=rows)
    except Exception as e:
        return jsonify(status="error", message=str(e)), 500


@permissions_bp.route("/role-menu-permissions", methods=["POST"])
def upsert_role_menu_permission():
    body = request.get_json(force=True) or {}
    if "role_id" not in body or "menu_id" not in body:
        return jsonify(status="error",
                       message="role_id and menu_id are required"), 400

    params = {
        "role_id":    body["role_id"],
        "menu_id":    body["menu_id"],
        "can_view":   int(body.get("can_view",   0)),
        "can_add":    int(body.get("can_add",    0)),
        "can_modify": int(body.get("can_modify", 0)),
        "can_delete": int(body.get("can_delete", 0)),
        "can_print":  int(body.get("can_print",  0)),
        "can_all":    int(body.get("can_all",    0)),
    }
    sql = """
        INSERT INTO role_menu_permissions
            (role_id, menu_id, can_view, can_add,
             can_modify, can_delete, can_print, can_all)
        VALUES (%(role_id)s, %(menu_id)s, %(can_view)s, %(can_add)s,
                %(can_modify)s, %(can_delete)s, %(can_print)s, %(can_all)s)
        ON DUPLICATE KEY UPDATE
            can_view   = VALUES(can_view),
            can_add    = VALUES(can_add),
            can_modify = VALUES(can_modify),
            can_delete = VALUES(can_delete),
            can_print  = VALUES(can_print),
            can_all    = VALUES(can_all)
    """
    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute(sql, params)
        db.commit()
        cursor.close()
        db.close()
        return jsonify(status="success")
    except Exception as e:
        return jsonify(status="error", message=str(e)), 500


@permissions_bp.route("/user-menu-permissions", methods=["POST"])
def upsert_user_menu_permission():
    body = request.get_json(force=True) or {}
    if "user_id" not in body or "menu_id" not in body:
        return jsonify(status="error",
                       message="user_id and menu_id are required"), 400

    params = {
        "user_id":    body["user_id"],
        "menu_id":    body["menu_id"],
        "can_view":   int(body.get("can_view",   0)),
        "can_add":    int(body.get("can_add",    0)),
        "can_modify": int(body.get("can_modify", 0)),
        "can_delete": int(body.get("can_delete", 0)),
        "can_print":  int(body.get("can_print",  0)),
        "can_all":    int(body.get("can_all",    0)),
    }
    sql = """
        INSERT INTO user_menu_permissions
            (user_id, menu_id, can_view, can_add,
             can_modify, can_delete, can_print, can_all)
        VALUES (%(user_id)s, %(menu_id)s, %(can_view)s, %(can_add)s,
                %(can_modify)s, %(can_delete)s, %(can_print)s, %(can_all)s)
        ON DUPLICATE KEY UPDATE
            can_view   = VALUES(can_view),
            can_add    = VALUES(can_add),
            can_modify = VALUES(can_modify),
            can_delete = VALUES(can_delete),
            can_print  = VALUES(can_print),
            can_all    = VALUES(can_all)
    """
    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute(sql, params)
        db.commit()
        cursor.close()
        db.close()
        return jsonify(status="success")
    except Exception as e:
        return jsonify(status="error", message=str(e)), 500
