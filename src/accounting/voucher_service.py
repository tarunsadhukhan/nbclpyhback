"""Voucher service — creation, validation, numbering, lifecycle, reversal,
and bill settlement for manual accounting vouchers.

All SQL columns in this module are verified against src/accounting/models.py
(the single source of truth for the accounting schema).
"""
import logging

from fastapi import HTTPException
from sqlalchemy import text, bindparam
from sqlalchemy.orm import Session

from src.common.utils import now_ist
from src.common.approval_utils import process_approval
from src.accounting import query as acc_query
from src.accounting.constants import (
    ACC_STATUS_IDS,
    APPROVAL_MENU_MAP,
    BILL_REF_TYPES,
    WARNING_CODES,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Status IDs (mirrors acc workflow statuses)
# ---------------------------------------------------------------------------
STATUS_DRAFT = ACC_STATUS_IDS["DRAFT"]                        # 21
STATUS_OPEN = ACC_STATUS_IDS["OPEN"]                          # 1
STATUS_PENDING_APPROVAL = ACC_STATUS_IDS["PENDING_APPROVAL"]  # 20
STATUS_APPROVED = ACC_STATUS_IDS["APPROVED"]                  # 3
STATUS_REJECTED = ACC_STATUS_IDS["REJECTED"]                  # 4
STATUS_CANCELLED = ACC_STATUS_IDS["CANCELLED"]                # 6

# Voucher type categories that require at least one Bank/Cash ledger line
BANK_CASH_REQUIRED_TYPES = {"PAYMENT", "RECEIPT", "CONTRA"}

# Rupee tolerance for DR/CR balance and settlement checks (2dp)
AMOUNT_TOLERANCE = 0.01


# =============================================================================
# INTERNAL HELPERS
# =============================================================================

def _r2(value) -> float:
    """Round to 2 decimals (financial comparison helper)."""
    return round(float(value or 0), 2)


def _get_voucher_header(db: Session, voucher_id: int) -> dict:
    """Fetch a voucher header (with type category) or raise 404."""
    row = db.execute(
        text("""
            SELECT av.acc_voucher_id, av.co_id, av.branch_id,
                   av.acc_voucher_type_id, av.acc_financial_year_id,
                   av.voucher_no, av.voucher_date, av.party_id,
                   av.ref_no, av.ref_date, av.narration, av.total_amount,
                   av.source_doc_type, av.source_doc_id,
                   av.is_auto_posted, av.is_reversed,
                   av.reversed_by_voucher_id, av.reversal_of_voucher_id,
                   av.status_id, av.approval_level,
                   av.approved_by, av.approved_date_time,
                   avt.type_category, avt.type_code, avt.prefix AS type_prefix
            FROM acc_voucher av
            LEFT JOIN acc_voucher_type avt
                ON avt.acc_voucher_type_id = av.acc_voucher_type_id
            WHERE av.acc_voucher_id = :voucher_id
              AND av.active = 1
        """),
        {"voucher_id": int(voucher_id)},
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Voucher not found")
    return dict(row._mapping)


def _resolve_voucher_type(db: Session, co_id: int, payload: dict) -> dict:
    """Resolve the voucher type row from acc_voucher_type_id (preferred) or
    type_category. Raises 400 when unresolvable."""
    voucher_type_id = payload.get("acc_voucher_type_id")
    type_category = (payload.get("type_category") or "").strip().upper()

    if voucher_type_id:
        row = db.execute(
            text("""
                SELECT acc_voucher_type_id, type_name, type_code,
                       type_category, prefix, requires_bank_cash
                FROM acc_voucher_type
                WHERE acc_voucher_type_id = :voucher_type_id
                  AND co_id = :co_id
                  AND active = 1
            """),
            {"voucher_type_id": int(voucher_type_id), "co_id": int(co_id)},
        ).fetchone()
        if not row:
            raise HTTPException(
                status_code=400,
                detail=f"Voucher type {voucher_type_id} not found for this company.",
            )
        return dict(row._mapping)

    if type_category:
        row = db.execute(
            text("""
                SELECT acc_voucher_type_id, type_name, type_code,
                       type_category, prefix, requires_bank_cash
                FROM acc_voucher_type
                WHERE co_id = :co_id
                  AND type_category = :type_category
                  AND active = 1
                LIMIT 1
            """),
            {"co_id": int(co_id), "type_category": type_category},
        ).fetchone()
        if not row:
            raise HTTPException(
                status_code=400,
                detail=f"Voucher type '{type_category}' not found for this company.",
            )
        return dict(row._mapping)

    raise HTTPException(
        status_code=400,
        detail="acc_voucher_type_id or type_category is required.",
    )


def _resolve_financial_year(db: Session, co_id: int, voucher_date) -> dict:
    """Return the financial year row containing voucher_date, ensuring it is
    not locked. Raises 400 if none exists or it is locked."""
    row = db.execute(
        text("""
            SELECT acc_financial_year_id, fy_start, fy_end, fy_label,
                   is_active, is_locked
            FROM acc_financial_year
            WHERE co_id = :co_id
              AND :vdate BETWEEN fy_start AND fy_end
            ORDER BY acc_financial_year_id DESC
            LIMIT 1
        """),
        {"co_id": int(co_id), "vdate": voucher_date},
    ).fetchone()
    if not row:
        raise HTTPException(
            status_code=400,
            detail="No financial year exists for the voucher date.",
        )
    fy = dict(row._mapping)
    if fy.get("is_locked"):
        raise HTTPException(
            status_code=400,
            detail=f"Financial year {fy.get('fy_label')} is locked.",
        )
    return fy


def _check_period_lock(db: Session, fy_id: int, voucher_date) -> None:
    """Raise 400 when the accounting period containing voucher_date is locked.
    Matches acc_period_lock rows by date range (period_start/period_end),
    which is robust to FY-relative period_month numbering."""
    row = db.execute(
        text("""
            SELECT apl.acc_period_lock_id, apl.period_month, apl.is_locked
            FROM acc_period_lock apl
            WHERE apl.acc_financial_year_id = :fy_id
              AND :vdate BETWEEN apl.period_start AND apl.period_end
            LIMIT 1
        """),
        {"fy_id": int(fy_id), "vdate": voucher_date},
    ).fetchone()
    if row and row._mapping.get("is_locked"):
        raise HTTPException(
            status_code=400,
            detail="The accounting period for the voucher date is locked.",
        )


def _normalize_lines(lines: list) -> tuple:
    """Validate lines and normalize each to dr_cr 'D'/'C' + amount.

    Each line must have exactly one of debit_amount / credit_amount > 0.
    Requires >= 2 lines and sum(DR) == sum(CR) within AMOUNT_TOLERANCE.

    Returns (normalized_lines, total_dr).
    """
    if not lines or len(lines) < 2:
        raise HTTPException(
            status_code=400,
            detail="At least 2 voucher lines are required.",
        )

    normalized = []
    total_dr = 0.0
    total_cr = 0.0
    for idx, line in enumerate(lines, start=1):
        ledger_id = line.get("acc_ledger_id")
        if not ledger_id:
            raise HTTPException(
                status_code=400,
                detail=f"Line {idx}: acc_ledger_id is required.",
            )
        try:
            dr = float(line.get("debit_amount") or 0)
            cr = float(line.get("credit_amount") or 0)
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=400,
                detail=f"Line {idx}: invalid debit/credit amount.",
            )
        if (dr > 0) == (cr > 0):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Line {idx}: exactly one of debit_amount or "
                    "credit_amount must be greater than zero."
                ),
            )
        dr_cr = "D" if dr > 0 else "C"
        amount = _r2(dr if dr > 0 else cr)
        total_dr += dr
        total_cr += cr
        normalized.append({
            "acc_ledger_id": int(ledger_id),
            "dr_cr": dr_cr,
            "amount": amount,
            "narration": line.get("narration"),
            "party_id": int(line["party_id"]) if line.get("party_id") else None,
            "branch_id": int(line["branch_id"]) if line.get("branch_id") else None,
            "cost_center_id": (
                int(line["cost_center_id"]) if line.get("cost_center_id") else None
            ),
            "source_line_type": line.get("source_line_type"),
        })

    if abs(_r2(total_dr) - _r2(total_cr)) > AMOUNT_TOLERANCE:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Total Debit ({_r2(total_dr):.2f}) does not match "
                f"Total Credit ({_r2(total_cr):.2f})."
            ),
        )

    return normalized, _r2(total_dr)


def _validate_bank_cash(db: Session, lines: list, type_category: str) -> None:
    """PAYMENT/RECEIPT/CONTRA vouchers must include at least one line whose
    ledger_type is Bank ('B') or Cash ('C')."""
    if (type_category or "").upper() not in BANK_CASH_REQUIRED_TYPES:
        return

    ledger_ids = sorted({l["acc_ledger_id"] for l in lines})
    if not ledger_ids:
        raise HTTPException(
            status_code=400,
            detail=f"{type_category} voucher must include ledger lines.",
        )

    q = text("""
        SELECT al.acc_ledger_id, al.ledger_type
        FROM acc_ledger al
        WHERE al.acc_ledger_id IN :ledger_ids
          AND al.active = 1
    """).bindparams(bindparam("ledger_ids", expanding=True))
    rows = db.execute(q, {"ledger_ids": ledger_ids}).fetchall()
    if not any(r._mapping.get("ledger_type") in ("B", "C") for r in rows):
        raise HTTPException(
            status_code=400,
            detail=(
                f"{type_category} voucher must include at least one "
                "Bank or Cash ledger line."
            ),
        )


def _insert_approval_log(
    db: Session,
    voucher_id: int,
    user_id: int,
    action: str,
    from_status: int | None,
    to_status: int | None,
    from_level: int | None = None,
    to_level: int | None = None,
    remarks: str | None = None,
) -> None:
    """Insert a row into acc_voucher_approval_log (columns per model)."""
    db.execute(
        acc_query.insert_approval_log(),
        {
            "acc_voucher_id": int(voucher_id),
            "action": action,
            "from_status_id": from_status,
            "to_status_id": to_status,
            "from_level": from_level,
            "to_level": to_level,
            "remarks": remarks,
            "action_by": int(user_id),
            "updated_by": int(user_id),
        },
    )


def _next_voucher_no(
    db: Session,
    co_id: int,
    voucher_type_id: int,
    fy_id: int,
    type_code: str | None,
    type_prefix: str | None,
    user_id: int,
) -> str:
    """Consume the acc_voucher_numbering sequence (co + type + fy, branch NULL).

    Locks the numbering row (SELECT ... FOR UPDATE), increments last_number,
    and returns CONCAT(COALESCE(prefix, type_code), '-', LPAD(n, 5, '0')).
    Inserts a numbering row starting at 1 when none exists.
    """
    row = db.execute(
        acc_query.get_next_voucher_number(),
        {
            "co_id": int(co_id),
            "voucher_type_id": int(voucher_type_id),
            "fy_id": int(fy_id),
        },
    ).fetchone()

    fallback_prefix = (type_prefix or type_code or "V")
    if row:
        numbering = dict(row._mapping)
        next_number = int(numbering.get("last_number") or 0) + 1
        db.execute(
            acc_query.increment_voucher_numbering(),
            {
                "acc_voucher_numbering_id": int(numbering["acc_voucher_numbering_id"]),
                "last_number": next_number,
                "updated_by": int(user_id),
            },
        )
        prefix = numbering.get("prefix") or fallback_prefix
    else:
        next_number = 1
        db.execute(
            acc_query.insert_voucher_numbering(),
            {
                "co_id": int(co_id),
                "acc_voucher_type_id": int(voucher_type_id),
                "acc_financial_year_id": int(fy_id),
                "prefix": fallback_prefix,
                "last_number": next_number,
                "updated_by": int(user_id),
            },
        )
        prefix = fallback_prefix

    return f"{prefix}-{next_number:05d}"


def _check_duplicate_entry(
    db: Session,
    co_id: int,
    voucher_date,
    party_ids: list[int],
    total_amount: float,
    exclude_voucher_id: int | None = None,
) -> dict | None:
    """Look for a possible duplicate voucher (same company + date + party +
    similar total amount). Returns the existing voucher row or None.

    Non-blocking: the caller records an acc_voucher_warning row instead of
    rejecting the entry.
    """
    if not party_ids:
        return None

    q = text("""
        SELECT av.acc_voucher_id, av.voucher_no
        FROM acc_voucher av
        WHERE av.co_id = :co_id
          AND av.active = 1
          AND av.voucher_date = :vdate
          AND av.party_id IN :party_ids
          AND ABS(COALESCE(av.total_amount, 0) - :amt) <= :tolerance
          AND av.status_id != :cancelled
          AND (:exclude_id IS NULL OR av.acc_voucher_id != :exclude_id)
        LIMIT 1
    """).bindparams(bindparam("party_ids", expanding=True))

    row = db.execute(
        q,
        {
            "co_id": int(co_id),
            "vdate": voucher_date,
            "party_ids": sorted(set(int(p) for p in party_ids)),
            "amt": float(total_amount),
            "tolerance": AMOUNT_TOLERANCE,
            "cancelled": STATUS_CANCELLED,
            "exclude_id": int(exclude_voucher_id) if exclude_voucher_id else None,
        },
    ).fetchone()
    return dict(row._mapping) if row else None


def _insert_duplicate_warning(
    db: Session, voucher_id: int, user_id: int, existing: dict
) -> dict:
    """Record a DUPLICATE_ENTRY warning on the voucher (never blocks save)."""
    code = WARNING_CODES["DUPLICATE_ENTRY"]
    message = code["message"].format(
        existing_no=existing.get("voucher_no") or existing.get("acc_voucher_id")
    )
    db.execute(
        acc_query.insert_voucher_warning(),
        {
            "acc_voucher_id": int(voucher_id),
            "warning_type": "DUPLICATE_ENTRY",
            "warning_message": message,
            "severity": code["severity"],
            "is_overridden": 0,
            "overridden_by": None,
            "overridden_date_time": None,
            "updated_by": int(user_id),
        },
    )
    return {
        "code": "DUPLICATE_ENTRY",
        "severity": code["severity"],
        "message": message,
    }


def _insert_lines(
    db: Session,
    voucher_id: int,
    lines: list,
    header_branch_id: int | None,
    header_party_id: int | None,
    user_id: int,
) -> list[int]:
    """Insert normalized voucher lines; returns list of new line ids."""
    line_ids = []
    for line in lines:
        result = db.execute(
            acc_query.insert_voucher_line(),
            {
                "acc_voucher_id": int(voucher_id),
                "acc_ledger_id": line["acc_ledger_id"],
                "dr_cr": line["dr_cr"],
                "amount": line["amount"],
                "branch_id": line["branch_id"] if line["branch_id"] else header_branch_id,
                "party_id": line["party_id"] if line["party_id"] else header_party_id,
                "narration": line["narration"],
                "source_line_type": line["source_line_type"],
                "cost_center_id": line["cost_center_id"],
                "updated_by": int(user_id),
            },
        )
        line_ids.append(result.lastrowid)
    return line_ids


def _insert_gst_lines(
    db: Session, voucher_id: int, gst_lines: list, line_ids: list[int], user_id: int
) -> None:
    """Insert acc_voucher_gst rows (columns per AccVoucherGst model).

    An optional 0-based `line_index` in a gst row links it to the voucher line
    inserted at that position.
    """
    for gst in gst_lines or []:
        line_ref = None
        line_index = gst.get("line_index")
        if line_index is not None:
            try:
                line_ref = line_ids[int(line_index)]
            except (IndexError, TypeError, ValueError):
                line_ref = None

        def _f(key):
            val = gst.get(key)
            return float(val) if val not in (None, "") else None

        db.execute(
            acc_query.insert_voucher_gst(),
            {
                "acc_voucher_id": int(voucher_id),
                "acc_voucher_line_id": line_ref,
                "gst_type": gst.get("gst_type"),
                "supply_type": gst.get("supply_type"),
                "hsn_sac_code": gst.get("hsn_sac_code"),
                "taxable_amount": _f("taxable_amount"),
                "cgst_rate": _f("cgst_rate"),
                "cgst_amount": _f("cgst_amount"),
                "sgst_rate": _f("sgst_rate"),
                "sgst_amount": _f("sgst_amount"),
                "igst_rate": _f("igst_rate"),
                "igst_amount": _f("igst_amount"),
                "cess_rate": _f("cess_rate"),
                "cess_amount": _f("cess_amount"),
                "total_gst_amount": _f("total_gst_amount"),
                "is_rcm": int(gst.get("is_rcm") or 0),
                "itc_eligibility": gst.get("itc_eligibility"),
                "updated_by": int(user_id),
            },
        )


def _insert_bill_refs(
    db: Session,
    voucher_id: int,
    co_id: int,
    header_party_id: int | None,
    bill_refs: list,
    user_id: int,
) -> None:
    """Insert acc_bill_ref rows for a voucher: co_id + party_id come from the
    header, pending_amount starts at amount, status 'OPEN'."""
    for ref in bill_refs or []:
        ref_type = (ref.get("ref_type") or "NEW").upper()
        if ref_type not in BILL_REF_TYPES:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Invalid bill ref_type '{ref_type}'. "
                    f"Expected one of {BILL_REF_TYPES}."
                ),
            )
        try:
            amount = _r2(ref.get("amount"))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid bill ref amount.")
        if amount <= 0:
            raise HTTPException(
                status_code=400,
                detail="Bill ref amount must be greater than zero.",
            )
        db.execute(
            acc_query.insert_bill_ref(),
            {
                "co_id": int(co_id),
                "acc_voucher_id": int(voucher_id),
                "acc_voucher_line_id": None,
                "party_id": header_party_id,
                "ref_type": ref_type,
                "bill_no": ref.get("bill_no"),
                "bill_date": ref.get("bill_date"),
                "due_date": ref.get("due_date"),
                "amount": amount,
                "pending_amount": amount,
                "status": "OPEN",
                "updated_by": int(user_id),
            },
        )


# =============================================================================
# CREATE / UPDATE
# =============================================================================

def create_manual_voucher(db: Session, payload: dict, user_id: int) -> dict:
    """Create a manual voucher (born Draft, status 21).

    Payload contract:
    {
        co_id, branch_id?, voucher_date,
        acc_voucher_type_id? | type_category?,
        party_id?, ref_no?, ref_date?, narration?,
        lines: [{acc_ledger_id, debit_amount, credit_amount, narration?, party_id?}],
        gst_lines?: [...],
        bill_refs?: [{ref_type, bill_no, bill_date?, due_date?, amount}]
    }
    """
    co_id = payload.get("co_id")
    if not co_id:
        raise HTTPException(status_code=400, detail="co_id is required")
    co_id = int(co_id)

    voucher_date = payload.get("voucher_date")
    if not voucher_date:
        raise HTTPException(status_code=400, detail="voucher_date is required")

    branch_id = int(payload["branch_id"]) if payload.get("branch_id") else None
    party_id = int(payload["party_id"]) if payload.get("party_id") else None

    # 1. Lines: normalize + balance
    lines, total_dr = _normalize_lines(payload.get("lines") or [])

    # 2. Voucher type
    vtype = _resolve_voucher_type(db, co_id, payload)
    type_category = (vtype.get("type_category") or "").upper()

    # 3. Bank/Cash rule for PAYMENT / RECEIPT / CONTRA
    _validate_bank_cash(db, lines, type_category)

    # 4. Financial year (must exist and not be locked) + period lock
    fy = _resolve_financial_year(db, co_id, voucher_date)
    fy_id = int(fy["acc_financial_year_id"])
    _check_period_lock(db, fy_id, voucher_date)

    # 5. Duplicate-entry probe (non-blocking; recorded as a warning after insert)
    dup_party_ids = [party_id] if party_id else [
        l["party_id"] for l in lines if l["party_id"]
    ]
    duplicate = _check_duplicate_entry(
        db, co_id, voucher_date, dup_party_ids, total_dr
    )

    # 6. Voucher number (assigned at create)
    voucher_no = _next_voucher_no(
        db, co_id, int(vtype["acc_voucher_type_id"]), fy_id,
        vtype.get("type_code"), vtype.get("prefix"), user_id,
    )

    # 7. Header
    result = db.execute(
        acc_query.insert_voucher(),
        {
            "co_id": co_id,
            "branch_id": branch_id,
            "acc_voucher_type_id": int(vtype["acc_voucher_type_id"]),
            "acc_financial_year_id": fy_id,
            "voucher_no": voucher_no,
            "voucher_date": voucher_date,
            "party_id": party_id,
            "ref_no": payload.get("ref_no"),
            "ref_date": payload.get("ref_date"),
            "narration": payload.get("narration"),
            "total_amount": total_dr,
            "source_doc_type": None,
            "source_doc_id": None,
            "is_auto_posted": 0,
            "is_reversed": 0,
            "status_id": STATUS_DRAFT,
            "approval_level": None,
            "place_of_supply_state_code": payload.get("place_of_supply_state_code"),
            "branch_gstin": payload.get("branch_gstin"),
            "party_gstin": payload.get("party_gstin"),
            "currency_id": int(payload["currency_id"]) if payload.get("currency_id") else None,
            "exchange_rate": float(payload["exchange_rate"]) if payload.get("exchange_rate") else None,
            "updated_by": int(user_id),
        },
    )
    voucher_id = result.lastrowid

    # 8. Lines / GST / bill refs
    line_ids = _insert_lines(db, voucher_id, lines, branch_id, party_id, user_id)
    _insert_gst_lines(db, voucher_id, payload.get("gst_lines"), line_ids, user_id)
    _insert_bill_refs(
        db, voucher_id, co_id, party_id, payload.get("bill_refs"), user_id
    )

    # 9. Duplicate warning (non-blocking)
    warnings = []
    if duplicate:
        warnings.append(
            _insert_duplicate_warning(db, voucher_id, user_id, duplicate)
        )

    # 10. Approval log
    _insert_approval_log(
        db, voucher_id, user_id,
        action="CREATE", from_status=None, to_status=STATUS_DRAFT,
        remarks="Voucher created",
    )

    db.commit()
    logger.info(
        "Voucher %s (id=%s) created by user %s", voucher_no, voucher_id, user_id
    )
    return {
        "voucher_id": voucher_id,
        "voucher_no": voucher_no,
        "status_id": STATUS_DRAFT,
        "total_amount": total_dr,
        "warnings": warnings,
    }


def update_draft_voucher(
    db: Session, voucher_id: int, payload: dict, user_id: int
) -> dict:
    """Update a Draft (21) or Open (1) voucher: delete-and-reinsert
    lines/gst/bill_refs and recompute total_amount.

    Open is editable because /reopen returns rejected and cancelled vouchers to
    Open (1), not Draft — a rejected voucher would otherwise be uncorrectable.
    Everything from Pending Approval (20) onward stays locked.
    """
    header = _get_voucher_header(db, voucher_id)
    status_id = int(header["status_id"])
    if status_id not in (STATUS_DRAFT, STATUS_OPEN):
        raise HTTPException(
            status_code=400,
            detail="Only draft or open vouchers can be edited.",
        )

    co_id = int(header["co_id"])
    voucher_date = payload.get("voucher_date") or header["voucher_date"]
    branch_id = (
        int(payload["branch_id"]) if payload.get("branch_id")
        else header.get("branch_id")
    )
    party_id = (
        int(payload["party_id"]) if payload.get("party_id")
        else header.get("party_id")
    )

    # Re-validate lines (mandatory on update — full replacement semantics)
    lines, total_dr = _normalize_lines(payload.get("lines") or [])
    _validate_bank_cash(db, lines, header.get("type_category") or "")

    # Re-validate financial year + period for the (possibly new) date
    fy = _resolve_financial_year(db, co_id, voucher_date)
    fy_id = int(fy["acc_financial_year_id"])
    _check_period_lock(db, fy_id, voucher_date)

    # Delete-and-reinsert children
    db.execute(
        text("DELETE FROM acc_voucher_gst WHERE acc_voucher_id = :voucher_id"),
        {"voucher_id": int(voucher_id)},
    )
    db.execute(
        text("DELETE FROM acc_bill_ref WHERE acc_voucher_id = :voucher_id"),
        {"voucher_id": int(voucher_id)},
    )
    db.execute(
        text("DELETE FROM acc_voucher_line WHERE acc_voucher_id = :voucher_id"),
        {"voucher_id": int(voucher_id)},
    )

    db.execute(
        text("""
            UPDATE acc_voucher
            SET voucher_date = :voucher_date,
                acc_financial_year_id = :fy_id,
                branch_id = :branch_id,
                party_id = :party_id,
                ref_no = :ref_no,
                ref_date = :ref_date,
                narration = :narration,
                total_amount = :total_amount,
                updated_by = :updated_by,
                updated_date_time = :updated_date_time
            WHERE acc_voucher_id = :voucher_id
        """),
        {
            "voucher_id": int(voucher_id),
            "voucher_date": voucher_date,
            "fy_id": fy_id,
            "branch_id": branch_id,
            "party_id": party_id,
            "ref_no": payload.get("ref_no", header.get("ref_no")),
            "ref_date": payload.get("ref_date", header.get("ref_date")),
            "narration": payload.get("narration", header.get("narration")),
            "total_amount": total_dr,
            "updated_by": int(user_id),
            "updated_date_time": now_ist(),
        },
    )

    line_ids = _insert_lines(db, voucher_id, lines, branch_id, party_id, user_id)
    _insert_gst_lines(db, voucher_id, payload.get("gst_lines"), line_ids, user_id)
    _insert_bill_refs(
        db, voucher_id, co_id, party_id, payload.get("bill_refs"), user_id
    )

    # Editing never changes status — log the voucher's real one, not "draft".
    _insert_approval_log(
        db, voucher_id, user_id,
        action="UPDATE", from_status=status_id, to_status=status_id,
        remarks="Draft voucher updated" if status_id == STATUS_DRAFT
        else "Open voucher updated",
    )

    db.commit()
    logger.info(
        "Voucher %s (status %s) updated by user %s",
        voucher_id, status_id, user_id,
    )
    return {
        "voucher_id": int(voucher_id),
        "status_id": status_id,
        "total_amount": total_dr,
    }


# =============================================================================
# LIFECYCLE TRANSITIONS
# =============================================================================

def _update_status(
    db: Session,
    voucher_id: int,
    status_id: int,
    user_id: int,
    approval_level: int | None = None,
    set_level: bool = False,
) -> None:
    """Update status (and optionally approval_level) on a voucher."""
    if set_level:
        sql = """
            UPDATE acc_voucher
            SET status_id = :status_id,
                approval_level = :approval_level,
                updated_by = :updated_by,
                updated_date_time = :updated_date_time
            WHERE acc_voucher_id = :voucher_id
        """
    else:
        sql = """
            UPDATE acc_voucher
            SET status_id = :status_id,
                updated_by = :updated_by,
                updated_date_time = :updated_date_time
            WHERE acc_voucher_id = :voucher_id
        """
    params = {
        "voucher_id": int(voucher_id),
        "status_id": status_id,
        "updated_by": int(user_id),
        "updated_date_time": now_ist(),
    }
    if set_level:
        params["approval_level"] = approval_level
    db.execute(text(sql), params)


def open_voucher(db: Session, voucher_id: int, user_id: int) -> dict:
    """Draft (21) -> Open (1). Assigns a voucher number if still missing."""
    header = _get_voucher_header(db, voucher_id)
    if header["status_id"] != STATUS_DRAFT:
        raise HTTPException(
            status_code=400, detail="Only draft vouchers can be opened."
        )

    voucher_no = header.get("voucher_no")
    if not voucher_no:
        voucher_no = _next_voucher_no(
            db,
            int(header["co_id"]),
            int(header["acc_voucher_type_id"]),
            int(header["acc_financial_year_id"]),
            header.get("type_code"),
            header.get("type_prefix"),
            user_id,
        )
        db.execute(
            text("""
                UPDATE acc_voucher
                SET voucher_no = :voucher_no
                WHERE acc_voucher_id = :voucher_id
            """),
            {"voucher_id": int(voucher_id), "voucher_no": voucher_no},
        )

    _update_status(db, voucher_id, STATUS_OPEN, user_id)
    _insert_approval_log(
        db, voucher_id, user_id,
        action="OPEN", from_status=STATUS_DRAFT, to_status=STATUS_OPEN,
        remarks="Voucher opened",
    )
    db.commit()
    logger.info("Voucher %s opened by user %s", voucher_id, user_id)
    return {
        "voucher_id": int(voucher_id),
        "voucher_no": voucher_no,
        "status_id": STATUS_OPEN,
    }


def cancel_voucher(db: Session, voucher_id: int, user_id: int) -> dict:
    """Draft (21) -> Cancelled (6)."""
    header = _get_voucher_header(db, voucher_id)
    if header["status_id"] != STATUS_DRAFT:
        raise HTTPException(
            status_code=400, detail="Only draft vouchers can be cancelled."
        )

    _update_status(db, voucher_id, STATUS_CANCELLED, user_id)
    _insert_approval_log(
        db, voucher_id, user_id,
        action="CANCEL", from_status=STATUS_DRAFT, to_status=STATUS_CANCELLED,
        remarks="Draft voucher cancelled",
    )
    db.commit()
    logger.info("Voucher %s cancelled by user %s", voucher_id, user_id)
    return {"voucher_id": int(voucher_id), "status_id": STATUS_CANCELLED}


def send_for_approval(db: Session, voucher_id: int, user_id: int) -> dict:
    """Open (1) -> Pending Approval (20) at level 1."""
    header = _get_voucher_header(db, voucher_id)
    if header["status_id"] != STATUS_OPEN:
        raise HTTPException(
            status_code=400,
            detail="Only open vouchers can be sent for approval.",
        )

    _update_status(
        db, voucher_id, STATUS_PENDING_APPROVAL, user_id,
        approval_level=1, set_level=True,
    )
    _insert_approval_log(
        db, voucher_id, user_id,
        action="SEND_FOR_APPROVAL",
        from_status=STATUS_OPEN, to_status=STATUS_PENDING_APPROVAL,
        from_level=None, to_level=1,
        remarks="Sent for approval (level 1)",
    )
    db.commit()
    logger.info("Voucher %s sent for approval by user %s", voucher_id, user_id)
    return {
        "voucher_id": int(voucher_id),
        "status_id": STATUS_PENDING_APPROVAL,
        "approval_level": 1,
    }


def _get_voucher_for_approval():
    """Doc query for the shared approval framework (needs status_id,
    approval_level, branch_id). Bind: acc_voucher_id."""
    return text("""
        SELECT av.acc_voucher_id, av.status_id, av.approval_level,
               av.branch_id, av.co_id, av.total_amount
        FROM acc_voucher av
        WHERE av.acc_voucher_id = :acc_voucher_id
          AND av.active = 1
    """)


def _update_voucher_status_for_approval():
    """Status update query for the shared approval framework.
    Binds: acc_voucher_id, status_id, approval_level, updated_by,
    updated_date_time."""
    return text("""
        UPDATE acc_voucher
        SET status_id = :status_id,
            approval_level = :approval_level,
            updated_by = :updated_by,
            updated_date_time = :updated_date_time
        WHERE acc_voucher_id = :acc_voucher_id
    """)


def _resolve_approval_menu_id(
    db: Session, type_category: str, menu_id: int | None
) -> int | None:
    """Resolve the menu_mst.menu_id used by the shared approval framework.

    An explicitly supplied menu_id wins (mirrors how salesInvoice.py accepts
    menu_id from the frontend payload). Otherwise the voucher type category is
    mapped to a menu name via constants.APPROVAL_MENU_MAP and looked up in
    menu_mst. Returns None when menus are not provisioned yet.
    """
    if menu_id:
        return int(menu_id)

    menu_name = APPROVAL_MENU_MAP.get((type_category or "").upper())
    if not menu_name:
        return None

    row = db.execute(
        text("""
            SELECT menu_id FROM menu_mst
            WHERE menu_name = :menu_name AND active = 1
            LIMIT 1
        """),
        {"menu_name": menu_name},
    ).fetchone()
    return int(row._mapping["menu_id"]) if row else None


def approve_voucher(
    db: Session,
    voucher_id: int,
    user_id: int,
    menu_id: int | None = None,
    remarks: str | None = None,
) -> dict:
    """Approve a voucher through the shared approval framework
    (src.common.approval_utils.process_approval).

    When no menu_mst row exists for the voucher type's approval menu (menus
    not yet provisioned), falls back to a direct 20 -> 3 approval.
    On final approval, approved_by + approved_date_time are stamped.
    """
    header = _get_voucher_header(db, voucher_id)
    current_status = header["status_id"]
    current_level = header.get("approval_level")

    if current_status not in (STATUS_OPEN, STATUS_PENDING_APPROVAL):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Cannot approve voucher with status_id {current_status}. "
                "Expected 20 (Pending Approval) or 1 (Open)."
            ),
        )

    resolved_menu_id = _resolve_approval_menu_id(
        db, header.get("type_category") or "", menu_id
    )

    if resolved_menu_id is not None:
        result = process_approval(
            doc_id=int(voucher_id),
            user_id=int(user_id),
            menu_id=int(resolved_menu_id),
            db=db,
            get_doc_fn=_get_voucher_for_approval,
            update_status_fn=_update_voucher_status_for_approval,
            id_param_name="acc_voucher_id",
            doc_name="Voucher",
            document_amount=float(header.get("total_amount") or 0),
            commit=False,
        )
        new_status = result["new_status_id"]
        new_level = result["new_approval_level"]
        message = result["message"]
    else:
        # Fallback: menus not provisioned — direct final approval from either
        # allowed entry state (Open or Pending Approval; enforced above).
        new_status = STATUS_APPROVED
        new_level = current_level
        message = "Voucher approved (no approval menu configured)."
        _update_status(
            db, voucher_id, STATUS_APPROVED, user_id,
            approval_level=new_level, set_level=True,
        )

    if new_status == STATUS_APPROVED:
        db.execute(
            text("""
                UPDATE acc_voucher
                SET approved_by = :approved_by,
                    approved_date_time = :approved_date_time
                WHERE acc_voucher_id = :voucher_id
            """),
            {
                "voucher_id": int(voucher_id),
                "approved_by": int(user_id),
                "approved_date_time": now_ist(),
            },
        )

    _insert_approval_log(
        db, voucher_id, user_id,
        action="APPROVE",
        from_status=current_status, to_status=new_status,
        from_level=current_level, to_level=new_level,
        remarks=remarks or message,
    )
    db.commit()

    logger.info(
        "Voucher %s approved (level %s->%s, status %s) by user %s",
        voucher_id, current_level, new_level, new_status, user_id,
    )
    return {
        "voucher_id": int(voucher_id),
        "status_id": new_status,
        "approval_level": new_level,
        "message": message,
    }


def reject_voucher(
    db: Session, voucher_id: int, user_id: int, reason: str
) -> dict:
    """Pending Approval (20) -> Rejected (4). Reason is mandatory and stored
    in the approval log remarks."""
    header = _get_voucher_header(db, voucher_id)
    if header["status_id"] != STATUS_PENDING_APPROVAL:
        raise HTTPException(
            status_code=400,
            detail="Only vouchers pending approval can be rejected.",
        )
    if not reason or not str(reason).strip():
        raise HTTPException(
            status_code=400, detail="Rejection reason is required."
        )

    current_level = header.get("approval_level")
    _update_status(
        db, voucher_id, STATUS_REJECTED, user_id,
        approval_level=None, set_level=True,
    )
    _insert_approval_log(
        db, voucher_id, user_id,
        action="REJECT",
        from_status=STATUS_PENDING_APPROVAL, to_status=STATUS_REJECTED,
        from_level=current_level, to_level=None,
        remarks=str(reason).strip(),
    )
    db.commit()
    logger.info("Voucher %s rejected by user %s: %s", voucher_id, user_id, reason)
    return {"voucher_id": int(voucher_id), "status_id": STATUS_REJECTED}


def reopen_voucher(db: Session, voucher_id: int, user_id: int) -> dict:
    """Cancelled (6) -> Open (1) or Rejected (4) -> Open (1); clears level."""
    header = _get_voucher_header(db, voucher_id)
    current_status = header["status_id"]
    if current_status not in (STATUS_CANCELLED, STATUS_REJECTED):
        raise HTTPException(
            status_code=400,
            detail="Only cancelled or rejected vouchers can be reopened.",
        )

    _update_status(
        db, voucher_id, STATUS_OPEN, user_id,
        approval_level=None, set_level=True,
    )
    _insert_approval_log(
        db, voucher_id, user_id,
        action="REOPEN", from_status=current_status, to_status=STATUS_OPEN,
        from_level=header.get("approval_level"), to_level=None,
        remarks="Voucher reopened",
    )
    db.commit()
    logger.info("Voucher %s reopened by user %s", voucher_id, user_id)
    return {"voucher_id": int(voucher_id), "status_id": STATUS_OPEN}


# =============================================================================
# REVERSAL
# =============================================================================

def reverse_voucher(
    db: Session, voucher_id: int, user_id: int, narration: str | None = None
) -> dict:
    """Create a mirror voucher (D <-> C) for an approved voucher.

    The mirror is born Approved (3), is_auto_posted 0, linked via
    reversal_of_voucher_id / reversed_by_voucher_id. A voucher can only be
    reversed once (is_reversed guard). Approval log rows are written on both
    vouchers.
    """
    header = _get_voucher_header(db, voucher_id)

    if header["status_id"] != STATUS_APPROVED:
        raise HTTPException(
            status_code=400, detail="Only approved vouchers can be reversed."
        )
    if header.get("is_reversed"):
        raise HTTPException(
            status_code=400, detail="This voucher has already been reversed."
        )

    orig_lines = db.execute(
        text("""
            SELECT acc_voucher_line_id, acc_ledger_id, dr_cr, amount,
                   branch_id, party_id, narration, source_line_type,
                   cost_center_id
            FROM acc_voucher_line
            WHERE acc_voucher_id = :voucher_id
              AND active = 1
            ORDER BY acc_voucher_line_id
        """),
        {"voucher_id": int(voucher_id)},
    ).fetchall()
    if not orig_lines:
        raise HTTPException(
            status_code=400, detail="Original voucher has no lines."
        )

    rev_no = _next_voucher_no(
        db,
        int(header["co_id"]),
        int(header["acc_voucher_type_id"]),
        int(header["acc_financial_year_id"]),
        header.get("type_code"),
        header.get("type_prefix"),
        user_id,
    )
    rev_narration = narration or f"Reversal of {header.get('voucher_no')}"
    approval_time = now_ist()

    result = db.execute(
        acc_query.insert_voucher(),
        {
            "co_id": int(header["co_id"]),
            "branch_id": header.get("branch_id"),
            "acc_voucher_type_id": int(header["acc_voucher_type_id"]),
            "acc_financial_year_id": int(header["acc_financial_year_id"]),
            "voucher_no": rev_no,
            "voucher_date": header["voucher_date"],
            "party_id": header.get("party_id"),
            "ref_no": header.get("ref_no"),
            "ref_date": header.get("ref_date"),
            "narration": rev_narration,
            "total_amount": header.get("total_amount"),
            "source_doc_type": None,
            "source_doc_id": None,
            "is_auto_posted": 0,
            "is_reversed": 0,
            "status_id": STATUS_APPROVED,
            "approval_level": None,
            "place_of_supply_state_code": None,
            "branch_gstin": None,
            "party_gstin": None,
            "currency_id": None,
            "exchange_rate": None,
            "updated_by": int(user_id),
        },
    )
    rev_voucher_id = result.lastrowid

    # Link reversal + stamp approval on the mirror
    db.execute(
        text("""
            UPDATE acc_voucher
            SET reversal_of_voucher_id = :original_id,
                approved_by = :approved_by,
                approved_date_time = :approved_date_time
            WHERE acc_voucher_id = :rev_id
        """),
        {
            "rev_id": int(rev_voucher_id),
            "original_id": int(voucher_id),
            "approved_by": int(user_id),
            "approved_date_time": approval_time,
        },
    )

    # Mirror lines (swap D/C)
    for line in orig_lines:
        m = line._mapping
        db.execute(
            acc_query.insert_voucher_line(),
            {
                "acc_voucher_id": int(rev_voucher_id),
                "acc_ledger_id": int(m["acc_ledger_id"]),
                "dr_cr": "C" if m["dr_cr"] == "D" else "D",
                "amount": m["amount"],
                "branch_id": m["branch_id"],
                "party_id": m["party_id"],
                "narration": m["narration"],
                "source_line_type": m["source_line_type"],
                "cost_center_id": m["cost_center_id"],
                "updated_by": int(user_id),
            },
        )

    # Mark original as reversed
    db.execute(
        text("""
            UPDATE acc_voucher
            SET is_reversed = 1,
                reversed_by_voucher_id = :rev_id,
                updated_by = :updated_by,
                updated_date_time = :updated_date_time
            WHERE acc_voucher_id = :voucher_id
        """),
        {
            "voucher_id": int(voucher_id),
            "rev_id": int(rev_voucher_id),
            "updated_by": int(user_id),
            "updated_date_time": approval_time,
        },
    )

    _insert_approval_log(
        db, voucher_id, user_id,
        action="REVERSE",
        from_status=STATUS_APPROVED, to_status=STATUS_APPROVED,
        remarks=f"Reversed by voucher {rev_no}",
    )
    _insert_approval_log(
        db, rev_voucher_id, user_id,
        action="CREATE",
        from_status=None, to_status=STATUS_APPROVED,
        remarks=rev_narration,
    )
    db.commit()

    logger.info(
        "Voucher %s reversed by user %s -> new voucher %s",
        voucher_id, user_id, rev_voucher_id,
    )
    return {
        "voucher_id": int(voucher_id),
        "reversal_voucher_id": rev_voucher_id,
        "reversal_voucher_no": rev_no,
    }


# =============================================================================
# BILL SETTLEMENT
# =============================================================================

def settle_bills(
    db: Session, voucher_id: int, settlements: list[dict], user_id: int
) -> dict:
    """Allocate an approved PAYMENT/RECEIPT voucher against outstanding bills.

    settlements: [{"acc_bill_ref_id": <target bill ref>, "amount": <alloc>}, ...]

    Ensures the payment voucher has its own AGAINST bill_ref row (created if
    absent with amount = sum of allocations, pending 0). For each row:
    validates the target bill ref (exists, same company, amount within
    pending + tolerance), inserts acc_bill_settlement, decrements the target
    pending_amount, and sets status PARTIAL/CLOSED.
    """
    header = _get_voucher_header(db, voucher_id)

    if header["status_id"] != STATUS_APPROVED:
        raise HTTPException(
            status_code=400,
            detail="Only approved vouchers can be used for bill settlement.",
        )
    type_category = (header.get("type_category") or "").upper()
    if type_category not in ("PAYMENT", "RECEIPT"):
        raise HTTPException(
            status_code=400,
            detail="Bill settlement is only allowed for Payment/Receipt vouchers.",
        )
    if not settlements:
        raise HTTPException(
            status_code=400, detail="settlements list is required."
        )

    co_id = int(header["co_id"])
    total_alloc = 0.0
    parsed = []
    for s in settlements:
        try:
            target_id = int(s["acc_bill_ref_id"])
            amount = _r2(s["amount"])
        except (KeyError, TypeError, ValueError):
            raise HTTPException(
                status_code=400,
                detail="Each settlement needs acc_bill_ref_id and amount.",
            )
        if amount <= 0:
            raise HTTPException(
                status_code=400,
                detail="Settlement amount must be greater than zero.",
            )
        parsed.append((target_id, amount))
        total_alloc += amount
    total_alloc = _r2(total_alloc)

    # Ensure the payment voucher has its own AGAINST bill_ref row
    own_ref_row = db.execute(
        text("""
            SELECT acc_bill_ref_id
            FROM acc_bill_ref
            WHERE acc_voucher_id = :voucher_id
              AND ref_type = 'AGAINST'
              AND active = 1
            LIMIT 1
        """),
        {"voucher_id": int(voucher_id)},
    ).fetchone()
    if own_ref_row:
        own_ref_id = int(own_ref_row._mapping["acc_bill_ref_id"])
    else:
        result = db.execute(
            acc_query.insert_bill_ref(),
            {
                "co_id": co_id,
                "acc_voucher_id": int(voucher_id),
                "acc_voucher_line_id": None,
                "party_id": header.get("party_id"),
                "ref_type": "AGAINST",
                "bill_no": header.get("voucher_no"),
                "bill_date": header.get("voucher_date"),
                "due_date": None,
                "amount": total_alloc,
                "pending_amount": 0,
                "status": "CLOSED",
                "updated_by": int(user_id),
            },
        )
        own_ref_id = result.lastrowid

    settled_count = 0
    for target_id, amount in parsed:
        if target_id == own_ref_id:
            raise HTTPException(
                status_code=400,
                detail="Cannot settle a voucher against its own bill reference.",
            )

        target_row = db.execute(
            text("""
                SELECT acc_bill_ref_id, co_id, pending_amount, status
                FROM acc_bill_ref
                WHERE acc_bill_ref_id = :target_id
                  AND active = 1
            """),
            {"target_id": target_id},
        ).fetchone()
        if not target_row:
            raise HTTPException(
                status_code=404,
                detail=f"Bill reference {target_id} not found.",
            )
        target = dict(target_row._mapping)
        if int(target["co_id"]) != co_id:
            raise HTTPException(
                status_code=400,
                detail=f"Bill reference {target_id} belongs to another company.",
            )
        pending = _r2(target.get("pending_amount"))
        if amount > pending + AMOUNT_TOLERANCE:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Settlement amount ({amount}) exceeds pending amount "
                    f"({pending}) for bill {target_id}."
                ),
            )

        db.execute(
            acc_query.insert_bill_settlement(),
            {
                "acc_bill_ref_id": own_ref_id,
                "settled_against_bill_ref_id": target_id,
                "settled_amount": amount,
                "settlement_date": header.get("voucher_date"),
                "updated_by": int(user_id),
            },
        )

        new_pending = _r2(max(pending - amount, 0))
        new_status = "CLOSED" if new_pending <= AMOUNT_TOLERANCE else "PARTIAL"
        db.execute(
            acc_query.update_bill_ref_pending(),
            {
                "acc_bill_ref_id": target_id,
                "pending_amount": new_pending,
                "status": new_status,
                "updated_by": int(user_id),
            },
        )
        settled_count += 1

    db.commit()
    logger.info(
        "Settled %d bills (total %.2f) against voucher %s by user %s",
        settled_count, total_alloc, voucher_id, user_id,
    )
    return {
        "voucher_id": int(voucher_id),
        "settled_count": settled_count,
        "total_settled": total_alloc,
        "payment_bill_ref_id": own_ref_id,
    }
