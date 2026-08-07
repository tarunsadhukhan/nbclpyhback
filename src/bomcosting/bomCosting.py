from fastapi import Depends, Request, HTTPException, APIRouter, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.masters.models import BomHdr, BomCostEntry, BomCostSnapshot, CostElementMst
from src.bomcosting.query import (
    get_bom_costing_list_query,
    get_bom_costing_detail_query,
    get_bom_cost_entries_for_hdr_query,
    get_next_bom_version_query,
    get_items_for_bom_costing_dropdown_query,
    get_children_entries_sum_query,
    get_cost_element_ancestors_query,
    get_cost_element_tree_query,
    get_bom_cost_snapshot_list_query,
    get_bom_cost_snapshot_detail_query,
    get_bom_cost_summary_view_query,
    mark_previous_snapshots_superseded_query,
)
from src.bomcosting.costElement import build_cost_element_tree
from src.common.utils import now_ist
from datetime import date

router = APIRouter()


# ═══════════════════════════════════════════════════════════════
# HELPER: Payload Validation
# ═══════════════════════════════════════════════════════════════

def parse_cost_basis_qty(value):
    """Validate a cost_basis_qty payload value (output-qty divisor for the
    rollup, design section 5.2). Returns a positive float or raises 400."""
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid cost_basis_qty format")
    if parsed <= 0:
        raise HTTPException(
            status_code=400, detail="cost_basis_qty must be greater than 0"
        )
    return parsed


# ═══════════════════════════════════════════════════════════════
# HELPER: Parent Rollup
# ═══════════════════════════════════════════════════════════════

def recompute_parent_rollup(db, bom_hdr_id, cost_element_id, co_id, user_id, effective_date):
    """After a leaf entry is saved/deleted, walk up the tree
    and recompute every ancestor as SUM(active children entries)."""
    # Sessions run with autoflush=False (get_tenant_db): flush pending ORM
    # changes so the raw-SQL child sums below see the leaf edit that
    # triggered this recompute.
    db.flush()
    ancestors = db.execute(
        get_cost_element_ancestors_query(),
        {"cost_element_id": int(cost_element_id), "co_id": int(co_id)},
    ).fetchall()

    for ancestor in ancestors:
        ancestor_id = ancestor._mapping["cost_element_id"]

        result = db.execute(
            get_children_entries_sum_query(),
            {
                "bom_hdr_id": int(bom_hdr_id),
                "parent_element_id": int(ancestor_id),
                "co_id": int(co_id),
            },
        ).fetchone()
        child_sum = float(result._mapping["total"]) if result._mapping["total"] else 0.0

        existing = (
            db.query(BomCostEntry)
            .filter(
                BomCostEntry.bom_hdr_id == int(bom_hdr_id),
                BomCostEntry.cost_element_id == int(ancestor_id),
                BomCostEntry.effective_date == effective_date,
                BomCostEntry.co_id == int(co_id),
                BomCostEntry.active == 1,
            )
            .first()
        )

        if existing:
            existing.amount = child_sum
            existing.source = "calculated"
            existing.qty = None
            existing.rate = None
            existing.updated_by = int(user_id)
            existing.updated_date_time = now_ist()
        else:
            new_entry = BomCostEntry(
                bom_hdr_id=int(bom_hdr_id),
                cost_element_id=int(ancestor_id),
                amount=child_sum,
                source="calculated",
                effective_date=effective_date,
                entered_by=int(user_id),
                co_id=int(co_id),
                active=1,
                updated_by=int(user_id),
                updated_date_time=now_ist(),
            )
            db.add(new_entry)

        db.flush()


# ═══════════════════════════════════════════════════════════════
# HELPER: Base Total Computation
# ═══════════════════════════════════════════════════════════════

def compute_base_total(material_cost, conversion_cost):
    """Base cost = material + conversion. Overhead is applied later as a % on the
    enquiry line (design 2026-07-16), so it is NOT part of the cost-sheet total."""
    return float(material_cost) + float(conversion_cost)


# ═══════════════════════════════════════════════════════════════
# HELPER: Full Rollup Computation
# ═══════════════════════════════════════════════════════════════

def compute_full_rollup(db, bom_hdr_id, co_id, user_id):
    """Compute full cost rollup and create a snapshot.

    cost_per_unit = total_cost / item_bom_hdr_mst.cost_basis_qty
    (output-qty divisor, design section 5.2; missing/zero basis treated as 1).
    """
    # Load the header's output-qty divisor for the per-unit cost
    hdr = (
        db.query(BomHdr)
        .filter_by(bom_hdr_id=int(bom_hdr_id), co_id=int(co_id), active=1)
        .first()
    )
    cost_basis_qty = (
        float(hdr.cost_basis_qty) if hdr and hdr.cost_basis_qty else 0.0
    )
    if cost_basis_qty <= 0:
        cost_basis_qty = 1.0

    # Load cost element tree
    elements = db.execute(
        get_cost_element_tree_query(), {"co_id": int(co_id)}
    ).fetchall()
    elements_by_id = {}
    for e in elements:
        d = dict(e._mapping)
        d["children_ids"] = []
        d["amount"] = 0.0
        d["source"] = None
        elements_by_id[d["cost_element_id"]] = d

    # Load all active cost entries
    entries = db.execute(
        get_bom_cost_entries_for_hdr_query(),
        {"bom_hdr_id": int(bom_hdr_id), "co_id": int(co_id)},
    ).fetchall()
    entries_by_element = {}
    for ent in entries:
        ed = dict(ent._mapping)
        entries_by_element[ed["cost_element_id"]] = ed

    # Assign entry amounts to elements
    for eid, elem in elements_by_id.items():
        entry = entries_by_element.get(eid)
        if entry:
            elem["amount"] = float(entry["amount"])
            elem["source"] = entry["source"]

    # Build parent->children mapping
    for eid, elem in elements_by_id.items():
        pid = elem["parent_element_id"]
        if pid and pid in elements_by_id:
            elements_by_id[pid]["children_ids"].append(eid)

    # Bottom-up aggregation
    max_level = max((e["element_level"] for e in elements_by_id.values()), default=0)
    for level in range(max_level, -1, -1):
        for eid, elem in elements_by_id.items():
            if elem["element_level"] == level and elem["children_ids"]:
                child_sum = sum(
                    elements_by_id[cid]["amount"] for cid in elem["children_ids"]
                )
                if child_sum > 0:
                    elem["amount"] = child_sum
                    elem["source"] = "calculated"

    # Compute category totals from root elements
    material_cost = 0.0
    conversion_cost = 0.0
    overhead_cost = 0.0
    for elem in elements_by_id.values():
        if elem["parent_element_id"] is None:
            if elem["element_type"] == "material":
                material_cost += elem["amount"]
            elif elem["element_type"] == "conversion":
                conversion_cost += elem["amount"]
            elif elem["element_type"] == "overhead":
                overhead_cost += elem["amount"]

    total_cost = compute_base_total(material_cost, conversion_cost)
    cost_per_unit = total_cost / cost_basis_qty

    # Build detail snapshot JSON
    detail_snapshot = [
        {
            "cost_element_id": e["cost_element_id"],
            "element_code": e["element_code"],
            "element_name": e["element_name"],
            "element_type": e["element_type"],
            "element_level": e["element_level"],
            "parent_element_id": e["parent_element_id"],
            "amount": e["amount"],
            "source": e["source"],
            "is_leaf": e["is_leaf"],
        }
        for e in sorted(elements_by_id.values(), key=lambda x: (x["sort_order"], x["element_level"]))
    ]

    # Mark old snapshots superseded
    db.execute(
        mark_previous_snapshots_superseded_query(),
        {"bom_hdr_id": int(bom_hdr_id), "co_id": int(co_id)},
    )

    # Create new snapshot
    snapshot = BomCostSnapshot(
        bom_hdr_id=int(bom_hdr_id),
        material_cost=material_cost,
        conversion_cost=conversion_cost,
        overhead_cost=overhead_cost,
        total_cost=total_cost,
        cost_per_unit=cost_per_unit,
        detail_snapshot=detail_snapshot,
        computed_at=now_ist(),
        computed_by=int(user_id),
        is_current=1,
        status="draft",
        co_id=int(co_id),
        active=1,
        updated_by=int(user_id),
        updated_date_time=now_ist(),
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)

    return {
        "bom_cost_snapshot_id": snapshot.bom_cost_snapshot_id,
        "material_cost": material_cost,
        "conversion_cost": conversion_cost,
        "overhead_cost": overhead_cost,
        "total_cost": total_cost,
        "cost_basis_qty": cost_basis_qty,
        "cost_per_unit": cost_per_unit,
        "detail_snapshot": detail_snapshot,
    }


# ═══════════════════════════════════════════════════════════════
# BOM HEADER CRUD
# ═══════════════════════════════════════════════════════════════

@router.get("/bom_costing_list")
def bom_costing_list(
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
            get_bom_costing_list_query(),
            {"co_id": int(co_id), "search": search_param},
        ).fetchall()
        data = [dict(r._mapping) for r in result]
        return {"data": data}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/bom_costing_detail")
def bom_costing_detail(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        bom_hdr_id = request.query_params.get("bom_hdr_id")
        co_id = request.query_params.get("co_id")
        if not bom_hdr_id or not co_id:
            raise HTTPException(
                status_code=400, detail="bom_hdr_id and co_id are required"
            )

        # Fetch header
        header_row = db.execute(
            get_bom_costing_detail_query(),
            {"bom_hdr_id": int(bom_hdr_id), "co_id": int(co_id)},
        ).fetchone()
        if not header_row:
            raise HTTPException(status_code=404, detail="BOM costing not found")
        header = dict(header_row._mapping)

        # Fetch cost entries
        entries_rows = db.execute(
            get_bom_cost_entries_for_hdr_query(),
            {"bom_hdr_id": int(bom_hdr_id), "co_id": int(co_id)},
        ).fetchall()
        entries_flat = [dict(r._mapping) for r in entries_rows]

        # Fetch full cost element tree for this co_id
        elements_rows = db.execute(
            get_cost_element_tree_query(), {"co_id": int(co_id)}
        ).fetchall()
        elements_flat = [dict(r._mapping) for r in elements_rows]

        # Merge entries into elements
        entries_by_element = {e["cost_element_id"]: e for e in entries_flat}
        for elem in elements_flat:
            entry = entries_by_element.get(elem["cost_element_id"])
            if entry:
                elem["bom_cost_entry_id"] = entry["bom_cost_entry_id"]
                elem["amount"] = entry["amount"]
                elem["source"] = entry["source"]
                elem["qty"] = entry["qty"]
                elem["rate"] = entry["rate"]
                elem["basis_override"] = entry["basis_override"]
                elem["effective_date"] = str(entry["effective_date"]) if entry["effective_date"] else None
                elem["remarks"] = entry["remarks"]
            else:
                elem["bom_cost_entry_id"] = None
                elem["amount"] = 0
                elem["source"] = None
                elem["qty"] = None
                elem["rate"] = None
                elem["basis_override"] = None
                elem["effective_date"] = None
                elem["remarks"] = None

        cost_tree = build_cost_element_tree(elements_flat)

        # Fetch snapshots
        snapshots_rows = db.execute(
            get_bom_cost_snapshot_list_query(),
            {"bom_hdr_id": int(bom_hdr_id), "co_id": int(co_id)},
        ).fetchall()
        snapshots = [dict(r._mapping) for r in snapshots_rows]

        return {
            "data": {
                "header": header,
                "cost_entries_tree": cost_tree,
                "cost_entries_flat": entries_flat,
                "snapshots": snapshots,
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/bom_costing_create_setup")
def bom_costing_create_setup(
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

        items_rows = db.execute(
            get_items_for_bom_costing_dropdown_query(),
            {"co_id": int(co_id), "search": search_param},
        ).fetchall()
        items = [dict(r._mapping) for r in items_rows]

        elements_rows = db.execute(
            get_cost_element_tree_query(), {"co_id": int(co_id)}
        ).fetchall()
        elements_flat = [dict(r._mapping) for r in elements_rows]
        elements_tree = build_cost_element_tree(elements_flat)

        return {"items": items, "cost_elements": elements_tree}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/bom_costing_create")
def bom_costing_create(
    payload: dict,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        item_id = payload.get("item_id")
        co_id = payload.get("co_id")
        if not item_id or not co_id:
            raise HTTPException(
                status_code=400, detail="item_id and co_id are required"
            )

        # Output-qty divisor for the rollup (optional; defaults to 1)
        cost_basis_qty = payload.get("cost_basis_qty")
        cost_basis_qty = (
            parse_cost_basis_qty(cost_basis_qty)
            if cost_basis_qty is not None
            else 1.0
        )

        # Auto-compute next version
        version_row = db.execute(
            get_next_bom_version_query(),
            {"item_id": int(item_id), "co_id": int(co_id)},
        ).fetchone()
        next_version = version_row._mapping["next_version"]

        user_id = int(token_data.get("user_id", 0))

        new_hdr = BomHdr(
            item_id=int(item_id),
            bom_version=int(next_version),
            version_label=payload.get("version_label"),
            status_id=21,  # draft
            effective_from=payload.get("effective_from"),
            effective_to=payload.get("effective_to"),
            is_current=0,
            cost_basis_qty=cost_basis_qty,
            remarks=payload.get("remarks"),
            co_id=int(co_id),
            active=1,
            updated_by=user_id,
            updated_date_time=now_ist(),
        )
        db.add(new_hdr)
        db.commit()
        db.refresh(new_hdr)

        response.status_code = 201
        return {
            "message": "BOM costing created successfully",
            "bom_hdr_id": new_hdr.bom_hdr_id,
            "bom_version": new_hdr.bom_version,
        }

    except HTTPException:
        raise
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/bom_costing_update")
def bom_costing_update(
    payload: dict,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        bom_hdr_id = payload.get("bom_hdr_id")
        co_id = payload.get("co_id")
        if not bom_hdr_id or not co_id:
            raise HTTPException(
                status_code=400, detail="bom_hdr_id and co_id are required"
            )

        hdr = (
            db.query(BomHdr)
            .filter_by(bom_hdr_id=int(bom_hdr_id), co_id=int(co_id), active=1)
            .first()
        )
        if not hdr:
            raise HTTPException(status_code=404, detail="BOM costing not found")

        if "version_label" in payload:
            hdr.version_label = payload["version_label"]
        if "remarks" in payload:
            hdr.remarks = payload["remarks"]
        if "effective_from" in payload:
            hdr.effective_from = payload["effective_from"]
        if "effective_to" in payload:
            hdr.effective_to = payload["effective_to"]
        if "status_id" in payload:
            hdr.status_id = int(payload["status_id"])
        if "cost_basis_qty" in payload:
            hdr.cost_basis_qty = parse_cost_basis_qty(payload["cost_basis_qty"])

        # If setting is_current=1, unset others for same item
        if payload.get("is_current") == 1:
            db.query(BomHdr).filter(
                BomHdr.item_id == hdr.item_id,
                BomHdr.co_id == int(co_id),
                BomHdr.bom_hdr_id != int(bom_hdr_id),
                BomHdr.is_current == 1,
            ).update({"is_current": 0}, synchronize_session="fetch")
            hdr.is_current = 1
        elif "is_current" in payload:
            hdr.is_current = int(payload["is_current"])

        hdr.updated_by = int(token_data.get("user_id", 0))
        hdr.updated_date_time = now_ist()
        db.commit()
        return {"message": "BOM costing updated successfully"}

    except HTTPException:
        raise
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════════════
# COST ENTRY OPERATIONS
# ═══════════════════════════════════════════════════════════════

@router.post("/bom_cost_entry_save")
def bom_cost_entry_save(
    payload: dict,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Save/update a cost entry. Core endpoint with skip-detail + parent rollup."""
    try:
        bom_hdr_id = payload.get("bom_hdr_id")
        cost_element_id = payload.get("cost_element_id")
        amount = payload.get("amount")
        effective_date = payload.get("effective_date")
        co_id = payload.get("co_id")

        if not bom_hdr_id or not cost_element_id or amount is None or not effective_date or not co_id:
            raise HTTPException(
                status_code=400,
                detail="bom_hdr_id, cost_element_id, amount, effective_date, and co_id are required",
            )

        # Validate BOM header exists
        hdr = (
            db.query(BomHdr)
            .filter_by(bom_hdr_id=int(bom_hdr_id), co_id=int(co_id), active=1)
            .first()
        )
        if not hdr:
            raise HTTPException(status_code=404, detail="BOM costing not found")

        # Validate cost element
        element = (
            db.query(CostElementMst)
            .filter_by(cost_element_id=int(cost_element_id), co_id=int(co_id), active=1)
            .first()
        )
        if not element:
            raise HTTPException(status_code=404, detail="Cost element not found")

        qty = payload.get("qty")
        rate = payload.get("rate")
        amount = float(amount)

        # Validate qty * rate = amount
        if qty is not None and rate is not None:
            qty = float(qty)
            rate = float(rate)
            expected = qty * rate
            if abs(amount - expected) > 0.01:
                raise HTTPException(
                    status_code=400,
                    detail=f"amount ({amount}) must equal qty × rate ({qty} × {rate} = {expected})",
                )

        # Skip-detail rule
        source = payload.get("source", "manual")
        if not element.is_leaf:
            child_result = db.execute(
                get_children_entries_sum_query(),
                {
                    "bom_hdr_id": int(bom_hdr_id),
                    "parent_element_id": int(cost_element_id),
                    "co_id": int(co_id),
                },
            ).fetchone()
            if child_result and child_result._mapping["entry_count"] and int(child_result._mapping["entry_count"]) > 0:
                raise HTTPException(
                    status_code=400,
                    detail="This element has child entries. Edit leaf entries directly, or remove children first.",
                )
            source = "assumed" if source not in ("manual",) else source

        user_id = int(token_data.get("user_id", 0))

        # Upsert: check unique (bom_hdr_id, cost_element_id, effective_date)
        existing = (
            db.query(BomCostEntry)
            .filter(
                BomCostEntry.bom_hdr_id == int(bom_hdr_id),
                BomCostEntry.cost_element_id == int(cost_element_id),
                BomCostEntry.effective_date == effective_date,
                BomCostEntry.co_id == int(co_id),
            )
            .first()
        )

        if existing:
            existing.amount = amount
            existing.source = source
            existing.qty = float(qty) if qty is not None else None
            existing.rate = float(rate) if rate is not None else None
            existing.basis_override = payload.get("basis_override")
            existing.remarks = payload.get("remarks")
            existing.active = 1
            existing.updated_by = user_id
            existing.updated_date_time = now_ist()
            entry_id = existing.bom_cost_entry_id
        else:
            new_entry = BomCostEntry(
                bom_hdr_id=int(bom_hdr_id),
                cost_element_id=int(cost_element_id),
                amount=amount,
                source=source,
                qty=float(qty) if qty is not None else None,
                rate=float(rate) if rate is not None else None,
                basis_override=payload.get("basis_override"),
                effective_date=effective_date,
                entered_by=user_id,
                remarks=payload.get("remarks"),
                co_id=int(co_id),
                active=1,
                updated_by=user_id,
                updated_date_time=now_ist(),
            )
            db.add(new_entry)
            try:
                db.flush()
                entry_id = new_entry.bom_cost_entry_id
            except IntegrityError:
                # Lost the insert race with a concurrent save (uk_bom_cost_entry):
                # roll back and update the row the winner created.
                db.rollback()
                existing = (
                    db.query(BomCostEntry)
                    .filter(
                        BomCostEntry.bom_hdr_id == int(bom_hdr_id),
                        BomCostEntry.cost_element_id == int(cost_element_id),
                        BomCostEntry.effective_date == effective_date,
                        BomCostEntry.co_id == int(co_id),
                    )
                    .first()
                )
                if not existing:
                    raise
                existing.amount = amount
                existing.source = source
                existing.qty = float(qty) if qty is not None else None
                existing.rate = float(rate) if rate is not None else None
                existing.basis_override = payload.get("basis_override")
                existing.remarks = payload.get("remarks")
                existing.active = 1
                existing.updated_by = user_id
                existing.updated_date_time = now_ist()
                entry_id = existing.bom_cost_entry_id

        # Recompute parent rollup
        recompute_parent_rollup(
            db, bom_hdr_id, cost_element_id, co_id, user_id, effective_date
        )

        db.commit()

        # Collect updated parent amounts to return
        ancestors = db.execute(
            get_cost_element_ancestors_query(),
            {"cost_element_id": int(cost_element_id), "co_id": int(co_id)},
        ).fetchall()
        updated_parents = []
        for anc in ancestors:
            anc_id = anc._mapping["cost_element_id"]
            parent_entry = (
                db.query(BomCostEntry)
                .filter(
                    BomCostEntry.bom_hdr_id == int(bom_hdr_id),
                    BomCostEntry.cost_element_id == int(anc_id),
                    BomCostEntry.effective_date == effective_date,
                    BomCostEntry.co_id == int(co_id),
                    BomCostEntry.active == 1,
                )
                .first()
            )
            if parent_entry:
                updated_parents.append({
                    "cost_element_id": anc_id,
                    "amount": parent_entry.amount,
                    "source": parent_entry.source,
                })

        return {
            "message": "Cost entry saved successfully",
            "bom_cost_entry_id": entry_id,
            "updated_parents": updated_parents,
        }

    except HTTPException:
        raise
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/bom_cost_entry_bulk_save")
def bom_cost_entry_bulk_save(
    payload: dict,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Batch save multiple cost entries with optimized rollup."""
    try:
        bom_hdr_id = payload.get("bom_hdr_id")
        co_id = payload.get("co_id")
        effective_date = payload.get("effective_date")
        entries = payload.get("entries", [])

        if not bom_hdr_id or not co_id or not effective_date:
            raise HTTPException(
                status_code=400,
                detail="bom_hdr_id, co_id, and effective_date are required",
            )
        if not entries:
            raise HTTPException(status_code=400, detail="entries list is required")

        # Validate BOM header
        hdr = (
            db.query(BomHdr)
            .filter_by(bom_hdr_id=int(bom_hdr_id), co_id=int(co_id), active=1)
            .first()
        )
        if not hdr:
            raise HTTPException(status_code=404, detail="BOM costing not found")

        user_id = int(token_data.get("user_id", 0))
        saved_ids = []
        affected_element_ids = set()

        for entry_data in entries:
            elem_id = entry_data.get("cost_element_id")
            amount = entry_data.get("amount")
            if elem_id is None or amount is None:
                continue

            qty = entry_data.get("qty")
            rate = entry_data.get("rate")
            source = entry_data.get("source", "manual")

            # Validate qty * rate
            if qty is not None and rate is not None:
                expected = float(qty) * float(rate)
                if abs(float(amount) - expected) > 0.01:
                    continue  # skip invalid entries in bulk mode

            # Upsert
            existing = (
                db.query(BomCostEntry)
                .filter(
                    BomCostEntry.bom_hdr_id == int(bom_hdr_id),
                    BomCostEntry.cost_element_id == int(elem_id),
                    BomCostEntry.effective_date == effective_date,
                    BomCostEntry.co_id == int(co_id),
                )
                .first()
            )

            if existing:
                existing.amount = float(amount)
                existing.source = source
                existing.qty = float(qty) if qty is not None else None
                existing.rate = float(rate) if rate is not None else None
                existing.remarks = entry_data.get("remarks")
                existing.active = 1
                existing.updated_by = user_id
                existing.updated_date_time = now_ist()
                saved_ids.append(existing.bom_cost_entry_id)
            else:
                new_entry = BomCostEntry(
                    bom_hdr_id=int(bom_hdr_id),
                    cost_element_id=int(elem_id),
                    amount=float(amount),
                    source=source,
                    qty=float(qty) if qty is not None else None,
                    rate=float(rate) if rate is not None else None,
                    effective_date=effective_date,
                    entered_by=user_id,
                    remarks=entry_data.get("remarks"),
                    co_id=int(co_id),
                    active=1,
                    updated_by=user_id,
                    updated_date_time=now_ist(),
                )
                db.add(new_entry)
                db.flush()
                saved_ids.append(new_entry.bom_cost_entry_id)

            affected_element_ids.add(int(elem_id))

        # Batch rollup: collect all unique ancestors and recompute each once
        all_ancestor_ids = set()
        for elem_id in affected_element_ids:
            ancestors = db.execute(
                get_cost_element_ancestors_query(),
                {"cost_element_id": elem_id, "co_id": int(co_id)},
            ).fetchall()
            for a in ancestors:
                all_ancestor_ids.add(a._mapping["cost_element_id"])

        # Recompute ancestors sorted by level DESC (deepest first)
        if all_ancestor_ids:
            ancestor_elements = (
                db.query(CostElementMst)
                .filter(
                    CostElementMst.cost_element_id.in_(all_ancestor_ids),
                    CostElementMst.co_id == int(co_id),
                )
                .order_by(CostElementMst.element_level.desc())
                .all()
            )
            for anc_elem in ancestor_elements:
                result = db.execute(
                    get_children_entries_sum_query(),
                    {
                        "bom_hdr_id": int(bom_hdr_id),
                        "parent_element_id": anc_elem.cost_element_id,
                        "co_id": int(co_id),
                    },
                ).fetchone()
                child_sum = float(result._mapping["total"]) if result._mapping["total"] else 0.0

                existing = (
                    db.query(BomCostEntry)
                    .filter(
                        BomCostEntry.bom_hdr_id == int(bom_hdr_id),
                        BomCostEntry.cost_element_id == anc_elem.cost_element_id,
                        BomCostEntry.effective_date == effective_date,
                        BomCostEntry.co_id == int(co_id),
                        BomCostEntry.active == 1,
                    )
                    .first()
                )
                if existing:
                    existing.amount = child_sum
                    existing.source = "calculated"
                    existing.qty = None
                    existing.rate = None
                    existing.updated_by = user_id
                    existing.updated_date_time = now_ist()
                else:
                    db.add(BomCostEntry(
                        bom_hdr_id=int(bom_hdr_id),
                        cost_element_id=anc_elem.cost_element_id,
                        amount=child_sum,
                        source="calculated",
                        effective_date=effective_date,
                        entered_by=user_id,
                        co_id=int(co_id),
                        active=1,
                        updated_by=user_id,
                        updated_date_time=now_ist(),
                    ))
                db.flush()

        db.commit()
        return {
            "message": f"Saved {len(saved_ids)} cost entries",
            "count": len(saved_ids),
        }

    except HTTPException:
        raise
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/bom_cost_entry_delete")
def bom_cost_entry_delete(
    payload: dict,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Soft-delete a cost entry and recompute parents."""
    try:
        bom_cost_entry_id = payload.get("bom_cost_entry_id")
        co_id = payload.get("co_id")
        if not bom_cost_entry_id or not co_id:
            raise HTTPException(
                status_code=400, detail="bom_cost_entry_id and co_id are required"
            )

        entry = (
            db.query(BomCostEntry)
            .filter_by(
                bom_cost_entry_id=int(bom_cost_entry_id), co_id=int(co_id), active=1
            )
            .first()
        )
        if not entry:
            raise HTTPException(status_code=404, detail="Cost entry not found")

        user_id = int(token_data.get("user_id", 0))
        cost_element_id = entry.cost_element_id
        bom_hdr_id = entry.bom_hdr_id
        effective_date = entry.effective_date

        entry.active = 0
        entry.updated_by = user_id
        entry.updated_date_time = now_ist()

        # Recompute parents
        recompute_parent_rollup(
            db, bom_hdr_id, cost_element_id, co_id, user_id, effective_date
        )

        db.commit()
        return {"message": "Cost entry deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════════════
# SNAPSHOTS & REPORTING
# ═══════════════════════════════════════════════════════════════

@router.post("/bom_cost_rollup")
def bom_cost_rollup(
    payload: dict,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Compute full cost rollup and create a snapshot."""
    try:
        bom_hdr_id = payload.get("bom_hdr_id")
        co_id = payload.get("co_id")
        if not bom_hdr_id or not co_id:
            raise HTTPException(
                status_code=400, detail="bom_hdr_id and co_id are required"
            )

        # Validate BOM exists
        hdr = (
            db.query(BomHdr)
            .filter_by(bom_hdr_id=int(bom_hdr_id), co_id=int(co_id), active=1)
            .first()
        )
        if not hdr:
            raise HTTPException(status_code=404, detail="BOM costing not found")

        user_id = int(token_data.get("user_id", 0))
        result = compute_full_rollup(db, bom_hdr_id, co_id, user_id)

        return {"message": "Cost rollup computed successfully", "snapshot": result}

    except HTTPException:
        raise
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/snapshot_approve")
def snapshot_approve(
    payload: dict,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Mark a cost snapshot as approved (design sections 5.2 + 6).

    Accepts bom_cost_snapshot_id (explicit snapshot) or bom_hdr_id (the
    header's current snapshot). Only that snapshot's status is flipped —
    other snapshots are untouched. The enquiry costing-confirm flow flips
    this status directly; this endpoint is the thin standalone equivalent.
    """
    try:
        bom_cost_snapshot_id = payload.get("bom_cost_snapshot_id")
        bom_hdr_id = payload.get("bom_hdr_id")
        co_id = payload.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        if not bom_cost_snapshot_id and not bom_hdr_id:
            raise HTTPException(
                status_code=400,
                detail="bom_cost_snapshot_id or bom_hdr_id is required",
            )

        if bom_cost_snapshot_id:
            snapshot = (
                db.query(BomCostSnapshot)
                .filter_by(
                    bom_cost_snapshot_id=int(bom_cost_snapshot_id),
                    co_id=int(co_id),
                    active=1,
                )
                .first()
            )
        else:
            snapshot = (
                db.query(BomCostSnapshot)
                .filter_by(
                    bom_hdr_id=int(bom_hdr_id),
                    co_id=int(co_id),
                    is_current=1,
                    active=1,
                )
                .first()
            )
        if not snapshot:
            raise HTTPException(status_code=404, detail="Snapshot not found")

        snapshot.status = "approved"
        snapshot.updated_by = int(token_data.get("user_id", 0))
        snapshot.updated_date_time = now_ist()
        db.commit()

        return {
            "message": "Snapshot approved successfully",
            "bom_cost_snapshot_id": snapshot.bom_cost_snapshot_id,
            "status": "approved",
        }

    except HTTPException:
        raise
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/bom_cost_snapshot_list")
def bom_cost_snapshot_list(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        bom_hdr_id = request.query_params.get("bom_hdr_id")
        co_id = request.query_params.get("co_id")
        if not bom_hdr_id or not co_id:
            raise HTTPException(
                status_code=400, detail="bom_hdr_id and co_id are required"
            )

        result = db.execute(
            get_bom_cost_snapshot_list_query(),
            {"bom_hdr_id": int(bom_hdr_id), "co_id": int(co_id)},
        ).fetchall()
        data = [dict(r._mapping) for r in result]
        return {"data": data}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/bom_cost_snapshot_detail")
def bom_cost_snapshot_detail(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        bom_cost_snapshot_id = request.query_params.get("bom_cost_snapshot_id")
        co_id = request.query_params.get("co_id")
        if not bom_cost_snapshot_id or not co_id:
            raise HTTPException(
                status_code=400,
                detail="bom_cost_snapshot_id and co_id are required",
            )

        result = db.execute(
            get_bom_cost_snapshot_detail_query(),
            {"bom_cost_snapshot_id": int(bom_cost_snapshot_id), "co_id": int(co_id)},
        ).fetchone()
        if not result:
            raise HTTPException(status_code=404, detail="Snapshot not found")

        return {"data": dict(result._mapping)}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/bom_cost_summary")
def bom_cost_summary(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        item_id = request.query_params.get("item_id")
        bom_hdr_id = request.query_params.get("bom_hdr_id")

        result = db.execute(
            get_bom_cost_summary_view_query(),
            {
                "co_id": int(co_id),
                "item_id": int(item_id) if item_id else None,
                "bom_hdr_id": int(bom_hdr_id) if bom_hdr_id else None,
            },
        ).fetchall()
        data = [dict(r._mapping) for r in result]
        return {"data": data}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
