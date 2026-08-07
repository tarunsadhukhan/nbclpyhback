from fastapi import Depends, Request, HTTPException, APIRouter
from fastapi.responses import StreamingResponse
import logging
import math
from sqlalchemy.orm import Session
from sqlalchemy.sql import text
from datetime import datetime, date
from src.common.utils import now_ist
from typing import Optional
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.procurement.query import (
	get_po_table_query,
	get_po_table_count_query,
	get_suppliers_with_party_type_1,
	get_supplier_branches,
	get_all_supplier_branches_bulk,
	get_company_branch_addresses,
	get_indent_line_items_for_po,
	insert_proc_po,
	insert_proc_po_dtl,
	insert_proc_po_additional,
	insert_po_gst,
	update_proc_po,
	delete_proc_po_dtl,
	delete_proc_po_additional,
	delete_po_gst,
	get_po_by_id_query,
	get_po_dtl_by_id_query,
	get_po_additional_by_id_query,
	get_po_gst_by_id_query,
	get_max_po_no_for_branch_fy,
	get_po_with_approval_info,
	update_po_status,
	get_po_consumed_amounts,
	get_item_by_group_id_purchaseable,
	get_item_make_by_group_id,
	get_item_uom_by_group_id,
	get_last_purchase_rates_by_item_group,
	get_expense_types,
	get_project,
	get_po_header_query,
	get_po_dtl_query,
	get_additional_charges_mst_list,
	# Validation queries (v2 — reads from pre-aggregated views)
	get_item_validation_data_v2,
	get_item_fy_indent_check_v2,
	get_expense_type_name_by_id,
	# PO-specific validation queries (v2)
	get_outstanding_po_qty_v2,
	check_open_po_for_item_v2,
	get_po_fy_check_v2,
	# In-place update queries
	update_proc_po_dtl,
	delete_po_gst_by_dtl_id,
	delete_po_gst_for_additional_charges,
	# Edit-mode validation queries
	get_current_po_item_outstanding,
	check_open_po_for_item_v2_exclude,
	get_po_fy_check_v2_exclude,
)
from src.masters.query import (
	get_branch_list,
	get_dept_list_by_branch_id,
	get_item_group_drodown,
)
from src.sales.query import get_brokers_for_sales
from src.common.companyAdmin.query import get_co_config_by_id_query
from src.procurement.indent import (
	format_indent_no,
	calculate_financial_year,
	get_fy_boundaries,
)
from src.procurement.export_helpers import build_xlsx, build_pdf


_PO_XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_PO_PDF_MEDIA_TYPE = "application/pdf"
_PO_DOWNLOAD_MAX_ROWS = 50000

# =============================================================================
# PO-SPECIFIC VALIDATION HELPERS
# =============================================================================

# Mapping: (po_type, expense_type_name) -> validation logic
# Logic 1: Max/Min Quantity Validation with Stock Check
# Logic 2: FY Check + max qty as forced value (requires min/max)
# Logic 3: No Validation / Free Entry
#
# NOTE: This differs from the indent VALIDATION_LOGIC_MAP in two key ways:
#   - Regular + Capital -> Logic 3 (indent uses Logic 2)
#   - Open + General/Maintenance/Production -> Logic 2 (indent uses Logic 3)
PO_VALIDATION_LOGIC_MAP = {
	# Regular PO
	("Regular", "General"): 1,
	("Regular", "Maintenance"): 1,
	("Regular", "Production"): 1,
	("Regular", "Overhaul"): 1,
	("Regular", "Capital"): 3,
	# Open PO — FY check + forced max qty
	("Open", "General"): 2,
	("Open", "Maintenance"): 2,
	("Open", "Production"): 2,
}


def determine_po_validation_logic(po_type: str, expense_type_name: str) -> int:
	"""Determine which validation logic applies for PO based on po_type + expense type."""
	return PO_VALIDATION_LOGIC_MAP.get((po_type, expense_type_name), 3)
from src.common.approval_utils import (
	process_approval,
	process_rejection,
	calculate_approval_permissions,
)
from src.procurement.query import (
	get_approval_flow_by_menu_branch,
)
from src.common.utils import parse_json_body

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/get_po_setup_1")
def get_po_setup_1(
	request: Request,
	db: Session = Depends(get_tenant_db),
	token_data: dict = Depends(get_current_user_with_refresh),
	branch_id: int | None = None,
	co_id: int | None = None,
):
	"""Return branches, suppliers, projects, expense types (category types), co_config, and branch addresses for PO creation."""
	try:
		# Get query parameters
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

		# Branch list
		branch_ids_list = [branch_id] if branch_id is not None else None
		branchquery = get_branch_list(branch_ids=branch_ids_list) if branch_ids_list else get_branch_list()
		branch_result = db.execute(branchquery, {"branch_ids": branch_ids_list} if branch_ids_list else {}).fetchall()
		branches = [dict(r._mapping) for r in branch_result]

		# Suppliers (party_type_id contains 1)
		supplier_query = get_suppliers_with_party_type_1(co_id=co_id)
		supplier_result = db.execute(supplier_query, {"co_id": co_id}).fetchall()
		suppliers = [dict(r._mapping) for r in supplier_result]

		# Projects (expects branch_id)
		projects = []
		if branch_id is not None:
			project_query = get_project(branch_id=branch_id)
			proj_result = db.execute(project_query, {"branch_id": branch_id}).fetchall()
			projects = [dict(r._mapping) for r in proj_result]

		# Expense types (category types)
		expense_query = get_expense_types()
		exp_result = db.execute(expense_query).fetchall()
		expense_types = [dict(r._mapping) for r in exp_result]

		# Co config
		co_config_query = get_co_config_by_id_query(co_id)
		co_config_result = db.execute(co_config_query, {"co_id": co_id}).fetchone()
		co_config = dict(co_config_result._mapping) if co_config_result else {}

		indent_required_value = co_config.get("indent_required") if co_config else None
		if isinstance(indent_required_value, str):
			indent_required_enabled = indent_required_value.strip().lower() not in {"0", "false", "no", ""}
		else:
			indent_required_enabled = bool(indent_required_value)

		item_groups = []
		if not indent_required_enabled:
			itemgrp_query = get_item_group_drodown(co_id=co_id)
			itemgrp_result = db.execute(itemgrp_query, {"co_id": co_id}).fetchall()
			item_groups = [dict(r._mapping) for r in itemgrp_result]

		# Company branch addresses (for billing and shipping)
		# Filter by co_id only (not branch_id) to show all company branch addresses
		branch_addresses_query = get_company_branch_addresses(co_id=co_id, branch_id=None)
		branch_addresses_result = db.execute(branch_addresses_query, {"co_id": co_id, "branch_id": None}).fetchall()
		branch_addresses = [dict(r._mapping) for r in branch_addresses_result]
		
		# Get ALL supplier branch addresses in a single bulk query (avoids N+1 query problem)
		# This is much faster than fetching branches for each supplier individually
		all_branches_query = get_all_supplier_branches_bulk(co_id=co_id)
		all_branches_result = db.execute(all_branches_query, {"co_id": co_id}).fetchall()
		
		# Group branches by party_id
		branches_by_party: dict[int, list[dict]] = {}
		for row in all_branches_result:
			branch_dict = dict(row._mapping)
			party_id = branch_dict.get("party_id")
			if party_id is not None:
				if party_id not in branches_by_party:
					branches_by_party[party_id] = []
				branches_by_party[party_id].append(branch_dict)
		
		# Attach branches to each supplier
		for supplier in suppliers:
			supplier_id = supplier.get("party_id")
			supplier["branches"] = branches_by_party.get(supplier_id, [])

		# Brokers
		broker_query = get_brokers_for_sales(co_id=co_id)
		broker_result = db.execute(broker_query, {"co_id": co_id}).fetchall()
		brokers = [dict(r._mapping) for r in broker_result]

		# Additional charges master list
		additional_charges_query = get_additional_charges_mst_list()
		additional_charges_result = db.execute(additional_charges_query).fetchall()
		additional_charges_options = [dict(r._mapping) for r in additional_charges_result]

		return {
			"branches": branches,
			"suppliers": suppliers,  # Now includes full supplier details and their branch addresses
			"brokers": brokers,
			"projects": projects,
			"expense_types": expense_types,
			"co_config": co_config,
			"branch_addresses": branch_addresses,  # Company branch addresses for billing and shipping
			"item_groups": item_groups,
			"additional_charges_options": additional_charges_options,
		}
	except HTTPException:
		raise
	except Exception as e:
		logger.exception("Error fetching PO setup 1")
		raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_po_setup_2")
def get_po_setup_2(
	request: Request,
	db: Session = Depends(get_tenant_db),
	token_data: dict = Depends(get_current_user_with_refresh),
):
	"""Return items, makes, and UOMs by item_group_id (reuse from indent setup)."""
	try:
		q_item_group = request.query_params.get("item_group")
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

		# Get item group info (code and name)
		item_group_query = text("""
			SELECT item_grp_code, item_grp_name
			FROM item_grp_mst
			WHERE item_grp_id = :item_group_id
		""")
		item_group_result = db.execute(item_group_query, {"item_group_id": item_group_id}).fetchone()
		item_grp_code = item_group_result.item_grp_code if item_group_result else None
		item_grp_name = item_group_result.item_grp_name if item_group_result else None

		# Get items purchasable in this group
		items_query = get_item_by_group_id_purchaseable(item_group_id=item_group_id)
		items_result = db.execute(items_query, {"item_group_id": item_group_id}).fetchall()
		items = [dict(r._mapping) for r in items_result]

		# Get item makes for this group
		makes_query = get_item_make_by_group_id(item_group_id=item_group_id)
		makes_result = db.execute(makes_query, {"item_group_id": item_group_id}).fetchall()
		makes = [dict(r._mapping) for r in makes_result]

		# Get item uom mappings for this group
		uoms_query = get_item_uom_by_group_id(item_group_id=item_group_id)
		uoms_result = db.execute(uoms_query, {"item_group_id": item_group_id}).fetchall()
		uoms = [dict(r._mapping) for r in uoms_result]

		# Enrich items with last purchase rate if co_id is provided
		co_id = request.query_params.get("co_id")
		if co_id:
			rates_query = get_last_purchase_rates_by_item_group()
			rates_result = db.execute(rates_query, {
				"item_group_id": item_group_id, "co_id": int(co_id)
			}).fetchall()
			rates_map = {r._mapping["item_id"]: dict(r._mapping) for r in rates_result}
			for item in items:
				rate_info = rates_map.get(item["item_id"])
				if rate_info:
					item["last_purchase_rate"] = rate_info["last_purchase_rate"]
					item["last_purchase_date"] = str(rate_info["last_purchase_date"]) if rate_info["last_purchase_date"] else None
					item["last_supplier_name"] = rate_info["last_supplier_name"]
				else:
					item["last_purchase_rate"] = None
					item["last_purchase_date"] = None
					item["last_supplier_name"] = None

		return {
			"item_grp_code": item_grp_code,
			"item_grp_name": item_grp_name,
			"items": items,
			"makes": makes,
			"uoms": uoms,
		}
	except HTTPException:
		raise
	except Exception as e:
		logger.exception("Error fetching PO setup 2")
		raise HTTPException(status_code=500, detail=str(e))


@router.get("/validate_item_for_po")
def validate_item_for_po(
	request: Request,
	db: Session = Depends(get_tenant_db),
	token_data: dict = Depends(get_current_user_with_refresh),
):
	"""
	Validate an item for direct PO creation.
	Returns validation data including errors, warnings, and allowable qty range
	based on (po_type + expense_type) → Logic 1, 2, or 3.

	Logic mapping (PO-specific — differs from indent):
	  Logic 1 (Regular + General/Maintenance/Production/Overhaul): Stock + max/min formula including outstanding_po_qty.
	  Logic 2 (Open + General/Maintenance/Production): FY PO check + max qty forced.
	  Logic 3 (Regular + Capital, others): No validation, free entry.
	"""
	try:
		branch_id = request.query_params.get("branch_id")
		item_id = request.query_params.get("item_id")
		po_type = request.query_params.get("po_type")  # "Regular" or "Open"
		expense_type_id = request.query_params.get("expense_type_id")
		po_id_raw = request.query_params.get("po_id")  # Optional — for edit mode

		if not branch_id:
			raise HTTPException(status_code=400, detail="branch_id is required")
		if not item_id:
			raise HTTPException(status_code=400, detail="item_id is required")
		if not po_type:
			raise HTTPException(status_code=400, detail="po_type is required")
		if not expense_type_id:
			raise HTTPException(status_code=400, detail="expense_type_id is required")

		try:
			branch_id = int(branch_id)
			item_id = int(item_id)
			expense_type_id = int(expense_type_id)
		except (TypeError, ValueError) as e:
			raise HTTPException(status_code=400, detail=f"Invalid parameter format: {e}")

		po_id = None
		if po_id_raw:
			try:
				po_id = int(po_id_raw)
			except (TypeError, ValueError):
				raise HTTPException(status_code=400, detail="Invalid po_id format")

		po_type = po_type.strip().capitalize()
		if po_type not in ("Regular", "Open"):
			raise HTTPException(status_code=400, detail=f"Invalid po_type '{po_type}'. Must be 'Regular' or 'Open'.")

		# Resolve expense type name
		expense_row = db.execute(
			get_expense_type_name_by_id(),
			{"expense_type_id": expense_type_id},
		).fetchone()
		if not expense_row:
			raise HTTPException(status_code=400, detail=f"Invalid expense_type_id: {expense_type_id}")
		expense_type_name = dict(expense_row._mapping)["expense_type_name"]

		# Determine validation logic using PO-specific mapping
		validation_logic = determine_po_validation_logic(po_type, expense_type_name)

		result = {
			"validation_logic": validation_logic,
			"po_type": po_type,
			"expense_type_name": expense_type_name,
			"errors": [],
			"warnings": [],
			# Logic 1 fields
			"branch_stock": None,
			"outstanding_indent_qty": None,
			"outstanding_po_qty": None,
			"minqty": None,
			"maxqty": None,
			"min_order_qty": None,
			"has_open_indent": False,
			"has_open_po": False,
			"stock_exceeds_max": False,
			"max_po_qty": None,
			"min_po_qty": None,
			# Logic 2 fields
			"fy_po_exists": False,
			"fy_po_no": None,
			"fy_indent_exists": False,
			"fy_indent_no": None,
			"has_minmax": False,
			"regular_bom_outstanding": None,
			"forced_qty": None,
		}

		if validation_logic == 3:
			# No validation — free entry
			return result

		today = date.today()
		fy_start, fy_end = get_fy_boundaries(today)

		# Fetch common item validation data (stock, min/max, outstanding, pre-computed limits)
		vdata_row = db.execute(
			get_item_validation_data_v2(),
			{"branch_id": branch_id, "item_id": item_id},
		).fetchone()

		vdata = dict(vdata_row._mapping) if vdata_row else {}
		branch_stock = float(vdata.get("branch_stock") or 0)
		outstanding_indent = float(vdata.get("outstanding_indent_qty") or 0)
		outstanding_po = float(vdata.get("outstanding_po_qty") or 0)
		regular_bom_outstanding_val = float(vdata.get("regular_bom_outstanding") or 0)
		minqty = vdata.get("minqty")
		maxqty = vdata.get("maxqty")
		min_order_qty = vdata.get("min_order_qty")
		# Pre-computed PO validation limits from view (sentinel: -2=open PO outstanding, -1=no minmax, >=0=limit)
		view_max_po = float(vdata.get("max_po_qty", -1))
		view_min_po = float(vdata.get("min_po_qty", -1))

		# ── Edit-mode adjustment ──
		# When editing an existing PO, the view already includes this PO's qty.
		# Subtract it so validation treats the current PO line as "not yet committed".
		current_po_outstanding = 0.0
		if po_id:
			cpo_row = db.execute(
				get_current_po_item_outstanding(),
				{"po_id": po_id, "item_id": item_id, "branch_id": branch_id},
			).fetchone()
			if cpo_row:
				current_po_outstanding = float(dict(cpo_row._mapping).get("current_po_outstanding", 0))
			outstanding_po = max(outstanding_po - current_po_outstanding, 0.0)

		result["branch_stock"] = branch_stock
		result["outstanding_indent_qty"] = outstanding_indent
		result["outstanding_po_qty"] = outstanding_po
		result["minqty"] = float(minqty) if minqty is not None else None
		result["maxqty"] = float(maxqty) if maxqty is not None else None
		result["min_order_qty"] = float(min_order_qty) if min_order_qty is not None else None

		# When editing, recalculate max/min PO qty instead of using pre-computed view values
		if po_id and validation_logic == 1:
			_maxqty = float(maxqty) if maxqty else 0
			_minqty = float(minqty) if minqty else 0
			_reorder = float(min_order_qty) if min_order_qty else 0

			if _maxqty <= 0:
				# No max configured — free entry (sentinel -1 behavior)
				view_max_po = -1
				view_min_po = -1
			else:
				available = _maxqty - branch_stock - outstanding_indent - outstanding_po
				if available <= 0:
					view_max_po = 0
					view_min_po = _minqty if _minqty > 0 else -1
				elif _reorder <= 0:
					# No reorder qty — use available directly
					view_max_po = available
					view_min_po = _minqty if _minqty > 0 else -1
				else:
					if available < _reorder:
						view_max_po = _reorder
					else:
						view_max_po = math.ceil(available / _reorder) * _reorder
					view_min_po = _minqty if _minqty > 0 else -1

		if validation_logic == 1:
			# --- Logic 1: Max/Min + Stock Check (Regular PO, non-Capital expense) ---
			# Pre-computed view columns handle sentinel values:
			#   -2 = open PO outstanding exists (warning)
			#   -1 = no minmax configured (free entry)
			#   >= 0 = computed limit (enforce)

			# Step 1: Check if an open indent already exists for this item at this branch
			open_indent_row = db.execute(
				get_item_fy_indent_check_v2(),
				{"branch_id": branch_id, "item_id": item_id, "fy_start": fy_start, "fy_end": fy_end},
			).fetchone()

			if open_indent_row:
				open_indent_data = dict(open_indent_row._mapping)
				result["has_open_indent"] = True
				result["errors"].append(
					f"An open indent (#{open_indent_data.get('indent_no')}) already exists for this item. "
					f"Please use the indent-based PO route instead."
				)
				return result

			# Step 2: Check if an active PO already exists for this item at this branch
			# This is a non-blocking warning — the user may still create a new PO.
			# Exclude the current PO during edit to avoid self-blocking.
			if po_id:
				open_po_row = db.execute(
					check_open_po_for_item_v2_exclude(),
					{"branch_id": branch_id, "item_id": item_id, "exclude_po_id": po_id},
				).fetchone()
			else:
				open_po_row = db.execute(
					check_open_po_for_item_v2(),
					{"branch_id": branch_id, "item_id": item_id},
				).fetchone()

			if open_po_row:
				open_po_data = dict(open_po_row._mapping)
				result["has_open_po"] = True
				result["warnings"].append(
					f"An active PO (#{open_po_data.get('po_no')}) already exists for this item. "
					f"Please resolve the existing PO before creating a new one."
				)

			# Step 3: Use pre-computed max/min from view with sentinel handling
			if view_max_po == -2:
				# Sentinel: open PO outstanding exists — warn but allow
				result["has_open_po"] = True
				result["has_minmax"] = True
				result["max_po_qty"] = None  # Cannot determine — open outstanding muddies the picture
				result["min_po_qty"] = None
				result["warnings"].append(
					f"Open PO outstanding ({float(vdata.get('open_po_outstanding', 0))}) exists "
					f"for this item. Max PO qty cannot be precisely calculated."
				)
			elif view_max_po == -1:
				# No max qty configured — free entry allowed
				result["has_minmax"] = False
			elif view_max_po == 0:
				# Computed limit is zero — stock + outstanding already meets/exceeds max
				result["has_minmax"] = True
				result["stock_exceeds_max"] = True
				result["max_po_qty"] = 0
				result["min_po_qty"] = view_min_po if view_min_po >= 0 else None
				result["errors"].append(
					f"Branch stock ({branch_stock}) + outstanding PO qty ({outstanding_po}) "
					f"already meets or exceeds max qty ({float(maxqty) if maxqty else 0}). Cannot create PO."
				)
			else:
				# view_max_po > 0: valid computed limit
				result["has_minmax"] = True
				result["max_po_qty"] = view_max_po
				result["min_po_qty"] = view_min_po if view_min_po >= 0 else None

		elif validation_logic == 2:
			# --- Logic 2: Open Entry + FY Check (Open PO, General/Maintenance/Production) ---

			# Step 1: Check if an open PO already exists for this item in current FY
			# Exclude the current PO during edit to avoid self-blocking.
			if po_id:
				fy_po_row = db.execute(
					get_po_fy_check_v2_exclude(),
					{"branch_id": branch_id, "item_id": item_id, "fy_start": fy_start, "fy_end": fy_end, "exclude_po_id": po_id},
				).fetchone()
			else:
				fy_po_row = db.execute(
					get_po_fy_check_v2(),
					{"branch_id": branch_id, "item_id": item_id, "fy_start": fy_start, "fy_end": fy_end},
				).fetchone()

			if fy_po_row:
				fy_po_data = dict(fy_po_row._mapping)
				result["fy_po_exists"] = True
				result["fy_po_no"] = fy_po_data.get("po_no")
				result["errors"].append(
					f"An open PO (#{fy_po_data.get('po_no')}) already exists for this item "
					f"in the current financial year ({fy_start.strftime('%d-%b-%Y')} to {fy_end.strftime('%d-%b-%Y')})."
				)

			# Step 2: Check if an open indent exists in current FY (warning only)
			fy_indent_row = db.execute(
				get_item_fy_indent_check_v2(),
				{"branch_id": branch_id, "item_id": item_id, "fy_start": fy_start, "fy_end": fy_end},
			).fetchone()

			if fy_indent_row:
				fy_indent_data = dict(fy_indent_row._mapping)
				result["fy_indent_exists"] = True
				result["fy_indent_no"] = fy_indent_data.get("indent_no")
				result["warnings"].append(
					f"An open indent (#{fy_indent_data.get('indent_no')}) exists for this item "
					f"in the current financial year. Consider using indent-based PO."
				)

			# Step 3: Check if max/min exists (required for Open PO)
			if maxqty is None and minqty is None:
				result["has_minmax"] = False
				result["errors"].append(
					"No max/min quantity defined for this item. Cannot create an Open PO."
				)
			else:
				result["has_minmax"] = True

			# Step 4: Check for Regular/BOM outstanding indent qty (warning only)
			# Already fetched from the aggregate view (regular_bom_outstanding_val)
			result["regular_bom_outstanding"] = regular_bom_outstanding_val
			if regular_bom_outstanding_val > 0:
				result["warnings"].append(
					f"Outstanding indent qty ({regular_bom_outstanding_val}) exists from Regular/BOM indents for this item."
				)

			# Step 5: Force qty to maxqty
			if maxqty is not None:
				result["forced_qty"] = float(maxqty)

		return result

	except HTTPException:
		raise
	except Exception as e:
		logger.exception("Error validating item for PO")
		raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_indent_line_items")
def get_indent_line_items(
	request: Request,
	db: Session = Depends(get_tenant_db),
	token_data: dict = Depends(get_current_user_with_refresh),
):
	"""Get line items for an indent to be used in PO creation popup."""
	try:
		q_indent_id = request.query_params.get("indent_id")
		if q_indent_id is None:
			raise HTTPException(status_code=400, detail="indent_id is required")

		try:
			indent_id = int(q_indent_id)
		except Exception:
			raise HTTPException(status_code=400, detail="Invalid indent_id")

		indent_line_items_query = get_indent_line_items_for_po(indent_id=indent_id)
		line_items_result = db.execute(indent_line_items_query, {"indent_id": indent_id}).fetchall()
		line_items = []
		for r in line_items_result:
			item = dict(r._mapping)
			# Format indent_no using the formatter
			raw_indent_no = item.get("indent_no")
			if raw_indent_no is not None and raw_indent_no != 0:
				try:
					item["indent_no"] = format_indent_no(
						indent_no=int(raw_indent_no),
						co_prefix=item.get("co_prefix"),
						branch_prefix=item.get("branch_prefix"),
						indent_date=item.get("indent_date"),
						document_type="INDENT",
					)
				except Exception:
					logger.exception("Error formatting indent number in PO line items")
					item["indent_no"] = str(raw_indent_no)
			line_items.append(item)

		return {
			"indent_id": indent_id,
			"expenseType": str(line_items[0].get("expense_type_id", "")) if line_items and line_items[0].get("expense_type_id") else "",
			"line_items": line_items,
		}
	except HTTPException:
		raise
	except Exception as e:
		logger.exception("Error fetching indent line items")
		raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_supplier_branches")
def get_supplier_branches_api(
	request: Request,
	db: Session = Depends(get_tenant_db),
	token_data: dict = Depends(get_current_user_with_refresh),
):
	"""Get branch addresses for a selected supplier."""
	try:
		q_party_id = request.query_params.get("party_id")
		if q_party_id is None:
			raise HTTPException(status_code=400, detail="party_id is required")

		try:
			party_id = int(q_party_id)
		except Exception:
			raise HTTPException(status_code=400, detail="Invalid party_id")

		supplier_branches_query = get_supplier_branches(party_id=party_id)
		branches_result = db.execute(supplier_branches_query, {"party_id": party_id}).fetchall()
		branches = [dict(r._mapping) for r in branches_result]

		return {
			"party_id": party_id,
			"branches": branches,
		}
	except HTTPException:
		raise
	except Exception as e:
		logger.exception("Error fetching supplier branches")
		raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_po_table")
def get_po_table(
	request: Request,
	db: Session = Depends(get_tenant_db),
	token_data: dict = Depends(get_current_user_with_refresh),
	page: int = 1,
	limit: int = 10,
	search: str | None = None,
	co_id: int | None = None,
):
	"""Return paginated procurement purchase order list."""

	try:
		page = max(page, 1)
		limit = max(min(limit, 100), 1)
		offset = (page - 1) * limit
		search_like = None
		if search:
			search_like = f"%{search.strip()}%"

		params = {
			"co_id": co_id,
			"search_like": search_like,
			"limit": limit,
			"offset": offset,
		}

		list_query = get_po_table_query()
		rows = db.execute(list_query, params).fetchall()
		data = []
		for row in rows:
			mapped = dict(row._mapping)
			po_date_obj = mapped.get("po_date")
			po_date = po_date_obj.isoformat() if hasattr(po_date_obj, "isoformat") else po_date_obj
			
			po_value = mapped.get("po_value")
			if po_value is not None:
				try:
					po_value = float(po_value)
				except (TypeError, ValueError):
					po_value = None
			
			# Format po_no using helper
			formatted_po_no = extract_formatted_po_no(mapped)
			
			data.append(
				{
					"po_id": mapped.get("po_id"),
					"po_no": formatted_po_no,
					"po_date": po_date,
					"supplier_name": mapped.get("supp_name") or "",
					"po_value": po_value,
					"branch_id": mapped.get("branch_id"),
					"branch_name": mapped.get("branch_name") or "",
					"project_name": mapped.get("project_name") or None,
					"status": mapped.get("status_name") or "Pending",
				}
			)

		count_query = get_po_table_count_query()
		count_result = db.execute(count_query, params).scalar()
		total = int(count_result) if count_result is not None else 0

		return {"data": data, "total": total}
	except HTTPException:
		raise
	except Exception as e:
		logger.exception("Error fetching PO table")
		raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


# ==================== HELPER FUNCTIONS ====================

def format_po_no(
	po_no: Optional[int],
	co_prefix: Optional[str],
	branch_prefix: Optional[str],
	po_date,
) -> str:
	"""Format PO number as "co_prefix/branch_prefix/PO/financial_year/po_no"."""
	if po_no is None or po_no == 0:
		return ""
	
	fy = calculate_financial_year(po_date)
	co_pref = co_prefix or ""
	branch_pref = branch_prefix or ""
	
	parts = []
	if co_pref:
		parts.append(co_pref)
	if branch_pref:
		parts.append(branch_pref)
	parts.extend(["PO", fy, str(po_no)])
	
	return "/".join(parts)


def extract_formatted_po_no(
	mapped: dict,
	po_no_key: str = "po_no",
	po_date_key: str = "po_date",
) -> str:
	"""Extract and format PO number from a mapped row.
	
	This helper extracts po_no, co_prefix, branch_prefix, and po_date from a 
	mapped database row and returns the formatted PO number string.
	
	Args:
		mapped: Dictionary from database row (dict(row._mapping))
		po_no_key: Key for raw PO number in mapped dict (default: "po_no")
		po_date_key: Key for PO date in mapped dict (default: "po_date")
	
	Returns:
		Formatted PO number string or empty string if po_no is None/0
	"""
	raw_po_no = mapped.get(po_no_key)
	if raw_po_no is None or raw_po_no == 0:
		return ""
	
	try:
		po_no_int = int(raw_po_no) if str(raw_po_no).isdigit() else None
		if po_no_int is None:
			return str(raw_po_no) if raw_po_no else ""
		
		co_prefix = mapped.get("co_prefix")
		branch_prefix = mapped.get("branch_prefix")
		po_date = mapped.get(po_date_key)
		
		formatted = format_po_no(
			po_no=po_no_int,
			co_prefix=co_prefix,
			branch_prefix=branch_prefix,
			po_date=po_date,
		)
		return formatted if formatted else str(raw_po_no)
	except Exception:
		return str(raw_po_no) if raw_po_no else ""


def calculate_gst_amounts(
	amount: float,
	tax_percentage: float,
	source_state_id: int,
	destination_state_id: int,
) -> dict:
	"""Calculate GST amounts based on source (supplier) and destination (shipping) states.
	
	Returns dict with:
	- i_tax_percentage: IGST percentage
	- s_tax_percentage: SGST percentage (if same state)
	- c_tax_percentage: CGST percentage (if same state)
	- i_tax_amount: IGST amount
	- s_tax_amount: SGST amount
	- c_tax_amount: CGST amount
	- tax_amount: Total tax amount
	"""
	if source_state_id == destination_state_id:
		# Same state: Split tax into SGST and CGST (each half)
		sgst_pct = tax_percentage / 2.0
		cgst_pct = tax_percentage / 2.0
		igst_pct = 0.0
		sgst_amt = round((amount * sgst_pct) / 100.0, 2)
		cgst_amt = round((amount * cgst_pct) / 100.0, 2)
		igst_amt = 0.0
	else:
		# Different state: Full tax as IGST
		igst_pct = tax_percentage
		sgst_pct = 0.0
		cgst_pct = 0.0
		igst_amt = round((amount * igst_pct) / 100.0, 2)
		sgst_amt = 0.0
		cgst_amt = 0.0

	total_tax = round(igst_amt + sgst_amt + cgst_amt, 2)
	
	return {
		"i_tax_percentage": igst_pct,
		"s_tax_percentage": sgst_pct,
		"c_tax_percentage": cgst_pct,
		"i_tax_amount": igst_amt,
		"s_tax_amount": sgst_amt,
		"c_tax_amount": cgst_amt,
		"tax_amount": total_tax,
		"tax_pct": tax_percentage,
		"stax_percentage": sgst_pct + cgst_pct,  # Combined state tax
	}


def resolve_line_tax_percentage(item: dict, master_default: float) -> float:
	"""Resolve the effective tax % for a PO line item.

	The frontend may override the per-line tax percentage (including an explicit 0,
	which means "no tax"). A blank or absent value keeps the item_mst master default.
	Server-side GST is calculated from this resolved value, not the master.
	"""
	raw = item.get("tax_pct")
	if raw is None or str(raw).strip() == "":
		return master_default
	try:
		return float(raw)
	except (TypeError, ValueError):
		return master_default


# ==================== CRUD APIs ====================

@router.post("/create_po")
def create_po(
	payload: dict,
	db: Session = Depends(get_tenant_db),
	token_data: dict = Depends(get_current_user_with_refresh),
):
	"""Create a purchase order with line items, additional charges, and GST."""
	
	def to_int(value, field_name: str, required: bool = False) -> int | None:
		if value is None or value == "":
			if required:
				raise HTTPException(status_code=400, detail=f"{field_name} is required")
			return None
		try:
			return int(value)
		except (TypeError, ValueError):
			raise HTTPException(status_code=400, detail=f"Invalid {field_name}")

	def to_float(value, field_name: str, default: float = 0.0) -> float:
		if value is None or value == "":
			return default
		try:
			return float(value)
		except (TypeError, ValueError):
			return default

	try:
		# Header fields
		branch_id = to_int(payload.get("branch"), "branch", required=True)
		supplier_id = to_int(payload.get("supplier"), "supplier", required=True)
		supplier_branch_id = to_int(payload.get("supplier_branch"), "supplier_branch", required=True)
		billing_branch_id = to_int(payload.get("billing_address"), "billing_address", required=True)
		shipping_branch_id = to_int(payload.get("shipping_address"), "shipping_address", required=True)
		project_id = to_int(payload.get("project"), "project")
		# When a PO is created from a price enquiry, carry the source enquiry id
		# so the PO -> enquiry audit trail is preserved.
		price_enquiry_id = to_int(payload.get("price_enquiry_id"), "price_enquiry_id")
		
		date_str = payload.get("date")
		if not date_str:
			raise HTTPException(status_code=400, detail="date is required")
		try:
			po_date = datetime.strptime(str(date_str), "%Y-%m-%d").date()
		except ValueError:
			raise HTTPException(status_code=400, detail="Invalid date format, expected YYYY-MM-DD")

		credit_days = to_int(payload.get("credit_term"), "credit_term")
		expected_delivery_days = to_int(payload.get("delivery_timeline"), "delivery_timeline", required=True)
		contact_person = payload.get("contact_person", "").strip() or None
		contact_no = payload.get("contact_no", "").strip() or None
		footer_notes = payload.get("footer_note", "").strip() or None
		remarks = payload.get("internal_note", "").strip() or None
		terms_conditions = payload.get("terms_conditions", "").strip() or None
		expense_type_id = to_int(payload.get("expense_type"), "expense_type")
		po_type = payload.get("po_type", "").strip() or None
		
		advance_value = to_float(payload.get("advance_percentage"), "advance_percentage")
		
		# Get supplier and shipping state IDs for GST calculation
		supplier_branch_query = text(
			"""
			SELECT pbm.state_id
			FROM party_branch_mst pbm
			WHERE pbm.party_mst_branch_id = :branch_id
			"""
		)
		supplier_result = db.execute(supplier_branch_query, {"branch_id": supplier_branch_id}).fetchone()
		supplier_state_id = supplier_result[0] if supplier_result else None
		
		shipping_branch_query = text("SELECT state_id FROM branch_mst WHERE branch_id = :branch_id")
		shipping_result = db.execute(shipping_branch_query, {"branch_id": shipping_branch_id}).fetchone()
		shipping_state_id = shipping_result[0] if shipping_result else None
		
		# Get co_config to check india_gst
		branch_query = text("SELECT co_id FROM branch_mst WHERE branch_id = :branch_id")
		branch_result = db.execute(branch_query, {"branch_id": branch_id}).fetchone()
		co_id = branch_result[0] if branch_result else None
		
		india_gst = False
		if co_id:
			co_config_query = get_co_config_by_id_query(co_id)
			co_config_result = db.execute(co_config_query, {"co_id": co_id}).fetchone()
			if co_config_result:
				co_config = dict(co_config_result._mapping)
				india_gst = bool(co_config.get("india_gst", False))
		
		# Line items
		raw_items = payload.get("items", [])
		if not isinstance(raw_items, list) or len(raw_items) == 0:
			raise HTTPException(status_code=400, detail="At least one item row is required")
		
		# Additional charges
		raw_additional = payload.get("additional_charges", [])
		
		updated_by = to_int(token_data.get("user_id"), "updated_by")
		created_at = now_ist()

		# Calculate totals
		net_amount = 0.0
		total_igst = 0.0
		total_sgst = 0.0
		total_cgst = 0.0

		# Process line items
		normalized_items = []
		for idx, item in enumerate(raw_items, start=1):
			item_id = to_int(item.get("item"), f"items[{idx}].item", required=True)
			qty = to_float(item.get("quantity"), f"items[{idx}].quantity")
			if qty <= 0:
				raise HTTPException(status_code=400, detail=f"items[{idx}].quantity must be greater than zero")
			rate = to_float(item.get("rate"), f"items[{idx}].rate")
			uom_id = to_int(item.get("uom"), f"items[{idx}].uom", required=True)
			item_make_id = to_int(item.get("make"), f"items[{idx}].make")
			indent_dtl_id = to_int(item.get("indent_dtl_id"), f"items[{idx}].indent_dtl_id")

			# Get tax percentage from item_mst
			item_query = text("SELECT tax_percentage, hsn_code FROM item_mst WHERE item_id = :item_id")
			item_result = db.execute(item_query, {"item_id": item_id}).fetchone()
			tax_percentage = 0.0
			hsn_code = None
			if item_result:
				tax_percentage = float(item_result[0] or 0.0)
				hsn_code = item_result[1]

			# Frontend may override tax % per line (incl. explicit 0); blank keeps item_mst default.
			# Server-side GST below is computed from this resolved value.
			tax_percentage = resolve_line_tax_percentage(item, tax_percentage)

			# Allow frontend to override hsn_code
			frontend_hsn = item.get("hsn_code")
			if frontend_hsn is not None and str(frontend_hsn).strip():
				hsn_code = str(frontend_hsn).strip()

			# Discount calculation
			discount_mode = to_int(item.get("discount_mode"), f"items[{idx}].discount_mode")
			discount_value = to_float(item.get("discount_value"), f"items[{idx}].discount_value")
			discount_amount = 0.0

			base_amount = qty * rate
			if discount_mode == 1:  # Percentage
				if discount_value > 100:
					raise HTTPException(status_code=400, detail=f"items[{idx}].discount_value cannot be greater than 100")
				discount_amount = (base_amount * discount_value) / 100.0
			elif discount_mode == 2:  # Amount
				if discount_value > base_amount:
					raise HTTPException(status_code=400, detail=f"items[{idx}].discount_amount cannot be greater than total amount")
				discount_amount = discount_value

			amount = base_amount - discount_amount
			net_amount += amount

			# Calculate GST if india_gst is enabled (server-side calculation)
			if india_gst and tax_percentage > 0 and supplier_state_id and shipping_state_id:
				line_amount = float(amount)
				gst_amounts = calculate_gst_amounts(
					line_amount, tax_percentage, supplier_state_id, shipping_state_id
				)
				total_igst += gst_amounts["i_tax_amount"]
				total_sgst += gst_amounts["s_tax_amount"]
				total_cgst += gst_amounts["c_tax_amount"]
			else:
				gst_amounts = None

			remarks_raw = item.get("remarks", "").strip() or None

			normalized_items.append({
				"item_id": item_id,
				"qty": qty,
				"rate": rate,
				"uom_id": uom_id,
				"item_make_id": item_make_id,
				"indent_dtl_id": indent_dtl_id,
				"hsn_code": hsn_code,
				"discount_mode": discount_mode,
				"discount_value": discount_value,
				"discount_amount": discount_amount,
				"amount": amount,
				"remarks": remarks_raw,
				"tax_percentage": tax_percentage,
				"gst_amounts": gst_amounts,
			})

		# Process additional charges
		normalized_additional = []
		for idx, addl in enumerate(raw_additional, start=1):
			additional_charges_id = to_int(addl.get("additional_charges_id"), f"additional_charges[{idx}].additional_charges_id", required=True)
			qty = to_int(addl.get("qty"), f"additional_charges[{idx}].qty", required=True)
			rate = to_float(addl.get("rate"), f"additional_charges[{idx}].rate")
			net_amt = qty * rate
			net_amount += net_amt
			
			remarks_raw = addl.get("remarks", "").strip() or None
			
			# GST for additional charges (if applicable, respecting apply_tax flag)
			gst_amounts = None
			apply_tax = addl.get("apply_tax", True)  # default to True for backwards compat
			if india_gst and supplier_state_id and shipping_state_id and apply_tax:
				# Use frontend-sent tax_pct if provided, fallback to master default_value
				tax_pct = to_float(addl.get("tax_pct"), f"additional_charges[{idx}].tax_pct")
				if tax_pct <= 0:
					addl_query = text("SELECT default_value FROM additional_charges_mst WHERE additional_charges_id = :id")
					addl_result = db.execute(addl_query, {"id": additional_charges_id}).fetchone()
					tax_pct = float(addl_result[0] or 0.0) if addl_result else 0.0
				if tax_pct > 0:
					gst_amounts = calculate_gst_amounts(net_amt, tax_pct, supplier_state_id, shipping_state_id)
					total_igst += gst_amounts["i_tax_amount"]
					total_sgst += gst_amounts["s_tax_amount"]
					total_cgst += gst_amounts["c_tax_amount"]

			normalized_additional.append({
				"additional_charges_id": additional_charges_id,
				"qty": qty,
				"rate": rate,
				"net_amount": net_amt,
				"remarks": remarks_raw,
				"gst_amounts": gst_amounts,
			})

		total_amount = net_amount + total_igst + total_sgst + total_cgst
		advance_amount = (net_amount * advance_value) / 100.0 if advance_value > 0 else 0.0

		# Insert PO header
		insert_header_query = insert_proc_po()
		header_params = {
			"credit_days": credit_days,
			"delivery_instructions": None,
			"expected_delivery_days": expected_delivery_days,
			"footer_notes": footer_notes,
			"po_date": po_date,
			"po_approve_date": None,
			"po_no": None,  # Will be generated on open
			"remarks": remarks,
			"delivery_mode": None,
			"terms_conditions": terms_conditions,
			"branch_id": branch_id,
			"price_enquiry_id": price_enquiry_id,
			"project_id": project_id,
			"supplier_id": supplier_id,
			"status_id": 21,  # Drafted
			"supplier_branch_id": supplier_branch_id,
			"billing_branch_id": billing_branch_id,
			"shipping_branch_id": shipping_branch_id,
			"total_amount": total_amount,
			"net_amount": net_amount,
			"advance_type": 1 if advance_value > 0 else None,
			"advance_value": advance_value,
			"advance_amount": advance_amount,
			"contact_no": contact_no,
			"contact_person": contact_person,
			"updated_by": updated_by,
			"updated_date_time": created_at,
			"approval_level": None,
			"expense_type_id": expense_type_id,
			"po_type": po_type,
		}
		
		result = db.execute(insert_header_query, header_params)
		po_id = result.lastrowid
		if not po_id:
			raise HTTPException(status_code=500, detail="Failed to create PO header")
		
		# Insert line items
		detail_query = insert_proc_po_dtl()
		for item in normalized_items:
			detail_params = {
				"po_id": po_id,
				"item_id": item["item_id"],
				"hsn_code": item["hsn_code"],
				"item_make_id": item["item_make_id"],
				"qty": item["qty"],
				"rate": item["rate"],
				"uom_id": item["uom_id"],
				"remarks": item["remarks"],
				"discount_mode": item["discount_mode"],
				"discount_value": item["discount_value"],
				"discount_amount": item["discount_amount"],
				"active": 1,
				"indent_dtl_id": item["indent_dtl_id"],
				"updated_by": updated_by,
				"updated_date_time": created_at,
				"state": 1,
			}
			result = db.execute(detail_query, detail_params)
			po_dtl_id = result.lastrowid
			
			# Insert GST if applicable
			if india_gst and item["gst_amounts"]:
				gst_query = insert_po_gst()
				gst_params = {
					"po_dtl_id": po_dtl_id,
					"po_additional_id": None,
					"tax_pct": item["gst_amounts"]["tax_pct"],
					"stax_percentage": item["gst_amounts"]["stax_percentage"],
					"s_tax_amount": item["gst_amounts"]["s_tax_amount"],
					"i_tax_amount": item["gst_amounts"]["i_tax_amount"],
					"i_tax_percentage": item["gst_amounts"]["i_tax_percentage"],
					"c_tax_amount": item["gst_amounts"]["c_tax_amount"],
					"c_tax_percentage": item["gst_amounts"]["c_tax_percentage"],
					"tax_amount": item["gst_amounts"]["tax_amount"],
				}
				db.execute(gst_query, gst_params)
		
		# Insert additional charges
		additional_query = insert_proc_po_additional()
		for addl in normalized_additional:
			addl_params = {
				"po_id": po_id,
				"additional_charges_id": addl["additional_charges_id"],
				"qty": addl["qty"],
				"rate": addl["rate"],
				"net_amount": addl["net_amount"],
				"remarks": addl["remarks"],
			}
			result = db.execute(additional_query, addl_params)
			po_additional_id = result.lastrowid
			
			# Insert GST for additional charges if applicable
			if india_gst and addl["gst_amounts"]:
				gst_query = insert_po_gst()
				gst_params = {
					"po_dtl_id": None,
					"po_additional_id": po_additional_id,
					"tax_pct": addl["gst_amounts"]["tax_pct"],
					"stax_percentage": addl["gst_amounts"]["stax_percentage"],
					"s_tax_amount": addl["gst_amounts"]["s_tax_amount"],
					"i_tax_amount": addl["gst_amounts"]["i_tax_amount"],
					"i_tax_percentage": addl["gst_amounts"]["i_tax_percentage"],
					"c_tax_amount": addl["gst_amounts"]["c_tax_amount"],
					"c_tax_percentage": addl["gst_amounts"]["c_tax_percentage"],
					"tax_amount": addl["gst_amounts"]["tax_amount"],
				}
				db.execute(gst_query, gst_params)

		# A PO created from a price enquiry award completes that enquiry's
		# lifecycle: move the enquiry from Approved (3) to Closed (5). The
		# linkage is only honoured when the PO's supplier matches the awarded
		# response, so a losing quote cannot be silently converted.
		if price_enquiry_id:
			awarded = db.execute(
				text(
					"""SELECT supplier_id FROM proc_price_enquiry_response
					WHERE enquiry_id = :enquiry_id
						AND is_selected = 1
						AND active = 1
					LIMIT 1"""
				),
				{"enquiry_id": int(price_enquiry_id)},
			).fetchone()
			if not awarded:
				raise HTTPException(
					status_code=400,
					detail="No awarded response exists for the linked price enquiry",
				)
			if int(awarded[0]) != int(supplier_id):
				raise HTTPException(
					status_code=400,
					detail="PO supplier does not match the awarded response of the linked price enquiry",
				)
			db.execute(
				text(
					"""UPDATE proc_enquiry SET
						status_id = 5,
						updated_by = :updated_by,
						updated_date_time = :updated_date_time
					WHERE enquiry_id = :enquiry_id
						AND status_id = 3"""
				),
				{
					"enquiry_id": int(price_enquiry_id),
					"updated_by": updated_by,
					"updated_date_time": now_ist(),
				},
			)

		db.commit()
		return {
			"message": "PO created successfully",
			"po_id": po_id,
		}
	except HTTPException as exc:
		db.rollback()
		logger.warning("PO create failed with HTTP error: %s", getattr(exc, "detail", exc))
		raise
	except Exception as e:
		db.rollback()
		logger.exception("Unexpected error while creating PO")
		raise HTTPException(
			status_code=500,
			detail={
				"message": "Failed to create PO",
				"error": str(e),
			},
		)


@router.get("/get_po_by_id")
def get_po_by_id(
	request: Request,
	db: Session = Depends(get_tenant_db),
	token_data: dict = Depends(get_current_user_with_refresh),
):
	"""Return PO details by ID with all line items, additional charges, and GST."""
	try:
		q_po_id = request.query_params.get("po_id")
		q_co_id = request.query_params.get("co_id")
		
		if q_po_id is None:
			raise HTTPException(status_code=400, detail="po_id is required")
		if q_co_id is None:
			raise HTTPException(status_code=400, detail="co_id is required")
		
		try:
			po_id = int(q_po_id)
			co_id = int(q_co_id)
		except (TypeError, ValueError):
			raise HTTPException(status_code=400, detail="Invalid po_id or co_id")
		
		# Fetch header data
		header_query = get_po_by_id_query()
		header_params = {"po_id": po_id, "co_id": co_id}
		header_result = db.execute(header_query, header_params).fetchone()
		
		if not header_result:
			raise HTTPException(status_code=404, detail="PO not found or access denied")
		
		header = dict(header_result._mapping)
		
		# Fetch line items
		detail_query = get_po_dtl_by_id_query()
		detail_params = {"po_id": po_id}
		detail_results = db.execute(detail_query, detail_params).fetchall()
		details = [dict(r._mapping) for r in detail_results]
		
		# Fetch additional charges
		additional_query = get_po_additional_by_id_query()
		additional_results = db.execute(additional_query, detail_params).fetchall()
		additional_charges = [dict(r._mapping) for r in additional_results]
		
		# Fetch GST records
		gst_query = get_po_gst_by_id_query()
		gst_results = db.execute(gst_query, detail_params).fetchall()
		gst_records = [dict(r._mapping) for r in gst_results]
		
		# Create GST lookup maps
		gst_by_dtl_id = {g["po_dtl_id"]: g for g in gst_records if g["po_dtl_id"]}
		gst_by_additional_id = {g["po_additional_id"]: g for g in gst_records if g["po_additional_id"]}
		
		# Format dates
		po_date = header.get("po_date")
		if po_date and hasattr(po_date, "date"):
			po_date_str = po_date.date().isoformat()
		elif po_date and hasattr(po_date, "isoformat"):
			po_date_str = po_date.isoformat()
		elif po_date:
			po_date_str = str(po_date)
		else:
			po_date_str = ""
		
		updated_at = header.get("update_date_time")
		updated_at_str = None
		if updated_at:
			if hasattr(updated_at, "isoformat"):
				updated_at_str = updated_at.isoformat()
			else:
				updated_at_str = str(updated_at)
		
		# Format PO number using helper
		formatted_po_no = extract_formatted_po_no(header)
		
		# Get approval_level (only when status_id = 20)
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
		
		# Build response
		response = {
			"id": str(header.get("po_id", "")),
			"poNo": formatted_po_no,
			"poDate": po_date_str,
			"branch": str(header.get("branch_id", "")) if header.get("branch_id") else "",
				"branchName": header.get("branch_name") or "",
			"supplier": str(header.get("supplier_id", "")) if header.get("supplier_id") else "",
			"supplierBranch": str(header.get("supplier_branch_id", "")) if header.get("supplier_branch_id") else "",
			"supplierState": header.get("supplier_state_name") if header.get("supplier_state_name") else None,
			"billingAddress": str(header.get("billing_branch_id", "")) if header.get("billing_branch_id") else "",
			"billingState": header.get("billing_state_name") if header.get("billing_state_name") else None,
			"shippingAddress": str(header.get("shipping_branch_id", "")) if header.get("shipping_branch_id") else "",
			"shippingState": header.get("shipping_state_name") if header.get("shipping_state_name") else None,
			"project": str(header.get("project_id", "")) if header.get("project_id") else "",
			"expenseType": str(header.get("expense_type_id", "")) if header.get("expense_type_id") else "",
			"poType": header.get("po_type") or "",
			"creditTerm": header.get("credit_days"),
			"deliveryTimeline": header.get("expected_delivery_days"),
			"contactPerson": header.get("contact_person") or "",
			"contactNo": header.get("contact_no") or "",
			"footerNote": header.get("footer_notes") or "",
			"internalNote": header.get("remarks") or "",
			"termsConditions": header.get("terms_conditions") or "",
			"netAmount": float(header.get("net_amount") or 0),
			"totalAmount": float(header.get("total_amount") or 0),
			"advancePercentage": float(header.get("advance_value") or 0),
			"advanceAmount": float(header.get("advance_amount") or 0),
			"status": header.get("status_name") or "",
			"statusId": header.get("status_id"),
			"approvalLevel": approval_level,
			"updatedBy": str(header.get("updated_by", "")) if header.get("updated_by") else None,
			"updatedAt": updated_at_str,
			"lines": [],
			"additionalCharges": [],
		}
		
		# Add permissions if calculated
		if permissions is not None:
			response["permissions"] = permissions
		
		# Map line items
		for detail in details:
			gst = gst_by_dtl_id.get(detail.get("po_dtl_id"))
			
			# Extract indent_dtl_id for balance calculation
			indent_dtl_id_val = detail.get("indent_dtl_id")
			if indent_dtl_id_val:
				try:
					indent_dtl_id_int = int(indent_dtl_id_val)
				except (TypeError, ValueError):
					indent_dtl_id_int = None
			else:
				indent_dtl_id_int = None
			
			# Format indent_no
			raw_indent_no = detail.get("indent_no")
			formatted_indent_no = None
			if raw_indent_no is not None and raw_indent_no != 0:
				try:
					formatted_indent_no = format_indent_no(
						indent_no=int(raw_indent_no),
						co_prefix=detail.get("indent_co_prefix"),
						branch_prefix=detail.get("indent_branch_prefix"),
						indent_date=detail.get("indent_date"),
						document_type="INDENT",
					)
				except Exception:
					logger.exception("Error formatting indent number in PO detail")
					formatted_indent_no = str(raw_indent_no)

			line = {
				"id": str(detail.get("po_dtl_id", "")) if detail.get("po_dtl_id") else "",
				"indentNo": formatted_indent_no,
				"indentDtlId": str(indent_dtl_id_val) if indent_dtl_id_val else None,
				"department": str(detail.get("dept_id", "")) if detail.get("dept_id") else None,
				"itemGroup": str(detail.get("item_grp_id", "")) if detail.get("item_grp_id") else "",
				"item": str(detail.get("item_id", "")) if detail.get("item_id") else "",
				"itemCode": detail.get("full_item_code") or detail.get("item_code") or "",
				"hsnCode": detail.get("hsn_code") if detail.get("hsn_code") else "",
				"itemMake": str(detail.get("item_make_id", "")) if detail.get("item_make_id") else None,
				"quantity": float(detail.get("qty", 0)) if detail.get("qty") is not None else 0,
				"rate": float(detail.get("rate", 0)) if detail.get("rate") is not None else 0,
				"uom": str(detail.get("uom_id", "")) if detail.get("uom_id") else "",
				"discountMode": detail.get("discount_mode"),
				"discountValue": float(detail.get("discount_value", 0)) if detail.get("discount_value") is not None else 0,
				"discountAmount": float(detail.get("discount_amount", 0)) if detail.get("discount_amount") is not None else 0,
				"amount": float(detail.get("qty", 0) * detail.get("rate", 0) - detail.get("discount_amount", 0)) if detail.get("qty") and detail.get("rate") else 0,
				"remarks": detail.get("remarks") if detail.get("remarks") else None,
				"taxPercentage": None,  # Will be calculated from GST if available
			}
			
			# Fetch available indent balance if indent_dtl_id exists
			if indent_dtl_id_int:
				try:
					# Try to fetch from vw_proc_indent_outstanding_new first
					indent_balance_query = text("""
						SELECT indent_bal_qty FROM vw_proc_indent_outstanding_new 
						WHERE indent_dtl_id = :indent_dtl_id
					""")
					indent_balance_result = db.execute(
						indent_balance_query, 
						{"indent_dtl_id": indent_dtl_id_int}
					).fetchone()
					
					# If view doesn't exist or no result, calculate manually
					if not indent_balance_result:
						# Get total indent qty from proc_indent_dtl
						indent_dtl_query = text("""
							SELECT qty FROM proc_indent_dtl 
							WHERE indent_dtl_id = :indent_dtl_id
						""")
						indent_dtl_result = db.execute(
							indent_dtl_query,
							{"indent_dtl_id": indent_dtl_id_int}
						).fetchone()
						
						if indent_dtl_result:
							indent_total_qty = float(indent_dtl_result[0]) if indent_dtl_result[0] is not None else 0
							
							# Get sum of all PO quantities for this indent (excluding soft-deleted)
							po_qty_query = text("""
								SELECT COALESCE(SUM(ppd.qty), 0) FROM proc_po_dtl ppd
								WHERE ppd.indent_dtl_id = :indent_dtl_id 
									AND ppd.active = 1
							""")
							po_result = db.execute(
								po_qty_query,
								{"indent_dtl_id": indent_dtl_id_int}
							).fetchone()
							po_qty = float(po_result[0]) if po_result else 0
							
							# indent_bal_qty = total_indent_qty - po_qty
							indent_bal_qty = indent_total_qty - po_qty
							line["availableIndentQty"] = indent_bal_qty
					else:
						line["availableIndentQty"] = float(indent_balance_result[0]) if indent_balance_result[0] is not None else 0
						
				except Exception as e:
					# Log for debugging
					logger.exception(f"Error fetching indent balance for indent_dtl_id {indent_dtl_id_int}: {e}")
			
			if gst:
				line["taxPercentage"] = float(gst.get("tax_pct", 0)) if gst.get("tax_pct") else None
				line["igst"] = float(gst.get("i_tax_amount", 0)) if gst.get("i_tax_amount") else 0
				line["sgst"] = float(gst.get("s_tax_amount", 0)) if gst.get("s_tax_amount") else 0
				line["cgst"] = float(gst.get("c_tax_amount", 0)) if gst.get("c_tax_amount") else 0
				line["igstPercentage"] = float(gst.get("i_tax_percentage", 0)) if gst.get("i_tax_percentage") else 0
				line["cgstPercentage"] = float(gst.get("c_tax_percentage", 0)) if gst.get("c_tax_percentage") else 0
				line["sgstPercentage"] = float(gst.get("stax_percentage", 0)) / 2 if gst.get("stax_percentage") else 0
				line["taxAmount"] = float(gst.get("tax_amount", 0)) if gst.get("tax_amount") else 0
			response["lines"].append(line)

		# Map additional charges
		for addl in additional_charges:
			gst = gst_by_additional_id.get(addl.get("po_additional_id"))
			addl_line = {
				"id": str(addl.get("po_additional_id", "")) if addl.get("po_additional_id") else "",
				"additionalChargesId": str(addl.get("additional_charges_id", "")) if addl.get("additional_charges_id") else "",
				"additionalChargesName": addl.get("additional_charges_name") if addl.get("additional_charges_name") else "",
				"qty": int(addl.get("qty", 0)) if addl.get("qty") is not None else 0,
				"rate": float(addl.get("rate", 0)) if addl.get("rate") is not None else 0,
				"netAmount": float(addl.get("net_amount", 0)) if addl.get("net_amount") is not None else 0,
				"remarks": addl.get("remarks") if addl.get("remarks") else None,
			}
			if gst:
				addl_line["igst"] = float(gst.get("i_tax_amount", 0)) if gst.get("i_tax_amount") else 0
				addl_line["sgst"] = float(gst.get("s_tax_amount", 0)) if gst.get("s_tax_amount") else 0
				addl_line["cgst"] = float(gst.get("c_tax_amount", 0)) if gst.get("c_tax_amount") else 0
				addl_line["tax_pct"] = float(gst.get("tax_pct", 0)) if gst.get("tax_pct") else 0
				addl_line["tax_amount"] = float(gst.get("tax_amount", 0)) if gst.get("tax_amount") else 0
				addl_line["apply_tax"] = True
			response["additionalCharges"].append(addl_line)
		
		return response
	except HTTPException:
		raise
	except Exception as e:
		logger.exception("Error fetching PO by ID")
		raise HTTPException(status_code=500, detail=str(e))


@router.put("/update_po")
def update_po(
	payload: dict,
	db: Session = Depends(get_tenant_db),
	token_data: dict = Depends(get_current_user_with_refresh),
):
	"""Update a purchase order with line items, additional charges, and GST."""
	
	def to_int(value, field_name: str, required: bool = False) -> int | None:
		if value is None or value == "":
			if required:
				raise HTTPException(status_code=400, detail=f"{field_name} is required")
			return None
		try:
			return int(value)
		except (TypeError, ValueError):
			raise HTTPException(status_code=400, detail=f"Invalid {field_name}")

	def to_float(value, field_name: str, default: float = 0.0) -> float:
		if value is None or value == "":
			return default
		try:
			return float(value)
		except (TypeError, ValueError):
			return default

	try:
		po_id = to_int(payload.get("id"), "id", required=True)
		
		# Verify PO exists
		check_query = text("SELECT po_id, status_id FROM proc_po WHERE po_id = :po_id")
		check_result = db.execute(check_query, {"po_id": po_id}).fetchone()
		if not check_result:
			raise HTTPException(status_code=404, detail="PO not found")
		
		existing_status_id = check_result[1] if check_result[1] is not None else None
		
		# Header fields (same as create)
		branch_id = to_int(payload.get("branch"), "branch", required=True)
		supplier_id = to_int(payload.get("supplier"), "supplier", required=True)
		supplier_branch_id = to_int(payload.get("supplier_branch"), "supplier_branch", required=True)
		billing_branch_id = to_int(payload.get("billing_address"), "billing_address", required=True)
		shipping_branch_id = to_int(payload.get("shipping_address"), "shipping_address", required=True)
		project_id = to_int(payload.get("project"), "project")
		
		date_str = payload.get("date")
		if not date_str:
			raise HTTPException(status_code=400, detail="date is required")
		try:
			po_date = datetime.strptime(str(date_str), "%Y-%m-%d").date()
		except ValueError:
			raise HTTPException(status_code=400, detail="Invalid date format, expected YYYY-MM-DD")

		credit_days = to_int(payload.get("credit_term"), "credit_term")
		expected_delivery_days = to_int(payload.get("delivery_timeline"), "delivery_timeline", required=True)
		contact_person = payload.get("contact_person", "").strip() or None
		contact_no = payload.get("contact_no", "").strip() or None
		footer_notes = payload.get("footer_note", "").strip() or None
		remarks = payload.get("internal_note", "").strip() or None
		terms_conditions = payload.get("terms_conditions", "").strip() or None
		expense_type_id = to_int(payload.get("expense_type"), "expense_type")
		po_type = payload.get("po_type", "").strip() or None
		
		advance_value = to_float(payload.get("advance_percentage"), "advance_percentage")
		
		# Get supplier and shipping state IDs for GST calculation
		supplier_branch_query = text(
			"""
			SELECT pbm.state_id
			FROM party_branch_mst pbm
			WHERE pbm.party_mst_branch_id = :branch_id
			"""
		)
		supplier_result = db.execute(supplier_branch_query, {"branch_id": supplier_branch_id}).fetchone()
		supplier_state_id = supplier_result[0] if supplier_result else None
		
		shipping_branch_query = text("SELECT state_id FROM branch_mst WHERE branch_id = :branch_id")
		shipping_result = db.execute(shipping_branch_query, {"branch_id": shipping_branch_id}).fetchone()
		shipping_state_id = shipping_result[0] if shipping_result else None
		
		# Get co_config to check india_gst
		branch_query = text("SELECT co_id FROM branch_mst WHERE branch_id = :branch_id")
		branch_result = db.execute(branch_query, {"branch_id": branch_id}).fetchone()
		co_id = branch_result[0] if branch_result else None
		
		india_gst = False
		if co_id:
			co_config_query = get_co_config_by_id_query(co_id)
			co_config_result = db.execute(co_config_query, {"co_id": co_id}).fetchone()
			if co_config_result:
				co_config = dict(co_config_result._mapping)
				india_gst = bool(co_config.get("india_gst", False))
		
		# Line items
		raw_items = payload.get("items", [])
		if not isinstance(raw_items, list) or len(raw_items) == 0:
			raise HTTPException(status_code=400, detail="At least one item row is required")
		
		# Additional charges
		raw_additional = payload.get("additional_charges", [])
		
		updated_by = to_int(token_data.get("user_id"), "updated_by")
		updated_at = now_ist()

		# Calculate totals (same logic as create)
		net_amount = 0.0
		total_igst = 0.0
		total_sgst = 0.0
		total_cgst = 0.0

		# Process line items (same as create)
		normalized_items = []
		for idx, item in enumerate(raw_items, start=1):
			item_id = to_int(item.get("item"), f"items[{idx}].item", required=True)
			qty = to_float(item.get("quantity"), f"items[{idx}].quantity")
			if qty <= 0:
				raise HTTPException(status_code=400, detail=f"items[{idx}].quantity must be greater than zero")
			rate = to_float(item.get("rate"), f"items[{idx}].rate")
			uom_id = to_int(item.get("uom"), f"items[{idx}].uom", required=True)
			item_make_id = to_int(item.get("make"), f"items[{idx}].make")
			indent_dtl_id = to_int(item.get("indent_dtl_id"), f"items[{idx}].indent_dtl_id")
			po_dtl_id_raw = to_int(item.get("po_dtl_id"), f"items[{idx}].po_dtl_id")

			# Get tax percentage from item_mst
			item_query = text("SELECT tax_percentage, hsn_code FROM item_mst WHERE item_id = :item_id")
			item_result = db.execute(item_query, {"item_id": item_id}).fetchone()
			tax_percentage = 0.0
			hsn_code = None
			if item_result:
				tax_percentage = float(item_result[0] or 0.0)
				hsn_code = item_result[1]

			# Frontend may override tax % per line (incl. explicit 0); blank keeps item_mst default.
			# Server-side GST below is computed from this resolved value.
			tax_percentage = resolve_line_tax_percentage(item, tax_percentage)

			# Allow frontend to override hsn_code
			frontend_hsn = item.get("hsn_code")
			if frontend_hsn is not None and str(frontend_hsn).strip():
				hsn_code = str(frontend_hsn).strip()

			# Discount calculation
			discount_mode = to_int(item.get("discount_mode"), f"items[{idx}].discount_mode")
			discount_value = to_float(item.get("discount_value"), f"items[{idx}].discount_value")
			discount_amount = 0.0

			base_amount = qty * rate
			if discount_mode == 1:  # Percentage
				if discount_value > 100:
					raise HTTPException(status_code=400, detail=f"items[{idx}].discount_value cannot be greater than 100")
				discount_amount = (base_amount * discount_value) / 100.0
			elif discount_mode == 2:  # Amount
				if discount_value > base_amount:
					raise HTTPException(status_code=400, detail=f"items[{idx}].discount_amount cannot be greater than total amount")
				discount_amount = discount_value

			amount = base_amount - discount_amount
			net_amount += amount

			# Calculate GST if india_gst is enabled (server-side calculation)
			if india_gst and tax_percentage > 0 and supplier_state_id and shipping_state_id:
				line_amount = float(amount)
				gst_amounts = calculate_gst_amounts(
					line_amount, tax_percentage, supplier_state_id, shipping_state_id
				)
				total_igst += gst_amounts["i_tax_amount"]
				total_sgst += gst_amounts["s_tax_amount"]
				total_cgst += gst_amounts["c_tax_amount"]
			else:
				gst_amounts = None

			remarks_raw = item.get("remarks", "").strip() or None

			normalized_items.append({
				"po_dtl_id": po_dtl_id_raw,
				"item_id": item_id,
				"qty": qty,
				"rate": rate,
				"uom_id": uom_id,
				"item_make_id": item_make_id,
				"indent_dtl_id": indent_dtl_id,
				"hsn_code": hsn_code,
				"discount_mode": discount_mode,
				"discount_value": discount_value,
				"discount_amount": discount_amount,
				"amount": amount,
				"remarks": remarks_raw,
				"tax_percentage": tax_percentage,
				"gst_amounts": gst_amounts,
			})

		# Process additional charges (same as create)
		normalized_additional = []
		for idx, addl in enumerate(raw_additional, start=1):
			additional_charges_id = to_int(addl.get("additional_charges_id"), f"additional_charges[{idx}].additional_charges_id", required=True)
			qty = to_int(addl.get("qty"), f"additional_charges[{idx}].qty", required=True)
			rate = to_float(addl.get("rate"), f"additional_charges[{idx}].rate")
			net_amt = qty * rate
			net_amount += net_amt
			
			remarks_raw = addl.get("remarks", "").strip() or None
			
			# GST for additional charges (if applicable, respecting apply_tax flag)
			gst_amounts = None
			apply_tax = addl.get("apply_tax", True)  # default to True for backwards compat
			if india_gst and supplier_state_id and shipping_state_id and apply_tax:
				# Use frontend-sent tax_pct if provided, fallback to master default_value
				tax_pct = to_float(addl.get("tax_pct"), f"additional_charges[{idx}].tax_pct")
				if tax_pct <= 0:
					addl_query = text("SELECT default_value FROM additional_charges_mst WHERE additional_charges_id = :id")
					addl_result = db.execute(addl_query, {"id": additional_charges_id}).fetchone()
					tax_pct = float(addl_result[0] or 0.0) if addl_result else 0.0
				if tax_pct > 0:
					gst_amounts = calculate_gst_amounts(net_amt, tax_pct, supplier_state_id, shipping_state_id)
					total_igst += gst_amounts["i_tax_amount"]
					total_sgst += gst_amounts["s_tax_amount"]
					total_cgst += gst_amounts["c_tax_amount"]

			normalized_additional.append({
				"additional_charges_id": additional_charges_id,
				"qty": qty,
				"rate": rate,
				"net_amount": net_amt,
				"remarks": remarks_raw,
				"gst_amounts": gst_amounts,
			})

		total_amount = net_amount + total_igst + total_sgst + total_cgst
		advance_amount = (net_amount * advance_value) / 100.0 if advance_value > 0 else 0.0

		# Get existing po_no to preserve it
		existing_query = text("SELECT po_no FROM proc_po WHERE po_id = :po_id")
		existing_result = db.execute(existing_query, {"po_id": po_id}).fetchone()
		existing_po_no = existing_result[0] if existing_result and existing_result[0] else None
		
		# Update PO header
		update_header_query = update_proc_po()
		header_params = {
			"po_id": po_id,
			"credit_days": credit_days,
			"delivery_instructions": None,
			"expected_delivery_days": expected_delivery_days,
			"footer_notes": footer_notes,
			"po_date": po_date,
			"remarks": remarks,
			"delivery_mode": None,
			"terms_conditions": terms_conditions,
			"branch_id": branch_id,
			"project_id": project_id,
			"supplier_id": supplier_id,
			"supplier_branch_id": supplier_branch_id,
			"billing_branch_id": billing_branch_id,
			"shipping_branch_id": shipping_branch_id,
			"total_amount": total_amount,
			"net_amount": net_amount,
			"advance_type": 1 if advance_value > 0 else None,
			"advance_value": advance_value,
			"advance_amount": advance_amount,
			"contact_no": contact_no,
			"contact_person": contact_person,
			"updated_by": updated_by,
			"updated_date_time": updated_at,
			"po_no": existing_po_no,
			"status_id": None,
			"approval_level": None,
			"expense_type_id": expense_type_id,
			"po_type": po_type,
		}
		db.execute(update_header_query, header_params)

		# ── Update detail rows in place ──────────────────────────────────
		# Existing rows are updated (preserving po_dtl_id for inward/GST
		# traceability). New rows are inserted. Removed rows are soft-deleted.
		# Triggers handle audit logging for updates and deletions.

		# Get current active detail rows for this PO (including all fields)
		existing_dtl_rows = db.execute(
			text("""SELECT po_dtl_id, qty, indent_dtl_id FROM proc_po_dtl 
					 WHERE po_id = :po_id AND active = 1"""),
			{"po_id": po_id},
		).fetchall()
		existing_dtl_map = {row[0]: {"qty": row[1], "indent_dtl_id": row[2]} for row in existing_dtl_rows}
		existing_dtl_ids = set(existing_dtl_map.keys())

		incoming_dtl_ids = set()
		for item in normalized_items:
			po_dtl_id_val = item.get("po_dtl_id")

			if po_dtl_id_val and po_dtl_id_val in existing_dtl_ids:
				# ── Update existing row in-place ──
				incoming_dtl_ids.add(po_dtl_id_val)

				# Get original values for inventory tracking
				existing_data = existing_dtl_map[po_dtl_id_val]
				old_qty = existing_data["qty"]
				original_indent_dtl_id = existing_data["indent_dtl_id"]
				
				# Preserve indent_dtl_id if not provided in update
				update_indent_dtl_id = item["indent_dtl_id"] if item["indent_dtl_id"] else original_indent_dtl_id
				
				# ── Validate indent balance qty if indent_dtl_id exists ──
				if update_indent_dtl_id:
					# Get indent detail info
					indent_dtl_query = text("""
						SELECT qty FROM proc_indent_dtl WHERE indent_dtl_id = :indent_dtl_id
					""")
					indent_dtl_result = db.execute(indent_dtl_query, {"indent_dtl_id": update_indent_dtl_id}).fetchone()
					
					if indent_dtl_result:
						indent_total_qty = indent_dtl_result[0]
						
						# Get sum of all OTHER PO quantities for this indent (excluding current line)
						other_po_qty_query = text("""
							SELECT COALESCE(SUM(ppd.qty), 0) FROM proc_po_dtl ppd
							WHERE ppd.indent_dtl_id = :indent_dtl_id 
								AND ppd.po_dtl_id != :po_dtl_id
								AND ppd.active = 1
						""")
						other_po_result = db.execute(
							other_po_qty_query, 
							{"indent_dtl_id": update_indent_dtl_id, "po_dtl_id": po_dtl_id_val}
						).fetchone()
						other_po_qty = other_po_result[0] if other_po_result else 0
						
						# Check if new quantity + other POs exceeds indent qty
						available_for_this_line = indent_total_qty - other_po_qty
						if item["qty"] > available_for_this_line:
							raise HTTPException(
								status_code=400, 
								detail=f"items[...].quantity {item['qty']} exceeds indent balance {available_for_this_line} for indent_dtl_id {update_indent_dtl_id}"
							)
				
				# Delete old GST for this line
				db.execute(delete_po_gst_by_dtl_id(), {"po_dtl_id": po_dtl_id_val})

				# Update the detail row
				db.execute(update_proc_po_dtl(), {
					"po_dtl_id": po_dtl_id_val,
					"po_id": po_id,
					"item_id": item["item_id"],
					"hsn_code": item["hsn_code"],
					"item_make_id": item["item_make_id"],
					"qty": item["qty"],
					"rate": item["rate"],
					"uom_id": item["uom_id"],
					"remarks": item["remarks"],
					"discount_mode": item["discount_mode"],
					"discount_value": item["discount_value"],
					"discount_amount": item["discount_amount"],
					"indent_dtl_id": update_indent_dtl_id,
					"updated_by": updated_by,
					"updated_date_time": updated_at,
				})
				


				# Re-insert GST if applicable
				if india_gst and item["gst_amounts"]:
					gst_query = insert_po_gst()
					gst_params = {
						"po_dtl_id": po_dtl_id_val,
						"po_additional_id": None,
						"tax_pct": item["gst_amounts"]["tax_pct"],
						"stax_percentage": item["gst_amounts"]["stax_percentage"],
						"s_tax_amount": item["gst_amounts"]["s_tax_amount"],
						"i_tax_amount": item["gst_amounts"]["i_tax_amount"],
						"i_tax_percentage": item["gst_amounts"]["i_tax_percentage"],
						"c_tax_amount": item["gst_amounts"]["c_tax_amount"],
						"c_tax_percentage": item["gst_amounts"]["c_tax_percentage"],
						"tax_amount": item["gst_amounts"]["tax_amount"],
					}
					db.execute(gst_query, gst_params)
			else:
				# ── New row — insert ──
				# ── Validate indent balance qty if indent_dtl_id exists ──
				if item["indent_dtl_id"]:
					# Get indent detail info
					indent_dtl_query = text("""
						SELECT qty FROM proc_indent_dtl WHERE indent_dtl_id = :indent_dtl_id
					""")
					indent_dtl_result = db.execute(indent_dtl_query, {"indent_dtl_id": item["indent_dtl_id"]}).fetchone()
					
					if indent_dtl_result:
						indent_total_qty = indent_dtl_result[0]
						
						# Get sum of all PO quantities for this indent
						po_qty_query = text("""
							SELECT COALESCE(SUM(ppd.qty), 0) FROM proc_po_dtl ppd
							WHERE ppd.indent_dtl_id = :indent_dtl_id
								AND ppd.active = 1
						""")
						po_result = db.execute(po_qty_query, {"indent_dtl_id": item["indent_dtl_id"]}).fetchone()
						po_qty = po_result[0] if po_result else 0
						
						# Available for this new line = indent qty - existing POs
						available_for_new_line = indent_total_qty - po_qty
						if item["qty"] > available_for_new_line:
							raise HTTPException(
								status_code=400, 
								detail=f"items[...].quantity {item['qty']} exceeds indent balance {available_for_new_line} for indent_dtl_id {item['indent_dtl_id']}"
							)
				
				detail_query = insert_proc_po_dtl()
				detail_params = {
					"po_id": po_id,
					"item_id": item["item_id"],
					"hsn_code": item["hsn_code"],
					"item_make_id": item["item_make_id"],
					"qty": item["qty"],
					"rate": item["rate"],
					"uom_id": item["uom_id"],
					"remarks": item["remarks"],
					"discount_mode": item["discount_mode"],
					"discount_value": item["discount_value"],
					"discount_amount": item["discount_amount"],
					"active": 1,
					"indent_dtl_id": item["indent_dtl_id"],
					"updated_by": updated_by,
					"updated_date_time": updated_at,
					"state": 1,
				}
				result = db.execute(detail_query, detail_params)
				new_po_dtl_id = result.lastrowid

				# Insert GST if applicable
				if india_gst and item["gst_amounts"]:
					gst_query = insert_po_gst()
					gst_params = {
						"po_dtl_id": new_po_dtl_id,
						"po_additional_id": None,
						"tax_pct": item["gst_amounts"]["tax_pct"],
						"stax_percentage": item["gst_amounts"]["stax_percentage"],
						"s_tax_amount": item["gst_amounts"]["s_tax_amount"],
						"i_tax_amount": item["gst_amounts"]["i_tax_amount"],
						"i_tax_percentage": item["gst_amounts"]["i_tax_percentage"],
						"c_tax_amount": item["gst_amounts"]["c_tax_amount"],
						"c_tax_percentage": item["gst_amounts"]["c_tax_percentage"],
						"tax_amount": item["gst_amounts"]["tax_amount"],
					}
					db.execute(gst_query, gst_params)

		# Soft-delete rows that were removed by the user
		removed_dtl_ids = existing_dtl_ids - incoming_dtl_ids
		for dtl_id in removed_dtl_ids:
			# Get indent_dtl_id and qty before deleting
			removed_line = db.execute(
				text("SELECT indent_dtl_id, qty FROM proc_po_dtl WHERE po_dtl_id = :dtl_id"),
				{"dtl_id": dtl_id}
			).fetchone()
			
			# Delete GST for removed line
			db.execute(delete_po_gst_by_dtl_id(), {"po_dtl_id": dtl_id})
			
			# Soft-delete the detail row
			db.execute(
				text(
					"UPDATE proc_po_dtl SET active = 0, updated_by = :updated_by, "
					"updated_date_time = :updated_date_time WHERE po_dtl_id = :dtl_id"
				),
				{"dtl_id": dtl_id, "updated_by": updated_by, "updated_date_time": updated_at},
			)

		# Delete GST for existing additional charges before removing them
		db.execute(delete_po_gst_for_additional_charges(), {"po_id": po_id})

		# Delete existing additional charges
		delete_additional_query = delete_proc_po_additional()
		db.execute(delete_additional_query, {"po_id": po_id})

		# Insert new additional charges (same as create)
		additional_query = insert_proc_po_additional()
		for addl in normalized_additional:
			addl_params = {
				"po_id": po_id,
				"additional_charges_id": addl["additional_charges_id"],
				"qty": addl["qty"],
				"rate": addl["rate"],
				"net_amount": addl["net_amount"],
				"remarks": addl["remarks"],
			}
			result = db.execute(additional_query, addl_params)
			po_additional_id = result.lastrowid
			
			# Insert GST for additional charges if applicable
			if india_gst and addl["gst_amounts"]:
				gst_query = insert_po_gst()
				gst_params = {
					"po_dtl_id": None,
					"po_additional_id": po_additional_id,
					"tax_pct": addl["gst_amounts"]["tax_pct"],
					"stax_percentage": addl["gst_amounts"]["stax_percentage"],
					"s_tax_amount": addl["gst_amounts"]["s_tax_amount"],
					"i_tax_amount": addl["gst_amounts"]["i_tax_amount"],
					"i_tax_percentage": addl["gst_amounts"]["i_tax_percentage"],
					"c_tax_amount": addl["gst_amounts"]["c_tax_amount"],
					"c_tax_percentage": addl["gst_amounts"]["c_tax_percentage"],
					"tax_amount": addl["gst_amounts"]["tax_amount"],
				}
				db.execute(gst_query, gst_params)
		
		db.commit()
		return {
			"message": "PO updated successfully",
			"po_id": po_id,
		}
	except HTTPException as exc:
		db.rollback()
		logger.warning("PO update failed with HTTP error: %s", getattr(exc, "detail", exc))
		raise
	except Exception as e:
		db.rollback()
		logger.exception("Unexpected error while updating PO")
		raise HTTPException(
			status_code=500,
			detail=str(e),
		)


@router.post("/save_po")
def save_po(
	payload: dict,
	db: Session = Depends(get_tenant_db),
	token_data: dict = Depends(get_current_user_with_refresh),
):
	"""Create or update a PO from the new UI using a single endpoint."""
	try:
		if payload.get("id"):
			return update_po(payload, db=db, token_data=token_data)
		return create_po(payload, db=db, token_data=token_data)
	except HTTPException:
		raise
	except Exception as e:
		logger.exception("Error saving PO (create/update)")
		raise HTTPException(status_code=500, detail=str(e))


# ==================== APPROVAL API ENDPOINTS ====================

@router.post("/approve_po")
def approve_po(
	payload: dict,
	db: Session = Depends(get_tenant_db),
	token_data: dict = Depends(get_current_user_with_refresh),
):
	"""Approve a PO (with value check - PO has monetary amounts)."""
	try:
		po_id = payload.get("po_id")
		branch_id = payload.get("branch_id")
		menu_id = payload.get("menu_id")
		
		if not po_id:
			raise HTTPException(status_code=400, detail="po_id is required")
		if not branch_id:
			raise HTTPException(status_code=400, detail="branch_id is required")
		if not menu_id:
			raise HTTPException(status_code=400, detail="menu_id is required")
		
		try:
			po_id = int(po_id)
			branch_id = int(branch_id)
			menu_id = int(menu_id)
		except (TypeError, ValueError):
			raise HTTPException(status_code=400, detail="Invalid po_id, branch_id, or menu_id")
		
		user_id = int(token_data.get("user_id"))
		
		# Get PO amount
		po_query = get_po_with_approval_info()
		po_result = db.execute(po_query, {"po_id": po_id}).fetchone()
		if not po_result:
			raise HTTPException(status_code=404, detail="PO not found")
		
		po = dict(po_result._mapping)
		document_amount = float(po.get("total_amount", 0))

		# Guard: cannot approve an already-approved PO
		if po.get("status_id") == 3:
			raise HTTPException(status_code=400, detail="Purchase Order is already approved and cannot be approved again.")
		
		# Process approval with value checks
		result = process_approval(
			doc_id=po_id,
			user_id=user_id,
			menu_id=menu_id,
			db=db,
			get_doc_fn=get_po_with_approval_info,
			update_status_fn=update_po_status,
			id_param_name="po_id",
			doc_name="Purchase Order",
			document_amount=document_amount,
			extra_update_params={"po_no": None},
			get_consumed_amounts_fn=get_po_consumed_amounts,
		)
		
		return result
	except HTTPException:
		raise
	except Exception as e:
		logger.exception("Error approving PO")
		raise HTTPException(status_code=500, detail=str(e))


@router.post("/open_po")
def open_po(
	payload: dict,
	db: Session = Depends(get_tenant_db),
	token_data: dict = Depends(get_current_user_with_refresh),
):
	"""Open a PO (change status from 21 Drafted to 1 Open). Generates document number if not already generated."""
	try:
		po_id = payload.get("po_id")
		branch_id = payload.get("branch_id")
		menu_id = payload.get("menu_id")
		
		if not po_id:
			raise HTTPException(status_code=400, detail="po_id is required")
		if not branch_id:
			raise HTTPException(status_code=400, detail="branch_id is required")
		if not menu_id:
			raise HTTPException(status_code=400, detail="menu_id is required")
		
		try:
			po_id = int(po_id)
			branch_id = int(branch_id)
			menu_id = int(menu_id)
		except (TypeError, ValueError):
			raise HTTPException(status_code=400, detail="Invalid po_id, branch_id, or menu_id")
		
		user_id = int(token_data.get("user_id"))
		
		# Get PO details
		po_query = get_po_with_approval_info()
		po_result = db.execute(po_query, {"po_id": po_id}).fetchone()
		if not po_result:
			raise HTTPException(status_code=404, detail="PO not found")
		
		po = dict(po_result._mapping)
		current_status_id = po.get("status_id")
		current_po_no = po.get("po_no")
		po_date = po.get("po_date")
		
		# Verify current status is Drafted (21)
		if current_status_id != 21:
			raise HTTPException(
				status_code=400,
				detail=f"Cannot open PO with status_id {current_status_id}. Expected status 21 (Drafted)."
			)
		
		# Generate po_no if not already set
		new_po_no = None
		if not po_date:
			raise HTTPException(
				status_code=400,
				detail="PO date is required to generate PO number."
			)
		
		# Only generate if po_no is NULL or 0
		if current_po_no is None or current_po_no == 0:
			# Calculate financial year boundaries (same as indent)
			if hasattr(po_date, "year") and hasattr(po_date, "month"):
				year = po_date.year
				month = po_date.month
			elif hasattr(po_date, "date"):
				date_obj = po_date.date()
				year = date_obj.year
				month = date_obj.month
			else:
				try:
					if isinstance(po_date, str):
						date_obj = datetime.strptime(po_date, "%Y-%m-%d").date()
					else:
						date_obj = datetime.fromisoformat(str(po_date)).date()
					year = date_obj.year
					month = date_obj.month
				except Exception:
					raise HTTPException(
						status_code=400,
						detail=f"Invalid po_date format: {po_date}"
					)
			
			# Calculate financial year boundaries
			if month >= 4:
				fy_start_year = year
				fy_end_year = year + 1
			else:
				fy_start_year = year - 1
				fy_end_year = year
			
			fy_start_date = datetime(fy_start_year, 4, 1).date()
			fy_end_date = datetime(fy_end_year, 3, 31).date()
			
			# Get max po_no for this branch and financial year
			max_query = get_max_po_no_for_branch_fy()
			max_result = db.execute(
				max_query,
				{
					"branch_id": branch_id,
					"fy_start_date": fy_start_date,
					"fy_end_date": fy_end_date,
				}
			).fetchone()
			
			if max_result:
				max_po_no = dict(max_result._mapping).get("max_po_no") or 0
				new_po_no = max_po_no + 1
			else:
				new_po_no = 1
		
		# Update status to Open (1) and set po_no if generated
		updated_at = now_ist()
		update_query = update_po_status()
		update_params = {
			"po_id": po_id,
			"status_id": 1,  # Open
			"approval_level": None,  # Reset approval level
			"updated_by": user_id,
			"updated_date_time": updated_at,
			"po_no": new_po_no if new_po_no is not None else None,  # Pass None to keep existing, or new value
		}
		
		db.execute(update_query, update_params)
		db.commit()
		
		# Return the po_no that was set (either newly generated or existing)
		final_po_no = new_po_no if new_po_no is not None else current_po_no
		
		return {
			"status": "success",
			"new_status_id": 1,
			"message": "PO opened successfully.",
			"po_no": final_po_no,
		}
	except HTTPException:
		db.rollback()
		raise
	except Exception as e:
		db.rollback()
		logger.exception("Error opening PO")
		raise HTTPException(status_code=500, detail=str(e))


@router.post("/cancel_draft_po")
def cancel_draft_po(
	payload: dict,
	db: Session = Depends(get_tenant_db),
	token_data: dict = Depends(get_current_user_with_refresh),
):
	"""Cancel a draft PO (change status from 21 Drafted to 6 Cancelled)."""
	try:
		po_id = payload.get("po_id")
		branch_id = payload.get("branch_id")
		menu_id = payload.get("menu_id")
		
		if not po_id:
			raise HTTPException(status_code=400, detail="po_id is required")
		if not branch_id:
			raise HTTPException(status_code=400, detail="branch_id is required")
		if not menu_id:
			raise HTTPException(status_code=400, detail="menu_id is required")
		
		try:
			po_id = int(po_id)
			branch_id = int(branch_id)
			menu_id = int(menu_id)
		except (TypeError, ValueError):
			raise HTTPException(status_code=400, detail="Invalid po_id, branch_id, or menu_id")
		
		user_id = int(token_data.get("user_id"))
		
		# Get PO details
		po_query = get_po_with_approval_info()
		po_result = db.execute(po_query, {"po_id": po_id}).fetchone()
		if not po_result:
			raise HTTPException(status_code=404, detail="PO not found")
		
		po = dict(po_result._mapping)
		current_status_id = po.get("status_id")
		
		# Verify current status is Drafted (21)
		if current_status_id != 21:
			raise HTTPException(
				status_code=400,
				detail=f"Cannot cancel PO with status_id {current_status_id}. Expected status 21 (Drafted)."
			)
		
		# Update status to Cancelled (6)
		updated_at = now_ist()
		update_query = update_po_status()
		db.execute(
			update_query,
			{
				"po_id": po_id,
				"status_id": 6,  # Cancelled
				"approval_level": None,
				"updated_by": user_id,
				"updated_date_time": updated_at,
				"po_no": None,  # Don't update po_no
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
		logger.exception("Error cancelling draft PO")
		raise HTTPException(status_code=500, detail=str(e))


@router.post("/reopen_po")
def reopen_po(
	payload: dict,
	db: Session = Depends(get_tenant_db),
	token_data: dict = Depends(get_current_user_with_refresh),
):
	"""Reopen a PO (change status from 6 Cancelled or 4 Rejected back to 1 Open or 21 Drafted)."""
	try:
		po_id = payload.get("po_id")
		branch_id = payload.get("branch_id")
		menu_id = payload.get("menu_id")
		
		if not po_id:
			raise HTTPException(status_code=400, detail="po_id is required")
		if not branch_id:
			raise HTTPException(status_code=400, detail="branch_id is required")
		if not menu_id:
			raise HTTPException(status_code=400, detail="menu_id is required")
		
		try:
			po_id = int(po_id)
			branch_id = int(branch_id)
			menu_id = int(menu_id)
		except (TypeError, ValueError):
			raise HTTPException(status_code=400, detail="Invalid po_id, branch_id, or menu_id")
		
		user_id = int(token_data.get("user_id"))
		
		# Get PO details
		po_query = get_po_with_approval_info()
		po_result = db.execute(po_query, {"po_id": po_id}).fetchone()
		if not po_result:
			raise HTTPException(status_code=404, detail="PO not found")
		
		po = dict(po_result._mapping)
		current_status_id = po.get("status_id")
		
		# Determine target status based on current status
		if current_status_id == 6:  # Cancelled
			new_status_id = 21  # Back to Drafted
		elif current_status_id == 4:  # Rejected
			new_status_id = 1  # Back to Open
		else:
			raise HTTPException(
				status_code=400,
				detail=f"Cannot reopen PO with status_id {current_status_id}. Only Cancelled (6) or Rejected (4) can be reopened."
			)
		
		# Update status
		updated_at = now_ist()
		update_query = update_po_status()
		db.execute(
			update_query,
			{
				"po_id": po_id,
				"status_id": new_status_id,
				"approval_level": None,
				"updated_by": user_id,
				"updated_date_time": updated_at,
				"po_no": None,  # Don't update po_no
			}
		)
		db.commit()
		
		return {
			"status": "success",
			"new_status_id": new_status_id,
			"message": f"PO reopened successfully (status: {new_status_id}).",
		}
	except HTTPException:
		db.rollback()
		raise
	except Exception as e:
		db.rollback()
		logger.exception("Error reopening PO")
		raise HTTPException(status_code=500, detail=str(e))


@router.post("/send_po_for_approval")
def send_po_for_approval(
	payload: dict,
	db: Session = Depends(get_tenant_db),
	token_data: dict = Depends(get_current_user_with_refresh),
):
	"""Send PO for approval (change status from 1 Open to 20 Pending Approval, set approval_level to 1)."""
	try:
		po_id = payload.get("po_id")
		branch_id = payload.get("branch_id")
		menu_id = payload.get("menu_id")
		
		if not po_id:
			raise HTTPException(status_code=400, detail="po_id is required")
		if not branch_id:
			raise HTTPException(status_code=400, detail="branch_id is required")
		if not menu_id:
			raise HTTPException(status_code=400, detail="menu_id is required")
		
		try:
			po_id = int(po_id)
			branch_id = int(branch_id)
			menu_id = int(menu_id)
		except (TypeError, ValueError):
			raise HTTPException(status_code=400, detail="Invalid po_id, branch_id, or menu_id")
		
		user_id = int(token_data.get("user_id"))
		
		# Get PO details
		po_query = get_po_with_approval_info()
		po_result = db.execute(po_query, {"po_id": po_id}).fetchone()
		if not po_result:
			raise HTTPException(status_code=404, detail="PO not found")
		
		po = dict(po_result._mapping)
		current_status_id = po.get("status_id")
		
		# Verify current status is Open (1)
		if current_status_id != 1:
			raise HTTPException(
				status_code=400,
				detail=f"Cannot send for approval PO with status_id {current_status_id}. Expected status 1 (Open)."
			)
		
		# Update status to Pending Approval (20) with level 1
		updated_at = now_ist()
		update_query = update_po_status()
		db.execute(
			update_query,
			{
				"po_id": po_id,
				"status_id": 20,  # Pending Approval
				"approval_level": 1,  # Start at level 1
				"updated_by": user_id,
				"updated_date_time": updated_at,
				"po_no": None,  # Don't update po_no
			}
		)
		db.commit()
		
		return {
			"status": "success",
			"new_status_id": 20,
			"new_approval_level": 1,
			"message": "PO sent for approval successfully.",
		}
	except HTTPException:
		db.rollback()
		raise
	except Exception as e:
		db.rollback()
		logger.exception("Error sending PO for approval")
		raise HTTPException(status_code=500, detail=str(e))


@router.post("/reject_po")
def reject_po(
	payload: dict,
	db: Session = Depends(get_tenant_db),
	token_data: dict = Depends(get_current_user_with_refresh),
):
	"""Reject a PO (change status from 20 Pending Approval to 4 Rejected)."""
	try:
		po_id = payload.get("po_id")
		co_id = payload.get("co_id")
		reason = payload.get("reason", "")
		menu_id = payload.get("menu_id")

		if not po_id:
			raise HTTPException(status_code=400, detail="po_id is required")
		if not co_id:
			raise HTTPException(status_code=400, detail="co_id is required")

		try:
			po_id = int(po_id)
			co_id = int(co_id)
			if menu_id is not None:
				menu_id = int(menu_id)
		except (TypeError, ValueError):
			raise HTTPException(status_code=400, detail="Invalid po_id, co_id, or menu_id")

		user_id = int(token_data.get("user_id"))

		result = process_rejection(
			doc_id=po_id,
			user_id=user_id,
			menu_id=menu_id,
			db=db,
			get_doc_fn=get_po_with_approval_info,
			update_status_fn=update_po_status,
			id_param_name="po_id",
			doc_name="Purchase Order",
			reason=reason,
			extra_update_params={"po_no": None},
		)

		return result
	except HTTPException:
		raise
	except Exception as e:
		logger.exception("Error rejecting PO")
		raise HTTPException(status_code=500, detail=str(e))


@router.post("/clone_po")
def clone_po(
	payload: dict,
	db: Session = Depends(get_tenant_db),
	token_data: dict = Depends(get_current_user_with_refresh),
):
	"""Clone a PO (create a new PO with same details as the original)."""
	try:
		po_id = payload.get("po_id")
		branch_id = payload.get("branch_id")
		
		if not po_id:
			raise HTTPException(status_code=400, detail="po_id is required")
		if not branch_id:
			raise HTTPException(status_code=400, detail="branch_id is required")
		
		try:
			po_id = int(po_id)
			branch_id = int(branch_id)
		except (TypeError, ValueError):
			raise HTTPException(status_code=400, detail="Invalid po_id or branch_id")
		
		user_id = int(token_data.get("user_id"))
		
		# Get original PO header
		po_query = get_po_header_query()
		po_result = db.execute(po_query, {"po_id": po_id}).fetchone()
		if not po_result:
			raise HTTPException(status_code=404, detail="PO not found")
		
		original = dict(po_result._mapping)
		
		# Get original PO line items
		dtl_query = get_po_dtl_query()
		dtl_results = db.execute(dtl_query, {"po_id": po_id}).fetchall()
		
		# Create new PO header (as Draft, no PO number yet)
		created_at = now_ist()
		new_po_no = None  # Will be generated when opened/approved
		
		insert_header = insert_proc_po()
		header_params = {
			"credit_days": original.get("credit_days"),
			"delivery_instructions": original.get("delivery_instructions"),
			"expected_delivery_days": original.get("expected_delivery_days"),
			"footer_notes": original.get("footer_notes"),
			"po_date": now_ist().date(),  # Use current date
			"po_no": new_po_no,
			"remarks": original.get("remarks"),
			"delivery_mode": original.get("delivery_mode"),
			"terms_conditions": original.get("terms_conditions"),
			"branch_id": branch_id,
			"project_id": original.get("project_id"),
			"supplier_id": original.get("supplier_id"),
			"supplier_branch_id": original.get("supplier_branch_id"),
			"billing_branch_id": original.get("billing_branch_id"),
			"shipping_branch_id": original.get("shipping_branch_id"),
			"total_amount": original.get("total_amount") or 0,
			"net_amount": original.get("net_amount") or 0,
			"status_id": 21,  # Drafted
			"advance_type": original.get("advance_type"),
			"advance_value": original.get("advance_value") or 0,
			"advance_amount": original.get("advance_amount") or 0,
			"contact_no": original.get("contact_no"),
			"contact_person": original.get("contact_person"),
			"created_by": user_id,
			"created_date_time": created_at,
			"updated_by": user_id,
			"updated_date_time": created_at,
			"approval_level": None,
		}
		
		result = db.execute(insert_header, header_params)
		new_po_id = result.lastrowid
		
		# Clone line items (without indent reference since it's a new PO)
		detail_query = insert_proc_po_dtl()
		for dtl_row in dtl_results:
			dtl = dict(dtl_row._mapping)
			detail_params = {
				"po_id": new_po_id,
				"item_id": dtl.get("item_id"),
				"hsn_code": dtl.get("hsn_code"),
				"item_make_id": dtl.get("item_make_id"),
				"qty": dtl.get("qty"),
				"rate": dtl.get("rate"),
				"uom_id": dtl.get("uom_id"),
				"remarks": dtl.get("remarks"),
				"discount_mode": dtl.get("discount_mode"),
				"discount_value": dtl.get("discount_value"),
				"discount_amount": dtl.get("discount_amount"),
				"created_by": user_id,
				"created_date_time": created_at,
				"updated_by": user_id,
				"updated_date_time": created_at,
				"indent_dtl_id": None,  # Don't copy indent reference
				"i_tax_percentage": dtl.get("i_tax_percentage"),
				"s_tax_percentage": dtl.get("s_tax_percentage"),
				"c_tax_percentage": dtl.get("c_tax_percentage"),
				"tax_percentage": dtl.get("tax_percentage"),
				"tax_amount": dtl.get("tax_amount"),
			}
			db.execute(detail_query, detail_params)
		
		db.commit()
		
		return {
			"status": "success",
			"id": str(new_po_id),
			"message": "PO cloned successfully.",
		}
	except HTTPException:
		db.rollback()
		raise
	except Exception as e:
		db.rollback()
		logger.exception("Error cloning PO")
		raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# DOWNLOAD ENDPOINT
# =============================================================================

_PO_TABLE_COLUMNS = [
	("PO No", "po_no"),
	("Date", "po_date"),
	("Supplier", "supplier_name"),
	("PO Value", "po_value"),
	("Branch", "branch_name"),
	("Project", "project_name"),
	("Status", "status"),
]


@router.get("/download_po_table")
def download_po_table(
	request: Request,
	db: Session = Depends(get_tenant_db),
	token_data: dict = Depends(get_current_user_with_refresh),
	format: str | None = None,
	search: str | None = None,
	co_id: int | None = None,
):
	"""Download the PO table as xlsx or pdf.

	Mirrors the listing endpoint's filters (co_id, search) but is unpaginated
	(capped at 50000 rows).
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
			"limit": _PO_DOWNLOAD_MAX_ROWS,
			"offset": 0,
		}

		rows = db.execute(get_po_table_query(), params).fetchall()

		data = []
		for row in rows:
			mapped = dict(row._mapping)
			po_date_obj = mapped.get("po_date")
			po_date = po_date_obj.isoformat() if hasattr(po_date_obj, "isoformat") else po_date_obj

			po_value = mapped.get("po_value")
			if po_value is not None:
				try:
					po_value = float(po_value)
				except (TypeError, ValueError):
					po_value = None

			formatted_po_no = extract_formatted_po_no(mapped)

			data.append({
				"po_no": formatted_po_no,
				"po_date": po_date,
				"supplier_name": mapped.get("supp_name") or "",
				"po_value": po_value,
				"branch_name": mapped.get("branch_name") or "",
				"project_name": mapped.get("project_name") or "",
				"status": mapped.get("status_name") or "Pending",
			})

		today_str = date.today().isoformat()
		title = "Purchase Orders"
		if fmt == "xlsx":
			buf = build_xlsx(data, _PO_TABLE_COLUMNS, sheet_name=title[:31])
			media_type = _PO_XLSX_MEDIA_TYPE
			ext = "xlsx"
		else:
			buf = build_pdf(data, _PO_TABLE_COLUMNS, title=title)
			media_type = _PO_PDF_MEDIA_TYPE
			ext = "pdf"

		return StreamingResponse(
			buf,
			media_type=media_type,
			headers={
				"Content-Disposition": f'attachment; filename="po-table-{today_str}.{ext}"'
			},
		)

	except HTTPException:
		raise
	except Exception as e:
		logger.exception("Error downloading PO table")
		raise HTTPException(status_code=500, detail=f"Error downloading PO table: {str(e)}")

