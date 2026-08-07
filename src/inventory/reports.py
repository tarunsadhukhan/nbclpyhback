"""
Inventory Report endpoints.
Provides endpoints for inventory stock position and item-wise issue reports.
"""

import logging
from datetime import date
from itertools import groupby
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.inventory.reportQueries import (
    get_inventory_stock_report_query,
    get_inventory_stock_report_count_query,
    get_issue_itemwise_report_query,
    get_issue_itemwise_report_count_query,
    get_item_ledger_opening_query,
    get_item_ledger_txns_query,
    get_inventory_minmax_report_query,
    get_item_monthwise_report_query,
    get_issue_consumption_query,
    consumption_dimension_keys,
    get_issue_machinewise_query,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/inventory-stock")
def get_inventory_stock_report(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    page: int = 1,
    limit: int = 10,
    co_id: int | None = None,
    branch_id: int | None = None,
    item_grp_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    search: str | None = None,
):
    """
    Inventory stock position report.

    Returns one row per item with opening, receipt, issue, and closing
    quantities over a date range.

    Query params:
    - co_id: Company ID (required)
    - branch_id: Branch ID (optional)
    - item_grp_id: Item Group ID (optional)
    - date_from: Start date YYYY-MM-DD (required)
    - date_to: End date YYYY-MM-DD (required)
    - search: Search term for item name, item group
    - page: Page number (default 1)
    - limit: Page size (default 10, max 10000)
    """
    try:
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        if not date_from:
            raise HTTPException(status_code=400, detail="date_from is required")
        if not date_to:
            raise HTTPException(status_code=400, detail="date_to is required")

        page = max(page, 1)
        limit = max(min(limit, 10000), 1)
        offset = (page - 1) * limit

        search_like = None
        if search:
            search_like = f"%{search.strip()}%"

        params = {
            "co_id": int(co_id),
            "branch_id": int(branch_id) if branch_id else None,
            "item_grp_id": int(item_grp_id) if item_grp_id else None,
            "date_from": date_from,
            "date_to": date_to,
            "search_like": search_like,
            "limit": limit,
            "offset": offset,
        }

        list_query = get_inventory_stock_report_query()
        rows = db.execute(list_query, params).fetchall()

        date_to_obj = date.fromisoformat(date_to)
        data = []
        for row in rows:
            mapped = dict(row._mapping)
            # Legacy PHP report drops rows with no movement and no value at all.
            if not any(
                float(mapped.get(f) or 0)
                for f in ("opening_qty", "opening_val", "receipt_qty",
                          "receipt_val", "issue_qty", "issue_val")
            ):
                continue
            closing_qty = float(mapped.get("closing_qty") or 0)
            last_receipt = mapped.get("last_receipt_date")
            last_issue = mapped.get("last_issue_date")
            # Not consumed for (days): 0 when out of stock; else days since the
            # last issue (or last receipt if never issued) — mirrors the legacy
            # PHP stores inventory report.
            if closing_qty <= 0:
                no_days = 0
            else:
                ref_date = last_issue or last_receipt
                no_days = (date_to_obj - ref_date).days if ref_date else None
            data.append({
                "item_id": mapped.get("item_id"),
                "item_code": mapped.get("item_code"),
                "item_name": mapped.get("item_name"),
                "item_grp_name": mapped.get("item_grp_name"),
                "uom_name": mapped.get("uom_name"),
                "opening_qty": mapped.get("opening_qty"),
                "opening_val": mapped.get("opening_val"),
                "receipt_qty": mapped.get("receipt_qty"),
                "receipt_val": mapped.get("receipt_val"),
                "issue_qty": mapped.get("issue_qty"),
                "issue_val": mapped.get("issue_val"),
                "closing_qty": mapped.get("closing_qty"),
                "closing_val": mapped.get("closing_val"),
                "last_receipt_date": last_receipt.isoformat() if last_receipt else None,
                "last_issue_date": last_issue.isoformat() if last_issue else None,
                "no_consumption_days": no_days,
            })

        count_query = get_inventory_stock_report_count_query()
        count_params = {
            "co_id": int(co_id),
            "branch_id": int(branch_id) if branch_id else None,
            "item_grp_id": int(item_grp_id) if item_grp_id else None,
            "date_from": date_from,
            "date_to": date_to,
            "search_like": search_like,
        }
        count_result = db.execute(count_query, count_params).scalar()
        total = int(count_result) if count_result is not None else 0

        return {"data": data, "total": total}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching inventory stock report: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/issue-itemwise")
def get_issue_itemwise_report(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    page: int = 1,
    limit: int = 10,
    co_id: int | None = None,
    branch_id: int | None = None,
    item_grp_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    search: str | None = None,
    dept_id: int | None = None,
    cost_factor_id: int | None = None,
    item_id: int | None = None,
):
    """
    Item-wise issue report (Stores Issue Check List), and the drill-down behind
    the consumption reports.

    Returns one row per issue line item with issue header info,
    item details, department, cost factor, and machine.

    Query params:
    - co_id: Company ID (required)
    - branch_id: Branch ID (optional)
    - item_grp_id: Item Group ID (optional)
    - date_from: Start date YYYY-MM-DD (optional)
    - date_to: End date YYYY-MM-DD (optional)
    - search: Search term for item name, branch name, item group, department
    - dept_id / cost_factor_id / item_id: drill-down filters — the ids of the
      consumption-report row the user opened (all optional)
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
            "item_grp_id": int(item_grp_id) if item_grp_id else None,
            "date_from": date_from if date_from else None,
            "date_to": date_to if date_to else None,
            "search_like": search_like,
            "dept_id": int(dept_id) if dept_id else None,
            "cost_factor_id": int(cost_factor_id) if cost_factor_id else None,
            "item_id": int(item_id) if item_id else None,
            "limit": limit,
            "offset": offset,
        }

        list_query = get_issue_itemwise_report_query()
        rows = db.execute(list_query, params).fetchall()

        data = []
        for row in rows:
            mapped = dict(row._mapping)
            issue_date_obj = mapped.get("issue_date")
            issue_date = issue_date_obj
            if hasattr(issue_date_obj, "isoformat"):
                issue_date = issue_date_obj.isoformat()

            # Format issue number using print_no if available, else pass_no
            issue_no = mapped.get("issue_pass_print_no") or ""
            if not issue_no:
                raw_no = mapped.get("issue_pass_no")
                if raw_no is not None:
                    issue_no = str(raw_no)

            data.append({
                "issue_li_id": mapped.get("issue_li_id"),
                "issue_id": mapped.get("issue_id"),
                "issue_no": issue_no,
                "issue_date": issue_date,
                "branch_name": mapped.get("branch_name"),
                "department": mapped.get("department"),
                "item_code": mapped.get("item_code"),
                "item_name": mapped.get("item_name"),
                "item_grp_name": mapped.get("item_grp_name"),
                "uom_name": mapped.get("uom_name"),
                "req_quantity": mapped.get("req_quantity"),
                "issue_qty": mapped.get("issue_qty"),
                "issue_value": mapped.get("issue_value"),
                "sr_no": mapped.get("sr_no"),
                "expense_type_name": mapped.get("expense_type_name"),
                "cost_factor_name": mapped.get("cost_factor_name"),
                "machine_name": mapped.get("machine_name"),
                "status_name": mapped.get("status_name"),
            })

        count_query = get_issue_itemwise_report_count_query()
        # Same filters as the list query minus paging, so the count matches the
        # rows actually returned (including any drill-down filters).
        count_params = {
            k: v for k, v in params.items() if k not in ("limit", "offset")
        }
        count_result = db.execute(count_query, count_params).scalar()
        total = int(count_result) if count_result is not None else 0

        return {"data": data, "total": total}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching issue itemwise report: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/item-ledger")
async def get_item_ledger_report(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    co_id: int | None = None,
    item_id: int | None = None,
    branch_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
):
    """
    Item ledger (quantity) for a single item.

    Returns the opening balance and one row per source document (receipts +
    issues) within the date range, chronologically ordered, plus a running
    balance. Value/amount columns are not included (issue costs are not stored
    in the schema).

    Query params:
    - co_id: Company ID (required)
    - item_id: Item ID (required)
    - branch_id: Branch ID (optional)
    - date_from: Start date YYYY-MM-DD (required)
    - date_to: End date YYYY-MM-DD (required)
    """
    try:
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        if not item_id:
            raise HTTPException(status_code=400, detail="item_id is required")
        if not date_from:
            raise HTTPException(status_code=400, detail="date_from is required")
        if not date_to:
            raise HTTPException(status_code=400, detail="date_to is required")

        params = {
            "co_id": int(co_id),
            "item_id": int(item_id),
            "branch_id": int(branch_id) if branch_id else None,
            "date_from": date_from,
            "date_to": date_to,
        }

        opening_row = db.execute(
            get_item_ledger_opening_query(),
            {k: params[k] for k in ("co_id", "item_id", "branch_id", "date_from")},
        ).fetchone()
        opening_map = dict(opening_row._mapping) if opening_row else {}
        opening_qty = float(opening_map.get("opening_qty") or 0)
        opening_val = float(opening_map.get("opening_val") or 0)

        rows = db.execute(get_item_ledger_txns_query(), params).fetchall()

        balance = opening_qty
        balance_val = opening_val
        data = []
        for row in rows:
            mapped = dict(row._mapping)
            txn_date_obj = mapped.get("txn_date")
            txn_date = txn_date_obj
            if hasattr(txn_date_obj, "isoformat"):
                txn_date = txn_date_obj.isoformat()
            in_qty = float(mapped.get("in_qty") or 0)
            out_qty = float(mapped.get("out_qty") or 0)
            in_val = float(mapped.get("in_val") or 0)
            out_val = float(mapped.get("out_val") or 0)
            balance = balance + in_qty - out_qty
            balance_val = balance_val + in_val - out_val
            data.append({
                "txn_date": txn_date,
                "txn_type": mapped.get("txn_type"),
                "ref_no": mapped.get("ref_no"),
                "in_qty": in_qty,
                "in_val": round(in_val, 2),
                "out_qty": out_qty,
                "out_val": round(out_val, 2),
                "balance": balance,
                "balance_val": round(balance_val, 2),
            })

        return {
            "opening_qty": opening_qty,
            "opening_val": round(opening_val, 2),
            "data": data,
            "total": len(data),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching item ledger report: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/inventory-minmax")
async def get_inventory_minmax_report(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    page: int = 1,
    limit: int = 10000,
    co_id: int | None = None,
    branch_id: int | None = None,
    item_grp_id: int | None = None,
    date_to: str | None = None,
    search: str | None = None,
):
    """
    Stores min-max report: items with active min-max levels for the branch, their
    reorder levels, and current stock as of date_to (with a Below Min / Above Max
    / OK status). branch_id is required (levels are per branch).

    Query params: co_id (required), branch_id (required), date_to (required),
    item_grp_id (optional), search (optional).
    """
    try:
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        if not branch_id:
            raise HTTPException(status_code=400, detail="branch_id is required")
        if not date_to:
            raise HTTPException(status_code=400, detail="date_to is required")

        page = max(page, 1)
        limit = max(min(limit, 10000), 1)
        offset = (page - 1) * limit
        search_like = f"%{search.strip()}%" if search else None

        rows = db.execute(get_inventory_minmax_report_query(), {
            "co_id": int(co_id),
            "branch_id": int(branch_id),
            "item_grp_id": int(item_grp_id) if item_grp_id else None,
            "date_to": date_to,
            "search_like": search_like,
            "limit": limit,
            "offset": offset,
        }).fetchall()

        data = []
        for row in rows:
            m = dict(row._mapping)
            current = float(m.get("current_qty") or 0)
            minq = m.get("minqty")
            maxq = m.get("maxqty")
            pending_indent = float(m.get("pending_indent_qty") or 0)
            pending_po = float(m.get("pending_po_qty") or 0)
            status = "OK"
            if minq is not None and current < float(minq):
                status = "Below Min"
            elif maxq is not None and current > float(maxq):
                status = "Above Max"
            # Qty to be ordered (legacy PHP rule): when stock + pending PO is
            # below min, order up to max.
            qty_to_order = 0.0
            if (
                minq is not None
                and maxq is not None
                and (current + pending_po) < float(minq)
            ):
                qty_to_order = max(float(maxq) - current - pending_po, 0.0)
            data.append({
                "item_id": m.get("item_id"),
                "item_code": m.get("item_code"),
                "item_name": m.get("item_name"),
                "item_grp_name": m.get("item_grp_name"),
                "uom_name": m.get("uom_name"),
                "min_qty": minq,
                "max_qty": maxq,
                "reorder_qty": m.get("min_order_qty"),
                "lead_time": m.get("lead_time"),
                "current_qty": current,
                "pending_indent_qty": round(pending_indent, 3),
                "pending_po_qty": round(pending_po, 3),
                "qty_to_be_ordered": round(qty_to_order, 3),
                "status": status,
            })

        return {"data": data, "total": len(data)}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching min-max report: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


def _month_range(date_from: str, date_to: str) -> list[str]:
    """Inclusive list of YYYY-MM strings spanning the two dates."""
    y, m = int(date_from[:4]), int(date_from[5:7])
    ey, em = int(date_to[:4]), int(date_to[5:7])
    out = []
    while (y, m) <= (ey, em):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1
    return out


@router.get("/item-monthwise")
async def get_item_monthwise_report(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    co_id: int | None = None,
    branch_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
):
    """
    Item month-wise consumption. Returns the ordered list of months in range and
    one row per item with issue qty per month plus Total, Months (# of months
    with consumption), and Avg.

    Query params: co_id (required), date_from (required), date_to (required),
    branch_id (optional).
    """
    try:
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        if not date_from:
            raise HTTPException(status_code=400, detail="date_from is required")
        if not date_to:
            raise HTTPException(status_code=400, detail="date_to is required")

        months = _month_range(date_from, date_to)

        rows = db.execute(get_item_monthwise_report_query(), {
            "co_id": int(co_id),
            "branch_id": int(branch_id) if branch_id else None,
            "date_from": date_from,
            "date_to": date_to,
        }).fetchall()

        # Pivot: one dict per item, month qty keyed by YYYY-MM.
        items: dict[int, dict] = {}
        for row in rows:
            m = dict(row._mapping)
            item_id = m.get("item_id")
            entry = items.get(item_id)
            if entry is None:
                entry = {
                    "item_id": item_id,
                    "item_name": m.get("item_name"),
                    "item_grp_name": m.get("item_grp_name"),
                    "uom_name": m.get("uom_name"),
                }
                for ym in months:
                    entry[ym] = 0.0
                items[item_id] = entry
            ym = m.get("ym")
            if ym in entry:
                entry[ym] = float(m.get("qty") or 0)

        data = []
        for entry in items.values():
            total = sum(entry[ym] for ym in months)
            active = sum(1 for ym in months if entry[ym] > 0)
            entry["total"] = round(total, 3)
            entry["active_months"] = active
            entry["avg"] = round(total / active, 3) if active else 0.0
            data.append(entry)

        return {"months": months, "data": data, "total": len(data)}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching item month-wise report: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# dev3 expense_type_mst name -> output field. "Mantainence" is dev3's spelling.
_CONSUMPTION_CATEGORIES = [
    ("Production", "production"),
    ("Overhauling", "overhauling"),
    ("Mantainence", "maintenance"),   # spelled this way in expense_type_mst
    ("Capital", "capital"),
    ("General", "general"),
]

# Issue lines with no expense type (or one outside the list above) land here.
# Without it their value was dropped from the pivot entirely, so the report
# under-reported against the Stores Issue Check List.
_CONSUMPTION_OTHER_FIELD = "others"

_CONSUMPTION_VALUE_FIELDS = (
    [f for _, f in _CONSUMPTION_CATEGORIES] + [_CONSUMPTION_OTHER_FIELD, "total"]
)


def _consumption_subtotal(rows: list[dict], **labels) -> dict:
    """Summary line over `rows`. The label cell must read exactly "Total" —
    that is what ReportGrid/exportExcel match on to style a summary row."""
    row = {"department": "", "cost_factor": "", "item_code": "", "item_name": ""}
    row.update(labels)
    for f in _CONSUMPTION_VALUE_FIELDS:
        row[f] = round(sum(r[f] for r in rows), 2)
    return row


def _consumption_with_subtotals(data: list[dict]) -> list[dict]:
    """IS01 reads as a printed statement: a Total line after every cost centre
    and after every department. Relies on `data` already being sorted by
    department then cost centre, so each group is contiguous."""
    out: list[dict] = []
    for dept, dept_rows in groupby(data, key=lambda r: r.get("department")):
        dept_rows = list(dept_rows)
        for cf, cf_rows in groupby(dept_rows, key=lambda r: r.get("cost_factor")):
            cf_rows = list(cf_rows)
            out.extend(cf_rows)
            out.append(_consumption_subtotal(cf_rows, cost_factor=cf, item_name="Total"))
        out.append(_consumption_subtotal(dept_rows, department=dept, cost_factor="Total"))
    return out


@router.get("/issue-consumption")
async def get_issue_consumption_report(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    dimension: str = "dept",
    co_id: int | None = None,
    branch_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    item_code: str | None = None,
):
    """
    Issue consumption value pivoted into expense categories (Production,
    Overhauling, Maintenance, Capital, General) + Total, grouped by dimension.

    dimension: 'dept' (IS03) | 'dept_cost' (IS02) | 'dept_cost_item' (IS01) |
    'item_group' (IS06). Issues valued at receipt-lot rate. Query params: co_id
    (required), date_from, date_to (required), branch_id (optional), item_code
    (optional partial match).
    """
    try:
        if dimension not in ("dept", "dept_cost", "dept_cost_item", "item_group"):
            raise HTTPException(status_code=400, detail="invalid dimension")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        if not date_from or not date_to:
            raise HTTPException(status_code=400, detail="date_from and date_to are required")

        keys = consumption_dimension_keys(dimension)
        code = (item_code or "").strip() or None
        rows = db.execute(get_issue_consumption_query(dimension), {
            "co_id": int(co_id),
            "branch_id": int(branch_id) if branch_id else None,
            "date_from": date_from,
            "date_to": date_to,
            "item_code": code,
            # Prefix match: typing "172" lists every item code starting 172.
            "item_code_like": f"{code}%" if code else None,
        }).fetchall()

        name_to_field = {name: field for name, field in _CONSUMPTION_CATEGORIES}
        groups: dict = {}
        for row in rows:
            m = dict(row._mapping)
            key = tuple(m.get(k) for k in keys)
            entry = groups.get(key)
            if entry is None:
                entry = {k: m.get(k) for k in keys}
                # Ids for the drill-down (present only on dimensions that
                # select them); the frontend passes these back to the
                # issue-itemwise endpoint.
                for id_field in ("dept_id", "cost_factor_id", "item_id", "dept_order"):
                    if id_field in m:
                        entry[id_field] = m[id_field]
                for _, field in _CONSUMPTION_CATEGORIES:
                    entry[field] = 0.0
                entry[_CONSUMPTION_OTHER_FIELD] = 0.0
                groups[key] = entry
            field = name_to_field.get(m.get("category")) or _CONSUMPTION_OTHER_FIELD
            entry[field] += float(m.get("value") or 0)

        data = []
        for entry in groups.values():
            entry["total"] = round(
                sum(entry[field] for _, field in _CONSUMPTION_CATEGORIES)
                + entry[_CONSUMPTION_OTHER_FIELD], 2
            )
            data.append(entry)

        # Stable order — the pivot query has no ORDER BY, and the Grand Total
        # below only reads correctly as the last row. Departments go by
        # dept_mst.order_id (absent on the item_group dimension, where the key
        # sort alone applies).
        data.sort(key=lambda e: (
            e.get("dept_order") or 0,
            tuple((e.get(k) or "") for k in keys),
        ))

        detail = data  # summed for the Grand Total — never the subtotal lines
        if dimension == "dept_cost_item":
            data = _consumption_with_subtotals(data)

        # Grand Total row: labelled in the first key column, the rest blank, so
        # ReportGrid/exportExcel pick it up as a total row and style it.
        if detail:
            grand = {k: "" for k in keys}
            grand[keys[0]] = "Grand Total"
            for field in [f for _, f in _CONSUMPTION_CATEGORIES] + [_CONSUMPTION_OTHER_FIELD]:
                grand[field] = round(sum(e[field] for e in detail), 2)
            grand["total"] = round(sum(e["total"] for e in detail), 2)
            data.append(grand)

        return {"dimensions": keys, "data": data, "total": len(data)}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching issue consumption report: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/issue-machinewise")
async def get_issue_machinewise_report(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    co_id: int | None = None,
    branch_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
):
    """
    Machine-wise item consumption (IS05): issue qty + value per machine and item
    (issues tagged to a machine). Value = issue_qty * receipt-lot rate.

    Query params: co_id (required), date_from, date_to (required), branch_id (optional).
    """
    try:
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        if not date_from or not date_to:
            raise HTTPException(status_code=400, detail="date_from and date_to are required")

        rows = db.execute(get_issue_machinewise_query(), {
            "co_id": int(co_id),
            "branch_id": int(branch_id) if branch_id else None,
            "date_from": date_from,
            "date_to": date_to,
        }).fetchall()

        data = []
        for i, row in enumerate(rows):
            m = dict(row._mapping)
            data.append({
                "id": i,
                "machine_name": m.get("machine_name"),
                "department": m.get("department"),
                "item_code": m.get("item_code"),
                "item_grp_name": m.get("item_grp_name"),
                "item_name": m.get("item_name"),
                "uom_name": m.get("uom_name"),
                "expense_type_name": m.get("expense_type_name"),
                "issue_qty": float(m.get("issue_qty") or 0),
                "issue_value": float(m.get("issue_value") or 0),
            })

        return {"data": data, "total": len(data)}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching machine-wise report: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
