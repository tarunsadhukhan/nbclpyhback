from fastapi import Depends, Request, HTTPException, APIRouter, Response, Cookie
import os
from sqlalchemy.sql import text
from sqlalchemy.orm import Session
from src.config.db import get_db_names, default_engine, get_tenant_db
from src.authorization.utils import  get_current_user_with_refresh
# from src.masters.schemas import MenuResponse
from src.masters.models import ItemGrpMst, ItemTypeMaster, ItemMst, ItemMake
from src.masters.query import get_item_group, get_item_group_drodown, india_gst_applicable, get_item_table, check_item_group_code_and_name
from src.masters.query import get_item_group_details_by_id, get_item_minmax_mapping, get_item, get_item_uom_mapping, get_uom_list, get_item_by_id
from src.masters.query import get_item_group_path, get_item_make
from src.masters.query import get_item_search_list_query, get_item_search_count_query, get_item_makes_by_group_ids_query, get_item_uoms_by_item_ids_query
from src.masters.query import get_item_table_list_query, get_item_table_count_query
from datetime import datetime
from src.common.utils import now_ist

router = APIRouter()


def optional_auth(request: Request, response: Response, access_token: str = Cookie(None, alias="access_token")) -> dict:
    """Dev-toggle auth dependency.
    If BYPASS_AUTH=1 or ENV=development, return a dummy user dict. Otherwise delegate to the real auth helper.
    """
    BYPASS = os.getenv("BYPASS_AUTH", "0")
    ENV = os.getenv("ENV", "development")
    if BYPASS == "1" or ENV == "development":
        return {"user_id": 1}
    # Delegate to the real auth function which will raise HTTPException if token invalid
    return get_current_user_with_refresh(request, response, access_token)


@router.get("/get_all_item_groups")
def get_item_groups(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    search: str = None
):
    try:
        # Get the item groups for the company specified in the request received
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")
        # Prepare search parameter for LIKE if provided
        search_param = f"%{search}%" if search else None
        query = get_item_group(int(co_id))
        result = db.execute(query, {"co_id": int(co_id), "search": search_param}).fetchall()
        data = [dict(row._mapping) for row in result]
        return {"data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    


@router.get("/createItemGroupSetup")
def create_item_group_setup(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    is_india_gst_applicable = False  # Ensure variable is always defined
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")
        # No search param for setup, just get all item groups for dropdown
        query = get_item_group_drodown(int(co_id))
        result = db.execute(query, {"co_id": int(co_id), "search": None}).fetchall()
        item_groups = [dict(row._mapping) for row in result]
        # Get all item types for dropdown
        item_types = db.query(ItemTypeMaster).all()
        item_type_list = [
            {"item_type_id": t.item_type_id, "item_type_name": t.item_type_name}
            for t in item_types
        ]
        # Check if India GST is applicable for the company
        india_gst_query = india_gst_applicable()
        result = db.execute(india_gst_query, {"co_id": int(co_id)}).fetchone()
        if result and result[0] is not None:
            is_india_gst_applicable = result[0]
        return {"item_groups": item_groups, "item_types": item_type_list, "india_gst_applicable": is_india_gst_applicable}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/createItemGroup")
def create_item_group(
    payload: dict,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh)
):
    try:
        def sanitize_int(value):
            return int(value) if isinstance(value, int) or (isinstance(value, str) and value.isdigit()) else None

        parent_grp_id = sanitize_int(payload.get("parent_grp_id"))
        item_type_id = sanitize_int(payload.get("item_type_id"))
        co_id = payload.get("co_id")
        item_grp_code = payload.get("item_grp_code")
        item_grp_name = payload.get("item_grp_name")
        updated_by = payload.get("updated_by") or str(token_data.get("user_id"))

        
        new_group = ItemGrpMst(
            co_id=co_id,
            active=1,
            updated_by=updated_by,
            updated_date_time=payload.get("updated_date_time", now_ist()),
            item_grp_name=item_grp_name,
            item_grp_code=item_grp_code,
            item_type_id=item_type_id,
            parent_grp_id=parent_grp_id
        )
        db.add(new_group)
        db.commit()
        db.refresh(new_group)
        return {"message": "Item group created successfully", "item_grp_id": new_group.item_grp_id}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    


@router.post("/updateItemGroupActive")
def update_item_group_active_status(
    payload: dict,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh)
):
    try:
        item_grp_id = payload.get("item_grp_id")
        active_status = payload.get("active")
        co_id = payload.get("co_id")

        if item_grp_id is None or active_status is None or co_id is None:
            raise HTTPException(status_code=400, detail="Item group ID, active status, and company ID are required")

        # Fetch the item group by id and company
        item_group = db.query(ItemGrpMst).filter_by(item_grp_id=item_grp_id, co_id=co_id).first()
        if not item_group:
            raise HTTPException(status_code=404, detail="Item group not found")

        item_group.active = active_status
        db.commit()
        return {"message": "Item group active status updated successfully"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    
@router.post("/itemGroupDetails")
def get_item_group_details(
    payload: dict,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh)
):
    try:
        item_grp_id = payload.get("itemgroupid")
        if not item_grp_id:
            raise HTTPException(status_code=400, detail="Item group ID (itemgroupid) is required")
        from src.masters.query import get_item_group_details_by_id
        query = get_item_group_details_by_id()
        result = db.execute(query, {"item_grp_id": int(item_grp_id)}).fetchone()
        if not result:
            raise HTTPException(status_code=404, detail="Item group not found")
        return dict(result._mapping)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@router.get("/get_item_table")
def get_item(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    page: int = 1,
    limit: int = 10,
    search: str = None
):
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")
        co_id = int(co_id)
        page = max(int(page), 1)
        limit = max(min(int(limit), 100), 1)
        offset = (page - 1) * limit
        search_like = f"%{search.strip()}%" if search and search.strip() else None
        params = {"co_id": co_id, "search_like": search_like, "limit": limit, "offset": offset}
        rows = db.execute(get_item_table_list_query(), params).fetchall()
        data = [dict(row._mapping) for row in rows]
        total = db.execute(
            get_item_table_count_query(),
            {"co_id": co_id, "search_like": search_like},
        ).scalar() or 0
        return {"data": data, "total": int(total)}
    except HTTPException:
        raise
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid page/limit/co_id")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    

@router.get("/item_create_setup")
def get_item_create_setup(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    item_id: int = None
):
    try:
        co_id = request.query_params.get("co_id")

        itemgroup_query = get_item_group_drodown(int(co_id))
        itemgroups = db.execute(itemgroup_query, {"co_id": int(co_id)}).fetchall()
        uomgroup_query = get_uom_list()
        uomgroups = db.execute(uomgroup_query, {"co_id": int(co_id)}).fetchall()
        minmax_query = get_item_minmax_mapping(None, int(co_id))
        minmax_mapping = db.execute(minmax_query, {"item_id": None, "co_id": int(co_id)}).fetchall()
        if not itemgroups:
            raise HTTPException(status_code=404, detail="Item groups not found")
        return {
            "itemgroups": [dict(row._mapping) for row in itemgroups], 
            "uomgroups": [dict(row._mapping) for row in uomgroups],
            "minmax_mapping": [dict(row._mapping) for row in minmax_mapping]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/item_edit_setup")
def get_item_edit_setup(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        # read required query params
        co_id = request.query_params.get("co_id")
        item_id = request.query_params.get("item_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")
        if not item_id:
            raise HTTPException(status_code=400, detail="Item ID (item_id) is required")

        co_id = int(co_id)
        item_id = int(item_id)


        # uom list
        uomgroup_query = get_uom_list()
        uomgroups = db.execute(uomgroup_query).fetchall()

        # item details
        item_query = get_item_by_id(item_id)
        item_row = db.execute(item_query, {"item_id": item_id}).fetchone()
        if not item_row:
            raise HTTPException(status_code=404, detail="Item not found")
        item_details = dict(item_row._mapping)

        # uom mappings for the item
        uom_map_query = get_item_uom_mapping(item_id)
        uom_mappings = db.execute(uom_map_query, {"item_id": item_id}).fetchall()

        # minmax mapping for the item and company
        minmax_query = get_item_minmax_mapping(item_id, co_id)
        minmax_mapping = db.execute(minmax_query, {"item_id": item_id, "co_id": co_id}).fetchall()

        # item group path for the item's group
        item_grp_id = item_details.get("item_grp_id")
        group_path = None
        if item_grp_id:
            group_path_query = get_item_group_path(item_grp_id)
            group_path_row = db.execute(group_path_query).fetchone()
            group_path = dict(group_path_row._mapping) if group_path_row else None

        return {
            "uomgroups": [dict(row._mapping) for row in uomgroups],
            "item_details": item_details,
            "uom_mappings": [dict(row._mapping) for row in uom_mappings],
            "minmax_mapping": [dict(row._mapping) for row in minmax_mapping],
            "item_group_path": group_path,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


    
# =============================================================================
# ITEM CREATE: shared helpers (used by single + bulk endpoints)
# =============================================================================

ITEM_STR_MAX_LEN = 255


def _sanitize_int(value):
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    return None


def _normalize_item_payload(payload: dict, token_user_id) -> dict:
    """Map incoming camelCase or snake_case payload to a normalized dict."""
    updated_by_raw = payload.get("updated_by") or str(token_user_id)
    try:
        tax_pct = float(payload.get("taxPercent") or payload.get("tax_percentage") or 0.0)
    except (TypeError, ValueError):
        tax_pct = None
    good_or_service = payload.get("goodOrService")
    tangible = bool(
        (isinstance(good_or_service, str) and good_or_service.lower().startswith("g"))
        or good_or_service == "Good"
    )
    return {
        "item_grp_id": _sanitize_int(payload.get("itemGroupId") or payload.get("item_grp_id")),
        "item_code": (payload.get("itemCode") or payload.get("item_code") or "").strip() or None,
        "item_name": (payload.get("itemName") or payload.get("item_name") or "").strip() or None,
        "uom_id": _sanitize_int(payload.get("uomId") or payload.get("uom_id")),
        "hsn_code": payload.get("hsnCode") or payload.get("hsn_code"),
        "tax_percentage": tax_pct,
        "uom_rounding": _sanitize_int(payload.get("uomRounding") or payload.get("uom_rounding")),
        "rate_rounding": _sanitize_int(payload.get("rateRounding") or payload.get("rate_rounding")),
        "tangible": tangible,
        "saleable": bool(payload.get("saleable")),
        "consumable": bool(payload.get("consumable")),
        "purchaseable": bool(payload.get("purchaseable")),
        "manufacturable": bool(payload.get("manufacturable")),
        "assembly": bool(payload.get("assembly")),
        "updated_by": int(updated_by_raw) if str(updated_by_raw).isdigit() else None,
    }


def _validate_item_payload(
    db: Session,
    co_id: int,
    n: dict,
    *,
    row_idx: int = 0,
    batch_codes_seen: dict | None = None,
    batch_names_seen: dict | None = None,
    valid_group_ids: set | None = None,
    valid_uom_ids: set | None = None,
) -> list[dict]:
    """Return list of error dicts: {row_idx, field, code, message}.

    batch_codes_seen / batch_names_seen are mutated in-place to track within-batch dupes.
    Pre-loaded valid_group_ids / valid_uom_ids avoid N+1 lookups when validating batches.
    """
    errors: list[dict] = []

    def err(field: str, code: str, message: str) -> None:
        errors.append({"row_idx": row_idx, "field": field, "code": code, "message": message})

    if n.get("item_grp_id") is None:
        err("itemGroupId", "REQUIRED", "Item group is required")
    if not n.get("item_code"):
        err("itemCode", "REQUIRED", "Item code is required")
    if not n.get("item_name"):
        err("itemName", "REQUIRED", "Item name is required")
    if n.get("uom_id") is None:
        err("uomId", "REQUIRED", "UOM is required")

    if n.get("tax_percentage") is None:
        err("taxPercent", "INVALID_TYPE", "tax_percentage must be a number")
    elif not (0.0 <= n["tax_percentage"] <= 100.0):
        err("taxPercent", "INVALID_TYPE", "tax_percentage must be between 0 and 100")

    for f, db_col in (("item_code", "itemCode"), ("item_name", "itemName"), ("hsn_code", "hsnCode")):
        v = n.get(f)
        if v and len(v) > ITEM_STR_MAX_LEN:
            err(db_col, "LENGTH_EXCEEDED", f"{db_col} exceeds {ITEM_STR_MAX_LEN} chars")

    grp = n.get("item_grp_id")
    if grp is not None and valid_group_ids is not None and grp not in valid_group_ids:
        err("itemGroupId", "FK_NOT_FOUND", "Item group not found for this company")
    uom = n.get("uom_id")
    if uom is not None and valid_uom_ids is not None and uom not in valid_uom_ids:
        err("uomId", "FK_NOT_FOUND", "UOM not found or inactive")

    if batch_codes_seen is not None and grp is not None and n.get("item_code"):
        key = (grp, n["item_code"])
        prior = batch_codes_seen.get(key)
        if prior is not None:
            err("itemCode", "DUP_IN_BATCH", f"Duplicate of row {prior + 1} in this batch")
        else:
            batch_codes_seen[key] = row_idx
    if batch_names_seen is not None and n.get("item_name"):
        key = n["item_name"]
        prior = batch_names_seen.get(key)
        if prior is not None:
            err("itemName", "DUP_IN_BATCH", f"Duplicate of row {prior + 1} in this batch")
        else:
            batch_names_seen[key] = row_idx

    if grp is not None and n.get("item_code"):
        existing_code = db.query(ItemMst).filter(
            ItemMst.item_grp_id == grp, ItemMst.item_code == n["item_code"]
        ).first()
        if existing_code:
            err("itemCode", "DUP_IN_DB", "Item code already exists in this group")
    if n.get("item_name") and valid_group_ids:
        existing_name = db.query(ItemMst).filter(
            ItemMst.item_grp_id.in_(valid_group_ids),
            ItemMst.item_name == n["item_name"],
        ).first()
        if existing_name:
            err("itemName", "DUP_IN_DB", "Item name already exists for this company")

    return errors


def _insert_item(db: Session, n: dict) -> int:
    """Insert a single item from a normalized payload. Caller manages transaction."""
    new_item = ItemMst(
        active=1,
        updated_by=n["updated_by"],
        item_grp_id=n["item_grp_id"],
        item_code=n["item_code"],
        tangible=n["tangible"],
        item_name=n["item_name"],
        hsn_code=n["hsn_code"],
        uom_id=n["uom_id"],
        tax_percentage=n["tax_percentage"],
        saleable=n["saleable"],
        consumable=n["consumable"],
        purchaseable=n["purchaseable"],
        manufacturable=n["manufacturable"],
        assembly=n["assembly"],
        uom_rounding=n["uom_rounding"],
        rate_rounding=n["rate_rounding"],
    )
    db.add(new_item)
    db.flush()
    return new_item.item_id


def _load_company_lookups(db: Session, co_id: int) -> tuple[set, set]:
    """Return (valid_group_ids_for_company, valid_active_uom_ids)."""
    group_ids = {g.item_grp_id for g in db.query(ItemGrpMst).filter(ItemGrpMst.co_id == co_id).all()}
    uom_rows = db.execute(get_uom_list()).fetchall()
    uom_ids = {row._mapping["uom_id"] for row in uom_rows}
    return group_ids, uom_ids


def _error_code_to_http_status(errors: list[dict]) -> int:
    if not errors:
        return 200
    code = errors[0]["code"]
    if code in ("DUP_IN_BATCH", "DUP_IN_DB"):
        return 409
    return 400


@router.post("/item_create")
def create_item(
    payload: dict,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh)
):
    try:
        co_id = _sanitize_int(payload.get("co_id"))
        if co_id is None:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")

        normalized = _normalize_item_payload(payload, token_data.get("user_id"))
        valid_group_ids, valid_uom_ids = _load_company_lookups(db, co_id)
        errors = _validate_item_payload(
            db,
            co_id,
            normalized,
            row_idx=0,
            batch_codes_seen={},
            batch_names_seen={},
            valid_group_ids=valid_group_ids,
            valid_uom_ids=valid_uom_ids,
        )
        if errors:
            raise HTTPException(
                status_code=_error_code_to_http_status(errors),
                detail=errors[0]["message"],
            )

        item_id = _insert_item(db, normalized)
        db.commit()
        response.status_code = 201
        return {"message": "Item created successfully", "item_id": item_id}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/item_bulk_validate")
def item_bulk_validate(
    payload: dict,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Dry-run validation for a batch of items. No writes."""
    try:
        co_id = _sanitize_int(payload.get("co_id"))
        if co_id is None:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")
        rows = payload.get("rows") or []
        if not isinstance(rows, list):
            raise HTTPException(status_code=400, detail="rows must be a list")

        valid_group_ids, valid_uom_ids = _load_company_lookups(db, co_id)
        all_errors: list[dict] = []
        batch_codes_seen: dict = {}
        batch_names_seen: dict = {}
        for idx, row in enumerate(rows):
            normalized = _normalize_item_payload(row, token_data.get("user_id"))
            row_errors = _validate_item_payload(
                db,
                co_id,
                normalized,
                row_idx=idx,
                batch_codes_seen=batch_codes_seen,
                batch_names_seen=batch_names_seen,
                valid_group_ids=valid_group_ids,
                valid_uom_ids=valid_uom_ids,
            )
            all_errors.extend(row_errors)

        return {
            "valid": len(all_errors) == 0,
            "row_count": len(rows),
            "error_count": len(all_errors),
            "errors": all_errors,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/item_bulk_create")
def item_bulk_create(
    payload: dict,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Re-validate the batch then insert all rows in a single transaction.
    All-or-nothing: any validation error blocks the entire batch.
    """
    try:
        co_id = _sanitize_int(payload.get("co_id"))
        if co_id is None:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")
        rows = payload.get("rows") or []
        if not isinstance(rows, list) or not rows:
            raise HTTPException(status_code=400, detail="rows must be a non-empty list")

        valid_group_ids, valid_uom_ids = _load_company_lookups(db, co_id)
        normalized_rows: list[dict] = []
        all_errors: list[dict] = []
        batch_codes_seen: dict = {}
        batch_names_seen: dict = {}
        for idx, row in enumerate(rows):
            n = _normalize_item_payload(row, token_data.get("user_id"))
            normalized_rows.append(n)
            row_errors = _validate_item_payload(
                db,
                co_id,
                n,
                row_idx=idx,
                batch_codes_seen=batch_codes_seen,
                batch_names_seen=batch_names_seen,
                valid_group_ids=valid_group_ids,
                valid_uom_ids=valid_uom_ids,
            )
            all_errors.extend(row_errors)

        if all_errors:
            raise HTTPException(
                status_code=400,
                detail={
                    "valid": False,
                    "row_count": len(rows),
                    "error_count": len(all_errors),
                    "errors": all_errors,
                },
            )

        try:
            created_ids = [_insert_item(db, n) for n in normalized_rows]
            db.commit()
        except Exception as e:
            db.rollback()
            raise HTTPException(status_code=500, detail=f"Insert failed: {e}")

        response.status_code = 201
        return {"created_count": len(created_ids), "item_ids": created_ids}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    


@router.api_route("/item_edit", methods=["POST", "PUT"])
def item_update_full(
    payload: dict,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(optional_auth)
):
    """Update ItemMst, ItemMinmaxMst and UomItemMapMst from the provided payload.

    Expected payload keys: item_id, itemGroupId, itemCode, itemName, taxPercent, uomId,
    uomRounding, rateRounding, goodOrService, saleable, consumable, purchaseable,
    manufacturable, assembly, uom_mappings (list), minmax_mappings (list)
    """
    def sanitize_int(value):
        return int(value) if isinstance(value, int) or (isinstance(value, str) and str(value).isdigit()) else None

    def sanitize_float(value):
        try:
            return float(value)
        except Exception:
            return None

    item_id = sanitize_int(payload.get("item_id"))
    if not item_id:
        raise HTTPException(status_code=400, detail="item_id is required")

    # load existing item
    existing = db.query(ItemMst).filter(ItemMst.item_id == item_id).first()
    if not existing:
        raise HTTPException(status_code=404, detail="Item not found")

    # map fields
    item_grp_id = sanitize_int(payload.get("itemGroupId") or payload.get("item_grp_id") )
    item_code = payload.get("itemCode") or payload.get("item_code")
    item_name = payload.get("itemName") or payload.get("item_name")
    uom_id = sanitize_int(payload.get("uomId") or payload.get("uom_id"))
    tax_percentage = sanitize_float(payload.get("taxPercent") or payload.get("tax_percentage")) or (existing.tax_percentage or 0.0)
    uom_rounding = sanitize_int(payload.get("uomRounding") or payload.get("uom_rounding"))
    rate_rounding = sanitize_int(payload.get("rateRounding") or payload.get("rate_rounding"))
    good_or_service = payload.get("goodOrService")
    saleable = payload.get("saleable") if "saleable" in payload else existing.saleable
    consumable = payload.get("consumable") if "consumable" in payload else existing.consumable
    purchaseable = payload.get("purchaseable") if "purchaseable" in payload else existing.purchaseable
    manufacturable = payload.get("manufacturable") if "manufacturable" in payload else existing.manufacturable
    assembly = payload.get("assembly") if "assembly" in payload else existing.assembly

    # Prefer user id from token for updated_by; fall back to payload.updated_by if token missing
    user_id = None
    if token_data and token_data.get("user_id"):
        user_id = token_data.get("user_id")
    else:
        user_id = payload.get("updated_by")

    # perform update inside transaction
    try:
        # update item_mst
        if item_grp_id is not None:
            existing.item_grp_id = item_grp_id
        if item_code is not None:
            existing.item_code = item_code
        if item_name is not None:
            existing.item_name = item_name
        if uom_id is not None:
            existing.uom_id = uom_id
        existing.hsn_code = payload.get("hsnCode") or existing.hsn_code
        existing.tax_percentage = float(tax_percentage)
        if uom_rounding is not None:
            existing.uom_rounding = uom_rounding
        if rate_rounding is not None:
            existing.rate_rounding = rate_rounding
        existing.tangible = True if (isinstance(good_or_service, str) and good_or_service.lower().startswith('g')) or good_or_service == 'Good' else existing.tangible
        existing.saleable = bool(saleable)
        existing.consumable = bool(consumable)
        existing.purchaseable = bool(purchaseable)
        existing.manufacturable = bool(manufacturable)
        existing.assembly = bool(assembly)
        existing.updated_by = int(user_id) if user_id and str(user_id).isdigit() else existing.updated_by
        existing.updated_date_time = now_ist()

        # UOM mappings: replace existing
        uom_mappings = payload.get("uom_mappings") or []
        delete_uom_sql = text("DELETE FROM uom_item_map_mst WHERE item_id = :item_id")
        db.execute(delete_uom_sql, {"item_id": item_id})
        for m in uom_mappings:
            map_from = sanitize_int(m.get("map_from_id") or m.get("mapFromUom") or m.get("map_from_uom")) or existing.uom_id
            map_to = sanitize_int(m.get("map_to_id") or m.get("mapToUom") or m.get("map_to_uom"))
            is_fixed = 1 if m.get("isFixed") or m.get("is_fixed") else 0
            relation_value = sanitize_float(m.get("relationValue") or m.get("relation_value"))
            rounding = sanitize_int(m.get("rounding"))
            insert_uom_sql = text(
                "INSERT INTO uom_item_map_mst (item_id, map_from_id, map_to_id, is_fixed, relation_value, rounding, updated_by, updated_date_time) VALUES (:item_id, :map_from, :map_to, :is_fixed, :relation_value, :rounding, :updated_by, :updated_date_time)"
            )
            db.execute(insert_uom_sql, {
                "item_id": item_id,
                "map_from": map_from,
                "map_to": map_to,
                "is_fixed": is_fixed,
                "relation_value": relation_value,
                "rounding": rounding,
                "updated_by": int(user_id) if user_id and str(user_id).isdigit() else None,
                "updated_date_time": now_ist()
            })

        # Minmax mappings: replace existing
        minmax_mappings = payload.get("minmax_mappings") or []
        delete_minmax_sql = text("DELETE FROM item_minmax_mst WHERE item_id = :item_id")
        db.execute(delete_minmax_sql, {"item_id": item_id})
        for mm in minmax_mappings:
            branch_id = sanitize_int(mm.get("branch_id"))
            minqty = sanitize_float(mm.get("minqty"))
            maxqty = sanitize_float(mm.get("maxqty"))
            min_order_qty = sanitize_float(mm.get("min_order_qty") or mm.get("min_order_qty"))
            lead_time = sanitize_int(mm.get("lead_time"))
            insert_minmax_sql = text(
                "INSERT INTO item_minmax_mst (branch_id, item_id, minqty, maxqty, min_order_qty, lead_time, updated_by, updated_date_time, active) VALUES (:branch_id, :item_id, :minqty, :maxqty, :min_order_qty, :lead_time, :updated_by, :updated_date_time, :active)"
            )
            db.execute(insert_minmax_sql, {
                "branch_id": branch_id,
                "item_id": item_id,
                "minqty": minqty,
                "maxqty": maxqty,
                "min_order_qty": min_order_qty,
                "lead_time": lead_time,
                "updated_by": int(user_id) if user_id and str(user_id).isdigit() else None,
                "updated_date_time": now_ist(),
                "active": 1
            })

        db.commit()
        db.refresh(existing)
        return {"message": "Item updated successfully", "item_id": item_id}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    

@router.get("/item_make_table")
def item_make_table(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    search: str = None
):
    try:
        # Get the item groups for the company specified in the request received
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")
        # Prepare search parameter for LIKE if provided
        search_param = f"%{search}%" if search else None
        query = get_item_make(int(co_id))
        result = db.execute(query, {"co_id": int(co_id), "search": search_param}).fetchall()
        data = [dict(row._mapping) for row in result]
        return {"data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@router.get("/item_make_create_setup")
def item_make_create_setup(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh)
):
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")
        query = get_item_group_drodown(int(co_id))
        result = db.execute(query, {"co_id": int(co_id)}).fetchall()
        data = [dict(row._mapping) for row in result]
        return {"data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@router.post("/item_make_create")
def item_make_create(
    payload: dict,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(optional_auth)
):
    """Create an ItemMake. Derive updated_by from token when available.

    Accepts payload keys: item_grp_id, item_make or item_make_name, (optional) co_id.
    """
    try:
        item_grp_id = payload.get("item_grp_id")
        # accept either `item_make` or `item_make_name` from clients
        item_make_name = payload.get("item_make") or payload.get("item_make_name")

        # Prefer user id from token_data; fall back to payload.updated_by if token missing
        user_id = None
        if token_data and token_data.get("user_id"):
            user_id = token_data.get("user_id")
        else:
            user_id = payload.get("updated_by")

        if not item_grp_id or not item_make_name:
            raise HTTPException(status_code=400, detail="Item group ID and item make name are required")

        new_item_make = ItemMake(
            item_grp_id=item_grp_id,
            item_make_name=item_make_name,
            updated_by=int(user_id) if user_id and str(user_id).isdigit() else None,
            updated_date_time=now_ist()
        )
        db.add(new_item_make)
        db.commit()
        db.refresh(new_item_make)
        response.status_code = 201
        return {"message": "Item make created successfully", "item_make_id": new_item_make.item_make_id}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/item_search")
def item_search(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Paginated searchable item list for item selection dialog.
    Returns items with group hierarchy, default UOM, HSN code, tax info,
    plus makes and UOM mappings for the returned items.

    Query params:
        co_id: Company ID (required)
        page: Page number, 1-indexed (default: 1)
        limit: Records per page, max 50 (default: 15)
        search: Search term for item code/name, group code/name, HSN code
        filter: Optional filter - 'purchaseable' or 'saleable'
    """
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        try:
            co_id_int = int(co_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid co_id format")

        raw_page = request.query_params.get("page", "1")
        raw_limit = request.query_params.get("limit", "15")
        raw_search = request.query_params.get("search")
        item_filter = request.query_params.get("filter")

        try:
            page = max(1, int(raw_page))
        except (TypeError, ValueError):
            page = 1

        try:
            limit = max(1, min(int(raw_limit), 50))
        except (TypeError, ValueError):
            limit = 15

        offset = (page - 1) * limit
        search_like = f"%{raw_search.strip()}%" if raw_search and raw_search.strip() else None

        # Get count
        count_query = get_item_search_count_query()
        count_result = db.execute(count_query, {
            "co_id": co_id_int,
            "search_like": search_like,
        }).fetchone()
        total = count_result.total if count_result else 0

        # Get items
        query = get_item_search_list_query()
        rows = db.execute(query, {
            "co_id": co_id_int,
            "search_like": search_like,
            "limit": limit,
            "offset": offset,
        }).fetchall()

        items = [dict(row._mapping) for row in rows]

        # Apply purchaseable/saleable filter in Python to keep SQL simpler
        if item_filter == "purchaseable":
            items = [item for item in items if item.get("purchaseable") == 1]
        elif item_filter == "saleable":
            items = [item for item in items if item.get("saleable") == 1]

        if not items:
            return {"data": [], "total": 0 if item_filter else total, "page": page, "limit": limit, "makes": [], "uoms": []}

        # Collect unique item_grp_ids and item_ids from results
        item_grp_ids = list({item["item_grp_id"] for item in items if item.get("item_grp_id")})
        item_ids = list({item["item_id"] for item in items if item.get("item_id")})

        # Fetch makes for returned item groups
        makes = []
        if item_grp_ids:
            makes_query = get_item_makes_by_group_ids_query()
            makes_rows = db.execute(makes_query, {"item_grp_ids": item_grp_ids}).fetchall()
            makes = [dict(row._mapping) for row in makes_rows]

        # Fetch UOM mappings for returned items
        uoms = []
        if item_ids:
            uoms_query = get_item_uoms_by_item_ids_query()
            uoms_rows = db.execute(uoms_query, {"item_ids": item_ids}).fetchall()
            uoms = [dict(row._mapping) for row in uoms_rows]

        return {
            "data": items,
            "total": total,
            "page": page,
            "limit": limit,
            "makes": makes,
            "uoms": uoms,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

