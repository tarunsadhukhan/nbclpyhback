"""
Accounting API endpoints.
Covers: setup & masters, voucher operations, reports, and opening balances.
"""
import logging
from datetime import date, datetime, timedelta
from fastapi import Depends, Request, HTTPException, APIRouter
from sqlalchemy.orm import Session
from sqlalchemy import text

from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.accounting import query as acc_query
from src.accounting import report_query
from src.accounting import voucher_service
from src.accounting.seed_data import activate_company
from src.accounting.constants import (
    DUE_DATE_RULES,
    POSTING_MODES,
    POSTING_QUEUE_STATUSES,
    VOUCHER_CATEGORIES,
)
from src.common.utils import parse_json_body

logger = logging.getLogger(__name__)

router = APIRouter()


# =============================================================================
# SETUP & MASTERS
# =============================================================================

# 1. POST /activate_company
@router.post("/activate_company")
def activate_company_endpoint(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        body = parse_json_body(request)
        co_id = body.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        user_id = token_data.get("user_id")
        result = activate_company(db, int(co_id), int(user_id))
        return {"data": result}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 2. GET /ledger_groups
@router.get("/ledger_groups")
def get_ledger_groups(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        query = acc_query.get_ledger_groups(int(co_id))
        rows = db.execute(query, {"co_id": int(co_id)}).fetchall()
        data = [dict(r._mapping) for r in rows]
        return {"data": data}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 3. POST /ledger_groups
@router.post("/ledger_groups")
def create_ledger_group(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        body = parse_json_body(request)
        co_id = body.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        group_name = body.get("group_name")
        parent_group_id = body.get("parent_group_id")
        nature = body.get("nature")
        affects_gross_profit = body.get("affects_gross_profit", 0)
        is_revenue = body.get("is_revenue", 0)
        normal_balance = body.get("normal_balance")
        is_party_group = body.get("is_party_group", 0)
        sequence_no = body.get("sequence_no", 999)

        if not group_name:
            raise HTTPException(status_code=400, detail="group_name is required")

        # A child group always carries its parent's nature — the whole branch has to
        # stay on one side of the chart of accounts, so the parent wins over the body.
        if parent_group_id:
            parent = db.execute(
                text("""
                    SELECT nature FROM acc_ledger_group
                    WHERE acc_ledger_group_id = :parent_group_id AND co_id = :co_id
                """),
                {"parent_group_id": int(parent_group_id), "co_id": int(co_id)},
            ).fetchone()
            if not parent:
                raise HTTPException(status_code=400, detail="Invalid parent_group_id")
            nature = parent[0]
            normal_balance = None  # recomputed below from the inherited nature

        if not nature:
            raise HTTPException(status_code=400, detail="nature is required")

        # Derive from nature when the FE omits it — Asset/Expense sit on the
        # debit side, Liability/Income on the credit side. Explicit body wins.
        if not normal_balance:
            normal_balance = {"A": "D", "E": "D", "L": "C", "I": "C"}.get(
                (nature or "").strip().upper()
            )

        user_id = token_data.get("user_id")

        result = db.execute(
            text("""
                INSERT INTO acc_ledger_group
                    (co_id, group_name, parent_group_id, nature,
                     affects_gross_profit, is_revenue, normal_balance,
                     is_party_group, is_system_group, sequence_no, active,
                     updated_by)
                VALUES
                    (:co_id, :group_name, :parent_group_id, :nature,
                     :affects_gross_profit, :is_revenue, :normal_balance,
                     :is_party_group, 0, :sequence_no, 1,
                     :updated_by)
            """),
            {
                "co_id": int(co_id),
                "group_name": group_name,
                "parent_group_id": int(parent_group_id) if parent_group_id else None,
                "nature": nature,
                "affects_gross_profit": int(affects_gross_profit),
                "is_revenue": int(is_revenue),
                "normal_balance": normal_balance,
                "is_party_group": int(is_party_group),
                "sequence_no": int(sequence_no),
                "updated_by": int(user_id),
            },
        )
        db.commit()

        return {"data": {"acc_ledger_group_id": result.lastrowid}}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 4. GET /ledgers
@router.get("/ledgers")
def get_ledgers(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        ledger_type = request.query_params.get("ledger_type")
        search = request.query_params.get("search")
        search_param = f"%{search}%" if search else None

        query = acc_query.get_ledgers(int(co_id))
        rows = db.execute(query, {
            "co_id": int(co_id),
            "ledger_type": ledger_type if ledger_type else None,
            "search": search_param,
        }).fetchall()
        data = [dict(r._mapping) for r in rows]
        return {"data": data}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _ensure_ledger_group(db: Session, group_id: int, co_id: int):
    """400 (not a raw-SQL 500) when the ledger group doesn't exist for this company."""
    row = db.execute(
        text("""
            SELECT 1 FROM acc_ledger_group
            WHERE acc_ledger_group_id = :group_id AND co_id = :co_id AND active = 1
        """),
        {"group_id": group_id, "co_id": co_id},
    ).fetchone()
    if not row:
        raise HTTPException(
            status_code=400,
            detail="acc_ledger_group_id does not exist for this company",
        )


# 5. POST /ledgers
@router.post("/ledgers")
def create_ledger(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        body = parse_json_body(request)
        co_id = body.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        ledger_name = body.get("ledger_name")
        if not ledger_name:
            raise HTTPException(status_code=400, detail="ledger_name is required")

        acc_ledger_group_id = body.get("acc_ledger_group_id")
        if not acc_ledger_group_id:
            raise HTTPException(status_code=400, detail="acc_ledger_group_id is required")

        _ensure_ledger_group(db, int(acc_ledger_group_id), int(co_id))

        user_id = token_data.get("user_id")

        result = db.execute(
            text("""
                INSERT INTO acc_ledger
                    (co_id, acc_ledger_group_id, ledger_name, ledger_code,
                     ledger_type, party_id, credit_days, credit_limit,
                     opening_balance, opening_balance_type, opening_fy_id,
                     gst_applicable, hsn_sac_code, is_system_ledger,
                     is_related_party, active, updated_by)
                VALUES
                    (:co_id, :acc_ledger_group_id, :ledger_name, :ledger_code,
                     :ledger_type, :party_id, :credit_days, :credit_limit,
                     :opening_balance, :opening_balance_type, :opening_fy_id,
                     :gst_applicable, :hsn_sac_code, 0,
                     :is_related_party, 1, :updated_by)
            """),
            {
                "updated_by": int(user_id),
                "co_id": int(co_id),
                "acc_ledger_group_id": int(acc_ledger_group_id),
                "ledger_name": ledger_name,
                "ledger_code": body.get("ledger_code"),
                "ledger_type": body.get("ledger_type", "G"),
                "party_id": int(body["party_id"]) if body.get("party_id") else None,
                "credit_days": int(body["credit_days"]) if body.get("credit_days") else None,
                "credit_limit": float(body["credit_limit"]) if body.get("credit_limit") else None,
                "opening_balance": float(body["opening_balance"]) if body.get("opening_balance") is not None else None,
                "opening_balance_type": body.get("opening_balance_type"),
                "opening_fy_id": int(body["opening_fy_id"]) if body.get("opening_fy_id") else None,
                "gst_applicable": int(body["gst_applicable"]) if body.get("gst_applicable") is not None else 0,
                "hsn_sac_code": body.get("hsn_sac_code"),
                "is_related_party": int(body["is_related_party"]) if body.get("is_related_party") is not None else 0,
            },
        )
        db.commit()

        return {"data": {"acc_ledger_id": result.lastrowid}}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 6. PUT /ledgers/{ledger_id}
@router.put("/ledgers/{ledger_id}")
def update_ledger(
    ledger_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        body = parse_json_body(request)
        co_id = body.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        if body.get("acc_ledger_group_id"):
            _ensure_ledger_group(db, int(body["acc_ledger_group_id"]), int(co_id))

        db.execute(
            text("""
                UPDATE acc_ledger
                SET acc_ledger_group_id = COALESCE(:acc_ledger_group_id, acc_ledger_group_id),
                    ledger_name = COALESCE(:ledger_name, ledger_name),
                    ledger_code = COALESCE(:ledger_code, ledger_code),
                    ledger_type = COALESCE(:ledger_type, ledger_type),
                    party_id = COALESCE(:party_id, party_id),
                    credit_days = COALESCE(:credit_days, credit_days),
                    credit_limit = COALESCE(:credit_limit, credit_limit),
                    opening_balance = COALESCE(:opening_balance, opening_balance),
                    opening_balance_type = COALESCE(:opening_balance_type, opening_balance_type),
                    opening_fy_id = COALESCE(:opening_fy_id, opening_fy_id),
                    gst_applicable = COALESCE(:gst_applicable, gst_applicable),
                    hsn_sac_code = COALESCE(:hsn_sac_code, hsn_sac_code),
                    is_related_party = COALESCE(:is_related_party, is_related_party),
                    updated_by = :updated_by
                WHERE acc_ledger_id = :ledger_id
                    AND co_id = :co_id
                    AND is_system_ledger = 0
            """),
            {
                "updated_by": int(token_data.get("user_id")),
                "ledger_id": int(ledger_id),
                "co_id": int(co_id),
                "acc_ledger_group_id": int(body["acc_ledger_group_id"]) if body.get("acc_ledger_group_id") else None,
                "ledger_name": body.get("ledger_name"),
                "ledger_code": body.get("ledger_code"),
                "ledger_type": body.get("ledger_type"),
                "party_id": int(body["party_id"]) if body.get("party_id") else None,
                "credit_days": int(body["credit_days"]) if body.get("credit_days") else None,
                "credit_limit": float(body["credit_limit"]) if body.get("credit_limit") else None,
                "opening_balance": float(body["opening_balance"]) if body.get("opening_balance") is not None else None,
                "opening_balance_type": body.get("opening_balance_type"),
                "opening_fy_id": int(body["opening_fy_id"]) if body.get("opening_fy_id") else None,
                "gst_applicable": int(body["gst_applicable"]) if body.get("gst_applicable") is not None else None,
                "hsn_sac_code": body.get("hsn_sac_code"),
                "is_related_party": int(body["is_related_party"]) if body.get("is_related_party") is not None else None,
            },
        )
        db.commit()

        return {"data": {"acc_ledger_id": int(ledger_id), "updated": True}}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 7. GET /parties_dropdown (for ledger party autocomplete)
@router.get("/parties_dropdown")
def get_parties_dropdown(
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

        query = acc_query.get_parties_for_dropdown()
        rows = db.execute(
            query,
            {"co_id": int(co_id), "search": search_param}
        ).fetchall()
        data = [dict(r._mapping) for r in rows]
        return {"data": data}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 8. GET /voucher_types
@router.get("/voucher_types")
def get_voucher_types(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        query = acc_query.get_voucher_types(int(co_id))
        rows = db.execute(query, {"co_id": int(co_id)}).fetchall()
        data = [dict(r._mapping) for r in rows]
        return {"data": data}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 8b. POST /voucher_types — manual setup for companies that never ran activate_company
@router.post("/voucher_types")
def create_voucher_type(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        body = parse_json_body(request)

        co_id = body.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        type_name = (body.get("voucher_type_name") or body.get("type_name") or "").strip()
        if not type_name:
            raise HTTPException(status_code=400, detail="voucher_type_name is required")

        type_category = (body.get("type_category") or "").strip().upper()
        if not type_category:
            raise HTTPException(status_code=400, detail="type_category is required")
        if type_category not in VOUCHER_CATEGORIES:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid type_category. Must be one of: {', '.join(VOUCHER_CATEGORIES)}",
            )

        cat_info = VOUCHER_CATEGORIES[type_category]
        # Seeder row shape: type_code == prefix == category code, unless caller overrides prefix.
        prefix = (body.get("prefix") or cat_info["code"]).strip()
        auto_numbering = int(body["auto_numbering"]) if body.get("auto_numbering") is not None else 1

        # No unique key on acc_voucher_type; the seeder writes one row per category
        # with a distinct display name, so both are treated as unique per company.
        dup = db.execute(
            text("""
                SELECT type_category FROM acc_voucher_type
                WHERE co_id = :co_id AND active = 1
                    AND (type_category = :type_category OR type_name = :type_name)
                LIMIT 1
            """),
            {"co_id": int(co_id), "type_category": type_category, "type_name": type_name},
        ).fetchone()
        if dup:
            clash = "type_category" if dup._mapping["type_category"] == type_category else "type_name"
            raise HTTPException(
                status_code=400,
                detail=f"A voucher type with this {clash} already exists for this company",
            )

        row = {
            "co_id": int(co_id),
            "type_name": type_name,
            "type_code": cat_info["code"],
            "type_category": type_category,
            "auto_numbering": auto_numbering,
            "prefix": prefix,
            "requires_bank_cash": 1 if cat_info["requires_bank_cash"] else 0,
            "is_system_type": 0,
        }

        result = db.execute(
            text("""
                INSERT INTO acc_voucher_type
                    (co_id, type_name, type_code, type_category, auto_numbering,
                     prefix, requires_bank_cash, is_system_type, active, updated_by)
                VALUES
                    (:co_id, :type_name, :type_code, :type_category, :auto_numbering,
                     :prefix, :requires_bank_cash, :is_system_type, 1, :updated_by)
            """),
            {**row, "updated_by": int(token_data.get("user_id"))},
        )
        db.commit()

        return {"data": {"acc_voucher_type_id": result.lastrowid, **row}}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 8. GET /financial_years
@router.get("/financial_years")
def get_financial_years(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        query = acc_query.get_financial_years(int(co_id))
        rows = db.execute(query, {"co_id": int(co_id)}).fetchall()
        data = [dict(r._mapping) for r in rows]
        return {"data": data}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 9. POST /financial_years
@router.post("/financial_years")
def create_financial_year(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        body = parse_json_body(request)
        co_id = body.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        fy_start = body.get("fy_start")
        fy_end = body.get("fy_end")
        fy_label = body.get("fy_label")

        if not fy_start or not fy_end or not fy_label:
            raise HTTPException(
                status_code=400,
                detail="fy_start, fy_end, and fy_label are required",
            )

        # Extract user_id from token
        user_id = token_data.get("user_id")
        if not user_id:
            raise HTTPException(status_code=401, detail="User ID not found in token")

        # Insert financial year
        result = db.execute(
            text("""
                INSERT INTO acc_financial_year
                    (co_id, fy_start, fy_end, fy_label, is_active, is_locked, updated_by)
                VALUES
                    (:co_id, :fy_start, :fy_end, :fy_label, 1, 0, :updated_by)
            """),
            {
                "co_id": int(co_id),
                "fy_start": fy_start,
                "fy_end": fy_end,
                "fy_label": fy_label,
                "updated_by": int(user_id),
            },
        )
        fy_id = result.lastrowid

        # Create 12 period_lock rows
        fy_start_dt = datetime.strptime(fy_start, "%Y-%m-%d").date()
        for month_offset in range(12):
            period_month = ((fy_start_dt.month - 1 + month_offset) % 12) + 1
            period_year = fy_start_dt.year + ((fy_start_dt.month - 1 + month_offset) // 12)

            # Calculate period start and end dates
            period_start = date(period_year, period_month, 1)
            if period_month == 12:
                period_end = date(period_year + 1, 1, 1)
            else:
                period_end = date(period_year, period_month + 1, 1)
            # Last day of the month
            period_end = date(period_end.year, period_end.month, period_end.day) - timedelta(days=1)

            db.execute(
                text("""
                    INSERT INTO acc_period_lock
                        (acc_financial_year_id, period_month, period_start,
                         period_end, is_locked, updated_by)
                    VALUES
                        (:fy_id, :period_month, :period_start,
                         :period_end, 0, :updated_by)
                """),
                {
                    "fy_id": int(fy_id),
                    "period_month": month_offset + 1,
                    "period_start": period_start.isoformat(),
                    "period_end": period_end.isoformat(),
                    "updated_by": int(user_id),
                },
            )

        db.commit()

        return {"data": {"acc_financial_year_id": fy_id, "periods_created": 12}}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 10. GET /account_determinations
@router.get("/account_determinations")
def get_account_determinations(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        query = acc_query.get_account_determinations(int(co_id))
        rows = db.execute(query, {"co_id": int(co_id)}).fetchall()
        data = [dict(r._mapping) for r in rows]
        return {"data": data}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 11. PUT /account_determinations
@router.put("/account_determinations")
def update_account_determinations(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        body = parse_json_body(request)
        rules = body if isinstance(body, list) else body.get("rules", [])

        if not rules:
            raise HTTPException(status_code=400, detail="No rules provided")

        for rule in rules:
            acc_account_determination_id = rule.get("acc_account_determination_id")
            acc_ledger_id = rule.get("acc_ledger_id")

            if not acc_account_determination_id:
                raise HTTPException(
                    status_code=400,
                    detail="acc_account_determination_id is required for each rule",
                )

            db.execute(
                text("""
                    UPDATE acc_account_determination
                    SET acc_ledger_id = :acc_ledger_id
                    WHERE acc_account_determination_id = :id
                """),
                {
                    "id": int(acc_account_determination_id),
                    "acc_ledger_id": int(acc_ledger_id) if acc_ledger_id else None,
                },
            )

        db.commit()

        return {"data": {"updated": len(rules)}}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# VOUCHER OPERATIONS
# =============================================================================

# 12. GET /vouchers
@router.get("/vouchers")
def get_vouchers(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        branch_id = request.query_params.get("branch_id")
        voucher_type_id = request.query_params.get("voucher_type_id")
        from_date = request.query_params.get("from_date")
        to_date = request.query_params.get("to_date")
        party_id = request.query_params.get("party_id")
        source_doc_type = request.query_params.get("source_doc_type")
        status_id = request.query_params.get("status_id")
        search = request.query_params.get("search")
        page = int(request.query_params.get("page", 1))
        limit = int(request.query_params.get("limit", 50))
        offset = (page - 1) * limit

        filter_params = {
            "co_id": int(co_id),
            "branch_id": int(branch_id) if branch_id else None,
            "voucher_type_id": int(voucher_type_id) if voucher_type_id else None,
            "from_date": from_date if from_date else None,
            "to_date": to_date if to_date else None,
            "party_id": int(party_id) if party_id else None,
            "source_doc_type": source_doc_type if source_doc_type else None,
            "status_id": int(status_id) if status_id else None,
            "search": f"%{search.strip()}%" if search and search.strip() else None,
        }

        query = acc_query.get_vouchers_list(int(co_id))
        rows = db.execute(query, {
            **filter_params,
            "limit": limit,
            "offset": offset,
        }).fetchall()
        data = [dict(r._mapping) for r in rows]

        total = db.execute(
            acc_query.get_vouchers_count(), filter_params
        ).scalar() or 0

        return {"data": data, "total": int(total), "page": page, "limit": limit}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 13. GET /vouchers/{voucher_id}
@router.get("/vouchers/{voucher_id}")
def get_voucher_detail(
    voucher_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        # Header
        header_query = acc_query.get_voucher_detail(int(voucher_id))
        header_row = db.execute(
            header_query, {"voucher_id": int(voucher_id)}
        ).fetchone()

        if not header_row:
            raise HTTPException(status_code=404, detail="Voucher not found")

        header = dict(header_row._mapping)

        # Lines
        lines_query = acc_query.get_voucher_lines(int(voucher_id))
        lines_rows = db.execute(
            lines_query, {"voucher_id": int(voucher_id)}
        ).fetchall()
        lines = [dict(r._mapping) for r in lines_rows]

        # GST
        gst_query = acc_query.get_voucher_gst(int(voucher_id))
        gst_rows = db.execute(
            gst_query, {"voucher_id": int(voucher_id)}
        ).fetchall()
        gst = [dict(r._mapping) for r in gst_rows]

        # Bill References
        bill_refs_query = acc_query.get_voucher_bill_refs(int(voucher_id))
        bill_refs_rows = db.execute(
            bill_refs_query, {"voucher_id": int(voucher_id)}
        ).fetchall()
        bill_refs = [dict(r._mapping) for r in bill_refs_rows]

        header["lines"] = lines
        header["gst"] = gst
        header["bill_refs"] = bill_refs

        return {"data": header}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 14. POST /vouchers
@router.post("/vouchers")
def create_voucher(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Create a manual voucher (born Draft).

    Body: {co_id, branch_id?, voucher_date,
           acc_voucher_type_id? | type_category?,
           party_id?, ref_no?, ref_date?, narration?,
           lines: [{acc_ledger_id, debit_amount, credit_amount,
                    narration?, party_id?}],
           gst_lines?: [...],
           bill_refs?: [{ref_type, bill_no, bill_date?, due_date?, amount}]}
    """
    try:
        body = parse_json_body(request)
        co_id = body.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        user_id = token_data.get("user_id")

        result = voucher_service.create_manual_voucher(db, body, int(user_id))
        return {"data": result}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 15. PUT /vouchers/{voucher_id}
@router.put("/vouchers/{voucher_id}")
def update_voucher(
    voucher_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Update a Draft (21) or Open (1) voucher (same body contract as
    POST /vouchers; lines/gst_lines/bill_refs are fully replaced)."""
    try:
        body = parse_json_body(request)
        user_id = token_data.get("user_id")

        result = voucher_service.update_draft_voucher(
            db, int(voucher_id), body, int(user_id)
        )
        return {"data": result}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 16. POST /vouchers/{voucher_id}/open
@router.post("/vouchers/{voucher_id}/open")
def open_voucher(
    voucher_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        user_id = token_data.get("user_id")
        result = voucher_service.open_voucher(db, int(voucher_id), int(user_id))
        return {"data": result}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 17. POST /vouchers/{voucher_id}/cancel
@router.post("/vouchers/{voucher_id}/cancel")
def cancel_voucher(
    voucher_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        user_id = token_data.get("user_id")
        result = voucher_service.cancel_voucher(db, int(voucher_id), int(user_id))
        return {"data": result}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 18. POST /vouchers/{voucher_id}/send_for_approval
@router.post("/vouchers/{voucher_id}/send_for_approval")
def send_voucher_for_approval(
    voucher_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        user_id = token_data.get("user_id")
        result = voucher_service.send_for_approval(
            db, int(voucher_id), int(user_id)
        )
        return {"data": result}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 19. POST /vouchers/{voucher_id}/approve
@router.post("/vouchers/{voucher_id}/approve")
def approve_voucher(
    voucher_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Approve via the shared approval framework. Optional body:
    {menu_id?, remarks?} — menu_id overrides the APPROVAL_MENU_MAP lookup."""
    try:
        try:
            body = parse_json_body(request) or {}
        except Exception:
            body = {}

        user_id = token_data.get("user_id")
        menu_id = body.get("menu_id")
        result = voucher_service.approve_voucher(
            db, int(voucher_id), int(user_id),
            menu_id=int(menu_id) if menu_id else None,
            remarks=body.get("remarks"),
        )
        return {"data": result}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 20. POST /vouchers/{voucher_id}/reject
@router.post("/vouchers/{voucher_id}/reject")
def reject_voucher(
    voucher_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        body = parse_json_body(request)
        reason = body.get("reason", "")
        user_id = token_data.get("user_id")

        result = voucher_service.reject_voucher(
            db, int(voucher_id), int(user_id), reason
        )
        return {"data": result}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 21. POST /vouchers/{voucher_id}/reopen
@router.post("/vouchers/{voucher_id}/reopen")
def reopen_voucher(
    voucher_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        user_id = token_data.get("user_id")
        result = voucher_service.reopen_voucher(
            db, int(voucher_id), int(user_id)
        )
        return {"data": result}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 22. POST /vouchers/{voucher_id}/reverse
@router.post("/vouchers/{voucher_id}/reverse")
def reverse_voucher(
    voucher_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        body = parse_json_body(request)
        narration = body.get("narration")
        user_id = token_data.get("user_id")

        result = voucher_service.reverse_voucher(
            db, int(voucher_id), int(user_id), narration
        )
        return {"data": result}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 23. POST /vouchers/{voucher_id}/settle_bills
@router.post("/vouchers/{voucher_id}/settle_bills")
def settle_bills(
    voucher_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        body = parse_json_body(request)
        settlements = body.get("settlements", [])

        if not settlements:
            raise HTTPException(status_code=400, detail="settlements list is required")

        user_id = token_data.get("user_id")

        result = voucher_service.settle_bills(
            db, int(voucher_id), settlements, int(user_id)
        )
        return {"data": result}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# REPORTS
# =============================================================================

# 24. GET /reports/trial_balance
@router.get("/reports/trial_balance")
def trial_balance(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        from_date = request.query_params.get("from_date")
        to_date = request.query_params.get("to_date")
        branch_id = request.query_params.get("branch_id")

        if not from_date or not to_date:
            raise HTTPException(status_code=400, detail="from_date and to_date are required")

        query = report_query.get_trial_balance()
        rows = db.execute(query, {
            "co_id": int(co_id),
            "from_date": from_date,
            "to_date": to_date,
            "branch_id": int(branch_id) if branch_id else None,
        }).fetchall()
        data = [dict(r._mapping) for r in rows]
        return {"data": data}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 25. GET /reports/profit_loss
@router.get("/reports/profit_loss")
def profit_loss(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        from_date = request.query_params.get("from_date")
        to_date = request.query_params.get("to_date")
        branch_id = request.query_params.get("branch_id")

        if not from_date or not to_date:
            raise HTTPException(status_code=400, detail="from_date and to_date are required")

        query = report_query.get_profit_loss()
        rows = db.execute(query, {
            "co_id": int(co_id),
            "from_date": from_date,
            "to_date": to_date,
            "branch_id": int(branch_id) if branch_id else None,
        }).fetchall()
        data = [dict(r._mapping) for r in rows]
        return {"data": data}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 26. GET /reports/balance_sheet
@router.get("/reports/balance_sheet")
def balance_sheet(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Balance sheet. Accepts either as_on_date (cumulative up to that date)
    or an explicit from_date + to_date window."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        as_on_date = request.query_params.get("as_on_date")
        from_date = request.query_params.get("from_date")
        to_date = request.query_params.get("to_date")
        branch_id = request.query_params.get("branch_id")

        if as_on_date:
            from_date = "1900-01-01"
            to_date = as_on_date
        elif not from_date or not to_date:
            raise HTTPException(
                status_code=400,
                detail="as_on_date or (from_date and to_date) is required",
            )

        query = report_query.get_balance_sheet()
        rows = db.execute(query, {
            "co_id": int(co_id),
            "from_date": from_date,
            "to_date": to_date,
            "branch_id": int(branch_id) if branch_id else None,
        }).fetchall()
        data = [dict(r._mapping) for r in rows]
        return {"data": data}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 27. GET /reports/ledger_report
@router.get("/reports/ledger_report")
def ledger_report(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        ledger_id = request.query_params.get("ledger_id")
        if not ledger_id:
            raise HTTPException(status_code=400, detail="ledger_id is required")

        from_date = request.query_params.get("from_date")
        to_date = request.query_params.get("to_date")
        branch_id = request.query_params.get("branch_id")

        if not from_date or not to_date:
            raise HTTPException(status_code=400, detail="from_date and to_date are required")

        query = report_query.get_ledger_report()
        rows = db.execute(query, {
            "ledger_id": int(ledger_id),
            "from_date": from_date,
            "to_date": to_date,
            "branch_id": int(branch_id) if branch_id else None,
        }).fetchall()
        data = [dict(r._mapping) for r in rows]
        return {"data": data}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 28. GET /reports/day_book
@router.get("/reports/day_book")
def day_book(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        from_date = request.query_params.get("from_date")
        to_date = request.query_params.get("to_date")
        branch_id = request.query_params.get("branch_id")
        voucher_type_id = request.query_params.get("voucher_type_id")

        if not from_date or not to_date:
            raise HTTPException(status_code=400, detail="from_date and to_date are required")

        query = report_query.get_day_book()
        rows = db.execute(query, {
            "co_id": int(co_id),
            "from_date": from_date,
            "to_date": to_date,
            "branch_id": int(branch_id) if branch_id else None,
            "voucher_type_id": int(voucher_type_id) if voucher_type_id else None,
        }).fetchall()
        data = [dict(r._mapping) for r in rows]
        return {"data": data}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 29. GET /reports/cash_book
@router.get("/reports/cash_book")
def cash_book(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        from_date = request.query_params.get("from_date")
        to_date = request.query_params.get("to_date")
        branch_id = request.query_params.get("branch_id")

        if not from_date or not to_date:
            raise HTTPException(status_code=400, detail="from_date and to_date are required")

        query = report_query.get_cash_book()
        rows = db.execute(query, {
            "co_id": int(co_id),
            "from_date": from_date,
            "to_date": to_date,
            "branch_id": int(branch_id) if branch_id else None,
        }).fetchall()
        data = [dict(r._mapping) for r in rows]
        return {"data": data}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 30. GET /reports/party_outstanding
@router.get("/reports/party_outstanding")
def party_outstanding(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        party_type = request.query_params.get("party_type")
        if party_type:
            party_type = party_type.upper()
            if party_type not in ("DEBTOR", "CREDITOR"):
                raise HTTPException(
                    status_code=400,
                    detail="party_type must be 'DEBTOR' or 'CREDITOR'",
                )
        branch_id = request.query_params.get("branch_id")

        query = report_query.get_party_outstanding()
        rows = db.execute(query, {
            "co_id": int(co_id),
            "party_type": party_type if party_type else None,
            "branch_id": int(branch_id) if branch_id else None,
        }).fetchall()
        data = [dict(r._mapping) for r in rows]
        return {"data": data}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Fallback ageing buckets when no acc_ageing_slab rows are configured
_DEFAULT_AGEING_SLABS = [
    {"slab_name": "0-30", "from_days": 0, "to_days": 30, "sequence_no": 1},
    {"slab_name": "31-60", "from_days": 31, "to_days": 60, "sequence_no": 2},
    {"slab_name": "61-90", "from_days": 61, "to_days": 90, "sequence_no": 3},
    {"slab_name": "91-180", "from_days": 91, "to_days": 180, "sequence_no": 4},
    {"slab_name": "181+", "from_days": 181, "to_days": None, "sequence_no": 5},
]


# 31. GET /reports/ageing_analysis
@router.get("/reports/ageing_analysis")
def ageing_analysis(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """AP/AR ageing bucketed per acc_ageing_slab (fallback defaults when a
    company has no slabs configured). Returns {"data": [...], "slabs": [...]}.
    Amounts not yet due (days < 0) accumulate in each party's not_due field.
    """
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        party_type = request.query_params.get("party_type")
        if party_type:
            party_type = party_type.upper()
            if party_type not in ("DEBTOR", "CREDITOR"):
                raise HTTPException(
                    status_code=400,
                    detail="party_type must be 'DEBTOR' or 'CREDITOR'",
                )
        branch_id = request.query_params.get("branch_id")

        # 1. Slabs for this company (fallback to defaults)
        slab_rows = db.execute(
            text("""
                SELECT acc_ageing_slab_id, slab_name, from_days, to_days,
                       sequence_no
                FROM acc_ageing_slab
                WHERE co_id = :co_id AND active = 1
                ORDER BY sequence_no, from_days
            """),
            {"co_id": int(co_id)},
        ).fetchall()
        slabs = (
            [dict(r._mapping) for r in slab_rows]
            if slab_rows else list(_DEFAULT_AGEING_SLABS)
        )

        # 2. Flat outstanding rows with days
        rows = db.execute(report_query.get_ageing_rows(), {
            "co_id": int(co_id),
            "party_type": party_type if party_type else None,
            "branch_id": int(branch_id) if branch_id else None,
        }).fetchall()

        # 3. Bucket per party in Python
        parties: dict = {}
        for r in rows:
            row = dict(r._mapping)
            key = row.get("party_id")
            if key not in parties:
                parties[key] = {
                    "party_id": key,
                    "party_name": row.get("party_name"),
                    "party_type": row.get("party_type"),
                    "not_due": 0.0,
                    "total_outstanding": 0.0,
                    "buckets": {s["slab_name"]: 0.0 for s in slabs},
                }
            entry = parties[key]
            pending = float(row.get("pending_amount") or 0)
            days = row.get("days")
            days = int(days) if days is not None else 0
            entry["total_outstanding"] = round(
                entry["total_outstanding"] + pending, 2
            )
            placed = False
            for slab in slabs:
                lo = slab["from_days"]
                hi = slab["to_days"]
                if days >= lo and (hi is None or days <= hi):
                    entry["buckets"][slab["slab_name"]] = round(
                        entry["buckets"][slab["slab_name"]] + pending, 2
                    )
                    placed = True
                    break
            if not placed:
                # Below the first slab (e.g., not yet due)
                entry["not_due"] = round(entry["not_due"] + pending, 2)

        data = sorted(
            parties.values(),
            key=lambda p: p["total_outstanding"],
            reverse=True,
        )
        return {"data": data, "slabs": slabs}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 32. GET /reports/gst_summary
@router.get("/reports/gst_summary")
def gst_summary(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        from_date = request.query_params.get("from_date")
        to_date = request.query_params.get("to_date")
        branch_gstin = request.query_params.get("branch_gstin")

        if not from_date or not to_date:
            raise HTTPException(status_code=400, detail="from_date and to_date are required")

        query = report_query.get_gst_summary()
        rows = db.execute(query, {
            "co_id": int(co_id),
            "from_date": from_date,
            "to_date": to_date,
            "branch_gstin": branch_gstin if branch_gstin else None,
        }).fetchall()
        data = [dict(r._mapping) for r in rows]
        return {"data": data}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# OPENING BALANCE
# =============================================================================

# 33. POST /opening_bills
@router.post("/opening_bills")
def import_opening_bills(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Import opening outstanding bills.

    Body: {co_id, rows: [{acc_ledger_id? | party_id?, bill_no, bill_date?,
           due_date?, bill_type: 'D'|'C', amount}]}
    When only party_id is given, the party's ledger is resolved from
    acc_ledger. Rows are inserted with pending_amount = amount, status OPEN,
    against the company's active financial year.
    """
    try:
        body = parse_json_body(request)
        if not isinstance(body, dict):
            raise HTTPException(
                status_code=400,
                detail="Body must be an object: {co_id, rows: [...]}",
            )

        co_id = body.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        co_id = int(co_id)

        rows = body.get("rows") or body.get("bills") or []
        if not rows:
            raise HTTPException(status_code=400, detail="rows list is required")

        user_id = token_data.get("user_id")

        # Resolve the company's active financial year
        fy_row = db.execute(
            text("""
                SELECT acc_financial_year_id
                FROM acc_financial_year
                WHERE co_id = :co_id AND is_active = 1
                ORDER BY fy_start DESC
                LIMIT 1
            """),
            {"co_id": co_id},
        ).fetchone()
        if not fy_row:
            raise HTTPException(
                status_code=400,
                detail="No active financial year found for this company.",
            )
        fy_id = int(fy_row._mapping["acc_financial_year_id"])

        inserted_count = 0
        for idx, bill in enumerate(rows, start=1):
            bill_type = (bill.get("bill_type") or "").upper()
            if bill_type not in ("D", "C"):
                raise HTTPException(
                    status_code=400,
                    detail=f"Row {idx}: bill_type must be 'D' or 'C'.",
                )

            try:
                amount = round(float(bill.get("amount")), 2)
            except (TypeError, ValueError):
                raise HTTPException(
                    status_code=400, detail=f"Row {idx}: invalid amount."
                )
            if amount <= 0:
                raise HTTPException(
                    status_code=400,
                    detail=f"Row {idx}: amount must be greater than zero.",
                )

            # Resolve the ledger: explicit acc_ledger_id or via the party
            acc_ledger_id = bill.get("acc_ledger_id")
            if acc_ledger_id:
                acc_ledger_id = int(acc_ledger_id)
            elif bill.get("party_id"):
                ledger_row = db.execute(
                    acc_query.get_ledger_by_party(),
                    {"co_id": co_id, "party_id": int(bill["party_id"])},
                ).fetchone()
                if not ledger_row:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            f"Row {idx}: no ledger found for party "
                            f"{bill['party_id']}."
                        ),
                    )
                acc_ledger_id = int(ledger_row._mapping["acc_ledger_id"])
            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"Row {idx}: acc_ledger_id or party_id is required.",
                )

            db.execute(
                acc_query.insert_opening_bill(),
                {
                    "co_id": co_id,
                    "acc_ledger_id": acc_ledger_id,
                    "acc_financial_year_id": fy_id,
                    "bill_no": bill.get("bill_no"),
                    "bill_date": bill.get("bill_date"),
                    "due_date": bill.get("due_date"),
                    "bill_type": bill_type,
                    "amount": amount,
                    "pending_amount": amount,
                    "status": "OPEN",
                    "updated_by": int(user_id),
                },
            )
            inserted_count += 1

        db.commit()

        return {"data": {"inserted": inserted_count}}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# COMPANY SETTINGS
# =============================================================================

_SETTINGS_DEFAULTS = {
    "acc_company_settings_id": None,
    "posting_mode_purchase": "OFF",
    "posting_mode_jute_purchase": "OFF",
    "posting_mode_sales": "OFF",
    "posting_mode_drcr": "OFF",
    "due_date_rule": "PO_CREDIT_DAYS",
    "default_credit_days": None,
    "enable_tds": 1,
    "expense_approval_required": 0,
}

_POSTING_MODE_FIELDS = (
    "posting_mode_purchase",
    "posting_mode_jute_purchase",
    "posting_mode_sales",
    "posting_mode_drcr",
)


# 34. GET /company_settings
@router.get("/company_settings")
def get_company_settings(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Per-company accounting behaviour. Returns defaults (with
    acc_company_settings_id null) when no row exists yet — does not insert."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        row = db.execute(
            text("""
                SELECT acc_company_settings_id, co_id,
                       posting_mode_purchase, posting_mode_jute_purchase,
                       posting_mode_sales, posting_mode_drcr,
                       due_date_rule, default_credit_days,
                       enable_tds, expense_approval_required
                FROM acc_company_settings
                WHERE co_id = :co_id AND active = 1
                LIMIT 1
            """),
            {"co_id": int(co_id)},
        ).fetchone()

        if row:
            return {"data": dict(row._mapping)}

        defaults = dict(_SETTINGS_DEFAULTS)
        defaults["co_id"] = int(co_id)
        return {"data": defaults}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 35. PUT /company_settings
@router.put("/company_settings")
def update_company_settings(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Upsert acc_company_settings by co_id. Posting modes must be in
    constants.POSTING_MODES; due_date_rule must be in constants.DUE_DATE_RULES."""
    try:
        body = parse_json_body(request)
        co_id = body.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        co_id = int(co_id)

        user_id = token_data.get("user_id")

        existing = db.execute(
            text("""
                SELECT acc_company_settings_id,
                       posting_mode_purchase, posting_mode_jute_purchase,
                       posting_mode_sales, posting_mode_drcr,
                       due_date_rule, default_credit_days,
                       enable_tds, expense_approval_required
                FROM acc_company_settings
                WHERE co_id = :co_id AND active = 1
                LIMIT 1
            """),
            {"co_id": co_id},
        ).fetchone()

        current = dict(existing._mapping) if existing else dict(_SETTINGS_DEFAULTS)

        # Merge incoming values over current/default values, validating enums
        values = {}
        for field in _POSTING_MODE_FIELDS:
            mode = body.get(field, current.get(field) or "OFF")
            mode = str(mode).upper()
            if mode not in POSTING_MODES:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"{field} must be one of "
                        f"{sorted(POSTING_MODES.keys())}"
                    ),
                )
            values[field] = mode

        due_date_rule = str(
            body.get("due_date_rule", current.get("due_date_rule")
                     or "PO_CREDIT_DAYS")
        ).upper()
        if due_date_rule not in DUE_DATE_RULES:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"due_date_rule must be one of "
                    f"{sorted(DUE_DATE_RULES.keys())}"
                ),
            )
        values["due_date_rule"] = due_date_rule

        default_credit_days = body.get(
            "default_credit_days", current.get("default_credit_days")
        )
        values["default_credit_days"] = (
            int(default_credit_days) if default_credit_days not in (None, "")
            else None
        )

        enable_tds = body.get("enable_tds", current.get("enable_tds"))
        values["enable_tds"] = int(enable_tds) if enable_tds is not None else 1

        expense_approval_required = body.get(
            "expense_approval_required",
            current.get("expense_approval_required"),
        )
        values["expense_approval_required"] = (
            int(expense_approval_required)
            if expense_approval_required is not None else 0
        )

        if existing:
            settings_id = int(existing._mapping["acc_company_settings_id"])
            db.execute(
                text("""
                    UPDATE acc_company_settings
                    SET posting_mode_purchase = :posting_mode_purchase,
                        posting_mode_jute_purchase = :posting_mode_jute_purchase,
                        posting_mode_sales = :posting_mode_sales,
                        posting_mode_drcr = :posting_mode_drcr,
                        due_date_rule = :due_date_rule,
                        default_credit_days = :default_credit_days,
                        enable_tds = :enable_tds,
                        expense_approval_required = :expense_approval_required,
                        updated_by = :updated_by,
                        updated_date_time = CURRENT_TIMESTAMP
                    WHERE acc_company_settings_id = :settings_id
                """),
                {**values, "settings_id": settings_id, "updated_by": int(user_id)},
            )
        else:
            result = db.execute(
                text("""
                    INSERT INTO acc_company_settings
                        (co_id, posting_mode_purchase,
                         posting_mode_jute_purchase, posting_mode_sales,
                         posting_mode_drcr, due_date_rule,
                         default_credit_days, enable_tds,
                         expense_approval_required, active, updated_by)
                    VALUES
                        (:co_id, :posting_mode_purchase,
                         :posting_mode_jute_purchase, :posting_mode_sales,
                         :posting_mode_drcr, :due_date_rule,
                         :default_credit_days, :enable_tds,
                         :expense_approval_required, 1, :updated_by)
                """),
                {**values, "co_id": co_id, "updated_by": int(user_id)},
            )
            settings_id = result.lastrowid

        db.commit()
        return {"data": {"acc_company_settings_id": settings_id,
                         "co_id": co_id, **values}}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# POSTING QUEUE
# =============================================================================

# 36. GET /posting_queue
@router.get("/posting_queue")
def get_posting_queue(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """List auto-posting queue rows for a company, newest first.
    Optional filter: status (PENDING/POSTED/DRAFTED/SKIPPED/FAILED)."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        status = request.query_params.get("status")
        if status:
            status = status.upper()
            if status not in POSTING_QUEUE_STATUSES:
                raise HTTPException(
                    status_code=400,
                    detail=f"status must be one of {POSTING_QUEUE_STATUSES}",
                )

        limit = int(request.query_params.get("limit", 100))

        rows = db.execute(
            text("""
                SELECT apq.acc_posting_queue_id, apq.co_id,
                       apq.source_doc_type, apq.source_doc_id,
                       apq.status, apq.acc_voucher_id,
                       av.voucher_no,
                       apq.attempt_count, apq.last_error,
                       apq.updated_date_time
                FROM acc_posting_queue apq
                LEFT JOIN acc_voucher av
                    ON av.acc_voucher_id = apq.acc_voucher_id
                WHERE apq.co_id = :co_id
                    AND apq.active = 1
                    AND (:status IS NULL OR apq.status = :status)
                ORDER BY apq.acc_posting_queue_id DESC
                LIMIT :limit
            """),
            {
                "co_id": int(co_id),
                "status": status if status else None,
                "limit": limit,
            },
        ).fetchall()
        data = [dict(r._mapping) for r in rows]
        return {"data": data}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 37. POST /posting_queue/{queue_id}/retry
@router.post("/posting_queue/{queue_id}/retry")
def retry_posting_queue(
    queue_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Re-run auto-posting for a queue row's source document."""
    try:
        row = db.execute(
            text("""
                SELECT acc_posting_queue_id, co_id, source_doc_type,
                       source_doc_id, status
                FROM acc_posting_queue
                WHERE acc_posting_queue_id = :queue_id
                    AND active = 1
            """),
            {"queue_id": int(queue_id)},
        ).fetchone()
        if not row:
            raise HTTPException(
                status_code=404, detail="Posting queue row not found"
            )
        queue_row = dict(row._mapping)

        user_id = token_data.get("user_id")

        # Lazy import: posting_service owns the posting pipeline; importing at
        # module scope would create a circular import at app startup.
        from src.accounting.posting_service import post_document

        result = post_document(
            db,
            queue_row["source_doc_type"],
            int(queue_row["source_doc_id"]),
            int(user_id),
        )
        return {"data": result}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
