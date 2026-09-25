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


_FLAGS = ("can_view", "can_add", "can_modify", "can_delete", "can_print")


def filter_menus(menus, perms):
    """Apply role permissions to the menu list.

    menus: active menu rows (menu_id, parent_id, is_group, ...).
    perms: {menu_id: {flag: 0/1}} merged over the user's roles, or None when the
    tenant has not configured mobile permissions yet (-> every menu, full access).
    A menu is kept if it has can_view; a group is kept if any descendant is kept.
    """
    if perms is None:
        return [{**m, **{f: 1 for f in _FLAGS}, "can_all": 1} for m in menus]
    by_id = {m["menu_id"]: m for m in menus}
    keep = set()
    for mid, p in perms.items():
        if not p.get("can_view") or mid not in by_id:
            continue
        # Walk up so the parent groups of a visible menu are visible too.
        while mid is not None and mid not in keep and mid in by_id:
            keep.add(mid)
            mid = by_id[mid]["parent_id"]
    out = []
    for m in menus:
        if m["menu_id"] not in keep:
            continue
        p = perms.get(m["menu_id"]) or {"can_view": 1}  # groups: view only
        flags = {f: int(p.get(f, 0)) for f in _FLAGS}
        out.append({**m, **flags, "can_all": int(all(flags.values()))})
    return out


@permissions_bp.route("/menu-permissions", methods=["GET"])
def menu_permissions():
    # Permissions come from mobile_role_menu_map (set in Tenant Admin > Mobile Menu
    # Permissions) for the user's portal roles in user_role_map. Named mobile_* because
    # menu_mst / role_menu_map are the ERP portal tables in the same tenant DB.
    user_id = request.args.get("user_id", type=int)
    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute("""
            SELECT id AS menu_id, menu_key, menu_name, parent_id, menu_order,
                   icon, activity_class, is_group
            FROM   menus
            WHERE  is_active = 1
            ORDER BY (parent_id IS NULL) DESC, parent_id, menu_order
        """)
        menus = cursor.fetchall()

        perms = None
        cursor.execute(
            "SELECT COUNT(*) AS n FROM information_schema.tables "
            "WHERE table_schema = DATABASE() AND table_name = 'mobile_role_menu_map'"
        )
        configured = cursor.fetchone()["n"] > 0
        if configured:
            cursor.execute("SELECT EXISTS(SELECT 1 FROM mobile_role_menu_map) AS n")
            configured = bool(cursor.fetchone()["n"])
        # ponytail: an unconfigured tenant (no table / no rows) keeps the old
        # everything-allowed behaviour so deploying this doesn't blank the app.
        if configured:
            cursor.execute(f"""
                SELECT p.menu_id, {", ".join(f"MAX(p.{f}) AS {f}" for f in _FLAGS)}
                FROM   mobile_role_menu_map p
                JOIN   (SELECT DISTINCT role_id FROM user_role_map WHERE user_id = %s) r
                       ON r.role_id = p.role_id
                GROUP BY p.menu_id
            """, (user_id or 0,))
            perms = {r["menu_id"]: r for r in cursor.fetchall()}
        cursor.close()
        db.close()
    except Exception as e:
        return jsonify(status="error", message=str(e)), 500

    return jsonify(status="success", menus=filter_menus(menus, perms))


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
