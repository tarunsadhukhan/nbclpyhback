"""
Designation Master API endpoints.

Provides CRUD operations for the designation_mst table.
Migrated from vowsls.designation with branch_id replacing company_id.
"""

from fastapi import Depends, Request, HTTPException, APIRouter, Response
from sqlalchemy.sql import text
from sqlalchemy.orm import Session
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.models.mst import DesignationMst
from datetime import datetime
from src.common.utils import parse_json_body

router = APIRouter()


# ─── SQL Queries ────────────────────────────────────────────────────


def get_designation_list_query(branch_ids=None):
    branch_filter = ""
    if branch_ids:
        placeholders = ",".join(str(int(b)) for b in branch_ids)
        branch_filter = f"AND d.branch_id IN ({placeholders})"
    return text(f"""
        SELECT
            d.designation_id,
            d.branch_id,
            d.dept_id,
            d.desig,
            d.norms,
            d.time_piece,
            d.direct_indirect,
            d.on_machine,
            d.machine_type,
            d.no_of_machines,
            d.cost_code,
            d.cost_description,
            d.piece_rate_type,
            d.active,
            d.updated_by,
            d.updated_date_time,
            dp.dept_desc AS dept_name,
            b.branch_name
        FROM designation_mst d
        LEFT JOIN dept_mst dp ON dp.dept_id = d.dept_id
        LEFT JOIN branch_mst b ON b.branch_id = d.branch_id
        WHERE d.active = 1
          {branch_filter}
          AND (:search IS NULL OR d.desig LIKE :search
               OR dp.dept_desc LIKE :search
               OR d.norms LIKE :search)
        ORDER BY d.designation_id DESC
    """)


def get_designation_by_id_query():
    return text("""
        SELECT
            d.designation_id,
            d.branch_id,
            d.dept_id,
            d.desig,
            d.norms,
            d.time_piece,
            d.direct_indirect,
            d.on_machine,
            d.machine_type,
            d.no_of_machines,
            d.cost_code,
            d.cost_description,
            d.piece_rate_type,
            d.active,
            d.updated_by,
            d.updated_date_time,
            dp.dept_desc AS dept_name,
            b.branch_name
        FROM designation_mst d
        LEFT JOIN dept_mst dp ON dp.dept_id = d.dept_id
        LEFT JOIN branch_mst b ON b.branch_id = d.branch_id
        WHERE d.designation_id = :designation_id
    """)


# ─── Endpoints ──────────────────────────────────────────────────────


@router.get("/get_designation_table")
def get_designation_table(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Get paginated list of designations."""
    try:
        search = request.query_params.get("search")
        search_param = f"%{search}%" if search else None

        raw_branch_ids = request.query_params.get("branch_id")
        branch_ids = None
        if raw_branch_ids:
            try:
                branch_ids = [int(b) for b in raw_branch_ids.split(",") if b.strip()]
            except (ValueError, TypeError):
                branch_ids = None

        page = int(request.query_params.get("page", 1))
        limit = int(request.query_params.get("limit", 10))

        query = get_designation_list_query(branch_ids=branch_ids)
        result = db.execute(query, {
            "search": search_param,
        }).fetchall()

        all_data = [dict(row._mapping) for row in result]
        total = len(all_data)
        start_idx = (page - 1) * limit
        paginated_data = all_data[start_idx:start_idx + limit]

        return {
            "data": paginated_data,
            "total": total,
            "page": page,
            "limit": limit,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_designation_by_id/{designation_id}")
def get_designation_by_id(
    designation_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Get a single designation record by ID."""
    try:
        query = get_designation_by_id_query()
        result = db.execute(query, {
            "designation_id": designation_id,
        }).fetchone()

        if not result:
            raise HTTPException(status_code=404, detail="Designation not found")

        return {"data": dict(result._mapping)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/designation_create_setup")
def designation_create_setup(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Get dropdown options needed for designation creation (departments, branches)."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        dept_query = text("""
            SELECT dept_id, dept_desc
            FROM dept_mst
            WHERE (:branch_id IS NULL OR branch_id = :branch_id)
            ORDER BY dept_desc
        """)
        branch_query = text("""
            SELECT branch_id, branch_name FROM branch_mst
            WHERE co_id = :co_id AND active = 1
            ORDER BY branch_name
        """)
        machine_type_query = text("""
            SELECT machine_type_id, machine_type_name FROM machine_type_mst
            WHERE active = 1
            ORDER BY machine_type_name
        """)

        branch_id = request.query_params.get("branch_id")

        depts = db.execute(dept_query, {"branch_id": int(branch_id) if branch_id else None}).fetchall()
        branches = db.execute(branch_query, {"co_id": int(co_id)}).fetchall()
        machine_types = db.execute(machine_type_query).fetchall()

        return {
            "departments": [dict(r._mapping) for r in depts],
            "branches": [dict(r._mapping) for r in branches],
            "machine_types": [dict(r._mapping) for r in machine_types],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/designation_create")
def designation_create(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Create a new designation record."""
    try:
        body = parse_json_body(request)

        desig = body.get("desig")
        if not desig:
            raise HTTPException(status_code=400, detail="Designation name (desig) is required")

        dept_id = body.get("dept_id")
        if not dept_id:
            raise HTTPException(status_code=400, detail="Department (dept_id) is required")

        # Check duplicate name within same department
        dup_query = text("""
            SELECT COUNT(*) AS cnt FROM designation_mst
            WHERE desig = :desig AND dept_id = :dept_id AND active = 1
        """)
        dup_result = db.execute(dup_query, {
            "desig": desig,
            "dept_id": int(dept_id),
        }).fetchone()

        if dup_result and dup_result.cnt > 0:
            raise HTTPException(
                status_code=400,
                detail="Designation with this name already exists in the selected department",
            )

        user_id = token_data.get("user_id") if token_data else None

        new_desig = DesignationMst(
            branch_id=int(body["branch_id"]) if body.get("branch_id") else None,
            dept_id=int(dept_id),
            desig=desig,
            norms=body.get("norms"),
            time_piece=body.get("time_piece"),
            direct_indirect=body.get("direct_indirect"),
            on_machine=body.get("on_machine"),
            machine_type=body.get("machine_type"),
            no_of_machines=body.get("no_of_machines"),
            cost_code=body.get("cost_code"),
            cost_description=body.get("cost_description"),
            piece_rate_type=body.get("piece_rate_type"),
            active=1,
            updated_by=user_id,
            updated_date_time=datetime.now(),
        )
        db.add(new_desig)
        db.commit()
        db.refresh(new_desig)

        return {
            "message": "Designation created successfully",
            "designation_id": new_desig.designation_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/designation_edit/{designation_id}")
def designation_edit(
    designation_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Update an existing designation record."""
    try:
        body = parse_json_body(request)

        desig = body.get("desig")
        if not desig:
            raise HTTPException(status_code=400, detail="Designation name (desig) is required")

        dept_id = body.get("dept_id")
        if not dept_id:
            raise HTTPException(status_code=400, detail="Department (dept_id) is required")

        existing = db.query(DesignationMst).filter(
            DesignationMst.designation_id == designation_id,
        ).first()

        if not existing:
            raise HTTPException(status_code=404, detail="Designation not found")

        # Check duplicate name (excluding current record)
        dup_query = text("""
            SELECT COUNT(*) AS cnt FROM designation_mst
            WHERE desig = :desig AND dept_id = :dept_id
              AND active = 1 AND designation_id != :designation_id
        """)
        dup_result = db.execute(dup_query, {
            "desig": desig,
            "dept_id": int(dept_id),
            "designation_id": designation_id,
        }).fetchone()

        if dup_result and dup_result.cnt > 0:
            raise HTTPException(
                status_code=400,
                detail="Designation with this name already exists in the selected department",
            )

        user_id = token_data.get("user_id") if token_data else None

        existing.desig = desig
        existing.dept_id = int(dept_id)
        existing.branch_id = int(body["branch_id"]) if body.get("branch_id") else existing.branch_id
        existing.norms = body.get("norms", existing.norms)
        existing.time_piece = body.get("time_piece", existing.time_piece)
        existing.direct_indirect = body.get("direct_indirect", existing.direct_indirect)
        existing.on_machine = body.get("on_machine", existing.on_machine)
        existing.machine_type = body.get("machine_type", existing.machine_type)
        existing.no_of_machines = body.get("no_of_machines", existing.no_of_machines)
        existing.cost_code = body.get("cost_code", existing.cost_code)
        existing.cost_description = body.get("cost_description", existing.cost_description)
        existing.piece_rate_type = body.get("piece_rate_type", existing.piece_rate_type)
        existing.updated_by = user_id
        existing.updated_date_time = datetime.now()

        db.commit()

        return {"message": "Designation updated successfully", "designation_id": designation_id}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
