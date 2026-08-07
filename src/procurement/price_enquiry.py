from fastapi import Depends, Request, HTTPException, APIRouter
import logging
from sqlalchemy.orm import Session
from sqlalchemy.sql import text
from sqlalchemy.exc import IntegrityError
from datetime import datetime, date
from src.common.utils import now_ist
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.procurement.price_enquiry_query import (
	get_enquiry_table_query,
	get_enquiry_table_count_query,
	get_indent_info_by_dtl_id,
	insert_proc_enquiry,
	insert_proc_enquiry_dtl,
	insert_proc_enquiry_supplier,
	upsert_proc_enquiry_supplier,
	update_proc_enquiry,
	delete_proc_enquiry_dtl,
	delete_proc_enquiry_supplier,
	get_enquiry_by_id_query,
	get_enquiry_dtl_by_id_query,
	get_enquiry_suppliers_query,
	insert_enquiry_response,
	insert_enquiry_response_dtl,
	update_enquiry_response,
	delete_enquiry_response_dtl,
	get_responses_for_comparison_query,
	get_approved_indent_items_for_enquiry,
	get_max_enquiry_no_for_branch_fy,
	update_enquiry_status,
	get_enquiry_with_approval_info,
	get_po_prefill_from_response,
	select_response_atomic,
	get_response_enquiry_status,
	get_enquiry_response_guards,
	get_response_detail_query,
	mark_enquiry_suppliers_sent,
)
from src.masters.query import get_branch_list
from src.procurement.query import (
	get_suppliers_with_party_type_1,
	get_expense_types,
	get_project,
)
from src.procurement.indent import (
	get_fy_boundaries,
	format_indent_no,
)
from src.common.approval_utils import (
	process_approval,
	process_rejection,
	calculate_approval_permissions,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# =============================================================================
# HELPERS
# =============================================================================

def _to_int(value, field_name: str, required: bool = False):
	if value is None or value == "":
		if required:
			raise HTTPException(status_code=400, detail=f"{field_name} is required")
		return None
	try:
		return int(value)
	except (TypeError, ValueError):
		raise HTTPException(status_code=400, detail=f"Invalid {field_name}")


def _to_float(value, field_name: str):
	if value is None or value == "":
		return None
	try:
		return float(value)
	except (TypeError, ValueError):
		raise HTTPException(status_code=400, detail=f"Invalid {field_name}")


def _resolve_co_id_from_branch(db: Session, branch_id: int):
	"""Resolve the owning company (co_id) from a branch. The stored co_id is
	derived from the branch rather than trusted from the client, so the
	enquiry header is always scoped to the correct tenant company."""
	row = db.execute(
		text("SELECT co_id FROM branch_mst WHERE branch_id = :branch_id"),
		{"branch_id": int(branch_id)},
	).fetchone()
	if not row:
		raise HTTPException(status_code=400, detail="Invalid branch_id")
	return row[0]


def _resolve_branch_scope(db: Session, branch_id: int):
	"""Resolve (co_id, co_prefix, branch_prefix) from a branch so document
	numbers carry the same company/branch prefixes as other transactions."""
	row = db.execute(
		text(
			"""SELECT bm.co_id, cm.co_prefix, bm.branch_prefix
			FROM branch_mst bm
			LEFT JOIN co_mst cm ON cm.co_id = bm.co_id
			WHERE bm.branch_id = :branch_id"""
		),
		{"branch_id": int(branch_id)},
	).fetchone()
	if not row:
		raise HTTPException(status_code=400, detail="Invalid branch_id")
	return row[0], row[1], row[2]


def _sanitize_response_terms(payload: dict):
	"""Clamp free-text terms fields to their column widths (String(255)) so
	oversize input fails softly instead of surfacing a DB error."""
	payment_terms = payload.get("payment_terms")
	if payment_terms:
		payment_terms = str(payment_terms).strip()[:255] or None
	terms_conditions = payload.get("terms_conditions")
	if terms_conditions:
		terms_conditions = str(terms_conditions).strip()[:255] or None
	return payment_terms, terms_conditions


def _validate_response_items(raw_items: list):
	"""Reject nonsensical quote lines: negative rate/qty/discount, or a
	discount larger than the line's gross amount."""
	for idx, item in enumerate(raw_items, start=1):
		rate = _to_float(item.get("rate"), f"items[{idx}].rate")
		qty = _to_float(item.get("qty"), f"items[{idx}].qty")
		discount_value = _to_float(item.get("discount_value"), f"items[{idx}].discount_value")
		discount_amount = _to_float(item.get("discount_amount"), f"items[{idx}].discount_amount")
		gross_amount = _to_float(item.get("gross_amount"), f"items[{idx}].gross_amount")
		if rate is not None and rate < 0:
			raise HTTPException(status_code=400, detail=f"items[{idx}]: rate cannot be negative")
		if qty is not None and qty < 0:
			raise HTTPException(status_code=400, detail=f"items[{idx}]: qty cannot be negative")
		if discount_value is not None and discount_value < 0:
			raise HTTPException(status_code=400, detail=f"items[{idx}]: discount_value cannot be negative")
		if (
			discount_amount is not None
			and gross_amount is not None
			and discount_amount > gross_amount
		):
			raise HTTPException(
				status_code=400,
				detail=f"items[{idx}]: discount_amount cannot exceed gross_amount",
			)


# =============================================================================
# SETUP
# =============================================================================

@router.get("/get_enquiry_setup")
def get_enquiry_setup(
	request: Request,
	db: Session = Depends(get_tenant_db),
	token_data: dict = Depends(get_current_user_with_refresh),
):
	"""Return branches, suppliers, expense types, projects for enquiry creation."""
	try:
		co_id = _to_int(request.query_params.get("co_id"), "co_id", required=True)
		branch_id = _to_int(request.query_params.get("branch_id"), "branch_id")

		branch_ids_list = [branch_id] if branch_id else None
		branch_query = get_branch_list(co_id=int(co_id), branch_ids=branch_ids_list)
		branch_params: dict = {"co_id": int(co_id)}
		if branch_ids_list:
			branch_params["branch_ids"] = branch_ids_list
		branch_result = db.execute(branch_query, branch_params).fetchall()
		branches = [dict(r._mapping) for r in branch_result]

		supp_query = get_suppliers_with_party_type_1()
		supp_result = db.execute(supp_query, {"co_id": int(co_id)}).fetchall()
		# Map aliased columns (supplier_name / supplier_code) back to the
		# supp_name / supp_code names the frontend consistently uses elsewhere.
		suppliers = []
		for row in supp_result:
			raw = dict(row._mapping)
			suppliers.append(
				{
					"party_id": raw.get("party_id"),
					"supp_name": raw.get("supplier_name"),
					"supp_code": raw.get("supplier_code"),
				}
			)

		exp_query = get_expense_types()
		exp_result = db.execute(exp_query).fetchall()
		expense_types = [dict(r._mapping) for r in exp_result]

		# Projects are branch-scoped; only query when a branch has been chosen.
		if branch_id:
			prj_query = get_project(branch_id=int(branch_id))
			prj_result = db.execute(prj_query, {"branch_id": int(branch_id)}).fetchall()
			projects = [dict(r._mapping) for r in prj_result]
		else:
			projects = []

		# Match the flat response shape used by procurement/indent so the
		# shared frontend `fetchWithCookie<T>` pattern reads fields directly.
		return {
			"branches": branches,
			"suppliers": suppliers,
			"expense_types": expense_types,
			"projects": projects,
		}
	except HTTPException:
		raise
	except Exception as e:
		logger.exception("Error fetching enquiry setup")
		raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# TABLE / LIST
# =============================================================================

@router.get("/get_enquiry_table")
def get_enquiry_table(
	request: Request,
	db: Session = Depends(get_tenant_db),
	token_data: dict = Depends(get_current_user_with_refresh),
):
	"""Get paginated list of price enquiries scoped to the selected branches."""
	try:
		branch_ids_raw = request.query_params.get("branch_ids")
		if not branch_ids_raw:
			raise HTTPException(status_code=400, detail="branch_ids is required")

		branch_ids: list[int] = []
		for token in branch_ids_raw.split(","):
			token = token.strip()
			if not token:
				continue
			try:
				branch_ids.append(int(token))
			except ValueError:
				raise HTTPException(status_code=400, detail="Invalid branch_ids")
		if not branch_ids:
			raise HTTPException(status_code=400, detail="branch_ids is required")

		status_filter = _to_int(request.query_params.get("status"), "status")
		search = request.query_params.get("search")
		page = _to_int(request.query_params.get("page"), "page") or 1
		page_size = _to_int(request.query_params.get("page_size"), "page_size") or 10
		page = max(page, 1)
		page_size = min(max(page_size, 1), 200)
		offset = (page - 1) * page_size

		params = {"branch_ids": branch_ids, "limit": page_size, "offset": offset}
		if status_filter:
			params["status_filter"] = int(status_filter)
		if search:
			params["search_like"] = f"%{search}%"

		query = get_enquiry_table_query(branch_ids, status_filter, search, page, page_size)
		result = db.execute(query, params).fetchall()
		rows = [dict(r._mapping) for r in result]

		count_query = get_enquiry_table_count_query(branch_ids, status_filter, search)
		count_params = {k: v for k, v in params.items() if k not in ("limit", "offset")}
		count_result = db.execute(count_query, count_params).fetchone()
		total = count_result[0] if count_result else 0

		return {"data": rows, "totalCount": total}
	except HTTPException:
		raise
	except Exception as e:
		logger.exception("Error fetching enquiry table")
		raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# GET BY ID
# =============================================================================

@router.get("/get_enquiry_by_id")
def get_enquiry_by_id(
	request: Request,
	db: Session = Depends(get_tenant_db),
	token_data: dict = Depends(get_current_user_with_refresh),
):
	"""Get single enquiry with details, suppliers, and response summaries."""
	try:
		enquiry_id = _to_int(request.query_params.get("enquiry_id"), "enquiry_id", required=True)
		co_id = _to_int(request.query_params.get("co_id"), "co_id")
		menu_id = _to_int(request.query_params.get("menu_id"), "menu_id")
		user_id = _to_int(token_data.get("user_id"), "user_id")

		header_query = get_enquiry_by_id_query()
		header_result = db.execute(header_query, {"enquiry_id": int(enquiry_id), "co_id": co_id}).fetchone()
		if not header_result:
			raise HTTPException(status_code=404, detail="Enquiry not found")
		header = dict(header_result._mapping)

		dtl_query = get_enquiry_dtl_by_id_query()
		dtl_result = db.execute(dtl_query, {"enquiry_id": int(enquiry_id)}).fetchall()
		items = [dict(r._mapping) for r in dtl_result]

		supp_query = get_enquiry_suppliers_query()
		supp_result = db.execute(supp_query, {"enquiry_id": int(enquiry_id)}).fetchall()
		suppliers = [dict(r._mapping) for r in supp_result]

		resp_query = get_responses_for_comparison_query()
		resp_result = db.execute(resp_query, {"enquiry_id": int(enquiry_id)}).fetchall()
		resp_rows = [dict(r._mapping) for r in resp_result]
		responses_map = {}
		for row in resp_rows:
			rid = row.get("proc_price_enquiry_response_id")
			if rid not in responses_map:
				responses_map[rid] = {
					"proc_price_enquiry_response_id": rid,
					"supplier_id": row.get("supplier_id"),
					"supp_name": row.get("supp_name"),
					"response_date": str(row.get("date", "")) if row.get("date") else None,
					"credit_days": row.get("credit_days"),
					"delivery_days": row.get("delivery_days"),
					"gross_amount": row.get("resp_gross_amount"),
					"net_amount": row.get("resp_net_amount"),
					"is_selected": row.get("is_selected", 0),
				}
		responses = list(responses_map.values())

		approval_permissions = {}
		if menu_id and user_id and header.get("branch_id"):
			approval_permissions = calculate_approval_permissions(
				user_id=int(user_id),
				menu_id=int(menu_id),
				branch_id=int(header["branch_id"]),
				status_id=header.get("status_id"),
				current_approval_level=header.get("approval_level"),
				db=db,
			)

		return {
			"data": {
				**header,
				"items": items,
				"suppliers": suppliers,
				"responses": responses,
				"approval_permissions": approval_permissions,
			}
		}
	except HTTPException:
		raise
	except Exception as e:
		logger.exception("Error fetching enquiry by id")
		raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# APPROVED INDENT ITEMS
# =============================================================================

@router.get("/get_approved_indent_items")
def get_approved_indent_items(
	request: Request,
	db: Session = Depends(get_tenant_db),
	token_data: dict = Depends(get_current_user_with_refresh),
):
	"""Get approved indent items available for enquiry."""
	try:
		branch_id = _to_int(request.query_params.get("branch_id"), "branch_id", required=True)

		query = get_approved_indent_items_for_enquiry()
		result = db.execute(query, {"branch_id": int(branch_id)}).fetchall()
		items = [dict(r._mapping) for r in result]
		logger.info(
			"get_approved_indent_items: branch_id=%s -> %s approved indent line(s)",
			branch_id,
			len(items),
		)

		return {"data": items}
	except HTTPException:
		raise
	except Exception as e:
		logger.exception("Error fetching approved indent items")
		raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# CREATE ENQUIRY
# =============================================================================

@router.post("/create_enquiry")
def create_enquiry(
	payload: dict,
	db: Session = Depends(get_tenant_db),
	token_data: dict = Depends(get_current_user_with_refresh),
):
	"""Create a new price enquiry with items and suppliers."""
	try:
		branch_id = _to_int(payload.get("branch_id"), "branch_id", required=True)
		expense_type_id = _to_int(payload.get("expense_type_id"), "expense_type_id")
		project_id = _to_int(payload.get("project_id"), "project_id")
		enquiry_type = payload.get("enquiry_type") or "Regular"
		remarks = payload.get("remarks")
		if remarks:
			remarks = str(remarks).strip()[:255]

		date_str = payload.get("date")
		if not date_str:
			raise HTTPException(status_code=400, detail="date is required")
		try:
			enquiry_date = datetime.strptime(str(date_str), "%Y-%m-%d").date()
		except ValueError:
			raise HTTPException(status_code=400, detail="Invalid date format, expected YYYY-MM-DD")

		raw_items = payload.get("items")
		if not isinstance(raw_items, list) or len(raw_items) == 0:
			raise HTTPException(status_code=400, detail="At least one item is required")

		raw_suppliers = payload.get("suppliers")
		if not isinstance(raw_suppliers, list) or len(raw_suppliers) == 0:
			raise HTTPException(status_code=400, detail="At least one supplier is required")

		updated_by = _to_int(token_data.get("user_id"), "updated_by")
		created_at = now_ist()

		# Derive co_id (and doc-number prefixes) from the branch so the header
		# is tenant-scoped and numbered like other transactions.
		co_id, co_prefix, branch_prefix = _resolve_branch_scope(db, int(branch_id))

		fy_start, fy_end = get_fy_boundaries(enquiry_date)
		max_no_query = get_max_enquiry_no_for_branch_fy()
		header_query = insert_proc_enquiry()

		# uk_enq_branch_fy makes concurrent creates race on the same number;
		# retry with a freshly read max instead of surfacing a duplicate-key 500.
		enquiry_id = None
		enquiry_no = 1
		sequence_no = ""
		for attempt in range(3):
			max_no_result = db.execute(max_no_query, {
				"branch_id": int(branch_id),
				"fy_start_date": fy_start,
				"fy_end_date": fy_end,
			}).fetchone()
			enquiry_no = 1
			if max_no_result and max_no_result[0]:
				enquiry_no = int(max_no_result[0]) + 1

			sequence_no = format_indent_no(enquiry_no, co_prefix, branch_prefix, enquiry_date, document_type="PE")

			try:
				result = db.execute(header_query, {
					"co_id": co_id,
					"price_enquiry_date": enquiry_date,
					"price_enquiry_squence_no": sequence_no,
					"enquiry_no": enquiry_no,
					"enquiry_type": enquiry_type,
					"remarks": remarks,
					"branch_id": int(branch_id),
					"expense_type_id": expense_type_id,
					"project_id": project_id,
					"status_id": 21,
					"approval_level": None,
					"active": 1,
					"updated_by": updated_by,
					"updated_date_time": created_at,
				})
				db.flush()
				enquiry_id = result.lastrowid
				break
			except IntegrityError:
				db.rollback()
				if attempt == 2:
					raise HTTPException(
						status_code=409,
						detail="Could not allocate a unique enquiry number, please retry",
					)
		if not enquiry_id:
			raise HTTPException(status_code=500, detail="Failed to create enquiry header")

		dtl_query = insert_proc_enquiry_dtl()
		indent_info_query = get_indent_info_by_dtl_id()
		for idx, item in enumerate(raw_items, start=1):
			item_id = _to_int(item.get("item_id"), f"items[{idx}].item_id", required=True)
			qty = _to_float(item.get("qty"), f"items[{idx}].qty")
			uom_id = _to_int(item.get("uom_id"), f"items[{idx}].uom_id")
			item_make_id = _to_int(item.get("item_make_id"), f"items[{idx}].item_make_id")
			indent_dtl_id = _to_int(item.get("indent_dtl_id"), f"items[{idx}].indent_dtl_id")
			item_remarks = item.get("remarks")
			if item_remarks:
				item_remarks = str(item_remarks).strip()[:255]

			indent_id = None
			dept_id = None
			if indent_dtl_id is not None:
				info = db.execute(indent_info_query, {"indent_dtl_id": indent_dtl_id}).fetchone()
				if info:
					indent_id = info[0]
					dept_id = info[1]

			db.execute(dtl_query, {
				"enquiry_id": enquiry_id,
				"indent_dtl_id": indent_dtl_id,
				"indent_id": indent_id,
				"dept_id": dept_id,
				"item_id": item_id,
				"item_make_id": item_make_id,
				"uom_id": uom_id,
				"qty": qty,
				"remarks": item_remarks,
				"active": 1,
				"updated_by": updated_by,
				"updated_date_time": created_at,
			})

		supp_query = insert_proc_enquiry_supplier()
		# Dedupe by supplier_id: a duplicate in one payload would violate
		# uk_enquiry_supplier and surface as a 500 instead of a clean save.
		seen_supplier_ids: set[int] = set()
		for supplier in raw_suppliers:
			supplier_id = _to_int(supplier.get("supplier_id"), "supplier_id", required=True)
			if supplier_id in seen_supplier_ids:
				continue
			seen_supplier_ids.add(supplier_id)
			supplier_branch_id = _to_int(supplier.get("supplier_branch_id"), "supplier_branch_id")
			db.execute(supp_query, {
				"enquiry_id": enquiry_id,
				"supplier_id": supplier_id,
				"supplier_branch_id": supplier_branch_id,
				"active": 1,
				"updated_by": updated_by,
				"updated_date_time": created_at,
			})

		db.commit()
		return {
			"message": "Price enquiry created successfully",
			"enquiry_id": enquiry_id,
			"enquiry_no": enquiry_no,
			"sequence_no": sequence_no,
		}
	except HTTPException as exc:
		db.rollback()
		raise
	except Exception as e:
		db.rollback()
		logger.exception("Error creating enquiry")
		raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# UPDATE ENQUIRY
# =============================================================================

@router.put("/update_enquiry")
def update_enquiry_endpoint(
	payload: dict,
	db: Session = Depends(get_tenant_db),
	token_data: dict = Depends(get_current_user_with_refresh),
):
	"""Update a draft price enquiry."""
	try:
		enquiry_id = _to_int(payload.get("enquiry_id"), "enquiry_id", required=True)
		branch_id = _to_int(payload.get("branch_id"), "branch_id", required=True)
		expense_type_id = _to_int(payload.get("expense_type_id"), "expense_type_id")
		project_id = _to_int(payload.get("project_id"), "project_id")
		enquiry_type = payload.get("enquiry_type") or "Regular"
		remarks = payload.get("remarks")
		if remarks:
			remarks = str(remarks).strip()[:255]

		date_str = payload.get("date")
		if not date_str:
			raise HTTPException(status_code=400, detail="date is required")
		try:
			enquiry_date = datetime.strptime(str(date_str), "%Y-%m-%d").date()
		except ValueError:
			raise HTTPException(status_code=400, detail="Invalid date format")

		updated_by = _to_int(token_data.get("user_id"), "updated_by")
		created_at = now_ist()

		# Only Draft enquiries may be rewritten; anything later in the workflow
		# (sent for approval, approved, awarded, ...) must stay immutable so
		# supplier responses keep referencing the same lines.
		status_row = db.execute(
			get_enquiry_with_approval_info(), {"enquiry_id": int(enquiry_id)}
		).fetchone()
		if not status_row:
			raise HTTPException(status_code=404, detail="Enquiry not found")
		if dict(status_row._mapping).get("status_id") != 21:
			raise HTTPException(
				status_code=400,
				detail="Only Draft enquiries can be updated",
			)

		# Re-derive co_id from the branch so the header stays tenant-scoped.
		co_id = _resolve_co_id_from_branch(db, int(branch_id))

		header_query = update_proc_enquiry()
		db.execute(header_query, {
			"enquiry_id": int(enquiry_id),
			"price_enquiry_date": enquiry_date,
			"enquiry_type": enquiry_type,
			"remarks": remarks,
			"branch_id": branch_id,
			"co_id": co_id,
			"expense_type_id": expense_type_id,
			"project_id": project_id,
			"updated_by": updated_by,
			"updated_date_time": created_at,
			"enquiry_no": None,
			"active": None,
			"status_id": None,
		})

		raw_items = payload.get("items")
		if isinstance(raw_items, list):
			del_dtl_query = delete_proc_enquiry_dtl(enquiry_id)
			db.execute(del_dtl_query, {"enquiry_id": int(enquiry_id), "updated_by": updated_by, "updated_date_time": created_at})

			dtl_query = insert_proc_enquiry_dtl()
			indent_info_query = get_indent_info_by_dtl_id()
			for item in raw_items:
				item_id = _to_int(item.get("item_id"), "item_id")
				qty = _to_float(item.get("qty"), "qty")
				uom_id = _to_int(item.get("uom_id"), "uom_id")
				item_make_id = _to_int(item.get("item_make_id"), "item_make_id")
				indent_dtl_id = _to_int(item.get("indent_dtl_id"), "indent_dtl_id")
				item_remarks = item.get("remarks")
				if item_remarks:
					item_remarks = str(item_remarks).strip()[:255]

				indent_id = None
				dept_id = None
				if indent_dtl_id is not None:
					info = db.execute(indent_info_query, {"indent_dtl_id": indent_dtl_id}).fetchone()
					if info:
						indent_id = info[0]
						dept_id = info[1]

				db.execute(dtl_query, {
					"enquiry_id": int(enquiry_id),
					"indent_dtl_id": indent_dtl_id,
					"indent_id": indent_id,
					"dept_id": dept_id,
					"item_id": item_id,
					"item_make_id": item_make_id,
					"uom_id": uom_id,
					"qty": qty,
					"remarks": item_remarks,
					"active": 1,
					"updated_by": updated_by,
					"updated_date_time": created_at,
				})

		raw_suppliers = payload.get("suppliers")
		if isinstance(raw_suppliers, list):
			del_supp_query = delete_proc_enquiry_supplier(enquiry_id)
			db.execute(del_supp_query, {"enquiry_id": int(enquiry_id), "updated_by": updated_by, "updated_date_time": created_at})

			# Upsert instead of plain insert: soft-deleted rows still occupy
			# uk_enquiry_supplier, so re-adding a kept supplier must reactivate
			# the existing row rather than insert a duplicate.
			supp_query = upsert_proc_enquiry_supplier()
			for supplier in raw_suppliers:
				supplier_id = _to_int(supplier.get("supplier_id"), "supplier_id")
				supplier_branch_id = _to_int(supplier.get("supplier_branch_id"), "supplier_branch_id")
				db.execute(supp_query, {
					"enquiry_id": int(enquiry_id),
					"supplier_id": supplier_id,
					"supplier_branch_id": supplier_branch_id,
					"active": 1,
					"updated_by": updated_by,
					"updated_date_time": created_at,
				})

		db.commit()
		return {"message": "Price enquiry updated successfully", "enquiry_id": enquiry_id}
	except HTTPException as exc:
		db.rollback()
		raise
	except Exception as e:
		db.rollback()
		logger.exception("Error updating enquiry")
		raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# MARK RFQ SENT
# =============================================================================

@router.post("/mark_rfq_sent")
def mark_rfq_sent(
	payload: dict,
	db: Session = Depends(get_tenant_db),
	token_data: dict = Depends(get_current_user_with_refresh),
):
	"""Record that the RFQ document was issued to suppliers (all invited
	suppliers, or the subset in `supplier_ids`). Only Approved enquiries can
	be sent out."""
	try:
		enquiry_id = _to_int(payload.get("enquiry_id"), "enquiry_id", required=True)
		user_id = _to_int(token_data.get("user_id"), "user_id")

		raw_supplier_ids = payload.get("supplier_ids")
		supplier_ids = None
		if isinstance(raw_supplier_ids, list) and raw_supplier_ids:
			supplier_ids = [
				_to_int(sid, "supplier_ids", required=True) for sid in raw_supplier_ids
			]

		info_result = db.execute(
			get_enquiry_with_approval_info(), {"enquiry_id": int(enquiry_id)}
		).fetchone()
		if not info_result:
			raise HTTPException(status_code=404, detail="Enquiry not found")
		if dict(info_result._mapping).get("status_id") != 3:
			raise HTTPException(
				status_code=400,
				detail="RFQ can only be sent for Approved enquiries",
			)

		params = {
			"enquiry_id": int(enquiry_id),
			"sent_date": date.today(),
			"updated_by": user_id,
			"updated_date_time": now_ist(),
		}
		if supplier_ids:
			params["supplier_ids"] = supplier_ids
		result = db.execute(mark_enquiry_suppliers_sent(supplier_ids), params)
		db.commit()
		return {"data": {"status": "success", "updated": result.rowcount}}
	except HTTPException:
		db.rollback()
		raise
	except Exception as e:
		db.rollback()
		logger.exception("Error marking RFQ sent")
		raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# ADD RESPONSE (SUPPLIER QUOTE)
# =============================================================================

@router.post("/add_response")
def add_response(
	payload: dict,
	db: Session = Depends(get_tenant_db),
	token_data: dict = Depends(get_current_user_with_refresh),
):
	"""Record a supplier's quote/response for an enquiry."""
	try:
		enquiry_id = _to_int(payload.get("enquiry_id"), "enquiry_id", required=True)
		supplier_id = _to_int(payload.get("supplier_id"), "supplier_id", required=True)
		supplier_branch_id = _to_int(payload.get("supplier_branch_id"), "supplier_branch_id")
		delivery_days = _to_int(payload.get("delivery_days"), "delivery_days")
		credit_days = _to_int(payload.get("credit_days"), "credit_days")
		payment_terms, terms_conditions = _sanitize_response_terms(payload)
		remarks = payload.get("remarks")
		if remarks:
			remarks = str(remarks).strip()[:255]
		updated_by = _to_int(token_data.get("user_id"), "updated_by")
		created_at = now_ist()

		date_str = payload.get("response_date")
		if date_str:
			try:
				response_date = datetime.strptime(str(date_str), "%Y-%m-%d").date()
			except ValueError:
				raise HTTPException(status_code=400, detail="Invalid response_date format, expected YYYY-MM-DD")
		else:
			response_date = date.today()

		raw_items = payload.get("items")
		if not isinstance(raw_items, list) or len(raw_items) == 0:
			raise HTTPException(status_code=400, detail="At least one item is required")
		_validate_response_items(raw_items)

		# Quotes may only be recorded against an Approved enquiry, from a
		# supplier that was actually invited, and at most once per supplier
		# (revisions go through update_response).
		guard_row = db.execute(
			get_enquiry_response_guards(),
			{"enquiry_id": int(enquiry_id), "supplier_id": int(supplier_id)},
		).fetchone()
		if not guard_row:
			raise HTTPException(status_code=404, detail="Enquiry not found")
		guards = dict(guard_row._mapping)
		if guards.get("status_id") != 3:
			raise HTTPException(
				status_code=400,
				detail="Responses can only be recorded for Approved enquiries",
			)
		if not guards.get("invited"):
			raise HTTPException(
				status_code=400,
				detail="Supplier is not part of this enquiry",
			)
		if guards.get("existing_responses"):
			raise HTTPException(
				status_code=409,
				detail="A response already exists for this supplier â€” edit it instead",
			)

		gross_total = 0.0
		net_total = 0.0
		for item in raw_items:
			g = _to_float(item.get("gross_amount"), "gross_amount") or 0
			n = _to_float(item.get("net_amount"), "net_amount") or 0
			gross_total += g
			net_total += n

		header_query = insert_enquiry_response()
		result = db.execute(header_query, {
			"enquiry_id": int(enquiry_id),
			"response_date": response_date,
			"supplier_id": int(supplier_id),
			"supplier_branch_id": supplier_branch_id,
			"credit_days": credit_days,
			"delivery_days": delivery_days,
			"payment_terms": payment_terms,
			"terms_conditions": terms_conditions,
			"remarks": remarks,
			"gross_amount": gross_total,
			"net_amount": net_total,
			"is_selected": 0,
			"active": 1,
			"updated_by": updated_by,
			"updated_date_time": created_at,
		})
		response_id = result.lastrowid
		if not response_id:
			raise HTTPException(status_code=500, detail="Failed to create response header")

		dtl_query = insert_enquiry_response_dtl()
		for item in raw_items:
			item_remarks = item.get("remarks")
			if item_remarks:
				item_remarks = str(item_remarks).strip()[:255]
			db.execute(dtl_query, {
				"proc_price_enquiry_response_id": response_id,
				"enquiry_dtl_id": _to_int(item.get("enquiry_dtl_id"), "enquiry_dtl_id"),
				"item_id": _to_int(item.get("item_id"), "item_id"),
				"item_make_id": _to_int(item.get("item_make_id"), "item_make_id"),
				"uom_id": _to_int(item.get("uom_id"), "uom_id"),
				"qty": _to_float(item.get("qty"), "qty"),
				"rate": _to_float(item.get("rate"), "rate"),
				"discount_mode": _to_int(item.get("discount_mode"), "discount_mode"),
				"discount_value": _to_float(item.get("discount_value"), "discount_value"),
				"discount_amount": _to_float(item.get("discount_amount"), "discount_amount"),
				"gross_amount": _to_float(item.get("gross_amount"), "gross_amount"),
				"net_amount": _to_float(item.get("net_amount"), "net_amount"),
				"remarks": item_remarks,
				"active": 1,
				"updated_by": updated_by,
				"updated_date_time": created_at,
			})

		db.commit()
		return {"message": "Response recorded successfully", "response_id": response_id}
	except HTTPException as exc:
		db.rollback()
		raise
	except Exception as e:
		db.rollback()
		logger.exception("Error adding response")
		raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# UPDATE RESPONSE
# =============================================================================

@router.put("/update_response")
def update_response_endpoint(
	payload: dict,
	db: Session = Depends(get_tenant_db),
	token_data: dict = Depends(get_current_user_with_refresh),
):
	"""Update an existing supplier response."""
	try:
		response_id = _to_int(payload.get("response_id"), "response_id", required=True)
		supplier_id = _to_int(payload.get("supplier_id"), "supplier_id", required=True)
		supplier_branch_id = _to_int(payload.get("supplier_branch_id"), "supplier_branch_id")
		delivery_days = _to_int(payload.get("delivery_days"), "delivery_days")
		credit_days = _to_int(payload.get("credit_days"), "credit_days")
		payment_terms, terms_conditions = _sanitize_response_terms(payload)
		remarks = payload.get("remarks")
		if remarks:
			remarks = str(remarks).strip()[:255]
		updated_by = _to_int(token_data.get("user_id"), "updated_by")
		created_at = now_ist()

		date_str = payload.get("response_date")
		if not date_str:
			raise HTTPException(status_code=400, detail="response_date is required")
		try:
			response_date = datetime.strptime(str(date_str), "%Y-%m-%d").date()
		except ValueError:
			raise HTTPException(status_code=400, detail="Invalid response_date format, expected YYYY-MM-DD")

		raw_items = payload.get("items")
		if not isinstance(raw_items, list) or len(raw_items) == 0:
			raise HTTPException(status_code=400, detail="At least one item is required")
		_validate_response_items(raw_items)

		# The response must exist, its enquiry must still be actionable, and an
		# awarded quote is frozen (re-award a different response first).
		guard_row = db.execute(
			get_response_enquiry_status(),
			{"proc_price_enquiry_response_id": int(response_id)},
		).fetchone()
		if not guard_row:
			raise HTTPException(status_code=404, detail="Response not found")
		guard = dict(guard_row._mapping)
		if guard.get("status_id") in (5, 6):
			raise HTTPException(
				status_code=400,
				detail="Responses cannot be edited on a Closed or Cancelled enquiry",
			)
		if int(guard.get("is_selected") or 0) == 1:
			raise HTTPException(
				status_code=400,
				detail="This response has been awarded and can no longer be edited",
			)

		gross_total = 0.0
		net_total = 0.0
		for item in raw_items:
			g = _to_float(item.get("gross_amount"), "gross_amount") or 0
			n = _to_float(item.get("net_amount"), "net_amount") or 0
			gross_total += g
			net_total += n

		header_query = update_enquiry_response()
		db.execute(header_query, {
			"proc_price_enquiry_response_id": int(response_id),
			"supplier_id": int(supplier_id),
			"supplier_branch_id": supplier_branch_id,
			"response_date": response_date,
			"credit_days": credit_days,
			"delivery_days": delivery_days,
			"payment_terms": payment_terms,
			"terms_conditions": terms_conditions,
			"remarks": remarks,
			"gross_amount": gross_total,
			"net_amount": net_total,
			"updated_by": updated_by,
			"updated_date_time": created_at,
		})

		if isinstance(raw_items, list):
			del_dtl_query = delete_enquiry_response_dtl(response_id)
			db.execute(del_dtl_query, {
				"proc_price_enquiry_response_id": int(response_id),
				"updated_by": updated_by,
				"updated_date_time": created_at,
			})

			dtl_query = insert_enquiry_response_dtl()
			for item in raw_items:
				item_remarks = item.get("remarks")
				if item_remarks:
					item_remarks = str(item_remarks).strip()[:255]
				db.execute(dtl_query, {
					"proc_price_enquiry_response_id": int(response_id),
					"enquiry_dtl_id": _to_int(item.get("enquiry_dtl_id"), "enquiry_dtl_id"),
					"item_id": _to_int(item.get("item_id"), "item_id"),
					"item_make_id": _to_int(item.get("item_make_id"), "item_make_id"),
					"uom_id": _to_int(item.get("uom_id"), "uom_id"),
					"qty": _to_float(item.get("qty"), "qty"),
					"rate": _to_float(item.get("rate"), "rate"),
					"discount_mode": _to_int(item.get("discount_mode"), "discount_mode"),
					"discount_value": _to_float(item.get("discount_value"), "discount_value"),
					"discount_amount": _to_float(item.get("discount_amount"), "discount_amount"),
					"gross_amount": _to_float(item.get("gross_amount"), "gross_amount"),
					"net_amount": _to_float(item.get("net_amount"), "net_amount"),
					"remarks": item_remarks,
					"active": 1,
					"updated_by": updated_by,
					"updated_date_time": created_at,
				})

		db.commit()
		return {"message": "Response updated successfully", "response_id": response_id}
	except HTTPException as exc:
		db.rollback()
		raise
	except Exception as e:
		db.rollback()
		logger.exception("Error updating response")
		raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# GET RESPONSE BY ID
# =============================================================================

@router.get("/get_response_by_id")
def get_response_by_id(
	request: Request,
	db: Session = Depends(get_tenant_db),
	token_data: dict = Depends(get_current_user_with_refresh),
):
	"""Get a single response with its detail lines."""
	try:
		response_id = _to_int(request.query_params.get("response_id"), "response_id", required=True)

		query = get_response_detail_query()
		result = db.execute(query, {"response_id": int(response_id)}).fetchall()
		if not result:
			raise HTTPException(status_code=404, detail="Response not found")

		rows = [dict(r._mapping) for r in result]
		first = rows[0]
		header = {
			"proc_price_enquiry_response_id": response_id,
			"enquiry_id": first.get("enquiry_id"),
			"supplier_id": first.get("supplier_id"),
			"supplier_branch_id": first.get("supplier_branch_id"),
			"supp_name": first.get("supp_name"),
			"supp_code": first.get("supp_code"),
			"response_date": str(first.get("response_date")) if first.get("response_date") else None,
			"credit_days": first.get("credit_days"),
			"delivery_days": first.get("delivery_days"),
			"terms_conditions": first.get("terms_conditions"),
			"payment_terms": first.get("payment_terms"),
			"remarks": first.get("response_remarks"),
			"is_selected": first.get("is_selected", 0),
			"gross_amount": first.get("resp_gross_amount"),
			"net_amount": first.get("resp_net_amount"),
		}
		items = []
		for row in rows:
			if row.get("item_id"):
				items.append({
					"enquiry_dtl_id": row.get("enquiry_dtl_id"),
					"item_id": row.get("item_id"),
					"item_code": row.get("item_code"),
					"item_name": row.get("item_name"),
					"item_make_id": row.get("item_make_id"),
					"item_make_name": row.get("item_make_name"),
					"uom_id": row.get("uom_id"),
					"uom_name": row.get("uom_name"),
					"qty": row.get("qty"),
					"rate": row.get("rate"),
					"discount_mode": row.get("discount_mode"),
					"discount_value": row.get("discount_value"),
					"discount_amount": row.get("discount_amount"),
					"gross_amount": row.get("dtl_gross_amount"),
					"net_amount": row.get("dtl_net_amount"),
					"remarks": row.get("dtl_remarks"),
				})

		return {"data": {**header, "items": items}}
	except HTTPException:
		raise
	except Exception as e:
		logger.exception("Error fetching response by id")
		raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# COMPARISON
# =============================================================================

@router.get("/get_responses_for_comparison")
def get_responses_for_comparison(
	request: Request,
	db: Session = Depends(get_tenant_db),
	token_data: dict = Depends(get_current_user_with_refresh),
):
	"""Get all responses for an enquiry formatted for comparison."""
	try:
		enquiry_id = _to_int(request.query_params.get("enquiry_id"), "enquiry_id", required=True)

		query = get_responses_for_comparison_query()
		result = db.execute(query, {"enquiry_id": int(enquiry_id)}).fetchall()
		rows = [dict(r._mapping) for r in result]

		responses_map = {}
		for row in rows:
			rid = row.get("proc_price_enquiry_response_id")
			if rid not in responses_map:
				responses_map[rid] = {
					"proc_price_enquiry_response_id": rid,
					"supplier_id": row.get("supplier_id"),
					"supp_name": row.get("supp_name"),
					"supp_code": row.get("supp_code"),
					"response_date": str(row.get("date", "")) if row.get("date") else None,
					"credit_days": row.get("credit_days"),
					"delivery_days": row.get("delivery_days"),
					"payment_terms": row.get("payment_terms"),
					"terms_conditions": row.get("terms_conditions"),
					"gross_amount": row.get("resp_gross_amount"),
					"net_amount": row.get("resp_net_amount"),
					"is_selected": row.get("is_selected", 0),
					"items": [],
				}
			if row.get("item_id"):
				responses_map[rid]["items"].append({
					"enquiry_dtl_id": row.get("enquiry_dtl_id"),
					"item_id": row.get("item_id"),
					"item_code": row.get("item_code"),
					"item_name": row.get("item_name"),
					"uom_name": row.get("uom_name"),
					"qty": row.get("qty"),
					"rate": row.get("rate"),
					"discount_mode": row.get("discount_mode"),
					"discount_value": row.get("discount_value"),
					"discount_amount": row.get("discount_amount"),
					"gross_amount": row.get("dtl_gross_amount"),
					"net_amount": row.get("dtl_net_amount"),
				})

		return {"data": list(responses_map.values())}
	except HTTPException:
		raise
	except Exception as e:
		logger.exception("Error fetching comparison data")
		raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# SELECT RESPONSE
# =============================================================================

@router.post("/select_response")
def select_response(
	payload: dict,
	db: Session = Depends(get_tenant_db),
	token_data: dict = Depends(get_current_user_with_refresh),
):
	"""Award a supplier response for an enquiry.

	The enquiry must be Approved (status 3) before a response can be awarded,
	and the selection is applied atomically so concurrent awards cannot leave
	two responses marked as selected."""
	try:
		response_id = _to_int(payload.get("response_id"), "response_id", required=True)
		enquiry_id = _to_int(payload.get("enquiry_id"), "enquiry_id", required=True)
		updated_by = _to_int(token_data.get("user_id"), "updated_by")
		created_at = now_ist()

		# Gate: the response must belong to the enquiry and the enquiry must be
		# Approved before an award can be recorded.
		status_row = db.execute(
			get_response_enquiry_status(),
			{"proc_price_enquiry_response_id": int(response_id)},
		).fetchone()
		if not status_row:
			raise HTTPException(status_code=404, detail="Response not found")
		status_info = dict(status_row._mapping)
		if int(status_info.get("enquiry_id")) != int(enquiry_id):
			raise HTTPException(status_code=400, detail="Response does not belong to the specified enquiry")
		if status_info.get("status_id") != 3:
			raise HTTPException(
				status_code=400,
				detail="Response selection is only allowed for Approved enquiries",
			)

		# Single atomic statement: award the chosen response, clear all others.
		db.execute(select_response_atomic(), {
			"proc_price_enquiry_response_id": int(response_id),
			"enquiry_id": int(enquiry_id),
			"updated_by": updated_by,
			"updated_date_time": created_at,
		})

		db.commit()
		return {"message": "Response selected successfully", "response_id": response_id}
	except HTTPException as exc:
		db.rollback()
		raise
	except Exception as e:
		db.rollback()
		logger.exception("Error selecting response")
		raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# PO PREFILL DATA
# =============================================================================

@router.get("/get_po_prefill_data")
def get_po_prefill_data(
	request: Request,
	db: Session = Depends(get_tenant_db),
	token_data: dict = Depends(get_current_user_with_refresh),
):
	"""Get data from selected response to pre-fill PO creation."""
	try:
		response_id = _to_int(request.query_params.get("response_id"), "response_id", required=True)

		query = get_po_prefill_from_response()
		result = db.execute(query, {"response_id": int(response_id)}).fetchall()
		if not result:
			raise HTTPException(status_code=404, detail="Response not found")

		rows = [dict(r._mapping) for r in result]
		first = rows[0]

		# A PO must trace back to the awarded quote; block prefill from
		# responses that were never selected on the comparison page.
		if int(first.get("is_selected") or 0) != 1:
			raise HTTPException(
				status_code=400,
				detail="PO can only be created from the selected (awarded) response",
			)

		prefill = {
			"supplier_id": first.get("supplier_id"),
			"supplier_branch_id": first.get("supplier_branch_id"),
			"credit_days": first.get("credit_days"),
			"delivery_days": first.get("delivery_days"),
			"terms_conditions": first.get("terms_conditions"),
			"payment_terms": first.get("payment_terms"),
			"branch_id": first.get("branch_id"),
			"expense_type_id": first.get("expense_type_id"),
			"project_id": first.get("project_id"),
			"enquiry_id": first.get("enquiry_id"),
			"items": [],
		}

		for row in rows:
			if row.get("item_id"):
				prefill["items"].append({
					"item_id": row.get("item_id"),
					"item_code": row.get("item_code"),
					"item_name": row.get("item_name"),
					"item_grp_id": row.get("item_grp_id"),
					"hsn_code": row.get("hsn_code"),
					"item_make_id": row.get("item_make_id"),
					"item_make_name": row.get("item_make_name"),
					"uom_id": row.get("uom_id"),
					"uom_name": row.get("uom_name"),
					"qty": row.get("qty"),
					"rate": row.get("rate"),
					"discount_mode": row.get("discount_mode"),
					"discount_value": row.get("discount_value"),
					"discount_amount": row.get("discount_amount"),
					"indent_dtl_id": row.get("indent_dtl_id"),
				})

		return {"data": prefill}
	except HTTPException:
		raise
	except Exception as e:
		logger.exception("Error fetching PO prefill data")
		raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# APPROVAL ENDPOINTS
# =============================================================================

@router.post("/send_for_approval")
def send_for_approval(
	payload: dict,
	db: Session = Depends(get_tenant_db),
	token_data: dict = Depends(get_current_user_with_refresh),
):
	"""Send enquiry for approval (Draft/Open -> 20 Pending Approval, level 1).

	Approval itself is a separate /approve_enquiry click â€” even when no
	approval hierarchy is configured â€” so Reject stays reachable, matching
	the rest of the procurement module (see indent send_indent_for_approval)."""
	try:
		enquiry_id = _to_int(payload.get("enquiry_id"), "enquiry_id", required=True)
		menu_id = _to_int(payload.get("menu_id"), "menu_id", required=True)
		user_id = _to_int(token_data.get("user_id"), "user_id")
		created_at = now_ist()

		info_query = get_enquiry_with_approval_info()
		info_result = db.execute(info_query, {"enquiry_id": int(enquiry_id)}).fetchone()
		if not info_result:
			raise HTTPException(status_code=404, detail="Enquiry not found")
		info = dict(info_result._mapping)

		current_status = info.get("status_id")
		if current_status not in (21, 1):
			raise HTTPException(status_code=400, detail="Enquiry must be in Draft or Open status to send for approval")

		status_query = update_enquiry_status()
		db.execute(status_query, {
			"enquiry_id": int(enquiry_id),
			"status_id": 20,
			"approval_level": 1,
			"updated_by": user_id,
			"updated_date_time": created_at,
			"enquiry_no": None,
		})
		db.commit()

		return {"data": {
			"status": "success",
			"new_status_id": 20,
			"new_approval_level": 1,
			"message": "Price Enquiry sent for approval successfully.",
		}}
	except HTTPException as exc:
		db.rollback()
		raise
	except Exception as e:
		db.rollback()
		logger.exception("Error sending enquiry for approval")
		raise HTTPException(status_code=500, detail=str(e))


@router.post("/approve_enquiry")
def approve_enquiry(
	payload: dict,
	db: Session = Depends(get_tenant_db),
	token_data: dict = Depends(get_current_user_with_refresh),
):
	"""Approve a price enquiry."""
	try:
		enquiry_id = _to_int(payload.get("enquiry_id"), "enquiry_id", required=True)
		menu_id = _to_int(payload.get("menu_id"), "menu_id", required=True)
		user_id = _to_int(token_data.get("user_id"), "user_id")

		result = process_approval(
			doc_id=int(enquiry_id),
			user_id=int(user_id),
			menu_id=int(menu_id),
			db=db,
			get_doc_fn=get_enquiry_with_approval_info,
			update_status_fn=update_enquiry_status,
			id_param_name="enquiry_id",
			doc_name="Price Enquiry",
			extra_update_params={"enquiry_no": None},
		)

		return {"data": result}
	except HTTPException as exc:
		db.rollback()
		raise
	except Exception as e:
		db.rollback()
		logger.exception("Error approving enquiry")
		raise HTTPException(status_code=500, detail=str(e))


@router.post("/reject_enquiry")
def reject_enquiry(
	payload: dict,
	db: Session = Depends(get_tenant_db),
	token_data: dict = Depends(get_current_user_with_refresh),
):
	"""Reject a price enquiry."""
	try:
		enquiry_id = _to_int(payload.get("enquiry_id"), "enquiry_id", required=True)
		menu_id = _to_int(payload.get("menu_id"), "menu_id", required=True)
		user_id = _to_int(token_data.get("user_id"), "user_id")
		reason = payload.get("reason", "")

		result = process_rejection(
			doc_id=int(enquiry_id),
			user_id=int(user_id),
			menu_id=int(menu_id),
			db=db,
			get_doc_fn=get_enquiry_with_approval_info,
			update_status_fn=update_enquiry_status,
			id_param_name="enquiry_id",
			doc_name="Price Enquiry",
			reason=str(reason) if reason else None,
			extra_update_params={"enquiry_no": None},
		)

		return {"data": result}
	except HTTPException as exc:
		db.rollback()
		raise
	except Exception as e:
		db.rollback()
		logger.exception("Error rejecting enquiry")
		raise HTTPException(status_code=500, detail=str(e))


@router.post("/cancel_enquiry")
def cancel_enquiry(
	payload: dict,
	db: Session = Depends(get_tenant_db),
	token_data: dict = Depends(get_current_user_with_refresh),
):
	"""Cancel a price enquiry. Allowed from Draft (21) or Open (1) -> Cancelled (6).
	Approved enquiries cannot be cancelled (matches the frontend gating)."""
	try:
		enquiry_id = _to_int(payload.get("enquiry_id"), "enquiry_id", required=True)
		user_id = _to_int(token_data.get("user_id"), "user_id")
		created_at = now_ist()

		info_result = db.execute(
			get_enquiry_with_approval_info(), {"enquiry_id": int(enquiry_id)}
		).fetchone()
		if not info_result:
			raise HTTPException(status_code=404, detail="Enquiry not found")
		current_status = dict(info_result._mapping).get("status_id")
		if current_status not in (21, 1):
			raise HTTPException(
				status_code=400,
				detail="Only Draft or Open enquiries can be cancelled",
			)

		db.execute(update_enquiry_status(), {
			"enquiry_id": int(enquiry_id),
			"status_id": 6,
			"approval_level": None,
			"updated_by": user_id,
			"updated_date_time": created_at,
			"enquiry_no": None,
		})
		db.commit()
		return {"data": {"status": "success", "new_status_id": 6, "message": "Enquiry cancelled"}}
	except HTTPException:
		db.rollback()
		raise
	except Exception as e:
		db.rollback()
		logger.exception("Error cancelling enquiry")
		raise HTTPException(status_code=500, detail=str(e))


@router.post("/reopen_enquiry")
def reopen_enquiry(
	payload: dict,
	db: Session = Depends(get_tenant_db),
	token_data: dict = Depends(get_current_user_with_refresh),
):
	"""Reopen a Cancelled (6) or Rejected (4) enquiry back to Draft (21)."""
	try:
		enquiry_id = _to_int(payload.get("enquiry_id"), "enquiry_id", required=True)
		user_id = _to_int(token_data.get("user_id"), "user_id")
		created_at = now_ist()

		info_result = db.execute(
			get_enquiry_with_approval_info(), {"enquiry_id": int(enquiry_id)}
		).fetchone()
		if not info_result:
			raise HTTPException(status_code=404, detail="Enquiry not found")
		current_status = dict(info_result._mapping).get("status_id")
		if current_status not in (6, 4):
			raise HTTPException(
				status_code=400,
				detail="Only Cancelled or Rejected enquiries can be reopened",
			)

		db.execute(update_enquiry_status(), {
			"enquiry_id": int(enquiry_id),
			"status_id": 21,
			"approval_level": None,
			"updated_by": user_id,
			"updated_date_time": created_at,
			"enquiry_no": None,
		})
		db.commit()
		return {"data": {"status": "success", "new_status_id": 21, "message": "Enquiry reopened"}}
	except HTTPException:
		db.rollback()
		raise
	except Exception as e:
		db.rollback()
		logger.exception("Error reopening enquiry")
		raise HTTPException(status_code=500, detail=str(e))
