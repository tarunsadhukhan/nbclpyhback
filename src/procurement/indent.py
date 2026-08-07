from fastapi import Depends, Request, HTTPException, APIRouter
from fastapi.responses import StreamingResponse
import os
import logging
from sqlalchemy.orm import Session
from sqlalchemy.sql import text
from src.config.db import get_db_names, default_engine, get_tenant_db
from src.authorization.utils import  get_current_user_with_refresh
# from src.masters.schemas import MenuResponse
from src.masters.models import CostFactorMst
from src.masters.query import  get_branch_list, get_dept_list_by_branch_id, get_item_group_drodown
from src.procurement.query import (
	get_project,
	get_expense_types,
	get_item_by_group_id_purchaseable,
	get_item_make_by_group_id,
	get_item_uom_by_group_id,
	insert_proc_indent,
	insert_proc_indent_detail,
	get_indent_table_query,
	get_indent_table_count_query,
	get_indent_by_id_query,
	get_indent_detail_by_id_query,
	update_proc_indent,
	update_proc_indent_detail,
	delete_proc_indent_detail,
	get_approval_flow_by_menu_branch,
	update_indent_status,
	get_indent_with_approval_info,
	get_max_indent_no_for_branch_fy,
	get_all_approved_indents_query,
	get_item_validation_data_v2,
	get_indent_item_outstanding,
	get_item_fy_indent_check_v2,
	get_expense_type_name_by_id,
	get_distinct_indent_titles,
	get_latest_indent_lines_by_title,
)
from src.procurement.constants import (
	INDENT_TYPES,
	VALID_INDENT_TYPE_VALUES,
	normalize_indent_type,
	is_valid_indent_type,
)
from src.common.approval_utils import (
	process_approval,
	process_rejection,
	calculate_approval_permissions,
)
from src.common.approval_query import get_max_approval_level
from datetime import datetime, date
from typing import Optional
from src.common.utils import now_ist
import math
from src.procurement.export_helpers import build_xlsx, build_pdf
from src.common.utils import parse_json_body


_INDENT_XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_INDENT_PDF_MEDIA_TYPE = "application/pdf"
_INDENT_DOWNLOAD_MAX_ROWS = 50000

logger = logging.getLogger(__name__)

router = APIRouter()


# =============================================================================
# VALIDATION HELPERS
# =============================================================================

# Mapping: (indent_type, expense_type_name) -> validation logic
# Logic 1: Max/Min Quantity Validation with Stock Check
# Logic 2: FY Check + max qty as forced value (requires min/max)
# Logic 3: No Validation / Free Entry
VALIDATION_LOGIC_MAP = {
    # Regular indent
    ("Regular", "General"): 1,
    ("Regular", "Maintenance"): 1,
    ("Regular", "Production"): 1,
    ("Regular", "Overhaul"): 1,
    ("Regular", "Capital"): 2,
    # Open indent — free entry, no validation
    ("Open", "General"): 3,
    ("Open", "Maintenance"): 3,
    ("Open", "Production"): 3,
    # BOM indent
    ("BOM", "General"): 1,
    ("BOM", "Maintenance"): 1,
    ("BOM", "Production"): 1,
    ("BOM", "Capital"): 2,
    ("BOM", "Overhaul"): 2,
}


def determine_validation_logic(indent_type: str, expense_type_name: str) -> int:
    """Determine which validation logic applies based on indent type + expense type."""
    return VALIDATION_LOGIC_MAP.get((indent_type, expense_type_name), 3)


def get_fy_boundaries(doc_date):
    """Calculate financial year start/end dates (April 1 → March 31)."""
    if isinstance(doc_date, str):
        doc_date = datetime.strptime(doc_date, "%Y-%m-%d").date()
    elif hasattr(doc_date, "date") and callable(doc_date.date):
        doc_date = doc_date.date()
    year = doc_date.year
    month = doc_date.month
    if month >= 4:
        return date(year, 4, 1), date(year + 1, 3, 31)
    else:
        return date(year - 1, 4, 1), date(year, 3, 31)


def calculate_max_indent_qty(
    maxqty: float,
    branch_stock: float,
    outstanding_indent_qty: float,
    min_order_qty: float,
) -> float | None:
    """
    DEPRECATED: This calculation is now pre-computed in the database view
    `vw_item_balance_qty_by_branch_new` as column `max_indent_qty`.
    Kept for backward compatibility and rollback safety.

    Original formula:
    available = max_qty - branch_stock - outstanding_indent_qty
    If available < reorder_qty → reorder_qty
    Else → ROUNDUP(available / reorder_qty) * reorder_qty
    Returns None if min_order_qty is 0/None (cannot compute).
    """
    if not min_order_qty or min_order_qty <= 0:
        # No reorder qty defined — cannot apply formula, allow any value
        return None
    available = maxqty - branch_stock - outstanding_indent_qty
    if available <= 0:
        return None  # No room to indent
    if available < min_order_qty:
        return min_order_qty
    return math.ceil(available / min_order_qty) * min_order_qty


@router.get("/validate_item_for_indent")
def validate_item_for_indent(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Validate an item for indent creation.
    Returns validation data including errors, warnings, and allowable qty range
    based on (indent_type + expense_type) → Logic 1, 2, or 3.

    Query params:
        branch_id       : int  (required)
        item_id         : int  (required)
        indent_type     : str  (required) — Regular | BOM | Open | Capital | Maintenance
        expense_type_id : int  (required)
        indent_date     : str  (optional, YYYY-MM-DD) — date selected by user for the indent;
                          used to derive the correct financial year for FY duplicate checks.
                          Defaults to today if omitted.
    """
    try:
        branch_id = request.query_params.get("branch_id")
        item_id = request.query_params.get("item_id")
        indent_type = request.query_params.get("indent_type")
        expense_type_id = request.query_params.get("expense_type_id")
        indent_date_str = request.query_params.get("indent_date")
        indent_id = request.query_params.get("indent_id")  # optional: exclude self when editing

        if not branch_id:
            raise HTTPException(status_code=400, detail="branch_id is required")
        if not item_id:
            raise HTTPException(status_code=400, detail="item_id is required")
        if not indent_type:
            raise HTTPException(status_code=400, detail="indent_type is required")
        if not expense_type_id:
            raise HTTPException(status_code=400, detail="expense_type_id is required")

        try:
            branch_id = int(branch_id)
            item_id = int(item_id)
            expense_type_id = int(expense_type_id)
        except (TypeError, ValueError) as e:
            raise HTTPException(status_code=400, detail=f"Invalid parameter format: {e}")

        # Derive the reference date for FY boundary calculation.
        # Use the user-supplied indent_date if provided; fall back to today.
        if indent_date_str:
            try:
                ref_date = datetime.strptime(indent_date_str, "%Y-%m-%d").date()
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid indent_date format '{indent_date_str}'. Expected YYYY-MM-DD.",
                )
        else:
            ref_date = date.today()

        indent_type = normalize_indent_type(indent_type)
        if not is_valid_indent_type(indent_type):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid indent_type '{indent_type}'",
            )

        # Resolve expense type name
        expense_row = db.execute(
            get_expense_type_name_by_id(),
            {"expense_type_id": expense_type_id},
        ).fetchone()
        if not expense_row:
            raise HTTPException(status_code=400, detail=f"Invalid expense_type_id: {expense_type_id}")
        expense_type_name = dict(expense_row._mapping)["expense_type_name"]

        validation_logic = determine_validation_logic(indent_type, expense_type_name)

        fy_start, fy_end = get_fy_boundaries(ref_date)

        result = {
            "validation_logic": validation_logic,
            "indent_type": indent_type,
            "expense_type_name": expense_type_name,
            # The reference date and FY used for duplicate-indent checks
            "indent_date": ref_date.strftime("%Y-%m-%d"),
            "fy_start": fy_start.strftime("%Y-%m-%d"),
            "fy_end": fy_end.strftime("%Y-%m-%d"),
            "errors": [],
            "warnings": [],
            # Logic 1 fields
            "branch_stock": None,
            "outstanding_indent_qty": None,
            "minqty": None,
            "maxqty": None,
            "min_order_qty": None,
            "has_open_indent": False,
            "stock_exceeds_max": False,
            "max_indent_qty": None,
            "min_indent_qty": None,
            # Logic 2 fields
            "fy_indent_exists": False,
            "fy_indent_no": None,
            "has_minmax": False,
            "regular_bom_outstanding": None,
            "forced_qty": None,
        }

        if validation_logic == 3:
            # No validation — free entry
            return result

        # Fetch common validation data from the pre-aggregated view
        vdata_row = db.execute(
            get_item_validation_data_v2(),
            {"branch_id": branch_id, "item_id": item_id},
        ).fetchone()

        vdata = dict(vdata_row._mapping) if vdata_row else {}
        branch_stock = float(vdata.get("branch_stock") or 0)
        outstanding = float(vdata.get("outstanding_indent_qty") or 0)
        regular_bom_outstanding_val = float(vdata.get("regular_bom_outstanding") or 0)
        minqty = vdata.get("minqty")
        maxqty = vdata.get("maxqty")
        min_order_qty = vdata.get("min_order_qty")
        # Pre-computed validation limits from the view (sentinel: -2=open outstanding, -1=no minmax, >=0=limit)
        view_max_indent = float(vdata.get("max_indent_qty", -1))
        view_min_indent = float(vdata.get("min_indent_qty", -1))

        # When editing an existing indent, the view's max_indent_qty already
        # includes this indent's own outstanding in the deduction. We need to
        # add it back so the user can keep/adjust their current qty.
        self_outstanding = 0.0
        if indent_id:
            self_row = db.execute(
                get_indent_item_outstanding(),
                {"branch_id": branch_id, "item_id": item_id, "indent_id": int(indent_id)},
            ).fetchone()
            if self_row:
                self_outstanding = float(dict(self_row._mapping).get("indent_outstanding") or 0)
            outstanding -= self_outstanding
            regular_bom_outstanding_val -= self_outstanding
            # Add self-outstanding back to the view's pre-computed max
            if view_max_indent >= 0 and self_outstanding > 0:
                view_max_indent += self_outstanding

        result["branch_stock"] = branch_stock
        result["outstanding_indent_qty"] = outstanding
        result["minqty"] = float(minqty) if minqty is not None else None
        result["maxqty"] = float(maxqty) if maxqty is not None else None
        result["min_order_qty"] = float(min_order_qty) if min_order_qty is not None else None

        if validation_logic == 1:
            # --- Logic 1: Max/Min + Stock Check ---
            # Pre-computed view columns handle sentinel values:
            #   -2 = open indent outstanding exists (warning)
            #   -1 = no minmax configured (free entry)
            #   >= 0 = computed limit (enforce)

            # Step 1: Check if an Open-type indent (indent_type = 'Open') already exists for
            # this item in the current financial year. Open-type indents are blanket/standing
            # orders — if one is active for the item, a new Regular indent should be blocked.
            # (fy_start / fy_end already derived from ref_date above)
            fy_open_row = db.execute(
                get_item_fy_indent_check_v2(),
                {
                    "branch_id": branch_id,
                    "item_id": item_id,
                    "fy_start": fy_start,
                    "fy_end": fy_end,
                },
            ).fetchone()

            if fy_open_row:
                fy_open_data = dict(fy_open_row._mapping)
                result["has_open_indent"] = True
                result["fy_indent_exists"] = True
                result["fy_indent_no"] = fy_open_data.get("indent_no")
                result["errors"].append(
                    f"An Open-type indent (#{fy_open_data.get('indent_no')}) already exists for this item "
                    f"in the current financial year ({fy_start.strftime('%d-%b-%Y')} to {fy_end.strftime('%d-%b-%Y')})."
                )

            # Step 2: Use pre-computed max/min from view with sentinel handling
            if view_max_indent == -2:
                # Sentinel: open indent outstanding exists — warn but allow
                result["has_open_indent"] = True
                result["has_minmax"] = True
                result["max_indent_qty"] = None  # Cannot determine — open outstanding muddies the picture
                result["min_indent_qty"] = None
                result["warnings"].append(
                    f"Open indent outstanding ({float(vdata.get('open_indent_outstanding', 0))}) exists "
                    f"for this item. Max indent qty cannot be precisely calculated."
                )
            elif view_max_indent == -1:
                # No max qty configured — per Logic 1, user may enter any value
                result["has_minmax"] = False
                # No error — free entry allowed when min/max not configured for Logic 1
            elif view_max_indent == 0:
                # Computed limit is zero — stock + outstanding already meets/exceeds max
                result["has_minmax"] = True
                result["stock_exceeds_max"] = True
                result["max_indent_qty"] = 0
                result["min_indent_qty"] = view_min_indent if view_min_indent >= 0 else None
                result["errors"].append(
                    f"Branch stock ({branch_stock}) + outstanding indent qty ({outstanding}) "
                    f"meets or exceeds max qty ({float(maxqty) if maxqty else 0}). Cannot create indent."
                )
            else:
                # view_max_indent > 0: valid computed limit
                result["has_minmax"] = True
                result["max_indent_qty"] = view_max_indent
                result["min_indent_qty"] = view_min_indent if view_min_indent >= 0 else None

        elif validation_logic == 2:
            # --- Logic 2: Open Entry + FY Check ---

            # Step 1: Check for existing open indent in FY derived from ref_date
            # (fy_start / fy_end already derived from ref_date above)
            fy_row = db.execute(
                get_item_fy_indent_check_v2(),
                {
                    "branch_id": branch_id,
                    "item_id": item_id,
                    "fy_start": fy_start,
                    "fy_end": fy_end,
                },
            ).fetchone()

            if fy_row:
                fy_data = dict(fy_row._mapping)
                result["fy_indent_exists"] = True
                result["fy_indent_no"] = fy_data.get("indent_no")
                result["errors"].append(
                    f"An open indent (#{fy_data.get('indent_no')}) already exists for this item "
                    f"in the current financial year ({fy_start.strftime('%d-%b-%Y')} to {fy_end.strftime('%d-%b-%Y')})."
                )

            # Step 2: Check if max/min exists
            if maxqty is None and minqty is None:
                result["has_minmax"] = False
                result["errors"].append(
                    "No max/min quantity defined for this item. Cannot create indent with forced quantity."
                )
            else:
                result["has_minmax"] = True

            # Step 3: Check Regular/BOM outstanding (warning only)
            # Already fetched from the aggregate view (regular_bom_outstanding_val)
            result["regular_bom_outstanding"] = regular_bom_outstanding_val
            if regular_bom_outstanding_val > 0:
                result["warnings"].append(
                    f"Outstanding indent qty ({regular_bom_outstanding_val}) exists from Regular/BOM indents for this item."
                )

            # Step 4: Force qty to maxqty
            if maxqty is not None:
                result["forced_qty"] = float(maxqty)

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error validating item for indent")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_indent_setup_1")
def get_indent_setup_1(
	request: Request,
	db: Session = Depends(get_tenant_db),
	token_data: dict = Depends(get_current_user_with_refresh),
	branch_id: int | None = None,
	co_id: int | None = None,
):
	"""Return branches, departments, projects, expense types and item groups for given branch_id and co_id."""
	try:
		# prefer query params if provided in request
		q_branch_id = request.query_params.get("branch_id")
		q_co_id = request.query_params.get("co_id")
		if q_branch_id is not None:
			try:
				branch_id = int(q_branch_id)
			except Exception:
				raise HTTPException(status_code=400, detail="Invalid branch_id")
		if q_co_id is not None:
			try:
				co_id = int(q_co_id)
			except Exception:
				raise HTTPException(status_code=400, detail="Invalid co_id")

		if co_id is None:
			raise HTTPException(status_code=400, detail="co_id is required")

		# Branch list: if branch_id provided, pass as single-element list, else let helper fetch all
		branch_ids_list = [branch_id] if branch_id is not None else None
		branchquery = get_branch_list(branch_ids=branch_ids_list) if branch_ids_list else get_branch_list()
		branch_result = db.execute(branchquery, {"branch_ids": branch_ids_list} if branch_ids_list else {}).fetchall()
		branches = [dict(r._mapping) for r in branch_result]

		# Departments for the branch(s)
		dept_query = get_dept_list_by_branch_id(branch_ids_list if branch_ids_list is not None else [])
		dept_result = db.execute(dept_query, {"branch_ids": branch_ids_list, "co_id": co_id}).fetchall()
		departments = [dict(r._mapping) for r in dept_result]

		# Projects (expects branch_id)
		projects = []
		if branch_id is not None:
			project_query = get_project(branch_id=branch_id)
			proj_result = db.execute(project_query, {"branch_id": branch_id}).fetchall()
			projects = [dict(r._mapping) for r in proj_result]

		# Expense types
		expense_query = get_expense_types()
		exp_result = db.execute(expense_query).fetchall()
		expense_types = [dict(r._mapping) for r in exp_result]

		# Item group dropdown (expects co_id)
		itemgrp_query = get_item_group_drodown(co_id=co_id)
		itemgrp_result = db.execute(itemgrp_query, {"co_id": co_id}).fetchall()
		item_groups = [dict(r._mapping) for r in itemgrp_result]

		# Indent title suggestions (scoped by co_id + branch_id)
		indent_titles = []
		try:
			title_query = get_distinct_indent_titles()
			title_result = db.execute(
				title_query,
				{"co_id": co_id, "branch_id": branch_id},
			).fetchall()
			indent_titles = [
				dict(r._mapping)["indent_title"]
				for r in title_result
				if dict(r._mapping).get("indent_title")
			]
		except Exception:
			# Non-critical — return empty list and proceed
			pass

		return {
			"branches": branches,
			"departments": departments,
			"projects": projects,
			"expense_types": expense_types,
			"item_groups": item_groups,
			"indent_titles": indent_titles,
		}
	except HTTPException:
		raise
	except Exception as e:
		raise HTTPException(status_code=500, detail=str(e))
	

@router.get("/get_indent_setup_2")
def get_indent_setup_2(
	request: Request,
	db: Session = Depends(get_tenant_db),
	token_data: dict = Depends(get_current_user_with_refresh),
):
	"""Return additional setup data for indents."""
	try:
		# Expecting an item_group param in the request (query param or JSON body)
		q_item_group = request.query_params.get("item_group")
		# if client sends JSON body for GET (non-standard), try reading it
		if q_item_group is None:
			try:
				body = parse_json_body(request)
				q_item_group = body.get("item_group") if isinstance(body, dict) else None
			except Exception:
				q_item_group = None

		if q_item_group is None:
			raise HTTPException(status_code=400, detail="item_group is required")

		try:
			item_group_id = int(q_item_group)
		except Exception:
			raise HTTPException(status_code=400, detail="Invalid item_group")

		# get items purchasable in this group
		items_query = get_item_by_group_id_purchaseable(item_group_id=item_group_id)
		items_result = db.execute(items_query, {"item_group_id": item_group_id}).fetchall()
		items = [dict(r._mapping) for r in items_result]

		# get item makes for this group
		makes_query = get_item_make_by_group_id(item_group_id=item_group_id)
		makes_result = db.execute(makes_query, {"item_group_id": item_group_id}).fetchall()
		makes = [dict(r._mapping) for r in makes_result]

		# get item uom mappings for this group
		uoms_query = get_item_uom_by_group_id(item_group_id=item_group_id)
		uoms_result = db.execute(uoms_query, {"item_group_id": item_group_id}).fetchall()
		uoms = [dict(r._mapping) for r in uoms_result]


		return {
			"items": items,
			"makes": makes,
			"uoms": uoms,
		}
	except HTTPException:
		raise
	except Exception as e:
		raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_indent_lines_by_title")
def get_indent_lines_by_title(
	request: Request,
	db: Session = Depends(get_tenant_db),
	token_data: dict = Depends(get_current_user_with_refresh),
):
	"""Return line items from the most recent indent matching the given indent_title,
	co_id and branch_id.  Used by the frontend to pre-fill line items when the user
	selects an existing indent name (template reuse)."""
	try:
		q_co_id = request.query_params.get("co_id")
		q_branch_id = request.query_params.get("branch_id")
		q_indent_title = request.query_params.get("indent_title")

		if not q_co_id:
			raise HTTPException(status_code=400, detail="co_id is required")
		if not q_branch_id:
			raise HTTPException(status_code=400, detail="branch_id is required")
		if not q_indent_title or not q_indent_title.strip():
			raise HTTPException(status_code=400, detail="indent_title is required")

		try:
			co_id = int(q_co_id)
			branch_id = int(q_branch_id)
		except (TypeError, ValueError):
			raise HTTPException(status_code=400, detail="Invalid co_id or branch_id format")

		indent_title = q_indent_title.strip()

		query = get_latest_indent_lines_by_title()
		result = db.execute(query, {
			"co_id": co_id,
			"branch_id": branch_id,
			"indent_title": indent_title,
		}).fetchall()

		if not result:
			return {"data": {"indent_id": None, "lines": []}}

		# The query orders by indent_id DESC — all rows from the most recent
		# indent share the same indent_id (via the INNER JOIN).  However the
		# query may return rows from multiple matching indents, so we only
		# keep lines belonging to the first (= most recent) indent.
		rows = [dict(r._mapping) for r in result]

		lines = []
		for row in rows:
			lines.append({
				"id": str(row.get("indent_dtl_id", "")),
				"department": str(row["dept_id"]) if row.get("dept_id") else None,
				"itemGroup": str(row["item_grp_id"]) if row.get("item_grp_id") else "",
				"item": str(row["item_id"]) if row.get("item_id") else "",
				"itemMake": str(row["item_make_id"]) if row.get("item_make_id") else None,
				"quantity": float(row["qty"]) if row.get("qty") is not None else None,
				"uom": str(row["uom_id"]) if row.get("uom_id") else "",
				"remarks": str(row["remarks"]) if row.get("remarks") else None,
			})

		return {"data": {"lines": lines}}

	except HTTPException:
		raise
	except Exception as e:
		raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_indent_table")
def get_indent_table(
	request: Request,
	db: Session = Depends(get_tenant_db),
	token_data: dict = Depends(get_current_user_with_refresh),
	page: int = 1,
	limit: int = 10,
	search: str | None = None,
	co_id: int | None = None,
	branch_id: int | None = None,
):
	"""Return paginated procurement indent list filtered by branch_id if provided."""

	try:
		page = max(page, 1)
		limit = max(min(limit, 100), 1)
		offset = (page - 1) * limit
		search_like = None
		if search:
			search_like = f"%{search.strip()}%"

		params = {
			"co_id": co_id,
			"branch_id": branch_id,
			"search_like": search_like,
			"limit": limit,
			"offset": offset,
		}

		list_query = get_indent_table_query()
		rows = db.execute(list_query, params).fetchall()
		data = []
		for row in rows:
			mapped = dict(row._mapping)
			indent_date_obj = mapped.get("indent_date")
			indent_date = indent_date_obj
			if hasattr(indent_date_obj, "isoformat"):
				indent_date = indent_date_obj.isoformat()
			
			# Format indent_no if it exists
			raw_indent_no = mapped.get("indent_no")
			formatted_indent_no = ""
			if raw_indent_no is not None and raw_indent_no != 0:
				try:
					indent_no_int = int(raw_indent_no) if raw_indent_no else None
					co_prefix = mapped.get("co_prefix")
					branch_prefix = mapped.get("branch_prefix")
					formatted_indent_no = format_indent_no(
						indent_no=indent_no_int,
						co_prefix=co_prefix,
						branch_prefix=branch_prefix,
						indent_date=indent_date_obj,
						document_type="INDENT"
					)
				except Exception as e:
					logger.exception("Error formatting indent number in list, using raw value")
					formatted_indent_no = str(raw_indent_no) if raw_indent_no else ""
			
			data.append(
				{
					"indent_id": mapped.get("indent_id"),
					"indent_no": formatted_indent_no,
					"indent_date": indent_date,
					"branch_name": mapped.get("branch_name"),
					"expense_type": mapped.get("expense_type_name"),
					"status": mapped.get("status_name"),
				}
			)

		count_query = get_indent_table_count_query()
		count_params = {"co_id": co_id, "branch_id": branch_id, "search_like": search_like}
		count_result = db.execute(count_query, count_params).scalar()
		total = int(count_result) if count_result is not None else 0

		return {
			"data": data,
			"total": total,
		}
	except HTTPException:
		raise
	except Exception as e:
		raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_all_approved_indents")
def get_all_approved_indents(
	request: Request,
	db: Session = Depends(get_tenant_db),
	token_data: dict = Depends(get_current_user_with_refresh),
	branch_id: int | None = None,
	co_id: int | None = None,
):
	"""Get all approved indents (status_id = 3) for dropdown selection."""
	try:
		# Priority: 1. co_id from query params, 2. co_id from token_data, 3. derive from branch_id
		filter_co_id = co_id
		
		if filter_co_id is None:
			# Try to get from token_data
			user_co_id = token_data.get("co_id")
			if user_co_id:
				filter_co_id = user_co_id
		
		if filter_co_id is None and branch_id:
			# If we have branch_id but no co_id, get co_id from branch
			# Query branch_mst directly to get co_id
			from sqlalchemy.sql import text
			branch_sql = text("SELECT co_id FROM branch_mst WHERE branch_id = :branch_id")
			branch_result = db.execute(branch_sql, {"branch_id": branch_id}).fetchone()
			if branch_result:
				filter_co_id = branch_result[0] if isinstance(branch_result, tuple) else branch_result._mapping.get("co_id")
		
		# If still no co_id, raise error
		if filter_co_id is None:
			raise HTTPException(status_code=400, detail="Company ID is required. Please provide co_id or branch_id.")
		
		query = get_all_approved_indents_query()
		params = {"branch_id": branch_id, "co_id": filter_co_id}
		results = db.execute(query, params).fetchall()
		
		data = []
		for row in results:
			mapped = row._mapping
			indent_id = mapped.get("indent_id")
			if not indent_id:
				continue
			
			# Format indent_no
			raw_indent_no = mapped.get("indent_no")
			formatted_indent_no = ""
			if raw_indent_no is not None and raw_indent_no != 0:
				try:
					indent_date_str = mapped.get("indent_date")
					indent_date_obj = None
					if indent_date_str:
						if isinstance(indent_date_str, str):
							indent_date_obj = datetime.strptime(indent_date_str, "%Y-%m-%d").date()
						else:
							indent_date_obj = indent_date_str
					
					indent_no_int = int(raw_indent_no) if raw_indent_no else None
					co_prefix = mapped.get("co_prefix")
					branch_prefix = mapped.get("branch_prefix")
					formatted_indent_no = format_indent_no(
						indent_no=indent_no_int,
						co_prefix=co_prefix,
						branch_prefix=branch_prefix,
						indent_date=indent_date_obj,
						document_type="INDENT"
					)
				except Exception as e:
					logger.exception("Error formatting indent number, using raw value")
					formatted_indent_no = str(raw_indent_no) if raw_indent_no else ""
			
			indent_date = mapped.get("indent_date")
			if indent_date:
				if isinstance(indent_date, str):
					indent_date = indent_date
				else:
					indent_date = indent_date.strftime("%Y-%m-%d") if hasattr(indent_date, "strftime") else str(indent_date)
			else:
				indent_date = ""
			
			data.append({
				"indent_id": indent_id,
				"indent_no": formatted_indent_no,
				"indent_date": indent_date,
				"branch_name": mapped.get("branch_name") or "",
				"expense_type": mapped.get("expense_type_name") or "",
			})
		
		return {"data": data}
	except HTTPException:
		raise
	except Exception as e:
		logger.exception("Error fetching approved indents")
		raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_indent_by_id")
def get_indent_by_id(
	request: Request,
	db: Session = Depends(get_tenant_db),
	token_data: dict = Depends(get_current_user_with_refresh),
):
	"""Return indent details by ID with all line items."""
	try:
		# Get query parameters
		q_indent_id = request.query_params.get("indent_id")
		q_co_id = request.query_params.get("co_id")

		if q_indent_id is None:
			raise HTTPException(status_code=400, detail="indent_id is required")
		if q_co_id is None:
			raise HTTPException(status_code=400, detail="co_id is required")

		try:
			indent_id = int(q_indent_id)
			co_id = int(q_co_id)
		except (TypeError, ValueError):
			raise HTTPException(status_code=400, detail="Invalid indent_id or co_id")

		# Fetch header data
		header_query = get_indent_by_id_query()
		header_params = {"indent_id": indent_id, "co_id": co_id}
		header_result = db.execute(header_query, header_params).fetchone()

		if not header_result:
			raise HTTPException(status_code=404, detail="Indent not found or access denied")

		header = dict(header_result._mapping)

		# Fetch line items
		detail_query = get_indent_detail_by_id_query()
		detail_params = {"indent_id": indent_id}
		detail_results = db.execute(detail_query, detail_params).fetchall()
		details = [dict(r._mapping) for r in detail_results]

		# Get indent_type - use normalize_indent_type from constants for consistency
		indent_type_id = header.get("indent_type_id")
		indent_type_str = normalize_indent_type(indent_type_id)

		# Format dates - frontend expects YYYY-MM-DD format
		indent_date = header.get("indent_date")
		if indent_date and hasattr(indent_date, "date"):
			# datetime object
			indent_date_str = indent_date.date().isoformat()
		elif indent_date and hasattr(indent_date, "isoformat"):
			# date object
			indent_date_str = indent_date.isoformat()
		elif indent_date:
			indent_date_str = str(indent_date)
		else:
			indent_date_str = ""

		updated_at = header.get("updated_date_time")
		updated_at_str = None
		if updated_at:
			if hasattr(updated_at, "isoformat"):
				updated_at_str = updated_at.isoformat()
			else:
				updated_at_str = str(updated_at)

		# Get approval_level (only when status_id = 20, otherwise null)
		approval_level = header.get("approval_level")
		if approval_level is not None:
			try:
				approval_level = int(approval_level)
			except (TypeError, ValueError):
				approval_level = None
		else:
			approval_level = None
		
		# Get status_id
		status_id = header.get("status_id")
		branch_id = header.get("branch_id")
		
		# Get menu_id from query params (optional - needed for permission calculation)
		q_menu_id = request.query_params.get("menu_id")
		menu_id = None
		if q_menu_id is not None:
			try:
				menu_id = int(q_menu_id)
			except (TypeError, ValueError):
				menu_id = None
		
		# Calculate permissions if menu_id is provided
		permissions = None
		if menu_id is not None and branch_id is not None and status_id is not None:
			try:
				user_id = int(token_data.get("user_id"))
				permissions = calculate_approval_permissions(
					user_id=user_id,
					menu_id=menu_id,
					branch_id=branch_id,
					status_id=status_id,
					current_approval_level=approval_level,
					db=db,
				)
			except Exception as e:
				logger.exception("Error calculating permissions, continuing without them")
				permissions = None
		
		# Get max approval level for this menu/branch
		max_approval_level = None
		if menu_id is not None and branch_id is not None:
			try:
				max_level_query = get_max_approval_level()
				max_level_result = db.execute(
					max_level_query,
					{"menu_id": menu_id, "branch_id": branch_id}
				).fetchone()
				if max_level_result:
					max_level_val = dict(max_level_result._mapping).get("max_level")
					if max_level_val is not None:
						max_approval_level = int(max_level_val)
			except Exception:
				logger.exception("Error fetching max approval level, continuing without it")

		# Format indent_no if it exists
		raw_indent_no = header.get("indent_no")
		formatted_indent_no = ""
		if raw_indent_no is not None and raw_indent_no != 0:
			try:
				indent_no_int = int(raw_indent_no) if raw_indent_no else None
				co_prefix = header.get("co_prefix")
				branch_prefix = header.get("branch_prefix")
				formatted_indent_no = format_indent_no(
					indent_no=indent_no_int,
					co_prefix=co_prefix,
					branch_prefix=branch_prefix,
					indent_date=indent_date,
					document_type="INDENT"
				)
			except Exception as e:
				logger.exception("Error formatting indent number, using raw value")
				formatted_indent_no = str(raw_indent_no) if raw_indent_no else ""

		# Build response
		response = {
			"id": str(header.get("indent_id", "")),
			"indentNo": formatted_indent_no,
			"indentDate": indent_date_str,
			"branch": str(header.get("branch_id", "")) if header.get("branch_id") else "",
			"indentType": indent_type_str,
			"expenseType": str(header.get("expense_type_id", "")) if header.get("expense_type_id") else "",
			"project": str(header.get("project_id", "")) if header.get("project_id") else None,
			"requester": header.get("indent_title") if header.get("indent_title") else None,
			"status": header.get("status_name") if header.get("status_name") else None,
			"statusId": header.get("status_id"),
			"approvalLevel": approval_level,
			"maxApprovalLevel": max_approval_level,
			"updatedBy": str(header.get("updated_by", "")) if header.get("updated_by") else None,
			"updatedAt": updated_at_str,
			"remarks": header.get("remarks") if header.get("remarks") else None,
			"lines": [],
		}
		
		# Add permissions if calculated
		if permissions is not None:
			response["permissions"] = permissions

		# Map line items
		for detail in details:
			line = {
				"id": str(detail.get("indent_dtl_id", "")) if detail.get("indent_dtl_id") else "",
				"department": str(detail.get("dept_id", "")) if detail.get("dept_id") else None,
				"itemGroup": str(detail.get("item_grp_id", "")) if detail.get("item_grp_id") else "",
				"item": str(detail.get("item_id", "")) if detail.get("item_id") else "",
				"itemMake": str(detail.get("item_make_id", "")) if detail.get("item_make_id") else None,
				"quantity": float(detail.get("qty", 0)) if detail.get("qty") is not None else 0,
				"uom": str(detail.get("uom_id", "")) if detail.get("uom_id") else "",
				"remarks": detail.get("remarks") if detail.get("remarks") else None,
			}
			response["lines"].append(line)

		return response
	except HTTPException:
		raise
	except Exception as e:
		logger.exception("Error fetching indent by ID")
		raise HTTPException(status_code=500, detail=str(e))


@router.post("/create_indent")
def create_indent(
	payload: dict,
	db: Session = Depends(get_tenant_db),
	token_data: dict = Depends(get_current_user_with_refresh),
):
	"""Create a procurement indent with detail rows."""

	def to_int(value, field_name: str, required: bool = False) -> int | None:
		if value is None or value == "":
			if required:
				raise HTTPException(status_code=400, detail=f"{field_name} is required")
			return None
		try:
			return int(value)
		except (TypeError, ValueError):
			raise HTTPException(status_code=400, detail=f"Invalid {field_name}")

	def to_positive_float(value, field_name: str) -> float:
		try:
			qty = float(value)
		except (TypeError, ValueError):
			raise HTTPException(status_code=400, detail=f"Invalid {field_name}")
		if qty <= 0:
			raise HTTPException(status_code=400, detail=f"{field_name} must be greater than zero")
		return qty

	try:
		branch_id = to_int(payload.get("branch"), "branch", required=True)
		expense_type_id = to_int(payload.get("expense_type"), "expense_type", required=True)
		indent_type = payload.get("indent_type")
		if not indent_type:
			raise HTTPException(status_code=400, detail="indent_type is required")
		if not is_valid_indent_type(indent_type):
			raise HTTPException(
				status_code=400, 
				detail=f"Invalid indent_type '{indent_type}'. Valid values: {VALID_INDENT_TYPE_VALUES}"
			)

		date_str = payload.get("date")
		if not date_str:
			raise HTTPException(status_code=400, detail="date is required")
		try:
			indent_date = datetime.strptime(str(date_str), "%Y-%m-%d").date()
		except ValueError:
			raise HTTPException(status_code=400, detail="Invalid date format, expected YYYY-MM-DD")

		raw_items = payload.get("items")
		if not isinstance(raw_items, list) or len(raw_items) == 0:
			raise HTTPException(status_code=400, detail="At least one item row is required")

		updated_by = to_int(token_data.get("user_id"), "updated_by")
		created_at = now_ist()
		indent_title_raw = payload.get("name") or payload.get("requester")
		indent_title = str(indent_title_raw).strip() if indent_title_raw else None
		header_remarks_raw = payload.get("remarks")
		header_remarks = str(header_remarks_raw).strip() if header_remarks_raw else None
		indent_no_value = to_int(payload.get("indent_no"), "indent_no", required=False)
		project_id = to_int(payload.get("project"), "project")

		normalized_items = []
		for idx, item in enumerate(raw_items, start=1):
			item_id = to_int(item.get("item"), f"items[{idx}].item", required=True)
			qty = to_positive_float(item.get("quantity"), f"items[{idx}].quantity")
			uom_id = to_int(item.get("uom"), f"items[{idx}].uom", required=True)
			item_make_id = to_int(item.get("item_make"), f"items[{idx}].item_make")
			department_id = to_int(item.get("department"), f"items[{idx}].department")

			remarks_raw = item.get("remarks")
			remarks = str(remarks_raw).strip() if remarks_raw else None
			if remarks:
				remarks = remarks[:599]

			normalized_items.append(
				{
					"item_id": item_id,
					"qty": qty,
					"uom_id": uom_id,
					"item_make_id": item_make_id,
					"remarks": remarks,
					"dept_id": department_id,
				}
			)

		logger.debug("Normalized indent items: %s", normalized_items)

		# ── Server-side line-item validation (safety net) ──────────────
		expense_name_row = db.execute(
			get_expense_type_name_by_id(),
			{"expense_type_id": int(expense_type_id)},
		).fetchone()
		resolved_expense_name = (
			dict(expense_name_row._mapping)["expense_type_name"]
			if expense_name_row
			else None
		)
		validation_logic = determine_validation_logic(indent_type, resolved_expense_name)

		if validation_logic in (1, 2):
			fy_start, fy_end = get_fy_boundaries(indent_date)
			for idx, ni in enumerate(normalized_items, start=1):
				item_id = ni["item_id"]

				if validation_logic == 1:
					vdata = db.execute(
						get_item_validation_data_v2(),
						{"branch_id": int(branch_id), "item_id": int(item_id)},
					).fetchone()
					if vdata:
						vd = dict(vdata._mapping)
						# Use pre-computed max_indent_qty from view
						# Sentinel: -2=open outstanding (skip), -1=no minmax (skip), >=0=enforce
						max_allowed = float(vd.get("max_indent_qty", -1))
						if max_allowed >= 0 and ni["qty"] > max_allowed:
							raise HTTPException(
								status_code=400,
								detail=(
									f"Row {idx}: Quantity {ni['qty']} exceeds the "
									f"maximum allowed indent quantity of {max_allowed:.2f} "
									f"for this item (maxQty={vd.get('maxqty')}, "
									f"stock={vd.get('branch_stock', 0)}, "
									f"outstanding={vd.get('outstanding_indent_qty', 0)})."
								),
							)

				elif validation_logic == 2:
					fy_row = db.execute(
						get_item_fy_indent_check_v2(),
						{
							"item_id": int(item_id),
							"branch_id": int(branch_id),
							"fy_start": fy_start,
							"fy_end": fy_end,
						},
					).fetchone()
					if fy_row:
						existing = dict(fy_row._mapping)
						raise HTTPException(
							status_code=400,
							detail=(
								f"Row {idx}: An open indent already exists for this "
								f"item in the current financial year "
								f"(Indent No: {existing.get('indent_no')})."
							),
						)

		insert_header_query = insert_proc_indent()
		header_params = {
			"indent_date": indent_date,
			"indent_no": indent_no_value,
			"active": 1,
			"indent_type_id": indent_type,
			"remarks": header_remarks,
			"branch_id": branch_id,
			"expense_type_id": expense_type_id,
			"project_id": project_id,
			"updated_by": updated_by,
			"updated_date_time": created_at,
			"status_id": 21,
			"indent_title": indent_title,
		}

		logger.info(
			"Creating indent: branch=%s, indent_type=%s, expense_type=%s, item_rows=%s",
			branch_id,
			indent_type,
			expense_type_id,
			len(normalized_items),
		)
		logger.debug("Indent header params: %s", header_params)

		result = db.execute(insert_header_query, header_params)
		indent_id = result.lastrowid
		if not indent_id:
			raise HTTPException(status_code=500, detail="Failed to create indent header")

		if indent_no_value is None:
			indent_no_value = indent_id

		detail_query = insert_proc_indent_detail()
		for detail in normalized_items:
			db.execute(
				detail_query,
				{
					"indent_id": indent_id,
					"required_by_days": None,
					"active": 1,
					"item_id": detail["item_id"],
					"qty": detail["qty"],
					"uom_id": detail["uom_id"],
					"remarks": detail["remarks"],
					"updated_by": updated_by,
					"updated_date_time": created_at,
					"item_make_id": detail["item_make_id"],
					"dept_id": detail["dept_id"],
				},
			)

		db.commit()
		return {
			"message": "Indent created successfully",
			"indent_id": indent_id,
			"indent_no": indent_no_value,
		}
	except HTTPException as exc:
		db.rollback()
		logger.warning("Indent create failed with HTTP error: %s", getattr(exc, "detail", exc))
		raise
	except Exception as e:
		db.rollback()
		logger.exception("Unexpected error while creating indent")
		raise HTTPException(
			status_code=500,
			detail={
				"message": "Failed to create indent",
				"error": str(e),
			},
		)


@router.put("/update_indent")
def update_indent(
	payload: dict,
	db: Session = Depends(get_tenant_db),
	token_data: dict = Depends(get_current_user_with_refresh),
):
	"""Update a procurement indent with detail rows."""
	def to_int(value, field_name: str, required: bool = False) -> int | None:
		if value is None or value == "":
			if required:
				raise HTTPException(status_code=400, detail=f"{field_name} is required")
			return None
		try:
			return int(value)
		except (TypeError, ValueError):
			raise HTTPException(status_code=400, detail=f"Invalid {field_name}")

	def to_positive_float(value, field_name: str) -> float:
		try:
			qty = float(value)
		except (TypeError, ValueError):
			raise HTTPException(status_code=400, detail=f"Invalid {field_name}")
		if qty <= 0:
			raise HTTPException(status_code=400, detail=f"{field_name} must be greater than zero")
		return qty

	try:
		indent_id = to_int(payload.get("id"), "id", required=True)
		branch_id = to_int(payload.get("branch"), "branch", required=True)
		expense_type_id = to_int(payload.get("expense_type"), "expense_type", required=True)
		indent_type = payload.get("indent_type")
		if not indent_type:
			raise HTTPException(status_code=400, detail="indent_type is required")
		if not is_valid_indent_type(indent_type):
			raise HTTPException(
				status_code=400, 
				detail=f"Invalid indent_type '{indent_type}'. Valid values: {VALID_INDENT_TYPE_VALUES}"
			)

		date_str = payload.get("date")
		if not date_str:
			raise HTTPException(status_code=400, detail="date is required")
		try:
			indent_date = datetime.strptime(str(date_str), "%Y-%m-%d").date()
		except ValueError:
			raise HTTPException(status_code=400, detail="Invalid date format, expected YYYY-MM-DD")

		raw_items = payload.get("items")
		if not isinstance(raw_items, list) or len(raw_items) == 0:
			raise HTTPException(status_code=400, detail="At least one item row is required")

		updated_by = to_int(token_data.get("user_id"), "updated_by")
		updated_at = now_ist()
		indent_title_raw = payload.get("name")
		indent_title = str(indent_title_raw).strip() if indent_title_raw else None
		header_remarks_raw = payload.get("remarks")
		header_remarks = str(header_remarks_raw).strip() if header_remarks_raw else None
		project_id = to_int(payload.get("project"), "project")

		# Verify indent exists (basic check - full access control handled by branch_id validation)
		# We'll verify the indent exists by checking if we can fetch it
		# The actual co_id validation happens through branch access
		check_query = text("SELECT indent_id FROM proc_indent WHERE indent_id = :indent_id AND active = 1")
		check_result = db.execute(check_query, {"indent_id": indent_id}).fetchone()
		if not check_result:
			raise HTTPException(status_code=404, detail="Indent not found or inactive")

		normalized_items = []
		for idx, item in enumerate(raw_items, start=1):
			item_id = to_int(item.get("item"), f"items[{idx}].item", required=True)
			qty = to_positive_float(item.get("quantity"), f"items[{idx}].quantity")
			uom_id = to_int(item.get("uom"), f"items[{idx}].uom", required=True)
			item_make_id = to_int(item.get("item_make"), f"items[{idx}].item_make")
			department_id = to_int(item.get("department"), f"items[{idx}].department")
			# indent_dtl_id may be a client-generated UUID for new lines — treat as None
			raw_dtl_id = item.get("indent_dtl_id")
			try:
				indent_dtl_id = int(raw_dtl_id) if raw_dtl_id else None
			except (TypeError, ValueError):
				indent_dtl_id = None

			remarks_raw = item.get("remarks")
			remarks = str(remarks_raw).strip() if remarks_raw else None
			if remarks:
				remarks = remarks[:599]

			normalized_items.append(
				{
					"indent_dtl_id": indent_dtl_id,
					"item_id": item_id,
					"qty": qty,
					"uom_id": uom_id,
					"item_make_id": item_make_id,
					"remarks": remarks,
					"dept_id": department_id,
				}
			)

		logger.debug("Normalized indent items for update: %s", normalized_items)

		# ── Server-side line-item validation (safety net) ──────────────
		expense_name_row = db.execute(
			get_expense_type_name_by_id(),
			{"expense_type_id": int(expense_type_id)},
		).fetchone()
		resolved_expense_name = (
			dict(expense_name_row._mapping)["expense_type_name"]
			if expense_name_row
			else None
		)
		validation_logic = determine_validation_logic(indent_type, resolved_expense_name)

		if validation_logic in (1, 2):
			fy_start, fy_end = get_fy_boundaries(indent_date)
			for idx, ni in enumerate(normalized_items, start=1):
				item_id = ni["item_id"]

				if validation_logic == 1:
					vdata = db.execute(
						get_item_validation_data_v2(),
						{"branch_id": int(branch_id), "item_id": int(item_id)},
					).fetchone()
					if vdata:
						vd = dict(vdata._mapping)
						max_allowed = float(vd.get("max_indent_qty", -1))
						outstanding_qty = float(vd.get("outstanding_indent_qty") or 0)

						# Add back the current indent's own outstanding so editing
						# doesn't fail against its own previously-saved quantity.
						self_row = db.execute(
							get_indent_item_outstanding(),
							{"branch_id": int(branch_id), "item_id": int(item_id), "indent_id": int(indent_id)},
						).fetchone()
						self_out = float(dict(self_row._mapping).get("indent_outstanding") or 0) if self_row else 0.0
						if self_out > 0 and max_allowed >= 0:
							max_allowed += self_out
							outstanding_qty -= self_out

						if max_allowed >= 0 and ni["qty"] > max_allowed:
							raise HTTPException(
								status_code=400,
								detail=(
									f"Row {idx}: Quantity {ni['qty']} exceeds the "
									f"maximum allowed indent quantity of {max_allowed:.2f} "
									f"for this item (maxQty={vd.get('maxqty')}, "
									f"stock={vd.get('branch_stock', 0)}, "
									f"outstanding={outstanding_qty})."
								),
							)

				elif validation_logic == 2:
					fy_row = db.execute(
						get_item_fy_indent_check_v2(),
						{
							"item_id": int(item_id),
							"branch_id": int(branch_id),
							"fy_start": fy_start,
							"fy_end": fy_end,
						},
					).fetchone()
					if fy_row:
						existing = dict(fy_row._mapping)
						raise HTTPException(
							status_code=400,
							detail=(
								f"Row {idx}: An open indent already exists for this "
								f"item in the current financial year "
								f"(Indent No: {existing.get('indent_no')})."
							),
						)

		# Get existing indent_no, active, and status_id to preserve them
		# This also helps avoid trigger issues by ensuring all columns are present
		existing_query = text("SELECT indent_no, active, status_id FROM proc_indent WHERE indent_id = :indent_id")
		existing_result = db.execute(existing_query, {"indent_id": indent_id}).fetchone()
		if not existing_result:
			raise HTTPException(status_code=404, detail="Indent not found")
		existing_indent_no = existing_result[0] if existing_result[0] is not None else None
		existing_active = existing_result[1] if existing_result[1] is not None else 1
		existing_status_id = existing_result[2] if existing_result[2] is not None else None

		# Update header
		update_header_query = update_proc_indent()
		header_params = {
			"indent_id": indent_id,
			"indent_date": indent_date,
			"branch_id": branch_id,
			"indent_type_id": indent_type,
			"expense_type_id": expense_type_id,
			"project_id": project_id,
			"indent_title": indent_title,
			"remarks": header_remarks,
			"updated_by": updated_by,
			"updated_date_time": updated_at,
			"indent_no": existing_indent_no,
			"active": existing_active,
			"status_id": existing_status_id,
		}

		logger.info(
			"Updating indent: indent_id=%s, branch=%s, indent_type=%s, expense_type=%s, item_rows=%s",
			indent_id,
			branch_id,
			indent_type,
			expense_type_id,
			len(normalized_items),
		)
		logger.debug("Indent header update params: %s", header_params)

		db.execute(update_header_query, header_params)

		# ── Update detail rows in place ──────────────────────────────────
		# Existing rows are updated (preserving indent_dtl_id for PO traceability
		# and view consistency). New rows are inserted. Removed rows are soft-deleted.

		# Get current active detail IDs for this indent
		existing_dtl_rows = db.execute(
			text("SELECT indent_dtl_id FROM proc_indent_dtl WHERE indent_id = :indent_id AND active = 1"),
			{"indent_id": indent_id},
		).fetchall()
		existing_dtl_ids = {row[0] for row in existing_dtl_rows}

		incoming_dtl_ids = set()
		for detail in normalized_items:
			dtl_id = detail.get("indent_dtl_id")
			if dtl_id and dtl_id in existing_dtl_ids:
				# Update existing row in place
				incoming_dtl_ids.add(dtl_id)
				db.execute(
					update_proc_indent_detail(),
					{
						"indent_dtl_id": dtl_id,
						"indent_id": indent_id,
						"item_id": detail["item_id"],
						"qty": detail["qty"],
						"uom_id": detail["uom_id"],
						"item_make_id": detail["item_make_id"],
						"dept_id": detail["dept_id"],
						"remarks": detail["remarks"],
						"updated_by": updated_by,
						"updated_date_time": updated_at,
					},
				)
			else:
				# New row — insert
				db.execute(
					insert_proc_indent_detail(),
					{
						"indent_id": indent_id,
						"required_by_days": None,
						"active": 1,
						"item_id": detail["item_id"],
						"qty": detail["qty"],
						"uom_id": detail["uom_id"],
						"remarks": detail["remarks"],
						"updated_by": updated_by,
						"updated_date_time": updated_at,
						"item_make_id": detail["item_make_id"],
						"dept_id": detail["dept_id"],
					},
				)

		# Soft-delete rows that were removed by the user
		removed_dtl_ids = existing_dtl_ids - incoming_dtl_ids
		if removed_dtl_ids:
			for dtl_id in removed_dtl_ids:
				db.execute(
					text(
						"UPDATE proc_indent_dtl SET active = 0, updated_by = :updated_by, "
						"updated_date_time = :updated_date_time WHERE indent_dtl_id = :dtl_id"
					),
					{"dtl_id": dtl_id, "updated_by": updated_by, "updated_date_time": updated_at},
				)

		db.commit()
		return {
			"message": "Indent updated successfully",
			"indent_id": indent_id,
		}
	except HTTPException as exc:
		db.rollback()
		logger.warning("Indent update failed with HTTP error: %s", getattr(exc, "detail", exc))
		raise
	except Exception as e:
		db.rollback()
		logger.exception("Unexpected error while updating indent")
		raise HTTPException(
			status_code=500,
			detail=str(e),
		)


# ==================== INDENT NUMBER FORMATTING ====================

def calculate_financial_year(indent_date) -> str:
	"""Calculate financial year in YY-YY format from a date.
	
	Financial year: April 1 to March 31
	- If month >= 4 (April-December): FY = YY-YY (e.g., April 2025 = 25-26)
	- If month < 4 (January-March): FY = (YY-1)-YY (e.g., January 2025 = 24-25)
	
	Args:
		indent_date: Date object, datetime object, or date string
		
	Returns:
		Financial year string in YY-YY format (e.g., "25-26")
	"""
	try:
		# Handle different date formats
		if hasattr(indent_date, "year") and hasattr(indent_date, "month"):
			# Date object
			year = indent_date.year
			month = indent_date.month
		elif hasattr(indent_date, "date"):
			# Datetime object
			date_obj = indent_date.date()
			year = date_obj.year
			month = date_obj.month
		else:
			# String or other format - try to parse
			if isinstance(indent_date, str):
				try:
					date_obj = datetime.strptime(indent_date, "%Y-%m-%d").date()
				except ValueError:
					date_obj = datetime.fromisoformat(indent_date).date()
			else:
				date_obj = datetime.fromisoformat(str(indent_date)).date()
			year = date_obj.year
			month = date_obj.month
		
		# Calculate financial year
		if month >= 4:
			# April-December: FY = current year to next year
			fy_start = year % 100
			fy_end = (year + 1) % 100
		else:
			# January-March: FY = previous year to current year
			fy_start = (year - 1) % 100
			fy_end = year % 100
		
		return f"{fy_start:02d}-{fy_end:02d}"
	except Exception as e:
		logger.exception(f"Error calculating financial year from {indent_date}")
		# Fallback to current year if date parsing fails
		now = now_ist()
		current_year = now.year
		current_month = now.month
		if current_month >= 4:
			return f"{current_year % 100:02d}-{(current_year + 1) % 100:02d}"
		else:
			return f"{(current_year - 1) % 100:02d}-{current_year % 100:02d}"


def format_indent_no(
	indent_no: Optional[int],
	co_prefix: Optional[str],
	branch_prefix: Optional[str],
	indent_date,
	document_type: str = "INDENT"
) -> str:
	"""Format indent number as "co_prefix/branch_prefix/document_type/financial_year/indent_no".
	
	Args:
		indent_no: Numeric indent number (from database)
		co_prefix: Company prefix from co_mst
		branch_prefix: Branch prefix from branch_mst
		indent_date: Date for calculating financial year
		document_type: Document type prefix (default: "INDENT")
		
	Returns:
		Formatted indent number string (e.g., "ABC/MAIN/INDENT/25-26/1")
		Returns empty string if indent_no is None or 0
	"""
	# Return empty string if indent_no is not set
	if indent_no is None or indent_no == 0:
		return ""
	
	# Calculate financial year
	fy = calculate_financial_year(indent_date)
	
	# Get prefixes with fallbacks (use empty string if None)
	co_pref = co_prefix or ""
	branch_pref = branch_prefix or ""
	
	# Build formatted string: co_prefix/branch_prefix/document_type/financial_year/indent_no
	# Filter out empty prefixes but keep structure for non-empty parts
	parts = []
	if co_pref:
		parts.append(co_pref)
	if branch_pref:
		parts.append(branch_pref)
	# Always include document_type, financial_year, and indent_no
	parts.extend([document_type, fy, str(indent_no)])
	
	return "/".join(parts)


# ==================== APPROVAL FLOW FUNCTIONS ====================

def get_approval_flow_details(menu_id: int, branch_id: int, db: Session) -> list:
	"""Get approval flow details for a menu and branch combination.
	
	Args:
		menu_id: The menu ID
		branch_id: The branch ID
		db: Database session
		
	Returns:
		List of approval flow records ordered by approval_level
	"""
	try:
		query = get_approval_flow_by_menu_branch()
		result = db.execute(query, {"menu_id": menu_id, "branch_id": branch_id}).fetchall()
		return [dict(r._mapping) for r in result]
	except Exception as e:
		logger.exception("Error fetching approval flow details")
		raise


# ==================== APPROVAL API ENDPOINTS ====================

@router.get("/get_approval_flow")
def get_approval_flow(
	request: Request,
	db: Session = Depends(get_tenant_db),
	token_data: dict = Depends(get_current_user_with_refresh),
	menu_id: Optional[int] = None,
	branch_id: Optional[int] = None,
):
	"""Get approval flow details for a menu and branch."""
	try:
		q_menu_id = request.query_params.get("menu_id")
		q_branch_id = request.query_params.get("branch_id")
		
		if q_menu_id is not None:
			try:
				menu_id = int(q_menu_id)
			except Exception:
				raise HTTPException(status_code=400, detail="Invalid menu_id")
		
		if q_branch_id is not None:
			try:
				branch_id = int(q_branch_id)
			except Exception:
				raise HTTPException(status_code=400, detail="Invalid branch_id")
		
		if menu_id is None:
			raise HTTPException(status_code=400, detail="menu_id is required")
		if branch_id is None:
			raise HTTPException(status_code=400, detail="branch_id is required")
		
		flow_details = get_approval_flow_details(menu_id, branch_id, db)
		
		return {
			"menu_id": menu_id,
			"branch_id": branch_id,
			"approval_flow": flow_details,
		}
	except HTTPException:
		raise
	except Exception as e:
		logger.exception("Error fetching approval flow")
		raise HTTPException(status_code=500, detail=str(e))


@router.post("/approve_indent")
def approve_indent(
	payload: dict,
	db: Session = Depends(get_tenant_db),
	token_data: dict = Depends(get_current_user_with_refresh),
):
	"""Approve an indent (without value check - indents don't have monetary amounts)."""
	try:
		indent_id = payload.get("indent_id")
		branch_id = payload.get("branch_id")
		menu_id = payload.get("menu_id")
		approval_level = payload.get("approval_level")  # Optional, for logging
		
		if not indent_id:
			raise HTTPException(status_code=400, detail="indent_id is required")
		if not branch_id:
			raise HTTPException(status_code=400, detail="branch_id is required")
		if not menu_id:
			raise HTTPException(status_code=400, detail="menu_id is required")
		
		try:
			indent_id = int(indent_id)
			branch_id = int(branch_id)
			menu_id = int(menu_id)
		except (TypeError, ValueError):
			raise HTTPException(status_code=400, detail="Invalid indent_id, branch_id, or menu_id")
		
		user_id = int(token_data.get("user_id"))
		
		# Process approval (indent is without value)
		result = process_approval(
			doc_id=indent_id,
			user_id=user_id,
			menu_id=menu_id,
			db=db,
			get_doc_fn=get_indent_with_approval_info,
			update_status_fn=update_indent_status,
			id_param_name="indent_id",
			doc_name="Indent",
			extra_update_params={"indent_no": None},
		)
		
		return result
	except HTTPException:
		raise
	except Exception as e:
		logger.exception("Error approving indent")
		raise HTTPException(status_code=500, detail=str(e))


@router.post("/approve_indent_with_value")
def approve_indent_with_value(
	payload: dict,
	db: Session = Depends(get_tenant_db),
	token_data: dict = Depends(get_current_user_with_refresh),
):
	"""Approve an indent with value checks (for documents with monetary amounts)."""
	try:
		indent_id = payload.get("indent_id")
		branch_id = payload.get("branch_id")
		menu_id = payload.get("menu_id")
		document_amount = payload.get("amount", 0.0)
		
		if not indent_id:
			raise HTTPException(status_code=400, detail="indent_id is required")
		if not branch_id:
			raise HTTPException(status_code=400, detail="branch_id is required")
		if not menu_id:
			raise HTTPException(status_code=400, detail="menu_id is required")
		
		try:
			indent_id = int(indent_id)
			branch_id = int(branch_id)
			menu_id = int(menu_id)
			document_amount = float(document_amount)
		except (TypeError, ValueError) as e:
			raise HTTPException(status_code=400, detail=f"Invalid parameters: {str(e)}")
		
		user_id = int(token_data.get("user_id"))
		
		# Process approval with value checks
		result = process_approval(
			doc_id=indent_id,
			user_id=user_id,
			menu_id=menu_id,
			db=db,
			get_doc_fn=get_indent_with_approval_info,
			update_status_fn=update_indent_status,
			id_param_name="indent_id",
			doc_name="Indent",
			document_amount=document_amount,
			extra_update_params={"indent_no": None},
		)
		
		return result
	except HTTPException:
		raise
	except Exception as e:
		logger.exception("Error approving indent with value")
		raise HTTPException(status_code=500, detail=str(e))


@router.post("/open_indent")
def open_indent(
	payload: dict,
	db: Session = Depends(get_tenant_db),
	token_data: dict = Depends(get_current_user_with_refresh),
):
	"""Open an indent (change status from 21 Drafted to 1 Open). Generates document number if not already generated."""
	try:
		indent_id = payload.get("indent_id")
		branch_id = payload.get("branch_id")
		menu_id = payload.get("menu_id")
		
		if not indent_id:
			raise HTTPException(status_code=400, detail="indent_id is required")
		if not branch_id:
			raise HTTPException(status_code=400, detail="branch_id is required")
		if not menu_id:
			raise HTTPException(status_code=400, detail="menu_id is required")
		
		try:
			indent_id = int(indent_id)
			branch_id = int(branch_id)
			menu_id = int(menu_id)
		except (TypeError, ValueError):
			raise HTTPException(status_code=400, detail="Invalid indent_id, branch_id, or menu_id")
		
		user_id = int(token_data.get("user_id"))
		
		# Get indent details
		indent_query = get_indent_with_approval_info()
		indent_result = db.execute(indent_query, {"indent_id": indent_id}).fetchone()
		if not indent_result:
			raise HTTPException(status_code=404, detail="Indent not found")
		
		indent = dict(indent_result._mapping)
		current_status_id = indent.get("status_id")
		current_indent_no = indent.get("indent_no")
		indent_date = indent.get("indent_date")
		
		# Verify current status is Drafted (21)
		if current_status_id != 21:
			raise HTTPException(
				status_code=400,
				detail=f"Cannot open indent with status_id {current_status_id}. Expected status 21 (Drafted)."
			)
		
		# Generate indent_no if not already set
		new_indent_no = None
		if not indent_date:
			raise HTTPException(
				status_code=400,
				detail="Indent date is required to generate indent number."
			)
		
		# Only generate if indent_no is NULL or 0
		if current_indent_no is None or current_indent_no == 0:
			# Calculate financial year boundaries
			if hasattr(indent_date, "year") and hasattr(indent_date, "month"):
				# Date object
				year = indent_date.year
				month = indent_date.month
			elif hasattr(indent_date, "date"):
				# Datetime object
				date_obj = indent_date.date()
				year = date_obj.year
				month = date_obj.month
			else:
				# String or other format - try to parse
				try:
					if isinstance(indent_date, str):
						date_obj = datetime.strptime(indent_date, "%Y-%m-%d").date()
					else:
						date_obj = datetime.fromisoformat(str(indent_date)).date()
					year = date_obj.year
					month = date_obj.month
				except Exception:
					raise HTTPException(
						status_code=400,
						detail=f"Invalid indent_date format: {indent_date}"
					)
			
			# Calculate financial year boundaries
			# Financial year: April 1 to March 31
			# If month >= 4 (April-December): FY = year-04-01 to (year+1)-03-31
			# If month < 4 (January-March): FY = (year-1)-04-01 to year-03-31
			if month >= 4:
				fy_start_year = year
				fy_end_year = year + 1
			else:
				fy_start_year = year - 1
				fy_end_year = year
			
			fy_start_date = datetime(fy_start_year, 4, 1).date()
			fy_end_date = datetime(fy_end_year, 3, 31).date()
			
			# Get max indent_no for this branch and financial year
			max_query = get_max_indent_no_for_branch_fy()
			max_result = db.execute(
				max_query,
				{
					"branch_id": branch_id,
					"fy_start_date": fy_start_date,
					"fy_end_date": fy_end_date,
				}
			).fetchone()
			
			if max_result:
				max_indent_no = dict(max_result._mapping).get("max_indent_no") or 0
				new_indent_no = max_indent_no + 1
			else:
				new_indent_no = 1
		
		# Update status to Open (1) and set indent_no if generated
		updated_at = now_ist()
		update_query = update_indent_status()
		update_params = {
			"indent_id": indent_id,
			"status_id": 1,  # Open
			"approval_level": None,  # Reset approval level
			"updated_by": user_id,
			"updated_date_time": updated_at,
		}
		# Only include indent_no if it was generated
		if new_indent_no is not None:
			update_params["indent_no"] = new_indent_no
		else:
			# Pass None to keep existing value
			update_params["indent_no"] = None
		
		db.execute(update_query, update_params)
		db.commit()
		
		# Return the indent_no that was set (either newly generated or existing)
		final_indent_no = new_indent_no if new_indent_no is not None else current_indent_no
		
		return {
			"status": "success",
			"new_status_id": 1,
			"message": "Indent opened successfully.",
			"indent_no": final_indent_no,
		}
	except HTTPException:
		db.rollback()
		raise
	except Exception as e:
		db.rollback()
		logger.exception("Error opening indent")
		raise HTTPException(status_code=500, detail=str(e))


@router.post("/cancel_draft_indent")
def cancel_draft_indent(
	payload: dict,
	db: Session = Depends(get_tenant_db),
	token_data: dict = Depends(get_current_user_with_refresh),
):
	"""Cancel a draft indent (change status from 21 Drafted to 6 Cancelled)."""
	try:
		indent_id = payload.get("indent_id")
		branch_id = payload.get("branch_id")
		menu_id = payload.get("menu_id")
		
		if not indent_id:
			raise HTTPException(status_code=400, detail="indent_id is required")
		if not branch_id:
			raise HTTPException(status_code=400, detail="branch_id is required")
		if not menu_id:
			raise HTTPException(status_code=400, detail="menu_id is required")
		
		try:
			indent_id = int(indent_id)
			branch_id = int(branch_id)
			menu_id = int(menu_id)
		except (TypeError, ValueError):
			raise HTTPException(status_code=400, detail="Invalid indent_id, branch_id, or menu_id")
		
		user_id = int(token_data.get("user_id"))
		
		# Get indent details
		indent_query = get_indent_with_approval_info()
		indent_result = db.execute(indent_query, {"indent_id": indent_id}).fetchone()
		if not indent_result:
			raise HTTPException(status_code=404, detail="Indent not found")
		
		indent = dict(indent_result._mapping)
		current_status_id = indent.get("status_id")
		
		# Verify current status is Drafted (21)
		if current_status_id != 21:
			raise HTTPException(
				status_code=400,
				detail=f"Cannot cancel indent with status_id {current_status_id}. Expected status 21 (Drafted)."
			)
		
		# Update status to Cancelled (6)
		updated_at = now_ist()
		update_query = update_indent_status()
		db.execute(
			update_query,
			{
				"indent_id": indent_id,
				"status_id": 6,  # Cancelled
				"approval_level": None,
				"updated_by": user_id,
				"updated_date_time": updated_at,
				"indent_no": None,  # Don't update indent_no
			}
		)
		db.commit()
		
		return {
			"status": "success",
			"new_status_id": 6,
			"message": "Draft cancelled successfully.",
		}
	except HTTPException:
		db.rollback()
		raise
	except Exception as e:
		db.rollback()
		logger.exception("Error cancelling draft indent")
		raise HTTPException(status_code=500, detail=str(e))


@router.post("/reopen_indent")
def reopen_indent(
	payload: dict,
	db: Session = Depends(get_tenant_db),
	token_data: dict = Depends(get_current_user_with_refresh),
):
	"""Reopen an indent (change status from 6 Cancelled or 4 Rejected back to 1 Open or 21 Drafted)."""
	try:
		indent_id = payload.get("indent_id")
		branch_id = payload.get("branch_id")
		menu_id = payload.get("menu_id")
		
		if not indent_id:
			raise HTTPException(status_code=400, detail="indent_id is required")
		if not branch_id:
			raise HTTPException(status_code=400, detail="branch_id is required")
		if not menu_id:
			raise HTTPException(status_code=400, detail="menu_id is required")
		
		try:
			indent_id = int(indent_id)
			branch_id = int(branch_id)
			menu_id = int(menu_id)
		except (TypeError, ValueError):
			raise HTTPException(status_code=400, detail="Invalid indent_id, branch_id, or menu_id")
		
		user_id = int(token_data.get("user_id"))
		
		# Get indent details
		indent_query = get_indent_with_approval_info()
		indent_result = db.execute(indent_query, {"indent_id": indent_id}).fetchone()
		if not indent_result:
			raise HTTPException(status_code=404, detail="Indent not found")
		
		indent = dict(indent_result._mapping)
		current_status_id = indent.get("status_id")
		
		# Determine target status based on current status
		if current_status_id == 6:  # Cancelled
			new_status_id = 21  # Back to Drafted
		elif current_status_id == 4:  # Rejected
			new_status_id = 1  # Back to Open
		else:
			raise HTTPException(
				status_code=400,
				detail=f"Cannot reopen indent with status_id {current_status_id}. Only Cancelled (6) or Rejected (4) can be reopened."
			)
		
		# Update status
		updated_at = now_ist()
		update_query = update_indent_status()
		db.execute(
			update_query,
			{
				"indent_id": indent_id,
				"status_id": new_status_id,
				"approval_level": None,
				"updated_by": user_id,
				"updated_date_time": updated_at,
				"indent_no": None,  # Don't update indent_no
			}
		)
		db.commit()
		
		return {
			"status": "success",
			"new_status_id": new_status_id,
			"message": f"Indent reopened successfully (status: {new_status_id}).",
		}
	except HTTPException:
		db.rollback()
		raise
	except Exception as e:
		db.rollback()
		logger.exception("Error reopening indent")
		raise HTTPException(status_code=500, detail=str(e))


@router.post("/send_indent_for_approval")
def send_indent_for_approval(
	payload: dict,
	db: Session = Depends(get_tenant_db),
	token_data: dict = Depends(get_current_user_with_refresh),
):
	"""Send indent for approval (change status from 1 Open to 20 Pending Approval, set approval_level to 1)."""
	try:
		indent_id = payload.get("indent_id")
		branch_id = payload.get("branch_id")
		menu_id = payload.get("menu_id")
		
		if not indent_id:
			raise HTTPException(status_code=400, detail="indent_id is required")
		if not branch_id:
			raise HTTPException(status_code=400, detail="branch_id is required")
		if not menu_id:
			raise HTTPException(status_code=400, detail="menu_id is required")
		
		try:
			indent_id = int(indent_id)
			branch_id = int(branch_id)
			menu_id = int(menu_id)
		except (TypeError, ValueError):
			raise HTTPException(status_code=400, detail="Invalid indent_id, branch_id, or menu_id")
		
		user_id = int(token_data.get("user_id"))
		
		# Get indent details
		indent_query = get_indent_with_approval_info()
		indent_result = db.execute(indent_query, {"indent_id": indent_id}).fetchone()
		if not indent_result:
			raise HTTPException(status_code=404, detail="Indent not found")
		
		indent = dict(indent_result._mapping)
		current_status_id = indent.get("status_id")
		
		# Verify current status is Open (1)
		if current_status_id != 1:
			raise HTTPException(
				status_code=400,
				detail=f"Cannot send for approval indent with status_id {current_status_id}. Expected status 1 (Open)."
			)
		
		# Update status to Pending Approval (20) with level 1
		updated_at = now_ist()
		update_query = update_indent_status()
		db.execute(
			update_query,
			{
				"indent_id": indent_id,
				"status_id": 20,  # Pending Approval
				"approval_level": 1,  # Start at level 1
				"updated_by": user_id,
				"updated_date_time": updated_at,
				"indent_no": None,  # Don't update indent_no
			}
		)
		db.commit()
		
		return {
			"status": "success",
			"new_status_id": 20,
			"new_approval_level": 1,
			"message": "Indent sent for approval successfully.",
		}
	except HTTPException:
		db.rollback()
		raise
	except Exception as e:
		db.rollback()
		logger.exception("Error sending indent for approval")
		raise HTTPException(status_code=500, detail=str(e))


@router.post("/reject_indent")
def reject_indent(
	payload: dict,
	db: Session = Depends(get_tenant_db),
	token_data: dict = Depends(get_current_user_with_refresh),
):
	"""Reject an indent (change status from 20 Pending Approval to 4 Rejected)."""
	try:
		indent_id = payload.get("indent_id")
		co_id = payload.get("co_id")
		reason = payload.get("reason", "")
		menu_id = payload.get("menu_id")

		if not indent_id:
			raise HTTPException(status_code=400, detail="indent_id is required")
		if not co_id:
			raise HTTPException(status_code=400, detail="co_id is required")

		try:
			indent_id = int(indent_id)
			co_id = int(co_id)
			if menu_id is not None:
				menu_id = int(menu_id)
		except (TypeError, ValueError):
			raise HTTPException(status_code=400, detail="Invalid indent_id, co_id, or menu_id")

		user_id = int(token_data.get("user_id"))

		result = process_rejection(
			doc_id=indent_id,
			user_id=user_id,
			menu_id=menu_id,
			db=db,
			get_doc_fn=get_indent_with_approval_info,
			update_status_fn=update_indent_status,
			id_param_name="indent_id",
			doc_name="Indent",
			reason=reason,
			extra_update_params={"indent_no": None},
		)

		return result
	except HTTPException:
		raise
	except Exception as e:
		logger.exception("Error rejecting indent")
		raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# DOWNLOAD ENDPOINT
# =============================================================================

_INDENT_TABLE_COLUMNS = [
	("Indent No", "indent_no"),
	("Date", "indent_date"),
	("Branch", "branch_name"),
	("Expense Type", "expense_type"),
	("Status", "status"),
]


@router.get("/download_indent_table")
def download_indent_table(
	request: Request,
	db: Session = Depends(get_tenant_db),
	token_data: dict = Depends(get_current_user_with_refresh),
	format: str | None = None,
	search: str | None = None,
	co_id: int | None = None,
	branch_id: int | None = None,
):
	"""Download the indent table as xlsx or pdf.

	Mirrors the listing endpoint's filters (co_id, branch_id, search) but is
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
			"branch_id": int(branch_id) if branch_id else None,
			"search_like": search_like,
			"limit": _INDENT_DOWNLOAD_MAX_ROWS,
			"offset": 0,
		}

		rows = db.execute(get_indent_table_query(), params).fetchall()

		data = []
		for row in rows:
			mapped = dict(row._mapping)
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
					logger.exception("Error formatting indent number in download")
					formatted_indent_no = str(raw_indent_no)

			data.append({
				"indent_no": formatted_indent_no,
				"indent_date": indent_date,
				"branch_name": mapped.get("branch_name") or "",
				"expense_type": mapped.get("expense_type_name") or "",
				"status": mapped.get("status_name") or "",
			})

		today_str = date.today().isoformat()
		title = "Indent List"
		if fmt == "xlsx":
			buf = build_xlsx(data, _INDENT_TABLE_COLUMNS, sheet_name=title[:31])
			media_type = _INDENT_XLSX_MEDIA_TYPE
			ext = "xlsx"
		else:
			buf = build_pdf(data, _INDENT_TABLE_COLUMNS, title=title)
			media_type = _INDENT_PDF_MEDIA_TYPE
			ext = "pdf"

		return StreamingResponse(
			buf,
			media_type=media_type,
			headers={
				"Content-Disposition": f'attachment; filename="indent-table-{today_str}.{ext}"'
			},
		)

	except HTTPException:
		raise
	except Exception as e:
		logger.exception("Error downloading indent table")
		raise HTTPException(status_code=500, detail=f"Error downloading indent table: {str(e)}")