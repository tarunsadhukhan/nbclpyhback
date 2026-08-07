from fastapi import APIRouter, Request, Response, HTTPException, Header, Depends  # Add Header to the imports
from starlette.status import HTTP_401_UNAUTHORIZED
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine
from sqlalchemy.sql import text
from sqlalchemy.orm import Session
from pydantic import BaseModel
import os
from src.authorization.utils import (
    decode_access_token,
    verify_access_token,
    get_current_user_with_refresh,
    create_access_token,
    verify_password,
    get_password_hash,
    SECRET_KEY,
    ALGORITHM
)
from src.authorization.auth import login_user, login_user_console
from src.authorization.query import validate_subdomain_query
from src.config.db import default_engine, extract_subdomain_from_request
from datetime import datetime
import jwt

from src.authorization.models import LoginRequest
common_router = APIRouter()


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str
    confirm_password: str


@common_router.post("/login")
def login_route(request: Request, login_data: LoginRequest):
    """Login Route (calls login_user from auth.py)"""
    print("\n=== Starting Login Process ===")
    print(f"🔄 Received login request for user: {login_data.username}")
    print(f"🔍 Login type: {login_data.logintype}")
    print(f"🔒 Remember me: {login_data.rememberMe}")

    # Extract subdomain
    subdomain = request.headers.get("X-Subdomain", "default")
    print(f"🌐 Using subdomain: {subdomain}")
    
    # Print all headers for debugging
    print("\n📋 Request Headers:")
    for header, value in request.headers.items():
        print(f"   {header}: {value}")
    
    try:
        result = login_user(
            request,
            login_data.username,
            login_data.password,
            login_data.logintype,
            subdomain
        )
        print("✅ Login function completed successfully")
        return result
    except Exception as e:
        print(f"❌ Login error in router: {str(e)}")
        print(f"Error type: {type(e).__name__}")
        raise

@common_router.post("/loginconsole")
def login_console_route(request: Request, login_data: LoginRequest):
    """Login Route (calls login_user_console from auth.py)"""
    print("Login User")

    # For console login, prefer frontend-provided subdomain from browser hostname; fallback to request extraction.
    header_subdomain = (request.headers.get("X-Subdomain") or "").strip().lower()
    subdomain = header_subdomain if header_subdomain else extract_subdomain_from_request(request)
    print(f"DEBUG: Extracted Subdomain = {subdomain}")  # Debugging
    print('hhhsub=====',subdomain)
    return login_user_console(
        request,
        login_data.username,
        login_data.password,
        login_data.logintype,
        subdomain  # ✅ Pass extracted subdomain
    )




@common_router.post("/change-password")
def change_password(
    request: Request,
    response: Response,
    payload: ChangePasswordRequest,
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Self-service password change for the currently logged-in user.

    Works for both personas based on the token's `type` field:
      * type == "portal"  -> tenant DB `user_mst` (resolved from subdomain, same
        mechanism as login_user()).
      * otherwise (console/admin) -> `vowconsole3.con_user_master` via the default
        engine, same mechanism as login_user_console().
    """
    try:
        user_id = token_data.get("user_id")
        if not user_id:
            raise HTTPException(status_code=403, detail="User ID not found in token")

        current_password = (payload.current_password or "").strip()
        new_password = (payload.new_password or "").strip()
        confirm_password = (payload.confirm_password or "").strip()

        # Validate all three fields non-empty
        if not current_password or not new_password or not confirm_password:
            raise HTTPException(
                status_code=400,
                detail="current_password, new_password and confirm_password are all required",
            )

        # New password must match its confirmation
        if new_password != confirm_password:
            raise HTTPException(
                status_code=400,
                detail="New password and confirm password do not match",
            )

        # Reject no-op change
        if new_password == current_password:
            raise HTTPException(
                status_code=400,
                detail="New password must be different from current password",
            )

        token_type = token_data.get("type")

        if token_type == "portal":
            # Resolve tenant DB exactly like login_user() does.
            subdomain = extract_subdomain_from_request(request)
            if not subdomain or subdomain == "default":
                raise HTTPException(status_code=400, detail="Unable to resolve tenant for portal user")

            tenant_url = (
                f"mysql+pymysql://{os.getenv('DATABASE_USER')}:{os.getenv('DATABASE_PASSWORD')}@"
                f"{os.getenv('DATABASE_HOST')}:{os.getenv('DATABASE_PORT')}/{subdomain}"
            )
            tenant_engine = create_engine(tenant_url, pool_pre_ping=True)

            with Session(tenant_engine) as session:
                row = session.execute(
                    text(
                        "SELECT user_id, password FROM user_mst "
                        "WHERE user_id = :user_id AND active = TRUE"
                    ),
                    {"user_id": user_id},
                ).fetchone()

                if not row:
                    raise HTTPException(status_code=404, detail="User not found")

                stored_hash = row.password
                if not stored_hash or not verify_password(current_password, stored_hash):
                    raise HTTPException(status_code=400, detail="Current password is incorrect")

                session.execute(
                    text("UPDATE user_mst SET password = :password WHERE user_id = :user_id"),
                    {"password": get_password_hash(new_password), "user_id": user_id},
                )
                session.commit()
        else:
            # Console / tenant-admin user lives in vowconsole3.con_user_master.
            with Session(default_engine) as session:
                row = session.execute(
                    text(
                        "SELECT con_user_id, con_user_login_password FROM con_user_master "
                        "WHERE con_user_id = :user_id AND active = 1"
                    ),
                    {"user_id": user_id},
                ).fetchone()

                if not row:
                    raise HTTPException(status_code=404, detail="User not found")

                stored_hash = row.con_user_login_password
                if not stored_hash or not verify_password(current_password, stored_hash):
                    raise HTTPException(status_code=400, detail="Current password is incorrect")

                session.execute(
                    text(
                        "UPDATE con_user_master SET con_user_login_password = :password "
                        "WHERE con_user_id = :user_id"
                    ),
                    {"password": get_password_hash(new_password), "user_id": user_id},
                )
                session.commit()

        return {"data": {"message": "Password changed successfully"}}

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error changing password: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@common_router.get("/validate-subdomain")
def validate_subdomain(request: Request, subdomain: str = ""):
    """
    Validate if a subdomain corresponds to an active organisation in con_org_master.
    'admin' is always valid (control desk).
    Returns { valid: true/false }
    """
    subdomain = subdomain.strip().lower()
    if not subdomain:
        return {"valid": False}

    # 'admin' is the control desk — always valid
    if subdomain == "admin":
        return {"valid": True}

    try:
        with Session(default_engine) as session:
            query = validate_subdomain_query()
            result = session.execute(query, {"subdomain": subdomain}).fetchone()
            is_valid = result is not None and result[0] > 0
            return {"valid": is_valid}
    except Exception as e:
        print(f"Error validating subdomain: {str(e)}")
        return {"valid": False}


@common_router.get("/valid-origins")
def get_valid_origins(request: Request):
    """
    Returns all active organisation shortnames from con_org_master.
    Used by CORS middleware to dynamically allow origins.
    """
    try:
        with Session(default_engine) as session:
            result = session.execute(
                text("""
                    SELECT LOWER(TRIM(con_org_shortname)) as shortname
                    FROM vowconsole3.con_org_master
                    WHERE active = 1
                      AND con_org_shortname IS NOT NULL
                      AND TRIM(con_org_shortname) != ''
                """)
            ).fetchall()
            shortnames = [row[0] for row in result]
            return {"data": shortnames}
    except Exception as e:
        print(f"Error fetching valid origins: {str(e)}")
        return {"data": []}


@common_router.get("/protected")
def protected_route(request: Request, authorization: str = Header(None)):
    """Protected Route"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid token")

    token = authorization.split(" ")[1]
    username = decode_access_token(token)  # Decode the token to get the username
    return {"message": f"Hello, {username}"}

@common_router.get("/verify-session")
def verify_session(request: Request):
    """
    Verify session validity.
    Returns 200 { ok: true } if valid, 401 if not.
    Also validates that the user's org matches the current subdomain.
    """
    try:
        access_token = request.cookies.get("access_token")

        # Try to verify access token first if it exists
        if access_token:
            try:
                payload = verify_access_token(access_token)

                # --- Org/subdomain validation for console sessions ---
                token_subdomain = payload.get("subdomain")
                token_org_id = payload.get("con_org_id")
                # Only validate org if the token was issued for a console session
                # (portal tokens have "type": "portal" and no "subdomain")
                if token_subdomain is not None:
                    # Resolve current subdomain from request
                    current_subdomain = extract_subdomain_from_request(request).strip().lower()
                    # Also check X-Subdomain header (frontend sends browser hostname)
                    header_sub = (request.headers.get("X-Subdomain") or "").strip().lower()
                    resolved_current = header_sub if header_sub and header_sub != "default" else current_subdomain
                    if not resolved_current or resolved_current == "default":
                        resolved_current = "default"

                    # If the token was issued for a specific subdomain, verify it matches
                    if token_subdomain != resolved_current:
                        print(f"Session org mismatch: token={token_subdomain}, current={resolved_current}")
                        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="Session not valid for this organization")

                return {"ok": True}
            except HTTPException as he:
                if he.status_code != 401:
                    raise
                
                # Access token is expired, try refresh using stored token
                try:
                    # Get user_id from expired token to look up refresh token
                    expired_payload = jwt.decode(access_token, SECRET_KEY, algorithms=[ALGORITHM], options={"verify_exp": False})
                    user_id = expired_payload.get("user_id")

                    if not user_id:
                        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED)

                    # --- Validate org/subdomain even for expired tokens ---
                    token_subdomain = expired_payload.get("subdomain")
                    if token_subdomain is not None:
                        current_sub = (request.headers.get("X-Subdomain") or "").strip().lower()
                        if not current_sub or current_sub == "default":
                            current_sub = extract_subdomain_from_request(request).strip().lower()
                        if token_subdomain != current_sub:
                            print(f"Refresh org mismatch: token={token_subdomain}, current={current_sub}")
                            raise HTTPException(status_code=HTTP_401_UNAUTHORIZED)

                    # Get refresh token from database
                    with Session(default_engine) as session:
                        result = session.execute(
                            text("""
                                SELECT refresh_token 
                                FROM con_user_master 
                                WHERE con_user_id = :user_id
                                AND active = 1
                            """),
                            {"user_id": user_id}
                        ).fetchone()

                        # Verify stored refresh token exists and is valid
                        if not result or not result[0]:
                            raise HTTPException(status_code=HTTP_401_UNAUTHORIZED)
                            
                        stored_token = result[0]
                        
                        # Verify the stored refresh token is still valid
                        try:
                            jwt.decode(stored_token, SECRET_KEY, algorithms=[ALGORITHM])
                        except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
                            raise HTTPException(status_code=HTTP_401_UNAUTHORIZED)

                        # Preserve org context in refreshed token
                        new_token_data = {"user_id": user_id}
                        if expired_payload.get("con_org_id") is not None:
                            new_token_data["con_org_id"] = expired_payload["con_org_id"]
                        if expired_payload.get("subdomain") is not None:
                            new_token_data["subdomain"] = expired_payload["subdomain"]
                        if expired_payload.get("type") is not None:
                            new_token_data["type"] = expired_payload["type"]

                        # Create new access token
                        new_access_token = create_access_token(new_token_data)

                        # Create response with just ok:true
                        response = JSONResponse(content={"ok": True})

                        # Set only the new access token cookie
                        ENV = os.getenv("ENV", "development")
                        COOKIE_DOMAIN = ".vowerp.co.in" if ENV == "production" else None
                        SECURE = True if ENV == "production" else False
                        SAMESITE = "None" if ENV == "production" else "Lax"

                        response.set_cookie(
                            key="access_token",
                            value=new_access_token,
                            httponly=True,
                            secure=SECURE,
                            samesite=SAMESITE,
                            path="/",
                            domain=COOKIE_DOMAIN
                        )

                        return response

                except:
                    raise HTTPException(status_code=HTTP_401_UNAUTHORIZED)

        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED)

    except HTTPException:
        raise
    except:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED)