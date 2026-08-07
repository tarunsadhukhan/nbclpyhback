from typing import List, Optional
from datetime import datetime
from src.common.utils import now_ist
from sqlalchemy.orm import Session
from sqlalchemy import  func
from sqlalchemy.sql import text
from fastapi import APIRouter, Depends, HTTPException, status, Request, Query, Path
from pydantic import BaseModel
from src.config.db import default_engine, extract_subdomain_from_request, get_tenant_db
from src.authorization.utils import verify_access_token
from src.common.query import (get_roles_tenant)
from src.common.portal.models import Base, ConUser, conRoleMaster, ConRoleMenuMap, ApprovalMst
from src.authorization.utils import get_password_hash
from src.common.utils import get_org_id_from_subdomain
from src.common.portal.query import get_co_brnach_all, get_submenu_portal, get_submenu_by_branch, get_users_approval_portal, get_max_approval, get_approval_data


router = APIRouter()

@router.get("/co_branch_submenu")
def co_branch_submenu(
    request: Request,
    token_data: dict = Depends(verify_access_token),
    tenant_session: Session = Depends(get_tenant_db),
):
    try:
        # Get companies and branches
        company_branch_query = get_co_brnach_all()
        company_branch_result = tenant_session.execute(company_branch_query).fetchall()
        
        # Get submenus per branch based on actual relationships (branch → role → menu)
        submenu_by_branch_query = get_submenu_by_branch()
        submenu_by_branch_result = tenant_session.execute(submenu_by_branch_query).fetchall()
        
        # Process company and branch data
        companies = {}
        branches = {}
        
        # Extract unique companies and organize branches by company
        for row in company_branch_result:
            co_id = str(row.co_id)
            branch_id = str(row.branch_id)
            
            # Add company if not exists
            if co_id not in companies:
                companies[co_id] = {"id": co_id, "name": row.co_name}
            
            # Group branches by company
            if co_id not in branches:
                branches[co_id] = []
            
            branches[co_id].append({"id": branch_id, "name": row.branch_name})
        
        # Map menus to branches based on actual relationships
        menu_by_branch = {}
        
        # Process submenu results and group by branch_id
        for row in submenu_by_branch_result:
            branch_id = str(row.branch_id)
            menu_id = str(row.menu_id)
            menu_name = row.menu_name
            
            if branch_id not in menu_by_branch:
                menu_by_branch[branch_id] = []
            
            # Add menu if not already added (to handle duplicates)
            menu_exists = any(menu["id"] == menu_id for menu in menu_by_branch[branch_id])
            if not menu_exists:
                menu_by_branch[branch_id].append({
                    "id": menu_id,
                    "name": menu_name
                })
        
        # Ensure all branches have an entry (even if empty)
        for company_id, branch_items in branches.items():
            for branch in branch_items:
                branch_id = branch["id"]
                if branch_id not in menu_by_branch:
                    menu_by_branch[branch_id] = []
        
        # Construct the final response structure
        response = [
            {
                "id": "company",
                "label": "Company",
                "items": [{"id": company_id, "name": company["name"]} for company_id, company in companies.items()]
            },
            {
                "id": "branch",
                "label": "Branch",
                "dependsOn": "company",
                "items": {company_id: branch_items for company_id, branch_items in branches.items()}
            },
            {
                "id": "menu",
                "label": "Menu",
                "dependsOn": "branch",
                "items": menu_by_branch
            }
        ]
        
        return response
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving co_branch_submenu data: {str(e)}")

class ApprovalLevelDataRequest(BaseModel):
    menuId: str
    branchId: str


class ApprovalLevelDetail(BaseModel):
    level: int
    users: List[str]
    maxSingle: Optional[str] = None
    maxDay: Optional[str] = None
    maxMonth: Optional[str] = None


class ApprovalLevelDataSubmitRequest(BaseModel):
    menuId: str
    branchId: str
    data: List[ApprovalLevelDetail]

@router.post("/approval_level_data_setup")
def get_approval_level_data_setup(
    request: Request,
    payload: ApprovalLevelDataRequest,
    token_data: dict = Depends(verify_access_token),
    tenant_session: Session = Depends(get_tenant_db),
):
    try:
        menu_id = int(payload.menuId)
        branch_id = int(payload.branchId)
        
        # Get available users for this menu and branch
        users_query = get_users_approval_portal(menu_id=menu_id, branch_id=branch_id)
        users_result = tenant_session.execute(users_query, {"menu_id": menu_id, "branch_id": branch_id}).fetchall()

        # Get max approval level for this menu
        max_level_query = get_max_approval(menu_id=menu_id)
        max_level_result = tenant_session.execute(max_level_query, {"menu_id": menu_id}).scalar()
        max_level = max_level_result if max_level_result else 0
        
        # Get approval data for this menu and branch
        approval_data_query = get_approval_data(menu_id=menu_id, branch_id=branch_id)
        approval_data_result = tenant_session.execute(
            approval_data_query,
            {"menu_id": menu_id, "branch_id": branch_id}
        ).fetchall()
        
        # Format users as options
        user_options = []
        for row in users_result:
            user_options.append({
                "id": str(row.user_id),
                "name": row.email_id
            })
        
        # Process approval data
        approval_levels = []
        for row in approval_data_result:
            level_data = {
                "level": row.approval_level,
                "users": [str(row.user_id)],
                "maxSingle": str(row.max_amount_single) if row.max_amount_single else "",
                "maxDay": str(row.day_max_amount) if row.day_max_amount else "",
                "maxMonth": str(row.month_max_amount) if row.month_max_amount else ""
            }
            
            # Check if we already have this level in our list
            level_exists = False
            for i, existing_level in enumerate(approval_levels):
                if existing_level["level"] == row.approval_level:
                    # Add user to the existing level
                    approval_levels[i]["users"].append(str(row.user_id))
                    level_exists = True
                    break
            
            if not level_exists:
                approval_levels.append(level_data)
        
        # Format the response as required
        response = {
            f"{menu_id}": {
                "maxLevel": max_level,
                "userOptions": user_options,
                "data": approval_levels
            }
        }
        
        return response
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving approval data: {str(e)}")
    
    
@router.post("/approval_level_data_setup_submit")
def approval_level_data_setup_submit(
    request: Request,
    payload: ApprovalLevelDataSubmitRequest,
    token_data: dict = Depends(verify_access_token),
    tenant_session: Session = Depends(get_tenant_db),
):
    try:
        # Get the authenticated user ID from token
        updated_by_user_id = token_data.get("user_id")
        if not updated_by_user_id:
            raise HTTPException(status_code=403, detail="User ID not found in token")
        
        menu_id = int(payload.menuId)
        branch_id = int(payload.branchId)
        
        # First, delete all existing entries for this menu and branch
        delete_count = tenant_session.query(ApprovalMst).filter(
            ApprovalMst.menu_id == menu_id,
            ApprovalMst.branch_id == branch_id
        ).delete(synchronize_session='fetch')
        
        # Now create new entries for each level and user combination
        new_entries = []
        
        for level_data in payload.data:
            level = level_data.level
            
            # Convert empty strings to None for numeric fields
            max_single = float(level_data.maxSingle) if level_data.maxSingle and float(level_data.maxSingle) > 0 else None
            max_day = float(level_data.maxDay) if level_data.maxDay and float(level_data.maxDay) > 0 else None
            max_month = float(level_data.maxMonth) if level_data.maxMonth and float(level_data.maxMonth) > 0 else None
            
            # Create an entry for each user in this level
            for user_id_str in level_data.users:
                user_id = int(user_id_str)
                
                new_approval = ApprovalMst(
                    menu_id=menu_id,
                    branch_id=branch_id,
                    user_id=user_id,
                    approval_level=level,
                    max_amount_single=max_single,
                    day_max_amount=max_day,
                    month_max_amount=max_month,
                    updated_by=updated_by_user_id,
                    updated_date_time=now_ist(),
                )
                
                tenant_session.add(new_approval)
                new_entries.append(f"Level {level}, User {user_id}")
        
        # Commit all changes
        tenant_session.commit()
        
        return {
            "success": True,
            "message": "Approval configuration updated successfully",
            "deleted": delete_count,
            "created": len(new_entries),
            "entries": new_entries
        }
        
    except Exception as e:
        tenant_session.rollback()
        raise HTTPException(status_code=500, detail=f"Error updating approval configuration: {str(e)}")




