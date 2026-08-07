"""
Stage-engine helpers for the sales-enquiry flow (AMCL enquiry-to-delivery).

Pure-Python helpers that run INSIDE the caller's open SQLAlchemy session /
transaction — they never commit or roll back; the calling router owns the
transaction boundary (design §4: automatic transitions are synchronous hooks
in the same DB transaction as the triggering action).

No FastAPI handlers live in this file. HTTPException is raised only to signal
validation failures (400/403) or missing configuration (404/500) back through
the calling handler.

Rules enforced here (docs/amcl-enquiry-flow-design.md §4):
- FORWARD only to a stage in ALLOWED_FORWARD[current]; leaving ENQ_NOTED
  additionally requires the enquiry itself to be Approved (status 3 — Q4 gate).
- SEND_BACK to any strictly earlier stage; feedback text mandatory.
- HOLD / RESUME keep the stage unchanged.
- MARK_LOST only from stages with sequence <= MARK_LOST_MAX_SEQUENCE (50).
- CLOSE from any non-terminal stage (won at the end of the chain, or
  cancelled mid-flow — the router validates the business close_reason).
- AUTO (system hooks) may re-log the current stage or move forward, never back.
- No transitions out of terminal stages (CLOSED / LOST).
"""

import logging

from fastapi import HTTPException
from sqlalchemy.orm import Session

from src.common.utils import now_ist
from src.sales.enquiry_constants import (
    ACTION_AUTO,
    ACTION_CLOSE,
    ACTION_CREATE,
    ACTION_FORWARD,
    ACTION_HOLD,
    ACTION_MARK_LOST,
    ACTION_RESUME,
    ACTION_SEND_BACK,
    ALLOWED_FORWARD,
    ENQUIRY_ACTIONS,
    ENQUIRY_FLOW_DOC_TYPE,
    FLOW_MODULE_ENQUIRY,
    FORWARD_GATE_STATUS_ID,
    LINKED_DOC_QUOTATION,
    LINKED_DOC_SALES_ORDER,
    LINKED_DOC_TYPE_SET,
    MARK_LOST_MAX_SEQUENCE,
    STAGE_CLOSED,
    STAGE_ENQ_NOTED,
    STAGE_LOST,
    STAGE_ORDER_CONFIRMED,
    STAGE_SEQUENCE,
    TERMINAL_STAGES,
)
from src.sales.enquiry_query import (
    get_enquiry_flow_state_query,
    get_quotation_enquiry_link_query,
    get_sales_order_enquiry_link_query,
    get_stage_by_code_query,
    get_stage_by_id_query,
    insert_flow_stage_log,
    update_enquiry_current_stage,
)

logger = logging.getLogger(__name__)


# =============================================================================
# STAGE MASTER LOOKUPS
# =============================================================================

def get_stage_row(db: Session, stage_code: str) -> dict:
    """Return the flow_stage_mst row (as a dict) for an ENQUIRY stage code.

    Raises HTTPException(500) if the stage seed is missing — that is a
    deployment/configuration fault, not a client error.
    """
    if not stage_code or stage_code not in STAGE_SEQUENCE:
        raise HTTPException(status_code=400, detail=f"Unknown enquiry stage code: {stage_code}")

    row = db.execute(
        get_stage_by_code_query(),
        {"module": FLOW_MODULE_ENQUIRY, "stage_code": stage_code},
    ).fetchone()
    if not row:
        raise HTTPException(
            status_code=500,
            detail=f"Flow stage '{stage_code}' (module {FLOW_MODULE_ENQUIRY}) is not seeded in flow_stage_mst",
        )
    return dict(row._mapping)


def get_stage_id(db: Session, stage_code: str) -> int:
    """Resolve an ENQUIRY stage code to its flow_stage_mst.stage_id."""
    return int(get_stage_row(db, stage_code)["stage_id"])


def get_stage_code_by_id(db: Session, stage_id) -> str | None:
    """Resolve a flow_stage_mst.stage_id back to its stage code (None if absent)."""
    if stage_id is None:
        return None
    row = db.execute(get_stage_by_id_query(), {"stage_id": int(stage_id)}).fetchone()
    if not row:
        return None
    return dict(row._mapping).get("stage_code")


def _get_enquiry_flow_state(db: Session, sales_enquiry_id: int) -> dict:
    """Fetch the enquiry's workflow + stage state. Raises 404 when missing."""
    row = db.execute(
        get_enquiry_flow_state_query(),
        {"sales_enquiry_id": int(sales_enquiry_id)},
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Enquiry not found")
    return dict(row._mapping)


# =============================================================================
# TRANSITION VALIDATION (pure rules — no DB access)
# =============================================================================

def validate_transition(current_stage_code, action, to_stage_code, enquiry_status_id, feedback) -> None:
    """Validate one stage transition against the design §4 rules.

    Raises HTTPException(400) for invalid/illegal transitions and
    HTTPException(403) for the ENQ_NOTED approval gate. Returns None when the
    transition is legal.

    Args:
        current_stage_code: the enquiry's current stage code (None only before
            the CREATE entry, i.e. the enquiry has not been opened yet)
        action: one of ENQUIRY_ACTIONS
        to_stage_code: target stage code (required for FORWARD / SEND_BACK /
            AUTO; optional for the fixed-target/stage-preserving actions)
        enquiry_status_id: the enquiry's status_id (Q4 gate check)
        feedback: feedback text (mandatory for SEND_BACK)
    """
    if action not in ENQUIRY_ACTIONS:
        raise HTTPException(status_code=400, detail=f"Invalid action: {action}")

    if to_stage_code is not None and to_stage_code not in STAGE_SEQUENCE:
        raise HTTPException(status_code=400, detail=f"Unknown target stage: {to_stage_code}")

    # CREATE is the opening entry: no current stage yet, lands on ENQ_NOTED.
    if action == ACTION_CREATE:
        if current_stage_code is not None:
            raise HTTPException(status_code=400, detail="CREATE is only valid for an enquiry with no current stage")
        if to_stage_code is not None and to_stage_code != STAGE_ENQ_NOTED:
            raise HTTPException(status_code=400, detail=f"CREATE must target {STAGE_ENQ_NOTED}")
        return

    if current_stage_code is None:
        raise HTTPException(status_code=400, detail="Enquiry has no current stage (not opened yet)")
    if current_stage_code not in STAGE_SEQUENCE:
        raise HTTPException(status_code=400, detail=f"Unknown current stage: {current_stage_code}")
    if current_stage_code in TERMINAL_STAGES:
        raise HTTPException(
            status_code=400,
            detail=f"Enquiry is in terminal stage {current_stage_code}; no further transitions allowed",
        )

    current_seq = STAGE_SEQUENCE[current_stage_code]

    if action == ACTION_FORWARD:
        if not to_stage_code:
            raise HTTPException(status_code=400, detail="to_stage is required for FORWARD")
        allowed = ALLOWED_FORWARD.get(current_stage_code, ())
        if to_stage_code not in allowed:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Cannot FORWARD from {current_stage_code} to {to_stage_code}. "
                    f"Allowed: {', '.join(allowed) if allowed else 'none'}"
                ),
            )
        # Q4 gate: approval is the signal the enquiry moves up the chain.
        if current_stage_code == STAGE_ENQ_NOTED and enquiry_status_id != FORWARD_GATE_STATUS_ID:
            raise HTTPException(
                status_code=403,
                detail=(
                    f"Enquiry must be Approved (status {FORWARD_GATE_STATUS_ID}) "
                    f"before it can move out of {STAGE_ENQ_NOTED}"
                ),
            )
        return

    if action == ACTION_SEND_BACK:
        if feedback is None or not str(feedback).strip():
            raise HTTPException(status_code=400, detail="feedback is mandatory for SEND_BACK")
        if not to_stage_code:
            raise HTTPException(status_code=400, detail="to_stage is required for SEND_BACK")
        if STAGE_SEQUENCE[to_stage_code] >= current_seq:
            raise HTTPException(
                status_code=400,
                detail=f"SEND_BACK target must be an earlier stage than {current_stage_code}",
            )
        return

    if action in (ACTION_HOLD, ACTION_RESUME):
        # Stage-preserving actions: target, if given, must be the current stage.
        if to_stage_code is not None and to_stage_code != current_stage_code:
            raise HTTPException(status_code=400, detail=f"{action} does not change the stage")
        return

    if action == ACTION_MARK_LOST:
        if current_seq > MARK_LOST_MAX_SEQUENCE:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"MARK_LOST is only allowed up to stage sequence {MARK_LOST_MAX_SEQUENCE} "
                    f"(before order confirmation); current stage is {current_stage_code}"
                ),
            )
        if to_stage_code is not None and to_stage_code != STAGE_LOST:
            raise HTTPException(status_code=400, detail=f"MARK_LOST must target {STAGE_LOST}")
        return

    if action == ACTION_CLOSE:
        if to_stage_code is not None and to_stage_code != STAGE_CLOSED:
            raise HTTPException(status_code=400, detail=f"CLOSE must target {STAGE_CLOSED}")
        return

    if action == ACTION_AUTO:
        # System transitions: re-log the current stage or move forward, never back.
        if not to_stage_code:
            raise HTTPException(status_code=400, detail="to_stage is required for AUTO")
        if STAGE_SEQUENCE[to_stage_code] < current_seq:
            raise HTTPException(status_code=400, detail="AUTO transitions cannot move to an earlier stage")
        return

    # ENQUIRY_ACTIONS membership makes this unreachable; kept as a safety net.
    raise HTTPException(status_code=400, detail=f"Unhandled action: {action}")


# =============================================================================
# TRANSITION WRITER
# =============================================================================

def log_stage_transition(db: Session, sales_enquiry_id, from_stage_id, to_stage_code,
                         action, feedback, linked_doc_type, linked_doc_id, user_id) -> int:
    """Append a flow_stage_log entry and keep the header stage pointer in sync.

    INSERTs flow_stage_log and, when the stage actually changes (or is set for
    the first time), UPDATEs sales_enquiry.current_stage_id + stage_since
    (now_ist()). Stage-preserving entries (HOLD / RESUME / AUTO re-logs) do NOT
    reset stage_since — days-in-stage aging keeps its anchor.

    Runs inside the caller's open transaction; the CALLER COMMITS. Does not
    re-validate the transition — call validate_transition() first for
    user-driven moves.

    Args:
        db: open tenant session (caller owns commit/rollback)
        sales_enquiry_id: flow_stage_log.doc_id
        from_stage_id: current flow_stage_mst.stage_id, or None on the CREATE entry
        to_stage_code: target stage code (resolved to stage_id here)
        action: one of ENQUIRY_ACTIONS
        feedback: feedback text or None
        linked_doc_type: one of LINKED_DOC_TYPES or None
        linked_doc_id: linked document id or None
        user_id: acting user (flow_stage_log.action_by + header audit)

    Returns:
        The resolved to_stage_id.
    """
    if action not in ENQUIRY_ACTIONS:
        raise HTTPException(status_code=400, detail=f"Invalid action: {action}")
    if linked_doc_type is not None and linked_doc_type not in LINKED_DOC_TYPE_SET:
        raise HTTPException(status_code=400, detail=f"Invalid linked_doc_type: {linked_doc_type}")

    sales_enquiry_id = int(sales_enquiry_id)
    user_id = int(user_id)
    to_stage_id = get_stage_id(db, to_stage_code)
    action_ts = now_ist()

    db.execute(insert_flow_stage_log(), {
        "doc_type": ENQUIRY_FLOW_DOC_TYPE,
        "doc_id": sales_enquiry_id,
        "from_stage_id": int(from_stage_id) if from_stage_id is not None else None,
        "to_stage_id": to_stage_id,
        "action": action,
        "feedback": feedback if feedback else None,
        "linked_doc_type": linked_doc_type,
        "linked_doc_id": int(linked_doc_id) if linked_doc_id is not None else None,
        "action_by": user_id,
        "action_date_time": action_ts,
    })

    stage_changed = from_stage_id is None or int(from_stage_id) != to_stage_id
    if stage_changed:
        db.execute(update_enquiry_current_stage(), {
            "sales_enquiry_id": sales_enquiry_id,
            "current_stage_id": to_stage_id,
            "stage_since": action_ts,
            "updated_by": user_id,
            "updated_date_time": action_ts,
        })

    return to_stage_id


# =============================================================================
# AUTOMATIC TRANSITIONS (called by quotation / sales-order approval endpoints,
# same transaction as the approval — design §4)
# =============================================================================

def advance_enquiry_on_quotation_approved(db: Session, quotation_id, user_id) -> int | None:
    """AUTO log entry on the enquiry linked to a just-approved quotation.

    Stage stays unchanged (quote sent to customer — design §4): the entry is
    written with to_stage_code = the enquiry's current stage code and
    linked_doc_type = QUOTATION.

    No-op (returns None) when the quotation has no enquiry link, or the linked
    enquiry has no current stage / is in a terminal stage. Returns the
    sales_enquiry_id when an entry was logged. Caller commits.
    """
    link_row = db.execute(
        get_quotation_enquiry_link_query(),
        {"sales_quotation_id": int(quotation_id)},
    ).fetchone()
    if not link_row:
        return None
    sales_enquiry_id = dict(link_row._mapping).get("sales_enquiry_id")
    if sales_enquiry_id is None:
        return None

    state = _get_enquiry_flow_state(db, int(sales_enquiry_id))
    current_stage_code = state.get("stage_code")
    if not current_stage_code:
        logger.warning(
            "Quotation %s approved but linked enquiry %s has no current stage; skipping AUTO log",
            quotation_id, sales_enquiry_id,
        )
        return None
    if current_stage_code in TERMINAL_STAGES:
        logger.warning(
            "Quotation %s approved but linked enquiry %s is in terminal stage %s; skipping AUTO log",
            quotation_id, sales_enquiry_id, current_stage_code,
        )
        return None

    log_stage_transition(
        db,
        sales_enquiry_id=int(sales_enquiry_id),
        from_stage_id=state.get("current_stage_id"),
        to_stage_code=current_stage_code,
        action=ACTION_AUTO,
        feedback="Quotation approved",
        linked_doc_type=LINKED_DOC_QUOTATION,
        linked_doc_id=int(quotation_id),
        user_id=user_id,
    )
    return int(sales_enquiry_id)


def advance_enquiry_on_sales_order_approved(db: Session, sales_order_id, user_id) -> int | None:
    """FORWARD the linked enquiry to ORDER_CONFIRMED when a sales order is approved.

    The enquiry is resolved via sales_order.sales_enquiry_id (direct/tender
    path — decision Q3), else via the SO's quotation ->
    sales_quotation.sales_enquiry_id. The transition is logged with action
    AUTO, linked_doc_type SALES_ORDER, feedback "Sales order approved".

    Idempotent: no-op (returns None) when no enquiry is linked, the enquiry
    has no current stage, or it is already at/past ORDER_CONFIRMED sequence
    (which also covers CLOSED and LOST). Returns the sales_enquiry_id when the
    enquiry was advanced. Caller commits.
    """
    link_row = db.execute(
        get_sales_order_enquiry_link_query(),
        {"sales_order_id": int(sales_order_id)},
    ).fetchone()
    if not link_row:
        return None
    link = dict(link_row._mapping)
    sales_enquiry_id = link.get("sales_enquiry_id") or link.get("quotation_sales_enquiry_id")
    if sales_enquiry_id is None:
        return None

    state = _get_enquiry_flow_state(db, int(sales_enquiry_id))
    current_stage_code = state.get("stage_code")
    if not current_stage_code:
        logger.warning(
            "Sales order %s approved but linked enquiry %s has no current stage; skipping AUTO advance",
            sales_order_id, sales_enquiry_id,
        )
        return None

    current_seq = STAGE_SEQUENCE.get(current_stage_code)
    if current_seq is None or current_seq >= STAGE_SEQUENCE[STAGE_ORDER_CONFIRMED]:
        # Already at/past ORDER_CONFIRMED (or terminal) — nothing to do.
        return None

    log_stage_transition(
        db,
        sales_enquiry_id=int(sales_enquiry_id),
        from_stage_id=state.get("current_stage_id"),
        to_stage_code=STAGE_ORDER_CONFIRMED,
        action=ACTION_AUTO,
        feedback="Sales order approved",
        linked_doc_type=LINKED_DOC_SALES_ORDER,
        linked_doc_id=int(sales_order_id),
        user_id=user_id,
    )
    return int(sales_enquiry_id)
