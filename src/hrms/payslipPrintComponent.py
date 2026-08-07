"""HRMS Payslip Print Component CRUD endpoints.

Manages tbl_payslip_print_component — which pay components to include when
printing/exporting payslips and pay-registers, in what order, and with what
printed label (desc_print).

Endpoints (all prefixed /api/hrms by main.py):
  GET  /payslip_print_component_list           — paginated list (JOINs for names)
  GET  /payslip_print_component_by_id/{pay_id} — single row by PK
  GET  /payslip_print_component_setup           — pay schemes dropdown only
  GET  /pay_scheme_components                   — components for a selected scheme
  POST /payslip_print_component_create          — create a new row
  PUT  /payslip_print_component_update/{pay_id} — update an existing row
  DELETE /payslip_print_component_delete/{pay_id} — permanently delete a row
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.models.hrms import TblPayslipPrintComponent
from .query import (
    list_payslip_print_components,
    count_payslip_print_components,
    get_payslip_print_component_by_id,
    check_payslip_print_component_duplicate,
    get_pay_scheme_dropdown,
    get_pay_scheme_details_by_scheme_id,
    get_pay_scheme_master_by_id,
)
from src.common.utils import parse_json_body

router = APIRouter()

_ALLOWED_FIXED_VAR = {"F", "V"}


def _validate_and_extract(body: dict, company_id: int) -> dict:
    """Extract and validate fields from request body.

    Args:
        body: parsed JSON request body
        company_id: derived from co_id query param (never from body)

    Returns:
        dict of validated fields

    Raises:
        HTTPException 400 on any validation failure
    """
    payscheme_id = body.get("payscheme_id")
    if not payscheme_id:
        raise HTTPException(status_code=400, detail="payscheme_id is required")

    component_id = body.get("component_id")
    if not component_id:
        raise HTTPException(status_code=400, detail="component_id is required")

    branch_id = body.get("branch_id")
    if branch_id is None:
        raise HTTPException(status_code=400, detail="Branch is required")

    fixed_var_cols = body.get("fixed_var_cols")
    if fixed_var_cols is not None and fixed_var_cols not in _ALLOWED_FIXED_VAR:
        raise HTTPException(
            status_code=400,
            detail=f"fixed_var_cols must be one of {sorted(_ALLOWED_FIXED_VAR)}",
        )

    return {
        "company_id": company_id,
        "payscheme_id": int(payscheme_id),
        "component_id": int(component_id),
        "branch_id": int(branch_id),
        "desc_print": body.get("desc_print"),
        "payslip_order": int(body["payslip_order"]) if body.get("payslip_order") is not None else None,
        "fixed_var_cols": fixed_var_cols,
        "total_print": int(body.get("total_print", 0)),
        "payslip_print": int(body.get("payslip_print", 1)),
        "is_active": int(body.get("is_active", 1)),
    }


# ─── Payslip Print Component List ──────────────────────────────────


@router.get("/payslip_print_component_list")
def payslip_print_component_list(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Paginated list of configured payslip/export columns.

    Query params:
      co_id        (required)
      branch_ids   CSV of branch IDs, e.g. "1,2,3" (optional)
      payscheme_id (optional)
      search       (optional, searches component name + desc_print)
      page         (default 1)
      page_size    (default 20)
    """
    try:
        co_id_raw = request.query_params.get("co_id")
        if not co_id_raw:
            raise HTTPException(status_code=400, detail="co_id is required")
        company_id = int(co_id_raw)

        branch_ids = request.query_params.get("branch_id") or None
        payscheme_id_raw = request.query_params.get("payscheme_id")
        payscheme_id = int(payscheme_id_raw) if payscheme_id_raw else None
        search_raw = request.query_params.get("search")
        search = f"%{search_raw}%" if search_raw else None

        page = int(request.query_params.get("page", 1))
        page_size = int(request.query_params.get("limit", 10))
        offset = (page - 1) * page_size

        list_params = {
            "company_id": company_id,
            "branch_ids": branch_ids,
            "payscheme_id": payscheme_id,
            "search": search,
            "page_size": page_size,
            "offset": offset,
        }
        count_params = {
            "company_id": company_id,
            "branch_ids": branch_ids,
            "payscheme_id": payscheme_id,
            "search": search,
        }

        rows = db.execute(list_payslip_print_components(), list_params).fetchall()
        data = [dict(r._mapping) for r in rows]

        total_row = db.execute(count_payslip_print_components(), count_params).fetchone()
        total = total_row._mapping["total"] if total_row else 0

        return {"data": data, "total": total, "page": page, "page_size": page_size}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Payslip Print Component By ID ─────────────────────────────────


@router.get("/payslip_print_component_by_id/{pay_id}")
def payslip_print_component_by_id(
    pay_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Get a single payslip print component row by primary key.

    Query params:
      co_id (required) — scoping guard, prevents cross-company access
    """
    try:
        co_id_raw = request.query_params.get("co_id")
        if not co_id_raw:
            raise HTTPException(status_code=400, detail="co_id is required")
        company_id = int(co_id_raw)

        row = db.execute(
            get_payslip_print_component_by_id(),
            {"pay_id": pay_id, "company_id": company_id},
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Record not found")

        return {"data": dict(row._mapping)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Payslip Print Component Setup (pay schemes dropdown only) ─────


@router.get("/payslip_print_component_setup")
def payslip_print_component_setup(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Return pay schemes dropdown for the create/edit dialog.

    Returns:
      pay_schemes — pay schemes for the company (payscheme_id + names)

    Query params:
      co_id (required)

    Note: scheme components are fetched separately via GET /pay_scheme_components.
    """
    try:
        co_id_raw = request.query_params.get("co_id")
        if not co_id_raw:
            raise HTTPException(status_code=400, detail="co_id is required")
        company_id = int(co_id_raw)

        scheme_rows = db.execute(
            get_pay_scheme_dropdown(), {"co_id": company_id}
        ).fetchall()
        pay_schemes = [dict(r._mapping) for r in scheme_rows]

        return {"data": {"pay_schemes": pay_schemes}}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Pay Scheme Components (components for a selected scheme) ──────


@router.get("/pay_scheme_components")
def pay_scheme_components(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Return pay components for a given pay scheme.

    Query params:
      co_id        (required)
      payscheme_id (required)

    Returns:
      {"data": [{component_id, component_name, component_code, type}]}
    """
    try:
        co_id_raw = request.query_params.get("co_id")
        if not co_id_raw:
            raise HTTPException(status_code=400, detail="co_id is required")
        company_id = int(co_id_raw)

        payscheme_id_raw = request.query_params.get("payscheme_id")
        if not payscheme_id_raw:
            raise HTTPException(status_code=400, detail="payscheme_id is required")
        payscheme_id = int(payscheme_id_raw)

        # Company-ownership check: ensure this scheme belongs to the requesting company
        scheme_row = db.execute(
            get_pay_scheme_master_by_id(),
            {"payscheme_id": payscheme_id},
        ).fetchone()
        if not scheme_row or scheme_row._mapping.get("co_id") != company_id:
            raise HTTPException(status_code=404, detail="Pay scheme not found")

        comp_rows = db.execute(
            get_pay_scheme_details_by_scheme_id(),
            {"payscheme_id": payscheme_id},
        ).fetchall()
        data = [
            {
                "component_id": r._mapping.get("component_id") or r._mapping.get("id"),
                "component_name": r._mapping.get("component_name"),
                "component_code": r._mapping.get("component_code"),
                "type": r._mapping.get("type"),
            }
            for r in comp_rows
        ]

        return {"data": data}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Payslip Print Component Create ────────────────────────────────


@router.post("/payslip_print_component_create")
def payslip_print_component_create(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Create a new payslip print component configuration row.

    Query params:
      co_id (required) — company is always derived from this param, never from body

    Body (JSON):
      branch_id     (required)
      payscheme_id  (required)
      component_id  (required)
      desc_print    (optional) — printed label; defaults to component name if omitted
      payslip_order (optional, int)
      fixed_var_cols (optional, str — must be "F" or "V")
      total_print   (optional, int 0/1)
      payslip_print (optional, int 0/1, default 1)
    """
    try:
        co_id_raw = request.query_params.get("co_id")
        if not co_id_raw:
            raise HTTPException(status_code=400, detail="co_id is required")
        company_id = int(co_id_raw)

        body = parse_json_body(request)
        user_id = token_data.get("user_id", 0)

        fields = _validate_and_extract(body, company_id)

        # Duplicate check: same scheme + company + branch + component (active rows only)
        dup = db.execute(
            check_payslip_print_component_duplicate(),
            {
                "payscheme_id": fields["payscheme_id"],
                "company_id": fields["company_id"],
                "branch_id": fields["branch_id"],
                "component_id": fields["component_id"],
                "exclude_pay_id": 0,
            },
        ).fetchone()
        if dup:
            raise HTTPException(
                status_code=400,
                detail="A configuration for this scheme/branch/component already exists",
            )

        record = TblPayslipPrintComponent(
            payscheme_id=fields["payscheme_id"],
            company_id=fields["company_id"],
            branch_id=fields["branch_id"],
            component_id=fields["component_id"],
            desc_print=fields["desc_print"],
            payslip_order=fields["payslip_order"],
            fixed_var_cols=fields["fixed_var_cols"],
            total_print=fields["total_print"],
            payslip_print=fields["payslip_print"],
            is_active=1,
            updated_by=user_id,
        )
        db.add(record)
        db.flush()
        db.commit()
        db.refresh(record)

        return {"data": {"pay_id": record.pay_id, "message": "Record created successfully"}}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# ─── Payslip Print Component Update ────────────────────────────────


@router.put("/payslip_print_component_update/{pay_id}")
def payslip_print_component_update(
    pay_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Update an existing payslip print component configuration row.

    Query params:
      co_id (required) — company is always derived from this param, never from body

    Body (JSON): same fields as create; partial updates supported.
      Pass is_active=0 to deactivate (skips duplicate check).
    """
    try:
        co_id_raw = request.query_params.get("co_id")
        if not co_id_raw:
            raise HTTPException(status_code=400, detail="co_id is required")
        company_id = int(co_id_raw)

        body = parse_json_body(request)
        user_id = token_data.get("user_id", 0)

        # Fetch with company scoping (prevents cross-tenant writes)
        record = db.query(TblPayslipPrintComponent).filter(
            TblPayslipPrintComponent.pay_id == pay_id,
            TblPayslipPrintComponent.company_id == company_id,
        ).first()
        if not record:
            raise HTTPException(status_code=404, detail="Record not found")

        fields = _validate_and_extract(body, company_id)

        # Only run duplicate check when row is active (not a deactivation)
        if fields["is_active"] == 1:
            dup = db.execute(
                check_payslip_print_component_duplicate(),
                {
                    "payscheme_id": fields["payscheme_id"],
                    "company_id": fields["company_id"],
                    "branch_id": fields["branch_id"],
                    "component_id": fields["component_id"],
                    "exclude_pay_id": pay_id,
                },
            ).fetchone()
            if dup:
                raise HTTPException(
                    status_code=400,
                    detail="A configuration for this scheme/branch/component already exists",
                )

        # Apply updates
        record.payscheme_id = fields["payscheme_id"]
        record.company_id = fields["company_id"]
        record.branch_id = fields["branch_id"]
        record.component_id = fields["component_id"]
        record.desc_print = fields["desc_print"]
        record.payslip_order = fields["payslip_order"]
        record.fixed_var_cols = fields["fixed_var_cols"]
        record.total_print = fields["total_print"]
        record.payslip_print = fields["payslip_print"]
        record.is_active = fields["is_active"]
        record.updated_by = user_id

        db.commit()
        return {"data": {"pay_id": pay_id, "message": "Record updated successfully"}}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# ─── Payslip Print Component Delete ────────────────────────────────


@router.delete("/payslip_print_component_delete/{pay_id}")
def payslip_print_component_delete(
    pay_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Permanently delete a payslip print component configuration row.

    Query params:
      co_id (required) — company is always derived from this param, never from body

    The row is removed from tbl_payslip_print_component (hard delete). Company
    scoping prevents cross-tenant deletes.
    """
    try:
        co_id_raw = request.query_params.get("co_id")
        if not co_id_raw:
            raise HTTPException(status_code=400, detail="co_id is required")
        company_id = int(co_id_raw)

        # Fetch with company scoping (prevents cross-tenant deletes)
        record = db.query(TblPayslipPrintComponent).filter(
            TblPayslipPrintComponent.pay_id == pay_id,
            TblPayslipPrintComponent.company_id == company_id,
        ).first()
        if not record:
            raise HTTPException(status_code=404, detail="Record not found")

        db.delete(record)
        db.commit()
        return {"data": {"pay_id": pay_id, "message": "Record deleted successfully"}}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
