"""HRMS Pay Scheme Creation endpoints — CRUD for pay_scheme_master / pay_scheme_details."""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.models.hrms import PayschemeMaster, PaySchemeDetails
from .query import (
    get_pay_scheme_master_list,
    get_pay_scheme_master_count,
    get_pay_scheme_master_by_id,
    get_pay_scheme_details_by_scheme_id,
    get_pay_scheme_dropdown,
    get_wage_type_list,
    get_pay_components_for_scheme,
    get_pay_scheme_create_setup,
    get_co_mst_list,
)
from src.common.utils import parse_json_body

router = APIRouter()


# ─── Pay Scheme List ────────────────────────────────────────────────

@router.get("/pay_scheme_list")
def pay_scheme_list(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id_raw = request.query_params.get("co_id")
        co_id = int(co_id_raw) if co_id_raw else None

        page = int(request.query_params.get("page", 1))
        page_size = int(request.query_params.get("page_size", 20))
        search_raw = request.query_params.get("search")
        search = f"%{search_raw}%" if search_raw else None

        params = {
            "co_id": co_id,
            "search": search,
            "page_size": page_size,
            "offset": (page - 1) * page_size,
        }

        rows = db.execute(get_pay_scheme_master_list(), params).fetchall()
        data = [dict(r._mapping) for r in rows]

        total_row = db.execute(
            get_pay_scheme_master_count(),
            {"co_id": co_id, "search": search},
        ).fetchone()
        total = total_row._mapping["total"] if total_row else 0

        return {"data": data, "total": total, "page": page, "page_size": page_size}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Pay Scheme By ID ──────────────────────────────────────────────

@router.get("/pay_scheme_by_id/{payscheme_id}")
def pay_scheme_by_id(
    payscheme_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        row = db.execute(
            get_pay_scheme_master_by_id(), {"payscheme_id": payscheme_id}
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Pay scheme not found")

        details = db.execute(
            get_pay_scheme_details_by_scheme_id(), {"payscheme_id": payscheme_id}
        ).fetchall()

        return {
            "data": {
                "scheme": dict(row._mapping),
                "details": [dict(r._mapping) for r in details],
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Pay Scheme Create Setup ───────────────────────────────────────

@router.get("/pay_scheme_create_setup")
def pay_scheme_create_setup(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id_raw = request.query_params.get("co_id")
        co_id = int(co_id_raw) if co_id_raw else None

        # Wage types
        wage_rows = db.execute(get_wage_type_list()).fetchall()
        wage_types = [dict(r._mapping) for r in wage_rows]

        # Pay components (for add item) — all components, not filtered by company
        comp_rows = db.execute(
            get_pay_components_for_scheme()
        ).fetchall()
        components = [dict(r._mapping) for r in comp_rows]

        # Existing pay schemes (for clone dropdown)
        scheme_rows = db.execute(
            get_pay_scheme_dropdown(), {"co_id": co_id}
        ).fetchall()
        schemes = [dict(r._mapping) for r in scheme_rows]

        # Companies from co_mst
        co_rows = db.execute(get_co_mst_list()).fetchall()
        companies = [dict(r._mapping) for r in co_rows]

        return {
            "data": {
                "wage_types": wage_types,
                "components": components,
                "schemes": schemes,
                "companies": companies,
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Pay Scheme Create ─────────────────────────────────────────────

@router.post("/pay_scheme_create")
def pay_scheme_create(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        body = parse_json_body(request)
        user_id = token_data.get("user_id", 0)

        co_id = body.get("co_id")
        code = body.get("code")
        name = body.get("name")
        wage_type = body.get("wage_type")

        if not code:
            raise HTTPException(status_code=400, detail="Code is required")
        if not name:
            raise HTTPException(status_code=400, detail="Name is required")
        if wage_type is None:
            raise HTTPException(status_code=400, detail="Wage type is required")

        scheme = PayschemeMaster(
            co_id=int(co_id) if co_id else None,
            payscheme_code=code,
            payscheme_name=name,
            wage_type=int(wage_type),
            branch_id=int(body["branch_id"]) if body.get("branch_id") else None,
            effective_from=body.get("effective_from"),
            record_status=1,
            updated_by=user_id,
        )
        db.add(scheme)
        db.flush()

        # Add detail lines
        for item in body.get("details", []):
            dtl = PaySchemeDetails(
                pay_scheme_id=scheme.payscheme_id,
                component_id=int(item["component_id"]),
                formula=item.get("formula"),
                type=str(item.get("type", "")),
                status_id=1,
                default_value=float(item["default_value"]) if item.get("default_value") is not None else None,
                updated_by=user_id,
            )
            db.add(dtl)

        db.commit()
        return {"data": {"payscheme_id": scheme.payscheme_id, "message": "Pay scheme created successfully"}}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# ─── Pay Scheme Update ─────────────────────────────────────────────

@router.put("/pay_scheme_update/{payscheme_id}")
def pay_scheme_update(
    payscheme_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        body = parse_json_body(request)
        user_id = token_data.get("user_id", 0)

        scheme = db.query(PayschemeMaster).filter(
            PayschemeMaster.payscheme_id == payscheme_id
        ).first()
        if not scheme:
            raise HTTPException(status_code=404, detail="Pay scheme not found")

        # Update header fields
        if "code" in body:
            scheme.payscheme_code = body["code"]
        if "name" in body:
            scheme.payscheme_name = body["name"]
        if "wage_type" in body:
            scheme.wage_type = int(body["wage_type"])
        if "branch_id" in body:
            scheme.branch_id = int(body["branch_id"]) if body["branch_id"] else None
        if "effective_from" in body:
            scheme.effective_from = body["effective_from"]
        if "record_status" in body:
            scheme.record_status = int(body["record_status"])
        scheme.updated_by = user_id

        # Replace detail lines if provided
        if "details" in body:
            # Soft-delete existing (set STATUS=0)
            db.query(PaySchemeDetails).filter(
                PaySchemeDetails.pay_scheme_id == payscheme_id
            ).update({"status_id": 0})

            for item in body["details"]:
                if item.get("status", 1) == 0:
                    continue  # skip deleted items
                dtl = PaySchemeDetails(
                    pay_scheme_id=payscheme_id,
                    component_id=int(item["component_id"]),
                    formula=item.get("formula"),
                    type=str(item.get("type", "")),
                    status_id=1,
                    default_value=float(item["default_value"]) if item.get("default_value") is not None else None,
                    updated_by=user_id,
                )
                db.add(dtl)

        db.commit()
        return {"data": {"payscheme_id": payscheme_id, "message": "Pay scheme updated successfully"}}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
