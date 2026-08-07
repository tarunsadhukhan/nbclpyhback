from fastapi import Depends, Request, HTTPException,APIRouter, Query
from sqlalchemy.orm import Session
from src.config.db import  get_tenant_db
from src.authorization.utils import verify_access_token
from src.common.companyAdmin.models import BranchMst
from src.common.companyAdmin.query import get_branch_all_query, get_branch_by_id_query
from src.common.companyAdmin.query import get_country_query, get_state_query, get_co_all_query_nosearch,get_branch_query_nosearch
from src.common.companyAdmin.schemas import BranchCreate
from typing import Optional, List
from pydantic import BaseModel


router = APIRouter()

@router.get("/get_branch_data_all")
def getBranchFull(
    request: Request,
    search: Optional[str] = None,
    token_data: dict = Depends(verify_access_token),
    db: Session = Depends(get_tenant_db)
    ):
    try:
            query = get_branch_all_query(search)
            params = {
                "search": f"%{search}%" if search else None,
            }
            coData = db.execute(query, params).fetchall()
            result = [dict(r._mapping) for r in coData]
            return {
                "data": result,
                "total": len(result),
            }

    except HTTPException as he:
        print(f"HTTP Exception in get_branch_data_all: {str(he)}")
        raise
    except Exception as e:
        print(f"Unexpected error in get_branch_data_all: {str(e)}")
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
            company     = db.execute(get_co_all_query_nosearch()).fetchall()
            countries   = db.execute(get_country_query()).fetchall()
            states      = db.execute(get_state_query()).fetchall()
            return {
                "data": dict(branch_details._mapping),
                "company":         [dict(co._mapping) for co in company],
                "countries":       [dict(c._mapping) for c in countries],
                "states":          [dict(s._mapping) for s in states],
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
    
@router.post("/create_branch_data")
def create_branch_data(
    payload: BranchCreate,
    token_data: dict = Depends(verify_access_token),
    db: Session = Depends(get_tenant_db),
):
    """
    Insert a new company record using the ORM model and return its id.
    """
    try:
        # Create the company using the tenant database
        new_branch = BranchMst(
        branch_name = payload.branch_name,
        branch_prefix = payload.branch_prefix,
        co_id = payload.co_id,
        branch_address1 = payload.branch_address1,
        branch_address2 = payload.branch_address2,
        branch_zipcode = payload.branch_zipcode,
        country_id = payload.country_id,
        state_id = payload.state_id,
        gst_no = payload.gst_no,
        contact_no = payload.contact_no,
        contact_person = payload.contact_person,
        branch_email = payload.branch_email,
        active = payload.active,
        gst_verified = payload.gst_verified,
        updated_by = token_data.get("user_id"),
        )
        
        db.add(new_branch)
        db.flush()  # Get the ID without committing
        db.commit()
        
        return {"message": "Branch created successfully", "co_id": new_branch.branch_id}
    except HTTPException:
        raise
    except Exception as exc:
        print(f"Unexpected error in create_branch_data: {exc}")
        import traceback; traceback.print_exc()
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(exc)}")
    



@router.post("/edit_branch_data")
def edit_branch_data(
    payload: BranchCreate,
    token_data: dict = Depends(verify_access_token),
    db: Session = Depends(get_tenant_db),
):
    """
    Update an existing branch record using the ORM model.
    branch_id is expected to be included in the payload.
    """
    try:        # Extract branch_id from the payload
        branch_id = payload.branch_id
        if branch_id is None:
            raise HTTPException(status_code=400, detail="branch_id is required in the payload")
        
        # Convert branch_id to int if it's a string
        if isinstance(branch_id, str):
            try:
                branch_id = int(branch_id)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid branch_id format")        # Get the existing branch
        branch = db.query(BranchMst).filter(BranchMst.branch_id == branch_id).first()
        if branch is None:
            raise HTTPException(status_code=404, detail="Branch not found")

        # Update the company fields
        branch.branch_name = payload.branch_name
        branch.branch_prefix = payload.branch_prefix
        branch.co_id = payload.co_id
        branch.branch_address1 = payload.branch_address1
        branch.branch_address2 = payload.branch_address2
        branch.branch_zipcode = payload.branch_zipcode
        branch.country_id = payload.country_id
        branch.state_id = payload.state_id
        branch.gst_no = payload.gst_no
        branch.contact_no = payload.contact_no
        branch.contact_person = payload.contact_person
        branch.branch_email = payload.branch_email
        branch.active = payload.active
        branch.gst_verified = payload.gst_verified
        branch.updated_by = token_data.get("user_id")
        
        # # Only update active status if it's provided in the payload
        # if payload.active is not None:
        #     company.active = payload.active
        db.commit()
        
        return {"message": "Branch updated successfully", "branch_id": branch.branch_id}
    except HTTPException:
        raise
    except Exception as exc:
        print(f"Unexpected error in edit_branch_data: {exc}")
        import traceback; traceback.print_exc()
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(exc)}")


