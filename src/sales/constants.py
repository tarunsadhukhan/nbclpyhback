"""
Sales module constants - single source of truth for sales status IDs and document types.
"""

# =============================================================================
# SALES STATUS DEFINITIONS
# =============================================================================

SALES_STATUS_IDS = {
    "DRAFT": 21,
    "OPEN": 1,
    "PENDING_APPROVAL": 20,
    "APPROVED": 3,
    "REJECTED": 4,
    "CLOSED": 5,
    "CANCELLED": 6,
}

SALES_STATUS_LABELS = {
    21: "Draft",
    1: "Open",
    20: "Pending Approval",
    3: "Approved",
    4: "Rejected",
    5: "Closed",
    6: "Cancelled",
}

# =============================================================================
# DOCUMENT TYPE CODES (used in document number generation)
# =============================================================================

SALES_DOC_TYPES = {
    "QUOTATION": "SQ",
    "SALES_ORDER": "SO",
    "DELIVERY_ORDER": "DO",
    "INVOICE": "SI",
    "ENQUIRY": "ENQ",
}

# =============================================================================
# INVOICE TYPE IDS (canonical, matches invoice_type_mst seed)
# =============================================================================
# These ids are the authoritative mapping as stored in `invoice_type_mst`:
#   1 -> Regular
#   2 -> Hessian
#   3 -> Govt Sacking
#   4 -> Yarn          (Jute Yarn)
#   5 -> Raw Jute
#   7 -> Govt Sacking Freight
#
# All sales-module code must use these ids (via INVOICE_TYPE_IDS below) and
# NEVER hard-code numeric literals like `if invoice_type == 5`. If the seed
# ever changes, update this file in one place.

INVOICE_TYPE_IDS = {
    "REGULAR": 1,
    "HESSIAN": 2,
    "GOVT_SKG": 3,
    "JUTE_YARN": 4,
    "RAW_JUTE": 5,
    "GOVT_SKG_FREIGHT": 7,
}

# Canonical string codes used to branch type-specific logic. Keeping a
# string layer keeps call sites self-documenting (`== INVOICE_TYPE_CODES["GOVT_SKG"]`
# reads clearly) and decouples the branching logic from the raw numeric ids.
INVOICE_TYPE_CODES = {
    "REGULAR": "REGULAR",
    "HESSIAN": "HESSIAN",
    "GOVT_SKG": "GOVT_SKG",
    "JUTE_YARN": "JUTE_YARN",
    "RAW_JUTE": "RAW_JUTE",
    "GOVT_SKG_FREIGHT": "GOVT_SKG_FREIGHT",
    "UNKNOWN": "UNKNOWN",
}

# Reverse lookup: numeric id -> canonical code. Built from INVOICE_TYPE_IDS so
# the two mappings can never drift.
_INVOICE_TYPE_ID_TO_CODE = {id_: code for code, id_ in INVOICE_TYPE_IDS.items()}


def resolve_invoice_type_code(invoice_type_id) -> str:
    """Return the canonical INVOICE_TYPE_CODES value for a numeric
    `invoice_type_id` as stored in `invoice_type_mst`.

    Pure lookup — no database call. Returns INVOICE_TYPE_CODES["UNKNOWN"] if
    the id is None or not one of the canonical ids.
    """
    if invoice_type_id is None:
        return INVOICE_TYPE_CODES["UNKNOWN"]
    try:
        invoice_type_id_int = int(invoice_type_id)
    except (TypeError, ValueError):
        return INVOICE_TYPE_CODES["UNKNOWN"]
    return _INVOICE_TYPE_ID_TO_CODE.get(invoice_type_id_int, INVOICE_TYPE_CODES["UNKNOWN"])


def is_govt_skg_invoice(invoice_type_id) -> bool:
    """Convenience: True iff invoice_type_id resolves to Govt Sacking."""
    return resolve_invoice_type_code(invoice_type_id) == INVOICE_TYPE_CODES["GOVT_SKG"]
