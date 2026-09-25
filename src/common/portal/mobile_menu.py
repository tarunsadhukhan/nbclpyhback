"""Tenant Admin > Mobile Menu Permissions.

Per portal role (roles_mst), which mobile app menus (menus) are allowed and with
which actions. Stored in mobile_role_menu_map in the tenant DB; the mobile app's
/menu-permissions endpoint reads it (src/mobileapp/src/permissions/permissions.py).
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy.sql import text

from src.authorization.utils import verify_access_token
from src.common.utils import now_ist
from src.config.db import get_tenant_db

router = APIRouter()

FLAGS = ("can_view", "can_add", "can_modify", "can_delete", "can_print")


@router.get("/mobile_menu_permissions")
def get_mobile_menu_permissions(
    role_id: Optional[int] = Query(None),
    token_data: dict = Depends(verify_access_token),
    tenant_session: Session = Depends(get_tenant_db),
):
    try:
        roles = tenant_session.execute(text(
            "SELECT role_id, role_name FROM roles_mst WHERE active = 1 ORDER BY role_name"
        )).fetchall()
        menus = tenant_session.execute(text(f"""
            SELECT m.id AS menu_id, m.menu_name, m.parent_id, m.menu_order, m.is_group,
                   {", ".join(f"COALESCE(p.{f}, 0) AS {f}" for f in FLAGS)}
            FROM menus m
            LEFT JOIN mobile_role_menu_map p ON p.menu_id = m.id AND p.role_id = :role_id
            WHERE m.is_active = 1
            ORDER BY (m.parent_id IS NULL) DESC, m.parent_id, m.menu_order
        """), {"role_id": role_id or 0}).fetchall()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error loading mobile menu permissions: {e}")
    return {
        "roles": [dict(r._mapping) for r in roles],
        "menus": [dict(r._mapping) for r in menus],
    }


class MobileMenuPermission(BaseModel):
    menu_id: int
    can_view: bool = False
    can_add: bool = False
    can_modify: bool = False
    can_delete: bool = False
    can_print: bool = False


class MobileMenuPermissionSubmit(BaseModel):
    role_id: int
    data: List[MobileMenuPermission]


@router.post("/mobile_menu_permissions_submit")
def submit_mobile_menu_permissions(
    payload: MobileMenuPermissionSubmit,
    token_data: dict = Depends(verify_access_token),
    tenant_session: Session = Depends(get_tenant_db),
):
    user_id = token_data.get("user_id")
    if not user_id:
        raise HTTPException(status_code=403, detail="User ID not found in token")
    # Only rows with at least one action are stored; unticked menus are simply absent.
    rows = [
        {"role_id": payload.role_id, "menu_id": p.menu_id, "updated_by": user_id,
         "updated_date_time": now_ist(), **{f: int(getattr(p, f)) for f in FLAGS}}
        for p in payload.data if any(getattr(p, f) for f in FLAGS)
    ]
    try:
        tenant_session.execute(
            text("DELETE FROM mobile_role_menu_map WHERE role_id = :role_id"),
            {"role_id": payload.role_id},
        )
        if rows:
            tenant_session.execute(text(f"""
                INSERT INTO mobile_role_menu_map
                    (role_id, menu_id, {", ".join(FLAGS)}, updated_by, updated_date_time)
                VALUES (:role_id, :menu_id, {", ".join(":" + f for f in FLAGS)},
                        :updated_by, :updated_date_time)
            """), rows)
        tenant_session.commit()
    except Exception as e:
        tenant_session.rollback()
        raise HTTPException(status_code=500, detail=f"Error saving mobile menu permissions: {e}")
    return {"success": True, "saved": len(rows)}
