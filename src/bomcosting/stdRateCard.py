from fastapi import Depends, Request, HTTPException, APIRouter, Response
from sqlalchemy.orm import Session
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.masters.models import StdRateCard, CostElementMst
from src.bomcosting.query import (
    get_std_rate_card_list_query,
    get_std_rate_card_current_query,
    get_std_rate_cards_for_bom_apply_query,
    get_cost_element_tree_query,
)
from src.common.utils import now_ist
from datetime import datetime

router = APIRouter()

VALID_RATE_TYPES = {"machine_hour", "labor_hour", "power_kwh", "floor_space_sqft", "overhead_pct"}
VALID_REFERENCE_TYPES = {"machine", "dept", "cost_element"}

# Mapping: element default_basis -> rate_type for rate card application
BASIS_TO_RATE_TYPE = {
    "per_machine_hour": "machine_hour",
    "per_hour": "labor_hour",
    "per_kwh": "power_kwh",
}


@router.get("/std_rate_card_list")
def std_rate_card_list(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        rate_type = request.query_params.get("rate_type")
        reference_type = request.query_params.get("reference_type")

        result = db.execute(
            get_std_rate_card_list_query(),
            {
                "co_id": int(co_id),
                "rate_type": rate_type if rate_type else None,
                "reference_type": reference_type if reference_type else None,
            },
        ).fetchall()
        data = [dict(r._mapping) for r in result]
        return {"data": data}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/std_rate_card_current")
def std_rate_card_current(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = request.query_params.get("co_id")
        rate_type = request.query_params.get("rate_type")
        if not co_id or not rate_type:
            raise HTTPException(status_code=400, detail="co_id and rate_type are required")

        reference_type = request.query_params.get("reference_type")
        reference_id = request.query_params.get("reference_id")

        result = db.execute(
            get_std_rate_card_current_query(),
            {
                "co_id": int(co_id),
                "rate_type": rate_type,
                "reference_type": reference_type if reference_type else None,
                "reference_id": int(reference_id) if reference_id else None,
            },
        ).fetchone()

        if not result:
            raise HTTPException(status_code=404, detail="No current rate card found")

        return {"data": dict(result._mapping)}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/std_rate_card_create")
def std_rate_card_create(
    payload: dict,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = payload.get("co_id")
        rate_type = payload.get("rate_type")
        rate = payload.get("rate")
        valid_from = payload.get("valid_from")

        if not co_id or not rate_type or rate is None or not valid_from:
            raise HTTPException(
                status_code=400,
                detail="co_id, rate_type, rate, and valid_from are required",
            )

        if rate_type not in VALID_RATE_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"rate_type must be one of: {', '.join(sorted(VALID_RATE_TYPES))}",
            )

        reference_type = payload.get("reference_type")
        if reference_type and reference_type not in VALID_REFERENCE_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"reference_type must be one of: {', '.join(sorted(VALID_REFERENCE_TYPES))}",
            )

        valid_to = payload.get("valid_to")
        if valid_to and valid_from and valid_to < valid_from:
            raise HTTPException(status_code=400, detail="valid_to must be >= valid_from")

        user_id = int(token_data.get("user_id", 0))

        new_card = StdRateCard(
            rate_type=rate_type,
            reference_id=int(payload["reference_id"]) if payload.get("reference_id") else None,
            reference_type=reference_type,
            rate=float(rate),
            uom=payload.get("uom"),
            valid_from=valid_from,
            valid_to=valid_to,
            co_id=int(co_id),
            active=1,
            updated_by=user_id,
            updated_date_time=now_ist(),
        )
        db.add(new_card)
        db.commit()
        db.refresh(new_card)

        response.status_code = 201
        return {
            "message": "Rate card created successfully",
            "std_rate_card_id": new_card.std_rate_card_id,
        }

    except HTTPException:
        raise
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/std_rate_card_update")
def std_rate_card_update(
    payload: dict,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        std_rate_card_id = payload.get("std_rate_card_id")
        co_id = payload.get("co_id")
        if not std_rate_card_id or not co_id:
            raise HTTPException(
                status_code=400, detail="std_rate_card_id and co_id are required"
            )

        card = (
            db.query(StdRateCard)
            .filter_by(
                std_rate_card_id=int(std_rate_card_id), co_id=int(co_id), active=1
            )
            .first()
        )
        if not card:
            raise HTTPException(status_code=404, detail="Rate card not found")

        if "rate" in payload:
            card.rate = float(payload["rate"])
        if "uom" in payload:
            card.uom = payload["uom"]
        if "valid_from" in payload:
            card.valid_from = payload["valid_from"]
        if "valid_to" in payload:
            card.valid_to = payload["valid_to"]

        card.updated_by = int(token_data.get("user_id", 0))
        card.updated_date_time = now_ist()
        db.commit()
        return {"message": "Rate card updated successfully"}

    except HTTPException:
        raise
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/std_rate_card_toggle_active")
def std_rate_card_toggle_active(
    payload: dict,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        std_rate_card_id = payload.get("std_rate_card_id")
        co_id = payload.get("co_id")
        if not std_rate_card_id or not co_id:
            raise HTTPException(
                status_code=400, detail="std_rate_card_id and co_id are required"
            )

        card = (
            db.query(StdRateCard)
            .filter_by(std_rate_card_id=int(std_rate_card_id), co_id=int(co_id))
            .first()
        )
        if not card:
            raise HTTPException(status_code=404, detail="Rate card not found")

        card.active = 0 if card.active == 1 else 1
        card.updated_by = int(token_data.get("user_id", 0))
        card.updated_date_time = now_ist()
        db.commit()

        action = "activated" if card.active == 1 else "deactivated"
        return {"message": f"Rate card {action} successfully"}

    except HTTPException:
        raise
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/std_rate_card_apply")
def std_rate_card_apply(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Suggest pre-populated cost entries based on current rate cards."""
    try:
        co_id = request.query_params.get("co_id")
        bom_hdr_id = request.query_params.get("bom_hdr_id")
        if not co_id or not bom_hdr_id:
            raise HTTPException(
                status_code=400, detail="co_id and bom_hdr_id are required"
            )

        # Fetch cost element tree
        elements = db.execute(
            get_cost_element_tree_query(), {"co_id": int(co_id)}
        ).fetchall()

        # Fetch current rate cards
        rate_cards = db.execute(
            get_std_rate_cards_for_bom_apply_query(), {"co_id": int(co_id)}
        ).fetchall()

        # Build rate lookup: rate_type -> first (most recent) rate card
        rate_lookup = {}
        for rc in rate_cards:
            rc_dict = dict(rc._mapping)
            rt = rc_dict["rate_type"]
            if rt not in rate_lookup:
                rate_lookup[rt] = rc_dict

        # Match leaf elements to rate cards
        suggestions = []
        for elem in elements:
            e = dict(elem._mapping)
            if not e["is_leaf"]:
                continue
            basis = e["default_basis"]
            matched_rate_type = BASIS_TO_RATE_TYPE.get(basis)
            if matched_rate_type and matched_rate_type in rate_lookup:
                rc = rate_lookup[matched_rate_type]
                suggestions.append({
                    "cost_element_id": e["cost_element_id"],
                    "element_code": e["element_code"],
                    "element_name": e["element_name"],
                    "default_basis": basis,
                    "suggested_rate": rc["rate"],
                    "uom": rc["uom"],
                    "source": "standard",
                    "rate_card_id": rc["std_rate_card_id"],
                })

        return {"data": suggestions}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
