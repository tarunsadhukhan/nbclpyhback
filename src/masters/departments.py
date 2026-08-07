from fastapi import Depends, Request, HTTPException, APIRouter, Response, Cookie, logger, params
import os
from sqlalchemy.sql import text
from sqlalchemy import bindparam as sa_bindparam
from sqlalchemy.orm import Session
from sqlmodel import bindparam
from src.config.db import get_db_names, default_engine, get_tenant_db
from src.authorization.utils import  get_current_user_with_refresh
# from src.masters.schemas import MenuResponse
from src.masters.models import ItemGrpMst, ItemTypeMaster, ItemMst, ItemMake,DeptMst,SubDeptMst
from src.masters.query import get_item_group, get_item_group_drodown, india_gst_applicable, get_item_table, check_item_group_code_and_name, get_dept_master
from src.masters.query import get_item_group_details_by_id, get_item_minmax_mapping, get_item, get_item_uom_mapping, get_uom_list, get_item_by_id
from src.masters.query import dept_master_create_setup as dept_master_create_setup_query,get_subdept_master
from src.masters.query import get_item_group_path, get_item_make
from src.masters.query import (
    get_branch_list,
    get_dept_list,
    # ...existing imports...
)
from datetime import datetime
from src.common.utils import now_ist
import json
import re
from urllib.parse import unquote, urlparse, parse_qs
import ast
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


@router.get("/dept_master_table")
def dept_master_table(
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
        query = get_dept_master(int(co_id), branch_ids=branch_ids_param)
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
# ...existing code...



 
@router.get("/dept_master_validate_table")
def dept_master_validate_table(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    search: str = None
):
    try:
        # Get the item groups for the company specified in the request received
        print('request', request, response, flush=True)
        co_id = request.query_params.get("co_id")
        branch_ids = request.query_params.get("branch_id")
        search = request.query_params.get("search")
        if not co_id:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")

        # Accept either "branchids" (JSON array string) or "branch_id" (comma-separated)
        raw_branch_ids = branch_ids
        print("raw_branch_ids:", raw_branch_ids, flush=True)

  
   
    
        # Build query (pass parsed branch_ids list so query generator can include the IN clause)
        query = get_dept_master(int(co_id), int(branch_ids), search=search)
 
        print("Executing query:", query, "params:", params, flush=True)
        result = db.execute(query, params).fetchall()
        data = [dict(row._mapping) for row in result]
        return {"data": data}
    except HTTPException:
        raise
    except Exception as e:
        print("dept_master_table error:", str(e), flush=True)
        raise HTTPException(status_code=500, detail=str(e))
# ...existing code...

 

@router.get("/dept_master_create_setup")
def dept_master_create_setup(
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
        branch_ids_param = parse_branch_ids(raw_branch_ids)

        # Return branches filtered by co_id and optionally by sidebar-selected branch_ids
        q_br = get_branch_list(co_id=int(co_id), branch_ids=branch_ids_param)
        params_br: dict = {"co_id": int(co_id)}
        if branch_ids_param:
            params_br["branch_ids"] = branch_ids_param
        rows_br = db.execute(q_br, params_br).fetchall()
        data = [dict(row._mapping) for row in rows_br]
        return {"data": data}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
# ...existing code...

@router.get("/dept_master_create_setup2")
def dept_master_create_setup(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    search: str = None
):
    try:
        # Get the item groups for the company specified in the request received
        print('request', request, response)
        url = str(request.url)
        parsed_url = urlparse(url)
        raw_query = parsed_url.query              # e.g. "%5B1,2,3%5D="

        # Decode to text like "[1,2,3]" or "[4]"
        decoded = unquote(raw_query)              # e.g. "[1,2,3]="
        if decoded.endswith("="):                 # our case puts the array in the key
            decoded = decoded[:-1]                # -> "[1,2,3]"

        # Safely convert to Python list
        try:
            ids = ast.literal_eval(decoded)       # -> [1, 2, 3] or [4]
            if not isinstance(ids, list):
                ids = [ids]
        except Exception:
            ids = []  # fallback if someone sends junk

        print("IDs:", ids)
  
        search_param = f"%{search}%" if search else None

        raw_branch_ids = ids
        print("raw_branch_id******:", raw_branch_ids, flush=True)

        branch_ids_param = parse_branch_ids(raw_branch_ids)

        print("raw_branch_id======:", raw_branch_ids, flush=True)
        query = dept_master_create_setup_query(branch_ids=raw_branch_ids)
        params = {"search": search_param}
        print('dept query', query)
        result = db.execute(query, params).fetchall()
        print('dept query result', result)
        data = [dict(row._mapping) for row in result]
        return {"data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



@router.post("/dept_master_create")
def dept_master_create(
    payload: dict,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(optional_auth)
):
    """Create an ItemMake. Derive updated_by from token when available.

    Accepts payload keys: item_grp_id, item_make or item_make_name, (optional) co_id.
    """
    try:
        branch_id = payload.get("branch_id")
        # accept either `item_make` or `item_make_name` from clients
        dept_code = payload.get("dept_code") 
        dept_desc = payload.get("dept_name")

        print(f"Creating department with branch_id={branch_id}, dept_code={dept_code}, dept_desc={dept_desc}", flush=True)  
        # Prefer user id from token_data; fall back to payload.updated_by if token missing
        user_id = None
        if token_data and token_data.get("user_id"):
            user_id = token_data.get("user_id")
        else:
            user_id = payload.get("updated_by")

        if not branch_id or not dept_desc or not dept_code:
            raise HTTPException(status_code=400, detail="Branch ID, department code, and department name are required")

        new_dept_master = DeptMst(
            branch_id=branch_id,
            created_by=int(user_id) if user_id and str(user_id).isdigit() else None,
            dept_desc=dept_desc,
            dept_code=dept_code,
            order_id=1,
            created_date=now_ist()
        )
        print(f"New DeptMst object: {new_dept_master}", flush=True)
        db.add(new_dept_master)
        db.commit()
        db.refresh(new_dept_master)
        response.status_code = 201
        return {"message": "Department created successfully", "dept_master_id": new_dept_master.dept_id}
    except HTTPException:
        raise
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/subdept_master_table")
def dept_master_table(
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

#type SubDeptRow = { id?: string | number; subdept_code?: string; subdept_name?: string; dept_name?: string; branch_display?: string; active?: number | boolean | string; order_by?: number | string };

        # Accept either "branchids" (JSON array string) or "branch_id" (comma-separated)
        raw_branch_ids = request.query_params.get("branchids") or request.query_params.get("branch_id")
        print("raw_branch_ids:", raw_branch_ids, flush=True)

        search_param = f"%{search}%" if search else None

        branch_ids_param = parse_branch_ids(raw_branch_ids)

        print(f"Parsed branch params co_id={co_id}, branch_ids={branch_ids_param}, search={search_param}", flush=True)

        # Build query (pass parsed branch_ids list so query generator can include the IN clause)
        query = get_subdept_master(int(co_id), branch_ids=branch_ids_param)
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
        print("sub dept_master_table error:", str(e), flush=True)
        raise HTTPException(status_code=500, detail=str(e))



@router.post("/subdept_master_create")
def subdept_master_create(
    payload: dict,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(optional_auth)
):
    """Create an ItemMake. Derive updated_by from token when available.

    Accepts payload keys: item_grp_id, item_make or item_make_name, (optional) co_id.
    """
    try:
        branch_id = payload.get("branch_id")
        # accept either `item_make` or `item_make_name` from clients
        subdept_name = payload.get("subdept_name") 
        subdept_code = payload.get("subdept_code")
        dept_id = payload.get("dept_id")
        order_by = payload.get("order_by")
        print(f"Creating department with branch_id={branch_id}, subdept_code={subdept_code}, subdept_name={subdept_name}", flush=True)  
        # Prefer user id from token_data; fall back to payload.updated_by if token missing
        user_id = None
        if token_data and token_data.get("user_id"):
            user_id = token_data.get("user_id")
        else:
            user_id = payload.get("updated_by")

        if not branch_id or not subdept_name or not subdept_code:
            raise HTTPException(status_code=400, detail="Branch ID, subdepartment code, and subdepartment name are required")

        # order_by is mandatory and must be a valid positive integer
        if order_by is None or str(order_by).strip() == "":
            raise HTTPException(status_code=400, detail="Order By (order_by) is required")
        try:
            order_by_int = int(order_by)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Order By (order_by) must be a valid integer")
        if order_by_int < 0:
            raise HTTPException(status_code=400, detail="Order By (order_by) must be a non-negative integer")

        new_subdept_master = SubDeptMst(
            updated_by=int(user_id) if user_id and str(user_id).isdigit() else None,
            sub_dept_code=subdept_code,
            sub_dept_desc=subdept_name,
            dept_id=dept_id,
            updated_date_time=now_ist(),
            order_no=order_by_int,
        )
        print(f"New SubDeptMst object: {new_subdept_master}", flush=True)
        db.add(new_subdept_master)
        db.commit()
        db.refresh(new_subdept_master)
        response.status_code = 201
        return {"message": "Subdepartment created successfully", "subdept_master_id": new_subdept_master.sub_dept_id}
    except HTTPException:
        raise
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))




@router.get("/subdept_master_create_setup")
def subdept_master_create_setup(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    search: str = None
):
    try:
        print("ENTER subdept_master_create_setup", flush=True)
        # parse branch ids (accept CSV, JSON-array, repeated params)
        print('request', request, response)
        url = str(request.url)
        print("Request URL:", url, flush=True)
        parsed_url = urlparse(url)
        raw_query = parsed_url.query              # e.g. "%5B1,2,3%5D="
#        print("Raw query string:", raw_query, flush=True)
        # Decode to text like "[1,2,3]" or "[4]"
        decoded = unquote(raw_query)              # e.g. "[1,2,3]="
        if decoded.endswith("="):                 # our case puts the array in the key
            decoded = decoded[:-1]                # -> "[1,2,3]"

        # Safely convert to Python list
        try:
            ids = ast.literal_eval(decoded)       # -> [1, 2, 3] or [4]
            if not isinstance(ids, list):
                ids = [ids]
        except Exception:
            ids = []  # fallback if someone sends junk

        print("IDs:", ids)
        branch_ids = ids  # existing helper expected to return list[int] or None
        print("parsed branch_ids:", branch_ids, flush=True)

        search_param = f"%{search}%" if search else None

        # Branches
        q_br = get_branch_list(branch_ids=branch_ids)
        params_br = {}
        if branch_ids:
            q_br = q_br.bindparams(sa_bindparam("branch_ids", expanding=True))
            params_br["branch_ids"] = branch_ids
        rows_br = db.execute(q_br, params_br).fetchall()
        branchs = [dict(r._mapping) for r in rows_br]

        # Departments
        q_dept = get_dept_list( branch_ids=branch_ids)
        params_dept = {}
        if branch_ids:
            params_dept["branch_ids"] = branch_ids
        rows_dept = db.execute(q_dept, params_dept).fetchall()
        departments = [dict(r._mapping) for r in rows_dept]

        return {"data": {"branchs": branchs, "departments": departments}}
    except HTTPException:
        raise
    except Exception as e:
        print("subdept_master_create_setup error:", str(e), flush=True)
        raise HTTPException(status_code=500, detail=str(e))# ...existing code...
    
    
 
 
