from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import  func
from sqlalchemy.sql import text
from fastapi import APIRouter, Depends, HTTPException, status, Request, Query, Path
from pydantic import BaseModel
from src.config.db import default_engine,extract_subdomain_from_request
from src.authorization.utils import verify_access_token
from src.common.query import (get_roles_ctrldsk_admin,get_roles_ctrldsk_full_menu,get_roles_ctrldsk_menu_by_roleid)
from .models import Base, ConUser, conRoleMaster, ConRoleMenuMap
from src.common.companyAdmin.users import get_org_id_from_subdomain


router = APIRouter()

# Define the API router for role endpoints
router = APIRouter(
    prefix="",
    responses={404: {"description": "Not found"}},
)


# function to find the org_id of the user 
def get_org_id_for_user(user_id: int) -> int:
    """
    Get the organization ID for a given user.
    
    Args:
        user_id (int): The ID of the user
        db (Session): SQLAlchemy database session
        
    Returns:
        int: The organization ID of the user
        
    Raises:
        HTTPException: If user not found or database error occurs
    """
    print(f"Getting org_id for user_id: {user_id}")
    try:
        # Use default_engine to create a new session
        with Session(default_engine) as session:

            # Add debug query printing
            query = session.query(ConUser).filter(ConUser.con_user_id == user_id)
            print(f"Executing query: {query}")
            
            user = query.first()
            print(f"Query result: {user}")
            
            if not user:
                print(f"No user found for user_id: {user_id}")
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"User with ID {user_id} not found"
                )
            
            org_id = user.con_org_id
            print(f"Found org_id: {org_id} for user_id: {user_id}")
            return org_id if org_id else None
            
    except HTTPException as he:
        print(f"HTTP Exception in get_org_id_for_user: {str(he)}")
        raise
    except Exception as e:
        print(f"Error in get_org_id_for_user: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error retrieving organization ID: {str(e)}"
        )



@router.get("/roles_ctrldsk_admin")
def get_roles(
    request: Request,
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1),
    search: Optional[str] = None,
    token_data: dict = Depends(verify_access_token),  # Use the new dependency
):
    print("Starting roles_tenant_admin endpoint")
    try:
        user_id_ck = token_data.get("user_id")  
        if not user_id_ck:
            raise HTTPException(status_code=403, detail="User ID not found in token")

        offset = (page - 1) * limit
        print(f"Calculated offset: {offset} for page: {page} and limit: {limit}")
        subdomain = extract_subdomain_from_request(request)
    except HTTPException as he:
        print(f"HTTP Exception in get_roles: {str(he)}")
            
    try:
        with Session(default_engine) as session:
            
            # org_id = get_org_id_from_subdomain(subdomain, session)
            # Create query with org_id
            query = get_roles_ctrldsk_admin(search)
            print(f"Executing query for org_id:  search: {search}")
            roles = session.execute(query, {"limit": limit, "offset": offset, "search": f"%{search}%" if search else None}).fetchall()
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


# @router.get("/admin_tenant_menu_full")
# async def get_admin_tenant_menu_full(
#     token_data: dict = Depends(verify_access_token),  # Use the new dependency  
#     ):
#     try:
#         with Session(default_engine) as session:
#             query = text(f"SELECT con_menu_id, con_menu_name, con_menu_parent_id FROM con_menu_master where active =1")
#             result = session.execute(query).fetchall()
#             print(f"Query returned {len(result)} results")
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=f"Query execution error: {str(e)}")
#     try:
#         menus = [dict(row._mapping) for row in result]  # Use _mapping to convert rows to dictionaries
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=f"Data conversion error: {str(e)}")
            
#     return {"data": menus}


@router.get("/admin_ctrldsk_menu_full")
def get_admin_tenant_menu_full(
    token_data: dict = Depends(verify_access_token),  # Use the new dependency  
    ):
    try:
        with Session(default_engine) as session:
            query = get_roles_ctrldsk_full_menu()
            # text(f"SELECT con_menu_id, con_menu_name, con_menu_parent_id FROM con_menu_master where active =1")
            result = session.execute(query).fetchall()
            print(f"Query returned {len(result)} results")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query execution error: {str(e)}")
    try:
        menus = [dict(row._mapping) for row in result]  # Use _mapping to convert rows to dictionaries
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Data conversion error: {str(e)}")
            
    return {"data": menus}


@router.get("/admin_ctrldsk_menu_by_roleid/{role_id}")
def get_admin_tenant_menu_by_roleid(
    _: dict = Depends(verify_access_token), 
    role_id: int = Path(..., description="Role ID to filter menus"),  
):
    try:
        with Session(default_engine) as session:
            # Fetch menus for the given role_id
            menu_query = text("""
                SELECT cmm.control_desk_menu_id con_menu_id, cmm.control_desk_menu_name con_menu_name, case when cmm.parent_id=0 then null else parent_id end con_menu_parent_id, crmm.con_role_id
    FROM control_desk_menu cmm 
    LEFT JOIN con_role_menu_map crmm 
    ON crmm.con_menu_id = cmm.control_desk_menu_id 
    and crmm.con_role_id = :role_id
            """).bindparams(role_id=role_id)
            menu_result = session.execute(menu_query).fetchall()
            print(f"Menu query returned {len(menu_result)} results")

            # Fetch role name for the given role_id
            role_query = text("""
                SELECT con_role_name 
                FROM con_role_master 
                WHERE con_role_id = :role_id
            """).bindparams(role_id=role_id)
            role_result = session.execute(role_query).fetchone()
            print(f"Role query returned: {role_result}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query execution error: {str(e)}")

    try:
        # Convert menu query results to dictionaries
        menus = [dict(row._mapping) for row in menu_result]  # row._mapping works across SQLAlchemy versions
        role_name = role_result[0] if role_result else None
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Data conversion error: {str(e)}")
    return {"data": menus, "roleName": role_name}

# Create a Pydantic model for the role creation request
class CreateRoleTenantAdminRequest(BaseModel):
    roleName: str
    selectedMenuIds: List[int]

# Add new Pydantic model after CreateRoleTenantAdminRequest
class EditRoleTenantAdminRequest(BaseModel):
    roleId: int
    selectedMenuIds: List[int]

@router.put("/create_role_ctrldsk_admin")
def create_role_tenant_admin(
    request: Request,
    role_data: CreateRoleTenantAdminRequest,
    token_data: dict = Depends(verify_access_token),
):
    """
    Create or update a tenant admin role with selected menu items
    
    Args:
        role_data: Role data including name and selected menu IDs
        token_data: Authentication token data
        
    Returns:
        Dict with status and created role data
    """
    print("Starting create_role_tenant_admin endpoint")
    try:
        user_id = token_data.get("user_id")
        if not user_id:
            raise HTTPException(status_code=403, detail="User ID not found in token")
        
        print(f"Authenticated user ID: {user_id}")
        
        # Print the received data
        print(f"Received role name: {role_data.roleName}")
        print(f"Received selected menu IDs: {role_data.selectedMenuIds}")
        
        # Get the org_id for the user
        subdomain = extract_subdomain_from_request(request)
        
        
        with Session(default_engine) as session:
            
            try:
                # org_id = get_org_id_from_subdomain(subdomain, session)
                # Create a new role
                new_role = conRoleMaster(
                    con_role_name=role_data.roleName,
                    # con_org_id=org_id,
                    status=1,  # Assuming 1 means active
                    created_by=user_id,
                    created_date_time=func.now(),
                    is_enable=1
                )
                
                session.add(new_role)
                session.flush()  # Flush to get the new role ID
                
                role_id = new_role.con_role_id
                print(f"Created new role with ID: {role_id}")
                
                # Create menu mappings for the role
                menu_mappings = []
                for menu_id in role_data.selectedMenuIds:
                    menu_mapping = ConRoleMenuMap(
                        con_role_id=role_id,
                        con_menu_id=menu_id
                    )
                    menu_mappings.append(menu_mapping)
                
                if menu_mappings:
                    session.add_all(menu_mappings)
                    print(f"Added {len(menu_mappings)} menu mappings")
                
                session.commit()
                
                return {
                    "status": "success",
                    "message": "Role and menu mappings created successfully",
                    "data": {
                        "role_id": role_id,
                        "role_name": role_data.roleName,
                        "mapped_menu_count": len(role_data.selectedMenuIds)
                    }
                }
                
            except Exception as db_error:
                session.rollback()
                print(f"Database error: {str(db_error)}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to create role: {str(db_error)}"
                )
        
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Unexpected error in create_role_tenant_admin: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )

# Add new endpoint before existing endpoints
@router.put("/edit_role_ctrldsk_admin")
def edit_role_tenant_admin(
    request: Request,
    role_data: EditRoleTenantAdminRequest,
    token_data: dict = Depends(verify_access_token),
):
    """
    Edit existing role menu mappings
    
    Args:
        role_data: Role data including role ID and selected menu IDs
        token_data: Authentication token data
        
    Returns:
        Dict with status and updated role data
    """
    print("Starting edit_role_tenant_admin endpoint")
    try:
        user_id = token_data.get("user_id")
        if not user_id:
            raise HTTPException(status_code=403, detail="User ID not found in token")
        
        print(f"Authenticated user ID: {user_id}")
        print(f"Editing role ID: {role_data.roleId}")
        print(f"New selected menu IDs: {role_data.selectedMenuIds}")
        
        with Session(default_engine) as session:
            try:
                # First verify if role exists
                role = session.query(conRoleMaster).filter(
                    conRoleMaster.con_role_id == role_data.roleId
                ).first()
                
                if not role:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Role with ID {role_data.roleId} not found"
                    )
                
                # Delete existing menu mappings for this role
                print(f"Deleting existing menu mappings for role {role_data.roleId}")
                delete_query = session.query(ConRoleMenuMap).filter(
                    ConRoleMenuMap.con_role_id == role_data.roleId
                ).delete()
                
                print(f"Deleted {delete_query} existing mappings")
                
                # Create new menu mappings
                menu_mappings = []
                for menu_id in role_data.selectedMenuIds:
                    menu_mapping = ConRoleMenuMap(
                        con_role_id=role_data.roleId,
                        con_menu_id=menu_id
                    )
                    menu_mappings.append(menu_mapping)
                
                if menu_mappings:
                    session.add_all(menu_mappings)
                    print(f"Added {len(menu_mappings)} new menu mappings")
                
                session.commit()
                
                return {
                    "status": "success",
                    "message": "Role menu mappings updated successfully",
                    "data": {
                        "role_id": role_data.roleId,
                        "role_name": role.con_role_name,
                        "mapped_menu_count": len(role_data.selectedMenuIds)
                    }
                }
                
            except Exception as db_error:
                session.rollback()
                print(f"Database error: {str(db_error)}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to update role menu mappings: {str(db_error)}"
                )
        
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Unexpected error in edit_role_tenant_admin: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )
    
    














