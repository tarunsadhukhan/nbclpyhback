from fastapi import Depends, Request, HTTPException, APIRouter, Query, Path
from sqlalchemy.orm import Session
from sqlalchemy import text
from src.config.db import get_db_names,default_engine, get_tenant_db
from src.authorization.utils import verify_access_token
from src.common.companyAdmin.models import DeptMst, BranchMst
from src.common.companyAdmin.query import get_department_all_query, get_department_all_count_query, get_branch_by_id_query
from src.common.companyAdmin.query import get_country_query, get_state_query, get_co_all_query_nosearch,get_branch_query_nosearch
from src.common.companyAdmin.query import get_department_by_id_query,get_subdepartment_all_query,get_subdepartment_all_count_query
from src.common.companyAdmin.schemas import DeptCreate, BranchCreate
from typing import Optional, List
from pydantic import BaseModel
from datetime import datetime


router = APIRouter()

@router.get("/get_department_data_all")
def getBranchFull(
    request: Request,
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1),
    search: Optional[str] = None,
    token_data: dict = Depends(verify_access_token),  # Use the new dependency  
    db: Session = Depends(get_tenant_db)
    ):
    offset = (page - 1) * limit
    try:

            query = get_department_all_query(search, offset, limit)
            # text(f"SELECT con_menu_id, con_menu_name, con_menu_parent_id FROM con_menu_master where active =1")
            params = {
                "search": f"%{search}%" if search else None,
                "limit": limit,
                "offset": offset
            }
            query_count = get_department_all_count_query(search)
            count_params = {
                "search": f"%{search}%" if search else None
            }
            coData = db.execute(query, params).fetchall()
            result_count = db.execute(query_count, count_params).scalar()
            # total_count = session.execute(count_query, count_params).scalar()
            result = [dict(r._mapping) for r in coData]
            return {
                "data": result,
                "total": result_count,
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


@router.get("/get_subdepartment_data_all")
def getBranchFull(
    request: Request,
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1),
    search: Optional[str] = None,
    token_data: dict = Depends(verify_access_token),  # Use the new dependency  
    db: Session = Depends(get_tenant_db)
    ):
    offset = (page - 1) * limit
    try:

            query = get_subdepartment_all_query(search, offset, limit)
            # text(f"SELECT con_menu_id, con_menu_name, con_menu_parent_id FROM con_menu_master where active =1")
            params = {
                "search": f"%{search}%" if search else None,
                "limit": limit,
                "offset": offset
            }
            query_count = get_subdepartment_all_count_query(search)
            count_params = {
                "search": f"%{search}%" if search else None
            }
            coData = db.execute(query, params).fetchall()
            result_count = db.execute(query_count, count_params).scalar()
            # total_count = session.execute(count_query, count_params).scalar()
            result = [dict(r._mapping) for r in coData]
            return {
                "data": result,
                "total": result_count,
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



@router.get("/get_branch_data_by_id/{branch_id}")
def get_branch_data_by_id(
    branch_id: int,
    token_data: dict = Depends(verify_access_token),
    db: Session = Depends(get_tenant_db),
):
    try:
            query = get_branch_by_id_query(branch_id)
            branch_details = db.execute(query, {"branch_id": branch_id}).fetchone()
            countries   = db.execute(get_country_query()).fetchall()
            states      = db.execute(get_state_query()).fetchall()
            return {
                "data": dict(branch_details._mapping),
                "countries":       [dict(c._mapping) for c in countries],
                "states":          [dict(s._mapping) for s in states],
            }
    except HTTPException:
        raise
    except Exception as exc:
        print(f"Unexpected error in get_org_data_by_id: {exc}")
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail="Internal server error")
    

@router.get("/get_department_data_by_id/{dept_id}")
def get_branch_data_by_id(
    dept_id: int,
    token_data: dict = Depends(verify_access_token),
    db: Session = Depends(get_tenant_db),
):
    try:
            query = get_department_by_id_query(dept_id)
            dept_details = db.execute(query, {"dept_id": dept_id}).fetchone()
            return {
                "data": dict(dept_details._mapping),
            }
    except HTTPException:
        raise
    except Exception as exc:
        print(f"Unexpected error in get_org_data_by_id: {exc}")
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail="Internal server error")




@router.get("/create_branch_setup_data")
def create_branch_setup_data(
    token_data: dict = Depends(verify_access_token),
    db: Session = Depends(get_tenant_db),
):
    try:
            company = db.execute(get_co_all_query_nosearch()).fetchall()
            branch = db.execute(get_branch_query_nosearch()).fetchall()
            countries   = db.execute(get_country_query()).fetchall()
            states      = db.execute(get_state_query()).fetchall()
            return {
                "company": [dict(co._mapping) for co in company],
                "branches":    [dict(b._mapping) for b in branch],
                "countries":    [dict(c._mapping) for c in countries],
                "states":       [dict(s._mapping) for s in states],
            }
    except HTTPException:
        raise
    except Exception as exc:
        print(f"Unexpected error in get_org_data_by_id: {exc}")
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail="Internal server error")
    
@router.post("/create_department_data")
def create_department_data(
    payload: DeptCreate,
    token_data: dict = Depends(verify_access_token),
    db: Session = Depends(get_tenant_db),
):
    """
    Insert a new company record using the ORM model and return its id.
    """
    print(f"Payload received: {payload}")

    try:
        # Create the company using the tenant database
        print(f"Payload received: {payload}")
        new_dept = DeptMst(
        dept_desc = payload.dept_desc,
        branch_id = payload.branch_id,
        dept_code = payload.dept_code,
        order_id = payload.order_id,
        created_by =  token_data.get("user_id", None),
        )
        
        db.add(new_dept)
        db.flush()  # Get the ID without committing
        db.commit()
        
        return {"message": f"Department created successfully Department_id {new_dept.dept_id}"}
    except HTTPException:
        raise
    except Exception as exc:
        print(f"Unexpected error in create_branch_data: {exc}")
        import traceback; traceback.print_exc()
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(exc)}")
    



@router.post("/edit_department_data")
def edit_department_data(
    payload: DeptCreate,
    token_data: dict = Depends(verify_access_token),
    db: Session = Depends(get_tenant_db),
):
    """
    Update an existing branch record using the ORM model.
    branch_id is expected to be included in the payload.
    """
    try:        # Extract branch_id from the payload
        dept_id = payload.dept_id
        if dept_id is None:
            raise HTTPException(status_code=400, detail="dept_id is required in the payload")
        
        # Convert branch_id to int if it's a string
        if isinstance(dept_id, str):
            try:
                dept_id = int(dept_id)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid dept_id format")        # Get the existing branch
        dept = db.query(DeptMst).filter(DeptMst.dept_id == dept_id).first()
        if dept is None:
            raise HTTPException(status_code=404, detail="Dept not found")

        # Update the company fields
        dept.dept_desc = payload.dept_desc
        dept.branch_id = payload.branch_id
        dept.dept_desc = payload.dept_desc
        dept.created_by = token_data.get("user_id", None)         
        # dept.created_date = datetime.now()  # Update created_date to current timestamp
        # # Only update active status if it's provided in the payload
        # if payload.active is not None:
        #     company.active = payload.active
        db.commit()
        
        return {"message":  f"Department created successfully Department_id {dept.dept_id}"}
        return {"message":  f"Department created successfully Department_id {dept.dept_id}"}
    except HTTPException:
        raise
    except Exception as exc:
        print(f"Unexpected error in edit_branch_data: {exc}")
        import traceback; traceback.print_exc()
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(exc)}")



@router.delete("/delete_department_data/{dept_id}")
def delete_department(
    dept_id: int = Path(..., description="ID of the department to delete"),
    token_data: dict = Depends(verify_access_token),
    db: Session = Depends(get_tenant_db),
):
    """
    Delete a department and log who deleted it using MySQL session variable @current_user_id.
    """
    try:
        # Step 1: Set the MySQL session variable for logging
        user_id = token_data.get("user_id")
        if user_id is None:
            raise HTTPException(status_code=403, detail="User ID not found in token")

        db.execute(text(f"SET @current_user_id = {user_id}"))

        # Step 2: Fetch and delete the department
        dept = db.query(DeptMst).filter(DeptMst.dept_id == dept_id).first()
        if not dept:
            raise HTTPException(status_code=404, detail="Department not found")

        db.delete(dept)
        db.commit()

        return {"message": f"Department with ID {dept_id} deleted successfully."}

    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        print(f"Unexpected error: {exc}")
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail="Internal server error")

