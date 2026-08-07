"""
Bill Pass API endpoints.
Consolidates SR and DRCR Notes for final payment processing.
Shows net payable amount after all adjustments.

Bill Pass appears automatically when SR is approved.
Editable (invoice details) until marked complete (billpass_status = 1).
"""
import logging
from datetime import date, datetime
from typing import Optional
from fastapi import Depends, Request, HTTPException, APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text

from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.procurement.query import (
    get_bill_pass_list_query,
    get_bill_pass_count_query,
    get_bill_pass_by_id_query,
    get_bill_pass_sr_lines_query,
    get_bill_pass_drcr_notes_query,
    get_bill_pass_drcr_note_lines_query,
    get_inward_additional_charges_query,
    update_bill_pass_query,
)
from src.procurement.inward import format_inward_no
from src.procurement.po import extract_formatted_po_no
from src.procurement.export_helpers import build_xlsx, build_pdf


XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PDF_MEDIA_TYPE = "application/pdf"
DOWNLOAD_MAX_ROWS = 50000

logger = logging.getLogger(__name__)

router = APIRouter()


# =============================================================================
# SCHEMAS
# =============================================================================

class BillPassUpdate(BaseModel):
    """Request body for updating bill pass fields."""
    invoice_no: Optional[str] = None
    invoice_date: Optional[str] = None  # YYYY-MM-DD
    invoice_amount: Optional[float] = None
    invoice_recvd_date: Optional[str] = None  # YYYY-MM-DD
    invoice_due_date: Optional[str] = None  # YYYY-MM-DD
    round_off_value: Optional[float] = None
    sr_remarks: Optional[str] = None
    bill_pass_complete: Optional[int] = None  # 1 = complete


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def format_currency(amount) -> str:
    """Format amount as currency string."""
    if amount is None:
        return "₹ 0.00"
    try:
        return f"₹ {float(amount):,.2f}"
    except (ValueError, TypeError):
        return "₹ 0.00"


def safe_float(value, default=0.0) -> float:
    """Safely convert value to float."""
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def format_date_iso(date_obj) -> str | None:
    """Format date object to ISO string."""
    if date_obj is None:
        return None
    if hasattr(date_obj, "isoformat"):
        return date_obj.isoformat()
    return str(date_obj)


def parse_date(date_str: str | None):
    """Parse YYYY-MM-DD string to date object, or return None."""
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str.strip(), "%Y-%m-%d").date()
    except (ValueError, AttributeError):
        return None


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.get("/get_bill_pass_list")
def get_bill_pass_list(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    page: int = 1,
    limit: int = 10,
    search: str | None = None,
    co_id: int | None = None,
):
    """
    Return paginated list of Bill Pass entries.

    Bill Pass shows approved SRs with DRCR adjustments computed.
    Each row contains:
    - SR info (bill_pass_no, date, inward reference)
    - SR total (sum of line amounts)
    - DR total (sum of approved debit notes)
    - CR total (sum of approved credit notes)
    - Net payable (SR - DR + CR)
    - billpass_status (NULL/0 = editable, 1 = complete)
    """
    try:
        page = max(page, 1)
        limit = max(min(limit, 100), 1)
        offset = (page - 1) * limit
        search_like = f"%{search.strip()}%" if search else None

        params = {
            "co_id": co_id,
            "search_like": search_like,
            "limit": limit,
            "offset": offset,
        }

        # Get list data
        list_query = get_bill_pass_list_query()
        rows = db.execute(list_query, params).fetchall()

        data = []
        for row in rows:
            mapped = dict(row._mapping)

            # Format GRN/Inward number
            raw_inward_seq = mapped.get("inward_sequence_no")
            inward_date_obj = mapped.get("inward_date")
            formatted_inward_no = raw_inward_seq
            if raw_inward_seq and isinstance(raw_inward_seq, int):
                try:
                    formatted_inward_no = format_inward_no(
                        inward_sequence_no=int(raw_inward_seq),
                        co_prefix=mapped.get("co_prefix"),
                        branch_prefix=mapped.get("branch_prefix"),
                        inward_date=inward_date_obj,
                    )
                except Exception:
                    formatted_inward_no = str(raw_inward_seq)

            data.append({
                "id": mapped.get("inward_id"),
                "inward_id": mapped.get("inward_id"),
                "bill_pass_no": mapped.get("bill_pass_no") or "",
                "bill_pass_date": format_date_iso(mapped.get("bill_pass_date")),
                "inward_no": formatted_inward_no or "",
                "inward_date": format_date_iso(inward_date_obj),
                "supplier_id": mapped.get("supplier_id"),
                "supplier_name": mapped.get("supplier_name") or "",
                "invoice_date": format_date_iso(mapped.get("invoice_date")),
                "branch_name": mapped.get("branch_name") or "",
                "sr_status_name": mapped.get("sr_status_name") or "Approved",
                "billpass_status": int(mapped.get("billpass_status") or 0),
                # Totals
                "sr_total": safe_float(mapped.get("sr_total")),
                "sr_taxable": safe_float(mapped.get("sr_taxable")),
                "sr_tax": safe_float(mapped.get("sr_tax")),
                "dr_total": safe_float(mapped.get("dr_total")),
                "dr_count": int(mapped.get("dr_count") or 0),
                "cr_total": safe_float(mapped.get("cr_total")),
                "cr_count": int(mapped.get("cr_count") or 0),
                "net_payable": safe_float(mapped.get("net_payable")),
            })

        # Get total count
        count_query = get_bill_pass_count_query()
        count_params = {
            "co_id": co_id,
            "search_like": search_like,
        }
        count_result = db.execute(count_query, count_params).fetchone()
        total = count_result.total if count_result else 0

        return {
            "data": data,
            "total": total,
            "page": page,
            "page_size": limit,
        }

    except Exception as e:
        logger.error(f"Error fetching bill pass list: {e}")
        raise HTTPException(status_code=500, detail=f"Error fetching bill pass list: {str(e)}")


@router.get("/get_bill_pass_by_id/{inward_id}")
def get_bill_pass_by_id(
    inward_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Get Bill Pass detail by inward_id.

    Returns:
    - Header info (bill_pass_no, dates, supplier, invoice)
    - Summary totals (sr_total, dr_total, cr_total, net_payable)
    - SR line items
    - DRCR notes with their line items
    - billpass_status for edit/view mode
    - Invoice fields for editing
    """
    try:
        params = {"inward_id": inward_id}

        # Get header
        header_query = get_bill_pass_by_id_query()
        header_row = db.execute(header_query, params).fetchone()

        if not header_row:
            raise HTTPException(status_code=404, detail=f"Bill Pass not found for inward_id: {inward_id}")

        mapped = dict(header_row._mapping)

        # Check if SR is approved (sr_status = 3)
        sr_status = mapped.get("sr_status")
        if sr_status != 3:
            raise HTTPException(
                status_code=400,
                detail=f"Bill Pass is only available for approved SRs. Current SR status: {mapped.get('sr_status_name', sr_status)}"
            )

        # Format GRN/Inward number
        raw_inward_seq = mapped.get("inward_sequence_no")
        inward_date_obj = mapped.get("inward_date")
        formatted_inward_no = raw_inward_seq
        if raw_inward_seq and isinstance(raw_inward_seq, int):
            try:
                formatted_inward_no = format_inward_no(
                    inward_sequence_no=int(raw_inward_seq),
                    co_prefix=mapped.get("co_prefix"),
                    branch_prefix=mapped.get("branch_prefix"),
                    inward_date=inward_date_obj,
                )
            except Exception:
                formatted_inward_no = str(raw_inward_seq)

        # Get SR line items
        sr_lines_query = get_bill_pass_sr_lines_query()
        sr_lines_rows = db.execute(sr_lines_query, params).fetchall()
        sr_lines = []
        for line_row in sr_lines_rows:
            line = dict(line_row._mapping)
            sr_lines.append({
                "inward_dtl_id": line.get("inward_dtl_id"),
                "item_id": line.get("item_id"),
                "item_name": line.get("item_name") or "",
                "item_code": line.get("full_item_code") or line.get("item_code") or "",
                "item_group_name": line.get("item_grp_name") or "",
                "hsn_code": line.get("hsn_code") or "",
                "accepted_make_name": line.get("accepted_make_name") or "",
                "uom_name": line.get("uom_name") or "",
                "approved_qty": safe_float(line.get("approved_qty")),
                "po_rate": safe_float(line.get("po_rate")),
                "accepted_rate": safe_float(line.get("accepted_rate")),
                "line_amount": safe_float(line.get("line_amount")),
                "discount_amount": safe_float(line.get("discount_amount")),
                "cgst_percent": safe_float(line.get("cgst_percent")),
                "cgst_amount": safe_float(line.get("cgst_amount")),
                "sgst_percent": safe_float(line.get("state_tax_percent")),
                "sgst_amount": safe_float(line.get("sgst_amount")),
                "igst_percent": safe_float(line.get("igst_percent")),
                "igst_amount": safe_float(line.get("igst_amount")),
                "tax_amount": safe_float(line.get("tax_amount")),
                "line_total": safe_float(line.get("line_total")),
                "po_no": extract_formatted_po_no(line) if line.get("po_no") else "",
            })

        # Get DRCR notes
        drcr_notes_query = get_bill_pass_drcr_notes_query()
        drcr_notes_rows = db.execute(drcr_notes_query, params).fetchall()

        debit_notes = []
        credit_notes = []
        for note_row in drcr_notes_rows:
            note = dict(note_row._mapping)
            note_data = {
                "drcr_note_id": note.get("debit_credit_note_id"),
                "note_date": format_date_iso(note.get("note_date")),
                "note_type": note.get("adjustment_type"),
                "note_type_name": note.get("note_type_name") or "",
                "remarks": note.get("remarks") or "",
                "gross_amount": safe_float(note.get("gross_amount")),
                "net_amount": safe_float(note.get("net_amount")),
                "status_name": note.get("status_name") or "",
                "line_count": int(note.get("line_count") or 0),
            }
            if note.get("adjustment_type") == 1:
                debit_notes.append(note_data)
            else:
                credit_notes.append(note_data)

        # Get DRCR note line items
        drcr_lines_query = get_bill_pass_drcr_note_lines_query()
        drcr_lines_rows = db.execute(drcr_lines_query, params).fetchall()

        drcr_lines_by_note = {}
        for line_row in drcr_lines_rows:
            line = dict(line_row._mapping)
            note_id = line.get("debit_credit_note_id")
            if note_id not in drcr_lines_by_note:
                drcr_lines_by_note[note_id] = []
            drcr_lines_by_note[note_id].append({
                "drcr_note_dtl_id": line.get("drcr_note_dtl_id"),
                "inward_dtl_id": line.get("inward_dtl_id"),
                "adjustment_reason": line.get("adjustment_reason") or "",
                "debitnote_type": line.get("debitnote_type"),
                "quantity": safe_float(line.get("quantity")),
                "rate": safe_float(line.get("rate")),
                "discount_amount": safe_float(line.get("discount_amount")),
                "line_amount": safe_float(line.get("line_amount")),
                "item_name": line.get("item_name") or "",
                "item_code": line.get("full_item_code") or line.get("item_code") or "",
                "po_no": extract_formatted_po_no(line) if line.get("po_no") else "",
            })

        # Attach lines to notes
        for note in debit_notes + credit_notes:
            note["lines"] = drcr_lines_by_note.get(note["drcr_note_id"], [])

        # Get additional charges (freight, insurance, etc.) captured at SR stage.
        # Reuses the SR-endpoint query so GST joins stay consistent.
        additional_charges_rows = db.execute(
            get_inward_additional_charges_query(), params
        ).fetchall()
        additional_charges = []
        for row in additional_charges_rows:
            r = dict(row._mapping)
            additional_charges.append({
                "proc_inward_additional_id": r.get("proc_inward_additional_id"),
                "additional_charges_id": r.get("additional_charges_id"),
                "additional_charges_name": r.get("additional_charges_name") or "",
                "qty": safe_float(r.get("qty")),
                "rate": safe_float(r.get("rate")),
                "net_amount": safe_float(r.get("net_amount")),
                "remarks": r.get("remarks") or "",
                "tax_pct": safe_float(r.get("tax_pct")),
                "cgst_amount": safe_float(r.get("cgst_amount")),
                "sgst_amount": safe_float(r.get("sgst_amount")),
                "igst_amount": safe_float(r.get("igst_amount")),
                "tax_amount": safe_float(r.get("tax_amount")),
            })

        # Build response
        response = {
            # Header info
            "inward_id": mapped.get("inward_id"),
            "bill_pass_no": mapped.get("bill_pass_no") or "",
            "bill_pass_date": format_date_iso(mapped.get("bill_pass_date")),
            "inward_no": formatted_inward_no or "",
            "inward_date": format_date_iso(inward_date_obj),
            "supplier_id": mapped.get("supplier_id"),
            "supplier_name": mapped.get("supplier_name") or "",
            "invoice_no": mapped.get("invoice_no") or "",
            "invoice_date": format_date_iso(mapped.get("invoice_date")),
            "invoice_amount": safe_float(mapped.get("invoice_amount")),
            "invoice_recvd_date": format_date_iso(mapped.get("invoice_recvd_date")),
            "invoice_due_date": format_date_iso(mapped.get("invoice_due_date")),
            "branch_id": mapped.get("branch_id"),
            "branch_name": mapped.get("branch_name") or "",
            "sr_status_name": mapped.get("sr_status_name") or "Approved",
            "sr_remarks": mapped.get("sr_remarks") or "",
            "challan_no": mapped.get("challan_no") or "",
            "challan_date": format_date_iso(mapped.get("challan_date")),
            "round_off_value": safe_float(mapped.get("round_off_value")),
            "billpass_status": int(mapped.get("billpass_status") or 0),
            # Summary totals
            "summary": {
                "sr_taxable": safe_float(mapped.get("sr_taxable")),
                "sr_cgst": safe_float(mapped.get("sr_cgst")),
                "sr_sgst": safe_float(mapped.get("sr_sgst")),
                "sr_igst": safe_float(mapped.get("sr_igst")),
                "sr_tax": safe_float(mapped.get("sr_tax")),
                "sr_total": safe_float(mapped.get("sr_total")),
                "sr_line_count": int(mapped.get("sr_line_count") or 0),
                "dr_total": safe_float(mapped.get("dr_total")),
                "dr_count": int(mapped.get("dr_count") or 0),
                "cr_total": safe_float(mapped.get("cr_total")),
                "cr_count": int(mapped.get("cr_count") or 0),
                "additional_net": safe_float(mapped.get("additional_net")),
                "additional_cgst": safe_float(mapped.get("additional_cgst")),
                "additional_sgst": safe_float(mapped.get("additional_sgst")),
                "additional_igst": safe_float(mapped.get("additional_igst")),
                "additional_tax": safe_float(mapped.get("additional_tax")),
                "additional_total": safe_float(mapped.get("additional_total")),
                "additional_count": int(mapped.get("additional_count") or 0),
                "net_payable": safe_float(mapped.get("net_payable")),
            },
            # Line items
            "sr_lines": sr_lines,
            "debit_notes": debit_notes,
            "credit_notes": credit_notes,
            "additional_charges": additional_charges,
        }

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching bill pass detail: {e}")
        raise HTTPException(status_code=500, detail=f"Error fetching bill pass detail: {str(e)}")


@router.put("/update_bill_pass/{inward_id}")
def update_bill_pass(
    inward_id: int,
    body: BillPassUpdate,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Update bill pass fields (invoice details, remarks, round off).

    Two modes:
    - Save: update fields without completing (bill_pass_complete = None or 0)
    - Complete: validate required fields and set billpass_status = 1

    Once billpass_status = 1, no further updates are allowed.
    """
    try:
        user_id = token_data.get("user_id")

        # Verify the inward exists and SR is approved
        check_sql = text("""
            SELECT inward_id, sr_status, billpass_status
            FROM proc_inward
            WHERE inward_id = :inward_id
        """)
        row = db.execute(check_sql, {"inward_id": inward_id}).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail=f"Inward not found: {inward_id}")

        mapped = dict(row._mapping)
        if mapped.get("sr_status") != 3:
            raise HTTPException(status_code=400, detail="Bill Pass is only available for approved SRs")

        if int(mapped.get("billpass_status") or 0) == 1:
            raise HTTPException(status_code=400, detail="Bill Pass is already complete and cannot be modified")

        # Determine if this is a complete action
        is_complete = body.bill_pass_complete == 1

        # Validate required fields on complete
        if is_complete:
            if not body.invoice_date:
                raise HTTPException(status_code=400, detail="Invoice Date is required to complete bill pass")
            if body.invoice_amount is None:
                raise HTTPException(status_code=400, detail="Invoice Amount is required to complete bill pass")

        # Build update params
        params = {
            "inward_id": inward_id,
            "invoice_no": body.invoice_no,
            "invoice_date": parse_date(body.invoice_date),
            "invoice_amount": round(body.invoice_amount, 2) if body.invoice_amount is not None else None,
            "invoice_recvd_date": parse_date(body.invoice_recvd_date),
            "invoice_due_date": parse_date(body.invoice_due_date),
            "round_off_value": round(body.round_off_value, 2) if body.round_off_value is not None else None,
            "sr_remarks": body.sr_remarks,
            "billpass_status": 1 if is_complete else None,
            "billpass_date": date.today() if is_complete else None,
            "updated_by": user_id,
        }

        query = update_bill_pass_query()
        db.execute(query, params)
        db.commit()

        # Auto-post into accounting AFTER the business commit — posting can
        # never fail or roll back the bill-pass completion itself.
        accounting_posting = None
        if is_complete:
            try:
                from src.accounting.posting_service import post_document
                accounting_posting = post_document(db, "PROC_BILLPASS", inward_id, user_id)
            except Exception as posting_error:  # defensive: post_document never raises
                logger.error(
                    f"Accounting auto-posting failed for inward {inward_id}: {posting_error}"
                )
                accounting_posting = {
                    "status": "FAILED",
                    "acc_voucher_id": None,
                    "message": str(posting_error),
                }

        return {
            "message": "Bill Pass completed successfully" if is_complete else "Bill Pass saved successfully",
            "inward_id": inward_id,
            "billpass_status": 1 if is_complete else 0,
            "accounting_posting": accounting_posting,
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating bill pass: {e}")
        raise HTTPException(status_code=500, detail=f"Error updating bill pass: {str(e)}")


# =============================================================================
# DOWNLOAD
# =============================================================================

BILL_PASS_COLUMNS = [
    ("Bill Pass No", "bill_pass_no"),
    ("Bill Pass Date", "bill_pass_date"),
    ("GRN No", "inward_no"),
    ("GRN Date", "inward_date"),
    ("Supplier", "supplier_name"),
    ("Branch", "branch_name"),
    ("Invoice Date", "invoice_date"),
    ("SR Status", "sr_status_name"),
    ("SR Total", "sr_total"),
    ("DR Total", "dr_total"),
    ("CR Total", "cr_total"),
    ("Net Payable", "net_payable"),
]


@router.get("/download_bill_pass_list")
def download_bill_pass_list(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    format: str | None = None,
    search: str | None = None,
    co_id: int | None = None,
):
    """Download the Bill Pass list as xlsx or pdf.

    Mirrors the listing endpoint's filters (co_id, search) but is
    unpaginated (capped at 50000 rows).
    """
    try:
        if not format:
            raise HTTPException(status_code=400, detail="format is required (xlsx or pdf)")
        fmt = format.lower()
        if fmt not in ("xlsx", "pdf"):
            raise HTTPException(status_code=400, detail="format must be 'xlsx' or 'pdf'")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        search_like = f"%{search.strip()}%" if search else None

        params = {
            "co_id": int(co_id),
            "search_like": search_like,
            "limit": DOWNLOAD_MAX_ROWS,
            "offset": 0,
        }

        rows = db.execute(get_bill_pass_list_query(), params).fetchall()

        data = []
        for row in rows:
            mapped = dict(row._mapping)

            raw_inward_seq = mapped.get("inward_sequence_no")
            inward_date_obj = mapped.get("inward_date")
            formatted_inward_no = raw_inward_seq
            if raw_inward_seq and isinstance(raw_inward_seq, int):
                try:
                    formatted_inward_no = format_inward_no(
                        inward_sequence_no=int(raw_inward_seq),
                        co_prefix=mapped.get("co_prefix"),
                        branch_prefix=mapped.get("branch_prefix"),
                        inward_date=inward_date_obj,
                    )
                except Exception:
                    formatted_inward_no = str(raw_inward_seq)

            data.append({
                "bill_pass_no": mapped.get("bill_pass_no") or "",
                "bill_pass_date": format_date_iso(mapped.get("bill_pass_date")),
                "inward_no": formatted_inward_no or "",
                "inward_date": format_date_iso(inward_date_obj),
                "supplier_name": mapped.get("supplier_name") or "",
                "branch_name": mapped.get("branch_name") or "",
                "invoice_date": format_date_iso(mapped.get("invoice_date")),
                "sr_status_name": mapped.get("sr_status_name") or "Approved",
                "sr_total": safe_float(mapped.get("sr_total")),
                "dr_total": safe_float(mapped.get("dr_total")),
                "cr_total": safe_float(mapped.get("cr_total")),
                "net_payable": safe_float(mapped.get("net_payable")),
            })

        today_str = date.today().isoformat()
        title = "Bill Pass Report"
        if fmt == "xlsx":
            buf = build_xlsx(data, BILL_PASS_COLUMNS, sheet_name=title[:31])
            media_type = XLSX_MEDIA_TYPE
            ext = "xlsx"
        else:
            buf = build_pdf(data, BILL_PASS_COLUMNS, title=title)
            media_type = PDF_MEDIA_TYPE
            ext = "pdf"

        return StreamingResponse(
            buf,
            media_type=media_type,
            headers={
                "Content-Disposition": f'attachment; filename="bill-pass-{today_str}.{ext}"'
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error downloading bill pass list: {e}")
        raise HTTPException(status_code=500, detail=f"Error downloading bill pass list: {str(e)}")
