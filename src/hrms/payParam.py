"""HRMS Pay Period / Pay Param endpoints — list, create, update, setup."""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.models.hrms import PayPeriod
from .query import get_pay_param_list
from src.common.utils import parse_json_body

router = APIRouter()


# ─── Pay Param List ─────────────────────────────────────────────────

@router.get("/pay_param_list")
def pay_param_list(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        page = int(request.query_params.get("page", 1))
        page_size = int(request.query_params.get("page_size", 20))
        search_raw = request.query_params.get("search")
        search = f"%{search_raw}%" if search_raw else None

        params = {
            "co_id": int(co_id),
            "search": search,
            "page_size": page_size,
            "offset": (page - 1) * page_size,
        }

        rows = db.execute(get_pay_param_list(), params).fetchall()
        data = [dict(r._mapping) for r in rows]

        return {"data": data, "page": page, "page_size": page_size}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Pay Param Create Setup ────────────────────────────────────────

@router.get("/pay_param_create_setup")
def pay_param_create_setup(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        from .query import get_pay_scheme_create_setup
        from sqlalchemy import text

        # Get pay schemes for dropdown
        schemes = db.execute(
            text("""
                SELECT ID AS id, CODE AS code, NAME AS name
                FROM pay_components
                WHERE company_id = :co_id AND TYPE = 0 AND STATUS = 1
                ORDER BY NAME
            """),
            {"co_id": int(co_id)},
        ).fetchall()

        # Get branches for dropdown
        branches = db.execute(
            text("""
                SELECT branch_id, branch_name
                FROM branch_mst
                WHERE co_id = :co_id AND active = 1
                ORDER BY branch_name
            """),
            {"co_id": int(co_id)},
        ).fetchall()

        return {
            "data": {
                "pay_schemes": [
                    {"label": r._mapping["name"], "value": str(r._mapping["id"])}
                    for r in schemes
                ],
                "branches": [
                    {"label": r._mapping["branch_name"], "value": str(r._mapping["branch_id"])}
                    for r in branches
                ],
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Pay Param Create ──────────────────────────────────────────────

@router.post("/pay_param_create")
def pay_param_create(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        body = parse_json_body(request)
        user_id = token_data.get("user_id", 0)

        period = PayPeriod(
            from_date=body.get("from_date"),
            to_date=body.get("to_date"),
            payscheme_id=body.get("payscheme_id"),
            branch_id=body.get("branch_id"),
            status_id=1,
            updated_by=user_id,
        )
        db.add(period)
        db.flush()
        db.commit()

        return {"data": {"id": period.id, "message": "Pay period created successfully"}}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# ─── Pay Param Update ──────────────────────────────────────────────

@router.put("/pay_param_update/{period_id}")
def pay_param_update(
    period_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        body = parse_json_body(request)
        user_id = token_data.get("user_id", 0)

        period = db.query(PayPeriod).filter(PayPeriod.id == period_id).first()
        if not period:
            raise HTTPException(status_code=404, detail="Pay period not found")

        for field in ("from_date", "to_date", "payscheme_id", "branch_id", "status_id"):
            if field in body:
                setattr(period, field, body[field])
        period.updated_by = user_id

        db.commit()
        return {"data": {"id": period_id, "message": "Pay period updated successfully"}}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
