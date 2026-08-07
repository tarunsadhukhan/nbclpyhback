"""JWT utility helpers used across authentication flows."""

from datetime import datetime, timedelta, timezone
import os
from typing import Any, Dict, Optional

import jwt
from fastapi import Cookie, Depends, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.context import CryptContext
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

# Password hashing context shared across auth flows
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# JWT configuration
SECRET_KEY = os.getenv("SECRET_KEY", "supersecretkey")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))

security = HTTPBearer(auto_error=False)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = _now_utc() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = _now_utc() + (expires_delta or timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def decode_access_token(token: str) -> Dict[str, Any]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError as exc:  # pragma: no cover - fast error path
        raise HTTPException(status_code=401, detail="Token expired") from exc
    except jwt.InvalidTokenError as exc:  # pragma: no cover - fast error path
        raise HTTPException(status_code=401, detail="Invalid token") from exc

    if "sub" not in payload and "user_id" not in payload:
        raise HTTPException(status_code=401, detail="Invalid token payload")
    return payload


def verify_token(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> Dict[str, Any]:
    if not credentials:
        raise HTTPException(status_code=403, detail="Not authenticated")
    return decode_access_token(credentials.credentials)


def verify_access_token(access_token: Optional[str] = Cookie(None, alias="access_token")) -> Dict[str, Any]:
    if not access_token:
        raise HTTPException(status_code=403, detail="No access token cookie provided")
    return decode_access_token(access_token)


def _refresh_cookie_settings() -> Dict[str, Any]:
    env_value = os.getenv("ENV", "development")
    return {
        "secure": env_value == "production",
        "domain": ".vowerp.co.in" if env_value == "production" else None,
        "samesite": "None" if env_value == "production" else "Lax",
    }


def _fetch_refresh_token(
    user_id: int,
    token_type: Optional[str],
    request: Request,
) -> Optional[str]:
    from src.config.db import (
        Session as DBSession,
        default_engine,
        extract_subdomain_from_request,
        get_tenant_engine,
    )

    if token_type == "portal":
        subdomain = extract_subdomain_from_request(request)
        tenant_db = subdomain if subdomain else None
        if not tenant_db or tenant_db == "default":
            return None

        TenantSession = sessionmaker(autocommit=False, autoflush=False, bind=get_tenant_engine(tenant_db))

        with TenantSession() as session:
            row = session.execute(
                text(
                    "SELECT refresh_token FROM user_mst "
                    "WHERE user_id = :user_id AND active = 1"
                ),
                {"user_id": user_id},
            ).fetchone()
        return row[0] if row and row[0] else None

    with DBSession(default_engine) as session:
        row = session.execute(
            text(
                "SELECT refresh_token FROM con_user_master "
                "WHERE con_user_id = :user_id AND active = 1"
            ),
            {"user_id": user_id},
        ).fetchone()
    return row[0] if row and row[0] else None


def _decode_refresh_token(token: str) -> Dict[str, Any]:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError as exc:  # pragma: no cover - fast error path
        raise HTTPException(status_code=401, detail="Refresh token expired") from exc
    except jwt.InvalidTokenError as exc:  # pragma: no cover - fast error path
        raise HTTPException(status_code=401, detail="Invalid refresh token") from exc


def get_current_user_with_refresh(
    request: Request,
    response: Response,
    access_token: Optional[str] = Cookie(None, alias="access_token"),
) -> Dict[str, Any]:
    if not access_token:
        raise HTTPException(status_code=403, detail="No access token cookie provided")

    try:
        return jwt.decode(access_token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        payload = jwt.decode(
            access_token,
            SECRET_KEY,
            algorithms=[ALGORITHM],
            options={"verify_exp": False},
        )
        user_id = payload.get("user_id")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid token payload")

        token_type = payload.get("type")

        stored_refresh_token = _fetch_refresh_token(user_id, token_type, request)
        if not stored_refresh_token:
            raise HTTPException(status_code=401, detail="No refresh token found")

        _decode_refresh_token(stored_refresh_token)

        token_payload = {"user_id": user_id}
        if token_type:
            token_payload["type"] = token_type

        new_access_token = create_access_token(token_payload)
        cookie_settings = _refresh_cookie_settings()

        response.set_cookie(
            key="access_token",
            value=new_access_token,
            httponly=True,
            secure=cookie_settings["secure"],
            samesite=cookie_settings["samesite"],
            path="/",
            domain=cookie_settings["domain"],
        )
        return {"user_id": user_id}
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc

