from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import  func
from sqlalchemy.sql import text
from fastapi import APIRouter, Depends, HTTPException, status, Request, Query, Path
from pydantic import BaseModel
from datetime import datetime
from src.config.db import default_engine, extract_subdomain_from_request
from src.authorization.utils import verify_access_token, get_password_hash
from src.common.query import (get_users_tenant_admin_query)
from .models import Base, ConUser, conRoleMaster, ConRoleMenuMap, ConOrgMaster, ConUserRoleMapping


router = APIRouter()

router = APIRouter(
    prefix="",
    responses={404: {"description": "Not found"}},
)

def get_org_id_from_subdomain(subdomain: str, db: Session) -> int:
    """
    Get the organization ID for a given subdomain using raw SQL.

    Args:
        subdomain (str): Subdomain extracted from the request.
        db (Session): SQLAlchemy session.

    Returns:
        int: Organization ID.

    Raises:
        HTTPException: If organization is not found or on DB error.
    """
    try:
        sql = text(
            "SELECT con_org_id "
            "FROM con_org_master "
            "WHERE con_org_shortname = :subdomain"
        )
        org_id = db.execute(sql, {"subdomain": subdomain}).scalar()

        if org_id is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Organization with subdomain {subdomain} not found",
            )

        return org_id

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in get_org_id_from_subdomain: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error retrieving organization ID: {str(e)}",
        )
    

@router.get("/get_user_tenant_admin")
def get_users_tenant_admin(
    request: Request,
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1),
    search: Optional[str] = None,
    token_data: dict = Depends(verify_access_token),
):
    """
    Get list of users for tenant admin
    
    Args:
        request (Request): FastAPI request object
        page (int): Page number for pagination
        limit (int): Number of items per page
        search (Optional[str]): Search string to filter users
        token_data (dict): Authentication token data
        
    Returns:
        dict: Dictionary containing users data and total count
    """
    print("Starting users_tenant_admin endpoint")
    try:
        # Verify user from token
        user_id = token_data.get("user_id")
        if not user_id:
            raise HTTPException(status_code=403, detail="User ID not found in token")

        # Calculate offset for pagination
        offset = (page - 1) * limit
        print(f"Calculated offset: {offset} for page: {page} and limit: {limit}")

        # Get subdomain from request
        subdomain = extract_subdomain_from_request(request)
        print(f"Extracted subdomain: {subdomain}")

        with Session(default_engine) as session:
            # Get org_id from subdomain
            org_id = get_org_id_from_subdomain(subdomain, session)
            print(f"Retrieved org_id: {org_id} for subdomain: {subdomain}")

            # First get total count
            count_query = text("""
                SELECT COUNT(*) as total
                FROM con_user_master cum 
                WHERE cum.con_org_id = :org_id
                AND (:search IS NULL OR 
                    cum.con_user_name LIKE :search OR 
                    cum.con_user_login_email_id LIKE :search)
            """)
            
            count_params = {
                "org_id": org_id,
                "search": f"%{search}%" if search else None
            }
            
            total_count = session.execute(count_query, count_params).scalar()
            print(f"Total count: {total_count}")

            # Get users query
            query = get_users_tenant_admin_query(search, org_id)
            print(f"Executing query for org_id: {org_id}, search: {search}")

            # Execute query with parameters
            params = {
                "org_id": org_id,
                "search": f"%{search}%" if search else None,
                "limit": limit,
                "offset": offset
            }
            print(f"Query parameters: {params}")

            result = session.execute(query, params)
            users = result.fetchall()
            print(f"Query returned {len(users) if users else 0} results")

            # Convert result to list of dictionaries
            users = [dict(r._mapping) for r in users]

            return {
                "data": users,
                "total": total_count
            }

    except HTTPException as he:
        print(f"HTTP Exception in get_users_tenant_admin: {str(he)}")
        raise
    except Exception as e:
        print(f"Unexpected error in get_users_tenant_admin: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )


@router.get("/get_roles_tenant_admin_assign")
def get_roles_tenant_admin_assign(
    request: Request,
    token_data: dict = Depends(verify_access_token),
):
    """
    Get list of enabled roles for tenant admin assignment
    
    Args:
        request (Request): FastAPI request object
        token_data (dict): Authentication token data
        
    Returns:
        list: List of roles with their IDs and names
    """
    try:
        # Verify user from token
        user_id = token_data.get("user_id")
        if not user_id:
            raise HTTPException(status_code=403, detail="User ID not found in token")

        # Get subdomain from request
        subdomain = extract_subdomain_from_request(request)

        with Session(default_engine) as session:
            # Get org_id from subdomain
            org_id = get_org_id_from_subdomain(subdomain, session)

            # Get roles query
            query = text("""
                SELECT con_role_id, con_role_name
                FROM con_role_master crm
                WHERE is_enable = 1
                AND con_org_id = :org_id
                ORDER BY con_role_name
            """)

            result = session.execute(query, {"org_id": org_id})
            roles = [dict(r._mapping) for r in result.fetchall()]

            return roles

    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )

class CreateUserTenantAdmin(BaseModel):
    name: str
    email: str
    roleId: int
    active: int
    password: str

@router.post("/create_user_tenant_admin")
def create_user_tenant_admin(
    request: Request,
    user_data: CreateUserTenantAdmin,
    token_data: dict = Depends(verify_access_token),
):
    """
    Create a new tenant admin user with role mapping
    
    Args:
        request (Request): FastAPI request object
        user_data (CreateUserTenantAdmin): User data from request body
        token_data (dict): Authentication token data
        
    Returns:
        dict: Created user details
    """
    try:
        # Verify user from token
        user_id = token_data.get("user_id")
        if not user_id:
            raise HTTPException(status_code=403, detail="User ID not found in token")

        # Get subdomain from request
        subdomain = extract_subdomain_from_request(request)

        with Session(default_engine) as session:
            # Get org_id from subdomain
            org_id = get_org_id_from_subdomain(subdomain, session)

            # Hash the password
            hashed_password = get_password_hash(user_data.password)

            # Create new user
            new_user = ConUser(
                con_org_id=org_id,
                con_user_login_email_id=user_data.email,
                con_user_login_password=hashed_password,
                con_user_name=user_data.name,
                con_user_type=1,  # Default to 1 for tenant admin
                created_by=user_id,
                active=user_data.active,
                refresh_token=None
            )
            
            session.add(new_user)
            session.flush()  # This will set the ID of the new user

            # Create role mapping
            role_mapping = ConUserRoleMapping(
                con_role_id=user_data.roleId,
                con_user_id=new_user.con_user_id,
                created_by=user_id
            )
            
            session.add(role_mapping)
            session.commit()

            return {
                "message": "User created successfully",
                "user_id": new_user.con_user_id,
                "role_mapping_id": role_mapping.con_user_role_mapping_id
            }

    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )

class EditUserTenantAdmin(BaseModel):
    userId: str
    roleId: Optional[int] = None
    active: Optional[int] = None
    timestamp: datetime

@router.post("/edit_user_tenant_admin")
def edit_user_tenant_admin(
    request: Request,
    payload: EditUserTenantAdmin,
    token_data: dict = Depends(verify_access_token),
):
    """
    Update user role and active status for tenant admin
    
    Args:
        request (Request): FastAPI request object
        submit_data (EditUserTenantAdmin): Data containing updates for user
        token_data (dict): Authentication token data
        
    Returns:
        dict: Status of the update operation
    """
    try:
        # Verify user from token
        user_id = token_data.get("user_id")
        if not user_id:
            raise HTTPException(status_code=403, detail="User ID not found in token")

        with Session(default_engine) as session:
            # Convert userId to integer
            target_user_id = int(payload.userId)
            
            # Handle role update if roleId is provided
            if payload.roleId is not None:
                # Delete existing role mapping
                session.query(ConUserRoleMapping).filter(
                    ConUserRoleMapping.con_user_id == target_user_id
                ).delete()
                
                # Create new role mapping
                new_role_mapping = ConUserRoleMapping(
                    con_role_id=payload.roleId,
                    con_user_id=target_user_id,
                    created_by=user_id,
                    created_date_time=payload.timestamp
                )
                session.add(new_role_mapping)
            
            # Handle active status update if active is provided
            if payload.active is not None:
                session.query(ConUser).filter(
                    ConUser.con_user_id == target_user_id
                ).update({
                    ConUser.active: payload.active
                })
            
            session.commit()
            
            return {
                "message": "User updated successfully",
                "user_id": target_user_id,
                "updates": {
                    "role_updated": payload.roleId is not None,
                    "active_status_updated": payload.active is not None
                }
            }

    except ValueError as ve:
        raise HTTPException(status_code=400, detail=f"Invalid user ID format: {str(ve)}")
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )











