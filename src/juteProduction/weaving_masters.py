"""Page A router — Weaving Quality Master (jute_prod_weaving_quality).

Portal persona (Depends(get_tenant_db) + get_current_user_with_refresh), every
response wrapped in {"data": ...}, soft delete via active=0, no approval workflow,
trigger-based audit (no created_*). Mirrors beaming_masters.py (bm/beaming token
renamed to weaving) — the composite-warp 1:N CRUD shape via jute_prod_weaving_quality_dtl.
Router is mounted at prefix /api/weavingMasters in src/main.py (registered in a later step).

Endpoints:
  GET    /weaving_quality_setup            -> {items, yarns}
  GET    /weaving_quality_list             -> [quality rows]   (filters co_id, branch_id?, item_id?, search?)
  POST   /weaving_quality_create           -> {weaving_quality_id} (duplicate guard; optional composite _dtl rows)
  PUT    /weaving_quality_edit/{id}         -> {message}
  DELETE /weaving_quality_delete/{id}       -> {message}        (soft active=0)
  GET    /weaving_quality_detail/{id}       -> {parent + components} (edit dialog)
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.authorization.utils import get_current_user_with_refresh
from src.config.db import get_tenant_db
from src.juteProduction.weaving_query import (
    check_weaving_quality_duplicate_query,
    get_weaving_cloth_items_query,
    get_weaving_quality_components_query,
    get_weaving_quality_detail_query,
    get_weaving_quality_list_query,
    get_weaving_quality_row_query,
    get_weaving_yarns_query,
    insert_weaving_quality_component_query,
    insert_weaving_quality_query,
    soft_delete_weaving_quality_components_query,
    soft_delete_weaving_quality_query,
    update_weaving_quality_query,
)


router = APIRouter()


# =============================================================================
# Helpers — required/optional query-param parsing (mirrors beaming_masters.py)
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
# Pydantic bodies
# =============================================================================


class WeavingQualityComponent(BaseModel):
    """One warp component of a composite weaving quality (mirror beaming, Q6).

    The real (ends, count) pair lives in jute_prod_weaving_quality_dtl; yarn_item_id is
    the optional linked jute yarn that supplied the count. Composite parents carry >=2 of
    these and the parent's ends = SUM(component ends), yarn_item_id = NULL.
    """

    component_no: int
    ends: int = Field(gt=0)
    yarn_item_id: Optional[int] = None
    count: float = Field(gt=0)


class WeavingQualityCreate(BaseModel):
    co_id: int
    branch_id: Optional[int] = None
    item_id: int
    weaving_quality_code: str
    weaving_quality_name: Optional[str] = None
    # Construction attrs (jute_prod_weaving_quality). For a composite quality
    # (is_composite=1), `ends` is derived as SUM(component ends) and the real
    # (ends,count) pairs travel in `components` (>=2).
    ends: Optional[int] = Field(default=None, gt=0)
    finished_length: float = Field(gt=0)  # yds/cut
    ozs_yds: float = Field(gt=0)  # ACTUAL oz/yd -> production_kg
    std_ozs_yds: Optional[float] = Field(default=None, gt=0)  # STANDARD oz/yd -> std_prod_kg
    no_of_jugar_per_cut: float = Field(gt=0)  # mandatory, >0 (jugar->yards divisor)
    width: Optional[float] = None
    ports: Optional[float] = None
    reed_porter: Optional[float] = None
    shrinkage_pct: Optional[float] = None
    shots: Optional[float] = None
    mc_teeth: Optional[int] = None
    jbo_rbo: Optional[str] = None
    reed_space: Optional[float] = None
    tpi: Optional[float] = None
    yarn_count: Optional[str] = None
    is_composite: int = 0  # 1 => multi-component (components required)
    components: Optional[list[WeavingQualityComponent]] = None  # required (len>=2) when is_composite=1


class WeavingQualityUpdate(BaseModel):
    weaving_quality_code: Optional[str] = None
    weaving_quality_name: Optional[str] = None
    ends: Optional[int] = Field(default=None, gt=0)
    finished_length: Optional[float] = Field(default=None, gt=0)
    ozs_yds: Optional[float] = Field(default=None, gt=0)
    std_ozs_yds: Optional[float] = Field(default=None, gt=0)
    no_of_jugar_per_cut: Optional[float] = Field(default=None, gt=0)
    width: Optional[float] = None
    ports: Optional[float] = None
    reed_porter: Optional[float] = None
    shrinkage_pct: Optional[float] = None
    shots: Optional[float] = None
    mc_teeth: Optional[int] = None
    jbo_rbo: Optional[str] = None
    reed_space: Optional[float] = None
    tpi: Optional[float] = None
    yarn_count: Optional[str] = None
    is_composite: Optional[int] = None
    active: Optional[int] = None
    components: Optional[list[WeavingQualityComponent]] = None  # required (len>=2) when is_composite=1


# =============================================================================
# Endpoints
# =============================================================================


@router.get("/weaving_quality_setup")
def weaving_quality_setup(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Dropdown sources for the create/edit dialog: woven-cloth items (item_type 5) and
    the jute-yarn count picker (item_type 4) for composite-warp components."""
    co_id = _require_co_id(request)
    try:
        items = [
            dict(r._mapping)
            for r in db.execute(get_weaving_cloth_items_query(), {"co_id": co_id}).fetchall()
        ]
        yarns = [
            dict(r._mapping)
            for r in db.execute(get_weaving_yarns_query(), {"co_id": co_id}).fetchall()
        ]
        return {"data": {"items": items, "yarns": yarns}}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/weaving_quality_list")
def weaving_quality_list(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Active weaving-quality rows for a company (filters co_id, branch_id?, item_id?, search?)."""
    co_id = _require_co_id(request)
    branch_id = _optional_branch_id(request)
    item_id = _optional_item_id(request)
    search_raw = request.query_params.get("search")
    search = f"%{search_raw}%" if search_raw else None
    try:
        rows = db.execute(
            get_weaving_quality_list_query(),
            {"co_id": co_id, "branch_id": branch_id, "item_id": item_id, "search": search},
        ).fetchall()
        return {"data": [dict(r._mapping) for r in rows]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/weaving_quality_create")
def weaving_quality_create(
    body: WeavingQualityCreate,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Create one weaving-quality row. Duplicate guard on (co_id, item_id,
    weaving_quality_code) among active=1 -> 400. Optional composite _dtl rows: when
    is_composite=1, >=2 components are required and parent ends = SUM(component ends)."""
    try:
        code = body.weaving_quality_code.strip()
        if not code:
            raise HTTPException(status_code=400, detail="weaving_quality_code is required")

        is_composite = int(body.is_composite)

        # Branch the parent's ends by composite-ness.
        if is_composite == 1:
            components = body.components or []
            if len(components) < 2:
                raise HTTPException(
                    status_code=400,
                    detail="A composite weaving quality requires at least 2 components",
                )
            parent_ends = sum(int(c.ends) for c in components)
        else:
            if body.ends is None:
                raise HTTPException(status_code=400, detail="ends is required")
            parent_ends = int(body.ends)

        dup = db.execute(
            check_weaving_quality_duplicate_query(),
            {
                "co_id": body.co_id,
                "item_id": int(body.item_id),
                "weaving_quality_code": code,
                "exclude_id": None,
            },
        ).fetchone()
        if dup:
            raise HTTPException(
                status_code=400,
                detail="A weaving quality with this code already exists for this item",
            )

        result = db.execute(
            insert_weaving_quality_query(),
            {
                "co_id": body.co_id,
                "branch_id": body.branch_id,
                "item_id": int(body.item_id),
                "weaving_quality_code": code,
                "weaving_quality_name": body.weaving_quality_name,
                "ends": parent_ends,
                "finished_length": float(body.finished_length),
                "ozs_yds": float(body.ozs_yds),
                "std_ozs_yds": float(body.std_ozs_yds) if body.std_ozs_yds is not None else None,
                "no_of_jugar_per_cut": float(body.no_of_jugar_per_cut),
                "width": float(body.width) if body.width is not None else None,
                "ports": float(body.ports) if body.ports is not None else None,
                "reed_porter": float(body.reed_porter) if body.reed_porter is not None else None,
                "shrinkage_pct": float(body.shrinkage_pct) if body.shrinkage_pct is not None else None,
                "shots": float(body.shots) if body.shots is not None else None,
                "mc_teeth": int(body.mc_teeth) if body.mc_teeth is not None else None,
                "jbo_rbo": body.jbo_rbo,
                "reed_space": float(body.reed_space) if body.reed_space is not None else None,
                "tpi": float(body.tpi) if body.tpi is not None else None,
                "yarn_count": body.yarn_count,
                "is_composite": is_composite,
                "updated_by": token_data.get("user_id"),
            },
        )
        new_id = result.lastrowid

        if is_composite == 1:
            for comp in body.components:
                db.execute(
                    insert_weaving_quality_component_query(),
                    {
                        "weaving_quality_id": new_id,
                        "component_no": int(comp.component_no),
                        "ends": int(comp.ends),
                        "yarn_item_id": (
                            int(comp.yarn_item_id) if comp.yarn_item_id is not None else None
                        ),
                        "count": float(comp.count),
                    },
                )

        db.commit()
        return {"data": {"weaving_quality_id": new_id}}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/weaving_quality_edit/{weaving_quality_id}")
def weaving_quality_edit(
    weaving_quality_id: int,
    body: WeavingQualityUpdate,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Patch update one weaving-quality row (co_id-scoped). Re-checks the
    (co_id, item_id, weaving_quality_code) duplicate guard when the code changes."""
    co_id = _require_co_id(request)
    try:
        existing = db.execute(
            get_weaving_quality_row_query(),
            {"weaving_quality_id": weaving_quality_id},
        ).fetchone()
        if not existing or existing._mapping["co_id"] != co_id:
            raise HTTPException(status_code=404, detail="Weaving quality not found")

        new_code = (
            body.weaving_quality_code.strip() if body.weaving_quality_code is not None else None
        )
        if body.weaving_quality_code is not None and not new_code:
            raise HTTPException(status_code=400, detail="weaving_quality_code cannot be blank")

        if new_code is not None and new_code != existing._mapping["weaving_quality_code"]:
            dup = db.execute(
                check_weaving_quality_duplicate_query(),
                {
                    "co_id": co_id,
                    "item_id": existing._mapping["item_id"],
                    "weaving_quality_code": new_code,
                    "exclude_id": weaving_quality_id,
                },
            ).fetchone()
            if dup:
                raise HTTPException(
                    status_code=400,
                    detail="A weaving quality with this code already exists for this item",
                )

        # Resolve the effective composite-ness: explicit body value wins, else keep existing.
        effective_composite = (
            int(body.is_composite)
            if body.is_composite is not None
            else int(existing._mapping["is_composite"])
        )

        # Composite branch: parent ends = SUM(component ends); replace component set.
        if effective_composite == 1:
            components = body.components or []
            if len(components) < 2:
                raise HTTPException(
                    status_code=400,
                    detail="A composite weaving quality requires at least 2 components",
                )
            parent_ends = sum(int(c.ends) for c in components)
        else:
            parent_ends = int(body.ends) if body.ends is not None else None

        db.execute(
            update_weaving_quality_query(),
            {
                "weaving_quality_id": weaving_quality_id,
                "weaving_quality_code": new_code,
                "weaving_quality_name": body.weaving_quality_name,
                "ends": parent_ends,
                "finished_length": (
                    float(body.finished_length) if body.finished_length is not None else None
                ),
                "ozs_yds": float(body.ozs_yds) if body.ozs_yds is not None else None,
                "std_ozs_yds": float(body.std_ozs_yds) if body.std_ozs_yds is not None else None,
                "no_of_jugar_per_cut": (
                    float(body.no_of_jugar_per_cut)
                    if body.no_of_jugar_per_cut is not None
                    else None
                ),
                "width": float(body.width) if body.width is not None else None,
                "ports": float(body.ports) if body.ports is not None else None,
                "reed_porter": float(body.reed_porter) if body.reed_porter is not None else None,
                "shrinkage_pct": (
                    float(body.shrinkage_pct) if body.shrinkage_pct is not None else None
                ),
                "shots": float(body.shots) if body.shots is not None else None,
                "mc_teeth": int(body.mc_teeth) if body.mc_teeth is not None else None,
                "jbo_rbo": body.jbo_rbo,
                "reed_space": float(body.reed_space) if body.reed_space is not None else None,
                "tpi": float(body.tpi) if body.tpi is not None else None,
                "yarn_count": body.yarn_count,
                "is_composite": (
                    int(body.is_composite) if body.is_composite is not None else None
                ),
                "active": int(body.active) if body.active is not None else None,
                "updated_by": token_data.get("user_id"),
            },
        )

        if effective_composite == 1:
            # Replace the component set (soft-delete old, re-insert).
            db.execute(
                soft_delete_weaving_quality_components_query(),
                {"weaving_quality_id": weaving_quality_id},
            )
            for comp in components:
                db.execute(
                    insert_weaving_quality_component_query(),
                    {
                        "weaving_quality_id": weaving_quality_id,
                        "component_no": int(comp.component_no),
                        "ends": int(comp.ends),
                        "yarn_item_id": (
                            int(comp.yarn_item_id) if comp.yarn_item_id is not None else None
                        ),
                        "count": float(comp.count),
                    },
                )
        else:
            # If switching from composite -> simple, drop any leftover component rows.
            if body.is_composite is not None and int(existing._mapping["is_composite"]) == 1:
                db.execute(
                    soft_delete_weaving_quality_components_query(),
                    {"weaving_quality_id": weaving_quality_id},
                )

        db.commit()
        return {"data": {"message": "Updated"}}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/weaving_quality_detail/{weaving_quality_id}")
def weaving_quality_detail(
    weaving_quality_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """One weaving-quality parent row plus its components for the edit dialog (Q6).

    co_id-scoped (404 if missing or owned by another company). ``components`` is the
    active jute_prod_weaving_quality_dtl set ordered by component_no — empty for a simple
    (non-composite) quality, >=2 rows for a composite one.
    """
    co_id = _require_co_id(request)
    try:
        parent = db.execute(
            get_weaving_quality_detail_query(),
            {"weaving_quality_id": weaving_quality_id, "co_id": co_id},
        ).fetchone()
        if not parent:
            raise HTTPException(status_code=404, detail="Weaving quality not found")

        components = [
            dict(r._mapping)
            for r in db.execute(
                get_weaving_quality_components_query(),
                {"weaving_quality_id": weaving_quality_id},
            ).fetchall()
        ]

        data = dict(parent._mapping)
        data["components"] = components
        return {"data": data}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/weaving_quality_delete/{weaving_quality_id}")
def weaving_quality_delete(
    weaving_quality_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Soft-delete (active=0) one weaving-quality row (co_id-scoped)."""
    co_id = _require_co_id(request)
    try:
        existing = db.execute(
            get_weaving_quality_row_query(),
            {"weaving_quality_id": weaving_quality_id},
        ).fetchone()
        if not existing or existing._mapping["co_id"] != co_id:
            raise HTTPException(status_code=404, detail="Weaving quality not found")

        db.execute(
            soft_delete_weaving_quality_query(),
            {"weaving_quality_id": weaving_quality_id, "updated_by": token_data.get("user_id")},
        )
        db.commit()
        return {"data": {"message": "Deleted"}}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
