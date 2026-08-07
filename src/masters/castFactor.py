from fastapi import Depends, Request, HTTPException, APIRouter, Response, Cookie
import os
from sqlalchemy.sql import text
from sqlalchemy.orm import Session
from src.config.db import get_db_names, default_engine, get_tenant_db
from src.authorization.utils import  get_current_user_with_refresh
# from src.masters.schemas import MenuResponse
from src.masters.models import CostFactorMst
from src.masters.query import  cost_factor_table, get_branch_list, get_dept_list_by_branch_id, cost_factor_table_by_id
from datetime import datetime
from src.common.utils import parse_json_body

router = APIRouter()


@router.get("/get_cost_factor_table")
def get_cost_factor(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    search: str = None
):
    try:
        co_id = request.query_params.get("co_id")
        # incoming param is 'branches' e.g. '1,2' per API client
        branches_param = request.query_params.get("branches") or request.query_params.get("branch_ids")
        if not co_id:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")
        # Prepare search parameter for LIKE if provided
        search_param = f"%{search}%" if search else None
        # parse branches CSV into list of ints
        branch_ids_list = None
        if branches_param:
            try:
                branch_ids_list = [int(x.strip()) for x in str(branches_param).split(",") if x.strip()]
            except Exception:
                raise HTTPException(status_code=400, detail="Invalid branches parameter")

        costfactorequery = cost_factor_table(branch_ids_list if branch_ids_list is not None else [])
        result = db.execute(costfactorequery, {"co_id": int(co_id), "search": search_param, "branch_ids": branch_ids_list}).fetchall()
        cost_factors = [dict(row._mapping) for row in result]
        branchquery = get_branch_list()
        branch_result = db.execute(branchquery).fetchall()
        branches = [dict(row._mapping) for row in branch_result]
        return {"data": cost_factors, "branches": branches}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/cost_factor_create")
def cost_factor_create(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        payload = parse_json_body(request)
        co_id_query = request.query_params.get("co_id")
        co_id = payload.get("co_id") if payload.get("co_id") is not None else co_id_query
        if co_id is None:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")

        # derive updated_by from token
        updated_by = None
        if token_data and token_data.get("user_id"):
            try:
                updated_by = int(token_data.get("user_id"))
            except Exception:
                updated_by = None

        try:
            branch_id = int(payload.get("branch_id")) if payload.get("branch_id") is not None else None
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid branch_id")

        if branch_id is None:
            raise HTTPException(status_code=400, detail="branch_id is required")

        cost_factor_name = payload.get("cost_factor_name")
        cost_factor_desc = payload.get("cost_factor_desc")
        try:
            dept_id = int(payload.get("dept_id")) if payload.get("dept_id") is not None else None
        except Exception:
            dept_id = None

        # duplicate check: same name within the same branch (case-insensitive)
        dup_sql = text("SELECT cost_factor_id FROM cost_factor_mst WHERE LOWER(cost_factor_name) = LOWER(:name) AND branch_id = :branch_id")
        dup = db.execute(dup_sql, {"name": (cost_factor_name or '').strip(), "branch_id": branch_id}).fetchone()
        if dup:
            raise HTTPException(status_code=409, detail="Cost factor with the same name already exists for this branch")

        from src.masters.models import CostFactorMst

        cf = CostFactorMst(
            branch_id=branch_id,
            cost_factor_name=cost_factor_name,
            cost_factor_desc=cost_factor_desc,
            dept_id=dept_id,
            updated_by=updated_by,
        )
        db.add(cf)
        db.commit()
        db.refresh(cf)

        return {"message": "Cost factor created", "cost_factor_id": getattr(cf, 'cost_factor_id', None)}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    

@router.get("/cost_factor_create_setup")
def get_cost_factor_setup(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    search: str = None
):
    try:
        co_id = request.query_params.get("co_id")
        # incoming param is 'branches' e.g. '1,2' per API client
        branches_param = request.query_params.get("branches") or request.query_params.get("branch_ids")
        if not co_id:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")
        # Prepare search parameter for LIKE if provided
        search_param = f"%{search}%" if search else None
        # parse branches CSV into list of ints
        branch_ids_list = None
        if branches_param:
            try:
                branch_ids_list = [int(x.strip()) for x in str(branches_param).split(",") if x.strip()]
            except Exception:
                raise HTTPException(status_code=400, detail="Invalid branches parameter")

        deptquery = get_dept_list_by_branch_id(branch_ids_list if branch_ids_list is not None else [])
        result = db.execute(deptquery, {"branch_ids": branch_ids_list}).fetchall()
        departments = [dict(row._mapping) for row in result]
        branchquery = get_branch_list()
        branch_result = db.execute(branchquery).fetchall()
        branches = [dict(row._mapping) for row in branch_result]
        return {"departments": departments, "branches": branches}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@router.get("/cost_factor_edit_setup")
def get_cost_factor_edit_setup(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    cost_factor_id: int = None
):
    try:
        # support param name variations: cost_factor_id or costfactorid
        q = request.query_params
        co_id = q.get("co_id")
        branches_param = q.get("branches") or q.get("branch_ids")
        # costfactor id may come as 'costfactorid' or 'cost_factor_id'
        cf_id_param = q.get("costfactorid") or q.get("cost_factor_id")
        if cost_factor_id is None and cf_id_param is not None:
            try:
                cost_factor_id = int(cf_id_param)
            except Exception:
                raise HTTPException(status_code=400, detail="Invalid costfactorid")

        if cost_factor_id is None:
            raise HTTPException(status_code=400, detail="Cost Factor ID is required")

        # parse branches CSV into list of ints (optional)
        branch_ids_list = None
        if branches_param:
            try:
                branch_ids_list = [int(x.strip()) for x in str(branches_param).split(",") if x.strip()]
            except Exception:
                raise HTTPException(status_code=400, detail="Invalid branches parameter")

        # fetch cost factor
        costfactor = cost_factor_table_by_id(cost_factor_id)
        result = db.execute(costfactor, {"cost_factor_id": cost_factor_id}).fetchone()

        if not result:
            raise HTTPException(status_code=404, detail="Cost Factor not found")

        # fetch departments for the provided branches (if any)
        departments = []
        if branch_ids_list is not None and len(branch_ids_list) > 0:
            deptquery = get_dept_list_by_branch_id(branch_ids_list)
            dept_result = db.execute(deptquery, {"branch_ids": branch_ids_list}).fetchall()
            departments = [dict(r._mapping) for r in dept_result]

        # fetch branches list for dropdown
        branchquery = get_branch_list()
        branch_result = db.execute(branchquery).fetchall()
        branches = [dict(row._mapping) for row in branch_result]

        return {"cost_factor": dict(result._mapping), "departments": departments, "branches": branches}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cost_factor_edit")
def cost_factor_edit(
        request: Request,
        response: Response,
        db: Session = Depends(get_tenant_db),
        token_data: dict = Depends(get_current_user_with_refresh),
    ):
        try:
            payload = parse_json_body(request)
            co_id_query = request.query_params.get("co_id")
            co_id = payload.get("co_id") if payload.get("co_id") is not None else co_id_query
            if co_id is None:
                raise HTTPException(status_code=400, detail="Company ID (co_id) is required")

            # parse and validate ids
            try:
                costfactorid = int(payload.get("costfactorid") if payload.get("costfactorid") is not None else payload.get("cost_factor_id"))
            except Exception:
                raise HTTPException(status_code=400, detail="Invalid costfactorid")

            try:
                branch_id = int(payload.get("branch_id")) if payload.get("branch_id") is not None and payload.get("branch_id") != "" else None
            except Exception:
                raise HTTPException(status_code=400, detail="Invalid branch_id")
            # branch_id is required for branch-scoped uniqueness
            if branch_id is None:
                raise HTTPException(status_code=400, detail="branch_id is required")
            cost_factor_name = payload.get("cost_factor_name")
            cost_factor_desc = payload.get("cost_factor_desc")
            # dept_id may be empty string
            dept_id_raw = payload.get("dept_id")
            try:
                dept_id = int(dept_id_raw) if dept_id_raw not in (None, "") else None
            except Exception:
                dept_id = None

            # derive updated_by
            updated_by = None
            if token_data and token_data.get("user_id"):
                try:
                    updated_by = int(token_data.get("user_id"))
                except Exception:
                    updated_by = None

            # check duplicate name for same branch (excluding current id)
            # case-insensitive duplicate check within the same branch (exclude current id)
            dup_sql = text("SELECT cost_factor_id FROM cost_factor_mst WHERE LOWER(cost_factor_name) = LOWER(:name) AND branch_id = :branch_id AND cost_factor_id != :id")
            dup = db.execute(dup_sql, {"name": (cost_factor_name or '').strip(), "branch_id": branch_id, "id": costfactorid}).fetchone()
            if dup:
                raise HTTPException(status_code=409, detail="Cost factor with the same name already exists for this branch")

            # perform update
            update_sql = text(
                """
                UPDATE cost_factor_mst
                SET cost_factor_name = :name,
                    cost_factor_desc = :desc,
                    branch_id = :branch_id,
                    dept_id = :dept_id,
                    updated_by = :updated_by,
                    updated_date_time = NOW()
                WHERE cost_factor_id = :id
                """
            )
            db.execute(update_sql, {"name": cost_factor_name, "desc": cost_factor_desc, "branch_id": branch_id, "dept_id": dept_id, "updated_by": updated_by, "id": costfactorid})
            db.commit()
            return {"message": "Cost factor updated"}
        except HTTPException:
            raise
        except Exception as e:
            db.rollback()
            raise HTTPException(status_code=500, detail=str(e))

