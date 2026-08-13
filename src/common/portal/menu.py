import logging
import os
from typing import Dict

import jwt
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.authorization.utils import (
    ALGORITHM,
    SECRET_KEY,
    create_access_token,
    get_current_user_with_refresh,
)
from src.common.portal.permission_cache import get_permissions, replace_permissions
from src.common.portal.query import (
    get_co_brnach_all,
    get_portal_user_menus,
    get_report_menu_tree,
    get_report_root_menu_id,
)
from src.config.db import get_tenant_db

router = APIRouter()
logger = logging.getLogger(__name__)


class PermissionCheckRequest(BaseModel):
    path: str
    action: str


class PermissionResponse(BaseModel):
    permissions: Dict[str, int]


def _cookie_settings() -> Dict[str, str | bool | None]:
    env_value = os.getenv("ENV", "development")
    return {
        "domain": ".vowerp.co.in" if env_value == "production" else None,
        "secure": env_value == "production",
        "samesite": "None" if env_value == "production" else "Lax",
    }


def _normalise_path(path: str | None) -> str:
    if not path:
        return ""

    cleaned = path.strip()
    if not cleaned:
        return ""

    cleaned = cleaned.lstrip("/")
    prefix = "dashboardportal/"
    if cleaned.lower().startswith(prefix):
        cleaned = cleaned[len(prefix):]

    cleaned = cleaned.rstrip("/")
    while "//" in cleaned:
        cleaned = cleaned.replace("//", "/")
    cleaned = cleaned.lower()

    return cleaned


def _action_threshold(action: str) -> int:
    mapping = {"view": 1, "print": 2, "create": 3, "edit": 4}
    return mapping.get(action.lower(), 4)


def get_portal_token_payload(
    access_token: str = Cookie(None, alias="access_token")
) -> dict:
    if not access_token:
        raise HTTPException(status_code=403, detail="No access token cookie provided")
    try:
        payload = jwt.decode(access_token, SECRET_KEY, algorithms=[ALGORITHM])
        payload["access_expired"] = False
        return payload
    except jwt.ExpiredSignatureError:
        try:
            payload = jwt.decode(
                access_token,
                SECRET_KEY,
                algorithms=[ALGORITHM],
                options={"verify_exp": False},
            )
            payload["access_expired"] = True
            return payload
        except jwt.InvalidTokenError as exc:
            raise HTTPException(status_code=401, detail=f"Invalid token: {str(exc)}") from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid token: {str(exc)}") from exc


@router.get("/portal_login_companies")
def portal_login_companies(tenant_session: Session = Depends(get_tenant_db)):
    """Company + branch list for the login screen, before any credentials exist.

    Deliberately unauthenticated: the login form shows these pickers above the
    username field, so there is no token yet. It returns ids and names only, and
    the tenant is fixed by the request's subdomain.

    The caller's pick is NOT authorisation. /portal_menu_items still decides
    what the signed-in user may actually see, and the frontend rejects a login
    whose chosen company/branch is not in that user's own list.
    """
    rows = tenant_session.execute(get_co_brnach_all()).mappings().all()

    companies: Dict[int, dict] = {}
    for row in rows:
        co_id = row["co_id"]
        if co_id is None:
            continue
        company = companies.setdefault(
            co_id, {"co_id": co_id, "co_name": row["co_name"], "branches": []}
        )
        if row["branch_id"] is not None:
            company["branches"].append(
                {"branch_id": row["branch_id"], "branch_name": row["branch_name"]}
            )

    return {"data": list(companies.values())}


@router.get("/portal_menu_items")
def compmenuitems(
    response: Response,
    token_data: dict = Depends(get_portal_token_payload),
    tenant_session: Session = Depends(get_tenant_db),
):
    user_id = token_data.get("user_id")
    if not user_id:
        raise HTTPException(status_code=403, detail="User ID not found in token")
    logger.debug("Authorized portal menu request for user %s", user_id)

    try:
        if token_data.get("access_expired"):
            refresh_result = tenant_session.execute(
                text(
                    "SELECT refresh_token FROM user_mst "
                    "WHERE user_id = :user_id AND active = 1"
                ),
                {"user_id": user_id},
            ).fetchone()
            if not refresh_result or not refresh_result[0]:
                raise HTTPException(status_code=401, detail="No refresh token found")

            refresh_token = refresh_result[0]
            try:
                jwt.decode(refresh_token, SECRET_KEY, algorithms=[ALGORITHM])
            except jwt.ExpiredSignatureError as exc:
                raise HTTPException(status_code=401, detail="Refresh token expired") from exc
            except jwt.InvalidTokenError as exc:
                raise HTTPException(status_code=401, detail=f"Invalid refresh token: {str(exc)}") from exc

            new_payload = {"user_id": user_id}
            if token_data.get("type"):
                new_payload["type"] = token_data.get("type")
            new_access_token = create_access_token(new_payload)
            cookie_cfg = _cookie_settings()
            response.set_cookie(
                key="access_token",
                value=new_access_token,
                httponly=True,
                secure=cookie_cfg["secure"],
                samesite=cookie_cfg["samesite"],
                path="/",
                domain=cookie_cfg["domain"],
            )

        menu_query = get_portal_user_menus(user_id=user_id)
        menu_rows = tenant_session.execute(menu_query, {"user_id": user_id}).fetchall()
        logger.debug("Found %s menu entries for user %s", len(menu_rows), user_id)
        #print(f"Found menus {menu_rows} menu entries for user {user_id}")
        companies: Dict[int, Dict[str, Dict[int, Dict[str, Dict[int, dict]]]]] = {}
        permissions_map: Dict[str, int] = {}

        for row in menu_rows:
            menu_id = row.menu_id
            if menu_id is None:
                continue

            menu_parent_id = row.menu_parent_id
            co_id = row.co_id
            branch_id = row.branch_id
            branch_name = row.branch_name
            menu_path = row.menu_path

            raw_access_type = row.access_type_id
            try:
                access_type_id = int(raw_access_type) if raw_access_type is not None else None
            except (TypeError, ValueError):
                access_type_id = None

            normalised_path = _normalise_path(menu_path)
            if normalised_path and access_type_id is not None:
                existing = permissions_map.get(normalised_path)
                if existing is None or access_type_id > existing:
                    permissions_map[normalised_path] = access_type_id

            # Menus are emitted flat at every depth; the sidebar rebuilds the
            # tree from menu_parent_id, so nesting is unlimited.
            company_entry = companies.setdefault(
                co_id,
                {
                    "co_id": co_id,
                    "co_name": row.co_name,
                    "branches": {},
                },
            )
            branch_entry = company_entry["branches"].setdefault(
                branch_id,
                {
                    "branch_id": branch_id,
                    "branch_name": branch_name,
                    "menus": {},
                },
            )
            branch_entry["menus"][menu_id] = {
                "menu_id": menu_id,
                "menu_name": row.menu_name,
                "menu_path": menu_path,
                "menu_parent_id": menu_parent_id,
                # Material Symbols ligature name, rendered by the sidebar
                "menu_icon": row.menu_icon,
                "access_type_id": access_type_id,
            }

        result = []
        for company in companies.values():
            branches = []
            for branch in company["branches"].values():
                branch_data = {
                    "branch_id": branch["branch_id"],
                    "branch_name": branch["branch_name"],
                    "menus": list(branch["menus"].values()),
                }
                branches.append(branch_data)
            result.append(
                {
                    "co_id": company["co_id"],
                    "co_name": company["co_name"],
                    "branches": branches,
                }
            )

        if permissions_map:
            cookie_cfg = _cookie_settings()
            token = replace_permissions(int(user_id), permissions_map)
            response.set_cookie(
                key="portal_permission_token",
                value=token,
                httponly=True,
                secure=cookie_cfg["secure"],
                samesite=cookie_cfg["samesite"],
                path="/",
                domain=cookie_cfg["domain"],
            )
        else:
            cookie_cfg = _cookie_settings()
            response.delete_cookie(
                key="portal_permission_token",
                path="/",
                domain=cookie_cfg["domain"],
            )
        return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error getting portal menu items for user %s", user_id)
        raise HTTPException(status_code=500, detail="Error getting portal menu items") from exc


@router.post("/portal_menu_permissions/check")
def check_portal_permission(
    payload: PermissionCheckRequest,
    request: Request,
    response: Response,
    current_user: dict = Depends(get_current_user_with_refresh),
):
    token = request.cookies.get("portal_permission_token")
    if not token:
        raise HTTPException(status_code=403, detail="No permission token")

    record = get_permissions(token)
    if not record:
        raise HTTPException(status_code=401, detail="Permission token expired")

    user_id = current_user.get("user_id")
    if user_id is None or record.user_id != int(user_id):
        raise HTTPException(status_code=403, detail="Permission token mismatch")

    path = _normalise_path(payload.path)
    access_type_id = None

    if path:
        segments = path.split("/")
        for idx in range(len(segments), 0, -1):
            candidate = "/".join(segments[:idx])
            candidate = candidate.lower()
            access_type_id = record.permissions.get(candidate)
            if access_type_id is not None:
                break
    else:
        access_type_id = record.permissions.get("")

    if access_type_id is None:
        return {"allowed": False, "access_type_id": None}

    required = _action_threshold(payload.action)
    allowed = access_type_id >= required
    return {"allowed": allowed, "access_type_id": access_type_id}


@router.get("/portal_menu_permissions", response_model=PermissionResponse)
def get_portal_permissions(
    request: Request,
    response: Response,
    current_user: dict = Depends(get_current_user_with_refresh),
):
    token = request.cookies.get("portal_permission_token")
    if not token:
        raise HTTPException(status_code=403, detail="No permission token")

    record = get_permissions(token)
    if not record:
        raise HTTPException(status_code=401, detail="Permission token expired")

    user_id = current_user.get("user_id")
    if user_id is None or record.user_id != int(user_id):
        raise HTTPException(status_code=403, detail="Permission token mismatch")

    return PermissionResponse(permissions=record.permissions)


@router.get("/report_menu_tree")
async def get_report_menu_tree_items(
    root_path: str,
    token_data: dict = Depends(get_portal_token_payload),
    tenant_session: Session = Depends(get_tenant_db),
):
    """Return the report-menu subtree (menu_mst rows flagged report = 1) that
    descends from the page identified by ``root_path``.

    Used by report-type pages to build a dynamic menu -> submenu -> sub-submenu
    selector. ``menu_mst`` is tenant-global, so the result is the same for every
    company/branch within the tenant. This is independent of the left sidebar
    menu loading.
    """
    if not token_data.get("user_id"):
        raise HTTPException(status_code=403, detail="User ID not found in token")

    normalised_root = _normalise_path(root_path)
    if not normalised_root:
        raise HTTPException(status_code=400, detail="root_path is required")

    try:
        root_row = tenant_session.execute(
            get_report_root_menu_id(), {"root_path": normalised_root}
        ).fetchone()
        root_menu_id = root_row[0] if root_row else None

        if root_menu_id is None:
            return {"root_menu_id": None, "data": []}

        rows = tenant_session.execute(
            get_report_menu_tree(), {"root_path": normalised_root}
        ).fetchall()
        data = [
            {
                "menu_id": r._mapping["menu_id"],
                "menu_name": r._mapping["menu_name"],
                "menu_path": r._mapping["menu_path"],
                "menu_parent_id": r._mapping["menu_parent_id"],
                "order_by": r._mapping["order_by"],
            }
            for r in rows
        ]
        return {"root_menu_id": root_menu_id, "data": data}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error getting report menu tree for root_path %s", root_path)
        raise HTTPException(status_code=500, detail="Error getting report menu tree") from exc
