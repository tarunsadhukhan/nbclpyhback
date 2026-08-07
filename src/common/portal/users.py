from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import  func
from sqlalchemy.sql import text
from fastapi import APIRouter, Depends, HTTPException, status, Request, Query, Path, Header
from pydantic import BaseModel
from src.config.db import default_engine, extract_subdomain_from_request, get_tenant_db
from src.authorization.utils import verify_access_token, get_current_user_with_refresh
from src.common.query import (get_users_tenant)
from src.common.portal.models import Base, ConUser, conRoleMaster, ConRoleMenuMap, UserRoleMap
from src.authorization.utils import get_password_hash
from src.common.utils import get_org_id_from_subdomain
from src.common.portal.query import get_roles_tenant, get_co_tenant, get_branch_tenant, get_user_role_map_tenant
from src.common.portal.schemas import UserCreatePortal


router = APIRouter()

# Fixed default password applied when an admin resets another portal user's password.
DEFAULT_RESET_PASSWORD = "Vow@123"

@router.get("/get_users_portal")
def get_roles(
    request: Request,
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1),
    search: Optional[str] = None,
    token_data: dict = Depends(verify_access_token),  # Use the new dependency
    tenant_session: Session = Depends(get_tenant_db),  # Renamed to tenant_session for clarity
):
    print("Starting users_tenant_admin endpoint")
    try:
        user_id = token_data.get("user_id")  
        if not user_id:
            raise HTTPException(status_code=403, detail="User ID not found in token")

        offset = (page - 1) * limit
        print(f"Calculated offset: {offset} for page: {page} and limit: {limit}")
        # subdomain = extract_subdomain_from_request(request)
    except HTTPException as he:
        print(f"HTTP Exception in get_roles: {str(he)}")
            
    try:
        # Create query with org_id
        query = get_users_tenant(search)
        print(f"Executing query for search: {search}")
        roles = tenant_session.execute(query, {"limit": limit, "offset": offset, "search": f"%{search}%" if search else None}).fetchall()
        # roles = result.fetchall()
        print(f"Query returned {len(roles) if roles else 0} results")
    except Exception as query_error:
        print(f"Query execution error: {query_error}")
        raise HTTPException(status_code=500, detail=f"Query execution error: {str(query_error)}")

    try: 
        roles = [dict(r._mapping) for r in roles]
        print(f"Converted {len(roles)} rows to dictionaries")
        total = len(roles)
    except Exception as conversion_error:
        print(f"Data conversion error: {conversion_error}")
        raise HTTPException(status_code=500, detail=f"Data conversion error: {str(conversion_error)}")
       
    return { "data": roles, "total": total }


@router.get("/get_user_create_setup_data")
def get_user_create_setup_data(
    request: Request,
    token_data: dict = Depends(verify_access_token),  # Use the new dependency
    tenant_session: Session = Depends(get_tenant_db),  # Renamed to tenant_session for clarity
):
    try:
        user_id = token_data.get("user_id")  
        if not user_id:
            raise HTTPException(status_code=403, detail="User ID not found in token")

        print(f"Fetching setup data for user ID: {user_id}")
        roles_query = get_roles_tenant()
        co_query = get_co_tenant()
        branch_query = get_branch_tenant()

        roles = tenant_session.execute(roles_query).fetchall()
        co = tenant_session.execute(co_query).fetchall()
        branch = tenant_session.execute(branch_query).fetchall()

        # Convert to dictionaries first
        roles_dict = [dict(r._mapping) for r in roles]
        co_dict = [dict(c._mapping) for c in co]
        branch_dict = [dict(b._mapping) for b in branch]

        # Format roles as dropdown options
        role_dropdown_options = []
        for role in roles_dict:
            role_dropdown_options.append({
                "role_id": str(role["role_id"]),
                "role_name": role["role_name"]
            })
        
        # # Add "Not Assigned" option if needed
        # if not any(option["value"] == "0" for option in role_dropdown_options):
        #     role_dropdown_options.insert(0, {"value": "0", "label": "Not Assigned"})
        
        # Format companies with nested branches
        companies_with_branches = []
        for company in co_dict:
            company_branches = [
                {
                    "branch_id": branch["branch_id"],
                    "branch_name": branch["branch_name"],
                    "company_id": branch["co_id"],
                    "role_id": None  # Default to null, can be updated if needed
                }
                for branch in branch_dict
                if branch["co_id"] == company["co_id"]
            ]
            
            companies_with_branches.append({
                "company_id": company["co_id"],
                "company_name": company["co_name"],
                "branches": company_branches
            })

        print(f"Formatted {len(role_dropdown_options)} roles and {len(companies_with_branches)} companies with branches")
    except Exception as e:
        print(f"Error fetching setup data: {e}")
        raise HTTPException(status_code=500, detail=f"Error fetching setup data: {str(e)}")

    return {
        "roles": role_dropdown_options,
        "companies": companies_with_branches
    }


@router.get("/get_user_edit_setup_data/{portal_user_id}")
def get_user_edit_setup_data(
    request: Request,
    portal_user_id: int,  # Renamed from user_id to portal_user_id for clarity
    token_data: dict = Depends(verify_access_token),
    tenant_session: Session = Depends(get_tenant_db),
):
    try:
        admin_user_id = token_data.get("user_id")  # This is the admin user making the request
        if not admin_user_id:
            raise HTTPException(status_code=403, detail="User ID not found in token")

        print(f"Admin user {admin_user_id} fetching setup data for editing portal user ID: {portal_user_id}")
        
        # Get the user data - using portal_user_id from path parameter
        user = tenant_session.query(ConUser).filter(ConUser.user_id == portal_user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail=f"User with ID {portal_user_id} not found")
            
        # Get the roles, companies and branches (same as create setup)
        roles_query = get_roles_tenant()
        co_query = get_co_tenant()
        branch_query = get_branch_tenant()
        
        # Get the query template for the user's role mappings
        user_role_map_query = get_user_role_map_tenant()

        # Execute all queries
        roles = tenant_session.execute(roles_query).fetchall()
        co = tenant_session.execute(co_query).fetchall()
        branch = tenant_session.execute(branch_query).fetchall()
        
        # Execute the user role map query with explicit parameters
        user_roles = tenant_session.execute(
            user_role_map_query, 
            {"user_id": portal_user_id}  # Explicitly pass the portal_user_id as a parameter
        ).fetchall()
        
        print(f"Found {len(user_roles) if user_roles else 0} role mappings for portal user {portal_user_id}")

        # Convert to dictionaries
        roles_dict = [dict(r._mapping) for r in roles]
        co_dict = [dict(c._mapping) for c in co]
        branch_dict = [dict(b._mapping) for b in branch]
        user_roles_dict = [dict(ur._mapping) for ur in user_roles]

        # Format roles as dropdown options
        role_dropdown_options = []
        for role in roles_dict:
            role_dropdown_options.append({
                "role_id": str(role["role_id"]),
                "role_name": role["role_name"]
            })
        
        # Format companies with nested branches
        companies_with_branches = []
        for company in co_dict:
            company_branches = [
                {
                    "branch_id": branch["branch_id"],
                    "branch_name": branch["branch_name"],
                    "company_id": branch["co_id"],
                    "role_id": None  # Default to null, will be updated if there's a mapping
                }
                for branch in branch_dict
                if branch["co_id"] == company["co_id"]
            ]
            
            # Update role_id for branches that have roles assigned to this user
            for branch_data in company_branches:
                for user_role in user_roles_dict:
                    if (user_role["co_id"] == branch_data["company_id"] and 
                        user_role["branch_id"] == branch_data["branch_id"]):
                        branch_data["role_id"] = str(user_role["role_id"])
                        break
            
            companies_with_branches.append({
                "company_id": company["co_id"],
                "company_name": company["co_name"],
                "branches": company_branches
            })
        
        # Format the branch roles for the response
        branch_roles = []
        for user_role in user_roles_dict:
            branch_roles.append({
                "company_id": user_role["co_id"],
                "branch_id": user_role["branch_id"],
                "role_id": str(user_role["role_id"])
            })

        print(f"Formatted data for editing user {user.user_id} with {len(branch_roles)} role mappings")
        
        # Return user data in the same format as expected for create
        user_data = {
            "user_id": user.user_id,
            "name": user.name,
            "user_name": user.email_id,
            "is_active": user.active,
        }

    except Exception as e:
        print(f"Error fetching user edit setup data: {e}")
        raise HTTPException(status_code=500, detail=f"Error fetching user edit setup data: {str(e)}")

    return {
        "user": user_data,
        "roles": role_dropdown_options,
        "companies": companies_with_branches
    }


@router.post("/create_user_portal")
def create_user_portal(
    request: Request,
    user_data: UserCreatePortal,
    token_data: dict = Depends(verify_access_token),
    tenant_session: Session = Depends(get_tenant_db),
):
    try:
        creator_user_id = token_data.get("user_id")  
        if not creator_user_id:
            raise HTTPException(status_code=403, detail="User ID not found in token")

        # Check if user already exists
        existing_user = tenant_session.query(ConUser).filter(ConUser.email_id == user_data.user_name).first()
        if existing_user:
            raise HTTPException(status_code=400, detail="User with this email already exists")
            
        print(f"Creating user with email: {user_data.user_name}")
        
        # Hash the password
        hashed_password = get_password_hash(user_data.password)
        
        # Create new user
        new_user = ConUser(
            name=user_data.name,
            email_id=user_data.user_name,
            password=hashed_password,
            active=user_data.is_active,
            updated_by_con_user=creator_user_id,
            refresh_token=None,
        )
        
        # Add and commit to get the user_id
        tenant_session.add(new_user)
        tenant_session.flush()  # Get the ID without committing the transaction
        
        # Now create role mappings for each branch role
        role_mappings = []
        
        for branch_role in user_data.branch_roles:
            # Create a new role mapping for each branch-role pair
            role_map = UserRoleMap(
                user_id=new_user.user_id,
                role_id=int(branch_role.role_id),  # Convert to int as it might come as string
                co_id=branch_role.company_id,
                branch_id=branch_role.branch_id,
                updated_by_con_user=creator_user_id
            )
            role_mappings.append(role_map)
            tenant_session.add(role_map)
        
        # Commit all changes
        tenant_session.commit()
        tenant_session.refresh(new_user)
        
        print(f"User created with ID: {new_user.user_id} and {len(role_mappings)} role mappings")
        
        # Prepare response
        return {
            "success": True, 
            "message": "User created successfully", 
            "user_id": new_user.user_id,
            "roles_mapped": len(role_mappings)
        }
        
    except HTTPException as he:
        # Re-raise HTTP exceptions
        tenant_session.rollback()
        raise he
    except Exception as e:
        tenant_session.rollback()
        print(f"Error creating user: {e}")
        raise HTTPException(status_code=500, detail=f"Error creating user: {str(e)}")


class UserEditRequest(BaseModel):
    user_id: str
    is_active: bool
    branch_roles: List[dict]

@router.post("/edit_user_portal")
def edit_user_portal(
    request: Request,
    user_data: UserEditRequest,
    token_data: dict = Depends(verify_access_token),
    tenant_session: Session = Depends(get_tenant_db),
):
    """Edit a user in the portal by updating their active status and role mappings."""
    try:
        admin_user_id = token_data.get("user_id")
        if not admin_user_id:
            raise HTTPException(status_code=403, detail="User ID not found in token")

        # Parse and validate target user id
        user_id = int(user_data.user_id)

        print(f"Admin user {admin_user_id} editing portal user ID: {user_id}")

        # Fetch user
        user = tenant_session.query(ConUser).filter(ConUser.user_id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail=f"User with ID {user_id} not found")

        # Update active flag
        user.active = user_data.is_active

        # Delete existing role mappings using raw SQL to avoid ORM prefetch/select
        try:
            delete_stmt = text("DELETE FROM user_role_map WHERE user_id = :user_id")
            result = tenant_session.execute(delete_stmt, {"user_id": user_id})
            tenant_session.flush()
            delete_count = result.rowcount if result is not None else 0
            print(f"Deleted {delete_count} existing role mappings for user {user_id} (direct SQL)")
        except Exception as delete_error:
            print(f"Error during role mappings deletion (direct SQL): {str(delete_error)}")
            tenant_session.rollback()
            raise HTTPException(status_code=500, detail=f"Failed to delete existing role mappings: {str(delete_error)}")

        # Create new role mappings for each branch role
        role_mappings = []
        for branch_role in user_data.branch_roles:
            role_map = UserRoleMap(
                user_id=user_id,
                role_id=int(branch_role["role_id"]),
                co_id=branch_role["company_id"],
                branch_id=branch_role["branch_id"],
                updated_by_con_user=admin_user_id
            )
            role_mappings.append(role_map)
            tenant_session.add(role_map)

        tenant_session.commit()

        print(f"User {user_id} updated with active status: {user.active} and {len(role_mappings)} new role mappings")

        return {
            "success": True,
            "message": "User updated successfully",
            "user_id": user_id,
            "roles_mapped": len(role_mappings)
        }

    except HTTPException as he:
        tenant_session.rollback()
        raise he
    except Exception as e:
        tenant_session.rollback()
        print(f"Error updating user: {e}")
        raise HTTPException(status_code=500, detail=f"Error updating user: {str(e)}")


class ResetPasswordRequest(BaseModel):
    user_id: int


@router.post("/reset_user_password")
async def reset_user_password(
    request: Request,
    payload: ResetPasswordRequest,
    token_data: dict = Depends(get_current_user_with_refresh),
    tenant_session: Session = Depends(get_tenant_db),
):
    """Admin resets ANOTHER portal user's password to a fixed default.

    The acting admin does not supply a password; the target user's password is
    set to DEFAULT_RESET_PASSWORD, their refresh_token is cleared (invalidating
    existing sessions), and updated_by_con_user records the acting admin.
    """
    try:
        acting_user_id = token_data.get("user_id")
        if not acting_user_id:
            raise HTTPException(status_code=403, detail="User ID not found in token")

        # Validate target user id
        try:
            target_user_id = int(payload.user_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid user_id format")

        if not target_user_id:
            raise HTTPException(status_code=400, detail="user_id is required")

        # Fetch target user
        user = tenant_session.query(ConUser).filter(ConUser.user_id == target_user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail=f"User with ID {target_user_id} not found")

        # Reset password to fixed default, invalidate sessions, record acting admin
        user.password = get_password_hash(DEFAULT_RESET_PASSWORD)
        user.refresh_token = None
        user.updated_by_con_user = acting_user_id

        tenant_session.commit()

        print(f"Admin user {acting_user_id} reset password for portal user {target_user_id}")

        return {
            "data": {
                "message": "Password reset to default",
                "default_password": DEFAULT_RESET_PASSWORD,
            }
        }

    except HTTPException as he:
        tenant_session.rollback()
        raise he
    except Exception as e:
        tenant_session.rollback()
        print(f"Error resetting user password: {e}")
        raise HTTPException(status_code=500, detail=f"Error resetting user password: {str(e)}")




