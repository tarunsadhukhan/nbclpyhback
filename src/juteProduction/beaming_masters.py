"""Page A router — Beaming Quality Master (jute_prod_bm_quality).

Portal persona (Depends(get_tenant_db) + get_current_user_with_refresh), every
response wrapped in {"data": ...}, soft delete via active=0, no approval workflow,
trigger-based audit (no created_*). Mirrors the spreader_masters.py item_maturity
1:N CRUD shape. Router is mounted at prefix /api/beamingMasters in src/main.py.

Endpoints (SPEC §A.6):
  GET    /bm_quality_create_setup        -> {items, yarns}
  GET    /bm_quality_list                -> [quality rows]   (filters co_id, branch_id?, item_id?)
  POST   /bm_quality_create              -> {bm_quality_id}   (duplicate guard §A.2; std_count §A.8)
  PUT    /bm_quality_edit/{id}           -> {message}
  DELETE /bm_quality_delete/{id}         -> {message}         (soft active=0)
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.authorization.utils import get_current_user_with_refresh
from src.config.db import get_tenant_db
from src.juteProduction.beaming_query import (
    check_bm_quality_duplicate_query,
    get_beaming_cloth_items_query,
    get_beaming_yarns_query,
    get_bm_quality_components_query,
    get_bm_quality_detail_query,
    get_bm_quality_list_query,
    get_bm_quality_row_query,
    insert_bm_quality_component_query,
    insert_bm_quality_query,
    null_composite_parent_fields_query,
    soft_delete_bm_quality_components_query,
    soft_delete_bm_quality_query,
    update_bm_quality_query,
)


router = APIRouter()


# =============================================================================
# Helpers — required/optional query-param parsing (mirrors spreader_masters.py)
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


# =============================================================================
# Pydantic bodies (SPEC §A.7)
# =============================================================================


class BmQualityComponent(BaseModel):
    """One warp component of a composite beaming quality (§A.4 / §Q3).

    The real (ends, count) pair lives in jute_prod_bm_quality_dtl; yarn_item_id is the
    optional linked jute yarn that supplied the count. Composite parents carry >=2 of
    these and the parent's ends = SUM(component ends), std_count/yarn_item_id = NULL.
    """

    component_no: int
    ends: int = Field(gt=0)
    yarn_item_id: Optional[int] = None
    count: float = Field(gt=0)


class BmQualityCreate(BaseModel):
    co_id: int
    branch_id: Optional[int] = None
    item_id: int
    bm_quality_code: str
    bm_quality_name: Optional[str] = None
    # ends/std_count/yarn_item_id describe the simple (non-composite) parent; for a
    # composite quality (is_composite=1) they are derived/NULL and the real (ends,count)
    # pairs travel in `components` (>=2). Validated per-branch in bm_quality_create.
    ends: Optional[int] = Field(default=None, gt=0)
    yarn_item_id: Optional[int] = None  # linked jute yarn; std_count derived from it (§A.8)
    std_count: Optional[float] = Field(default=None, gt=0)  # may be auto-filled from jute_yarn_mst.jute_yarn_count
    is_composite: int = 0               # 1 => multi-component (components required, §A.4)
    components: Optional[list[BmQualityComponent]] = None  # required (len>=2) when is_composite=1


class BmQualityUpdate(BaseModel):
    bm_quality_code: Optional[str] = None
    bm_quality_name: Optional[str] = None
    ends: Optional[int] = Field(default=None, gt=0)
    yarn_item_id: Optional[int] = None
    std_count: Optional[float] = Field(default=None, gt=0)
    is_composite: Optional[int] = None
    active: Optional[int] = None
    components: Optional[list[BmQualityComponent]] = None  # required (len>=2) when is_composite=1


# =============================================================================
# Endpoints
# =============================================================================


@router.get("/bm_quality_create_setup")
def bm_quality_create_setup(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Dropdown sources for the create/edit dialog: jute-cloth items (type 5) and
    the jute-yarn count picker (type 4, auto-fills std_count — §A.8)."""
    co_id = _require_co_id(request)
    try:
        items = [
            dict(r._mapping)
            for r in db.execute(get_beaming_cloth_items_query(), {"co_id": co_id}).fetchall()
        ]
        yarns = [
            dict(r._mapping)
            for r in db.execute(get_beaming_yarns_query(), {"co_id": co_id}).fetchall()
        ]
        return {"data": {"items": items, "yarns": yarns}}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/bm_quality_list")
def bm_quality_list(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Active beaming-quality rows for a company (filters co_id, branch_id?, item_id?)."""
    co_id = _require_co_id(request)
    branch_id = _optional_branch_id(request)
    item_id = _optional_item_id(request)
    try:
        rows = db.execute(
            get_bm_quality_list_query(),
            {"co_id": co_id, "branch_id": branch_id, "item_id": item_id},
        ).fetchall()
        return {"data": [dict(r._mapping) for r in rows]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/bm_quality_create")
def bm_quality_create(
    body: BmQualityCreate,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Create one beaming-quality row. Duplicate guard on (co_id, item_id,
    bm_quality_code) among active=1 -> 400 (SPEC §A.2). std_count may be auto-filled
    on the FE from the selected yarn's jute_yarn_count (§A.8); the value is stored
    as a snapshot here."""
    try:
        code = body.bm_quality_code.strip()
        if not code:
            raise HTTPException(status_code=400, detail="bm_quality_code is required")

        is_composite = int(body.is_composite)

        # Branch the parent's (ends, std_count, yarn_item_id) by composite-ness (§A.4/§Q3).
        if is_composite == 1:
            components = body.components or []
            if len(components) < 2:
                raise HTTPException(
                    status_code=400,
                    detail="A composite beaming quality requires at least 2 components",
                )
            parent_ends = sum(int(c.ends) for c in components)
            parent_std_count = None
            parent_yarn_item_id = None
        else:
            if body.ends is None:
                raise HTTPException(status_code=400, detail="ends is required")
            if body.std_count is None:
                raise HTTPException(status_code=400, detail="std_count is required")
            parent_ends = int(body.ends)
            parent_std_count = float(body.std_count)
            parent_yarn_item_id = (
                int(body.yarn_item_id) if body.yarn_item_id is not None else None
            )

        dup = db.execute(
            check_bm_quality_duplicate_query(),
            {
                "co_id": body.co_id,
                "item_id": int(body.item_id),
                "bm_quality_code": code,
                "exclude_id": None,
            },
        ).fetchone()
        if dup:
            raise HTTPException(
                status_code=400,
                detail="A beaming quality with this code already exists for this item",
            )

        result = db.execute(
            insert_bm_quality_query(),
            {
                "co_id": body.co_id,
                "branch_id": body.branch_id,
                "item_id": int(body.item_id),
                "bm_quality_code": code,
                "bm_quality_name": body.bm_quality_name,
                "ends": parent_ends,
                "std_count": parent_std_count,
                "yarn_item_id": parent_yarn_item_id,
                "is_composite": is_composite,
                "updated_by": token_data.get("user_id"),
            },
        )
        new_id = result.lastrowid

        if is_composite == 1:
            for comp in body.components:
                db.execute(
                    insert_bm_quality_component_query(),
                    {
                        "bm_quality_id": new_id,
                        "component_no": int(comp.component_no),
                        "ends": int(comp.ends),
                        "yarn_item_id": (
                            int(comp.yarn_item_id) if comp.yarn_item_id is not None else None
                        ),
                        "count": float(comp.count),
                    },
                )

        db.commit()
        return {"data": {"bm_quality_id": new_id}}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/bm_quality_edit/{bm_quality_id}")
def bm_quality_edit(
    bm_quality_id: int,
    body: BmQualityUpdate,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Patch update one beaming-quality row (co_id-scoped). Re-checks the
    (co_id, item_id, bm_quality_code) duplicate guard when the code changes."""
    co_id = _require_co_id(request)
    try:
        existing = db.execute(
            get_bm_quality_row_query(),
            {"bm_quality_id": bm_quality_id},
        ).fetchone()
        if not existing or existing._mapping["co_id"] != co_id:
            raise HTTPException(status_code=404, detail="Beaming quality not found")

        new_code = body.bm_quality_code.strip() if body.bm_quality_code is not None else None
        if body.bm_quality_code is not None and not new_code:
            raise HTTPException(status_code=400, detail="bm_quality_code cannot be blank")

        if new_code is not None and new_code != existing._mapping["bm_quality_code"]:
            dup = db.execute(
                check_bm_quality_duplicate_query(),
                {
                    "co_id": co_id,
                    "item_id": existing._mapping["item_id"],
                    "bm_quality_code": new_code,
                    "exclude_id": bm_quality_id,
                },
            ).fetchone()
            if dup:
                raise HTTPException(
                    status_code=400,
                    detail="A beaming quality with this code already exists for this item",
                )

        # Resolve the effective composite-ness: explicit body value wins, else keep existing.
        effective_composite = (
            int(body.is_composite)
            if body.is_composite is not None
            else int(existing._mapping["is_composite"])
        )

        # Composite branch: parent ends = SUM(component ends); std_count/yarn_item_id NULL;
        # replace the component set (soft-delete old, re-insert) — §Q3.
        if effective_composite == 1:
            components = body.components or []
            if len(components) < 2:
                raise HTTPException(
                    status_code=400,
                    detail="A composite beaming quality requires at least 2 components",
                )
            parent_ends = sum(int(c.ends) for c in components)
            parent_std_count = None
            parent_yarn_item_id = None
        else:
            parent_ends = int(body.ends) if body.ends is not None else None
            parent_std_count = float(body.std_count) if body.std_count is not None else None
            parent_yarn_item_id = (
                int(body.yarn_item_id) if body.yarn_item_id is not None else None
            )

        if effective_composite == 1:
            db.execute(
                update_bm_quality_query(),
                {
                    "bm_quality_id": bm_quality_id,
                    "bm_quality_code": new_code,
                    "bm_quality_name": body.bm_quality_name,
                    "ends": parent_ends,
                    "std_count": parent_std_count,
                    "yarn_item_id": parent_yarn_item_id,
                    "is_composite": 1,
                    "active": int(body.active) if body.active is not None else None,
                    "updated_by": token_data.get("user_id"),
                },
            )
            # update_bm_quality_query COALESCEs std_count/yarn_item_id (can't NULL them) —
            # set them explicitly so the composite parent ends up NULL on both.
            db.execute(
                null_composite_parent_fields_query(),
                {"bm_quality_id": bm_quality_id},
            )
            db.execute(
                soft_delete_bm_quality_components_query(),
                {"bm_quality_id": bm_quality_id},
            )
            for comp in components:
                db.execute(
                    insert_bm_quality_component_query(),
                    {
                        "bm_quality_id": bm_quality_id,
                        "component_no": int(comp.component_no),
                        "ends": int(comp.ends),
                        "yarn_item_id": (
                            int(comp.yarn_item_id) if comp.yarn_item_id is not None else None
                        ),
                        "count": float(comp.count),
                    },
                )
        else:
            db.execute(
                update_bm_quality_query(),
                {
                    "bm_quality_id": bm_quality_id,
                    "bm_quality_code": new_code,
                    "bm_quality_name": body.bm_quality_name,
                    "ends": parent_ends,
                    "std_count": parent_std_count,
                    "yarn_item_id": parent_yarn_item_id,
                    "is_composite": (
                        int(body.is_composite) if body.is_composite is not None else None
                    ),
                    "active": int(body.active) if body.active is not None else None,
                    "updated_by": token_data.get("user_id"),
                },
            )
            # If switching from composite -> simple, drop any leftover component rows.
            if body.is_composite is not None and int(existing._mapping["is_composite"]) == 1:
                db.execute(
                    soft_delete_bm_quality_components_query(),
                    {"bm_quality_id": bm_quality_id},
                )

        db.commit()
        return {"data": {"message": "Updated"}}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/bm_quality_detail/{bm_quality_id}")
def bm_quality_detail(
    bm_quality_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """One beaming-quality parent row plus its components for the edit dialog (§Q3).

    co_id-scoped (404 if missing or owned by another company). ``components`` is the
    active jute_prod_bm_quality_dtl set ordered by component_no — empty for a simple
    (non-composite) quality, >=2 rows for a composite one.
    """
    co_id = _require_co_id(request)
    try:
        parent = db.execute(
            get_bm_quality_detail_query(),
            {"bm_quality_id": bm_quality_id, "co_id": co_id},
        ).fetchone()
        if not parent:
            raise HTTPException(status_code=404, detail="Beaming quality not found")

        components = [
            dict(r._mapping)
            for r in db.execute(
                get_bm_quality_components_query(),
                {"bm_quality_id": bm_quality_id},
            ).fetchall()
        ]

        data = dict(parent._mapping)
        data["components"] = components
        return {"data": data}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/bm_quality_delete/{bm_quality_id}")
def bm_quality_delete(
    bm_quality_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Soft-delete (active=0) one beaming-quality row (co_id-scoped)."""
    co_id = _require_co_id(request)
    try:
        existing = db.execute(
            get_bm_quality_row_query(),
            {"bm_quality_id": bm_quality_id},
        ).fetchone()
        if not existing or existing._mapping["co_id"] != co_id:
            raise HTTPException(status_code=404, detail="Beaming quality not found")

        db.execute(
            soft_delete_bm_quality_query(),
            {"bm_quality_id": bm_quality_id, "updated_by": token_data.get("user_id")},
        )
        db.commit()
        return {"data": {"message": "Deleted"}}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
