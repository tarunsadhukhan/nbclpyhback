from fastapi import Depends, Request, HTTPException, APIRouter, Response, Cookie, logger, params
import os
from sqlalchemy.sql import text
from sqlalchemy import bindparam as sa_bindparam
from sqlalchemy.orm import Session
from sqlmodel import bindparam
from src.config.db import get_db_names, default_engine, get_tenant_db
from src.authorization.utils import  get_current_user_with_refresh
# from src.masters.schemas import MenuResponse
from src.masters.models import ItemGrpMst, ItemTypeMaster, ItemMst, ItemMake,DeptMst,SubDeptMst,MachineTypeMst,MachineMst
from src.masters.query import get_item_group, get_item_group_drodown, get_mechine_type_list, india_gst_applicable, get_item_table, check_item_group_code_and_name, get_dept_master
from src.masters.query import get_item_group_details_by_id, get_item_minmax_mapping, get_item, get_item_uom_mapping, get_uom_list, get_item_by_id
from src.masters.query import dept_master_create_setup as dept_master_create_setup_query,get_subdept_master
from src.masters.query import get_item_group_path, get_item_make
from src.masters.query import get_mechine_type_master_query, get_mechine_master
from src.masters.query import (
    get_branch_list,
    get_dept_list,get_mechine_master_view
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
        # Even in dev/bypass, resolve the real user from the token when a cookie is
        # present so updated_by gets populated. Never hard-fail in dev.
        if access_token:
            try:
                return get_current_user_with_refresh(request, response, access_token)
            except Exception:
                return {"user_id": None}
        return {"user_id": None}
    # Delegate to the real auth function which will raise HTTPException if token invalid
    return get_current_user_with_refresh(request, response, access_token)


@router.get("/mechine_type_master_table")
def mechine_type_master_table(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    page: int = 1,
    limit: int = 10,
    search: str = None,
):
    try:
        print("ENTER mechine_type_master_table", flush=True)
        search_param = f"%{search}%" if search else None
        query = get_mechine_type_master_query()
        params = {"search": search_param}
        rows = db.execute(query, params).fetchall()
        data = [dict(r._mapping) for r in rows]
        return {"data": data, "page": page, "limit": limit}
    except Exception as e:
        print("mechine_type_master_table error:", str(e), flush=True)
        raise HTTPException(status_code=500, detail=str(e))
# ...existing code...



@router.post("/mechine_type_master_create")
def mechine_type_master_create(
    payload: dict,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(optional_auth)
):
    """Create an ItemMake. Derive updated_by from token when available.

    Accepts payload keys: item_grp_id, item_make or item_make_name, (optional) co_id.
    """
    try:
        user_id = None
        if token_data and token_data.get("user_id"):
            user_id = token_data.get("user_id")
        else:
            user_id = payload.get("updated_by")


        new_mech_type_master = MachineTypeMst(
            machine_type_name=payload.get("mechine_type"),
            updated_by=int(user_id) if user_id and str(user_id).isdigit() else None,
            updated_date_time=now_ist(),
            active=payload.get("active", 1),
        )
        print(f"New MechineTypeMaster object: {new_mech_type_master}", flush=True)
        db.add(new_mech_type_master)
        db.commit()
        db.refresh(new_mech_type_master)
        response.status_code = 201
        return {"message": "Machine Type created successfully", "machine_type_id": new_mech_type_master.machine_type_id}
    except HTTPException:
        raise
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))




@router.get("/mechine_master_table")
def mechine_master_table(
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
        query = get_mechine_master(int(co_id), branch_ids=branch_ids_param or None)
        params = {"search": search_param}
        if branch_ids_param:
            params["branch_ids"] = branch_ids_param

        print("Executing query:", query, "params:", params, flush=True)
        result = db.execute(query, params).fetchall()
        data = [dict(row._mapping) for row in result]
        return {"data": data, "total": len(data)}
    except HTTPException:
        raise
    except Exception as e:
        print("dept_master_table error:", str(e), flush=True)
        raise HTTPException(status_code=500, detail=str(e))
# ...existing code...



@router.get("/mechine_master_create_setup")
def mechine_master_create_setup(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    search: str = None
):
    try:
        print("ENTER mechine_master_create_setup", flush=True)
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")

        # Accept either "branchids" (JSON array string) or "branch_id" (CSV/JSON)
        raw_branch_ids = request.query_params.get("branchids") or request.query_params.get("branch_id")
        branch_ids = parse_branch_ids(raw_branch_ids)
        print(f"co_id={co_id}, parsed branch_ids={branch_ids}", flush=True)

        search_param = f"%{search}%" if search else None

        # Branches (scoped to company + selected sidebar branches)
        q_br = get_branch_list(co_id=int(co_id), branch_ids=branch_ids)
        params_br = {"co_id": int(co_id)}
        if branch_ids:
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

        q_mech_type = get_mechine_type_list()
        params_mech_type = {}
        rows_mech_type = db.execute(q_mech_type, params_mech_type).fetchall()
        mechine_types = [dict(r._mapping) for r in rows_mech_type]


        return {"data": {"branchs": branchs, "departments": departments, "mechine_types": mechine_types}}
    except HTTPException:
        raise
    except Exception as e:
        print("mechine_master_create_setup error:", str(e), flush=True)
        raise HTTPException(status_code=500, detail=str(e))# ...existing code...
    

@router.post("/mechine_master_create")
def mechine_master_create(
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
        mechine_name = payload.get("mechine_name") 
        mechine_code = payload.get("mechine_code")
        dept_id = payload.get("dept_id")
        mechine_type_id = payload.get("mechine_type_id")
        mech_posting_code = payload.get("mechine_posting_code")
        remarks = payload.get("remarks")
        active = payload.get("active", 1)
        print(f"Creating department with branch_id={branch_id}, mechine_code={mechine_code}, mechine_name={mechine_name}", flush=True)  
        # Prefer user id from token_data; fall back to payload.updated_by if token missing
        user_id = None
        if token_data and token_data.get("user_id"):
            user_id = token_data.get("user_id")
        else:
            user_id = payload.get("updated_by")

        if not branch_id or not mechine_name or not mechine_code:
            raise HTTPException(status_code=400, detail="Branch ID, mechine code, and mechine name are required")

        new_mechine_master = MachineMst(
            dept_id=dept_id,
            machine_name=mechine_name,
            machine_type_id=mechine_type_id,
            updated_by=int(user_id) if user_id and str(user_id).isdigit() else None,
            remarks=remarks,
            updated_date_time=now_ist(),
            active=active,
            mech_posting_code=mech_posting_code,
            mech_code=mechine_code,
        )
        print(f"New MachineMst object: {new_mechine_master}", flush=True)
        db.add(new_mechine_master)
        db.commit()
        db.refresh(new_mechine_master)
        response.status_code = 201
        return {"message": "Machine created successfully", "mechine_master_id": new_mechine_master.machine_id}
    except HTTPException:
        raise
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))



@router.put("/mechine_master_edit/{machine_id}")
def mechine_master_edit(
    machine_id: int,
    payload: dict,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(optional_auth)
):
    """Update an existing machine master record."""
    try:
        machine = db.query(MachineMst).filter(MachineMst.machine_id == machine_id).first()
        if not machine:
            raise HTTPException(status_code=404, detail="Machine not found")

        user_id = None
        if token_data and token_data.get("user_id"):
            user_id = token_data.get("user_id")
        else:
            user_id = payload.get("updated_by")

        if payload.get("dept_id") is not None:
            machine.dept_id = payload["dept_id"]
        if payload.get("mechine_name") is not None:
            machine.machine_name = payload["mechine_name"]
        if payload.get("mechine_type_id") is not None:
            machine.machine_type_id = payload["mechine_type_id"]
        if payload.get("mechine_code") is not None:
            machine.mech_code = payload["mechine_code"]
        if "remarks" in payload:
            machine.remarks = payload["remarks"] if payload["remarks"] else None
        if "active" in payload:
            machine.active = payload["active"]
        if "mechine_posting_code" in payload:
            machine.mech_posting_code = int(payload["mechine_posting_code"]) if payload["mechine_posting_code"] not in (None, "") else None

        machine.updated_by = int(user_id) if user_id and str(user_id).isdigit() else machine.updated_by
        machine.updated_date_time = datetime.utcnow()

        db.commit()
        db.refresh(machine)
        return {"message": "Machine updated successfully", "mechine_master_id": machine.machine_id}
    except HTTPException:
        raise
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/mechine_master_by_id/{machine_id}")
def mechine_master_by_id(
    machine_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Get a single machine record by ID with setup data for editing."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        query = get_mechine_master_view(int(co_id), int(machine_id))
        params = {"search": None, "mechine_master_id": int(machine_id)}
        result = db.execute(query, params).fetchone()
        if not result:
            raise HTTPException(status_code=404, detail="Machine not found")

        data = dict(result._mapping)

        # Also fetch setup data for dropdowns
        raw_branch_ids = request.query_params.get("branchids") or request.query_params.get("branch_id")
        branch_ids = parse_branch_ids(raw_branch_ids)

        q_br = get_branch_list(branch_ids=branch_ids)
        params_br = {}
        if branch_ids:
            q_br = q_br.bindparams(sa_bindparam("branch_ids", expanding=True))
            params_br["branch_ids"] = branch_ids
        rows_br = db.execute(q_br, params_br).fetchall()
        branches = [dict(r._mapping) for r in rows_br]

        q_dept = get_dept_list(branch_ids=branch_ids)
        params_dept = {}
        if branch_ids:
            params_dept["branch_ids"] = branch_ids
        rows_dept = db.execute(q_dept, params_dept).fetchall()
        departments = [dict(r._mapping) for r in rows_dept]

        q_mech_type = get_mechine_type_list()
        rows_mech_type = db.execute(q_mech_type, {}).fetchall()
        mechine_types = [dict(r._mapping) for r in rows_mech_type]

        return {"data": data, "master": {"branchs": branches, "departments": departments, "mechine_types": mechine_types}}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



@router.get("/mechine_master_view")
def mechine_master_view(
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
        mechine_master_id = request.query_params.get("mechine_master_id")
        if not mechine_master_id:
            raise HTTPException(status_code=400, detail="Machine ID (mechine_master_id) is required")

        # Accept either "branchids" (JSON array string) or "branch_id" (comma-separated)
 
        search_param = f"%{search}%" if search else None

 
        print(f"Parsed branch params co_id={co_id}, branch_ids={mechine_master_id}, search={search_param}", flush=True)

        # Build query (pass parsed branch_ids list so query generator can include the IN clause)
        query = get_mechine_master_view(int(co_id),int(mechine_master_id))
        print("Built query:", query, flush=True)
        params = {"search": search_param}
        if mechine_master_id:
            # pass single integer with the name used in the SQL text
            params["mechine_master_id"] = int(mechine_master_id)

        print("Executing query:", query, "params:", params, flush=True)     
        result = db.execute(query, params).fetchall()
        data = [dict(row._mapping) for row in result]
        return {"data": data}
    except HTTPException:
        raise
    except Exception as e:
        print("mechine_master_table error:", str(e), flush=True)
        raise HTTPException(status_code=500, detail=str(e))
