"""
Procurement Report endpoints.
Provides endpoints for item-wise indent reports and related procurement reports.
"""

import logging
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.procurement.reportQueries import (
    get_indent_itemwise_report_query,
    get_indent_itemwise_report_count_query,
    get_po_itemwise_report_query,
    get_po_itemwise_report_count_query,
    get_sr_itemwise_report_query,
    get_sr_itemwise_report_count_query,
)
from src.procurement.indent import format_indent_no
from src.procurement.inward import format_inward_no
from src.procurement.po import format_po_no
from src.procurement.export_helpers import build_xlsx, build_pdf

logger = logging.getLogger(__name__)

router = APIRouter()


XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PDF_MEDIA_TYPE = "application/pdf"
DOWNLOAD_MAX_ROWS = 50000


def _validate_format(fmt: str | None) -> str:
    """Validate the ?format= query param. Returns the normalized format."""
    if not fmt:
        raise HTTPException(status_code=400, detail="format is required (xlsx or pdf)")
    fmt_l = fmt.lower()
    if fmt_l not in ("xlsx", "pdf"):
        raise HTTPException(status_code=400, detail="format must be 'xlsx' or 'pdf'")
    return fmt_l


def _download_response(
    rows: list[dict],
    columns: list[tuple[str, str]],
    fmt: str,
    filename_base: str,
    title: str,
) -> StreamingResponse:
    """Build a StreamingResponse for an xlsx or pdf download."""
    today_str = date.today().isoformat()
    if fmt == "xlsx":
        buf = build_xlsx(rows, columns, sheet_name=title[:31])
        media_type = XLSX_MEDIA_TYPE
        ext = "xlsx"
    else:
        buf = build_pdf(rows, columns, title=title)
        media_type = PDF_MEDIA_TYPE
        ext = "pdf"
    filename = f"{filename_base}-{today_str}.{ext}"
    return StreamingResponse(
        buf,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _format_indent_row(mapped: dict) -> dict:
    """Shape one indent-itemwise mapped row into the response dict used by both
    the listing endpoint and the download endpoint."""
    indent_date_obj = mapped.get("indent_date")
    indent_date = indent_date_obj
    if hasattr(indent_date_obj, "isoformat"):
        indent_date = indent_date_obj.isoformat()

    raw_indent_no = mapped.get("indent_no")
    formatted_indent_no = ""
    if raw_indent_no is not None and raw_indent_no != 0:
        try:
            formatted_indent_no = format_indent_no(
                indent_no=int(raw_indent_no),
                co_prefix=mapped.get("co_prefix"),
                branch_prefix=mapped.get("branch_prefix"),
                indent_date=indent_date_obj,
                document_type="INDENT",
            )
        except Exception:
            logger.exception("Error formatting indent number in report")
            formatted_indent_no = str(raw_indent_no)

    return {
        "indent_dtl_id": mapped.get("indent_dtl_id"),
        "indent_id": mapped.get("indent_id"),
        "indent_no": formatted_indent_no,
        "indent_date": indent_date,
        "branch_name": mapped.get("branch_name"),
        "item_name": mapped.get("item_name"),
        "item_grp_name": mapped.get("item_grp_name"),
        "uom_name": mapped.get("uom_name"),
        "indent_qty": mapped.get("indent_qty"),
        "po_consumed_qty": mapped.get("po_consumed_qty"),
        "outstanding_qty": mapped.get("outstanding_qty"),
        "indent_type_id": mapped.get("indent_type_id"),
        "expense_type_name": mapped.get("expense_type_name"),
        "status_name": mapped.get("status_name"),
    }


def _format_po_row(mapped: dict) -> dict:
    """Shape one po-itemwise mapped row into the response dict."""
    po_date_obj = mapped.get("po_date")
    po_date = po_date_obj
    if hasattr(po_date_obj, "isoformat"):
        po_date = po_date_obj.isoformat()

    raw_po_no = mapped.get("po_no")
    formatted_po_no = ""
    if raw_po_no is not None and raw_po_no != 0:
        try:
            formatted_po_no = format_po_no(
                po_no=int(raw_po_no),
                co_prefix=mapped.get("co_prefix"),
                branch_prefix=mapped.get("branch_prefix"),
                po_date=po_date_obj,
            )
        except Exception:
            logger.exception("Error formatting PO number in report")
            formatted_po_no = str(raw_po_no)

    return {
        "po_dtl_id": mapped.get("po_dtl_id"),
        "po_id": mapped.get("po_id"),
        "po_no": formatted_po_no,
        "po_date": po_date,
        "branch_name": mapped.get("branch_name"),
        "supplier_name": mapped.get("supplier_name"),
        "item_name": mapped.get("item_name"),
        "item_grp_name": mapped.get("item_grp_name"),
        "uom_name": mapped.get("uom_name"),
        "po_qty": mapped.get("po_qty"),
        "rate": mapped.get("rate"),
        "inward_consumed_qty": mapped.get("inward_consumed_qty"),
        "outstanding_qty": mapped.get("outstanding_qty"),
        "po_type": mapped.get("po_type"),
        "expense_type_name": mapped.get("expense_type_name"),
        "status_name": mapped.get("status_name"),
    }


def _format_sr_row(mapped: dict) -> dict:
    """Shape one sr-itemwise mapped row into the response dict."""
    inward_date_obj = mapped.get("inward_date")
    inward_date = inward_date_obj
    if hasattr(inward_date_obj, "isoformat"):
        inward_date = inward_date_obj.isoformat()

    raw_inward_no = mapped.get("inward_sequence_no")
    formatted_inward_no = ""
    if raw_inward_no is not None and raw_inward_no != 0:
        try:
            formatted_inward_no = format_inward_no(
                inward_sequence_no=int(raw_inward_no),
                co_prefix=mapped.get("co_prefix"),
                branch_prefix=mapped.get("branch_prefix"),
                inward_date=inward_date_obj,
            )
        except Exception:
            logger.exception("Error formatting GRN number in SR report")
            formatted_inward_no = str(raw_inward_no)

    return {
        "inward_dtl_id": mapped.get("inward_dtl_id"),
        "inward_id": mapped.get("inward_id"),
        "inward_no": formatted_inward_no,
        "inward_date": inward_date,
        "branch_name": mapped.get("branch_name"),
        "supplier_name": mapped.get("supplier_name"),
        "item_name": mapped.get("item_name"),
        "item_grp_name": mapped.get("item_grp_name"),
        "uom_name": mapped.get("uom_name"),
        "approved_qty": mapped.get("approved_qty"),
        "rejected_qty": mapped.get("rejected_qty"),
        "rate": mapped.get("rate"),
        "amount": mapped.get("amount"),
        "status_name": mapped.get("status_name"),
    }


@router.get("/indent-itemwise")
def get_indent_itemwise_report(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    page: int = 1,
    limit: int = 10,
    co_id: int | None = None,
    branch_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    indent_type: str | None = None,
    outstanding_filter: str | None = None,
    status_id: int | None = None,
    search: str | None = None,
):
    """
    Item-wise indent report.

    Returns one row per indent detail line with indent header info,
    item details, and outstanding quantity tracking.

    Query params:
    - co_id: Company ID (required)
    - branch_id: Branch ID (optional, NULL = all branches)
    - date_from: Start date YYYY-MM-DD (optional)
    - date_to: End date YYYY-MM-DD (optional)
    - indent_type: 'Regular', 'Open', 'BOM', or omit for all
    - outstanding_filter: 'outstanding', 'non_outstanding', or omit for all
    - status_id: Single status to filter to (1=Open, 3=Approved, 5=Closed, 20=Pending Approval).
                 If omitted, returns all in (1, 3, 5, 20).
    - search: Search term for item name, branch name, item group
    - page: Page number (default 1)
    - limit: Page size (default 10, max 10000)
    """
    try:
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        page = max(page, 1)
        limit = max(min(limit, 10000), 1)
        offset = (page - 1) * limit

        search_like = None
        if search:
            search_like = f"%{search.strip()}%"

        # Validate outstanding_filter
        if outstanding_filter and outstanding_filter not in ("outstanding", "non_outstanding"):
            raise HTTPException(status_code=400, detail="outstanding_filter must be 'outstanding' or 'non_outstanding'")

        # Validate indent_type
        if indent_type and indent_type not in ("Regular", "Open", "BOM"):
            raise HTTPException(status_code=400, detail="indent_type must be 'Regular', 'Open', or 'BOM'")

        params = {
            "co_id": int(co_id),
            "branch_id": int(branch_id) if branch_id else None,
            "date_from": date_from if date_from else None,
            "date_to": date_to if date_to else None,
            "indent_type": indent_type if indent_type else None,
            "outstanding_filter": outstanding_filter if outstanding_filter else None,
            "status_id": int(status_id) if status_id else None,
            "search_like": search_like,
            "limit": limit,
            "offset": offset,
        }

        # Fetch data
        list_query = get_indent_itemwise_report_query()
        rows = db.execute(list_query, params).fetchall()

        data = [_format_indent_row(dict(row._mapping)) for row in rows]

        # Fetch count
        count_query = get_indent_itemwise_report_count_query()
        count_params = {
            "co_id": int(co_id),
            "branch_id": int(branch_id) if branch_id else None,
            "date_from": date_from if date_from else None,
            "date_to": date_to if date_to else None,
            "indent_type": indent_type if indent_type else None,
            "outstanding_filter": outstanding_filter if outstanding_filter else None,
            "status_id": int(status_id) if status_id else None,
            "search_like": search_like,
        }
        count_result = db.execute(count_query, count_params).scalar()
        total = int(count_result) if count_result is not None else 0

        return {"data": data, "total": total}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching indent itemwise report: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/po-itemwise")
def get_po_itemwise_report(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    page: int = 1,
    limit: int = 10,
    co_id: int | None = None,
    branch_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    po_type: str | None = None,
    outstanding_filter: str | None = None,
    search: str | None = None,
):
    """
    Item-wise PO report.

    Returns one row per PO detail line with PO header info,
    item details, rate, and outstanding quantity tracking.

    Query params:
    - co_id: Company ID (required)
    - branch_id: Branch ID (optional, NULL = all branches)
    - date_from: Start date YYYY-MM-DD (optional)
    - date_to: End date YYYY-MM-DD (optional)
    - po_type: 'Regular', 'Open', or omit for all
    - outstanding_filter: 'outstanding', 'non_outstanding', or omit for all
    - search: Search term for item name, branch name, item group, supplier name
    - page: Page number (default 1)
    - limit: Page size (default 10, max 10000)
    """
    try:
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        page = max(page, 1)
        limit = max(min(limit, 10000), 1)
        offset = (page - 1) * limit

        search_like = None
        if search:
            search_like = f"%{search.strip()}%"

        if outstanding_filter and outstanding_filter not in ("outstanding", "non_outstanding"):
            raise HTTPException(status_code=400, detail="outstanding_filter must be 'outstanding' or 'non_outstanding'")

        if po_type and po_type not in ("Regular", "Open"):
            raise HTTPException(status_code=400, detail="po_type must be 'Regular' or 'Open'")

        params = {
            "co_id": int(co_id),
            "branch_id": int(branch_id) if branch_id else None,
            "date_from": date_from if date_from else None,
            "date_to": date_to if date_to else None,
            "po_type": po_type if po_type else None,
            "outstanding_filter": outstanding_filter if outstanding_filter else None,
            "search_like": search_like,
            "limit": limit,
            "offset": offset,
        }

        list_query = get_po_itemwise_report_query()
        rows = db.execute(list_query, params).fetchall()

        data = []
        for row in rows:
            mapped = dict(row._mapping)
            po_date_obj = mapped.get("po_date")
            po_date = po_date_obj
            if hasattr(po_date_obj, "isoformat"):
                po_date = po_date_obj.isoformat()

            raw_po_no = mapped.get("po_no")
            formatted_po_no = ""
            if raw_po_no is not None and raw_po_no != 0:
                try:
                    formatted_po_no = format_po_no(
                        po_no=int(raw_po_no),
                        co_prefix=mapped.get("co_prefix"),
                        branch_prefix=mapped.get("branch_prefix"),
                        po_date=po_date_obj,
                    )
                except Exception:
                    logger.exception("Error formatting PO number in report")
                    formatted_po_no = str(raw_po_no)

            data.append({
                "po_dtl_id": mapped.get("po_dtl_id"),
                "po_id": mapped.get("po_id"),
                "po_no": formatted_po_no,
                "po_date": po_date,
                "branch_name": mapped.get("branch_name"),
                "supplier_name": mapped.get("supplier_name"),
                "item_name": mapped.get("item_name"),
                "item_grp_name": mapped.get("item_grp_name"),
                "uom_name": mapped.get("uom_name"),
                "po_qty": mapped.get("po_qty"),
                "rate": mapped.get("rate"),
                "inward_consumed_qty": mapped.get("inward_consumed_qty"),
                "outstanding_qty": mapped.get("outstanding_qty"),
                "po_type": mapped.get("po_type"),
                "expense_type_name": mapped.get("expense_type_name"),
                "status_name": mapped.get("status_name"),
            })

        count_query = get_po_itemwise_report_count_query()
        count_params = {
            "co_id": int(co_id),
            "branch_id": int(branch_id) if branch_id else None,
            "date_from": date_from if date_from else None,
            "date_to": date_to if date_to else None,
            "po_type": po_type if po_type else None,
            "outstanding_filter": outstanding_filter if outstanding_filter else None,
            "search_like": search_like,
        }
        count_result = db.execute(count_query, count_params).scalar()
        total = int(count_result) if count_result is not None else 0

        return {"data": data, "total": total}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching PO itemwise report: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sr-itemwise")
def get_sr_itemwise_report(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    page: int = 1,
    limit: int = 10,
    co_id: int | None = None,
    branch_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    search: str | None = None,
):
    """
    Item-wise SR report.

    Returns one row per inward detail line with GRN header info,
    item details, approved/rejected quantities, and rate.

    Query params:
    - co_id: Company ID (required)
    - branch_id: Branch ID (optional, NULL = all branches)
    - date_from: Start date YYYY-MM-DD (optional)
    - date_to: End date YYYY-MM-DD (optional)
    - search: Search term for item name, branch name, item group, supplier name
    - page: Page number (default 1)
    - limit: Page size (default 10, max 10000)
    """
    try:
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        page = max(page, 1)
        limit = max(min(limit, 10000), 1)
        offset = (page - 1) * limit

        search_like = None
        if search:
            search_like = f"%{search.strip()}%"

        params = {
            "co_id": int(co_id),
            "branch_id": int(branch_id) if branch_id else None,
            "date_from": date_from if date_from else None,
            "date_to": date_to if date_to else None,
            "search_like": search_like,
            "limit": limit,
            "offset": offset,
        }

        list_query = get_sr_itemwise_report_query()
        rows = db.execute(list_query, params).fetchall()

        data = []
        for row in rows:
            mapped = dict(row._mapping)
            inward_date_obj = mapped.get("inward_date")
            inward_date = inward_date_obj
            if hasattr(inward_date_obj, "isoformat"):
                inward_date = inward_date_obj.isoformat()

            raw_inward_no = mapped.get("inward_sequence_no")
            formatted_inward_no = ""
            if raw_inward_no is not None and raw_inward_no != 0:
                try:
                    formatted_inward_no = format_inward_no(
                        inward_sequence_no=int(raw_inward_no),
                        co_prefix=mapped.get("co_prefix"),
                        branch_prefix=mapped.get("branch_prefix"),
                        inward_date=inward_date_obj,
                    )
                except Exception:
                    logger.exception("Error formatting GRN number in SR report")
                    formatted_inward_no = str(raw_inward_no)

            data.append({
                "inward_dtl_id": mapped.get("inward_dtl_id"),
                "inward_id": mapped.get("inward_id"),
                "inward_no": formatted_inward_no,
                "inward_date": inward_date,
                "branch_name": mapped.get("branch_name"),
                "supplier_name": mapped.get("supplier_name"),
                "item_name": mapped.get("item_name"),
                "item_grp_name": mapped.get("item_grp_name"),
                "uom_name": mapped.get("uom_name"),
                "approved_qty": mapped.get("approved_qty"),
                "rejected_qty": mapped.get("rejected_qty"),
                "rate": mapped.get("rate"),
                "amount": mapped.get("amount"),
                "status_name": mapped.get("status_name"),
            })

        count_query = get_sr_itemwise_report_count_query()
        count_params = {
            "co_id": int(co_id),
            "branch_id": int(branch_id) if branch_id else None,
            "date_from": date_from if date_from else None,
            "date_to": date_to if date_to else None,
            "search_like": search_like,
        }
        count_result = db.execute(count_query, count_params).scalar()
        total = int(count_result) if count_result is not None else 0

        return {"data": data, "total": total}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching SR itemwise report: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# DOWNLOAD ENDPOINTS (xlsx + pdf)
# =============================================================================

INDENT_ITEMWISE_COLUMNS = [
    ("Indent No", "indent_no"),
    ("Indent Date", "indent_date"),
    ("Branch", "branch_name"),
    ("Item", "item_name"),
    ("Item Group", "item_grp_name"),
    ("UOM", "uom_name"),
    ("Indent Qty", "indent_qty"),
    ("PO Consumed", "po_consumed_qty"),
    ("Outstanding Qty", "outstanding_qty"),
    ("Type", "indent_type_id"),
    ("Expense Type", "expense_type_name"),
    ("Status", "status_name"),
]

PO_ITEMWISE_COLUMNS = [
    ("PO No", "po_no"),
    ("PO Date", "po_date"),
    ("Branch", "branch_name"),
    ("Supplier", "supplier_name"),
    ("Item", "item_name"),
    ("Item Group", "item_grp_name"),
    ("UOM", "uom_name"),
    ("PO Qty", "po_qty"),
    ("Rate", "rate"),
    ("Inward Consumed", "inward_consumed_qty"),
    ("Outstanding Qty", "outstanding_qty"),
    ("PO Type", "po_type"),
    ("Expense Type", "expense_type_name"),
    ("Status", "status_name"),
]

SR_ITEMWISE_COLUMNS = [
    ("GRN No", "inward_no"),
    ("GRN Date", "inward_date"),
    ("Branch", "branch_name"),
    ("Supplier", "supplier_name"),
    ("Item", "item_name"),
    ("Item Group", "item_grp_name"),
    ("UOM", "uom_name"),
    ("Approved Qty", "approved_qty"),
    ("Rejected Qty", "rejected_qty"),
    ("Rate", "rate"),
    ("Amount", "amount"),
    ("Status", "status_name"),
]


@router.get("/indent-itemwise/download")
def download_indent_itemwise_report(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    format: str | None = None,
    co_id: int | None = None,
    branch_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    indent_type: str | None = None,
    outstanding_filter: str | None = None,
    status_id: int | None = None,
    search: str | None = None,
):
    """Download the indent-itemwise report as xlsx or pdf. Same filters as
    `/indent-itemwise` listing endpoint, but unpaginated (capped at 50000 rows).
    """
    try:
        fmt = _validate_format(format)
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        if outstanding_filter and outstanding_filter not in ("outstanding", "non_outstanding"):
            raise HTTPException(status_code=400, detail="outstanding_filter must be 'outstanding' or 'non_outstanding'")
        if indent_type and indent_type not in ("Regular", "Open", "BOM"):
            raise HTTPException(status_code=400, detail="indent_type must be 'Regular', 'Open', or 'BOM'")

        search_like = f"%{search.strip()}%" if search else None

        params = {
            "co_id": int(co_id),
            "branch_id": int(branch_id) if branch_id else None,
            "date_from": date_from if date_from else None,
            "date_to": date_to if date_to else None,
            "indent_type": indent_type if indent_type else None,
            "outstanding_filter": outstanding_filter if outstanding_filter else None,
            "status_id": int(status_id) if status_id else None,
            "search_like": search_like,
            "limit": DOWNLOAD_MAX_ROWS,
            "offset": 0,
        }
        rows = db.execute(get_indent_itemwise_report_query(), params).fetchall()
        data = [_format_indent_row(dict(r._mapping)) for r in rows]

        return _download_response(
            rows=data,
            columns=INDENT_ITEMWISE_COLUMNS,
            fmt=fmt,
            filename_base="indent-itemwise",
            title="Indent Item-wise Report",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error downloading indent itemwise report: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/po-itemwise/download")
def download_po_itemwise_report(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    format: str | None = None,
    co_id: int | None = None,
    branch_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    po_type: str | None = None,
    outstanding_filter: str | None = None,
    search: str | None = None,
):
    """Download the po-itemwise report as xlsx or pdf. Same filters as
    `/po-itemwise` listing endpoint, but unpaginated (capped at 50000 rows).
    """
    try:
        fmt = _validate_format(format)
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        if outstanding_filter and outstanding_filter not in ("outstanding", "non_outstanding"):
            raise HTTPException(status_code=400, detail="outstanding_filter must be 'outstanding' or 'non_outstanding'")
        if po_type and po_type not in ("Regular", "Open"):
            raise HTTPException(status_code=400, detail="po_type must be 'Regular' or 'Open'")

        search_like = f"%{search.strip()}%" if search else None

        params = {
            "co_id": int(co_id),
            "branch_id": int(branch_id) if branch_id else None,
            "date_from": date_from if date_from else None,
            "date_to": date_to if date_to else None,
            "po_type": po_type if po_type else None,
            "outstanding_filter": outstanding_filter if outstanding_filter else None,
            "search_like": search_like,
            "limit": DOWNLOAD_MAX_ROWS,
            "offset": 0,
        }
        rows = db.execute(get_po_itemwise_report_query(), params).fetchall()
        data = [_format_po_row(dict(r._mapping)) for r in rows]

        return _download_response(
            rows=data,
            columns=PO_ITEMWISE_COLUMNS,
            fmt=fmt,
            filename_base="po-itemwise",
            title="PO Item-wise Report",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error downloading PO itemwise report: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sr-itemwise/download")
def download_sr_itemwise_report(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    format: str | None = None,
    co_id: int | None = None,
    branch_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    search: str | None = None,
):
    """Download the sr-itemwise report as xlsx or pdf. Same filters as
    `/sr-itemwise` listing endpoint, but unpaginated (capped at 50000 rows).
    """
    try:
        fmt = _validate_format(format)
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        search_like = f"%{search.strip()}%" if search else None

        params = {
            "co_id": int(co_id),
            "branch_id": int(branch_id) if branch_id else None,
            "date_from": date_from if date_from else None,
            "date_to": date_to if date_to else None,
            "search_like": search_like,
            "limit": DOWNLOAD_MAX_ROWS,
            "offset": 0,
        }
        rows = db.execute(get_sr_itemwise_report_query(), params).fetchall()
        data = [_format_sr_row(dict(r._mapping)) for r in rows]

        return _download_response(
            rows=data,
            columns=SR_ITEMWISE_COLUMNS,
            fmt=fmt,
            filename_base="sr-itemwise",
            title="SR Item-wise Report",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error downloading SR itemwise report: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
