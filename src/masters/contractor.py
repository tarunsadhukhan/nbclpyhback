"""
Contractor Master API endpoints.

Provides CRUD operations for the contractor_master table.
Fields: contractor_name, address, bank details, PF/ESI codes, registration dates, branch.
"""

from fastapi import Depends, Request, HTTPException, APIRouter, Response
from sqlalchemy.sql import text
from sqlalchemy.orm import Session
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.models.mst import ContractorMst
from datetime import datetime
from src.common.utils import parse_json_body

router = APIRouter()


# ─── SQL Queries ────────────────────────────────────────────────────


def get_contractor_list_query(branch_ids=None):
    branch_filter = ""
    if branch_ids:
        placeholders = ",".join(str(int(b)) for b in branch_ids)
        branch_filter = f"AND c.branch_id IN ({placeholders})"
    return text(f"""
        SELECT
            c.cont_id,
            c.contractor_name,
            c.phone_no,
            c.email_id,
            c.pan_no,
            c.aadhar_no,
            c.pf_code,
            c.esi_code,
            c.address_1,
            c.address_2,
            c.address_3,
            c.bank_acc_no,
            c.bank_name,
            c.ifsc_code,
            c.branch_id,
            c.date_of_registration,
            c.date_of_registration_mill,
            c.updated_by,
            c.updated_date_time,
            b.branch_name
        FROM contractor_mst c
        LEFT JOIN branch_mst b ON b.branch_id = c.branch_id
        WHERE (:search IS NULL
               OR c.contractor_name LIKE :search
               OR c.phone_no LIKE :search
               OR c.email_id LIKE :search
               OR c.pan_no LIKE :search)
          {branch_filter}
        ORDER BY c.cont_id DESC
    """)


def get_contractor_by_id_query():
    return text("""
        SELECT
            c.cont_id,
            c.contractor_name,
            c.phone_no,
            c.email_id,
            c.pan_no,
            c.aadhar_no,
            c.pf_code,
            c.esi_code,
            c.address_1,
            c.address_2,
            c.address_3,
            c.bank_acc_no,
            c.bank_name,
            c.ifsc_code,
            c.branch_id,
            c.date_of_registration,
            c.date_of_registration_mill,
            c.updated_by,
            c.updated_date_time,
            b.branch_name
        FROM contractor_mst c
        LEFT JOIN branch_mst b ON b.branch_id = c.branch_id
        WHERE c.cont_id = :cont_id
    """)


# ─── Endpoints ──────────────────────────────────────────────────────


@router.get("/get_contractor_table")
def get_contractor_table(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Get paginated list of contractors."""
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

        query = get_contractor_list_query(branch_ids=branch_ids)
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


@router.get("/get_contractor_by_id/{cont_id}")
def get_contractor_by_id(
    cont_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Get a single contractor record by ID."""
    try:
        query = get_contractor_by_id_query()
        result = db.execute(query, {
            "cont_id": cont_id,
        }).fetchone()

        if not result:
            raise HTTPException(status_code=404, detail="Contractor not found")

        return {"data": dict(result._mapping)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/contractor_create_setup")
def contractor_create_setup(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Get dropdown options needed for contractor creation (branches)."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        branch_query = text("""
            SELECT branch_id, branch_name FROM branch_mst
            WHERE co_id = :co_id AND active = 1
            ORDER BY branch_name
        """)
        branches = db.execute(branch_query, {"co_id": int(co_id)}).fetchall()

        return {
            "branches": [dict(r._mapping) for r in branches],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/contractor_create")
def contractor_create(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Create a new contractor record."""
    try:
        body = parse_json_body(request)

        contractor_name = body.get("contractor_name")
        if not contractor_name:
            raise HTTPException(status_code=400, detail="Contractor name is required")

        # Check duplicate name
        dup_query = text("""
            SELECT COUNT(*) AS cnt FROM contractor_mst
            WHERE contractor_name = :contractor_name
        """)
        dup_result = db.execute(dup_query, {
            "contractor_name": contractor_name,
        }).fetchone()

        if dup_result and dup_result.cnt > 0:
            raise HTTPException(
                status_code=400,
                detail="Contractor with this name already exists",
            )

        user_id = token_data.get("user_id") if token_data else None

        new_contractor = ContractorMst(
            contractor_name=contractor_name,
            address_1=body.get("address_1"),
            address_2=body.get("address_2"),
            address_3=body.get("address_3"),
            bank_acc_no=body.get("bank_acc_no"),
            bank_name=body.get("bank_name"),
            ifsc_code=body.get("ifsc_code"),
            branch_id=int(body["branch_id"]) if body.get("branch_id") else None,
            email_id=body.get("email_id"),
            esi_code=body.get("esi_code"),
            aadhar_no=body.get("aadhar_no"),
            pan_no=body.get("pan_no"),
            pf_code=body.get("pf_code"),
            phone_no=body.get("phone_no"),
            date_of_registration=body.get("date_of_registration"),
            date_of_registration_mill=body.get("date_of_registration_mill"),
            updated_by=user_id,
            updated_date_time=datetime.now(),
        )
        db.add(new_contractor)
        db.commit()
        db.refresh(new_contractor)

        return {
            "message": "Contractor created successfully",
            "cont_id": new_contractor.cont_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/contractor_edit/{cont_id}")
def contractor_edit(
    cont_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Update an existing contractor record."""
    try:
        body = parse_json_body(request)

        contractor_name = body.get("contractor_name")
        if not contractor_name:
            raise HTTPException(status_code=400, detail="Contractor name is required")

        existing = db.query(ContractorMst).filter(
            ContractorMst.cont_id == cont_id,
        ).first()

        if not existing:
            raise HTTPException(status_code=404, detail="Contractor not found")

        # Check duplicate name (excluding current record)
        dup_query = text("""
            SELECT COUNT(*) AS cnt FROM contractor_mst
            WHERE contractor_name = :contractor_name AND cont_id != :cont_id
        """)
        dup_result = db.execute(dup_query, {
            "contractor_name": contractor_name,
            "cont_id": cont_id,
        }).fetchone()

        if dup_result and dup_result.cnt > 0:
            raise HTTPException(
                status_code=400,
                detail="Contractor with this name already exists",
            )

        user_id = token_data.get("user_id") if token_data else None

        existing.contractor_name = contractor_name
        existing.address_1 = body.get("address_1", existing.address_1)
        existing.address_2 = body.get("address_2", existing.address_2)
        existing.address_3 = body.get("address_3", existing.address_3)
        existing.bank_acc_no = body.get("bank_acc_no", existing.bank_acc_no)
        existing.bank_name = body.get("bank_name", existing.bank_name)
        existing.ifsc_code = body.get("ifsc_code", existing.ifsc_code)
        existing.branch_id = int(body["branch_id"]) if body.get("branch_id") else existing.branch_id
        existing.email_id = body.get("email_id", existing.email_id)
        existing.esi_code = body.get("esi_code", existing.esi_code)
        existing.aadhar_no = body.get("aadhar_no", existing.aadhar_no)
        existing.pan_no = body.get("pan_no", existing.pan_no)
        existing.pf_code = body.get("pf_code", existing.pf_code)
        existing.phone_no = body.get("phone_no", existing.phone_no)
        existing.date_of_registration = body.get("date_of_registration", existing.date_of_registration)
        existing.date_of_registration_mill = body.get("date_of_registration_mill", existing.date_of_registration_mill)
        existing.updated_by = user_id if user_id else existing.updated_by
        existing.updated_date_time = datetime.now()

        db.commit()

        return {"message": "Contractor updated successfully", "cont_id": cont_id}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
