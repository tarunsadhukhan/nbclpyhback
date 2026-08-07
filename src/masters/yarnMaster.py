"""
Yarn Master API endpoints.
Provides CRUD operations for jute yarn master data.

Each yarn record in jute_yarn_mst has a corresponding item_mst record.
On create, item_mst is created first, then jute_yarn_mst references it via item_id.
On edit, item_mst is updated first, then jute_yarn_mst details.

Schema (jute_yarn_mst):
- jute_yarn_id: int (PK, auto)
- jute_yarn_count: float (nullable)
- item_grp_id: int (FK to item_grp_mst, yarn type group)
- jute_yarn_remarks: str (nullable)
- item_id: int (FK to item_mst, the linked item record)
- jute_yarn_name: str (DEPRECATED - kept for backward compat; name from item_mst)
- co_id: int (DEPRECATED - kept for backward compat; scoping via item_grp_mst)
- updated_date_time: datetime
- updated_by: int
"""

from fastapi import Depends, Request, HTTPException, APIRouter, Response
from sqlalchemy.sql import text
from sqlalchemy.orm import Session
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.models.jute import JuteYarnMst
from src.models.item import ItemMst, ItemGrpMst
from datetime import datetime
from src.common.utils import now_ist
from src.common.utils import parse_json_body

router = APIRouter()

# item_type_id for Yarn in item_type_master
YARN_ITEM_TYPE_ID = 4

# Default item_mst field values for yarn items
YARN_ITEM_DEFAULTS = {
    "active": 1,
    "tangible": True,
    "hsn_code": "5304",
    "tax_percentage": 5.0,
    "saleable": True,
    "consumable": True,
    "purchaseable": True,
    "manufacturable": True,
    "assembly": False,
    "uom_rounding": 0,
    "rate_rounding": 2,
}


def _resolve_yarn_uom_id(db: Session) -> int:
    """
    Resolve the tenant's KG unit from uom_mst at runtime.
    uom_mst ids differ per tenant DB (dev3: KG=163, sls: KGS=132),
    so a hardcoded id breaks the item_mst FK on other tenants.
    """
    row = db.execute(text("""
        SELECT uom_id FROM uom_mst
        WHERE UPPER(TRIM(uom_name)) IN ('KG', 'KGS', 'KGS.')
          AND active = 1
        ORDER BY FIELD(UPPER(TRIM(uom_name)), 'KG', 'KGS', 'KGS.'), uom_id
        LIMIT 1
    """)).fetchone()
    if not row:
        raise HTTPException(
            status_code=400,
            detail="No active KG/KGS unit found in uom_mst for this tenant"
        )
    return int(row[0])


# ============================================================================
# SQL QUERY FUNCTIONS
# ============================================================================

def get_yarn_list_query():
    """
    Get all yarn masters for a company with item details joined.
    Authoritative name comes from item_mst.item_name.
    Falls back to jute_yarn_mst.jute_yarn_name for un-migrated rows.
    """
    return text("""
        SELECT 
            ym.jute_yarn_id,
            ym.item_id,
            COALESCE(im.item_name, ym.jute_yarn_name) AS jute_yarn_name,
            im.item_code,
            ym.jute_yarn_count,
            ym.std_mr_pct,
            ym.item_grp_id,
            ig.item_grp_name,
            ig.item_grp_code,
            ym.jute_yarn_remarks,
            ym.co_id,
            ym.updated_by,
            ym.updated_date_time
        FROM jute_yarn_mst ym
        LEFT JOIN item_mst im ON ym.item_id = im.item_id
        LEFT JOIN item_grp_mst ig ON ym.item_grp_id = ig.item_grp_id
        WHERE ym.co_id = :co_id
        ORDER BY ym.jute_yarn_id DESC
    """)


def get_yarn_list_with_search_query():
    """
    Get all yarn masters for a company with search filter.
    """
    return text("""
        SELECT 
            ym.jute_yarn_id,
            ym.item_id,
            COALESCE(im.item_name, ym.jute_yarn_name) AS jute_yarn_name,
            im.item_code,
            ym.jute_yarn_count,
            ym.std_mr_pct,
            ym.item_grp_id,
            ig.item_grp_name,
            ig.item_grp_code,
            ym.jute_yarn_remarks,
            ym.co_id,
            ym.updated_by,
            ym.updated_date_time
        FROM jute_yarn_mst ym
        LEFT JOIN item_mst im ON ym.item_id = im.item_id
        LEFT JOIN item_grp_mst ig ON ym.item_grp_id = ig.item_grp_id
        WHERE ym.co_id = :co_id
          AND (
              COALESCE(im.item_name, ym.jute_yarn_name) LIKE :search
              OR ig.item_grp_name LIKE :search
              OR ym.jute_yarn_remarks LIKE :search
              OR im.item_code LIKE :search
          )
        ORDER BY ym.jute_yarn_id DESC
    """)


def get_yarn_types_for_company():
    """
    Get all yarn types (item groups with item_type_id=4) for dropdown.
    """
    return text("""
        SELECT 
            item_grp_id,
            item_grp_name,
            item_grp_code
        FROM item_grp_mst
        WHERE co_id = :co_id
          AND item_type_id = :item_type_id
          AND parent_grp_id IS NULL
        ORDER BY item_grp_name
    """)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def _resolve_yarn_uom_id(db: Session) -> int:
    """
    Resolve the tenant's KG unit from uom_mst (uom ids differ per tenant DB,
    e.g. dev3 has KG=163 while sls only has KGS=132 — never hardcode the id).
    Prefers exact 'KG' over 'KGS'.
    """
    row = db.execute(text("""
        SELECT uom_id
        FROM uom_mst
        WHERE active = 1
          AND UPPER(REPLACE(REPLACE(uom_name, '.', ''), ' ', '')) IN ('KG', 'KGS')
        ORDER BY CASE WHEN UPPER(REPLACE(REPLACE(uom_name, '.', ''), ' ', '')) = 'KG' THEN 0 ELSE 1 END,
                 uom_id
        LIMIT 1
    """)).fetchone()
    if not row:
        raise HTTPException(
            status_code=400,
            detail="No active 'KG'/'KGS' unit found in uom_mst for this tenant. Add one in UOM Master first."
        )
    return row[0]


def _generate_item_code(jute_yarn_name: str) -> str:
    """
    Generate an item_code from the yarn name.
    Uses the yarn name directly as the item code (since it is already a
    composite like "10-SKWP-Gold").
    """
    return jute_yarn_name.strip() if jute_yarn_name else ""


def _check_item_uniqueness(db: Session, co_id: int, item_grp_id: int | None,
                           item_code: str, item_name: str,
                           exclude_item_id: int | None = None):
    """
    Check that item_code is unique within the item group and
    item_name is unique across all company groups.
    Raises HTTPException on conflict.
    """
    # Get all group IDs for this company
    groups = db.query(ItemGrpMst).filter(ItemGrpMst.co_id == co_id).all()
    group_ids = [g.item_grp_id for g in groups]

    # Check item_code uniqueness within the same item group
    if item_grp_id:
        code_query = db.query(ItemMst).filter(
            ItemMst.item_grp_id == item_grp_id,
            ItemMst.item_code == item_code
        )
        if exclude_item_id:
            code_query = code_query.filter(ItemMst.item_id != exclude_item_id)
        if code_query.first():
            raise HTTPException(
                status_code=409,
                detail=f"Item code '{item_code}' already exists in this yarn type group"
            )

    # Check item_name uniqueness across all company groups
    if group_ids:
        name_query = db.query(ItemMst).filter(
            ItemMst.item_grp_id.in_(group_ids),
            ItemMst.item_name == item_name
        )
        if exclude_item_id:
            name_query = name_query.filter(ItemMst.item_id != exclude_item_id)
        if name_query.first():
            raise HTTPException(
                status_code=409,
                detail=f"Item with name '{item_name}' already exists"
            )


# ============================================================================
# ENDPOINTS
# ============================================================================

@router.get("/get_yarn_table")
def get_yarn_table(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    search: str = None,
    page: int = 1,
    limit: int = 10,
):
    """
    Get paginated list of yarn masters for the current company.
    """
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")

        # Prepare search parameter for LIKE if provided
        search_param = f"%{search}%" if search else None

        # Choose query based on search
        if search_param:
            query = get_yarn_list_with_search_query()
            params = {"co_id": int(co_id), "search": search_param}
        else:
            query = get_yarn_list_query()
            params = {"co_id": int(co_id)}

        result = db.execute(query, params).fetchall()
        all_data = [dict(row._mapping) for row in result]

        # Calculate pagination
        total = len(all_data)
        start_idx = (page - 1) * limit
        end_idx = start_idx + limit
        paginated_data = all_data[start_idx:end_idx]

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


@router.get("/get_yarn_by_id/{yarn_id}")
def get_yarn_by_id(
    yarn_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Get a single yarn master record by ID, with item details.
    """
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")

        query = text("""
            SELECT 
                ym.jute_yarn_id,
                ym.item_id,
                COALESCE(im.item_name, ym.jute_yarn_name) AS jute_yarn_name,
                im.item_code,
                ym.jute_yarn_count,
                ym.std_mr_pct,
                ym.item_grp_id,
                ig.item_grp_name,
                ig.item_grp_code,
                ym.jute_yarn_remarks,
                ym.co_id,
                ym.updated_by,
                ym.updated_date_time
            FROM jute_yarn_mst ym
            LEFT JOIN item_mst im ON ym.item_id = im.item_id
            LEFT JOIN item_grp_mst ig ON ym.item_grp_id = ig.item_grp_id
            WHERE ym.jute_yarn_id = :yarn_id
              AND ym.co_id = :co_id
        """)

        result = db.execute(query, {"yarn_id": yarn_id, "co_id": int(co_id)}).fetchone()
        
        if not result:
            raise HTTPException(status_code=404, detail="Yarn master record not found")

        return {"data": dict(result._mapping)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/yarn_create_setup")
def yarn_create_setup(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Get setup data for creating a new yarn master record.
    Returns list of yarn types for dropdown.
    """
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")

        # Get yarn types (item groups with item_type_id=4) for dropdown
        yarn_types_result = db.execute(
            get_yarn_types_for_company(),
            {"co_id": int(co_id), "item_type_id": YARN_ITEM_TYPE_ID},
        ).fetchall()
        yarn_types = [dict(row._mapping) for row in yarn_types_result]

        return {
            "yarn_types": yarn_types
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/yarn_edit_setup/{yarn_id}")
def yarn_edit_setup(
    yarn_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Get setup data for editing a yarn master record.
    Returns the existing yarn details (with item info) and yarn types for dropdown.
    """
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")

        # Get the existing yarn record with item details
        query = text("""
            SELECT 
                ym.jute_yarn_id,
                ym.item_id,
                COALESCE(im.item_name, ym.jute_yarn_name) AS jute_yarn_name,
                im.item_code,
                ym.jute_yarn_count,
                ym.std_mr_pct,
                ym.item_grp_id,
                ig.item_grp_name,
                ig.item_grp_code,
                ym.jute_yarn_remarks,
                ym.co_id,
                ym.updated_by,
                ym.updated_date_time
            FROM jute_yarn_mst ym
            LEFT JOIN item_mst im ON ym.item_id = im.item_id
            LEFT JOIN item_grp_mst ig ON ym.item_grp_id = ig.item_grp_id
            WHERE ym.jute_yarn_id = :yarn_id
              AND ym.co_id = :co_id
        """)

        result = db.execute(query, {"yarn_id": yarn_id, "co_id": int(co_id)}).fetchone()
        
        if not result:
            raise HTTPException(status_code=404, detail="Yarn master record not found")

        # Get yarn types (item groups with item_type_id=4) for dropdown
        yarn_types_result = db.execute(
            get_yarn_types_for_company(),
            {"co_id": int(co_id), "item_type_id": YARN_ITEM_TYPE_ID},
        ).fetchall()
        yarn_types = [dict(row._mapping) for row in yarn_types_result]

        return {
            "yarn_details": dict(result._mapping),
            "yarn_types": yarn_types
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/yarn_create")
def yarn_create(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Create a new yarn master record.
    
    Flow:
    1. Validate inputs
    2. Generate item_code from jute_yarn_name
    3. Check uniqueness for item_code/item_name in item_mst
    4. Create item_mst record FIRST
    5. Create jute_yarn_mst record with item_id FK
    6. Also write jute_yarn_name and co_id for backward compat
    """
    try:
        body = parse_json_body(request)
        co_id = body.get("co_id") or request.query_params.get("co_id")
        
        if not co_id:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")

        jute_yarn_name = body.get("jute_yarn_name")
        if not jute_yarn_name:
            raise HTTPException(status_code=400, detail="Yarn name is required")

        jute_yarn_count = body.get("jute_yarn_count")
        item_grp_id = body.get("item_grp_id")
        jute_yarn_remarks = body.get("jute_yarn_remarks")
        std_mr_pct = body.get("std_mr_pct")

        # Parse item_grp_id
        parsed_grp_id = int(item_grp_id) if item_grp_id else None

        # Generate item_code from yarn name
        item_code = _generate_item_code(jute_yarn_name)
        if not item_code:
            raise HTTPException(status_code=400, detail="Could not generate item code from yarn name")

        # Check uniqueness in item_mst
        _check_item_uniqueness(
            db=db,
            co_id=int(co_id),
            item_grp_id=parsed_grp_id,
            item_code=item_code,
            item_name=jute_yarn_name,
        )

        # Get user ID from token
        user_id = token_data.get("user_id") if token_data else None
        updated_by = int(user_id) if user_id and str(user_id).isdigit() else None

        # --- Step 1: Create item_mst record ---
        new_item = ItemMst(
            active=YARN_ITEM_DEFAULTS["active"],
            updated_by=updated_by or 0,
            updated_date_time=now_ist(),
            item_grp_id=parsed_grp_id,
            item_code=item_code,
            tangible=YARN_ITEM_DEFAULTS["tangible"],
            item_name=jute_yarn_name,
            hsn_code=YARN_ITEM_DEFAULTS["hsn_code"],
            uom_id=_resolve_yarn_uom_id(db),
            tax_percentage=YARN_ITEM_DEFAULTS["tax_percentage"],
            saleable=YARN_ITEM_DEFAULTS["saleable"],
            consumable=YARN_ITEM_DEFAULTS["consumable"],
            purchaseable=YARN_ITEM_DEFAULTS["purchaseable"],
            manufacturable=YARN_ITEM_DEFAULTS["manufacturable"],
            assembly=YARN_ITEM_DEFAULTS["assembly"],
            uom_rounding=YARN_ITEM_DEFAULTS["uom_rounding"],
            rate_rounding=YARN_ITEM_DEFAULTS["rate_rounding"],
        )
        db.add(new_item)
        db.flush()  # flush to get item_id without committing

        # --- Step 2: Create jute_yarn_mst record ---
        new_yarn = JuteYarnMst(
            jute_yarn_name=jute_yarn_name,  # backward compat
            jute_yarn_count=float(jute_yarn_count) if jute_yarn_count else None,
            std_mr_pct=float(std_mr_pct) if std_mr_pct not in (None, "") else None,
            item_grp_id=parsed_grp_id,
            jute_yarn_remarks=jute_yarn_remarks,
            item_id=new_item.item_id,
            co_id=int(co_id),  # backward compat
            updated_by=updated_by,
            updated_date_time=now_ist(),
        )
        db.add(new_yarn)
        db.commit()
        db.refresh(new_yarn)

        return {
            "message": "Yarn master created successfully",
            "jute_yarn_id": new_yarn.jute_yarn_id,
            "item_id": new_item.item_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/yarn_edit/{yarn_id}")
def yarn_edit(
    yarn_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Update an existing yarn master record.
    
    Flow:
    1. Validate inputs
    2. Find existing jute_yarn_mst record
    3. If item_id exists, update item_mst (name, code, group)
    4. If item_id is missing (pre-migration row), create item_mst first
    5. Update jute_yarn_mst fields
    """
    try:
        body = parse_json_body(request)
        co_id = body.get("co_id") or request.query_params.get("co_id")
        
        if not co_id:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")

        jute_yarn_name = body.get("jute_yarn_name")
        if not jute_yarn_name:
            raise HTTPException(status_code=400, detail="Yarn name is required")

        jute_yarn_count = body.get("jute_yarn_count")
        item_grp_id = body.get("item_grp_id")
        jute_yarn_remarks = body.get("jute_yarn_remarks")
        std_mr_pct = body.get("std_mr_pct")
        parsed_grp_id = int(item_grp_id) if item_grp_id else None

        # Check record exists
        existing = db.query(JuteYarnMst).filter(
            JuteYarnMst.jute_yarn_id == yarn_id,
            JuteYarnMst.co_id == int(co_id)
        ).first()

        if not existing:
            raise HTTPException(status_code=404, detail="Yarn master record not found")

        # Generate item_code from yarn name
        item_code = _generate_item_code(jute_yarn_name)
        if not item_code:
            raise HTTPException(status_code=400, detail="Could not generate item code from yarn name")

        # Get user ID from token
        user_id = token_data.get("user_id") if token_data else None
        updated_by = int(user_id) if user_id and str(user_id).isdigit() else None

        if existing.item_id:
            # --- Existing item: update item_mst ---
            item_record = db.query(ItemMst).filter(
                ItemMst.item_id == existing.item_id
            ).first()

            if item_record:
                # Check uniqueness excluding current item
                _check_item_uniqueness(
                    db=db,
                    co_id=int(co_id),
                    item_grp_id=parsed_grp_id,
                    item_code=item_code,
                    item_name=jute_yarn_name,
                    exclude_item_id=item_record.item_id,
                )

                item_record.item_name = jute_yarn_name
                item_record.item_code = item_code
                item_record.item_grp_id = parsed_grp_id
                item_record.updated_by = updated_by or item_record.updated_by
                item_record.updated_date_time = now_ist()
        else:
            # --- Pre-migration row: no item_id yet — create item_mst ---
            _check_item_uniqueness(
                db=db,
                co_id=int(co_id),
                item_grp_id=parsed_grp_id,
                item_code=item_code,
                item_name=jute_yarn_name,
            )

            new_item = ItemMst(
                active=YARN_ITEM_DEFAULTS["active"],
                updated_by=updated_by or 0,
                updated_date_time=now_ist(),
                item_grp_id=parsed_grp_id,
                item_code=item_code,
                tangible=YARN_ITEM_DEFAULTS["tangible"],
                item_name=jute_yarn_name,
                hsn_code=YARN_ITEM_DEFAULTS["hsn_code"],
                uom_id=_resolve_yarn_uom_id(db),
                tax_percentage=YARN_ITEM_DEFAULTS["tax_percentage"],
                saleable=YARN_ITEM_DEFAULTS["saleable"],
                consumable=YARN_ITEM_DEFAULTS["consumable"],
                purchaseable=YARN_ITEM_DEFAULTS["purchaseable"],
                manufacturable=YARN_ITEM_DEFAULTS["manufacturable"],
                assembly=YARN_ITEM_DEFAULTS["assembly"],
                uom_rounding=YARN_ITEM_DEFAULTS["uom_rounding"],
                rate_rounding=YARN_ITEM_DEFAULTS["rate_rounding"],
            )
            db.add(new_item)
            db.flush()
            existing.item_id = new_item.item_id

        # --- Update jute_yarn_mst ---
        existing.jute_yarn_name = jute_yarn_name  # backward compat
        existing.jute_yarn_count = float(jute_yarn_count) if jute_yarn_count else None
        if std_mr_pct not in (None, ""):
            existing.std_mr_pct = float(std_mr_pct)
        existing.item_grp_id = parsed_grp_id
        existing.jute_yarn_remarks = jute_yarn_remarks
        existing.updated_by = updated_by
        existing.updated_date_time = now_ist()
        
        db.commit()

        return {
            "message": "Yarn master updated successfully",
            "jute_yarn_id": yarn_id,
            "item_id": existing.item_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
