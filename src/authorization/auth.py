from src.authorization.utils import create_access_token, create_refresh_token, verify_password
from fastapi import Request, HTTPException, Response
from sqlalchemy.sql import text
from src.config.db import get_db_names, default_engine, Session, extract_subdomain_from_request, get_tenant_engine
from fastapi.responses import JSONResponse
from src.authorization.query import (
    get_admin_login_query,
    get_company_admin_login_query,
)
import os

def login_user_console(
    request: Request,
    username: str,
    password: str,
    logintype: str,
    subdomain: str,
):
    """Login logic - Queries user table where username, password, and subdomain match"""
    try:
        with Session(default_engine) as session:
            request_subdomain = extract_subdomain_from_request(request).strip().lower()
            header_subdomain = (subdomain or "").strip().lower()
            resolved_subdomain = request_subdomain if request_subdomain and request_subdomain != "default" else header_subdomain

            if not resolved_subdomain:
                resolved_subdomain = "default"

            # Get appropriate query and bind params based on subdomain
            if resolved_subdomain == "admin":
                query = get_admin_login_query()
                query_params = {"username": username}
            else:
                query = get_company_admin_login_query()
                query_params = {
                    "username": username,
                    "subdomain": resolved_subdomain,
                }

            # Execute query and get user
            result = session.execute(query, query_params)
            user = result.fetchone() if result else None

            # Validate user exists
            if not user or not hasattr(user, 'con_user_login_password'):
                return JSONResponse(
                    content={
                        "access_token": "",
                        "token_type": "",
                        "status": 401,
                        "message": "User is not registered",
                    },
                    status_code=401,
                )

            # Validate password
            if not verify_password(password, user.con_user_login_password):
                return JSONResponse(
                    content={
                        "access_token": "",
                        "token_type": "",
                        "status": 401,
                        "message": "Wrong password entered",
                    },
                    status_code=401,
                )

            # Create tokens
            user_id = getattr(user, 'con_user_id', None)
            if not user_id:
                raise HTTPException(status_code=500, detail="User ID not found in database")

            # Build token payload with org context for session validation
            con_org_id = getattr(user, 'con_org_id', None)
            token_payload = {
                "user_id": user_id,
                "con_org_id": con_org_id,
                "subdomain": resolved_subdomain,
            }

            # Create access token for frontend
            token = create_access_token(token_payload)
            
            # Create refresh token (stored only in DB)
            refresh_token = create_refresh_token(token_payload)
            
            # Update refresh token in DB only
            try:
                update_query = text("""
                    UPDATE maindata.con_user_master 
                    SET refresh_token = :refresh_token 
                    WHERE con_user_login_email_id = :username
                """)
                session.execute(update_query, {
                    "username": username,
                    "refresh_token": refresh_token
                })
                session.commit()
                print('Refresh token updated in database for:', username)
            except Exception as e:
                print('Error updating refresh token:', str(e))
                raise HTTPException(status_code=500, detail="Failed to update refresh token")

            # Create response with access token only
            response = JSONResponse(
                content={
                    "message": "Login successful",
                    "status": 200,
                    "access_token": token,
                    "user_id": user_id
                },
                status_code=200
            )

            # Set only access token cookie and ensure any legacy refresh cookie is cleared
            ENV = os.getenv("ENV", "development")
            COOKIE_DOMAIN = ".vowerp.co.in" if ENV == "production" else None
            SECURE = True if ENV == "production" else False
            SAMESITE = "None" if ENV == "production" else "Lax"

            response.set_cookie(
                key="access_token",
                value=token,
                httponly=True,
                secure=SECURE,
                samesite=SAMESITE,
                path="/",
                domain=COOKIE_DOMAIN
            )
            response.delete_cookie(
                key="refresh_token",
                path="/",
                domain=COOKIE_DOMAIN
            )

            return response

    except Exception as e:
        print(f"Login error: {str(e)}")
        return JSONResponse(
            content={
                "access_token": "",
                "token_type": "",
                "status": 500,
                "message": "Internal server error",
            },
            status_code=500,
        )


def login_user(
    request: Request,
    username: str,
    password: str,
    logintype: str,
    subdomain: str,
):
    """Login logic for portal users - Queries user_mst table where email_id and password match"""
    print("\n=== Processing Login in auth.py ===")
    try:
        # Get the subdomain and create appropriate database session
        subdomain = extract_subdomain_from_request(request)
        print(f"🌐 Using database for subdomain: {subdomain}")

        tenant_engine = get_tenant_engine(subdomain)

        with Session(tenant_engine) as session:
            print("🔄 Database session started")
            
            # Query user from user_mst table
            query = text("""
                SELECT user_id, password, active
                FROM user_mst
                WHERE email_id = :username
                AND active = TRUE
            """)
            print(f"🔍 Executing query for user: {username}")
            print(f"📝 SQL Query: {query}")
            
            try:
                result = session.execute(query, {"username": username})
                user = result.fetchone()
                print(f"📋 Query result: {user is not None}")
                
                if not user:
                    print("❌ No user found with this email")
                    return JSONResponse(
                        content={
                            "access_token": "",
                            "token_type": "",
                            "status": 401,
                            "message": "Invalid username or password",
                        },
                        status_code=401,
                    )
                
                print("🔐 Verifying password...")
                if not verify_password(password, user.password):
                    print("❌ Password verification failed")
                    return JSONResponse(
                        content={
                            "access_token": "",
                            "token_type": "",
                            "status": 401,
                            "message": "Invalid username or password",
                        },
                        status_code=401,
                    )
                print("✅ Password verified successfully")

                # Create tokens with portal type included
                token_data = {
                    "user_id": user.user_id,
                    "type": "portal"
                }
                print(f"🎫 Creating tokens for user_id: {user.user_id}")
                
                # Create access token for frontend
                token = create_access_token(token_data)
                print("✅ Access token created")
                
                # Create refresh token
                refresh_token = create_refresh_token(token_data)
                print("✅ Refresh token created")
                
                # Update refresh token in DB
                try:
                    print("🔄 Updating refresh token in database")
                    update_query = text("""
                        UPDATE user_mst 
                        SET refresh_token = :refresh_token 
                        WHERE email_id = :username
                    """)
                    session.execute(update_query, {
                        "username": username,
                        "refresh_token": refresh_token
                    })
                    session.commit()
                    print('✅ Refresh token updated in database')
                except Exception as e:
                    print(f'❌ Error updating refresh token: {str(e)}')
                    raise HTTPException(status_code=500, detail="Failed to update refresh token")

                # Create response
                response = JSONResponse(
                    content={
                        "message": "Login successful",
                        "status": 200,
                        "access_token": token,
                        "user_id": user.user_id
                    },
                    status_code=200
                )

                # Set cookie with proper configuration
                ENV = os.getenv("ENV", "development")
                COOKIE_DOMAIN = ".vowerp.co.in" if ENV == "production" else None
                SECURE = True if ENV == "production" else False
                SAMESITE = "None" if ENV == "production" else "Lax"
                
                print(f"""🍪 Setting cookie with configuration:
                Domain: {COOKIE_DOMAIN}
                Secure: {SECURE}
                SameSite: {SAMESITE}""")
                
                response.set_cookie(
                    key="access_token",
                    value=token,
                    httponly=True,
                    secure=SECURE,
                    samesite=SAMESITE,
                    path="/",
                    domain=COOKIE_DOMAIN
                )
                response.delete_cookie(
                    key="refresh_token",
                    path="/",
                    domain=COOKIE_DOMAIN
                )
                print("✅ Cookie set successfully")

                return response

            except Exception as e:
                print(f"❌ Database query error: {str(e)}")
                print(f"Error type: {type(e).__name__}")
                print(f"Error details: {e.__dict__}")
                raise

    except Exception as e:
        print(f"❌ Login error: {str(e)}")
        print(f"Error type: {type(e).__name__}")
        print(f"Error details: {e.__dict__}")
        return JSONResponse(
            content={
                "access_token": "",
                "token_type": "",
                "status": 500,
                "message": f"Internal server error: {str(e)}",
            },
            status_code=500,
        )