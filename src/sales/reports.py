"""
Sales Report endpoints.

Endpoints for Tally-style downloads and other sales reports. Mirrors the
validation / response shape of src/juteProcurement/reports.py.
"""

import logging
from datetime import datetime
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from sqlalchemy.orm import Session

from src.authorization.utils import get_current_user_with_refresh
from src.config.db import get_tenant_db
from src.sales.constants import INVOICE_TYPE_IDS, SALES_STATUS_IDS
from src.sales.reportQueries import (
    get_invoice_list_report_query,
    get_sales_jute_summary_query,
    get_sales_jute_tally_download_query,
    get_sales_order_list_report_query,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# Hard cap on rows returned by the tally download endpoint. Matches the
# 10,000-row limit used elsewhere in the reports module.
_MAX_ROWS = 10000

# Internal ORDER BY helper columns emitted by the SQL but NOT part of the
# Tally xlsx. Stripped before writing to the workbook.
_INTERNAL_COLS = {
    "invoice_date",
    "invoice_no_string",
    "invoice_line_item_id",
    "rem",
    "rem_rank",
    "slno",
}

# Canonical output column order for the Tally xlsx. The misspellings and
# punctuation are preserved EXACTLY — Tally importers match on these strings.
_CSV_COLUMNS = [
    "Voucher Type Name",
    "Voucher Date",
    "Voucher Number",
    "Ledger Name",
    "Ledger Amount",
    "Ledger Amount Dr/Cr",
    "Despatch Doc no.",
    "Despath though",          # (sic) legacy misspelling — keep
    "Destination",
    "other references",
    "Item Name",
    "Godown",
    "Batch/Lotno.",            # dot is intentional
    "Billed Quantity",
    "Item Rate",
    "Item Rate per",
    "Item Amount",
    "Description ?",           # space + ? is intentional
    "Change Mode",
    "Bill Amount",
    "Bill Amount - Dr/Cr",
    "Bill Name",
    "Bill Type of Ref",
    "Due or credit days",
    "Narration",
    "Address1",
    "State1",
    "Country1",
    "Address2",
    "State2",
    "Country2",
]

# Ledger-related columns that must be blanked on subsequent ln rows for the
# same invoice (matching the reference file layout).
_LN_LEDGER_BLANK_COLS = (
    "Ledger Name",
    "Ledger Amount",
    "Ledger Amount Dr/Cr",
)


def _parse_iso_date(value: str, field_name: str) -> str:
    """Validate a YYYY-MM-DD date string. Raises HTTPException(400) if invalid."""
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid {field_name} format, expected YYYY-MM-DD",
        )
    return value


def _project_rows_to_xlsx_data(rows):
    """Project DB rows onto the 31-column Tally template and post-process.

    Post-processing: within each invoice group (keyed by `invoice_no_string`),
    the first ln row keeps its Ledger fields populated; subsequent ln rows
    have Ledger Name / Ledger Amount / Ledger Amount Dr/Cr blanked out. This
    matches the reference workbook layout.

    Rows are assumed to arrive already ordered by:
        invoice_date, invoice_no_string, rem_rank, invoice_line_item_id
    (which the SQL guarantees).
    """
    output = []
    current_invoice_key = None
    first_ln_seen_for_current = False

    for r in rows:
        mapped = dict(r._mapping)

        rem = mapped.get("rem")
        invoice_key = mapped.get("invoice_no_string")

        # Reset per-invoice tracking when we move to a new invoice.
        if invoice_key != current_invoice_key:
            current_invoice_key = invoice_key
            first_ln_seen_for_current = False

        # Strip internal-only ordering helpers.
        for k in _INTERNAL_COLS:
            mapped.pop(k, None)

        # Project to canonical column order. Missing columns default to ''.
        row_out = {col: mapped.get(col, "") for col in _CSV_COLUMNS}

        # Blank ledger fields on ln rows after the first for this invoice.
        if rem == "ln":
            if first_ln_seen_for_current:
                for col in _LN_LEDGER_BLANK_COLS:
                    row_out[col] = ""
            else:
                first_ln_seen_for_current = True

        output.append(row_out)

    return output


def _build_xlsx_bytes(projected_rows) -> BytesIO:
    """Build a single-sheet `Sales` xlsx workbook and return as BytesIO."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Sales"

    # Header row.
    ws.append(list(_CSV_COLUMNS))

    # Data rows.
    for row in projected_rows:
        ws.append([row.get(col, "") for col in _CSV_COLUMNS])

    bio = BytesIO()
    wb.save(bio)
    bio.seek(0)
    return bio


@router.get("/jute-tally-download")
def get_sales_jute_tally_download(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Sales Raw Jute Tally xlsx download.

    Returns a single-sheet `Sales` xlsx workbook in the exact column order
    Tally expects for a Raw Jute export (invoice_type = RAW_JUTE,
    status = APPROVED) between two dates.

    Query params:
    - co_id:     Company ID (required, int)
    - branch_id: Branch ID (optional, int)
    - date_from: Start date YYYY-MM-DD (required)
    - date_to:   End date YYYY-MM-DD (required)

    Response: `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`
    with Content-Disposition attachment.
    """
    try:
        q_co_id = request.query_params.get("co_id")
        q_branch_id = request.query_params.get("branch_id")
        q_date_from = request.query_params.get("date_from")
        q_date_to = request.query_params.get("date_to")

        if not q_co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        if not q_date_from:
            raise HTTPException(status_code=400, detail="date_from is required")
        if not q_date_to:
            raise HTTPException(status_code=400, detail="date_to is required")

        try:
            co_id = int(q_co_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid co_id")

        branch_id = None
        if q_branch_id not in (None, ""):
            try:
                branch_id = int(q_branch_id)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="Invalid branch_id")

        date_from = _parse_iso_date(q_date_from, "date_from")
        date_to = _parse_iso_date(q_date_to, "date_to")

        params = {
            "co_id": co_id,
            "branch_id": branch_id,
            "date_from": date_from,
            "date_to": date_to,
            "invoice_type_id": INVOICE_TYPE_IDS["RAW_JUTE"],
            "approved_status_id": SALES_STATUS_IDS["APPROVED"],
        }

        query = get_sales_jute_tally_download_query()
        rows = db.execute(query, params).fetchall()

        projected = _project_rows_to_xlsx_data(rows)

        if len(projected) > _MAX_ROWS:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Result set too large ({len(projected)} rows, "
                    f"max {_MAX_ROWS}). Narrow your date range."
                ),
            )

        bio = _build_xlsx_bytes(projected)

        filename = f"sales_raw_jute_tally_{date_from}_{date_to}.xlsx"
        return StreamingResponse(
            bio,
            media_type=(
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            ),
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Error generating sales jute tally download: {e}", exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail=f"Error generating sales jute tally download: {str(e)}",
        )


@router.get("/jute-mr-summary")
def get_sales_jute_mr_summary(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Per-sales-invoice summary of MRs that match the Tally download scope.

    Same filter scope as `/jute-tally-download`. One row per sales invoice
    with linked MR number + amounts so the user can preview before downloading.

    Query params:
    - co_id:     Company ID (required, int)
    - branch_id: Branch ID (optional, int)
    - date_from: Start date YYYY-MM-DD (required)
    - date_to:   End date YYYY-MM-DD (required)

    Returns: {"data": [row, ...]}
    """
    try:
        q_co_id = request.query_params.get("co_id")
        q_branch_id = request.query_params.get("branch_id")
        q_date_from = request.query_params.get("date_from")
        q_date_to = request.query_params.get("date_to")

        if not q_co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        if not q_date_from:
            raise HTTPException(status_code=400, detail="date_from is required")
        if not q_date_to:
            raise HTTPException(status_code=400, detail="date_to is required")

        try:
            co_id = int(q_co_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid co_id")

        branch_id = None
        if q_branch_id not in (None, ""):
            try:
                branch_id = int(q_branch_id)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="Invalid branch_id")

        date_from = _parse_iso_date(q_date_from, "date_from")
        date_to = _parse_iso_date(q_date_to, "date_to")

        params = {
            "co_id": co_id,
            "branch_id": branch_id,
            "date_from": date_from,
            "date_to": date_to,
            "invoice_type_id": INVOICE_TYPE_IDS["RAW_JUTE"],
            "approved_status_id": SALES_STATUS_IDS["APPROVED"],
        }

        rows = db.execute(get_sales_jute_summary_query(), params).fetchall()

        data = []
        for row in rows:
            mapped = dict(row._mapping)
            value = mapped.get("invoice_date")
            if value is not None and hasattr(value, "isoformat"):
                mapped["invoice_date"] = value.isoformat()
            for num_field in ("total_qty_kg", "invoice_amount", "claim_amount"):
                v = mapped.get(num_field)
                if v is not None:
                    mapped[num_field] = float(v)
            data.append(mapped)

        return {"data": data}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Error fetching sales jute MR summary: {e}", exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching sales jute MR summary: {str(e)}",
        )


# =============================================================================
# Sales Order list / Invoice list reports
#
# Two simple, date-range scoped reports surfaced under the Sales Reports page.
# All statuses included (incl. Cancelled) per user requirement — Status column
# is exposed so users can scan visually. JSON variant powers the on-screen
# DataGrid; -download variant streams an xlsx via openpyxl.
# =============================================================================

_SO_LIST_DATE_COLS = ("sales_order_date",)
_SO_LIST_NUM_COLS = ("gross_amount", "net_amount")

_INV_LIST_DATE_COLS = ("invoice_date", "challan_date", "due_date")
_INV_LIST_NUM_COLS = (
    "invoice_amount",
    "tax_amount",
    "tax_payable",
    "round_off",
)


def _serialize_report_row(mapped: dict, date_cols: tuple, num_cols: tuple) -> dict:
    """Convert SQL date/numeric columns to JSON-friendly types."""
    for col in date_cols:
        v = mapped.get(col)
        if v is not None and hasattr(v, "isoformat"):
            mapped[col] = v.isoformat()
    for col in num_cols:
        v = mapped.get(col)
        if v is not None:
            try:
                mapped[col] = float(v)
            except (TypeError, ValueError):
                pass
    return mapped


def _read_list_query_params(request: Request) -> dict:
    """Validate the shared (co_id, branch_id, date_from, date_to) tuple."""
    q_co_id = request.query_params.get("co_id")
    q_branch_id = request.query_params.get("branch_id")
    q_date_from = request.query_params.get("date_from")
    q_date_to = request.query_params.get("date_to")

    if not q_co_id:
        raise HTTPException(status_code=400, detail="co_id is required")
    if not q_date_from:
        raise HTTPException(status_code=400, detail="date_from is required")
    if not q_date_to:
        raise HTTPException(status_code=400, detail="date_to is required")

    try:
        co_id = int(q_co_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid co_id")

    branch_id = None
    if q_branch_id not in (None, ""):
        try:
            branch_id = int(q_branch_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid branch_id")

    return {
        "co_id": co_id,
        "branch_id": branch_id,
        "date_from": _parse_iso_date(q_date_from, "date_from"),
        "date_to": _parse_iso_date(q_date_to, "date_to"),
    }


_SO_XLSX_COLUMNS = [
    ("sales_no", "Sales No"),
    ("sales_no_formatted", "SO Number"),
    ("sales_order_date", "Date"),
    ("branch_name", "Branch"),
    ("party_name", "Party"),
    ("quotation_no", "Quotation No"),
    ("invoice_type", "Invoice Type"),
    ("status_name", "Status"),
    ("approval_level", "Approval Level"),
    ("gross_amount", "Gross Amount"),
    ("net_amount", "Net Amount"),
]

_INV_XLSX_COLUMNS = [
    ("invoice_no", "Invoice No"),
    ("invoice_no_formatted", "Invoice Number"),
    ("invoice_date", "Date"),
    ("branch_name", "Branch"),
    ("party_name", "Party"),
    ("invoice_type", "Invoice Type"),
    ("status_name", "Status"),
    ("approval_level", "Approval Level"),
    ("challan_no", "Challan No"),
    ("challan_date", "Challan Date"),
    ("due_date", "Due Date"),
    ("invoice_amount", "Invoice Amount"),
    ("tax_amount", "Tax Amount"),
    ("tax_payable", "Tax Payable"),
    ("round_off", "Round Off"),
]


def _build_list_xlsx(rows, columns, sheet_title: str) -> BytesIO:
    """Build a single-sheet xlsx with the given columns from row mappings."""
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_title

    ws.append([label for _, label in columns])
    for r in rows:
        mapped = dict(r._mapping)
        out_row = []
        for key, _ in columns:
            v = mapped.get(key)
            if v is not None and hasattr(v, "isoformat"):
                v = v.isoformat()
            out_row.append(v if v is not None else "")
        ws.append(out_row)

    bio = BytesIO()
    wb.save(bio)
    bio.seek(0)
    return bio


@router.get("/sales-order-list")
def get_sales_order_list(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """List of Sales Orders within a date range, JSON for on-screen render."""
    try:
        params = _read_list_query_params(request)
        rows = db.execute(get_sales_order_list_report_query(), params).fetchall()

        data = [
            _serialize_report_row(
                dict(r._mapping), _SO_LIST_DATE_COLS, _SO_LIST_NUM_COLS
            )
            for r in rows
        ]
        if len(data) > _MAX_ROWS:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Result set too large ({len(data)} rows, "
                    f"max {_MAX_ROWS}). Narrow your date range."
                ),
            )
        return {"data": data}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching sales order list report: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching sales order list report: {str(e)}",
        )


@router.get("/sales-order-list-download")
def get_sales_order_list_download(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Excel download of the Sales Orders list report."""
    try:
        params = _read_list_query_params(request)
        rows = db.execute(get_sales_order_list_report_query(), params).fetchall()
        if len(rows) > _MAX_ROWS:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Result set too large ({len(rows)} rows, "
                    f"max {_MAX_ROWS}). Narrow your date range."
                ),
            )
        bio = _build_list_xlsx(rows, _SO_XLSX_COLUMNS, "SalesOrders")
        filename = f"sales_orders_{params['date_from']}_{params['date_to']}.xlsx"
        return StreamingResponse(
            bio,
            media_type=(
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            ),
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Error generating sales order list xlsx: {e}", exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail=f"Error generating sales order list xlsx: {str(e)}",
        )


@router.get("/invoice-list")
def get_invoice_list(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """List of Sales Invoices within a date range, JSON for on-screen render."""
    try:
        params = _read_list_query_params(request)
        rows = db.execute(get_invoice_list_report_query(), params).fetchall()

        data = [
            _serialize_report_row(
                dict(r._mapping), _INV_LIST_DATE_COLS, _INV_LIST_NUM_COLS
            )
            for r in rows
        ]
        if len(data) > _MAX_ROWS:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Result set too large ({len(data)} rows, "
                    f"max {_MAX_ROWS}). Narrow your date range."
                ),
            )
        return {"data": data}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching invoice list report: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching invoice list report: {str(e)}",
        )


@router.get("/invoice-list-download")
def get_invoice_list_download(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Excel download of the Sales Invoices list report."""
    try:
        params = _read_list_query_params(request)
        rows = db.execute(get_invoice_list_report_query(), params).fetchall()
        if len(rows) > _MAX_ROWS:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Result set too large ({len(rows)} rows, "
                    f"max {_MAX_ROWS}). Narrow your date range."
                ),
            )
        bio = _build_list_xlsx(rows, _INV_XLSX_COLUMNS, "Invoices")
        filename = f"sales_invoices_{params['date_from']}_{params['date_to']}.xlsx"
        return StreamingResponse(
            bio,
            media_type=(
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            ),
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Error generating invoice list xlsx: {e}", exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail=f"Error generating invoice list xlsx: {str(e)}",
        )
