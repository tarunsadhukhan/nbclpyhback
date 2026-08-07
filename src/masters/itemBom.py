from fastapi import Depends, Request, HTTPException, APIRouter, Response
from sqlalchemy.orm import Session
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.masters.models import ItemBom, BomHdr
from src.masters.query import (
    get_bom_items_with_children,
    get_bom_children_query,
    get_bom_parents_query,
    get_items_for_bom_dropdown,
    get_bom_uom_list,
    get_full_bom_tree_query,
    get_bom_node_by_id_query,
)
from src.common.utils import now_ist
from src.masters.constants import BOM_STATUS_VALUES
from src.common.utils import parse_json_body

router = APIRouter()

MAX_BOM_DEPTH = 15


def ensure_bom_hdr_exists(db: Session, item_id: int, co_id: int, user_id: int) -> BomHdr:
    """Ensure an item_bom_hdr_mst record exists for this item.
    Creates version 1 with is_current=1 if none exists."""
    existing = db.query(BomHdr).filter(
        BomHdr.item_id == item_id,
        BomHdr.co_id == co_id,
        BomHdr.active == 1,
    ).first()
    if existing:
        return existing

    new_hdr = BomHdr(
        item_id=item_id,
        bom_version=1,
        version_label=None,
        status_id=21,
        is_current=1,
        co_id=co_id,
        active=1,
        updated_by=user_id,
        updated_date_time=now_ist(),
    )
    db.add(new_hdr)
    db.flush()
    return new_hdr


def has_circular_reference(db: Session, parent_id: int, child_id: int, co_id: int, visited: set = None) -> bool:
    """Check if adding child_id under parent_id would create a cycle."""
    if visited is None:
        visited = set()
    if child_id == parent_id:
        return True
    if child_id in visited:
        return False
    visited.add(child_id)
    children = db.execute(
        get_bom_children_query(),
        {"parent_item_id": child_id, "co_id": co_id}
    ).fetchall()
    for row in children:
        if has_circular_reference(db, parent_id, row._mapping["child_item_id"], co_id, visited):
            return True
    return False


def build_bom_tree(db: Session, item_id: int, co_id: int) -> list:
    """Build BOM tree from an item using a single recursive CTE.

    Replaces the previous N+1 implementation. One DB round-trip fetches the
    full subtree as flat rows (depth-ordered), and we assemble in Python via a
    parent_item_id dict. Cycle protection is built into the CTE depth cap.
    """
    rows = db.execute(
        get_full_bom_tree_query(),
        {"root_item_id": item_id, "co_id": co_id},
    ).fetchall()

    if not rows:
        return []

    # Bucket rows by parent_item_id so each parent gets its ordered children.
    # Dedup by bom_id: the recursive CTE re-emits descendants once per copy of
    # an ancestor edge, so a (parent, child) duplicate at depth N inflates every
    # bom_id below it. Rows are ORDER BY depth ASC, so the first occurrence is
    # the canonical one.
    children_by_parent: dict[int, list] = {}
    seen_bom_ids: set[int] = set()
    for row in rows:
        node = dict(row._mapping)
        bom_id = node["bom_id"]
        if bom_id in seen_bom_ids:
            continue
        seen_bom_ids.add(bom_id)
        node.pop("depth", None)
        node["children"] = []
        node["is_leaf"] = True
        children_by_parent.setdefault(node["parent_item_id"], []).append(node)

    # Wire children references — each row's child_item_id may itself be a
    # parent in the bucket map.
    for parent_id, nodes in children_by_parent.items():
        for node in nodes:
            kids = children_by_parent.get(node["child_item_id"])
            if kids:
                node["children"] = kids
                node["is_leaf"] = False

    return children_by_parent.get(item_id, [])


@router.get("/get_bom_list")
def get_bom_list(
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

        query = get_bom_items_with_children()
        result = db.execute(query, {"co_id": int(co_id), "search": search_param}).fetchall()
        data = [dict(r._mapping) for r in result]
        return {"data": data}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_bom_tree")
def get_bom_tree(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = request.query_params.get("co_id")
        item_id = request.query_params.get("item_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        if not item_id:
            raise HTTPException(status_code=400, detail="item_id is required")

        tree = build_bom_tree(db, int(item_id), int(co_id))
        return {"data": tree}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_bom_children")
def get_bom_children(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = request.query_params.get("co_id")
        parent_item_id = request.query_params.get("parent_item_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        if not parent_item_id:
            raise HTTPException(status_code=400, detail="parent_item_id is required")

        query = get_bom_children_query()
        result = db.execute(query, {
            "parent_item_id": int(parent_item_id),
            "co_id": int(co_id),
        }).fetchall()
        data = [dict(r._mapping) for r in result]
        return {"data": data}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_bom_parents")
def get_bom_parents(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = request.query_params.get("co_id")
        child_item_id = request.query_params.get("child_item_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        if not child_item_id:
            raise HTTPException(status_code=400, detail="child_item_id is required")

        query = get_bom_parents_query()
        result = db.execute(query, {
            "child_item_id": int(child_item_id),
            "co_id": int(co_id),
        }).fetchall()
        data = [dict(r._mapping) for r in result]
        return {"data": data}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/bom_create_setup")
def bom_create_setup(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        search = request.query_params.get("search")
        items_query = get_items_for_bom_dropdown(search=search)
        params = {"co_id": int(co_id)}
        if search:
            params["search"] = f"%{search}%"
        items = db.execute(items_query, params).fetchall()

        uom_query = get_bom_uom_list()
        uoms = db.execute(uom_query).fetchall()

        return {
            "items": [dict(r._mapping) for r in items],
            "uoms": [dict(r._mapping) for r in uoms],
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/bom_add_component")
def bom_add_component(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        body = parse_json_body(request)
        parent_item_id = body.get("parent_item_id")
        child_item_id = body.get("child_item_id")
        qty = body.get("qty")
        uom_id = body.get("uom_id")
        co_id = body.get("co_id")
        sequence_no = body.get("sequence_no", 0)
        additional_description = body.get("additional_description")

        if not all([parent_item_id, child_item_id, qty, uom_id, co_id]):
            raise HTTPException(status_code=400, detail="parent_item_id, child_item_id, qty, uom_id, and co_id are required")

        parent_item_id = int(parent_item_id)
        child_item_id = int(child_item_id)
        co_id = int(co_id)

        # Self-reference check
        if parent_item_id == child_item_id:
            raise HTTPException(status_code=400, detail="An item cannot be a component of itself")

        # Circular reference check
        if has_circular_reference(db, parent_item_id, child_item_id, co_id):
            raise HTTPException(status_code=400, detail="Adding this component would create a circular reference")

        # Ensure a BOM header record exists for this parent item
        user_id = token_data.get("user_id", 0)
        ensure_bom_hdr_exists(db, parent_item_id, co_id, int(user_id))

        new_bom = ItemBom(
            parent_item_id=parent_item_id,
            child_item_id=child_item_id,
            qty=float(qty),
            uom_id=int(uom_id),
            co_id=co_id,
            sequence_no=int(sequence_no),
            additional_description=(additional_description or None),
            active=1,
            updated_by=token_data.get("user_id"),
            updated_date_time=now_ist(),
        )
        db.add(new_bom)
        db.commit()
        db.refresh(new_bom)
        response.status_code = 201
        return {"message": "Component added successfully", "bom_id": new_bom.bom_id}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/bom_add_components_bulk")
def bom_add_components_bulk(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Atomically add multiple BOM components under a single parent.

    Body: {
        parent_item_id, co_id,
        components: [{ child_item_id, qty, uom_id, sequence_no, additional_description? }, ...]
    }

    Validation per component: self-ref. Circular-ref runs once per unique child.
    Duplicate child_item_id values within the same payload are allowed (the
    item_bom unique constraint was removed in commit 2df30cf so duplicates can
    differ by sequence_no / additional_description). All inserts run inside one
    transaction; any failure rolls back the entire batch. Response bom_ids
    preserve request order.
    """
    try:
        body = parse_json_body(request)
        parent_item_id = body.get("parent_item_id")
        co_id = body.get("co_id")
        components = body.get("components")

        if not parent_item_id:
            raise HTTPException(status_code=400, detail="parent_item_id is required")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        if not isinstance(components, list) or not components:
            raise HTTPException(status_code=400, detail="components must be a non-empty list")

        parent_item_id = int(parent_item_id)
        co_id = int(co_id)

        normalised: list[dict] = []
        for idx, comp in enumerate(components):
            child_item_id = comp.get("child_item_id")
            qty = comp.get("qty")
            uom_id = comp.get("uom_id")
            sequence_no = comp.get("sequence_no", 0)
            additional_description = comp.get("additional_description")

            if not all([child_item_id, qty, uom_id]):
                raise HTTPException(
                    status_code=400,
                    detail=f"components[{idx}] requires child_item_id, qty, uom_id",
                )

            child_item_id = int(child_item_id)
            if child_item_id == parent_item_id:
                raise HTTPException(
                    status_code=400,
                    detail=f"components[{idx}] (item {child_item_id}) cannot be a component of itself",
                )

            normalised.append({
                "child_item_id": child_item_id,
                "qty": float(qty),
                "uom_id": int(uom_id),
                "sequence_no": int(sequence_no),
                "additional_description": (additional_description or None),
            })

        # Once per unique child, not once per row.
        for cid in {n["child_item_id"] for n in normalised}:
            if has_circular_reference(db, parent_item_id, cid, co_id):
                raise HTTPException(
                    status_code=400,
                    detail=f"adding item {cid} would create a circular reference",
                )

        user_id = int(token_data.get("user_id") or 0)
        ensure_bom_hdr_exists(db, parent_item_id, co_id, user_id)

        ts = now_ist()
        new_rows: list[ItemBom] = []
        for n in normalised:
            row = ItemBom(
                parent_item_id=parent_item_id,
                child_item_id=n["child_item_id"],
                qty=n["qty"],
                uom_id=n["uom_id"],
                co_id=co_id,
                sequence_no=n["sequence_no"],
                additional_description=n["additional_description"],
                active=1,
                updated_by=user_id,
                updated_date_time=ts,
            )
            db.add(row)
            new_rows.append(row)

        db.flush()
        db.commit()
        for r in new_rows:
            db.refresh(r)

        response.status_code = 201
        return {
            "message": f"{len(new_rows)} component(s) added successfully",
            "bom_ids": [r.bom_id for r in new_rows],
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/bom_edit_component")
def bom_edit_component(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        body = parse_json_body(request)
        bom_id = body.get("bom_id")
        co_id = body.get("co_id")

        if not bom_id:
            raise HTTPException(status_code=400, detail="bom_id is required")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        existing = db.query(ItemBom).filter(
            ItemBom.bom_id == int(bom_id),
            ItemBom.co_id == int(co_id),
            ItemBom.active == 1,
        ).first()

        if not existing:
            raise HTTPException(status_code=404, detail="BOM component not found")

        if "qty" in body and body["qty"] is not None:
            existing.qty = float(body["qty"])
        if "uom_id" in body and body["uom_id"] is not None:
            existing.uom_id = int(body["uom_id"])
        if "sequence_no" in body and body["sequence_no"] is not None:
            existing.sequence_no = int(body["sequence_no"])
        if "additional_description" in body:
            val = body["additional_description"]
            existing.additional_description = val if val else None

        existing.updated_by = token_data.get("user_id")
        existing.updated_date_time = now_ist()
        db.commit()
        return {"message": "Component updated successfully"}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/bom_update_status")
def bom_update_status(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Update the lifecycle status of a BOM header.
    Independent of status_id (BOM Costing approval) — interchangeable, no workflow.
    Any authenticated user with co_id access may switch between the allowed values.
    """
    try:
        body = parse_json_body(request)
        co_id = body.get("co_id")
        item_id = body.get("item_id")
        bom_status = body.get("bom_status")

        if not co_id or not item_id or not bom_status:
            raise HTTPException(status_code=400, detail="co_id, item_id, and bom_status are required")
        if bom_status not in BOM_STATUS_VALUES:
            raise HTTPException(
                status_code=400,
                detail=f"bom_status must be one of {list(BOM_STATUS_VALUES)}",
            )

        hdr = db.query(BomHdr).filter(
            BomHdr.item_id == int(item_id),
            BomHdr.co_id == int(co_id),
            BomHdr.is_current == 1,
            BomHdr.active == 1,
        ).first()

        if not hdr:
            raise HTTPException(status_code=404, detail="BOM header not found for this item")

        hdr.bom_status = bom_status
        hdr.updated_by = token_data.get("user_id")
        hdr.updated_date_time = now_ist()
        db.commit()
        return {"message": "Status updated", "bom_status": bom_status}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/bom_reorder_siblings")
def bom_reorder_siblings(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        body = parse_json_body(request)
        co_id = body.get("co_id")
        parent_item_id = body.get("parent_item_id")
        rows = body.get("rows")

        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        if not parent_item_id:
            raise HTTPException(status_code=400, detail="parent_item_id is required")
        if not isinstance(rows, list) or not rows:
            raise HTTPException(status_code=400, detail="rows must be a non-empty list")

        co_id = int(co_id)
        parent_item_id = int(parent_item_id)

        bom_ids = []
        seq_by_id = {}
        for r in rows:
            bom_id = r.get("bom_id")
            seq = r.get("sequence_no")
            if bom_id is None or seq is None:
                raise HTTPException(status_code=400, detail="each row needs bom_id and sequence_no")
            bom_ids.append(int(bom_id))
            seq_by_id[int(bom_id)] = int(seq)

        existing = db.query(ItemBom).filter(
            ItemBom.bom_id.in_(bom_ids),
            ItemBom.co_id == co_id,
            ItemBom.active == 1,
        ).all()

        if len(existing) != len(bom_ids):
            raise HTTPException(status_code=404, detail="one or more bom_ids not found")

        for row in existing:
            if row.parent_item_id != parent_item_id:
                raise HTTPException(
                    status_code=400,
                    detail="all rows must belong to the given parent_item_id",
                )

        user_id = token_data.get("user_id")
        ts = now_ist()
        for row in existing:
            row.sequence_no = seq_by_id[row.bom_id]
            row.updated_by = user_id
            row.updated_date_time = ts

        db.commit()
        return {"data": {"updated": len(existing)}}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/bom_remove_component")
def bom_remove_component(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        body = parse_json_body(request)
        bom_id = body.get("bom_id")
        co_id = body.get("co_id")

        if not bom_id:
            raise HTTPException(status_code=400, detail="bom_id is required")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        existing = db.query(ItemBom).filter(
            ItemBom.bom_id == int(bom_id),
            ItemBom.co_id == int(co_id),
            ItemBom.active == 1,
        ).first()

        if not existing:
            raise HTTPException(status_code=404, detail="BOM component not found")

        existing.active = 0
        existing.updated_by = token_data.get("user_id")
        existing.updated_date_time = now_ist()
        db.commit()
        return {"message": "Component removed successfully"}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
