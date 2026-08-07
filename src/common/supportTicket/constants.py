"""Status, priority, category and lifecycle constants for support tickets.

NOTE: These status ids are a dedicated enum for the support-ticket feature and
are intentionally NOT the global transaction status ids (21/1/20/3/4/6) used by
approval workflows elsewhere in the system.
"""

from typing import Optional, Tuple

# ── Status lifecycle ──────────────────────────────────────────────────────────
STATUS_RAISED = 1        # New, awaiting VOW triage
STATUS_OPEN = 2          # Accepted / assigned, to be worked on
STATUS_IN_PROGRESS = 3   # Developer actively working
STATUS_ON_HOLD = 4       # Blocked / waiting on reporter for more info
STATUS_RESOLVED = 5      # Work done, awaiting confirmation / close
STATUS_CLOSED = 6        # Closed (completed)
STATUS_REJECTED = 7      # Closed without work (invalid / workflow not followed)

STATUS_LABELS = {
    STATUS_RAISED: "Raised",
    STATUS_OPEN: "Open",
    STATUS_IN_PROGRESS: "In Progress",
    STATUS_ON_HOLD: "On Hold",
    STATUS_RESOLVED: "Resolved",
    STATUS_CLOSED: "Closed",
    STATUS_REJECTED: "Rejected",
}

# Statuses that still count as "not done"
OPEN_STATUSES = {STATUS_RAISED, STATUS_OPEN, STATUS_IN_PROGRESS, STATUS_ON_HOLD}
TERMINAL_STATUSES = {STATUS_CLOSED, STATUS_REJECTED}

# ── Priority ──────────────────────────────────────────────────────────────────
PRIORITY_LOW = 1
PRIORITY_MEDIUM = 2
PRIORITY_HIGH = 3
PRIORITY_URGENT = 4

PRIORITY_LABELS = {
    PRIORITY_LOW: "Low",
    PRIORITY_MEDIUM: "Medium",
    PRIORITY_HIGH: "High",
    PRIORITY_URGENT: "Urgent",
}

# ── Category / close reasons ────────────────────────────────────────────────────
CATEGORIES = ["bug", "feature", "question", "data_issue", "other"]

CLOSE_REASONS = [
    "completed",
    "workflow_not_followed",
    "duplicate",
    "cannot_reproduce",
    "invalid",
    "wont_fix",
    "other",
]

# ── Lifecycle transitions ───────────────────────────────────────────────────────
# action -> rule:
#   "from"   : statuses the action may be applied from
#   "to"     : resulting status
#   "reason" : True if a reason is mandatory (stored in close_reason)
#   "notes"  : True if resolution notes are accepted
TRANSITIONS = {
    "open":    {"from": {STATUS_RAISED, STATUS_ON_HOLD}, "to": STATUS_OPEN},
    "start":   {"from": {STATUS_OPEN, STATUS_ON_HOLD}, "to": STATUS_IN_PROGRESS},
    "hold":    {"from": {STATUS_OPEN, STATUS_IN_PROGRESS}, "to": STATUS_ON_HOLD},
    "resume":  {"from": {STATUS_ON_HOLD}, "to": STATUS_OPEN},
    "resolve": {"from": {STATUS_OPEN, STATUS_IN_PROGRESS}, "to": STATUS_RESOLVED, "notes": True},
    "close":   {"from": {STATUS_OPEN, STATUS_IN_PROGRESS, STATUS_RESOLVED}, "to": STATUS_CLOSED, "reason": True, "notes": True},
    "reject":  {"from": {STATUS_RAISED, STATUS_OPEN, STATUS_IN_PROGRESS, STATUS_ON_HOLD}, "to": STATUS_REJECTED, "reason": True},
    "reopen":  {"from": {STATUS_RESOLVED, STATUS_CLOSED, STATUS_REJECTED}, "to": STATUS_OPEN},
}


def validate_raise_fields(priority: int, category: Optional[str]) -> None:
    """Raise ValueError if a raise payload's priority/category are invalid."""
    if priority not in PRIORITY_LABELS:
        raise ValueError("Invalid priority")
    if category and category not in CATEGORIES:
        raise ValueError("Invalid category")


def resolve_transition(current_status: int, action: str) -> Tuple[Optional[int], Optional[str]]:
    """Pure lifecycle resolver.

    Returns ``(new_status, None)`` for a valid transition or
    ``(None, error_message)`` if the action is unknown or not allowed from the
    current status.
    """
    rule = TRANSITIONS.get(action)
    if not rule:
        return None, f"Unknown action '{action}'"
    if current_status not in rule["from"]:
        return None, (
            f"Cannot '{action}' a ticket that is "
            f"{STATUS_LABELS.get(current_status, current_status)}"
        )
    return rule["to"], None


def transition_requires_reason(action: str) -> bool:
    return bool(TRANSITIONS.get(action, {}).get("reason"))


def build_meta() -> dict:
    """Reference data the frontend uses to render dropdowns / badges."""
    return {
        "statuses": [{"id": k, "label": v} for k, v in STATUS_LABELS.items()],
        "priorities": [{"id": k, "label": v} for k, v in PRIORITY_LABELS.items()],
        "categories": CATEGORIES,
        "close_reasons": CLOSE_REASONS,
        "actions": list(TRANSITIONS.keys()),
    }


# ── Attachments (screenshots + documents) ───────────────────────────────────────
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024  # 10 MB per file

# Allowed upload MIME types -> (kind, file extension). Screenshots (images) and
# common document types. kind is used by the UI to render thumbnails vs links.
ATTACHMENT_MIME_EXT = {
    "image/png": ("image", "png"),
    "image/jpeg": ("image", "jpg"),
    "image/jpg": ("image", "jpg"),
    "image/gif": ("image", "gif"),
    "image/webp": ("image", "webp"),
    "application/pdf": ("document", "pdf"),
    "application/msword": ("document", "doc"),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ("document", "docx"),
    "application/vnd.ms-excel": ("document", "xls"),
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ("document", "xlsx"),
    "application/vnd.ms-powerpoint": ("document", "ppt"),
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ("document", "pptx"),
    "text/csv": ("document", "csv"),
    "text/plain": ("document", "txt"),
}


def attachment_kind_ext(mime: Optional[str]) -> Optional[Tuple[str, str]]:
    """Return ``(kind, ext)`` for an allowed MIME type, else ``None``."""
    if not mime:
        return None
    return ATTACHMENT_MIME_EXT.get(mime.lower())

