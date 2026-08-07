"""HRMS Pay Component endpoints — list, detail, create, update for pay_components table."""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.models.hrms import PayComponents, PayEmployeeStructure
from .query import (
    get_pay_component_list,
    get_pay_component_count,
    get_pay_component_by_id,
)
from src.common.utils import parse_json_body

router = APIRouter()

# Component type options
COMPONENT_TYPES = [
    {"value": 0, "label": "No Calculation"},
    {"value": 1, "label": "Earning"},
    {"value": 2, "label": "Deduction"},
    {"value": 3, "label": "Summary"},
]

ROUNDOF_OPTIONS = [
    {"value": 0, "label": "0 Decimals"},
    {"value": 1, "label": "1 Decimal"},
    {"value": 2, "label": "2 Decimals"},
    {"value": 3, "label": "3 Decimals"},
    {"value": 4, "label": "4 Decimals"},
    {"value": 5, "label": "5 Decimals"},
    {"value": 6, "label": "6 Decimals"},
    {"value": 7, "label": "7 Decimals"},
]

ROUNDOF_TYPE_OPTIONS = [
    {"value": 0, "label": "None"},
    {"value": 1, "label": "Round Up"},
    {"value": 2, "label": "Round Down"},
    {"value": 3, "label": "Round Nearest"},
]


# ─── Pay Component List ────────────────────────────────────────────

@router.get("/pay_component_list")
def pay_component_list(
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
        type_raw = request.query_params.get("type")
        comp_type = int(type_raw) if type_raw is not None and type_raw != "" else None

        params = {
            "co_id": co_id,
            "search": search,
            "type": comp_type,
            "page_size": page_size,
            "offset": (page - 1) * page_size,
        }

        rows = db.execute(get_pay_component_list(), params).fetchall()
        data = [dict(r._mapping) for r in rows]

        # Check which components are used in pay_employee_structure
        if data:
            comp_ids = [row["id"] for row in data]
            used_ids_rows = (
                db.query(PayEmployeeStructure.component_id)
                .filter(PayEmployeeStructure.component_id.in_(comp_ids))
                .distinct()
                .all()
            )
            used_ids = {r.component_id for r in used_ids_rows}
            for row in data:
                row["in_use"] = row["id"] in used_ids
        else:
            for row in data:
                row["in_use"] = False

        count_row = db.execute(
            get_pay_component_count(),
            {"co_id": co_id, "search": search, "type": comp_type},
        ).fetchone()
        total = count_row._mapping["total"] if count_row else 0

        return {"data": data, "total": total, "page": page, "page_size": page_size}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Pay Component By ID ───────────────────────────────────────────

@router.get("/pay_component_by_id/{component_id}")
def pay_component_by_id(
    component_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id_raw = request.query_params.get("co_id")
        co_id = int(co_id_raw) if co_id_raw else None

        row = db.execute(
            get_pay_component_by_id(), {"id": component_id, "co_id": co_id}
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Pay component not found")

        return {"data": dict(row._mapping)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Pay Component Create Setup ────────────────────────────────────

@router.get("/pay_component_create_setup")
def pay_component_create_setup(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id_raw = request.query_params.get("co_id")
        co_id = int(co_id_raw) if co_id_raw else None

        # Fetch existing components for parent dropdown
        q = db.query(PayComponents.id, PayComponents.name, PayComponents.code)
        if co_id is not None:
            q = q.filter(PayComponents.co_id == co_id)
        parents = q.order_by(PayComponents.name).all()
        parent_options = [
            {"value": p.id, "label": f"{p.code} - {p.name}" if p.code else p.name}
            for p in parents
        ]

        return {
            "data": {
                "type_options": COMPONENT_TYPES,
                "parent_options": parent_options,
                "roundof_options": ROUNDOF_OPTIONS,
                "roundof_type_options": ROUNDOF_TYPE_OPTIONS,
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Pay Component Create ──────────────────────────────────────────

@router.post("/pay_component_create")
def pay_component_create(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id_raw = request.query_params.get("co_id")
        co_id = int(co_id_raw) if co_id_raw else None

        body = parse_json_body(request)
        user_id = token_data.get("user_id", 0)

        code = (body.get("code") or "").strip()
        name = (body.get("name") or "").strip()
        if not code:
            raise HTTPException(status_code=400, detail="Code is required")
        if not name:
            raise HTTPException(status_code=400, detail="Name is required")

        # Check duplicate code within same tenant DB
        dup_q = db.query(PayComponents).filter(PayComponents.code == code)
        if co_id is not None:
            dup_q = dup_q.filter(PayComponents.co_id == co_id)
        if dup_q.first():
            raise HTTPException(status_code=400, detail=f"Component with code '{code}' already exists")

        comp = PayComponents(
            code=code,
            name=name,
            description=body.get("description"),
            type=int(body.get("type", 1)),
            effective_from=body.get("effective_from") or None,
            ends_on=body.get("ends_on") or None,
            parent_id=int(body["parent_id"]) if body.get("parent_id") else None,
            is_custom_component=1 if body.get("is_custom_component") else 0,
            is_displayable_in_payslip=1 if body.get("is_displayable_in_payslip") else 0,
            is_occasionally=1 if body.get("is_occasionally") else 0,
            is_excel_downloadable=1 if body.get("is_excel_downloadable") else 0,
            roundof=int(body["roundof"]) if body.get("roundof") is not None else None,
            roundof_type=int(body["roundof_type"]) if body.get("roundof_type") is not None else None,
            default_value=float(body["default_value"]) if body.get("default_value") else None,
            co_id=co_id,
            status_id=3,
            updated_by=user_id,
        )
        db.add(comp)
        db.commit()
        db.refresh(comp)

        return {"data": {"id": comp.id, "message": "Pay component created successfully"}}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# ─── Pay Component Update ──────────────────────────────────────────

@router.put("/pay_component_update/{component_id}")
def pay_component_update(
    component_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id_raw = request.query_params.get("co_id")
        co_id = int(co_id_raw) if co_id_raw else None

        body = parse_json_body(request)
        user_id = token_data.get("user_id", 0)

        find_q = db.query(PayComponents).filter(PayComponents.id == component_id)
        if co_id is not None:
            find_q = find_q.filter(PayComponents.co_id == co_id)
        comp = find_q.first()
        if not comp:
            raise HTTPException(status_code=404, detail="Pay component not found")

        code = (body.get("code") or "").strip()
        if code and code != comp.code:
            dup_q = db.query(PayComponents).filter(
                PayComponents.code == code,
                PayComponents.id != component_id,
            )
            if co_id is not None:
                dup_q = dup_q.filter(PayComponents.co_id == co_id)
            if dup_q.first():
                raise HTTPException(status_code=400, detail=f"Component with code '{code}' already exists")
            comp.code = code

        if "name" in body:
            comp.name = (body["name"] or "").strip()
        if "description" in body:
            comp.description = body["description"]
        if "type" in body:
            comp.type = int(body["type"])
        if "effective_from" in body:
            comp.effective_from = body["effective_from"] or None
        if "ends_on" in body:
            comp.ends_on = body["ends_on"] or None
        if "parent_id" in body:
            comp.parent_id = int(body["parent_id"]) if body["parent_id"] else None
        if "is_custom_component" in body:
            comp.is_custom_component = 1 if body["is_custom_component"] else 0
        if "is_displayable_in_payslip" in body:
            comp.is_displayable_in_payslip = 1 if body["is_displayable_in_payslip"] else 0
        if "is_occasionally" in body:
            comp.is_occasionally = 1 if body["is_occasionally"] else 0
        if "is_excel_downloadable" in body:
            comp.is_excel_downloadable = 1 if body["is_excel_downloadable"] else 0
        if "roundof" in body:
            comp.roundof = int(body["roundof"]) if body["roundof"] is not None else None
        if "roundof_type" in body:
            comp.roundof_type = int(body["roundof_type"]) if body["roundof_type"] is not None else None
        if "default_value" in body:
            comp.default_value = float(body["default_value"]) if body["default_value"] else None

        comp.updated_by = user_id
        db.commit()

        return {"data": {"id": component_id, "message": "Pay component updated successfully"}}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
