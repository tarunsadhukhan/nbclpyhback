from fastapi import Depends, Request, HTTPException, APIRouter, Response, Cookie, logger, params
import os
from sqlalchemy.sql import text
from sqlalchemy import bindparam as sa_bindparam
from sqlalchemy.orm import Session
from sqlmodel import Column, bindparam
from src.config.db import get_db_names, default_engine, get_tenant_db
from src.authorization.utils import  get_current_user_with_refresh
# from src.masters.schemas import MenuResponse
from src.masters.models import ItemGrpMst, ItemTypeMaster, ItemMst, ItemMake,DeptMst,SubDeptMst,MachineTypeMst,MachineMst,ProjectMst
from src.masters.query import get_item_group, get_item_group_drodown, get_mechine_type_list, get_proj_party_list, india_gst_applicable, get_item_table, check_item_group_code_and_name, get_dept_master
from src.masters.query import get_item_group_details_by_id, get_item_minmax_mapping, get_item, get_item_uom_mapping, get_uom_list, get_item_by_id
from src.masters.query import dept_master_create_setup as dept_master_create_setup_query,get_subdept_master
from src.masters.query import get_item_group_path, get_item_make
from src.masters.query import get_mechine_type_master_query, get_mechine_master
from src.masters.query import (
    get_branch_list,
    get_dept_list,get_project_master
    # ...existing imports...
)
from datetime import datetime
from src.common.utils import now_ist
import json
import re
router = APIRouter()


def parse_branch_ids(raw_branch_ids):
    """Return a list of ints from input which can be:
    - a JSON array string like "[1,2]"
    - a CSV string like "1,2"
    - a single numeric string like "1"
    - already a list of ints
    Non-numeric characters (brackets/spaces) are ignored safely.
    Returns None if input is falsy.
    """
    if not raw_branch_ids:
        return None
    # if it's already a list, coerce to ints
    if isinstance(raw_branch_ids, list):
        try:
            return [int(x) for x in raw_branch_ids]
        except Exception:
            return None

    # try JSON first (handles '[1,2]' and '1' etc.)
    try:
        parsed = json.loads(raw_branch_ids)
        if isinstance(parsed, list):
            return [int(x) for x in parsed]
        return [int(parsed)]
    except Exception:
        pass

    # fallback: strip surrounding brackets and split by comma
    cleaned = re.sub(r"^[\[\(]+|[\]\)]+$", "", str(raw_branch_ids)).strip()
    if cleaned == "":
        return None
    parts = [p.strip() for p in cleaned.split(",") if p.strip() != ""]
    out = []
    for p in parts:
        # extract leading integer token from each part
        m = re.search(r"-?\d+", p)
        if m:
            out.append(int(m.group(0)))
    return out if out else None


def optional_auth(request: Request, response: Response, access_token: str = Cookie(None, alias="access_token")) -> dict:
    """Dev-toggle auth dependency.
    If BYPASS_AUTH=1 or ENV=development, return a dummy user dict. Otherwise delegate to the real auth helper.
    """
    BYPASS = os.getenv("BYPASS_AUTH", "0")
    ENV = os.getenv("ENV", "development")
    if BYPASS == "1" or ENV == "development":
        return {"user_id": None}
    # Delegate to the real auth function which will raise HTTPException if token invalid
    return get_current_user_with_refresh(request, response, access_token)


@router.get("/project_master_table")
def project_master_table(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    search: str = None
):
    try:
        # Get the item groups for the company specified in the request received
#        print('request', request, response, flush=True)
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")

        # Accept either "branchids" (JSON array string) or "branch_id" (comma-separated)
        raw_branch_ids = request.query_params.get("branchids") or request.query_params.get("branch_id")
        print("raw_branch_ids:", raw_branch_ids, flush=True)

        search_param = f"%{search}%" if search else None

        branch_ids_param = parse_branch_ids(raw_branch_ids)

        print(f"Parsed branch params co_id={co_id}, branch_ids={branch_ids_param}, search={search_param}", flush=True)

        # Build query (pass parsed branch_ids list so query generator can include the IN clause)
        query = get_project_master(int(co_id), branch_ids=branch_ids_param)
        if branch_ids_param is not None:
            params = {"search": search_param, "branch_ids": branch_ids_param}
        else:
            params = {"search": search_param}

        print("Executing query:", query, "params:", params, flush=True)
        result = db.execute(query, params).fetchall()
        data = [dict(row._mapping) for row in result]
        return {"data": data}
    except HTTPException:
        raise
    except Exception as e:
        print("dept_master_table error:", str(e), flush=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/project_master_create_setup")
def project_master_create_setup(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    search: str = None
):
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        # Parse branch_id from query param (supports JSON array "[1,2]", CSV "1,2", or single "1")
        raw_branch_ids = request.query_params.get("branch_id") or request.query_params.get("branchids")
        branch_ids = parse_branch_ids(raw_branch_ids)

        # Branches — filter by co_id and optionally by sidebar-selected branch_ids
        # get_branch_list already applies bindparams(expanding=True) when branch_ids is provided
        q_br = get_branch_list(co_id=int(co_id), branch_ids=branch_ids)
        params_br: dict = {"co_id": int(co_id)}
        if branch_ids:
            params_br["branch_ids"] = branch_ids
        rows_br = db.execute(q_br, params_br).fetchall()
        branchs = [dict(r._mapping) for r in rows_br]

        # Departments — filtered by the same branch scope
        q_dept = get_dept_list(branch_ids=branch_ids)
        params_dept: dict = {}
        if branch_ids:
            params_dept["branch_ids"] = branch_ids
        rows_dept = db.execute(q_dept, params_dept).fetchall()
        departments = [dict(r._mapping) for r in rows_dept]

        # Parties
        q_prj_party = get_proj_party_list(co_id=co_id)
        params_prj_party: dict = {}
        if co_id:
            params_prj_party["co_id"] = co_id
        rows_prj_party = db.execute(q_prj_party, params_prj_party).fetchall()
        parties = [dict(r._mapping) for r in rows_prj_party]

        return {"data": {"branchs": branchs, "departments": departments, "parties": parties}}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
  
  
@router.post("/project_master_create")
def project_master_create(
    payload: dict,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(optional_auth)
):
    """Create a Project. Derive updated_by from token when available.

    Accepts payload keys: item_grp_id, item_make or item_make_name, (optional) co_id.
    """
    try:
 
        prj_desc = payload.get("prj_desc")
        prj_end_dt = payload.get("prj_end_dt")
        prj_name = payload.get("prj_name")
        prj_start_dt = payload.get("prj_start_dt")
        status_id = payload.get("status_id")
        active = payload.get("active", 1)
        branch_id = payload.get("branch_id")
        updated_by = payload.get("updated_by")
        updated_date_time = payload.get("updated_date_time")
        party_id = payload.get("party_id")
        dept_id = payload.get("dept_id")
        print(f"Creating department with branch_id={branch_id}", flush=True)
        # Prefer user id from token_data; fall back to payload.updated_by if token missing
        user_id = None
        if token_data and token_data.get("user_id"):
            user_id = token_data.get("user_id")
        else:
            user_id = payload.get("updated_by")

        if not branch_id or not prj_name :
            raise HTTPException(status_code=400, detail="Branch ID and project name are required")

        new_project_master = ProjectMst(
            prj_desc=prj_desc,
            prj_end_dt=prj_end_dt,
            prj_name=prj_name,
            prj_start_dt=prj_start_dt,
            status_id=status_id,
            active=active,
            branch_id=branch_id,
            updated_by=user_id,
            updated_date_time=now_ist(),
            party_id=party_id,
            dept_id=dept_id
        )
        print(f"New ProjectMst object: {new_project_master}", flush=True)
        db.add(new_project_master)
        db.commit()
        db.refresh(new_project_master)
        response.status_code = 201
        return {"message": "Project created successfully", "project_master_id": new_project_master.project_id}
    except HTTPException:
        raise
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))
