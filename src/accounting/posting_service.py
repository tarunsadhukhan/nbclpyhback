"""
Auto-posting service — the single entry point that turns approved/completed
business documents into balanced accounting vouchers.

    post_document(db, source_doc_type, source_doc_id, user_id) -> dict

Supported source_doc_type values (see constants.SOURCE_DOC_TYPES):
    PROC_BILLPASS  — proc_inward (bill pass complete)     -> PURCHASE voucher
    JUTE_BILLPASS  — jute_mr (bill pass complete)         -> PURCHASE voucher (+ optional
                     JUTE_FREIGHT PAYMENT voucher when frieght_paid > 0)
    SALES_INVOICE  — sales_invoice (approved)             -> SALES voucher
    DRCR_NOTE      — drcr_note (approved)                 -> DEBIT_NOTE / CREDIT_NOTE voucher

Non-negotiable properties (plan §5.2):
    - NEVER raises — every outcome is returned as
      {"status": "POSTED"|"DRAFTED"|"SKIPPED"|"FAILED", "acc_voucher_id": int|None, "message": str}
    - Failure-isolated — every attempt is recorded in acc_posting_queue
      (unique on source_doc_type + source_doc_id); on failure the voucher work is
      rolled back and only the queue row is committed.
    - Idempotent — an existing active, non-cancelled voucher for the same source
      document short-circuits to POSTED.
    - Config-driven — acc_company_settings.posting_mode_* per doc type:
      OFF -> SKIPPED, AUTO_DRAFT -> voucher born at status 21 (DRAFTED),
      AUTO_APPROVED -> voucher born at status 3 (POSTED).
    - Balanced by construction — |sum(DR) - sum(CR)| <= 0.01 asserted before insert.

Owner decisions honoured here:
    (2) jute net_total deducts TDS (recomputed defensively via compute_jute_totals)
    (3) claims post as GROSS purchase/sale + a separate claim-recovery leg
    (4) due dates derive from PO credit days (settings.due_date_rule)
    (5) this module is only invoked on approval / bill-pass-complete triggers
"""

import logging
from datetime import date, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.common.utils import now_ist
from src.accounting.constants import (
    ACC_STATUS_IDS,
    POSTING_MODES,
    DUE_DATE_RULES,
    SOURCE_DOC_TYPES,
    LINE_TYPES,
)
from src.juteProcurement.totals import compute_jute_totals

logger = logging.getLogger(__name__)

DR = "D"
CR = "C"
BALANCE_TOLERANCE = 0.01
SALES_HEADER_TOLERANCE = 1.00  # header totals are FE-computed; small drift tolerated

STATUS_APPROVED = ACC_STATUS_IDS["APPROVED"]   # 3
STATUS_DRAFT = ACC_STATUS_IDS["DRAFT"]         # 21
STATUS_CANCELLED = ACC_STATUS_IDS["CANCELLED"] # 6

MODE_OFF = POSTING_MODES["OFF"]
MODE_AUTO_DRAFT = POSTING_MODES["AUTO_DRAFT"]
MODE_AUTO_APPROVED = POSTING_MODES["AUTO_APPROVED"]

# acc_company_settings column per source doc type
_MODE_FIELDS = {
    SOURCE_DOC_TYPES["PROC_BILLPASS"]: "posting_mode_purchase",
    SOURCE_DOC_TYPES["JUTE_BILLPASS"]: "posting_mode_jute_purchase",
    SOURCE_DOC_TYPES["SALES_INVOICE"]: "posting_mode_sales",
    SOURCE_DOC_TYPES["DRCR_NOTE"]: "posting_mode_drcr",
}

# Account-determination doc_type resolution order (most specific first).
_DETERMINATION_FALLBACKS = {
    SOURCE_DOC_TYPES["DRCR_NOTE"]: [SOURCE_DOC_TYPES["DRCR_NOTE"], SOURCE_DOC_TYPES["PROC_BILLPASS"]],
    SOURCE_DOC_TYPES["JUTE_FREIGHT"]: [SOURCE_DOC_TYPES["JUTE_FREIGHT"], SOURCE_DOC_TYPES["JUTE_BILLPASS"]],
}


class PostingError(Exception):
    """Business-level posting failure with a human-readable message."""


# =============================================================================
# GENERIC HELPERS
# =============================================================================

def _r2(value) -> float:
    """Round to 2 decimal places, treating None as 0."""
    return round(float(value or 0), 2)


def _result(status: str, voucher_id, message: str) -> dict:
    return {
        "status": status,
        "acc_voucher_id": int(voucher_id) if voucher_id else None,
        "message": message,
    }


def _upsert_queue(db: Session, co_id: int, source_doc_type: str, source_doc_id: int,
                  status: str, voucher_id, error, user_id: int):
    """Upsert the acc_posting_queue row (unique on source_doc_type + source_doc_id)."""
    db.execute(
        text("""
            INSERT INTO acc_posting_queue
                (co_id, source_doc_type, source_doc_id, status, acc_voucher_id,
                 attempt_count, last_error, active, updated_by, updated_date_time)
            VALUES
                (:co_id, :source_doc_type, :source_doc_id, :status, :acc_voucher_id,
                 1, :last_error, 1, :updated_by, :now)
            ON DUPLICATE KEY UPDATE
                co_id = VALUES(co_id),
                status = VALUES(status),
                acc_voucher_id = VALUES(acc_voucher_id),
                attempt_count = attempt_count + 1,
                last_error = VALUES(last_error),
                updated_by = VALUES(updated_by),
                updated_date_time = VALUES(updated_date_time)
        """),
        {
            "co_id": int(co_id or 0),
            "source_doc_type": source_doc_type,
            "source_doc_id": int(source_doc_id),
            "status": status,
            "acc_voucher_id": int(voucher_id) if voucher_id else None,
            "last_error": (str(error)[:1000] if error else None),
            "updated_by": int(user_id or 0),
            "now": now_ist(),
        },
    )


def _finalize(db: Session, co_id: int, source_doc_type: str, source_doc_id: int,
              status: str, voucher_id, message: str, user_id: int) -> dict:
    """Record the attempt in the posting queue and commit. Never raises."""
    try:
        _upsert_queue(db, co_id, source_doc_type, source_doc_id, status, voucher_id,
                      message if status == "FAILED" else None, user_id)
        db.commit()
    except Exception:
        logger.exception(
            "posting_service: failed to record queue row for %s/%s",
            source_doc_type, source_doc_id,
        )
        try:
            db.rollback()
        except Exception:
            pass
    return _result(status, voucher_id, message)


def _load_settings(db: Session, co_id: int):
    row = db.execute(
        text("""
            SELECT posting_mode_purchase, posting_mode_jute_purchase,
                   posting_mode_sales, posting_mode_drcr,
                   due_date_rule, default_credit_days, enable_tds
            FROM acc_company_settings
            WHERE co_id = :co_id AND active = 1
            LIMIT 1
        """),
        {"co_id": int(co_id)},
    ).fetchone()
    return dict(row._mapping) if row else None


def _existing_voucher_id(db: Session, source_doc_type: str, source_doc_id: int):
    """Return the id of an active, non-cancelled voucher already posted for this doc."""
    row = db.execute(
        text("""
            SELECT acc_voucher_id FROM acc_voucher
            WHERE source_doc_type = :source_doc_type
              AND source_doc_id = :source_doc_id
              AND active = 1
              AND (status_id IS NULL OR status_id != :cancelled)
            LIMIT 1
        """),
        {
            "source_doc_type": source_doc_type,
            "source_doc_id": int(source_doc_id),
            "cancelled": STATUS_CANCELLED,
        },
    ).fetchone()
    return int(row._mapping["acc_voucher_id"]) if row else None


def _is_accounting_activated(db: Session, co_id: int) -> bool:
    row = db.execute(
        text("SELECT 1 FROM acc_voucher_type WHERE co_id = :co_id AND active = 1 LIMIT 1"),
        {"co_id": int(co_id)},
    ).fetchone()
    return row is not None


def _get_financial_year_id(db: Session, co_id: int, voucher_date) -> int:
    row = db.execute(
        text("""
            SELECT acc_financial_year_id FROM acc_financial_year
            WHERE co_id = :co_id
              AND :voucher_date BETWEEN fy_start AND fy_end
              AND is_active = 1
            LIMIT 1
        """),
        {"co_id": int(co_id), "voucher_date": voucher_date},
    ).fetchone()
    if not row:
        raise PostingError(
            f"No active financial year covers {voucher_date} for co_id {co_id} — "
            "create the financial year in accounting setup first"
        )
    return int(row._mapping["acc_financial_year_id"])


def _get_voucher_type(db: Session, co_id: int, type_category: str) -> dict:
    row = db.execute(
        text("""
            SELECT acc_voucher_type_id, type_code, prefix
            FROM acc_voucher_type
            WHERE co_id = :co_id AND type_category = :type_category AND active = 1
            LIMIT 1
        """),
        {"co_id": int(co_id), "type_category": type_category},
    ).fetchone()
    if not row:
        raise PostingError(
            f"No {type_category} voucher type configured for co_id {co_id} — "
            "run accounting activation first"
        )
    return dict(row._mapping)


def _next_voucher_no(db: Session, co_id: int, voucher_type: dict, fy_id: int, user_id: int) -> str:
    """
    Consume acc_voucher_numbering (co + type + fy, branch NULL) under
    SELECT ... FOR UPDATE. Inserts the numbering row if missing.
    """
    select_sql = text("""
        SELECT acc_voucher_numbering_id, prefix, COALESCE(last_number, 0) AS last_number
        FROM acc_voucher_numbering
        WHERE co_id = :co_id
          AND acc_voucher_type_id = :voucher_type_id
          AND acc_financial_year_id = :fy_id
          AND branch_id IS NULL
          AND active = 1
        LIMIT 1
        FOR UPDATE
    """)
    params = {
        "co_id": int(co_id),
        "voucher_type_id": int(voucher_type["acc_voucher_type_id"]),
        "fy_id": int(fy_id),
    }
    row = db.execute(select_sql, params).fetchone()
    if row is None:
        db.execute(
            text("""
                INSERT INTO acc_voucher_numbering
                    (co_id, acc_voucher_type_id, acc_financial_year_id, branch_id,
                     prefix, last_number, active, updated_by, updated_date_time)
                VALUES
                    (:co_id, :voucher_type_id, :fy_id, NULL,
                     :prefix, 0, 1, :updated_by, :now)
            """),
            {
                **params,
                "prefix": voucher_type.get("prefix") or voucher_type.get("type_code"),
                "updated_by": int(user_id),
                "now": now_ist(),
            },
        )
        row = db.execute(select_sql, params).fetchone()
        if row is None:
            raise PostingError("Failed to initialise voucher numbering row")

    mapped = row._mapping
    next_number = int(mapped["last_number"]) + 1
    db.execute(
        text("""
            UPDATE acc_voucher_numbering
            SET last_number = :next_number, updated_by = :updated_by,
                updated_date_time = :now
            WHERE acc_voucher_numbering_id = :numbering_id
        """),
        {
            "next_number": next_number,
            "updated_by": int(user_id),
            "now": now_ist(),
            "numbering_id": int(mapped["acc_voucher_numbering_id"]),
        },
    )
    prefix = mapped["prefix"] or voucher_type.get("prefix") or voucher_type.get("type_code") or "V"
    return f"{prefix}-{next_number:05d}"


# =============================================================================
# LEDGER RESOLUTION
# =============================================================================

def _find_determination(db: Session, co_id: int, doc_types: list, line_type: str,
                        item_grp_id=None):
    """Resolve a ledger via acc_account_determination, most specific first."""
    for doc_type in doc_types:
        if item_grp_id is not None:
            row = db.execute(
                text("""
                    SELECT acc_ledger_id FROM acc_account_determination
                    WHERE co_id = :co_id AND doc_type = :doc_type AND line_type = :line_type
                      AND item_grp_id = :item_grp_id AND active = 1
                    LIMIT 1
                """),
                {
                    "co_id": int(co_id), "doc_type": doc_type,
                    "line_type": line_type, "item_grp_id": int(item_grp_id),
                },
            ).fetchone()
            if row and row._mapping["acc_ledger_id"]:
                return int(row._mapping["acc_ledger_id"])
        else:
            row = db.execute(
                text("""
                    SELECT acc_ledger_id FROM acc_account_determination
                    WHERE co_id = :co_id AND doc_type = :doc_type AND line_type = :line_type
                      AND is_default = 1 AND active = 1
                    LIMIT 1
                """),
                {"co_id": int(co_id), "doc_type": doc_type, "line_type": line_type},
            ).fetchone()
            if row and row._mapping["acc_ledger_id"]:
                return int(row._mapping["acc_ledger_id"])
    return None


def _require_ledger(db: Session, co_id: int, doc_type: str, line_type: str) -> int:
    doc_types = _DETERMINATION_FALLBACKS.get(doc_type, [doc_type])
    ledger_id = _find_determination(db, co_id, doc_types, line_type)
    if ledger_id is None:
        raise PostingError(
            f"No account determination configured for {doc_type}/{line_type} "
            f"(co_id {co_id}) — configure it in accounting setup"
        )
    return ledger_id


def _resolve_split_ledgers(db: Session, co_id: int, doc_type: str, line_type: str,
                           group_amounts: dict) -> dict:
    """
    Resolve {item_grp_id_or_None: amount} into {acc_ledger_id: amount}, preferring
    item-group-specific determination rows and falling back to the default rule.
    """
    doc_types = _DETERMINATION_FALLBACKS.get(doc_type, [doc_type])
    default_ledger = _find_determination(db, co_id, doc_types, line_type)
    split: dict = {}
    for item_grp_id, amount in group_amounts.items():
        amount = _r2(amount)
        if amount == 0:
            continue
        ledger_id = None
        if item_grp_id is not None:
            ledger_id = _find_determination(
                db, co_id, doc_types, line_type, item_grp_id=int(item_grp_id)
            )
        if ledger_id is None:
            ledger_id = default_ledger
        if ledger_id is None:
            raise PostingError(
                f"No account determination configured for {doc_type}/{line_type} "
                f"(co_id {co_id}) — configure it in accounting setup"
            )
        split[ledger_id] = _r2(split.get(ledger_id, 0.0) + amount)
    return split


def _get_party_ledger(db: Session, co_id: int, party_id: int) -> int:
    row = db.execute(
        text("""
            SELECT acc_ledger_id FROM acc_ledger
            WHERE co_id = :co_id AND party_id = :party_id
              AND ledger_type = 'P' AND active = 1
            LIMIT 1
        """),
        {"co_id": int(co_id), "party_id": int(party_id)},
    ).fetchone()
    if not row:
        raise PostingError(
            f"Party ledger not configured for party {party_id} — "
            "run accounting activation or create the ledger"
        )
    return int(row._mapping["acc_ledger_id"])


def _get_cash_ledger(db: Session, co_id: int, doc_type: str) -> int:
    """CASH ledger via determination, falling back to the company's cash-type ledger."""
    doc_types = _DETERMINATION_FALLBACKS.get(doc_type, [doc_type])
    ledger_id = _find_determination(db, co_id, doc_types, LINE_TYPES["CASH"])
    if ledger_id:
        return ledger_id
    row = db.execute(
        text("""
            SELECT acc_ledger_id FROM acc_ledger
            WHERE co_id = :co_id AND ledger_type = 'C' AND active = 1
            ORDER BY acc_ledger_id
            LIMIT 1
        """),
        {"co_id": int(co_id)},
    ).fetchone()
    if not row:
        raise PostingError(f"No cash ledger configured for co_id {co_id}")
    return int(row._mapping["acc_ledger_id"])


# =============================================================================
# DUE-DATE RULE
# =============================================================================

def _derive_due_date(settings: dict, doc_due_date, base_date, credit_days):
    """
    'MANUAL'          -> only the document's own due date.
    'PO_CREDIT_DAYS'  -> doc due date, else base date + PO-chain credit days,
                         else base date + settings.default_credit_days, else NULL.
    """
    rule = (settings or {}).get("due_date_rule") or DUE_DATE_RULES["PO_CREDIT_DAYS"]
    if rule == DUE_DATE_RULES["MANUAL"]:
        return doc_due_date
    if doc_due_date:
        return doc_due_date
    if base_date is None:
        return None
    if credit_days:
        return base_date + timedelta(days=int(credit_days))
    default_credit_days = (settings or {}).get("default_credit_days")
    if default_credit_days:
        return base_date + timedelta(days=int(default_credit_days))
    return None


# =============================================================================
# ENTRY ASSEMBLY / INSERTS
# =============================================================================

def _assert_balanced(entry: list, source_doc_type: str, source_doc_id: int) -> float:
    """Assert |sum(DR) - sum(CR)| <= tolerance; return total DR."""
    total_dr = _r2(sum(leg["amount"] for leg in entry if leg["dr_cr"] == DR))
    total_cr = _r2(sum(leg["amount"] for leg in entry if leg["dr_cr"] == CR))
    if abs(total_dr - total_cr) > BALANCE_TOLERANCE:
        raise PostingError(
            f"Unbalanced entry for {source_doc_type}/{source_doc_id}: "
            f"DR {total_dr} vs CR {total_cr} — voucher not inserted"
        )
    if total_dr <= 0:
        raise PostingError(
            f"Zero-value entry for {source_doc_type}/{source_doc_id} — nothing to post"
        )
    return total_dr


def _write_voucher(db: Session, *, co_id: int, branch_id, type_category: str,
                   voucher_date, party_id, ref_no, ref_date, narration: str,
                   entry: list, source_doc_type: str, source_doc_id: int,
                   mode: str, user_id: int):
    """
    Insert acc_voucher + acc_voucher_line rows + approval log for a balanced entry.

    Each entry leg: {"line_type", "dr_cr", "amount", "ledger_id", "narration",
                     "party_id" (optional), "is_party_leg" (optional)}

    Returns (voucher_id, voucher_no, party_line_id, total_dr).
    """
    total_dr = _assert_balanced(entry, source_doc_type, source_doc_id)
    voucher_type = _get_voucher_type(db, co_id, type_category)
    fy_id = _get_financial_year_id(db, co_id, voucher_date)
    voucher_no = _next_voucher_no(db, co_id, voucher_type, fy_id, user_id)
    now = now_ist()
    status_id = STATUS_APPROVED if mode == MODE_AUTO_APPROVED else STATUS_DRAFT

    result = db.execute(
        text("""
            INSERT INTO acc_voucher
                (co_id, branch_id, acc_voucher_type_id, acc_financial_year_id,
                 voucher_no, voucher_date, party_id, ref_no, ref_date, narration,
                 total_amount, source_doc_type, source_doc_id,
                 is_auto_posted, is_reversed, status_id,
                 approved_by, approved_date_time,
                 active, updated_by, updated_date_time)
            VALUES
                (:co_id, :branch_id, :voucher_type_id, :fy_id,
                 :voucher_no, :voucher_date, :party_id, :ref_no, :ref_date, :narration,
                 :total_amount, :source_doc_type, :source_doc_id,
                 1, 0, :status_id,
                 :approved_by, :approved_date_time,
                 1, :updated_by, :now)
        """),
        {
            "co_id": int(co_id),
            "branch_id": int(branch_id) if branch_id else None,
            "voucher_type_id": int(voucher_type["acc_voucher_type_id"]),
            "fy_id": int(fy_id),
            "voucher_no": voucher_no,
            "voucher_date": voucher_date,
            "party_id": int(party_id) if party_id else None,
            "ref_no": str(ref_no)[:50] if ref_no else None,
            "ref_date": ref_date,
            "narration": narration[:500] if narration else None,
            "total_amount": total_dr,
            "source_doc_type": source_doc_type,
            "source_doc_id": int(source_doc_id),
            "status_id": status_id,
            "approved_by": int(user_id) if mode == MODE_AUTO_APPROVED else None,
            "approved_date_time": now if mode == MODE_AUTO_APPROVED else None,
            "updated_by": int(user_id),
            "now": now,
        },
    )
    voucher_id = result.lastrowid

    party_line_id = None
    for leg in entry:
        line_result = db.execute(
            text("""
                INSERT INTO acc_voucher_line
                    (acc_voucher_id, acc_ledger_id, dr_cr, amount, branch_id,
                     party_id, narration, source_line_type,
                     active, updated_by, updated_date_time)
                VALUES
                    (:voucher_id, :ledger_id, :dr_cr, :amount, :branch_id,
                     :party_id, :narration, :source_line_type,
                     1, :updated_by, :now)
            """),
            {
                "voucher_id": int(voucher_id),
                "ledger_id": int(leg["ledger_id"]),
                "dr_cr": leg["dr_cr"],
                "amount": _r2(leg["amount"]),
                "branch_id": int(branch_id) if branch_id else None,
                "party_id": int(leg["party_id"]) if leg.get("party_id") else None,
                "narration": (leg.get("narration") or "")[:255] or None,
                "source_line_type": leg["line_type"],
                "updated_by": int(user_id),
                "now": now,
            },
        )
        if leg.get("is_party_leg"):
            party_line_id = line_result.lastrowid

    db.execute(
        text("""
            INSERT INTO acc_voucher_approval_log
                (acc_voucher_id, action, from_status_id, to_status_id,
                 from_level, to_level, remarks, action_by, action_date_time,
                 active, updated_by, updated_date_time)
            VALUES
                (:voucher_id, 'AUTO_POST', NULL, :to_status_id,
                 NULL, NULL, :remarks, :action_by, :now,
                 1, :updated_by, :now)
        """),
        {
            "voucher_id": int(voucher_id),
            "to_status_id": status_id,
            "remarks": (narration or "Auto-posted")[:255],
            "action_by": int(user_id),
            "updated_by": int(user_id),
            "now": now,
        },
    )

    return int(voucher_id), voucher_no, party_line_id, total_dr


def _insert_gst_summary(db: Session, *, voucher_id: int, taxable: float,
                        cgst: float, sgst: float, igst: float, user_id: int):
    """Insert the voucher-level GST summary row (only called when GST is present)."""
    total_gst = _r2(cgst + sgst + igst)
    gst_type = "INTRA" if cgst > 0 else "INTER"
    db.execute(
        text("""
            INSERT INTO acc_voucher_gst
                (acc_voucher_id, acc_voucher_line_id, gst_type, taxable_amount,
                 cgst_amount, sgst_amount, igst_amount, total_gst_amount,
                 active, updated_by, updated_date_time)
            VALUES
                (:voucher_id, NULL, :gst_type, :taxable,
                 :cgst, :sgst, :igst, :total_gst,
                 1, :updated_by, :now)
        """),
        {
            "voucher_id": int(voucher_id),
            "gst_type": gst_type,
            "taxable": _r2(taxable),
            "cgst": _r2(cgst),
            "sgst": _r2(sgst),
            "igst": _r2(igst),
            "total_gst": total_gst,
            "updated_by": int(user_id),
            "now": now_ist(),
        },
    )


def _insert_bill_ref(db: Session, *, co_id: int, voucher_id: int, voucher_line_id,
                     party_id, ref_type: str, bill_no, bill_date, due_date,
                     amount: float, pending_amount: float, status: str,
                     user_id: int) -> int:
    result = db.execute(
        text("""
            INSERT INTO acc_bill_ref
                (co_id, acc_voucher_id, acc_voucher_line_id, party_id, ref_type,
                 bill_no, bill_date, due_date, amount, pending_amount, status,
                 active, updated_by, updated_date_time)
            VALUES
                (:co_id, :voucher_id, :voucher_line_id, :party_id, :ref_type,
                 :bill_no, :bill_date, :due_date, :amount, :pending_amount, :status,
                 1, :updated_by, :now)
        """),
        {
            "co_id": int(co_id),
            "voucher_id": int(voucher_id),
            "voucher_line_id": int(voucher_line_id) if voucher_line_id else None,
            "party_id": int(party_id) if party_id else None,
            "ref_type": ref_type,
            "bill_no": str(bill_no)[:50] if bill_no else None,
            "bill_date": bill_date,
            "due_date": due_date,
            "amount": _r2(amount),
            "pending_amount": _r2(pending_amount),
            "status": status,
            "updated_by": int(user_id),
            "now": now_ist(),
        },
    )
    return int(result.lastrowid)


# =============================================================================
# RECIPE: PROCUREMENT BILL PASS  (source = proc_inward, id = inward_id)
# =============================================================================

def _recipe_proc_billpass(db: Session, co_id: int, inward_id: int, user_id: int,
                          settings: dict, mode: str):
    """
    DR MATERIAL (line taxable + additional-charge net, split by item group)
    DR CGST_INPUT / SGST_INPUT / IGST_INPUT (each if > 0)
    DR/CR ROUND_OFF (sign of proc_inward.round_off_value)
    CR party ledger (creditor total)
    """
    doc_type = SOURCE_DOC_TYPES["PROC_BILLPASS"]
    hdr = db.execute(
        text("""
            SELECT pi.inward_id, pi.branch_id, bm.co_id AS co_id, pi.supplier_id,
                   pi.invoice_no, pi.invoice_date, pi.invoice_due_date,
                   pi.sr_no, pi.billpass_no, pi.billpass_date, pi.inward_date,
                   pi.round_off_value
            FROM proc_inward pi
            INNER JOIN branch_mst bm ON bm.branch_id = pi.branch_id
            WHERE pi.inward_id = :inward_id
        """),
        {"inward_id": int(inward_id)},
    ).fetchone()
    if not hdr:
        raise PostingError(f"Inward {inward_id} not found")
    h = hdr._mapping
    supplier_id = h["supplier_id"]
    if not supplier_id:
        raise PostingError(f"Inward {inward_id} has no supplier — cannot post")

    # Line taxable per item group: approved_qty * COALESCE(accepted_rate, rate) - discount
    group_rows = db.execute(
        text("""
            SELECT im.item_grp_id AS item_grp_id,
                   COALESCE(SUM(
                       (COALESCE(pid.approved_qty, 0) * COALESCE(pid.accepted_rate, pid.rate, 0))
                       - COALESCE(pid.discount_amount, 0)
                   ), 0) AS taxable
            FROM proc_inward_dtl pid
            LEFT JOIN item_mst im ON im.item_id = pid.item_id
            WHERE pid.inward_id = :inward_id AND pid.active = 1
            GROUP BY im.item_grp_id
        """),
        {"inward_id": int(inward_id)},
    ).fetchall()
    group_amounts = {
        r._mapping["item_grp_id"]: _r2(r._mapping["taxable"]) for r in group_rows
    }
    taxable_lines = _r2(sum(group_amounts.values()))

    # Additional charges (no active flag on proc_inward_additional)
    addl_row = db.execute(
        text("""
            SELECT COALESCE(SUM(
                COALESCE(pia.net_amount, COALESCE(pia.qty, 0) * COALESCE(pia.rate, 0))
            ), 0) AS additional_net
            FROM proc_inward_additional pia
            WHERE pia.inward_id = :inward_id
        """),
        {"inward_id": int(inward_id)},
    ).fetchone()
    taxable_addl = _r2(addl_row._mapping["additional_net"] if addl_row else 0)
    if taxable_addl != 0:
        group_amounts[None] = _r2(group_amounts.get(None, 0.0) + taxable_addl)

    # GST — proc_gst links to detail rows via the column literally named
    # `proc_inward_dtl` AND to additional charges via proc_inward_additional_id.
    gst_row = db.execute(
        text("""
            SELECT COALESCE(SUM(pg.c_tax_amount), 0) AS cgst,
                   COALESCE(SUM(pg.s_tax_amount), 0) AS sgst,
                   COALESCE(SUM(pg.i_tax_amount), 0) AS igst
            FROM proc_gst pg
            LEFT JOIN proc_inward_dtl pid ON pid.inward_dtl_id = pg.proc_inward_dtl
            LEFT JOIN proc_inward_additional pia
                   ON pia.proc_inward_additional_id = pg.proc_inward_additional_id
            WHERE pg.active = 1
              AND (
                    (pid.inward_id = :inward_id AND pid.active = 1)
                 OR pia.inward_id = :inward_id
              )
        """),
        {"inward_id": int(inward_id)},
    ).fetchone()
    cgst = _r2(gst_row._mapping["cgst"] if gst_row else 0)
    sgst = _r2(gst_row._mapping["sgst"] if gst_row else 0)
    igst = _r2(gst_row._mapping["igst"] if gst_row else 0)

    round_off = _r2(h["round_off_value"])
    creditor_amount = _r2(taxable_lines + taxable_addl + cgst + sgst + igst + round_off)

    party_ledger = _get_party_ledger(db, co_id, supplier_id)
    material_split = _resolve_split_ledgers(
        db, co_id, doc_type, LINE_TYPES["MATERIAL"], group_amounts
    )

    entry = []
    for ledger_id, amount in material_split.items():
        entry.append({
            "line_type": LINE_TYPES["MATERIAL"], "dr_cr": DR, "amount": amount,
            "ledger_id": ledger_id, "narration": "Purchase material",
        })
    if cgst > 0:
        entry.append({
            "line_type": LINE_TYPES["CGST_INPUT"], "dr_cr": DR, "amount": cgst,
            "ledger_id": _require_ledger(db, co_id, doc_type, LINE_TYPES["CGST_INPUT"]),
            "narration": "CGST Input",
        })
    if sgst > 0:
        entry.append({
            "line_type": LINE_TYPES["SGST_INPUT"], "dr_cr": DR, "amount": sgst,
            "ledger_id": _require_ledger(db, co_id, doc_type, LINE_TYPES["SGST_INPUT"]),
            "narration": "SGST Input",
        })
    if igst > 0:
        entry.append({
            "line_type": LINE_TYPES["IGST_INPUT"], "dr_cr": DR, "amount": igst,
            "ledger_id": _require_ledger(db, co_id, doc_type, LINE_TYPES["IGST_INPUT"]),
            "narration": "IGST Input",
        })
    if round_off != 0:
        entry.append({
            "line_type": LINE_TYPES["ROUND_OFF"],
            "dr_cr": DR if round_off > 0 else CR,
            "amount": abs(round_off),
            "ledger_id": _require_ledger(db, co_id, doc_type, LINE_TYPES["ROUND_OFF"]),
            "narration": "Round off",
        })
    entry.append({
        "line_type": LINE_TYPES["CREDITOR"], "dr_cr": CR, "amount": creditor_amount,
        "ledger_id": party_ledger, "party_id": supplier_id, "is_party_leg": True,
        "narration": f"Payable — invoice {h['invoice_no'] or h['sr_no'] or inward_id}",
    })

    voucher_date = h["invoice_date"] or h["billpass_date"] or h["inward_date"] or date.today()
    bill_no = h["invoice_no"] or h["sr_no"] or str(inward_id)
    bill_date = h["invoice_date"] or voucher_date

    # Due date: invoice_due_date, else invoice_date + PO credit days (via the
    # inward_dtl -> proc_po_dtl -> proc_po chain), else default_credit_days.
    credit_days_row = db.execute(
        text("""
            SELECT pp.credit_days
            FROM proc_inward_dtl pid
            INNER JOIN proc_po_dtl ppd ON ppd.po_dtl_id = pid.po_dtl_id
            INNER JOIN proc_po pp ON pp.po_id = ppd.po_id
            WHERE pid.inward_id = :inward_id AND pp.credit_days IS NOT NULL
            LIMIT 1
        """),
        {"inward_id": int(inward_id)},
    ).fetchone()
    po_credit_days = credit_days_row._mapping["credit_days"] if credit_days_row else None
    due_date = _derive_due_date(settings, h["invoice_due_date"], bill_date, po_credit_days)

    narration = (
        f"Auto-posted: procurement bill pass for inward {inward_id}"
        f" — invoice {h['invoice_no'] or 'N/A'}"
    )
    voucher_id, voucher_no, party_line_id, total_dr = _write_voucher(
        db, co_id=co_id, branch_id=h["branch_id"], type_category="PURCHASE",
        voucher_date=voucher_date, party_id=supplier_id,
        ref_no=h["invoice_no"] or h["sr_no"], ref_date=h["invoice_date"],
        narration=narration, entry=entry,
        source_doc_type=doc_type, source_doc_id=inward_id, mode=mode, user_id=user_id,
    )

    if (cgst + sgst + igst) > 0:
        _insert_gst_summary(
            db, voucher_id=voucher_id, taxable=_r2(taxable_lines + taxable_addl),
            cgst=cgst, sgst=sgst, igst=igst, user_id=user_id,
        )

    _insert_bill_ref(
        db, co_id=co_id, voucher_id=voucher_id, voucher_line_id=party_line_id,
        party_id=supplier_id, ref_type="NEW", bill_no=bill_no, bill_date=bill_date,
        due_date=due_date, amount=creditor_amount, pending_amount=creditor_amount,
        status="OPEN", user_id=user_id,
    )

    message = f"Purchase voucher {voucher_no} posted for inward {inward_id} (₹{total_dr:,.2f})"
    return voucher_id, message, {"voucher_no": voucher_no}


# =============================================================================
# RECIPE: DR/CR NOTE  (source = drcr_note, id = debit_credit_note_id)
# =============================================================================

def _recipe_drcr_note(db: Session, co_id: int, note_id: int, user_id: int,
                      settings: dict, mode: str):
    """
    adjustment_type 1 (Debit note — supplier owes us):
        DR party ledger net_amount; CR MATERIAL base; CR *_INPUT GST reversals.
        Settles against the inward's PURCHASE voucher bill ref when it exists.
    adjustment_type 2 (Credit note — we owe more):
        mirror entry; creates a NEW payable bill ref.
    """
    doc_type = SOURCE_DOC_TYPES["DRCR_NOTE"]
    hdr = db.execute(
        text("""
            SELECT dn.debit_credit_note_id, dn.adjustment_type, dn.inward_id,
                   dn.date AS note_date, dn.net_amount, dn.gross_amount, dn.status_id,
                   pi.supplier_id, pi.branch_id, pi.invoice_no, bm.co_id AS co_id
            FROM drcr_note dn
            INNER JOIN proc_inward pi ON pi.inward_id = dn.inward_id
            INNER JOIN branch_mst bm ON bm.branch_id = pi.branch_id
            WHERE dn.debit_credit_note_id = :note_id
        """),
        {"note_id": int(note_id)},
    ).fetchone()
    if not hdr:
        raise PostingError(f"DRCR note {note_id} not found")
    h = hdr._mapping
    if h["status_id"] != STATUS_APPROVED:
        raise PostingError(f"DRCR note {note_id} is not approved (status {h['status_id']})")
    supplier_id = h["supplier_id"]
    if not supplier_id:
        raise PostingError(f"DRCR note {note_id}: inward has no supplier")
    adjustment_type = int(h["adjustment_type"] or 0)
    if adjustment_type not in (1, 2):
        raise PostingError(f"DRCR note {note_id}: unknown adjustment_type {h['adjustment_type']}")

    net_amount = _r2(h["net_amount"] if h["net_amount"] is not None else h["gross_amount"])
    if net_amount <= 0:
        raise PostingError(f"DRCR note {note_id}: net amount is zero — nothing to post")

    gst_row = db.execute(
        text("""
            SELECT COALESCE(SUM(dng.cgst_amount), 0) AS cgst,
                   COALESCE(SUM(dng.sgst_amount), 0) AS sgst,
                   COALESCE(SUM(dng.igst_amount), 0) AS igst
            FROM drcr_note_dtl dnd
            INNER JOIN drcr_note_dtl_gst dng ON dng.drcr_note_dtl_id = dnd.drcr_note_dtl_id
            WHERE dnd.debit_credit_note_id = :note_id
              AND (dng.active = 1 OR dng.active IS NULL)
        """),
        {"note_id": int(note_id)},
    ).fetchone()
    cgst = _r2(gst_row._mapping["cgst"] if gst_row else 0)
    sgst = _r2(gst_row._mapping["sgst"] if gst_row else 0)
    igst = _r2(gst_row._mapping["igst"] if gst_row else 0)
    base_amount = _r2(net_amount - cgst - sgst - igst)
    if base_amount < 0:
        raise PostingError(
            f"DRCR note {note_id}: GST total ({_r2(cgst + sgst + igst)}) exceeds "
            f"net amount ({net_amount})"
        )

    party_ledger = _get_party_ledger(db, co_id, supplier_id)
    material_ledger = _require_ledger(db, co_id, doc_type, LINE_TYPES["MATERIAL"])

    is_debit_note = adjustment_type == 1
    party_side = DR if is_debit_note else CR
    other_side = CR if is_debit_note else DR

    entry = [{
        "line_type": LINE_TYPES["CREDITOR"], "dr_cr": party_side, "amount": net_amount,
        "ledger_id": party_ledger, "party_id": supplier_id, "is_party_leg": True,
        "narration": f"{'Debit' if is_debit_note else 'Credit'} note against inward {h['inward_id']}",
    }]
    if base_amount > 0:
        entry.append({
            "line_type": LINE_TYPES["MATERIAL"], "dr_cr": other_side, "amount": base_amount,
            "ledger_id": material_ledger, "narration": "Purchase adjustment",
        })
    if cgst > 0:
        entry.append({
            "line_type": LINE_TYPES["CGST_INPUT"], "dr_cr": other_side, "amount": cgst,
            "ledger_id": _require_ledger(db, co_id, doc_type, LINE_TYPES["CGST_INPUT"]),
            "narration": "CGST Input adjustment",
        })
    if sgst > 0:
        entry.append({
            "line_type": LINE_TYPES["SGST_INPUT"], "dr_cr": other_side, "amount": sgst,
            "ledger_id": _require_ledger(db, co_id, doc_type, LINE_TYPES["SGST_INPUT"]),
            "narration": "SGST Input adjustment",
        })
    if igst > 0:
        entry.append({
            "line_type": LINE_TYPES["IGST_INPUT"], "dr_cr": other_side, "amount": igst,
            "ledger_id": _require_ledger(db, co_id, doc_type, LINE_TYPES["IGST_INPUT"]),
            "narration": "IGST Input adjustment",
        })

    voucher_date = h["note_date"] or date.today()
    note_prefix = "DN" if is_debit_note else "CN"
    note_year = voucher_date.year if hasattr(voucher_date, "year") else date.today().year
    bill_no = f"{note_prefix}-{note_year}-{int(note_id):05d}"
    type_category = "DEBIT_NOTE" if is_debit_note else "CREDIT_NOTE"

    narration = (
        f"Auto-posted: {'debit' if is_debit_note else 'credit'} note {bill_no} "
        f"against inward {h['inward_id']} (invoice {h['invoice_no'] or 'N/A'})"
    )
    voucher_id, voucher_no, party_line_id, total_dr = _write_voucher(
        db, co_id=co_id, branch_id=h["branch_id"], type_category=type_category,
        voucher_date=voucher_date, party_id=supplier_id,
        ref_no=bill_no, ref_date=voucher_date, narration=narration, entry=entry,
        source_doc_type=doc_type, source_doc_id=note_id, mode=mode, user_id=user_id,
    )

    if (cgst + sgst + igst) > 0:
        _insert_gst_summary(
            db, voucher_id=voucher_id, taxable=base_amount,
            cgst=cgst, sgst=sgst, igst=igst, user_id=user_id,
        )

    if is_debit_note:
        # Reduce the pending amount of the original purchase bill (if posted).
        purchase_ref = db.execute(
            text("""
                SELECT br.acc_bill_ref_id, COALESCE(br.pending_amount, br.amount, 0) AS pending
                FROM acc_bill_ref br
                INNER JOIN acc_voucher v ON v.acc_voucher_id = br.acc_voucher_id
                WHERE v.source_doc_type = :purchase_doc_type
                  AND v.source_doc_id = :inward_id
                  AND v.active = 1
                  AND (v.status_id IS NULL OR v.status_id != :cancelled)
                  AND br.ref_type = 'NEW' AND br.active = 1
                LIMIT 1
            """),
            {
                "purchase_doc_type": SOURCE_DOC_TYPES["PROC_BILLPASS"],
                "inward_id": int(h["inward_id"]),
                "cancelled": STATUS_CANCELLED,
            },
        ).fetchone()

        against_ref_id = _insert_bill_ref(
            db, co_id=co_id, voucher_id=voucher_id, voucher_line_id=party_line_id,
            party_id=supplier_id, ref_type="AGAINST", bill_no=bill_no,
            bill_date=voucher_date, due_date=None, amount=net_amount,
            pending_amount=0, status="CLOSED", user_id=user_id,
        )
        if purchase_ref:
            pr = purchase_ref._mapping
            new_pending = _r2(float(pr["pending"]) - net_amount)
            new_status = "CLOSED" if new_pending <= 0.005 else "PARTIAL"
            db.execute(
                text("""
                    INSERT INTO acc_bill_settlement
                        (acc_bill_ref_id, settled_against_bill_ref_id, settled_amount,
                         settlement_date, active, updated_by, updated_date_time)
                    VALUES
                        (:bill_ref_id, :against_ref_id, :settled_amount,
                         :settlement_date, 1, :updated_by, :now)
                """),
                {
                    "bill_ref_id": against_ref_id,
                    "against_ref_id": int(pr["acc_bill_ref_id"]),
                    "settled_amount": net_amount,
                    "settlement_date": voucher_date,
                    "updated_by": int(user_id),
                    "now": now_ist(),
                },
            )
            db.execute(
                text("""
                    UPDATE acc_bill_ref
                    SET pending_amount = :pending_amount, status = :status,
                        updated_by = :updated_by, updated_date_time = :now
                    WHERE acc_bill_ref_id = :bill_ref_id
                """),
                {
                    "pending_amount": new_pending,
                    "status": new_status,
                    "updated_by": int(user_id),
                    "now": now_ist(),
                    "bill_ref_id": int(pr["acc_bill_ref_id"]),
                },
            )
    else:
        # Credit note — extra payable to the supplier, shown as a fresh open bill.
        credit_days_row = db.execute(
            text("""
                SELECT pp.credit_days
                FROM proc_inward_dtl pid
                INNER JOIN proc_po_dtl ppd ON ppd.po_dtl_id = pid.po_dtl_id
                INNER JOIN proc_po pp ON pp.po_id = ppd.po_id
                WHERE pid.inward_id = :inward_id AND pp.credit_days IS NOT NULL
                LIMIT 1
            """),
            {"inward_id": int(h["inward_id"])},
        ).fetchone()
        po_credit_days = credit_days_row._mapping["credit_days"] if credit_days_row else None
        due_date = _derive_due_date(settings, None, voucher_date, po_credit_days)
        _insert_bill_ref(
            db, co_id=co_id, voucher_id=voucher_id, voucher_line_id=party_line_id,
            party_id=supplier_id, ref_type="NEW", bill_no=bill_no,
            bill_date=voucher_date, due_date=due_date, amount=net_amount,
            pending_amount=net_amount, status="OPEN", user_id=user_id,
        )

    message = (
        f"{'Debit' if is_debit_note else 'Credit'} note voucher {voucher_no} posted "
        f"for note {note_id} (₹{total_dr:,.2f})"
    )
    return voucher_id, message, {"voucher_no": voucher_no}


# =============================================================================
# RECIPE: JUTE BILL PASS  (source = jute_mr, id = jute_mr_id)
# =============================================================================

def _recipe_jute_billpass(db: Session, co_id: int, jute_mr_id: int, user_id: int,
                          settings: dict, mode: str):
    """
    Gross purchase + claim-recovery + TDS legs (owner decisions 2 & 3):
        DR MATERIAL total_amount
        DR/CR ROUND_OFF (recomputed TDS-aware roundoff)
        CR CLAIMS claim_amount (if > 0)
        CR TDS tds_amount (if > 0)
        CR party ledger net_total  (net = total - claim - tds + roundoff)
    Plus, when frieght_paid > 0 (production-typo column name — kept):
        a second PAYMENT voucher (source_doc_type JUTE_FREIGHT):
        DR FREIGHT frieght_paid / CR CASH frieght_paid — no bill ref.
    """
    doc_type = SOURCE_DOC_TYPES["JUTE_BILLPASS"]
    hdr = db.execute(
        text("""
            SELECT jm.jute_mr_id, jm.branch_id, bm.co_id AS co_id,
                   CAST(jm.party_id AS UNSIGNED) AS party_id_int,
                   jm.total_amount, jm.claim_amount, jm.tds_amount, jm.frieght_paid,
                   jm.invoice_no, jm.invoice_date, jm.jute_mr_date,
                   jm.payment_due_date, jm.bill_pass_no, jm.po_id
            FROM jute_mr jm
            INNER JOIN branch_mst bm ON bm.branch_id = jm.branch_id
            WHERE jm.jute_mr_id = :jute_mr_id
        """),
        {"jute_mr_id": int(jute_mr_id)},
    ).fetchone()
    if not hdr:
        raise PostingError(f"Jute MR {jute_mr_id} not found")
    h = hdr._mapping
    party_id = int(h["party_id_int"] or 0)
    if not party_id:
        raise PostingError(f"Jute MR {jute_mr_id} has no numeric party_id — cannot post")

    total_amount = _r2(h["total_amount"])
    claim_amount = _r2(h["claim_amount"])
    tds_amount = _r2(h["tds_amount"])
    if total_amount <= 0:
        raise PostingError(f"Jute MR {jute_mr_id}: total amount is zero — nothing to post")

    # Defensive recompute (owner decision 2 — TDS must be deducted from net).
    roundoff, net_total = compute_jute_totals(total_amount, claim_amount, tds_amount)
    if net_total <= 0:
        raise PostingError(
            f"Jute MR {jute_mr_id}: computed net payable is {net_total} "
            f"(total {total_amount} - claim {claim_amount} - TDS {tds_amount})"
        )

    party_ledger = _get_party_ledger(db, co_id, party_id)

    # MATERIAL ledger: honour an item-group-specific rule only when all line
    # items share one item group (header total is client-editable, so a
    # per-group split cannot be reconciled against it safely).
    grp_rows = db.execute(
        text("""
            SELECT DISTINCT im.item_grp_id AS item_grp_id
            FROM jute_mr_li jml
            LEFT JOIN item_mst im
                   ON im.item_id = COALESCE(jml.actual_item_id, jml.challan_item_id)
            WHERE jml.jute_mr_id = :jute_mr_id
              AND (jml.active = 1 OR jml.active IS NULL)
        """),
        {"jute_mr_id": int(jute_mr_id)},
    ).fetchall()
    distinct_groups = {r._mapping["item_grp_id"] for r in grp_rows}
    single_group = distinct_groups.pop() if len(distinct_groups) == 1 else None
    material_split = _resolve_split_ledgers(
        db, co_id, doc_type, LINE_TYPES["MATERIAL"], {single_group: total_amount}
    )

    entry = []
    for ledger_id, amount in material_split.items():
        entry.append({
            "line_type": LINE_TYPES["MATERIAL"], "dr_cr": DR, "amount": amount,
            "ledger_id": ledger_id, "narration": "Jute purchase (gross)",
        })
    if roundoff != 0:
        entry.append({
            "line_type": LINE_TYPES["ROUND_OFF"],
            "dr_cr": DR if roundoff > 0 else CR,
            "amount": abs(roundoff),
            "ledger_id": _require_ledger(db, co_id, doc_type, LINE_TYPES["ROUND_OFF"]),
            "narration": "Round off",
        })
    if claim_amount > 0:
        entry.append({
            "line_type": LINE_TYPES["CLAIMS"], "dr_cr": CR, "amount": claim_amount,
            "ledger_id": _require_ledger(db, co_id, doc_type, LINE_TYPES["CLAIMS"]),
            "narration": "Claim recovery",
        })
    if tds_amount > 0:
        entry.append({
            "line_type": LINE_TYPES["TDS"], "dr_cr": CR, "amount": tds_amount,
            "ledger_id": _require_ledger(db, co_id, doc_type, LINE_TYPES["TDS"]),
            "narration": "TDS deducted",
        })
    entry.append({
        "line_type": LINE_TYPES["CREDITOR"], "dr_cr": CR, "amount": net_total,
        "ledger_id": party_ledger, "party_id": party_id, "is_party_leg": True,
        "narration": f"Payable — jute MR {jute_mr_id}",
    })

    bill_date = h["invoice_date"] or h["jute_mr_date"] or date.today()
    voucher_date = bill_date
    bill_no = h["invoice_no"] or (str(h["bill_pass_no"]) if h["bill_pass_no"] else str(jute_mr_id))

    # Due date: payment_due_date, else bill date + jute PO credit_term
    # (jute_mr.po_id -> jute_po.jute_po_id), else default_credit_days.
    po_credit_days = None
    if h["po_id"]:
        credit_row = db.execute(
            text("""
                SELECT jp.credit_term FROM jute_po jp
                WHERE jp.jute_po_id = :po_id
                LIMIT 1
            """),
            {"po_id": int(h["po_id"])},
        ).fetchone()
        po_credit_days = credit_row._mapping["credit_term"] if credit_row else None
    due_date = _derive_due_date(settings, h["payment_due_date"], bill_date, po_credit_days)

    narration = (
        f"Auto-posted: jute bill pass for MR {jute_mr_id}"
        f" — invoice {h['invoice_no'] or 'N/A'}"
    )
    voucher_id, voucher_no, party_line_id, total_dr = _write_voucher(
        db, co_id=co_id, branch_id=h["branch_id"], type_category="PURCHASE",
        voucher_date=voucher_date, party_id=party_id,
        ref_no=h["invoice_no"], ref_date=h["invoice_date"],
        narration=narration, entry=entry,
        source_doc_type=doc_type, source_doc_id=jute_mr_id, mode=mode, user_id=user_id,
    )

    _insert_bill_ref(
        db, co_id=co_id, voucher_id=voucher_id, voucher_line_id=party_line_id,
        party_id=party_id, ref_type="NEW", bill_no=bill_no, bill_date=bill_date,
        due_date=due_date, amount=net_total, pending_amount=net_total,
        status="OPEN", user_id=user_id,
    )

    extras = {"voucher_no": voucher_no}
    message = f"Jute purchase voucher {voucher_no} posted for MR {jute_mr_id} (₹{total_dr:,.2f})"

    # Freight paid in cash -> separate PAYMENT voucher (JUTE_FREIGHT).
    frieght_paid = _r2(h["frieght_paid"])
    if frieght_paid > 0:
        freight_doc_type = SOURCE_DOC_TYPES["JUTE_FREIGHT"]
        existing_freight = _existing_voucher_id(db, freight_doc_type, jute_mr_id)
        if existing_freight:
            extras["freight_acc_voucher_id"] = existing_freight
        else:
            freight_entry = [
                {
                    "line_type": LINE_TYPES["FREIGHT"], "dr_cr": DR, "amount": frieght_paid,
                    "ledger_id": _require_ledger(db, co_id, freight_doc_type, LINE_TYPES["FREIGHT"]),
                    "narration": f"Freight paid — jute MR {jute_mr_id}",
                },
                {
                    "line_type": LINE_TYPES["CASH"], "dr_cr": CR, "amount": frieght_paid,
                    "ledger_id": _get_cash_ledger(db, co_id, freight_doc_type),
                    "narration": "Cash paid for freight",
                },
            ]
            freight_voucher_id, freight_voucher_no, _, _ = _write_voucher(
                db, co_id=co_id, branch_id=h["branch_id"], type_category="PAYMENT",
                voucher_date=voucher_date, party_id=None,
                ref_no=bill_no, ref_date=h["invoice_date"],
                narration=f"Auto-posted: freight paid in cash for jute MR {jute_mr_id}",
                entry=freight_entry, source_doc_type=freight_doc_type,
                source_doc_id=jute_mr_id, mode=mode, user_id=user_id,
            )
            extras["freight_acc_voucher_id"] = freight_voucher_id
            extras["freight_voucher_no"] = freight_voucher_no
            message += f"; freight payment voucher {freight_voucher_no} (₹{frieght_paid:,.2f})"

    return voucher_id, message, extras


# =============================================================================
# RECIPE: SALES INVOICE  (source = sales_invoice, id = invoice_id)
# =============================================================================

def _recipe_sales_invoice(db: Session, co_id: int, invoice_id: int, user_id: int,
                          settings: dict, mode: str):
    """
    DR party ledger invoice_amount (debtor)
    DR CLAIMS claim (jute-type invoices, owner decision 3 — gross sale + claim leg)
    CR REVENUE taxable (lines + additional charges, split by item group)
    CR CGST_OUTPUT / SGST_OUTPUT / IGST_OUTPUT
    CR/DR ROUND_OFF — the exact difference so the voucher balances (validated
    against header totals within ±1.00 since those are FE-computed).
    """
    doc_type = SOURCE_DOC_TYPES["SALES_INVOICE"]
    hdr = db.execute(
        text("""
            SELECT si.invoice_id, si.branch_id, bm.co_id AS co_id, si.party_id,
                   si.invoice_no, si.invoice_date, si.due_date, si.payment_terms,
                   si.invoice_amount, si.round_off
            FROM sales_invoice si
            INNER JOIN branch_mst bm ON bm.branch_id = si.branch_id
            WHERE si.invoice_id = :invoice_id
        """),
        {"invoice_id": int(invoice_id)},
    ).fetchone()
    if not hdr:
        raise PostingError(f"Sales invoice {invoice_id} not found")
    h = hdr._mapping
    party_id = h["party_id"]
    if not party_id:
        raise PostingError(f"Sales invoice {invoice_id} has no party — cannot post")

    debtor_amount = _r2(h["invoice_amount"])
    if debtor_amount <= 0:
        raise PostingError(f"Sales invoice {invoice_id}: invoice amount is zero — nothing to post")
    header_round_off = _r2(h["round_off"])

    # Taxable per item group (sales_invoice_dtl has no active flag).
    group_rows = db.execute(
        text("""
            SELECT im.item_grp_id AS item_grp_id,
                   COALESCE(SUM(COALESCE(sid.amount_without_tax, 0)), 0) AS taxable
            FROM sales_invoice_dtl sid
            LEFT JOIN item_mst im ON im.item_id = sid.item_id
            WHERE sid.invoice_id = :invoice_id
            GROUP BY im.item_grp_id
        """),
        {"invoice_id": int(invoice_id)},
    ).fetchall()
    group_amounts = {
        r._mapping["item_grp_id"]: _r2(r._mapping["taxable"]) for r in group_rows
    }
    taxable_lines = _r2(sum(group_amounts.values()))

    addl_row = db.execute(
        text("""
            SELECT COALESCE(SUM(
                COALESCE(sia.net_amount, COALESCE(sia.qty, 0) * COALESCE(sia.rate, 0))
            ), 0) AS additional_net
            FROM sales_invoice_additional sia
            WHERE sia.invoice_id = :invoice_id
        """),
        {"invoice_id": int(invoice_id)},
    ).fetchone()
    taxable_addl = _r2(addl_row._mapping["additional_net"] if addl_row else 0)
    if taxable_addl != 0:
        group_amounts[None] = _r2(group_amounts.get(None, 0.0) + taxable_addl)
    taxable_total = _r2(taxable_lines + taxable_addl)

    # GST: line GST joins on invoice_line_item_id; additional-charge GST joins
    # on sales_invoice_additional_id.
    gst_dtl = db.execute(
        text("""
            SELECT COALESCE(SUM(sg.cgst_amount), 0) AS cgst,
                   COALESCE(SUM(sg.sgst_amount), 0) AS sgst,
                   COALESCE(SUM(sg.igst_amount), 0) AS igst
            FROM sales_invoice_dtl_gst sg
            INNER JOIN sales_invoice_dtl sid
                    ON sid.invoice_line_item_id = sg.invoice_line_item_id
            WHERE sid.invoice_id = :invoice_id
        """),
        {"invoice_id": int(invoice_id)},
    ).fetchone()
    gst_addl = db.execute(
        text("""
            SELECT COALESCE(SUM(sag.cgst_amount), 0) AS cgst,
                   COALESCE(SUM(sag.sgst_amount), 0) AS sgst,
                   COALESCE(SUM(sag.igst_amount), 0) AS igst
            FROM sales_invoice_additional_gst sag
            INNER JOIN sales_invoice_additional sia
                    ON sia.sales_invoice_additional_id = sag.sales_invoice_additional_id
            WHERE sia.invoice_id = :invoice_id
        """),
        {"invoice_id": int(invoice_id)},
    ).fetchone()
    cgst = _r2(float(gst_dtl._mapping["cgst"] or 0) + float(gst_addl._mapping["cgst"] or 0))
    sgst = _r2(float(gst_dtl._mapping["sgst"] or 0) + float(gst_addl._mapping["sgst"] or 0))
    igst = _r2(float(gst_dtl._mapping["igst"] or 0) + float(gst_addl._mapping["igst"] or 0))
    gst_total = _r2(cgst + sgst + igst)

    # Jute-type claim (sales_invoice_jute header extension; 0 when absent).
    claim_row = db.execute(
        text("""
            SELECT COALESCE(sij.claim_amount, 0) AS claim_amount
            FROM sales_invoice_jute sij
            WHERE sij.invoice_id = :invoice_id
            LIMIT 1
        """),
        {"invoice_id": int(invoice_id)},
    ).fetchone()
    claim_amount = _r2(claim_row._mapping["claim_amount"] if claim_row else 0)

    # Validate header vs computed totals (FE computes the header) within ±1.00,
    # then post the exact residual into ROUND_OFF so the voucher balances.
    dr_side = _r2(debtor_amount + claim_amount)
    cr_side = _r2(taxable_total + gst_total + header_round_off)
    if abs(dr_side - cr_side) > SALES_HEADER_TOLERANCE:
        raise PostingError(
            f"Sales invoice {invoice_id} totals inconsistent: DR side "
            f"(invoice_amount {debtor_amount} + claim {claim_amount}) = {dr_side} vs "
            f"CR side (taxable {taxable_total} + GST {gst_total} + "
            f"round_off {header_round_off}) = {cr_side} — difference exceeds ±1.00"
        )
    effective_round_off = _r2(dr_side - taxable_total - gst_total)

    party_ledger = _get_party_ledger(db, co_id, party_id)
    revenue_split = _resolve_split_ledgers(
        db, co_id, doc_type, LINE_TYPES["REVENUE"], group_amounts
    )

    entry = [{
        "line_type": LINE_TYPES["DEBTOR"], "dr_cr": DR, "amount": debtor_amount,
        "ledger_id": party_ledger, "party_id": party_id, "is_party_leg": True,
        "narration": f"Receivable — invoice {h['invoice_no'] or invoice_id}",
    }]
    if claim_amount > 0:
        entry.append({
            "line_type": LINE_TYPES["CLAIMS"], "dr_cr": DR, "amount": claim_amount,
            "ledger_id": _require_ledger(db, co_id, doc_type, LINE_TYPES["CLAIMS"]),
            "narration": "Claim on sale",
        })
    for ledger_id, amount in revenue_split.items():
        entry.append({
            "line_type": LINE_TYPES["REVENUE"], "dr_cr": CR, "amount": amount,
            "ledger_id": ledger_id, "narration": "Sales revenue",
        })
    if cgst > 0:
        entry.append({
            "line_type": LINE_TYPES["CGST_OUTPUT"], "dr_cr": CR, "amount": cgst,
            "ledger_id": _require_ledger(db, co_id, doc_type, LINE_TYPES["CGST_OUTPUT"]),
            "narration": "CGST Output",
        })
    if sgst > 0:
        entry.append({
            "line_type": LINE_TYPES["SGST_OUTPUT"], "dr_cr": CR, "amount": sgst,
            "ledger_id": _require_ledger(db, co_id, doc_type, LINE_TYPES["SGST_OUTPUT"]),
            "narration": "SGST Output",
        })
    if igst > 0:
        entry.append({
            "line_type": LINE_TYPES["IGST_OUTPUT"], "dr_cr": CR, "amount": igst,
            "ledger_id": _require_ledger(db, co_id, doc_type, LINE_TYPES["IGST_OUTPUT"]),
            "narration": "IGST Output",
        })
    if effective_round_off != 0:
        entry.append({
            "line_type": LINE_TYPES["ROUND_OFF"],
            "dr_cr": CR if effective_round_off > 0 else DR,
            "amount": abs(effective_round_off),
            "ledger_id": _require_ledger(db, co_id, doc_type, LINE_TYPES["ROUND_OFF"]),
            "narration": "Round off",
        })

    voucher_date = h["invoice_date"] or date.today()
    bill_no = str(h["invoice_no"]) if h["invoice_no"] else str(invoice_id)
    due_date = _derive_due_date(settings, h["due_date"], voucher_date, h["payment_terms"])

    narration = f"Auto-posted: sales invoice {bill_no}"
    voucher_id, voucher_no, party_line_id, total_dr = _write_voucher(
        db, co_id=co_id, branch_id=h["branch_id"], type_category="SALES",
        voucher_date=voucher_date, party_id=party_id,
        ref_no=bill_no, ref_date=h["invoice_date"],
        narration=narration, entry=entry,
        source_doc_type=doc_type, source_doc_id=invoice_id, mode=mode, user_id=user_id,
    )

    if gst_total > 0:
        _insert_gst_summary(
            db, voucher_id=voucher_id, taxable=taxable_total,
            cgst=cgst, sgst=sgst, igst=igst, user_id=user_id,
        )

    _insert_bill_ref(
        db, co_id=co_id, voucher_id=voucher_id, voucher_line_id=party_line_id,
        party_id=party_id, ref_type="NEW", bill_no=bill_no,
        bill_date=h["invoice_date"] or voucher_date, due_date=due_date,
        amount=debtor_amount, pending_amount=debtor_amount,
        status="OPEN", user_id=user_id,
    )

    message = f"Sales voucher {voucher_no} posted for invoice {bill_no} (₹{total_dr:,.2f})"
    return voucher_id, message, {"voucher_no": voucher_no}


# =============================================================================
# DISPATCH
# =============================================================================

_RECIPES = {
    SOURCE_DOC_TYPES["PROC_BILLPASS"]: _recipe_proc_billpass,
    SOURCE_DOC_TYPES["DRCR_NOTE"]: _recipe_drcr_note,
    SOURCE_DOC_TYPES["JUTE_BILLPASS"]: _recipe_jute_billpass,
    SOURCE_DOC_TYPES["SALES_INVOICE"]: _recipe_sales_invoice,
}

# co_id resolution per doc type (none of the source headers carry co_id —
# it is always derived via branch_mst.branch_id -> branch_mst.co_id).
_CO_ID_SQL = {
    SOURCE_DOC_TYPES["PROC_BILLPASS"]: """
        SELECT bm.co_id FROM proc_inward pi
        INNER JOIN branch_mst bm ON bm.branch_id = pi.branch_id
        WHERE pi.inward_id = :doc_id
    """,
    SOURCE_DOC_TYPES["DRCR_NOTE"]: """
        SELECT bm.co_id FROM drcr_note dn
        INNER JOIN proc_inward pi ON pi.inward_id = dn.inward_id
        INNER JOIN branch_mst bm ON bm.branch_id = pi.branch_id
        WHERE dn.debit_credit_note_id = :doc_id
    """,
    SOURCE_DOC_TYPES["JUTE_BILLPASS"]: """
        SELECT bm.co_id FROM jute_mr jm
        INNER JOIN branch_mst bm ON bm.branch_id = jm.branch_id
        WHERE jm.jute_mr_id = :doc_id
    """,
    SOURCE_DOC_TYPES["SALES_INVOICE"]: """
        SELECT bm.co_id FROM sales_invoice si
        INNER JOIN branch_mst bm ON bm.branch_id = si.branch_id
        WHERE si.invoice_id = :doc_id
    """,
}


def _resolve_co_id(db: Session, source_doc_type: str, source_doc_id: int):
    sql = _CO_ID_SQL.get(source_doc_type)
    if not sql:
        return None
    row = db.execute(text(sql), {"doc_id": int(source_doc_id)}).fetchone()
    return int(row._mapping["co_id"]) if row and row._mapping["co_id"] else None


def _post_pending_drcr_notes(db: Session, inward_id: int, user_id: int) -> list:
    """After posting a purchase voucher, post any approved DRCR notes on the
    same inward that do not yet have a voucher. Each note gets its own
    post_document call (own queue row, own commit). Never raises."""
    results = []
    try:
        rows = db.execute(
            text("""
                SELECT dn.debit_credit_note_id
                FROM drcr_note dn
                WHERE dn.inward_id = :inward_id
                  AND dn.status_id = :approved
                  AND NOT EXISTS (
                      SELECT 1 FROM acc_voucher v
                      WHERE v.source_doc_type = :drcr_doc_type
                        AND v.source_doc_id = dn.debit_credit_note_id
                        AND v.active = 1
                        AND (v.status_id IS NULL OR v.status_id != :cancelled)
                  )
                ORDER BY dn.debit_credit_note_id
            """),
            {
                "inward_id": int(inward_id),
                "approved": STATUS_APPROVED,
                "drcr_doc_type": SOURCE_DOC_TYPES["DRCR_NOTE"],
                "cancelled": STATUS_CANCELLED,
            },
        ).fetchall()
        for row in rows:
            note_id = int(row._mapping["debit_credit_note_id"])
            note_result = post_document(db, SOURCE_DOC_TYPES["DRCR_NOTE"], note_id, user_id)
            results.append({"drcr_note_id": note_id, **note_result})
    except Exception:
        logger.exception(
            "posting_service: failed while cascading DRCR notes for inward %s", inward_id
        )
    return results


# =============================================================================
# PUBLIC ENTRY POINT
# =============================================================================

def post_document(db: Session, source_doc_type: str, source_doc_id: int, user_id: int) -> dict:
    """
    Post one business document into accounting.

    Returns {"status": "POSTED"|"DRAFTED"|"SKIPPED"|"FAILED",
             "acc_voucher_id": int|None, "message": str}. NEVER raises.
    """
    co_id = 0
    try:
        doc_id = int(source_doc_id)
    except (TypeError, ValueError):
        return _result("FAILED", None, f"Invalid source_doc_id: {source_doc_id!r}")

    try:
        uid = int(user_id) if user_id else 0

        recipe = _RECIPES.get(source_doc_type)
        if recipe is None:
            return _finalize(
                db, 0, source_doc_type, doc_id, "FAILED", None,
                f"Unsupported source_doc_type '{source_doc_type}'", uid,
            )

        co_id = _resolve_co_id(db, source_doc_type, doc_id) or 0
        if not co_id:
            return _finalize(
                db, 0, source_doc_type, doc_id, "FAILED", None,
                f"{source_doc_type} {doc_id} not found or its company could not "
                "be resolved via the branch", uid,
            )

        settings = _load_settings(db, co_id)
        mode = (settings or {}).get(_MODE_FIELDS[source_doc_type]) or MODE_OFF
        if settings is None or mode not in (MODE_AUTO_DRAFT, MODE_AUTO_APPROVED):
            return _finalize(
                db, co_id, source_doc_type, doc_id, "SKIPPED", None,
                (f"Auto-posting is OFF for co_id {co_id} "
                 f"({_MODE_FIELDS[source_doc_type]}={mode})"
                 if settings is not None
                 else f"No acc_company_settings row for co_id {co_id} — posting skipped"),
                uid,
            )

        existing = _existing_voucher_id(db, source_doc_type, doc_id)
        if existing:
            return _finalize(
                db, co_id, source_doc_type, doc_id, "POSTED", existing,
                f"Voucher {existing} already exists for {source_doc_type} {doc_id} "
                "(idempotent skip)", uid,
            )

        if not _is_accounting_activated(db, co_id):
            return _finalize(
                db, co_id, source_doc_type, doc_id, "FAILED", None,
                f"Company {co_id} is not accounting-activated (no voucher types "
                "found) — run accounting activation first", uid,
            )

        voucher_id, message, extras = recipe(db, co_id, doc_id, uid, settings, mode)

        status = "POSTED" if mode == MODE_AUTO_APPROVED else "DRAFTED"
        result = _finalize(db, co_id, source_doc_type, doc_id, status, voucher_id, message, uid)
        if extras:
            for key, value in extras.items():
                result.setdefault(key, value)

        # After a successful purchase posting, cascade approved-but-unposted
        # DRCR notes for the same inward (spec: PROC_BILLPASS recipe step 6).
        if source_doc_type == SOURCE_DOC_TYPES["PROC_BILLPASS"]:
            drcr_results = _post_pending_drcr_notes(db, doc_id, uid)
            if drcr_results:
                result["drcr_notes"] = drcr_results

        return result

    except PostingError as posting_error:
        try:
            db.rollback()
        except Exception:
            pass
        logger.warning(
            "posting_service: posting failed for %s/%s: %s",
            source_doc_type, doc_id, posting_error,
        )
        return _finalize(
            db, co_id, source_doc_type, doc_id, "FAILED", None, str(posting_error), user_id or 0,
        )
    except Exception as unexpected_error:
        try:
            db.rollback()
        except Exception:
            pass
        logger.exception(
            "posting_service: unexpected error for %s/%s", source_doc_type, doc_id
        )
        return _finalize(
            db, co_id, source_doc_type, doc_id, "FAILED", None,
            f"Unexpected error: {unexpected_error}", user_id or 0,
        )
