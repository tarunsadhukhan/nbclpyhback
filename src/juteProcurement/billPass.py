"""
Jute Bill Pass API endpoints.
Bill Pass is a view of approved Jute Material Receipts (MRs) with invoice details.
This module provides endpoints for viewing and updating bill pass records from the jute_mr table.
"""

from fastapi import Depends, Request, HTTPException, APIRouter
from typing import Optional, List
from pydantic import BaseModel
import logging
from datetime import datetime
from src.common.utils import now_ist
from sqlalchemy.orm import Session
from sqlalchemy import text
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.juteProcurement.query import (
    get_jute_bill_pass_table_query,
    get_jute_bill_pass_table_count_query,
    get_jute_bill_pass_by_id_query,
    get_jute_mr_line_items_query,
)
from src.juteProcurement._excel_utils import (
    parse_iso_date,
    build_excel_response,
    enforce_row_cap,
)
from src.juteProcurement.totals import compute_jute_totals

logger = logging.getLogger(__name__)

router = APIRouter()


# =============================================================================
# CONSTANTS
# =============================================================================

STATUS_APPROVED = 3


# =============================================================================
# PYDANTIC MODELS
# =============================================================================

class BillPassUpdate(BaseModel):
    """Model for updating a bill pass record."""
    # Vendor Invoice Details
    invoice_no: Optional[str] = None
    invoice_date: Optional[str] = None  # YYYY-MM-DD
    invoice_amount: Optional[float] = None
    invoice_received_date: Optional[str] = None  # YYYY-MM-DD
    payment_due_date: Optional[str] = None  # YYYY-MM-DD
    
    # Financial amounts
    total_amount: Optional[float] = None
    claim_amount: Optional[float] = None
    roundoff: Optional[float] = None
    net_total: Optional[float] = None
    tds_amount: Optional[float] = None
    frieght_paid: Optional[float] = None
    
    # File uploads (paths)
    invoice_upload: Optional[str] = None
    challan_upload: Optional[str] = None
    
    # Remarks
    remarks: Optional[str] = None
    
    # Complete flag
    bill_pass_complete: Optional[int] = None


# =============================================================================
# ENDPOINTS
# =============================================================================

JUTE_BILL_PASS_DOWNLOAD_COLUMNS = [
    ("Bill Pass No", "bill_pass_num"),
    ("Bill Pass Date", "bill_pass_date"),
    ("MR No", "mr_num"),
    ("MR Date", "mr_date"),
    ("Branch", "branch_name"),
    ("Supplier", "supplier_name"),
    ("Party", "party_name"),
    ("Invoice No", "invoice_no"),
    ("Invoice Date", "invoice_date"),
    ("Invoice Amount", "invoice_amount"),
    ("Total Amount", "total_amount"),
    ("Claim Amount", "claim_amount"),
    ("Roundoff", "roundoff"),
    ("Net Total", "amount"),
    ("TDS Amount", "tds_amount"),
    ("Payment Due Date", "payment_due_date"),
    ("Status", "status"),
]


def _build_bill_pass_params(co_id: int, q_search: str, date_from, date_to):
    search_param = f"%{q_search}%" if q_search else None
    base = {
        "co_id": co_id,
        "date_from": date_from,
        "date_to": date_to,
    }
    if search_param:
        base["search"] = search_param
    return base


@router.get("/get_bill_pass_list")
def get_jute_bill_pass_list(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Get paginated list of jute bill pass records.
    Bill passes are approved MRs (status_id = 3) with bill_pass_no assigned.

    Query params:
    - co_id: Company ID (required)
    - page: Page number (default: 1)
    - limit: Records per page (default: 10)
    - search: Search term
    - from_date / to_date: Optional ISO dates (YYYY-MM-DD) bounding bill_pass_date
    """
    try:
        q_co_id = request.query_params.get("co_id")
        q_page = request.query_params.get("page", "1")
        q_limit = request.query_params.get("limit", "10")
        q_search = request.query_params.get("search", "").strip()
        q_from_date = (request.query_params.get("from_date") or "").strip()
        q_to_date = (request.query_params.get("to_date") or "").strip()

        if not q_co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        try:
            co_id = int(q_co_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid co_id")

        date_from = parse_iso_date(q_from_date, "from_date")
        date_to = parse_iso_date(q_to_date, "to_date")

        try:
            page = max(1, int(q_page))
            limit = max(1, min(100, int(q_limit)))
        except ValueError:
            page = 1
            limit = 10

        offset = (page - 1) * limit
        base_params = _build_bill_pass_params(co_id, q_search, date_from, date_to)

        count_query = get_jute_bill_pass_table_count_query(co_id, q_search)
        count_result = db.execute(count_query, base_params).fetchone()
        total = count_result[0] if count_result else 0

        data_query = get_jute_bill_pass_table_query(co_id, q_search)
        data_params = {**base_params, "limit": limit, "offset": offset}

        rows = db.execute(data_query, data_params).fetchall()
        data = [dict(r._mapping) for r in rows]

        return {
            "data": data,
            "total": total,
            "page": page,
            "page_size": limit,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching jute bill pass list: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/download_bill_pass_list")
def download_jute_bill_pass_list(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Download the Jute Bill Pass list as an .xlsx workbook with same filters."""
    try:
        q_co_id = request.query_params.get("co_id")
        q_search = request.query_params.get("search", "").strip()
        q_from_date = (request.query_params.get("from_date") or "").strip()
        q_to_date = (request.query_params.get("to_date") or "").strip()

        if not q_co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        try:
            co_id = int(q_co_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid co_id")

        date_from = parse_iso_date(q_from_date, "from_date")
        date_to = parse_iso_date(q_to_date, "to_date")

        base_params = _build_bill_pass_params(co_id, q_search, date_from, date_to)

        count_query = get_jute_bill_pass_table_count_query(co_id, q_search)
        count_result = db.execute(count_query, base_params).fetchone()
        total = int(count_result[0]) if count_result and count_result[0] else 0
        enforce_row_cap(total)

        rows = []
        if total > 0:
            data_query = get_jute_bill_pass_table_query(co_id, q_search)
            data_params = {**base_params, "limit": total, "offset": 0}
            result = db.execute(data_query, data_params).fetchall()
            rows = [dict(r._mapping) for r in result]

        return build_excel_response(
            rows=rows,
            columns=JUTE_BILL_PASS_DOWNLOAD_COLUMNS,
            sheet_title="Jute Bill Pass",
            filename_prefix="jute_bill_pass",
            from_date_str=q_from_date,
            to_date_str=q_to_date,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error downloading Jute Bill Pass list")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_bill_pass_by_id")
def get_jute_bill_pass_by_id(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Get a single jute bill pass (approved MR) by ID.
    
    Query params:
    - co_id: Company ID (required)
    - id: Bill Pass / MR ID (required)
    """
    try:
        # Get query parameters
        q_co_id = request.query_params.get("co_id")
        q_id = request.query_params.get("id")

        # Validate required params
        if not q_co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        if not q_id:
            raise HTTPException(status_code=400, detail="id is required")

        try:
            co_id = int(q_co_id)
            mr_id = int(q_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid co_id or id")

        # Get bill pass details
        query = get_jute_bill_pass_by_id_query()
        result = db.execute(query, {"co_id": co_id, "jute_mr_id": mr_id}).fetchone()

        if not result:
            raise HTTPException(status_code=404, detail="Bill pass not found")

        return dict(result._mapping)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching jute bill pass by ID: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_bill_pass_line_items")
def get_jute_bill_pass_line_items(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Get line items for a bill pass (approved MR).
    
    Query params:
    - co_id: Company ID (required)
    - id: Bill Pass / MR ID (required)
    """
    try:
        q_co_id = request.query_params.get("co_id")
        q_id = request.query_params.get("id")

        if not q_co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        if not q_id:
            raise HTTPException(status_code=400, detail="id is required")

        try:
            co_id = int(q_co_id)
            mr_id = int(q_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid co_id or id")

        query = get_jute_mr_line_items_query()
        rows = db.execute(query, {"mr_id": mr_id}).fetchall()
        data = [dict(r._mapping) for r in rows]

        return {"data": data}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching bill pass line items: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/update_bill_pass/{bill_pass_id}")
def update_jute_bill_pass(
    bill_pass_id: int,
    body: BillPassUpdate,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Update a bill pass record with invoice details and financial information.
    
    Path params:
    - bill_pass_id: The jute_mr_id of the bill pass to update
    
    Query params:
    - co_id: Company ID (required)
    """
    try:
        q_co_id = request.query_params.get("co_id")
        user_id = token_data.get("user_id")

        if not q_co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        if not user_id:
            raise HTTPException(status_code=401, detail="User not authenticated")

        try:
            co_id = int(q_co_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid co_id")

        # Verify bill pass exists and is approved (also fetch stored amounts so
        # roundoff/net_total can be recomputed server-side)
        verify_query = text("""
            SELECT jm.jute_mr_id, jm.status_id,
                   jm.total_amount, jm.claim_amount, jm.tds_amount
            FROM jute_mr jm
            INNER JOIN branch_mst bm ON bm.branch_id = jm.branch_id
            WHERE jm.jute_mr_id = :bill_pass_id
            AND bm.co_id = :co_id
            AND jm.status_id = 3
        """)
        result = db.execute(verify_query, {"bill_pass_id": bill_pass_id, "co_id": co_id}).fetchone()

        if not result:
            raise HTTPException(status_code=404, detail="Bill pass not found or not in approved status")

        stored = dict(result._mapping)

        now = now_ist()

        # Build dynamic update query
        update_fields = ["updated_by = :updated_by", "updated_date_time = :updated_date_time"]
        update_params = {
            "bill_pass_id": bill_pass_id,
            "updated_by": user_id,
            "updated_date_time": now,
        }

        # Add invoice fields if provided
        if body.invoice_no is not None:
            update_fields.append("invoice_no = :invoice_no")
            update_params["invoice_no"] = body.invoice_no

        if body.invoice_date is not None:
            update_fields.append("invoice_date = :invoice_date")
            update_params["invoice_date"] = body.invoice_date if body.invoice_date else None

        if body.invoice_amount is not None:
            update_fields.append("invoice_amount = :invoice_amount")
            update_params["invoice_amount"] = body.invoice_amount

        if body.invoice_received_date is not None:
            update_fields.append("invoice_received_date = :invoice_received_date")
            update_params["invoice_received_date"] = body.invoice_received_date if body.invoice_received_date else None

        if body.payment_due_date is not None:
            update_fields.append("payment_due_date = :payment_due_date")
            update_params["payment_due_date"] = body.payment_due_date if body.payment_due_date else None

        # Add financial fields if provided (round to 2 decimal places for currency precision)
        if body.total_amount is not None:
            update_fields.append("total_amount = :total_amount")
            update_params["total_amount"] = round(body.total_amount, 2)

        if body.claim_amount is not None:
            update_fields.append("claim_amount = :claim_amount")
            update_params["claim_amount"] = round(body.claim_amount, 2)

        if body.tds_amount is not None:
            update_fields.append("tds_amount = :tds_amount")
            update_params["tds_amount"] = round(body.tds_amount, 2)

        # Recompute roundoff/net_total server-side from the effective (client-
        # editable) total/claim/TDS amounts — client-sent net_total/roundoff are
        # NOT trusted, and net_total always deducts TDS (owner decision 2).
        recompute_needed = (
            body.total_amount is not None
            or body.claim_amount is not None
            or body.tds_amount is not None
            or body.net_total is not None
            or body.roundoff is not None
            or body.bill_pass_complete == 1
        )
        if recompute_needed:
            effective_total = (
                round(body.total_amount, 2) if body.total_amount is not None
                else float(stored.get("total_amount") or 0)
            )
            effective_claim = (
                round(body.claim_amount, 2) if body.claim_amount is not None
                else float(stored.get("claim_amount") or 0)
            )
            effective_tds = (
                round(body.tds_amount, 2) if body.tds_amount is not None
                else float(stored.get("tds_amount") or 0)
            )
            computed_roundoff, computed_net_total = compute_jute_totals(
                effective_total, effective_claim, effective_tds
            )
            update_fields.append("roundoff = :roundoff")
            update_params["roundoff"] = computed_roundoff
            update_fields.append("net_total = :net_total")
            update_params["net_total"] = computed_net_total

        if body.frieght_paid is not None:
            update_fields.append("frieght_paid = :frieght_paid")
            update_params["frieght_paid"] = round(body.frieght_paid, 2)

        # Add file upload fields if provided
        if body.invoice_upload is not None:
            update_fields.append("invoice_upload = :invoice_upload")
            update_params["invoice_upload"] = body.invoice_upload

        if body.challan_upload is not None:
            update_fields.append("challan_upload = :challan_upload")
            update_params["challan_upload"] = body.challan_upload

        # Add remarks if provided
        if body.remarks is not None:
            update_fields.append("remarks = :remarks")
            update_params["remarks"] = body.remarks

        # Add complete flag if provided
        if body.bill_pass_complete is not None:
            update_fields.append("bill_pass_complete = :bill_pass_complete")
            update_params["bill_pass_complete"] = body.bill_pass_complete

        update_query = text(f"""
            UPDATE jute_mr
            SET {', '.join(update_fields)}
            WHERE jute_mr_id = :bill_pass_id
        """)
        
        db.execute(update_query, update_params)
        db.commit()

        # Auto-post into accounting AFTER the business commit — posting can
        # never fail or roll back the bill-pass completion itself.
        accounting_posting = None
        if body.bill_pass_complete == 1:
            try:
                from src.accounting.posting_service import post_document
                accounting_posting = post_document(db, "JUTE_BILLPASS", bill_pass_id, user_id)
            except Exception as posting_error:  # defensive: post_document never raises
                logger.error(
                    f"Accounting auto-posting failed for jute MR {bill_pass_id}: {posting_error}"
                )
                accounting_posting = {
                    "status": "FAILED",
                    "acc_voucher_id": None,
                    "message": str(posting_error),
                }

        return {
            "success": True,
            "message": "Bill pass updated successfully",
            "bill_pass_id": bill_pass_id,
            "accounting_posting": accounting_posting,
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error updating bill pass")
        raise HTTPException(status_code=500, detail=str(e))
