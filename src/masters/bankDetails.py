"""
Bank Details Master API endpoints.

Provides CRUD operations for the bank_details_mst table.
Fields: bank_name, bank_branch, acc_no, ifsc_code, mcr_code, swift_code.
"""

from fastapi import Depends, Request, HTTPException, APIRouter, Response
from sqlalchemy.sql import text
from sqlalchemy.orm import Session
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.models.mst import BankDetailsMst
from datetime import datetime
from src.common.utils import parse_json_body

router = APIRouter()


# ─── SQL Queries ────────────────────────────────────────────────────


def get_bank_details_list_query():
    return text("""
        SELECT
            b.bank_detail_id,
            b.bank_name,
            b.bank_branch,
            RIGHT(b.acc_no, 5) AS acc_no_masked,
            b.ifsc_code,
            b.active,
            b.updated_by,
            b.updated_date_time
        FROM bank_details_mst b
        WHERE b.co_id = :co_id
          AND b.active = 1
          AND (:search IS NULL
               OR b.bank_name LIKE :search
               OR b.bank_branch LIKE :search
               OR b.ifsc_code LIKE :search)
        ORDER BY b.bank_detail_id DESC
    """)


def get_bank_detail_by_id_query():
    return text("""
        SELECT
            b.bank_detail_id,
            b.bank_name,
            b.bank_branch,
            b.acc_no,
            b.ifsc_code,
            b.mcr_code,
            b.swift_code,
            b.co_id,
            b.active,
            b.updated_by,
            b.updated_date_time
        FROM bank_details_mst b
        WHERE b.bank_detail_id = :bank_detail_id
          AND b.co_id = :co_id
    """)


# ─── Endpoints ──────────────────────────────────────────────────────


@router.get("/get_bank_details_table")
def get_bank_details_table(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Get paginated list of bank details with masked account numbers."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        search = request.query_params.get("search")
        search_param = f"%{search}%" if search else None

        page = int(request.query_params.get("page", 1))
        limit = int(request.query_params.get("limit", 10))

        query = get_bank_details_list_query()
        result = db.execute(query, {
            "co_id": int(co_id),
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


@router.get("/get_bank_detail_by_id/{bank_detail_id}")
def get_bank_detail_by_id(
    bank_detail_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Get a single bank detail record by ID (full account number)."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        query = get_bank_detail_by_id_query()
        result = db.execute(query, {
            "bank_detail_id": bank_detail_id,
            "co_id": int(co_id),
        }).fetchone()

        if not result:
            raise HTTPException(status_code=404, detail="Bank detail not found")

        return {"data": dict(result._mapping)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/bank_details_create_setup")
def bank_details_create_setup(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Get setup data for bank details creation form."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        return {"co_id": int(co_id)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/bank_details_create")
def bank_details_create(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Create a new bank detail record."""
    try:
        body = parse_json_body(request)

        co_id = body.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        bank_name = body.get("bank_name")
        if not bank_name:
            raise HTTPException(status_code=400, detail="Bank Name is required")

        bank_branch = body.get("bank_branch")
        if not bank_branch:
            raise HTTPException(status_code=400, detail="Bank Branch is required")

        acc_no = body.get("acc_no")
        if not acc_no:
            raise HTTPException(status_code=400, detail="Account Number is required")

        ifsc_code = body.get("ifsc_code")
        if not ifsc_code:
            raise HTTPException(status_code=400, detail="IFSC Code is required")

        # Check duplicate (same account + IFSC + company)
        dup_query = text("""
            SELECT COUNT(*) AS cnt FROM bank_details_mst
            WHERE acc_no = :acc_no AND ifsc_code = :ifsc_code AND co_id = :co_id
        """)
        dup_result = db.execute(dup_query, {
            "acc_no": acc_no,
            "ifsc_code": ifsc_code,
            "co_id": int(co_id),
        }).fetchone()

        if dup_result and dup_result.cnt > 0:
            raise HTTPException(
                status_code=400,
                detail="Bank account with this Account Number and IFSC already exists",
            )

        user_id = token_data.get("user_id") if token_data else None

        new_record = BankDetailsMst(
            bank_name=bank_name,
            bank_branch=bank_branch,
            acc_no=acc_no,
            ifsc_code=ifsc_code,
            mcr_code=body.get("mcr_code") or None,
            swift_code=body.get("swift_code") or None,
            co_id=int(co_id),
            updated_by=int(user_id) if user_id else None,
            updated_date_time=datetime.now(),
        )
        db.add(new_record)
        db.commit()
        db.refresh(new_record)

        return {
            "message": "Bank details created successfully",
            "bank_detail_id": new_record.bank_detail_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/bank_details_edit/{bank_detail_id}")
def bank_details_edit(
    bank_detail_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Update an existing bank detail record."""
    try:
        body = parse_json_body(request)

        bank_name = body.get("bank_name")
        if not bank_name:
            raise HTTPException(status_code=400, detail="Bank Name is required")

        bank_branch = body.get("bank_branch")
        if not bank_branch:
            raise HTTPException(status_code=400, detail="Bank Branch is required")

        acc_no = body.get("acc_no")
        if not acc_no:
            raise HTTPException(status_code=400, detail="Account Number is required")

        ifsc_code = body.get("ifsc_code")
        if not ifsc_code:
            raise HTTPException(status_code=400, detail="IFSC Code is required")

        existing = db.query(BankDetailsMst).filter(
            BankDetailsMst.bank_detail_id == bank_detail_id,
        ).first()

        if not existing:
            raise HTTPException(status_code=404, detail="Bank detail not found")

        # Check duplicate (excluding current record)
        dup_query = text("""
            SELECT COUNT(*) AS cnt FROM bank_details_mst
            WHERE acc_no = :acc_no AND ifsc_code = :ifsc_code
              AND co_id = :co_id AND bank_detail_id != :bank_detail_id
        """)
        dup_result = db.execute(dup_query, {
            "acc_no": acc_no,
            "ifsc_code": ifsc_code,
            "co_id": existing.co_id,
            "bank_detail_id": bank_detail_id,
        }).fetchone()

        if dup_result and dup_result.cnt > 0:
            raise HTTPException(
                status_code=400,
                detail="Bank account with this Account Number and IFSC already exists",
            )

        user_id = token_data.get("user_id") if token_data else None

        existing.bank_name = bank_name
        existing.bank_branch = bank_branch
        existing.acc_no = acc_no
        existing.ifsc_code = ifsc_code
        existing.mcr_code = body.get("mcr_code") or None
        existing.swift_code = body.get("swift_code") or None
        existing.updated_by = int(user_id) if user_id else existing.updated_by
        existing.updated_date_time = datetime.now()

        db.commit()

        return {"message": "Bank details updated successfully", "bank_detail_id": bank_detail_id}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
