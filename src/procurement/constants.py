"""
Procurement module constants - single source of truth for indent types.

IMPORTANT: This file must stay in sync with the frontend:
  vowerp3ui/src/app/dashboardportal/procurement/indent/createIndent/utils/indentConstants.ts

When modifying indent types, update BOTH files to maintain consistency.
"""

# =============================================================================
# INDENT TYPE DEFINITIONS
# =============================================================================
# Labels match values for clarity and 100% frontend-backend consistency

INDENT_TYPES = {
    "Regular": {"id": 1, "label": "Regular", "value": "Regular"},
    "Open": {"id": 2, "label": "Open", "value": "Open"},
    "BOM": {"id": 3, "label": "BOM", "value": "BOM"},
}

# Valid indent type values for validation
VALID_INDENT_TYPE_VALUES = list(INDENT_TYPES.keys())

# Mapping from numeric IDs (legacy) to string values
INDENT_TYPE_ID_TO_VALUE = {
    1: "Regular",
    2: "Open",
    3: "BOM",
    "1": "Regular",
    "2": "Open",
    "3": "BOM",
}


def get_indent_type_label(value: str) -> str:
    """Get display label for indent type value."""
    return INDENT_TYPES.get(value, {}).get("label", value)


def normalize_indent_type(indent_type_id) -> str:
    """
    Normalize indent type to string value.
    Handles both string values and legacy numeric IDs.
    """
    if indent_type_id is None:
        return ""
    if isinstance(indent_type_id, str):
        # Already a string - return as-is if valid, otherwise try to map
        if indent_type_id in VALID_INDENT_TYPE_VALUES:
            return indent_type_id
        # Try legacy numeric string mapping
        return INDENT_TYPE_ID_TO_VALUE.get(indent_type_id, indent_type_id)
    # Numeric ID - map to string value
    return INDENT_TYPE_ID_TO_VALUE.get(indent_type_id, str(indent_type_id))


def is_valid_indent_type(value: str) -> bool:
    """Check if a value is a valid indent type."""
    return value in VALID_INDENT_TYPE_VALUES


# =============================================================================
# INDENT STATUS DEFINITIONS  
# =============================================================================

INDENT_STATUS_IDS = {
    "DRAFT": 21,
    "OPEN": 1,
    "PENDING_APPROVAL": 20,
    "APPROVED": 3,
    "REJECTED": 4,
    "CLOSED": 5,
    "CANCELLED": 6,
}

INDENT_STATUS_LABELS = {
    21: "Draft",
    1: "Open",
    20: "Pending Approval",
    3: "Approved",
    4: "Rejected",
    5: "Closed",
    6: "Cancelled",
}
