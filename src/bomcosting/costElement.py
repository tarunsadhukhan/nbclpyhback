from fastapi import Depends, Request, HTTPException, APIRouter, Response
from sqlalchemy.orm import Session
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.masters.models import CostElementMst
from src.bomcosting.query import (
    get_cost_element_tree_query,
    get_cost_element_flat_list_query,
    get_cost_element_template_query,
    get_cost_element_descendant_ids_query,
)
from src.common.utils import now_ist

router = APIRouter()


def build_cost_element_tree(rows):
    """Build nested tree from flat list of cost element rows."""
    nodes = {}
    for r in rows:
        nodes[r["cost_element_id"]] = {**r, "children": []}
    roots = []
    for node in nodes.values():
        pid = node["parent_element_id"]
        if pid is None or pid not in nodes:
            roots.append(node)
        else:
            nodes[pid]["children"].append(node)
    return roots


@router.get("/cost_element_tree")
def cost_element_tree(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        result = db.execute(
            get_cost_element_tree_query(), {"co_id": int(co_id)}
        ).fetchall()
        flat = [dict(r._mapping) for r in result]
        tree = build_cost_element_tree(flat)
        return {"data": tree}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/cost_element_list")
def cost_element_list(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        search = request.query_params.get("search")
        search_param = f"%{search}%" if search else None

        result = db.execute(
            get_cost_element_flat_list_query(),
            {"co_id": int(co_id), "search": search_param},
        ).fetchall()
        data = [dict(r._mapping) for r in result]
        return {"data": data}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cost_element_create")
def cost_element_create(
    payload: dict,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = payload.get("co_id")
        element_code = payload.get("element_code")
        element_name = payload.get("element_name")
        element_type = payload.get("element_type")

        if not co_id or not element_code or not element_name or not element_type:
            raise HTTPException(
                status_code=400,
                detail="co_id, element_code, element_name, and element_type are required",
            )

        parent_element_id = payload.get("parent_element_id")
        element_level = 0

        if parent_element_id:
            parent = (
                db.query(CostElementMst)
                .filter_by(
                    cost_element_id=int(parent_element_id),
                    co_id=int(co_id),
                    active=1,
                )
                .first()
            )
            if not parent:
                raise HTTPException(status_code=404, detail="Parent element not found")
            element_level = parent.element_level + 1

        user_id = token_data.get("user_id", 0)

        new_element = CostElementMst(
            element_code=element_code,
            element_name=element_name,
            parent_element_id=int(parent_element_id) if parent_element_id else None,
            element_level=element_level,
            element_type=element_type,
            default_basis=payload.get("default_basis"),
            is_leaf=int(payload.get("is_leaf", 1)),
            sort_order=int(payload.get("sort_order", 0)),
            element_desc=payload.get("element_desc"),
            co_id=int(co_id),
            active=1,
            updated_by=int(user_id),
            updated_date_time=now_ist(),
        )
        db.add(new_element)
        db.commit()
        db.refresh(new_element)

        response.status_code = 201
        return {
            "message": "Cost element created successfully",
            "cost_element_id": new_element.cost_element_id,
        }

    except HTTPException:
        raise
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cost_element_update")
def cost_element_update(
    payload: dict,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        cost_element_id = payload.get("cost_element_id")
        co_id = payload.get("co_id")
        if not cost_element_id or not co_id:
            raise HTTPException(
                status_code=400, detail="cost_element_id and co_id are required"
            )

        element = (
            db.query(CostElementMst)
            .filter_by(
                cost_element_id=int(cost_element_id), co_id=int(co_id), active=1
            )
            .first()
        )
        if not element:
            raise HTTPException(status_code=404, detail="Cost element not found")

        if "element_name" in payload:
            element.element_name = payload["element_name"]
        if "element_desc" in payload:
            element.element_desc = payload["element_desc"]
        if "default_basis" in payload:
            element.default_basis = payload["default_basis"]
        if "sort_order" in payload:
            element.sort_order = int(payload["sort_order"])
        if "is_leaf" in payload:
            element.is_leaf = int(payload["is_leaf"])

        element.updated_by = int(token_data.get("user_id", 0))
        element.updated_date_time = now_ist()
        db.commit()
        return {"message": "Cost element updated successfully"}

    except HTTPException:
        raise
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cost_element_toggle_active")
def cost_element_toggle_active(
    payload: dict,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        cost_element_id = payload.get("cost_element_id")
        co_id = payload.get("co_id")
        if not cost_element_id or not co_id:
            raise HTTPException(
                status_code=400, detail="cost_element_id and co_id are required"
            )

        element = (
            db.query(CostElementMst)
            .filter_by(cost_element_id=int(cost_element_id), co_id=int(co_id))
            .first()
        )
        if not element:
            raise HTTPException(status_code=404, detail="Cost element not found")

        new_active = 0 if element.active == 1 else 1
        user_id = int(token_data.get("user_id", 0))

        element.active = new_active
        element.updated_by = user_id
        element.updated_date_time = now_ist()

        # Cascade deactivation to descendants
        if new_active == 0:
            desc_rows = db.execute(
                get_cost_element_descendant_ids_query(),
                {"cost_element_id": int(cost_element_id), "co_id": int(co_id)},
            ).fetchall()
            desc_ids = [r._mapping["cost_element_id"] for r in desc_rows]
            if desc_ids:
                db.query(CostElementMst).filter(
                    CostElementMst.cost_element_id.in_(desc_ids),
                    CostElementMst.co_id == int(co_id),
                ).update(
                    {"active": 0, "updated_by": user_id, "updated_date_time": now_ist()},
                    synchronize_session="fetch",
                )

        db.commit()
        action = "activated" if new_active == 1 else "deactivated"
        return {"message": f"Cost element {action} successfully"}

    except HTTPException:
        raise
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cost_element_seed")
def cost_element_seed(
    payload: dict,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Copy template cost elements (co_id=0) to a tenant co_id. Idempotent."""
    try:
        co_id = payload.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        co_id = int(co_id)

        # Check if already seeded
        existing = (
            db.query(CostElementMst).filter_by(co_id=co_id, active=1).first()
        )
        if existing:
            raise HTTPException(
                status_code=409,
                detail="Cost elements already exist for this company. Seed skipped.",
            )

        # Fetch template rows ordered by level
        templates = db.execute(get_cost_element_template_query()).fetchall()
        if not templates:
            raise HTTPException(
                status_code=404, detail="No template elements found (co_id=0)"
            )

        user_id = int(token_data.get("user_id", 0))
        old_to_new = {}  # template cost_element_id -> new cost_element_id

        for tmpl in templates:
            t = dict(tmpl._mapping)
            old_id = t["cost_element_id"]
            old_parent = t["parent_element_id"]

            new_parent = old_to_new.get(old_parent) if old_parent else None

            new_element = CostElementMst(
                element_code=t["element_code"],
                element_name=t["element_name"],
                parent_element_id=new_parent,
                element_level=t["element_level"],
                element_type=t["element_type"],
                default_basis=t["default_basis"],
                is_leaf=t["is_leaf"],
                sort_order=t["sort_order"],
                element_desc=t["element_desc"],
                co_id=co_id,
                active=1,
                updated_by=user_id,
                updated_date_time=now_ist(),
            )
            db.add(new_element)
            db.flush()  # get the new PK
            old_to_new[old_id] = new_element.cost_element_id

        db.commit()
        response.status_code = 201
        return {
            "message": f"Seeded {len(old_to_new)} cost elements for co_id {co_id}",
            "count": len(old_to_new),
        }

    except HTTPException:
        raise
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))
