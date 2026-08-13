from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from sqlalchemy.sql import text
from sqlalchemy.orm import Session
from src.config.db import default_engine
import os


def get_active_subdomains_from_db():
    """Fetch all active organisation shortnames from the database."""
    try:
        with Session(default_engine) as session:
            result = session.execute(
                text("""
                    SELECT LOWER(TRIM(con_org_shortname)) as shortname
                    FROM maindata.con_org_master
                    WHERE active = 1
                      AND con_org_shortname IS NOT NULL
                      AND TRIM(con_org_shortname) != ''
                """)
            ).fetchall()
            return [row[0] for row in result]
    except Exception as e:
        print(f"Error fetching subdomains for CORS: {str(e)}")
        return []


def build_allowed_origin(subdomain: str) -> list[str]:
    """Build the allowed origin URLs for a given subdomain."""
    origins = []
    # Development origins
    origins.append(f"http://{subdomain}.localhost:3001")
    # Production origins
    origins.append(f"https://{subdomain}.vowerp.co.in")
    return origins


def is_origin_allowed(origin: str) -> bool:
    """
    Check if the given Origin header is allowed by querying the DB
    for active organisations.
    """
    if not origin:
        return False

    # Always allow plain localhost/127.0.0.1 (for dev tools, Postman, etc.)
    always_allowed = [
        "http://localhost:3001",
        "http://127.0.0.1:3001",
    ]
    if origin in always_allowed:
        return True

    # Extract subdomain from origin
    # e.g. "http://sls.localhost:3000" -> "sls"
    # e.g. "https://dev3.vowerp.co.in" -> "dev3"
    try:
        from urllib.parse import urlparse
        parsed = urlparse(origin)
        hostname = parsed.hostname or ""

        if ".localhost" in hostname:
            subdomain = hostname.split(".localhost")[0]
        elif ".vowerp.co.in" in hostname:
            subdomain = hostname.split(".vowerp.co.in")[0]
        else:
            return False

        if not subdomain:
            return False

        # 'admin' is always valid (control desk)
        if subdomain == "admin":
            return True

        # Query the DB to check if this subdomain is an active org
        try:
            with Session(default_engine) as session:
                result = session.execute(
                    text("""
                        SELECT COUNT(*) as cnt
                        FROM maindata.con_org_master
                        WHERE LOWER(TRIM(con_org_shortname)) = LOWER(TRIM(:subdomain))
                          AND active = 1
                        LIMIT 1
                    """),
                    {"subdomain": subdomain}
                ).fetchone()
                return result is not None and result[0] > 0
        except Exception as e:
            print(f"Error checking CORS origin in DB: {str(e)}")
            return False

    except Exception as e:
        print(f"Error parsing origin for CORS: {str(e)}")
        return False


class DynamicCORSMiddleware(BaseHTTPMiddleware):
    """
    Custom CORS middleware that validates origins dynamically
    against the con_org_master table in maindata.
    """

    async def dispatch(self, request: Request, call_next):
        origin = request.headers.get("origin", "")

        # Handle preflight OPTIONS requests
        if request.method == "OPTIONS":
            if is_origin_allowed(origin):
                response = Response(status_code=200)
                response.headers["Access-Control-Allow-Origin"] = origin
                response.headers["Access-Control-Allow-Credentials"] = "true"
                response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, PATCH, OPTIONS"
                response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Subdomain, X-Tenant, Cookie"
                response.headers["Access-Control-Max-Age"] = "600"
                return response
            else:
                return Response(status_code=403)

        # Process the actual request
        response = await call_next(request)

        # Set CORS headers if origin is allowed
        if origin and is_origin_allowed(origin):
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, PATCH, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Subdomain, X-Tenant, Cookie"

        return response


def add_cors_middleware(app):
    app.add_middleware(DynamicCORSMiddleware)
