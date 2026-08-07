"""Finishing Quality Master router (jute_prod_finishing_quality).

Portal persona (Depends(get_tenant_db) + get_current_user_with_refresh), every response
wrapped in {"data": ...}, soft delete via active=0, no approval workflow, trigger-based
audit (no created_*). Mirrors beaming_masters.py shape. Router is mounted at prefix
/api/finishingMasters in src/main.py.

The ITEM is the identity: exactly one active row per (co_id, item_id, quality_type), with
quality_type=1 -> Hessian and quality_type=2 -> Sacking (DISPLAY labels only; the stored
value stays INT 1/2). The separate quality code/name and all structural params are gone;
three OPTIONAL params attach directly to the item: packsheet_wt (kg), std_bale_weight (kg),
no_of_bags (pcs) — all nullable, never required.

Endpoints:
  GET    /quality_setup                 -> {items}
  GET    /quality_list                  -> [quality rows]   (filters co_id, quality_type?, item_id?, branch_id?)
  GET    /quality_detail/{id}           -> one quality (item label + 3 params)
  POST   /quality_create                -> {finishing_quality_id}   (duplicate guard on co_id,quality_type,item_id)
  PUT    /quality_edit/{id}             -> {message}
  DELETE /quality_delete/{id}           -> {message}         (soft active=0)
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.authorization.utils import get_current_user_with_refresh
from src.config.db import get_tenant_db
from src.juteProduction.constants import (
    FINISHING_ITEM_TYPE_ID,
    FINISHING_QUALITY_TYPE_BAG,
    FINISHING_QUALITY_TYPE_CLOTH,
)
from src.juteProduction.finishing_query import (
    check_finishing_quality_duplicate_query,
    get_finishing_items_query,
    get_finishing_quality_detail_query,
    get_finishing_quality_list_query,
    get_finishing_quality_row_query,
    insert_finishing_quality_query,
    soft_delete_finishing_quality_query,
    update_finishing_quality_query,
)


router = APIRouter()

QUALITY_NOT_FOUND_MSG = "Finishing quality not found"


# =============================================================================
# Helpers
# =============================================================================


def _require_co_id(request: Request) -> int:
    raw = request.query_params.get("co_id")
    if not raw:
        raise HTTPException(status_code=400, detail="co_id is required")
    try:
        return int(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid co_id")


def _optional_branch_id(request: Request) -> Optional[int]:
    raw = request.query_params.get("branch_id")
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid branch_id")


def _optional_item_id(request: Request) -> Optional[int]:
    raw = request.query_params.get("item_id")
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid item_id")


def _optional_quality_type(request: Request) -> Optional[int]:
    raw = request.query_params.get("quality_type")
    if not raw:
        return None
    try:
        qt = int(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid quality_type")
    if qt not in (FINISHING_QUALITY_TYPE_CLOTH, FINISHING_QUALITY_TYPE_BAG):
        raise HTTPException(status_code=400, detail="Invalid quality_type")
    return qt


def _f(v):
    return None if v is None else float(v)


# =============================================================================
# Pydantic bodies
# =============================================================================


class FinishingQualityCreate(BaseModel):
    co_id: int
    branch_id: Optional[int] = None
    quality_type: int = Field(description="1=hessian, 2=sacking")
    item_id: int
    packsheet_wt: Optional[float] = None      # kg
    std_bale_weight: Optional[float] = None   # kg
    no_of_bags: Optional[int] = None          # pcs


class FinishingQualityUpdate(BaseModel):
    item_id: Optional[int] = None
    packsheet_wt: Optional[float] = None      # kg
    std_bale_weight: Optional[float] = None   # kg
    no_of_bags: Optional[int] = None          # pcs
    active: Optional[int] = None


# =============================================================================
# Endpoints
# =============================================================================


@router.get("/quality_setup")
def quality_setup(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Dropdown source for the create/edit dialog: finished items (the item is the
    quality identity)."""
    co_id = _require_co_id(request)
    try:
        items = [
            dict(r._mapping)
            for r in db.execute(
                get_finishing_items_query(),
                {"co_id": co_id, "item_grp_id": None, "item_type_id": FINISHING_ITEM_TYPE_ID},
            ).fetchall()
        ]
        return {"data": {"items": items}}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/quality_list")
def quality_list(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Active finishing-quality rows (filters co_id, quality_type?, item_id?, branch_id?)."""
    co_id = _require_co_id(request)
    branch_id = _optional_branch_id(request)
    item_id = _optional_item_id(request)
    quality_type = _optional_quality_type(request)
    try:
        rows = db.execute(
            get_finishing_quality_list_query(),
            {
                "co_id": co_id,
                "branch_id": branch_id,
                "item_id": item_id,
                "quality_type": quality_type,
            },
        ).fetchall()
        return {"data": [dict(r._mapping) for r in rows]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/quality_detail/{finishing_quality_id}")
def quality_detail(
    finishing_quality_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """One finishing-quality row (full columns), co_id-scoped (404 if missing/foreign)."""
    co_id = _require_co_id(request)
    try:
        row = db.execute(
            get_finishing_quality_detail_query(),
            {"finishing_quality_id": finishing_quality_id, "co_id": co_id},
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=QUALITY_NOT_FOUND_MSG)
        return {"data": dict(row._mapping)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/quality_create")
def quality_create(
    body: FinishingQualityCreate,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Create one finishing-quality row. Duplicate guard on
    (co_id, quality_type, item_id) among active=1 -> 400. The item is the identity;
    the three params (packsheet_wt / std_bale_weight / no_of_bags) are all optional."""
    try:
        quality_type = int(body.quality_type)
        if quality_type not in (FINISHING_QUALITY_TYPE_CLOTH, FINISHING_QUALITY_TYPE_BAG):
            raise HTTPException(status_code=400, detail="Invalid quality_type (1=hessian, 2=sacking)")

        dup = db.execute(
            check_finishing_quality_duplicate_query(),
            {
                "co_id": body.co_id,
                "quality_type": quality_type,
                "item_id": int(body.item_id),
                "exclude_id": None,
            },
        ).fetchone()
        if dup:
            raise HTTPException(
                status_code=400,
                detail="A finishing quality for this item and type already exists",
            )

        result = db.execute(
            insert_finishing_quality_query(),
            {
                "co_id": body.co_id,
                "branch_id": body.branch_id,
                "quality_type": quality_type,
                "item_id": int(body.item_id),
                "packsheet_wt": _f(body.packsheet_wt),
                "std_bale_weight": _f(body.std_bale_weight),
                "no_of_bags": int(body.no_of_bags) if body.no_of_bags is not None else None,
                "updated_by": token_data.get("user_id"),
            },
        )
        db.commit()
        return {"data": {"finishing_quality_id": result.lastrowid}}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/quality_edit/{finishing_quality_id}")
def quality_edit(
    finishing_quality_id: int,
    body: FinishingQualityUpdate,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Patch update one finishing-quality row (co_id-scoped). Re-checks the
    (co_id, quality_type, item_id) duplicate guard when item_id changes."""
    co_id = _require_co_id(request)
    try:
        existing = db.execute(
            get_finishing_quality_row_query(),
            {"finishing_quality_id": finishing_quality_id},
        ).fetchone()
        if not existing or existing._mapping["co_id"] != co_id:
            raise HTTPException(status_code=404, detail=QUALITY_NOT_FOUND_MSG)

        new_item_id = int(body.item_id) if body.item_id is not None else None
        if new_item_id is not None and new_item_id != existing._mapping["item_id"]:
            dup = db.execute(
                check_finishing_quality_duplicate_query(),
                {
                    "co_id": co_id,
                    "quality_type": existing._mapping["quality_type"],
                    "item_id": new_item_id,
                    "exclude_id": finishing_quality_id,
                },
            ).fetchone()
            if dup:
                raise HTTPException(
                    status_code=400,
                    detail="A finishing quality for this item and type already exists",
                )

        db.execute(
            update_finishing_quality_query(),
            {
                "finishing_quality_id": finishing_quality_id,
                "item_id": new_item_id,
                "packsheet_wt": _f(body.packsheet_wt),
                "std_bale_weight": _f(body.std_bale_weight),
                "no_of_bags": int(body.no_of_bags) if body.no_of_bags is not None else None,
                "active": int(body.active) if body.active is not None else None,
                "updated_by": token_data.get("user_id"),
            },
        )
        db.commit()
        return {"data": {"message": "Updated"}}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/quality_delete/{finishing_quality_id}")
def quality_delete(
    finishing_quality_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Soft-delete (active=0) one finishing-quality row (co_id-scoped)."""
    co_id = _require_co_id(request)
    try:
        existing = db.execute(
            get_finishing_quality_row_query(),
            {"finishing_quality_id": finishing_quality_id},
        ).fetchone()
        if not existing or existing._mapping["co_id"] != co_id:
            raise HTTPException(status_code=404, detail=QUALITY_NOT_FOUND_MSG)

        db.execute(
            soft_delete_finishing_quality_query(),
            {
                "finishing_quality_id": finishing_quality_id,
                "updated_by": token_data.get("user_id"),
            },
        )
        db.commit()
        return {"data": {"message": "Deleted"}}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
